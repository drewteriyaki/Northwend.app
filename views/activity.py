# Part of dashboard.py, which runs this file with _view("activity") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# The Activity page: buys and sells inferred from holdings updates, and the
# real history from an imported activity export (txn_import.py). Calm by
# default (ROADMAP S6): the last year's money in and out and the latest moves,
# with the whole history (filters, table, CSV) in a window; the full page for
# advisors and for Show everything (_show_everything).
# ruff: noqa: F821

import txn_import

ACTIVITY_LATEST = 5   # moves listed in the calm view


def _render_activity_empty():
    """Activity with nothing in it yet: why, how it fills itself, and the next step."""
    if SNAPSHOT_SOURCE == SAMPLE_SOURCE:
        st.info(":material/science: The example portfolio is a single made-up snapshot, so it "
                "has no buys or sells. Add your own holdings and this page starts filling in.")
    elif SNAPSHOT_SOURCE == manual_entry.PCT_SOURCE:
        st.info(":material/percent: A percentages-only portfolio is pretend, so there are no real "
                "buys and sells to record. Enter share counts instead to track activity.")
    else:
        st.info(":material/history: No activity yet. It fills in by itself - there's nothing "
                "to type in.")
    st.markdown("**How it works**")
    _md("1. Each time you update your holdings - a CSV, a paste, screenshots or by hand - "
        f"{APP_NAME} compares them with your last update.\n"
        "2. Shares that went up are recorded as a **buy**, shares that went down as a **sell** "
        "(with an estimated gain or loss), and new or removed holdings likewise. An "
        "account's first update is its starting point, not a purchase.\n"
        "3. Update every so often - after you trade, or once a month - and the history builds up.\n"
        "\n**Want the real history?** Download your brokerage's **activity** (or transaction "
        "history) export and upload it with **Upload a CSV** - your actual buys, sells, "
        "dividends and deposits, any brokerage.")
    st.dataframe(pd.DataFrame([
        {"Holding": "VTI", "Last update": "10 shares", "This update": "15 shares",
         "Recorded as": "Buy 5"},
        {"Holding": "AAPL", "Last update": "8 shares", "This update": "5 shares",
         "Recorded as": "Sell 3"},
        {"Holding": "BND", "Last update": "-", "This update": "20 shares",
         "Recorded as": "Buy 20"},
    ]), hide_index=True, width="stretch")
    st.caption("An example. Prices and amounts are estimated from your holdings' values, and "
               "trades made and undone between two updates won't show.")
    if CAN_IMPORT:
        b1, b2, _ = st.columns([1, 1, 2])
        b1.button(":material/content_paste: Update holdings", key="act_manual", width="stretch",
                  on_click=_open_holdings_dialog, args=("manual",))
        b2.button(":material/upload_file: Upload a CSV", key="act_import", width="stretch",
                  on_click=_open_holdings_dialog, args=("import",))


def _load_activity():
    """Every transaction of this account, newest first (one query)."""
    c = connect(DB)
    try:
        txns = [dict(r) for r in c.execute(
            "SELECT * FROM transactions WHERE user_id = ? ORDER BY trade_date DESC, id DESC",
            (USER_ID,))]
    finally:
        c.close()
    for t in txns:
        t["account"] = accounts.display(t["account"], ACCOUNT_LABELS)
    return txns


def _render_activity_table(all_txns):
    """The whole history: filters, the table, a CSV, and how rows are worked out."""
    has_imported = any(t.get("origin") for t in all_txns)
    fc1, fc2, fc3 = st.columns(3)
    f_accounts = fc1.multiselect(
        "Account", sorted({t["account"] for t in all_txns if t["account"]}), key="txn_f_account")
    f_actions = fc2.multiselect(
        "Action", sorted({t["action"] for t in all_txns if t["action"]}), key="txn_f_action",
        format_func=lambda a: txn_import.TYPES.get(a, a))
    f_symbol = fc3.text_input("Symbol contains", key="txn_f_symbol", placeholder="e.g. AAPL")

    f_source = (st.segmented_control(
        "Show", ["Everything", "From your brokerage", "Worked out from updates"],
        default="Everything", key="txn_f_source") or "Everything") if has_imported \
        else "Everything"
    filtered = all_txns
    if f_source != "Everything":
        want = f_source == "From your brokerage"
        filtered = [t for t in filtered if bool(t.get("origin")) == want]
    if f_accounts:
        filtered = [t for t in filtered if t["account"] in f_accounts]
    if f_actions:
        filtered = [t for t in filtered if t["action"] in f_actions]
    if f_symbol.strip():
        sq = f_symbol.strip().upper()
        filtered = [t for t in filtered if sq in (t["symbol"] or "").upper()]

    if not filtered:
        st.caption("No transactions match these filters.")
        return
    realized = [t["realized_gain"] for t in filtered if t["realized_gain"] is not None]
    rc1, rc2 = st.columns(2)
    rc1.metric("Transactions shown", len(filtered))
    if realized:
        rc2.metric("Realized gain/loss", fmt_money(sum(realized)))

    # Pre-formatted to display strings (not left as raw floats for the
    # Styler to format at render time) - Streamlit's dataframe grid
    # doesn't reliably pick up a Styler's na_rep/format for a NaN cell,
    # rendering the raw missing value as the literal text "None" instead.
    # Color still needs the ORIGINAL numbers, so it's computed from a
    # closure over the raw list, independent of the now-string columns.
    amount_raw = [t["amount"] for t in filtered]
    gain_raw = [t["realized_gain"] for t in filtered]
    tdf = pd.DataFrame([{
        "Date": t["trade_date"], "Action": txn_import.TYPES.get(t["action"], t["action"]),
        "Symbol": t["symbol"] or "—",   # deposits, withdrawals, fees have none
        "Description": t["description"] or "", "Qty": fmt_qty(t["quantity"]),
        "Price": fmt_price(t["price"]), "Amount": fmt_money(t["amount"]),
        "Realized G/L": fmt_money(t["realized_gain"]), "Account": t["account"],
        **({"From": "Brokerage" if t.get("origin") else "Worked out"}
           if has_imported else {}),
    } for t in filtered])
    txn_styler = (
        tdf.style
        .apply(lambda col: [color_sign(v) for v in amount_raw], subset=["Amount"])
        .apply(lambda col: [color_sign(v) for v in gain_raw], subset=["Realized G/L"])
    )
    st.dataframe(txn_styler, width="stretch", hide_index=True)
    tdf_raw = pd.DataFrame([{
        "Date": t["trade_date"], "Action": t["action"], "Symbol": t["symbol"],
        "Description": t["description"], "Qty": t["quantity"], "Price": t["price"],
        "Amount": t["amount"], "Realized G/L": t["realized_gain"], "Account": t["account"],
        "From": "brokerage" if t.get("origin") else "worked out",
    } for t in filtered])
    st.download_button(
        "Download CSV", tdf_raw.to_csv(index=False).encode("utf-8"),
        file_name="activity.csv", mime="text/csv", key="activity_dl", on_click="ignore",
        disabled=hide_amounts, help=(
            "Disabled while amounts are hidden — turn off Hide amounts to export real figures."
            if hide_amounts else None),
    )
    st.caption(("**From your brokerage:** rows from an activity export you imported, as "
                "your brokerage recorded them; a sale's Realized G/L uses the average "
                "cost of the buys in that history, and is blank when the history doesn't "
                "reach back to when the shares were bought. " if has_imported else "")
               + "**Worked out** rows come from the change in shares between two "
               "updates of your holdings - prices and amounts are estimates, and "
               "Realized G/L uses the average-cost method. Import your brokerage's "
               "activity export (Upload a CSV) for the real history.")


@st.dialog("All activity", width="large", on_dismiss=_dialog_closed)
def _activity_window(all_txns):
    _render_activity_table(all_txns)


def _activity_summary(all_txns, today):
    """The last 12 months (or everything, when nothing is that recent): money
    added and taken out, bought, sold and the gain or loss on what was sold."""
    since = (today - timedelta(days=365)).isoformat()
    recent = [t for t in all_txns if (t["trade_date"] or "") >= since]
    period = "last 12 months" if recent else "so far"
    rows = recent or all_txns

    def total(kinds, sign=1):
        return sum(sign * t["amount"] for t in rows
                   if t["action"] in kinds and t["amount"] is not None)
    cash_moves = [t for t in rows if t["action"] in ("DEPOSIT", "WITHDRAWAL")
                  and t["amount"] is not None]
    bought, sold = total(("BUY", "REINVEST"), -1), total(("SELL",))
    gains = [t["realized_gain"] for t in rows if t["realized_gain"] is not None]
    stats = []
    if cash_moves:
        put_in = sum(t["amount"] for t in cash_moves)
        stats.append((f"Money added, {period}", _signed_money(put_in),
                      f"{len(cash_moves)} deposit{'s' if len(cash_moves) != 1 else ''} or "
                      "withdrawal" + ("s" if len(cash_moves) != 1 else "")))
    else:
        stats.append((f"Moves, {period}", str(len(rows)), None))
    stats.append(("Bought", fmt_money(bought), None))
    gain = sum(gains)
    # said in words too, not only by the color ("gain/loss" while amounts are hidden)
    gain_word = " gain/loss" if _hidden() else (" loss" if gain < 0 else " gain")
    stats.append(("Sold", fmt_money(sold),
                  _tone(gain, _signed_money(gain) + gain_word) if gains else None))
    _summary_stats(stats)


def _activity_move(t):
    """'Buy 5 VTI' / 'Dividend SCHD' / 'Deposit' for the latest moves."""
    kind = txn_import.TYPES.get(t["action"], t["action"] or "Move")
    qty = fmt_qty(t["quantity"]) if t["action"] in ("BUY", "SELL", "REINVEST") \
        and t["quantity"] else ""
    return " ".join(x for x in (kind, qty, t["symbol"] or "") if x)


def _render_activity_calm(all_txns):
    _activity_summary(all_txns, datetime.now().date())
    st.markdown("**Latest moves**")
    # a list to screen readers: each move's date, what it was and its amount
    st.html("<div class='pt-legend' role='list' aria-label='Latest moves'>" + "".join(
        "<div class='pt-legend-row' role='listitem'>"
        f"<time class='pt-legend-val' style='text-align:left' "
        f"datetime='{html.escape(str(t['trade_date'] or '')[:10], quote=True)}'>"
        f"{_fmt_date(t['trade_date'])}</time>"
        f"<span class='pt-legend-label'>{html.escape(_activity_move(t))}</span>"
        f"<span class='pt-legend-pct'>{_tone(t['amount'], _signed_money(t['amount']))}</span>"
        "</div>" for t in all_txns[:ACTIVITY_LATEST]) + "</div>")
    if st.button(f"See all activity ({len(all_txns)})", key="activity_open", type="tertiary",
                 icon=":material/open_in_new:"):
        _open_window(_activity_window, all_txns)
    if CAN_IMPORT and not any(t.get("origin") for t in all_txns):
        _next_step_card("activity", "Want the real history? Upload your brokerage's "
                        "<b>activity</b> export (any brokerage) - your actual buys, sells, "
                        "dividends and deposits. Until then, moves are worked out from your "
                        "updates.",
                        (":material/upload_file: Upload a CSV", _open_holdings_dialog, ("import",)))
    _calm_footer()


if PAGE == "Activity":
    # ---- activity: inferred and imported transaction history -------------- #
    _all_txns = _load_activity()
    if not _all_txns:
        _render_activity_empty()
    elif _show_everything():
        _render_activity_table(_all_txns)
    else:
        _render_activity_calm(_all_txns)
