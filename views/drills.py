# Part of dashboard.py, which runs this file with _view("drills") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Preparedness drills (ROADMAP R12, the one-week test; drills.py), behind flag
# drills (flags.FEATURES - this whole file is skipped while it's off, so its
# callers check on("drills")). One small card on Home, just under Your kit
# (views/dashboard_page.py, and views/start_home.py for someone not investing
# yet): this week's drill - a situation, their own mix and timeline in
# percentages and words, then taps for what they'd weigh, never a trade and
# never graded - and the readiness map. One drill a week; no reminders, no
# emails. What they tapped is kept in their own settings (prefs drills: keys
# only) and is theirs: never drawn while an advisor is in a client's account
# (_kit_shown, views/kit.py), never in an advisor's client record, never sent
# to the AI.
# ruff: noqa: F821

import drills
import feature_counts
import flags


def _drill_shown():
    """The kit's rule: an investor (or a client) on their own account - also
    checked in the callback, a run later."""
    return flags.on("drills") and _kit_shown()


def _drill_today():
    return datetime.now().date()


def _drill_mix():
    """Their mix by asset class in whole percents, from their own holdings -
    None for someone with no real holdings yet (the example portfolio isn't
    theirs) or with amounts hidden, so the drill is the beginner version."""
    if not HAS_REAL_HOLDINGS or SNAPSHOT_SOURCE == SAMPLE_SOURCE or not positions:
        return None
    if st.session_state.get("hide_amounts"):
        return None
    try:
        rows = allocate(positions, cash_by_account, CLASS_SPLITS)["by_asset_class"]
    except Exception:  # noqa: BLE001 - no mix: the drill just leaves it out
        return None
    return {r["label"]: r["pct"] for r in rows if r.get("pct") is not None} or None


def _drill_years():
    """Years to their goal's date, else their profile's timeline answer."""
    plan = load_plan()
    today = _drill_today()
    if plans.has_goal(plan):
        months = plans.months_until(plan["target_date"], today)
        if months > 0:
            return months / 12
    try:
        return float(_profile().get("time_horizon_years") or 0) or None
    except (TypeError, ValueError):
        return None


def _drill_open():
    st.session_state["drill_open"] = True


def _drill_tap(key, choice):
    """A tap: keep this week's drill and the key of what they'd weigh."""
    if not _drill_shown():
        return
    p = _read_prefs()
    if drills.record(p, key, choice, _drill_today()):
        _write_prefs(p)
        st.session_state["drill_open"] = True   # the note after the tap stays in view


def _drill_map_html(p):
    """The readiness map: rehearsed or not yet, hard times and good times."""
    cols = []
    for _side, label, items in drills.readiness(p):
        lis = "".join(
            f"<li>{'&#10003;' if done else '&#9675;'} {html.escape(title)} "
            f"<span class='pt-region'>{'rehearsed' if done else 'not yet'}</span></li>"
            for _k, title, done in items)
        cols.append(f"<div style='flex:1 1 12rem'><b>{html.escape(label)}</b>"
                    f"<ul style='list-style:none;padding:0;margin:.2rem 0'>{lis}</ul></div>")
    return ("<div style='display:flex;flex-wrap:wrap;gap:.6rem 1.2rem'>"
            + "".join(cols) + "</div>")


def _render_drill_map(p):
    n = drills.count(p)
    with st.expander("Your readiness map", icon=":material/map:"):
        st.html(f"<div class='pt-region'>{n} of {len(drills.KEYS)} situations rehearsed</div>"
                + _drill_map_html(p))
        st.caption("Each situation you've thought through is marked. You can do them in "
                   "any order, at your own pace. Only you can see this"
                   + (" - unless you choose to bring it to your advisor (Account)."
                      if IS_MANAGED_CLIENT and flags.on("advisor_pack") else "."))


def render_drill_card():
    """Home's preparedness drill: this week's one, small and calm - a line
    and a button in the column; the situation, the taps and what they'd weigh
    open in a window (_drill_window); done, next week's day."""
    if not _drill_shown():
        return
    p = _read_prefs()
    today = _drill_today()
    key, repeat = drills.suggested(p, today)
    done_key = drills.done_this_week(p, today)
    weeks = drills.weeks_rehearsed(p)
    with st.container(border=True, key="pt_drill"):
        st.html("<div class='pt-eyebrow' style='margin:0'>This week's drill</div>"
                f"<div><b>{html.escape(drills.title_of(key))}</b>"
                + (" <span class='pt-region'>· again, with a twist</span>" if repeat else "")
                + "</div>"
                + (f"<div class='pt-region'>{html.escape(drills.weeks_text(weeks))}</div>"
                   if weeks else ""))
        if flags.on("month_world"):
            render_month_world()   # this month's world, if there's a note (views/month_world.py)
        if done_key:
            st.caption("Done for this week. The next one is ready on "
                       f"{_fmt_date(drills.next_week_start(today).isoformat())}.")
        else:
            st.caption(drills.INTRO)
            st.button("Try this week's drill", key="drill_start", icon=":material/explore:",
                      on_click=_drill_open)
        _render_drill_map(p)
    if st.session_state.get("drill_open") and _dialog_free():
        st.session_state["dialog_open"] = True   # live prices wait (_dialog_closed)
        _drill_window(key, repeat)


def _drill_closed():
    st.session_state.pop("drill_open", None)
    _dialog_closed()


@st.dialog("This week's drill", width="large", on_dismiss=_drill_closed)
def _drill_window(key, repeat):
    """The drill itself, wide enough to read: the situation, the taps, then
    what they'd weigh and next week's day."""
    p = _read_prefs()
    today = _drill_today()
    done_key = drills.done_this_week(p, today)
    with st.container(key="pt_drill_read"):
        st.markdown(f"### {drills.title_of(key)}")
        st.markdown(drills.BY_KEY[key][3])
        if repeat:
            st.markdown(f"*{drills.twist_of(key)}*")
        lines = drills.picture(key, _drill_mix(), _drill_years())
        if lines:
            st.caption(" ".join(lines))
        mine = drills.chosen(p, key) if done_key == key else None
        if mine is None:
            st.markdown("**What would you think about first?**")
            for choice, words in drills.choices_of(key):
                st.button(words, key=f"drill_tap_{choice}", width="stretch",
                          on_click=_drill_tap, args=(key, choice))
        else:
            st.markdown(f":material/check_circle: You'd start with: "
                        f"*{drills.choice_words(key, mine)}*")
            with st.container(border=True, key="pt_drill_note"):
                st.markdown(f"**{drills.THINK_LEAD}**")
                st.markdown(drills.think_of(key))
                st.caption(drills.NO_RIGHT_ANSWER)
            st.caption("A new one is ready on "
                       f"{_fmt_date(drills.next_week_start(today).isoformat())}. "
                       "It's fine to skip a week.")
            if not feature_counts.left_out(p):
                st.caption("Northwend counts how many people come back for a third drill, "
                           "in totals only - never you by name, never what you tapped. You "
                           "can leave yourself out on Account.")
        if st.button("Close", key="drill_close"):
            _drill_closed()
            st.rerun()
