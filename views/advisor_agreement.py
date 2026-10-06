# Part of dashboard.py, which runs this file with _view("advisor_agreement") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# The advisor agreement (advisor_agreement.py; master brief 4.1, gate L1; flag
# advisor_agreement): an approved advisor who hasn't accepted the current
# version sees it on Your clients, in place of the book, once - a calm page,
# like the two-step gate but only in front of the advisor tools. Until they
# accept, auth.can_view opens no client's account; their own investor side
# (Portfolio, Plan, Money, Account) works as usual. With gate L1 off it's
# marked "Beta" (free beta seats, brief 4.5).
#
# Also the standing line in the app (standing_line.py; brief 4.4): _render_standing
# draws "This is <advisor>'s advice, from <firm> - not Northwend's..." under
# whatever an advisor shares with a client - proposals, reports, messages, and
# the advisor card at the top of the client's Your advisor page.
# ruff: noqa: F821

import advisor_agreement
import standing_line

# Whether this advisor still has the current agreement to accept (read once a
# run, and only while the flag is on).
ADVISOR_AGREEMENT_DUE = False
if IS_ADVISOR and advisor_agreement.required():
    _ag_conn = connect(DB)
    try:
        ADVISOR_AGREEMENT_DUE = advisor_agreement.due(_ag_conn, LOGIN_ID, is_advisor=True)
    finally:
        _ag_conn.close()

# advisor id -> their standing line, read at most once a run
_STANDING = {}


def _standing_text(advisor_id):
    """The standing line for this advisor (standing_line.for_advisor)."""
    if advisor_id not in _STANDING:
        c = connect(DB)
        try:
            _STANDING[advisor_id] = standing_line.for_advisor(c, advisor_id)
        finally:
            c.close()
    return _STANDING[advisor_id]


def _render_standing(advisor_id):
    """The standing line, small, under something an advisor shared."""
    st.caption(":material/verified_user: " + _md_name(_standing_text(advisor_id)))


def _agreement_accept():
    c = connect(DB)
    try:
        advisor_agreement.accept(c, st.session_state["user_id"],
                                 ticked=bool(st.session_state.get("agreement_tick")))
    except ValueError as exc:
        st.session_state["agreement_msg"] = str(exc)
    else:
        st.session_state["agreement_msg"] = None
        st.toast("Thank you - your clients are below.")
    finally:
        c.close()


def _render_advisor_agreement():
    """Your clients, until the current agreement is accepted."""
    c = connect(DB)
    try:
        before = advisor_agreement.latest(c, LOGIN_ID)
    finally:
        c.close()
    beta = advisor_agreement.label()
    st.markdown("#### One thing before your clients")
    if before:
        st.caption(f"The advisor agreement has changed since you accepted it on "
                   f"{_fmt_date(before['accepted_at'][:10])}. Please read this version - it "
                   "takes a couple of minutes.")
    else:
        st.caption("Northwend is the software; the advice is yours. Please read the advisor "
                   "agreement once - it takes a couple of minutes. Your own portfolio, plan and "
                   "Money pages work as usual in the meantime.")
    with st.container(border=True, key="pt_agreement"):
        st.markdown(f"**{advisor_agreement.TITLE}**"
                    + (f" &nbsp;:blue-badge[{beta}]" if beta else ""))
        st.caption(f"Version {advisor_agreement.VERSION}")
        st.markdown(advisor_agreement.TEXT)
        if beta:
            st.caption(advisor_agreement.BETA_NOTE)
    msg = st.session_state.pop("agreement_msg", None)
    if msg:
        st.warning(msg)
    st.checkbox(advisor_agreement.TICK_LABEL, key="agreement_tick")
    st.button("Accept and continue", key="agreement_accept", type="primary",
              on_click=_agreement_accept)
    st.caption("Questions about it? Write to support@northwend.app - we're happy to help.")
