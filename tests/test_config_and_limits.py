"""PLAN step 1a items 3-5 (security audit 1.5b, 1.3b, 1.1c):
- settings.py: a hosted copy fails closed - no Postgres PORTFOLIO_DB, no start;
  no server-path box, no error details, alerts on - decided by "hosted", not
  by the database;
- size limits: uploads, CSV rows, pasted text, the chat box, screenshot types;
- sign-in limits: per internet address across usernames, and an unknown
  username takes the same hash as a wrong password.

    python -m unittest tests.test_config_and_limits     (from the repo root)
"""

import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import auth  # noqa: E402
import csv_import  # noqa: E402
import paste_parse  # noqa: E402
import portfolio  # noqa: E402
import settings  # noqa: E402
import txn_import  # noqa: E402

BROKERS = os.path.join(os.path.dirname(__file__), "fixtures", "brokers")
PW = "pw-123456789"
IP = "203.0.113.7"
T0 = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
# every setting that says "hosted" - cleared so a test decides it
HOST_KEYS = ("RENDER", "NORTHWEND_ENV", "PORTFOLIO_DB", "HOSTNAME", "MOVED_TO",
             "FINNHUB_API_KEY", "NORTHWEND_ADMINS")


def _env(**values):
    """os.environ without the hosting settings, plus `values`."""
    env = {k: v for k, v in os.environ.items() if k not in HOST_KEYS}
    env.update(values)
    return unittest.mock.patch.dict(os.environ, env, clear=True)


def _not_on_community_cloud():
    return unittest.mock.patch.object(settings, "_on_community_cloud", return_value=False)


# --------------------------------------------------------------------------- #
# 3. settings.py
# --------------------------------------------------------------------------- #
class SettingsTests(unittest.TestCase):

    def test_what_counts_as_hosted(self):
        with _not_on_community_cloud():
            for env, hosted in (({}, False), ({"NORTHWEND_ENV": "development"}, False),
                                ({"RENDER": "true"}, True),
                                ({"NORTHWEND_ENV": "production"}, True),
                                ({"NORTHWEND_ENV": " Staging "}, True)):
                with _env(**env):
                    self.assertEqual(settings.hosted(), hosted, env)
            with _env(NORTHWEND_ENV="staging"):
                self.assertTrue(settings.staging())
            with _env(RENDER="true"):
                self.assertEqual(settings.host(), "Render")
        # Community Cloud checks the app out under /mount/src
        with _env(), unittest.mock.patch.object(settings, "HERE", "/mount/src/portfolio_tracker"):
            self.assertEqual(settings.host(), "Streamlit Community Cloud")
            self.assertTrue(settings.hosted())

    def test_a_hosted_copy_needs_a_postgres_database(self):
        with _not_on_community_cloud():
            with _env(NORTHWEND_ENV="production"):
                self.assertEqual(settings.config_problem(),
                                 "This copy isn't set up: PORTFOLIO_DB is missing.")
                self.assertEqual(settings.database("/code/portfolio.db"), "")  # no fallback
            with _env(RENDER="1", PORTFOLIO_DB="/tmp/some.db"):
                self.assertIn("isn't a Postgres connection string", settings.config_problem())
                self.assertNotIn("/tmp/some.db", settings.config_problem())
            with _env(RENDER="1", PORTFOLIO_DB="postgresql://u:secret@h/db"):
                self.assertEqual(settings.config_problem(), "")
                self.assertEqual(settings.database("/code/portfolio.db"),
                                 "postgresql://u:secret@h/db")

    def test_a_local_run_keeps_the_friendly_defaults(self):
        with _not_on_community_cloud(), _env():
            self.assertEqual(settings.config_problem(), "")
            self.assertEqual(settings.database("/code/portfolio.db"), "/code/portfolio.db")
            self.assertTrue(settings.server_files_ok())
            self.assertTrue(settings.show_error_details())
            self.assertFalse(settings.send_error_alerts())
        with _not_on_community_cloud(), _env(NORTHWEND_ENV="production"):
            self.assertFalse(settings.server_files_ok())
            self.assertFalse(settings.show_error_details())
            self.assertTrue(settings.send_error_alerts())
        # a local run on a Postgres database is still a local run
        with _not_on_community_cloud(), _env(PORTFOLIO_DB="postgresql://u@h/db"):
            self.assertTrue(settings.server_files_ok())
            self.assertFalse(settings.send_error_alerts())

    def test_get_reads_the_environment_and_optionally_the_env_file(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = os.path.join(tmp, ".env")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# a comment\nSOME_KEY = 'from-file'\n")
        with unittest.mock.patch.object(settings, "ENV_PATH", path), \
                _env(SOME_KEY="  from-env  ", BLANK="   "):
            self.assertEqual(settings.get("SOME_KEY"), "from-env")
            self.assertEqual(settings.get("SOME_KEY", env_file=True), "from-file")
            self.assertEqual(settings.get("BLANK", "fallback"), "fallback")
            self.assertEqual(settings.get("NOT_SET"), "")

    def test_the_jobs_can_import_their_settings_without_streamlit(self):
        code = ("import sys; import settings, mailer, hosting, error_alerts, update_prices, "
                "weekly_email, manage_users, admin; print('streamlit' in sys.modules)")
        out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True,
                             text=True, timeout=120)
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "False"), out.stderr)

    def test_the_moved_modules_read_through_settings(self):
        for name in ("mailer.py", "admin.py", "error_alerts.py", "update_prices.py",
                     "weekly_email.py", "manage_users.py", "hosting.py"):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                self.assertNotIn("os.environ", fh.read(), name)
        with open(os.path.join(REPO, "dashboard.py"), encoding="utf-8") as fh:
            dash = fh.read()
        for old in ('os.environ.get("PORTFOLIO_DB")', 'os.environ.get("NORTHWEND_ENV")',
                    'os.environ.get("ANTHROPIC_API_KEY")', "send_alerts=pgcompat",
                    "show_details=not pgcompat"):
            self.assertNotIn(old, dash)
        with open(os.path.join(REPO, "views", "holdings_input.py"), encoding="utf-8") as fh:
            self.assertIn("settings.server_files_ok()", fh.read())


class _App(unittest.TestCase):
    """dashboard.py through AppTest on a scratch database (never the real one)."""

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_cfg_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.uid = auth.create_user(c, "ann", PW)
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def app(self, env, **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in state.items():
            at.session_state[k] = v
        for p in (_env(MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused", **env),
                  _not_on_community_cloud(),
                  unittest.mock.patch.object(yfinance, "Ticker", offline),
                  unittest.mock.patch("socket.socket.connect", offline)):
            p.start()
            self.addCleanup(p.stop)
        return at

    def signed_in(self, env, **state):
        return self.app(env, user_id=self.uid, username="ann", page="Dashboard",
                        auto_backfilled=True, income_synced=True, **state)


class FailClosedAppTests(_App):

    def test_a_hosted_copy_without_a_database_stops_with_a_calm_message(self):
        local_file = os.path.join(REPO, "portfolio.db")
        existed = os.path.exists(local_file)
        at = self.app({"NORTHWEND_ENV": "production"})
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        self.assertEqual([e.value for e in at.error],
                         ["This copy isn't set up: PORTFOLIO_DB is missing."])
        self.assertIn("PORTFOLIO_DB", " ".join(c.value for c in at.caption))
        self.assertNotIn("login_user", [w.key for w in at.text_input])   # stopped before sign-in
        self.assertEqual(os.path.exists(local_file), existed)            # no local file made

    def test_a_hosted_copy_on_a_local_file_stops_too(self):
        at = self.app({"RENDER": "true", "PORTFOLIO_DB": self.db})
        at.run()
        self.assertEqual(len(at.error), 1)
        self.assertIn("isn't a Postgres connection string", at.error[0].value)
        self.assertNotIn(self.db, at.error[0].value)
        self.assertNotIn("login_user", [w.key for w in at.text_input])

    def test_a_local_run_with_a_scratch_file_starts_as_before(self):
        at = self.app({"PORTFOLIO_DB": self.db})
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        self.assertIn("login_user", [w.key for w in at.text_input])
        self.assertEqual([e.value for e in at.error], [])

    def test_the_server_path_box_is_only_for_a_local_run(self):
        at = self.signed_in({"PORTFOLIO_DB": self.db}, open_dialog="import")
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        self.assertIn("csv_path", [w.key for w in at.text_input])
        self.assertIn("csv_upload_0", [w.key for w in at.get("file_uploader")])
        # hosted (on a scratch file here, so the start-up check is passed by
        # hand - patched by name: the run above may have reloaded the module)
        with unittest.mock.patch("settings.config_problem", return_value=""):
            at = self.signed_in({"PORTFOLIO_DB": self.db, "NORTHWEND_ENV": "production"},
                                open_dialog="import")
            at.run()
        self.assertEqual([e.message for e in at.exception], [])
        self.assertEqual([e.value for e in at.error], [])
        self.assertIn("csv_upload_0", [w.key for w in at.get("file_uploader")])  # the dialog
        self.assertNotIn("csv_path", [w.key for w in at.text_input])


# --------------------------------------------------------------------------- #
# 4. size limits
# --------------------------------------------------------------------------- #
class SizeLimitTests(unittest.TestCase):

    def test_uploads_are_capped_at_10_mb(self):
        with open(os.path.join(REPO, ".streamlit", "config.toml"), "rb") as fh:
            self.assertEqual(tomllib.load(fh)["server"]["maxUploadSize"], 10)

    def test_a_csv_over_5000_rows_is_refused_whole(self):
        head = b"Symbol,Quantity,Value\n"
        ok = csv_import.read_rows(head + b"VTI,1,300\n" * (csv_import.MAX_ROWS - 1))
        self.assertEqual(len(ok), csv_import.MAX_ROWS)
        with self.assertRaises(csv_import.TooManyRows) as cm:
            csv_import.read_rows(head + b"VTI,1,300\n" * csv_import.MAX_ROWS)
        self.assertEqual(str(cm.exception), csv_import.TOO_MANY_ROWS)
        self.assertIn("more than 5,000 rows", csv_import.TOO_MANY_ROWS)
        # activity exports go through the same reader
        self.assertIs(txn_import.read_rows, csv_import.read_rows)

    def test_the_command_line_import_says_so_too(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = os.path.join(tmp, "big.csv")
        with open(path, "wb") as fh:
            fh.write(b"Symbol,Quantity,Value\n" + b"VTI,1,300\n" * csv_import.MAX_ROWS)
        with self.assertRaises(SystemExit) as cm:
            portfolio.parse_csv(path)
        self.assertEqual(str(cm.exception), csv_import.TOO_MANY_ROWS)

    def test_pasted_text_has_a_length_cap(self):
        line = "VTI 10\n"
        fits = line * (paste_parse.MAX_CHARS // len(line))
        self.assertEqual(paste_parse.parse(fits)["holdings"][0]["Symbol"], "VTI")
        over = paste_parse.parse(fits + "x" * (paste_parse.MAX_CHARS - len(fits) + 1))
        self.assertEqual((over["holdings"], over.get("too_long")), ([], True))
        self.assertIsNone(paste_parse.parse("VTI 10").get("too_long"))
        self.assertEqual(paste_parse.MAX_CHARS, 50_000)


class SizeLimitAppTests(_App):

    def test_the_paste_box_and_the_chat_box_have_limits(self):
        at = self.signed_in({"PORTFOLIO_DB": self.db}, open_dialog="manual")
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        self.assertEqual(at.text_area(key="me_paste").max_chars, paste_parse.MAX_CHARS)
        at = self.app({"PORTFOLIO_DB": self.db}, user_id=self.uid, username="ann",
                      page="AI Assistant", auto_backfilled=True, income_synced=True)
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        self.assertEqual([c.proto.max_chars for c in at.chat_input], [2000])

    def test_a_long_csv_gets_a_calm_message(self):
        path = os.path.join(self.dir, "big.csv")
        with open(path, "wb") as fh:
            fh.write(b"Symbol,Quantity,Value\n" + b"VTI,1,300\n" * csv_import.MAX_ROWS)
        at = self.signed_in({"PORTFOLIO_DB": self.db}, open_dialog="import", csv_path=path)
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        self.assertIn(csv_import.TOO_MANY_ROWS, [w.value for w in at.warning])

    def test_the_csv_uploader_starts_afresh_after_a_save(self):
        at = self.signed_in({"PORTFOLIO_DB": self.db}, open_dialog="import",
                            csv_path=os.path.join(BROKERS, "fidelity_positions.csv"))
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        self.assertIn("csv_upload_0", [w.key for w in at.get("file_uploader")])
        at.button(key="csv_save").click()
        at.session_state["open_dialog"] = "import"
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        self.assertEqual(at.session_state["csv_upload_n"], 1)   # next time: csv_upload_1, empty


# --------------------------------------------------------------------------- #
# 5. sign-in limits
# --------------------------------------------------------------------------- #
class SignInLimitTests(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_signin_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.db = os.path.join(self.dir, "t.db")
        self.conn = portfolio.connect(self.db)
        self.addCleanup(self.conn.close)
        self.uid = auth.create_user(self.conn, "ann", PW)

    def spray(self, n, ip=IP, start=T0):
        """n wrong passwords, each for a different username, from `ip`."""
        r = None
        for i in range(n):
            r = auth.attempt_login(self.conn, f"user{i}@example.com", "Password1", ip=ip,
                                   now=start + timedelta(seconds=i))
        return r

    def test_the_address_limit_trips_across_usernames(self):
        r = self.spray(auth.MAX_FAILED_LOGINS_PER_ADDRESS - 1)
        self.assertFalse(r["from_here"])
        r = self.spray(1, start=T0 + timedelta(minutes=1))
        self.assertTrue(r["from_here"])
        self.assertEqual(r["locked_minutes"], auth.LOCKOUT_MINUTES)
        # even the right password waits; another address doesn't
        r = auth.attempt_login(self.conn, "ann", PW, ip=IP, now=T0 + timedelta(minutes=2))
        self.assertEqual((r["user_id"], r["from_here"]), (None, True))
        r = auth.attempt_login(self.conn, "ann", PW, ip="198.51.100.4",
                               now=T0 + timedelta(minutes=2))
        self.assertEqual(r["user_id"], self.uid)
        # the pause runs out
        later = T0 + timedelta(minutes=1 + auth.LOCKOUT_MINUTES, seconds=5)
        self.assertEqual(auth.attempt_login(self.conn, "ann", PW, ip=IP, now=later)["user_id"],
                         self.uid)
        # kept like the sign-up limits: "addr:" and the hashed address, never the address
        keys = [r["username_key"] for r in self.conn.execute(
            "SELECT username_key FROM login_failures WHERE username_key LIKE 'addr:%'")]
        self.assertEqual(keys, ["addr:" + auth._address_key(IP)])
        self.assertNotIn(IP, keys[0])

    def test_a_right_password_doesnt_clear_the_address_count(self):
        self.spray(auth.MAX_FAILED_LOGINS_PER_ADDRESS - 1)
        ok = auth.attempt_login(self.conn, "ann", PW, ip=IP, now=T0 + timedelta(minutes=1))
        self.assertEqual(ok["user_id"], self.uid)
        r = auth.attempt_login(self.conn, "someone", "x", ip=IP, now=T0 + timedelta(minutes=2))
        self.assertTrue(r["from_here"])

    def test_spread_out_tries_never_add_up(self):
        for i in range(auth.MAX_FAILED_LOGINS_PER_ADDRESS + 5):
            r = auth.attempt_login(self.conn, f"u{i}", "x", ip=IP,
                                   now=T0 + timedelta(minutes=(auth.LOCKOUT_MINUTES + 1) * i))
        self.assertFalse(r["from_here"])

    def test_without_an_address_nobody_is_locked_out_together(self):
        self.spray(auth.MAX_FAILED_LOGINS_PER_ADDRESS + 5, ip=None)
        r = auth.attempt_login(self.conn, "ann", PW, ip=None, now=T0 + timedelta(minutes=1))
        self.assertEqual((r["user_id"], r["from_here"]), (self.uid, False))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) AS n FROM login_failures "
                                           "WHERE username_key LIKE 'addr:%'").fetchone()["n"], 0)

    def test_the_username_lock_still_works(self):
        for i in range(auth.MAX_FAILED_LOGINS):
            r = auth.attempt_login(self.conn, "ann", "wrong", ip=IP, now=T0 + timedelta(seconds=i))
        self.assertEqual((r["locked_minutes"], r["from_here"]), (auth.LOCKOUT_MINUTES, False))
        r = auth.attempt_login(self.conn, "ann", PW, ip="198.51.100.4",
                               now=T0 + timedelta(minutes=1))
        self.assertIsNone(r["user_id"])                 # a username lock holds from anywhere
        self.assertGreater(r["locked_minutes"], 0)

    def test_an_unknown_username_takes_the_same_one_hash(self):
        calls = []
        real = auth._hash_password

        def counting(password, salt, count=None):
            calls.append(salt)
            return real(password, salt, count)
        with unittest.mock.patch.object(auth, "_hash_password", counting):
            unknown = auth.attempt_login(self.conn, "nobody", "Password1", ip=IP, now=T0)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0], auth._DUMMY_SALT)
            wrong = auth.attempt_login(self.conn, "ann", "Password1", ip=IP, now=T0)
            self.assertEqual(len(calls), 2)
            auth.attempt_login(self.conn, "nobody@example.com", "Password1", now=T0)
            self.assertEqual(len(calls), 3)               # an email-shaped one too
        self.assertEqual(unknown, wrong)                  # nothing tells them apart


class SignInFormTests(_App):

    def sign_in(self, at, user, pw):
        at.text_input(key="login_user").input(user)
        at.text_input(key="login_pw").input(pw)
        next(b for b in at.button if b.label == "Log in").click()
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        return [e.value for e in at.error]

    def setUp(self):
        c = portfolio.connect(self.db)
        try:
            c.execute("DELETE FROM login_failures")
            c.commit()
        finally:
            c.close()

    def test_unknown_user_and_wrong_password_read_the_same(self):
        at = self.app({"PORTFOLIO_DB": self.db})
        at.run()
        unknown = self.sign_in(at, "nobody-here", "Password1")
        at = self.app({"PORTFOLIO_DB": self.db})
        at.run()
        wrong = self.sign_in(at, "ann", "Password1")
        self.assertEqual(unknown, wrong)
        self.assertEqual(unknown, ["Wrong email, username or password."])

    def test_too_many_tries_from_one_address(self):
        c = portfolio.connect(self.db)
        try:
            for i in range(auth.MAX_FAILED_LOGINS_PER_ADDRESS):
                auth.attempt_login(c, f"guess{i}", "Password1", ip=IP)
        finally:
            c.close()
        at = self.app({"PORTFOLIO_DB": self.db})
        at.run()   # (patched by name after a first run, which may reload the modules)
        with unittest.mock.patch("hosting.client_ip", return_value=IP):
            shown = self.sign_in(at, "ann", PW)
        self.assertEqual(shown, [auth.TOO_MANY_FROM_HERE])
        self.assertNotIn("user_id", at.session_state)
        # a different address (or none, running locally) signs in as usual
        at = self.app({"PORTFOLIO_DB": self.db})
        at.run()
        self.assertEqual(self.sign_in(at, "ann", PW), [])


if __name__ == "__main__":
    unittest.main()
