# Part of dashboard.py, which runs this file with _view("holdings_input") at the point
# where this code used to sit, in dashboard.py's own namespace: the names here
# (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what this
# defines is visible there afterwards. See _view() in dashboard.py.
#
# Getting holdings in: paste, type by hand, screenshots, CSV files, the shared
# review-and-save step, and the example portfolio.
# ruff: noqa: F821

def _after_import():
    """A new statement can bring new tickers: fetch their prices and history
    on the next run instead of waiting for the scheduled jobs."""
    st.session_state.pop("auto_backfilled", None)
    st.session_state["dialog_open"] = False  # saved: the dialog is closing
    for k in ("last_open_snapshot", "value_logged", "export_zip"):  # it changed: start afresh
        st.session_state.pop(k, None)


def _manual_rows_init(current_positions, current_cash, current_source=None):
    """Start the hand-entry form from the latest snapshot (once per opening)."""
    if "me_ids" in st.session_state:
        return
    to_broker = {v: k for k, v in ACCOUNT_LABELS.items()}
    base = [{**p, "account": p.get("broker_account") or p.get("account")} for p in current_positions]
    cash = {to_broker.get(a, a): v for a, v in current_cash.items()}
    holdings, cash_rows = manual_entry.prefill(base, cash)
    weights, cash_pct = manual_entry.prefill_weights(base, cash)
    pct_by = {(w["Account"], w["Symbol"]): w["Percent"] for w in weights}
    holdings = holdings or [{"Account": manual_entry.DEFAULT_ACCOUNT, "Type": "ETF"}]
    cash_rows = cash_rows or [{"Account": holdings[0]["Account"], "Cash": None}]
    ss = st.session_state
    ss["me_next"] = 0
    ss["me_ids"], ss["me_cash_ids"] = [], []
    ss["me_mode"] = "Percentages" if current_source == manual_entry.PCT_SOURCE else "Shares"
    # Number fields keep their values here, not in their widget keys: Streamlit
    # drops a widget's value on a run where it isn't shown, and the Shares and
    # Percentages fields take turns being hidden.
    ss["me_vals"] = {"cash_pct": cash_pct if base else None, "total": manual_entry.DEFAULT_TOTAL}
    if current_source == manual_entry.PCT_SOURCE and base:
        # keep the pretend total it was made with
        ss["me_vals"]["total"] = round(sum(p.get("market_value") or 0.0 for p in base)
                               + sum(v or 0.0 for v in cash.values()), 2)
    for r in holdings:
        _manual_add_row({**r, "Percent": pct_by.get((r["Account"], r.get("Symbol")))})
    for r in cash_rows:
        _manual_add_cash(r)


def _manual_number(label, name, *, min_value=0.0, **kw):
    """A number field whose value lives in me_vals (see _manual_rows_init)."""
    vals = st.session_state["me_vals"]
    wkey = f"me_w_{name}"

    def keep():
        vals[name] = st.session_state.get(wkey)
        st.session_state.pop("me_review", None)
    st.session_state[wkey] = vals.get(name)
    return st.number_input(label, key=wkey, min_value=min_value, on_change=keep, **kw)


def _manual_new_id():
    st.session_state["me_next"] += 1
    return st.session_state["me_next"]


def _manual_add_row(r=None):
    r = r or {"Account": _manual_last_account(), "Type": "ETF"}
    i = _manual_new_id()
    st.session_state[f"me_acct_{i}"] = r.get("Account") or manual_entry.DEFAULT_ACCOUNT
    st.session_state[f"me_sym_{i}"] = r.get("Symbol") or ""
    st.session_state["me_vals"].update({f"qty_{i}": r.get("Shares"), f"cost_{i}": r.get("Total cost"),
                                        f"pct_{i}": r.get("Percent")})
    st.session_state[f"me_type_{i}"] = r.get("Type") or "ETF"
    st.session_state["me_ids"].append(i)
    st.session_state.pop("me_review", None)


def _manual_add_cash(r=None):
    r = r or {"Account": _manual_last_account()}
    i = _manual_new_id()
    st.session_state[f"me_cacct_{i}"] = r.get("Account") or manual_entry.DEFAULT_ACCOUNT
    st.session_state["me_vals"][f"cash_{i}"] = r.get("Cash")
    st.session_state["me_cash_ids"].append(i)
    st.session_state.pop("me_review", None)


def _manual_last_account():
    ids = st.session_state.get("me_ids") or []
    return (st.session_state.get(f"me_acct_{ids[-1]}") if ids else None) or \
        manual_entry.DEFAULT_ACCOUNT


def _manual_remove(kind, i):
    st.session_state[kind].remove(i)
    st.session_state.pop("me_review", None)


def _manual_form_rows():
    ss = st.session_state
    v = ss["me_vals"]
    holdings = [{"Account": ss.get(f"me_acct_{i}"), "Symbol": ss.get(f"me_sym_{i}"),
                 "Shares": v.get(f"qty_{i}"), "Total cost": v.get(f"cost_{i}"),
                 "Percent": v.get(f"pct_{i}"), "Type": ss.get(f"me_type_{i}")}
                for i in ss["me_ids"]]
    cash = [{"Account": ss.get(f"me_cacct_{i}"), "Cash": v.get(f"cash_{i}")}
            for i in ss["me_cash_ids"]]
    return holdings, cash


def _manual_from_paste():
    """Replace the form's rows with what paste_parse finds in the pasted text,
    then forget the text."""
    ss = st.session_state
    found = paste_parse.parse(ss.get("me_paste") or "")
    ss["me_paste"] = ""  # the pasted text isn't kept, even in this session
    if not found["holdings"]:
        ss["me_paste_msg"] = ("warning", "Couldn't find any holdings in that text. Try copying "
                              "just the positions table, or type lines like `VTI 10`.")
        return
    ss["me_paste_msg"] = _manual_fill(found)


def _manual_fill(found):
    """Replace the form's rows with `found` (paste_parse.parse() / screenshot_read
    shape). Returns the (kind, message) to show."""
    ss = st.session_state
    acct = _manual_last_account()
    ss["me_ids"], ss["me_cash_ids"] = [], []
    for h in found["holdings"]:
        _manual_add_row({"Account": acct, "Symbol": h["Symbol"], "Shares": h["Shares"],
                         "Total cost": h["Total cost"], "Percent": h["Percent"],
                         "Type": h.get("Type") or "Other"})
    _manual_add_cash({"Account": acct, "Cash": found["cash"] if found["mode"] == "Shares" else None})
    ss["me_mode"] = found["mode"]
    n = len(found["holdings"])
    return ("success", f"Found {n} holding{'s' if n != 1 else ''}"
                          + (f" and {fmt_money(found['cash'])} cash" if found["cash"] else "")
                          + " - check them below, then look up prices. Type is set to Other; "
                            "Yahoo works out what each one holds.")


def _render_screenshot_reader():
    """Read from screenshots: opt-in, the images go to Anthropic's AI (see
    screenshot_read.py). They're read from memory and never kept."""
    ss = st.session_state
    msg = ss.pop("me_shot_msg", None)
    with st.expander(":material/photo_camera: Read from screenshots (uses AI)",
                     expanded=bool(msg)):
        key = _anthropic_key()
        if not key:
            st.caption("Reading screenshots needs the AI, which isn't set up on this site.")
            return
        st.caption("For phone apps and sites where copying is hard. **Crop each screenshot to "
                   "just your holdings list first** - the whole image is sent to Anthropic's AI "
                   "to read it. Only symbols, share counts and cost are taken from what it "
                   "reads, and the images aren't saved.")
        shots = st.file_uploader(
            "Screenshots", type=sorted(screenshot_read.MEDIA_TYPES), accept_multiple_files=True,
            key=f"me_shots_{ss.get('me_shots_n', 0)}", label_visibility="collapsed")
        agreed = st.checkbox("Send these images to Anthropic's AI to read them",
                             key="me_shots_ok")
        if msg:
            getattr(st, msg[0])(msg[1])
        quota = _ai_status("screenshot")  # this month's allowance (ai_usage.py)
        if not quota["ok"]:
            st.info(ai_usage.used_up_text(quota, "screenshot") + " You can still paste or "
                    "type your holdings.")
        elif quota["limit"]:
            st.caption(ai_usage.left_text(quota, "screenshot").capitalize() + ".")
        if st.button("Read screenshots", key="me_shots_btn",
                     disabled=not (shots and agreed and quota["ok"])):
            images, errors = screenshot_read.check_images([(f.name, f.getvalue()) for f in shots])
            if errors:
                st.error("  \n".join(errors))
                return
            _ai_record("screenshot")
            with st.spinner("Reading your screenshots..."):
                found = screenshot_read.read(images, key)
            del images, shots  # nothing of the images is kept past this point
            ss["me_shots_n"] = ss.get("me_shots_n", 0) + 1   # empties the uploader
            ss["me_shots_ok"] = False
            if found["error"]:
                ss["me_shot_msg"] = ("error", found["error"])
            elif not found["holdings"]:
                ss["me_shot_msg"] = ("warning", "No holdings could be read from those "
                                     "screenshots. Try cropping closer to the list.")
            else:
                ss["me_shot_msg"] = _manual_fill(found)
            st.rerun(scope="fragment")


def _manual_clear():
    for k in [k for k in st.session_state if k.startswith("me_")]:
        del st.session_state[k]


def _manual_save(meta, rows, totals, txns, source):
    """Write a reviewed hand entry: the snapshot (portfolio.write_snapshot, the
    same save an import uses) and the day's inferred buys and sells."""
    conn = connect(DB)
    try:
        write_snapshot(conn, USER_ID, meta, rows, totals, source)
        conn.execute("DELETE FROM transactions WHERE trade_date = ? AND user_id = ?",
                     (meta["snapshot_date"], USER_ID))
        for tx in txns:
            tx["user_id"] = USER_ID
        if txns:
            conn.executemany(
                "INSERT INTO transactions (account, trade_date, action, symbol, "
                "description, quantity, price, amount, fees, realized_gain, "
                "source_file, user_id) VALUES "
                "(:account, :trade_date, :action, :symbol, :description, :quantity, "
                ":price, :amount, :fees, :realized_gain, :source_file, :user_id)", txns)
        conn.commit()
    except DBError:
        conn.rollback()
        raise
    finally:
        conn.close()


def _review_and_save(meta, rows, totals, source, *, pct_mode=False, key="save_holdings",
                     after=None):
    """"What we'll keep", the change summary and Save, for holdings about to be
    saved as a snapshot - hand entry, paste, screenshots and CSV files alike.
    `after` runs once saved (e.g. clearing the form)."""
    st.markdown("**What we'll keep**")
    st.dataframe(pd.DataFrame([{
        "Account": accounts.mask_number(r["account"]), "Symbol": r["symbol"],
        "Name": r["description"] or "",
        "Shares": round(r["quantity"], 4), "Value": fmt_money(r["market_value"]),
        **({} if pct_mode else {"Total cost": fmt_money(r["cost_basis"])
                                if r["cost_basis"] is not None else ""})}
        for r in rows]), hide_index=True, width="stretch")
    total = sum(r["market_value"] for r in rows) + sum(t["cash_value"] or 0 for t in totals.values())
    conn = connect(DB)
    try:
        base_date = conn.execute(
            "SELECT MAX(snapshot_date) d FROM positions WHERE snapshot_date < ? AND user_id = ?",
            (meta["snapshot_date"], USER_ID)).fetchone()["d"]
        base_rows = [dict(r) for r in conn.execute(
            "SELECT account, symbol, description, quantity, cost_basis, market_value "
            "FROM positions WHERE snapshot_date = ? AND user_id = ?",
            (base_date, USER_ID))] if base_date else []
    finally:
        conn.close()
    d = diff_positions(base_rows, rows)
    # a pretend portfolio has no real buys and sells to record
    txns = [] if pct_mode else synthesize_transactions(d, meta["snapshot_date"], source)
    _md(f"Total **{fmt_money(total)}**"
        + (" (pretend)" if pct_mode else " today")
        + f" · {len(d['new'])} new, {len(d['increased']) + len(d['decreased'])} changed, "
          f"{len(d['closed'])} removed since "
          f"{_fmt_date(base_date) if base_date else 'nothing yet'}.")
    st.caption(NOT_KEPT)
    if st.button("Save holdings", type="primary", key=key):
        try:
            _manual_save(meta, rows, totals, txns, source)
        except DBError as exc:
            st.error(f"Saving failed, nothing was changed: {exc}")
        else:
            st.session_state["import_flash"] = (f"Saved {len(rows)} holding(s) for "
                                  f"{_fmt_date(meta['snapshot_date'])}.")
            if after:
                after()
            _after_import()
            st.rerun()


@st.dialog("Add or update holdings", width="large", on_dismiss=_dialog_closed)
def _manual_dialog(current_positions, current_cash, current_source=None):
    """Type in holdings (no file needed); saved as today's snapshot, like an import.
    Shares mode records real holdings; Percentages mode records only each
    holding's share of a pretend total."""
    st.session_state["dialog_open"] = True  # live prices wait (see _live_status)
    _manual_rows_init(current_positions, current_cash, current_source)
    ss = st.session_state
    st.caption(":material/lock: " + TRUST_LINE)
    _empty = not any((ss.get(f"me_sym_{i}") or "").strip() for i in ss["me_ids"])
    with st.expander(":material/content_paste: Paste from your brokerage",
                     expanded=_empty or bool(ss.get("me_paste_msg"))):
        st.caption("On your brokerage's website, select your positions table, copy it, and "
                   "paste it here. The app reads it itself - no AI - and keeps only symbols, "
                   "share counts and cost. The pasted text isn't saved.")
        st.text_area("Pasted positions", key="me_paste", height=120,
                     label_visibility="collapsed",
                     placeholder="VTI   10\nBND   25\n...or paste a whole table")
        st.button("Fill in from pasted text", key="me_paste_btn", on_click=_manual_from_paste)
        _pm = ss.pop("me_paste_msg", None)
        if _pm:
            getattr(st, _pm[0])(_pm[1])
    _render_screenshot_reader()
    st.segmented_control("How to enter them", ["Shares", "Percentages"], key="me_mode",
                         required=True, on_change=lambda: ss.pop("me_review", None))
    pct_mode = ss.get("me_mode") == "Percentages"
    if pct_mode:
        st.caption("No real amounts: give each holding's share of the portfolio, and the app "
                   "works with a pretend total. Allocation, the stock / bond mix, risk and "
                   "projections all work; gains are tracked from today.")
    else:
        st.caption("For any brokerage, or no file at all. Add each holding - its value comes "
                   "from today's price. Saving records today's snapshot; to update later, "
                   "open this again and change what's different.")
    types = list(manual_entry.TYPES)
    for i in list(ss["me_ids"]):
        with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
            st.text_input("Account", key=f"me_acct_{i}", width=150)
            st.text_input("Symbol", key=f"me_sym_{i}", width=100, placeholder="VTI")
            if pct_mode:
                _manual_number("% of portfolio", f"pct_{i}", max_value=100.0, step=5.0,
                               format="%.1f", width=150)
            else:
                _manual_number("Shares", f"qty_{i}", step=1.0, format="%.4f", width=130)
                _manual_number("Total cost", f"cost_{i}", step=100.0, format="%.2f", width=140,
                               help="What you paid in total (optional) - for gain and loss.")
            st.selectbox("Type", types, key=f"me_type_{i}", width=130)
            st.button(":material/close:", key=f"me_del_{i}", type="tertiary",
                      on_click=_manual_remove, args=("me_ids", i), help="Remove this row")
    st.button(":material/add: Add another holding", key="me_add", type="tertiary",
              on_click=_manual_add_row)
    if pct_mode:
        with st.container(horizontal=True, gap="small"):
            _manual_number("Cash %", "cash_pct", max_value=100.0, step=5.0, format="%.1f",
                           width=150)
            _manual_number("Pretend total", "total", min_value=1.0, step=1000.0, format="%.0f",
                           width=180, help="Any amount - it only sets the scale of the numbers "
                                           "shown.")
    else:
        st.markdown("**Cash** (optional)")
        for i in list(ss["me_cash_ids"]):
            with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
                st.text_input("Account", key=f"me_cacct_{i}", width=150)
                _manual_number("Cash", f"cash_{i}", step=100.0, format="%.2f", width=160)
                st.button(":material/close:", key=f"me_cdel_{i}", type="tertiary",
                          on_click=_manual_remove, args=("me_cash_ids", i), help="Remove")
        st.button(":material/add: Add cash for another account", key="me_add_cash",
                  type="tertiary", on_click=_manual_add_cash)

    holdings, cash_rows = _manual_form_rows()
    if pct_mode:
        clean, cash_pct, errors = manual_entry.validate_weights(
            holdings, ss["me_vals"].get("cash_pct"), ss["me_vals"].get("total"))
    else:
        clean, cash, errors = manual_entry.validate(holdings, cash_rows)
    if st.button("Look up prices and review", type="primary", key="me_review_btn"):
        if errors:
            ss.pop("me_review", None)
            st.error("  \n".join(errors))
        else:
            known = {p["symbol"]: p.get("description") for p in current_positions}
            with st.spinner("Looking up prices..."):
                found = manual_entry.lookup(
                    [h["symbol"] for h in clean],
                    finnhub_quote=manual_entry.finnhub_price(resolve_key(None, ENV_PATH)),
                    yahoo_info=manual_entry.yahoo_price_and_name, known_names=known)
            ss["me_review"] = (manual_entry.build_weights(clean, cash_pct,
                                                          ss["me_vals"]["total"], found)
                               if pct_mode else manual_entry.build(clean, cash, found))
    review = ss.get("me_review")
    if not review:
        return
    meta, rows, totals, price_errors = review
    if price_errors:
        st.error("  \n".join(price_errors))
        return
    _review_and_save(meta, rows, totals,
                     manual_entry.PCT_SOURCE if pct_mode else manual_entry.SOURCE,
                     pct_mode=pct_mode, key="me_save", after=_manual_clear)


def _load_sample():
    c = connect(DB)
    try:
        sample_data.load(c, USER_ID)
    finally:
        c.close()
    st.session_state["import_flash"] = ("Loaded an example portfolio - explore freely. Clear it "
                                        "any time from the banner at the top.")
    _after_import()


def _clear_sample():
    c = connect(DB)
    try:
        sample_data.clear(c, USER_ID)
    finally:
        c.close()
    st.session_state["import_flash"] = "Example portfolio removed."
    _after_import()


CSV_FIELDS = ("symbol", "quantity", "cost", "avg_cost", "value", "percent", "account",
              "account_number", "description")


def _import_csv_file(src_path, source_name):
    """A positions CSV from any brokerage - one path for every file
    (csv_import.py): find the table, check the columns (matched by name or a
    remembered layout; the AI only if asked, from column names and cell kinds),
    then the same review and save as every other way of adding holdings."""
    ss = st.session_state
    if not os.path.isfile(src_path):
        st.error(f"No file at: {src_path}")
        return
    with open(src_path, "rb") as fh:
        rows = csv_import.read_rows(fh.read())
    header_i, problem = csv_import.find_header(rows)
    if problem == "transactions":
        st.warning("This looks like **transaction history** (buys and sells), not your current "
                   "holdings. Export your **Positions** or **Holdings** instead - or copy the "
                   "positions table from your brokerage's website and use **Paste or type "
                   "holdings**.")
        return
    if header_i is None:
        header_i = csv_import.guess_header(rows)
    if header_i is None:
        st.error("Couldn't find a table of holdings in this file. Try your brokerage's "
                 "Positions export, or paste the positions table instead.")
        return
    header = rows[header_i]
    sig = csv_import.signature(header)
    conn = connect(DB)
    try:
        known = csv_import.remembered(conn, header)
    finally:
        conn.close()
    mapping = known or csv_import.auto_mapping(header)
    ai_key = f"csv_ai_{sig[:12]}"
    if ss.get(ai_key):
        mapping = {**mapping, **ss[ai_key]}
    quota = (_ai_status("csv") if not csv_import.usable(mapping) and _anthropic_key()
             and ai_key not in ss else None)  # this month's allowance (ai_usage.py)
    if quota and not quota["ok"]:
        st.caption(ai_usage.used_up_text(quota, "csv") + " Choose the columns below.")
    elif quota:
        if st.button(":material/auto_awesome: Let AI guess the columns", key=f"{ai_key}_btn",
                     help="Sends only the column names and what kind of thing each cell is "
                          "(text, number, money) - never your holdings or amounts."
                          + (f" {ai_usage.left_text(quota, 'csv').capitalize()}."
                             if quota["limit"] else "")):
            _ai_record("csv")
            with st.spinner("Working out the columns..."):
                ss[ai_key] = csv_import.ai_mapping(
                    header, csv_import.sample_shapes(rows, header_i), _anthropic_key()) or {}
            mapping = {**mapping, **ss[ai_key]}
            if not ss[ai_key]:
                st.warning("The AI couldn't tell either - choose the columns below.")

    names = [f"{c or '(blank)'}  ·  column {i + 1}" for i, c in enumerate(header)]
    ver = "ai" if ss.get(ai_key) else "auto"  # new widgets when the AI's guess arrives
    with st.expander("Check the columns", expanded=not (known and csv_import.usable(mapping))):
        st.caption("Which column holds what. Only these are read; every other column is "
                   "ignored." + (" This layout was remembered from an earlier file." if known
                                 else ""))
        cols = st.columns(3)
        chosen = {}
        for n, field in enumerate(CSV_FIELDS):
            pick = cols[n % 3].selectbox(
                csv_import.LABELS.get(field, "Account number"), [None, *range(len(header))],
                index=(mapping[field] + 1) if field in mapping else 0,
                format_func=lambda i: "—" if i is None else names[i],
                key=f"csvmap_{sig[:10]}_{ver}_{field}")
            if pick is not None:
                chosen[field] = pick
        # the optional extras (dividends, earnings, day change ...) come along
        # when the file names them; they aren't worth a dropdown each
        chosen.update({f: i for f, i in mapping.items() if f not in CSV_FIELDS})
    if not csv_import.usable(chosen):
        st.info("Choose at least the **Symbol** column and **Shares** (or **Value**).")
        return
    found = csv_import.parse(rows, chosen, filename=os.path.basename(source_name.replace("upload: ", "")))
    if not found["holdings"]:
        st.warning("No holdings were found with these columns - check the choices above.")
        return
    if found["mode"] == "Percentages":
        st.info("This file only has percentages, no share counts. Use **Paste or type holdings** "
                "in the sidebar and its Percentages mode instead.")
        return

    meta, prow, totals = csv_import.to_snapshot(found, account_default=manual_entry.DEFAULT_ACCOUNT)
    # the file's own values where it has them; today's price for the rest
    unpriced = [r["symbol"] for r in prow if r["market_value"] is None]
    if unpriced:
        pkey = f"csv_prices_{sig[:10]}"
        if pkey not in ss:
            with st.spinner("Looking up prices..."):
                ss[pkey] = manual_entry.lookup(
                    unpriced, finnhub_quote=manual_entry.finnhub_price(resolve_key(None, ENV_PATH)),
                    yahoo_info=manual_entry.yahoo_price_and_name)
        for r in prow:
            got = ss[pkey].get(r["symbol"]) or {}
            if r["market_value"] is None and got.get("price") and r["quantity"]:
                r["market_value"] = round(got["price"] * r["quantity"], 2)
                r["description"] = r["description"] or got.get("name")
        still = [r["symbol"] for r in prow if r["market_value"] is None]
        if still:
            st.error("No price found for " + ", ".join(still) + " - check those symbols.")
            return
    cash = sum(t["cash_value"] or 0 for t in totals.values())
    _md(f"Found **{len(prow)} holding(s)**" + (f" and {fmt_money(cash)} cash" if cash else "")
        + f" from {_fmt_date(meta['snapshot_date'])}.")
    meta["as_of_text"] = meta["as_of_text"] or \
        f"Imported from {os.path.basename(source_name.replace('upload: ', ''))}"

    def _remember_layout():
        c = connect(DB)
        try:
            csv_import.remember(c, header, chosen)  # column names only
        finally:
            c.close()
    _review_and_save(meta, prow, totals, source_name, key="csv_save", after=_remember_layout)


@st.dialog("Import a positions CSV", width="large", on_dismiss=_dialog_closed)
def _import_dialog():
    """Upload a positions export from any brokerage; check it; save it."""
    st.session_state["dialog_open"] = True  # live prices wait (see _live_status)
    st.caption("Upload your brokerage's **Positions** (or Holdings) export - any brokerage. "
               "You'll check it before anything is saved.")
    st.caption(":material/lock: " + TRUST_LINE)
    up = st.file_uploader("Positions export (.csv)", type=["csv"], key="csv_upload")
    # A path on "this machine" is only meaningful running locally - on the
    # hosted app it would be a path on the server, which users must not read.
    path_in = "" if pgcompat.is_postgres_dsn(DB) else st.text_input(
        "…or a path to a CSV on this machine",
        key="csv_path",
        placeholder="C:\\Users\\you\\Downloads\\positions.csv",
    ).strip().strip('"')

    if up is not None:
        with temp_upload(up.name, up.getbuffer()) as src_path:  # deleted right after
            _import_csv_file(src_path, upload_label(up.name))
    elif path_in:
        _import_csv_file(path_in, os.path.abspath(path_in))
