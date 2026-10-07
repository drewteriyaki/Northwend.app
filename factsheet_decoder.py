"""The Fact Sheet Decoder (ROADMAP R6, fact sheets first): paste the text of a
fund's fact sheet, see what it says in plain words. No AI. Descriptive only.

A fund fact sheet is a public document - one or two pages the fund company
publishes about one fund, with no personal data in it. decode() reads its
text locally and finds, each "as the fact sheet states it":

- the fund's name and ticker;
- its yearly fee (the expense ratio, as a percent - net before gross, the
  same reading as the 401(k) Menu Decoder's, menu_decoder.fees_in);
- the kind of fund: index or actively managed (from the sheet's own words or
  its name), and its asset class (the sheet's category, explained with the
  Menu Decoder's kinds);
- the share in its largest holdings, the number of holdings, the inception
  date and the benchmark.

Anything it can't find is an honest "couldn't find" row, never a guess. Each
row has a "what this means" line - general education, the same for everyone.
At a monthly amount the person types, the fee in dollars on a year of
contributions (menu_decoder.yearly_dollars, the same rough estimate).

Nothing here ranks, rates or compares the fund with anything: no good/bad,
cheap/expensive, should or best (a test checks every word it can show).

Statements are NOT read (ROADMAP R6's principle risk: a statement is full of
names, figures and account numbers, and local redaction isn't proven yet).
looks_like_statement() comes first: if the text has an account number, an
"account value" or "your balance", or a name-and-address block, decode()
stops and returns only which kinds of signs it saw - never the text or any
part of it - and the window says calmly that statements aren't read yet and
nothing was kept.

Nothing is written anywhere: the pasted text and the result live only in the
person's session (views/factsheet_decoder.py), never in the database, the
logs or the AI. Pure logic; standard library plus the app's calculation
modules.
"""

from __future__ import annotations

import re
from datetime import date

import fees
import menu_decoder as md

MAX_CHARS = 40000   # a fact sheet is 2-4 pages of text; the rest is left out
FIELDS = ("name", "ticker", "fee", "management", "asset_class", "top_share", "holdings",
          "inception", "benchmark")

NOT_FOUND = "Couldn't find this on the fact sheet"
CALM = ("This describes the fund the way its fact sheet does. It doesn't rate the fund or "
        "say whether to choose it - that's your decision (and the fund's prospectus or a "
        "professional can help).")
STATEMENT_NOTE = ("This looks like an account statement rather than a fund fact sheet. "
                  "Statements aren't read here yet - we want to be sure names, balances and "
                  "account numbers can be removed safely first. Nothing you pasted was kept, "
                  "and the box has been cleared.")
PLACEHOLDER = ("For example:\n"
               "Example Total Market Index Fund\n"
               "Ticker: EXTMX\n"
               "Expense ratio 0.04%\n"
               "Benchmark: Example Total Market Index\n"
               "Number of holdings 3,500")

# field -> (label shown, what it means: general education, the same for everyone)
ROWS = {
    "name": ("Fund name",
             "The fund's full name. Many funds come in several versions (share classes) with "
             "different fees, so the full name tells you which one this sheet is about."),
    "ticker": ("Ticker",
               "The short code used to look the fund up at a brokerage or in a 401(k). Each "
               "version of a fund has its own."),
    "fee": ("Yearly fee (expense ratio)",
            "The share of what you hold in the fund that it takes each year to run itself. "
            "It comes out of the fund's value, so you never see a bill."),
    "management": ("Index or actively managed",
                   "An index fund aims to follow a market index - a set list of investments. "
                   "An actively managed fund has managers who choose what to buy and sell."),
    "asset_class": ("What it invests in",
                    "The broad kind of investment the fund holds - stocks, bonds, a mix, or "
                    "something else."),
    "top_share": ("Share in its largest holdings",
                  "How much of the fund is in its biggest few holdings. The larger this "
                  "share, the more the fund's value rises and falls with those few."),
    "holdings": ("Number of holdings",
                 "How many different investments the fund owned on the fact sheet's date."),
    "inception": ("Inception date",
                  "The day the fund started. It has no results from before that day."),
    "benchmark": ("Benchmark",
                  "The index the fund measures itself against. Fact sheets usually show the "
                  "fund's results beside it."),
}
MANAGEMENT = {
    "index": ("Index fund", "It aims to follow a market index rather than having managers "
                            "pick what to buy."),
    "active": ("Actively managed", "Its managers choose what to buy and sell, aiming for "
                                   "results different from an index."),
}

# ---- is it a statement? ------------------------------------------------------ #
# what each sign is called in the window (never the text that matched)
STATEMENT_SIGNS = {
    "account_number": "an account number",
    "balance": "an account value or balance",
    "address": "a name and address",
    "statement": "a statement period or \"your account\" wording",
}
_ACCT_NUMBER = re.compile(
    r"(?i)\b(?:account|acct\.?|a/c)\s*(?:number|no\.?|#|num\.?)?\s*[:#]?\s*"
    # one mask character per repeat: "(?:[X*•]+[\-\s]?)*" matched the same
    # text, but a long run of X's or stars with no digits after took
    # exponential time (the whole app waits on it)
    r"(?:[X*•][\-\s]?)*\d{2,}[\d\-]*\d{2,}"
    r"|\b(?:account|acct\.?)\s*(?:number|no\.?|#)\s*[:#]?\s*(?=[A-Z\-]*\d)[A-Z0-9][A-Z0-9\-]{3,}"
    r"|(?<![\w-])(?:[X*•]{2,}[\-\s]?){1,4}\d{3,4}\b")
_BALANCE = re.compile(
    r"(?i)\b(?:(?:total\s+|your\s+|ending\s+|beginning\s+|closing\s+|opening\s+)?account\s+"
    r"(?:value|balance)|your\s+(?:balance|account\s+value|portfolio\s+value|holdings|"
    r"vested\s+balance)|(?:ending|beginning|closing|opening|current|total|vested)\s+balance|"
    r"market\s+value\s+of\s+your|net\s+account\s+value)\b")
_STATEMENT_WORDS = re.compile(
    r"(?i)\b(?:statement\s+(?:period|date|for)|account\s+statement|(?:quarterly|monthly|"
    r"annual)\s+statement|your\s+account|account\s+(?:holder|owner|summary|type)|"
    r"prepared\s+for|participant\s+(?:name|id)|social\s+security|dear\s+[A-Z][a-z]+)\b")
_CITY_ZIP = re.compile(r"^[A-Za-z][A-Za-z .'-]+,?\s+[A-Z]{2}\s+\d{5}(?:-\d{4})?\s*$")
_STREET = re.compile(r"(?i)^(?:\d+[A-Z]?\s+[\w .'-]+\b(?:st|street|ave|avenue|rd|road|blvd|"
                     r"boulevard|ln|lane|dr|drive|ct|court|way|pl|place|cir|circle|pkwy|"
                     r"parkway|ter|terrace|hwy|highway|trl|trail)\.?|p\.?\s*o\.?\s+box\s+\d+)"
                     r"\b.*$")
_ORG_WORDS = re.compile(r"(?i)\b(?:fund|funds|investments?|group|inc|llc|lp|company|co|corp|"
                        r"corporation|trust|management|distributors?|services|securities|"
                        r"advisors?|advisers?|capital|partners|bank|financial|asset|assets|"
                        r"global|street|the|address|contact|mail|mailing|phone|write|call|"
                        r"visit|office|headquarters|by|to|us|for)\b")
_PERSON = re.compile(r"^(?:(?:Mr|Mrs|Ms|Mx|Dr)\.?\s+)?[A-Z][a-z'-]+(?:\s+[A-Z]\.?)?"
                     r"(?:\s+[A-Z][a-z'-]+){1,2}(?:\s*(?:&|and)\s*[A-Z][a-z'-]+"
                     r"(?:\s+[A-Z][a-z'-]+)?)?$")


def _lines(text: str) -> list[str]:
    return [" ".join(raw.replace("\u00a0", " ").split())
            for raw in str(text or "")[:MAX_CHARS].splitlines()]


def _address_block(lines: list[str]) -> bool:
    """A person's name, a street line and a "City, ST 12345" line one under
    another - the address block at the top of a statement. A fund company's
    own address ("The Example Group, 100 Example Blvd, ...") isn't one: the
    line above the street must look like a person's name."""
    rows = [x for x in lines if x]
    for i, line in enumerate(rows):
        if not _CITY_ZIP.match(line):
            continue
        for j in (i - 1, i - 2):
            if j < 1 or not _STREET.match(rows[j]):
                continue
            above = rows[j - 1]
            if _PERSON.match(above) and not _ORG_WORDS.search(above):
                return True
    return False


def looks_like_statement(text: str) -> list[str]:
    """The kinds of statement signs in the text (STATEMENT_SIGNS keys, in a
    fixed order), or [] for text that reads like a fact sheet. Only the kinds
    are returned - never what matched."""
    t = str(text or "")[:MAX_CHARS]
    found = []
    if _ACCT_NUMBER.search(t):
        found.append("account_number")
    if _BALANCE.search(t):
        found.append("balance")
    if _address_block(_lines(t)):
        found.append("address")
    if _STATEMENT_WORDS.search(t):
        found.append("statement")
    # "your account" wording alone is a sign but not enough by itself (a fact
    # sheet may say "before you add it to your account"): it needs another
    return found if (set(found) - {"statement"}) or len(found) > 1 else []


# ---- reading labels and values ----------------------------------------------- #
_LABELS = {
    "name": r"(?:fund|portfolio)\s+name|name\s+of\s+(?:the\s+)?fund",
    "ticker": r"(?:ticker|trading)\s*(?:symbol)?|symbol|(?:nasdaq|nyse(?:\s+arca)?|"
              r"cboe(?:\s+bzx)?)\s*(?:symbol|ticker)?",
    "fee": r"(?:total\s+|net\s+|gross\s+)?(?:annual\s+)?(?:fund\s+)?(?:operating\s+)?"
           r"expenses?(?:\s+ratio)?(?:\s*\((?:gross\s*/\s*net|net\s*/\s*gross|net|gross)\))?"
           r"|(?:net|gross)\s+expense\s+ratio|exp\.?\s*ratio|gross\s*/\s*net\s+expense\s+ratio",
    "asset_class": r"(?:morningstar\s+)?category|asset\s+class|fund\s+(?:type|category)|"
                   r"investment\s+(?:type|category)",
    "holdings": r"(?:total\s+)?(?:number|no\.?|#)\s*of\s+(?:holdings|stocks|bonds|securities|"
                r"issues|positions|companies)|(?:holdings|positions)\s+count",
    "top_share": r"(?:%\s*(?:of\s+)?(?:the\s+)?(?:fund|portfolio|(?:net\s+|total\s+)?assets)\s+"
                 r"in\s+)?(?:the\s+)?top\s+(?:10|ten|five|5|25|twenty[\s-]five)\s+holdings"
                 r"(?:\s+as\s+(?:a\s+)?%\s+of\s+(?:total\s+|net\s+)*(?:assets|portfolio|fund))?"
                 r"(?:\s*\(%\s*of\s+(?:total\s+|net\s+)*(?:assets|portfolio|fund)\))?"
                 r"|concentration\s+in\s+top\s+(?:10|ten)",
    "inception": r"(?:fund\s+|share\s+class\s+|class\s+)?inception(?:\s+date)?|date\s+of\s+"
                 r"inception|launch\s+date|commencement\s+of\s+operations",
    "benchmark": r"(?:primary\s+|fund\s+|the\s+fund'?s\s+)?benchmark(?:\s+index)?|"
                 r"(?:target|underlying|tracking)\s+index|index\s+tracked",
}
_LABEL_RE = {k: re.compile(r"(?i)^\s*(" + v + r")\s*(?:[:\-–—|=]\s*|\s+|$)")
             for k, v in _LABELS.items()}
_LABEL_ONLY = {k: re.compile(r"(?i)^\s*(?:" + v + r")\s*:?\s*$") for k, v in _LABELS.items()}


def _cells(line: str) -> list[str]:
    """A line's columns: tabs, pipes, or runs of two or more spaces (the
    lines are joined with single spaces only after this)."""
    if "\t" in line:
        cells = line.split("\t")
    elif "|" in line:
        cells = line.split("|")
    else:
        cells = re.split(r"\s{2,}", line)
    return [c.strip() for c in cells if c.strip()]


def _label_of(cell: str) -> str | None:
    for field, rx in _LABEL_ONLY.items():
        if rx.match(cell):
            return field
    return None


def pairs(text: str) -> list[tuple[str, str, str]]:
    """Every (field, label as written, value as written) the text gives, in
    order, from four layouts: "Label: value" on one line, a label alone on
    its line with the value under it, label and value side by side in
    columns, and a row of labels with a row of values under it."""
    raw = [raw.replace("\u00a0", " ").rstrip() for raw in str(text or "")[:MAX_CHARS].splitlines()]
    raw = [r for r in raw if r.strip()]
    out: list[tuple[str, str, str]] = []
    used_as_value: set[int] = set()
    for i, line in enumerate(raw):
        if i in used_as_value:
            continue
        cells = _cells(line)
        nxt = raw[i + 1] if i + 1 < len(raw) else ""
        nxt_cells = _cells(nxt) if nxt else []
        labels = [_label_of(c) for c in cells]
        # a row of labels with a row of values under it
        if len(cells) >= 2 and all(labels) and len(nxt_cells) == len(cells) \
                and not any(_label_of(c) for c in nxt_cells):
            out += [(f, c, v) for f, c, v in zip(labels, cells, nxt_cells)]
            used_as_value.add(i + 1)
            continue
        # a label alone on its line, the value under it
        if len(cells) == 1 and labels[0]:
            if nxt and not any(_label_of(c) for c in nxt_cells) \
                    and not any(rx.match(nxt) for rx in _LABEL_RE.values()):
                out.append((labels[0], cells[0], " ".join(nxt.split())))
                used_as_value.add(i + 1)
            continue
        # labels and values side by side in columns, or "Label: value" in a
        # column (or on the whole line)
        k = 0
        while k < len(cells):
            if labels[k] and k + 1 < len(cells) and not labels[k + 1]:
                out.append((labels[k], cells[k], cells[k + 1]))
                k += 2
                continue
            flat = " ".join(cells[k].split())
            for field, rx in _LABEL_RE.items():
                m = rx.match(flat)
                if m and flat[m.end():].strip():
                    out.append((field, m.group(1), flat[m.end():].strip()))
                    break
            k += 1
    return out


# ---- each field -------------------------------------------------------------- #
_PCT_ANY = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d+)?|\.\d+)\s?%")
_INT = re.compile(r"(?<![\d.,/])(\d{1,3}(?:,\d{3})+|\d{1,6})(?![\d.,]*\d)(?!\s?%)(?!/)")
_DATE = re.compile(
    r"(?i)\b(\d{1,2}/\d{1,2}/(?:19|20)\d{2}|(?:19|20)\d{2}-\d{2}-\d{2}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+"
    r"(?:19|20)\d{2}|\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"[a-z]*\.?,?\s+(?:19|20)\d{2}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
    r"[a-z]*\.?\s+(?:19|20)\d{2}|(?:19|20)\d{2})\b")
_NOT_TICKERS = {"CUSIP", "ISIN", "SEDOL", "NASDAQ", "NYSE", "ARCA", "CBOE", "BZX", "CLASS",
                "SHARE", "SHARES", "ADMIRAL", "INVESTOR", "SYMBOL", "TICKER"}
_TICKER_TOKEN = re.compile(r"(?<![A-Za-z0-9])([A-Z]{1,5})(?![A-Za-z0-9])")
_EXCHANGE_TICKER = re.compile(r"\b(?:NASDAQ|NYSE(?:\s+Arca)?|Cboe(?:\s+BZX)?)\s*:\s*([A-Z]{1,5})\b")
_NAME_WORDS = re.compile(r"(?i)\b(?:fund|etf|portfolio|trust|index|shares|series)\b")
_NOT_A_NAME = re.compile(
    r"(?i)^(?:fact\s*sheet|fund\s+(?:facts?|overview|information|details|profile|"
    r"highlights)|key\s+facts|as\s+of|data\s+as\s+of|quarterly|monthly|for\s+use|"
    r"the\s+fund|this\s+fund|it\s+|seeks|investment\s+objective|objective|strategy|"
    r"performance|top\s+(?:10|ten)|portfolio\s+(?:composition|characteristics|holdings)|"
    r"holdings|important|before\s+investing|risk|you\s+could|an\s+investment|"
    r"shares\s+of|fund\s+name)")


def _fee(found: list, lines: list[str]) -> dict:
    """{"fee", "gross", "said"}: the expense ratio as a fraction (net before
    an unlabelled one before gross), the gross one when it differs, and the
    words the sheet used for it."""
    picks = {"net": None, "any": None, "gross": None}
    said = None
    for field, label, value in found:
        if field != "fee":
            continue
        text = f"{label} {value}"
        lower = label.lower()
        both = re.search(r"(?i)gross\s*/\s*net|net\s*/\s*gross", text)
        kind = None if both else ("net" if "net" in lower else
                                  "gross" if "gross" in lower else "any")
        if both:
            net = md.fees_in(text)
            if net is not None and picks["net"] is None:
                picks["net"], said = net, said or label
            nums = [md._as_fee(m.group(1)) for m in _PCT_ANY.finditer(value)]
            nums = [n for n in nums if n is not None]
            if len(nums) == 2 and picks["gross"] is None:
                picks["gross"] = nums[0] if re.search(r"(?i)gross\s*/", text) else nums[1]
            continue
        m = _PCT_ANY.search(value)
        v = md._as_fee(m.group(1)) if m else None
        if v is not None and picks[kind] is None:
            picks[kind] = v
            said = said or label
    if all(v is None for v in picks.values()):   # "The fund's expense ratio is 0.04%."
        for line in lines:
            v = md.fees_in(line)
            if v is not None:
                picks["any"], said = v, "expense ratio"
                break
    fee = next((picks[k] for k in ("net", "any", "gross") if picks[k] is not None), None)
    gross = picks["gross"] if picks["gross"] is not None and fee is not None \
        and abs(picks["gross"] - fee) >= 0.00005 else None
    return {"fee": fee, "gross": gross, "said": said}


def _clean_name(line: str) -> str:
    t = md._MARKS.sub("", line)
    t = re.sub(r"\(\s*[A-Z]{1,5}\s*\)", " ", t)
    t = re.split(r"\s+[|•·]\s+|\s+[-–—]\s+(?=(?i:fact\s*sheet|fund\s+facts|quarterly|monthly|"
                 r"as\s+of|q[1-4]\b|data\b))", t)[0]
    t = re.sub(r"(?i)\s*\bfact\s*sheet\b.*$", "", t)
    return " ".join(t.split()).strip(" -–—:;,|")


def _name(found: list, lines: list[str]) -> str | None:
    for field, _label, value in found:
        if field == "name":
            return _clean_name(value) or None
    for line in [x for x in lines if x][:15]:
        if len(line) < 6 or len(line) > 120 or "%" in line or _NOT_A_NAME.match(line):
            continue
        if any(rx.match(line) for rx in _LABEL_RE.values()):
            continue
        if line.rstrip().endswith(".") or not _NAME_WORDS.search(line):
            continue
        if not line[0].isupper() and not line[0].isdigit():
            continue
        name = _clean_name(line)
        if name and _NAME_WORDS.search(name):
            return name
    return None


def _tickers(found: list, lines: list[str]) -> list[str]:
    out: list[str] = []

    def add(sym):
        if sym not in md.NOT_TICKERS and sym not in _NOT_TICKERS and sym not in out \
                and len(sym) >= 2:
            out.append(sym)
    for field, _label, value in found:
        if field == "ticker":
            for m in _TICKER_TOKEN.finditer(value):
                add(m.group(1))
    for line in lines[:15]:   # "(FXAIX)" beside the name at the top
        if _NAME_WORDS.search(line):
            for m in md._PAREN_TICKER.finditer(line):
                add(m.group(1))
    for line in lines:
        for m in _EXCHANGE_TICKER.finditer(line):
            add(m.group(1))
    return out[:6]


_INDEX_WORDS = re.compile(r"(?i)\b(?:seeks?\s+to\s+track|designed\s+to\s+track|tracks?\s+the\s+"
                          r"(?:performance|investment\s+results|return)|track\s+the\s+"
                          r"(?:performance|investment\s+results)|passively\s+managed|"
                          r"index[\s-](?:tracking|sampling|replication)|replicat\w*\s+the\s+"
                          r"(?:index|performance)|employs\s+an\s+indexing|indexing\s+"
                          r"(?:approach|strategy|investment\s+approach))\b")
_ACTIVE_WORDS = re.compile(r"(?i)\b(?:actively\s+managed|active(?:ly)?\s+manage(?:s|d)?|"
                           r"active\s+management|seeks?\s+to\s+(?:outperform|beat)|"
                           r"(?:portfolio\s+)?managers?\s+(?:select|choose|pick)s?|"
                           r"bottom-up|stock\s+selection|security\s+selection)\b")


def _management(name: str | None, lines: list[str]) -> dict:
    """{"kind": "index" / "active" / None, "from": "sheet" / "name" / None}."""
    text = " ".join(lines)
    idx, act = bool(_INDEX_WORDS.search(text)), bool(_ACTIVE_WORDS.search(text))
    if idx != act:
        return {"kind": "index" if idx else "active", "from": "sheet"}
    if not idx and md.is_index(name or ""):
        return {"kind": "index", "from": "name"}
    return {"kind": None, "from": None}


def _kind_from_class(stated: str) -> str | None:
    """A kind from an asset-class line in words fact sheets use ("Domestic
    Stock - General", "Fixed Income", "Balanced"); None when it's unclear."""
    s = " " + stated.lower().replace("u.s.", "us") + " "
    if any(w in s for w in ("fixed income", " bond", "treasury", "municipal")):
        return "bond"
    if any(w in s for w in ("balanced", "multi-asset", "multi asset", "hybrid", "allocation")):
        return "balanced"
    if any(w in s for w in ("real estate", "commodit", "sector", "specialty")):
        return "sector"
    stockish = any(w in s for w in (" stock", "equit"))
    if stockish and any(w in s for w in ("international", "foreign", "non-us", "emerging",
                                         "developed")):
        return "intl_stock"
    if stockish and any(w in s for w in ("domestic", " us ", "u s ", "american")):
        return "us_stock"
    if stockish:
        return "stock"
    return None


def _asset_class(found: list, name: str | None) -> dict:
    """{"stated": the sheet's own category, "kind": a menu_decoder.KINDS key
    or None, "from": "sheet" / "name" / None}."""
    stated = next((v for f, _label, v in found if f == "asset_class"), None)
    if stated:
        stated = " ".join(stated.split())[:80]
        k = md.kind_from_name(stated) or fees.kind_of(stated, None) or _kind_from_class(stated)
        if k not in md.KINDS:
            k = None
        return {"stated": stated, "kind": k, "from": "sheet"}
    k = md.kind_from_name(name or "") or fees.kind_of(None, name or "")
    if k in md.KINDS:
        return {"stated": None, "kind": k, "from": "name"}
    return {"stated": None, "kind": None, "from": None}


_BARE_WORDS = re.compile(r"(?i)\b(?:of|in|the|net|total|assets?|portfolio|fund|as|a|approx|"
                         r"approximately|about|stocks?|bonds?|holdings|securities|issues|"
                         r"positions|companies)\b")


def _bare(value: str) -> bool:
    """A value that is only a number (with a few words like "of net assets")
    - not the first row of a list ("Example Co. 7.1%") under a heading."""
    return not re.search(r"[A-Za-z]", _BARE_WORDS.sub(" ", value))


def _top_share(found: list) -> dict | None:
    words = {"ten": 10, "five": 5, "twenty-five": 25, "twenty five": 25}
    for field, label, value in found:
        if field != "top_share" or not _bare(value):
            continue
        m = _PCT_ANY.search(value)
        if not m:
            continue
        v = float(m.group(1))
        if 0 < v <= 100:
            n = re.search(r"(?i)top\s+(10|ten|five|5|25|twenty[\s-]five)", label)
            count = n.group(1).lower() if n else "10"
            return {"pct": v, "of": int(count) if count.isdigit() else words.get(count, 10)}
    return None


def _holdings(found: list) -> int | None:
    for field, _label, value in found:
        if field != "holdings" or not _bare(value):
            continue
        m = _INT.search(value)
        if m:
            n = int(m.group(1).replace(",", ""))
            if 0 < n < 1_000_000:
                return n
    return None


def _inception(found: list) -> str | None:
    for field, _label, value in found:
        if field == "inception":
            m = _DATE.search(value)
            if m:
                return m.group(1)
    return None


def _year_of(stated: str | None) -> int | None:
    m = re.search(r"(?:19|20)\d{2}", stated or "")
    return int(m.group(0)) if m else None


def _benchmark(found: list) -> str | None:
    for field, _label, value in found:
        if field == "benchmark":
            v = " ".join(value.split()).strip(" -–—:;,|")
            v = re.split(r"\s{2,}|\t", v)[0]
            if re.search(r"[A-Za-z]{2}", v) and not re.fullmatch(r"(?i)n/?a|none|-+", v):
                return v[:120]
    return None


# ---- the whole sheet --------------------------------------------------------- #
def decode(text: str) -> dict:
    """{"statement": [sign kinds] - when non-empty, nothing else is read and
    nothing from the text is returned; else "found" (how many FIELDS were
    found), "name", "tickers", "fee", "gross", "fee_said", "management",
    "asset_class", "top_share", "holdings", "inception", "benchmark",
    "truncated"}."""
    signs = looks_like_statement(text)
    if signs:
        return {"statement": signs}
    lines = _lines(text)
    found = pairs(text)
    name = _name(found, lines)
    fee = _fee(found, lines)
    out = {"statement": [], "name": name, "tickers": _tickers(found, lines),
           "fee": fee["fee"], "gross": fee["gross"], "fee_said": fee["said"],
           "management": _management(name, lines), "asset_class": _asset_class(found, name),
           "top_share": _top_share(found), "holdings": _holdings(found),
           "inception": _inception(found), "benchmark": _benchmark(found),
           "truncated": len(str(text or "")) > MAX_CHARS}
    out["found"] = sum(1 for f in FIELDS if _has(out, f))
    return out


def _has(r: dict, field: str) -> bool:
    if field == "ticker":
        return bool(r["tickers"])
    if field == "management":
        return r["management"]["kind"] is not None
    if field == "asset_class":
        return bool(r["asset_class"]["stated"] or r["asset_class"]["kind"])
    return r.get(field) is not None


def _a_kind(label: str) -> str:
    """'US stock fund' -> 'a US stock fund', 'International stock fund' ->
    'an international stock fund'."""
    if len(label) > 1 and label[1].islower():
        label = label[0].lower() + label[1:]
        return ("an " if label[0] in "aeiou" else "a ") + label
    return "a " + label   # "a US stock fund"


def _pct(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return s + "%"


def rows(result: dict, monthly=None, today: date | None = None) -> list[dict]:
    """The window's table: one dict per field in FIELDS' fixed order -
    {"What": label, "As the fact sheet states it": value or NOT_FOUND,
    "What this means": the general line, plus a specific one where there's
    something to add}. Never sorted, ranked or marked."""
    today = today or date.today()
    out = []
    for field in FIELDS:
        label, means = ROWS[field]
        value, extra = None, ""
        if field == "name":
            value = result["name"]
        elif field == "ticker" and result["tickers"]:
            value = ", ".join(result["tickers"])
            if len(result["tickers"]) > 1:
                extra = "The sheet lists more than one - usually one per share class."
        elif field == "fee" and result["fee"] is not None:
            value = fees.fmt_ratio(result["fee"]) + " a year"
            if result["gross"] is not None:
                value += f" (before any fee waiver: {fees.fmt_ratio(result['gross'])})"
            per100 = result["fee"] * 10000
            extra = (f"That's {md.fmt_dollars(per100)} a year for every $10,000 in the fund.")
            dollars = md.yearly_dollars(monthly, result["fee"])
            if dollars is not None:
                extra += (f" On a year of {md.fmt_dollars(float(monthly))} a month, about "
                          f"{md.fmt_dollars(dollars)}.")
        elif field == "management" and result["management"]["kind"]:
            k = result["management"]["kind"]
            value = MANAGEMENT[k][0]
            if result["management"]["from"] == "name":
                value += " (going by its name)"
            extra = MANAGEMENT[k][1]
        elif field == "asset_class" and (result["asset_class"]["stated"]
                                         or result["asset_class"]["kind"]):
            a = result["asset_class"]
            kind_text = md.KINDS[a["kind"]][0] if a["kind"] else None
            if a["stated"]:
                value = a["stated"]
                if kind_text and kind_text.lower() != a["stated"].lower():
                    value += f" ({_a_kind(kind_text)})"
            else:
                value = f"{kind_text} (going by its name)"
            if a["kind"]:
                extra = md.KINDS[a["kind"]][1]
        elif field == "top_share" and result["top_share"]:
            t = result["top_share"]
            value = f"{_pct(t['pct'])} in its top {t['of']}"
        elif field == "holdings" and result["holdings"] is not None:
            value = f"{result['holdings']:,}"
        elif field == "inception" and result["inception"]:
            value = result["inception"]
            year = _year_of(value)
            if year and year <= today.year:
                age = today.year - year
                extra = ("It started this year." if age == 0 else
                         f"That's about {age} year{'s' if age != 1 else ''} ago.")
        elif field == "benchmark" and result["benchmark"]:
            value = result["benchmark"]
        out.append({"What": label, "As the fact sheet states it": value or NOT_FOUND,
                    "What this means": f"{means} {extra}".strip()})
    return out


def statement_signs_text(signs: list[str]) -> str:
    """'an account number and an account value or balance' - the kinds only."""
    words = [STATEMENT_SIGNS[s] for s in signs if s in STATEMENT_SIGNS]
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]
