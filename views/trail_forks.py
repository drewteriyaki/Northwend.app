# Part of dashboard.py, which runs this file with _view("trail_forks") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Trail Forks (ROADMAP R8, trail_forks.py), behind flag trail_forks
# (flags.FEATURES - this whole file is skipped while it's off): on the Life
# page, above the Inheritance Rehearsal (views/life.py calls render_trail_forks). A
# route per life event - a new job, a layoff, a new baby, an inheritance, a
# divorce, the death of a parent: what changes, what to gather, what to ask
# and whom, what not to rush - with official links only. Each fork ends
# pointing into the Walk: Home with the monthly walk open (views/checkin.py,
# as the kit's logbook does) when the walk is on and shown to this person,
# else the Plan page.
#
# Which forks are theirs and which steps they've ticked are kept in the
# login's own settings (prefs trail_forks.PREF): fixed keys only - nothing
# typed, no dates. Only ever the login's own: never drawn while an advisor is
# in a client's account (USER_ID != LOGIN_ID), never sent to the AI.
# ruff: noqa: F821

import trail_forks


def _tf_own():
    """Only ever the login's own forks (also in a callback, a run later)."""
    return USER_ID == LOGIN_ID


def _tf_mark(fork):
    if not _tf_own():
        return
    mine = bool(st.session_state.get(f"tf_on_{fork}"))
    _write_prefs(trail_forks.with_fork(_read_prefs(), fork, mine))
    if not mine:   # its ticks are gone: so are their boxes
        for step in trail_forks.steps(fork):
            st.session_state.pop(f"tf_{fork}_{step}", None)


def _tf_tick(fork, step):
    if not _tf_own():
        return
    _write_prefs(trail_forks.with_step(_read_prefs(), fork, step,
                                       bool(st.session_state.get(f"tf_{fork}_{step}"))))


def _tf_clear():
    if not _tf_own():
        return
    _write_prefs(trail_forks.cleared(_read_prefs()))
    for fork in trail_forks.FORK_KEYS:
        st.session_state.pop(f"tf_on_{fork}", None)
        for step in trail_forks.steps(fork):
            st.session_state.pop(f"tf_{fork}_{step}", None)
    st.session_state["tf_msg"] = "Your marks and ticks were cleared."


def _tf_walk_on():
    """The monthly walk is on and shown to this person (views/checkin.py)."""
    return flags.on("walk") and _checkin_shown()


def _tf_go_walk():
    """Home, with this month's walk open (the kit's logbook does the same)."""
    st.session_state["checkin_open"] = True
    _go("Dashboard")


def _tf_md(text):
    """Text for st.markdown: dollar signs aren't a formula."""
    return str(text).replace("$", r"\$")


def _tf_items(fork, items, ticking, done):
    """Steps as ticks on a fork that's theirs, else a plain list."""
    if not ticking:
        st.markdown("\n".join(f"- {_tf_md(t)}" for _, t in items))
        return
    for step, words in items:
        st.checkbox(words, value=step in done, key=f"tf_{fork}_{step}",
                    on_change=_tf_tick, args=(fork, step))


def _tf_fork(f, saved):
    key = f["key"]
    is_mine = key in trail_forks.mine(saved)
    done = set(trail_forks.done_steps(saved, key))
    title = f["title"]
    if is_mine:
        n, of = trail_forks.progress(saved, key)
        title += " · yours"
    with st.expander(title, icon=f["icon"], expanded=is_mine):
        st.markdown(f"*{_tf_md(f['opening'])}*")
        st.checkbox(trail_forks.MINE_LABEL, value=is_mine, key=f"tf_on_{key}",
                    help=trail_forks.MINE_HELP, on_change=_tf_mark, args=(key,))
        if is_mine:
            st.caption(f"{n} of {of} steps ticked.")
        st.markdown(f"**{trail_forks.CHANGES}**  \n"
                    + "\n".join(f"- {_tf_md(c)}" for c in f["changes"]))
        st.markdown(f"**{trail_forks.GATHER}**")
        _tf_items(key, f["gather"], is_mine, done)
        st.markdown(f"**{trail_forks.ASK}**")
        for whom, questions in f["ask"]:
            st.markdown(f"*{_tf_md(whom)}*")
            _tf_items(key, questions, is_mine, done)
        if IS_MANAGED_CLIENT:
            st.caption(f"Your advisor, {_md_name(_advisor_display_name())}, is someone else "
                       "you could ask - only if you choose to tell them. Nothing here is "
                       "shared with them"
                       + (" unless you tick this one in Bring to my advisor, on your "
                          "Account page." if flags.on("advisor_pack") else "."))
        st.markdown(f"**{trail_forks.NOT_RUSH}**  \n"
                    + "\n".join(f"- {_tf_md(c)}" for c in f["not_rush"]))
        st.markdown("  \n".join(f"[{t}]({u})" for t, u in f["links"]))
        for also in f["see_also"]:
            if also != "lost_found" or flags.on("lost_found"):
                st.caption(f":material/subdirectory_arrow_right: {trail_forks.SEE_ALSO[also]}")
        # the fork's end: into the Walk
        with st.container(border=True, horizontal=True, vertical_alignment="center",
                          key=f"pt_tf_end_{key}"):
            if _tf_walk_on():
                st.markdown(f":material/hiking: {trail_forks.WALK_END}", width="stretch")
                st.button(trail_forks.WALK_BUTTON, key=f"tf_walk_{key}", type="tertiary",
                          icon=":material/arrow_forward:", on_click=_tf_go_walk)
            else:
                st.markdown(f":material/hiking: {trail_forks.PLAN_END}", width="stretch")
                st.button(trail_forks.PLAN_BUTTON, key=f"tf_plan_{key}", type="tertiary",
                          icon=":material/arrow_forward:", on_click=_go, args=("Plan",))


def render_trail_forks():
    """The Life page's Trail Forks section (the login's own only)."""
    if not _tf_own():
        return
    saved = _read_prefs().get(trail_forks.PREF)
    st.subheader("Trail Forks", anchor="trail-forks")
    st.caption(trail_forks.INTRO)
    st.caption(f":material/lock: {trail_forks.PRIVATE}")
    msg = st.session_state.pop("tf_msg", None)
    if msg:
        st.caption(f":material/check: {msg}")
    for f in trail_forks.FORKS:
        _tf_fork(f, saved)
    if trail_forks.mine(saved):
        st.button("Clear my marks and ticks", key="tf_clear", type="tertiary", on_click=_tf_clear)
    st.caption(trail_forks.NOT_ADVICE)
