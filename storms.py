"""Storms (ROADMAP T4): a sharp drop treated as weather to wait out. Pure
logic, no Streamlit.

The check uses the current holdings priced at each day's close (perf's
reconstructed line), so money added or taken out never looks like the
market moving. The note on Home is calm and general - what drops have
looked like before, why long-term investors usually wait them out - and
never says to buy or sell. Holding steady through one earns the storm
cloak (gear.py); nothing is ever earned for selling or buying.

The narrator (docs/AI_PLAN.md section 9, row 4 - rules, not AI): every
word on the storm note and in "What storms have looked like" is a fixed
template here (narrate(), WINDOW_CAPTION, WINDOW_NOTE), filled only from
weather() and PAST_STORMS. History in the past tense, never a prediction:
no "will recover", no "soon", no bottom called (a test checks every
template). AI narration about markets would risk predicting.
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
# (the storms window's "Learn more" is learn.LEARN_MORE["market_drops"])

# ---- the narrator: fixed words only ------------------------------------------ #
TITLES = {"storm": "A storm on the trail", "rough": "Rough weather"}
BODIES = {
    "storm": "Drops of 10% or more have come along about once every year or two on "
             "average, and the market has climbed past every one so far - sometimes in "
             "months, sometimes in years.",
    "rough": "Dips like this have come a few times in a typical year, and most passed "
             "without much notice.",
}
# (COPY_AUDIT.md "Same problem" 19: describes, never a hold message)
STEADY = ("Drops like this are part of investing. Your plan's target and dates haven't "
          "changed; they're on the Plan page.")
WINDOW_CAPTION = ("The S&P 500 - the 500 largest US companies - from its high to its low, "
                  "and how long until it passed that high again. Rounded; its price without "
                  "dividends.")
WINDOW_NOTE = ("Every one of these passed, though some took years - and nobody knew at the "
               "time how long it would last. That's why people investing for goals years "
               "away often plan for storms instead of trying to dodge them: selling after a "
               "fall turns a drop on paper into a real loss, and some of the market's "
               "strongest days have come within days of its weakest. Past storms don't promise "
               "what the next one will do.")


def _iso_date(d) -> str:
    return str(d)[:10]


def narrate(w: dict, fmt_date=_iso_date) -> dict:
    """The storm note's words for weather() `w`: {"title", "lead", "body",
    "steady"} - fixed templates with the drop (whole percent) and two dates
    filled in. `fmt_date` turns an ISO date into words (the app's
    _fmt_date)."""
    level = "storm" if w["level"] == "storm" else "rough"
    lead = (f"Your holdings are about {w['drop_pct']:.0f}% below their high on "
            f"{fmt_date(w['high_date'])} (as of the close on {fmt_date(w['as_of'])}).")
    return {"title": TITLES[level], "lead": lead, "body": BODIES[level], "steady": STEADY}


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
