# Part of dashboard.py, which runs this file with _view("income") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# The Income page: dividends received (from an imported activity export),
# the next 12 months by month, and yields.
# ruff: noqa: F821

def _render_income_by_month(income_rows):
    """The next 12 months of estimated dividend income (income.py): each
    holding's past year of payments repeated, times the shares held now."""
    import income
    today = datetime.now().date()
    qty, annual = {}, {}
    for p in positions:
        qty[p["symbol"]] = qty.get(p["symbol"], 0.0) + (p.get("quantity") or 0.0)
    for r in income_rows:
        annual[r["symbol"]] = annual.get(r["symbol"], 0.0) + r["est_income"]
    c = connect(DB)
    try:
        synced = income.has_history(c, qty)
        paid = income.payments(c, qty, today)
    finally:
        c.close()
    # payment dates come with the price history; fetch it once for holdings
    # synced before dividends were kept
    unsynced = sorted(set(qty) - synced)
    if unsynced and not st.session_state.get("income_synced"):
        st.session_state["income_synced"] = True
        _sync_history(unsynced, quick=True)
    plan = income.schedule([{"symbol": s, "quantity": q, "annual": annual.get(s)}
                            for s, q in sorted(qty.items())], paid, synced, today)
    if not plan["total"]:
        if unsynced:
            st.caption("Payment dates fill in with tonight's price history.")
        return

    st.subheader("Next 12 months", anchor=False)
    months = plan["months"]
    peak = max(months, key=lambda r: r["total"])
    label = lambda m: datetime.strptime(m + "-01", "%Y-%m-%d").strftime("%b %Y")  # noqa: E731
    mc1, mc2 = st.columns(2)
    mc1.metric("Estimated income, next 12 months", fmt_money(plan["total"]))
    mc2.metric("Biggest month", label(peak["month"]), fmt_money(peak["total"]),
               delta_color="off", delta_arrow="off")
    st.altair_chart(_income_bars(months, label), width="stretch")
    notes = ["By ex-dividend month - the money usually arrives a few weeks later. Each holding "
             "repeats its last year of payments at today's share count; dividends can change."]
    if plan["spread"]:
        notes.append("No payment dates yet for " + ", ".join(plan["spread"])
                     + " - its yearly estimate is spread evenly across the months.")
    st.caption(" ".join(notes))
    st.divider()


def _income_bars(months, label):
    """Monthly bars: [{"month", "total", "by_symbol"}]."""
    chart_df = pd.DataFrame([{"Month": label(r["month"]), "order": i,
                              "Income": 0.0 if _hidden() else r["total"],
                              "Paid by": ", ".join(s for s, v in sorted(
                                  r["by_symbol"].items(), key=lambda kv: -kv[1]) if v)}
                             for i, r in enumerate(months)])
    color = (SERIES_DARK if st.context.theme.type == "dark" else SERIES_LIGHT)[0]
    return alt.Chart(chart_df).mark_bar(color=color, cornerRadiusTopLeft=3,
                                        cornerRadiusTopRight=3).encode(
        x=alt.X("Month:N", sort=alt.SortField("order"), title=None,
                axis=alt.Axis(labelAngle=0, labelExpr="slice(datum.label, 0, 3)")),
        y=alt.Y("Income:Q", title=None, axis=alt.Axis(format="$,.0f", labels=not _hidden())),
        tooltip=[alt.Tooltip("Month:N"), alt.Tooltip("Income:Q", format="$,.2f"),
                 alt.Tooltip("Paid by:N")])


def _render_income_received():
    """What was actually paid in the last 12 months, from an imported activity
    export (income.received). Nothing when none was imported."""
    import income
    c = connect(DB)
    try:
        got = income.received(c, USER_ID, datetime.now().date())
    finally:
        c.close()
    if got is None:
        return
    label = lambda m: datetime.strptime(m + "-01", "%Y-%m-%d").strftime("%b %Y")  # noqa: E731
    st.subheader("Received, last 12 months", anchor=False)
    rc1, rc2, rc3 = st.columns(3)
    rc1.metric("Dividends received", fmt_money(got["dividends"]))
    rc2.metric("Interest received", fmt_money(got["interest"]))
    rc3.metric("Total", fmt_money(got["total"]))
    if got["total"]:
        st.altair_chart(_income_bars(got["months"], label), width="stretch")
    st.caption("From your brokerage's activity history that you imported - what was actually "
               "paid, including dividends that were reinvested."
               + (f" It starts on {_fmt_date(got['since'])}, so earlier months show nothing."
                  if got["since"] else ""))
    st.divider()


if PAGE == "Income":
    # ---- income: dividend yield summary + per-position breakdown ---------- #

    _income_rows = []
    for p, ctx in zip(positions, contexts):
        _yld = M.value("div_yield_pct", ctx)
        _mv = M.eff_mv(ctx)
        if _yld is None or _mv is None:
            continue
        _income_rows.append({
            "symbol": p["symbol"], "description": p.get("description"), "market_value": _mv,
            "yield_pct": _yld, "est_income": _mv * _yld / 100,
            "last_pay_date": p.get("div_pay_date"),
            "reinvest": {1: "Yes", 0: "No"}.get(p.get("reinvest")), "account": p["account"],
        })

    _render_income_received()
    _render_income_by_month(_income_rows)

    if not _income_rows:
        st.caption("No dividend-yield figures from your brokerage's file - the table of yields "
                   "below appears when your broker's export includes a **Dividend Yield** column.")
    else:
        _total_income = sum(r["est_income"] for r in _income_rows)
        _yield_on_holdings = (_total_income / tot_mv * 100) if tot_mv else None

        ic1, ic2, ic3 = st.columns(3)
        ic1.metric("Est. annual dividend income", fmt_money(_total_income))
        ic2.metric("Yield on holdings", fmt_pct(_yield_on_holdings))
        ic3.metric("Income-producing positions", f"{len(_income_rows)} / {len(positions)}")

        _income_rows.sort(key=lambda r: r["est_income"], reverse=True)
        _idf_raw = pd.DataFrame([{
            "Symbol": r["symbol"], "Description": r["description"],
            "Market Value": r["market_value"], "Div Yield %": r["yield_pct"],
            "Est. Annual Income": r["est_income"], "Last Pay Date": r["last_pay_date"],
            "Reinvest": r["reinvest"], "Account": r["account"],
        } for r in _income_rows])
        _idf = pd.DataFrame([{
            "Symbol": r["symbol"], "Description": r["description"],
            "Market Value": fmt_money(r["market_value"]), "Div Yield %": fmt_pct(r["yield_pct"]),
            "Est. Annual Income": fmt_money(r["est_income"]),
            "Last Pay Date": r["last_pay_date"] or "—", "Reinvest": r["reinvest"] or "—",
            "Account": r["account"],
        } for r in _income_rows])
        st.dataframe(_idf, width="stretch", hide_index=True)
        st.download_button(
            "Download CSV", _idf_raw.to_csv(index=False).encode("utf-8"),
            file_name="income.csv", mime="text/csv", key="income_dl",
            disabled=hide_amounts, help=(
                "Disabled while amounts are hidden — turn off Hide amounts to export real figures."
                if hide_amounts else None),
        )
        st.caption("Est. Annual Income = market value × dividend yield, both as reported in the CSV "
                   "— a simple estimate, not a payment schedule. **Last Pay Date** is the most "
                   "recently known payment from your brokerage's file, not a prediction of the "
                   "next one.")
