# Part of dashboard.py, which runs this file with _view("life") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# The Life page: the paperwork side of money, in one place - a row of cards
# (the account map, Lost & Found, Explain it to someone, Doing it together)
# that jump to their sections, Trail Forks (life changes), the Inheritance
# Rehearsal, and then those sections themselves. Every section keeps its own flag and its own
# rules: each draws only the login's own (LOGIN_ID), never while an advisor
# is in a client's account (views/account_map.py, lost_found.py,
# trail_forks.py, inheritance_rehearsal.py, explain_share.py decide). Life is
# in everyone's menu (PAGES, NAV) - an advisor's only while they're on their
# own portfolio, never in a client's account; Account just points here.
# ruff: noqa: F821

LIFE_INTRO = ("The paperwork side of money: where things are, what to do when life changes, "
              "and how to explain your plan to someone. Only you see what you keep here.")
# the cards along the top: (key, small heading, title, one line, link words, the section's anchor)
LIFE_CARDS = (
    ("account_map", "Your records", "Account map",
     "A list of your accounts for the people you trust: who to call and where the paperwork "
     "is.", "Open", "account-map"),
    ("lost_found", "Your records", "Lost & Found",
     "The official places to look for an old 401(k) or money a state is holding for you.",
     "Open", "lost-and-found"),
    ("explain_share", "Sharing", "Explain it to someone",
     "A private link that shows someone your plan in plain words, with percentages only.",
     "Make a link", "explain-it"),
    ("together", "Sharing", "Doing it together",
     "Pair up with someone and see each other's habits - never amounts or holdings.",
     "Open", "together"),
)


def _life_cards_shown():
    """The cards whose section this login sees here: the account map always
    (the login's own), Lost & Found with its flag, Explain it to someone where
    the login may share (_xs_own: its flag, their own account, not a managed
    client or an admin)."""
    shown = {"account_map": USER_ID == LOGIN_ID,
             "lost_found": flags.on("lost_found") and USER_ID == LOGIN_ID,
             "explain_share": flags.on("explain_share") and _xs_own(),
             "together": flags.on("together") and _tg_own()}
    return [c for c in LIFE_CARDS if shown[c[0]]]


def _render_life_sections():
    """The sections themselves, in the order their words expect: Trail Forks,
    then the Inheritance Rehearsal ("Trail Forks, just above"), then the
    account map, Lost & Found ("the account map above") and Explain it to
    someone. Each checks its own flag and whose account it is."""
    if flags.on("trail_forks"):
        render_trail_forks()
    if flags.on("inheritance_rehearsal"):
        render_inheritance_rehearsal()
    render_account_map()
    if flags.on("lost_found"):
        render_lost_found()
    if flags.on("explain_share"):
        render_explain_share()
    if flags.on("together"):   # Doing it together (views/together.py)
        render_together()


def _render_life():
    # Style C (dashboard.py's pt_page_layout): the intro is on the
    # slim band under the title (_slim_band_line), then one column of white
    # cards - no right-hand panel on Life
    with st.container(key="pt_page_layout"), st.container(key="pt_page_main"):
        if flags.on("together"):   # a Doing it together link just opened: answered first
            render_together_invite()
        cards = _life_cards_shown()
        if cards:
            cols = st.columns(len(cards))
            for col, (key, small, title, line, go, anchor) in zip(cols, cards):
                with col, st.container(border=True, height="stretch", key=f"pt_life_{key}"):
                    st.html(f"<div class='pt-life-small'>{html.escape(small)}</div>"
                            f"<div class='pt-life-title'>{html.escape(title)}</div>")
                    st.caption(line)
                    st.markdown(f"[{go}](#{anchor})")
        _render_life_sections()
