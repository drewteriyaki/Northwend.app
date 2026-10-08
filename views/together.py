# Part of dashboard.py, which runs this file with _view("together") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, connect, flags, USER_ID, LOGIN_ID, the helpers...) are
# dashboard.py's, and what this defines is visible there afterwards. See
# _view() in dashboard.py.
#
# Doing it together (together.py), flag together: a section on the Life page
# (views/life.py checks on("together")). Two people with their own accounts
# pair up with a one-time link and each sees three habit facts about the
# other - learning days this month, this month's walk done or not, wins
# earned - read only through together.for_partner. A nudge sends a fixed
# "Your walk is waiting" email. Only the login's own account: never an
# advisor, an admin, an advisor's client or an advisor in a client's account.
#
# A link (?together=<token>) is taken in dashboard.py once someone is signed
# in: only its hash is kept in this session ("together_hash") and Life opens,
# where this section asks them to say yes in the exact words recorded.
# ruff: noqa: F821

import together as tg


def _tg_own() -> bool:
    """Only the login's own account, and an individual's (also in a callback,
    a run later). together.py checks again in the database."""
    return (flags.on(tg.FLAG) and USER_ID == LOGIN_ID and not IS_MANAGED_CLIENT
            and not IS_ADMIN and not IS_ADVISOR)


def _tg_today():
    return datetime.now(timezone.utc).date()


# ---- callbacks ------------------------------------------------------------------ #
def _tg_invite():
    if not _tg_own() or not st.session_state.get("tg_agree"):
        return
    conn = connect(DB)
    try:
        if not rate_limits.allow(conn, LOGIN_ID, rate_limits.INVITE):
            st.session_state["tg_msg"] = rate_limits.CALM
            return
        token = tg.invite(conn, LOGIN_ID, by=LOGIN_ID)
    except PermissionError:
        st.session_state["tg_msg"] = tg.NOT_ALLOWED
        return
    except ValueError:
        st.session_state["tg_msg"] = tg.FULL
        return
    finally:
        conn.close()
    # in this session's memory only, until "Done" - never saved anywhere
    st.session_state["tg_new"] = tg.link(_app_address(), token)
    st.session_state["tg_agree"] = False


def _tg_done():
    st.session_state.pop("tg_new", None)


def _tg_cancel(invite_id):
    if not _tg_own():
        return
    conn = connect(DB)
    try:
        tg.cancel_invite(conn, LOGIN_ID, invite_id)
    finally:
        conn.close()
    st.session_state["tg_msg"] = "That invitation is cancelled. Its link no longer works."


def _tg_join(hashed, words):
    st.session_state.pop("together_hash", None)
    if not _tg_own():
        return
    conn = connect(DB)
    try:
        tg.accept(conn, hashed, LOGIN_ID, by=LOGIN_ID, text_shown=words)
        st.session_state["tg_msg"] = tg.JOINED
    except PermissionError:
        st.session_state["tg_msg"] = tg.NOT_ALLOWED
    except ValueError as e:
        st.session_state["tg_msg"] = str(e)
    finally:
        conn.close()


def _tg_decline():
    st.session_state.pop("together_hash", None)
    st.session_state["tg_msg"] = tg.DECLINED


def _tg_stop(partner_id):
    if USER_ID != LOGIN_ID:
        return
    conn = connect(DB)
    try:
        if tg.stop(conn, LOGIN_ID, partner_id, by=LOGIN_ID):
            st.session_state["tg_msg"] = tg.STOPPED
    finally:
        conn.close()


def _tg_nudge(partner_id):
    if not _tg_own():
        return
    conn = connect(DB)
    try:
        _sent, words = tg.nudge(conn, LOGIN_ID, partner_id, by=LOGIN_ID,
                                app_url=_app_address())
    except PermissionError:
        words = tg.NOT_ALLOWED
    finally:
        conn.close()
    if words:
        st.session_state["tg_msg"] = words


def _tg_nudges_switch():
    if not _tg_own():
        return
    p = _read_prefs()
    tg.set_nudges(p, bool(st.session_state.get("tg_nudges_on")))
    _write_prefs(p)


# ---- drawing ------------------------------------------------------------------- #
def _tg_card(title, line, facts, month):
    rows = ((tg.LEARN_LABEL, str(facts["learn_days"])),
            (tg.WALK_LABEL.format(month=month), tg.DONE if facts["walk_done"] else tg.NOT_YET),
            (tg.WINS_LABEL, str(facts["wins"])))
    st.html(f"<div class='pt-life-title'>{html.escape(title)}</div>"
            f"<div class='pt-life-small'>{html.escape(line)}</div>"
            + "".join("<div style='display:flex;justify-content:space-between;margin-top:.5rem'>"
                      f"<span>{html.escape(k)}</span><b>{html.escape(v)}</b></div>"
                      for k, v in rows))


def _tg_answer_invite(conn):
    """A link opened in this session: ask them to say yes, in the exact
    words recorded with their yes."""
    hashed = st.session_state.get("together_hash")
    if not hashed:
        return
    if not _tg_own():
        st.session_state.pop("together_hash", None)
        st.info(tg.NOT_ALLOWED, icon=":material/info:")
        return
    found = tg.find_invite(conn, hashed)
    if found is None or found["user_id"] == LOGIN_ID:
        st.session_state.pop("together_hash", None)
        st.info(tg.OWN_LINK if found else tg.LINK_GONE, icon=":material/info:")
        return
    words = tg.join_text(found["name"])
    with st.container(border=True, key="pt_tg_invited"):
        # (a first name is letters only: explain_share.first_name)
        st.markdown(f"**{_md_name(found['name'])} invited you to do it together**")
        st.markdown(words)
        with st.container(horizontal=True):
            st.button(tg.JOIN_YES, key="tg_yes", type="primary", on_click=_tg_join,
                      args=(hashed, words))
            st.button(tg.JOIN_NO, key="tg_no", on_click=_tg_decline)


def render_together_invite():
    """A link opened in this session, answered at the top of Life (views/life.py)."""
    if not flags.on(tg.FLAG) or not st.session_state.get("together_hash"):
        return
    conn = connect(DB)
    try:
        _tg_answer_invite(conn)
    finally:
        conn.close()


def render_together():
    """The Life page's "Doing it together" (the login's own only)."""
    if not _tg_own():
        return
    today = _tg_today()
    month = tg.month_name(today)
    conn = connect(DB)
    try:
        pairs = tg.partners(conn, LOGIN_ID)
        shown = []
        for pair in pairs:
            try:
                shown.append((pair, tg.for_partner(conn, LOGIN_ID, pair["partner_id"],
                                                   today=today)))
            except PermissionError:
                shown.append((pair, None))
        invites = tg.open_invites(conn, LOGIN_ID)
        room = tg.room(conn, LOGIN_ID)
        record = tg.history(conn, LOGIN_ID)
    finally:
        conn.close()
    mine = tg.facts_from(_read_prefs(), today)
    st.subheader(tg.TITLE, anchor="together")
    st.caption(tg.INTRO)
    msg = st.session_state.pop("tg_msg", None)
    if msg:
        st.caption(f":material/check: {msg}")

    cards = [(tg.YOU, MY_NAME if USER_ID == LOGIN_ID else "", mine, None)]
    for pair, facts in shown:
        since = datetime.strptime(pair["since"][:10], "%Y-%m-%d")
        cards.append((pair["name"], tg.PAIRED_SINCE.format(month=f"{since:%B}"), facts, pair))
    if len(cards) > 1:
        for start in range(0, len(cards), 2):
            cols = st.columns(2)
            for col, (title, line, facts, pair) in zip(cols, cards[start:start + 2]):
                with col, st.container(border=True, height="stretch",
                                       key=f"pt_tg_card_{pair['partner_id'] if pair else 0}"):
                    if facts is None:
                        st.markdown(f"**{_md_name(title)}**")
                        st.caption(tg.NOT_SHOWN)
                    else:
                        _tg_card(title, line, facts, month)
                    if pair:
                        st.button(tg.STOP, key=f"tg_stop_{pair['partner_id']}", type="tertiary",
                                  on_click=_tg_stop, args=(pair["partner_id"],))
        for pair, facts in shown:
            if facts is None or facts["walk_done"]:
                continue
            with st.container(border=True, horizontal=True, vertical_alignment="center",
                              key=f"pt_tg_nudge_{pair['partner_id']}"):
                with st.container():
                    st.markdown("**" + tg.NUDGE_TITLE.format(name=_md_name(pair["name"]),
                                                             month=month) + "**")
                    st.caption(tg.NUDGE_NOTE)
                st.button(tg.NUDGE_BUTTON, key=f"tg_nudge_{pair['partner_id']}",
                          on_click=_tg_nudge, args=(pair["partner_id"],), width="content")
    else:
        st.caption(tg.NONE_YET)
    st.caption(f":material/lock: {tg.WHAT_SHARED}")

    new = st.session_state.get("tg_new")
    if new:
        with st.container(border=True, key="pt_tg_new"):
            st.markdown("**Your invitation link**")
            st.code(new, language=None, wrap_lines=True)
            st.caption(tg.SHOWN_ONCE)
            st.button("Done", key="tg_done", type="tertiary", on_click=_tg_done)
    if room > 0:
        with st.expander(tg.MAKE_LINK, icon=":material/link:"):
            st.markdown(tg.INVITE_CONSENT)
            st.checkbox(tg.INVITE_AGREE, key="tg_agree", value=False)
            st.button(tg.MAKE_LINK, key="tg_make", type="primary",
                      disabled=not st.session_state.get("tg_agree"), on_click=_tg_invite)
    else:
        st.caption(tg.FULL)
    if invites:
        st.markdown("**Invitations not answered yet**")
        for row in invites:
            with st.container(horizontal=True, vertical_alignment="center",
                              key=f"pt_tg_inv_{row['id']}"):
                st.caption(f"Made {_fmt_date(row['created_at'])} · works until "
                           f"{_fmt_date(row['expires_at'])}", width="stretch")
                st.button("Cancel", key=f"tg_cancel_{row['id']}", type="tertiary",
                          on_click=_tg_cancel, args=(row["id"],))
    if pairs or record:
        st.toggle(tg.NUDGE_SWITCH, key="tg_nudges_on", value=tg.nudges_on(_read_prefs()),
                  on_change=_tg_nudges_switch)
    if record:
        with st.expander("Your sharing record"):
            for r in record:
                verb = "You agreed to share with" if r["kind"] == "grant" else "Sharing ended with"
                st.markdown(f"**{_fmt_date(r['at'])}** · {verb} {_md_name(r['name'])}")
                if r["text_shown"]:
                    st.caption(f"What you saw: {_md_name(r['text_shown'])}")
            st.caption("Kept for 7 years after sharing ends, even if an account is deleted. It "
                       "holds who, when and these words - never figures.")
