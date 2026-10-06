# Part of dashboard.py, which runs this file with _view("account_map") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what
# this defines is visible there afterwards. See _view() in dashboard.py.
#
# Account map (ROADMAP 10, account_map.py): the "if something happens to me"
# binder, on the Account page - the login's own account (LOGIN_ID) always,
# so an advisor looking at a client's account never sees the client's map.
# Each account brought in, what the person fills in for it, accounts added
# by hand, notes for family, a PDF only they download, and a short guide to
# finding old accounts (with flag lost_found on, Lost & Found just below -
# views/lost_found.py - takes its place; the PDF keeps the short guide). Home shows one line (render_account_map_nudge) when
# there are 2+ accounts and no map yet, until it's made or put away.
# ruff: noqa: F821

import account_map

AMAP_NUDGE_OFF = "account_map_nudge_off"
_AMAP_NOT_SET = "Not filled in"


def _amap_msg(kind, text):
    st.session_state["amap_msg"] = (kind, text)


def _amap_fields(prefix):
    g = st.session_state.get
    kind = g(f"{prefix}_kind")
    return {"kind": None if kind == _AMAP_NOT_SET else kind, "contact": g(f"{prefix}_contact"),
            "phone": g(f"{prefix}_phone"), "beneficiary": g(f"{prefix}_beneficiary"),
            "paperwork": g(f"{prefix}_paperwork"), "notes": g(f"{prefix}_notes")}


def _amap_secret_note(*texts):
    return any(account_map.looks_secret(t) for t in texts)


def _amap_save_account(account, prefix):
    fields = _amap_fields(prefix)
    c = connect(DB)
    try:
        account_map.save_account(c, LOGIN_ID, account, fields)
    finally:
        c.close()
    if _amap_secret_note(fields["notes"], fields["paperwork"], fields["contact"]):
        _amap_msg("warning", "Saved. One of your notes looks like it might hold a password or "
                  "login - please take it out. Say where to find it instead (for example, "
                  "\"in the password manager\").")
    else:
        _amap_msg("success", "Saved.")


def _amap_save_other(other_id, prefix):
    fields = {**_amap_fields(prefix), "label": st.session_state.get(f"{prefix}_label"),
              "digits": st.session_state.get(f"{prefix}_digits")}
    c = connect(DB)
    try:
        saved = account_map.save_other(c, LOGIN_ID, fields, other_id)
    finally:
        c.close()
    if not saved:
        _amap_msg("error", "Give the account a name first.")
        return
    if other_id is None:   # an empty form for the next one
        for k in ("label", "digits", "kind", "contact", "phone", "beneficiary", "paperwork",
                  "notes"):
            st.session_state.pop(f"{prefix}_{k}", None)
    _amap_msg("warning" if _amap_secret_note(fields["notes"], fields["paperwork"])
              else "success",
              "Saved. One of your notes looks like it might hold a password - please take it "
              "out." if _amap_secret_note(fields["notes"], fields["paperwork"]) else "Saved.")


def _amap_delete(entry_id):
    c = connect(DB)
    try:
        account_map.delete_entry(c, LOGIN_ID, entry_id)
    finally:
        c.close()
    _amap_msg("success", "Removed.")


def _amap_save_family():
    text = st.session_state.get("amap_family") or ""
    c = connect(DB)
    try:
        account_map.save_family(c, LOGIN_ID, text)
    finally:
        c.close()
    if account_map.looks_secret(text):
        _amap_msg("warning", "Saved. Your notes look like they might hold a password, PIN or "
                  "login - please take it out. Say where to find it instead.")
    else:
        _amap_msg("success", "Saved your notes for family.")


def _amap_clear():
    c = connect(DB)
    try:
        account_map.clear(c, LOGIN_ID)
    finally:
        c.close()
    for k in [k for k in st.session_state if str(k).startswith("amap_")]:
        st.session_state.pop(k, None)
    _amap_msg("success", "Your account map was deleted.")


def _amap_form(prefix, entry, *, guess=None, on_save, args, extra=None):
    """The fields for one account, in a form: its kind, who to call, a
    beneficiary named, where the paperwork is, a note."""
    kinds = (_AMAP_NOT_SET, *account_map.KINDS)
    kind = entry.get("kind") or guess
    with st.form(f"{prefix}_form", border=False):
        if extra:
            extra()
        st.selectbox("Kind of account", kinds, key=f"{prefix}_kind",
                     index=kinds.index(kind) if kind in kinds else 0,
                     help="A guess from its name when you haven't chosen one yet.")
        c1, c2 = st.columns(2)
        c1.text_input("Who to call", key=f"{prefix}_contact", value=entry.get("contact") or "",
                      max_chars=account_map.LIMITS["contact"],
                      placeholder="e.g. the brokerage's help line, or Ann at the bank")
        c2.text_input("Phone", key=f"{prefix}_phone", value=entry.get("phone") or "",
                      max_chars=account_map.LIMITS["phone"])
        st.radio("Beneficiary named?", account_map.BENEFICIARY, key=f"{prefix}_beneficiary",
                 index=(account_map.BENEFICIARY.index(entry["beneficiary"])
                        if entry.get("beneficiary") in account_map.BENEFICIARY else None),
                 horizontal=True,
                 help="Who the account goes to is set with the brokerage or plan, not in a "
                      "will. \"Not sure\" is a fine answer - it's worth checking.")
        st.text_input("Where the paperwork is", key=f"{prefix}_paperwork",
                      value=entry.get("paperwork") or "",
                      max_chars=account_map.LIMITS["paperwork"],
                      placeholder="e.g. blue folder in the desk; statements by email")
        st.text_area("Notes", key=f"{prefix}_notes", value=entry.get("notes") or "",
                     max_chars=account_map.LIMITS["notes"], height=80,
                     placeholder="Anything that would help - never a password")
        st.form_submit_button("Save", on_click=on_save, args=args)


def _amap_value(a):
    if a["gone"]:
        return "No longer in your holdings"
    return f"About {fmt_money(a['value'])} · as of {_fmt_date(a['as_of'])}"


def render_account_map():
    """The Account page's Account map section."""
    c = connect(DB)
    try:
        m = account_map.load(c, LOGIN_ID, accounts.labels(c, LOGIN_ID))
    finally:
        c.close()
    st.subheader("Account map", anchor=False)
    st.caption("An \"if something happens to me\" list for the people you trust: each "
               "account, who to call, whether a beneficiary is named and where the paperwork "
               "is. Private to you - never shown to an advisor, never emailed. Download it as "
               "a PDF and keep it somewhere safe.")
    msg = st.session_state.pop("amap_msg", None)
    if msg:
        getattr(st, msg[0])(msg[1])
    st.session_state.pop("amap_open", None)   # (Home's "Make one" lands here)
    st.caption(":material/lock: Please never write passwords, PINs or full account numbers "
               "here. Say where to find them instead - for example, \"my spouse knows the "
               "password manager\". Account numbers show their last 3 digits only.")

    if m["pretend"]:
        st.caption("The example or percentages portfolio isn't a real account, so it isn't "
                   "listed. Bring in your own holdings, or add accounts by hand below.")
    elif not m["accounts"]:
        st.caption("Nothing brought in yet. Add accounts by hand below, or bring in your "
                   "holdings and they'll be listed here.")
    for i, a in enumerate(m["accounts"]):
        done = any(a.get(f) for f in account_map.FIELDS)
        head = (f"**{a['name']}**" + (f" · ...{a['digits']}" if a["digits"]
                                      and f"...{a['digits']}" not in a["name"] else "")
                + f" · {_amap_value(a)}" + (" · filled in" if done else ""))
        with st.expander(head.replace("$", r"\$"), icon=":material/account_balance:"):
            _amap_form(f"amap_a{i}", a, guess=a["guess"], on_save=_amap_save_account,
                       args=(a["account"], f"amap_a{i}"))
            if a["gone"] and a["id"]:
                st.button("Remove from the map", key=f"amap_rm_a{i}", type="tertiary",
                          on_click=_amap_delete, args=(a["id"],))

    for o in m["others"]:
        pre = f"amap_o{o['id']}"
        with st.expander(f"**{o['label']}**" + (f" · ...{o['digits']}" if o["digits"] else "")
                         + " · added by hand", icon=":material/account_balance_wallet:"):
            def _names(o=o, pre=pre):
                c1, c2 = st.columns([3, 1])
                c1.text_input("Name", key=f"{pre}_label", value=o["label"],
                              max_chars=account_map.LIMITS["label"])
                c2.text_input("Last 3 digits", key=f"{pre}_digits", value=o["digits"] or "",
                              max_chars=3)
            _amap_form(pre, o, on_save=_amap_save_other, args=(o["id"], pre), extra=_names)
            st.button("Remove", key=f"amap_rm_o{o['id']}", type="tertiary",
                      on_click=_amap_delete, args=(o["id"],))
    with st.expander("Add another account - a bank account, an old 401(k), a pension, "
                     "life insurance", icon=":material/add:"):
        def _new_names():
            c1, c2 = st.columns([3, 1])
            c1.text_input("Name", key="amap_new_label", max_chars=account_map.LIMITS["label"],
                          placeholder="e.g. Credit union savings")
            c2.text_input("Last 3 digits", key="amap_new_digits", max_chars=3,
                          help="Only the last 3 - never the whole number.")
        _amap_form("amap_new", {}, on_save=_amap_save_other, args=(None, "amap_new"),
                   extra=_new_names)

    with st.expander("Notes for family" + (" · written" if m["family"] else ""),
                     icon=":material/family_restroom:"):
        with st.form("amap_family_form", border=False):
            st.text_area("Notes for family", key="amap_family", value=m["family"] or "",
                         max_chars=account_map.LIMITS["family"], height=140,
                         label_visibility="collapsed",
                         placeholder="e.g. My spouse knows the password manager. Our lawyer "
                                     "is ... The will is in the safe at home.")
            st.form_submit_button("Save notes", on_click=_amap_save_family)

    with st.container(horizontal=True, vertical_alignment="center"):
        st.download_button(
            "Download my account map (PDF)",
            account_map.render_pdf(m, name=MY_NAME, app_name=APP_NAME),
            file_name=account_map.file_name(), mime="application/pdf", key="amap_pdf",
            on_click="ignore", icon=":material/download:",
            help="Only you download it - it's never emailed or shown to anyone. It includes "
                 "rough values, so keep it somewhere safe.")
        if m["made"]:
            with st.popover("Delete the map", icon=":material/delete:", type="tertiary"):
                st.caption("Deletes everything you filled in here. The accounts themselves "
                           "aren't touched.")
                st.button("Delete my account map", key="amap_clear", on_click=_amap_clear)
    if m["updated_at"]:
        st.caption(f"Last changed {_fmt_date(m['updated_at'][:10])}. Worth a look once a year, "
                   "or when something changes.")

    if flags.on("lost_found") and USER_ID == LOGIN_ID:
        # Lost & Found, just below, goes further (views/lost_found.py)
        st.caption(":material/travel_explore: Looking for an old 401(k) or forgotten "
                   "account? **Lost & Found**, just below, shows where to look.")
        return
    with st.expander("Finding old accounts", icon=":material/travel_explore:"):
        st.caption("Money can get left behind when you change jobs, move or a company "
                   "changes hands. These free places help you look - none of them ever "
                   "charges to find or claim what's yours.")
        for title, text, links in account_map.FIND_OLD:
            st.markdown(f"**{title}**  \n{text}  \n"
                        + "  \n".join(f"[{t}]({u})" for t, u in links))


def _amap_nudge_off():
    p = _read_prefs()
    p[AMAP_NUDGE_OFF] = True
    _write_prefs(p)


def _amap_nudge_go():
    _amap_nudge_off()   # shown once: going to make one puts the line away too
    st.session_state["amap_open"] = True
    _go("Account")


def render_account_map_nudge():
    """Home: one line, once, when there are two or more real accounts and no
    map yet - until it's made or put away."""
    if USER_ID != LOGIN_ID or SNAPSHOT_SOURCE in (SAMPLE_SOURCE, manual_entry.PCT_SOURCE):
        return
    n = len({p.get("broker_account") or p["account"] for p in positions} | set(cash_by_account))
    if n < 2 or _read_prefs().get(AMAP_NUDGE_OFF):
        return
    c = connect(DB)
    try:
        made = c.execute("SELECT 1 FROM account_map WHERE user_id = ? LIMIT 1",
                         (LOGIN_ID,)).fetchone() is not None
    finally:
        c.close()
    if not account_map.nudge(n, made, False):
        return
    with st.container(horizontal=True, vertical_alignment="center", key="pt_amap_nudge"):
        st.caption(f":material/map: You have {n} accounts. An account map lists them for the "
                   "people you trust - who to call, where the paperwork is. Private to you.",
                   width="stretch")
        st.button("Make one", key="amap_nudge_go", type="tertiary", on_click=_amap_nudge_go)
        st.button("Not now", key="amap_nudge_off", type="tertiary", on_click=_amap_nudge_off)
