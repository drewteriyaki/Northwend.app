"""Error alerts (ROADMAP R1, error_alerts.py): an unexpected error or a failed
scheduled job is noted and emailed to the admin, at most once an hour per
kind - and never with anyone's data.

    python -m unittest tests.test_error_alerts        (from the repo root)
"""

import contextlib
import io
import os
import re
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
import error_alerts  # noqa: E402
import mailer  # noqa: E402
import portfolio  # noqa: E402
import settings  # noqa: E402

T0 = datetime(2026, 10, 1, 14, 0, tzinfo=timezone.utc)


def _boom():
    portfolio.money("secret-value AAPL bob@example.com")   # TypeError inside portfolio.py


def _caught(fn=_boom):
    try:
        fn()
    except Exception as ex:   # noqa: BLE001
        return ex
    raise AssertionError("expected an error")


class _DB(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_alerts_")
        self.db = os.path.join(self.dir, "test.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.conn = portfolio.connect(self.db)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def rows(self):
        return error_alerts.recent(self.conn)


class FingerprintTests(unittest.TestCase):
    def test_type_file_and_function_never_the_message(self):
        f = error_alerts.fingerprint(_caught())
        self.assertEqual(f["error_type"], "TypeError")
        self.assertEqual(f["place"], "portfolio.py, money")
        self.assertEqual(f["kind"], "TypeError in portfolio.py, money")
        self.assertIsInstance(f["line"], int)
        for leak in ("secret", "AAPL", "bob@"):
            self.assertNotIn(leak, repr(f))

    def test_the_kind_ignores_the_line(self):
        def a():
            raise KeyError("x")

        def b():
            raise KeyError("y")
        fa, fb = error_alerts.fingerprint(_caught(a)), error_alerts.fingerprint(_caught(b))
        self.assertEqual(fa["place"], "tests/test_error_alerts.py, a")
        self.assertNotEqual(fa["kind"], fb["kind"])   # different functions, different kinds
        self.assertEqual(error_alerts.fingerprint(_caught(a))["kind"], fa["kind"])

    def test_library_frames_point_back_to_our_code(self):
        def ours():
            int("not a number")   # raised inside Python, called from here
        self.assertEqual(error_alerts.fingerprint(_caught(ours))["place"],
                         "tests/test_error_alerts.py, ours")

    def test_no_traceback(self):
        f = error_alerts.fingerprint(ValueError("x"))
        self.assertEqual((f["place"], f["line"]), ("unknown", None))


class ThrottleTests(_DB):
    def rec(self, now, **kw):
        return error_alerts.record(self.conn, error_type="KeyError", place="views/plan.py, f",
                                   line=10, now=now, **kw)

    def test_one_email_an_hour_per_kind(self):
        self.assertTrue(self.rec(T0))
        self.assertFalse(self.rec(T0 + timedelta(minutes=5)))
        self.assertFalse(self.rec(T0 + timedelta(minutes=59)))
        self.assertTrue(self.rec(T0 + timedelta(minutes=61)))
        # another kind isn't held back
        self.assertTrue(error_alerts.record(self.conn, error_type="KeyError",
                                            place="views/income.py, g", now=T0))
        r = next(x for x in self.rows() if x["place"] == "views/plan.py, f")
        self.assertEqual(r["times"], 4)
        self.assertEqual(r["first_seen"], "2026-10-01T14:00:00Z")
        self.assertEqual(r["last_seen"], "2026-10-01T15:01:00Z")
        self.assertEqual(r["emailed_at"], "2026-10-01T15:01:00Z")

    def test_only_one_process_claims_it(self):
        other = portfolio.connect(self.db)   # a second app process
        try:
            first = self.rec(T0)
            second = error_alerts.record(other, error_type="KeyError",
                                         place="views/plan.py, f", now=T0)
        finally:
            other.close()
        self.assertEqual((first, second), (True, False))
        self.assertEqual(self.rows()[0]["times"], 2)

    def test_counting_only_doesnt_use_up_the_email(self):
        self.assertFalse(self.rec(T0, claim=False))
        self.assertIsNone(self.rows()[0]["emailed_at"])
        self.assertTrue(self.rec(T0))

    def test_newest_first_and_clear(self):
        error_alerts.record(self.conn, error_type="A", place="x.py, f", now=T0)
        error_alerts.record(self.conn, error_type="B", place="y.py, g",
                            now=T0 + timedelta(minutes=1))
        self.assertEqual([r["error_type"] for r in self.rows()], ["B", "A"])
        self.assertEqual(error_alerts.clear(self.conn), 2)
        self.assertEqual(self.rows(), [])

    def test_table_holds_no_account(self):
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(error_events)")}
        self.assertFalse(cols & {"user_id", "advisor_id", "client_id", "message", "email"})

    def test_both_schemas_have_it(self):
        for name in ("schema.sql", "schema_pg.sql"):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                self.assertIn("CREATE TABLE IF NOT EXISTS error_events", fh.read(), name)


class NotifyTests(_DB):
    def test_email_says_what_and_where_never_the_data(self):
        f = error_alerts.fingerprint(_caught())
        with unittest.mock.patch.object(mailer, "send", return_value=True) as send, \
                unittest.mock.patch.dict(os.environ, {"ALERT_EMAIL": "ops@example.com"}), \
                unittest.mock.patch.object(settings, "load_env", return_value={}):
            self.assertTrue(error_alerts.notify(self.conn, f, copy="Staging", ref="abc123",
                                                now=T0))
            self.assertFalse(error_alerts.notify(self.conn, f, now=T0 + timedelta(minutes=2)))
        self.assertEqual(send.call_count, 1)
        to, subject, text = send.call_args.args
        self.assertEqual(to, "ops@example.com")
        self.assertIn("Staging", subject)
        self.assertIn("TypeError in portfolio.py, money", subject)
        for want in ("Where: portfolio.py, money, line", "abc123", "No one's data"):
            self.assertIn(want, text)
        for leak in ("secret", "AAPL", "bob@"):
            self.assertNotIn(leak, subject + text)

    def test_default_address(self):
        with unittest.mock.patch.dict(os.environ, {"ALERT_EMAIL": ""}), \
                unittest.mock.patch.object(settings, "load_env", return_value={}):
            self.assertEqual(error_alerts.alert_to(), "admin@northwend.app")
            self.assertEqual(mailer._admin_to(), "admin@northwend.app")

    def test_a_failed_send_lets_the_next_one_try(self):
        f = error_alerts.fingerprint(_caught())
        with unittest.mock.patch.object(mailer, "send", return_value=False):
            self.assertFalse(error_alerts.notify(self.conn, f, now=T0))
        self.assertIsNone(self.rows()[0]["emailed_at"])
        with unittest.mock.patch.object(mailer, "send", return_value=True):
            self.assertTrue(error_alerts.notify(self.conn, f, now=T0 + timedelta(minutes=1)))

    def test_not_sending_still_lists_it(self):
        f = error_alerts.fingerprint(_caught())
        with unittest.mock.patch.object(mailer, "send") as send:
            self.assertFalse(error_alerts.notify(self.conn, f, send=False))
        send.assert_not_called()
        self.assertEqual(self.rows()[0]["times"], 1)


class ReportTests(_DB):
    """From the app: in the background, and never an error of its own."""

    def test_records_in_the_background(self):
        with unittest.mock.patch.object(mailer, "send", return_value=True) as send:
            t = error_alerts.report(self.db, _caught(), ref="abc123", copy="Live")
            t.join(10)
        self.assertEqual(self.rows()[0]["kind"], "TypeError in portfolio.py, money")
        self.assertEqual(send.call_count, 1)

    def test_never_raises(self):
        with contextlib.redirect_stderr(io.StringIO()) as err:
            t = error_alerts.report(self.dir, _caught())   # a folder, not a database
            t.join(10)
            self.assertIsNone(error_alerts.report(None, _caught()))
        self.assertIn("couldn't record", err.getvalue())
        with unittest.mock.patch.object(error_alerts, "fingerprint", side_effect=RuntimeError):
            self.assertIsNone(error_alerts.report(self.db, _caught()))

    def test_a_slow_email_doesnt_hold_up_the_page(self):
        def slow(*a, **k):
            time.sleep(1.5)
            return True
        with unittest.mock.patch.object(mailer, "send", side_effect=slow):
            started = time.monotonic()
            t = error_alerts.report(self.db, _caught())
            self.assertLess(time.monotonic() - started, 0.5)
            t.join(10)


class SaveFailedTests(_DB):
    """Audit X4: a save the page catches shows the calm message with a code -
    never the exception's text - and is noted for the admin like any error."""

    def test_the_message_has_a_code_and_none_of_the_error(self):
        import friendly_errors
        ex = _caught()
        with unittest.mock.patch.dict(friendly_errors._alert, {"db": self.db, "copy": "Live",
                                                               "send": False}), \
                contextlib.redirect_stderr(io.StringIO()) as err, \
                unittest.mock.patch.object(error_alerts, "report") as report:
            msg = friendly_errors.save_failed(ex, "Removing it")
        ref = re.search(r"error code \*\*([0-9a-f]{6})\*\*", msg).group(1)
        self.assertTrue(msg.startswith("Removing it didn't work, so nothing was changed."))
        for raw in ("secret-value", "AAPL", "bob@example.com", "TypeError", "money"):
            self.assertNotIn(raw, msg)
        self.assertIn(f"error code {ref}", err.getvalue())     # ties the log to the code
        self.assertEqual(report.call_args.kwargs["ref"], ref)
        self.assertEqual(report.call_args.args[0], self.db)


class JobTests(_DB):
    URL = "https://github.com/o/r/actions/runs/1"

    def test_a_failed_job_emails_once_an_hour(self):
        with unittest.mock.patch.object(mailer, "send", return_value=True) as send:
            self.assertTrue(error_alerts.job_failed(self.db, "Refresh live prices", self.URL))
            self.assertFalse(error_alerts.job_failed(self.db, "Refresh live prices", self.URL))
            self.assertTrue(error_alerts.job_failed(self.db, "Sync price history", self.URL))
        self.assertEqual(send.call_count, 2)
        subject, text = send.call_args_list[0].args[1:3]
        self.assertIn("Refresh live prices", subject)
        self.assertIn(self.URL, text)
        r = next(x for x in self.rows() if x["place"] == "Refresh live prices")
        self.assertEqual((r["source"], r["times"]), ("job", 2))

    def test_database_down_still_emails(self):
        with unittest.mock.patch.object(mailer, "send", return_value=True) as send, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertTrue(error_alerts.job_failed(self.dir, "Sync price history", self.URL))
        self.assertIn("couldn't be reached", send.call_args.args[2])

    def test_command_line(self):
        with unittest.mock.patch.object(mailer, "send", return_value=True), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            code = error_alerts.main(["job", "Advisors' Monday email", "--db", self.db,
                                      "--run-url", self.URL])
        self.assertEqual(code, 0)
        self.assertIn("Alert sent", out.getvalue())

    def test_every_scheduled_job_has_a_failure_step(self):
        with open(os.path.join(REPO, ".github", "workflows", "scheduled-sync.yml"),
                  encoding="utf-8") as fh:
            text = fh.read()
        jobs = re.findall(r"^  ([\w-]+):\s*$", text.split("\njobs:", 1)[1], re.M)
        self.assertGreaterEqual(len(jobs), 3)
        self.assertEqual(text.count("if: failure()"), len(jobs))
        self.assertEqual(text.count("python error_alerts.py job "), len(jobs))


class AppTests(_DB):
    """The friendly error page notes the error; the System panel lists it."""

    PAGE = """
import sys
sys.path.insert(0, {repo!r})
import friendly_errors
friendly_errors.install(alert_db={db!r}, copy="Live", send_alerts=False)
_boom = __import__("portfolio").money
_boom("secret-value")
"""

    def test_an_error_on_a_page_is_noted(self):
        from streamlit.testing.v1 import AppTest
        with contextlib.redirect_stderr(io.StringIO()):
            at = AppTest.from_string(self.PAGE.format(repo=REPO, db=self.db)).run()
        self.assertIn("Something went wrong", at.error[0].value)
        for _ in range(100):   # it's written in the background
            if self.rows():
                break
            time.sleep(0.05)
        r = self.rows()[0]
        self.assertEqual(r["kind"], "TypeError in portfolio.py, money")
        self.assertIsNone(r["emailed_at"])   # a local copy only lists it

    PANEL = """
import sys, os
sys.path.insert(0, {repo!r})
import pandas as pd
import streamlit as st
import auth, mailer, pgcompat
from portfolio import connect
HERE = {repo!r}
DB = {db!r}
STAGING = False
HOSTED = False
APP_NAME = "Northwend"
LOGIN_ID = {uid}
IS_ADVISOR = False
_app_address = lambda: ""
_anthropic_key = lambda: None
resolve_key = lambda k: None
st.session_state["user_id"] = {uid}
st.session_state["username"] = "boss"
path = os.path.join(HERE, "views", "admin.py")
with open(path, encoding="utf-8") as fh:
    exec(compile(fh.read(), path, "exec"), globals())
msg = st.session_state.pop("admin_msg", None)
if msg:
    getattr(st, msg[0])(msg[1])
c = connect(DB)
_render_system(c)
c.close()
"""

    def test_system_panel_lists_and_clears(self):
        from streamlit.testing.v1 import AppTest
        import admin
        uid = auth.create_user(self.conn, "boss", "pw-boss-123")
        admin.set_admin(self.conn, "boss", True)
        error_alerts.record(self.conn, error_type="KeyError", place="views/plan.py, f",
                            line=12, now=T0)
        error_alerts.record(self.conn, error_type="Job failed", place="Sync price history",
                            source="job", now=T0 + timedelta(hours=1))
        at = AppTest.from_string(self.PANEL.format(repo=REPO, db=self.db, uid=uid),
                                 default_timeout=30).run()
        self.assertEqual(len(at.exception), 0, [e.message for e in at.exception])
        md = "\n".join(m.value for m in at.markdown)
        self.assertIn("Recent errors", md)
        self.assertIn("**Error alerts:** listed below only", md)
        df = at.dataframe[0].value
        self.assertEqual(list(df["What"]), ["Scheduled job failed", "KeyError"])
        self.assertEqual(list(df["Where"]), ["Sync price history", "views/plan.py, f, line 12"])
        next(b for b in at.button if b.label == "Clear the list").click().run()
        self.assertEqual(self.rows(), [])
        self.assertIn("Cleared the list of errors.", [s.value for s in at.success])
        self.assertTrue(any("None noted" in c.value for c in at.caption))


if __name__ == "__main__":
    unittest.main()
