"""Meeting prep (ROADMAP G7): before a review, one view of what changed since
the last one - value, buys and sells, goal progress, drift, open next steps,
proposals - and talking points the AI drafts for the advisor to edit.

prep() is pure storage reads; talking_points() calls Claude with percentages
and facts only (no dollar amounts, no notes - the same rule as Ask Northwend).
"""

from __future__ import annotations

from datetime import date

import advising
import changes
import plans
import proposals

TALKING_POINTS_REQUEST = (
    "You are helping a financial advisor prepare for a review meeting with their client. "
    "From the client's profile, holdings summary and the facts below, draft 4 to 6 short "
    "talking points for the advisor: what to celebrate, what to check in about, and questions "
    "to ask the client. The advisor makes any recommendation themselves: follow your rules - "
    "don't recommend buying, selling or holding a specific security, or a specific mix; "
    "describe the facts and the considerations instead. Output only the points, one per "
    "line, each starting with \"- \", plain text, no headings."
)


def _snapshot_on_or_before(conn, user_id: int, day: str) -> str | None:
    row = conn.execute("SELECT MAX(snapshot_date) AS d FROM snapshots WHERE user_id = ? AND "
                       "snapshot_date <= ?", (user_id, day)).fetchone()
    return row["d"] if row else None


def _positions(conn, user_id: int, snapshot_date: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT account, symbol, description, quantity, cost_basis, market_value "
        "FROM positions WHERE user_id = ? AND snapshot_date = ?", (user_id, snapshot_date))]


def _value_at(conn, user_id: int, day: str) -> float | None:
    """The portfolio value logged on or before `day` (value_log), if any."""
    row = conn.execute("SELECT portfolio_value FROM value_log WHERE user_id = ? AND "
                       "substr(logged_at, 1, 10) <= ? AND portfolio_value IS NOT NULL "
                       "ORDER BY logged_at DESC LIMIT 1", (user_id, day)).fetchone()
    return row["portfolio_value"] if row else None


def prep(conn, client_id: int, *, today: date, value: float | None, latest_snapshot: str | None,
         actual_pct: dict, targets: dict, drift_threshold: float,
         return_pct: float = plans.DEFAULT_RETURN_PCT, advisor_id: int | None = None) -> dict:
    """Everything the prep view shows. `value` is today's portfolio value;
    `actual_pct` the mix by asset class now. Keys: last_review (date or
    None), days_since, value_then, value_now, value_change, value_change_pct,
    trades ({"bought": [...], "sold": [...], "new": [...], "closed": [...]} of
    "SYM (account)" or None when there's nothing to compare), goal
    (plans.progress or None), drift ([(class, actual, target, delta)]),
    next_steps (open ones), proposals (waiting / accepted)."""
    last = advising.last_review(conn, client_id)
    out = {"last_review": last, "days_since": None, "value_then": None, "value_now": value,
           "value_change": None, "value_change_pct": None, "trades": None}
    if last:
        out["days_since"] = (today - date.fromisoformat(last[:10])).days
        then = _value_at(conn, client_id, last[:10])
        out["value_then"] = then
        if then and value is not None:
            out["value_change"] = value - then
            out["value_change_pct"] = (value - then) / then * 100
        old_snap = _snapshot_on_or_before(conn, client_id, last[:10])
        if old_snap and latest_snapshot and old_snap != latest_snapshot:
            d = changes.diff_positions(_positions(conn, client_id, old_snap),
                                       _positions(conn, client_id, latest_snapshot))
            fmt = lambda e: f"{e['symbol']} ({e['account']})"  # noqa: E731
            out["trades"] = {"new": [fmt(e) for e in d["new"]],
                             "bought": [fmt(e) for e in d["increased"]],
                             "sold": [fmt(e) for e in d["decreased"]],
                             "closed": [fmt(e) for e in d["closed"]]}
        elif old_snap:
            out["trades"] = {"new": [], "bought": [], "sold": [], "closed": []}
    plan = plans.get_plan(conn, client_id)
    out["goal"] = (plans.progress(plan, value or 0.0, today=today, return_pct=return_pct)
                   if plans.has_goal(plan) else None)
    out["plan"] = plan
    out["drift"] = sorted(
        [(k, actual_pct.get(k, 0.0) or 0.0, t, (actual_pct.get(k, 0.0) or 0.0) - t)
         for k, t in targets.items() if abs((actual_pct.get(k, 0.0) or 0.0) - t) > drift_threshold],
        key=lambda r: -abs(r[3]))
    out["next_steps"] = advising.open_next_steps(
        advising.list_notes(conn, client_id, include_private=True, advisor_id=advisor_id))
    out["proposals"] = [p for p in proposals.for_client(conn, client_id, include_drafts=False)
                        if p["status"] in ("shared", "accepted")]
    return out


def facts_for_ai(p: dict) -> str:
    """The prep as plain lines for the AI: percentages and facts only - no
    dollar amounts, no note text."""
    lines = []
    if p["last_review"]:
        lines.append(f"Last review: {p['days_since']} days ago.")
    else:
        lines.append("This is the first review.")
    if p["value_change_pct"] is not None:
        lines.append(f"Portfolio value since the last review: {p['value_change_pct']:+.1f}%.")
    t = p["trades"]
    if t:
        for label, key in (("New holdings", "new"), ("Added to", "bought"),
                           ("Reduced", "sold"), ("Sold out of", "closed")):
            if t[key]:
                lines.append(f"{label}: " + ", ".join(s.split(" (")[0] for s in t[key]) + ".")
    g = p["goal"]
    if g:
        lines.append(f"Goal: {g['pct_of_target'] or 0:.0f}% of the target, {g['months']} months "
                     f"left, status {g['status'].replace('_', ' ')}.")
    else:
        lines.append("No goal set yet.")
    for k, a, tgt, d in p["drift"]:
        lines.append(f"{k}: {a:.0f}% vs a {tgt:.0f}% target ({d:+.0f} points).")
    if p["next_steps"]:
        lines.append(f"Open next steps from earlier meetings: {len(p['next_steps'])}.")
    for pr in p["proposals"]:
        lines.append("A proposed new mix is "
                     + ("accepted by the client." if pr["status"] == "accepted"
                        else "waiting for the client's answer."))
    return "\n".join(lines)


def talking_points(client, profile: dict, summary: str, facts: str, *,
                   user_id: int | None = None) -> list[str] | None:
    """Draft talking points (a list of lines), or None if the model declined.
    API errors (and the gateway's Refused) propagate for the caller to
    report. `summary` is advisor.portfolio_summary() output (weights only);
    `user_id` the advisor, whose allowance it uses (ai_gateway.py)."""
    import advisor
    import ai_gateway

    message = ai_gateway.call(
        "prep", client=client, user_id=user_id,
        system=advisor.system_prompt(profile, summary, ""),
        messages=[{"role": "user", "content": "## Since the last review\n" + facts + "\n\n"
                   + TALKING_POINTS_REQUEST}])
    if message.stop_reason == "refusal":
        return None
    text = "".join(b.text for b in message.content if b.type == "text").strip()
    if not text:
        return None
    pts = [ln.strip()[2:].strip() for ln in text.splitlines() if ln.strip().startswith("- ")]
    return pts or [text]
