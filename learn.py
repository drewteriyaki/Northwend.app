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
    # each step says how many points it moves the split, so the list adds up
    # to the number shown above it (a starting point, then the adjustments)
    reasons = [f"{round(years, 1):g}-year horizon: start from about {base}% in stocks, a "
               "common starting point - "
               + ("the longer the money can stay invested, the more time there is to recover "
                  "from drops." if years >= 5 else
                  "money needed soon has less time to recover from a drop.")]

    def _pts(n):
        return f"{abs(n)} points {'less' if n < 0 else 'more'} in stocks"

    stocks = base
    risk = p.get("risk_tolerance")
    if risk in _RISK_ADJ and _RISK_ADJ[risk]:
        stocks += _RISK_ADJ[risk]
        reasons.append(f"{risk.capitalize()} comfort with risk: {_pts(_RISK_ADJ[risk])}.")
    drop = p.get("drawdown_reaction")
    if drop in _DROP_ADJ and _DROP_ADJ[drop]:
        stocks += _DROP_ADJ[drop]
        reasons.append(f"You said you'd \"{drop.lower()}\" after a 20% drop: "
                       f"{_pts(_DROP_ADJ[drop])} - "
                       + ("a steadier mix makes that less likely." if _DROP_ADJ[drop] < 0
                          else "you're comfortable riding out drops."))
    adjusted = stocks
    stocks = int(5 * round(max(10, min(95, stocks)) / 5))
    if len(reasons) > 1 or stocks != adjusted:
        reasons.append(f"That comes to about {stocks}% in stocks"
                       + (" (kept between 10% and 95%)." if stocks != adjusted else "."))
    us = round(stocks * US_SHARE_OF_STOCKS)
    return {"stocks_pct": stocks, "weights": {"us": us, "intl": stocks - us, "bonds": 100 - stocks},
            "horizon_years": years, "short_horizon": years < 3, "reasons": reasons}


# ---- investor type ("Find your direction", ROADMAP G3) ----------------------- #
# Named from the readiness check and the example mix above, so the type always
# agrees with them. Education: "people in your spot often...", never "buy".
INVESTOR_TYPES = {
    "foundation": {
        "name": "Foundation builder", "line": "Build your base first - investing comes right after.",
        "about": "People in your spot usually start by putting a little aside for emergencies and "
                 "paying down high-interest debt. It's often the strongest first move: it protects "
                 "you from surprises, and credit-card interest costs more than investing tends to "
                 "earn.",
        "watch": "Once the base is in place, the example mix below shows what investing could "
                 "look like for you.",
        "kinds": ("A high-yield savings account for the emergency fund",
                  "Then a simple mix of broad index funds")},
    "short_term": {
        "name": "Short-term saver", "line": "Keep it safe and easy to reach.",
        "about": "Money you'll need within about 3 years usually stays out of the stock market, "
                 "because prices can fall a lot in a short time and might not recover before you "
                 "need it.",
        "watch": "Steadier places earn less, but the money is there when you need it.",
        "kinds": ("High-yield savings accounts", "Certificates of deposit (CDs)",
                  "Treasury bills", "Short-term bond funds")},
    "preserver": {
        "name": "Careful preserver", "line": "Steadiness first.",
        "about": "People who prefer a calmer ride often keep more in bonds than stocks. The "
                 "portfolio moves less day to day, and grows more slowly over time.",
        "watch": "Even a careful mix can fall in a bad year, just usually by less.",
        "kinds": ("A broad bond index fund for most of it",
                  "A total US stock market fund", "An international stock fund")},
    "balanced": {
        "name": "Balanced navigator", "line": "Growth and steadiness in equal measure.",
        "about": "A middle path: enough in stocks to grow, enough in bonds to soften the drops. "
                 "It's a common choice for goals several years away.",
        "watch": "In big market drops, a mix like this has historically fallen noticeably less "
                 "than stocks alone - and recovered more slowly in the strongest years.",
        "kinds": ("A total US stock market fund", "An international stock fund",
                  "A broad bond index fund", "Or one balanced or target-date fund")},
    "builder": {
        "name": "Steady builder", "line": "Growth with a cushion.",
        "about": "Mostly stocks for growth, with a slice of bonds to steady things. People with "
                 "goals around ten years away often start somewhere like this.",
        "watch": "Expect some years to be down 20% or more along the way - holding on through "
                 "them has historically mattered more than timing them.",
        "kinds": ("A total US stock market fund", "An international stock fund",
                  "A broad bond index fund", "Or one target-date fund")},
    "grower": {
        "name": "Long-horizon grower", "line": "Time is on your side.",
        "about": "With many years ahead, people in your spot often hold mostly stocks: there's "
                 "time to ride out the drops, and growth does the heavy lifting.",
        "watch": "Drops of 30% or more happen on a long journey. What tends to matter most is "
                 "staying invested and keeping up the monthly amount.",
        "kinds": ("A total US stock market fund", "An international stock fund",
                  "A small slice of a bond fund", "Or one target-date fund")},
}


def investor_type(profile: dict, mix: dict | None, items: list[dict]) -> dict | None:
    """{"key", "name", "line", "about", "watch", "kinds"} for the profile, or
    None until there's a time horizon to go on. Foundation (an emergency fund
    or high-interest debt comes first) and short-term money take precedence
    over the mix's stock share."""
    if mix is None:
        return None
    if any(i["state"] == STOP for i in items):
        key = "foundation"
    elif mix["short_horizon"]:
        key = "short_term"
    elif mix["stocks_pct"] >= 80:
        key = "grower"
    elif mix["stocks_pct"] >= 60:
        key = "builder"
    elif mix["stocks_pct"] >= 40:
        key = "balanced"
    else:
        key = "preserver"
    return {"key": key, **INVESTOR_TYPES[key]}


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


# ---- learn more from trusted sources -------------------------------------- #
# One small "Learn more" next to an idea the app explains, to the matching page
# on a public education site - Investor.gov (the SEC), FINRA or the CFPB -
# never their text copied in. topic -> (what the page is about, its address,
# who runs it). A page shows one with learn_more(topic) (dashboard.py).
LEARN_MORE_SITES = {   # the only sites linked to, and how they're named
    "www.investor.gov": "Investor.gov",
    "www.finra.org": "FINRA",
    "www.consumerfinance.gov": "the CFPB",
}
LEARN_MORE = {
    "index_funds": ("what an index fund is",
                    "https://www.investor.gov/introduction-investing/investing-basics/"
                    "glossary/index-fund", "Investor.gov"),
    "etfs": ("ETFs and mutual funds, side by side",
             "https://www.finra.org/investors/insights/etf-vs-mutual-fund", "FINRA"),
    "bonds": ("how bonds work",
              "https://www.investor.gov/introduction-investing/investing-basics/"
              "investment-products/bonds-or-fixed-income-products/bonds", "Investor.gov"),
    "diversification": ("spreading your money out",
                        "https://www.investor.gov/introduction-investing/investing-basics/"
                        "save-and-invest/diversify-your-investments", "Investor.gov"),
    "asset_allocation": ("asset allocation and diversification",
                         "https://www.investor.gov/introduction-investing/getting-started/"
                         "asset-allocation", "Investor.gov"),
    "rebalancing": ("rebalancing back to your mix",
                    "https://www.investor.gov/introduction-investing/investing-basics/"
                    "glossary/rebalancing", "Investor.gov"),
    "market_drops": ("why a mix of investments softens a drop",
                     "https://www.investor.gov/additional-resources/general-resources/"
                     "publications-research/info-sheets/beginners-guide-asset", "Investor.gov"),
    "expense_ratios": ("fund fees and expenses",
                       "https://www.investor.gov/introduction-investing/general-resources/"
                       "news-alerts/alerts-bulletins/investor-bulletins/"
                       "mutual-fund-and-etf-fees-and-expenses-investor-bulletin", "Investor.gov"),
    "compound_interest": ("compound interest",
                          "https://www.investor.gov/introduction-investing/investing-basics/"
                          "glossary/compound-interest", "Investor.gov"),
    "risk": ("what risk means in investing",
             "https://www.investor.gov/introduction-investing/investing-basics/what-risk",
             "Investor.gov"),
    "risk_tolerance": ("knowing your comfort with risk",
                       "https://www.investor.gov/introduction-investing/investing-basics/"
                       "save-and-invest/gauge-your-risk-tolerance", "Investor.gov"),
    "account_types": ("retirement accounts: IRAs and 401(k)s",
                      "https://www.finra.org/investors/investing/investment-accounts/"
                      "retirement-accounts", "FINRA"),
    "brokerage_accounts": ("brokerage accounts",
                           "https://www.finra.org/investors/investing/investment-accounts/"
                           "brokerage-accounts", "FINRA"),
    "dividends": ("what a dividend is",
                  "https://www.investor.gov/introduction-investing/investing-basics/"
                  "glossary/dividend", "Investor.gov"),
    "emergency_fund": ("building an emergency fund",
                       "https://www.consumerfinance.gov/an-essential-guide-to-building-an-"
                       "emergency-fund/", "the CFPB"),
}


def learn_more_md(topic: str) -> str:
    """The "Learn more" line for `topic` as Streamlit markdown - a link,
    which Streamlit opens in a new tab - or "" for an unknown topic."""
    entry = LEARN_MORE.get(topic)
    if not entry:
        return ""
    label, url, source = entry
    return f":material/open_in_new: Learn more at {source}: [{label}]({url})"
