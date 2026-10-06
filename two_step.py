"""Two-step sign-in (ROADMAP R2): after the password, a 6-digit code from an
authenticator app on the person's phone - TOTP (RFC 6238): HMAC-SHA-1,
6 digits, 30-second steps, one step either side allowed for a phone whose
clock is a little off. Required for advisors and admins (their login opens
other people's portfolios); anyone else can turn it on on the Account page.

- The secret key is stored per login (`two_step` table), shown only during
  setup - never again, never exported, never to an admin. Checking codes
  needs it, so it can't be hashed: with NORTHWEND_TOTP_KEY set it's stored
  encrypted (Fernet, `enc1:` in front - "Keys at rest" below), so a copy of
  the database alone can't make anyone's codes. Without that setting (a
  local run, or a host not set up yet) it's stored readable, as it always
  was; Admin > System says which, and how many are still readable.
- BACKUP_CODES one-time backup codes, shown once (at setup, or when new ones
  are made) and stored only as slow hashes (PBKDF2, _backup_match); each
  works once.
- Wrong codes count toward a lock exactly like wrong passwords
  (login_failures, under a key of their own per account), and a code that
  worked can't be used again (last_token_step).
- "Remember this device": the browser's stay-signed-in session
  (login_sessions.two_step_until) skips the code until then. Turning
  two-step on or off forgets every device; a new password ends the sessions.
- reset() (Admin portal, `manage_users.py reset-two-step`) is for someone
  locked out: it turns two-step off and signs the account out everywhere, so
  setting it up again needs the password.

The codes are standard library only; the encryption is the `cryptography`
package, imported only when a key is set. The app's pages are in
views/two_step.py.
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
import settings

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
# keys at rest (audit 1.1e, PLAN D14)
# --------------------------------------------------------------------------- #
# two_step.totp_secret holds either the key as the app shows it (base32 -
# readable: rows from before NORTHWEND_TOTP_KEY, or a copy without it) or
# SEALED + a Fernet token (AES-128-CBC and HMAC-SHA256) made with the first
# of settings.totp_keys(). Base32 has no ":", so the two can't be mixed up.
# Readable rows become sealed at the person's next good code (_good_code), or
# all at once with `manage_users.py encrypt-two-step` (encrypt_all, which
# also re-seals with a new first key after a rotation). A sealed key that no
# key here opens (a wrong or missing NORTHWEND_TOTP_KEY) matches no code:
# backup codes and the password paths still work, and Admin > System counts
# them (storage). Never logged, printed or shown, sealed or not.
SEALED = "enc1:"


class KeyUnreadable(Exception):
    """A stored two-step key that this copy's NORTHWEND_TOTP_KEY can't open.
    Only its type and place reach the admin (error_alerts.py) - never a key."""


_BOXES: dict[tuple[str, ...], object] = {}


def _box():
    """A MultiFernet for settings.totp_keys() (the first encrypts, all
    decrypt), None without a usable key - unset, or not a Fernet key
    (key_state says which)."""
    keys = tuple(settings.totp_keys())
    if not keys:
        return None
    if keys not in _BOXES:
        try:
            from cryptography.fernet import Fernet, MultiFernet
            _BOXES[keys] = MultiFernet([Fernet(k.encode("ascii")) for k in keys])
        except (ValueError, TypeError, UnicodeEncodeError, ImportError):
            _BOXES[keys] = None
    return _BOXES[keys]


def key_id(key: str) -> str:
    """A short name for a key - the start of a hash, which gives nothing of
    the key away - so the host's key can be checked against the one a
    command ran with without showing either."""
    return hashlib.sha256(b"northwend two-step key id:" + key.encode("utf-8")).hexdigest()[:8]


def key_state() -> dict:
    """{"state": "set" / "not set" / "not valid", "count": how many keys,
    "key_id": the first (encrypting) key's key_id or None}. For Admin >
    System and the command line - never a key itself."""
    keys = settings.totp_keys()
    if not keys:
        return {"state": "not set", "count": 0, "key_id": None}
    return {"state": "set" if _box() is not None else "not valid", "count": len(keys),
            "key_id": key_id(keys[0])}


def _seal(secret: str) -> str:
    """The form to store: sealed with the first key, or - without a usable
    key - readable, as before."""
    box = _box()
    if box is None:
        return secret
    return SEALED + box.encrypt(secret.encode("ascii")).decode("ascii")


def _open(stored: str | None) -> str | None:
    """The key from its stored form; None when it's sealed and no key here
    opens it."""
    stored = stored or ""
    if not stored.startswith(SEALED):
        return stored
    box = _box()
    if box is None:
        return None
    from cryptography.fernet import InvalidToken
    try:
        return box.decrypt(stored[len(SEALED):].encode("ascii")).decode("ascii")
    except (InvalidToken, ValueError, UnicodeError):
        return None


def _needs_sealing(stored: str) -> bool:
    """Readable while a key is set, or sealed with a key that's no longer
    the first one (a rotation): re-seal at the next good code."""
    box = _box()
    if box is None:
        return False
    if not stored.startswith(SEALED):
        return True
    from cryptography.fernet import Fernet, InvalidToken
    try:
        Fernet(settings.totp_keys()[0].encode("ascii")).decrypt(
            stored[len(SEALED):].encode("ascii"))
        return False
    except (InvalidToken, ValueError):
        return True


def storage(conn) -> dict:
    """How the two-step keys are stored, as counts (no names): {"sealed":
    opens with this copy's key, "readable": not encrypted yet, "unreadable":
    sealed but no key here opens it, "old_key": sealed with a key that isn't
    the first one any more}. For Admin > System."""
    out = {"sealed": 0, "readable": 0, "unreadable": 0, "old_key": 0}
    for row in conn.execute("SELECT totp_secret FROM two_step"):
        stored = row["totp_secret"] or ""
        if not stored.startswith(SEALED):
            out["readable"] += 1
        elif _open(stored) is None:
            out["unreadable"] += 1
        else:
            out["sealed"] += 1
            out["old_key"] += _needs_sealing(stored)
    return out


def encrypt_all(conn, *, rotate: bool = False) -> dict:
    """`manage_users.py encrypt-two-step`: seal every readable key with the
    first key, in one transaction - and with rotate=True, re-seal the sealed
    ones with it too (after a new key went in front). Refuses, changing
    nothing, without a usable key or when a sealed key won't open (the key
    here isn't the one the app uses). {"ok", "error", "sealed", "resealed",
    "key_id"}."""
    state = key_state()
    out = {"ok": False, "error": None, "sealed": 0, "resealed": 0, "key_id": state["key_id"]}
    if state["state"] == "not set":
        return {**out, "error": "NORTHWEND_TOTP_KEY isn't set here, so there's nothing to "
                                "encrypt with."}
    if state["state"] == "not valid":
        return {**out, "error": "NORTHWEND_TOTP_KEY isn't a valid key (each one is 44 "
                                "letters, digits, - or _, ending in =)."}
    rows = conn.execute("SELECT user_id, totp_secret FROM two_step ORDER BY user_id").fetchall()
    work = []
    for row in rows:
        stored = row["totp_secret"] or ""
        if not stored.startswith(SEALED):
            work.append((row["user_id"], stored, "sealed"))
            continue
        secret = _open(stored)
        if secret is None:
            n = sum(1 for r in rows if (r["totp_secret"] or "").startswith(SEALED)
                    and _open(r["totp_secret"]) is None)
            return {**out, "error": f"{n} stored key{'s' if n != 1 else ''} won't open with "
                                    "the NORTHWEND_TOTP_KEY here - it isn't the key the app "
                                    "uses. Nothing was changed."}
        if rotate and _needs_sealing(stored):
            work.append((row["user_id"], secret, "resealed"))
    for user_id, secret, how in work:
        conn.execute("UPDATE two_step SET totp_secret = ? WHERE user_id = ?",
                     (_seal(secret), user_id))
        out[how] += 1
    conn.commit()
    return {**out, "ok": True}


def _good_code(conn, user_id: int, row, code: str, now: datetime) -> tuple[int | None, bool]:
    """(the time step `code` matched for this login's stored key, or None;
    True when the stored key couldn't be opened). A match moves
    last_token_step on - and seals a readable key (or re-seals one made
    with an older key) on the way."""
    stored = row["totp_secret"] or ""
    secret = _open(stored)
    if secret is None:
        return None, True
    step = _match(secret, code, now, row["last_token_step"] or 0)
    if step is not None:
        if _needs_sealing(stored):
            conn.execute("UPDATE two_step SET last_token_step = ?, totp_secret = ? "
                         "WHERE user_id = ?", (step, _seal(secret), user_id))
        else:
            conn.execute("UPDATE two_step SET last_token_step = ? WHERE user_id = ?",
                         (step, user_id))
    return step, False


# --------------------------------------------------------------------------- #
# backup codes
# --------------------------------------------------------------------------- #
# Each code is about 40 random bits. The lock covers guessing online; against
# offline guessing from a copy of the database, the stored hashes are slow
# ones (PLAN 1b.8, audit 1.1e): PBKDF2-SHA256 with a salt per set, stored as
# "p2$<count>$<salt hex>$<hash hex>" per code, space-separated. Sets made
# before that are plain SHA-256 (_backup_hash): still accepted, each one gone
# once it's used, and all of them replaced by a new set (new_backup_codes).
BACKUP_ITERATIONS = 100_000   # 8 codes are hashed at setup, so lower than a password's
_SLOW = "p2"


def _backup_hash(user_id: int, code: str) -> str:
    """The old stored form of a backup code (plain SHA-256), still accepted."""
    return hashlib.sha256(f"{user_id}:{_clean(code)}".encode("utf-8")).hexdigest()


def _backup_slow(user_id: int, code: str, salt_hex: str, count: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", f"{user_id}:{_clean(code)}".encode("utf-8"),
                               bytes.fromhex(salt_hex), count).hex()


def _new_backup_codes(user_id: int) -> tuple[list[str], str]:
    """(codes to show, as 'abcd-efgh'; the hashes to store)."""
    codes = []
    for _ in range(BACKUP_CODES):
        raw = "".join(secrets.choice(_BACKUP_ALPHABET) for _ in range(_BACKUP_LEN))
        codes.append(f"{raw[:4]}-{raw[4:]}")
    salt, count = os.urandom(16).hex(), auth.iterations(BACKUP_ITERATIONS)
    return codes, " ".join(f"{_SLOW}${count}${salt}${_backup_slow(user_id, c, salt, count)}"
                           for c in codes)


def _backup_match(user_id: int, code: str, stored: list[str]) -> str | None:
    """The stored entry (one of `stored`) that `code` - already _clean -
    matches, or None. Slow entries are hashed once per salt (a set shares
    one); old SHA-256 ones are compared as they are."""
    if not _is_backup_shape(code):
        return None
    made: dict[tuple[str, str], str] = {}
    hit = None
    for entry in stored:
        if entry.startswith(_SLOW + "$"):
            try:
                _, count, salt, digest = entry.split("$")
                key = (count, salt)
                if key not in made:
                    made[key] = _backup_slow(user_id, code, salt, int(count))
            except ValueError:   # not a well-formed entry: matches nothing
                continue
            candidate = made[key]
        else:
            candidate, digest = _backup_hash(user_id, code), entry
        if hmac.compare_digest(candidate, digest) and hit is None:
            hit = entry
    return hit


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
    """(status(), the login's users row it came from - auth.LOGIN_COLUMNS and
    the app-wide everyone_gen, or None when there's no such login), in
    status()'s one query. The sign-in
    gate reads this first thing on every run, and the rest of that run uses
    the row instead of reading it again (auth.login_facts_of)."""
    import admin  # admin imports auth; not at the top, to keep auth's import light
    row = conn.execute(
        "SELECT " + ", ".join(f"u.{c}" for c in auth.LOGIN_COLUMNS) + ", "
        + auth.EVERYONE_GEN_SQL + ", "
        "t.totp_secret, t.enabled_at, t.backup_codes_hash FROM users u "
        "LEFT JOIN two_step t ON t.user_id = u.id WHERE u.id = ?", (user_id,)).fetchone()
    if row is None:
        return {"on": False, "required": False, "stamp": None, "backup_left": 0}, None
    on = bool(row["totp_secret"])
    # from the key itself, not its stored form: sealing it (or re-sealing it
    # with a new key) mustn't look like a new setup to a tab already past the
    # code - only turning it on, off or reset should
    shown = (_open(row["totp_secret"]) or row["totp_secret"]) if on else ""
    stamp = (hashlib.sha256(f"{row['enabled_at']}:{shown}".encode("utf-8"))
             .hexdigest()[:16] if on else None)
    return ({"on": on,
             "required": bool(row["is_advisor"]) or admin._admin_row(row, admin.listed_admins()),
             "stamp": stamp,
             "backup_left": len((row["backup_codes_hash"] or "").split()) if on else 0},
            {c: row[c] for c in (*auth.LOGIN_COLUMNS, "everyone_gen")})


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
                 (user_id, _seal(re.sub(r"[\s-]", "", secret).upper()), hashes,
                  auth._utc(now), step))
    _forget_devices(conn, user_id)
    conn.commit()
    return {"ok": True, "error": None, "backup_codes": codes}


def verify(conn, user_id: int, code: str, *, now: datetime | None = None) -> dict:
    """The sign-in check: a code from the app, or a backup code (used up).
    Wrong codes count toward a lock, like passwords. Returns {"ok",
    "error", "locked_minutes", "used_backup", "backup_left", "key_problem":
    the stored key wouldn't open with this copy's NORTHWEND_TOTP_KEY - the
    page tells the admin (KeyUnreadable)}. A good code also seals a
    readable key (_good_code)."""
    now = now or datetime.now(timezone.utc)
    out = {"ok": False, "error": None, "locked_minutes": 0, "used_backup": False,
           "backup_left": 0, "key_problem": False}
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
    step, unreadable = _good_code(conn, user_id, row, code, now)   # moves last_token_step on
    out["key_problem"] = unreadable
    backup = None if step is not None else _backup_match(user_id, code, hashes)
    if step is None and backup is not None:
        hashes.remove(backup)   # used up
        conn.execute("UPDATE two_step SET backup_codes_hash = ? WHERE user_id = ?",
                     (" ".join(hashes), user_id))
        out["used_backup"] = True
    elif step is None:
        # still counted when the key wouldn't open: the lock is what guards
        # the backup codes, which go on working
        mins, left = _note_failure(conn, key, now)
        if mins:
            return {**out, "locked_minutes": mins,
                    "error": f"Too many tries. Please wait {_minutes(mins)} and try again."}
        if unreadable:
            return {**out, "error": "We couldn't check codes from your app just now - sorry. "
                                    "One of your backup codes works in its place, or try again "
                                    "a little later."}
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
        step, _unreadable = _good_code(conn, user_id, row, code, now)
        if step is not None:
            conn.commit()
            return None
        if _backup_match(user_id, code, (row["backup_codes_hash"] or "").split()):
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
