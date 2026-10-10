"""Your first month (docs/DIRECTION_2026-10-09.md section 6, item 13): a
short checklist for a new investor's first weeks, worked out from what the
app already keeps. Pure logic, no Streamlit; the card on Home's "This month"
is views/first_month.py.

Five steps, each with the day it's aimed at, each earning one piece of gear
in the kit (gear.py) - the same rule as the gear, so the two never disagree:

  start     day 0   the questions about you      the map        (profile_done)
  practice  day 3   practice money on Learn      the rope       (practice_done)
  costs     day 7   what your funds cost         the binoculars (costs_checked)
  goal      day 14  a goal with an amount, date  the compass    (goal_set)
  walk      day 30  the first Monthly Walk       the watch      (first_walk)

The day is only a guide: a step past its day is simply still open - never
"overdue", never a streak, never a colour that scolds. The step shown now is
the first one not done, in order. Someone with no holdings yet is pointed at
practice money and Learn; their walk step points at the route's next Start
investing waypoint (route.py: brokerage -> account opened and funded ->
first investments -> bring them in), since the walk opens only once their
own holdings are in.

What's kept, only for what isn't recorded anywhere else: PREF in the login's
own settings, {"used": ["fees", "decoder", "factsheet"]} - which of the cost
tools was opened, keys only, never a figure, a fund or any words. Reading
"Fees add up" in Learn the basics already counts (recap's learn_reads).

Every line is fixed and the same for everyone, with no figures, so a later
email (once the owner has a postal address for CAN-SPAM) can reuse lines().
"""

from __future__ import annotations

from datetime import date, datetime

import checkin

PREF = "first_month"
TASK = "first_month"                      # its key in home_tasks.TASKS (the X and Done)
USED = ("fees", "decoder", "factsheet")   # the Fee check, the 401(k) Menu Decoder, the Fact Sheet Decoder
READS_PREF = "learn_reads"                # recap.LEARN_READS (a test keeps them in step)
FEES_READ = "basics:fees"                 # Learn the basics' "Fees add up"
SHOW_DAYS = 35                            # the card shows while the account is younger than this

START, PRACTICE, COSTS, GOAL, WALK = "start", "practice", "costs", "goal", "walk"
# key, the day it's aimed at, the gear it earns (gear.py), the fact behind it
STEPS = (
    (START, 0, "map", "profile_done"),
    (PRACTICE, 3, "rope", "practice_done"),
    (COSTS, 7, "binoculars", "costs_checked"),
    (GOAL, 14, "compass", "goal_set"),
    (WALK, 30, "watch", "first_walk"),
)
KEYS = tuple(s[0] for s in STEPS)
GEAR = {k: g for k, _d, g, _f in STEPS}
DAY = {k: d for k, d, _g, _f in STEPS}
FACT = {k: f for k, _d, _g, f in STEPS}

# ---- the fixed words -------------------------------------------------------- #
TITLE = "Your first month"
INTRO = "A few short steps for your first weeks. Each one stays open until you get to it."
GEAR_LINE = "Each step adds a piece of gear to your kit."
NEXT_LEAD = "Next"
COUNT_LINE = "{done} of {total} done"

TITLES = {
    START: "Answer a few questions about you",
    PRACTICE: "Try practice money",
    COSTS: "Check what your funds cost",
    GOAL: "Set a goal",
    WALK: "Take your first Monthly Walk",
}
# when each is aimed at, in words (no numbers)
WHEN = {START: "First day", PRACTICE: "First few days", COSTS: "First week",
        GOAL: "Second week", WALK: "End of the first month"}

WHY = {
    START: "A few taps about your timeline and how you feel about ups and downs.",
    PRACTICE: "Watch a mix rise and fall on real past prices, with pretend money.",
    GOAL: "What you're investing for and roughly when.",
}
COSTS_HELD = "See what the funds you hold charge each year."
COSTS_NONE = "Every fund charges a small yearly fee. A short read in Learn the basics explains it."
WALK_DUE = "A few minutes once a month: your holdings, your mix and one short read."
WALK_LATER = "It shows up here once a month, starting the month after your own holdings came in."
WALK_NO_HOLDINGS = ("It starts once your own holdings are in. Until then, the next step to "
                    "start investing is on Learn.")

# button labels
GO = {START: "Answer the questions", PRACTICE: "Try practice money", GOAL: "Set a goal"}
GO_FEES = "Check fees"
GO_FEES_READ = "Read about fees"
GO_WALK = "Start this month's walk"
GO_INVEST = "Start investing"


# ---- what's kept ------------------------------------------------------------ #

def used(prefs: dict) -> list[str]:
    """The cost tools opened (USED keys only)."""
    kept = (prefs or {}).get(PREF)
    got = kept.get("used") if isinstance(kept, dict) else None
    return [k for k in USED if isinstance(got, list) and k in got]


def note_used(prefs: dict, what: str) -> bool:
    """Remember that a cost tool was opened. Changes `prefs` in place; True
    when it did (so the caller saves only then). Unknown keys are ignored."""
    if what not in USED or what in used(prefs):
        return False
    prefs[PREF] = {"used": [k for k in USED if k in used(prefs) or k == what]}
    return True


def costs_checked(prefs: dict) -> bool:
    """A cost tool was opened, or "Fees add up" was read in Learn the basics."""
    reads = (prefs or {}).get(READS_PREF)
    return bool(used(prefs)) or (isinstance(reads, dict) and FEES_READ in reads)


def first_walk(prefs: dict) -> bool:
    """At least one Monthly Walk finished (checkin.py)."""
    return checkin.count(prefs or {}) >= 1


# ---- the checklist ---------------------------------------------------------- #

def age_days(created_at, today: date) -> int | None:
    """Days since the account was made (users.created_at, 'YYYY-MM-DD ...'),
    or None when it can't be read."""
    if not created_at:
        return None
    try:
        made = datetime.fromisoformat(str(created_at)[:10]).date()
    except ValueError:
        return None
    return max(0, (today - made).days)


def checklist(facts: dict, walk: bool = True) -> list[dict]:
    """The steps in order: {"key", "day", "gear", "title", "when", "done"}.
    `facts`: profile_done, practice_done, costs_checked, goal_set, first_walk
    (booleans). Without the Monthly Walk (`walk` False: its flag is off) its
    step is left out, so nothing points to a walk that isn't there."""
    return [{"key": k, "day": d, "gear": g, "title": TITLES[k], "when": WHEN[k],
             "done": bool((facts or {}).get(f))}
            for k, d, g, f in STEPS if walk or k != WALK]


def current(steps: list[dict]) -> dict | None:
    """The step to show now: the first not done, in order (None: all done)."""
    return next((s for s in steps if not s["done"]), None)


QUIET_GEAR = ("binoculars", "watch")   # the pieces that came with this (gear.NEEDS_FIRST_MONTH)


def quiet_for(fresh: list[str], age: int | None) -> list[str]:
    """The gear to celebrate, from gear.new_since()'s `fresh`: the binoculars
    and the watch only for an account still in its first month (the card's
    own age rule). Older accounts - or one whose age can't be read - had what
    earns them before the feature arrived, so those two are taken quietly
    (still kept as seen); every other piece is unchanged."""
    if age is not None and age < SHOW_DAYS:
        return list(fresh)
    return [k for k in fresh if k not in QUIET_GEAR]


def shown(age: int | None, steps: list[dict]) -> bool:
    """Whether the card shows: a young account (under SHOW_DAYS days) with a
    step still open."""
    return age is not None and age < SHOW_DAYS and current(steps) is not None


def why(key: str, *, has_funds: bool = False, real_holdings: bool = False,
        walk_due: bool = False) -> str:
    """The one line under the next step."""
    if key == COSTS:
        return COSTS_HELD if has_funds else COSTS_NONE
    if key == WALK:
        if walk_due:
            return WALK_DUE
        return WALK_LATER if real_holdings else WALK_NO_HOLDINGS
    return WHY[key]


def action(key: str, *, has_funds: bool = False, walk_due: bool = False,
           real_holdings: bool = False, invest_next: str | None = None):
    """(button label, where) for the next step, or None when there's nothing
    to press yet. `where`: ("learn", Get started waypoint) | ("fees", None):
    the Fee check window | ("checkin", None): Home with the walk open.
    `invest_next`: the route's next Start investing waypoint, if any."""
    if key in GO:
        return GO[key], ("learn", {START: "profile", PRACTICE: "practice", GOAL: "goal"}[key])
    if key == COSTS:
        return (GO_FEES, ("fees", None)) if has_funds else (GO_FEES_READ, ("learn", "basics"))
    if walk_due:
        return GO_WALK, ("checkin", None)
    if not real_holdings and invest_next:
        return GO_INVEST, ("learn", invest_next)
    return None


def lines(steps: list[dict], **ctx) -> dict:
    """The card's words (and a later email's): {"title", "intro", "count",
    "items": [(when, title, done)], "next", "why", "gear"} - fixed lines
    only, the same for everyone."""
    nxt = current(steps)
    return {"title": TITLE, "intro": INTRO,
            "count": COUNT_LINE.format(done=sum(1 for s in steps if s["done"]),
                                       total=len(steps)),
            "items": [(s["when"], s["title"], s["done"]) for s in steps],
            "next": nxt["title"] if nxt else "",
            "why": why(nxt["key"], **ctx) if nxt else "",
            "gear": GEAR_LINE}


def templates() -> list[str]:
    """Every fixed line, for the wording tests."""
    return [TITLE, INTRO, GEAR_LINE, NEXT_LEAD, *TITLES.values(), *WHEN.values(),
            *WHY.values(), COSTS_HELD, COSTS_NONE, WALK_DUE, WALK_LATER, WALK_NO_HOLDINGS,
            *GO.values(), GO_FEES, GO_FEES_READ, GO_WALK, GO_INVEST]
