"""Keep prices current by themselves, so there's no Refresh button.

While someone has the dashboard open, freshen() runs about once a minute
(an auto-rerunning fragment in dashboard.py). For each ticker the account
holds it decides whether a new quote is due:

- stocks and ETFs: every minute while the US market is open (9:30-4:00 ET,
  weekdays); once more after the close to pick up the closing price; not
  at all overnight or on weekends;
- crypto (BTC-USD ...): every few minutes, around the clock;
- mutual funds: they price once a day after the close, so hourly is plenty.

"Due" is judged from price_history, which every account shares: a ticker
fetched in the last minute for anyone is reused, not fetched again, so the
number of requests grows with the number of different tickers, not with the
number of people watching - that keeps within Finnhub's free limit (60 a
minute). Stocks and ETFs come from Finnhub, falling back to Yahoo; crypto and
mutual funds come from Yahoo, which Finnhub's free quotes don't cover.

New prices are then written onto the account's positions with
update_prices.apply_live_prices(), the same step the scheduled job uses.
"""

from __future__ import annotations

import threading
from datetime import datetime, time, timedelta, timezone

from update_prices import _record_quote, apply_live_prices, fetch_quote, latest_snapshot, utc_now_iso

try:
    from zoneinfo import ZoneInfo
    NY = ZoneInfo("America/New_York")
except Exception:  # no timezone data: US Eastern standard time (an hour off in summer)
    NY = timezone(timedelta(hours=-5))

OPEN, CLOSE = time(9, 30), time(16, 0)
EVERY_OPEN = timedelta(seconds=55)      # a hair under the page's 60 s tick
EVERY_CRYPTO = timedelta(minutes=5)
EVERY_FUND = timedelta(hours=1)
_LOCK = threading.Lock()                # one freshen at a time in this process


def market_open(now: datetime | None = None) -> bool:
    """US stock market hours (holidays not counted)."""
    ny = (now or datetime.now(timezone.utc)).astimezone(NY)
    return ny.weekday() < 5 and OPEN <= ny.time() < CLOSE


def last_close(now: datetime | None = None) -> datetime:
    """The most recent 4:00 PM ET close at or before `now` (as UTC)."""
    ny = (now or datetime.now(timezone.utc)).astimezone(NY)
    day = ny.date()
    while True:
        close = datetime.combine(day, CLOSE, tzinfo=NY)
        if day.weekday() < 5 and close <= ny:
            return close.astimezone(timezone.utc)
        day -= timedelta(days=1)


def kind(symbol: str, asset_type: str | None) -> str:
    """'crypto', 'fund' (mutual fund) or 'stock' (stocks, ETFs and the rest)."""
    if symbol.endswith("-USD") or asset_type == "Crypto":
        return "crypto"
    if asset_type == "Mutual Funds":
        return "fund"
    return "stock"


def due(k: str, last_fetch: datetime | None, now: datetime) -> bool:
    """Whether a ticker of kind `k`, last fetched at `last_fetch`, needs a new quote."""
    if last_fetch is None:
        return True
    age = now - last_fetch
    if k == "crypto":
        return age >= EVERY_CRYPTO
    if k == "fund":
        return age >= EVERY_FUND
    if market_open(now):
        return age >= EVERY_OPEN
    return last_fetch < last_close(now)  # once after the close, for the closing price


def _parse(ts):
    if not ts:
        return None
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00").replace(" ", "T"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _latest(conn, tickers) -> dict:
    """{ticker: (price, fetched_at)} from the newest successful quote of each."""
    if not tickers:
        return {}
    ph = ", ".join("?" for _ in tickers)
    rows = conn.execute(
        "SELECT ph.ticker, ph.price, ph.fetched_at FROM price_history ph JOIN ("
        f" SELECT ticker, MAX(fetched_at) m FROM price_history WHERE ok = 1 AND ticker IN ({ph})"
        " GROUP BY ticker) last ON ph.ticker = last.ticker AND ph.fetched_at = last.m "
        "WHERE ph.ok = 1", tuple(tickers)).fetchall()
    return {r["ticker"]: (r["price"], _parse(r["fetched_at"])) for r in rows}


def _last_tried(conn, tickers) -> dict:
    """{ticker: when a quote was last asked for, whether or not it worked} - so
    a symbol nobody has a price for isn't asked again every minute."""
    if not tickers:
        return {}
    ph = ", ".join("?" for _ in tickers)
    return {r["ticker"]: _parse(r["m"]) for r in conn.execute(
        f"SELECT ticker, MAX(fetched_at) m FROM price_history WHERE ticker IN ({ph}) "
        "GROUP BY ticker", tuple(tickers))}


def yahoo_quote(symbol: str) -> tuple[dict, str]:
    """(data, error) in Finnhub's /quote shape (c, pc, d, dp, o, h, l, t) from Yahoo."""
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).fast_info
        price = info.get("lastPrice") if hasattr(info, "get") else info.last_price
        prev = info.get("previousClose") if hasattr(info, "get") else info.previous_close
    except Exception as exc:  # noqa: BLE001 - any Yahoo failure is just "no quote"
        return {}, f"yahoo: {type(exc).__name__}"
    if not price:
        return {}, "yahoo: no price"
    price, prev = float(price), (float(prev) if prev else None)
    return {"c": price, "pc": prev, "d": (price - prev) if prev else None,
            "dp": ((price - prev) / prev * 100) if prev else None,
            "t": int(datetime.now(timezone.utc).timestamp())}, ""


def _record_yahoo(conn, ticker, data, error, ok):
    """Like update_prices._record_quote, marked as coming from Yahoo."""
    _record_quote(conn, ticker, data, error, ok)
    conn.execute("UPDATE price_history SET source = 'yahoo' WHERE id = "
                 "(SELECT MAX(id) FROM price_history WHERE ticker = ?)", (ticker,))
    conn.commit()


def freshen(conn, user_id: int, finnhub_key: str | None, *, now: datetime | None = None,
            finnhub=None, yahoo=None) -> dict:
    """Fetch whatever quotes are due for this account's holdings and watchlist,
    and apply the newest known price of every holding to its positions.
    `finnhub(symbol)` and `yahoo(symbol)` return (data, error) and are for tests.

    Returns {"fetched": n, "updated": positions changed, "watch_fetched":
    watchlist tickers fetched, "as_of": newest quote time (UTC) of a holding or
    None, "live": whether anything updates on its own right now}."""
    now = now or datetime.now(timezone.utc)
    finnhub = finnhub or (lambda s: fetch_quote(s, finnhub_key, 8.0) if finnhub_key
                          else ({}, "no FINNHUB_API_KEY"))
    yahoo = yahoo or yahoo_quote
    snap = latest_snapshot(conn, user_id)
    held = {r["symbol"]: r["asset_type"] for r in conn.execute(
        "SELECT DISTINCT symbol, asset_type FROM positions WHERE snapshot_date = ? AND user_id = ?",
        (snap, user_id))} if snap else {}
    watched = [r["ticker"] for r in conn.execute(
        "SELECT ticker FROM watchlist WHERE user_id = ?", (user_id,))]
    kinds = {s: kind(s, t) for s, t in held.items()}
    for w in watched:
        kinds.setdefault(w, kind(w, None))
    if not kinds:
        return {"fetched": 0, "updated": 0, "watch_fetched": 0, "as_of": None, "live": False}
    fetched, watch_fetched = 0, 0
    with _LOCK:
        tried = _last_tried(conn, list(kinds))  # read inside the lock: another viewer may have just fetched
        for sym, k in sorted(kinds.items()):
            if not due(k, tried.get(sym), now):
                continue
            data, err = ({}, "") if k != "stock" else finnhub(sym)
            price = (data or {}).get("c")
            if k == "stock" and data and not err and price:
                _record_quote(conn, sym, data, "", True)
            else:
                data, err = yahoo(sym)
                ok = bool(data) and not err and bool(data.get("c"))
                _record_yahoo(conn, sym, data, err, ok)
            fetched += 1
            watch_fetched += sym not in held
        latest = _latest(conn, list(held))
    prices = {s: p for s, (p, _) in latest.items() if p}
    held_fetched = fetched - watch_fetched
    updated = apply_live_prices(conn, snap, user_id, prices, utc_now_iso()) if held_fetched else 0
    as_of = max((t for _, t in latest.values() if t), default=None)
    return {"fetched": fetched, "updated": updated, "watch_fetched": watch_fetched,
            "as_of": as_of, "live": market_open(now) or "crypto" in kinds.values()}


def quotes(conn, tickers) -> dict:
    """{ticker: {"price", "prev_close", "change", "pct_change", "fetched_at"}}
    from each ticker's newest successful quote - for the watchlist rows."""
    tickers = sorted(set(tickers))
    if not tickers:
        return {}
    ph = ", ".join("?" for _ in tickers)
    rows = conn.execute(
        "SELECT ph.ticker, ph.price, ph.prev_close, ph.change, ph.pct_change, ph.fetched_at "
        "FROM price_history ph JOIN ("
        f" SELECT ticker, MAX(fetched_at) m FROM price_history WHERE ok = 1 AND ticker IN ({ph})"
        " GROUP BY ticker) last ON ph.ticker = last.ticker AND ph.fetched_at = last.m "
        "WHERE ph.ok = 1", tuple(tickers)).fetchall()
    return {r["ticker"]: {"price": r["price"], "prev_close": r["prev_close"],
                          "change": r["change"], "pct_change": r["pct_change"],
                          "fetched_at": _parse(r["fetched_at"])} for r in rows}
