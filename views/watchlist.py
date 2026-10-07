# Part of dashboard.py, which runs this file with _view("watchlist") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# The Watchlist page. Calm by default (ROADMAP S6): how many you watch and
# today's biggest moves, with the whole list in a window; the full list on the
# page for advisors and for Show everything (_show_everything).
# ruff: noqa: F821

import price_report

WATCH_CALM_ROWS = 5   # rows on the page in the calm view; the rest in a window


def _open_watch(sym):
    """A watchlist row: open (or close again) its chart and stats below."""
    st.session_state["holdings_pill"] = None
    st.session_state["watchlist_pill"] = None if st.session_state.get("watchlist_pill") == sym \
        else sym


def _open_watch_from_window(sym):
    """A row in the watchlist window: close the window, and open the ticker's
    chart and stats on the page (_watch_window sees the flag)."""
    st.session_state["holdings_pill"] = None
    st.session_state["watchlist_pill"] = sym
    st.session_state["watch_window_close"] = True


def _remove_watch(sym):
    c = connect(DB)
    try:
        watchlist.remove(c, USER_ID, sym)
    finally:
        c.close()
    if st.session_state.get("watchlist_pill") == sym:
        st.session_state["watchlist_pill"] = None


def _watch_quotes(symbols):
    c = connect(DB)
    try:
        return live_prices.quotes(c, symbols)
    finally:
        c.close()


def _render_watch_rows(symbols, q, in_window=False):
    """One row per watched ticker: symbol and name, the latest price and today's
    change - kept current by the live price updates - then open or remove.
    `q` is live_prices.quotes() for them."""
    w = "w_" if in_window else ""   # the window's rows can be drawn with the page's
    for sym in symbols:
        quote = q.get(sym) or {}
        name = (sec_info.get(sym) or {}).get("name") or ""
        price, chg, pct = quote.get("price"), quote.get("change"), quote.get("pct_change")
        with st.container(border=True, horizontal=True, vertical_alignment="center", gap="small",
                          key=f"wlrow_{w}{sym}"):
            st.button(f"**{sym}**", key=f"wl_{w}open_{sym}",
                      on_click=_open_watch_from_window if in_window else _open_watch,
                      args=(sym,),
                      type="primary" if st.session_state.get("watchlist_pill") == sym else "tertiary",
                      help="Show its chart and stats")
            st.html(f"<div class='pt-wl-name'>{html.escape(name)}</div>", width="stretch")
            if price:
                move = (_tone(chg, f"{'+' if chg >= 0 else '-'}{abs(chg):,.2f}"
                                   + (f" ({pct:+.2f}%)" if pct is not None else ""))
                        if chg is not None else "")
                # when the price is from (price_report.as_of: the quote's own
                # time, read with it - no extra query)
                asof = price_report.as_of(
                    quote.get("fetched_at"),
                    price_report.kind(sym, None, (sec_info.get(sym) or {}).get("quote_type")))
                # what the two numbers are, for screen readers ("Price 106.00, +3.00 today")
                st.html(f"<div class='pt-wl-quote'><span class='pt-sr'>Price </span>"
                        f"<b>{price:,.2f}</b><br>"
                        + (f"<span class='pt-sr'>, </span>{move}<span class='pt-sr'> today</span>"
                           if move else "")
                        + (f"<br><span class='pt-wl-asof'>as of {html.escape(asof['text'])}"
                           "</span>" if asof else "") + "</div>")
            else:
                st.html("<div class='pt-wl-quote pt-muted'>No price yet</div>")
            st.button(":material/close:", key=f"wl_{w}del_{sym}", type="tertiary",
                      on_click=_remove_watch, args=(sym,), help=f"Remove {sym} from your watchlist")


@st.dialog("Your watchlist", width="large", on_dismiss=_dialog_closed)
def _watch_window():
    if st.session_state.pop("watch_window_close", False):
        # a ticker was picked: close the window, its chart opens on the page
        _dialog_closed()
        st.rerun()
    c = connect(DB)
    try:   # read again: a removal here redraws only this window
        symbols = [t for t in watchlist.list_tickers(c, USER_ID) if t not in _held_symbols]
    finally:
        c.close()
    if not symbols:
        st.caption("Nothing on your watchlist now.")
        return
    st.caption("Prices update by themselves while the market is open. Tap a ticker for its "
               "chart and stats.")
    _render_watch_rows(symbols, _watch_quotes(symbols), in_window=True)


def _render_watch_calm(symbols):
    """How many, today's biggest rise and fall, and the biggest movers' rows;
    the whole list in a window."""
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
    shown = order[:WATCH_CALM_ROWS]
    st.caption(("Today's biggest moves. " if len(symbols) > len(shown) else "")
               + "Prices update by themselves while the market is open. Tap a ticker for its "
               "chart and stats.")
    _render_watch_rows(shown, q)
    if len(symbols) > len(shown):
        if st.button(f"See all {len(symbols)}", key="watch_open", type="tertiary",
                     icon=":material/open_in_new:"):
            _open_window(_watch_window)
        _calm_footer()


if PAGE == "Watchlist":
    # ---- watchlist: tickers tracked for their chart/stats, not owned ------- #
    if st.session_state.pop("watch_window_close", False):
        _dialog_closed()   # a pick in the window that this whole-page run closed
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
        st.caption("Prices update by themselves while the market is open. Tap a ticker for its "
                   "chart and stats.")
        _render_watch_rows(sorted(watch_only), _watch_quotes(watch_only))
    else:
        _render_watch_calm(sorted(watch_only))

    st.divider()
