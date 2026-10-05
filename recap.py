"""Year in review (ROADMAP 9): a private recap of one calendar year - the
year so far, or a whole past year - for the person's own account, and a
version to share with no dollar figures. Pure logic, no Streamlit; the
window is views/year_review.py.

What it looks at, all already in the app:
- money added: plans.money_moves (logged on Plan, or the deposits and
  withdrawals in an imported activity export)
- dividends and interest: the imported activity history when there is one,
  else worked out from Yahoo's payments times the shares held (like income.py)
- value at the start and the end: the values logged on visits (value_log)
  and the holdings updates' own figures - never the example portfolio or a
  percentages portfolio (pretend dollars)
- best and worst month, and the year's move: the holdings you have now,
  priced at each day's close (perf's reconstructed line) - the market's
  effect alone, money in or out never shows
- milestones earned (gear dates in settings), reads opened and Learn steps
  completed that year (dated in settings: note_done), and notes to future
  you written that year (the future_notes table, when it exists)

The share version (share_lines / share_pdf) carries percentages, counts,
months and names of milestones only - never an amount of money.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date

import gear
import income
import perf
import plans

SAMPLE_SOURCE = "sample portfolio"
PCT_SOURCE = "percentages"
PRETEND_SOURCES = (SAMPLE_SOURCE, PCT_SOURCE)

MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")

# Learn's waypoints by name (views/get_started.py GET_STARTED_STEPS)
STEP_NAMES = {
    "profile": "About you", "ready": "Are you ready to invest?", "goal": "Set a goal",
    "basics": "Learn the basics", "mix": "An example mix",
    "practice": "Try it with practice money", "brokerage": "Choose a brokerage",
    "account": "Open your account", "first": "Your first investments", "bring": "Bring it in",
}
# a piece of gear that can only come from completing that step
GEAR_STEP = {"map": "profile", "compass": "goal", "tent": "basics", "rope": "practice"}
# settings keys: {step: 'YYYY-MM-DD'} and {read: 'YYYY-MM-DD'}, first time only
LEARN_DATES = "learn_dates"
LEARN_READS = "learn_reads"
# Home's January card: years whose recap was opened or put away
SEEN_PREF = "year_review_seen"
NOTES_TABLE = "future_notes"


def note_done(prefs: dict, key: str, item: str, today: date | None = None) -> bool:
    """Date a Learn step or read the first time it's done (settings `key`:
    LEARN_DATES or LEARN_READS). Changes `prefs` in place; True if it did,
    so the caller saves only then."""
    dates = dict(prefs.get(key) or {})
    if item in dates:
        return False
    dates[item] = (today or date.today()).isoformat()
    prefs[key] = dates
    return True


# --------------------------------------------------------------------------- #
# which year
# --------------------------------------------------------------------------- #
def window(year: int, today: date) -> tuple[str, str]:
    """(first day, last day) of the year, the last never after today."""
    end = min(date(year, 12, 31), today)
    return f"{year:04d}-01-01", end.isoformat()


def january_year(today: date) -> int | None:
    """The year Home's January card offers: last year, during January."""
    return today.year - 1 if today.month == 1 else None


def month_name(ym: str) -> str:
    return MONTHS[int(ym[5:7]) - 1]


# --------------------------------------------------------------------------- #
# the pieces
# --------------------------------------------------------------------------- #
def _real_snapshot_dates(conn, user_id: int) -> dict[str, str]:
    """{snapshot_date: source} of every holdings update (pretend ones too)."""
    out = {}
    for r in conn.execute("SELECT snapshot_date, source_file FROM snapshots WHERE user_id = ? "
                          "ORDER BY snapshot_date, imported_at", (user_id,)):
        out[str(r["snapshot_date"])[:10]] = r["source_file"]
    return out


def value_points(conn, user_id: int) -> list[tuple[str, float]]:
    """(day, value) of the whole portfolio in real dollars, oldest first: each
    visit's logged value (value_log) and each holdings update whose every
    holding has a value (its own figures). Pretend portfolios left out."""
    sources = _real_snapshot_dates(conn, user_id)
    pts: dict[str, float] = {}
    for r in conn.execute(
            "SELECT snapshot_date, COUNT(*) AS n, COUNT(market_value) AS nv, "
            "SUM(market_value) AS mv FROM positions WHERE user_id = ? GROUP BY snapshot_date",
            (user_id,)):
        d = str(r["snapshot_date"])[:10]
        if sources.get(d) in PRETEND_SOURCES or not r["n"] or r["nv"] != r["n"]:
            continue
        pts[d] = float(r["mv"] or 0.0)
    for r in conn.execute("SELECT snapshot_date, SUM(cash_value) AS c FROM account_totals "
                          "WHERE user_id = ? GROUP BY snapshot_date", (user_id,)):
        d = str(r["snapshot_date"])[:10]
        if d in pts:
            pts[d] += float(r["c"] or 0.0)
    for r in conn.execute("SELECT logged_at, snapshot_date, portfolio_value FROM value_log "
                          "WHERE user_id = ? AND portfolio_value IS NOT NULL ORDER BY logged_at",
                          (user_id,)):
        if sources.get(str(r["snapshot_date"] or "")[:10]) in PRETEND_SOURCES:
            continue
        pts[str(r["logged_at"])[:10]] = float(r["portfolio_value"])   # the day's last visit
    return sorted(pts.items())


def start_end(points, start: str, end: str, current: float | None):
    """(start value, its day, end value, its day): the last value before the
    year began (else the first inside it - "since"), and the last on or
    before its end (`current`, today's live value, for the year so far)."""
    before = [p for p in points if p[0] < start]
    inside = [p for p in points if start <= p[0] <= end]
    first = before[-1] if before else (inside[0] if inside else None)
    last = (end, current) if current is not None else (inside[-1] if inside else None)
    if first is None or last is None:
        return None, None, None, None
    return first[1], (start if before else first[0]), last[1], last[0]


def monthly_moves(series, year: int, end: str) -> list[dict]:
    """Each month's move, in percent, of a (day, value) series - the last
    value of the month against the last of the month before (or the
    month's first value, when the series starts inside it: "partial")."""
    month_end: dict[str, float] = {}
    month_first: dict[str, float] = {}
    for d, v in series:
        if not v or d[:10] > end:
            continue
        ym = d[:7]
        month_first.setdefault(ym, v)
        month_end[ym] = v
    out = []
    prev_key = f"{year - 1:04d}-12"
    prev = month_end.get(prev_key)
    for m in range(1, 13):
        ym = f"{year:04d}-{m:02d}"
        if ym > end[:7]:
            break
        if ym not in month_end:
            prev = None
            continue
        base, partial = (prev, False) if prev else (month_first[ym], True)
        if base and not (partial and month_first[ym] == month_end[ym]):
            out.append({"month": ym, "pct": round((month_end[ym] / base - 1) * 100, 2),
                        "partial": partial})
        prev = month_end[ym]
    return out


def year_move(series, year: int, end: str) -> tuple[float | None, str | None]:
    """(percent, since): the series over the year - from the last value of
    the year before, else its first value inside the year (`since`, its day)."""
    start = f"{year:04d}-01-01"
    before = [(d, v) for d, v in series if d[:10] < start and v]
    inside = [(d, v) for d, v in series if start <= d[:10] <= end and v]
    if not inside:
        return None, None
    base = before[-1] if before else inside[0]
    if base == inside[-1]:
        return None, None
    return round((inside[-1][1] / base[1] - 1) * 100, 2), (None if before else base[0][:10])


def market_series(conn, basis, year: int) -> list[tuple[str, float]]:
    """The holdings you have now at each day's close, from the December
    before (perf's reconstructed line; only the days every covered holding
    had a price, so a fund whose prices start later isn't a jump)."""
    if not basis or not basis[1]:
        return []
    rows = perf._reconstructed_daily_rows(conn, basis, f"{year - 1:04d}-12-01")
    most = max((r["n_priced"] for r in rows), default=0)
    return [(str(r["t"])[:10], r["portfolio_value"]) for r in rows if r["n_priced"] == most]


def income_in(conn, user_id: int, start: str, end: str, *, skip_sources=PRETEND_SOURCES) -> dict:
    """Dividends and interest that year: {"total", "dividends", "interest",
    "payments" (how many), "source": "brokerage" | "estimated" | None,
    "since": the imported history's first day when it starts inside the year}."""
    window_ = plans.imported_window(conn, user_id)
    if window_ and window_[1] >= start:
        divs = interest = 0.0
        n = 0
        for r in conn.execute(
                "SELECT action, amount FROM transactions WHERE user_id = ? AND origin = "
                "'imported' AND action IN ('DIV', 'INTEREST') AND amount > 0 AND "
                "trade_date >= ? AND trade_date <= ?", (user_id, start, end)):
            n += 1
            if r["action"] == "DIV":
                divs += float(r["amount"])
            else:
                interest += float(r["amount"])
        return {"total": round(divs + interest, 2), "dividends": round(divs, 2),
                "interest": round(interest, 2), "payments": n, "source": "brokerage",
                "since": window_[0] if window_[0] > start else None}
    history = income.holding_history(conn, user_id, skip_sources)
    held = {s: income.held_since(history, s) for d in history.values() for s in d}
    held = {s: d for s, d in held.items() if d}
    total, n = 0.0, 0
    if held:
        paid = income.payments_since(conn, held, min(min(held.values()), start))
        dates = sorted(history)
        for sym, since in held.items():
            for ex, per_share in paid.get(sym) or []:
                if not (since < ex <= end and ex >= start):
                    continue
                before = [d for d in dates if since <= d < ex]
                shares = (history[before[-1]].get(sym) or 0.0) if before else 0.0
                if shares > 0:
                    total += per_share * shares
                    n += 1
    return {"total": round(total, 2), "dividends": round(total, 2), "interest": 0.0,
            "payments": n, "source": "estimated" if n else None, "since": None}


def months_invested(conn, user_id: int, start: str, end: str) -> tuple[int, str | None]:
    """(months of the year with your own holdings in, the first update ever)."""
    row = conn.execute(
        "SELECT MIN(snapshot_date) AS d FROM snapshots WHERE user_id = ? AND source_file "
        "NOT IN (?, ?)", (user_id, *PRETEND_SOURCES)).fetchone()
    first = str(row["d"])[:10] if row and row["d"] else None
    if not first or first > end:
        return 0, first
    a = max(first, start)
    return (int(end[:4]) - int(a[:4])) * 12 + int(end[5:7]) - int(a[5:7]) + 1, first


def _table_exists(conn, name: str) -> bool:
    # (sqlite3 is never reloaded; pgcompat can be - codefresh.py - so its
    # class isn't a safe test here)
    if isinstance(conn, sqlite3.Connection):
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                            (name,)).fetchone() is not None
    return conn.execute("SELECT 1 FROM information_schema.tables WHERE table_name = ? AND "
                        "table_schema = current_schema()", (name,)).fetchone() is not None


def notes_written(conn, user_id: int, start: str, end: str) -> int | None:
    """Notes to future you written that year - None when the app has no
    such notes (yet)."""
    if not _table_exists(conn, NOTES_TABLE):
        return None
    return conn.execute(f"SELECT COUNT(*) AS n FROM {NOTES_TABLE} WHERE user_id = ? AND "
                        "created_at >= ? AND created_at < ?",
                        (user_id, start, end + "~")).fetchone()["n"]


def _in_year(d: str | None, start: str, end: str) -> bool:
    return bool(d) and start <= str(d)[:10] <= end


def learned(prefs: dict, start: str, end: str) -> dict:
    """{"gear": [keys earned that year], "steps": [Learn steps completed],
    "reads": [reads opened]} from the dates kept in settings."""
    dates = prefs.get("gear_dates") or {}
    got = [k for k in gear.KEYS
           if _in_year((dates.get(k) or {}).get("on") or (dates.get(k) or {}).get("by"),
                       start, end)]
    steps = {s for s, d in (prefs.get(LEARN_DATES) or {}).items() if _in_year(d, start, end)}
    steps |= {GEAR_STEP[k] for k in got if k in GEAR_STEP}
    reads = sorted(r for r, d in (prefs.get(LEARN_READS) or {}).items()
                   if _in_year(d, start, end))
    return {"gear": got, "steps": [s for s in STEP_NAMES if s in steps], "reads": reads}


# --------------------------------------------------------------------------- #
# the recap
# --------------------------------------------------------------------------- #
def build(conn, user_id: int, year: int, today: date, *, prefs: dict | None = None,
          current_value: float | None = None, basis=None, pretend: str | None = None) -> dict:
    """Everything the recap shows for one year. `current_value`: today's
    value, for the year so far; `basis`: perf.basis_of() of the holdings now;
    `pretend`: the holdings' source when it's the example or a percentages
    portfolio - then no money figures at all (`money` is False)."""
    start, end = window(year, today)
    so_far = end < f"{year:04d}-12-31"
    money = pretend not in PRETEND_SOURCES
    moves = plans.money_moves(conn, user_id, start, end)
    counted = [m for m in moves if m["counted"]]
    added = round(sum(m["amount"] for m in counted), 2)
    months_added = sorted({m["date"][:7] for m in counted if m["amount"] > 0})
    v0, v0_day, v1, v1_day = (start_end(value_points(conn, user_id), start, end,
                                        current_value if so_far else None)
                              if money else (None, None, None, None))
    added_since = (added if v0_day == start or v0_day is None
                   else plans.money_added(conn, user_id, v0_day, end))
    growth = (round(v1 - v0 - added_since, 2) if v0 is not None and v1 is not None else None)
    series = market_series(conn, basis, year) if pretend != SAMPLE_SOURCE else []
    months = monthly_moves(series, year, end)
    move, move_since = year_move(series, year, end)
    full = [m for m in months if not m["partial"]] or months
    best = max(full, key=lambda m: m["pct"]) if len(full) >= 2 else None
    worst = min(full, key=lambda m: m["pct"]) if len(full) >= 2 else None
    n_months, first = months_invested(conn, user_id, start, end)
    r = {
        "year": year, "start": start, "end": end, "so_far": so_far, "money": money,
        "pretend": pretend,
        "added": added if money else None, "moves": len(counted),
        "months_added": months_added,
        "income": income_in(conn, user_id, start, end) if money else None,
        "value_start": v0, "value_start_day": v0_day, "value_end": v1, "value_end_day": v1_day,
        "growth": growth if money else None,
        "months": months, "best": best, "worst": worst,
        "market_move": move, "market_since": move_since,
        "months_invested": n_months, "investing_since": first,
        **learned(prefs or {}, start, end),
        "notes": notes_written(conn, user_id, start, end),
    }
    r["perspective"] = perspective(r)
    return r


def perspective(r: dict) -> str:
    """One calm line about the year - never a forecast, never advice."""
    worst = r.get("worst")
    if worst and worst["pct"] <= -5:
        return (f"{month_name(worst['month'])} was a hard month, and you're still here. Staying "
                "with a plan through the rough stretches is most of the work.")
    if len(r.get("months_added") or []) >= 6:
        return (f"You added money in {len(r['months_added'])} months. Steady habits like that "
                "tend to matter more than any single month.")
    if r.get("gear") or r.get("steps") or r.get("reads"):
        return ("You spent part of this year learning how investing works. That understanding "
                "keeps paying off long after the year ends.")
    if r.get("months_invested"):
        return ("A year is a short stretch on a long route. What counts most is that you're "
                "still on it.")
    return ("Every route starts somewhere. Whenever you're ready, the next step is on Home.")


def is_empty(r: dict) -> bool:
    """Nothing at all to look back on."""
    return not (r["moves"] or r["months"] or r["value_end"] is not None or r["gear"]
                or r["steps"] or r["reads"] or r["notes"] or r["months_invested"]
                or (r["income"] or {}).get("payments"))


# --------------------------------------------------------------------------- #
# the version to share: no dollar figures
# --------------------------------------------------------------------------- #
def _pct(v: float) -> str:
    return f"{v:+.1f}%"


def share_lines(r: dict) -> list[tuple[str, str]]:
    """[(heading, line)] for the share card: percentages, counts, months and
    milestone names - never an amount of money."""
    out = []
    label = f"{r['year']} so far" if r["so_far"] else str(r["year"])
    if r["months_invested"]:
        since = r["investing_since"]
        out.append(("Invested", f"{r['months_invested']} month"
                    f"{'s' if r['months_invested'] != 1 else ''} of {label}"
                    + (f", since {month_name(since[:7])} {since[:4]}"
                       if since and since[:4] == str(r["year"]) else "")))
    if r["market_move"] is not None:
        out.append(("The year's move", f"{_pct(r['market_move'])} for what I hold"
                    + (f", since {month_name(r['market_since'][:7])}"
                       if r["market_since"] else "")))
    if r["best"]:
        out.append(("Best month", f"{month_name(r['best']['month'])}, {_pct(r['best']['pct'])}"))
    if r["worst"]:
        out.append(("Toughest month",
                    f"{month_name(r['worst']['month'])}, {_pct(r['worst']['pct'])}"))
    if r["months_added"]:
        n = len(r["months_added"])
        out.append(("Steady habit", f"Added money in {n} month{'s' if n != 1 else ''}"))
    if (r["income"] or {}).get("payments"):
        n = r["income"]["payments"]
        out.append(("Paid to me", f"{n} dividend or interest payment{'s' if n != 1 else ''}"))
    if r["gear"]:
        out.append(("Milestones", ", ".join(gear.BY_KEY[k][1] for k in r["gear"])))
    if r["reads"] or r["steps"]:
        bits = []
        if r["reads"]:
            bits.append(f"{len(r['reads'])} read{'s' if len(r['reads']) != 1 else ''}")
        if r["steps"]:
            bits.append(f"{len(r['steps'])} Learn step{'s' if len(r['steps']) != 1 else ''}")
        out.append(("Learned", " and ".join(bits)))
    if r["notes"]:
        out.append(("Notes to future me", f"{r['notes']} written"))
    out.append(("", r["perspective"]))
    return out


_MONEYISH = re.compile(r"\$|\b\d{1,3}(,\d{3})+\b|\b\d{4,}\.\d")


def has_money(text: str) -> bool:
    """Whether text holds anything that reads as an amount of money."""
    return bool(_MONEYISH.search(text))


def share_text(r: dict) -> str:
    return "\n".join(f"{h}: {t}" if h else t for h, t in share_lines(r))


def _latin(s: str) -> str:
    s = s.replace("—", "-").replace("–", "-").replace("’", "'")
    return s.encode("latin-1", "replace").decode("latin-1")


def share_pdf(r: dict, app_name: str = "Northwend") -> bytes:
    """The share card as a one-page PDF (fpdf2): no dollar figures."""
    from fpdf import FPDF

    pdf = FPDF(format=(148, 210))   # A5, in mm
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.set_margins(14, 14, 14)
    pdf.add_page()
    pdf.set_draw_color(161, 98, 7)
    pdf.set_line_width(0.6)
    pdf.rect(8, 8, pdf.w - 16, pdf.h - 16)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(110)
    pdf.cell(0, 6, _latin(f"{app_name} - year in review"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(20)
    pdf.set_font("Times", "B", 24)
    title = f"My {r['year']} so far" if r["so_far"] else f"My {r['year']}"
    pdf.cell(0, 13, _latin(title), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    for head, line in share_lines(r):
        if head:
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_text_color(110)
            pdf.cell(0, 5, _latin(head.upper()), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(20)
            pdf.set_font("Helvetica", "", 12)
            pdf.multi_cell(0, 6, _latin(line), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        else:
            pdf.ln(2)
            pdf.set_font("Times", "I", 12)
            pdf.multi_cell(0, 6, _latin(line), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(120)
    pdf.multi_cell(0, 3.5, _latin(
        "Percent moves are for the holdings I have now, at each day's close. Past results "
        "don't say what comes next. No amounts are shown on purpose."),
        new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def share_file_name(r: dict) -> str:
    return f"my-{r['year']}{'-so-far' if r['so_far'] else ''}-northwend.pdf"
