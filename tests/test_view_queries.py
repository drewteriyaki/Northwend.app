"""The reads that used to sit in views/ as SQL (Step 8 Phase 3, no SQL in
pages): each is a module function now, tested here on a scratch database -
what it returns, and that a per-account read never returns another
account's rows.

    python -m unittest tests.test_view_queries        (from the repo root)
"""

import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import account_map  # noqa: E402
import accounts  # noqa: E402
import admin  # noqa: E402
import ai_usage  # noqa: E402
import auth  # noqa: E402
import overview  # noqa: E402
import perf  # noqa: E402
import portfolio  # noqa: E402
import proposals  # noqa: E402
import reports  # noqa: E402
import txn_import  # noqa: E402


class _DB(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_viewq_")
        self.db = os.path.join(self.dir, "t.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.conn = portfolio.connect(self.db)
        self.ann = auth.create_user(self.conn, "ann", "pw-123456789")
        self.bo = auth.create_user(self.conn, "bo", "pw-123456789")

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _position(self, user_id, account, symbol, day="2026-09-01"):
        self.conn.execute("INSERT INTO positions (snapshot_date, account, symbol, market_value, "
                          "user_id) VALUES (?, ?, ?, 100.0, ?)", (day, account, symbol, user_id))

    def _txn(self, user_id, day, action, symbol="VTI"):
        self.conn.execute("INSERT INTO transactions (account, trade_date, action, symbol, "
                          "user_id) VALUES ('Brokerage ...123', ?, ?, ?, ?)",
                          (day, action, symbol, user_id))

    def _bar(self, ticker, day, close, adj=None):
        self.conn.execute("INSERT INTO daily_bars (ticker, date, close, adj_close) "
                          "VALUES (?, ?, ?, ?)", (ticker, day, close, adj))


# --------------------------------------------------------------------------- #
# Account (views/account.py) and messages (views/clients.py): auth
# --------------------------------------------------------------------------- #
class AuthReadTests(_DB):

    def test_account_row_is_the_login_own(self):
        c = self.conn
        c.execute("UPDATE users SET email = 'ann@example.com', display_name = 'Ann' "
                  "WHERE id = ?", (self.ann,))
        c.execute("UPDATE users SET email = 'bo@example.com' WHERE id = ?", (self.bo,))
        row = auth.account_row(c, self.ann)
        self.assertEqual((row["username"], row["email"], row["display_name"]),
                         ("ann", "ann@example.com", "Ann"))
        for k in ("email_verified_at", "created_at", "last_login_at"):
            self.assertIn(k, row.keys())
        self.assertEqual(auth.account_row(c, self.bo)["email"], "bo@example.com")
        self.assertIsNone(auth.account_row(c, 9999))

    def test_live_sessions_count_only_this_login_and_unexpired(self):
        c = self.conn
        now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
        auth.create_session(c, self.ann, now=now)
        auth.create_session(c, self.ann, now=now)
        auth.create_session(c, self.bo, now=now)
        self.assertEqual(auth.live_sessions(c, self.ann, now=now), 2)
        self.assertEqual(auth.live_sessions(c, self.bo, now=now), 1)
        later = now + timedelta(days=auth.SESSION_DAYS + 1)
        self.assertEqual(auth.live_sessions(c, self.ann, now=later), 0)
        self.assertEqual(auth.live_sessions(c, 9999, now=now), 0)
        # without `now`, the clock (these sessions started in the past)
        self.assertIsInstance(auth.live_sessions(c, self.ann), int)

    def test_confirmed_emails_need_a_confirmed_address_and_a_sign_in(self):
        c = self.conn
        cy = auth.create_user(c, "cy", "pw-123456789")
        dee = auth.create_user(c, "dee", "pw-123456789")
        stamp = "2026-10-01 10:00:00"
        c.execute("UPDATE users SET email = ?, email_verified_at = ?, last_login_at = ? "
                  "WHERE id = ?", ("ann@example.com", stamp, stamp, self.ann))
        c.execute("UPDATE users SET email = ?, email_verified_at = ?, last_login_at = ? "
                  "WHERE id = ?", ("bo@example.com", stamp, stamp, self.bo))
        c.execute("UPDATE users SET email = 'cy@example.com', last_login_at = ? WHERE id = ?",
                  (stamp, cy))                                     # not confirmed
        c.execute("UPDATE users SET email = 'dee@example.com', email_verified_at = ? "
                  "WHERE id = ?", (stamp, dee))                    # never signed in
        self.assertEqual(auth.confirmed_emails(c, [self.bo, cy, dee, self.ann]),
                         ["ann@example.com", "bo@example.com"])   # id order
        self.assertEqual(auth.confirmed_emails(c, [self.bo]), ["bo@example.com"])
        self.assertEqual(auth.confirmed_emails(c, []), [])


# --------------------------------------------------------------------------- #
# The Clients page (views/clients.py): overview, proposals, reports
# --------------------------------------------------------------------------- #
class BookReadTests(_DB):

    def test_held_symbols_only_for_the_ids_given(self):
        self._position(self.ann, "A", "VTI")
        self._position(self.ann, "A", "BND", day="2026-08-01")
        self._position(self.ann, "B", "VTI")
        self._position(self.bo, "A", "QQQ")
        self.assertEqual(sorted(overview.held_symbols(self.conn, [self.ann])), ["BND", "VTI"])
        self.assertEqual(sorted(overview.held_symbols(self.conn, (self.ann, self.bo))),
                         ["BND", "QQQ", "VTI"])
        self.assertEqual(overview.held_symbols(self.conn, []), [])

    def test_login_facts_only_for_the_ids_given(self):
        self.conn.execute("UPDATE users SET last_login_at = '2026-10-01 09:00:00', "
                          "email = 'ann@example.com' WHERE id = ?", (self.ann,))
        logins, emails = overview.login_facts(self.conn, [self.ann])
        self.assertEqual(logins, {self.ann: "2026-10-01 09:00:00"})
        self.assertEqual(emails, {self.ann: "ann@example.com"})
        logins, emails = overview.login_facts(self.conn, [self.ann, self.bo])
        self.assertEqual(set(logins), {self.ann, self.bo})
        self.assertIsNone(logins[self.bo])
        self.assertEqual(overview.login_facts(self.conn, []), ({}, {}))

    def test_open_counts_shared_and_accepted_not_archived(self):
        c = self.conn
        adv = auth.create_user(c, "adv", "pw-123456789")

        def add(client, status, archived=None):
            c.execute("INSERT INTO proposals (advisor_id, client_id, title, mix_json, status, "
                      "created_at, updated_at, archived_at) VALUES (?, ?, 't', '{}', ?, "
                      "'2026-10-01', '2026-10-01', ?)", (adv, client, status, archived))
        add(self.ann, "shared")
        add(self.ann, "shared")
        add(self.ann, "accepted")
        add(self.ann, "draft")
        add(self.ann, "declined")
        add(self.ann, "shared", archived="2026-10-02 00:00:00")
        add(self.bo, "accepted")
        self.assertEqual(proposals.open_counts(c, [self.ann]),
                         {self.ann: {"shared": 2, "accepted": 1}})
        self.assertEqual(proposals.open_counts(c, [self.ann, self.bo])[self.bo], {"accepted": 1})
        self.assertEqual(proposals.open_counts(c, []), {})

    def test_latest_labels_newest_report_per_client(self):
        c = self.conn
        adv = auth.create_user(c, "adv", "pw-123456789")

        def add(client, label):
            c.execute("INSERT INTO progress_reports (advisor_id, client_id, period_label, "
                      "period_start, period_end, facts_json, created_at) VALUES "
                      "(?, ?, ?, '2026-07-01', '2026-09-30', '{}', '2026-10-01')",
                      (adv, client, label))
        add(self.ann, "Q2 2026")
        add(self.bo, "Q2 2026")
        add(self.ann, "Q3 2026")
        self.assertEqual(reports.latest_labels(c, [self.ann]), {self.ann: "Q3 2026"})
        self.assertEqual(reports.latest_labels(c, [self.ann, self.bo]),
                         {self.ann: "Q3 2026", self.bo: "Q2 2026"})
        cy = auth.create_user(c, "cy", "pw-123456789")
        self.assertEqual(reports.latest_labels(c, [cy]), {})
        self.assertEqual(reports.latest_labels(c, []), {})


# --------------------------------------------------------------------------- #
# Account map nudge, Activity, Your kit, the activity import
# --------------------------------------------------------------------------- #
class OwnRowsTests(_DB):

    def test_account_map_exists_per_login(self):
        self.assertFalse(account_map.exists(self.conn, self.ann))
        account_map.save_family(self.conn, self.bo, "Call my sister.")
        self.assertTrue(account_map.exists(self.conn, self.bo))
        self.assertFalse(account_map.exists(self.conn, self.ann))

    def test_all_for_newest_first_own_rows_only(self):
        self._txn(self.ann, "2026-09-01", "BUY")
        self._txn(self.ann, "2026-09-03", "SELL")
        self._txn(self.ann, "2026-09-03", "DIV")
        self._txn(self.bo, "2026-09-05", "BUY", symbol="QQQ")
        rows = txn_import.all_for(self.conn, self.ann)
        self.assertEqual([(r["trade_date"], r["action"]) for r in rows],
                         [("2026-09-03", "DIV"), ("2026-09-03", "SELL"), ("2026-09-01", "BUY")])
        self.assertTrue(all(isinstance(r, dict) and r["user_id"] == self.ann for r in rows))
        self.assertEqual(len(txn_import.all_for(self.conn, self.bo)), 1)

    def test_sell_dates_own_sells_only(self):
        self._txn(self.ann, "2026-09-01", "BUY")
        self._txn(self.ann, "2026-09-03", "SELL")
        self._txn(self.bo, "2026-09-04", "SELL")
        self.assertEqual(txn_import.sell_dates(self.conn, self.ann), ["2026-09-03"])
        self.assertEqual(txn_import.sell_dates(self.conn, self.bo), ["2026-09-04"])

    def test_logged_values_own_rows_with_a_value(self):
        c = self.conn
        for uid, at, v in ((self.ann, "2026-09-01T10:00:00Z", 1000.0),
                           (self.ann, "2026-09-02T10:00:00Z", None),
                           (self.bo, "2026-09-03T10:00:00Z", 5.0)):
            c.execute("INSERT INTO value_log (logged_at, portfolio_value, user_id) "
                      "VALUES (?, ?, ?)", (at, v, uid))
        self.assertEqual(perf.logged_values(c, self.ann), [("2026-09-01T10:00:00Z", 1000.0)])
        self.assertEqual(perf.logged_values(c, self.bo), [("2026-09-03T10:00:00Z", 5.0)])
        c.commit()
        self.assertEqual(perf.logged_values(self.db, self.ann),           # a path works too
                         [("2026-09-01T10:00:00Z", 1000.0)])

    def test_held_account_names_own_only_alphabetical(self):
        self._position(self.ann, "Roth ...789", "VTI")
        self._position(self.ann, "Brokerage ...123", "VTI", day="2026-08-01")
        self._position(self.ann, "Brokerage ...123", "BND")
        self._position(self.bo, "Bo's IRA", "QQQ")
        self.assertEqual(accounts.held(self.conn, self.ann), ["Brokerage ...123", "Roth ...789"])
        self.assertEqual(accounts.held(self.conn, self.bo), ["Bo's IRA"])

    def test_snapshot_positions_and_cash_one_snapshot_own_only(self):
        # Home's holdings (dashboard.load): one snapshot, this account's rows only
        self._position(self.ann, "Roth ...789", "VTI")
        self._position(self.ann, "Brokerage ...123", "BND")
        self._position(self.ann, "Brokerage ...123", "AAPL", day="2026-08-01")
        self._position(self.bo, "Brokerage ...123", "QQQ")
        for uid, acct, cash in ((self.ann, "Brokerage ...123", 250.0),
                                (self.ann, "Roth ...789", None), (self.bo, "Brokerage ...123", 9.0)):
            self.conn.execute("INSERT INTO account_totals (snapshot_date, account, cash_value, "
                              "user_id) VALUES ('2026-09-01', ?, ?, ?)", (acct, cash, uid))
        rows = portfolio.snapshot_positions(self.conn, self.ann, "2026-09-01")
        self.assertEqual([(r["account"], r["symbol"]) for r in rows],
                         [("Brokerage ...123", "BND"), ("Roth ...789", "VTI")])
        self.assertEqual(portfolio.snapshot_cash(self.conn, self.ann, "2026-09-01"),
                         {"Brokerage ...123": 250.0, "Roth ...789": 0.0})
        self.assertEqual(portfolio.snapshot_positions(self.conn, self.ann, "2026-07-01"), [])


# --------------------------------------------------------------------------- #
# Shared market data: the storm note, Learn's practice prices, Admin
# --------------------------------------------------------------------------- #
class MarketReadTests(_DB):

    def test_closes_since_by_ticker_then_date(self):
        self._bar("VTI", "2026-08-30", 99.0)
        self._bar("VTI", "2026-09-02", 101.0)
        self._bar("VTI", "2026-09-01", 100.0)
        self._bar("VTI", "2026-09-03", None)
        self._bar("BND", "2026-09-01", 70.0)
        self._bar("QQQ", "2026-09-01", 400.0)
        rows = perf.closes_since(self.conn, ["VTI", "BND"], "2026-09-01")
        self.assertEqual([(r["ticker"], r["date"], r["close"]) for r in rows],
                         [("BND", "2026-09-01", 70.0), ("VTI", "2026-09-01", 100.0),
                          ("VTI", "2026-09-02", 101.0)])
        self.assertEqual(perf.closes_since(self.conn, [], "2026-09-01"), [])

    def test_full_adjusted_closes_prefer_adjusted(self):
        self._bar("VTI", "2026-09-02", 101.0, adj=100.5)
        self._bar("VTI", "2026-09-01", 100.0)
        self._bar("BND", "2026-09-01", None, None)
        out = perf.full_adjusted_closes(self.conn, ["VTI", "BND", "ZZZ"])
        self.assertEqual(list(out), ["VTI", "BND", "ZZZ"])
        self.assertEqual(out["VTI"], [("2026-09-01", 100.0), ("2026-09-02", 100.5)])
        self.assertEqual(out["BND"], [])
        self.assertEqual(out["ZZZ"], [])

    def test_data_freshness_and_flagged_admins(self):
        c = self.conn
        self.assertEqual(admin.data_freshness(c), (None, None))
        c.execute("INSERT INTO price_history (ticker, price, fetched_at) VALUES "
                  "('VTI', 1.0, '2026-10-01T10:00:00Z'), ('VTI', 2.0, '2026-10-02T10:00:00Z')")
        self._bar("VTI", "2026-09-30", 1.0)
        self._bar("BND", "2026-10-01", 1.0)
        self.assertEqual(admin.data_freshness(c), ("2026-10-02T10:00:00Z", "2026-10-01"))
        self.assertEqual(admin.flagged_admins(c), [])
        admin.set_admin(c, "bo", True)
        admin.set_admin(c, "ann", True)
        self.assertEqual(admin.flagged_admins(c), ["ann", "bo"])
        admin.set_admin(c, "bo", False)
        self.assertEqual(admin.flagged_admins(c), ["ann"])

    def test_month_rows_one_month_by_login_then_kind(self):
        c = self.conn
        for uid, month, kind, used in ((self.bo, "2026-10", "chat", 3),
                                       (self.ann, "2026-10", "plan", 1),
                                       (self.ann, "2026-10", "chat", 2),
                                       (self.ann, "2026-09", "chat", 9)):
            c.execute("INSERT INTO ai_usage (user_id, month, kind, used, cost_micro) "
                      "VALUES (?, ?, ?, ?, 10)", (uid, month, kind, used))
        rows = ai_usage.month_rows(c, "2026-10")
        self.assertEqual([(r["username"], r["kind"], r["used"], r["cost_micro"]) for r in rows],
                         [("ann", "chat", 2, 10), ("ann", "plan", 1, 10), ("bo", "chat", 3, 10)])
        self.assertEqual(ai_usage.month_rows(c, "2026-08"), [])


if __name__ == "__main__":
    unittest.main()
