"""Your news (flag `news_feed`): headlines about what a person holds or
watches, from the `news` table that news.py fills from Finnhub.

Two parts, both without Streamlit:

1. The background job (`python news_feed.py --db ...`, its own job in
   .github/workflows/scheduled-sync.yml, hourly): the tickers every account
   holds (each account's latest snapshot) or watches, each fetched once with a
   pause between calls (Finnhub's free plan allows 60 a minute, shared with the
   price updates), the oldest-fetched first, at most MAX_PER_RUN a run. It does
   nothing while the flag is off. Pages never wait on Finnhub for the feed:
   they read only what this job stored (ticker detail still fetches its own
   ticker when it's opened, as before).

2. The selection (`pick`, pure): which stories to show. In plain words:
   - only the last RECENT_DAYS days;
   - press-release wires (Business Wire, GlobeNewswire, PR Newswire and the
     like) and law-firm "investor alert" notices are left out, as are
     headlines of fewer than four words and links that aren't web pages;
   - the same story told twice - the same link, or for the same ticker a
     headline sharing most of its words with another - is shown once, with
     how many sources had it;
   - newest first, a story covered by more sources moving up a little
     (BOOST_HOURS per extra source, up to two extra);
   - at most PER_TICKER stories per ticker and LIMIT in all.
   Nothing is ranked by what it might mean for buying or selling.

What's shown is the headline, the source, how long ago and a link to the
source - never Finnhub's summary or article text, and never the person's
figures. Only ticker symbols go to Finnhub.
"""

from __future__ import annotations

import argparse
import os
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import news

# ---- the selection's rules ------------------------------------------------ #
RECENT_DAYS = 3        # how far back a story can be
PER_TICKER = 2         # stories per ticker at most
LIMIT = 10             # stories in all (the News tab)
HOME_LIMIT = 4         # on Home's card
BOOST_HOURS = 6        # each extra source moves a story up this much ...
BOOST_MAX_SOURCES = 3  # ... counting up to this many sources
SAME_STORY = 0.6       # share of headline words in common that makes it the same story

# Press-release wires: a company's own announcement, sent out as it is.
PRESS_WIRES = ("business wire", "businesswire", "globenewswire", "globe newswire",
               "pr newswire", "prnewswire", "accesswire", "access newswire", "newsfile",
               "einpresswire", "ein presswire", "newswire")
PRESS_WIRE_SITES = ("businesswire.com", "globenewswire.com", "prnewswire.com",
                    "accesswire.com", "newsfilecorp.com", "einpresswire.com",
                    "einnews.com")
# Law-firm notices looking for clients ("SHAREHOLDER ALERT: ... class action").
JUNK_WORDS = ("class action", "shareholder alert", "investor alert", "investors who lost",
              "lead plaintiff", "deadline reminder", "law firm", "securities fraud",
              "investigation on behalf", "encourages investors")

# Words that say little about which story it is.
_STOP = {"a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "at", "by", "with",
         "as", "is", "are", "its", "it", "from", "after", "over", "into", "this", "that",
         "be", "was", "has", "have", "new", "says", "say", "stock", "stocks", "shares"}

# ---- the job's rules ------------------------------------------------------ #
DELAY = 1.5           # seconds between calls: at most 40 a minute, leaving room for prices
MAX_PER_RUN = 250     # tickers a run at most (about 6 minutes)
FRESH_MINUTES = 45    # a ticker with a new story stored this recently isn't fetched again
KEEP_DAYS = 30        # stories older than this are deleted at the end of a run
RATE_LIMITED_STOP = 3 # this many "too many requests" in a row ends the run

# 5-letter symbols ending in X are mutual funds: Finnhub has no company news for them.
_FUND = re.compile(r"^[A-Z]{4}X$")
_TICKER = re.compile(r"^[A-Z][A-Z0-9]{0,5}(?:[.\-][A-Z0-9]{1,4})?$")


# --------------------------------------------------------------------------- #
# The selection
# --------------------------------------------------------------------------- #
def _when(published) -> datetime | None:
    if not published:
        return None
    try:
        return datetime.strptime(str(published)[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=timezone.utc)
    except ValueError:
        return None


def _site(url: str) -> str:
    host = urlsplit(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def same_link(url: str) -> str:
    """A link without its query, fragment, trailing slash or www., for comparing."""
    parts = urlsplit((url or "").strip())
    return (_site(url) + parts.path.rstrip("/")).lower()


def headline_words(headline: str) -> set[str]:
    """The words of a headline that tell stories apart, lower case."""
    words = re.findall(r"[a-z0-9]+", (headline or "").lower().replace("'", ""))
    return {w for w in words if w not in _STOP}


def is_junk(article: dict) -> bool:
    """Left out: a press-release wire, a law-firm notice, a headline of fewer
    than four words, or a link that isn't a web page."""
    headline = (article.get("headline") or "").strip()
    url = (article.get("url") or "").strip()
    source = (article.get("source") or "").strip().lower()
    if len(headline.split()) < 4 or not url.lower().startswith(("http://", "https://")):
        return True
    if any(w in source for w in PRESS_WIRES):
        return True
    site = _site(url)
    if any(site == s or site.endswith("." + s) for s in PRESS_WIRE_SITES):
        return True
    low = headline.lower()
    return any(w in low for w in JUNK_WORDS)


def _similar(a: set[str], b: set[str]) -> bool:
    if len(a) < 3 or len(b) < 3:
        return False
    return len(a & b) / len(a | b) >= SAME_STORY


def stories(articles, *, now: datetime | None = None,
            days: int = RECENT_DAYS) -> list[dict]:
    """Group articles into stories: recent, junk left out, the same story told
    twice put together. Each: {headline, url, source, published_at, when,
    tickers, sources (how many), score}, newest (plus boost) first."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    rows = []
    for a in articles:
        when = _when(a.get("published_at"))
        if when is None or when < since or when > now + timedelta(hours=1) or is_junk(a):
            continue
        rows.append((when, a))
    rows.sort(key=lambda r: r[0], reverse=True)
    groups: list[dict] = []
    for when, a in rows:
        link, words = same_link(a["url"]), headline_words(a["headline"])
        ticker = (a.get("ticker") or "").upper()
        for g in groups:
            # the same link is the same story under any ticker; similar words
            # only under the same one ("X rises after earnings" isn't Y's story)
            if link in g["_links"] or (ticker in g["tickers"]
                                       and any(_similar(words, w) for w in g["_words"])):
                g["_links"].add(link)
                g["_words"].append(words)
                g["_sources"].add((a.get("source") or _site(a["url"])).strip().lower())
                if ticker and ticker not in g["tickers"]:
                    g["tickers"].append(ticker)
                break
        else:
            groups.append({"headline": a["headline"].strip(), "url": a["url"].strip(),
                           "source": (a.get("source") or _site(a["url"])).strip(),
                           "published_at": a["published_at"], "when": when,
                           "tickers": [ticker] if ticker else [],
                           "_links": {link}, "_words": [words],
                           "_sources": {(a.get("source") or _site(a["url"])).strip().lower()}})
    out = []
    for g in groups:
        n = len(g["_sources"])
        extra = min(n, BOOST_MAX_SOURCES) - 1
        score = g["when"].timestamp() + extra * BOOST_HOURS * 3600
        out.append({k: v for k, v in g.items() if not k.startswith("_")}
                   | {"sources": n, "score": score})
    out.sort(key=lambda s: s["score"], reverse=True)
    return out


def pick(articles, *, now: datetime | None = None, per_ticker: int = PER_TICKER,
         limit: int = LIMIT, days: int = RECENT_DAYS) -> list[dict]:
    """The stories to show (see the module's docstring for the rule in plain
    words). A story under several tickers counts toward each of them."""
    taken, count = [], {}
    for s in stories(articles, now=now, days=days):
        if any(count.get(t, 0) >= per_ticker for t in s["tickers"]):
            continue
        for t in s["tickers"]:
            count[t] = count.get(t, 0) + 1
        taken.append(s)
        if len(taken) >= limit:
            break
    return taken


def ago(when: datetime, now: datetime | None = None) -> str:
    """How long ago, in words: "just now", "25 minutes ago", "3 hours ago",
    "yesterday", "2 days ago"."""
    now = now or datetime.now(timezone.utc)
    secs = max(0, (now - when).total_seconds())
    if secs < 120:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)} minutes ago"
    if secs < 7200:
        return "1 hour ago"
    if secs < 86400:
        return f"{int(secs // 3600)} hours ago"
    days = int(secs // 86400)
    return "yesterday" if days == 1 else f"{days} days ago"


def load(conn, tickers, *, now: datetime | None = None, days: int = RECENT_DAYS) -> list[dict]:
    """The stored articles for these tickers from the last `days` days - one
    query, nothing fetched. Pass the rows to pick()."""
    tickers = sorted({str(t).upper() for t in tickers if t})
    if not tickers:
        return []
    since = ((now or datetime.now(timezone.utc)) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    marks = ", ".join("?" for _ in tickers)
    rows = conn.execute(
        "SELECT ticker, headline, source, url, published_at FROM news "
        f"WHERE ticker IN ({marks}) AND published_at >= ? "
        "ORDER BY published_at DESC LIMIT 2000", (*tickers, since)).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# The job
# --------------------------------------------------------------------------- #
def wanted(symbol: str) -> bool:
    """A symbol worth asking Finnhub about: a ticker, not a mutual fund."""
    s = (symbol or "").strip().upper()
    return bool(_TICKER.match(s)) and not _FUND.match(s)


def tickers_to_fetch(conn) -> list[str]:
    """Every ticker any account holds (in its latest snapshot) or watches,
    each once, the ones fetched longest ago first."""
    held = conn.execute(
        "SELECT DISTINCT p.symbol AS t FROM positions p JOIN "
        "(SELECT user_id, MAX(snapshot_date) AS d FROM positions "
        " WHERE user_id IS NOT NULL GROUP BY user_id) l "
        "ON p.user_id = l.user_id AND p.snapshot_date = l.d").fetchall()
    watched = conn.execute("SELECT DISTINCT ticker AS t FROM watchlist").fetchall()
    symbols = {str(r["t"]).strip().upper() for r in [*held, *watched] if r["t"]}
    symbols = {s for s in symbols if wanted(s)}
    last = {r["ticker"]: r["m"] or "" for r in conn.execute(
        "SELECT ticker, MAX(fetched_at) AS m FROM news GROUP BY ticker")}
    return sorted(symbols, key=lambda s: (last.get(s, ""), s))


def prune(conn, *, now: datetime | None = None, keep_days: int = KEEP_DAYS) -> int:
    """Delete stored stories published more than `keep_days` ago."""
    cut = ((now or datetime.now(timezone.utc)) - timedelta(days=keep_days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    cur = conn.execute("DELETE FROM news WHERE published_at IS NOT NULL AND published_at < ?",
                       (cut,))
    conn.commit()
    return cur.rowcount or 0


def sync_all(conn, token: str, *, delay: float = DELAY, max_tickers: int = MAX_PER_RUN,
             fetch=None, sleep=time.sleep, log=print) -> dict:
    """Fetch and store news for every held or watched ticker (tickers_to_fetch),
    pausing `delay` seconds between calls. `fetch(symbol, token)` returns
    (articles, error) - news.fetch_company_news unless a test passes its own.
    Returns {tickers, fetched, skipped, new, failed, stopped}."""
    fetch = fetch or news.fetch_company_news
    todo = tickers_to_fetch(conn)
    fresh_hours = FRESH_MINUTES / 60
    summary = {"tickers": len(todo), "fetched": 0, "skipped": 0, "new": 0, "failed": 0,
               "stopped": False}
    limited, calls = 0, 0
    for sym in todo:
        if calls >= max_tickers:
            summary["skipped"] += 1
            continue
        if not news.needs_refresh(conn, sym, max_age_hours=fresh_hours):
            summary["skipped"] += 1
            continue
        if calls:
            sleep(delay)
        calls += 1
        articles, err = fetch(sym, token)
        if err:
            summary["failed"] += 1
            log(f"  {sym:<8} {err}")
            limited = limited + 1 if err.startswith("HTTP 429") else 0
            if limited >= RATE_LIMITED_STOP:
                summary["stopped"] = True
                log("  Finnhub says too many requests - stopping; the next run carries on.")
                break
            continue
        limited = 0
        summary["fetched"] += 1
        summary["new"] += news.upsert_news(conn, sym, articles)
    return summary


def main(argv=None) -> int:
    import flags
    import pgcompat
    import settings
    from portfolio import connect

    ap = argparse.ArgumentParser(description="Store news for every held or watched ticker.")
    ap.add_argument("--db", default=settings.get("PORTFOLIO_DB") or "portfolio.db")
    ap.add_argument("--delay", type=float, default=DELAY,
                    help=f"seconds between calls (default {DELAY}; the free plan allows 60 a minute)")
    ap.add_argument("--max", type=int, default=MAX_PER_RUN, help="tickers a run at most")
    args = ap.parse_args(argv)
    if not flags.on("news_feed"):
        print("Your news (flag news_feed) is off - nothing fetched.")
        return 0
    token = settings.get("FINNHUB_API_KEY", env_file=True)
    if not token:
        print("FINNHUB_API_KEY is not set - nothing fetched.")
        return 0
    if not pgcompat.is_postgres_dsn(args.db) and not os.path.isfile(args.db):
        raise SystemExit(f"No database at {args.db}")
    conn = connect(args.db)
    try:
        s = sync_all(conn, token, delay=args.delay, max_tickers=args.max)
        gone = prune(conn)
    finally:
        conn.close()
    print(f"News: {s['tickers']} ticker(s), {s['fetched']} fetched, {s['skipped']} skipped, "
          f"{s['failed']} failed, {s['new']} new, {gone} older than {KEEP_DAYS} days deleted.")
    # a run fails (and the admin hears) only when every call it made failed
    return 1 if s["failed"] and not s["fetched"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
