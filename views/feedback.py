# Part of dashboard.py, which runs this file with _view("feedback") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, LOGIN_ID, PAGE, the helpers...) are dashboard.py's, and what
# this defines is visible there afterwards. See _view() in dashboard.py.
#
# Send feedback (feedback.py): a small window from the name menu and the About
# page, for everyone signed in. Their words, the kind, the page's name and the
# copy go to the owner by email; nothing is stored but the rate-limit count.
# Always the login's own: an advisor in a client's account sends as themselves,
# and nothing of the client's (or anyone's figures) is read or attached.
# ruff: noqa: F821

import feedback


def _feedback_open(page):
    """The name menu's or the About page's Send feedback: the window opens on
    the next run, remembering only the name of the page it was opened from."""
    st.session_state["fb_open"] = True
    st.session_state["fb_page"] = _label(page)
    st.session_state.pop("fb_sent", None)
    st.session_state.pop("fb_note", None)


def _feedback_closed():
    for k in ("fb_open", "fb_sent", "fb_note", "fb_page"):
        st.session_state.pop(k, None)
    _dialog_closed()


def _feedback_reply_email():
    """The login's own confirmed email, or "" - never the viewed client's."""
    c = connect(DB)
    try:
        status = auth.email_status(c, LOGIN_ID)
    finally:
        c.close()
    return (status["email"] or "") if status["confirmed"] else ""


def _feedback_copy():
    if STAGING:
        return "Staging"
    return "Live" if settings.hosted() else "Local"


def _feedback_send():
    words = st.session_state.get("fb_words") or ""
    why = feedback.problem(words)
    if why:
        st.session_state["fb_note"] = why
        return
    if not _limit_ok(rate_limits.FEEDBACK):
        st.session_state["fb_note"] = LIMIT_TEXT
        return
    reply = _feedback_reply_email() if st.session_state.get("fb_reply") else ""
    ok = feedback.send(words, st.session_state.get("fb_kind") or "other",
                       page=st.session_state.get("fb_page") or "", version=hosting.version(HERE),
                       copy=_feedback_copy(), login_id=LOGIN_ID, reply_email=reply or None)
    if not ok:
        st.session_state["fb_note"] = feedback.NOT_SENT
        return
    st.session_state["fb_sent"] = True
    st.session_state.pop("fb_note", None)
    for k in ("fb_words", "fb_kind", "fb_reply"):
        st.session_state.pop(k, None)


@st.dialog("Send feedback", width="small", on_dismiss=_feedback_closed)
def _feedback_window():
    with st.container(key="pt_feedback"):
        if st.session_state.get("fb_sent"):
            st.success(feedback.THANKS, icon=":material/check_circle:")
            if st.button("Close", key="fb_close", type="primary"):
                _feedback_closed()
                st.rerun()
            return
        st.markdown(feedback.INTRO)
        st.radio("What is it?", [k for k, _ in feedback.KINDS], key="fb_kind", index=None,
                 format_func=feedback.KIND_WORDS.get, horizontal=True)
        st.text_area("What would you like to tell us?", key="fb_words",
                     max_chars=feedback.MAX_CHARS, height=140)
        if _feedback_reply_email():
            st.checkbox(feedback.REPLY_BOX, key="fb_reply", value=False,
                        help=feedback.REPLY_HELP)
        else:
            st.caption(feedback.NO_EMAIL)
        st.caption(feedback.PRIVATE)
        if st.session_state.get("fb_note"):
            st.warning(st.session_state["fb_note"], icon=":material/info:")
        with st.container(horizontal=True):
            st.button("Send", key="fb_send", type="primary", icon=":material/send:",
                      on_click=_feedback_send)
            if st.button("Cancel", key="fb_cancel", type="tertiary"):
                _feedback_closed()
                st.rerun()


def render_feedback():
    """Open the window while it's asked for (dashboard.py calls this once the
    page's other helpers exist); another window already open goes first."""
    if st.session_state.get("fb_open") and _dialog_free():
        st.session_state["dialog_open"] = True   # live prices wait (_dialog_closed)
        _feedback_window()
