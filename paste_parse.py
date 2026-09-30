"""Read holdings out of text pasted from a brokerage's website.

People select the positions table on their brokerage's site, copy it, and
paste it. What arrives depends on the site: a tab-separated table with a
header row, one cell per line, or a list someone typed ("VTI 10"). This
module finds each holding's symbol and share count (or % of portfolio),
plus cost when a header names that column, and cash. It keeps nothing else:
names, prices, balances, gains and account numbers are dropped here.

No AI and no network - it's plain text matching, so pasted text never
leaves the app. Results fill the hand-entry review form (manual_entry.py),
where every row is checked, and priced, before anything is saved.
"""

from __future__ import annotations

import re

# ticker-shaped: 1-5 capitals, optional class suffix (BRK.B, BF-B)
_TICKER_RE = re.compile(r"^[A-Z]{1,5}(?:[.\-][A-Z]{1,2})?$")
# capitalised words a table shows that aren't tickers
_NOT_TICKERS = {
    "CASH", "TOTAL", "TOTALS", "USD", "ETF", "ETFS", "NA", "ACCT", "QTY", "PRICE", "VALUE",
    "COST", "GAIN", "LOSS", "DAY", "TODAY", "SHARE", "SHARES", "BUY", "SELL", "HOLD", "NEW",
    "ALL", "YTD", "MTD", "AVG", "MKT", "IRA", "ROTH", "SEP", "FUND", "FUNDS", "INC", "CORP",
    "LLC", "LTD", "TRUST", "CLASS", "AND", "THE", "OF", "FOR", "MY", "DIV", "EST", "APR", "APY",
    "USA", "US", "NAME", "TYPE", "VIEW", "MORE", "LESS", "SORT", "EDIT", "TRADE", "OPEN",
    "CLOSE", "HIGH", "LOW", "LAST", "CHANGE", "CHG", "PCT", "YIELD", "ACCOUNT", "SYMBOL",
    "PENDING", "MARGIN", "CORE", "SWEEP", "OTHER", "STOCK", "STOCKS", "BOND", "BONDS", "OPTION",
    "OPTIONS", "SPDR", "PLC", "NV", "SA", "AG", "CO", "LP", "ADR", "ETN", "CEF", "REIT", "NYSE",
    "AMEX", "OTC", "IPO", "EPS", "PE", "N", "A", "I", "Y",
}

# header cell text -> field (matched lowercase, punctuation-insensitive)
_HEADERS = {
    "symbol": ("symbol", "ticker", "symbol/cusip", "sym"),
    "quantity": ("quantity", "qty", "shares", "shares owned", "units", "quantity/shares",
                 "share count", "position", "qty (shares)"),
    "cost": ("cost basis", "cost basis total", "total cost", "cost", "total cost basis",
             "cost basis ($)", "book value"),
    "percent": ("% of account", "% of portfolio", "percent", "weight", "allocation",
                "% of holdings", "portfolio %", "% of acct", "% of total", "percent of account",
                "% portfolio", "portfolio weight"),
}

_NUM_RE = re.compile(r"^\(?[-+]?\$?\(?[-+]?\d[\d,]*(?:\.\d+)?\)?%?\)?$")
_CASH_WORDS = ("cash", "money market", "sweep", "core position")


def _cells(line: str) -> list[str]:
    """A line's cells: tabs if it has them, else runs of 2+ spaces, else words."""
    if "\t" in line:
        return [c.strip() for c in line.split("\t")]
    parts = re.split(r"\s{2,}", line.strip())
    return parts if len(parts) > 1 else line.split()


def _number(tok: str):
    """(kind, value) for a number token: kind is 'plain', 'dollar' or 'pct';
    None for anything else. Signed percents (day change) count as 'change'."""
    t = tok.strip()
    if not t or not _NUM_RE.match(t):
        return None
    neg = t.startswith("-") or t.startswith("(") or t.startswith("-$")
    signed = t[0] in "+-"
    kind = "pct" if t.endswith("%") or t.endswith("%)") else ("dollar" if "$" in t else "plain")
    try:
        v = float(re.sub(r"[^\d.]", "", t))
    except ValueError:
        return None
    if kind == "pct" and signed:
        kind = "change"
    return kind, (-v if neg else v)


def _is_ticker(tok: str) -> bool:
    return bool(_TICKER_RE.match(tok)) and tok not in _NOT_TICKERS


def _field_of(cell: str):
    c = re.sub(r"\s+", " ", cell.strip().lower().replace(" ", " "))
    for field, names in _HEADERS.items():
        if c in names:
            return field
    return None


def _tabular(lines: list[str]) -> list[dict] | None:
    """Rows from a table with a header row naming its columns, else None."""
    for hi, line in enumerate(lines):
        cells = _cells(line)
        cols = {}
        for i, c in enumerate(cells):
            f = _field_of(c)
            if f and f not in cols:
                cols[f] = i
        if "symbol" not in cols or not ({"quantity", "percent"} & set(cols)):
            continue
        rows = []
        for line2 in lines[hi + 1:]:
            cells2 = _cells(line2)
            if len(cells2) <= cols["symbol"]:
                continue
            sym = cells2[cols["symbol"]].strip().upper().rstrip("*")
            if not _is_ticker(sym):
                continue

            def val(field, kinds):
                i = cols.get(field)
                if i is None or i >= len(cells2):
                    return None
                n = _number(cells2[i])
                return n[1] if n and n[0] in kinds else None
            rows.append({"Symbol": sym, "Shares": val("quantity", ("plain", "dollar")),
                         "Total cost": val("cost", ("dollar", "plain")),
                         "Percent": val("percent", ("pct", "plain"))})
        if rows:
            return rows
    return None


def _row_start(cells: list[str]) -> str | None:
    """The symbol if this line begins a holding: the line is just a ticker, or a
    ticker followed only by numbers, 'shares', or tab-separated cells."""
    if not cells:
        return None
    first = cells[0].strip().rstrip("*")
    rest = [c for c in cells[1:] if c.strip()]
    sym = first.upper() if (first.islower() and rest) else first
    if not _is_ticker(sym):
        return None
    if not rest:
        return sym
    numericish = all(_number(c) or c.lower() in ("shares", "share", "sh", "shs") for c in rest)
    return sym if numericish or len(cells) > 2 else None


def _scan(lines: list[str]) -> list[dict]:
    """Rows from free-form text: each symbol line, and the numbers after it."""
    starts = [(i, _row_start(_cells(line))) for i, line in enumerate(lines)]
    starts = [(i, s) for i, s in starts if s]
    rows = []
    for k, (i, sym) in enumerate(starts):
        end = starts[k + 1][0] if k + 1 < len(starts) else min(len(lines), i + 9)
        end = min(end, i + 9)
        shares = pct = None
        strong = None
        for j, line in enumerate(lines[i:end]):
            toks = _cells(line)[1:] if j == 0 else _cells(line)
            m = re.search(r"([\d,]*\.?\d+)\s*(?:shares?|sh|shs)\b", line, re.I)
            if m and strong is None:
                strong = float(m.group(1).replace(",", ""))
            for tok in toks:
                n = _number(tok)
                if not n:
                    continue
                if n[0] == "plain" and shares is None:
                    shares = n[1]
                elif n[0] == "pct" and pct is None:
                    pct = n[1]
        rows.append({"Symbol": sym, "Shares": strong if strong is not None else shares,
                     "Total cost": None, "Percent": pct})
    return rows


def _cash(lines: list[str]) -> float | None:
    """Cash from lines like 'Cash & Money Market  $1,234.56'."""
    total, found = 0.0, False
    for i, line in enumerate(lines):
        low = line.lower()
        if not any(w in low for w in _CASH_WORDS) or _row_start(_cells(line)):
            continue
        for tok in _cells(line) + (_cells(lines[i + 1]) if i + 1 < len(lines) else []):
            n = _number(tok)
            if n and n[0] == "dollar" and n[1] > 0:
                total += n[1]
                found = True
                break
    return round(total, 2) if found else None


def parse(text: str) -> dict:
    """{"holdings": [{"Symbol", "Shares", "Total cost", "Percent"}], "cash":
    float | None, "mode": "Shares" | "Percentages", "ignored_lines": int}.
    The same symbol twice (in two accounts) is combined."""
    lines = [ln.replace(" ", " ").rstrip() for ln in (text or "").replace("\r", "").split("\n")]
    lines = [ln for ln in lines if ln.strip()]
    rows = _tabular(lines) or _scan(lines)
    merged: dict = {}
    for r in rows:
        if r["Shares"] is None and r["Percent"] is None:
            continue
        m = merged.setdefault(r["Symbol"], {"Symbol": r["Symbol"], "Shares": None,
                                            "Total cost": None, "Percent": None})
        for k in ("Shares", "Total cost", "Percent"):
            if r[k] is not None:
                m[k] = (m[k] or 0.0) + r[k]
    holdings = list(merged.values())
    with_shares = [h for h in holdings if h["Shares"]]
    mode = "Shares" if with_shares or not holdings else "Percentages"
    if mode == "Shares":
        holdings = with_shares
    return {"holdings": holdings, "cash": _cash(lines), "mode": mode,
            "ignored_lines": max(0, len(lines) - len(holdings))}
