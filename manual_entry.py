"""Holdings typed in by hand, for people with no Schwab file to import.

A hand entry becomes a snapshot exactly like an import: the same row shapes
as portfolio.parse_csv(), saved by portfolio.write_snapshot(), so the
Dashboard, Plan, Activity, asset classes and alerts all work unchanged.
Each save is a snapshot dated the day it's saved (replacing that day's, as a
re-import would).

Values come from prices looked up at save time - Finnhub first (the live
price source), then Yahoo, which also gives the name. A symbol with no price
anywhere is rejected, which catches typos too.
"""

from __future__ import annotations

from datetime import date

SOURCE = "manual entry"          # snapshots.source_file for a hand-entered snapshot
DEFAULT_ACCOUNT = "My account"

# the choices in the form -> broker asset types (what imports store)
TYPES = {"Stock": "Equity", "ETF": "ETFs & Closed End Funds", "Mutual fund": "Mutual Funds",
         "Bond": "Fixed Income", "Crypto": "Crypto", "Other": "Other"}
_TYPE_OF = {v: k for k, v in TYPES.items()}
MAX_ROWS = 200


def type_label(asset_type: str | None) -> str:
    return _TYPE_OF.get(asset_type or "", "Other")


def _num(v):
    if v is None or v == "":
        return None
    try:
        f = float(str(v).replace(",", "").replace("$", "").strip())
    except ValueError:
        return "bad"
    return None if f != f else f  # NaN (an empty table cell) counts as blank


def prefill(positions: list[dict], cash_by_account: dict) -> tuple[list[dict], list[dict]]:
    """Form rows from the latest snapshot, so an update starts from what's there."""
    holdings = [{"Account": p.get("account") or DEFAULT_ACCOUNT, "Symbol": p.get("symbol"),
                 "Shares": p.get("quantity"), "Total cost": p.get("cost_basis"),
                 "Type": type_label(p.get("asset_type"))}
                for p in sorted(positions, key=lambda p: (p.get("account") or "", p.get("symbol") or ""))]
    cash = [{"Account": a, "Cash": v} for a, v in sorted(cash_by_account.items()) if v]
    return holdings, cash


def validate(holdings: list[dict], cash: list[dict]) -> tuple[list[dict], dict, list[str]]:
    """Clean the form rows: (holdings, {account: cash}, errors). Blank rows are
    dropped; any error means nothing should be saved."""
    errors, out, seen = [], [], set()
    for i, r in enumerate(holdings, start=1):
        sym = str(r.get("Symbol") or "").strip().upper()
        shares, cost = _num(r.get("Shares")), _num(r.get("Total cost"))
        acct = str(r.get("Account") or "").strip() or DEFAULT_ACCOUNT
        if not sym and shares is None and cost is None:
            continue  # an empty row
        where = f"Row {i}" + (f" ({sym})" if sym else "")
        if not sym:
            errors.append(f"{where}: add a symbol.")
        elif not all(ch.isalnum() or ch in ".-/^" for ch in sym) or len(sym) > 12:
            errors.append(f"{where}: '{sym}' doesn't look like a ticker symbol.")
        if shares in (None, "bad") or (shares != "bad" and shares <= 0):
            errors.append(f"{where}: enter how many shares, more than 0.")
        if cost == "bad" or (cost is not None and cost != "bad" and cost < 0):
            errors.append(f"{where}: total cost should be a dollar amount, or blank.")
        if (acct, sym) in seen:
            errors.append(f"{where}: {sym} is listed twice in {acct} - combine them into one row.")
        seen.add((acct, sym))
        out.append({"account": acct, "symbol": sym, "quantity": shares,
                    "cost_basis": cost if cost != "bad" else None,
                    "asset_type": TYPES.get(r.get("Type"), TYPES["Other"])})
    if len(out) > MAX_ROWS:
        errors.append(f"That's more than {MAX_ROWS} holdings - import a file instead.")
    cash_by_account: dict = {}
    # Cash left on the default name, when every holding is in one renamed
    # account, belongs to that account (its row was made before the rename).
    named = {h["account"] for h in out}
    only = next(iter(named)) if len(named) == 1 and DEFAULT_ACCOUNT not in named else None
    for r in cash:
        acct = str(r.get("Account") or "").strip() or DEFAULT_ACCOUNT
        if acct == DEFAULT_ACCOUNT and only:
            acct = only
        v = _num(r.get("Cash"))
        if v is None:
            continue
        if v == "bad" or v < 0:
            errors.append(f"Cash for {acct}: enter a dollar amount, or leave it blank.")
            continue
        cash_by_account[acct] = cash_by_account.get(acct, 0.0) + v
    if not out and not cash_by_account:
        errors.append("Add at least one holding or some cash.")
    return out, cash_by_account, errors


def lookup(symbols, *, finnhub_quote=None, yahoo_info=None, known_names=None) -> dict:
    """{symbol: {"price": float | None, "name": str | None}}. `finnhub_quote(sym)`
    returns a price or None; `yahoo_info(sym)` returns (price, name). Names
    already known (from the last snapshot) are kept without asking Yahoo."""
    known_names = known_names or {}
    out = {}
    for sym in sorted(set(symbols)):
        price = finnhub_quote(sym) if finnhub_quote else None
        name = known_names.get(sym)
        if (price is None or not name) and yahoo_info:
            y_price, y_name = yahoo_info(sym)
            price = price if price is not None else y_price
            name = name or y_name
        out[sym] = {"price": price, "name": name}
    return out


def build(holdings: list[dict], cash_by_account: dict, found: dict, *,
          today: date | None = None) -> tuple[dict, list[dict], dict, list[str]]:
    """(meta, rows, totals, errors) in parse_csv()'s shapes, ready for
    portfolio.write_snapshot(). Errors name symbols with no price."""
    snap = (today or date.today()).isoformat()
    errors = [f"No price found for {h['symbol']} - check the symbol."
              for h in holdings if (found.get(h["symbol"]) or {}).get("price") in (None, 0)]
    rows = []
    for h in holdings:
        price = (found.get(h["symbol"]) or {}).get("price") or 0.0
        mv = round(h["quantity"] * price, 2)
        cost = h["cost_basis"]
        rows.append({
            "snapshot_date": snap, "account": h["account"], "symbol": h["symbol"],
            "description": (found.get(h["symbol"]) or {}).get("name"),
            "asset_type": h["asset_type"], "quantity": h["quantity"], "cost_basis": cost,
            "market_value": mv,
            "reported_gain": round(mv - cost, 2) if cost is not None else None,
            "reported_gain_pct": round((mv - cost) / cost * 100, 2) if cost else None,
        })
    totals = {a: {"cash_value": cash_by_account.get(a), "reported_cost_basis": None,
                  "reported_market_value": None, "reported_gain": None,
                  "reported_gain_pct": None}
              for a in sorted({r["account"] for r in rows} | set(cash_by_account))}
    meta = {"snapshot_date": snap, "as_of_text": "Entered by hand"}
    return meta, rows, totals, errors


# ---- percentages only ------------------------------------------------------ #
# For people who'd rather not enter real amounts: each holding's share of the
# portfolio, against a pretend total. Shares are worked out from today's
# price, and the cost is set to today's value, so gains track from today.
PCT_SOURCE = "percentages"
DEFAULT_TOTAL = 10_000.0


def prefill_weights(positions: list[dict], cash_by_account: dict) -> tuple[list[dict], float]:
    """Percent rows (and a cash %) from a snapshot's values."""
    cash = sum(v or 0.0 for v in cash_by_account.values())
    total = sum(p.get("market_value") or 0.0 for p in positions) + cash
    rows = [{"Account": p.get("account") or DEFAULT_ACCOUNT, "Symbol": p.get("symbol"),
             "Percent": round((p.get("market_value") or 0.0) / total * 100, 1) if total else None,
             "Type": type_label(p.get("asset_type"))}
            for p in sorted(positions, key=lambda p: -(p.get("market_value") or 0.0))]
    return rows, (round(cash / total * 100, 1) if total else 0.0)


def validate_weights(rows: list[dict], cash_pct, total) -> tuple[list[dict], float, list[str]]:
    """Clean percent rows: (holdings with "weight", cash %, errors). The
    percentages and cash must add up to 100."""
    errors, out, seen = [], [], set()
    for i, r in enumerate(rows, start=1):
        sym = str(r.get("Symbol") or "").strip().upper()
        pct = _num(r.get("Percent"))
        acct = str(r.get("Account") or "").strip() or DEFAULT_ACCOUNT
        if not sym and pct is None:
            continue
        where = f"Row {i}" + (f" ({sym})" if sym else "")
        if not sym:
            errors.append(f"{where}: add a symbol.")
        elif not all(ch.isalnum() or ch in ".-/^" for ch in sym) or len(sym) > 12:
            errors.append(f"{where}: '{sym}' doesn't look like a ticker symbol.")
        if pct in (None, "bad") or (pct != "bad" and not 0 < pct <= 100):
            errors.append(f"{where}: enter a percentage between 0 and 100.")
        if (acct, sym) in seen:
            errors.append(f"{where}: {sym} is listed twice in {acct} - combine them into one row.")
        seen.add((acct, sym))
        out.append({"account": acct, "symbol": sym, "weight": pct if pct != "bad" else 0.0,
                    "asset_type": TYPES.get(r.get("Type"), TYPES["Other"])})
    cash = _num(cash_pct)
    if cash == "bad" or (cash is not None and not 0 <= cash <= 100):
        errors.append("Cash should be a percentage between 0 and 100, or blank.")
        cash = 0.0
    cash = cash or 0.0
    tot = _num(total)
    if tot in (None, "bad") or tot <= 0:
        errors.append("Enter a pretend total above 0.")
    if not out:
        errors.append("Add at least one holding.")
    elif not errors:
        added = sum(h["weight"] for h in out) + cash
        if abs(added - 100) > 0.5:
            errors.append(f"The percentages add up to {added:g}% - make them total 100%.")
    return out, cash, errors


def build_weights(holdings: list[dict], cash_pct: float, total: float, found: dict, *,
                  today: date | None = None) -> tuple[dict, list[dict], dict, list[str]]:
    """Like build(), from percentages of a pretend `total`."""
    shares = []
    for h in holdings:
        price = (found.get(h["symbol"]) or {}).get("price")
        value = round(total * h["weight"] / 100, 2)
        shares.append({**h, "quantity": round(value / price, 6) if price else 0.0,
                       "cost_basis": value})
    meta, rows, totals, errors = build(shares, {}, found, today=today)
    for r, h in zip(rows, shares):
        r["market_value"] = h["cost_basis"]   # exactly the chosen share of the total
        r["reported_gain"], r["reported_gain_pct"] = 0.0, 0.0
    if cash_pct:
        acct = holdings[0]["account"] if holdings else DEFAULT_ACCOUNT
        totals.setdefault(acct, {k: None for k in ("cash_value", "reported_cost_basis",
                                                   "reported_market_value", "reported_gain",
                                                   "reported_gain_pct")})
        totals[acct]["cash_value"] = round(total * cash_pct / 100, 2)
    meta["as_of_text"] = f"Percentages of a pretend {total:,.0f}"
    return meta, rows, totals, errors


# ---- the real price sources ------------------------------------------------ #
def finnhub_price(key: str | None):
    """A finnhub_quote callable for lookup(), or None without a key."""
    if not key:
        return None
    from update_prices import fetch_quote

    def quote(sym):
        data, _err = fetch_quote(sym, key, 8.0)
        c = (data or {}).get("c")
        return float(c) if c else None  # an unknown symbol comes back as c=0
    return quote


def yahoo_price_and_name(sym: str):
    """(price, name) from Yahoo, (None, None) if it has nothing."""
    try:
        import yfinance as yf
        info = yf.Ticker(sym).info or {}
    except Exception:
        return None, None
    price = info.get("regularMarketPrice") or info.get("navPrice") or info.get("previousClose")
    return (float(price) if price else None), (info.get("shortName") or info.get("longName"))
