# Part of dashboard.py, which runs this file with _view("first_month") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Your first month (first_month.py, flag first_month): one card in Home's "This
# month" while the account is young and a step is still open - the five steps
# as a short checklist and the next one as a button. An individual's own
# account only: never an advisor, never client mode (an advisor's client, or
# an advisor in a client's account). Not owned by its flag (the gear's button
# and the cost tools call in here), so each place checks on("first_month").
# Kept: only which cost tool was opened (first_month.PREF, keys only).
# ruff: noqa: F821

import first_month
import home_tasks


def _fmo_shown():
    """An individual on their own account, with the flag on."""
    return (flags.on("first_month") and not IS_ADVISOR and not CLIENT_MODE
            and USER_ID == LOGIN_ID)


def first_month_note(what):
    """A cost tool was opened (first_month.USED): remember its key in the
    login's own settings - never from an advisor's session, never a figure."""
    if not _fmo_shown():
        return
    p = _read_prefs()
    if first_month.note_used(p, what):
        _write_prefs(p)


def _fmo_age():
    """Days since this login was made (read once per browser session)."""
    key = ("first_month_made", LOGIN_ID)
    if key not in st.session_state:
        c = connect(DB)
        try:
            row = auth.account_row(c, LOGIN_ID)   # (the Account page's own read)
        finally:
            c.close()
        st.session_state[key] = str(row["created_at"]) if row and row["created_at"] else None
    return first_month.age_days(st.session_state[key], datetime.now().date())


def _fmo_facts(state):
    """first_month.checklist()'s facts - the gear's own (views/kit.py), so a
    step and its piece of gear never disagree."""
    p = _read_prefs()
    return {"profile_done": state["done"]["profile"],
            "practice_done": state["done"]["practice"],
            "costs_checked": first_month.costs_checked(p),
            "goal_set": state["done"]["goal"],
            "first_walk": first_month.first_walk(p)}


def _fmo_has_funds():
    """Funds held to check the fees of (views/fees.py)."""
    try:
        return bool(HAS_REAL_HOLDINGS and positions) and fees.has_funds(_fee_check())
    except NameError:   # not on Home (positions are Home's)
        return False


def _fmo_context(state):
    invest = route.stage_keys(route.INVEST)
    return {"has_funds": _fmo_has_funds(), "walk_due": _checkin_due(),
            "real_holdings": bool(HAS_REAL_HOLDINGS),
            "invest_next": next((k for k in invest if not state["done"].get(k)), None)}


def _fmo_go(where):
    kind, target = where
    if kind == "checkin":   # Home, with this month's walk open (views/checkin.py)
        st.session_state["checkin_open"] = True
        _go("Dashboard")
    else:                   # that waypoint open on Learn
        st.session_state["gs_at"] = target
        st.session_state.pop("gs_goal_part", None)
        _go("Get started")


def _fmo_open_costs():
    """The Fee check when there are funds to check, else Learn the basics,
    where "Fees add up" is."""
    if _fmo_has_funds():
        open_fee_window()   # views/fees.py
    else:
        _fmo_go(("learn", "basics"))
        st.rerun()


def first_month_pending():
    """The binoculars' button in the kit asked for the Fee check (views/kit.py
    _gear_go): open it now, on Home, if no other window has opened."""
    if st.session_state.get("first_month_costs") and _dialog_free():
        st.session_state.pop("first_month_costs", None)
        _fmo_open_costs()


def _fmo_mark(mark):
    """The card's X (put away until next week) or Done - the login's own
    settings only (home_tasks.py: the key, the week's id and the mark)."""
    if USER_ID != LOGIN_ID:
        return
    p = _read_prefs()
    new = home_tasks.with_mark(p, first_month.TASK, home_tasks.today(), mark)
    if new != p:
        _write_prefs(new)


def render_first_month_card(on_home=True):
    """"Your first month": the steps, what's done, and the next one as a
    button. `on_home`: in Home's This month, with its X and Done like the
    other cards (home_tasks.py); False on the not-investing-yet Home
    (views/start_home.py), where the cards around it have neither."""
    if not _fmo_shown():
        return
    if on_home and home_tasks.hidden(_read_prefs(), first_month.TASK, home_tasks.today()):
        return
    state = _route_state(HAS_HOLDINGS)
    steps = first_month.checklist(_fmo_facts(state), walk=flags.on("walk"))
    if not first_month.shown(_fmo_age(), steps):
        return
    ctx = _fmo_context(state)
    words = first_month.lines(steps, has_funds=ctx["has_funds"], walk_due=ctx["walk_due"],
                              real_holdings=ctx["real_holdings"])
    nxt = first_month.current(steps)
    items = "".join(
        f"<li class='pt-fm-item{' pt-fm-done' if done else ''}"
        f"{' pt-fm-next' if title == words['next'] else ''}'>"
        f"<span class='pt-fm-mark' aria-hidden='true'>{'&#10003;' if done else '&#9675;'}</span>"
        f"<span class='pt-fm-title'>{html.escape(title)}"
        f"<span class='pt-sr'>{' (done)' if done else ' (not done yet)'}</span></span>"
        f"<span class='pt-fm-when'>{html.escape(when)}</span></li>"
        for when, title, done in words["items"])
    with st.container(key=f"pt_task_{first_month.TASK}" if on_home else "pt_first_month_start"):
        if on_home:
            st.button(":material/close:", key=f"task_away_{first_month.TASK}", type="tertiary",
                      help=home_tasks.away_help(first_month.TASK), on_click=_fmo_mark,
                      args=(home_tasks.AWAY,))
        with st.container(border=True, key="pt_first_month"):
            st.html(f"<div class='pt-month-card-title'>{html.escape(words['title'])}</div>"
                    f"<div class='pt-region pt-fm-intro'>{html.escape(words['intro'])}</div>"
                    f"<div class='pt-route-label'>{html.escape(words['count'])}</div>"
                    f"<ul class='pt-fm-list' aria-label='{html.escape(words['title'], quote=True)}'>"
                    f"{items}</ul>"
                    f"<div class='pt-region'>{html.escape(words['why'])}</div>"
                    f"<div class='pt-region pt-fm-intro'>{html.escape(words['gear'])}</div>")
            go = first_month.action(nxt["key"], **ctx)
            if go:
                label, where = go
                if where[0] == "fees":   # a window: opened in this run
                    if st.button(label, key="first_month_go", type="primary"):
                        _fmo_open_costs()
                else:
                    st.button(label, key="first_month_go", type="primary", on_click=_fmo_go,
                              args=(where,))
        if on_home:
            with st.container(horizontal=True, gap="small", key=f"pt_tfoot_{first_month.TASK}"):
                st.button(home_tasks.DONE_LABEL, key=f"task_done_{first_month.TASK}",
                          type="tertiary", icon=":material/check:", help=home_tasks.DONE_HELP,
                          on_click=_fmo_mark, args=(home_tasks.DONE,))

