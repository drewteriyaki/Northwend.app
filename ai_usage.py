"""Monthly AI allowances per account, so the cost of the AI features stays
predictable however many people use the app.

Each AI feature has its own allowance per calendar month (UTC): Ask Northwend
messages, screenshot reads, CSV column help, plan write-ups and meeting-prep
talking points (meeting.py). Whoever
clicks is the one counted - an advisor working in a client's account uses
the advisor's allowance. Advisors get ADVISOR_SCALE times the amounts; an
account an admin marks unlimited (manage_users.py ai-unlimited) has none.

Only counts are kept (`ai_usage`: account, month, feature, how many) - never
what was asked.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

# per account per month
LIMITS = {"chat": 100, "screenshot": 10, "csv": 20, "plan": 5, "prep": 20}
ADVISOR_SCALE = 5
# self-serve accounts use the AI only once their email is confirmed
CONFIRM_FOR_AI = True
# how each allowance is named to people: (one, many)
NOUNS = {"chat": ("message", "messages"), "screenshot": ("screenshot read", "screenshot reads"),
         "csv": ("CSV read", "CSV reads"), "plan": ("plan write-up", "plan write-ups"),
         "prep": ("set of talking points", "sets of talking points")}


def month_of(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


def resets_on(now: datetime | None = None) -> date:
    """The day this month's counts start again: the 1st of next month."""
    now = now or datetime.now(timezone.utc)
    return date(now.year + (now.month == 12), now.month % 12 + 1, 1)


def limit_for(conn, user_id: int, kind: str) -> int | None:
    """This account's monthly allowance for `kind`, or None for unlimited."""
    row = conn.execute("SELECT is_advisor, ai_unlimited FROM users WHERE id = ?",
                       (user_id,)).fetchone()
    return _limit_of(row, kind)


def _limit_of(row, kind: str) -> int | None:
    if row and row["ai_unlimited"]:
        return None
    return LIMITS[kind] * (ADVISOR_SCALE if row and row["is_advisor"] else 1)


def awaiting_confirmation(conn, user_id: int) -> bool:
    """A self-serve account whose email isn't confirmed yet: the AI features
    wait until it is (when CONFIRM_FOR_AI), so made-up sign-ups can't run up
    AI costs. Accounts from an admin or advisor have no email - never waiting."""
    if not CONFIRM_FOR_AI:
        return False
    row = conn.execute("SELECT email, email_verified_at FROM users WHERE id = ?",
                       (user_id,)).fetchone()
    return _waiting_of(row)


def _waiting_of(row) -> bool:
    return CONFIRM_FOR_AI and bool(row and row["email"] and not row["email_verified_at"])


def used(conn, user_id: int, kind: str, now: datetime | None = None) -> int:
    row = conn.execute("SELECT used FROM ai_usage WHERE user_id = ? AND month = ? AND kind = ?",
                       (user_id, month_of(now), kind)).fetchone()
    return row["used"] if row else 0


def status(conn, user_id: int, kind: str, now: datetime | None = None, *,
           user=None) -> dict:
    """{"used", "limit" (None = unlimited), "left" (None = unlimited), "ok"
    (one more is allowed), "resets" (a date), "unconfirmed" (waiting on the
    email to be confirmed - then ok is False)}. `user`: the account's users
    row when the caller has just read it (auth.LOGIN_COLUMNS) - else it's read
    here, once for both the allowance and the email check."""
    if user is None:
        user = conn.execute("SELECT is_advisor, ai_unlimited, email, email_verified_at "
                            "FROM users WHERE id = ?", (user_id,)).fetchone()
    n, limit = used(conn, user_id, kind, now), _limit_of(user, kind)
    left = None if limit is None else max(0, limit - n)
    waiting = _waiting_of(user)
    return {"used": n, "limit": limit, "left": left,
            "ok": not waiting and (left is None or left > 0),
            "resets": resets_on(now), "unconfirmed": waiting}


def record(conn, user_id: int, kind: str, now: datetime | None = None) -> None:
    """Count one use - called just before the AI request is sent."""
    conn.execute("INSERT INTO ai_usage (user_id, month, kind, used) VALUES (?, ?, ?, 1) "
                 "ON CONFLICT (user_id, month, kind) DO UPDATE SET used = ai_usage.used + 1",
                 (user_id, month_of(now), kind))
    conn.commit()


def set_unlimited(conn, user_id: int, flag: bool) -> None:
    conn.execute("UPDATE users SET ai_unlimited = ? WHERE id = ?", (1 if flag else None, user_id))
    conn.commit()


def left_text(st: dict, kind: str) -> str:
    """'37 of 100 messages left this month', or '' when unlimited."""
    if st["limit"] is None:
        return ""
    one, many = NOUNS[kind]
    return f"{st['left']} of {st['limit']} {many if st['limit'] != 1 else one} left this month"


def used_up_text(st: dict, kind: str) -> str:
    """Why `kind` can't be used right now - for any status() with ok False."""
    if st.get("unconfirmed"):
        return ("Confirm your email to use this - open the link we sent you (you can send "
                "it again from the note at the top of the page).")
    one, many = NOUNS[kind]
    return (f"You've used this month's {st['limit']} {many if st['limit'] != 1 else one}. "
            f"They start again on {st['resets']:%B} {st['resets'].day}.")
