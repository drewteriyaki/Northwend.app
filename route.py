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


# ---- the expedition (ROADMAP T1): regions and the trail ---------------------- #
# Stretches of the Get started route, by waypoint key (the design system's
# "The expedition"): where you are is the region of your first waypoint not
# yet reached.
REGIONS = (
    ("Base camp", ("profile",)),
    ("The foothills", ("ready", "goal")),
    ("Learner's ridge", ("basics", "mix")),
    ("The practice range", ("practice",)),
    ("The summit", ("account",)),
)


def region(waypoints: list[tuple[str, str, bool]]) -> tuple[str, str | None]:
    """(the region you're in, the next one or None) from (key, title, done)."""
    names = [n for n, _ in REGIONS]
    here = next((k for k, _, done in waypoints if not done), None)
    if here is None:
        return names[-1], None
    i = next((n for n, (_, keys) in enumerate(REGIONS) if here in keys), len(REGIONS) - 1)
    return names[i], (names[i + 1] if i + 1 < len(names) else None)


# rising north: each dot a little higher than the last, with a gentle sway
_TRAIL_Y = (48, 30, 42, 24, 36, 18, 30, 14, 24)


# the design system's colours per theme (the app's --pt-* variables): the
# trail is an image (st.html strips inline SVG), so it can't read the CSS ones
TRAIL_COLORS = {
    "light": {"compass": "#2a78d6", "soft": "#e3eefb", "line": "#74838f", "dawn": "#f0b23c",
              "dawn_soft": "#fbebc9"},
    "dark": {"compass": "#3987e5", "soft": "#16304d", "line": "#62748a", "dawn": "#f2bd57",
             "dawn_soft": "#3a2f17"},
}


def trail_svg(states: list[str], c: dict) -> str:
    """The route drawn as a trail (dots from dots()) in colours `c`: solid
    compass for the legs walked, dotted ahead, the goal a disc."""
    n = len(states)
    w, pad = 640, 16
    xs = [pad + i * (w - 2 * pad) / max(1, n - 1) for i in range(n)]
    ys = [_TRAIL_Y[i % len(_TRAIL_Y)] for i in range(n)]
    all_done = all(s == "done" for s in states[:-1])
    legs = []
    for i in range(n - 1):
        walked = states[i] == "done" and (states[i + 1] in ("done", "here")
                                          or (states[i + 1].startswith("goal") and all_done))
        mid = (xs[i] + xs[i + 1]) / 2
        d = (f"M{xs[i]:.1f} {ys[i]} C{mid:.1f} {ys[i]} {mid:.1f} {ys[i + 1]} "
             f"{xs[i + 1]:.1f} {ys[i + 1]}")
        legs.append(f'<path d="{d}" stroke="{c["compass"]}" stroke-width="3"/>' if walked else
                    f'<path d="{d}" stroke="{c["line"]}" stroke-width="2.5" '
                    f'stroke-dasharray="2 8"/>')
    dots = []
    for x, y, s in zip(xs, ys, states):
        if s == "done":
            dots.append(f'<circle cx="{x:.1f}" cy="{y}" r="7" fill="{c["compass"]}"/>')
        elif s == "here":
            dots.append(f'<circle cx="{x:.1f}" cy="{y}" r="9" fill="{c["soft"]}" '
                        f'stroke="{c["compass"]}" stroke-width="3.5"/>')
        elif s == "goal_reached":
            dots.append(f'<circle cx="{x:.1f}" cy="{y}" r="10" fill="{c["dawn"]}"/>')
        elif s == "goal":
            dots.append(f'<circle cx="{x:.1f}" cy="{y}" r="10" fill="{c["dawn_soft"]}" '
                        f'stroke="{c["dawn"]}" stroke-width="2.5"/>')
        else:
            dots.append(f'<circle cx="{x:.1f}" cy="{y}" r="6" fill="none" '
                        f'stroke="{c["line"]}" stroke-width="2"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} 64" width="{w}" '
            f'height="64" fill="none" stroke-linecap="round">{"".join(legs)}{"".join(dots)}</svg>')


def trail_html(states: list[str], label: str) -> str:
    """The trail as two images, one per theme (the app's styles show the one
    that matches), with `label` as their text for screen readers."""
    import base64
    from html import escape
    label = escape(label, quote=True)
    out = []
    for theme, colors in TRAIL_COLORS.items():
        data = base64.b64encode(trail_svg(states, colors).encode("utf-8")).decode("ascii")
        out.append(f"<img class='pt-trail pt-on-{theme}' alt='{label}' "
                   f"src='data:image/svg+xml;base64,{data}'>")
    return "".join(out)
