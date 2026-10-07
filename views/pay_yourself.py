# Part of dashboard.py, which runs this file with _view("pay_yourself") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Pay yourself (ROADMAP R11, pay_yourself.py), behind flag pay_yourself AND
# gate L3 (flags.FEATURES - this whole file is skipped while it's off): a Plan
# tab next to Money going out (views/plan.py adds it). A monthly "paycheck"
# picture from the person's own data: the payouts their holdings are estimated
# to pay each month (income.py) under a rule of thumb they pick from a fixed,
# named list - income only (the default), 3%, 4% or 5% of today's balance a
# year - with the thinnest month and a labelled hypothetical 20% fall.
#
# Who sees it:
# - the login's own account (USER_ID == LOGIN_ID, not an advisor's client):
#   the tab, and the picked rule's key kept in their own settings (prefs
#   pay_yourself.PREF - a key only, never an amount);
# - an advisor in a client's account (ON_CLIENT): the same picture on the
#   client's own data, as an advisor tool - the rule picked there lives in the
#   session only, is never saved to the client's settings and never reads the
#   client's own pick; with the standing line (standing_line.py): anything the
#   advisor shares from it is their advice, not Northwend's;
# - an advisor's client signed in themselves (IS_MANAGED_CLIENT): not shown -
#   their retirement income is their advisor's to talk through, and a rule of
#   thumb from Northwend beside the advisor's advice would second-guess it.
# Never sent to the AI.
# ruff: noqa: F821

import pay_yourself
import standing_line

PAY_TAB = "Pay yourself"
PAY_EXAMPLE = 100_000.0   # the example amount without real dollars to go on


def _pay_who():
    """'own', 'advisor' (an advisor in a client's account) or None (an
    advisor's client signed in themselves: not shown)."""
    if ON_CLIENT:
        return "advisor"
    if IS_MANAGED_CLIENT or USER_ID != LOGIN_ID:
        return None
    return "own"


def _pay_shown():
    return _pay_who() is not None


def _pay_key():
    """The radio's session key: per account, and a separate one for an
    advisor, so their pick never becomes the client's."""
    return f"pay_rule_{'adv_' if _pay_who() == 'advisor' else ''}{USER_ID}"


def _pay_picked():
    """Kept in the login's own settings (a known rule key only). An advisor
    in a client's account never writes there."""
    if _pay_who() != "own":
        return
    key = st.session_state.get(_pay_key())
    if key in pay_yourself.BY_KEY:
        _write_prefs(pay_yourself.with_rule(_read_prefs(), key))


def _pay_income_months():
    """The next 12 months of estimated payouts (pay_yourself.income_ahead):
    income.py's dividend schedule for the holdings now, plus cash interest
    from an imported activity history. Doesn't fetch anything."""
    import income
    today = datetime.now().date()
    qty, annual = _income_held(), {}
    for r in _income_yield_rows():
        annual[r["symbol"]] = annual.get(r["symbol"], 0.0) + r["est_income"]
    c = connect(DB)
    try:
        got = income.received(c, USER_ID, today)
        synced = income.has_history(c, qty)
        paid = income.payments(c, qty, today)
    finally:
        c.close()
    sched = income.schedule([{"symbol": s, "quantity": q, "annual": annual.get(s)}
                             for s, q in sorted(qty.items())], paid, synced, today)
    return pay_yourself.income_ahead(sched["months"], (got or {}).get("months"))


def _pay_standing():
    c = connect(DB)
    try:
        return standing_line.for_advisor(c, LOGIN_ID)
    finally:
        c.close()


def _pay_questions():
    with st.expander(pay_yourself.QUESTIONS_TITLE, icon=":material/help:"):
        st.markdown(pay_yourself.QUESTIONS_LEAD)
        st.markdown("\n".join(f"- {q}" for q in pay_yourself.QUESTIONS))


def _pay_example(key, lead):
    """Without real dollars: what the rule means for every PAY_EXAMPLE."""
    money = lambda v: f"${v:,.0f}"   # an example amount isn't anyone's own: not hidden
    st.caption(lead.format(example=money(PAY_EXAMPLE)).replace("$", r"\$"))
    r = pay_yourself.rule(key)
    if r["pct"] is None:
        st.markdown(pay_yourself.EXAMPLE_INCOME_ONLY)
        return
    pc = pay_yourself.paycheck(key, PAY_EXAMPLE, [])
    _md(pay_yourself.EXAMPLE_LINE.format(example=money(PAY_EXAMPLE),
                                         monthly=money(pc["monthly"]),
                                         yearly=money(pc["yearly"])))


def _pay_table(pc):
    cols = pay_yourself.TABLE_COLUMNS
    rows = []
    for m in pc["months"]:
        row = {cols[0]: pay_yourself.month_label(m["month"]), cols[1]: fmt_money0(m["income"])}
        if pc["pct"] is not None:
            row[cols[2]] = fmt_money0(m["from_balance"])
        row[cols[3]] = fmt_money0(m["total"])
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


@st.fragment
def _render_pay_yourself(value, today):
    """The Pay yourself tab (pay_yourself.py): the rule picker, the monthly
    paycheck under it, the thinnest month, the 20% hypothetical and the
    questions to ask a licensed professional. Every figure is under the
    rule picked; nothing here says what anyone ought to do."""
    who = _pay_who()
    if who is None:
        return
    py = pay_yourself
    st.markdown(f"#### {py.TITLE}")
    st.caption(py.INTRO)
    if who == "advisor":
        st.info(f"{py.ADVISOR_LEAD} {_pay_standing()}", icon=":material/badge:")

    skey = _pay_key()
    if skey not in st.session_state:
        st.session_state[skey] = (py.saved_rule(_read_prefs()) if who == "own" else py.DEFAULT)
    key = st.radio(py.PICK_LABEL, py.RULE_KEYS, key=skey, help=py.PICK_HELP,
                   format_func=lambda k: py.BY_KEY[k]["name"], on_change=_pay_picked)
    r = py.rule(key)
    st.caption(r["about"])

    pretend = SNAPSHOT_SOURCE == manual_entry.PCT_SOURCE if value else False
    if not value or value <= 0:
        _pay_example(key, py.NO_HOLDINGS)
    elif pretend:
        _pay_example(key, py.PRETEND)
        pc = py.paycheck(py.INCOME_ONLY, 0, _pay_income_months())
        if pc["thin"]:
            st.markdown(py.THIN_NAME_ONLY.format(thin=py.month_label(pc["thin"]["month"]),
                                                 full=py.month_label(pc["full"]["month"])))
    else:
        _pay_figures(key, value)

    st.caption(py.NOT_INCLUDED)
    _pay_questions()
    if who == "own":
        st.caption(py.KEPT_LINE)


def _pay_figures(key, value):
    """The paycheck on the person's own balance and payouts."""
    py = pay_yourself
    months = _pay_income_months()
    pc = py.paycheck(key, value, months)
    income_only = pc["pct"] is None
    if income_only and not pc["thin"]:
        st.markdown(py.NO_INCOME)
        return
    drop = py.after_drop(key, value, months)
    thin = pc["thin"]
    stats = [((py.STAT_PAYCHECK_INCOME if income_only else py.STAT_PAYCHECK),
              fmt_money0(pc["monthly"]),
              "estimated, unevenly" if income_only else f"{py.pct_text(pc['pct'])}% a year")]
    if thin:
        stats.append((py.STAT_THIN, py.month_label(thin["month"]),
                      f"about {fmt_money0(thin['total'])} paid out"))
    stats.append((py.STAT_DROP, fmt_money0(drop["after"]), "a month, hypothetical"))
    _summary_stats(stats)

    if income_only:
        _md(py.PAYCHECK_INCOME.format(yearly=fmt_money0(pc["yearly"]),
                                      monthly=fmt_money0(pc["monthly"])))
        _md(py.THIN_INCOME.format(thin=py.month_label(thin["month"]),
                                  thin_amount=fmt_money0(thin["total"]),
                                  full=py.month_label(pc["full"]["month"]),
                                  full_amount=fmt_money0(pc["full"]["total"])))
    else:
        _md(py.PAYCHECK_PCT.format(name_short=py.short_name(key),
                                   monthly=fmt_money0(pc["monthly"]),
                                   yearly=fmt_money0(pc["yearly"]),
                                   pct=py.pct_text(pc["pct"]), balance=fmt_money0(value)))
        if pc["covered"]:
            st.markdown(py.COVERED_PCT)
        elif thin:
            row = next(m for m in pc["months"] if m["month"] == thin["month"])
            _md(py.THIN_PCT.format(thin=py.month_label(thin["month"]),
                                   thin_amount=fmt_money0(thin["total"]),
                                   from_balance=fmt_money0(row["from_balance"])))
    _pay_table(pc)
    st.caption(py.PAYOUT_NOTE)

    with st.container(border=True):
        st.markdown(f"**{py.DROP_LABEL}**")
        if income_only:
            _md(py.DROP_INCOME_LINE.format(monthly=fmt_money0(drop["after"])))
        else:
            _md(py.DROP_PCT_LINE.format(after=fmt_money0(drop["after"]),
                                        before=fmt_money0(drop["before"]),
                                        pct=py.pct_text(pc["pct"]),
                                        kept_pct=py.pct_text(drop["kept_pct"] or 0)))
        st.caption(py.DROP_NOTE)
