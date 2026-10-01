# Part of dashboard.py, which runs this file with _view("assistant") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Ask Northwend: the AI guide's chat page.
# ruff: noqa: F821

def _render_assistant(contexts, cash_by_account):
    import advisor

    if st.session_state.pop("profile_toast", False):
        st.toast("Profile updated from the conversation.")
    api_key = _anthropic_key()
    if not api_key:
        st.info(f"{GUIDE} needs an `ANTHROPIC_API_KEY` - add it to `.env` locally, or to "
                "Settings → Secrets on Streamlit Cloud.")
        return

    conn = connect(DB)
    try:
        profile = advisor.get_profile(conn, USER_ID)
        memory = advisor.get_memory(conn, USER_ID)
    finally:
        conn.close()

    missing = advisor.missing_fields(profile)
    display = st.session_state.setdefault("chat_display", [])
    history = st.session_state.setdefault("chat_api", [])
    n_required = len(advisor.REQUIRED_PROFILE_FIELDS)
    with st.expander(f"Your investing profile ({n_required - len(missing)}/{n_required} key "
                     "questions answered)", expanded=bool(missing) and not display):
        _render_profile_form(advisor, profile)
        st.caption(f"{GUIDE} also fills this in from what you tell it in the chat, and "
                   "keeps short notes of its own so the next conversation picks up where this "
                   "one left off.")

    st.caption(f"Educational information only - not financial advice. {GUIDE} is not a "
               "licensed financial advisor; do your own research before making any investment "
               "decision.")

    _render_plan_export(api_key, profile, memory, contexts, cash_by_account, display)
    # new messages are written into this box too, so they land above the input
    chat_box = st.container()
    with chat_box:
        if not display:
            with st.chat_message("assistant", avatar=SAGE_AVATAR):
                st.markdown(f"Hi, I'm **{GUIDE}**, your guide. Ask me anything "
                            "about investing or your portfolio - what a fund is, whether your mix "
                            "fits your goal, what to look at next. I'll explain in plain "
                            "language, and I won't tell you what to buy.")
        for msg in display:
            with st.chat_message(msg["role"], avatar=_avatar(msg["role"])):
                st.markdown(msg["text"])

    prompt = None
    if not display:
        cols = st.columns(len(QUICK_STARTS))
        for col, (label, text) in zip(cols, QUICK_STARTS.items()):
            if col.button(label, width="stretch", key=f"quick_{label}"):
                prompt = text

    n_sent = sum(1 for m in display if m["role"] == "user")
    quota = _ai_status("chat")  # this month's allowance (ai_usage.py)
    at_limit = n_sent >= CHAT_MESSAGE_LIMIT or not quota["ok"]
    # Inside a container the input sits inline under the chat instead of pinned to
    # the bottom of the screen. Pinned, Streamlit also keeps the page stuck to the
    # bottom, and on phones scrolling up (which resizes the browser's address bar)
    # snapped it straight back down.
    with st.container():
        typed = st.chat_input(f"Ask {GUIDE} about investing or your portfolio...",
                              disabled=at_limit)
    # a question handed over from a Get started step
    prompt = typed or prompt or st.session_state.pop("coach_prompt", None)

    if prompt and not at_limit:
        import anthropic

        _ai_record("chat")
        if quota["left"] is not None:
            quota["left"] -= 1
        display.append({"role": "user", "text": prompt})
        history.append({"role": "user", "content": prompt})
        with chat_box, st.chat_message("user"):
            st.markdown(prompt)

        system = advisor.system_prompt(profile, advisor.portfolio_summary(contexts, cash_by_account, CLASS_SPLITS),
                                       memory)
        updated = []

        def on_update(fields):
            c = connect(DB)
            try:
                advisor.save_profile(c, USER_ID, fields)
            finally:
                c.close()
            updated.append(fields)

        def on_memory(text):
            c = connect(DB)
            try:
                advisor.save_memory(c, USER_ID, text)
            finally:
                c.close()

        with chat_box, st.chat_message("assistant", avatar=SAGE_AVATAR):
            try:
                reply = st.write_stream(advisor.stream_reply(
                    anthropic.Anthropic(api_key=api_key), history, system, on_update,
                    on_memory))
            except anthropic.AuthenticationError:
                reply = "The ANTHROPIC_API_KEY was rejected - check that it's correct."
                st.error(reply)
            except anthropic.RateLimitError:
                reply = f"{GUIDE} is busy right now - wait a minute and try again."
                st.error(reply)
            except (anthropic.APIConnectionError, anthropic.APIStatusError) as exc:
                reply = f"Couldn't reach {GUIDE}: {exc}"
                st.error(reply)
        display.append({"role": "assistant", "text": reply if isinstance(reply, str) else "".join(reply)})
        if updated:
            # rerun so the profile form shows the new values; the toast is
            # carried across the rerun, since one fired right before it is lost
            st.session_state["profile_toast"] = True
            st.rerun()

    if not quota["ok"]:
        st.info(ai_usage.used_up_text(quota, "chat"))
    elif at_limit:
        st.info(f"This conversation hit the {CHAT_MESSAGE_LIMIT}-message limit. Start a new one "
                "to keep going.")
    if display:
        def _new_conversation():
            st.session_state["chat_display"] = []
            st.session_state["chat_api"] = []
        st.button("New conversation", on_click=_new_conversation)
    st.caption(f"Your holdings are shared with {GUIDE} as percentages only - no dollar "
               "amounts, share counts, or account names."
               + (f" {ai_usage.left_text(quota, 'chat')}." if quota["ok"] and quota["limit"] else ""))
