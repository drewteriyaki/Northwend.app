"""Your wins (flag wins): one-time milestones for things that pay off for
years whatever the market does, each worked out from data the app already
has. Pure logic; the Home card and the Plan tab are views/wins.py.

The wins, in order:
- fees     Lower fees found: the average yearly fee on the funds held now is
           at least FEE_DROP lower than on the first holdings update (fees.py
           on both; security_info.expense_ratio). Shown with the yearly
           difference at today's value and, labelled hypothetical, what that
           could add up to over LONG_YEARS at LONG_RATE. Never listed as one
           still to earn: that would reward changing funds.
- match    Full employer match: the Free money check's remembered answers
           (employer_match.py, prefs match_check) get the whole match - or
           the About you answer says so.
- regular  Regular deposits: money added in STREAK calendar months in a row
           (plans.money_moves' rule, from progress_split.read).
- cushion  Three months of expenses saved: the About you emergency savings
           answer is 3-6 months or more.
- roth     A Roth IRA opened: an account named Roth among the holdings, or
           marked by the person.
- debt     High-interest debt paid off: only the person marks it.

Kept, in the login's own settings (prefs PREF): {key: {"on": "YYYY-MM-DD"}}
for each win earned, plus "self": true for one the person marked - never an
amount, a fee, a pay figure or an answer. A win stays earned once earned.
Never drawn while an advisor is in a client's account (or for an advisor's
client), never sent to the AI. Nothing here rewards trading: buying or
selling never earns anything.
"""

from __future__ import annotations

from datetime import date, timedelta

import employer_match
import fees

PREF = "wins"
FEES, MATCH, REGULAR, CUSHION, ROTH, DEBT = "fees", "match", "regular", "cushion", "roth", "debt"
ORDER = (FEES, MATCH, REGULAR, CUSHION, ROTH, DEBT)
SELF_MARKED = (ROTH, DEBT)            # the person can mark these themselves
NEVER_TO_EARN = (FEES,)               # shown only once earned

FEE_DROP = 0.0005      # 0.05 points a year lower, on average
LONG_YEARS = 30
LONG_RATE = 0.06       # the hypothetical yearly growth for the long-run figure
STREAK = 3             # months in a row with money added
NEW_DAYS = 30          # Home's card shows a win earned this recently
CUSHION_ANSWERS = ("3-6 months", "6+ months of expenses")
MATCH_ANSWER = "Yes, and I get the full match"
NO_MATCH_ANSWER = "No match or no plan"

TITLES = {
    FEES: "Lower fees found",
    MATCH: "Full employer match",
    REGULAR: "Regular deposits",
    CUSHION: "Three months of expenses saved",
    ROTH: "A Roth IRA opened",
    DEBT: "High-interest debt paid off",
}

# ---- the words (fixed; every one goes through the wording tests) ----------- #
PAGE_TITLE = "Your wins"
INTRO = ("Things you did that pay off for years, whatever the market does. Each one is earned "
         "once and stays.")
EARNED = "Earned {day}"
EARNED_NO_DAY = "Earned"
TO_EARN = "Still to earn"
NONE_YET = "No wins yet. The ones below are earned from what you do, not from what the market does."
ALL_EARNED = "You've earned every win here."
MARK = "Mark as done"
UNMARK = "Undo"
CARD_TITLE = "A new win"
CARD_LINK = "See your wins"
PRIVATE = "Only you see your wins. Northwend keeps which ones you've earned and the day - never an amount."

FEES_NUMBER = "{amount} a year"
FEES_NUMBER_PCT = "{points} points a year"
FEES_LINE = "The average yearly fee on your funds went from {old} to {new}."
FEES_LONG = ("Over {years} years that could be about {amount} more, at a hypothetical {rate}% a "
             "year - an illustration, not a promise.")
FEES_GONE = "Your funds' fees have changed since - the Fee check on Home shows them now."

MATCH_NUMBER = "{amount} a year"
MATCH_NUMBER_PCT = "{pct}% of your pay"
MATCH_LINE = ("You put in what it takes to get all of your employer's 401(k) match - money that would "
              "otherwise be left behind.")
MATCH_FROM_ANSWER = "From your answer in About you."
MATCH_PROGRESS = "You're getting a match of {got}% of your pay, of {most}% on offer."
MATCH_HOW = ("The Free money check on Plan, under Contributions, works out whether you get your "
             "employer's whole match. Ask it to remember your answers and this fills in.")

REGULAR_NUMBER = "{amount} a month"
REGULAR_NUMBER_MONTHS = "{n} months in a row"
REGULAR_LINE = "Money went in {n} months in a row - steady amounts add up over the years."
REGULAR_PROGRESS = "Months in a row with money added so far: {n} of {streak}."
REGULAR_HOW = ("Earned after money goes in {streak} months in a row. An automatic deposit at your "
               "brokerage does it without having to remember.")
REGULAR_SOURCE = "Counted from what you logged on Plan and any activity export you brought in."

CUSHION_NUMBER = "{answer}"
CUSHION_LINE = ("Savings for surprises can keep a bad month in the market from touching your "
                "investments.")
CUSHION_PROGRESS = "Your answer in About you: {answer}."
CUSHION_HOW = "Answer the emergency savings question in About you and this fills in."

ROTH_LINE = ("A Roth IRA is a retirement account you put taxed money into; under the IRS's rules "
             "what it grows to can come out tax-free in retirement.")
ROTH_FOUND = "An account named Roth is in your holdings."
ROTH_HOW = "Mark it when you've opened one."

DEBT_LINE = ("Credit card interest often runs 20% a year or more, so paying a card off saves that "
             "interest every year.")
DEBT_HOW = "Only you can mark this one."
SELF_NOTE = "You marked this one."


def _clean(prefs: dict) -> dict:
    """The kept wins, checked: {key: {"on": day, "self": bool}}."""
    out = {}
    for k, v in ((prefs or {}).get(PREF) or {}).items():
        if k in ORDER and isinstance(v, dict) and isinstance(v.get("on"), str):
            try:
                date.fromisoformat(v["on"])
            except ValueError:
                continue
            out[k] = {"on": v["on"], **({"self": True} if v.get("self") else {})}
    return out


def kept(prefs: dict) -> dict:
    return _clean(prefs)


def with_earned(prefs: dict, earned: dict) -> dict:
    """A copy of `prefs` with each win in `earned` ({key: day}) recorded
    (already earned ones keep their day). Only known keys and real days."""
    have = _clean(prefs)
    for k, day in (earned or {}).items():
        if k in ORDER and k not in have:
            try:
                have[k] = {"on": date.fromisoformat(str(day)[:10]).isoformat()}
            except ValueError:
                continue
    out = dict(prefs)
    if have:
        out[PREF] = have
    return out


def with_mark(prefs: dict, key: str, today: date, on: bool) -> dict:
    """Marked by the person (only SELF_MARKED keys), or unmarked - an undo
    only takes away a win the person marked themselves."""
    if key not in SELF_MARKED:
        return dict(prefs)
    have = _clean(prefs)
    if on and key not in have:
        have[key] = {"on": today.isoformat(), "self": True}
    elif not on and have.get(key, {}).get("self"):
        have.pop(key)
    out = dict(prefs)
    if have:
        out[PREF] = have
    else:
        out.pop(PREF, None)
    return out


# --------------------------------------------------------------------------- #
# working each one out
# --------------------------------------------------------------------------- #
def fee_ratio(rows) -> tuple[float | None, float]:
    """(average yearly fee as a fraction, value of the funds with a known
    fee) for [{symbol, asset_type, quote_type, value, expense_ratio}]."""
    holdings = [{"symbol": r["symbol"], "name": None, "asset_type": r.get("asset_type"),
                 "value": r.get("value") or 0.0} for r in rows or () if r.get("symbol")]
    info = {r["symbol"]: {"quote_type": r.get("quote_type"), "expense_ratio": r.get("expense_ratio")}
            for r in rows or () if r.get("symbol")}
    got = fees.check(holdings, info)
    return got["ratio"], got["value_known"]


def long_run(yearly: float, years: int = LONG_YEARS, rate: float = LONG_RATE) -> float:
    """`yearly` kept each year for `years`, growing `rate` a year (added at
    each year's end): the hypothetical long-run figure."""
    if rate == 0:
        return yearly * years
    return yearly * ((1 + rate) ** years - 1) / rate


def fee_win(first_rows, first_day: str | None, now_rows, latest_day: str | None) -> dict | None:
    """{"old", "new", "drop", "yearly", "long"} when the funds held now cost
    at least FEE_DROP a year less on average than the first update's - and
    the holdings have been updated since (a price move alone never earns it)."""
    if not first_day or not latest_day or latest_day <= first_day:
        return None
    old, _ = fee_ratio(first_rows)
    new, value = fee_ratio(now_rows)
    if old is None or new is None or old - new < FEE_DROP - 1e-12:
        return None
    yearly = (old - new) * value
    return {"old": old, "new": new, "drop": old - new, "yearly": yearly, "long": long_run(yearly)}


def match_state(prefs: dict, profile: dict) -> dict:
    """{"earned", "check" (employer_match.check or None), "from_answer",
    "applies"}."""
    saved = employer_match.clean_saved((prefs or {}).get(employer_match.PREF))
    tiers = employer_match.tiers_for(saved.get("preset"), saved.get("rate"), saved.get("up_to"))
    got = (employer_match.check(saved.get("salary"), saved.get("contrib_pct", 0.0), tiers)
           if tiers and "contrib_pct" in saved else None)
    answer = (profile or {}).get("employer_match")
    by_check = bool(got and got["has_match"] and got["getting_all"])
    return {"earned": by_check or answer == MATCH_ANSWER, "check": got,
            "from_answer": not by_check and answer == MATCH_ANSWER,
            "applies": answer != NO_MATCH_ANSWER or by_check}


def _month_after(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y + (m == 12):04d}-{m % 12 + 1:02d}"


def streaks(moves) -> list[dict]:
    """Runs of calendar months in a row with more money in than out:
    [{"months": [ym...], "total", "done_on": the day of the last deposit in
    the STREAK-th month (None if shorter)}], oldest first."""
    net: dict[str, float] = {}
    for d, a in moves or ():
        net[d[:7]] = net.get(d[:7], 0.0) + a
    good = sorted(m for m, v in net.items() if v > 0)
    runs, cur = [], []
    for m in good:
        if cur and _month_after(cur[-1]) == m:
            cur.append(m)
        else:
            if cur:
                runs.append(cur)
            cur = [m]
    if cur:
        runs.append(cur)
    out = []
    for run in runs:
        done = None
        if len(run) >= STREAK:
            third = run[STREAK - 1]
            done = max(d for d, a in moves if d[:7] == third and a > 0)
        out.append({"months": run, "total": sum(net[m] for m in run), "done_on": done})
    return out


def current_streak(moves, today: date) -> int:
    """Months in a row with money added, up to this month or last month."""
    this = f"{today:%Y-%m}"
    last = f"{(today.replace(day=1) - timedelta(days=1)):%Y-%m}"
    for run in reversed(streaks(moves)):
        if run["months"][-1] in (this, last):
            return len(run["months"])
    return 0


def has_roth(accounts) -> bool:
    return any("roth" in str(a or "").lower() for a in accounts or ())


# --------------------------------------------------------------------------- #
# the list
# --------------------------------------------------------------------------- #
def evaluate(*, prefs: dict, today: date, moves=(), first_rows=(), first_day=None,
             now_rows=(), latest_day=None, profile=None, accounts=(), pct_only=False) -> dict:
    """{"wins": [{"key", "title", "earned", "on", "self", "can_mark",
    "can_unmark", and the raw parts words() turns into text}], "new":
    {key: day} for wins earned now that aren't kept yet (the caller records
    them with with_earned - only for the login's own account)}."""
    have = _clean(prefs)
    profile = profile or {}
    out, new = [], {}

    def add(key, earned_now, *, on=None, **parts):
        kept_ = have.get(key)
        earned = bool(kept_) or earned_now
        if earned_now and not kept_:
            new[key] = on or today.isoformat()
        out.append({"key": key, "title": TITLES[key], "earned": earned,
                    "on": kept_["on"] if kept_ else (on if earned else None),
                    "self": bool(kept_ and kept_.get("self")),
                    "can_mark": key in SELF_MARKED and not earned,
                    "can_unmark": bool(kept_ and kept_.get("self")), **parts})

    fw = fee_win(first_rows, first_day, now_rows, latest_day)
    add(FEES, fw is not None, on=today.isoformat(), fee=fw, pct_only=pct_only)

    ms = match_state(prefs, profile)
    if ms["applies"] or MATCH in have:
        add(MATCH, ms["earned"], on=today.isoformat(), match=ms)

    runs = streaks(moves)
    done = [r for r in runs if r["done_on"]]
    latest = done[-1] if done else None
    add(REGULAR, bool(done), on=done[0]["done_on"] if done else None,
        run=latest, streak_now=current_streak(moves, today), pct_only=pct_only)

    answer = profile.get("emergency_fund")
    add(CUSHION, answer in CUSHION_ANSWERS, on=today.isoformat(), answer=answer)

    add(ROTH, has_roth(accounts), on=today.isoformat(), found=has_roth(accounts))
    add(DEBT, False)
    return {"wins": out, "new": new}


def words(w: dict, money) -> dict:
    """{"number", "line", "note", "progress" (0-1 or None), "how"} for one
    win, in fixed words. `money`: a whole-dollar formatter that masks while
    amounts are hidden."""
    k = w["key"]
    number = line = note = how = ""
    progress = None
    if k == FEES:
        fw = w.get("fee")
        if fw and w["earned"]:
            number = (FEES_NUMBER_PCT.format(points=f"{fw['drop'] * 100:.2f}") if w["pct_only"]
                      else FEES_NUMBER.format(amount=money(fw["yearly"])))
            line = FEES_LINE.format(old=fees.fmt_ratio(fw["old"]), new=fees.fmt_ratio(fw["new"]))
            if not w["pct_only"]:
                note = FEES_LONG.format(years=LONG_YEARS, amount=money(fw["long"]),
                                        rate=f"{LONG_RATE * 100:g}")
        elif w["earned"]:
            line = FEES_GONE
    elif k == MATCH:
        ms = w["match"]
        got = ms["check"]
        if w["earned"]:
            line = MATCH_LINE
            if got and got["getting_all"]:
                number = (MATCH_NUMBER.format(amount=money(got["max_yearly"]))
                          if got["max_yearly"] else
                          MATCH_NUMBER_PCT.format(pct=f"{got['max_pct']:g}"))
            elif ms["from_answer"]:
                note = MATCH_FROM_ANSWER
        elif got and got["has_match"]:
            how = MATCH_PROGRESS.format(got=f"{got['match_pct']:g}", most=f"{got['max_pct']:g}")
            progress = got["match_pct"] / got["max_pct"] if got["max_pct"] else None
        else:
            how = MATCH_HOW
    elif k == REGULAR:
        run = w.get("run")
        if w["earned"] and run:
            n = len(run["months"])
            number = (REGULAR_NUMBER_MONTHS.format(n=n) if w["pct_only"]
                      else REGULAR_NUMBER.format(amount=money(run["total"] / n)))
            line = REGULAR_LINE.format(n=n)
            note = REGULAR_SOURCE
        elif not w["earned"]:
            now = w.get("streak_now") or 0
            how = (REGULAR_PROGRESS.format(n=now, streak=STREAK) if now
                   else REGULAR_HOW.format(streak=STREAK))
            progress = min(1.0, now / STREAK)
    elif k == CUSHION:
        answer = w.get("answer")
        if w["earned"]:
            number = CUSHION_NUMBER.format(answer=answer) if answer in CUSHION_ANSWERS else ""
            line = CUSHION_LINE
        else:
            how = (CUSHION_PROGRESS.format(answer=answer) + " " + CUSHION_LINE if answer
                   else CUSHION_HOW)
    elif k == ROTH:
        line = ROTH_LINE
        if w["earned"]:
            note = ROTH_FOUND if w.get("found") and not w["self"] else (SELF_NOTE if w["self"] else "")
        else:
            how = ROTH_HOW
    elif k == DEBT:
        line = DEBT_LINE
        if w["earned"]:
            note = SELF_NOTE
        else:
            how = DEBT_HOW
    return {"number": number, "line": line, "note": note, "progress": progress, "how": how}


def shown(wins: list[dict]) -> tuple[list[dict], list[dict]]:
    """(earned, newest first; still to earn, in ORDER - never NEVER_TO_EARN)."""
    earned = sorted((w for w in wins if w["earned"]), key=lambda w: w["on"] or "", reverse=True)
    left = [w for w in wins if not w["earned"] and w["key"] not in NEVER_TO_EARN]
    return earned, left


def recent(wins: list[dict], today: date) -> list[dict]:
    """Earned within NEW_DAYS, newest first - Home's card."""
    floor = (today - timedelta(days=NEW_DAYS)).isoformat()
    return [w for w in shown(wins)[0] if w["on"] and w["on"] >= floor]


def day_words(day: str | None) -> str:
    """'Sep 12, 2026' (the one way the wins show a day)."""
    if not day:
        return ""
    d = date.fromisoformat(day[:10])
    return f"{d:%b} {d.day}, {d.year}"


def templates() -> list[str]:
    """Every fixed line, filled with example figures, for the wording tests."""
    ex = "$180"
    return [PAGE_TITLE, INTRO, EARNED.format(day="Sep 12, 2026"), EARNED_NO_DAY, TO_EARN,
            NONE_YET, ALL_EARNED, MARK, UNMARK, CARD_TITLE, CARD_LINK, PRIVATE,
            *TITLES.values(), FEES_NUMBER.format(amount=ex), FEES_NUMBER_PCT.format(points="0.30"),
            FEES_LINE.format(old="0.45%", new="0.12%"),
            FEES_LONG.format(years=30, amount="$14,000", rate="6"), FEES_GONE,
            MATCH_NUMBER.format(amount="$2,400"), MATCH_NUMBER_PCT.format(pct="3"), MATCH_LINE,
            MATCH_FROM_ANSWER, MATCH_PROGRESS.format(got="1.5", most="3"), MATCH_HOW,
            REGULAR_NUMBER.format(amount="$350"), REGULAR_NUMBER_MONTHS.format(n=4),
            REGULAR_LINE.format(n=3), REGULAR_PROGRESS.format(n=2, streak=STREAK),
            REGULAR_HOW.format(streak=STREAK), REGULAR_SOURCE,
            CUSHION_NUMBER.format(answer="3-6 months"), CUSHION_LINE,
            CUSHION_PROGRESS.format(answer="Under 3 months"), CUSHION_HOW,
            ROTH_LINE, ROTH_FOUND, ROTH_HOW, DEBT_LINE, DEBT_HOW, SELF_NOTE]
