"""Estimated dividend income by month, for the next 12 months.

Each holding is assumed to pay in the same months as it did over the past
year, the same amount per share, times the shares held now. The past
payments come from Yahoo's daily history (daily_bars.dividend - the amount
per share on each ex-dividend date, saved by sync_history.py). A holding with
a dividend yield but no payment history yet is spread evenly over the year,
and said so.

Months are ex-dividend months; the money usually arrives a few weeks later.
An estimate from the past, not a promise: companies change dividends.
"""

from __future__ import annotations

from datetime import date, timedelta


def _month(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def next_months(today: date, n: int = 12) -> list[str]:
    """'YYYY-MM' for this month and the n-1 after it."""
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def payments(conn, tickers, today: date) -> dict:
    """{ticker: [(ex_date, amount_per_share)]} over the last 12 months."""
    tickers = sorted(set(tickers))
    if not tickers:
        return {}
    since = (today - timedelta(days=365)).isoformat()
    ph = ", ".join("?" for _ in tickers)
    out: dict = {t: [] for t in tickers}
    for r in conn.execute(
            f"SELECT ticker, date, dividend FROM daily_bars WHERE dividend > 0 AND date > ? "
            f"AND ticker IN ({ph}) ORDER BY date", (since, *tickers)):
        out[r["ticker"]].append((date.fromisoformat(r["date"][:10]), float(r["dividend"])))
    return out


def has_history(conn, tickers) -> set:
    """The tickers whose daily bars were synced with dividends (any value,
    even 0) - so "no payments" can be told apart from "not synced yet"."""
    tickers = sorted(set(tickers))
    if not tickers:
        return set()
    ph = ", ".join("?" for _ in tickers)
    return {r["ticker"] for r in conn.execute(
        f"SELECT DISTINCT ticker FROM daily_bars WHERE dividend IS NOT NULL AND ticker IN ({ph})",
        tuple(tickers))}


def schedule(holdings, paid: dict, synced: set, today: date) -> dict:
    """The next 12 months of estimated income.

    holdings: [{"symbol", "quantity", "annual"}] - `annual` is the yield-based
    yearly estimate, used only for a holding with no payment history.
    Returns {"months": [{"month": "YYYY-MM", "total", "by_symbol": {sym: amount}}],
    "total", "spread": [symbols spread evenly], "none": [synced, no payments]}."""
    months = next_months(today)
    by_month = {m: {} for m in months}
    spread, none = [], []
    for h in holdings:
        sym, qty = h["symbol"], h.get("quantity") or 0.0
        past = paid.get(sym) or []
        if past and qty:
            for ex, per_share in past:
                # the same month next time round
                nxt = _month(date(ex.year + 1, ex.month, 1))
                key = nxt if nxt in by_month else _month(date(ex.year, ex.month, 1))
                if key in by_month:
                    by_month[key][sym] = by_month[key].get(sym, 0.0) + per_share * qty
        elif h.get("annual"):
            spread.append(sym)
            for m in months:
                by_month[m][sym] = by_month[m].get(sym, 0.0) + h["annual"] / 12
        elif sym in synced:
            none.append(sym)
    rows = [{"month": m, "by_symbol": by_month[m], "total": round(sum(by_month[m].values()), 2)}
            for m in months]
    return {"months": rows, "total": round(sum(r["total"] for r in rows), 2),
            "spread": sorted(spread), "none": sorted(none)}


def past_months(today: date, n: int = 12) -> list[str]:
    """'YYYY-MM' for the n months ending with this one, oldest first."""
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m < 1:
            y, m = y - 1, 12
    return out[::-1]


def received(conn, user_id: int, today: date) -> dict | None:
    """Dividends and interest actually paid in the last 12 months, from an
    imported activity export (txn_import.py) - None when none was imported.
    {"months": [{"month", "total", "by_symbol"}], "dividends", "interest",
    "total", "since": the first imported date, if inside the 12 months}."""
    first = conn.execute("SELECT MIN(trade_date) AS d FROM transactions WHERE user_id = ? AND "
                         "origin = 'imported'", (user_id,)).fetchone()["d"]
    if not first:
        return None
    months = past_months(today)
    by_month = {m: {} for m in months}
    divs = interest = 0.0
    for r in conn.execute(
            "SELECT trade_date, action, symbol, amount FROM transactions WHERE user_id = ? AND "
            "origin = 'imported' AND action IN ('DIV', 'INTEREST') AND amount > 0 AND "
            "trade_date >= ?", (user_id, months[0] + "-01")):
        m = r["trade_date"][:7]
        if m not in by_month:
            continue
        key = r["symbol"] or ("Interest" if r["action"] == "INTEREST" else "Other")
        by_month[m][key] = by_month[m].get(key, 0.0) + r["amount"]
        if r["action"] == "DIV":
            divs += r["amount"]
        else:
            interest += r["amount"]
    rows = [{"month": m, "by_symbol": by_month[m], "total": round(sum(by_month[m].values()), 2)}
            for m in months]
    return {"months": rows, "dividends": round(divs, 2), "interest": round(interest, 2),
            "total": round(divs + interest, 2),
            "since": first if first > months[0] + "-01" else None}
