# Part of dashboard.py, which runs this file with _view("explain_share") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, connect, flags, _visitor_ip, _show_signup...) are dashboard.py's,
# and what this defines is visible there afterwards. See _view() in dashboard.py.
#
# Explain it to someone (ROADMAP R10, explain_share.py), flag explain_share.
# Two parts:
# - _share_page(): the whole run for ?share=<token>, before sign-in, like the
#   unsubscribe and reset links (dashboard._login calls it first). It signs
#   nobody in and draws nothing else - no menu, no sidebar, no other page. A
#   figure-free page from the owner's current data, or - for any link that
#   doesn't work, and for every link while the flag is off - the same calm
#   "no longer active" page. Each browser visit is counted once against the
#   per-address limit before the link is looked up. The token is never
#   printed, logged or kept in session state (only its hash, to count a visit
#   once).
# - render_explain_share(): the owner's section on the Life page (an advisor's: Account)
#   (views/account.py checks on("explain_share")): make a link (7 or 30 days,
#   first name off unless ticked), see it once, see the working ones, turn
#   any or all off. Only the login's own account: never while an advisor is
#   in a client's account, never for an advisor's client, never an admin.
#
# Not owned by the flag (flags.FEATURES: "view": None) on purpose: this file
# always loads so the inactive page is there while the flag is off.
# ruff: noqa: F821

import explain_share as xs


# ---- the page the link opens ------------------------------------------------- #
def _share_wanted() -> bool:
    return xs.QUERY in st.query_params


def _xs_leave():
    """The Learn button: off this page - to Create account, or, for someone
    already signed in on this browser, back to their own account."""
    if xs.QUERY in st.query_params:
        del st.query_params[xs.QUERY]
    st.session_state.pop("xs_seen", None)
    if not st.session_state.get("user_id"):
        _show_signup(True)


def _xs_learn_offer():
    st.subheader(xs.LEARN_TITLE, anchor=False)
    st.markdown(xs.LEARN_TEXT)
    st.button(xs.LEARN_BUTTON, key="xs_learn", type="primary", on_click=_xs_leave,
              icon=":material/school:")


def _xs_route(stage):
    keys = [k for k, _ in xs.ROUTE]
    at = keys.index(stage) if stage in keys else -1
    rows = []
    for i, (_k, label) in enumerate(xs.ROUTE):
        if i < at:
            rows.append(f"- :material/check_circle: {label}")
        elif i == at:
            rows.append(f"- :material/my_location: **{label}** - where they are now")
        else:
            rows.append(f"- :material/radio_button_unchecked: {label}")
    st.markdown("\n".join(rows))


def _xs_body(shown):
    """The page's content, from explain_share.page() - also the owner's preview."""
    lines = xs.lines(shown)
    if not lines:
        st.markdown(xs.PAGE_EMPTY)
    for part, heading, text in lines:
        with st.container(border=True):
            st.markdown(f"**{heading}**")
            if part == "stage":
                _xs_route(shown.get("stage"))
            st.markdown(text)
    classes = xs.classes_shown(shown)
    if classes:
        with st.expander("What these words mean"):
            for k in classes:
                st.markdown(f"**{k}** - {xs.CLASS_WORDS[k]}")


def _xs_inactive():
    st.title(xs.INACTIVE_TITLE, anchor=False)
    st.markdown(xs.INACTIVE_TEXT)


def _share_page() -> bool:
    """The whole run for ?share=... Always False: nobody is signed in by it."""
    token = str(st.query_params.get(xs.QUERY) or "")
    seen = st.session_state.setdefault("xs_seen", {})   # the link's hash -> limit message
    shown, limited = None, None
    if flags.on(xs.FLAG):
        key = xs.token_hash(token)
        conn = connect(DB)
        try:
            if key not in seen:   # once per browser visit, before the link is looked up
                seen[key] = xs.take(conn, _visitor_ip())
                found = None if seen[key] else xs.lookup(conn, token)
                if found:
                    xs.note_open(conn, found["user_id"], found["id"])
            limited = seen[key]
            found = None if limited else xs.lookup(conn, token)   # every run: still working?
            if found:
                shown = xs.page(conn, found["user_id"], show_name=found["show_name"])
        finally:
            conn.close()
    _, mid, _ = st.columns([1, 4, 1])
    with mid:
        st.html(_brand_html("pt-brand-line"))
        if limited:
            st.info(limited, icon=":material/schedule:")
        elif shown is None:
            _xs_inactive()
        else:
            st.title(xs.title(shown), anchor=False)
            st.caption(f":material/lock: {xs.PAGE_INTRO}")
            _xs_body(shown)
        st.divider()
        _xs_learn_offer()
        st.caption(xs.FOOTER)
    return False


# ---- the owner's section on Life ---------------------------------------------- #
def _xs_own() -> bool:
    """Only the login's own account, and only one that may share (also in a
    callback, a run later). explain_share.create checks again in the database."""
    return (flags.on(xs.FLAG) and USER_ID == LOGIN_ID and not IS_MANAGED_CLIENT
            and not IS_ADMIN)


def _xs_create():
    if not _xs_own():
        return
    days = st.session_state.get("xs_days") or xs.DEFAULT_DAYS
    conn = connect(DB)
    try:
        token = xs.create(conn, LOGIN_ID, by=LOGIN_ID, days=int(days),
                          show_name=bool(st.session_state.get("xs_name")))
    except PermissionError:
        st.session_state["xs_msg"] = xs.NOT_ALLOWED
        return
    except ValueError:
        st.session_state["xs_msg"] = xs.TOO_MANY
        return
    finally:
        conn.close()
    # in this session's memory only, until "Done" - never saved anywhere
    st.session_state["xs_new"] = xs.link(_app_address(), token)


def _xs_done():
    st.session_state.pop("xs_new", None)


def _xs_revoke(link_id):
    if not _xs_own():
        return
    conn = connect(DB)
    try:
        xs.revoke(conn, LOGIN_ID, link_id)
    finally:
        conn.close()
    st.session_state["xs_msg"] = "That link is turned off. Anyone who opens it now sees that it's no longer active."


def _xs_revoke_all():
    if not _xs_own():
        return
    conn = connect(DB)
    try:
        xs.revoke_all(conn, LOGIN_ID)
    finally:
        conn.close()
    st.session_state.pop("xs_new", None)
    st.session_state["xs_msg"] = "All your links are turned off."


def _xs_day(stamp) -> str:
    try:
        d = datetime.strptime(str(stamp)[:10], "%Y-%m-%d")
    except ValueError:
        return str(stamp)[:10]
    return f"{d:%b} {d.day}, {d.year}"


def _xs_link_line(row) -> str:
    opened = (f"opened {row['opens']} time{'s' if row['opens'] != 1 else ''}, last on "
              f"{_xs_day(row['last_opened_on'])}" if row["opens"] else "not opened yet")
    return (f"Made {_xs_day(row['created_at'])} · works until {_xs_day(row['expires_at'])} · "
            + ("shows your first name" if row["show_name"] else "no name shown")
            + f" · {opened}")


def render_explain_share():
    """The Life page's "Explain it to someone" (the login's own only)."""
    if not _xs_own():
        return
    conn = connect(DB)
    try:
        links = xs.active(conn, LOGIN_ID)
        name = xs.owner_first_name(conn, LOGIN_ID)
        preview = xs.page(conn, LOGIN_ID, show_name=bool(st.session_state.get("xs_name")))
    finally:
        conn.close()
    st.subheader(xs.OWNER_TITLE, anchor="explain-it")
    st.caption(xs.OWNER_INTRO)
    st.caption(f":material/lock: {xs.OWNER_NEVER}")
    msg = st.session_state.pop("xs_msg", None)
    if msg:
        st.caption(f":material/check: {msg}")
    new = st.session_state.get("xs_new")
    if new:
        with st.container(border=True, key="pt_xs_new"):
            st.markdown("**Your new link**")
            st.code(new, language=None, wrap_lines=True)
            st.caption(xs.SHOWN_ONCE)
            st.button("Done", key="xs_done", type="tertiary", on_click=_xs_done)
    with st.container(border=True, key="pt_xs_make"):
        if name:
            st.checkbox(f"Show my first name ({name})", key="xs_name", value=False)
        else:
            st.checkbox("Show my first name", key="xs_name", value=False, disabled=True,
                        help="Add the name you'd like to be called on your Account page "
                             "to show it.")
        st.selectbox("The link works for", xs.DAYS_CHOICES, index=0, key="xs_days",
                     format_func=lambda d: f"{d} days")
        with st.expander("What they'll see"):
            _xs_body(preview)
        full = len(links) >= xs.MAX_ACTIVE
        st.button("Make a link", key="xs_make", icon=":material/link:", disabled=full,
                  on_click=_xs_create)
        if full:
            st.caption(xs.TOO_MANY)
    if links:
        st.markdown("**Your working links**")
        for row in links:
            with st.container(horizontal=True, vertical_alignment="center",
                              key=f"pt_xs_row_{row['id']}"):
                st.caption(_xs_link_line(row), width="stretch")
                st.button("Turn off", key=f"xs_off_{row['id']}", type="tertiary",
                          on_click=_xs_revoke, args=(row["id"],))
        if len(links) > 1:
            st.button("Turn all off", key="xs_off_all", type="tertiary",
                      on_click=_xs_revoke_all)
    st.caption(xs.OWNER_EXPIRY)
