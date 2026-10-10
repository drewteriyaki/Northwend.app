# Part of dashboard.py, which runs this file with _view("clients") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Advisor side: notes and next steps, the advisor card, model portfolios,
# the Clients page, and the weekly summary notice.
# ruff: noqa: F821

import rate_limits
import standing_line

# ---- advisor notes, the advisor card, the clients page ------------------------ #
_NOTE_ICON = {"Review": ":material/event:", "Note": ":material/notes:",
              "Next step": ":material/flag:"}


def _render_advisor_card(card):
    """How a managed client sees their advisor: name, firm, contact, message."""
    name = card.get("name") or card.get("username") or "Your advisor"
    contact = " · ".join(v for v in (card.get("email"), card.get("phone")) if v)
    with st.container(border=True):
        # (_md_name escapes "$" itself, so plain st.markdown)
        st.markdown(f"**Your advisor: {_md_name(name)}**"
                    + (f" · {_md_name(card['firm'])}" if card.get("firm") else ""))
        if contact:
            st.caption(contact)
        if card.get("message"):
            _md(card["message"])
        if MY_ADVISOR:   # whose advice the notes below are (standing_line.py)
            _render_standing(MY_ADVISOR)


def _notes_for_view(conn):
    """This account's advisor notes as the viewer may see them: an advisor on a
    client's account sees their own private ones too; the client never does."""
    return advising.list_notes(conn, USER_ID, include_private=ON_CLIENT,
                               advisor_id=LOGIN_ID if ON_CLIENT else None)


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

    # only the note's own advisor changes it (advisor_id): never the client,
    # never another advisor
    def _set_done(note_id, done):
        c = connect(DB)
        try:
            advising.set_done(c, USER_ID, note_id, done, advisor_id=st.session_state["user_id"])
        finally:
            c.close()

    def _archive(note_id, archive):
        c = connect(DB)
        try:
            me = st.session_state["user_id"]
            ok = (advising.archive_note(c, USER_ID, note_id, advisor_id=me) if archive
                  else advising.restore_note(c, USER_ID, note_id, advisor_id=me))
        finally:
            c.close()
        if ok:
            st.toast("Archived - it's kept, and Show archived brings it back." if archive
                     else "Restored.")

    def _edit(note_id):
        body = st.session_state.get(f"note_edit_{note_id}")
        c = connect(DB)
        try:
            advising.edit_note(c, USER_ID, note_id, body, advisor_id=st.session_state["user_id"])
        except ValueError:
            st.toast("A note needs some text - nothing was changed.")
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
                if ON_CLIENT and n["advisor_id"] == LOGIN_ID:
                    st.button("Mark done", key=f"note_done_{n['id']}", type="tertiary",
                              on_click=_set_done, args=(n["id"], True))

    st.markdown("#### Timeline")
    if not notes:
        st.caption("No notes yet." if ON_CLIENT else "Notes from your advisor show up here.")
    for n in notes:
        _render_note(n, _set_done, _archive, _edit)
    if ON_CLIENT:
        st.caption("The client sees everything here except private and archived notes. "
                   "Nothing is deleted: Archive hides a note and keeps it, and an edit keeps "
                   "the earlier text.")
        _render_archived_notes(_archive)
        _render_client_record()
        with st.expander(":material/link_off: End the relationship"):
            _render_end_confirm(USER_ID, "notes")
    elif IS_MANAGED_CLIENT:
        # the client's own choice to show their walks (views/client_book.py; R16)
        if flags.on("client_owned_book"):
            render_walk_share()
        _render_stop_sharing()


def _render_note(n, set_done, archive, edit):
    """One note in the timeline. The advisor (ON_CLIENT) can edit it, archive
    it and see its earlier text; the client sees it as it is now."""
    label = n["kind"] + (" (done)" if n["kind"] == "Next step" and n["done"] else "")
    archived = bool(n.get("archived_at"))
    with st.container(border=True):
        st.caption(f"{_NOTE_ICON.get(n['kind'], '')} **{label}** · {_fmt_date(n['note_date'])}"
                   + (" · Message" if n.get("is_message") else "")
                   + (" · :orange[Private]" if n["private"] else "")
                   + (f" · edited {_fmt_date(n['edited_at'][:10])}" if n.get("edited_at") else "")
                   + (f" · archived {_fmt_date(n['archived_at'][:10])}" if archived else ""))
        _md(n["body"])
        if n.get("is_message") and n.get("advisor_id"):   # a message: whose advice it is
            _render_standing(n["advisor_id"])
        if not ON_CLIENT or n.get("advisor_id") != LOGIN_ID:   # only the note's own advisor
            return
        earlier = advising.note_history(n)
        if earlier:
            with st.expander(f"Earlier text ({len(earlier)})"):
                for h in reversed(earlier):
                    st.caption(f"Until {_fmt_date(h['replaced_at'][:10])}")
                    _md(h["body"])
        with st.container(horizontal=True):
            if archived:
                st.button("Restore", key=f"note_restore_{n['id']}", type="tertiary",
                          icon=":material/unarchive:", on_click=archive, args=(n["id"], False))
                return
            if n["kind"] == "Next step" and n["done"]:
                st.button("Reopen", key=f"note_undo_{n['id']}", type="tertiary",
                          on_click=set_done, args=(n["id"], False))
            with st.popover("Edit", type="tertiary", width=90):
                st.text_area("Note", value=n["body"], key=f"note_edit_{n['id']}")
                st.caption("The earlier text is kept with the note.")
                st.button("Save", key=f"note_save_{n['id']}", type="primary",
                          on_click=edit, args=(n["id"],))
            st.button("Archive", key=f"note_archive_{n['id']}", type="tertiary",
                      on_click=archive, args=(n["id"], True),
                      help="Hide it from this page and the client's. It's kept, and Show "
                           "archived brings it back.")


def _render_archived_notes(archive):
    """The advisor's Show archived: notes they archived, with Restore."""
    if not st.toggle("Show archived", key="notes_show_archived"):
        return
    conn = connect(DB)
    try:
        gone = advising.list_notes(conn, USER_ID, include_private=True, archived=True,
                                   advisor_id=LOGIN_ID)
        gone = [n for n in gone if n["advisor_id"] == LOGIN_ID]   # only their own to restore
    finally:
        conn.close()
    st.markdown("#### Archived")
    if not gone:
        st.caption("Nothing archived.")
    for n in gone:
        _render_note(n, None, archive, None)


def _prepare_client_record():
    """Export this client's record: the advisor's own notes (archived and
    earlier text too), proposals, reports and the client's answers, as a ZIP
    kept for the download button."""
    import export
    if not _limit_ok(rate_limits.EXPORT):
        _limit_hit("client_record")
        return
    c = connect(DB)
    try:
        data = export.client_record_zip(c, LOGIN_ID, USER_ID)
    except PermissionError:
        data = None
    finally:
        c.close()
    if data is not None:
        st.session_state["client_record"] = (USER_ID, export.record_file_name(ACTIVE_NAME), data,
                                             datetime.now(timezone.utc).strftime("%H:%M UTC"))


def _prepare_all_records():
    """Your clients: every client's record in one ZIP (a folder each)."""
    import export
    if not _limit_ok(rate_limits.EXPORT):
        _limit_hit("all_records")
        return
    c = connect(DB)
    try:
        data = export.all_client_records_zip(c, LOGIN_ID)
    finally:
        c.close()
    st.session_state["all_records"] = (export.record_file_name(None), data,
                                       datetime.now(timezone.utc).strftime("%H:%M UTC"))


def _render_all_records():
    """Your clients: Export all client records."""
    with st.expander(":material/folder_zip: Export all client records"):
        st.caption("One ZIP with a folder for each of your clients: your notes, reviews, next "
                   "steps and messages (archived ones and earlier text too), proposals and "
                   "their answers, progress reports sent, and their profile answers. Keep it "
                   "with your firm's records. Only your own clients and your own records.")
        _limit_note("all_records")
        ready = st.session_state.get("all_records")
        if ready:
            with st.container(horizontal=True, vertical_alignment="center"):
                st.download_button("Download all records", ready[1], file_name=ready[0],
                                   mime="application/zip", key="all_records_download",
                                   type="primary", on_click="ignore", icon=":material/download:")
                st.button(f"Prepared at {ready[2]} - prepare again", key="all_records_again",
                          type="tertiary", on_click=_prepare_all_records)
        else:
            st.button("Prepare all records", key="all_records_prepare",
                      on_click=_prepare_all_records, icon=":material/folder_zip:")


def _render_client_record():
    """Advisor notes page (advisor side): Export this client's record."""
    with st.expander(":material/folder_zip: Export this client's record"):
        st.caption("Everything you've recorded for this client, as spreadsheet (CSV) files in "
                   "one ZIP: notes, reviews, next steps and messages (archived ones and earlier "
                   "text too), proposals and their answers, progress reports sent, and their "
                   "profile answers. Only your own records - never their password or sign-in "
                   "details.")
        _limit_note("client_record")
        ready = st.session_state.get("client_record")
        if ready and ready[0] == USER_ID:
            with st.container(horizontal=True, vertical_alignment="center"):
                st.download_button("Download the record", ready[2], file_name=ready[1],
                                   mime="application/zip", key="client_record_download",
                                   type="primary", on_click="ignore", icon=":material/download:")
                st.button(f"Prepared at {ready[3]} - prepare again", key="client_record_again",
                          type="tertiary", on_click=_prepare_client_record)
        else:
            st.button("Prepare the record", key="client_record_prepare",
                      on_click=_prepare_client_record, icon=":material/folder_zip:")


# ---- ending a relationship (advising.end_relationship) ----------------------- #
def _end_relationship(client_id):
    """The advisor ends it: the client keeps their account (or, with no way
    in at all, it's closed) and gets a short email from the advisor; the
    advisor's records stay under Former clients."""
    viewer = st.session_state["user_id"]
    if not st.session_state.get(f"end_ok_{client_id}"):
        st.session_state["end_msg"] = (client_id, "Tick the box to confirm first.")
        return
    c = connect(DB)
    try:
        if (viewer == client_id or not auth.is_advisor(c, viewer)
                or not auth.can_view(c, viewer, client_id)):
            return
        res = advising.end_relationship(c, viewer, client_id, by="advisor")
        email = res["client_email"] if res["ok"] and res["account"] != "closed" else None
        # at most one such email an hour to an address (auth.notice_ok)
        tell = bool(email) and auth.notice_ok(c, "ended", email)
        card = prefs.load(c, viewer).get("advisor_card") or {}
    finally:
        c.close()
    if not res["ok"]:
        st.session_state["client_msg"] = ("info", res["error"])
        return
    sent = False
    if tell:
        body_name, from_name = _advisor_names(card, st.session_state["username"])
        token = res["setup_token"]
        sent = mailer.relationship_ended(
            email, f"{_app_address()}?reset={token}" if token else _app_address(), body_name,
            setup_days=auth.SETUP_DAYS if token else None, from_name=from_name)
    name = res["name"]
    text = {"kept": f"Ended your relationship with {name}. They keep their account and manage "
                    "it themselves from now on.",
            "setup link": f"Ended your relationship with {name}. They keep their account",
            "closed": f"Ended your relationship with {name} and closed their account - nobody "
                      "could have opened it."}[res["account"]]
    if res["account"] == "setup link":
        text += (" - we emailed them a link to choose a password." if sent else
                 ". The email with their password link couldn't go just now - they can use "
                 "Forgot password with their email to get in.")
    elif email:
        text += (" We emailed them to let them know." if sent else
                 " No email went just now - you may want to tell them yourself.")
    text += " Your notes, proposals and reports are under **Former clients** below."
    if st.session_state.get("active_user_id") == client_id:
        _switch_to(viewer)
    st.session_state["page"] = "Clients"
    st.session_state["client_msg"] = ("success", text)


def _render_end_confirm(client_id, where, plan=None):
    """The confirm step for ending a relationship: what happens, then a box
    to tick and the button. `plan` is advising.ending_plan's answer when the
    page already has what it needs (Your clients' cards); read here
    otherwise. Ending itself works it out again."""
    if plan is None:
        c = connect(DB)
        try:
            plan = advising.ending_plan(c, LOGIN_ID, client_id)
        finally:
            c.close()
    if plan is None:
        return
    msg = st.session_state.get("end_msg")
    if msg and msg[0] == client_id:
        st.session_state.pop("end_msg")
        st.error(msg[1])
    name = _md_name(plan["name"])
    account = {
        "kept": f"**{name}** keeps their account and everything in it, and manages it "
                "themselves from now on. You'll no longer see their portfolio.",
        "setup link": f"**{name}** hasn't set up their login yet, so we'll email them a link "
                      "to choose a password and keep the account. A password you set for "
                      "them stops working.",
        "closed": f":orange[**{name}** has never signed in and there's no email for them, so "
                  "nobody could open this account afterwards. It will be **closed**: the "
                  "holdings and plan in it are deleted.]"}[plan["account"]]
    st.markdown(account)
    st.markdown("Your notes, proposals and reports about them are **kept** - under Former "
                "clients on Your clients, where you can still export their record."
                + (" They get a short email from you saying it has ended - no figures."
                   if plan["email"] and plan["account"] != "closed" else ""))
    st.checkbox("I understand - end this relationship", key=f"end_ok_{client_id}")
    st.button("End relationship", key=f"end_go_{where}_{client_id}", type="primary",
              on_click=_end_relationship, args=(client_id,))


def _stop_sharing():
    """A client ends it (Your advisor > Stop sharing with my advisor): they
    keep everything; their advisor is emailed and keeps their own records."""
    me = st.session_state["user_id"]
    if not st.session_state.get("stop_sharing_ok"):
        st.session_state["stop_sharing_msg"] = "Tick the box to confirm first."
        return
    c = connect(DB)
    try:
        adv = advising.advisor_of(c, me)
        if adv is None:
            return
        # the confirm step's words go with the consent revoke (consent.py)
        res = advising.end_relationship(c, adv, me, by="client",
                                        text_shown=st.session_state.get("_stop_sharing_text"))
        to = auth.email_status(c, adv)
        email = (to["email"] if res["ok"] and to["confirmed"]
                 and auth.notice_ok(c, "ended", to["email"]) else None)
    finally:
        c.close()
    if email:
        # what the advisor calls them (Your clients), so they know who it is
        mailer.client_stopped_sharing(email, f"{_app_address()}?page=your-clients",
                                      res["name"])
    st.session_state["page"] = "Dashboard"
    st.session_state["import_flash"] = ("You've stopped sharing with your advisor. Everything "
                                        "is still here, and it's yours to manage from now on.")
    st.toast("You've stopped sharing with your advisor.")


def _render_stop_sharing():
    """Your advisor page (a managed client): stop sharing, with a confirm step."""
    msg = st.session_state.pop("stop_sharing_msg", None)
    with st.expander(":material/link_off: Stop sharing with my advisor", expanded=bool(msg)):
        if msg:
            st.error(msg)
        words = (f"Your advisor, {_advisor_display_name()}, will no longer see your account. "
                 "You keep everything - your holdings, plan and goals - and manage them "
                 "yourself from now on.",
                 "Your advisor keeps their own notes about your time working together, for "
                 "their records. We'll let them know you've stopped sharing.")
        st.session_state["_stop_sharing_text"] = "\n\n".join(words)
        st.markdown(f"Your advisor, **{_md_name(_advisor_display_name())}**, will no longer "
                    "see your account. You keep everything - your holdings, plan and goals - "
                    "and manage them yourself from now on.")
        st.markdown(words[1])
        if flags.on("client_owned_book"):
            # what each side keeps, in full (views/client_book.py; R16) - the
            # words go with the consent revoke too
            st.session_state["_stop_sharing_text"] = "\n\n".join(words + render_exit_keeps())
        st.checkbox("I understand - stop sharing my account", key="stop_sharing_ok")
        st.button("Stop sharing", key="stop_sharing", type="primary", on_click=_stop_sharing)


def _prepare_former_record(client_id, name):
    import export
    if not _limit_ok(rate_limits.EXPORT):
        _limit_hit("former_record")
        return
    c = connect(DB)
    try:
        data = export.client_record_zip(c, LOGIN_ID, client_id)
    except PermissionError:
        data = None
    finally:
        c.close()
    if data is not None:
        st.session_state["former_record"] = (client_id, export.record_file_name(name), data)


def _render_former_clients():
    """Your clients: relationships that ended - the advisor's records stay."""
    c = connect(DB)
    try:
        former = advising.former_clients(c, LOGIN_ID)
    finally:
        c.close()
    if not former:
        return
    with st.expander(f":material/inventory_2: Former clients ({len(former)})"):
        st.caption("Clients whose relationship with you ended. You no longer see their "
                   "accounts; your notes, proposals and reports about them are kept here, and "
                   "in Export all client records.")
        _limit_note("former_record")
        ready = st.session_state.get("former_record")
        for f in former:
            name = f["client_name"] or f"Client {f['client_id']}"
            who = "you ended it" if f["ended_by"] == "advisor" else "they stopped sharing"
            closed = " · account closed" if f["account"] == "closed" else ""
            with st.container(horizontal=True, vertical_alignment="center"):
                st.html(f"<b>{html.escape(name)}</b> <span class='pt-muted'>· ended "
                        f"{html.escape(_fmt_date(f['ended_at'][:10]))} · {who}{closed}</span>",
                        width="stretch")
                if ready and ready[0] == f["client_id"]:
                    st.download_button("Download the record", ready[2], file_name=ready[1],
                                       mime="application/zip", on_click="ignore",
                                       key=f"former_dl_{f['client_id']}",
                                       icon=":material/download:")
                else:
                    st.button("Prepare the record", key=f"former_prep_{f['client_id']}",
                              type="tertiary", icon=":material/folder_zip:",
                              on_click=_prepare_former_record, args=(f["client_id"], name))


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
        st.caption("Shown to clients whose accounts you manage: on their **Your advisor** page "
                   "and in the menu under their name.")
        st.session_state["weekly_email_on"] = not p.get("weekly_email_off")  # what's saved
        st.toggle("Monday email", key="weekly_email_on", on_change=_set_weekly_email,
                  help="A short email on Monday mornings when reviews are due or a client "
                       "accepted a proposal - counts only, no client names or figures. Sent to "
                       "your login email once it's confirmed.")


def _set_weekly_email():
    c = connect(DB)
    try:
        p = prefs.load(c, LOGIN_ID)
        if st.session_state.get("weekly_email_on"):
            p.pop("weekly_email_off", None)
        else:
            p["weekly_email_off"] = True
        prefs.save(c, LOGIN_ID, p)
    finally:
        c.close()


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
    import proposals
    import reports

    conn = connect(DB)
    try:
        # only the tickers these clients hold
        _ids = tuple(cid for cid, _ in CLIENTS)
        quotes = overview.latest_quotes(conn, overview.held_symbols(conn, _ids))
        # read for the whole book at once, not once per client
        logins, emails = overview.login_facts(conn, _ids)
        all_props = proposals.open_counts(conn, _ids)
        last_reports = reports.latest_labels(conn, _ids)
        can_import = advising.clients_can_import(conn, _ids)
        # who hasn't confirmed sharing in their own words yet (consent.py, step 5.7)
        unconfirmed = consent.unconfirmed(conn, LOGIN_ID)
        # their settings (alert limits, asset-class choices), summaries, plans
        # and notes: each read once for the whole book
        saved = prefs.load_many(conn, _ids, _legacy_prefs_path)
        summaries = overview.account_summaries(
            conn, _ids, quotes, {cid: _rules_from(saved[cid]) for cid in _ids},
            overrides={cid: asset_classes.overrides_in(saved[cid]) for cid in _ids})
        all_plans = plans.get_plans(conn, _ids)
        all_notes = advising.notes_for(conn, _ids, include_private=True, advisor_id=LOGIN_ID)
        rows = []
        for cid, name in CLIENTS:
            summ = summaries[cid]
            plan = all_plans[cid]
            goal = (plans.progress(plan, summ["portfolio_value"] or 0.0, today=today)
                    if plans.has_goal(plan) else None)
            drift = (advising.max_drift(summ["alloc_pct"], (plan or {}).get("target_alloc"))
                     if summ["has_data"] else None)
            notes = all_notes[cid]
            review, days = advising.review_status(advising.last_review_in(notes), today)
            steps = advising.open_next_steps(notes)
            login = logins.get(cid)
            login_days = ((today - date.fromisoformat(login[:10])).days if login else None)
            props = all_props.get(cid, {})
            rows.append({**summ, "name": name, "email": emails.get(cid), "plan": plan,
                         "goal": goal, "drift": drift,
                         "can_import": cid in can_import,
                         "unconfirmed": cid in unconfirmed,
                         "review": review, "review_days": days, "n_steps": len(steps),
                         "login_days": login_days, "proposals": props,
                         "last_report": last_reports.get(cid),
                         "reasons": advising.attention(
                             has_data=summ["has_data"],
                             goal_status=goal["status"] if goal else None, review=review,
                             n_alerts=summ["n_alerts_attention"], drift=drift,
                             profile_done=summ["profile_answered"] >= summ["profile_total"],
                             proposal_accepted=bool(props.get("accepted")),
                             days_since_login=login_days)})
    finally:
        conn.close()
    # who needs a look first, then the biggest accounts
    rows.sort(key=lambda r: (-len(r["reasons"]), -(r["portfolio_value"] or 0.0)))
    return rows


def _client_msg():
    """The message from Add client, renaming or a send - with an Open button
    for the client it's about."""
    msg = st.session_state.pop("client_msg", None)
    if not msg:
        return
    getattr(st, msg[0])(msg[1])
    if len(msg) > 2 and msg[2] in dict(CLIENTS):
        st.button(f"Open {dict(CLIENTS)[msg[2]]}", key="client_msg_open", icon=":material/login:",
                  on_click=_open_client, args=(msg[2],))


def _render_add_client():
    """Add client, at the top of Your clients: their name or household and
    their email; with an email, the setup link goes out in the same step.
    Before the first invite, the advisor's own name and firm (who it's from)."""
    _client_msg()
    if not SEAT_OPEN:   # a paid seat that isn't active: one line instead (views/billing.py)
        _render_seat_paused("add")
        return
    with st.expander(":material/person_add: Add client", expanded=not CLIENTS):
        c1, c2 = st.columns(2)
        c1.text_input("Name or household", key="new_client_name", max_chars=auth.CLIENT_NAME_MAX,
                      placeholder="e.g. Dana Lee or Chen household",
                      help="How they're listed for you. Only you see it; you can change it "
                           "later.")
        c2.text_input("Their email", key="new_client_email", max_chars=100,
                      placeholder="name@example.com",
                      help="Where the setup link goes. Leave it blank to manage the account "
                           "yourself for now.")
        has_email = bool((st.session_state.get("new_client_email") or "").strip())
        invite = st.checkbox("Email them a setup link", value=True, key="new_client_invite",
                             disabled=not has_email,
                             help="They choose their own password - you never see it - then "
                                  "answer a few questions about their goals before your first "
                                  "meeting.") and has_email
        if invite:
            _render_who_from("new_adv")
        st.button("Add and send invite" if invite else "Add client", key="add_client",
                  on_click=_add_client, type="primary")
    _render_add_from_file()


def _render_who_from(prefix):
    """Before the first invite (no name under How clients see you yet): the
    advisor's name and firm, saved by _save_invite_card."""
    conn = connect(DB)
    try:
        card = prefs.load(conn, LOGIN_ID).get("advisor_card") or {}
    finally:
        conn.close()
    if card.get("name"):
        return
    st.markdown("**Who's it from?** Your name and firm go in the invite, so they "
                "know it's you.")
    c1, c2 = st.columns(2)
    c1.text_input("Your name", key=f"{prefix}_name", max_chars=60,
                  placeholder="e.g. Dana Ruiz")
    c2.text_input("Firm (optional)", key=f"{prefix}_firm", max_chars=80,
                  placeholder="e.g. Ruiz Wealth")
    st.caption("Saved under **How clients see you** at the bottom of this page, "
               "where you can change it any time.")


# ---- adding clients from a file (client_csv.py) ------------------------------ #
def _bulk_reset():
    st.session_state.pop("bulk_review", None)
    st.session_state["bulk_upload_n"] = st.session_state.get("bulk_upload_n", 0) + 1


def _add_clients_from_file():
    """Add the file's ready rows (client_csv.review, re-checked by
    create_client) through the same path as Add client, and email each a
    setup link while today's limit allows (_send_invite)."""
    review = st.session_state.get("bulk_review")
    viewer = st.session_state["user_id"]
    invite = bool(st.session_state.get("bulk_invite", True))
    if not review:
        return
    if not _seat_ok():   # a paid seat that isn't active (views/billing.py)
        return
    if not _limit_ok(rate_limits.SAVE):   # many adds in a short time: nothing added
        st.session_state["bulk_msg"] = ("info", LIMIT_TEXT)
        return
    ready = [r for r in review[1] if r["state"] == "ok"]
    added, invited, not_sent, failed = [], 0, {}, 0
    c = connect(DB)
    try:
        if not auth.is_advisor(c, viewer):
            return
        if invite:
            missing = _save_invite_card(c, viewer, "bulk_adv")
            if missing:
                st.session_state["bulk_msg"] = ("error", missing)
                return
        for r in ready:
            try:
                client_id, shown, sent = _add_one_client(c, viewer, r["name"], r["email"],
                                                         invite)
            except (ValueError, DBError):
                failed += 1   # taken since the review (or by another row): not added
                continue
            added.append(client_id)
            if sent and sent[0]:
                invited += 1
                if not mailer.dry_run():
                    time.sleep(0.6)   # the email service takes a couple a second
            elif sent:
                not_sent[sent[1]] = not_sent.get(sent[1], 0) + 1
    finally:
        c.close()
    n = len(added)
    text = f"Added {n} client{'s' if n != 1 else ''}."
    if invite and invited:
        text += f" Setup links went to {invited}."
    for why, k in not_sent.items():
        text += (f" {k} didn't get a setup link yet: {why[0].lower()}{why[1:].rstrip('.')}. "
                 "Send theirs from **Client login** in their account.")
    if failed:
        text += (f" {failed} couldn't be added - their email has a Northwend account "
                 "already.")
    st.session_state["client_msg"] = ("success" if n and not not_sent and not failed
                                      else "warning", text)
    _bulk_reset()


def _render_add_from_file():
    """Your clients: Add clients from a file - review each row first."""
    import hashlib

    import client_csv

    msg = st.session_state.pop("bulk_msg", None)
    with st.expander(":material/upload_file: Add clients from a file",
                     expanded=bool(msg or st.session_state.get("bulk_review"))):
        if msg:
            getattr(st, msg[0])(msg[1])
        st.caption(f"A CSV file with a row per client: their name (or household) and email - "
                   f"up to {client_csv.MAX_ROWS} rows. Most spreadsheets and CRMs can save one. "
                   "You'll see every row before anything is added. The file itself isn't kept.")
        up = st.file_uploader("Your client list (CSV)", type=["csv", "txt"],
                              key=f"bulk_upload_{st.session_state.get('bulk_upload_n', 0)}")
        if up is None:
            st.session_state.pop("bulk_review", None)
            return
        data = bytes(up.getvalue())   # read in memory, never written anywhere
        sig = (up.name, len(data), hashlib.sha256(data).hexdigest())
        review = st.session_state.get("bulk_review")
        if not review or review[0] != sig:
            if not _upload_ok(up):   # many files in a short time (rate_limits.py)
                st.info(LIMIT_TEXT)
                return
            parsed = client_csv.parse(data)
            if not parsed["ok"]:
                st.warning(parsed["error"])
                return
            c = connect(DB)
            try:
                review = (sig, client_csv.review(c, LOGIN_ID, parsed["rows"]))
            finally:
                c.close()
            st.session_state["bulk_review"] = review
        rows = review[1]
        n = client_csv.counts(rows)
        ready = n["ok"]
        others = len(rows) - ready
        st.markdown(f"**{ready} of {len(rows)} ready to add.**"
                    + (f" {others} need{'s' if others == 1 else ''} a look - they won't be "
                       "added." if others else ""))
        st.dataframe(pd.DataFrame([{"Row": r["row"], "Name": r["name"] or "",
                                    "Email": r["email"], "Status": client_csv.STATES[r["state"]],
                                    "Why": r["why"]} for r in rows]),
                     hide_index=True, width="stretch", height=min(38 + 35 * len(rows), 320))
        if others:
            st.download_button("Download the rows that need a look",
                               client_csv.needs_a_look_csv(rows), on_click="ignore",
                               file_name="clients-to-check.csv", mime="text/csv",
                               key="bulk_problems", icon=":material/download:", type="tertiary")
            if n["taken"]:
                st.caption("An email that already has a Northwend account can't be added as a "
                           "new client - as with Add client.")
        if not ready:
            st.button("Choose another file", key="bulk_again", on_click=_bulk_reset)
            return
        invite = st.checkbox("Email each of them a setup link", value=True, key="bulk_invite",
                             help="They choose their own password - you never see it - then "
                                  "answer a few questions about their goals.")
        if invite:
            c = connect(DB)
            try:
                left = auth.invites_left_today(c, LOGIN_ID)
            finally:
                c.close()
            if ready > left:
                st.info(f"You can email {auth.INVITES_PER_ADVISOR_PER_DAY} setup links a day, "
                        f"and {left} are left today. Everyone is added; "
                        f"{'the first ' + str(left) if left else 'none'} get their link now, "
                        "and you can send the rest from **Client login** in their account "
                        "tomorrow.")
            _render_who_from("bulk_adv")
        with st.container(horizontal=True):
            st.button(f"Add {ready} client{'s' if ready != 1 else ''}"
                      + (" and send invites" if invite else ""),
                      key="bulk_add", type="primary", on_click=_add_clients_from_file)
            st.button("Cancel", key="bulk_cancel", type="tertiary", on_click=_bulk_reset)


def _rename_client(client_id):
    name = st.session_state.get(f"rename_{client_id}")
    c = connect(DB)
    try:
        ok = auth.set_client_name(c, st.session_state["user_id"], client_id, name)
    finally:
        c.close()
    if ok:
        st.session_state["client_msg"] = ("success", "Saved the new name."
                                          if auth.clean_client_name(name) else
                                          "Name cleared - they're listed by their own name or "
                                          "login.")


def _send_message():
    """Message clients: a Note on each picked client's Your advisor page, and
    a short email to those who can sign in and have a confirmed email - it
    only says there's a message (no text, no figures)."""
    viewer = st.session_state["user_id"]
    picked = st.session_state.get("msg_clients") or []
    body = st.session_state.get("msg_body") or ""
    st.session_state["msg_confirm"] = False
    if not _seat_ok():   # a paid seat that isn't active (views/billing.py)
        return
    c = connect(DB)
    try:
        res = advising.message_clients(c, viewer, picked, body,
                                       now=datetime.now(timezone.utc),
                                       today=datetime.now().date())
        to_email, waited = [], 0
        if res["ok"]:
            confirmed = auth.confirmed_emails(c, res["sent_to"])
            # at most one "you have a message" email an hour per client: more
            # messages are still on their page, only the email waits
            to_email = [e for e in confirmed if auth.notice_ok(c, "message", e)]
            waited = len(confirmed) - len(to_email)
        card = prefs.load(c, viewer).get("advisor_card") or {}
        standing = standing_line.for_advisor(c, viewer)   # whose advice it is (brief 4.4)
    finally:
        c.close()
    if not res["ok"]:
        st.session_state["msg_result"] = ("warning", res["error"])
        return
    body_name, from_name = _advisor_names(card, st.session_state["username"])
    emailed = 0
    for i, email in enumerate(to_email):
        if i:
            time.sleep(0.6)   # the email service takes a couple a second
        emailed += bool(mailer.advisor_message(email, f"{_app_address()}?page=your-advisor",
                                               body_name, standing=standing,
                                               from_name=from_name))
    n, in_app = len(res["sent_to"]), len(res["sent_to"]) - emailed - waited
    text = (f"Sent to {n} client{'s' if n != 1 else ''} - it's on their Advisor notes page. "
            + (f"Emailed {emailed} that it's there. " if emailed else "")
            + (f"{waited} had an email about a message in the last hour, so no new one "
               "went. " if waited else "")
            + (f"{in_app} will see it next time they sign in "
               "(no confirmed email or login yet" + (", or the email couldn't be sent"
                                                    if len(to_email) > emailed else "") + ")."
               if in_app else ""))
    st.session_state["msg_result"] = ("success", text.strip())
    st.session_state["msg_body"] = ""


def _render_message_clients(rows):
    """Your clients: one message to all clients (or some), checked before it goes."""
    with st.expander(":material/campaign: Message clients"):
        res = st.session_state.pop("msg_result", None)
        if res:
            getattr(st, res[0])(res[1])
        if not SEAT_OPEN:   # a paid seat that isn't active (views/billing.py)
            _render_seat_paused("message")
            return
        names = {r["user_id"]: r["name"] for r in rows}
        if "msg_clients" not in st.session_state:
            st.session_state["msg_clients"] = list(names)
        st.session_state["msg_clients"] = [i for i in st.session_state["msg_clients"]
                                           if i in names]
        st.multiselect("To", list(names), key="msg_clients", format_func=names.get,
                       placeholder="Pick clients",
                       on_change=lambda: st.session_state.update(msg_confirm=False))
        # a first draft (views/drafts.py; flag advisor_drafts): one text for
        # several clients, so only what the advisor types here goes - no card
        _render_draft_tools("message", "msg_body", lambda: {},
                            what="What the message is about (for the draft)")
        st.text_area("Message", key="msg_body", max_chars=advising.MESSAGE_MAX,
                     placeholder="e.g. Markets have been bumpy this week. Your plan already "
                                 "allows for this - no need to do anything. Happy to talk any "
                                 "time.",
                     on_change=lambda: st.session_state.update(msg_confirm=False))
        n = len(st.session_state.get("msg_clients") or [])
        ready = n and (st.session_state.get("msg_body") or "").strip()
        if st.session_state.get("msg_confirm") and ready:
            st.warning(f"Send this message to {n} client{'s' if n != 1 else ''}? It's added to "
                       "their Advisor notes page, and those with a confirmed email get a short "
                       "note that it's there.")
            with st.container(horizontal=True):
                st.button(f"Yes, send to {n}", key="msg_send", type="primary",
                          on_click=_send_message)
                st.button("Cancel", key="msg_cancel", type="tertiary",
                          on_click=lambda: st.session_state.update(msg_confirm=False))
        else:
            st.button(f"Review and send to {n} client{'s' if n != 1 else ''}", key="msg_review",
                      type="primary", disabled=not ready,
                      on_click=lambda: st.session_state.update(msg_confirm=True))
        st.caption("Each client sees it as a note from you on their Advisor notes page. The "
                   "email only says there's a message - the text stays in Northwend.")


def _render_clients():
    if ADVISOR_AGREEMENT_DUE:   # the advisor agreement first (views/advisor_agreement.py)
        _render_advisor_agreement()
        return
    today = datetime.now().date()
    _render_add_client()
    if flags.on("intros") and flags.on("directory"):
        # introductions from Find a guide - only those sent to this advisor
        # (views/intros.py)
        _render_intros_advisor()
        st.divider()
    if not CLIENTS:
        st.info("No clients yet - add your first one with **Add client** just above.")
    else:
        rows = _client_rows(today)
        _week_seen()  # the Clients page shows this week's summary itself
        _summary = advising.weekly_summary(rows)
        with st.expander(":material/event_upcoming: This week", expanded=_summary["any"]):
            _render_week_summary(_summary, where="clients")
        # what clients are reading this season (views/advisor_pack.py; R7)
        if flags.on("advisor_pack"):
            render_pack_season_note(today)
        # the Client-Owned Book (views/client_book.py; R16): how the book works,
        # counts only, and the client-reported label on each card
        _book = flags.on("client_owned_book")
        _book_sig = book_signals(rows, today) if _book else {}
        if _book:
            render_book_note()

        st.html(_stat_row(
                "<div class='pt-stats' role='list' aria-label='Client summary'>"
                f"<div class='pt-stat' role='listitem'><div class='pt-stat-label'>Clients</div>"
                f"<div class='pt-stat-value'>{len(rows)}</div></div>"
                f"<div class='pt-stat' role='listitem'><div class='pt-stat-label'>Total value</div>"
                f"<div class='pt-stat-value'>{fmt_money0(sum(r['portfolio_value'] or 0 for r in rows))}"
                "</div>" + ("<div class='pt-stat-sub'>client-reported</div>" if _book else "")
                + "</div>"
                f"<div class='pt-stat' role='listitem'><div class='pt-stat-label'>Need attention</div>"
                f"<div class='pt-stat-value'>{sum(1 for r in rows if r['reasons'])}</div>"
                f"<div class='pt-stat-sub'>{sum(1 for r in rows if r['review'] != 'ok')} review(s) due"
                "</div></div></div>"))

        if _book:
            render_book_counts(_book_sig, today)

        _render_reports_bulk(rows)
        _render_message_clients(rows)

        # narrow the book down (ROADMAP G9)
        with st.container(horizontal=True, vertical_alignment="bottom"):
            show = st.segmented_control(
                "Show", ["Everyone", "Needs a look", "Review due", "Waiting on you"],
                default="Everyone", key="book_show",
                help="Waiting on you: an accepted proposal to act on, or open next steps."
            ) or "Everyone"
            find = st.text_input("Find a client", key="book_find", placeholder="Find a client",
                                 label_visibility="collapsed")
        wanted = {
            "Everyone": lambda r: True,
            "Needs a look": lambda r: bool(r["reasons"]),
            "Review due": lambda r: r["review"] != "ok",
            "Waiting on you": lambda r: bool(r["proposals"].get("accepted") or r["n_steps"]),
        }[show]
        _find = find.strip().lower()
        rows = [r for r in rows if wanted(r) and (_find in r["name"].lower()
                                                   or _find in (r["email"] or "").lower())]
        if not rows:
            st.caption("No clients match.")

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
                if r["proposals"].get("shared"):
                    bits.append("proposal waiting for their answer")
                if r["snapshot_date"]:
                    bits.append(f"statement {_fmt_date(r['snapshot_date'])}")
                if r["last_report"]:
                    bits.append(f"last report {r['last_report']}")
                if r["login_days"] is not None:
                    bits.append("signed in today" if r["login_days"] == 0
                                else f"signed in {r['login_days']}d ago")
                else:
                    bits.append("login not set up yet")
                if r["unconfirmed"] and r["login_days"] is not None:
                    bits.append("hasn't confirmed sharing yet")
                # the email as plain text (st.html: no mailto link), under the name
                email = (r["email"] if r["email"] and r["email"] != r["name"] else "")
                st.html(
                    "<div class='pt-goal-top'>"
                    f"<b>{html.escape(r['name'])}</b>"
                    + (f"<span>{fmt_money0(r['portfolio_value'])}</span>"
                       f"{_tone(gain, fmt_pct(gain)) if gain is not None else ''}"
                       if r["has_data"] else "<span class='pt-muted'>no statement yet</span>")
                    + "</div>"
                    + (f"<div class='pt-goal-sub'>{html.escape(email)}</div>" if email else "")
                    + (book_card_html(r, _book_sig) if _book else "")
                    + f"<div style='margin:.45rem 0'>{chips}</div>"
                    f"<div class='pt-goal-sub'>{' · '.join(bits)}</div>")
                with st.container(horizontal=True, vertical_alignment="center"):
                    st.button("Open", key=f"open_client_{r['user_id']}", on_click=_open_client,
                              args=(r["user_id"],))
                    with st.popover("Rename", type="tertiary", width=110):
                        st.text_input("Name or household", value=r["name"],
                                      key=f"rename_{r['user_id']}",
                                      max_chars=auth.CLIENT_NAME_MAX,
                                      help="Only you see it. Leave it blank to go back to "
                                           "their own name or login.")
                        st.button("Save name", key=f"rename_save_{r['user_id']}",
                                  type="primary", on_click=_rename_client, args=(r["user_id"],))
                    key = f"can_import_{r['user_id']}"
                    st.session_state[key] = r["can_import"]  # always what's saved
                    st.toggle("Client can import", key=key, on_change=_set_can_import,
                              args=(r["user_id"],),
                              help="Let this client import their own statements. Their plan, "
                                   "goal, target mix and alert limits stay yours to set.")
                    with st.popover("End", type="tertiary", width=90,
                                    help="End your relationship with this client"):
                        _render_end_confirm(r["user_id"], "card", plan={
                            "name": r["name"], "email": r["email"],
                            "account": ("kept" if r["login_days"] is not None else
                                        "setup link" if r["email"] else "closed")})
        st.caption(f"Sorted by what needs a look. Reviews are due {advising.REVIEW_EVERY_DAYS} days "
                   f"after the last one; drift is flagged past {advising.DRIFT_ATTENTION_PTS:g} "
                   "points from the plan's target mix; alerts count holdings past the "
                   "client's own day-move limit, or down past their gain/loss limit (gains "
                   "don't count); a "
                   f"client who used to sign in is flagged after {advising.INACTIVE_DAYS} days "
                   "away."
                   + (" Hasn't confirmed sharing yet: we'll ask them once, the next time they "
                      "sign in, whether to keep sharing with you - until then you see their "
                      "account as today." if any(r["unconfirmed"] for r in rows) else ""))
        _render_all_records()
    _render_former_clients()
    st.divider()
    _render_models()
    st.divider()
    _render_advisor_settings()
    if flags.on("directory"):   # your listing in Find a guide (views/directory.py)
        st.divider()
        _render_directory_listing()
    st.caption(f":material/mail: Questions about using Northwend in your practice: "
               f"**{disclosures.CONTACT}**")


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
    """Each client who needs a look this week, once, with all their reasons
    (reviews due first, then coming due, then the rest), each with Open."""
    if not summary["any"]:
        st.markdown(":material/check_circle: Nothing due this week - every review is up "
                    "to date and no client needs a look.")
        return
    items = summary["clients"]
    for r in items[:WEEK_LIST_MAX]:
        with st.container(horizontal=True, vertical_alignment="center"):
            # plain text (st.html), so a client listed by email isn't a mailto link
            st.html(f"<b>{html.escape(r['name'])}</b> - {html.escape(', '.join(r['why']))}",
                    width="stretch")
            st.button("Open", key=f"wk_{where}_{r['user_id']}", type="tertiary",
                      on_click=_open_from_summary, args=(r["user_id"],),
                      help=f"Open {r['name']}'s portfolio")
    if len(items) > WEEK_LIST_MAX:
        st.caption(f"and {len(items) - WEEK_LIST_MAX} more on Your clients."
                   if where != "clients" else
                   f"and {len(items) - WEEK_LIST_MAX} more - they're first in the list below.")


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
                            f"{len(_summary['others'])} other client"
                            f"{'s' if len(_summary['others']) != 1 else ''} to look at.")
                _render_week_summary(_summary, where="notice")
                with st.container(horizontal=True):
                    st.button("Your clients", key="week_clients", type="primary",
                              on_click=lambda: (_week_seen(), _go("Clients")))
                    st.button("Got it", key="week_ok", type="tertiary", on_click=_week_seen,
                              help="Hide this until next week")
