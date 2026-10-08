# Part of dashboard.py, which runs this file with _view("dashboard_page") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# The Dashboard page (Home): the value on the band, then three parts on a laptop -
# the performance chart and the holdings table in the middle (a row opens the
# ticker's own page; allocation and accounts below) and "This month" on the
# right: the first few cards - the walk, the next step, the mix... - each short,
# with a small X to put it away (home_tasks.py), long ones opening in a window,
# and "Show N more" for the rest. On a phone: one column, This month first.
# ruff: noqa: F821

import home_tasks

ROUTE_ASK = {   # what "Ask Northwend" starts with, per next step
    "storm": "The market has dropped and my portfolio is down. What have drops like this "
             "looked like before, and how do long-term investors usually think about them?",
    "drift": "My mix has drifted from my target. What does rebalancing mean, and how do people "
             "usually decide when and how to do it?",
    "gap": "I'm behind on my goal. What are the usual ways to close a gap like mine - adding "
           "more, waiting longer, or changing the target?",
    "monthly": "How do people decide how much to invest each month toward a goal like mine?",
    "steady": "I'm on track for my goal. What should I keep an eye on from here?",
    "reached": "I've reached my goal. What do people usually think about when they hit a goal "
               "and set the next one?",
    **CLIENT_ASK,   # an advisor's client's next steps (views/start_home.py)
}


def _ask_route(key):
    st.session_state["coach_prompt"] = ROUTE_ASK.get(
        key, "Looking at my plan and portfolio, what's a sensible next step for me to learn about?")
    st.session_state["page"] = "AI Assistant"


def _route_words(step, gp, monthly, plan):
    """(title, explanation, button label, what the button does) for route.next_step()."""
    k = step["key"]
    when = _fmt_month(plan["target_date"]) if plans.has_goal(plan) else ""
    if k == "goal":
        return ("Set your goal", "Pick what you're investing for and roughly when. Everything "
                "else on your route follows from it.", "Set a goal", ("learn", "goal"))
    if k == "goal_wait":
        return ("Your advisor sets your goal with you", "It shows up here once they have. Their "
                "notes to you are under Advisor notes.", "Advisor notes", ("page", "Advisor notes"))
    if k == "profile":
        return ("Tell us a little about you", "A few quick questions - your timeline and how you "
                "feel about ups and downs - so your route fits you.", "Answer the questions",
                ("page", "Get started"))
    if k == "holdings":
        return ("Bring in your holdings", "Paste them from any brokerage, type them in, or use "
                "percentages only.", "Add holdings", ("dialog", "manual"))
    if k == "monthly":
        need = step.get("needed")
        return ("Choose how much to add each month", "Regular amounts do most of the work on the "
                "way to a goal." + (f" About {fmt_money0(need)} a month would reach yours by "
                                    f"{when} at the plan's assumed return." if need else ""),
                "Open your plan", ("page", "Plan"))
    if k == "gap":
        return ("Close the gap to your goal",
                f"You're adding {fmt_money0(monthly)} a month. About {fmt_money0(step['needed'])} "
                f"({fmt_money0(step['extra'])} more) would get you there by {when} at the plan's "
                "assumed return - or you could move the date or the target.",
                "Open your plan", ("page", "Plan"))
    if k == "drift":
        actual = mask_or(f"{step['actual']:.0f}%")
        return ("Your mix has drifted from its target",
                f"{step['label']} is {actual} of your portfolio against a target of "
                f"{step['target']:.0f}%. Bringing it back is called rebalancing - new money "
                "can do it without selling.",
                "See your target mix", ("page", "Plan"))
    if k == "update":
        return ("Update your holdings", f"You last brought them in {step['days']} days ago - "
                "an update keeps your route and plan accurate.", "Update holdings",
                ("dialog", "manual"))
    if k == "learn":   # the stage and step are in the line above ("You're in ...")
        return (step["title"], f"Next on your route in {_label('Get started')}.",
                "Continue", ("learn", step["step"]))
    if k == "reached":
        return ("You've reached your goal", "Well done. Set your next goal whenever you're "
                "ready.", "Set the next goal", ("page", "Plan"))
    return ("You're on track", f"At {fmt_money0(monthly)} a month, the projection reaches "
            f"your goal by {when}. Hypothetical, not a promise.", "Open your plan",
            ("page", "Plan"))


def _route_go(action):
    kind, target = action
    if kind == "dialog":
        _open_holdings_dialog(target)
    elif kind == "learn":   # that waypoint open on Learn (Set a goal is walked there)
        st.session_state["gs_at"] = target
        st.session_state.pop("gs_goal_part", None)
        _go("Get started")
    else:
        _go(target)


def _render_route():
    """The investor home's first card (ROADMAP G2): the goal, the waypoints,
    and the one next step (route.py decides which)."""
    state = _route_state(True)
    plan = state["plan"]
    has_goal = plans.has_goal(plan)
    gp = _goal_progress(plan, portfolio_value) if has_goal else None
    monthly = float((plan or {}).get("monthly_contribution") or 0.0)
    pct = {r["label"]: r["pct"] for r in
           allocate(positions, cash_by_account, CLASS_SPLITS)["by_asset_class"]}
    try:
        days = (datetime.now().date() - date.fromisoformat(str(snapshot)[:10])).days
    except ValueError:
        days = None
    waypoints = state["waypoints"]   # their route (Learn only while it's theirs)
    # an advisor's client: what their advisor left them first (client mode)
    client_step = _client_step(state, bool(positions))
    step = client_step or route.next_step(
        has_goal=has_goal, can_manage=CAN_MANAGE, profile_missing=bool(state["missing"]),
        has_holdings=bool(positions), monthly=monthly, goal=gp,
        drift=route.drifted(pct, load_alloc_targets(), load_drift_threshold()),
        days_since_holdings=days, waypoints=waypoints)
    reached = bool(gp and gp["status"] == "reached")
    title, text, button, action = (_client_step_words(step) if client_step else
                                   _route_words(step, gp, monthly, plan))

    with st.container(border=True, key="pt_route_reached" if reached else "pt_route"):
        # the investor type comes with an example mix - not beside an advisor's,
        # and only with gate L3 on (views/get_started.py _direction_kind)
        kind = None if CLIENT_MODE else _direction_kind(state["profile"], state["horizon"],
                                                         state["items"])
        head = ("<div class='pt-route-label'>"
                + ("Your next step, with your advisor" if CLIENT_MODE else "Your route")
                + (f" · {html.escape(kind['name'])}" if kind else "") + "</div>")
        if has_goal:
            label, tone = PLAN_STATUS[gp["status"]]
            share = min(100.0, max(0.0, gp["pct_of_target"] or 0.0))
            head += (f"<div class='pt-goal-top'><b>{html.escape(plan.get('goal_name') or plan['goal_type'] or 'Goal')}</b>"
                     f"<span class='pt-goal-pct'>{mask_or(f'{share:.0f}%')}</span>"
                     f"<span class='pt-chip {tone}'>{label}</span></div>"
                     f"<div class='pt-goal-track' role='progressbar' aria-label='Progress to your goal' "
                     f"aria-valuenow='{share:.0f}' aria-valuemin='0' aria-valuemax='100'>"
                     f"<div class='pt-goal-fill' style='width:{share:.1f}%'></div></div>"
                     f"<div class='pt-goal-sub'>{fmt_money0(gp['current'])} of "
                     f"{fmt_money0(gp['target'])} by {_fmt_month(plan['target_date'])}</div>")
        if not CLIENT_MODE:   # an advisor's client walks with their advisor, not a trail
            n_done = sum(1 for _, _, d in waypoints if d)
            # the route as a trail through the expedition's regions (route.py)
            head += route.trail_html(route.dots(waypoints, reached),
                                     f"{n_done} of {len(waypoints)} steps done, then "
                                     "your goal")
            head += _where_html(state)   # "You're in Start investing · step 2 of 4 · ..."
        st.html(head)
        with st.container(horizontal=True, vertical_alignment="center"):
            # "$" escaped: a pair of them would be read as a math formula
            st.markdown((f":material/flag: **Next: {title}**" + (f"  \n{text}" if text else ""))
                        .replace("$", r"\$"), width="stretch")
            st.button(button, key="route_go", type="primary", on_click=_route_go,
                      args=(action,))
            st.button(f"Ask {GUIDE}", key="route_ask", type="tertiary", on_click=_ask_route,
                      args=(step["key"],))




# ---- This month: the right-hand column (home_tasks.py) -------------------- #
# The things to do or look at this month, gathered in one column: each
# feature's own card, drawn as before. Cards that keep their own state (the
# walk, the weekly summary, the season, the storm note, the year card, the
# account map line) use it behind the same X; the rest get the X (and Done
# where it fits) here, kept as keys
# and the period's id in the login's own settings. An advisor in a client's
# account sees the same cards and writes nothing.

def _task_own():
    """Only the login's own settings are ever written (also in a callback)."""
    return USER_ID == LOGIN_ID


def _task_mark(key, mark):
    if not _task_own():
        return
    p = _read_prefs()
    new = home_tasks.with_mark(p, key, home_tasks.today(), mark)
    if new != p:
        _write_prefs(new)


def _task_bring_back():
    if not _task_own():
        return
    p = _read_prefs()
    new = home_tasks.cleared(p)
    if new != p:
        _write_prefs(new)


def _month_task(key, render):
    """One suggestion: the small X at its top right (put away until its
    period ends), its card, then Done where it has one - the X and Done for
    the login's own only. Put away or done this period: nothing."""
    if home_tasks.hidden(_read_prefs(), key, home_tasks.today()):
        return
    with st.container(key=f"pt_task_{key}"):
        if _task_own():
            st.button(":material/close:", key=f"task_away_{key}", type="tertiary",
                      help=home_tasks.away_help(key), on_click=_task_mark,
                      args=(key, home_tasks.AWAY))
        render()
        if _task_own() and home_tasks.TASKS[key][1]:
            with st.container(horizontal=True, gap="small", key=f"pt_tfoot_{key}"):
                st.button(home_tasks.DONE_LABEL, key=f"task_done_{key}", type="tertiary",
                          icon=":material/check:", help=home_tasks.DONE_HELP,
                          on_click=_task_mark, args=(key, home_tasks.DONE))


def _open_target_mix():
    st.session_state["plan_tab"] = "Target mix"
    _go("Plan")


def _mix_card(alloc):
    """The mix by asset class against its target, in percentages and whole
    points only - what the Plan's target mix says, never what to trade."""
    rows = alloc["by_asset_class"]
    targets = load_alloc_targets()
    hidden = _hidden()
    slots = _slot_map({r["label"] for r in rows}, CLASS_SLOT)
    colors = SERIES_DARK if st.context.theme.type == "dark" else SERIES_LIGHT
    segs = "".join(
        f"<div class='pt-alloc-seg' style='flex:{r['value']} 0 0;background:"
        f"{colors[slots[r['label']]] if slots.get(r['label']) is not None else SERIES_OTHER}'>"
        "</div>" for r in rows if (r["value"] or 0) > 0)
    summary = home_tasks.mix_summary(rows, masked=hidden)
    lines = (home_tasks.mix_lines({r["label"]: r["pct"] for r in rows}, targets,
                                  load_drift_threshold(), masked=hidden)
             if targets else [home_tasks.MIX_NO_TARGET])
    warn = bool(targets) and lines != [home_tasks.MIX_WITHIN]
    with st.container(border=True, key="pt_mix_card"):
        st.html(f"<div class='pt-month-card-title'>{home_tasks.MIX_TITLE}</div>"
                + ("" if hidden or not segs else
                   f"<div class='pt-alloc-bar pt-mini' aria-hidden='true'>{segs}</div>")
                + (f"<div class='pt-region'>{html.escape(summary)}</div>" if summary else "")
                + "".join(f"<div class='pt-region{' pt-warn' if warn else ''}'>"
                          f"{html.escape(ln)}</div>" for ln in lines))
        if CAN_MANAGE and "Plan" in PAGES:
            st.button(home_tasks.MIX_LINK, key="mix_open", type="tertiary",
                      on_click=_open_target_mix)


def _goal_card():
    """The goal in one line from the plan, or a way to set one (the advisor's
    own portfolio; the investor home has it in Your route)."""
    _plan = load_plan()
    with st.container(border=True, key="pt_goal_card"):
        if plans.has_goal(_plan):
            _gp = _goal_progress(_plan, portfolio_value)
            _glabel, _gtone = PLAN_STATUS[_gp["status"]]
            _gpct = mask_or(f"{_gp['pct_of_target'] or 0:.0f}%")
            st.html(f"<span class='pt-chip {_gtone}'>{_glabel}</span>&nbsp; "
                    f"<b>{html.escape(_plan.get('goal_name') or _plan['goal_type'] or 'Goal')}</b>"
                    f" · {_gpct} of "
                    f"{fmt_money0(_gp['target'])} by {_fmt_month(_plan['target_date'])}")
            st.button("Open plan", key="dash_open_plan", type="tertiary", on_click=_go,
                      args=("Plan",))
        elif CAN_MANAGE:
            st.markdown("Set a goal to see whether you're on track.")
            st.button("Set a goal", key="dash_set_goal", type="tertiary", on_click=_go,
                      args=("Plan",))
        else:
            st.markdown("Your advisor hasn't set a goal for you yet.")


def _month_cards(alloc):
    """This month's cards, most relevant first: [(name, draw)]. A draw may
    show nothing (nothing to say this time, or put away)."""
    cards = []
    if INVESTOR_VIEW and flags.on("money_minute") and _minute_shown():
        # today's minute: first, so first on a phone (views/money_minute.py)
        cards.append(("minute", lambda: _month_task("minute", render_minute_card)))
    cards.append(("storm", render_weather))   # a storm note while well below the high (T4)
    if INVESTOR_VIEW:
        cards.append(("walk", render_checkin_card))   # the Monthly Walk (views/checkin.py)
        cards.append(("route", lambda: _month_task("route", _render_route)))
        if flags.on("weekly"):
            cards.append(("weekly", render_weekly))   # Your week / The week ahead (views/weekly.py)
        if flags.on("seasons"):
            cards.append(("season", render_seasons_card))   # the Four Seasons (views/seasons.py)
    else:
        cards.append(("goal", _goal_card))
    if ON_CLIENT or IS_MANAGED_CLIENT:
        cards.append(("notes", _advisor_notes_card))
    cards.append(("mix", lambda: _month_task("mix", lambda: _mix_card(alloc))))
    if INVESTOR_VIEW:
        if flags.on("drills") and _drill_shown():
            # this week's drill (views/drills.py)
            cards.append(("drill", lambda: _month_task("drill", render_drill_card)))
        if flags.on("challenges") and _ch_shown() and _ch_month_key():
            cards.append(("challenge",   # views/challenges.py
                          lambda: _month_task("challenge", render_challenge_card)))
        # fee check, fund overlap and cash check in one card (views/cash_check.py)
        _checks = money_check_rows()
        if _checks:
            cards.append(("checks", lambda: _month_task("checks",
                                                        lambda: render_money_checks(_checks))))
        # 2+ accounts and no map yet (views/account_map.py); Year in review (views/year_review.py)
        cards.append(("amap", render_account_map_nudge))
        cards.append(("year", render_year_card))
        if flags.on("wins") and _wins_shown() and _wins_recent():
            # a win earned lately (views/wins.py)
            cards.append(("wins", lambda: _month_task("wins", render_wins_card)))
        if _kit_shown():
            cards.append(("kit", lambda: _month_task(   # views/kit.py
                "kit", lambda: render_kit_card(portfolio_value))))
    if flags.on("news_feed"):
        cards.append(("news", lambda: _month_task(   # views/news_feed.py
            "news", lambda: render_news_card(NEWS_ROWS))))
    return cards


def _drew(box, before):
    """Whether drawing into `box` added anything since its count was `before`
    (a card with nothing to say draws nothing)."""
    return _box_count(box) > before


def _box_count(box):
    """How many things are in a container so far (streamlit's own count of
    its children; a test pins it)."""
    return getattr(getattr(box, "_cursor", None), "index", 0)


def _render_this_month(alloc):
    """Home's right-hand column (a row of cards across on a phone): the
    first MONTH_LIMIT cards that have something to say, then "Show N more",
    which opens the rest in place. The rest are drawn either way (they read
    nothing more), just hidden until then."""
    today = home_tasks.today()
    st.html(f"<div class='pt-month-title'>{home_tasks.TITLE}</div>")
    opened = bool(st.session_state.get("month_all"))
    first = st.container(key="pt_month_cards", gap="small")
    rest = st.container(key="pt_month_more_open" if opened else "pt_month_more", gap="small")
    shown = extra = 0
    for _name, draw in _month_cards(alloc):
        box = first if shown < home_tasks.MONTH_LIMIT else rest
        before = _box_count(box)
        with box:
            draw()
        if _drew(box, before):
            if box is first:
                shown += 1
            else:
                extra += 1
    if extra:
        st.button(home_tasks.SHOW_FEWER if opened else home_tasks.SHOW_MORE.format(n=extra),
                  key="month_more", type="tertiary", on_click=_flip, args=("month_all",),
                  icon=":material/expand_less:" if opened else ":material/expand_more:")
    away = home_tasks.put_away(_read_prefs(), today)
    if away and _task_own():
        with st.container(horizontal=True, vertical_alignment="center", key="pt_month_away"):
            st.caption(home_tasks.PUT_AWAY_LINE.format(
                names=", ".join(home_tasks.NAMES[k] for k in away)), width="stretch")
            st.button(home_tasks.BRING_BACK, key="task_bring_back", type="tertiary",
                      on_click=_task_bring_back)
    if INVESTOR_VIEW:
        check_milestones(portfolio_value)


# ---- the holdings table under the chart ----------------------------------- #

def _holdings_columns():
    """The metrics the table shows after the ticker and its mini chart: the
    Columns choice (load_columns), the total-return ones only when some
    holding has dividends to add, and no dollar amounts or share counts for a
    percentages portfolio (they're pretend)."""
    if "col_keys" not in st.session_state:
        st.session_state["col_keys"] = load_columns()
    chosen = [M.BY_KEY[k] for k in st.session_state["col_keys"]
              if k in M.BY_KEY and k != "symbol"] \
        or [M.BY_KEY[k] for k in M.DEFAULT_KEYS if k != "symbol"]
    chosen = [m for m in chosen if m.key not in M.SHOWN_WHEN_KNOWN
              or any(M.value(m.key, ctx) is not None for ctx in contexts)]
    if SNAPSHOT_SOURCE == manual_entry.PCT_SOURCE:
        chosen = [m for m in chosen if m.fmt not in ("money", "qty")]
    return chosen


def _holdings_frame(rows, chosen):
    """(styled table, its column settings) for the positions at `rows`: the
    ticker, the past month and the chosen columns under short headings,
    numbers right-aligned and formatted (masked while amounts are hidden),
    gains and losses colored by the numbers themselves."""
    heads = [home_tasks.HEADINGS.get(m.key, m.label) for m in chosen]
    df = pd.DataFrame([[M.value(m.key, contexts[i]) for m in chosen] for i in rows],
                      columns=heads)
    fmt_map = {h: FORMATTERS[m.fmt] for h, m in zip(heads, chosen) if m.fmt in FORMATTERS}
    color_cols = [h for h, m in zip(heads, chosen) if m.color_sign]
    # The table draws an empty cell as a grey "None", whatever the format says:
    # a column with blanks (a holding entered without its cost) is shown as its
    # formatted text instead (still right-aligned, like numbers), "—" for the blanks.
    # While amounts are hidden every column is its masked text: the numbers
    # themselves never reach the page (the table's own copy and download).
    shown, config = df.copy(), {}
    for col in df.columns:
        if _hidden() or df[col].isna().any():
            fmt = fmt_map.pop(col, None)
            shown[col] = [fmt(v) if fmt else ("—" if _blank(v) else str(v)) for v in df[col]]
            if fmt:
                config[col] = st.column_config.TextColumn(col, alignment="right")
    # "Price as of" in words ("3:45 pm ET", "Oct 3 close" - price_report.as_of)
    asof_head = home_tasks.HEADINGS.get("price_at", M.BY_KEY["price_at"].label)
    if asof_head in shown.columns:
        asofs = [price_report.as_of(M.value("price_at", contexts[i]), price_report.kind(
            positions[i]["symbol"], positions[i].get("asset_type"),
            (contexts[i].get("info") or {}).get("quote_type"))) for i in rows]
        shown[asof_head] = [a["text"] if a else "—" for a in asofs]
    shown.insert(0, SPARK_LABEL, [_spark(positions[i]["symbol"]) for i in rows])
    shown.insert(0, "Ticker", [positions[i]["symbol"] for i in rows])
    config["Ticker"] = st.column_config.TextColumn("Ticker", pinned=True)
    if "Name" in shown.columns:
        config["Name"] = st.column_config.TextColumn("Name", width=150)
    styler = shown.style.format(fmt_map, na_rep="—")
    if color_cols:   # colored by the numbers, not the text shown
        styler = styler.apply(lambda s: [color_sign(v) for v in df[s.name]], subset=color_cols)
    return styler, config


def _render_holdings_table():
    """Home's holdings: one table in its card under the chart - headings, the
    ticker, the past month's mini chart and the chosen columns. The largest
    LIST_LIMIT rows first; "Show all" opens the rest in place, and a search
    shows every match. Tapping a row opens that ticker's own page
    (dashboard._ticker_table). Columns and Download CSV as before."""
    chosen = _holdings_columns()
    order = sorted(range(len(positions)),
                   key=lambda i: (-(M.eff_mv(contexts[i]) or 0.0), positions[i]["symbol"]))
    with st.container(border=True, key="pt_home_list", gap="small"):
        with st.container(horizontal=True, vertical_alignment="center", gap="small",
                          key="pt_hold_head"):
            st.html(f"<div class='pt-month-card-title'>{home_tasks.HOLDINGS_TITLE}</div>",
                    width="stretch")
            search = st.text_input("Search holdings", key="ticker_search",
                                   placeholder="Search", label_visibility="collapsed",
                                   width=150, icon=":material/search:")
            with st.popover("Columns", type="tertiary", icon=":material/view_column:"):
                # (the ticker is always the first column, so it isn't offered)
                kept = [k for k in st.session_state["col_keys"] if k in M.BY_KEY and k != "symbol"]
                labels = st.multiselect(
                    "Columns — add or remove as many as you want",
                    [m.label for m in M.AVAILABLE if m.key != "symbol"],
                    default=[M.BY_KEY[k].label for k in kept], key="col_labels")
                new_keys = [M.BY_LABEL[lbl].key for lbl in labels]
                if new_keys and new_keys != kept:
                    st.session_state["col_keys"] = new_keys
                    save_columns(new_keys)
                # any Yahoo history at all (what's already read shows it without asking)
                if not (_covered or bar_stats or perf.has_bars(DB)):
                    st.caption("The **Yahoo history** columns (MA, Volume, 52-wk, Beta, P/E, "
                               "Sector) stay blank until you tap sync history "
                               "(:material/history:) up top.")
        q = (search or "").strip().upper()
        if q:
            rows = [i for i in order if q in positions[i]["symbol"].upper()
                    or q in (positions[i].get("description") or "").upper()]
        elif st.session_state.get("home_hold_all"):
            rows = order
        else:
            rows = order[:home_tasks.LIST_LIMIT]
        if not rows:
            st.caption("No holding matches your search.")
        else:
            styler, config = _holdings_frame(rows, chosen)
            _ticker_table("home_table", styler, [positions[i]["symbol"] for i in rows],
                          "Dashboard", column_config=config,
                          alt="Your holdings, largest first: ticker, past month and the columns "
                              "you chose. Select a row to open that holding's page.")
        with st.container(horizontal=True, vertical_alignment="center", gap="small",
                          key="pt_hold_foot"):
            if not q and len(order) > home_tasks.LIST_LIMIT:
                _show_all_toggle("home_hold_all", len(order), home_tasks.HOLDINGS_NOUN)
            st.caption(home_tasks.HOLDINGS_TAP, width="stretch")
            # the CSV keeps every holding and the columns' full names
            st.download_button(
                "Download CSV",
                export.csv_bytes(pd.DataFrame(
                    [{"Symbol": p["symbol"], **{m.label: M.value(m.key, c) for m in chosen}}
                     for p, c in zip(positions, contexts)])),
                file_name="holdings.csv", mime="text/csv", key="holdings_dl",
                type="tertiary", icon=":material/download:",
                disabled=hide_amounts, help=(
                    "Disabled while amounts are hidden — turn off Hide amounts to export real "
                    "figures." if hide_amounts else None))


if PAGE == "Dashboard":
    # ---- hero: value, today's move, since last visit, headline stats ----- #
    _day_base = portfolio_value - day_change_total
    _day_pct = (day_change_total / _day_base * 100) if _day_base else None
    if hide_amounts:
        _day_html = f"{MASK} today"
    elif n_live:
        _arrow = (f"<span aria-hidden='true'>{'▲' if day_change_total >= 0 else '▼'}</span>"
                  f"<span class='pt-sr'>{'Up' if day_change_total >= 0 else 'Down'}</span>")
        _day_html = _tone(day_change_total, f"{_arrow} {fmt_money(abs(day_change_total))}"
                          + (f" ({_day_pct:+.2f}%)" if _day_pct is not None else "") + " today")
    else:
        _day_html = ""

    _since_html = ""
    _last_open = st.session_state["last_open_snapshot"]
    # Only when it's the same statement - a new import's jump is new holdings
    # data, not the market moving. Nothing changed (the market closed, or a
    # visit a minute ago): no "$0.00 (+0.00%)" line.
    if (_last_open and _last_open.get("portfolio_value")
            and _last_open.get("snapshot_date") == snapshot
            and abs(portfolio_value - _last_open["portfolio_value"]) >= 0.01):
        _prev_val = _last_open["portfolio_value"]
        _since_delta = portfolio_value - _prev_val
        _since_pct = (_since_delta / _prev_val * 100) if _prev_val else None
        _last_ts = pd.to_datetime(_last_open["logged_at"], utc=True).to_pydatetime()
        _secs = (datetime.now(timezone.utc) - _last_ts).total_seconds()
        if _secs < 3600:
            _ago = f"{max(1, int(_secs // 60))} min ago"
        elif _secs < 86400:
            _ago = f"{int(_secs // 3600)}h ago"
        else:
            _ago = f"{int(_secs // 86400)}d ago"
        _since_html = (f"Since your last visit ({_ago}): " + _signed_money(_since_delta)
                       + ("" if hide_amounts or _since_pct is None else f" ({_since_pct:+.2f}%)"))

    def _stat(label, value, sub=""):
        return (f"<div class='pt-stat' role='listitem'><div class='pt-stat-label'>{label}</div>"
                f"<div class='pt-stat-value'>{value}</div>"
                + (f"<div class='pt-stat-sub'>{sub}</div>" if sub else "") + "</div>")

    # the value and today's change on the band at the top (_page_header)
    with _HOME_HERO or st.container():
        st.html("<div class='pt-hero'>"
                "<div class='pt-hero-label'>Portfolio value</div>"
                f"<div class='pt-hero-value'>{fmt_money(portfolio_value)}</div>"
                + (f"<div class='pt-hero-delta'>{_day_html}</div>" if _day_html else "")
                + (f"<div class='pt-hero-sub'>{_since_html}</div>" if _since_html else "")
                + "</div>")

    # ---- the layout (Style C): the middle - the chart, then the holdings -
    # and "This month" on the right; one column on a phone, This month first
    _home_alloc = allocate(positions, cash_by_account, CLASS_SPLITS)
    with st.container(horizontal=True, gap="medium", key="pt_home_layout"):
        _home_main = st.container(key="pt_home_main")
        _home_side = st.container(key="pt_home_side")
    with _home_side:
        _render_this_month(_home_alloc)

    with _home_main:
        # ---- performance over time: the largest thing on Home --------- #
        with st.container(border=True, key="pt_home_chart"):
            p1, p2 = st.columns([0.65, 0.35])
            p1.subheader("Performance")
            series_col = p2.selectbox(
                "Series", [c for c, _, _ in perf.SERIES],
                index=[c for c, _, _ in perf.SERIES].index(load_perf_series()),
                format_func=lambda c: perf.SERIES_LABEL[c], key="perf_series_sel",
                label_visibility="collapsed",
            )
            if series_col != load_perf_series():
                save_perf_series(series_col)

            prng = st.segmented_control("Range", charts.RANGE_LABELS, default="1D",
                                        key="perf_range", label_visibility="collapsed") or "1D"

            # history() picks the reconstruction's resolution to match `prng`, exactly like
            # ticker_series() does for a single ticker (finest Yahoo interval that covers
            # the window). With only daily bars so far (right after the automatic
            # backfill, before the nightly intraday sync) a short range can come back
            # empty - then show the shortest wider range that has data, and say so.
            _shown_rng = prng
            _hist_conn = connect(DB)   # one connection for every range tried
            try:
                _hist = perf.history(_hist_conn, USER_ID, days=charts.RANGE_DAYS[prng],
                                     include_app_open=False, basis=PERF_BASIS)
                for _wider in charts.RANGE_LABELS[charts.RANGE_LABELS.index(prng) + 1:]:
                    if len(_hist) >= 2:
                        break
                    _shown_rng = _wider
                    _hist = perf.history(_hist_conn, USER_ID, days=charts.RANGE_DAYS[_wider],
                                         include_app_open=False, basis=PERF_BASIS)
            finally:
                _hist_conn.close()
            if _shown_rng != prng and len(_hist) >= 2:
                st.caption(f"No {prng} chart yet - showing {_shown_rng}. Prices through the day "
                           "are added each evening.")
            if len(_hist) < 2:
                st.caption("Your performance chart fills in once price history for your holdings has "
                           "loaded - it updates on its own every trading day.")
            else:
                _fmtname = perf.SERIES_FMT[series_col]
                y_title = perf.SERIES_LABEL[series_col]
                hist_df = pd.DataFrame(_hist)
                hist_df["t"] = pd.to_datetime(hist_df["t"], utc=True, format="mixed")
                pwin = hist_df.dropna(subset=[series_col]).sort_values("t")

                if len(pwin) < 2:
                    st.caption(f"No **{y_title}** recorded in this window yet.")
                else:
                    # Intraday-resolution data (minutes/hours apart) gets the gaps-compressed
                    # axis; daily-resolution data (~1 day apart, weekends aside) doesn't need it.
                    _pcompress = pwin["t"].diff().dt.total_seconds().median() < 20 * 3600

                    _pf, _pl, ppct = charts.window_change(pwin, "t", series_col)
                    pmcol, _ = st.columns([0.4, 0.6])
                    pmcol.metric(y_title, mask_or(FORMATTERS[_fmtname](_pl)),
                                 delta=(None if hide_amounts or ppct is None else f"{ppct:+.2f}% over {_shown_rng}"))

                    _ptips = [alt.Tooltip("t:T", title="When", format="%b %d, %Y  %H:%M")]
                    if not hide_amounts:
                        _ptips.append(alt.Tooltip(f"{series_col}:Q", title=y_title, format=TOOLTIP_FORMAT[_fmtname]))
                    st.altair_chart(
                        charts.line(
                            pwin, x="t", y=series_col, y_title=y_title, y_format=AXIS_FORMAT[_fmtname],
                            mask=hide_amounts, compress_gaps=bool(_pcompress),
                            line_color=(SERIES_DARK if st.context.theme.type == "dark" else SERIES_LIGHT)[0],
                            tooltip=_ptips),
                        width="stretch",
                    )
                    st.caption(
                        "Worked out from what you hold now and each day's closing prices. "
                        + (f"Past prices for {', '.join(_missing)} aren't here yet, so "
                           f"{'they are' if len(_missing) != 1 else 'it is'} left out of the "
                           "line for now." if _missing else "")
                    )

        if flags.on("progress_split"):
            render_progress_split()   # what you did vs what the market did (views/progress_split.py)

        _render_holdings_table()   # every holding, in one table under the chart

        st.html(_stat_row(
            "<div class='pt-stats' role='list' aria-label='Portfolio summary'>"
            # with dividends known: the price change, then the total return beside it
            + _stat("Price change" if tot_return else "Total gain/loss",
                    _tone(tot_gl, _signed_money(tot_gl)),
                    _tone(tot_glp, fmt_pct(tot_glp)) if tot_glp is not None else "")
            + (_stat("Total return, with dividends",
                     _tone(tot_return["usd"], _signed_money(tot_return["usd"])),
                     _tone(tot_return["usd"], fmt_pct(tot_return["pct"]))
                     if tot_return["pct"] is not None else "") if tot_return else "")
            + _stat("Holdings", fmt_money(tot_mv), f"{len(positions)} positions")
            + _stat("Cash", fmt_money(cash),
                    "" if hide_amounts or not portfolio_value
                    else f"{cash / portfolio_value * 100:.1f}% of total")
            + "</div>"
        ))
        if tot_return:
            # "$" escaped: two amounts would be read as a math formula
            st.caption((f"Total return adds the {fmt_money(tot_return['dividends'])} in dividends "
                        "your holdings paid to their price change. "
                        + income.source_words(DIVIDENDS[p["symbol"]]["source"]
                                              for p, c in zip(positions, contexts)
                                              if c["dividends"] and p["cost_basis"] is not None))
                       .replace("$", r"\$"))

        # ---- alerts: one line, open for the list and the limits ------------ #
        _rules = load_rules()
        _fired = alerts.evaluate(contexts, _rules)
        _alert_label = (f":red[:material/notifications_active:] **{len(_fired)} "
                        f"alert{'s' if len(_fired) != 1 else ''}** · holdings past the alert "
                        "limits (open to see or change them)"
                        if _fired else ":material/notifications: No alerts")
        with st.expander(_alert_label):
            for _a in _fired:
                st.markdown(_a.masked_message if hide_amounts else _a.message)
            if not _fired:
                st.caption("No position is past its day-move or gain/loss limit.")
            if CAN_MANAGE:
                st.markdown("**Limits**")
                _new = []
                for _col, _r in zip(st.columns(len(alerts.DEFAULT_RULES)), alerts.DEFAULT_RULES):
                    cur = next((x["abs_gt"] for x in _rules if x["key"] == _r["key"]), _r["abs_gt"])
                    val = _col.number_input(f"{_r['label']} — flag beyond ±%", min_value=0.0,
                                            max_value=1000.0, value=float(cur), step=0.5,
                                            key=f"rule_{_r['key']}")
                    _new.append({**_r, "abs_gt": val})
                if _new != _rules:
                    save_rules(_new)
                    st.rerun()
                st.caption("Checked against the latest prices every time the page loads.")
            else:
                st.caption("Limits set by your advisor: " + " · ".join(
                    f"{r['label']} beyond ±{r['abs_gt']:g}%" for r in _rules) + ".")

        st.divider()

        # ---- allocation ----------------------------------------------------- #
        alloc = allocate(positions, cash_by_account, CLASS_SPLITS)
        # What the bars group by: asset class (what's held - targets and drift use
        # this) or the broker's own asset type. One color per group across the page.
        _by_type = st.session_state.get("alloc_group") == "Broker type"
        _group = "by_asset_type" if _by_type else "by_asset_class"
        _asset_slots = _slot_map({r["label"] for r in alloc[_group]},
                                 ASSET_SLOT if _by_type else CLASS_SLOT)

        al1, al2 = st.columns([0.75, 0.25])
        al1.subheader("Allocation")
        if CAN_MANAGE:
            with al2.popover("Targets", width="stretch"):
                st.caption("Set a target % of portfolio for stocks, bonds, cash or other - leave "
                           "at 0 for no target.")
                _saved_targets = load_alloc_targets()
                _new_targets = {}
                for _lbl in asset_classes.CLASSES:
                    _new_targets[_lbl] = st.number_input(
                        _lbl, min_value=0.0, max_value=100.0, step=1.0,
                        value=float(_saved_targets.get(_lbl, 0.0)), key=f"target_{_lbl}")
                _new_thresh = st.number_input(
                    "Flag drift beyond ± this many percentage points", min_value=0.5, max_value=50.0,
                    step=0.5, value=load_drift_threshold(), key="drift_threshold_input")
                if {k: v for k, v in _new_targets.items() if v} != _saved_targets:
                    save_alloc_targets(_new_targets)
                if _new_thresh != load_drift_threshold():
                    save_drift_threshold(_new_thresh)
        if flags.on("plain_summary") and not hide_amounts:
            # the mix in plain words: fixed templates, no AI (allocation.py)
            _plain = summary_words(alloc, positions)
            if _plain:
                st.markdown(_plain)
        st.segmented_control("Group by", ["Asset class", "Broker type"], default="Asset class",
                             key="alloc_group", label_visibility="collapsed",
                             help="Asset class is what holdings hold - a bond ETF counts as bonds. "
                                  "Broker type is how the statement labels them.")

        _title = "By broker type" if _by_type else "By asset class"
        if len(alloc["by_account"]) > 1:
            a1, a2 = st.columns(2, gap="large")
            a1.html(_alloc_bar(alloc[_group], _title, _asset_slots))
            a2.html(_account_mix(alloc["by_account"], positions, cash_by_account, _asset_slots,
                                 _group))
        else:
            st.html(_alloc_bar(alloc[_group], _title, _asset_slots))
        _render_classification(positions)

        if alloc["concentration"]:
            lines = "  \n".join(
                f"- **{r['symbol']}** ({r['account']}) — {fmt_money(r['value'])}, "
                + (MASK if hide_amounts else f"**{r['pct']:.1f}%**") + " of portfolio"
                for r in alloc["concentration"]
            )
            st.warning(f"Positions over {CONCENTRATION_PCT:.0f}% of portfolio value:  \n{lines}")
        else:
            st.caption(f"No single position exceeds {CONCENTRATION_PCT:.0f}% of portfolio value.")
        learn_more("diversification")
        what_this_means("Asset class", "Asset allocation", "Concentration", "Diversification",
                        "Drift", "Band", "Rebalancing", key="gloss_home")

        _targets = load_alloc_targets()
        if _targets:
            _thresh = load_drift_threshold()
            _pct_by_label = {r["label"]: r["pct"] for r in alloc["by_asset_class"]}
            _drift = []
            for _lbl, _target in _targets.items():
                _actual = _pct_by_label.get(_lbl, 0.0) or 0.0
                _delta = _actual - _target
                if abs(_delta) > _thresh:
                    _drift.append((_lbl, _actual, _target, _delta))
            _drift.sort(key=lambda r: abs(r[3]), reverse=True)
            if _drift:
                lines = "  \n".join(
                    f"- {'▲' if d > 0 else '▼'} **{lbl}** — "
                    + (MASK if hide_amounts else f"{actual:.1f}% vs {target:.1f}% target ({d:+.1f} pts)")
                    for lbl, actual, target, d in _drift
                )
                st.warning(f"Drifted beyond ±{_thresh:g} pts from target:  \n{lines}")
                _dep = deposit_line(alloc["by_asset_class"], _targets)   # views/next_deposit.py
                if _dep:
                    with st.container(horizontal=True, vertical_alignment="center"):
                        st.caption(f":material/savings: {_dep}", width="stretch")
                        st.button("Where it could go", key="dash_deposit", type="tertiary",
                                  on_click=_open_deposit_tab)
            else:
                st.caption(f"Every targeted asset class is within ±{_thresh:g} pts of target.")
            learn_more("rebalancing")

        st.divider()

        ac1, ac2, ac3 = st.columns([0.5, 0.25, 0.25])
        ac1.subheader("Accounts")
        # the broker's own names, recovered from the display names in use
        _to_broker = {v: k for k, v in ACCOUNT_LABELS.items()}
        _broker_accts = sorted({p["broker_account"] for p in positions}
                               | {_to_broker.get(a, a) for a in cash_by_account})
        if CAN_MANAGE:
            with ac2.popover("Rename", width="stretch"):
                with st.form("rename_accounts", border=False):
                    st.caption("Give an account a name you'll recognize. Leave blank to use the "
                               "broker's name.")
                    _typed = {a: st.text_input(a, value=ACCOUNT_LABELS.get(a, ""), placeholder=a,
                                               max_chars=accounts.MAX_LEN, key=f"acct_name_{a}")
                              for a in _broker_accts}
                    if st.form_submit_button("Save names", type="primary"):
                        _proposed = {a: n.strip() for a, n in _typed.items() if n.strip()}
                        _bad = next((a for a in _broker_accts
                                     if accounts.clash(a, _proposed.get(a, a), _broker_accts, _proposed)), None)
                        if _bad:
                            st.error(f"Two accounts can't share the name "
                                     f"“{accounts.display(_bad, _proposed)}”.")
                        else:
                            _c = connect(DB)
                            try:
                                for a in _broker_accts:
                                    if _proposed.get(a) != ACCOUNT_LABELS.get(a):
                                        accounts.set_label(_c, USER_ID, a, _proposed.get(a))
                            finally:
                                _c.close()
                            st.rerun()

        _acct_stats = {}
        for _p, _ctx in zip(positions, contexts):
            _a = _p["account"]
            _s = _acct_stats.setdefault(_a, {"mv": 0.0, "cost": 0.0, "gain": 0.0, "day_change": 0.0, "n": 0})
            _mv = M.eff_mv(_ctx)
            if _mv is not None:
                _s["mv"] += _mv
                _s["n"] += 1
                _cost = _p["cost_basis"]
                if _cost is not None:
                    _s["cost"] += _cost
                    _s["gain"] += _mv - _cost
                _dchg = M.value("day_change_usd", _ctx)
                if _dchg is not None:
                    _s["day_change"] += _dchg

        _all_accounts = sorted(set(list(_acct_stats) + list(cash_by_account)))
        _acct_rows = []
        for _a in _all_accounts:
            _s = _acct_stats.get(_a, {"mv": 0.0, "cost": 0.0, "gain": 0.0, "day_change": 0.0, "n": 0})
            _csh = cash_by_account.get(_a, 0.0) or 0.0
            _total = _s["mv"] + _csh
            _acct_rows.append({
                "account": _a, "total": _total, "holdings": _s["mv"], "cash": _csh,
                "gain_usd": _s["gain"], "gain_pct": (_s["gain"] / _s["cost"] * 100) if _s["cost"] else None,
                "day_change": _s["day_change"], "n_positions": _s["n"],
                "pct_of_portfolio": (_total / portfolio_value * 100) if portfolio_value else None,
            })
        _acct_rows.sort(key=lambda r: r["total"], reverse=True)

        if CAN_IMPORT and len(_broker_accts) > 1:
            # Updating one account never removes another (an import replaces only
            # the accounts in it), so taking one out is done here, on purpose.
            with ac3.popover("Remove", width="stretch"):
                _worth = {_to_broker.get(r["account"], r["account"]): r["total"] for r in _acct_rows}
                st.caption("Take an account out of your holdings - one you closed or moved. Your "
                           "other accounts stay as they are, and its past stays in your history.")
                _rm = st.selectbox("Account to remove", _broker_accts, key="acct_rm_pick",
                                   format_func=lambda a: accounts.display(a, ACCOUNT_LABELS))
                _ok = st.checkbox(f"Yes, remove {accounts.display(_rm, ACCOUNT_LABELS)} "
                                  f"({fmt_money(_worth.get(_rm, 0.0))})".replace("$", r"\$"),
                                  key=f"acct_rm_ok_{_rm}")   # asked again for another account
                st.button("Remove this account", key="acct_rm_btn", type="primary",
                          disabled=not _ok, on_click=_remove_account, args=(_rm,))

        if len(_acct_rows) < 2:
            st.caption("Only one account in this portfolio — nothing to compare yet.")
        else:
            _adf_raw = pd.DataFrame(_acct_rows)
            _adf = pd.DataFrame([{
                "Account": r["account"], "Total Value": fmt_money(r["total"]),
                "% of Portfolio": fmt_pct_level(r["pct_of_portfolio"]), "Holdings": fmt_money(r["holdings"]),
                "Cash": fmt_money(r["cash"]), "Gain/Loss": fmt_money(r["gain_usd"]),
                "Gain/Loss %": fmt_pct(r["gain_pct"]), "Today": fmt_money(r["day_change"]),
                "Positions": r["n_positions"],
            } for r in _acct_rows])
            _gain_raw = [r["gain_usd"] for r in _acct_rows]
            _today_raw = [r["day_change"] for r in _acct_rows]
            _acct_styler = (
                _adf.style
                .apply(lambda col: [color_sign(v) for v in _gain_raw], subset=["Gain/Loss"])
                .apply(lambda col: [color_sign(v) for v in _today_raw], subset=["Today"])
            )
            st.dataframe(_acct_styler, width="stretch", hide_index=True)
            st.download_button(
                "Download CSV", export.csv_bytes(_adf_raw),
                file_name="accounts.csv", mime="text/csv", key="accounts_dl",
                disabled=hide_amounts, help=(
                    "Disabled while amounts are hidden — turn off Hide amounts to export real figures."
                    if hide_amounts else None),
            )
        learn_more("account_types")
