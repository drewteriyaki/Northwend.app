# Part of dashboard.py, which runs this file with _view("own_numbers") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Learn the basics with your own numbers (flag learn_own_numbers, own_numbers.py):
# under a basics topic's read in its window (views/get_started.py), one short
# box "In your own portfolio" - a fact from their holdings, description only.
# The person's own account only: never while an advisor is in a client's
# account (an advisor's client signed in as themselves sees their own, like
# Home's plain-words line). Nothing saved, nothing sent to the AI.
# Uses positions / cash_by_account / CLASS_SPLITS / sec_info, which exist by the
# time Learn is drawn with holdings (gs_has_holdings).
# ruff: noqa: F821

import own_numbers

OWN_OPEN_FEES = "own_open_fees"   # Fee check asked for from the box (opened by render_fee_step)


def _own_lines(topic):
    """own_numbers.lines() for `topic` from what Learn already has loaded."""
    alloc = allocate(positions, cash_by_account, CLASS_SPLITS, sec_info)
    fee_result = money = year = None
    if topic == "fees":
        fee_result = _fee_check()
        # the dollars only as Fee check shows them on its own (not hidden, not
        # a percentages-only portfolio, whose dollars are pretend)
        if (fee_result["funds"] and not _hidden()
                and SNAPSHOT_SOURCE != manual_entry.PCT_SOURCE):
            money = fmt_money0(fee_result["total_yearly"])
    if topic == "ups":
        stand_ins = (learn.PRACTICE_TICKERS["us"], learn.PRACTICE_TICKERS["bonds"])
        prices = perf.full_adjusted_closes(DB, stand_ins)
        bonds = next((r["pct"] or 0.0 for r in alloc["by_asset_class"] if r["label"] == "Bonds"),
                     0.0)
        # (the whole percent the words show, so the sum and the words agree)
        year = own_numbers.mix_year(prices[stand_ins[0]], prices[stand_ins[1]], round(bonds))
    return own_numbers.lines(topic, alloc=alloc, positions=positions, info=sec_info,
                             fee_result=fee_result, fee_money=money, year=year)


def render_own_numbers(topic):
    """The box under one basics topic's read, or nothing for a topic without
    one (own_numbers.SKIPPED) or an advisor in a client's account."""
    if topic not in own_numbers.TOPICS or USER_ID != LOGIN_ID:
        return
    has = bool(st.session_state.get("gs_has_holdings"))
    with st.container(border=True, key=f"pt_own_{topic}"):
        example = has and SNAPSHOT_SOURCE == SAMPLE_SOURCE
        st.markdown(f"**:material/person: "
                    f"{own_numbers.TITLE_EXAMPLE if example else own_numbers.TITLE}**")
        if not has:
            ways = CAN_IMPORT or not CLIENT_MODE
            st.markdown(own_numbers.NO_HOLDINGS if ways else own_numbers.NO_HOLDINGS_MANAGED)
            # (in a window a click reruns only the window: the callback does
            # the work, then a full rerun closes it and opens the next one)
            with st.container(horizontal=True):
                if CAN_IMPORT and st.button(":material/content_paste: Add your holdings",
                                            key=f"own_add_{topic}", type="tertiary",
                                            on_click=_open_holdings_dialog, args=("manual",)):
                    st.rerun()
                if not CLIENT_MODE and st.button(":material/science: Try the example portfolio",
                                                 key=f"own_sample_{topic}", type="tertiary",
                                                 on_click=_load_sample):
                    st.rerun()
            return
        got = _own_lines(topic)
        if not got:
            st.caption("Nothing to show here yet with your holdings.")
            return
        _md(" ".join(got))
        if topic == "fees" and fees.has_funds(_fee_check()):
            if st.button("Fee check", key="own_fees_open", type="tertiary",
                         icon=":material/open_in_new:", on_click=_own_open_fees):
                st.rerun()


def _own_open_fees():
    st.session_state[OWN_OPEN_FEES] = True   # Fee check opens on the full rerun (render_fee_step)
