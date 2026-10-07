"""Downloadable client plan: a PDF of one account's profile, goal, holdings,
and "Questions to look into".

Pure logic, no Streamlit; the AI Assistant page owns the button
(views/profile.py). No AI: nothing in the plan leaves the machine. The
questions (questions()) come from fixed rules over the person's own answers
and figures - drift beyond their own band, a fund's fee above a level, the
cash share, the goal's projection, open profile answers, the emergency fund
- and are always questions, never instructions (docs/AI_PLAN.md section 9,
item 12, and step 15; the plan's old AI "Suggested next steps" was the
closest thing to a personal conclusion, LEGAL_GATES.md G4). The answers
about getting ready come through learn.readiness (the same check Learn
shows), and the plan ends with a fixed bank of questions people often ask a
licensed professional (PRO_QUESTIONS), the same for everyone.
"""

from __future__ import annotations

import re
from datetime import date

from fpdf import FPDF

import advising
import advisor
import asset_classes
import fees
import learn
import plans
import alerts
import metrics as M
import overview
from allocation import CONCENTRATION_PCT, SHORT_ASSET_TYPE, allocate

DISCLAIMER = ("Educational information only - not financial advice. Northwend doesn't tell "
              "anyone what to buy, sell or hold; do your own research before making any "
              "investment decision.")

QUESTIONS_TITLE = "Questions to look into"
# printed under the questions
QUESTIONS_NOTE = ("Worked out from your own answers and figures by fixed rules - anyone with "
                  "the same numbers gets the same questions. They are questions to think "
                  "about, or to take to a licensed professional of your choosing - not "
                  "recommendations. Any figure about the future is hypothetical.")
FEE_LINE = 0.005       # a fund's yearly fee from which it gets a question (0.50%)
CASH_LINE = 20.0       # % of the portfolio in cash from which it gets a question
MAX_QUESTIONS = 10
# asked of everyone, after the ones from their own figures
GENERAL_QUESTIONS = (
    "How much of a drop - 20%, 30%, more - could I sit through without changing my plan?",
    "Which of these would I like to understand better before changing anything?",
)
# A fixed bank, the same for everyone and printed in its own section
# (AI_PLAN section 9, row 12): what people commonly ask a licensed
# professional - if they ever choose to work with one. Never a suggestion
# that they need one, and never which kind (ai_policy rule no_advisor_picks).
PRO_TITLE = "Questions people often ask a licensed professional"
PRO_TITLE_CLIENT = "Questions people often ask their advisor"
PRO_NOTE = ("The same list for everyone - for anyone who ever chooses to work with a "
            "professional.")
PRO_QUESTIONS = (
    "How are you paid: a flat fee, a share of what you manage, commissions, or a mix?",
    "Are you a fiduciary - required to put my interests first - for all of the advice you "
    "give me, all of the time?",
    "What licences or registrations do you hold, and where can I look them up (FINRA "
    "BrokerCheck, the SEC's adviser search)?",
    "What would you want to know about my situation before giving any advice?",
    "What do all the costs come to in a year, in dollars - your fee and the funds' own fees?",
    "How often would we look at my plan again, and what would make you change it?",
)


# --------------------------------------------------------------------------- #
# facts (computed locally, dollars included)
# --------------------------------------------------------------------------- #
def build_facts(conn, user_id: int, contexts: list[dict], cash_by_account: dict,
                rules=None, *, band: float | None = None, info: dict | None = None) -> dict:
    """Everything the PDF shows. `contexts` is dashboard.py's per-position
    metric context list; `band` the account's drift band in points (its
    setting, else 5); `info` the holdings' security_info rows (for fees)."""
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
    # each fund's yearly fee, where it's known (fees.py) - for the questions
    fee_rows = fees.check([{"symbol": c["pos"].get("symbol"),
                            "name": c["pos"].get("description"),
                            "asset_type": c["pos"].get("asset_type"), "value": M.eff_mv(c)}
                           for c in contexts], info or {})["funds"] if info else []

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
        "band": float(band) if band else 5.0,
        "fees": [{"symbol": f["symbol"], "ratio": f["ratio"]} for f in fee_rows],
    }


# --------------------------------------------------------------------------- #
# Questions to look into - fixed rules, no AI
# --------------------------------------------------------------------------- #
def _pct_of(rows, label) -> float:
    return next((float(r["pct"] or 0.0) for r in rows or [] if r["label"] == label), 0.0)


def questions(facts: dict) -> list[str]:
    """The plan's "Questions to look into": from the person's own answers and
    figures, by fixed rules (the same numbers always give the same
    questions), then GENERAL_QUESTIONS. Each one is a question - something to
    think about or ask - never an instruction. At most MAX_QUESTIONS."""
    out = []
    p = facts.get("profile") or {}
    missing = facts.get("missing") or []
    has_data = bool((facts.get("summary") or {}).get("has_data"))
    by_class = facts.get("by_asset_class") or []

    # open answers about them
    if missing:
        names = ", ".join(advisor.PROFILE_FIELDS[f].lower() for f in missing[:3])
        out.append(f"Some questions about you are still open ({names}"
                   + (" and more" if len(missing) > 3 else "") + "). What are your answers?")
    # the readiness check (learn.readiness, the same one Learn shows): a
    # question for each item that isn't in place yet. Unanswered items are
    # the open answers above.
    ready = {i["key"]: i["state"] for i in learn.readiness(p)}

    def not_in_place(key):
        return ready.get(key) in (learn.CAUTION, learn.STOP)

    if not_in_place("emergency_fund"):
        out.append(f"You answered \"{p.get('emergency_fund')}\" for emergency savings. How much "
                   "would you want set aside for surprises, and where would it sit?")
    if not_in_place("high_interest_debt"):
        out.append("How does the interest on your high-interest debt compare with what "
                   "investing has earned in the past?")
    if not_in_place("employer_match"):
        out.append("Does your employer match what you put into a retirement plan, and how?"
                   if p.get("employer_match") == "Not sure" else
                   "What would it take to get all of your employer's match, and what are its "
                   "vesting rules?")
    if not_in_place("income_stability"):
        out.append("Your income varies a lot. How many months of expenses would you want set "
                   "aside for the leaner months?")

    # the target mix: their own rule
    plan = facts.get("plan") or {}
    target = {k: float(v) for k, v in (plan.get("target_alloc") or {}).items() if v}
    band = float(facts.get("band") or 5.0)
    if not target:
        out.append("What split between stocks, bonds and cash would you choose for this goal, "
                   "and why?")
    elif has_data:
        drifted = sorted(((k, _pct_of(by_class, k) - t, t) for k, t in target.items()
                          if abs(_pct_of(by_class, k) - t) > band),
                         key=lambda r: -abs(r[1]))
        for label, off, t in drifted[:2]:
            out.append(f"{label}: {abs(off):.0f} points {'above' if off > 0 else 'below'} "
                       f"the {t:g}% target you set, outside your {band:g}-point band. "
                       "Your mix has moved from your target - what would you like to do "
                       "about that, and is the target still the one you want?")

    if has_data:
        cash = _pct_of(by_class, "Cash")
        if cash >= CASH_LINE:
            out.append(f"{cash:.0f}% of the portfolio is cash. What is that cash for, and "
                       "where does it sit - a sweep account or a money market fund?")
        for f in sorted(facts.get("fees") or [], key=lambda f: -f["ratio"]):
            if f["ratio"] >= FEE_LINE:
                out.append(f"{f['symbol']} charges {fees.fmt_ratio(f['ratio'])} a year. What "
                           "do you get for that fee, and what do similar funds charge?")
                break
        for c in (facts.get("concentration") or [])[:1]:
            out.append(f"{c['symbol']} is {c['pct']:.0f}% of the portfolio. How much of your "
                       "money do you want riding on one holding?")
        stocks = _pct_of(by_class, "Stocks")
        if p.get("withdrawal_needs") == "A large amount" and stocks > 50:
            out.append("You expect to take out a large amount within about 3 years. How much "
                       "of that money would you want kept out of the stock market's ups and "
                       "downs?")

    # the goal, by the plan's own arithmetic (hypothetical)
    g = facts.get("goal")
    if not g:
        out.append("What are you investing for, and by when?")
    elif g["status"] == "past_date":
        out.append("Your goal's date has passed. What's the next goal, or a new date?")
    elif g["status"] in ("behind", "starting"):
        out.append("At the plan's assumed return, the projection doesn't reach your goal by "
                   "its date (hypothetical). Which, if any, would you change: the monthly "
                   "amount, the date or the target?")
    elif g["status"] in ("on_track", "within_reach"):
        out.append("At the plan's assumed return, the projection reaches your goal by its date "
                   "(hypothetical). What would change if returns were lower than assumed?")

    out = out[:MAX_QUESTIONS - len(GENERAL_QUESTIONS)]
    return out + list(GENERAL_QUESTIONS)


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


def render_pdf(facts: dict, asks: list[str] | None = None, *, account_name: str,
               advisor_name: str | None = None, today: date | None = None) -> bytes:
    """The plan as PDF bytes. `asks`: the Questions to look into (None:
    questions(facts))."""
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

    heading(QUESTIONS_TITLE)
    for i, ask in enumerate(questions(facts) if asks is None else asks, 1):
        para(f"{i}. {ask}")
    pdf.set_text_color(90)
    para(QUESTIONS_NOTE)
    pdf.set_text_color(0)

    heading(PRO_TITLE_CLIENT if advisor_name else PRO_TITLE)
    for ask in PRO_QUESTIONS:
        para(f"- {ask}")
    pdf.set_text_color(90)
    para(PRO_NOTE)
    pdf.set_text_color(0)

    return bytes(pdf.output())
