# Part of dashboard.py, which runs this file with _view("advisor_pack") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, USER_ID, LOGIN_ID, PAGE, the helpers...) are dashboard.py's, and
# what this defines is visible there afterwards. See _view() in dashboard.py.
#
# Bring to my advisor (ROADMAP Phase C2, advisor_pack.py), behind flag
# advisor_pack (flags.FEATURES - this whole file is skipped while it's off; the
# places that draw it check on("advisor_pack") first). Three parts:
# - render_advisor_pack(): on the Account page (views/account.py), for a client
#   signed in as themselves - never an advisor in client mode, never an admin.
#   Checkboxes, all off; the first tick shows the consent words and "Yes, share
#   what I ticked" records the grant with them (advisor_pack.start); after that
#   each tick or untick is saved at once, and unticking the last ends it.
# - _render_pack_advisor(): "What <client> chose to bring", over meeting prep on
#   the client's Advisor notes page (views/meeting.py calls it). Closed until
#   the advisor opens it; each opening writes an access_log row (page
#   "advisor_pack") that the client sees. Only the ticked items, each "Shared by
#   <client> on <date>; client-reported".
# - render_pack_season_note(): "This season for your clients" in the advisor's
#   book (views/clients.py) - the season clients are in and what they read.
# ruff: noqa: F821

import advisor_pack
import future_notes
import standing_line


# ---- the client's side (Account) ---------------------------------------------- #
def _pack_mine():
    """A client signed in as themselves (also in a callback, a run later);
    advisor_pack checks again in the database."""
    return (USER_ID == LOGIN_ID and IS_MANAGED_CLIENT and not IS_ADVISOR and not IS_ADMIN
            and flags.on(advisor_pack.FLAG))


def _pack_today():
    return datetime.now().date()


def _pack_tick(item):
    if not _pack_mine():
        return
    on = bool(st.session_state.get(f"pack_{item}"))
    c = connect(DB)
    try:
        advisor_pack.tick(c, LOGIN_ID, item, on, by=LOGIN_ID, today=_pack_today())
    except PermissionError:
        st.session_state["pack_msg"] = advisor_pack.NOT_ALLOWED
    finally:
        c.close()


def _pack_start(text):
    if not _pack_mine():
        return
    picked = [i for i in st.session_state.get("_pack_offered", ())
              if st.session_state.get(f"pack_{i}")]
    c = connect(DB)
    try:
        advisor_pack.start(c, LOGIN_ID, picked, by=LOGIN_ID, text_shown=text,
                           today=_pack_today())
        st.session_state["pack_msg"] = "Shared. Your advisor sees only what's ticked."
    except PermissionError:
        st.session_state["pack_msg"] = advisor_pack.NOT_ALLOWED
    except ValueError:
        st.session_state["pack_msg"] = "Tick something first."
    finally:
        c.close()


def _pack_stop():
    if not _pack_mine():
        return
    c = connect(DB)
    try:
        advisor_pack.stop(c, LOGIN_ID, by=LOGIN_ID)
    except PermissionError:
        st.session_state["pack_msg"] = advisor_pack.NOT_ALLOWED
        return
    finally:
        c.close()
    for i in st.session_state.get("_pack_offered", ()):
        st.session_state.pop(f"pack_{i}", None)
    st.session_state["pack_msg"] = advisor_pack.STOPPED


def render_advisor_pack():
    """The Account page's Bring to my advisor section."""
    if not _pack_mine():
        return
    c = connect(DB)
    try:
        advisor_id = advisor_pack.advisor_for(c, LOGIN_ID, LOGIN_ID)
        if advisor_id is None:
            return
        have = advisor_pack.shared(c, LOGIN_ID, advisor_id)
        agreed = advisor_pack.consented(c, LOGIN_ID, advisor_id)
        note = (future_notes.get(c, LOGIN_ID, future_notes.DRILL)
                if flags.on("storm_drill") else None)
    finally:
        c.close()
    items = advisor_pack.offered(_read_prefs(), has_storm_note=bool(note),
                                 features=advisor_pack.features_now(), ticked=have)
    st.session_state["_pack_offered"] = items

    st.subheader(advisor_pack.TITLE, anchor="bring-to-my-advisor")
    st.caption(advisor_pack.INTRO)
    msg = st.session_state.pop("pack_msg", None)
    if msg:
        st.caption(f":material/check: {msg}")

    def box(item):
        key = f"pack_{item}"
        if agreed:   # what's saved, each run (an untick elsewhere shows here too)
            st.session_state[key] = item in have
        st.checkbox(advisor_pack.label(item), key=key,
                    on_change=_pack_tick if agreed else None,
                    args=(item,) if agreed else None)
        if item == advisor_pack.STORM_NOTE and note:
            st.caption(f"“{_md_name(' '.join(str(note['body']).split()))}”")
        if agreed and item in have:
            st.caption(advisor_pack.SHARED_ON.format(date=_fmt_date(have[item])))

    with st.container(border=True, key="pt_pack_client"):
        for item in items:
            if advisor_pack.kind(item) != advisor_pack.QUESTION:
                box(item)
        st.markdown(f"**{advisor_pack.QUESTIONS_LEAD}**")
        st.caption(advisor_pack.QUESTIONS_NOTE)
        for item in items:
            if advisor_pack.kind(item) == advisor_pack.QUESTION:
                box(item)
    if agreed:
        st.button(advisor_pack.STOP, key="pack_stop", type="tertiary", on_click=_pack_stop)
        return
    picked = [i for i in items if st.session_state.get(f"pack_{i}")]
    if not picked:
        st.caption(f":material/lock: {advisor_pack.NOT_YET}")
        return
    text = advisor_pack.consent_text(_advisor_display_name())
    with st.container(border=True, key="pt_pack_consent"):
        st.markdown(_md_name(text))
        st.button(advisor_pack.CONFIRM, key="pack_share", type="primary",
                  on_click=_pack_start, args=(text,))


# ---- the advisor's side (over meeting prep) ------------------------------------- #
def _pack_advisor_view():
    return (IS_ADVISOR and ON_CLIENT and USER_ID != LOGIN_ID
            and flags.on(advisor_pack.FLAG))


def _pack_open():
    """Open the card: one access_log row each time (the client sees it)."""
    if not _pack_advisor_view():
        return
    viewer, target = st.session_state["user_id"], st.session_state["active_user_id"]
    c = connect(DB)
    try:
        if viewer == target or not auth.can_view(c, viewer, target):
            return
        access_log.record(c, viewer, target, advisor_pack.ACCESS_PAGE)
    finally:
        c.close()
    # open for this client, until the next page view (dashboard's _access_last)
    st.session_state["pack_open"] = (target, st.session_state.get("_access_last"))


def _pack_close():
    st.session_state.pop("pack_open", None)


def _render_pack_advisor():
    """What the client chose to bring - only the ticked items."""
    if not _pack_advisor_view():
        return
    client = _md_name(ACTIVE_NAME)
    with st.container(border=True, key="pt_pack_advisor"):
        st.markdown(f"**:material/inventory_2: "
                    f"{advisor_pack.ADVISOR_TITLE.format(client=client)}**")
        st.caption(advisor_pack.ADVISOR_INTRO.format(client=client))
        if st.session_state.get("pack_open") != (USER_ID, st.session_state.get("_access_last")):
            st.button(advisor_pack.ADVISOR_OPEN, key="pack_open_btn", on_click=_pack_open,
                      icon=":material/visibility:")
            return
        c = connect(DB)
        try:
            items = advisor_pack.for_advisor(c, LOGIN_ID, USER_ID,
                                             features=advisor_pack.features_now())
            line = standing_line.for_advisor(c, LOGIN_ID)
        except PermissionError:
            items, line = [], None
        finally:
            c.close()
        if not items:
            st.caption(advisor_pack.NOTHING_SHARED.format(client=client))
        questions = [i for i in items if i["kind"] == advisor_pack.QUESTION]
        for it in items:
            if it["kind"] == advisor_pack.QUESTION:
                continue
            st.markdown(f"**{_md_name(it['title'])}**")
            if it["own_words"]:
                st.markdown("\n".join(f"> {_md_name(t)}" for t in it["lines"]))
                if it.get("written_on"):
                    st.caption(advisor_pack.STORM_WRITTEN.format(
                        date=_fmt_date(it["written_on"])))
            else:
                st.markdown("\n".join(f"- {_md_name(t)}" for t in it["lines"]))
            st.caption(advisor_pack.SHARED_BY.format(client=client,
                                                     date=_fmt_date(it["shared_on"])))
        if questions:
            st.markdown(f"**{advisor_pack.QUESTIONS_ADVISOR}**")
            for it in questions:
                st.markdown(f"- {_md_name(it['lines'][0])}  \n"
                            f"  :gray[{advisor_pack.SHARED_BY.format(client=client, date=_fmt_date(it['shared_on']))}]")
        st.caption(advisor_pack.ADVISOR_FOOT.format(client=client))
        if line:
            st.caption(f"Anything you write to {client} from it reaches them under your name, "
                       f"with: “{_md_name(line)}”")
        st.button(advisor_pack.ADVISOR_CLOSE, key="pack_close_btn", type="tertiary",
                  on_click=_pack_close)


# ---- the advisor's book: this season for your clients (R7) --------------------- #
def render_pack_season_note(today):
    if not (IS_ADVISOR and flags.on(advisor_pack.FLAG)):
        return
    heading, text = advisor_pack.season_note(today)
    with st.container(border=True, key="pt_pack_season"):
        st.markdown(f"**:material/calendar_month: {advisor_pack.SEASON_TITLE}** · {heading}")
        st.caption(f"{text} {advisor_pack.SEASON_NOTE}")
