"""When a price is from, in calm words, and "Price look wrong?" (PLAN G8).

As of (always on - it only describes the prices already shown): every price
the app shows comes from a stored quote, and each quote keeps the time it was
fetched (price_history.fetched_at, or positions.live_price_at once applied to
a holding - see live_prices.py and update_prices.py; nothing here changes how
prices are fetched). as_of() turns that time into words, in US Eastern time,
the market's own clock:

- a stock or ETF fetched while the market is open: "3:45 pm ET" (today) or
  "Oct 3, 3:45 pm ET";
- fetched while it's closed (evenings, weekends, before the open): the
  close it carries, "Oct 3 close";
- a mutual fund: priced once a day after the close, so the day it was
  checked, "Oct 3" - with a note that funds price once a day;
- crypto trades around the clock: always the time.

Each also says whether it's older than usual (`older`): a stock quote more
than OLD_OPEN old while the market is open, or not the latest close while it's
closed; crypto more than OLD_CRYPTO; a fund more than OLD_FUND. Market
holidays aren't counted (as in live_prices.market_open).

Report a wrong price (flag price_report): on a ticker's details, the person
picks one of REASONS - no free text - and a row goes in `price_reports`
(their login, the ticker, the reason key, the price shown and its time,
when). Kept with their account until it's deleted (admin.ACCOUNT_TABLES), in
their own export (export.OWN). Limits: one report per ticker a day, PER_DAY a
day in all, per login. Admins see counts only (admin_counts): ticker,
reason, how many, the latest price time - never who reported.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from live_prices import NY, last_close, market_open

OLD_OPEN = timedelta(minutes=30)
OLD_CRYPTO = timedelta(hours=1)
OLD_FUND = timedelta(days=4)

# reason key -> what the person taps. Fixed: nothing typed is ever kept.
REASONS = {
    "too_high": "It looks too high",
    "too_low": "It looks too low",
    "old": "It looks out of date",
    "wrong_fund": "It looks like a different fund or company",
}
PER_DAY = 5   # reports a day per login, across all tickers (and one per ticker a day)
ADMIN_ROWS = 50

THANKS = ("Thank you - we've noted it. Prices come from outside data companies, and "
          "notes like this help us check prices that look wrong.")
SAME_TICKER = "Thank you - you've already told us about this price today."
TOO_MANY = "Thank you - that's all the notes we can take today. You can send more tomorrow."


def _when(ts) -> datetime | None:
    if ts is None or ts == "":
        return None
    if isinstance(ts, datetime):
        at = ts
    else:
        try:
            at = datetime.fromisoformat(str(ts).strip().replace("Z", "+00:00").replace(" ", "T"))
        except ValueError:
            return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def kind(symbol: str, asset_type: str | None = None, quote_type: str | None = None) -> str:
    """'crypto', 'fund' (a mutual fund) or 'stock' (stocks, ETFs and the rest):
    the broker's type, else Yahoo's (security_info.quote_type)."""
    q = (quote_type or "").upper()
    if (symbol or "").upper().endswith("-USD") or asset_type == "Crypto" or q == "CRYPTOCURRENCY":
        return "crypto"
    if asset_type == "Mutual Funds" or q == "MUTUALFUND":
        return "fund"
    return "stock"


def _day(d) -> str:
    return f"{d:%b} {d.day}"


def _clock(at: datetime) -> str:
    return at.strftime("%I:%M %p").lstrip("0").lower() + " ET"


def as_of(ts, k: str = "stock", now: datetime | None = None) -> dict | None:
    """{"text", "close", "older"} for a price stored at `ts` (ISO text or a
    datetime, UTC), or None without a time. "text" follows "as of": "3:45 pm
    ET", "Oct 3, 3:45 pm ET", "Oct 3 close" or, for a fund, "Oct 3"."""
    at = _when(ts)
    if at is None:
        return None
    now = now or datetime.now(timezone.utc)
    ny, ny_now = at.astimezone(NY), now.astimezone(NY)
    if k == "fund":
        return {"text": _day(ny), "close": True, "older": now - at > OLD_FUND}
    if k == "crypto" or market_open(at):
        text = _clock(ny) if ny.date() == ny_now.date() else f"{_day(ny)}, {_clock(ny)}"
        if k == "crypto":
            older = now - at > OLD_CRYPTO
        else:
            older = (now - at > OLD_OPEN) if market_open(now) else at < last_close(now)
        return {"text": text, "close": False, "older": older}
    closed = last_close(at)
    older = (now - at > OLD_OPEN) if market_open(now) else closed < last_close(now)
    return {"text": f"{_day(closed.astimezone(NY))} close", "close": True, "older": older}


def as_of_line(ts, k: str = "stock", now: datetime | None = None) -> str:
    """The words under one price: "As of 3:45 pm ET · may be delayed" (the
    source can lag - dashboard.PRICE_SOURCE), with a calm note when the price
    is older than usual or a fund's. "" without a time."""
    a = as_of(ts, k, now)
    if a is None:
        return ""
    extra = ""
    if k == "fund":
        extra = " · funds are priced once a day, after the market closes"
    elif a["older"]:
        extra = " · older than usual, the newest price we have"
    return f"As of {a['text']}{extra} · may be delayed"


# --------------------------------------------------------------------------- #
# reports
# --------------------------------------------------------------------------- #
def _day_start(now: datetime) -> str:
    n = now.astimezone(timezone.utc)
    return _iso(datetime(n.year, n.month, n.day, tzinfo=timezone.utc))


def can_report(conn, login_id: int, ticker: str, *, now: datetime | None = None) -> str | None:
    """None when this login may report `ticker` now, else the calm line to
    show instead (already told us today; the day's limit reached)."""
    now = now or datetime.now(timezone.utc)
    rows = conn.execute("SELECT ticker FROM price_reports WHERE user_id = ? AND created_at >= ?",
                        (login_id, _day_start(now))).fetchall()
    if any(r["ticker"] == ticker.upper() for r in rows):
        return SAME_TICKER
    if len(rows) >= PER_DAY:
        return TOO_MANY
    return None


def report(conn, login_id: int, ticker: str, reason: str, *, price=None, price_as_of=None,
           now: datetime | None = None) -> dict:
    """Save one report. {"ok", "message"}: ok False (nothing saved) for an
    unknown reason or past a limit - each with a calm message."""
    ticker = (ticker or "").strip().upper()
    if reason not in REASONS or not ticker or len(ticker) > 20:
        return {"ok": False, "message": "Pick one of the reasons first."}
    now = now or datetime.now(timezone.utc)
    stop = can_report(conn, login_id, ticker, now=now)
    if stop:
        return {"ok": False, "message": stop}
    shown_at = _when(price_as_of)
    try:
        shown = round(float(price), 6) if price is not None else None
    except (TypeError, ValueError):
        shown = None
    conn.execute("INSERT INTO price_reports (user_id, ticker, reason, shown_price, "
                 "price_as_of, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                 (login_id, ticker, reason, shown, _iso(shown_at) if shown_at else None,
                  _iso(now)))
    conn.commit()
    return {"ok": True, "message": THANKS}


def admin_counts(conn, limit: int = ADMIN_ROWS) -> list[dict]:
    """Reports by ticker and reason, most first: how many, the latest price
    time reported and the latest report - never who."""
    return [dict(r) for r in conn.execute(
        "SELECT ticker, reason, COUNT(*) AS n, MAX(price_as_of) AS latest_as_of, "
        "MAX(created_at) AS latest FROM price_reports GROUP BY ticker, reason "
        "ORDER BY n DESC, latest DESC LIMIT ?", (int(limit),))]
