# Part of dashboard.py, which runs this file with _view("directory") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what
# this defines is visible there afterwards. See _view() in dashboard.py.
#
# The advisor directory (directory.py; flag `directory`, gate L2 - this view
# isn't run at all while either is off): "Find a guide", the page an
# individual opens from their name menu (never in client mode, never for an
# advisor), and "Your directory listing", the advisor's own section on Your
# clients (_render_clients calls it when flags.on("directory")).
#
# Find a guide lists advisors alphabetically by name within the person's own
# filters (directory.listings) - nothing ranked or featured. Nothing about
# browsing is written or counted: the filters live in this browser session
# only. "Request an introduction" opens the intro form (views/intros.py,
# flag `intros`) - only an intro actually sent is written; with that flag off
# it says introductions open soon (directory.request_intro_placeholder).
# ruff: noqa: F821

import directory


def _dir_md(text):
    """Plain text the advisor typed, shown as typed inside st.markdown."""
    return _md_name(text).replace("\n", "  \n")


def _dir_request_intro(advisor_id):
    if flags.on("intros"):
        # opens the intro form in this card (views/intros.py) - nothing is
        # written until the person sends it
        st.session_state["intro_to"] = advisor_id
        return
    # the intro flow is off: nothing is sent, saved or counted - see
    # directory.request_intro_placeholder
    result = directory.request_intro_placeholder(LOGIN_ID, advisor_id)
    st.session_state["dir_intro"] = (advisor_id, result["message"])


def _dir_filters():
    """The person's filters, from this session's widgets only (never saved)."""
    g = st.session_state.get
    return {"state": g("dir_f_state"), "meeting": g("dir_f_meeting"),
            "fee_models": g("dir_f_fees") or [], "serves": g("dir_f_serves") or [],
            "minimum": g("dir_f_min")}


def _dir_listing_card(p):
    words = directory.describe(p)
    uid = p["user_id"]
    with st.container(border=True, key=f"dir_card_{uid}"):
        creds = ", ".join(p["credentials"])
        st.markdown(f"**{_dir_md(p['display_name'])}**"
                    + (f" · {_dir_md(creds)}" if creds else "")
                    + f"  \n{_dir_md(p['firm'])}")
        found = directory.lookup(p)
        reg = f"{words['reg_type']} · CRD {_dir_md(p['reg_number'])}"
        if found:
            reg += f" · [Public record on {found[0]}]({found[1]})"
        st.caption(reg)
        where = ("every state" if words["all_states"] else ", ".join(words["states"]))
        lines = [("Fees", ", ".join(words["fee_models"])),
                 ("Account minimum", words["minimum"]),
                 ("Works with", ", ".join(words["serves"])),
                 ("Meets clients", words["meeting"]),
                 ("Serves clients in", where)]
        st.markdown("  \n".join(f"**{k}:** {v}" for k, v in lines).replace("$", r"\$"))
        st.markdown(_dir_md(p["description"]))
        with st.container(horizontal=True, gap="small"):
            st.button("Request an introduction", key=f"dir_intro_{uid}",
                      on_click=_dir_request_intro, args=(uid,))
            if p["scheduling_url"]:
                st.link_button("Their own scheduling page", p["scheduling_url"],
                               type="tertiary", icon=":material/open_in_new:")
        shown = st.session_state.get("dir_intro")
        if shown and shown[0] == uid:
            st.info(shown[1], icon=":material/schedule:")
        if flags.on("intros") and st.session_state.get("intro_to") == uid:
            _intro_compose(p)   # views/intros.py


def _render_find_a_guide():
    """Find a guide: the copy (DRAFT under L2), the B4 filters, and the
    listings alphabetically by name."""
    if flags.on("intros"):
        _render_my_intros()   # the person's own introductions (views/intros.py)
    st.write(directory.INTRO)
    with st.container(border=True):
        for line in directory.ABOUT_LINES:
            st.markdown(line)
    if STAGING and directory.COPY_STATUS == "DRAFT":
        st.caption("Draft wording - for review under legal gate L2.")

    st.subheader("Filters", anchor=False)
    c1, c2 = st.columns(2)
    states = dict(directory.STATES)
    c1.selectbox("Your state", [None, *states], key="dir_f_state",
                 format_func=lambda k: "Any state" if k is None else states[k],
                 help="Advisors are shown only for the states they serve. Not saved.")
    meeting = {"virtual": "Virtual", "in_person": "In person"}
    c2.radio("Meeting", [None, *meeting], key="dir_f_meeting", horizontal=True,
             format_func=lambda k: "Either" if k is None else meeting[k],
             help="An advisor who meets both ways shows for either.")
    fees = dict(directory.FEE_MODELS)
    c1.multiselect("Fee model", list(fees), key="dir_f_fees", format_func=fees.get,
                   placeholder="Any")
    mins = dict(directory.MINIMUM_FILTER)
    c2.selectbox("Account minimum", [None, *mins], key="dir_f_min",
                 format_func=lambda k: "Any minimum" if k is None else mins[k].replace(
                     "$", r"\$"))
    serves = dict(directory.SERVES)
    st.multiselect("Who they work with", list(serves), key="dir_f_serves",
                   format_func=serves.get, placeholder="Anyone")

    conn = connect(DB)
    try:
        everyone = directory.visible(conn)
    finally:
        conn.close()
    shown = [p for p in everyone if directory.matches(p, _dir_filters())]
    st.caption(f"{directory.ORDER_LINE} {directory.PRIVACY_LINE}")
    if not everyone:
        st.write(directory.NONE_YET)
        return
    if not shown:
        st.write(directory.NONE_MATCH)
        return
    for p in shown:
        _dir_listing_card(p)


# ---- the advisor's own listing (Your clients) ------------------------------ #
_DIR_FORM = ("display_name", "firm", "reg_type", "reg_number", "credentials", "fee_models",
             "minimum", "serves", "states", "meeting", "description", "scheduling_url")


def _dir_form_defaults(profile, card):
    """Fill the form's keys once a session: the saved listing, else the
    name and firm from How clients see you."""
    if st.session_state.get("dir_p_loaded"):
        return
    p = profile or {"display_name": card.get("name") or "", "firm": card.get("firm") or ""}
    for f in _DIR_FORM:
        value = p.get(f)
        if f == "credentials":
            value = ", ".join(value or [])
        elif f in ("fee_models", "serves", "states"):
            value = list(value or [])
        elif f in ("reg_type", "minimum", "meeting"):
            value = value or None
        else:
            value = value or ""
        st.session_state[f"dir_p_{f}"] = value
    st.session_state["dir_p_all_states"] = bool(
        profile and len(profile.get("states") or []) == len(directory.STATES))
    st.session_state["dir_p_listed"] = bool(profile and profile.get("listed"))
    st.session_state["dir_p_loaded"] = True


def _dir_save_listing():
    g = st.session_state.get
    fields = {f: g(f"dir_p_{f}") for f in _DIR_FORM}
    if g("dir_p_all_states"):
        fields["states"] = [k for k, _ in directory.STATES]
    c = connect(DB)
    try:
        result = directory.save_profile(c, LOGIN_ID, fields, listed=bool(g("dir_p_listed")))
    finally:
        c.close()
    st.session_state["dir_p_msg"] = (
        ("success", "Saved." + (" Your listing is on." if g("dir_p_listed") else ""))
        if result["ok"] else ("error", " ".join(result["errors"])))


def _dir_delete_listing():
    c = connect(DB)
    try:
        directory.delete_profile(c, LOGIN_ID)
    finally:
        c.close()
    st.session_state.pop("dir_p_loaded", None)
    st.session_state["dir_p_msg"] = ("success", "Your listing is deleted.")


def _render_directory_listing():
    """Your directory listing: what individuals see on Find a guide, edited
    by the advisor. No counts of views or clicks - there are none."""
    st.subheader("Your directory listing", anchor=False)
    conn = connect(DB)
    try:
        profile = directory.get_profile(conn, LOGIN_ID)
        card = prefs.load(conn, LOGIN_ID).get("advisor_card") or {}
        why = directory.why_not_shown(conn, LOGIN_ID)
    finally:
        conn.close()
    if why:
        st.caption(":material/visibility_off: Not shown in Find a guide: " + " ".join(why))
    else:
        st.caption(":material/check_circle: Shown in Find a guide.")
    st.caption("People browsing Find a guide see listings in alphabetical order by name, "
               "within their own filters. No one can pay for a place in the list, and "
               "Northwend doesn't count views or clicks.")
    msg = st.session_state.pop("dir_p_msg", None)
    if msg:
        (st.success if msg[0] == "success" else st.error)(msg[1])
    _dir_form_defaults(profile, card)
    with st.expander("Edit your listing", expanded=profile is None):
        with st.form("dir_listing_form", border=False):
            c1, c2 = st.columns(2)
            c1.text_input("Name as shown", key="dir_p_display_name",
                          max_chars=directory.LIMITS["display_name"])
            c2.text_input("Firm", key="dir_p_firm", max_chars=directory.LIMITS["firm"])
            regs = {k: label for k, label, _ in directory.REG_TYPES}
            c1.selectbox("Registration type", list(regs), key="dir_p_reg_type",
                         format_func=regs.get, index=None, placeholder="Choose one")
            c2.text_input("Your CRD number", key="dir_p_reg_number",
                          max_chars=directory.LIMITS["reg_number"],
                          help="Your listing links to your public record on the SEC's "
                               "Investment Adviser Public Disclosure or FINRA BrokerCheck.")
            st.text_input("Credentials (optional)", key="dir_p_credentials",
                          placeholder="e.g. CFP®, CFA - separated by commas",
                          help="Shown on your listing. People can't filter on them.")
            fees = dict(directory.FEE_MODELS)
            c1, c2 = st.columns(2)
            c1.multiselect("Fee model", list(fees), key="dir_p_fee_models",
                           format_func=fees.get, placeholder="Any that apply")
            mins = dict(directory.MINIMUMS)
            c2.selectbox("Account minimum", list(mins), key="dir_p_minimum",
                         format_func=lambda k: mins[k].replace("$", r"\$"), index=None,
                         placeholder="Choose one")
            serves = dict(directory.SERVES)
            st.multiselect("Who you work with", list(serves), key="dir_p_serves",
                           format_func=serves.get, placeholder="Any that apply")
            states = dict(directory.STATES)
            st.multiselect("States you serve", list(states), key="dir_p_states",
                           format_func=states.get, placeholder="Where you're able to work")
            st.checkbox("Every state and DC", key="dir_p_all_states")
            meeting = dict(directory.MEETING)
            st.radio("How you meet clients", list(meeting), key="dir_p_meeting",
                     format_func=meeting.get, horizontal=True, index=None)
            st.text_area("A short description", key="dir_p_description",
                         max_chars=directory.LIMITS["description"],
                         help="Plain text: no links or email addresses.")
            st.text_input("Scheduling link (optional)", key="dir_p_scheduling_url",
                          max_chars=directory.LIMITS["scheduling_url"],
                          placeholder="https://...",
                          help="Your own calendar tool's page. It must start with https://")
            st.checkbox("List me in Find a guide", key="dir_p_listed")
            st.form_submit_button("Save listing", type="primary", on_click=_dir_save_listing)
        if profile is not None:
            st.button("Delete my listing", key="dir_p_delete", type="tertiary",
                      on_click=_dir_delete_listing)
