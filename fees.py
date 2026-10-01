"""Fee check (ROADMAP G10): what each fund's yearly fee costs in dollars.

A fund takes its expense ratio out of what you hold, a little every day, so
there is never a bill to notice. This turns it into dollars: the yearly cost
at today's value, the portfolio's total, and what that adds up to over 10 and
30 years if the money grew at an assumed rate - the fees themselves plus the
growth that money would have earned.

Beside each fund: what low-cost index funds of the same kind often charge,
as education only. Nothing here names a fund to buy or says to switch.

The expense ratio comes from Yahoo via sync_history (security_info.expense_ratio,
a fraction: 0.0003 = 0.03%). Pure logic, standard library only.
"""

from __future__ import annotations

import re

from asset_classes import from_yahoo

GROWTH = 0.06          # the assumed yearly growth for "over the years" (said in the window)
HORIZONS = (10, 30)

# What broad, low-cost index funds of each kind often charge a year, as a
# fraction - rounded ballpark figures (2026) for learning what's typical,
# never a particular fund. Review now and then; they drift down over time.
KINDS = {
    "us_stock": ("US stock funds", 0.0005),
    "intl_stock": ("International stock funds", 0.0007),
    "stock": ("Stock funds", 0.0005),
    "bond": ("Bond funds", 0.0005),
    "target_date": ("Target-date funds", 0.0010),
    "balanced": ("Balanced funds", 0.0012),
    "sector": ("Sector and specialty funds", 0.0010),
}

FUND_TYPES = ("ETF", "MUTUALFUND")
# broker asset types (what imports store) that are funds
_FUND_ASSET_TYPES = ("ETFs & Closed End Funds", "Mutual Funds", "ETF / CEF")
_CASH_ASSET_TYPES = ("Cash and Money Market", "Cash")

# category words (Yahoo uses Morningstar-style categories: "Large Blend",
# "Foreign Large Blend", "Intermediate Core Bond", "Target-Date 2055" ...)
_BOND_WORDS = ("bond", "muni", "government", "treasury", "inflation", "corporate",
               "high yield", "ultrashort", "bank loan", "multisector", "securitized")
_SECTOR_WORDS = ("technology", "health", "financial", "real estate", "utilities", "energy",
                 "natural resources", "communications", "consumer", "industrials",
                 "commodities", "precious metals", "infrastructure", "digital assets",
                 "derivative income", "options", "sector", "preferred")
_INTL_WORDS = ("foreign", "world", "global", "international", "emerging", "europe",
               "pacific", "asia", "japan", "china", "india", "latin america", "intl",
               "ex-us", "ex us", "developed markets")
_US_STYLE = re.compile(r"\b(large|mid|small)\b|\b(blend|growth|value)\b")
_US_NAMES = ("s&p 500", "500 index", "total stock", "total market", "total us",
             "russell", "nasdaq", "dow jones")
_TARGET_NAMES = ("target retirement", "target date", "target-date", "lifepath",
                 "freedom 20", "freedom index 20")


def _has(text: str, words) -> bool:
    return any(w in text for w in words)


def kind_of(category: str | None, name: str | None = None, info: dict | None = None) -> str | None:
    """The kind of fund (a KINDS key) from Yahoo's category, else its name,
    else what it holds; None when it's a kind with no simple low-cost
    comparison (leveraged / inverse trading funds) or nothing is known."""
    cat = (category or "").lower()
    if cat.startswith("trading") or _has(cat, ("leveraged", "inverse")):
        return None
    if cat:
        if "target-date" in cat or "target date" in cat:
            return "target_date"
        if "allocation" in cat:
            return "balanced"
        if _has(cat, _BOND_WORDS):
            return "bond"
        if _has(cat, _SECTOR_WORDS):
            return "sector"
        if _has(cat, _INTL_WORDS):
            return "intl_stock"
        if _US_STYLE.search(cat):
            return "us_stock"
    nm = (name or "").lower()
    if nm:
        if _has(nm, ("leveraged", "inverse", "ultrapro", "2x", "3x")):
            return None
        if _has(nm, _TARGET_NAMES):
            return "target_date"
        if _has(nm, ("bond", "treasury", "fixed income")):
            return "bond"
        if _has(nm, _INTL_WORDS):
            return "intl_stock"
        if _has(nm, _US_NAMES):
            return "us_stock"
    split = from_yahoo({k: v for k, v in (info or {}).items() if k != "quote_type"})
    if split:
        stocks, bonds = split.get("Stocks", 0.0), split.get("Bonds", 0.0)
        if stocks >= 0.8:
            return "stock"
        if bonds >= 0.8:
            return "bond"
        if stocks >= 0.15 and bonds >= 0.15:
            return "balanced"
    return None


def holding_type(quote_type: str | None, asset_type: str | None) -> str:
    """'fund', 'stock', 'cash' or 'other' (no fund fee: crypto, single bonds...)."""
    qt = (quote_type or "").upper()
    if qt in FUND_TYPES:
        return "fund"
    if qt == "MONEYMARKET" or (not qt and asset_type in _CASH_ASSET_TYPES):
        return "cash"
    if qt == "EQUITY":
        # a closed-end fund trades like a stock (Yahoo calls it EQUITY) but
        # the broker files it with funds - it has a fee we don't know
        return "fund" if asset_type in _FUND_ASSET_TYPES else "stock"
    if not qt:
        if asset_type in _FUND_ASSET_TYPES:
            return "fund"
        if asset_type == "Equity":
            return "stock"
    return "other"


def cost_over(value: float, ratio: float, years: int, growth: float = GROWTH) -> dict:
    """What a yearly fee of `ratio` takes from `value` over `years`, if the
    money grew `growth` a year with nothing added and the fee came out at
    each year's end. {paid: the fees themselves, lost_growth: what those
    dollars would have grown to on top, total: the difference in the end
    balance (paid + lost_growth)}."""
    value, ratio = max(0.0, float(value or 0.0)), max(0.0, float(ratio or 0.0))
    bal, paid = value, 0.0
    for _ in range(int(years)):
        bal *= 1 + growth
        fee = bal * ratio
        paid += fee
        bal -= fee
    total = value * (1 + growth) ** int(years) - bal
    return {"paid": paid, "lost_growth": total - paid, "total": total}


def check(holdings, info_by_symbol: dict | None, *, growth: float = GROWTH,
          horizons=HORIZONS) -> dict:
    """The fee check for `holdings` ([{symbol, name, asset_type, value}], one
    per position - the same fund in two accounts is added up) with their
    security_info rows ({symbol: row}). Returns:

      funds    - [{symbol, name, value, ratio, yearly, kind, kind_label,
                  typical, typical_yearly, over: {years: cost_over()}}] for
                  funds with a known expense ratio, biggest yearly cost first
      unknown  - [{symbol, name, value}] funds whose expense ratio isn't known
      no_fee   - symbols of single stocks and other holdings with no fund fee
      cash     - symbols of cash and money market holdings (left out)
      total_yearly, value_known (what the funds with a known fee are worth),
      ratio    - the yearly cost as a share of value_known (None if nothing),
      over     - {years: cost_over()} added up across the funds,
      growth, horizons."""
    info_by_symbol = info_by_symbol or {}
    merged: dict = {}
    for h in holdings or []:
        sym = (h.get("symbol") or "").strip()
        if not sym:
            continue
        row = merged.setdefault(sym, {"symbol": sym, "name": h.get("name"),
                                      "asset_type": h.get("asset_type"), "value": 0.0})
        row["value"] += float(h.get("value") or 0.0)
        row["name"] = row["name"] or h.get("name")
    funds, unknown, no_fee, cash = [], [], [], []
    for sym, h in merged.items():
        info = info_by_symbol.get(sym) or {}
        kind_of_holding = holding_type(info.get("quote_type"), h["asset_type"])
        if kind_of_holding == "cash":
            cash.append(sym)
            continue
        if kind_of_holding != "fund":
            no_fee.append(sym)
            continue
        name = info.get("name") or h["name"] or sym
        ratio = info.get("expense_ratio")
        if ratio is None:
            unknown.append({"symbol": sym, "name": name, "value": h["value"]})
            continue
        ratio = float(ratio)
        kind = kind_of(info.get("category"), name, info)
        label, typical = KINDS.get(kind, (None, None))
        funds.append({"symbol": sym, "name": name, "value": h["value"], "ratio": ratio,
                      "yearly": h["value"] * ratio, "kind": kind, "kind_label": label,
                      "typical": typical,
                      "typical_yearly": h["value"] * typical if typical is not None else None,
                      "over": {y: cost_over(h["value"], ratio, y, growth) for y in horizons}})
    funds.sort(key=lambda f: (-f["yearly"], f["symbol"]))
    unknown.sort(key=lambda f: (-f["value"], f["symbol"]))
    total_yearly = sum(f["yearly"] for f in funds)
    value_known = sum(f["value"] for f in funds)
    over = {y: {k: sum(f["over"][y][k] for f in funds) for k in ("paid", "lost_growth", "total")}
            for y in horizons}
    return {"funds": funds, "unknown": unknown, "no_fee": sorted(no_fee), "cash": sorted(cash),
            "total_yearly": total_yearly, "value_known": value_known,
            "ratio": (total_yearly / value_known) if value_known else None,
            "over": over, "growth": growth, "horizons": tuple(horizons)}


def has_funds(result: dict) -> bool:
    """Anything for the fee check to show: a fund, known fee or not."""
    return bool(result["funds"] or result["unknown"])


def fmt_ratio(ratio: float | None) -> str:
    """0.0003 -> '0.03%', 0.00015 -> '0.015%', 0.0075 -> '0.75%'."""
    if ratio is None:
        return "—"
    s = f"{ratio * 100:.3f}"
    if s.endswith("0"):
        s = s[:-1]
    return s + "%"
