# Part of dashboard.py, which runs this file with _view("checkin") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# The monthly check-in (ROADMAP 11, checkin.py): a 3-minute routine on Home
# once a month - update holdings, look at the mix against its target, one
# short read, and a note to future you if they like. Finishing it counts
# toward the logbook in the kit (gear.py). Its settings - the day it's
# offered from and the optional reminder email (off unless turned on) - are
# on the Account page. The person's own: like the kit, never the advisor app
# or an advisor looking at a client.
# ruff: noqa: F821

import checkin


def _checkin_shown():
    """Investors and advisors' clients on their own account, with real
    holdings to look at (the kit's rule, views/kit.py _kit_shown)."""
    return _kit_shown() and HAS_REAL_HOLDINGS


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


def _checkin_tick(step, done=True):
    p = _read_prefs()
    checkin.tick(p, step, _checkin_today(), done)
    _write_prefs(p)


def _checkin_open():
    st.session_state["checkin_open"] = True


def _checkin_skip():
    p = _read_prefs()
    checkin.skip(p, _checkin_today())
    _write_prefs(p)
    st.session_state.pop("checkin_open", None)
    st.session_state["import_flash"] = ("No check-in this month - it'll be back next month. "
                                        "Nothing is lost.")


def _checkin_finish():
    p = _read_prefs()
    today = _checkin_today()
    if checkin.finish(p, today):
        _write_prefs(p)
        n = checkin.count(p)
        st.session_state["import_flash"] = (
            f"Your {checkin.month_name(checkin.month_of(today))} check-in is done - see you "
            "next month." + (f" That's {n} so far." if n > 1 else ""))
    st.session_state.pop("checkin_open", None)


def _checkin_holdings():
    _checkin_open()
    _open_holdings_dialog("manual")


def _checkin_read_topic(month):
    """This month's short read: one of Learn's basics, in turn."""
    topics = _basics_topics(200.0, 10)   # (views/get_started.py) the same words as Learn
    key = checkin.read_for(month, [t[0] for t in topics])
    return next(t for t in topics if t[0] == key)


def _checkin_mix_html():
    actual = {r["label"]: r["pct"] for r in
              allocate(positions, cash_by_account, CLASS_SPLITS)["by_asset_class"]}
    targets = load_alloc_targets()
    rows = checkin.drift_rows(actual, targets)
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


def _checkin_step_head(n, title, done):
    mark = ":material/check_circle:" if done else f"**{n}.**"
    st.markdown(f"{mark} **{title}**" + (" - done" if done else ""))


def _render_checkin_steps(state):
    month = state["month"]
    done = set(state["done"])
    # brought in this month already: that step is done
    if "holdings" not in done and str(snapshot or "")[:7] == month:
        _checkin_tick("holdings")
        done.add("holdings")
    by_key = {k: (title, why) for k, title, why in checkin.STEPS}

    # 1. holdings
    title, why = by_key["holdings"]
    _checkin_step_head(1, title, "holdings" in done)
    if "holdings" not in done:
        st.caption(why if CAN_IMPORT else "Your advisor keeps your holdings up to date here - "
                   "a quick look is all this step needs.")
        with st.container(horizontal=True):
            if CAN_IMPORT:
                st.button("Update holdings", key="ci_holdings", on_click=_checkin_holdings)
            st.button("Nothing changed" if CAN_IMPORT else "Looked", key="ci_holdings_same",
                      type="tertiary", on_click=_checkin_tick, args=("holdings",))

    # 2. the mix against its target
    title, why = by_key["mix"]
    _checkin_step_head(2, title, "mix" in done)
    if "mix" not in done:
        st.caption(why)
        table = _checkin_mix_html()
        if table:
            st.html(table)
        if not load_alloc_targets():
            st.caption("No target mix yet - you can choose one on Plan, under Target mix.")
        else:
            st.caption(f"A few points either way is normal. Plan flags a kind that's "
                       f"{load_drift_threshold():.0f} points or more from its target. Bringing "
                       "it back is called rebalancing - there's no need to do anything today.")
        with st.container(horizontal=True):
            st.button("Looked at it", key="ci_mix", type="tertiary",
                      on_click=_checkin_tick, args=("mix",))
            st.button("Open my target mix", key="ci_mix_plan", type="tertiary",
                      on_click=_go, args=("Plan",))

    # 3. one short read
    title, why = by_key["read"]
    _checkin_step_head(3, title, "read" in done)
    if "read" not in done:
        k, icon, t_title, _line, body = _checkin_read_topic(month)
        with st.container(border=True, key="pt_checkin_read"):
            st.markdown(f"{icon} **{t_title}**")
            st.markdown(body)
            learn_more(BASICS_LINKS.get(k))
        st.button("Read it", key="ci_read", type="tertiary",
                  on_click=_checkin_tick, args=("read",))

    # 4. a note to future you (optional)
    title, why = by_key["note"]
    st.markdown(f"**4.** **{title}** (optional)")
    st.caption(why)
    render_future_note(None)

    can = checkin.can_finish({"done": list(done)})
    with st.container(horizontal=True, vertical_alignment="center"):
        st.button("Finish check-in", key="ci_finish", type="primary", disabled=not can,
                  on_click=_checkin_finish)
        if not can:
            st.caption("Tick the first three to finish - the note is up to you.")


def render_checkin_card():
    """Home's monthly check-in, while one is waiting (checkin.due)."""
    if not _checkin_due():
        return
    p = _read_prefs()
    state = checkin.current(p, _checkin_today())
    n_done = sum(1 for k in checkin.REQUIRED if k in state["done"])
    is_open = bool(st.session_state.get("checkin_open"))
    with st.container(border=True, key="pt_checkin"):
        st.html("<div class='pt-eyebrow' style='margin:0'>Monthly check-in</div>"
                f"<div class='pt-storm-title'>Your {checkin.month_name(state['month'])} "
                "check-in</div>"
                "<div>About 3 minutes: your holdings, your mix, one short read - and a note "
                "to future you if you like. Finishing it counts toward the <b>logbook</b> in "
                "your kit.</div>"
                + (f"<div class='pt-region' style='margin-top:.3rem'>{n_done} of "
                   f"{len(checkin.REQUIRED)} done</div>" if n_done else ""))
        if is_open:
            _render_checkin_steps(state)
        else:
            with st.container(horizontal=True):
                st.button("Continue" if n_done else "Start", key="ci_start", type="primary",
                          on_click=_checkin_open)
                st.button("Not this month", key="ci_skip", type="tertiary",
                          on_click=_checkin_skip)


# ---- Account > Monthly check-in ------------------------------------------- #

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
    """The day the check-in is offered from, and the reminder email - off
    unless they turn it on, and only to a confirmed email."""
    if IS_ADVISOR or USER_ID != LOGIN_ID:
        return
    p = _read_prefs()
    st.subheader("Monthly check-in", anchor=False)
    st.caption("A 3-minute look on Home once a month: your holdings, your mix, one short "
               "read, and a note to future you if you like.")
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
