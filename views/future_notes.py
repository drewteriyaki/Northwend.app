# Part of dashboard.py, which runs this file with _view("future_notes") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Notes to future you (ROADMAP 8, future_notes.py): a private note on a
# holding (its details, views/ticker_detail.py) or on the plan (Plan, by the
# goal), shown back on Home's storm note when markets drop (views/kit.py),
# and a gentle "leave a note?" after a first save of holdings. Drawn only on
# the login's own account - never while an advisor is looking at a client -
# and sent to Ask Northwend only when the person asks it about a note.
# ruff: noqa: F821

import future_notes
import sealed_envelope


def _notes_mine():
    """Notes are private: only on the person's own account."""
    return USER_ID == LOGIN_ID


def _fn_key(symbol):
    if symbol == future_notes.DRILL:
        return "drill"
    return symbol or "plan"


def _fn_read(symbol):
    c = connect(DB)
    try:
        return future_notes.get(c, USER_ID, symbol)
    finally:
        c.close()


def _fn_save(symbol, text_key=None):
    k = _fn_key(symbol)
    if not _notes_mine():
        return
    c = connect(DB)
    try:
        kept = future_notes.save(c, USER_ID, symbol,
                                 st.session_state.get(text_key or f"fn_text_{k}") or "")
    finally:
        c.close()
    st.session_state.pop(f"fn_edit_{k}", None)
    st.session_state[f"fn_msg_{k}"] = ("Saved. Only you can see it." if kept else
                                       "Nothing to save, so there's no note here.")


def _fn_edit(symbol, body):
    k = _fn_key(symbol)
    st.session_state[f"fn_edit_{k}"] = True
    st.session_state[f"fn_text_{k}"] = body or ""


def _fn_cancel(symbol):
    k = _fn_key(symbol)
    for name in (f"fn_edit_{k}", f"fn_del_{k}"):
        st.session_state.pop(name, None)


def _fn_ask_delete(symbol):
    st.session_state[f"fn_del_{_fn_key(symbol)}"] = True


def _fn_delete(symbol):
    k = _fn_key(symbol)
    if not _notes_mine():
        return
    c = connect(DB)
    try:
        future_notes.delete(c, USER_ID, symbol)
    finally:
        c.close()
    for name in (f"fn_edit_{k}", f"fn_del_{k}", f"fn_text_{k}"):
        st.session_state.pop(name, None)
    st.session_state[f"fn_msg_{k}"] = "Deleted."


def _fn_ask(note):
    """Ask Northwend about this note - the only way a note reaches the AI:
    in the person's own question, as one quoted line (future_notes.ask_text)."""
    st.session_state["coach_prompt"] = future_notes.ask_text(note)
    st.session_state["page"] = "AI Assistant"


def _fn_quote_html(note, *, lead=None):
    """The note as a quote, with the day it was written (escaped: it's
    typed text)."""
    when = _fmt_date(future_notes.written_on(note))
    return ("<div class='pt-fnote'>" + html.escape(note["body"]) + "</div>"
            f"<div class='pt-fnote-when'>{html.escape(lead or 'You wrote this on')} "
            f"{html.escape(when)}</div>")


def _render_note_body(symbol, note):
    """The note (or the box to write one) without its frame."""
    k = _fn_key(symbol)
    ss = st.session_state
    msg = ss.pop(f"fn_msg_{k}", None)
    if msg:
        st.caption(f":material/check: {msg}")
    if note and not ss.get(f"fn_edit_{k}"):
        st.html(_fn_quote_html(note))
        if ss.get(f"fn_del_{k}"):
            with st.container(horizontal=True, vertical_alignment="center"):
                st.caption("Delete this note? It can't be brought back.", width="stretch")
                st.button("Delete", key=f"fn_del_yes_{k}", on_click=_fn_delete, args=(symbol,))
                st.button("Keep it", key=f"fn_del_no_{k}", type="tertiary",
                          on_click=_fn_cancel, args=(symbol,))
            return
        with st.container(horizontal=True):
            st.button("Edit", key=f"fn_edit_btn_{k}", type="tertiary", icon=":material/edit:",
                      on_click=_fn_edit, args=(symbol, note["body"]))
            st.button("Delete", key=f"fn_del_btn_{k}", type="tertiary",
                      icon=":material/delete:",
                      on_click=_fn_ask_delete, args=(symbol,))
            st.button(f"Ask {GUIDE} about it", key=f"fn_ask_{k}", type="tertiary",
                      icon=":material/forum:", on_click=_fn_ask, args=(note,))
        return
    drill = symbol == future_notes.DRILL   # the Storm Drill: no example, no right answer
    st.text_area(future_notes.DRILL_QUESTION if drill else "Note to future you",
                 key=f"fn_text_{k}", max_chars=future_notes.MAX_CHARS,
                 height=90, label_visibility="collapsed",
                 placeholder=(None if drill else future_notes.PLACEHOLDER_HOLDING if symbol
                              else future_notes.PLACEHOLDER_PLAN))
    with st.container(horizontal=True):
        st.button("Save note", key=f"fn_save_{k}", type="primary", on_click=_fn_save,
                  args=(symbol,))
        if note:
            st.button("Cancel", key=f"fn_cancel_{k}", type="tertiary", on_click=_fn_cancel,
                      args=(symbol,))


@st.fragment
def render_future_note(symbol=None):
    """"Note to future you" on a holding's details (`symbol`) or on Plan
    (None). Saving or deleting redraws just this box."""
    if not _notes_mine():
        return
    note = _fn_read(symbol)
    with st.container(border=True, key=f"pt_fnote_{_fn_key(symbol)}"):
        st.markdown(":material/edit_note: **Note to future you**")
        st.caption(("Why you hold this, in your own words - shown back to you if markets "
                    "drop a lot. " if symbol else
                    "What this money is for, in your own words - shown back to you if "
                    "markets drop a lot. ") + future_notes.PRIVATE_LINE)
        _render_note_body(symbol, note)


# ---- the storm note (views/kit.py render_weather): their own words back ----- #

def _storm_falls(symbols, since):
    """{symbol: % below its highest close since `since`} from the daily
    closes - one query, only for the holdings that have a note."""
    if not symbols:
        return {}
    c = connect(DB)
    try:
        rows = perf.closes_since(c, symbols, since)
    finally:
        c.close()
    out, high, last = {}, {}, {}
    for r in rows:
        t = r["ticker"]
        high[t] = max(high.get(t, 0.0), r["close"])
        last[t] = r["close"]
    for t, h in high.items():
        if h > 0:
            out[t] = max(0.0, (h - last[t]) / h * 100)
    return out


def render_storm_notes(w):
    """Under the storm note: what the person wrote to themselves, for their
    plan and the holdings that fell most - calm, their words, nothing to do."""
    if not _notes_mine():
        return
    c = connect(DB)
    try:
        notes = future_notes.all_notes(c, USER_ID)
    finally:
        c.close()
    if not notes:
        return
    held = {p["symbol"] for p in positions}
    with_notes = sorted(s for s in notes if s is not None and s in held)
    picks = future_notes.storm_picks(notes, _storm_falls(with_notes, w["high_date"]), held)
    if not picks:
        return
    parts = []
    for n in picks:
        head = "Your plan" if n.get("symbol") is None else n["symbol"]
        parts.append(f"<div class='pt-fnote-head'>{html.escape(head)}</div>"
                     f"<div>{html.escape(future_notes.quote(n, _fmt_date))}</div>")
    st.html("<div class='pt-fnote-storm'><div class='pt-eyebrow' style='margin:0'>"
            "In your own words</div>" + "".join(parts) + "</div>")


# ---- the Storm Drill (ROADMAP R4, flag storm_drill): written on the Stress
# test after seeing 2008, read back on the storm note when a drop comes ----- #

DRILL_LINE = ("Your own words - there's no right answer. If markets drop, Home shows you "
              "what you wrote. ")
DRILL_COUNT_LINE = ("Northwend counts only how many people wrote one, never the words; "
                    "you can leave yourself out on Account.")


def _drill_on():
    """The drill is the person's own: only with its flag, on their own account."""
    return flags.on("storm_drill") and _notes_mine()


def render_storm_drill_field():
    """On the Stress test, after the hard years (views/stress_test.py): one
    field, the person's own words, no suggested answers."""
    if not _drill_on():
        return
    note = _fn_read(future_notes.DRILL)
    with st.container(border=True, key="pt_storm_drill"):
        st.markdown(f":material/edit_note: **{future_notes.DRILL_QUESTION}**")
        st.caption(DRILL_LINE + future_notes.PRIVATE_LINE + " " + DRILL_COUNT_LINE
                   + (" You can choose to bring it to your advisor, on Account."
                      if IS_MANAGED_CLIENT and flags.on("advisor_pack") else ""))
        _render_note_body(future_notes.DRILL, note)
        if note and not st.session_state.get("fn_edit_drill") \
                and not st.session_state.get("fn_del_drill"):
            render_sealed_envelope(note)


# ---- the Sealed Envelope (flag sealed_envelope, sealed_envelope.py): the
# drill answer as a one-page PDF to seal - their words, their day, no figures #

def _envelope_on():
    """Only beside the person's own drill answer (so storm_drill on too)."""
    return _drill_on() and flags.on("sealed_envelope")


def _envelope_name():
    """The name they asked to be called - never the login (MY_NAME falls
    back to it), so None without one."""
    return None if MY_NAME == st.session_state.get("username") else MY_NAME


def _envelope_made():
    """Remember only the day (prefs, the login's own): the PDF isn't kept."""
    if _notes_mine():
        _save_login_pref(sealed_envelope.PREF_MADE, date.today().isoformat())


def _envelope_toggle():
    st.session_state["se_open"] = not st.session_state.get("se_open")


def render_sealed_envelope(note):
    """Under the drill answer: "Make it a sealed envelope" - the PDF is made
    on the download click (a callable), from the words and the day only."""
    if not _envelope_on():
        return
    st.button(sealed_envelope.OFFER, key="se_offer", type="tertiary", icon=":material/mail:",
              on_click=_envelope_toggle)
    if not st.session_state.get("se_open"):
        return
    st.caption(sealed_envelope.OFFER_LINE)
    name = _envelope_name()
    with_name = bool(name) and st.checkbox("Put my name on it", key="se_name", value=False)
    body, day = sealed_envelope.words(note), future_notes.written_on(note)
    shown = name if with_name else None
    st.download_button("Download the envelope (PDF)",
                       lambda: sealed_envelope.render_pdf(body, day, name=shown),
                       file_name=sealed_envelope.file_name(), mime="application/pdf",
                       key="se_pdf", icon=":material/download:", on_click=_envelope_made)


def _envelope_for(note):
    """Whether they made an envelope since these words were written (an
    envelope from older words isn't this answer's)."""
    made = str(_read_prefs().get(sealed_envelope.PREF_MADE) or "")
    return (flags.on("sealed_envelope") and bool(made)
            and made[:10] >= future_notes.written_on(note))


def render_storm_drill():
    """On the storm note (views/kit.py render_weather): the person's drill
    answer back, calmly - or one quiet line saying where to write one."""
    if not _drill_on():
        return
    note = _fn_read(future_notes.DRILL)
    if note:
        lead = ("<div>" + html.escape(sealed_envelope.STORM_LINE) + "</div>"
                if _envelope_for(note) else "")
        st.html("<div class='pt-fnote-storm'><div class='pt-eyebrow' style='margin:0'>"
                "Your storm drill</div>" + lead + "<div>"
                + html.escape(future_notes.drill_quote(note, _fmt_date)) + "</div></div>")
    else:
        st.caption(f"You can write down what you'd do in a drop like this on "
                   f"{_label('Plan')}'s Stress test.")


# ---- after a first save of holdings: "leave a note for future you?" -------- #

def _fn_nudge_done():
    st.session_state.pop("fn_nudge", None)
    st.session_state["dialog_open"] = False


@st.dialog("A note to future you", width="small", on_dismiss=_fn_nudge_done)
def _fn_nudge_window():
    st.caption("Why are you investing this money? A line or two now can be good to read on "
               "a day the market drops. " + future_notes.PRIVATE_LINE)
    st.text_area("Your note", key="fn_text_nudge", max_chars=future_notes.MAX_CHARS, height=110,
                 placeholder=future_notes.PLACEHOLDER_PLAN)
    st.caption("You can also leave one on any holding, from its details on "
               f"{_label('Dashboard')}.")
    with st.container(horizontal=True):
        if st.button("Save note", key="fn_nudge_save", type="primary"):
            _fn_save(None, "fn_text_nudge")
            _fn_nudge_done()
            st.rerun()
        if st.button("Not now", key="fn_nudge_later", type="tertiary"):
            _fn_nudge_done()
            st.rerun()


def render_future_note_nudge():
    """After a first save of real holdings (views/holdings_input.py sets
    fn_nudge): a gentle offer, once - "Not now" or a saved note ends it."""
    if not st.session_state.get("fn_nudge") or not _notes_mine():
        return
    with st.container(border=True, key="pt_fnote_nudge"):
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(":material/edit_note: **Want to leave a note for future you about "
                        "why?** A line about what this money is for - only you can see it.",
                        width="stretch")
            if st.button("Write a note", key="fn_nudge_open"):
                st.session_state["dialog_open"] = True   # live prices wait
                _fn_nudge_window()
            st.button("Not now", key="fn_nudge_no", type="tertiary", on_click=_fn_nudge_done)
