"""This month's practice challenge (challenges.py, views/challenges.py, flag
challenges).

The logic: scored only on following the rule the person picked, never on
what the practice money made; a challenge whose past prices aren't all in
daily_bars is not ready (and none is highlighted); one highlighted a month,
in turn; only keys kept. The words: every fixed line passes the conclusion
policy and the banned words, the chart is labelled as practice money on past
prices. In the app: off unless its flag is set; on Home's This month and on
Learn under practice money; never for an advisor's client or an advisor in a
client's account (nothing drawn, nothing written); Home stays under its
query cap with it on.

    python -m unittest tests.test_challenges        (from the repo root)
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
from datetime import date

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import advisor  # noqa: E402
import ai_policy  # noqa: E402
import auth  # noqa: E402
import challenges as ch  # noqa: E402
import export  # noqa: E402
import flags  # noqa: E402
import gear  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sample_data  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
BANNED = re.compile(
    r"\b(?:should|best|recommend\w*|guarantee\w*|safe|forecast\w*|predict(?!ion\b)\w*|"
    r"winner|leaderboard|rank\w*|beat|outperform\w*|smart|mistake|wrong|correct|"
    r"great|good|bad|urgent|act now|will)\b", re.I)
PROFILE = {"goal": "Build long-term wealth", "time_horizon_years": 15,
           "risk_tolerance": "moderate", "drawdown_reaction": "Hold",
           "experience": "new", "age_range": "25-34", "income_stability": "Very stable",
           "emergency_fund": "3-6 months"}


def _months(first, last):
    y, m = int(first[:4]), int(first[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        y, m = y + (m == 12), m % 12 + 1
    return out


def _prices(first="2018-01", last="2023-12"):
    """{ticker: [(date, price)]}: stocks swing hard, bonds barely move."""
    out = {ch.STOCKS: [], ch.BONDS: []}
    for i, m in enumerate(_months(first, last)):
        out[ch.STOCKS].append((f"{m}-02", 100.0 * (1.6 if i % 6 < 3 else 0.7)))
        out[ch.STOCKS].append((f"{m}-15", 1.0))   # mid-month: never used
        out[ch.BONDS].append((f"{m}-02", 50.0 + i * 0.01))
    return out


def _run(c, points, rule, pick):
    """Play a challenge to the end, answering each check with pick(said)."""
    answers = []
    while True:
        r = ch.play(c, points, rule, answers)
        if r["pending"] is None:
            return r
        p = r["pending"]
        answers.append(pick(ch.rule_says(p["stocks_pct"], ch.RULES[rule], c["monthly"])))


class ScoringTests(unittest.TestCase):

    def setUp(self):
        self.points = ch.monthly_points(_prices())
        self.c = ch.BY_KEY["y2020"]

    def test_points_are_each_months_first_day(self):
        self.assertEqual(self.points["2019-07"][0], "2019-07-02")
        self.assertNotIn(1.0, self.points["2019-07"][1].values())

    def test_the_rule(self):
        self.assertEqual(ch.rule_says(70, 70, 100), {ch.NOTHING})
        self.assertEqual(ch.rule_says(74.9, 70, 100), {ch.NOTHING})
        self.assertEqual(ch.rule_says(58, 70, 100), {ch.REBALANCE, ch.DEPOSITS})
        self.assertEqual(ch.rule_says(80, 70, 0), {ch.REBALANCE})
        for pct in range(0, 101):   # cashing out is never what a rule says
            self.assertNotIn(ch.SELL, ch.rule_says(pct, 70, 100))

    def test_scored_only_on_following_the_rule(self):
        # always what the rule says: every month followed
        r = _run(self.c, self.points, "s70", lambda said: sorted(said)[-1])
        self.assertEqual(ch.score(r["checks"]), (24, 24))
        self.assertEqual(ch.followed_line(self.c, r["checks"]),
                         "Followed your rule: 24 of 24 months")
        # the other choice the rule allows: different money, the same score
        r2 = _run(self.c, self.points, "s70", lambda said: sorted(said)[0])
        self.assertEqual(ch.score(r2["checks"]), (24, 24))
        # never what the rule says: none followed, whatever the money did
        r3 = _run(self.c, self.points, "s70",
                  lambda said: ch.SELL if ch.NOTHING not in said else ch.REBALANCE)
        self.assertEqual(ch.score(r3["checks"])[0], 0)
        # the score reads only whether each answer followed the rule
        self.assertNotEqual(round(r["rows"][-1]["value"]), round(r3["rows"][-1]["value"]))
        self.assertEqual(ch.score([{"followed": True}, {"followed": False}]), (1, 2))
        self.assertNotIn("value", {k for x in r["checks"] for k in x})

    def test_the_answers_move_the_practice_money(self):
        held = _run(self.c, self.points, "s70", lambda said: ch.NOTHING)
        out = _run(self.c, self.points, "s70", lambda said: ch.SELL)
        self.assertEqual(held["rows"][-1]["money_in"], out["rows"][-1]["money_in"])
        self.assertEqual(held["rows"][-1]["money_in"], 10000 + 100 * 25)
        self.assertNotEqual(round(held["rows"][-1]["value"]), round(out["rows"][-1]["value"]))

    def test_steps_every_three_months(self):
        c = ch.BY_KEY["first100"]
        self.assertEqual(ch.steps(c), 20)
        r = ch.play(c, self.points, "s60", [])
        self.assertEqual(r["pending"]["step"], 1)
        self.assertEqual(r["pending"]["month"], "2018-04")
        self.assertEqual(ch.unit(c), "checks")
        r = _run(c, self.points, "s60", lambda said: ch.NOTHING)
        self.assertEqual(len(r["checks"]), 20)

    def test_said_lines(self):
        self.assertEqual(ch.said_line({"move": True, "stocks_pct": 58.2}, 70),
                         "Your rule said bring it back: stocks were 12 points away from 70%.")
        self.assertEqual(ch.said_line({"move": False, "stocks_pct": 68}, 70),
                         "Your rule said leave it: stocks were within 5 points of 70%.")


class DataTests(unittest.TestCase):

    def test_unavailable_when_a_month_is_missing(self):
        pts = ch.monthly_points(_prices())
        self.assertEqual(ch.available_keys(pts), ["y2020", "y2022", "first100"])
        self.assertFalse(ch.available(ch.BY_KEY["y2018"], pts))   # 2017 isn't there
        gap = _prices()
        gap[ch.BONDS] = [r for r in gap[ch.BONDS] if not r[0].startswith("2020-03")]
        self.assertNotIn("y2020", ch.available_keys(ch.monthly_points(gap)))
        self.assertIn("y2022", ch.available_keys(ch.monthly_points(gap)))
        self.assertEqual(ch.monthly_points({ch.STOCKS: _prices()[ch.STOCKS]}), {})
        self.assertEqual(ch.available_keys({}), [])
        self.assertIsNone(ch.of_month([], date(2026, 10, 7)))

    def test_one_a_month_in_turn(self):
        keys = ["a", "b", "c"]
        seen = [ch.of_month(keys, date(2026, m, 15)) for m in range(1, 13)]
        self.assertEqual(set(seen), set(keys))
        for m in range(1, 12):
            self.assertEqual(ch.next_of_month(keys, date(2026, m, 3)),
                             ch.of_month(keys, date(2026, m + 1, 1)))
        self.assertEqual(ch.next_of_month(keys, date(2026, 12, 3)),
                         ch.of_month(keys, date(2027, 1, 1)))
        self.assertEqual(ch.month_end(date(2026, 2, 3)), date(2026, 2, 28))
        self.assertEqual(ch.month_end(date(2026, 12, 3)), date(2026, 12, 31))

    def test_stand_ins_are_the_practice_portfolios(self):
        import learn
        self.assertEqual(ch.PRACTICE_PART, {ch.STOCKS: "us", ch.BONDS: "bonds"})
        for part, block in ch.PRACTICE_PART.items():   # kinds, worded as Learn words them
            self.assertEqual(ch.KIND_WORDS[part], learn.KINDS[block])
            self.assertIn(ch.KIND_WORDS[part], ch.mix_line())
        with open(os.path.join(REPO, "challenges.py"), encoding="utf-8") as fh:
            src = fh.read()
        for t in ("VTI", "BND", "VXUS"):   # never a ticker: kinds of funds only
            self.assertNotIn(t, src)


class KeptTests(unittest.TestCase):

    def test_only_keys_are_kept(self):
        d = date(2026, 10, 7)
        p = ch.started({"other": 1}, "first100", "s60")
        self.assertEqual(p, {"other": 1, ch.PREF: {"first100": {"rule": "s60", "step": 0,
                                                                "answers": []}}})
        for _ in range(ch.steps(ch.BY_KEY["first100"])):
            p = ch.answered(p, "first100", ch.NOTHING, d)
        e = p[ch.PREF]["first100"]
        self.assertEqual(set(e), {"rule", "step", "answers", "done"})
        self.assertEqual(e["step"], 20)
        self.assertEqual(e["done"], "2026-10-07")
        self.assertEqual(set(e["answers"]), {ch.NOTHING})
        # one more does nothing; unknown keys and choices change nothing
        self.assertEqual(ch.answered(p, "first100", ch.NOTHING, d), p)
        self.assertEqual(ch.answered(p, "y2020", ch.NOTHING, d), p)     # not started
        q = ch.started(p, "y2020", "s70")
        self.assertEqual(ch.answered(q, "y2020", "buy VTI", d), q)
        self.assertEqual(ch.started(p, "nope", "s70"), p)
        self.assertEqual(ch.started(p, "y2020", "s99"), p)
        # nothing but keys, whole numbers and a day
        text = json.dumps(p[ch.PREF])
        self.assertNotIn("$", text)
        self.assertNotRegex(text, r"\d+\.\d")
        # start again: gone
        self.assertEqual(ch.cleared(ch.cleared(p, "first100"), "nope"), {"other": 1})

    def test_a_bad_entry_reads_as_not_started(self):
        self.assertIsNone(ch.entry({ch.PREF: {"y2020": {"rule": "x"}}}, "y2020"))
        self.assertIsNone(ch.entry({ch.PREF: "junk"}, "y2020"))
        e = ch.entry({ch.PREF: {"y2020": {"rule": "s70", "answers": ["nothing", "??"],
                                          "done": "2026-10-07"}}}, "y2020")
        self.assertEqual(e, {"rule": "s70", "step": 1, "answers": ["nothing"]})   # not done


class WordingTests(unittest.TestCase):

    def test_every_fixed_line(self):
        lines = ch.templates()
        self.assertGreater(len(lines), 40)
        for t in lines:
            with self.subTest(t):
                self.assertEqual(ai_policy.findings(t), [], t)
                self.assertIsNone(BANNED.search(t), t)

    def test_the_chart_label_and_the_score_line(self):
        self.assertEqual(ch.CHART_LABEL, "Practice money, past prices, not a prediction")
        self.assertIn("not on how much the practice money made", ch.SCORED)
        self.assertIn("practice money, not real", ch.EYEBROW)

    def test_three_or_more_and_kinds_not_picks(self):
        self.assertGreaterEqual(len(ch.CHALLENGES), 3)
        self.assertIn("fund", ch.MIX_LINE)
        self.assertIn("{stocks}", ch.MIX_LINE)

    def test_never_in_the_ai_or_an_advisors_files(self):
        for name in ("advisor.py", "context_card.py", "ai_gateway.py", "ai_tools.py",
                     "ai_library.py", "meeting.py", "reports.py", "overview.py",
                     "advising.py", "proposals.py", "weekly_email.py", "client_plan.py",
                     os.path.join("views", "assistant.py"), os.path.join("views", "clients.py")):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                self.assertNotIn("challenges", fh.read(), name)

    def test_the_flag_is_off_unless_set_and_owns_the_view(self):
        self.assertEqual(flags.FEATURES["challenges"], {"gates": (), "view": "challenges"})
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": ""}), \
                unittest.mock.patch.object(flags, "_secret", lambda name: None):
            self.assertFalse(flags.on("challenges"))
            self.assertFalse(flags.view_on("challenges"))


class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_chal_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.bea = auth.create_user(c, "bea", PW)   # a beginner, nothing invested
            advisor.save_profile(c, cls.bea, PROFILE)
            prefs.save(c, cls.bea, {"first_steps": {"done": True},
                                    "gear_seen": list(gear.KEYS)})
            cls.ivy = auth.create_user(c, "ivy", PW)   # an investor (the example portfolio)
            sample_data.load(c, cls.ivy)
            prefs.save(c, cls.ivy, {"first_steps": {"done": True},
                                    "gear_seen": list(gear.KEYS)})
            cls.carol = auth.create_user(c, "carol", PW)
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dana = auth.create_user(c, "dana", PW)
            sample_data.load(c, cls.dana)
            auth.link_client(c, cls.carol, cls.dana)
            prefs.save(c, cls.dana, {"first_steps": {"done": True},
                                     ch.PREF: {"y2020": {"rule": "s70", "step": 0,
                                                         "answers": []}}})
            import learn
            c.executemany("INSERT INTO daily_bars (ticker, date, close, adj_close) "
                          "VALUES (?, ?, ?, ?)",
                          [(learn.PRACTICE_TICKERS[ch.PRACTICE_PART[part]], d, p, p)
                           for part, rows in _prices().items() for d, p in rows])
            c.commit()
        finally:
            c.close()
        cls.ready = ["y2020", "y2022", "first100"]

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _app(self, uid, name, flag="challenges", page="Dashboard", **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": page,
                     "auto_backfilled": True, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                   NORTHWEND_FLAGS=flag)
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
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
        parts += [str(e.value) for e in at.info]
        return " ".join(parts)

    def _prefs(self, uid):
        c = portfolio.connect(self.db)
        try:
            return prefs.load(c, uid)
        finally:
            c.close()

    def _month(self):
        return ch.BY_KEY[ch.of_month(self.ready, date.today())]

    def test_off_unless_set(self):
        for uid, name, page in ((self.bea, "bea", "Dashboard"), (self.ivy, "ivy", "Dashboard"),
                                (self.bea, "bea", "Get started")):
            with self._app(uid, name, flag="", page=page, gs_at="practice", fs_hide=True) as at:
                text = self._text(at)
                self.assertNotIn("practice challenge", text.lower())
                self.assertFalse([b for b in at.button if str(b.key).startswith("ch_")])

    def test_home_card_for_an_investor_and_a_beginner(self):
        for uid, name in ((self.ivy, "ivy"), (self.bea, "bea")):
            with self._app(uid, name) as at:
                text = self._text(at)
                self.assertIn(self._month()["title"], text)
                self.assertIn("practice money, not real", text)
                self.assertIn(ch.NOT_STARTED, text)
                self.assertIn("ch_card_open", [b.key for b in at.button])

    def test_learn_play_two_months_keys_kept(self):
        c = self._month()
        key = c["key"]
        with self._app(self.bea, "bea", page="Get started", gs_at="practice",
                       fs_hide=True) as at:
            text = self._text(at)
            self.assertIn(ch.SECTION, text)
            self.assertIn(ch.PICK_TITLE, text)
            at.button(key=f"ch_start_{key}").click().run()
            text = self._text(at)
            self.assertIn(ch.CHART_LABEL, text)
            self.assertIn(ch.SCORED, text)
            self.assertIn("What does your rule say?", text)
            at.button(key=f"ch_{key}_{ch.NOTHING}").click().run()
            at.button(key=f"ch_{key}_{ch.SELL}").click().run()
            text = self._text(at)
            self.assertRegex(text, r"Followed your rule: [0-2] of 2 (months|checks)")
        kept = self._prefs(self.bea)[ch.PREF]
        self.assertEqual(kept, {key: {"rule": "s70", "step": 2,
                                      "answers": [ch.NOTHING, ch.SELL]}})
        c2 = portfolio.connect(self.db)
        try:
            self.assertIn(ch.PREF, str(export.collect(c2, self.bea)["settings"]))
        finally:
            c2.close()
        # not ready: marked, and it can't be started
        with self._app(self.bea, "bea", page="Get started", gs_at="practice", fs_hide=True,
                       ch_pick="y2018", ch_picked=True) as at:
            text = self._text(at)
            self.assertIn("Not ready yet", text)
            self.assertNotIn("ch_start_y2018", [b.key for b in at.button])
        # not chosen by them: the pick moves to this month's ready one
        with self._app(self.bea, "bea", page="Get started", gs_at="practice", fs_hide=True,
                       ch_pick="y2018") as at:
            self.assertNotEqual(at.selectbox(key="ch_pick").value, "y2018")
            self.assertNotIn("Not ready yet", self._text(at))

    def test_never_for_an_advisors_client_or_an_advisor_in_her_account(self):
        before = self._prefs(self.dana)
        with self._app(self.carol, "carol", two_step_ok=self.carol_ok,
                       active_user_id=self.dana) as at:
            self.assertNotIn("practice challenge", self._text(at).lower())
            self.assertFalse([b for b in at.button if str(b.key).startswith("ch_")])
        self.assertEqual(self._prefs(self.dana), before)   # the advisor wrote nothing
        for page in ("Dashboard", "Get started"):
            with self._app(self.dana, "dana", page=page, gs_at="practice", fs_hide=True) as at:
                self.assertNotIn("practice challenge", self._text(at).lower())
                self.assertFalse([b for b in at.button if str(b.key).startswith("ch_")])
        # signed in herself (an advisor's client): her kept challenge is untouched
        self.assertEqual(self._prefs(self.dana)[ch.PREF], before[ch.PREF])

    def test_home_stays_under_its_query_cap(self):
        from streamlit.testing.v1 import AppTest
        from tests.test_page_queries import HOME_CONNECTIONS, HOME_QUERIES
        seen = {"sql": 0, "connect": 0}
        real = sqlite3.connect

        def counting(*a, **k):
            conn = real(*a, **k)
            seen["connect"] += 1
            conn.set_trace_callback(lambda s: seen.__setitem__(
                "sql", seen["sql"] + (not s.startswith("PRAGMA"))))
            return conn
        with self._app(self.ivy, "ivy") as at:
            self.assertIn(self._month()["title"], self._text(at))
            self.assertIsInstance(at, AppTest)
            with unittest.mock.patch("sqlite3.connect", counting):
                at.run()
        self.assertLessEqual(seen["sql"], HOME_QUERIES)
        self.assertLessEqual(seen["connect"], HOME_CONNECTIONS)


if __name__ == "__main__":
    unittest.main()
