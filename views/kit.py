# Part of dashboard.py, which runs this file with _view("kit") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Milestones and gear (ROADMAP T3, gear.py): the "milestone reached" window
# when a piece is first earned, and Your kit on Home. Gear is earned by
# learning and steady habits only; nothing is lost or for sale.
# ruff: noqa: F821

import gear
import storms


def _gear_facts(value):
    """What gear.earned() needs, from what the app already knows. Read once
    per run (Home's kit card and the milestone check both ask - _RUN)."""
    if ("gear_facts", value) not in _RUN:
        _RUN[("gear_facts", value)] = _read_gear_facts(value)
    return dict(_RUN[("gear_facts", value)])


def _read_gear_facts(value):
    state = _route_state(HAS_HOLDINGS)
    plan = state["plan"]
    reached = False
    # made-up money never reaches a real goal (the example portfolio)
    if plans.has_goal(plan) and value is not None and SNAPSHOT_SOURCE != SAMPLE_SOURCE:
        reached = _goal_progress(plan, value)["status"] == "reached"
    c = connect(DB)
    try:
        added = [m["date"] for m in plans.money_moves(c, USER_ID)
                 if m["counted"] and m["amount"] > 0]
        values = [(r["logged_at"], r["portfolio_value"]) for r in c.execute(
            "SELECT logged_at, portfolio_value FROM value_log WHERE user_id = ? AND "
            "portfolio_value IS NOT NULL", (USER_ID,))]
        sells = [r["trade_date"] for r in c.execute(
            "SELECT trade_date FROM transactions WHERE user_id = ? AND action = 'SELL'",
            (USER_ID,))]
    finally:
        c.close()
    return {"profile_done": state["done"]["profile"], "goal_set": state["done"]["goal"],
            "basics_done": state["done"]["basics"], "practice_done": state["done"]["practice"],
            "statement_in": HAS_HOLDINGS and SNAPSHOT_SOURCE != SAMPLE_SOURCE,
            "steady": gear.steady_months(added, datetime.now().date()),
            "storm": gear.weathered_storm(values, sells), "goal_reached": reached}


def _kit_shown():
    """Gear and milestones are an investor's own: not the advisor app, and not
    while an advisor is looking at a client."""
    return not IS_ADVISOR and USER_ID == LOGIN_ID


def _milestone_done():
    """Continue, the X or Escape: the window is finished with."""
    st.session_state.pop("milestone_queue", None)
    st.session_state["dialog_open"] = False


@st.dialog("Milestone reached", width="small", on_dismiss=_milestone_done)
def _milestone_window(keys):
    for k in keys:
        _key, name, title, _how, region, _paths = gear.BY_KEY[k]
        st.html("<div class='pt-milestone'>"
                f"<div class='pt-milestone-badge'>{gear.icon_html(k, True, 44)}</div>"
                + (f"<div class='pt-eyebrow' style='margin:0'>{html.escape(region)}</div>"
                   if region else "")
                + f"<div class='pt-milestone-title'>{html.escape(title)}</div>"
                f"<div>You've earned the <b>{html.escape(name.lower())}</b> for your kit.</div>"
                "</div>")
    if st.button("Continue", key="milestone_ok", type="primary", width="stretch"):
        _milestone_done()
        st.rerun()


def check_milestones(value):
    """Show the window once for gear earned since last time (an account from
    before gear existed takes what it has quietly - gear.new_since)."""
    if not _kit_shown():
        return
    have = gear.earned(_gear_facts(value))
    p = _read_prefs()
    fresh, seen = gear.new_since(have, p.get("gear_seen"))
    if seen != p.get("gear_seen"):
        p["gear_seen"] = seen
        _write_prefs(p)
    # kept until it's closed: a redraw that didn't open the window again
    # would close it (live prices wait while it's open - dialog_open)
    queue = st.session_state.get("milestone_queue", []) + fresh
    if queue:
        st.session_state["milestone_queue"] = queue
        st.session_state["dialog_open"] = True
        _milestone_window(queue)


@st.dialog("Your kit", width="large", on_dismiss=_dialog_closed)
def _kit_window(have):
    st.caption(f"{len(have)} of {len(gear.KEYS)} earned. Gear is for learning and steady "
               "habits - never for trading more or taking more risk - and nothing is lost if "
               "you miss a month.")
    cols = st.columns(4)
    for n, k in enumerate(gear.KEYS):
        _key, name, _title, how, _region, _paths = gear.BY_KEY[k]
        got = k in have
        with cols[n % 4].container(border=True, key=f"pt_gear_{k}"):
            st.html(f"<div class='pt-gear-tile{' pt-gear-earned' if got else ''}'>"
                    f"{gear.icon_html(k, got, 28)}</div>"
                    f"<div style='font-weight:600;margin-top:.4rem'>{html.escape(name)}</div>")
            st.caption("Earned" if got else how)


def render_kit_card(value):
    """Your kit on Home: what's earned, and the next one to earn."""
    if not _kit_shown():
        return
    have = gear.earned(_gear_facts(value))
    nxt = next((k for k in gear.KEYS if k not in have), None)
    with st.container(border=True, horizontal=True, vertical_alignment="center",
                      key="pt_kit"):
        icons = "".join(f"<span class='pt-gear-tile{' pt-gear-earned' if k in have else ''}'>"
                        f"{gear.icon_html(k, k in have)}</span>" for k in gear.KEYS)
        st.html("<div class='pt-route-label'>Your kit · "
                f"{len(have)} of {len(gear.KEYS)}</div><div class='pt-gear-row'>{icons}</div>"
                + (f"<div class='pt-region'>Next to earn: <b>{html.escape(gear.BY_KEY[nxt][1].lower())}</b>"
                   f" - {html.escape(gear.BY_KEY[nxt][3][0].lower() + gear.BY_KEY[nxt][3][1:])}</div>"
                   if nxt else "<div class='pt-region'>Every piece earned.</div>"),
                width="stretch")
        if st.button("See your kit", key="kit_open", type="tertiary"):
            st.session_state["dialog_open"] = True   # live prices wait (_dialog_closed)
            _kit_window(have)


# ---- storms (ROADMAP T4, storms.py): a sharp drop as weather to wait out --- #

def _weather_now():
    """storms.weather() for the holdings, worked out once a day per statement
    (the closes only change with the nightly sync)."""
    today = datetime.now().date()
    key = (USER_ID, snapshot, today.isoformat())
    kept = st.session_state.get("weather")
    if not kept or kept[0] != key:
        since = (today - timedelta(days=storms.WINDOW_DAYS)).isoformat()
        kept = (key, storms.weather(perf.daily_values(DB, PERF_BASIS, since), today))
        st.session_state["weather"] = kept
    return kept[1]


def _hide_weather(w):
    p = _read_prefs()
    p["storm_hidden"] = {"level": w["level"], "high_date": w["high_date"]}
    _write_prefs(p)


@st.dialog("What storms have looked like", width="medium", on_dismiss=_dialog_closed)
def _storms_window():
    st.caption("The S&P 500 - the 500 largest US companies - from its high to its low, "
               "and how long until it passed that high again. Rounded; its price "
               "without dividends.")
    rows = "".join(f"<tr><td>{html.escape(name)}</td><td>{fall}%</td><td>{html.escape(back)}</td></tr>"
                   for name, fall, back in storms.PAST_STORMS)
    st.html("<table class='pt-storm-table'><thead><tr><th>Storm</th><th>Fell</th>"
            f"<th>Back to the old high</th></tr></thead><tbody>{rows}</tbody></table>")
    st.markdown("Every one of these passed, though some took years - and nobody knew "
                "at the time how long it would last. That's why people investing for "
                "goals years away usually plan for storms instead of trying to dodge "
                "them: selling after a fall turns a drop on paper into a real loss, and "
                "some of the market's best days have come soon after its worst. Past "
                "storms don't promise what the next one will do.")
    learn_more("market_drops")


def render_weather():
    """A calm note on Home while the holdings are well below their recent
    high - nothing to do, never buy or sell."""
    if not HAS_HOLDINGS:
        return
    w = _weather_now()
    own = USER_ID == LOGIN_ID
    if not w or (own and storms.hidden(w, _read_prefs().get("storm_hidden"))):
        return
    storm = w["level"] == "storm"
    title = "A storm on the trail" if storm else "Rough weather"
    lead = (f"Your holdings are about {w['drop_pct']:.0f}% below their high on "
            f"{_fmt_date(w['high_date'])} (as of the close on {_fmt_date(w['as_of'])}).")
    body = ("Drops of 10% or more have come along about once every year or two on "
            "average, and the market has climbed past every one so far - sometimes "
            "in months, sometimes in years." if storm else
            "Dips like this happen a few times in a typical year, and most pass "
            "without much notice.")
    nothing = ("Nothing needs doing today. If your goal is years away, the plan you "
               "set still holds; if you'll need this money soon, that's worth a look "
               "at your plan.")
    cloak = (storm and _kit_shown()
             and "cloak" not in (_read_prefs().get("gear_seen") or []))
    with st.container(border=True, key="pt_storm"):
        st.html("<div class='pt-eyebrow' style='margin:0'>Weather on the trail</div>"
                f"<div class='pt-storm-title'>{title}</div>"
                f"<div>{html.escape(lead)} {html.escape(body)}</div>"
                f"<div class='pt-region' style='margin-top:.4rem'>{html.escape(nothing)}"
                + (" Holding steady through a storm earns the <b>storm cloak</b> for "
                   "your kit." if cloak else "") + "</div>")
        with st.container(horizontal=True):
            if st.button("What storms have looked like", key="storm_more", type="tertiary"):
                st.session_state["dialog_open"] = True   # live prices wait (_dialog_closed)
                _storms_window()
            st.button(f"Ask {GUIDE}", key="storm_ask", type="tertiary",
                      on_click=_ask_route, args=("storm",))
            if own:
                st.button("Hide for now", key="storm_hide", type="tertiary",
                          on_click=_hide_weather, args=(w,))
