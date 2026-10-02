# Part of dashboard.py, which runs this file with _view("first_steps") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# First steps (ROADMAP S1): a new investor's start as a slideshow - one screen
# at a time, Back / Next and progress dots - instead of the whole Get started
# page at once. Welcome -> a few tap questions (the profile, two at a time) ->
# a goal -> their direction -> bring holdings in. Skippable and resumable
# (where they are is kept in their settings, so it follows them to another
# device); Get started shows the full page once it's done or skipped, with a
# way to go through it again.
# ruff: noqa: F821

# (key, title, profile fields asked on that screen)
FIRST_STEPS = (
    ("welcome", "Welcome", ()),
    ("why", "What it's for", ("goal", "time_horizon_years")),
    ("ups", "Ups and downs", ("risk_tolerance", "drawdown_reaction")),
    ("you", "A bit about you", ("experience", "age_range")),
    ("safety", "Your safety net", ("income_stability", "emergency_fund")),
    ("goal", "Your goal", ()),
    ("direction", "Your direction", ()),
    ("bring", "Bring it in", ()),
)
# a trusted, public place to read more about each screen's idea (learn.LEARN_MORE)
FIRST_STEPS_LINKS = {
    "ups": "risk_tolerance",
    "safety": "emergency_fund",
    "direction": "asset_allocation",
}


def _fs_state():
    return dict(_read_prefs().get("first_steps") or {})


def _fs_save(**changes):
    p = _read_prefs()
    p["first_steps"] = {**(p.get("first_steps") or {}), **changes}
    _write_prefs(p)


def _fs_steps():
    """The screens for this account: no goal screen when an advisor sets it,
    no bring-it-in screen when the advisor brings statements in."""
    return [s for s in FIRST_STEPS
            if not (s[0] == "goal" and not CAN_MANAGE)
            and not (s[0] == "bring" and not CAN_IMPORT)]


def first_steps_active(has_holdings):
    """Show the slideshow instead of Get started: an investor's own account
    that hasn't finished or skipped it, and still has something to do."""
    if IS_ADVISOR or USER_ID != LOGIN_ID or st.session_state.get("fs_hide"):
        return False
    s = _fs_state()
    if s.get("done") or s.get("skipped"):
        return False
    import advisor
    missing = advisor.missing_fields(_profile())   # read once per run (dashboard.py)
    return bool(missing) or not has_holdings


def _fs_save_answers(fields):
    """Save this screen's answers (only the ones given; nothing is cleared)."""
    import advisor
    got = {}
    for f in fields:
        v = st.session_state.get(f"fs_{f}")
        if isinstance(v, list):
            order = advisor.MULTI_CHOICES[f]
            v = advisor.MULTI_SEP.join(sorted(v, key=lambda x: order.index(x)
                                              if x in order else len(order)))
        if v not in (None, "", []):
            got[f] = v
    if got:
        c = connect(DB)
        try:
            advisor.save_profile(c, USER_ID, got)
        finally:
            c.close()


def _fs_save_goal():
    goal_type = st.session_state.get("fs_goal_type")
    target = st.session_state.get("fs_goal_target") or 0
    if not goal_type or target <= 0:
        return  # a goal is optional here; the Plan page asks again later
    years = int(st.session_state.get("fs_goal_years") or 10)
    when = plans.add_months(datetime.now().date(), 12 * years)
    save_plan_fields({"goal_type": goal_type, "target_amount": float(target),
                      "target_date": when.isoformat(),
                      "monthly_contribution": float(st.session_state.get("fs_goal_monthly") or 0)})


def _fs_move(i, delta):
    """Back / Next: keep what's on this screen, then move."""
    steps = _fs_steps()
    key, _, fields = steps[i]
    if delta > 0:
        if fields:
            _fs_save_answers(fields)
        elif key == "goal":
            _fs_save_goal()
    nxt = i + delta
    if nxt >= len(steps):
        _fs_save(done=True, step=0)
        st.session_state["page"] = "Get started"
        return
    _fs_save(step=max(nxt, 0))


def _fs_skip():
    _fs_save(skipped=True)


def _fs_finish(then=None):
    _fs_save(done=True, step=0)
    if then == "example":
        _load_sample()
        st.session_state["page"] = "Dashboard"   # straight to seeing it
    elif then in ("manual", "import"):
        _open_holdings_dialog(then)


def _fs_dots(i, n):
    dots = "".join(f"<span class='pt-fs-dot{' pt-fs-dot-on' if k <= i else ''}'></span>"
                   for k in range(n))
    st.html(f"<div class='pt-fs-dots' role='img' aria-label='Step {i + 1} of {n}'>{dots}</div>")


def _fs_question(field, profile):
    """One profile question as taps, prefilled with any saved answer."""
    import advisor
    q, cur = PROFILE_QUESTIONS[field], profile.get(field)
    key = f"fs_{field}"
    if field in advisor.MULTI_CHOICES:
        st.session_state.setdefault(key, advisor.split_multi(cur))
        st.pills(q, list(advisor.MULTI_CHOICES[field]), selection_mode="multi", key=key)
    elif field == "time_horizon_years":
        st.session_state.setdefault(key, int(cur) if cur else None)
        st.pills(q, list(HORIZON_YEARS), key=key,
                 format_func=lambda v: f"{v} year{'s' if v != 1 else ''}"
                 f"{'+' if v == HORIZON_YEARS[-1] else ''}")
    else:
        st.session_state.setdefault(key, cur or None)
        st.pills(q, list(advisor.CHOICES[field]), key=key,
                 format_func=lambda v: v[:1].upper() + v[1:])


def _fs_screen_goal(profile):
    import advisor
    plan = load_plan() or {}
    first = (advisor.split_multi(profile.get("goal")) or [None])[0]
    st.session_state.setdefault("fs_goal_type", plan.get("goal_type")
                                or _GOAL_FROM_PROFILE.get(first))
    st.session_state.setdefault("fs_goal_target", float(plan.get("target_amount") or 0.0))
    st.session_state.setdefault("fs_goal_years", int(profile.get("time_horizon_years") or 10))
    st.session_state.setdefault("fs_goal_monthly", float(plan.get("monthly_contribution") or 0))
    st.markdown("A rough goal is plenty - you can change it any time on the Plan page.")
    st.pills("What's the goal?", plans.GOAL_TYPES, key="fs_goal_type")
    c1, c2 = st.columns(2)
    c1.number_input("About how much you'll need ($)", min_value=0.0, step=1000.0,
                    format="%.0f", key="fs_goal_target")
    c2.number_input("In how many years?", min_value=1, max_value=60, step=1,
                    key="fs_goal_years")
    c1.number_input("What you might add each month ($)", min_value=0.0, step=50.0,
                    format="%.0f", key="fs_goal_monthly")
    st.caption("Not sure yet? Leave the amount at 0 and press Next.")


def _fs_screen_direction(profile):
    plan = load_plan()
    today = datetime.now().date()
    horizon = (plans.months_until(plan["target_date"], today) / 12
               if plans.has_goal(plan) and plans.months_until(plan["target_date"], today) > 0
               else None)
    mix = learn.starter_mix(profile, horizon)
    kind = learn.investor_type(profile, mix, learn.readiness(profile))
    if kind:
        _render_direction(kind, mix)
    else:
        st.markdown("Answer the questions on the earlier screens and this shows what kind of "
                    "investor you are, with an example mix that fits.")


def _fs_screen_bring():
    st.markdown("Last step: bring in what you own - from **any brokerage**, by pasting, a CSV, "
                "screenshots or typing it in. Or look around with an example portfolio first.")
    st.caption(":material/lock: " + TRUST_LINE)
    with st.container(horizontal=True):
        st.button(":material/content_paste: Paste or type", key="fs_manual", type="primary",
                  on_click=_fs_finish, args=("manual",))
        st.button(":material/upload_file: Upload a CSV", key="fs_import",
                  on_click=_fs_finish, args=("import",))
        st.button(":material/science: Try an example", key="fs_example",
                  on_click=_fs_finish, args=("example",))
    st.caption(f"Don't have an account yet? Finish here, and the {_label('Get started')} page "
               "walks you through opening one.")


def render_first_steps(has_holdings):
    steps = _fs_steps()
    i = min(int(_fs_state().get("step") or 0), len(steps) - 1)
    key, title, fields = steps[i]
    profile = _profile()   # read once per run (dashboard.py)
    _, mid, _ = st.columns([1, 3, 1])
    with mid:
        _fs_dots(i, len(steps))
        # a new key per screen, so each one slides in (the styles animate it)
        with st.container(border=True, key=f"pt_slide_{key}"):
            st.caption(f"Step {i + 1} of {len(steps)}")
            if key == "welcome":
                st.markdown(f"### Welcome to {APP_NAME}")
                st.markdown(f"{APP_NAME} is your guide from first step to goal. A few quick "
                            "questions - every answer a tap - and it shows what kind of investor "
                            "you are and a route to follow, one waypoint at a time.")
                st.markdown(":material/lock: **Private by design.** We never ask for your "
                            "brokerage login, and you can use percentages or an example "
                            "portfolio instead of real numbers.  \n"
                            ":material/school: **A guide, not a salesperson.** It explains and "
                            "shows examples; it never tells you what to buy, and has nothing to "
                            "sell you.")
            else:
                st.markdown(f"### {title}")
                if fields:
                    for f in fields:
                        _fs_question(f, profile)
                elif key == "goal":
                    _fs_screen_goal(profile)
                elif key == "direction":
                    _fs_screen_direction(profile)
                elif key == "bring":
                    _fs_screen_bring()
            if key in FIRST_STEPS_LINKS:
                learn_more(FIRST_STEPS_LINKS[key])
        with st.container(horizontal=True, vertical_alignment="center"):
            if i:
                st.button(":material/arrow_back: Back", key="fs_back", on_click=_fs_move,
                          args=(i, -1))
            st.button("Skip for now", key="fs_skip", type="tertiary", on_click=_fs_skip,
                      help=f"Go to the {_label('Get started')} page instead - it has "
                           "everything on one page, and you "
                           "can come back to these steps there.")
            st.space("stretch")
            last = i == len(steps) - 1
            st.button("Finish" if last else ("Let's go" if key == "welcome" else "Next"),
                      key="fs_next", type="secondary" if key == "bring" else "primary",
                      on_click=_fs_move, args=(i, 1))


def _fs_restart():
    _fs_save(done=False, skipped=False, step=0)
