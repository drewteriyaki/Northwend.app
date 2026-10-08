"""Home's "This month" column: which suggestions the person marked done or
put away (views/dashboard_page.py).

Each suggestion on Home's right-hand column (today's minute, the route's next
step, the mix against its target, the money checks, the drill, the practice
challenge, the kit, the news) can be marked Done or put away with Not now. Both
last until the period ends - the month for most, the week for the drill and the
news, the day for today's minute - and then it comes back.
What's kept, in the login's own settings (prefs key PREF), is only the
suggestion's key, the period's id and "done" or "away": never a figure, a
ticker or any words. Cards that already keep their own state (the monthly
walk, the weekly summary, the season, the storm note, the year card, the
account map line) use their own and are not listed here.
"""

from __future__ import annotations

from datetime import date, datetime

PREF = "home_tasks"
DONE, AWAY = "done", "away"
MONTH, WEEK, DAY = "month", "week", "day"

# key: (period kind, Done offered too). The words on the buttons are fixed.
TASKS = {
    "minute": (DAY, False),
    "route": (MONTH, True),
    "mix": (MONTH, True),
    "checks": (MONTH, True),
    "drill": (WEEK, False),
    "challenge": (MONTH, False),
    "kit": (MONTH, False),
    "news": (WEEK, False),
    "wins": (MONTH, True),
}

TITLE = "This month"
DONE_LABEL = "Done"
AWAY_LABEL = "Not now"
DONE_HELP = "Marked done for now - it comes back next time."
AWAY_HELP = "Out of the way until next time, then it comes back."
PUT_AWAY_LINE = "Put away for now: {names}. They come back next time."
BRING_BACK = "Bring them back"

# what a put-away suggestion is called in the line above
NAMES = {"minute": "today's minute", "route": "your next step", "mix": "your mix", "checks": "money checks",
         "drill": "this week's drill", "challenge": "the practice challenge",
         "kit": "your kit", "news": "news",
         "wins": "your new win"}

# the mix card (fixed words; percentages only)
MIX_TITLE = "Your mix"
MIX_OVER = "{label} is {points} points over your target."
MIX_UNDER = "{label} is {points} points under your target."
MIX_WITHIN = "Each part is within your target band."
MIX_NO_TARGET = "No target mix set yet. With one, this card shows how far each part is from it."
MIX_LINK = "Open your target mix"
MIX_NOTE = "By asset class, against the target you set. For learning, not advice."

# the holdings list in the middle
HOLDINGS_TITLE = "Holdings"
HOLDINGS_MORE = "{n} more in the full table below."
FULL_TABLE = "All holdings - the full table"
LIST_LIMIT = 8
MASK = "•••"   # dashboard.MASK


def today() -> date:
    return datetime.now().date()


def period_id(kind: str, d: date) -> str:
    """'2026-10' for a month, '2026-W41' for an ISO week, '2026-10-07' for a
    day."""
    if kind == DAY:
        return d.isoformat()
    if kind == WEEK:
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    return f"{d:%Y-%m}"


def task_period(key: str, d: date) -> str:
    return period_id(TASKS[key][0], d)


def status(prefs: dict, key: str, d: date) -> str | None:
    """'done' / 'away' for this period, else None (shown)."""
    kept = (prefs or {}).get(PREF)
    if not isinstance(kept, dict):
        return None
    entry = kept.get(key)
    if (isinstance(entry, list) and len(entry) == 2 and entry[0] == task_period(key, d)
            and entry[1] in (DONE, AWAY)):
        return entry[1]
    return None


def hidden(prefs: dict, key: str, d: date) -> bool:
    return status(prefs, key, d) is not None


def put_away(prefs: dict, d: date) -> list[str]:
    """The keys put away or done this period, in TASKS order."""
    return [k for k in TASKS if hidden(prefs, k, d)]


def with_mark(prefs: dict, key: str, d: date, mark: str | None) -> dict:
    """A copy of `prefs` with `key` marked for this period (None: shown
    again). Only known keys and marks; entries for past periods are dropped."""
    if key not in TASKS or mark not in (DONE, AWAY, None):
        return dict(prefs)
    out = dict(prefs)
    kept = {k: v for k, v in (out.get(PREF) or {}).items()
            if k in TASKS and isinstance(v, list) and len(v) == 2
            and v[0] == task_period(k, d)}
    if mark is None:
        kept.pop(key, None)
    else:
        kept[key] = [task_period(key, d), mark]
    if kept:
        out[PREF] = kept
    else:
        out.pop(PREF, None)
    return out


def cleared(prefs: dict) -> dict:
    """Every suggestion shown again (Bring them back)."""
    out = dict(prefs)
    out.pop(PREF, None)
    return out


def mix_lines(actual: dict, targets: dict, band: float, masked: bool = False) -> list[str]:
    """The mix card's lines: each asset class past its band, largest first,
    in whole points (MASK while amounts are hidden) - or that all are within it."""
    out = []
    rows = []
    for label, target in (targets or {}).items():
        delta = (actual.get(label) or 0.0) - float(target)
        if abs(delta) > band:
            rows.append((abs(delta), label, delta))
    for _, label, delta in sorted(rows, key=lambda r: (-r[0], r[1])):
        out.append((MIX_OVER if delta > 0 else MIX_UNDER).format(
            label=label, points=MASK if masked else f"{abs(delta):.0f}"))
    if targets and not out:
        out.append(MIX_WITHIN)
    return out


def mix_summary(rows: list, masked: bool = False) -> str:
    """'About 85% stocks, 12% bonds, 3% cash' from allocate()'s by_asset_class
    (the percentages as MASK while amounts are hidden)."""
    parts = [f"{MASK if masked else format(r['pct'], '.0f') + '%'} {r['label'].lower()}"
             for r in sorted(rows, key=lambda r: -(r.get("pct") or 0.0))
             if r.get("pct") is not None and round(r["pct"]) > 0]
    return ("About " + ", ".join(parts)) if parts else ""


def templates() -> list[str]:
    """Every fixed line, for the wording tests."""
    return [TITLE, DONE_LABEL, AWAY_LABEL, DONE_HELP, AWAY_HELP,
            PUT_AWAY_LINE.format(names=", ".join(NAMES.values())), BRING_BACK,
            MIX_TITLE, MIX_OVER.format(label="Stocks", points="15"),
            MIX_UNDER.format(label="Bonds", points="9"), MIX_WITHIN, MIX_NO_TARGET, MIX_LINK,
            MIX_NOTE, HOLDINGS_TITLE, HOLDINGS_MORE.format(n=4), FULL_TABLE]
