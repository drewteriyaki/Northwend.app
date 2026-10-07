# Part of dashboard.py, which runs this file with _view("client_book") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, USER_ID, LOGIN_ID, PAGE, the helpers...) are dashboard.py's, and
# what this defines is visible there afterwards. See _view() in dashboard.py.
#
# The Client-Owned Book (ROADMAP R16, client_book.py), behind flag
# client_owned_book and gate L2 (flags.FEATURES - this whole file is skipped
# while it's off; the places that draw it check on("client_owned_book") first).
# - Your clients (views/clients.py): render_book_note() ("How your book
#   works"), book_signals() + render_book_counts() (counts only), and
#   book_card_html() on each card: "Client-reported, as of <date>" and, for a
#   client who shares it, "Walked this month / Last walk".
# - The client's Your advisor page (views/clients.py, _render_notes):
#   render_walk_share(), the client's own switch, and render_exit_keeps()
#   inside Stop sharing - what they keep and what their advisor keeps.
# ruff: noqa: F821

import client_book


# ---- the advisor's book ------------------------------------------------------ #
def book_signals(rows, today):
    """client_book.signals for the clients on the page - this advisor's own
    links only (anyone else's id is dropped there)."""
    c = connect(DB)
    try:
        return client_book.signals(c, LOGIN_ID, [r["user_id"] for r in rows], today)
    finally:
        c.close()


def render_book_note():
    with st.expander(f":material/menu_book: {client_book.BOOK_TITLE}"):
        for line in client_book.HOW_BOOK_WORKS:
            st.markdown(f"- {line}")


def render_book_counts(sig, today):
    """Counts only - never a list or an order of who."""
    n = client_book.counts(sig, today)
    walks = flags.on("walk")
    parts = []
    if walks:
        parts.append(
            f"<div class='pt-stat' role='listitem'><div class='pt-stat-label'>Walked this month"
            f"</div><div class='pt-stat-value'>{n['walked_this_month']}</div>"
            f"<div class='pt-stat-sub'>of {n['sharing_walks']} who share their walks</div></div>")
    parts.append(
        f"<div class='pt-stat' role='listitem'><div class='pt-stat-label'>Updated in "
        f"{client_book.UPDATED_DAYS} days</div><div class='pt-stat-value'>"
        f"{n['updated_recently']}</div><div class='pt-stat-sub'>of {n['clients']} clients"
        "</div></div>")
    st.html(_stat_row("<div class='pt-stats' role='list' aria-label='Book counts'>"
                      + "".join(parts) + "</div>"))
    st.caption("Counts only. A client's walk shows here only if they choose to share it."
               if walks else "Counts only.")


def book_card_html(r, sig):
    """The lines a client's card adds: the client-reported label and, when
    the client shares it, their walk."""
    s = sig.get(r["user_id"]) or {}
    lines = []
    if r["has_data"]:
        lines.append(client_book.reported(s.get("updated") or r.get("imported_at")))
    walk = client_book.walk_line(s) if flags.on("walk") else None
    if walk:
        lines.append(walk)
    return "".join(f"<div class='pt-goal-sub'>{html.escape(x)}</div>" for x in lines)


# ---- the client's side -------------------------------------------------------- #
def _walk_share_mine():
    """A client signed in as themselves (also in a callback, a run later);
    client_book checks again in the database."""
    return (USER_ID == LOGIN_ID and IS_MANAGED_CLIENT and not IS_ADVISOR and not IS_ADMIN
            and flags.on(client_book.FLAG) and flags.on("walk"))


def _walk_share_set():
    if not _walk_share_mine():
        return
    on = bool(st.session_state.get("walk_share"))
    c = connect(DB)
    try:
        client_book.set_walk_sharing(c, LOGIN_ID, on, by=LOGIN_ID,
                                     text_shown=st.session_state.get("_walk_share_text"))
    except (PermissionError, ValueError):
        pass
    finally:
        c.close()


def render_walk_share():
    """Your advisor page: the client's own choice to show their walks."""
    if not _walk_share_mine():
        return
    c = connect(DB)
    try:
        adv = client_book.advisor_for(c, LOGIN_ID, LOGIN_ID)
        on = adv is not None and client_book.shares_walk(c, LOGIN_ID, adv)
    finally:
        c.close()
    if adv is None:
        return
    text = client_book.consent_text(_advisor_display_name())
    st.session_state["_walk_share_text"] = text
    st.session_state["walk_share"] = on   # always what's saved
    with st.container(border=True):
        st.toggle(client_book.WALK_SHARE_LABEL, key="walk_share", on_change=_walk_share_set,
                  help=client_book.WALK_SHARE_HELP)
        st.caption(client_book.WALK_SHARE_ON if on else
                   f"{client_book.WALK_SHARE_OFF} {_md_name(text)}")


def render_exit_keeps():
    """Inside Stop sharing: what the client keeps and what their advisor
    keeps. Returns the words shown, which go with the consent revoke."""
    st.markdown(f"**{client_book.EXIT_TITLE}**")
    st.markdown(f"- {client_book.EXIT_YOU_KEEP}")
    st.markdown(f"- {client_book.EXIT_ADVISOR_KEEPS}")
    return (client_book.EXIT_YOU_KEEP, client_book.EXIT_ADVISOR_KEEPS)
