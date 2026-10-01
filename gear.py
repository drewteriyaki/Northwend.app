"""Milestones and gear (ROADMAP T3): the expedition's rewards. Pure logic, no
Streamlit.

Each piece of gear is earned by learning or a steady habit - never by
trading more, taking more risk or chasing returns - and nothing is ever
lost or for sale. Whether one is earned is worked out from what the app
already knows (the profile, the plan, Get started, holdings, money added,
value history); only which ones a person has already been shown is kept,
in their settings, so the "milestone reached" window appears once each.

The icons are line drawings (24 x 24, 1.8 stroke, the design system's
"Milestones and gear"). Streamlit's st.html strips inline SVG, so each is
an image, one per theme (the app's styles show the one that matches).
"""

from __future__ import annotations

import base64
from datetime import date
from html import escape

# key, name, the milestone's title, what earns it, the region (route.REGIONS),
# and the icon's SVG paths
GEAR = (
    ("map", "Map", "Base camp: you know where you're starting",
     "Answer the questions about you.", "Base camp",
     ('<path d="M9 4L3 6v14l6-2 6 2 6-2V4l-6 2z"/>', '<path d="M9 4v14"/>',
      '<path d="M15 6v14"/>')),
    ("compass", "Compass", "First camp: your goal is set",
     "Set a goal.", "The foothills",
     ('<circle cx="12" cy="12" r="9"/>', '<path d="M15.5 8.5l-2 5-5 2 2-5z"/>')),
    ("tent", "Tent", "Learner's ridge: the basics, learned",
     "Learn the basics on the Learn page.", "Learner's ridge",
     ('<path d="M4 19c0-5 3.5-9 8-9s8 4 8 9"/>', '<path d="M12 10V4"/>',
      '<path d="M8 19l4-9 4 9"/>')),
    ("rope", "Rope", "The practice range: tried with practice money",
     "Try the practice money on the Learn page.", "The practice range",
     ('<circle cx="12" cy="12" r="4"/>', '<circle cx="12" cy="12" r="8"/>',
      '<path d="M12 4V3"/>', '<path d="M12 21v-1"/>')),
    ("boots", "Boots", "On the trail: your first statement is in",
     "Bring in your holdings from your brokerage.", "The summit",
     ('<path d="M7 3h5v9l6 3a2 2 0 0 1 1 1.7V19H5V3z"/>', '<path d="M5 15h14"/>')),
    ("lantern", "Lantern", "A steady pace: money added three months running",
     "Add money three months in a row.", None,
     ('<path d="M9 6h6"/>', '<path d="M10 3h4v3h-4z"/>',
      '<rect x="7" y="6" width="10" height="13" rx="3"/>', '<path d="M12 10v5"/>')),
    ("cloak", "Storm cloak", "Storm weathered: you held steady through a drop",
     "Hold steady - no selling - through a 10% drop.", None,
     ('<path d="M3 15h18"/>', '<path d="M6 15c0-4 2.7-7 6-7s6 3 6 7"/>',
      '<path d="M12 4v2"/>', '<path d="M5 9l1.5 1"/>', '<path d="M19 9l-1.5 1"/>')),
    ("flag", "Summit flag", "The summit: you reached your goal",
     "Reach your goal.", "The summit",
     ('<path d="M5 21V4"/>', '<path d="M5 4h11l-2 4 2 4H5"/>')),
)
KEYS = tuple(g[0] for g in GEAR)
BY_KEY = {g[0]: g for g in GEAR}
STORM_DROP_PCT = 10.0
STREAK_MONTHS = 3

# per theme: earned (dawn on dawn-soft) and not yet (line-strong) - the design system's
COLORS = {"light": {"earned": "#a16207", "todo": "#74838f"},
          "dark": {"earned": "#f2bd57", "todo": "#62748a"}}


def _month_index(d: str) -> int:
    return int(d[:4]) * 12 + int(d[5:7]) - 1


def steady_months(dates_added: list[str], today: date) -> bool:
    """Money added in each of STREAK_MONTHS calendar months in a row, ending
    this month or last (`dates_added`: the dates of the additions)."""
    have = {_month_index(d) for d in dates_added if d and len(d) >= 7}
    now = today.year * 12 + today.month - 1
    for end in (now, now - 1):
        if all(end - k in have for k in range(STREAK_MONTHS)):
            return True
    return False


def weathered_storm(values: list[tuple[str, float]], sells: list[str]) -> bool:
    """Held steady through a drop: the portfolio's value (`values`: (date,
    value), any order) fell STORM_DROP_PCT or more below its high, and
    nothing was sold (`sells`: dates) between that high and the low."""
    peak_d, peak = None, None
    worst = None   # (drop %, peak date, low date)
    for d, v in sorted(values):
        if v is None or v <= 0:
            continue
        if peak is None or v > peak:
            peak_d, peak = d, v
            continue
        drop = (peak - v) / peak * 100
        if drop >= STORM_DROP_PCT and (worst is None or drop > worst[0]):
            worst = (drop, peak_d, d)
    if worst is None:
        return False
    _, high, low = worst
    return not any(high[:10] <= (s or "")[:10] <= low[:10] for s in sells)


def earned(facts: dict) -> list[str]:
    """The keys of the gear earned, in kit order. `facts`: profile_done,
    goal_set, basics_done, practice_done, statement_in, steady, storm,
    goal_reached (booleans)."""
    need = {"map": "profile_done", "compass": "goal_set", "tent": "basics_done",
            "rope": "practice_done", "boots": "statement_in", "lantern": "steady",
            "cloak": "storm", "flag": "goal_reached"}
    return [k for k in KEYS if facts.get(need[k])]


def new_since(earned_keys: list[str], seen: list[str] | None) -> tuple[list[str], list[str]]:
    """(gear to celebrate now, the seen list to save). With no seen list yet
    (an account from before gear existed) everything earned so far is taken
    as seen, quietly - no flood of windows on the first visit."""
    if seen is None:
        return [], list(earned_keys)
    fresh = [k for k in earned_keys if k not in seen]
    return fresh, list(seen) + fresh


def icon_html(key: str, is_earned: bool, size: int = 24) -> str:
    """The gear's icon as two images, one per theme, its name as their text."""
    paths = "".join(BY_KEY[key][5])
    name = escape(BY_KEY[key][1] + ("" if is_earned else ", not earned yet"), quote=True)
    out = []
    for theme, c in COLORS.items():
        color = c["earned"] if is_earned else c["todo"]
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="{size}" '
               f'height="{size}" fill="none" stroke="{color}" stroke-width="1.8" '
               f'stroke-linecap="round" stroke-linejoin="round">{paths}</svg>')
        data = base64.b64encode(svg.encode("utf-8")).decode("ascii")
        out.append(f"<img class='pt-gear-icon pt-on-{theme}' width='{size}' height='{size}' "
                   f"alt='{name}' src='data:image/svg+xml;base64,{data}'>")
    return "".join(out)
