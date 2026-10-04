""""What these kinds of funds look like": the example-funds card - general
education, the same for everyone.

Most simple portfolios are built from three kinds of funds (learn.BLOCKS):
a broad US stock index fund, a broad international stock index fund and a
broad US bond index fund. The card shows, for each kind, a few widely used,
low-cost index funds from different providers, so no one provider is
favoured and no single company's stock is named. It is never weighted by,
or tied to, the person's own answers or mix: named funds next to "your mix"
would read as a recommendation for them, which is advice, not education. It
always says the funds are examples of each kind to learn from, not
recommendations. How much goes in each kind is Learn's "An example mix",
which speaks in kinds of funds and percentages only.

card() is the pure part (tested); render() draws it with Streamlit on any
page: Learn the basics, Start investing's "Your first investments" and the
hand-entry window's "Not sure yet" tab. Never for an advisor's client
(CLIENT_MODE): their advisor recommends what to buy. Its two buttons add the
funds to the Watchlist and open Learn's practice-money waypoint.
"""

from __future__ import annotations

import learn

TITLE = "What these kinds of funds look like"
NOT_SURE = "You're not sure yet - that's normal."
INTRO = ("Most simple portfolios are built from three kinds of funds. Here are a few "
         "well-known examples of each kind, from several providers:")
FOOTER = ("These are examples of each kind, from several providers, to learn from - not "
          "recommendations. Many similar funds exist.")
MIX_NOTE = ("How much goes in each kind depends on your timeline and how you feel about ups "
            "and downs - Learn's *An example mix* shows a split in percentages.")

# The three kinds (learn.BLOCKS) and, for each, one broad index fund from each
# of three providers. Names as the providers give them; the yearly fee comes
# from the market data the app keeps.
PARTS = (
    {"key": "us", "label": "US stocks", "funds": ("VTI", "ITOT", "SCHB")},
    {"key": "intl", "label": "International stocks", "funds": ("VXUS", "IXUS", "SCHF")},
    {"key": "bonds", "label": "Bonds", "funds": ("BND", "AGG", "SCHZ")},
)
KIND = learn.KINDS   # {part key: "a broad US stock index fund", ...}
FUNDS = {
    "VTI": ("Vanguard", "Vanguard Total Stock Market ETF"),
    "ITOT": ("iShares", "iShares Core S&P Total U.S. Stock Market ETF"),
    "SCHB": ("Schwab", "Schwab U.S. Broad Market ETF"),
    "VXUS": ("Vanguard", "Vanguard Total International Stock ETF"),
    "IXUS": ("iShares", "iShares Core MSCI Total International Stock ETF"),
    "SCHF": ("Schwab", "Schwab International Equity ETF"),
    "BND": ("Vanguard", "Vanguard Total Bond Market ETF"),
    "AGG": ("iShares", "iShares Core U.S. Aggregate Bond ETF"),
    "SCHZ": ("Schwab", "Schwab U.S. Aggregate Bond ETF"),
}
ALL_FUNDS = tuple(t for p in PARTS for t in p["funds"])
PRACTICE_WAYPOINT = "practice"   # views/get_started.py's GET_STARTED_STEPS key


def fee_text(ratio) -> str | None:
    """A yearly fee (a fraction, as security_info keeps it) as "0.03% a year"."""
    if ratio is None:
        return None
    pct = f"{float(ratio) * 100:.3f}".rstrip("0").rstrip(".")
    return f"{pct}% a year"


def card(info: dict | None = None, *, not_sure: bool = False) -> dict:
    """The card's content: {"intro", "parts": [{key, label, kind, funds:
    [{symbol, provider, name, fee}]}], "note", "footer"}. The same for
    everyone - it takes no profile and no mix. `info` is {ticker: {"name",
    "expense_ratio"}} from security_info; `not_sure` opens with "You're not
    sure yet - that's normal." (the hand-entry window's tab)."""
    info = info or {}
    parts = []
    for p in PARTS:
        funds = []
        for t in p["funds"]:
            provider, name = FUNDS[t]
            got = info.get(t) or {}
            funds.append({"symbol": t, "provider": provider, "name": got.get("name") or name,
                          "fee": got.get("expense_ratio")})
        parts.append({"key": p["key"], "label": p["label"], "kind": KIND[p["key"]],
                      "funds": funds})
    return {"intro": f"{NOT_SURE} {INTRO}" if not_sure else INTRO, "parts": parts,
            "note": MIX_NOTE, "footer": FOOTER}


def fund_info(conn) -> dict:
    """{ticker: {"name", "expense_ratio"}} for the card's funds, from the
    market data the app keeps (whatever of it there is)."""
    ph = ",".join("?" * len(ALL_FUNDS))
    try:
        rows = conn.execute(f"SELECT ticker, name, expense_ratio FROM security_info "
                            f"WHERE ticker IN ({ph})", ALL_FUNDS).fetchall()
    except Exception:
        return {}
    return {r["ticker"]: {"name": r["name"], "expense_ratio": r["expense_ratio"]} for r in rows}


def open_practice(state) -> None:
    """Go to Learn's practice-money waypoint (`state`: st.session_state)."""
    state["page"] = "Get started"
    state["gs_at"] = PRACTICE_WAYPOINT
    state["fs_hide"] = True        # straight there, not the first-steps slideshow
    state["dialog_open"] = False   # leaving a window, if the card was in one


def render(*, db, user_id, key="starter", not_sure=False) -> None:
    """Draw the card with Streamlit: the three kinds with their examples,
    then "Add to my watchlist" and "Try them with practice money". Keys
    start with `key`."""
    import streamlit as st

    import watchlist
    from portfolio import connect

    conn = connect(db)
    try:
        c = card(fund_info(conn), not_sure=not_sure)
    finally:
        conn.close()
    ss = st.session_state
    with st.container(border=True, key=f"{key}_card"):
        st.markdown(f"**{c['intro']}**")
        for p in c["parts"]:
            with st.container(horizontal=True, gap="small", key=f"{key}_part_{p['key']}"):
                st.markdown(f"**{p['label']}**", width=190)
                st.markdown(f"{p['kind'][0].upper()}{p['kind'][1:]} - e.g. "
                            + ", ".join(f["symbol"] for f in p["funds"]), width="stretch")
            st.caption("  \n".join(
                f"{f['symbol']}: {f['name']}" + (f" - {fee_text(f['fee'])}" if f["fee"] is not None
                                                 else "")
                for f in p["funds"]).replace("$", r"\$"))
        st.caption(f":material/lightbulb: {c['note']}")
        st.markdown(c["footer"])
        with st.container(horizontal=True, gap="small"):
            watch = st.button("Add to my watchlist", key=f"{key}_watch",
                              icon=":material/visibility:")
            practice = st.button("Try them with practice money", key=f"{key}_practice",
                                 icon=":material/science:")
        if watch:
            conn = connect(db)
            try:
                added = [t for t in ALL_FUNDS if watchlist.add(conn, user_id, t)]
            finally:
                conn.close()
            st.success("Added " + ", ".join(added) + " to your Watchlist - follow their "
                       "prices there. Nothing is bought.")
        if practice:
            open_practice(ss)
            st.rerun()   # the whole app: a new page (and out of a window)
