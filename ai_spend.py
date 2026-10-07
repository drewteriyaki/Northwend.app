"""The app-wide AI spend for the month, and the ceiling over it (PLAN 1a.6,
docs/AI_COSTS.md section 7). The first slice of the AI gateway (AI_PLAN step 6).

Every AI answer's token counts are added to one row per (month, helper,
model) in `ai_spend`, with an estimated cost in micro-dollars from PRICES.
Counts only: never the question, the answer, a name or an account - the
table has no user_id and no text column (so it isn't account data: not in
admin.ACCOUNT_TABLES or export.OWN). The AI gateway (ai_gateway.py) calls
note() right after each successful answer; it writes only once the app has
called use_db().

The month's total against the ceiling (NORTHWEND_AI_CEILING_USD, default
100) sets the level everything AI follows:

    under 50%   normal
    50%         alert    - the admin is emailed (ALERT_EMAIL), counts only
    80%         reduced  - emailed again; chat answers are shorter and at low
                           effort; the optional helpers (screenshot reads, CSV
                           column guesses, plan next steps, talking points) rest
    95%         closing  - no new conversations; open ones may finish
    100%        resting  - every AI feature shows the calm "resting" line

The same table counts Ask Northwend's output-check breaks (note_break: a
row per kind of break, "check:<kind>", with no tokens and no cost); summary()
keeps them out of the answers and lists them apart for Admin.

Each email goes once per threshold per month (an `ai_alerts` row claims it,
so two processes can't both send). The wording people see never says
"limit", "budget" or "cost".
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone

import settings

# Dollars per million tokens - the same number is micro-dollars per token.
# (input, output, cache write (5 min), cache read). From docs/AI_COSTS.md
# section 1, Anthropic's list prices as of 2026-09-25. VERIFY on Anthropic's
# pricing page before relying on them.
PRICES = {
    "claude-sonnet-5": (2.00, 10.00, 2.50, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.20),
    "claude-haiku-4-5-20251001": (1.00, 5.00, 1.25, 0.10),
}
# a model not in the table is priced as the dearest one, so it's never undercounted
FALLBACK_PRICE = max(PRICES.values(), key=lambda p: p[1])

CEILING_DEFAULT_USD = 100
NORMAL, ALERT, REDUCED, CLOSING, RESTING = "normal", "alert", "reduced", "closing", "resting"
# (percent of the ceiling, level), highest first
LEVELS = ((100, RESTING), (95, CLOSING), (80, REDUCED), (50, ALERT))
ALERT_AT = (50, 80)                 # the admin is emailed at these percents
CHAT_MAX_TOKENS_REDUCED = 1500      # a chat answer's length from 80% (AI_COSTS 7.1)
CHAT_EFFORT_REDUCED = "low"
# the helpers that rest from 80% (ai_usage kinds); chat keeps going to 95%
OPTIONAL = ("screenshot", "csv", "plan", "prep", "grader")
# how each feature is named in the resting line
FEATURES = {"chat": None, "screenshot": "Reading screenshots", "csv": "Guessing the columns",
            "plan": "Writing suggested next steps", "prep": "Drafting talking points",
            "grader": "Checking explanations"}

USAGE_FIELDS = (("input_tokens", "input_tokens"), ("output_tokens", "output_tokens"),
                ("cache_write_tokens", "cache_creation_input_tokens"),
                ("cache_read_tokens", "cache_read_input_tokens"))


def month_of(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


def resets_on(now: datetime | None = None) -> date:
    """The 1st of next month (UTC), when the month's total starts again."""
    now = now or datetime.now(timezone.utc)
    return date(now.year + (now.month == 12), now.month % 12 + 1, 1)


def _stamp(now: datetime) -> str:
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- what one answer used --------------------------------------------------- #

def _count(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0


def usage_of(response) -> dict:
    """{"input_tokens", "output_tokens", "cache_write_tokens",
    "cache_read_tokens"} from an API response's `usage` - 0 for anything
    missing (a test's stand-in has none). Numbers only, nothing else of it.
    When some of the cache writes were for the 1-hour cache (the shared
    first block, ai_gateway.build_request), "cache_write_1h_tokens" says how
    many of them - they cost twice the input price, not 1.25 times."""
    usage = getattr(response, "usage", None)
    out = {}
    for name, attr in USAGE_FIELDS:
        out[name] = _count(getattr(usage, attr, None) if usage is not None else None)
    long_writes = _count(getattr(getattr(usage, "cache_creation", None),
                                 "ephemeral_1h_input_tokens", None))
    if long_writes:
        out["cache_write_1h_tokens"] = min(long_writes, out["cache_write_tokens"])
    return out


def cost_micro(model: str, usage: dict) -> int:
    """The estimated cost of `usage` on `model`, in micro-dollars."""
    inp, out, write, read = PRICES.get(model, FALLBACK_PRICE)
    long_writes = usage.get("cache_write_1h_tokens", 0)
    return round(usage.get("input_tokens", 0) * inp + usage.get("output_tokens", 0) * out
                 + (usage.get("cache_write_tokens", 0) - long_writes) * write
                 + long_writes * inp * 2
                 + usage.get("cache_read_tokens", 0) * read)


def record(conn, helper: str, model: str, usage: dict, now: datetime | None = None) -> int:
    """Add one answer to this month's row for (helper, model). Returns its
    cost in micro-dollars."""
    now = now or datetime.now(timezone.utc)
    cost = cost_micro(model, usage)
    conn.execute(
        "INSERT INTO ai_spend (month, helper, model, calls, input_tokens, output_tokens, "
        "cache_write_tokens, cache_read_tokens, cost_micro, updated_at) "
        "VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?) ON CONFLICT (month, helper, model) DO UPDATE SET "
        "calls = ai_spend.calls + 1, "
        "input_tokens = ai_spend.input_tokens + excluded.input_tokens, "
        "output_tokens = ai_spend.output_tokens + excluded.output_tokens, "
        "cache_write_tokens = ai_spend.cache_write_tokens + excluded.cache_write_tokens, "
        "cache_read_tokens = ai_spend.cache_read_tokens + excluded.cache_read_tokens, "
        "cost_micro = ai_spend.cost_micro + excluded.cost_micro, "
        "updated_at = excluded.updated_at",
        (month_of(now), helper, model, usage.get("input_tokens", 0),
         usage.get("output_tokens", 0), usage.get("cache_write_tokens", 0),
         usage.get("cache_read_tokens", 0), cost, _stamp(now)))
    conn.commit()
    return cost


# ---- the month's total and the level ---------------------------------------- #

def ceiling_micro() -> int:
    """The month's ceiling in micro-dollars (settings.ai_ceiling_usd)."""
    return round(settings.ai_ceiling_usd(CEILING_DEFAULT_USD) * 1_000_000)


def month_total(conn, now: datetime | None = None) -> int:
    """This month's estimated spend, all helpers, in micro-dollars."""
    row = conn.execute("SELECT COALESCE(SUM(cost_micro), 0) AS n FROM ai_spend WHERE month = ?",
                       (month_of(now),)).fetchone()
    return int(row["n"] or 0)


def percent(spent: int, ceiling: int) -> float:
    return 100.0 if ceiling <= 0 else spent * 100.0 / ceiling


def level_of(spent: int, ceiling: int) -> str:
    """NORMAL, ALERT, REDUCED, CLOSING or RESTING for `spent` of `ceiling`."""
    pct = percent(spent, ceiling)
    for at, level in LEVELS:
        if pct >= at:
            return level
    return NORMAL


def level(conn, now: datetime | None = None) -> str:
    return level_of(month_total(conn, now), ceiling_micro())


def summary(conn, now: datetime | None = None) -> dict:
    """For the Admin page - counts only: {"month", "spent" and "ceiling"
    (micro-dollars), "percent", "level", "projected" (micro-dollars at this
    month's daily rate so far), "calls", "rows" (per helper and model),
    "breaks" (the output check's counts, breaks())}."""
    now = now or datetime.now(timezone.utc)
    every = [dict(r) for r in conn.execute(
        "SELECT helper, model, calls, input_tokens, output_tokens, cache_write_tokens, "
        "cache_read_tokens, cost_micro FROM ai_spend WHERE month = ? ORDER BY helper, model",
        (month_of(now),))]
    rows = [r for r in every if not r["helper"].startswith(CHECK_PREFIX)]
    spent, ceiling = sum(r["cost_micro"] for r in rows), ceiling_micro()
    days = (resets_on(now) - date(now.year, now.month, 1)).days
    elapsed = max(1.0, now.day - 1 + now.hour / 24)
    return {"month": month_of(now), "spent": spent, "ceiling": ceiling,
            "percent": percent(spent, ceiling), "level": level_of(spent, ceiling),
            "projected": round(spent * days / elapsed), "calls": sum(r["calls"] for r in rows),
            "rows": rows, "breaks": breaks(every)}


def dollars(micro: int) -> str:
    return f"${micro / 1_000_000:,.2f}"


# ---- what each feature may do at a level ------------------------------------- #

def gate(level_: str, kind: str, *, conversation_open: bool = False) -> str | None:
    """Why `kind` (an ai_usage kind) can't run at `level_`, or None if it can:
    "resting" (100%: everything), "closed" (95%: a new conversation),
    "paused" (from 80%: the optional helpers)."""
    if level_ == RESTING:
        return "resting"
    if kind == "chat":
        return "closed" if level_ == CLOSING and not conversation_open else None
    if kind in OPTIONAL and level_ in (REDUCED, CLOSING):
        return "paused"
    return None


def apply(status: dict, level_: str, kind: str, *, conversation_open: bool = False) -> dict:
    """An ai_usage.status() dict with the ceiling's say added: "level",
    "resting_why" (gate's answer) and "ok" False when the feature rests."""
    why = gate(level_, kind, conversation_open=conversation_open)
    return {**status, "level": level_, "resting_why": why, "ok": status["ok"] and not why}


def resting_text(why: str, kind: str, resets: date, app_name: str = "Northwend") -> str:
    """The calm line for a feature that's resting - it names the day it's
    back, and never says why in money terms."""
    when = f"{resets:%B} {resets.day}"
    rest = f"Everything else in {app_name} works as usual."
    if why == "closed":
        return (f"Ask {app_name} isn't starting new conversations until {when}. {rest}")
    if why == "paused":
        return f"{FEATURES.get(kind) or 'This'} is resting until {when}. {rest}"
    return f"Ask {app_name} is resting until {when}. {rest}"


def chat_settings(level_: str) -> dict:
    """Overrides for advisor.stream_reply at this level ({} = as usual)."""
    if level_ in (REDUCED, CLOSING):
        return {"max_tokens": CHAT_MAX_TOKENS_REDUCED, "effort": CHAT_EFFORT_REDUCED}
    return {}


# ---- the admin's emails -------------------------------------------------------- #

def _alert_email(spent: int, ceiling: int, projected: int, at: int, copy: str,
                 month: str) -> tuple[str, str]:
    label = f" ({copy})" if copy else ""
    pct = percent(spent, ceiling)
    then = ("Chat answers are now shorter, and screenshot reads, column guesses, plan next "
            "steps and talking points rest until next month. New conversations close at 95%, "
            "and everything AI rests at 100%." if at >= 80 else
            "Nothing changes for anyone yet. At 80% chat answers get shorter and the optional "
            "AI helpers rest.")
    subject = f"Northwend{label}: AI use has reached {at}% of this month's ceiling"
    text = "\n\n".join([
        f"AI use in {month}: {dollars(spent)} of the {dollars(ceiling)} ceiling "
        f"({pct:.0f}%), estimated from token counts at list price.",
        f"At this month's rate so far it would reach {dollars(projected)} by the month's end.",
        then,
        "The Admin page shows it by helper. To change the ceiling, set "
        "NORTHWEND_AI_CEILING_USD in the app's settings.",
        "Totals only - no one's name or messages are in this email."]) + "\n"
    return subject, text


def maybe_alert(conn, *, send: bool = True, copy: str = "",
                now: datetime | None = None) -> int | None:
    """Email the admin when this month's total has passed 50% or 80% and that
    threshold wasn't emailed yet this month. One email names the highest
    threshold passed; every threshold passed is claimed. Returns the percent
    emailed, or None. send=False does nothing (local runs)."""
    if not send:
        return None
    import mailer
    now = now or datetime.now(timezone.utc)
    s = summary(conn, now)
    reached = [at for at in ALERT_AT if s["percent"] >= at]
    if not reached:
        return None
    month, stamp, claimed = s["month"], _stamp(now), []
    for at in reached:
        cur = conn.execute("INSERT INTO ai_alerts (month, level, sent_at) VALUES (?, ?, ?) "
                           "ON CONFLICT (month, level) DO NOTHING", (month, at, stamp))
        if cur.rowcount > 0:
            claimed.append(at)
    conn.commit()
    if not claimed:
        return None
    import error_alerts
    subject, text = _alert_email(s["spent"], s["ceiling"], s["projected"], max(claimed), copy,
                                 month)
    if mailer.send(error_alerts.alert_to(), subject, text):
        return max(claimed)
    for at in claimed:   # didn't go: the next answer tries again
        conn.execute("DELETE FROM ai_alerts WHERE month = ? AND level = ? AND sent_at = ?",
                     (month, at, stamp))
    conn.commit()
    return None


# ---- the hook every AI module calls ------------------------------------------- #

_SINK: dict = {"db": None, "send": False, "copy": ""}


def use_db(db: str | None, *, send: bool = False, copy: str = "") -> None:
    """Where note() records answers (the app sets this once a run). `send`:
    email the admin at the thresholds (hosted copies only)."""
    _SINK.update(db=db, send=send, copy=copy)


def sink_db() -> str | None:
    """The database use_db() named (None until then) - the AI gateway checks
    allowances and the level there too."""
    return _SINK["db"]


def note(response, helper: str, model: str, *, also=None) -> None:
    """Record one successful answer's token counts - never raises, so a
    failing count can't break the feature. Does nothing until use_db().
    `also(conn, cost)`: run on the same connection with the answer's cost in
    micro-dollars (ai_gateway adds it to the person's own allowance there -
    this table itself never holds who asked)."""
    db = _SINK["db"]
    if not db:
        return
    try:
        from portfolio import connect
        usage = usage_of(response)
        conn = connect(db)
        try:
            cost = record(conn, helper, model, usage)
            if also is not None:
                also(conn, cost)
            maybe_alert(conn, send=_SINK["send"], copy=_SINK["copy"])
        finally:
            conn.close()
    except Exception as exc:   # counts only; the answer itself is fine
        try:
            print(f"[ai spend] couldn't record a {helper} answer: {type(exc).__name__}",
                  file=sys.stderr)
        except Exception:
            pass


# ---- the output check's breaks, for the Admin page ------------------------------ #
# A break of the conclusion policy's output check (ai_policy, AI_PLAN 7.2) is
# counted in this same table, as a row per (month, "check:<kind>", what
# followed) with no tokens and no cost: "retried" when the model was asked
# once more, "fallback" when the second draft broke too and the calm line was
# shown. The kind of break only - never the text, never who.
CHECK_PREFIX = "check:"
RETRIED, FELL_BACK = "retried", "fallback"


def note_break(kinds, retried: bool, now: datetime | None = None) -> None:
    """Count one break of the output check, once for each of its `kinds`
    (ai_policy.KINDS; anything else is ignored). `retried`: it was the
    second draft that broke (the calm fallback line was shown). Never
    raises; does nothing until use_db()."""
    db = _SINK["db"]
    if not db:
        return
    try:
        import ai_policy
        from portfolio import connect
        conn = connect(db)
        try:
            for kind in sorted(set(kinds or ()) & set(ai_policy.KINDS)):
                record(conn, CHECK_PREFIX + kind, FELL_BACK if retried else RETRIED, {}, now)
        finally:
            conn.close()
    except Exception as exc:   # counts only; the answer itself is fine
        try:
            print(f"[ai spend] couldn't count a check: {type(exc).__name__}", file=sys.stderr)
        except Exception:
            pass


def breaks(rows) -> list[dict]:
    """The output check's counts out of summary()'s rows: [{"kind",
    "retried", "fallback"}], most first."""
    out: dict = {}
    for r in rows:
        if r["helper"].startswith(CHECK_PREFIX) and r["model"] in (RETRIED, FELL_BACK):
            kind = r["helper"][len(CHECK_PREFIX):]
            out.setdefault(kind, {"kind": kind, RETRIED: 0, FELL_BACK: 0})[r["model"]] += r["calls"]
    return sorted(out.values(), key=lambda b: (-(b[RETRIED] + b[FELL_BACK]), b["kind"]))

