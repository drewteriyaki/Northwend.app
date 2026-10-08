"""Northwend (formerly Waypoint, and Portfolio Tracker before that) - single-page Streamlit dashboard.

Run it:  streamlit run dashboard.py   (or double-click dashboard.cmd)
"""

import contextlib
import functools
import html
import json
import os
import re
import time
from datetime import date, datetime, timedelta, timezone

import altair as alt
import pandas as pd
import streamlit as st

import codefresh

# After a deploy, drop any of our modules still loaded at an older version so
# the imports below load one current set (see codefresh.py).
_OLD_MODULES = codefresh.drop_stale(os.path.dirname(os.path.abspath(__file__)))

import access_log
import accounts
import advising
import ai_spend
import ai_policy
import ai_usage
import alerts
import asset_classes
import auth
import charts
import consent
import csv_import
import disclosures
import export
import flags
import friendly_errors
import glossary
import fund_holdings
import hosting
import income
import invite_codes
import learn
import live_prices
import mailer
import manual_entry
import paste_parse
import screenshot_read
import sample_data
import settings
import metrics as M
import news
import news_feed
import perf
import pgcompat
import plans
import prefs
import price_report
import rate_limits
import together
import whats_new
import route
import watchlist
from allocation import CONCENTRATION_PCT, allocate, summary_words
from portfolio import (SAMPLE_SOURCE, DBError, connect, delete_holdings, snapshot_cash,
                       snapshot_positions, snapshot_source, temp_upload, upload_label)
from update_prices import ENV_PATH, latest_snapshot, load_env, refresh_prices, resolve_key
import changes

codefresh.carry_over(_OLD_MODULES)
codefresh.mark_loaded(os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))
# Running locally, defaults to ./portfolio.db; set PORTFOLIO_DB to point at another
# file (handy for trying the importer against a throwaway copy). A hosted copy
# never falls back to a local file: it stops below the page setup without a
# Postgres PORTFOLIO_DB (settings.py).
DB = settings.database(os.path.join(HERE, "portfolio.db"))
HOSTED = settings.hosted()   # live or staging, not someone's own computer
# The staging app (its own Streamlit Cloud app on the `staging` branch, with
# its own database) sets NORTHWEND_ENV = "staging" in its Secrets: every page
# then says so, so it is never mistaken for the live app.
STAGING = settings.staging()


def _view(name):
    """Run views/<name>.py here, in this script's own namespace - exactly as if
    its code were written at this spot. Each page's code lives in its own file
    so it can be read and changed on its own; nothing else about it changes.
    A view a feature owns (flags.FEATURES) is skipped while that feature is off."""
    if not flags.view_on(name):
        return
    path = os.path.join(HERE, "views", f"{name}.py")
    with open(path, encoding="utf-8") as fh:
        exec(compile(fh.read(), path, "exec"), globals())  # noqa: S102

# An unexpected error shows "something went wrong" instead of a traceback; the
# traceback goes to the log. Details show on screen only for a local run. The
# hosted copies (live, staging) also email the admin about it (error_alerts.py,
# once an hour per kind); every copy lists it on Admin > System.
friendly_errors.install(show_details=settings.show_error_details()
                        and st.get_option("client.showErrorDetails") in ("full", True, "true"),
                        alert_db=DB or None, copy="Staging" if STAGING else "Live",
                        send_alerts=settings.send_error_alerts())
# Every AI answer's token counts go into this copy's month total (ai_spend.py:
# counts only); the admin is emailed at 50% and 80% of the ceiling - hosted only.
ai_spend.use_db(DB or None, send=settings.send_error_alerts(),
                copy="Staging" if STAGING else "Live")

# said wherever people decide what to share (import, hand entry, paste). True
# to what's saved: each holding's symbol, shares, cost and value, and cash
# (csv_import.to_snapshot, portfolio.write_snapshot) - never the file itself,
# a brokerage login, or more than an account number's last 3 digits.
TRUST_LINE = ("We never ask for your brokerage login. We save your holdings - symbols, "
              "shares, cost, value and cash - so the app can show them, and never more than "
              "the last 3 digits of an account number.")
NOT_KEPT = ("Not kept: the file, screenshot or pasted text itself, your brokerage login, and "
            "account numbers beyond their last 3 digits.")


def learn_more(topic):
    """A small, quiet "Learn more" link next to an idea the page explains, to
    a public education page (Investor.gov, FINRA, the CFPB - learn.LEARN_MORE).
    Opens in a new tab."""
    line = learn.learn_more_md(topic)
    if line:
        st.caption(line)


def what_this_means(*words, key, label="What does this mean?"):
    """A small "What does this mean?" popover with the glossary's meaning of
    a few words the page uses (glossary.py - owner-written, no AI). Nothing
    while the `glossary` flag is off, or when none of the words is in it."""
    if not flags.on("glossary"):
        return
    rows = glossary.pick(words)
    if not rows:
        return
    with st.popover(label, icon=":material/menu_book:", type="tertiary", key=key):
        st.markdown("\n\n".join(f"**{t}** - {m}" for t, m in rows))   # our own text

# The brand: Northwend, and the AI guide (the AI Assistant) carries the same
# name - "Ask Northwend". Was Waypoint / Sage until October 2026. Pages keep
# their internal names (session state, links, `if PAGE == ...`); PAGE_LABELS
# is only what people see.
APP_NAME = "Northwend"
TAGLINE = "Your guide from first step to goal."
GUIDE = APP_NAME  # the AI guide shares the app's name: "Ask Northwend"
# The logo, star over paper hills (static/logo.svg, logo-dark.svg): the tab's
# icon, and shown beside the name - in the menu column, the phone's top bar
# and the sign-in screens. In the page it's two images, one per theme (the
# styles show the one that matches; Streamlit's sanitizer drops inline SVG and
# serves static files as plain text). Material's flag is Plan's icon only.
APP_ICON = os.path.join(HERE, "static", "logo.svg")


@functools.lru_cache(maxsize=1)
def _logo_srcs():
    import base64
    out = {}
    for theme, name in (("light", "logo.svg"), ("dark", "logo-dark.svg")):
        with open(os.path.join(HERE, "static", name), "rb") as fh:
            out[theme] = "data:image/svg+xml;base64," + base64.b64encode(fh.read()).decode("ascii")
    return out


def _logo(size=""):
    """The logo (decoration: the name is beside it); `size` 'lg' beside a
    page-sized title."""
    cls = "pt-logo" + (f" pt-logo-{size}" if size else "")
    return "".join(f"<img class='{cls} pt-on-{theme}' alt='' src='{src}'>"
                   for theme, src in _logo_srcs().items())


def _brand_html(extra=""):
    """The logo and the name, in Newsreader: the menu's brand, and the small
    line over a page shown without signing in (`extra` 'pt-brand-line')."""
    return (f"<div class='pt-brand{' ' + extra if extra else ''}'>{_logo()}"
            f"<span class='pt-brand-name'>{html.escape(APP_NAME)}</span></div>")


def _logo_title(text):
    """A sign-in screen's (or a page shown before signing in) title with the
    logo before it."""
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        st.html(_logo("lg"), width="content")
        st.title(text, anchor=False, width="stretch")


PAGE_LABELS = {"AI Assistant": f"Ask {GUIDE}", "Clients": "Your clients"}
TICKER_PAGE = "Ticker"   # one ticker's own page (views/ticker_detail.py; ?page=ticker&t=VTI)
TICKER_RE = re.compile(r"[A-Z0-9][A-Z0-9.\-^=]{0,14}")   # what ?t= may hold


def _open_ticker(sym, came_from):
    """A row on Home or the Watchlist: that ticker's own page, with Back to
    `came_from` (a button's callback, or the old open-ticker state)."""
    st.session_state["ticker_sym"] = sym
    st.session_state["ticker_from"] = came_from
    st.session_state["page"] = TICKER_PAGE


def _label(page):
    return PAGE_LABELS.get(page, page)


SAGE_AVATAR = ":material/explore:"   # a compass, for the guide's chat messages


def _avatar(role):
    return SAGE_AVATAR if role == "assistant" else None


LIVE_EVERY_SEC = 60  # how often an open page checks for new prices (live_prices.py)


def _dialog_closed():
    """A dialog's X or Escape: live prices may redraw the page again (they
    wait while a dialog is open, since a redraw would close it)."""
    st.session_state["dialog_open"] = False


# up / down text colors with AA contrast on each theme (as --pt-up / --pt-down)
SIGN_COLORS = {"light": ("#15803d", "#b91c1c"), "dark": ("#4ade80", "#f87171")}

st.set_page_config(page_title=APP_NAME + (" (staging)" if STAGING else ""),
                   page_icon=APP_ICON, layout="wide",
                   initial_sidebar_state="auto")

# App-wide styles: hide Streamlit's own running/deploy widgets, tighten the
# page on phones, and the classes used by the hero, stat tiles, and
# allocation bars below. Text inherits the theme's colors; only marks and
# gain/loss figures carry their own.
st.html("""<style>
/* The Northwend design system's colors for the app's own pieces, per theme
   (the rest is in .streamlit/config.toml); ui_enhancements.js marks the theme
   on the page root. up / down / warning pass WCAG AA (4.5:1) as text; compass
   is the brand blue for bars and marks; line a hairline; line-strong the edge
   of a control (3:1); sunken the track behind a bar; ink-muted quieter
   text that still passes AA. */
:root { --pt-up: #15803d; --pt-down: #b91c1c; --pt-warn: #a16207; --pt-compass: #2a78d6;
  --pt-line: #d5dde5; --pt-line-strong: #74838f; --pt-sunken: #e8eef4; --pt-dawn-soft: #fbebc9;
  --pt-link: #1d5fae; --pt-compass-soft: #e3eefb; --pt-dawn: #f0b23c; --pt-ink-muted: #4d5d6c; }
:root[data-pt-theme="dark"] { --pt-up: #4ade80; --pt-down: #f87171; --pt-warn: #fbbf24;
  --pt-compass: #3987e5; --pt-line: #2a3847; --pt-line-strong: #62748a; --pt-sunken: #1c2a38;
  --pt-dawn-soft: #3a2f17; --pt-link: #7cb3f2; --pt-compass-soft: #16304d; --pt-dawn: #f2bd57;
  --pt-ink-muted: #9eadbb; }
/* the advisor app's role chip, and the bar shown while inside a client's account */
.pt-role { color: var(--pt-link); background: var(--pt-compass-soft); border-color: transparent;
  margin: -.4rem 0 .4rem; }
.st-key-pt_viewing { background: var(--pt-compass-soft); border-color: var(--pt-compass) !important; }
/* Your route (the investor home, route.py): waypoint dots heading to the goal */
.pt-route-label { font-size: .75rem; font-weight: 600; letter-spacing: .02em; opacity: .75;
  margin-bottom: .35rem; }
.pt-route { display: flex; align-items: center; margin: .9rem 0 .2rem; }
.pt-dot { width: 12px; height: 12px; border-radius: 999px; border: 2px solid var(--pt-line-strong);
  flex: none; box-sizing: border-box; }
.pt-dot-done { background: var(--pt-compass); border-color: var(--pt-compass); }
.pt-dot-here { width: 20px; height: 20px; background: var(--pt-compass-soft); border: 4px solid var(--pt-compass); }
.pt-dot-goal, .pt-dot-goal_reached { width: 20px; height: 20px; border: 2px solid currentColor; }
.pt-dot-goal_reached { background: var(--pt-dawn); }
.pt-leg { height: 2px; flex: 1 1 0; max-width: 56px; min-width: 10px; background: var(--pt-line-strong); }
.pt-leg-done { background: var(--pt-compass); }
.st-key-pt_route_reached { background: var(--pt-dawn-soft); border-color: var(--pt-dawn) !important; }
/* Find your direction (Get started): the investor type */
.st-key-pt_direction { border-color: var(--pt-compass) !important; }
.pt-type-name { font-family: Newsreader, Georgia, serif; font-size: 1.75rem; line-height: 1.2;
  font-weight: 500; }
.pt-type-line { opacity: .75; margin-top: .15rem; }
/* the staging app's banner (STAGING): text in the theme's own color */
.pt-staging { background: var(--pt-dawn-soft); border: 1px solid var(--pt-warn); border-radius: .5rem;
  padding: .5rem .9rem; font-size: .9rem; font-weight: 600; }
/* Newsreader is for page and section titles only; card headings (h4 and
   smaller) stay in the text face, Figtree */
h4, h5, h6 { font-family: Figtree, "Segoe UI", system-ui, sans-serif !important; }
/* Controls people must find get the stronger edge (3:1); the theme's
   borderColor stays the hairline for cards and expanders. Focused fields and
   selected pills keep Streamlit's own primary-colored edge. */
[data-testid="stTextInputRootElement"]:not(:focus-within),
[data-testid="stTextAreaRootElement"]:not(:focus-within),
[data-testid="stNumberInputContainer"]:not(:focus-within),
[data-testid="stDateInputField"]:not(:focus-within),
[data-testid="stSelectbox"] [data-baseweb="select"] > div:not(:focus-within),
[data-testid="stMultiSelect"] [data-baseweb="select"] > div:not(:focus-within),
[data-testid^="stBaseButton-secondary"]:not(:hover):not(:focus-visible),
[data-testid="stButtonGroup"] button[aria-checked="false"]:not(:hover):not(:focus-visible) {
  border-color: var(--pt-line-strong) !important; }
/* dark: the selected tab, segment or pill, and a slider's value, are labelled
   in the link blue - the theme's primary blue reads only 3.9:1 as text on the
   dark page */
:root[data-pt-theme="dark"] [data-testid="stButtonGroup"] button[aria-checked="true"],
:root[data-pt-theme="dark"] [data-testid="stTab"][aria-selected="true"],
:root[data-pt-theme="dark"] [data-testid="stSliderThumbValue"] {
  color: var(--pt-link); }
/* captions: Streamlit fades the whole caption to 60%, which left its text
   under AA on the light theme (4.0:1) and a link in it (the Learn more lines)
   too faint on the dark one (3.8:1); fade only the text, a little less, so
   it passes on both and a link keeps its full color */
[data-testid="stCaptionContainer"] { opacity: 1;
  color: color-mix(in srgb, currentColor 70%, transparent); }
/* a slider's min and max labels: Streamlit fades them to 60%, under AA on
   the light theme (4.0:1); the design system's muted text passes on both */
[data-testid="stSlider"]:not(:has([role="slider"][aria-disabled="true"])) [data-testid="stSliderTickBar"] {
  color: var(--pt-ink-muted); }
/* the expedition (ROADMAP T1): faint contour lines behind every page, drawn in
   static/topo-light.svg and topo-dark.svg, one step above the page colour */
[data-testid="stMain"] { background-repeat: no-repeat;
  background-position: right -220px top -40px; background-size: 1400px auto; }
/* movement (ROADMAP T2; ui_enhancements.js adds the classes): a new page fades
   in (opacity only - a transform would unpin the phone tab bar for a moment),
   and the trail draws itself forward when a waypoint is reached */
.pt-page-enter { animation: pt-page-in .35s ease-out; }
@keyframes pt-page-in { from { opacity: 0; } to { opacity: 1; } }
.pt-trail-advance { animation: pt-trail-draw .9s ease-out; }
@keyframes pt-trail-draw { from { clip-path: inset(0 100% 0 0); } to { clip-path: inset(0 0 0 0); } }
/* milestones and gear (views/kit.py, gear.py): icon tiles, earned ones in dawn */
.pt-gear-row { display: flex; flex-wrap: wrap; gap: 10px 8px; margin: .6rem 0 .45rem !important;
  padding: 0 !important; list-style: none; }
.pt-gear-cell { width: 64px; margin: 0 !important; padding: 0; display: flex; flex-direction: column;
  align-items: center; gap: 4px; }
.pt-gear-label { font-size: .72rem; line-height: 1.2; text-align: center; color: var(--pt-ink-muted); }
.pt-gear-tile { width: 40px; height: 40px; border-radius: 10px; display: inline-flex; flex: none;
  align-items: center; justify-content: center; border: 1px dashed var(--pt-line-strong); }
.pt-gear-earned { border: 0; background: var(--pt-dawn-soft); }
/* the kit window: one row per piece - what it's for, how it's earned */
.pt-gear-item { display: flex; gap: .8rem; align-items: flex-start; }
.pt-gear-head { display: flex; flex-wrap: wrap; align-items: center; gap: .3rem .5rem;
  margin-bottom: .15rem; }
.pt-gear-how { font-size: .85rem; color: var(--pt-ink-muted); margin-top: .15rem; }
.pt-gear-why { color: var(--pt-ink-muted); }
.pt-gear-chip { display: inline-block; padding: .05rem .55rem; border-radius: 999px;
  font-size: .75rem; font-weight: 600; color: var(--pt-ink-muted);
  border: 1px dashed var(--pt-line-strong); }
.pt-gear-chip-earned { color: inherit; background: var(--pt-dawn-soft); border: 1px solid var(--pt-dawn); }
.pt-milestone { display: flex; flex-direction: column; gap: .5rem; align-items: flex-start; }
.pt-milestone-badge { width: 76px; height: 76px; border-radius: 999px; background: var(--pt-dawn-soft);
  display: flex; align-items: center; justify-content: center; margin-bottom: .3rem; }
.pt-milestone-title { font-family: Newsreader, Georgia, serif; font-size: 1.6rem; line-height: 1.2;
  font-weight: 500; }
/* storms (views/kit.py render_weather): a calm note, a cool rain edge */
.st-key-pt_storm { border-left: 3px solid var(--pt-compass) !important; }
.pt-storm-title { font-family: Newsreader, Georgia, serif; font-size: 1.3rem; font-weight: 500;
  margin: .1rem 0 .3rem; }
.pt-storm-table { width: 100%; border-collapse: collapse; font-size: .92rem; }
.pt-storm-table th { text-align: left; font-weight: 600; opacity: .75; padding: .3rem .4rem; }
.pt-storm-table td { padding: .35rem .4rem; border-top: 1px solid var(--pt-line); }
/* notes to future you (views/future_notes.py): the person's own words, quoted */
.pt-fnote { border-left: 3px solid var(--pt-dawn); padding: .1rem 0 .1rem .7rem;
  font-family: Newsreader, Georgia, serif; font-style: italic; font-size: 1.05rem;
  white-space: pre-wrap; overflow-wrap: anywhere; }
.pt-fnote-when { font-size: .8rem; opacity: .75; margin: .2rem 0 0 .85rem; }
.pt-fnote-storm { margin-top: .6rem; padding: .5rem .8rem; border-radius: .5rem;
  background: var(--pt-dawn-soft); overflow-wrap: anywhere; }
.pt-fnote-head { font-weight: 600; margin-top: .45rem; }
/* the trail is two images, one per theme; show the one that matches */
:root[data-pt-theme="dark"] .pt-on-light, :root:not([data-pt-theme="dark"]) .pt-on-dark {
  display: none; }
/* the route as a trail (route.trail_html), and the map plate above a title */
.pt-trail { display: block; width: 100%; max-width: 760px; height: auto; margin: .6rem 0 .1rem; }
.pt-region { font-size: .85rem; opacity: .8; margin: 0 0 .2rem; }
.pt-checks-title { font-weight: 600; font-size: .95rem; }
[class*="st-key-pt_check_"] { border-top: 1px solid var(--pt-line); padding-top: .5rem; }
.pt-region b { font-family: Newsreader, Georgia, serif; font-style: italic; font-weight: 500;
  font-size: 1rem; opacity: 1; }
.pt-eyebrow { font-family: Newsreader, Georgia, serif; font-style: italic; font-size: 1rem;
  opacity: .78; margin: 0 0 -1.1rem; }
/* the hide-amounts eye beside the title: a finger-sized tap target on phones */
.st-key-pt_hide button { min-width: 44px; min-height: 44px; justify-content: center; }
/* first steps (views/first_steps.py): progress dots, and each screen slides in */
.pt-fs-dots { display: flex; gap: 6px; margin: 0 0 .25rem; }
.pt-fs-dot { flex: 1 1 0; height: 5px; border-radius: 3px; background: var(--pt-sunken);
  transition: background .3s ease; }
.pt-fs-dot-on { background: var(--pt-compass); }
.pt-fs-dot-at { outline: 2px solid var(--pt-compass); outline-offset: 1px; }
/* Learn (views/get_started.py): how far along the route, one segment per
   waypoint - complete ones filled, the open one outlined - and each
   waypoint's one line about why it matters */
.pt-steps { margin: 0 0 .4rem; }
.pt-steps-top { display: flex; justify-content: space-between; align-items: baseline;
  gap: .5rem; font-size: .95rem; margin-bottom: .35rem; }
.pt-steps-top span { font-size: .85rem; color: var(--pt-ink-muted); font-variant-numeric: tabular-nums; }
.pt-steps-bar { display: flex; gap: 4px; }
.pt-steps-seg { flex: 1 1 0; height: 10px; border-radius: 5px; background: var(--pt-sunken);
  box-shadow: inset 0 0 0 1px var(--pt-line); transition: background .3s ease; }
.pt-steps-done { background: var(--pt-compass); box-shadow: none; }
.pt-steps-at { outline: 2px solid var(--pt-compass); outline-offset: 2px; }
.pt-why { font-family: Newsreader, Georgia, serif; font-style: italic; font-size: 1.08rem;
  line-height: 1.4; margin: -.35rem 0 .35rem; }
.st-key-pt_gs_nav button p { font-size: .9rem; }
[class*="st-key-pt_slide_"] { animation: pt-slide-in .35s ease-out both; }
/* a chosen answer in a slide (first steps, Learn's waypoints) reads as chosen
   at a glance: a check, a firmer edge and bold, not just a pale tint */
[class*="st-key-pt_slide_"] button[data-variant="pills"][data-selected="true"] {
  border: 2px solid var(--pt-compass) !important; background: var(--pt-compass-soft) !important;
  color: var(--pt-link) !important; font-weight: 600; }
[class*="st-key-pt_slide_"] button[data-variant="pills"][data-selected="true"]::before {
  content: "\\2713"; margin-right: .35rem; font-weight: 700; }
/* just signed up: the one line about the email link, its Send it again a
   small link-sized button rather than a full row of its own */
.st-key-pt_email_brief { row-gap: 0 !important; }
.st-key-pt_email_brief button { min-height: 0; padding: 0; }
.st-key-pt_email_brief button p { font-size: .85rem; }
/* phones: first steps' Back / Next stay in reach at the bottom of the screen
   (the tab bar steps aside while they're open - render_first_steps) */
@media (max-width: 640px) {
  /* the row sits in a wrapper just its own size, so the wrapper is what sticks */
  div:has(> .st-key-pt_fs_nav) { position: sticky; bottom: 0; z-index: 20; }
  .st-key-pt_fs_nav { background: var(--pt-bg, transparent);
    padding: .5rem 0 calc(.5rem + env(safe-area-inset-bottom)); border-top: 1px solid var(--pt-line); }
}
@keyframes pt-slide-in { from { opacity: 0; transform: translateX(18px); }
  to { opacity: 1; transform: none; } }
/* read by screen readers, not shown */
.pt-sr { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: .01ms !important;
    transition-duration: .01ms !important; } }
[data-testid="stStatusWidget"], [data-testid="stAppDeployButton"], .stAppDeployButton {
  display: none !important; }
/* room for the menu: pinned down the left side on a laptop (13.5rem wide),
   along the top on a phone (below) */
[data-testid="stMainBlockContainer"] { padding-top: 3.5rem; }
@media (min-width: 641px) {
  [data-testid="stMain"]:has(.st-key-pt_menu) { margin-left: 13.5rem;
    width: calc(100% - 13.5rem); } }
/* the pinned menus, and a script with nothing to show (ui_enhancements.js,
   the sign-in cookie), take no room in the page's own column */
[data-testid="stLayoutWrapper"]:has(> .st-key-pt_menu),
[data-testid="stLayoutWrapper"]:has(> .st-key-pt_menu_foot),
[data-testid="stLayoutWrapper"]:has(> .st-key-pt_tabbar) { display: contents; }
[data-testid="stElementContainer"]:has(> [data-testid="stHtml"] > script:only-child) {
  display: none; }
/* a slider's end label can poke past a phone's edge; never scroll sideways */
[data-testid="stMain"] { overflow-x: hidden; }
/* a table's own "Download as CSV" writes each cell as it is, so a name typed
   like a formula would run in a spreadsheet: the app's Download CSV buttons
   (export.csv_bytes) are the safe way, and this one is left out */
[data-testid="stElementToolbarButton"]:has(button[aria-label="Download as CSV"]) {
  display: none !important; }
/* phones and touch screens: the charts' and tables' small (22px) toolbars are
   too small to tap and get in the way of scrolling, so they're left out */
@media (max-width: 640px), (pointer: coarse) {
  [data-testid="stElementToolbar"] { display: none !important; } }
@media (max-width: 640px) {
  [data-testid="stMainBlockContainer"] { padding: 4.75rem 1rem 6rem; }
  h1 { font-size: 1.6rem !important; }
  /* a ticker's stats (_stat_tiles): two per line, not one long column */
  .st-key-pt_stat_tiles [data-testid="stColumn"] { min-width: calc(50% - 8px) !important; }
  .st-key-pt_stat_tiles [data-testid="stColumn"]:not(:has([data-testid="stElementContainer"])) {
    display: none; }
  /* tabs (Plan's) wrap onto a second line instead of scrolling sideways
     behind Streamlit's arrow */
  [data-testid="stTabs"] [role="tablist"] { flex-wrap: wrap; overflow-x: visible; row-gap: .25rem; }
  [data-testid="stTabsScrollLeft"], [data-testid="stTabsScrollRight"] { display: none !important; }
  /* the paste / type window (holdings_input.py): shorter on a phone - a
     holding is a plain group inside its account's card (no box of its own),
     its number of shares and what was paid share one line, without the
     +/- steppers (the phone's own number keys do that) */
  [class*="st-key-pt_me_hold_"] { border: 0 !important; padding: 0 !important;
    border-top: 1px solid var(--pt-line) !important; border-radius: 0 !important;
    padding-top: .6rem !important; }
  [class*="st-key-pt_me_row_"] { row-gap: .4rem !important; }
  [class*="st-key-pt_me_row_"] > [data-testid="stElementContainer"]:has([data-testid="stTextInput"]) {
    flex: 1 1 calc(100% - 3rem) !important; width: auto !important; }
  [class*="st-key-pt_me_row_"] > [data-testid="stElementContainer"]:has([data-testid="stNumberInput"]) {
    flex: 1 1 calc(50% - .5rem) !important; width: auto !important; min-width: 0 !important; }
  [class*="st-key-pt_me_row_"] [data-testid="stNumberInputStepDown"],
  [class*="st-key-pt_me_row_"] [data-testid="stNumberInputStepUp"] { display: none !important; }
}
/* the menu (_render_menu): on a laptop a column pinned down the left side
   of the window, on the page's own background (--pt-bg, kept in step with
   light/dark by ui_enhancements.js) - the brand, every item, then at its
   foot the route's progress, + Add holdings and the name menu. Streamlit's
   header strip stays above the page, see-through, so its three-dot menu
   sits at the top right. On a phone (below) it slims to a bar along the top. */
[data-testid="stHeader"] { background: transparent; }
[data-testid="stHeader"], [data-testid="stHeader"] * { pointer-events: none; }
[data-testid="stHeader"] [data-testid="stMainMenu"],
[data-testid="stHeader"] [data-testid="stMainMenu"] * { pointer-events: auto; }
.st-key-pt_menu { position: fixed; top: 0; bottom: 0; left: 0; z-index: 999980;
  width: 13.5rem; box-sizing: border-box; padding: 1.25rem .75rem 1rem;
  flex-direction: column !important; flex-wrap: nowrap !important;
  align-items: stretch !important; gap: .2rem !important;
  overflow-y: auto; overflow-x: hidden; scrollbar-width: thin;
  background: var(--pt-bg, #f5f7f9); border-right: 1px solid var(--pt-line); }
.st-key-pt_menu > div, .st-key-pt_menu_foot > div { flex: none; width: 100% !important; }
.pt-brand { display: flex; align-items: center; gap: .5rem; margin: 0 .5rem 1.1rem;
  white-space: nowrap; font-family: Newsreader, Georgia, serif; font-size: 1.35rem;
  font-weight: 500; line-height: 1; }
/* the small brand line over a page shown without signing in */
.pt-brand.pt-brand-line { margin: 0 0 .5rem; font-size: 1.1rem; }
/* the logo (_logo): one image per theme (.pt-on-light / .pt-on-dark), a
   little larger beside a sign-in title */
.pt-logo { display: block; flex: none; width: 1.75rem; height: 1.75rem; }
.pt-logo.pt-logo-lg { width: 2.75rem; height: 2.75rem; }
/* the items: plain words, left-aligned, the full width of the column; the
   page showing reads in the link blue on a soft compass tint, bold (and
   aria-current, ui_enhancements.js); Money's tabs listed under it, indented */
.st-key-pt_menu [class*="st-key-nav"] .stButton,
.st-key-pt_menu [class*="st-key-nav"] button { width: 100%; }
.st-key-pt_menu [class*="st-key-nav"] button { min-height: 2.5rem; padding: .45rem .75rem;
  justify-content: flex-start; border: 0; border-radius: .5rem; font-weight: 500; }
.st-key-pt_menu [class*="st-key-nav"] button > div { justify-content: flex-start; text-align: left; }
.st-key-pt_menu [class*="st-key-navsub_"] button { min-height: 2.1rem; padding-left: 1.75rem; }
.st-key-pt_menu [class*="st-key-nav"] button:hover { background: var(--pt-sunken); }
.st-key-pt_menu [class*="st-key-nav"] button[kind="primary"],
.st-key-pt_tabbar button[kind="primary"] {
  background: var(--pt-compass-soft) !important; color: var(--pt-link) !important;
  border-color: transparent !important; }
.st-key-pt_menu [class*="st-key-nav"] button[kind="primary"] p,
.st-key-pt_tabbar button[kind="primary"] p { font-weight: 600; }
/* the foot: the route's progress, + Add holdings and the name menu, at the
   bottom of the column */
.st-key-pt_menu_foot { flex: none !important; margin-top: auto; padding-top: 1rem;
  flex-direction: column !important;
  flex-wrap: nowrap !important; align-items: stretch !important; gap: .35rem !important; }
.pt-side-route { font-size: .82rem; color: var(--pt-ink-muted); padding: 0 .5rem; }
.pt-side-bar { height: 6px; border-radius: 3px; background: var(--pt-sunken); overflow: hidden;
  margin: .4rem 0 .1rem; }
.pt-side-bar span { display: block; height: 100%; background: var(--pt-compass); }
.st-key-side_route_next button { min-height: 0; padding: .1rem .5rem .5rem; text-align: left; }
.st-key-side_route_next button p { font-size: .82rem; color: var(--pt-link); }
.st-key-pt_menu_foot [data-testid="stPopover"],
.st-key-pt_menu_foot [data-testid="stPopoverButton"] { width: 100%; }
.st-key-pt_menu_foot [data-testid="stPopoverButton"] { justify-content: flex-start; }
.st-key-pt_menu [data-testid="stPopoverButton"] > div { gap: .3rem; }
/* their words in full (Streamlit would cut a menu button's words short) */
.st-key-pt_add [data-testid="stPopoverButton"] [data-testid="stMarkdownContainer"],
.st-key-pt_client_login [data-testid="stMarkdownContainer"] { min-width: max-content; }
/* the client's own Get started, in the viewing bar: marked as the items are */
.st-key-viewing_start button[kind="primary"] { background: var(--pt-compass-soft) !important;
  color: var(--pt-link) !important; border-color: var(--pt-compass) !important; }
/* an advisor's Viewing: says what it is, the account's name after it */
.st-key-viewing_select [role="group"] { background: transparent; }
.st-key-viewing_select [role="group"]::before { content: "Viewing"; align-self: center;
  padding-left: .7rem; font-size: .8rem; color: var(--pt-ink-muted); white-space: nowrap; }
.st-key-viewing_select [role="combobox"] { background: transparent; padding-left: .4rem;
  font-weight: 600; }
/* inside + Add holdings and the name menu: a list of rows, left-aligned and
   close together; the page showing marked as in the menu */
[data-testid="stPopoverBody"]:has(.st-key-menu_logout) [data-testid="stVerticalBlock"],
[data-testid="stPopoverBody"]:has(.st-key-add_manual) [data-testid="stVerticalBlock"] {
  gap: .3rem; }
[data-testid="stPopoverBody"]:has(.st-key-menu_logout) button,
[data-testid="stPopoverBody"]:has(.st-key-add_manual) button { padding: .45rem .6rem; }
[data-testid="stPopoverBody"]:has(.st-key-menu_logout) button > div,
[data-testid="stPopoverBody"]:has(.st-key-add_manual) button > div {
  justify-content: flex-start; text-align: left; }
[data-testid="stPopoverBody"]:has(.st-key-menu_logout) button:hover,
[data-testid="stPopoverBody"]:has(.st-key-add_manual) button:hover {
  background: var(--pt-sunken); }
[class*="st-key-menu_"] button[kind="primary"] { background: var(--pt-compass-soft) !important;
  color: var(--pt-link) !important; border-color: transparent !important; }
[class*="st-key-menu_"] button[kind="primary"] p { font-weight: 600; }
/* an open menu's button keeps readable words (Streamlit dims a plain one
   to a dark blue, hard to read on the dark theme) */
.st-key-pt_me [data-testid="stPopoverButton"][aria-expanded="true"],
.st-key-pt_client_login [data-testid="stPopoverButton"][aria-expanded="true"] {
  color: var(--pt-link); }
/* the name menu: a long name or email shortens with "..." */
.st-key-pt_me button [data-testid="stMarkdownContainer"] { min-width: 0; overflow: hidden; }
.st-key-pt_me button p { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
/* Money's tabs (Income, Activity, Watchlist; _money_tabs): words on a
   hairline, the one showing underlined in the compass blue */
.st-key-pt_money_tabs { gap: 1.5rem !important; border-bottom: 1px solid var(--pt-line);
  margin: -.5rem 0 .25rem; }
.st-key-pt_money_tabs button { min-height: 2.5rem; padding: .25rem .1rem; border: 0;
  border-bottom: 2px solid transparent; border-radius: 0; background: transparent !important;
  margin-bottom: -1px; }
.st-key-pt_money_tabs button:hover { color: var(--pt-link); }
.st-key-pt_money_tabs button[kind="primary"] { color: var(--pt-link) !important;
  border-bottom-color: var(--pt-compass) !important; }
.st-key-pt_money_tabs button[kind="primary"] p { font-weight: 600; }
/* phone tab bar (_render_tab_bar): pinned to the bottom on narrow screens,
   hidden on wider ones where the menu column holds the items. */
.st-key-pt_tabbar { display: none !important; }
/* the sign-up form's hidden field (_signup): people never see it, bots fill it in */
.st-key-signup_website { display: none !important; }
@media (max-width: 640px) {
  .st-key-pt_tabbar {
    display: flex !important; position: fixed; left: 0; right: 0; bottom: 0; z-index: 999990;
    justify-content: space-around; gap: 0 !important;
    padding: .3rem .25rem calc(.3rem + env(safe-area-inset-bottom));
    background: var(--pt-bg, #0d1620); border-top: 1px solid var(--pt-line);
  }
  .st-key-pt_tabbar > div { flex: 1 1 0; min-width: 0; }
  .st-key-pt_tabbar button {
    width: 100%; min-height: 3.1rem; padding: .15rem .1rem; border: none;
  }
  .st-key-pt_tabbar button p { font-size: .7rem; line-height: 1.15; text-align: center; }
  /* the icon on its own line, above the label */
  .st-key-pt_tabbar button p span[role="img"] {
    display: block !important; font-size: 1.4rem; line-height: 1.2; margin: 0 auto;
  }
  /* the menu slims to a bar along the top - the brand, + and the name's
     icon: the items are along the bottom */
  .st-key-pt_menu { bottom: auto; right: 0; width: auto; height: 3.25rem;
    padding: 0 3rem 0 1rem; flex-direction: row !important; align-items: center !important;
    gap: .25rem !important; overflow: hidden; border-right: 0;
    border-bottom: 1px solid var(--pt-line); }
  .st-key-pt_menu > div, .st-key-pt_menu_foot > div { width: auto !important; }
  .pt-brand { margin: 0 .5rem 0 0; }
  .st-key-pt_menu [class*="st-key-nav"],
  .st-key-pt_menu_foot > :not(.st-key-pt_add):not(.st-key-pt_me) { display: none !important; }
  .st-key-pt_menu_foot { width: auto !important; margin: 0 0 0 auto; padding-top: 0;
    flex-direction: row !important; align-items: center !important; }
  .st-key-pt_menu_foot [data-testid="stPopover"],
  .st-key-pt_menu_foot [data-testid="stPopoverButton"] { width: auto; }
  .st-key-pt_add button [data-testid="stMarkdownContainer"],
  .st-key-pt_me button [data-testid="stMarkdownContainer"] { display: none; }
  .st-key-pt_add button, .st-key-pt_me button { min-width: 2.75rem; padding: .3rem .55rem; }
  .pt-brand-compact .pt-brand-name { display: none; }
  .st-key-pt_menu [data-testid="stSelectbox"] { width: 9.5rem !important; }
  .st-key-viewing_select [role="group"]::before { content: none; }
}
/* The slim band pages in two parts (pt_page_layout: views/plan.py, _money_parts,
   views/get_started.py, life.py, assistant.py): the middle (pt_page_main)
   and a right-hand panel (pt_page_side) of about 19rem, white cards on the
   band's paler page. Up to 900px one column, the panel after the middle */
.st-key-pt_page_layout { align-items: flex-start; flex-wrap: nowrap !important; }
[data-testid="stLayoutWrapper"]:has(> .st-key-pt_page_main) {
  flex: 1 1 0 !important; min-width: 0; width: auto !important; }
[data-testid="stLayoutWrapper"]:has(> .st-key-pt_page_side) {
  flex: 0 0 19rem !important; width: 19rem !important; min-width: 0; }
.st-key-pt_page_side { padding: 1.1rem 1rem; }
.st-key-pt_page_side [data-testid="stVerticalBlock"][class*="st-key-pt_"] { border-radius: 12px; }
.st-key-pt_plan_goal, .st-key-pt_plan_tabs, .st-key-pt_money_card, .st-key-pt_page_side,
.st-key-pt_page_main [class*="st-key-pt_fnote_"] {
  background: #ffffff; border-color: transparent !important; border-radius: 16px;
  box-shadow: 0 12px 28px -6px #132a3e40; }
:root[data-pt-theme="dark"] .st-key-pt_plan_goal, :root[data-pt-theme="dark"] .st-key-pt_plan_tabs,
:root[data-pt-theme="dark"] .st-key-pt_money_card, :root[data-pt-theme="dark"] .st-key-pt_page_side,
:root[data-pt-theme="dark"] .st-key-pt_page_main [class*="st-key-pt_fnote_"] {
  background: #15212d; box-shadow: 0 12px 28px -6px #00000099; }
.st-key-pt_plan_goal, .st-key-pt_plan_tabs, .st-key-pt_money_card { padding: 1.1rem 1.4rem; }
.st-key-pt_plan_goal h4 { font-family: Newsreader, Georgia, serif !important;
  font-weight: 500 !important; font-size: 1.6rem !important; padding: 0; }
/* Plan's three tab groups as one rounded switch (the tabs inside each keep
   their own look) */
.st-key-pt_plan_tabs [data-testid="stTabs"]:not([data-testid="stTabs"] *) > div > [role="tablist"] {
  background: var(--pt-sunken); border-radius: 10px; padding: 4px; gap: 4px;
  width: fit-content; max-width: 100%; border: 0; box-shadow: none; }
.st-key-pt_plan_tabs [data-testid="stTabs"]:not([data-testid="stTabs"] *) > div > [role="tablist"] > [role="tab"] {
  border-radius: 8px; padding: .3rem 1rem; border: 0; }
.st-key-pt_plan_tabs [data-testid="stTabs"]:not([data-testid="stTabs"] *) > div > [role="tablist"]::after,
.st-key-pt_plan_tabs [data-testid="stTabs"]:not([data-testid="stTabs"] *) > div > [role="tablist"] > [role="tab"] > .react-aria-SelectionIndicator {
  display: none; }
.st-key-pt_plan_tabs [data-testid="stTabs"]:not([data-testid="stTabs"] *) > div > [role="tablist"] > [role="tab"][aria-selected="true"] {
  background: #ffffff; box-shadow: 0 1px 3px #132a3e26; }
:root[data-pt-theme="dark"] .st-key-pt_plan_tabs [data-testid="stTabs"]:not([data-testid="stTabs"] *) > div > [role="tablist"] > [role="tab"][aria-selected="true"] {
  background: #2a3847; }
/* Plan's mix on the right: kind, now and target in three columns */
.pt-pmix { display: grid; grid-template-columns: 1fr auto auto; gap: .3rem .9rem;
  font-size: .9rem; font-variant-numeric: tabular-nums; margin-bottom: .4rem; }
.pt-pmix-h { font-size: .75rem; font-weight: 600; color: var(--pt-ink-muted); }
/* Money's accounts and the year's income on the right */
.pt-acct-list { display: flex; flex-direction: column; gap: .45rem; }
.pt-acct-row { display: flex; justify-content: space-between; gap: .75rem; font-size: .9rem; }
.pt-acct-name { font-weight: 600; min-width: 0; overflow-wrap: anywhere; }
.pt-acct-val { font-variant-numeric: tabular-nums; white-space: nowrap; }
.pt-inc-bars { display: flex; align-items: flex-end; gap: 4px; height: 4.4rem; margin-bottom: .4rem; }
.pt-inc-bar { flex: 1; background: var(--pt-compass); border-radius: 3px; }
@media (max-width: 900px) {
  .st-key-pt_page_layout { flex-direction: column !important; align-items: stretch; }
  [data-testid="stLayoutWrapper"]:has(> .st-key-pt_page_main),
  [data-testid="stLayoutWrapper"]:has(> .st-key-pt_page_side) {
    flex: 0 0 auto !important; width: 100% !important; }
}
@media (max-width: 640px) {
  .st-key-pt_page_side { padding: .9rem .75rem; }
  .st-key-pt_plan_goal, .st-key-pt_plan_tabs, .st-key-pt_money_card { padding: .9rem .8rem; }
}
/* Life's cards (views/life.py): a small heading over the title */
.pt-life-small { font-size: .75rem; font-weight: 600; color: var(--pt-ink-muted); }
.pt-life-title { font-size: 1.1rem; font-weight: 600; margin-top: .15rem; }
.pt-status { font-size: .8rem; opacity: .75; margin-top: -.6rem; }
/* Learn, Life and Ask Northwend in the same two parts (views/get_started.py,
   life.py, assistant.py: pt_page_layout, pt_page_main and, on Learn and Ask,
   pt_page_side; Life is the middle alone). Their cards are white too */
.st-key-pt_gs_steps, .st-key-pt_gs_direction_line,
.st-key-pt_gs_common_points_line, .st-key-pt_page_main [class*="st-key-pt_slide_"],
.st-key-pt_page_main [class*="st-key-pt_life_"], .st-key-pt_ir, .st-key-pt_next_assistant,
.st-key-chat_suggest_box, .st-key-pt_page_main [data-testid="stExpander"] details,
.st-key-pt_page_main [data-testid="stChatMessage"] {
  background: #ffffff; border-color: transparent !important; border-radius: 16px;
  box-shadow: 0 12px 28px -6px #132a3e40; }
:root[data-pt-theme="dark"] :is(.st-key-pt_gs_steps,
  .st-key-pt_gs_direction_line, .st-key-pt_gs_common_points_line,
  .st-key-pt_page_main [class*="st-key-pt_slide_"], .st-key-pt_page_main [class*="st-key-pt_life_"],
  .st-key-pt_ir, .st-key-pt_next_assistant, .st-key-chat_suggest_box,
  .st-key-pt_page_main [data-testid="stExpander"] details,
  .st-key-pt_page_main [data-testid="stChatMessage"]) {
  background: #15212d; box-shadow: 0 12px 28px -6px #00000099; }
/* a window or a card's own expander inside a card keeps the plain look */
.st-key-pt_page_main [data-testid="stVerticalBlock"][class*="st-key-pt_"]:not(.st-key-pt_page_main):not(.st-key-pt_tf_grid) [data-testid="stExpander"] details {
  background: transparent; border-color: var(--pt-line) !important; border-radius: 8px;
  box-shadow: none; }
/* Life's changes (views/trail_forks.py): a grid of cards, an open one the whole row */
.st-key-pt_tf_grid { display: grid !important; grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: .75rem !important; align-items: start; }
.st-key-pt_tf_grid > * { width: auto !important; min-width: 0; }
.st-key-pt_tf_grid > :has(details[open]) { grid-column: 1 / -1; }
/* Ask Northwend: your own questions in a soft blue bubble on the right */
.st-key-pt_page_main [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
  background: var(--pt-compass-soft); box-shadow: none; margin-left: auto; max-width: 85%; }
:root[data-pt-theme="dark"] .st-key-pt_page_main [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
  background: var(--pt-compass-soft); box-shadow: none; }
.st-key-pt_page_main [class*="st-key-quick_"] button { border-radius: 9999px; }
.st-key-pt_page_main [data-testid="stChatInput"] > div { border-radius: 12px; }
.pt-ask-sees { margin: 0 0 .5rem; font-size: .9rem; color: var(--pt-ink-muted); }
.pt-ask-sees:last-child { margin-bottom: 0; }
@media (max-width: 900px) {
  .st-key-pt_tf_grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  .st-key-pt_tf_grid { grid-template-columns: minmax(0, 1fr); }
}
/* Home's band (_band_css; key pt_home_band, _page_header): the eyebrow,
   title, value, today's change and the status line in white on the navy,
   up and down in the dark theme's colors, signs and arrows kept. Tall enough
   that the first cards after it overlap the band's foot (it is 22.5rem from
   the top of the page, 18.5rem on a phone) */
.st-key-pt_home_band { min-height: 13.5rem; color: #ffffff; --pt-up: #4ade80;
  --pt-down: #f87171; --pt-link: #a9cdf7; }
.st-key-pt_home_band h1, .st-key-pt_home_band .pt-eyebrow, .st-key-pt_home_band .pt-hero,
.st-key-pt_home_band [data-testid="stCaptionContainer"],
.st-key-pt_home_band .st-key-pt_hide button { color: #ffffff !important; }
.st-key-pt_home_band [data-testid="stCaptionContainer"] a { color: var(--pt-link) !important; }
.st-key-pt_home_band .pt-hero-label, .st-key-pt_home_band .pt-hero-sub { opacity: .85; }
/* the slim band (key pt_page_band: Plan, Money, Learn, Life and Ask
   Northwend, _band_kind): Learn's eyebrow, the title, the line under it
   (_slim_band_line), the status line and Money's tabs in white on the navy */
.st-key-pt_page_band { min-height: 5.5rem; color: #ffffff; --pt-up: #4ade80;
  --pt-down: #f87171; --pt-link: #a9cdf7; }
.st-key-pt_page_band h1, .st-key-pt_page_band .pt-eyebrow,
.st-key-pt_page_band [data-testid="stCaptionContainer"],
.st-key-pt_page_band .st-key-pt_hide button,
.st-key-pt_page_band .st-key-pt_money_tabs button { color: #ffffff !important; }
.st-key-pt_page_band [data-testid="stCaptionContainer"] { opacity: .88; max-width: 46rem; }
.st-key-pt_page_band [data-testid="stCaptionContainer"] a { color: var(--pt-link) !important; }
.st-key-pt_page_band .st-key-pt_money_tabs { border-bottom-color: #ffffff33; }
.st-key-pt_page_band .st-key-pt_money_tabs button[kind="primary"] {
  border-bottom-color: #f0b23c !important; }
/* Home's cards (and those under the slim band): white (the theme's raised
   surface on dark), rounder, lifted off the page by a soft navy shadow
   instead of an edge */
[data-testid="stLayoutWrapper"]:has(> .st-key-pt_home_band) ~ [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"]:not(.st-key-pt_route_reached),
[data-testid="stLayoutWrapper"]:has(> .st-key-pt_home_band) ~ [data-testid="stElementContainer"] [data-testid="stExpander"] details,
[data-testid="stLayoutWrapper"]:has(> .st-key-pt_page_band) ~ [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"]:not(.st-key-pt_page_layout),
[data-testid="stLayoutWrapper"]:has(> .st-key-pt_page_band) ~ [data-testid="stElementContainer"] [data-testid="stExpander"] details {
  background: #ffffff; border-color: transparent !important; border-radius: 16px;
  box-shadow: 0 12px 28px -6px #132a3e40; }
:root[data-pt-theme="dark"] [data-testid="stLayoutWrapper"]:has(> .st-key-pt_home_band) ~ [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"]:not(.st-key-pt_route_reached),
:root[data-pt-theme="dark"] [data-testid="stLayoutWrapper"]:has(> .st-key-pt_home_band) ~ [data-testid="stElementContainer"] [data-testid="stExpander"] details,
:root[data-pt-theme="dark"] [data-testid="stLayoutWrapper"]:has(> .st-key-pt_page_band) ~ [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"]:not(.st-key-pt_page_layout),
:root[data-pt-theme="dark"] [data-testid="stLayoutWrapper"]:has(> .st-key-pt_page_band) ~ [data-testid="stElementContainer"] [data-testid="stExpander"] details {
  background: #15212d; box-shadow: 0 12px 28px -6px #00000099; }
/* Home in three parts (views/dashboard_page.py): the menu, the middle (the
   chart, the holdings list, the rest below) and This month on the right,
   about 19rem. Up to 900px wide: one column with This month first; on a
   phone its cards are one row that scrolls sideways inside itself. The
   parts' own wrappers are what sit in the row, so the widths go on them. */
.st-key-pt_home_layout { align-items: flex-start; flex-wrap: nowrap !important; }
[data-testid="stLayoutWrapper"]:has(> .st-key-pt_home_main) {
  flex: 1 1 0 !important; min-width: 0; width: auto !important; }
[data-testid="stLayoutWrapper"]:has(> .st-key-pt_home_side) {
  flex: 0 0 19rem !important; width: 19rem !important; min-width: 0; }
.st-key-pt_home_side { padding: 1.1rem 1rem; }
.st-key-pt_home_chart, .st-key-pt_home_list, .st-key-pt_home_side, .st-key-pt_progress_split,
.st-key-pt_home_main [data-testid="stExpander"] details {
  background: #ffffff; border-color: transparent !important; border-radius: 16px;
  box-shadow: 0 12px 28px -6px #132a3e40; }
:root[data-pt-theme="dark"] .st-key-pt_home_chart,
:root[data-pt-theme="dark"] .st-key-pt_progress_split,
:root[data-pt-theme="dark"] .st-key-pt_home_list,
:root[data-pt-theme="dark"] .st-key-pt_home_side,
:root[data-pt-theme="dark"] .st-key-pt_home_main [data-testid="stExpander"] details {
  background: #15212d; box-shadow: 0 12px 28px -6px #00000099; }
.pt-month-title { font-family: Newsreader, Georgia, serif; font-size: 1.4rem;
  font-weight: 500; line-height: 1.2; }
.pt-month-card-title { font-weight: 600; margin-bottom: .2rem; }
/* Today's minute: a deep blue top with the count and the week's marks */
.st-key-pt_minute { gap: .45rem; }
.pt-mm-head { background: #132a3e; color: #ffffff; border-radius: 12px;
  padding: .7rem .8rem .6rem; display: flex; flex-direction: column; gap: .45rem; }
.pt-mm-top { display: flex; justify-content: space-between; align-items: center;
  gap: .5rem; flex-wrap: wrap; }
.pt-mm-title { font-family: Newsreader, Georgia, serif; font-size: 1.2rem; font-weight: 500; }
.pt-mm-count { display: inline-flex; align-items: center; gap: .3rem; font-size: .85rem;
  font-weight: 600; color: #f2bd57; }
.pt-mm-marks { display: flex; gap: 5px; }
.pt-mm-mark { flex: 1; height: 6px; border-radius: 3px; background: #2c4660; }
.pt-mm-mark.pt-mm-done { background: #f0b23c; }
.pt-mm-mark.pt-mm-open { background: #4d6a86; }
.pt-mm-mark.pt-mm-today { background: #3987e5; }
.pt-mm-week { font-size: .75rem; color: #c9d6e2; }
.pt-mm-kind { font-size: .78rem; font-weight: 600; color: var(--pt-link); }
.pt-mm-next { font-size: .8rem; color: var(--pt-ink-muted); text-align: center; }
.st-key-pt_mm_note { background: var(--pt-sunken); border-color: transparent !important; }
/* Your wins (views/wins.py): the earned day, the name, the figure */
.pt-chip.pt-win-chip { color: inherit; background: var(--pt-dawn-soft); }
.pt-win-title { font-weight: 600; font-size: 1.05rem; margin-top: .35rem; }
.pt-win-num { font-weight: 700; font-size: 1.6rem; color: var(--pt-link);
  font-variant-numeric: tabular-nums; line-height: 1.25; }
.pt-win-head { margin-bottom: .15rem; }
/* each card in This month: a hairline edge; a card drawn inside an X / Done
   wrapper (pt_task_*) gives its edge to the wrapper. The cards after the
   first few (pt_month_more) stay hidden until Show N more opens them */
.st-key-pt_home_side [data-testid="stVerticalBlock"][class*="st-key-pt_"]:not([class*="st-key-pt_tfoot_"]):not(.st-key-pt_month_cards):not([class*="st-key-pt_month_more"]) {
  border-radius: 12px; position: relative; }
.st-key-pt_home_side [class*="st-key-pt_task_"] { border: 1px solid var(--pt-line);
  padding: .8rem .9rem .3rem; gap: .25rem; }
.st-key-pt_home_side [class*="st-key-pt_task_"] > [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"] {
  border: 0 !important; padding: 0 !important; background: transparent !important;
  box-shadow: none !important; }
.st-key-pt_home_side .st-key-pt_walk { background: var(--pt-compass-soft);
  border-color: var(--pt-compass) !important; }
.st-key-pt_month_more { display: none !important; }
[class*="st-key-pt_tfoot_"] button { min-height: 2rem; padding: 0 .4rem; }
/* the small X at a card's top right (put it away until its period ends):
   the card's first line keeps clear of it */
.st-key-pt_home_side :is([class*="st-key-task_away_"], .st-key-ss_later, .st-key-wk_later,
  .st-key-walk_skip, .st-key-year_card_later, .st-key-amap_nudge_off, .st-key-storm_hide) {
  position: absolute; top: .3rem; right: .3rem; width: auto !important; z-index: 2; }
.st-key-pt_home_side :is([class*="st-key-task_away_"], .st-key-ss_later, .st-key-wk_later,
  .st-key-walk_skip, .st-key-year_card_later, .st-key-amap_nudge_off, .st-key-storm_hide) button {
  min-height: 1.9rem; min-width: 1.9rem; padding: 0; color: var(--pt-ink-muted); }
.st-key-pt_home_side :is([class*="st-key-task_away_"], .st-key-ss_later, .st-key-wk_later,
  .st-key-walk_skip, .st-key-year_card_later, .st-key-amap_nudge_off, .st-key-storm_hide)
  + * { padding-right: 1.6rem; }
/* Home's holdings: one table under a title row (search, Columns) and a foot
   row (Show all, Download CSV) */
.st-key-pt_hold_head, .st-key-pt_hold_foot { flex-wrap: wrap; }
.st-key-pt_hold_foot [data-testid="stCaptionContainer"] { min-width: 10rem; }
/* a long read in a window (a season, the week, a drill): about 65 characters a line */
.st-key-pt_ss_read, .st-key-pt_wk_read, .st-key-pt_drill_read { max-width: 40rem;
  margin: 0 auto; line-height: 1.6; }
.st-key-pt_ss_read h3, .st-key-pt_wk_read h3, .st-key-pt_drill_read h3 {
  font-family: Newsreader, Georgia, serif !important; font-weight: 500 !important; }
/* a ticker's page (views/ticker_detail.py): Back, its name and where it is
   on the slim band */
.st-key-pt_page_band .st-key-ticker_back button { color: #ffffff !important; padding-left: 0;
  min-height: 2rem; }
.pt-tk-name { font-size: 1.05rem; font-weight: 600; color: #ffffff; }
.pt-tk-kind { font-size: .8rem; color: #ffffff; opacity: .8; }
@media (max-width: 900px) {
  .st-key-pt_home_layout { flex-direction: column !important; align-items: stretch; }
  [data-testid="stLayoutWrapper"]:has(> .st-key-pt_home_main),
  [data-testid="stLayoutWrapper"]:has(> .st-key-pt_home_side) {
    flex: 0 0 auto !important; width: 100% !important; }
  [data-testid="stLayoutWrapper"]:has(> .st-key-pt_home_side) { order: -1; }
}
@media (max-width: 640px) {
  .st-key-pt_home_side { padding: .9rem .75rem; }
  .st-key-pt_month_cards { flex-direction: row !important; flex-wrap: nowrap !important;
    align-items: flex-start; overflow-x: auto; scroll-snap-type: x proximity;
    padding-bottom: .4rem; }
  .st-key-pt_month_more_open { flex-direction: row !important; flex-wrap: nowrap !important;
    align-items: flex-start; overflow-x: auto; scroll-snap-type: x proximity;
    padding-bottom: .4rem; }
  .st-key-pt_month_cards > *, .st-key-pt_month_more_open > * {
    flex: 0 0 min(16.5rem, 78vw) !important;
    width: min(16.5rem, 78vw) !important; scroll-snap-align: start;
    max-height: 22rem; overflow-y: auto; }
}
.pt-hero-label { font-size: .85rem; opacity: .7; }
.pt-hero-value { font-size: 2.6rem; font-weight: 700; line-height: 1.15;
  font-variant-numeric: tabular-nums; }
.pt-hero-delta { font-size: 1rem; font-weight: 600; margin-top: .15rem; }
.pt-hero-sub { font-size: .8rem; opacity: .75; margin-top: .2rem; }
.pt-up { color: var(--pt-up); } .pt-down { color: var(--pt-down); }
.pt-live { color: var(--pt-up); }
.pt-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: .6rem; margin-top: 1rem; }
/* exactly four boxes (Home with a total return beside the price change):
   one row of four, two rows of two on a phone - never three and a lone one */
.pt-stats:has(> .pt-stat:nth-child(4):last-child) {
  grid-template-columns: repeat(4, minmax(0, 1fr)); }
.pt-stat { border: 1px solid var(--pt-line); border-radius: .5rem;
  padding: .55rem .7rem; min-width: 0; }
.pt-stat-label { font-size: .75rem; opacity: .7; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
.pt-stat-value { font-size: 1.1rem; font-weight: 600; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; font-variant-numeric: tabular-nums; }
.pt-stat-sub { font-size: .8rem; font-weight: 600; white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; }
/* phones: three boxes in a row leave about 90px each, so a label or note
   wraps onto a second line instead of running into the next box. A value's
   size follows its box (cqi, a share of the box's width; .75rem to .9rem),
   which fits $1,234,567.00 in a 113px box, and a longer amount or a narrower
   box wraps after a thousands comma (_stat_row marks those spots) rather
   than being cut off */
@media (max-width: 640px) { .pt-hero-value { font-size: 2.2rem; }
  .pt-stat { padding: .5rem .5rem; container-type: inline-size; }
  .pt-stat-value { font-size: .9rem; font-size: clamp(.75rem, 14cqi, .9rem);
    white-space: normal; line-height: 1.3; }
  .pt-stat-label, .pt-stat-sub { white-space: normal; overflow-wrap: break-word; }
  .pt-stats:has(> .pt-stat:nth-child(4):last-child) {
    grid-template-columns: repeat(2, minmax(0, 1fr)); } }
/* summary tiles that open a window (Learn the basics; Income, Activity,
   Watchlist and Ask Northwend in the calm view): lift a little on hover */
[class*="st-key-pt_tile_"] { transition: border-color .2s ease, transform .2s ease; }
[class*="st-key-pt_tile_"]:hover { border-color: var(--pt-compass) !important;
  transform: translateY(-2px); }
.pt-alloc-title { font-size: .9rem; font-weight: 600; margin-bottom: .35rem; }
.pt-alloc-bar { display: flex; gap: 2px; height: 14px; border-radius: 4px;
  overflow: hidden; margin-bottom: .6rem; }
.pt-alloc-seg { height: 100%; min-width: 3px; }
/* the legend's one column never grows past its card (a grid track sizes to
   its widest line otherwise); a long label wraps, and the percentage and
   amount keep their place at the right, top-aligned with the label */
.pt-legend { display: grid; grid-template-columns: minmax(0, 1fr); gap: .3rem;
  margin-bottom: .75rem; }
.pt-legend-row { display: flex; align-items: flex-start; gap: .5rem; font-size: .9rem;
  line-height: 1.4; min-width: 0; }
.pt-swatch { width: 10px; height: 10px; border-radius: 3px; flex: none; margin-top: .35em; }
.pt-legend-label { flex: 1 1 auto; min-width: 0; overflow-wrap: anywhere; }
.pt-legend-pct { flex: none; font-weight: 600; font-variant-numeric: tabular-nums; }
.pt-legend-val { flex: none; opacity: .75; font-variant-numeric: tabular-nums; min-width: 5.5rem;
  text-align: right; }
.pt-acct { margin-bottom: .8rem; }
.pt-acct .pt-legend-row { margin-bottom: .3rem; }
.pt-alloc-bar.pt-mini { height: 8px; margin-bottom: 0; }
.pt-warn { color: var(--pt-warn); } .pt-muted { opacity: .7; }
/* a goal with nothing invested yet: a calm compass chip, not a red "Behind" */
.pt-chip.pt-start { color: var(--pt-link); background: var(--pt-compass-soft);
  border-color: transparent; }
.pt-chip { display: inline-block; padding: .1rem .6rem; border-radius: 999px; font-size: .8rem;
  font-weight: 600; border: 1px solid currentColor; }
.pt-goal-top { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; }
.pt-goal-pct { font-weight: 600; }
.pt-goal-track { height: 10px; border-radius: 5px; background: var(--pt-sunken);
  overflow: hidden; margin: .5rem 0 .4rem; }
.pt-goal-fill { height: 100%; border-radius: 5px; background: var(--pt-compass); }
.pt-goal-sub { font-size: .8rem; opacity: .7; }
.pt-mix-track { position: relative; height: 8px; border-radius: 4px;
  background: var(--pt-sunken); margin: 0 0 .6rem; }
.pt-mix-fill { height: 100%; border-radius: 4px; background: var(--pt-compass); }
.pt-mix-target { position: absolute; top: -3px; width: 3px; height: 14px; border-radius: 1px;
  margin-left: -1px; background: currentColor; }
</style>""")


@functools.lru_cache(maxsize=1)
def _topo_css() -> str:
    """The expedition's contour lines behind every page (ROADMAP T1), one
    drawing per theme, built into the stylesheet: Streamlit's static files
    are served as plain text, which browsers won't draw as a picture."""
    from urllib.parse import quote
    rules = []
    for theme, sel in (("light", ':root:not([data-pt-theme="dark"])'),
                       ("dark", ':root[data-pt-theme="dark"]')):
        with open(os.path.join(HERE, "static", f"topo-{theme}.svg"), encoding="utf-8") as fh:
            svg = quote(fh.read().strip(), safe=" =:/,.-#")
        rules.append(f'{sel} [data-testid="stMain"] {{ background-image: '
                     f'url("data:image/svg+xml,{svg}"); }}')
    return "<style>" + "\n".join(rules) + "</style>"


st.html(_topo_css())

# Home's deep blue band (the look the owner chose, "E2"): navy behind the top
# of Home's main area - the title, the value and today's change - with the
# dawn star at the upper right among a few faint dots, and two paper hills
# whose last edge falls into the page; the first cards overlap it. Colors per
# theme: (band, dots, star, near hill, far hill, page, shadow). The page under
# it is a little bluer than elsewhere, so Home's white cards stand out.
BAND_COLORS = {"light": ("#132a3e", "#4d6a86", "#f0b23c", "#1d3f62", "#245689", "#eef3f8",
                         "#0b1a2a"),
               "dark": ("#09121b", "#2a3847", "#f2bd57", "#15212d", "#1c2a38", "#0d1620",
                        "#000000")}


def _band_svgs(theme):
    """(hills, sky) drawings for Home's band: the hills (9rem tall) stretch to
    the main area's width, the sky (star and dots) keeps its shape."""
    band, dots, star, hill1, hill2, page, shade = BAND_COLORS[theme]
    hills = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1440 144' "
             "preserveAspectRatio='none'><defs><filter id='s' x='-5%' y='-60%' width='110%' "
             "height='220%'><feDropShadow dx='0' dy='-5' stdDeviation='6' "
             f"flood-color='{shade}' flood-opacity='.45'/></filter></defs>"
             "<path d='M0 44 C240 14 470 58 760 32 S1210 4 1440 28 L1440 144 L0 144 Z' "
             f"fill='{hill1}'/>"
             "<path d='M0 84 C260 60 560 98 870 76 S1270 54 1440 72 L1440 144 L0 144 Z' "
             f"fill='{hill2}' filter='url(#s)'/>"
             "<path d='M0 118 C330 100 700 130 1050 112 S1350 102 1440 108 L1440 144 "
             f"L0 144 Z' fill='{page}' filter='url(#s)'/></svg>")
    sky = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 260 200'>"
           f"<circle cx='190' cy='70' r='40' fill='{star}' fill-opacity='.10'/>"
           "<path d='M190 34 L197.5 62.5 L226 70 L197.5 77.5 L190 106 L182.5 77.5 L154 70 "
           f"L182.5 62.5 Z' fill='{star}'/>"
           + "".join(f"<circle cx='{x}' cy='{y}' r='{r}' fill='{dots}'/>"
                     for x, y, r in ((24, 46, 2), (78, 18, 1.6), (112, 104, 2.2),
                                     (246, 150, 1.8), (58, 140, 1.6), (140, 28, 1.4),
                                     (250, 16, 2), (16, 170, 1.4)))
           + "</svg>")
    return hills, sky


# Where the band is drawn: only on the main area of a page that opts in
# (_band_kind: Home's tall one, the slim one on Plan, Money, Learn, Life and Ask), and only once
# ui_enhancements.js has found the band's own container there (key
# pt_home_band or pt_page_band, made by _page_header) and marked the main area
# with data-pt-band ("home" / "slim") and where the band starts and ends
# (--pt-band-top, --pt-band-end). Anything above it (the staging note, a
# one-time agree box) stays on the page's own background; sign-in, every other
# page and every window never have it.
_BAND_ON = '[data-testid="stMainBlockContainer"][data-pt-band]'


@functools.lru_cache(maxsize=1)
def _band_css() -> str:
    """The band (Home's, and the slim one), built into its own stylesheet (like _topo_css): layers on
    the main area's background - the sky, the hills at the band's foot, and
    the navy from the band's top down behind the hills. No image is fetched.
    The words on it (white) and Home's cards are in the main stylesheet."""
    from urllib.parse import quote
    rules = []
    for theme, sel in (("light", ':root:not([data-pt-theme="dark"])'),
                       ("dark", ':root[data-pt-theme="dark"]')):
        hills, sky = (quote(s, safe=" =:/,.-") for s in _band_svgs(theme))
        navy, page = BAND_COLORS[theme][0], BAND_COLORS[theme][5]
        rules.append(f'{sel} [data-testid="stMain"]:has({_BAND_ON}) '
                     f"{{ background-color: {page}; }}")
        rules.append(f"{sel} {_BAND_ON} {{ background-image: "
                     f'url("data:image/svg+xml,{sky}"), url("data:image/svg+xml,{hills}"), '
                     f"linear-gradient({navy}, {navy}); }}")
    # --pt-band-end is where the band's last (page-colored) edge ends: 5rem
    # past its container when a card overlaps the foot, else at its foot
    # (ui_enhancements.js); the hills are its last 9rem, the navy above them
    # The star stays clear of the hide-amounts eye at the title's right: on a
    # laptop up beside the title, on a phone beside the value
    top, end = "var(--pt-band-top, 0px)", "var(--pt-band-end, 15rem)"
    start = "var(--pt-band-start, 3.5rem)"
    return ("<style>" + "\n".join(rules) + "\n"
            ".st-key-pt_home_band { padding-bottom: var(--pt-band-pad, 0px); }\n"
            f"{_BAND_ON} {{ background-repeat: no-repeat; "
            f"background-position: right 8rem top max({top}, calc({start} - 2.5rem)), "
            f"0 calc({end} - 9rem), 0 {top}; "
            f"background-size: 260px 200px, 100% 9rem, 100% calc({end} - {top} - 5rem); }}\n"
            f"@media (max-width: 640px) {{ {_BAND_ON} {{ "
            f"background-position: right -.75rem top calc({start} + 3.25rem), "
            f"0 calc({end} - 9rem), 0 {top}; background-size: 130px 100px, 100% 9rem, "
            f"100% calc({end} - {top} - 5rem); }} }}\n"
            # the slim band (Plan, Money, Learn, Life, Ask: key pt_page_band, data-pt-band="slim"):
            # the same layers, its hills 5.5rem (the navy reaches 3rem into
            # them, where its cards start) and a smaller star beside the title
            ".st-key-pt_page_band { padding-bottom: var(--pt-band-pad, 0px); }\n"
            f'{_BAND_ON}[data-pt-band="slim"] {{ '
            f"background-position: right 7rem top max({top}, calc({start} - 1.25rem)), "
            f"0 calc({end} - 5.5rem), 0 {top}; "
            f"background-size: 156px 120px, 100% 5.5rem, 100% calc({end} - {top} - 3rem); }}\n"
            f'@media (max-width: 640px) {{ {_BAND_ON}[data-pt-band="slim"] {{ '
            f"background-position: right 2.75rem top calc({start} - .75rem), "
            f"0 calc({end} - 5.5rem), 0 {top}; background-size: 104px 80px, 100% 5.5rem, "
            f"100% calc({end} - {top} - 3rem); }} }}\n"
            # (Learn's eyebrow runs the width of a phone: its star goes down
            # beside the title, which has no hide-amounts eye there)
            f'@media (max-width: 640px) {{ {_BAND_ON}[data-pt-band="slim"]'
            f":has(.st-key-pt_page_band .pt-eyebrow) {{ "
            f"background-position: right .25rem top calc({start} + .6rem), "
            f"0 calc({end} - 5.5rem), 0 {top}; }} }}\n"
            "</style>")


st.html(_band_css())

if STAGING:
    st.html("<div class='pt-staging' role='note'>Staging copy, for trying changes before "
            "they go live. Use test data only: this is not the real Northwend.</div>")

# The old address once the app has moved (hosting.MOVED_TO): only say where it is now.
if hosting.moved_to():
    _new = hosting.moved_link(hosting.moved_to(), st.query_params.to_dict())
    _, _mid, _ = st.columns([1, 1.4, 1])
    with _mid:
        _logo_title(f"{APP_NAME} has moved")
        st.markdown(f"{APP_NAME} now lives at its own address. Your account, holdings and "
                    "plan came along - sign in there as usual.")
        st.link_button(f"Go to {APP_NAME}", _new, type="primary", width="stretch")
        st.caption(f"Worth updating your bookmark: {hosting.moved_to()}")
    st.stop()

# Fail closed (settings.py): a hosted copy without a Postgres PORTFOLIO_DB stops
# here, before anything reads or writes data - never a local file on the server.
if settings.config_problem():
    _, _mid, _ = st.columns([1, 1.4, 1])
    with _mid:
        _logo_title(APP_NAME)
        st.error(settings.config_problem(), icon=":material/settings:")
        st.caption("For the admin: add the database's connection string as PORTFOLIO_DB in "
                   "this host's settings (Environment on Render, Secrets on Streamlit "
                   "Community Cloud), then restart the app. Nobody's data was touched.")
    st.stop()


def _visitor_ip():
    """The visitor's address for sign-in, sign-up and email limits - from the proxy's
    header on our own host (hosting.CLIENT_IP_HEADER)."""
    return hosting.client_ip(st.context.headers, st.context.ip_address)

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


def _app_address() -> str:
    """This app's web address without its ?query, for links to send people:
    APP_URL when set, never only what the visitor's browser says (hosting.py)."""
    return hosting.app_address(st.context.url, st.context.headers)


def _email_not_sent(purpose, to):
    """An account email (`purpose`: confirm, change, reset) didn't go - Resend
    refused it (on a busy day, its daily allowance) or couldn't be reached.
    The count it used is given back (auth.send_failed), so "Send it again"
    tries at once, and the admin hears of it like any error: its kind only,
    never the address (error_alerts.py; Admin > System lists it). An alert
    sent through the same Resend can wait until it accepts email again."""
    try:
        conn = connect(DB)
        try:
            auth.send_failed(conn, purpose, to)
        finally:
            conn.close()
        raise mailer.EmailNotSent(f"a {purpose} email wasn't accepted")
    except mailer.EmailNotSent as ex:
        try:
            import error_alerts
            error_alerts.report(DB, ex, copy="Staging" if STAGING else "Live",
                                send=settings.send_error_alerts())
        except Exception:  # noqa: BLE001 - an alert must never break the page
            pass
    except Exception:  # noqa: BLE001 - nor must giving the count back
        pass


def _send_confirmation(user_id) -> tuple[bool, str]:
    """Email this account a confirm-your-email link (auth.start_confirmation,
    mailer.py). (sent, a message to show)."""
    conn = connect(DB)
    try:
        res = auth.start_confirmation(conn, user_id, ip=_visitor_ip())
    finally:
        conn.close()
    if not res["ok"]:
        return False, res["error"]
    if not mailer.confirm_email(res["to"], f"{_app_address()}?confirm={res['token']}",
                                auth.CONFIRM_DAYS):
        _email_not_sent("confirm", res["to"])
        return False, "We couldn't send the email just now. Please try again in a few minutes."
    return True, (f"We sent a link to {res['to']}. It can take a minute - check your spam "
                  "folder too.")


def _render_disclosures(*, summary=True):
    """The About and disclosures text (disclosures.py) - the About page, and
    on the login screen for people who haven't signed in."""
    if summary:
        st.markdown(disclosures.SUMMARY)
    for title, body in disclosures.SECTIONS:
        st.subheader(title, anchor=False)
        st.markdown(body.strip())
    st.caption(f"Last updated {disclosures.LAST_UPDATED}. {LEGAL_LINKS} say the same in "
               "more detail.")


def _toggle_about():
    st.session_state["show_about"] = not st.session_state.get("show_about")


# asked beside "I'm 18 or older" wherever that box is (decision D10)
US_RESIDENT_BOX = "I live in the United States"
# the published Terms of Use and Privacy Policy, on the website
LEGAL_LINKS = (f"The [Terms of Use]({disclosures.TERMS_URL}) and "
               f"[Privacy Policy]({disclosures.PRIVACY_URL})")
AGREE_BOX = (f"I've read and agree to the [Terms of Use]({disclosures.TERMS_URL}), "
             f"[Privacy Policy]({disclosures.PRIVACY_URL}) and About and disclosures")
AGREE_HELP = ("What the app is, what's stored and what's sent to the AI. The About and "
              "disclosures are below; the Terms and the Privacy Policy open on northwend.app.")


def _md_name(name):
    """A person's name or email inside st.markdown, shown as typed: markdown
    characters escaped, and an email isn't turned into a mailto link (an
    invisible word joiner before the @ stops the autolink). (Up here: the
    setup link page uses it before sign-in.)"""
    text = re.sub(r"([\\`*_{}\[\]<>()#+!|~$])", r"\\\1", str(name or ""))
    return text.replace("@", "\u2060@")


def _invite_setup(token: str) -> bool:
    """The page a client's setup link opens: choose a password for the
    account their advisor made, then they're signed in. False until then."""
    conn = connect(DB)
    try:
        info = auth.invite_info(conn, token)
        # the sharing words, recorded verbatim with the consent grant (consent.py)
        sharing = (consent.setup_link_text(consent.advisor_label(conn, info["advisor_id"]))
                   if info and info.get("advisor_id") else None)
    finally:
        conn.close()
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        _logo_title(APP_NAME)
        if info is None:
            st.error("This setup link has expired or was already used. Ask your advisor "
                     "for a new one.")
            if st.button("Go to sign in", type="primary"):
                del st.query_params["invite"]
                st.rerun()
            return False
        st.subheader("Set up your login", anchor=False)
        st.caption(f"Your advisor set up a {APP_NAME} account for you. Choose a password "
                   "only you know - your advisor never sees it.")
        if sharing:
            st.caption(f":material/group: {_md_name(sharing)}")
        with st.form("invite_form", border=True):
            st.text_input("Username", value=info["username"], disabled=True,
                          help="You'll sign in with this.")
            pw = st.text_input("Choose a password", type="password", key="invite_pw",
                               help=f"At least {auth.MIN_PASSWORD_LENGTH} characters.")
            again = st.text_input("Type it again", type="password", key="invite_pw_again")
            # the same boxes as Create account: a client agrees here, once
            adult = st.checkbox(f"I'm {disclosures.MIN_AGE} or older", key="invite_adult")
            us_resident = st.checkbox(US_RESIDENT_BOX, key="invite_us")
            agreed = st.checkbox(AGREE_BOX, key="invite_agree", help=AGREE_HELP)
            remember = st.checkbox(f"Stay signed in on this device ({auth.SESSION_DAYS} days)",
                                   value=True, key="invite_remember",
                                   help="Leave this off on a shared or public computer.")
            submitted = st.form_submit_button("Create my login", type="primary",
                                              width="stretch")
        st.caption(disclosures.SUMMARY)
        st.button("Hide about and disclosures" if st.session_state.get("show_about")
                  else "About and disclosures", key="invite_about", type="tertiary",
                  on_click=_toggle_about)
    if st.session_state.get("show_about"):
        with mid.container(border=True):
            _render_disclosures(summary=False)
    if not submitted:
        return False
    if pw != again:
        mid.error("The two passwords don't match.")
        return False
    conn = connect(DB)
    try:
        result = auth.accept_invite(conn, token, pw, agreed=agreed, adult=adult,
                                    us_resident=us_resident,
                                    terms_version=disclosures.LAST_UPDATED,
                                    consent_text=sharing)
        if result["ok"]:
            # they just agreed to this version, so no "worth a quick read"
            # banner; their advisor may have set other settings already
            saved = prefs.load(conn, result["user_id"])
            saved["disclosures_seen"] = disclosures.LAST_UPDATED
            prefs.save(conn, result["user_id"], saved)
        session = (auth.create_session(conn, result["user_id"])
                   if result["ok"] and remember else None)
    finally:
        conn.close()
    if not result["ok"]:
        mid.error(result["error"])
        return False
    st.session_state.clear()  # whoever was signed in on this browser before
    st.session_state["user_id"] = result["user_id"]
    st.session_state["username"] = result["username"]
    st.session_state["session_token"] = session
    # straight to the goals and risk questions, so the advisor has a ready
    # profile before the first meeting (ROADMAP G6)
    st.session_state["page"] = "Get started"
    st.session_state["import_flash"] = (
        "Your login is ready. Welcome! First, a few quick questions about your goals and how "
        "you feel about ups and downs - about two minutes. Your advisor sees your answers.")
    del st.query_params["invite"]
    st.rerun()


def _show_signup(flag):
    """Switch the sign-in screen between Log in and Create account."""
    st.session_state["show_signup"] = flag
    st.session_state.pop("signup_opened", None)
    if not flag and "signup" in st.query_params:
        del st.query_params["signup"]


SIGNUP_ROLES = {"investor": "For my own investing", "advisor": "I'm a financial advisor"}


def _signup() -> bool:
    """The Create account page (auth.sign_up): how they'll use Northwend, an
    email, a password, and agreeing to the disclosures. A new account is
    signed in straight away and starts on Get started. An advisor's account
    starts as an investor account with a request for advisor access
    (auth.request_advisor) that the admin approves. Linkable as ?signup=1, or
    ?signup=advisor to start on the advisor choice. False until it's made."""
    # when the form first appeared - one sent sooner than a person could is asked again
    st.session_state.setdefault("signup_opened", time.time())
    need_code = auth.invite_only()   # while gate L0 is off (setup links never need one)
    st.session_state.setdefault("signup_role", "advisor" if st.query_params.get("signup")
                                == "advisor" else "investor")
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        _logo_title(APP_NAME)
        st.subheader("Create your account", anchor=False)
        st.caption(f"Free while {APP_NAME} is in beta. Your email is just your login: it's never "
                   "shown to anyone or sent to the AI, and you never connect a brokerage. We don't sell "
                   "investments or take commissions. You can "
                   "start with an example portfolio or percentages instead of real numbers.")
        role = st.segmented_control("How will you use Northwend?", list(SIGNUP_ROLES),
                                    format_func=SIGNUP_ROLES.get, key="signup_role",
                                    width="stretch") or "investor"
        firm = licence = code = ""
        with st.form("signup_form", border=True):
            if need_code:   # gate L0 off: a small beta, by invite code (invite_codes.py)
                st.markdown(invite_codes.BETA_LINE)
                code = st.text_input("Invite code", key="signup_code", max_chars=20,
                                     placeholder="ABCD-EFGH")
            email = st.text_input("Email", key="signup_email", autocomplete="email",
                                  placeholder="name@example.com")
            pw = st.text_input("Choose a password", type="password", key="signup_pw",
                               autocomplete="new-password",
                               help=f"At least {auth.MIN_PASSWORD_LENGTH} characters, and one "
                                    "you don't use anywhere else.")
            again = st.text_input("Type it again", type="password", key="signup_pw_again",
                                  autocomplete="new-password")
            st.text_input("Website", key="signup_website")  # hidden (see the CSS); bots fill it
            if role == "advisor":
                st.caption("Advisor tools are for licensed professionals, so we check each "
                           "request first - usually within two working days. Until then you "
                           "can explore Northwend as an investor. Questions about advisor "
                           f"access: {disclosures.CONTACT}")
                firm = st.text_input("Firm name", key="signup_firm", max_chars=100)
                licence = st.text_input("CRD or licence number", key="signup_licence",
                                        max_chars=40,
                                        help="Your individual CRD number (FINRA BrokerCheck) or "
                                             "the licence number where you're registered.")
            adult = st.checkbox(f"I'm {disclosures.MIN_AGE} or older", key="signup_adult")
            us_resident = st.checkbox(US_RESIDENT_BOX, key="signup_us")
            agreed = st.checkbox(AGREE_BOX, key="signup_agree", help=AGREE_HELP)
            remember = st.checkbox(f"Stay signed in on this device ({auth.SESSION_DAYS} days)",
                                   value=True, key="signup_remember",
                                   help="Leave this off on a shared or public computer.")
            submitted = st.form_submit_button("Create account", type="primary", width="stretch")
        st.caption("We'll email you a link to confirm your address - it unlocks the AI guide "
                   "and lets you reset your password if you ever forget it.")
        with st.container(horizontal=True):
            st.button("Hide about and disclosures" if st.session_state.get("show_about")
                      else "About and disclosures", key="signup_about", type="tertiary",
                      on_click=_toggle_about)
            st.button("Already have an account? Sign in", key="signup_to_login",
                      type="tertiary", on_click=_show_signup, args=(False,))
    if st.session_state.get("show_about"):
        with mid.container(border=True):
            _render_disclosures()
    if not submitted:
        return False
    if pw != again:
        mid.error("The two passwords don't match.")
        return False
    if role == "advisor" and auth.advisor_request_error(firm, licence):
        mid.error(auth.advisor_request_error(firm, licence))
        return False
    conn = connect(DB)
    try:
        result = auth.sign_up(conn, email, pw, agreed=agreed, adult=adult,
                              us_resident=us_resident, invite_code=code,
                              needs_code=need_code,
                              terms_version=disclosures.LAST_UPDATED,
                              ip=_visitor_ip(),
                              seconds_open=time.time() - st.session_state["signup_opened"],
                              honeypot=st.session_state.get("signup_website") or "")
        if result["ok"]:
            # they just agreed to this version, so no "worth a quick read" banner
            prefs.save(conn, result["user_id"], {"disclosures_seen": disclosures.LAST_UPDATED})
            session = auth.create_session(conn, result["user_id"]) if remember else None
            if role == "advisor":
                auth.request_advisor(conn, result["user_id"], firm, licence)
    finally:
        conn.close()
    if not result["ok"]:
        mid.error(result["error"])
        return False
    if role == "advisor":  # a failure is logged by mailer; `advisor-requests` lists it anyway
        mailer.advisor_request(result["username"], firm.strip(), licence.strip(),
                               _app_address())
    sent, note = _send_confirmation(result["user_id"])
    st.session_state.clear()  # whoever was signed in on this browser before
    st.session_state["user_id"] = result["user_id"]
    st.session_state["username"] = result["username"]
    st.session_state["session_token"] = session
    if sent:
        # just signed up: one short line about the link (and, for an advisor,
        # their request), so the welcome screen stays in view - a phone has
        # room for little else; the fuller card with "Send it again" comes back
        # in later sessions, and the name menu shows the request
        st.session_state["email_brief"] = "advisor" if role == "advisor" else True
    else:
        st.session_state["email_flash"] = (False, note)
        if role == "advisor":
            st.session_state["import_flash"] = (
                f"Your account is ready. Welcome to {APP_NAME}! We're checking your advisor "
                "details; advisor tools appear once they're approved. Until then, have a look "
                "around as an investor.")
    if "signup" in st.query_params:
        del st.query_params["signup"]
    st.rerun()


def _show_forgot(flag):
    """Switch the sign-in screen between Log in and Forgot password."""
    st.session_state["show_forgot"] = flag
    st.session_state.pop("forgot_sent", None)


def _forgot() -> bool:
    """The "Forgot password?" page: an email address in, a reset link out
    (auth.request_password_reset, mailer.py). The answer is the same whether
    or not there's an account, so it can't be used to find out who has one."""
    submitted = False
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        _logo_title(APP_NAME)
        st.subheader("Reset your password", anchor=False)
        sent_to = st.session_state.get("forgot_sent")
        if sent_to:
            st.success(f"If there's an account for {sent_to}, we've sent it a link to choose a "
                       f"new password. The link works for {auth.RESET_MINUTES} minutes - check "
                       "your spam folder too.")
        else:
            st.caption("Enter the email you signed up with and we'll send you a link to choose "
                       "a new password.")
            with st.form("forgot_form", border=True):
                email = st.text_input("Email", key="forgot_email", autocomplete="email",
                                      placeholder="name@example.com")
                submitted = st.form_submit_button("Send me a link", type="primary",
                                                  width="stretch")
        st.caption("Your account was set up by an advisor or an administrator? Ask them to "
                   "reset your password.")
        st.button("Back to sign in", key="forgot_back", type="tertiary",
                  on_click=_show_forgot, args=(False,))
    if sent_to or not submitted:
        return False
    conn = connect(DB)
    try:
        res = auth.request_password_reset(conn, email, ip=_visitor_ip())
    finally:
        conn.close()
    if not res["ok"]:
        mid.error(res["error"])
        return False
    # the answer must look the same either way, so a failed send only tells the admin
    if res["token"] and not mailer.reset_password(
            res["to"], f"{_app_address()}?reset={res['token']}", auth.RESET_MINUTES):
        _email_not_sent("reset", res["to"])
    st.session_state["forgot_sent"] = auth.normalize_email(email)
    st.rerun()


def _reset_setup(token: str) -> bool:
    """The page a reset link opens: choose a new password, then signed in
    (everywhere else signed out). False until then."""
    conn = connect(DB)
    try:
        info = auth.reset_info(conn, token)
    finally:
        conn.close()
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        _logo_title(APP_NAME)
        if info is None:
            st.error("This reset link has expired or was already used. You can ask for a new one.")
            if st.button("Go to sign in", type="primary"):
                del st.query_params["reset"]
                st.rerun()
            return False
        st.subheader("Choose a new password", anchor=False)
        with st.form("reset_form", border=True):
            st.text_input("Email", value=info["email"], disabled=True)
            pw = st.text_input("New password", type="password", key="reset_pw",
                               autocomplete="new-password",
                               help=f"At least {auth.MIN_PASSWORD_LENGTH} characters.")
            again = st.text_input("Type it again", type="password", key="reset_pw_again",
                                  autocomplete="new-password")
            remember = st.checkbox(f"Stay signed in on this device ({auth.SESSION_DAYS} days)",
                                   value=True, key="reset_remember",
                                   help="Leave this off on a shared or public computer.")
            submitted = st.form_submit_button("Save new password", type="primary",
                                              width="stretch")
        st.caption("Saving signs you out on every other device.")
    if not submitted:
        return False
    if pw != again:
        mid.error("The two passwords don't match.")
        return False
    conn = connect(DB)
    try:
        result = auth.reset_password(conn, token, pw)
        session = (auth.create_session(conn, result["user_id"])
                   if result["ok"] and remember else None)
    finally:
        conn.close()
    if not result["ok"]:
        mid.error(result["error"])
        return False
    st.session_state.clear()  # whoever was signed in on this browser before
    st.session_state["user_id"] = result["user_id"]
    st.session_state["username"] = result["username"]
    st.session_state["session_token"] = session
    st.session_state["import_flash"] = "Your new password is saved. Welcome back!"
    del st.query_params["reset"]
    st.rerun()


def _take_confirm_link():
    """A confirm-your-email link (?confirm=...): mark the email confirmed and
    say so - on the sign-in screen, and once signed in."""
    token = st.query_params.get("confirm")
    if not token:
        return
    del st.query_params["confirm"]
    # already handled in this session (the address kept it, or signing in
    # reran the page with it): nothing more to say
    done = st.session_state.setdefault("links_done", [])
    if token in done:
        return
    conn = connect(DB)
    try:
        res = auth.confirm_email(conn, str(token))
    finally:
        conn.close()
    done.append(token)
    if res["ok"]:
        msg = f"Your email is confirmed - thank you! The AI guide, Ask {GUIDE}, is ready."
    else:
        msg = res["error"] + " If you still need to confirm, send a new link after signing in."
    st.session_state["email_flash"] = (res["ok"], msg)
    st.session_state["email_state"] = None  # look it up again
    st.session_state["login_notice"] = msg + ("" if st.session_state.get("user_id")
                                              else " Sign in to continue.")


def _take_email_change_link():
    """A change-your-email link (?email_change=..., the Account page): the new
    address becomes the account's, the old one is told, and a signed-in
    browser follows a login that was the old email."""
    token = st.query_params.get("email_change")
    if not token:
        return
    conn = connect(DB)
    try:
        res = auth.confirm_email_change(conn, str(token))
    finally:
        conn.close()
    del st.query_params["email_change"]
    if res["ok"]:
        if res["old_email"]:
            mailer.email_changed(res["old_email"], res["email"], _app_address())
        if st.session_state.get("user_id") == res["user_id"]:
            st.session_state["username"] = res["username"]
        msg = f"Your email is now {res['email']}."
        if res["username"] == res["email"]:
            msg += " Sign in with it from now on."
    else:
        msg = res["error"]
    st.session_state["email_flash"] = (res["ok"], msg)
    st.session_state["email_state"] = None  # look it up again
    st.session_state["login_notice"] = msg + ("" if st.session_state.get("user_id")
                                              else " Sign in to continue.")


def _login() -> bool:
    """Per-account login. Accounts are made by an admin (manage_users.py),
    an advisor for a client, or by people themselves on the Create account
    page (_signup). Sets
    st.session_state["user_id"]/["username"] on success. Generic error
    message on any failure (unknown username OR wrong password) so the
    login screen never reveals which username exists.

    A new browser session (a reload, a phone reopening the tab) first tries
    the stay-signed-in cookie; the token is checked against the database
    every time, so logging out or changing the password ends it."""
    unsub = st.query_params.get("unsubscribe")
    if unsub:  # an email's one-click unsubscribe link - no sign-in (views/unsubscribe.py)
        return _unsubscribe_page(str(unsub))
    # ?share=...: an "Explain it to someone" link (views/explain_share.py) - the
    # whole run, signed in or not; it signs nobody in and opens no other page
    if _share_wanted():
        return _share_page()
    # ?decode=401k: the 401(k) decoder without an account (views/decoder_public.py),
    # only while its flag is on and nobody is signed in in this tab
    if (flags.on("decoder_public") and not st.session_state.get("user_id")
            and _decoder_public_wanted()):
        return _decoder_public_page()
    invite = st.query_params.get("invite")
    if invite:  # a client's setup link (auth.create_invite)
        return _invite_setup(str(invite))
    reset = st.query_params.get("reset")
    if reset:  # a reset-your-password link (auth.request_password_reset)
        return _reset_setup(str(reset))
    _take_confirm_link()
    _take_email_change_link()
    # signed in, however it happened: two-step sign-in comes next (views/two_step.py)
    if st.session_state.get("user_id"):
        return _two_step_gate()
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
            return _two_step_gate()
        st.session_state["signed_out"] = True  # a dead cookie: remove it below
    if st.session_state.get("signed_out") and cookie:
        st.html(_cookie_script(None), unsafe_allow_javascript=True)
    if st.session_state.get("show_signup", "signup" in st.query_params):
        return _signup()
    if st.session_state.get("show_forgot"):
        return _forgot()

    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        _logo_title(APP_NAME)
        st.caption(f"{TAGLINE} Sign in to see your portfolio.")
        _notice = st.session_state.get("login_notice")
        if _notice:
            st.info(_notice)
        if flags.on("together") and "together" in st.query_params:
            # a Doing it together invitation: answered after signing in (together.py)
            st.info(together.SIGN_IN)
        with st.form("login_form", border=True):
            user = st.text_input("Email or username", key="login_user", autocomplete="username")
            pw = st.text_input("Password", type="password", key="login_pw",
                               autocomplete="current-password")
            remember = st.checkbox(f"Stay signed in on this device ({auth.SESSION_DAYS} days)",
                                   value=True, key="login_remember",
                                   help="Leave this off on a shared or public computer.")
            submitted = st.form_submit_button("Log in", type="primary", width="stretch")
        st.button("Forgot password?", key="login_forgot", type="tertiary",
                  on_click=_show_forgot, args=(True,))
        st.button("New here? Create an account", key="login_to_signup", width="stretch",
                  on_click=_show_signup, args=(True,))
        st.caption(disclosures.SUMMARY)
        st.button("Hide about and disclosures" if st.session_state.get("show_about")
                  else "About and disclosures", key="login_about", type="tertiary",
                  on_click=_toggle_about)
    if st.session_state.get("show_about"):
        with mid.container(border=True):
            _render_disclosures(summary=False)  # the summary is just above
    if submitted:
        if not user or not pw:
            mid.error("Enter your email or username, and your password.")
            return False
        conn = connect(DB)
        try:
            # behind the lockout: too many wrong passwords locks the username,
            # and too many from one internet address pause sign-in from there
            result = auth.attempt_login(conn, user, pw, ip=_visitor_ip())
            user_id = result["user_id"]
            token = auth.create_session(conn, user_id) if user_id is not None and remember else None
            # as stored, not as typed (an email works in any letter case)
            username = auth.get_username(conn, user_id) if user_id is not None else None
        finally:
            conn.close()
        if user_id is not None:
            st.session_state.pop("signed_out", None)
            st.session_state.pop("login_notice", None)
            st.session_state["user_id"] = user_id
            st.session_state["username"] = username
            st.session_state["session_token"] = token
            st.rerun()
        if result.get("from_here"):
            mid.error(auth.TOO_MANY_FROM_HERE)
        elif result["locked_minutes"]:
            m = result["locked_minutes"]
            mid.error(f"Too many attempts. Try again in {m} minute{'s' if m != 1 else ''}, "
                      "or choose a new one with Forgot password? (if an advisor manages your "
                      "account, ask them).")
        elif result["attempts_left"] <= 2:
            mid.error(f"Wrong email, username or password. {result['attempts_left']} more "
                      f"attempt{'s' if result['attempts_left'] != 1 else ''} before a "
                      f"{auth.LOCKOUT_MINUTES}-minute lock.")
        else:
            mid.error("Wrong email, username or password.")
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


# two-step sign-in: the code / setup pages _login() shows after the password
_view("two_step")
# the page an email's one-click unsubscribe link opens (unsubscribe.py)
_view("unsubscribe")
# the 401(k) decoder without an account, ?decode=401k (decoder_public.py)
_view("decoder_public")
# an "Explain it to someone" link, ?share=... (explain_share.py), and the
# owner's section on Account (always loaded: off, a link says it's not active)
_view("explain_share")

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
    # the login's own row (password stamp, advisor, admin, name): as the
    # two-step gate read it just now, in this run (views/two_step.py)
    _gate = _gate_read(LOGIN_ID)
    _me = (auth.login_facts_of(_gate[1]) if _gate is not None
           else auth.login_facts(_conn, LOGIN_ID))
    # A password change (here, on another device, or by an admin or advisor)
    # signs out tabs that are already open, not just the saved cookies.
    _stamp = _me["stamp"]
    if st.session_state.setdefault("pw_stamp", _stamp) != _stamp:
        st.session_state.clear()
        st.session_state["signed_out"] = True
        st.session_state["login_notice"] = "Your password was changed. Sign in again."
        st.rerun()
    IS_ADVISOR = _me["is_advisor"]
    # the Admin portal (admin.py; granted only from the command line)
    IS_ADMIN = _me["is_admin"]
    # what they asked to be called (the Account page), else their login
    MY_NAME = _me["display_name"] or st.session_state["username"]
    CLIENTS = auth.list_clients(_conn, LOGIN_ID) if IS_ADVISOR else []
    # an investor account that asked for advisor access (shown in the name menu)
    ADVISOR_REQUEST = None if IS_ADVISOR else auth.advisor_request(_conn, LOGIN_ID)
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
    # the latest holdings' date (load() reads that snapshot below)
    _LATEST_SNAPSHOT = latest_snapshot(_conn, _active)
    HAS_HOLDINGS = _LATEST_SNAPSHOT is not None
    # where they came from (load() below reuses it): the example portfolio
    # isn't an account they've opened, so Learn keeps its place while it's all
    # there is (HAS_REAL_HOLDINGS)
    _LATEST_SOURCE = snapshot_source(_conn, _active, _LATEST_SNAPSHOT) if HAS_HOLDINGS else None
    HAS_REAL_HOLDINGS = HAS_HOLDINGS and _LATEST_SOURCE != SAMPLE_SOURCE
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
# Client mode: an advisor's client - and their advisor in their account, who
# sees what they see. Their plan and recommendations are the advisor's, so
# the beginner's example funds, example mix and practice money stay out of
# it, Learn is never required, and Home's next step speaks for the advisor
# (route.advisor_step). Milestones and gear stay: learning and habits only.
CLIENT_MODE = IS_MANAGED_CLIENT or ON_CLIENT
# Gate L3 (docs/LEGAL_GATES.md, flags.GATE_CHECKS): anything worked out from a
# person's own answers. Off (the default): Learn, Home and Plan show common
# starting points - one table, the same for everyone (learn.common_starting_points)
# - instead of an example mix or investor type picked for them, and nothing
# copies Northwend's mix into their target. On: the tailored example mix.
TAILORED_MIX = flags.gate("L3")
# The investor experience: investors, clients, and an advisor looking at a
# client's account (they see what the client sees). An advisor's own
# portfolio is the advisor experience.
INVESTOR_VIEW = not IS_ADVISOR or ON_CLIENT
# The portfolio page is "Home" in the investor app and "Portfolio" in the
# advisor app, whose home is Your clients. (Its internal name stays
# "Dashboard"; old ?page=dashboard links still open it.)
PAGE_LABELS["Dashboard"] = "Portfolio" if IS_ADVISOR else "Home"
# Get started is "Learn" in the investor menu (ROADMAP S4); an advisor's
# copy, in a client's account too, keeps "Get started".
if not IS_ADVISOR:
    PAGE_LABELS["Get started"] = "Learn"
# a managed client's page from their advisor: notes, reports and proposals
if IS_MANAGED_CLIENT:
    PAGE_LABELS["Advisor notes"] = "Your advisor"
st.session_state["active_user_id"] = USER_ID
ACTIVE_NAME = (MY_NAME if USER_ID == LOGIN_ID
               else dict(CLIENTS).get(USER_ID, "client"))
# where this account's settings lived before they moved into the database;
# read once, the first time, so they carry over (prefs.py)
PREFS_PATH = os.path.join(HERE, f".dashboard_prefs.{USER_ID}.json")

# Two experiences (ROADMAP G1). Investors - and clients of an advisor - get the
# investor app: Get started leads for an account with nothing imported yet
# (and is where it lands); once there are holdings it moves to the end as a
# reference. Advisors get the advisor app: it opens on Your clients, and the
# portfolio pages below it are for whichever account is being viewed; Get
# started only appears when that's a client's.
if IS_ADVISOR:
    _start = ["Get started"] if ON_CLIENT else []
    PAGES = ["Clients", *([] if HAS_HOLDINGS else _start),
             "Dashboard", "Plan", *(["Advisor notes"] if ON_CLIENT else []),
             "Watchlist", "Activity", "Income", "News", "AI Assistant",
             *(_start if HAS_HOLDINGS else []), "Account", "What's new", "About"]
else:
    # an advisor's client lands on Home (their advisor's next step), never
    # on Learn: it's there for them, not required
    _learn_last = HAS_REAL_HOLDINGS or IS_MANAGED_CLIENT
    PAGES = [*([] if _learn_last else ["Get started"]),
             "Dashboard", "Plan", *(["Advisor notes"] if IS_MANAGED_CLIENT else []),
             "Watchlist", "Activity", "Income", "News", "AI Assistant", "Life",
             *(["Get started"] if _learn_last else []), "Account", "What's new", "About"]
# One ticker's page (views/ticker_detail.py, ?page=ticker&t=VTI): opened from
# a row on Home or the Watchlist, never from the menu - it would be empty
# without a ticker. The menu shows the page it was opened from (_nav_current).
PAGES.append(TICKER_PAGE)
if IS_ADMIN:
    PAGES.append("Admin")
# while advisor access is being checked: a read-only preview of the advisor
# side, with made-up clients (views/advisor_demo.py) - in the name menu
ADVISOR_PENDING = bool(ADVISOR_REQUEST and ADVISOR_REQUEST["decision"] is None)
if ADVISOR_PENDING:
    PAGES.append("Advisor preview")
# Find a guide, the advisor directory (flag directory, gate L2; views/directory.py):
# for an individual, from the name menu - never an advisor, never client mode
if not IS_ADVISOR and not CLIENT_MODE:
    PAGES.append("Find a guide")
# a page whose feature is off (flags.FEATURES) isn't one this account can open
PAGES = [p for p in PAGES if flags.page_on(p)]

# The menu: a column down the left side on a laptop (the menu column; on a
# phone the tab bar along the bottom shows the same items, and the column
# slims to a bar along the top with the name and the two menus), everything
# on it at once - nothing hidden behind a "More". Investors get Home, Plan,
# Money, Life, Learn and Ask Northwend (+ Your advisor for a managed client);
# advisors Your clients, Portfolio, Plan, Advisor notes (in a client's
# account), Money and Ask Northwend. Money is one page with a tab each for
# Income, Activity and Watchlist (MONEY_PAGES): those stay pages of their own
# inside (their ?page= names, _go("Income") and the views' `if PAGE == ...`),
# the menu just groups them, and lists them under Money while it's open. Life
# (views/life.py) gathers the paperwork side: the account map, Lost & Found,
# Trail Forks, the Inheritance Rehearsal and Explain it to someone - only an
# individual's (an advisor keeps their own on Account). Account, What's new,
# About, Admin and Log out are in the name menu at the bottom (ACCOUNT_MENU).
# PAGES stays every page this account can open (the address, ?page=, checks
# against it). Always in this order, before holdings and after (where they
# land is PAGES[0]): an item never moves under someone's thumb.
MONEY = "Money"
# (+ News, Your news, while its flag news_feed is on: views/news_feed.py)
MONEY_PAGES = ("Income", "Activity", "Watchlist", *(("News",) if "News" in PAGES else ()))
if IS_ADVISOR:
    NAV = ["Clients", "Dashboard", "Plan", *(["Advisor notes"] if ON_CLIENT else []),
           MONEY, "AI Assistant"]
else:
    NAV = ["Dashboard", "Plan", MONEY, "Life", "Get started", "AI Assistant",
           *(["Advisor notes"] if IS_MANAGED_CLIENT else [])]
NAV = [p for p in NAV if p == MONEY or p in PAGES]
# (Advisor preview is reached from the name menu's "advisor access requested" note)
ACCOUNT_MENU = [p for p in ("Account", "Find a guide", "What's new", "About", "Admin")
                if p in PAGES]


def _nav_label(item):
    return item if item == MONEY else _label(item)


def _slug(page):
    """A page's name in the address: 'Ask Northwend' -> 'ask-northwend'."""
    return _label(page).lower().replace("'", "").replace(" ", "-")


# addresses saved before a page was renamed still open it - and a link made in
# the other experience (Home / Portfolio, Learn / Get started)
OLD_SLUGS = {"ask-sage": "AI Assistant", "clients": "Clients", "dashboard": "Dashboard",
             "home": "Dashboard", "portfolio": "Dashboard",
             "get-started": "Get started", "learn": "Get started",
             # Money opens on its first tab; each tab keeps its own name
             # (?page=income, activity, watchlist)
             "money": "Income",
             # a managed client's "Your advisor" is the advisor's "Advisor notes"
             # (the report emails link to ?page=advisor-notes)
             "advisor-notes": "Advisor notes", "your-advisor": "Advisor notes"}

# ?together=...: a "Doing it together" invitation (together.py). Only its hash
# is kept, in this session, and Life opens, where the invitation is answered
# (views/together.py); the address then loses it (just below).
if "together" in st.query_params:
    if flags.on("together") and "Life" in PAGES:
        st.session_state["together_hash"] = together.token_hash(
            str(st.query_params.get("together")))
        st.session_state["page"] = "Life"
    del st.query_params["together"]

if "page" not in st.session_state:
    # a fresh session: start on the page in the address (?page=plan), if it's
    # one this account can open
    _wanted = str(st.query_params.get("page", "")).lower()
    st.session_state["page"] = {_slug(p): p for p in PAGES}.get(
        _wanted, OLD_SLUGS.get(_wanted) if OLD_SLUGS.get(_wanted) in PAGES else PAGES[0])
    if st.session_state["page"] == TICKER_PAGE:   # ?page=ticker&t=VTI
        _t = str(st.query_params.get("t", "")).strip().upper()
        if TICKER_RE.fullmatch(_t):
            st.session_state["ticker_sym"] = _t
# a ticker opened the way it used to be (the open row of Home's or the
# Watchlist's ticker strip): its own page now, Back returns there
for _old_key, _old_from in (("holdings_pill", "Dashboard"), ("watchlist_pill", "Watchlist")):
    _old_sym = st.session_state.pop(_old_key, None)
    if _old_sym:
        _open_ticker(_old_sym, _old_from)
if st.session_state.get("page") == TICKER_PAGE and not st.session_state.get("ticker_sym"):
    st.session_state["page"] = st.session_state.get("ticker_from") or PAGES[0]
if st.session_state.get("page") not in PAGES:
    st.session_state["page"] = PAGES[0]

# kept when an advisor switches accounts; everything else is per-account
_KEEP_ON_SWITCH = ("user_id", "username", "page", "session_token", "pw_stamp", "session_gen",
                   "two_step_ok")


def _go(page):
    st.session_state["page"] = page


def _guide_line(key):
    """ADR 0005: the one quiet "Find a guide" line (directory.GUIDE_LINE), on
    Learn once it's finished and on Plan once a goal is set. Only where Find
    a guide is open to this login (flag `directory`, gate L2) and only for an
    individual on their own account - never an advisor, an admin, client
    mode or someone with an advisor (directory.guide_link_shown). No pop-up;
    nothing is written or counted about who sees or presses it."""
    import directory

    if ("Find a guide" not in PAGES or USER_ID != LOGIN_ID
            or not directory.guide_link_shown(
                directory_on=flags.on("directory"), is_advisor=IS_ADVISOR, is_admin=IS_ADMIN,
                client_mode=CLIENT_MODE, has_advisor=IS_MANAGED_CLIENT)):
        return
    with st.container(horizontal=True, vertical_alignment="center", gap="small",
                      key=f"pt_{key}"):
        st.caption(directory.GUIDE_LINE, width="content")
        st.button(directory.GUIDE_BUTTON, key=key, type="tertiary", on_click=_go,
                  args=("Find a guide",), icon=":material/signpost:")


def _advisor_display_name():
    """The managing advisor's name as they've chosen to show it."""
    card = MY_ADVISOR_CARD
    return (card.get("name") or card.get("username") or "your advisor") +         (f", {card['firm']}" if card.get("firm") else "")


def _advisor_names(card, username):
    """An advisor's (name for an email's text, name for its From line) from
    their card (How clients see you): "Dana Ruiz (Ruiz Wealth)" and
    "Dana Ruiz, Ruiz Wealth" - the login when there's no name yet."""
    name = card.get("name") or username
    firm = card.get("firm")
    return (f"{name} ({firm})" if firm else name), (f"{name}, {firm}" if firm else name)


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


def _back_to_clients():
    """The viewing bar's way out of a client's account."""
    _switch_to(st.session_state["user_id"])
    st.session_state["page"] = "Clients"


def _add_client():
    """Add client (Your clients): their name or household and, with an email,
    a setup link sent in the same step - from the advisor's name and firm,
    asked for here before the first invite if How clients see you is empty."""
    name = auth.clean_client_name(st.session_state.get("new_client_name"))
    email = (st.session_state.get("new_client_email") or "").strip()
    invite = bool(email) and st.session_state.get("new_client_invite", True)
    viewer = st.session_state["user_id"]
    if not name and not email:
        st.session_state["client_msg"] = (
            "error", "Enter their name, or a household name like Chen household.")
        return
    if email and "@" not in email:
        st.session_state["client_msg"] = (
            "error", "That doesn't look like an email address - check it, or leave it blank.")
        return
    c = connect(DB)
    try:
        if invite:
            missing = _save_invite_card(c, viewer, "new_adv")
            if missing:
                st.session_state["client_msg"] = ("error", missing)
                return
        client_id, shown, sent = _add_one_client(c, viewer, name, email, invite)
    except ValueError as exc:
        st.session_state["client_msg"] = ("error", str(exc).capitalize() + ".")
        return
    except DBError:
        st.session_state["client_msg"] = ("error", "That login is already taken - try another.")
        return
    finally:
        c.close()
    for k in ("new_client_name", "new_client_email"):
        st.session_state[k] = ""
    if sent is None:
        msg = (f"Added {shown}. " + ("When you're ready, send them a setup link from "
                                     "**Client login** in their account." if email else
                                     "Without an email, they can't sign in yet - you can add "
                                     "their statements and plan for them, or create a setup "
                                     "link to send yourself from **Client login**."))
        st.session_state["client_msg"] = ("success", msg, client_id)
    elif sent[0]:
        st.session_state["client_msg"] = ("success", f"Added {shown} and {sent[1][0].lower()}"
                                                     f"{sent[1][1:]}", client_id)
    else:
        st.session_state["client_msg"] = ("warning", f"Added {shown}, but {sent[1][0].lower()}"
                                                     f"{sent[1][1:]}", client_id)


def _save_invite_card(c, viewer, prefix):
    """Before the first invite: who it's from. If How clients see you has no
    name yet, the "Who's it from?" inputs (`prefix`_name / _firm, drawn by
    _render_who_from) are saved there. The error to show, or None."""
    p = prefs.load(c, viewer)
    card = p.get("advisor_card") or {}
    if card.get("name"):
        return None
    my_name = " ".join((st.session_state.get(f"{prefix}_name") or "").split())[:60]
    my_firm = " ".join((st.session_state.get(f"{prefix}_firm") or "").split())[:80]
    if not my_name:
        return "Add your name first - the invite tells them who it's from."
    p["advisor_card"] = {**card, "name": my_name, **({"firm": my_firm} if my_firm else {})}
    prefs.save(c, viewer, p)
    return None


def _add_one_client(c, viewer, name, email, invite):
    """Add one client - Add client, and each row of a file - and, with
    `invite`, email their setup link (_send_invite, with its limits). Returns
    (client id, how to show them, (sent, message) or None). Raises
    ValueError / DBError as auth.create_client does."""
    client_id = auth.create_client(c, viewer, email, name=name)
    shown = name or auth.get_username(c, client_id)   # an email is stored lower-cased
    sent = _send_invite(c, viewer, client_id) if invite else None
    return client_id, shown, sent


def _send_invite(c, viewer, client_id):
    """Email one of this advisor's clients a fresh setup link, from the
    advisor's name and firm (the From line and the text). (sent, message)."""
    email = auth.email_status(c, client_id)["email"]
    if not email:
        return False, "This client has no email address yet."
    card = prefs.load(c, viewer).get("advisor_card") or {}
    if not card.get("name"):
        return False, ("Add your name under **Your clients > How clients see you** first - "
                       "the invite tells them who it's from.")
    if viewer == client_id or not auth.can_view(c, viewer, client_id):
        raise ValueError("you can only invite your own clients")
    # limits on setup-link emails (to this address, and this advisor's day);
    # checked before a new link replaces the one they may already have
    too_many = auth.invite_email_limit(c, viewer, email)
    if too_many:
        return False, too_many
    token = auth.create_invite(c, viewer, client_id)   # ValueError: not their client
    body_name, from_name = _advisor_names(card, st.session_state["username"])
    if mailer.client_invite(email, f"{_app_address()}?invite={token}", body_name,
                            auth.INVITE_DAYS, from_name=from_name):
        return True, f"Sent {email} a setup link. It works for {auth.INVITE_DAYS} days."
    return False, ("the email couldn't be sent just now. Try again from **Client login** in "
                   "their account, or create a link there and send it yourself.")


def _set_client_password():
    pw = st.session_state.get("client_login_pw") or ""
    if len(pw) < auth.MIN_PASSWORD_LENGTH:
        st.session_state["login_msg"] = (
            "error", f"Use a password of at least {auth.MIN_PASSWORD_LENGTH} characters.")
        return
    viewer, target = st.session_state["user_id"], st.session_state["active_user_id"]
    c = connect(DB)
    try:
        if viewer == target or not auth.can_view(c, viewer, target):
            st.session_state["login_msg"] = ("error", "You can only set passwords for your clients.")
            return
        auth.set_password(c, auth.get_username(c, target), pw)
    finally:
        c.close()
    st.session_state["client_login_pw"] = ""
    st.session_state["login_msg"] = ("success", "Login password set - the client can log in now.")


def _create_invite():
    """A one-time setup link for the client being viewed. Only its hash is
    stored, so the link itself is shown once, here, for the advisor to send."""
    viewer, target = st.session_state["user_id"], st.session_state["active_user_id"]
    c = connect(DB)
    try:
        token = auth.create_invite(c, viewer, target)
    except ValueError:
        st.session_state["login_msg"] = ("error", "You can only invite your own clients.")
        return
    finally:
        c.close()
    st.session_state[f"invite_link_{target}"] = f"{_app_address()}?invite={token}"


def _email_invite():
    """Email the client being viewed a fresh setup link (ROADMAP G6): they
    choose a password, then answer the goals and risk questions."""
    viewer, target = st.session_state["user_id"], st.session_state["active_user_id"]
    c = connect(DB)
    try:
        sent, msg = _send_invite(c, viewer, target)
    except ValueError:
        sent, msg = False, "You can only invite your own clients."
    finally:
        c.close()
    if sent:
        st.session_state.pop(f"invite_link_{target}", None)
    st.session_state["login_msg"] = ("success" if sent else "error", msg[0].upper() + msg[1:])


def _cancel_invite():
    viewer, target = st.session_state["user_id"], st.session_state["active_user_id"]
    c = connect(DB)
    try:
        if viewer != target and auth.can_view(c, viewer, target):
            auth.cancel_invite(c, target)
    finally:
        c.close()
    st.session_state.pop(f"invite_link_{target}", None)
    st.session_state["login_msg"] = ("success", "Setup link cancelled - it no longer works.")


def _prepare_export():
    """Profile > Your data: the account's own data as a ZIP (export.py), kept
    in this session for the download button - built only when asked."""
    import export
    if not _limit_ok(rate_limits.EXPORT):   # many exports in a short time
        _limit_hit("export")
        return
    c = connect(DB)
    try:
        data = export.export_zip(c, st.session_state["user_id"])  # own account only
    finally:
        c.close()
    st.session_state["export_zip"] = (export.file_name(), data)


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
    """Add holdings (the menu's, and the pages' own buttons): the menu
    is drawn before this account's holdings are loaded, so it leaves a note
    and the dialog opens just after they are (see open_dialog below load())."""
    if kind == "manual":
        _manual_clear()  # start from the latest snapshot
    st.session_state["open_dialog"] = kind


PAGE = st.session_state["page"]
# The advisor access log (access_log.py, brief 4.3.5): an advisor opening a
# page in a client's account - the client sees it on their Account page. One
# row per page opened, not per rerun (access_log.is_new_view). The login's
# own pages (Account, About...) and Your clients aren't the client's.
if ON_CLIENT and PAGE not in access_log.NOT_THE_CLIENTS:
    _now_ts = time.time()
    if access_log.is_new_view(st.session_state.get("_access_last"), USER_ID, PAGE, _now_ts):
        _conn = connect(DB)
        try:
            access_log.record(_conn, LOGIN_ID, USER_ID, PAGE)
        finally:
            _conn.close()
        st.session_state["_access_last"] = (USER_ID, PAGE, _now_ts)
# the Money tab last open: the menu's Money goes back to it
if PAGE in MONEY_PAGES:
    st.session_state["money_tab"] = PAGE
# Keep where you are in the address, so a reload or a bookmark comes back here
# (read above, for a fresh session). The client is re-checked on every load.
_want_qp = {"page": _slug(PAGE),
            **({"t": st.session_state["ticker_sym"]} if PAGE == TICKER_PAGE else {}),
            **({"client": str(USER_ID)} if USER_ID != LOGIN_ID else {})}
if dict(st.query_params) != _want_qp:
    st.query_params.from_dict(_want_qp)


def _nav_target(item):
    """The page a menu tab opens: Money its tab last open (Income at first)."""
    if item == MONEY:
        tab = st.session_state.get("money_tab")
        return tab if tab in MONEY_PAGES else MONEY_PAGES[0]
    return item


def _nav_current(item):
    """Whether this menu tab is the page showing (Money: any of its tabs). A
    ticker's page has no menu item: the one it was opened from shows."""
    page = (st.session_state.get("ticker_from") or "Dashboard") if PAGE == TICKER_PAGE else PAGE
    return page in MONEY_PAGES if item == MONEY else page == item


# The brand at the top of the menu: the logo, then the name; an advisor's
# phone shows the logo alone, to make room for Viewing.
_BRAND = _brand_html("pt-brand-compact" if IS_ADVISOR else "")
ACCOUNT_ICONS = {"Account": ":material/person:", "About": ":material/info:",
                 "What's new": ":material/campaign:", "Find a guide": ":material/signpost:",
                 "Admin": ":material/admin_panel_settings:",
                 "Advisor preview": ":material/preview:",
                 "Send feedback": ":material/feedback:"}


def _whats_new_unseen():
    """True while What's new has an entry newer than the one this login last
    opened (the login's own settings, read once per browser session)."""
    if "_wn_seen" not in st.session_state:
        conn = connect(DB)
        try:
            st.session_state["_wn_seen"] = prefs.load(conn, LOGIN_ID).get(whats_new.PREF_SEEN, "")
        finally:
            conn.close()
    return whats_new.unseen({whats_new.PREF_SEEN: st.session_state["_wn_seen"]})


def _render_viewing_pick():
    """An advisor's Viewing: their own portfolio or a client's, in the bar."""
    accounts_ = {LOGIN_ID: f"My portfolio ({st.session_state['username']})", **dict(CLIENTS)}
    st.session_state["viewing_select"] = USER_ID
    st.selectbox("Viewing", list(accounts_), format_func=accounts_.get, key="viewing_select",
                 on_change=_on_viewing_change, label_visibility="collapsed", width="stretch")


def _render_add_menu():
    """+ Add holdings: the ways to bring holdings in (a window each)."""
    with st.popover("Add holdings", icon=":material/add:", key="pt_add"):
        if ON_CLIENT:
            st.caption(f"Into **{_md_name(ACTIVE_NAME)}**'s account")
        st.button(":material/content_paste: Paste or type holdings", key="add_manual",
                  width="stretch", type="tertiary", on_click=_open_holdings_dialog,
                  args=("manual",),
                  help="Paste your positions from any brokerage's website, read them from "
                       "screenshots, type them in, or use percentages only.")
        st.button(":material/upload_file: Upload a CSV", key="add_import", width="stretch",
                  type="tertiary", on_click=_open_holdings_dialog, args=("import",),
                  help="A Positions export file from your brokerage.")
        if not HAS_HOLDINGS:
            st.button(":material/science: Try example data", key="add_sample", width="stretch",
                      type="tertiary", on_click=lambda: _load_sample(),  # defined further down
                      help="A made-up portfolio to explore with. Removed when you add your own.")


def _render_name_menu():
    """The name at the foot of the menu (on a phone, top right): who's signed
    in, Account, What's new, About, Admin, the light / dark switch and Log out."""
    with st.popover(MY_NAME, icon=":material/account_circle:", type="tertiary", key="pt_me"):
        if IS_ADVISOR or IS_ADMIN:
            st.html(" ".join(f"<span class='pt-chip pt-role'>{r}</span>"
                             for r, on in (("Advisor", IS_ADVISOR), ("Admin", IS_ADMIN)) if on))
        _viewing = f" · viewing **{_md_name(ACTIVE_NAME)}**" if USER_ID != LOGIN_ID else ""
        st.caption(f"Logged in as **{MY_NAME}**{_viewing}")
        if IS_MANAGED_CLIENT:
            st.caption(f"Your advisor: **{_advisor_display_name()}**")
        if ADVISOR_PENDING:
            st.caption(f":material/hourglass_top: **Advisor access requested** for "
                       f"{_md_name(ADVISOR_REQUEST['firm'])}. We're checking your details - "
                       "usually within two working days. Advisor tools appear once it's "
                       "approved.")
            st.button("While you wait: see what Northwend looks like for an advisor",
                      key="menu_advisor_preview", on_click=_go, args=("Advisor preview",),
                      width="stretch", type="secondary",
                      icon=ACCOUNT_ICONS["Advisor preview"])
        elif ADVISOR_REQUEST and ADVISOR_REQUEST["decision"] == "declined":
            st.caption("Your request for advisor access wasn't approved. Questions: "
                       f"{disclosures.CONTACT}")
        for p in ACCOUNT_MENU:
            # What's new: a small dot until its newest entry has been opened -
            # nothing else draws attention to it (whats_new.py)
            dot = " •" if p == "What's new" and _whats_new_unseen() else ""
            st.button(f"{ACCOUNT_ICONS[p]} {_label(p)}{dot}", key=f"menu_{p}", on_click=_go, args=(p,),
                      width="stretch", type="primary" if PAGE == p else "tertiary")
        # the open beta's Send feedback window, for everyone signed in - always
        # the login's own, even in a client's account (views/feedback.py)
        st.button(f"{ACCOUNT_ICONS['Send feedback']} Send feedback", key="menu_feedback",
                  on_click=_feedback_open, args=(PAGE,), width="stretch", type="tertiary")
        # flips light/dark in the browser (ui_enhancements.js); nothing runs here
        st.button(":material/contrast: Light / dark", key="pt_theme", type="tertiary",
                  width="stretch", help="Switch between the light and dark theme. System, Light "
                                        "and Dark are also in the ⋮ menu at the top right.")
        st.button(":material/logout: Log out", key="menu_logout", on_click=_logout,
                  width="stretch", type="tertiary")


def _side_route_go(key):
    """The menu's "Next: ..." line: that waypoint open on Learn."""
    st.session_state["gs_at"] = key
    st.session_state.pop("gs_goal_part", None)   # Set a goal opens at its first open part
    _go("Get started")


def _render_side_route():
    """At the foot of the menu, above Add holdings: how far along the route
    (route.py) - "Start investing · step 3 of 4", a slim bar of that stage's
    waypoints reached, and the next one as a link to it on Learn. Only for an
    investor's own route (never client mode or an advisor), and only while a
    waypoint is still open. Drawn into its place once Learn's code has run
    (_route_state, views/get_started.py)."""
    if IS_ADVISOR or CLIENT_MODE or "Get started" not in PAGES:
        return
    state = _route_state(HAS_HOLDINGS)
    here = next((k for k, _, d in state["waypoints"] if not d), None)
    if here is None:
        return
    keys = route.stage_keys(route.stage_of(here), state["managed"])
    reached = sum(1 for k in keys if state["done"].get(k))
    with _SIDE_ROUTE.container(key="pt_side_route"):
        st.html(f"<div class='pt-side-route'>"
                f"<div>{html.escape(route.stage_words(here, state['managed']))}</div>"
                f"<div class='pt-side-bar' role='img' aria-label='{reached} of {len(keys)} "
                f"steps reached'><span style='width:{round(100 * reached / len(keys))}%'>"
                f"</span></div></div>")
        st.button(f"Next: {dict(GET_STARTED_STEPS)[here]}", key="side_route_next",
                  type="tertiary", on_click=_side_route_go, args=(here,))


def _render_menu():
    """The menu: the brand, every item, the route's progress, + Add holdings
    and the name menu. On a laptop a column pinned down the left side (the
    styles), with Money's tabs listed under it while one is open; on a phone a
    slim bar along the top with the brand and the two menus as icons - the
    items are in the tab bar along the bottom (_render_tab_bar)."""
    global _SIDE_ROUTE
    with st.container(horizontal=True, vertical_alignment="center", gap="small",
                      key="pt_menu"):
        st.html(_BRAND, width="content")
        for item in NAV:
            if IS_ADVISOR and item == "Dashboard":
                _render_viewing_pick()   # Clients, then whose account, then its pages
            st.button(_nav_label(item), key=f"nav_{item}", on_click=_go,
                      args=(_nav_target(item),),
                      type="primary" if _nav_current(item) else "tertiary")
            if item == MONEY and _nav_current(MONEY):
                for p in MONEY_PAGES:
                    st.button(_label(p), key=f"navsub_{p}", on_click=_go, args=(p,),
                              type="primary" if _nav_current(p) else "tertiary")
        with st.container(horizontal=True, vertical_alignment="center", gap="small",
                          key="pt_menu_foot"):
            _SIDE_ROUTE = st.empty()   # filled by _render_side_route, further down
            if CAN_IMPORT:
                _render_add_menu()
            _render_name_menu()


# Phones: the same items along the bottom (the styles show it only on narrow
# screens), each with its icon above a short label.
TAB_ICONS = {"Get started": (":material/school:", "Learn"),
             "Dashboard": ((":material/pie_chart:", "Portfolio") if IS_ADVISOR
                           else (":material/home:", "Home")),
             "Plan": (":material/flag:", "Plan"), "AI Assistant": (":material/explore:", "Ask"),
             MONEY: (":material/payments:", "Money"), "Life": (":material/folder_open:", "Life"),
             "Advisor notes": ((":material/sticky_note_2:", "Notes") if IS_ADVISOR
                               else (":material/support_agent:", "Advisor")),
             "Clients": (":material/groups:", "Clients")}


def _render_tab_bar():
    with st.container(horizontal=True, key="pt_tabbar"):
        for item in NAV:
            icon, short = TAB_ICONS[item]
            st.button(f"{icon} {short}", key=f"tab_{item}", on_click=_go,
                      args=(_nav_target(item),),
                      type="primary" if _nav_current(item) else "tertiary")


def _render_client_login():
    """An advisor in a client's account: the client's own login - a setup
    link to email or copy, or a password set for them."""
    link = st.session_state.get(f"invite_link_{USER_ID}")
    with st.popover("Client login", icon=":material/key:", type="tertiary",
                    key="pt_client_login"):
        msg = st.session_state.pop("login_msg", None)
        if msg:
            getattr(st, msg[0])(msg[1])
        c = connect(DB)
        try:
            pending = auth.pending_invite(c, USER_ID)
            client_email = auth.email_status(c, USER_ID)["email"]
            has_name = bool((prefs.load(c, LOGIN_ID).get("advisor_card") or {}).get("name"))
        finally:
            c.close()
        if client_email:
            st.button(f"Email {client_email} a setup link", key="invite_email",
                      type="primary", on_click=_email_invite, width="stretch",
                      disabled=not has_name,
                      help="They choose a password, then answer the goals and risk "
                           "questions - you'll see their answers.")
            if not has_name:
                st.caption("First add your name under **Your clients > How clients see "
                           "you** - the invite tells them who it's from.")
        if pending:  # (_fmt_date is defined further down)
            d = datetime.strptime(pending[:10], "%Y-%m-%d")
            until = f"{d:%b} {d.day}"
        st.caption(f"Send **{ACTIVE_NAME}** a setup link to choose their own password "
                   "and see their portfolio - you never need to know it.")
        if link and pending:
            st.code(link, language=None, wrap_lines=True)
            st.caption(f"Copy it and send it privately - it works once, until "
                       f"{until}. Anyone with the link can set "
                       "the password, so don't post it anywhere public.")
        elif pending:
            st.caption(f"A setup link is waiting to be used, until "
                       f"{until}. A new link replaces it.")
        st.button("Create a new setup link" if pending else "Create setup link",
                  key="invite_create", on_click=_create_invite, width="stretch",
                  type="secondary" if client_email else "primary",
                  help="A link to copy and send yourself.")
        if pending:
            st.button("Cancel the link", key="invite_cancel", on_click=_cancel_invite,
                      width="stretch", type="tertiary")
        st.markdown("**Or set a password yourself**")
        st.text_input("New password", type="password", key="client_login_pw")
        st.button("Set login password", on_click=_set_client_password, width="stretch")


# Send feedback (the name menu, the About page): its window (views/feedback.py)
_view("feedback")
_render_menu()
_render_tab_bar()  # phones only (see the styles); fixed to the bottom
# the menus' click-away and the theme switch, names for icon buttons, the
# current tab marked for screen readers, pull to refresh (see the file)
with open(os.path.join(HERE, "ui_enhancements.js"), encoding="utf-8") as _fh:
    st.html(f"<script>{_fh.read()}</script>", unsafe_allow_javascript=True)


def _save_login_pref(key, value):
    """Save one setting of the signed-in login (not the client being viewed),
    keeping the page's cached copy in step - a later settings save writes
    that copy back whole, and would otherwise undo this."""
    c = connect(DB)
    try:
        p = prefs.load(c, LOGIN_ID)
        p[key] = value
        prefs.save(c, LOGIN_ID, p)
    finally:
        c.close()
    cached = st.session_state.get("_prefs")
    if cached and cached[0] == LOGIN_ID:
        cached[1][key] = value


def _disclosures_seen():
    """Remember (per login) that this version of the disclosures was seen."""
    _save_login_pref("disclosures_seen", disclosures.LAST_UPDATED)
    st.session_state["disclosures_seen"] = disclosures.LAST_UPDATED


# An advisor inside a client's account always sees whose it is, at the top of
# every page, with the way back - so nobody edits the wrong person's plan.
# The client's own Get started and their login are here too: they belong to
# this client, not to the advisor's menu.
# (Not on Your clients itself: that page is about every client, not this one.)
if ON_CLIENT and PAGE != "Clients":
    with st.container(border=True, horizontal=True, vertical_alignment="center",
                      key="pt_viewing"):
        st.markdown(f":material/visibility: Viewing **{_md_name(ACTIVE_NAME)}**'s account",
                    width="stretch")
        if "Get started" in PAGES:
            st.button(_label("Get started"), key="viewing_start", icon=":material/route:",
                      type="primary" if PAGE == "Get started" else "tertiary",
                      on_click=_go, args=("Get started",))
        _render_client_login()
        st.button("Back to your clients", key="viewing_back", type="tertiary",
                  on_click=_back_to_clients)


# The disclosures promise to say when they change: once per new version, after
# sign-in (and once for everyone at first). Opening About counts as seen.
if "disclosures_seen" not in st.session_state:
    _dc = connect(DB)
    try:
        st.session_state["disclosures_seen"] = prefs.load(_dc, LOGIN_ID).get("disclosures_seen")
    finally:
        _dc.close()
if PAGE == "About" and st.session_state["disclosures_seen"] != disclosures.LAST_UPDATED:
    _disclosures_seen()


def _agree_now():
    """The one-time ask below: keep that this login agreed, and to which version."""
    if not (st.session_state.get("terms_adult") and st.session_state.get("terms_us")
            and st.session_state.get("terms_agree")):
        return
    c = connect(DB)
    try:
        auth.record_agreement(c, LOGIN_ID, disclosures.LAST_UPDATED, via=auth.TERMS_VIA_SIGN_IN)
    finally:
        c.close()
    _disclosures_seen()
    st.toast("Thank you - you won't be asked again.", icon=":material/check:")


# Everyone agrees to the About and disclosures once. Sign-up and a client's
# setup link ask on the way in; an account an advisor or admin made that got
# in another way (a temporary password, a reset link, or before the setup link
# asked) is asked here, once, on any page - calmly, without blocking anything.
# Admins run the app, so they aren't asked.
if not _me["agreed"] and not IS_ADMIN:
    with st.container(border=True, key="pt_agree"):
        st.markdown(f":material/handshake: **One quick thing.** Please read {APP_NAME}'s About "
                    "and disclosures - what it is, how your data is used and what's sent to "
                    f"the AI - and its [Terms of Use]({disclosures.TERMS_URL}) and "
                    f"[Privacy Policy]({disclosures.PRIVACY_URL}), and agree to them. You only "
                    "need to do this once.")
        st.checkbox(f"I'm {disclosures.MIN_AGE} or older", key="terms_adult")
        st.checkbox(US_RESIDENT_BOX, key="terms_us")
        st.checkbox(AGREE_BOX, key="terms_agree")
        with st.container(horizontal=True):
            st.button("Agree", key="terms_ok", type="primary", on_click=_agree_now,
                      disabled=not (st.session_state.get("terms_adult")
                                    and st.session_state.get("terms_us")
                                    and st.session_state.get("terms_agree")))
            if PAGE != "About":
                st.button("Read it", key="terms_read", type="tertiary", on_click=_go,
                          args=("About",))
elif st.session_state["disclosures_seen"] != disclosures.LAST_UPDATED:
    with st.container(border=True, horizontal=True, vertical_alignment="center"):
        st.markdown(f":material/info: **About and disclosures** - what {APP_NAME} is, how your "
                    "data is used and what's sent to the AI - "
                    + ("was updated on " + disclosures.LAST_UPDATED + "."
                       if st.session_state["disclosures_seen"] else "worth a quick read."),
                    width="stretch")
        st.button("Read it", key="disc_read", on_click=lambda: (_disclosures_seen(), _go("About")))
        st.button("Got it", key="disc_ok", type="tertiary", on_click=_disclosures_seen)

# A client whose sharing with their advisor was never confirmed in their own
# words is asked once, the same calm way (consent.to_ask; PLAN step 5.7)
_view("consent_ask")


def _resend_confirmation():
    sent, note = _send_confirmation(LOGIN_ID)
    st.session_state["email_flash"] = (sent, note)


# A self-serve account's email waits to be confirmed (auth.confirm_email): a
# notice with "Send it again" until it is. Looked up each run only while
# waiting - the link may be opened in another tab - then remembered.
if st.session_state.get("email_state") is None:
    if _gate is not None:   # the row the two-step gate read at the top of this run
        _es = auth.email_status_of(_gate[1])
    else:
        _ec = connect(DB)
        try:
            _es = auth.email_status(_ec, LOGIN_ID)
        finally:
            _ec.close()
    if not _es["email"] or _es["confirmed"]:
        st.session_state["email_state"] = "done"
    _waiting_email = None if st.session_state.get("email_state") else _es["email"]
else:
    _waiting_email = None
_email_flash = st.session_state.pop("email_flash", None)
if _email_flash:
    (st.success if _email_flash[0] else st.warning)(_email_flash[1])
if _waiting_email and st.session_state.get("email_brief"):
    with st.container(horizontal=True, vertical_alignment="center", gap="small",
                      key="pt_email_brief"):
        st.caption(f":material/mail: We've sent a link to {_waiting_email} - confirm any time."
                   + (" Advisor tools appear once we've checked your details."
                      if st.session_state.get("email_brief") == "advisor" else ""),
                   width="content")
        st.button("Send it again", key="email_resend", type="tertiary",
                  on_click=_resend_confirmation)
elif _waiting_email:
    with st.container(border=True, horizontal=True, vertical_alignment="center"):
        st.markdown(f":material/mail: **Confirm your email** - open the link we sent to "
                    f"{_waiting_email}. It unlocks Ask {GUIDE} and the other AI features, and "
                    "lets you reset your password if you forget it.", width="stretch")
        st.button("Send it again", key="email_resend", on_click=_resend_confirmation)


def _anthropic_key() -> str | None:
    """Same resolution order as resolve_key() uses for FINNHUB_API_KEY -
    .env locally, then the OS environment (which is how Streamlit
    Community Cloud exposes its Secrets UI entries). None if unset -
    every AI-assisted-parsing call site treats that as "skip the AI
    fallback, strict parsing only," today's exact behavior."""
    return settings.get("ANTHROPIC_API_KEY", env_file=True) or None


def _ai_status(kind, *, full_run=False, conversation_open=False):
    """This month's AI allowance for `kind` (ai_usage.py) of whoever is signed
    in - an advisor in a client's account uses their own - with the app-wide
    ceiling's say (ai_spend.apply: "level", and "resting_why" when the feature
    rests this month). `full_run`: the caller is drawn in the page's full run
    (not in a fragment or a window), so the login's row the two-step gate read
    at the top of this run is used rather than read again; the count used so
    far is always read. `conversation_open`: chat only - a conversation
    already under way may finish once new ones have closed (95%)."""
    gate = _gate_read(LOGIN_ID) if full_run else None
    c = connect(DB)
    try:
        st_ = ai_usage.status(c, LOGIN_ID, kind, user=gate[1] if gate else None)
        level = ai_spend.level(c)
    finally:
        c.close()
    return ai_spend.apply(st_, level, kind, conversation_open=conversation_open)


def _ai_record(kind):
    """Count one AI use against the signed-in account - only once it has
    succeeded, so a failed one doesn't use up the allowance. (Its cost is
    added by the AI gateway itself, ai_gateway._record; this count is what
    turns cost left into "about N left".)"""
    c = connect(DB)
    try:
        ai_usage.record(c, LOGIN_ID, kind)
    finally:
        c.close()


def _ai_failed(exc, kind, feature=""):
    """An AI request (`kind`, ai_usage.KINDS) failed: the details go to the
    server log, a key or set-up problem is noted for the admin like any other
    error (error_alerts.py: its type and place only), and what to show comes
    back - one calm sentence per kind of failure, never the error's text. A
    call the gateway didn't make (ai_gateway.Refused: an allowance or the
    month's level) brings its own calm sentence and alerts no one."""
    ai_usage.log_failure(exc, kind)
    if ai_usage.failure_kind(exc) == ai_usage.UNAVAILABLE:
        try:
            import error_alerts
            error_alerts.report(DB, exc, copy="Staging" if STAGING else "Live",
                                send=settings.send_error_alerts())
        except Exception:
            pass
    return ai_usage.failure_text(exc, GUIDE, feature)


LIMIT_TEXT = rate_limits.CALM   # over a limit on uploads, saves or downloads: calm, not an error


def _limit_ok(action):
    """Whether the signed-in login may do `action` (rate_limits.UPLOAD, SAVE,
    EXPORT) now - True counts it. An advisor in a client's account counts
    against the advisor (LOGIN_ID), never the client. When it's False the
    caller shows LIMIT_TEXT and reads, saves or builds nothing (audit 1.8d)."""
    c = connect(DB)
    try:
        return rate_limits.allow(c, LOGIN_ID, action)
    finally:
        c.close()


def _upload_ok(up):
    """An uploaded file (st.file_uploader's) may be read: each new file counts
    once against rate_limits.UPLOAD - not each time the page redraws while it
    sits in the uploader."""
    seen = st.session_state.setdefault("limit_uploads_seen", [])
    fid = getattr(up, "file_id", None) or f"{up.name}:{up.size}"
    if fid in seen:
        return True
    if not _limit_ok(rate_limits.UPLOAD):
        return False
    seen[:] = (seen + [fid])[-20:]   # the last few files only
    return True


def _limit_hit(where):
    """A button callback was over a limit: say so (LIMIT_TEXT) next to that
    button on the next run - see _limit_note."""
    st.session_state["limit_hit"] = where


def _limit_note(where):
    """Show LIMIT_TEXT here if the click at `where` was over a limit."""
    if st.session_state.get("limit_hit") == where:
        st.session_state.pop("limit_hit", None)
        st.info(LIMIT_TEXT)


CHAT_MESSAGE_LIMIT = 30  # per conversation - keeps each one a sensible length (AI_PLAN 10.2)
CHAT_MAX_CHARS = 2000    # one question's length (audit 1.3b)
QUICK_STARTS = {
    "Help me get started": "I'm new to investing. Help me figure out how to get started.",
    "Review my portfolio": "Walk me through how my current portfolio compares with my goals, "
                           "and what people usually look at in a mix like mine.",
    "Check for overlap and concentration": "Check my holdings for overlap between funds, and "
                                           "show how much of the portfolio is in any one "
                                           "holding.",
}
# ...and before anything is invested: nothing to review yet. Each asks for
# general education, never a conclusion about the person (COPY_AUDIT.md)
QUICK_STARTS_NEW = {
    "Help me get started": QUICK_STARTS["Help me get started"],
    "What do people do before investing?": "I haven't started investing yet. What do people "
                                           "usually take care of first, and in what order?",
    "What kinds of accounts are there?": "What's the difference between a regular brokerage "
                                         "account, a Roth IRA and a 401(k)? Which questions "
                                         "should I ask myself to pick one?",
}


def _legacy_prefs_path(account_id):
    return os.path.join(HERE, f".dashboard_prefs.{account_id}.json")


def _rules_for(account_id, conn=None):
    """That account's saved alert limits, else defaults."""
    c = conn or connect(DB)
    try:
        saved = prefs.load(c, account_id, _legacy_prefs_path(account_id))
    finally:
        if conn is None:
            c.close()
    return _rules_from(saved)


def _rules_from(saved_prefs):
    """The alert limits in an account's settings (prefs.load), else defaults."""
    saved = saved_prefs.get("rules") or {}
    if not isinstance(saved, dict):
        saved = {}
    return [{**r, "abs_gt": float(saved.get(r["key"], r["abs_gt"]))} for r in alerts.DEFAULT_RULES]


# the advisor agreement before Your clients, and the standing line's helpers
_view("advisor_agreement")

# "Draft with Northwend" for proposals, messages and reports (advisor_drafts.py)
_view("drafts")

_view("clients")

# the advisor directory: Find a guide, and the advisor's listing (directory.py)
_view("directory")
# introductions and the two-step consent to full sharing (intros.py), drawn
# inside Find a guide and Your clients
_view("intros")


_view("meeting")


_view("reports")


_view("admin")

# the signed-in person's own account (name, email, password, data)
_view("account")

# What's new: the dated list of changes, from the name menu (whats_new.py)
_view("whats_new")


_view("profile")


_view("plan")


_view("proposals")

# "See what you'll get": made-up clients while advisor access is pending
_view("advisor_demo")


# milestones and gear: the "milestone reached" window and Your kit (gear.py)
_view("kit")

# notes to future you: on a holding, on the plan, back on a storm (future_notes.py)
_view("future_notes")

# the Monthly Walk on Home (it grew out of the monthly check-in), and its
# settings on Account (checkin.py)
_view("checkin")

# Home: this week's preparedness drill and the readiness map, flag drills (drills.py)
_view("drills")
# ...and inside its card, this month's world, flag month_world (month_world.py)
_view("month_world")
# Home and Learn: this month's practice challenge, flag challenges (challenges.py)
_view("challenges")

# Fee check: each fund's yearly fee in dollars, in a window (fees.py)
_view("fees")

# Fund overlap: do the funds hold the same companies? (fund_holdings.py)
_view("fund_overlap")

# Cash check, and Home's "Your money, checked" card (fees, overlap, cash)
_view("cash_check")

# Plan: Stress test your mix (stress.py)
_view("stress_test")

# Plan: Pay yourself, flag pay_yourself + gate L3 (pay_yourself.py)
_view("pay_yourself")

# Plan and Home: where the next deposit could go (next_deposit.py)
_view("next_deposit")

# Learn and Plan: the employer match calculator (employer_match.py)
_view("free_money")

# Home: what you did vs what the market did, flag progress_split (progress_split.py)
_view("progress_split")

# Home and Plan: your wins, flag wins (wins.py) - uses progress_split's one read
_view("wins")

# beside it: the 401(k) Menu Decoder, flag decoder_401k (menu_decoder.py)
_view("menu_decoder")

# and the Fact Sheet Decoder, flag decoder_factsheet (factsheet_decoder.py)
_view("factsheet_decoder")

# Home: Year in review, private, and a version to share (recap.py)
_view("year_review")

# Life page: the account map, and its line on Home (account_map.py)
_view("account_map")

# just under it: Lost & Found, flag lost_found (lost_found.py)
_view("lost_found")

# and under that: Trail Forks, flag trail_forks (trail_forks.py)
_view("trail_forks")
# Bring to my advisor, flag advisor_pack (advisor_pack.py): the client's
# choices on Account, the advisor's card over meeting prep, the season note
_view("advisor_pack")
# the Client-Owned Book, flag client_owned_book + gate L2 (client_book.py):
# counts, client-reported labels and walk signals in Your clients; the
# client's walk-sharing switch and what each side keeps after an exit
_view("client_book")
# and under that: the Inheritance Rehearsal, flag inheritance_rehearsal
# (inheritance_rehearsal.py)
_view("inheritance_rehearsal")
# Doing it together, flag together (together.py): a section on Life
_view("together")
# the Life page that draws them (an advisor's own are on Account)
_view("life")
# the Four Seasons: a card on Home in season, a line on Learn, flag seasons (seasons.py)
_view("seasons")
# weekly summaries: "Your week" and "The week ahead", a card on Home, flag weekly (weekly.py)
_view("weekly")
# Teach It Back (flag teach_back): "Explain it back in your own words" in
# Learn's basics window - defined here, drawn by views/get_started.py
_view("teach_back")
# Today's minute (flag money_minute): one small card a day at the top of Home's
# This month column - defined here, drawn by views/dashboard_page.py and
# views/start_home.py (money_minute.py)
_view("money_minute")

# a new investor's first steps, one screen at a time (Get started shows it)
_view("first_steps")
_view("get_started")


_view("assistant")


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


def fmt_pct(v, signed=True):
    """A percent. Signed ("+0.87%") for a change - a day's move, a gain, a
    return; signed=False ("0.87%") for a level - a yield, a share of the
    portfolio (fmt_pct_level, the metrics' "pct_level")."""
    if _hidden():
        return MASK
    return "—" if _blank(v) else (f"{v:+.2f}%" if signed else f"{v:.2f}%")


def fmt_pct_level(v):
    return fmt_pct(v, signed=False)


def color_sign(v):
    if _hidden() or v is None or pd.isna(v) or v == 0:
        return ""
    up, down = SIGN_COLORS["dark" if st.context.theme.type == "dark" else "light"]
    return f"color: {up if v > 0 else down}; font-weight: 600"


def fmt_price(v):
    return MASK if _hidden() else ("—" if _blank(v) else f"${v:,.2f}")


def fmt_qty(v):
    return "—" if _blank(v) else f"{v:,.4f}".rstrip("0").rstrip(".")


def fmt_num(v):
    return MASK if _hidden() else ("—" if _blank(v) else f"{v:,.2f}")


def fmt_int(v):
    return MASK if _hidden() else ("—" if _blank(v) else f"{v:,.0f}")


FORMATTERS = {"money": fmt_money, "pct": fmt_pct, "pct_level": fmt_pct_level,
              "price": fmt_price, "qty": fmt_qty, "num": fmt_num, "int": fmt_int}

# axis / tooltip number format string per metric-format name
AXIS_FORMAT = {"money": charts.MONEY_AXIS, "price": "$,.2f", "pct": ".2f", "pct_level": ".2f",
               "int": "d", "num": ",.2f"}
TOOLTIP_FORMAT = {"money": "$,.2f", "price": "$,.2f", "pct": ".2f", "pct_level": ".2f",
                  "int": "d", "num": ",.2f"}


def _stat_tiles(ctx, keys, ncols=4):
    """A compact label/value grid for a list of metrics.py keys — the
    Robinhood-style "stats" block under a ticker's chart. Skips keys with no
    registered metric; renders '—' for a None value like the Holdings table."""
    keys = [k for k in keys if k in M.BY_KEY]
    if not keys:
        return
    # one row of columns per ncols stats, so a phone (where columns stack;
    # two per line there, .st-key-pt_stat_tiles) keeps the reading order
    with st.container(key="pt_stat_tiles"):
        for start in range(0, len(keys), ncols):
            for col, k in zip(st.columns(ncols), keys[start:start + ncols]):
                m = M.BY_KEY[k]
                v = M.value(k, ctx)
                text = FORMATTERS[m.fmt](v) if m.fmt in FORMATTERS else ("—" if _blank(v) else str(v))
                with col:
                    st.caption(m.label)
                    if m.color_sign and not _hidden() and not _blank(v) and v != 0:
                        st.markdown(f"<span class='{'pt-up' if v > 0 else 'pt-down'}' "
                                    f"style='font-weight:600'>{text}</span>", unsafe_allow_html=True)
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
            f"<div class='pt-alloc-bar' aria-hidden='true'>{segs}</div>"
            f"<div class='pt-legend'>{legend}</div>")


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
        segs, tips = "", []
        for m in mix:
            if (m["value"] or 0) <= 0:
                continue
            i = slots.get(m["label"])
            tip = m["label"] if _hidden() or m["pct"] is None else f"{m['label']} {m['pct']:.1f}%"
            tips.append(tip)
            segs += (f"<div class='pt-alloc-seg' style='flex:{m['value']} 0 0;"
                     f"background:{colors[i] if i is not None else SERIES_OTHER}' "
                     f"title='{_h.escape(tip, quote=True)}'></div>")
        pct = MASK if _hidden() or r["pct"] is None else f"{r['pct']:.1f}%"
        out += ("<div class='pt-acct'><div class='pt-legend-row'>"
                f"<span class='pt-legend-label'>{_h.escape(acct)}</span>"
                f"<span class='pt-legend-pct'>{pct}</span>"
                f"<span class='pt-legend-val'>{fmt_money(r['value'])}</span></div>"
                # the mix is only in the segments' tooltips, so say it for screen readers
                f"<div class='pt-alloc-bar pt-mini' role='img' aria-label="
                f"'{_h.escape(acct + ' mix: ' + ', '.join(tips), quote=True)}'>{segs}</div></div>")
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
            data = prefs.load(conn, USER_ID, PREFS_PATH)
        finally:
            conn.close()
        # the third part: the settings as read, to tell what this session changed
        cached = (USER_ID, data, json.dumps(data))
        st.session_state["_prefs"] = cached
    return dict(cached[1])


def _write_prefs(d):
    """Save this account's settings. Only what this session changed since it
    read them is written over what's saved now (prefs.merge): another tab,
    the client on their phone, or their advisor may have saved since."""
    cached = st.session_state.get("_prefs")
    conn = connect(DB)
    try:
        if cached and cached[0] == USER_ID and len(cached) > 2:
            d = prefs.merge(json.loads(cached[2]), d, prefs.load(conn, USER_ID))
        prefs.save(conn, USER_ID, d)
    finally:
        conn.close()
    st.session_state["_prefs"] = (USER_ID, dict(d), json.dumps(d))


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


# Read once per run: what several parts of one page need. This script runs
# afresh on every rerun, so it starts empty each time (a click's callback has
# already saved its change). A fragment's or window's own rerun still sees the
# last full run's, so keep here only what changes by a full rerun - never what
# a fragment itself saves (the Plan tabs read their own).
_RUN = {}
# each holding's asset-class split (asset_classes.py), worked out once the
# holdings are loaded below; empty until then, so the pages drawn before
# anything is brought in (Ask Northwend, meeting prep) can use it too
CLASS_SPLITS = {}


def _profile():
    """This account's investor profile (advisor.get_profile), read once per
    run - Home's route card and kit, Get started, the first steps and the map
    plate above the title all use it. Saving it (the profile form, then
    st.rerun; a first steps button's callback) starts a new run. The guide's
    notes share its row, so they're kept too (Ask Northwend's _assist_profile)."""
    if "profile" not in _RUN:
        import advisor
        conn = connect(DB)
        try:
            _RUN["profile"], _RUN["memory"] = advisor.get_profile_and_memory(conn, USER_ID)
        finally:
            conn.close()
    return dict(_RUN["profile"])


# the route's progress at the foot of the menu (drawn above, filled in here,
# once Learn's _route_state and what it reads are defined)
_render_side_route()


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


def save_alloc_targets(targets: dict, by: str = "own"):
    """The plan's target mix, and where it came from (checkin.note_target:
    "own", "advisor", or "example" - Northwend's example mix taken untouched,
    which the Walk then asks about, LEGAL_GATES.md C3)."""
    import checkin
    save_plan_fields({"target_alloc": {k: v for k, v in targets.items() if v}})
    if ON_CLIENT and by == checkin.TARGET_OWN:
        by = checkin.TARGET_ADVISOR   # an advisor saving in a client's account
    p = _read_prefs()
    checkin.note_target(p, by, targets)
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


def load(conn):
    """Return (snapshot_date, positions, cash_by_account, quotes, watchlist
    tickers), read on `conn`. The snapshot is the one found at the top of
    this run (holdings are only saved in a callback or a window, each
    followed by a new run)."""
    snap = _LATEST_SNAPSHOT
    import overview
    if not snap:
        # nothing brought in yet - the watchlist still works (Learn's example
        # funds go on it before anything is bought), and so does News
        watch = (watchlist.list_tickers(conn, USER_ID)
                 if PAGE in ("Watchlist", "News", TICKER_PAGE) else [])
        return None, [], {}, overview.latest_quotes(conn, sorted(watch)) if watch else {}, watch
    rows = snapshot_positions(conn, USER_ID, snap)
    cash_by_account = snapshot_cash(conn, USER_ID, snap)
    # the latest quote of each ticker this account holds or watches - not
    # every ticker in price_history, which grows every minute
    watch = watchlist.list_tickers(conn, USER_ID)   # read once: the Watchlist uses it too
    quotes = overview.latest_quotes(conn, sorted({r["symbol"] for r in rows} | set(watch)))
    # Nicknames replace the broker's account names from here on (display
    # only); the broker's name stays available as "broker_account".
    positions = [dict(r) for r in rows]
    for p in positions:
        p["broker_account"] = p["account"]
        p["account"] = accounts.display(p["account"], ACCOUNT_LABELS)
    cash_by_account = {accounts.display(a, ACCOUNT_LABELS): v for a, v in cash_by_account.items()}
    return snap, positions, cash_by_account, quotes, watch


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


_view("holdings_input")


_view("start_home")


def _toggle_hide():
    st.session_state["hide_amounts"] = not st.session_state.get("hide_amounts", False)
    save_hide(st.session_state["hide_amounts"])


# Where prices come from, said once per page on the status line (and beside a
# single ticker's price): Finnhub for stocks, Yahoo Finance (unofficial,
# through yfinance) for funds, crypto and price history - see live_prices.py,
# update_prices.py, sync_history.py. Either can lag the market.
PRICE_SOURCE = "Prices from Finnhub and Yahoo Finance, may be delayed 15 minutes or more"


@st.fragment(run_every=LIVE_EVERY_SEC)
def _live_status():
    """Keeps prices current without a Refresh button: every minute (only this
    line reruns) it fetches whatever quotes are due (live_prices.freshen -
    shared across everyone viewing, so each ticker is asked for at most once a
    minute), then redraws the page if any price changed. It waits while a
    dialog is open, so it never interrupts adding holdings."""
    ss = st.session_state
    try:
        # what this page run loaded (holdings and the watchlist only change
        # by a save, which starts a new run) - not read again every minute.
        # freshen opens its own connections: none is held while it fetches.
        # `applied`: a price another tab fetched since this page's last one
        # is applied too (with many tabs open, one fetches and others skip)
        live = live_prices.freshen(
            lambda: connect(DB), USER_ID, resolve_key(None, ENV_PATH),
            known=(snapshot, {p["symbol"]: p["asset_type"] for p in positions},
                   list(watch_tickers)), applied=last_live)
    except Exception:  # noqa: BLE001 - prices failing must never break the page
        live = {"updated": 0, "as_of": None, "live": False}
    if (live["updated"] or (PAGE == "Watchlist" and live.get("watch_fetched"))) \
            and not ss.get("dialog_open"):
        st.rerun()  # the whole page, with the new prices
    as_of = live["as_of"] or live_prices._parse(last_live)
    if live["live"] and as_of:
        age = (datetime.now(timezone.utc) - as_of).total_seconds()
        ago = ("just now" if age < 90 else f"{int(age // 60)} min ago" if age < 3600
               else _fmt_when(as_of))
        prices = f"<span class='pt-live' aria-hidden='true'>●</span> Live · prices updated {ago}"
    elif as_of:
        # "Oct 3 close" (price_report.as_of: the market's own clock, ET)
        prices = f"Market closed · prices as of {price_report.as_of(as_of)['text']}"
    else:
        prices = "No live prices yet"
    if n_live < len(positions):
        prices += f" ({n_live} of {len(positions)} priced)"
    _what = {manual_entry.SOURCE: "Entered by hand", manual_entry.PCT_SOURCE: "Percentages",
             SAMPLE_SOURCE: "Example portfolio"}.get(SNAPSHOT_SOURCE, "Statement")
    st.html(f"<div class='pt-status'>{prices}"
            # the watchlist before anything is brought in: no holdings to date
            + (f" · {_what} from {_fmt_date(snapshot)}" if snapshot else "")
            + f"<br>{PRICE_SOURCE}.</div>")


def _expedition_eyebrow():
    """The map plate above an investor's Home and Get started title: where
    they are on the route (route.region) - "Learner's ridge · your expedition"."""
    state = _route_state(HAS_HOLDINGS)
    waypoints = state["waypoints"]   # their route (views/get_started.py)
    here, _next = route.region(waypoints)
    if PAGE == "Get started":
        n = sum(d for _, _, d in waypoints)
        return f"{here} · {n} of {len(waypoints)} waypoints reached"
    return f"{here} · your expedition"


def _money_tabs():
    """Money's tabs: Income, Activity and Watchlist, a page each (?page=income
    and so on), so links to any of them keep working."""
    with st.container(horizontal=True, gap="small", key="pt_money_tabs"):
        for p in MONEY_PAGES:
            st.button(_label(p), key=f"money_{p}", on_click=_go, args=(p,),
                      type="primary" if PAGE == p else "tertiary")


_HOME_HERO = None   # Home's place for the value on its band (_page_header)
_PAGE_MAIN = None   # a Money page's main card (_money_parts), else None
_PAGE_SIDE = None   # a Money page's right-hand panel (_money_parts), else None
# the slim band's pages, besides Money's (_band_kind): Plan, Learn, Life, Ask
# Northwend and a ticker's own page. On Life and Ask a line goes under the
# title (_slim_band_line)
BAND_PAGES = ("Plan", "Get started", "Life", "AI Assistant", TICKER_PAGE)


def _band_kind():
    """Which deep blue band the page opts into (_band_css): Home's tall one
    ("home", key pt_home_band), the slimmer one with the title ("slim", key
    pt_page_band) on Plan, Money, Learn, Life and Ask Northwend, or none.
    Sign-in, the agree box and windows never have one - they are drawn
    before or apart from the page."""
    if PAGE == "Dashboard":
        return "home"
    if PAGE in BAND_PAGES or PAGE in MONEY_PAGES:
        return "slim"
    return None


def _slim_band_line():
    """The line under the slim band's title, or None."""
    if PAGE == "Life":
        return LIFE_INTRO   # views/life.py
    if PAGE == "AI Assistant":
        return ASSIST_LINE if USER_ID == LOGIN_ID else ASSIST_LINE_ADVISOR   # views/assistant.py
    return None


def _page_main():
    """Where a Money page draws its content: the main card when the page is
    in two parts (_money_parts), else just the page."""
    return _PAGE_MAIN if _PAGE_MAIN is not None else contextlib.nullcontext()


def _money_parts():
    """Money's two parts under its band (Style C): the page's content in one
    white card in the middle, and on the right the accounts (and, on Income,
    the year ahead - views/income.py). Built from the holdings already loaded:
    no reads of its own. One column up to 900px wide."""
    global _PAGE_MAIN, _PAGE_SIDE
    side = bool(acct_value)   # (none: the watchlist alone, nothing held)
    with st.container(horizontal=True, gap="medium", key="pt_page_layout"):
        with st.container(key="pt_page_main"):
            _PAGE_MAIN = st.container(border=True, key="pt_money_card")
        _PAGE_SIDE = st.container(key="pt_page_side", gap="small") if side else None
    if _PAGE_SIDE is not None:
        with _PAGE_SIDE:
            _money_accounts_card()


def _money_accounts_card():
    """Each account and its value now, largest first - or its share of the
    whole for a percentages portfolio (pretend dollars). Masked when hidden."""
    pct_only = SNAPSHOT_SOURCE == manual_entry.PCT_SOURCE
    st.html(f"<div class='pt-month-title'>{MONEY_ACCOUNTS_TITLE}</div>")
    with st.container(border=True, key="pt_money_accounts"):
        rows = ""
        for name, v in sorted(acct_value.items(), key=lambda kv: -(kv[1] or 0.0)):
            shown = (mask_or(f"{(v or 0.0) / portfolio_value * 100:.0f}%")
                     if pct_only and portfolio_value else fmt_money0(v))
            rows += (f"<div class='pt-acct-row'><span class='pt-acct-name'>"
                     f"{html.escape(str(name))}</span>"
                     f"<span class='pt-acct-val'>{html.escape(shown)}</span></div>")
        st.html(f"<div class='pt-acct-list'>{rows}</div>")
        if pct_only:
            st.caption(MONEY_ACCOUNTS_PCT)


MONEY_ACCOUNTS_TITLE = "Accounts"
MONEY_ACCOUNTS_PCT = "Each account's share of the whole."
MONEY_INCOME_TITLE = "Income ahead"
MONEY_INCOME_LINE = "About {total} over the next 12 months, estimated."


def _page_header(title, *, data=True):
    """The page's title with the hide-amounts toggle and, on `data` pages
    (this account's portfolio), a status line that keeps prices current by
    itself (_live_status) - there's no Refresh button. Adding or updating
    holdings is the menu's + Add holdings. An investor's Home and
    Get started carry the map plate above the title (_expedition_eyebrow).
    Income, Activity and Watchlist are the Money page's tabs: their title is
    Money, with the tabs under it (_money_tabs)."""
    global _HOME_HERO, _PAGE_MAIN, _PAGE_SIDE
    _PAGE_MAIN = _PAGE_SIDE = None
    if PAGE in MONEY_PAGES:
        title = MONEY
    if PAGE == TICKER_PAGE:
        title = st.session_state["ticker_sym"]
    home = PAGE == "Dashboard"
    band = _band_kind()
    # Home's deep blue band (_band_css): the title, the value and today's
    # change (written into _HOME_HERO by views/dashboard_page.py) and the
    # status line sit on it; the cards after it overlap its foot. Plan, Money,
    # Learn, Life and Ask have the slimmer one: the title, the status line,
    # Money's tabs and on Life and Ask a line under the title (_slim_band_line)
    with (st.container(key="pt_home_band" if band == "home" else "pt_page_band")
          if band else contextlib.nullcontext()):
        # (an advisor's client's Home is their advisor's next step, not an expedition)
        if INVESTOR_VIEW and not IS_ADVISOR and (PAGE == "Get started"
                                                 or home and not CLIENT_MODE):
            st.html(f"<div class='pt-eyebrow'>{html.escape(_expedition_eyebrow())}</div>")
        if PAGE == TICKER_PAGE:   # a ticker's page: back to where it was opened
            back = st.session_state.get("ticker_from") or "Dashboard"
            st.button(f"Back to {_label(back)}", key="ticker_back", type="tertiary", icon=":material/arrow_back:",
                      on_click=_go, args=(back,))
        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            st.title(title, anchor=False, width="stretch")
            # Learn (and first steps, shown in its place) has nothing of theirs to
            # hide: examples and practice money only. The setting still holds.
            if PAGE != "Get started":
                st.button(":material/visibility_off:" if _hidden() else ":material/visibility:",
                          key="pt_hide", type="tertiary", on_click=_toggle_hide,
                          help="Show amounts" if _hidden() else "Hide amounts - mask every "
                                                                 "dollar and percent with " + MASK)
        if band == "slim" and _slim_band_line():
            st.caption(_slim_band_line())
        # Home's value, or a ticker's name (views/ticker_detail.py)
        _HOME_HERO = st.container() if (home or PAGE == TICKER_PAGE) and data else None
        if data:
            _live_status()
        if PAGE in MONEY_PAGES:
            _money_tabs()
    if data:
        if SNAPSHOT_SOURCE == SAMPLE_SOURCE:
            with st.container(border=True, horizontal=True, vertical_alignment="center"):
                st.markdown(":material/science: **This is an example portfolio** - made-up "
                            "holdings to explore with. It's removed as soon as you import or "
                            "enter your own.", width="stretch")
                if CAN_IMPORT:
                    st.button("Remove example", key="pt_clear_sample", on_click=_clear_sample)
        elif SNAPSHOT_SOURCE == manual_entry.PCT_SOURCE:
            st.caption(":material/percent: A percentages portfolio - dollar amounts are pretend, "
                       "scaled to the total you chose. Change it with **Add holdings** at the top: "
                       "**Paste or type holdings**.")

    # the result of a refresh / sync / import that happened just before the rerun
    _msg = st.session_state.pop("refresh_msg", None)
    if _msg:
        getattr(st, _msg[0])(_msg[1])
    _flash = st.session_state.pop("import_flash", None)
    if _flash:
        st.success(_flash)
    render_future_note_nudge()   # after a first save of holdings (views/future_notes.py)
    if data and PAGE in MONEY_PAGES:
        _money_parts()


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


# ---- calm by default (ROADMAP S6): a summary first, detail in a window ---- #
def _show_everything():
    """True for the full pages: advisors always, and an investor who turned on
    Show everything on the Account page. Otherwise Income, Activity, Watchlist
    and Ask Northwend lead with a short summary and open the detail in a window."""
    return IS_ADVISOR or bool(_read_prefs().get("show_everything"))


_THOUSANDS_COMMA = re.compile(r"(?<=\d),(?=\d{3}\b)")


def _stat_row(markup):
    """A row of stat boxes (.pt-stats) with a line-break chance after each
    thousands comma: on a phone a box can be about 90px wide, so a long
    amount goes onto two lines at a comma instead of being cut off (the
    phone styles let .pt-stat-value wrap; on a wider screen it fits)."""
    return _THOUSANDS_COMMA.sub(",<wbr>", markup)


def _summary_stats(items):
    """A row of small stat boxes (.pt-stats): [(label, value_html, sub_html or None)].
    Values are already formatted (and masked) by the caller. A list to screen
    readers, one item per box, so each reads as its label then its value."""
    st.html(_stat_row(
            "<div class='pt-stats' role='list' aria-label='Summary' style='margin-top:.25rem'>"
            + "".join(
                "<div class='pt-stat' role='listitem'>"
                f"<div class='pt-stat-label'>{html.escape(label)}</div>"
                f"<div class='pt-stat-value'>{value}</div>"
                + (f"<div class='pt-stat-sub'>{sub}</div>" if sub else "") + "</div>"
                for label, value, sub in items) + "</div>"))


def _next_step_card(key, line, button=None):
    """One next step under a page's summary, in the Fee check card's look:
    `line` is HTML; `button` is (label, on_click or None, args) or None.
    Returns whether the button was pressed (to open a window with it)."""
    with st.container(border=True, horizontal=True, vertical_alignment="center",
                      key=f"pt_next_{key}"):
        # one sentence to a screen reader: "Next step: ..." (the button's icon
        # is left out of its name by ui_enhancements.js)
        st.html("<div class='pt-route-label'>Next step<span class='pt-sr'>:</span></div>"
                f"<div class='pt-region'>{line}</div>",
                width="stretch")
        if button:
            label, on_click, args = button
            return st.button(label, key=f"next_{key}", type="tertiary", on_click=on_click,
                             args=args)
    return False


def _dialog_free():
    """Whether no window has opened yet in this run: streamlit allows one at a
    time, and a window kept open by its state (a season, the week, a drill,
    the storm note, a milestone) waits its turn rather than break the page."""
    from streamlit.runtime.scriptrunner import get_script_run_ctx
    ctx = get_script_run_ctx()
    return not (ctx is not None and getattr(ctx, "has_dialog_opened", False))


def _open_window(window, *args):
    """Open a detail window (an st.dialog); live prices wait while it's open."""
    st.session_state["dialog_open"] = True
    window(*args)


def _detail_tiles(tiles):
    """Summary tiles in a row, each opening its detail in a window:
    [(key, icon, title, summary, button label, window, args)]."""
    if not tiles:
        return
    cols = st.columns(len(tiles))
    for col, (key, icon, title, summary, label, window, args) in zip(cols, tiles):
        with col.container(border=True, key=f"pt_tile_{key}"):
            st.markdown(f"{icon} **{title}**")
            st.caption(summary.replace("$", "\\$"))   # two amounts would read as math
            if st.button(label, key=f"tile_{key}", type="tertiary",
                         icon=":material/open_in_new:"):
                _open_window(window, *args)


def _ask_guide(question):
    """A button's "Ask Northwend": carry the question over to the chat."""
    st.session_state["coach_prompt"] = question
    st.session_state["page"] = "AI Assistant"


def _calm_footer():
    st.caption("Prefer everything on one page? Turn on **Show everything** on the Account page.")


# --------------------------------------------------------------------------- #
if not pgcompat.is_postgres_dsn(DB) and not os.path.isfile(DB):
    st.error("No `portfolio.db` yet. Build it first:")
    st.code("python portfolio.py import \"path\\to\\All-Accounts-Positions-....csv\"", language="bash")
    st.stop()

render_feedback()   # the Send feedback window, while it's open (views/feedback.py)

if "hide_amounts" not in st.session_state:
    st.session_state["hide_amounts"] = bool(_read_prefs().get("hide_amounts", False))

# Add holdings (the menu) or a page's own button was pressed (_open_holdings_dialog)
_open = st.session_state.pop("open_dialog", None)
if PAGE in ("Clients", "Admin", "Account", "Life", "About", "What's new",
            "Advisor preview") and not _open:
    # these pages are about the login, its clients or the app - not the viewed
    # account's holdings, so they aren't read (a Holdings window needs them)
    snapshot, positions, cash_by_account, quotes, watch_tickers = None, [], {}, {}, []
    SNAPSHOT_SOURCE = None
else:
    _data_conn = connect(DB)   # one connection for the holdings, their source and the watchlist
    try:
        snapshot, positions, cash_by_account, quotes, watch_tickers = load(_data_conn)
        # an import, a hand entry, a percentages portfolio or the example portfolio
        SNAPSHOT_SOURCE = (_LATEST_SOURCE if snapshot == _LATEST_SNAPSHOT   # read above
                           else snapshot_source(_data_conn, USER_ID, snapshot))
    finally:
        _data_conn.close()
# what the value chart prices, from the holdings just loaded (no re-reads)
PERF_BASIS = perf.basis_of(snapshot, positions, cash_by_account)
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
        if ON_CLIENT:
            _render_meeting_prep(None, None, None, None)
            _render_report_advisor(None)
        if IS_MANAGED_CLIENT:
            _render_reports_client()
            _render_proposals_client(None, None)
        _render_notes()
    else:
        _render_assistant([], {})
    st.stop()
if PAGE == "Clients":
    # about the advisor's clients, not the viewed account's data
    _page_header(_label(PAGE), data=False)
    _render_clients()
    st.stop()
if PAGE == "Admin":
    # about accounts and logins, not the viewed account's data
    _page_header("Admin", data=False)
    _render_admin()
    st.stop()
if PAGE == "Account":
    # the login's own account, whichever account is being viewed
    _page_header("Account", data=False)
    _render_account()
    st.stop()
if PAGE == "Life":
    # the login's own records and life changes, whichever account is viewed
    _page_header("Life", data=False)
    _render_life()
    st.stop()
if PAGE == "What's new":
    _page_header("What's new", data=False)
    _render_whats_new()
    st.stop()
if PAGE == "About":
    _page_header("About and disclosures", data=False)
    _render_disclosures()
    # the same Send feedback window as the name menu's (views/feedback.py)
    st.caption("Something confusing, broken or missing?")
    st.button("Send feedback", key="about_feedback", icon=":material/feedback:",
              on_click=_feedback_open, args=("About",))
    st.stop()
if PAGE == "Find a guide":
    # the advisor directory - listings, not the viewed account's data
    _page_header(_label(PAGE), data=False)
    _render_find_a_guide()
    st.stop()
if PAGE == "Advisor preview":
    # made-up clients, in memory only - nothing of the viewed account's is read
    _page_header("See what you'll get", data=False)
    _render_advisor_demo()
    st.stop()
if not positions and PAGE not in ("Watchlist", "News", TICKER_PAGE):
    # Nothing brought in yet (the watchlist works regardless - Learn's example
    # funds go on it before anything is bought - and so does the news on what's
    # watched). What shows depends on whose
    # account it is (views/start_home.py):
    if ON_CLIENT or IS_ADVISOR:
        # an advisor: a client's (or their own) statements to bring in
        _page_header(_label(PAGE), data=False)
        _render_bring_in(ACTIVE_NAME if ON_CLIENT else None)
        if ON_CLIENT and PAGE == "Dashboard":
            _render_client_home(preview=True)   # what the client sees on their Home
    elif IS_MANAGED_CLIENT and PAGE == "Dashboard":
        # an advisor's client: their advisor's next step (client mode)
        _page_header(_label(PAGE), data=False)
        _render_client_home()
    elif not CAN_IMPORT:
        # a client whose advisor brings the statements in
        _page_header("Welcome", data=False)
        st.info(f"Welcome, **{ACTIVE_NAME}**. Your advisor, {_advisor_display_name()}, "
                "brings your statements in - your portfolio shows up here once they have.")
        with st.container(horizontal=True):
            st.button(f"Open {_label('Advisor notes')}", key="onboard_notes", type="primary",
                      on_click=_go, args=("Advisor notes",))
            st.button(f"Open {_label('Get started')}", key="onboard_get_started",
                      on_click=_go, args=("Get started",))
    elif PAGE == "Dashboard":
        # someone not investing yet: Home is their route, not an import form
        _page_header(_label(PAGE), data=False)
        _render_start_home()
    else:
        # Activity, Income: one calm line until there's something to show
        _page_header(_label(PAGE), data=False)
        _render_not_yet(PAGE)
    st.stop()

cash = sum(cash_by_account.values())

_held_symbols = {p["symbol"] for p in positions}
# Deep Yahoo history (moving averages, volume, 52-wk, beta, P/E, sector) - for
# this account's holdings and watchlist only, not every ticker anyone holds.
_my_tickers = _held_symbols | set(watch_tickers)
_bars_conn = connect(DB)   # one connection for the history these need
try:
    bar_stats = perf.bar_stats(_bars_conn, _my_tickers)
    sec_info = perf.security_info(_bars_conn, _my_tickers)
    # Holdings with no Yahoo history yet (a first import, or a new position) -
    # filled in below, once per visit, so the charts fill in without a manual sync
    _covered, _missing = perf.holdings_coverage(_bars_conn, USER_ID, PERF_BASIS)
    # the funds' top holdings kept from Yahoo, for Home's Fund overlap card
    # (fund_holdings.py; nothing is fetched here - the window asks Yahoo)
    fund_tops = (fund_holdings.cached(_bars_conn, fund_holdings.funds_in(positions, sec_info))
                 if PAGE == "Dashboard" and INVESTOR_VIEW else {})
    # The dividends each holding paid while held, for its total return (Home
    # and a holding's details): the imported activity history, else estimated
    # from Yahoo's payments. Not for a percentages portfolio (pretend shares).
    DIVIDENDS = (income.received_while_held(
        _bars_conn, USER_ID, _held_symbols, datetime.now().date(),
        skip_sources=(SAMPLE_SOURCE, manual_entry.PCT_SOURCE))
        if PAGE in ("Dashboard", TICKER_PAGE) and SNAPSHOT_SOURCE != manual_entry.PCT_SOURCE
        else {})
    # Your news (flag news_feed): the stored headlines for what this account
    # holds or watches - read only; the hourly job fetches them (news_feed.py)
    NEWS_ROWS = (news_feed.load(_bars_conn, _my_tickers)
                 if PAGE in ("Dashboard", "News") and flags.on("news_feed") else [])
finally:
    _bars_conn.close()
# What each holding holds - Stocks / Bonds / Cash / Other (asset_classes.py):
# the account's own choice, else Yahoo's fund breakdown, else the broker type.
CLASS_OVERRIDES = {s: c for s, c in (_read_prefs().get(asset_classes.OVERRIDES_PREF) or {}).items()
                   if c in asset_classes.CLASSES}
CLASS_SPLITS = asset_classes.splits_from(positions, sec_info, CLASS_OVERRIDES)
watch_only = [t for t in watch_tickers if t not in _held_symbols]
if PAGE == TICKER_PAGE and st.session_state.get("ticker_sym") not in _my_tickers:
    # a ticker's page only for what this account holds or watches (an old
    # address, or one just taken off the watchlist): back where it came from
    st.session_state.pop("ticker_sym", None)
    st.session_state["page"] = st.session_state.get("ticker_from") or PAGES[0]
    st.rerun()

# One metric context per position (same order as `positions`). Reused everywhere
# below: totals, alerts, the holdings table. port_value / acct_value are filled
# in once the totals are known.
contexts = [{"pos": p, "quote": quotes.get(p["symbol"], {}),
             "stats": bar_stats.get(p["symbol"], {}), "info": sec_info.get(p["symbol"], {}),
             "port_value": None, "acct_value": None,
             "dividends": d}
            for p, d in zip(positions, income.split_by_holding(positions, DIVIDENDS))]

tot_mv = tot_gl = tot_cost = tot_div = 0.0
acct_value = {}
for p, ctx in zip(positions, contexts):
    mv, cost = M.eff_mv(ctx), p["cost_basis"]
    if mv is not None:
        tot_mv += mv
        acct_value[p["account"]] = acct_value.get(p["account"], 0.0) + mv
        if cost is not None:
            tot_gl += mv - cost
            tot_cost += cost
            tot_div += ctx["dividends"] or 0.0   # only where there's a gain to add them to

for acct, csh in cash_by_account.items():
    acct_value[acct] = acct_value.get(acct, 0.0) + (csh or 0.0)

portfolio_value = tot_mv + cash
tot_glp = (tot_gl / tot_cost * 100) if tot_cost else None
# price change plus dividends (None: no dividends known - the price change alone)
tot_return = income.total_return(tot_gl if tot_cost else None, tot_cost, round(tot_div, 2))
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
if "value_logged" not in st.session_state and positions:   # (none: the watchlist alone)
    # just saved new holdings (_after_import): log their value now, whatever the
    # gap, so the next visit is compared with them
    _rebase = st.session_state.pop("value_rebase", False)
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
    }, **({"min_gap_sec": 0} if _rebase else {}))


# Holdings with no Yahoo history yet (a first import, or a new position;
# _missing, read above): fetch it once per visit so the charts fill in without
# a manual sync. Runs before the header so the header's one-shot messages
# survive its rerun.
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


def _flip(key):
    st.session_state[key] = not st.session_state.get(key)


def _show_all_toggle(key, total, noun):
    """"Show all 22 holdings" / "Show fewer" under a list cut short: the rest
    open in place (session state `key`), nothing in a window."""
    showing = bool(st.session_state.get(key))
    st.button("Show fewer" if showing else f"Show all {total} {noun}", key=f"{key}_btn",
              type="tertiary", on_click=_flip, args=(key,),
              icon=":material/expand_less:" if showing else ":material/expand_more:")


SPARK_LABEL = "Past month"   # the rows' mini chart column (perf.bar_stats' "spark")
SPARK_HELP = "Daily closing prices over about the last month."


def _spark(sym):
    """A row's mini chart: the last month's daily closes (read with the
    page's other history - perf.bar_stats), or an empty line."""
    return list((bar_stats.get(sym) or {}).get("spark") or [])


def _ticker_table(key, frame, symbols, came_from, column_config=None, alt=None):
    """Tickers as one table (Home's holdings, the Watchlist): headings, the
    mini chart, numbers right-aligned. Tapping any cell of a row opens that
    ticker's own page; the table starts afresh after, so coming
    Back finds nothing still picked. `symbols`: each row's ticker."""
    n = st.session_state.get(f"{key}_n", 0)
    wkey = f"{key}_{n}"
    syms = list(symbols)

    def picked():
        sel = (st.session_state.get(wkey) or {}).get("selection") or {}
        rows = list(sel.get("rows") or []) + [c[0] for c in (sel.get("cells") or [])]
        st.session_state[f"{key}_n"] = n + 1
        if rows and 0 <= rows[0] < len(syms):
            _open_ticker(syms[rows[0]], came_from)

    # a cell picks its row: a tap anywhere on a row, without a column of
    # checkboxes beside the tickers
    st.dataframe(frame, key=wkey, on_select=picked, selection_mode="single-cell",
                 hide_index=True,
                 width="stretch", height="content", row_height=36,
                 column_config={SPARK_LABEL: st.column_config.LineChartColumn(
                     SPARK_LABEL, width="small", help=SPARK_HELP, color="auto"),
                     **(column_config or {})},
                 alt=alt)


_view("news_feed")


_view("dashboard_page")


_view("watchlist")


_view("ticker_detail")


_view("activity")


_view("income")


if PAGE == "Plan":
    _render_plan(portfolio_value, tot_gl,
                 allocate(positions, cash_by_account, CLASS_SPLITS)["by_asset_class"])

if PAGE == "Get started":
    _render_get_started(True, portfolio_value)

if PAGE == "Advisor notes":
    if ON_CLIENT:
        _render_meeting_prep(portfolio_value,
                             allocate(positions, cash_by_account, CLASS_SPLITS)["by_asset_class"],
                             contexts, cash_by_account)
        _render_report_advisor(portfolio_value)   # figures are masked on screen, not stored
    if IS_MANAGED_CLIENT:
        _render_reports_client()
        _render_proposals_client(
            allocate(positions, cash_by_account, CLASS_SPLITS)["by_asset_class"],
            None if _hidden() else portfolio_value)
    _render_notes()

if PAGE == "AI Assistant":
    _render_assistant(contexts, cash_by_account)
