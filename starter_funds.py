""""Not sure what to start with": the example-funds card, for someone who
hasn't bought anything yet.

The card is education, not advice: it shows the person's own example mix
(learn.starter_mix - their time horizon and comfort with risk) split into
its three parts, and for each part a few widely used, low-cost index funds
from different providers, so no one provider is favoured and no single
company's stock is named. It always says the funds are examples to learn
from, not recommendations - the line that keeps it on the education side.

card() is the pure part (tested); render() draws it with Streamlit on any
page: the hand-entry window's "Not sure yet" tab today. Its two buttons add
the funds to the Watchlist and open Learn's practice-money waypoint.
"""

from __future__ import annotations

import learn

INTRO = "You're not sure yet - that's normal."
FOOTER = ("Broad, low-cost index funds like these are a common place to start. "
          "These are examples to learn from, not recommendations.")
NO_MIX = ("Answer a few questions on Learn (how long until you need the money, and how you "
          "feel about ups and downs) to see the split for you.")

# The parts of the example mix (learn.starter_mix's weights) and, for each,
# one broad index fund from each of three providers. Names as the providers
# give them; the yearly fee comes from the market data the app keeps.
PARTS = (
    {"key": "us", "label": "US stocks", "funds": ("VTI", "ITOT", "SCHB")},
    {"key": "intl", "label": "International", "funds": ("VXUS", "IXUS", "SCHF")},
    {"key": "bonds", "label": "Bonds", "funds": ("BND", "AGG", "SCHZ")},
)
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
_COUNT = {1: "one", 2: "two", 3: "three"}
PRACTICE_WAYPOINT = "practice"   # views/get_started.py's GET_STARTED_STEPS key


def fee_text(ratio) -> str | None:
    """A yearly fee (a fraction, as security_info keeps it) as "0.03% a year"."""
    if ratio is None:
        return None
    pct = f"{float(ratio) * 100:.3f}".rstrip("0").rstrip(".")
    return f"{pct}% a year"


def card(profile: dict | None, horizon_years: float | None = None,
         info: dict | None = None) -> dict:
    """The card's content: {"intro", "mix" (learn.starter_mix or None),
    "kind" (learn.investor_type or None), "parts": [{key, label, pct,
    funds: [{symbol, provider, name, fee}]}], "note", "footer"}. `info` is
    {ticker: {"name", "expense_ratio"}} from security_info."""
    profile = profile or {}
    info = info or {}
    mix = learn.starter_mix(profile, horizon_years)
    kind = learn.investor_type(profile, mix, learn.readiness(profile)) if mix else None
    parts = []
    for p in PARTS:
        pct = mix["weights"][p["key"]] if mix else None
        if mix and not pct:
            continue
        funds = []
        for t in p["funds"]:
            provider, name = FUNDS[t]
            got = info.get(t) or {}
            funds.append({"symbol": t, "provider": provider, "name": got.get("name") or name,
                          "fee": got.get("expense_ratio")})
        parts.append({"key": p["key"], "label": p["label"], "pct": pct, "funds": funds})
    n = _COUNT.get(len(parts), str(len(parts)))
    intro = f"{INTRO} {'Your' if mix else 'A simple'} example mix has {n} parts:"
    note = None
    if not mix:
        note = NO_MIX
    elif kind and kind["key"] in ("foundation", "short_term"):
        note = kind["about"]   # money needed soon, or a base to build first
    return {"intro": intro, "mix": mix, "kind": kind, "parts": parts, "note": note,
            "footer": FOOTER}


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


def render(profile, horizon_years, *, db, user_id, key="starter") -> None:
    """Draw the card with Streamlit: the parts, then "Add to my watchlist"
    and "Try them with practice money". Keys start with `key`."""
    import streamlit as st

    import watchlist
    from portfolio import connect

    conn = connect(db)
    try:
        c = card(profile, horizon_years, fund_info(conn))
    finally:
        conn.close()
    ss = st.session_state
    with st.container(border=True, key=f"{key}_card"):
        st.markdown(f"**{c['intro']}**")
        for p in c["parts"]:
            with st.container(horizontal=True, gap="small", key=f"{key}_part_{p['key']}"):
                st.markdown(f"**{p['label']}**" + (f" ({p['pct']}%)" if p["pct"] is not None
                                                   else ""), width=190)
                st.markdown("e.g. " + ", ".join(f["symbol"] for f in p["funds"]),
                            width="stretch")
            st.caption("  \n".join(
                f"{f['symbol']}: {f['name']}" + (f" - {fee_text(f['fee'])}" if f["fee"] is not None
                                                 else "")
                for f in p["funds"]).replace("$", r"\$"))
        if c["note"]:
            st.info(c["note"], icon=":material/lightbulb:")
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
