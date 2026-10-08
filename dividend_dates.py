"""Upcoming dividend dates, as announced - never estimated.

Two sources, both kept as facts with where they came from:

1. Yahoo, already asked each night (sync_history.fetch_info - no extra
   request): a stock's ex-dividend date, pay date and a confirmed earnings
   date, in security_info. Funds and ETFs get none of these from Yahoo.
2. Polygon (now also called Massive) - the reference dividends endpoint,
   for stocks and funds alike:

       GET {DIVIDEND_API_BASE}/v3/reference/dividends
           ?ticker=VTI&order=desc&sort=ex_dividend_date&limit=12
       Authorization: Bearer <POLYGON_API_KEY>

   Fields read from each result: ticker, ex_dividend_date, pay_date,
   declaration_date, record_date, cash_amount, currency. The key goes in the
   header, never in the address. Only ticker symbols are sent.

The nightly job (`python dividend_dates.py --db ...`, its own job in
.github/workflows/scheduled-sync.yml): every ticker any account holds (its
latest snapshot) or watches, the ones asked longest ago first, skipping any
asked in the last FRESH_DAYS days, at most MAX_PER_RUN a night, PACE seconds
apart (the free plan allows about 5 calls a minute). STOP_AFTER "too many
requests" / "not allowed" replies in a row end the run - the next night
carries on where it left off. The run fails (and the admin hears) only when
every call it made failed. Without POLYGON_API_KEY (or MASSIVE_API_KEY) it
makes no calls at all and says so in one line.

The pages read one query (upcoming) for the account's own tickers, and
`merged` puts the three sources together: an announced date first, Yahoo's
for the same ticker and kind only when no announced one is kept, the
brokerage file's pay date as before. Only dates from today on are shown.

Stored in dividend_events: shared market data, no user_id, like
fund_top_holdings. A row with ex_date '' records when a ticker was last asked
(many pay no dividends). prune() (tidy.py, nightly) drops what's older than
KEEP_DAYS.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

import settings

DEFAULT_BASE = "https://api.polygon.io"
BASE_SETTING = "DIVIDEND_API_BASE"           # another address for the same API (Massive's)
KEY_NAMES = ("POLYGON_API_KEY", "MASSIVE_API_KEY")
PATH = "/v3/reference/dividends"
PAGE_SIZE = 12          # the newest dividends per ticker: what's announced and the last ones
PACE = 12.5             # seconds between calls: under the free plan's 5 a minute
MAX_PER_RUN = 200       # tickers a night at most (about 42 minutes)
FRESH_DAYS = 3          # a ticker asked this recently isn't asked again
STOP_AFTER = 2          # this many 429 / 403 replies in a row end the run
KEEP_DAYS = 730         # about two years of dividends kept
ASKED_KEEP_DAYS = 30    # a "when it was asked" row for a ticker nobody asks about any more
TIMEOUT = 20
SOURCE = "polygon"

# where a date came from, in words (the pages)
ANNOUNCED, YAHOO, BROKER = "announced", "yahoo", "broker"
SOURCE_WORDS = {ANNOUNCED: "Announced by the company or fund",
                YAHOO: "From Yahoo Finance",
                BROKER: "From your brokerage's file"}
PAY, EX, EARNINGS = "pay", "ex", "earnings"
NONE_YET = "No upcoming date announced yet"

# 5-letter symbols ending in X are mutual funds; Polygon's stock data has none
_MUTUAL_FUND = re.compile(r"^[A-Z]{4}X$")
_TICKER = re.compile(r"^[A-Z][A-Z0-9]{0,5}(?:[.\-/][A-Z0-9]{1,4})?$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------- #
# settings
# --------------------------------------------------------------------------- #
def api_key() -> str:
    """The Polygon / Massive key, or "" (then nothing is fetched)."""
    return (settings.get("POLYGON_API_KEY", env_file=True)
            or settings.get("MASSIVE_API_KEY", env_file=True))


def base_url() -> str:
    return (settings.get("DIVIDEND_API_BASE") or DEFAULT_BASE).rstrip("/")


# --------------------------------------------------------------------------- #
# Polygon: fetch and parse
# --------------------------------------------------------------------------- #
def wanted(symbol) -> bool:
    """A symbol worth asking about: a ticker, not a mutual fund or crypto pair."""
    s = str(symbol or "").strip().upper()
    return bool(_TICKER.match(s)) and not _MUTUAL_FUND.match(s) and not s.endswith("-USD")


def query_symbol(symbol: str) -> str:
    """Polygon writes share classes with a dot (BRK.B); files and Yahoo
    sometimes use '-' or '/'."""
    return re.sub(r"[-/]", ".", symbol.strip().upper())


def request_url(symbol: str, base: str | None = None) -> str:
    q = urllib.parse.urlencode({"ticker": query_symbol(symbol), "order": "desc",
                                "sort": "ex_dividend_date", "limit": PAGE_SIZE})
    return f"{(base or base_url()).rstrip('/')}{PATH}?{q}"


def http_get(url: str, key: str) -> tuple[int, dict | None]:
    """(HTTP status, JSON body or None). 0 when nothing came back at all."""
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}",
                                               "Accept": "application/json",
                                               "User-Agent": "Northwend dividend dates"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, OSError, ValueError):
        return 0, None


def _day(v) -> str | None:
    s = str(v or "").strip()[:10]
    if not _DAY.match(s):
        return None
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        return None


def _amount(v, currency) -> float | None:
    if currency and str(currency).upper() != "USD":
        return None    # the dates still count; an amount in another currency isn't shown
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if 0 < n < 1e6 else None


def parse(payload, symbol: str) -> list[dict]:
    """The dividends in one reply, for `symbol` (as held): each {ex_date,
    pay_date, declared_date, record_date, amount}. A result for another
    ticker, or without a valid ex-dividend date, is left out."""
    want = query_symbol(symbol)
    out, seen = [], set()
    for r in (payload or {}).get("results") or []:
        if not isinstance(r, dict):
            continue
        if r.get("ticker") and query_symbol(str(r["ticker"])) != want:
            continue
        ex = _day(r.get("ex_dividend_date"))
        if not ex or ex in seen:
            continue
        seen.add(ex)
        out.append({"ex_date": ex, "pay_date": _day(r.get("pay_date")),
                    "declared_date": _day(r.get("declaration_date")),
                    "record_date": _day(r.get("record_date")),
                    "amount": _amount(r.get("cash_amount"), r.get("currency"))})
    return out


# --------------------------------------------------------------------------- #
# store
# --------------------------------------------------------------------------- #
def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def store(conn, symbol: str, rows, *, now: datetime | None = None) -> int:
    """Keep one ticker's reply: its upcoming rows are replaced by what was
    just announced (a moved or withdrawn date doesn't linger), past ones
    are updated, and the "asked" row is set. Commits."""
    now = now or datetime.now(timezone.utc)
    sym, stamp, today = symbol.strip().upper(), _iso(now), now.date().isoformat()
    oldest = (now.date() - timedelta(days=KEEP_DAYS)).isoformat()
    rows = [r for r in rows if r["ex_date"] >= oldest]
    conn.execute("DELETE FROM dividend_events WHERE ticker = ? AND ex_date >= ?", (sym, today))
    conn.executemany(
        "INSERT INTO dividend_events (ticker, ex_date, pay_date, declared_date, record_date, "
        "amount, source, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(ticker, ex_date) DO UPDATE SET pay_date=excluded.pay_date, "
        "declared_date=excluded.declared_date, record_date=excluded.record_date, "
        "amount=excluded.amount, source=excluded.source, fetched_at=excluded.fetched_at",
        [(sym, r["ex_date"], r["pay_date"], r["declared_date"], r["record_date"], r["amount"],
          SOURCE, stamp) for r in rows]
        + [(sym, "", None, None, None, None, SOURCE, stamp)])
    conn.commit()
    return len(rows)


def prune(conn, *, now: datetime | None = None) -> int:
    """Delete dividends whose ex-dividend and pay dates are both more than
    KEEP_DAYS ago, and "asked" rows untouched for ASKED_KEEP_DAYS. No commit
    (tidy.run commits)."""
    now = now or datetime.now(timezone.utc)
    cut = (now.date() - timedelta(days=KEEP_DAYS)).isoformat()
    cur = conn.execute("DELETE FROM dividend_events WHERE ex_date <> '' AND ex_date < ? "
                       "AND (pay_date IS NULL OR pay_date < ?)", (cut, cut))
    gone = max(cur.rowcount or 0, 0)
    cur = conn.execute("DELETE FROM dividend_events WHERE ex_date = '' AND fetched_at < ?",
                       (_iso(now - timedelta(days=ASKED_KEEP_DAYS)),))
    return gone + max(cur.rowcount or 0, 0)


# --------------------------------------------------------------------------- #
# the nightly job
# --------------------------------------------------------------------------- #
def tickers_to_fetch(conn, *, now: datetime | None = None) -> tuple[list[str], int]:
    """(tickers to ask tonight, how many were skipped as asked recently):
    every ticker any account holds in its latest snapshot or watches, the
    never-asked first, then the longest ago."""
    now = now or datetime.now(timezone.utc)
    held = conn.execute(
        "SELECT DISTINCT p.symbol AS t FROM positions p JOIN "
        "(SELECT user_id, MAX(snapshot_date) AS d FROM positions "
        " WHERE user_id IS NOT NULL GROUP BY user_id) l "
        "ON p.user_id = l.user_id AND p.snapshot_date = l.d").fetchall()
    watched = conn.execute("SELECT DISTINCT ticker AS t FROM watchlist").fetchall()
    symbols = {str(r["t"]).strip().upper() for r in [*held, *watched] if r["t"]}
    symbols = {s for s in symbols if wanted(s)}
    asked = {r["ticker"]: r["fetched_at"] or "" for r in conn.execute(
        "SELECT ticker, fetched_at FROM dividend_events WHERE ex_date = ''")}
    fresh = _iso(now - timedelta(days=FRESH_DAYS))
    due = [s for s in symbols if asked.get(s, "") < fresh]
    return sorted(due, key=lambda s: (asked.get(s, ""), s)), len(symbols) - len(due)


def sync_all(conn, key: str, *, base: str | None = None, pace: float = PACE,
             max_tickers: int = MAX_PER_RUN, get=None, sleep=time.sleep,
             now: datetime | None = None, log=print) -> dict:
    """Ask Polygon about each due ticker (tickers_to_fetch), `pace` seconds
    apart. `get(url, key)` -> (status, body): http_get unless a test passes
    its own. Returns {tickers, asked, ok, failed, skipped, stored, stopped}."""
    get = get or http_get
    base = base or base_url()
    todo, recent = tickers_to_fetch(conn, now=now)
    summary = {"tickers": len(todo) + recent, "asked": 0, "ok": 0, "failed": 0,
               "skipped": recent + max(0, len(todo) - max_tickers), "stored": 0,
               "stopped": False}
    refused = 0
    for sym in todo[:max_tickers]:
        if summary["asked"]:
            sleep(pace)
        summary["asked"] += 1
        status, body = get(request_url(sym, base), key)
        if status == 200 and isinstance(body, dict):
            refused = 0
            summary["ok"] += 1
            summary["stored"] += store(conn, sym, parse(body, sym), now=now)
            continue
        summary["failed"] += 1
        log(f"  {sym:<8} HTTP {status or 'no reply'}")
        refused = refused + 1 if status in (403, 429) else 0
        if refused >= STOP_AFTER:
            summary["stopped"] = True
            log("  The dividend data service is refusing or limiting requests - stopping; "
                "the next run carries on.")
            break
    return summary


def main(argv=None) -> int:
    import pgcompat
    from portfolio import connect

    ap = argparse.ArgumentParser(description="Store announced dividend dates (Polygon) for "
                                             "every held or watched ticker.")
    ap.add_argument("--db", default=settings.get("DATABASE_URL") or settings.get("PORTFOLIO_DB")
                    or "portfolio.db")
    ap.add_argument("--pace", type=float, default=PACE,
                    help=f"seconds between calls (default {PACE}: the free plan allows 5 a minute)")
    ap.add_argument("--max", type=int, default=MAX_PER_RUN, help="tickers a run at most")
    args = ap.parse_args(argv)
    key = api_key()
    if not key:
        print("Dividend dates: no POLYGON_API_KEY set - nothing fetched. Yahoo's dates "
              "(from the history sync) still show.")
        return 0
    if not pgcompat.is_postgres_dsn(args.db) and not os.path.isfile(args.db):
        raise SystemExit(f"No database at {args.db}")
    conn = connect(args.db)
    try:
        s = sync_all(conn, key, pace=args.pace, max_tickers=args.max)
    finally:
        conn.close()
    print(f"Dividend dates: {s['tickers']} ticker(s), {s['asked']} asked, {s['ok']} answered, "
          f"{s['failed']} failed, {s['skipped']} left for later, {s['stored']} dividend(s) kept"
          + (" - stopped early." if s["stopped"] else "."))
    return 1 if s["asked"] and not s["ok"] else 0


# --------------------------------------------------------------------------- #
# for the pages
# --------------------------------------------------------------------------- #
def today() -> date:
    """Today on the US market's clock (New York): what "upcoming" counts from."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York")).date()
    except Exception:   # pragma: no cover - no tz database
        return (datetime.now(timezone.utc) - timedelta(hours=5)).date()


def upcoming(conn, tickers, today: date) -> list[dict]:
    """The kept dividends of `tickers` whose ex-dividend or pay date is today
    or later - one query, nothing fetched."""
    syms = sorted({str(t).strip().upper() for t in tickers or () if t})
    if not syms:
        return []
    day = today.isoformat()
    marks = ", ".join("?" for _ in syms)
    rows = conn.execute(
        "SELECT ticker, ex_date, pay_date, amount FROM dividend_events "
        f"WHERE ticker IN ({marks}) AND ex_date <> '' AND (ex_date >= ? OR pay_date >= ?) "
        "ORDER BY ticker, ex_date LIMIT 500", (*syms, day, day)).fetchall()
    return [dict(r) for r in rows]


def _as_day(v) -> date | None:
    s = _day(v)
    return date.fromisoformat(s) if s else None


def merged(events, info, positions, *, start: date, end: date, tickers=None,
           earnings: bool = True) -> list[dict]:
    """Every known date from `start` to `end` (both included), facts only:
    [{"day", "ticker", "kind": pay | ex | earnings, "amount", "source"}],
    by day, then ticker, then kind.

    events: upcoming()'s rows (announced). info: {ticker: security_info row}
    (Yahoo's dates). positions: the holdings, whose div_pay_date /
    next_earnings_date cells are the brokerage file's own. tickers: limit to
    these (default: every ticker in the three). For a ticker and kind, an
    announced date from `start` on is used if one is kept; Yahoo's only
    otherwise. The
    brokerage file's date is listed unless the same date is already there."""
    keep = {str(t).upper() for t in tickers} if tickers is not None else None
    found: dict[tuple, dict] = {}
    announced: set[tuple] = set()

    def add(day, ticker, kind, source, amount=None):
        if day is None or not (start <= day <= end) or not ticker:
            return
        t = str(ticker).upper()
        if keep is not None and t not in keep:
            return
        found.setdefault((day, t, kind), {"day": day, "ticker": t, "kind": kind,
                                          "amount": amount, "source": source})

    for e in events or ():
        t = str(e.get("ticker") or "").upper()
        for kind, field in ((EX, "ex_date"), (PAY, "pay_date")):
            d = _as_day(e.get(field))
            if d is not None and d >= start:
                announced.add((t, kind))
                add(d, t, kind, ANNOUNCED, e.get("amount"))
    for t, row in (info or {}).items():
        t = str(t).upper()
        row = row or {}
        for kind, field in ((EX, "ex_dividend_date"), (PAY, "dividend_pay_date"),
                            (EARNINGS, "earnings_date")):
            if kind == EARNINGS and not earnings:
                continue
            if (t, kind) not in announced:
                add(_as_day(row.get(field)), t, kind, YAHOO)
    import weekly   # its parse_day reads a brokerage file's cell
    for p in positions or ():
        for field, kind in (("div_pay_date", PAY), ("next_earnings_date", EARNINGS)):
            if kind == EARNINGS and not earnings:
                continue
            add(weekly.parse_day(p.get(field)), p.get("symbol"), kind, BROKER)
    order = {EX: 0, PAY: 1, EARNINGS: 2}
    return sorted(found.values(), key=lambda r: (r["day"], r["ticker"], order[r["kind"]]))


def next_for(events, info_row, ticker: str, today: date) -> dict:
    """One ticker's next dates from today on (its page): {"ex", "pay",
    "amount", "source", "earnings", "earnings_source"} - None where nothing
    is announced. An announced dividend first, else Yahoo's dates."""
    t = ticker.upper()
    out = {"ex": None, "pay": None, "amount": None, "source": None, "earnings": None,
           "earnings_source": None}
    mine = sorted((e for e in events or () if str(e.get("ticker") or "").upper() == t),
                  key=lambda e: e.get("ex_date") or "")
    for e in mine:
        ex, pay = _as_day(e.get("ex_date")), _as_day(e.get("pay_date"))
        if (ex and ex >= today) or (pay and pay >= today):
            out.update(ex=ex if ex and ex >= today else None,
                       pay=pay if pay and pay >= today else None,
                       amount=e.get("amount"), source=ANNOUNCED)
            break
    row = info_row or {}
    if out["source"] is None:
        ex, pay = _as_day(row.get("ex_dividend_date")), _as_day(row.get("dividend_pay_date"))
        ex = ex if ex and ex >= today else None
        pay = pay if pay and pay >= today else None
        if ex or pay:
            out.update(ex=ex, pay=pay, source=YAHOO)
    earn = _as_day(row.get("earnings_date"))
    if earn and earn >= today:
        out.update(earnings=earn, earnings_source=YAHOO)
    return out


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    finally:
        try:
            import pgcompat
            pgcompat.close_all_pools()
        except Exception:
            pass
