"""The beginner path: someone who isn't investing yet. Home is their route
(not an import form), the example portfolio isn't an opened account, a goal
typed in first steps is kept, a goal with nothing invested is "Starting
out" (never "Behind"), and Learn's waypoints answer and tick in place. Runs
dashboard.py with streamlit's AppTest on a scratch database in a temp dir,
plus the pure pieces (plans, route, learn).

    python -m unittest tests.test_beginner_path        (from the repo root)
"""

import contextlib
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from datetime import date

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import advisor  # noqa: E402
import auth  # noqa: E402
import learn  # noqa: E402
import plans  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import route  # noqa: E402
import sample_data  # noqa: E402
import two_step  # noqa: E402

PROFILE = {"goal": "Build long-term wealth", "time_horizon_years": 10,
           "risk_tolerance": "conservative", "drawdown_reaction": "Sell some",
           "experience": "new", "age_range": "Under 25", "income_stability": "Very stable",
           "emergency_fund": "Under 3 months"}
STEPS_DONE = {"first_steps": {"done": True}}
GOAL = {"goal_type": "Build long-term wealth", "target_amount": 20000.0,
        "target_date": "2036-10-01", "monthly_contribution": 100.0}


class BeginnerPathTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or "")) == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_beginner_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            # nothing brought in, profile answered, a goal set
            cls.nina = auth.create_user(c, "nina", "pw-123456789")
            advisor.save_profile(c, cls.nina, PROFILE)
            prefs.save(c, cls.nina, STEPS_DONE)
            plans.save_plan(c, cls.nina, GOAL, set_by=cls.nina)
            # only the example portfolio
            cls.ezra = auth.create_user(c, "ezra", "pw-123456789")
            advisor.save_profile(c, cls.ezra, PROFILE)
            prefs.save(c, cls.ezra, STEPS_DONE)
            sample_data.load(c, cls.ezra)
            # on the first steps' goal screen
            cls.gina = auth.create_user(c, "gina", "pw-123456789")
            advisor.save_profile(c, cls.gina, PROFILE)
            prefs.save(c, cls.gina, {"first_steps": {"step": 5}})
            # an advisor and her empty client
            cls.carol = auth.create_user(c, "carol", "pw-123456789")
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dana = auth.create_user(c, "dana", "pw-123456789")
            auth.link_client(c, cls.carol, cls.dana)
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _run(self, uid, name, page, **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": page, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused")
        # no prices from the internet: Yahoo and any socket fail at once
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    @staticmethod
    def _keys(at):
        return [b.key for b in at.button if b.key]

    @staticmethod
    def _html(at):
        return " ".join(h.proto.body for h in at.get("html"))

    @staticmethod
    def _md(at):
        return " ".join(m.value for m in at.markdown)

    # ---- Home with nothing invested --------------------------------------- #
    def test_home_without_holdings_is_the_route(self):
        with self._run(self.nina, "nina", "Dashboard") as at:
            keys = self._keys(at)
            # Your route and the next step, not an import form
            self.assertIn("route_go", keys)
            self.assertIn("Your route", self._html(at))
            self.assertIn("Next: Waypoint", self._md(at))
            # calm ways to look around, or bring in what they own
            for k in ("start_practice", "start_example", "start_bring"):
                self.assertIn(k, keys)
            self.assertEqual(len(at.get("file_uploader")), 0)
            self.assertNotIn("no data yet", self._md(at))
            # the direction, one line
            self.assertIn("start_direction", keys)
            # "I already invest" shows the existing ways in
            at.button(key="start_bring").click().run()
            self.assertIn("start_manual", self._keys(at))
            self.assertIn("start_import", self._keys(at))

    def test_more_pages_without_holdings(self):
        for page, words in (("Income", "the dividends it pays"),
                            ("Activity", "your buys and sells")):
            with self._run(self.nina, "nina", page) as at:
                self.assertIn(words, self._md(at))
                self.assertEqual(len(at.get("file_uploader")), 0)
        # the watchlist works before anything is brought in (Learn's example funds)
        c = portfolio.connect(self.db)
        try:
            c.execute("INSERT INTO watchlist (user_id, ticker) VALUES (?, 'VTI')", (self.nina,))
            c.commit()
        finally:
            c.close()
        with self._run(self.nina, "nina", "Watchlist") as at:
            self.assertTrue(any(k.startswith("wl_open_VTI") for k in self._keys(at)))

    def test_advisor_sees_an_empty_client_in_her_own_words(self):
        with self._run(self.carol, "carol", "Dashboard", active_user_id=self.dana,
                       two_step_ok=self.carol_ok) as at:
            self.assertIn("Bring dana's statements in", self._md(at))
            self.assertIn("onboard_paste", self._keys(at))
            self.assertNotIn("start_practice", self._keys(at))

    # ---- the example portfolio isn't an opened account ---------------------- #
    def test_example_portfolio_does_not_reach_waypoint_7(self):
        with self._run(self.ezra, "ezra", "Get started", gs_at="account") as at:
            keys = self._keys(at)
            self.assertIn("gs_opened", keys)          # "I've opened an account"
            self.assertNotIn("gs_open_dash", keys)    # (the reached state)
            # ticking it turns the main button into "Bring it in" (the paste window)
            at.button(key="gs_opened").click().run()
            self.assertIn("gs_import", self._keys(at))
            self.assertTrue(at.checkbox(key="gs_acct_opened").value)
        c = portfolio.connect(self.db)
        try:
            self.assertEqual(prefs.load(c, self.ezra)["account_steps"], ["chosen", "opened"])
        finally:
            c.close()

    def test_learn_keeps_its_place_with_only_the_example(self):
        with self._run(self.ezra, "ezra", None) as at:
            # lands on Learn, and the menu keeps one order before and after holdings
            self.assertEqual(at.session_state["page"], "Get started")
            tabs = [b.key for b in at.button if (b.key or "").startswith("tab_")]
            self.assertEqual(tabs, ["tab_Dashboard", "tab_Plan", "tab_AI Assistant",
                                    "tab_Get started"])

    # ---- first steps ---------------------------------------------------------- #
    def test_goal_typed_in_first_steps_is_kept(self):
        with self._run(self.gina, "gina", "Get started") as at:
            # the profile's goal is picked for them, and a tap can't un-pick it
            self.assertEqual(at.session_state["fs_goal_type"], "Build long-term wealth")
            at.number_input(key="fs_goal_target").set_value(20000.0)
            at.number_input(key="fs_goal_monthly").set_value(100.0)
            at.button(key="fs_next").click().run()
        c = portfolio.connect(self.db)
        try:
            row = plans.get_plan(c, self.gina)
        finally:
            c.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["goal_type"], "Build long-term wealth")
        self.assertEqual(row["target_amount"], 20000.0)

    def test_new_investor_is_led_to_opening_an_account(self):
        c = portfolio.connect(self.db)
        try:
            prefs.save(c, self.gina, {"first_steps": {"step": 7}})   # the last screen
        finally:
            c.close()
        with self._run(self.gina, "gina", "Get started") as at:
            self.assertEqual(at.button(key="fs_no_account").proto.type, "primary")
            self.assertNotEqual(at.button(key="fs_manual").proto.type, "primary")
            at.button(key="fs_no_account").click().run()
            self.assertEqual(at.session_state["page"], "Get started")
            self.assertEqual(at.session_state["gs_at"], "account")
            self.assertIn("gs_opened", self._keys(at))

    # ---- Plan with nothing invested ------------------------------------------- #
    def test_plan_with_nothing_invested_is_starting_out(self):
        with self._run(self.nina, "nina", "Plan") as at:
            body = self._html(at)
            self.assertIn("Starting out", body)
            self.assertIn("a month gets you there", body)
            self.assertNotIn(">Behind<", body)

    # ---- Learn's waypoint 2 answers in place; Ask's suggestions ---------------- #
    def test_readiness_questions_answer_in_the_waypoint(self):
        with self._run(self.nina, "nina", "Get started", gs_at="ready") as at:
            pills = [p.key for p in at.get("button_group")]
            self.assertIn("fs_high_interest_debt", pills)
            self.assertIn("fs_employer_match", pills)
            self.assertNotIn("in your profile", self._md(at))

    def test_practice_prices_that_dont_load_say_so(self):
        import sync_history
        with unittest.mock.patch.object(sync_history, "sync", lambda *a, **k: None), \
                self._run(self.nina, "nina", "Get started", gs_at="practice") as at:
            at.button(key="gs_load_prices").click().run()
            self.assertIn("Couldn't load past prices right now - try again later.",
                          " ".join(i.value for i in at.info))

    def test_ask_offers_beginner_questions_without_holdings(self):
        with self._run(self.nina, "nina", "AI Assistant") as at:
            labels = [b.label for b in at.button]
            self.assertIn("What should I do before I invest?", labels)
            self.assertNotIn("Review my portfolio", labels)
            # the profile count includes the two readiness questions still open
            self.assertTrue(any("(8/10)" in b for b in labels), labels)


class BeginnerPiecesTests(unittest.TestCase):
    TODAY = date(2026, 10, 2)

    def test_nothing_invested_is_starting_out(self):
        p = plans.progress(GOAL, 0.0, today=self.TODAY)
        self.assertEqual(p["status"], "starting")
        self.assertGreater(p["needed_monthly"], 100)
        # money in: the usual statuses
        self.assertEqual(plans.progress(GOAL, 1000.0, today=self.TODAY)["status"], "behind")
        self.assertEqual(plans.progress({**GOAL, "target_date": "2026-01-01"}, 0.0,
                                        today=self.TODAY)["status"], "past_date")

    def test_route_when_starting_is_the_next_waypoint(self):
        wps = [("profile", "About you", True), ("ready", "Ready?", False),
               ("goal", "Set a goal", True)]
        kw = dict(has_goal=True, can_manage=True, profile_missing=False, has_holdings=False,
                  monthly=100.0, goal=None, drift=[], days_since_holdings=None, waypoints=wps)
        self.assertEqual(route.next_step(**kw)["key"], "holdings")
        step = route.next_step(**kw, starting=True)
        self.assertEqual((step["key"], step["step"], step["number"]), ("learn", "ready", 2))

    def test_mix_reasons_add_up_to_the_split(self):
        mix = learn.starter_mix(PROFILE)
        self.assertEqual(mix["stocks_pct"], 55)
        self.assertIn("75%", mix["reasons"][0])
        self.assertIn("15 points less", mix["reasons"][1])
        self.assertIn("5 points less", mix["reasons"][2])
        self.assertIn("55%", mix["reasons"][-1])

    def test_legend_never_grows_past_its_card(self):
        with open(os.path.join(REPO, "dashboard.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("grid-template-columns: minmax(0, 1fr)", src.split(".pt-legend {", 1)[1][:80])
        self.assertNotIn("white-space: nowrap", src.split(".pt-legend-label {", 1)[1][:80])


if __name__ == "__main__":
    unittest.main()
