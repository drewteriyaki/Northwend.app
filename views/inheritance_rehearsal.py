# Part of dashboard.py, which runs this file with _view("inheritance_rehearsal")
# at the point where this code used to sit, in dashboard.py's own namespace:
# the names here (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's,
# and what this defines is visible there afterwards. See _view() in dashboard.py.
#
# The Inheritance Rehearsal (ROADMAP "Someday" -> built; inheritance_rehearsal.py),
# behind flag inheritance_rehearsal (flags.FEATURES - this whole file is skipped
# while it's off, so views/account.py checks on("inheritance_rehearsal")). On
# the Account page just under Trail Forks, beside the account map and Lost &
# Found: a practice run at looking after a made-up parent's accounts, one step
# at a time - a situation, two or three taps (things to find out or ask, never
# graded), then what people often find. Ends at the person's own account map
# and, where it's on, Trail Forks' route for the death of a parent.
#
# Kept in the login's own settings (prefs inheritance_rehearsal.PREF): step
# keys walked through and the day finished - never what was tapped (that stays
# in this browser session), nothing typed. Only ever the login's own: never
# drawn while an advisor is in a client's account (USER_ID != LOGIN_ID), never
# sent to the AI.
# ruff: noqa: F821

import inheritance_rehearsal as ir


def _ir_own():
    """Only ever the login's own rehearsal (also in a callback, a run later)."""
    return USER_ID == LOGIN_ID


def _ir_md(text):
    """Text for st.markdown: dollar signs aren't a formula."""
    return str(text).replace("$", r"\$")


def _ir_reset_taps():
    for k in ir.STEP_KEYS:
        st.session_state.pop(f"ir_tap_{k}", None)


def _ir_start():
    _ir_reset_taps()
    st.session_state["ir_step"] = 0


def _ir_leave():
    _ir_reset_taps()
    st.session_state.pop("ir_step", None)


def _ir_tap(step, choice):
    """A tap: show its note, and keep that this step was walked through."""
    if not _ir_own():
        return
    st.session_state[f"ir_tap_{step}"] = choice
    _write_prefs(ir.with_step(_read_prefs(), step))


def _ir_next():
    i = st.session_state.get("ir_step")
    if not isinstance(i, int):
        return
    if i + 1 < len(ir.STEPS):
        st.session_state["ir_step"] = i + 1
        return
    if _ir_own():
        _write_prefs(ir.with_finished(_read_prefs(), datetime.now().date()))
    st.session_state["ir_step"] = "end"


def _ir_clear():
    if not _ir_own():
        return
    _write_prefs(ir.cleared(_read_prefs()))
    _ir_leave()
    st.session_state["ir_msg"] = "Your practice run was cleared."


def _ir_step(i):
    s = ir.STEPS[i]
    key = s["key"]
    st.caption(f"Step {i + 1} of {len(ir.STEPS)}")
    st.markdown(f"**{_ir_md(s['title'])}**")
    st.markdown(_ir_md(s["situation"]))
    tapped = st.session_state.get(f"ir_tap_{key}")
    note = ir.note_of(key, tapped) if tapped else None
    if note is None:
        st.markdown(f"*{ir.TAP_LEAD}*")
        for choice, words in ir.choices_of(key):
            st.button(words, key=f"ir_tap_btn_{key}_{choice}", width="stretch",
                      on_click=_ir_tap, args=(key, choice))
        st.caption(ir.NO_RIGHT_ANSWER)
    else:
        words = dict(ir.choices_of(key))[tapped]
        st.markdown(f":material/check_circle: *{_ir_md(words)}*")
        with st.container(border=True, key=f"pt_ir_note_{key}"):
            st.markdown(f"**{ir.NOTE_LEAD}**")
            st.markdown(_ir_md(note))
        if s["links"]:
            st.markdown("  \n".join(f"[{t}]({u})" for t, u in s["links"]))
        last = i + 1 == len(ir.STEPS)
        st.button(ir.FINISH if last else ir.NEXT, key=f"ir_next_{key}", type="primary",
                  icon=":material/arrow_forward:", on_click=_ir_next)
    st.button(ir.LEAVE, key=f"ir_leave_{key}", type="tertiary", on_click=_ir_leave)


def _ir_end():
    st.markdown(f"**{ir.END_TITLE}**")
    st.markdown(ir.END)
    label, words = ir.END_LINKS["account_map"]
    st.caption(f":material/map: **{label}** - {words}")
    if flags.on("trail_forks"):
        label, words = ir.END_LINKS["trail_forks"]
        st.caption(f":material/local_florist: [{label}](#trail-forks) - {words}")
    st.button("Close", key="ir_close", type="tertiary", on_click=_ir_leave)


def render_inheritance_rehearsal():
    """The Account page's Inheritance Rehearsal (the login's own only)."""
    if not _ir_own():
        return
    saved = _read_prefs().get(ir.PREF)
    st.subheader(ir.TITLE, anchor="inheritance-rehearsal")
    st.caption(ir.INTRO)
    st.caption(f":material/lock: {ir.PRIVATE}")
    msg = st.session_state.pop("ir_msg", None)
    if msg:
        st.caption(f":material/check: {msg}")
    at = st.session_state.get("ir_step")
    with st.container(border=True, key="pt_ir"):
        if at == "end":
            _ir_end()
        elif isinstance(at, int) and 0 <= at < len(ir.STEPS):
            if at == 0:
                st.markdown(f"*{_ir_md(ir.FAMILY)}*")
            _ir_step(at)
        else:
            finished = ir.finished_on(saved)
            done = len(ir.done_steps(saved))
            if finished:
                st.caption(f"You finished the practice run on "
                           f"{_fmt_date(finished.isoformat())}. You can go through it "
                           "again any time.")
            elif done:
                st.caption(f"You've gone through {done} of {len(ir.STEPS)} steps.")
            st.button(ir.AGAIN if finished else ir.START, key="ir_start",
                      icon=":material/family_history:", on_click=_ir_start)
    if saved and (ir.done_steps(saved) or ir.finished_on(saved)) and at is None:
        st.button("Clear my practice run", key="ir_clear", type="tertiary", on_click=_ir_clear)
    st.caption(ir.NOT_ADVICE)
