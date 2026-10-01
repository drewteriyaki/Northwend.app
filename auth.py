"""Individual login accounts. Created by an admin (manage_users.py) or by an
advisor for a client (create_client) - there is no self-service signup.
A client chooses their own password from a one-time setup link the advisor
sends (create_invite / accept_invite), so no password is ever shared.

Passwords are never stored in plain text: pbkdf2_hmac('sha256', ...) with a
per-user random salt, both stored as hex in the `users` table. No external
dependency needed - this is stdlib-only (hashlib, hmac, os), same
"standard library only" spirit as the rest of the CLI-facing code.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

PBKDF2_ITERATIONS = 200_000
SESSION_DAYS = 30  # how long "stay signed in" lasts before the password is needed again
MAX_FAILED_LOGINS = 5   # wrong passwords for one username within LOCKOUT_MINUTES...
LOCKOUT_MINUTES = 15    # ...lock that username for this long
MIN_PASSWORD_LENGTH = 8


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS).hex()


def create_user(conn: sqlite3.Connection, username: str, password: str) -> int:
    """Create a new account. Raises the backend's own integrity error
    (sqlite3.IntegrityError / psycopg's equivalent, both covered by
    portfolio.DBError) if `username` is already taken."""
    salt = os.urandom(16)
    pw_hash = _hash_password(password, salt)
    conn.execute(
        "INSERT INTO users (username, password_hash, password_salt) VALUES (?, ?, ?)",
        (username, pw_hash, salt.hex()))
    conn.commit()
    row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    return row["id"]


def verify_login(conn: sqlite3.Connection, username: str, password: str) -> int | None:
    """The user's id on a correct username/password, else None. Never
    reveals whether the username or the password was wrong (avoids
    username enumeration) - both a missing user and a wrong password just
    return None."""
    row = conn.execute(
        "SELECT id, password_hash, password_salt FROM users WHERE username = ?",
        (username,)).fetchone()
    if row is None:
        return None
    salt = bytes.fromhex(row["password_salt"])
    candidate = _hash_password(password, salt)
    if hmac.compare_digest(candidate, row["password_hash"]):
        return row["id"]
    return None


def set_password(conn: sqlite3.Connection, username: str, new_password: str) -> bool:
    """Change an existing user's password, signing that account out of every
    browser where it stayed signed in. Returns False if no such user."""
    salt = os.urandom(16)
    pw_hash = _hash_password(new_password, salt)
    cur = conn.execute(
        "UPDATE users SET password_hash = ?, password_salt = ? WHERE username = ?",
        (pw_hash, salt.hex(), username))
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
    """A short fingerprint of the account's current password hash, or None if
    the account is gone. The dashboard notes it at sign-in and compares it on
    every run, so a password change signs out tabs already open elsewhere."""
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        return None
    return hashlib.sha256((row["password_hash"] or "").encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# failed-login lockout
# --------------------------------------------------------------------------- #
def _login_key(username: str | None) -> str:
    """The lockout's key for a typed username: case-folded (so 'Alice' and
    'alice' share one count) and hashed (so what people typed isn't stored)."""
    return hashlib.sha256((username or "").strip().casefold().encode("utf-8")).hexdigest()


def attempt_login(conn, username: str, password: str, *, now: datetime | None = None) -> dict:
    """verify_login() behind the lockout. Returns {"user_id": id or None,
    "locked_minutes": minutes left on a lock (0 if none), "attempts_left":
    wrong passwords left before a lock}. A locked username is refused
    without checking the password - even the right one. Unknown usernames
    are counted and locked exactly like real ones."""
    now = now or datetime.now(timezone.utc)
    key, stamp = _login_key(username), _utc(now)
    row = conn.execute("SELECT failures, window_start, locked_until FROM login_failures "
                       "WHERE username_key = ?", (key,)).fetchone()
    if row and row["locked_until"] and row["locked_until"] > stamp:
        left = datetime.strptime(row["locked_until"], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc) - now
        return {"user_id": None, "locked_minutes": max(1, -(-int(left.total_seconds()) // 60)),
                "attempts_left": 0}

    user_id = verify_login(conn, username, password) if username and password else None
    if user_id is not None:
        conn.execute("DELETE FROM login_failures WHERE username_key = ?", (key,))
        conn.commit()
        return {"user_id": user_id, "locked_minutes": 0, "attempts_left": MAX_FAILED_LOGINS}

    window_open = _utc(now - timedelta(minutes=LOCKOUT_MINUTES))
    fresh = row is None or row["window_start"] <= window_open or row["locked_until"]
    failures = 1 if fresh else row["failures"] + 1
    locked_until = (_utc(now + timedelta(minutes=LOCKOUT_MINUTES))
                    if failures >= MAX_FAILED_LOGINS else None)
    conn.execute("DELETE FROM login_failures WHERE username_key = ?", (key,))
    conn.execute("INSERT INTO login_failures (username_key, failures, window_start, locked_until) "
                 "VALUES (?, ?, ?, ?)",
                 (key, failures, stamp if fresh else row["window_start"], locked_until))
    # tidy: counts nobody has added to in a day, and locks that have run out
    conn.execute("DELETE FROM login_failures WHERE window_start < ? "
                 "AND (locked_until IS NULL OR locked_until < ?)",
                 (_utc(now - timedelta(days=1)), stamp))
    conn.commit()
    return {"user_id": None, "locked_minutes": LOCKOUT_MINUTES if locked_until else 0,
            "attempts_left": max(0, MAX_FAILED_LOGINS - failures)}


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
    """{"user_id", "username", "expires_at"} for a live setup link, else None
    (unknown, expired or already used alike)."""
    if not token:
        return None
    now = now or datetime.now(timezone.utc)
    row = conn.execute(
        "SELECT i.user_id, u.username, i.expires_at FROM invites i JOIN users u ON u.id = i.user_id "
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


def accept_invite(conn, token: str, password: str, *, now: datetime | None = None) -> dict:
    """The client sets their password from a setup link. The link is used up
    (it can't set the password again), and any other sign-ins of that account
    end. Returns {"ok", "error", "user_id", "username"}."""
    info = invite_info(conn, token, now=now)
    if info is None:
        return {"ok": False, "error": "This setup link has expired or was already used. "
                "Ask your advisor for a new one.", "user_id": None, "username": None}
    if len(password) < MIN_PASSWORD_LENGTH:
        return {"ok": False, "error": f"Use a password of at least {MIN_PASSWORD_LENGTH} "
                "characters.", "user_id": None, "username": None}
    conn.execute("DELETE FROM invites WHERE user_id = ?", (info["user_id"],))
    set_password(conn, info["username"], password)  # commits both
    return {"ok": True, "error": None, "user_id": info["user_id"], "username": info["username"]}


def get_user_id(conn: sqlite3.Connection, username: str) -> int | None:
    row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
    return row["id"] if row else None


def get_username(conn: sqlite3.Connection, user_id: int) -> str | None:
    row = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
    return row["username"] if row else None


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
    """Returns False if no such user."""
    cur = conn.execute("UPDATE users SET is_advisor = ? WHERE username = ?",
                       (1 if flag else 0, username))
    conn.commit()
    return cur.rowcount > 0


def link_client(conn: sqlite3.Connection, advisor_id: int, client_id: int) -> None:
    conn.execute("INSERT INTO advisor_clients (advisor_id, client_id) VALUES (?, ?) "
                 "ON CONFLICT (advisor_id, client_id) DO NOTHING", (advisor_id, client_id))
    conn.commit()


def unlink_client(conn: sqlite3.Connection, advisor_id: int, client_id: int) -> None:
    conn.execute("DELETE FROM advisor_clients WHERE advisor_id = ? AND client_id = ?",
                 (advisor_id, client_id))
    conn.commit()


def list_clients(conn: sqlite3.Connection, advisor_id: int) -> list[tuple[int, str]]:
    return [(r["id"], r["username"]) for r in conn.execute(
        "SELECT u.id, u.username FROM advisor_clients ac JOIN users u ON u.id = ac.client_id "
        "WHERE ac.advisor_id = ? ORDER BY u.username", (advisor_id,))]


def can_view(conn: sqlite3.Connection, viewer_id: int, target_id: int) -> bool:
    """Whose data a logged-in user may see: their own, plus - if they're an
    advisor - accounts linked to them as clients."""
    if viewer_id == target_id:
        return True
    if not is_advisor(conn, viewer_id):
        return False
    return conn.execute("SELECT 1 FROM advisor_clients WHERE advisor_id = ? AND client_id = ?",
                        (viewer_id, target_id)).fetchone() is not None


def create_client(conn: sqlite3.Connection, advisor_id: int, username: str,
                  password: str | None = None) -> int:
    """Create an account managed by `advisor_id`. Without a password it gets a
    random one nobody knows, so only the advisor can reach it until they set
    a real one with set_password(). Raises ValueError for a non-advisor or
    an invalid username, and the backend's integrity error for a taken one."""
    if not is_advisor(conn, advisor_id):
        raise ValueError("only advisors can create client accounts")
    if not valid_username(username):
        raise ValueError("usernames are 1-50 letters, digits, or . _ @ -")
    client_id = create_user(conn, username, password or secrets.token_urlsafe(32))
    link_client(conn, advisor_id, client_id)
    return client_id
