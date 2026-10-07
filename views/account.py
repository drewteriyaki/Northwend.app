# Part of dashboard.py, which runs this file with _view("account") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# The Account page: the signed-in person's own account - what's on it, their
# name, email (changed only through a link to the new address), password,
# other signed-in devices, two-step sign-in (set up with views/two_step.py's
# steps), a copy of their data, leaving themselves out of feature counts
# (feature_counts.py), and deleting it. Always the
# login's own account (LOGIN_ID), even while an advisor is viewing a client.
# ruff: noqa: F821

import access_log
import admin
import consent
import feature_counts
import trail_conditions
import two_step


def _acct_msg(kind, text):
    st.session_state["acct_msg"] = (kind, text)


def _acct_save_name():
    c = connect(DB)
    try:
        auth.set_display_name(c, st.session_state["user_id"], st.session_state.get("acct_name"))
    finally:
        c.close()
    _acct_msg("success", "Saved your name.")


def _acct_show_all():
    p = _read_prefs()
    p["show_everything"] = bool(st.session_state.get("acct_show_all"))
    _write_prefs(p)


def _acct_counts_off():
    """"Leave me out of feature counts" (feature_counts.PREF_OFF), on the
    login's own settings - honoured by every count from then on."""
    c = connect(DB)
    try:
        p = prefs.load(c, LOGIN_ID)
        p[feature_counts.PREF_OFF] = bool(st.session_state.get("acct_counts_off"))
        prefs.save(c, LOGIN_ID, p)
    finally:
        c.close()
    st.session_state.pop("_prefs", None)   # read afresh (_read_prefs)


def _acct_trail_switch():
    """Trail Conditions on or off (trail_conditions.set_on), on the login's
    own settings: on keeps the time of consent, off stops it at once."""
    c = connect(DB)
    try:
        p = prefs.load(c, LOGIN_ID)
        trail_conditions.set_on(p, bool(st.session_state.get("acct_trail")))
        prefs.save(c, LOGIN_ID, p)
    finally:
        c.close()
    st.session_state.pop("_prefs", None)   # read afresh (_read_prefs)


def _render_trail_switch(confirmed_email):
    """The opt-in Monday email (flag trail_conditions): off unless turned on,
    only to a confirmed email, never for an advisor's own login."""
    if IS_ADVISOR:
        return
    c = connect(DB)
    try:
        on = trail_conditions.is_on(prefs.load(c, LOGIN_ID))
    finally:
        c.close()
    st.subheader(trail_conditions.SWITCH_LABEL, anchor=False)
    st.session_state["acct_trail"] = on
    st.toggle("Email me Trail Conditions", key="acct_trail", on_change=_acct_trail_switch,
              disabled=not confirmed_email and not on)
    st.caption(trail_conditions.SWITCH_HELP + " Off unless you turn it on."
               + ("" if confirmed_email else
                  " It needs a confirmed email - see Email, just below."))


def _render_counts_switch():
    c = connect(DB)
    try:
        off = feature_counts.left_out(prefs.load(c, LOGIN_ID))
    finally:
        c.close()
    st.session_state["acct_counts_off"] = off
    st.toggle("Leave me out of feature counts", key="acct_counts_off",
              on_change=_acct_counts_off)
    st.caption("To learn whether features like the monthly walk help, Northwend counts in "
               "totals only, inside its own database - never you by name, only groups of 20 "
               "or more, never shared or sold, and never sent to the AI. Turn this on and "
               "you're left out of every count.")


def _acct_change_email():
    c = connect(DB)
    try:
        res = auth.start_email_change(c, st.session_state["user_id"],
                                      st.session_state.get("acct_new_email") or "",
                                      st.session_state.get("acct_email_pw") or "",
                                      ip=_visitor_ip())
    finally:
        c.close()
    st.session_state["acct_email_pw"] = ""
    if not res["ok"]:
        _acct_msg("error", res["error"])
        return
    sent = mailer.confirm_new_email(res["to"], f"{_app_address()}?email_change={res['token']}",
                                    auth.CONFIRM_DAYS)
    st.session_state["acct_new_email"] = ""
    _acct_msg("success" if sent else "warning",
              f"We sent a link to {res['to']}. Your email changes when you open it."
              if sent else "The email couldn't be sent just now. Please try again in a minute.")


def _acct_cancel_email():
    c = connect(DB)
    try:
        auth.cancel_email_change(c, st.session_state["user_id"])
    finally:
        c.close()
    _acct_msg("success", "Cancelled - your email stays as it is.")


def _acct_sign_out_others():
    c = connect(DB)
    try:
        n = auth.end_other_sessions(c, st.session_state["user_id"],
                                    st.session_state.get("session_token"))
        # the login's session number went up: this tab notes the new one and
        # stays signed in; tabs open anywhere else land on sign-in (audit X5)
        st.session_state["session_gen"] = auth.session_gen(c, st.session_state["user_id"])
    finally:
        c.close()
    _acct_msg("success", f"Signed out {n} other device{'s' if n != 1 else ''}, and any other "
              "open tabs." if n else "Signed out anywhere else this account was open.")


def _acct_two_step_start():
    st.session_state["acct_two_step_setup"] = True
    st.session_state.pop("two_step_secret", None)   # a fresh key each time


def _acct_two_step_cancel():
    st.session_state.pop("acct_two_step_setup", None)
    st.session_state.pop("two_step_secret", None)


def _acct_two_step(action):
    """'off' or 'codes' (new backup codes), after a code or the password."""
    uid = st.session_state["user_id"]
    answer = st.session_state.get("acct_two_step_answer") or ""
    c = connect(DB)
    try:
        res = (two_step.disable(c, uid, answer) if action == "off"
               else two_step.new_backup_codes(c, uid, answer))
    finally:
        c.close()
    st.session_state["acct_two_step_answer"] = ""
    if not res["ok"]:
        _acct_msg("error", res["error"])
        return
    if action == "off":
        _two_step_done(None)   # this tab stays signed in
        _acct_msg("success", "Two-step sign-in is off. You can turn it back on here any time.")
    else:
        st.session_state["two_step_codes"] = ("acct", res["backup_codes"])
        _acct_msg("success", "Here are your new backup codes - the old ones no longer work.")


def _render_two_step(state):
    """The two-step sign-in part of Password and devices."""
    st.markdown("**Two-step sign-in**")
    if state["on"]:
        st.session_state.pop("acct_two_step_setup", None)
        st.caption(":material/verified_user: On - after your password, you type a code from "
                   "the app on your phone. "
                   + (f"{state['backup_left']} backup code{'s' if state['backup_left'] != 1 else ''}"
                      " left." if state["backup_left"] else "No backup codes left - make new "
                                                          "ones below.")
                   + (" It's always on for advisor and admin accounts." if state["required"]
                      else ""))
        _two_step_codes_box("acct")
        with st.expander("Backup codes" if state["required"]
                         else "Backup codes, or turn it off"):
            st.text_input("A code from your app, or your password", type="password",
                          key="acct_two_step_answer", autocomplete="one-time-code")
            with st.container(horizontal=True):
                st.button("Make new backup codes", key="acct_two_step_codes",
                          on_click=_acct_two_step, args=("codes",))
                if not state["required"]:
                    st.button("Turn off two-step sign-in", key="acct_two_step_off",
                              on_click=_acct_two_step, args=("off",))
            st.caption("New backup codes replace the old ones.")
        return
    if not st.session_state.get("acct_two_step_setup"):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.caption("Add a second step when you sign in: a 6-digit code from an app on your "
                       "phone, so your password alone isn't enough. Optional, and you can turn "
                       "it off again.", width="stretch")
            st.button("Set it up", key="acct_two_step_start", on_click=_acct_two_step_start)
        return
    with st.container(border=True):
        _two_step_setup("acct")
        st.button("Cancel", key="acct_two_step_cancel", type="tertiary",
                  on_click=_acct_two_step_cancel)


def _acct_delete():
    if (st.session_state.get("acct_delete_word") or "").strip().upper() != "DELETE":
        _acct_msg("error", "Type DELETE to confirm.")
        return
    c = connect(DB)
    try:
        res = admin.delete_own(c, st.session_state["user_id"],
                               st.session_state.get("acct_delete_pw") or "")
    finally:
        c.close()
    st.session_state["acct_delete_pw"] = ""
    if not res["ok"]:
        _acct_msg("error", res["error"])
        return
    st.session_state.clear()
    st.session_state["signed_out"] = True   # the cookie is dead already; it's removed too
    st.session_state["login_notice"] = (f"Your account and everything in it was deleted. "
                                        f"Thank you for trying {APP_NAME}.")


def _acct_forget_note(index):
    """Delete one of the guide's notes - the login's own only."""
    import advisor
    c = connect(DB)
    try:
        advisor.forget_note(c, LOGIN_ID, index)
    finally:
        c.close()
    _acct_msg("success", f"{GUIDE} won't remember that any more.")


def _acct_forget_all():
    import advisor
    c = connect(DB)
    try:
        advisor.forget_all(c, LOGIN_ID)
    finally:
        c.close()
    _acct_msg("success", f"{GUIDE}'s notes are gone - the next conversation starts fresh.")


def _render_guide_notes():
    """What Ask Northwend remembers (AI_PLAN section 6): the guide's notes
    from earlier conversations, each with Delete, and Forget everything. The
    login's own notes only - an advisor's conversations in a client's account
    never keep any."""
    import advisor
    c = connect(DB)
    try:
        notes = advisor.get_notes(c, LOGIN_ID)
    finally:
        c.close()
    st.subheader(f"What {GUIDE} remembers", anchor=False)
    if not notes:
        st.caption(f"Nothing yet. {GUIDE} keeps a few short notes between conversations - "
                   "your goals and dates, what it has explained - and they'll show here.")
        return
    st.caption(f"Short notes {GUIDE} keeps between conversations, so the next one picks up "
               "where you left off. Never dollar amounts or account numbers. Delete any you'd "
               "rather it forgot.")
    for i, n in enumerate(notes):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(f"**{advisor.MEMORY_KINDS[n.kind]}:** {_md_name(n.text)}",
                        width="stretch")
            st.button("Delete", key=f"acct_note_del_{i}", type="tertiary",
                      on_click=_acct_forget_note, args=(i,), icon=":material/delete:")
    st.button("Forget everything", key="acct_notes_forget", on_click=_acct_forget_all)


_CONSENT_HOW = {"setup_link": "when you set up your login from their link",
                "intro": "after you asked to work with them",
                "client_stop": "you stopped sharing", "advisor_end": "your advisor ended it",
                "admin": "ended by Northwend support",
                "account_deleted": "an account was closed",
                "migration": "from before these records were kept",
                "sign_in_ask": "when we asked you once, at sign-in",
                "pack_choice": "your choice in Bring to my advisor"}
# access log pages that aren't one of PAGES (advisor_pack.ACCESS_PAGE)
_ACCESS_PAGES = {"advisor_pack": "What you chose to bring"}


def _render_who_looked():
    """Who has looked at your account (access_log.py, brief 4.3.5): each page
    an advisor opened in the login's own account, the last SHOWN_DAYS days,
    and their sharing record (consent.py). Only for someone who has, or had,
    an advisor; always the login's own rows."""
    c = connect(DB)
    try:
        seen = access_log.for_client(c, LOGIN_ID, LOGIN_ID)
        shared = consent.history(c, LOGIN_ID)
    finally:
        c.close()
    if not (seen or shared or IS_MANAGED_CLIENT):
        return

    def who(advisor_id, name):
        if advisor_id == MY_ADVISOR:
            return _advisor_display_name()
        return name or "A former advisor"

    st.subheader("Who has looked at your account", anchor=False)
    st.caption(f"Each time an advisor opens a page in your account, it's noted here: who, "
               f"which page and when - never what was on it. The last {access_log.SHOWN_DAYS} "
               "days are shown; your data download has them all. Only you see this list.")
    if seen:
        st.dataframe(pd.DataFrame([{"When": _fmt_when(r["at"]),
                                    "Who": who(r["advisor_id"], r["advisor"]),
                                    "Page": _ACCESS_PAGES.get(r["page"], _label(r["page"]))}
                                   for r in seen]),
                     hide_index=True, width="stretch", height=min(36 * (len(seen) + 1) + 2, 320))
    else:
        st.caption(f"No advisor has opened your account in the last {access_log.SHOWN_DAYS} "
                   "days.")
    if shared:
        with st.expander("Your sharing record"):
            for r in shared:
                pack = r["scope"] == consent.ADVISOR_PACK   # Bring to my advisor
                verb = (("You chose things to bring to" if pack else
                         "You agreed to share your account with") if r["kind"] == "grant"
                        else "Bring to my advisor ended with" if pack else "Sharing ended with")
                st.markdown(f"**{_fmt_date(r['at'])}** · {verb} "
                            f"{_md_name(who(r['advisor_id'], r['advisor']))} "
                            f"({_CONSENT_HOW.get(r['how'], r['how'])})")
                if r["text_shown"] and r["how"] != "migration":
                    st.caption(f"What you saw: {_md_name(r['text_shown'])}")
            st.caption("Kept for 7 years after sharing ends, even if an account is deleted, "
                       "to protect you and your advisor. It holds who, when and these "
                       "words - never figures.")


def _acct_facts(c):
    # the login's row and two-step state as the sign-in gate read them at the
    # top of this run (this page is drawn in the full run; its changes are
    # made in callbacks, before the gate's read)
    gate = _gate_read(LOGIN_ID)
    if gate is not None and gate[1] is not None:
        state, row = gate
    else:
        row = c.execute("SELECT username, email, email_verified_at, display_name, created_at, "
                        "last_login_at FROM users WHERE id = ?", (LOGIN_ID,)).fetchone()
        state = two_step.status(c, LOGIN_ID)
    me = {k: row[k] for k in ("username", "email", "email_verified_at", "display_name",
                              "created_at", "last_login_at")}
    sessions = c.execute("SELECT COUNT(*) AS n FROM login_sessions WHERE user_id = ? AND "
                         "expires_at > ?", (LOGIN_ID, datetime.now(timezone.utc)
                                            .strftime("%Y-%m-%d %H:%M:%S"))).fetchone()["n"]
    advisor_id = advising.advisor_of(c, LOGIN_ID)
    advisor = auth.get_username(c, advisor_id) if advisor_id else None
    pending = auth.pending_email_change(c, LOGIN_ID)
    can_delete = not (IS_ADMIN or CLIENTS or advisor_id)
    return me, sessions, advisor, pending, can_delete, state


def _render_account():
    c = connect(DB)
    try:
        me, sessions, advisor, pending, can_delete, two_step_state = _acct_facts(c)
    finally:
        c.close()
    msg = st.session_state.pop("acct_msg", None)
    if msg:
        getattr(st, msg[0])(msg[1])

    # ---- what's on the account -------------------------------------------- #
    kind = ("Admin" + (" · advisor app" if IS_ADVISOR else "") if IS_ADMIN
            else "Advisor" if IS_ADVISOR
            else f"Client of {_advisor_display_name()}" if advisor else "Investor")
    if not me["email"]:
        email_txt = "none yet - add one below to reset your password by email"
    elif me["email_verified_at"]:
        email_txt = f"{me['email']} (confirmed)"
    else:
        email_txt = f"{me['email']} (not confirmed yet)"
    with st.container(border=True):
        st.markdown("\n".join(f"- **{k}:** {v}" for k, v in (
            ("Name", me["display_name"] or "not set"),
            ("Sign in with", me["username"]),
            ("Email", email_txt),
            ("Account", kind),
            ("Member since", _fmt_date(str(me["created_at"])[:10])),
            ("Signed in on", f"{max(sessions, 1)} device{'s' if max(sessions, 1) != 1 else ''}"),
            ("Two-step sign-in", "on" if two_step_state["on"] else "off"),
        )))

    # ---- name ---------------------------------------------------------------- #
    st.subheader("Your name", anchor=False)
    st.session_state.setdefault("acct_name", me["display_name"] or "")
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.text_input("What should we call you?", key="acct_name", max_chars=auth.NAME_MAX,
                      placeholder="e.g. Sam")
        st.button("Save name", key="acct_name_save", on_click=_acct_save_name)
    st.caption("Shown in the app in place of your login" + (", and to your advisor"
               if advisor else "") + ". Never sent to the AI.")

    # ---- how pages look (ROADMAP S6; advisors always see everything) ---- #
    if not IS_ADVISOR:
        st.subheader("How pages look", anchor=False)
        st.session_state["acct_show_all"] = bool(_read_prefs().get("show_everything"))
        st.toggle("Show everything on one page", key="acct_show_all", on_change=_acct_show_all,
                  help="Off: Income, Activity, Watchlist and Ask Northwend start with a short "
                       "summary, and the details open in a window when you ask. On: every "
                       "section is on the page at once.")

    # ---- the Monthly Walk: its day and reminder email (views/checkin.py) ----- #
    render_checkin_settings(bool(me["email"] and me["email_verified_at"]))
    # ---- Trail Conditions: the opt-in Monday note (trail_conditions.py) ------ #
    if flags.on("trail_conditions"):
        _render_trail_switch(bool(me["email"] and me["email_verified_at"]))

    # ---- email ----------------------------------------------------------------- #
    st.subheader("Email", anchor=False)
    if me["email"] and not me["email_verified_at"]:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.caption(f"{me['email']} isn't confirmed yet - open the link we sent, or get a "
                       "new one.", width="stretch")
            st.button("Send it again", key="acct_resend", on_click=_resend_confirmation)
    if pending:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.caption(f":material/mail: Waiting for you to open the link we sent to "
                       f"**{pending}**.", width="stretch")
            st.button("Cancel", key="acct_cancel_email", on_click=_acct_cancel_email)
    login_is_email = bool(me["email"]) and me["username"].lower() == me["email"].lower()
    with st.expander("Change email" if me["email"] else "Add an email"):
        st.text_input("New email", key="acct_new_email", autocomplete="email")
        st.text_input("Your password", type="password", key="acct_email_pw",
                      autocomplete="current-password")
        st.button("Send a confirmation link", key="acct_email_go", type="primary",
                  on_click=_acct_change_email)
        st.caption("We send a link to the new address; nothing changes until you open it"
                   + (" - then you sign in with the new email" if login_is_email else "")
                   + ". Your old address gets a note that it changed.")

    # ---- password and devices ------------------------------------------------- #
    st.subheader("Password and devices", anchor=False)
    _pw_msg = st.session_state.pop("pw_msg", None)
    with st.expander("Change password", expanded=bool(_pw_msg)):
        if _pw_msg:
            getattr(st, _pw_msg[0])(_pw_msg[1])
        with st.form("change_pw_form", border=False):
            st.text_input("Current password", type="password", key="pw_current")
            st.text_input("New password", type="password", key="pw_new",
                          help=f"At least {auth.MIN_PASSWORD_LENGTH} characters.")
            st.text_input("New password again", type="password", key="pw_again")
            st.form_submit_button("Change password", on_click=_change_password)
    with st.container(horizontal=True, vertical_alignment="center"):
        st.caption("Signed in somewhere you shouldn't be, like a shared computer? Sign out "
                   "everywhere except here.", width="stretch")
        st.button("Sign out other devices", key="acct_sign_out_others",
                  on_click=_acct_sign_out_others)
    _render_two_step(two_step_state)

    # ---- the guide's notes (the write rule: visible and deletable) -------------- #
    _render_guide_notes()

    # ---- who has looked: an advisor's visits and the sharing record ----------- #
    _render_who_looked()

    # ---- your data ------------------------------------------------------------ #
    st.subheader("Your data", anchor=False)
    st.caption("Download a copy of everything Northwend holds for your account, as "
               "spreadsheet (CSV) files in one ZIP.")
    _limit_note("export")
    _export = st.session_state.get("export_zip")
    if _export:
        st.download_button("Download my data", _export[1], file_name=_export[0],
                           mime="application/zip", key="export_download", type="primary",
                           on_click="ignore", icon=":material/download:")
    else:
        st.button("Prepare my data", key="export_prepare", on_click=_prepare_export,
                  icon=":material/folder_zip:")
    _render_counts_switch()
    if not IS_MANAGED_CLIENT:
        with st.expander("Delete all my holdings"):
            st.caption("Delete everything you've imported or entered: holdings, cash, "
                       "activity and value history. Your goals, settings and login stay.")
            st.checkbox("Yes, delete all my holdings", key="confirm_delete_holdings")
            st.button("Delete all my holdings", key="delete_holdings",
                      disabled=not st.session_state.get("confirm_delete_holdings"),
                      on_click=_delete_my_holdings)

    # ---- the account map: private to this login (views/account_map.py) ----- #
    render_account_map()
    # ---- Lost & Found: finding old accounts (views/lost_found.py) ----------- #
    if flags.on("lost_found"):
        render_lost_found()
    # ---- Trail Forks: life events (views/trail_forks.py) -------------------- #
    if flags.on("trail_forks"):
        render_trail_forks()
    # ---- Explain it to someone: a figure-free share link (views/explain_share.py) #
    if flags.on("explain_share"):
        render_explain_share()
    # ---- Bring to my advisor: a client's own choices (views/advisor_pack.py) - #
    if flags.on("advisor_pack"):
        render_advisor_pack()

    # ---- delete the account ------------------------------------------------ #
    st.subheader("Delete your account", anchor=False)
    if can_delete:
        with st.expander("Delete my account"):
            st.caption("Deletes your login and everything in it - holdings, plan, answers, "
                       "settings. It can't be undone; download your data first if you'd "
                       "like a copy.")
            st.text_input("Your password", type="password", key="acct_delete_pw",
                          autocomplete="current-password")
            st.text_input("Type DELETE to confirm", key="acct_delete_word")
            st.button("Delete my account", key="acct_delete", type="primary",
                      on_click=_acct_delete)
    elif IS_ADMIN:
        st.caption("Admin accounts can't be deleted here.")
    elif CLIENTS:
        st.caption(f"You still have clients. Write to {disclosures.CONTACT} and we'll help "
                   "them keep their accounts first.")
    else:
        st.caption(f"Your advisor manages this account - ask them, or write to "
                   f"{disclosures.CONTACT}.")
