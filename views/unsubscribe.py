# Part of dashboard.py, which runs this file with _view("unsubscribe") at the
# point where this code used to sit, in dashboard.py's own namespace: the
# names here (st, DB, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# The page an email's one-click unsubscribe link opens (?unsubscribe=...,
# unsubscribe.py): before sign-in, like the confirm and reset links. It turns
# that one email off for the account the link was made for and says so -
# nothing else about the account is shown, and nobody is signed in.
# ruff: noqa: F821

import unsubscribe


def _unsubscribe_page(token: str) -> bool:
    """Turn the email off (once per browser session - a reload says the same)
    and show a calm page. Always False: this page is the whole run."""
    done = st.session_state.setdefault("unsub_done", {})
    if token not in done:
        conn = connect(DB)
        try:
            done[token] = unsubscribe.use(conn, token)
        finally:
            conn.close()
        st.session_state.pop("_prefs", None)   # a signed-in tab reads its settings afresh
    res = done[token]
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        st.title(f"{APP_ICON} {APP_NAME}")
        if res["ok"]:
            st.success("You won't get these emails any more. You can turn them back on in "
                       f"{unsubscribe.WHERE[res['kind']]}.")
        else:
            st.info("This link isn't working any more - it may be an old one, or the email "
                    "on the account has changed. You can turn emails off in Account after "
                    "signing in.")
        if st.button(f"Open {APP_NAME}", key="unsub_open", type="primary"):
            del st.query_params["unsubscribe"]
            st.rerun()
    return False
