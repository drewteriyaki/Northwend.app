# Part of dashboard.py, which runs this file with _view("lost_found") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Lost & Found (ROADMAP R9, lost_found.py), behind flag lost_found
# (flags.FEATURES - this whole file is skipped while it's off): on the Account
# page, just under the account map (views/account.py calls render_lost_found).
# Where to look for money someone already owns - old workplace plans, state
# unclaimed property, an old HSA, FSA or IRA, savings bonds - with official
# links only; the employer match opens the Free money check
# (views/free_money.py) instead of repeating it; an old 401(k)'s common choices
# side by side with questions to ask, never which one. Their own checklist
# ("places I've looked") is kept in the login's own settings (prefs
# lost_found.PREF): statuses only - never an amount, a number or a name.
#
# Only ever the login's own: never drawn while an advisor is in a client's
# account (USER_ID != LOGIN_ID), never sent to the AI. A client signed in
# themselves sees it (their own money, education only); for them the IRA's
# brokerages list gives way to a line about their advisor.
# ruff: noqa: F821

import brokerages
import lost_found


def _lf_own():
    """Only ever the login's own list (also in a callback, a run later)."""
    return USER_ID == LOGIN_ID


def _lf_set(place):
    if not _lf_own():
        return
    label = st.session_state.get(f"lf_place_{place}")
    status = next((k for k, v in lost_found.STATUSES.items() if v == label), lost_found.NOT_YET)
    _write_prefs(lost_found.with_status(_read_prefs(), place, status))


def _lf_clear():
    if not _lf_own():
        return
    _write_prefs(lost_found.cleared(_read_prefs()))
    for place in lost_found.PLACE_KEYS:
        st.session_state.pop(f"lf_place_{place}", None)
    st.session_state["lf_msg"] = "Your list was cleared."


def _lf_md(text):
    """Text for st.markdown: dollar signs aren't a formula."""
    return str(text).replace("$", r"\$")


def _lf_links(links):
    return "  \n".join(f"[{t}]({u})" for t, u in links)


def _lf_section(key, title, icon, paras, links, ready):
    with st.expander(title, icon=icon):
        for p in paras:
            st.markdown(_lf_md(p))
        if ready:
            st.markdown("**What to have ready**  \n"
                        + "\n".join(f"- {_lf_md(r)}" for r in ready))
        st.markdown(_lf_links(links))


def _lf_options():
    with st.expander(lost_found.OPTIONS_TITLE, icon=":material/alt_route:"):
        st.markdown(_lf_md(lost_found.OPTIONS_INTRO))
        for title, words in lost_found.OPTIONS:
            st.markdown(f"**{title}** - {_lf_md(words)}")
        st.markdown(f"**{lost_found.QUESTIONS_LEAD}**  \n"
                    + "\n".join(f"- {_lf_md(q)}" for q in lost_found.QUESTIONS))
        st.markdown(_lf_links(lost_found.OPTIONS_LINKS))
        if IS_MANAGED_CLIENT:
            st.markdown(f"Your advisor, {_md_name(_advisor_display_name())}, can talk these "
                        "choices through with you as well.")
        else:
            st.markdown(f"{lost_found.IRA_LEAD}\n\n{brokerages.list_markdown()}")
            st.caption(f"{brokerages.NOT_RANKED} {brokerages.OTHERS}")


def _lf_checklist():
    saved = _read_prefs().get(lost_found.PREF)
    places = lost_found.clean_saved(saved)["places"]
    with st.container(border=True, key="pt_lf_list"):
        st.markdown("**Places I've looked**")
        st.caption("Your own list, to pick up where you left off. Only you see it.")
        msg = st.session_state.pop("lf_msg", None)
        if msg:
            st.caption(f":material/check: {msg}")
        options = list(lost_found.STATUSES.values())   # shown as words, kept as statuses
        for i, (place, label) in enumerate(lost_found.PLACES):
            if i % 2 == 0:   # a row of two (one under the other on a phone, in order)
                cols = st.columns(2)
            now = places.get(place, lost_found.NOT_YET)
            cols[i % 2].selectbox(label, options, index=options.index(lost_found.STATUSES[now]),
                                  key=f"lf_place_{place}", on_change=_lf_set, args=(place,))
        s = lost_found.summary(saved)
        if s["looked"]:
            st.caption(f"Looked in {s['looked']} of {s['of']} places"
                       + (f" · found something in {s['found']}" if s["found"] else "")
                       + ".")
        if s["found"]:
            st.markdown(f":material/inventory_2: {lost_found.FOUND_NEXT}")
            if CAN_IMPORT:
                with st.container(horizontal=True):
                    st.button("Paste or type holdings", key="lf_add_manual", type="tertiary",
                              icon=":material/content_paste:",
                              on_click=_open_holdings_dialog, args=("manual",))
                    st.button("Upload a CSV", key="lf_add_import", type="tertiary",
                              icon=":material/upload_file:",
                              on_click=_open_holdings_dialog, args=("import",))
        if places:
            st.button("Clear my list", key="lf_clear", type="tertiary", on_click=_lf_clear)


def render_lost_found():
    """The Account page's Lost & Found section (the login's own only)."""
    if not _lf_own():
        return
    st.subheader("Lost & Found", anchor="lost-and-found")
    st.caption(lost_found.INTRO)
    st.caption(f":material/lock: {lost_found.PRIVATE}")
    for key, title, icon, paras, links, ready in lost_found.SECTIONS:
        _lf_section(key, title, icon, paras, links, ready)
    with st.container(border=True, horizontal=True, vertical_alignment="center",
                      key="pt_lf_match"):
        st.markdown(f":material/redeem: **{lost_found.MATCH_TITLE}** - "
                    f"{_lf_md(lost_found.MATCH_TEXT)}", width="stretch")
        if st.button("Work it out", key="lf_match_open", type="tertiary",
                     icon=":material/open_in_new:"):
            open_free_money_window()   # views/free_money.py
    _lf_options()
    _lf_checklist()
    st.caption(lost_found.NOT_ADVICE)
