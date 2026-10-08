# Part of dashboard.py, which runs this file with _view("two_step") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, the helpers...) are dashboard.py's, and what this defines is
# visible there afterwards. See _view() in dashboard.py.
#
# Two-step sign-in (ROADMAP R2; the logic is two_step.py): what comes between
# the password and the app. _two_step_gate() runs inside _login() on every
# run, whichever way the browser got signed in (the login form, the
# stay-signed-in cookie, a setup or reset link): it asks for a code from the
# phone, or - for an advisor or admin who hasn't set it up yet - sets it up
# right there, before anything else opens. The Account page reuses the setup
# steps (_two_step_setup) and the backup codes box (_two_step_codes_box).
#
# st.session_state["two_step_ok"] is "<login id>:<two_step.status stamp>" once
# this tab is past the check. The stamp changes when two-step is turned on,
# off or reset, so a change made elsewhere is noticed on the next click.
# ruff: noqa: F821

import two_step

TWO_STEP_ISSUER = APP_NAME + (" staging" if STAGING else "")

# What the gate read this run: {login id: (two_step.status, the login's users
# row - auth.LOGIN_COLUMNS, None if the login is gone)}. This file runs afresh
# with dashboard.py on every full run, so this starts empty each time and the
# gate fills it before anything else reads the row. A fragment's or window's
# own rerun skips the gate and would still see the last full run's: so only
# code drawn in the full run itself uses it (_gate_read).
_GATE_ROW = {}


def _gate_read(uid):
    """(status, users row) as the gate read them at the top of this run, or
    None if it hasn't for `uid`. Only for code that runs in the page's full
    run - never in a fragment or a window (st.dialog), whose own reruns skip
    the gate."""
    return _GATE_ROW.get(uid)


def _two_step_qr(uri):
    """The setup QR code as an image address (SVG), or None when segno isn't
    installed - the key and the link below it still work."""
    try:
        import segno
        return segno.make_qr(uri, error="m").svg_data_uri(scale=5, border=2,
                                                          dark="#000000", light="#ffffff")
    except Exception:  # noqa: BLE001 - a QR code is a nicety, never a blocker
        return None


def _two_step_done(stamp):
    """Mark this tab as past the check for the account's current setup
    (two_step.status's stamp; None when two-step is off)."""
    st.session_state["two_step_ok"] = f"{st.session_state['user_id']}:{stamp}"


def _two_step_setup(where):
    """The setup steps: an app on the phone, the key (QR code, a link, or
    typed in), then the app's first code - two-step only turns on once that
    checks out, so nobody is locked out by a key that didn't get saved.
    `where` keeps widget keys apart ('gate' / 'acct'). Once it's on, the
    backup codes go to st.session_state['two_step_codes'] and the page reruns."""
    uid = st.session_state["user_id"]
    secret = st.session_state.setdefault("two_step_secret", two_step.new_secret())
    uri = two_step.otpauth_uri(secret, st.session_state.get("username") or "", TWO_STEP_ISSUER)
    st.markdown("**1. Get an authenticator app on your phone** if you don't have one yet - "
                "Google Authenticator, Microsoft Authenticator or your password manager all "
                "work, and they're free.")
    qr = _two_step_qr(uri)
    if qr:
        st.markdown(f"**2. Add {APP_NAME} to the app.** Tap *add* (often a **+**) and scan "
                    "this code with your phone's camera:")
        st.html(f'<img src="{qr}" width="190" height="190" alt="A code to scan with your '
                'authenticator app" style="border-radius: 8px">')
        st.caption(f"Can't scan it? Choose *enter a setup key* in the app and type this in "
                   f"(name it {APP_NAME}; it's a time-based key):")
    else:   # no QR library here: the key and the link do the same job
        st.markdown(f"**2. Add {APP_NAME} to the app.** Tap *add* (often a **+**), choose "
                    f"*enter a setup key*, name it {APP_NAME} and type this in (it's a "
                    "time-based key):")
    st.code(two_step.grouped(secret), language=None)
    st.link_button("Reading this on your phone? Add it to the app here", uri, type="tertiary",
                   icon=":material/smartphone:")
    st.markdown(f"**3. Type the 6-digit code** the app now shows for {APP_NAME}.")
    with st.form(f"two_step_setup_{where}", border=False):
        code = st.text_input("Code from the app", key=f"two_step_setup_code_{where}",
                             placeholder="123456", autocomplete="one-time-code")
        remember = False
        if st.session_state.get("session_token"):
            remember = st.checkbox(f"Don't ask for a code on this device for "
                                   f"{two_step.REMEMBER_DAYS} days", value=True,
                                   key=f"two_step_setup_remember_{where}",
                                   help="Leave this off on a shared or public computer.")
        go = st.form_submit_button("Turn on two-step sign-in", type="primary")
    if not go:
        return
    c = connect(DB)
    try:
        res = two_step.enable(c, uid, secret, code)
        if res["ok"] and remember:
            two_step.remember_device(c, st.session_state.get("session_token"), uid)
        stamp = two_step.status(c, uid)["stamp"]
    finally:
        c.close()
    if not res["ok"]:
        st.error(res["error"])
        return
    st.session_state.pop("two_step_secret", None)
    _two_step_done(stamp)
    st.session_state["two_step_codes"] = (where, res["backup_codes"])
    st.rerun()


def _two_step_codes_seen():
    st.session_state.pop("two_step_codes", None)


def _two_step_codes_box(where):
    """New backup codes, shown once, with a download. True while showing."""
    shown = st.session_state.get("two_step_codes")
    if not shown or shown[0] != where:
        return False
    codes = shown[1]
    with st.container(border=True):
        st.markdown(":material/key: **Save your backup codes**")
        st.caption("If your phone is ever lost or replaced, each of these signs you in once "
                   "in place of a code. Keep them somewhere safe - your password manager, or "
                   "printed at home. This is the only time they're shown.")
        st.code("\n".join(codes), language=None)
        with st.container(horizontal=True):
            st.download_button(
                "Download them", "\n".join([
                    f"{APP_NAME} backup codes for {st.session_state.get('username') or ''}",
                    "Each one works once, in place of a code from your phone.", "", *codes, ""]),
                file_name=f"{APP_NAME.lower()}-backup-codes.txt", mime="text/plain",
                on_click="ignore", icon=":material/download:", key=f"two_step_dl_{where}")
            st.button("I've saved them", type="primary", key=f"two_step_seen_{where}",
                      on_click=_two_step_codes_seen)
    return True


def _two_step_sign_out(notice):
    st.session_state.clear()
    st.session_state["signed_out"] = True
    st.session_state["login_notice"] = notice
    st.rerun()


def _two_step_page_top():
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        _logo_title(APP_NAME)
    return mid


def _two_step_gate() -> bool:
    """After the password (or a stay-signed-in cookie, or a setup / reset
    link): True when this tab may open the app. Otherwise it draws the code
    page, or the setup page for an advisor or admin who hasn't set two-step
    up, and returns False."""
    uid = st.session_state["user_id"]
    token = st.session_state.get("session_token")
    passed = st.session_state.get("two_step_ok")
    c = connect(DB)
    try:
        s, row = two_step.status_and_login(c, uid)
        # as of this check: the rest of this run reads them from here
        # (_gate_read) instead of reading the row again
        _GATE_ROW.clear()
        _GATE_ROW[uid] = (s, row)
        mine = f"{uid}:{s['stamp']}"
        remembered = (s["on"] and passed != mine
                      and two_step.device_remembered(c, token, uid))
    finally:
        c.close()
    # "Sign out other devices" (this login) or the admin's "Sign everyone
    # out" (every login) since this tab signed in: back to sign-in, so a tab
    # left open somewhere is closed too, not just the saved cookies (audit X5).
    # Noted here, first thing on every run, rather than once the app opens,
    # so a tab still on the code page is caught as well.
    gen = auth.session_gen_of(row)
    if gen is not None and st.session_state.setdefault("session_gen", gen) != gen:
        _two_step_sign_out("You've been signed out. Please sign in again.")
    if (passed and passed.startswith(f"{uid}:") and passed != f"{uid}:None"
            and not s["on"]):
        # it was on when this tab got in, and has been turned off or reset
        # since (the Admin portal, another device): the password again, so an
        # open tab can't set up a new phone on its own
        _two_step_sign_out("Two-step sign-in was changed for your account. Please sign in "
                           "again.")
    if passed == mine and _two_step_codes_box_page():
        return False
    if s["required"] and not s["on"]:
        _two_step_setup_page()
        return False
    if passed == mine:
        return True
    if not s["on"] or remembered:
        _two_step_done(s["stamp"])
        return True
    _two_step_code_page(uid, token, s["stamp"])
    return False


def _two_step_codes_box_page():
    """Right after setting it up at sign-in: the backup codes, before the app."""
    shown = st.session_state.get("two_step_codes")
    if not shown or shown[0] != "gate":
        return False
    mid = _two_step_page_top()
    with mid:
        st.success("Two-step sign-in is on. From now on you'll type a code from your phone "
                   "after your password.")
        _two_step_codes_box("gate")
    return True


def _two_step_setup_page():
    """An advisor or admin without two-step: set it up now - nothing else
    opens until it's on."""
    mid = _two_step_page_top()
    with mid:
        st.subheader("One more step to keep accounts safe", anchor=False)
        st.caption("Advisor and admin logins can open other people's portfolios, so they sign "
                   "in with two steps: your password, then a 6-digit code from an app on your "
                   "phone. Setting it up takes about two minutes, and you only do it once.")
        with st.container(border=True):
            _two_step_setup("gate")
        st.button("Sign out", key="two_step_setup_out", type="tertiary", on_click=_logout)


def _two_step_key_alert():
    """A stored two-step key wouldn't open with this copy's NORTHWEND_TOTP_KEY
    (a wrong or missing key): tell the admin like any error - its type and
    place only, at most an email an hour (error_alerts.py) - and Admin >
    System counts them. Never the key, never who."""
    try:
        raise two_step.KeyUnreadable("a stored two-step key didn't open with NORTHWEND_TOTP_KEY")
    except two_step.KeyUnreadable as ex:
        try:
            import error_alerts
            error_alerts.report(DB, ex, copy="Staging" if STAGING else "Live",
                                send=settings.send_error_alerts())
        except Exception:  # noqa: BLE001 - an alert must never break sign-in
            pass


def _two_step_code_page(uid, token, stamp):
    """Ask for the code from the phone (or a backup code)."""
    mid = _two_step_page_top()
    with mid:
        st.subheader("Enter your code", anchor=False)
        st.caption(f"Open the authenticator app on your phone and type the 6-digit code it "
                   f"shows for {APP_NAME}.")
        with st.form("two_step_form", border=True):
            code = st.text_input("Code", key="two_step_code", placeholder="123456",
                                 autocomplete="one-time-code")
            remember = False
            if token:
                remember = st.checkbox(f"Don't ask again on this device for "
                                       f"{two_step.REMEMBER_DAYS} days", value=True,
                                       key="two_step_remember",
                                       help="Leave this off on a shared or public computer.")
            go = st.form_submit_button("Continue", type="primary", width="stretch")
        with st.expander("Lost your phone?"):
            st.caption("Type one of your backup codes in the box above instead - each one "
                       f"works once. No backup codes either? Write to {disclosures.CONTACT} "
                       "and we'll help you back in once we've made sure it's you.")
        st.button("Sign out", key="two_step_code_out", type="tertiary", on_click=_logout)
    if not go:
        return
    c = connect(DB)
    try:
        res = two_step.verify(c, uid, code)
        if res["ok"] and remember:
            two_step.remember_device(c, token, uid)
    finally:
        c.close()
    if res.get("key_problem"):
        _two_step_key_alert()
    if not res["ok"]:
        mid.error(res["error"])
        return
    _two_step_done(stamp)
    if res["used_backup"]:
        n = res["backup_left"]
        st.session_state["email_flash"] = (
            False, f"You signed in with a backup code - {n} left. You can make a new set on "
                   "the Account page.")
    st.rerun()
