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

Many tabs open at once (launch week, docs/RUNBOOK.md): one tab fetches at a
time and the others skip that minute rather than wait; no database connection
is held while quotes are fetched; and the whole process asks Finnhub at most
FINNHUB_PER_MINUTE times a minute, asking Yahoo for the rest.

New prices are then written onto the account's positions with
update_prices.apply_live_prices(), the same step the scheduled job uses.
"""

from __future__ import annotations

import collections
import threading
import time as time_mod
from contextlib import contextmanager
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
_LOCK = threading.Lock()                # one tab fetching at a time in this process (others skip)


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


class Budget:
    """At most `per_minute` calls in any 60 seconds, for the whole process
    (every open tab together). take() says whether one more call fits now."""

    def __init__(self, per_minute: int, clock=time_mod.monotonic):
        self.per_minute, self._clock = per_minute, clock
        self._calls: collections.deque = collections.deque()
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            now = self._clock()
            while self._calls and self._calls[0] <= now - 60:
                self._calls.popleft()
            if len(self._calls) >= self.per_minute:
                return False
            self._calls.append(now)
            return True


# Finnhub's free plan allows 60 calls a minute; the app keeps 10 spare for the
# news box (news.py). Past the budget a stock is asked of Yahoo instead - what
# already happened whenever Finnhub said "too many", minus the wasted call.
FINNHUB_PER_MINUTE = 50
FINNHUB_BUDGET = Budget(FINNHUB_PER_MINUTE)


@contextmanager
def _using(db):
    """`db` is an open connection (used and left open - the caller's) or a
    function that opens one (opened here, closed straight after)."""
    if hasattr(db, "execute"):
        yield db
        return
    conn = db()
    try:
        yield conn
    finally:
        conn.close()


def _fetch_one(sym: str, k: str, finnhub, yahoo, budget: Budget):
    """(symbol, data, error, ok, source, fetched_at) for one ticker - network
    only, nothing written. Stocks from Finnhub while the budget allows, else
    (or when Finnhub has no price) from Yahoo; crypto and funds from Yahoo."""
    if k == "stock" and finnhub is not None and budget.take():
        data, err = finnhub(sym)
        if data and not err and data.get("c"):
            return sym, data, "", True, "finnhub", utc_now_iso()
    data, err = yahoo(sym)
    ok = bool(data) and not err and bool(data.get("c"))
    return sym, data, err, ok, "yahoo", utc_now_iso()


# Tickers a tab wanted while another tab was fetching ({ticker: kind}): the
# next tab to fetch takes up to ASKED_PER_ROUND of them (those still due) after
# its own, so a tab that keeps arriving mid-fetch isn't left behind.
_ASKED: dict = {}
_ASKED_LOCK = threading.Lock()
ASKED_PER_ROUND = 20
_UNSET = object()


def _as_of(latest) -> datetime | None:
    return max((t for _, t in latest.values() if t), default=None)


def _apply(conn, snap, user_id, latest, *, fetched_held: bool, applied) -> int:
    """Write the newest prices onto the account's positions when this tab
    fetched one of its holdings, or (`applied`: when the page's positions last
    got prices, None = never) when another tab stored a newer quote since."""
    if not snap:
        return 0
    if not fetched_held:
        as_of = _as_of(latest)
        last = _parse(applied) if applied is not _UNSET else None
        if applied is _UNSET or as_of is None or (last is not None and as_of <= last):
            return 0
    prices = {s: p for s, (p, _) in latest.items() if p}
    return apply_live_prices(conn, snap, user_id, prices, utc_now_iso()) if prices else 0


def freshen(db, user_id: int, finnhub_key: str | None, *, now: datetime | None = None,
            finnhub=None, yahoo=None, known=None, applied=_UNSET,
            budget: Budget | None = None) -> dict:
    """Fetch whatever quotes are due for this account's holdings and watchlist,
    and apply the newest known price of every holding to its positions.

    `db`: a function that opens a database connection (the app passes one), or
    an open connection. With a function no connection is held while quotes are
    fetched: one is opened to read what's due, closed, the quotes fetched, and
    another opened to write them - so a slow fetch never keeps a pooled
    connection from the pages.

    One tab fetches at a time in this process. A tab that finds another one
    fetching doesn't wait: it skips this minute's fetch, leaves its tickers for
    the next tab that fetches (_ASKED), and uses the prices already stored.
    Finnhub calls stay within `budget` (FINNHUB_BUDGET); past it, Yahoo.

    `finnhub(symbol)` and `yahoo(symbol)` return (data, error) and are for tests.
    `known`: (latest snapshot date, {held symbol: asset type}, [watched
    tickers]) when the caller has just read them (the dashboard's page run) -
    the same three reads done here otherwise. `applied`: the newest
    `live_price_at` of the page's positions (None if none) - given, a holding's
    quote that another tab stored since is applied too.

    Returns {"fetched": n, "updated": positions changed, "watch_fetched":
    watchlist tickers fetched, "as_of": newest quote time (UTC) of a holding or
    None, "live": whether anything updates on its own right now}."""
    now = now or datetime.now(timezone.utc)
    if finnhub is None and finnhub_key:
        def finnhub(s):
            return fetch_quote(s, finnhub_key, 8.0)
    yahoo = yahoo or yahoo_quote
    budget = budget or FINNHUB_BUDGET
    locked = False
    try:
        with _using(db) as conn:
            if known is not None:
                snap, held, watched = known
            else:
                snap = latest_snapshot(conn, user_id)
                held = {r["symbol"]: r["asset_type"] for r in conn.execute(
                    "SELECT DISTINCT symbol, asset_type FROM positions "
                    "WHERE snapshot_date = ? AND user_id = ?", (snap, user_id))} if snap else {}
                watched = [r["ticker"] for r in conn.execute(
                    "SELECT ticker FROM watchlist WHERE user_id = ?", (user_id,))]
            kinds = {s: kind(s, t) for s, t in held.items()}
            for w in watched:
                kinds.setdefault(w, kind(w, None))
            if not kinds:
                return {"fetched": 0, "updated": 0, "watch_fetched": 0, "as_of": None,
                        "live": False}
            todo, extra = [], []
            locked = _LOCK.acquire(blocking=False)
            if not locked:
                # another tab is fetching: don't wait for it - leave these for
                # the next fetch, and this minute uses what's stored
                with _ASKED_LOCK:
                    for s, k in kinds.items():
                        _ASKED.setdefault(s, k)
            else:
                with _ASKED_LOCK:
                    asked = {s: k for s, k in _ASKED.items() if s not in kinds}
                    _ASKED.clear()
                # inside the lock: another tab may have just fetched
                tried = _last_tried(conn, list(kinds) + list(asked))
                todo = [(s, k) for s, k in sorted(kinds.items()) if due(k, tried.get(s), now)]
                extra = [(s, k) for s, k in sorted(asked.items()) if due(k, tried.get(s), now)]
                if len(extra) > ASKED_PER_ROUND:
                    with _ASKED_LOCK:
                        for s, k in extra[ASKED_PER_ROUND:]:
                            _ASKED.setdefault(s, k)
                    extra = extra[:ASKED_PER_ROUND]
            if not todo and not extra:
                latest = _latest(conn, list(held))
                updated = _apply(conn, snap, user_id, latest, fetched_held=False, applied=applied)
                return _summary(0, updated, 0, latest, kinds, now)
        # the network part, with no database connection held (when `db` opens one)
        got = [_fetch_one(s, k, finnhub, yahoo, budget) for s, k in todo + extra]
        with _using(db) as conn:
            for sym, data, err, ok, source, at in got:
                _record_quote(conn, sym, data, err, ok, source=source, fetched_at=at, commit=False)
            conn.commit()
            _LOCK.release()   # written: the next tab to fetch sees these as done
            locked = False
            latest = _latest(conn, list(held))
            fetched = len(todo)                       # this tab's own; `extra` were others'
            watch_fetched = sum(s not in held for s, _ in todo)
            updated = _apply(conn, snap, user_id, latest,
                             fetched_held=fetched > watch_fetched, applied=applied)
        return _summary(fetched, updated, watch_fetched, latest, kinds, now)
    finally:
        if locked:
            _LOCK.release()


def _summary(fetched, updated, watch_fetched, latest, kinds, now) -> dict:
    return {"fetched": fetched, "updated": updated, "watch_fetched": watch_fetched,
            "as_of": _as_of(latest), "live": market_open(now) or "crypto" in kinds.values()}


# price_history gains a row per ticker per market minute; past this many days
# only each ticker's closing quote of the day is kept (trim_history).
KEEP_MINUTES_DAYS = 7


def trim_history(conn, *, keep_days: int = KEEP_MINUTES_DAYS, now: datetime | None = None) -> int:
    """Keep every quote from the last `keep_days` days; before that, only each
    ticker's last successful quote of each day (its close) - failed attempts and
    the rest of the minute-by-minute rows go. Run nightly (sync_history.py).
    Returns how many rows were deleted."""
    now = now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=keep_days)).strftime("%Y-%m-%d")
    # fetched_at is ISO ("2026-09-29T15:00:00Z", or with a space): its first 10
    # characters are the day, and it compares as text against a date
    cur = conn.execute(
        "DELETE FROM price_history WHERE fetched_at < ? AND (ok = 0 OR id NOT IN ("
        "  SELECT MAX(id) FROM price_history WHERE ok = 1 AND fetched_at < ?"
        "  GROUP BY ticker, substr(fetched_at, 1, 10)))", (cutoff, cutoff))
    conn.commit()
    return cur.rowcount or 0


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
