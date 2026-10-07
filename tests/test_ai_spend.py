"""PLAN step 1a item 6 (AI ceiling, first slice; AI_PLAN 10 steps 2 and 6,
AI_COSTS 7): hard caps on a chat message, every AI answer's token counts and
estimated cost in `ai_spend` (counts only, no text, no user_id), the app-wide
month total against NORTHWEND_AI_CEILING_USD, the admin's emails at 50% and
80%, and what each feature does at 80%, 95% and 100%.

    python -m unittest tests.test_ai_spend     (from the repo root)
"""

import os
import re
import shutil
import sys
import tempfile
import types
import unittest
import unittest.mock
from datetime import date, datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import advisor  # noqa: E402
import ai_spend  # noqa: E402
import ai_usage  # noqa: E402
import auth  # noqa: E402
import csv_import  # noqa: E402
import mailer  # noqa: E402
import meeting  # noqa: E402
import portfolio  # noqa: E402
import screenshot_read  # noqa: E402
import settings  # noqa: E402
import txn_import  # noqa: E402

PW = "pw-123456789"
WHEN = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
SONNET = "claude-sonnet-5"
DOLLAR = 1_000_000   # micro-dollars


def _usage(**kw):
    return types.SimpleNamespace(input_tokens=kw.get("i", 0), output_tokens=kw.get("o", 0),
                                 cache_creation_input_tokens=kw.get("w", 0),
                                 cache_read_input_tokens=kw.get("r", 0))


def _ceiling(usd="100"):
    return unittest.mock.patch.dict(os.environ, {"NORTHWEND_AI_CEILING_USD": usd})


class _DB(unittest.TestCase):
    def setUp(self):
        ai_spend.use_db(None)   # an earlier app run's database is long gone
        self.dir = tempfile.mkdtemp(prefix="pt_aispend_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.db = os.path.join(self.dir, "t.db")
        self.conn = portfolio.connect(self.db)
        self.addCleanup(self.conn.close)
        self.addCleanup(ai_spend.use_db, None)

    def spend(self, micro, now=WHEN, helper="chat"):
        """Add `micro` micro-dollars of spend (as output tokens on Sonnet: $10 per
        million, so 1 token = 10 micro-dollars)."""
        assert micro % 10 == 0
        ai_spend.record(self.conn, helper, SONNET, {"output_tokens": micro // 10}, now=now)


# --------------------------------------------------------------------------- #
# the hard caps (AI_PLAN 10 step 2)
# --------------------------------------------------------------------------- #
class CapTests(unittest.TestCase):

    def setUp(self):
        ai_spend.use_db(None)   # an earlier app run's database is long gone

    def test_the_caps(self):
        self.assertEqual(advisor.MAX_TOKENS, 2500)
        self.assertEqual(advisor.MAX_TOOL_ROUNDS, 3)
        with open(os.path.join(REPO, "dashboard.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertRegex(src, r"(?m)^CHAT_MESSAGE_LIMIT = 30\b")
        self.assertRegex(src, r"(?m)^CHAT_MAX_CHARS = 2000\b")
        self.assertEqual(ai_spend.CHAT_MAX_TOKENS_REDUCED, 1500)
        self.assertLess(ai_spend.CHAT_MAX_TOKENS_REDUCED, advisor.MAX_TOKENS)

    def test_a_reply_takes_at_most_three_rounds_and_the_capped_length(self):
        calls = []

        class _Stream:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def __iter__(self):
                return iter(())

            def get_final_message(self):   # always asks for another tool round
                block = types.SimpleNamespace(type="tool_use", name="save_memory", id="t",
                                              input={"notes": "- likes index funds"})
                return types.SimpleNamespace(stop_reason="tool_use", content=[block],
                                             usage=_usage(i=100, o=50))

        class _Client:
            @property
            def messages(self):
                return self

            def stream(self, **kw):
                calls.append(kw)
                return _Stream()
        list(advisor.stream_reply(_Client(), [{"role": "user", "content": "x"}], "sys",
                                  lambda f: None, lambda t: None, max_tokens=99_999))
        self.assertEqual(len(calls), 3)
        self.assertEqual({c["max_tokens"] for c in calls}, {2500})
        calls.clear()
        list(advisor.stream_reply(_Client(), [{"role": "user", "content": "x"}], "sys",
                                  lambda f: None, lambda t: None,
                                  **ai_spend.chat_settings(ai_spend.REDUCED)))
        self.assertEqual({(c["max_tokens"], c["output_config"]["effort"]) for c in calls},
                         {(1500, "low")})
        self.assertEqual(ai_spend.chat_settings(ai_spend.ALERT), {})


# --------------------------------------------------------------------------- #
# logging: counts and cost, never text
# --------------------------------------------------------------------------- #
class LoggingTests(_DB):

    def test_the_table_holds_counts_only(self):
        cols = {r["name"]: r["type"] for r in self.conn.execute("PRAGMA table_info(ai_spend)")}
        self.assertEqual(set(cols), {
            "month", "helper", "model", "calls", "input_tokens", "output_tokens",
            "cache_write_tokens", "cache_read_tokens", "cost_micro", "updated_at"})
        self.assertNotIn("user_id", cols)
        # the only text columns are the keys and the time - nowhere for a prompt or answer
        self.assertEqual({c for c, t in cols.items() if t == "TEXT"},
                         {"month", "helper", "model", "updated_at"})
        alert_cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(ai_alerts)")}
        self.assertEqual(alert_cols, {"month", "level", "sent_at"})
        # not account data: no account column, so not in the delete or export lists
        import admin
        self.assertNotIn("ai_spend", admin.ACCOUNT_TABLES)
        self.assertNotIn("ai_alerts", admin.ACCOUNT_TABLES)
        for path in ("schema.sql", "schema_pg.sql"):
            with open(os.path.join(REPO, path), encoding="utf-8") as fh:
                src = fh.read()
            self.assertIn("CREATE TABLE IF NOT EXISTS ai_spend", src, path)
            self.assertIn("CREATE TABLE IF NOT EXISTS ai_alerts", src, path)

    def test_usage_and_cost(self):
        resp = types.SimpleNamespace(usage=_usage(i=1000, o=500, w=2000, r=4000))
        u = ai_spend.usage_of(resp)
        self.assertEqual(u, {"input_tokens": 1000, "output_tokens": 500,
                             "cache_write_tokens": 2000, "cache_read_tokens": 4000})
        # Sonnet: $2 in, $10 out, $2.50 cache write, $0.20 cache read per million
        self.assertEqual(ai_spend.cost_micro(SONNET, u), 2000 + 5000 + 5000 + 800)
        # Haiku is half
        self.assertEqual(ai_spend.cost_micro(csv_import.AI_MODEL, u), 6400)
        # an unknown model is priced as the dearest, never undercounted
        self.assertEqual(ai_spend.cost_micro("claude-new", u), 12800)
        # a stand-in response without usage counts nothing (and doesn't fail)
        self.assertEqual(ai_spend.usage_of(unittest.mock.Mock()), dict.fromkeys(u, 0))
        self.assertEqual(ai_spend.usage_of(object()), dict.fromkeys(u, 0))

    def test_answers_add_up_per_month_helper_and_model(self):
        ai_spend.record(self.conn, "chat", SONNET, {"input_tokens": 1000}, now=WHEN)
        ai_spend.record(self.conn, "chat", SONNET, {"output_tokens": 100}, now=WHEN)
        ai_spend.record(self.conn, "csv", csv_import.AI_MODEL, {"input_tokens": 240}, now=WHEN)
        ai_spend.record(self.conn, "chat", SONNET, {"input_tokens": 5},
                        now=datetime(2026, 11, 1, tzinfo=timezone.utc))
        rows = {r["helper"]: dict(r) for r in self.conn.execute(
            "SELECT * FROM ai_spend WHERE month = '2026-10'")}
        self.assertEqual((rows["chat"]["calls"], rows["chat"]["input_tokens"],
                          rows["chat"]["output_tokens"], rows["chat"]["cost_micro"]),
                         (2, 1000, 100, 3000))
        self.assertEqual(rows["csv"]["cost_micro"], 240)
        self.assertEqual(ai_spend.month_total(self.conn, WHEN), 3240)
        s = ai_spend.summary(self.conn, WHEN)
        self.assertEqual((s["spent"], s["calls"], len(s["rows"])), (3240, 3, 2))

    def test_every_ai_module_notes_its_answer(self):
        # the AI calls each record their token counts once they've answered
        # (the plan PDF has none since AI_PLAN step 15)
        ai_spend.use_db(self.db)
        resp = types.SimpleNamespace(stop_reason="end_turn", usage=_usage(i=100, o=10),
                                     content=[types.SimpleNamespace(type="text",
                                                                    text="- One point")])

        class _Client:
            def __init__(self):
                self.messages = self

            def create(self, **kw):
                return resp
        profile = {f: None for f in advisor.PROFILE_FIELDS}
        meeting.talking_points(_Client(), profile, "No holdings yet", "facts")
        csv_import.ai_mapping(["Symbol"], ["text"], "k", client=_Client())
        txn_import.ai_mapping(["Date"], ["text"], "k", client=_Client())
        screenshot_read.read([(b"x", "image/png")], "k", client=_Client())
        got = {r["helper"]: r["calls"] for r in self.conn.execute(
            "SELECT helper, calls FROM ai_spend")}
        self.assertEqual(got, {"prep": 1, "csv": 1, "txn": 1, "screenshot": 1})
        # without a database set, nothing is written and nothing fails
        ai_spend.use_db(None)
        meeting.talking_points(_Client(), profile, "No holdings yet", "facts")
        self.assertEqual(self.conn.execute("SELECT SUM(calls) AS n FROM ai_spend").fetchone()["n"],
                         4)

    def test_a_failing_count_never_breaks_the_feature(self):
        ai_spend.use_db(os.path.join(self.dir, "missing", "nope.db"))
        ai_spend.note(types.SimpleNamespace(usage=_usage(i=1)), "chat", SONNET)   # no raise

    def test_no_text_reaches_the_log_either(self):
        with open(os.path.join(REPO, "ai_spend.py"), encoding="utf-8") as fh:
            src = fh.read()
        for m in re.finditer(r"print\((.*?)\)\s*$", src, re.M | re.S):
            self.assertNotIn("response", m.group(1))
            self.assertNotIn("content", m.group(1))


# --------------------------------------------------------------------------- #
# the ceiling: levels, what each feature does, the emails
# --------------------------------------------------------------------------- #
class CeilingTests(_DB):

    def test_the_ceiling_setting(self):
        for value, want in (("", 100), ("250", 250), ("12.5", 12.5), ("lots", 100),
                            ("-5", 100), ("0", 0)):
            with _ceiling(value):
                self.assertEqual(settings.ai_ceiling_usd(100), want, value)
        with _ceiling("40"):
            self.assertEqual(ai_spend.ceiling_micro(), 40 * DOLLAR)

    def test_levels_at_49_50_80_95_100(self):
        ceiling = 100 * DOLLAR
        for pct, want in ((0, ai_spend.NORMAL), (49, ai_spend.NORMAL), (50, ai_spend.ALERT),
                          (79.99, ai_spend.ALERT), (80, ai_spend.REDUCED),
                          (94, ai_spend.REDUCED), (95, ai_spend.CLOSING),
                          (99.99, ai_spend.CLOSING), (100, ai_spend.RESTING),
                          (180, ai_spend.RESTING)):
            self.assertEqual(ai_spend.level_of(round(pct * DOLLAR), ceiling), want, pct)
        self.assertEqual(ai_spend.level_of(0, 0), ai_spend.RESTING)   # a ceiling of 0: off
        with _ceiling("100"):
            self.spend(49 * DOLLAR)
            self.assertEqual(ai_spend.level(self.conn, WHEN), ai_spend.NORMAL)
            self.spend(1 * DOLLAR)
            self.assertEqual(ai_spend.level(self.conn, WHEN), ai_spend.ALERT)
            self.spend(30 * DOLLAR)
            self.assertEqual(ai_spend.level(self.conn, WHEN), ai_spend.REDUCED)
            self.spend(15 * DOLLAR)
            self.assertEqual(ai_spend.level(self.conn, WHEN), ai_spend.CLOSING)
            self.spend(5 * DOLLAR)
            self.assertEqual(ai_spend.level(self.conn, WHEN), ai_spend.RESTING)
            # a new month starts afresh
            self.assertEqual(ai_spend.level(self.conn, datetime(2026, 11, 1, tzinfo=timezone.utc)),
                             ai_spend.NORMAL)

    def test_what_each_feature_does_at_each_level(self):
        R, O = "resting", "paused"
        table = {   # level: {kind: why, ...}; chat as a new / an open conversation
            ai_spend.NORMAL: {"chat": (None, None), "screenshot": None, "csv": None,
                              "plan": None, "prep": None, "grader": None, "glossary": None, "draft": None},
            ai_spend.ALERT: {"chat": (None, None), "screenshot": None, "csv": None,
                             "plan": None, "prep": None, "grader": None, "glossary": None, "draft": None},
            ai_spend.REDUCED: {"chat": (None, None), "screenshot": O, "csv": O, "plan": O,
                               "prep": O, "grader": O, "glossary": O, "draft": O},
            ai_spend.CLOSING: {"chat": ("closed", None), "screenshot": O, "csv": O, "plan": O,
                               "prep": O, "grader": O, "glossary": O, "draft": O},
            ai_spend.RESTING: {"chat": (R, R), "screenshot": R, "csv": R, "plan": R,
                               "prep": R, "grader": R, "glossary": R, "draft": R},
        }
        for level, kinds in table.items():
            for kind, want in kinds.items():
                if kind == "chat":
                    self.assertEqual((ai_spend.gate(level, kind),
                                      ai_spend.gate(level, kind, conversation_open=True)),
                                     want, level)
                else:
                    self.assertEqual(ai_spend.gate(level, kind), want, (level, kind))
        self.assertEqual(set(ai_usage.KINDS), set(table[ai_spend.NORMAL]))   # every kind

    def test_the_resting_words_are_calm(self):
        status = {"ok": True, "used": 0, "limit": 100, "left": 100,
                  "resets": date(2026, 11, 1), "unconfirmed": False}
        st = ai_spend.apply(status, ai_spend.RESTING, "chat")
        self.assertFalse(st["ok"])
        self.assertEqual(ai_usage.used_up_text(st, "chat"),
                         "Ask Northwend is resting until November 1. Everything else in "
                         "Northwend works as usual.")
        texts = [ai_usage.used_up_text(ai_spend.apply(status, lvl, k), k)
                 for lvl in (ai_spend.REDUCED, ai_spend.CLOSING, ai_spend.RESTING)
                 for k in ai_usage.KINDS
                 if ai_spend.gate(lvl, k)]
        self.assertIn("Ask Northwend isn't starting new conversations until November 1. "
                      "Everything else in Northwend works as usual.", texts)
        self.assertIn("Reading screenshots is resting until November 1. Everything else in "
                      "Northwend works as usual.", texts)
        for t in texts:
            for word in ("limit", "budget", "cost", "spend", "$", "ceiling", "error"):
                self.assertNotIn(word, t.lower(), t)
        # the person's own allowance still counts at a normal level
        self.assertTrue(ai_spend.apply(status, ai_spend.ALERT, "chat")["ok"])
        self.assertFalse(ai_spend.apply({**status, "ok": False}, ai_spend.NORMAL, "chat")["ok"])

    def test_one_alert_per_threshold_per_month(self):
        sent = []

        def fake_send(to, subject, text, *a, **kw):
            sent.append((to, subject, text))
            return True
        with _ceiling("100"), unittest.mock.patch.object(mailer, "send", fake_send), \
                unittest.mock.patch.dict(os.environ, {"ALERT_EMAIL": "owner@example.com"}):
            self.spend(49 * DOLLAR)
            self.assertIsNone(ai_spend.maybe_alert(self.conn, now=WHEN))   # 49%: nothing
            self.spend(1 * DOLLAR)
            self.assertEqual(ai_spend.maybe_alert(self.conn, now=WHEN), 50)
            self.assertIsNone(ai_spend.maybe_alert(self.conn, now=WHEN))   # once
            self.spend(29 * DOLLAR)
            self.assertIsNone(ai_spend.maybe_alert(self.conn, now=WHEN))   # 79%
            self.spend(1 * DOLLAR)
            self.assertEqual(ai_spend.maybe_alert(self.conn, now=WHEN), 80)
            self.spend(25 * DOLLAR)   # 105%: no third email
            self.assertIsNone(ai_spend.maybe_alert(self.conn, now=WHEN))
            self.assertEqual(len(sent), 2)
            to, subject, text = sent[0]
            self.assertEqual(to, "owner@example.com")
            self.assertIn("50%", subject)
            self.assertIn("$50.00 of the $100.00 ceiling", text)
            self.assertIn("no one's name", text)
            self.assertIn("80%", sent[1][1])
            # next month, again from the start; jumping straight past both sends one email
            nov = datetime(2026, 11, 20, tzinfo=timezone.utc)
            self.spend(90 * DOLLAR, now=nov)
            self.assertEqual(ai_spend.maybe_alert(self.conn, now=nov), 80)
            self.assertIsNone(ai_spend.maybe_alert(self.conn, now=nov))
            self.assertEqual(len(sent), 3)
            self.assertEqual([r["level"] for r in self.conn.execute(
                "SELECT level FROM ai_alerts WHERE month = '2026-11' ORDER BY level")], [50, 80])

    def test_an_email_that_didnt_go_is_tried_again(self):
        with _ceiling("100"), unittest.mock.patch.object(mailer, "send", return_value=False):
            self.spend(60 * DOLLAR)
            self.assertIsNone(ai_spend.maybe_alert(self.conn, now=WHEN))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) AS n FROM ai_alerts")
                         .fetchone()["n"], 0)
        with _ceiling("100"), unittest.mock.patch.object(mailer, "send", return_value=True):
            self.assertEqual(ai_spend.maybe_alert(self.conn, now=WHEN), 50)

    def test_local_runs_send_nothing(self):
        with _ceiling("100"), unittest.mock.patch.object(mailer, "send") as send:
            self.spend(90 * DOLLAR)
            self.assertIsNone(ai_spend.maybe_alert(self.conn, send=False, now=WHEN))
            send.assert_not_called()

    def test_note_records_and_alerts(self):
        ai_spend.use_db(self.db, send=True, copy="Staging")
        resp = types.SimpleNamespace(usage=_usage(o=6_000_000))   # $60 on Sonnet
        with _ceiling("100"), unittest.mock.patch.object(mailer, "send",
                                                         return_value=True) as send:
            ai_spend.note(resp, "chat", SONNET)
        send.assert_called_once()
        self.assertIn("(Staging)", send.call_args[0][1])
        self.assertEqual(ai_spend.month_total(self.conn), 60 * DOLLAR)


# --------------------------------------------------------------------------- #
# in the app
# --------------------------------------------------------------------------- #
class RestingAppTests(unittest.TestCase):
    """Ask Northwend's page through AppTest on a scratch database."""

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_airest_")
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
        ai_spend.use_db(None)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        c = portfolio.connect(self.db)
        try:
            c.execute("DELETE FROM ai_spend")
            c.commit()
        finally:
            c.close()

    def spend(self, usd):
        c = portfolio.connect(self.db)
        try:
            ai_spend.record(c, "chat", SONNET, {"output_tokens": usd * 100_000})
        finally:
            c.close()

    def page(self, **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in dict(user_id=self.uid, username="ann", page="AI Assistant",
                         auto_backfilled=True, income_synced=True, **state).items():
            at.session_state[k] = v
        keep = {k: v for k, v in os.environ.items()
                if k not in ("RENDER", "NORTHWEND_ENV", "HOSTNAME", "MOVED_TO")}
        keep.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                    NORTHWEND_AI_CEILING_USD="100")
        for p in (unittest.mock.patch.dict(os.environ, keep, clear=True),
                  unittest.mock.patch.object(settings, "_on_community_cloud",
                                             return_value=False),
                  unittest.mock.patch.object(yfinance, "Ticker", offline),
                  unittest.mock.patch("socket.socket.connect", offline)):
            p.start()
            self.addCleanup(p.stop)
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        return at

    def test_resting_at_the_ceiling(self):
        self.spend(100)
        at = self.page()
        when = ai_spend.resets_on()
        self.assertIn(f"Ask Northwend is resting until {when:%B} {when.day}. Everything else "
                      "in Northwend works as usual.", [i.value for i in at.info])
        self.assertTrue(at.chat_input[0].proto.disabled)

    def test_new_conversations_close_at_95_but_an_open_one_may_finish(self):
        self.spend(96)
        at = self.page()
        self.assertTrue(any("isn't starting new conversations" in i.value for i in at.info))
        self.assertTrue(at.chat_input[0].proto.disabled)
        at = self.page(chat_display=[{"role": "user", "text": "hi"},
                                     {"role": "assistant", "text": "hello"}],
                       chat_api=[{"role": "user", "content": "hi"},
                                 {"role": "assistant", "content": "hello"}])
        self.assertFalse(any("resting" in i.value or "new conversations" in i.value
                             for i in at.info))
        self.assertFalse(at.chat_input[0].proto.disabled)

    def test_the_admin_sees_the_month_against_the_ceiling(self):
        from streamlit.testing.v1 import AppTest
        self.spend(85)
        script = f"""
import sys, os
sys.path.insert(0, {REPO!r})
os.environ["NORTHWEND_AI_CEILING_USD"] = "100"
import pandas as pd
import streamlit as st
from portfolio import connect
HERE = {REPO!r}
DB = {self.db!r}
STAGING = False
HOSTED = False
LOGIN_ID = {self.uid}
IS_ADVISOR = False
path = os.path.join(HERE, "views", "admin.py")
with open(path, encoding="utf-8") as fh:
    exec(compile(fh.read(), path, "exec"), globals())
c = connect(DB)
_render_ai_spend(ai_spend.summary(c))
c.close()
"""
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_AI_CEILING_USD": "100"}):
            at = AppTest.from_string(script, default_timeout=30).run()
        self.assertEqual([e.message for e in at.exception], [])
        md = " ".join(m.value for m in at.markdown)
        self.assertIn("**$85.00** of the $100.00 monthly ceiling (85%)", md)
        self.assertIn("Past 80%", " ".join(c.value for c in at.caption))
        df = at.dataframe[0].value
        self.assertEqual(list(df["Helper"]), ["chat"])
        self.assertNotIn("user", " ".join(df.columns).lower())

    def test_below_the_ceiling_nothing_shows(self):
        self.spend(60)
        at = self.page()
        self.assertFalse(at.chat_input[0].proto.disabled)
        self.assertFalse(any("resting" in i.value for i in at.info))


if __name__ == "__main__":
    unittest.main()
