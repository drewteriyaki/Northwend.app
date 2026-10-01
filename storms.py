"""Storms (ROADMAP T4): a sharp drop treated as weather to wait out. Pure
logic, no Streamlit.

The check uses the current holdings priced at each day's close (perf's
reconstructed line), so money added or taken out never looks like the
market moving. The note on Home is calm and general - what drops have
looked like before, why long-term investors usually wait them out - and
never says to buy or sell. Holding steady through one earns the storm
cloak (gear.py); nothing is ever earned for selling or buying.
"""

from __future__ import annotations

from datetime import date, timedelta

WINDOW_DAYS = 90     # the high is the highest close in this many days
ROUGH_PCT = 5.0      # "rough weather"
STORM_PCT = 10.0     # "a storm" (the storm cloak's drop too - gear.STORM_DROP_PCT)
MIN_POINTS = 5       # fewer closes than this in the window: too little to say

# Past drops of the S&P 500 (its price, high to low, without dividends;
# rounded): the storm, how far it fell, and how long until the old high
# was passed again.
PAST_STORMS = (
    ("The 1987 crash", 34, "about 2 years"),
    ("The dot-com bust, 2000-02", 49, "about 7 years"),
    ("The financial crisis, 2007-09", 57, "about 5½ years"),
    ("The 2018 slide", 20, "about 7 months"),
    ("The 2020 pandemic drop", 34, "about 6 months"),
    ("The 2022 bear market", 25, "about 2 years"),
)

LEARN_MORE = ("Investor.gov: why a mix of investments softens a drop",
              "https://www.investor.gov/additional-resources/general-resources/"
              "publications-research/info-sheets/beginners-guide-asset")


def weather(points: list[tuple[str, float]], today: date | None = None) -> dict | None:
    """The weather now, or None when it's calm. `points`: (date, value) of
    the holdings at each close, any order. When the latest value is
    ROUGH_PCT or more below the highest of the last WINDOW_DAYS:
    {"level": "rough" | "storm", "drop_pct", "high", "high_date", "now",
    "as_of"}."""
    pts = sorted((d[:10], v) for d, v in points if d and v is not None and v > 0)
    if not pts:
        return None
    end = today or date.fromisoformat(pts[-1][0])
    since = (end - timedelta(days=WINDOW_DAYS)).isoformat()
    pts = [p for p in pts if p[0] >= since]
    if len(pts) < MIN_POINTS:
        return None
    high_date, high = max(pts, key=lambda p: (p[1], p[0]))
    as_of, now = pts[-1]
    drop = (high - now) / high * 100
    if drop < ROUGH_PCT:
        return None
    return {"level": "storm" if drop >= STORM_PCT else "rough", "drop_pct": drop,
            "high": high, "high_date": high_date, "now": now, "as_of": as_of}


def hidden(w: dict | None, hide: dict | None) -> bool:
    """Whether "Hide for now" still covers this weather: the same high, and
    no worse a level than when it was hidden (a storm after rough weather
    shows again, and so does any drop from a new high)."""
    if not w or not hide:
        return False
    rank = {"rough": 1, "storm": 2}
    return (hide.get("high_date") == w["high_date"]
            and rank.get(hide.get("level"), 0) >= rank[w["level"]])
