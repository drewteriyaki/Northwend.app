#!/usr/bin/env python3
"""Pull real price history from Yahoo Finance (via yfinance) into SQLite.

  1. reads the distinct tickers from the positions table
  2. downloads daily OHLCV for each (default: 2 years) and upserts `daily_bars`
  3. downloads intraday OHLCV at every resolution Yahoo allows and upserts
     `intraday_bars` - each resolution requested at Yahoo's own maximum
     look-back, so a 1D/5D chart has real minute-by-minute movement, not one
     point per day
  4. grabs a small bag of reference fundamentals into `security_info`, with
     the dates Yahoo's quote already carries (no extra request): the
     ex-dividend date, the dividend pay date and a confirmed earnings date -
     facts as Yahoo gives them, never worked out (see _event_dates)

This is the one part of the project with a third-party data dependency:

    pip install yfinance

`update_prices.py` (Finnhub, standard library only) still handles the fast
"current price" refresh; this fills in the deep history the charts and moving
averages need. Run:  python sync_history.py
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    _NY = ZoneInfo("America/New_York")
except Exception:   # pragma: no cover - no tz database: standard time all year
    _NY = timezone(timedelta(hours=-5))

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pgcompat  # noqa: E402
from portfolio import DEFAULT_DB, connect  # noqa: E402

try:
    import yfinance as yf
except ImportError:  # pragma: no cover - only hit when the dep is missing
    yf = None

DEFAULT_PERIOD = "2y"

# Intraday resolutions to fetch, each at the longest look-back Yahoo actually
# serves for that resolution (verified against the live endpoint; it silently
# returns nothing if a period exceeds what a resolution allows):
#   1m  -> ~8 days      5m/15m -> ~60 days      60m -> ~2 years
INTRADAY_SPECS = [
    ("1m", "7d"),
    ("5m", "60d"),
    ("15m", "60d"),
    ("60m", "2y"),
]

_INFO_KEYS = {
    "name": "shortName",
    "sector": "sector",
    "industry": "industry",
    "market_cap": "marketCap",
    "beta": "beta",
    "trailing_pe": "trailingPE",
    "forward_pe": "forwardPE",
    "price_to_book": "priceToBook",
    "dividend_yield": "dividendYield",
    "week52_high": "fiftyTwoWeekHigh",
    "week52_low": "fiftyTwoWeekLow",
    "avg_volume": "averageVolume",
    "avg_volume_10d": "averageVolume10days",
    "quote_type": "quoteType",   # EQUITY / ETF / MUTUALFUND / MONEYMARKET ... (asset_classes.py)
    "category": "category",      # a fund's category, e.g. "Intermediate Core Bond"
}
# A fund's split, from Ticker.funds_data.asset_classes (fractions). Preferred
# and convertible shares count as other.
_FUND_SPLIT_KEYS = {"stock_pct": ("stockPosition",), "bond_pct": ("bondPosition",),
                    "cash_pct": ("cashPosition",),
                    "other_pct": ("otherPosition", "preferredPosition", "convertiblePosition")}
_FUND_TYPES = ("ETF", "MUTUALFUND")
# A fund's yearly fee (fees.py), stored as a FRACTION (0.0003 = 0.03%). Yahoo
# gives it in mixed units (checked against VOO 0.03%, VTSAX 0.04%, FXAIX
# 0.015% in Oct 2026): info's netExpenseRatio is in PERCENT (VOO: 0.03), its
# annualReportExpenseRatio (mutual funds only) and funds_data.fund_operations'
# "Annual Report Expense Ratio" are fractions (VTSAX: 0.0004).
_MAX_EXPENSE_RATIO = 0.10   # 10% a year: anything above is a unit mix-up, not a fee


def _expense_ratio(raw: dict):
    """A fund's expense ratio as a fraction from Yahoo's info, or None. The
    net figure (after any fee waiver - what holders actually pay) first."""
    net = _num(raw.get("netExpenseRatio"))
    for v in ((net / 100) if net is not None else None, _num(raw.get("annualReportExpenseRatio"))):
        if v is not None and 0 <= v < _MAX_EXPENSE_RATIO:
            return v
    return None


# Dates from the same info reply (Yahoo's quote; no extra request), stored as
# ISO days. Yahoo gives unix seconds. Its dividendDate can be the LAST pay
# date, already past: stored as given (security_info.fetched_at is the day it
# was asked) - the app shows only dates that are today or later. An earnings
# date is kept only when Yahoo doesn't call it an estimate
# (isEarningsDateEstimate) and isn't giving a range of days (Start != End):
# facts only. Funds and ETFs get none of these from Yahoo (JEPQ, VTI: none,
# Oct 2026); dividend_dates.py asks Polygon for theirs.
EVENT_COLS = ("ex_dividend_date", "dividend_pay_date", "earnings_date")


def _when(v):
    """Unix seconds as an aware UTC datetime, or None."""
    n = _num(v)
    if n is None or n <= 0:
        return None
    try:
        return datetime.fromtimestamp(n, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _day_utc(v):
    """A unix-seconds date (Yahoo's dividend dates are midnight UTC) as
    'YYYY-MM-DD', or None."""
    when = _when(v)
    return when.date().isoformat() if when else None


def _day_ny(v):
    """A unix-seconds moment (an earnings call's time) as its New York day."""
    when = _when(v)
    return when.astimezone(_NY).date().isoformat() if when else None


def _event_dates(raw: dict) -> dict:
    """{ex_dividend_date, dividend_pay_date, earnings_date} from Yahoo's info
    (ISO days or None) - see EVENT_COLS above for what's kept."""
    earn = None
    if not raw.get("isEarningsDateEstimate"):
        start, end = raw.get("earningsTimestampStart"), raw.get("earningsTimestampEnd")
        if _day_ny(start) and _day_ny(end) and _day_ny(start) != _day_ny(end):
            earn = None   # a range of days: not settled yet
        else:
            earn = _day_ny(raw.get("earningsTimestamp")) or _day_ny(start)
    return {"ex_dividend_date": _day_utc(raw.get("exDividendDate")),
            "dividend_pay_date": _day_utc(raw.get("dividendDate")),
            "earnings_date": earn}


def _require_yf():
    if yf is None:
        raise SystemExit(
            "yfinance is not installed. Run:  pip install yfinance\n"
            "(or  pip install -r requirements.txt)"
        )


def portfolio_tickers(conn: sqlite3.Connection) -> list[str]:
    return [r["symbol"] for r in conn.execute(
        "SELECT DISTINCT symbol FROM positions ORDER BY symbol")]


def default_tickers(conn: sqlite3.Connection) -> list[str]:
    """Held positions + watchlist tickers, deduped - what a sync with no
    explicit `tickers` argument covers."""
    import watchlist
    return watchlist.all_sync_tickers(conn)


# --------------------------------------------------------------------------- #
# fetch
# --------------------------------------------------------------------------- #
def _num(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if v != v else v  # drop NaN


def fetch_bars(ticker: str, period: str = DEFAULT_PERIOD):
    """Return (rows, error). rows: list of dicts date/open/high/low/close/adj_close/volume."""
    _require_yf()
    try:
        df = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
    except Exception as exc:  # network, parse, rate limit, ...
        return [], f"{type(exc).__name__}: {exc}"
    if df is None or df.empty:
        return [], "no data returned"

    rows = []
    for idx, r in df.iterrows():
        rows.append({
            "date": idx.strftime("%Y-%m-%d"),
            "open": _num(r.get("Open")),
            "high": _num(r.get("High")),
            "low": _num(r.get("Low")),
            "close": _num(r.get("Close")),
            "adj_close": _num(r.get("Adj Close")),
            "volume": int(_num(r.get("Volume"))) if _num(r.get("Volume")) is not None else None,
            # Yahoo's daily history already carries each dividend (per share,
            # on its ex-date) - kept for the Income page's monthly estimate
            "dividend": _num(r.get("Dividends")) or 0.0,
        })
    return rows, ""


def fetch_intraday(ticker: str, interval: str, period: str):
    """Return (rows, error). rows: list of dicts ts/open/high/low/close/volume.
    `ts` is the bar's start time as an ISO-8601 UTC string."""
    _require_yf()
    try:
        df = yf.Ticker(ticker).history(period=period, interval=interval,
                                       auto_adjust=False, prepost=False)
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"
    if df is None or df.empty:
        return [], "no data returned"

    rows = []
    for idx, r in df.iterrows():
        ts = idx.tz_convert("UTC") if idx.tzinfo is not None else idx.tz_localize("UTC")
        rows.append({
            "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "open": _num(r.get("Open")),
            "high": _num(r.get("High")),
            "low": _num(r.get("Low")),
            "close": _num(r.get("Close")),
            "volume": int(_num(r.get("Volume"))) if _num(r.get("Volume")) is not None else None,
        })
    return rows, ""


def fetch_info(ticker: str) -> dict:
    _require_yf()
    try:
        raw = yf.Ticker(ticker).info or {}
    except Exception:
        return {}
    out = {}
    for col, key in _INFO_KEYS.items():
        v = raw.get(key)
        out[col] = v if v not in ("", "Infinity", "-Infinity") else None
    if raw and out.get("quote_type") is None:
        out["quote_type"] = ""  # asked, and Yahoo has no type for it (None = never asked)
    out.update(_event_dates(raw))
    fund = out.get("quote_type") in _FUND_TYPES
    out["expense_ratio"] = _expense_ratio(raw) if fund else None
    if not fund:
        out.update(dict.fromkeys(_FUND_SPLIT_KEYS))
        return out
    details = fetch_fund_split(ticker)
    # the same fund-details reply also has the yearly fee and, for a mutual
    # fund (whose info has no category), its category
    extra_ratio, extra_category = details.pop("_expense_ratio", None), details.pop("_category", None)
    out.update(details)
    if out["expense_ratio"] is None:
        out["expense_ratio"] = extra_ratio
    if not out.get("category") and extra_category:
        out["category"] = extra_category
    return out


def _fund_extras(fd) -> dict:
    """The expense ratio (a fraction) and category from a funds_data object
    whose reply is already in hand - no further request."""
    out = {"_expense_ratio": None, "_category": None}
    try:
        ops = fd.fund_operations
        v = _num(ops.loc["Annual Report Expense Ratio"].iloc[0])
        if v is not None and 0 <= v < _MAX_EXPENSE_RATIO:
            out["_expense_ratio"] = v
    except Exception:
        pass
    try:
        out["_category"] = (fd.fund_overview or {}).get("categoryName") or None
    except Exception:
        pass
    return out


def fetch_fund_split(ticker: str) -> dict:
    """{stock_pct, bond_pct, cash_pct, other_pct} as fractions for a fund -
    one extra Yahoo request, made only for ETFs and mutual funds. All None if
    Yahoo has no breakdown; that fund then falls back to its broker type.
    Also `_expense_ratio` / `_category` from the same reply (fetch_info
    takes them out)."""
    empty = dict.fromkeys(_FUND_SPLIT_KEYS)
    try:
        fd = yf.Ticker(ticker).funds_data
        raw = fd.asset_classes or {}
    except Exception:
        return empty   # nothing came back: don't ask again for the extras
    out = {}
    for col, keys in _FUND_SPLIT_KEYS.items():
        vals = [_num(raw.get(k)) for k in keys]
        vals = [v for v in vals if v is not None]
        out[col] = sum(vals) if vals else None
    return {**(out if any(v for v in out.values()) else empty), **_fund_extras(fd)}


# --------------------------------------------------------------------------- #
# store
# --------------------------------------------------------------------------- #
_BAR_COLS = ["ticker", "date", "open", "high", "low", "close", "adj_close", "volume", "dividend"]


def upsert_bars(conn: sqlite3.Connection, ticker: str, rows) -> int:
    conn.executemany(
        f"INSERT INTO daily_bars ({', '.join(_BAR_COLS)}, fetched_at) "
        f"VALUES ({', '.join('?' for _ in _BAR_COLS)}, datetime('now')) "
        "ON CONFLICT(ticker, date) DO UPDATE SET "
        "open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close, "
        "adj_close=excluded.adj_close, volume=excluded.volume, dividend=excluded.dividend, "
        "fetched_at=excluded.fetched_at",
        [tuple([ticker] + [r.get(c) for c in _BAR_COLS[1:]]) for r in rows],
    )
    return len(rows)


_INTRADAY_COLS = ["ticker", "interval", "ts", "open", "high", "low", "close", "volume"]


def upsert_intraday(conn: sqlite3.Connection, ticker: str, interval: str, rows) -> int:
    conn.executemany(
        f"INSERT INTO intraday_bars ({', '.join(_INTRADAY_COLS)}, fetched_at) "
        f"VALUES ({', '.join('?' for _ in _INTRADAY_COLS)}, datetime('now')) "
        "ON CONFLICT(ticker, interval, ts) DO UPDATE SET "
        "open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close, "
        "volume=excluded.volume, fetched_at=excluded.fetched_at",
        [(ticker, interval, r["ts"], r["open"], r["high"], r["low"], r["close"], r["volume"])
         for r in rows],
    )
    return len(rows)


def upsert_info(conn: sqlite3.Connection, ticker: str, info: dict) -> None:
    cols = (list(_INFO_KEYS.keys()) + list(_FUND_SPLIT_KEYS.keys()) + ["expense_ratio"]
            + list(EVENT_COLS))
    conn.execute(
        f"INSERT INTO security_info (ticker, {', '.join(cols)}, fetched_at) "
        f"VALUES (?, {', '.join('?' for _ in cols)}, datetime('now')) "
        "ON CONFLICT(ticker) DO UPDATE SET "
        + ", ".join(f"{c}=excluded.{c}" for c in cols)
        + ", fetched_at=excluded.fetched_at",
        tuple([ticker] + [info.get(c) for c in cols]),
    )


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
def sync(db_path: str, tickers=None, *, period: str = DEFAULT_PERIOD,
         with_info: bool = True, with_intraday: bool = True,
         delay: float = 0.3, on_progress=None) -> dict:
    """Sync `daily_bars`, `intraday_bars` (every resolution in INTRADAY_SPECS),
    and optionally `security_info`, for `tickers` (default: everything held
    plus everything on the watchlist). Returns a summary dict.
    `on_progress(i, n, ticker, n_rows_this_ticker, ok, err)` fires once per
    ticker, after all of that ticker's fetches."""
    _require_yf()
    conn = connect(db_path)
    try:
        tickers = list(tickers) if tickers else default_tickers(conn)
        results, bars_written, intraday_written, failed = [], 0, 0, []
        for i, tk in enumerate(tickers):
            rows, err = fetch_bars(tk, period)
            if rows:
                with conn:
                    upsert_bars(conn, tk, rows)
                bars_written += len(rows)

            if with_info:
                info = fetch_info(tk)
                if info:
                    with conn:
                        upsert_info(conn, tk, info)
                if delay:
                    time.sleep(delay)

            tk_intraday = 0
            if with_intraday:
                for interval, iperiod in INTRADAY_SPECS:
                    irows, ierr = fetch_intraday(tk, interval, iperiod)
                    if irows:
                        with conn:
                            upsert_intraday(conn, tk, interval, irows)
                        tk_intraday += len(irows)
                    if delay:
                        time.sleep(delay)
            intraday_written += tk_intraday

            total = len(rows) + tk_intraday
            if not total:
                failed.append(tk)
            results.append((tk, total, err or None))
            if on_progress:
                on_progress(i + 1, len(tickers), tk, total, bool(total), None if total else err)
        return {
            "tickers": len(tickers),
            "ok": len(tickers) - len(failed),
            "failed": failed,
            "bars_written": bars_written,
            "intraday_written": intraday_written,
            "results": results,
        }
    finally:
        conn.close()


def latest_bar_date(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT MAX(date) AS d FROM daily_bars").fetchone()
    return row["d"] if row else None


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Fetch daily price history from Yahoo Finance.")
    ap.add_argument("--db", default=DEFAULT_DB, help=f"SQLite file (default: {DEFAULT_DB})")
    ap.add_argument("--period", default=DEFAULT_PERIOD,
                    help="yfinance period: 1mo 3mo 6mo 1y 2y 5y max (default: 2y)")
    ap.add_argument("--tickers", nargs="*", help="tickers to sync (default: all in positions)")
    ap.add_argument("--no-info", action="store_true", help="skip the fundamentals fetch")
    ap.add_argument("--no-intraday", action="store_true",
                    help="skip intraday bars (1m/5m/15m/60m) - daily only, faster")
    ap.add_argument("--delay", type=float, default=0.3, help="seconds between each fetch")
    args = ap.parse_args(argv)

    _require_yf()
    if not pgcompat.is_postgres_dsn(args.db) and not os.path.isfile(args.db):
        raise SystemExit(f"No database at {os.path.abspath(args.db)} - import a CSV first.")

    intraday_note = "" if args.no_intraday else (
        " + intraday (" + ", ".join(i for i, _ in INTRADAY_SPECS) + ")")
    print(f"Syncing history from Yahoo (daily period={args.period}{intraday_note}):\n")

    def show(i, n, tk, nrows, ok, err):
        print(f"  {tk:<8} {nrows:>6,} rows" if ok else f"  {tk:<8} {'--':>6}         {err}")

    summary = sync(args.db, args.tickers, period=args.period, with_info=not args.no_info,
                   with_intraday=not args.no_intraday, delay=args.delay, on_progress=show)
    print(f"\n{summary['bars_written']:,} daily bars + "
          f"{summary['intraday_written']:,} intraday bars, "
          f"across {summary['ok']}/{summary['tickers']} tickers.")
    if summary["failed"]:
        print("No data at all for: " + ", ".join(summary["failed"]))
    # nightly housekeeping: the live price table keeps minute-by-minute quotes
    # for a week, then one closing quote per ticker per day (live_prices.py)
    import live_prices
    conn = connect(args.db)
    try:
        trimmed = live_prices.trim_history(conn)
    finally:
        conn.close()
    print(f"Trimmed {trimmed:,} old minute-by-minute quote(s) from price_history.")
    print("\nSee it in the dashboard:  streamlit run dashboard.py")
    return 0 if not summary["failed"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        # No-op unless a Postgres DSN was connected - see the identical
        # comment in update_prices.py.
        pgcompat.close_all_pools()
