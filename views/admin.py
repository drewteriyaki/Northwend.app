# Part of dashboard.py, which runs this file with _view("admin") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# The Admin page (ROADMAP A1): accounts and logins, advisor requests, AI use,
# feature tests (totals only, feature_counts.py), invite codes for sign-up
# while gate L0 is off (invite_codes.py),
# and which experience the admin's own account shows. Only admins see it
# (admin.is_admin, set from the command line). Logins only - never anyone's
# holdings or plans. Every action re-checks admin rights in the database, and
# is written to the admin action log (admin_log.py, shown on System) - both in
# _admin_do.
# ruff: noqa: F821

import secrets

import admin
import admin_log
import ai_spend
import dividend_dates
import error_alerts
import feature_counts
import flags
import hosting
import invite_codes
import licence_check
import price_report
import rate_limits
import two_step


def _admin_do(fn, action, target=None, detail=""):
    """Run fn(conn) as the signed-in admin, or refuse; a message for the page.
    Every admin action comes through here, so every one is logged: when it
    was done - fn's message is a success or a warning - `action` (an
    admin_log.ACTIONS word) goes in the admin action log (admin_log.py),
    naming `target` (an account id, if any). fn may return (level, message,
    target, detail) when only it knows those (a new account's id, how many
    codes). Never holdings or figures in `detail`."""
    c = connect(DB)
    try:
        if not admin.is_admin(c, st.session_state["user_id"]):
            st.session_state["admin_msg"] = ("error", "Only an admin can do that.")
            return
        msg = fn(c)
        if len(msg) == 4:
            msg, target, detail = msg[:2], msg[2], msg[3]
        if action and msg[0] in ("success", "warning"):
            admin_log.add(c, st.session_state["user_id"], action, target, detail)
        st.session_state["admin_msg"] = msg
    finally:
        c.close()


def _admin_set_own_role():
    want_advisor = st.session_state.get("admin_own_role") == "Advisor app"
    _admin_do(lambda c: (auth.set_advisor(c, st.session_state["username"], want_advisor),
                         ("success", "Your account now shows the "
                          + ("advisor app." if want_advisor else "investor app.")))[1],
              "own_role", st.session_state["user_id"],
              "advisor app" if want_advisor else "investor app")


def _admin_told(res):
    """What the approve / decline email did, for the message."""
    return {True: " We emailed them to let them know.",
            False: " The email to them couldn't be sent - let them know yourself.",
            None: ""}[res["emailed"]]


def _admin_emailed(res):
    """The approve / decline email, for the action log."""
    return {True: "emailed", False: "email failed", None: "no email"}[res["emailed"]]


def _admin_check_from(key):
    """The license check typed into a form (Advisor requests, License checks):
    {"source", "crd", "checked_on"}, and what's wrong with it or None."""
    check = {"source": st.session_state.get(f"admin_src_{key}"),
             "crd": st.session_state.get(f"admin_crd_{key}") or "",
             "checked_on": st.session_state.get(f"admin_on_{key}")}
    return check, licence_check.check_error(check["source"], check["crd"], check["checked_on"])


def _admin_check_form(key, crd=""):
    """Where the admin looked an advisor up, the number that matched and the
    day (D15) - asked before approving, and for each yearly re-check."""
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.selectbox("Checked on", licence_check.SOURCES, index=None, key=f"admin_src_{key}",
                     placeholder="BrokerCheck or IAPD")
        st.text_input("CRD or license number that matched", value=crd, key=f"admin_crd_{key}",
                      max_chars=40)
        today = datetime.now(timezone.utc).date()   # as licence_check.check_error counts
        st.date_input("Day checked", value=today, max_value=today, key=f"admin_on_{key}")
    st.caption("Look them up on [BrokerCheck](https://brokercheck.finra.org/) or "
               "[IAPD](https://adviserinfo.sec.gov/) and match the firm and number - a check, "
               "not an endorsement.")


def _admin_decide(username, approve):
    """An advisor request: approve or decline it, and email them either way
    (admin.approve_advisor / decline_advisor). Approving keeps the license
    check typed above it (licence_check.py, D15) - it can't go without one."""
    def act(c):
        if approve:
            check, error = _admin_check_from(username)
            if error:
                return ("error", f"{username}: {error}")
            res = admin.approve_advisor(c, username, _app_address(), check=check,
                                        by=st.session_state["user_id"])
            return ("success", f"{username} is now an advisor." + _admin_told(res),
                    auth.get_user_id(c, username),
                    f"request approved; checked on {check['source']} {check['checked_on']}; "
                    + _admin_emailed(res))
        res = admin.decline_advisor(c, username, _app_address())
        if not res["ok"]:
            return ("info", f"{username} has no advisor request waiting.")
        return ("success", f"Declined {username}'s advisor request." + _admin_told(res),
                auth.get_user_id(c, username), _admin_emailed(res))
    _admin_do(act, "approve_advisor" if approve else "decline_advisor")


def _admin_record_check(user_id, username):
    """License checks: record a re-check of an advisor (licence_check.record)."""
    def act(c):
        check, error = _admin_check_from(f"re{user_id}")
        if error:
            return ("error", error)
        row = licence_check.record(c, user_id, source=check["source"], crd=check["crd"],
                                   checked_on=check["checked_on"],
                                   by=st.session_state["user_id"])
        return ("success", f"Recorded {username}'s license check on {row['source']} "
                           f"({row['checked_on']}).",
                user_id, f"{row['source']} {row['checked_on']}")
    _admin_do(act, "licence_check")


_LICENCE_WORDS = {licence_check.NONE: "no check on record", licence_check.CURRENT: "current",
                  licence_check.DUE: "due a re-check",
                  licence_check.OVERDUE: "not re-checked in 13 months"}


def _render_licence_checks(advisors_due):
    """Advisors whose license check is 11 months old or more, or missing (D15),
    each with a form to record a new one. Past 13 months they're flagged:
    the directory leaves them out until they're re-checked."""
    st.subheader(f"License checks due ({len(advisors_due)})", anchor=False)
    if not advisors_due:
        st.caption("Every advisor was checked in the last 11 months.")
        return
    st.caption("About once a year, look each advisor up again on BrokerCheck or IAPD and "
               "record it here. Past 13 months without one, an advisor is left out of the "
               "advisor directory until they're re-checked.")
    for a in advisors_due:
        last = a["check"]
        with st.expander(f"{a['username']} - {_LICENCE_WORDS[a['status']]}"
                         + (f" (last {last['checked_on']} on {last['source']})" if last else ""),
                         icon=(":material/error:" if a["status"] in (licence_check.NONE,
                                                                     licence_check.OVERDUE)
                               else ":material/schedule:")):
            _admin_check_form(f"re{a['id']}", last["crd"] if last else "")
            st.button("Record this check", key=f"admin_check_{a['id']}", type="primary",
                      on_click=_admin_record_check, args=(a["id"], a["username"]))


def _admin_reset_link(user_id):
    def act(c):
        email = auth.email_status(c, user_id)["email"]
        res = auth.request_password_reset(c, email or "")
        if not res["ok"] or not res["token"]:
            return ("error", res["error"] or "This account has no email address.")
        sent = mailer.reset_password(res["to"], f"{_app_address()}?reset={res['token']}",
                                     auth.RESET_MINUTES)
        return (("success", f"Sent a password reset link to {res['to']}.") if sent
                else ("error", "The email couldn't be sent just now."))
    _admin_do(act, "reset_password", user_id, "reset link emailed")


def _admin_temp_password(user_id):
    def act(c):
        temp = secrets.token_urlsafe(9)
        auth.set_password(c, auth.get_username(c, user_id), temp)
        st.session_state["admin_temp"] = (user_id, temp)
        return ("success", "Temporary password set - shown below once. The account is signed "
                           "out everywhere.")
    # the password itself is never logged
    _admin_do(act, "temp_password", user_id, "shown to the admin once")


def _admin_unlock(username):
    def act(c):
        uid = auth.get_user_id(c, username)
        auth.unlock_login(c, username)
        two_step.unlock(c, uid)
        return ("success", f"Unlocked {username}.", uid, "")
    _admin_do(act, "unlock")


def _admin_reset_two_step(user_id, username):
    def act(c):
        two_step.reset(c, user_id)
        return ("success", f"Two-step sign-in is reset for {username}, and they're signed out "
                           "everywhere. They sign in with their password"
                + (" and set it up again straight away." if two_step.status(c, user_id)["required"]
                   else "; they can turn it on again on their Account page."))
    _admin_do(act, "reset_two_step", user_id)


def _admin_advisor(username, flag):
    """An account's role: making someone an advisor approves them, so they get
    the same "your advisor access is ready" email."""
    def act(c):
        uid = auth.get_user_id(c, username)
        if flag:
            res = admin.approve_advisor(c, username, _app_address())
            return ("success", f"{username} is now an advisor." + _admin_told(res), uid,
                    _admin_emailed(res))
        auth.set_advisor(c, username, False)
        return ("success", f"{username} is no longer an advisor.", uid, "")
    _admin_do(act, "approve_advisor" if flag else "remove_advisor")


def _admin_ai(user_id, username, unlimited):
    _admin_do(lambda c: (ai_usage.set_unlimited(c, user_id, unlimited),
                         ("success", f"{username} {'has no' if unlimited else 'has the normal'} "
                                     "monthly AI limits."))[1],
              "ai_limits", user_id, "no limits" if unlimited else "normal limits")


def _admin_link(client_id, client_name):
    advisor_id = st.session_state.get(f"admin_link_to_{client_id}")
    if advisor_id is None:
        return

    def act(c):
        auth.link_client(c, advisor_id, client_id)
        return ("success", f"{client_name} is now a client of {auth.get_username(c, advisor_id)}.")
    _admin_do(act, "link_client", client_id, f"advisor #{advisor_id}")


def _admin_unlink(advisor_name, client_id, client_name):
    def act(c):
        advisor_id = auth.get_user_id(c, advisor_name)
        auth.unlink_client(c, advisor_id, client_id)
        return ("success", f"{client_name} is no longer {advisor_name}'s client.", client_id,
                f"advisor #{advisor_id}")
    _admin_do(act, "unlink_client")


def _admin_delete(user_id, username):
    if (st.session_state.get(f"admin_del_confirm_{user_id}") or "").strip() != username:
        st.session_state["admin_msg"] = ("error", "Type the login exactly to confirm.")
        return

    def act(c):
        res = admin.delete_account(c, user_id, by=st.session_state["user_id"])
        if not res["ok"]:
            return ("error", res["error"])
        st.session_state.pop("admin_pick", None)
        return ("success", f"Deleted {username} and all its data."
                + (f" {res['orphaned_clients']} client(s) no longer have an advisor."
                   if res["orphaned_clients"] else ""))
    # the account is gone, so the row names none - as delete_account clears
    # it from older rows that did (admin.ACCOUNT_REFERENCES)
    _admin_do(act, "delete_account", None, "the login and everything it held")


def _admin_create():
    login = st.session_state.get("admin_new_login") or ""
    as_advisor = st.session_state.get("admin_new_role") == "Advisor"
    client_of = st.session_state.get("admin_new_client_of")

    def act(c):
        res = admin.create_account(c, login)
        if not res["ok"]:
            return ("error", res["error"])
        if as_advisor:
            auth.set_advisor(c, res["username"], True)
        elif client_of:
            auth.link_client(c, client_of, res["user_id"])
        st.session_state["admin_new_login"] = ""
        kind = ("advisor" if as_advisor else f"client of advisor #{client_of}" if client_of
                else "investor")
        if res["email"]:
            link = auth.setup_link(c, res["user_id"])
            sent = link["ok"] and mailer.account_created(
                link["to"], f"{_app_address()}?reset={link['token']}", auth.SETUP_DAYS)
            return (("success", f"Created {res['username']} and emailed a link to choose a "
                                f"password (works for {auth.SETUP_DAYS} days).",
                     res["user_id"], f"{kind}; setup link emailed") if sent else
                    ("warning", f"Created {res['username']}, but the email couldn't be sent - "
                                "use Send password reset email on the account.",
                     res["user_id"], f"{kind}; setup email failed"))
        st.session_state["admin_temp"] = (res["user_id"], res["temp_password"])
        return ("success", f"Created {res['username']}. Its temporary password is shown below "
                           "once - pass it on privately.",
                res["user_id"], f"{kind}; temporary password shown once")
    _admin_do(act, "create_account")


def _admin_make_codes():
    how_many = st.session_state.get("admin_codes_n") or 1
    note = st.session_state.get("admin_codes_note") or ""

    def act(c):
        made = invite_codes.make(c, how_many, by=LOGIN_ID, note=note)
        st.session_state["admin_codes_note"] = ""
        st.session_state["admin_codes_made"] = [invite_codes.shown(x) for x in made]
        # how many - never the codes, which work until used
        return ("success", f"Made {len(made)} invite code{'s' if len(made) != 1 else ''}. "
                           "Each works once.", None,
                f"{len(made)} code{'s' if len(made) != 1 else ''}")
    _admin_do(act, "make_codes")


def _admin_revoke_code(code):
    # a stopped code no longer works, so naming it is safe
    _admin_do(lambda c: ("success", f"{invite_codes.shown(code)} won't work any more.")
              if invite_codes.revoke(c, code) else
              ("info", f"{invite_codes.shown(code)} was already used or stopped."),
              "revoke_code", None, invite_codes.shown(code))


def _render_invite_codes(c):
    """Invite codes (invite_codes.py): what Create account asks for while
    gate L0 is off. Make a few, see which were used and when, stop one."""
    with st.expander(":material/key: Invite codes"):
        if auth.invite_only():
            st.caption("Sign-up is by invite code for now (gate L0 is off). Each code works "
                       "once. Setup links from advisors and accounts made here never need one.")
        else:
            st.caption("Sign-up is open (gate L0 is on), so no code is asked for. Codes made "
                       "here start working if L0 is turned off.")
        with st.container(horizontal=True, vertical_alignment="bottom"):
            st.number_input("How many", min_value=1, max_value=invite_codes.MAX_AT_ONCE,
                            value=1, step=1, key="admin_codes_n")
            st.text_input("Note (optional)", key="admin_codes_note",
                          max_chars=invite_codes.MAX_NOTE, placeholder="Who they're for")
            st.button("Make codes", key="admin_codes_make", type="primary",
                      on_click=_admin_make_codes)
        made = st.session_state.pop("admin_codes_made", None)
        if made:
            st.code("\n".join(made), language=None)
        codes = invite_codes.listing(c)
        if not codes:
            st.caption("No codes yet.")
            return
        unused = [r for r in codes if r["status"] == "unused"]
        st.markdown(f"**Unused ({len(unused)})**")
        for r in unused:
            with st.container(horizontal=True, vertical_alignment="center"):
                st.markdown(f"`{invite_codes.shown(r['code'])}` - made "
                            f"{_admin_when(r['created_at'])}"
                            + (f" - {r['note']}" if r["note"] else ""), width="stretch")
                st.button("Revoke", key=f"admin_code_revoke_{r['code']}", type="tertiary",
                          on_click=_admin_revoke_code, args=(r["code"],))
        done = [r for r in codes if r["status"] != "unused"]
        if done:
            st.markdown(f"**Used or revoked ({len(done)})**")
            st.dataframe(pd.DataFrame([{
                "Code": invite_codes.shown(r["code"]), "Note": r["note"] or "",
                "Made": _admin_when(r["created_at"]),
                "Status": ("Used " + _admin_when(r["used_at"])) if r["status"] == "used"
                else ("Revoked " + _admin_when(r["revoked_at"])),
                "Account": r["used_by"] or ("(deleted)" if r["status"] == "used" else ""),
            } for r in done]), hide_index=True, width="stretch")


def _admin_clear_cache():
    _admin_do(lambda c: (st.cache_data.clear(),
                         ("success", "Cleared the cached prices, charts and news - they "
                                     "reload on the next page."))[1], "clear_cache")


def _admin_sign_out_all():
    """The incident switch (audit X5): every account signed out at once - the
    saved sign-ins end, and every open tab lands on sign-in at its next
    click. The admin's own tab too: simplest, and the right thing when a
    session may have been stolen."""
    if not st.session_state.get("admin_sign_out_all_ok"):
        st.session_state["admin_msg"] = ("error", "Tick the box first to confirm.")
        return

    def act(c):
        n = auth.sign_out_everyone(c)
        return ("success", "Everyone is signed out, you included.", None,
                f"{n} saved sign-in{'s' if n != 1 else ''} ended")
    _admin_do(act, "sign_out_all")


def _admin_test_email():
    def act(c):
        email = auth.email_status(c, LOGIN_ID)["email"]
        if not email:
            return ("error", "Your account has no email address.")
        sent = mailer.send(email, f"{APP_NAME} test email",
                           f"This is a test from the Admin page of {_app_address() or APP_NAME}. "
                           "If you can read it, email sending works.")
        return (("success", f"Sent a test email to {email}.") if sent else
                ("error", "It couldn't be sent - check RESEND_API_KEY and the server log."))
    _admin_do(act, "test_email", LOGIN_ID)


def _admin_clear_errors():
    _admin_do(lambda c: (error_alerts.clear(c), ("success", "Cleared the list of errors."))[1],
              "clear_errors")


def _render_admin_log(c):
    """The admin action log (admin_log.py; audit X2): the newest rows, who did
    what to which login. Logins only - never holdings."""
    rows = admin_log.recent(c)
    st.markdown("**Admin actions**")
    if not rows:
        st.caption("None yet. Every action taken here or with manage_users.py is listed, "
                   f"and kept for {admin_log.KEEP_DAYS // 365} year.")
        return
    st.caption(f"The last {admin_log.SHOWN} actions taken here or with manage_users.py, newest "
               f"first. Kept for {admin_log.KEEP_DAYS // 365} year; nothing here can be edited.")
    st.dataframe(pd.DataFrame([{
        "When": _admin_when(r["at"]),
        "Admin": r["admin"] or ("command line" if r["detail"].startswith(admin_log.COMMAND_LINE)
                                else "(deleted)"),
        "Action": r["action"].replace("_", " "),
        "Account": r["target"] or "",
        "Detail": r["detail"],
    } for r in rows]), hide_index=True, width="stretch")


def _render_sign_out_all():
    """Admin > System's "Sign everyone out", behind a tick box (System is an
    expander already, so a box here, not another one)."""
    with st.container(border=True):
        st.markdown("**Sign everyone out**")
        st.caption("For an emergency, such as a leaked password or a stolen device: every "
                   "account is signed out at once, on every device and every open tab - "
                   "yours too. Saved sign-ins stop working, so everyone signs in again with "
                   "their password (and two-step code). Nothing else changes.")
        st.checkbox("Yes, sign out every account, mine included", key="admin_sign_out_all_ok")
        st.button("Sign everyone out", key="admin_sign_out_all", type="primary",
                  on_click=_admin_sign_out_all)


def _render_errors(c):
    """Recent unexpected errors and failed jobs, one line per kind, newest
    first (error_alerts.py). Type and place only - never anyone's data."""
    rows = error_alerts.recent(c)
    st.markdown("**Recent errors**")
    if not rows:
        st.caption("None noted. Unexpected errors and failed scheduled jobs show up here.")
        return
    st.dataframe(pd.DataFrame([{
        "Last seen": _admin_when(r["last_seen"]),
        "What": "Scheduled job failed" if r["source"] == "job" else r["error_type"],
        "Where": r["place"] + (f", line {r['line']}" if r["line"] else ""),
        "Times": r["times"], "Since": _admin_when(r["first_seen"]),
        "Emailed": _admin_when(r["emailed_at"]) if r["emailed_at"] else "",
    } for r in rows]), hide_index=True, width="stretch")
    st.button("Clear the list", key="admin_clear_errors", on_click=_admin_clear_errors,
              help="Starts the list afresh. A cleared kind is emailed again the next time "
                   "it happens.")


def _admin_flag_rows():
    """Which legal gates and feature flags are on (flags.py) - not secrets."""
    s = flags.state()
    gates = ", ".join(f"{g} {'on' if v else 'off'}" for g, v in s["gates"].items())
    feats = ", ".join(
        f"{n} {'on' if f['on'] else 'off'}"
        + (f" (set, waiting for {' and '.join(f['needs'])})" if f["set"] and not f["on"] else "")
        for n, f in s["flags"].items())
    if s["unknown"]:
        feats += "; not known here: " + ", ".join(s["unknown"])
    return [("Legal gates (NORTHWEND_GATES)", gates),
            ("Feature flags (NORTHWEND_FLAGS)", feats)]


def _admin_two_step_rows(c):
    """Whether two-step keys are stored encrypted (two_step.py, audit 1.1e):
    the key set or not - with its key id, never the key - and how many are
    still readable or won't open, as counts with no names."""
    k = two_step.key_state()
    n = two_step.storage(c)
    if k["state"] == "set":
        key = (f"set (key id {k['key_id']}"
               + (f"; {k['count']} keys, the first encrypts" if k["count"] > 1 else "") + ")")
    elif k["state"] == "not valid":
        key = ("set, but not a valid key - new two-step keys are stored readable until it's "
               "fixed")
    else:
        key = ("not set - two-step keys are stored readable" if HOSTED
               else "not set - two-step keys are stored readable (fine for a local copy)")
    stored = f"{n['sealed']} encrypted, {n['readable']} readable"
    if n["readable"] and k["state"] == "set":
        stored += (" (each is encrypted at its next sign-in, or all at once with "
                   "manage_users.py encrypt-two-step)")
    if n["old_key"]:
        stored += f", {n['old_key']} with an older key (manage_users.py encrypt-two-step --rotate)"
    if n["unreadable"]:
        stored += (f", **{n['unreadable']} that won't open with this key** - those people "
                   "need a backup code until the right key is back in NORTHWEND_TOTP_KEY")
    return [("Two-step key (NORTHWEND_TOTP_KEY)", key), ("Two-step keys stored", stored)]


def _render_system(c):
    """Developer facts about this copy of the app - never a secret's value."""
    from manage_users import where
    sha = hosting.version(HERE)
    last_price, last_bar = admin.data_freshness(c)
    flagged = admin.flagged_admins(c)
    listed = sorted(admin.listed_admins())
    admins = [x for x in (", ".join(flagged) + " (make-admin)" if flagged else "",
                          ", ".join(listed) + " (NORTHWEND_ADMINS)" if listed else "") if x]
    mail = {"sending": "sending (Resend)", "dry run": "dry run - written to the log, not sent",
            "off": "off - RESEND_API_KEY isn't set"}[mailer.status()]
    rows = [
        ("This copy", "Staging" if STAGING else "Live" if HOSTED else "Local"),
        ("Runs on", hosting.host_name()),
        ("Version", f"[{sha}](https://github.com/drewteriyaki/portfolio_tracker/commit/{sha})"
         if sha else "unknown"),
        ("Address", _app_address() or "unknown"),
        ("Database", where(DB)),
        ("Email", mail),
        ("Error alerts", f"emailed to {error_alerts.alert_to()}, at most once an hour per kind"
         if HOSTED else "listed below only - a local copy doesn't email"),
        ("AI (Anthropic key)", "set" if _anthropic_key() else "not set - AI features are off"),
        ("Live prices (Finnhub key)", "set" if resolve_key(None) else "not set"),
        # the nightly job fetches with it (dividend_dates.py); set or not, never the value
        ("Dividend dates (Polygon key)", "set" if dividend_dates.api_key() else
         "not set - only Yahoo's and the brokerage file's dates show"),
        *_admin_two_step_rows(c),
        ("Last price update", _admin_when(last_price)),
        ("Newest daily price history", last_bar or "none"),
        ("Admins", "; ".join(admins)),
        *_admin_flag_rows(),
        # the limits as set in rate_limits.py - never anyone's counts (audit 1.8d)
        *((f"Limit - {what}", how) for what, how in rate_limits.rows_for_admin()),
    ]
    st.markdown("\n".join(f"- **{k}:** {v}" for k, v in rows))
    with st.container(horizontal=True):
        st.button("Clear cached data", key="admin_clear_cache", on_click=_admin_clear_cache,
                  help="Prices, charts and news are kept for a few minutes to keep pages "
                       "quick. Clear them to see fresh data straight away.")
        st.button("Send me a test email", key="admin_test_email", on_click=_admin_test_email)
    st.caption("Settings like keys and NORTHWEND_ADMINS live in the app's Secrets (Streamlit "
               "Cloud: Manage app, Settings, Secrets; Render: Environment). Only whether a key "
               "is set is shown here, never its value.")
    _render_sign_out_all()
    _render_errors(c)
    _render_admin_log(c)


def _admin_when(stamp):
    if not stamp:
        return "never"
    return str(stamp)[:16].replace("T", " ")


def _render_admin():
    st.caption("Only admin accounts see this page. It shows logins - who has an account and "
               "its role - never anyone's holdings or plans.")
    msg = st.session_state.pop("admin_msg", None)
    if msg:
        getattr(st, msg[0])(msg[1])
    temp = st.session_state.get("admin_temp")
    c = connect(DB)
    try:
        if not admin.is_admin(c, LOGIN_ID):
            st.error("Only an admin can open this page.")
            return
        accounts = admin.list_accounts(c)
        requests = auth.pending_advisor_requests(c)
        licence_due = licence_check.due(c)   # advisors whose check is old or missing (D15)
        usage = ai_usage.month_rows(c, ai_usage.month_of())
        spend = ai_spend.summary(c)   # the app-wide month total, counts only
    finally:
        c.close()
    by_id = {a["id"]: a for a in accounts}
    advisors = [a for a in accounts if a["is_advisor"]]

    # ---- your own account: which app it shows ---------------------------- #
    with st.container(border=True):
        st.markdown("**Your own account**")
        st.segmented_control("Show my account as", ["Investor app", "Advisor app"],
                             default="Advisor app" if IS_ADVISOR else "Investor app",
                             key="admin_own_role", on_change=_admin_set_own_role)
        st.caption("Switch to check what each kind of account sees. In the advisor app you can "
                   "add test clients; switching back keeps them, just out of sight.")

    # ---- this copy of the app, for the developer ------------------------- #
    with st.expander(":material/developer_mode: System"):
        c = connect(DB)
        try:
            _render_system(c)
        finally:
            c.close()

    # ---- advisor requests ------------------------------------------------- #
    st.subheader(f"Advisor requests ({len(requests)})", anchor=False)
    if not requests:
        st.caption("None waiting.")
    else:
        st.caption("Check each one, then approve or decline - either way they get a short "
                   "email saying so. Approving keeps where you checked, the number that "
                   "matched and the day. Approved advisors are asked to set up two-step "
                   "sign-in, then add a client.")
    for r in requests:
        with st.container(border=True):
            # firm and licence are as typed at sign-up: shown as text, never as a
            # link or an image (_md_name escapes markdown)
            st.markdown(f"**{_md_name(r['username'])}** · {_md_name(r['firm'])} · CRD/license "
                        f"**{_md_name(r['licence'])}** · asked {_admin_when(r['requested_at'])}")
            _admin_check_form(r["username"], r["licence"])
            with st.container(horizontal=True):
                st.button("Approve", key=f"admin_ok_{r['username']}", type="primary",
                          on_click=_admin_decide, args=(r["username"], True))
                st.button("Decline", key=f"admin_no_{r['username']}",
                          on_click=_admin_decide, args=(r["username"], False))

    # ---- licence re-checks (D15) ------------------------------------------ #
    _render_licence_checks(licence_due)

    # ---- accounts ------------------------------------------------------------ #
    st.subheader(f"Accounts ({len(accounts)})", anchor=False)
    roles = {}
    for a in accounts:
        roles[a["role"]] = roles.get(a["role"], 0) + 1
    st.caption(" · ".join(f"{n} {r}{'s' if n != 1 else ''}" for r, n in sorted(roles.items())))
    find = st.text_input("Find an account", key="admin_find", placeholder="Email or username")
    shown = [a for a in accounts if find.strip().lower() in (a["username"] or "").lower()]
    st.dataframe(pd.DataFrame([{
        "Login": a["username"], "Role": a["role"],
        "Email confirmed": "-" if a["confirmed"] is None else ("yes" if a["confirmed"] else "no"),
        "Advisor": a["advisor"] or "", "Clients": str(a["clients"]) if a["clients"] else "",
        "Created": _admin_when(a["created_at"]), "Last sign-in": _admin_when(a["last_login_at"]),
        "Locked": "locked" if a["locked"] else "", "Two-step": "on" if a["two_step"] else "",
        "AI limits": "none" if a["ai_unlimited"] else "",
        # advisors: the agreement version they accepted, and their licence check
        "Agreement": (((a["agreement"]["version"] + ("" if a["agreement"]["current"] else " (old)"))
                       if a["agreement"] else "not yet") if a["is_advisor"] else ""),
        "License": _LICENCE_WORDS[a["licence_status"]] if a["is_advisor"] else "",
    } for a in shown]), hide_index=True, width="stretch")

    pick = st.selectbox("Open an account", [a["id"] for a in shown], index=None,
                        format_func=lambda i: by_id[i]["username"], key="admin_pick",
                        placeholder="Pick an account to manage it")
    if pick in by_id:
        a = by_id[pick]
        with st.container(border=True):
            st.markdown(f"#### {a['username']}")
            facts = [f"Role: **{a['role']}**",
                     f"made {'by themselves' if a['signed_up'] else 'by an admin or advisor'} "
                     f"on {_admin_when(a['created_at'])[:10]}",
                     f"last sign-in {_admin_when(a['last_login_at'])}"]
            if a["email"]:
                facts.append("email confirmed" if a["confirmed"] else "email not confirmed yet")
            if a["is_advisor"]:
                # what Northwend did: checked a licence number - not an endorsement
                chk = a["licence_check"]
                facts.append(f"license checked {chk['checked_on']} on {chk['source']} "
                             f"(**{_md_name(chk['crd'])}**) - {_LICENCE_WORDS[a['licence_status']]}"
                             if chk else
                             f"request approved {_admin_when(a['licence_checked'])[:10]} - no "
                             "license check on record" if a["licence_checked"] else
                             "advisor without a request - no license check on record")
                ag = a["agreement"]   # advisor_agreement.py
                facts.append(f"advisor agreement {ag['version']}"
                             + (" (beta)" if not ag["l1_on"] else "")
                             + f" accepted {_admin_when(ag['accepted_at'])[:10]}"
                             + ("" if ag["current"] else " - not the current version")
                             if ag else "advisor agreement not accepted yet")
            facts.append(f"agreed to the disclosures ({a['terms_version']} version) on "
                         f"{_admin_when(a['terms_accepted_at'])[:10]}" if a["terms_version"]
                         else "hasn't agreed to the disclosures yet")
            if a["advisor"]:
                facts.append(f"client of **{a['advisor']}**")
            if a["clients"]:
                facts.append(f"**{a['clients']}** client{'s' if a['clients'] != 1 else ''}")
            facts.append("two-step sign-in on" if a["two_step"] else "two-step sign-in off")
            st.markdown(" · ".join(facts))
            if temp and temp[0] == pick:
                st.code(temp[1], language=None)
                st.caption("Temporary password - shown only now. Pass it on privately; they can "
                           "change it under Change password.")
            with st.container(horizontal=True):
                if a["email"]:
                    st.button("Send password reset email", key="admin_reset",
                              on_click=_admin_reset_link, args=(pick,))
                else:
                    st.button("Set a temporary password", key="admin_temp_pw",
                              on_click=_admin_temp_password, args=(pick,))
                if a["locked"]:
                    st.button("Unlock", key="admin_unlock", on_click=_admin_unlock,
                              args=(a["username"],))
                if not a["is_admin"]:
                    st.button("Remove advisor" if a["is_advisor"] else "Make advisor",
                              key="admin_adv", on_click=_admin_advisor,
                              args=(a["username"], not a["is_advisor"]))
                st.button("Normal AI limits" if a["ai_unlimited"] else "No AI limits",
                          key="admin_ai", on_click=_admin_ai,
                          args=(pick, a["username"], not a["ai_unlimited"]))
            if not a["is_advisor"] and not a["is_admin"]:
                if a["advisor"]:
                    st.button(f"Unlink from {a['advisor']}", key="admin_unlink", type="tertiary",
                              on_click=_admin_unlink, args=(a["advisor"], pick, a["username"]))
                elif advisors:
                    with st.container(horizontal=True, vertical_alignment="bottom"):
                        st.selectbox("Make this a client of", [x["id"] for x in advisors],
                                     index=None, key=f"admin_link_to_{pick}",
                                     format_func=lambda i: by_id[i]["username"],
                                     placeholder="Pick an advisor")
                        st.button("Link", key="admin_link", on_click=_admin_link,
                                  args=(pick, a["username"]))
            if a["two_step"]:
                with st.expander("Reset two-step sign-in"):
                    st.caption("For someone who lost their phone and their backup codes. Only "
                               "do this once you're sure it's really them (for example, they "
                               "wrote from the account's email). It turns two-step off and "
                               "signs them out everywhere; advisors and admins set it up again "
                               "as soon as they sign in. Their key is never shown here.")
                    st.button("Reset two-step sign-in", key="admin_two_step_reset",
                              on_click=_admin_reset_two_step, args=(pick, a["username"]))
            if not a["is_admin"]:
                with st.expander("Delete this account"):
                    st.caption("Deletes the login and everything it holds - holdings, plan, "
                               "profile, notes, settings. This can't be undone."
                               + (f" Its {a['clients']} client(s) keep their accounts but no "
                                  "longer have an advisor." if a["clients"] else "")
                               + (f" {a['advisor']}'s notes, proposals and reports for this "
                                  "client go too - ask them to export the client's record "
                                  "first (Advisor notes > Export this client's record)."
                                  if a["advisor"] else ""))
                    st.text_input(f"Type {a['username']} to confirm",
                                  key=f"admin_del_confirm_{pick}")
                    st.button("Delete account", key="admin_delete", type="primary",
                              on_click=_admin_delete, args=(pick, a["username"]))

    # ---- add an account -------------------------------------------------- #
    with st.expander("Add an account"):
        st.text_input("Email address or username", key="admin_new_login",
                      help="With an email address they get a link to choose their own "
                           "password. A username gets a temporary password shown here once.")
        role = st.segmented_control("Kind of account", ["Investor", "Advisor"],
                                    default="Investor", key="admin_new_role")
        if role != "Advisor" and advisors:
            st.selectbox("Client of (optional)", [x["id"] for x in advisors], index=None,
                         key="admin_new_client_of", format_func=lambda i: by_id[i]["username"],
                         placeholder="No advisor")
        st.button("Create account", key="admin_create", type="primary", on_click=_admin_create)

    # ---- invite codes (sign-up while gate L0 is off) ---------------------- #
    c = connect(DB)
    try:
        _render_invite_codes(c)
    finally:
        c.close()

    # ---- AI use ---------------------------------------------------------- #
    st.subheader(f"AI use in {ai_usage.month_of()}", anchor=False)
    _render_ai_spend(spend)
    if usage:
        st.dataframe(pd.DataFrame([{"Account": r["username"], "Feature": r["kind"],
                                    "Used": r["used"],
                                    "Estimated": ai_spend.dollars(r["cost_micro"] or 0)}
                                   for r in usage]),
                     hide_index=True, width="stretch")
    else:
        st.caption("No AI use yet this month.")

    # ---- "Price look wrong?" notes: counts only (price_report.py) ---------- #
    if flags.on("price_report"):
        c = connect(DB)
        try:
            _render_price_reports(c)
        finally:
            c.close()

    # ---- feature tests: totals only (feature_counts.py) -------------------- #
    c = connect(DB)
    try:
        _render_feature_tests(c)
        if flags.on("storm_drill"):
            _render_drill_count(c)
        _render_decoder_counts(c)
        if flags.on("drills"):
            _render_drill_returns(c)
    finally:
        c.close()


AI_LEVEL_WORDS = {
    ai_spend.NORMAL: "Everything AI runs as usual.",
    ai_spend.ALERT: "Past 50% - you were emailed. Everything AI still runs as usual.",
    ai_spend.REDUCED: "Past 80%: chat answers are shorter, and screenshot reads, column "
                      "guesses, plan next steps and talking points rest until next month.",
    ai_spend.CLOSING: "Past 95%: no new conversations; open ones may finish. The other AI "
                      "helpers rest.",
    ai_spend.RESTING: "At the ceiling: everything AI rests until next month.",
}


def _render_ai_spend(s):
    """The month's AI spend against the ceiling (ai_spend.py) - totals only,
    estimated from token counts at list price."""
    st.markdown(f"**{ai_spend.dollars(s['spent'])}** of the {ai_spend.dollars(s['ceiling'])} "
                f"monthly ceiling ({s['percent']:.0f}%) · {s['calls']} AI answers · on track "
                f"for {ai_spend.dollars(s['projected'])} by the month's end")
    st.progress(min(1.0, s["percent"] / 100))
    st.caption(AI_LEVEL_WORDS[s["level"]] + " Estimated from token counts at list price; "
               "the ceiling is NORTHWEND_AI_CEILING_USD.")
    if s["rows"]:
        with st.expander("By helper"):
            st.dataframe(pd.DataFrame([{
                "Helper": r["helper"], "Model": r["model"], "Answers": r["calls"],
                "Input tokens": r["input_tokens"], "Output tokens": r["output_tokens"],
                "Cache write": r["cache_write_tokens"], "Cache read": r["cache_read_tokens"],
                "Estimated": ai_spend.dollars(r["cost_micro"])} for r in s["rows"]]),
                hide_index=True, width="stretch")
    _render_ai_breaks(s.get("breaks") or [])


AI_BREAK_WORDS = {   # ai_policy.KINDS, in words
    "conclusion": "Said what to do", "for_you_mix": "A mix for them", "rating": "Rated a choice",
    "advisor_pick": "Pointed to an advisor", "prediction": "A prediction",
    "urgency": "Urgency", "ticker": "Named a fund outside the card",
}


def _render_ai_breaks(rows):
    """Ask Northwend's output check this month (ai_policy, AI_PLAN 7.2):
    how often a draft broke the conclusion policy, by kind - totals only,
    never the text or who asked."""
    st.markdown("**The output check** - drafts stopped by the conclusion policy this month")
    if not rows:
        st.caption("None this month.")
        return
    st.dataframe(pd.DataFrame([{
        "Kind": AI_BREAK_WORDS.get(r["kind"], r["kind"]),
        "Asked once more": r[ai_spend.RETRIED],
        "Calm line shown": r[ai_spend.FELL_BACK]} for r in rows]),
        hide_index=True, width="stretch")
    st.caption("A first break asks the model once more with a reminder; a second shows the "
               "calm line instead. Counts only - never the text, never who asked.")


def _render_price_reports(c):
    """Prices people said look wrong (price_report.admin_counts): by ticker
    and reason, how many and the latest price time - never who."""
    rows = price_report.admin_counts(c)
    st.subheader("Price notes", anchor=False)
    if not rows:
        st.caption("No one has said a price looks wrong.")
        return
    st.dataframe(pd.DataFrame([{
        "Ticker": r["ticker"], "Reason": price_report.REASONS.get(r["reason"], r["reason"]),
        "Notes": r["n"],
        "Latest price time": _admin_when(r["latest_as_of"]) if r["latest_as_of"] else "",
        "Latest note": _admin_when(r["latest"])} for r in rows]),
        hide_index=True, width="stretch")
    st.caption("Counts only - never who sent a note. Worth a look at the ticker's price "
               "source when one shows up more than once.")


def _render_drill_count(c):
    """The Storm Drill (R4): how many people wrote down what they'd do - a
    total, never the words. Selling on a drop isn't measured yet."""
    n = feature_counts.drill_answers(c)
    st.markdown("**The storm drill** - people who wrote down what they'd do in a drop")
    if n is None:
        st.caption(f"Fewer than {feature_counts.MIN_GROUP} people have written one so far - "
                   "nothing to show yet.")
    else:
        st.markdown(f"- Wrote a drill answer: {n}")
    st.caption("Only the count of answers. What people do on a drop isn't measured yet.")


def _render_feature_tests(c):
    """Whether features help, in totals only (feature_counts.py): no names,
    nobody's row, nothing for a group under feature_counts.MIN_GROUP, and
    without anyone who left themselves out on Account."""
    st.subheader("Feature tests", anchor=False)
    st.caption(f"Totals only, worked out from what's stored - never a person. A total shows "
               f"once a group reaches {feature_counts.MIN_GROUP} people, and people who turned "
               "on \"Leave me out of feature counts\" are never counted.")
    days = feature_counts.SECOND_WITHIN_DAYS
    w = feature_counts.walks(c, datetime.now().date())
    st.markdown(f"**The monthly walk** - a second walk within {days} days of the first")
    if w is None:
        st.caption(f"Fewer than {feature_counts.MIN_GROUP} people have finished a first walk "
                   "so far - nothing to show yet.")
        return
    lines = [f"- Finished a first walk: {w['first_walks']}",
             f"- Their {days} days are up: {w['window_closed']}"]
    if w["second_walks"] is None:
        lines.append(f"- Walked again within {days} days: shown once {feature_counts.MIN_GROUP} "
                     f"people's {days} days are up")
    else:
        share = w["second_walks"] / w["window_closed"] * 100
        lines.append(f"- Walked again within {days} days: {w['second_walks']} of "
                     f"{w['window_closed']} ({share:.0f}%)")
    st.markdown("\n".join(lines))


def _render_drill_returns(c):
    """R12 in Feature tests: unprompted return for a third preparedness drill,
    in totals only (feature_counts.drill_returns) - never who, never a tap."""
    st.markdown("**Preparedness drills** - came back for a third drill")
    d = feature_counts.drill_returns(c)
    if d is None:
        st.caption(f"Fewer than {feature_counts.MIN_GROUP} people have tried a drill so far - "
                   "nothing to show yet.")
        return
    share = d["third"] / d["started"] * 100 if d["started"] else 0.0
    st.markdown(f"- People who rehearsed a first drill: {d['started']}\n"
                f"- Of them, rehearsed a third: {d['third']} ({share:.0f}%)")


def _render_decoder_counts(c):
    """R5 in Feature tests: the share of pasted 401(k) funds identified, in
    totals only (feature_counts.decoder) - never a fund name or a person."""
    st.markdown("**The 401(k) Menu Decoder** - the share of pasted funds identified")
    d = feature_counts.decoder(c)
    if d is None:
        st.caption(f"Fewer than {feature_counts.MIN_GROUP} people have used it so far - "
                   "nothing to show yet.")
        return
    share = d["identified"] / d["lines"] * 100 if d["lines"] else 0.0
    st.markdown(f"- People who used it: {d['people']} ({d['decodes']} lists)\n"
                f"- Funds identified: {d['identified']} of {d['lines']} ({share:.0f}%)")
