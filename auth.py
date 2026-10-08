"""Individual login accounts. Created by an admin (manage_users.py), by an
advisor for a client (create_client), or by people themselves with their
email address (sign_up - the email is the login, confirmed from an emailed
link; a forgotten password is reset the same way). A client chooses their own password from a one-time setup
link the advisor sends (create_invite / accept_invite), so no password is
ever shared.

Passwords are never stored in plain text: pbkdf2_hmac('sha256', ...) with a
per-user random salt, both stored as hex in the `users` table, with the
iteration count each hash was made with (users.password_iterations). New
hashes use PBKDF2_ITERATIONS; an older, smaller count still checks out and
is replaced at the next successful sign-in (audit 1.1b, PLAN 1b.7). No
external dependency needed - this is stdlib-only (hashlib, hmac, os), same
"standard library only" spirit as the rest of the CLI-facing code.

Signing out: a password change ends every session (the password stamp, below);
"sign out other devices" (end_other_sessions) and the admin's "sign everyone
out" (sign_out_everyone) bump a session generation number - per login
(users.session_gen) and app-wide (app_state 'session_gen'). Every run compares
both with what the tab noted at sign-in, so tabs already open are closed too,
not just the saved cookies (audit X5, PLAN 1b.2).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

import settings

# New and upgraded password hashes (audit 1.1b: about 600,000 is today's
# advice for PBKDF2-SHA256). Each users row keeps its own count.
PBKDF2_ITERATIONS = 600_000
# The count before 1b.7: rows that existed then were back-filled with it
# (portfolio._ensure_schema) and are upgraded at their next sign-in.
LEGACY_ITERATIONS = 200_000
# A local copy (the tests) may lower the count for new hashes with this
# setting, to keep a run quick. A hosted copy ignores it.
ITERATIONS_SETTING = "NORTHWEND_PBKDF2_ITERATIONS"
SESSION_DAYS = 30  # how long "stay signed in" lasts before the password is needed again
MAX_FAILED_LOGINS = 5   # wrong passwords for one username within LOCKOUT_MINUTES...
LOCKOUT_MINUTES = 15    # ...lock that username for this long
# One internet address, any usernames (audit 1.1c): this many wrong passwords
# within LOCKOUT_MINUTES pause sign-in from that address for LOCKOUT_MINUTES.
# High enough for a family or an office sharing one address; low enough that
# trying one common password against many usernames gets nowhere.
MAX_FAILED_LOGINS_PER_ADDRESS = 20
TOO_MANY_FROM_HERE = "Too many tries from here - please wait a few minutes and try again."
MIN_PASSWORD_LENGTH = 8
# an unknown username still takes one full hash (against this, at today's
# count), so how long a wrong sign-in takes doesn't say whether the account exists
_DUMMY_SALT = bytes(16)


def iterations(default: int | None = None) -> int:
    """The PBKDF2 count for a new hash: `default` (PBKDF2_ITERATIONS when not
    given), or - only on a local copy, never a hosted one - a smaller
    ITERATIONS_SETTING (the tests set it)."""
    default = default or PBKDF2_ITERATIONS
    raw = settings.get(ITERATIONS_SETTING)
    if raw and not settings.hosted():
        try:
            n = int(raw)
        except ValueError:
            return default
        if 1 <= n < default:
            return n
    return default


def _hash_password(password: str, salt: bytes, count: int | None = None) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                               count or iterations()).hex()


def create_user(conn: sqlite3.Connection, username: str, password: str) -> int:
    """Create a new account. Raises the backend's own integrity error
    (sqlite3.IntegrityError / psycopg's equivalent, both covered by
    portfolio.DBError) if `username` is already taken - after rolling back,
    so the connection can still be used (Postgres refuses every later query
    in a failed transaction: manage_users.py's bulk create carries on)."""
    salt, count = os.urandom(16), iterations()
    pw_hash = _hash_password(password, salt, count)
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, password_salt, password_iterations) "
            "VALUES (?, ?, ?, ?)", (username, pw_hash, salt.hex(), count))
    except Exception:
        conn.rollback()
        raise
    conn.commit()
    row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    return row["id"]


def verify_login(conn: sqlite3.Connection, username: str, password: str) -> int | None:
    """The user's id on a correct username/password, else None. Never
    reveals whether the username or the password was wrong (avoids
    username enumeration) - both a missing user and a wrong password just
    return None, after the same one hash (against a dummy salt for a
    missing user, so the time taken doesn't tell them apart either). A
    self-serve account's email works in any letter case.

    A right password stored with a smaller count than today's is hashed
    again at today's count (same salt, so the password stamp - and so the
    person's other open tabs - stay as they are) and saved."""
    cols = "id, password_hash, password_salt, password_iterations"
    row = conn.execute(f"SELECT {cols} FROM users WHERE username = ?", (username,)).fetchone()
    if row is None and "@" in (username or ""):
        row = conn.execute(f"SELECT {cols} FROM users WHERE email = ?",
                           (normalize_email(username),)).fetchone()
    if row is None:
        hmac.compare_digest(_hash_password(password or "", _DUMMY_SALT), "0" * 64)
        return None
    salt = bytes.fromhex(row["password_salt"])
    count = row["password_iterations"] or LEGACY_ITERATIONS
    if not hmac.compare_digest(_hash_password(password, salt, count), row["password_hash"]):
        return None
    now_count = iterations()
    if count < now_count:
        conn.execute("UPDATE users SET password_hash = ?, password_iterations = ? WHERE id = ?",
                     (_hash_password(password, salt, now_count), now_count, row["id"]))
        conn.commit()
    return row["id"]


def set_password(conn: sqlite3.Connection, username: str, new_password: str) -> bool:
    """Change an existing user's password, signing that account out of every
    browser where it stayed signed in. Returns False if no such user."""
    salt, count = os.urandom(16), iterations()
    pw_hash = _hash_password(new_password, salt, count)
    cur = conn.execute(
        "UPDATE users SET password_hash = ?, password_salt = ?, password_iterations = ? "
        "WHERE username = ?", (pw_hash, salt.hex(), count, username))
    conn.execute("DELETE FROM login_sessions WHERE user_id IN "
                 "(SELECT id FROM users WHERE username = ?)", (username,))
    conn.execute("DELETE FROM login_failures WHERE username_key = ?", (_login_key(username),))
    conn.commit()
    return cur.rowcount > 0


def change_password(conn, user_id: int, current: str, new: str, *,
                    keep_session: bool = False, now: datetime | None = None) -> dict:
    """A signed-in user changing their own password. The current password is
    checked through attempt_login(), so wrong guesses count toward the same
    lockout as the login form. On success every stay-signed-in session ends
    (set_password); with keep_session a fresh one is started for this browser.
    Returns {"ok": bool, "error": message or None, "token": new session token
    or None}."""
    def fail(msg):
        return {"ok": False, "error": msg, "token": None}

    username = get_username(conn, user_id)
    if username is None:
        return fail("Account not found.")
    if len(new or "") < MIN_PASSWORD_LENGTH:
        return fail(f"Use a new password of at least {MIN_PASSWORD_LENGTH} characters.")
    result = attempt_login(conn, username, current or "", now=now)
    if result["locked_minutes"]:
        m = result["locked_minutes"]
        return fail(f"Too many wrong passwords. Try again in {m} minute{'s' if m != 1 else ''}.")
    if result["user_id"] != user_id:
        left = result["attempts_left"]
        return fail("Your current password is wrong." + (
            f" {left} more attempt{'s' if left != 1 else ''} before a "
            f"{LOCKOUT_MINUTES}-minute lock." if left <= 2 else ""))
    # only after the current password checks out, so this can't confirm a guess
    if new == current:
        return fail("The new password must be different from the current one.")
    set_password(conn, username, new)
    token = create_session(conn, user_id, now=now) if keep_session else None
    return {"ok": True, "error": None, "token": token}


def password_stamp(conn, user_id: int) -> str | None:
    """A short fingerprint of the account's current password, or None if the
    account is gone. The dashboard notes it at sign-in and compares it on
    every run, so a password change signs out tabs already open elsewhere.
    Taken from the salt, which every new password replaces - not from the
    hash, which a sign-in can re-make at a higher count (verify_login)
    without the password changing."""
    row = conn.execute("SELECT password_salt FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        return None
    return _stamp_of(row["password_salt"])


def _stamp_of(password_salt) -> str:
    return hashlib.sha256((password_salt or "").encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# signing out tabs that are already open (audit X5, PLAN 1b.2)
# --------------------------------------------------------------------------- #
# app_state's row for the app-wide number sign_out_everyone() bumps
EVERYONE_GEN = "session_gen"
# read beside the login's own row on every run (login_facts, two_step's gate)
EVERYONE_GEN_SQL = (f"(SELECT g.number FROM app_state g WHERE g.name = '{EVERYONE_GEN}') "
                    "AS everyone_gen")


def _value(row, name):
    """row[name], or None when the row wasn't read with that column."""
    try:
        return row[name]
    except (IndexError, KeyError, ValueError):   # sqlite3.Row / dict / pgcompat.Row
        return None


def session_gen_of(row) -> str | None:
    """The session generation a tab notes at sign-in and compares on every
    run: this login's own number (users.session_gen, bumped by "sign out
    other devices") and the app-wide one (app_state, bumped by "sign
    everyone out"). None for a login that no longer exists."""
    if row is None:
        return None
    return f"{_value(row, 'session_gen') or 0}.{_value(row, 'everyone_gen') or 0}"


def session_gen(conn, user_id: int) -> str | None:
    """session_gen_of() for a login, read now."""
    return login_facts(conn, user_id)["session_gen"]


def sign_out_everyone(conn) -> int:
    """The incident switch (Admin > System, manage_users.py sign-out-all):
    every stay-signed-in session ends, and the app-wide number goes up, so
    every tab already open lands on sign-in at its next click - the admin's
    own included. Returns how many stay-signed-in sessions ended."""
    conn.execute("INSERT INTO app_state (name, number) VALUES (?, 1) "
                 "ON CONFLICT (name) DO UPDATE SET number = app_state.number + 1",
                 (EVERYONE_GEN,))
    cur = conn.execute("DELETE FROM login_sessions")
    conn.commit()
    return cur.rowcount


# What the app reads about the signed-in login on every run - its password
# stamp, session generation, roles, name, email state and AI allowance - all
# from one read of its users row (plus the app-wide sign-out number,
# EVERYONE_GEN_SQL). two_step.status_and_login reads these along with
# two-step's own state (the sign-in gate, first thing every run) and hands
# them on, so the rest of that run doesn't read the row again: login_facts_of,
# email_status_of, ai_usage.status(user=...) and the Account page.
LOGIN_COLUMNS = ("username", "password_salt", "session_gen", "is_advisor", "is_admin",
                 "terms_version", "terms_via", "email", "email_verified_at", "display_name",
                 "ai_unlimited", "created_at", "last_login_at")


def login_facts(conn, user_id: int) -> dict:
    """What the app checks about the signed-in login on every run, from one
    read of its users row: {"stamp": password_stamp(), "session_gen":
    session_gen_of(), "is_advisor": is_advisor(), "is_admin":
    admin.is_admin(), "display_name": display_name(), "agreed":
    has_agreed()} - the same answers as those, in one query."""
    row = conn.execute(f"SELECT {', '.join(LOGIN_COLUMNS)}, {EVERYONE_GEN_SQL} FROM users "
                       "WHERE id = ?", (user_id,)).fetchone()
    return login_facts_of(row)


def login_facts_of(row) -> dict:
    """login_facts() from a users row already read (LOGIN_COLUMNS, and
    everyone_gen; None for a login that no longer exists)."""
    import admin  # admin imports auth; not at the top
    if row is None:
        return {"stamp": None, "session_gen": None, "is_advisor": False, "is_admin": False,
                "display_name": None, "agreed": False}
    return {"stamp": _stamp_of(row["password_salt"]), "session_gen": session_gen_of(row),
            "is_advisor": bool(row["is_advisor"]),
            "is_admin": bool(admin._admin_row(row, admin.listed_admins())),
            "display_name": row["display_name"] or None,
            "agreed": bool(row["terms_version"])}


# --------------------------------------------------------------------------- #
# agreeing to the About and disclosures
# --------------------------------------------------------------------------- #
# Everyone agrees once, and the version agreed to is kept with the time
# (users.terms_version, terms_accepted_at), next to the two confirmations
# asked with it, each with its own time (decision D10): 18 or older
# (age_confirmed_at) and living in the United States (us_resident_at). At sign-up (sign_up), at a client's
# setup link (accept_invite), or - for an account an advisor or admin made
# that got in some other way - once at their next sign-in (record_agreement).
# terms_via says where when it wasn't sign-up. NULL means sign-up, so an
# account that made itself is still told apart from one an admin or advisor
# made (made_by_themselves: admin.py, proposals.who_to_tell, weekly_email).
# Accounts that agreed before the two confirmations had fields of their own
# have them NULL (their 18+ box was part of that agreement) and aren't asked
# again.
TERMS_VIA_SETUP_LINK = "setup link"
TERMS_VIA_SIGN_IN = "sign-in"


def made_by_themselves(row) -> bool:
    """Whether a users row (with terms_version and terms_via) came from
    self-serve sign-up, rather than from an admin or an advisor."""
    return bool(row["terms_version"]) and not row["terms_via"]


def has_agreed(conn, user_id: int) -> bool:
    """Whether this login has agreed to the About and disclosures (any version)."""
    row = conn.execute("SELECT terms_version FROM users WHERE id = ?", (user_id,)).fetchone()
    return bool(row and row["terms_version"])


def agreement_error(*, agreed: bool, adult: bool, us_resident: bool) -> str | None:
    """What's missing from the three checkboxes (as at sign-up), or None."""
    if not adult:
        return "Accounts are for people 18 and over - tick the box to confirm."
    if not us_resident:
        return ("For now Northwend is for people who live in the United States - tick the "
                "box to confirm.")
    if not agreed:
        return ("Tick the box to agree to the Terms of Use, Privacy Policy and About and "
                "disclosures.")
    return None


def record_agreement(conn, user_id: int, terms_version: str, *, via: str,
                     now: datetime | None = None, commit: bool = True) -> None:
    """Keep that this login agreed to `terms_version` of the disclosures, and
    when - for an account that didn't come through sign-up (`via`:
    TERMS_VIA_SETUP_LINK or TERMS_VIA_SIGN_IN). An account that had already
    agreed keeps where it first did. The caller asked all three boxes
    (agreement_error), so the 18+ and US-residency confirmations are kept
    with the same time (age_confirmed_at, us_resident_at - D10)."""
    if not terms_version:
        raise ValueError("which version of the disclosures was agreed to?")
    stamp = _utc(now or datetime.now(timezone.utc))
    conn.execute("UPDATE users SET terms_via = CASE WHEN terms_version IS NULL THEN ? "
                 "ELSE terms_via END, terms_version = ?, terms_accepted_at = ?, "
                 "age_confirmed_at = ?, us_resident_at = ? WHERE id = ?",
                 (via, terms_version, stamp, stamp, stamp, user_id))
    if commit:
        conn.commit()


# --------------------------------------------------------------------------- #
# failed-login lockout
# --------------------------------------------------------------------------- #
def _login_key(username: str | None) -> str:
    """The lockout's key for a typed username: case-folded (so 'Alice' and
    'alice' share one count) and hashed (so what people typed isn't stored)."""
    return hashlib.sha256((username or "").strip().casefold().encode("utf-8")).hexdigest()


def _failures_row(conn, key: str):
    return conn.execute("SELECT failures, window_start, locked_until FROM login_failures "
                        "WHERE username_key = ?", (key,)).fetchone()


def _minutes_locked(row, now: datetime) -> int:
    """Minutes left on a login_failures row's lock (0 when it has none)."""
    if not (row and row["locked_until"] and row["locked_until"] > _utc(now)):
        return 0
    left = datetime.strptime(row["locked_until"], "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=timezone.utc) - now
    return max(1, -(-int(left.total_seconds()) // 60))


def _count_failure(conn, key: str, row, now: datetime, limit: int) -> tuple[int, bool]:
    """One more wrong password on `key` (a login_failures row, `row` as read):
    (failures in this window, whether that reached `limit` and locked it)."""
    stamp = _utc(now)
    window_open = _utc(now - timedelta(minutes=LOCKOUT_MINUTES))
    fresh = row is None or row["window_start"] <= window_open or row["locked_until"]
    failures = 1 if fresh else row["failures"] + 1
    locked_until = (_utc(now + timedelta(minutes=LOCKOUT_MINUTES))
                    if failures >= limit else None)
    conn.execute("DELETE FROM login_failures WHERE username_key = ?", (key,))
    conn.execute("INSERT INTO login_failures (username_key, failures, window_start, locked_until) "
                 "VALUES (?, ?, ?, ?)",
                 (key, failures, stamp if fresh else row["window_start"], locked_until))
    return failures, locked_until is not None


def attempt_login(conn, username: str, password: str, *, ip: str | None = None,
                  now: datetime | None = None) -> dict:
    """verify_login() behind the lockout. Returns {"user_id": id or None,
    "locked_minutes": minutes left on a lock (0 if none), "attempts_left":
    wrong passwords left before a lock, "from_here": True when it's the
    visitor's address that's paused}. A locked username is refused
    without checking the password - even the right one. Unknown usernames
    are counted and locked exactly like real ones.

    `ip` (the sign-in form's visitor) also counts wrong passwords per
    internet address, across any usernames: MAX_FAILED_LOGINS_PER_ADDRESS
    within LOCKOUT_MINUTES pause sign-in from there (key "addr:" + the
    hashed address, as the sign-up limits keep it). A right password doesn't
    clear that count. Without an address (a local run) only the username
    lock applies - nobody is locked out together."""
    now = now or datetime.now(timezone.utc)
    key, stamp = _login_key(username), _utc(now)
    addr = ("addr:" + _address_key(ip)) if ip else ""
    addr_row = _failures_row(conn, addr) if addr else None
    if _minutes_locked(addr_row, now):
        return {"user_id": None, "locked_minutes": _minutes_locked(addr_row, now),
                "attempts_left": 0, "from_here": True}
    row = _failures_row(conn, key)
    if _minutes_locked(row, now):
        return {"user_id": None, "locked_minutes": _minutes_locked(row, now),
                "attempts_left": 0, "from_here": False}

    user_id = verify_login(conn, username, password) if username and password else None
    if user_id is not None:
        conn.execute("DELETE FROM login_failures WHERE username_key = ?", (key,))
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (stamp, user_id))
        conn.commit()
        return {"user_id": user_id, "locked_minutes": 0, "attempts_left": MAX_FAILED_LOGINS,
                "from_here": False}

    failures, locked = _count_failure(conn, key, row, now, MAX_FAILED_LOGINS)
    from_here = False
    if addr:
        _, from_here = _count_failure(conn, addr, addr_row, now, MAX_FAILED_LOGINS_PER_ADDRESS)
    # tidy: counts nobody has added to in a day, and locks that have run out
    conn.execute("DELETE FROM login_failures WHERE window_start < ? "
                 "AND (locked_until IS NULL OR locked_until < ?)",
                 (_utc(now - timedelta(days=1)), stamp))
    conn.commit()
    if from_here:
        return {"user_id": None, "locked_minutes": LOCKOUT_MINUTES, "attempts_left": 0,
                "from_here": True}
    return {"user_id": None, "locked_minutes": LOCKOUT_MINUTES if locked else 0,
            "attempts_left": max(0, MAX_FAILED_LOGINS - failures), "from_here": False}


def unlock_login(conn, username: str) -> bool:
    """Clear a username's failed logins and any lock. True if there was one."""
    cur = conn.execute("DELETE FROM login_failures WHERE username_key = ?", (_login_key(username),))
    conn.commit()
    return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# stay signed in
# --------------------------------------------------------------------------- #
def _token_hash(token: str) -> str:
    # Tokens are 256 random bits, so a plain SHA-256 (no salt, no stretching)
    # is enough to make the stored value useless for signing in.
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def create_session(conn, user_id: int, *, now: datetime | None = None) -> str:
    """Start a stay-signed-in session and return its token, for the browser's
    cookie. Only the token's hash is stored. Also clears this user's expired
    sessions."""
    now = now or datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM login_sessions WHERE user_id = ? AND expires_at <= ?",
                 (user_id, _utc(now)))
    conn.execute("INSERT INTO login_sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                 (_token_hash(token), user_id, _utc(now + timedelta(days=SESSION_DAYS))))
    conn.commit()
    return token


def session_user(conn, token: str | None, *, now: datetime | None = None) -> tuple[int, str] | None:
    """(user_id, username) for a live session token, else None - for an
    unknown, expired, or signed-out token alike."""
    if not token:
        return None
    now = now or datetime.now(timezone.utc)
    row = conn.execute(
        "SELECT u.id, u.username FROM login_sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ? AND s.expires_at > ?", (_token_hash(token), _utc(now))).fetchone()
    if row:  # a stay-signed-in return counts as signing in (the admin portal shows it)
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (_utc(now), row["id"]))
        conn.commit()
    return (row["id"], row["username"]) if row else None


def end_session(conn, token: str | None) -> None:
    """Sign one browser out (its cookie stops working even if it's kept)."""
    if token:
        conn.execute("DELETE FROM login_sessions WHERE token_hash = ?", (_token_hash(token),))
        conn.commit()


INVITE_DAYS = 7  # how long a setup link works, if it isn't used first


def create_invite(conn, advisor_id: int, client_id: int, *,
                  now: datetime | None = None) -> str:
    """A one-time setup link token for one of `advisor_id`'s clients: the
    client opens it and chooses their own password (accept_invite), so the
    advisor never sets or shares one. A new link replaces any earlier one
    for that client. Only the token's hash is stored. Raises ValueError if
    `client_id` isn't this advisor's client."""
    if advisor_id == client_id or not can_view(conn, advisor_id, client_id):
        raise ValueError("you can only invite your own clients")
    now = now or datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM invites WHERE user_id = ? OR expires_at <= ?",
                 (client_id, _utc(now)))
    conn.execute("INSERT INTO invites (token_hash, user_id, created_by, created_at, expires_at) "
                 "VALUES (?, ?, ?, ?, ?)",
                 (_token_hash(token), client_id, advisor_id, _utc(now),
                  _utc(now + timedelta(days=INVITE_DAYS))))
    conn.commit()
    return token


def invite_info(conn, token: str | None, *, now: datetime | None = None) -> dict | None:
    """{"user_id", "username", "expires_at", "advisor_id" (who made it)} for
    a live setup link, else None (unknown, expired or already used alike)."""
    if not token:
        return None
    now = now or datetime.now(timezone.utc)
    row = conn.execute(
        "SELECT i.user_id, u.username, i.expires_at, i.created_by AS advisor_id "
        "FROM invites i JOIN users u ON u.id = i.user_id "
        "WHERE i.token_hash = ? AND i.expires_at > ?", (_token_hash(token), _utc(now))).fetchone()
    return dict(row) if row else None


def pending_invite(conn, client_id: int, *, now: datetime | None = None) -> str | None:
    """When the client's unused setup link expires ('YYYY-MM-DD HH:MM:SS'
    UTC), or None if there isn't one."""
    now = now or datetime.now(timezone.utc)
    row = conn.execute("SELECT expires_at FROM invites WHERE user_id = ? AND expires_at > ?",
                       (client_id, _utc(now))).fetchone()
    return row["expires_at"] if row else None


def cancel_invite(conn, client_id: int) -> None:
    conn.execute("DELETE FROM invites WHERE user_id = ?", (client_id,))
    conn.commit()


def accept_invite(conn, token: str, password: str, *, agreed: bool = False,
                  adult: bool = False, us_resident: bool = False,
                  terms_version: str | None = None, consent_text: str | None = None,
                  now: datetime | None = None) -> dict:
    """The client sets their password from a setup link and agrees to the
    About and disclosures, as at sign-up: `agreed` / `adult` / `us_resident`
    are the form's three checkboxes and `terms_version` the version agreed to (kept with the
    time - record_agreement), all required. The link is used up (it can't
    set the password again), and any other sign-ins of that account end.
    While they're still that advisor's client, a consent grant is recorded
    with the sharing words the page showed (`consent_text`; by default
    consent.setup_link_text for this advisor). Returns {"ok", "error",
    "user_id", "username"}."""
    info = invite_info(conn, token, now=now)
    if info is None:
        return {"ok": False, "error": "This setup link has expired or was already used. "
                "Ask your advisor for a new one.", "user_id": None, "username": None}
    if len(password) < MIN_PASSWORD_LENGTH:
        return {"ok": False, "error": f"Use a password of at least {MIN_PASSWORD_LENGTH} "
                "characters.", "user_id": None, "username": None}
    missing = agreement_error(agreed=agreed and bool(terms_version), adult=adult,
                              us_resident=us_resident)
    if missing:
        return {"ok": False, "error": missing, "user_id": None, "username": None}
    record_agreement(conn, info["user_id"], terms_version, via=TERMS_VIA_SETUP_LINK,
                     now=now, commit=False)   # set_password below commits it all
    advisor_id = info.get("advisor_id")
    if advisor_id and conn.execute("SELECT 1 FROM advisor_clients WHERE advisor_id = ? AND "
                                   "client_id = ?", (advisor_id, info["user_id"])).fetchone():
        import consent
        consent.grant(conn, info["user_id"], advisor_id,
                      consent_text or consent.setup_link_text(
                          consent.advisor_label(conn, advisor_id)),
                      "setup_link", now=now, commit=False)
    conn.execute("DELETE FROM invites WHERE user_id = ?", (info["user_id"],))
    stamp = _utc(now or datetime.now(timezone.utc))
    # an email the advisor gave counts as confirmed once the client is in
    conn.execute("UPDATE users SET email_verified_at = COALESCE(email_verified_at, ?) "
                 "WHERE id = ? AND email IS NOT NULL", (stamp, info["user_id"]))
    # they're signed in straight away, so this counts as their first sign-in
    conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (stamp, info["user_id"]))
    set_password(conn, info["username"], password)  # commits all of it
    return {"ok": True, "error": None, "user_id": info["user_id"], "username": info["username"]}


# --------------------------------------------------------------------------- #
# self-serve sign-up
# --------------------------------------------------------------------------- #
# Bot protection without an outside service: a hidden field people never see
# (filled in = a bot), a form sent faster than a person could, and limits on
# how many accounts one internet address - and the whole app - can make.
SIGNUP_MIN_SECONDS = 3            # a form sent sooner than this is asked again
SIGNUPS_PER_ADDRESS_PER_DAY = 3   # accounts made from one internet address
SIGNUP_TRIES_PER_ADDRESS_PER_HOUR = 10  # any sign-up tries from one address
SIGNUPS_PER_HOUR = 200            # accounts made app-wide, in case addresses are hidden
                                  # (20 until the launch: room for a busy hour, still a stop)
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def valid_email(email: str) -> bool:
    return len(email or "") <= 254 and bool(_EMAIL_RE.match(email or ""))


def _address_key(ip: str | None) -> str:
    """The rate limit's key for an internet address: hashed, so the address
    itself isn't stored, and '' when it isn't known (only the app-wide
    limit applies then)."""
    return hashlib.sha256(ip.encode("utf-8")).hexdigest() if ip else ""


def invite_only() -> bool:
    """Whether Create account needs an invite code: while gate L0 is off
    (flags.py; docs/LEGAL_GATES.md). Setup links, admin-made accounts and
    signing in never do."""
    import flags
    return not flags.gate("L0")


def sign_up(conn, email: str, password: str, *, agreed: bool, adult: bool,
            us_resident: bool = False, terms_version: str, ip: str | None = None,
            seconds_open: float = 0, honeypot: str = "", invite_code: str | None = None,
            needs_code: bool | None = None, now: datetime | None = None) -> dict:
    """Create an account from the sign-up form: the email (lower-cased) is
    both the login and the address, not yet confirmed. `agreed` / `adult` /
    `us_resident` are the form's three checkboxes; `terms_version` is the
    disclosures version agreed to (stored with the time, as are the two
    confirmations). `seconds_open` is how long the form was on screen and
    `honeypot` the hidden field. `needs_code` (default invite_only(): gate
    L0 off) asks for `invite_code`, one the admin made (invite_codes.py),
    used up with the account. Returns {"ok", "error", "user_id",
    "username"}."""
    import invite_codes
    def fail(msg):
        return {"ok": False, "error": msg, "user_id": None, "username": None}

    now = now or datetime.now(timezone.utc)
    stamp, key = _utc(now), _address_key(ip)
    email = normalize_email(email)
    conn.execute("DELETE FROM signups WHERE created_at < ?", (_utc(now - timedelta(days=1)),))
    conn.commit()
    if honeypot:  # only a bot fills in a field nobody can see; say nothing useful
        _note_signup(conn, key, stamp, ok=False)
        return fail("Something went wrong. Please try again in a little while.")
    if not valid_email(email):
        return fail("Enter your email address, like name@example.com.")
    if len(password or "") < MIN_PASSWORD_LENGTH:
        return fail(f"Use a password of at least {MIN_PASSWORD_LENGTH} characters.")
    if needs_code is None:
        needs_code = invite_only()
    if needs_code and not invite_codes.normalize(invite_code):
        return fail(invite_codes.NEED_CODE)
    missing = agreement_error(agreed=agreed, adult=adult, us_resident=us_resident)
    if missing:
        return fail(missing)

    hour_ago, day_ago = _utc(now - timedelta(hours=1)), _utc(now - timedelta(days=1))
    if key:
        tries = conn.execute("SELECT COUNT(*) AS n FROM signups WHERE address_key = ? "
                             "AND created_at >= ?", (key, hour_ago)).fetchone()["n"]
        made = conn.execute("SELECT COUNT(*) AS n FROM signups WHERE address_key = ? "
                            "AND ok = 1 AND created_at >= ?", (key, day_ago)).fetchone()["n"]
        if tries >= SIGNUP_TRIES_PER_ADDRESS_PER_HOUR or made >= SIGNUPS_PER_ADDRESS_PER_DAY:
            return fail("Too many new accounts from here for now. Please try again tomorrow.")
    recent = conn.execute("SELECT COUNT(*) AS n FROM signups WHERE ok = 1 AND created_at >= ?",
                          (hour_ago,)).fetchone()["n"]
    if recent >= SIGNUPS_PER_HOUR:
        return fail("Lots of people are signing up right now. Please try again in an hour.")
    if seconds_open < SIGNUP_MIN_SECONDS:
        return fail("That was quick! Check your details and press Create account again.")

    # a wrong code counts as a try, so codes can't be guessed quickly
    if needs_code and not invite_codes.usable(conn, invite_code):
        _note_signup(conn, key, stamp, ok=False)
        return fail(invite_codes.NOT_WORKING)
    taken = conn.execute("SELECT 1 FROM users WHERE lower(username) = ? OR email = ?",
                         (email, email)).fetchone()
    if taken:  # counted, so the form can't be used to check many emails quickly
        _note_signup(conn, key, stamp, ok=False)
        return fail("There's already an account with this email. Sign in instead.")
    if needs_code and not invite_codes.claim(conn, invite_code, stamp):
        conn.rollback()   # used by someone else a moment ago
        _note_signup(conn, key, stamp, ok=False)
        return fail(invite_codes.NOT_WORKING)
    user_id = create_user(conn, email, password)   # commits the claim with it
    conn.execute("UPDATE users SET email = ?, terms_version = ?, terms_accepted_at = ?, "
                 "age_confirmed_at = ?, us_resident_at = ? WHERE id = ?",
                 (email, terms_version, stamp, stamp, stamp, user_id))
    if needs_code:
        invite_codes.record_user(conn, invite_code, user_id, stamp)
    _note_signup(conn, key, stamp, ok=True)
    return {"ok": True, "error": None, "user_id": user_id, "username": email}


def _note_signup(conn, key: str, stamp: str, *, ok: bool) -> None:
    conn.execute("INSERT INTO signups (address_key, created_at, ok) VALUES (?, ?, ?)",
                 (key, stamp, 1 if ok else 0))
    conn.commit()


# --------------------------------------------------------------------------- #
# email links: confirming the address, resetting a password (mailer.py sends)
# --------------------------------------------------------------------------- #
CONFIRM_DAYS = 3            # how long a confirm-your-email link works
RESET_MINUTES = 60          # how long a reset-your-password link works
CONFIRM_GAP_MINUTES = 2     # "send it again" waits this long after the last one
CONFIRMS_PER_DAY = 5        # confirm emails to one address a day
RESETS_PER_EMAIL_PER_HOUR = 3
EMAILS_PER_ADDRESS_PER_HOUR = 10  # any of these emails asked for from one internet address


def _email_key(email: str) -> str:
    """The send limits' key for an email address: hashed, so the limits
    don't keep the addresses people type."""
    return hashlib.sha256(normalize_email(email).encode("utf-8")).hexdigest()


def _email_limit(conn, purpose: str, email: str, ip: str | None, now: datetime) -> str | None:
    """Why another `purpose` email can't go out now, or None if it can. The
    request is counted either way (it's keyed on what was typed, so a limit
    says nothing about whether an account exists). Counts older than a day
    are tidied away."""
    stamp, ekey, akey = _utc(now), _email_key(email), _address_key(ip)
    hour_ago = _utc(now - timedelta(hours=1))
    conn.execute("DELETE FROM email_sends WHERE sent_at < ?", (_utc(now - timedelta(days=1)),))
    rows = conn.execute("SELECT sent_at FROM email_sends WHERE email_key = ? AND purpose = ? "
                        "ORDER BY sent_at DESC", (ekey, purpose)).fetchall()
    from_here = conn.execute("SELECT COUNT(*) AS n FROM email_sends WHERE address_key = ? "
                             "AND sent_at >= ?", (akey, hour_ago)).fetchone()["n"] if akey else 0
    reason = None
    if from_here >= EMAILS_PER_ADDRESS_PER_HOUR:
        reason = "Too many emails asked for from here. Please try again in an hour."
    elif purpose in ("confirm", "change"):
        if rows and rows[0]["sent_at"] > _utc(now - timedelta(minutes=CONFIRM_GAP_MINUTES)):
            reason = ("We just sent one - check your inbox and spam folder. You can send "
                      "another in a couple of minutes.")
        elif len(rows) >= CONFIRMS_PER_DAY:
            reason = "That's a lot of emails for one day. Please try again tomorrow."
    elif purpose == "reset":
        if sum(r["sent_at"] >= hour_ago for r in rows) >= RESETS_PER_EMAIL_PER_HOUR:
            reason = ("We've sent a few reset emails already - check your inbox and spam "
                      "folder, or try again in an hour.")
    if reason is None:
        conn.execute("INSERT INTO email_sends (email_key, address_key, purpose, sent_at) "
                     "VALUES (?, ?, ?, ?)", (ekey, akey, purpose, stamp))
    conn.commit()
    return reason


def send_failed(conn, purpose: str, email: str) -> None:
    """The `purpose` email to `email` that _email_limit just counted didn't go
    (Resend refused it - on a busy day, its daily allowance - or couldn't be
    reached): take that count back, so "Send it again" doesn't answer "we just
    sent one" for an email that never left, and a failed send doesn't use up
    the day's emails. Only the newest count for that address and purpose."""
    ekey = _email_key(email)
    conn.execute("DELETE FROM email_sends WHERE email_key = ? AND purpose = ? AND sent_at = "
                 "(SELECT MAX(sent_at) FROM email_sends WHERE email_key = ? AND purpose = ?)",
                 (ekey, purpose, ekey, purpose))
    conn.commit()


# Emails an advisor's clicks send (setup links, "there's a message / report /
# proposal for you"): limits so no amount of clicking - a double click, a
# reload, or someone using an advisor's login - can send without end.
INVITE_GAP_MINUTES = 2            # a setup link to the same address again
INVITES_PER_ADDRESS_PER_DAY = 5   # setup links to one address a day
INVITES_PER_ADVISOR_PER_DAY = 50  # setup links one advisor sends a day, to anyone
NOTICE_GAP_MINUTES = 60           # one "something's waiting" email of a kind an hour


def _sends(conn, now: datetime, **where) -> list:
    """email_sends rows (newest first) matching `where` (column = value),
    after tidying away those older than a day."""
    conn.execute("DELETE FROM email_sends WHERE sent_at < ?", (_utc(now - timedelta(days=1)),))
    cols = " AND ".join(f"{k} = ?" for k in where)
    return conn.execute(f"SELECT sent_at FROM email_sends WHERE {cols} ORDER BY sent_at DESC",
                        tuple(where.values())).fetchall()


def invite_email_limit(conn, advisor_id: int, email: str, *,
                       now: datetime | None = None) -> str | None:
    """Why another setup link can't be emailed to `email` now, or None (and
    it's counted). The advisor is counted under their own key, so the
    whole day's invites are capped too."""
    now = now or datetime.now(timezone.utc)
    ekey, akey = _email_key(email), _address_key(f"advisor:{advisor_id}")
    to_them = _sends(conn, now, email_key=ekey, purpose="invite")
    by_advisor = _sends(conn, now, address_key=akey, purpose="invite")
    reason = None
    if to_them and to_them[0]["sent_at"] > _utc(now - timedelta(minutes=INVITE_GAP_MINUTES)):
        reason = ("A setup link went to this address a moment ago - give it a couple of "
                  "minutes to arrive (it can land in spam).")
    elif len(to_them) >= INVITES_PER_ADDRESS_PER_DAY:
        reason = "That's a lot of setup links to one address for one day. Try again tomorrow."
    elif len(by_advisor) >= INVITES_PER_ADVISOR_PER_DAY:
        reason = (f"You've sent {INVITES_PER_ADVISOR_PER_DAY} setup links today - that's the "
                  "daily limit. Try again tomorrow, or create a link to send yourself.")
    if reason is None:
        conn.execute("INSERT INTO email_sends (email_key, address_key, purpose, sent_at) "
                     "VALUES (?, ?, 'invite', ?)", (ekey, akey, _utc(now)))
    conn.commit()
    return reason


def invites_left_today(conn, advisor_id: int, *, now: datetime | None = None) -> int:
    """How many more setup links this advisor can email today
    (INVITES_PER_ADVISOR_PER_DAY, counted by invite_email_limit)."""
    now = now or datetime.now(timezone.utc)
    sent = _sends(conn, now, address_key=_address_key(f"advisor:{advisor_id}"), purpose="invite")
    conn.commit()
    return max(0, INVITES_PER_ADVISOR_PER_DAY - len(sent))


# Adding clients from a file (client_csv.review) says which addresses already
# have a Northwend account - as Add client does, one at a time, when it can't
# make the account. So a file can't check addresses faster than that, each
# advisor may look up this many NEW addresses a day (the same address again
# is free; their own clients aren't looked up). One full file's worth.
CLIENT_CHECKS_PER_DAY = 200


def client_checks_allowed(conn, advisor_id: int, emails, *,
                          now: datetime | None = None) -> set:
    """Which of `emails` (normalized) may be checked for an existing account
    now: those already checked today, then new ones up to
    CLIENT_CHECKS_PER_DAY - each new one is counted (hashed, kept a day)."""
    now = now or datetime.now(timezone.utc)
    akey = _address_key(f"advisor:{advisor_id}")
    _sends(conn, now, address_key=akey, purpose="client_check")   # tidies a day's old ones
    seen = {r["email_key"] for r in conn.execute(
        "SELECT email_key FROM email_sends WHERE address_key = ? AND purpose = 'client_check'",
        (akey,))}
    allowed, stamp = set(), _utc(now)
    for email in dict.fromkeys(emails):
        key = _email_key(email)
        if key not in seen:
            if len(seen) >= CLIENT_CHECKS_PER_DAY:
                continue
            seen.add(key)
            conn.execute("INSERT INTO email_sends (email_key, address_key, purpose, sent_at) "
                         "VALUES (?, ?, 'client_check', ?)", (key, akey, stamp))
        allowed.add(email)
    conn.commit()
    return allowed


def notice_ok(conn, purpose: str, email: str, *, now: datetime | None = None) -> bool:
    """Whether a "something's waiting for you" email (`purpose`: 'message',
    'report', 'proposal', 'answer') may go to `email` now: at most one of a
    kind every NOTICE_GAP_MINUTES. True counts it. What it's about is still
    saved and shown in the app either way - only the email waits."""
    now = now or datetime.now(timezone.utc)
    ekey = _email_key(email)
    rows = _sends(conn, now, email_key=ekey, purpose=purpose)
    if rows and rows[0]["sent_at"] > _utc(now - timedelta(minutes=NOTICE_GAP_MINUTES)):
        conn.commit()
        return False
    conn.execute("INSERT INTO email_sends (email_key, address_key, purpose, sent_at) "
                 "VALUES (?, '', ?, ?)", (ekey, purpose, _utc(now)))
    conn.commit()
    return True


def _create_email_token(conn, user_id: int, purpose: str, email: str, now: datetime,
                        life: timedelta | None = None) -> str:
    """A one-time link token; replaces this account's earlier one for the same
    purpose. Only its hash is stored."""
    token = secrets.token_urlsafe(32)
    life = life or (timedelta(days=CONFIRM_DAYS) if purpose in ("confirm", "change")
                    else timedelta(minutes=RESET_MINUTES))
    conn.execute("DELETE FROM email_tokens WHERE (user_id = ? AND purpose = ?) OR expires_at <= ?",
                 (user_id, purpose, _utc(now)))
    conn.execute("INSERT INTO email_tokens (token_hash, user_id, purpose, email, created_at, "
                 "expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                 (_token_hash(token), user_id, purpose, email, _utc(now), _utc(now + life)))
    conn.commit()
    return token


def _email_token(conn, token: str | None, purpose: str, now: datetime) -> dict | None:
    """{"user_id", "username", "email"} for a live link whose email is still
    the account's, else None (unknown, expired, used, or the email changed)."""
    if not token:
        return None
    row = conn.execute(
        "SELECT t.user_id, u.username, u.email FROM email_tokens t JOIN users u ON u.id = t.user_id "
        "WHERE t.token_hash = ? AND t.purpose = ? AND t.expires_at > ? AND t.email = u.email",
        (_token_hash(token), purpose, _utc(now))).fetchone()
    return dict(row) if row else None


def email_status(conn, user_id: int) -> dict:
    """{"email": the account's email or None, "confirmed": bool}. Accounts made
    by an admin or advisor have no email."""
    row = conn.execute("SELECT email, email_verified_at FROM users WHERE id = ?",
                       (user_id,)).fetchone()
    return email_status_of(row)


def email_status_of(row) -> dict:
    """email_status() from a users row already read (LOGIN_COLUMNS)."""
    return {"email": row["email"] if row else None,
            "confirmed": bool(row and row["email_verified_at"])}


def start_confirmation(conn, user_id: int, *, ip: str | None = None,
                       now: datetime | None = None) -> dict:
    """A confirm-your-email link for this account's (unconfirmed) email.
    Returns {"ok", "error", "to", "token"}; the caller emails the link."""
    now = now or datetime.now(timezone.utc)
    st_ = email_status(conn, user_id)
    if not st_["email"] or st_["confirmed"]:
        return {"ok": False, "error": "There's no email waiting to be confirmed.",
                "to": None, "token": None}
    reason = _email_limit(conn, "confirm", st_["email"], ip, now)
    if reason:
        return {"ok": False, "error": reason, "to": None, "token": None}
    return {"ok": True, "error": None, "to": st_["email"],
            "token": _create_email_token(conn, user_id, "confirm", st_["email"], now)}


CONFIRMED_LINK = "confirmed"   # email_tokens.purpose of a confirm link already used


def confirm_email(conn, token: str, *, now: datetime | None = None) -> dict:
    """Open a confirm link: the email is marked confirmed and the link used
    up. The same link opened again within a day (a reload, or an address that
    kept it) answers ok with "already": True - not "expired". Returns {"ok",
    "error", "user_id", "email", "already"}."""
    now = now or datetime.now(timezone.utc)
    info = _email_token(conn, token, "confirm", now)
    if info is None:
        # the same link opened again - a reload, an address that kept
        # ?confirm=, signing in after opening it: it did its job, so say so
        # rather than "expired" (kept as 'confirmed' for a day, below)
        done = _email_token(conn, token, CONFIRMED_LINK, now)
        if done is not None and email_status(conn, done["user_id"])["confirmed"]:
            return {"ok": True, "error": None, "user_id": done["user_id"],
                    "email": done["email"], "already": True}
        return {"ok": False, "user_id": None, "email": None,
                "error": "This link has expired or was already used."}
    conn.execute("UPDATE users SET email_verified_at = COALESCE(email_verified_at, ?) "
                 "WHERE id = ?", (_utc(now), info["user_id"]))
    conn.execute("DELETE FROM email_tokens WHERE user_id = ? AND purpose IN ('confirm', ?) "
                 "AND token_hash != ?", (info["user_id"], CONFIRMED_LINK, _token_hash(token)))
    # used up: it can't confirm anything again, but opening it again is recognised
    conn.execute("UPDATE email_tokens SET purpose = ?, expires_at = ? WHERE token_hash = ?",
                 (CONFIRMED_LINK, _utc(now + timedelta(days=1)), _token_hash(token)))
    conn.commit()
    return {"ok": True, "error": None, "user_id": info["user_id"], "email": info["email"],
            "already": False}


# ---- the Account page: name, email, sessions -------------------------------- #
NAME_MAX = 60


def display_name(conn, user_id: int) -> str | None:
    """The name this person chose to be called (Account page), or None."""
    row = conn.execute("SELECT display_name FROM users WHERE id = ?", (user_id,)).fetchone()
    return (row["display_name"] or None) if row else None


def set_display_name(conn, user_id: int, name: str | None) -> None:
    """Blank clears it. Only shown in the app (to them and their advisor)."""
    name = " ".join((name or "").split())[:NAME_MAX] or None
    conn.execute("UPDATE users SET display_name = ? WHERE id = ?", (name, user_id))
    conn.commit()


def _email_taken(conn, email: str, user_id: int) -> bool:
    row = conn.execute("SELECT 1 FROM users WHERE id != ? AND (email = ? OR LOWER(username) = ?) "
                       "LIMIT 1", (user_id, email, email)).fetchone()
    return row is not None


def start_email_change(conn, user_id: int, new_email: str, password: str, *,
                       ip: str | None = None, now: datetime | None = None) -> dict:
    """Change (or add) the account's email: the password is checked (wrong
    guesses count toward the lock), then a confirm link goes to the NEW
    address; nothing changes until it's opened. Returns {"ok", "error",
    "to", "token"}; the caller emails the link."""
    now = now or datetime.now(timezone.utc)

    def fail(msg):
        return {"ok": False, "error": msg, "to": None, "token": None}

    username = get_username(conn, user_id)
    if username is None:
        return fail("Account not found.")
    new_email = normalize_email(new_email)
    if not valid_email(new_email):
        return fail("Enter the new email address, like name@example.com.")
    result = attempt_login(conn, username, password or "", now=now)
    if result["locked_minutes"]:
        m = result["locked_minutes"]
        return fail(f"Too many wrong passwords. Try again in {m} minute{'s' if m != 1 else ''}.")
    if result["user_id"] != user_id:
        return fail("Your password is wrong.")
    if new_email == (email_status(conn, user_id)["email"] or ""):
        return fail("That's already your email.")
    if _email_taken(conn, new_email, user_id):
        # it can't be used, but don't say whose it is
        return fail("That email can't be used for this account. Try another, or contact us.")
    reason = _email_limit(conn, "change", new_email, ip, now)
    if reason:
        return fail(reason)
    return {"ok": True, "error": None, "to": new_email,
            "token": _create_email_token(conn, user_id, "change", new_email, now)}


def pending_email_change(conn, user_id: int, *, now: datetime | None = None) -> str | None:
    """A new email waiting for its confirm link, or None."""
    now = now or datetime.now(timezone.utc)
    row = conn.execute("SELECT email FROM email_tokens WHERE user_id = ? AND purpose = 'change' "
                       "AND expires_at > ?", (user_id, _utc(now))).fetchone()
    return row["email"] if row else None


def cancel_email_change(conn, user_id: int) -> None:
    conn.execute("DELETE FROM email_tokens WHERE user_id = ? AND purpose = 'change'", (user_id,))
    conn.commit()


def confirm_email_change(conn, token: str, *, now: datetime | None = None) -> dict:
    """Open a change-email link: the new address becomes the account's
    (confirmed), and - for an account that signs in with its email - its
    login too. Earlier links to the old address stop working. Returns {"ok",
    "error", "user_id", "email", "old_email", "username"}."""
    now = now or datetime.now(timezone.utc)
    out = {"ok": False, "error": "This link has expired or was already used.", "user_id": None,
           "email": None, "old_email": None, "username": None}
    if not token:
        return out
    row = conn.execute(
        "SELECT t.user_id, t.email AS new_email, u.username, u.email AS old_email "
        "FROM email_tokens t JOIN users u ON u.id = t.user_id WHERE t.token_hash = ? AND "
        "t.purpose = 'change' AND t.expires_at > ?", (_token_hash(token), _utc(now))).fetchone()
    if row is None:
        return out
    uid, new = row["user_id"], row["new_email"]
    if _email_taken(conn, new, uid):
        conn.execute("DELETE FROM email_tokens WHERE user_id = ? AND purpose = 'change'", (uid,))
        conn.commit()
        return {**out, "error": "That email is now used by another account, so it wasn't "
                                "changed. Try a different one."}
    old = row["old_email"]
    username = row["username"]
    login_is_email = bool(old) and username.lower() == old.lower()
    if login_is_email:
        username = new
        conn.execute("DELETE FROM login_failures WHERE username_key = ?",
                     (_login_key(row["username"]),))
    conn.execute("UPDATE users SET email = ?, email_verified_at = ?, username = ? WHERE id = ?",
                 (new, _utc(now), username, uid))
    conn.execute("DELETE FROM email_tokens WHERE user_id = ?", (uid,))
    conn.commit()
    return {"ok": True, "error": None, "user_id": uid, "email": new, "old_email": old,
            "username": username}


def end_other_sessions(conn, user_id: int, keep_token: str | None) -> int:
    """Sign out every other device; this browser's stay-signed-in session
    (keep_token) stays. The login's session number goes up too, so tabs
    already open elsewhere land on sign-in at their next click (audit X5) -
    the caller notes the new number for its own tab (session_gen). Returns
    how many stay-signed-in sessions ended."""
    keep = _token_hash(keep_token) if keep_token else ""
    cur = conn.execute("DELETE FROM login_sessions WHERE user_id = ? AND token_hash != ?",
                       (user_id, keep))
    conn.execute("UPDATE users SET session_gen = COALESCE(session_gen, 0) + 1 WHERE id = ?",
                 (user_id,))
    conn.commit()
    return cur.rowcount


def request_password_reset(conn, email: str, *, ip: str | None = None,
                           now: datetime | None = None) -> dict:
    """The "Forgot password?" request: {"ok", "error", "to", "token"}. ok is False only
    when a limit is hit or the email isn't one; otherwise the answer looks
    the same whether or not there's an account - "to"/"token" are set only
    when there is one, for the caller to send, and never shown."""
    now = now or datetime.now(timezone.utc)
    email = normalize_email(email)
    if not valid_email(email):
        return {"ok": False, "error": "Enter your email address, like name@example.com.",
                "to": None, "token": None}
    reason = _email_limit(conn, "reset", email, ip, now)
    if reason:
        return {"ok": False, "error": reason, "to": None, "token": None}
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if row is None:
        return {"ok": True, "error": None, "to": None, "token": None}
    return {"ok": True, "error": None, "to": email,
            "token": _create_email_token(conn, row["id"], "reset", email, now)}


SETUP_DAYS = 7   # how long the "choose your password" link for an admin-made account works


def setup_link(conn, user_id: int, *, now: datetime | None = None) -> dict:
    """A "choose your password" link for an account the admin made with an
    email address (admin.create_account) - a reset link that lasts
    SETUP_DAYS. Returns {"ok", "error", "to", "token"}; the caller emails it."""
    now = now or datetime.now(timezone.utc)
    email = email_status(conn, user_id)["email"]
    if not email:
        return {"ok": False, "error": "This account has no email address.", "to": None,
                "token": None}
    return {"ok": True, "error": None, "to": email,
            "token": _create_email_token(conn, user_id, "reset", email, now,
                                         life=timedelta(days=SETUP_DAYS))}


def reset_info(conn, token: str | None, *, now: datetime | None = None) -> dict | None:
    return _email_token(conn, token, "reset", now or datetime.now(timezone.utc))


def reset_password(conn, token: str, password: str, *, now: datetime | None = None) -> dict:
    """Choose a new password from a reset link. Signs the account out
    everywhere and clears any lockout (set_password); opening the link also
    proves the email, so it counts as confirmed. Returns {"ok", "error",
    "user_id", "username"}."""
    now = now or datetime.now(timezone.utc)
    info = reset_info(conn, token, now=now)
    if info is None:
        return {"ok": False, "user_id": None, "username": None,
                "error": "This reset link has expired or was already used. Ask for a new one."}
    if len(password or "") < MIN_PASSWORD_LENGTH:
        return {"ok": False, "user_id": None, "username": None,
                "error": f"Use a password of at least {MIN_PASSWORD_LENGTH} characters."}
    conn.execute("DELETE FROM email_tokens WHERE user_id = ? AND purpose = 'reset'",
                 (info["user_id"],))
    conn.execute("UPDATE users SET email_verified_at = COALESCE(email_verified_at, ?) "
                 "WHERE id = ?", (_utc(now), info["user_id"]))
    set_password(conn, info["username"], password)  # commits all three
    return {"ok": True, "error": None, "user_id": info["user_id"], "username": info["username"]}


def get_user_id(conn: sqlite3.Connection, username: str) -> int | None:
    row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    return row["id"] if row else None


def get_username(conn: sqlite3.Connection, user_id: int) -> str | None:
    row = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
    return row["username"] if row else None


def account_row(conn, user_id: int):
    """The login's own row as the Account page shows it (name, email and its
    confirmation, joined, last sign-in), or None."""
    return conn.execute("SELECT username, email, email_verified_at, display_name, created_at, "
                        "last_login_at FROM users WHERE id = ?", (user_id,)).fetchone()


def live_sessions(conn, user_id: int, *, now: datetime | None = None) -> int:
    """How many stay-signed-in sessions of this login haven't expired."""
    now = now or datetime.now(timezone.utc)
    return conn.execute("SELECT COUNT(*) AS n FROM login_sessions WHERE user_id = ? AND "
                        "expires_at > ?", (user_id, _utc(now))).fetchone()["n"]


def confirmed_emails(conn, user_ids) -> list[str]:
    """The emails of these logins that are confirmed and have signed in at
    least once, in id order (who an advisor's "you have a message" goes to)."""
    ids = tuple(user_ids)
    if not ids:
        return []
    return [r["email"] for r in conn.execute(
        "SELECT email FROM users WHERE id IN (" + ", ".join("?" for _ in ids) + ") "
        "AND email IS NOT NULL AND email_verified_at IS NOT NULL "
        "AND last_login_at IS NOT NULL ORDER BY id", ids)]


# --------------------------------------------------------------------------- #
# advisor mode
# --------------------------------------------------------------------------- #
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._@-]{1,50}$")


def valid_username(username: str) -> bool:
    return bool(_USERNAME_RE.match(username or ""))


def is_advisor(conn: sqlite3.Connection, user_id: int) -> bool:
    """False for NULL too - accounts created before advisor mode have no value."""
    row = conn.execute("SELECT is_advisor FROM users WHERE id = ?", (user_id,)).fetchone()
    return bool(row and row["is_advisor"])


def set_advisor(conn: sqlite3.Connection, username: str, flag: bool) -> bool:
    """Returns False if no such user. Making someone an advisor also approves
    their advisor request, if they made one (request_advisor)."""
    cur = conn.execute("UPDATE users SET is_advisor = ? WHERE username = ?",
                       (1 if flag else 0, username))
    if flag and cur.rowcount:
        conn.execute("UPDATE advisor_requests SET decision = 'approved', decided_at = ? "
                     "WHERE user_id = (SELECT id FROM users WHERE username = ?) "
                     "AND decision IS NULL", (_utc(datetime.now(timezone.utc)), username))
    conn.commit()
    return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# asking for advisor access - nobody makes themselves an advisor
# --------------------------------------------------------------------------- #
def advisor_request_error(firm: str, licence: str) -> str | None:
    """What's wrong with an advisor request's details, or None."""
    firm, licence = (firm or "").strip(), (licence or "").strip()
    if not firm or len(firm) > 100:
        return "Enter your firm's name (up to 100 characters)."
    if not licence or len(licence) > 40:
        return "Enter your CRD or license number (up to 40 characters)."
    return None


def request_advisor(conn, user_id: int, firm: str, licence: str, *,
                    now: datetime | None = None) -> None:
    """Record that this account asked for advisor access. The admin checks the
    firm and license and approves it (set_advisor / manage_users.py
    make-advisor) or declines it (decline_advisor); until then the account
    is an ordinary investor account. A new request replaces an earlier one."""
    error = advisor_request_error(firm, licence)
    if error:
        raise ValueError(error)
    now = now or datetime.now(timezone.utc)
    conn.execute("DELETE FROM advisor_requests WHERE user_id = ?", (user_id,))
    conn.execute("INSERT INTO advisor_requests (user_id, firm, licence, requested_at) "
                 "VALUES (?, ?, ?, ?)", (user_id, firm.strip(), licence.strip(), _utc(now)))
    conn.commit()


def advisor_request(conn, user_id: int) -> dict | None:
    """{"firm", "licence", "requested_at", "decision" (None while waiting,
    'approved' or 'declined')} or None if the account never asked."""
    row = conn.execute("SELECT firm, licence, requested_at, decision FROM advisor_requests "
                       "WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def pending_advisor_requests(conn) -> list[dict]:
    """Requests waiting for a decision, oldest first, with the username."""
    return [dict(r) for r in conn.execute(
        "SELECT u.username, r.firm, r.licence, r.requested_at FROM advisor_requests r "
        "JOIN users u ON u.id = r.user_id WHERE r.decision IS NULL ORDER BY r.requested_at")]


def decline_advisor(conn, username: str, *, now: datetime | None = None) -> bool:
    """Turn down a waiting request. False if there was none."""
    now = now or datetime.now(timezone.utc)
    cur = conn.execute("UPDATE advisor_requests SET decision = 'declined', decided_at = ? "
                       "WHERE user_id = (SELECT id FROM users WHERE username = ?) "
                       "AND decision IS NULL", (_utc(now), username))
    conn.commit()
    return cur.rowcount > 0


def link_client(conn: sqlite3.Connection, advisor_id: int, client_id: int, *,
                commit: bool = True) -> None:
    """Full sharing: the advisor sees the client's account (can_view).
    `commit=False` leaves it to the caller's transaction (intros.share_account
    writes the consent grant in the same one)."""
    conn.execute("INSERT INTO advisor_clients (advisor_id, client_id) VALUES (?, ?) "
                 "ON CONFLICT (advisor_id, client_id) DO NOTHING", (advisor_id, client_id))
    if commit:
        conn.commit()


def unlink_client(conn: sqlite3.Connection, advisor_id: int, client_id: int) -> None:
    """The admin's unlink (Admin portal, manage_users.py): when there was a
    link, a consent revoke records that it ended ('admin', consent.py)."""
    cur = conn.execute("DELETE FROM advisor_clients WHERE advisor_id = ? AND client_id = ?",
                       (advisor_id, client_id))
    if cur.rowcount:
        import advisor_pack
        import client_book
        import consent
        consent.revoke(conn, client_id, advisor_id, "admin", commit=False)
        advisor_pack.on_unlink(conn, client_id, advisor_id, "admin")
        client_book.on_unlink(conn, client_id, advisor_id, "admin")
    conn.commit()


CLIENT_NAME_MAX = 60


def clean_client_name(name: str | None) -> str | None:
    """A client's name as the advisor typed it ("Dana Lee", "Chen household"):
    spaces tidied, at most CLIENT_NAME_MAX characters; None when blank."""
    return " ".join((name or "").split())[:CLIENT_NAME_MAX] or None


def list_clients(conn: sqlite3.Connection, advisor_id: int) -> list[tuple[int, str]]:
    """(id, name) per client, by name: what the advisor calls them (Add client,
    set_client_name), else the name they chose (Account page), else their login."""
    rows = [(r["id"], r["client_name"] or r["display_name"] or r["username"]) for r in
            conn.execute("SELECT u.id, u.username, u.display_name, ac.client_name "
                         "FROM advisor_clients ac JOIN users u ON u.id = ac.client_id "
                         "WHERE ac.advisor_id = ?", (advisor_id,))]
    return sorted(rows, key=lambda r: (r[1].casefold(), r[0]))


def set_client_name(conn, advisor_id: int, client_id: int, name: str | None) -> bool:
    """The advisor's name for one of their clients; blank goes back to the
    client's own name or login. Only the advisor's own clients - False (and
    nothing changed) otherwise. The client's own Account name isn't touched."""
    cur = conn.execute("UPDATE advisor_clients SET client_name = ? WHERE advisor_id = ? "
                       "AND client_id = ?", (clean_client_name(name), advisor_id, client_id))
    conn.commit()
    return cur.rowcount > 0


def has_signed_in(conn, user_id: int) -> bool:
    """Whether this account has ever signed in (or chosen its password from
    a setup link). A client the advisor added who hasn't yet can't read
    anything "in the app" - they need a setup link first."""
    row = conn.execute("SELECT last_login_at FROM users WHERE id = ?", (user_id,)).fetchone()
    return bool(row and row["last_login_at"])


def _login_from_name(conn, name: str) -> str:
    """A login for a client added without an email ("Chen household" ->
    "chen.household", then "chen.household2"...). Nobody types it unless the
    advisor sets them a password or sends a setup link."""
    base = re.sub(r"[^a-z0-9]+", ".", name.casefold()).strip(".")[:40] or "client"
    login, n = base, 1
    while conn.execute("SELECT 1 FROM users WHERE lower(username) = ?", (login,)).fetchone():
        n += 1
        login = f"{base}{n}"
    return login


def can_view(conn: sqlite3.Connection, viewer_id: int, target_id: int) -> bool:
    """Whose data a logged-in user may see: their own, plus - if they're an
    advisor - accounts linked to them as clients, once they've accepted the
    current advisor agreement (advisor_agreement.tools_open: asked only while
    its flag is on)."""
    if viewer_id == target_id:
        return True
    if not is_advisor(conn, viewer_id):
        return False
    import advisor_agreement
    if not advisor_agreement.tools_open(conn, viewer_id):
        return False
    return conn.execute("SELECT 1 FROM advisor_clients WHERE advisor_id = ? AND client_id = ?",
                        (viewer_id, target_id)).fetchone() is not None


def create_client(conn: sqlite3.Connection, advisor_id: int, username: str,
                  password: str | None = None, *, name: str | None = None) -> int:
    """Create an account managed by `advisor_id`. Without a password it gets a
    random one nobody knows, so only the advisor can reach it until they set
    a real one with set_password() or a setup link (create_invite). An email
    address becomes the login and the account's email, so the setup link can
    be emailed (ROADMAP G6). `name` is what the advisor calls them ("Dana
    Lee", "Chen household" - set_client_name); with a name and no username
    a login is made from the name. Raises ValueError for a non-advisor, an
    invalid username or email, or an email already in use, and the backend's
    integrity error for a taken username."""
    if not is_advisor(conn, advisor_id):
        raise ValueError("only advisors can create client accounts")
    name = clean_client_name(name)
    username = (username or "").strip()
    email = normalize_email(username) if "@" in username else None
    if email is not None:
        # an email address is the login, as at sign-up, so the setup link can be emailed
        if not valid_email(email):
            raise ValueError("that doesn't look like an email address")
        if conn.execute("SELECT 1 FROM users WHERE lower(username) = ? OR email = ?",
                        (email, email)).fetchone():
            raise ValueError(f"there's already an account for {email}")
        username = email
    elif not username and name:
        username = _login_from_name(conn, name)
    elif not valid_username(username):
        raise ValueError("usernames are 1-50 letters, digits, or . _ @ -")
    client_id = create_user(conn, username, password or secrets.token_urlsafe(32))
    if email is not None:
        conn.execute("UPDATE users SET email = ? WHERE id = ?", (email, client_id))
    link_client(conn, advisor_id, client_id)
    if name:
        set_client_name(conn, advisor_id, client_id, name)
    return client_id
