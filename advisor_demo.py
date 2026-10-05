"""A made-up advisor's book (ROADMAP 7), for someone whose advisor access is
still being checked (auth.request_advisor): "See what you'll get" shows Your
clients with three example clients, a shared proposal, a progress report and
meeting prep - so the wait isn't a blank one.

Everything here is in memory: no database, no accounts, no emails, no AI
(the talking points are a fixed sample). Nothing in it can appear in a real
list, count, export or email, because it is never written anywhere. The
numbers go through the app's own pure logic (advising.attention,
proposals.compare, reports.summary_lines) so the preview looks like the
real pages. Kinds of funds only, never tickers.
"""

from __future__ import annotations

from datetime import date, timedelta

import advising
import proposals

LABEL = "Example"

# made-up people: plain, varied, obviously sample
_CLIENTS = [
    {"id": 1, "name": "Rivera household", "value": 412_300.0, "gain_pct": 18.4,
     "goal": {"name": "Retirement", "pct": 64.0, "target": 1_200_000.0, "status": "on_track",
              "years": 15},
     "review_days": 41, "n_steps": 1, "proposal": "shared", "last_report": "Q3 2026",
     "login_days": 3, "drift": 2.0, "alerts": 0, "profile_done": True},
    {"id": 2, "name": "Sam Okafor", "value": 96_850.0, "gain_pct": 7.2,
     "goal": {"name": "College fund", "pct": 41.0, "target": 90_000.0, "status": "behind",
              "years": 6},
     "review_days": 104, "n_steps": 2, "proposal": "accepted", "last_report": None,
     "login_days": 12, "drift": 7.0, "alerts": 1, "profile_done": True},
    {"id": 3, "name": "Lee family", "value": 238_900.0, "gain_pct": -1.3, "goal": None,
     "review_days": None, "n_steps": 0, "proposal": None, "last_report": None,
     "login_days": None, "drift": None, "alerts": 0, "profile_done": False},
]

# the Rivera household's shared proposal
PROPOSAL = {
    "client": "Rivera household",
    "title": "A steadier mix for the next fifteen years",
    "note": "You told me the 2022 drop kept you up at night. Moving some of the stock "
            "funds into a bond fund means smaller swings, and the plan still reaches "
            "your retirement goal on time.",
    "today": {"Stocks": 78.0, "Bonds": 17.0, "Cash": 5.0},
    "proposed": {"Stocks": 65.0, "Bonds": 30.0, "Cash": 5.0},
    "monthly": 1_500.0,
}

# the Rivera household's progress report
REPORT = {
    "client": "Rivera household",
    "period": "Q3 2026",
    "facts": {"value_start": 398_100.0, "value_end": 412_300.0, "money_in": 4_500.0,
              "growth": 9_700.0,
              "goal": {"goal_name": "Retirement", "pct": 64.0, "target": 1_200_000.0,
                       "status": "on_track", "target_date": "2041-06-30"},
              "next_steps": ["Open a Roth IRA for Maria before the end of the year"]},
    "message": "A steady quarter. Your monthly savings did a good part of the work, and "
               "you're on track for retirement. Nothing to change right now.",
}

# meeting prep for Sam Okafor (what meeting.prep finds, written out)
MEETING = {
    "client": "Sam Okafor",
    "facts": [
        "**Last review:** 104 days ago - a review is due",
        "**Value since then:** +$3,120 (+3.3%)",
        "**Changes in holdings:** Added to: a US stock index fund; New: a short-term bond fund",
        "**Goal:** behind - 41% of $90,000, 6 years left",
        "**Drift:** Stocks 72% vs 65% target (+7 pts)",
        "**Open next steps:** Raise the monthly amount to $650; Check the 529 plan's options",
        "**Proposal:** Catch up on the college fund - accepted",
    ],
    # a fixed sample - the real ones are drafted on request, then edited by the advisor
    "talking_points": [
        "Start with the good news: the account grew by about $3,100 since we last spoke.",
        "The college fund is behind. Walk through raising the monthly amount to $650 - "
        "what it does to the date.",
        "Stocks have drifted 7 points over the target mix. Agree on rebalancing with new "
        "money first, so nothing has to be sold.",
        "Sam said yes to the proposal - confirm the next step and when it happens.",
        "Ask: has anything changed at work or at home since spring?",
    ],
}


def _review(days: int | None) -> str:
    if days is None:
        return "never"
    return "due" if days > advising.REVIEW_EVERY_DAYS else "ok"


def book(today: date) -> list[dict]:
    """The example clients as Your clients shows them: name (with LABEL),
    value, gain, goal, review, next steps, why they need a look - sorted the
    same way (most reasons first, then the biggest)."""
    rows = []
    for c in _CLIENTS:
        review = _review(c["review_days"])
        goal = c["goal"]
        if goal:
            goal = {**goal, "target_date": (today + timedelta(days=365 * goal["years"]))}
        rows.append({
            **c, "label": LABEL, "goal": goal, "review": review,
            "reasons": advising.attention(
                has_data=True, goal_status=goal["status"] if goal else None, review=review,
                n_alerts=c["alerts"], drift=c["drift"], profile_done=c["profile_done"],
                proposal_accepted=c["proposal"] == "accepted",
                days_since_login=c["login_days"])})
    rows.sort(key=lambda r: (-len(r["reasons"]), -r["value"]))
    return rows


def proposal_compare() -> dict:
    """proposals.compare for the example proposal (fifteen years to the goal)."""
    p = PROPOSAL
    return proposals.compare(p["today"], p["proposed"], value=412_300.0, monthly=p["monthly"],
                             months=15 * 12)
