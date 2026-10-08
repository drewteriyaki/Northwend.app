# Part of dashboard.py, which runs this file with _view("watchlist") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# The Watchlist page. One table, as Home's holdings: a row per ticker with its
# name, the past month's mini chart, the price, today's change and when the
# price is from; tapping a row opens the ticker's own page
# (dashboard._ticker_table, views/ticker_detail.py). Calm by default (ROADMAP
# S6): how many you watch and today's biggest moves, the biggest movers' rows
# first and "Show all" opening the rest in place; every row at once for
# advisors and for Show everything (_show_everything).
# ruff: noqa: F821

import price_report

WATCH_CALM_ROWS = 5   # rows shown at first in the calm view; Show all opens the rest
WATCH_COLS = ("Ticker", "Name", SPARK_LABEL, "Price", "Today", "As of")


def _remove_watch():
    sym = st.session_state.get("wl_remove_pick")
    if not sym:
        return
    c = connect(DB)
    try:
        watchlist.remove(c, USER_ID, sym)
    finally:
        c.close()
    st.session_state["import_flash"] = f"Took **{sym}** off your watchlist."


def _watch_quotes(symbols):
    c = connect(DB)
    try:
        return live_prices.quotes(c, symbols)
    finally:
        c.close()


def _watch_frame(symbols, q):
    """The rows: ticker, name, the mini chart, the latest price and today's
    change (signed, colored by direction) - kept current by the live price
    updates - and when the price is from (price_report.as_of: the quote's own
    time, read with it - no extra query)."""
    rows, moves = [], []
    for sym in symbols:
        quote = q.get(sym) or {}
        price, chg, pct = quote.get("price"), quote.get("change"), quote.get("pct_change")
        asof = price_report.as_of(
            quote.get("fetched_at"),
            price_report.kind(sym, None, (sec_info.get(sym) or {}).get("quote_type"))) \
            if price else None
        rows.append({"Ticker": sym, "Name": (sec_info.get(sym) or {}).get("name") or "",
                     SPARK_LABEL: _spark(sym),
                     "Price": f"{price:,.2f}" if price else "No price yet",
                     "Today": (f"{'+' if chg >= 0 else '-'}{abs(chg):,.2f}"
                               + (f" ({pct:+.2f}%)" if pct is not None else ""))
                     if price and chg is not None else "—",
                     "As of": asof["text"] if asof else "—"})
        moves.append(chg if price else None)
    frame = pd.DataFrame(rows, columns=list(WATCH_COLS))
    return frame.style.apply(lambda col: [color_sign(v) for v in moves], subset=["Today"])


def _render_watch_table(symbols, q):
    _ticker_table("watch_table", _watch_frame(symbols, q), symbols, "Watchlist",
                  column_config={
                      "Ticker": st.column_config.TextColumn("Ticker", pinned=True),
                      "Price": st.column_config.TextColumn("Price", alignment="right"),
                      "Today": st.column_config.TextColumn("Today", alignment="right"),
                      "As of": st.column_config.TextColumn("As of", alignment="right")},
                  alt="Your watchlist: each ticker's name, past month, price and today's "
                      "change. Select a row to open that ticker's page.")


def _render_watch_remove(symbols):
    with st.popover("Remove a ticker", icon=":material/remove:", type="tertiary",
                    key="pt_wl_remove"):
        st.selectbox("Ticker to take off your watchlist", symbols, key="wl_remove_pick")
        st.button("Remove", key="wl_remove_btn", on_click=_remove_watch)


def _render_watch_calm(symbols):
    """How many, today's biggest rise and fall, and the biggest movers' rows
    first; Show all opens every row in place."""
    q = _watch_quotes(symbols)
    moves = sorted(((q.get(s) or {}).get("pct_change"), s) for s in symbols
                   if (q.get(s) or {}).get("pct_change") is not None)
    stats = [("Watching", str(len(symbols)),
              "ticker" + ("s" if len(symbols) != 1 else "") + " you don't own")]
    up = [m for m in moves if m[0] > 0]
    down = [m for m in moves if m[0] < 0]
    stats.append(("Biggest rise today", html.escape(up[-1][1]) if up else "—",
                  _tone(up[-1][0], f"{up[-1][0]:+.2f}%") if up else None))
    stats.append(("Biggest fall today", html.escape(down[0][1]) if down else "—",
                  _tone(down[0][0], f"{down[0][0]:+.2f}%") if down else None))
    _summary_stats(stats)
    # the biggest moves first, then the rest alphabetically
    order = sorted(symbols, key=lambda s: (-abs((q.get(s) or {}).get("pct_change") or 0.0), s))
    cut = len(symbols) > WATCH_CALM_ROWS and not st.session_state.get("watch_all")
    shown = order[:WATCH_CALM_ROWS] if cut else order
    st.caption(("Today's biggest moves. " if cut else "")
               + "Prices update by themselves while the market is open. Tap a row for the "
               "ticker's chart and details.")
    _render_watch_table(shown, q)
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        if len(symbols) > WATCH_CALM_ROWS:
            _show_all_toggle("watch_all", len(symbols), "tickers")
        _render_watch_remove(symbols)
    if len(symbols) > WATCH_CALM_ROWS:
        _calm_footer()


if PAGE == "Watchlist":
    with _page_main():   # Money's main card (dashboard._money_parts)
        # ---- watchlist: tickers tracked for their chart/stats, not owned ------- #
        with st.form("wl_add_form", clear_on_submit=True, border=False):  # Enter adds it too
            wc1, wc2 = st.columns([0.75, 0.25], vertical_alignment="bottom")
            _wl_raw = wc1.text_input("Add a ticker", key="wl_add_input",
                                     placeholder="Add a ticker, e.g. NVDA", label_visibility="collapsed")
            _wl_go = wc2.form_submit_button("+ Add to watchlist", width="stretch")
        if _wl_go and _wl_raw.strip():
            _wl_conn = connect(DB)
            try:
                added = watchlist.add(_wl_conn, USER_ID, _wl_raw)
            finally:
                _wl_conn.close()
            if added and added in _held_symbols:
                st.session_state["import_flash"] = (f"You already own **{added}** - it's on "
                                                    f"{_label('Dashboard')} with its chart and stats.")
                st.rerun()
            if added:
                st.session_state["import_flash"] = f"Added **{added}** to your watchlist."
                try:  # its price now, rather than at the next minute's update
                    live_prices.freshen(lambda: connect(DB), USER_ID, resolve_key(None, ENV_PATH))
                except Exception:  # noqa: BLE001 - the next update will get it
                    pass
                _sync_history([added], quick=True)  # its chart data (reruns the page)
            else:
                st.session_state["refresh_msg"] = ("error", f"'{_wl_raw}' doesn't look like a valid ticker.")
            st.rerun()

        if not watch_only:
            st.caption("Nothing on your watchlist yet — add a ticker above to follow its price and chart "
                       "without owning it.")
        elif _show_everything():
            st.caption("Prices update by themselves while the market is open. Tap a row for the "
                       "ticker's chart and details.")
            _render_watch_table(sorted(watch_only), _watch_quotes(watch_only))
            _render_watch_remove(sorted(watch_only))
        else:
            _render_watch_calm(sorted(watch_only))
