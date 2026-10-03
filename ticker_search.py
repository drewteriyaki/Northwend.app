"""Find a stock or fund from what someone types: its ticker or its name.

People new to investing often know "Apple" or "Vanguard Total Stock Market",
not AAPL or VTI. resolve() takes what was typed in the hand-entry window
(views/holdings_input.py) and says what it is:

- "ticker": an exact ticker - taken as is (its name is shown beside it).
- "suggest": a name, matched - a best guess and a few others, shown as a
  question ("Apple Inc. (AAPL)?") to confirm or pick from. Never taken
  without the person choosing it.
- "unknown": looks like a ticker but nothing here knows it (the search is
  out of reach) - taken as typed; the price lookup before saving checks it.
- "none": not a ticker and no name matched.

Where the names come from, in order:
1. Yahoo Finance's search (yfinance.Search), when it answers - a short
   timeout, results cached for a day, and a failure remembered for a couple
   of minutes so a page redraw never waits on it again.
2. Names already known here: security_info (the market data the app keeps),
   this account's own holdings' descriptions (known(), read by the caller),
   and COMMON below - a short, factual list of widely held US stocks and
   funds, so the common names work even with no network.

Only the typed text goes to Yahoo, never holdings or amounts. No Streamlit.
"""

from __future__ import annotations

import re
import threading
import time

# Yahoo's quoteType -> the hand-entry form's types (manual_entry.TYPES)
KINDS = {"EQUITY": "Stock", "ETF": "ETF", "MUTUALFUND": "Mutual fund",
         "CRYPTOCURRENCY": "Crypto"}
# broker asset types (what imports store) -> the same words
_ASSET_KINDS = {"Equity": "Stock", "ETFs & Closed End Funds": "ETF", "ETF / CEF": "ETF",
                "Mutual Funds": "Mutual fund", "Crypto": "Crypto"}

# (symbol, name, kind, other names people use). Widely held US stocks and
# broad funds from several providers - a fallback for when the search is out
# of reach, not a list of picks. Names as the companies and funds give them.
COMMON = (
    ("AAPL", "Apple Inc.", "Stock", ""),
    ("MSFT", "Microsoft Corporation", "Stock", ""),
    ("NVDA", "NVIDIA Corporation", "Stock", ""),
    ("AMZN", "Amazon.com, Inc.", "Stock", "amazon"),
    ("GOOGL", "Alphabet Inc. Class A", "Stock", "google"),
    ("GOOG", "Alphabet Inc. Class C", "Stock", "google"),
    ("META", "Meta Platforms, Inc.", "Stock", "facebook"),
    ("TSLA", "Tesla, Inc.", "Stock", ""),
    ("BRK-B", "Berkshire Hathaway Inc. Class B", "Stock", ""),
    ("JPM", "JPMorgan Chase & Co.", "Stock", "chase"),
    ("V", "Visa Inc.", "Stock", ""),
    ("MA", "Mastercard Incorporated", "Stock", ""),
    ("JNJ", "Johnson & Johnson", "Stock", ""),
    ("WMT", "Walmart Inc.", "Stock", ""),
    ("COST", "Costco Wholesale Corporation", "Stock", ""),
    ("KO", "The Coca-Cola Company", "Stock", "coke"),
    ("PEP", "PepsiCo, Inc.", "Stock", "pepsi"),
    ("PG", "The Procter & Gamble Company", "Stock", ""),
    ("DIS", "The Walt Disney Company", "Stock", "disney"),
    ("NFLX", "Netflix, Inc.", "Stock", ""),
    ("MCD", "McDonald's Corporation", "Stock", "mcdonalds"),
    ("NKE", "NIKE, Inc.", "Stock", ""),
    ("SBUX", "Starbucks Corporation", "Stock", ""),
    ("AMD", "Advanced Micro Devices, Inc.", "Stock", "amd"),
    ("INTC", "Intel Corporation", "Stock", ""),
    ("AVGO", "Broadcom Inc.", "Stock", ""),
    ("ORCL", "Oracle Corporation", "Stock", ""),
    ("CRM", "Salesforce, Inc.", "Stock", ""),
    ("ADBE", "Adobe Inc.", "Stock", ""),
    ("HD", "The Home Depot, Inc.", "Stock", ""),
    ("UNH", "UnitedHealth Group Incorporated", "Stock", ""),
    ("LLY", "Eli Lilly and Company", "Stock", "lilly"),
    ("PFE", "Pfizer Inc.", "Stock", ""),
    ("XOM", "Exxon Mobil Corporation", "Stock", "exxon"),
    ("T", "AT&T Inc.", "Stock", ""),
    ("VZ", "Verizon Communications Inc.", "Stock", ""),
    ("F", "Ford Motor Company", "Stock", ""),
    ("GM", "General Motors Company", "Stock", ""),
    ("BA", "The Boeing Company", "Stock", ""),
    ("UBER", "Uber Technologies, Inc.", "Stock", ""),
    ("PLTR", "Palantir Technologies Inc.", "Stock", ""),
    ("VTI", "Vanguard Total Stock Market ETF", "ETF", ""),
    ("VOO", "Vanguard S&P 500 ETF", "ETF", ""),
    ("VT", "Vanguard Total World Stock ETF", "ETF", ""),
    ("VXUS", "Vanguard Total International Stock ETF", "ETF", ""),
    ("VEA", "Vanguard FTSE Developed Markets ETF", "ETF", ""),
    ("VWO", "Vanguard FTSE Emerging Markets ETF", "ETF", ""),
    ("BND", "Vanguard Total Bond Market ETF", "ETF", ""),
    ("BNDX", "Vanguard Total International Bond ETF", "ETF", ""),
    ("VYM", "Vanguard High Dividend Yield ETF", "ETF", ""),
    ("VNQ", "Vanguard Real Estate ETF", "ETF", ""),
    ("SPY", "SPDR S&P 500 ETF Trust", "ETF", ""),
    ("DIA", "SPDR Dow Jones Industrial Average ETF Trust", "ETF", "dow"),
    ("GLD", "SPDR Gold Shares", "ETF", "gold"),
    ("IVV", "iShares Core S&P 500 ETF", "ETF", ""),
    ("ITOT", "iShares Core S&P Total U.S. Stock Market ETF", "ETF", ""),
    ("IXUS", "iShares Core MSCI Total International Stock ETF", "ETF", ""),
    ("AGG", "iShares Core U.S. Aggregate Bond ETF", "ETF", ""),
    ("IWM", "iShares Russell 2000 ETF", "ETF", ""),
    ("SCHB", "Schwab U.S. Broad Market ETF", "ETF", ""),
    ("SCHX", "Schwab U.S. Large-Cap ETF", "ETF", ""),
    ("SCHF", "Schwab International Equity ETF", "ETF", ""),
    ("SCHZ", "Schwab U.S. Aggregate Bond ETF", "ETF", ""),
    ("SCHD", "Schwab U.S. Dividend Equity ETF", "ETF", ""),
    ("QQQ", "Invesco QQQ Trust", "ETF", "nasdaq"),
    ("VTSAX", "Vanguard Total Stock Market Index Fund Admiral Shares", "Mutual fund", ""),
    ("VFIAX", "Vanguard 500 Index Fund Admiral Shares", "Mutual fund", ""),
    ("VTIAX", "Vanguard Total International Stock Index Fund Admiral Shares", "Mutual fund", ""),
    ("VBTLX", "Vanguard Total Bond Market Index Fund Admiral Shares", "Mutual fund", ""),
    ("FXAIX", "Fidelity 500 Index Fund", "Mutual fund", ""),
    ("FSKAX", "Fidelity Total Market Index Fund", "Mutual fund", ""),
    ("FTIHX", "Fidelity Total International Index Fund", "Mutual fund", ""),
    ("FXNAX", "Fidelity U.S. Bond Index Fund", "Mutual fund", ""),
    ("SWPPX", "Schwab S&P 500 Index Fund", "Mutual fund", ""),
    ("SWTSX", "Schwab Total Stock Market Index Fund", "Mutual fund", ""),
)

MAX_CHOICES = 5          # a best guess and up to four others
TIMEOUT = 3.0            # seconds to wait for Yahoo's search
CACHE_SECONDS = 24 * 3600
DOWN_SECONDS = 120       # after a failed search, don't ask again for this long

_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9]{0,5}(?:[.\-][A-Z0-9]{1,4})?$")
# words that don't tell one company or fund from another
_FILLER = {"inc", "corp", "corporation", "co", "company", "the", "ltd", "plc", "class",
           "shares", "share", "etf", "fund", "index", "incorporated", "and", "of", "a"}


def looks_like_ticker(text: str) -> bool:
    """A short code like VTI, BRK-B or BRK.B: no spaces, a letter first."""
    t = (text or "").strip()
    return bool(t) and " " not in t and bool(_TICKER_RE.match(t.upper()))


def _words(text: str) -> list[str]:
    """Lower-case words without filler: "S&P" -> "sp", "Amazon.com" -> "amazoncom"."""
    t = (text or "").lower().replace("&", "").replace(".", "").replace("'", "")
    t = t.replace("’", "")
    return [w for w in re.split(r"[^a-z0-9]+", t) if w and w not in _FILLER]


def name_score(query: str, name: str, also: str = "") -> float:
    """How well a typed name matches a security's name (0 = not at all).
    Every typed word has to begin a word of the name (or of `also`, the
    other names people use); more of the name covered scores higher."""
    q = _words(query)
    n = _words(name) + _words(also)
    if not q or not n:
        return 0.0
    hits = 0
    for w in q:
        if w in n:
            hits += 2
        elif len(w) >= 2 and any(x.startswith(w) for x in n):
            hits += 1
        else:
            return 0.0
    covered = len(q) / max(len(_words(name)) or 1, 1)
    return hits / (2 * len(q)) + min(covered, 1.0)


def _entry(symbol, name, kind=None) -> dict:
    return {"symbol": (symbol or "").strip().upper(), "name": (name or "").strip() or None,
            "kind": kind}


# ---- Yahoo's search, cached --------------------------------------------- #
_LOCK = threading.Lock()
_CACHE: dict = {}          # query (lower case) -> (time, results)
_DOWN_UNTIL = [0.0]


def _yahoo_raw(query: str, timeout: float) -> list[dict]:
    import yfinance as yf
    s = yf.Search(query, max_results=8, news_count=0, lists_count=0, include_cb=False,
                  recommended=0, timeout=timeout, raise_errors=True)
    return list(s.quotes or [])


def yahoo_search(query: str, *, timeout: float = TIMEOUT, now=None, raw=None) -> list[dict] | None:
    """[{symbol, name, kind}] from Yahoo's search - US listings of stocks,
    funds and crypto - or None when Yahoo can't be reached. Cached; a failure
    pauses asking for DOWN_SECONDS. `raw` stands in for the request (tests)."""
    q = (query or "").strip()
    if not q:
        return []
    key = q.lower()
    t = time.time() if now is None else now
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and t - hit[0] < CACHE_SECONDS:
            return hit[1]
        if t < _DOWN_UNTIL[0]:
            return None
    try:
        quotes = (raw or _yahoo_raw)(q, timeout)
    except Exception:
        with _LOCK:
            _DOWN_UNTIL[0] = t + DOWN_SECONDS
        return None
    out, seen = [], set()
    for r in quotes or []:
        sym = str(r.get("symbol") or "").upper()
        kind = KINDS.get(str(r.get("quoteType") or "").upper())
        # other exchanges' listings carry a suffix (AAPL.MX); crypto is BTC-USD
        if not sym or not kind or sym in seen or ("." in sym and kind != "Crypto"):
            continue
        seen.add(sym)
        out.append(_entry(sym, r.get("longname") or r.get("shortname"), kind))
    with _LOCK:
        if len(_CACHE) > 2000:
            _CACHE.clear()
        _CACHE[key] = (t, out)
    return out


def clear_cache():
    with _LOCK:
        _CACHE.clear()
        _DOWN_UNTIL[0] = 0.0


# ---- names known here --------------------------------------------------- #
def known(conn, user_id: int | None = None) -> list[dict]:
    """Securities this copy already knows by name: the market data it keeps
    (security_info) and, with `user_id`, that account's own holdings'
    descriptions. [{symbol, name, kind}]."""
    out = []
    try:
        for r in conn.execute("SELECT ticker, name, quote_type FROM security_info "
                              "WHERE name IS NOT NULL"):
            out.append(_entry(r["ticker"], r["name"], KINDS.get((r["quote_type"] or "").upper())))
    except Exception:
        pass   # an older database without quote_type: the names are a nice-to-have
    if user_id is not None:
        for r in conn.execute("SELECT DISTINCT symbol, description, asset_type FROM positions "
                              "WHERE user_id = ? AND description IS NOT NULL", (user_id,)):
            out.append(_entry(r["symbol"], r["description"], _ASSET_KINDS.get(r["asset_type"])))
    return out


def _local(extra) -> list[dict]:
    """COMMON plus `extra` (known()), one entry per symbol, COMMON first."""
    out, seen = [], set()
    for sym, name, kind, also in COMMON:
        seen.add(sym)
        out.append({**_entry(sym, name, kind), "also": also})
    for e in extra or ():
        if e.get("symbol") and e["symbol"] not in seen and e.get("name"):
            seen.add(e["symbol"])
            out.append({**e, "also": ""})
    return out


# ---- what was typed ------------------------------------------------------ #
def resolve(text: str, *, search="yahoo", extra=()) -> dict:
    """What `text` is: {"status", "query", "symbol", "name", "kind",
    "choices", "online"}. status is "empty", "ticker" (symbol/name/kind set),
    "suggest" (choices: [{symbol, name, kind}], best first - to confirm),
    "unknown" (looks like a ticker nobody here knows; symbol = as typed) or
    "none". `search`: "yahoo" (yahoo_search), a stand-in, or None (names
    known here only); `extra` is known()."""
    raw = (text or "").strip()
    out = {"status": "empty", "query": raw, "symbol": None, "name": None, "kind": None,
           "choices": [], "online": False}
    if not raw:
        return out
    q = raw.upper()
    caps = raw == q and any(ch.isalpha() for ch in raw)
    if search == "yahoo":
        search = yahoo_search
    found = search(raw) if search else None
    out["online"] = found is not None
    local = _local(extra)
    by_sym = {e["symbol"]: e for e in local}
    exact = next((e for e in (found or []) if e["symbol"] == q), None) or by_sym.get(q)
    if exact and not exact.get("name") and by_sym.get(q):
        exact = {**exact, "name": by_sym[q]["name"]}
    # names that match: the search's results (it matched them), then local ones
    scored = sorted(((name_score(raw, e["name"] or "", e.get("also", "")), i, e)
                     for i, e in enumerate(local)), key=lambda x: (-x[0], x[1]))
    named = [e for s, _, e in scored if s > 0]
    candidates, seen = [], set()
    for e in [*(found or []), *named]:
        if e["symbol"] not in seen:
            seen.add(e["symbol"])
            candidates.append({k: e.get(k) for k in ("symbol", "name", "kind")})
    if exact:
        # typed in capitals, or nothing else goes by that name: the ticker.
        # "ford" is a ticker too (another company's), so a lower-case word
        # that is also a name is asked about, the name's match first.
        others = [e for e in named if e["symbol"] != q] + \
                 [e for e in (found or []) if e["symbol"] != q and name_score(raw, e["name"] or "")]
        if caps or not others or not looks_like_ticker(raw):
            out.update(status="ticker", symbol=exact["symbol"], name=exact.get("name"),
                       kind=exact.get("kind"))
            return out
        candidates = [c for c in candidates if c["symbol"] != q]
        candidates = [*[c for c in candidates if any(o["symbol"] == c["symbol"] for o in others)],
                      *[c for c in candidates if not any(o["symbol"] == c["symbol"]
                                                         for o in others)]]
        candidates.insert(min(MAX_CHOICES - 1, len(candidates)),
                          {k: exact.get(k) for k in ("symbol", "name", "kind")})
    if candidates:
        out.update(status="suggest", choices=candidates[:MAX_CHOICES])
        best = candidates[0]
        out.update(symbol=best["symbol"], name=best["name"], kind=best["kind"])
        return out
    if looks_like_ticker(raw):
        out.update(status="unknown", symbol=q)
    else:
        out["status"] = "none"
    return out


def label(choice: dict) -> str:
    """"Apple Inc. (AAPL)" - or just the symbol when there's no name."""
    return f"{choice['name']} ({choice['symbol']})" if choice.get("name") else choice["symbol"]
