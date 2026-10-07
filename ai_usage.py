"""AI allowances per account, so the cost of the AI features stays predictable
however many people use the app (docs/AI_COSTS.md section 6, AI_PLAN step 7).

Allowances are counted in cost - micro-dollars worked out from each answer's
logged token counts at list price (ai_spend.cost_micro) - per day and per
calendar month (UTC), in buckets:

    individual   chat     $0.25 a day, $1.00 a month (+ the habit bonus)
                 decode   $0.30 a month (screenshot reads, CSV column help)
    advisor      chat     $2.00 a day, $8 a month
                 drafts   $6 a month (meeting prep, plan write-ups, advisor drafts)
                 decode   $3 a month             ($17 a month in all)

An individual's plan write-up comes out of their chat bucket, and so does
Teach It Back's explanation check (kind "grader", teach_back.py). The habit
bonus is earned by habits only, never bought: +$0.10 to the month's chat
allowance for each Monthly Walk finished in this month and the four before
(checkin.PREF_LOG), so at most +$0.50.

People never see dollars: status() turns what's left into an approximate
count - "about 12 messages left today" - using the person's own average cost
per use once they have a few, else a typical one (TYPICAL_MICRO).

Whoever clicks is the one counted - an advisor working in a client's account
uses the advisor's allowance. An account an admin marks unlimited
(manage_users.py ai-unlimited) has none; ai-limited puts the normal ones back.

Only counts and costs are kept (`ai_usage`: account, month, feature, how many,
cost this month, cost on the last day used) - never what was asked. The AI
gateway (ai_gateway.py) checks status() before each call and adds the cost
with add_cost() after it; the page counts the use with record() once the
answer has come.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

KINDS = ("chat", "screenshot", "csv", "plan", "prep", "grader",
         "glossary",   # an unknown word explained (glossary_ai.py): the chat bucket
         "draft")      # an advisor draft (advisor_drafts.py): the drafts bucket
# micro-dollars (docs/AI_COSTS.md section 6, approved October 2026)
ALLOWANCES = {
    "individual": {"chat": {"day": 250_000, "month": 1_000_000},
                   "decode": {"month": 300_000}},
    "advisor": {"chat": {"day": 2_000_000, "month": 8_000_000},
                "drafts": {"month": 6_000_000},
                "decode": {"month": 3_000_000}},
}
HABIT_BONUS_PER_WALK = 100_000   # +$0.10 for each finished Monthly Walk ...
HABIT_BONUS_MONTHS = 5           # ... in this month and the four before
HABIT_BONUS_MAX = 500_000        # +$0.50 at most
# what one use typically costs (docs/AI_COSTS.md sections 3-4), for the
# approximate count until the person has an average of their own
TYPICAL_MICRO = {"chat": 13_000, "plan": 24_000, "prep": 13_000, "screenshot": 26_000,
                 "csv": 700, "grader": 1_500, "glossary": 500, "draft": 15_000}
OWN_AVERAGE_AFTER = 3            # uses this month before their own average counts
# self-serve accounts use the AI only once their email is confirmed
CONFIRM_FOR_AI = True
# how each allowance is named to people: (one, many)
NOUNS = {"chat": ("message", "messages"), "screenshot": ("screenshot read", "screenshot reads"),
         "csv": ("CSV read", "CSV reads"), "plan": ("plan write-up", "plan write-ups"),
         "prep": ("set of talking points", "sets of talking points"),
         "grader": ("explanation check", "explanation checks"),
         "glossary": ("word look-up", "word look-ups"), "draft": ("draft", "drafts")}


def month_of(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


def day_of(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}-{now.day:02d}"


def resets_on(now: datetime | None = None) -> date:
    """The day this month's counts start again: the 1st of next month."""
    now = now or datetime.now(timezone.utc)
    return date(now.year + (now.month == 12), now.month % 12 + 1, 1)


def bucket_of(kind: str, is_advisor: bool) -> str:
    """The allowance `kind` comes out of: "chat", "drafts" (advisors) or
    "decode". An individual's plan write-up is chat."""
    if kind in ("screenshot", "csv"):
        return "decode"
    if kind in ("plan", "prep", "draft"):
        return "drafts" if is_advisor else "chat"
    return "chat"


def _side(row) -> str:
    return "advisor" if row and row["is_advisor"] else "individual"


def limit_for(conn, user_id: int, kind: str) -> int | None:
    """This account's monthly allowance for `kind`'s bucket, in micro-dollars
    (before any habit bonus), or None for unlimited."""
    row = conn.execute("SELECT is_advisor, ai_unlimited FROM users WHERE id = ?",
                       (user_id,)).fetchone()
    return _limit_of(row, kind)


def _limit_of(row, kind: str) -> int | None:
    if row and row["ai_unlimited"]:
        return None
    side = _side(row)
    return ALLOWANCES[side][bucket_of(kind, side == "advisor")]["month"]


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


def month_rows(conn, month: str) -> list:
    """Everyone's use in one month (YYYY-MM): rows of username, kind, used,
    cost_micro, by login then kind - the Admin portal's AI use table."""
    return conn.execute("SELECT u.username, a.kind, a.used, a.cost_micro FROM ai_usage a "
                        "JOIN users u ON u.id = a.user_id WHERE a.month = ? "
                        "ORDER BY u.username, a.kind", (month,)).fetchall()


def habit_bonus(saved_prefs: dict | None, now: datetime | None = None) -> int:
    """The month's habit bonus in micro-dollars: HABIT_BONUS_PER_WALK for each
    Monthly Walk finished in this month and the HABIT_BONUS_MONTHS - 1 before
    it (checkin.PREF_LOG holds the months), at most HABIT_BONUS_MAX."""
    import checkin
    now = now or datetime.now(timezone.utc)
    months, y, m = set(), now.year, now.month
    for _ in range(HABIT_BONUS_MONTHS):
        months.add(f"{y:04d}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    log = (saved_prefs or {}).get(checkin.PREF_LOG) or []
    walks = len({x for x in log if isinstance(x, str) and x in months})
    return min(HABIT_BONUS_MAX, walks * HABIT_BONUS_PER_WALK)


def status(conn, user_id: int, kind: str, now: datetime | None = None, *,
           user=None) -> dict:
    """What's left of `kind`'s allowance: {"used" (uses this month), "limit"
    and "left" (approximate counts for the month and for now - None when
    unlimited), "ok" (one more is allowed), "period" ("day" when today's
    allowance is what runs out first, else "month"), "resets" (the 1st of
    next month), "unconfirmed" (waiting on the email to be confirmed - then
    ok is False), "cost_used" / "cost_limit" / "cost_left" (micro-dollars,
    for the gateway and the admin - never shown to people)}. `user`: the
    account's users row when the caller has just read it
    (auth.LOGIN_COLUMNS) - else it's read here, once for both the allowance
    and the email check."""
    if user is None:
        user = conn.execute("SELECT is_advisor, ai_unlimited, email, email_verified_at "
                            "FROM users WHERE id = ?", (user_id,)).fetchone()
    now = now or datetime.now(timezone.utc)
    waiting = _waiting_of(user)
    rows = conn.execute("SELECT kind, used, cost_micro, day, day_cost_micro FROM ai_usage "
                        "WHERE user_id = ? AND month = ?", (user_id, month_of(now))).fetchall()
    mine = next((r for r in rows if r["kind"] == kind), None)
    n = mine["used"] if mine else 0
    base = {"used": n, "resets": resets_on(now), "unconfirmed": waiting, "period": "month"}
    if user and user["ai_unlimited"]:
        return {**base, "limit": None, "left": None, "ok": not waiting,
                "cost_used": sum(int(r["cost_micro"] or 0) for r in rows),
                "cost_limit": None, "cost_left": None}
    side = _side(user)
    bucket = bucket_of(kind, side == "advisor")
    allowance = ALLOWANCES[side][bucket]
    same = [r for r in rows if bucket_of(r["kind"], side == "advisor") == bucket]
    month_used = sum(int(r["cost_micro"] or 0) for r in same)
    today = day_of(now)
    day_used = sum(int(r["day_cost_micro"] or 0) for r in same if r["day"] == today)
    month_limit = allowance["month"]
    if side == "individual" and bucket == "chat":
        import prefs
        month_limit += habit_bonus(prefs.load(conn, user_id), now)
    cost_left, period = max(0, month_limit - month_used), "month"
    if "day" in allowance and allowance["day"] - day_used < cost_left:
        cost_left, period = max(0, allowance["day"] - day_used), "day"
    own = int(mine["cost_micro"] or 0) if mine else 0
    each = own // n if n >= OWN_AVERAGE_AFTER and own > 0 else TYPICAL_MICRO[kind]
    each = max(1, each)
    left = cost_left // each
    return {**base, "period": period, "limit": max(1, month_limit // each), "left": left,
            "ok": not waiting and left > 0, "cost_used": month_used,
            "cost_limit": month_limit, "cost_left": cost_left}


def record(conn, user_id: int, kind: str, now: datetime | None = None) -> None:
    """Count one use - called once the AI request has succeeded (a failed one
    doesn't use up the allowance)."""
    conn.execute("INSERT INTO ai_usage (user_id, month, kind, used) VALUES (?, ?, ?, 1) "
                 "ON CONFLICT (user_id, month, kind) DO UPDATE SET used = ai_usage.used + 1",
                 (user_id, month_of(now), kind))
    conn.commit()


def add_cost(conn, user_id: int, kind: str, cost: int, now: datetime | None = None) -> None:
    """Add one answer's cost (micro-dollars) to the account's month and day
    for `kind` - the AI gateway, after each successful call."""
    conn.execute(
        "INSERT INTO ai_usage (user_id, month, kind, used, cost_micro, day, day_cost_micro) "
        "VALUES (?, ?, ?, 0, ?, ?, ?) ON CONFLICT (user_id, month, kind) DO UPDATE SET "
        "cost_micro = ai_usage.cost_micro + excluded.cost_micro, "
        "day_cost_micro = CASE WHEN ai_usage.day = excluded.day "
        "THEN ai_usage.day_cost_micro + excluded.day_cost_micro "
        "ELSE excluded.day_cost_micro END, "
        "day = excluded.day",
        (user_id, month_of(now), kind, int(cost), day_of(now), int(cost)))
    conn.commit()


def set_unlimited(conn, user_id: int, flag: bool) -> None:
    conn.execute("UPDATE users SET ai_unlimited = ? WHERE id = ?", (1 if flag else None, user_id))
    conn.commit()


def left_text(st: dict, kind: str) -> str:
    """'About 37 messages left this month' ('... left today' when today's
    allowance runs out first), or '' when unlimited."""
    if st["limit"] is None:
        return ""
    one, many = NOUNS[kind]
    when = "today" if st.get("period") == "day" else "this month"
    return f"About {st['left']} {one if st['left'] == 1 else many} left {when}"


def used_up_text(st: dict, kind: str, app_name: str = "Northwend") -> str:
    """Why `kind` can't be used right now - for any status() with ok False
    (also with the app-wide ceiling's say, ai_spend.apply)."""
    if st.get("resting_why"):
        import ai_spend
        return ai_spend.resting_text(st["resting_why"], kind, st["resets"], app_name)
    if st.get("unconfirmed"):
        return ("Confirm your email to use this - open the link we sent you (you can send "
                "it again from the note at the top of the page).")
    many = NOUNS[kind][1]
    if st.get("period") == "day":
        return f"You've used today's {many}. They start again tomorrow."
    return (f"You've used this month's {many}. "
            f"They start again on {st['resets']:%B} {st['resets'].day}.")


# ---- when an AI request fails ---------------------------------------------- #
# One calm sentence per kind of failure, never the error's own text (it can
# hold status codes, request ids or the key's state). The server log gets the
# error's type, status and request id only; a request is only counted
# (record) once it has succeeded.
BUSY, UNAVAILABLE, REFUSED = "busy", "unavailable", "refused"
# HTTP statuses that mean "try again shortly": rate limited, overloaded, down
_BUSY_STATUSES = {408, 429, 500, 502, 503, 504, 529}


def failure_kind(exc: BaseException) -> str:
    """BUSY (rate limited, overloaded, timed out, couldn't connect - worth
    another try in a minute), REFUSED (the AI gateway didn't make the call:
    an allowance, the month's level, ai_gateway.Refused) or UNAVAILABLE (the
    key, the account or the request itself - needs someone to fix it)."""
    if getattr(exc, "calm_text", None):
        return REFUSED
    try:
        import anthropic
    except ImportError:   # pragma: no cover - the SDK is a requirement
        return UNAVAILABLE
    busy = tuple(getattr(anthropic, n) for n in (
        "RateLimitError", "OverloadedError", "ServiceUnavailableError", "InternalServerError",
        "APIConnectionError", "DeadlineExceededError", "RetryableError")
        if hasattr(anthropic, n))
    if isinstance(exc, busy) or getattr(exc, "status_code", None) in _BUSY_STATUSES:
        return BUSY
    return UNAVAILABLE


def failure_text(exc: BaseException, app_name: str = "Northwend", feature: str = "") -> str:
    """What to show when an AI request failed - one friendly sentence per
    kind. `feature` names what isn't available (default "Ask <app>")."""
    kind = failure_kind(exc)
    if kind == REFUSED:
        return exc.calm_text
    if kind == BUSY:
        return f"{app_name} is busy right now - try again in a minute."
    return f"{feature or 'Ask ' + app_name} isn't available right now."


def log_failure(exc: BaseException, kind: str) -> None:
    """For the server log only: the error's type, HTTP status and request id
    - never its text, which could echo part of a request (AI_PLAN 4.2)."""
    import sys
    status = getattr(exc, "status_code", None)
    request_id = getattr(exc, "request_id", None)
    print(f"[ai] {kind} request failed ({failure_kind(exc)}): {type(exc).__name__}"
          + (f", status {status}" if isinstance(status, int) else "")
          + (f", request {request_id}" if isinstance(request_id, str) else ""),
          file=sys.stderr)
