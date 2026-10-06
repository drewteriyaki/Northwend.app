"""Stress test your mix (ROADMAP overnight plan, item 3): how a mix of asset
classes would have done in three hard stretches - 2008 (the global financial
crisis), 2020 (the Covid drop) and 2022 (stocks and bonds both down).

For each: the drop from the stock market's high to its low, and roughly how
long the mix took to get back to where it started. Asset classes only
(Stocks / Bonds / Cash / Other, asset_classes.CLASSES) - never a fund.

Hypothetical and rounded on purpose. Each stretch has, per asset class, the
rough change of a broad index from the stock market's high to its low
("drop") and the rough yearly pace it grew at in the years after the low
("pace") - the same spirit as the advisor proposal card's hard years
(proposals.HARD_YEARS, calendar-year returns) and worked out with the same
weighted mix (asset_classes.mix_return). Recovery assumes each class then grew
at its pace, with no rebalancing and nothing added or taken out. The past
won't repeat the same way.

Pure functions, standard library only.
"""

from __future__ import annotations

import math

from asset_classes import mix_return as _mix_return

# Stocks: US and international stock indexes blended. Bonds: the US aggregate
# bond index. Cash: Treasury bills. Other: a rough middle for real estate and
# commodities. "months_down": the stock market's high to its low.
SCENARIOS = (
    {"key": "2008", "name": "2008: the global financial crisis",
     "when": "Oct 2007 to Mar 2009", "months_down": 17,
     "about": "Banks failed and stock markets around the world lost about half their value.",
     # stocks recovered over roughly 3 (US) to 5 (international) years
     "drop": {"Stocks": -50.0, "Bonds": 5.0, "Cash": 2.0, "Other": -55.0},
     "pace": {"Stocks": 20.0, "Bonds": 6.0, "Cash": 0.1, "Other": 15.0}},
    {"key": "2020", "name": "2020: the Covid drop",
     "when": "Feb to Mar 2020", "months_down": 1,
     "about": "Stocks fell about a third in a month, then recovered within the year.",
     # stocks were back within about 5 (US) to 8 (international) months
     "drop": {"Stocks": -34.0, "Bonds": -1.0, "Cash": 0.2, "Other": -35.0},
     "pace": {"Stocks": 100.0, "Bonds": 7.0, "Cash": 0.3, "Other": 50.0}},
    {"key": "2022", "name": "2022: stocks and bonds both down",
     "when": "Jan to Oct 2022", "months_down": 9,
     "about": "Rising interest rates pulled stocks and bonds down together - bonds "
              "cushioned less than usual.",
     # stocks were back in about 15 months; bonds took several years
     "drop": {"Stocks": -25.0, "Bonds": -16.0, "Cash": 1.0, "Other": -20.0},
     "pace": {"Stocks": 25.0, "Bonds": 5.0, "Cash": 4.5, "Other": 10.0}},
)
BY_KEY = {s["key"]: s for s in SCENARIOS}
MAX_MONTHS = 240   # past 20 years: "more than 20 years"

ASSUMPTIONS = ("Hypothetical, worked out from rounded figures for broad market indexes: US and "
               "international stocks blended, the US bond index, Treasury bills for cash, and "
               "a rough middle of real estate and commodities for other holdings. The drop is "
               "from the stock market's high to its low; the time back assumes each part then "
               "grew at about the pace it did in the years after, with nothing added, taken "
               "out or rebalanced. Real funds, fees and timing differ, and the past won't "
               "repeat the same way.")


def clean(mix: dict | None) -> dict:
    """{class: share} with only the shares above 0, scaled to add up to 100."""
    mix = {k: float(v) for k, v in (mix or {}).items() if v and float(v) > 0}
    total = sum(mix.values())
    return {k: v * 100 / total for k, v in mix.items()} if total else {}


def drop_pct(mix: dict, scenario: dict) -> float | None:
    """The mix's change from the high to the low, in % (negative is a drop)."""
    mix = clean(mix)
    return _mix_return(mix, scenario["drop"]) if mix else None


def months_back(mix: dict, scenario: dict, cap: int = MAX_MONTHS) -> int | None:
    """Months after the low until the mix is back where it started: 0 if it
    never fell, None if not within `cap` months. Each class grows from its
    low at its yearly pace; nothing is rebalanced."""
    mix = clean(mix)
    if not mix:
        return None
    parts = [(w / 100 * (1 + scenario["drop"].get(k, scenario["drop"]["Other"]) / 100),
              (1 + scenario["pace"].get(k, scenario["pace"]["Other"]) / 100) ** (1 / 12))
             for k, w in mix.items()]
    for m in range(cap + 1):
        if sum(v * g ** m for v, g in parts) >= 1 - 1e-9:
            return m
    return None


def run(mix: dict, value: float | None = None) -> list[dict]:
    """Each stretch for one mix: [{key, name, when, about, months_down,
    drop_pct, drop_usd (on `value`, or None), months_back}]."""
    out = []
    for s in SCENARIOS:
        pct = drop_pct(mix, s)
        if pct is None:
            continue
        out.append({"key": s["key"], "name": s["name"], "when": s["when"], "about": s["about"],
                    "months_down": s["months_down"], "drop_pct": pct,
                    "drop_usd": value * pct / 100 if value else None,
                    "months_back": months_back(mix, s)})
    return out


def worst(rows: list[dict]) -> dict | None:
    """The stretch with the biggest drop."""
    return min(rows, key=lambda r: r["drop_pct"]) if rows else None


def time_text(months: int | None) -> str:
    """'about 7 months', 'about 2½ years', 'more than 20 years'."""
    if months is None:
        return f"more than {MAX_MONTHS // 12} years"
    if months <= 0:
        return "no time"
    if months < 18:
        return f"about {months} month{'s' if months != 1 else ''}"
    halves = round(months / 6) / 2
    whole = math.floor(halves)
    return f"about {whole}{'½' if halves - whole else ''} years"
