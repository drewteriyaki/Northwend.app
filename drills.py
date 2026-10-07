"""Preparedness drills (ROADMAP R12, the one-week test; flag `drills`). Pure
content and logic, no Streamlit, no database.

Ten short, tap-only situations - hard times and good times with equal
weight - that a person rehearses one a week on Home (views/drills.py). Each
drill is a situation in plain words; with the person's own mix and timeline
in percentages and words only (never an amount, a ticker or an account
name), or for someone not investing yet, the same situation without a mix.
Then two to four taps: things the person would weigh or ask - never a
trade, and never marked as a good or poor choice. After a tap, a short
"things people often think about here" note (education) and NO_RIGHT_ANSWER.

The readiness map (which of the ten are rehearsed, hard times and good
times) is the pull, not a streak: a weekly count of weeks rehearsed is shown
gently and never breaks. One drill is suggested per ISO week (the next one
not rehearsed yet; once all ten are, the one rehearsed longest ago comes
back with its twist). No reminders of its own; the opt-in Trail Conditions
email (trail_conditions.py) may say, at most every few weeks, that one
situation on the readiness map is waiting - never which, never a tap.

What's kept (prefs PREF), keys only - never free text:
  {"done": {drill key: {"choice": tap key, "week": "2026-W41", "times": n}},
   "weeks": ["2026-W40", "2026-W41"]}
The tapped choice is the person's own: never shown to an advisor, never in
an advisor's client record, never sent to the AI.
"""

from __future__ import annotations

from datetime import date, timedelta

PREF = "drills"
GEAR_AT = 3          # drills rehearsed for the gear (gear.py, "whistle"); the metric's "third drill"
HARD, GOOD = "hard", "good"
SIDES = ((HARD, "Hard times"), (GOOD, "Good times"))

THINK_LEAD = "Things people often think about here"
NO_RIGHT_ANSWER = ("There's no right answer on an investment choice - a drill is about "
                   "knowing what you'd weigh, before you need to.")
BEGINNER_LINE = ("You haven't invested yet, and that's fine - picture it as if you had. "
                 "Rehearsing before the first dollar makes it familiar later.")
INTRO = ("A short situation to rehearse, once a week: tap what you'd weigh first. "
         "Nothing is graded, and nothing here buys or sells anything.")

# key, side, title, situation, lens (which part of their own picture it
# brings in: "stocks", "cash" or None), choices ((key, words), 2-4), the
# note after a tap, and the twist when it comes back.
DRILLS = (
    ("drop", HARD, "A sharp market drop",
     "Imagine the stock market falls sharply over a few weeks and stays down for a while. "
     "The news is gloomy and everyone seems to have an opinion.",
     "stocks",
     (("plan", "I'd look at my plan and my timeline before changing anything"),
      ("when", "I'd want to know when I'll actually need this money"),
      ("talk", "I'd want to talk it through with someone I trust first")),
     "A drop matters most for money that's needed soon, so people often start with when "
     "they'll need it. Many also notice how they feel: drops are a normal part of "
     "investing, and nobody knows in advance how long one will last. Some write down "
     "ahead of time what they'd do, so a drop isn't the moment they decide.",
     "This time, imagine the drop comes not long before you planned to use some of the "
     "money."),
    ("raise", GOOD, "A raise",
     "Imagine you get a raise at work.",
     None,
     (("split", "I'd think about splitting it between spending, saving and investing"),
      ("match", "I'd check whether I'm getting all of any employer match"),
      ("goal", "I'd look at whether it changes my goal or its date")),
     "A common idea is choosing what share of a raise goes to saving before it reaches "
     "the budget, so everyday spending doesn't quietly absorb all of it. People also "
     "look at any employer match, their emergency savings and any high-interest debt.",
     "This time, imagine the raise comes with a move to a new employer and a new "
     "workplace retirement plan."),
    ("job", HARD, "Losing a job",
     "Imagine your job ends unexpectedly, and finding the next one takes a while.",
     "cash",
     (("fund", "I'd want to know how long my emergency savings would last"),
      ("costs", "I'd look at which costs I could pause or trim"),
      ("invest", "I'd want to understand what using my investments would mean - taxes, "
                 "timing - before doing it")),
     "People often start with the emergency fund: how long it covers the essentials. "
     "Others think about health coverage, any severance or unemployment benefits, and "
     "which bills could wait. A retirement plan from that job is a separate question "
     "that can usually wait for a calmer moment.",
     "This time, imagine the job ends while the market is down too."),
    ("bonus", GOOD, "A bonus",
     "Imagine a one-time bonus lands in your account.",
     None,
     (("debt", "I'd look at any high-interest debt first"),
      ("fund", "I'd check whether my emergency savings are where I want them"),
      ("enjoy", "I'd set aside some of it to enjoy, guilt-free")),
     "Bonuses are often taxed when they're paid, so what arrives can be smaller than "
     "the number announced. People often make a plan for it before it lands - including "
     "a share to enjoy - so the decision isn't made in the moment.",
     "This time, imagine the bonus is paid partly in your employer's shares."),
    ("expense", HARD, "A surprise expense",
     "Imagine a big bill you didn't plan for arrives - a car repair, a medical bill or "
     "a home repair.",
     "cash",
     (("fund", "I'd check whether my emergency savings cover it"),
      ("order", "I'd think about which money to use first, and what each choice costs"),
      ("ask", "I'd ask whether the bill can be paid over time without interest")),
     "People often think about the order they'd reach for money: emergency savings "
     "first, then other cash, with investments and high-interest credit further down "
     "the list because of taxes, timing or interest. Asking about a payment plan, or "
     "checking what insurance covers, is common too.",
     "This time, imagine the bill arrives in a month when the market is down."),
    ("windfall", GOOD, "A windfall",
     "Imagine you receive a large sum you didn't expect - an inheritance, a gift or "
     "money from a sale.",
     None,
     (("wait", "I'd give myself time before deciding anything"),
      ("taxes", "I'd want to understand any taxes first"),
      ("pro", "I'd want to talk to a professional, like a tax professional or an "
              "advisor")),
     "Many people give themselves a pause before big decisions about a windfall. "
     "Common questions: are there taxes, does it change my goals or timeline, and is it "
     "a one-time sum? An inheritance can come with its own rules, so asking the "
     "executor or a tax professional is common.",
     "This time, imagine the windfall is an investment account rather than cash."),
    ("fund_closing", HARD, "A fund closing",
     "Imagine a letter arrives saying one of your funds is closing, or merging into "
     "another fund.",
     None,
     (("letter", "I'd read what happens to my money, and when"),
      ("admin", "I'd ask my brokerage or plan administrator what happens if I do "
                "nothing"),
      ("taxes", "I'd want to know whether there are any tax effects")),
     "The letter usually says what happens to the money - often it's paid out as cash "
     "or moved into another fund. People often ask what happens if they do nothing, "
     "whether it counts as a sale for taxes in a taxable account, and how any "
     "replacement compares on fees and what it holds.",
     "This time, imagine it's a fund in a workplace retirement plan, where the plan "
     "picks the replacement."),
    ("goal_early", GOOD, "A goal reached early",
     "Imagine your investments reach your goal's amount well before the date you set.",
     "stocks",
     (("when", "I'd ask myself when I actually need the money now"),
      ("next", "I'd think about what my next goal is"),
      ("mix", "I'd look at whether my mix still fits my timeline")),
     "Reaching a goal early raises a fresh question: is the money still for that goal "
     "and that date? People often think about how much up and down still makes sense "
     "now that the amount is there, and what comes next. Enjoying the moment is part "
     "of it too.",
     "This time, imagine the goal is reached, and then the market dips the next month."),
    ("prices", HARD, "Prices rising fast",
     "Imagine everyday prices climb quickly for a while - groceries, rent, fuel.",
     "cash",
     (("budget", "I'd look at my budget before my investments"),
      ("cash", "I'd think about how much I keep in cash, and what it earns"),
      ("goal", "I'd check whether my goal's amount still fits")),
     "Rising prices shrink what cash buys over time, so people often think about how "
     "much they keep in cash beyond their emergency savings. Many also revisit a goal's "
     "amount, since the same goal can cost more later. Different kinds of investments "
     "react differently, and nobody knows how long a stretch like this will last.",
     "This time, imagine prices rise while your pay stays the same."),
    ("strong_year", GOOD, "A strong year for markets",
     "Imagine the market has a great year and your investments grow more than you "
     "expected. Friends are talking about whatever has been going up.",
     "stocks",
     (("drift", "I'd look at how far my mix has moved from my target"),
      ("chase", "I'd notice whether I'm tempted to chase what's been rising"),
      ("why", "I'd remind myself why I chose my plan in the first place")),
     "After a strong run, a mix often drifts toward more stocks than planned, which "
     "changes how bumpy it is. People also notice the pull to chase what has recently "
     "gone up; past gains don't tell anyone what comes next.",
     "This time, imagine one fund you hold grew much faster than the rest."),
)
KEYS = tuple(d[0] for d in DRILLS)
BY_KEY = {d[0]: d for d in DRILLS}


def side_of(key: str) -> str:
    return BY_KEY[key][1]


def title_of(key: str) -> str:
    return BY_KEY[key][2]


def choices_of(key: str) -> tuple[tuple[str, str], ...]:
    return BY_KEY[key][5]


def choice_words(key: str, choice: str) -> str | None:
    return dict(choices_of(key)).get(choice)


def think_of(key: str) -> str:
    return BY_KEY[key][6]


def twist_of(key: str) -> str:
    return BY_KEY[key][7]


# ---- the person's own picture, in percentages and words only --------------- #

# (the upper end in years, words) - a timeline in words, never a figure
TIMELINE_WORDS = ((3, "a short way off - a few years or less"),
                  (10, "a middle distance away - several years"),
                  (None, "a long way off - many years"))


def timeline_words(years: float | None) -> str | None:
    """Their timeline in words (TIMELINE_WORDS), or None when unknown."""
    if years is None:
        return None
    try:
        y = float(years)
    except (TypeError, ValueError):
        return None
    if y <= 0:
        return None
    for top, words in TIMELINE_WORDS:
        if top is None or y < top:
            return words
    return None


def _whole(pct) -> int | None:
    try:
        v = float(pct)
    except (TypeError, ValueError):
        return None
    if v != v or v < 0 or v > 100:   # NaN or out of range
        return None
    return int(round(v))


def picture(key: str, mix: dict | None, years: float | None) -> list[str]:
    """The lines that bring the situation to their own picture: the share of
    their mix the drill is about (whole percent, by asset class - the lens)
    and their timeline in words. `mix` is {asset class: percent} or None for
    someone with no real holdings - then BEGINNER_LINE instead of a mix."""
    out = []
    lens = BY_KEY[key][4]
    if not mix:
        out.append(BEGINNER_LINE)
    elif lens == "stocks":
        s = _whole(mix.get("Stocks"))
        if s is not None:
            out.append(f"In your own mix, about {s}% is in stocks - the part that usually "
                       "moves most, down and up.")
    elif lens == "cash":
        c = _whole(mix.get("Cash"))
        if c is not None:
            out.append(f"Of what you hold here, about {c}% is cash.")
    words = timeline_words(years)
    if words:
        out.append(f"Your goal is {words}.")
    return out


# ---- what's kept, and the weekly cadence ------------------------------------ #

def iso_week(d: date) -> str:
    """'2026-W41' - the ISO week (Monday to Sunday) a day is in."""
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def week_start(d: date) -> date:
    """The Monday of a day's ISO week."""
    return d - timedelta(days=d.weekday())


def next_week_start(d: date) -> date:
    return week_start(d) + timedelta(days=7)


def _is_week(w) -> bool:
    if not isinstance(w, str) or len(w) != 8 or w[4:6] != "-W":
        return False
    try:
        return 1 <= int(w[6:]) <= 53 and int(w[:4]) > 2000
    except ValueError:
        return False


def clean(raw) -> dict:
    """The kept state with anything unknown dropped: only known drill and
    choice keys, ISO weeks and counts - never text the person typed."""
    raw = raw if isinstance(raw, dict) else {}
    done = {}
    for k, v in (raw.get("done") or {}).items() if isinstance(raw.get("done"), dict) else ():
        if k not in BY_KEY or not isinstance(v, dict):
            continue
        choice = v.get("choice") if v.get("choice") in dict(choices_of(k)) else None
        week = v.get("week") if _is_week(v.get("week")) else None
        if choice is None or week is None:
            continue
        times = v.get("times")
        times = times if isinstance(times, int) and not isinstance(times, bool) and times > 0 else 1
        done[k] = {"choice": choice, "week": week, "times": times}
    weeks = sorted({w for w in raw.get("weeks") or [] if _is_week(w)}
                   | {v["week"] for v in done.values()})
    return {"done": done, "weeks": weeks}


def state(p: dict | None) -> dict:
    return clean((p or {}).get(PREF))


def rehearsed(p: dict | None) -> list[str]:
    """The drills rehearsed at least once, in DRILLS order."""
    done = state(p)["done"]
    return [k for k in KEYS if k in done]


def count(p: dict | None) -> int:
    return len(rehearsed(p))


def weeks_rehearsed(p: dict | None) -> int:
    """The gentle weekly count: how many weeks had a drill done. It only
    grows - a week without one costs nothing."""
    return len(state(p)["weeks"])


def done_this_week(p: dict | None, today: date) -> str | None:
    """The drill done in today's week, or None."""
    week = iso_week(today)
    done = state(p)["done"]
    return next((k for k in KEYS if done.get(k, {}).get("week") == week), None)


def suggested(p: dict | None, today: date) -> tuple[str, bool]:
    """(this week's drill, whether it's a repeat with its twist): the one
    done this week if any; else the first not rehearsed yet (hard and good
    in turn, DRILLS order); once all ten are rehearsed, the one done longest
    ago comes back."""
    s = state(p)
    this = done_this_week(p, today)
    if this:
        return this, s["done"][this]["times"] > 1
    todo = [k for k in KEYS if k not in s["done"]]
    if todo:
        return todo[0], False
    oldest = min(KEYS, key=lambda k: (s["done"][k]["week"], KEYS.index(k)))
    return oldest, True


def record(p: dict, key: str, choice: str, today: date) -> bool:
    """Keep a tap: this week's drill and the key of what they'd weigh. One
    drill a week - a different drill in a week that already has one isn't
    kept; tapping again on this week's drill changes the choice. Changes
    `p`; True when something was kept."""
    if key not in BY_KEY or choice not in dict(choices_of(key)):
        return False
    s = state(p)
    week = iso_week(today)
    this = done_this_week(p, today)
    if this and this != key:
        return False
    prev = s["done"].get(key)
    times = (prev["times"] if prev and prev["week"] == week
             else (prev["times"] + 1 if prev else 1))
    s["done"][key] = {"choice": choice, "week": week, "times": times}
    if week not in s["weeks"]:
        s["weeks"] = sorted(s["weeks"] + [week])
    p[PREF] = s
    return True


def chosen(p: dict | None, key: str) -> str | None:
    """The person's own tap for a drill (their eyes only)."""
    return state(p)["done"].get(key, {}).get("choice")


def readiness(p: dict | None) -> list[tuple[str, str, list[tuple[str, str, bool]]]]:
    """The readiness map: [(side, its label, [(drill key, title, rehearsed)])],
    hard times then good times."""
    have = set(rehearsed(p))
    return [(side, label, [(k, title_of(k), k in have) for k in KEYS if side_of(k) == side])
            for side, label in SIDES]


def third_done(p: dict | None) -> bool:
    """Rehearsed at least GEAR_AT drills (the gear, and R12's metric)."""
    return count(p) >= GEAR_AT


def weeks_text(n: int) -> str:
    """'Weeks you've rehearsed: 3' - a count that only grows."""
    return f"Weeks you've rehearsed: {n}"


def all_text() -> str:
    """Every word the drills show (for the wording tests)."""
    parts = [THINK_LEAD, NO_RIGHT_ANSWER, BEGINNER_LINE, INTRO]
    parts += [w for _, w in TIMELINE_WORDS]
    for key, _side, title, situation, _lens, choices, think, twist in DRILLS:
        parts += [title, situation, think, twist] + [w for _, w in choices]
    return "\n".join(parts)
