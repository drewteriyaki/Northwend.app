"""The investor home's "Your route" (ROADMAP G2): where someone is on the way
to their goal, and the one next step that matters most right now.

Pure functions over plain values, so the order of priorities is easy to test
and change; the Home page (views/dashboard_page.py) turns the result into
words and a button. Nothing here gives investment advice: steps point to the
person's own plan, profile and learning waypoints.
"""

from __future__ import annotations

STALE_DAYS = 45       # holdings older than this get "update your holdings"


def next_step(*, has_goal: bool, can_manage: bool, profile_missing: bool,
              has_holdings: bool, monthly: float, goal: dict | None,
              drift: list[tuple[str, float, float, float]], days_since_holdings: int | None,
              waypoints: list[tuple[str, str, bool]]) -> dict:
    """The single next step, as {"key", ...details}. In order:

    goal       - no goal yet (or "goal_wait": an advisor-managed client)
    profile    - the few questions about you are unanswered
    holdings   - nothing brought in yet
    monthly    - a goal but no monthly amount
    gap        - behind (or only within reach): what monthly amount closes it
    drift      - the mix is past its drift limit from the target
    update     - holdings not brought in for STALE_DAYS
    learn      - a Get started waypoint not done yet
    reached    - the goal is reached: time for the next one
    steady     - on track; keep going

    `goal` is plans.progress() output; `drift` is [(class, actual %, target
    %, delta pts)] past the limit, biggest first; `waypoints` is Get
    started's [(key, title, done)] in order."""
    if not has_goal:
        return {"key": "goal" if can_manage else "goal_wait"}
    if profile_missing and can_manage:
        return {"key": "profile"}
    if not has_holdings:
        return {"key": "holdings"}
    status = (goal or {}).get("status")
    if status == "reached":
        return {"key": "reached"}
    if can_manage and not monthly:
        return {"key": "monthly", "needed": (goal or {}).get("needed_monthly")}
    if status in ("behind", "within_reach") and can_manage:
        needed = (goal or {}).get("needed_monthly")
        if needed and needed > monthly:
            return {"key": "gap", "needed": needed, "extra": needed - monthly}
    if drift:
        label, actual, target, delta = drift[0]
        return {"key": "drift", "label": label, "actual": actual, "target": target,
                "delta": delta}
    if days_since_holdings is not None and days_since_holdings > STALE_DAYS and can_manage:
        return {"key": "update", "days": days_since_holdings}
    for i, (key, title, done) in enumerate(waypoints, start=1):
        if not done:
            return {"key": "learn", "number": i, "step": key, "title": title}
    return {"key": "steady", "status": status}


def dots(waypoints: list[tuple[str, str, bool]], goal_reached: bool) -> list[str]:
    """The route as dot states, one per waypoint then the goal: 'done', 'here'
    (the first not done), 'todo', and finally 'goal' or 'goal_reached'."""
    out, here_set = [], False
    for _, _, done in waypoints:
        if done:
            out.append("done")
        elif not here_set:
            out.append("here")
            here_set = True
        else:
            out.append("todo")
    out.append("goal_reached" if goal_reached else "goal")
    return out


def drifted(actual_pct: dict[str, float], targets: dict[str, float],
            threshold: float) -> list[tuple[str, float, float, float]]:
    """Asset classes past `threshold` points from their target, biggest first."""
    rows = []
    for label, target in targets.items():
        actual = actual_pct.get(label, 0.0) or 0.0
        delta = actual - target
        if abs(delta) > threshold:
            rows.append((label, actual, target, delta))
    return sorted(rows, key=lambda r: abs(r[3]), reverse=True)
