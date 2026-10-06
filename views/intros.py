# Part of dashboard.py, which runs this file with _view("intros") at the
# point where this code would sit, in dashboard.py's own namespace: the names
# here (st, DB, LOGIN_ID, MY_NAME, the helpers...) are dashboard.py's, and what
# this defines is visible there afterwards. See _view() in dashboard.py.
#
# Introductions (intros.py; flag `intros`, gate L2 - this view isn't run at
# all while either is off; it lives inside Find a guide, so `directory` too):
# - the person's side, on Find a guide (views/directory.py calls it when
#   flags.on("intros")): "Request an introduction" opens a short form - a
#   name, a message and the figure-free outline they tick - and "Your
#   introductions" lists what they sent, the advisor's answer, and, after an
#   answer, "Share my full account": two separate steps (what sharing means,
#   then a tick and confirm) before intros.share_account writes the consent
#   grant and the link. Plain session-state steps, not a dialog, so AppTest
#   can drive them.
# - the advisor's side, "Introductions" on Your clients (views/clients.py):
#   only intros sent to them; reply in text, share their scheduling link, or
#   decline. No counts of anything.
# Emails say only that something is waiting (mailer.intro_received /
# intro_answered), at most one of a kind an hour (auth.notice_ok).
# ruff: noqa: F821

import intros

_INTRO_STATUS = {
    "sent": "Waiting for their answer",
    "replied": "They answered",
    "declined": "They're not able to take this further",
    "withdrawn": "You withdrew it",
    "shared": "You're sharing your full account with them",
}
_INTRO_STATUS_ADVISOR = {
    "declined": "You declined", "withdrawn": "They withdrew it",
    "shared": "They shared their full account with you - they're on your client list",
}


def _intro_md(text):
    """Plain text someone typed, shown as typed inside st.markdown."""
    return _md_name(text).replace("\n", "  \n")


def _intro_day(iso):
    try:
        d = datetime.strptime((iso or "")[:10], "%Y-%m-%d")
    except ValueError:
        return ""
    return f"{d:%b} {d.day}, {d.year}"


def _intro_lines_md(lines):
    return "  \n".join(f"**{head}:** {_intro_md(line)}" for _, head, line in lines)


def _intro_draft_note():
    if STAGING and intros.COPY_STATUS == "DRAFT":
        st.caption("Draft wording - for review under legal gate L2.")


# ---- the person's side (Find a guide) ----------------------------------------- #
def _intro_default_name():
    name = MY_NAME or ""
    return "" if "@" in name else name[:intros.LIMITS["name"]]


def _intro_send(advisor_id):
    g = st.session_state.get
    parts = [p for p in intros.PARTS if g(f"intro_part_{p}")]
    c = connect(DB)
    try:
        found = intros.outline(c, LOGIN_ID)
        res = intros.send(c, LOGIN_ID, advisor_id, g(f"intro_msg_{advisor_id}") or "",
                          name=g("intro_name") or "", outline=intros.pick(found, parts))
        email = None
        if res["ok"]:
            to = auth.email_status(c, advisor_id)
            email = (to["email"] if to["confirmed"] and auth.notice_ok(c, "intro", to["email"])
                     else None)
    finally:
        c.close()
    if not res["ok"]:
        st.session_state["intro_flash"] = ("error", res["error"], advisor_id)
        return
    if email:
        mailer.intro_received(email, f"{_app_address()}?page=your-clients")
    st.session_state.pop("intro_to", None)
    st.session_state.pop(f"intro_msg_{advisor_id}", None)
    st.session_state["intro_flash"] = ("success", intros.SENT_NOTE, None)


def _intro_close_form():
    st.session_state.pop("intro_to", None)


def _intro_compose(p):
    """The form inside a listing card: a name, a message, and what of the
    outline to send - each part shown as it would be sent."""
    uid = p["user_id"]
    flash = st.session_state.get("intro_flash")
    if flash and flash[2] == uid:
        st.session_state.pop("intro_flash", None)
        st.error(flash[1])
    c = connect(DB)
    try:
        problem = intros.can_send(c, LOGIN_ID, uid)
        found = intros.outline(c, LOGIN_ID) if problem is None else {}
    finally:
        c.close()
    if problem:
        st.info(problem, icon=":material/info:")
        return
    st.session_state.setdefault("intro_name", _intro_default_name())
    with st.form(f"intro_form_{uid}", border=True):
        st.markdown(f"**Introduce yourself to {_intro_md(p['display_name'])}**")
        st.caption(intros.FORM_INTRO)
        st.text_input("Your name, as they'll see it", key="intro_name",
                      max_chars=intros.LIMITS["name"])
        st.text_area("Your message", key=f"intro_msg_{uid}",
                     max_chars=intros.LIMITS["message"],
                     placeholder="A few words about what you'd like help with.")
        lines = intros.outline_lines(found)
        if lines:
            st.markdown("**You can also send** (untick anything you'd rather keep):")
            for part, head, line in lines:
                st.session_state.setdefault(f"intro_part_{part}", True)
                st.checkbox(f"{intros.PART_LABELS[part]}: {line}", key=f"intro_part_{part}")
        st.caption(intros.FORM_PRIVACY)
        _intro_draft_note()
        st.form_submit_button("Send introduction", type="primary", on_click=_intro_send,
                              args=(uid,))
    st.button("Cancel", key=f"intro_cancel_{uid}", type="tertiary", on_click=_intro_close_form)


def _intro_withdraw(intro_id):
    c = connect(DB)
    try:
        res = intros.withdraw(c, LOGIN_ID, intro_id)
    finally:
        c.close()
    st.session_state["intro_flash"] = (("success", "Withdrawn. The advisor won't see it as "
                                        "waiting any more.", None) if res["ok"]
                                       else ("error", res["error"], None))


def _intro_share_step(intro_id, step):
    """Move through the two steps; step 0 closes them."""
    if step:
        st.session_state["intro_share"] = (intro_id, step)
    else:
        st.session_state.pop("intro_share", None)
    st.session_state.pop("intro_share_ok", None)


def _intro_share_go(intro_id):
    """Step 2 confirmed: the consent grant with the exact words shown, then
    the link - one transaction (intros.share_account)."""
    c = connect(DB)
    try:
        res = intros.share_account(c, LOGIN_ID, intro_id,
                                   st.session_state.get("_intro_share_text") or "",
                                   confirmed=bool(st.session_state.get("intro_share_ok")))
        who = intros.advisor_names(c, res["advisor_id"]) if res["ok"] else None
    finally:
        c.close()
    if not res["ok"]:
        st.session_state["intro_flash"] = ("error", res["error"], None)
        return
    st.session_state.pop("intro_share", None)
    st.session_state.pop("intro_share_ok", None)
    st.session_state["page"] = "Dashboard"
    st.session_state["import_flash"] = (
        f"You're now sharing your account with {who['name']}. You can stop at any time "
        "from the Your advisor page, and you keep everything.")
    st.toast(f"You're now sharing your account with {who['name']}.")


def _intro_share_steps(r):
    """The two steps, one after the other, inside the intro's card."""
    step = st.session_state.get("intro_share")
    if not step or step[0] != r["id"]:
        return
    lines = intros.sharing_lines(r["advisor"], r["firm"])
    with st.container(border=True, key=f"intro_share_box_{r['id']}"):
        st.markdown(f"**Step {step[1]} of 2 - {intros.SHARE_TITLE}**")
        st.markdown("\n".join(f"- {_intro_md(line)}" for line in lines))
        _intro_draft_note()
        if step[1] == 1:
            with st.container(horizontal=True, gap="small"):
                st.button("Continue", key="intro_share_next", type="primary",
                          on_click=_intro_share_step, args=(r["id"], 2))
                st.button("Not now", key="intro_share_cancel", type="tertiary",
                          on_click=_intro_share_step, args=(r["id"], 0))
            return
        # step 2: exactly these words go with the consent record (consent.py)
        st.session_state["_intro_share_text"] = intros.sharing_text(r["advisor"], r["firm"])
        st.checkbox(intros.CONFIRM_LINE.format(name=r["advisor"]), key="intro_share_ok")
        with st.container(horizontal=True, gap="small"):
            st.button("Share my account", key="intro_share_go", type="primary",
                      on_click=_intro_share_go, args=(r["id"],))
            st.button("Not now", key="intro_share_cancel", type="tertiary",
                      on_click=_intro_share_step, args=(r["id"], 0))


def _intro_person_card(r):
    with st.container(border=True, key=f"intro_card_{r['id']}"):
        firm = f", {_intro_md(r['firm'])}" if r["firm"] else ""
        st.markdown(f"**To {_intro_md(r['advisor'])}**{firm}")
        st.caption(f"Sent {_intro_day(r['created_at'])} · {_INTRO_STATUS[r['status']]}")
        with st.expander("What you sent"):
            st.markdown(_intro_md(r["message"]))
            if r["lines"]:
                st.markdown(_intro_lines_md(r["lines"]))
        if r["reply"]:
            st.markdown(f"**Their answer** ({_intro_day(r['replied_at'])})  \n"
                        + _intro_md(r["reply"]))
        if r["reply"] or r["scheduling_url"]:
            # whatever an advisor writes says whose advice it is (standing_line.py)
            st.caption(standing_line.text(r["advisor"], r["firm"]))
        if r["scheduling_url"] and r["status"] in intros.OPEN:
            st.link_button("Book a time on their scheduling page", r["scheduling_url"],
                           icon=":material/open_in_new:")
        if r["status"] in intros.OPEN:
            with st.container(horizontal=True, gap="small"):
                if r["status"] == "replied":
                    st.button(f"Share my full account with {r['advisor']}",
                              key=f"intro_share_{r['id']}",
                              on_click=_intro_share_step, args=(r["id"], 1))
                st.button("Withdraw", key=f"intro_withdraw_{r['id']}", type="tertiary",
                          on_click=_intro_withdraw, args=(r["id"],))
        _intro_share_steps(r)


def _render_my_intros():
    """Your introductions, at the top of Find a guide (when there are any)."""
    flash = st.session_state.get("intro_flash")
    if flash and flash[2] is None:
        st.session_state.pop("intro_flash", None)
        (st.success if flash[0] == "success" else st.error)(flash[1])
    c = connect(DB)
    try:
        mine = intros.for_person(c, LOGIN_ID)
    finally:
        c.close()
    if not mine:
        return
    st.subheader("Your introductions", anchor=False)
    st.caption(intros.PERSON_LIST_NOTE)
    for r in mine:
        _intro_person_card(r)


# ---- the advisor's side (Your clients) ------------------------------------------ #
def _intro_answer_email(c, intro_id):
    """Tell the person there's an answer - only that (mailer.intro_answered)."""
    email = intros.answer_email(c, LOGIN_ID, intro_id)
    if not (email and auth.notice_ok(c, "intro_answer", email)):
        return None
    who = intros.advisor_names(c, LOGIN_ID)
    return (email, who, standing_line.text(who["name"], who["firm"]))


def _intro_send_answer_email(note):
    if not note:
        return
    email, who, standing = note
    from_name = f"{who['name']}, {who['firm']}" if who["firm"] else who["name"]
    mailer.intro_answered(email, f"{_app_address()}?page=find-a-guide", who["name"],
                          standing=standing, from_name=from_name)


def _intro_reply(intro_id):
    g = st.session_state.get
    c = connect(DB)
    try:
        res = intros.reply(c, LOGIN_ID, intro_id, g(f"intro_reply_{intro_id}") or "",
                           share_link=bool(g(f"intro_link_{intro_id}")))
        note = _intro_answer_email(c, intro_id) if res["ok"] else None
    finally:
        c.close()
    if res["ok"]:
        _intro_send_answer_email(note)
    st.session_state["intro_adv_flash"] = (("success", "Sent. They'll see your answer in "
                                            "Northwend.") if res["ok"]
                                           else ("error", res["error"]))


def _intro_share_link(intro_id):
    c = connect(DB)
    try:
        res = intros.share_link(c, LOGIN_ID, intro_id)
    finally:
        c.close()
    st.session_state["intro_adv_flash"] = (("success", "Your scheduling link is shared.")
                                           if res["ok"] else ("error", res["error"]))


def _intro_decline(intro_id):
    c = connect(DB)
    try:
        res = intros.decline(c, LOGIN_ID, intro_id,
                             st.session_state.get(f"intro_decline_note_{intro_id}") or "")
        note = _intro_answer_email(c, intro_id) if res["ok"] else None
    finally:
        c.close()
    if res["ok"]:
        _intro_send_answer_email(note)
    st.session_state["intro_adv_flash"] = (("success", "Declined. They'll see that you're not "
                                            "able to take it further.") if res["ok"]
                                           else ("error", res["error"]))


def _intro_advisor_card(r, url):
    rid = r["id"]
    with st.container(border=True, key=f"intro_adv_card_{rid}"):
        st.markdown(f"**{_intro_md(r['person_name'])}**")
        st.caption(f"Sent {_intro_day(r['created_at'])}")
        st.markdown(_intro_md(r["message"]))
        if r["lines"]:
            st.markdown(_intro_lines_md(r["lines"]))
        if r["status"] == "sent":
            st.text_area("Your reply", key=f"intro_reply_{rid}",
                         max_chars=intros.LIMITS["reply"],
                         help="Plain text - no links or email addresses. They read it in "
                              "Northwend.")
            st.checkbox("Share my scheduling link", key=f"intro_link_{rid}", disabled=not url,
                        help=("The link on your directory listing." if url else
                              "Add a scheduling link to your directory listing to share it."))
            st.button("Send reply", key=f"intro_send_reply_{rid}", type="primary",
                      on_click=_intro_reply, args=(rid,))
        else:
            if r["reply"]:
                st.markdown(f"**Your answer** ({_intro_day(r['replied_at'])})  \n"
                            + _intro_md(r["reply"]))
            if r["link_shared"]:
                st.caption(":material/event: Your scheduling link is shared with them.")
            elif url:
                st.button("Share my scheduling link", key=f"intro_share_link_{rid}",
                          on_click=_intro_share_link, args=(rid,))
        with st.popover("Decline", type="tertiary"):
            st.text_input("A short note (optional)", key=f"intro_decline_note_{rid}",
                          max_chars=intros.LIMITS["reply"])
            st.button("Decline this introduction", key=f"intro_decline_{rid}",
                      on_click=_intro_decline, args=(rid,))


def _render_intros_advisor():
    """Introductions on Your clients: only those sent to this advisor."""
    st.subheader("Introductions", anchor=False)
    st.caption(intros.ADVISOR_INTRO)
    _intro_draft_note()
    flash = st.session_state.pop("intro_adv_flash", None)
    if flash:
        (st.success if flash[0] == "success" else st.error)(flash[1])
    c = connect(DB)
    try:
        rows = intros.for_advisor(c, LOGIN_ID)
        url = intros.scheduling_url(c, LOGIN_ID)
    finally:
        c.close()
    waiting = [r for r in rows if r["status"] in intros.OPEN]
    if not waiting:
        st.caption("No introductions waiting.")
    for r in waiting:
        _intro_advisor_card(r, url)
    earlier = [r for r in rows if r["status"] not in intros.OPEN]
    if earlier:
        with st.expander("Earlier introductions"):
            for r in earlier:
                st.markdown(f"**{_intro_md(r['person_name'])}** · sent "
                            f"{_intro_day(r['created_at'])} · "
                            f"{_INTRO_STATUS_ADVISOR[r['status']]}")
