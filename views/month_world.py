# Part of dashboard.py, which runs this file with _view("month_world") at the
# point where this code used to sit, in dashboard.py's own namespace: the
# names here (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and
# what this defines is visible there afterwards. See _view() in dashboard.py.
#
# This month's world, for your mix (ROADMAP Phase C; month_world.py), behind
# flag month_world (flags.FEATURES - this whole file is skipped while it's
# off, so its caller checks on("month_world")). One line inside the
# preparedness drill card on Home (views/drills.py calls render_month_world,
# so it shows only where the drills do too): the owner's reviewed note for
# this month or last, with a button to open it. Open: the past facts, the
# lines for the person's own largest asset class or two (whole percents,
# from views/drills.py's _drill_mix - none for someone not investing yet),
# and the official sources. Kept: only which months' notes were opened
# (prefs month_world_seen). The login's own account only - never while an
# advisor is in a client's account (_kit_shown) - and never sent to the AI.
# ruff: noqa: F821

import month_world


def _world_shown():
    """The kit's rule, as the drills: the login's own account - also checked
    in the callback, a run later."""
    return flags.on("month_world") and _kit_shown()


def _world_open(month):
    if not _world_shown():
        return
    st.session_state["world_open"] = True
    p = _read_prefs()
    if month_world.mark_seen(p, month):
        _write_prefs(p)


def _world_close():
    st.session_state["world_open"] = False


def render_month_world():
    """The line in the drill card, and the note once opened. Nothing at all
    when there's no reviewed note for this month or last."""
    if not _world_shown():
        return
    note = month_world.current(_drill_today())
    if note is None:
        return
    with st.container(border=True, key="pt_world"):
        st.html("<div class='pt-eyebrow' style='margin:0'>"
                f"{html.escape(month_world.TITLE)}</div>"
                f"<div><b>{html.escape(note['title'])}</b></div>")
        if not st.session_state.get("world_open"):
            st.button(month_world.OPEN, key="world_open_btn", icon=":material/public:",
                      on_click=_world_open, args=(note["month"],))
            return
        st.caption(month_world.INTRO)
        for para in note["paragraphs"]:
            st.markdown(para.replace("$", r"\$"))
        lines = month_world.lines_for(note, _drill_mix())
        for i, (key, pct, line) in enumerate(lines):
            st.markdown(f"**{month_world.lead_of(key, pct, largest=i == 0)}:** "
                        + line.replace("$", r"\$"))
        if not lines and not HAS_REAL_HOLDINGS:
            st.caption(month_world.GENERAL_ONLY)
        st.caption(f"{month_world.SOURCES_LEAD}: " + " · ".join(
            f"[{label}]({url})" for label, url in note["sources"]))
        st.caption(month_world.NOT_ADVICE)
        st.button(month_world.CLOSE, key="world_close_btn", on_click=_world_close)
