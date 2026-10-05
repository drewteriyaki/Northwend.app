# Part of dashboard.py, which runs this file with _view("advisor_demo") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# "See what you'll get" (ROADMAP 7): while someone's advisor access is being
# checked, a read-only preview of the advisor side - Your clients with three
# made-up clients, a shared proposal, a progress report and meeting prep.
# All of it from advisor_demo.py, in memory: nothing here reads or writes the
# database, sends an email or asks the AI.
# ruff: noqa: F821

import advisor_demo

_EX = "<span class='pt-chip pt-role'>Example</span>"


def _demo_card(r):
    gain = r["gain_pct"]
    chips = "".join(f"<span class='pt-chip pt-warn'>{html.escape(x)}</span> "
                    for x in r["reasons"]) or "<span class='pt-chip pt-up'>All good</span>"
    bits = []
    g = r["goal"]
    if g:
        bits.append(f"{html.escape(g['name'])}: {mask_or(format(g['pct'], '.0f') + '%')} of "
                    f"{fmt_money0(g['target'])}, {PLAN_STATUS[g['status']][0].lower()}")
    bits.append("never reviewed" if r["review"] == "never" else f"reviewed {r['review_days']}d ago")
    if r["n_steps"]:
        bits.append(f"{r['n_steps']} open next step{'s' if r['n_steps'] != 1 else ''}")
    if r["proposal"] == "shared":
        bits.append("proposal waiting for their answer")
    if r["last_report"]:
        bits.append(f"last report {r['last_report']}")
    bits.append("login not set up yet" if r["login_days"] is None
                else f"signed in {r['login_days']}d ago")
    with st.container(border=True):
        st.html("<div class='pt-goal-top'>"
                f"<b>{html.escape(r['name'])}</b> {_EX}"
                f"<span>{fmt_money0(r['value'])}</span>{_tone(gain, fmt_pct(gain))}</div>"
                f"<div style='margin:.45rem 0'>{chips}</div>"
                f"<div class='pt-goal-sub'>{' · '.join(bits)}</div>")


def _demo_proposal():
    p = advisor_demo.PROPOSAL
    cmp = advisor_demo.proposal_compare()
    st.html(f"<b>{html.escape(p['title'])}</b>&nbsp; <span class='pt-chip pt-warn'>Shared - "
            f"waiting for their answer</span> {_EX}"
            f"<div class='pt-goal-sub'>For {html.escape(p['client'])}</div>")
    _md(f"**Your note:** {p['note']}")
    st.dataframe(pd.DataFrame([{
        "Asset class": cls, "Today": f"{now:.0f}%", "Proposed": f"{new:.0f}%",
        "Change": f"{change:+.0f} pts"} for cls, now, new, change in cmp["rows"]]),
        hide_index=True, width="stretch")
    t_ret, p_ret = cmp["assumed_return"]
    lines = [f"**Assumed long-run return:** {t_ret:.1f}% today, {p_ret:.1f}% proposed"]
    for year, (now, new) in cmp["hard_years"].items():
        lines.append(f"**In a year like {year}:** about {now:+.0f}% today, {new:+.0f}% proposed")
    if cmp.get("projected"):
        now, new = cmp["projected"]
        lines.append(f"**At their goal date:** about {fmt_money0(now)} today, "
                     f"{fmt_money0(new)} proposed")
    _md("  \n".join(lines))
    st.caption(proposals.ASSUMPTIONS_NOTE)
    st.caption("The client reads it on their Your advisor page and answers \"Let's go ahead\" "
               "or \"Not right now\" - you're told by email. Nothing is bought or sold.")


def _demo_report():
    rep = advisor_demo.REPORT
    st.html(f"<b>Progress report - {html.escape(rep['period'])}</b> {_EX}"
            f"<div class='pt-goal-sub'>For {html.escape(rep['client'])}</div>")
    _md("  \n".join(reports.summary_lines(rep["facts"], fmt_money0)))
    _md("**What's next:**  \n" + "  \n".join(f"- {s}" for s in rep["facts"]["next_steps"]))
    _md(f"**Your message:** {rep['message']}")
    st.caption("Sent from Your clients in one step for everyone, or from a client's page. The "
               "client gets a short email that it's there - the figures stay in Northwend. "
               "Each report has a PDF.")


def _demo_meeting():
    m = advisor_demo.MEETING
    st.html(f"<b>Meeting prep - {html.escape(m['client'])}</b> {_EX}")
    _md("  \n".join(m["facts"]))
    st.markdown("**Talking points** (a sample)")
    _md("\n".join(f"- {t}" for t in m["talking_points"]))
    st.caption(f"With your own clients, {GUIDE} drafts these on request from percentages and "
               "the facts above - never dollar amounts or your notes - and you edit them and "
               "keep them as a private note.")


def _render_advisor_demo():
    """The whole preview, read-only."""
    st.info(":material/hourglass_top: **This is an example.** The clients below are made up "
            "and nothing here is saved. Once your advisor access is approved - usually within "
            "two working days - **Your clients** opens with your own clients instead.")
    rows = advisor_demo.book(datetime.now().date())
    st.html(_stat_row(
        "<div class='pt-stats' role='list' aria-label='Example client summary'>"
        f"<div class='pt-stat' role='listitem'><div class='pt-stat-label'>Clients</div>"
        f"<div class='pt-stat-value'>{len(rows)}</div><div class='pt-stat-sub'>examples</div></div>"
        f"<div class='pt-stat' role='listitem'><div class='pt-stat-label'>Total value</div>"
        f"<div class='pt-stat-value'>{fmt_money0(sum(r['value'] for r in rows))}</div></div>"
        f"<div class='pt-stat' role='listitem'><div class='pt-stat-label'>Need attention</div>"
        f"<div class='pt-stat-value'>{sum(1 for r in rows if r['reasons'])}</div>"
        f"<div class='pt-stat-sub'>{sum(1 for r in rows if r['review'] != 'ok')} review(s) due"
        "</div></div></div>"))
    st.subheader("Your clients")
    st.caption("Sorted by what needs a look: reviews due, goals behind, drift from the target "
               "mix, a proposal they accepted.")
    cols = st.columns(len(rows))
    for col, r in zip(cols, rows):
        with col:
            _demo_card(r)
    proposal, report, prep = st.tabs(["A shared proposal", "A progress report", "Meeting prep"])
    with proposal:
        _demo_proposal()
    with report:
        _demo_report()
    with prep:
        _demo_meeting()
    st.subheader("Also waiting for you")
    _md("- **Add clients** one at a time or from a CSV file, each with a setup link - they "
        "choose their own password and answer a few questions about their goals.\n"
        "- **Notes and next steps** for each client, private or shared, and a **Message "
        "clients** note to everyone at once.\n"
        "- **Model portfolios** to apply to any client's plan, and a **Monday email** with "
        "the week's reviews.\n"
        "- **Client records** to export for your firm's files.")
