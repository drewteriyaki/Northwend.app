# Part of dashboard.py, which runs this file with _view("fees") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Fee check (ROADMAP G10, fees.py): each fund's yearly fee in dollars, the
# total, and what it adds up to over the years - in a window opened from a
# small card on Home and from Learn the basics on Get started. What low-cost
# funds of the same kind charge is shown for learning, never as "switch".
# Uses positions / contexts / sec_info, which exist by the time Home or Get
# started (with holdings) is drawn.
# ruff: noqa: F821

import fees

FEE_ASK = ("What is an expense ratio, how do fund fees add up over the years, and what do "
           "people usually look at when they compare funds? Use examples, not recommendations.")


def _fee_check():
    """fees.check() for this account's holdings at today's values."""
    return fees.check([{"symbol": p["symbol"], "name": p.get("description"),
                        "asset_type": p.get("asset_type"), "value": M.eff_mv(ctx)}
                       for p, ctx in zip(positions, contexts)], sec_info)


def _fee_ask():
    st.session_state["coach_prompt"] = FEE_ASK
    st.session_state["page"] = "AI Assistant"


def _fee_names(symbols):
    return ", ".join(symbols[:-1]) + (" and " if len(symbols) > 1 else "") + symbols[-1]


@st.dialog("Fee check", width="large", on_dismiss=_dialog_closed)
def _fee_window():
    r = _fee_check()
    growth = f"{r['growth'] * 100:.0f}%"
    st.caption("Every fund takes a small yearly fee, called its expense ratio, out of what you "
               "hold. There's no bill, so it's easy to miss - here it is in dollars, at "
               "today's values.")
    if r["funds"]:
        cols = st.columns(1 + len(r["horizons"]))
        cols[0].metric("Each year, at today's value", fmt_money0(r["total_yearly"]),
                       help=f"About {fees.fmt_ratio(r['ratio'])} of what these funds are worth.")
        for col, years in zip(cols[1:], r["horizons"]):
            col.metric(f"Over {years} years", fmt_money0(r["over"][years]["total"]),
                       help=f"If it grew {growth} a year with nothing added: the fees, plus the "
                            "growth those dollars would have earned.")
        far = r["over"][r["horizons"][-1]]
        _md(f"If these funds grew {growth} a year with nothing added, over "
            f"{r['horizons'][-1]} years the fees would come to about "
            f"**{fmt_money0(far['paid'])}**, and the growth that money would have earned "
            f"about **{fmt_money0(far['lost_growth'])}** more.")
        st.dataframe(pd.DataFrame([{
            "Fund": f"{f['symbol']} - {f['name']}" if f["name"] != f["symbol"] else f["symbol"],
            "Value": fmt_money0(f["value"]),
            "Yearly fee": fees.fmt_ratio(f["ratio"]),
            "Per year": fmt_money0(f["yearly"]),
            "Low-cost index funds of this kind often charge": (
                f"around {fees.fmt_ratio(f['typical'])} · {f['kind_label']}"
                if f["typical"] is not None else "No simple comparison"),
        } for f in r["funds"]]), width="stretch", hide_index=True)
        st.caption("The last column is a rough figure for learning what's typical for each kind "
                   "of fund - not a suggestion to buy or sell anything. A fee is one thing among "
                   "many; what a fund holds matters too.")
        if _hidden():
            st.caption(f"Amounts are hidden ({MASK}). Show amounts at the top of the page to "
                       "see the dollars.")
    if r["unknown"]:
        syms = [u["symbol"] for u in r["unknown"]]
        st.markdown(f":material/help: We don't know the yearly fee for {_fee_names(syms)} "
                    "yet, so it isn't counted above. The fund's page at your brokerage lists it "
                    "as the expense ratio.")
    if r["no_fee"]:
        st.markdown(f":material/check: Single stocks have no yearly fund fee, so "
                    f"{_fee_names(r['no_fee'])} {'is' if len(r['no_fee']) == 1 else 'are'} "
                    "left out.")
    if r["cash"]:
        st.markdown(":material/savings: Cash and money market funds are left out - a money "
                    "market fund's fee is already taken out of the yield it shows.")
    st.caption(f"An illustration at {growth} a year, not a prediction. Expense ratios come "
               "from Yahoo Finance and can change; your brokerage's fund page has the latest.")
    learn_more("expense_ratios")
    what_this_means("Expense ratio", "Index fund", "Actively managed fund", "ETF", "Mutual fund",
                    "Money market fund", key="gloss_fees")
    # (in a window: switch pages with a full rerun, which also closes it)
    if st.button(f":material/forum: Ask {GUIDE} about fees", key="fee_ask", type="tertiary"):
        _fee_ask()
        _dialog_closed()
        st.rerun()


def open_fee_window():
    st.session_state["dialog_open"] = True   # live prices wait (_dialog_closed)
    _fee_window()


def fee_card_line():
    """Fee check's one line on Home (HTML): the yearly total. None when there
    are no funds (single stocks have no fund fee). Drawn in Home's "Your
    money, checked" card (views/cash_check.py)."""
    r = _fee_check()
    if not fees.has_funds(r):
        return None
    n_unknown = len(r["unknown"])
    return ("We don't have your funds' yearly fees yet." if not r["funds"] else
            f"Your funds' yearly fees: about <span style='font-weight:600'>{html.escape(fmt_money0(r['total_yearly']))}"
            "</span> a year at today's value"
            + (f" ({n_unknown} fund{'s' if n_unknown != 1 else ''} not known yet)."
               if n_unknown else "."))


def render_fee_step():
    """The fee check as a step in Learn the basics (Get started), once there
    are holdings to look at."""
    if not st.session_state.get("gs_has_holdings") or not fees.has_funds(_fee_check()):
        return
    with st.container(border=True, horizontal=True, vertical_alignment="center",
                      key="pt_fees_learn"):
        st.markdown(":material/percent: **Your own funds' fees** - what they cost in dollars "
                    "each year, and over 10 and 30 years.", width="stretch")
        if st.button("Fee check", key="fees_learn_open", type="tertiary",
                     icon=":material/open_in_new:"):
            open_fee_window()
