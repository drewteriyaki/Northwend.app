# Part of dashboard.py, which runs this file with _view("get_started") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# The Get started page: the new-investor path and the practice portfolio.
# ruff: noqa: F821

# ---- Get started page ------------------------------------------------------ #
# readiness state -> (icon markdown, words); the words always go with the icon
_READY_ICON = {
    learn.GOOD: (":green[:material/check_circle:]", "Good"),
    learn.CAUTION: (":orange[:material/error:]", "Look at this"),
    learn.STOP: (":red[:material/cancel:]", "Start here"),
    learn.UNKNOWN: (":gray[:material/help:]", "Not answered"),
}
GET_STARTED_STEPS = (
    ("profile", "About you"),
    ("ready", "Are you ready to invest?"),
    ("goal", "Set a goal"),
    ("basics", "Learn the basics"),
    ("mix", "An example mix"),
    ("practice", "Try it with practice money"),
    ("account", "Open an account and bring it in"),
)
# questions a step can hand to the AI Assistant
COACH_PROMPTS = {
    "ready": "Looking at my situation, what should I take care of before I start investing, "
             "and in what order?",
    "basics": "Explain stocks, bonds, index funds and ETFs to me like I'm brand new to investing.",
    "mix": "Explain why a mix of US stocks, international stocks and bonds might fit my time "
           "horizon and comfort with risk. Use examples, not recommendations.",
    "practice": "What should I expect emotionally when my investments drop 20% or more, and "
                "what do long-term investors usually do?",
    "account": "What's the difference between a regular brokerage account, a Roth IRA and a "
               "401(k), and which questions should I ask to pick one?",
}
PRACTICE_MIXES = ("Example mix", "All stocks", "Mostly bonds")


def _usd0(v):
    """Whole dollars, never masked - for hypothetical practice numbers."""
    return f"-${abs(v):,.0f}" if v < 0 else f"${v:,.0f}"


def _ask_coach(step):
    st.session_state["coach_prompt"] = COACH_PROMPTS[step]
    st.session_state["page"] = "AI Assistant"


def _coach_button(step):
    st.button(f":material/forum: Ask {GUIDE} about this", key=f"coach_{step}",
              type="tertiary", on_click=_ask_coach, args=(step,))


def _done_steps():
    return set(_read_prefs().get("get_started_done") or [])


def _mark_done(step, done=True):
    p = _read_prefs()
    steps = set(p.get("get_started_done") or [])
    (steps.add if done else steps.discard)(step)
    p["get_started_done"] = sorted(steps)
    _write_prefs(p)
    if done:
        st.session_state["gs_advance"] = step   # move on to the next waypoint

def _done_button(step, done):
    if done:
        st.button("Mark as not done", key=f"undone_{step}", type="tertiary",
                  on_click=_mark_done, args=(step, False))
    else:
        st.button("Mark as done", key=f"done_{step}", on_click=_mark_done, args=(step,))


def _practice_prices(conn):
    """{ticker: [(date, price)]} for the practice funds, dividends included
    (adjusted close, falling back to close)."""
    out = {}
    for t in learn.PRACTICE_TICKERS.values():
        out[t] = [(r["date"], float(r["adj_close"] if r["adj_close"] is not None else r["close"]))
                  for r in conn.execute(
                      "SELECT date, adj_close, close FROM daily_bars WHERE ticker = ? "
                      "AND COALESCE(adj_close, close) IS NOT NULL ORDER BY date", (t,))]
    return out


def _render_mix_bar(weights):
    palette = SERIES_DARK if st.context.theme.type == "dark" else SERIES_LIGHT
    segs = legend = ""
    for i, b in enumerate(learn.BLOCKS):
        pct = weights[b["key"]]
        if pct > 0:
            segs += (f"<div class='pt-alloc-seg' style='flex:{pct} 0 0;background:{palette[i]}' "
                     f"title='{b['label']} {pct}%'></div>")
        legend += ("<div class='pt-legend-row'>"
                   f"<span class='pt-swatch' style='background:{palette[i]}'></span>"
                   f"<span class='pt-legend-label'><b>{b['label']}</b> - {b['about']}</span>"
                   f"<span class='pt-legend-pct'>{pct}%</span></div>"
                   f"<div class='pt-goal-sub' style='margin:0 0 .5rem 1.1rem'>Examples: "
                   f"{', '.join(b['examples'])}</div>")
    st.html(f"<div class='pt-alloc-bar' aria-hidden='true'>{segs}</div>"
            f"<div class='pt-legend'>{legend}</div>")


def _step_profile(advisor, profile, missing):
    if missing:
        st.caption("A few questions so the rest of this page fits you. Every answer is a tap, "
                   "and you can change them any time.")
        _render_profile_form(advisor, profile)
        return
    known = [f"{advisor.PROFILE_FIELDS[f]}: **{profile[f]}**" for f in
             ("goal", "time_horizon_years", "risk_tolerance", "experience", "age_range")
             if profile.get(f) not in (None, "")]
    st.markdown("  \n".join(known))
    if st.toggle("Change my answers", key="gs_edit_profile"):
        _render_profile_form(advisor, profile)


def _step_ready(items):
    st.markdown(f"**{learn.readiness_summary(items)}**")
    for it in items:
        icon, words = _READY_ICON[it["state"]]
        st.markdown(f"{icon} **{it['label']}** ({words}) - {it['text']}")
    st.caption("These are common first steps many people take before investing, not rules - "
               "your situation may differ.")
    _coach_button("ready")


def _step_goal(plan, value):
    if plans.has_goal(plan):
        gp = _goal_progress(plan, value)
        label, _tone_cls = PLAN_STATUS[gp["status"]]
        _md(f"**{plan.get('goal_name') or plan['goal_type']}**: {fmt_money0(gp['target'])} by "
            f"{_fmt_month(plan['target_date'])} - {label.lower()}.")
        st.button("Open plan", key="gs_open_plan", on_click=_go, args=("Plan",))
    elif not CAN_MANAGE:
        st.caption("Your advisor sets your goal with you - it shows up on the Plan page once "
                   "they have.")
    else:
        st.caption("Pick what you're investing for and roughly how much you'll need. Even a "
                   "rough goal makes it easier to know how much to put in each month.")
        st.button("Set a goal", key="gs_set_goal", type="primary", on_click=_go, args=("Plan",))


def _basics_topics(monthly, years):
    """The basics, one topic each: (key, icon, title, one line, the full text)."""
    yrs = max(1, int(round(years)))
    put_in = monthly * 12 * yrs
    grown = learn.grow_monthly(monthly, yrs, 6)
    later = learn.grow_monthly(monthly, yrs - 10, 6) if yrs > 10 else None
    fee = learn.fee_cost(monthly, yrs, 6, 0.05, 1.0)
    fmt = lambda v: _usd0(v).replace("$", r"\$")  # noqa: E731
    return [
        ("funds", ":material/category:", "Stocks, bonds and funds", "What you can actually buy",
         "A stock is a small piece of one company. A bond is a loan to a government or company "
         "that pays you interest. A fund holds many stocks or bonds at once; an **ETF** is a "
         "fund you buy and sell like a stock, and an **index fund** simply holds a whole market "
         "(like every US company) instead of trying to pick winners."),
        ("spread", ":material/scatter_plot:", "Why spread it out", "One stumble can't sink you",
         "Any one company can stumble or fail. A total-market fund holds thousands of "
         "companies, so no single one can sink you - that's diversification, and index funds "
         "give it to you in one purchase."),
        ("time", ":material/hourglass_bottom:", "Time does the heavy lifting",
         "Why starting early matters",
         f"Putting in {fmt(monthly)} a month for {yrs} years is {fmt(put_in)} of your own "
         f"money. At 6% a year it could grow to about **{fmt(grown)}**."
         + (f" Starting 10 years later, the same {fmt(monthly)} a month gets to about "
            f"{fmt(later)} - most of the growth comes from the early years." if later else "")
         + "\n\n*An illustration at 6% a year, not a prediction.*"),
        ("fees", ":material/percent:", "Fees add up", "Small percentages, big dollars",
         f"Funds charge a yearly fee called the expense ratio. On {fmt(monthly)} a month for "
         f"{yrs} years, a fund charging 1% instead of 0.05% would leave you about "
         f"**{fmt(fee)} less**. Broad index funds are usually among the cheapest."),
        ("ups", ":material/show_chart:", "Ups and downs are normal", "What drops look like",
         "The US stock market fell about a third in a month in early 2020 and by more than "
         "half in 2007-09, then recovered over the following years. Staying invested through "
         "drops has historically mattered more than timing them. Money you'll need in the next "
         "few years usually belongs in savings instead."),
        ("accounts", ":material/account_balance:", "Account types",
         "Brokerage, Roth IRA, 401(k)",
         "A regular brokerage account has no limits but you pay tax on gains and dividends. A "
         "**Roth IRA** is for retirement: you put in money you've already paid tax on, and it "
         "can grow and come out tax-free later. A **401(k)** through work often comes with an "
         "employer match. IRAs and 401(k)s have yearly limits - check IRS.gov for this year's."),
    ]


@st.dialog("The basics", width="medium")
def _basics_window(key, monthly, years):
    for k, icon, title, _line, body in _basics_topics(monthly, years):
        if k == key:
            st.markdown(f"### {icon} {title}")
            st.markdown(body)
    # (in a window: switch pages with a full rerun, which also closes it)
    if st.button(f":material/forum: Ask {GUIDE} about this", key="basics_ask", type="tertiary"):
        _ask_coach("basics")
        st.rerun()


def _step_basics(monthly, years, done):
    st.caption("Six short ideas worth knowing before you invest. Open any of them.")
    topics = _basics_topics(monthly, years)
    cols = st.columns(3)
    for n, (k, icon, title, line, _body) in enumerate(topics):
        with cols[n % 3].container(border=True, key=f"pt_tile_basics_{k}"):
            st.markdown(f"{icon} **{title}**")
            st.caption(line)
            if st.button("Read", key=f"basics_{k}", type="tertiary",
                         icon=":material/open_in_new:"):
                _basics_window(k, monthly, years)
    render_fee_step()   # your own funds' fees, once there are holdings (views/fees.py)
    _done_button("basics", done)


def _step_mix(mix, profile, plan, done):
    if mix is None:
        st.caption("Answer the time horizon question in step 1 to see an example mix.")
        return
    if mix["short_horizon"]:
        st.info("You'll need this money within about 3 years. Money needed that soon usually "
                "goes in a high-yield savings account, CDs or Treasury bills rather than stocks. "
                "This is how a cautious mix would look if you do invest some of it.")
    st.markdown(f"An example for someone with your answers: **{mix['stocks_pct']}% stocks, "
                f"{mix['weights']['bonds']}% bonds.**")
    _render_mix_bar(mix["weights"])
    st.markdown("Why this split:  \n" + "  \n".join(f"- {r}" for r in mix["reasons"]))
    extra = []
    year = learn.target_date_year(plan, profile.get("age_range"), datetime.now().date())
    prefs_set = set((profile.get("preferences") or "").split("; "))
    if year and ((plan or {}).get("goal_type") == "Retirement"
                 or "Hands-off / set and forget" in prefs_set or "Retirement" in (profile.get("goal") or "")):
        extra.append(f"**One-fund option:** a target-date fund (look for a name with **{year}** "
                     "in it, like \"Target Retirement " + str(year) + "\") holds a mix like this "
                     "in a single fund and gradually shifts toward bonds as that year gets closer.")
    if "Sustainable (ESG) investing" in prefs_set:
        extra.append("**Sustainable investing:** ESG versions of broad index funds exist - for "
                     "example ESGV for US stocks.")
    if "Dividend income" in prefs_set:
        extra.append("**Dividend income:** dividend-focused funds, for example SCHD or VYM, lean "
                     "toward companies that pay regular dividends.")
    for e in extra:
        st.markdown(e)
    st.caption("An example for learning, based on common rules of thumb - not a recommendation "
               "to buy these funds. The tickers are examples of well-known, low-cost index "
               "funds; many similar funds exist.")

    def _watch_examples():
        c = connect(DB)
        try:
            for t in learn.PRACTICE_TICKERS.values():
                watchlist.add(c, USER_ID, t)
        finally:
            c.close()
        st.session_state["refresh_msg"] = (
            "toast", "Added " + ", ".join(learn.PRACTICE_TICKERS.values()) + " to your watchlist.")

    with st.container(horizontal=True):
        st.button("Watch these example funds", key="gs_watch", on_click=_watch_examples,
                  help="Adds " + ", ".join(learn.PRACTICE_TICKERS.values())
                       + " to your Watchlist so you can follow their prices.")
        _coach_button("mix")
    _done_button("mix", done)


def _step_practice(mix, plan, profile, done):
    today = datetime.now().date()
    conn = connect(DB)
    try:
        prices = _practice_prices(conn)
    finally:
        conn.close()
    have = [p for p in prices.values() if p]
    first = max(p[0][0] for p in have) if len(have) == len(prices) else None
    last = min(p[-1][0] for p in have) if have else None
    years_avail = ((today - date.fromisoformat(first)).days / 365.25) if first else 0
    stale = not last or (today - date.fromisoformat(last)).days > 7
    if years_avail < 5 or stale:
        st.caption("The practice portfolio uses real past prices for "
                   + ", ".join(learn.PRACTICE_TICKERS.values()) + ". Load them first (takes a "
                   "few seconds).")
        if st.button("Load price history", key="gs_load_prices", type="primary"):
            try:
                import sync_history
            except ImportError:
                st.error("Price history needs yfinance - run: pip install yfinance")
                return
            with st.spinner("Loading 10 years of prices..."):
                sync_history.sync(DB, list(learn.PRACTICE_TICKERS.values()), period="10y",
                                  with_intraday=False, with_info=False, delay=0.0)
            st.rerun()
        if not first:
            return

    default_monthly = float((plan or {}).get("monthly_contribution") or 200.0)
    c1, c2 = st.columns(2)
    monthly = c1.number_input("Put in each month ($)", min_value=0.0, step=50.0, format="%.0f",
                              value=default_monthly, key="gs_monthly")
    initial = c2.number_input("Starting amount ($)", min_value=0.0, step=100.0, format="%.0f",
                              value=0.0, key="gs_initial")
    span_opts = [y for y in (1, 3, 5, 10) if y <= years_avail + 0.05] or [1]
    years = st.segmented_control("Starting", span_opts, default=span_opts[-1], key="gs_years",
                                 format_func=lambda y: f"{y} year{'s' if y != 1 else ''} ago") \
        or span_opts[-1]
    which = st.segmented_control("Mix", PRACTICE_MIXES, default=PRACTICE_MIXES[0],
                                 key="gs_mix") or PRACTICE_MIXES[0]
    stocks = {"Example mix": (mix or {}).get("stocks_pct", 60), "All stocks": 100,
              "Mostly bonds": 20}[which]
    us = round(stocks * learn.US_SHARE_OF_STOCKS)
    t = learn.PRACTICE_TICKERS
    weights = {t["us"]: us, t["intl"]: stocks - us, t["bonds"]: 100 - stocks}
    start = plans.add_months(today, -12 * years).isoformat()
    rows = learn.simulate(prices, weights, monthly=monthly, initial=initial, start=start)
    if len(rows) < 2 or not rows[-1]["money_in"]:
        st.caption("Enter an amount to see how it would have gone.")
        return
    end = rows[-1]
    growth = end["value"] - end["money_in"]
    dd = learn.max_drawdown(rows)
    tone = "pt-up" if growth > 0 else "pt-down" if growth < 0 else ""
    st.html("<div class='pt-stats'>"
            f"<div class='pt-stat'><div class='pt-stat-label'>Put in</div>"
            f"<div class='pt-stat-value'>{_usd0(end['money_in'])}</div></div>"
            f"<div class='pt-stat'><div class='pt-stat-label'>Worth today</div>"
            f"<div class='pt-stat-value'>{_usd0(end['value'])}</div>"
            f"<div class='pt-stat-sub {tone}'>{'+' if growth >= 0 else ''}{_usd0(growth)}</div></div>"
            f"<div class='pt-stat'><div class='pt-stat-label'>Worst drop</div>"
            f"<div class='pt-stat-value'>{dd:.0f}%</div></div></div>")
    df = pd.DataFrame(rows[::5] + ([rows[-1]] if len(rows) % 5 != 1 else []))
    df["date"] = pd.to_datetime(df["date"])
    palette = SERIES_DARK if st.context.theme.type == "dark" else SERIES_LIGHT
    st.altair_chart(charts.money_in_chart(df, money_color=SERIES_OTHER, value_color=palette[0]),
                    width="stretch")
    mix_words = f"{stocks}% stocks / {100 - stocks}% bonds ({', '.join(f'{k} {v}%' for k, v in weights.items() if v)})"
    reaction = profile.get("drawdown_reaction")
    _md(f"Starting {_fmt_month(rows[0]['date'])} with {_usd0(initial)} and {_usd0(monthly)} a "
        f"month in {mix_words}. At its worst, the mix was **{abs(dd):.0f}% below its high**"
        + (f" - you said you'd *{reaction.lower()}* after a 20% drop. Selling during a drop "
           "locks in the loss; the chart shows what staying in would have looked like."
           if reaction in ("Sell everything", "Sell some") and dd <= -15 else "."))
    st.caption("Real past prices with dividends reinvested; no fees or taxes; nothing is "
               "rebalanced. Past results don't predict future ones - this is practice, not "
               "a forecast.")
    _coach_button("practice")
    _done_button("practice", done)


def _step_account(monthly, has_holdings):
    if not CAN_IMPORT and not has_holdings:
        st.markdown(f"Your advisor, {_advisor_display_name()}, helps you open the account and "
                    "brings your statements in - your portfolio shows up on Home once they have.")
        _coach_button("account")
        return
    if has_holdings:
        st.markdown("You've brought in your first statement - **Home** shows your real "
                    "portfolio and the **Plan** tracks it against your goal.")
        st.button("Open Home", key="gs_open_dash", on_click=_go, args=("Dashboard",))
        return
    st.markdown(
        "1. **Pick a brokerage.** Large low-cost ones include Schwab, Fidelity and Vanguard. "
        "Look for no account minimum and no trading commissions.\n"
        "2. **Pick the account type** - see *Account types* in step 4.\n"
        "3. **Link your bank** and move money in.\n"
        "4. **Buy your funds.** Many brokerages let you buy fractional shares, so you can start "
        "with a small amount.\n"
        + (f"5. **Set up automatic investing** of {_usd0(monthly)} a month - the amount in your "
           "plan - so it happens without you having to remember.\n".replace("$", r"\$")
           if monthly else
           "5. **Set up automatic monthly investing** so it happens without you having to "
           "remember.\n")
        + "6. **Bring it in here:** use **Holdings** in the sidebar - paste your positions, "
        "upload a CSV or type them in; any brokerage works. Your Plan then tracks the real thing.")
    with st.container(horizontal=True):
        st.button("Import my first statement", key="gs_import", type="primary", on_click=_go,
                  args=("Dashboard",))
        _coach_button("account")


def _route_state(has_holdings):
    """Where this account is on Get started's route - shared with the Home
    page's "Your route" card (route.py). Returns a dict: profile, missing
    (unanswered profile questions), items (readiness), plan, horizon (years
    to the goal date, or None), done ({waypoint key: bool})."""
    import advisor

    today = datetime.now().date()
    conn = connect(DB)
    try:
        profile = advisor.get_profile(conn, USER_ID)
    finally:
        conn.close()
    plan = load_plan()
    missing = advisor.missing_fields(profile)
    items = learn.readiness(profile)
    manual = _done_steps()
    horizon = (plans.months_until(plan["target_date"], today) / 12
               if plans.has_goal(plan) and plans.months_until(plan["target_date"], today) > 0 else None)
    done = {
        "profile": not missing,
        "ready": all(i["state"] != learn.UNKNOWN for i in items),
        "goal": plans.has_goal(plan),
        "basics": "basics" in manual,
        "mix": "mix" in manual,
        "practice": "practice" in manual,
        "account": has_holdings,
    }
    return {"profile": profile, "missing": missing, "items": items, "plan": plan,
            "horizon": horizon, "done": done}


def _ask_type(name):
    st.session_state["coach_prompt"] = (
        f"Northwend says I'm a \"{name}\". Explain what that means for someone like me, what "
        "the example mix is built from, and what I should understand before investing. Use "
        "examples, not recommendations.")
    st.session_state["page"] = "AI Assistant"


def _render_direction(kind, mix):
    """The "Find your direction" card (ROADMAP G3): the investor type from the
    answers, with the example mix and the kinds of funds that usually fill it."""
    with st.container(border=True, key="pt_direction"):
        st.html(f"<div class='pt-route-label'>Your direction</div>"
                f"<div class='pt-type-name'>{html.escape(kind['name'])}</div>"
                f"<div class='pt-type-line'>{html.escape(kind['line'])}</div>")
        st.markdown(kind["about"])
        if kind["key"] not in ("short_term",):
            st.markdown(f"**An example mix for this type:** {mix['stocks_pct']}% stocks, "
                        f"{mix['weights']['bonds']}% bonds.")
            _render_mix_bar(mix["weights"])
        st.markdown("**Kinds of funds that usually fill it:**  \n"
                    + "  \n".join(f"- {k}" for k in kind["kinds"]))
        st.markdown(f":material/info: {kind['watch']}")
        st.caption("A common rule of thumb for learning, from your answers - not a "
                   "recommendation to buy anything. Change your answers in waypoint 1 any time.")
        st.button(f":material/forum: Ask {GUIDE} what this means for me", key="type_ask",
                  type="tertiary", on_click=_ask_type, args=(kind["name"],))


def _gs_go(key):
    st.session_state["gs_at"] = key


def _gs_pick():
    if st.session_state.get("gs_pick"):
        st.session_state["gs_at"] = st.session_state["gs_pick"]


@st.dialog("Your direction", width="large")
def _direction_window(kind_key):
    state = _route_state(st.session_state.get("gs_has_holdings", False))
    mix = learn.starter_mix(state["profile"], state["horizon"])
    kind = learn.investor_type(state["profile"], mix, state["items"])
    if kind:
        _render_direction(kind, mix)
    if st.session_state.get("page") == "AI Assistant":   # its Ask button: go there
        st.rerun()


def _render_get_started(has_holdings, value):
    import advisor

    if first_steps_active(has_holdings):   # a new investor: the slideshow (first_steps.py)
        render_first_steps(has_holdings)
        return

    st.session_state["gs_has_holdings"] = has_holdings
    state = _route_state(has_holdings)
    profile, missing, items, plan = (state["profile"], state["missing"], state["items"],
                                     state["plan"])
    horizon, done = state["horizon"], state["done"]
    mix = learn.starter_mix(profile, horizon)
    monthly = float((plan or {}).get("monthly_contribution") or 0.0)
    years = horizon or float(profile.get("time_horizon_years") or 20)
    n_done = sum(done.values())
    kind = learn.investor_type(profile, mix, items)
    keys = [k for k, _ in GET_STARTED_STEPS]
    titles = dict(GET_STARTED_STEPS)

    # which waypoint is open: the first not reached, unless they picked one;
    # marking one done (_mark_done) moves on to the next not reached
    after = st.session_state.pop("gs_advance", None)
    if after in keys:
        later = keys[keys.index(after) + 1:] + keys[:keys.index(after)]
        st.session_state["gs_at"] = next((k for k in later if not done[k]), after)
    first_open = next((k for k in keys if not done[k]), keys[-1])
    at = st.session_state.get("gs_at")
    if at not in keys:
        at = first_open
    i = keys.index(at)

    # ---- your direction, in one line (the whole card in a window) --------- #
    if kind and not missing:
        with st.container(border=True, horizontal=True, vertical_alignment="center"):
            st.html(f"<span class='pt-route-label'>Your direction</span><br>"
                    f"<b>{html.escape(kind['name'])}</b> - {html.escape(kind['line'])}",
                    width="stretch")
            if st.button("See your mix", key="gs_direction", type="tertiary",
                         icon=":material/open_in_new:"):
                _direction_window(kind["key"])

    # ---- the route: drawn as a trail, then every waypoint to tap -------- #
    waypoints = [(k, titles[k], done[k]) for k in keys]
    here, nxt = route.region(waypoints)
    st.html(route.trail_html(route.dots(waypoints, False),
                             f"{n_done} of {len(keys)} waypoints reached")
            + f"<div class='pt-region'>You're in <b>{html.escape(here)}</b>"
            + (f" · next, {html.escape(nxt)}" if nxt else "") + "</div>")
    st.caption("It explains and shows examples; it never tells you what to buy.")
    st.session_state["gs_pick"] = at   # always the open one
    st.pills("Waypoints", keys, key="gs_pick", label_visibility="collapsed",
             on_change=_gs_pick,
             format_func=lambda k: ("✓ " if done[k] else f"{keys.index(k) + 1}. ") + titles[k])

    # ---- the open waypoint ------------------------------------------------ #
    with st.container(border=True, key=f"pt_slide_gs_{at}"):
        st.caption(f"Waypoint {i + 1} of {len(keys)}" + (" · reached" if done[at] else ""))
        st.markdown(f"### {titles[at]}")
        if at == "profile":
            _step_profile(advisor, profile, missing)
        elif at == "ready":
            _step_ready(items)
        elif at == "goal":
            _step_goal(plan, value)
        elif at == "basics":
            _step_basics(monthly or 200.0, years, done["basics"])
        elif at == "mix":
            _step_mix(mix, profile, plan, done["mix"])
        elif at == "practice":
            _step_practice(mix, plan, profile, done["practice"])
        else:
            _step_account(monthly, has_holdings)
    with st.container(horizontal=True):
        if i:
            st.button(":material/arrow_back: " + titles[keys[i - 1]], key="gs_prev",
                      on_click=_gs_go, args=(keys[i - 1],))
        st.space("stretch")
        if i < len(keys) - 1:
            st.button(titles[keys[i + 1]] + " :material/arrow_forward:", key="gs_next",
                      on_click=_gs_go, args=(keys[i + 1],))
    if not IS_ADVISOR and USER_ID == LOGIN_ID:
        st.button(":material/replay: Go through the first steps again", key="fs_restart",
                  type="tertiary", on_click=_fs_restart)
    check_milestones(value)   # a waypoint just reached may earn gear (views/kit.py)
