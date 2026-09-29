"""Portfolio Tracker - single-page Streamlit dashboard.

Run it:  streamlit run dashboard.py   (or double-click dashboard.cmd)
"""

import json
import os
from datetime import datetime, timedelta, timezone

import altair as alt
import pandas as pd
import streamlit as st

import accounts
import alerts
import auth
import charts
import metrics as M
import news
import perf
import pgcompat
import watchlist
from allocation import CONCENTRATION_PCT, allocate
from portfolio import DBError, connect, import_csv, parse_csv_smart
from update_prices import ENV_PATH, latest_snapshot, load_env, refresh_prices, resolve_key
from changes import diff_positions, synthesize_transactions

HERE = os.path.dirname(os.path.abspath(__file__))
# Defaults to ./portfolio.db; set PORTFOLIO_DB to point at another file (handy for
# trying the importer against a throwaway copy).
DB = os.environ.get("PORTFOLIO_DB") or os.path.join(HERE, "portfolio.db")

GREEN = "#16a34a"
RED = "#dc2626"

st.set_page_config(page_title="Portfolio Tracker", layout="wide",
                   initial_sidebar_state="auto")

# App-wide styles: hide Streamlit's own running/deploy widgets, tighten the
# page on phones, and the classes used by the hero, stat tiles, and
# allocation bars below. Text inherits the theme's colors; only marks and
# gain/loss figures carry their own.
st.html("""<style>
[data-testid="stStatusWidget"], [data-testid="stAppDeployButton"], .stAppDeployButton {
  display: none !important; }
[data-testid="stMainBlockContainer"] { padding-top: 3rem; }
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
</style>""")


def _login() -> bool:
    """Per-account login - every account is admin-provisioned (see
    manage_users.py); there is no signup anywhere in this app. Sets
    st.session_state["user_id"]/["username"] on success, same pattern the
    old single shared-password gate used for "authed". Generic error
    message on any failure (unknown username OR wrong password) so the
    login screen never reveals which username exists."""
    if st.session_state.get("user_id"):
        return True
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        st.title("Portfolio Tracker")
        st.caption("Sign in to see your portfolio.")
        with st.form("login_form", border=True):
            user = st.text_input("Username", key="login_user")
            pw = st.text_input("Password", type="password", key="login_pw")
            submitted = st.form_submit_button("Log in", type="primary", width="stretch")
    if submitted:
        conn = connect(DB)
        try:
            user_id = auth.verify_login(conn, user, pw) if user and pw else None
        finally:
            conn.close()
        if user_id is not None:
            st.session_state["user_id"] = user_id
            st.session_state["username"] = user
            st.rerun()
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
    st.session_state.clear()


if not _login():
    st.stop()

# Advisor mode: user_id is who logged in; active_user_id is whose data is
# showing. Every query below goes through USER_ID, so it's resolved here,
# re-checked against the database on every run - never trusted from
# session state alone.
LOGIN_ID = st.session_state["user_id"]
_conn = connect(DB)
try:
    IS_ADVISOR = auth.is_advisor(_conn, LOGIN_ID)
    CLIENTS = auth.list_clients(_conn, LOGIN_ID) if IS_ADVISOR else []
    _active = st.session_state.get("active_user_id", LOGIN_ID)
    if not auth.can_view(_conn, LOGIN_ID, _active):
        _active = LOGIN_ID
    ACCOUNT_LABELS = accounts.labels(_conn, _active)
finally:
    _conn.close()
USER_ID = _active
st.session_state["active_user_id"] = USER_ID
ACTIVE_NAME = (st.session_state["username"] if USER_ID == LOGIN_ID
               else dict(CLIENTS).get(USER_ID, "client"))
PREFS_PATH = os.path.join(HERE, f".dashboard_prefs.{USER_ID}.json")

PAGES = ["Dashboard", *(["Clients"] if IS_ADVISOR else []),
         "Watchlist", "Activity", "Income", "AI Assistant"]
if st.session_state.get("page") not in PAGES:
    st.session_state["page"] = PAGES[0]

# kept when an advisor switches accounts; everything else is per-account
_KEEP_ON_SWITCH = ("user_id", "username", "page")


def _go(page):
    st.session_state["page"] = page


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
    if len(pw) < 8:
        st.session_state["client_msg"] = ("error", "Use a password of at least 8 characters.")
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


with st.sidebar:
    st.markdown("### Portfolio Tracker")
    for _p in PAGES:
        st.button(_p, key=f"nav_{_p}", on_click=_go, args=(_p,), width="stretch",
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

    _viewing = f" · viewing **{ACTIVE_NAME}**" if USER_ID != LOGIN_ID else ""
    st.caption(f"Logged in as **{st.session_state['username']}**{_viewing}")
    st.button("Log out", on_click=_logout, width="stretch")
    # sidebar handle, click-away to close, pull to refresh (see the file)
    with open(os.path.join(HERE, "ui_enhancements.js"), encoding="utf-8") as _fh:
        st.html(f"<script>{_fh.read()}</script>", unsafe_allow_javascript=True)

PAGE = st.session_state["page"]


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


def _rules_for(account_id):
    """That account's saved alert limits (its own prefs file), else defaults."""
    try:
        with open(os.path.join(HERE, f".dashboard_prefs.{account_id}.json"), encoding="utf-8") as fh:
            saved = (json.load(fh) or {}).get("rules") or {}
    except (OSError, ValueError, AttributeError):
        saved = {}
    return [{**r, "abs_gt": float(saved.get(r["key"], r["abs_gt"]))} for r in alerts.DEFAULT_RULES]


def _render_clients():
    import overview

    if not CLIENTS:
        st.info("No clients yet - add one with **Add client** in the sidebar.")
        return
    conn = connect(DB)
    try:
        quotes = overview.latest_quotes(conn)
        rows = [{**overview.account_summary(conn, cid, quotes, _rules_for(cid)), "name": name}
                for cid, name in CLIENTS]
    finally:
        conn.close()
    rows.sort(key=lambda r: r["portfolio_value"] or 0.0, reverse=True)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Clients", len(rows))
    m2.metric("Total value", fmt_money(sum(r["portfolio_value"] or 0.0 for r in rows)))
    m3.metric("With alerts", sum(1 for r in rows if r["n_alerts"]))
    m4.metric("Profiles incomplete", sum(1 for r in rows if r["profile_answered"] < r["profile_total"]))

    widths = [2, 1.5, 1.2, 1, 1, 1.4, 1.1, 1]
    for col, head in zip(st.columns(widths), ["Client", "Value", "Gain/loss", "Positions",
                                              "Alerts", "As of", "Profile", ""]):
        col.caption(head)
    for r in rows:
        cols = st.columns(widths, vertical_alignment="center")
        cols[0].markdown(f"**{r['name']}**")
        if r["has_data"]:
            cols[1].write(fmt_money(r["portfolio_value"]))
            gain = r["gain_pct"]
            if gain is None or _hidden():
                cols[2].write(fmt_pct(gain))
            else:
                cols[2].markdown(f"<span style='color:{GREEN if gain >= 0 else RED}'>"
                                 f"{fmt_pct(gain)}</span>", unsafe_allow_html=True)
            cols[3].write(str(r["n_positions"]))
            cols[4].write(str(r["n_alerts"]) if r["n_alerts"] else "—")
            cols[5].write(r["snapshot_date"])
        else:
            cols[1].caption("No data yet")
        done, total = r["profile_answered"], r["profile_total"]
        cols[6].write("Complete" if done == total else f"{done}/{total}")
        cols[7].button("Open", key=f"open_client_{r['user_id']}", on_click=_open_client,
                       args=(r["user_id"],), width="stretch")
    st.caption("Alerts use each client's own limits (set under **Rules** on their Dashboard). "
               "Profile counts the AI Assistant questions answered.")


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
    "contributions": "How often will you add money?",
    "withdrawal_needs": "Planning to take money out in the next 3 years?",
    "preferences": "Anything you'd like in your investments? Pick any.",
}
PROFILE_SECTIONS = (
    ("Goals", ("goal", "time_horizon_years", "target_return_pct")),
    ("Comfort with risk", ("risk_tolerance", "drawdown_reaction", "experience")),
    ("Your situation", ("age_range", "income_stability", "emergency_fund",
                        "high_interest_debt", "contributions", "withdrawal_needs")),
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
                        advisor.portfolio_summary(contexts, cash_by_account),
                        client_plan.chat_transcript(display), memory)
                except anthropic.AuthenticationError:
                    st.warning("The ANTHROPIC_API_KEY was rejected - the plan was made "
                               "without suggested next steps.")
                except anthropic.RateLimitError:
                    st.warning("The assistant is rate-limited right now - the plan was made "
                               "without suggested next steps.")
                except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
                    st.warning(f"Couldn't reach the assistant ({exc}) - the plan was made "
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


def _render_assistant(contexts, cash_by_account):
    import advisor

    if st.session_state.pop("profile_toast", False):
        st.toast("Profile updated from the conversation.")
    api_key = _anthropic_key()
    if not api_key:
        st.info("The assistant needs an `ANTHROPIC_API_KEY` - add it to `.env` locally, or to "
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
        st.caption("The assistant also fills this in from what you tell it in the chat, and "
                   "keeps short notes of its own so the next conversation picks up where this "
                   "one left off.")

    st.caption("Educational information only - not financial advice. The assistant is not a "
               "licensed financial advisor; do your own research before making any investment "
               "decision.")

    _render_plan_export(api_key, profile, memory, contexts, cash_by_account, display)
    # new messages are written into this box too, so they land above the input
    chat_box = st.container()
    with chat_box:
        for msg in display:
            with st.chat_message(msg["role"]):
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
        typed = st.chat_input("Ask about investing or your portfolio...", disabled=at_limit)
    prompt = typed or prompt

    if prompt and not at_limit:
        import anthropic

        display.append({"role": "user", "text": prompt})
        history.append({"role": "user", "content": prompt})
        with chat_box, st.chat_message("user"):
            st.markdown(prompt)

        system = advisor.system_prompt(profile, advisor.portfolio_summary(contexts, cash_by_account),
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

        with chat_box, st.chat_message("assistant"):
            try:
                reply = st.write_stream(advisor.stream_reply(
                    anthropic.Anthropic(api_key=api_key), history, system, on_update,
                    on_memory))
            except anthropic.AuthenticationError:
                reply = "The ANTHROPIC_API_KEY was rejected - check that it's correct."
                st.error(reply)
            except anthropic.RateLimitError:
                reply = "The assistant is rate-limited right now - wait a minute and try again."
                st.error(reply)
            except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
                reply = f"Couldn't reach the assistant: {exc}"
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
    st.caption("Your holdings are shared with the assistant as percentages only - no dollar "
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


def _read_prefs():
    try:
        with open(PREFS_PATH, encoding="utf-8") as fh:
            d = json.load(fh)
            return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_prefs(d):
    try:
        with open(PREFS_PATH, "w", encoding="utf-8") as fh:
            json.dump(d, fh, indent=1)
    except OSError:
        pass


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


def load_alloc_targets():
    """{asset-type label: target %}. Only labels the user has explicitly set
    a nonzero target for are included — an unset label has no target and is
    never flagged, rather than implicitly meaning "target 0%"."""
    saved = _read_prefs().get("alloc_targets") or {}
    return {k: float(v) for k, v in saved.items() if v}


def save_alloc_targets(targets: dict):
    p = _read_prefs()
    p["alloc_targets"] = {k: v for k, v in targets.items() if v}
    _write_prefs(p)


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


def _prices_stale(last_live) -> bool:
    if not last_live:
        return True
    try:
        at = datetime.fromisoformat(str(last_live).replace("Z", "+00:00"))
    except ValueError:
        return True
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - at > AUTO_REFRESH_AFTER


def _refresh_prices(auto=False):
    """Fetch Finnhub quotes for this account, then rerun to show them. Success
    is a toast; problems get a banner. The automatic refresh on opening an
    account says nothing when there's no key."""
    key = resolve_key(None, ENV_PATH)
    if not key:
        if auto:
            return
        st.session_state["refresh_msg"] = ("error", "No FINNHUB_API_KEY in .env — add it and retry.")
        st.rerun()
    bar = st.progress(0.0, text="Updating prices…" if auto else "Contacting Finnhub…")
    conn = connect(DB)
    try:
        summary = refresh_prices(
            conn, latest_snapshot(conn, USER_ID), USER_ID, key, delay=0.0,
            on_quote=lambda i, n, tk, ok, px, err: bar.progress(i / n, text=f"{tk} ({i}/{n})"),
        )
    finally:
        conn.close()
    bar.empty()
    if summary["failed"]:
        bad = ", ".join(tk for tk, _, err, _ in summary["results"] if err)
        st.session_state["refresh_msg"] = (
            "warning",
            f"Updated {summary['updated']} positions · {summary['ok']}/{summary['tickers']} quotes OK · "
            f"no data for: {bad}",
        )
    else:
        st.session_state["refresh_msg"] = (
            "toast", f"Prices updated: {summary['ok']} live quotes.")
    st.rerun()


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
    st.session_state.pop("auto_refreshed", None)
    st.session_state.pop("auto_backfilled", None)


def _toggle_hide():
    st.session_state["hide_amounts"] = not st.session_state.get("hide_amounts", False)
    save_hide(st.session_state["hide_amounts"])


def _page_header(title, *, data=True):
    """The page's title with the app's icon actions beside it. `data` pages
    (this account's portfolio) also get import / refresh / sync and a
    one-line status: how fresh the prices are and the statement date."""
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.title(title, anchor=False, width="stretch")
        if data and st.button(":material/upload:", key="pt_import", type="tertiary",
                              help="Import a new positions CSV"):
            _import_dialog()
        st.button(":material/visibility_off:" if _hidden() else ":material/visibility:",
                  key="pt_hide", type="tertiary", on_click=_toggle_hide,
                  help="Show amounts" if _hidden() else "Hide amounts - mask every dollar and "
                                                         "percent with " + MASK)
        if data and st.button(":material/refresh:", key="pt_refresh", type="tertiary",
                              help="Refresh prices. On a phone you can also pull down from the top "
                                   "of the page. Prices also refresh on their own when you open "
                                   "an account."):
            _refresh_prices()
        if data and st.button(":material/history:", key="pt_sync", type="tertiary",
                              help="Sync history from Yahoo: the deepest history Yahoo allows at "
                                   "every resolution (~2 years daily, plus 1-minute to hourly "
                                   "bars) and fundamentals. Takes a minute or two. It also runs "
                                   "on its own every evening."):
            _sync_history()
    if data:
        if last_live:
            prices = f"Prices as of {_fmt_when(last_live)}"
            if n_live < len(positions):
                prices += f" ({n_live} of {len(positions)} priced)"
        else:
            prices = "No live prices yet"
        st.html(f"<div class='pt-status'>{prices} · Statement from {_fmt_date(snapshot)}</div>")

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
if not positions and PAGE == "AI Assistant":
    # Helping brand-new investors plan a first portfolio is a core use of the
    # assistant, so it works before any CSV has been imported.
    _page_header(PAGE, data=False)
    _render_assistant([], {})
    st.stop()
if PAGE == "Clients":
    # about the advisor's clients, not the viewed account's data
    _page_header(PAGE, data=False)
    _render_clients()
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
    st.info(f"Welcome, **{ACTIVE_NAME}** — this account has no data yet. "
            "Upload a Schwab Positions export CSV to get started.")
    st.caption("New to investing? Open **AI Assistant** in the sidebar for help planning a "
               "first portfolio.")
    up = st.file_uploader("Positions export (.csv)", type=["csv"], key="onboard_csv_upload")
    if up is not None:
        imports_dir = os.path.join(HERE, "imports", str(USER_ID))
        os.makedirs(imports_dir, exist_ok=True)
        src_path = os.path.join(imports_dir, up.name)
        with open(src_path, "wb") as fh:
            fh.write(up.getbuffer())
        _conn = connect(DB)
        try:
            info = import_csv(_conn, src_path, USER_ID, _anthropic_key())
        except DBError as exc:
            st.error(f"Import failed: {exc}")
        except SystemExit as exc:
            st.error(f"Couldn't parse this file: {exc}")
        else:
            note = " (Claude helped interpret this file's headers — worth a spot check.)" \
                if info["ai_assisted"] else ""
            st.session_state["import_flash"] = (
                f"Imported your statement from {_fmt_date(info['snapshot_date'])} - "
                f"{info['n_positions']} positions.{note}")
            _after_import()
            st.rerun()
        finally:
            _conn.close()
    st.stop()

cash = sum(cash_by_account.values())

# Deep Yahoo history (moving averages, volume, 52-wk, beta, P/E, sector).
bar_stats = perf.bar_stats(DB)
sec_info = perf.security_info(DB)

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

# Refresh once when an account is opened (login, or an advisor switching
# accounts - the flag is dropped with the rest of the session on a switch),
# unless the scheduled job already did it recently.
if not st.session_state.get("auto_refreshed"):
    st.session_state["auto_refreshed"] = True
    if _prices_stale(last_live):
        _refresh_prices(auto=True)
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


@st.dialog("Import a positions CSV", width="large")
def _import_dialog():
    """Upload a new Schwab Positions export, preview what changed, confirm."""
    st.caption(
        "Upload a fresh Schwab **Positions** export. You'll see exactly what changed "
        "before anything is saved."
    )
    up = st.file_uploader("Positions export (.csv)", type=["csv"], key="csv_upload")
    # A path on "this machine" is only meaningful running locally - on the
    # hosted app it would be a path on the server, which users must not read.
    path_in = "" if pgcompat.is_postgres_dsn(DB) else st.text_input(
        "…or a path to a CSV on this machine",
        key="csv_path",
        placeholder="C:\\Users\\you\\Downloads\\All-Accounts-Positions-....csv",
    ).strip().strip('"')

    src_path = None
    if up is not None:
        imports_dir = os.path.join(HERE, "imports", str(USER_ID))
        os.makedirs(imports_dir, exist_ok=True)
        src_path = os.path.join(imports_dir, up.name)
        with open(src_path, "wb") as fh:
            fh.write(up.getbuffer())
    elif path_in:
        src_path = path_in

    if src_path and not os.path.isfile(src_path):
        st.error(f"No file at: {src_path}")
    elif src_path:
        _parse_info: dict = {}
        try:
            _meta, new_rows, _ = parse_csv_smart(src_path, _anthropic_key(), _parse_info)
        except SystemExit as exc:
            st.error(f"Couldn't parse this file: {exc}")
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

                txns = synthesize_transactions(d, file_date, os.path.abspath(src_path))
                st.caption(
                    f"On confirm: positions + account totals for **{file_date}** are written, "
                    f"and **{len(txns)}** transaction row(s) inferred from the quantity deltas "
                    f"(BUY / SELL) are recorded."
                )

                if st.button("Confirm import", type="primary", key="csv_confirm"):
                    try:
                        info = import_csv(_conn, src_path, USER_ID, _anthropic_key())
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


# Holdings with no Yahoo history yet (a first import, or a new position):
# fetch it once per visit so the charts fill in without a manual sync. Runs
# before the header so the header's one-shot messages survive its rerun.
_covered, _missing = perf.holdings_coverage(DB, USER_ID)
if PAGE == "Dashboard" and _missing and not st.session_state.get("auto_backfilled"):
    st.session_state["auto_backfilled"] = True
    _sync_history(_missing, quick=True)

_page_header(PAGE)
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
    alloc = allocate(positions, cash_by_account)
    # One color per asset type across every allocation bar on the page.
    _asset_slots = _slot_map({r["label"] for r in alloc["by_asset_type"]}, ASSET_SLOT)

    al1, al2 = st.columns([0.75, 0.25])
    al1.subheader("Allocation")
    _asset_labels = [r["label"] for r in alloc["by_asset_type"]]
    with al2.popover("Targets", width="stretch"):
        st.caption("Set a target % of portfolio for any asset type — leave at 0 for no target.")
        _saved_targets = load_alloc_targets()
        _new_targets = {}
        for _lbl in _asset_labels:
            _new_targets[_lbl] = st.number_input(
                _lbl, min_value=0.0, max_value=100.0, step=1.0,
                value=float(_saved_targets.get(_lbl, 0.0)), key=f"target_{_lbl}")
        _new_thresh = st.number_input(
            "Flag drift beyond ± this many percentage points", min_value=0.5, max_value=50.0,
            step=0.5, value=load_drift_threshold(), key="drift_threshold_input")
        if _new_targets != _saved_targets:
            save_alloc_targets(_new_targets)
        if _new_thresh != load_drift_threshold():
            save_drift_threshold(_new_thresh)

    if len(alloc["by_account"]) > 1:
        a1, a2 = st.columns(2, gap="large")
        a1.html(_alloc_bar(alloc["by_asset_type"], "By asset type", _asset_slots))
        a2.html(_alloc_bar(alloc["by_account"], "By account",
                           _slot_map({r["label"] for r in alloc["by_account"]})))
    else:
        st.html(_alloc_bar(alloc["by_asset_type"], "By asset type", _asset_slots))

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
        _pct_by_label = {r["label"]: r["pct"] for r in alloc["by_asset_type"]}
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
            st.caption(f"All targeted asset types are within ±{_thresh:g} pts of target.")

    st.divider()

    # ---- accounts: side-by-side comparison -------------------------------- #
    ac1, ac2 = st.columns([0.75, 0.25])
    ac1.subheader("Accounts")
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

        st.caption("Asset mix by account:")
        _acct_cols = st.columns(len(_all_accounts))
        for _col, _a in zip(_acct_cols, _all_accounts):
            _acct_positions = [p for p in positions if p["account"] == _a]
            _acct_cash = {_a: cash_by_account.get(_a, 0.0)}
            _acct_alloc = allocate(_acct_positions, _acct_cash)
            _col.html(_alloc_bar(_acct_alloc["by_asset_type"], _a, _asset_slots))

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


if PAGE == "AI Assistant":
    _render_assistant(contexts, cash_by_account)
