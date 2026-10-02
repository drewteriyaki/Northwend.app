"""How many database queries a page makes. Home stays under a cap, and Your
clients reads a few things per client - not one query per fact per client.
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

HOME_QUERIES = 44       # Home's queries on a rerun here: 39 when written (it was 52)
HOME_CONNECTIONS = 11   # 9 (it was 23)
PER_CLIENT = 10         # Your clients: queries per client, about 8 (it was 17)


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

    def _count(self, user_id, username, page, **state):
        """(queries, connections) of the page's second run."""
        from streamlit.testing.v1 import AppTest
        seen = {"sql": 0, "connect": 0}
        real = sqlite3.connect

        def counting(*a, **k):
            conn = real(*a, **k)
            seen["connect"] += 1
            conn.set_trace_callback(
                lambda s: seen.__setitem__("sql", seen["sql"] + (not s.startswith("PRAGMA"))))
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
            at.run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
        return seen["sql"], seen["connect"]

    def test_home_stays_under_its_cap(self):
        queries, connections = self._count(self.alice, "alice", "Dashboard")
        self.assertLessEqual(queries, HOME_QUERIES)
        self.assertLessEqual(connections, HOME_CONNECTIONS)

    def test_your_clients_reads_a_few_things_per_client(self):
        state = {"two_step_ok": self.carol_ok, "active_user_id": self.carol}
        one, _ = self._count(self.carol, "carol", "Clients", **state)
        c = portfolio.connect(self.db)
        try:
            for name in ("erin", "frank"):
                cid = auth.create_user(c, name, "pw-123456789")
                auth.link_client(c, self.carol, cid)
                sample_data.load(c, cid)
        finally:
            c.close()
        three, _ = self._count(self.carol, "carol", "Clients", **state)
        self.assertLessEqual((three - one) / 2, PER_CLIENT)


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


if __name__ == "__main__":
    unittest.main()
