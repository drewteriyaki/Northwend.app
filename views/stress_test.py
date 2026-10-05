# Part of dashboard.py, which runs this file with _view("stress_test") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Stress test your mix (stress.py): the Plan page's "Stress test" tab - how the
# mix now, and the target mix if there is one, would have done in 2008, 2020
# and 2022: the drop at the low and roughly how long it took to get back.
# Asset classes only; hypothetical, with its assumptions stated.
# ruff: noqa: F821

import stress

STRESS_NOW, STRESS_TARGET = "Your mix now", "Your target mix"


def _stress_mix_text(mix, masked):
    parts = sorted(((k, v) for k, v in stress.clean(mix).items()), key=lambda kv: -kv[1])
    return ", ".join(f"{mask_or(f'{v:.0f}%') if masked else f'{v:.0f}%'} {k.lower()}"
                     for k, v in parts)


@st.fragment
def _render_stress_test(alloc_rows, value):
    """The Stress test tab. `alloc_rows` is the mix now (None without
    holdings); the target mix comes from the plan."""
    now = {r["label"]: r["pct"] or 0.0 for r in (alloc_rows or [])}
    target = load_alloc_targets()
    choices = [c for c, m in ((STRESS_NOW, now), (STRESS_TARGET, target)) if stress.clean(m)]
    if not choices:
        st.caption("Bring in your holdings or set a target mix to see how it would have done "
                   "in hard years.")
        return
    st.caption("Three hard stretches for markets, replayed on a mix of stocks, bonds and cash: "
               "how far it fell at the low, and roughly how long it took to get back. "
               "Hypothetical - the past won't repeat the same way.")
    pick = choices[0]
    if len(choices) > 1:
        pick = st.segmented_control("Which mix", choices, default=choices[0], key="stress_pick",
                                    label_visibility="collapsed") or choices[0]
    is_now = pick == STRESS_NOW
    mix = now if is_now else target
    pretend = SNAPSHOT_SOURCE == manual_entry.PCT_SOURCE
    # dollars on today's value - not for pretend dollars or without holdings
    base = value if value and not pretend else None
    # the mix now is the person's own: masked with amounts; a target is a plan
    masked = is_now
    st.markdown(f"**{pick}:** {_stress_mix_text(mix, masked)}")

    rows = stress.run(mix, base)
    out = ""
    for r in rows:
        held = r["drop_pct"] >= -0.05
        pct = (f"+{r['drop_pct']:.0f}%" if r["drop_pct"] > 0.5 else "about level") if held \
            else f"{r['drop_pct']:.0f}%"
        pct = mask_or(pct) if masked else pct
        usd = "" if r["drop_usd"] is None or held else fmt_money0(r["drop_usd"])
        if held:
            after = "It held its value through the drop."
        else:
            after = (f"Down for about {r['months_down']} month{'s' if r['months_down'] != 1 else ''}"
                     f", then back to where it started in {stress.time_text(r['months_back'])}.")
        out += ("<div class='pt-legend-row'>"
                f"<span class='pt-legend-label'><b>{html.escape(r['name'])}</b></span>"
                f"<span class='pt-legend-pct'>{html.escape(pct)}</span>"
                + (f"<span class='pt-legend-val'>{html.escape(usd)}</span>" if base else "")
                + "</div>"
                f"<div class='pt-goal-sub' style='margin:0 0 .6rem'>{html.escape(r['when'])} · "
                f"{html.escape(r['about'])} {html.escape(after)}</div>")
    st.html(f"<div class='pt-legend'>{out}</div>")
    if base:
        st.caption("The first figure is the drop from the high to the low; the second, the same "
                   "drop on today's value.")
    elif pretend:
        st.caption("Your dollar amounts are pretend, so this shows percentages only.")

    # the other mix, in one line, when both are there
    if len(choices) > 1:
        other = target if is_now else now
        w, wo = stress.worst(rows), stress.worst(stress.run(other))
        if w and wo and abs(w["drop_pct"] - wo["drop_pct"]) >= 1:
            name = "your target mix" if is_now else "your mix now"
            other_pct = f"{wo['drop_pct']:.0f}%"
            if not is_now:
                other_pct = mask_or(other_pct)
            st.caption(f"In {wo['key']}, {name} would have been about {other_pct} at the low.")
    with st.expander("How this is worked out"):
        st.caption(stress.ASSUMPTIONS)
        st.markdown("  \n".join(
            f"**{s['key']}:** " + ", ".join(f"{k.lower()} {v:+.0f}%" for k, v in s["drop"].items())
            for s in stress.SCENARIOS))
        st.caption("Each asset class's rough change from the stock market's high to its low.")
    learn_more("market_drops")
