"""An account email Resend didn't accept (launch week: its daily allowance
used up on a busy day, or no answer). The count it used is given back
(auth.send_failed), so "Send it again" tries at once instead of saying "we
just sent one" for an email that never left, and the admin hears of it as an
error kind (error_alerts.py) - never the address. A reset's answer stays the
same either way.

    python -m unittest tests.test_email_not_sent        (from the repo root)
"""

import os
import shutil
import sys
import tempfile
import time
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import auth  # noqa: E402
import portfolio  # noqa: E402

NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
EMAIL = "pat@example.com"


def _sign_up(conn, email=EMAIL, now=NOW):
    return auth.sign_up(conn, email, "pw-123456789", agreed=True, adult=True,
                        us_resident=True, needs_code=False, terms_version="v",
                        ip="203.0.113.9", seconds_open=10, now=now)


class SendFailedTests(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_notsent_")
        self.db = os.path.join(self.dir, "t.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.conn = portfolio.connect(self.db)
        self.uid = _sign_up(self.conn)["user_id"]

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _sends(self, purpose):
        return self.conn.execute("SELECT COUNT(*) AS n FROM email_sends WHERE purpose = ?",
                                 (purpose,)).fetchone()["n"]

    def test_a_failed_confirm_doesnt_block_the_next_try(self):
        first = auth.start_confirmation(self.conn, self.uid, now=NOW)
        self.assertTrue(first["ok"])
        auth.send_failed(self.conn, "confirm", first["to"])
        self.assertEqual(self._sends("confirm"), 0)
        again = auth.start_confirmation(self.conn, self.uid, now=NOW + timedelta(seconds=20))
        self.assertTrue(again["ok"], again["error"])
        # a send that worked still holds the next one back a couple of minutes
        soon = auth.start_confirmation(self.conn, self.uid, now=NOW + timedelta(seconds=40))
        self.assertIn("just sent", soon["error"])

    def test_failed_sends_dont_use_up_the_day(self):
        t = NOW
        for _ in range(auth.CONFIRMS_PER_DAY + 3):
            res = auth.start_confirmation(self.conn, self.uid, now=t)
            self.assertTrue(res["ok"], res["error"])
            auth.send_failed(self.conn, "confirm", EMAIL)
            t += timedelta(minutes=5)

    def test_only_the_newest_count_for_that_email_and_purpose_goes(self):
        auth.start_confirmation(self.conn, self.uid, now=NOW)
        auth.request_password_reset(self.conn, EMAIL, now=NOW + timedelta(minutes=1))
        later = NOW + timedelta(minutes=5)
        auth.start_confirmation(self.conn, self.uid, now=later)
        auth.send_failed(self.conn, "confirm", "PAT@example.com ")   # as typed
        rows = self.conn.execute("SELECT purpose, sent_at FROM email_sends "
                                 "ORDER BY sent_at").fetchall()
        self.assertEqual([r["purpose"] for r in rows], ["confirm", "reset"])
        self.assertEqual(rows[0]["sent_at"], auth._utc(NOW))
        auth.send_failed(self.conn, "confirm", "nobody@example.com")   # nothing of theirs
        self.assertEqual(self._sends("confirm") + self._sends("reset"), 2)


class PageTests(unittest.TestCase):
    """The pages: email "on" but Resend refusing (no key, not a dry run -
    mailer.send answers False, as it does when Resend says no)."""

    @classmethod
    def setUpClass(cls):
        # The app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        # the code they test (as tests/test_calm_pages.py does)
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.tmp = tempfile.mkdtemp()
        cls.db = os.path.join(cls.tmp, "notsent.db")
        cls.env = unittest.mock.patch.dict(os.environ, {
            "PORTFOLIO_DB": cls.db, "MAIL_DRY_RUN": "0"})
        cls.env.start()
        for key in ("ANTHROPIC_API_KEY", "FINNHUB_API_KEY", "RESEND_API_KEY",
                    "NORTHWEND_ADMINS", "NORTHWEND_ENV"):
            os.environ.pop(key, None)
        c = portfolio.connect(cls.db)
        try:
            cls.uid = _sign_up(c, now=datetime.now(timezone.utc))["user_id"]
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        cls.env.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _events(self, wait=True):
        """error_events kinds, after the background report has had a moment."""
        for _ in range(50 if wait else 1):
            c = portfolio.connect(self.db)
            try:
                kinds = [r["kind"] for r in c.execute("SELECT kind FROM error_events")]
            finally:
                c.close()
            if kinds or not wait:
                return kinds
            time.sleep(0.1)
        return kinds

    def _count(self, purpose):
        c = portfolio.connect(self.db)
        try:
            return c.execute("SELECT COUNT(*) AS n FROM email_sends WHERE purpose = ?",
                             (purpose,)).fetchone()["n"]
        finally:
            c.close()

    def _app(self, **state):
        from streamlit.testing.v1 import AppTest
        c = portfolio.connect(self.db)
        try:
            c.execute("DELETE FROM error_events")
            c.commit()
        finally:
            c.close()
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in state.items():
            at.session_state[k] = v
        return at

    def test_send_it_again_tries_again_and_the_admin_hears(self):
        at = self._app(user_id=self.uid, username=EMAIL, page="Dashboard")
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        for _ in range(2):   # twice in a row: never "we just sent one"
            at.button(key="email_resend").click().run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
            shown = " ".join(w.value for w in at.warning)
            self.assertIn("couldn't send the email just now", shown)
            self.assertNotIn("just sent", shown)
        self.assertEqual(self._count("confirm"), 0)
        kinds = self._events()
        self.assertTrue(any(k.startswith("EmailNotSent in dashboard.py") for k in kinds), kinds)
        self.assertFalse(any("@" in k for k in kinds), kinds)

    def test_a_reset_answers_the_same_and_gives_the_count_back(self):
        at = self._app(show_forgot=True)
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        at.text_input(key="forgot_email").set_value(EMAIL)
        submit = next(b for b in at.button if b.label == "Send me a link")
        submit.click().run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertIn("If there's an account for", " ".join(s.value for s in at.success))
        self.assertEqual(self._count("reset"), 0)
        self.assertTrue(any(k.startswith("EmailNotSent") for k in self._events()))

    def test_every_account_email_is_wired(self):
        with open(os.path.join(REPO, "dashboard.py"), encoding="utf-8") as fh:
            dash = fh.read()
        with open(os.path.join(REPO, "views", "account.py"), encoding="utf-8") as fh:
            account = fh.read()
        self.assertIn('_email_not_sent("confirm"', dash)
        self.assertIn('_email_not_sent("reset"', dash)
        self.assertIn('_email_not_sent("change"', account)


if __name__ == "__main__":
    unittest.main()
