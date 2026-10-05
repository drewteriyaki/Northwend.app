"""Cash check (ROADMAP overnight plan, item 5): how much of a portfolio sits
in cash, and a plain word on what cash can earn.

Two kinds of cash are told apart:
- plain cash in the accounts - the brokerage's default "sweep", which often
  pays little,
- money market funds held as positions (fees.holding_type "cash"), which
  pay a rate closer to short-term interest rates.

No rate is promised and no fund or brokerage is named: the page shows what
each 1% a year would be worth on the cash, and says it's worth checking what
the cash earns at the person's own brokerage.

Pure functions, standard library only.
"""

from __future__ import annotations

SHARE_PCT = 10.0       # shown when cash is at least this share of the portfolio...
DOLLARS = 5000.0       # ...or at least this many dollars (real dollars only)


def summary(sweep: float, money_market: float, portfolio_value: float, *,
            pretend: bool = False) -> dict:
    """{"cash", "sweep", "money_market", "pct" (of the portfolio, or None),
    "per_point" (dollars a year for each 1% of interest), "show"}.
    `pretend`: a percentages portfolio's dollars are made up, so only the
    share counts toward showing it."""
    sweep = max(0.0, float(sweep or 0.0))
    mm = max(0.0, float(money_market or 0.0))
    cash = sweep + mm
    value = float(portfolio_value or 0.0)
    pct = cash / value * 100 if value > 0 else None
    show = cash > 0 and pct is not None and (
        pct >= SHARE_PCT or (not pretend and cash >= DOLLARS))
    return {"cash": cash, "sweep": sweep, "money_market": mm, "pct": pct,
            "per_point": cash / 100, "show": show}


def yearly_at(cash: float, rate_pct: float) -> float:
    """What `cash` would earn in a year at `rate_pct` (simple, for an example)."""
    return max(0.0, float(cash or 0.0)) * max(0.0, float(rate_pct or 0.0)) / 100


def mostly(s: dict) -> str:
    """'sweep', 'money_market' or 'both' - which kind holds most of it."""
    if not s["cash"]:
        return "sweep"
    share = s["sweep"] / s["cash"]
    return "sweep" if share >= 0.8 else "money_market" if share <= 0.2 else "both"
