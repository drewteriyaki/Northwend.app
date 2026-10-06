"""Downloadable client plan: a PDF of one account's profile, holdings, and
suggested next steps.

Pure logic, no Streamlit; dashboard.py's AI Assistant page owns the button.

What leaves the machine: only next_steps() calls the API, with the same
weights-only portfolio summary the chat uses (advisor.portfolio_summary) and
the session's chat transcript, plus the assistant's own saved notes (which
are never printed in the PDF). The dollar figures in the PDF are computed and
rendered locally.
"""

from __future__ import annotations

import re
from datetime import date

from fpdf import FPDF

import advising
import advisor
import asset_classes
import plans
import alerts
import metrics as M
import overview
from allocation import CONCENTRATION_PCT, SHORT_ASSET_TYPE, allocate

MAX_TOKENS = 4000
DISCLAIMER = ("Educational information only - not financial advice. The assistant is not a "
              "licensed financial advisor; do your own research before making any investment "
              "decision.")

_NEXT_STEPS_REQUEST = (
    "Write the \"Suggested next steps\" section of a short written plan for this person, "
    "based on their profile, their holdings, and the conversation so far (if any). Give 3 to 6 "
    "concrete, educational steps tied to their goals and risk tolerance: things to learn, "
    "check, decide for themselves or ask a professional about. Follow your rules - no step "
    "may recommend buying, selling or holding a specific security, or a specific mix for "
    "them. If profile answers are missing, one step can be to settle them. Output only the "
    "steps, one per line, each starting with \"- \", in plain text: no headings, no bold, no "
    "intro or closing line."
)

# printed under the AI-written steps
AI_STEPS_NOTE = ("Written by AI for education - not a recommendation to buy, sell or hold "
                 "anything. Any figure about the future is hypothetical. Talk to a licensed "
                 "professional before acting on it.")


# --------------------------------------------------------------------------- #
# facts (computed locally, dollars included)
# --------------------------------------------------------------------------- #
def build_facts(conn, user_id: int, contexts: list[dict], cash_by_account: dict,
                rules=None) -> dict:
    """Everything the PDF shows except the AI section. `contexts` is
    dashboard.py's per-position metric context list."""
    profile = advisor.get_profile(conn, user_id)
    quotes = {c["pos"]["symbol"]: c.get("quote") or {} for c in contexts}
    summary = overview.account_summary(conn, user_id, quotes, rules)
    splits = asset_classes.splits(conn, [c["pos"] for c in contexts],
                                  asset_classes.load_overrides(conn, user_id))
    alloc = allocate([{**c["pos"], "live_market_value": M.eff_mv(c)} for c in contexts],
                     cash_by_account, splits)
    port = alloc["portfolio_value"]

    holdings = []
    for c in contexts:
        mv = M.eff_mv(c)
        holdings.append({
            "symbol": c["pos"].get("symbol"),
            "description": c["pos"].get("description"),
            "asset_type": SHORT_ASSET_TYPE.get(c["pos"].get("asset_type"), c["pos"].get("asset_type")),
            "account": c["pos"].get("account"),
            "value": mv,
            "weight_pct": (mv / port * 100) if (mv is not None and port) else None,
            "gain_pct": M.value("unrealized_pct", {**c, "port_value": port}),
        })
    holdings.sort(key=lambda h: h["value"] or 0.0, reverse=True)

    plan = plans.get_plan(conn, user_id)
    money_out = plans.list_money_out(conn, user_id)   # planned expenses, regular withdrawal
    goal = (plans.progress(plan, summary["portfolio_value"] or 0.0, today=date.today(),
                           items=money_out)
            if plans.has_goal(plan) else None)
    # the advisor's open next steps the client can see - never private notes
    advisor_steps = [n["body"] for n in advising.open_next_steps(
        advising.list_notes(conn, user_id, include_private=False))]

    return {
        "profile": profile,
        "plan": plan,
        "goal": goal,
        "money_out": money_out,
        "advisor_steps": advisor_steps,
        "missing": advisor.missing_fields(profile),
        "summary": summary,
        "cash": round(sum(float(v or 0.0) for v in cash_by_account.values()), 2),
        "by_asset_class": alloc["by_asset_class"],
        "by_asset_type": alloc["by_asset_type"],
        "by_account": alloc["by_account"],
        "concentration": alloc["concentration"],
        "alerts": alerts.evaluate(contexts, rules),
        "holdings": holdings,
    }


# --------------------------------------------------------------------------- #
# the one API call (percentages only)
# --------------------------------------------------------------------------- #
def next_steps(client, profile: dict, summary: str, chat_text: str = "",
               memory: str = "", *, user_id: int | None = None) -> list[str] | None:
    """Suggested next steps as a list of short lines, or None if the model
    declined. API errors propagate so the caller can say what went wrong.
    `summary` must be advisor.portfolio_summary() output (weights only);
    `memory` is the assistant's saved notes (advisor.get_memory); the call
    goes through ai_gateway (`user_id`: whose allowance)."""
    import ai_gateway
    content = _NEXT_STEPS_REQUEST
    if chat_text.strip():
        content = "## Conversation so far\n" + chat_text.strip() + "\n\n" + content
    message = ai_gateway.call("plan", client=client, user_id=user_id,
                              system=advisor.system_prompt(profile, summary, memory),
                              messages=[{"role": "user", "content": content}])
    if message.stop_reason == "refusal":
        return None
    text = "".join(b.text for b in message.content if b.type == "text").strip()
    if not text:
        return None
    steps = [ln.strip()[2:].strip() for ln in text.splitlines() if ln.strip().startswith("- ")]
    return steps or [text]


def chat_transcript(display: list[dict]) -> str:
    """The AI Assistant page's chat_display list as plain text."""
    who = {"user": "User", "assistant": "Assistant"}
    return "\n\n".join(f"{who.get(m['role'], m['role'])}: {m['text']}" for m in display)


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #
_ASCII = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": " - ",
    "…": "...", "•": "-", " ": " ", "−": "-", "▲": "+", "▼": "-",
    "→": "->", "≤": "<=", "≥": ">=",
})


def _safe(s) -> str:
    """The built-in PDF fonts are latin-1 only; anything else would raise."""
    text = re.sub(r"(?<=\S) {2,}(?=\S)", " ", str(s if s is not None else "").translate(_ASCII))
    return text.encode("latin-1", "replace").decode("latin-1")


def _money(v) -> str:
    return "n/a" if v is None else f"-${abs(v):,.2f}" if v < 0 else f"${v:,.2f}"


def _money0(v) -> str:
    return "n/a" if v is None else f"${v:,.0f}"


def _pct(v, signed=False) -> str:
    return "n/a" if v is None else (f"{v:+.1f}%" if signed else f"{v:.1f}%")


class _PlanPDF(FPDF):
    def footer(self):
        self.set_y(-18)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(110)
        self.multi_cell(0, 3.5, _safe(DISCLAIMER + f"   Page {self.page_no()}"), align="C")
        self.set_text_color(0)


def render_pdf(facts: dict, steps: list[str] | None, *, account_name: str,
               advisor_name: str | None = None, today: date | None = None) -> bytes:
    pdf = _PlanPDF(format="Letter")
    pdf.set_auto_page_break(auto=True, margin=22)
    pdf.set_margins(18, 16, 18)
    pdf.add_page()
    s = facts["summary"]

    def heading(text):
        if pdf.will_page_break(25):  # keep a heading with what follows it
            pdf.add_page()
        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 7, _safe(text), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9.5)

    def para(text):
        pdf.multi_cell(0, 5, _safe(text), align="L", new_x="LMARGIN", new_y="NEXT")

    def table(header, rows, widths, align):
        pdf.set_font("Helvetica", "", 8.5)
        with pdf.table(col_widths=widths, text_align=align, line_height=5) as t:
            r = t.row()
            for h in header:
                r.cell(_safe(h))
            for row in rows:
                r = t.row()
                for v in row:
                    r.cell(_safe(v))
        pdf.set_font("Helvetica", "", 9.5)

    # header
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, _safe(f"Investment plan: {account_name}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(90)
    line = f"Prepared {(today or date.today()).isoformat()}"
    if advisor_name:
        line += f" by {advisor_name}"
    if s.get("snapshot_date"):
        line += f"  |  Holdings as of {s['snapshot_date']}"
    para(line)
    pdf.set_text_color(0)

    # profile
    heading("Investing profile")
    p = facts["profile"]
    for field, label in advisor.PROFILE_FIELDS.items():
        v = p.get(field)
        if field == "target_return_pct" and v not in (None, ""):
            v = f"{float(v):g}%"
        para(f"{label}: {v if v not in (None, '') else 'not set'}")
    if facts["missing"]:
        para("Still to discuss: " + ", ".join(advisor.PROFILE_FIELDS[f] for f in facts["missing"]) + ".")

    # goal
    g, plan = facts.get("goal"), facts.get("plan") or {}
    if g:
        heading("Goal")
        words = {"reached": "reached", "starting": "just starting out", "on_track": "on track", "within_reach": "within reach",
                 "behind": "behind", "past_date": "past its date"}[g["status"]]
        para(f"{plan.get('goal_name') or plan.get('goal_type') or 'Goal'}: "
             f"{_money0(g['target'])} by {plan['target_date'][:7]}, adding "
             f"{_money0(g['monthly'])} a month. Now {_money0(g['current'])} "
             f"({g['pct_of_target'] or 0:.0f}% of the goal) - {words}.")
        if g["status"] in ("on_track", "within_reach", "behind", "starting"):
            para(f"At {plans.DEFAULT_RETURN_PCT:g}% a year it would reach about "
                 f"{_money0(g['projected'])} "
                 f"({_money0(g['projected_low'])} to {_money0(g['projected_high'])} at "
                 f"{plans.DEFAULT_RETURN_PCT - plans.SPREAD_PCT:g}-"
                 f"{plans.DEFAULT_RETURN_PCT + plans.SPREAD_PCT:g}%)."
                 + (f" Reaching the goal at {plans.DEFAULT_RETURN_PCT:g}% would take about "
                    f"{_money0(g['needed_monthly'])} a month." if g["status"] != "on_track" else "")
                 + " An illustration, before inflation, fees and taxes - not a prediction.")
        if plan.get("target_alloc"):
            para("Target mix: " + ", ".join(f"{k} {v:g}%" for k, v in sorted(
                plan["target_alloc"].items(), key=lambda kv: -kv[1])) + ".")
    if facts.get("money_out"):
        if not g:
            heading("Goal")
        para("Money going out: " + plans.money_out_text(facts["money_out"], _money0)
             + (" - taken out of the figures above on their dates." if g else "."))

    # summary
    heading("Portfolio summary")
    if not s.get("has_data"):
        para("No holdings imported yet.")
    else:
        para(f"Total value: {_money(s['portfolio_value'])}   Cash: {_money(facts['cash'])}   "
             f"Gain/loss on cost: {_pct(s['gain_pct'], signed=True)}   "
             f"Positions: {s['n_positions']}")

        heading("Allocation by asset class")
        table(["Asset class", "Value", "Share"],
              [(r["label"], _money(r["value"]), _pct(r["pct"])) for r in facts["by_asset_class"]],
              (90, 45, 30), ("LEFT", "RIGHT", "RIGHT"))
        if len(facts["by_account"]) > 1:
            heading("Allocation by account")
            table(["Account", "Value", "Share"],
                  [(r["label"], _money(r["value"]), _pct(r["pct"])) for r in facts["by_account"]],
                  (90, 45, 30), ("LEFT", "RIGHT", "RIGHT"))

        heading("Holdings")
        table(["Symbol", "Name", "Type", "Value", "Weight", "Gain/loss"],
              [(h["symbol"], (h["description"] or "")[:40], h["asset_type"] or "",
                _money(h["value"]), _pct(h["weight_pct"]), _pct(h["gain_pct"], signed=True))
               for h in facts["holdings"]],
              (18, 62, 34, 28, 18, 20), ("LEFT", "LEFT", "LEFT", "RIGHT", "RIGHT", "RIGHT"))

        heading("Things to watch")
        watch = [f"{c['symbol']} is {c['pct']:.1f}% of the portfolio (above {CONCENTRATION_PCT:.0f}%)."
                 for c in facts["concentration"]]
        watch += [f"{a.symbol} ({a.account}): {a.rule_label} "
                  + (f"{a.value:+.1f}%" if a.is_pct else f"{a.value:+,.2f}")
                  + f", past the {a.threshold:g}{'%' if a.is_pct else ''} limit."
                  for a in facts["alerts"]]
        for w in watch or ["Nothing flagged: no position above the concentration limit and no alerts."]:
            para(f"- {w}")

    if facts.get("advisor_steps"):
        heading("Next steps from your advisor")
        for i, step in enumerate(facts["advisor_steps"], 1):
            para(f"{i}. {step}")

    heading("Suggested next steps (AI-written)" if facts.get("advisor_steps")
            else "Suggested next steps")
    if steps:
        for i, st in enumerate(steps, 1):
            para(f"{i}. {st}")
        para(AI_STEPS_NOTE)
    else:
        para("The AI-written suggestions weren't available when this plan was created.")

    return bytes(pdf.output())
