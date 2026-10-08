# Part of dashboard.py, which runs this file with _view("seasons") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what
# this defines is visible there afterwards. See _view() in dashboard.py.
#
# The Four Seasons (ROADMAP R7, seasons.py), behind flag seasons
# (flags.FEATURES - this whole file is skipped while it's off): four fixed
# moments in the year - January, April, October-November, December - each
# with something worth a look that isn't the balance.
# - Home (views/dashboard_page.py calls render_seasons_card): while a season
#   is on, a short card (its title, one line, "Take a look" and an X that
#   puts it away); once opened, one quiet line; put away, nothing until the
#   next season. Its contents open in a large window (_ss_window), never in
#   the narrow column.
# - Learn (views/get_started.py calls render_seasons_learn): one line any
#   time, opening any of the four.
# What's kept: per season, opened or put away (prefs seasons.PREF) - never
# free text. Only the login's own (USER_ID == LOGIN_ID): never drawn while an
# advisor is in a client's account, never sent to the AI. Education only:
# official links, dated figures shown only in their own tax year, "check with
# your plan or a tax professional".
# ruff: noqa: F821

import future_notes
import seasons


def _ss_own():
    """Only ever the login's own (also in a callback, a run later)."""
    return USER_ID == LOGIN_ID


def _ss_today():
    return seasons.today()


def _ss_md(text):
    """Text for st.markdown: dollar signs aren't a formula."""
    return str(text).replace("$", r"\$")


def _ss_links(links):
    st.markdown("  \n".join(f"[{t}]({u})" for t, u in links))


def _ss_go(where, opener, *args):
    """Open another window from a season's contents - straight away on
    Learn, by way of _ss_then from Home's season window."""
    if where == "home":
        _ss_then(lambda: opener(*args))
    else:
        opener(*args)


def _ss_mark(sid, status):
    if not _ss_own() or not sid:
        return
    p = _read_prefs()
    new = seasons.with_status(p, sid, status)
    if new != p:
        _write_prefs(new)


def _ss_open(where, key):
    st.session_state[f"ss_open_{where}"] = key
    sid = seasons.season_id(_ss_today())
    if sid and sid.endswith(f"-{key}"):
        _ss_mark(sid, seasons.SEEN)


def _ss_close(where):
    st.session_state.pop(f"ss_open_{where}", None)


def _ss_put_away(sid):
    _ss_mark(sid, seasons.PUT_AWAY)
    _ss_close("home")


def _ss_limits(lead, keys):
    year = _ss_today().year
    shown = seasons.limits_for(year, keys)
    if not shown:
        return False
    st.markdown(f"**{lead.format(year=year)}**  \n"
                + "\n".join(f"- {what}: {_ss_md(figs)}" for _k, what, figs, _u in shown))
    st.caption(f"For the {seasons.LIMITS_YEAR} tax year, from the IRS pages linked here "
               f"(checked {_fmt_date(seasons.LIMITS_CHECKED)}).")
    return True


def _ss_fee_bill(where):
    """January's fee bill from the Fee check's own figures (views/fees.py)."""
    st.markdown(f"**{seasons.FEE_TITLE}**")
    bill, plan = None, None
    if where == "home" or st.session_state.get("gs_has_holdings"):
        plan = load_plan()
        bill = seasons.fee_bill(_fee_check(), _ss_today(),
                                plan.get("target_date") if plans.has_goal(plan) else None)
    if not bill:
        st.markdown(_ss_md(seasons.FEE_NONE))
        return
    line = (f"Your funds' fees come to about {fmt_money0(bill['yearly'])} a year at today's "
            "value" + (f" ({fees.fmt_ratio(bill['ratio'])} of what those funds hold)."
                       if bill["ratio"] is not None else "."))
    if bill["years"]:
        line += (f" If that stayed the same until your goal date, {_fmt_month(plan['target_date'])} "
                 f"- about {bill['years']} year{'s' if bill['years'] != 1 else ''} - and the "
                 f"money grew {bill['growth'] * 100:.0f}% a year (the Fee check's assumption, "
                 "not a forecast), the fees and the growth they'd have earned would add up to "
                 f"about {fmt_money0(bill['total'])}.")
    st.markdown(_ss_md(line))
    if st.button("Fee check", key=f"ss_fees_{where}", type="tertiary",
                 icon=":material/open_in_new:"):
        _ss_go(where, open_fee_window)   # views/fees.py


def _ss_january(where):
    for p in seasons.JAN_PARAS:
        st.markdown(_ss_md(p))
    if not _ss_limits(seasons.JAN_LIMITS_LEAD, ("ira", "401k", "hsa")):
        st.markdown(_ss_md(seasons.JAN_NO_LIMITS))
    for p in seasons.JAN_MORE:
        st.markdown(_ss_md(p))
    _ss_fee_bill(where)
    _ss_links(seasons.LINKS["january"])


def _ss_april(where):
    for p in seasons.APRIL_PARAS:
        st.markdown(_ss_md(p))
    st.markdown("\n".join(f"- **{form}** - {_ss_md(words)} [About it]({url})"
                          for form, words, url in seasons.FORMS))
    for p in seasons.APRIL_MORE:
        st.markdown(_ss_md(p))
    _ss_links(seasons.APRIL_LINKS)


def _ss_enrollment(where):
    for p in seasons.FALL_PARAS:
        st.markdown(_ss_md(p))
    _ss_limits(seasons.FALL_LIMITS_LEAD, ("hsa",))
    _ss_links(seasons.LINKS["enrollment"])
    with st.container(horizontal=True):
        if st.button("Free money check", key=f"ss_match_{where}", type="tertiary",
                     icon=":material/redeem:"):
            _ss_go(where, open_free_money_window)   # views/free_money.py
        if flags.on("decoder_401k") and st.button(
                "Decode a 401(k) menu", key=f"ss_decoder_{where}", type="tertiary",
                icon=":material/list_alt:"):
            _ss_go(where, open_decoder_window)   # the 401(k) Menu Decoder (views/menu_decoder.py)


def _ss_letter(where):
    st.markdown(f"**{seasons.LETTER_TITLE}**")
    c = connect(DB)
    try:
        note = future_notes.get(c, USER_ID, future_notes.PLAN)
    finally:
        c.close()
    if note:
        st.markdown(seasons.LETTER_BACK)
        st.html(_fn_quote_html(note))   # views/future_notes.py (escaped)
    else:
        st.markdown(_ss_md(seasons.LETTER_NONE))
    st.button("Open Plan", key=f"ss_plan_{where}", type="tertiary",
              icon=":material/edit_note:", on_click=_go, args=("Plan",))


def _ss_december(where):
    today = _ss_today()
    for p in seasons.DEC_PARAS:
        st.markdown(_ss_md(p))
    if st.button(f"Your {today.year} so far", key=f"ss_year_{where}", type="tertiary",
                 icon=":material/auto_stories:"):
        _ss_go(where, _year_open, today.year)   # Year in review (views/year_review.py)
    _ss_letter(where)
    if seasons.rmd_may_apply(_profile().get("age_range")):
        st.markdown(f"**{seasons.RMD_TITLE}**  \n{_ss_md(seasons.rmd_text(today.year))}")
        dated = seasons.dated_line(today.year)
        if dated:
            st.caption(dated)
        _ss_links(seasons.LINKS["december"])   # the IRS's RMD page, with the note only


_SS_BODY = {"january": _ss_january, "april": _ss_april, "enrollment": _ss_enrollment,
            "december": _ss_december}


def _ss_body(key, where):
    _SS_BODY[key](where)
    st.caption(f":material/info: {seasons.CHECK} {seasons.NOT_ADVICE}")


def render_seasons_card():
    """Home: the season's card while it's on and new, one quiet line once
    opened, nothing once put away (or between seasons)."""
    if not _ss_own():
        return
    today = _ss_today()
    state = seasons.home_state(_read_prefs().get(seasons.PREF), today)
    if not state:
        return
    key, sid = seasons.season_of(today), seasons.season_id(today)
    _k, _m, title, icon, why = seasons.BY_KEY[key]
    then = st.session_state.pop("ss_then", None)
    is_open = st.session_state.get("ss_open_home") == key
    if state == "line":
        with st.container(horizontal=True, vertical_alignment="center", key="pt_season_line"):
            st.caption(f"{title} - {why}", width="stretch")
            st.button("This season", key="ss_open_home_btn", type="tertiary", icon=icon,
                      on_click=_ss_open, args=("home", key))
    else:
        # in the column: the title, one line and Take a look; the X puts it
        # away until the next season. The guide itself opens in a window.
        with st.container(border=True, key="pt_season_card"):
            st.button(":material/close:", key="ss_later", type="tertiary",
                      help="Put away until next season", on_click=_ss_put_away, args=(sid,))
            st.markdown(f"**{title}**")
            st.caption(why)
            st.button("Take a look", key="ss_open_home_btn", type="primary", icon=icon,
                      on_click=_ss_open, args=("home", key))
    if then and _dialog_free():   # a button in the season's window: that window instead
        st.session_state["dialog_open"] = True
        then()
    elif is_open and _dialog_free():
        st.session_state["dialog_open"] = True   # live prices wait (_dialog_closed)
        _ss_window(key)


def _ss_window_closed():
    _ss_close("home")
    _dialog_closed()


def _ss_then(opener):
    """A button inside the season's window that opens another window (the
    Fee check, the free money check, the Menu Decoder, Year in review): one
    window at a time, so this one closes and that one opens in its place."""
    _ss_close("home")
    st.session_state["ss_then"] = opener
    st.rerun()


@st.dialog("This season", width="large", on_dismiss=_ss_window_closed)
def _ss_window(key):
    """The season's guide in a window wide enough to read: its title, the
    short sections as on Learn, the official links at the end, then Close."""
    _k, _m, title, icon, why = seasons.BY_KEY[key]
    with st.container(key="pt_ss_read"):
        st.markdown(f"### {icon} {title}")
        st.caption(why)
        _ss_body(key, "home")
        if st.button("Close", key="ss_close_home", type="secondary"):
            _ss_window_closed()
            st.rerun()


def _ss_learn_pick():
    pick = st.session_state.get("ss_pick_learn")
    if pick:
        _ss_open("learn", pick)


def render_seasons_learn():
    """Learn: one line any time - this season, or the next one coming - and
    any of the four inline."""
    if not _ss_own():
        return
    today = _ss_today()
    now = seasons.season_of(today)
    key = now or seasons.next_season(today)[0]
    lead = "This season" if now else f"Coming up in {seasons.when_label(key)}"
    is_open = st.session_state.get("ss_open_learn")
    with st.container(border=True, key="pt_season_learn"):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(f":material/calendar_month: **The four seasons** - {seasons.INTRO} "
                        f"{lead}: {seasons.BY_KEY[key][2]}.", width="stretch")
            if is_open:
                st.button("Close", key="ss_close_learn", type="tertiary",
                          on_click=_ss_close, args=("learn",))
            else:
                st.button("Take a look", key="ss_open_learn_btn", type="tertiary",
                          icon=":material/open_in_new:", on_click=_ss_open,
                          args=("learn", key))
        if is_open:
            st.session_state["ss_pick_learn"] = is_open
            st.pills("Season", seasons.KEYS, key="ss_pick_learn", label_visibility="collapsed",
                     on_change=_ss_learn_pick, required=True,
                     format_func=lambda k: f"{seasons.BY_KEY[k][2].split(':')[0]}")
            st.markdown(f"**{seasons.BY_KEY[is_open][2]}**")
            _ss_body(is_open, "learn")
