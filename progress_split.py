"""What you did vs what the market did (flag progress_split): for this year,
or since the first value the app has, how much of the change in the
portfolio's value was money the person added and how much the market did.
Pure logic plus one read; the card is views/progress_split.py (on Home,
under the performance chart).

Where the figures come from - all already in the app, nothing fetched:
- money added: the same source as Plan's Contributions and Year in review
  (plans.money_moves) - amounts logged by hand on Plan, and the deposits and
  withdrawals in an imported activity export (txn_import.py, origin
  'imported'). A hand entry dated inside the imported history isn't counted
  (the history has the real figure); money-market sweeps and moves between
  your own accounts were never deposits. Buys and sells worked out from
  holdings updates (changes.py) are not money added - a buy can be paid
  for with cash already in the account - so they're never used here.
- values: what recap.value_points reads - each visit's logged value
  (value_log) and each holdings update whose every holding has a value, plus
  cash. Never the example portfolio or a percentages portfolio (their
  dollars are pretend).
- dividends and interest: the imported activity history's DIV / INTEREST
  rows, only said when that history covers the time. They're already inside
  the market part (they're in the account's value), never added twice.

What the market did is the change in value less the money added: price
changes and dividends. When the app doesn't know what was added (nothing
logged, no activity export), it says so and shows only the change in value
- it never guesses. With only an activity export, the split covers just the
days that history covers, and says so.

One query (read) gathers everything Home needs for this card and for Your
wins (wins.py): a UNION ALL of small per-account reads, each filtered by
user_id.
"""

from __future__ import annotations

from datetime import date, timedelta

SAMPLE_SOURCE = "sample portfolio"    # portfolio.SAMPLE_SOURCE
PCT_SOURCE = "percentages"            # manual_entry.PCT_SOURCE
PRETEND_SOURCES = (SAMPLE_SOURCE, PCT_SOURCE)

YEAR, ALL = "year", "all"
PERIODS = {YEAR: "This year", ALL: "Since you started"}
BEFORE_DAYS = 31     # a value this close before January 1 starts "this year"
EDGE_DAYS = 7        # an activity history this close to a day covers it

# states of a split
SPLIT, UNKNOWN, NOT_ENOUGH, PRETEND, PERCENTAGES = (
    "split", "unknown", "not_enough", "pretend", "percentages")

# ---- the words (fixed; every one goes through the wording tests) ----------- #
TITLE = "What you did vs what the market did"
YOU_LABEL = "What you did"
YOU_SUB = "Money you added"
YOU_SUB_NET = "Money you added, less what you took out"
YOU_SUB_COUNT = "Money you added, {n} deposits"
MARKET_LABEL = "What the market did"
MARKET_SUB = "Price changes and dividends"
MARKET_SUB_DIVS = "With {amount} dividends & interest"
SHARE_LABEL = "From your own deposits"
SHARE_SUB = "of the growth was money added"
CHANGE_LABEL = "Change in value"
CHART_ADDED = "Money you added"
CHART_MARKET = "What the market did"

LINE_BOTH = ("Of the {change} your portfolio grew, {added} was money you added and {market} "
             "came from the market.")
LINE_MARKET_DOWN = ("The market part was down {market}, and the {added} you added still "
                    "raised the total.")
LINE_MARKET_DOWN_MORE = "The market part was down {market}, more than the {added} you added."
LINE_NONE_ADDED = ("No money was added in this time, so the change of {change} is all the "
                   "market's.")
LINE_TOOK_OUT = ("More money came out than went in, so the market part is the change in value "
                 "plus what you took out.")
STEADY = ("The money you add is the part you control. The market part goes up and down on its "
          "own, month to month.")
SOURCE_NOTE = ("Money added is what you logged on Plan, under Contributions, and the deposits "
               "and withdrawals in an activity export you brought in. Moves between your own "
               "accounts don't count. What the market did is the change in value less that.")
SINCE = "From {day}, the first value Northwend has for this time."
UNTIL = "To {day}, where your activity history ends - deposits after it aren't known."
LATE = ("Money added after your last holdings update shows in the value once you update them - "
        "until then the market part looks smaller than it is.")
UNKNOWN_LINE = ("Northwend doesn't know how much money you added in this time, so it can't "
                "split the change into yours and the market's.")
UNKNOWN_HOW = ("To split it, log money you add on Plan, under Contributions, or bring in an "
               "activity export from your brokerage.")
UNKNOWN_CHANGE = "Your portfolio's value changed by {change} over this time."
NOT_ENOUGH_LINE = ("This fills in once there are two values to compare. It grows as you visit "
                   "and update your holdings.")
SAMPLE_LINE = ("This works on your own holdings. The example portfolio's dollar figures are "
               "made up, so there's nothing to split yet.")
PCT_LINE = ("Your portfolio is in percentages, so there are no dollar amounts to split. Here "
            "is what's known in percentages and counts.")
PCT_MARKET = "The market moved your mix {pct} over this time."
PCT_MARKET_NONE = "The market's move on your mix fills in once price history has loaded."
PCT_ADDED = "You logged money added in {n} of these months."
PCT_ADDED_NONE = "No money added is logged for this time."

# the automatic deposit explainer (education only - nothing is set up here)
AUTO_BUTTON = "Set up an automatic deposit"
AUTO_TITLE = "How automatic deposits work"
AUTO_LINES = (
    "An automatic deposit moves the same amount from your bank to your investment account on a "
    "schedule - every payday or once a month, for example. It's set up at your brokerage, not "
    "in Northwend: Northwend can't move money.",
    "Brokerages call it different things: a recurring transfer, an automatic investment or an "
    "automatic deposit. You usually pick the amount, how often, and the bank account it comes "
    "from. Some can also put it into funds you choose.",
    "For a 401(k) it comes out of your pay instead, through your employer's plan website or HR.",
    "Most let you change the amount or stop it whenever you like.",
)
AUTO_NOTE = "For learning: how much to add, and where, is your choice."
AUTO_LOOK = "Look for it in your brokerage's website or app, under transfers or deposits."


# --------------------------------------------------------------------------- #
# the one read
# --------------------------------------------------------------------------- #
_T = "CAST(NULL AS TEXT)"
_N = "CAST(NULL AS DOUBLE PRECISION)"

# (kind, SELECT ... - eight columns: k, d, t1, t2, t3, x, y, z). Each part
# filters by user_id; every one is a small read the app already makes.
_PARTS = (
    # money logged by hand on Plan
    f"SELECT 'h' AS k, date AS d, {_T} AS t1, {_T} AS t2, {_T} AS t3, amount AS x, "
    f"{_N} AS y, {_N} AS z FROM contributions WHERE user_id = ?",
    # deposits and withdrawals in an imported activity export
    f"SELECT 'b', trade_date, action, {_T}, {_T}, amount, {_N}, {_N} FROM transactions "
    "WHERE user_id = ? AND origin = 'imported' AND action IN ('DEPOSIT', 'WITHDRAWAL') "
    "AND amount IS NOT NULL",
    # dividends and interest in it
    f"SELECT 'i', trade_date, action, {_T}, {_T}, amount, {_N}, {_N} FROM transactions "
    "WHERE user_id = ? AND origin = 'imported' AND action IN ('DIV', 'INTEREST') AND amount > 0",
    # the days the imported history covers
    f"SELECT 'w', MIN(trade_date), MAX(trade_date), {_T}, {_T}, {_N}, {_N}, {_N} "
    "FROM transactions WHERE user_id = ? AND origin = 'imported'",
    # each holdings update and where it came from
    f"SELECT 's', snapshot_date, source_file, {_T}, {_T}, {_N}, {_N}, {_N} FROM snapshots "
    "WHERE user_id = ?",
    # each update's holdings: how many, how many with a value, their total
    f"SELECT 'p', snapshot_date, {_T}, {_T}, {_T}, CAST(COUNT(*) AS DOUBLE PRECISION), "
    "CAST(COUNT(market_value) AS DOUBLE PRECISION), SUM(market_value) FROM positions "
    "WHERE user_id = ? GROUP BY snapshot_date",
    # each update's cash
    f"SELECT 'a', snapshot_date, {_T}, {_T}, {_T}, SUM(cash_value), {_N}, {_N} "
    "FROM account_totals WHERE user_id = ? GROUP BY snapshot_date",
    # each visit's logged value
    f"SELECT 'v', logged_at, snapshot_date, {_T}, {_T}, portfolio_value, {_N}, {_N} "
    "FROM value_log WHERE user_id = ? AND portfolio_value IS NOT NULL",
    # the first update's funds and their yearly fees (wins.py: lower fees)
    "SELECT 'f', p.snapshot_date, p.symbol, p.asset_type, si.quote_type, p.market_value, "
    f"si.expense_ratio, {_N} FROM positions p LEFT JOIN security_info si ON si.ticker = p.symbol "
    "WHERE p.user_id = ? AND p.snapshot_date = (SELECT MIN(s.snapshot_date) FROM snapshots s "
    "WHERE s.user_id = ? AND s.source_file <> ?)",
)
SQL = " UNION ALL ".join(_PARTS)


def read(conn, user_id: int) -> dict:
    """Everything the card and Your wins need, in one query:
    {"hand": [(date, amount)], "brokerage": [(date, amount)], "income":
    [(date, amount)], "window": (first, last) of the imported history or
    None, "sources": {snapshot day: source}, "positions": {day: (n, n with a
    value, total)}, "cash": {day: total}, "visits": [(logged_at, snapshot
    day, value)], "first_funds": [{symbol, asset_type, quote_type, value,
    expense_ratio}], "first_day": that update's day or None}."""
    params = (user_id,) * 10 + (SAMPLE_SOURCE,)
    out = {"hand": [], "brokerage": [], "income": [], "window": None, "sources": {},
           "positions": {}, "cash": {}, "visits": [], "first_funds": [], "first_day": None}
    for r in conn.execute(SQL, params):
        k, d = r["k"], (str(r["d"]) if r["d"] is not None else None)
        if k == "h" and d and r["x"] is not None:
            out["hand"].append((d[:10], float(r["x"])))
        elif k == "b" and d:
            out["brokerage"].append((d[:10], float(r["x"])))
        elif k == "i" and d:
            out["income"].append((d[:10], float(r["x"])))
        elif k == "w" and d and r["t1"]:
            out["window"] = (d[:10], str(r["t1"])[:10])
        elif k == "s" and d:
            out["sources"].setdefault(d[:10], []).append(r["t1"])
        elif k == "p" and d:
            out["positions"][d[:10]] = (int(r["x"] or 0), int(r["y"] or 0), float(r["z"] or 0.0))
        elif k == "a" and d:
            out["cash"][d[:10]] = float(r["x"] or 0.0)
        elif k == "v" and d:
            out["visits"].append((d, str(r["t1"] or "")[:10], float(r["x"])))
        elif k == "f" and d:
            out["first_day"] = d[:10]
            out["first_funds"].append({"symbol": r["t1"], "asset_type": r["t2"],
                                       "quote_type": r["t3"], "value": r["x"],
                                       "expense_ratio": r["y"]})
    out["visits"].sort()
    out["hand"].sort()
    out["brokerage"].sort()
    out["income"].sort()
    return out


# --------------------------------------------------------------------------- #
# the pieces
# --------------------------------------------------------------------------- #
def _pretend_day(facts: dict, day: str) -> bool:
    return any(s in PRETEND_SOURCES for s in facts["sources"].get(day, ()))


def value_points(facts: dict) -> list[tuple[str, float]]:
    """(day, value) in real dollars, oldest first - recap.value_points from
    the one read: each holdings update whose every holding has a value
    (plus its cash), and each day's last visit. Pretend portfolios left out."""
    pts: dict[str, float] = {}
    for d, (n, nv, mv) in facts["positions"].items():
        if _pretend_day(facts, d) or not n or nv != n:
            continue
        pts[d] = mv + facts["cash"].get(d, 0.0)
    for logged, snap, value in facts["visits"]:   # oldest first: the day's last wins
        if _pretend_day(facts, snap):
            continue
        pts[logged[:10]] = value
    return sorted(pts.items())


def moves(facts: dict) -> list[tuple[str, float]]:
    """Money added (+) or taken out (-), oldest first - plans.money_moves'
    rule: a hand entry inside the imported history isn't counted."""
    w = facts["window"]
    out = [(d, a) for d, a in facts["hand"] if not (w and w[0] <= d <= w[1])]
    out += list(facts["brokerage"])
    return sorted(out)


def known_range(facts: dict) -> tuple[str, str] | None:
    """The days for which money added is known: all of them once anything is
    logged by hand (the person keeps that record), else the imported
    history's days, else None (not known at all)."""
    if facts["hand"]:
        return ("0000-01-01", "9999-12-31")
    return facts["window"]


def _day(s: str) -> date:
    return date.fromisoformat(s[:10])


def _shift(s: str, days: int) -> str:
    return (_day(s) + timedelta(days=days)).isoformat()


def period_start(period: str, today: date, points) -> str | None:
    """January 1 for this year; the first value's day for since you started."""
    if period == YEAR:
        return f"{today.year:04d}-01-01"
    return points[0][0] if points else None


def _base(points, start: str, floor: str, until: str):
    """The value the split starts from: the last on or before `start` and
    no earlier than `floor`, else the first after `start` (up to `until`)."""
    before = [p for p in points if floor <= p[0] <= start]
    if before:
        return before[-1]
    after = [p for p in points if start < p[0] <= until]
    return after[0] if after else None


def share_pct(added: float, market: float) -> float | None:
    """The share of the growth that was money added, in percent: only when
    both parts grew it (a share of a fall, or of more than all, means
    nothing)."""
    if added > 0 and market >= 0 and added + market > 0:
        return added / (added + market) * 100
    return None


def split(facts: dict, period: str, today: date, *, current: float | None = None,
          pretend: str | None = None) -> dict:
    """The card's figures for `period` (YEAR / ALL). `current`: today's live
    value; `pretend`: the holdings' source when it's the example or a
    percentages portfolio. Returns {"state", and for SPLIT: "start", "end",
    "v0", "v1", "added", "market", "change", "share", "deposits" (how many),
    "withdrawals", "income" (dividends and interest known, or None),
    "since" (the first value's day when after the period's start), "until"
    (the history's end when before today), "late" (money added after the
    last holdings update), "series" [{"date", "added", "market"}]; for
    UNKNOWN "change" (or None); for PERCENTAGES "months_added", "start"}."""
    today_s = today.isoformat()
    if pretend == SAMPLE_SOURCE:
        return {"state": PRETEND}
    counted = moves(facts)
    if pretend == PCT_SOURCE:
        own = sorted(d for d, srcs in facts["sources"].items() if SAMPLE_SOURCE not in srcs)
        start = f"{today.year:04d}-01-01" if period == YEAR else (own[0] if own else today_s)
        months = {d[:7] for d, a in counted if start <= d <= today_s and a > 0}
        return {"state": PERCENTAGES, "start": start, "months_added": len(months),
                "known": known_range(facts) is not None}
    points = value_points(facts)
    start = period_start(period, today, points)
    if start is None or not points:
        return {"state": NOT_ENOUGH}
    rng = known_range(facts)
    lo = start if rng is None else max(start, rng[0])
    hi = today_s if rng is None or rng[1] >= _shift(today_s, -EDGE_DAYS) else min(today_s, rng[1])
    floor = _shift(lo, -(BEFORE_DAYS if period == YEAR else 0))
    if rng is not None and rng[0] > "0000-01-01":
        floor = max(floor, _shift(rng[0], -EDGE_DAYS))
    base = _base(points, lo, floor, hi)
    end_pt = None
    if base is not None:
        if hi == today_s and current is not None and today_s > base[0]:
            end_pt = (today_s, float(current))
        else:
            later = [p for p in points if base[0] < p[0] <= hi]
            end_pt = later[-1] if later else None
    if base is None or end_pt is None:
        return {"state": NOT_ENOUGH}
    change = end_pt[1] - base[1]
    if rng is None:
        return {"state": UNKNOWN, "change": round(change, 2), "start": base[0], "end": end_pt[0]}
    inside = [(d, a) for d, a in counted if base[0] < d <= end_pt[0]]
    added = round(sum(a for _, a in inside), 2)
    market = round(change - added, 2)
    w = facts["window"]
    income = None
    if w and w[0] <= _shift(base[0], EDGE_DAYS) and w[1] >= _shift(end_pt[0], -EDGE_DAYS):
        income = round(sum(a for d, a in facts["income"] if base[0] < d <= end_pt[0]), 2)
    real_updates = sorted(d for d, srcs in facts["sources"].items()
                          if not any(s in PRETEND_SOURCES for s in srcs))
    added_days = [d for d, a in inside if a > 0]
    late = bool(added_days and real_updates and end_pt[0] == today_s
                and added_days[-1] > real_updates[-1])
    return {"state": SPLIT, "start": base[0], "end": end_pt[0], "v0": base[1], "v1": end_pt[1],
            "added": added, "market": market, "change": round(change, 2),
            "share": share_pct(added, market),
            "deposits": sum(1 for _, a in inside if a > 0),
            "withdrawals": sum(1 for _, a in inside if a < 0),
            "income": income or None,
            "since": base[0] if base[0] > start else None,
            "until": end_pt[0] if end_pt[0] < _shift(today_s, -EDGE_DAYS) else None,
            "late": late, "series": series(points, inside, base, end_pt)}


def series(points, inside, base, end_pt) -> list[dict]:
    """The chart: at the base (both 0), each month's last value after it,
    and the end - cumulative money added, and the market part (the value's
    change less that)."""
    by_month: dict[str, tuple[str, float]] = {}
    for d, v in points:
        if base[0] < d < end_pt[0]:
            by_month[d[:7]] = (d, v)
    stops = [base] + [by_month[m] for m in sorted(by_month) if m != end_pt[0][:7]] + [end_pt]
    out = []
    for d, v in stops:
        added = round(sum(a for day, a in inside if day <= d), 2)
        out.append({"date": d, "added": added, "market": round(v - base[1] - added, 2)})
    return out


def market_pct(rows, since: str) -> float | None:
    """The holdings now, priced at each day's close (perf's reconstructed
    rows), from `since` (the last close on or before it, else the first
    after) to the latest: percent, one decimal. Only the days every covered
    holding had a price, as recap.market_series."""
    most = max((r["n_priced"] for r in rows or ()), default=0)
    pts = sorted((str(r["t"])[:10], r["portfolio_value"]) for r in rows or ()
                 if r["n_priced"] == most and r.get("portfolio_value"))
    if len(pts) < 2:
        return None
    before = [p for p in pts if p[0] <= since]
    first = before[-1] if before else pts[0]
    if first == pts[-1]:
        return None
    return round((pts[-1][1] / first[1] - 1) * 100, 1)


def lines(r: dict, money) -> list[str]:
    """The plain-words lines under the figures. `money`: a whole-dollar
    formatter (it masks while amounts are hidden)."""
    if r["state"] != SPLIT:
        return []
    added, market, change = r["added"], r["market"], r["change"]
    if added > 0 and market >= 0:
        out = [LINE_BOTH.format(change=money(change), added=money(added), market=money(market))]
    elif added > 0 and change > 0:
        out = [LINE_MARKET_DOWN.format(market=money(abs(market)), added=money(added))]
    elif added > 0:
        out = [LINE_MARKET_DOWN_MORE.format(market=money(abs(market)), added=money(added))]
    elif added == 0:
        out = [LINE_NONE_ADDED.format(change=money(change))]
    else:
        out = [LINE_TOOK_OUT]
    out.append(STEADY)
    return out


def you_sub(r: dict) -> str:
    if r.get("withdrawals"):
        return YOU_SUB_NET
    if r.get("deposits"):
        return YOU_SUB_COUNT.format(n=r["deposits"]) if r["deposits"] > 1 else YOU_SUB
    return YOU_SUB


def templates() -> list[str]:
    """Every fixed line, filled with example figures, for the wording tests."""
    ex = "$1,800"
    return [TITLE, YOU_LABEL, YOU_SUB, YOU_SUB_NET, YOU_SUB_COUNT.format(n=10), MARKET_LABEL,
            MARKET_SUB, MARKET_SUB_DIVS.format(amount="$120"), SHARE_LABEL, SHARE_SUB,
            CHANGE_LABEL, CHART_ADDED, CHART_MARKET, *PERIODS.values(),
            LINE_BOTH.format(change="$6,000", added="$4,200", market=ex),
            LINE_MARKET_DOWN.format(market=ex, added="$4,200"),
            LINE_MARKET_DOWN_MORE.format(market=ex, added="$1,200"),
            LINE_NONE_ADDED.format(change=ex), LINE_TOOK_OUT, STEADY, SOURCE_NOTE,
            SINCE.format(day="March 3"), UNTIL.format(day="June 30"), LATE, UNKNOWN_LINE,
            UNKNOWN_HOW, UNKNOWN_CHANGE.format(change=ex), NOT_ENOUGH_LINE, SAMPLE_LINE,
            PCT_LINE, PCT_MARKET.format(pct="+4.2%"), PCT_MARKET_NONE, PCT_ADDED.format(n=3),
            PCT_ADDED_NONE, AUTO_BUTTON, AUTO_TITLE, *AUTO_LINES, AUTO_NOTE, AUTO_LOOK]
