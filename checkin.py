"""The monthly check-in (ROADMAP 11): a 3-minute routine on Home once a
month - update holdings, look at the mix against its target, one short
read from Learn, and (if they like) a note to future you. Pure logic, no
Streamlit; the card is views/checkin.py, the reminder email checkin_email.py.

Kept in the account's settings (prefs.py), never anywhere else:
  PREF_STATE  {"month": "2026-10", "done": [step keys], "finished": date |
               None, "skipped": bool} - this month's check-in
  PREF_LOG    ["2026-08", "2026-10"] - the months a check-in was finished
  PREF_SINCE  "2026-10" - the month real holdings were first seen: the
              check-in is offered from the month after
  PREF_DAY    1-28 - the day of the month it's offered from (default 1)
  PREF_EMAIL  True when they asked for the reminder email (off by default)
  PREF_SENT   "2026-10" - the month the reminder was last sent

Finishing it is a habit, and earns the logbook in the kit (gear.py) after
LOGBOOK_CHECKINS of them, in any months - a missed month never takes
anything away. Nothing about it ever asks anyone to buy or sell.
"""

from __future__ import annotations

from datetime import date

from gear import CHECKINS as LOGBOOK_CHECKINS   # the kit's logbook

PREF_STATE = "checkin"
PREF_LOG = "checkin_log"
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
    ("note", "A note to future you",
     "Optional: a line about why you're investing, for when markets get rough."),
)
REQUIRED = ("holdings", "mix", "read")   # the note is optional
STEP_KEYS = tuple(s[0] for s in STEPS)


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


def finish(p: dict, today: date) -> bool:
    """Finish this month's check-in when the required steps are ticked: kept
    in PREF_LOG (once a month). Changes `p`; True when finished now."""
    st = current(p, today)
    if st["finished"] or not can_finish(st):
        return False
    st["finished"] = today.isoformat()
    p[PREF_STATE] = st
    log = [m for m in p.get(PREF_LOG) or [] if isinstance(m, str)]
    if st["month"] not in log:
        log.append(st["month"])
    p[PREF_LOG] = sorted(log)
    return True


def skip(p: dict, today: date) -> None:
    """"Not this month": put off until next month (it doesn't count, and
    nothing is lost)."""
    st = current(p, today)
    st["skipped"] = True
    p[PREF_STATE] = st


def count(p: dict) -> int:
    """How many months a check-in was finished."""
    return len({m for m in p.get(PREF_LOG) or [] if isinstance(m, str)})


def logbook(p: dict) -> bool:
    """The kit's logbook: LOGBOOK_CHECKINS check-ins finished, any months."""
    return count(p) >= LOGBOOK_CHECKINS


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
