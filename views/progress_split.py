# Part of dashboard.py, which runs this file with _view("progress_split") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# What you did vs what the market did (flag progress_split, progress_split.py):
# a card on Home's middle column, under the performance chart - for this year
# or since the first value, the money added (logged on Plan or in an imported
# activity export) against the market's part of the change, a stacked chart of
# the two, and "Set up an automatic deposit", which only explains how that's
# done at a brokerage. Read-only: nothing here is saved (the period picked is
# this session's only), so an advisor in a client's account sees the same card.
# Your wins (views/wins.py) shares the one read (_ps_facts).
# ruff: noqa: F821

import brokerages
import progress_split


def _ps_facts():
    """progress_split.read() for this account, once per run (one query)."""
    if "ps_facts" not in _RUN:
        conn = connect(DB)
        try:
            _RUN["ps_facts"] = progress_split.read(conn, USER_ID)
        finally:
            conn.close()
    return _RUN["ps_facts"]


def _ps_pretend():
    """The holdings' source when its dollars are pretend (the example or a
    percentages portfolio), else None."""
    src = globals().get("SNAPSHOT_SOURCE")
    return src if src in progress_split.PRETEND_SOURCES else None


def _ps_day(day):
    try:
        d = datetime.strptime(str(day)[:10], "%Y-%m-%d")
    except ValueError:
        return str(day)
    return f"{d:%B} {d.day}, {d.year}"


def _ps_chart(series):
    """Money added, with the market's part stacked on it, at each stop."""
    rows = []
    for s in series:
        rows.append({"date": s["date"], "part": progress_split.CHART_ADDED, "amount": s["added"]})
        rows.append({"date": s["date"], "part": progress_split.CHART_MARKET, "amount": s["market"]})
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    palette = SERIES_DARK if st.context.theme.type == "dark" else SERIES_LIGHT
    hidden = _hidden()
    order = [progress_split.CHART_ADDED, progress_split.CHART_MARKET]
    tips = [alt.Tooltip("date:T", title="When", format="%b %d, %Y"), alt.Tooltip("part:N", title="")]
    if not hidden:
        tips.append(alt.Tooltip("amount:Q", title="Amount", format="$,.0f"))
    chart = alt.Chart(df).mark_area(opacity=0.85, interpolate="monotone").encode(
        x=alt.X("date:T", title=None, axis=alt.Axis(format="%b %Y", grid=False)),
        y=alt.Y("amount:Q", title=None, stack="zero",
                axis=charts.y_axis(charts.MONEY_AXIS, labels=not hidden, grid=True,
                                   gridOpacity=0.25, gridDash=[2, 2])),
        color=alt.Color("part:N", title=None, sort=order, legend=alt.Legend(orient="top", direction="vertical"),
                        scale=alt.Scale(domain=order, range=[palette[0], palette[2]])),
        order=alt.Order("order:Q"),
        tooltip=tips,
    ).transform_calculate(order=f"datum.part == '{progress_split.CHART_ADDED}' ? 0 : 1")
    st.altair_chart(chart.properties(height=220), width="stretch")


def _ps_auto_deposit():
    """How automatic deposits work, and where: only words and the brokerages'
    own links, in alphabetical order (brokerages.py) - nothing is set up."""
    with st.popover(progress_split.AUTO_BUTTON, icon=":material/event_repeat:"):
        st.markdown(f"**{progress_split.AUTO_TITLE}**")
        for line in progress_split.AUTO_LINES:
            st.markdown(line)
        st.markdown(progress_split.AUTO_LOOK)
        st.caption(brokerages.LIST_INTRO)
        names = sorted(brokerages.BROKERAGES, key=lambda b: brokerages.sort_key(b[0]))
        st.markdown("  \n".join("[" + n.replace("*", r"\*") + f"]({url})" for n, url in names))
        st.caption(f"{brokerages.OTHERS} {brokerages.NOT_RANKED}")
        st.caption(progress_split.AUTO_NOTE)


@st.fragment
def render_progress_split():
    """The card. A fragment: picking the period redraws only this."""
    today = datetime.now().date()
    with st.container(border=True, key="pt_progress_split"):
        st.subheader(progress_split.TITLE)
        period = st.segmented_control(
            "Period", list(progress_split.PERIODS), default=progress_split.YEAR,
            format_func=progress_split.PERIODS.get, key="ps_period",
            label_visibility="collapsed") or progress_split.YEAR
        pretend = _ps_pretend()
        r = progress_split.split(_ps_facts(), period, today, current=portfolio_value,
                                 pretend=pretend)
        state = r["state"]
        if state == progress_split.PRETEND:
            st.caption(progress_split.SAMPLE_LINE)
            return
        if state == progress_split.NOT_ENOUGH:
            st.caption(progress_split.NOT_ENOUGH_LINE)
            return
        if state == progress_split.PERCENTAGES:
            _ps_percentages(r)
            _ps_auto_deposit()
            return
        if state == progress_split.UNKNOWN:
            _summary_stats([(progress_split.CHANGE_LABEL,
                             _tone(r["change"], _signed_money0(r["change"])), None)])
            st.markdown(progress_split.UNKNOWN_LINE)
            st.caption(progress_split.UNKNOWN_HOW)
            _ps_auto_deposit()
            return
        market_sub = (progress_split.MARKET_SUB_DIVS.format(amount=fmt_money0(r["income"]))
                      if r["income"] else progress_split.MARKET_SUB)
        third = ((progress_split.SHARE_LABEL, mask_or(f"{r['share']:.0f}%"),
                  html.escape(progress_split.SHARE_SUB)) if r["share"] is not None else
                 (progress_split.CHANGE_LABEL, _tone(r["change"], _signed_money0(r["change"])),
                  None))
        _summary_stats([
            (progress_split.YOU_LABEL, _signed_money0(r["added"]),
             html.escape(progress_split.you_sub(r))),
            (progress_split.MARKET_LABEL, _tone(r["market"], _signed_money0(r["market"])),
             html.escape(market_sub)),
            third])
        if len(r["series"]) >= 2:
            _ps_chart(r["series"])
        for line in progress_split.lines(r, fmt_money0):
            _md(line)
        notes = []
        if r["since"]:
            notes.append(progress_split.SINCE.format(day=_ps_day(r["since"])))
        if r["until"]:
            notes.append(progress_split.UNTIL.format(day=_ps_day(r["until"])))
        if r["late"]:
            notes.append(progress_split.LATE)
        notes.append(progress_split.SOURCE_NOTE)
        st.caption(" ".join(notes))
        _ps_auto_deposit()


def _signed_money0(v):
    """'+$1,800' / '-$1,800' in whole dollars (masked while amounts are hidden)."""
    if _hidden():
        return MASK
    return ("+" if v > 0 else "") + fmt_money0(v)


def _ps_percentages(r):
    """A percentages portfolio: no dollars - the market's move on the mix in
    percent (the holdings now at each day's close, as the chart above), and
    how many months had money added logged."""
    st.markdown(progress_split.PCT_LINE)
    since = r["start"]
    pct = None
    if PERF_BASIS and PERF_BASIS[1]:
        conn = connect(DB)
        try:
            lead = (datetime.strptime(since[:10], "%Y-%m-%d").date()
                    - timedelta(days=progress_split.EDGE_DAYS)).isoformat()
            pct = progress_split.market_pct(perf._reconstructed_daily_rows(conn, PERF_BASIS, lead),
                                            since)
        finally:
            conn.close()
    st.markdown(progress_split.PCT_MARKET.format(pct=mask_or(f"{pct:+.1f}%")) if pct is not None
                else progress_split.PCT_MARKET_NONE)
    if r["known"]:
        st.markdown(progress_split.PCT_ADDED.format(n=r["months_added"]) if r["months_added"]
                    else progress_split.PCT_ADDED_NONE)
    st.caption(progress_split.STEADY)
