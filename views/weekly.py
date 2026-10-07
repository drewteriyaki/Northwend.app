# Part of dashboard.py, which runs this file with _view("weekly") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what
# this defines is visible there afterwards. See _view() in dashboard.py.
#
# Weekly summaries (weekly.py), behind flag weekly (flags.FEATURES - this
# whole file is skipped while it's off). One card on Home
# (views/dashboard_page.py calls render_weekly - self-contained, so it can
# move when Home is redesigned):
# - Friday after the close through Sunday, "Your week": the week's change,
#   the holdings that went up and down the most, the goal's start and end,
#   and up to three kept headlines about the biggest movers.
# - Monday to Thursday, "The week ahead": known pay and earnings dates from
#   the brokerage's file, and the hand-kept public calendar.
# New: a card ("Take a look" / "Not now"); opened: one quiet line; put away:
# nothing until the next moment. What's kept: the moment's id and "seen" or
# "put_away" (prefs weekly.PREF), and only from the login's own session - an
# advisor in a client's account sees the same facts and writes nothing.
# Reads only what's kept: nothing is fetched here.
# ruff: noqa: F821

import news
import weekly


def _wk_own():
    """Only the login's own settings are ever written (also in a callback)."""
    return USER_ID == LOGIN_ID


def _wk_moment():
    return weekly.moment(weekly.now())


def _wk_md(text):
    """Text for st.markdown: dollar signs aren't a formula, and a headline's
    brackets or stars aren't markup."""
    return re.sub(r"([\\`*_\[\]()#<>$|~])", r"\\\1", str(text))


def _wk_mark(mid, status):
    if not _wk_own() or not mid:
        return
    p = _read_prefs()
    new = weekly.with_status(p, mid, status)
    if new != p:
        _write_prefs(new)


def _wk_open(mid):
    st.session_state["wk_open"] = mid
    _wk_mark(mid, weekly.SEEN)


def _wk_close():
    st.session_state.pop("wk_open", None)


def _wk_put_away(mid):
    _wk_mark(mid, weekly.PUT_AWAY)
    _wk_close()


def _wk_your_week(m):
    """weekly.your_week() for this account, read once per moment and
    statement (closes change only with the nightly sync)."""
    key = (USER_ID, snapshot, m["id"])
    kept = st.session_state.get("wk_data")
    if kept and kept[0] == key:
        return kept[1]
    since = (m["start"] - timedelta(days=weekly.LEAD_IN_DAYS)).isoformat()
    tickers = sorted({p["symbol"] for p in positions if p.get("symbol")})
    pretend = SNAPSHOT_SOURCE == manual_entry.PCT_SOURCE   # a pretend total
    plan = load_plan()
    goal = plans.has_goal(plan) and not pretend
    c = connect(DB)
    try:
        values = perf.daily_values(c, PERF_BASIS, since)
        closes = perf.closes_since(c, tickers, since)
        data = weekly.your_week(values, closes, start=m["start"], end=m["end"])
        movers = [t for t, _p in data["up"] + data["down"]]
        kept_news = {t: news.latest_news(c, t, limit=10) for t in movers}
    finally:
        c.close()
    data = weekly.your_week(
        values, closes, start=m["start"], end=m["end"],
        target=plan.get("target_amount") if goal else None,
        goal_name=(plan.get("goal_name") or plan.get("goal_type")) if goal else None,
        news=kept_news)
    data["dollars"] = not pretend
    st.session_state["wk_data"] = (key, data)
    return data


def _wk_week_body(m):
    data = _wk_your_week(m)
    words = weekly.your_week_lines(
        data, money=_signed_money, pct=lambda v: mask_or(f"{v:+.2f}%"),
        level=lambda v: mask_or(f"{v:.0f}%"), dollars=data["dollars"])
    st.caption(_wk_md(words["span"]))
    st.markdown(_wk_md(words["change"]))
    if data["change"] is not None:
        st.caption(_wk_md(words["how"]))
    for lead, items in ((weekly.UP_LEAD, words["up"]), (weekly.DOWN_LEAD, words["down"])):
        if items:
            st.markdown(f"**{_wk_md(lead)}** " + ", ".join(_wk_md(i) for i in items))
    if words["movers_none"]:
        st.markdown(_wk_md(words["movers_none"]))
    if words["goal"]:
        st.markdown(_wk_md(words["goal"]))
    if words["headlines"]:
        st.markdown(f"**{_wk_md(words['news_lead'])}**")
        st.markdown("\n".join(
            f"- {_wk_md(h['ticker'])}: [{_wk_md(h['headline'])}]({h['url']})"
            + (f" - {_wk_md(h['source'])}" if h["source"] else "")
            for h in words["headlines"]))
        st.caption(_wk_md(words["news_note"]))
    st.caption(f":material/info: {_wk_md(words['foot'])}")


def _wk_ahead_body(m):
    snap_day = None
    try:
        snap_day = date.fromisoformat(str(snapshot)[:10])
    except ValueError:
        pass
    data = weekly.week_ahead(positions, start=m["start"], end=m["end"], snapshot=snap_day)
    words = weekly.week_ahead_lines(data)
    st.caption(_wk_md(words["span"]))
    if words["holdings"]:
        st.markdown("\n".join(f"- **{_wk_md(d)}** - {_wk_md(t)}" for d, t in words["holdings"]))
        if words["source"]:
            st.caption(_wk_md(words["source"]))
    else:
        st.markdown(_wk_md(words["holdings_none"]))
    st.caption(_wk_md(words["ex_note"]))
    if words["calendar"]:
        st.markdown(f"**{_wk_md(words['cal_lead'])}**")
        st.markdown("\n".join(f"- **{_wk_md(d)}** - {_wk_md(t)} ([source]({u}))"
                              for d, t, u in words["calendar"]))
        st.caption(_wk_md(words["cal_note"]))
    st.caption(f":material/info: {_wk_md(words['foot'])}")


def render_weekly():
    """Home: this moment's card while it's new, one quiet line once opened,
    nothing once put away (or on Friday before the close)."""
    if not HAS_HOLDINGS:
        return
    m = _wk_moment()
    if not m:
        return
    state = weekly.home_state(_read_prefs().get(weekly.PREF), m["id"])
    if not state:
        return
    week = m["kind"] == weekly.WEEK
    title = weekly.WEEK_TITLE if week else weekly.AHEAD_TITLE
    why = weekly.WEEK_WHY if week else weekly.AHEAD_WHY
    icon = ":material/date_range:" if week else ":material/event_upcoming:"
    is_open = st.session_state.get("wk_open") == m["id"]
    if state == "line" and not is_open:
        with st.container(horizontal=True, vertical_alignment="center", key="pt_weekly_line"):
            st.caption(f"{title} - {why}", width="stretch")
            st.button(title, key="wk_open_btn", type="tertiary", icon=icon,
                      on_click=_wk_open, args=(m["id"],))
        return
    with st.container(border=True, key="pt_weekly_card"):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(f"{icon} **{title}** - {why}", width="stretch")
            if is_open:
                st.button("Close", key="wk_close", type="tertiary", on_click=_wk_close)
            else:
                st.button("Take a look", key="wk_open_btn", type="primary",
                          on_click=_wk_open, args=(m["id"],))
                if _wk_own():
                    st.button("Not now", key="wk_later", type="tertiary",
                              on_click=_wk_put_away, args=(m["id"],))
        if is_open:
            (_wk_week_body if week else _wk_ahead_body)(m)
