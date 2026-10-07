"""Shadow Trail (ROADMAP R14): up to two hypothetical paths beside the
person's real mix, on real past prices, from the day each one was set.

The careful version (docs/LEGAL_GATES.md section 6; L3 review before it's on
anywhere but staging - flags.FEATURES["shadow_trail"] needs gate L3 as well
as its flag):
- A shadow is a mix of KINDS of funds only (US stocks, international
  stocks, bonds, cash, in whole 5% steps adding up to 100) - never a ticker
  or a named fund. Each kind is represented by the past prices of one broad
  index fund of that kind, the same stand-ins the practice portfolio uses
  (learn.PRACTICE_TICKERS, read from daily_bars; never shown by name), and
  cash is counted flat (no interest). Nothing new is fetched for it.
- At most MAX_SHADOWS, and each can change at most once a quarter (LOCK_MONTHS
  after it was last set); removing one is always allowed, but its place
  takes a new mix only once that date has passed.
- Always labelled HYPOTHETICAL. Percentages only. The table lists your mix
  first, then the shadows in the order they were made - never sorted by how
  they did; no colour for whichever is higher, no ranking words, and nothing
  to act on (no "switch", no "rebalance to this", no link to trade).
- What's kept: prefs PREF - for each shadow its mix (kind keys and whole
  percentages), the day it was first set and the day it was last changed.
  Never free text, never an amount.

Pure logic and fixed text: standard library only. No
Streamlit, no database, no network (tests/test_repo_rules.py's calculation
layer). The view is views/shadow_trail.py.
"""

from __future__ import annotations

from datetime import date

PREF = "shadow_trail"   # user_prefs key: {"shadows": [slot, slot]}
MAX_SHADOWS = 2
LOCK_MONTHS = 3          # a shadow changes at most once a quarter
STEP = 5                 # whole 5% steps

# The kinds of funds a shadow is made of, in this fixed order. "proxy" is the
# daily_bars ticker that stands in for the kind (never shown); None is flat.
# The same stand-ins and kind descriptions as learn.PRACTICE_TICKERS and
# learn.KINDS (copied, not imported - learn reaches the database through
# plans; tests/test_shadow_trail.py checks they stay in step).
KINDS = (
    {"key": "us", "label": "US stocks", "proxy": "VTI",
     "about": "a broad US stock index fund"},
    {"key": "intl", "label": "International stocks", "proxy": "VXUS",
     "about": "a broad international stock index fund"},
    {"key": "bonds", "label": "Bonds", "proxy": "BND",
     "about": "a broad US bond index fund"},
    {"key": "cash", "label": "Cash", "proxy": None, "about": "cash, counted flat (no interest)"},
)
KIND_KEYS = tuple(k["key"] for k in KINDS)
BY_KIND = {k["key"]: k for k in KINDS}
IN_TEXT = {"us": "US stocks", "intl": "international stocks", "bonds": "bonds", "cash": "cash"}
NAMES = ("Shadow A", "Shadow B")
REAL = "Your mix"

# ---- fixed text (every line here is checked by tests/test_shadow_trail.py) -- #
TITLE = "Shadow Trail"
HYPOTHETICAL = ("Hypothetical - a path you didn't take, on past prices. Not a forecast, "
                "not advice.")
INTRO = ("Set up to two shadow mixes of kinds of funds and see how each path has moved since "
         "the day you set it, beside your own mix. It's a way to see how different kinds of "
         "funds have moved - nothing here says what anyone ought to hold.")
PROXY_LINE = ("Kinds of funds, represented by the past prices of {proxies}, the same stand-ins "
              "as the practice portfolio; cash is counted flat, with no interest. Dividends "
              "are included where the price history has them. Each shadow is invested on the "
              "day it was set and left alone - nothing added, taken out or rebalanced. Real "
              "funds, fees and timing differ.")
REAL_LINE = ("Your mix is your holdings today, on the same past prices - money you added or "
             "took out isn't counted, so it shows the market's effect alone.")
LOCK_LINE = ("A shadow can change at most once every {months} months, so it stays a slow "
             "comparison rather than a chase.")
NONE_YET = ("No shadows yet. A shadow is a mix of kinds of funds - for example 60% US stocks "
            "and 40% bonds - that runs beside your own from the day you set it.")
NO_PRICES = ("Past prices for these kinds of funds aren't on this copy yet, so the paths "
             "can't be drawn. Your shadows are kept, and their paths show once the prices "
             "are here.")
STARTS_SOON = ("{name} starts with the next closing prices after {start}.")
NO_REAL = ("Your own mix isn't drawn: there are no past prices for your holdings over these "
           "days.")
CHART_NOTE = ("Each shadow branches off your mix's line on the day it was set. Percentage "
              "change only; prices through {through}.")
TABLE_NOTE = ("Change since each shadow was set, on the same days for your mix. Listed in "
              "the order they were made.")
SLOT_SET = "Set {start}; this mix since {changed}."
SLOT_NEXT = "It can change on {next}."
SLOT_NOW = "It can change now."
SLOT_EMPTY_LOCKED = "This place can hold a new shadow from {next}."
SLOT_EMPTY = "Empty."
TOTAL_LINE = "Adds up to {total}% - it needs to be 100%."
SET_NOTE = ("Once it's set, it can change again on {next}.")
KEPT_LINE = ("Kept in your own settings: each shadow's mix as percentages, the day you set it "
             "and the day you last changed it. Only you see it - not an advisor, and not Ask "
             "Northwend.")
TABLE_COLUMNS = ("Path", "Mix", "Since", "Change, shadow", "Change, your mix")

# button and field labels (also checked)
EDIT_LABEL = "Edit {name}"
NEW_LABEL = "Set up {name}"
SAVE_LABEL = "Save {name}"
REMOVE_LABEL = "Remove {name}"
CANCEL_LABEL = "Cancel"
FIELD_LABEL = "{kind} (%)"


# ---- small helpers ------------------------------------------------------- #
def add_months(d: date, months: int) -> date:
    """`d` plus whole months, the day clipped to the month's last day."""
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    last = (nxt - date.resolution).day
    return date(y, m, min(d.day, last))


def _day(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def date_text(d: date | str | None) -> str:
    """'Oct 6, 2026'."""
    d = _day(d) if not isinstance(d, date) else d
    return f"{d:%b} {d.day}, {d.year}" if d else ""


def pct_text(v: float | None) -> str:
    """'+3.1%', '-0.4%', '0.0%'; an en dash for nothing."""
    if v is None:
        return "–"
    v = round(v, 1)
    if v == 0:
        return "0.0%"
    return f"{v:+.1f}%"


def clean_mix(mix) -> dict | None:
    """{kind: whole %} for known kinds above 0, in STEP steps, adding up to
    exactly 100 - else None. Nothing else (no ticker, no text) gets through."""
    if not isinstance(mix, dict):
        return None
    out = {}
    for k, v in mix.items():
        if k not in BY_KIND:
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        if f != int(f) or f < 0 or f > 100 or int(f) % STEP:
            return None
        if f:
            out[k] = int(f)
    if sum(out.values()) != 100:
        return None
    return {k: out[k] for k in KIND_KEYS if k in out}


def mix_text(mix: dict) -> str:
    """'60% US stocks / 40% bonds' in the fixed kind order."""
    return " / ".join(f"{mix[k]}% {IN_TEXT[k]}" for k in KIND_KEYS if mix.get(k))


# ---- what's kept --------------------------------------------------------- #
def _slot(raw) -> dict | None:
    """One kept place, checked: {"mix": {...} or {}, "start", "changed"}, or None."""
    if not isinstance(raw, dict):
        return None
    changed = _day(raw.get("changed"))
    if changed is None:
        return None
    mix = clean_mix(raw.get("mix")) if raw.get("mix") else {}
    if mix is None:
        mix = {}
    start = _day(raw.get("start")) if mix else None
    return {"mix": mix, "start": (start or changed).isoformat() if mix else None,
            "changed": changed.isoformat()}


def slots(prefs_data) -> list:
    """The MAX_SHADOWS places, each None (never used) or a checked slot. A
    slot with an empty mix was removed: its lock still runs."""
    raw = ((prefs_data or {}).get(PREF) or {})
    raw = raw.get("shadows") if isinstance(raw, dict) else None
    raw = raw if isinstance(raw, list) else []
    return [_slot(raw[i]) if i < len(raw) else None for i in range(MAX_SHADOWS)]


def active(prefs_data) -> list[tuple[int, dict]]:
    """[(place, slot)] for the shadows with a mix, in the order of their places."""
    return [(i, s) for i, s in enumerate(slots(prefs_data)) if s and s["mix"]]


def next_change(slot) -> date | None:
    """The first day the place can take a new mix; None if it never held one."""
    if not slot:
        return None
    return add_months(_day(slot["changed"]), LOCK_MONTHS)


def can_change(slot, today: date) -> bool:
    nxt = next_change(slot)
    return nxt is None or today >= nxt


def _store(prefs_data, places) -> dict:
    out = dict(prefs_data or {})
    places = list(places)
    while places and places[-1] is None:
        places.pop()
    if places:
        out[PREF] = {"shadows": places}
    else:
        out.pop(PREF, None)
    return out


def with_shadow(prefs_data, place: int, mix, today: date) -> tuple[dict, bool]:
    """(new prefs, saved?). Saves `mix` in `place` only if the place's lock
    has passed and the mix is clean; the start day stays when the place
    already held a mix, the changed day becomes today."""
    mix = clean_mix(mix)
    if mix is None or not 0 <= place < MAX_SHADOWS:
        return dict(prefs_data or {}), False
    places = slots(prefs_data)
    old = places[place]
    if not can_change(old, today):
        return dict(prefs_data or {}), False
    start = old["start"] if old and old["mix"] else today.isoformat()
    places[place] = {"mix": mix, "start": start, "changed": today.isoformat()}
    return _store(prefs_data, places), True


def without_shadow(prefs_data, place: int) -> dict:
    """Removes the mix in `place` (always allowed); its lock date stays, so a
    removal can't be used to change a shadow sooner."""
    places = slots(prefs_data)
    if 0 <= place < MAX_SHADOWS and places[place]:
        places[place] = {"mix": {}, "start": None, "changed": places[place]["changed"]}
    return _store(prefs_data, places)


def cleared(prefs_data) -> dict:
    out = dict(prefs_data or {})
    out.pop(PREF, None)
    return out


# ---- the paths ----------------------------------------------------------- #
def proxies(mix: dict) -> set[str]:
    """The stand-in tickers a mix needs prices for (cash needs none)."""
    return {BY_KIND[k]["proxy"] for k in mix if BY_KIND[k]["proxy"]}


def path(prices: dict, mix: dict, since: str) -> list[tuple[str, float]]:
    """[(date, % change)] of `mix` bought on the first day on or after
    `since` that every needed stand-in has a price, then left alone. `prices`
    is {ticker: [(YYYY-MM-DD, price), ...]} (adjusted close). Cash is flat.
    Empty when a needed series is missing or has no day from `since`."""
    mix = clean_mix(mix)
    if not mix:
        return []
    need = proxies(mix)
    series = {t: {d: float(p) for d, p in (prices.get(t) or []) if p} for t in need}
    if any(not s for s in series.values()):
        return []
    if need:
        days = sorted(set.intersection(*(set(s) for s in series.values())))
    else:   # all cash: flat from the day it was set
        return [(since, 0.0)]
    days = [d for d in days if d >= since]
    if not days:
        return []
    d0 = days[0]
    out = []
    for d in days:
        grown = sum(w / 100 * (series[BY_KIND[k]["proxy"]][d] / series[BY_KIND[k]["proxy"]][d0]
                               if BY_KIND[k]["proxy"] else 1.0)
                    for k, w in mix.items())
        out.append((d, (grown - 1) * 100))
    return out


def real_path(values: list[tuple[str, float]], since: str) -> list[tuple[str, float]]:
    """[(date, % change)] of the person's own line (perf.daily_values) from
    the first day on or after `since`."""
    vals = [(d[:10], float(v)) for d, v in values or [] if v and d[:10] >= since]
    if not vals:
        return []
    v0 = vals[0][1]
    return [(d, (v / v0 - 1) * 100) for d, v in vals]


def change(series: list[tuple[str, float]], through: str | None = None) -> float | None:
    """The % change at the last day on or before `through` (the end of a path)."""
    pts = [p for d, p in series if through is None or d <= through]
    return pts[-1] if pts else None


def last_day(*series_list) -> str | None:
    """The last day every non-empty series has reached (so all lines end together)."""
    ends = [s[-1][0] for s in series_list if s]
    return min(ends) if ends else None


def chart_rows(real: list[tuple[str, float]], shadows: list[tuple[str, list]],
               through: str | None) -> list[dict]:
    """Rows {date, line, pct} for one chart. Your mix from the earliest
    shadow's start; each shadow branches off your line on its own first day
    (its level there times its own growth), or from 0% where your line
    isn't drawn."""
    real_by_day = dict(real)
    rows = [{"date": d, "line": REAL, "pct": p} for d, p in real
            if through is None or d <= through]
    for name, pts in shadows:
        if not pts:
            continue
        base = real_by_day.get(pts[0][0], 0.0)
        for d, p in pts:
            if through is None or d <= through:
                rows.append({"date": d, "line": name,
                             "pct": ((1 + base / 100) * (1 + p / 100) - 1) * 100})
    return rows


def table_rows(real_values: list[tuple[str, float]], shadows: list[dict],
               through: str | None) -> list[dict]:
    """One row per shadow in its place's order (never sorted by change):
    {name, mix, since, shadow, real} - the change since the shadow was set
    and your mix's change over the same days."""
    out = []
    for s in shadows:
        own = real_path(real_values, s["first"]) if s["points"] else []
        out.append({"name": s["name"], "mix": mix_text(s["mix"]), "since": s["changed"],
                    "shadow": change(s["points"], through),
                    "real": change(own, through) if own else None})
    return out


def sample_texts() -> list[str]:
    """Every fixed line with its placeholders filled in, for the banned-word
    and conclusion-policy checks."""
    f = {"proxies": "a broad US stock index fund", "name": "Shadow A", "start": "Oct 6, 2026",
         "changed": "Oct 6, 2026", "next": "Jan 6, 2027", "months": LOCK_MONTHS,
         "through": "Oct 5, 2026", "total": 95, "kind": "US stocks"}
    lines = [TITLE, HYPOTHETICAL, INTRO, PROXY_LINE, REAL_LINE, LOCK_LINE, NONE_YET, NO_PRICES,
             STARTS_SOON, NO_REAL, CHART_NOTE, TABLE_NOTE, SLOT_SET, SLOT_NEXT, SLOT_NOW,
             SLOT_EMPTY_LOCKED, SLOT_EMPTY, TOTAL_LINE, SET_NOTE, KEPT_LINE, EDIT_LABEL,
             NEW_LABEL, SAVE_LABEL, REMOVE_LABEL, CANCEL_LABEL, FIELD_LABEL, REAL, *NAMES,
             *TABLE_COLUMNS]
    lines += [k["label"] for k in KINDS] + [k["about"] for k in KINDS]
    return [s.format(**f) for s in lines]


def all_text() -> str:
    return "\n".join(sample_texts())
