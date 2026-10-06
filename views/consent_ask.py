# Part of dashboard.py, which runs this file with _view("consent_ask") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Sharing with your advisor, asked once (PLAN step 5.7; consent.py). A client
# whose sharing rests only on a 'migration' grant - or on none at all while
# linked (an admin linked two accounts; they got in with a password their
# advisor set, not the setup link) - is asked at their next sign-in, the way
# the once-only agreement box above asks: calmly, on any page, without
# blocking anything, until they answer. "Keep sharing" records a 'sign_in_ask'
# grant with the exact words shown (consent.ask_text); "Stop sharing" asks to
# confirm, then ends it as Your advisor's "Stop sharing" does
# (advising.end_relationship, by the client, which writes the revoke).
# Only the client's own login is asked: never an advisor (in a client's
# account or not), never an admin, and only once they've agreed to the
# disclosures (one box at a time). Until they answer, the advisor sees the
# account as before - a question for gate L2 (docs/LEGAL_GATES.md) - and their
# book says "hasn't confirmed sharing yet" (views/clients.py).
# ruff: noqa: F821

# the advisors this login shares with but hasn't said yes to in its own words
# (consent.to_ask); once there are none, not read again this session
_CONSENT_ASK, _CONSENT_WHO = [], None
if (IS_MANAGED_CLIENT and not IS_ADVISOR and not IS_ADMIN and _me["agreed"]
        and st.session_state.get("consent_clear") != LOGIN_ID):
    _ca_conn = connect(DB)
    try:
        _CONSENT_ASK = consent.to_ask(_ca_conn, LOGIN_ID)
        if _CONSENT_ASK:
            _CONSENT_WHO = consent.advisor_label(_ca_conn, _CONSENT_ASK[0])
    finally:
        _ca_conn.close()
    if not _CONSENT_ASK:
        st.session_state["consent_clear"] = LOGIN_ID


def _consent_stop_words(who):
    """The confirm step's words (as on Your advisor's Stop sharing),
    recorded with the revoke."""
    return (f"Your advisor, {who}, will no longer see your account. You keep everything - "
            "your holdings, plan and goals - and manage them yourself from now on.",
            "Your advisor keeps their own notes about your time working together, for their "
            "records. We'll let them know you've stopped sharing.")


def _consent_keep(advisor_id, text):
    """Keep sharing: a 'sign_in_ask' grant with the words on screen."""
    me = st.session_state["user_id"]
    c = connect(DB)
    try:
        if advisor_id in consent.to_ask(c, me):   # still linked, still not asked
            consent.grant(c, me, advisor_id, text, "sign_in_ask")
    finally:
        c.close()
    st.session_state.pop("consent_stop", None)
    st.toast("Thank you - you're still sharing with your advisor. You won't be asked again.",
             icon=":material/check:")


def _consent_stop_ask(advisor_id):
    st.session_state["consent_stop"] = advisor_id


def _consent_stop_back():
    st.session_state.pop("consent_stop", None)


def _consent_stop(advisor_id, text):
    """Stop sharing, confirmed: the client's own stop (advising.end_relationship
    writes the revoke with `text`); their advisor gets the usual short email."""
    me = st.session_state["user_id"]
    st.session_state.pop("consent_stop", None)
    c = connect(DB)
    try:
        if advisor_id not in consent.to_ask(c, me):
            return
        res = advising.end_relationship(c, advisor_id, me, by="client", text_shown=text)
        to = auth.email_status(c, advisor_id)
        email = (to["email"] if res["ok"] and to["confirmed"]
                 and auth.notice_ok(c, "ended", to["email"]) else None)
    finally:
        c.close()
    if email:
        # what the advisor calls them (Your clients), so they know who it is
        mailer.client_stopped_sharing(email, f"{_app_address()}?page=your-clients",
                                      res["name"])
    st.session_state["page"] = "Dashboard"
    st.session_state["import_flash"] = ("You've stopped sharing with your advisor. Everything "
                                        "is still here, and it's yours to manage from now on.")
    st.toast("You've stopped sharing with your advisor.")


if _CONSENT_ASK:
    _ca_adv = _CONSENT_ASK[0]
    with st.container(border=True, key="pt_consent_ask"):
        if st.session_state.get("consent_stop") == _ca_adv:
            _ca_words = _consent_stop_words(_CONSENT_WHO)
            st.markdown(":material/link_off: **Stop sharing with your advisor?**")
            for _w in _ca_words:
                st.markdown(_md_name(_w))
            with st.container(horizontal=True):
                st.button("Yes, stop sharing", key="consent_stop_yes", type="primary",
                          on_click=_consent_stop, args=(_ca_adv, "\n\n".join(_ca_words)))
                st.button("Go back", key="consent_stop_back", type="tertiary",
                          on_click=_consent_stop_back)
        else:
            _ca_text = consent.ask_text(_CONSENT_WHO)
            st.markdown(":material/group: **Sharing with your advisor**")
            for _w in _ca_text.split("\n\n"):
                st.markdown(_md_name(_w))
            with st.container(horizontal=True):
                st.button("Keep sharing", key="consent_keep", type="primary",
                          on_click=_consent_keep, args=(_ca_adv, _ca_text))
                st.button("Stop sharing", key="consent_stop_start", type="tertiary",
                          on_click=_consent_stop_ask, args=(_ca_adv,))
