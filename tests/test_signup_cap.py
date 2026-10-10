"""The daily sign-up cap (owner's item 7): NORTHWEND_MAX_SIGNUPS_PER_DAY.

Once that many accounts were made on Create account since midnight US
Eastern time, the form gives way to "We're full for today" and a form sent
anyway is refused. Unset, blank, 0 or not a number: no cap. Signing in,
password resets, an advisor's client setup links and accounts an admin or
advisor makes are never counted or stopped.

    python -m unittest tests.test_signup_cap        (from the repo root)
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
import flags  # noqa: E402
import portfolio  # noqa: E402
import settings  # noqa: E402
import two_step  # noqa: E402
from tests import offline as offline_net  # noqa: E402

CAP = "NORTHWEND_MAX_SIGNUPS_PER_DAY"
PW = "pw-123456789"
# 2026-10-06 is in daylight time: midnight Eastern = 04:00 UTC
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
BOXES = dict(agreed=True, adult=True, us_resident=True, terms_version="October 1, 2026",
             needs_code=False, seconds_open=10)


def _cap(value):
    """Only this cap (None: not set at all)."""
    env = {k: v for k, v in os.environ.items() if k != CAP}
    if value is not None:
        env[CAP] = value
    return unittest.mock.patch.dict(os.environ, env, clear=True)


class SettingTests(unittest.TestCase):

    def test_only_a_positive_whole_number_is_a_cap(self):
        for value, want in ((None, None), ("", None), ("  ", None), ("0", None),
                            ("-3", None), ("ten", None), ("2.5", None), ("25", 25),
                            (" 7 ", 7)):
            with self.subTest(value=value), _cap(value), self.assertNoLogs(level="ERROR"):
                self.assertEqual(settings.max_signups_per_day(), want)

    def test_a_bad_value_is_logged_not_raised(self):
        with _cap("lots"), self.assertLogs("settings", level="WARNING") as logged:
            self.assertIsNone(settings.max_signups_per_day())
        self.assertIn(CAP, logged.output[0])

    def test_the_day_starts_at_midnight_eastern(self):
        self.assertEqual(auth.signup_day_start(NOW),
                         datetime(2026, 10, 6, 4, 0, tzinfo=timezone.utc))
        # just after midnight UTC it is still the evening before in New York
        late = datetime(2026, 10, 7, 2, 0, tzinfo=timezone.utc)
        self.assertEqual(auth.signup_day_start(late),
                         datetime(2026, 10, 6, 4, 0, tzinfo=timezone.utc))
        # in standard time (January) midnight Eastern is 05:00 UTC
        winter = datetime(2026, 1, 15, 4, 59, tzinfo=timezone.utc)
        self.assertEqual(auth.signup_day_start(winter),
                         datetime(2026, 1, 14, 5, 0, tzinfo=timezone.utc))

    def test_the_wording(self):
        self.assertEqual(auth.FULL_TITLE, "We're full for today")
        self.assertIn("come back tomorrow", auth.FULL_TEXT)
        self.assertIn("midnight Eastern time", auth.FULL_TEXT)
        for word in ("calm", "error", "denied", "blocked", "trail"):
            self.assertNotIn(word, (auth.FULL_TITLE + auth.FULL_TEXT).lower())


class _DB(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_cap_")
        self.db = os.path.join(self.dir, "t.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.conn = portfolio.connect(self.db)
        self.n = 0

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _sign_up(self, now=NOW, **kw):
        self.n += 1
        args = dict(BOXES, ip=f"203.0.113.{self.n}", now=now)   # a new address each time
        args.update(kw)
        return auth.sign_up(self.conn, f"person{self.n}@example.com", PW, **args)

    def _users(self):
        return self.conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]


class CountTests(_DB):

    def test_below_the_cap_works_and_at_it_is_refused(self):
        with _cap("2"):
            self.assertFalse(auth.signups_full(self.conn, now=NOW))
            self.assertTrue(self._sign_up()["ok"])
            self.assertTrue(self._sign_up()["ok"])
            self.assertTrue(auth.signups_full(self.conn, now=NOW))
            refused = self._sign_up()
        self.assertFalse(refused["ok"])
        self.assertTrue(refused["full"])
        self.assertEqual(refused["error"], auth.FULL_TEXT)
        self.assertEqual(self._users(), 2)
        # a refusal isn't an account: still 2
        self.assertEqual(auth.signups_today(self.conn, now=NOW), 2)

    def test_no_cap_when_unset_zero_or_not_a_number(self):
        for value in (None, "", "0", "soon"):
            with self.subTest(value=value), _cap(value):
                for _ in range(3):
                    self.assertTrue(self._sign_up()["ok"])
                self.assertFalse(auth.signups_full(self.conn, now=NOW))

    def test_only_accounts_people_made_themselves_count(self):
        advisor = auth.create_user(self.conn, "carol", PW)          # an admin-made login
        auth.set_advisor(self.conn, "carol", True)
        client = auth.create_client(self.conn, advisor, "", name="Dana")
        token = auth.create_invite(self.conn, advisor, client)
        with _cap("1"):
            self.assertTrue(auth.accept_invite(self.conn, token, "clientpass1", now=NOW,
                                               agreed=True, adult=True,
                                               us_resident=True,
                                               terms_version="October 1, 2026")["ok"])
            self.assertEqual(auth.signups_today(self.conn, now=NOW), 0)
            self.assertTrue(self._sign_up()["ok"])
            self.assertTrue(auth.signups_full(self.conn, now=NOW))
            # full: a setup link, an admin-made account, an advisor's client,
            # signing in and a password reset all still work
            client2 = auth.create_client(self.conn, advisor, "", name="Eli")
            token2 = auth.create_invite(self.conn, advisor, client2)
            self.assertTrue(auth.accept_invite(self.conn, token2, "clientpass2", now=NOW,
                                               agreed=True, adult=True, us_resident=True,
                                               terms_version="October 1, 2026")["ok"])
            self.assertIsNotNone(auth.create_user(self.conn, "made.by.admin", PW))
            self.assertEqual(auth.attempt_login(self.conn, "carol", PW)["user_id"], advisor)
            self.assertIsNotNone(auth.attempt_login(self.conn, "person1@example.com",
                                                    PW)["user_id"])
            sent = auth.start_confirmation(self.conn, auth.get_user_id(
                self.conn, "person1@example.com"), now=NOW)
            self.assertTrue(auth.confirm_email(self.conn, sent["token"], now=NOW)["ok"])
            reset = auth.request_password_reset(self.conn, "person1@example.com", now=NOW)
            self.assertTrue(reset["token"])
            self.assertTrue(auth.reset_password(self.conn, reset["token"], "new-pw-12345",
                                                now=NOW)["ok"])
            self.assertEqual(auth.signups_today(self.conn, now=NOW), 1)
        # the decoder's and share links' counting rows (ok = 0) never count
        self.conn.execute("INSERT INTO signups (address_key, created_at, ok) "
                          "VALUES ('decoder:x', ?, 0)", (auth._utc(NOW),))
        self.conn.commit()
        self.assertEqual(auth.signups_today(self.conn, now=NOW), 1)

    def test_yesterday_does_not_count_and_midnight_opens_it_again(self):
        before = datetime(2026, 10, 6, 3, 59, 59, tzinfo=timezone.utc)   # 11:59:59 pm ET
        at_midnight = datetime(2026, 10, 6, 4, 0, tzinfo=timezone.utc)   # 12:00 am ET
        with _cap("1"):
            self.assertTrue(self._sign_up(now=before)["ok"])
            self.assertTrue(auth.signups_full(self.conn, now=before))
            self.assertTrue(self._sign_up(now=before)["full"])
            self.assertFalse(auth.signups_full(self.conn, now=at_midnight))
            self.assertEqual(auth.signups_today(self.conn, now=at_midnight), 0)
            self.assertTrue(self._sign_up(now=at_midnight)["ok"])
            self.assertTrue(self._sign_up(now=at_midnight + timedelta(hours=19))["full"])

    def test_the_count_is_one_query_on_the_time_index(self):
        plan = " ".join(str(tuple(r)) for r in self.conn.execute(
            "EXPLAIN QUERY PLAN SELECT COUNT(*) AS n FROM signups WHERE created_at >= ? "
            "AND ok = 1", ("2026-10-06 04:00:00",)))
        self.assertIn("idx_signups_time", plan)


# --------------------------------------------------------------------------- #
# in the app: Create account, signing in, a setup link, Admin > System
# --------------------------------------------------------------------------- #
class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_cap_app_")

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        self.db = os.path.join(self.dir, f"{self._testMethodName}.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        c = portfolio.connect(self.db)
        try:
            self.ann = auth.create_user(c, "ann", PW)      # an admin, with two-step
            secret = two_step.new_secret()
            two_step.enable(c, self.ann, secret, two_step.totp(secret))
            self.ann_ok = f"{self.ann}:{two_step.status(c, self.ann)['stamp']}"
            self.carol = auth.create_user(c, "carol", PW)
            auth.set_advisor(c, "carol", True)
        finally:
            c.close()

    def _conn(self):
        return portfolio.connect(self.db)

    def _made_today(self, n):
        c = self._conn()
        try:
            stamp = auth._utc(datetime.now(timezone.utc))
            c.executemany("INSERT INTO signups (address_key, created_at, ok) VALUES (?, ?, 1)",
                          [(f"k{i}", stamp) for i in range(n)])
            c.commit()
        finally:
            c.close()

    def _app(self, cap, *, query=None, state=None, admins=""):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in (query or {}).items():
            at.query_params[k] = v
        for k, v in (state or {}).items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "ANTHROPIC_API_KEY", "RESEND_API_KEY",
                            "NORTHWEND_ADMINS", flags.GATES_SETTING, CAP)}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1")
        env[flags.GATES_SETTING] = "L0"          # sign-up open, no invite code
        if cap is not None:
            env[CAP] = cap
        if admins:
            env["NORTHWEND_ADMINS"] = admins
        self._env = env
        return at

    def _run(self, at):
        with unittest.mock.patch.dict(os.environ, self._env, clear=True), \
                unittest.mock.patch("socket.socket.connect", offline_net.connect), \
                unittest.mock.patch.object(flags, "_secret", lambda name: None):
            at.run()
        self.assertEqual([e.message for e in at.exception], [])
        return at

    @staticmethod
    def _text(at):
        parts = [m.value for m in at.markdown] + [s.value for s in at.subheader]
        for kind in ("error", "caption", "info", "success"):
            parts += [str(e.value) for e in getattr(at, kind)]
        return " ".join(parts)

    def _fill_signup(self, at, email):
        at.text_input(key="signup_email").input(email)
        at.text_input(key="signup_pw").input(PW)
        at.text_input(key="signup_pw_again").input(PW)
        at.checkbox(key="signup_adult").check()
        at.checkbox(key="signup_us").check()
        at.checkbox(key="signup_agree").check()
        at.button(key="FormSubmitter:signup_form-Create account").click()

    def _user(self, email):
        c = self._conn()
        try:
            return c.execute("SELECT id FROM users WHERE username = ?", (email,)).fetchone()
        finally:
            c.close()

    def test_full_shows_the_page_instead_of_the_form(self):
        self._made_today(2)
        at = self._run(self._app("2", query={"signup": "1"}))
        text = self._text(at)
        self.assertIn(auth.FULL_TITLE, text)
        self.assertIn(auth.FULL_TEXT, text)
        self.assertNotIn("signup_email", [t.key for t in at.text_input])
        # back to Log in, which works as usual
        at.button(key="signup_full_to_login").click()
        self._run(at)
        self.assertIn("login_user", [t.key for t in at.text_input])
        at.text_input(key="login_user").input("carol")
        at.text_input(key="login_pw").input(PW)
        at.button(key="FormSubmitter:login_form-Log in").click()
        self._run(at)
        self.assertEqual(at.session_state["user_id"], self.carol)

    def test_below_the_cap_the_form_works(self):
        self._made_today(1)
        at = self._run(self._app("2", query={"signup": "1"},
                                 state={"signup_opened": time.time() - 60}))
        self.assertNotIn(auth.FULL_TITLE, self._text(at))
        self._fill_signup(at, "just.in@example.com")
        self._run(at)
        row = self._user("just.in@example.com")
        self.assertIsNotNone(row)
        self.assertEqual(at.session_state["user_id"], row["id"])

    def test_filled_in_after_the_last_place_went_is_refused(self):
        self._made_today(1)
        at = self._run(self._app("2", query={"signup": "1"},
                                 state={"signup_opened": time.time() - 60}))
        self.assertIn("signup_email", [t.key for t in at.text_input])
        self._made_today(1)            # someone else took the last place meanwhile
        self._fill_signup(at, "too.late@example.com")
        self._run(at)
        self.assertIsNone(self._user("too.late@example.com"))
        self.assertIsNone(at.session_state["user_id"] if "user_id" in at.session_state
                          else None)
        self.assertIn(auth.FULL_TITLE, self._text(at))

    def test_no_cap_set_the_form_shows(self):
        self._made_today(50)
        for cap in (None, "0", "many"):
            with self.subTest(cap=cap):
                at = self._run(self._app(cap, query={"signup": "1"}))
                self.assertNotIn(auth.FULL_TITLE, self._text(at))
                self.assertIn("signup_email", [t.key for t in at.text_input])

    def test_a_setup_link_still_works_when_full(self):
        self._made_today(1)
        c = self._conn()
        try:
            client = auth.create_client(c, self.carol, "", name="Eve")
            token = auth.create_invite(c, self.carol, client)
        finally:
            c.close()
        at = self._run(self._app("1", query={"invite": token}))
        self.assertNotIn(auth.FULL_TITLE, self._text(at))
        at.text_input(key="invite_pw").input("clientpass1")
        at.text_input(key="invite_pw_again").input("clientpass1")
        at.checkbox(key="invite_adult").check()
        at.checkbox(key="invite_us").check()
        at.checkbox(key="invite_agree").check()
        at.button(key="FormSubmitter:invite_form-Create my login").click()
        self._run(at)
        self.assertEqual(at.session_state["user_id"], client)

    def test_admin_system_shows_the_cap_and_todays_count(self):
        self._made_today(3)
        state = {"user_id": self.ann, "username": "ann", "two_step_ok": self.ann_ok}
        at = self._run(self._app("5", query={"page": "admin"}, state=state, admins="ann"))
        self.assertIn("New accounts a day (NORTHWEND_MAX_SIGNUPS_PER_DAY):** 5; 3 made on "
                      "Create account today (since midnight Eastern)", self._text(at))
        at = self._run(self._app(None, query={"page": "admin"}, state=state, admins="ann"))
        self.assertIn("NORTHWEND_MAX_SIGNUPS_PER_DAY):** no cap; 3 made", self._text(at))


if __name__ == "__main__":
    unittest.main()
