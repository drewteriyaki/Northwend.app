"""Get started: the logic behind the new-investor path. Pure functions, no
Streamlit, no network.

- readiness(): the common order of operations before investing (emergency
  savings, high-interest debt, an employer match, money needed soon), read
  from the investing profile's answers.
- starter_mix(): an example stock / bond split from the time horizon and
  comfort with risk - a transparent rule of thumb for learning, shown with
  its reasons, not a recommendation.
- simulate(): a practice portfolio - a monthly amount invested in a mix
  over real past prices - and max_drawdown() for its worst drop.

Everything here is general education. Example funds are well-known,
low-cost index funds, named so the lessons are concrete.
"""

from __future__ import annotations

from datetime import date

# The building blocks of a simple portfolio, each with example funds. The
# first example of each is what the practice portfolio buys.
BLOCKS = (
    {"key": "us", "label": "US stocks", "examples": ("VTI", "ITOT", "SCHB"),
     "about": "A total US stock market fund: thousands of US companies, large and small, "
              "in one fund."},
    {"key": "intl", "label": "International stocks", "examples": ("VXUS", "IXUS"),
     "about": "Companies outside the US - Europe, Asia, emerging markets - so you're not tied "
              "to one country's economy."},
    {"key": "bonds", "label": "Bonds", "examples": ("BND", "AGG", "SCHZ"),
     "about": "Loans to the US government and companies that pay interest. They usually move "
              "less than stocks, which steadies the whole portfolio."},
)
PRACTICE_TICKERS = {b["key"]: b["examples"][0] for b in BLOCKS}
US_SHARE_OF_STOCKS = 0.7  # the rest of the stock portion goes international

# ---- readiness ------------------------------------------------------------ #
GOOD, CAUTION, STOP, UNKNOWN = "good", "caution", "stop", "unknown"


def readiness(profile: dict) -> list[dict]:
    """[{key, label, state, text}] - state is good / caution / stop, or
    unknown when the question hasn't been answered yet."""
    p = profile or {}
    items = []

    ef = p.get("emergency_fund")
    items.append({"key": "emergency_fund", "label": "Emergency savings", **(
        {"state": GOOD, "text": "You have a cushion, so a surprise bill won't force you to "
                                "sell investments at a bad time."}
        if ef in ("6+ months of expenses", "3-6 months") else
        {"state": CAUTION, "text": "Aim for 3-6 months of expenses in savings before investing "
                                   "money you might need soon."}
        if ef == "Under 3 months" else
        {"state": STOP, "text": "Start with an emergency fund - even $500-$1,000 in savings "
                                "helps - so a surprise bill doesn't land on a credit card or "
                                "force you to sell."}
        if ef == "None" else
        {"state": UNKNOWN, "text": "Answer the emergency savings question in your profile."})})

    debt = p.get("high_interest_debt")
    items.append({"key": "high_interest_debt", "label": "High-interest debt", **(
        {"state": GOOD, "text": "No high-interest debt working against you."}
        if debt == "None" else
        {"state": CAUTION if debt == "Some" else STOP,
         "text": "Credit card interest (often 20% a year or more) usually costs more than "
                 "investing is likely to earn, so paying it down first is a strong move."}
        if debt in ("Some", "A lot") else
        {"state": UNKNOWN, "text": "Answer the high-interest debt question in your profile."})})

    match = p.get("employer_match")
    items.append({"key": "employer_match", "label": "Employer match", **(
        {"state": GOOD, "text": "You're getting your employer's full match - money you'd "
                                "otherwise leave on the table."}
        if match == "Yes, and I get the full match" else
        {"state": CAUTION, "text": "Putting in enough to get the full match is usually the "
                                   "best return available: the match is often 50% or 100% of "
                                   "what you put in."}
        if match == "Yes, but I'm not getting all of it" else
        {"state": GOOD, "text": "No employer match to collect. An IRA is a common place to "
                                "start instead."}
        if match == "No match or no plan" else
        {"state": CAUTION, "text": "Check your benefits site or ask HR - many employers match "
                                   "part of what you put into a 401(k)."}
        if match == "Not sure" else
        {"state": UNKNOWN, "text": "Answer the employer match question in your profile."})})

    wd = p.get("withdrawal_needs")
    if wd == "A large amount":
        items.append({"key": "withdrawal_needs", "label": "Money you'll need soon",
                      "state": CAUTION,
                      "text": "Money you'll need within about 3 years is usually kept in "
                              "savings or short-term bonds, not stocks - prices can drop a lot "
                              "in a short time."})
    if p.get("income_stability") == "Varies a lot":
        items.append({"key": "income_stability", "label": "Uneven income", "state": CAUTION,
                      "text": "With income that varies, a bigger emergency fund (6 months or "
                              "more) matters more."})
    return items


def readiness_summary(items: list[dict]) -> str:
    states = {i["state"] for i in items}
    if STOP in states:
        return "Start here first"
    if CAUTION in states:
        return "A few things to look at"
    if UNKNOWN in states:
        return "Answer a few questions"
    return "Ready to start"


# ---- example mix ------------------------------------------------------------ #
_RISK_ADJ = {"conservative": -15, "moderate": 0, "aggressive": 10}
_DROP_ADJ = {"Sell everything": -15, "Sell some": -5, "Hold and wait": 0, "Buy more": 5}


def _base_stock_pct(years: float) -> int:
    if years < 3:
        return 20
    if years < 5:
        return 40
    if years < 10:
        return 60
    if years < 20:
        return 75
    return 90


def starter_mix(profile: dict, horizon_years: float | None = None) -> dict:
    """An example split for learning: {stocks_pct, weights {us, intl, bonds}
    (percent), horizon_years, short_horizon, reasons}. `horizon_years`
    overrides the profile's (e.g. from the plan's target date). None when
    there's no horizon to go on."""
    p = profile or {}
    years = horizon_years if horizon_years is not None else p.get("time_horizon_years")
    if not years:
        return None
    years = float(years)
    base = _base_stock_pct(years)
    reasons = [f"{years:g}-year horizon: about {base}% in stocks is a common starting point - "
               + ("the longer the money can stay invested, the more time there is to recover "
                  "from drops." if years >= 5 else
                  "money needed soon has less time to recover from a drop.")]
    stocks = base
    risk = p.get("risk_tolerance")
    if risk in _RISK_ADJ and _RISK_ADJ[risk]:
        stocks += _RISK_ADJ[risk]
        reasons.append(f"{risk.capitalize()} comfort with risk: "
                       + ("less in stocks." if _RISK_ADJ[risk] < 0 else "more in stocks."))
    drop = p.get("drawdown_reaction")
    if drop in _DROP_ADJ and _DROP_ADJ[drop]:
        stocks += _DROP_ADJ[drop]
        reasons.append(f"You said you'd \"{drop.lower()}\" after a 20% drop: "
                       + ("a steadier mix makes that less likely." if _DROP_ADJ[drop] < 0
                          else "you're comfortable riding out drops."))
    stocks = int(5 * round(max(10, min(95, stocks)) / 5))
    us = round(stocks * US_SHARE_OF_STOCKS)
    return {"stocks_pct": stocks, "weights": {"us": us, "intl": stocks - us, "bonds": 100 - stocks},
            "horizon_years": years, "short_horizon": years < 3, "reasons": reasons}


def target_date_year(plan: dict | None, age_range: str | None, today: date) -> int | None:
    """The year for a target-date retirement fund, rounded to the nearest 5:
    the plan's retirement date if there is one, else age 65 from the age
    range's middle."""
    if plan and plan.get("goal_type") == "Retirement" and plan.get("target_date"):
        year = int(str(plan["target_date"])[:4])
    else:
        mid = {"Under 25": 22, "25-34": 30, "35-44": 40, "45-54": 50, "55-64": 60}.get(age_range or "")
        if mid is None:
            return None
        year = today.year + (65 - mid)
    return int(5 * round(year / 5))


# ---- lesson numbers --------------------------------------------------------- #
def grow_monthly(monthly: float, years: float, annual_pct: float) -> float:
    """What `monthly` a month grows to over `years` at `annual_pct`."""
    months = int(round(years * 12))
    r = (1 + annual_pct / 100) ** (1 / 12) - 1
    return monthly * months if r == 0 else monthly * ((1 + r) ** months - 1) / r


def fee_cost(monthly: float, years: float, annual_pct: float, low_fee: float, high_fee: float) -> float:
    """How much less a higher-fee fund leaves you with: the same monthly
    amount grown at (return - fee) for each fee."""
    return (grow_monthly(monthly, years, annual_pct - low_fee)
            - grow_monthly(monthly, years, annual_pct - high_fee))


# ---- practice portfolio ----------------------------------------------------- #
def simulate(prices: dict[str, list[tuple[str, float]]], weights: dict[str, float], *,
             monthly: float, initial: float = 0.0, start: str | None = None) -> list[dict]:
    """A practice portfolio over past prices: `initial` invested on the first
    day, then `monthly` on the first trading day of each later month, each
    amount split by `weights` ({ticker: share}, any scale) and never
    rebalanced. `prices` is {ticker: [(YYYY-MM-DD, price), ...]}; prices
    should include dividends (adjusted close). Only days every weighted
    ticker has a price are used. Returns [{date, money_in, value, nav}],
    where nav is the portfolio's time-weighted growth of $1 (contributions
    don't move it)."""
    w = {t: float(v) for t, v in weights.items() if v and float(v) > 0}
    if not w:
        return []
    total_w = sum(w.values())
    w = {t: v / total_w for t, v in w.items()}
    by_ticker = {t: dict(prices.get(t) or []) for t in w}
    days = sorted(set.intersection(*(set(d) for d in by_ticker.values())))
    if start:
        days = [d for d in days if d >= start]
    units = {t: 0.0 for t in w}
    money_in, nav, prev_value, out, last_month = 0.0, 1.0, 0.0, [], None
    for i, d in enumerate(days):
        amount = (initial + monthly) if i == 0 else (monthly if d[:7] != last_month else 0.0)
        last_month = d[:7]
        before = sum(units[t] * by_ticker[t][d] for t in w)  # today's prices, before adding
        if prev_value:
            nav *= before / prev_value
        if amount:
            for t, share in w.items():
                units[t] += amount * share / by_ticker[t][d]
            money_in += amount
        value = before + amount
        prev_value = value
        out.append({"date": d, "money_in": money_in, "value": value, "nav": nav})
    return out


def max_drawdown(rows: list[dict]) -> float | None:
    """The worst fall from a high, in % (negative), on the time-weighted
    `nav` from simulate() - price moves only, so a contribution made right
    after a drop doesn't hide it. None with fewer than two rows."""
    if len(rows) < 2:
        return None
    peak, worst = rows[0]["nav"], 0.0
    for r in rows:
        peak = max(peak, r["nav"])
        worst = min(worst, r["nav"] / peak - 1)
    return worst * 100
