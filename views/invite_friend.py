# Part of dashboard.py, which runs this file with _view("invite_friend") at
# the point where this code sits, in dashboard.py's own namespace: the names
# here (st, DB, LOGIN_ID, IS_ADVISOR, the helpers...) are dashboard.py's, and
# what this defines is visible there afterwards. See _view() in dashboard.py.
#
# Invite someone (invite_links.py): a small window from the name menu with
# the login's own link to share, a ready-made message and how many people
# joined with it - a count, never who. Northwend sends nothing and asks for
# no one's address. Always the login's own (LOGIN_ID); the menu leaves it out
# while an advisor is in a client's account or sign-up isn't open
# (INVITE_SHOWN). An advisor's link invites people as individuals, never as
# clients (client setup links stay on Your clients).
# ruff: noqa: F821


def _invite_open():
    """The name menu's Invite someone: the window opens on the next run."""
    st.session_state["inv_open"] = True
    st.session_state.pop("inv_note", None)


def _invite_closed():
    for k in ("inv_open", "inv_note"):
        st.session_state.pop(k, None)
    _dialog_closed()


def _invite_new_link():
    """Make a new link: the old one then just opens the usual sign-up."""
    if not INVITE_SHOWN:
        return
    if not _limit_ok(rate_limits.NEW_LINK):
        st.session_state["inv_note"] = ("info", LIMIT_TEXT)
        return
    c = connect(DB)
    try:
        invite_links.new_code(c, LOGIN_ID)
    finally:
        c.close()
    st.session_state["inv_note"] = ("success", invite_links.NEW_LINK_DONE)


@st.dialog(invite_links.TITLE, width="small", on_dismiss=_invite_closed)
def _invite_window():
    c = connect(DB)
    try:
        code = invite_links.code_for(c, LOGIN_ID)   # made the first time it's opened
        joined = invite_links.joined(c, LOGIN_ID)
    finally:
        c.close()
    link = invite_links.link(_app_address(), code)
    # the boxes' copy buttons always showing - a phone has no hover to bring them up
    st.html("<style>.st-key-pt_invite [data-testid='stCode'] > div:has("
            "[data-testid='stElementToolbarButton']) { visibility: visible !important; "
            "opacity: 1 !important; }</style>")
    with st.container(key="pt_invite"):
        st.markdown(invite_links.INTRO)
        st.caption("Your link - the button in its corner copies it")
        st.code(link, language=None, wrap_lines=True)
        st.caption("A message you could send with it")
        st.code(invite_links.message(link), language=None, wrap_lines=True)
        if IS_ADVISOR:
            st.caption(invite_links.ADVISOR_NOTE)
        st.caption(invite_links.PRIVATE)
        st.caption(invite_links.joined_words(joined))
        note = st.session_state.pop("inv_note", None)
        if note:
            if note[0] == "success":
                st.success(note[1], icon=":material/check_circle:")
            else:
                st.info(note[1], icon=":material/info:")
        with st.container(horizontal=True):
            st.button("Make a new link", key="inv_new", type="tertiary",
                      icon=":material/refresh:", on_click=_invite_new_link,
                      help=invite_links.NEW_LINK_HELP)
            if st.button("Close", key="inv_close", type="primary"):
                _invite_closed()
                st.rerun()


def render_invite():
    """Open the window while it's asked for (dashboard.py calls this once the
    page's other helpers exist); another window already open goes first."""
    if st.session_state.get("inv_open") and INVITE_SHOWN and _dialog_free():
        st.session_state["dialog_open"] = True   # live prices wait (_dialog_closed)
        _invite_window()
