"""Learn the basics with your own numbers (direction item 14, flag
`learn_own_numbers`): after a basics topic's read, one short box "In your own
portfolio" with a fact from the person's own holdings next to the idea.

Description only (docs/PRINCIPLES.md principle 2): every line says what *is*
- counts, shares, a fee as a percentage - and never what to do or whether it
is good ("should", "consider", "too high", "better" never appear; the tests
run every template through ai_policy.findings). No tickers or fund names:
asset classes and kinds of holding only. Anything not from their own
holdings - the 2022 mix - is labelled hypothetical and comes from prices
already kept (the practice money's stand-ins in daily_bars), never a
projection. A topic with no honest fact to show has no box (SKIPPED).

Pure functions, standard library only: views/own_numbers.py draws the box.
Nothing here is saved and nothing goes to the AI.
"""

from __future__ import annotations

import fees
from allocation import CLASS_WORDS

TITLE = "In your own portfolio"
TITLE_EXAMPLE = "In the example portfolio"   # while the example portfolio is all there is
NO_HOLDINGS = ("Add your holdings (or try the example portfolio) to see this with your own "
               "numbers.")
# an advisor's client who can't bring holdings in or load the example themselves
NO_HOLDINGS_MANAGED = "Once your holdings are here, this shows the idea with your own numbers."

# Learn the basics' topics (views/get_started.py _basics_topics) that get a box
TOPICS = ("funds", "spread", "fees", "ups")
# ... and the ones that don't, with why - nothing invented to fill them
SKIPPED = {
    "time": "Compounding needs years of the person's own growth; their kept history is "
            "too short and mixes in deposits, so there's no honest fact to put beside it.",
    "accounts": "Northwend doesn't know an account's type (Roth IRA, 401(k), brokerage) - "
                "only the name the brokerage gives it - so it can't say which kinds they have.",
}

# the year both stocks and bonds fell, for "Ups and downs are normal"
DROP_YEAR = 2022
FIXED_2022 = ("In 2022, stocks and bonds both fell in the same year - bonds usually move less "
              "than stocks, but they can fall too. That's the same for everyone, whatever the "
              "mix.")


# ---- small words ------------------------------------------------------------- #
def share(pct: float) -> str:
    """A share in words: 'under 1%' for a sliver, else a whole percent."""
    return "under 1%" if 0 < pct < 1 else f"{pct:.0f}%"


def _signed(pct: float) -> str:
    """A change in words: 'down about 18%' / 'up about 3%' / 'about flat'."""
    if round(pct) == 0:
        return "about flat"
    return f"{'down' if pct < 0 else 'up'} about {abs(pct):.0f}%"


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _n(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _mv(pos: dict) -> float:
    v = pos.get("live_market_value")
    if v is None:
        v = pos.get("market_value")
    return float(v or 0.0)


# ---- what they hold ------------------------------------------------------------ #
_KIND_WORDS = {   # fees.holding_type -> (one, many)
    "fund": ("fund", "funds"),
    "stock": ("single stock", "single stocks"),
    "cash": ("cash or money market holding", "cash or money market holdings"),
    "other": ("other holding", "other holdings"),
}
_KIND_ORDER = ("fund", "stock", "other", "cash")


def by_holding(positions, info: dict | None) -> dict:
    """{symbol: {"kind": fees.holding_type, "value"}} - the same symbol in two
    accounts is one holding (as allocation.summary_words counts them)."""
    info = info or {}
    out: dict = {}
    for p in positions or ():
        sym = (p.get("symbol") or "").strip()
        if not sym:
            continue
        row = out.setdefault(sym, {"kind": fees.holding_type(
            (info.get(sym) or {}).get("quote_type"), p.get("asset_type")), "value": 0.0})
        row["value"] += _mv(p)
    return out


def funds_lines(positions, info: dict | None, total: float) -> list[str]:
    """Stocks, bonds and funds: how many of their holdings are funds and how
    many single stocks, and each kind's share of the total."""
    held = by_holding(positions, info)
    if not held or total <= 0:
        return []
    counts = {k: sum(1 for h in held.values() if h["kind"] == k) for k in _KIND_ORDER}
    values = {k: sum(h["value"] for h in held.values() if h["kind"] == k) for k in _KIND_ORDER}
    parts = [_n(counts[k], *_KIND_WORDS[k]) for k in _KIND_ORDER if counts[k]]
    out = [f"You hold {_join(parts)}."]
    shown = [k for k in ("fund", "stock") if counts[k] and values[k] > 0]
    if shown and len([k for k in _KIND_ORDER if values[k] > 0]) > 1:
        words = [f"{'Funds' if k == 'fund' else 'Single stocks'} are about "
                 f"{share(values[k] / total * 100)} of your total" if i == 0 else
                 f"{'funds' if k == 'fund' else 'single stocks'} about "
                 f"{share(values[k] / total * 100)}" for i, k in enumerate(shown)]
        out.append(", ".join(words) + ".")
    return out


def spread_lines(alloc: dict, positions, info: dict | None) -> list[str]:
    """Why spread it out: how many holdings, across which asset classes, and
    the largest single holding's share of the total (and what kind it is)."""
    total = float(alloc.get("portfolio_value") or 0.0)
    held = by_holding(positions, info)
    classes = [r["label"] for r in alloc.get("by_asset_class") or [] if r.get("pct")]
    if not held or total <= 0 or not classes:
        return []
    names = [CLASS_WORDS.get(c, "other holdings") for c in classes]
    n = len(held)
    if len(classes) == 1:
        out = [f"You have {_n(n, 'holding', 'holdings')}, all in {names[0]}."]
    else:
        out = [f"You have {_n(n, 'holding', 'holdings')} across {len(classes)} asset classes: "
               f"{_join(names)}."]
    sym, top = max(((s, h) for s, h in held.items()), key=lambda kv: (kv[1]["value"], kv[0]))
    if top["value"] > 0:
        kind = {"fund": " It's a fund, which holds many companies or bonds itself.",
                "stock": " It's a single company's stock."}.get(top["kind"], "")
        lead = "Your one holding is" if n == 1 else "Your largest single holding is"
        out.append(f"{lead} about {share(top['value'] / total * 100)} of your total.{kind}")
    return out


def fees_lines(result: dict, money: str | None = None) -> list[str]:
    """Fees add up: the Fee check's own result in words (fees.check()).
    `money` is Fee check's own "each year, at today's value" figure, already
    formatted - passed only where Fee check shows the dollars to this person."""
    if not fees.has_funds(result):
        return ["None of your holdings is a fund, so there's no yearly fund fee to add up - "
                "single stocks and cash don't charge one."]
    n_unknown = len(result["unknown"])
    if not result["funds"]:
        return ["The yearly fees for your funds aren't known here yet, so Fee check can't "
                "add them up so far. Each fund's page at your brokerage lists its fee as the "
                "expense ratio."]
    out = [f"Your funds' average yearly fee is about {fees.fmt_ratio(result['ratio'])} of what "
           "they're worth, weighted by how much is in each."]
    if money:
        out.append(f"At today's value that's about {money} a year - the same figure Fee check "
                   "shows.")
    if n_unknown:
        out.append(f"{_n(n_unknown, 'fund', 'funds')} with a fee not known yet "
                   f"{'isn' if n_unknown == 1 else 'aren'}'t counted.")
    return out


def year_change(prices, year: int) -> float | None:
    """The % change of one price series ([(YYYY-MM-DD, price)], dividends
    included) over a calendar year: the last price of the year before to the
    last of `year`. None unless both ends are kept (each within the last
    week of its year), so a gap never passes for a result."""
    before = after = None
    for d, p in sorted(prices or ()):
        d = str(d)[:10]
        if p is None:
            continue
        if d <= f"{year - 1}-12-31":
            before = (d, float(p))
        elif d <= f"{year}-12-31":
            after = (d, float(p))
    if not before or not after or before[1] <= 0:
        return None
    if before[0] < f"{year - 1}-12-24" or after[0] < f"{year}-12-24":
        return None
    return (after[1] / before[1] - 1) * 100


def mix_year(stock_prices, bond_prices, bond_pct: float, year: int = DROP_YEAR) -> dict | None:
    """A hypothetical mix of `bond_pct`% bonds and the rest in US stocks,
    bought at the start of `year` and left alone to its end, from the
    stand-ins' kept prices: {"stocks", "bonds", "mix"} in %. None without
    both years' prices."""
    s, b = year_change(stock_prices, year), year_change(bond_prices, year)
    if s is None or b is None:
        return None
    w = max(0.0, min(100.0, float(bond_pct))) / 100
    return {"stocks": s, "bonds": b, "mix": (1 - w) * s + w * b}


def ups_lines(alloc: dict, year: dict | None) -> list[str]:
    """Ups and downs are normal: their bond share, then 2022 - a hypothetical
    mix with the same bond share on the stand-ins' kept prices, or the fixed
    line, the same for everyone."""
    rows = {r["label"]: float(r.get("pct") or 0.0) for r in alloc.get("by_asset_class") or []}
    if not rows or float(alloc.get("portfolio_value") or 0.0) <= 0:
        return []
    bonds, stocks = rows.get("Bonds", 0.0), rows.get("Stocks", 0.0)
    if bonds > 0:
        out = [f"Bonds are about {share(bonds)} of your mix"
               + (f", stocks about {share(stocks)}." if stocks > 0 else ".")]
    else:
        out = ["Your mix has no bonds" + (f"; stocks are about {share(stocks)} of it."
                                          if stocks > 0 else ".")]
    if year is None:
        return out + [FIXED_2022]
    b = round(bonds)
    mix = (f"a mix of {b}% bonds and {100 - b}% US stocks" if 0 < b < 100 else
           "a mix of all US stocks" if b <= 0 else "a mix of all bonds")
    out.append(f"In {DROP_YEAR}, broad US stocks were {_signed(year['stocks'])} and broad US "
               f"bonds {_signed(year['bonds'])} - both fell in the same year.")
    out.append(f"Hypothetically, {mix} held through all of {DROP_YEAR} would have been "
               f"{_signed(year['mix'])}. That's from the practice money's past prices, "
               "dividends included - not your own holdings, and not a prediction.")
    return out


def lines(topic: str, *, alloc: dict | None = None, positions=(), info: dict | None = None,
          fee_result: dict | None = None, fee_money: str | None = None,
          year: dict | None = None) -> list[str]:
    """The box's lines for one basics topic, or [] for a topic without one."""
    alloc = alloc or {}
    if topic == "funds":
        return funds_lines(positions, info, float(alloc.get("portfolio_value") or 0.0))
    if topic == "spread":
        return spread_lines(alloc, positions, info)
    if topic == "fees":
        return fees_lines(fee_result, fee_money) if fee_result is not None else []
    if topic == "ups":
        return ups_lines(alloc, year)
    return []
