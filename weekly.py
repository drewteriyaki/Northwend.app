"""Weekly summaries (flag `weekly`): two moments in each week, drawn as a
card on Home by views/weekly.py (render_weekly). The monthly walk
(checkin.py) stays the target-mix check; these only describe.

- "Your week" - from Friday after the close (4 pm ET) through Sunday: the
  week just finished, Monday to Friday. The portfolio's change in dollars
  and percent at each day's close (perf.daily_values: the holdings held now,
  so money added or taken out isn't part of it), the holdings that went up
  and down the most (percent only), where the goal stood at the start and
  end of the week (the plan's target amount), and up to three headlines
  about the holdings that moved the most (news.latest_news - only what's
  already kept; nothing is fetched).
- "The week ahead" - Monday through Thursday: dates already known in the
  next seven days. Dividend pay dates and earnings dates for holdings come
  only from the brokerage's own file (positions.div_pay_date /
  next_earnings_date); ex-dividend dates are kept only once they've passed
  (daily_bars.dividend), so none are listed and none are estimated. Plus a
  small hand-kept public calendar (CALENDAR: Federal Reserve rate meetings
  and US market holidays and early closes, each with its official source);
  a test fails once CALENDAR_YEAR is past, so it gets reviewed each January.

Descriptive only - the person's own portfolio and public calendar dates,
never advice, never what comes next (LEGAL_GATES.md section 6: no gate).
No broad-market comparison: the app keeps no market index's prices.

Pure logic, no Streamlit and no database: your_week() and week_ahead() take
what the caller read and return plain data; your_week_lines() and
week_ahead_lines() turn it into the fixed sentences below, with the caller's
own money and percent formatters (so hidden amounts stay hidden) - an email
can reuse them later.

What's kept: per moment ("2026-W41-week", "2026-W41-ahead"), "seen" or
"put_away", in the person's own settings (prefs PREF) - never free text.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlparse

try:
    from zoneinfo import ZoneInfo
    NY = ZoneInfo("America/New_York")
except Exception:   # pragma: no cover - no tz database: standard time all year
    NY = timezone(timedelta(hours=-5))

CLOSE = time(16, 0)          # the US market's close, New York time
PREF = "weekly"              # user_prefs key: {"2026-W41-week": "seen" | "put_away", ...}
SEEN, PUT_AWAY = "seen", "put_away"
STATUSES = (SEEN, PUT_AWAY)
WEEK, AHEAD = "week", "ahead"
KINDS = (WEEK, AHEAD)
KEEP = 8                     # the newest moments' states kept; older ones drop
MOVERS = 3                   # up and down, each
HEADLINES = 3
LEAD_IN_DAYS = 10            # closes read before Monday, for the week's starting close

# --------------------------------------------------------------------------- #
# the fixed words
# --------------------------------------------------------------------------- #
WEEK_TITLE = "Scout: your week"
WEEK_WHY = "How your portfolio's value changed from Monday to Friday's close."
WEEK_SPAN = "{start} to {end}, at each day's closing price."
CHANGE_LINE = "Your portfolio's value changed by {money} ({pct}) over the week."
CHANGE_PCT_LINE = "Your portfolio's value changed by {pct} over the week."
CHANGE_NONE = ("There aren't daily prices for this week yet, so the week's change isn't "
               "shown.")
CHANGE_HOW = ("This counts the holdings you have now at each day's closing price, so money "
              "added or taken out isn't part of it.")
UP_LEAD = "Went up the most this week:"
DOWN_LEAD = "Went down the most this week:"
MOVERS_NONE = "There are no daily prices for your holdings this week."
GOAL_LINE = "Your goal, {name}: from {start} to {end} of the amount over the week."
NEWS_LEAD = "Headlines this week about the holdings that moved the most:"
NEWS_NOTE = ("From the news sources named, as they published them - Northwend doesn't write "
             "or check them.")
WEEK_FOOT = ("A record of what already happened, worked out the same way for everyone. It "
             "isn't advice, and it says nothing about the weeks to come.")

AHEAD_TITLE = "Scout: the week ahead"
AHEAD_WHY = "Dates already known for the next seven days."
AHEAD_SPAN = "{start} to {end}."
PAY_ITEM = "{ticker} dividend pay date"
EARN_ITEM = "{ticker} earnings report date"
HOLDING_SOURCE = ("Pay and earnings dates come from your brokerage's file of {date}. "
                  "Companies sometimes move them.")
AHEAD_NONE = "No pay or earnings dates are known for your holdings in these seven days."
NO_BROKER_DATES = ("Dividend pay dates and earnings dates show here when your brokerage's "
                   "file includes them.")
EX_NOTE = ("Ex-dividend dates aren't listed: Northwend keeps them only once they've "
           "passed.")
CAL_LEAD = "On the public calendar:"
CAL_NOTE = "From the official calendars linked here, checked {checked}."
AHEAD_FOOT = "Dates only, as published - nothing here says what happens on them."

# --------------------------------------------------------------------------- #
# the public calendar: hand-kept, each date with its official source.
# Reviewed each January - a test fails once CALENDAR_YEAR is past.
# --------------------------------------------------------------------------- #
CALENDAR_YEAR = 2026
CALENDAR_CHECKED = "2026-10-07"
FED_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
NYSE_URL = "https://www.nyse.com/markets/hours-calendars"
OFFICIAL_SITES = ("www.federalreserve.gov", "www.nyse.com")
FOMC_WORDS = ("The Federal Reserve's rate committee ends its two-day meeting and "
              "posts its statement")
CLOSED_WORDS = "US stock markets closed ({name})"
EARLY_WORDS = "US stock markets close early, at 1 pm ET ({name})"
# (date, words, source) - the second day of each two-day FOMC meeting
CALENDAR = (
    ("2026-01-01", CLOSED_WORDS.format(name="New Year's Day"), NYSE_URL),
    ("2026-01-19", CLOSED_WORDS.format(name="Martin Luther King, Jr. Day"), NYSE_URL),
    ("2026-01-28", FOMC_WORDS, FED_URL),
    ("2026-02-16", CLOSED_WORDS.format(name="Washington's Birthday"), NYSE_URL),
    ("2026-03-18", FOMC_WORDS, FED_URL),
    ("2026-04-03", CLOSED_WORDS.format(name="Good Friday"), NYSE_URL),
    ("2026-04-29", FOMC_WORDS, FED_URL),
    ("2026-05-25", CLOSED_WORDS.format(name="Memorial Day"), NYSE_URL),
    ("2026-06-17", FOMC_WORDS, FED_URL),
    ("2026-06-19", CLOSED_WORDS.format(name="Juneteenth"), NYSE_URL),
    ("2026-07-03", CLOSED_WORDS.format(name="Independence Day, observed"), NYSE_URL),
    ("2026-07-29", FOMC_WORDS, FED_URL),
    ("2026-09-07", CLOSED_WORDS.format(name="Labor Day"), NYSE_URL),
    ("2026-09-16", FOMC_WORDS, FED_URL),
    ("2026-10-28", FOMC_WORDS, FED_URL),
    ("2026-11-26", CLOSED_WORDS.format(name="Thanksgiving Day"), NYSE_URL),
    ("2026-11-27", EARLY_WORDS.format(name="the day after Thanksgiving"), NYSE_URL),
    ("2026-12-09", FOMC_WORDS, FED_URL),
    ("2026-12-24", EARLY_WORDS.format(name="Christmas Eve"), NYSE_URL),
    ("2026-12-25", CLOSED_WORDS.format(name="Christmas Day"), NYSE_URL),
    ("2027-01-01", CLOSED_WORDS.format(name="New Year's Day"), NYSE_URL),
)


# --------------------------------------------------------------------------- #
# which moment
# --------------------------------------------------------------------------- #
def now() -> datetime:
    """The time the app goes by (one place, so the tests can set it)."""
    return datetime.now(timezone.utc)


def moment(at: datetime) -> dict | None:
    """What's on at `at` (an aware datetime), on the market's clock:
    {"kind": "ahead", "id", "start": today, "end": today + 6} Monday to
    Thursday; {"kind": "week", "id", "start": Monday, "end": Friday} from
    Friday's close through Sunday; None on Friday before the close. The id
    is the ISO week of that Monday ("2026-W41") and the kind - so a week
    that crosses the new year keeps one id."""
    ny = at.astimezone(NY)
    day = ny.date()
    monday = day - timedelta(days=day.weekday())
    iso_year, iso_week, _ = monday.isocalendar()
    wid = f"{iso_year}-W{iso_week:02d}"
    if day.weekday() <= 3:
        return {"kind": AHEAD, "id": f"{wid}-{AHEAD}", "start": day,
                "end": day + timedelta(days=6)}
    if day.weekday() == 4 and ny.time() < CLOSE:
        return None
    return {"kind": WEEK, "id": f"{wid}-{WEEK}", "start": monday,
            "end": monday + timedelta(days=4)}


_MID = re.compile(r"^(\d{4})-W(\d{2})-(" + "|".join(KINDS) + r")$")


def _order(mid: str):
    m = _MID.match(mid)
    return int(m.group(1)), int(m.group(2)), KINDS.index(m.group(3))


def clean_saved(saved) -> dict:
    """What's kept, checked: {moment id: status}, known ids and statuses only,
    the newest KEEP of them."""
    if not isinstance(saved, dict):
        return {}
    kept = {k: v for k, v in saved.items()
            if isinstance(k, str) and _MID.match(k) and v in STATUSES}
    order = sorted(kept, key=_order, reverse=True)
    return {k: kept[k] for k in order[:KEEP]}


def with_status(prefs_data: dict, mid: str, status: str) -> dict:
    """The person's settings with one moment's state set. "seen" never
    replaces "put_away"; an unknown id or status changes nothing."""
    out = dict(prefs_data or {})
    if not (isinstance(mid, str) and _MID.match(mid)) or status not in STATUSES:
        return out
    kept = clean_saved(out.get(PREF))
    if status == SEEN and kept.get(mid) == PUT_AWAY:
        return out
    kept[mid] = status
    out[PREF] = clean_saved(kept)
    return out


def home_state(saved, mid: str | None) -> str | None:
    """What Home shows: "card" (new), "line" (opened already: one quiet
    line), or None (nothing on, or put away until the next moment)."""
    if not mid:
        return None
    status = clean_saved(saved).get(mid)
    return None if status == PUT_AWAY else ("line" if status == SEEN else "card")


# --------------------------------------------------------------------------- #
# Your week
# --------------------------------------------------------------------------- #
def _iso(d) -> str:
    return str(d)[:10]


def _change(series, start: date, end: date):
    """(base, last, last day): the last close before `start` and the last on
    or before `end` - or Nones when either is missing."""
    s, e = start.isoformat(), end.isoformat()
    before = [(d, v) for d, v in series if _iso(d) < s and v is not None]
    inside = [(d, v) for d, v in series if s <= _iso(d) <= e and v is not None]
    if not before or not inside:
        return None, None, None
    return float(before[-1][1]), float(inside[-1][1]), _iso(inside[-1][0])


def _published_day(a) -> str:
    return str(a.get("published_at") or "")[:10]


def _safe_url(url) -> str | None:
    u = str(url or "")
    return u if urlparse(u).scheme in ("http", "https") and urlparse(u).netloc else None


def your_week(values, closes, *, start: date, end: date, target=None, goal_name=None,
              news=None) -> dict:
    """The week from `start` (Monday) to `end` (Friday).

    values: [(date, portfolio value)] at each close (perf.daily_values),
    from before `start`. closes: rows (ticker, date, close) - perf.closes_since
    - or {ticker: [(date, close)]}. target: the plan's target amount, if it
    has a goal. news: {ticker: [article dicts]} already kept (news.latest_news).

    Returns {"start", "end", "last_day", "base", "value", "change", "pct",
    "up": [(ticker, pct)], "down": [(ticker, pct)], "goal": {"name",
    "start_pct", "end_pct"} | None, "headlines": [...], "empty"}."""
    base, last, last_day = _change(sorted(values or [], key=lambda r: _iso(r[0])), start, end)
    change = pct = None
    if base is not None and last is not None:
        change = round(last - base, 2)
        pct = (last - base) / base * 100 if base else None

    by_ticker: dict = {}
    if isinstance(closes, dict):
        by_ticker = {t: list(rows) for t, rows in closes.items()}
    else:
        for r in closes or []:
            t, d, c = (r["ticker"], r["date"], r["close"]) if not isinstance(r, tuple) else r
            by_ticker.setdefault(t, []).append((d, c))
    moves = []
    for t, rows in by_ticker.items():
        b, la, _d = _change(sorted(rows, key=lambda r: _iso(r[0])), start, end)
        if b and la is not None:
            moves.append((t, round((la - b) / b * 100, 6)))
    up = sorted([m for m in moves if m[1] > 0], key=lambda m: (-m[1], m[0]))[:MOVERS]
    down = sorted([m for m in moves if m[1] < 0], key=lambda m: (m[1], m[0]))[:MOVERS]

    goal = None
    try:
        tgt = float(target) if target is not None else None
    except (TypeError, ValueError):
        tgt = None
    if tgt and tgt > 0 and base is not None and last is not None:
        goal = {"name": goal_name or "your goal", "start_pct": base / tgt * 100,
                "end_pct": last / tgt * 100}

    headlines = []
    first, through = start.isoformat(), (end + timedelta(days=2)).isoformat()
    for t, _p in sorted(moves, key=lambda m: (-abs(m[1]), m[0])):
        if len(headlines) >= HEADLINES:
            break
        for a in sorted((news or {}).get(t) or [], key=_published_day, reverse=True):
            url = _safe_url(a.get("url"))
            if a.get("headline") and url and first <= _published_day(a) <= through:
                headlines.append({"ticker": t, "headline": str(a["headline"]).strip(),
                                  "source": str(a.get("source") or "").strip(),
                                  "url": url, "day": _published_day(a)})
                break

    return {"start": start, "end": end, "last_day": last_day, "base": base, "value": last,
            "change": change, "pct": pct, "up": up, "down": down, "goal": goal,
            "headlines": headlines, "empty": change is None and not moves}


def _signed_pct(v: float) -> str:
    return f"{v:+.1f}%"


def _day_words(d) -> str:
    d = d if isinstance(d, date) else date.fromisoformat(_iso(d))
    return f"{d:%a}, {d:%b} {d.day}"


def your_week_lines(data: dict, *, money=lambda v: f"${v:+,.2f}", pct=_signed_pct,
                    level=lambda v: f"{v:.0f}%", dollars: bool = True) -> dict:
    """The fixed sentences for your_week()'s data. money / pct / level are
    the caller's formatters (the app's mask hidden amounts); dollars=False
    leaves the dollar change out (a percentages-only portfolio's total is
    pretend). Returns {"title", "why", "span", "change", "how", "up",
    "down", "movers_none", "goal", "news_lead", "headlines", "news_note",
    "foot"} - a list or "" where there's nothing."""
    out = {"title": WEEK_TITLE, "why": WEEK_WHY,
           "span": WEEK_SPAN.format(start=_day_words(data["start"]),
                                    end=_day_words(data["last_day"] or data["end"])),
           "how": CHANGE_HOW, "foot": WEEK_FOOT}
    if data["change"] is None:
        out["change"] = CHANGE_NONE
    elif dollars and data["pct"] is not None:
        out["change"] = CHANGE_LINE.format(money=money(data["change"]), pct=pct(data["pct"]))
    elif data["pct"] is not None:
        out["change"] = CHANGE_PCT_LINE.format(pct=pct(data["pct"]))
    else:
        out["change"] = CHANGE_NONE
    out["up"] = [f"{t} {_signed_pct(p)}" for t, p in data["up"]]
    out["down"] = [f"{t} {_signed_pct(p)}" for t, p in data["down"]]
    out["movers_none"] = "" if (data["up"] or data["down"]) else MOVERS_NONE
    g = data["goal"]
    out["goal"] = (GOAL_LINE.format(name=g["name"], start=level(g["start_pct"]),
                                    end=level(g["end_pct"])) if g else "")
    out["headlines"] = list(data["headlines"])
    out["news_lead"] = NEWS_LEAD if data["headlines"] else ""
    out["news_note"] = NEWS_NOTE if data["headlines"] else ""
    return out


# --------------------------------------------------------------------------- #
# The week ahead
# --------------------------------------------------------------------------- #
_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y")


def parse_day(text) -> date | None:
    """A date from a brokerage file's cell ("10/15/2026", "2026-10-15",
    "Oct 15, 2026"), or None ("--", "N/A", blank, anything else)."""
    s = str(text or "").strip()
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s[:10] if fmt == "%Y-%m-%d" else s, fmt).date()
        except ValueError:
            continue
    return None


def week_ahead(positions, *, start: date, end: date, snapshot=None,
               calendar=CALENDAR) -> dict:
    """Known dates from `start` to `end` (both included).

    positions: the holdings (dicts with symbol, div_pay_date,
    next_earnings_date - the brokerage file's own cells). Only dates that
    parse and fall in the window; nothing is estimated. Returns {"start",
    "end", "holdings": [(date, ticker, "pay" | "earnings")], "has_broker_dates",
    "snapshot", "calendar": [(date, words, url)]}."""
    items, has_dates = set(), False
    for p in positions or []:
        sym = p.get("symbol")
        for field, kind in (("div_pay_date", "pay"), ("next_earnings_date", "earnings")):
            d = parse_day(p.get(field))
            if d is None:
                continue
            has_dates = True
            if sym and start <= d <= end:
                items.add((d, sym, kind))
    cal = [(date.fromisoformat(d), words, url) for d, words, url in calendar
           if start.isoformat() <= d <= end.isoformat()]
    return {"start": start, "end": end, "holdings": sorted(items), "has_broker_dates": has_dates,
            "snapshot": snapshot, "calendar": sorted(cal)}


def week_ahead_lines(data: dict, *, day_fmt=None) -> dict:
    """The fixed sentences for week_ahead()'s data: {"title", "why", "span",
    "holdings": [(day, text)], "holdings_none", "source", "ex_note",
    "cal_lead", "calendar": [(day, text, url)], "cal_note", "foot"}."""
    fmt = day_fmt or _day_words
    hold = [(fmt(d), (PAY_ITEM if k == "pay" else EARN_ITEM).format(ticker=t))
            for d, t, k in data["holdings"]]
    if hold:
        none = ""
    else:
        none = AHEAD_NONE if data["has_broker_dates"] else NO_BROKER_DATES
    snap = data.get("snapshot")
    return {"title": AHEAD_TITLE, "why": AHEAD_WHY,
            "span": AHEAD_SPAN.format(start=fmt(data["start"]), end=fmt(data["end"])),
            "holdings": hold, "holdings_none": none,
            "source": (HOLDING_SOURCE.format(date=fmt(snap)) if hold and snap else ""),
            "ex_note": EX_NOTE,
            "cal_lead": CAL_LEAD if data["calendar"] else "",
            "calendar": [(fmt(d), w, u) for d, w, u in data["calendar"]],
            "cal_note": (CAL_NOTE.format(checked=CALENDAR_CHECKED) if data["calendar"] else ""),
            "foot": AHEAD_FOOT}


# --------------------------------------------------------------------------- #
# for the tests
# --------------------------------------------------------------------------- #
def templates() -> list[str]:
    """Every fixed sentence shown, with sample values filled in."""
    return [WEEK_TITLE, WEEK_WHY, WEEK_SPAN.format(start="Mon, Oct 5", end="Fri, Oct 9"),
            CHANGE_LINE.format(money="+$120.00", pct="+1.2%"),
            CHANGE_PCT_LINE.format(pct="-0.4%"), CHANGE_NONE, CHANGE_HOW, UP_LEAD, DOWN_LEAD,
            MOVERS_NONE, GOAL_LINE.format(name="Retirement", start="41%", end="42%"),
            NEWS_LEAD, NEWS_NOTE, WEEK_FOOT, AHEAD_TITLE, AHEAD_WHY,
            AHEAD_SPAN.format(start="Mon, Oct 5", end="Sun, Oct 11"),
            PAY_ITEM.format(ticker="VTI"), EARN_ITEM.format(ticker="AAPL"),
            HOLDING_SOURCE.format(date="Fri, Oct 2"), AHEAD_NONE, NO_BROKER_DATES, EX_NOTE,
            CAL_LEAD, CAL_NOTE.format(checked=CALENDAR_CHECKED), AHEAD_FOOT,
            *sorted({w for _d, w, _u in CALENDAR})]
