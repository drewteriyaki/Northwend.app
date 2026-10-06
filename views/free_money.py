# Part of dashboard.py, which runs this file with _view("free_money") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Free money check (employer_match.py): an employer 401(k) match calculator in
# a window - pay, what you put in, the match formula -> the match you get vs
# could get. Opened from Learn's "Are you ready to invest?" step (where the
# employer match question is) and from the Plan page's Contributions tab.
# The numbers are kept only if the person ticks "Remember these numbers"
# (user_prefs, employer_match.PREF).
# ruff: noqa: F821

import employer_match

MATCH_ASK = ("How does an employer 401(k) match work, what is vesting, and what do people "
             "usually check in their plan's rules? Use examples, not recommendations.")
_FM_KEYS = ("fm_salary", "fm_contrib", "fm_preset", "fm_rate", "fm_upto")


def _fm_saved():
    return employer_match.clean_saved(_read_prefs().get(employer_match.PREF))


def _fm_defaults():
    """Fill the window's fields from what was remembered, once a session."""
    if st.session_state.get("fm_loaded"):
        return
    st.session_state["fm_loaded"] = True
    saved = _fm_saved()
    st.session_state["fm_remember"] = bool(saved)
    st.session_state["fm_salary"] = saved.get("salary", 0.0)
    st.session_state["fm_contrib"] = saved.get("contrib_pct", 0.0)
    st.session_state["fm_preset"] = saved.get("preset", employer_match.PRESETS[0][0])
    st.session_state["fm_rate"] = saved.get("rate", 50.0)
    st.session_state["fm_upto"] = saved.get("up_to", 6.0)


def _fm_remember_change():
    """Remember the numbers in this account's settings - or forget them."""
    p = _read_prefs()
    if st.session_state.get("fm_remember") and CAN_MANAGE:
        p[employer_match.PREF] = {
            "salary": float(st.session_state.get("fm_salary") or 0.0),
            "contrib_pct": float(st.session_state.get("fm_contrib") or 0.0),
            "preset": st.session_state.get("fm_preset"),
            "rate": float(st.session_state.get("fm_rate") or 0.0),
            "up_to": float(st.session_state.get("fm_upto") or 0.0)}
    elif employer_match.PREF in p:
        p.pop(employer_match.PREF)
    else:
        return
    _write_prefs(p)


def _fm_ask():
    st.session_state["coach_prompt"] = MATCH_ASK
    st.session_state["page"] = "AI Assistant"


def _pay_pct(v):
    return f"{v:.1f}".rstrip("0").rstrip(".") + "% of pay"


@st.dialog("Free money check", width="medium", on_dismiss=_dialog_closed)
def _free_money_window():
    _fm_defaults()
    st.caption("Many employers add money to your 401(k) when you put some in - a match. "
               "Here's what yours could be worth, and whether you're getting all of it.")
    hidden = _hidden()
    remembered = CAN_MANAGE and st.session_state.get("fm_remember")
    c1, c2 = st.columns(2)
    if hidden:
        salary = None
        c1.caption("Amounts are hidden, so this works in shares of your pay. Show amounts "
                   "(the eye beside a page title) to see dollars.")
    else:
        salary = c1.number_input("Your yearly pay before tax ($)", min_value=0.0,
                                 max_value=10_000_000.0, step=1000.0, format="%.0f",
                                 key="fm_salary",
                                 on_change=_fm_remember_change if remembered else None)
    contrib = c2.number_input("What you put in (% of pay)", min_value=0.0, max_value=100.0,
                              step=1.0, format="%g", key="fm_contrib",
                              on_change=_fm_remember_change if remembered else None)
    options = [label for label, _ in employer_match.PRESETS] + [employer_match.CUSTOM]
    preset = st.selectbox("How your employer matches", options, key="fm_preset",
                          help="Your plan's summary or benefits site says how - usually as a "
                               "share of what you put in, up to a share of your pay.",
                          on_change=_fm_remember_change if remembered else None)
    rate = up_to = None
    if preset == employer_match.CUSTOM:
        c3, c4 = st.columns(2)
        rate = c3.number_input("They add (% of what you put in)", min_value=0.0,
                               max_value=200.0, step=5.0, format="%g", key="fm_rate",
                               on_change=_fm_remember_change if remembered else None)
        up_to = c4.number_input("on up to (% of your pay)", min_value=0.0, max_value=100.0,
                                step=1.0, format="%g", key="fm_upto",
                                on_change=_fm_remember_change if remembered else None)
    tiers = employer_match.tiers_for(preset, rate, up_to)
    r = employer_match.check(salary, contrib, tiers)

    if not r["has_match"]:
        st.caption("Enter how your employer matches to see what it's worth.")
    else:
        def money(v, pct):
            return fmt_money0(v) if v is not None else _pay_pct(pct)

        def sub(v, pct):
            return _pay_pct(pct) if v is not None else None
        _summary_stats([
            ("You put in", money(r["you_yearly"], r["you_pct"]),
             sub(r["you_yearly"], r["you_pct"])),
            ("Your employer adds", money(r["match_yearly"], r["match_pct"]),
             sub(r["match_yearly"], r["match_pct"])),
            ("The most they'd add", money(r["max_yearly"], r["max_pct"]),
             f"if you put in {r['full_at']:g}%")])
        if r["getting_all"]:
            _md(f":material/check_circle: You're getting the whole match - "
                f"{employer_match.describe(tiers)} of your pay.")
        else:
            gap = (f"about **{fmt_money0(r['missing_yearly'])} a year**"
                   if r["missing_yearly"] is not None else
                   f"about **{_pay_pct(r['missing_pct'])}** a year")
            _md(f":material/redeem: You may be leaving {gap} of free money on the table. "
                f"Putting in {r['full_at']:g}% of your pay (instead of {r['you_pct']:g}%) would "
                "get the whole match.")
        st.caption("Before tax and investment growth, a year at a time. Matched money can come "
                   "with a waiting period, called vesting, before it's all yours if you leave "
                   "the job - and some plans match each paycheck, or cap what counts. Check "
                   "your plan's rules (its summary plan description). There's also a yearly "
                   "IRS limit on what you can put in - IRS.gov has this year's.")
    if CAN_MANAGE:
        st.checkbox("Remember these numbers", key="fm_remember", on_change=_fm_remember_change,
                    help="Kept with your account's settings so this opens with them next "
                         "time. Untick to forget them.")
    learn_more("account_types")
    # (in a window: switch pages with a full rerun, which also closes it)
    if st.button(f":material/forum: Ask {GUIDE} about matches", key="fm_ask", type="tertiary"):
        _fm_ask()
        _dialog_closed()
        st.rerun()


def open_free_money_window():
    st.session_state["dialog_open"] = True   # live prices wait (_dialog_closed)
    _free_money_window()


def render_free_money_card(where):
    """The one-line card that opens the window: `where` is "learn" or "plan"
    (the button's key). With flag decoder_401k on, the 401(k) Menu Decoder's
    card follows it."""
    with st.container(border=True, horizontal=True, vertical_alignment="center",
                      key=f"pt_free_money_{where}"):
        st.markdown(":material/redeem: **Free money check** - what your employer's 401(k) "
                    "match is worth, and whether you're getting all of it.", width="stretch")
        if st.button("Work it out", key=f"fm_open_{where}", type="tertiary",
                     icon=":material/open_in_new:"):
            open_free_money_window()
    if flags.on("decoder_401k"):
        render_decoder_card(where)   # the 401(k) Menu Decoder (views/menu_decoder.py)
