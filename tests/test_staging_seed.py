"""The staging seed (PLAN 1b.12): `manage_users.py seed-staging` adds a
made-up household, an approved advisor and three clients - on a scratch
SQLite file here - runs again without doubling anything, and refuses the
live copy.

    python -m unittest tests.test_staging_seed        (from the repo root)
"""

import contextlib
import io
import os
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from datetime import date

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import auth  # noqa: E402
import checkin  # noqa: E402
import mailer  # noqa: E402
import manage_users  # noqa: E402
import plans  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sample_data  # noqa: E402

SEEDED = [manage_users.SEED_HOUSEHOLD["login"], manage_users.SEED_ADVISOR["login"],
          *(c["login"] for c in manage_users.SEED_CLIENTS)]


class StagingSeedTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_seed_")
        self.db = os.path.join(self.dir, "seed.db")
        self.env = unittest.mock.patch.dict(os.environ, {"MAIL_DRY_RUN": "1"})
        self.env.start()
        for key in ("NORTHWEND_ENV", "PORTFOLIO_DB", "RESEND_API_KEY"):
            os.environ.pop(key, None)
        self.mail = unittest.mock.patch.object(mailer, "send")
        self.sent = self.mail.start()

    def tearDown(self):
        self.mail.stop()
        self.env.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _cli(self, *args, db=None):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = manage_users.main(["--db", db or self.db, "seed-staging", *args])
        return code, out.getvalue()

    @staticmethod
    def _passwords(text):
        """{login: the temporary password printed for it}."""
        found = {}
        for line in text.splitlines():
            parts = line.split()
            if len(parts) == 4 and parts[0] in SEEDED:
                found[parts[0]] = parts[3]
        return found

    def test_seed_makes_the_people(self):
        code, out = self._cli()
        self.assertEqual(code, 0, out)
        conn = portfolio.connect(self.db)
        try:
            users = {r["username"]: dict(r) for r in conn.execute(
                "SELECT id, username, email, email_verified_at, is_advisor, display_name "
                "FROM users")}
            self.assertEqual(sorted(users), sorted(SEEDED))
            for login, row in users.items():
                # made up and unreachable: example.com, the login is the email
                self.assertTrue(login.endswith("@example.com"), login)
                self.assertEqual(row["email"], login)
                self.assertTrue(row["display_name"])
            # every login and its temporary password is printed, and works
            pws = self._passwords(out)
            self.assertEqual(sorted(pws), sorted(SEEDED))
            for login, pw in pws.items():
                self.assertIsNotNone(auth.verify_login(conn, login, pw), login)

            # the advisor: approved, no two-step yet (set up at first sign-in)
            aid = users[manage_users.SEED_ADVISOR["login"]]["id"]
            self.assertTrue(auth.is_advisor(conn, aid))
            self.assertEqual(auth.advisor_request(conn, aid)["decision"], "approved")
            self.assertIsNone(conn.execute("SELECT 1 FROM two_step WHERE user_id = ?",
                                           (aid,)).fetchone())
            # ...with three clients, by the names the advisor uses
            self.assertEqual(sorted(n for _, n in auth.list_clients(conn, aid)),
                             sorted(c["name"] for c in manage_users.SEED_CLIENTS))

            # the household: sample_data's holdings, a plan with a target mix,
            # and this month's walk due
            hid = users[manage_users.SEED_HOUSEHOLD["login"]]["id"]
            syms = {r["symbol"] for r in conn.execute(
                "SELECT symbol FROM positions WHERE user_id = ?", (hid,))}
            self.assertEqual(syms, {h[1] for h in sample_data.HOLDINGS})
            sources = {r["source_file"] for r in conn.execute(
                "SELECT source_file FROM snapshots WHERE user_id = ?", (hid,))}
            self.assertEqual(sources, {manage_users.SEED_SOURCE})   # not the "example" kind
            plan = plans.get_plan(conn, hid)
            self.assertTrue(plans.has_goal(plan))
            self.assertEqual(plan["target_alloc"], manage_users.SEED_HOUSEHOLD["mix"])
            self.assertTrue(checkin.due(prefs.load(conn, hid), date.today()))
            # each client has holdings and a plan the advisor set
            for c in manage_users.SEED_CLIENTS:
                cid = users[c["login"]]["id"]
                self.assertTrue(auth.can_view(conn, aid, cid))
                self.assertEqual(plans.get_plan(conn, cid)["set_by"], aid)
                self.assertTrue(conn.execute("SELECT 1 FROM positions WHERE user_id = ?",
                                             (cid,)).fetchone())
        finally:
            conn.close()
        self.sent.assert_not_called()   # nobody is emailed

    def test_running_again_doubles_nothing(self):
        code, out = self._cli()
        first = self._passwords(out)

        def counts():
            conn = portfolio.connect(self.db)
            try:
                return {t: conn.execute(f"SELECT COUNT(*) n FROM {t}").fetchone()["n"]
                        for t in ("users", "advisor_clients", "snapshots", "positions",
                                  "account_totals", "plans", "advisor_requests")}
            finally:
                conn.close()

        before = counts()
        code, out = self._cli()
        self.assertEqual(code, 0, out)
        self.assertEqual(counts(), before)
        self.assertEqual(out.count("refreshed"), len(SEEDED))
        self.assertEqual(self._passwords(out), {})   # passwords kept, none printed
        conn = portfolio.connect(self.db)
        try:
            for login, pw in first.items():
                self.assertIsNotNone(auth.verify_login(conn, login, pw), login)
        finally:
            conn.close()
        # --reset-passwords gives each a new one
        code, out = self._cli("--reset-passwords")
        new = self._passwords(out)
        self.assertEqual(sorted(new), sorted(SEEDED))
        conn = portfolio.connect(self.db)
        try:
            for login, pw in new.items():
                self.assertIsNotNone(auth.verify_login(conn, login, pw), login)
                self.assertIsNone(auth.verify_login(conn, login, first[login]), login)
        finally:
            conn.close()

    def test_refuses_the_live_copy(self):
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_ENV": "production"}):
            code, out = self._cli()
        self.assertEqual(code, 1)
        self.assertIn("production", out)
        self.assertFalse(os.path.exists(self.db))   # nothing was opened, let alone written
        # Postgres only when NORTHWEND_ENV says staging (never connected here)
        with unittest.mock.patch.object(manage_users, "connect") as connect:
            code, out = self._cli(db="postgresql://seed@db.invalid/northwend")
            self.assertEqual(code, 1)
            self.assertIn("NORTHWEND_ENV=staging", out)
            connect.assert_not_called()
            self.assertIn("staging", manage_users.seed_refusal("postgresql://x@y/z") or "")
            with unittest.mock.patch.dict(os.environ, {"NORTHWEND_ENV": "staging"}):
                self.assertIsNone(manage_users.seed_refusal("postgresql://x@y/z"))
        # never a local portfolio.db (someone's own holdings)
        code, out = self._cli(db=os.path.join(self.dir, "portfolio.db"))
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "portfolio.db")))

    def test_names_are_obviously_made_up(self):
        people = [manage_users.SEED_HOUSEHOLD, manage_users.SEED_ADVISOR,
                  *manage_users.SEED_CLIENTS]
        for who in people:
            self.assertRegex(who["login"], r"^seed\.[a-z0-9]+@example\.com$")
            self.assertTrue(re.search(r"Example|Sample|Placeholder|Testcase", who["name"]),
                            who["name"])

    def test_sample_rows_unchanged_for_the_example_portfolio(self):
        # load() still saves exactly HOLDINGS (snapshot_rows at scale 1)
        rows, totals = sample_data.snapshot_rows("2026-10-01")
        self.assertEqual([(r["symbol"], r["quantity"], r["cost_basis"]) for r in rows],
                         [(h[1], float(h[4]), h[5]) for h in sample_data.HOLDINGS])
        self.assertEqual({a: t["cash_value"] for a, t in totals.items()}, sample_data.CASH)
        half, _ = sample_data.snapshot_rows("2026-10-01", scale=0.5)
        self.assertEqual(half[0]["quantity"], sample_data.HOLDINGS[0][4] / 2)


if __name__ == "__main__":
    unittest.main()
