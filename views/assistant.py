# Part of dashboard.py, which runs this file with _view("assistant") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Ask Northwend: the AI guide's chat page. Calm by default (ROADMAP S6): the
# hello, a few suggested questions and the chat, with the investing profile
# and the printable plan in a window; the full page (both open above the chat)
# for advisors and for Show everything (_show_everything).
# ruff: noqa: F821

ASSIST_PROFILE_NOTE = (f"When you tell {GUIDE} something that belongs here, it offers to save "
                       "it - nothing changes until you tap Save. It also keeps short notes so "
                       "the next conversation picks up where this one left off; you can read "
                       "and delete them on your Account page.")
ASSIST_DISCLAIMER = (f"Educational information only - not financial advice. {GUIDE} is an AI, "
                     "not a licensed financial advisor, and can be wrong; it won't recommend "
                     "what to buy or sell. Any projection is hypothetical. Do your own research "
                     "or talk to a licensed professional before making any investment decision.")


def _assist_profile():
    import advisor
    c = connect(DB)
    try:
        return advisor.get_profile_and_memory(c, USER_ID)
    finally:
        c.close()


@st.dialog("Your investing profile", width="large", on_dismiss=_dialog_closed)
def _assist_profile_window():
    import advisor
    st.caption(ASSIST_PROFILE_NOTE)
    _render_profile_form(advisor, _assist_profile()[0])   # Save closes the window


@st.dialog("Printable plan (PDF)", width="large", on_dismiss=_dialog_closed)
def _assist_plan_window(api_key, contexts, cash_by_account):
    profile, memory = _assist_profile()
    _render_plan_export(api_key, profile, memory, contexts, cash_by_account,
                        st.session_state.get("chat_display", []), in_window=True)


def _chat_keeps_notes():
    """The guide reads and keeps its notes only in the person's own account -
    never an advisor's conversation in a client's (AI_PLAN section 6)."""
    import ai_gateway
    return ai_gateway.may_keep_memory(LOGIN_ID, USER_ID)


def _chat_card(contexts, cash_by_account, profile, memory):
    """This conversation's ContextCard, rendered (context_card.py): made at
    its first message, then the same text every turn - live prices moving
    don't change it, so the cached prompt keeps working."""
    import context_card

    def make():
        return context_card.build(
            profile=profile, contexts=contexts, cash_by_account=cash_by_account,
            splits=CLASS_SPLITS, targets=load_alloc_targets(), band=load_drift_threshold(),
            stage=context_card.stage_of(has_real_holdings=HAS_REAL_HOLDINGS,
                                        experience=profile.get("experience"),
                                        managed=CLIENT_MODE),
            memory=memory if _chat_keeps_notes() else "",
            scope=context_card.SELF if _chat_keeps_notes() else context_card.ADVISOR_FULL)
    return context_card.for_conversation(st.session_state, USER_ID, make)[0]


def _new_conversation():
    import context_card
    st.session_state["chat_display"] = []
    st.session_state["chat_api"] = []
    st.session_state.pop("chat_suggest", None)
    context_card.forget(st.session_state)


def _chat_save_suggestion():
    """The person tapped Save under a profile suggestion: only now is it
    written (the write rule - the model's tool only suggests)."""
    import advisor
    sug = st.session_state.pop("chat_suggest", None)
    if not sug or sug.get("for") != USER_ID:
        return
    # checked when it was suggested (advisor.validate_profile_input); never notes
    fields = {k: v for k, v in sug["fields"].items() if k in advisor.TOOL_PROFILE_FIELDS}
    if not fields:
        return
    c = connect(DB)
    try:
        advisor.save_profile(c, USER_ID, fields)
    finally:
        c.close()
    st.session_state["profile_toast"] = True


def _chat_skip_suggestion():
    st.session_state.pop("chat_suggest", None)


def _render_assistant(contexts, cash_by_account):
    import advisor

    if st.session_state.pop("profile_toast", False):
        st.toast("Saved to the profile.")
    api_key = _anthropic_key()
    if not api_key:
        # the set-up detail (no ANTHROPIC_API_KEY) is on Admin > System
        st.info(f"Ask {GUIDE} isn't available on this site right now.")
        return

    profile, memory = _assist_profile()
    if (st.session_state.get("chat_card") or {}).get("for", USER_ID) != USER_ID:
        _new_conversation()   # another account now: its own conversation and card

    # the count covers the readiness questions too (debt, employer match), so
    # it never says every question is answered while some are still open
    missing = [f for f in advisor.KEY_PROFILE_FIELDS if profile.get(f) in (None, "")]
    display = st.session_state.setdefault("chat_display", [])
    history = st.session_state.setdefault("chat_api", [])
    n_required = len(advisor.KEY_PROFILE_FIELDS)
    answered = f"{n_required - len(missing)}/{n_required}"
    full = _show_everything()
    if full:
        with st.expander(f"Your investing profile ({answered} key questions answered)",
                         expanded=bool(missing) and not display):
            _render_profile_form(advisor, profile)
            st.caption(ASSIST_PROFILE_NOTE)

        st.caption(ASSIST_DISCLAIMER)

        _render_plan_export(api_key, profile, memory, contexts, cash_by_account, display)
    elif missing and not display:
        # the calm view's one next step: the questions that make answers fit
        if _next_step_card("assistant", "Answer a few quick questions about you "
                           f"({n_required - len(missing)} of {n_required} done), so "
                           f"{GUIDE}'s answers fit your timeline and comfort with "
                           "ups and downs.", ("Answer the questions", None, ())):
            _open_window(_assist_profile_window)
    # new messages are written into this box too, so they land above the input
    chat_box = st.container()
    with chat_box:
        if not display:
            with st.chat_message("assistant", avatar=SAGE_AVATAR):
                st.markdown(f"Hi, I'm **{GUIDE}**, your AI guide. Ask me anything "
                            "about investing or your portfolio - what a fund is, how your mix "
                            "compares with your goal, what people usually look at next. I'll "
                            "explain in plain language, and I won't tell you what to buy or "
                            "sell.")
        for msg in display:
            with st.chat_message(msg["role"], avatar=_avatar(msg["role"])):
                st.markdown(msg["text"])

    prompt = None
    if not display:
        if not full:
            st.caption("Not sure where to start? Try one of these:")
        starts = QUICK_STARTS if contexts else QUICK_STARTS_NEW   # nothing to review yet
        cols = st.columns(len(starts))
        for col, (label, text) in zip(cols, starts.items()):
            if col.button(label, width="stretch", key=f"quick_{label}"):
                prompt = text

    n_sent = sum(1 for m in display if m["role"] == "user")
    # this month's allowance (ai_usage.py); this page is drawn in the full run
    # (and the app-wide ceiling, ai_spend.py: a conversation under way may
    # finish after new ones close)
    quota = _ai_status("chat", full_run=True, conversation_open=n_sent > 0)
    at_limit = n_sent >= CHAT_MESSAGE_LIMIT or not quota["ok"]
    # Inside a container the input sits inline under the chat instead of pinned to
    # the bottom of the screen. Pinned, Streamlit also keeps the page stuck to the
    # bottom, and on phones scrolling up (which resizes the browser's address bar)
    # snapped it straight back down.
    with st.container():
        typed = st.chat_input(f"Ask {GUIDE} about investing or your portfolio...",
                              disabled=at_limit, max_chars=CHAT_MAX_CHARS)
    typed = (typed or "")[:CHAT_MAX_CHARS] or None   # the box's limit, checked here too
    # a question handed over from a Get started step
    prompt = typed or prompt or st.session_state.pop("coach_prompt", None)

    if prompt and not at_limit:
        import anthropic

        display.append({"role": "user", "text": prompt})
        history.append({"role": "user", "content": prompt})
        n_history = len(history)
        with chat_box, st.chat_message("user"):
            st.markdown(prompt)

        # the person's card, made at the conversation's first message and kept
        # (context_card.py); the rules and tools are the gateway's shared block
        card = _chat_card(contexts, cash_by_account, profile, memory)
        suggested, kept = [], []   # the write rule: nothing is saved from inside the answer

        with chat_box, st.chat_message("assistant", avatar=SAGE_AVATAR):
            try:
                reply = st.write_stream(advisor.stream_reply(
                    anthropic.Anthropic(api_key=api_key), history, card, suggested.append,
                    kept.append if _chat_keeps_notes() else None, user_id=LOGIN_ID,
                    **ai_spend.chat_settings(quota["level"])))
            except anthropic.AnthropicError as exc:
                # one calm sentence, never the error's text (_ai_failed); the
                # question leaves the history so the next try asks it afresh,
                # and nothing is counted against the month's allowance
                reply = _ai_failed(exc, "chat")
                del history[n_history - 1:]
                st.warning(reply)
                suggested, kept = [], []
            else:
                _ai_record("chat")  # counted once it has answered
                if quota["left"] is not None:
                    quota["left"] = max(0, quota["left"] - 1)
        display.append({"role": "assistant", "text": reply if isinstance(reply, str) else "".join(reply)})
        if kept:
            # the guide's notes - typed and scrubbed (advisor.MemoryNote) - kept
            # on the person's behalf by the gateway, only in their own account
            import ai_gateway
            c = connect(DB)
            try:
                ai_gateway.save_memory(c, login_id=LOGIN_ID, account_id=USER_ID, notes=kept[-1])
            finally:
                c.close()
        if suggested:
            # a profile suggestion: a button under the answer, saved only on a tap
            merged = {}
            for fields in suggested:
                merged.update(fields)
            st.session_state["chat_suggest"] = {"for": USER_ID, "fields": merged}

    _sug = st.session_state.get("chat_suggest")
    if _sug and _sug.get("for") == USER_ID and _sug.get("fields"):
        with st.container(border=True, horizontal=True, vertical_alignment="center",
                          key="chat_suggest_box"):
            st.caption(f"Save to {'your' if USER_ID == LOGIN_ID else 'their'} profile? "
                       + advisor.describe_answers(_sug["fields"]), width="stretch")
            st.button("Save", key="chat_suggest_save", type="primary",
                      on_click=_chat_save_suggestion, icon=":material/check:")
            st.button("Not now", key="chat_suggest_skip", type="tertiary",
                      on_click=_chat_skip_suggestion)

    if not quota["ok"]:
        st.info(ai_usage.used_up_text(quota, "chat", GUIDE))
    elif at_limit:
        st.info(f"This conversation hit the {CHAT_MESSAGE_LIMIT}-message limit. Start a new one "
                "to keep going.")
    if full:
        if display:
            st.button("New conversation", on_click=_new_conversation)
    else:
        # the calm view: the profile and the printable plan open in a window
        with st.container(horizontal=True, vertical_alignment="center"):
            if display:
                st.button("New conversation", on_click=_new_conversation)
            if st.button(f"Your investing profile ({answered})", key="assist_profile_open",
                         type="tertiary", icon=":material/person:"):
                _open_window(_assist_profile_window)
            if st.button("Printable plan (PDF)", key="assist_plan_open", type="tertiary",
                         icon=":material/picture_as_pdf:"):
                _open_window(_assist_plan_window, api_key, contexts, cash_by_account)
        st.caption(ASSIST_DISCLAIMER)
    st.caption(f"Your holdings are shared with {GUIDE} as percentages only - no dollar "
               "amounts, share counts, or account names."
               + (f" {ai_usage.left_text(quota, 'chat')}." if quota["ok"] and quota["limit"] else ""))
