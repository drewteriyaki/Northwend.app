# Part of dashboard.py, which runs this file with _view("drafts") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Advisor drafts (AI_PLAN section 9 row 11, advisor_drafts.py; flag
# advisor_drafts, gate L1a): "Draft with Northwend" beside the editable
# box for a proposal's words (views/proposals.py), a message to clients
# (views/clients.py) and a progress report's message (views/reports.py). The
# draft only fills the box; sending is the advisor's own button, as before.
# ruff: noqa: F821

import advisor_drafts

DRAFT_FEATURE = f"Drafting with {GUIDE}"


def _draft_card():
    """The client's ContextCard in scope ADVISOR_FULL, rendered: percentages,
    no notes, no amounts (context_card.py). Made when the advisor presses
    Draft, from that page's holdings; None without a client."""
    import advisor
    import context_card

    if not ON_CLIENT:
        return None
    c = connect(DB)
    try:
        profile = advisor.get_profile(c, USER_ID)
    finally:
        c.close()
    return context_card.build(
        profile=profile, contexts=globals().get("contexts") or [],
        cash_by_account=globals().get("cash_by_account") or {}, splits=CLASS_SPLITS,
        targets=load_alloc_targets(), band=load_drift_threshold(),
        scope=context_card.ADVISOR_FULL).render()


def _draft_write(kind, box_key, make_inputs):
    """Draft with Northwend: a first draft into the box `box_key` - nothing
    sent, saved or shared. Counted against the advisor's own allowance."""
    import anthropic

    msg_key = f"draft_msg_{kind}"
    if not _seat_ok():   # a paid seat that isn't active (views/billing.py)
        return
    key = _anthropic_key()
    quota = _ai_status("draft")
    if not key:
        st.session_state[msg_key] = ("info", f"{DRAFT_FEATURE} isn't available on this site - "
                                             "write your own in the box.")
        return
    if not quota["ok"]:
        st.session_state[msg_key] = ("info", ai_usage.used_up_text(quota, "draft", GUIDE))
        return
    try:
        text = advisor_drafts.draft(kind, client=anthropic.Anthropic(api_key=key),
                                    user_id=LOGIN_ID,
                                    points=st.session_state.get(f"draft_points_{kind}") or "",
                                    **make_inputs())
    except anthropic.AnthropicError as exc:
        st.session_state[msg_key] = ("warning", _ai_failed(exc, "draft", DRAFT_FEATURE))
        return
    _ai_record("draft")   # counted once it has answered
    if not text:
        st.session_state[msg_key] = ("info", advisor_drafts.NO_DRAFT)
        return
    st.session_state[box_key] = text
    st.session_state[f"draft_for_{box_key}"] = text   # what the label is about
    if kind == "message":   # a new text: Review and send again before it goes
        st.session_state["msg_confirm"] = False


def _render_draft_tools(kind, box_key, make_inputs, *, what="What to cover (optional)"):
    """Above an editable box: the advisor's points for the draft and the
    Draft with Northwend button; once a draft is in the box, its label (the
    advisor's view only). Nothing while the feature is off."""
    # (and not while a paid seat isn't active - views/billing.py: the AI
    # helpers are part of the seat; the box below still works)
    if not (flags.on("advisor_drafts") and IS_ADVISOR and SEAT_OPEN):
        return
    msg = st.session_state.pop(f"draft_msg_{kind}", None)
    if msg:
        getattr(st, msg[0])(msg[1])
    quota = _ai_status("draft")
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.text_input(what, key=f"draft_points_{kind}", max_chars=advisor_drafts.POINTS_MAX,
                      placeholder="A few words - the draft uses only these and the "
                                  "percentages")
        st.button(f":material/auto_awesome: Draft with {GUIDE}", key=f"draft_{kind}",
                  on_click=_draft_write, args=(kind, box_key, make_inputs),
                  disabled=not quota["ok"],
                  help="Writes a first draft into the box below for you to edit. Sends "
                       + ("this client's mix and holdings as percentages and " if kind != "message"
                          else "")
                       + "what you type here - never dollar amounts, names or your notes. "
                       "Nothing is sent to anyone until you press your own Send. "
                       + (ai_usage.left_text(quota, "draft") or ""))
    if quota.get("resting_why"):   # the month's AI use is high (ai_spend.py)
        st.caption(ai_usage.used_up_text(quota, "draft", GUIDE) + " Write your own below.")
    held = st.session_state.get(f"draft_for_{box_key}")
    if held and (st.session_state.get(box_key) or "").strip():
        st.caption(f":material/edit_note: {advisor_drafts.LABEL}")
