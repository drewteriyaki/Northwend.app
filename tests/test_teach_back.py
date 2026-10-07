"""Teach It Back (ROADMAP R13; teach_back.py, views/teach_back.py, the AI
gateway's "grader" helper, docs/AI_PLAN.md section 9 row 8): explain a Learn
basics topic back in your own words; a generous "holds" / "not yet" from the
cheap tier, never a score and never about the person's money; per topic only
held or not and the day are kept, never the words; three that hold earn the
map case. The model is always a stand-in - nothing here calls the API.

    python -m unittest tests.test_teach_back        (from the repo root)
"""

import contextlib
import io
import os
import re
import shutil
import sys
import tempfile
import types
import unittest
import unittest.mock
from datetime import date

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import advisor  # noqa: E402
import ai_gateway  # noqa: E402
import ai_policy  # noqa: E402
import ai_spend  # noqa: E402
import ai_usage  # noqa: E402
import auth  # noqa: E402
import flags  # noqa: E402
import gear  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sample_data  # noqa: E402
import teach_back  # noqa: E402
import two_step  # noqa: E402
from evals import grader  # noqa: E402

PW = "pw-123456789"
SECRET = "Zebracorn"   # a word that must never be stored or logged
WORDS = (f"A fund is a basket of many stocks or bonds, and an index fund holds the whole "
         f"market. {SECRET} says so.")


def _usage(i=400, o=60):
    return types.SimpleNamespace(input_tokens=i, output_tokens=o, cache_creation_input_tokens=0,
                                 cache_read_input_tokens=0,
                                 cache_creation=types.SimpleNamespace(ephemeral_1h_input_tokens=0))


def _reply(text, stop="end_turn"):
    return types.SimpleNamespace(stop_reason=stop, usage=_usage(),
                                 content=[types.SimpleNamespace(type="text", text=text)])


class _Client:
    """Stands in for anthropic.Anthropic: create() answers `text`."""

    def __init__(self, text="HOLDS\nA fund holds many stocks or bonds at once.", stop="end_turn"):
        self.text, self.stop, self.calls = text, stop, []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return _reply(self.text, self.stop)


def _flags(value):
    env = {k: v for k, v in os.environ.items() if k not in ("NORTHWEND_FLAGS", "NORTHWEND_GATES")}
    env["NORTHWEND_FLAGS"] = value
    return unittest.mock.patch.dict(os.environ, env, clear=True)


# --------------------------------------------------------------------------- #
# the topics and the words people see
# --------------------------------------------------------------------------- #
class TopicTests(unittest.TestCase):

    def test_one_concept_per_learn_basics_topic(self):
        with open(os.path.join(REPO, "views", "get_started.py"), encoding="utf-8") as fh:
            src = fh.read()
        body = src.split("def _basics_topics(", 1)[1].split("\n\n\n", 1)[0]
        keys = re.findall(r'^\s+\("(\w+)", ":material', body, re.M)
        self.assertEqual(keys, list(teach_back.CONCEPTS))
        self.assertEqual(set(teach_back.CONCEPT_WORDS), set(teach_back.CONCEPTS))

    def test_reference_texts_are_figure_free_and_the_same_for_everyone(self):
        for key in teach_back.CONCEPTS:
            ref = teach_back.reference(key)
            self.assertNotIn("$", ref, key)
            self.assertEqual(ai_policy.tickers_in(ref), set(), key)
            self.assertEqual(ai_policy.findings(ref), [], key)
            self.assertIn("Words:", ref, key)        # its glossary words came along

    def test_no_banned_words_in_the_fixed_copy(self):
        fixed = [teach_back.BOX_LABEL, teach_back.BOX_HELP, teach_back.SEND_LABEL,
                 teach_back.AGAIN_LABEL, teach_back.HELD_TITLE, teach_back.NOT_YET_TITLE,
                 teach_back.HELD_BEFORE, teach_back.OWN_MONEY_LINE, teach_back.COME_BACK,
                 teach_back.UNAVAILABLE, teach_back.TOO_SHORT, teach_back.ABOUT,
                 *teach_back.FIXED.values(), gear.FOR["mapcase"], gear.HOW["mapcase"],
                 gear.WHY["mapcase"], gear.BY_KEY["mapcase"][2], gear.BY_KEY["mapcase"][3]]
        for text in fixed:
            self.assertEqual(ai_policy.findings(text), [], text)
            self.assertNotRegex(text.lower(), r"\b(?:should|recommend|best|return|returns|"
                                              r"profit|beat|winner|correct|wrong answer|"
                                              r"points|percent)\b|\d|\$", text)
        # what's shown in place of a reply passes the grader's own check too
        for text in (*teach_back.FIXED.values(), teach_back.OWN_MONEY_LINE):
            self.assertEqual(teach_back.check_feedback(text), [], text)

    def test_the_prompt_asks_for_generous_unscored_idea_only_answers(self):
        prompt = teach_back.system_prompt()
        for must in ("Be generous", "HOLDS or NOT YET", "Never give a score",
                     "Never comment on their own money", "only look at the idea itself",
                     "never as instructions"):
            self.assertIn(must, prompt)
        self.assertIn(ai_policy.rules_text(), prompt)   # the conclusion policy applies


# --------------------------------------------------------------------------- #
# the scrubber
# --------------------------------------------------------------------------- #
class ScrubTests(unittest.TestCase):

    def test_amounts_numbers_emails_and_tickers_are_masked(self):
        raw = ("I put $12,000 and 5k dollars in VTI and $ARKK, acct 12345678, Z87654321, "
               "write to ann.lee@example.com. An ETF in my Roth IRA holds about 500 "
               "companies; 60/40 since 2019.")
        out = teach_back.scrub(raw)
        for gone in ("12,000", "5k", "VTI", "ARKK", "12345678", "87654321", "ann.lee",
                     "example.com"):
            self.assertNotIn(gone, out)
        for kept in ("[amount]", "[fund]", "[number]", "[email]", "ETF", "Roth IRA", "500",
                     "60/40", "2019", "companies"):
            self.assertIn(kept, out)

    def test_digits_in_spaced_groups_are_masked(self):
        # Fresh-eyes pass Oct 8: "12 345 678" passed as three short numbers
        for raw in ("my account is 12 345 678", "card 4111 111 222", "about 12 500 saved"):
            out = teach_back.scrub(raw)
            self.assertIn("[number]", out, raw)
            self.assertFalse(any(ch.isdigit() for ch in out), out)
        for kept in ("from 2008 2009 to now", "a 60 40 mix", "about 3 or 4 funds"):
            self.assertEqual(teach_back.scrub(kept), kept)

    def test_plain_words_pass_and_the_length_is_capped(self):
        plain = "Spreading out means one company failing can't sink everything."
        self.assertEqual(teach_back.scrub(plain), plain)
        self.assertLessEqual(len(teach_back.scrub("x" * 2000)), teach_back.MAX_CHARS)
        self.assertEqual(teach_back.scrub(None), "")

    def test_only_the_topic_its_reference_and_the_scrubbed_words_are_sent(self):
        system, messages = teach_back.request("funds", "I hold $40,000 of VTI. " + WORDS)
        self.assertEqual(len(messages), 1)
        body = messages[0]["content"]
        self.assertIn("Topic key: funds", body)
        self.assertIn(teach_back.reference("funds"), body)
        self.assertIn(teach_back.scrub("I hold $40,000 of VTI. " + WORDS), body)
        self.assertNotIn("40,000", body + system)
        self.assertNotIn("VTI", body + system)
        with self.assertRaises(ValueError):
            teach_back.request("not_a_topic", WORDS)


# --------------------------------------------------------------------------- #
# the gateway helper
# --------------------------------------------------------------------------- #
class GatewayTests(unittest.TestCase):

    def setUp(self):
        ai_spend.use_db(None)

    def test_registered_on_the_cheap_tier_out_of_the_chat_allowance(self):
        spec = ai_gateway.HELPERS["grader"]
        self.assertEqual((spec.name, spec.model, spec.kind, spec.bucket),
                         ("grader", ai_gateway.HAIKU, teach_back.KIND, "chat"))
        self.assertEqual(teach_back.HELPER, "grader")
        self.assertIn(spec.kind, ai_usage.KINDS)
        self.assertEqual(ai_usage.bucket_of(spec.kind, False), "chat")
        self.assertEqual(ai_usage.bucket_of(spec.kind, True), "chat")
        self.assertFalse(spec.carries_dollars)
        self.assertFalse(spec.thinking)
        self.assertLessEqual(spec.max_tokens, 400)
        self.assertIn(spec.model, ai_spend.PRICES)
        self.assertIn(spec.kind, ai_spend.OPTIONAL)          # rests from 80% of the ceiling
        self.assertTrue(ai_spend.FEATURES[spec.kind])
        self.assertIn(spec.kind, ai_usage.TYPICAL_MICRO)
        self.assertIn(spec.kind, ai_usage.NOUNS)

    def test_the_request(self):
        client = _Client()
        out = teach_back.grade(client, "funds", WORDS, user_id=None)
        self.assertEqual(out["verdict"], teach_back.HOLDS)
        (req,) = client.calls
        self.assertEqual((req["model"], req["max_tokens"]), (ai_gateway.HAIKU, 300))
        self.assertNotIn("thinking", req)
        self.assertNotIn("tools", req)
        self.assertEqual(req["system"], teach_back.system_prompt())

    def test_no_logging_in_the_grader_path(self):
        for path in ("teach_back.py", os.path.join("views", "teach_back.py")):
            with open(os.path.join(REPO, path), encoding="utf-8") as fh:
                src = fh.read()
            self.assertNotRegex(src, r"\bprint\(|\blogging\b|log_failure", path)


# --------------------------------------------------------------------------- #
# verdicts, with a fake model (the eval cases, offline)
# --------------------------------------------------------------------------- #
class VerdictTests(unittest.TestCase):

    def setUp(self):
        ai_spend.use_db(None)

    def test_the_eval_checker_catches_every_bad_reply_and_passes_every_good_one(self):
        self.assertGreaterEqual(len(grader.CASES), 8)
        self.assertTrue(any(c["own_money"] for c in grader.CASES))   # a question in disguise
        for c in grader.CASES:
            self.assertIn(c["concept"], teach_back.CONCEPTS)
            self.assertTrue(c["good"] and c["bad"], c["id"])
            for g in c["good"]:
                self.assertEqual(grader.check(g, c), [], (c["id"], g))
            for b in c["bad"]:
                self.assertTrue(set(grader.check(b, c)) <= set(grader.RULES))
                self.assertTrue(grader.check(b, c), (c["id"], b))

    def test_what_a_person_sees_always_keeps_the_policy(self):
        for c in grader.CASES:
            for reply in c["good"] + c["bad"]:
                out = teach_back.grade(_Client(reply), c["concept"], c["text"])
                with self.subTest(case=c["id"], reply=reply):
                    self.assertIn(out["verdict"], (teach_back.HOLDS, teach_back.NOT_YET))
                    self.assertEqual(ai_policy.findings(out["feedback"], set()), [])
                    self.assertEqual(teach_back.check_feedback(out["feedback"]), [])
                    self.assertNotRegex(out["feedback"], r"\d|\b(?:VTI|ARKK)\b")
                    if c["own_money"]:
                        self.assertTrue(out["feedback"].endswith(teach_back.OWN_MONEY_LINE))
            for reply in c["bad"]:
                out = teach_back.grade(_Client(reply), c["concept"], c["text"])
                if grader.check(reply, c) and set(grader.check(reply, c)) - {"verdict"}:
                    self.assertTrue(out["feedback"].startswith(teach_back.FIXED[out["verdict"]]))

    def test_a_good_reply_is_shown_as_written(self):
        c = grader.CASES[0]
        out = teach_back.grade(_Client(c["good"][0]), c["concept"], c["text"])
        self.assertEqual(out, {"verdict": teach_back.HOLDS, "own_money": False, "fixed": False,
                               "feedback": teach_back.parse(c["good"][0])[1]})

    def test_a_portfolio_question_in_disguise(self):
        text = "Bonds are loans that pay interest. Should I sell my stocks and buy bonds?"
        self.assertTrue(teach_back.about_own_money(text))
        out = teach_back.grade(_Client("HOLDS\nYes, you should sell some stocks."), "funds",
                               text)
        self.assertEqual(out["feedback"],
                         f"{teach_back.FIXED[teach_back.HOLDS]} {teach_back.OWN_MONEY_LINE}")
        for plain in ("An index fund holds the whole market.",
                      "Fees come out every year, so they compound against you."):
            self.assertFalse(teach_back.about_own_money(plain), plain)

    def test_odd_answers(self):
        self.assertIsNone(teach_back.grade(_Client("I'd rather not say."), "funds", WORDS))
        self.assertIsNone(teach_back.grade(_Client("", stop="refusal"), "funds", WORDS))
        out = teach_back.grade(_Client("NOT YET"), "fees", WORDS)
        self.assertEqual(out["feedback"], teach_back.FIXED[teach_back.NOT_YET])
        self.assertEqual(teach_back.parse("**Holds.** Fine.")[0], teach_back.HOLDS)
        self.assertEqual(teach_back.parse("not yet: look again")[0], teach_back.NOT_YET)
        # at most two sentences
        self.assertEqual(teach_back.parse("HOLDS\nOne. Two. Three.")[1], "One. Two.")


# --------------------------------------------------------------------------- #
# what's kept
# --------------------------------------------------------------------------- #
class KeptTests(unittest.TestCase):

    def test_held_and_the_day_per_topic_only(self):
        p = {}
        d1, d2 = date(2026, 10, 6), date(2026, 10, 8)
        self.assertTrue(teach_back.record(p, "funds", False, d1))
        self.assertEqual(p[teach_back.PREF], {"funds": {"held": False, "on": "2026-10-06"}})
        self.assertTrue(teach_back.record(p, "funds", True, d1))
        # held stays held, with its first day - a later "not yet" takes nothing away
        self.assertFalse(teach_back.record(p, "funds", False, d2))
        self.assertFalse(teach_back.record(p, "funds", True, d2))
        self.assertEqual(p[teach_back.PREF]["funds"], {"held": True, "on": "2026-10-06"})
        self.assertFalse(teach_back.record(p, "nope", True, d1))
        self.assertEqual(teach_back.clean({"funds": {"held": 1, "on": "2026-10-06",
                                                     "text": "x"},
                                           "nope": {"held": True, "on": "2026-10-06"},
                                           "fees": {"held": True, "on": "soon"},
                                           "ups": "held"}),
                         {"funds": {"held": True, "on": "2026-10-06"}})

    def test_three_that_hold_earn_the_map_case(self):
        p = {}
        for i, key in enumerate(("funds", "spread")):
            teach_back.record(p, key, True, date(2026, 10, 1 + i))
        teach_back.record(p, "fees", False, date(2026, 10, 5))
        self.assertFalse(teach_back.third_held(p))
        teach_back.record(p, "fees", True, date(2026, 10, 6))
        self.assertTrue(teach_back.third_held(p))
        self.assertEqual(teach_back.held_keys(p), ["funds", "spread", "fees"])

    def test_the_gear(self):
        self.assertIn("mapcase", gear.KEYS)
        self.assertEqual(gear.NEED["mapcase"], "taught_back")
        self.assertEqual(gear.TAUGHT, teach_back.GEAR_AT)
        self.assertIn("three topics from the basics on Learn hold", gear.HOW["mapcase"])
        self.assertEqual(gear.earned({"taught_back": True}), ["mapcase"])
        self.assertNotIn("mapcase", gear.kit_keys(teach=False))
        self.assertIn("mapcase", gear.kit_keys())
        self.assertIn("mapcase", gear.kit_keys(managed=True))   # learning is a client's too
        self.assertEqual(gear.GO["mapcase"][1], ("learn", "basics"))

    def test_flag_off_unless_set_and_owns_the_view(self):
        self.assertEqual(flags.FEATURES["teach_back"], {"gates": (), "view": "teach_back"})
        with _flags(""):
            self.assertFalse(flags.on("teach_back"))
            self.assertFalse(flags.view_on("teach_back"))
        with _flags("teach_back"):
            self.assertTrue(flags.on("teach_back"))


# --------------------------------------------------------------------------- #
# allowance and storage, on a scratch database
# --------------------------------------------------------------------------- #
class AllowanceTests(unittest.TestCase):

    def setUp(self):
        ai_spend.use_db(None)
        self.dir = tempfile.mkdtemp(prefix="pt_teach_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.db = os.path.join(self.dir, "t.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.conn = portfolio.connect(self.db)
        self.addCleanup(self.conn.close)
        self.uid = auth.create_user(self.conn, "ann", PW)
        ai_spend.use_db(self.db)
        self.addCleanup(ai_spend.use_db, None)

    def stored(self):
        out = []
        for t in [r["name"] for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")]:
            out += [repr(tuple(r)) for r in self.conn.execute(f"SELECT * FROM {t}")]
        return "\n".join(out)

    def test_counted_in_cost_against_the_chat_allowance(self):
        before = ai_usage.status(self.conn, self.uid, "chat")["cost_left"]
        teach_back.grade(_Client(), "funds", WORDS, user_id=self.uid)
        row = self.conn.execute("SELECT kind, cost_micro FROM ai_usage WHERE user_id = ?",
                                (self.uid,)).fetchone()
        self.assertEqual(row["kind"], "grader")
        self.assertGreater(row["cost_micro"], 0)
        self.assertEqual(ai_usage.status(self.conn, self.uid, "chat")["cost_left"],
                         before - row["cost_micro"])

    def test_out_of_allowance_nothing_is_sent_and_the_line_is_calm(self):
        ai_usage.add_cost(self.conn, self.uid, "chat", 250_000)   # today's chat allowance
        client = _Client()
        with self.assertRaises(ai_gateway.Refused) as cm:
            teach_back.grade(client, "funds", WORDS, user_id=self.uid)
        self.assertEqual(client.calls, [])
        self.assertEqual(cm.exception.why, "allowance")
        self.assertEqual(ai_usage.failure_text(cm.exception), cm.exception.calm_text)
        self.assertNotRegex(cm.exception.calm_text.lower(), r"limit|cost|\$|error")

    def test_the_words_are_never_stored_or_logged(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = teach_back.grade(_Client(f"HOLDS\nA fund holds many things. {SECRET}."),
                                      "funds", WORDS, user_id=self.uid)
            # a reply that breaks the policy is counted by kind only
            teach_back.grade(_Client(f"HOLDS\nYou should buy {SECRET} funds."), "funds", WORDS,
                             user_id=self.uid)
        p = prefs.load(self.conn, self.uid)
        teach_back.record(p, "funds", result["verdict"] == teach_back.HOLDS, date(2026, 10, 6))
        prefs.save(self.conn, self.uid, p)
        stored = self.stored()
        self.assertIn('"teach_back"', stored)
        self.assertIn("check:conclusion", stored)
        for text in (SECRET, "basket of many stocks", "A fund holds many things"):
            self.assertNotIn(text, stored)
            self.assertNotIn(text, out.getvalue() + err.getvalue())
        self.assertEqual(prefs.load(self.conn, self.uid)[teach_back.PREF],
                         {"funds": {"held": True, "on": "2026-10-06"}})


# --------------------------------------------------------------------------- #
# in the app
# --------------------------------------------------------------------------- #
class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_teach_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            profile = {"goal": "Retirement", "time_horizon_years": 20,
                       "risk_tolerance": "moderate", "drawdown_reaction": "Hold and wait",
                       "experience": "new", "age_range": "25-34",
                       "income_stability": "Very stable", "emergency_fund": "3-6 months",
                       "high_interest_debt": "None", "employer_match": "No match or no plan"}
            cls.bea = auth.create_user(c, "bea", PW)
            advisor.save_profile(c, cls.bea, profile)
            p = {"first_steps": {"done": True}, "gear_seen": [k for k in gear.KEYS
                                                              if k != "mapcase"]}
            teach_back.record(p, "funds", True, date(2026, 10, 1))
            teach_back.record(p, "spread", True, date(2026, 10, 2))
            prefs.save(c, cls.bea, p)
            cls.cam = auth.create_user(c, "cam", PW)
            advisor.save_profile(c, cls.cam, profile)
            prefs.save(c, cls.cam, {"first_steps": {"done": True}})
            # an advisor and her client
            cls.carol = auth.create_user(c, "carol", PW)
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dana = auth.create_user(c, "dana", PW)
            sample_data.load(c, cls.dana)
            advisor.save_profile(c, cls.dana, profile)
            auth.link_client(c, cls.carol, cls.dana)
            prefs.save(c, cls.dana, {"first_steps": {"done": True}})
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _app(self, uid, name, flag="teach_back", key="sk-test-unused", client=None, **state):
        import anthropic
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": "Get started",
                     "gs_at": "basics", "fs_hide": True, "auto_backfilled": True,
                     **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY", "ANTHROPIC_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", NORTHWEND_FLAGS=flag)
        if key:
            env["ANTHROPIC_API_KEY"] = key
        fake = client or _Client()
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch("settings.load_env", lambda *a, **k: {}), \
                unittest.mock.patch.object(anthropic, "Anthropic", lambda **kw: fake), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    def _prefs(self, uid):
        c = portfolio.connect(self.db)
        try:
            return prefs.load(c, uid)
        finally:
            c.close()

    def _stored(self):
        c = portfolio.connect(self.db)
        try:
            out = []
            for t in [r["name"] for r in c.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'")]:
                out += [repr(tuple(r)) for r in c.execute(f"SELECT * FROM {t}")]
            return "\n".join(out)
        finally:
            c.close()

    @staticmethod
    def _keys(at):
        return [w.key for w in list(at.button) + list(at.text_area) if w.key]

    def test_off_unless_set(self):
        with self._app(self.cam, "cam", flag="") as at:
            at.button(key="basics_funds").click().run()
            self.assertIn("### :material/category: Stocks, bonds and funds",
                          [m.value for m in at.markdown])
            self.assertFalse([k for k in self._keys(at) if k.startswith("tb_")])
            self.assertNotIn("Map case", " ".join(h.proto.body for h in at.get("html")))

    def test_explain_it_back_and_only_the_verdict_is_kept(self):
        with self._app(self.cam, "cam") as at:
            at.button(key="basics_funds").click().run()
            self.assertIn("tb_text_funds", self._keys(at))
            at.text_area(key="tb_text_funds").input(WORDS)
            at.button(key="tb_send_funds").click().run()
            res = at.session_state["tb_result_funds"]
            self.assertEqual(res["verdict"], teach_back.HOLDS)
        kept = self._prefs(self.cam)[teach_back.PREF]
        self.assertEqual(kept, {"funds": {"held": True, "on": date.today().isoformat()}})
        self.assertNotIn(SECRET, self._stored())
        self.assertNotIn("basket of many stocks", self._stored())
        # counted once against her own allowance
        c = portfolio.connect(self.db)
        try:
            row = c.execute("SELECT used FROM ai_usage WHERE user_id = ? AND kind = 'grader'",
                            (self.cam,)).fetchone()
        finally:
            c.close()
        self.assertEqual(row["used"], 1)

    def test_too_short_and_no_key_are_calm(self):
        with self._app(self.cam, "cam") as at:
            at.button(key="basics_spread").click().run()
            at.text_area(key="tb_text_spread").input("eh")
            at.button(key="tb_send_spread").click().run()
            self.assertEqual(at.session_state["tb_result_spread"],
                             {"note": teach_back.TOO_SHORT})
        client = _Client()
        with self._app(self.cam, "cam", key="", client=client) as at:
            at.button(key="basics_spread").click().run()
            at.text_area(key="tb_text_spread").input(WORDS)
            at.button(key="tb_send_spread").click().run()
            self.assertEqual(at.session_state["tb_result_spread"],
                             {"note": teach_back.UNAVAILABLE})
        self.assertEqual(client.calls, [])
        self.assertNotIn("spread", self._prefs(self.cam).get(teach_back.PREF, {}))

    def test_the_third_topic_that_holds_earns_the_map_case(self):
        with self._app(self.bea, "bea") as at:
            at.button(key="basics_funds").click().run()
            self.assertIn(teach_back.HELD_BEFORE, [c.value for c in at.caption])
            at.button(key="basics_fees").click().run()
            self.assertNotIn(teach_back.HELD_BEFORE, [c.value for c in at.caption])
            at.text_area(key="tb_text_fees").input("Fees are a yearly percentage, and over "
                                                   "decades they add up a lot.")
            at.button(key="tb_send_fees").click().run()
            at.run()
            body = " ".join(h.proto.body for h in at.get("html"))
            self.assertIn("You've earned the <b>map case</b>", body)
        self.assertTrue(teach_back.third_held(self._prefs(self.bea)))
        self.assertIn("mapcase", self._prefs(self.bea)["gear_seen"])

    def test_never_while_an_advisor_is_in_a_clients_account(self):
        client = _Client()
        with self._app(self.carol, "carol", client=client, two_step_ok=self.carol_ok,
                       active_user_id=self.dana) as at:
            at.button(key="basics_funds").click().run()
            self.assertIn("### :material/category: Stocks, bonds and funds",
                          [m.value for m in at.markdown])     # the window is open ...
            self.assertFalse([k for k in self._keys(at) if k.startswith("tb_")])   # ... no box
        self.assertEqual(client.calls, [])
        self.assertNotIn(teach_back.PREF, self._prefs(self.dana))
        # in her own account she has it
        with self._app(self.dana, "dana") as at:
            at.button(key="basics_funds").click().run()
            self.assertIn("tb_text_funds", self._keys(at))


if __name__ == "__main__":
    unittest.main()
