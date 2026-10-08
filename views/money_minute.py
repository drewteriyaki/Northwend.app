# Part of dashboard.py, which runs this file with _view("money_minute") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Today's minute (money_minute.py), behind flag money_minute (flags.FEATURES -
# this whole file is skipped while it's off, so its callers check
# on("money_minute")). One small card a day at the top of Home's "This month"
# column (views/dashboard_page.py; first on a phone) and on Home before
# anything is invested (views/start_home.py): a drill's situation, a quick
# question, a myth or fact, or once a week Teach It Back (views/teach_back.py,
# its own AI check and allowance). The count of days of learning and the
# week's seven marks; a missed day costs nothing. Kept in the login's own
# settings (prefs money_minute: days and card ids only - never a tap or the
# words typed). The person's own only: never drawn while an advisor is in a
# client's account or on an advisor's own Home (_kit_shown, views/kit.py),
# never sent to the AI (Teach It Back sends only what it always sends).
# ruff: noqa: F821

import drills
import money_minute
import teach_back


def _minute_shown():
    """The kit's rule: an investor (or a client) on their own account - also
    checked in the callbacks, a run later."""
    return flags.on("money_minute") and _kit_shown()


def _mm_today():
    return datetime.now().date()


def _mm_teach(today):
    """Whether today may be a teach-back day: Teach It Back is on and the
    person didn't ask for a quick question instead."""
    return flags.on("teach_back") and st.session_state.get("mm_swap") != today.isoformat()


def _mm_keep(item):
    p = _read_prefs()
    if money_minute.record(p, item, _mm_today()):
        _write_prefs(p)


def _mm_tap(item, choice):
    """A tap: what they tapped stays in this browser session only; the day
    and the card's id are kept."""
    if not _minute_shown() or item not in money_minute.ALL_IDS:
        return
    st.session_state["mm_tap"] = {"day": _mm_today().isoformat(), "item": item,
                                  "choice": choice}
    _mm_keep(item)


def _mm_teach_done(key):
    """Teach It Back answered (views/teach_back.py, after its own record):
    the day counts once there's a verdict."""
    if not _minute_shown():
        return
    if (st.session_state.get(f"tb_result_{key}") or {}).get("verdict"):
        _mm_keep(f"t_{key}")


def _mm_swap():
    st.session_state["mm_swap"] = _mm_today().isoformat()


def _mm_open_mix():
    st.session_state["plan_tab"] = "Target mix"
    _go("Plan")


def _mm_marks_html(p, today):
    labels = {"done": "a minute", "today": "today", "open": "no minute", "later": "to come"}
    marks = money_minute.week_marks(p, today)
    done = sum(1 for _d, m in marks if m == "done")
    spans = "".join(f"<span class='pt-mm-mark pt-mm-{m}' title='{d:%a}: {labels[m]}'></span>"
                    for d, m in marks)
    return (f"<div class='pt-mm-marks' role='img' aria-label='This week: {done} of 7 days "
            f"with a minute'>{spans}</div>")


def _mm_head_html(p, today):
    star = ("<svg width='16' height='16' viewBox='0 0 24 24' aria-hidden='true'><path "
            "d='M12 2 L14 10 L22 12 L14 14 L12 22 L10 14 L2 12 L10 10 Z' "
            "fill='currentColor'></path></svg>")
    return ("<div class='pt-mm-head'><div class='pt-mm-top'>"
            f"<span class='pt-mm-title'>{html.escape(money_minute.TITLE)}</span>"
            f"<span class='pt-mm-count'>{star}"
            f"{html.escape(money_minute.days_text(money_minute.count(p)))}</span></div>"
            + _mm_marks_html(p, today)
            + f"<div class='pt-mm-week'>{html.escape(money_minute.WEEK_LINE)}</div></div>")


def _mm_source(key):
    src = money_minute.source(key)
    if src:
        label, url, who = src
        st.caption(":material/open_in_new: "
                   + money_minute.SOURCE_LINE.format(who=who, label=label, url=url))


def _mm_link(link, where):
    """A link to their own page, where it applies: the Fee check (Home with
    holdings), their target mix (Plan, when they set it)."""
    if link == "fees" and where == "home" and HAS_REAL_HOLDINGS:
        line, button = money_minute.LINK_LINES["fees"]
        st.caption(line)
        if st.button(button, key="mm_link_fees", type="tertiary"):
            open_fee_window()   # views/fees.py
    elif link == "mix" and CAN_MANAGE and "Plan" in PAGES:
        line, button = money_minute.LINK_LINES["mix"]
        st.caption(line)
        st.button(button, key="mm_link_mix", type="tertiary", on_click=_mm_open_mix)


def _mm_esc(text):
    return text.replace("$", r"\$")


def _mm_drill(item, tapped, done):
    key = money_minute.drill_key(item)
    st.markdown(drills.BY_KEY[key][3])
    if tapped is None and not done:
        st.markdown(f"**{money_minute.DRILL_ASK}**")
        for choice, words in drills.choices_of(key):
            st.button(words, key=f"mm_{choice}", width="stretch", on_click=_mm_tap,
                      args=(item, choice))
        return
    if tapped is not None and drills.choice_words(key, tapped):
        st.markdown(f":material/check_circle: {money_minute.YOUD_START} "
                    f"*{drills.choice_words(key, tapped)}*")
    with st.container(border=True, key="pt_mm_note"):
        st.markdown(f"**{drills.THINK_LEAD}**")
        st.markdown(drills.think_of(key))
        st.caption(drills.NO_RIGHT_ANSWER)


def _mm_quiz(item, tapped, done, where):
    _id, question, choices, answer, why, src, link = money_minute.QUIZ_BY_ID[item]
    st.markdown(f"**{_mm_esc(question)}**")
    if tapped is None and not done:
        for choice, words in choices:
            st.button(_mm_esc(words), key=f"mm_{choice}", width="stretch", on_click=_mm_tap,
                      args=(item, choice))
        return
    lead = ("" if tapped is None else
            (money_minute.QUIZ_YES if tapped == answer else money_minute.QUIZ_NOT_QUITE) + " ")
    st.markdown(_mm_esc(lead + money_minute.ANSWER_IS.format(
        answer=money_minute.quiz_answer_words(item))))
    st.markdown(_mm_esc(why))
    _mm_source(src)
    _mm_link(link, where)


def _mm_myth(item, tapped, done, where):
    _id, statement, is_myth, why, src, link = money_minute.MYTH_BY_ID[item]
    st.markdown(f"**“{_mm_esc(statement)}”**")
    if tapped is None and not done:
        with st.container(horizontal=True, gap="small", key="pt_mm_mf"):
            st.button(money_minute.MYTH_WORD, key="mm_myth", on_click=_mm_tap,
                      args=(item, "myth"))
            st.button(money_minute.FACT_WORD, key="mm_fact", on_click=_mm_tap,
                      args=(item, "fact"))
        return
    word = money_minute.MYTH_WORD if is_myth else money_minute.FACT_WORD
    st.markdown(f"**{word}.** {_mm_esc(why)}")
    _mm_source(src)
    _mm_link(link, where)


def _mm_teach_card(item, done):
    key = money_minute.teach_key(item)
    title, text = teach_back.CONCEPTS[key]
    st.markdown(f"**{title}**")
    has_result = bool(st.session_state.get(f"tb_result_{key}"))
    if done and not has_result:
        st.caption(money_minute.DONE_TODAY)
        return
    st.markdown(money_minute.TEACH_LEAD)
    with st.expander(money_minute.TEACH_READ, icon=":material/menu_book:"):
        st.markdown(text)
    render_teach_back(key, after=_mm_teach_done, compact=True)   # views/teach_back.py
    if not has_result:
        st.button(money_minute.TEACH_SWAP, key="mm_swap", type="tertiary", on_click=_mm_swap)


def render_minute_card(where="home"):
    """Today's minute: the count and the week's marks, the day's card, and
    tomorrow's kind. `where`: "home" (with holdings) or "start" (Home before
    anything is invested)."""
    if not _minute_shown():
        return
    p = _read_prefs()
    today = _mm_today()
    teach = _mm_teach(today)
    item = money_minute.pick(LOGIN_ID, today, p, teach)
    kind = money_minute.kind_of(item)
    done = money_minute.answered(p, today)
    tap = st.session_state.get("mm_tap") or {}
    tapped = (tap.get("choice") if tap.get("day") == today.isoformat()
              and tap.get("item") == item else None)
    with st.container(border=True, key="pt_minute", gap="small"):
        st.html(_mm_head_html(p, today))
        extra = money_minute.ONCE_A_WEEK if kind == money_minute.TEACH \
            else money_minute.ABOUT_A_MINUTE
        st.html(f"<div class='pt-mm-kind'>{html.escape(money_minute.KIND_LABELS[kind])}"
                f" · {html.escape(extra)}</div>")
        if kind == money_minute.DRILL:
            _mm_drill(item, tapped, done)
        elif kind == money_minute.QUIZ:
            _mm_quiz(item, tapped, done, where)
        elif kind == money_minute.MYTH:
            _mm_myth(item, tapped, done, where)
        else:
            _mm_teach_card(item, done)
        if done and kind != money_minute.TEACH and tapped is None:
            st.caption(money_minute.DONE_TODAY)
        st.html(f"<div class='pt-mm-next'>"
                f"{html.escape(money_minute.tomorrow_line(LOGIN_ID, today, flags.on('teach_back')))}"
                "</div>")
