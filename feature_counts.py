"""Feature counts (ROADMAP R1 and R4, "Decided (owner, Oct 5)"): whether a
feature helps, in totals only. Pure logic plus one read; no Streamlit.

The rules, as the privacy text says them (disclosures.py, the Privacy
Policy draft):
- Totals only, worked out here in code. Nobody looks at a single person's
  row: the query reads the settings column alone - no user id, no name.
- A total is shown only for a group of at least MIN_GROUP people.
- Never shared or sold, and never sent to the AI: only the Admin portal's
  "Feature tests" panel shows them (views/admin.py).
- Anyone can leave themselves out: Account > "Leave me out of feature
  counts" (PREF_OFF), honoured on every count, past walks included.
- Counting applies only from when the privacy text said so: a walk counts
  only when it was kept with its day (checkin.PREF_VERDICTS, from the Walk
  on), and someone whose first walk was a check-in from before isn't in
  the "first walk" group at all.

R1's metric: of the people who finished a first walk, how many finished a
second within SECOND_WITHIN_DAYS days of it - among those whose window has
closed, so the share isn't pulled down by people still inside it.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import checkin

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


def walk_totals(all_prefs, today: date) -> dict | None:
    """R1's totals from every account's settings: {"first_walks": people
    who finished a first walk, "window_closed": of them, those whose first
    walk was SECOND_WITHIN_DAYS or more days ago, "second_walks": of those,
    how many finished a second within that many days (None while that
    group is under MIN_GROUP)}. None while fewer than MIN_GROUP people
    finished a first walk."""
    pairs = [x for x in (first_two(p) for p in all_prefs) if x]
    if len(pairs) < MIN_GROUP:
        return None
    window = timedelta(days=SECOND_WITHIN_DAYS)
    closed = [(a, b) for a, b in pairs if a + window <= today]
    second = (sum(1 for a, b in closed if b is not None and b - a <= window)
              if len(closed) >= MIN_GROUP else None)
    return {"first_walks": len(pairs), "window_closed": len(closed), "second_walks": second}


def _all_settings(conn):
    """Every account's settings that hold a walk - the settings column
    only, never whose they are."""
    for r in conn.execute("SELECT data FROM user_prefs WHERE data LIKE ?",
                          (f'%"{checkin.PREF_VERDICTS}"%',)):
        try:
            p = json.loads(r["data"])
        except (TypeError, ValueError):
            continue
        if isinstance(p, dict):
            yield p


def walks(conn, today: date | None = None) -> dict | None:
    """walk_totals() from the database."""
    return walk_totals(_all_settings(conn), today or date.today())
