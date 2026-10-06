# Part of dashboard.py, which runs this file with _view("checkin") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# The Monthly Walk (ROADMAP R1, checkin.py; it grew out of the monthly
# check-in, item 11): a 3-minute routine on Home once a month, one step at a
# time - update holdings, look at the mix against its target, one short
# read, and the verdict: what the person's own rule (target mix and band)
# says this month, by asset class, never a fund or a figure. Finishing it
# counts toward the logbook in the kit (gear.py). Its settings - the day
# it's offered from and the optional reminder email (off unless turned on) -
# are on the Account page. The person's own: like the kit, never the advisor
# app or an advisor looking at a client. Its done state also carries "Your
# log" (the Expedition Log, R3, expedition_log.py, flag walk_log) and "Your
# ledger" (the Do-Nothing Ledger, R2, ledger.py, flag ledger).
# ruff: noqa: F821

import checkin
import expedition_log
import feature_counts
import flags
import future_notes
import ledger


def _checkin_shown():
    """Investors and advisors' clients on their own account, with real
    holdings to look at (the kit's rule, views/kit.py _kit_shown) - while the
    walk is on (flags.py; off, Home says nothing about walks and earlier
    walks stay as they were)."""
    return flags.on("walk") and _kit_shown() and HAS_REAL_HOLDINGS


def _checkin_today():
    return datetime.now().date()


def _checkin_due():
    if not _checkin_shown():
        return False
    p = _read_prefs()
    # once: the month the holdings came in (or their date, if earlier)
    if checkin.note_seen(p, _checkin_today(), True, str(snapshot or "")):
        _write_prefs(p)
    return checkin.due(p, _checkin_today())


def _walk_day(d):
    """'Sunday, November 1' - or 'today'."""
    return "today" if d == _checkin_today() else f"{d:%A, %B} {d.day}"


def _checkin_tick(step, done=True):
    p = _read_prefs()
    checkin.tick(p, step, _checkin_today(), done)
    _write_prefs(p)


def _checkin_open():
    st.session_state["checkin_open"] = True


def _checkin_skip():
    p = _read_prefs()
    today = _checkin_today()
    checkin.skip(p, today)
    _write_prefs(p)
    st.session_state.pop("checkin_open", None)
    st.session_state["import_flash"] = (
        f"No walk this month - the next one is on {_walk_day(checkin.next_walk(p, today))}. "
        "Nothing is lost.")


def _walk_log_facts(p, today):
    """The finished walk's facts for the Expedition Log and the Ledger
    (expedition_log.py): percentages, points and yes/no only."""
    month = checkin.month_of(today)
    actual = {r["label"]: r["pct"] for r in _walk_by_class()}
    since = (today - timedelta(days=expedition_log.MARKET_DAYS + 1)).isoformat()
    try:
        market = expedition_log.market_move(perf.daily_values(DB, PERF_BASIS, since), today)
    except Exception:  # noqa: BLE001 - no prices: the line just leaves the move out
        market = None
    c = connect(DB)
    try:
        sold = expedition_log.sold_since(c, USER_ID, expedition_log.previous_day(p, month),
                                         today.isoformat())
        note = future_notes.get(c, USER_ID, None)
    finally:
        c.close()
    return {"on": today.isoformat(), "updated": str(snapshot or "")[:7] == month,
            "drift": expedition_log.largest_drift(actual, load_alloc_targets()),
            "market": market, "sold": sold,
            "note": bool(note) and future_notes.written_on(note)[:7] == month}


def _checkin_finish(verdict):
    p = _read_prefs()
    today = _checkin_today()
    if (flags.on("walk_log") or flags.on("ledger")) and not checkin.current(p, today)["finished"]:
        expedition_log.record(p, checkin.month_of(today), _walk_log_facts(p, today))
    if checkin.finish(p, today, verdict):
        _write_prefs(p)
        st.session_state["import_flash"] = (
            f"Your {checkin.month_name(checkin.month_of(today))} walk is done. Walks finished: "
            f"{checkin.count(p)}. Next walk: {_walk_day(checkin.next_walk(p, today))}.")
    st.session_state.pop("checkin_open", None)


def _checkin_holdings():
    _checkin_open()
    _open_holdings_dialog("manual")


def _walk_to_target_mix():
    """The verdict's link: the Plan page, on its Target mix tab."""
    st.session_state["plan_tab"] = "Target mix"
    _go("Plan")


def _checkin_read_topic(month):
    """This month's short read: one of Learn's basics, in turn."""
    topics = _basics_topics(200.0, 10)   # (views/get_started.py) the same words as Learn
    key = checkin.read_for(month, [t[0] for t in topics])
    return next(t for t in topics if t[0] == key)


def _walk_by_class():
    return allocate(positions, cash_by_account, CLASS_SPLITS)["by_asset_class"]


def _walk_verdict():
    """This month's verdict from their own rule (checkin.verdict): the plan's
    monthly amount (else views/next_deposit.py's default) only picks which
    asset class new money would go to first - no figure is shown or kept."""
    values = {r["label"]: float(r["value"] or 0.0) for r in _walk_by_class()}
    return checkin.verdict(values, load_alloc_targets(), load_drift_threshold(),
                           _deposit_start())


def _checkin_mix_html():
    actual = {r["label"]: r["pct"] for r in _walk_by_class()}
    rows = checkin.drift_rows(actual, load_alloc_targets())
    if not rows:
        return ""
    body = "".join(_checkin_mix_row(r) for r in rows)
    return ("<table class='pt-storm-table'><thead><tr><th>Kind</th><th>Now</th>"
            f"<th>Your target</th></tr></thead><tbody>{body}</tbody></table>")


def _checkin_mix_row(r):
    now = mask_or(f"{r['now']:.0f}%")
    target = "-" if r["target"] is None else f"{r['target']:.0f}%"
    return (f"<tr><td>{html.escape(r['label'])}</td><td>{html.escape(now)}</td>"
            f"<td>{html.escape(target)}</td></tr>")


def _walk_step_head(n, title):
    st.html(f"<div class='pt-eyebrow' style='margin:.4rem 0 0'>Step {n} of "
            f"{len(checkin.STEPS)}</div><div><b>{html.escape(title)}</b></div>")


def _render_walk_verdict():
    """Step 4: the verdict, then the rule it came from - theirs, and where
    to change it."""
    v = _walk_verdict()
    targets, band = load_alloc_targets(), load_drift_threshold()
    with st.container(border=True, key="pt_walk_verdict"):
        st.markdown(f"**{checkin.verdict_text(v)}**")
        if v["kind"] == checkin.NONE:
            st.caption("Your target mix is the rule the walk reads each month: how much you "
                       "want in stocks, bonds and cash."
                       + ("" if CAN_MANAGE else " Your advisor can set one with you."))
        else:
            st.caption(checkin.rule_text(targets, band) + " "
                       + ("You can change both on the Plan, under Target mix." if CAN_MANAGE
                          else "Your advisor set these with you - ask them about a change.")
                       + " By asset class only: which funds, and whether to add money at "
                         "all, is up to you.")
        # still Northwend's example mix, untouched: say so, and ask (LEGAL_GATES C3)
        from_example = (CAN_MANAGE and v["kind"] != checkin.NONE
                        and checkin.target_from_example(_read_prefs(), targets))
        if from_example:
            st.caption(":material/help: " + checkin.TARGET_FROM_NOTE)
        with st.container(horizontal=True):
            if from_example:
                st.button("Keep it as mine", key="walk_target_mine", type="tertiary",
                          icon=":material/check:", on_click=_walk_target_mine)
            if CAN_MANAGE or v["kind"] != checkin.NONE:
                st.button("Set a target mix" if v["kind"] == checkin.NONE
                          else "Open my target mix", key="walk_plan", type="tertiary",
                          icon=":material/tune:", on_click=_walk_to_target_mix)
    return v


def _walk_target_mine():
    """"Keep it as mine": the target mix is theirs from now on."""
    p = _read_prefs()
    checkin.note_target(p, checkin.TARGET_OWN, load_alloc_targets())
    _write_prefs(p)


def _render_checkin_steps(state):
    month = state["month"]
    done = set(state["done"])
    # brought in this month already: that step is done
    if "holdings" not in done and str(snapshot or "")[:7] == month:
        _checkin_tick("holdings")
        done.add("holdings")
    by_key = {k: (title, why) for k, title, why in checkin.STEPS}
    # the steps behind them, one line each
    lines = [f":material/check_circle: {by_key[k][0]}" for k in checkin.REQUIRED if k in done]
    if lines:
        st.markdown("  \n".join(lines))
    step = next((k for k in checkin.REQUIRED if k not in done), "verdict")
    n = checkin.STEP_KEYS.index(step) + 1
    title, why = by_key[step]
    _walk_step_head(n, title)

    if step == "holdings":
        st.caption(why if CAN_IMPORT else "Your advisor keeps your holdings up to date here - "
                   "a quick look is all this step needs.")
        with st.container(horizontal=True):
            if CAN_IMPORT:
                st.button("Update holdings", key="walk_holdings", type="primary",
                          width="stretch", on_click=_checkin_holdings)
            st.button("Nothing changed" if CAN_IMPORT else "Looked", key="walk_holdings_same",
                      width="stretch", on_click=_checkin_tick, args=("holdings",))

    elif step == "mix":
        st.caption(why)
        table = _checkin_mix_html()
        if table:
            st.html(table)
        if not load_alloc_targets():
            st.caption("No target mix yet - you can choose one on Plan, under Target mix.")
        else:
            st.caption(f"Your band is {load_drift_threshold():g} points either way: a kind "
                       "further than that from its target is flagged. A few points either way "
                       "is normal.")
        st.button("Looked at it", key="walk_mix", type="primary", width="stretch",
                  on_click=_checkin_tick, args=("mix",))

    elif step == "read":
        k, icon, t_title, _line, body = _checkin_read_topic(month)
        with st.container(border=True, key="pt_checkin_read"):
            st.markdown(f"{icon} **{t_title}**")
            st.markdown(body)
            learn_more(BASICS_LINKS.get(k))
        st.button("Read it", key="walk_read", type="primary", width="stretch",
                  on_click=_checkin_tick, args=("read",))

    else:
        st.caption(why)
        v = _render_walk_verdict()
        with st.expander(":material/edit_note: A note to future you (optional)"):
            render_future_note(None)
        st.button("Finish the walk", key="walk_finish", type="primary", width="stretch",
                  on_click=_checkin_finish, args=(checkin.stored(v),))
        if not feature_counts.left_out(_read_prefs()):
            st.caption("Northwend counts finished walks in totals only - never you by name - "
                       "to learn whether the walk helps. You can leave yourself out on Account.")


def _render_walk_log(p):
    """"Your log" (ROADMAP R3, expedition_log.py): a line per finished walk,
    newest first, and the note to future you written on that walk while it's
    still the same note. Only on the card, which is the person's own."""
    if not flags.on("walk_log"):
        return
    rows = expedition_log.lines(p)[:12]
    if not rows:
        return
    note = None
    if any(r["note"] for r in rows):
        c = connect(DB)
        try:
            note = future_notes.get(c, USER_ID, None)
        finally:
            c.close()
    with st.expander("Your log", icon=":material/menu_book:"):
        for r in rows:
            words = (f"<div class='pt-region'>{html.escape(future_notes.quote(note, _fmt_date))}"
                     "</div>" if r["note"] and note
                     and future_notes.written_on(note)[:7] == r["month"] else "")
            st.html(f"<div style='margin:.15rem 0'>{html.escape(r['text'])}</div>{words}")
        st.caption("Written from your walks - percentages only, never amounts. Only you can "
                   "see it.")


def _ledger_points(entries):
    """The holdings' closes the hypotheticals need, worked out once a day per
    statement (like _weather_now, views/kit.py)."""
    start = ledger.since(entries)
    key = (USER_ID, snapshot, _checkin_today().isoformat(), start)
    kept = st.session_state.get("ledger_points")
    if not kept or kept[0] != key:
        kept = (key, perf.daily_values(DB, PERF_BASIS, start) if start else [])
        st.session_state["ledger_points"] = kept
    return kept[1]


def _render_ledger(p):
    """"Your ledger" (ROADMAP R2, ledger.py): each walk with no sale since the
    one before. During a drop (the storm note's condition) each line also
    shows the hypothetical both ways - a record, never a grade."""
    if not flags.on("ledger"):
        return
    rows = ledger.entries(p)[:ledger.MONTHS_SHOWN]
    if not rows:
        return
    storm = bool(HAS_HOLDINGS and _weather_now())
    points = _ledger_points(rows) if storm else []
    shown = False
    with st.expander("Your ledger", icon=":material/fact_check:"):
        for e in rows:
            pct = ledger.what_if(points, e["on"]) if storm else None
            extra = ""
            if pct is not None:
                shown = True
                extra = ("<div class='pt-region'>"
                         f"{html.escape(ledger.what_if_text(_fmt_date(e['on']), pct))}</div>")
            st.html(f"<div style='margin:.15rem 0'>{html.escape(ledger.entry_text(e['month']))}"
                    f"</div>{extra}")
        if shown:
            st.caption(ledger.HINDSIGHT)
        st.caption("A finished walk with no sale since the walk before adds a line. Only you "
                   "can see it.")


def render_checkin_card():
    """Home's Monthly Walk: this month's walk while one is waiting
    (checkin.due), else one quiet line - walks finished and the next walk's
    day (and this month's verdict, once walked)."""
    if not _checkin_shown():
        return
    due = _checkin_due()
    p = _read_prefs()
    today = _checkin_today()
    state = checkin.current(p, today)
    n = checkin.count(p)
    tally = f"Walks finished: {n}"
    if not due:
        with st.container(border=True, key="pt_walk_quiet"):
            said = (checkin.verdict_past(checkin.verdict_of(p, state["month"]))
                    if state["finished"] else "")
            st.html("<div class='pt-eyebrow' style='margin:0'>The monthly walk</div>"
                    + (f"<div>Your {checkin.month_name(state['month'])} walk is done. "
                       f"{html.escape(said)}</div>" if state["finished"] else "")
                    + f"<div class='pt-region'>{tally} · Next walk: "
                    f"{html.escape(_walk_day(checkin.next_walk(p, today)))}</div>")
            _render_walk_log(p)
            _render_ledger(p)
        return
    n_done = sum(1 for k in checkin.REQUIRED if k in state["done"])
    is_open = bool(st.session_state.get("checkin_open"))
    with st.container(border=True, key="pt_walk"):
        st.html("<div class='pt-eyebrow' style='margin:0'>The monthly walk</div>"
                f"<div class='pt-storm-title'>Your {checkin.month_name(state['month'])} "
                "walk</div>"
                "<div>About 3 minutes, one step at a time: your holdings, your mix, one short "
                "read - then what your own plan says for the month.</div>"
                f"<div class='pt-region' style='margin-top:.3rem'>{tally}"
                + (f" · {n_done} of {len(checkin.STEPS)} steps done" if n_done else "")
                + "</div>")
        if is_open:
            _render_checkin_steps(state)
        else:
            with st.container(horizontal=True):
                st.button("Continue the walk" if n_done else "Start the walk", key="walk_start",
                          type="primary", width="stretch", icon=":material/hiking:",
                          on_click=_checkin_open)
                st.button("Not this month", key="walk_skip", width="stretch",
                          on_click=_checkin_skip)


# ---- Account > Monthly walk ----------------------------------------------- #

def _checkin_save_day():
    p = _read_prefs()
    p[checkin.PREF_DAY] = int(st.session_state.get("acct_checkin_day") or checkin.DEFAULT_DAY)
    _write_prefs(p)


def _checkin_save_email():
    p = _read_prefs()
    p[checkin.PREF_EMAIL] = bool(st.session_state.get("acct_checkin_email"))
    _write_prefs(p)


def _ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def render_checkin_settings(confirmed_email):
    """The day the walk is offered from, and the reminder email - off
    unless they turn it on, and only to a confirmed email. Not shown while
    the walk is off (flags.py)."""
    if IS_ADVISOR or USER_ID != LOGIN_ID or not flags.on("walk"):
        return
    p = _read_prefs()
    st.subheader("Monthly walk", anchor=False)
    st.caption("A 3-minute walk on Home once a month: your holdings, your mix, one short "
               "read, and what your own plan says for the month.")
    st.session_state["acct_checkin_day"] = checkin.day_of(p)
    st.selectbox("Offer it from", list(range(1, checkin.LAST_DAY + 1)), key="acct_checkin_day",
                 format_func=lambda d: f"The {_ordinal(d)} of each month",
                 on_change=_checkin_save_day, width=260)
    st.session_state["acct_checkin_email"] = bool(p.get(checkin.PREF_EMAIL))
    st.toggle("Email me a reminder", key="acct_checkin_email", on_change=_checkin_save_email,
              disabled=not confirmed_email and not p.get(checkin.PREF_EMAIL))
    st.caption("One short email a month that just says it's time - no amounts, holdings or "
               "anything else about your money. Off unless you turn it on."
               + ("" if confirmed_email else
                  " It needs a confirmed email - see Email, just below."))
