"""The Monthly Walk (ROADMAP R1; it grew out of the monthly check-in, item
11): a 3-minute routine on Home once a month - update holdings, look at the
mix against its target, one short read from Learn, and the verdict: what
the person's own rule (their target mix and their band) says this month.
Pure logic, no Streamlit; the card is views/checkin.py, the reminder email
checkin_email.py, the totals feature_counts.py.

The verdict is rule-based, never AI, and speaks in asset classes only: no
target mix, no verdict; within the band, nothing to do this month; outside
it, one next step for new money by asset class (next_deposit.py). Never a
fund, a ticker, a dollar figure or selling.

Kept in the account's settings (prefs.py), never anywhere else. The keys
still say "checkin", so check-ins finished before the Walk count as walks:
  PREF_STATE  {"month": "2026-10", "done": [step keys], "finished": date |
               None, "skipped": bool} - this month's walk
  PREF_LOG    ["2026-08", "2026-10"] - the months a walk was finished
  PREF_VERDICTS {"2026-10": {"kind": "next", "class": "Bonds", "how": "most",
               "on": "2026-10-05"}} - each finished walk's verdict kind (no
              figures) and the day it was finished; R2 and R3 build on it
  PREF_SINCE  "2026-10" - the month real holdings were first seen: the
              walk is offered from the month after
  PREF_DAY    1-28 - the day of the month it's offered from (default 1)
  PREF_EMAIL  True when they asked for the reminder email (off by default)
  PREF_SENT   "2026-10" - the month the reminder was last sent

Finishing it is a habit, and earns the logbook in the kit (gear.py) after
LOGBOOK_CHECKINS of them, in any months - a missed month never takes
anything away. Walks are counted, never returns.
"""

from __future__ import annotations

from datetime import date

import next_deposit
import route
from asset_classes import CLASSES
from gear import CHECKINS as LOGBOOK_CHECKINS   # the kit's logbook

PREF_STATE = "checkin"
PREF_LOG = "checkin_log"
PREF_VERDICTS = "walk_verdicts"
PREF_SINCE = "checkin_since"
PREF_DAY = "checkin_day"
PREF_EMAIL = "checkin_email"
PREF_SENT = "checkin_email_sent"

DEFAULT_DAY = 1
LAST_DAY = 28            # every month has one

# key, title, what it's for - the order they're walked in
STEPS = (
    ("holdings", "Update your holdings",
     "Bring in anything that changed since last month - or say nothing has."),
    ("mix", "Look at your mix",
     "How your money is spread now, beside the target mix you chose."),
    ("read", "One short read",
     "A couple of minutes on one idea worth knowing."),
    ("verdict", "What your plan says",
     "What your own target mix and band mean for this month."),
)
REQUIRED = ("holdings", "mix", "read")   # then the verdict, and Finish
STEP_KEYS = tuple(s[0] for s in STEPS)

# the verdict's kinds (stored per walk, PREF_VERDICTS)
NONE, WITHIN, NEXT = "none", "within", "next"
KINDS = (NONE, WITHIN, NEXT)
HOWS = ("all", "most", "much")   # how much of the next deposit the class gets, in words


def month_of(today: date) -> str:
    return f"{today.year:04d}-{today.month:02d}"


def month_name(month: str) -> str:
    """'October' from '2026-10'."""
    return date(int(month[:4]), int(month[5:7]), 1).strftime("%B")


def day_of(p: dict) -> int:
    """The chosen day of the month, 1-28."""
    try:
        d = int(p.get(PREF_DAY) or DEFAULT_DAY)
    except (TypeError, ValueError):
        return DEFAULT_DAY
    return min(LAST_DAY, max(1, d))


def current(p: dict, today: date) -> dict:
    """This month's check-in (a fresh one when the saved one is older)."""
    st = p.get(PREF_STATE)
    month = month_of(today)
    if not isinstance(st, dict) or st.get("month") != month:
        return {"month": month, "done": [], "finished": None, "skipped": False}
    return {"month": month, "done": [k for k in st.get("done") or [] if k in STEP_KEYS],
            "finished": st.get("finished"), "skipped": bool(st.get("skipped"))}


def note_seen(p: dict, today: date, has_real_holdings: bool,
              holdings_date: str | None = None) -> bool:
    """Remember the month real holdings were first seen (PREF_SINCE): this
    month, or the month of the holdings' date when that's earlier (holdings
    from before the check-in existed). Changes `p`; True when it did (so
    it's saved)."""
    if has_real_holdings and not p.get(PREF_SINCE):
        month = month_of(today)
        if holdings_date and len(str(holdings_date)) >= 7:
            month = min(month, str(holdings_date)[:7])
        p[PREF_SINCE] = month
        return True
    return False


def due(p: dict, today: date) -> bool:
    """Whether Home offers this month's check-in: not finished or put off
    this month; started already, or on or after the chosen day - and not in
    the month the holdings first came in (they've just done the work)."""
    st = current(p, today)
    if st["finished"] or st["skipped"]:
        return False
    if st["done"]:
        return True
    since = p.get(PREF_SINCE)
    if not since or since >= st["month"]:
        return False
    return today.day >= day_of(p)


def tick(p: dict, step: str, today: date, done: bool = True) -> dict:
    """Mark a step done (or not). Changes `p` and returns this month's state."""
    st = current(p, today)
    if step in STEP_KEYS:
        if done and step not in st["done"]:
            st["done"].append(step)
        elif not done and step in st["done"]:
            st["done"].remove(step)
    p[PREF_STATE] = st
    return st


def can_finish(st: dict) -> bool:
    return all(k in st["done"] for k in REQUIRED)


def finish(p: dict, today: date, verdict: dict | None = None) -> bool:
    """Finish this month's walk when the required steps are ticked: kept in
    PREF_LOG (once a month), with the verdict's kind - no figures - and the
    day in PREF_VERDICTS. Changes `p`; True when finished now."""
    st = current(p, today)
    if st["finished"] or not can_finish(st):
        return False
    st["finished"] = today.isoformat()
    p[PREF_STATE] = st
    log = [m for m in p.get(PREF_LOG) or [] if isinstance(m, str)]
    if st["month"] not in log:
        log.append(st["month"])
    p[PREF_LOG] = sorted(log)
    kept = p.get(PREF_VERDICTS)
    kept = dict(kept) if isinstance(kept, dict) else {}
    kept[st["month"]] = {**stored(verdict), "on": today.isoformat()}
    p[PREF_VERDICTS] = kept
    return True


def stored(verdict: dict | None) -> dict:
    """What's kept of a verdict: its kind, and for a next step the asset
    class and how much of it ("all" / "most" / "much") - only names from
    fixed lists, so no figure can ever be stored."""
    v = verdict or {}
    kind = v.get("kind")
    if kind not in KINDS:
        return {}
    out = {"kind": kind}
    if kind == NEXT and v.get("class") in CLASSES:
        out["class"] = v["class"]
        if v.get("how") in HOWS:
            out["how"] = v["how"]
    return out


def verdict_of(p: dict, month: str) -> dict | None:
    """The kept verdict of a month's walk (PREF_VERDICTS), or None."""
    kept = p.get(PREF_VERDICTS)
    v = kept.get(month) if isinstance(kept, dict) else None
    return v if isinstance(v, dict) else None


def skip(p: dict, today: date) -> None:
    """"Not this month": put off until next month (it doesn't count, and
    nothing is lost)."""
    st = current(p, today)
    st["skipped"] = True
    p[PREF_STATE] = st


def count(p: dict) -> int:
    """How many months a walk was finished (check-ins from before count)."""
    return len({m for m in p.get(PREF_LOG) or [] if isinstance(m, str)})


def logbook(p: dict) -> bool:
    """The kit's logbook: LOGBOOK_CHECKINS walks finished, any months."""
    return count(p) >= LOGBOOK_CHECKINS


def next_walk(p: dict, today: date) -> date:
    """The day the next walk is offered: today while one is waiting, this
    month's chosen day when it's still ahead, else next month's."""
    st = current(p, today)
    day = day_of(p)
    since = p.get(PREF_SINCE)
    if not (st["finished"] or st["skipped"] or not since or since >= st["month"]):
        if st["done"] or today.day >= day:
            return today
        return date(today.year, today.month, day)
    y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    return date(y, m, day)


# ---- the verdict: their own rule speaking ----------------------------------- #

def verdict(values: dict, targets: dict, band: float, amount: float) -> dict:
    """What the person's own rule says this month, by asset class:
    {"kind": NONE} without a target mix; {"kind": WITHIN} when every
    targeted class is within `band` points of its target (the drift Home
    and Plan flag, route.drifted); else {"kind": NEXT, "class", "how",
    "below"}: the class that gets most of a deposit of `amount` split to
    move toward the target without selling (next_deposit.split), "how" much
    of it in words, and whether it's below its target now. `values` is
    {class: dollars held now}, `targets` {class: target %}. The amount only
    picks the class - no figure is ever part of the verdict."""
    targets = {k: float(v) for k, v in (targets or {}).items() if v}
    if not targets:
        return {"kind": NONE}
    values = {k: float(v or 0.0) for k, v in (values or {}).items()}
    now = next_deposit.mix_pct(values)
    if not route.drifted(now, targets, float(band)):
        return {"kind": WITHIN}
    add = next_deposit.split(values, targets, amount or 1.0)
    if not add:
        return {"kind": NEXT, "class": None, "how": None, "below": False}
    top = max(sorted(add), key=add.get)
    share = add[top] / sum(add.values())
    # next_deposit.words' thresholds: "mostly" from 60%
    how = "all" if share > 0.995 else "most" if share >= 0.6 else "much"
    return {"kind": NEXT, "class": top, "how": how,
            "below": now.get(top, 0.0) < targets.get(top, 0.0)}


def class_name(cls: str) -> str:
    """'bonds', 'other holdings' - an asset class in a sentence."""
    return next_deposit._name(cls)


def _deposit_words(v: dict) -> str:
    name = class_name(v["class"])
    if v.get("how") == "all":
        return f"your next deposit would go to {name}"
    if v.get("how") == "most":
        return f"most of your next deposit would go to {name}"
    return f"the largest part of your next deposit would go to {name}"


def verdict_text(v: dict) -> str:
    """The verdict in one sentence, as the person's own plan speaking.
    Never "sell", never a fund, a ticker or a figure."""
    kind = (v or {}).get("kind")
    if kind == WITHIN:
        return ("Your mix is within the band you set, so your plan says there's nothing to do "
                "this month.")
    if kind == NEXT and v.get("class"):
        lead = (f"Your target has more {class_name(v['class'])} than you hold now. "
                if v.get("below") else "")
        return f"{lead}Under your plan, {_deposit_words(v)}."
    if kind == NEXT:
        return ("Your mix has moved outside the band you set. The Target mix tab on your Plan "
                "page shows where new money could go.")
    return "Set a target mix on your Plan page to see what your plan says each month."


def verdict_past(v: dict | None) -> str:
    """A finished walk's kept verdict, looking back ("Your plan said ...")."""
    kind = (v or {}).get("kind")
    if kind == WITHIN:
        return ("Your plan said there was nothing to do this month - your mix was within your "
                "band.")
    if kind == NEXT and v.get("class"):
        return f"Your plan said {_deposit_words(v)}."
    if kind == NEXT:
        return ("Your mix was outside your band, so your plan said new money could go back "
                "toward your target.")
    if kind == NONE:
        return "No target mix was set, so there was nothing to check this month."
    return ""


# ---- where the target came from (LEGAL_GATES.md C3) ------------------------- #
# Kept beside the target in the account's settings: {"by": TARGET_*, "mix":
# {class: %}}. When the target is still exactly Northwend's example mix (gate
# L3 on, "Use this" or the slider left where it started), the verdict would be
# Northwend's mix speaking as "your plan" - so the Walk says so, once, and
# asks whether it's theirs.
PREF_TARGET_FROM = "target_from"
TARGET_OWN, TARGET_ADVISOR, TARGET_EXAMPLE = "own", "advisor", "example"
TARGET_FROM_NOTE = ("This target started as Northwend's example mix and hasn't changed since. "
                    "Is it the one you want? You can keep it as yours, or change it on the "
                    "Plan.")


def _mix(targets: dict | None) -> dict:
    return {k: round(float(v), 1) for k, v in (targets or {}).items() if v}


def note_target(p: dict, by: str, targets: dict) -> None:
    """Note who chose the target mix just saved into the settings `p`."""
    p[PREF_TARGET_FROM] = {"by": by, "mix": _mix(targets)}


def target_from_example(p: dict, targets: dict) -> bool:
    """The target is still Northwend's example mix, untouched since it was
    taken (a target changed or confirmed since then is theirs)."""
    rec = (p or {}).get(PREF_TARGET_FROM) or {}
    return rec.get("by") == TARGET_EXAMPLE and bool(_mix(targets)) \
        and rec.get("mix") == _mix(targets)


def rule_text(targets: dict, band: float) -> str:
    """'Your rule: a target mix of 60% stocks, 35% bonds and 5% cash, and a
    band of 5 points either way.' - shown under every verdict."""
    parts = [f"{float(v):g}% {class_name(k)}" for k, v in
             sorted(((k, v) for k, v in (targets or {}).items() if v), key=lambda kv: -kv[1])]
    if not parts:
        return ""
    mix = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return (f"Your rule: a target mix of {mix}, and a band of {float(band):g} points either "
            "way.")


def read_for(month: str, keys: list[str]) -> str:
    """This month's short read: Learn's basics in turn, one a month."""
    n = int(month[:4]) * 12 + int(month[5:7]) - 1
    return keys[n % len(keys)]


def drift_rows(actual: dict, targets: dict) -> list[dict]:
    """[{"label", "now", "target", "off"}] for each asset class in either,
    largest target first (`actual`, `targets`: {label: %})."""
    labels = sorted(set(actual) | set(targets),
                    key=lambda k: (-(targets.get(k) or 0.0), -(actual.get(k) or 0.0), k))
    return [{"label": k, "now": float(actual.get(k) or 0.0),
             "target": (float(targets[k]) if k in targets else None),
             "off": (float(actual.get(k) or 0.0) - float(targets[k]) if k in targets else None)}
            for k in labels]


# ---- the reminder email (checkin_email.py) ---------------------------------- #

def wants_email(p: dict, today: date) -> bool:
    """A reminder is due: asked for, not sent this month, on or after their
    day, and this month's check-in not already finished or put off."""
    if not p.get(PREF_EMAIL):
        return False
    st = current(p, today)
    if p.get(PREF_SENT) == st["month"] or st["finished"] or st["skipped"]:
        return False
    # only when Home will have the check-in waiting for them (due())
    since = p.get(PREF_SINCE)
    return bool(since) and since < st["month"] and today.day >= day_of(p)
