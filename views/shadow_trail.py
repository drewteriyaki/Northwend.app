# Part of dashboard.py, which runs this file with _view("shadow_trail") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Shadow Trail (ROADMAP R14, shadow_trail.py), behind flag shadow_trail AND
# gate L3 (flags.FEATURES - this whole file is skipped while it's off): a Plan
# tab after Stress test (views/plan.py adds it). Up to two hypothetical mixes
# of KINDS of funds, each run on past prices from the day it was set, beside
# the person's own holdings on the same prices - percentages only, one small
# chart and a table, always labelled hypothetical. Changed at most once a
# quarter. Nothing to act on: no "switch", no "rebalance to this", no trade
# link; neutral colours, the table never sorted by how a path did.
#
# Who sees it: the login's own account only (USER_ID == LOGIN_ID) - an
# advisor's client signed in themselves included (it's their own exploration,
# like the practice portfolio). Never drawn while an advisor is in a client's
# account (ON_CLIENT): the shadows are the client's private what-ifs, and an
# advisor seeing them beside the portfolio they built would turn a learning
# toy into a scorecard of the advice. The client's shadows are never read for
# them. Never sent to the AI.
# ruff: noqa: F821

import shadow_trail

SHADOW_TAB = "Shadow Trail"


def _shadow_shown():
    return not ON_CLIENT and USER_ID == LOGIN_ID


def _shadow_real(since):
    """The person's own holdings on past prices (perf.daily_values), or []."""
    try:
        return perf.daily_values(DB, PERF_BASIS, since)
    except Exception:  # noqa: BLE001 - no line is a calm note, never an error page
        return []


def _shadow_remove(place):
    if not _shadow_shown():
        return
    _write_prefs(shadow_trail.without_shadow(_read_prefs(), place))
    st.session_state.pop("shadow_edit", None)


def _shadow_open(place):
    st.session_state["shadow_edit"] = place


def _shadow_close():
    st.session_state.pop("shadow_edit", None)


def _shadow_save(place, today):
    """The form's save (a callback, so the redraw already shows it): kept only
    when it adds up to 100 and the place's date has passed."""
    if not _shadow_shown():
        return
    sh = shadow_trail
    values = {k: int(st.session_state.get(f"shadow_{place}_{k}") or 0) for k in sh.KIND_KEYS}
    new, ok = sh.with_shadow(_read_prefs(), place, values, today)
    if ok:
        _write_prefs(new)
        st.session_state.pop("shadow_edit", None)
        st.session_state.pop("shadow_problem", None)
        for k in sh.KIND_KEYS:
            st.session_state.pop(f"shadow_{place}_{k}", None)
    else:
        st.session_state["shadow_problem"] = sh.save_problem(values)


def _shadow_form(place, slot, today):
    """Whole 5% steps per kind of fund, adding up to 100."""
    sh = shadow_trail
    name = sh.NAMES[place]
    mix = (slot or {}).get("mix") or {}
    problem = st.session_state.pop("shadow_problem", None)
    with st.form(key=f"shadow_form_{place}", border=True):
        cols = st.columns(len(sh.KINDS))
        for col, k in zip(cols, sh.KINDS):
            key = f"shadow_{place}_{k['key']}"
            st.session_state.setdefault(key, int(mix.get(k["key"], 0)))
            col.number_input(sh.FIELD_LABEL.format(kind=k["label"]), min_value=0,
                             max_value=100, step=sh.STEP, key=key,
                             help=k["about"].capitalize() + ".")
        nxt = shadow_trail.add_months(today, sh.LOCK_MONTHS)
        st.caption(sh.SET_NOTE.format(next=sh.date_text(nxt)))
        if problem:
            st.warning(problem)
        st.form_submit_button(sh.SAVE_LABEL.format(name=name), on_click=_shadow_save,
                              args=(place, today))
    st.button(sh.CANCEL_LABEL, key=f"shadow_cancel_{place}", type="tertiary",
              on_click=_shadow_close)


def _shadow_places(places, today):
    """Each place: its mix and dates, edit (only once its lock has passed)
    and remove."""
    sh = shadow_trail
    editing = st.session_state.get("shadow_edit")
    for i, slot in enumerate(places):
        name = sh.NAMES[i]
        with st.container(border=True):
            st.markdown(f"**{name}**" + (f" · {sh.mix_text(slot['mix'])}"
                                          if slot and slot["mix"] else ""))
            nxt = sh.next_change(slot)
            unlocked = sh.can_change(slot, today)
            if slot and slot["mix"]:
                st.caption(sh.SLOT_SET.format(start=sh.date_text(slot["start"]),
                                              changed=sh.date_text(slot["changed"])) + " "
                           + (sh.SLOT_NOW if unlocked
                              else sh.SLOT_NEXT.format(next=sh.date_text(nxt))))
            elif slot:
                st.caption(sh.SLOT_EMPTY if unlocked
                           else sh.SLOT_EMPTY_LOCKED.format(next=sh.date_text(nxt)))
            else:
                st.caption(sh.SLOT_EMPTY)
            if editing == i and unlocked:
                _shadow_form(i, slot, today)
                continue
            c1, c2 = st.columns(2)
            if unlocked:
                label = sh.EDIT_LABEL if slot and slot["mix"] else sh.NEW_LABEL
                c1.button(label.format(name=name), key=f"shadow_open_{i}", type="tertiary",
                          on_click=_shadow_open, args=(i,))
            if slot and slot["mix"]:
                c2.button(sh.REMOVE_LABEL.format(name=name), key=f"shadow_remove_{i}",
                          type="tertiary", on_click=_shadow_remove, args=(i,),
                          help="Removing it doesn't let you set a new mix here any sooner.")


def _shadow_chart(rows):
    """One small chart, percentages only, neutral colours: your mix a solid
    line, the shadows grey dashes - nothing marks which is higher."""
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    palette = SERIES_DARK if st.context.theme.type == "dark" else SERIES_LIGHT
    names = [shadow_trail.REAL, *shadow_trail.NAMES]
    scale = alt.Scale(domain=names, range=[palette[0], SERIES_OTHER, SERIES_OTHER])
    dash = alt.Scale(domain=names, range=[[1, 0], [6, 3], [2, 2]])
    chart = (alt.Chart(df).mark_line(strokeWidth=2)
             .encode(x=alt.X("date:T", title=None),
                     y=alt.Y("pct:Q", title="Change (%)", scale=alt.Scale(zero=False)),
                     color=alt.Color("line:N", scale=scale, title=None,
                                     legend=alt.Legend(orient="bottom")),
                     strokeDash=alt.StrokeDash("line:N", scale=dash, legend=None),
                     tooltip=[alt.Tooltip("line:N", title="Path"),
                              alt.Tooltip("date:T", title="Date", format="%b %d, %Y"),
                              alt.Tooltip("pct:Q", title="Change (%)", format="+.1f")])
             .properties(height=220))
    st.altair_chart(chart, width="stretch")


@st.fragment
def _render_shadow_trail(today):
    """The Shadow Trail tab (shadow_trail.py): the places, then the paths -
    one small chart and a table, percentages only, labelled hypothetical."""
    if not _shadow_shown():
        return
    sh = shadow_trail
    st.markdown(f"#### {sh.TITLE}")
    st.info(sh.HYPOTHETICAL, icon=":material/route:")
    st.caption(sh.INTRO)
    p = _read_prefs()
    places = sh.slots(p)
    shadows = sh.active(p)
    if not shadows:
        st.markdown(sh.NONE_YET)
    _shadow_places(places, today)
    st.caption(sh.LOCK_LINE.format(months=sh.LOCK_MONTHS))
    if shadows:
        _shadow_paths(shadows, today)
    st.caption(sh.PROXY_LINE.format(proxies=", ".join(k["about"] for k in sh.KINDS
                                                      if k["proxy"])))
    st.caption(sh.KEPT_LINE)


def _shadow_paths(shadows, today):
    sh = shadow_trail
    first = min(s["changed"] for _, s in shadows)
    need = set().union(*(sh.proxies(s["mix"]) for _, s in shadows))
    prices = perf.adjusted_closes(DB, need, first)   # the stand-ins kept; nothing fetched
    values = _shadow_real(first)
    real = sh.real_path(values, first)
    lines, info = [], []
    for i, s in shadows:
        pts = sh.path(prices, s["mix"], s["changed"])
        lines.append((sh.NAMES[i], pts))
        info.append({"name": sh.NAMES[i], "mix": s["mix"], "changed": s["changed"],
                     "first": pts[0][0] if pts else s["changed"], "points": pts})
    if not any(pts for _, pts in lines):
        missing = any(not prices.get(t) for t in need)
        st.markdown(sh.NO_PRICES if missing else " ".join(
            sh.STARTS_SOON.format(name=n["name"], start=sh.date_text(n["changed"]))
            for n in info))
        return
    through = sh.last_day(real, *(pts for _, pts in lines if pts))
    _shadow_chart(sh.chart_rows(real, lines, through))
    st.caption(sh.CHART_NOTE.format(through=sh.date_text(through)))
    st.caption(sh.HYPOTHETICAL)
    cols = sh.TABLE_COLUMNS
    rows = [{cols[0]: r["name"], cols[1]: r["mix"], cols[2]: sh.date_text(r["since"]),
             cols[3]: sh.pct_text(r["shadow"]), cols[4]: sh.pct_text(r["real"])}
            for r in sh.table_rows(values, info, through)]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(sh.TABLE_NOTE)
    for n in info:
        if not n["points"]:
            st.caption(sh.STARTS_SOON.format(name=n["name"], start=sh.date_text(n["changed"])))
    if not real and PERF_BASIS[1]:
        st.caption(sh.NO_REAL)
    st.caption(sh.REAL_LINE)
