# Part of dashboard.py, which runs this file with _view("wins") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Your wins (flag wins, wins.py): one-time milestones worked out from data the
# app already has - a card in Home's This month when one was earned lately
# (Done / Not now, home_tasks "wins"), and the full list as a tab on Plan.
# The login's own account only: never while an advisor is in a client's
# account and not for an advisor's client (CLIENT_MODE) - so nothing is ever
# written from an advisor's session. Kept: each win's key and the day it was
# earned, and whether the person marked it (prefs wins) - never an amount.
# Uses _ps_facts (views/progress_split.py) for the one read it shares with
# What you did vs what the market did.
# ruff: noqa: F821

import wins

WINS_TAB = wins.PAGE_TITLE


def _wins_shown():
    """Only the login's own account, never in client mode."""
    return USER_ID == LOGIN_ID and not CLIENT_MODE


def _wins_state():
    """wins.evaluate() for this account, once per run. Wins earned for the
    first time are recorded here (the login's own settings only)."""
    if "wins" in _RUN:
        return _RUN["wins"]
    today = datetime.now().date()
    facts = _ps_facts()
    held = globals().get("positions") or []
    info = globals().get("sec_info") or {}
    ctxs = globals().get("contexts") or []
    src = globals().get("SNAPSHOT_SOURCE")
    now_rows = [{"symbol": p["symbol"], "asset_type": p.get("asset_type"),
                 "quote_type": (info.get(p["symbol"]) or {}).get("quote_type"),
                 "expense_ratio": (info.get(p["symbol"]) or {}).get("expense_ratio"),
                 "value": M.eff_mv(ctx)} for p, ctx in zip(held, ctxs)]
    accounts = ([] if src == progress_split.SAMPLE_SOURCE else
                {p.get("account") for p in held} | set(globals().get("cash_by_account") or {}))
    p = _read_prefs()
    got = wins.evaluate(
        prefs=p, today=today, moves=progress_split.moves(facts),
        first_rows=facts["first_funds"], first_day=facts["first_day"], now_rows=now_rows,
        latest_day=str(globals().get("snapshot") or "")[:10] or None, profile=_profile(),
        accounts=accounts, pct_only=src == progress_split.PCT_SOURCE)
    if got["new"] and _wins_shown():   # each one dated as it's shown (evaluate)
        _write_prefs(wins.with_earned(p, got["new"]))
    _RUN["wins"] = got
    return got


def _wins_mark(key, on):
    """Mark as done / Undo, for the wins only the person can mark."""
    if not _wins_shown():
        return
    p = _read_prefs()
    new = wins.with_mark(p, key, datetime.now().date(), on)
    if new != p:
        _write_prefs(new)


def _wins_open():
    st.session_state["plan_tab"] = WINS_TAB
    _go("Plan")


def _wins_recent():
    return wins.recent(_wins_state()["wins"], datetime.now().date())


def render_wins_card():
    """Home's This month card: the newest win earned lately."""
    w = _wins_recent()[0]
    t = wins.words(w, fmt_money0)
    with st.container(border=True, key="pt_wins_card"):
        st.html(f"<div class='pt-month-card-title'>{html.escape(wins.CARD_TITLE)}</div>"
                f"<div class='pt-win-head'><b>{html.escape(w['title'])}</b>"
                + (f" · {html.escape(t['number'])}" if t["number"] else "") + "</div>"
                + (f"<div class='pt-region'>{html.escape(t['line'])}</div>" if t["line"] else ""))
        if "Plan" in PAGES:
            st.button(wins.CARD_LINK, key="wins_open", type="tertiary", on_click=_wins_open)


def _win_box(w, earned):
    t = wins.words(w, fmt_money0)
    with st.container(border=True, key=f"pt_win_{w['key']}", height="stretch"):
        if earned:
            day = wins.day_words(w["on"])
            chip = wins.EARNED.format(day=day) if day else wins.EARNED_NO_DAY
            st.html(f"<span class='pt-chip pt-win-chip'>{html.escape(chip)}</span>"
                    f"<div class='pt-win-title'>{html.escape(w['title'])}</div>"
                    + (f"<div class='pt-win-num'>{html.escape(t['number'])}</div>"
                       if t["number"] else ""))
            if t["line"]:
                _md(t["line"])
            if t["note"]:
                st.caption(t["note"].replace("$", r"\$"))
            if w["can_unmark"]:
                st.button(wins.UNMARK, key=f"win_undo_{w['key']}", type="tertiary",
                          on_click=_wins_mark, args=(w["key"], False))
        else:
            st.html(f"<div class='pt-win-title'>{html.escape(w['title'])}</div>")
            if t["how"]:
                _md(t["how"])
            if t["progress"] is not None:
                st.progress(max(0.0, min(1.0, t["progress"])))
            if t["line"] and w["key"] in wins.SELF_MARKED:
                st.caption(t["line"])
            if w["key"] == wins.ROTH:
                what_this_means("Roth IRA", key="win_roth_means")
            if w["can_mark"]:
                st.button(wins.MARK, key=f"win_mark_{w['key']}",
                          on_click=_wins_mark, args=(w["key"], True))


def _render_wins():
    """The Plan tab: wins earned (newest first), then the ones still to earn."""
    st.caption(wins.INTRO)
    earned, left = wins.shown(_wins_state()["wins"])
    if not earned:
        st.caption(wins.NONE_YET)
    for i in range(0, len(earned), 3):
        cols = st.columns(3)
        for col, w in zip(cols, earned[i:i + 3]):
            with col:
                _win_box(w, True)
    if left:
        st.markdown(f"**{wins.TO_EARN}**")
        for i in range(0, len(left), 3):
            cols = st.columns(3)
            for col, w in zip(cols, left[i:i + 3]):
                with col:
                    _win_box(w, False)
    else:
        st.caption(wins.ALL_EARNED)
    st.caption(wins.PRIVATE)
