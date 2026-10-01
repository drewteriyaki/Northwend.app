# Part of dashboard.py, which runs this file with _view("activity") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# The Activity page: buys and sells inferred from holdings updates, and the
# real history from an imported activity export (txn_import.py).
# ruff: noqa: F821

import txn_import

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
        "(with an estimated gain or loss), and new or removed holdings likewise.\n"
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


if PAGE == "Activity":
    # ---- activity: inferred transaction history --------------------------- #

    _txn_conn = connect(DB)
    try:
        _all_txns = [dict(r) for r in _txn_conn.execute(
            "SELECT * FROM transactions WHERE user_id = ? ORDER BY trade_date DESC, id DESC", (USER_ID,))]
    finally:
        _txn_conn.close()
    for _t in _all_txns:
        _t["account"] = accounts.display(_t["account"], ACCOUNT_LABELS)

    if not _all_txns:
        _render_activity_empty()
    else:
        _has_imported = any(t.get("origin") for t in _all_txns)
        fc1, fc2, fc3 = st.columns(3)
        _f_accounts = fc1.multiselect(
            "Account", sorted({t["account"] for t in _all_txns if t["account"]}), key="txn_f_account")
        _f_actions = fc2.multiselect(
            "Action", sorted({t["action"] for t in _all_txns if t["action"]}), key="txn_f_action",
            format_func=lambda a: txn_import.TYPES.get(a, a))
        _f_symbol = fc3.text_input("Symbol contains", key="txn_f_symbol", placeholder="e.g. AAPL")

        _f_source = (st.segmented_control(
            "Show", ["Everything", "From your brokerage", "Worked out from updates"],
            default="Everything", key="txn_f_source") or "Everything") if _has_imported             else "Everything"
        _filtered = _all_txns
        if _f_source != "Everything":
            _want = _f_source == "From your brokerage"
            _filtered = [t for t in _filtered if bool(t.get("origin")) == _want]
        if _f_accounts:
            _filtered = [t for t in _filtered if t["account"] in _f_accounts]
        if _f_actions:
            _filtered = [t for t in _filtered if t["action"] in _f_actions]
        if _f_symbol.strip():
            _sq = _f_symbol.strip().upper()
            _filtered = [t for t in _filtered if _sq in (t["symbol"] or "").upper()]

        if not _filtered:
            st.caption("No transactions match these filters.")
        else:
            _realized = [t["realized_gain"] for t in _filtered if t["realized_gain"] is not None]
            rc1, rc2 = st.columns(2)
            rc1.metric("Transactions shown", len(_filtered))
            if _realized:
                rc2.metric("Realized gain/loss", fmt_money(sum(_realized)))

            # Pre-formatted to display strings (not left as raw floats for the
            # Styler to format at render time) - Streamlit's dataframe grid
            # doesn't reliably pick up a Styler's na_rep/format for a NaN cell,
            # rendering the raw missing value as the literal text "None" instead.
            # Color still needs the ORIGINAL numbers, so it's computed from a
            # closure over the raw list, independent of the now-string columns.
            _amount_raw = [t["amount"] for t in _filtered]
            _gain_raw = [t["realized_gain"] for t in _filtered]
            _tdf = pd.DataFrame([{
                "Date": t["trade_date"], "Action": txn_import.TYPES.get(t["action"], t["action"]),
                "Symbol": t["symbol"],
                "Description": t["description"] or "", "Qty": fmt_qty(t["quantity"]),
                "Price": fmt_price(t["price"]), "Amount": fmt_money(t["amount"]),
                "Realized G/L": fmt_money(t["realized_gain"]), "Account": t["account"],
                **({"From": "Brokerage" if t.get("origin") else "Worked out"}
                   if _has_imported else {}),
            } for t in _filtered])
            _txn_styler = (
                _tdf.style
                .apply(lambda col: [color_sign(v) for v in _amount_raw], subset=["Amount"])
                .apply(lambda col: [color_sign(v) for v in _gain_raw], subset=["Realized G/L"])
            )
            st.dataframe(_txn_styler, width="stretch", hide_index=True)
            _tdf_raw = pd.DataFrame([{
                "Date": t["trade_date"], "Action": t["action"], "Symbol": t["symbol"],
                "Description": t["description"], "Qty": t["quantity"], "Price": t["price"],
                "Amount": t["amount"], "Realized G/L": t["realized_gain"], "Account": t["account"],
                "From": "brokerage" if t.get("origin") else "worked out",
            } for t in _filtered])
            st.download_button(
                "Download CSV", _tdf_raw.to_csv(index=False).encode("utf-8"),
                file_name="activity.csv", mime="text/csv", key="activity_dl",
                disabled=hide_amounts, help=(
                    "Disabled while amounts are hidden — turn off Hide amounts to export real figures."
                    if hide_amounts else None),
            )
            st.caption(("**From your brokerage:** rows from an activity export you imported, as "
                        "your brokerage recorded them; a sale's Realized G/L uses the average "
                        "cost of the buys in that history, and is blank when the history doesn't "
                        "reach back to when the shares were bought. " if _has_imported else "")
                       + "**Worked out** rows come from the change in shares between two "
                       "updates of your holdings - prices and amounts are estimates, and "
                       "Realized G/L uses the average-cost method. Import your brokerage's "
                       "activity export (Upload a CSV) for the real history.")
