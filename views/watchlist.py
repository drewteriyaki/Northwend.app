# Part of dashboard.py, which runs this file with _view("watchlist") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# The Watchlist page.
# ruff: noqa: F821

def _open_watch(sym):
    """A watchlist row: open (or close again) its chart and stats below."""
    st.session_state["holdings_pill"] = None
    st.session_state["watchlist_pill"] = None if st.session_state.get("watchlist_pill") == sym \
        else sym


def _remove_watch(sym):
    c = connect(DB)
    try:
        watchlist.remove(c, USER_ID, sym)
    finally:
        c.close()
    if st.session_state.get("watchlist_pill") == sym:
        st.session_state["watchlist_pill"] = None


def _render_watch_rows(symbols):
    """One row per watched ticker: symbol and name, the latest price and today's
    change - kept current by the live price updates - then open or remove."""
    c = connect(DB)
    try:
        q = live_prices.quotes(c, symbols)
    finally:
        c.close()
    st.caption("Prices update by themselves while the market is open. Tap a ticker for its "
               "chart and stats.")
    for sym in symbols:
        quote = q.get(sym) or {}
        name = (sec_info.get(sym) or {}).get("name") or ""
        price, chg, pct = quote.get("price"), quote.get("change"), quote.get("pct_change")
        with st.container(border=True, horizontal=True, vertical_alignment="center", gap="small",
                          key=f"wlrow_{sym}"):
            st.button(f"**{sym}**", key=f"wl_open_{sym}", on_click=_open_watch, args=(sym,),
                      type="primary" if st.session_state.get("watchlist_pill") == sym else "tertiary",
                      help="Show its chart and stats")
            st.html(f"<div class='pt-wl-name'>{html.escape(name)}</div>", width="stretch")
            if price:
                move = (_tone(chg, f"{'+' if chg >= 0 else '-'}{abs(chg):,.2f}"
                                   + (f" ({pct:+.2f}%)" if pct is not None else ""))
                        if chg is not None else "")
                st.html(f"<div class='pt-wl-quote'><b>{price:,.2f}</b><br>{move}</div>")
            else:
                st.html("<div class='pt-wl-quote pt-muted'>No price yet</div>")
            st.button(":material/close:", key=f"wl_del_{sym}", type="tertiary",
                      on_click=_remove_watch, args=(sym,), help=f"Remove {sym} from your watchlist")


if PAGE == "Watchlist":
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
            st.session_state["import_flash"] = (f"You already own **{added}** - it's on your "
                                                "Dashboard with its chart and stats.")
            st.rerun()
        if added:
            st.session_state["import_flash"] = f"Added **{added}** to your watchlist."
            _wl_conn = connect(DB)
            try:  # its price now, rather than at the next minute's update
                live_prices.freshen(_wl_conn, USER_ID, resolve_key(None, ENV_PATH))
            except Exception:  # noqa: BLE001 - the next update will get it
                pass
            finally:
                _wl_conn.close()
            _sync_history([added], quick=True)  # its chart data (reruns the page)
        else:
            st.session_state["refresh_msg"] = ("error", f"'{_wl_raw}' doesn't look like a valid ticker.")
        st.rerun()

    if not watch_only:
        st.caption("Nothing on your watchlist yet — add a ticker above to follow its price and chart "
                   "without owning it.")
    else:
        _render_watch_rows(sorted(watch_only))

    st.divider()
