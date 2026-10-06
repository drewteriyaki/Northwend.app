# Part of dashboard.py, which runs this file with _view("whats_new") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, LOGIN_ID, PAGE, the helpers...) are dashboard.py's, and what
# this defines is visible there afterwards. See _view() in dashboard.py.
#
# What's new (whats_new.py): the dated list of changes, newest first, from the
# name menu. Opening it marks the newest entry as seen in the login's own
# settings - the only thing it does; there's no pop-up and no banner.
# ruff: noqa: F821


def _whats_new_mark_seen():
    """The login's own settings (never a client's an advisor is viewing)."""
    newest = whats_new.latest()
    if not newest or st.session_state.get("_wn_seen") == newest:
        return
    conn = connect(DB)
    try:
        prefs.save(conn, LOGIN_ID, whats_new.mark_seen(prefs.load(conn, LOGIN_ID)))
    finally:
        conn.close()
    st.session_state["_wn_seen"] = newest


def _render_whats_new():
    entries = whats_new.visible()
    if not entries:
        st.caption("Nothing new to show yet.")
        return
    st.caption("What changed in Northwend, newest first.")
    for i, e in enumerate(entries):
        with st.expander(f"**{e['title']}** · {whats_new.when(e['date'])}", expanded=(i == 0)):
            st.markdown("\n".join(f"- {item}" for item in e["items"]))
    _whats_new_mark_seen()
