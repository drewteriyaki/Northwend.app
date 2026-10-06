"""Read holdings out of text pasted from a brokerage's website.

People select the positions table on their brokerage's site, copy it, and
paste it. What arrives depends on the site:
- a table with a header row (tab- or space-separated): read by the same
  engine as uploaded CSVs (csv_import.py), so both share one list of column
  names and one set of rules;
- one cell per line, or a list someone typed ("VTI 10"): read here, from
  each symbol line and the numbers after it.
Either way only symbols, share counts, cost (or % of portfolio) and cash are
kept; names, prices, balances, gains and account numbers are dropped.

No AI and no network - it's plain text matching, so pasted text never
leaves the app. Results fill the hand-entry review form (manual_entry.py),
where every row is checked, and priced, before anything is saved.
"""

from __future__ import annotations

import re

import csv_import
from csv_import import _is_ticker

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


MAX_CHARS = 50_000   # the paste box's limit (audit 1.3b); a positions table is far less
TOO_LONG = ("That's more text than Northwend reads at once (50,000 characters). Copy just "
            "the positions table, or paste one account at a time.")


def parse(text: str) -> dict:
    """{"holdings": [{"Symbol", "Shares", "Total cost", "Percent"}], "cash":
    float | None, "mode": "Shares" | "Percentages", "ignored_lines": int}.
    The same symbol twice (in two accounts) is combined. Text longer than
    MAX_CHARS isn't read at all ("too_long": True), rather than cut mid-row."""
    if len(text or "") > MAX_CHARS:
        return {"holdings": [], "cash": None, "mode": "Shares", "ignored_lines": 0,
                "too_long": True}
    lines =[ln.replace(" ", " ").rstrip() for ln in (text or "").replace("\r", "").split("\n")]
    lines = [ln for ln in lines if ln.strip()]
    table = _as_table(lines)
    rows = table["holdings"] if table else _scan(lines)
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
    cash = round(sum(table["cash"].values()), 2) or None if table else _cash(lines)
    return {"holdings": holdings, "cash": cash, "mode": mode,
            "ignored_lines": max(0, len(lines) - len(holdings))}


def _as_table(lines: list[str]) -> dict | None:
    """The pasted text read as a table by the CSV engine - when it has a header
    row the engine recognizes - else None (then it's read line by line)."""
    rows = [_cells(line) for line in lines]
    header_i, problem = csv_import.find_header(rows)
    if header_i is None:
        return None
    mapping = csv_import.auto_mapping(rows[header_i])
    if not csv_import.usable(mapping):
        return None
    found = csv_import.parse(rows, mapping)
    return found if found["holdings"] else None
