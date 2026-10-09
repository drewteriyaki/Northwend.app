"""Invite someone: each login's own link to share with friends (the name
menu's "Invite someone" window, views/invite_friend.py). Standard library
only, no Streamlit.

Sign-up is open (gate L0 on), so a link opens nothing new: it's the usual
Create account page with one friendly line on top (ARRIVED). It never shows
who sent it - no name, no email. Northwend sends nothing to the friend and
collects no addresses: the person copies their link (and, if they like, the
ready-made MESSAGE) and shares it however they want. While L0 is off
(sign-up by invite code, invite_codes.py) the window isn't offered at all.

One row per login in table invite_links: the code, when it was made and
`joined` - how many accounts were made through this person's links. A count
only: nothing records which account came through which link, so nobody -
the inviter, an admin - can see who joined. No rewards, no ranking. "Make a
new link" replaces the code (the count stays with the person); the old link
then just opens the plain sign-up, with no error. Deleted with the account
(admin.ACCOUNT_TABLES; the accounts made through it stay), in the person's
own export (export.OWN).

The code isn't a secret - it only says "a friend sent this" - so it's kept
as is (it has to be looked up when someone arrives). 10 characters from
invite_codes.ALPHABET (no look-alikes), which tells it apart from an
admin's 8-character invite code and an advisor's much longer setup link,
both of which also arrive as ?invite=.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from invite_codes import ALPHABET

LENGTH = 10
PARAM = "invite"   # the link's ?invite=<code> (shared with advisors' setup links)

# the window's words (calm: no rewards, no counts to chase)
TITLE = "Invite someone"
INTRO = "Know someone who'd like a calm place to start? Share your link."
PRIVATE = ("Northwend doesn't email anyone or ask for their address - you share the link "
           "however you like. It doesn't show them your name or email, and it only tells you "
           "how many people joined with it, never who.")
ADVISOR_NOTE = ("This link invites someone to use Northwend on their own. To add a client, "
                "use Your clients.")
NEW_LINK_HELP = "Your old link will then just open the usual sign-up."
NEW_LINK_DONE = "Here's your new link. The old one now just opens the usual sign-up."
# what the sign-up page says when someone arrives through a link
ARRIVED = "A friend invited you to Northwend."


def message(link: str) -> str:
    """The ready-to-paste note to send with the link."""
    return ("I've been using Northwend to learn about investing - it's free and never sells "
            f"you anything. Here's a link: {link}")


def joined_words(n: int) -> str:
    """The window's count line - a number, never who."""
    if n <= 0:
        return "No one has joined with your link yet."
    return f"{n} {'person has' if n == 1 else 'people have'} joined with your link."


def _stamp(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize(code: str | None) -> str:
    """A code from an address, as stored: upper case, no spaces or dashes."""
    return "".join(ch for ch in str(code or "").upper() if ch not in " -\t\n")


def looks_like(code: str | None) -> bool:
    """Whether ?invite= holds a personal link's code (not a setup link's
    token or an admin's code): LENGTH characters from ALPHABET."""
    raw = str(code or "").strip()
    return len(raw) == LENGTH and all(ch in ALPHABET for ch in raw.upper())


def link(app_address: str, code: str) -> str:
    """The full link: the app's own address (APP_URL - never the browser's)."""
    return f"{(app_address or '').rstrip('/')}/?{PARAM}={code}"


def _new_code(conn) -> str:
    while True:
        code = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
        if not conn.execute("SELECT 1 FROM invite_links WHERE code = ?", (code,)).fetchone():
            return code


def code_for(conn, user_id: int, *, now: datetime | None = None) -> str:
    """This login's code, made the first time it's asked for."""
    row = conn.execute("SELECT code FROM invite_links WHERE user_id = ?", (user_id,)).fetchone()
    if row:
        return row["code"]
    code = _new_code(conn)
    conn.execute("INSERT INTO invite_links (user_id, code, created_at, joined) "
                 "VALUES (?, ?, ?, 0)", (user_id, code, _stamp(now)))
    conn.commit()
    return code


def new_code(conn, user_id: int, *, now: datetime | None = None) -> str:
    """Make a new link: a fresh code replaces the old one (which then opens
    the plain sign-up); the count stays."""
    if not conn.execute("SELECT 1 FROM invite_links WHERE user_id = ?", (user_id,)).fetchone():
        return code_for(conn, user_id, now=now)
    code = _new_code(conn)
    conn.execute("UPDATE invite_links SET code = ?, created_at = ? WHERE user_id = ?",
                 (code, _stamp(now), user_id))
    conn.commit()
    return code


def valid(conn, code: str | None) -> bool:
    """Whether a code is someone's current link."""
    if not looks_like(code):
        return False
    return conn.execute("SELECT 1 FROM invite_links WHERE code = ?",
                        (normalize(code),)).fetchone() is not None


def count_join(conn, code: str | None) -> None:
    """An account was just made through `code`: one more on its count (and
    nothing else - not which account). Not committed: auth.sign_up commits
    it with the new account."""
    if looks_like(code):
        conn.execute("UPDATE invite_links SET joined = joined + 1 WHERE code = ?",
                     (normalize(code),))


def joined(conn, user_id: int) -> int:
    """How many accounts were made through this login's links."""
    row = conn.execute("SELECT joined FROM invite_links WHERE user_id = ?",
                       (user_id,)).fetchone()
    return int(row["joined"] or 0) if row else 0


def total_joined(conn) -> int:
    """Admin's total: accounts made from invite links (of people who still
    have an account to count them) - a number, never names."""
    row = conn.execute("SELECT COALESCE(SUM(joined), 0) AS n FROM invite_links").fetchone()
    return int(row["n"] or 0)
