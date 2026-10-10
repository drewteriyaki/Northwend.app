"""Feature counts (ROADMAP R1 and R4, "Decided (owner, Oct 5)"): whether a
feature helps, in totals only. Pure logic plus one read; no Streamlit.

The rules, as the privacy text says them (disclosures.py, the Privacy
Policy draft):
- Totals only, worked out here in code. Nobody looks at a single person's
  row: each query hands back the settings column alone - no user id, no
  name, never a note's words.
- A total is shown only for a group of at least MIN_GROUP people.
- Never shared or sold, and never sent to the AI: only the Admin portal's
  "Feature tests" panel shows them (views/admin.py).
- Anyone can leave themselves out: Account > "Leave me out of feature
  counts" (PREF_OFF), honoured on every count, past walks included.
- Counting applies only from when the privacy text said so: a walk counts
  only when it was kept with its day (checkin.PREF_VERDICTS, from the Walk
  on), and someone whose first walk was a check-in from before isn't in
  the "first walk" group at all.

R1's metric ("the one measure"): of the people who finished a first walk,
how many finished a second within SECOND_WITHIN_DAYS days of it - among
those whose window has closed (the first walk more than SECOND_WITHIN_DAYS
days ago, so the last day of the window is over), so the share isn't pulled
down by people still inside it. A walk is kept once a month (by month), so
two walks are never on one day or in one month. Admin logins (users.is_admin
and NORTHWEND_ADMINS, passed in) aren't counted: the owner's own walks would
tilt a small group. A deleted account's settings go with it, so it leaves
every count. The same, by the month of the first walk: walk_month_totals().
The owner's read-only SQL for the same number is in docs/RUNBOOK.md.

R4's, for now: how many people wrote a Storm Drill answer (drill_answers) -
a count of rows, never the words.
R5's metric (the 401(k) Menu Decoder): the share of pasted funds that were
identified - from numbers kept in each person's settings (how many decodes,
fund lines and identified lines; menu_decoder.add_counts), never the text or
a fund's name.
R12's metric (preparedness drills): unprompted return for a third drill -
how many people who rehearsed one drill went on to a third, from how many
drill keys their settings hold (drills.PREF), never what they tapped.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import checkin
import drills
import future_notes
import menu_decoder

MIN_GROUP = 20
SECOND_WITHIN_DAYS = 45
PREF_OFF = "feature_counts_off"


def left_out(p: dict) -> bool:
    """They turned on "Leave me out of feature counts"."""
    return bool((p or {}).get(PREF_OFF))


def walk_days(p: dict) -> list[date]:
    """The days their counted walks were finished, oldest first."""
    kept = (p or {}).get(checkin.PREF_VERDICTS)
    out = []
    for v in (kept.values() if isinstance(kept, dict) else ()):
        try:
            out.append(date.fromisoformat(str((v or {}).get("on"))[:10]))
        except (TypeError, ValueError, AttributeError):
            continue
    return sorted(out)


def first_two(p: dict) -> tuple[date, date | None] | None:
    """(first walk, second walk or None) for one account's settings - None
    when they're left out, have no counted walk, or walked (as a check-in)
    before walks were counted."""
    if left_out(p):
        return None
    days = walk_days(p)
    if not days:
        return None
    first_month = f"{days[0].year:04d}-{days[0].month:02d}"
    if any(isinstance(m, str) and m < first_month for m in p.get(checkin.PREF_LOG) or []):
        return None
    return days[0], (days[1] if len(days) > 1 else None)


def window_closed(first: date, today: date) -> bool:
    """Their SECOND_WITHIN_DAYS days are over: the window's last day (first
    + SECOND_WITHIN_DAYS, which still counts) is before today."""
    return first + timedelta(days=SECOND_WITHIN_DAYS) < today


def walked_again(first: date, second: date | None) -> bool:
    """A second walk within SECOND_WITHIN_DAYS days of the first (the
    SECOND_WITHIN_DAYS-th day included)."""
    return second is not None and (second - first).days <= SECOND_WITHIN_DAYS


def walk_totals(all_prefs, today: date) -> dict | None:
    """R1's totals from every account's settings: {"first_walks": people
    who finished a first walk, "window_closed": of them, those whose
    SECOND_WITHIN_DAYS days are over (window_closed), "second_walks": of
    those, how many finished a second within that many days (None while
    that group is under MIN_GROUP)}. None while fewer than MIN_GROUP people
    finished a first walk."""
    pairs = [x for x in (first_two(p) for p in all_prefs) if x]
    if len(pairs) < MIN_GROUP:
        return None
    closed = [(a, b) for a, b in pairs if window_closed(a, today)]
    second = (sum(1 for a, b in closed if walked_again(a, b))
              if len(closed) >= MIN_GROUP else None)
    return {"first_walks": len(pairs), "window_closed": len(closed), "second_walks": second}


def _month_end(month: str) -> date:
    y, m = int(month[:4]), int(month[5:7])
    return date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)


def walk_month_totals(all_prefs, today: date) -> list[dict] | None:
    """The same rate by the month of the first walk, oldest first: [{"month":
    "2026-10", "people": first walks that month or None, "second": of them,
    walked again within SECOND_WITHIN_DAYS days, or None}] - only months
    whose every window is over (the month's last day + SECOND_WITHIN_DAYS
    before today). A month under MIN_GROUP shows neither number; and while
    the months not shown add up to between 1 and MIN_GROUP - 1 people (the
    overall total minus the shown months would give them away), the
    smallest shown month is held back too ("people" stays, "second" is
    None). None when walk_totals shows no rate."""
    all_prefs = list(all_prefs)
    totals = walk_totals(all_prefs, today)
    if not totals or totals["second_walks"] is None:
        return None
    by_month: dict[str, list] = {}
    for a, b in (x for x in (first_two(p) for p in all_prefs) if x):
        if window_closed(a, today):
            by_month.setdefault(f"{a.year:04d}-{a.month:02d}", []).append(walked_again(a, b))
    rows = [{"month": m, "people": len(v), "second": sum(v)}
            for m, v in sorted(by_month.items())
            if window_closed(_month_end(m), today)]
    for r in rows:
        if r["people"] < MIN_GROUP:
            r["people"] = r["second"] = None
    while True:
        shown = [r for r in rows if r["second"] is not None]
        hidden = totals["window_closed"] - sum(r["people"] for r in shown)
        if not shown or hidden == 0 or hidden >= MIN_GROUP:
            break
        min(shown, key=lambda r: (r["people"], r["month"]))["second"] = None
    return rows


def walk_settings(conn, skip_logins=()):
    """Every account's settings that hold a walk, without admin logins
    (users.is_admin, and `skip_logins` - NORTHWEND_ADMINS, which the caller
    reads) - the settings column only, never whose they are (the login only
    filters inside the query)."""
    skip = sorted({str(x).lower() for x in skip_logins or () if str(x).strip()})
    sql = ("SELECT p.data AS data FROM user_prefs p JOIN users u ON u.id = p.user_id "
           "WHERE p.data LIKE ? AND COALESCE(u.is_admin, 0) = 0")
    if skip:
        sql += f" AND LOWER(u.username) NOT IN ({', '.join('?' for _ in skip)})"
    for r in conn.execute(sql, (f'%"{checkin.PREF_VERDICTS}"%', *skip)):
        try:
            p = json.loads(r["data"])
        except (TypeError, ValueError):
            continue
        if isinstance(p, dict):
            yield p


def _all_settings(conn, key: str = checkin.PREF_VERDICTS):
    """Every account's settings that hold `key` (a walk, by default) - the
    settings column only, never whose they are."""
    for r in conn.execute("SELECT data FROM user_prefs WHERE data LIKE ?",
                          (f'%"{key}"%',)):
        try:
            p = json.loads(r["data"])
        except (TypeError, ValueError):
            continue
        if isinstance(p, dict):
            yield p


def walks(conn, today: date | None = None, skip_logins=()) -> dict | None:
    """walk_totals() from the database (admin logins left out)."""
    return walk_totals(walk_settings(conn, skip_logins), today or date.today())


# R4 (the Storm Drill): for now only how many people wrote a drill answer.
# Selling behaviour on the next drop isn't measured yet - that needs its own
# privacy text first.

def drill_total(settings_of_writers) -> int | None:
    """How many people wrote a Storm Drill answer, from each writer's
    settings (None when they have none) - without anyone left out; None
    while that's under MIN_GROUP."""
    n = sum(1 for p in settings_of_writers if not left_out(p if isinstance(p, dict) else {}))
    return n if n >= MIN_GROUP else None


def drill_answers(conn) -> int | None:
    """drill_total() from the database. The query hands back only each
    writer's settings column - never the words, never whose they are (the
    user id only joins the two tables inside the query)."""
    def settings():
        for r in conn.execute("SELECT p.data AS data FROM future_notes n LEFT JOIN user_prefs p "
                              "ON p.user_id = n.user_id WHERE n.symbol = ?",
                              (future_notes.DRILL,)):
            try:
                yield json.loads(r["data"]) if r["data"] else {}
            except (TypeError, ValueError):
                yield {}
    return drill_total(settings())
# ---- R5: the 401(k) Menu Decoder ------------------------------------------- #
def decoder_totals(all_prefs) -> dict | None:
    """R5's metric, the share of pasted funds identified, from every
    account's settings (menu_decoder.PREF_COUNTS - numbers only, never a fund
    name): {"people", "decodes", "lines", "identified"}. None while fewer
    than MIN_GROUP people (not left out) have used it."""
    got = [c for c in (menu_decoder.counts_in(p) for p in all_prefs if not left_out(p)) if c]
    if len(got) < MIN_GROUP:
        return None
    return {"people": len(got), **{k: sum(c[k] for c in got)
                                   for k in ("decodes", "lines", "identified")}}


def decoder(conn) -> dict | None:
    """decoder_totals() from the database - the settings column only."""
    return decoder_totals(_all_settings(conn, menu_decoder.PREF_COUNTS))


# ---- R12: preparedness drills ---------------------------------------------- #
def drill_totals(all_prefs) -> dict | None:
    """R12's metric, unprompted return for a third drill (there are no
    reminders, so every return is unprompted; one drill a week, so a third
    drill means a third week): {"started": people who rehearsed a first
    drill, "third": of them, how many rehearsed a third}, from how many
    drills each account's settings hold (drills.count - never which choice
    anyone tapped). None while fewer than MIN_GROUP people (not left out)
    have started."""
    started = [n for n in (drills.count(p) for p in all_prefs
                           if isinstance(p, dict) and not left_out(p)) if n >= 1]
    if len(started) < MIN_GROUP:
        return None
    return {"started": len(started), "third": sum(1 for n in started if n >= drills.GEAR_AT)}


def drill_returns(conn) -> dict | None:
    """drill_totals() from the database - the settings column only."""
    return drill_totals(_all_settings(conn, drills.PREF))
