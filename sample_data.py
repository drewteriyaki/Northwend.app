"""A made-up example portfolio, for trying the app without sharing anything.

Loaded into the person's own account as an ordinary snapshot whose source is
portfolio.SAMPLE_SOURCE, so every page works on it. The Dashboard marks it as
example data; clear() removes it, and portfolio.write_snapshot() removes it
automatically the moment real holdings (an import or a hand entry) are saved.

Prices here are rough starting values; the normal live price refresh
replaces them.
"""

from __future__ import annotations

from datetime import date

from portfolio import SAMPLE_SOURCE, write_snapshot

# (account, symbol, name, broker asset type, shares, total cost, rough price)
HOLDINGS = [
    ("Brokerage", "VTI", "Vanguard Total Stock Market ETF", "ETFs & Closed End Funds",
     40, 9200.0, 300.0),
    ("Brokerage", "VXUS", "Vanguard Total International Stock ETF", "ETFs & Closed End Funds",
     80, 4400.0, 65.0),
    ("Brokerage", "BND", "Vanguard Total Bond Market ETF", "ETFs & Closed End Funds",
     70, 5100.0, 73.0),
    ("Brokerage", "AAPL", "Apple Inc", "Equity", 12, 1900.0, 230.0),
    ("Roth IRA", "VOO", "Vanguard S&P 500 ETF", "ETFs & Closed End Funds", 10, 4300.0, 550.0),
    ("Roth IRA", "SCHD", "Schwab US Dividend Equity ETF", "ETFs & Closed End Funds",
     60, 1560.0, 28.0),
]
CASH = {"Brokerage": 850.0, "Roth IRA": 240.0}


def load(conn, user_id: int, *, today: date | None = None) -> int:
    """Save the example portfolio as today's snapshot. Returns the number of
    holdings. Only for an account with nothing in it (the caller checks)."""
    snap = (today or date.today()).isoformat()
    rows = []
    for acct, sym, name, asset_type, shares, cost, price in HOLDINGS:
        mv = round(shares * price, 2)
        rows.append({"snapshot_date": snap, "account": acct, "symbol": sym, "description": name,
                     "asset_type": asset_type, "quantity": float(shares), "cost_basis": cost,
                     "market_value": mv, "reported_gain": round(mv - cost, 2),
                     "reported_gain_pct": round((mv - cost) / cost * 100, 2)})
    totals = {a: {"cash_value": c, "reported_cost_basis": None, "reported_market_value": None,
                  "reported_gain": None, "reported_gain_pct": None} for a, c in CASH.items()}
    write_snapshot(conn, user_id, {"snapshot_date": snap, "as_of_text": "Example portfolio"},
                   rows, totals, SAMPLE_SOURCE)
    return len(rows)


def clear(conn, user_id: int) -> None:
    """Remove the example portfolio (every snapshot saved from it)."""
    from portfolio import clear_sample
    with conn:
        clear_sample(conn, user_id)
