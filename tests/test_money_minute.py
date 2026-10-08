"""Today's minute (money_minute.py, views/money_minute.py, flag money_minute).

The library: at least 30 quick questions and myths, drills' situations reused,
Learn's basics for Teach It Back; every fixed line through the conclusion
policy and a banned-word list; no tickers; official links only. The pick: the
same card for the same person and day, each kind in the person's own order
with no repeats until it has gone round, the teach-back day once a week and
only while Teach It Back is on. The count: days of learning only grow - a
missed day takes nothing away. What's kept: days and card ids only. In the
app: off unless its flag is set; at the top of Home's This month column and
on Home before anything is invested; a tap keeps the day; Teach It Back's day
goes through its own allowance path (an offline fake client); never while an
advisor is in a client's account, and nothing written there.

    python -m unittest tests.test_money_minute        (from the repo root)
"""

import contextlib
import os
import re
import shutil
import sys
import tempfile
import types
import unittest
import unittest.mock
from datetime import date, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import advisor  # noqa: E402
import ai_policy  # noqa: E402
import auth  # noqa: E402
import drills  # noqa: E402
import flags  # noqa: E402
import gear  # noqa: E402
import manual_entry  # noqa: E402
import money_minute as mm  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sample_data  # noqa: E402
import teach_back  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
BANNED = (r"\bshould\b", r"\bbest\b", r"\brecommend", r"\bbuy\b", r"\bsell\b", r"\bsold\b",
          r"\bbought\b", r"\bwill\b", r"\bexpect", r"\bpredict", r"\bforecast", r"\blikely\b",
          r"\burgent", r"\bcorrect\b", r"\bwrong\b", r"\bbetter\b", r"\bworst\b",
          r"\bmistake", r"\bsmart\b", r"\bguarantee", r"\bmust\b", r"\bstreak",
          r"\bdon't miss\b", r"\bact now\b", r"\bbroken\b", r"\blose your\b")
PROFILE = {"goal": "Build long-term wealth", "time_horizon_years": 15,
           "risk_tolerance": "moderate", "drawdown_reaction": "Hold",
           "experience": "new", "age_range": "25-34", "income_stability": "Very stable",
           "emergency_fund": "3-6 months"}
D = date(2026, 10, 7)


def _code_words(path):
    with open(path, encoding="utf-8") as fh:
        return "\n".join(line for line in fh.read().splitlines()
                         if not line.lstrip().startswith("#"))


class LibraryTests(unittest.TestCase):

    def test_size_and_ids(self):
        self.assertGreaterEqual(len(mm.QUIZZES) + len(mm.MYTHS), 30)
        self.assertGreaterEqual(len(mm.QUIZZES), 15)
        self.assertGreaterEqual(len(mm.MYTHS), 15)
        ids = [q[0] for q in mm.QUIZZES] + [m[0] for m in mm.MYTHS]
        self.assertEqual(len(ids), len(set(ids)))
        for i in ids:
            self.assertRegex(i, r"^[qm]_[a-z0-9_]+$")
        # the drills' situations and Learn's basics, reused - not copied
        self.assertEqual(mm.DRILL_IDS, tuple(f"d_{k}" for k in drills.KEYS))
        self.assertEqual(mm.TEACH_IDS, tuple(f"t_{k}" for k in teach_back.CONCEPTS))
        for i in mm.ALL_IDS:
            self.assertIn(mm.kind_of(i), mm.KINDS)
        self.assertIsNone(mm.kind_of("q_nothing"))

    def test_each_question_has_one_answer_among_its_choices(self):
        for _id, question, choices, answer, why, _src, link in mm.QUIZZES:
            keys = [c for c, _ in choices]
            self.assertTrue(2 <= len(choices) <= 3, _id)
            self.assertEqual(len(set(keys)), len(keys), _id)
            self.assertIn(answer, keys, _id)
            self.assertTrue(question and why.endswith("."), _id)
            self.assertIn(link, (None, *mm.LINK_LINES), _id)
        for _id, statement, is_myth, why, _src, link in mm.MYTHS:
            self.assertIsInstance(is_myth, bool)
            self.assertTrue(statement.endswith(".") and why.endswith("."), _id)
            self.assertIn(link, (None, *mm.LINK_LINES), _id)
        # myths and facts both
        self.assertTrue(any(m[2] for m in mm.MYTHS) and not all(m[2] for m in mm.MYTHS))

    def test_official_sources_only(self):
        keys = {q[5] for q in mm.QUIZZES} | {m[4] for m in mm.MYTHS}
        for key in keys - {None}:
            src = mm.source(key)
            self.assertIsNotNone(src, key)
            host = re.sub(r"^https://([^/]+)/.*$", r"\1", src[1])
            self.assertTrue(src[1].startswith("https://"), key)
            self.assertIn(host, mm.OFFICIAL_SITES, key)

    def test_every_line_keeps_the_conclusion_policy(self):
        for line in mm.templates():
            with self.subTest(line=line[:50]):
                self.assertEqual(ai_policy.findings(line, allowed_tickers=set()), [])

    def test_no_banned_words_tickers_or_trades(self):
        for line in mm.templates():
            for pat in BANNED:
                self.assertNotRegex(line.lower(), pat, line)
            self.assertEqual(ai_policy.tickers_in(line), set(), line)
            caps = set(re.findall(r"\b[A-Z]{2,5}\b", line)) - ai_policy.NOT_TICKERS
            self.assertEqual(caps, set(), line)
        view = _code_words(os.path.join(REPO, "views", "money_minute.py")).lower()
        for pat in BANNED:
            self.assertNotRegex(view, pat, ("views/money_minute.py", pat))

    def test_the_days_count_reads_gently(self):
        self.assertEqual(mm.days_text(1), "1 day of learning")
        self.assertEqual(mm.days_text(12), "12 days of learning")
        self.assertIn("never goes down", mm.WEEK_LINE)


class PickTests(unittest.TestCase):

    def test_the_same_person_and_day_get_the_same_card(self):
        for login in (1, 7, 42):
            for i in range(30):
                d = D + timedelta(days=i)
                self.assertEqual(mm.pick(login, d, {}), mm.pick(login, d, {}))
        # and different people don't all get the same days
        days = [D + timedelta(days=i) for i in range(14)]
        self.assertNotEqual([mm.pick(1, d, {}) for d in days], [mm.pick(2, d, {}) for d in days])

    def test_first_days_never_open_on_a_hard_time(self):
        # fewer than GENTLE_DAYS answered: "what would you do?" is a good time
        for login in range(1, 40):
            for i in range(60):
                item = mm.pick(login, D + timedelta(days=i), {}, False)
                if mm.kind_of(item) == mm.DRILL:
                    self.assertEqual(drills.side_of(mm.drill_key(item)), drills.GOOD, item)
        # after that, the hard times come in too
        seen = {mm.pick(login, D + timedelta(days=i), self.SEASONED, False)
                for login in (1, 2, 3) for i in range(60)}
        self.assertTrue({i for i in seen if i.startswith("d_")
                         and drills.side_of(mm.drill_key(i)) == drills.HARD})
        # answering today never changes today's card
        p = {mm.PREF: {"days": [(D - timedelta(days=n)).isoformat()
                                for n in range(1, mm.GENTLE_DAYS)], "seen": []}}
        for login in range(1, 30):
            item = mm.pick(login, D, p, False)
            q = {mm.PREF: {"days": p[mm.PREF]["days"] + [D.isoformat()], "seen": [item]}}
            self.assertEqual(mm.pick(login, D, q, False), item)

    # someone with many days of minutes behind them (the whole library in turn)
    SEASONED = {mm.PREF: {"days": [(D - timedelta(days=n)).isoformat()
                                   for n in range(1, 30)], "seen": []}}

    def test_no_repeats_until_a_kind_goes_round(self):
        for login in (3, 11, 250):
            for teach in (False, True):
                seen = {k: [] for k in (mm.QUIZ, mm.MYTH, mm.DRILL)}
                for i in range(400):
                    item = mm.pick(login, D + timedelta(days=i), self.SEASONED, teach)
                    kind = mm.kind_of(item)
                    if kind == mm.TEACH:
                        continue
                    seen[kind].append(item)
                for kind, items in seen.items():
                    n = len(mm.LIBRARY[kind])
                    if not teach:
                        # each round is the whole list once, in the person's order
                        for start in range(0, len(items) - n + 1, n):
                            self.assertEqual(sorted(items[start:start + n]),
                                             sorted(mm.LIBRARY[kind]), (login, kind))
                    else:
                        # a teach-back day skips a turn now and then, never repeats one
                        w = n // 2
                        for start in range(len(items) - w + 1):
                            window = items[start:start + w]
                            self.assertEqual(len(window), len(set(window)), (login, kind))

    def test_all_three_kinds_take_turns(self):
        kinds = {mm.kind_of(mm.pick(5, D + timedelta(days=i), {}, False)) for i in range(5)}
        self.assertEqual(kinds, {mm.QUIZ, mm.MYTH, mm.DRILL})

    def test_teach_back_once_a_week_and_only_while_on(self):
        for login in (1, 2, 3, 4):
            for week in range(6):
                monday = D - timedelta(days=D.weekday()) + timedelta(weeks=week)
                week_kinds = [mm.kind_for(login, monday + timedelta(days=i)) for i in range(7)]
                self.assertEqual(week_kinds.count(mm.TEACH), 1)
                self.assertEqual(week_kinds.index(mm.TEACH), mm.teach_weekday(login))
                off = [mm.kind_for(login, monday + timedelta(days=i), teach=False)
                       for i in range(7)]
                self.assertNotIn(mm.TEACH, off)

    def test_the_teach_topic_stays_put_on_its_day(self):
        p = {}
        self.assertEqual(mm.teach_topic(p, D), "funds")
        teach_back.record(p, "funds", True, D)    # held today: still today's topic
        self.assertEqual(mm.teach_topic(p, D), "funds")
        self.assertEqual(mm.teach_topic(p, D + timedelta(days=7)), "spread")
        all_held = {}
        for k in teach_back.CONCEPTS:
            teach_back.record(all_held, k, True, D - timedelta(days=30))
        topics = {mm.teach_topic(all_held, D + timedelta(weeks=w)) for w in range(6)}
        self.assertEqual(topics, set(teach_back.CONCEPTS))

    def test_tomorrow_says_the_kind(self):
        line = mm.tomorrow_line(9, D)
        self.assertEqual(line, mm.TOMORROW[mm.kind_for(9, D + timedelta(days=1))])


class KeptTests(unittest.TestCase):

    def test_a_missed_day_never_resets_the_count(self):
        p = {}
        mm.record(p, "q_fee_math", D)
        mm.record(p, "m_drops", D + timedelta(days=1))
        self.assertEqual(mm.count(p), 2)
        # two days missed, then one more
        mm.record(p, "d_drop", D + timedelta(days=4))
        self.assertEqual(mm.count(p), 3)
        # the same day again adds nothing
        mm.record(p, "q_bond", D + timedelta(days=4))
        self.assertEqual(mm.count(p), 3)
        marks = dict(mm.week_marks(p, D + timedelta(days=4)))
        monday = D - timedelta(days=D.weekday())     # Oct 5
        self.assertEqual(marks[monday], "open")       # quiet, not a loss
        self.assertEqual(marks[D], "done")
        self.assertEqual(marks[D + timedelta(days=4)], "done")
        self.assertEqual(len(marks), 7)
        later = dict(mm.week_marks({}, D))
        self.assertEqual(later[D], "today")
        self.assertEqual(later[D + timedelta(days=1)], "later")

    def test_only_days_and_card_ids_are_kept(self):
        p = {"other": 1}
        self.assertTrue(mm.record(p, "q_fee_math", D))
        self.assertFalse(mm.record(p, "q_fee_math", D))
        self.assertFalse(mm.record(p, "made up", D))
        self.assertEqual(p[mm.PREF], {"days": ["2026-10-07"], "seen": ["q_fee_math"]})
        self.assertEqual(p["other"], 1)
        junk = {mm.PREF: {"days": ["2026-10-07", "yesterday", 5, "2026-13-01"],
                          "seen": ["q_fee_math", "my words", None], "choice": "b",
                          "text": "I would sell"}}
        self.assertEqual(mm.state(junk), {"days": ["2026-10-07"], "seen": ["q_fee_math"]})
        self.assertEqual(mm.state({mm.PREF: "nonsense"}), {"days": [], "seen": []})


class NeverSharedTests(unittest.TestCase):

    def test_the_flag_is_off_unless_set_and_owns_the_view(self):
        self.assertEqual(flags.FEATURES["money_minute"], {"gates": (), "view": "money_minute"})
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": ""}), \
                unittest.mock.patch.object(flags, "_secret", lambda name: None):
            self.assertFalse(flags.on("money_minute"))
            self.assertFalse(flags.view_on("money_minute"))
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": "money_minute"}):
            self.assertTrue(flags.on("money_minute"))

    def test_never_in_the_ai_an_advisors_files_or_an_email(self):
        for name in ("advisor.py", "context_card.py", "ai_gateway.py", "ai_tools.py",
                     "ai_library.py", "meeting.py", "reports.py", "overview.py",
                     "advising.py", "export.py", "checkin_email.py", "weekly_email.py",
                     "trail_conditions.py", "mailer.py",
                     os.path.join("views", "assistant.py"), os.path.join("views", "clients.py")):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                self.assertNotIn("money_minute", fh.read(), name)
        view = _code_words(os.path.join(REPO, "views", "money_minute.py"))
        for pat in (r"\bai_gateway\b", r"\badvisor\.\w", r"\bcoach_prompt\b", r"\b_ai_",
                    r"\bmailer\b", r"\bsend_"):
            self.assertNotRegex(view, pat)


# --------------------------------------------------------------------------- #
# in the app
# --------------------------------------------------------------------------- #
def _usage(i=400, o=60):
    return types.SimpleNamespace(input_tokens=i, output_tokens=o, cache_creation_input_tokens=0,
                                 cache_read_input_tokens=0,
                                 cache_creation=types.SimpleNamespace(ephemeral_1h_input_tokens=0))


class _Client:
    """Stands in for anthropic.Anthropic: the grader says it holds."""

    def __init__(self):
        self.calls = []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return types.SimpleNamespace(
            stop_reason="end_turn", usage=_usage(),
            content=[types.SimpleNamespace(type="text",
                                           text="HOLDS\nA fund holds many stocks or bonds.")])


class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_minute_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        cls.today = date.today()
        seen_all = {"first_steps": {"done": True}, "gear_seen": list(gear.KEYS)}
        c = portfolio.connect(cls.db)
        try:
            # a beginner: nothing invested yet
            cls.bea = auth.create_user(c, "bea", PW)
            advisor.save_profile(c, cls.bea, PROFILE)
            prefs.save(c, cls.bea, dict(seen_all))
            # an investor with her own holdings
            cls.ivy = auth.create_user(c, "ivy", PW)
            advisor.save_profile(c, cls.ivy, PROFILE)
            meta, rows, totals, _ = manual_entry.build(
                [{"account": "Brokerage", "symbol": "VTI", "quantity": 10, "cost_basis": 2500.0,
                  "asset_type": "Equity"},
                 {"account": "Brokerage", "symbol": "BND", "quantity": 10, "cost_basis": 1000.0,
                  "asset_type": "Fixed Income"}],
                {"Brokerage": 50.0}, {"VTI": {"price": 300.0}, "BND": {"price": 100.0}},
                today=cls.today - timedelta(days=3))
            portfolio.write_snapshot(c, cls.ivy, meta, rows, totals, manual_entry.SOURCE)
            prefs.save(c, cls.ivy, dict(seen_all))
            # an advisor and her client
            cls.carol = auth.create_user(c, "carol", PW)
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dana = auth.create_user(c, "dana", PW)
            sample_data.load(c, cls.dana)
            auth.link_client(c, cls.carol, cls.dana)
            prefs.save(c, cls.dana, dict(seen_all))
            # someone whose teach-back day is today
            cls.tom = None
            for i in range(60):
                uid = auth.create_user(c, f"t{i}", PW)
                if mm.teach_weekday(uid) == cls.today.weekday():
                    cls.tom = uid
                    advisor.save_profile(c, uid, PROFILE)
                    prefs.save(c, uid, dict(seen_all))
                    break
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _app(self, uid, name, flag="money_minute", client=None, **state):
        import anthropic
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": "Dashboard",
                     "auto_backfilled": True, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY", "ANTHROPIC_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                   NORTHWEND_FLAGS=flag)
        fake = client or _Client()
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch("settings.load_env", lambda *a, **k: {}), \
                unittest.mock.patch.object(anthropic, "Anthropic", lambda **kw: fake), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline_net.connect):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    @staticmethod
    def _text(at):
        parts = [m.value for m in at.markdown]
        parts += [str(e.value) for e in at.caption]
        parts += [h.proto.body for h in at.get("html")]
        return " ".join(parts)

    def _prefs(self, uid):
        c = portfolio.connect(self.db)
        try:
            return prefs.load(c, uid)
        finally:
            c.close()

    @staticmethod
    def _answer_keys(at):
        return [b.key for b in at.button if str(b.key).startswith("mm_")
                and b.key not in ("mm_swap", "mm_link_fees", "mm_link_mix")]

    def test_off_unless_set(self):
        with self._app(self.ivy, "ivy", flag="") as at:
            self.assertNotIn("class='pt-mm-head'", self._text(at))
            self.assertFalse(self._answer_keys(at))

    def test_at_the_top_of_this_month_and_a_tap_keeps_the_day(self):
        before = mm.count(self._prefs(self.ivy))
        with self._app(self.ivy, "ivy") as at:
            text = self._text(at)
            self.assertIn(mm.TITLE, text)
            self.assertIn(mm.days_text(before), text)
            # above the row of cards, so first on a phone
            body = [h.proto.body for h in at.get("html")]
            title = next(i for i, b in enumerate(body) if home_title(b))
            minute = next(i for i, b in enumerate(body) if "class='pt-mm-head'" in b)
            self.assertLess(title, minute)
            item = mm.pick(self.ivy, self.today, self._prefs(self.ivy), False)
            keys = self._answer_keys(at)
            self.assertTrue(keys, item)
            at.button(key=keys[0]).click().run()
            text = self._text(at)
            self.assertIn(mm.days_text(before + 1), text)
            if mm.kind_of(item) == mm.DRILL:
                self.assertIn(drills.THINK_LEAD, text)
                self.assertIn(drills.NO_RIGHT_ANSWER, text)
            elif mm.kind_of(item) == mm.QUIZ:
                self.assertIn("The answer:", text)
            else:
                self.assertRegex(text, r"\*\*(Myth|Fact)\.\*\*")
            self.assertFalse(self._answer_keys(at))
        kept = self._prefs(self.ivy)[mm.PREF]
        self.assertEqual(kept, {"days": [self.today.isoformat()], "seen": [item]})
        # a new visit the same day: done for today, the same card, nothing to tap
        with self._app(self.ivy, "ivy") as at:
            self.assertIn(mm.DONE_TODAY, self._text(at))
            self.assertFalse(self._answer_keys(at))

    def test_before_anything_is_invested_too(self):
        with self._app(self.bea, "bea") as at:
            self.assertIn("class='pt-mm-head'", self._text(at))
            self.assertTrue(self._answer_keys(at))

    def test_never_while_an_advisor_is_in_a_clients_account(self):
        before = self._prefs(self.dana)
        with self._app(self.carol, "carol", two_step_ok=self.carol_ok,
                       active_user_id=self.dana) as at:
            self.assertNotIn("class='pt-mm-head'", self._text(at))
            self.assertFalse(self._answer_keys(at))
        self.assertEqual(self._prefs(self.dana), before)
        # nor on the advisor's own Home
        with self._app(self.carol, "carol", two_step_ok=self.carol_ok) as at:
            self.assertNotIn("class='pt-mm-head'", self._text(at))
        # the client herself, signed in: she has it
        with self._app(self.dana, "dana") as at:
            self.assertIn("class='pt-mm-head'", self._text(at))

    def test_teach_back_day_uses_its_own_check_and_allowance(self):
        if self.tom is None:
            self.skipTest("no login with today as its teach-back day")
        # with Teach It Back off, an ordinary card instead
        with self._app(self.tom, "tom", flag="money_minute") as at:
            self.assertFalse([b for b in at.button if str(b.key).startswith("tb_")])
            self.assertTrue(self._answer_keys(at))
        client = _Client()
        with self._app(self.tom, "tom", flag="money_minute,teach_back", client=client) as at:
            text = self._text(at)
            self.assertIn(mm.KIND_LABELS[mm.TEACH], text)
            at.text_area(key="tb_text_funds").input(
                "A fund holds lots of stocks or bonds at once, and an index fund holds a "
                "whole market.")
            at.button(key="tb_send_funds").click().run()
            self.assertEqual(at.session_state["tb_result_funds"]["verdict"], teach_back.HOLDS)
            self.assertIn(mm.days_text(1), self._text(at))
        self.assertEqual(len(client.calls), 1)
        p = self._prefs(self.tom)
        self.assertEqual(p[mm.PREF], {"days": [self.today.isoformat()], "seen": ["t_funds"]})
        self.assertEqual(p[teach_back.PREF]["funds"]["held"], True)
        self.assertNotIn("whole market", str(p))
        c = portfolio.connect(self.db)
        try:
            row = c.execute("SELECT used FROM ai_usage WHERE user_id = ? AND kind = 'grader'",
                            (self.tom,)).fetchone()
        finally:
            c.close()
        self.assertEqual(row["used"], 1)


def home_title(body):
    return "pt-month-title" in body


if __name__ == "__main__":
    unittest.main()
