"""How many database queries a page makes. Home stays under a cap, and Your
clients reads the whole book at once - more clients, not more queries.
Counts the SQL statements and connections of a page's second run (a rerun:
what every click costs), as in CLAUDE.md's "Testing on scratch data". On
Postgres each statement and each connection is a round trip.

    python -m unittest tests.test_page_queries        (from the repo root)
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import auth  # noqa: E402
import portfolio  # noqa: E402
import sample_data  # noqa: E402
import two_step  # noqa: E402

HOME_QUERIES = 40       # Home's queries on a rerun here: 35 now (39 when written; it was 52)
HOME_CONNECTIONS = 11   # 9 (it was 23)
BOOK_MORE = 12          # Your clients: one client, then this many more ...
BOOK_EXTRA = 2          # ... adds at most this many queries: 0 when written (it was ~8 each)


class PageQueryTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.db = os.path.join(cls.tmp, "queries.db")
        cls.env = unittest.mock.patch.dict(os.environ, {
            "PORTFOLIO_DB": cls.db, "MAIL_DRY_RUN": "1"})
        cls.env.start()
        for key in ("ANTHROPIC_API_KEY", "FINNHUB_API_KEY", "RESEND_API_KEY",
                    "NORTHWEND_ADMINS"):
            os.environ.pop(key, None)
        c = portfolio.connect(cls.db)
        try:
            cls.alice = auth.create_user(c, "alice", "pw-123456789")
            sample_data.load(c, cls.alice)
            cls.carol = auth.create_user(c, "carol", "pw-123456789")  # an advisor
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            dave = auth.create_user(c, "dave", "pw-123456789")
            auth.link_client(c, cls.carol, dave)
            sample_data.load(c, dave)
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _count(self, user_id, username, page, statements=None, **state):
        """(queries, connections) of the page's second run. `statements`: a
        list to collect that run's SQL in."""
        from streamlit.testing.v1 import AppTest
        seen = {"sql": 0, "connect": 0}
        real = sqlite3.connect

        def note(s):
            seen["sql"] += not s.startswith("PRAGMA")
            if statements is not None and not s.startswith("PRAGMA"):
                statements.append(s)

        def counting(*a, **k):
            conn = real(*a, **k)
            seen["connect"] += 1
            conn.set_trace_callback(note)
            return conn

        def offline(*a, **k):
            raise RuntimeError("offline")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": user_id, "username": username, "page": page,
                     "auto_backfilled": True, "income_synced": True, **state}.items():
            at.session_state[k] = v
        with unittest.mock.patch("sqlite3.connect", counting), \
                unittest.mock.patch("socket.socket.connect", offline):
            at.run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
            seen.update(sql=0, connect=0)
            if statements is not None:
                statements.clear()
            at.run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
        return seen["sql"], seen["connect"]

    def test_home_stays_under_its_cap(self):
        queries, connections = self._count(self.alice, "alice", "Dashboard")
        self.assertLessEqual(queries, HOME_QUERIES)
        self.assertLessEqual(connections, HOME_CONNECTIONS)

    def test_the_login_row_is_read_once_a_run(self):
        # the two-step gate's read, handed on to the password check, the email
        # notice and Ask Northwend's allowance (views/two_step.py _gate_read)
        sql = []
        with unittest.mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-not-used"}):
            self._count(self.alice, "alice", "AI Assistant", statements=sql)
        self.assertTrue(any("FROM ai_usage" in s for s in sql), sql)   # the chat was drawn
        self.assertEqual(len([s for s in sql if " FROM users" in s]), 1, sql)
        self.assertEqual(len([s for s in sql if "FROM investor_profiles" in s]), 1, sql)

    def test_your_clients_reads_the_whole_book_at_once(self):
        import advising
        import prefs
        state = {"two_step_ok": self.carol_ok, "active_user_id": self.carol}
        one, one_conns = self._count(self.carol, "carol", "Clients", **state)
        c = portfolio.connect(self.db)
        try:
            for n in range(BOOK_MORE):
                cid = auth.create_user(c, f"client{n:02d}", "pw-123456789")
                auth.link_client(c, self.carol, cid)
                if n % 4 != 3:  # some with no statement yet
                    sample_data.load(c, cid)
                if n % 2 == 0:
                    advising.add_note(c, cid, self.carol, "Next step", "call", "2026-09-01")
                if n % 3 == 0:
                    prefs.save(c, cid, {"class_overrides": {"VTI": "Bonds"}})
        finally:
            c.close()
        many, many_conns = self._count(self.carol, "carol", "Clients", **state)
        self.assertLessEqual(many - one, BOOK_EXTRA)
        self.assertLessEqual(many_conns, one_conns)


class OneReadHelperTests(unittest.TestCase):
    """The helpers that read once give the same answers as the ones they replace."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.c = portfolio.connect(os.path.join(self.tmp, "helpers.db"))

    def tearDown(self):
        self.c.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_login_facts_match_the_four_reads(self):
        import admin
        c = self.c
        uid = auth.create_user(c, "ann", "pw-123456789")
        auth.set_display_name(c, uid, "Ann")
        for adv in (False, True):
            auth.set_advisor(c, "ann", adv)
            with unittest.mock.patch.dict(os.environ, {"NORTHWEND_ADMINS": "ann" if adv else ""}):
                self.assertEqual(auth.login_facts(c, uid), {
                    "stamp": auth.password_stamp(c, uid), "is_advisor": auth.is_advisor(c, uid),
                    "is_admin": admin.is_admin(c, uid), "display_name": auth.display_name(c, uid)})
        self.assertIsNone(auth.login_facts(c, 9999)["stamp"])

    def test_the_gates_row_gives_the_same_answers(self):
        # two_step.status_and_login: the one read the rest of a run reuses
        import advisor
        import ai_usage
        import two_step
        c = self.c
        uid = auth.sign_up(c, "ann@example.com", "pw-123456789", agreed=True, adult=True,
                           terms_version="2026-01-01", seconds_open=30)["user_id"]
        auth.set_display_name(c, uid, "Ann")
        for step in ("unconfirmed", "confirmed", "advisor", "unlimited"):
            if step == "confirmed":
                c.execute("UPDATE users SET email_verified_at = '2026-10-01 10:00:00' WHERE id = ?",
                          (uid,))
            elif step == "advisor":
                auth.set_advisor(c, "ann@example.com", True)
                secret = two_step.new_secret()
                two_step.enable(c, uid, secret, two_step.totp(secret))
            elif step == "unlimited":
                ai_usage.set_unlimited(c, uid, True)
            ai_usage.record(c, uid, "chat")
            state, row = two_step.status_and_login(c, uid)
            self.assertEqual(state, two_step.status(c, uid), step)
            self.assertEqual(auth.login_facts_of(row), auth.login_facts(c, uid), step)
            self.assertEqual(auth.email_status_of(row), auth.email_status(c, uid), step)
            self.assertEqual(ai_usage.status(c, uid, "chat", user=row),
                             ai_usage.status(c, uid, "chat"), step)
        self.assertEqual(two_step.status_and_login(c, 9999),
                         (two_step.status(c, 9999), None))
        self.assertEqual(auth.login_facts_of(None), auth.login_facts(c, 9999))
        advisor.save_profile(c, uid, {"goal": "Retirement"})
        advisor.save_memory(c, uid, "likes index funds")
        for who in (uid, 9999):
            self.assertEqual(advisor.get_profile_and_memory(c, who),
                             (advisor.get_profile(c, who), advisor.get_memory(c, who)))

    def test_month_total_from_moves_read_once(self):
        import plans
        c = self.c
        uid = auth.create_user(c, "ann", "pw-123456789")
        for d, a in (("2026-09-30", 50.0), ("2026-10-01", 100.0), ("2026-10-15", -20.0),
                     ("2026-10-31", 7.5), ("2026-11-01", 900.0)):
            plans.add_contribution(c, uid, d, a, None)
        c.execute("INSERT INTO transactions (user_id, account, trade_date, action, amount, origin) "
                  "VALUES (?, 'B', '2026-10-10', 'DEPOSIT', 300, 'imported')", (uid,))
        c.commit()
        window = plans.imported_window(c, uid)
        moves = plans.money_moves(c, uid, window=window)
        self.assertEqual(moves, plans.money_moves(c, uid))
        for month in (9, 10, 11, 12):
            self.assertEqual(plans.month_total(None, uid, 2026, month, moves=moves),
                             plans.month_total(c, uid, 2026, month))

    def test_book_wide_reads_match_per_client_ones(self):
        import advising
        import reports
        from datetime import date
        c = self.c
        adv = auth.create_user(c, "adv", "pw-123456789")
        auth.set_advisor(c, "adv", True)
        ids = []
        for n in range(3):
            cid = auth.create_user(c, f"client{n}", "pw-123456789")
            auth.link_client(c, adv, cid)
            ids.append(cid)
        advising.set_client_can_import(c, adv, ids[1], True)
        advising.add_note(c, ids[0], adv, "Review", "met", "2026-03-01")
        advising.add_note(c, ids[0], adv, "Review", "met again", "2026-06-01", private=True)
        advising.add_note(c, ids[0], adv, "Note", "later", "2026-09-01")
        reports.save(c, adv, ids[2], label="Q2 2026", start=date(2026, 4, 1),
                     end=date(2026, 6, 30), facts={}, message="")
        self.assertEqual(advising.clients_can_import(c, ids),
                         {i for i in ids if advising.client_can_import(c, i)})
        ends, sent = reports.sent(c, ids)
        for cid in ids:
            notes = advising.list_notes(c, cid, include_private=True)
            self.assertEqual(advising.last_review_in(notes), advising.last_review(c, cid))
            self.assertEqual(ends.get(cid), reports.last_end(c, cid))
        self.assertEqual(sent, {(ids[2], "Q2 2026")})

    def _book(self):
        """An advisor's book of varied clients: (advisor id, client ids)."""
        import advising
        import advisor
        import manual_entry
        import plans
        import prefs
        from datetime import date
        c = self.c
        adv = auth.create_user(c, "adv", "pw-123456789")
        auth.set_advisor(c, "adv", True)
        ids = []
        for n in range(6):
            cid = auth.create_user(c, f"client{n}", "pw-123456789")
            auth.link_client(c, adv, cid)
            ids.append(cid)
        a, empty, pcts, moved, plain, two = ids
        # the example portfolio, with a plan, notes, settings and part of a profile
        sample_data.load(c, a)
        plans.save_plan(c, a, {"goal_type": "Retirement", "target_amount": 500000,
                               "target_date": "2040-01-01", "monthly_contribution": 500,
                               "target_alloc": {"Stocks": 70, "Bonds": 30}}, adv)
        advising.add_note(c, a, adv, "Review", "met", "2026-03-01")
        advising.add_note(c, a, adv, "Next step", "call", "2026-04-01", private=True)
        prefs.save(c, a, {"rules": {"day_move": 1.0}, "class_overrides": {"VTI": "Bonds"}})
        advisor.save_profile(c, a, {"goal": "retire", "risk_tolerance": "moderate"})
        # no holdings at all, but a full profile and a plan without a goal
        advisor.save_profile(c, empty, {**{f: "x" for f in advisor.REQUIRED_PROFILE_FIELDS},
                                        "time_horizon_years": 10})
        plans.save_plan(c, empty, {"target_alloc": {"Stocks": 100}}, adv)
        # percentages only, against a pretend total, with cash
        holdings, cash, errors = manual_entry.validate_weights(
            [{"Symbol": "VTI", "Percent": 60, "Type": "ETF"},
             {"Symbol": "BND", "Percent": 30, "Type": "ETF"}], 10, 10000)
        self.assertEqual(errors, [])
        meta, rows, totals, errors = manual_entry.build_weights(
            holdings, cash, 10000, {"VTI": {"price": 300.0}, "BND": {"price": 72.0}},
            today=date(2026, 9, 1))
        portfolio.write_snapshot(c, pcts, meta, rows, totals, manual_entry.PCT_SOURCE)
        # two statements (the latest counts) and imported activity
        for day, qty in ((date(2026, 6, 30), 10), (date(2026, 9, 30), 12)):
            meta, rows, totals, _ = manual_entry.build(
                [{"account": "Brokerage", "symbol": "AAPL", "quantity": qty, "cost_basis": 1500.0,
                  "asset_type": "Equity"},
                 {"account": "IRA", "symbol": "ZZZZ", "quantity": 3, "cost_basis": None,
                  "asset_type": None}],
                {"Brokerage": 250.0, "IRA": 40.0}, {"AAPL": {"price": 200.0}, "ZZZZ": {"price": 9.0}},
                today=day)
            portfolio.write_snapshot(c, moved, meta, rows, totals, manual_entry.SOURCE)
        c.execute("INSERT INTO transactions (user_id, account, trade_date, action, amount, origin) "
                  "VALUES (?, 'Brokerage', '2026-08-10', 'DEPOSIT', 300, 'imported')", (moved,))
        prefs.save(c, moved, {"class_overrides": {"AAPL": "Other", "BAD": "Nope"}})
        # the example portfolio with nothing else; and another on a different day
        sample_data.load(c, plain)
        sample_data.load(c, two, today=date(2026, 1, 15))
        c.execute("INSERT INTO security_info (ticker, quote_type, stock_pct, bond_pct, cash_pct, "
                  "other_pct) VALUES ('VTI', 'ETF', 0.98, 0.0, 0.02, 0.0)")
        for t, p in (("VTI", 310.0), ("AAPL", 230.0), ("BND", 71.0)):
            c.execute("INSERT INTO price_history (ticker, price, prev_close, change, pct_change, "
                      "ok) VALUES (?, ?, ?, ?, ?, 1)", (t, p, p - 5, 5, 5 / p * 100))
        c.commit()
        return adv, ids

    def test_whole_book_summaries_match_one_at_a_time(self):
        import alerts
        import overview
        c = self.c
        _, ids = self._book()
        for quotes in ({}, overview.latest_quotes(c)):
            book = overview.account_summaries(c, ids, quotes)
            self.assertEqual(list(book), ids)
            self.assertEqual(book, {i: overview.account_summary(c, i, quotes) for i in ids})
            # alert limits and asset-class choices handed in, for some accounts only
            rules = {ids[0]: [{**r, "abs_gt": 0.1} for r in alerts.DEFAULT_RULES]}
            over = {ids[3]: {}, ids[0]: {"BND": "Stocks"}}
            book = overview.account_summaries(c, ids, quotes, rules, overrides=over)
            for i in ids:
                kw = {"overrides": over[i]} if i in over else {}
                self.assertEqual(book[i], overview.account_summary(c, i, quotes, rules.get(i), **kw))
        self.assertEqual(overview.account_summaries(c, [], {}), {})
        # the book is varied: data and none, alerts, a target mix moved by overrides
        self.assertEqual([book[i]["has_data"] for i in ids], [True, False, True, True, True, True])
        self.assertEqual(book[ids[3]]["snapshot_date"], "2026-09-30")

    def test_whole_book_reads_match_per_client_ones(self):
        import advising
        import advisor
        import plans
        import prefs
        c = self.c
        _, ids = self._book()
        legacy = os.path.join(self.tmp, "legacy.json")
        with open(legacy, "w", encoding="utf-8") as fh:
            fh.write('{"rules": {"day_move": 2.0}}')
        paths = {ids[5]: legacy}
        self.assertEqual(prefs.load_many(c, ids, paths.get),
                         {i: prefs.load(c, i, paths.get(i)) for i in ids})
        self.assertEqual(prefs.load(c, ids[5]), {"rules": {"day_move": 2.0}})  # carried over
        self.assertEqual(advisor.get_profiles(c, ids), {i: advisor.get_profile(c, i) for i in ids})
        self.assertEqual(plans.get_plans(c, ids), {i: plans.get_plan(c, i) for i in ids})
        for private in (True, False):
            self.assertEqual(advising.notes_for(c, ids, include_private=private),
                             {i: advising.list_notes(c, i, include_private=private) for i in ids})
        for helper in (prefs.load_many, advisor.get_profiles, plans.get_plans):
            self.assertEqual(helper(c, []), {})


if __name__ == "__main__":
    unittest.main()
