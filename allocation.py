"""Portfolio allocation breakdowns. Pure functions, standard library only.

Groups holdings by asset type and by account, using the best available market
value per position (applied live value, else the CSV's), and treats each
account's cash as its own slice. Also flags positions that are a large share of
the whole portfolio.
"""

from __future__ import annotations

from asset_classes import from_asset_type

CONCENTRATION_PCT = 15.0  # a single position above this share of the portfolio is flagged

# what a holding is, for the concentration line (holding_kind)
SINGLE, BROAD_FUND, FOCUSED_FUND = "single", "broad_fund", "focused_fund"
FUND_QUOTE_TYPES = ("ETF", "MUTUALFUND", "MONEYMARKET")
# Yahoo (Morningstar) fund categories spread across a whole market, a style
# box or many bonds: "Large Blend", "Target-Date 2045", "Moderate Allocation",
# "Intermediate Core Bond", "Foreign Large Blend"... - not one sector or region
BROAD_CATEGORY_WORDS = ("blend", "growth", "value", "target", "allocation", "retirement",
                        "bond", "government", "muni", "money market", "inflation",
                        "diversified", "world", "global", "foreign large", "total")
BROAD_NAME_WORDS = ("total stock", "total market", "total world", "total bond",
                    "total international", "s&p 500", "target", "balanced", "lifestrategy",
                    "all-world", "all world", "aggregate bond")

# Long Schwab asset-type strings -> short labels for the chart.
SHORT_ASSET_TYPE = {
    "ETFs & Closed End Funds": "ETF / CEF",
    "Cash and Money Market": "Cash",
}


def _mv(pos):
    v = pos.get("live_market_value")
    if v is not None:
        return float(v)
    v = pos.get("market_value")
    return float(v) if v is not None else 0.0


def _rows(totals: dict, portfolio_value: float):
    rows = [{"label": k, "value": round(v, 2),
             "pct": round(v / portfolio_value * 100, 2) if portfolio_value else None}
            for k, v in totals.items()]
    rows.sort(key=lambda r: r["value"], reverse=True)
    return rows


def holding_kind(pos: dict, info: dict | None = None) -> str:
    """What one holding is, for the concentration line: SINGLE (one company,
    or nothing says it's a fund), BROAD_FUND (a fund spread across many
    companies or bonds - total market, S&P 500, target date, balanced, core
    bonds...) or FOCUSED_FUND (a fund in one sector, region or theme, by
    Yahoo's category). `info` is the holding's security_info row, if any.
    A fund with no category to go by counts as broad: it isn't flagged."""
    info = info or {}
    qt = (info.get("quote_type") or "").upper()
    at = (pos.get("asset_type") or "").lower()
    is_fund = (qt in FUND_QUOTE_TYPES
               or any(w in at for w in ("etf", "fund", "closed end", "money market")))
    if not is_fund or qt == "EQUITY":
        return SINGLE
    category = (info.get("category") or "").lower()
    if not category or any(w in category for w in BROAD_CATEGORY_WORDS):
        return BROAD_FUND
    name = (info.get("name") or pos.get("description") or "").lower()
    if any(w in name for w in BROAD_NAME_WORDS):
        return BROAD_FUND
    return FOCUSED_FUND


def allocate(positions, cash_by_account: dict | None = None, splits: dict | None = None,
             info: dict | None = None):
    """positions: iterable of dicts with account, asset_type, market_value and/or
    live_market_value. cash_by_account: {account: cash_value}. splits:
    {symbol: {class: fraction}} from asset_classes.splits(); a holding without
    one is classed by its broker asset type. info: {symbol: security_info
    row} (quote_type, category, name), so broad funds aren't flagged as
    concentrated (holding_kind).

    Returns {"portfolio_value", "by_asset_class", "by_asset_type", "by_account",
    "concentration"}. by_asset_class (Stocks / Bonds / Cash / Other) is what
    targets and drift use; by_asset_type is the broker's own grouping.
    Concentration lists holdings above CONCENTRATION_PCT that are a single
    company (kind SINGLE) or a fund focused on one area (FOCUSED_FUND).
    """
    cash_by_account = {k: float(v or 0.0) for k, v in (cash_by_account or {}).items()}
    positions = list(positions)
    splits = splits or {}

    holdings_value = sum(_mv(p) for p in positions)
    cash_total = sum(cash_by_account.values())
    portfolio_value = holdings_value + cash_total

    by_type: dict[str, float] = {}
    by_class: dict[str, float] = {}
    by_acct: dict[str, float] = {}
    for p in positions:
        mv = _mv(p)
        at = p.get("asset_type") or "Unknown"
        by_type[SHORT_ASSET_TYPE.get(at, at)] = by_type.get(SHORT_ASSET_TYPE.get(at, at), 0.0) + mv
        for cls, frac in (splits.get(p.get("symbol")) or from_asset_type(at)).items():
            by_class[cls] = by_class.get(cls, 0.0) + mv * frac
        acct = p.get("account") or "Unknown"
        by_acct[acct] = by_acct.get(acct, 0.0) + mv

    if cash_total:
        by_type["Cash"] = by_type.get("Cash", 0.0) + cash_total
        by_class["Cash"] = by_class.get("Cash", 0.0) + cash_total
    for acct, cash in cash_by_account.items():
        by_acct[acct] = by_acct.get(acct, 0.0) + cash

    concentration = []
    for p in positions:
        mv = _mv(p)
        share = (mv / portfolio_value * 100) if portfolio_value else 0.0
        if share > CONCENTRATION_PCT:
            kind = holding_kind(p, (info or {}).get(p.get("symbol")))
            if kind == BROAD_FUND:
                continue   # a fund of many companies isn't one company's risk
            concentration.append({
                "symbol": p.get("symbol"),
                "account": p.get("account"),
                "value": round(mv, 2),
                "pct": round(share, 2),
                "kind": kind,
            })
    concentration.sort(key=lambda r: r["pct"], reverse=True)

    return {
        "portfolio_value": round(portfolio_value, 2),
        # a class under 0.05% (a fund's leftover slivers) isn't worth a "0.0%" row
        "by_asset_class": _rows({k: v for k, v in by_class.items()
                                 if portfolio_value and v / portfolio_value >= 0.0005},
                                portfolio_value),
        "by_asset_type": _rows(by_type, portfolio_value),
        "by_account": _rows(by_acct, portfolio_value),
        "concentration": concentration,
    }


# ---- the plain-words read on Home (flag plain_summary) ----------------------- #
# docs/AI_PLAN.md section 9, row 1 - rules, not AI: fixed templates over the
# mix, the same words for the same numbers, reviewed once. Descriptive only:
# shares, counts and the largest holding's share - never a judgement ("too
# much", "well diversified"), never what to do. Northwend has no data on
# where a fund's companies are based, so there is no US / international
# part (never an invented figure).
CLASS_WORDS = {"Stocks": "stocks", "Bonds": "bonds", "Cash": "cash", "Other": "other holdings"}


def _share(pct: float) -> str:
    # below 1 (not 0.5): "{:.0f}" rounds halves to even, so 0.5% read "0%"
    return "under 1%" if 0 < pct < 1 else f"{pct:.0f}%"


def _join(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def summary_words(alloc: dict, positions=()) -> str:
    """The mix in plain words, from allocate()'s result and the same
    positions: 'About 70% in stocks, 25% in bonds and 5% in cash. 12
    holdings across 2 accounts; the largest, VTI, is 31% of the total.'
    Empty when there's nothing to read."""
    rows = [r for r in alloc.get("by_asset_class") or [] if r.get("pct")]
    port = float(alloc.get("portfolio_value") or 0.0)
    if not rows or port <= 0:
        return ""
    if len(rows) == 1:
        out = [f"Everything is in {CLASS_WORDS.get(rows[0]['label'], 'other holdings')}."]
    else:
        out = ["About " + _join([f"{_share(r['pct'])} in "
                                 f"{CLASS_WORDS.get(r['label'], 'other holdings')}"
                                 for r in rows]) + "."]
    by_symbol: dict[str, float] = {}
    for p in positions or ():
        if p.get("symbol"):
            by_symbol[p["symbol"]] = by_symbol.get(p["symbol"], 0.0) + _mv(p)
    if by_symbol:
        n = len(by_symbol)
        count = f"{n} holding{'' if n == 1 else 's'}"
        accounts = len(alloc.get("by_account") or [])
        if accounts > 1:
            count += f" across {accounts} accounts"
        sym, top = max(by_symbol.items(), key=lambda kv: (kv[1], kv[0]))
        out.append(count + (f"; the largest, {sym}, is {_share(top / port * 100)} of the "
                            "total." if n > 1 and top > 0 else "."))
    return " ".join(out)
