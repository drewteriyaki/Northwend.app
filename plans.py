"""Plans: one goal per account, progress toward it, and money in vs growth.

A plan is a goal (a target amount by a target date), how much is added each
month, and a target mix by asset type. It is written by the account owner or
their advisor (`set_by`). Everything else here is arithmetic on that plus
the account's imported snapshots and logged contributions - no network, no
Streamlit.

Projections are compound growth at an assumed yearly return, shown as a
range (the assumption plus and minus `SPREAD_PCT`), in today's dollars
without inflation. They illustrate what a plan implies; they don't predict.

Money going out (planned expenses and a regular withdrawal, the `money_out`
table) is taken out month by month on its dates (simulate); with none, the
closed-form results are used unchanged.
"""

from __future__ import annotations

import json
from datetime import date

GOAL_TYPES = ("Retirement", "Buy a home", "Pay for education", "Build long-term wealth",
              "Big purchase", "Other")
DEFAULT_RETURN_PCT = 6.0
SPREAD_PCT = 2.0

# A goal's first suggested date, by what it's for (goal_years_default): a
# retirement from the person's age (about 65), else RETIRE_DEFAULT_YEARS;
# the others from their own timeline answer, else a typical one.
RETIRE_AGE = 65
RETIRE_DEFAULT_YEARS = 25
_AGE_MIDDLE = {"Under 25": 22, "25-34": 30, "35-44": 40, "45-54": 50, "55-64": 60,
               "65 or older": 66}
GOAL_TYPICAL_YEARS = {"Buy a home": 5, "Pay for education": 10, "Build long-term wealth": 20,
                      "Big purchase": 3, "Other": 10}


def goal_years_default(goal_type: str | None, profile: dict | None) -> tuple[int, str]:
    """(years from now, why) for a new goal's date: why is "age" (a
    retirement, from the age answer), "timeline" (their time-horizon answer)
    or "typical" (nothing to go on: a usual timeline for that kind of goal).
    A retirement never takes the time-horizon answer - "3 years" there is
    when they need some money, not when they stop working."""
    p = profile or {}
    if goal_type == "Retirement":
        age = _AGE_MIDDLE.get(p.get("age_range"))
        if age is not None:
            return max(2, min(45, RETIRE_AGE - age)), "age"
        return RETIRE_DEFAULT_YEARS, "typical"
    try:
        answered = int(float(p.get("time_horizon_years") or 0))
    except (TypeError, ValueError):
        answered = 0
    if answered > 0:
        return max(1, min(40, answered)), "timeline"
    return GOAL_TYPICAL_YEARS.get(goal_type, 10), "typical"

_FIELDS = ("goal_type", "goal_name", "target_amount", "target_date", "monthly_contribution",
           "target_alloc", "notes")


# --------------------------------------------------------------------------- #
# storage
# --------------------------------------------------------------------------- #
def get_plan(conn, user_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM plans WHERE user_id = ?", (user_id,)).fetchone()
    return _plan_from(row)


def get_plans(conn, user_ids) -> dict:
    """get_plan() for several accounts in one query: {user_id: plan or None}."""
    ids = tuple(dict.fromkeys(user_ids))
    if not ids:
        return {}
    rows = {r["user_id"]: r for r in conn.execute(
        f"SELECT * FROM plans WHERE user_id IN ({', '.join('?' for _ in ids)})", ids)}
    return {i: _plan_from(rows.get(i)) for i in ids}


def _plan_from(row) -> dict | None:
    if row is None:
        return None
    plan = dict(row)
    try:
        alloc = json.loads(plan.get("target_alloc") or "{}")
    except ValueError:
        alloc = {}
    plan["target_alloc"] = {k: float(v) for k, v in alloc.items() if v} if isinstance(alloc, dict) else {}
    return plan


def save_plan(conn, user_id: int, fields: dict, set_by: int) -> dict:
    """Merge `fields` into the account's plan (creating it) and return it.
    A key that's present with None clears that field."""
    plan = get_plan(conn, user_id) or {f: None for f in _FIELDS}
    plan.update({k: v for k, v in fields.items() if k in _FIELDS})
    alloc = {k: float(v) for k, v in (plan.get("target_alloc") or {}).items() if v}
    conn.execute(
        "INSERT INTO plans (user_id, goal_type, goal_name, target_amount, target_date, "
        "monthly_contribution, target_alloc, notes, set_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (user_id) DO UPDATE SET goal_type = excluded.goal_type, "
        "goal_name = excluded.goal_name, target_amount = excluded.target_amount, "
        "target_date = excluded.target_date, monthly_contribution = excluded.monthly_contribution, "
        "target_alloc = excluded.target_alloc, notes = excluded.notes, set_by = excluded.set_by, "
        "updated_at = datetime('now')",
        (user_id, plan.get("goal_type"), plan.get("goal_name"), plan.get("target_amount"),
         plan.get("target_date"), plan.get("monthly_contribution"), json.dumps(alloc),
         plan.get("notes"), set_by))
    if "target_alloc" in fields:  # new targets replace any cleared by the class change
        conn.execute("UPDATE plans SET targets_cleared = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    return get_plan(conn, user_id)


def has_goal(plan: dict | None) -> bool:
    return bool(plan and plan.get("target_amount") and plan.get("target_date"))


def add_contribution(conn, user_id: int, on: str, amount: float, note: str | None = None) -> None:
    """Log money added (positive) or taken out (negative) on date `on`."""
    conn.execute("INSERT INTO contributions (user_id, date, amount, note) VALUES (?, ?, ?, ?)",
                 (user_id, on, float(amount), (note or "").strip() or None))
    conn.commit()


def delete_contribution(conn, user_id: int, contribution_id: int) -> None:
    conn.execute("DELETE FROM contributions WHERE id = ? AND user_id = ?", (contribution_id, user_id))
    conn.commit()


def list_contributions(conn, user_id: int, limit: int = 50) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT id, date, amount, note FROM contributions WHERE user_id = ? "
        "ORDER BY date DESC, id DESC LIMIT ?", (user_id, limit))]


# ---- money added: logged by hand, or from an imported activity export ------ #
def imported_window(conn, user_id: int) -> tuple[str, str] | None:
    """(first, last) date of the imported activity history (txn_import.py)."""
    row = conn.execute("SELECT MIN(trade_date) AS a, MAX(trade_date) AS b FROM transactions "
                       "WHERE user_id = ? AND origin = 'imported'", (user_id,)).fetchone()
    return (row["a"], row["b"]) if row and row["a"] else None


def money_moves(conn, user_id: int, start: str | None = None, end: str | None = None,
                *, window=False) -> list[dict]:
    """Money added (+) or taken out (-), newest first: hand-logged entries
    and the deposits and withdrawals in imported activity history.
    [{"id", "date", "amount", "note", "source": "hand" | "brokerage",
    "counted"}]. A hand entry dated inside the imported history isn't
    counted - the history already has the real figure (moves between your
    own accounts and money-market sweeps are never money added).
    `window`: imported_window() if the caller already read it."""
    start, end = start or "0000-00-00", end or "9999-99-99"
    if window is False:
        window = imported_window(conn, user_id)
    out = [{"id": r["id"], "date": r["date"], "amount": float(r["amount"]), "note": r["note"],
            "source": "hand",
            "counted": not (window and window[0] <= r["date"] <= window[1])}
           for r in conn.execute("SELECT id, date, amount, note FROM contributions WHERE "
                                 "user_id = ? AND date >= ? AND date <= ?", (user_id, start, end))]
    out += [{"id": r["id"], "date": r["trade_date"], "amount": float(r["amount"]),
             "note": r["description"], "source": "brokerage", "counted": True}
            for r in conn.execute(
                "SELECT id, trade_date, amount, description FROM transactions WHERE user_id = ? "
                "AND origin = 'imported' AND action IN ('DEPOSIT', 'WITHDRAWAL') AND amount IS "
                "NOT NULL AND trade_date >= ? AND trade_date <= ?", (user_id, start, end))]
    out.sort(key=lambda m: (m["date"], m["source"] == "brokerage", m["id"]), reverse=True)
    return out


def money_added(conn, user_id: int, start: str, end: str) -> float:
    """Net money added between two dates (YYYY-MM-DD, inclusive)."""
    return round(sum(m["amount"] for m in money_moves(conn, user_id, start, end)
                     if m["counted"]), 2)


def month_total(conn, user_id: int, year: int, month: int, moves=None) -> float:
    """Net money added in that month. `moves`: every money_moves() already
    read - that month's are picked from them, nothing is read again."""
    start, end = f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-31"
    if moves is not None:
        return round(sum(m["amount"] for m in moves
                         if m["counted"] and start <= m["date"] <= end), 2)
    return money_added(conn, user_id, start, end)


def money_in_history(conn, user_id: int) -> list[dict]:
    """Per imported snapshot, from the statement's own figures: total value,
    growth (market value minus cost, over positions with a known cost), and
    money in (the rest: cost basis plus cash). Oldest first."""
    rows = {r["snapshot_date"]: {"date": r["snapshot_date"], "holdings": float(r["mv"] or 0.0),
                                 "growth": float(r["gl"] or 0.0)}
            for r in conn.execute(
                "SELECT snapshot_date, SUM(market_value) AS mv, "
                "SUM(CASE WHEN cost_basis IS NOT NULL AND market_value IS NOT NULL "
                "THEN market_value - cost_basis ELSE 0 END) AS gl "
                "FROM positions WHERE user_id = ? GROUP BY snapshot_date", (user_id,))}
    for r in conn.execute("SELECT snapshot_date, SUM(cash_value) AS cash FROM account_totals "
                          "WHERE user_id = ? GROUP BY snapshot_date", (user_id,)):
        rows.setdefault(r["snapshot_date"], {"date": r["snapshot_date"], "holdings": 0.0,
                                             "growth": 0.0})["cash"] = float(r["cash"] or 0.0)
    out = []
    for d in sorted(rows):
        r = rows[d]
        value = r["holdings"] + r.get("cash", 0.0)
        out.append({"date": d, "value": value, "growth": r["growth"], "money_in": value - r["growth"]})
    return out


# --------------------------------------------------------------------------- #
# arithmetic
# --------------------------------------------------------------------------- #
def months_until(target_date: str, today: date) -> int:
    """Whole months from `today` to `target_date` (YYYY-MM-DD); negative if past."""
    t = date.fromisoformat(str(target_date)[:10])
    return (t.year - today.year) * 12 + (t.month - today.month) - (1 if t.day < today.day else 0)


def _monthly_rate(annual_pct: float) -> float:
    return (1 + annual_pct / 100) ** (1 / 12) - 1


def future_value(present: float, monthly: float, annual_pct: float, months: int) -> float:
    """`present` grown for `months` at `annual_pct` a year, plus `monthly`
    added at the end of each month."""
    months = max(0, months)
    r = _monthly_rate(annual_pct)
    if r == 0:
        return present + monthly * months
    g = (1 + r) ** months
    return present * g + monthly * (g - 1) / r


def required_monthly(present: float, target: float, annual_pct: float, months: int,
                     items=None, *, today: date | None = None) -> float | None:
    """Monthly amount that reaches `target` in `months` at `annual_pct`;
    0 if growth alone gets there, None when there's no time left. With
    money going out (`items`, from list_money_out, and `today`): what still
    gets there after it, worked out month by month (None if no monthly
    amount can - additions stop when regular withdrawals start)."""
    if months <= 0:
        return None
    if items and today is not None:
        return _required_with_out(present, target, annual_pct, months, items, today)
    r = _monthly_rate(annual_pct)
    g = (1 + r) ** months
    gap = target - present * g
    if gap <= 0:
        return 0.0
    return gap / months if r == 0 else gap * r / (g - 1)


def months_to_reach(present: float, monthly: float, annual_pct: float, target: float, *,
                    cap: int = 600) -> int | None:
    """Whole months until `present` plus `monthly` reaches `target` at
    `annual_pct`; 0 if already there, None if not within `cap` months."""
    if present >= target:
        return 0
    r = _monthly_rate(annual_pct)
    value = present
    for n in range(1, cap + 1):
        value = value * (1 + r) + monthly
        if value >= target:
            return n
    return None


# The "what if" playground's return for a mix (ROADMAP G5): the same rounded
# long-run assumptions as advisor proposals (proposals.ASSUMED_RETURN).
STOCK_RETURN_PCT, BOND_RETURN_PCT = 7.0, 4.0


def mix_return(stocks_pct: float) -> float:
    """Assumed yearly return for a mix of `stocks_pct` stocks, the rest bonds."""
    s = max(0.0, min(100.0, stocks_pct)) / 100
    return STOCK_RETURN_PCT * s + BOND_RETURN_PCT * (1 - s)


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    for day in (d.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    raise ValueError(d)


def progress(plan: dict, current_value: float, *, today: date,
             return_pct: float = DEFAULT_RETURN_PCT, spread: float = SPREAD_PCT,
             items=None) -> dict:
    """Where the account stands against its goal.

    status: 'reached' (already at or past the target), 'starting' (nothing
    invested yet - day one isn't "behind"; needed_monthly is what gets
    there), 'on_track' (the assumed return gets there), 'within_reach' (only
    the optimistic end does), 'behind', or 'past_date' (the date has passed
    short of it).

    `items`: the plan's money going out (list_money_out). Whatever comes out
    by the goal date is taken out month by month; "projected_without" is
    then where the plan would be without it, and "out_by_goal" how much
    comes out before the goal date. Without any, the closed-form results."""
    target = float(plan["target_amount"])
    monthly = float(plan.get("monthly_contribution") or 0.0)
    months = months_until(plan["target_date"], today)
    lo, mid, hi = (value_at(current_value, monthly, p, months, items, today=today)
                   for p in (return_pct - spread, return_pct, return_pct + spread))
    if current_value >= target:
        status = "reached"
    elif months <= 0:
        status = "past_date"
    elif current_value <= 0:
        status = "starting"
    elif mid >= target:
        status = "on_track"
    elif hi >= target:
        status = "within_reach"
    else:
        status = "behind"
    out = {
        "target": target, "current": current_value, "monthly": monthly, "months": months,
        "pct_of_target": (current_value / target * 100) if target else None,
        "projected_low": lo, "projected": mid, "projected_high": hi,
        "needed_monthly": required_monthly(current_value, target, return_pct, months,
                                           items, today=today),
        "status": status,
    }
    if items:
        sched = out_schedule(items, today, max(0, months))
        out["out_by_goal"] = round(sum(sched.values()), 2)
        out["projected_without"] = future_value(current_value, monthly, return_pct, months)
    return out


def projection_series(current_value: float, monthly: float, months: int, *, today: date,
                      return_pct: float = DEFAULT_RETURN_PCT, spread: float = SPREAD_PCT,
                      items=None) -> list[dict]:
    """One row per month from today to `months` on: the low / assumed / high
    projected value. At most ~240 rows (long horizons are sampled). With
    money going out (`items`), worked out month by month, and the months it
    comes out in (and the one before) are always kept so the dips show."""
    months = max(0, months)
    step = max(1, -(-months // 240))  # ceiling, so at most ~240 points
    points = list(range(0, months + 1, step))
    if points[-1] != months:
        points.append(months)
    if not items:
        return [{"date": add_months(today, n).isoformat(),
                 "low": future_value(current_value, monthly, return_pct - spread, n),
                 "mid": future_value(current_value, monthly, return_pct, n),
                 "high": future_value(current_value, monthly, return_pct + spread, n)}
                for n in points]
    sched = out_schedule(items, today, months)
    stop = adding_stops(items, today)
    lo, mid, hi = (simulate(current_value, monthly, p, months, sched, add_until=stop)["values"]
                   for p in (return_pct - spread, return_pct, return_pct + spread))
    # one-off dips: the month before and the month itself (regular
    # withdrawals come out every month - only where they start)
    keep = {n for n in _expense_steps(items, today, months) for n in (n - 1, n)}
    if stop is not None and 1 <= stop <= months:
        keep |= {stop - 1, stop}
    points = sorted(set(points) | {n for n in keep if 0 <= n <= months})
    return [{"date": add_months(today, n).isoformat(), "low": lo[n], "mid": mid[n],
             "high": hi[n]} for n in points]


# --------------------------------------------------------------------------- #
# money going out (ROADMAP 12): planned expenses and regular withdrawals
# --------------------------------------------------------------------------- #
# An "expense" is an amount on a date, repeated `times` times every
# `every_months` (1 time: a one-off; tuition each fall for 4 years: 4 times
# every 12 months). A "withdrawal" is a monthly amount from `start_date`
# (to `end_date`, if set), rising `inflation_pct` a year from when it starts
# if that's set. An account has at most one regular withdrawal. Saved by
# the owner or their advisor (`set_by`), like the plan.
OUT_KINDS = ("expense", "withdrawal")
DEFAULT_INFLATION_PCT = 2.5      # a stated, hypothetical rate
LAST_AGE = 95                    # "does it last" checks to about this age...
LAST_YEARS = 30                  # ...or this many years of withdrawals, without an age
OUT_CAP_YEARS = 80
MAX_TIMES = 40
_OUT_FIELDS = ("label", "amount", "start_date", "end_date", "times", "every_months",
               "inflation_pct")


def may_change(conn, by: int, user_id: int) -> bool:
    """Who may change an account's plan and money going out: the owner,
    unless an advisor manages the account (then it's the advisor's, and the
    client's view is read-only), or that advisor (auth.can_view)."""
    import advising
    import auth
    if by == user_id:
        return advising.advisor_of(conn, user_id) is None
    return auth.can_view(conn, by, user_id)


def _out_from(row) -> dict:
    d = dict(row)
    d["amount"] = float(d["amount"])
    d["times"] = int(d.get("times") or 1)
    d["every_months"] = int(d.get("every_months") or (1 if d["kind"] == "withdrawal" else 12))
    d["inflation_pct"] = float(d["inflation_pct"]) if d.get("inflation_pct") else None
    return d


def list_money_out(conn, user_id: int, *, viewer: int | None = None) -> list[dict]:
    """The account's planned expenses and regular withdrawal, by date.
    With `viewer`, only for someone who may see the account (else
    PermissionError)."""
    if viewer is not None:
        import auth
        if not auth.can_view(conn, viewer, user_id):
            raise PermissionError("not your account")
    return [_out_from(r) for r in conn.execute(
        "SELECT * FROM money_out WHERE user_id = ? ORDER BY start_date, id", (user_id,))]


def get_withdrawal(items) -> dict | None:
    """The regular withdrawal among `items`, if one is set."""
    return next((i for i in items or () if i["kind"] == "withdrawal"), None)


def _clean_out(kind: str, fields: dict) -> dict:
    """Checked, tidied fields for a money_out row; ValueError when they don't make sense."""
    if kind not in OUT_KINDS:
        raise ValueError(f"unknown kind {kind!r}")
    f = {k: fields.get(k) for k in _OUT_FIELDS}
    try:
        f["amount"] = round(float(f["amount"]), 2)
    except (TypeError, ValueError):
        raise ValueError("Enter an amount above $0.") from None
    if f["amount"] <= 0:
        raise ValueError("Enter an amount above $0.")
    try:
        start = date.fromisoformat(str(f["start_date"])[:10])
    except ValueError:
        raise ValueError("Pick a date.") from None
    f["start_date"] = start.isoformat()
    f["label"] = (str(f["label"] or "").strip()[:60]) or None
    if kind == "expense":
        f["times"] = max(1, min(MAX_TIMES, int(f["times"] or 1)))
        f["every_months"] = max(1, min(120, int(f["every_months"] or 12)))
        f["end_date"], f["inflation_pct"] = None, None
        if not f["label"]:
            raise ValueError("Say what it's for (a car, tuition...).")
    else:
        f["times"], f["every_months"] = 1, 1
        if f["end_date"]:
            end = date.fromisoformat(str(f["end_date"])[:10])
            if end < start:
                raise ValueError("The end date is before the start.")
            f["end_date"] = end.isoformat()
        else:
            f["end_date"] = None
        infl = f["inflation_pct"]
        f["inflation_pct"] = None if not infl else max(0.0, min(15.0, float(infl))) or None
        f["label"] = f["label"] or "Regular withdrawal"
    return f


def add_money_out(conn, user_id: int, kind: str, fields: dict, *, by: int) -> int:
    """Add a planned expense, or set the regular withdrawal (it replaces the
    one there was). Returns its id. PermissionError for anyone but the owner
    or their advisor (may_change)."""
    if not may_change(conn, by, user_id):
        raise PermissionError("not your plan")
    f = _clean_out(kind, fields)
    if kind == "withdrawal":
        old = get_withdrawal(list_money_out(conn, user_id))
        if old:
            return update_money_out(conn, user_id, old["id"], fields, by=by)
    conn.execute(
        "INSERT INTO money_out (user_id, kind, label, amount, start_date, end_date, times, "
        "every_months, inflation_pct, set_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, kind, f["label"], f["amount"], f["start_date"], f["end_date"], f["times"],
         f["every_months"], f["inflation_pct"], by))
    conn.commit()
    return conn.execute("SELECT MAX(id) AS id FROM money_out WHERE user_id = ?",
                        (user_id,)).fetchone()["id"]


def update_money_out(conn, user_id: int, item_id: int, fields: dict, *, by: int) -> int:
    """Change one of the account's items (fields left out keep their value).
    Returns its id; LookupError if it isn't this account's."""
    if not may_change(conn, by, user_id):
        raise PermissionError("not your plan")
    row = conn.execute("SELECT * FROM money_out WHERE id = ? AND user_id = ?",
                       (item_id, user_id)).fetchone()
    if row is None:
        raise LookupError("no such item")
    old = _out_from(row)
    f = _clean_out(old["kind"], {**{k: old[k] for k in _OUT_FIELDS},
                                 **{k: v for k, v in fields.items() if k in _OUT_FIELDS}})
    conn.execute(
        "UPDATE money_out SET label = ?, amount = ?, start_date = ?, end_date = ?, times = ?, "
        "every_months = ?, inflation_pct = ?, set_by = ?, updated_at = datetime('now') "
        "WHERE id = ? AND user_id = ?",
        (f["label"], f["amount"], f["start_date"], f["end_date"], f["times"], f["every_months"],
         f["inflation_pct"], by, item_id, user_id))
    conn.commit()
    return item_id


def delete_money_out(conn, user_id: int, item_id: int, *, by: int) -> bool:
    """Remove one of the account's items; False if it wasn't there."""
    if not may_change(conn, by, user_id):
        raise PermissionError("not your plan")
    cur = conn.execute("DELETE FROM money_out WHERE id = ? AND user_id = ?", (item_id, user_id))
    conn.commit()
    return bool(cur.rowcount)


# ---- the month-by-month projection ----------------------------------------- #
def _d(s) -> date:
    return date.fromisoformat(str(s)[:10])


def step_of(d: date, today: date) -> int:
    """The projection month (1 = the month from today) an amount dated `d`
    comes out in: the first month-end on or after it. 0 or less: already past."""
    n = (d.year - today.year) * 12 + (d.month - today.month)
    if add_months(today, n) < d:
        n += 1
    return n


def _expense_steps(items, today: date, months: int) -> list[int]:
    out = []
    for it in items or ():
        if it["kind"] != "expense":
            continue
        start = _d(it["start_date"])
        for i in range(int(it.get("times") or 1)):
            n = step_of(add_months(start, i * int(it.get("every_months") or 12)), today)
            if 1 <= n <= months:
                out.append(n)
    return out


def _withdrawal_amounts(w: dict, today: date, months: int):
    """(step, amount) for each month of a regular withdrawal up to `months`."""
    start = _d(w["start_date"])
    end = _d(w["end_date"]) if w.get("end_date") else None
    first = step_of(start, today)
    rise = (w.get("inflation_pct") or 0.0) / 100
    for n in range(max(1, first), months + 1):
        k = n - first                                  # months since it started
        if end is not None and add_months(start, k) > end:
            break
        yield n, float(w["amount"]) * (1 + rise) ** (k // 12)


def out_schedule(items, today: date, months: int) -> dict[int, float]:
    """{projection month: amount coming out} for months 1..`months`; past
    dates are left out (they've happened)."""
    sched: dict[int, float] = {}
    for it in items or ():
        if it["kind"] == "withdrawal":
            for n, amt in _withdrawal_amounts(it, today, months):
                sched[n] = sched.get(n, 0.0) + amt
        else:
            start = _d(it["start_date"])
            for i in range(int(it.get("times") or 1)):
                n = step_of(add_months(start, i * int(it.get("every_months") or 12)), today)
                if 1 <= n <= months:
                    sched[n] = sched.get(n, 0.0) + float(it["amount"])
    return sched


def adding_stops(items, today: date) -> int | None:
    """The projection month money stops being added: when the regular
    withdrawal starts (people stop adding when they start living on it).
    None: it keeps being added."""
    w = get_withdrawal(items)
    return max(1, step_of(_d(w["start_date"]), today)) if w else None


def simulate(present: float, monthly: float, annual_pct: float, months: int,
             sched: dict | None = None, *, add_until: int | None = None) -> dict:
    """Month by month: grow at `annual_pct`, add `monthly` at the end of
    each month (until month `add_until`), take out `sched` {month: amount}.
    {"values": value after each month, [0] = today; "runs_out": the first
    month there wasn't enough to take out, or None}. The value never goes
    below 0 - what can't be taken out isn't."""
    r = _monthly_rate(annual_pct)
    value, values, runs_out = float(present), [float(present)], None
    sched = sched or {}
    for n in range(1, max(0, months) + 1):
        add = monthly if add_until is None or n < add_until else 0.0
        value = value * (1 + r) + add - sched.get(n, 0.0)
        if value < -1e-9:
            if runs_out is None:
                runs_out = n
            value = 0.0
        values.append(value)
    return {"values": values, "runs_out": runs_out}


def value_at(present: float, monthly: float, annual_pct: float, months: int, items=None, *,
             today: date | None = None) -> float:
    """future_value(), with the money going out in `items` taken out on its
    dates (the same as future_value when there's none)."""
    if not items or today is None:
        return future_value(present, monthly, annual_pct, months)
    months = max(0, months)
    return simulate(present, monthly, annual_pct, months, out_schedule(items, today, months),
                    add_until=adding_stops(items, today))["values"][-1]


def _required_with_out(present, target, annual_pct, months, items, today):
    def reach(m):
        return value_at(present, m, annual_pct, months, items, today=today)
    if reach(0.0) >= target:
        return 0.0
    hi = max(100.0, (target - present) / months)
    while reach(hi) < target:
        hi *= 2
        if hi > 1e10:
            return None       # nothing added makes it: additions stopped already
    lo = 0.0
    while hi - lo > 0.005:
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if reach(mid) < target else (lo, mid)
    return hi


def age_from(profile: dict | None) -> int | None:
    """About how old they are, from the profile's age range (None if unanswered)."""
    return _AGE_MIDDLE.get((profile or {}).get("age_range"))


def lasting(present: float, monthly: float, annual_pct: float, items, *, today: date,
            age: int | None = None) -> dict | None:
    """How long the money lasts with the regular withdrawal (and any
    expenses), month by month at `annual_pct`. None without a withdrawal.

    {"monthly": its first amount, "start": its first projection month,
    "horizon": how far it's checked (to about LAST_AGE with an `age`, else
    LAST_YEARS of withdrawals, or its end date), "runs_out": the month the
    money can't cover it, or None if it lasts the whole way, "less": how
    much less a month (in $50s) lasts the whole way, "later": how many
    years later a start would. Arithmetic, not advice."""
    w = get_withdrawal(items)
    if not w:
        return None
    start = max(1, step_of(_d(w["start_date"]), today))
    if w.get("end_date"):
        horizon = step_of(_d(w["end_date"]), today)
    elif age is not None:
        horizon = (LAST_AGE - age) * 12
    else:
        horizon = start + LAST_YEARS * 12
    horizon = max(1, min(OUT_CAP_YEARS * 12, max(horizon, start + 12)))

    def runs_out(its):
        return simulate(present, monthly, annual_pct, horizon, out_schedule(its, today, horizon),
                        add_until=adding_stops(its, today))["runs_out"]

    found = {"monthly": float(w["amount"]), "start": start, "horizon": horizon,
             "runs_out": runs_out(items), "less": None, "later": None}
    if found["runs_out"] is not None:
        others = [i for i in items if i is not w]
        if runs_out(others) is None:      # without the withdrawal it lasts: some less does
            lo, hi = 0.0, float(w["amount"])
            while hi - lo > 1:
                mid = (lo + hi) / 2
                ok = runs_out(others + [{**w, "amount": w["amount"] - mid}]) is None
                lo, hi = (lo, mid) if ok else (mid, hi)
            found["less"] = float(min(w["amount"], -(-hi // 50) * 50))
        for years in range(1, 16):
            moved = {**w, "start_date": add_months(_d(w["start_date"]), 12 * years).isoformat()}
            if w.get("end_date"):
                moved["end_date"] = add_months(_d(w["end_date"]), 12 * years).isoformat()
            if runs_out(others + [moved]) is None:
                found["later"] = years
                break
    return found


def out_horizon(items, today: date, months: int, age: int | None = None) -> int:
    """How far a projection with this money going out runs: the goal date,
    and on past the last expense and through the regular withdrawal's
    lasting check."""
    h = max(0, months)
    steps = _expense_steps(items, today, OUT_CAP_YEARS * 12)
    if steps:
        h = max(h, max(steps) + 6)
    w = get_withdrawal(items)
    if w:
        start = max(1, step_of(_d(w["start_date"]), today))
        if w.get("end_date"):
            end = step_of(_d(w["end_date"]), today)
        elif age is not None:
            end = (LAST_AGE - age) * 12
        else:
            end = start + LAST_YEARS * 12
        h = max(h, min(OUT_CAP_YEARS * 12, max(end, start + 12)))
    return h


def out_markers(items, today: date, months: int) -> list[dict]:
    """Where the chart marks money going out: each expense ("expense", a
    dip) and where the regular withdrawal starts ("income")."""
    out = []
    for it in items or ():
        if it["kind"] == "withdrawal":
            n = step_of(_d(it["start_date"]), today)
            if 1 <= n <= months:
                out.append({"date": add_months(today, n).isoformat(), "kind": "income",
                            "label": "Income starts"})
            continue
        start = _d(it["start_date"])
        for i in range(int(it.get("times") or 1)):
            n = step_of(add_months(start, i * int(it.get("every_months") or 12)), today)
            if 1 <= n <= months:
                out.append({"date": add_months(today, n).isoformat(), "kind": "expense",
                            "label": it.get("label") or "Expense"})
    return sorted(out, key=lambda m: m["date"])


def when_text(item: dict) -> str:
    """'Jun 2027', 'each year for 4 years from Sep 2027', 'from Jan 2035 to
    Dec 2040, rising 2.5% a year' - an item's dates in words (no amounts)."""
    def month(s):
        d = _d(s)
        return f"{d:%b} {d.year}"
    if item["kind"] == "withdrawal":
        text = f"a month from {month(item['start_date'])}"
        if item.get("end_date"):
            text += f" to {month(item['end_date'])}"
        if item.get("inflation_pct"):
            text += f", rising {item['inflation_pct']:g}% a year"
        return text
    times, every = int(item.get("times") or 1), int(item.get("every_months") or 12)
    if times <= 1:
        return month(item["start_date"])
    each = "each year" if every == 12 else f"every {every} months"
    return f"{each} for {times} {'years' if every == 12 else 'times'} from {month(item['start_date'])}"


def money_out_text(items, money=lambda v: f"${v:,.0f}") -> str:
    """The plan's money going out in one line, for a card or a PDF:
    "A car, $20,000 in Jun 2027; $2,000 a month from Jan 2035". `money`
    formats an amount (a masked one when amounts are hidden)."""
    parts = []
    for it in items or ():
        if it["kind"] == "withdrawal":
            parts.append(f"{money(it['amount'])} {when_text(it)}")
        else:
            w = when_text(it)
            parts.append(f"{it.get('label') or 'Expense'}, {money(it['amount'])} "
                         + (w if w.startswith(("each", "every")) else f"in {w}"))
    return "; ".join(parts)


# --------------------------------------------------------------------------- #
# what the portfolio could pay each year (the Plan's retirement view)
# --------------------------------------------------------------------------- #
# Rules of thumb for a yearly withdrawal, as a share of today's value. 4% is
# the best-known one, from studies of past US markets over 30-year
# retirements; 3-5% is the range planners usually talk about. Illustrations,
# never advice: nothing here says what anyone should take out.
WITHDRAWAL_RATES = (3.0, 4.0, 5.0)
# The one stated growth rate for "how long it lasts": modest on purpose,
# before inflation, fees and taxes.
LASTS_GROWTH_PCT = 4.0
LASTS_CAP_YEARS = 60
# A goal date this close (or a profile that says so) puts the view first.
NEAR_YEARS = 10
_RETIRED_ANSWERS = {"age_range": ("65 or older",),
                    "income_stability": ("Not working or retired",),
                    "contributions": ("Withdrawing regularly",)}
_INCOME_GOALS = ("Retirement", "Generate income")


def withdrawals(value: float, rates=WITHDRAWAL_RATES) -> list[dict]:
    """[{"rate", "yearly", "monthly"}]: `rate`% of `value` a year."""
    value = max(0.0, float(value or 0.0))
    return [{"rate": float(r), "yearly": value * r / 100, "monthly": value * r / 100 / 12}
            for r in rates]


def months_lasting(present: float, yearly: float, growth_pct: float = LASTS_GROWTH_PCT, *,
                   cap_years: int = LASTS_CAP_YEARS) -> int | None:
    """Whole months `present` keeps paying `yearly` (a twelfth at the start
    of each month), the rest growing at `growth_pct` a year. None when it's
    still paying after `cap_years` (or nothing is taken out); 0 when there
    isn't a first month's amount."""
    present, yearly = float(present or 0.0), float(yearly or 0.0)
    if yearly <= 0:
        return None
    take, r, value = yearly / 12, _monthly_rate(growth_pct), present
    for n in range(cap_years * 12):
        if value + 1e-9 < take:
            return n
        value = (value - take) * (1 + r)
    return None


def retirement_first(plan: dict | None, profile: dict | None, today: date) -> bool:
    """Whether the Plan leads with what the portfolio could pay each year:
    for someone retired or about to be - an answer that says so (65 or
    older, not working or retired, withdrawing regularly), or a retirement
    or income goal that isn't known to be more than NEAR_YEARS away (the
    plan's goal date, else the profile's time horizon)."""
    p = profile or {}
    if any(p.get(k) in v for k, v in _RETIRED_ANSWERS.items()):
        return True
    goals = {g.strip() for g in str(p.get("goal") or "").split(";")}
    if (plan or {}).get("goal_type"):
        goals.add(plan["goal_type"])
    if not goals & set(_INCOME_GOALS):
        return False
    if has_goal(plan) and plan.get("goal_type") in _INCOME_GOALS:
        return months_until(plan["target_date"], today) <= NEAR_YEARS * 12
    try:
        years = float(p.get("time_horizon_years"))
    except (TypeError, ValueError):
        return True     # a retirement goal, with no timeline to say it's far off
    return years <= NEAR_YEARS
