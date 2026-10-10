# Part of dashboard.py, which runs this file with _view("factsheet_decoder") at
# the point where this code used to sit, in dashboard.py's own namespace: the
# names here (st, pd, learn_more, _dialog_closed...) are dashboard.py's, and
# what this defines is visible there afterwards. See _view() in dashboard.py.
#
# The Fact Sheet Decoder (ROADMAP R6, fact sheets first; factsheet_decoder.py),
# behind flag decoder_factsheet (flags.FEATURES - this whole file is skipped
# while it's off): a window where someone pastes the text of a fund's fact
# sheet and sees, row by row, what it says in plain words - name, ticker,
# yearly fee (and that fee in dollars at a monthly amount they type), index or
# active, asset class, top holdings share, number of holdings, inception date,
# benchmark - each with a "what this means" line, and "couldn't find" where
# the sheet doesn't say. Opened from a card beside the Free money check (Plan's
# Contributions tab, Learn's "Are you ready to invest?" step). Signed in only
# (no ?decode= version yet). No AI, no PDF reading yet (paste only: a PDF
# reader would be a new dependency). Descriptive only: never rates or ranks.
#
# Statements are not read: text that looks like one (an account number, an
# account value or balance, a name and address) is stopped before anything is
# read from it, the box is cleared and the window says so calmly. Nothing is
# saved anywhere - the pasted text and the table live only in this session.
# ruff: noqa: F821

import factsheet_decoder


def _fs_decode():
    """The Describe button (a callback, so it works whether the window redraws
    on its own or with the page): read what's pasted, in this session only."""
    text = st.session_state.get("fs_text") or ""
    st.session_state["fs_monthly_kept"] = st.session_state.get("fs_monthly")
    if not text.strip():
        st.session_state.pop("fs_result", None)
        st.session_state["fs_paste"] = ""
        return
    try:
        result = factsheet_decoder.decode(text)
    except Exception:   # never an error page for a paste: say it couldn't be read
        result = {"statement": [], "failed": True}
    if result.get("statement"):
        # a statement: nothing from it stays - not the box, not the result
        st.session_state["fs_text"] = ""
        st.session_state["fs_paste"] = ""
    else:
        st.session_state["fs_paste"] = text
    st.session_state["fs_result"] = result


def _fs_esc(text):
    """Text for st.markdown: dollar signs aren't a formula."""
    return str(text).replace("$", r"\$")


@st.dialog("Read a fund fact sheet", width="large", on_dismiss=_dialog_closed)
def _fs_window():
    st.caption("A fact sheet is the one- or two-page summary a fund company publishes about "
               "a fund. Open it (often a PDF on the fund's page), select all the text, copy it "
               "and paste it here. You'll see what it says, in plain words.")
    st.caption(":material/lock: What you paste isn't saved and no AI reads it - it stays in "
               "this visit only. Fact sheets only for now: account statements aren't read yet.")
    if "fs_text" not in st.session_state:
        st.session_state["fs_text"] = st.session_state.get("fs_paste", "")
    st.text_area("The fact sheet's text", key="fs_text", height=180,
                 max_chars=factsheet_decoder.MAX_CHARS,
                 placeholder=factsheet_decoder.PLACEHOLDER)
    kw = {} if "fs_monthly" in st.session_state else {
        "value": st.session_state.get("fs_monthly_kept")}
    monthly = st.number_input("What you put in each month, in dollars (optional)",
                              min_value=0.0, step=50.0, key="fs_monthly",
                              placeholder="For example 300", **kw)
    st.button("Describe this fund", key="fs_go", type="primary", on_click=_fs_decode)
    result = st.session_state.get("fs_result")
    if result is not None:
        _fs_results(result, monthly)


def _fs_results(result, monthly):
    if result.get("statement"):
        st.markdown(":material/lock: " + factsheet_decoder.STATEMENT_NOTE)
        st.caption("What made it look like a statement: "
                   + factsheet_decoder.statement_signs_text(result["statement"])
                   + ". A fund's fact sheet is usually on the fund company's website, on the "
                     "fund's own page, or in your plan's materials.")
        return
    if result.get("failed"):
        st.markdown(":material/help: We couldn't read that text. Try copying the fact sheet "
                    "again and pasting it here.")
        return
    if not result.get("found"):
        st.markdown(":material/help: We didn't find a fund's details in what you pasted. Try "
                    "copying all the text of the fact sheet, then paste it again.")
        return
    st.markdown("**Here's what the fact sheet says**, in plain words.")
    st.markdown(f":material/info: {factsheet_decoder.CALM}")
    rows = factsheet_decoder.rows(result, monthly)
    st.table(pd.DataFrame(rows).set_index("What"))
    if monthly and monthly > 0 and result.get("fee") is not None:
        st.caption(_fs_esc(
            "How the dollars are worked out: what you put in each month, times 12, times the "
            "yearly fee. It's a rough estimate of one year's fee on one year of contributions: "
            "money added during the year is invested for less than a full year, and growth "
            "isn't counted."))
    elif result.get("fee") is not None:
        st.caption("Type what you put in each month to see the fee in dollars.")
    if any(r["As the fact sheet states it"] == factsheet_decoder.NOT_FOUND for r in rows):
        st.caption("\"Couldn't find\" means we didn't see it in the text you pasted - it may be "
                   "on the sheet in a form we don't read yet, so the sheet itself is the place "
                   "to check.")
    if result.get("truncated"):
        st.caption("That was longer than a fact sheet usually is, so only the first part was "
                   "read.")
    st.caption("A fact sheet is a snapshot on its own date: fees, holdings and figures change. "
               "The fund's prospectus has the full details. What a fund holds, and the mix "
               "across all your funds, matter as much as any one number here.")
    learn_more("expense_ratios")


def open_factsheet_window():
    first_month_note("factsheet")   # Your first month's step (views/first_month.py)
    st.session_state["dialog_open"] = True   # live prices wait (_dialog_closed)
    _fs_window()


def render_factsheet_card(where):
    """The one-line card that opens the window, beside the Free money check:
    `where` is "learn" or "plan" (the button's key)."""
    with st.container(border=True, horizontal=True, vertical_alignment="center",
                      key=f"pt_factsheet_{where}"):
        st.markdown(":material/description: **Read a fund fact sheet** - paste one to see "
                    "what the fund is, what it charges and what it holds, in plain words.",
                    width="stretch")
        if st.button("Read", key=f"fs_open_{where}", type="tertiary",
                     icon=":material/open_in_new:"):
            open_factsheet_window()
