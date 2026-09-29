"""Plans: one goal per account, progress toward it, and money in vs growth.

A plan is a goal (a target amount by a target date), how much is added each
month, and a target mix by asset type. It is written by the account owner or
their advisor (`set_by`). Everything else here is arithmetic on that plus
the account's imported snapshots and logged contributions - no network, no
Streamlit.

Projections are compound growth at an assumed yearly return, shown as a
range (the assumption plus and minus `SPREAD_PCT`), in today's dollars
without inflation. They illustrate what a plan implies; they don't predict.
"""

from __future__ import annotations

import json
from datetime import date

GOAL_TYPES = ("Retirement", "Buy a home", "Pay for education", "Build long-term wealth",
              "Big purchase", "Other")
DEFAULT_RETURN_PCT = 6.0
SPREAD_PCT = 2.0

_FIELDS = ("goal_type", "goal_name", "target_amount", "target_date", "monthly_contribution",
           "target_alloc", "notes")


# --------------------------------------------------------------------------- #
# storage
# --------------------------------------------------------------------------- #
def get_plan(conn, user_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM plans WHERE user_id = ?", (user_id,)).fetchone()
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


def month_total(conn, user_id: int, year: int, month: int) -> float:
    prefix = f"{year:04d}-{month:02d}-"
    row = conn.execute("SELECT SUM(amount) AS s FROM contributions WHERE user_id = ? AND date LIKE ?",
                       (user_id, prefix + "%")).fetchone()
    return float(row["s"] or 0.0)


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


def required_monthly(present: float, target: float, annual_pct: float, months: int) -> float | None:
    """Monthly amount that reaches `target` in `months` at `annual_pct`;
    0 if growth alone gets there, None when there's no time left."""
    if months <= 0:
        return None
    r = _monthly_rate(annual_pct)
    g = (1 + r) ** months
    gap = target - present * g
    if gap <= 0:
        return 0.0
    return gap / months if r == 0 else gap * r / (g - 1)


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
             return_pct: float = DEFAULT_RETURN_PCT, spread: float = SPREAD_PCT) -> dict:
    """Where the account stands against its goal.

    status: 'reached' (already at or past the target), 'on_track' (the
    assumed return gets there), 'within_reach' (only the optimistic end
    does), 'behind', or 'past_date' (the date has passed short of it)."""
    target = float(plan["target_amount"])
    monthly = float(plan.get("monthly_contribution") or 0.0)
    months = months_until(plan["target_date"], today)
    lo, mid, hi = (future_value(current_value, monthly, p, months)
                   for p in (return_pct - spread, return_pct, return_pct + spread))
    if current_value >= target:
        status = "reached"
    elif months <= 0:
        status = "past_date"
    elif mid >= target:
        status = "on_track"
    elif hi >= target:
        status = "within_reach"
    else:
        status = "behind"
    return {
        "target": target, "current": current_value, "monthly": monthly, "months": months,
        "pct_of_target": (current_value / target * 100) if target else None,
        "projected_low": lo, "projected": mid, "projected_high": hi,
        "needed_monthly": required_monthly(current_value, target, return_pct, months),
        "status": status,
    }


def projection_series(current_value: float, monthly: float, months: int, *, today: date,
                      return_pct: float = DEFAULT_RETURN_PCT, spread: float = SPREAD_PCT) -> list[dict]:
    """One row per month from today to the goal date: the low / assumed / high
    projected value. At most ~240 rows (long horizons are sampled)."""
    months = max(0, months)
    step = max(1, -(-months // 240))  # ceiling, so at most ~240 points
    points = list(range(0, months + 1, step))
    if points[-1] != months:
        points.append(months)
    return [{"date": add_months(today, n).isoformat(),
             "low": future_value(current_value, monthly, return_pct - spread, n),
             "mid": future_value(current_value, monthly, return_pct, n),
             "high": future_value(current_value, monthly, return_pct + spread, n)}
            for n in points]
