# Part of dashboard.py, which runs this file with _view("menu_decoder") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# The 401(k) Menu Decoder (ROADMAP R5, menu_decoder.py), behind flag
# decoder_401k (flags.FEATURES - this whole file is skipped while it's off): a
# window where someone pastes their plan's fund list and sees, line by line in
# the order they pasted, what kind of fund each one is, its yearly fee and that
# fee in dollars at a monthly amount they type. Opened from a card beside the
# Free money check (views/free_money.py: Plan's Contributions tab and Learn's
# "Are you ready to invest?" step). No AI. Descriptive only: never sorted by
# fee, ranked or marked "best". Nothing is saved - the pasted text and the
# table live only in this session; the one thing kept is numbers for the R5
# metric (menu_decoder.add_counts, totals only via feature_counts.py). The
# optional overlap check reads and keeps funds' public top holdings like Home's
# Fund overlap (fund_holdings.py, shared market data, no user id).
# ruff: noqa: F821

import feature_counts
import fees
import fund_holdings
import menu_decoder

MD_CALM = menu_decoder.CALM
MD_PLACEHOLDER = menu_decoder.PLACEHOLDER


def _md_decode():
    """The Describe button (a callback, so it works whether the window redraws
    on its own or with the page): decode what's pasted into this session."""
    text = st.session_state.get("md_text") or ""
    st.session_state["md_paste"] = text
    st.session_state["md_monthly_kept"] = st.session_state.get("md_monthly")
    st.session_state.pop("md_overlap_result", None)
    if not text.strip():
        st.session_state.pop("md_result", None)
        return
    try:
        c = connect(DB)
        try:
            known = menu_decoder.known_funds(c)
        finally:
            c.close()
        result = menu_decoder.decode(text, known)
    except Exception:   # never an error page for a paste: say it couldn't be read
        result = {"rows": [], "lines": 0, "identified": 0, "skipped": [],
                  "truncated": False, "failed": True}
    st.session_state["md_result"] = result
    _md_count(text, result)
    _track("decoder_used", kind="menu_401k")   # app use (analytics.py): never the text


def _md_count(text, result):
    """R5's metric: this decode's numbers added to the person's own counts
    (no fund names, no text) - once per pasted text in a session, only on
    their own account, and not if they left themselves out of feature counts."""
    if not result.get("lines") or LOGIN_ID != USER_ID:
        return
    if st.session_state.get("md_counted") == text:
        return
    st.session_state["md_counted"] = text   # (this session only)
    saved = _read_prefs()
    if feature_counts.left_out(saved):
        return
    _write_prefs(menu_decoder.add_counts(saved, result))


def _md_overlap_fetch(funds):
    """Look up the identified funds' top holdings (fund_holdings: kept a week
    as shared market data) and describe which pairs share them."""
    try:
        c = connect(DB)
        try:
            tops, failed = fund_holdings.ensure(c, list(funds))
        finally:
            c.close()
    except Exception:
        tops, failed = {}, list(funds)
    order = {f: i for i, f in enumerate(funds)}
    pairs = [p for p in fund_holdings.overlaps(tops, funds) if p["n_shared"]]
    # in the pasted order, like the table - not by how much they share
    pairs.sort(key=lambda p: tuple(sorted((order[p["a"]], order[p["b"]]))))
    st.session_state["md_overlap_result"] = {
        "funds": tuple(funds),
        "lines": [fund_holdings.describe(p) for p in pairs],
        "failed": list(failed),
        "not_listed": [f for f in funds if f not in failed
                       and not (tops.get(f) or {}).get("holdings")],
        "compared": [f for f in funds if (tops.get(f) or {}).get("holdings")],
    }


def _md_esc(text):
    """Text for st.markdown: dollar signs aren't a formula."""
    return str(text).replace("$", r"\$")


@st.dialog("Decode a 401(k) menu", width="large", on_dismiss=_dialog_closed)
def _md_window():
    st.caption("Paste the list of funds from your workplace plan's enrolment page - one fund "
               "per line, as it's shown there. You'll see what kind of fund each one is and "
               "what it charges each year.")
    st.caption(":material/lock: What you paste isn't saved and no AI reads it - it stays in "
               "this visit only.")
    if "md_text" not in st.session_state:
        st.session_state["md_text"] = st.session_state.get("md_paste", "")
    st.text_area("Your plan's fund list", key="md_text", height=180,
                 placeholder=MD_PLACEHOLDER)
    kw = {} if "md_monthly" in st.session_state else {
        "value": st.session_state.get("md_monthly_kept")}
    monthly = st.number_input("What you put in each month, in dollars (optional)",
                              min_value=0.0, step=50.0, key="md_monthly",
                              placeholder="For example 300", **kw)
    st.button("Describe these funds", key="md_go", type="primary", on_click=_md_decode)
    result = st.session_state.get("md_result")
    if result is not None:
        _md_results(result, monthly)


def _md_results(result, monthly):
    if result.get("failed"):
        st.markdown(":material/help: We couldn't read that list. Try pasting it again, one "
                    "fund per line.")
        return
    if not result["rows"]:
        st.markdown(":material/help: We didn't find any fund names in what you pasted. Try "
                    "copying the list of funds again, one fund per line.")
        return
    n, k = result["lines"], result["identified"]
    st.markdown(f"**We identified {k} of the {n} fund{'s' if n != 1 else ''} you pasted**, "
                "shown in the order you pasted them.")
    st.markdown(f":material/info: {MD_CALM}")
    df = pd.DataFrame(menu_decoder.table(result, monthly)).set_index("#")
    st.table(df)
    show_dollars = bool(monthly) and monthly > 0
    if show_dollars:
        year = monthly * 12
        st.caption(_md_esc(
            f"How the dollars are worked out: {menu_decoder.fmt_dollars(monthly)} a month is "
            f"{menu_decoder.fmt_dollars(year)} in a year, times the fund's yearly fee. It's a "
            "rough estimate of one year's fee on one year of contributions, as if all of it "
            "went into that one fund: money added during the year is invested for less than "
            "a full year, and growth isn't counted."))
    else:
        st.caption("Type what you put in each month to see each fee in dollars.")
    differ = [r for r in result["rows"] if r.get("data_fee") is not None]
    for r in differ:
        st.caption(f"#{r['line']}: Yahoo Finance lists {fees.fmt_ratio(r['data_fee'])} for "
                   f"{r['symbol']}"
                   + (f" ({menu_decoder.fmt_day(r['fee_date'])})" if r["fee_date"] else "")
                   + " - the table shows the fee you pasted, which may be your plan's own.")
    missed = [r for r in result["rows"] if r["status"] == "unidentified"]
    if missed:
        st.caption("Not identified: " + "; ".join(
            f"#{r['line']} - {menu_decoder.WHY.get(r['why'], '')}" for r in missed)
            + ". We only name a fund when we're sure - a plan's own version (a trust, or "
              "another share class) can have a different fee.")
    if any(r["kind_from"] == "name" for r in result["rows"]):
        st.caption("\"Going by its name\" means the kind comes from words in the fund's name "
                   "only.")
    if result["skipped"]:
        st.caption("Not counted as funds (they look like headings): "
                   + ", ".join(result["skipped"]) + ".")
    if result.get("truncated"):
        st.caption(f"Only the first {menu_decoder.MAX_LINES} funds are shown.")
    st.caption("Fees from Yahoo Finance are for the fund with that ticker and can change. "
               "Your plan's fund fact sheet or fee disclosure has the fee that applies to you. "
               "What a fund holds, and the mix across all your funds, matter as much as any "
               "one fee.")
    kinds = menu_decoder.kinds_present(result)
    if kinds:
        with st.expander("What these kinds of funds are"):
            for kind in kinds:
                label, words = menu_decoder.KINDS[kind]
                st.markdown(f"**{label}** - {words}")
    learn_more("expense_ratios")
    funds = menu_decoder.overlap_funds(result)
    if len(funds) >= 2:
        _md_overlap(funds)


def _md_overlap(funds):
    st.button("Do these funds hold the same companies?", key="md_overlap", type="tertiary",
              icon=":material/join_inner:", on_click=_md_overlap_fetch, args=(tuple(funds),))
    got = st.session_state.get("md_overlap_result")
    if not got or got["funds"] != tuple(funds):
        return
    for line in got["lines"]:
        st.markdown(f"- {line}")
    if len(got["compared"]) >= 2 and not got["lines"]:
        st.markdown("- None of these funds share any of their largest holdings.")
    if got["failed"]:
        st.caption("We couldn't get the top holdings for " + ", ".join(got["failed"])
                   + " just now. Try again in a few minutes.")
    if got["not_listed"]:
        st.caption("Top holdings aren't available for " + ", ".join(got["not_listed"])
                   + " (often the case for bond funds and funds made of other funds).")
    st.caption(f"Based on each fund's top {fund_holdings.TOP_N} holdings from Yahoo Finance. "
               "Some overlap is normal, and this isn't a suggestion to choose or avoid any "
               "fund.")


def open_decoder_window():
    first_month_note("decoder")   # Your first month's step (views/first_month.py)
    st.session_state["dialog_open"] = True   # live prices wait (_dialog_closed)
    _md_window()


def render_decoder_card(where):
    """The one-line card that opens the window, beside the Free money check:
    `where` is "learn" or "plan" (the button's key)."""
    with st.container(border=True, horizontal=True, vertical_alignment="center",
                      key=f"pt_decoder_{where}"):
        st.markdown(":material/list_alt: **Decode a 401(k) menu** - paste your plan's list of "
                    "funds to see what kind each one is and what it charges.", width="stretch")
        if st.button("Decode", key=f"md_open_{where}", type="tertiary",
                     icon=":material/open_in_new:"):
            open_decoder_window()
