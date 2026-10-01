"""Client progress reports (ROADMAP G8): a short summary an advisor sends a
client for a month or a quarter - how the portfolio moved, how much of that
was money added, progress to the goal, and what's next - with the advisor's
own message. Stored, so the client reads it in the app (and as a PDF); the
email only says a report is waiting, never the figures.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import plans

PERIODS = ("Last month", "Last quarter", "Since the last report")
PDF_FOOTER = ("Prepared by your advisor in Northwend. Past results don't predict future ones; "
              "all investing involves risk, including loss.")


def period_bounds(kind: str, today: date, last_end: str | None = None) -> tuple[date, date, str]:
    """(start, end, label) for a report period ending before `today`."""
    first_this_month = today.replace(day=1)
    if kind == "Last month":
        end = first_this_month - timedelta(days=1)
        start = end.replace(day=1)
        return start, end, f"{start:%B} {start.year}"
    if kind == "Last quarter":
        q_start_month = 3 * ((today.month - 1) // 3) + 1
        end = today.replace(month=q_start_month, day=1) - timedelta(days=1)
        start = end.replace(month=3 * ((end.month - 1) // 3) + 1, day=1)
        return start, end, f"Q{(start.month - 1) // 3 + 1} {start.year}"
    start = (date.fromisoformat(last_end) + timedelta(days=1)) if last_end else today - timedelta(days=90)
    end = today
    return start, end, f"{start:%b} {start.day} - {end:%b} {end.day}, {end.year}"


def _value_between(conn, user_id: int, first: date, last: date, *, latest: bool) -> float | None:
    """A logged portfolio value between two days (value_log is written when
    the account is opened, so there may be none): the latest or earliest."""
    row = conn.execute("SELECT portfolio_value FROM value_log WHERE user_id = ? AND "
                       "substr(logged_at, 1, 10) BETWEEN ? AND ? AND portfolio_value IS NOT NULL "
                       f"ORDER BY logged_at {'DESC' if latest else 'ASC'} LIMIT 1",
                       (user_id, first.isoformat(), last.isoformat())).fetchone()
    return row["portfolio_value"] if row else None


def build(conn, client_id: int, start: date, end: date, *, value_now: float | None,
          today: date) -> dict:
    """The report's figures: value_start, value_end, money_in, growth (None
    where unknown), goal ({"pct", "status", "target", "target_date",
    "goal_name"} or None), next_steps (the advisor's open, shared next steps,
    first lines)."""
    # only values close to the period's edges count; otherwise they're unknown
    v_start = (_value_between(conn, client_id, start - timedelta(days=31), start, latest=True)
               or _value_between(conn, client_id, start, start + timedelta(days=7),
                                 latest=False))
    if value_now is not None and (today - end).days <= 7:
        v_end = value_now
    else:
        v_end = _value_between(conn, client_id, end - timedelta(days=14), end, latest=True)
    # logged by hand, or from imported activity history (plans.money_added)
    money_in = plans.money_added(conn, client_id, start.isoformat(), end.isoformat())
    growth = (v_end - v_start - money_in) if v_start is not None and v_end is not None else None
    plan = plans.get_plan(conn, client_id)
    goal = None
    if plans.has_goal(plan) and v_end is not None:
        g = plans.progress(plan, v_end, today=today)
        goal = {"pct": g["pct_of_target"], "status": g["status"], "target": g["target"],
                "target_date": plan["target_date"],
                "goal_name": plan.get("goal_name") or plan.get("goal_type")}
    steps = [r["body"].splitlines()[0][:120] for r in conn.execute(
        "SELECT body FROM advisor_notes WHERE client_id = ? AND kind = 'Next step' AND "
        "COALESCE(done, 0) = 0 AND COALESCE(private, 0) = 0 ORDER BY note_date DESC LIMIT 5",
        (client_id,))]
    return {"value_start": v_start, "value_end": v_end, "money_in": money_in, "growth": growth,
            "goal": goal, "next_steps": steps}


def save(conn, advisor_id: int, client_id: int, *, label: str, start: date, end: date,
         facts: dict, message: str) -> int:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("INSERT INTO progress_reports (advisor_id, client_id, period_label, "
                 "period_start, period_end, facts_json, message, created_at) "
                 "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (advisor_id, client_id, label[:60], start.isoformat(), end.isoformat(),
                  json.dumps(facts), (message or "").strip()[:3000], now))
    conn.commit()
    return conn.execute("SELECT MAX(id) AS id FROM progress_reports WHERE client_id = ?",
                        (client_id,)).fetchone()["id"]


def for_client(conn, client_id: int) -> list[dict]:
    out = []
    for r in conn.execute("SELECT * FROM progress_reports WHERE client_id = ? ORDER BY id DESC",
                          (client_id,)):
        d = dict(r)
        d["facts"] = json.loads(d.pop("facts_json") or "{}")
        out.append(d)
    return out


def last_end(conn, client_id: int) -> str | None:
    row = conn.execute("SELECT MAX(period_end) AS d FROM progress_reports WHERE client_id = ?",
                       (client_id,)).fetchone()
    return row["d"] if row else None


def mark_read(conn, client_id: int, report_id: int) -> None:
    conn.execute("UPDATE progress_reports SET read_at = COALESCE(read_at, ?) WHERE id = ? AND "
                 "client_id = ?", (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                                   report_id, client_id))
    conn.commit()


def summary_lines(facts: dict, money) -> list[str]:
    """The report as plain sentences; `money` formats an amount (so the app
    can mask it)."""
    lines = []
    vs, ve, mi, gr = (facts.get(k) for k in ("value_start", "value_end", "money_in", "growth"))
    if vs is not None and ve is not None:
        lines.append(f"Your portfolio went from {money(vs)} to {money(ve)}.")
        parts = []
        if mi:
            parts.append(f"{money(abs(mi))} {'added' if mi > 0 else 'taken out'} by you")
        if gr is not None:
            parts.append(f"{money(abs(gr))} {'growth' if gr >= 0 else 'fall'} from the markets")
        if parts:
            lines.append("That's " + " and ".join(parts) + ".")
    elif ve is not None:
        lines.append(f"Your portfolio is worth {money(ve)}.")
    g = facts.get("goal")
    if g:
        words = {"reached": "reached", "on_track": "on track", "within_reach": "within reach",
                 "behind": "behind", "past_date": "past its date"}.get(g["status"], g["status"])
        lines.append(f"{g['goal_name'] or 'Your goal'}: {g['pct'] or 0:.0f}% of {money(g['target'])} "
                     f"by {g['target_date'][:7]} - {words}.")
    return lines


def render_pdf(report: dict, *, client_name: str, advisor_name: str) -> bytes:
    from fpdf import FPDF

    from client_plan import _money0, _safe

    class _ReportPDF(FPDF):
        def footer(self):
            self.set_y(-18)
            self.set_font("Helvetica", "I", 7)
            self.set_text_color(110)
            self.multi_cell(0, 3.5, _safe(PDF_FOOTER), align="C")
            self.set_text_color(0)

    pdf = _ReportPDF(format="Letter")
    pdf.set_auto_page_break(auto=True, margin=22)
    pdf.set_margins(18, 16, 18)
    pdf.add_page()

    def para(text, size=10, style=""):
        pdf.set_font("Helvetica", style, size)
        pdf.multi_cell(0, 5.5, _safe(text), align="L", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, _safe(f"Your progress: {report['period_label']}"), new_x="LMARGIN",
             new_y="NEXT")
    pdf.set_text_color(90)
    para(f"For {client_name}, from {advisor_name}  |  {report['created_at'][:10]}", 9.5)
    pdf.set_text_color(0)
    pdf.ln(2)
    if report.get("message"):
        para(report["message"])
        pdf.ln(2)
    for line in summary_lines(report["facts"], _money0):
        para(line)
    steps = report["facts"].get("next_steps") or []
    if steps:
        pdf.ln(2)
        para("What's next", 12, "B")
        for s in steps:
            para(f"- {s}")
    return bytes(pdf.output())
