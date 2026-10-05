# Part of dashboard.py, which runs this file with _view("cash_check") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Cash check (cash_check.py): how much sits in cash and a plain word on what
# cash can earn - the brokerage's default cash ("sweep") vs money market
# funds, no fund or brokerage named and no rate promised. Shown only when
# cash is a meaningful share.
#
# And Home's one "Your money, checked" card: Fee check (views/fees.py), Fund
# overlap (views/fund_overlap.py) and Cash check, one line each with its
# window on a tap - three separate cards under the route made Home busy.
# Uses positions / contexts / sec_info / cash_by_account / portfolio_value,
# which exist by the time Home is drawn.
# ruff: noqa: F821

import cash_check
import fees

CASH_ASK = ("What's the difference between a brokerage's default cash (a sweep account) and a "
            "money market fund, and what do people usually check about what their cash earns? "
            "Use examples, not recommendations.")


def _cash_summary():
    """cash_check.summary() for this account: plain cash in the accounts and
    money market funds held, at today's values."""
    mm = sum(M.eff_mv(ctx) or 0.0 for p, ctx in zip(positions, contexts)
             if fees.holding_type((sec_info.get(p["symbol"]) or {}).get("quote_type"),
                                  p.get("asset_type")) == "cash")
    return cash_check.summary(sum(cash_by_account.values()), mm, portfolio_value,
                              pretend=SNAPSHOT_SOURCE == manual_entry.PCT_SOURCE)


def _cash_ask():
    st.session_state["coach_prompt"] = CASH_ASK
    st.session_state["page"] = "AI Assistant"


def _cash_interest_last_year():
    """Interest paid on cash in the last 12 months, from an imported activity
    history (income.received), or None without one."""
    c = connect(DB)
    try:
        got = income.received(c, USER_ID, datetime.now().date())
    finally:
        c.close()
    return None if got is None else got.get("cash_interest")


@st.dialog("Cash check", width="large", on_dismiss=_dialog_closed)
def _cash_window():
    s = _cash_summary()
    pretend = SNAPSHOT_SOURCE == manual_entry.PCT_SOURCE
    share = mask_or(f"{s['pct']:.0f}%") if s["pct"] is not None else "—"
    if pretend:   # pretend dollars: the share is what's real
        _summary_stats([("Cash", share, "of your portfolio")])
    else:
        _summary_stats([("Cash in your accounts", fmt_money0(s["sweep"]), None),
                        ("Money market funds", fmt_money0(s["money_market"]), None),
                        ("Share of your portfolio", share, None)])
    st.markdown("**Two common places cash sits**")
    _md("- **Your brokerage's default cash**, often called a *sweep*: money from deposits, "
        "sales and dividends lands here until it's invested. What it pays depends on the "
        "brokerage and the account - some pay very little.\n"
        "- **Money market funds**: funds that hold very short-term, high-quality debt. They're "
        "bought like other funds, and their yield usually follows short-term interest rates - "
        "it changes, and it isn't guaranteed.")
    if not pretend:
        lines = [f"Each 1% a year of interest on your {fmt_money0(s['cash'])} of cash is about "
                 f"**{fmt_money0(s['per_point'])} a year** - so the rate it earns matters."]
        got = _cash_interest_last_year()
        if got is not None:
            lines.append(f"Your imported activity shows {fmt_money0(got)} of interest on cash in "
                         "the last 12 months.")
        _md("  \n".join(lines))
    _md("**Worth checking:** what your cash earns at your brokerage. The account's cash (or "
        "sweep) page shows its rate, and a money market fund's page shows its yield. Cash you'll "
        "need soon, or keep for emergencies, is still best kept safe and easy to reach - this is "
        "only about what it earns while it waits.")
    st.caption("No fund or brokerage is suggested here and no rate is promised - rates change, "
               "and what's available depends on your brokerage and account.")
    learn_more("emergency_fund")
    # (in a window: switch pages with a full rerun, which also closes it)
    if st.button(f":material/forum: Ask {GUIDE} about cash", key="cash_ask", type="tertiary"):
        _cash_ask()
        _dialog_closed()
        st.rerun()


def open_cash_window():
    st.session_state["dialog_open"] = True   # live prices wait (_dialog_closed)
    _cash_window()


def cash_card_line():
    """Cash check's one line on Home (HTML), or None when cash isn't a
    meaningful share (cash_check.SHARE_PCT / DOLLARS)."""
    s = _cash_summary()
    if not s["show"]:
        return None
    share = html.escape(mask_or(f"{s['pct']:.0f}%"))
    if SNAPSHOT_SOURCE == manual_entry.PCT_SOURCE:
        lead = f"About <span style='font-weight:600'>{share}</span> of your portfolio is cash."
    else:
        lead = (f"About <span style='font-weight:600'>{html.escape(fmt_money0(s['cash']))}"
                f"</span> ({share} of your portfolio) is in cash.")
    return lead + " Worth a look at what it earns."


def render_money_checks():
    """Home's "Your money, checked" card: one line each for Fee check, Fund
    overlap and Cash check, whichever apply, each opening its window.
    Nothing when none apply."""
    rows = [(label, line, button, key, opener)
            for label, line, button, key, opener in (
                ("Fee check", fee_card_line(), "Check fees", "fees_open", open_fee_window),
                ("Fund overlap", overlap_card_line(), "See overlap", "overlap_open",
                 open_overlap_window),
                ("Cash check", cash_card_line(), "Check cash", "cash_open", open_cash_window))
            if line]
    if not rows:
        return
    with st.container(border=True, key="pt_checks", gap="small"):
        st.html("<div class='pt-checks-title'>Your money, checked</div>")
        for label, line, button, key, opener in rows:
            with st.container(horizontal=True, vertical_alignment="center",
                              key=f"pt_check_{key}"):
                st.html(f"<div class='pt-route-label'>{label}</div>"
                        f"<div class='pt-region'>{line}</div>", width="stretch")
                if st.button(button, key=key, type="tertiary"):
                    opener()
