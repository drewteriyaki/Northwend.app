"""Two-step sign-in (ROADMAP R2): after the password, a 6-digit code from an
authenticator app on the person's phone - TOTP (RFC 6238): HMAC-SHA-1,
6 digits, 30-second steps, one step either side allowed for a phone whose
clock is a little off. Required for advisors and admins (their login opens
other people's portfolios); anyone else can turn it on on the Account page.

- The secret key is stored per login (`two_step` table). It has to stay
  readable to check codes, so it's shown only during setup - never again,
  never exported, never to an admin.
- BACKUP_CODES one-time backup codes, shown once (at setup, or when new ones
  are made) and stored only as hashes; each works once.
- Wrong codes count toward a lock exactly like wrong passwords
  (login_failures, under a key of their own per account), and a code that
  worked can't be used again (last_token_step).
- "Remember this device": the browser's stay-signed-in session
  (login_sessions.two_step_until) skips the code until then. Turning
  two-step on or off forgets every device; a new password ends the sessions.
- reset() (Admin portal, `manage_users.py reset-two-step`) is for someone
  locked out: it turns two-step off and signs the account out everywhere, so
  setting it up again needs the password.

Standard library only. The app's pages are in views/two_step.py.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import struct
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import auth

DIGITS = 6
PERIOD = 30          # seconds per code
WINDOW = 1           # steps either side accepted
BACKUP_CODES = 8
REMEMBER_DAYS = 30   # "remember this device"
_BACKUP_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"   # no 0/o, 1/l/i
_BACKUP_LEN = 8


# --------------------------------------------------------------------------- #
# the code itself (RFC 4226 / 6238)
# --------------------------------------------------------------------------- #
def new_secret() -> str:
    """A fresh secret key: 160 random bits as base32 (32 letters/digits)."""
    return base64.b32encode(os.urandom(20)).decode("ascii")


def grouped(secret: str) -> str:
    """The key in groups of four, for typing into an app by hand."""
    return " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))


def _key(secret: str) -> bytes:
    s = re.sub(r"[\s-]", "", secret or "").upper()
    return base64.b32decode(s + "=" * (-len(s) % 8))


def hotp(key: bytes, counter: int, digits: int = DIGITS) -> str:
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    value = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10 ** digits).zfill(digits)


def step_of(now: datetime | float) -> int:
    ts = now.timestamp() if isinstance(now, datetime) else float(now)
    return int(ts // PERIOD)


def totp(secret: str, now: datetime | float | None = None, digits: int = DIGITS) -> str:
    """The code an authenticator app shows for `secret` at `now`."""
    now = datetime.now(timezone.utc) if now is None else now
    return hotp(_key(secret), step_of(now), digits)


def _match(secret: str, code: str, now: datetime, after_step: int = 0) -> int | None:
    """The time step `code` belongs to (now, or one either side), if it's
    later than `after_step` (a used code doesn't work twice); else None."""
    if not re.fullmatch(rf"\d{{{DIGITS}}}", code or ""):
        return None
    key, here = _key(secret), step_of(now)
    for s in range(here - WINDOW, here + WINDOW + 1):
        if s > after_step and hmac.compare_digest(hotp(key, s), code):
            return s
    return None


def otpauth_uri(secret: str, account: str, issuer: str = "Northwend") -> str:
    """The otpauth:// link (and QR code contents) an authenticator app reads."""
    label = quote(f"{issuer}:{account}", safe=":@")
    return (f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={PERIOD}")


def _clean(code: str | None) -> str:
    return re.sub(r"[\s-]", "", code or "").lower()


# --------------------------------------------------------------------------- #
# backup codes
# --------------------------------------------------------------------------- #
def _backup_hash(user_id: int, code: str) -> str:
    # ~40 random bits each and behind the lock, so a plain SHA-256 is enough
    return hashlib.sha256(f"{user_id}:{_clean(code)}".encode("utf-8")).hexdigest()


def _new_backup_codes(user_id: int) -> tuple[list[str], str]:
    """(codes to show, as 'abcd-efgh'; the hashes to store)."""
    codes = []
    for _ in range(BACKUP_CODES):
        raw = "".join(secrets.choice(_BACKUP_ALPHABET) for _ in range(_BACKUP_LEN))
        codes.append(f"{raw[:4]}-{raw[4:]}")
    return codes, " ".join(_backup_hash(user_id, c) for c in codes)


def _is_backup_shape(code: str) -> bool:
    return len(code) == _BACKUP_LEN and all(ch in _BACKUP_ALPHABET for ch in code)


# --------------------------------------------------------------------------- #
# a lock on wrong codes, like the one on wrong passwords (auth.attempt_login)
# --------------------------------------------------------------------------- #
def _fail_key(user_id: int) -> str:
    return hashlib.sha256(f"two-step:{user_id}".encode("utf-8")).hexdigest()


def _lock_left(conn, key: str, now: datetime) -> int:
    """Minutes left on a lock for `key` (a login_failures row), 0 if none."""
    row = conn.execute("SELECT locked_until FROM login_failures WHERE username_key = ?",
                       (key,)).fetchone()
    if not (row and row["locked_until"] and row["locked_until"] > auth._utc(now)):
        return 0
    left = datetime.strptime(row["locked_until"], "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=timezone.utc) - now
    return max(1, -(-int(left.total_seconds()) // 60))


def _note_failure(conn, key: str, now: datetime) -> tuple[int, int]:
    """Count one wrong code. (minutes locked now - 0 if not, tries left)."""
    stamp = auth._utc(now)
    row = conn.execute("SELECT failures, window_start, locked_until FROM login_failures "
                       "WHERE username_key = ?", (key,)).fetchone()
    window_open = auth._utc(now - timedelta(minutes=auth.LOCKOUT_MINUTES))
    fresh = row is None or row["window_start"] <= window_open or row["locked_until"]
    failures = 1 if fresh else row["failures"] + 1
    locked_until = (auth._utc(now + timedelta(minutes=auth.LOCKOUT_MINUTES))
                    if failures >= auth.MAX_FAILED_LOGINS else None)
    conn.execute("DELETE FROM login_failures WHERE username_key = ?", (key,))
    conn.execute("INSERT INTO login_failures (username_key, failures, window_start, locked_until) "
                 "VALUES (?, ?, ?, ?)",
                 (key, failures, stamp if fresh else row["window_start"], locked_until))
    conn.commit()
    return (auth.LOCKOUT_MINUTES if locked_until else 0,
            max(0, auth.MAX_FAILED_LOGINS - failures))


def unlock(conn, user_id: int) -> bool:
    """Clear a lock on wrong codes (the Admin portal's Unlock). True if there was one."""
    cur = conn.execute("DELETE FROM login_failures WHERE username_key = ?", (_fail_key(user_id),))
    conn.commit()
    return cur.rowcount > 0


def _minutes(m: int) -> str:
    return f"{m} minute{'s' if m != 1 else ''}"


# --------------------------------------------------------------------------- #
# whether it's on, and whether it has to be
# --------------------------------------------------------------------------- #
def status(conn, user_id: int) -> dict:
    """{"on": two-step is set up, "required": an advisor or admin login (it
    must be on), "stamp": a fingerprint that changes whenever it's turned on,
    off or reset (None when off), "backup_left": unused backup codes}. One
    query - the app checks this on every run."""
    return status_and_login(conn, user_id)[0]


def status_and_login(conn, user_id: int) -> tuple[dict, dict | None]:
    """(status(), the login's users row it came from - auth.LOGIN_COLUMNS, or
    None when there's no such login), in status()'s one query. The sign-in
    gate reads this first thing on every run, and the rest of that run uses
    the row instead of reading it again (auth.login_facts_of)."""
    import admin  # admin imports auth; not at the top, to keep auth's import light
    row = conn.execute(
        "SELECT " + ", ".join(f"u.{c}" for c in auth.LOGIN_COLUMNS) + ", "
        "t.totp_secret, t.enabled_at, t.backup_codes_hash FROM users u "
        "LEFT JOIN two_step t ON t.user_id = u.id WHERE u.id = ?", (user_id,)).fetchone()
    if row is None:
        return {"on": False, "required": False, "stamp": None, "backup_left": 0}, None
    on = bool(row["totp_secret"])
    stamp = (hashlib.sha256(f"{row['enabled_at']}:{row['totp_secret']}".encode("utf-8"))
             .hexdigest()[:16] if on else None)
    return ({"on": on,
             "required": bool(row["is_advisor"]) or admin._admin_row(row, admin.listed_admins()),
             "stamp": stamp,
             "backup_left": len((row["backup_codes_hash"] or "").split()) if on else 0},
            {c: row[c] for c in auth.LOGIN_COLUMNS})


def is_on(conn, user_id: int) -> bool:
    return conn.execute("SELECT 1 FROM two_step WHERE user_id = ?",
                        (user_id,)).fetchone() is not None


def _forget_devices(conn, user_id: int) -> None:
    conn.execute("UPDATE login_sessions SET two_step_until = NULL WHERE user_id = ?", (user_id,))


# --------------------------------------------------------------------------- #
# turning it on, checking a code, turning it off
# --------------------------------------------------------------------------- #
def enable(conn, user_id: int, secret: str, code: str, *,
           now: datetime | None = None) -> dict:
    """Turn two-step on with `secret` (shown during setup) once the app's
    first code checks out - so it's only on when the app really works.
    Replaces any earlier setup, and forgets remembered devices. Returns
    {"ok", "error", "backup_codes": shown once}."""
    now = now or datetime.now(timezone.utc)
    try:
        if len(_key(secret)) < 10:
            raise ValueError
    except (ValueError, TypeError):
        return {"ok": False, "error": "Something went wrong with the setup key. Start again.",
                "backup_codes": None}
    step = _match(secret, _clean(code), now)
    if step is None:
        return {"ok": False, "backup_codes": None,
                "error": "That code didn't match. Check the app shows Northwend, and type the "
                         "6 digits it shows now (they change every 30 seconds)."}
    codes, hashes = _new_backup_codes(user_id)
    conn.execute("DELETE FROM two_step WHERE user_id = ?", (user_id,))
    conn.execute("INSERT INTO two_step (user_id, totp_secret, backup_codes_hash, enabled_at, "
                 "last_token_step) VALUES (?, ?, ?, ?, ?)",
                 (user_id, re.sub(r"[\s-]", "", secret).upper(), hashes, auth._utc(now), step))
    _forget_devices(conn, user_id)
    conn.commit()
    return {"ok": True, "error": None, "backup_codes": codes}


def verify(conn, user_id: int, code: str, *, now: datetime | None = None) -> dict:
    """The sign-in check: a code from the app, or a backup code (used up).
    Wrong codes count toward a lock, like passwords. Returns {"ok",
    "error", "locked_minutes", "used_backup", "backup_left"}."""
    now = now or datetime.now(timezone.utc)
    out = {"ok": False, "error": None, "locked_minutes": 0, "used_backup": False,
           "backup_left": 0}
    key = _fail_key(user_id)
    locked = _lock_left(conn, key, now)
    if locked:
        return {**out, "locked_minutes": locked,
                "error": f"Too many tries. Please wait {_minutes(locked)} and try again."}
    row = conn.execute("SELECT totp_secret, backup_codes_hash, last_token_step FROM two_step "
                       "WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:   # turned off or reset meanwhile - nothing to check against
        return {**out, "error": "Two-step sign-in isn't on for this account any more. "
                                "Sign in again."}
    code = _clean(code)
    hashes = (row["backup_codes_hash"] or "").split()
    step = _match(row["totp_secret"], code, now, row["last_token_step"] or 0)
    if step is not None:
        conn.execute("UPDATE two_step SET last_token_step = ? WHERE user_id = ?", (step, user_id))
    elif _is_backup_shape(code) and _backup_hash(user_id, code) in hashes:
        hashes.remove(_backup_hash(user_id, code))
        conn.execute("UPDATE two_step SET backup_codes_hash = ? WHERE user_id = ?",
                     (" ".join(hashes), user_id))
        out["used_backup"] = True
    else:
        mins, left = _note_failure(conn, key, now)
        if mins:
            return {**out, "locked_minutes": mins,
                    "error": f"Too many tries. Please wait {_minutes(mins)} and try again."}
        return {**out, "error": "That code didn't work. Type the 6 digits your app shows now"
                + (f" ({left} more tr{'ies' if left != 1 else 'y'} before a short wait)."
                   if left <= 2 else ".")}
    conn.execute("DELETE FROM login_failures WHERE username_key = ?", (key,))
    conn.commit()
    return {**out, "ok": True, "backup_left": len(hashes)}


def _confirm_it_is_them(conn, user_id: int, answer: str, now: datetime) -> str | None:
    """Before turning two-step off or making new backup codes: a code from
    the app, a backup code (not used up - everything's replaced anyway), or
    the password. Every wrong answer counts toward the password lock, and a
    locked login can't get past this. None when it checks out, else why not."""
    username = auth.get_username(conn, user_id)
    if username is None:
        return "Account not found."
    locked = _lock_left(conn, auth._login_key(username), now)
    if locked:
        return f"Too many tries. Please wait {_minutes(locked)} and try again."
    row = conn.execute("SELECT totp_secret, backup_codes_hash, last_token_step FROM two_step "
                       "WHERE user_id = ?", (user_id,)).fetchone()
    code = _clean(answer)
    if row is not None:
        step = _match(row["totp_secret"], code, now, row["last_token_step"] or 0)
        if step is not None:
            conn.execute("UPDATE two_step SET last_token_step = ? WHERE user_id = ?",
                         (step, user_id))
            conn.commit()
            return None
        if _is_backup_shape(code) and _backup_hash(user_id, code) in (
                row["backup_codes_hash"] or "").split():
            return None
    result = auth.attempt_login(conn, username, answer or "", now=now)
    if result["user_id"] == user_id:
        return None
    if result["locked_minutes"]:
        return f"Too many tries. Please wait {_minutes(result['locked_minutes'])} and try again."
    return "That code or password isn't right."


def disable(conn, user_id: int, answer: str, *, now: datetime | None = None) -> dict:
    """Turn two-step off (Account page) after a code or the password. Not
    for advisors and admins, who must keep it. Returns {"ok", "error"}."""
    now = now or datetime.now(timezone.utc)
    st_ = status(conn, user_id)
    if not st_["on"]:
        return {"ok": False, "error": "Two-step sign-in is already off."}
    if st_["required"]:
        return {"ok": False, "error": "Advisor and admin accounts keep two-step sign-in on."}
    why = _confirm_it_is_them(conn, user_id, answer, now)
    if why:
        return {"ok": False, "error": why}
    conn.execute("DELETE FROM two_step WHERE user_id = ?", (user_id,))
    _forget_devices(conn, user_id)
    conn.commit()
    return {"ok": True, "error": None}


def new_backup_codes(conn, user_id: int, answer: str, *, now: datetime | None = None) -> dict:
    """A fresh set of backup codes, after a code or the password; the old ones
    stop working. Returns {"ok", "error", "backup_codes"}."""
    now = now or datetime.now(timezone.utc)
    if not is_on(conn, user_id):
        return {"ok": False, "error": "Two-step sign-in isn't on.", "backup_codes": None}
    why = _confirm_it_is_them(conn, user_id, answer, now)
    if why:
        return {"ok": False, "error": why, "backup_codes": None}
    codes, hashes = _new_backup_codes(user_id)
    conn.execute("UPDATE two_step SET backup_codes_hash = ? WHERE user_id = ?", (hashes, user_id))
    conn.commit()
    return {"ok": True, "error": None, "backup_codes": codes}


def reset(conn, user_id: int) -> bool:
    """For someone locked out (lost phone and backup codes): two-step off,
    remembered devices and code locks cleared, and the account signed out
    everywhere - so only the password gets them back in, and an advisor or
    admin is asked to set it up again straight away. Never shows the key.
    True if two-step was on."""
    cur = conn.execute("DELETE FROM two_step WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM login_sessions WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM login_failures WHERE username_key = ?", (_fail_key(user_id),))
    conn.commit()
    return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# remember this device (on the stay-signed-in session)
# --------------------------------------------------------------------------- #
def remember_device(conn, token: str | None, user_id: int, *,
                    now: datetime | None = None) -> bool:
    """Mark this browser's stay-signed-in session as not needing a code for
    REMEMBER_DAYS. False without such a session (nothing to remember with)."""
    if not token:
        return False
    now = now or datetime.now(timezone.utc)
    cur = conn.execute("UPDATE login_sessions SET two_step_until = ? WHERE token_hash = ? "
                       "AND user_id = ? AND expires_at > ?",
                       (auth._utc(now + timedelta(days=REMEMBER_DAYS)), auth._token_hash(token),
                        user_id, auth._utc(now)))
    conn.commit()
    return cur.rowcount > 0


def device_remembered(conn, token: str | None, user_id: int, *,
                      now: datetime | None = None) -> bool:
    if not token:
        return False
    now = now or datetime.now(timezone.utc)
    stamp = auth._utc(now)
    return conn.execute("SELECT 1 FROM login_sessions WHERE token_hash = ? AND user_id = ? "
                        "AND expires_at > ? AND two_step_until > ?",
                        (auth._token_hash(token), user_id, stamp, stamp)).fetchone() is not None
