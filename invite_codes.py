"""Invite codes for sign-up while gate L0 is off (docs/PLAN.md step 1a.9,
decision B7; docs/LEGAL_GATES.md, L0). Standard library only, no Streamlit.

With L0 off, Create account asks for a code first (auth.sign_up). The admin
makes codes on the Admin page (a few at a time, with an optional note to
remember who they're for), hands them out, and can revoke one that hasn't
been used. Each works once: using it records when and which account
(used_at, used_by). With L0 on, sign-up is open and no code is asked for.
Advisors' client setup links and accounts an admin makes never need one, and
signing in to an existing account is never affected.

Codes are 8 characters from an alphabet without look-alikes (no 0/O, 1/I/L),
shown as ABCD-EFGH; typing them in any case, with or without the dash or
spaces, works. They're stored as typed-out text, not hashed: a code is
single-use, opens nothing but the sign-up form (which was open to anyone
before), and the admin needs to see unused ones again to hand them out.

invite_codes rows mention accounts (created_by, used_by), so deleting an
account clears those columns (admin.ACCOUNT_REFERENCES) - the code itself
stays used, so it can't be used again.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # no 0 O 1 I L
LENGTH = 8
MAX_AT_ONCE = 50          # codes made in one go from Admin
MAX_NOTE = 100

# what the sign-up form says (calm: nothing about why, nothing to worry about)
BETA_LINE = "Northwend is in a small beta. If you have an invite code, enter it here."
NEED_CODE = "Enter your invite code to create an account."
NOT_WORKING = ("That invite code isn't working - check it and try again, or ask the person "
               "who gave it to you for a new one.")


def _utc(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def normalize(code: str | None) -> str:
    """A typed code as stored: upper case, no dashes or spaces."""
    return "".join(ch for ch in (code or "").upper() if ch not in " -\t\n")


def shown(code: str) -> str:
    """ABCDEFGH -> ABCD-EFGH, as handed out."""
    return f"{code[:4]}-{code[4:]}" if len(code) == LENGTH else code


def _new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))


def make(conn, how_many: int, *, by: int | None, note: str = "",
         now: datetime | None = None) -> list[str]:
    """Make `how_many` new codes (1..MAX_AT_ONCE), each with the same note.
    Returns them (stored form; shown() for display)."""
    how_many = max(1, min(int(how_many), MAX_AT_ONCE))
    note = (note or "").strip()[:MAX_NOTE] or None
    stamp = _utc(now or datetime.now(timezone.utc))
    made = []
    while len(made) < how_many:
        code = _new_code()
        if code in made or conn.execute("SELECT 1 FROM invite_codes WHERE code = ?",
                                        (code,)).fetchone():
            continue
        conn.execute("INSERT INTO invite_codes (code, note, created_by, created_at) "
                     "VALUES (?, ?, ?, ?)", (code, note, by, stamp))
        made.append(code)
    conn.commit()
    return made


def listing(conn) -> list[dict]:
    """Every code, newest first: code, note, created_at, used_at, used_by
    (the login, or None - also once that account is deleted), revoked_at and
    status ('unused', 'used' or 'revoked')."""
    rows = conn.execute(
        "SELECT i.code, i.note, i.created_at, i.used_at, i.revoked_at, u.username AS used_by "
        "FROM invite_codes i LEFT JOIN users u ON u.id = i.used_by "
        "ORDER BY i.created_at DESC, i.code").fetchall()
    out = []
    for r in rows:
        status = "used" if r["used_at"] else "revoked" if r["revoked_at"] else "unused"
        out.append({"code": r["code"], "note": r["note"], "created_at": r["created_at"],
                    "used_at": r["used_at"], "used_by": r["used_by"],
                    "revoked_at": r["revoked_at"], "status": status})
    return out


def revoke(conn, code: str, *, now: datetime | None = None) -> bool:
    """Stop an unused code working. False if it's unknown, used or revoked."""
    cur = conn.execute("UPDATE invite_codes SET revoked_at = ? WHERE code = ? "
                       "AND used_at IS NULL AND revoked_at IS NULL",
                       (_utc(now or datetime.now(timezone.utc)), normalize(code)))
    conn.commit()
    return cur.rowcount > 0


def usable(conn, code: str | None) -> bool:
    """Whether a typed code would work now: known, unused, not revoked."""
    code = normalize(code)
    if len(code) != LENGTH:
        return False
    return conn.execute("SELECT 1 FROM invite_codes WHERE code = ? AND used_at IS NULL "
                        "AND revoked_at IS NULL", (code,)).fetchone() is not None


def claim(conn, code: str | None, stamp: str) -> bool:
    """Use a code up, at `stamp`, if it's still usable - one UPDATE, so two
    sign-ups at once can't both use it. Not committed: auth.sign_up makes
    the account next, which commits both together (or rolls both back)."""
    cur = conn.execute("UPDATE invite_codes SET used_at = ? WHERE code = ? "
                       "AND used_at IS NULL AND revoked_at IS NULL", (stamp, normalize(code)))
    return cur.rowcount == 1


def record_user(conn, code: str | None, user_id: int, stamp: str) -> None:
    """Which account a claimed code made. Not committed (the caller does)."""
    conn.execute("UPDATE invite_codes SET used_by = ? WHERE code = ? AND used_at = ?",
                 (user_id, normalize(code), stamp))
