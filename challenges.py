"""This month's practice challenge (flag challenges; views/challenges.py).

Practice money - pretend dollars - on real past prices, one month at a time.
Each challenge is a fixed script, the same for everyone: a name, a start
month, a length, the pretend money put in, and a broad stand-in mix of two
KINDS of funds (a broad US stock index fund and a broad US bond index fund,
learn.KINDS). The prices are those of the practice portfolio's stand-in for
each kind (learn.PRACTICE_TICKERS, PRACTICE_PART here), read by the view from
what daily_bars already holds; nothing is fetched for a challenge. This
module only knows the two parts, never a ticker. A challenge whose months
aren't all there is shown as not ready yet (available()).

At the start the person picks their own rule: how much in stocks (one of
RULES, the same choices for everyone - never worked out from their answers)
and to bring it back when it's more than BAND points off. Each step shows
the practice value up to that month and asks what their rule says. The
score is only whether they did what their own rule said ("Followed your
rule: 12 of 13 months") - never how much the practice money made, never a
ranking or a comparison with anyone. No leaderboard.

What's kept, in the login's own settings (prefs PREF): per challenge, the
rule's key, the step reached, the answers as choice keys and the day it was
finished. Never an amount, never free text.

Pure: no Streamlit, no database (a test checks - the layer rule).
"""

from __future__ import annotations

from datetime import date

PREF = "challenges"
STOCKS, BONDS = "stocks", "bonds"   # the practice mix's two parts
STAND_INS = (STOCKS, BONDS)
# each part -> the learn.BLOCKS key whose practice stand-in prices it
# (learn.PRACTICE_TICKERS; the view maps them - learn isn't imported here)
PRACTICE_PART = {STOCKS: "us", BONDS: "bonds"}
# the kinds of funds, as learn.KINDS words them (a test keeps them in step)
KIND_WORDS = {STOCKS: "a broad US stock index fund", BONDS: "a broad US bond index fund"}
BAND = 5   # points away from the target before the rule says bring it back

# the rule's choices: key -> percent in stocks (the rest in bonds)
RULES = {"s80": 80, "s70": 70, "s60": 60, "s40": 40}

# the answers, as keys; words in choice_words()
REBALANCE, DEPOSITS, SELL, NOTHING = "rebalance", "deposits", "sell", "nothing"
CHOICES = (REBALANCE, DEPOSITS, SELL, NOTHING)

# the fixed scripts. start: the first month (YYYY-MM); months: how many
# months it runs after that; every: months between checks; initial and
# monthly: pretend dollars.
CHALLENGES = (
    {"key": "y2008", "title": "Ride out 2008 with your plan", "start": "2007-07",
     "months": 24, "every": 1, "initial": 10000, "monthly": 100,
     "about": "A pretend $10,000 in mid-2007, plus $100 a month, through two years of real "
              "past prices, one month at a time."},
    {"key": "y2020", "title": "The sudden drop of 2020", "start": "2019-07",
     "months": 24, "every": 1, "initial": 10000, "monthly": 100,
     "about": "A pretend $10,000 in mid-2019, plus $100 a month, through two years that held "
              "one of the fastest falls on record, one month at a time."},
    {"key": "y2022", "title": "When stocks and bonds fell together", "start": "2021-07",
     "months": 24, "every": 1, "initial": 10000, "monthly": 100,
     "about": "A pretend $10,000 in mid-2021, plus $100 a month, through two years when both "
              "kinds of funds went down at once, one month at a time."},
    {"key": "first100", "title": "Your first $100 a month, for 5 years", "start": "2018-01",
     "months": 60, "every": 3, "initial": 0, "monthly": 100,
     "about": "A pretend $100 a month from nothing in 2018, checked every three months for "
              "five years of real past prices."},
)
BY_KEY = {c["key"]: c for c in CHALLENGES}
KEYS = tuple(BY_KEY)

# ---- the words (fixed; every one is checked by the wording tests) ---------- #
EYEBROW = "{month} challenge · practice money, not real"
CHART_LABEL = "Practice money, past prices, not a prediction"
PICK_TITLE = "Pick your rule before you start"
PICK_HELP = ("How much of the practice money goes in stocks; the rest goes in bonds. These "
             "choices are the same for everyone, for practice only.")
RULE_WORDS = "{pct}% stocks"
RULE_LINE = "Your rule: {pct}% stocks, check {every}"
RULE_BAND = "Bring it back when stocks are more than {band} points away from {pct}%."
QUESTION = "Stocks are now {now}% of your practice portfolio. What does your rule say?"
STEP_LINE = "{unit_cap} {at} of {total} · {when}"
SAID_MOVE = "Your rule said bring it back: stocks were {pts} points away from {pct}%."
SAID_STAY = "Your rule said leave it: stocks were within {band} points of {pct}%."
YOU_FOLLOWED = "You followed your rule."
YOU_DIDNT = "This time you went another way than your rule."
SCORED_TITLE = "How it's scored"
SCORED = ("On sticking to the rule you picked at the start, not on how much the practice "
          "money made. Nobody wins by taking big bets.")
FOLLOWED = "Followed your rule: {n} of {m} {unit}"
NOT_STARTED = "Not started yet"
FINISHED = "Finished {day}."
ENDS = "Ends {day}"
NEXT = "Next month: \"{title}\""
NOT_READY = ("Not ready yet: this one needs past prices from {first} to {last}, and they "
             "aren't all here yet.")
NONE_READY = ("The practice challenges use past prices that aren't loaded yet. The \"Load "
              "price history\" button in practice money on Learn brings in ten years of them.")
MIX_LINE = ("The practice mix is two kinds of funds: {stocks} and {bonds}. One widely held "
            "fund stands in for each kind's real past prices, dividends included.")
FOOTER = ("Practice money only: nothing here is bought or sold for you, and none of it is a "
          "suggestion for your own money. No fees or taxes are counted. Past prices don't "
          "say what comes next.")
CARD_OPEN = "Open the challenge"
CARD_GO_ON = "Keep going"
AGAIN = "Start this one again"
START = "Start"
OTHERS = "Choose a challenge - earlier ones can be tried again"
SECTION = "This month's practice challenge"
NOT_READY_TAG = "not ready yet"

_EVERY = {1: "monthly", 3: "every three months"}


def choice_words(choice: str, ch: dict, pct: int, low: str) -> str:
    """The words on an answer's button. `low`: the part below its target
    ("stocks" or "bonds")."""
    return {REBALANCE: f"Bring it back to {pct}%",
            DEPOSITS: f"Send new deposits to {low}",
            SELL: "Cash out of everything",
            NOTHING: "Do nothing this month" if ch["every"] == 1 else "Do nothing this time",
            }[choice]


def mix_line() -> str:
    return MIX_LINE.format(stocks=KIND_WORDS[STOCKS], bonds=KIND_WORDS[BONDS])


def unit(ch: dict) -> str:
    return "months" if ch["every"] == 1 else "checks"


def every_words(ch: dict) -> str:
    return _EVERY.get(ch["every"], f"every {ch['every']} months")


def steps(ch: dict) -> int:
    """How many checks the challenge has."""
    return ch["months"] // ch["every"]


# ---- months and prices ------------------------------------------------------ #
def _add(month: str, n: int) -> str:
    y, m = int(month[:4]), int(month[5:7]) - 1 + n
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}"


def months_of(ch: dict) -> list[str]:
    """Every month the challenge uses, YYYY-MM: the start, then `months` more."""
    return [_add(ch["start"], i) for i in range(ch["months"] + 1)]


def monthly_points(prices: dict) -> dict:
    """{YYYY-MM: (date, {part: price})} - the first day of each month on
    which both parts have a price. `prices`: {part: [(date, price)]}, each
    part's stand-in as perf.full_adjusted_closes gives it (adjusted closes)."""
    by = {t: dict(prices.get(t) or []) for t in STAND_INS}
    if not all(by.values()):
        return {}
    days = sorted(set.intersection(*(set(d) for d in by.values())))
    out = {}
    for d in days:
        m = d[:7]
        if m not in out:
            out[m] = (d, {t: float(by[t][d]) for t in STAND_INS})
    return out


def available(ch: dict, points: dict) -> bool:
    """Whether every month the challenge uses has prices here."""
    return all(m in points for m in months_of(ch))


def available_keys(points: dict) -> list[str]:
    return [c["key"] for c in CHALLENGES if available(c, points)]


def of_month(keys: list[str], d: date) -> str | None:
    """The challenge highlighted in `d`'s month: the ready ones in turn,
    one a month. None when none is ready."""
    if not keys:
        return None
    return keys[(d.year * 12 + d.month - 1) % len(keys)]


def next_of_month(keys: list[str], d: date) -> str | None:
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return of_month(keys, nxt)


def month_end(d: date) -> date:
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return date.fromordinal(nxt.toordinal() - 1)


# ---- what they kept --------------------------------------------------------- #
def entry(p: dict, key: str) -> dict | None:
    """Their kept state for a challenge, cleaned: {"rule", "step",
    "answers", "done"?} - None if not started (or anything unknown)."""
    kept = (p or {}).get(PREF)
    e = kept.get(key) if isinstance(kept, dict) else None
    if key not in BY_KEY or not isinstance(e, dict) or e.get("rule") not in RULES:
        return None
    answers = [a for a in (e.get("answers") or []) if a in CHOICES][:steps(BY_KEY[key])]
    out = {"rule": e["rule"], "step": len(answers), "answers": answers}
    if isinstance(e.get("done"), str) and len(answers) == steps(BY_KEY[key]):
        out["done"] = e["done"][:10]
    return out


def _put(p: dict, key: str, e: dict | None) -> dict:
    out = dict(p)
    kept = {k: v for k, v in (out.get(PREF) or {}).items() if k in BY_KEY and isinstance(v, dict)}
    if e is None:
        kept.pop(key, None)
    else:
        kept[key] = e
    if kept:
        out[PREF] = kept
    else:
        out.pop(PREF, None)
    return out


def started(p: dict, key: str, rule: str) -> dict:
    """A copy of `p` with the challenge begun under `rule` (from step 0)."""
    if key not in BY_KEY or rule not in RULES:
        return dict(p)
    return _put(p, key, {"rule": rule, "step": 0, "answers": []})


def answered(p: dict, key: str, choice: str, today: date) -> dict:
    """A copy of `p` with the next step's answer kept; the last one also
    keeps the day it was finished."""
    e = entry(p, key)
    if e is None or choice not in CHOICES or e["step"] >= steps(BY_KEY[key]):
        return dict(p)
    answers = e["answers"] + [choice]
    new = {"rule": e["rule"], "step": len(answers), "answers": answers}
    if len(answers) == steps(BY_KEY[key]):
        new["done"] = today.isoformat()
    return _put(p, key, new)


def cleared(p: dict, key: str) -> dict:
    """A copy of `p` without the challenge (Start this one again)."""
    return _put(p, key, None)


# ---- playing it out --------------------------------------------------------- #
def rule_says(stocks_pct: float, target: int, monthly: float) -> set[str]:
    """What the rule accepts at a check: within BAND points, leave it;
    further, bring it back - by moving money across, or, when money is going
    in each month, by sending it to the part that's low."""
    if abs(stocks_pct - target) > BAND:
        return {REBALANCE, DEPOSITS} if monthly else {REBALANCE}
    return {NOTHING}


def play(ch: dict, points: dict, rule: str, answers: list[str]) -> dict:
    """Replay the challenge with the answers given so far. Returns
    {"rows": [{date, money_in, value, stocks_pct}] up to now, "checks":
    [{step, month, stocks_pct, said, answer, followed}], "pending": the
    next check {step, month, date, stocks_pct, low} or None when finished}.

    The pretend money: `initial` plus the first `monthly` in at the start,
    split by the rule's target; each later month `monthly` more, split by the
    target - except at a check, where the answer decides: bring it back
    (everything back to the target), send the deposit to the low part, cash out of
    everything (into cash, which then stays flat) or do nothing."""
    target = RULES[rule]
    t = target / 100
    months = months_of(ch)
    units = {STOCKS: 0.0, BONDS: 0.0}
    cash, money_in = 0.0, 0.0
    rows, checks, pending = [], [], None

    def value(px):
        return units[STOCKS] * px[STOCKS] + units[BONDS] * px[BONDS] + cash

    def split(amount, px, share):
        units[STOCKS] += amount * share / px[STOCKS]
        units[BONDS] += amount * (1 - share) / px[BONDS]

    def pct(px):
        v = value(px)
        return units[STOCKS] * px[STOCKS] / v * 100 if v else 0.0

    for i, m in enumerate(months):
        d, px = points[m]
        deposit = ch["initial"] + ch["monthly"] if i == 0 else ch["monthly"]
        if i and i % ch["every"] == 0:
            k = i // ch["every"]
            now = pct(px)
            if k > len(answers):
                rows.append({"date": d, "money_in": money_in, "value": value(px),
                             "stocks_pct": now})
                pending = {"step": k, "month": m, "date": d, "stocks_pct": now,
                           "low": "stocks" if now < target else "bonds"}
                break
            a = answers[k - 1]
            said = rule_says(now, target, ch["monthly"])
            checks.append({"step": k, "month": m, "stocks_pct": now,
                           "move": REBALANCE in said, "answer": a, "followed": a in said})
            money_in += deposit
            if a == REBALANCE:
                total = value(px) + deposit
                units[STOCKS] = total * t / px[STOCKS]
                units[BONDS] = total * (1 - t) / px[BONDS]
                cash = 0.0
            elif a == DEPOSITS:
                split(deposit, px, 1.0 if now < target else 0.0)
            elif a == SELL:
                cash = value(px) + deposit
                units[STOCKS] = units[BONDS] = 0.0
            else:
                split(deposit, px, t)
        else:
            money_in += deposit
            split(deposit, px, t)
        rows.append({"date": d, "money_in": money_in, "value": value(px), "stocks_pct": pct(px)})
    return {"rows": rows, "checks": checks, "pending": pending}


def score(checks: list[dict]) -> tuple[int, int]:
    """(followed, out of): only whether each answer was what their own rule
    said - never anything about the money."""
    return sum(1 for c in checks if c["followed"]), len(checks)


def followed_line(ch: dict, checks: list[dict]) -> str:
    n, m = score(checks)
    return FOLLOWED.format(n=n, m=m, unit=unit(ch) if m != 1 else unit(ch)[:-1])


def said_line(check: dict, target: int) -> str:
    if check["move"]:
        return SAID_MOVE.format(pts=f"{abs(check['stocks_pct'] - target):.0f}", pct=target)
    return SAID_STAY.format(band=BAND, pct=target)


def first_last(ch: dict) -> tuple[str, str]:
    ms = months_of(ch)
    return ms[0], ms[-1]


def templates() -> list[str]:
    """Every fixed line, filled with sample values, for the wording tests."""
    out = [EYEBROW.format(month="October"), CHART_LABEL, PICK_TITLE, PICK_HELP,
           RULE_LINE.format(pct=70, every="monthly"), RULE_BAND.format(band=BAND, pct=70),
           QUESTION.format(now=58), STEP_LINE.format(unit_cap="Month", at=14, total=24,
                                                     when="March 2009"),
           SAID_MOVE.format(pts=12, pct=70), SAID_STAY.format(band=BAND, pct=70),
           YOU_FOLLOWED, YOU_DIDNT, SCORED_TITLE, SCORED,
           FOLLOWED.format(n=12, m=13, unit="months"), NOT_STARTED,
           FINISHED.format(day="Oct 7, 2026"), ENDS.format(day="Oct 31"),
           NEXT.format(title=CHALLENGES[-1]["title"]),
           NOT_READY.format(first="Jul 2007", last="Jul 2009"), NONE_READY,
           mix_line(),
           FOOTER, CARD_OPEN, CARD_GO_ON, AGAIN, START, OTHERS, SECTION, NOT_READY_TAG]
    out += [RULE_WORDS.format(pct=v) for v in RULES.values()]
    for c in CHALLENGES:
        out += [c["title"], c["about"]]
        out += [choice_words(k, c, 70, low) for k in CHOICES for low in ("stocks", "bonds")]
    return out
