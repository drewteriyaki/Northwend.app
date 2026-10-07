# Part of dashboard.py, which runs this file with _view("teach_back") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Teach It Back (ROADMAP R13; teach_back.py), behind flag teach_back
# (flags.FEATURES - this whole file is skipped while it's off, so its caller,
# Learn's basics window in views/get_started.py, checks on("teach_back")).
# Under each basics topic: an optional "Explain it back in your own words"
# box. The words are scrubbed and checked by the AI gateway's "grader"
# helper (the cheap tier, out of the person's chat allowance: _ai_status /
# _ai_record), generously - "That holds" or "Not quite yet" and a pointer to
# what the topic says, never a score, never anything about their own money.
# "Try again" any time, no penalty. Kept: per topic, held or not and the day
# (prefs teach_back) - never the words. The person's own only: never while
# an advisor is in a client's account (_kit_shown, views/kit.py). Three
# topics that hold earn the map case (gear.py).
# ruff: noqa: F821

import teach_back


def _tb_shown():
    """An investor (or a client) on their own account - also checked in the
    callbacks, a run later."""
    return flags.on("teach_back") and _kit_shown()


def _tb_result_key(key):
    return f"tb_result_{key}"


def _tb_note(key, text):
    st.session_state[_tb_result_key(key)] = {"note": text}


def _tb_later(text):
    """A calm line that always ends by saying this can wait."""
    text = (text or "").strip()
    return text if text.endswith(teach_back.COME_BACK) else f"{text} {teach_back.COME_BACK}"


def _tb_send(key):
    """Check my explanation: scrub, ask the grader, keep held / not yet and
    the day. The words stay in the box (session state) only."""
    if not _tb_shown() or key not in teach_back.CONCEPTS:
        return
    text = (st.session_state.get(f"tb_text_{key}") or "").strip()
    if len(text) < teach_back.MIN_CHARS:
        _tb_note(key, teach_back.TOO_SHORT)
        return
    api_key = _anthropic_key()
    if not api_key:
        _tb_note(key, teach_back.UNAVAILABLE)
        return
    quota = _ai_status(teach_back.KIND)   # the chat allowance (ai_usage.bucket_of)
    if not quota["ok"]:
        _tb_note(key, _tb_later(ai_usage.used_up_text(quota, teach_back.KIND, GUIDE)))
        return
    import anthropic

    try:
        result = teach_back.grade(anthropic.Anthropic(api_key=api_key), key, text,
                                  user_id=LOGIN_ID)
    except anthropic.AnthropicError as exc:
        _tb_note(key, _tb_later(_ai_failed(exc, teach_back.KIND, "Checking explanations")))
        return
    _ai_record(teach_back.KIND)   # counted once it has answered
    if result is None:
        _tb_note(key, teach_back.UNAVAILABLE)
        return
    p = _read_prefs()
    if teach_back.record(p, key, result["verdict"] == teach_back.HOLDS, datetime.now().date()):
        _write_prefs(p)
    st.session_state[_tb_result_key(key)] = result


def _tb_again(key):
    """Try again: an empty box, nothing lost, nothing counted."""
    st.session_state.pop(_tb_result_key(key), None)
    st.session_state[f"tb_text_{key}"] = ""


def render_teach_back(key):
    """The box under one basics topic (Learn's basics window)."""
    if not _tb_shown() or key not in teach_back.CONCEPTS:
        return
    st.divider()
    st.markdown(f"**:material/record_voice_over: {teach_back.BOX_LABEL}**")
    if teach_back.state(_read_prefs()).get(key, {}).get("held"):
        st.caption(teach_back.HELD_BEFORE)
    res = st.session_state.get(_tb_result_key(key)) or {}
    if res.get("verdict"):
        holds = res["verdict"] == teach_back.HOLDS
        words = res["feedback"].replace("$", r"\$")
        title = teach_back.HELD_TITLE if holds else teach_back.NOT_YET_TITLE
        (st.success if holds else st.info)(
            f"**{title}** {words}",
            icon=":material/check_circle:" if holds else ":material/lightbulb:")
        st.button(teach_back.AGAIN_LABEL, key=f"tb_again_{key}", type="tertiary",
                  icon=":material/refresh:", on_click=_tb_again, args=(key,))
        st.caption(teach_back.ABOUT)
        return
    st.text_area(teach_back.BOX_LABEL, key=f"tb_text_{key}", max_chars=teach_back.MAX_CHARS,
                 label_visibility="collapsed", height=110,
                 placeholder="In a sentence or two, what's the main idea?")
    st.caption(teach_back.BOX_HELP)
    if res.get("note"):
        st.info(res["note"], icon=":material/schedule:")
    st.button(teach_back.SEND_LABEL, key=f"tb_send_{key}", icon=":material/fact_check:",
              on_click=_tb_send, args=(key,))
    st.caption(teach_back.ABOUT)
