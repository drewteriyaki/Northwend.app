"""App use (analytics.py, flag analytics; direction item 12): events in
Northwend's own database. The validator drops anything not on its
allow-lists; nothing is recorded with the flag off, for someone opted out, a
browser sending Global Privacy Control / Do Not Track, an admin or an advisor
in a client's account; opting out deletes the past events; the 12-month
prune; the admin summary hides groups under 20; page_opened once per page
change; no user id anywhere in the table; both schema files in step; Home's
queries no worse than one more per run.

    python -m unittest tests.test_analytics        (from the repo root)
"""

import contextlib
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import admin  # noqa: E402
import analytics  # noqa: E402
import auth  # noqa: E402
import export  # noqa: E402
import feature_counts  # noqa: E402
import flags  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sample_data  # noqa: E402
import tidy  # noqa: E402
import two_step  # noqa: E402

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
ID_A, ID_B = "0123456789abcdef", "fedcba9876543210"


def _events(conn, anon=None):
    sql = "SELECT * FROM analytics_events" + (" WHERE anon_id = ?" if anon else "")
    return [dict(r) for r in conn.execute(sql + " ORDER BY id", (anon,) if anon else ())]


class _DB(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_analytics_")
        self.db = os.path.join(self.dir, "t.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.conn = portfolio.connect(self.db)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.dir, ignore_errors=True)


# --------------------------------------------------------------------------- #
# the validator
# --------------------------------------------------------------------------- #
class CleanTests(unittest.TestCase):

    def test_only_listed_events(self):
        self.assertIsNone(analytics.clean("bought_VTI"))
        self.assertIsNone(analytics.clean(None))
        self.assertIsNone(analytics.clean({"event": "page_opened"}))
        self.assertEqual(analytics.clean("page_opened", "Plan"), ("page_opened", "Plan", None))

    def test_forbidden_props_are_dropped(self):
        bad = {"amount": "1200", "ticker": "VTI", "symbol": "AAPL", "account": "Roth IRA",
               "email": "a@b.co", "name": "Ann", "text": "what should I buy?",
               "value": 1234.5, "user_id": "7", "query": "x",
               "method": "123 Main St",          # a listed key with an unlisted value
               "device": "Mozilla/5.0 (iPhone)",  # the browser string, never kept
               "kind": "menu_401k"}               # not one of holdings_added's keys
        self.assertEqual(analytics.clean("holdings_added", "Dashboard", bad),
                         ("holdings_added", "Dashboard", None))
        got = analytics.clean("holdings_added", "Dashboard",
                              {**bad, "method": "csv", "device": "phone"})
        self.assertEqual(json.loads(got[2]), {"method": "csv", "device": "phone"})

    def test_non_strings_and_unknown_pages_are_dropped(self):
        got = analytics.clean("decoder_used", "VTI", {"kind": ["menu_401k"], "device": 1})
        self.assertEqual(got, ("decoder_used", None, None))
        self.assertEqual(analytics.clean("page_opened", "Ticker VTI")[1], None)
        self.assertEqual(analytics.clean("page_opened", "Ticker")[1], "Ticker")

    def test_every_prop_value_is_a_short_word(self):
        for key, values in analytics.PROPS.items():
            for v in values:
                self.assertRegex(v, r"^[a-z0-9_]{2,12}$", key)
        for event, keys in analytics.EVENTS.items():
            self.assertTrue(set(keys) <= set(analytics.PROPS), event)

    def test_every_page_the_app_lists_is_known(self):
        with open(os.path.join(REPO, "dashboard.py"), encoding="utf-8") as fh:
            src = fh.read()
        block = src[src.index("if IS_ADVISOR:\n    _start"):src.index("PAGES.append(TICKER_PAGE)")]
        named = set(re.findall(r'"([A-Z][A-Za-z\' ]+)"', block))
        named |= {"Ticker", "Admin", "Advisor preview", "Find a guide"}
        self.assertEqual(named - set(analytics.PAGES), set())

    def test_device_kind_only(self):
        self.assertEqual(analytics.device_of({"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone "
                                                            "OS 17_0) Mobile/15E148"}), "phone")
        self.assertEqual(analytics.device_of({"user-agent": "Mozilla/5.0 (Linux; Android 14; "
                                                            "Pixel 8) Mobile Safari"}), "phone")
        self.assertEqual(analytics.device_of({"User-Agent": "Mozilla/5.0 (iPad; CPU OS 17)"}),
                         "tablet")
        self.assertEqual(analytics.device_of({"User-Agent": "Mozilla/5.0 (Windows NT 10.0)"}),
                         "computer")
        self.assertIsNone(analytics.device_of({}))
        self.assertIsNone(analytics.device_of(None))


# --------------------------------------------------------------------------- #
# when nothing is recorded
# --------------------------------------------------------------------------- #
class AllowedTests(unittest.TestCase):

    def ok(self, **kw):
        return analytics.allowed(**{"prefs": {}, "headers": {}, "flag": True, **kw})

    def test_the_plain_case(self):
        self.assertTrue(self.ok())

    def test_flag_off(self):
        self.assertFalse(self.ok(flag=False))
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": ""}):
            self.assertFalse(analytics.allowed(prefs={}, headers={}))
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": "analytics"}):
            self.assertTrue(analytics.allowed(prefs={}, headers={}))
        self.assertEqual(flags.FEATURES["analytics"], {"gates": (), "view": None})

    def test_opted_out(self):
        self.assertFalse(self.ok(prefs={feature_counts.PREF_OFF: True}))
        self.assertTrue(self.ok(prefs={feature_counts.PREF_OFF: False}))
        self.assertEqual(analytics.PREF_OFF, "feature_counts_off")   # old choices carry over

    def test_gpc_and_dnt(self):
        self.assertFalse(self.ok(headers={"Sec-GPC": "1"}))
        self.assertFalse(self.ok(headers={"sec-gpc": "1"}))
        self.assertFalse(self.ok(headers={"DNT": "1"}))
        self.assertTrue(self.ok(headers={"DNT": "0"}))

    def test_admin_advisor_in_a_clients_account_and_signed_out(self):
        self.assertFalse(self.ok(is_admin=True))
        self.assertFalse(self.ok(in_clients_account=True))
        self.assertFalse(self.ok(signed_in=False))

    def test_the_switch_keeps_its_published_name_until_the_flag_is_on(self):
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": ""}):
            self.assertEqual(analytics.switch_label(), "Leave me out of feature counts")
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": "analytics"}):
            self.assertEqual(analytics.switch_label(), "Don't use my data to improve the app")


# --------------------------------------------------------------------------- #
# storage, opting out, deletion, prune, export, the admin summary
# --------------------------------------------------------------------------- #
class StoreTests(_DB):

    def test_record_one_row_with_no_user_id(self):
        self.assertTrue(analytics.record(self.conn, ID_A, "holdings_added", "Dashboard",
                                         {"method": "paste", "ticker": "VTI"}, now=NOW))
        rows = _events(self.conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0]), {"id", "at", "anon_id", "event", "page", "props"})
        self.assertEqual((rows[0]["at"], rows[0]["anon_id"], rows[0]["props"]),
                         ("2026-10-10T12:00:00Z", ID_A, '{"method": "paste"}'))

    def test_bad_ids_and_events_record_nothing_and_never_raise(self):
        self.assertFalse(analytics.record(self.conn, "7", "page_opened"))
        self.assertFalse(analytics.record(self.conn, None, "page_opened"))
        self.assertFalse(analytics.record(self.conn, ID_A, "sold_everything"))
        broken = unittest.mock.MagicMock()
        broken.execute.side_effect = sqlite3.OperationalError("no such table")
        self.assertFalse(analytics.record(broken, ID_A, "page_opened"))
        self.assertEqual(_events(self.conn), [])

    def test_forget_deletes_only_that_id_and_the_id(self):
        for anon in (ID_A, ID_A, ID_B):
            analytics.record(self.conn, anon, "page_opened", "Plan", now=NOW)
        p = {analytics.PREF_ID: ID_A, "hide_amounts": True}
        self.assertEqual(analytics.forget(self.conn, p), 2)
        self.conn.commit()
        self.assertEqual(p, {"hide_amounts": True})
        self.assertEqual([r["anon_id"] for r in _events(self.conn)], [ID_B])
        self.assertEqual(analytics.forget(self.conn, {}), 0)

    def test_deleting_the_account_deletes_its_events(self):
        uid = auth.create_user(self.conn, "ann", "pw-123456789")
        other = auth.create_user(self.conn, "ben", "pw-123456789")
        prefs.save(self.conn, uid, {analytics.PREF_ID: ID_A})
        prefs.save(self.conn, other, {analytics.PREF_ID: ID_B})
        analytics.record(self.conn, ID_A, "page_opened", "Plan", now=NOW)
        analytics.record(self.conn, ID_B, "page_opened", "Plan", now=NOW)
        self.assertTrue(admin.delete_account(self.conn, uid, by=-1)["ok"])
        self.assertEqual([r["anon_id"] for r in _events(self.conn)], [ID_B])
        self.assertNotIn("analytics_events", admin.ACCOUNT_TABLES)

    def test_prune_after_twelve_months_and_in_the_nightly_tidy(self):
        analytics.record(self.conn, ID_A, "page_opened", now=NOW - timedelta(days=366))
        analytics.record(self.conn, ID_A, "page_opened", now=NOW - timedelta(days=364))
        self.assertEqual(analytics.KEEP_DAYS, 365)
        done = tidy.run(self.conn, now=NOW)
        self.assertEqual(done["app-use events"], 1)
        self.assertEqual(len(_events(self.conn)), 1)
        self.assertEqual(analytics.prune(self.conn, now=NOW), 0)

    def test_own_events_in_export_everything(self):
        uid = auth.create_user(self.conn, "ann", "pw-123456789")
        prefs.save(self.conn, uid, {analytics.PREF_ID: ID_A})
        analytics.record(self.conn, ID_A, "decoder_used", "Plan", {"kind": "factsheet"}, now=NOW)
        analytics.record(self.conn, ID_B, "page_opened", "Plan", now=NOW)   # someone else's
        got = export.collect(self.conn, uid)["app_use"]
        self.assertEqual(got, [{"at": "2026-10-10T12:00:00Z", "event": "decoder_used",
                                "page": "Plan", "details": '{"kind": "factsheet"}'}])
        self.assertIn("app_use.csv", export.README)
        uid2 = auth.create_user(self.conn, "cy", "pw-123456789")
        self.assertNotIn("app_use", export.collect(self.conn, uid2))

    def test_admin_summary_hides_groups_under_twenty(self):
        ids = [f"{i:016x}" for i in range(25)]
        for anon in ids[:19]:
            analytics.record(self.conn, anon, "page_opened", "Plan", {"device": "phone"},
                             now=NOW - timedelta(days=1))
            analytics.record(self.conn, anon, "walk_finished", now=NOW - timedelta(days=1))
        analytics.record(self.conn, ids[0], "ask_question", now=NOW)   # one person
        s = analytics.summary(self.conn, now=NOW)
        self.assertEqual(s, {"events": [], "details": [], "pages": [], "days": []})
        analytics.record(self.conn, ids[19], "page_opened", "Plan", {"device": "phone"},
                         now=NOW - timedelta(days=1))
        analytics.record(self.conn, ids[20], "page_opened", "Plan",
                         now=NOW - timedelta(days=40))                   # too long ago
        s = analytics.summary(self.conn, now=NOW)
        self.assertEqual(s["events"], [{"event": "page_opened", "times": 20, "people": 20}])
        self.assertEqual(s["details"], [{"event": "page_opened", "detail": "device phone",
                                         "people": 20}])
        self.assertEqual(s["pages"], [{"page": "Plan", "times": 20, "people": 20}])
        self.assertEqual(s["days"], [{"day": "2026-10-09", "people": 20}])
        flat = json.dumps(s)
        for anon in ids:
            self.assertNotIn(anon, flat)                                # never an id
        self.assertEqual(analytics.MIN_GROUP, feature_counts.MIN_GROUP)


class AdminPanelTests(_DB):
    PANEL = """
import sys, os
sys.path.insert(0, {repo!r})
import pandas as pd
import streamlit as st
from portfolio import connect
HERE = {repo!r}
DB = {db!r}
STAGING = False
HOSTED = False
LOGIN_ID = 1
IS_ADVISOR = False
_label = lambda p: p
path = os.path.join(HERE, "views", "admin.py")
with open(path, encoding="utf-8") as fh:
    exec(compile(fh.read(), path, "exec"), globals())
c = connect(DB)
_render_app_use(c)
c.close()
"""

    def _panel(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_string(self.PANEL.format(repo=REPO, db=self.db),
                                 default_timeout=30).run()
        self.assertEqual(len(at.exception), 0, [e.message for e in at.exception])
        return at

    def test_nothing_under_twenty_and_never_an_id(self):
        now = datetime.now(timezone.utc) - timedelta(hours=1)
        ids = [f"{i:016x}" for i in range(20)]
        for anon in ids[:19]:
            analytics.record(self.conn, anon, "page_opened", "Plan", now=now)
        at = self._panel()
        self.assertIn("App use (last 30 days)", [h.value for h in at.subheader])
        self.assertIn("nothing to show yet", " ".join(c.value for c in at.caption))
        self.assertEqual(len(at.dataframe), 0)
        analytics.record(self.conn, ids[19], "page_opened", "Plan", now=now)
        at = self._panel()
        frames = [d.value for d in at.dataframe]
        self.assertTrue(frames)
        flat = " ".join(f.to_csv() for f in frames)
        self.assertIn("Opened a page", flat)
        for anon in ids:
            self.assertNotIn(anon, flat)
        # nothing by advisor (or by account): the summary's queries name neither
        import inspect
        with open(os.path.join(REPO, "views", "admin.py"), encoding="utf-8") as fh:
            view = fh.read()
        panel = view[view.index("def _render_app_use"):]
        panel = panel[:panel.index("\ndef ", 5)] if "\ndef " in panel[5:] else panel
        src = inspect.getsource(analytics.summary) + panel
        for word in ("advisor_id", "client_id", "user_id", "is_advisor", "advisor_clients",
                     "users", "JOIN"):
            self.assertNotIn(word, src)


# --------------------------------------------------------------------------- #
# the schema
# --------------------------------------------------------------------------- #
def _columns(path, table="analytics_events"):
    with open(path, encoding="utf-8") as fh:
        sql = fh.read()
    body = re.search(rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\n\);", sql, re.S).group(1)
    body = re.sub(r"--[^\n]*", "", body)
    return [line.split()[0] for line in body.split(",") if line.strip()]


class SchemaTests(_DB):

    def test_no_user_id_and_both_files_in_step(self):
        lite = _columns(os.path.join(REPO, "schema.sql"))
        pg = _columns(os.path.join(REPO, "schema_pg.sql"))
        self.assertEqual(lite, ["id", "at", "anon_id", "event", "page", "props"])
        self.assertEqual(lite, pg)
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(analytics_events)")}
        self.assertEqual(cols, set(lite))
        self.assertGreaterEqual(portfolio.SCHEMA_VERSION, 14)


# --------------------------------------------------------------------------- #
# in the app
# --------------------------------------------------------------------------- #
class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or "")) == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_analytics_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.alice = auth.create_user(c, "alice", "pw-123456789")
            sample_data.load(c, cls.alice)
            prefs.save(c, cls.alice, {"first_steps": {"done": True}})
            cls.olga = auth.create_user(c, "olga", "pw-123456789")       # opted out
            sample_data.load(c, cls.olga)
            prefs.save(c, cls.olga, {"first_steps": {"done": True},
                                     feature_counts.PREF_OFF: True})
            cls.carol = auth.create_user(c, "carol", "pw-123456789")     # an advisor
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dave = auth.create_user(c, "dave", "pw-123456789")       # her client
            auth.link_client(c, cls.carol, cls.dave)
            sample_data.load(c, cls.dave)
            prefs.save(c, cls.dave, {"first_steps": {"done": True}})
            cls.root = auth.create_user(c, "root", "pw-123456789")       # an admin
            admin.set_admin(c, "root", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.root, secret, two_step.totp(secret))
            cls.root_ok = f"{cls.root}:{two_step.status(c, cls.root)['stamp']}"
            sample_data.load(c, cls.root)
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        c = portfolio.connect(self.db)
        try:
            c.execute("DELETE FROM analytics_events")
            c.commit()
        finally:
            c.close()

    @contextlib.contextmanager
    def _app(self, uid, name, page="Dashboard", flags_on="analytics", counter=None, **state):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": page,
                     "auto_backfilled": True, "income_synced": True, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "ANTHROPIC_API_KEY",
                            "RESEND_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", NORTHWEND_FLAGS=flags_on)
        patches = [unittest.mock.patch.dict(os.environ, env, clear=True),
                   unittest.mock.patch("socket.socket.connect", offline_net.connect)]
        if counter is not None:
            patches.append(unittest.mock.patch("sqlite3.connect", counter))
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    def _rows(self):
        c = portfolio.connect(self.db)
        try:
            return _events(c)
        finally:
            c.close()

    def _prefs(self, uid):
        c = portfolio.connect(self.db)
        try:
            return prefs.load(c, uid)
        finally:
            c.close()

    def test_page_opened_once_per_page_change(self):
        with self._app(self.alice, "alice") as at:
            rows = self._rows()
            self.assertEqual([(r["event"], r["page"]) for r in rows],
                             [("page_opened", "Dashboard")])
            anon = self._prefs(self.alice)[analytics.PREF_ID]
            self.assertEqual(rows[0]["anon_id"], anon)
            self.assertNotEqual(anon, str(self.alice))
            at.run()                                                # a rerun: nothing new
            self.assertEqual(len(self._rows()), 1)
            at.session_state["page"] = "Plan"
            at.run()
            at.run()
            self.assertEqual([(r["event"], r["page"]) for r in self._rows()],
                             [("page_opened", "Dashboard"), ("page_opened", "Plan")])
            self.assertEqual({r["anon_id"] for r in self._rows()}, {anon})

    def test_nothing_with_the_flag_off(self):
        with self._app(self.alice, "alice", flags_on="") as at:
            at.session_state["page"] = "Plan"
            at.run()
        self.assertEqual(self._rows(), [])

    def test_nothing_for_someone_opted_out(self):
        with self._app(self.olga, "olga") as at:
            at.session_state["page"] = "Plan"
            at.run()
        self.assertEqual(self._rows(), [])
        self.assertNotIn(analytics.PREF_ID, self._prefs(self.olga))

    def test_nothing_for_an_admin(self):
        with self._app(self.root, "root", two_step_ok=self.root_ok) as at:
            at.session_state["page"] = "Plan"
            at.run()
        self.assertEqual(self._rows(), [])

    def test_nothing_for_an_advisor_in_a_clients_account(self):
        before = self._prefs(self.dave)
        with self._app(self.carol, "carol", active_user_id=self.dave,
                       two_step_ok=self.carol_ok) as at:
            at.session_state["page"] = "Plan"
            at.run()
        self.assertEqual(self._rows(), [])
        self.assertEqual(self._prefs(self.dave), before)               # no id written there
        self.assertNotIn(analytics.PREF_ID, self._prefs(self.carol))

    def test_the_switch_deletes_past_events_at_once(self):
        c = portfolio.connect(self.db)
        try:
            p = prefs.load(c, self.alice)
            p[analytics.PREF_ID] = ID_A
            prefs.save(c, self.alice, p)
            analytics.record(c, ID_A, "walk_finished", now=NOW)
            analytics.record(c, ID_B, "walk_finished", now=NOW)          # someone else's
        finally:
            c.close()
        with self._app(self.alice, "alice", page="Account") as at:
            toggle = at.toggle(key="acct_counts_off")
            self.assertEqual(toggle.label, "Don't use my data to improve the app")
            captions = " ".join(c.value for c in at.caption)
            self.assertIn("the ones already recorded are deleted", captions)
            toggle.set_value(True).run()
            self.assertEqual([r["anon_id"] for r in self._rows()], [ID_B])
            p = self._prefs(self.alice)
            self.assertIs(p[feature_counts.PREF_OFF], True)
            self.assertNotIn(analytics.PREF_ID, p)
            at.session_state["page"] = "Plan"
            at.run()
            self.assertEqual([r["anon_id"] for r in self._rows()], [ID_B])  # none from now on
        # turned off again: a new id, never the old one
        c = portfolio.connect(self.db)
        try:
            p = prefs.load(c, self.alice)
            p[feature_counts.PREF_OFF] = False
            prefs.save(c, self.alice, p)
        finally:
            c.close()
        with self._app(self.alice, "alice"):
            pass
        new = self._prefs(self.alice)[analytics.PREF_ID]
        self.assertNotEqual(new, ID_A)
        self.assertEqual(self._rows()[-1]["anon_id"], new)

    def test_the_switch_keeps_its_published_name_while_the_flag_is_off(self):
        with self._app(self.alice, "alice", page="Account", flags_on="") as at:
            self.assertEqual(at.toggle(key="acct_counts_off").label,
                             "Leave me out of feature counts")

    def _queries(self, flags_on):
        """Home's queries on its first and second runs (CLAUDE.md "Testing
        on scratch data"), alice already having her id."""
        seen = {"sql": 0}
        real = sqlite3.connect

        def counting(*a, **k):
            conn = real(*a, **k)
            conn.set_trace_callback(lambda s: seen.__setitem__(
                "sql", seen["sql"] + (not s.startswith("PRAGMA"))))
            return conn
        with self._app(self.alice, "alice", flags_on=flags_on, counter=counting) as at:
            first = seen["sql"]
            seen["sql"] = 0
            at.run()
            second = seen["sql"]
        return first, second

    def test_home_costs_at_most_one_more_query_a_run(self):
        c = portfolio.connect(self.db)
        try:
            p = prefs.load(c, self.alice)
            p[analytics.PREF_ID] = ID_A
            p.pop(feature_counts.PREF_OFF, None)
            prefs.save(c, self.alice, p)
        finally:
            c.close()
        off_first, off_second = self._queries("")
        on_first, on_second = self._queries("analytics")
        self.assertLessEqual(on_second, off_second)          # a rerun: nothing at all
        self.assertLessEqual(on_first, off_first + 1)        # a page change: the one INSERT
        self.assertEqual(len(self._rows()), 1)


class WiringTests(unittest.TestCase):
    """The feature events sit where they happen, and pass only listed words."""

    CALLS = {
        "views/holdings_input.py": ('_track("holdings_added"',),
        "views/checkin.py": ('_track("walk_finished")',),
        "views/menu_decoder.py": ('_track("decoder_used", kind="menu_401k")',),
        "views/factsheet_decoder.py": ('_track("decoder_used", kind="factsheet")',),
        "views/first_steps.py": ('_track("first_steps_done")', '_track("first_steps_skipped")'),
        "views/assistant.py": ('_track("ask_question")',),
        "views/challenges.py": ('_track("challenge_started")',),
        "views/drills.py": ('_track("drill_done")',),
        "dashboard.py": ('_track("page_opened", PAGE)', "st.context.headers",
                         "in_clients_account=ON_CLIENT", "is_admin=IS_ADMIN",
                         "USER_ID != LOGIN_ID"),
    }

    def test_each_call_is_there_and_names_a_listed_event(self):
        for path, calls in self.CALLS.items():
            with open(os.path.join(REPO, path), encoding="utf-8") as fh:
                src = fh.read()
            for call in calls:
                self.assertIn(call, src, path)
            for event in re.findall(r'_track\("([a-z_]+)"', src):
                self.assertIn(event, analytics.EVENTS, path)


if __name__ == "__main__":
    unittest.main()
