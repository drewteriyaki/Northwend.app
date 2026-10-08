# Part of dashboard.py, which runs this file with _view("decoder_public") at
# the point where this code used to sit, in dashboard.py's own namespace: the
# names here (st, DB, connect, _visitor_ip, _show_signup...) are dashboard.py's,
# and what this defines is visible there afterwards. See _view() in dashboard.py.
#
# The 401(k) Menu Decoder without an account (master brief 8a; docs/PLAN.md
# step 3 item 6, decision B12; decoder_public.py), behind flag decoder_public
# and gate L0 (flags.FEATURES - this whole file is skipped while it's off).
# ?decode=401k opens it before sign-in, like the unsubscribe and reset links:
# the same paste box and table as the signed-in decoder (menu_decoder.py), in
# the pasted order, never sorted or ranked. No AI, no fetching - only the fund
# data already kept is read - and no Fund overlap button (it fetches). Nothing
# is kept: the pasted text and the table live only in this session. The one
# write is the rate-limit count per hashed address (decoder_public.take).
# Only after a table is shown, one calm line offers an account.
# ruff: noqa: F821

import decoder_public
import fees
import menu_decoder


def _decoder_public_wanted() -> bool:
    """Whether this visit asks for the decoder (?decode=401k)."""
    return decoder_public.wanted(st.query_params.to_dict())


def _dp_decode():
    """The Describe button (a callback): count it against the address's
    hourly limit, then decode what's pasted, in this session only."""
    text = st.session_state.get("dp_text") or ""
    st.session_state["dp_monthly_kept"] = st.session_state.get("dp_monthly")
    st.session_state.pop("dp_limited", None)
    st.session_state.pop("dp_result", None)
    if not text.strip():
        return
    try:
        c = connect(DB)
        try:
            limited = decoder_public.take(c, _visitor_ip())
            known = [] if limited else menu_decoder.known_funds(c)
        finally:
            c.close()
        if limited:
            st.session_state["dp_limited"] = limited
            return
        result = menu_decoder.decode(text, known)
    except Exception:   # never an error page for a paste: say it couldn't be read
        result = {"rows": [], "lines": 0, "identified": 0, "skipped": [],
                  "truncated": False, "failed": True}
    st.session_state["dp_result"] = result


def _dp_to_signup():
    """The account offer: Create account, in this same session. The pasted
    list goes along in memory only (the signed-in decoder's paste box)."""
    st.session_state["md_paste"] = st.session_state.get("dp_text") or ""
    if decoder_public.QUERY in st.query_params:
        del st.query_params[decoder_public.QUERY]
    _show_signup(True)


def _dp_esc(text):
    """Text for st.markdown: dollar signs aren't a formula."""
    return str(text).replace("$", r"\$")


def _dp_results(result, monthly) -> bool:
    """The table and its notes. True when a table was shown."""
    if result.get("failed"):
        st.markdown(":material/help: We couldn't read that list. Try pasting it again, one "
                    "fund per line.")
        return False
    if not result["rows"]:
        st.markdown(":material/help: We didn't find any fund names in what you pasted. Try "
                    "copying the list of funds again, one fund per line.")
        return False
    n, k = result["lines"], result["identified"]
    st.markdown(f"**We identified {k} of the {n} fund{'s' if n != 1 else ''} you pasted**, "
                "shown in the order you pasted them.")
    st.markdown(f":material/info: {menu_decoder.CALM}")
    st.table(pd.DataFrame(menu_decoder.table(result, monthly)).set_index("#"))
    if monthly and monthly > 0:
        st.caption(_dp_esc(
            f"How the dollars are worked out: {menu_decoder.fmt_dollars(monthly)} a month is "
            f"{menu_decoder.fmt_dollars(monthly * 12)} in a year, times the fund's yearly fee. "
            "It's a rough estimate of one year's fee on one year of contributions, as if all "
            "of it went into that one fund: money added during the year is invested for less "
            "than a full year, and growth isn't counted."))
    else:
        st.caption("Type what you put in each month to see each fee in dollars.")
    for r in result["rows"]:
        if r.get("data_fee") is not None:
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
    return True


def _decoder_public_page() -> bool:
    """The whole run for ?decode=401k without signing in. Always False."""
    _, mid, _ = st.columns([1, 4, 1])
    with mid:
        st.html(_brand_html("pt-brand-line"))
        st.title("Decode a 401(k) menu")
        st.markdown("Paste the list of funds from your workplace plan's enrolment page - one "
                    "fund per line, as it's shown there. You'll see what kind of fund each one "
                    "is and what it charges each year.")
        st.caption(":material/lock: No account needed. What you paste isn't saved and no AI "
                   "reads it - it stays in this visit only.")
        st.text_area("Your plan's fund list", key="dp_text", height=180,
                     max_chars=menu_decoder.MAX_CHARS, placeholder=menu_decoder.PLACEHOLDER)
        kw = {} if "dp_monthly" in st.session_state else {
            "value": st.session_state.get("dp_monthly_kept")}
        monthly = st.number_input("What you put in each month, in dollars (optional)",
                                  min_value=0.0, step=50.0, key="dp_monthly",
                                  placeholder="For example 300", **kw)
        st.button("Describe these funds", key="dp_go", type="primary", on_click=_dp_decode)
        limited = st.session_state.get("dp_limited")
        if limited:
            st.info(limited, icon=":material/schedule:")
        result = st.session_state.get("dp_result")
        if result is not None and _dp_results(result, monthly):
            # the one offer, only after a result
            with st.container(horizontal=True, vertical_alignment="center",
                              key="pt_decoder_offer"):
                st.markdown("Want to keep track of your plan?", width="content")
                st.button("Create a free account", key="dp_signup", type="tertiary",
                          on_click=_dp_to_signup)
        st.divider()
        st.caption(f"{APP_NAME} is an educational tool. This page describes funds - it isn't "
                   "financial advice, and nothing you paste is saved.")
    return False
