"""One-click unsubscribe (PLAN 1a.8, audit 1.7c) for the emails someone gets
again and again: the Monthly Walk's reminder (checkin_email.py), the
advisors' Monday email (weekly_email.py) and Trail Conditions
(trail_conditions.py).

Each of those emails carries a link, <app>/?unsubscribe=<token>, that turns
that one email off with no sign-in, and the same address in a
List-Unsubscribe header (mailer.unsubscribe_headers). The token is like
the confirm and reset links' (auth.py): 256 random bits, only its hash kept
in email_tokens, with its own purpose per email (PURPOSES). Unlike them it
is long-lived and can be used again (a second click just says the same),
and each email gets a fresh one - an earlier email's link keeps working
until it expires. It does one thing: turn that email off for that account.
It never signs anyone in, shows nothing of the account, and stops working
when the account's email changes (like every link in email_tokens).

Streamlit can't answer a POST, so the RFC 8058 one-click POST that some
mail apps send to the header's address isn't handled here (see
mailer.unsubscribe_headers); the link itself, opened in a browser, is.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

import auth
import checkin
import prefs

LIFE_DAYS = 365   # an old email's link still works for a year
# which email -> its token's purpose in email_tokens
PURPOSES = {"walk": "unsub_walk", "weekly": "unsub_weekly", "trail": "unsub_trail"}
KIND_OF = {v: k for k, v in PURPOSES.items()}
# where each is turned back on, for the page the link opens
WHERE = {"walk": "Account, under Monthly walk",
         "weekly": "Your clients, under How clients see you",
         "trail": "Account, under Trail Conditions"}


def new_token(conn, user_id: int, kind: str, email: str, *,
              now: datetime | None = None) -> str:
    """A fresh unsubscribe token for one email to `email`. Only its hash is
    kept; tokens past their date (anyone's) are tidied away."""
    now = now or datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM email_tokens WHERE expires_at <= ?", (auth._utc(now),))
    conn.execute("INSERT INTO email_tokens (token_hash, user_id, purpose, email, created_at, "
                 "expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                 (auth._token_hash(token), user_id, PURPOSES[kind], email, auth._utc(now),
                  auth._utc(now + timedelta(days=LIFE_DAYS))))
    conn.commit()
    return token


def link(app_url: str, token: str) -> str:
    return f"{app_url.rstrip('/')}/?unsubscribe={token}"


def turn_off(p: dict, kind: str) -> dict:
    """The person's settings with that email turned off."""
    if kind == "walk":
        p[checkin.PREF_EMAIL] = False
    elif kind == "trail":
        import trail_conditions   # (it imports this module)
        trail_conditions.set_on(p, False)
    else:
        import weekly_email   # (it imports this module)
        p[weekly_email.PREF_OFF] = True
    return p


def use(conn, token: str | None, *, now: datetime | None = None) -> dict:
    """Open an unsubscribe link: {"ok", "kind"}. A live token of one of
    PURPOSES whose email is still the account's turns that email off for
    that account; anything else (unknown, expired, another kind of link, an
    email changed since) changes nothing and answers ok False."""
    now = now or datetime.now(timezone.utc)
    if not token:
        return {"ok": False, "kind": None}
    marks = ", ".join("?" for _ in PURPOSES)
    row = conn.execute(
        "SELECT t.user_id, t.purpose FROM email_tokens t JOIN users u ON u.id = t.user_id "
        f"WHERE t.token_hash = ? AND t.purpose IN ({marks}) AND t.expires_at > ? "
        "AND t.email = u.email",
        (auth._token_hash(str(token)), *PURPOSES.values(), auth._utc(now))).fetchone()
    if row is None:
        return {"ok": False, "kind": None}
    kind = KIND_OF[row["purpose"]]
    prefs.save(conn, row["user_id"], turn_off(prefs.load(conn, row["user_id"]), kind))
    return {"ok": True, "kind": kind}
