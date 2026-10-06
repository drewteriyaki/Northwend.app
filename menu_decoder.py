"""The 401(k) Menu Decoder (ROADMAP R5; docs/PLAN.md step 3 item 5, started
early in step 2 by decision B11): paste a plan's fund list, see what kind of
fund each line is and what it charges. No AI. Descriptive only.

A person copies the list of investment options from their plan's enrolment
page - one fund per line, in whatever shape the recordkeeper shows it: a name,
sometimes a ticker in brackets or its own column, sometimes the expense ratio
in the text, sometimes headings ("Large Cap") and performance figures in
between. decode() reads it and, for each fund line, in the order pasted:

- identifies it, conservatively, against the fund data the app already keeps
  (security_info, from Yahoo via sync_history) and ticker_search.COMMON's
  names: by its ticker when the line has one (and the name doesn't plainly
  contradict it), else by its name - the same words, after spelling out the
  usual abbreviations ("Idx", "Intl", "Adm"). A trust or a different share
  class is a different fund with a different fee, so "close" is not a match:
  anything unsure is an honest "couldn't identify";
- says its kind (target-date, US stock, international, bond, stable value,
  money market...), from the fund data, or - marked as such - from plain
  words in its name;
- gives its yearly fee: the one pasted with it when the line says so ("as
  you pasted it"), else the fund data's (security_info.expense_ratio, with
  its date);
- and, at a monthly amount the person types, the fee in dollars on a year
  of contributions (yearly_dollars: monthly x 12 x the fee - a rough
  estimate, said plainly in the window).

The rows stay in the pasted order. Nothing here sorts by fee or anything
else Northwend works out, ranks, or calls a fund "best" (ROADMAP's principle
risks for R5: a table of kind and fee reads as a pick list). Nothing is
written anywhere: the pasted text and the result live only in the person's
session (views/menu_decoder.py). The one thing counted is numbers for the R5
metric, "the share of pasted funds identified" (add_counts, read in totals by
feature_counts.decoder).

Pure logic plus one read (known_funds); standard library only.
"""

from __future__ import annotations

import re
from datetime import date

import fees
from ticker_search import COMMON

PREF_COUNTS = "decoder_401k_counts"   # user_prefs: {"decodes", "lines", "identified"} - numbers only
MAX_LINES = 120                       # a plan menu is 10-40 funds; the rest is left out
MAX_CHARS = 30000

# kind -> (label, a plain one-line description - general education, the same for everyone)
KINDS = {
    "target_date": ("Target-date fund",
                    "One fund holding stocks and bonds together, shifting toward bonds as the "
                    "year in its name gets closer."),
    "us_stock": ("US stock fund", "Owns shares of US companies."),
    "intl_stock": ("International stock fund", "Owns shares of companies outside the US."),
    "stock": ("Stock fund", "Owns mostly company shares, in the US and abroad."),
    "bond": ("Bond fund",
             "Lends money to governments and companies, and is paid interest. Bond funds "
             "usually rise and fall less than stock funds."),
    "balanced": ("Balanced fund", "Holds stocks and bonds together, in a set mix."),
    "sector": ("Sector or specialty fund",
               "Owns one slice of the market - one industry, real estate or a commodity."),
    "stable_value": ("Stable value fund",
                     "A workplace-plan option meant to keep its value steady while paying a "
                     "modest rate of interest."),
    "money_market": ("Money market fund",
                     "Holds very short-term loans; it works much like cash and pays interest."),
    "company_stock": ("A single company's stock",
                      "Shares of one company - its value rises and falls with that company "
                      "alone."),
    "other": ("Other kind", "The fund data doesn't say clearly what kind of fund this is."),
}
INDEXABLE = ("target_date", "us_stock", "intl_stock", "stock", "bond", "balanced", "sector")

UNIDENTIFIED = "Couldn't identify this one - check the plan's fund fact sheet"
WHY = {   # why a line wasn't identified (shown under the table)
    "no_match": "no fund we know has exactly that name",
    "unknown_ticker": "we don't have data for that ticker",
    "name_and_ticker_differ": "its name and ticker point to different funds",
    "several": "more than one fund we know matches it",
    "several_tickers": "the line has more than one ticker",
}

# ---- reading the paste ------------------------------------------------------ #
_PCT = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d+)?|\.\d+)\s?%")
# dollar amounts and digit groups (a balance pasted along with the menu): never kept or shown
_MONEY = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?|(?<![\d.])\d{1,3}(?:,\d{3})+(?:\.\d+)?")
_PAREN_TICKER = re.compile(r"\(\s*([A-Z]{2,5})\s*\)")
_LABEL_TICKER = re.compile(r"(?i:\b(?:ticker|symbol)\b)\s*(?:symbol)?\s*[:#-]?\s*([A-Z]{1,5})\b")
_FUND_TICKER = re.compile(r"(?<![A-Za-z0-9])([A-Z]{4}X)(?![A-Za-z0-9])")
_BARE_TICKER = re.compile(r"(?<![A-Za-z0-9&.'-])([A-Z]{2,5})(?![A-Za-z0-9&'-])")
_BULLET = re.compile(r"^\s*(?:[-*•·◦▪]+|\d{1,3}[.)]|\(\d{1,3}\))\s+")
_MARKS = re.compile(r"[®™℠©*†‡]")

# capitals in fund names that aren't tickers
NOT_TICKERS = {
    "US", "USA", "ETF", "ETFS", "CIT", "II", "III", "IV", "VI", "TR", "NAV", "NA", "SA",
    "LP", "LLC", "INC", "REIT", "MSCI", "FTSE", "CRSP", "EAFE", "ESG", "TIPS", "ACWI",
    "ADM", "INST", "INV", "IDX", "INTL", "FID", "SP", "MM", "BOND", "FUND", "STOCK",
    "INDEX", "GROWTH", "VALUE", "TOTAL", "YR", "YTD", "ER", "NET", "GROSS", "ADV", "SEL",
    "PIMCO", "DFA", "JP", "AB", "BNY", "SSGA", "IS", "CL", "PL", "NT", "TDF", "QDIA",
    "SMID", "EM", "DM", "MID", "CAP", "LG", "SM", "GOVT", "MUNI", "FIXED", "TRUST",
    "BLEND", "PLUS", "CORE", "STABLE", "MONEY", "MARKET", "INCOME", "EQUITY", "LARGE",
    "SMALL", "TARGET", "DATE", "THE", "AND", "OF", "FOR", "USD", "NONE",
}

# words that start a detail about the fund above, not a fund of its own
_DETAIL_START = re.compile(
    r"^(?:ticker|symbol|(?:gross|net|total)?\s*(?:annual\s+)?(?:operating\s+)?expense|exp\.?\s*ratio|"
    r"er\b|fees?\b|gross\b|net\b|category|morningstar|inception|asset\s+class|returns?\b|ytd\b|"
    r"\d+\s*-?\s*(?:yr|year|mo|month)s?\b|since\b|as\s+of\b|redemption|turnover|rating|"
    r"fact\s*sheet|prospectus|view\b|details?\b|performance|benchmark|style\b)", re.I)
_LABEL_WORDS = re.compile(
    r"(?i)\b(?:ticker|symbol|gross|net|total|annual|operating|expenses?|exp\.?|ratios?|er|fees?|"
    r"category|morningstar|inception|asset|class|returns?|ytd|yrs?|years?|mos?|months?|since|as|of|"
    r"date|redemption|turnover|rating|fact|sheet|prospectus|view|details?|performance|"
    r"benchmark|style|n/?a|none|nav|price|day|7-day|yield|life|fund|"
    # a balance or an election pasted along with the menu
    r"balances?|account|your|current|elections?|contributions?|units|shares|value|invested|"
    r"amount|change|percent|allocated|future)\b")
# fee labels just before a percentage, nearest first
_FEE_NET = re.compile(r"(?i)\bnet\b")
_FEE_GROSS = re.compile(r"(?i)\bgross\b")
_FEE_ANY = re.compile(r"(?i)expense|exp\.?\s*ratio|\ber\b|\bfees?\b|operating")
_NUM = r"(\d{1,2}(?:\.\d+)?|\.\d+)"
_GROSS_NET = re.compile(r"(?i)\b(gross\s*/\s*net|net\s*/\s*gross)\b\)?[^\d%]{0,30}?"
                        + _NUM + r"\s?%?\s*/\s*" + _NUM + r"\s?%")

# words a heading line is made of ("Large Cap", "Fixed Income:", "Tier 2 - Index Funds")
HEADING_WORDS = {
    "large", "mid", "small", "cap", "caps", "capitalization", "blend", "value", "growth",
    "core", "plus", "foreign", "international", "domestic", "us", "u", "s", "global", "world",
    "emerging", "markets", "market", "equity", "equities", "stock", "stocks", "bond", "bonds",
    "fixed", "income", "target", "date", "target-date", "retirement", "lifecycle", "funds",
    "asset", "allocation", "balanced", "short",
    "short-term", "intermediate", "long", "term", "government", "specialty", "sector",
    "real", "estate", "cash", "money", "stable", "preservation", "capital", "conservative",
    "moderate", "aggressive", "tier", "tiers", "1", "2", "3", "4", "i", "ii", "iii", "iv",
    "investments", "investment", "options", "option", "choices", "your", "plan", "menu",
    "active", "actively", "passive", "passively", "managed", "other", "and", "inflation",
    "protected", "high", "yield", "mixed", "hybrid", "alternatives", "alternative", "blended",
    "self-directed", "brokerage", "window", "lifestyle", "do-it-yourself", "diy", "help",
    "do", "it", "for", "me", "myself", "core", "default", "qdia", "a", "the", "of",
}
_HEADER_NAME = re.compile(r"(?i)\b(?:fund|investment|option|name|description)\b")
_HEADER_TICKER = re.compile(r"(?i)\b(?:ticker|symbol)\b")
_HEADER_FEE = re.compile(r"(?i)expense|\bfees?\b|\ber\b")


def _clean_space(s: str) -> str:
    return " ".join(str(s or "").split())


def _fee_from_cell(cell: str) -> float | None:
    """A fee column's value: "0.04%" or a bare "0.04" (the column says it's a
    percent). A fraction, or None."""
    m = re.fullmatch(r"\s*(\d{1,2}(?:\.\d+)?|\.\d+)\s?%?\s*", cell or "")
    return _as_fee(m.group(1)) if m else None


def _as_fee(pct_text: str) -> float | None:
    """'0.04' (percent) -> 0.0004; None when it isn't a plausible yearly fee."""
    try:
        v = float(pct_text)
    except ValueError:
        return None
    return round(v / 100, 8) if 0 <= v < 3 else None


def fees_in(text: str) -> float | None:
    """The yearly fee a line states, as a fraction - only a percentage with a
    fee label just before it ("Expense ratio 0.04%", "Net 0.45%", "ER: .02%").
    A bare percentage could be a return or a yield, so it's never taken. Net
    (what holders pay) before an unlabelled-kind fee before gross."""
    text = text or ""
    both = _GROSS_NET.search(text)
    if both:   # "Gross/Net 0.52% / 0.45%"
        first, second = _as_fee(both.group(2)), _as_fee(both.group(3))
        net = second if both.group(1).lower().startswith("gross") else first
        if net is not None:
            return net
    found = {"net": None, "any": None, "gross": None}
    prev_end = 0
    for m in _PCT.finditer(text):
        # only the words since the number before count
        window = text[max(prev_end, m.start() - 40):m.start()]
        prev_end = m.end()
        fee = _as_fee(m.group(1))
        if fee is None:
            continue
        kind = ("net" if _FEE_NET.search(window) else "gross" if _FEE_GROSS.search(window)
                else "any" if _FEE_ANY.search(window) else None)
        if kind and found[kind] is None:
            found[kind] = fee
    for kind in ("net", "any", "gross"):
        if found[kind] is not None:
            return found[kind]
    return None


def tickers_in(text: str, known: set | None = None, columns=()) -> list[str]:
    """Tickers a line gives, in order, one each: in brackets "(FXAIX)", after a
    label "Ticker: VFIAX", a mutual-fund-style code "VBTLX", a column of its
    own, or - only when the app knows it and the line isn't all capitals -
    a short code standing on its own ("... ETF  VTI")."""
    known = known or set()
    out: list[str] = []

    def add(sym):
        sym = sym.upper()
        if sym not in NOT_TICKERS and sym not in out:
            out.append(sym)
    for m in _PAREN_TICKER.finditer(text):
        add(m.group(1))
    for m in _LABEL_TICKER.finditer(text):
        if m.group(1).upper() not in ("N", "NA"):
            add(m.group(1))
    letters = [ch for ch in text if ch.isalpha()]
    caps = bool(letters) and sum(ch.isupper() for ch in letters) / len(letters) > 0.8
    for m in _FUND_TICKER.finditer(text):
        if not caps or m.group(1) in known:
            add(m.group(1))
    for col in columns:
        col = col.strip()
        if re.fullmatch(r"[A-Z]{1,5}", col) and (col in known or re.fullmatch(r"[A-Z]{4}X", col)):
            add(col)
    if not caps:
        for m in _BARE_TICKER.finditer(text):
            if m.group(1) in known:
                add(m.group(1))
    return out


def _strip_name(text: str, tickers=()) -> str:
    """The fund's name from a line: its tickers (in brackets or not), labelled
    fees, percentages, dollar amounts and trademark signs taken out, and cut
    before a fee or ticker label. Other capitals ("(CIT)", "INDEX") stay."""
    t = _MARKS.sub("", text)
    t = _MONEY.sub(" ", t)
    cut = re.search(r"(?i)\s(?:ticker|symbol|(?:gross|net|total)\s+(?:annual\s+)?expense|"
                    r"expense|exp\.?\s*ratio|\ber\s*:|fees?\s*:)", t)
    if cut:
        t = t[:cut.start()]
    t = _PCT.sub(" ", t)
    for sym in tickers:
        t = re.sub(r"\(\s*" + re.escape(sym) + r"\s*\)|(?<![A-Za-z0-9])" + re.escape(sym)
                   + r"(?![A-Za-z0-9])", " ", t)
    t = re.sub(r"\(\s*\)", " ", t)
    t = re.sub(r"(?i)\bn/a\b", " ", t)
    t = _clean_space(t)
    return t.strip(" -–—:;,/|")


def _is_heading(name: str) -> bool:
    words = [w for w in re.split(r"[\s/&,+()]+|\s-\s", name.lower().rstrip(":")) if w]
    if not words:
        return False
    if name.endswith(":") and len(words) <= 6:
        return True

    def heading_word(w):
        w = w.strip(".-–—")
        return not w or w in HEADING_WORDS or bool(re.fullmatch(r"20\d\d", w))
    return len(words) <= 6 and all(heading_word(w) for w in words)


def _attach(funds: list, tickers: list, fee) -> None:
    """A detail line's ticker or fee goes to the fund above it, if it has none."""
    if not funds:
        return
    if tickers and not funds[-1]["tickers"]:
        funds[-1]["tickers"] = tickers
    if fee is not None and funds[-1]["fee"] is None:
        funds[-1]["fee"] = fee


def _split(line: str) -> list[str]:
    """A line's columns: tabs (a table copied from a web page), pipes, or runs
    of spaces. An empty cell keeps its place, so columns line up with the
    header's."""
    if "\t" in line:
        cols = line.split("\t")
    elif "|" in line:
        cols = line.split("|")
    else:
        cols = re.split(r"\s{2,}", line)
    return [c.strip() for c in cols]


def _header(cols: list[str]) -> dict | None:
    """Column positions from a header line ("Fund name | Ticker | Net expense
    ratio"), or None when the line isn't one."""
    if sum(1 for c in cols if c) < 2 or any(_PCT.search(c) for c in cols):
        return None
    pos = {"name": None, "ticker": None, "fee": None}
    fee_net = None
    for i, c in enumerate(cols):
        if not c:
            continue
        if _HEADER_TICKER.search(c) and pos["ticker"] is None:
            pos["ticker"] = i
        elif _HEADER_FEE.search(c):
            if re.search(r"(?i)\bnet\b", c):
                fee_net = i
            elif pos["fee"] is None:
                pos["fee"] = i
        elif _HEADER_NAME.search(c) and pos["name"] is None:
            pos["name"] = i
    if fee_net is not None:
        pos["fee"] = fee_net
    if pos["name"] is None or (pos["ticker"] is None and pos["fee"] is None):
        return None
    if any(len(c.split()) > 5 for c in cols):
        return None
    return pos


def _residue(text: str) -> str:
    """What's left of a line once tickers, numbers, percentages and label
    words are taken out - empty for a line of details only."""
    t = _MONEY.sub(" ", _MARKS.sub("", text))
    t = _PCT.sub(" ", t)
    t = _PAREN_TICKER.sub(" ", t)
    t = _LABEL_TICKER.sub(" ", t)
    t = _FUND_TICKER.sub(" ", t)
    t = _LABEL_WORDS.sub(" ", t)
    t = re.sub(r"[\d.,:;/|()\-–—+%$#]+", " ", t)
    return _clean_space(t)


def read_lines(text: str, known_symbols: set | None = None) -> dict:
    """The paste, line by line: {"funds": [{"pasted", "tickers", "fee"}] in
    the pasted order, "skipped": headings not counted as funds, "truncated":
    more than MAX_LINES fund lines (the rest left out)}. A line with only a
    ticker or a fee ("Expense ratio: 0.04%") belongs to the fund above it;
    a header line sets which column holds what."""
    known_symbols = known_symbols or set()
    funds: list[dict] = []
    skipped: list[str] = []
    header = None
    truncated = False
    for raw in str(text or "")[:MAX_CHARS].splitlines():
        line = _BULLET.sub("", raw.replace("\u00a0", " ")).strip()
        if not any(ch.isalpha() for ch in line):
            continue
        cols = _split(line)
        head = _header(cols)
        if head:
            header = head
            continue
        filled = [c for c in cols if c]
        tickers = tickers_in(line, known_symbols, filled if len(filled) > 1 else ())
        fee = fees_in(line)
        name_src = line
        if header and len(cols) > max(v for v in header.values() if v is not None) \
                and cols[header["name"]]:
            name_src = cols[header["name"]]
            if header["ticker"] is not None:
                t = cols[header["ticker"]].upper()
                if re.fullmatch(r"[A-Z]{1,5}", t) and t not in NOT_TICKERS and t not in tickers:
                    tickers.insert(0, t)
            if header["fee"] is not None and fee is None:
                fee = _fee_from_cell(cols[header["fee"]])
        elif len(filled) > 1:
            # the first column with a name in it
            name_src = next((c for c in filled if _residue(c)), filled[0])
        detail = bool(_DETAIL_START.match(line)) or not _residue(line)
        if detail:
            _attach(funds, tickers, fee)
            continue
        name = _strip_name(name_src, tickers)
        # a trailing "- Large Blend" or "(Large Cap)" is a category, not part of the name
        tail = re.search(r"\s+[-–—]\s+([^-–—]+)$|\s*\(([^()]+)\)$", name)
        if tail and _is_heading(tail.group(1) or tail.group(2)):
            name = name[:tail.start()].strip()
        if _is_heading(name):
            if not tickers and fee is None:
                skipped.append(name.rstrip(":"))
            else:   # "Large Blend   Expense ratio 0.02%": about the fund above
                _attach(funds, tickers, fee)
            continue
        if len(funds) >= MAX_LINES:
            truncated = True
            break
        funds.append({"pasted": name or line, "tickers": tickers, "fee": fee})
    return {"funds": funds, "skipped": skipped, "truncated": truncated}


# ---- names ------------------------------------------------------------------ #
_ABBR = {
    "idx": "index", "indx": "index", "intl": "international", "internatl": "international",
    "inst": "institutional", "instl": "institutional", "instn": "institutional",
    "adm": "admiral", "admrl": "admiral", "inv": "investor", "mkt": "market",
    "mkts": "market", "markets": "market", "stk": "stock", "stocks": "stock",
    "govt": "government", "gov": "government", "ret": "retirement", "tgt": "target",
    "bd": "bond", "bds": "bond", "bonds": "bond", "tot": "total", "ttl": "total",
    "eq": "equity", "lg": "large", "lrg": "large", "sm": "small", "sml": "small",
    "val": "value", "grth": "growth", "gwth": "growth", "fid": "fidelity",
    "vang": "vanguard", "vngd": "vanguard", "amer": "american", "intermed": "intermediate",
    "intmdt": "intermediate", "intm": "intermediate", "yr": "year", "port": "portfolio",
    "trst": "trust", "cl": "class", "shs": "shares", "sh": "shares", "fd": "fund",
    "em": "emerging", "emg": "emerging", "dev": "developed", "glbl": "global",
    "infl": "inflation", "prot": "protected", "sec": "securities", "secs": "securities",
    "cit": "trust", "collective": "trust", "res": "reserves",
}
_FILLER = {"the", "fund", "funds", "inc", "shares", "share", "class", "and", "of", "co",
           "usd", "series"}


def name_words(name: str) -> list[str]:
    """A fund name as comparable words, in order: lower case, trademark signs
    and filler gone, the usual abbreviations spelled out."""
    t = _MARKS.sub("", str(name or "")).lower()
    t = t.replace("s&p", "sp").replace("u.s.", "us").replace("’", "").replace("'", "")
    t = t.replace("&", " ")
    out = []
    for w in re.split(r"[^a-z0-9]+", t):
        if not w:
            continue
        w = _ABBR.get(w, w)
        if w and w not in _FILLER:
            out.append(w)
    return out


def name_key(name: str) -> tuple:
    """A name's words in a fixed order: two names are the same fund's when
    their keys are equal. Nothing looser - "Vanguard 500 Index Fund" isn't
    "...Admiral Shares", and a name the fund data has cut short ("...Index
    Fund Ad") can't say which share class it was, so neither is a match."""
    return tuple(sorted(name_words(name)))


# ---- the fund data ---------------------------------------------------------- #
_INFO_COLS = ("ticker", "name", "quote_type", "category", "expense_ratio", "stock_pct",
              "bond_pct", "cash_pct", "other_pct", "fetched_at")
_FUND_QT = ("ETF", "MUTUALFUND", "MONEYMARKET")


def known_funds(conn) -> list[dict]:
    """The fund data the app already keeps (security_info - shared market
    data, no user id): one read, nothing written, nothing fetched."""
    try:
        rows = conn.execute(f"SELECT {', '.join(_INFO_COLS)} FROM security_info").fetchall()
    except Exception:   # an older database without these columns: nothing known
        return []
    return [{c: r[c] for c in _INFO_COLS} for r in rows]


def catalog(info_rows=()) -> dict:
    """{"by_symbol": {SYM: entry}, "names": {name_key: {SYM: entry}}} from
    security_info rows and ticker_search.COMMON's funds (names only - a fee
    comes only from security_info). Single stocks are known by ticker only."""
    by_symbol: dict = {}
    for r in info_rows or ():
        sym = str(r.get("ticker") or "").strip().upper()
        if not sym:
            continue
        by_symbol[sym] = {**r, "symbol": sym, "source": "data"}
    kinds = {"ETF": "ETF", "Mutual fund": "MUTUALFUND", "Stock": "EQUITY"}
    for sym, name, kind, _also in COMMON:
        e = by_symbol.get(sym)
        if e is None:
            by_symbol[sym] = {"symbol": sym, "ticker": sym, "name": name,
                              "quote_type": kinds.get(kind), "category": None,
                              "expense_ratio": None, "fetched_at": None, "source": "common"}
        elif not e.get("name"):
            e["name"] = name
    names: dict = {}
    for e in by_symbol.values():
        qt = (e.get("quote_type") or "").upper()
        if not e.get("name") or not (qt in _FUND_QT or (not qt and e.get("expense_ratio"))):
            continue
        key = name_key(e["name"])
        if key:
            names.setdefault(key, {})[e["symbol"]] = e
    return {"by_symbol": by_symbol, "names": names}


# ---- kinds ------------------------------------------------------------------ #
_TD_YEAR = re.compile(r"\b20[2-7][05]\b")
_TD_WORDS = ("target", "retirement", "lifetime", "lifepath", "freedom", "lifecycle",
             "destination", "life cycle")
_STOCKISH = ("stock", "equity", "equities")
_BONDISH = ("bond", "bonds", "treasury", "fixed income", "tips")
_INTLISH = ("international", "intl", "foreign", "emerging", "ex-us", "ex us", "eafe",
            "developed market")
_USISH = ("s&p 500", "sp 500", "500 index", "total stock market", "total us stock",
          "russell", "us stock", "large cap index", "mid cap index", "small cap index",
          "extended market")


def kind_from_name(name: str) -> str | None:
    """A kind from plain words in a fund's name - only the clear ones; None
    when the name doesn't say."""
    n = " " + _MARKS.sub("", str(name or "")).lower().replace("u.s.", "us") + " "
    if "stable value" in n or "stable asset" in n:
        return "stable_value"
    if "money market" in n or " money fund" in n or "government cash reserves" in n:
        return "money_market"
    if _TD_YEAR.search(n) and any(w in n for w in _TD_WORDS) or "target date" in n \
            or "target-date" in n:
        return "target_date"
    bondish = any(w in n for w in _BONDISH)
    stockish = any(w in n for w in _STOCKISH)
    intlish = any(w in n for w in _INTLISH)
    if bondish and not stockish:
        return "bond"
    if intlish and not bondish and not any(w in n for w in ("global", "world")):
        return "intl_stock"
    if any(w in n for w in _USISH) and not intlish and not bondish:
        return "us_stock"
    return None


def kind_of(entry: dict) -> str:
    """A known fund's kind, from its fund data (Yahoo's type and category,
    what it holds), then its name."""
    qt = (entry.get("quote_type") or "").upper()
    name = entry.get("name") or ""
    if qt == "EQUITY":
        return "company_stock"
    if qt == "MONEYMARKET":
        return "money_market"
    by_name = kind_from_name(name)
    if by_name in ("stable_value", "money_market"):
        return by_name
    k = fees.kind_of(entry.get("category"), name, entry)
    if k in KINDS:
        return k
    return by_name or "other"


def is_index(name: str) -> bool:
    n = " " + str(name or "").lower() + " "
    return " index" in n or " idx" in n


def kind_label(kind: str | None, name: str = "") -> str:
    """'US stock index fund', 'Bond fund', 'Stable value fund'..."""
    if not kind:
        return "—"
    label = KINDS[kind][0]
    if kind in INDEXABLE and is_index(name):
        label = label.replace(" fund", " index fund")
    return label


# ---- the whole menu --------------------------------------------------------- #
def _shares_a_word(pasted: str, known_name: str) -> bool:
    """A pasted name and the data's name for its ticker have something in
    common - or the paste has too little name to say."""
    generic = {"fund", "index", "trust", "portfolio", "class", "shares", "admiral",
               "institutional", "investor", "plus", "select", "premier", "k", "i", "a", "c",
               "r6", "r5", "r4", "r3", "r2", "r1", "y", "z"}
    p = [w for w in name_words(pasted) if w not in generic]
    if len(p) < 2:
        return True
    return bool(set(p) & set(name_words(known_name)))


def _identify(line: dict, cat: dict) -> dict:
    """{"status": "ticker" / "name" / "unidentified", "why", "entry", "symbol"}."""
    by_symbol = cat["by_symbol"]
    tickers = line["tickers"]
    if len(tickers) > 1:
        known = [t for t in tickers if t in by_symbol]
        if len(known) != 1:
            return {"status": "unidentified", "why": "several_tickers", "entry": None,
                    "symbol": None}
        tickers = known
    if tickers:
        sym = tickers[0]
        e = by_symbol.get(sym)
        if e is None:
            return {"status": "unidentified", "why": "unknown_ticker", "entry": None,
                    "symbol": sym}
        if e.get("name") and not _shares_a_word(line["pasted"], e["name"]):
            return {"status": "unidentified", "why": "name_and_ticker_differ", "entry": None,
                    "symbol": sym}
        return {"status": "ticker", "why": None, "entry": e, "symbol": sym}
    key = name_key(line["pasted"])
    hits = cat["names"].get(key, {}) if key else {}
    if len(hits) == 1:
        e = next(iter(hits.values()))
        return {"status": "name", "why": None, "entry": e, "symbol": e["symbol"]}
    return {"status": "unidentified", "why": "several" if hits else "no_match", "entry": None,
            "symbol": None}


def decode(text: str, info_rows=()) -> dict:
    """The decoded menu: {"rows": [...] in the pasted order, "lines": fund
    lines read, "identified": how many were identified, "skipped": headings
    not counted, "truncated"}. Each row: {"line" (1, 2, ...), "pasted" (the
    name as pasted, without any dollar amount), "pasted_ticker" (the line's
    one ticker, if it had one), "status" ("ticker", "name" or
    "unidentified"), "why", "symbol", "name", "quote_type", "kind",
    "kind_from" ("data" / "name" / None), "fee" (a fraction), "fee_source"
    ("pasted" / "data" / None), "fee_date" (ISO day of the data's fee),
    "data_fee" (the data's fee when it differs from the pasted one)}.
    `info_rows` is known_funds(); nothing is fetched or written."""
    cat = catalog(info_rows)
    read = read_lines(text, set(cat["by_symbol"]))
    rows = []
    for i, line in enumerate(read["funds"], start=1):
        found = _identify(line, cat)
        e = found["entry"]
        row = {"line": i, "pasted": line["pasted"],
               "pasted_ticker": line["tickers"][0] if len(line["tickers"]) == 1 else None,
               "status": found["status"], "why": found["why"], "symbol": found["symbol"],
               "name": None,
               "quote_type": None, "kind": None, "kind_from": None, "fee": None,
               "fee_source": None, "fee_date": None, "data_fee": None}
        if e is not None:
            row.update(name=e.get("name") or e["symbol"], quote_type=e.get("quote_type"),
                       kind=kind_of(e), kind_from="data")
            data_fee = e.get("expense_ratio")
            data_fee = float(data_fee) if data_fee is not None else None
            if row["kind"] == "company_stock":
                data_fee = None
            if line["fee"] is not None:
                row.update(fee=line["fee"], fee_source="pasted")
                if data_fee is not None and abs(data_fee - line["fee"]) >= 0.00005:
                    row.update(data_fee=data_fee, fee_date=_day(e.get("fetched_at")))
            elif data_fee is not None:
                row.update(fee=data_fee, fee_source="data", fee_date=_day(e.get("fetched_at")))
        else:
            k = kind_from_name(line["pasted"])
            if k:
                row.update(kind=k, kind_from="name")
            if line["fee"] is not None:
                row.update(fee=line["fee"], fee_source="pasted")
        rows.append(row)
    identified = sum(1 for r in rows if r["status"] != "unidentified")
    return {"rows": rows, "lines": len(rows), "identified": identified,
            "skipped": read["skipped"], "truncated": read["truncated"]}


def _day(ts) -> str | None:
    s = str(ts or "")[:10]
    try:
        date.fromisoformat(s)
    except ValueError:
        return None
    return s


# ---- the arithmetic --------------------------------------------------------- #
def yearly_dollars(monthly, ratio) -> float | None:
    """The fee on a year of contributions: monthly x 12 x the yearly fee.
    A rough estimate - money added during a year is invested for less than
    all of it, and growth isn't counted (said in the window)."""
    if monthly is None or ratio is None:
        return None
    try:
        monthly, ratio = float(monthly), float(ratio)
    except (TypeError, ValueError):
        return None
    if monthly <= 0 or ratio < 0:
        return None
    return monthly * 12 * ratio


def fmt_dollars(v) -> str:
    """'$1.44', '$36', '$1,250'."""
    if v is None:
        return "—"
    text = f"${v:,.2f}" if v < 1000 else f"${v:,.0f}"
    return text[:-3] if text.endswith(".00") else text


def fmt_day(iso: str | None) -> str:
    """'2026-10-03' -> 'Oct 3, 2026'."""
    try:
        d = date.fromisoformat(str(iso)[:10])
    except (TypeError, ValueError):
        return ""
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def fee_source_text(row: dict) -> str:
    if row["fee_source"] == "pasted":
        return "As you pasted it"
    if row["fee_source"] == "data":
        day = fmt_day(row["fee_date"])
        return "Yahoo Finance" + (f", {day}" if day else "")
    return "—"


def dollars_column(monthly) -> str:
    return f"Fee on a year of {fmt_dollars(float(monthly))} a month"


def table(result: dict, monthly=None) -> list[dict]:
    """The window's table, one dict per row in the pasted order - never
    sorted, ranked or marked."""
    out = []
    show_dollars = monthly is not None and float(monthly or 0) > 0
    for r in result["rows"]:
        if r["status"] == "unidentified":
            what = UNIDENTIFIED
        else:
            what = f"{r['name']} ({r['symbol']})" if r["name"] != r["symbol"] else r["symbol"]
        kind = kind_label(r["kind"], f"{r['name'] or ''} {r['pasted']}")
        if r["kind_from"] == "name":
            kind += " (going by its name)"
        pasted = r["pasted"] + (f" ({r['pasted_ticker']})" if r.get("pasted_ticker") else "")
        row = {"#": r["line"], "As you pasted it": pasted, "What it is": what,
               "Kind": kind, "Yearly fee": fees.fmt_ratio(r["fee"]),
               "Where the fee comes from": fee_source_text(r)}
        if show_dollars:
            row[dollars_column(monthly)] = fmt_dollars(yearly_dollars(monthly, r["fee"]))
        out.append(row)
    return out


def kinds_present(result: dict) -> list[str]:
    """The kinds in the result, in the order they first appear."""
    return list(dict.fromkeys(r["kind"] for r in result["rows"] if r["kind"]))


def overlap_funds(result: dict) -> list[str]:
    """Identified funds whose top holdings could be compared (ETFs and mutual
    funds), in the pasted order, each once."""
    return list(dict.fromkeys(r["symbol"] for r in result["rows"]
                              if r["status"] != "unidentified"
                              and fees.holding_type(r["quote_type"], None) == "fund"))


# ---- the R5 count (feature_counts.decoder) ----------------------------------- #
def add_counts(saved: dict, result: dict) -> dict:
    """The person's settings with this decode added to their counts: numbers
    only (decodes, fund lines, identified) - never a fund name or the text."""
    old = (saved or {}).get(PREF_COUNTS)
    old = old if isinstance(old, dict) else {}

    def n(k):
        try:
            return max(0, int(old.get(k) or 0))
        except (TypeError, ValueError):
            return 0
    new = {"decodes": n("decodes") + 1, "lines": n("lines") + int(result["lines"]),
           "identified": n("identified") + int(result["identified"])}
    return {**(saved or {}), PREF_COUNTS: new}


def counts_in(saved: dict) -> dict | None:
    """{"decodes", "lines", "identified"} from one account's settings, or None."""
    c = (saved or {}).get(PREF_COUNTS)
    if not isinstance(c, dict):
        return None
    try:
        out = {k: max(0, int(c.get(k) or 0)) for k in ("decodes", "lines", "identified")}
    except (TypeError, ValueError):
        return None
    out["identified"] = min(out["identified"], out["lines"])
    return out if out["decodes"] else None
