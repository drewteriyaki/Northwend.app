# Part of dashboard.py, which runs this file with _view("reports") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Client progress reports (ROADMAP G8, reports.py): the advisor prepares and
# sends one from the client's Advisor notes page; the client reads them there.
# ruff: noqa: F821

import proposals
import reports
import standing_line


def _rep_save_one(c, viewer, target, kind, message, value, today):
    """Build and save one client's report; (label, the email to tell them at
    or None, whether they've signed in). Only a confirmed email is told
    (proposals.who_to_tell, as for proposals) - a client's is confirmed once
    they set up their login."""
    start, end, label = reports.period_bounds(kind, today, reports.last_end(c, target))
    if reports.sent_just_now(c, target, label):
        return label, None, "just now"   # a double click: not saved or emailed again
    facts = reports.build(c, target, start, end, value_now=value, today=today)
    reports.save(c, viewer, target, label=label, start=start, end=end, facts=facts,
                 message=message)
    who = proposals.who_to_tell(c, target)
    # at most one "your report is ready" email an hour (auth.notice_ok): a
    # second send in that time is still on their page, only the email waits
    if who["email"] and not auth.notice_ok(c, "report", who["email"]):
        return label, None, "recent"
    return label, who["email"], who["signed_in"]


def _rep_untold(signed_in):
    """Why a client wasn't emailed about their report, for the advisor."""
    if signed_in == "recent":
        return ("They had an email about a report in the last hour, so no new one went - "
                "it's waiting on their page.")
    return ("They'll see it next time they sign in." if signed_in else
            "They haven't set up their login yet - send them a setup link from Client login, "
            "and it'll be waiting when they do.")


def _rep_tell(email, label, card):
    """Email a client that a report is waiting - no figures - from the
    advisor's name and firm, with their standing line. True if sent."""
    body_name, from_name = _advisor_names(card, st.session_state["username"])
    return mailer.report_ready(email, f"{_app_address()}?page=advisor-notes", body_name, label,
                               standing=_standing_text(st.session_state["user_id"]),
                               from_name=from_name)


def _rep_send(value):
    viewer, target = st.session_state["user_id"], st.session_state["active_user_id"]
    kind = st.session_state.get("rep_period") or reports.PERIODS[1]
    today = datetime.now().date()
    c = connect(DB)
    try:
        if viewer == target or not auth.can_view(c, viewer, target):
            st.session_state["rep_msg"] = ("error", "Only this client's advisor can send a report.")
            return
        label, email, signed_in = _rep_save_one(c, viewer, target, kind,
                                                st.session_state.get("rep_message") or "",
                                                value, today)
        card = prefs.load(c, viewer).get("advisor_card") or {}
    finally:
        c.close()
    if signed_in == "just now":
        st.session_state["rep_msg"] = ("warning", f"You sent the {label} report a moment ago, so "
                                                  "it wasn't sent again.")
        return
    st.session_state["rep_message"] = ""
    if email:
        note = (f" We emailed {email} that it's waiting." if _rep_tell(email, label, card)
                else " (The email to let them know couldn't be sent.)")
    else:
        note = " " + _rep_untold(signed_in)
    st.session_state["rep_msg"] = ("success", f"Sent the {label} report - it's on their "
                                              f"Advisor notes page.{note}")


def _rep_send_all(values):
    """Clients page: the same report to every client picked, each with their
    own figures; the message is shared."""
    viewer = st.session_state["user_id"]
    kind = st.session_state.get("rep_all_period") or reports.PERIODS[0]
    picked = st.session_state.get("rep_all_clients") or []
    if not picked:
        st.session_state["rep_all_msg"] = ("warning", "Pick at least one client.")
        return
    today = datetime.now().date()
    message = st.session_state.get("rep_all_message") or ""
    done, to_tell = [], []
    no_login = no_email = recent = 0
    c = connect(DB)
    try:
        for cid in picked:
            if cid == viewer or not auth.can_view(c, viewer, cid):
                continue
            label, email, signed_in = _rep_save_one(c, viewer, cid, kind, message,
                                                    values.get(cid), today)
            if signed_in == "just now":   # sent a moment ago: not twice
                continue
            done.append(label)
            if email:
                to_tell.append((email, label))
            elif signed_in == "recent":
                recent += 1
            elif signed_in:
                no_email += 1
            else:
                no_login += 1
        card = prefs.load(c, viewer).get("advisor_card") or {}
    finally:
        c.close()
    failed = 0
    for i, (email, label) in enumerate(to_tell):
        if i:
            time.sleep(0.6)   # the email service takes a couple a second
        failed += not _rep_tell(email, label, card)
    st.session_state["rep_all_message"] = ""
    st.session_state["rep_all_clients"] = []
    told = len(to_tell) - failed
    st.session_state["rep_all_msg"] = (
        "success", f"Sent {len(done)} report{'s' if len(done) != 1 else ''} - each client reads "
        f"theirs on their Advisor notes page."
        + (f" Emailed {told} that it's waiting." if told else "")
        + (f" {no_login} hadn't set up their login yet, so weren't emailed - send them a setup "
           "link from Client login." if no_login else "")
        + (f" {no_email} without a confirmed email will see it next time they sign in."
           if no_email else "")
        + (f" {recent} had an email about a report in the last hour, so no new one went."
           if recent else "")
        + (f" {failed} email(s) couldn't be sent." if failed else ""))


def _render_reports_bulk(rows):
    """Clients page: send a progress report to several clients at once."""
    today = datetime.now().date()
    with st.expander(":material/summarize: Send progress reports"):
        msg = st.session_state.pop("rep_all_msg", None)
        if msg:
            getattr(st, msg[0])(msg[1])
        kind = st.segmented_control("Period", reports.PERIODS, default=reports.PERIODS[0],
                                    key="rep_all_period") or reports.PERIODS[0]
        c = connect(DB)
        try:
            # every client's reports at once, not two queries per client
            ends, sent = reports.sent(c, [r["user_id"] for r in rows])
        finally:
            c.close()
        labels = {r["user_id"]: reports.period_bounds(
            kind, today, ends.get(r["user_id"]))[2] for r in rows}
        already = {r["user_id"] for r in rows if (r["user_id"], labels[r["user_id"]]) in sent}
        names = {r["user_id"]: r["name"] for r in rows}
        if "rep_all_clients" not in st.session_state or                 st.session_state.get("rep_all_for") != kind:
            st.session_state["rep_all_clients"] = [r["user_id"] for r in rows
                                                   if r["user_id"] not in already]
            st.session_state["rep_all_for"] = kind
        st.multiselect("Clients", list(names), key="rep_all_clients",
                       format_func=lambda i: names[i] + (" (already sent)" if i in already
                                                         else ""),
                       placeholder="Pick clients")
        st.text_area("A message for all of them (optional)", key="rep_all_message",
                     placeholder="A note that suits everyone, like a market recap")
        n = len(st.session_state.get("rep_all_clients") or [])
        st.button(f"Send {n} report{'s' if n != 1 else ''}", key="rep_all_send", type="primary",
                  disabled=not n, on_click=_rep_send_all,
                  args=({r["user_id"]: r["portfolio_value"] for r in rows},))
        st.caption("Each client gets their own figures for the period; clients who already "
                   "have this period's report start unticked. Each reads theirs on their "
                   "Advisor notes page - the email only says it's there, and goes only to a "
                   "confirmed email (once a client has set up their login).")


def _rep_body(rep, money):
    lines = reports.summary_lines(rep["facts"], money)
    if not lines:
        lines = ["Not enough history yet to show how the portfolio moved in this period."]
    _md("  \n".join(lines))
    steps = rep["facts"].get("next_steps") or []
    if steps:
        _md("**What's next:**  \n" + "  \n".join(f"- {s}" for s in steps))


def _rep_pdf_button(rep, client_name):
    key = f"rep_pdf_{rep['id']}"
    if st.session_state.get(key):
        st.download_button("Download PDF", st.session_state[key], mime="application/pdf",
                           file_name=f"progress-{rep['period_label'].replace(' ', '-')}.pdf",
                           key=f"rep_dl_{rep['id']}")
    elif st.button("PDF", key=f"rep_mk_{rep['id']}", type="tertiary",
                   # a report is its figures: the file has them, hidden here or not
                   help=("The PDF shows the report's real amounts, even while amounts are "
                         "hidden here." if _hidden() else None)):
        c = connect(DB)
        try:   # the advisor's name and firm as their clients know them
            adv = standing_line.who(c, rep["advisor_id"])
        finally:
            c.close()
        st.session_state[key] = reports.render_pdf(rep, client_name=client_name,
                                                   advisor_name=adv["name"], firm=adv["firm"])
        st.rerun()


def _render_report_advisor(value):
    """Advisor only, on a client's Advisor notes page."""
    today = datetime.now().date()
    c = connect(DB)
    try:
        sent = reports.for_client(c, USER_ID)
        last = reports.last_end(c, USER_ID)
    finally:
        c.close()
    with st.expander(":material/summarize: Progress report", expanded=False):
        msg = st.session_state.pop("rep_msg", None)
        if msg:
            getattr(st, msg[0])(msg[1])
        kind = st.segmented_control("Period", reports.PERIODS, default=reports.PERIODS[1],
                                    key="rep_period") or reports.PERIODS[1]
        start, end, label = reports.period_bounds(kind, today, last)
        c = connect(DB)
        try:
            facts = reports.build(c, USER_ID, start, end, value_now=value, today=today)
        finally:
            c.close()
        st.markdown(f"**Preview - {label}**")
        _rep_body({"facts": facts}, fmt_money0)
        st.text_area("A message from you (optional)", key="rep_message",
                     placeholder="How things went, and what you'd like to talk about next time")
        st.button(f"Send the {label} report to {ACTIVE_NAME}", key="rep_send", type="primary",
                  on_click=_rep_send, args=(value,))
        st.caption("They read it on their Advisor notes page. The email only tells them it's "
                   "there - the figures aren't sent by email - and goes only to a confirmed "
                   "email (once they've set up their login).")
        if sent:
            st.markdown("**Sent before:** " + ", ".join(
                f"{r['period_label']} ({'read' if r['read_at'] else 'not read yet'})"
                for r in sent[:6]))


def _rep_open(report_id):
    c = connect(DB)
    try:
        reports.mark_read(c, st.session_state["user_id"], report_id)
    finally:
        c.close()


def _render_reports_client():
    """On a client's Advisor notes page: the reports their advisor sent."""
    c = connect(DB)
    try:
        sent = reports.for_client(c, USER_ID)
    finally:
        c.close()
    if not sent:
        return
    st.markdown("#### Progress reports")
    for i, rep in enumerate(sent[:8]):
        new = " - new" if not rep["read_at"] else ""
        with st.expander(f"{rep['period_label']}{new}", expanded=(i == 0 and not rep["read_at"])):
            if not rep["read_at"] and st.session_state.get("user_id") == USER_ID:
                _rep_open(rep["id"])
            if rep.get("message"):
                _md(f"**From your advisor:** {rep['message']}")
            _rep_body(rep, fmt_money0)
            _render_standing(rep["advisor_id"])   # whose advice it is (standing_line.py)
            _rep_pdf_button(rep, ACTIVE_NAME)
