"""How often one login may read uploaded files, save, and build downloads
(rate_limits.py, security audit 1.8d): the limits trip at the right count,
let go after the window, count against the advisor in a client's account,
and over a limit the page is calm and nothing is saved or built.

    python -m unittest tests.test_rate_limits        (from the repo root)
"""

import hashlib
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import auth  # noqa: E402
import portfolio  # noqa: E402
import rate_limits  # noqa: E402
import sample_data  # noqa: E402
import tidy  # noqa: E402
import two_step  # noqa: E402

BROKERS = os.path.join(os.path.dirname(__file__), "fixtures", "brokers")
PW = "pw-123456789"
T0 = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


def _fill(db, login_id, action, n=None):
    """Use up the hour's allowance of `action` for `login_id`, now."""
    c = portfolio.connect(db)
    try:
        for _ in range(n if n is not None else rate_limits.LIMITS[action][0]):
            assert rate_limits.allow(c, login_id, action)
    finally:
        c.close()


def _count(db, login_id, action):
    c = portfolio.connect(db)
    try:
        return c.execute("SELECT COUNT(*) AS n FROM email_sends WHERE email_key = ? "
                         "AND purpose = ?", (rate_limits._key(login_id),
                                             rate_limits.PURPOSE_PREFIX + action)).fetchone()["n"]
    finally:
        c.close()


class LimitTests(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_rate_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.conn = portfolio.connect(os.path.join(self.dir, "t.db"))
        self.addCleanup(self.conn.close)
        self.uid = auth.create_user(self.conn, "ann", PW)

    def allow(self, action, now, uid=None):
        return rate_limits.allow(self.conn, uid or self.uid, action, now=now)

    def test_the_limits_are_generous_named_and_all_there(self):
        self.assertEqual(set(rate_limits.LIMITS), {rate_limits.UPLOAD, rate_limits.SAVE,
                                                   rate_limits.EXPORT})
        self.assertEqual(set(rate_limits.LABELS), set(rate_limits.LIMITS))
        for action, (per_hour, per_day) in rate_limits.LIMITS.items():
            self.assertGreaterEqual(per_hour, 20, action)    # nobody really gets near
            self.assertGreater(per_day, per_hour, action)
        self.assertEqual(rate_limits.CALM, "You've done a lot of that in a short time - "
                                           "please try again in a little while.")

    def test_the_hour_limit_trips_at_its_count_and_lets_go_after_the_hour(self):
        per_hour = rate_limits.LIMITS[rate_limits.UPLOAD][0]
        for i in range(per_hour):
            self.assertTrue(self.allow(rate_limits.UPLOAD, T0 + timedelta(seconds=i)), i)
        self.assertFalse(self.allow(rate_limits.UPLOAD, T0 + timedelta(minutes=30)))
        self.assertFalse(self.allow(rate_limits.UPLOAD, T0 + timedelta(minutes=59)))
        # a refused try isn't counted: once the first ones are an hour old, it's open
        self.assertTrue(self.allow(rate_limits.UPLOAD, T0 + timedelta(hours=1, seconds=1)))
        self.assertFalse(self.allow(rate_limits.UPLOAD, T0 + timedelta(hours=1, seconds=1)))

    def test_the_day_limit_trips_and_lets_go_after_a_day(self):
        per_hour, per_day = rate_limits.LIMITS[rate_limits.SAVE]
        t = T0
        done = 0
        while done < per_day:   # spread out, so only the day's limit is met
            for _ in range(per_hour):
                if done == per_day:
                    break
                self.assertTrue(self.allow(rate_limits.SAVE, t), done)
                done += 1
            t += timedelta(hours=1, minutes=1)
        self.assertLess(t - T0, timedelta(days=1))
        self.assertFalse(self.allow(rate_limits.SAVE, t))
        self.assertTrue(self.allow(rate_limits.SAVE, T0 + timedelta(days=1, minutes=2)))

    def test_each_login_and_each_action_counts_on_its_own(self):
        other = auth.create_user(self.conn, "bob", PW)
        per_hour = rate_limits.LIMITS[rate_limits.EXPORT][0]
        for _ in range(per_hour):
            self.allow(rate_limits.EXPORT, T0)
        self.assertFalse(self.allow(rate_limits.EXPORT, T0))
        self.assertTrue(self.allow(rate_limits.EXPORT, T0, uid=other))
        self.assertTrue(self.allow(rate_limits.SAVE, T0))
        self.assertTrue(self.allow(rate_limits.UPLOAD, T0))
        # nothing to count against: allowed
        self.assertTrue(rate_limits.allow(self.conn, None, rate_limits.EXPORT, now=T0))

    def test_counts_only_hashed_and_tidied_after_a_day(self):
        self.allow(rate_limits.UPLOAD, T0)
        rows = [dict(r) for r in self.conn.execute("SELECT * FROM email_sends")]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["purpose"], "limit_upload")
        self.assertEqual(rows[0]["address_key"], "")
        self.assertEqual(len(rows[0]["email_key"]), 64)
        self.assertEqual(rows[0]["email_key"],   # a hash of the login's id, not the id
                         hashlib.sha256(f"login:{self.uid}".encode()).hexdigest())
        done = tidy.run(self.conn, now=T0 + timedelta(days=1, minutes=1))
        self.assertEqual(done["email-send counts"], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) AS n FROM email_sends")
                         .fetchone()["n"], 0)

    def test_admin_sees_the_numbers_only(self):
        rows = rate_limits.rows_for_admin()
        self.assertEqual(len(rows), len(rate_limits.LIMITS))
        for (label, text), (h, d) in zip(rows, rate_limits.LIMITS.values()):
            self.assertEqual(text, f"{h} an hour, {d} a day per login")
        with open(os.path.join(REPO, "views", "admin.py"), encoding="utf-8") as fh:
            self.assertIn("rate_limits.rows_for_admin()", fh.read())

    def test_every_heavy_path_checks_a_limit(self):
        def src(name):
            with open(os.path.join(REPO, *name.split("/")), encoding="utf-8") as fh:
                return fh.read()
        hi = src("views/holdings_input.py")
        self.assertEqual(hi.count("_limit_ok(rate_limits.SAVE)"), 4)  # save, activity,
        self.assertEqual(hi.count("_upload_ok(up)"), 1)               # remove, example
        self.assertEqual(hi.count("_limit_ok(rate_limits.UPLOAD)"), 1)  # screenshots
        cl = src("views/clients.py")
        self.assertEqual(cl.count("_limit_ok(rate_limits.EXPORT)"), 3)   # the record ZIPs
        self.assertEqual(cl.count("_limit_ok(rate_limits.SAVE)"), 1)     # clients from a file
        self.assertEqual(cl.count("_upload_ok(up)"), 1)                  # the client list
        for name in ("views/profile.py", "views/reports.py", "views/proposals.py"):
            self.assertEqual(src(name).count("_limit_ok(rate_limits.EXPORT)"), 1, name)
        self.assertIn("_limit_ok(rate_limits.EXPORT)", src("dashboard.py"))   # my data ZIP


class _App(unittest.TestCase):
    """dashboard.py through AppTest on a scratch database (never the real one)."""

    @classmethod
    def setUpClass(cls):
        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_rate_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.ann = auth.create_user(c, "ann", PW)
            cls.carol = auth.create_user(c, "carol", PW)   # an advisor, with two-step
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dave = auth.create_user(c, "dave", PW)     # her client
            auth.link_client(c, cls.carol, cls.dave)
            sample_data.load(c, cls.dave)
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        c = portfolio.connect(self.db)
        try:   # each test starts with no counts
            c.execute("DELETE FROM email_sends")
            c.commit()
        finally:
            c.close()

    def app(self, user_id, username, **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY", "ANTHROPIC_API_KEY",
                            "RENDER", "NORTHWEND_ENV", "MOVED_TO")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1")
        for p in (unittest.mock.patch.dict(os.environ, env, clear=True),
                  unittest.mock.patch("settings._on_community_cloud", return_value=False),
                  unittest.mock.patch.object(yfinance, "Ticker", offline),
                  unittest.mock.patch("socket.socket.connect", offline_net.connect)):
            p.start()
            self.addCleanup(p.stop)
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": user_id, "username": username, "page": "Dashboard",
                     "auto_backfilled": True, "income_synced": True, **state}.items():
            at.session_state[k] = v
        return at

    def run_ok(self, at):
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        return at

    def saved(self, uid):
        """Every snapshot row of `uid`, to see whether a save happened."""
        c = portfolio.connect(self.db)
        try:
            return [tuple(r) for r in c.execute(
                "SELECT snapshot_date, source_file, imported_at FROM snapshots "
                "WHERE user_id = ? ORDER BY snapshot_date, imported_at", (uid,))]
        finally:
            c.close()

    def snapshots(self, uid):
        c = portfolio.connect(self.db)
        try:
            return c.execute("SELECT COUNT(*) AS n FROM snapshots WHERE user_id = ?",
                             (uid,)).fetchone()["n"]
        finally:
            c.close()


class CalmMessageAppTests(_App):

    def import_csv(self, user_id, username, **state):
        return self.run_ok(self.app(user_id, username, open_dialog="import",
                                    csv_path=os.path.join(BROKERS, "fidelity_positions.csv"),
                                    **state))

    def test_a_save_over_the_limit_is_calm_and_saves_nothing(self):
        at = self.import_csv(self.ann, "ann")
        _fill(self.db, self.ann, rate_limits.SAVE)
        at.button(key="csv_save").click()
        at.session_state["open_dialog"] = "import"   # (the window, drawn again)
        self.run_ok(at)
        self.assertIn(rate_limits.CALM, [i.value for i in at.info])
        self.assertEqual(self.snapshots(self.ann), 0)
        # the refused save wasn't counted
        self.assertEqual(_count(self.db, self.ann, rate_limits.SAVE),
                         rate_limits.LIMITS[rate_limits.SAVE][0])

    def test_a_save_under_the_limit_is_counted(self):
        at = self.import_csv(self.ann, "ann")
        at.button(key="csv_save").click()
        at.session_state["open_dialog"] = "import"
        self.run_ok(at)
        self.assertNotIn(rate_limits.CALM, [i.value for i in at.info])
        self.assertEqual(_count(self.db, self.ann, rate_limits.SAVE), 1)
        c = portfolio.connect(self.db)
        try:   # (put ann back as she was for the other tests)
            portfolio.delete_holdings(c, self.ann)
        finally:
            c.close()

    def test_an_advisor_in_a_clients_account_counts_against_the_advisor(self):
        before = self.saved(self.dave)
        # the client's own count being full doesn't stop their advisor...
        _fill(self.db, self.dave, rate_limits.SAVE)
        at = self.import_csv(self.carol, "carol", active_user_id=self.dave,
                             two_step_ok=self.carol_ok)
        at.button(key="csv_save").click()
        at.session_state["open_dialog"] = "import"
        self.run_ok(at)
        self.assertNotIn(rate_limits.CALM, [i.value for i in at.info])
        after = self.saved(self.dave)
        self.assertNotEqual(after, before)                                  # saved
        self.assertEqual(_count(self.db, self.carol, rate_limits.SAVE), 1)   # hers
        self.assertEqual(_count(self.db, self.dave, rate_limits.SAVE),
                         rate_limits.LIMITS[rate_limits.SAVE][0])          # theirs: unchanged
        # ...and the advisor's own count being full does
        _fill(self.db, self.carol, rate_limits.SAVE,
              rate_limits.LIMITS[rate_limits.SAVE][0] - 1)
        at = self.import_csv(self.carol, "carol", active_user_id=self.dave,
                             two_step_ok=self.carol_ok)
        at.button(key="csv_save").click()
        at.session_state["open_dialog"] = "import"
        self.run_ok(at)
        self.assertIn(rate_limits.CALM, [i.value for i in at.info])
        self.assertEqual(self.saved(self.dave), after)                      # nothing saved

    def test_preparing_my_data_over_the_limit_is_calm_and_builds_nothing(self):
        _fill(self.db, self.ann, rate_limits.EXPORT)
        at = self.run_ok(self.app(self.ann, "ann", page="Account"))
        at.button(key="export_prepare").click()
        self.run_ok(at)
        self.assertIn(rate_limits.CALM, [i.value for i in at.info])
        self.assertNotIn("export_zip", at.session_state)
        self.assertEqual([b for b in at.get("download_button")
                          if b.proto.id.endswith("export_download")], [])
        # the note shows once; the next run is back to normal
        self.run_ok(at)
        self.assertNotIn(rate_limits.CALM, [i.value for i in at.info])


if __name__ == "__main__":
    unittest.main()
