"""The Do-Nothing Ledger (ROADMAP R2): a record of the walks where the
person stayed with their plan, and - only during a market drop - what
selling at those walks would have meant since, shown both ways honestly.
Pure logic, no Streamlit; the card is views/checkin.py.

The rule for an entry (conservative on purpose): a finished walk with a log
record (expedition_log.py) and no sale recorded in the account's activity
since the walk before - worked out from holdings updates or imported. Any
sale at all keeps that month out, even one the plan called for: the app
can't tell a planned sale from a reactive one, so it never guesses.

During a drop (the storm note's condition, storms.weather) each entry can
show a hypothetical: the holdings the person has now, priced at the close on
the walk's day and at the latest close (perf's reconstructed line), as if
everything had been sold that day and held as cash. It says honestly which
way it came out - ahead or behind - in percent, labelled hypothetical, with
the reminder that hindsight cuts both ways. It records the decision; it
never grades it ("the right call" is never said).
"""

from __future__ import annotations

from datetime import date, timedelta

import expedition_log

HYPOTHETICAL = "Hypothetical"
VALUE_SLACK = 7       # the walk day's close may be up to this many days before it
FLAT = 0.5            # within half a point either way: "about where your mix is now"
MONTHS_SHOWN = 12     # entries shown on the card

HINDSIGHT = ("Hindsight cuts both ways: after some walks selling would have come out "
             "ahead, after others behind, and nobody can know which beforehand. This "
             "records what you decided - it isn't a grade. Worked out on the holdings you "
             "have now at each day's closing price, before taxes, fees and any interest on "
             "cash.")


def entries(p: dict) -> list[dict]:
    """[{"month", "on"}] newest first: each logged walk with no sale since
    the walk before (the rule above)."""
    return [{"month": m, "on": rec["on"]}
            for m, rec in sorted(expedition_log.entries(p).items(), reverse=True)
            if not rec["sold"] and rec["on"]]


def entry_text(month: str) -> str:
    """'You stayed with your plan in October 2026.'"""
    return f"You stayed with your plan in {expedition_log.month_label(month)}."


def _clean(points) -> list[tuple[str, float]]:
    return sorted((str(d)[:10], float(v)) for d, v in points or ()
                  if d and v is not None and float(v) > 0)


def value_on(points, day: str) -> float | None:
    """The value at the last close on or before `day`, at most VALUE_SLACK
    days before it; None when there's none."""
    pts = [pt for pt in _clean(points) if pt[0] <= day[:10]]
    if not pts:
        return None
    floor = (date.fromisoformat(day[:10]) - timedelta(days=VALUE_SLACK)).isoformat()
    return pts[-1][1] if pts[-1][0] >= floor else None


def what_if(points, day: str) -> float | None:
    """Selling everything at the close on `day` and holding cash, against
    keeping the same holdings to the latest close: the percent difference
    from where the mix is now (positive: selling would be ahead, negative:
    behind), one decimal. None without prices on both days."""
    pts = _clean(points)
    then = value_on(pts, day)
    if then is None or not pts or pts[-1][0] <= day[:10]:
        return None
    return round((then / pts[-1][1] - 1) * 100, 1)


def what_if_text(day_words: str, pct: float) -> str:
    """The hypothetical in one sentence, whichever way it came out."""
    lead = f"{HYPOTHETICAL}: if you had sold everything on {day_words} and held cash, "
    if pct >= FLAT:
        return lead + f"you'd be about {pct:.1f}% ahead of where your mix is now."
    if pct <= -FLAT:
        return lead + f"you'd be about {abs(pct):.1f}% behind where your mix is now."
    return lead + "you'd be about where your mix is now."


def since(entries_: list[dict]) -> str | None:
    """The first day the hypotheticals need prices from (a little before the
    earliest entry shown), or None."""
    days = [e["on"] for e in entries_[:MONTHS_SHOWN] if e.get("on")]
    if not days:
        return None
    return (date.fromisoformat(min(days)) - timedelta(days=VALUE_SLACK)).isoformat()
