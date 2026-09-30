"""Waypoint (formerly Portfolio Tracker) - single-page Streamlit dashboard.

Run it:  streamlit run dashboard.py   (or double-click dashboard.cmd)
"""

import html
import json
import os
from datetime import date, datetime, timedelta, timezone

import altair as alt
import pandas as pd
import streamlit as st

import codefresh

# After a deploy, drop any of our modules still loaded at an older version so
# the imports below load one current set (see codefresh.py).
_OLD_MODULES = codefresh.drop_stale(os.path.dirname(os.path.abspath(__file__)))

import accounts
import advising
import alerts
import asset_classes
import auth
import charts
import csv_import
import disclosures
import friendly_errors
import learn
import live_prices
import manual_entry
import paste_parse
import screenshot_read
import sample_data
import metrics as M
import news
import perf
import pgcompat
import plans
import prefs
import watchlist
from allocation import CONCENTRATION_PCT, allocate
from portfolio import (SAMPLE_SOURCE, DBError, connect, delete_holdings, import_csv,
                       parse_csv_smart, snapshot_source, temp_upload, upload_label,
                       write_snapshot)
from update_prices import ENV_PATH, latest_snapshot, load_env, refresh_prices, resolve_key
from changes import diff_positions, synthesize_transactions

codefresh.carry_over(_OLD_MODULES)
codefresh.mark_loaded(os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))
# Defaults to ./portfolio.db; set PORTFOLIO_DB to point at another file (handy for
# trying the importer against a throwaway copy).
DB = os.environ.get("PORTFOLIO_DB") or os.path.join(HERE, "portfolio.db")

# An unexpected error shows "something went wrong" instead of a traceback; the
# traceback goes to the log. Details show on screen only for a local run.
friendly_errors.install(show_details=not pgcompat.is_postgres_dsn(DB)
                        and st.get_option("client.showErrorDetails") in ("full", True, "true"))

# said wherever people decide what to share (import, hand entry, paste)
TRUST_LINE = ("We never ask for your brokerage login. Only symbols, share counts and cost "
              "are saved - never balances or full account numbers.")
NOT_KEPT = ("Not kept: the file, image or pasted text itself, balances and gains, and account "
            "numbers beyond their last 3 digits.")

# The brand: Waypoint, with Sage as the guide (the AI Assistant). Pages keep
# their internal names (session state, links, `if PAGE == ...`); PAGE_LABELS
# is only what people see.
APP_NAME = "Waypoint"
TAGLINE = "Your guide from first step to goal."
GUIDE = "Sage"
APP_ICON = ":material/flag:"
PAGE_LABELS = {"AI Assistant": f"Ask {GUIDE}"}


def _label(page):
    return PAGE_LABELS.get(page, page)


SAGE_AVATAR = ":material/explore:"   # a compass, for Sage's chat messages


def _avatar(role):
    return SAGE_AVATAR if role == "assistant" else None


LIVE_EVERY_SEC = 60  # how often an open page checks for new prices (live_prices.py)


def _dialog_closed():
    """A dialog's X or Escape: live prices may redraw the page again (they
    wait while a dialog is open, since a redraw would close it)."""
    st.session_state["dialog_open"] = False


GREEN = "#16a34a"
RED = "#dc2626"

st.set_page_config(page_title=APP_NAME, page_icon=APP_ICON, layout="wide",
                   initial_sidebar_state="auto")

# App-wide styles: hide Streamlit's own running/deploy widgets, tighten the
# page on phones, and the classes used by the hero, stat tiles, and
# allocation bars below. Text inherits the theme's colors; only marks and
# gain/loss figures carry their own.
st.html("""<style>
[data-testid="stStatusWidget"], [data-testid="stAppDeployButton"], .stAppDeployButton {
  display: none !important; }
[data-testid="stMainBlockContainer"] { padding-top: 3rem; }
/* a slider's end label can poke past a phone's edge; never scroll sideways */
[data-testid="stMain"] { overflow-x: hidden; }
@media (max-width: 640px) {
  [data-testid="stMainBlockContainer"] { padding: 3.75rem 1rem 3rem; }
  h1 { font-size: 1.6rem !important; }
}
.pt-status { font-size: .8rem; opacity: .65; margin-top: -.6rem; }
.pt-hero-label { font-size: .85rem; opacity: .7; }
.pt-hero-value { font-size: 2.6rem; font-weight: 700; line-height: 1.15;
  font-variant-numeric: tabular-nums; }
.pt-hero-delta { font-size: 1rem; font-weight: 600; margin-top: .15rem; }
.pt-hero-sub { font-size: .8rem; opacity: .65; margin-top: .2rem; }
.pt-up { color: #16a34a; } .pt-down { color: #dc2626; }
.pt-live { color: #16a34a; }
.pt-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: .6rem; margin-top: 1rem; }
.pt-stat { border: 1px solid rgba(128,128,128,.25); border-radius: .5rem;
  padding: .55rem .7rem; min-width: 0; }
.pt-stat-label { font-size: .75rem; opacity: .7; white-space: nowrap; }
.pt-stat-value { font-size: 1.1rem; font-weight: 600; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; font-variant-numeric: tabular-nums; }
.pt-stat-sub { font-size: .8rem; font-weight: 600; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
@media (max-width: 640px) { .pt-hero-value { font-size: 2.2rem; }
  .pt-stat-value { font-size: .95rem; } }
.pt-alloc-title { font-size: .9rem; font-weight: 600; margin-bottom: .35rem; }
.pt-alloc-bar { display: flex; gap: 2px; height: 14px; border-radius: 4px;
  overflow: hidden; margin-bottom: .6rem; }
.pt-alloc-seg { height: 100%; min-width: 3px; }
.pt-legend { display: grid; gap: .3rem; margin-bottom: .75rem; }
.pt-legend-row { display: flex; align-items: center; gap: .5rem; font-size: .9rem; }
.pt-swatch { width: 10px; height: 10px; border-radius: 3px; flex: none; }
.pt-legend-label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; }
.pt-legend-pct { font-weight: 600; font-variant-numeric: tabular-nums; }
.pt-legend-val { opacity: .65; font-variant-numeric: tabular-nums; min-width: 5.5rem;
  text-align: right; }
.pt-acct { margin-bottom: .8rem; }
.pt-acct .pt-legend-row { margin-bottom: .3rem; }
.pt-alloc-bar.pt-mini { height: 8px; margin-bottom: 0; }
.pt-warn { color: #c98500; } .pt-muted { opacity: .7; }
.pt-chip { display: inline-block; padding: .1rem .6rem; border-radius: 999px; font-size: .8rem;
  font-weight: 600; border: 1px solid currentColor; }
.pt-goal-top { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; }
.pt-goal-pct { font-weight: 600; }
.pt-goal-track { height: 10px; border-radius: 5px; background: rgba(128,128,128,.2);
  overflow: hidden; margin: .5rem 0 .4rem; }
.pt-goal-fill { height: 100%; border-radius: 5px; background: #2a78d6; }
.pt-goal-sub { font-size: .8rem; opacity: .7; }
.pt-mix-track { position: relative; height: 8px; border-radius: 4px;
  background: rgba(128,128,128,.2); margin: 0 0 .6rem; }
.pt-mix-fill { height: 100%; border-radius: 4px; background: #2a78d6; }
.pt-mix-target { position: absolute; top: -3px; width: 3px; height: 14px; border-radius: 1px;
  margin-left: -1px; background: currentColor; }
</style>""")


SESSION_COOKIE = "pt_session"


def _cookie_script(token: str | None) -> str:
    """JS that stores the stay-signed-in token in a browser cookie, or with
    None deletes it. Streamlit can read cookies (st.context.cookies) but not
    set them, so the page does it. Secure on https; Lax keeps it off
    cross-site requests."""
    if token:
        value = f"{SESSION_COOKIE}={token}; Max-Age={auth.SESSION_DAYS * 86400}"
    else:
        value = f"{SESSION_COOKIE}=; Max-Age=0"
    return ("<script>document.cookie = " + json.dumps(value + "; Path=/; SameSite=Lax")
            + " + (location.protocol === 'https:' ? '; Secure' : '');</script>")


def _session_cookie() -> str | None:
    """The browser's stay-signed-in token, or None. Only ever a string -
    anything else (an empty or odd cookie jar) counts as no cookie."""
    value = st.context.cookies.get(SESSION_COOKIE)
    return value if isinstance(value, str) and value else None


def _render_disclosures(*, summary=True):
    """The About and disclosures text (disclosures.py) - the About page, and
    on the login screen for people who haven't signed in."""
    if summary:
        st.markdown(disclosures.SUMMARY)
    for title, body in disclosures.SECTIONS:
        st.subheader(title, anchor=False)
        st.markdown(body.strip())
    st.caption(f"Last updated {disclosures.LAST_UPDATED}.")


def _toggle_about():
    st.session_state["show_about"] = not st.session_state.get("show_about")


def _login() -> bool:
    """Per-account login - every account is admin-provisioned (see
    manage_users.py); there is no signup anywhere in this app. Sets
    st.session_state["user_id"]/["username"] on success. Generic error
    message on any failure (unknown username OR wrong password) so the
    login screen never reveals which username exists.

    A new browser session (a reload, a phone reopening the tab) first tries
    the stay-signed-in cookie; the token is checked against the database
    every time, so logging out or changing the password ends it."""
    if st.session_state.get("user_id"):
        return True
    cookie = _session_cookie()
    if cookie and not st.session_state.get("signed_out"):
        conn = connect(DB)
        try:
            found = auth.session_user(conn, cookie)
        finally:
            conn.close()
        if found:
            st.session_state["user_id"], st.session_state["username"] = found
            st.session_state["session_token"] = cookie
            return True
        st.session_state["signed_out"] = True  # a dead cookie: remove it below
    if st.session_state.get("signed_out") and cookie:
        st.html(_cookie_script(None), unsafe_allow_javascript=True)

    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        st.title(f"{APP_ICON} {APP_NAME}")
        st.caption(f"{TAGLINE} Sign in to see your portfolio.")
        _notice = st.session_state.get("login_notice")
        if _notice:
            st.info(_notice)
        with st.form("login_form", border=True):
            user = st.text_input("Username", key="login_user")
            pw = st.text_input("Password", type="password", key="login_pw")
            remember = st.checkbox(f"Stay signed in on this device ({auth.SESSION_DAYS} days)",
                                   value=True, key="login_remember",
                                   help="Leave this off on a shared or public computer.")
            submitted = st.form_submit_button("Log in", type="primary", width="stretch")
        st.caption(disclosures.SUMMARY)
        st.button("Hide about and disclosures" if st.session_state.get("show_about")
                  else "About and disclosures", key="login_about", type="tertiary",
                  on_click=_toggle_about)
    if st.session_state.get("show_about"):
        with mid.container(border=True):
            _render_disclosures(summary=False)  # the summary is just above
    if submitted:
        if not user or not pw:
            mid.error("Enter your username and password.")
            return False
        conn = connect(DB)
        try:
            # behind the lockout: too many wrong passwords locks the username
            result = auth.attempt_login(conn, user, pw)
            user_id = result["user_id"]
            token = auth.create_session(conn, user_id) if user_id is not None and remember else None
        finally:
            conn.close()
        if user_id is not None:
            st.session_state.pop("signed_out", None)
            st.session_state.pop("login_notice", None)
            st.session_state["user_id"] = user_id
            st.session_state["username"] = user
            st.session_state["session_token"] = token
            st.rerun()
        if result["locked_minutes"]:
            m = result["locked_minutes"]
            mid.error(f"Too many attempts. Try again in {m} minute{'s' if m != 1 else ''}, "
                      "or ask whoever manages your account to reset your password.")
        elif result["attempts_left"] <= 2:
            mid.error(f"Invalid username or password. {result['attempts_left']} more "
                      f"attempt{'s' if result['attempts_left'] != 1 else ''} before a "
                      f"{auth.LOCKOUT_MINUTES}-minute lock.")
        else:
            mid.error("Invalid username or password.")
    return False


def _logout():
    # Full session_state reset, not just clearing user_id/username - every
    # other key (hide_amounts, col_keys, last_open_snapshot, pill
    # selections, etc.) was populated for the PREVIOUS account and would
    # otherwise leak into the next login on the same browser tab even
    # though each account's own on-disk prefs file is already correctly
    # separated (PREFS_PATH is per-user) - the in-memory session state
    # isn't, unless explicitly cleared here. No st.rerun() needed - an
    # on_click callback is always followed by an automatic rerun, and
    # calling it explicitly here just logs a "no-op" warning.
    # The stay-signed-in session ends in the database (so the cookie is dead
    # even if deleting it fails), and "signed_out" stops the login page from
    # using the cookie and has it deleted from the browser.
    conn = connect(DB)
    try:
        auth.end_session(conn, st.session_state.get("session_token")
                         or _session_cookie())
    finally:
        conn.close()
    st.session_state.clear()
    st.session_state["signed_out"] = True


if not _login():
    st.stop()
# Just signed in with "stay signed in": put the token in the browser's cookie.
# Rendered on every run until a reload shows the browser has it, so a rerun
# right after login can't drop it.
if (st.session_state.get("session_token")
        and _session_cookie() != st.session_state["session_token"]):
    st.html(_cookie_script(st.session_state["session_token"]), unsafe_allow_javascript=True)

# Advisor mode: user_id is who logged in; active_user_id is whose data is
# showing. Every query below goes through USER_ID, so it's resolved here,
# re-checked against the database on every run - never trusted from
# session state alone.
LOGIN_ID = st.session_state["user_id"]
_conn = connect(DB)
try:
    # A password change (here, on another device, or by an admin or advisor)
    # signs out tabs that are already open, not just the saved cookies.
    _stamp = auth.password_stamp(_conn, LOGIN_ID)
    if st.session_state.setdefault("pw_stamp", _stamp) != _stamp:
        st.session_state.clear()
        st.session_state["signed_out"] = True
        st.session_state["login_notice"] = "Your password was changed. Sign in again."
        st.rerun()
    IS_ADVISOR = auth.is_advisor(_conn, LOGIN_ID)
    CLIENTS = auth.list_clients(_conn, LOGIN_ID) if IS_ADVISOR else []
    if "active_user_id" not in st.session_state:
        # a fresh session (reload, bookmark): start on the client in the address,
        # if any - re-checked by can_view just below, like every other run
        try:
            st.session_state["active_user_id"] = int(st.query_params.get("client", LOGIN_ID))
        except ValueError:
            pass
    _active = st.session_state.get("active_user_id", LOGIN_ID)
    if not auth.can_view(_conn, LOGIN_ID, _active):
        _active = LOGIN_ID
    ACCOUNT_LABELS = accounts.labels(_conn, _active)
    HAS_HOLDINGS = latest_snapshot(_conn, _active) is not None
    # A client whose account an advisor manages: the plan, target mix, alert
    # limits and imports are the advisor's, so the client's view is read-only
    # for those. MY_ADVISOR_CARD is how the advisor presents themselves.
    MY_ADVISOR = None if IS_ADVISOR else advising.advisor_of(_conn, LOGIN_ID)
    MY_ADVISOR_CARD = ({**(prefs.load(_conn, MY_ADVISOR).get("advisor_card") or {}),
                        "username": auth.get_username(_conn, MY_ADVISOR)} if MY_ADVISOR else {})
    # ...except imports, which the advisor can open up per client (Clients page)
    CLIENT_CAN_IMPORT = bool(MY_ADVISOR) and advising.client_can_import(_conn, LOGIN_ID)
finally:
    _conn.close()
USER_ID = _active
IS_MANAGED_CLIENT = MY_ADVISOR is not None
CAN_MANAGE = not IS_MANAGED_CLIENT         # may edit this account's plan, limits, imports
CAN_IMPORT = CAN_MANAGE or CLIENT_CAN_IMPORT  # may import statements into this account
ON_CLIENT = IS_ADVISOR and USER_ID != LOGIN_ID   # an advisor working on a client's account
st.session_state["active_user_id"] = USER_ID
ACTIVE_NAME = (st.session_state["username"] if USER_ID == LOGIN_ID
               else dict(CLIENTS).get(USER_ID, "client"))
# where this account's settings lived before they moved into the database;
# read once, the first time, so they carry over (prefs.py)
PREFS_PATH = os.path.join(HERE, f".dashboard_prefs.{USER_ID}.json")

# Get started leads for an account with nothing imported yet (and is where it
# lands); once there are holdings it moves to the end as a reference.
PAGES = [*([] if HAS_HOLDINGS else ["Get started"]),
         "Dashboard", "Plan", *(["Advisor notes"] if ON_CLIENT or IS_MANAGED_CLIENT else []),
         *(["Clients"] if IS_ADVISOR else []),
         "Watchlist", "Activity", "Income", "AI Assistant",
         *(["Get started"] if HAS_HOLDINGS else []), "About"]


def _slug(page):
    """A page's name in the address: 'Ask Sage' -> 'ask-sage'."""
    return _label(page).lower().replace(" ", "-")


if "page" not in st.session_state:
    # a fresh session: start on the page in the address (?page=plan), if it's
    # one this account can open
    st.session_state["page"] = {_slug(p): p for p in PAGES}.get(
        str(st.query_params.get("page", "")).lower(), PAGES[0])
if st.session_state.get("page") not in PAGES:
    st.session_state["page"] = PAGES[0]

# kept when an advisor switches accounts; everything else is per-account
_KEEP_ON_SWITCH = ("user_id", "username", "page", "session_token", "pw_stamp")


def _go(page):
    st.session_state["page"] = page


def _advisor_display_name():
    """The managing advisor's name as they've chosen to show it."""
    card = MY_ADVISOR_CARD
    return (card.get("name") or card.get("username") or "your advisor") +         (f", {card['firm']}" if card.get("firm") else "")


def _switch_to(account_id):
    for k in list(st.session_state.keys()):
        if k not in _KEEP_ON_SWITCH:
            del st.session_state[k]
    st.session_state["active_user_id"] = account_id
    st.session_state["viewing_select"] = account_id


def _on_viewing_change():
    _switch_to(st.session_state["viewing_select"])


def _open_client(account_id):
    _switch_to(account_id)
    st.session_state["page"] = "Dashboard"


def _add_client():
    name = (st.session_state.get("new_client_name") or "").strip()
    pw = st.session_state.get("new_client_pw") or None
    c = connect(DB)
    try:
        client_id = auth.create_client(c, st.session_state["user_id"], name, pw)
    except ValueError as exc:
        st.session_state["client_msg"] = ("error", str(exc))
        return
    except DBError:
        st.session_state["client_msg"] = ("error", f"The username '{name}' is already taken.")
        return
    finally:
        c.close()
    _switch_to(client_id)
    st.session_state["client_msg"] = ("success", f"Added client '{name}' - you're now viewing them.")


def _set_client_password():
    pw = st.session_state.get("client_login_pw") or ""
    if len(pw) < auth.MIN_PASSWORD_LENGTH:
        st.session_state["client_msg"] = (
            "error", f"Use a password of at least {auth.MIN_PASSWORD_LENGTH} characters.")
        return
    viewer, target = st.session_state["user_id"], st.session_state["active_user_id"]
    c = connect(DB)
    try:
        if viewer == target or not auth.can_view(c, viewer, target):
            st.session_state["client_msg"] = ("error", "You can only set passwords for your clients.")
            return
        auth.set_password(c, auth.get_username(c, target), pw)
    finally:
        c.close()
    st.session_state["client_login_pw"] = ""
    st.session_state["client_msg"] = ("success", "Login password set - the client can log in now.")


def _delete_my_holdings():
    if not st.session_state.get("confirm_delete_holdings"):
        return
    c = connect(DB)
    try:
        delete_holdings(c, st.session_state["user_id"])  # own account only
    finally:
        c.close()
    st.session_state["confirm_delete_holdings"] = False
    st.session_state["import_flash"] = "All your holdings were deleted."
    _after_import()


def _change_password():
    cur, new, again = (st.session_state.get(k) or "" for k in ("pw_current", "pw_new", "pw_again"))
    if new != again:
        st.session_state["pw_msg"] = ("error", "The new passwords don't match.")
        return
    c = connect(DB)
    try:
        # a stay-signed-in browser gets a fresh session; every other one ends
        result = auth.change_password(c, st.session_state["user_id"], cur, new,
                                      keep_session=bool(st.session_state.get("session_token")))
        stamp = auth.password_stamp(c, st.session_state["user_id"]) if result["ok"] else None
    finally:
        c.close()
    if not result["ok"]:
        st.session_state["pw_msg"] = ("error", result["error"])
        return
    for k in ("pw_current", "pw_new", "pw_again"):
        st.session_state[k] = ""
    st.session_state["pw_stamp"] = stamp  # keeps this tab signed in
    if result["token"]:
        st.session_state["session_token"] = result["token"]  # the cookie follows on this run
    st.session_state["pw_msg"] = ("success", "Password changed. Your other devices are signed out.")


def _open_holdings_dialog(kind):
    """A sidebar Holdings button: the sidebar is drawn before this account's
    holdings are loaded, so it leaves a note and the dialog opens just after
    they are (see open_dialog below load())."""
    if kind == "manual":
        _manual_clear()  # start from the latest snapshot
    st.session_state["open_dialog"] = kind


with st.sidebar:
    st.markdown(f"### {APP_ICON} {APP_NAME}")
    st.caption(TAGLINE)
    for _p in PAGES:
        st.button(_label(_p), key=f"nav_{_p}", on_click=_go, args=(_p,), width="stretch",
                  type="primary" if st.session_state["page"] == _p else "tertiary")
    st.divider()

    if IS_ADVISOR:
        _accounts = {LOGIN_ID: f"My portfolio ({st.session_state['username']})", **dict(CLIENTS)}
        st.session_state["viewing_select"] = USER_ID
        st.selectbox("Viewing", list(_accounts), format_func=_accounts.get,
                     key="viewing_select", on_change=_on_viewing_change)
        _msg = st.session_state.pop("client_msg", None)
        if _msg:
            getattr(st, _msg[0])(_msg[1])
        with st.expander("Add client"):
            st.text_input("Username", key="new_client_name")
            st.text_input("Login password (optional)", type="password", key="new_client_pw",
                          help="Leave blank for a client you manage without them logging in. "
                               "You can give them a login later.")
            st.button("Add client", on_click=_add_client, width="stretch")
        if USER_ID != LOGIN_ID:
            with st.expander("Client login"):
                st.caption(f"Set a password so **{ACTIVE_NAME}** can log in and see their own "
                           "portfolio.")
                st.text_input("New password", type="password", key="client_login_pw")
                st.button("Set login password", on_click=_set_client_password,
                          width="stretch")
        st.divider()

    if CAN_IMPORT:
        st.markdown("**Holdings**" + (f" · {ACTIVE_NAME}" if USER_ID != LOGIN_ID else ""))
        st.button(":material/content_paste: Paste or type holdings", key="sb_manual",
                  width="stretch", on_click=_open_holdings_dialog, args=("manual",),
                  help="Paste your positions from any brokerage's website, read them from "
                       "screenshots, type them in, or use percentages only.")
        st.button(":material/upload_file: Upload a CSV", key="sb_import", width="stretch",
                  on_click=_open_holdings_dialog, args=("import",),
                  help="A Positions export file from your brokerage.")
        if not HAS_HOLDINGS:
            st.button(":material/science: Try example data", key="sb_sample", width="stretch",
                      on_click=lambda: _load_sample(),  # defined further down
                      help="A made-up portfolio to explore with. Removed when you add your own.")
        st.divider()

    # flips light/dark in the browser (ui_enhancements.js); nothing runs here
    st.button(":material/contrast: Light / dark", key="pt_theme", type="tertiary",
              width="stretch", help="Switch between the light and dark theme. System, Light and "
                                    "Dark are also in the ⋮ menu at the top right.")
    if IS_MANAGED_CLIENT:
        st.caption(f"Your advisor: **{_advisor_display_name()}**")
    _viewing = f" · viewing **{ACTIVE_NAME}**" if USER_ID != LOGIN_ID else ""
    st.caption(f"Logged in as **{st.session_state['username']}**{_viewing}")
    _pw_msg = st.session_state.pop("pw_msg", None)
    with st.expander("Change password", expanded=bool(_pw_msg)):
        if _pw_msg:
            getattr(st, _pw_msg[0])(_pw_msg[1])
        with st.form("change_pw_form", border=False):
            st.text_input("Current password", type="password", key="pw_current")
            st.text_input("New password", type="password", key="pw_new",
                          help=f"At least {auth.MIN_PASSWORD_LENGTH} characters.")
            st.text_input("New password again", type="password", key="pw_again")
            st.form_submit_button("Change password", on_click=_change_password, width="stretch")
    if CAN_MANAGE and USER_ID == LOGIN_ID:
        with st.expander("Your data"):
            st.caption("Delete everything you've imported or entered: holdings, cash, "
                       "activity and value history. Your goals, settings and login stay.")
            st.checkbox("Yes, delete all my holdings", key="confirm_delete_holdings")
            st.button("Delete all my holdings", key="delete_holdings", width="stretch",
                      disabled=not st.session_state.get("confirm_delete_holdings"),
                      on_click=_delete_my_holdings)
    st.button("Log out", on_click=_logout, width="stretch")
    # sidebar handle, click-away to close, pull to refresh (see the file)
    with open(os.path.join(HERE, "ui_enhancements.js"), encoding="utf-8") as _fh:
        st.html(f"<script>{_fh.read()}</script>", unsafe_allow_javascript=True)

PAGE = st.session_state["page"]
# Keep where you are in the address, so a reload or a bookmark comes back here
# (read above, for a fresh session). The client is re-checked on every load.
_want_qp = {"page": _slug(PAGE), **({"client": str(USER_ID)} if USER_ID != LOGIN_ID else {})}
if dict(st.query_params) != _want_qp:
    st.query_params.from_dict(_want_qp)


def _anthropic_key() -> str | None:
    """Same resolution order as resolve_key() uses for FINNHUB_API_KEY -
    .env locally, then the OS environment (which is how Streamlit
    Community Cloud exposes its Secrets UI entries). None if unset -
    every AI-assisted-parsing call site treats that as "skip the AI
    fallback, strict parsing only," today's exact behavior."""
    return (load_env(ENV_PATH).get("ANTHROPIC_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
            or "").strip() or None


CHAT_MESSAGE_LIMIT = 40  # per session - a simple guard on API spend
QUICK_STARTS = {
    "Help me get started": "I'm new to investing. Help me figure out how to get started.",
    "Review my portfolio": "Review my current portfolio against my goals and suggest improvements.",
    "Check for overlap and concentration": "Check my holdings for overlap between funds and "
                                           "for anything I'm too concentrated in.",
}


def _legacy_prefs_path(account_id):
    return os.path.join(HERE, f".dashboard_prefs.{account_id}.json")


def _rules_for(account_id, conn=None):
    """That account's saved alert limits, else defaults."""
    c = conn or connect(DB)
    try:
        saved = prefs.load(c, account_id, _legacy_prefs_path(account_id)).get("rules") or {}
    finally:
        if conn is None:
            c.close()
    if not isinstance(saved, dict):
        saved = {}
    return [{**r, "abs_gt": float(saved.get(r["key"], r["abs_gt"]))} for r in alerts.DEFAULT_RULES]


# ---- advisor notes, the advisor card, the clients page ------------------------ #
_NOTE_ICON = {"Review": ":material/event:", "Note": ":material/notes:",
              "Next step": ":material/flag:"}


def _render_advisor_card(card):
    """How a managed client sees their advisor: name, firm, contact, message."""
    name = card.get("name") or card.get("username") or "Your advisor"
    contact = " · ".join(v for v in (card.get("email"), card.get("phone")) if v)
    with st.container(border=True):
        _md(f"**Your advisor: {name}**" + (f" · {card['firm']}" if card.get("firm") else ""))
        if contact:
            st.caption(contact)
        if card.get("message"):
            _md(card["message"])


def _notes_for_view(conn):
    """This account's advisor notes as the viewer may see them: an advisor on a
    client's account sees private ones too; the client never does."""
    return advising.list_notes(conn, USER_ID, include_private=ON_CLIENT)


def _render_notes():
    today = datetime.now().date()
    conn = connect(DB)
    try:
        notes = _notes_for_view(conn)
    finally:
        conn.close()
    if IS_MANAGED_CLIENT:
        _render_advisor_card(MY_ADVISOR_CARD)

    if ON_CLIENT:
        with st.expander("Add a note", expanded=not notes):
            with st.form("note_form", clear_on_submit=True, border=False):
                c1, c2 = st.columns([2, 1])
                kind = c1.segmented_control("Type", advising.NOTE_KINDS, default="Note",
                                            help="A Review is a meeting - the latest one is "
                                                 "this client's last review. A Next step is "
                                                 "something to do; tick it off when it's done.")
                on = c2.date_input("Date", value=today, max_value=today)
                body = st.text_area("Note", placeholder="e.g. Reviewed the plan together; "
                                                        "moving the monthly amount to $600.")
                private = st.checkbox("Private - only you see this, never the client")
                if st.form_submit_button("Save note", type="primary"):
                    c = connect(DB)
                    try:
                        advising.add_note(c, USER_ID, LOGIN_ID, kind or "Note", body,
                                          on.isoformat(), private)
                    except ValueError as exc:
                        st.error(str(exc).capitalize() + ".")
                    else:
                        st.rerun()
                    finally:
                        c.close()

    def _set_done(note_id, done):
        c = connect(DB)
        try:
            advising.set_done(c, USER_ID, note_id, done)
        finally:
            c.close()

    def _delete(note_id):
        c = connect(DB)
        try:
            advising.delete_note(c, USER_ID, note_id)
        finally:
            c.close()

    steps = advising.open_next_steps(notes)
    st.markdown("#### Next steps")
    if not steps:
        st.caption("No open next steps." if notes or ON_CLIENT else
                   "Nothing here yet - your advisor's next steps for you show up here.")
    for n in steps:
        with st.container(border=True):
            _md(f":material/flag: {n['body']}")
            with st.container(horizontal=True, vertical_alignment="center"):
                st.caption(f"From {_fmt_date(n['note_date'])}"
                           + (" · Private" if n["private"] else ""))
                if ON_CLIENT:
                    st.button("Mark done", key=f"note_done_{n['id']}", type="tertiary",
                              on_click=_set_done, args=(n["id"], True))

    st.markdown("#### Timeline")
    if not notes:
        st.caption("No notes yet." if ON_CLIENT else "Notes from your advisor show up here.")
    for n in notes:
        label = n["kind"] + (" (done)" if n["kind"] == "Next step" and n["done"] else "")
        with st.container(border=True):
            st.caption(f"{_NOTE_ICON.get(n['kind'], '')} **{label}** · {_fmt_date(n['note_date'])}"
                       + (" · :orange[Private]" if n["private"] else ""))
            _md(n["body"])
            if ON_CLIENT:
                with st.container(horizontal=True):
                    if n["kind"] == "Next step" and n["done"]:
                        st.button("Reopen", key=f"note_undo_{n['id']}", type="tertiary",
                                  on_click=_set_done, args=(n["id"], False))
                    st.button("Delete", key=f"note_del_{n['id']}", type="tertiary",
                              on_click=_delete, args=(n["id"],))
    if ON_CLIENT:
        st.caption("The client sees everything here except private notes.")


def _advisor_notes_card():
    """Dashboard line for an account with an advisor: the latest note and the
    open next steps, linking to Advisor notes."""
    conn = connect(DB)
    try:
        notes = _notes_for_view(conn)
        last = advising.last_review(conn, USER_ID)
    finally:
        conn.close()
    steps = advising.open_next_steps(notes)
    with st.container(border=True, horizontal=True, vertical_alignment="center"):
        if ON_CLIENT:
            review, days = advising.review_status(last, datetime.now().date())
            text = ("No review yet" if review == "never" else
                    f"Last review {days} day{'s' if days != 1 else ''} ago"
                    + (" - due" if review == "due" else ""))
        else:
            latest = next((n for n in notes), None)
            first_line = (latest["body"].splitlines() or [""])[0] if latest else ""
            text = (f"**From {_advisor_display_name()}**: "
                    + (first_line[:90] + ("…" if len(first_line) > 90 else "") if latest
                       else "no notes yet"))
        text += f" · {len(steps)} open next step{'s' if len(steps) != 1 else ''}" if steps else ""
        st.markdown(text.replace("$", r"\$"), width="stretch")
        st.button("Advisor notes", key="dash_notes", type="tertiary", on_click=_go,
                  args=("Advisor notes",))


def _render_advisor_settings():
    """The advisor's own card as clients see it, stored in their settings."""
    conn = connect(DB)
    try:
        p = prefs.load(conn, LOGIN_ID)
    finally:
        conn.close()
    card = p.get("advisor_card") or {}
    with st.expander("How clients see you"):
        with st.form("advisor_card_form", border=False):
            c1, c2 = st.columns(2)
            name = c1.text_input("Your name", value=card.get("name") or "", max_chars=60,
                                 placeholder=st.session_state["username"])
            firm = c2.text_input("Firm (optional)", value=card.get("firm") or "", max_chars=80)
            email = c1.text_input("Email (optional)", value=card.get("email") or "", max_chars=100)
            phone = c2.text_input("Phone (optional)", value=card.get("phone") or "", max_chars=40)
            message = st.text_area("A note for your clients (optional)", max_chars=300,
                                   value=card.get("message") or "",
                                   placeholder="e.g. Questions any time - I'll reply within a day.")
            if st.form_submit_button("Save", type="primary"):
                p["advisor_card"] = {k: v.strip() for k, v in (
                    ("name", name), ("firm", firm), ("email", email), ("phone", phone),
                    ("message", message)) if v.strip()}
                c = connect(DB)
                try:
                    prefs.save(c, LOGIN_ID, p)
                finally:
                    c.close()
                st.toast("Saved - your clients see this on their Advisor notes page.")
        st.caption("Shown to clients whose accounts you manage, on their Advisor notes page and "
                   "in the sidebar.")


def _render_models():
    st.subheader("Model portfolios")
    conn = connect(DB)
    try:
        models = advising.list_models(conn, LOGIN_ID)
    finally:
        conn.close()

    def _delete_model(model_id):
        c = connect(DB)
        try:
            advising.delete_model(c, LOGIN_ID, model_id)
        finally:
            c.close()

    if not models:
        st.caption("Save a target mix you use often, then apply it to any client from their "
                   "Plan page.")
    for m in models:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(f"**{m['name']}** - " + (advising.mix_text(m["target_alloc"]) or
                        "*no targets - the old mix used ETF / CEF or Mutual Funds, which can't be "
                        "moved to stocks / bonds. Save it again under the same name.*"),
                        width="stretch")
            st.button(":material/delete:", key=f"model_del_{m['id']}", type="tertiary",
                      on_click=_delete_model, args=(m["id"],), help="Delete this model")
    with st.expander("New model portfolio"):
        with st.form("model_form", border=False):
            name = st.text_input("Name", max_chars=60, placeholder="e.g. Balanced 60/40",
                                 help="Saving with an existing name replaces that model.")
            cols = st.columns(len(advising.MODEL_ASSET_TYPES))
            mix = {t: cols[i].number_input(f"{t} %", min_value=0.0, max_value=100.0,
                                           step=5.0, format="%.0f", key=f"model_{t}")
                   for i, t in enumerate(advising.MODEL_ASSET_TYPES)}
            if st.form_submit_button("Save model", type="primary"):
                c = connect(DB)
                try:
                    advising.save_model(c, LOGIN_ID, name, mix)
                except ValueError as exc:
                    st.error(str(exc).capitalize() + ".")
                else:
                    st.rerun()
                finally:
                    c.close()
        st.caption("Targets are by what holdings hold: a stock fund counts as stocks, a bond "
                   "fund as bonds, and a balanced fund is split between them.")


def _set_can_import(client_id):
    allowed = bool(st.session_state.get(f"can_import_{client_id}"))
    c = connect(DB)
    try:
        # set_client_can_import only touches the advisor's own clients
        advising.set_client_can_import(c, st.session_state["user_id"], client_id, allowed)
    finally:
        c.close()


def _render_clients():
    import overview

    today = datetime.now().date()
    if not CLIENTS:
        st.info("No clients yet - add one with **Add client** in the sidebar.")
    else:
        conn = connect(DB)
        try:
            quotes = overview.latest_quotes(conn)
            rows = []
            for cid, name in CLIENTS:
                summ = overview.account_summary(conn, cid, quotes, _rules_for(cid, conn))
                plan = plans.get_plan(conn, cid)
                goal = (plans.progress(plan, summ["portfolio_value"] or 0.0, today=today)
                        if plans.has_goal(plan) else None)
                drift = (advising.max_drift(summ["alloc_pct"], (plan or {}).get("target_alloc"))
                         if summ["has_data"] else None)
                review, days = advising.review_status(advising.last_review(conn, cid), today)
                steps = advising.open_next_steps(advising.list_notes(conn, cid, include_private=True))
                rows.append({**summ, "name": name, "plan": plan, "goal": goal, "drift": drift,
                             "can_import": advising.client_can_import(conn, cid),
                             "review": review, "review_days": days, "n_steps": len(steps),
                             "reasons": advising.attention(
                                 has_data=summ["has_data"],
                                 goal_status=goal["status"] if goal else None, review=review,
                                 n_alerts=summ["n_alerts"], drift=drift,
                                 profile_done=summ["profile_answered"] >= summ["profile_total"])})
        finally:
            conn.close()
        # who needs a look first, then the biggest accounts
        rows.sort(key=lambda r: (-len(r["reasons"]), -(r["portfolio_value"] or 0.0)))

        st.html("<div class='pt-stats'>"
                f"<div class='pt-stat'><div class='pt-stat-label'>Clients</div>"
                f"<div class='pt-stat-value'>{len(rows)}</div></div>"
                f"<div class='pt-stat'><div class='pt-stat-label'>Total value</div>"
                f"<div class='pt-stat-value'>{fmt_money0(sum(r['portfolio_value'] or 0 for r in rows))}"
                "</div></div>"
                f"<div class='pt-stat'><div class='pt-stat-label'>Need attention</div>"
                f"<div class='pt-stat-value'>{sum(1 for r in rows if r['reasons'])}</div>"
                f"<div class='pt-stat-sub'>{sum(1 for r in rows if r['review'] != 'ok')} review(s) due"
                "</div></div></div>")

        cols = st.columns(2)
        for i, r in enumerate(rows):
            with cols[i % 2], st.container(border=True):
                gain = r["gain_pct"]
                chips = "".join(f"<span class='pt-chip pt-warn'>{html.escape(x)}</span> "
                                for x in r["reasons"]) or "<span class='pt-chip pt-up'>All good</span>"
                bits = []
                if r["goal"]:
                    g, plan = r["goal"], r["plan"]
                    goal_name = html.escape(plan.get("goal_name") or plan["goal_type"] or "Goal")
                    pct_txt = mask_or(f"{g['pct_of_target'] or 0:.0f}%")
                    bits.append(f"{goal_name}: {pct_txt} of {fmt_money0(g['target'])}, "
                                f"{PLAN_STATUS[g['status']][0].lower()}")
                bits.append("never reviewed" if r["review"] == "never"
                            else f"reviewed {r['review_days']}d ago")
                if r["n_steps"]:
                    bits.append(f"{r['n_steps']} open next step{'s' if r['n_steps'] != 1 else ''}")
                if r["snapshot_date"]:
                    bits.append(f"statement {_fmt_date(r['snapshot_date'])}")
                st.html(
                    "<div class='pt-goal-top'>"
                    f"<b>{html.escape(r['name'])}</b>"
                    + (f"<span>{fmt_money0(r['portfolio_value'])}</span>"
                       f"{_tone(gain, fmt_pct(gain)) if gain is not None else ''}"
                       if r["has_data"] else "<span class='pt-muted'>no statement yet</span>")
                    + f"</div><div style='margin:.45rem 0'>{chips}</div>"
                    f"<div class='pt-goal-sub'>{' · '.join(bits)}</div>")
                with st.container(horizontal=True, vertical_alignment="center"):
                    st.button("Open", key=f"open_client_{r['user_id']}", on_click=_open_client,
                              args=(r["user_id"],))
                    key = f"can_import_{r['user_id']}"
                    st.session_state[key] = r["can_import"]  # always what's saved
                    st.toggle("Client can import", key=key, on_change=_set_can_import,
                              args=(r["user_id"],),
                              help="Let this client import their own statements. Their plan, "
                                   "goal, target mix and alert limits stay yours to set.")
        st.caption(f"Sorted by what needs a look. Reviews are due {advising.REVIEW_EVERY_DAYS} days "
                   f"after the last one; drift is flagged past {advising.DRIFT_ATTENTION_PTS:g} "
                   "points from the plan's target mix; alerts use each client's own limits.")
    st.divider()
    _render_models()
    st.divider()
    _render_advisor_settings()


# The investing-profile form: every answer is a tap, not typing. Keys match
# advisor.PROFILE_FIELDS; the wording here is just for the form.
PROFILE_QUESTIONS = {
    "goal": "What are you investing for? Pick all that apply.",
    "time_horizon_years": "When will you need most of this money?",
    "target_return_pct": "What yearly return are you hoping for?",
    "risk_tolerance": "How much risk are you comfortable with?",
    "drawdown_reaction": "If your portfolio dropped 20% in a month, you would...",
    "experience": "How much investing experience do you have?",
    "age_range": "Your age",
    "income_stability": "How steady is your income?",
    "emergency_fund": "Emergency savings outside this portfolio",
    "high_interest_debt": "High-interest debt, like credit cards",
    "employer_match": "Does your employer match what you put into a retirement plan?",
    "contributions": "How often will you add money?",
    "withdrawal_needs": "Planning to take money out in the next 3 years?",
    "preferences": "Anything you'd like in your investments? Pick any.",
}
PROFILE_SECTIONS = (
    ("Goals", ("goal", "time_horizon_years", "target_return_pct")),
    ("Comfort with risk", ("risk_tolerance", "drawdown_reaction", "experience")),
    ("Your situation", ("age_range", "income_stability", "emergency_fund",
                        "high_interest_debt", "employer_match", "contributions",
                        "withdrawal_needs")),
    ("Preferences", ("preferences",)),
)
HORIZON_YEARS = (1, 2, 3, 5, 7, 10, 15, 20, 25, 30, 40)
TARGET_RETURNS = (3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 12.0, 15.0)
_NOT_SET = "Not set"


def _with_current(options, current):
    """`options` plus a saved value that isn't one of them (answers saved
    before the presets existed), so the form still shows it."""
    return sorted({*options, current}) if current is not None and current not in options \
        else list(options)


def _render_profile_form(advisor, profile):
    with st.form("investor_profile_form", border=False):
        answers = {}
        for title, fields in PROFILE_SECTIONS:
            st.markdown(f"**{title}**")
            for field in fields:
                q, cur = PROFILE_QUESTIONS[field], profile.get(field)
                if field in advisor.MULTI_CHOICES:
                    chosen = advisor.split_multi(cur)
                    opts = list(advisor.MULTI_CHOICES[field]) + [c for c in chosen
                                                                 if c not in advisor.MULTI_CHOICES[field]]
                    answers[field] = st.pills(q, opts, selection_mode="multi", default=chosen)
                elif field in advisor.CHOICES:
                    opts = list(advisor.CHOICES[field]) + (
                        [cur] if cur and cur not in advisor.CHOICES[field] else [])
                    answers[field] = st.pills(q, opts, default=cur or None,
                                              format_func=lambda v: v[:1].upper() + v[1:])
                elif field == "time_horizon_years":
                    cur = int(cur) if cur else None
                    answers[field] = st.select_slider(
                        q, [_NOT_SET, *_with_current(HORIZON_YEARS, cur)], value=cur or _NOT_SET,
                        format_func=lambda v: v if v == _NOT_SET else
                        f"{v} year{'s' if v != 1 else ''}{'+' if v == HORIZON_YEARS[-1] else ''}")
                elif field == "target_return_pct":
                    cur = float(cur) if cur else None
                    answers[field] = st.select_slider(
                        q, ["Not sure", *_with_current(TARGET_RETURNS, cur)],
                        value=cur or "Not sure",
                        format_func=lambda v: v if isinstance(v, str) else f"{v:g}%")
        notes = st.text_area("Other notes", value=profile["notes"] or "",
                             placeholder="Anything else worth knowing: a date you're saving "
                                         "toward, accounts elsewhere, investments to avoid...")
        if st.form_submit_button("Save profile", type="primary"):
            fields = {}
            for field, v in answers.items():
                if isinstance(v, list):
                    order = advisor.MULTI_CHOICES[field]
                    v = advisor.MULTI_SEP.join(sorted(
                        v, key=lambda x: order.index(x) if x in order else len(order)))
                fields[field] = None if v in (None, "", _NOT_SET, "Not sure") else v
            fields["notes"] = notes.strip() or None
            conn = connect(DB)
            try:
                advisor.save_profile(conn, USER_ID, fields, replace=True)
            finally:
                conn.close()
            st.rerun()


def _render_plan_export(api_key, profile, memory, contexts, cash_by_account, display):
    """'Client plan' block: one API call for next steps, then a PDF download.
    The PDF lives in session state only, so switching accounts drops it."""
    import advisor
    import anthropic
    import client_plan

    with st.expander("Client plan (PDF)", expanded=False):
        st.caption("A printable plan for this account: profile, allocation, holdings with "
                   "dollar amounts, things to watch, and AI-suggested next steps. The AI only "
                   "sees percentages; the dollar figures are added on this machine.")
        blocked = ("Turn off Hide amounts to create a plan - it includes dollar figures."
                   if _hidden() else
                   "Import positions for this account first." if not contexts else None)
        if st.button("Create plan", disabled=bool(blocked), help=blocked):
            conn = connect(DB)
            try:
                facts = client_plan.build_facts(conn, USER_ID, contexts, cash_by_account,
                                                _rules_for(USER_ID))
            finally:
                conn.close()
            steps = None
            with st.spinner("Writing suggested next steps..."):
                try:
                    steps = client_plan.next_steps(
                        anthropic.Anthropic(api_key=api_key), profile,
                        advisor.portfolio_summary(contexts, cash_by_account, CLASS_SPLITS),
                        client_plan.chat_transcript(display), memory)
                except anthropic.AuthenticationError:
                    st.warning("The ANTHROPIC_API_KEY was rejected - the plan was made "
                               "without suggested next steps.")
                except anthropic.RateLimitError:
                    st.warning(f"{GUIDE} is busy right now - the plan was made "
                               "without suggested next steps.")
                except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
                    st.warning(f"Couldn't reach {GUIDE} ({exc}) - the plan was made "
                               "without suggested next steps.")
            today = datetime.now().date()
            st.session_state["plan_pdf"] = {
                "data": client_plan.render_pdf(
                    facts, steps, account_name=ACTIVE_NAME, today=today,
                    advisor_name=None if USER_ID == LOGIN_ID else st.session_state["username"]),
                "name": f"plan-{ACTIVE_NAME}-{today.isoformat()}.pdf",
            }
        plan = st.session_state.get("plan_pdf")
        if plan and not blocked:
            st.download_button("Download plan", plan["data"], file_name=plan["name"],
                               mime="application/pdf", type="primary")


# ---- Plan page ------------------------------------------------------------ #
# status -> (label, css tone); the label always goes with the color
PLAN_STATUS = {
    "reached": ("Goal reached", "pt-up"),
    "on_track": ("On track", "pt-up"),
    "within_reach": ("Within reach", "pt-warn"),
    "behind": ("Behind", "pt-down"),
    "past_date": ("Date passed", "pt-muted"),
}
# the profile's goal answers -> the plan's goal types
_GOAL_FROM_PROFILE = {"Retirement": "Retirement", "Buy a home": "Buy a home",
                      "Pay for education": "Pay for education",
                      "Build long-term wealth": "Build long-term wealth",
                      "Save for a big purchase": "Big purchase"}
RETURN_CHOICES = tuple(float(p) for p in range(2, 11))


def _fmt_month(d):
    """'Jan 2055' from '2055-01-01'."""
    try:
        d = datetime.strptime(str(d)[:10], "%Y-%m-%d")
    except ValueError:
        return str(d)
    return f"{d:%b} {d.year}"


def _time_left(months):
    if months <= 0:
        return "no time left"
    y, m = divmod(months, 12)
    parts = ([f"{y} year{'s' if y != 1 else ''}"] if y else []) + \
            ([f"{m} month{'s' if m != 1 else ''}"] if m else [])
    return " ".join(parts) + " left"


def _plan_author(plan):
    """Who last saved the plan, from the viewer's side. Only the owner and
    their advisor can save it, so anyone else an owner sees is the advisor."""
    by = plan.get("set_by")
    if not by or by == LOGIN_ID:
        return "Set by you"
    conn = connect(DB)
    try:
        name = auth.get_username(conn, by) or "someone else"
    finally:
        conn.close()
    return f"Set by your advisor {name}" if USER_ID == LOGIN_ID else f"Set by {name}"


def _plan_return_pct():
    """The assumed yearly return for projections: the slider's value this
    session, else the saved one, else plans.DEFAULT_RETURN_PCT."""
    if "plan_return" not in st.session_state:
        saved = _read_prefs().get("plan_return_pct")
        st.session_state["plan_return"] = float(saved) if saved in RETURN_CHOICES \
            else plans.DEFAULT_RETURN_PCT
    return st.session_state["plan_return"]


def _goal_progress(plan, value):
    return plans.progress(plan, value or 0.0, today=datetime.now().date(),
                          return_pct=_plan_return_pct())


def _render_plan_form(plan, today):
    import advisor

    plan = plan or {}
    conn = connect(DB)
    try:
        profile = advisor.get_profile(conn, USER_ID)
    finally:
        conn.close()
    first_goal = (advisor.split_multi(profile.get("goal")) or [None])[0]
    horizon = int(profile.get("time_horizon_years") or 10)
    when_default = (datetime.strptime(plan["target_date"], "%Y-%m-%d").date()
                    if plan.get("target_date") else plans.add_months(today, 12 * horizon))
    if not plans.has_goal(plan):
        st.markdown("#### Set a goal")
        st.caption("What you're investing for, how much you'll need, and by when. The plan then "
                   "shows whether you're on track and what it would take to get there.")
    with st.form("plan_form"):
        goal_type = st.pills("What's the goal?", plans.GOAL_TYPES,
                             default=plan.get("goal_type") or _GOAL_FROM_PROFILE.get(first_goal))
        goal_name = st.text_input("Name it (optional)", value=plan.get("goal_name") or "",
                                  placeholder="e.g. Retire at 60", max_chars=60)
        c1, c2 = st.columns(2)
        target = c1.number_input("Target amount ($)", min_value=0.0, step=1000.0, format="%.0f",
                                 value=float(plan.get("target_amount") or 0.0))
        when = c2.date_input("Target date", value=when_default,
                             min_value=min(when_default, plans.add_months(today, 1)),
                             max_value=date(today.year + 80, 12, 31))
        monthly = c1.number_input("Adding each month ($)", min_value=0.0, step=50.0, format="%.0f",
                                  value=float(plan.get("monthly_contribution") or 0.0))
        notes = st.text_area("Notes (optional)", value=plan.get("notes") or "",
                             placeholder="Anything worth remembering about this goal")
        with st.container(horizontal=True):
            save = st.form_submit_button("Save plan", type="primary")
            cancel = plans.has_goal(plan) and st.form_submit_button("Cancel")
    if save:
        if not goal_type or target <= 0:
            st.error("Pick a goal and enter a target amount above $0.")
            return
        save_plan_fields({"goal_type": goal_type, "goal_name": goal_name.strip() or None,
                          "target_amount": float(target), "target_date": when.isoformat(),
                          "monthly_contribution": float(monthly), "notes": notes.strip() or None})
        st.session_state["plan_editing"] = False
        st.rerun()
    if cancel:
        st.session_state["plan_editing"] = False
        st.rerun()


def fmt_money0(v):
    """Whole dollars ('$1,000,000'), for goals and projections."""
    if _hidden():
        return MASK
    if _blank(v):
        return "—"
    return f"-${abs(v):,.0f}" if v < 0 else f"${v:,.0f}"


def _md(text):
    """st.markdown for text with dollar amounts: a pair of '$' would
    otherwise be read as a math formula."""
    st.markdown(text.replace("$", r"\$"))


def _render_plan_status(plan, value, today):
    rp = _plan_return_pct()
    prog = plans.progress(plan, value or 0.0, today=today, return_pct=rp)
    label, tone = PLAN_STATUS[prog["status"]]
    title = plan.get("goal_name") or plan.get("goal_type") or "Your goal"
    target, when = prog["target"], _fmt_month(plan["target_date"])

    h1, h2 = st.columns([0.8, 0.2], vertical_alignment="center")
    h1.markdown(f"#### {title}")
    if CAN_MANAGE and h2.button("Edit goal", key="plan_edit", width="stretch"):
        st.session_state["plan_editing"] = True
        st.rerun()
    pct = prog["pct_of_target"] or 0.0
    st.html(
        "<div class='pt-goal'><div class='pt-goal-top'>"
        f"<span class='pt-chip {tone}'>{label}</span>"
        f"<span class='pt-goal-pct'>{mask_or(f'{pct:.1f}%')} of {fmt_money0(target)}</span></div>"
        f"<div class='pt-goal-track'><div class='pt-goal-fill' style='width:{min(100.0, pct):.1f}%'>"
        "</div></div>"
        f"<div class='pt-goal-sub'>{fmt_money0(prog['current'])} now · goal {fmt_money0(target)} by "
        f"{when} · {_time_left(prog['months'])} · "
        f"{fmt_money0(prog['monthly'])}/month planned · {_plan_author(plan)}</div></div>")

    projected, needed = fmt_money0(prog["projected"]), fmt_money0(prog["needed_monthly"])
    status = prog["status"]
    if status == "reached":
        _md("You've reached this goal. Edit it to set the next one.")
    elif status == "past_date":
        _md(f"The goal date has passed with {fmt_money0(target - prog['current'])} still to "
                    "go. Edit the goal to set a new date.")
    elif status == "on_track":
        _md(f"At **{rp:g}%** a year, adding {fmt_money0(prog['monthly'])} a month, you'd have "
                    f"about **{projected}** by {when}.")
    elif status == "within_reach":
        _md(f"At **{rp:g}%** a year you'd have about **{projected}** by {when} - short of "
                    f"the goal unless returns run higher. About **{needed}** a month would get you "
                    "there at this rate.")
    else:
        _md(f"At **{rp:g}%** a year you'd have about **{projected}** by {when}. Reaching "
                    f"{fmt_money0(target)} would take about **{needed}** a month.")

    if prog["months"] > 0:
        st.select_slider("Assumed yearly return", RETURN_CHOICES, key="plan_return",
                         format_func=lambda v: f"{v:g}%")
        if st.session_state["plan_return"] != _read_prefs().get("plan_return_pct"):
            _p = _read_prefs()
            _p["plan_return_pct"] = st.session_state["plan_return"]
            _write_prefs(_p)
        df = pd.DataFrame(plans.projection_series(
            prog["current"], prog["monthly"], prog["months"], today=today, return_pct=rp))
        df["date"] = pd.to_datetime(df["date"])
        tips = [alt.Tooltip("date:T", title="Date", format="%b %Y")]
        if not _hidden():
            tips += [alt.Tooltip("mid:Q", title=f"At {rp:g}%", format="$,.0f"),
                     alt.Tooltip("low:Q", title=f"At {rp - plans.SPREAD_PCT:g}%", format="$,.0f"),
                     alt.Tooltip("high:Q", title=f"At {rp + plans.SPREAD_PCT:g}%", format="$,.0f")]
        palette = SERIES_DARK if st.context.theme.type == "dark" else SERIES_LIGHT
        st.altair_chart(charts.projection(df, target=target, color=palette[0], mask=_hidden(),
                                          tooltip=tips), width="stretch")
        st.caption(f"The line assumes {rp:g}% a year; the shaded range is "
                   f"{rp - plans.SPREAD_PCT:g}-{rp + plans.SPREAD_PCT:g}%. The dashed line is the "
                   "goal. Before inflation, fees and taxes - an illustration of the plan, not a "
                   "prediction.")
    if plan.get("notes"):
        st.caption(f"Notes: {plan['notes']}")


def _render_contributions(plan, today):
    st.markdown("#### Contributions")
    conn = connect(DB)
    try:
        this_month = plans.month_total(conn, USER_ID, today.year, today.month)
        recent = plans.list_contributions(conn, USER_ID, limit=10)
    finally:
        conn.close()
    planned = float((plan or {}).get("monthly_contribution") or 0.0)
    _md(f"This month: **{fmt_money0(this_month)}**"
                + (f" of {fmt_money0(planned)} planned" if planned else ""))
    if CAN_MANAGE:
        with st.expander("Log money added or taken out"):
            with st.form("contribution_form", clear_on_submit=True):
                c1, c2, c3 = st.columns([1, 1, 1])
                kind = c1.segmented_control("Type", ["Added", "Took out"], default="Added")
                amount = c2.number_input("Amount ($)", min_value=0.0, step=50.0, format="%.2f")
                on = c3.date_input("Date", value=today, max_value=today)
                note = st.text_input("Note (optional)", max_chars=100)
                if st.form_submit_button("Save", type="primary"):
                    if amount <= 0:
                        st.error("Enter an amount above $0.")
                    else:
                        c = connect(DB)
                        try:
                            plans.add_contribution(c, USER_ID, on.isoformat(),
                                                   -amount if kind == "Took out" else amount, note)
                        finally:
                            c.close()
                        st.rerun()
            st.caption("Logged by hand - importing a statement doesn't add these.")
            if recent:
                by_id = {r["id"]: r for r in recent}
                c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
                drop = c1.selectbox(
                    "Remove an entry", list(by_id), index=None, placeholder="Pick one to remove",
                    format_func=lambda i: f"{_fmt_date(by_id[i]['date'])}  {_signed_money(by_id[i]['amount'])}"
                                          + (f"  {by_id[i]['note']}" if by_id[i]["note"] else ""))
                if c2.button("Remove", disabled=drop is None, width="stretch"):
                    c = connect(DB)
                    try:
                        plans.delete_contribution(c, USER_ID, drop)
                    finally:
                        c.close()
                    st.rerun()
    if recent:
        st.html("<div class='pt-legend'>" + "".join(
            "<div class='pt-legend-row'>"
            f"<span class='pt-legend-val' style='text-align:left'>{_fmt_date(r['date'])}</span>"
            f"<span class='pt-legend-label'>{html.escape(r['note'] or '')}</span>"
            f"<span class='pt-legend-pct'>{_tone(r['amount'], _signed_money(r['amount']))}</span>"
            "</div>" for r in recent) + "</div>")


def _render_money_in(value, growth):
    st.markdown("#### Money in vs growth")
    money_in = value - growth
    st.html("<div class='pt-stats'>"
            f"<div class='pt-stat'><div class='pt-stat-label'>Money in</div>"
            f"<div class='pt-stat-value'>{fmt_money(money_in)}</div></div>"
            f"<div class='pt-stat'><div class='pt-stat-label'>Growth</div>"
            f"<div class='pt-stat-value'>{_tone(growth, _signed_money(growth))}</div></div>"
            f"<div class='pt-stat'><div class='pt-stat-label'>Value</div>"
            f"<div class='pt-stat-value'>{fmt_money(value)}</div></div></div>")
    conn = connect(DB)
    try:
        hist = plans.money_in_history(conn, USER_ID)
    finally:
        conn.close()
    if len(hist) >= 2:
        df = pd.DataFrame(hist)
        df["date"] = pd.to_datetime(df["date"])
        palette = SERIES_DARK if st.context.theme.type == "dark" else SERIES_LIGHT
        st.altair_chart(charts.money_in_chart(df, money_color=SERIES_OTHER, value_color=palette[0],
                                              mask=_hidden()), width="stretch")
    st.caption("Money in is what you paid for your holdings plus cash; growth is the rest. "
               + ("The chart uses each statement's own figures. " if len(hist) >= 2 else
                  "Import more statements over time and this becomes a chart. ")
               + "Dividends and gains you've sold count as money in, since they're in the "
                 "account as cash or cost.")


def _render_target_mix(alloc_rows):
    st.markdown("#### Target mix")
    targets = load_alloc_targets()
    actual = {r["label"]: r["pct"] or 0.0 for r in alloc_rows}
    labels = sorted(set(actual) | set(targets), key=lambda lbl: -(actual.get(lbl) or 0.0))
    if (load_plan() or {}).get("targets_cleared"):
        st.info("Targets are now set by what holdings actually hold - stocks, bonds, cash - "
                "instead of by fund type. The old target mix used ETF / CEF or Mutual Funds, "
                "which can't be translated, so it was cleared. Set it again below.")
    if not targets:
        st.caption("No targets yet. Set a target % for stocks, bonds and cash to see how far "
                   "the portfolio is from its plan.")
    else:
        rows = ""
        for lbl in labels:
            a, t = actual.get(lbl, 0.0), targets.get(lbl)
            diff = "" if t is None else f"{a - t:+.1f} pts"
            rows += ("<div class='pt-legend-row'>"
                     f"<span class='pt-legend-label'>{html.escape(lbl)}</span>"
                     f"<span class='pt-legend-pct'>{mask_or(f'{a:.1f}%')}</span>"
                     f"<span class='pt-legend-val'>target {'—' if t is None else f'{t:g}%'}</span>"
                     f"<span class='pt-legend-val'>{mask_or(diff) if diff else ''}</span></div>"
                     "<div class='pt-mix-track'>"
                     f"<div class='pt-mix-fill' style='width:{min(100.0, a):.1f}%'></div>"
                     + (f"<div class='pt-mix-target' style='left:{min(100.0, t):.1f}%'></div>"
                        if t is not None else "")
                     + "</div>")
        st.html(f"<div class='pt-legend'>{rows}</div>")
        st.caption("The bar is where the portfolio is now; the mark is the target.")
    if IS_ADVISOR:
        conn = connect(DB)
        try:
            models = advising.list_models(conn, LOGIN_ID)
        finally:
            conn.close()
        if any(m["target_alloc"] for m in models):
            by_id = {m["id"]: m for m in models if m["target_alloc"]}
            c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
            pick = c1.selectbox("Apply a model portfolio", list(by_id), index=None,
                                placeholder="Pick one of your models",
                                format_func=lambda i: f"{by_id[i]['name']} - "
                                                      f"{advising.mix_text(by_id[i]['target_alloc'])}")
            if c2.button("Apply", disabled=pick is None, width="stretch", key="apply_model"):
                save_alloc_targets(by_id[pick]["target_alloc"])
                st.rerun()
    if CAN_MANAGE:
        with st.expander("Edit target mix"):
            with st.form("target_mix_form", border=False):
                cols = st.columns(len(asset_classes.CLASSES))
                new = {lbl: cols[i].number_input(
                           f"{lbl} %", min_value=0.0, max_value=100.0, step=5.0, format="%.0f",
                           value=float(targets.get(lbl, 0.0)), key=f"plan_target_{lbl}")
                       for i, lbl in enumerate(asset_classes.CLASSES)}
                if st.form_submit_button("Save target mix", type="primary"):
                    total = sum(new.values())
                    if total and abs(total - 100) > 0.5:
                        st.error(f"The targets add up to {total:g}% - make them total 100%.")
                    else:
                        save_alloc_targets(new)
                        st.rerun()


def _render_plan(value, growth, alloc_rows):
    """The Plan page. `value` / `growth` / `alloc_rows` are None for an
    account with no holdings yet - the goal and contributions still work."""
    today = datetime.now().date()
    plan = load_plan()
    if not CAN_MANAGE and not plans.has_goal(plan):
        st.info(f"Your advisor, {_advisor_display_name()}, sets your goal - it shows up here "
                "once they have.")
    elif CAN_MANAGE and (st.session_state.get("plan_editing") or not plans.has_goal(plan)):
        _render_plan_form(plan, today)
    else:
        _render_plan_status(plan, value, today)
    st.divider()
    _render_contributions(plan, today)
    if value is not None:
        st.divider()
        _render_money_in(value, growth)
    if alloc_rows:
        st.divider()
        _render_target_mix(alloc_rows)


# ---- Get started page ------------------------------------------------------ #
# readiness state -> (icon markdown, words); the words always go with the icon
_READY_ICON = {
    learn.GOOD: (":green[:material/check_circle:]", "Good"),
    learn.CAUTION: (":orange[:material/error:]", "Look at this"),
    learn.STOP: (":red[:material/cancel:]", "Start here"),
    learn.UNKNOWN: (":gray[:material/help:]", "Not answered"),
}
GET_STARTED_STEPS = (
    ("profile", "About you"),
    ("ready", "Are you ready to invest?"),
    ("goal", "Set a goal"),
    ("basics", "Learn the basics"),
    ("mix", "An example mix"),
    ("practice", "Try it with practice money"),
    ("account", "Open an account and bring it in"),
)
# questions a step can hand to the AI Assistant
COACH_PROMPTS = {
    "ready": "Looking at my situation, what should I take care of before I start investing, "
             "and in what order?",
    "basics": "Explain stocks, bonds, index funds and ETFs to me like I'm brand new to investing.",
    "mix": "Explain why a mix of US stocks, international stocks and bonds might fit my time "
           "horizon and comfort with risk. Use examples, not recommendations.",
    "practice": "What should I expect emotionally when my investments drop 20% or more, and "
                "what do long-term investors usually do?",
    "account": "What's the difference between a regular brokerage account, a Roth IRA and a "
               "401(k), and which questions should I ask to pick one?",
}
PRACTICE_MIXES = ("Example mix", "All stocks", "Mostly bonds")


def _usd0(v):
    """Whole dollars, never masked - for hypothetical practice numbers."""
    return f"-${abs(v):,.0f}" if v < 0 else f"${v:,.0f}"


def _ask_coach(step):
    st.session_state["coach_prompt"] = COACH_PROMPTS[step]
    st.session_state["page"] = "AI Assistant"


def _coach_button(step):
    st.button(f":material/forum: Ask {GUIDE} about this", key=f"coach_{step}",
              type="tertiary", on_click=_ask_coach, args=(step,))


def _done_steps():
    return set(_read_prefs().get("get_started_done") or [])


def _mark_done(step, done=True):
    p = _read_prefs()
    steps = set(p.get("get_started_done") or [])
    (steps.add if done else steps.discard)(step)
    p["get_started_done"] = sorted(steps)
    _write_prefs(p)


def _done_button(step, done):
    if done:
        st.button("Mark as not done", key=f"undone_{step}", type="tertiary",
                  on_click=_mark_done, args=(step, False))
    else:
        st.button("Mark as done", key=f"done_{step}", on_click=_mark_done, args=(step,))


def _practice_prices(conn):
    """{ticker: [(date, price)]} for the practice funds, dividends included
    (adjusted close, falling back to close)."""
    out = {}
    for t in learn.PRACTICE_TICKERS.values():
        out[t] = [(r["date"], float(r["adj_close"] if r["adj_close"] is not None else r["close"]))
                  for r in conn.execute(
                      "SELECT date, adj_close, close FROM daily_bars WHERE ticker = ? "
                      "AND COALESCE(adj_close, close) IS NOT NULL ORDER BY date", (t,))]
    return out


def _render_mix_bar(weights):
    palette = SERIES_DARK if st.context.theme.type == "dark" else SERIES_LIGHT
    segs = legend = ""
    for i, b in enumerate(learn.BLOCKS):
        pct = weights[b["key"]]
        if pct > 0:
            segs += (f"<div class='pt-alloc-seg' style='flex:{pct} 0 0;background:{palette[i]}' "
                     f"title='{b['label']} {pct}%'></div>")
        legend += ("<div class='pt-legend-row'>"
                   f"<span class='pt-swatch' style='background:{palette[i]}'></span>"
                   f"<span class='pt-legend-label'><b>{b['label']}</b> - {b['about']}</span>"
                   f"<span class='pt-legend-pct'>{pct}%</span></div>"
                   f"<div class='pt-goal-sub' style='margin:0 0 .5rem 1.1rem'>Examples: "
                   f"{', '.join(b['examples'])}</div>")
    st.html(f"<div class='pt-alloc-bar'>{segs}</div><div class='pt-legend'>{legend}</div>")


def _step_profile(advisor, profile, missing):
    if missing:
        st.caption("A few questions so the rest of this page fits you. Every answer is a tap, "
                   "and you can change them any time.")
        _render_profile_form(advisor, profile)
        return
    known = [f"{advisor.PROFILE_FIELDS[f]}: **{profile[f]}**" for f in
             ("goal", "time_horizon_years", "risk_tolerance", "experience", "age_range")
             if profile.get(f) not in (None, "")]
    st.markdown("  \n".join(known))
    if st.toggle("Change my answers", key="gs_edit_profile"):
        _render_profile_form(advisor, profile)


def _step_ready(items):
    st.markdown(f"**{learn.readiness_summary(items)}**")
    for it in items:
        icon, words = _READY_ICON[it["state"]]
        st.markdown(f"{icon} **{it['label']}** ({words}) - {it['text']}")
    st.caption("These are common first steps many people take before investing, not rules - "
               "your situation may differ.")
    _coach_button("ready")


def _step_goal(plan, value):
    if plans.has_goal(plan):
        gp = _goal_progress(plan, value)
        label, _tone_cls = PLAN_STATUS[gp["status"]]
        _md(f"**{plan.get('goal_name') or plan['goal_type']}**: {fmt_money0(gp['target'])} by "
            f"{_fmt_month(plan['target_date'])} - {label.lower()}.")
        st.button("Open plan", key="gs_open_plan", on_click=_go, args=("Plan",))
    elif not CAN_MANAGE:
        st.caption("Your advisor sets your goal with you - it shows up on the Plan page once "
                   "they have.")
    else:
        st.caption("Pick what you're investing for and roughly how much you'll need. Even a "
                   "rough goal makes it easier to know how much to put in each month.")
        st.button("Set a goal", key="gs_set_goal", type="primary", on_click=_go, args=("Plan",))


def _step_basics(monthly, years, done):
    yrs = max(1, int(round(years)))
    put_in = monthly * 12 * yrs
    grown = learn.grow_monthly(monthly, yrs, 6)
    later = learn.grow_monthly(monthly, yrs - 10, 6) if yrs > 10 else None
    fee = learn.fee_cost(monthly, yrs, 6, 0.05, 1.0)
    m, fmt = _usd0(monthly), lambda v: _usd0(v).replace("$", r"\$")
    st.markdown(
        "**Stocks, bonds and funds.** A stock is a small piece of one company. A bond is a loan "
        "to a government or company that pays you interest. A fund holds many stocks or bonds at "
        "once; an **ETF** is a fund you buy and sell like a stock, and an **index fund** simply "
        "holds a whole market (like every US company) instead of trying to pick winners.")
    st.markdown(
        "**Why spread it out.** Any one company can stumble or fail. A total-market fund holds "
        "thousands of companies, so no single one can sink you - that's diversification, and "
        "index funds give it to you in one purchase.")
    st.markdown(
        f"**Time does the heavy lifting.** Putting in {fmt(monthly)} a month for {yrs} years is "
        f"{fmt(put_in)} of your own money. At 6% a year it could grow to about **{fmt(grown)}**."
        + (f" Starting 10 years later, the same {fmt(monthly)} a month gets to about "
           f"{fmt(later)} - most of the growth comes from the early years." if later else ""))
    st.markdown(
        f"**Fees add up.** Funds charge a yearly fee called the expense ratio. On {fmt(monthly)} "
        f"a month for {yrs} years, a fund charging 1% instead of 0.05% would leave you about "
        f"**{fmt(fee)} less**. Broad index funds are usually among the cheapest.")
    st.markdown(
        "**Ups and downs are normal.** The US stock market fell about a third in a month in "
        "early 2020 and by more than half in 2007-09, then recovered over the following years. "
        "Staying invested through drops has historically mattered more than timing them. Money "
        "you'll need in the next few years usually belongs in savings instead.")
    st.markdown(
        "**Account types.** A regular brokerage account has no limits but you pay tax on gains "
        "and dividends. A **Roth IRA** is for retirement: you put in money you've already paid "
        "tax on, and it can grow and come out tax-free later. A **401(k)** through work often "
        "comes with an employer match. IRAs and 401(k)s have yearly limits - check IRS.gov for "
        "this year's.")
    st.caption(f"Examples use {m} a month and {yrs} years from your plan or profile, and 6% a "
               "year - an illustration, not a prediction.")
    _coach_button("basics")
    _done_button("basics", done)


def _step_mix(mix, profile, plan, done):
    if mix is None:
        st.caption("Answer the time horizon question in step 1 to see an example mix.")
        return
    if mix["short_horizon"]:
        st.info("You'll need this money within about 3 years. Money needed that soon usually "
                "goes in a high-yield savings account, CDs or Treasury bills rather than stocks. "
                "This is how a cautious mix would look if you do invest some of it.")
    st.markdown(f"An example for someone with your answers: **{mix['stocks_pct']}% stocks, "
                f"{mix['weights']['bonds']}% bonds.**")
    _render_mix_bar(mix["weights"])
    st.markdown("Why this split:  \n" + "  \n".join(f"- {r}" for r in mix["reasons"]))
    extra = []
    year = learn.target_date_year(plan, profile.get("age_range"), datetime.now().date())
    prefs_set = set((profile.get("preferences") or "").split("; "))
    if year and ((plan or {}).get("goal_type") == "Retirement"
                 or "Hands-off / set and forget" in prefs_set or "Retirement" in (profile.get("goal") or "")):
        extra.append(f"**One-fund option:** a target-date fund (look for a name with **{year}** "
                     "in it, like \"Target Retirement " + str(year) + "\") holds a mix like this "
                     "in a single fund and gradually shifts toward bonds as that year gets closer.")
    if "Sustainable (ESG) investing" in prefs_set:
        extra.append("**Sustainable investing:** ESG versions of broad index funds exist - for "
                     "example ESGV for US stocks.")
    if "Dividend income" in prefs_set:
        extra.append("**Dividend income:** dividend-focused funds, for example SCHD or VYM, lean "
                     "toward companies that pay regular dividends.")
    for e in extra:
        st.markdown(e)
    st.caption("An example for learning, based on common rules of thumb - not a recommendation "
               "to buy these funds. The tickers are examples of well-known, low-cost index "
               "funds; many similar funds exist.")

    def _watch_examples():
        c = connect(DB)
        try:
            for t in learn.PRACTICE_TICKERS.values():
                watchlist.add(c, USER_ID, t)
        finally:
            c.close()
        st.session_state["refresh_msg"] = (
            "toast", "Added " + ", ".join(learn.PRACTICE_TICKERS.values()) + " to your watchlist.")

    with st.container(horizontal=True):
        st.button("Watch these example funds", key="gs_watch", on_click=_watch_examples,
                  help="Adds " + ", ".join(learn.PRACTICE_TICKERS.values())
                       + " to your Watchlist so you can follow their prices.")
        _coach_button("mix")
    _done_button("mix", done)


def _step_practice(mix, plan, profile, done):
    today = datetime.now().date()
    conn = connect(DB)
    try:
        prices = _practice_prices(conn)
    finally:
        conn.close()
    have = [p for p in prices.values() if p]
    first = max(p[0][0] for p in have) if len(have) == len(prices) else None
    last = min(p[-1][0] for p in have) if have else None
    years_avail = ((today - date.fromisoformat(first)).days / 365.25) if first else 0
    stale = not last or (today - date.fromisoformat(last)).days > 7
    if years_avail < 5 or stale:
        st.caption("The practice portfolio uses real past prices for "
                   + ", ".join(learn.PRACTICE_TICKERS.values()) + ". Load them first (takes a "
                   "few seconds).")
        if st.button("Load price history", key="gs_load_prices", type="primary"):
            try:
                import sync_history
            except ImportError:
                st.error("Price history needs yfinance - run: pip install yfinance")
                return
            with st.spinner("Loading 10 years of prices..."):
                sync_history.sync(DB, list(learn.PRACTICE_TICKERS.values()), period="10y",
                                  with_intraday=False, with_info=False, delay=0.0)
            st.rerun()
        if not first:
            return

    default_monthly = float((plan or {}).get("monthly_contribution") or 200.0)
    c1, c2 = st.columns(2)
    monthly = c1.number_input("Put in each month ($)", min_value=0.0, step=50.0, format="%.0f",
                              value=default_monthly, key="gs_monthly")
    initial = c2.number_input("Starting amount ($)", min_value=0.0, step=100.0, format="%.0f",
                              value=0.0, key="gs_initial")
    span_opts = [y for y in (1, 3, 5, 10) if y <= years_avail + 0.05] or [1]
    years = st.segmented_control("Starting", span_opts, default=span_opts[-1], key="gs_years",
                                 format_func=lambda y: f"{y} year{'s' if y != 1 else ''} ago") \
        or span_opts[-1]
    which = st.segmented_control("Mix", PRACTICE_MIXES, default=PRACTICE_MIXES[0],
                                 key="gs_mix") or PRACTICE_MIXES[0]
    stocks = {"Example mix": (mix or {}).get("stocks_pct", 60), "All stocks": 100,
              "Mostly bonds": 20}[which]
    us = round(stocks * learn.US_SHARE_OF_STOCKS)
    t = learn.PRACTICE_TICKERS
    weights = {t["us"]: us, t["intl"]: stocks - us, t["bonds"]: 100 - stocks}
    start = plans.add_months(today, -12 * years).isoformat()
    rows = learn.simulate(prices, weights, monthly=monthly, initial=initial, start=start)
    if len(rows) < 2 or not rows[-1]["money_in"]:
        st.caption("Enter an amount to see how it would have gone.")
        return
    end = rows[-1]
    growth = end["value"] - end["money_in"]
    dd = learn.max_drawdown(rows)
    tone = "pt-up" if growth > 0 else "pt-down" if growth < 0 else ""
    st.html("<div class='pt-stats'>"
            f"<div class='pt-stat'><div class='pt-stat-label'>Put in</div>"
            f"<div class='pt-stat-value'>{_usd0(end['money_in'])}</div></div>"
            f"<div class='pt-stat'><div class='pt-stat-label'>Worth today</div>"
            f"<div class='pt-stat-value'>{_usd0(end['value'])}</div>"
            f"<div class='pt-stat-sub {tone}'>{'+' if growth >= 0 else ''}{_usd0(growth)}</div></div>"
            f"<div class='pt-stat'><div class='pt-stat-label'>Worst drop</div>"
            f"<div class='pt-stat-value'>{dd:.0f}%</div></div></div>")
    df = pd.DataFrame(rows[::5] + ([rows[-1]] if len(rows) % 5 != 1 else []))
    df["date"] = pd.to_datetime(df["date"])
    palette = SERIES_DARK if st.context.theme.type == "dark" else SERIES_LIGHT
    st.altair_chart(charts.money_in_chart(df, money_color=SERIES_OTHER, value_color=palette[0]),
                    width="stretch")
    mix_words = f"{stocks}% stocks / {100 - stocks}% bonds ({', '.join(f'{k} {v}%' for k, v in weights.items() if v)})"
    reaction = profile.get("drawdown_reaction")
    _md(f"Starting {_fmt_month(rows[0]['date'])} with {_usd0(initial)} and {_usd0(monthly)} a "
        f"month in {mix_words}. At its worst, the mix was **{abs(dd):.0f}% below its high**"
        + (f" - you said you'd *{reaction.lower()}* after a 20% drop. Selling during a drop "
           "locks in the loss; the chart shows what staying in would have looked like."
           if reaction in ("Sell everything", "Sell some") and dd <= -15 else "."))
    st.caption("Real past prices with dividends reinvested; no fees or taxes; nothing is "
               "rebalanced. Past results don't predict future ones - this is practice, not "
               "a forecast.")
    _coach_button("practice")
    _done_button("practice", done)


def _step_account(monthly, has_holdings):
    if not CAN_IMPORT and not has_holdings:
        st.markdown(f"Your advisor, {_advisor_display_name()}, helps you open the account and "
                    "brings your statements in - your portfolio shows up on the Dashboard once "
                    "they have.")
        _coach_button("account")
        return
    if has_holdings:
        st.markdown("You've brought in your first statement - the **Dashboard** shows your real "
                    "portfolio and the **Plan** tracks it against your goal.")
        st.button("Open Dashboard", key="gs_open_dash", on_click=_go, args=("Dashboard",))
        return
    st.markdown(
        "1. **Pick a brokerage.** Large low-cost ones include Schwab, Fidelity and Vanguard. "
        "Look for no account minimum and no trading commissions.\n"
        "2. **Pick the account type** - see *Account types* in step 4.\n"
        "3. **Link your bank** and move money in.\n"
        "4. **Buy your funds.** Many brokerages let you buy fractional shares, so you can start "
        "with a small amount.\n"
        + (f"5. **Set up automatic investing** of {_usd0(monthly)} a month - the amount in your "
           "plan - so it happens without you having to remember.\n".replace("$", r"\$")
           if monthly else
           "5. **Set up automatic monthly investing** so it happens without you having to "
           "remember.\n")
        + "6. **Bring it in here:** use **Holdings** in the sidebar - paste your positions, "
        "upload a CSV or type them in; any brokerage works. Your Plan then tracks the real thing.")
    with st.container(horizontal=True):
        st.button("Import my first statement", key="gs_import", type="primary", on_click=_go,
                  args=("Dashboard",))
        _coach_button("account")


def _render_get_started(has_holdings, value):
    import advisor

    today = datetime.now().date()
    conn = connect(DB)
    try:
        profile = advisor.get_profile(conn, USER_ID)
    finally:
        conn.close()
    plan = load_plan()
    missing = advisor.missing_fields(profile)
    items = learn.readiness(profile)
    manual = _done_steps()
    horizon = (plans.months_until(plan["target_date"], today) / 12
               if plans.has_goal(plan) and plans.months_until(plan["target_date"], today) > 0 else None)
    mix = learn.starter_mix(profile, horizon)
    monthly = float((plan or {}).get("monthly_contribution") or 0.0)
    years = horizon or float(profile.get("time_horizon_years") or 20)

    done = {
        "profile": not missing,
        "ready": all(i["state"] != learn.UNKNOWN for i in items),
        "goal": plans.has_goal(plan),
        "basics": "basics" in manual,
        "mix": "mix" in manual,
        "practice": "practice" in manual,
        "account": has_holdings,
    }
    n_done = sum(done.values())
    st.caption("Your route, one waypoint at a time - built from your answers. It explains how "
               f"investing works and shows examples; it doesn't tell you what to buy. Stuck? "
               f"Each waypoint has an **Ask {GUIDE}** button.")
    st.progress(n_done / len(GET_STARTED_STEPS),
                text=f"{n_done} of {len(GET_STARTED_STEPS)} waypoints reached")
    current = next((k for k, _ in GET_STARTED_STEPS if not done[k]), None)
    for i, (key, title) in enumerate(GET_STARTED_STEPS, start=1):
        icon = ":green[:material/check_circle:]" if done[key] else ":material/radio_button_unchecked:"
        with st.expander(f"{icon} Waypoint {i}: {title}", expanded=(key == current)):
            if key == "profile":
                _step_profile(advisor, profile, missing)
            elif key == "ready":
                _step_ready(items)
            elif key == "goal":
                _step_goal(plan, value)
            elif key == "basics":
                _step_basics(monthly or 200.0, years, done["basics"])
            elif key == "mix":
                _step_mix(mix, profile, plan, done["mix"])
            elif key == "practice":
                _step_practice(mix, plan, profile, done["practice"])
            else:
                _step_account(monthly, has_holdings)


def _render_assistant(contexts, cash_by_account):
    import advisor

    if st.session_state.pop("profile_toast", False):
        st.toast("Profile updated from the conversation.")
    api_key = _anthropic_key()
    if not api_key:
        st.info(f"{GUIDE} needs an `ANTHROPIC_API_KEY` - add it to `.env` locally, or to "
                "Settings → Secrets on Streamlit Cloud.")
        return

    conn = connect(DB)
    try:
        profile = advisor.get_profile(conn, USER_ID)
        memory = advisor.get_memory(conn, USER_ID)
    finally:
        conn.close()

    missing = advisor.missing_fields(profile)
    display = st.session_state.setdefault("chat_display", [])
    history = st.session_state.setdefault("chat_api", [])
    n_required = len(advisor.REQUIRED_PROFILE_FIELDS)
    with st.expander(f"Your investing profile ({n_required - len(missing)}/{n_required} key "
                     "questions answered)", expanded=bool(missing) and not display):
        _render_profile_form(advisor, profile)
        st.caption(f"{GUIDE} also fills this in from what you tell it in the chat, and "
                   "keeps short notes of its own so the next conversation picks up where this "
                   "one left off.")

    st.caption(f"Educational information only - not financial advice. {GUIDE} is not a "
               "licensed financial advisor; do your own research before making any investment "
               "decision.")

    _render_plan_export(api_key, profile, memory, contexts, cash_by_account, display)
    # new messages are written into this box too, so they land above the input
    chat_box = st.container()
    with chat_box:
        if not display:
            with st.chat_message("assistant", avatar=SAGE_AVATAR):
                st.markdown(f"Hi, I'm **{GUIDE}**, your guide in {APP_NAME}. Ask me anything "
                            "about investing or your portfolio - what a fund is, whether your mix "
                            "fits your goal, what to look at next. I'll explain in plain "
                            "language, and I won't tell you what to buy.")
        for msg in display:
            with st.chat_message(msg["role"], avatar=_avatar(msg["role"])):
                st.markdown(msg["text"])

    prompt = None
    if not display:
        cols = st.columns(len(QUICK_STARTS))
        for col, (label, text) in zip(cols, QUICK_STARTS.items()):
            if col.button(label, width="stretch", key=f"quick_{label}"):
                prompt = text

    n_sent = sum(1 for m in display if m["role"] == "user")
    at_limit = n_sent >= CHAT_MESSAGE_LIMIT
    # Inside a container the input sits inline under the chat instead of pinned to
    # the bottom of the screen. Pinned, Streamlit also keeps the page stuck to the
    # bottom, and on phones scrolling up (which resizes the browser's address bar)
    # snapped it straight back down.
    with st.container():
        typed = st.chat_input(f"Ask {GUIDE} about investing or your portfolio...",
                              disabled=at_limit)
    # a question handed over from a Get started step
    prompt = typed or prompt or st.session_state.pop("coach_prompt", None)

    if prompt and not at_limit:
        import anthropic

        display.append({"role": "user", "text": prompt})
        history.append({"role": "user", "content": prompt})
        with chat_box, st.chat_message("user"):
            st.markdown(prompt)

        system = advisor.system_prompt(profile, advisor.portfolio_summary(contexts, cash_by_account, CLASS_SPLITS),
                                       memory)
        updated = []

        def on_update(fields):
            c = connect(DB)
            try:
                advisor.save_profile(c, USER_ID, fields)
            finally:
                c.close()
            updated.append(fields)

        def on_memory(text):
            c = connect(DB)
            try:
                advisor.save_memory(c, USER_ID, text)
            finally:
                c.close()

        with chat_box, st.chat_message("assistant", avatar=SAGE_AVATAR):
            try:
                reply = st.write_stream(advisor.stream_reply(
                    anthropic.Anthropic(api_key=api_key), history, system, on_update,
                    on_memory))
            except anthropic.AuthenticationError:
                reply = "The ANTHROPIC_API_KEY was rejected - check that it's correct."
                st.error(reply)
            except anthropic.RateLimitError:
                reply = f"{GUIDE} is busy right now - wait a minute and try again."
                st.error(reply)
            except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
                reply = f"Couldn't reach {GUIDE}: {exc}"
                st.error(reply)
        display.append({"role": "assistant", "text": reply if isinstance(reply, str) else "".join(reply)})
        if updated:
            # rerun so the profile form shows the new values; the toast is
            # carried across the rerun, since one fired right before it is lost
            st.session_state["profile_toast"] = True
            st.rerun()

    if at_limit:
        st.info(f"This conversation hit the {CHAT_MESSAGE_LIMIT}-message limit. Start a new one "
                "to keep going.")
    if display:
        def _new_conversation():
            st.session_state["chat_display"] = []
            st.session_state["chat_api"] = []
        st.button("New conversation", on_click=_new_conversation)
    st.caption(f"Your holdings are shared with {GUIDE} as percentages only - no dollar "
               "amounts, share counts, or account names.")


MASK = "•••"


def _hidden() -> bool:
    return bool(st.session_state.get("hide_amounts", False))


def mask_or(s):
    """MASK when 'hide amounts' is on, else `s` unchanged."""
    return MASK if _hidden() else s


def _blank(v):
    return v is None or (isinstance(v, float) and pd.isna(v))


# --------------------------------------------------------------------------- #
def fmt_money(v):
    if _hidden():
        return MASK
    if _blank(v):
        return "—"
    return f"-${abs(v):,.2f}" if v < 0 else f"${v:,.2f}"


def fmt_pct(v):
    if _hidden():
        return MASK
    return "—" if _blank(v) else f"{v:+.2f}%"


def color_sign(v):
    if _hidden() or v is None or pd.isna(v) or v == 0:
        return ""
    return f"color: {GREEN}; font-weight: 600" if v > 0 else f"color: {RED}; font-weight: 600"


def fmt_price(v):
    return MASK if _hidden() else ("—" if _blank(v) else f"${v:,.2f}")


def fmt_qty(v):
    return "—" if _blank(v) else f"{v:,.4f}".rstrip("0").rstrip(".")


def fmt_num(v):
    return MASK if _hidden() else ("—" if _blank(v) else f"{v:,.2f}")


def fmt_int(v):
    return MASK if _hidden() else ("—" if _blank(v) else f"{v:,.0f}")


FORMATTERS = {"money": fmt_money, "pct": fmt_pct, "price": fmt_price,
              "qty": fmt_qty, "num": fmt_num, "int": fmt_int}

# axis / tooltip number format string per metric-format name
AXIS_FORMAT = {"money": "$,.2s", "price": "$,.2f", "pct": ".2f", "int": "d", "num": ",.2f"}
TOOLTIP_FORMAT = {"money": "$,.2f", "price": "$,.2f", "pct": ".2f", "int": "d", "num": ",.2f"}


def _stat_tiles(ctx, keys, ncols=4):
    """A compact label/value grid for a list of metrics.py keys — the
    Robinhood-style "stats" block under a ticker's chart. Skips keys with no
    registered metric; renders '—' for a None value like the Holdings table."""
    keys = [k for k in keys if k in M.BY_KEY]
    if not keys:
        return
    cols = st.columns(ncols)
    for i, k in enumerate(keys):
        m = M.BY_KEY[k]
        v = M.value(k, ctx)
        text = FORMATTERS[m.fmt](v) if m.fmt in FORMATTERS else ("—" if _blank(v) else str(v))
        with cols[i % ncols]:
            st.caption(m.label)
            if m.color_sign and not _hidden() and not _blank(v) and v != 0:
                st.markdown(f"<span style='font-weight:600;color:{GREEN if v > 0 else RED}'>"
                            f"{text}</span>", unsafe_allow_html=True)
            else:
                st.markdown(f"**{text}**")


# Categorical palette (dataviz reference palette, fixed slot order), light and
# dark steps. Asset types keep a fixed slot so a color always means the same
# thing; anything else takes the next free slot.
SERIES_LIGHT = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948")
SERIES_DARK = ("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767")
SERIES_OTHER = "#8a8a86"
ASSET_SLOT = {"Equity": 0, "ETF / CEF": 1, "Cash": 2, "Fixed Income": 3, "Mutual Funds": 4,
              "Option": 6}
# asset classes keep the colors of their nearest broker type
CLASS_SLOT = {"Stocks": 0, "Bonds": 3, "Cash": 2, "Other": 6}


def _slot_map(labels, fixed=None):
    """{label: palette slot}. Labels in `fixed` keep their slot; the rest take
    the unused slots in name order - so a color follows its entity, not its
    rank. Past eight, labels get the neutral 'other' gray (slot None)."""
    fixed = fixed or {}
    out = {lbl: fixed[lbl] for lbl in labels if lbl in fixed}
    free = [i for i in range(len(SERIES_LIGHT)) if i not in out.values()]
    for lbl in sorted(lbl for lbl in labels if lbl not in out):
        out[lbl] = free.pop(0) if free else None
    return out


def _alloc_bar(rows, title, slots):
    """Part-to-whole as one stacked bar plus a legend of label / % / value.
    HTML rather than a chart library so it lays out cleanly at phone width;
    every segment is named in the legend, so identity never rests on color."""
    import html as _h
    colors = SERIES_DARK if st.context.theme.type == "dark" else SERIES_LIGHT

    def color(label):
        i = slots.get(label)
        return colors[i] if i is not None else SERIES_OTHER

    segs = "".join(
        f"<div class='pt-alloc-seg' style='flex:{r['value']} 0 0;background:{color(r['label'])}' "
        f"title='{_h.escape(r['label'], quote=True)}'></div>"
        for r in rows if (r["value"] or 0) > 0)
    legend = ""
    for r in rows:
        pct = MASK if _hidden() or r["pct"] is None else f"{r['pct']:.1f}%"
        legend += ("<div class='pt-legend-row'>"
                   f"<span class='pt-swatch' style='background:{color(r['label'])}'></span>"
                   f"<span class='pt-legend-label'>{_h.escape(r['label'])}</span>"
                   f"<span class='pt-legend-pct'>{pct}</span>"
                   f"<span class='pt-legend-val'>{fmt_money(r['value'])}</span></div>")
    return (f"<div class='pt-alloc-title'>{_h.escape(title)}</div>"
            f"<div class='pt-alloc-bar'>{segs}</div><div class='pt-legend'>{legend}</div>")


def _account_mix(by_account, positions, cash_by_account, slots, group="by_asset_class"):
    """'By account': each account's share of the portfolio, with a thin bar
    of its own asset mix underneath - one view instead of a by-account bar
    plus a separate asset-mix chart per account. Mix colors match the asset
    type legend beside it; each segment names itself on hover."""
    import html as _h
    colors = SERIES_DARK if st.context.theme.type == "dark" else SERIES_LIGHT
    out = "<div class='pt-alloc-title'>By account</div>"
    for r in by_account:
        acct = r["label"]
        mix = allocate([p for p in positions if p["account"] == acct],
                       {acct: cash_by_account.get(acct, 0.0)}, CLASS_SPLITS)[group]
        segs = ""
        for m in mix:
            if (m["value"] or 0) <= 0:
                continue
            i = slots.get(m["label"])
            tip = m["label"] if _hidden() or m["pct"] is None else f"{m['label']} {m['pct']:.1f}%"
            segs += (f"<div class='pt-alloc-seg' style='flex:{m['value']} 0 0;"
                     f"background:{colors[i] if i is not None else SERIES_OTHER}' "
                     f"title='{_h.escape(tip, quote=True)}'></div>")
        pct = MASK if _hidden() or r["pct"] is None else f"{r['pct']:.1f}%"
        out += ("<div class='pt-acct'><div class='pt-legend-row'>"
                f"<span class='pt-legend-label'>{_h.escape(acct)}</span>"
                f"<span class='pt-legend-pct'>{pct}</span>"
                f"<span class='pt-legend-val'>{fmt_money(r['value'])}</span></div>"
                f"<div class='pt-alloc-bar pt-mini'>{segs}</div></div>")
    return out


def _render_classification(positions):
    """How each holding is classed (Stocks / Bonds / Cash / Other) and where
    that came from; whoever manages the account can set a holding by hand."""
    by_sym = {p["symbol"]: p for p in positions if p.get("symbol")}
    if not by_sym:
        return
    rows = []
    for s in sorted(by_sym):
        split, source = asset_classes.split_for(s, by_sym[s].get("asset_type"), sec_info.get(s),
                                                CLASS_OVERRIDES)
        rows.append({"Symbol": s, "Holds": asset_classes.describe(split),
                     "From": asset_classes.SOURCE_LABELS[source],
                     "Set to": CLASS_OVERRIDES.get(s, "Automatic")})
    n_guess = sum(r["From"] == asset_classes.SOURCE_LABELS["broker"] for r in rows)
    with st.expander("How holdings are classified"
                     + (f" · {n_guess} from broker type only" if n_guess else "")):
        st.caption("Funds are split by what they hold, from Yahoo - a balanced fund counts part "
                   "stocks, part bonds. Without Yahoo data a holding goes by its broker type "
                   "(Equity is stocks, Fixed Income is bonds); the rest fills in by itself."
                   + (" Choose a holding below to decide its class yourself." if CAN_MANAGE
                      else ""))
        df = pd.DataFrame(rows)
        st.dataframe(df if CAN_MANAGE else df.drop(columns=["Set to"]), hide_index=True,
                     width="stretch")
        if not CAN_MANAGE:
            return
        with st.form("class_override_form", border=False):
            c1, c2, c3 = st.columns([2, 2, 1], vertical_alignment="bottom")
            sym = c1.selectbox("Holding", sorted(by_sym), key="class_pick_symbol")
            cls = c2.selectbox("Set to", ["Automatic", *asset_classes.CLASSES],
                               key="class_pick_class",
                               help="Automatic uses Yahoo, else the broker type.")
            if c3.form_submit_button("Save", width="stretch"):
                new = dict(CLASS_OVERRIDES)
                if cls in asset_classes.CLASSES:
                    new[sym] = cls
                else:
                    new.pop(sym, None)
                p = _read_prefs()
                p[asset_classes.OVERRIDES_PREF] = new  # kept for symbols not held right now
                _write_prefs(p)
                st.rerun()


def _read_prefs():
    """This account's saved settings (prefs.py). Read from the database once
    per browser session, then served from session state - the page reads a
    setting many times per run."""
    cached = st.session_state.get("_prefs")
    if cached is None or cached[0] != USER_ID:
        conn = connect(DB)
        try:
            cached = (USER_ID, prefs.load(conn, USER_ID, PREFS_PATH))
        finally:
            conn.close()
        st.session_state["_prefs"] = cached
    return dict(cached[1])


def _write_prefs(d):
    conn = connect(DB)
    try:
        prefs.save(conn, USER_ID, d)
    finally:
        conn.close()
    st.session_state["_prefs"] = (USER_ID, dict(d))


def load_columns():
    saved = _read_prefs().get("columns")
    keys = [k for k in (saved or M.DEFAULT_KEYS) if k in M.BY_KEY and M.BY_KEY[k].available]
    return keys or list(M.DEFAULT_KEYS)


def save_columns(keys):
    p = _read_prefs()
    p["columns"] = list(keys)
    _write_prefs(p)


def load_rules():
    saved = _read_prefs().get("rules") or {}
    return [{**r, "abs_gt": float(saved.get(r["key"], r["abs_gt"]))} for r in alerts.DEFAULT_RULES]


def save_rules(rules):
    p = _read_prefs()
    p["rules"] = {r["key"]: r["abs_gt"] for r in rules}
    _write_prefs(p)


def load_perf_series():
    s = _read_prefs().get("perf_series")
    return s if s in perf.SERIES_LABEL else perf.SERIES[0][0]


DEFAULT_DRIFT_THRESHOLD = 5.0  # percentage points off target before flagging


def load_plan():
    """This account's plan (plans.py), or None. Cached for the session like
    the settings; saving through save_plan_fields() refreshes it."""
    cached = st.session_state.get("_plan")
    if cached is None or cached[0] != USER_ID:
        conn = connect(DB)
        try:
            cached = (USER_ID, plans.get_plan(conn, USER_ID))
        finally:
            conn.close()
        st.session_state["_plan"] = cached
    return cached[1]


def save_plan_fields(fields: dict):
    """Save into this account's plan, recording who saved it (an advisor
    editing a client's plan is recorded as the advisor)."""
    conn = connect(DB)
    try:
        plan = plans.save_plan(conn, USER_ID, fields, set_by=LOGIN_ID)
    finally:
        conn.close()
    st.session_state["_plan"] = (USER_ID, plan)
    return plan


def load_alloc_targets():
    """{asset-type label: target %}, from the plan's target mix. Only labels
    with a nonzero target are included — an unset label has no target and is
    never flagged, rather than implicitly meaning "target 0%". Targets saved
    before plans existed (in the settings) are used until the plan has some."""
    plan = load_plan()
    saved = (plan or {}).get("target_alloc")
    if not saved:  # the pre-plans settings key, in the old broker-type groups
        saved, _cleared = asset_classes.convert_targets(_read_prefs().get("alloc_targets"))
    return {k: float(v) for k, v in (saved or {}).items() if v}


def save_alloc_targets(targets: dict):
    save_plan_fields({"target_alloc": {k: v for k, v in targets.items() if v}})


def load_drift_threshold():
    v = _read_prefs().get("drift_threshold")
    return float(v) if v else DEFAULT_DRIFT_THRESHOLD


def save_drift_threshold(v):
    p = _read_prefs()
    p["drift_threshold"] = float(v)
    _write_prefs(p)


def save_hide(on):
    p = _read_prefs()
    p["hide_amounts"] = bool(on)
    _write_prefs(p)


def save_perf_series(col):
    p = _read_prefs()
    p["perf_series"] = col
    _write_prefs(p)


def load():
    """Return (snapshot_date, positions, cash_by_account, quotes)."""
    conn = connect(DB)
    try:
        snap = latest_snapshot(conn, USER_ID)
        if not snap:
            return None, [], {}, {}
        rows = conn.execute(
            "SELECT * FROM positions WHERE snapshot_date = ? AND user_id = ? ORDER BY account, symbol",
            (snap, USER_ID)
        ).fetchall()
        cash_by_account = {
            r["account"]: r["cash_value"] or 0.0
            for r in conn.execute(
                "SELECT account, cash_value FROM account_totals WHERE snapshot_date = ? AND user_id = ?",
                (snap, USER_ID))
        }
        quotes = {
            r["ticker"]: dict(r)
            for r in conn.execute(
                "SELECT ph.* FROM price_history ph JOIN ("
                "  SELECT ticker, MAX(fetched_at) AS m FROM price_history WHERE ok = 1 GROUP BY ticker"
                ") latest ON ph.ticker = latest.ticker AND ph.fetched_at = latest.m WHERE ph.ok = 1")
        }
    finally:
        conn.close()
    # Nicknames replace the broker's account names from here on (display
    # only); the broker's name stays available as "broker_account".
    positions = [dict(r) for r in rows]
    for p in positions:
        p["broker_account"] = p["account"]
        p["account"] = accounts.display(p["account"], ACCOUNT_LABELS)
    cash_by_account = {accounts.display(a, ACCOUNT_LABELS): v for a, v in cash_by_account.items()}
    return snap, positions, cash_by_account, quotes


AUTO_REFRESH_AFTER = timedelta(minutes=15)


# ---- header -------------------------------------------------------------- #
def _sync_history(tickers=None, *, quick=False):
    """Pull Yahoo history, then rerun to show it. `quick` is the automatic
    backfill for holdings that have none yet: daily bars and fundamentals
    only (seconds, not minutes) - the full sync and the nightly job add the
    intraday bars. It stays silent when it can't run."""
    try:
        import sync_history
    except ImportError:
        if quick:
            return
        st.session_state["refresh_msg"] = ("error", "yfinance not installed — run: pip install yfinance")
        st.rerun()
    prog = st.progress(0.0, text="Loading price history for your holdings…" if quick
                       else "Contacting Yahoo…")
    try:
        summary = sync_history.sync(
            DB, tickers, period=sync_history.DEFAULT_PERIOD, with_intraday=not quick,
            on_progress=lambda i, n, tk, nr, ok, err: prog.progress(
                i / n, text=f"{tk} ({i}/{n}) — {nr:,} rows"),
        )
    except Exception:  # noqa: BLE001 - the automatic backfill must never break the page
        if not quick:
            raise
        prog.empty()
        return
    prog.empty()
    if quick:
        if summary["ok"]:
            st.session_state["refresh_msg"] = (
                "toast", f"Loaded price history for {summary['ok']} holding(s).")
            st.rerun()
        return
    msg = (f"Synced {summary['bars_written']:,} daily + "
           f"{summary['intraday_written']:,} intraday bars for "
           f"{summary['ok']}/{summary['tickers']} tickers.")
    if summary["failed"]:
        st.session_state["refresh_msg"] = ("warning", msg + " No data for: " + ", ".join(summary["failed"]))
    else:
        st.session_state["refresh_msg"] = ("success", msg)
    st.rerun()


def _local_time(ts):
    """A stored UTC timestamp as an aware datetime in the viewer's timezone
    (UTC when the browser didn't report one)."""
    at = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    off = st.context.timezone_offset
    return at.astimezone(timezone(-timedelta(minutes=off)) if off is not None else timezone.utc)


def _fmt_when(ts):
    """'4:18 PM' today, 'Sep 28, 4:18 PM' this year, with the year otherwise."""
    try:
        at = _local_time(ts)
    except (TypeError, ValueError):
        return str(ts)
    now = datetime.now(at.tzinfo)
    clock = at.strftime("%I:%M %p").lstrip("0") + ("" if st.context.timezone_offset is not None
                                                   else " UTC")
    if at.date() == now.date():
        return clock
    if at.year == now.year:
        return f"{at:%b} {at.day}, {clock}"
    return f"{at:%b} {at.day}, {at.year}, {clock}"


def _fmt_date(d):
    """'Jan 15, 2026' from '2026-01-15'."""
    try:
        d = datetime.strptime(str(d)[:10], "%Y-%m-%d")
    except ValueError:
        return str(d)
    return f"{d:%b} {d.day}, {d.year}"


def _after_import():
    """A new statement can bring new tickers: fetch their prices and history
    on the next run instead of waiting for the scheduled jobs."""
    st.session_state.pop("auto_backfilled", None)
    st.session_state["dialog_open"] = False  # saved: the dialog is closing
    for k in ("last_open_snapshot", "value_logged"):  # the portfolio changed: compare afresh
        st.session_state.pop(k, None)


def _manual_rows_init(current_positions, current_cash, current_source=None):
    """Start the hand-entry form from the latest snapshot (once per opening)."""
    if "me_ids" in st.session_state:
        return
    to_broker = {v: k for k, v in ACCOUNT_LABELS.items()}
    base = [{**p, "account": p.get("broker_account") or p.get("account")} for p in current_positions]
    cash = {to_broker.get(a, a): v for a, v in current_cash.items()}
    holdings, cash_rows = manual_entry.prefill(base, cash)
    weights, cash_pct = manual_entry.prefill_weights(base, cash)
    pct_by = {(w["Account"], w["Symbol"]): w["Percent"] for w in weights}
    holdings = holdings or [{"Account": manual_entry.DEFAULT_ACCOUNT, "Type": "ETF"}]
    cash_rows = cash_rows or [{"Account": holdings[0]["Account"], "Cash": None}]
    ss = st.session_state
    ss["me_next"] = 0
    ss["me_ids"], ss["me_cash_ids"] = [], []
    ss["me_mode"] = "Percentages" if current_source == manual_entry.PCT_SOURCE else "Shares"
    # Number fields keep their values here, not in their widget keys: Streamlit
    # drops a widget's value on a run where it isn't shown, and the Shares and
    # Percentages fields take turns being hidden.
    ss["me_vals"] = {"cash_pct": cash_pct if base else None, "total": manual_entry.DEFAULT_TOTAL}
    if current_source == manual_entry.PCT_SOURCE and base:
        # keep the pretend total it was made with
        ss["me_vals"]["total"] = round(sum(p.get("market_value") or 0.0 for p in base)
                               + sum(v or 0.0 for v in cash.values()), 2)
    for r in holdings:
        _manual_add_row({**r, "Percent": pct_by.get((r["Account"], r.get("Symbol")))})
    for r in cash_rows:
        _manual_add_cash(r)


def _manual_number(label, name, *, min_value=0.0, **kw):
    """A number field whose value lives in me_vals (see _manual_rows_init)."""
    vals = st.session_state["me_vals"]
    wkey = f"me_w_{name}"

    def keep():
        vals[name] = st.session_state.get(wkey)
        st.session_state.pop("me_review", None)
    st.session_state[wkey] = vals.get(name)
    return st.number_input(label, key=wkey, min_value=min_value, on_change=keep, **kw)


def _manual_new_id():
    st.session_state["me_next"] += 1
    return st.session_state["me_next"]


def _manual_add_row(r=None):
    r = r or {"Account": _manual_last_account(), "Type": "ETF"}
    i = _manual_new_id()
    st.session_state[f"me_acct_{i}"] = r.get("Account") or manual_entry.DEFAULT_ACCOUNT
    st.session_state[f"me_sym_{i}"] = r.get("Symbol") or ""
    st.session_state["me_vals"].update({f"qty_{i}": r.get("Shares"), f"cost_{i}": r.get("Total cost"),
                                        f"pct_{i}": r.get("Percent")})
    st.session_state[f"me_type_{i}"] = r.get("Type") or "ETF"
    st.session_state["me_ids"].append(i)
    st.session_state.pop("me_review", None)


def _manual_add_cash(r=None):
    r = r or {"Account": _manual_last_account()}
    i = _manual_new_id()
    st.session_state[f"me_cacct_{i}"] = r.get("Account") or manual_entry.DEFAULT_ACCOUNT
    st.session_state["me_vals"][f"cash_{i}"] = r.get("Cash")
    st.session_state["me_cash_ids"].append(i)
    st.session_state.pop("me_review", None)


def _manual_last_account():
    ids = st.session_state.get("me_ids") or []
    return (st.session_state.get(f"me_acct_{ids[-1]}") if ids else None) or \
        manual_entry.DEFAULT_ACCOUNT


def _manual_remove(kind, i):
    st.session_state[kind].remove(i)
    st.session_state.pop("me_review", None)


def _manual_form_rows():
    ss = st.session_state
    v = ss["me_vals"]
    holdings = [{"Account": ss.get(f"me_acct_{i}"), "Symbol": ss.get(f"me_sym_{i}"),
                 "Shares": v.get(f"qty_{i}"), "Total cost": v.get(f"cost_{i}"),
                 "Percent": v.get(f"pct_{i}"), "Type": ss.get(f"me_type_{i}")}
                for i in ss["me_ids"]]
    cash = [{"Account": ss.get(f"me_cacct_{i}"), "Cash": v.get(f"cash_{i}")}
            for i in ss["me_cash_ids"]]
    return holdings, cash


def _manual_from_paste():
    """Replace the form's rows with what paste_parse finds in the pasted text,
    then forget the text."""
    ss = st.session_state
    found = paste_parse.parse(ss.get("me_paste") or "")
    ss["me_paste"] = ""  # the pasted text isn't kept, even in this session
    if not found["holdings"]:
        ss["me_paste_msg"] = ("warning", "Couldn't find any holdings in that text. Try copying "
                              "just the positions table, or type lines like `VTI 10`.")
        return
    ss["me_paste_msg"] = _manual_fill(found)


def _manual_fill(found):
    """Replace the form's rows with `found` (paste_parse.parse() / screenshot_read
    shape). Returns the (kind, message) to show."""
    ss = st.session_state
    acct = _manual_last_account()
    ss["me_ids"], ss["me_cash_ids"] = [], []
    for h in found["holdings"]:
        _manual_add_row({"Account": acct, "Symbol": h["Symbol"], "Shares": h["Shares"],
                         "Total cost": h["Total cost"], "Percent": h["Percent"],
                         "Type": h.get("Type") or "Other"})
    _manual_add_cash({"Account": acct, "Cash": found["cash"] if found["mode"] == "Shares" else None})
    ss["me_mode"] = found["mode"]
    n = len(found["holdings"])
    return ("success", f"Found {n} holding{'s' if n != 1 else ''}"
                          + (f" and {fmt_money(found['cash'])} cash" if found["cash"] else "")
                          + " - check them below, then look up prices. Type is set to Other; "
                            "Yahoo works out what each one holds.")


def _render_screenshot_reader():
    """Read from screenshots: opt-in, the images go to Anthropic's AI (see
    screenshot_read.py). They're read from memory and never kept."""
    ss = st.session_state
    msg = ss.pop("me_shot_msg", None)
    with st.expander(":material/photo_camera: Read from screenshots (uses AI)",
                     expanded=bool(msg)):
        key = _anthropic_key()
        if not key:
            st.caption("Reading screenshots needs the AI, which isn't set up on this site.")
            return
        st.caption("For phone apps and sites where copying is hard. **Crop each screenshot to "
                   "just your holdings list first** - the whole image is sent to Anthropic's AI "
                   "to read it. Only symbols, share counts and cost are taken from what it "
                   "reads, and the images aren't saved.")
        shots = st.file_uploader(
            "Screenshots", type=sorted(screenshot_read.MEDIA_TYPES), accept_multiple_files=True,
            key=f"me_shots_{ss.get('me_shots_n', 0)}", label_visibility="collapsed")
        agreed = st.checkbox("Send these images to Anthropic's AI to read them",
                             key="me_shots_ok")
        if msg:
            getattr(st, msg[0])(msg[1])
        if st.button("Read screenshots", key="me_shots_btn", disabled=not (shots and agreed)):
            images, errors = screenshot_read.check_images([(f.name, f.getvalue()) for f in shots])
            if errors:
                st.error("  \n".join(errors))
                return
            with st.spinner("Reading your screenshots..."):
                found = screenshot_read.read(images, key)
            del images, shots  # nothing of the images is kept past this point
            ss["me_shots_n"] = ss.get("me_shots_n", 0) + 1   # empties the uploader
            ss["me_shots_ok"] = False
            if found["error"]:
                ss["me_shot_msg"] = ("error", found["error"])
            elif not found["holdings"]:
                ss["me_shot_msg"] = ("warning", "No holdings could be read from those "
                                     "screenshots. Try cropping closer to the list.")
            else:
                ss["me_shot_msg"] = _manual_fill(found)
            st.rerun(scope="fragment")


def _manual_clear():
    for k in [k for k in st.session_state if k.startswith("me_")]:
        del st.session_state[k]


def _manual_save(meta, rows, totals, txns, source):
    """Write a reviewed hand entry: the snapshot (portfolio.write_snapshot, the
    same save an import uses) and the day's inferred buys and sells."""
    conn = connect(DB)
    try:
        write_snapshot(conn, USER_ID, meta, rows, totals, source)
        conn.execute("DELETE FROM transactions WHERE trade_date = ? AND user_id = ?",
                     (meta["snapshot_date"], USER_ID))
        for tx in txns:
            tx["user_id"] = USER_ID
        if txns:
            conn.executemany(
                "INSERT INTO transactions (account, trade_date, action, symbol, "
                "description, quantity, price, amount, fees, realized_gain, "
                "source_file, user_id) VALUES "
                "(:account, :trade_date, :action, :symbol, :description, :quantity, "
                ":price, :amount, :fees, :realized_gain, :source_file, :user_id)", txns)
        conn.commit()
    except DBError:
        conn.rollback()
        raise
    finally:
        conn.close()


def _review_and_save(meta, rows, totals, source, *, pct_mode=False, key="save_holdings",
                     after=None):
    """"What we'll keep", the change summary and Save, for holdings about to be
    saved as a snapshot - hand entry, paste, screenshots and non-Schwab CSVs.
    `after` runs once saved (e.g. clearing the form)."""
    st.markdown("**What we'll keep**")
    st.dataframe(pd.DataFrame([{
        "Account": accounts.mask_number(r["account"]), "Symbol": r["symbol"],
        "Name": r["description"] or "",
        "Shares": round(r["quantity"], 4), "Value": fmt_money(r["market_value"]),
        **({} if pct_mode else {"Total cost": fmt_money(r["cost_basis"])
                                if r["cost_basis"] is not None else ""})}
        for r in rows]), hide_index=True, width="stretch")
    total = sum(r["market_value"] for r in rows) + sum(t["cash_value"] or 0 for t in totals.values())
    conn = connect(DB)
    try:
        base_date = conn.execute(
            "SELECT MAX(snapshot_date) d FROM positions WHERE snapshot_date < ? AND user_id = ?",
            (meta["snapshot_date"], USER_ID)).fetchone()["d"]
        base_rows = [dict(r) for r in conn.execute(
            "SELECT account, symbol, description, quantity, cost_basis, market_value "
            "FROM positions WHERE snapshot_date = ? AND user_id = ?",
            (base_date, USER_ID))] if base_date else []
    finally:
        conn.close()
    d = diff_positions(base_rows, rows)
    # a pretend portfolio has no real buys and sells to record
    txns = [] if pct_mode else synthesize_transactions(d, meta["snapshot_date"], source)
    _md(f"Total **{fmt_money(total)}**"
        + (" (pretend)" if pct_mode else " today")
        + f" · {len(d['new'])} new, {len(d['increased']) + len(d['decreased'])} changed, "
          f"{len(d['closed'])} removed since "
          f"{_fmt_date(base_date) if base_date else 'nothing yet'}.")
    st.caption(NOT_KEPT)
    if st.button("Save holdings", type="primary", key=key):
        try:
            _manual_save(meta, rows, totals, txns, source)
        except DBError as exc:
            st.error(f"Saving failed, nothing was changed: {exc}")
        else:
            st.session_state["import_flash"] = (f"Saved {len(rows)} holding(s) for "
                                  f"{_fmt_date(meta['snapshot_date'])}.")
            if after:
                after()
            _after_import()
            st.rerun()


@st.dialog("Add or update holdings", width="large", on_dismiss=_dialog_closed)
def _manual_dialog(current_positions, current_cash, current_source=None):
    """Type in holdings (no file needed); saved as today's snapshot, like an import.
    Shares mode records real holdings; Percentages mode records only each
    holding's share of a pretend total."""
    st.session_state["dialog_open"] = True  # live prices wait (see _live_status)
    _manual_rows_init(current_positions, current_cash, current_source)
    ss = st.session_state
    st.caption(":material/lock: " + TRUST_LINE)
    _empty = not any((ss.get(f"me_sym_{i}") or "").strip() for i in ss["me_ids"])
    with st.expander(":material/content_paste: Paste from your brokerage",
                     expanded=_empty or bool(ss.get("me_paste_msg"))):
        st.caption("On your brokerage's website, select your positions table, copy it, and "
                   "paste it here. The app reads it itself - no AI - and keeps only symbols, "
                   "share counts and cost. The pasted text isn't saved.")
        st.text_area("Pasted positions", key="me_paste", height=120,
                     label_visibility="collapsed",
                     placeholder="VTI   10\nBND   25\n...or paste a whole table")
        st.button("Fill in from pasted text", key="me_paste_btn", on_click=_manual_from_paste)
        _pm = ss.pop("me_paste_msg", None)
        if _pm:
            getattr(st, _pm[0])(_pm[1])
    _render_screenshot_reader()
    st.segmented_control("How to enter them", ["Shares", "Percentages"], key="me_mode",
                         required=True, on_change=lambda: ss.pop("me_review", None))
    pct_mode = ss.get("me_mode") == "Percentages"
    if pct_mode:
        st.caption("No real amounts: give each holding's share of the portfolio, and the app "
                   "works with a pretend total. Allocation, the stock / bond mix, risk and "
                   "projections all work; gains are tracked from today.")
    else:
        st.caption("For any brokerage, or no file at all. Add each holding - its value comes "
                   "from today's price. Saving records today's snapshot; to update later, "
                   "open this again and change what's different.")
    types = list(manual_entry.TYPES)
    for i in list(ss["me_ids"]):
        with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
            st.text_input("Account", key=f"me_acct_{i}", width=150)
            st.text_input("Symbol", key=f"me_sym_{i}", width=100, placeholder="VTI")
            if pct_mode:
                _manual_number("% of portfolio", f"pct_{i}", max_value=100.0, step=5.0,
                               format="%.1f", width=150)
            else:
                _manual_number("Shares", f"qty_{i}", step=1.0, format="%.4f", width=130)
                _manual_number("Total cost", f"cost_{i}", step=100.0, format="%.2f", width=140,
                               help="What you paid in total (optional) - for gain and loss.")
            st.selectbox("Type", types, key=f"me_type_{i}", width=130)
            st.button(":material/close:", key=f"me_del_{i}", type="tertiary",
                      on_click=_manual_remove, args=("me_ids", i), help="Remove this row")
    st.button(":material/add: Add another holding", key="me_add", type="tertiary",
              on_click=_manual_add_row)
    if pct_mode:
        with st.container(horizontal=True, gap="small"):
            _manual_number("Cash %", "cash_pct", max_value=100.0, step=5.0, format="%.1f",
                           width=150)
            _manual_number("Pretend total", "total", min_value=1.0, step=1000.0, format="%.0f",
                           width=180, help="Any amount - it only sets the scale of the numbers "
                                           "shown.")
    else:
        st.markdown("**Cash** (optional)")
        for i in list(ss["me_cash_ids"]):
            with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
                st.text_input("Account", key=f"me_cacct_{i}", width=150)
                _manual_number("Cash", f"cash_{i}", step=100.0, format="%.2f", width=160)
                st.button(":material/close:", key=f"me_cdel_{i}", type="tertiary",
                          on_click=_manual_remove, args=("me_cash_ids", i), help="Remove")
        st.button(":material/add: Add cash for another account", key="me_add_cash",
                  type="tertiary", on_click=_manual_add_cash)

    holdings, cash_rows = _manual_form_rows()
    if pct_mode:
        clean, cash_pct, errors = manual_entry.validate_weights(
            holdings, ss["me_vals"].get("cash_pct"), ss["me_vals"].get("total"))
    else:
        clean, cash, errors = manual_entry.validate(holdings, cash_rows)
    if st.button("Look up prices and review", type="primary", key="me_review_btn"):
        if errors:
            ss.pop("me_review", None)
            st.error("  \n".join(errors))
        else:
            known = {p["symbol"]: p.get("description") for p in current_positions}
            with st.spinner("Looking up prices..."):
                found = manual_entry.lookup(
                    [h["symbol"] for h in clean],
                    finnhub_quote=manual_entry.finnhub_price(resolve_key(None, ENV_PATH)),
                    yahoo_info=manual_entry.yahoo_price_and_name, known_names=known)
            ss["me_review"] = (manual_entry.build_weights(clean, cash_pct,
                                                          ss["me_vals"]["total"], found)
                               if pct_mode else manual_entry.build(clean, cash, found))
    review = ss.get("me_review")
    if not review:
        return
    meta, rows, totals, price_errors = review
    if price_errors:
        st.error("  \n".join(price_errors))
        return
    _review_and_save(meta, rows, totals,
                     manual_entry.PCT_SOURCE if pct_mode else manual_entry.SOURCE,
                     pct_mode=pct_mode, key="me_save", after=_manual_clear)


def _load_sample():
    c = connect(DB)
    try:
        sample_data.load(c, USER_ID)
    finally:
        c.close()
    st.session_state["import_flash"] = ("Loaded an example portfolio - explore freely. Clear it "
                                        "any time from the banner at the top.")
    _after_import()


def _clear_sample():
    c = connect(DB)
    try:
        sample_data.clear(c, USER_ID)
    finally:
        c.close()
    st.session_state["import_flash"] = "Example portfolio removed."
    _after_import()


CSV_FIELDS = ("symbol", "quantity", "cost", "avg_cost", "value", "percent", "account",
              "account_number", "description")


def _import_any_csv(src_path, source_name):
    """A positions CSV from any brokerage other than Schwab: find the table,
    check the columns (matched by name, a remembered layout, or the AI from
    column names and cell kinds only), then the usual review and save."""
    ss = st.session_state
    with open(src_path, "rb") as fh:
        rows = csv_import.read_rows(fh.read())
    header_i, problem = csv_import.find_header(rows)
    if problem == "transactions":
        st.warning("This looks like **transaction history** (buys and sells), not your current "
                   "holdings. Export your **Positions** or **Holdings** instead - or copy the "
                   "positions table from your brokerage's website and use **Paste or type "
                   "holdings**.")
        return
    if header_i is None:
        header_i = csv_import.guess_header(rows)
    if header_i is None:
        st.error("Couldn't find a table of holdings in this file. Try your brokerage's "
                 "Positions export, or paste the positions table instead.")
        return
    header = rows[header_i]
    sig = csv_import.signature(header)
    conn = connect(DB)
    try:
        known = csv_import.remembered(conn, header)
    finally:
        conn.close()
    mapping = known or csv_import.auto_mapping(header)
    if not csv_import.usable(mapping) and _anthropic_key():
        cache = ss.setdefault("csv_ai_maps", {})
        if sig not in cache:
            with st.spinner("Working out the columns..."):
                cache[sig] = csv_import.ai_mapping(header, csv_import.sample_shapes(rows, header_i),
                                                   _anthropic_key())
        mapping = {**mapping, **(cache[sig] or {})}

    names = [f"{c or '(blank)'}  ·  column {i + 1}" for i, c in enumerate(header)]
    with st.expander("Check the columns", expanded=not (known and csv_import.usable(mapping))):
        st.caption("Which column holds what. Only these are read; every other column is "
                   "ignored." + (" This layout was remembered from an earlier file." if known
                                 else ""))
        cols = st.columns(3)
        chosen = {}
        for n, field in enumerate(CSV_FIELDS):
            pick = cols[n % 3].selectbox(
                csv_import.LABELS.get(field, "Account number"), [None, *range(len(header))],
                index=(mapping[field] + 1) if field in mapping else 0,
                format_func=lambda i: "—" if i is None else names[i], key=f"csvmap_{sig[:10]}_{field}")
            if pick is not None:
                chosen[field] = pick
    if not csv_import.usable(chosen):
        st.info("Choose at least the **Symbol** column and **Shares** (or **Value**).")
        return
    found = csv_import.parse(rows, chosen, filename=source_name.replace("upload: ", ""))
    if not found["holdings"]:
        st.warning("No holdings were found with these columns - check the choices above.")
        return
    if found["mode"] == "Percentages":
        st.info("This file only has percentages, no share counts. Use **Paste or type holdings** "
                "in the sidebar and its Percentages mode instead.")
        return

    clean, cash, errors = manual_entry.validate(
        [{"Account": h["Account"], "Symbol": h["Symbol"], "Shares": h["Shares"],
          "Total cost": h["Total cost"], "Type": "Other"} for h in found["holdings"]],
        [{"Account": a, "Cash": v} for a, v in found["cash"].items()])
    if errors:
        st.error("  \n".join(errors))
        return
    _md(f"Found **{len(clean)} holding(s)**"
        + (f" and {fmt_money(sum(cash.values()))} cash" if cash else "")
        + f" from {_fmt_date(found['snapshot_date'])}.")
    # values from the file where it has them; today's price for the rest
    prices = {h["Symbol"]: {"price": round(h["Value"] / h["Shares"], 6), "name": h["Name"]}
              for h in found["holdings"] if h["Value"] and h["Shares"]}
    missing = [h["symbol"] for h in clean if h["symbol"] not in prices]
    if missing:
        key = f"csv_prices_{sig[:10]}"
        if key not in ss:
            with st.spinner("Looking up prices..."):
                ss[key] = manual_entry.lookup(
                    missing, finnhub_quote=manual_entry.finnhub_price(resolve_key(None, ENV_PATH)),
                    yahoo_info=manual_entry.yahoo_price_and_name)
        prices.update(ss[key])
    meta, prow, totals, price_errors = manual_entry.build(
        clean, cash, prices, today=date.fromisoformat(found["snapshot_date"]))
    if price_errors:
        st.error("  \n".join(price_errors))
        return
    meta["as_of_text"] = f"Imported from {os.path.basename(source_name.replace('upload: ', ''))}"

    def _remember_layout():
        c = connect(DB)
        try:
            csv_import.remember(c, header, chosen)  # column names only
        finally:
            c.close()
    _review_and_save(meta, prow, totals, source_name, key="csv_any_save", after=_remember_layout)


@st.dialog("Import a positions CSV", width="large", on_dismiss=_dialog_closed)
def _import_dialog():
    """Upload a new Schwab Positions export, preview what changed, confirm."""
    st.session_state["dialog_open"] = True  # live prices wait (see _live_status)
    st.caption(
        "Upload your brokerage's **Positions** (or Holdings) export - Schwab, Fidelity, "
        "Vanguard, E*TRADE or any other. You'll check it before anything is saved."
    )
    st.caption(":material/lock: " + TRUST_LINE)
    up = st.file_uploader("Positions export (.csv)", type=["csv"], key="csv_upload")
    # A path on "this machine" is only meaningful running locally - on the
    # hosted app it would be a path on the server, which users must not read.
    path_in = "" if pgcompat.is_postgres_dsn(DB) else st.text_input(
        "…or a path to a CSV on this machine",
        key="csv_path",
        placeholder="C:\\Users\\you\\Downloads\\All-Accounts-Positions-....csv",
    ).strip().strip('"')

    if up is not None:
        with temp_upload(up.name, up.getbuffer()) as src_path:  # deleted right after
            _import_preview(src_path, upload_label(up.name))
    elif path_in:
        _import_preview(path_in, os.path.abspath(path_in))


def _import_preview(src_path, source_name):
    """The import dialog's preview and confirm, for a file at `src_path`;
    `source_name` is what the database records as its source."""
    if src_path and not os.path.isfile(src_path):
        st.error(f"No file at: {src_path}")
    elif src_path:
        _parse_info: dict = {}
        try:
            # Schwab's own layout, strictly; any other file goes to csv_import below
            # (it replaces the old Schwab-shaped AI fallback for these uploads)
            _meta, new_rows, _ = parse_csv_smart(src_path, None, _parse_info)
        except SystemExit:
            # not a Schwab export: any other brokerage's layout (csv_import.py)
            _import_any_csv(src_path, source_name)
        else:
            if _parse_info.get("ai_assisted"):
                st.info("This file's headers didn't match the expected format, so Claude "
                        "helped interpret it — double check the numbers below before confirming.")
            file_date = _meta["snapshot_date"]
            _conn = connect(DB)
            try:
                # Diff against the snapshot *before* this file's date, so the change
                # set (and the transactions derived from it) is the same however many
                # times this file is imported.
                base_date = _conn.execute(
                    "SELECT MAX(snapshot_date) d FROM positions WHERE snapshot_date < ? AND user_id = ?",
                    (file_date, USER_ID),
                ).fetchone()["d"]
                base_rows = [dict(r) for r in _conn.execute(
                    "SELECT account, symbol, description, quantity, cost_basis, market_value "
                    "FROM positions WHERE snapshot_date = ? AND user_id = ?",
                    (base_date, USER_ID))] if base_date else []
                replacing = _conn.execute(
                    "SELECT 1 FROM positions WHERE snapshot_date = ? AND user_id = ? LIMIT 1",
                    (file_date, USER_ID)
                ).fetchone() is not None

                d = diff_positions(base_rows, new_rows)
                n_changed = len(d["increased"]) + len(d["decreased"])

                st.markdown(
                    f"Changes vs snapshot **{base_date or '— none (first import)'}**"
                )
                c = st.columns(5)
                c[0].metric("New", len(d["new"]))
                c[1].metric("Qty changed", n_changed)
                c[2].metric("Closed", len(d["closed"]))
                c[3].metric("Unchanged", len(d["unchanged"]))
                c[4].metric("File date", file_date)

                if replacing:
                    st.warning(
                        f"A snapshot for {file_date} already exists — importing replaces "
                        "its positions, account totals, and inferred transactions."
                    )

                def _tbl(entries, cols):
                    return pd.DataFrame([{k: e[k] for k in cols} for e in entries])

                if d["new"]:
                    st.markdown("**New positions**")
                    st.dataframe(_tbl(d["new"], ["account", "symbol", "description",
                                                "new_qty", "new_cost", "new_mv"]),
                                 hide_index=True, width="stretch")
                if n_changed:
                    st.markdown("**Quantity changes**")
                    st.dataframe(_tbl(d["increased"] + d["decreased"],
                                      ["account", "symbol", "old_qty", "new_qty", "dqty",
                                       "old_mv", "new_mv"]),
                                 hide_index=True, width="stretch")
                if d["closed"]:
                    st.markdown("**Closed positions**")
                    st.dataframe(_tbl(d["closed"], ["account", "symbol", "description",
                                                    "old_qty", "old_mv"]),
                                 hide_index=True, width="stretch")

                txns = synthesize_transactions(d, file_date, source_name)
                st.caption(
                    f"On confirm: positions + account totals for **{file_date}** are written, "
                    f"and **{len(txns)}** transaction row(s) inferred from the quantity deltas "
                    f"(BUY / SELL) are recorded."
                )

                st.caption("Kept: each holding's symbol, shares, cost and value, and account "
                           "names. " + NOT_KEPT)
                if st.button("Confirm import", type="primary", key="csv_confirm"):
                    try:
                        info = import_csv(_conn, src_path, USER_ID, None,
                                          source_name=source_name)
                        # Replace-by-date: this date's inferred transactions are
                        # rewritten from the new file's diff.
                        _conn.execute(
                            "DELETE FROM transactions WHERE trade_date = ? AND user_id = ?",
                            (info["snapshot_date"], USER_ID),
                        )
                        if txns:
                            for _t in txns:
                                _t["user_id"] = USER_ID
                            _conn.executemany(
                                "INSERT INTO transactions (account, trade_date, action, symbol, "
                                "description, quantity, price, amount, fees, realized_gain, "
                                "source_file, user_id) VALUES "
                                "(:account, :trade_date, :action, :symbol, :description, :quantity, "
                                ":price, :amount, :fees, :realized_gain, :source_file, :user_id)",
                                txns,
                            )
                        _conn.commit()
                    except DBError as exc:
                        _conn.rollback()
                        st.error(f"Import failed, nothing was saved: {exc}")
                    else:
                        st.session_state["import_flash"] = (
                            f"Imported your statement from {_fmt_date(info['snapshot_date'])} - "
                            f"{info['n_positions']} positions, {len(txns)} transaction(s) recorded."
                        )
                        _after_import()
                        st.rerun()
            finally:
                _conn.close()


def _toggle_hide():
    st.session_state["hide_amounts"] = not st.session_state.get("hide_amounts", False)
    save_hide(st.session_state["hide_amounts"])


@st.fragment(run_every=LIVE_EVERY_SEC)
def _live_status():
    """Keeps prices current without a Refresh button: every minute (only this
    line reruns) it fetches whatever quotes are due (live_prices.freshen -
    shared across everyone viewing, so each ticker is asked for at most once a
    minute), then redraws the page if any price changed. It waits while a
    dialog is open, so it never interrupts adding holdings."""
    ss = st.session_state
    try:
        c = connect(DB)
        try:
            live = live_prices.freshen(c, USER_ID, resolve_key(None, ENV_PATH))
        finally:
            c.close()
    except Exception:  # noqa: BLE001 - prices failing must never break the page
        live = {"updated": 0, "as_of": None, "live": False}
    if live["updated"] and not ss.get("dialog_open"):
        st.rerun()  # the whole page, with the new prices
    as_of = live["as_of"] or live_prices._parse(last_live)
    if live["live"] and as_of:
        age = (datetime.now(timezone.utc) - as_of).total_seconds()
        ago = ("just now" if age < 90 else f"{int(age // 60)} min ago" if age < 3600
               else _fmt_when(as_of))
        prices = f"<span class='pt-live'>●</span> Live · prices updated {ago}"
    elif as_of:
        prices = f"Market closed · prices as of {_fmt_when(as_of)}"
    else:
        prices = "No live prices yet"
    if n_live < len(positions):
        prices += f" ({n_live} of {len(positions)} priced)"
    _what = {manual_entry.SOURCE: "Entered by hand", manual_entry.PCT_SOURCE: "Percentages",
             SAMPLE_SOURCE: "Example portfolio"}.get(SNAPSHOT_SOURCE, "Statement")
    st.html(f"<div class='pt-status'>{prices} · {_what} from {_fmt_date(snapshot)}</div>")


def _page_header(title, *, data=True):
    """The page's title with the hide-amounts toggle and, on `data` pages
    (this account's portfolio), a status line that keeps prices current by
    itself (_live_status) - there's no Refresh button. Adding or updating
    holdings lives in the sidebar's Holdings section."""
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.title(title, anchor=False, width="stretch")
        st.button(":material/visibility_off:" if _hidden() else ":material/visibility:",
                  key="pt_hide", type="tertiary", on_click=_toggle_hide,
                  help="Show amounts" if _hidden() else "Hide amounts - mask every dollar and "
                                                         "percent with " + MASK)
    if data:
        _live_status()
        if SNAPSHOT_SOURCE == SAMPLE_SOURCE:
            with st.container(border=True, horizontal=True, vertical_alignment="center"):
                st.markdown(":material/science: **This is an example portfolio** - made-up "
                            "holdings to explore with. It's removed as soon as you import or "
                            "enter your own.", width="stretch")
                if CAN_IMPORT:
                    st.button("Remove example", key="pt_clear_sample", on_click=_clear_sample)
        elif SNAPSHOT_SOURCE == manual_entry.PCT_SOURCE:
            st.caption(":material/percent: A percentages portfolio - dollar amounts are pretend, "
                       "scaled to the total you chose. Change it with **Paste or type holdings** "
                       "in the sidebar.")

    # the result of a refresh / sync / import that happened just before the rerun
    _msg = st.session_state.pop("refresh_msg", None)
    if _msg:
        getattr(st, _msg[0])(_msg[1])
    _flash = st.session_state.pop("import_flash", None)
    if _flash:
        st.success(_flash)


def _signed_money(v):
    """'+$12.30' / '-$12.30' (fmt_money has no plus sign)."""
    if _hidden():
        return MASK
    if _blank(v):
        return "—"
    return ("+" if v > 0 else "") + fmt_money(v)


def _tone(v, html):
    """Wrap `html` in the gain/loss color for `v` (plain when hidden or flat)."""
    if _hidden() or _blank(v) or v == 0:
        return html
    return f"<span class='{'pt-up' if v > 0 else 'pt-down'}'>{html}</span>"


# --------------------------------------------------------------------------- #
if not pgcompat.is_postgres_dsn(DB) and not os.path.isfile(DB):
    st.error("No `portfolio.db` yet. Build it first:")
    st.code("python portfolio.py import \"path\\to\\All-Accounts-Positions-....csv\"", language="bash")
    st.stop()

if "hide_amounts" not in st.session_state:
    st.session_state["hide_amounts"] = bool(_read_prefs().get("hide_amounts", False))

snapshot, positions, cash_by_account, quotes = load()
_src_conn = connect(DB)
try:
    # an import, a hand entry, a percentages portfolio or the example portfolio
    SNAPSHOT_SOURCE = snapshot_source(_src_conn, USER_ID, snapshot)
finally:
    _src_conn.close()
# a Holdings button in the sidebar was pressed (_open_holdings_dialog)
_open = st.session_state.pop("open_dialog", None)
if _open == "manual" and CAN_IMPORT:
    _manual_dialog(positions, cash_by_account, SNAPSHOT_SOURCE)
elif _open == "import" and CAN_IMPORT:
    _import_dialog()
if not positions and PAGE in ("AI Assistant", "Plan", "Get started", "Advisor notes"):
    # Helping brand-new investors plan a first portfolio is a core use of the
    # assistant, and a goal can be set before there's anything invested, so
    # both work before any CSV has been imported.
    _page_header(_label(PAGE), data=False)
    if PAGE == "Plan":
        _render_plan(None, None, None)
    elif PAGE == "Get started":
        _render_get_started(False, None)
    elif PAGE == "Advisor notes":
        _render_notes()
    else:
        _render_assistant([], {})
    st.stop()
if PAGE == "Clients":
    # about the advisor's clients, not the viewed account's data
    _page_header(PAGE, data=False)
    _render_clients()
    st.stop()
if PAGE == "About":
    _page_header("About and disclosures", data=False)
    _render_disclosures()
    st.stop()
if not positions:
    # Blank-account onboarding: a brand-new admin-provisioned account has no
    # data at all yet. Skip straight to a CSV upload prompt instead of the
    # rest of the page (which would otherwise render a wall of "no data"
    # empty states across every section) - reuses the same import_csv()
    # entry point as the full "Import a new positions CSV" expander further
    # down, just without that flow's diff-preview step (there's nothing to
    # diff a first import against).
    _page_header("Welcome", data=False)
    if not CAN_IMPORT:
        st.info(f"Welcome, **{ACTIVE_NAME}**. Your advisor, {_advisor_display_name()}, "
                "brings your statements in - your portfolio shows up here once they have.")
        with st.container(horizontal=True):
            st.button("Get started", key="onboard_get_started", type="primary", on_click=_go,
                      args=("Get started",))
            st.button("Advisor notes", key="onboard_notes", on_click=_go, args=("Advisor notes",))
        st.stop()
    st.info(f"Welcome, **{ACTIVE_NAME}** — this account has no data yet. Paste your holdings, "
            "enter them by hand, or upload a Schwab Positions export CSV.")
    st.caption(":material/lock: " + TRUST_LINE)
    with st.container(horizontal=True, vertical_alignment="center"):
        st.markdown("New to investing, or don't have an account yet?", width="stretch")
        st.button("Start here", key="onboard_get_started", type="primary", on_click=_go,
                  args=("Get started",))
    with st.container(horizontal=True, vertical_alignment="center"):
        st.markdown("**Quickest:** copy your positions table from your brokerage's website "
                    "and paste it - any brokerage.", width="stretch")
        if st.button("Paste your holdings", key="onboard_paste", type="primary"):
            _manual_clear()
            _manual_dialog([], {})
    with st.container(horizontal=True, vertical_alignment="center"):
        st.markdown("No file, or rather not share your real numbers?", width="stretch")
        if st.button("Enter holdings by hand", key="onboard_manual",
                     help="Shares from any brokerage - or just percentages, no real amounts."):
            _manual_clear()
            _manual_dialog([], {})
        st.button("Try it with example data", key="onboard_sample", on_click=_load_sample,
                  help="A made-up portfolio to explore with. Removed when you add your own.")
    up = st.file_uploader("Positions export (.csv)", type=["csv"], key="onboard_csv_upload")
    if up is not None:
        _conn = connect(DB)
        info = None
        try:
            with temp_upload(up.name, up.getbuffer()) as src_path:  # deleted right after
                try:
                    info = import_csv(_conn, src_path, USER_ID, None,
                                      source_name=upload_label(up.name))
                except SystemExit:
                    # not a Schwab export: any other brokerage's layout (csv_import.py)
                    _import_any_csv(src_path, upload_label(up.name))
        except DBError as exc:
            st.error(f"Import failed: {exc}")
        finally:
            _conn.close()
        if info is not None:
            note = " (Claude helped interpret this file's headers — worth a spot check.)" \
                if info["ai_assisted"] else ""
            st.session_state["import_flash"] = (
                f"Imported your statement from {_fmt_date(info['snapshot_date'])} - "
                f"{info['n_positions']} positions.{note}")
            _after_import()
            st.rerun()
    st.stop()

cash = sum(cash_by_account.values())

# Deep Yahoo history (moving averages, volume, 52-wk, beta, P/E, sector).
bar_stats = perf.bar_stats(DB)
sec_info = perf.security_info(DB)
# What each holding holds - Stocks / Bonds / Cash / Other (asset_classes.py):
# the account's own choice, else Yahoo's fund breakdown, else the broker type.
CLASS_OVERRIDES = {s: c for s, c in (_read_prefs().get(asset_classes.OVERRIDES_PREF) or {}).items()
                   if c in asset_classes.CLASSES}
CLASS_SPLITS = asset_classes.splits_from(positions, sec_info, CLASS_OVERRIDES)

_wl_conn = connect(DB)
try:
    watch_tickers = watchlist.list_tickers(_wl_conn, USER_ID)
finally:
    _wl_conn.close()
_held_symbols = {p["symbol"] for p in positions}
watch_only = [t for t in watch_tickers if t not in _held_symbols]

# One metric context per position (same order as `positions`). Reused everywhere
# below: totals, alerts, the holdings table. port_value / acct_value are filled
# in once the totals are known.
contexts = [{"pos": p, "quote": quotes.get(p["symbol"], {}),
             "stats": bar_stats.get(p["symbol"], {}), "info": sec_info.get(p["symbol"], {}),
             "port_value": None, "acct_value": None} for p in positions]

tot_mv = tot_gl = tot_cost = 0.0
acct_value = {}
for p, ctx in zip(positions, contexts):
    mv, cost = M.eff_mv(ctx), p["cost_basis"]
    if mv is not None:
        tot_mv += mv
        acct_value[p["account"]] = acct_value.get(p["account"], 0.0) + mv
        if cost is not None:
            tot_gl += mv - cost
            tot_cost += cost

for acct, csh in cash_by_account.items():
    acct_value[acct] = acct_value.get(acct, 0.0) + (csh or 0.0)

portfolio_value = tot_mv + cash
tot_glp = (tot_gl / tot_cost * 100) if tot_cost else None
for p, ctx in zip(positions, contexts):
    ctx["port_value"] = portfolio_value
    ctx["acct_value"] = acct_value.get(p["account"])

n_live = sum(1 for p in positions if p["live_price"] is not None)
last_live = max((p["live_price_at"] for p in positions if p["live_price_at"]), default=None)

day_change_total = sum(
    v for v in (M.value("day_change_usd", ctx) for ctx in contexts) if v is not None
)

# ---- log this session's portfolio value (once, throttled) ---------- #
# last_open() must run BEFORE log_open() writes this session's own row, or
# "since you last opened" would just be comparing the portfolio to itself.
if "last_open_snapshot" not in st.session_state:
    st.session_state["last_open_snapshot"] = perf.last_open(DB, USER_ID)
if "value_logged" not in st.session_state:
    st.session_state["value_logged"] = perf.log_open(DB, USER_ID, {
        "snapshot_date": snapshot,
        "portfolio_value": portfolio_value,
        "holdings_value": tot_mv,
        "cash": cash,
        "cost_basis": tot_cost,
        "unrealized_gain": tot_gl,
        "unrealized_gain_pct": tot_glp,
        "day_change_usd": day_change_total,
        "n_positions": len(positions),
        "n_priced": n_live,
        "priced_at": last_live,
    })


# Holdings with no Yahoo history yet (a first import, or a new position):
# fetch it once per visit so the charts fill in without a manual sync. Runs
# before the header so the header's one-shot messages survive its rerun.
_covered, _missing = perf.holdings_coverage(DB, USER_ID)
# ...and holdings Yahoo was never asked to describe (what a fund holds -
# asset_classes.py). quote_type is None until asked, "" if Yahoo had nothing.
_undescribed = sorted({p["symbol"] for p in positions
                       if (sec_info.get(p["symbol"]) or {}).get("quote_type") is None}
                      - set(_missing))
if PAGE == "Dashboard" and (_missing or _undescribed)         and not st.session_state.get("auto_backfilled"):
    st.session_state["auto_backfilled"] = True
    _sync_history(sorted(set(_missing) | set(_undescribed)), quick=True)

_page_header(_label(PAGE))
hide_amounts = st.session_state["hide_amounts"]


def _pick_holdings():
    st.session_state["watchlist_pill"] = None


def _pick_watchlist():
    st.session_state["holdings_pill"] = None


if PAGE == "Dashboard":
    # ---- hero: value, today's move, since last visit, headline stats ----- #
    _day_base = portfolio_value - day_change_total
    _day_pct = (day_change_total / _day_base * 100) if _day_base else None
    if hide_amounts:
        _day_html = f"{MASK} today"
    elif n_live:
        _arrow = "▲" if day_change_total >= 0 else "▼"
        _day_html = _tone(day_change_total, f"{_arrow} {fmt_money(abs(day_change_total))}"
                          + (f" ({_day_pct:+.2f}%)" if _day_pct is not None else "") + " today")
    else:
        _day_html = ""

    _since_html = ""
    _last_open = st.session_state["last_open_snapshot"]
    # Only when it's the same statement - a new import's jump is new holdings
    # data, not the market moving.
    if (_last_open and _last_open.get("portfolio_value")
            and _last_open.get("snapshot_date") == snapshot):
        _prev_val = _last_open["portfolio_value"]
        _since_delta = portfolio_value - _prev_val
        _since_pct = (_since_delta / _prev_val * 100) if _prev_val else None
        _last_ts = pd.to_datetime(_last_open["logged_at"], utc=True).to_pydatetime()
        _secs = (datetime.now(timezone.utc) - _last_ts).total_seconds()
        if _secs < 3600:
            _ago = f"{max(1, int(_secs // 60))} min ago"
        elif _secs < 86400:
            _ago = f"{int(_secs // 3600)}h ago"
        else:
            _ago = f"{int(_secs // 86400)}d ago"
        _since_html = (f"Since your last visit ({_ago}): " + _signed_money(_since_delta)
                       + ("" if hide_amounts or _since_pct is None else f" ({_since_pct:+.2f}%)"))

    def _stat(label, value, sub=""):
        return (f"<div class='pt-stat'><div class='pt-stat-label'>{label}</div>"
                f"<div class='pt-stat-value'>{value}</div>"
                + (f"<div class='pt-stat-sub'>{sub}</div>" if sub else "") + "</div>")

    st.html(
        "<div class='pt-hero'>"
        "<div class='pt-hero-label'>Portfolio value</div>"
        f"<div class='pt-hero-value'>{fmt_money(portfolio_value)}</div>"
        + (f"<div class='pt-hero-delta'>{_day_html}</div>" if _day_html else "")
        + (f"<div class='pt-hero-sub'>{_since_html}</div>" if _since_html else "")
        + "</div><div class='pt-stats'>"
        + _stat("Total gain/loss", _tone(tot_gl, _signed_money(tot_gl)),
                _tone(tot_glp, fmt_pct(tot_glp)) if tot_glp is not None else "")
        + _stat("Holdings", fmt_money(tot_mv), f"{len(positions)} positions")
        + _stat("Cash", fmt_money(cash),
                "" if hide_amounts or not portfolio_value
                else f"{cash / portfolio_value * 100:.1f}% of total")
        + "</div>"
    )

    # ---- goal: one line from the plan, or a nudge to set one ----------- #
    _plan = load_plan()
    with st.container(border=True, horizontal=True, vertical_alignment="center"):
        if plans.has_goal(_plan):
            _gp = _goal_progress(_plan, portfolio_value)
            _glabel, _gtone = PLAN_STATUS[_gp["status"]]
            _gpct = mask_or(f"{_gp['pct_of_target'] or 0:.0f}%")
            st.html(f"<span class='pt-chip {_gtone}'>{_glabel}</span>&nbsp; "
                    f"<b>{html.escape(_plan.get('goal_name') or _plan['goal_type'] or 'Goal')}</b>"
                    f" · {_gpct} of "
                    f"{fmt_money0(_gp['target'])} by {_fmt_month(_plan['target_date'])}",
                    width="stretch")
            st.button("Open plan", key="dash_open_plan", type="tertiary", on_click=_go,
                      args=("Plan",))
        else:
            if CAN_MANAGE:
                st.markdown("Set a goal to see whether you're on track.", width="stretch")
                st.button("Set a goal", key="dash_set_goal", type="tertiary", on_click=_go,
                          args=("Plan",))
            else:
                st.markdown("Your advisor hasn't set a goal for you yet.", width="stretch")

    if ON_CLIENT or IS_MANAGED_CLIENT:
        _advisor_notes_card()

    # ---- alerts: one line, open for the list and the limits ------------ #
    _rules = load_rules()
    _fired = alerts.evaluate(contexts, _rules)
    _alert_label = (f":red[:material/notifications_active:] **{len(_fired)} "
                    f"alert{'s' if len(_fired) != 1 else ''}** · positions past your limits"
                    if _fired else ":material/notifications: No alerts")
    with st.expander(_alert_label):
        for _a in _fired:
            st.markdown(_a.masked_message if hide_amounts else _a.message)
        if not _fired:
            st.caption("No position is past its day-move or gain/loss limit.")
        if CAN_MANAGE:
            st.markdown("**Limits**")
            _new = []
            for _col, _r in zip(st.columns(len(alerts.DEFAULT_RULES)), alerts.DEFAULT_RULES):
                cur = next((x["abs_gt"] for x in _rules if x["key"] == _r["key"]), _r["abs_gt"])
                val = _col.number_input(f"{_r['label']} — flag beyond ±%", min_value=0.0,
                                        max_value=1000.0, value=float(cur), step=0.5,
                                        key=f"rule_{_r['key']}")
                _new.append({**_r, "abs_gt": val})
            if _new != _rules:
                save_rules(_new)
                st.rerun()
            st.caption("Checked against the latest prices every time the page loads.")
        else:
            st.caption("Limits set by your advisor: " + " · ".join(
                f"{r['label']} beyond ±{r['abs_gt']:g}%" for r in _rules) + ".")

    st.divider()

    # ---- performance over time ---------------------------------------- #
    p1, p2 = st.columns([0.65, 0.35])
    p1.subheader("Performance")
    series_col = p2.selectbox(
        "Series", [c for c, _, _ in perf.SERIES],
        index=[c for c, _, _ in perf.SERIES].index(load_perf_series()),
        format_func=lambda c: perf.SERIES_LABEL[c], key="perf_series_sel",
        label_visibility="collapsed",
    )
    if series_col != load_perf_series():
        save_perf_series(series_col)

    prng = st.segmented_control("Range", charts.RANGE_LABELS, default="1D",
                                key="perf_range", label_visibility="collapsed") or "1D"

    # history() picks the reconstruction's resolution to match `prng`, exactly like
    # ticker_series() does for a single ticker (finest Yahoo interval that covers
    # the window). With only daily bars so far (right after the automatic
    # backfill, before the nightly intraday sync) a short range can come back
    # empty - then show the shortest wider range that has data, and say so.
    _shown_rng = prng
    _hist = perf.history(DB, USER_ID, days=charts.RANGE_DAYS[prng], include_app_open=False)
    for _wider in charts.RANGE_LABELS[charts.RANGE_LABELS.index(prng) + 1:]:
        if len(_hist) >= 2:
            break
        _shown_rng = _wider
        _hist = perf.history(DB, USER_ID, days=charts.RANGE_DAYS[_wider], include_app_open=False)
    if _shown_rng != prng and len(_hist) >= 2:
        st.caption(f"No {prng} data yet - showing {_shown_rng}. Intraday history loads each evening.")
    if len(_hist) < 2:
        st.caption("Your performance chart fills in once price history for your holdings has "
                   "loaded - it updates on its own every trading day.")
    else:
        _fmtname = perf.SERIES_FMT[series_col]
        y_title = perf.SERIES_LABEL[series_col]
        hist_df = pd.DataFrame(_hist)
        hist_df["t"] = pd.to_datetime(hist_df["t"], utc=True, format="mixed")
        pwin = hist_df.dropna(subset=[series_col]).sort_values("t")

        if len(pwin) < 2:
            st.caption(f"No **{y_title}** recorded in this window yet.")
        else:
            # Intraday-resolution data (minutes/hours apart) gets the gaps-compressed
            # axis; daily-resolution data (~1 day apart, weekends aside) doesn't need it.
            _pcompress = pwin["t"].diff().median() < pd.Timedelta(hours=20)

            _pf, _pl, ppct = charts.window_change(pwin, "t", series_col)
            pmcol, _ = st.columns([0.4, 0.6])
            pmcol.metric(y_title, mask_or(FORMATTERS[_fmtname](_pl)),
                         delta=(None if hide_amounts or ppct is None else f"{ppct:+.2f}% over {_shown_rng}"))

            _ptips = [alt.Tooltip("t:T", title="When", format="%b %d, %Y  %H:%M")]
            if not hide_amounts:
                _ptips.append(alt.Tooltip(f"{series_col}:Q", title=y_title, format=TOOLTIP_FORMAT[_fmtname]))
            st.altair_chart(
                charts.line(
                    pwin, x="t", y=series_col, y_title=y_title, y_format=AXIS_FORMAT[_fmtname],
                    mask=hide_amounts, compress_gaps=bool(_pcompress),
                    line_color=(SERIES_DARK if st.context.theme.type == "dark" else SERIES_LIGHT)[0],
                    tooltip=_ptips),
                width="stretch",
            )
            st.caption(
                f"{len(pwin)} points · reconstructed from current holdings × each bar's close. "
                + (f"Sync {len(_missing)} more ticker(s) to extend the line: {', '.join(_missing)}."
                   if _missing else "")
            )

    st.divider()

    # ---- allocation ----------------------------------------------------- #
    alloc = allocate(positions, cash_by_account, CLASS_SPLITS)
    # What the bars group by: asset class (what's held - targets and drift use
    # this) or the broker's own asset type. One color per group across the page.
    _by_type = st.session_state.get("alloc_group") == "Broker type"
    _group = "by_asset_type" if _by_type else "by_asset_class"
    _asset_slots = _slot_map({r["label"] for r in alloc[_group]},
                             ASSET_SLOT if _by_type else CLASS_SLOT)

    al1, al2 = st.columns([0.75, 0.25])
    al1.subheader("Allocation")
    if CAN_MANAGE:
        with al2.popover("Targets", width="stretch"):
            st.caption("Set a target % of portfolio for stocks, bonds, cash or other - leave "
                       "at 0 for no target.")
            _saved_targets = load_alloc_targets()
            _new_targets = {}
            for _lbl in asset_classes.CLASSES:
                _new_targets[_lbl] = st.number_input(
                    _lbl, min_value=0.0, max_value=100.0, step=1.0,
                    value=float(_saved_targets.get(_lbl, 0.0)), key=f"target_{_lbl}")
            _new_thresh = st.number_input(
                "Flag drift beyond ± this many percentage points", min_value=0.5, max_value=50.0,
                step=0.5, value=load_drift_threshold(), key="drift_threshold_input")
            if {k: v for k, v in _new_targets.items() if v} != _saved_targets:
                save_alloc_targets(_new_targets)
            if _new_thresh != load_drift_threshold():
                save_drift_threshold(_new_thresh)
    st.segmented_control("Group by", ["Asset class", "Broker type"], default="Asset class",
                         key="alloc_group", label_visibility="collapsed",
                         help="Asset class is what holdings hold - a bond ETF counts as bonds. "
                              "Broker type is how the statement labels them.")

    _title = "By broker type" if _by_type else "By asset class"
    if len(alloc["by_account"]) > 1:
        a1, a2 = st.columns(2, gap="large")
        a1.html(_alloc_bar(alloc[_group], _title, _asset_slots))
        a2.html(_account_mix(alloc["by_account"], positions, cash_by_account, _asset_slots,
                             _group))
    else:
        st.html(_alloc_bar(alloc[_group], _title, _asset_slots))
    _render_classification(positions)

    if alloc["concentration"]:
        lines = "  \n".join(
            f"- **{r['symbol']}** ({r['account']}) — {fmt_money(r['value'])}, "
            + (MASK if hide_amounts else f"**{r['pct']:.1f}%**") + " of portfolio"
            for r in alloc["concentration"]
        )
        st.warning(f"Positions over {CONCENTRATION_PCT:.0f}% of portfolio value:  \n{lines}")
    else:
        st.caption(f"No single position exceeds {CONCENTRATION_PCT:.0f}% of portfolio value.")

    _targets = load_alloc_targets()
    if _targets:
        _thresh = load_drift_threshold()
        _pct_by_label = {r["label"]: r["pct"] for r in alloc["by_asset_class"]}
        _drift = []
        for _lbl, _target in _targets.items():
            _actual = _pct_by_label.get(_lbl, 0.0) or 0.0
            _delta = _actual - _target
            if abs(_delta) > _thresh:
                _drift.append((_lbl, _actual, _target, _delta))
        _drift.sort(key=lambda r: abs(r[3]), reverse=True)
        if _drift:
            lines = "  \n".join(
                f"- {'▲' if d > 0 else '▼'} **{lbl}** — "
                + (MASK if hide_amounts else f"{actual:.1f}% vs {target:.1f}% target ({d:+.1f} pts)")
                for lbl, actual, target, d in _drift
            )
            st.warning(f"Drifted beyond ±{_thresh:g} pts from target:  \n{lines}")
        else:
            st.caption(f"Every targeted asset class is within ±{_thresh:g} pts of target.")

    st.divider()

    # ---- accounts: side-by-side comparison -------------------------------- #
    ac1, ac2 = st.columns([0.75, 0.25])
    ac1.subheader("Accounts")
    if CAN_MANAGE:
        with ac2.popover("Rename", width="stretch"):
            # the broker's own names, recovered from the display names in use
            _to_broker = {v: k for k, v in ACCOUNT_LABELS.items()}
            _broker_accts = sorted({p["broker_account"] for p in positions}
                                   | {_to_broker.get(a, a) for a in cash_by_account})
            with st.form("rename_accounts", border=False):
                st.caption("Give an account a name you'll recognize. Leave blank to use the "
                           "broker's name.")
                _typed = {a: st.text_input(a, value=ACCOUNT_LABELS.get(a, ""), placeholder=a,
                                           max_chars=accounts.MAX_LEN, key=f"acct_name_{a}")
                          for a in _broker_accts}
                if st.form_submit_button("Save names", type="primary"):
                    _proposed = {a: n.strip() for a, n in _typed.items() if n.strip()}
                    _bad = next((a for a in _broker_accts
                                 if accounts.clash(a, _proposed.get(a, a), _broker_accts, _proposed)), None)
                    if _bad:
                        st.error(f"Two accounts can't share the name "
                                 f"“{accounts.display(_bad, _proposed)}”.")
                    else:
                        _c = connect(DB)
                        try:
                            for a in _broker_accts:
                                if _proposed.get(a) != ACCOUNT_LABELS.get(a):
                                    accounts.set_label(_c, USER_ID, a, _proposed.get(a))
                        finally:
                            _c.close()
                        st.rerun()

    _acct_stats = {}
    for _p, _ctx in zip(positions, contexts):
        _a = _p["account"]
        _s = _acct_stats.setdefault(_a, {"mv": 0.0, "cost": 0.0, "gain": 0.0, "day_change": 0.0, "n": 0})
        _mv = M.eff_mv(_ctx)
        if _mv is not None:
            _s["mv"] += _mv
            _s["n"] += 1
            _cost = _p["cost_basis"]
            if _cost is not None:
                _s["cost"] += _cost
                _s["gain"] += _mv - _cost
            _dchg = M.value("day_change_usd", _ctx)
            if _dchg is not None:
                _s["day_change"] += _dchg

    _all_accounts = sorted(set(list(_acct_stats) + list(cash_by_account)))
    _acct_rows = []
    for _a in _all_accounts:
        _s = _acct_stats.get(_a, {"mv": 0.0, "cost": 0.0, "gain": 0.0, "day_change": 0.0, "n": 0})
        _csh = cash_by_account.get(_a, 0.0) or 0.0
        _total = _s["mv"] + _csh
        _acct_rows.append({
            "account": _a, "total": _total, "holdings": _s["mv"], "cash": _csh,
            "gain_usd": _s["gain"], "gain_pct": (_s["gain"] / _s["cost"] * 100) if _s["cost"] else None,
            "day_change": _s["day_change"], "n_positions": _s["n"],
            "pct_of_portfolio": (_total / portfolio_value * 100) if portfolio_value else None,
        })
    _acct_rows.sort(key=lambda r: r["total"], reverse=True)

    if len(_acct_rows) < 2:
        st.caption("Only one account in this portfolio — nothing to compare yet.")
    else:
        _adf_raw = pd.DataFrame(_acct_rows)
        _adf = pd.DataFrame([{
            "Account": r["account"], "Total Value": fmt_money(r["total"]),
            "% of Portfolio": fmt_pct(r["pct_of_portfolio"]), "Holdings": fmt_money(r["holdings"]),
            "Cash": fmt_money(r["cash"]), "Gain/Loss": fmt_money(r["gain_usd"]),
            "Gain/Loss %": fmt_pct(r["gain_pct"]), "Today": fmt_money(r["day_change"]),
            "Positions": r["n_positions"],
        } for r in _acct_rows])
        _gain_raw = [r["gain_usd"] for r in _acct_rows]
        _today_raw = [r["day_change"] for r in _acct_rows]
        _acct_styler = (
            _adf.style
            .apply(lambda col: [color_sign(v) for v in _gain_raw], subset=["Gain/Loss"])
            .apply(lambda col: [color_sign(v) for v in _today_raw], subset=["Today"])
        )
        st.dataframe(_acct_styler, width="stretch", hide_index=True)
        st.download_button(
            "Download CSV", _adf_raw.to_csv(index=False).encode("utf-8"),
            file_name="accounts.csv", mime="text/csv", key="accounts_dl",
            disabled=hide_amounts, help=(
                "Disabled while amounts are hidden — turn off Hide amounts to export real figures."
                if hide_amounts else None),
        )


    st.divider()

    # ---- holdings (configurable columns) -------------------------------- #
    if "col_keys" not in st.session_state:
        st.session_state["col_keys"] = load_columns()

    h1, h2 = st.columns([0.75, 0.25])
    h1.subheader("Holdings")
    with h2.popover("Columns", width="stretch"):
        labels = st.multiselect(
            "Columns — add or remove as many as you want",
            [m.label for m in M.AVAILABLE],
            default=[M.BY_KEY[k].label for k in st.session_state["col_keys"] if k in M.BY_KEY],
            key="col_labels",
        )
        new_keys = [M.BY_LABEL[lbl].key for lbl in labels]
        if new_keys and new_keys != st.session_state["col_keys"]:
            st.session_state["col_keys"] = new_keys
            save_columns(new_keys)
        if not perf.has_bars(DB):
            st.caption("The **Yahoo history** columns (MA, Volume, 52-wk, Beta, P/E, Sector) "
                       "stay blank until you tap sync history (:material/history:) up top.")

    # A tappable strip of ticker symbols — the Robinhood-style "click the name"
    # entry point into the detail view below. Deliberately separate from the
    # data grid's own row/cell interactions (Streamlit's dataframe treats a plain
    # cell click as spreadsheet-style cell focus, not row selection — only its
    # checkbox actually selects a row, which isn't the one-tap feel we want here).
    # The search box keeps this usable as the holdings list grows past a couple
    # dozen tickers, where a flat pill strip alone starts taking real scrolling.
    # Only one of the Holdings / Watchlist pill strips can be "the" open ticker
    # at a time — picking one clears the other via on_change (see _pick_holdings
    # / _pick_watchlist below), so there's a single unambiguous selection.
    st.caption("Tap a ticker for its chart and full details:")
    _desc_by_sym = {p["symbol"]: (p.get("description") or "") for p in positions}
    _symbols_held = sorted(_desc_by_sym)
    _search = st.text_input("Search tickers", key="ticker_search",
                            placeholder="Filter by symbol or name…", label_visibility="collapsed")
    if _search.strip():
        _q = _search.strip().upper()
        _pill_options = [s for s in _symbols_held if _q in s.upper() or _q in _desc_by_sym[s].upper()]
    else:
        _pill_options = _symbols_held
    # Never let a search term hide the ticker you already have open.
    _cur_pill = st.session_state.get("holdings_pill")
    if _cur_pill and _cur_pill not in _pill_options:
        _pill_options = sorted(_pill_options + [_cur_pill])


    if not _pill_options:
        st.caption("No ticker matches your search.")
    else:
        st.pills("Tickers", _pill_options, key="holdings_pill", label_visibility="collapsed",
                on_change=_pick_holdings)

    chosen = [M.BY_KEY[k] for k in st.session_state["col_keys"] if k in M.BY_KEY] \
        or [M.BY_KEY[k] for k in M.DEFAULT_KEYS]

    records = [{m.label: M.value(m.key, ctx) for m in chosen} for ctx in contexts]

    df = pd.DataFrame(records, columns=[m.label for m in chosen])
    fmt_map = {m.label: FORMATTERS[m.fmt] for m in chosen if m.fmt in FORMATTERS}
    color_cols = [m.label for m in chosen if m.color_sign]
    styler = df.style.format(fmt_map, na_rep="—")
    if color_cols:
        styler = styler.map(color_sign, subset=color_cols)
    st.dataframe(styler, width="stretch", hide_index=True)
    st.download_button(
        "Download CSV", df.to_csv(index=False).encode("utf-8"),
        file_name="holdings.csv", mime="text/csv", key="holdings_dl",
        disabled=hide_amounts, help=(
            "Disabled while amounts are hidden — turn off Hide amounts to export real figures."
            if hide_amounts else None),
    )
    st.caption("Green = gain, red = loss. Price / Market Value / Gain-Loss use the live price where "
               "available, otherwise the CSV's figures. Edit the column set with **Columns**.")

    st.divider()

if PAGE == "Watchlist":
    # ---- watchlist: tickers tracked for their chart/stats, not owned ------- #
    wc1, wc2 = st.columns([0.75, 0.25])
    _wl_raw = wc1.text_input("Add a ticker", key="wl_add_input", placeholder="Add a ticker, e.g. NVDA",
                             label_visibility="collapsed")
    wc2.write("")
    if wc2.button("+ Add to watchlist", width="stretch") and _wl_raw.strip():
        _wl_conn = connect(DB)
        try:
            added = watchlist.add(_wl_conn, USER_ID, _wl_raw)
        finally:
            _wl_conn.close()
        if added:
            st.session_state["refresh_msg"] = (
                "success", f"Added **{added}** to your watchlist. "
                           f"Tap sync history (:material/history:) up top to pull its chart data.")
        else:
            st.session_state["refresh_msg"] = ("error", f"'{_wl_raw}' doesn't look like a valid ticker.")
        st.rerun()

    if not watch_only:
        st.caption("Nothing on your watchlist yet — add a ticker above to track its chart and stats "
                   "without owning it.")
    else:
        st.caption("Tap a ticker for its chart and stats (no position, so no cost/return figures):")
        st.pills("Watchlist", sorted(watch_only), key="watchlist_pill", label_visibility="collapsed",
                on_change=_pick_watchlist)

    st.divider()

if PAGE in ("Dashboard", "Watchlist"):
    # Each page only renders its own pill strip, so the open ticker comes
    # from that page's strip alone.
    _pill_sym = st.session_state.get("holdings_pill" if PAGE == "Dashboard" else "watchlist_pill")
    # ---- ticker detail: chart + everything about the position/security ----- #
    _idx = next((i for i, p in enumerate(positions) if p["symbol"] == _pill_sym), None) \
        if _pill_sym else None
    _is_held = _idx is not None
    if _pill_sym and not _is_held:
        # Watchlist-only ticker: synthesize a position-less context. eff_price /
        # eff_mv / etc. all read via ctx.get(...).get(...) so a missing "pos"
        # field just resolves to None instead of raising.
        _pos = {"symbol": _pill_sym, "description": sec_info.get(_pill_sym, {}).get("name")}
        _ctx = {"pos": _pos, "quote": quotes.get(_pill_sym, {}), "stats": bar_stats.get(_pill_sym, {}),
                "info": sec_info.get(_pill_sym, {}), "port_value": portfolio_value, "acct_value": None}
    if _pill_sym:
        if _is_held:
            _pos = positions[_idx]
            _ctx = contexts[_idx]
        _sym = _pos["symbol"]
        _has_yahoo = perf.ticker_has_bars(DB, _sym)

        with st.container(border=True):
            # ---- header: symbol, description, live price, today's move ---- #
            hc1, hc2 = st.columns([0.65, 0.35])
            with hc1:
                st.markdown(f"## {_sym}")
                if _pos.get("description"):
                    st.caption(_pos["description"])
            _price = M.eff_price(_ctx)
            _dchg_pct = M.value("day_change_pct", _ctx)
            _dchg_usd = M.value("day_change_usd", _ctx)
            with hc2:
                st.metric("Price", fmt_price(_price),
                          delta=(None if hide_amounts or _dchg_pct is None
                                 else f"{fmt_money(_dchg_usd)} ({_dchg_pct:+.2f}%) today"))
            _price_at = M.value("price_at", _ctx)
            if _price_at:
                st.caption(f"As of {_fmt_when(_price_at)}")

            t1, t2 = st.columns([0.6, 0.4])
            t1.markdown("#### Price history")
            _series = perf.PRICE_SERIES if _has_yahoo else perf.TICKER_SERIES
            _series_label = perf.PRICE_SERIES_LABEL if _has_yahoo else perf.TICKER_SERIES_LABEL
            _series_fmt = perf.PRICE_SERIES_FMT if _has_yahoo else perf.TICKER_SERIES_FMT
            tk_col = t2.selectbox("Ticker series", [c for c, _, _ in _series],
                                  format_func=lambda c: _series_label[c],
                                  key="tk_series_sel", label_visibility="collapsed")

            rng = st.segmented_control("Range", charts.RANGE_LABELS, default="1D",
                                       key="tk_range", label_visibility="collapsed") or "1D"

            if _has_yahoo:
                # ticker_series() already picks the finest resolution Yahoo has for this
                # window (1-minute up through daily) and clips to it at the SQL level.
                _rows, _interval = perf.ticker_series(DB, _sym, charts.RANGE_DAYS[rng])
                _short = False
            else:
                _th = perf.ticker_history(DB, _sym)
                _rows = [{**r, "t": r["fetched_at"]} for r in _th]
                _interval = "sparse"

            if len(_rows) < 2:
                st.info(f"Not enough history for **{_sym}** in this range yet. Tap "
                        "sync history (:material/history:) up top for real intraday + daily bars, or keep "
                        "tapping refresh (:material/refresh:).")
            else:
                tdf = pd.DataFrame(_rows)
                tdf["t"] = pd.to_datetime(tdf["t"], utc=True, format="mixed")
                full = tdf.dropna(subset=[tk_col]) if tk_col in tdf.columns else tdf.iloc[0:0]

                if full.empty:
                    st.info(f"No **{_series_label[tk_col]}** recorded for {_sym} at this resolution.")
                else:
                    _fname = _series_fmt[tk_col]
                    _title = _series_label[tk_col]
                    if _has_yahoo:
                        win = full  # already clipped to the range by ticker_series()
                    else:
                        win, _short = charts.window(full, "t", charts.RANGE_DAYS[rng])

                    mas = []
                    if _interval == "1d" and tk_col == "close":
                        picked = st.segmented_control(
                            "Moving averages", list(charts.MA_STYLE), format_func=lambda w: f"{w}-day",
                            selection_mode="multi", key="tk_ma", label_visibility="collapsed") or []
                        mas = [(f"ma_{w}", *charts.MA_STYLE[w]) for w in picked if f"ma_{w}" in win.columns]

                    first, last, pct = charts.window_change(win, "t", tk_col)
                    mcol, _sp = st.columns([0.4, 0.6])
                    mcol.metric(
                        _title, FORMATTERS[_fname](last) if _fname in FORMATTERS else mask_or(f"{last:,.2f}"),
                        delta=(None if hide_amounts or pct is None else f"{pct:+.2f}% over {rng}"))

                    _date_fmt = "%b %d, %Y" if _interval == "1d" else "%b %d, %Y  %H:%M"
                    _tips = [alt.Tooltip("t:T", title="Date", format=_date_fmt)]
                    if not hide_amounts:
                        _tips.append(alt.Tooltip(f"{tk_col}:Q", title=_title, format=TOOLTIP_FORMAT[_fname]))
                        for _mc, _, _ in mas:
                            _tips.append(alt.Tooltip(f"{_mc}:Q", title=_mc.replace("ma_", "") + "-day MA",
                                                     format="$,.2f"))
                    st.altair_chart(
                        charts.line(win, x="t", y=tk_col, y_title=_title, y_format=AXIS_FORMAT[_fname],
                                    overlays=mas, tooltip=_tips, mask=hide_amounts,
                                    compress_gaps=(_interval in ("1m", "5m", "15m", "60m"))),
                        width="stretch",
                    )
                    _res_label = perf.INTERVAL_LABEL.get(_interval, _interval)
                    st.caption(
                        f"{len(win)}" + (f" of {len(full)}" if len(win) != len(full) else "") + " points · "
                        + (f"**{_res_label}** Yahoo bars." if _has_yahoo
                           else "sparse refresh history — sync history (:material/history:) for real bars.")
                        + (f"  ·  *{rng} is shorter than the data interval — showing the last {len(win)}.*"
                           if _short else "")
                    )

            # ---- your position (held) or watchlist note ------------------- #
            st.divider()
            if _is_held:
                st.markdown("#### Your position")
                _qty = M.value("quantity", _ctx)
                _cost_basis = M.value("cost_basis", _ctx)
                _avg_cost = (_cost_basis / _qty) if (_qty and _cost_basis is not None) else None
                _mv = M.eff_mv(_ctx)
                _unreal_usd = M.value("unrealized_usd", _ctx)
                _unreal_pct = M.value("unrealized_pct", _ctx)
                _pct_port = M.value("pct_of_portfolio", _ctx)

                pc1, pc2, pc3, pc4 = st.columns(4)
                pc1.metric("Shares", fmt_qty(_qty))
                pc2.metric("Avg Cost", fmt_price(_avg_cost))
                pc3.metric("Market Value", fmt_money(_mv))
                pc4.metric("Total Return", fmt_money(_unreal_usd),
                          delta=(None if hide_amounts or _unreal_pct is None else f"{_unreal_pct:+.2f}%"))

                pc5, pc6, pc7, pc8 = st.columns(4)
                pc5.metric("Cost Basis", fmt_money(_cost_basis))
                pc6.metric("Today's Return", fmt_money(_dchg_usd),
                          delta=(None if hide_amounts or _dchg_pct is None else f"{_dchg_pct:+.2f}%"))
                pc7.metric("% of Portfolio", fmt_pct(_pct_port))
                pc8.metric("Account", _pos.get("account") or "—")
            else:
                st.markdown("#### On your watchlist")
                st.caption("Not a position you own — tracking it for the chart and stats only.")

                def _remove_from_watchlist(sym=_sym):
                    # Must clear the "watchlist_pill" widget's state from a
                    # callback, not the main script body below where it renders -
                    # Streamlit forbids writing to a widget's key after that
                    # widget has already been instantiated in the same run.
                    _wl_conn = connect(DB)
                    try:
                        watchlist.remove(_wl_conn, USER_ID, sym)
                    finally:
                        _wl_conn.close()
                    st.session_state["watchlist_pill"] = None

                st.button("Remove from watchlist", key="wl_remove_from_detail",
                         on_click=_remove_from_watchlist)

            # ---- stats: day range, fundamentals, income -------------------- #
            st.markdown("#### Stats")
            _stat_tiles(_ctx, [
                "prev_close", "day_open", "day_high", "day_low",
                "week52_high", "week52_low", "pct_off_52wk_high",
                "volume", "avg_volume", "beta", "pe_ttm", "pb_ratio", "market_cap", "sector",
                "ma_20", "ma_50", "ma_200", "price_vs_ma50",
                "div_yield_pct", "div_pay_date", "reinvest", "next_earnings",
            ])
            if not perf.has_bars(DB):
                st.caption("Fundamentals (52-wk range, beta, P/E, market cap, sector, moving averages) "
                           "fill in after you tap sync history (:material/history:) up top.")

            # ---- news: cached Finnhub headlines, fetched when stale --------- #
            st.markdown("#### Recent News")
            _news_key = resolve_key(None, ENV_PATH)
            if not _news_key:
                st.caption("No `FINNHUB_API_KEY` in `.env` — news uses the same key as "
                           "price refresh.")
            else:
                _news_conn = connect(DB)
                try:
                    _n_new, _news_err = news.sync_ticker(_news_conn, _sym, _news_key)
                    _articles = news.latest_news(_news_conn, _sym)
                finally:
                    _news_conn.close()
                if _news_err and not _articles:
                    st.caption(f"Couldn't load news for {_sym}: {_news_err}")
                elif not _articles:
                    st.caption(f"No recent news for {_sym} in the last {news.LOOKBACK_DAYS} days.")
                else:
                    for _a in _articles:
                        _pub = (pd.to_datetime(_a["published_at"], utc=True).strftime("%b %d, %Y %H:%M UTC")
                               if _a["published_at"] else "")
                        st.markdown(f"**[{_a['headline']}]({_a['url']})**  \n*{_a['source']} · {_pub}*")
                        if _a.get("summary"):
                            _sumtext = _a["summary"]
                            st.caption(_sumtext[:220] + ("…" if len(_sumtext) > 220 else ""))
        st.divider()
    else:
        st.caption("↑ Tap a ticker above to see its chart and full details here.")
        st.divider()


if PAGE == "Activity":
    # ---- activity: inferred transaction history --------------------------- #

    _txn_conn = connect(DB)
    try:
        _all_txns = [dict(r) for r in _txn_conn.execute(
            "SELECT * FROM transactions WHERE user_id = ? ORDER BY trade_date DESC, id DESC", (USER_ID,))]
    finally:
        _txn_conn.close()
    for _t in _all_txns:
        _t["account"] = accounts.display(_t["account"], ACCOUNT_LABELS)

    if not _all_txns:
        st.caption("No transactions yet — they're inferred automatically the next time you import "
                   "a CSV whose quantities differ from your last snapshot.")
    else:
        fc1, fc2, fc3 = st.columns(3)
        _f_accounts = fc1.multiselect(
            "Account", sorted({t["account"] for t in _all_txns if t["account"]}), key="txn_f_account")
        _f_actions = fc2.multiselect(
            "Action", sorted({t["action"] for t in _all_txns if t["action"]}), key="txn_f_action")
        _f_symbol = fc3.text_input("Symbol contains", key="txn_f_symbol", placeholder="e.g. AAPL")

        _filtered = _all_txns
        if _f_accounts:
            _filtered = [t for t in _filtered if t["account"] in _f_accounts]
        if _f_actions:
            _filtered = [t for t in _filtered if t["action"] in _f_actions]
        if _f_symbol.strip():
            _sq = _f_symbol.strip().upper()
            _filtered = [t for t in _filtered if _sq in (t["symbol"] or "").upper()]

        if not _filtered:
            st.caption("No transactions match these filters.")
        else:
            _realized = [t["realized_gain"] for t in _filtered if t["realized_gain"] is not None]
            rc1, rc2 = st.columns(2)
            rc1.metric("Transactions shown", len(_filtered))
            if _realized:
                rc2.metric("Realized gain/loss", fmt_money(sum(_realized)))

            # Pre-formatted to display strings (not left as raw floats for the
            # Styler to format at render time) - Streamlit's dataframe grid
            # doesn't reliably pick up a Styler's na_rep/format for a NaN cell,
            # rendering the raw missing value as the literal text "None" instead.
            # Color still needs the ORIGINAL numbers, so it's computed from a
            # closure over the raw list, independent of the now-string columns.
            _amount_raw = [t["amount"] for t in _filtered]
            _gain_raw = [t["realized_gain"] for t in _filtered]
            _tdf = pd.DataFrame([{
                "Date": t["trade_date"], "Action": t["action"], "Symbol": t["symbol"],
                "Description": t["description"], "Qty": fmt_qty(t["quantity"]),
                "Price": fmt_price(t["price"]), "Amount": fmt_money(t["amount"]),
                "Realized G/L": fmt_money(t["realized_gain"]), "Account": t["account"],
            } for t in _filtered])
            _txn_styler = (
                _tdf.style
                .apply(lambda col: [color_sign(v) for v in _amount_raw], subset=["Amount"])
                .apply(lambda col: [color_sign(v) for v in _gain_raw], subset=["Realized G/L"])
            )
            st.dataframe(_txn_styler, width="stretch", hide_index=True)
            _tdf_raw = pd.DataFrame([{
                "Date": t["trade_date"], "Action": t["action"], "Symbol": t["symbol"],
                "Description": t["description"], "Qty": t["quantity"], "Price": t["price"],
                "Amount": t["amount"], "Realized G/L": t["realized_gain"], "Account": t["account"],
            } for t in _filtered])
            st.download_button(
                "Download CSV", _tdf_raw.to_csv(index=False).encode("utf-8"),
                file_name="activity.csv", mime="text/csv", key="activity_dl",
                disabled=hide_amounts, help=(
                    "Disabled while amounts are hidden — turn off Hide amounts to export real figures."
                    if hide_amounts else None),
            )
            st.caption("Inferred from the quantity change between imported snapshots, not broker "
                       "trade confirmations — Price/Amount are estimates, and Realized G/L uses the "
                       "average-cost method (a Positions export has no per-lot detail for FIFO).")


if PAGE == "Income":
    # ---- income: dividend yield summary + per-position breakdown ---------- #

    _income_rows = []
    for p, ctx in zip(positions, contexts):
        _yld = M.value("div_yield_pct", ctx)
        _mv = M.eff_mv(ctx)
        if _yld is None or _mv is None:
            continue
        _income_rows.append({
            "symbol": p["symbol"], "description": p.get("description"), "market_value": _mv,
            "yield_pct": _yld, "est_income": _mv * _yld / 100,
            "last_pay_date": p.get("div_pay_date"),
            "reinvest": {1: "Yes", 0: "No"}.get(p.get("reinvest")), "account": p["account"],
        })

    if not _income_rows:
        st.caption("No dividend-yield data on any position yet — it comes straight from the Schwab "
                   "CSV export's **Dividend Yield** / **Div Pay Date** columns, not Yahoo, so it's "
                   "only there if your broker reported it at import time.")
    else:
        _total_income = sum(r["est_income"] for r in _income_rows)
        _yield_on_holdings = (_total_income / tot_mv * 100) if tot_mv else None

        ic1, ic2, ic3 = st.columns(3)
        ic1.metric("Est. annual dividend income", fmt_money(_total_income))
        ic2.metric("Yield on holdings", fmt_pct(_yield_on_holdings))
        ic3.metric("Income-producing positions", f"{len(_income_rows)} / {len(positions)}")

        _income_rows.sort(key=lambda r: r["est_income"], reverse=True)
        _idf_raw = pd.DataFrame([{
            "Symbol": r["symbol"], "Description": r["description"],
            "Market Value": r["market_value"], "Div Yield %": r["yield_pct"],
            "Est. Annual Income": r["est_income"], "Last Pay Date": r["last_pay_date"],
            "Reinvest": r["reinvest"], "Account": r["account"],
        } for r in _income_rows])
        _idf = pd.DataFrame([{
            "Symbol": r["symbol"], "Description": r["description"],
            "Market Value": fmt_money(r["market_value"]), "Div Yield %": fmt_pct(r["yield_pct"]),
            "Est. Annual Income": fmt_money(r["est_income"]),
            "Last Pay Date": r["last_pay_date"] or "—", "Reinvest": r["reinvest"] or "—",
            "Account": r["account"],
        } for r in _income_rows])
        st.dataframe(_idf, width="stretch", hide_index=True)
        st.download_button(
            "Download CSV", _idf_raw.to_csv(index=False).encode("utf-8"),
            file_name="income.csv", mime="text/csv", key="income_dl",
            disabled=hide_amounts, help=(
                "Disabled while amounts are hidden — turn off Hide amounts to export real figures."
                if hide_amounts else None),
        )
        st.caption("Est. Annual Income = market value × dividend yield, both as reported in the CSV "
                   "— a simple estimate, not a payment schedule. **Last Pay Date** is the most "
                   "recently known payment from Schwab, not a prediction of the next one.")


if PAGE == "Plan":
    _render_plan(portfolio_value, tot_gl,
                 allocate(positions, cash_by_account, CLASS_SPLITS)["by_asset_class"])

if PAGE == "Get started":
    _render_get_started(True, portfolio_value)

if PAGE == "Advisor notes":
    _render_notes()

if PAGE == "AI Assistant":
    _render_assistant(contexts, cash_by_account)
