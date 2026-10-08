# Part of dashboard.py, which runs this file with _view("year_review") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what
# this defines is visible there afterwards. See _view() in dashboard.py.
#
# Year in review (ROADMAP 9, recap.py): a private look back at the year so
# far, or the whole of last year, as a short scroll of cards in a window -
# opened from Home ("Your year so far" any time; a card through January for
# the year just ended). Plus a version to share with no dollar figures: a
# card on screen to screenshot, and a one-page PDF. Hidden amounts are
# masked; the example and percentages portfolios show no money figures.
# Only in a person's own account (never while an advisor views a client).
# ruff: noqa: F821

import flags
import gear
import recap


def _year_shown():
    return USER_ID == LOGIN_ID


def _year_pretend():
    return SNAPSHOT_SOURCE if SNAPSHOT_SOURCE in recap.PRETEND_SOURCES else None


def _year_mark_seen(year):
    if not _year_shown():
        return
    p = _read_prefs()
    seen = list(p.get(recap.SEEN_PREF) or [])
    if year not in seen:
        p[recap.SEEN_PREF] = seen + [year]
        _write_prefs(p)


def _year_card(title, body_html):
    with st.container(border=True):
        st.html(f"<div class='pt-route-label'>{html.escape(title)}</div>{body_html}")


def _year_big(text, sub=""):
    return (f"<div style='font-family: Newsreader, Georgia, serif; font-size: 1.7rem; "
            f"line-height: 1.2'>{text}</div>"
            + (f"<div class='pt-region'>{sub}</div>" if sub else ""))


def _year_pct(v):
    return _tone(v, fmt_pct(v)) if v is not None else "—"


def _year_share_html(r):
    """The share card: what recap.share_lines() says, styled to screenshot."""
    rows = "".join(
        (f"<div style='margin:.55rem 0'><div style='font-size:.7rem; font-weight:600; "
         f"letter-spacing:.06em; text-transform:uppercase; opacity:.7'>{html.escape(h)}</div>"
         f"<div style='font-size:1.05rem'>{html.escape(t)}</div></div>") if h else
        (f"<div style='margin-top:.9rem; font-family: Newsreader, Georgia, serif; "
         f"font-style: italic; font-size:1.1rem'>{html.escape(t)}</div>")
        for h, t in recap.share_lines(r))
    title = f"My {r['year']} so far" if r["so_far"] else f"My {r['year']}"
    return ("<div style='border:2px solid var(--pt-dawn); border-radius:16px; padding:1.2rem "
            "1.4rem; background: var(--pt-dawn-soft); max-width: 26rem'>"
            f"<div style='font-size:.75rem; opacity:.7'>{html.escape(APP_NAME)} · year in "
            "review</div>"
            f"<div style='font-family: Newsreader, Georgia, serif; font-size:2rem; "
            f"line-height:1.15; margin:.2rem 0 .4rem'>{html.escape(title)}</div>{rows}</div>")


def _year_cards(r):
    hidden = _hidden()
    label = "this year so far" if r["so_far"] else str(r["year"])
    if r["pretend"] == SAMPLE_SOURCE:
        st.caption(":material/science: You're looking around with the example portfolio, so "
                   "there are no real figures here yet - only what you've learned. Bring in "
                   "your own holdings and next time this fills in.")
    elif r["pretend"]:
        st.caption(":material/percent: A percentages portfolio has no real dollar amounts, so "
                   "this shows percentages and counts only.")

    # ---- money added ---------------------------------------------------------- #
    if r["money"]:
        n = len(r["months_added"])
        if r["moves"]:
            _year_card("Money you added", _year_big(
                fmt_money(r["added"]),
                (f"Added in {n} month{'s' if n != 1 else ''} of {label}" if n else
                 "Net of what you took out") + "."))
        else:
            _year_card("Money you added", "<div class='pt-region'>Nothing logged for "
                       f"{html.escape(label)}. Money you add can be logged on Plan, or comes in "
                       "with your brokerage's activity export.</div>")

    # ---- paid to you ---------------------------------------------------------- #
    inc = r["income"]
    if inc and inc["payments"]:
        how = ("From your brokerage's activity" + (f", since {_fmt_date(inc['since'])}"
                                                   if inc["since"] else "")
               if inc["source"] == "brokerage" else
               "Worked out from each fund's payments and the shares you held - a rough figure")
        parts = [f"{inc['payments']} payment{'s' if inc['payments'] != 1 else ''}"]
        if inc["interest"] and not hidden:
            parts.append(f"{fmt_money(inc['interest'])} of it interest")
        _year_card("Dividends and interest paid to you",
                   _year_big(fmt_money(inc["total"]), html.escape(f"{', '.join(parts)}. {how}.")))

    # ---- start and end ------------------------------------------------------- #
    if r["money"] and r["value_end"] is not None:
        start_word = ("January 1" if r["value_start_day"] == r["start"]
                      else _fmt_date(r["value_start_day"]))
        end_word = "today" if r["so_far"] else "December 31"
        sub = f"From {fmt_money(r['value_start'])} on {start_word}."
        if r["growth"] is not None:
            sub += (f" Beyond the money you added, that's {_signed_money(r['growth'])} from the "
                    "markets and what your investments paid.")
        _year_card(f"Your portfolio, {start_word} to {end_word}",
                   _year_big(fmt_money(r["value_end"]), sub))

    # ---- month by month ---------------------------------------------------- #
    if r["months"]:
        body = ""
        if r["market_move"] is not None:
            body += _year_big(_year_pct(r["market_move"]),
                              "How the holdings you have now moved over "
                              + (f"the year, since {_fmt_date(r['market_since'])}"
                                 if r["market_since"] else html.escape(label))
                              + ", at each day's close - the market's part alone.")
        if r["best"] and r["worst"]:
            body += (f"<div style='margin-top:.6rem'>Best month: <b>"
                     f"{recap.month_name(r['best']['month'])}</b> {_year_pct(r['best']['pct'])}"
                     f" · Toughest: <b>{recap.month_name(r['worst']['month'])}</b> "
                     f"{_year_pct(r['worst']['pct'])}</div>")
        _year_card("Month by month", body)
        if not hidden and len(r["months"]) >= 2:
            st.bar_chart(pd.DataFrame({"Month": [recap.month_name(m["month"])[:3]
                                                 for m in r["months"]],
                                       "Change %": [m["pct"] for m in r["months"]]}),
                         x="Month", y="Change %", height=180, sort=False)

    # ---- learning and milestones ------------------------------------------- #
    if r["gear"] or r["steps"] or r["reads"] or r["notes"]:
        body = ""
        if r["gear"]:
            body += ("<div style='display:flex; gap:.6rem; flex-wrap:wrap; margin:.2rem 0 .5rem'>"
                     + "".join(f"<span title='{html.escape(gear.BY_KEY[k][1], quote=True)}'>"
                               f"{gear.icon_html(k, True, 30)}</span>" for k in r["gear"])
                     + "</div><div>Milestones: <b>"
                     + html.escape(", ".join(gear.BY_KEY[k][1] for k in r["gear"])) + "</b></div>")
        if r["steps"]:
            body += ("<div>Learn steps completed: "
                     + html.escape(", ".join(recap.STEP_NAMES[s] for s in r["steps"])) + "</div>")
        if r["reads"]:
            body += (f"<div>{len(r['reads'])} short read{'s' if len(r['reads']) != 1 else ''} "
                     "opened on Learn</div>")
        if r["notes"]:
            body += (f"<div>{r['notes']} note{'s' if r['notes'] != 1 else ''} to future you "
                     "written</div>")
        _year_card("What you learned and kept up", body)

    # the Expedition Log's lines (R3, expedition_log.py): the person's own walks
    if r.get("walk_log") and flags.on("walk") and flags.on("walk_log") and not IS_ADVISOR:
        _year_card("Your log", "".join(f"<div style='margin:.15rem 0'>{html.escape(t)}</div>"
                                       for t in r["walk_log"]))

    st.html("<div style='font-family: Newsreader, Georgia, serif; font-style: italic; "
            f"font-size: 1.15rem; margin: .4rem 0 .2rem'>{html.escape(r['perspective'])}</div>")
    if hidden:
        st.caption(f"Amounts are hidden ({MASK}). Show amounts at the top of the page to see them.")


@st.dialog("Your year", width="medium", on_dismiss=_dialog_closed)
def _year_window(year):
    today = datetime.now().date()
    years = [today.year, today.year - 1]
    st.session_state.setdefault("yr_pick", year if year in years else today.year)
    pick = st.segmented_control("Which year", years, key="yr_pick",
                                format_func=lambda y: "This year so far" if y == today.year
                                else str(y), label_visibility="collapsed") or today.year
    if pick < today.year:
        _year_mark_seen(pick)
    c = connect(DB)
    try:
        r = recap.build(c, USER_ID, pick, today, prefs=_read_prefs(),
                        current_value=None if _year_pretend() else portfolio_value,
                        basis=PERF_BASIS, pretend=_year_pretend())
    finally:
        c.close()
    st.caption("Private to you - nobody else sees this, and nothing is sent anywhere.")
    if recap.is_empty(r):
        st.info(f"Nothing to look back on for {pick} yet. "
                "It fills in as you add money, learn and keep going.")
        return
    _year_cards(r)
    with st.expander("A version to share, with no amounts", icon=":material/ios_share:"):
        st.caption("Percentages, months and milestones only - never a dollar figure. Take a "
                   "screenshot of the card, or download it as a PDF. Share it only if you'd "
                   "like to.")
        if _hidden():
            st.caption(f"Amounts are hidden, so the card is too ({MASK}). The PDF has the "
                       "percentages, still no dollar figures.")
        else:
            st.html(_year_share_html(r))
        st.download_button("Download as PDF", recap.share_pdf(r, APP_NAME),
                           file_name=recap.share_file_name(r), mime="application/pdf",
                           key="yr_share_pdf", on_click="ignore",
                           icon=":material/download:")


def _year_open(year):
    if st.session_state.get("milestone_queue"):
        return   # the "milestone reached" window is open: one window at a time
    st.session_state["yr_pick"] = year
    _open_window(_year_window, year)


def _year_later(year):
    _year_mark_seen(year)


def render_year_card():
    """Home: through January, a card for the year just ended (until it's
    opened or put away); any other time, one quiet "Your year so far" line."""
    if not _year_shown():
        return
    today = datetime.now().date()
    last = recap.january_year(today)
    if last and last not in (_read_prefs().get(recap.SEEN_PREF) or []):
        with st.container(border=True, key="pt_year_card"):
            st.button(":material/close:", key="year_card_later", type="tertiary",
                      help="Put away", on_click=_year_later, args=(last,))
            st.html(f"<div class='pt-month-card-title'>Your {last} in review</div>"
                    "<div class='pt-region'>Money added, what you learned and the year's "
                    "ups and downs, just for you.</div>")
            if st.button("Take a look", key="year_card_open", type="primary",
                         icon=":material/auto_stories:"):
                _year_open(last)
        return
    with st.container(horizontal=True, vertical_alignment="center", key="pt_year_line"):
        st.caption(f"A private look back at {today.year} so far: money added, what you've "
                   "learned, the year's ups and downs.", width="stretch")
        if st.button("Your year so far", key="year_open", type="tertiary",
                     icon=":material/auto_stories:"):
            _year_open(today.year)
