# Part of dashboard.py, which runs this file with _view("account") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# The Account page: the signed-in person's own account - what's on it, their
# name, email (changed only through a link to the new address), password,
# other signed-in devices, two-step sign-in (set up with views/two_step.py's
# steps), a copy of their data, and deleting it. Always the
# login's own account (LOGIN_ID), even while an advisor is viewing a client.
# ruff: noqa: F821

import admin
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
    finally:
        c.close()
    _acct_msg("success", f"Signed out {n} other device{'s' if n != 1 else ''}." if n
              else "No other devices were signed in.")


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


def _acct_facts(c):
    row = c.execute("SELECT username, email, email_verified_at, display_name, created_at, "
                    "last_login_at FROM users WHERE id = ?", (LOGIN_ID,)).fetchone()
    sessions = c.execute("SELECT COUNT(*) AS n FROM login_sessions WHERE user_id = ? AND "
                         "expires_at > ?", (LOGIN_ID, datetime.now(timezone.utc)
                                            .strftime("%Y-%m-%d %H:%M:%S"))).fetchone()["n"]
    advisor_id = advising.advisor_of(c, LOGIN_ID)
    advisor = auth.get_username(c, advisor_id) if advisor_id else None
    pending = auth.pending_email_change(c, LOGIN_ID)
    can_delete = not (IS_ADMIN or CLIENTS or advisor_id)
    return dict(row), sessions, advisor, pending, can_delete, two_step.status(c, LOGIN_ID)


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

    # ---- your data ------------------------------------------------------------ #
    st.subheader("Your data", anchor=False)
    st.caption("Download a copy of everything Northwend holds for your account, as "
               "spreadsheet (CSV) files in one ZIP.")
    _export = st.session_state.get("export_zip")
    if _export:
        st.download_button("Download my data", _export[1], file_name=_export[0],
                           mime="application/zip", key="export_download", type="primary",
                           on_click="ignore", icon=":material/download:")
    else:
        st.button("Prepare my data", key="export_prepare", on_click=_prepare_export,
                  icon=":material/folder_zip:")
    if not IS_MANAGED_CLIENT:
        with st.expander("Delete all my holdings"):
            st.caption("Delete everything you've imported or entered: holdings, cash, "
                       "activity and value history. Your goals, settings and login stay.")
            st.checkbox("Yes, delete all my holdings", key="confirm_delete_holdings")
            st.button("Delete all my holdings", key="delete_holdings",
                      disabled=not st.session_state.get("confirm_delete_holdings"),
                      on_click=_delete_my_holdings)

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
