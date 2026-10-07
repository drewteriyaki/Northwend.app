"""This month's world, for your mix (ROADMAP Phase C, R12's second renewable
content source; flag `month_world`). Pure content and logic, no Streamlit,
no database.

The owner writes one short note a month: what happened in the world last
month, in plain words - PAST facts only, never a forecast - and a line or
two on what it meant for someone with mostly stocks, bonds or cash. Every
note is reviewed (LEGAL_GATES.md section 6, L3) before it's published: it
shows only once `reviewed_by` and `reviewed_on` are filled in. How to write
one: docs/RUNBOOK.md, "Writing this month's world".

Where it shows: one line inside the preparedness drill card on Home
(views/month_world.py, drawn by views/drills.py), with a button to open it.
A note shows only in its own month and the month after (current()), and
only while it passes problems() - the same checks the tests run over NOTES,
so a note with a forecast word, a ticker or an unofficial source fails CI
before it ships and never shows even if it slipped through.

The person's own mix (asset classes in whole percents, from allocation.py)
picks which "for someone with mostly ..." lines show: their largest class,
and the next one too when it's a real part of the mix (lines_for()).
Someone with no holdings yet sees the general paragraphs only. Northwend has
no data on where a fund's companies are based (allocation.py), so the lines
are by asset class only - no US / international split.

What's kept (prefs PREF): the months whose note the person opened - keys
only, the newest KEEP of them. Never sent to the AI; drawn only on the
login's own account (never while an advisor is in a client's account). The
opt-in Trail Conditions email may say there's a new note (trail_conditions.WORLD),
a fixed line with nothing from the note in it.
"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlparse

import brokerages

PREF = "month_world_seen"   # user_prefs key: ["2026-09", "2026-10"] - months opened
KEEP = 6

# the "for someone with mostly ..." lines: asset_classes.CLASSES' own classes,
# in lower case ("Other" has no line: it's too mixed to say anything about)
CLASS_KEYS = {"stocks": "Stocks", "bonds": "Bonds", "cash": "Cash"}
CLASS_WORDS = {"stocks": "mostly stocks", "bonds": "mostly bonds", "cash": "mostly cash"}
SECOND_AT = 25   # the next-largest class's line shows too from this share (whole %)

# every source is an official or primary one - government sites only
OFFICIAL_SITES = (
    "www.federalreserve.gov",    # the Federal Reserve Board
    "www.bls.gov",               # the Bureau of Labor Statistics
    "www.bea.gov",               # the Bureau of Economic Analysis
    "home.treasury.gov",         # the US Treasury
    "www.treasurydirect.gov",    # the Treasury's savings bonds and auctions
    "fiscaldata.treasury.gov",   # the Treasury's published data
    "www.sec.gov",               # the Securities and Exchange Commission
    "www.investor.gov",          # the SEC's investor education site
    "www.fdic.gov",              # the Federal Deposit Insurance Corporation
)

# words a note never uses: forecasts, advice and trades (the checks below,
# case-insensitive, whole words)
BANNED = (
    (r"\bwill\b", "will"), (r"\bwon't\b", "won't"), (r"\b\w+'ll\b", "'ll"),
    (r"\bgoing to\b", "going to"),
    (r"\bexpect\w*", "expect"), (r"\bforecast\w*", "forecast"), (r"\bpredict\w*", "predict"),
    (r"\boutlook\b", "outlook"),
    (r"\bshould\b", "should"), (r"\bbest\b", "best"), (r"\brecommend\w*", "recommend"),
    (r"\bbuy(s|ing)?\b", "buy"), (r"\bsell(s|ing)?\b", "sell"), (r"\bnow is\b", "now is"),
)
# capitals that are names of agencies or measures, not tickers
ACRONYMS = frozenset({"US", "USA", "UK", "EU", "CPI", "PCE", "GDP", "FOMC", "BLS", "BEA",
                      "SEC", "FDIC", "IRS"})
# fund families: a note names no fund (a kind of fund - "a money market
# fund" - is fine; a fund's name nearly always carries its family's or a ticker)
FUND_WORDS = ("Vanguard", "iShares", "BlackRock", "SPDR", "State Street", "Invesco",
              "T. Rowe", "PIMCO", "Franklin Templeton", "American Funds", "Dimensional",
              "Nuveen", "ProShares", "Direxion", "Ark Invest")
_TICKER = re.compile(r"\$?\b[A-Z]{2,5}\b")
_MONTH = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")

TITLE = "This month's world"
INTRO = ("A short note on what happened in the markets and the economy last month - only "
         "what already happened, never a forecast.")
NOT_ADVICE = ("Educational, not advice: it describes what happened, the same for everyone, "
              "and says nothing about what comes next or what to do.")
GENERAL_ONLY = ("Once you add your holdings, a line about the kinds of investments you hold "
                "shows here too.")
SOURCES_LEAD = "Sources"
OPEN = "Read this month's note"
CLOSE = "Close"

# --------------------------------------------------------------------------- #
# The notes, newest first - the owner's to write (docs/RUNBOOK.md, "Writing
# this month's world"). Each one:
#   {"month": "2026-10",                 # the month it's about to show in
#    "title": "...",
#    "paragraphs": ["...", "..."],      # 2-4 short paragraphs of past facts
#    "for_mix": {"stocks": "...", "bonds": "...", "cash": "..."},   # any of these
#    "sources": [("label", "https://www.bls.gov/...")],             # OFFICIAL_SITES
#    "reviewed_by": "...",               # who reviewed it (L3)
#    "reviewed_on": "2026-10-03"}        # the day; empty = never shown
# Empty until the owner writes the first one: nothing is invented here.
# --------------------------------------------------------------------------- #
NOTES: list[dict] = []


# ---- the checks ------------------------------------------------------------- #
def host(url: str) -> str:
    return urlparse(url).netloc.lower()


def words_of(note: dict) -> list[str]:
    """Every sentence a note shows (not its sources' addresses)."""
    out = [str(note.get("title") or "")]
    out += [str(p) for p in note.get("paragraphs") or ()]
    out += [str(v) for v in (note.get("for_mix") or {}).values()]
    out += [str(s[0]) for s in note.get("sources") or () if isinstance(s, (tuple, list)) and s]
    return out


def word_problems(text: str) -> list[str]:
    """What's wrong with a piece of a note's wording: a banned word, a ticker
    or a fund's name."""
    out = []
    low = text.lower().replace("’", "'")   # a curly apostrophe counts too
    for pat, word in BANNED:
        if re.search(pat, low):
            out.append(f"uses '{word}'")
    for m in _TICKER.finditer(text):
        if m.group(0).lstrip("$") not in ACRONYMS:
            out.append(f"looks like a ticker: {m.group(0)}")
    for name in FUND_WORDS:
        if re.search(r"\b" + re.escape(name.lower()) + r"\b", low):
            out.append(f"names a fund: {name.strip()}")
    for name, _url in brokerages.BROKERAGES:
        name = name.replace("*", "").strip()
        if name and re.search(r"\b" + re.escape(name.lower()) + r"\b", low):
            out.append(f"names a brokerage: {name}")
    return out


def _is_day(v) -> bool:
    try:
        date.fromisoformat(str(v))
    except ValueError:
        return False
    return isinstance(v, str) and len(v) == 10


def problems(note) -> list[str]:
    """Everything that keeps a note from showing ([] = fine). Reviewing is
    checked by reviewed() - an unreviewed note can still be well formed."""
    if not isinstance(note, dict):
        return ["not a note"]
    out = []
    if not _MONTH.match(str(note.get("month") or "")):
        out.append("month is not like 2026-10")
    if not str(note.get("title") or "").strip():
        out.append("no title")
    paras = note.get("paragraphs")
    if not isinstance(paras, (list, tuple)) or not 2 <= len(paras) <= 4 \
            or not all(isinstance(p, str) and p.strip() for p in paras):
        out.append("needs 2 to 4 paragraphs")
    mix = note.get("for_mix") or {}
    if not isinstance(mix, dict) or set(mix) - set(CLASS_KEYS) \
            or not all(isinstance(v, str) and v.strip() for v in mix.values()):
        out.append(f"for_mix keys are only {', '.join(CLASS_KEYS)}, each a line")
    sources = note.get("sources")
    if not isinstance(sources, (list, tuple)) or not sources:
        out.append("needs at least one source")
    else:
        for s in sources:
            if not (isinstance(s, (tuple, list)) and len(s) == 2 and str(s[0]).strip()):
                out.append("a source is (label, address)")
                continue
            if not str(s[1]).startswith("https://") or host(str(s[1])) not in OFFICIAL_SITES:
                out.append(f"not an official source: {s[1]}")
    if note.get("reviewed_on") and not _is_day(note.get("reviewed_on")):
        out.append("reviewed_on is not like 2026-10-03")
    for text in words_of(note):
        out += word_problems(text)
    return out


def reviewed(note: dict, today: date | None = None) -> bool:
    """Reviewed and dated (L3), on or before today."""
    on = note.get("reviewed_on")
    if not (str(note.get("reviewed_by") or "").strip() and _is_day(on)):
        return False
    return today is None or date.fromisoformat(on) <= today


# ---- which note shows ------------------------------------------------------- #
def month_of(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def last_month(d: date) -> str:
    return f"{d.year - 1}-12" if d.month == 1 else f"{d.year}-{d.month - 1:02d}"


def current(today: date, notes=None) -> dict | None:
    """The note to show today: this month's or last month's - this month's
    first - reviewed and passing every check. None otherwise."""
    notes = NOTES if notes is None else notes
    for month in (month_of(today), last_month(today)):
        for n in notes:
            if (isinstance(n, dict) and n.get("month") == month and reviewed(n, today)
                    and not problems(n)):
                return n
    return None


def lines_for(note: dict, mix: dict | None) -> list[tuple[str, int, str]]:
    """The "for someone with mostly ..." lines for this person's mix:
    [(class key, their whole percent, the note's line)] - their largest class
    with a line, and the next one too from SECOND_AT. `mix` is {"Stocks": 72.4,
    ...} (asset_classes' classes) or None for someone with no holdings: then
    none, and the general paragraphs stand alone."""
    if not mix:
        return []
    have = note.get("for_mix") or {}
    ranked = []
    for key, label in CLASS_KEYS.items():
        try:
            pct = float(mix.get(label))
        except (TypeError, ValueError):
            continue
        if pct != pct or pct <= 0 or key not in have:
            continue
        ranked.append((pct, key))
    ranked.sort(key=lambda t: (-t[0], list(CLASS_KEYS).index(t[1])))
    out = []
    for i, (pct, key) in enumerate(ranked[:2]):
        if i == 1 and pct < SECOND_AT:
            break
        out.append((key, int(round(pct)), have[key]))
    return out


def lead_of(key: str, pct: int) -> str:
    """'For someone with mostly stocks (about 72% of your mix)'."""
    return f"For someone with {CLASS_WORDS[key]} (about {pct}% of your mix)"


# ---- what's kept ------------------------------------------------------------ #
def clean_seen(raw) -> list[str]:
    """The months opened, checked: month keys only, the newest KEEP."""
    if not isinstance(raw, (list, tuple)):
        return []
    return sorted({m for m in raw if isinstance(m, str) and _MONTH.match(m)})[-KEEP:]


def seen(p: dict | None, month: str) -> bool:
    return month in clean_seen((p or {}).get(PREF))


def mark_seen(p: dict, month: str) -> bool:
    """Keep that this month's note was opened. Changes `p`; True if changed."""
    if not (isinstance(month, str) and _MONTH.match(month)) or seen(p, month):
        return False
    p[PREF] = clean_seen(clean_seen(p.get(PREF)) + [month])
    return True


def all_text() -> str:
    """Every fixed word the frame shows (for the wording tests)."""
    return "\n".join([TITLE, INTRO, NOT_ADVICE, GENERAL_ONLY, SOURCES_LEAD, OPEN, CLOSE,
                      *CLASS_WORDS.values()])
