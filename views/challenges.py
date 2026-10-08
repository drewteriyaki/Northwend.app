# Part of dashboard.py, which runs this file with _view("challenges") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# This month's practice challenge (challenges.py), behind flag challenges
# (flags.FEATURES - this whole file is skipped while it's off, so its callers
# check on("challenges")). A card in Home's This month column
# (views/dashboard_page.py, and views/start_home.py for someone not investing
# yet) and the full challenge on Learn, under practice money
# (views/get_started.py). Practice money on real past prices from what
# daily_bars already holds - nothing is fetched here. Scored only on following
# the rule the person picked. Kept in the login's own settings (prefs
# challenges: keys, the step, answers as keys, the day finished). Never for an
# advisor's client or an advisor in a client's account (CLIENT_MODE), never
# for the advisor app: nothing is drawn, so nothing is written.
# ruff: noqa: F821

import challenges
import starter_funds


def _ch_shown():
    """An investor on their own account only - also checked in the
    callbacks, a run later."""
    return (flags.on("challenges") and not CLIENT_MODE and not IS_ADVISOR
            and USER_ID == LOGIN_ID)


def _ch_today():
    return datetime.now().date()


def _ch_points():
    """{YYYY-MM: (date, {ticker: price})} for the stand-ins - read once a
    day per browser session (two reads of market data, shared by
    everyone), then kept in session state: a rerun reads nothing."""
    day = _ch_today().isoformat()
    kept = st.session_state.get("ch_points")
    if kept and kept[0] == day and kept[1] == DB:
        return kept[2]
    tickers = {part: learn.PRACTICE_TICKERS[block]
               for part, block in challenges.PRACTICE_PART.items()}
    try:
        raw = perf.full_adjusted_closes(DB, tickers.values())
        pts = challenges.monthly_points({part: raw[t] for part, t in tickers.items()})
    except Exception:  # noqa: BLE001 - no prices: every challenge shows as not ready yet
        pts = {}
    st.session_state["ch_points"] = (day, DB, pts)
    return pts


def _ch_month_key(pts=None):
    pts = _ch_points() if pts is None else pts
    return challenges.of_month(challenges.available_keys(pts), _ch_today())


def _ch_month_name(month):
    """'March 2009' from '2009-03'."""
    return f"{date(int(month[:4]), int(month[5:7]), 1):%B %Y}"


def _ch_go(key):
    """Home's button: Learn's practice money, with this challenge open."""
    st.session_state["ch_pick"] = key
    st.session_state["ch_picked"] = True
    starter_funds.open_practice(st.session_state)


def _ch_start(key):
    if not _ch_shown():
        return
    rule = st.session_state.get(f"ch_rule_{key}")
    p = _read_prefs()
    new = challenges.started(p, key, rule)
    if new != p:
        _write_prefs(new)


def _ch_answer(key, choice):
    if not _ch_shown():
        return
    p = _read_prefs()
    new = challenges.answered(p, key, choice, _ch_today())
    if new != p:
        _write_prefs(new)


def _ch_again(key):
    if not _ch_shown():
        return
    p = _read_prefs()
    new = challenges.cleared(p, key)
    if new != p:
        _write_prefs(new)


def _ch_progress(ch, e, pts):
    """The one-line progress for a started challenge."""
    r = challenges.play(ch, pts, e["rule"], e["answers"])
    line = challenges.followed_line(ch, r["checks"]) if r["checks"] else ""
    if e.get("done"):
        return f"{challenges.FINISHED.format(day=_fmt_date(e['done']))} {line}".strip(), r
    return line or challenges.NOT_STARTED, r


def render_challenge_card():
    """Home's card: this month's challenge, its progress and a way in."""
    if not _ch_shown():
        return
    pts = _ch_points()
    key = _ch_month_key(pts)
    if key is None:
        return   # none ready: Learn says why, Home stays quiet
    ch = challenges.BY_KEY[key]
    today = _ch_today()
    e = challenges.entry(_read_prefs(), key)
    status = challenges.NOT_STARTED if e is None else _ch_progress(ch, e, pts)[0]
    end = challenges.month_end(today)
    with st.container(border=True, key="pt_challenge"):
        st.html("<div class='pt-eyebrow' style='margin:0'>"
                f"{html.escape(challenges.EYEBROW.format(month=f'{today:%B}'))}</div>"
                f"<div><b>{html.escape(ch['title'])}</b></div>"
                f"<div class='pt-region'>{html.escape(ch['about'])}</div>"
                f"<div class='pt-region'>{html.escape(status)} · "
                f"{html.escape(challenges.ENDS.format(day=f'{end:%b} {end.day}'))}</div>")
        st.button(challenges.CARD_OPEN if e is None or e.get("done") else challenges.CARD_GO_ON,
                  key="ch_card_open", type="tertiary", icon=":material/flag:",
                  on_click=_ch_go, args=(key,))


def _ch_chart(rows):
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    palette = SERIES_DARK if st.context.theme.type == "dark" else SERIES_LIGHT
    st.caption(f"**{challenges.CHART_LABEL}**")
    st.altair_chart(charts.money_in_chart(df, money_color=SERIES_OTHER, value_color=palette[0],
                                          height=200), width="stretch")


def _ch_pick_rule(ch, key):
    st.markdown(f"**{challenges.PICK_TITLE}**")
    st.caption(challenges.PICK_HELP)
    keys = list(challenges.RULES)
    st.segmented_control("Your rule", keys, default="s70", key=f"ch_rule_{key}",
                         label_visibility="collapsed",
                         format_func=lambda k: challenges.RULE_WORDS.format(
                             pct=challenges.RULES[k]))
    pct = challenges.RULES.get(st.session_state.get(f"ch_rule_{key}") or "s70", 70)
    st.caption(challenges.RULE_LINE.format(pct=pct, every=challenges.every_words(ch)) + ". "
               + challenges.RULE_BAND.format(band=challenges.BAND, pct=pct))
    st.button(challenges.START, key=f"ch_start_{key}", type="primary",
              disabled=not st.session_state.get(f"ch_rule_{key}"),
              on_click=_ch_start, args=(key,))


def _ch_play(ch, key, e, pts):
    pct = challenges.RULES[e["rule"]]
    r = challenges.play(ch, pts, e["rule"], e["answers"])
    st.caption(challenges.RULE_LINE.format(pct=pct, every=challenges.every_words(ch)) + ". "
               + challenges.RULE_BAND.format(band=challenges.BAND, pct=pct))
    _ch_chart(r["rows"])
    if r["checks"]:
        last = r["checks"][-1]
        mark = (":material/check_circle: " + challenges.YOU_FOLLOWED if last["followed"]
                else ":material/info: " + challenges.YOU_DIDNT)
        st.markdown(f"{challenges.said_line(last, pct)} {mark}")
    pending = r["pending"]
    if pending:
        st.html("<div class='pt-region'>" + html.escape(challenges.STEP_LINE.format(
            unit_cap="Month" if ch["every"] == 1 else "Check", at=pending["step"],
            total=challenges.steps(ch), when=_ch_month_name(pending["month"]))) + "</div>")
        now = f"{pending['stocks_pct']:.0f}"
        st.markdown(f"**{challenges.QUESTION.format(now=now)}**")
        with st.container(horizontal=True, gap="small", key=f"pt_ch_choices_{key}"):
            for choice in challenges.CHOICES:
                st.button(challenges.choice_words(choice, ch, pct, pending["low"]),
                          key=f"ch_{key}_{choice}", on_click=_ch_answer, args=(key, choice))
    elif e.get("done"):
        st.markdown(challenges.FINISHED.format(day=_fmt_date(e["done"])))
    with st.container(border=True, key=f"pt_ch_scored_{key}"):
        st.markdown(f"**{challenges.SCORED_TITLE}**")
        st.caption(challenges.SCORED)
        if r["checks"]:
            st.markdown(f"**{challenges.followed_line(ch, r['checks'])}**")
    st.button(challenges.AGAIN, key=f"ch_again_{key}", type="tertiary",
              icon=":material/replay:", on_click=_ch_again, args=(key,))


def render_challenges():
    """Learn, under practice money: this month's challenge, any other to
    replay, and the steps."""
    if not _ch_shown():
        return
    pts = _ch_points()
    ready = challenges.available_keys(pts)
    month_key = challenges.of_month(ready, _ch_today())
    st.markdown(f"#### {challenges.SECTION}")
    if not ready:
        st.caption(challenges.NONE_READY)
    keys = list(challenges.KEYS)
    # until they choose one themselves, the pick follows this month's: once
    # past prices are loaded it moves off a challenge that isn't ready yet
    if (st.session_state.get("ch_pick") not in keys
            or not st.session_state.get("ch_picked") and month_key
            and st.session_state["ch_pick"] != month_key):
        st.session_state["ch_pick"] = month_key or keys[0]
    key = st.selectbox(
        challenges.OTHERS, keys, key="ch_pick",
        on_change=lambda: st.session_state.update(ch_picked=True),
        format_func=lambda k: challenges.BY_KEY[k]["title"]
        + ("" if k in ready else f" ({challenges.NOT_READY_TAG})"))
    ch = challenges.BY_KEY[key]
    today = _ch_today()
    with st.container(border=True, key="pt_ch_full"):
        if key == month_key:
            end = challenges.month_end(today)
            st.html("<div class='pt-eyebrow' style='margin:0'>"
                    f"{html.escape(challenges.EYEBROW.format(month=f'{today:%B}'))} · "
                    f"{html.escape(challenges.ENDS.format(day=f'{end:%b} {end.day}'))}</div>")
        st.markdown(f"**{ch['title']}**  \n{ch['about']}".replace("$", r"\$"))
        st.caption(challenges.mix_line())
        if key not in ready:
            first, last = challenges.first_last(ch)
            st.info(challenges.NOT_READY.format(first=_ch_month_name(first),
                                                last=_ch_month_name(last)),
                    icon=":material/hourglass_empty:")
        else:
            e = challenges.entry(_read_prefs(), key)
            if e is None:
                _ch_pick_rule(ch, key)
            else:
                _ch_play(ch, key, e, pts)
        nxt = challenges.next_of_month(ready, today)
        if key == month_key and nxt and nxt != key:
            st.caption(challenges.NEXT.format(title=challenges.BY_KEY[nxt]["title"])
                       .replace("$", r"\$"))
    st.caption(challenges.FOOTER)
