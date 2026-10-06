"""The 401(k) Menu Decoder without an account (master brief 8a; docs/PLAN.md
step 3 item 6, decision B12): `?decode=401k` draws the decoder before
sign-in (views/decoder_public.py), behind flag `decoder_public` and gate L0.

The same reading and table as the signed-in decoder (menu_decoder.py), with
nothing kept: the pasted list and the table live only in the visitor's
Streamlit session, in server memory. No AI, no fetching (only the fund data
already kept in security_info is read), no account row, no settings, no
counts per person, nothing logged.

The one thing written is a rate-limit count per internet address, so the
page can't be used as a free fund-data lookup or to tie up the server: a row
in the `signups` table (the hashed-address counts sign-up uses, tidied away
after a day by tidy.py and by sign-up itself) whose key is KEY_PREFIX plus
the SHA-256 of the address - never the address. The prefix keeps these rows
out of sign-up's own limits (they count by the bare hash, or by ok = 1) and
lets the app-wide cap count them. Standard library only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import auth

QUERY = "decode"                 # ?decode=401k
ROUTE = "401k"
KEY_PREFIX = "decoder:"          # signups.address_key for a decode
PER_ADDRESS_PER_HOUR = 20        # decodes from one internet address in an hour
PER_HOUR = 600                   # decodes app-wide in an hour, in case addresses are hidden

TOO_MANY_FROM_HERE = ("That's a lot of lists from here in the last hour. The decoder will be "
                      "ready again within the hour - nothing you pasted was kept.")
TOO_MANY_EVERYWHERE = ("Lots of people are using the decoder right now. Please try again in "
                       "a little while - nothing you pasted was kept.")


def wanted(query: dict) -> bool:
    """Whether this visit asks for the no-account decoder (?decode=401k)."""
    return str((query or {}).get(QUERY) or "").strip().lower() == ROUTE


def address_key(ip: str | None) -> str:
    """The count's key: the prefix and the address's SHA-256 (auth's hashing),
    or the prefix alone when the address isn't known."""
    return KEY_PREFIX + auth._address_key(ip)


def take(conn, ip: str | None, *, now: datetime | None = None) -> str | None:
    """Count one decode from `ip`, or say calmly why not now (and count
    nothing). Counts older than a day are tidied away first, as sign-up does."""
    now = now or datetime.now(timezone.utc)
    stamp, key = auth._utc(now), address_key(ip)
    hour_ago = auth._utc(now - timedelta(hours=1))
    conn.execute("DELETE FROM signups WHERE created_at < ?",
                 (auth._utc(now - timedelta(days=1)),))
    reason = None
    if key != KEY_PREFIX:
        here = conn.execute("SELECT COUNT(*) AS n FROM signups WHERE address_key = ? "
                            "AND created_at >= ?", (key, hour_ago)).fetchone()["n"]
        if here >= PER_ADDRESS_PER_HOUR:
            reason = TOO_MANY_FROM_HERE
    if reason is None:
        everyone = conn.execute("SELECT COUNT(*) AS n FROM signups WHERE address_key LIKE ? "
                                "AND created_at >= ?", (KEY_PREFIX + "%", hour_ago)
                                ).fetchone()["n"]
        if everyone >= PER_HOUR:
            reason = TOO_MANY_EVERYWHERE
    if reason is None:
        conn.execute("INSERT INTO signups (address_key, created_at, ok) VALUES (?, ?, 0)",
                     (key, stamp))
    conn.commit()
    return reason
