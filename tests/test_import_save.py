"""Saving holdings (views/holdings_input.py's review and save): what changed,
the buys and sells worked out from it, and account numbers kept to their last
3 digits everywhere. The save is the same three steps the view takes:
portfolio.previous_snapshot, changes.compare, then write_snapshot and
txn_import.save_worked_out. The last class drives the app itself (AppTest).

    python -m unittest tests.test_import_save        (from the repo root)
"""

import math
import os
import re
import shutil
import sys
import tempfile
import types
import unittest
import unittest.mock
from datetime import date, datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import accounts  # noqa: E402
import auth  # noqa: E402
import changes  # noqa: E402
import csv_import  # noqa: E402
import manual_entry  # noqa: E402
import perf  # noqa: E402
import portfolio  # noqa: E402
import sample_data  # noqa: E402
import txn_import  # noqa: E402

BROKERS = os.path.join(os.path.dirname(__file__), "fixtures", "brokers")
SCHWAB = os.path.join(os.path.dirname(__file__), "fixtures", "sample_positions.csv")
# positions exports, and the columns to read when the names don't say
POSITION_FILES = {"vanguard_download.csv": None, "fidelity_positions.csv": None,
                  "etrade_portfolio.csv": None,
                  "odd_layout.csv": {"symbol": 0, "quantity": 1, "cost": 2, "value": 3}}
# a 401(k) export with a pooled fund known only by its CUSIP
FIDELITY_401K = (
    "Account Number,Account Name,Symbol,Description,Quantity,Last Price,Current Value,"
    "Cost Basis Total\n"
    "71234,ACME CORP 401(K) PLAN,FXAIX,FIDELITY 500 INDEX FUND,120.512,$245.10,$29537.49,"
    "$22000.00\n"
    "71234,ACME CORP 401(K) PLAN,31617E471,FID CONTRAFUND POOL CL 2,180.0,$28.40,$5112.00,"
    "$4200.00\n")


def read_file(path, mapping=None, day=None):
    """A positions file as the CSV import reads it: (meta, rows, totals, parsed)."""
    with open(path, "rb") as fh:
        rows = csv_import.read_rows(fh.read())
    hi, _ = csv_import.find_header(rows)
    hi = hi if hi is not None else csv_import.guess_header(rows)
    found = csv_import.parse(rows, mapping or csv_import.auto_mapping(rows[hi]),
                             today=day or date(2026, 9, 30))
    meta, prow, totals = csv_import.to_snapshot(found, account_default="My account")
    return meta, prow, totals, found


def dated(meta, rows, day):
    """The same holdings, saved as of `day`."""
    meta = {**meta, "snapshot_date": day.isoformat()}
    return meta, [{**r, "snapshot_date": day.isoformat()} for r in rows]


def save(conn, user_id, meta, rows, totals, src="upload: test.csv"):
    """The view's review and save: returns (diff, the trades worked out)."""
    _, base_rows, base_accounts = portfolio.previous_snapshot(conn, user_id, meta["snapshot_date"])
    d, txns = changes.compare(base_rows, rows, meta["snapshot_date"], src,
                              old_accounts=base_accounts, new_accounts=totals)
    portfolio.write_snapshot(conn, user_id, meta, rows, totals, src)
    txn_import.save_worked_out(conn, user_id, meta["snapshot_date"], txns)
    conn.commit()
    return d, txns


class _DB(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_save_")
        self.db = os.path.join(self.dir, "test.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.conn = portfolio.connect(self.db)
        self.user_id = auth.create_user(self.conn, "saver", "pw-123456789")

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def trades(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT account, action, symbol, quantity, realized_gain FROM transactions "
            "WHERE user_id = ? ORDER BY id", (self.user_id,))]


class WhatChangedTests(_DB):

    def test_the_same_file_again_changes_nothing(self):
        meta, rows, totals, _ = read_file(os.path.join(BROKERS, "vanguard_download.csv"))
        save(self.conn, self.user_id, *dated(meta, rows, date(2026, 9, 1)), totals)
        d, txns = save(self.conn, self.user_id, *dated(meta, rows, date(2026, 9, 2)), totals)
        self.assertEqual((len(d["new"]), len(d["closed"]), len(d["increased"]),
                          len(d["decreased"]), len(d["unchanged"])), (0, 0, 0, 0, 3))
        self.assertEqual(txns, [])
        self.assertEqual(self.trades(), [])
        # a real change is still worked out, in the account as saved
        more = [{**r, "quantity": r["quantity"] + 2} if r["symbol"] == "VTSAX" else r
                for r in rows]
        d, txns = save(self.conn, self.user_id, *dated(meta, more, date(2026, 9, 3)), totals)
        self.assertEqual([(t["account"], t["action"], t["symbol"], t["quantity"])
                          for t in self.trades()], [("...678", "BUY", "VTSAX", 2.0)])

    def test_a_first_save_is_where_an_account_starts_not_buys(self):
        clean, cash, _ = manual_entry.validate(
            [{"Account": "Roth", "Symbol": "VTI", "Shares": 10, "Total cost": 2000}], [])
        found = {"VTI": {"price": 300.0}, "SCHD": {"price": 28.0}}
        meta, rows, totals, _ = manual_entry.build(clean, cash, found, today=date(2026, 9, 1))
        _, txns = save(self.conn, self.user_id, meta, rows, totals, manual_entry.SOURCE)
        self.assertEqual(txns, [])                      # the very first save
        # later: one more share of VTI, and a new account with 1,100 SCHD
        clean, cash, _ = manual_entry.validate(
            [{"Account": "Roth", "Symbol": "VTI", "Shares": 11, "Total cost": 2300},
             {"Account": "Brokerage", "Symbol": "SCHD", "Shares": 1100, "Total cost": 28000}], [])
        meta, rows, totals, _ = manual_entry.build(clean, cash, found, today=date(2026, 9, 2))
        d, txns = save(self.conn, self.user_id, meta, rows, totals, manual_entry.SOURCE)
        self.assertEqual(len(d["new"]), 1)              # still shown as new in the review
        self.assertEqual([(t["account"], t["action"], t["symbol"]) for t in self.trades()],
                         [("Roth", "BUY", "VTI")])      # but SCHD wasn't bought that day
        # an account left out of a save wasn't sold off either
        clean, cash, _ = manual_entry.validate(
            [{"Account": "Brokerage", "Symbol": "SCHD", "Shares": 1000, "Total cost": 25000}], [])
        meta, rows, totals, _ = manual_entry.build(clean, cash, found, today=date(2026, 9, 3))
        _, txns = save(self.conn, self.user_id, meta, rows, totals, manual_entry.SOURCE)
        self.assertEqual([(t["account"], t["action"], t["symbol"], t["quantity"]) for t in txns],
                         [("Brokerage", "SELL", "SCHD", 100.0)])

    def test_an_account_with_only_cash_before_records_its_buys(self):
        clean, cash, _ = manual_entry.validate([], [{"Account": "Roth", "Cash": 5000}])
        meta, rows, totals, _ = manual_entry.build(clean, cash, {}, today=date(2026, 9, 1))
        save(self.conn, self.user_id, meta, rows, totals, manual_entry.SOURCE)
        clean, cash, _ = manual_entry.validate([{"Account": "Roth", "Symbol": "VTI", "Shares": 10}],
                                               [{"Account": "Roth", "Cash": 2000}])
        meta, rows, totals, _ = manual_entry.build(clean, cash, {"VTI": {"price": 300.0}},
                                                   today=date(2026, 9, 2))
        _, txns = save(self.conn, self.user_id, meta, rows, totals, manual_entry.SOURCE)
        self.assertEqual([(t["action"], t["symbol"]) for t in txns], [("BUY", "VTI")])

    def test_the_example_portfolio_replaced_by_a_first_import_is_not_sold(self):
        sample_data.load(self.conn, self.user_id, today=date(2026, 9, 1))
        meta, rows, totals, _ = read_file(SCHWAB)
        d, txns = save(self.conn, self.user_id, *dated(meta, rows, date(2026, 9, 2)), totals)
        self.assertEqual((d["closed"], txns, self.trades()), ([], [], []))
        self.assertEqual(portfolio.previous_snapshot(self.conn, self.user_id, "2026-09-03")[0],
                         "2026-09-02")


class AccountNumberTests(_DB):

    def test_no_table_ever_holds_a_full_account_number(self):
        files = [(os.path.join(BROKERS, n), m) for n, m in POSITION_FILES.items()]
        files += [(SCHWAB, None)]
        plain = os.path.join(self.dir, "fid401k.csv")
        with open(plain, "w", encoding="utf-8") as fh:
            fh.write(FIDELITY_401K)
        files += [(plain, None)]
        numbers = set()
        day = date(2026, 1, 1)
        for path, mapping in files:
            meta, rows, totals, found = read_file(path, mapping)
            numbers |= {n for h in found["holdings"] for n in re.findall(r"\d{5,}", h["Account"])}
            for change in range(3):   # first save, the same again, then a change
                day += timedelta(days=1)
                if change == 2:
                    rows = [{**r, "quantity": r["quantity"] + 1} for r in rows[:-1]] or rows
                save(self.conn, self.user_id, *dated(meta, rows, day), totals,
                     f"upload: {os.path.basename(path)}")
            accounts.set_label(self.conn, self.user_id, rows[0]["account"], "Mine")
        self.assertTrue({"12345678", "87654321", "71234"} <= numbers, numbers)
        self.assertTrue(self.trades())               # some trades were worked out
        dump = "\n".join(self.conn.iterdump())
        for n in numbers:
            self.assertNotIn(n, dump)
        for table in portfolio.ACCOUNT_COLUMNS:
            for r in self.conn.execute(f"SELECT DISTINCT account FROM {table}"):
                self.assertEqual(accounts.mask_number(r["account"]), r["account"], table)

    def test_old_rows_are_masked_once_when_the_app_starts(self):
        c, uid = self.conn, self.user_id
        c.execute("INSERT INTO transactions (account, trade_date, action, symbol, user_id) "
                  "VALUES ('12345678', '2026-09-01', 'BUY', 'VTI', ?)", (uid,))
        c.execute("INSERT INTO transactions (account, trade_date, action, symbol, user_id) "
                  "VALUES ('Roth IRA', '2026-09-01', 'BUY', 'VTI', ?)", (uid,))
        for acct in ("Individual Z12345678", "Individual ...999", "Individual 55554999"):
            c.execute("INSERT INTO positions (snapshot_date, account, symbol, quantity, user_id, "
                      "imported_at) VALUES ('2026-09-01', ?, 'VTI', 1, ?, datetime('now'))",
                      (acct, uid))
        c.execute("INSERT INTO account_totals (snapshot_date, account, cash_value, user_id, "
                  "imported_at) VALUES ('2026-09-01', 'Individual Z12345678', 5, ?, "
                  "datetime('now'))", (uid,))
        c.execute("INSERT INTO account_labels (user_id, account, nickname) "
                  "VALUES (?, 'Individual Z12345678', 'Main')", (uid,))
        c.commit()
        c.close()
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))   # the next process start
        self.conn = c = portfolio.connect(self.db)
        self.assertEqual(sorted(r["account"] for r in c.execute("SELECT account FROM transactions")),
                         ["...678", "Roth IRA"])
        self.assertEqual(sorted(r["account"] for r in c.execute("SELECT account FROM positions")),
                         ["Individual ...678", "Individual ...999", "Individual ...999 (2)"])
        self.assertEqual([r["account"] for r in c.execute("SELECT account FROM account_totals")],
                         ["Individual ...678"])
        self.assertEqual([r["account"] for r in c.execute("SELECT account FROM account_labels")],
                         ["Individual ...678"])
        # ("Individual ...999" already held VTI that day: kept apart, not merged.)
        self.assertEqual(portfolio._mask_saved_accounts(c), {})   # nothing left to do


class LastVisitTests(_DB):

    def test_since_your_last_visit_starts_again_after_a_save(self):
        perf.log_open(self.db, self.user_id, {"portfolio_value": 100000.0}, min_gap_sec=0)
        hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.conn.execute("UPDATE value_log SET logged_at = ?", (hour_ago,))
        self.conn.commit()
        self.assertEqual(perf.last_open(self.db, self.user_id)["portfolio_value"], 100000.0)
        clean, cash, _ = manual_entry.validate([{"Symbol": "VTI", "Shares": 10}], [])
        meta, rows, totals, _ = manual_entry.build(clean, cash, {"VTI": {"price": 300.0}})
        save(self.conn, self.user_id, meta, rows, totals, manual_entry.SOURCE)
        self.assertIsNone(perf.last_open(self.db, self.user_id))   # that visit saw other holdings
        perf.log_open(self.db, self.user_id, {"portfolio_value": 3000.0}, min_gap_sec=0)
        self.assertEqual(perf.last_open(self.db, self.user_id)["portfolio_value"], 3000.0)


class SkippedRowTests(unittest.TestCase):

    def test_a_row_without_a_ticker_is_named_not_imported(self):
        rows = csv_import.read_rows(FIDELITY_401K.encode())
        hi, _ = csv_import.find_header(rows)
        found = csv_import.parse(rows, csv_import.auto_mapping(rows[hi]))
        self.assertEqual([h["Symbol"] for h in found["holdings"]], ["FXAIX"])   # as before
        self.assertEqual(found["left_out"], [{"Name": "FID CONTRAFUND POOL CL 2",
                                              "Value": 5112.0, "why": "it has no ticker"}])
        self.assertEqual(csv_import.left_out_text(found["left_out"]),
                         "1 row skipped, not imported: FID CONTRAFUND POOL CL 2 ($5,112.00)"
                         " - it has no ticker.")
        for name, mapping in POSITION_FILES.items():   # nothing made up for the others
            self.assertEqual(read_file(os.path.join(BROKERS, name), mapping)[3]["left_out"], [],
                             name)


class AppSaveTests(unittest.TestCase):
    """The hand-entry window and Home, run with AppTest on a scratch database."""

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or "")) == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_appsave_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.uid = auth.create_user(c, "ann", "pw-123456789")
            clean, cash, _ = manual_entry.validate(
                [{"Symbol": "VTI", "Shares": 10, "Total cost": 2500},
                 {"Symbol": "AAPL", "Shares": 5}], [])          # no cost for AAPL
            meta, rows, totals, _ = manual_entry.build(
                clean, cash, {"VTI": {"price": 300.0}, "AAPL": {"price": 230.0}})
            portfolio.write_snapshot(c, cls.uid, meta, rows, totals, manual_entry.SOURCE)
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _app(self, **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": self.uid, "username": "ann", "page": "Dashboard",
                     "auto_backfilled": True, "income_synced": True, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused")
        patches = [unittest.mock.patch.dict(os.environ, env, clear=True),
                   unittest.mock.patch.object(yfinance, "Ticker", offline),
                   unittest.mock.patch("socket.socket.connect", offline)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return at

    def test_screenshots_are_read_once_and_counted_once(self):
        import streamlit
        at = self._app(open_dialog="manual")
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        reads = []

        def fake_read(images, key, **kw):
            reads.append(len(images))
            return {"holdings": [{"Symbol": "SCHD", "Shares": 3.0, "Total cost": None,
                                  "Percent": None, "Type": None}],
                    "cash": None, "mode": "Shares", "error": None, "answered": True}
        shot = types.SimpleNamespace(name="holdings.png", getvalue=lambda: b"png-bytes")
        real_uploader = streamlit.file_uploader

        def uploader(label, *a, key=None, **kw):
            if key and key.startswith("me_shots_"):
                return [shot]
            return real_uploader(label, *a, key=key, **kw)
        real_rerun = streamlit.rerun

        def rerun(*a, **kw):   # AppTest draws a window in the full run, not as a fragment
            return real_rerun(*a, **{**kw, "scope": "app"})
        for p in (unittest.mock.patch.object(sys.modules["screenshot_read"], "read", fake_read),
                  unittest.mock.patch.object(streamlit, "file_uploader", uploader),
                  unittest.mock.patch.object(streamlit, "rerun", rerun)):
            p.start()
            self.addCleanup(p.stop)
        at.session_state["open_dialog"] = "manual"
        at.run()
        at.checkbox(key="me_shots_ok_0").check()
        at.session_state["open_dialog"] = "manual"
        at.run()
        at.button(key="me_shots_btn").click()
        at.session_state["open_dialog"] = "manual"
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        self.assertEqual(reads, [1])
        self.assertEqual(at.session_state["me_shots_n"], 1)        # a fresh uploader and box
        self.assertNotIn("me_shots_ok_1", [c.key for c in at.checkbox if c.value])
        c = portfolio.connect(self.db)
        try:
            import ai_usage
            self.assertEqual(ai_usage.status(c, self.uid, "screenshot")["used"], 1)
        finally:
            c.close()
        filled = [at.session_state[f"me_sym_{i}"] for i in at.session_state["me_ids"]]
        self.assertEqual(filled, ["SCHD"])

    def test_a_new_hand_entry_row_is_type_other(self):
        at = self._app(open_dialog="manual")
        at.run()
        at.button(key="me_add").click()
        at.session_state["open_dialog"] = "manual"
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        last = at.session_state["me_ids"][-1]
        self.assertEqual(at.session_state[f"me_type_{last}"], "Other")

    def test_home_after_a_save_logs_a_fresh_baseline_and_shows_no_none(self):
        c = portfolio.connect(self.db)
        try:
            perf.log_open(self.db, self.uid, {"portfolio_value": 1.0}, min_gap_sec=0)
            n = c.execute("SELECT COUNT(*) n FROM value_log WHERE user_id = ?",
                          (self.uid,)).fetchone()["n"]
        finally:
            c.close()
        at = self._app(value_rebase=True)   # as _after_import leaves it
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        c = portfolio.connect(self.db)
        try:
            self.assertEqual(c.execute("SELECT COUNT(*) n FROM value_log WHERE user_id = ?",
                                       (self.uid,)).fetchone()["n"], n + 1)   # despite the gap
        finally:
            c.close()
        self.assertNotIn("value_rebase", at.session_state)
        table = at.dataframe[-1].value
        table = getattr(table, "data", table)
        self.assertIn("Cost Basis", table.columns)
        costs = list(table["Cost Basis"])
        self.assertIn("—", costs)                     # AAPL, entered without a cost
        self.assertFalse(any(v is None or (isinstance(v, float) and math.isnan(v)) for v in costs))


if __name__ == "__main__":
    unittest.main()
