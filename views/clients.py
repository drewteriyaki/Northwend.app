# Part of dashboard.py, which runs this file with _view("clients") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Advisor side: notes and next steps, the advisor card, model portfolios,
# the Clients page, and the weekly summary notice.
# ruff: noqa: F821

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


def _client_rows(today):
    """One row per client of this advisor: their summary, goal, review and
    why they need a look - the Clients page and the weekly summary."""
    import overview

    conn = connect(DB)
    try:
        # only the tickers these clients hold
        _ids = [cid for cid, _ in CLIENTS]
        quotes = overview.latest_quotes(conn, [r["symbol"] for r in conn.execute(
            f"SELECT DISTINCT symbol FROM positions WHERE user_id IN "
            f"({', '.join('?' for _ in _ids)})", tuple(_ids))])
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
    return rows


def _render_clients():
    today = datetime.now().date()
    if not CLIENTS:
        st.info("No clients yet - add one with **Add client** in the sidebar.")
    else:
        rows = _client_rows(today)
        _week_seen()  # the Clients page shows this week's summary itself
        _summary = advising.weekly_summary(rows)
        with st.expander(":material/event_upcoming: This week", expanded=_summary["any"]):
            _render_week_summary(_summary, where="clients")

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


WEEK_LIST_MAX = 5  # clients listed per group in the weekly summary; the rest are counted


def _week_seen():
    """This week's summary was seen (per advisor login, on any device)."""
    week = advising.week_of(datetime.now().date())
    if st.session_state.get("week_seen") == week:
        return
    _save_login_pref("week_seen", week)
    st.session_state["week_seen"] = week


def _open_from_summary(client_id):
    _week_seen()
    _open_client(client_id)


def _render_week_summary(summary, *, where):
    """Reviews due, coming due, and other clients needing a look, each with
    an Open button."""
    if not summary["any"]:
        st.markdown(":material/check_circle: Nothing due this week - every review is up "
                    "to date and no client needs a look.")
        return
    groups = (
        ("due", "Reviews due",
         lambda r: "never reviewed" if r["review"] == "never"
         else f"last review {r['review_days']} days ago"),
        ("soon", f"Coming due in the next {advising.SOON_DAYS} days",
         lambda r: f"due in {r['in_days']} day{'s' if r['in_days'] != 1 else ''}"),
        ("attention", "Also needs a look", lambda r: ", ".join(r["other"])),
    )
    for group, title, why in groups:
        items = summary[group]
        if not items:
            continue
        st.markdown(f"**{title}** · {len(items)}")
        for r in items[:WEEK_LIST_MAX]:
            with st.container(horizontal=True, vertical_alignment="center"):
                st.markdown(f"{r['name'].replace('_', chr(92) + '_')} - {why(r)}",
                            width="stretch")
                st.button("Open", key=f"wk_{where}_{group}_{r['user_id']}", type="tertiary",
                          on_click=_open_from_summary, args=(r["user_id"],),
                          help=f"Open {r['name']}'s dashboard")
        if len(items) > WEEK_LIST_MAX:
            st.caption(f"and {len(items) - WEEK_LIST_MAX} more on Your clients.")


# Advisors: once a week (from Monday), the first visit opens with this week's
# reviews and who needs a look; "Got it" hides it until next week. Nothing is
# shown in a week with nothing to say. The Clients page always has it.
if IS_ADVISOR and CLIENTS and PAGE != "Clients":
    _week = advising.week_of(datetime.now().date())
    if "week_seen" not in st.session_state:
        _wc = connect(DB)
        try:
            st.session_state["week_seen"] = prefs.load(_wc, LOGIN_ID).get("week_seen")
        finally:
            _wc.close()
    if st.session_state["week_seen"] != _week:
        # worked out once per session, not on every rerun (live prices rerun the page)
        if st.session_state.get("week_summary", (None,))[0] != _week:
            st.session_state["week_summary"] = (
                _week, advising.weekly_summary(_client_rows(datetime.now().date())))
        _summary = st.session_state["week_summary"][1]
        if _summary["any"]:
            with st.container(border=True, key="week_notice"):
                st.markdown(f":material/event_upcoming: **This week** - "
                            f"{len(_summary['due'])} review{'s' if len(_summary['due']) != 1 else ''}"
                            f" due, {len(_summary['soon'])} coming up, "
                            f"{len(_summary['attention'])} other client"
                            f"{'s' if len(_summary['attention']) != 1 else ''} to look at.")
                _render_week_summary(_summary, where="notice")
                with st.container(horizontal=True):
                    st.button("Your clients", key="week_clients", type="primary",
                              on_click=lambda: (_week_seen(), _go("Clients")))
                    st.button("Got it", key="week_ok", type="tertiary", on_click=_week_seen,
                              help="Hide this until next week")
