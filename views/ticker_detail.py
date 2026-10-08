# Part of dashboard.py, which runs this file with _view("ticker_detail") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# One ticker's own page (TICKER_PAGE, ?page=ticker&t=VTI), opened from a row of
# Home's holdings or the Watchlist (dashboard._ticker_table): on the slim band
# the ticker, its name and Back; then cards - the price and its chart, your
# position (or the watchlist note), the stats (with the upcoming dividend and
# earnings dates, if announced) and the news.
# ruff: noqa: F821

import math

import fees
import price_report
from weekly import parse_day as weekly_parse_day


def _send_price_report(sym, price, price_at):
    """Price look wrong? > Send: one row in price_reports for this login
    (price_report.report - limits there), then the calm thank-you."""
    ss = st.session_state
    reason = ss.get(f"price_report_reason_{sym}")
    c = connect(DB)
    try:
        res = price_report.report(c, LOGIN_ID, sym, reason, price=price, price_as_of=price_at)
    finally:
        c.close()
    ss[f"price_report_msg_{sym}"] = res["message"]
    # sent, or a limit reached: the calm line in its place for this visit
    ss[f"price_report_done_{sym}"] = res["ok"] or reason in price_report.REASONS


def _render_price_report(sym, price, price_at):
    """"Price look wrong?" under a ticker's price (flag price_report): fixed
    reasons only, nothing typed. Nothing is read while it's drawn - the
    limits are checked when Send is tapped."""
    ss = st.session_state
    msg = ss.get(f"price_report_msg_{sym}")
    if ss.get(f"price_report_done_{sym}"):
        st.caption(msg)
        return
    with st.popover("Price look wrong?", type="tertiary", icon=":material/flag:",
                    key=f"price_report_open_{sym}"):
        st.radio("What looks wrong?", list(price_report.REASONS),
                 format_func=price_report.REASONS.get, index=None,
                 key=f"price_report_reason_{sym}")
        st.button("Send", key=f"price_report_send_{sym}", on_click=_send_price_report,
                  args=(sym, price, price_at))
        if msg:
            st.caption(msg)
        st.caption("Northwend keeps the ticker, the reason you pick and the price you saw, "
                   "with your account - nothing else.")


def _ticker_learn_more(sym, pos):
    """One quiet Learn more under a fund's or bond's name: how bonds work for
    something that's mostly bonds (BND, a single bond), ETFs and mutual funds
    for any other fund. Nothing for a single stock."""
    info = sec_info.get(sym) or {}
    split, _ = asset_classes.split_for(sym, pos.get("asset_type"), info, CLASS_OVERRIDES)
    if asset_classes.main_class(split) == "Bonds":
        learn_more("bonds")
    elif fees.holding_type(info.get("quote_type"), pos.get("asset_type")) == "fund":
        learn_more("etfs")


def _tk_source(source):
    if source == dividend_dates.BROKER and snapshot:
        return f"From your brokerage's file of {_fmt_date(snapshot)}"
    return dividend_dates.SOURCE_WORDS.get(source, "")


def _render_ticker_dates(sym, pos):
    """Upcoming dates (dividend_dates.py): the next ex-dividend and pay date
    and the amount a share if announced, and for a stock its next earnings
    date - each with where it came from, never estimated. Reads nothing more
    (DIV_EVENTS and sec_info came with the page's market data)."""
    info = sec_info.get(sym) or {}
    today = dividend_dates.today()
    nxt = dividend_dates.next_for(DIV_EVENTS, info, sym, today)
    if not nxt["source"]:   # the brokerage file's pay date, as before
        pay = weekly_parse_day(pos.get("div_pay_date"))
        if pay and pay >= today:
            nxt.update(pay=pay, source=dividend_dates.BROKER)
    st.markdown("##### Upcoming dates")
    if nxt["source"]:
        bits = []
        if nxt["ex"]:
            bits.append(f"ex-dividend **{_fmt_date(nxt['ex'])}**")
        if nxt["pay"]:
            bits.append(f"paid **{_fmt_date(nxt['pay'])}**")
        if nxt["amount"] is not None:
            bits.append(f"{fmt_price(nxt['amount'])} a share".replace("$", "\\$"))
        lines = ["Next dividend: " + ", ".join(bits) + f" ({_tk_source(nxt['source'])})"]
    else:
        lines = [f"Next dividend: {dividend_dates.NONE_YET}."]
    if fees.holding_type(info.get("quote_type"), pos.get("asset_type")) == "stock":
        earn, src = nxt["earnings"], nxt["earnings_source"]
        if not earn:
            earn = weekly_parse_day(pos.get("next_earnings_date"))
            earn, src = (earn, dividend_dates.BROKER) if earn and earn >= today else (None, None)
        lines.append(f"Next earnings report: **{_fmt_date(earn)}** ({_tk_source(src)})" if earn
                     else f"Next earnings report: {dividend_dates.NONE_YET}.")
    st.markdown("  \n".join(lines))
    st.caption("Only dates already announced - none are worked out from past payments. "
               "Companies and funds sometimes move them.")


def _remove_from_watchlist(sym):
    """The watchlist note's Remove: off the list, and back to the Watchlist."""
    _wl_conn = connect(DB)
    try:
        watchlist.remove(_wl_conn, USER_ID, sym)
    finally:
        _wl_conn.close()
    st.session_state.pop("ticker_sym", None)
    _go(st.session_state.get("ticker_from") or "Watchlist")


def _tk_full_name(*names):
    """The longest of a holding's names (the brokerage's description, Yahoo's
    name) - one may be cut short at the source."""
    names = [str(n).strip() for n in names if n and str(n).strip()]
    return max(names, key=len) if names else ""


# a ticker's stats in plain words, each with a short explanation (its ⓘ)
TK_STATS = (
    ("prev_close", "Yesterday's closing price", None),
    ("day_open", "Today's opening price", None),
    ("day_high", "Today's high", None),
    ("day_low", "Today's low", None),
    ("week52_high", "Highest price in the past year", None),
    ("week52_low", "Lowest price in the past year", None),
    ("pct_off_52wk_high", "Below the past year's high",
     "How far today's price is under the highest price of the past 52 weeks."),
    ("volume", "Shares traded (latest day)", None),
    ("avg_volume", "Shares traded on an average day", None),
    ("beta", "How much it moves vs the market (beta)",
     "About 1 means it has tended to move up and down about as much as the market as a "
     "whole; above 1, more; below 1, less. It looks back, not ahead."),
    ("pe_ttm", "Price to earnings (P/E)",
     "The share price divided by the company's profit per share over the past 12 months - "
     "one way to compare a price with what the company earns."),
    ("pb_ratio", "Price to book value (P/B)",
     "The share price compared with what the company owns minus what it owes, per share, "
     "as its accounts show it."),
    ("market_cap", "Company size (market value)",
     "All of the company's shares together, at today's price."),
    ("sector", "Sector", "The part of the economy the company is in."),
    ("ma_20", "20-day average price",
     "The average closing price over the last 20 trading days - it smooths out daily moves."),
    ("ma_50", "50-day average price", "The average closing price over the last 50 trading days."),
    ("ma_200", "200-day average price",
     "The average closing price over the last 200 trading days, about ten months."),
    ("price_vs_ma50", "Price vs its 50-day average",
     "How far today's price is above or below its 50-day average price."),
    ("div_yield_pct", "Dividend yield", "A year's dividends as a percentage of today's price."),
    ("div_pay_date", "Dividend pay date", None),
    ("reinvest", "Dividends reinvested", "Whether your brokerage buys more shares with the "
                                         "dividends this holding pays."),
    ("next_earnings", "Next earnings date", None),
)
# a company's own figures: for a fund they're left out, not "not available"
TK_COMPANY_ONLY = ("pe_ttm", "pb_ratio", "market_cap", "sector", "next_earnings")


def _ticker_context(sym):
    """(position, metric context, held?) for `sym`: the holding's own, or a
    position-less one for a watched ticker (the metrics read through
    ctx.get(...), so a missing "pos" field just reads as None)."""
    idx = next((i for i, p in enumerate(positions) if p["symbol"] == sym), None)
    if idx is not None:
        return positions[idx], contexts[idx], True
    pos = {"symbol": sym, "description": sec_info.get(sym, {}).get("name")}
    ctx = {"pos": pos, "quote": quotes.get(sym, {}), "stats": bar_stats.get(sym, {}),
           "info": sec_info.get(sym, {}), "port_value": portfolio_value, "acct_value": None}
    return pos, ctx, False


if PAGE == TICKER_PAGE:
    _sym = st.session_state["ticker_sym"]
    _pos, _ctx, _is_held = _ticker_context(_sym)
    _has_yahoo = perf.ticker_has_bars(DB, _sym)
    _price = M.eff_price(_ctx)
    _dchg_pct = M.value("day_change_pct", _ctx)
    _dchg_usd = M.value("day_change_usd", _ctx)
    # under Price, the price's own move per share (as on a watchlist row); the
    # holding's move in dollars is Today's Return under Your position. Without
    # a per-share move, just the percent.
    _dchg_share = (_ctx.get("quote") or {}).get("change")
    try:
        _dchg_share = float(_dchg_share)
        if not math.isfinite(_dchg_share):
            _dchg_share = None    # a NaN/inf move reads as missing
    except (TypeError, ValueError):
        _dchg_share = None
    _price_at = M.value("price_at", _ctx)
    _asof = price_report.as_of_line(
        _price_at, price_report.kind(_sym, _pos.get("asset_type"),
                                     (sec_info.get(_sym) or {}).get("quote_type")))

    # ---- on the band: its name and what it is, under the ticker ---------- #
    # the fuller of the two names (Yahoo's short name stops at about 32
    # characters; a brokerage's description may be longer), wrapped in full
    _tk_name = _tk_full_name(_pos.get("description"), (sec_info.get(_sym) or {}).get("name"))
    with _HOME_HERO or st.container():
        st.html("<div class='pt-hero pt-tk-hero'>"
                + (f"<div class='pt-tk-name'>{html.escape(_tk_name)}</div>"
                   if _tk_name else "")
                + "<div class='pt-tk-kind'>"
                + ("In your holdings" if _is_held else "On your watchlist") + "</div></div>")

    # ---- the price and its chart ----------------------------------------- #
    with st.container(border=True, key="pt_tk_price"):
        hc1, hc2 = st.columns([0.6, 0.4], vertical_alignment="center")
        with hc1:
            st.metric("Price", fmt_price(_price),
                      delta=(None if hide_amounts or _dchg_pct is None
                             else f"{_dchg_share:+,.2f} ({_dchg_pct:+.2f}%) today"
                             if _dchg_share is not None
                             else f"{_dchg_pct:+.2f}% today"))
            if _asof:
                # (where it comes from is on the page's status line: PRICE_SOURCE)
                st.caption(_asof)
        with hc2:
            if _price and flags.on("price_report"):
                _render_price_report(_sym, _price, _price_at)
            _ticker_learn_more(_sym, _pos)

        t1, t2 = st.columns([0.6, 0.4])
        t1.markdown("#### Price history")
        _series = perf.PRICE_SERIES if _has_yahoo else perf.TICKER_SERIES
        _series_label = perf.PRICE_SERIES_LABEL if _has_yahoo else perf.TICKER_SERIES_LABEL
        _series_fmt = perf.PRICE_SERIES_FMT if _has_yahoo else perf.TICKER_SERIES_FMT
        tk_col = t2.selectbox("Ticker series", [c for c, _, _ in _series],
                              format_func=lambda c: _series_label[c],
                              key="tk_series_sel", label_visibility="collapsed")

        rng = st.segmented_control("Range", charts.RANGE_LABELS, default="1D",
                                   key="tk_range", label_visibility="collapsed") or "1D"

        if _has_yahoo:
            # ticker_series() already picks the finest resolution Yahoo has for this
            # window (1-minute up through daily) and clips to it at the SQL level.
            _rows, _interval = perf.ticker_series(DB, _sym, charts.RANGE_DAYS[rng])
            _short = False
        else:
            _th = perf.ticker_history(DB, _sym)
            _rows = [{**r, "t": r["fetched_at"]} for r in _th]
            _interval = "sparse"

        if len(_rows) < 2:
            st.info(f"Not enough history for **{_sym}** in this range yet - it fills in by "
                    "itself (price history loads each evening). Try a longer range.")
        else:
            tdf = pd.DataFrame(_rows)
            tdf["t"] = pd.to_datetime(tdf["t"], utc=True, format="mixed")
            full = tdf.dropna(subset=[tk_col]) if tk_col in tdf.columns else tdf.iloc[0:0]

            if full.empty:
                st.info(f"No **{_series_label[tk_col]}** recorded for {_sym} at this resolution.")
            else:
                _fname = _series_fmt[tk_col]
                _title = _series_label[tk_col]
                if _has_yahoo:
                    win = full  # already clipped to the range by ticker_series()
                else:
                    win, _short = charts.window(full, "t", charts.RANGE_DAYS[rng])

                mas = []
                if _interval == "1d" and tk_col == "close":
                    picked = st.segmented_control(
                        "Moving averages", list(charts.MA_STYLE), format_func=lambda w: f"{w}-day",
                        selection_mode="multi", key="tk_ma", label_visibility="collapsed") or []
                    mas = [(f"ma_{w}", *charts.MA_STYLE[w]) for w in picked if f"ma_{w}" in win.columns]

                first, last, pct = charts.window_change(win, "t", tk_col)
                mcol, _sp = st.columns([0.4, 0.6])
                mcol.metric(
                    _title, FORMATTERS[_fname](last) if _fname in FORMATTERS else mask_or(f"{last:,.2f}"),
                    delta=(None if hide_amounts or pct is None else f"{pct:+.2f}% over {rng}"))

                _date_fmt = "%b %d, %Y" if _interval == "1d" else "%b %d, %Y  %H:%M"
                _tips = [alt.Tooltip("t:T", title="Date", format=_date_fmt)]
                if not hide_amounts:
                    _tips.append(alt.Tooltip(f"{tk_col}:Q", title=_title, format=TOOLTIP_FORMAT[_fname]))
                    for _mc, _, _ in mas:
                        _tips.append(alt.Tooltip(f"{_mc}:Q", title=_mc.replace("ma_", "") + "-day average",
                                                 format="$,.2f"))
                st.altair_chart(
                    charts.line(win, x="t", y=tk_col, y_title=_title, y_format=AXIS_FORMAT[_fname],
                                overlays=mas, tooltip=_tips, mask=hide_amounts,
                                compress_gaps=(_interval in ("1m", "5m", "15m", "60m")),
                                daily=(_interval == "1d")),
                    width="stretch",
                )
                _res_label = perf.INTERVAL_LABEL.get(_interval, _interval)
                if _has_yahoo and _interval == "1d" and (charts.RANGE_DAYS[rng] or 99) <= 1:
                    # no prices through the day for 1D: say what the line shows
                    st.caption(f"Prices through the day aren't kept for {_sym} yet, so this "
                               f"shows its last {len(win)} daily closing prices.")
                st.caption(
                    f"{len(win)}" + (f" of {len(full)}" if len(win) != len(full) else "") + " points · "
                    + (f"**{_res_label}** Yahoo bars." if _has_yahoo
                       else "sparse refresh history — sync history (:material/history:) for real bars.")
                    + (f"  ·  *{rng} is shorter than the data interval — showing the last {len(win)}.*"
                       if _short else "")
                )

    # ---- your position (held) or the watchlist note ---------------------- #
    with st.container(border=True, key="pt_tk_position"):
        if _is_held:
            st.markdown("#### Your position")
            _qty = M.value("quantity", _ctx)
            _cost_basis = M.value("cost_basis", _ctx)
            _avg_cost = (_cost_basis / _qty) if (_qty and _cost_basis is not None) else None
            _mv = M.eff_mv(_ctx)
            _unreal_usd = M.value("unrealized_usd", _ctx)
            _unreal_pct = M.value("unrealized_pct", _ctx)
            _pct_port = M.value("pct_of_portfolio", _ctx)

            pc1, pc2, pc3, pc4 = st.columns(4)
            pc1.metric("Shares", fmt_qty(_qty))
            pc2.metric("Avg Cost", fmt_price(_avg_cost))
            pc3.metric("Market Value", fmt_money(_mv))
            # market value minus cost: the price change (dividends below, when known)
            pc4.metric("Price change", fmt_money(_unreal_usd),
                       delta=(None if hide_amounts or _unreal_pct is None else f"{_unreal_pct:+.2f}%"))

            pc5, pc6, pc7, pc8 = st.columns(4)
            pc5.metric("Cost Basis", fmt_money(_cost_basis))
            pc6.metric("Today's Return", fmt_money(_dchg_usd),
                       delta=(None if hide_amounts or _dchg_pct is None else f"{_dchg_pct:+.2f}%"))
            pc7.metric("% of Portfolio", fmt_pct_level(_pct_port))
            pc8.metric("Account", _pos.get("account") or "—")

            # total return: the price change plus the dividends it paid
            # while held - only when they're known (else the price change alone)
            _tr_usd = M.value("total_return_usd", _ctx)
            if _tr_usd is not None:
                _tr_pct = M.value("total_return_pct", _ctx)
                _div = DIVIDENDS.get(_sym) or {}
                pc9, pc10, _pc11, _pc12 = st.columns(4)
                pc9.metric("Dividends received", fmt_money(M.value("dividends_usd", _ctx)))
                pc10.metric("Total return, with dividends", fmt_money(_tr_usd),
                            delta=(None if hide_amounts or _tr_pct is None
                                   else f"{_tr_pct:+.2f}%"))
                if _div.get("source") == "brokerage":
                    _from = ("From your brokerage's activity history that you imported"
                             + (f", since {_fmt_date(_div['since'])}" if _div.get("since")
                                else "") + ".")
                else:
                    _from = (f"Estimated from what {_sym} paid per share on each ex-dividend "
                             "date while you held it here"
                             + (f" (since {_fmt_date(_div['since'])}, when it first shows in "
                                "your holdings)" if _div.get("since") else "") + ".")
                st.caption("Total return is the price change plus the dividends this holding "
                           f"paid. {_from} Dividends can change.")
            # private, the person's own (views/future_notes.py)
            render_future_note(_sym)
        else:
            st.markdown("#### On your watchlist")
            st.caption("Not a position you own — tracking it for the chart and stats only.")
            st.button("Remove from watchlist", key="wl_remove_from_detail",
                      on_click=_remove_from_watchlist, args=(_sym,))

    # ---- stats: day range, fundamentals, income -------------------------- #
    with st.container(border=True, key="pt_tk_stats"):
        st.markdown("#### Stats")
        # plain words with a short explanation each; stats with nothing to
        # show are left out and named once, instead of rows of dashes
        _missing_stats = _stat_tiles(_ctx, [k for k, _, _ in TK_STATS],
                                     labels={k: w for k, w, _ in TK_STATS},
                                     helps={k: h for k, _, h in TK_STATS if h},
                                     skip_blank=True)
        _is_fund = fees.holding_type((sec_info.get(_sym) or {}).get("quote_type"),
                                     _pos.get("asset_type")) == "fund"
        if _is_fund:   # a company's own figures aren't missing for a fund: they don't apply
            _labels = dict((k, w) for k, w, _ in TK_STATS)
            _missing_stats = [w for w in _missing_stats
                              if w not in {_labels[k] for k in TK_COMPANY_ONLY}]
        if _missing_stats:
            st.caption(f"Not available for {'this fund' if _is_fund else _sym}: "
                       + "; ".join(_missing_stats) + ".")
        if not _blank(M.value("div_yield_pct", _ctx)):
            learn_more("dividends")   # beside its dividend yield
        what_this_means("Dividend yield", "Volatility", key="tk_stats_words")
        _render_ticker_dates(_sym, _pos)
        if not (_covered or bar_stats or perf.has_bars(DB)):   # any Yahoo history at all
            st.caption("More stats (the past year's range, beta, price to earnings, company size, "
                       "sector, average prices) fill in once price history has loaded - usually "
                       "by the next morning.")

    # ---- news: cached Finnhub headlines, fetched when stale --------------- #
    with st.container(border=True, key="pt_tk_news"):
        st.markdown("#### Recent News")
        _news_key = resolve_key(None, ENV_PATH)
        if not _news_key:
            st.caption("News isn't available on this copy of Northwend right now.")
        else:
            _news_conn = connect(DB)
            try:
                _n_new, _news_err = news.sync_ticker(_news_conn, _sym, _news_key)
                _articles = news.latest_news(_news_conn, _sym)
            finally:
                _news_conn.close()
            if _news_err and not _articles:
                st.caption(f"Couldn't load news for {_sym}: {_news_err}")
            elif not _articles:
                st.caption(f"No recent news for {_sym} in the last {news.LOOKBACK_DAYS} days.")
            else:
                for _a in _articles:
                    _pub = (pd.to_datetime(_a["published_at"], utc=True).strftime("%b %d, %Y %H:%M UTC")
                           if _a["published_at"] else "")
                    st.markdown(f"**[{_a['headline']}]({_a['url']})**  \n*{_a['source']} · {_pub}*")
                    if _a.get("summary"):
                        _sumtext = _a["summary"]
                        st.caption(_sumtext[:220] + ("…" if len(_sumtext) > 220 else ""))
