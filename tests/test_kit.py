"""Your kit (views/kit.py, gear.py) explains itself: Home's card names every
piece and opens a window that says what each is for and how it's earned,
with a button to where it's earned; the "milestone reached" window says
what was earned, why it matters and what's next, and the day it was earned
is kept. Runs dashboard.py with streamlit's AppTest on a scratch database
in a temp dir.

    python -m unittest tests.test_kit        (from the repo root)
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
import gear  # noqa: E402
import plans  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402

PROFILE = {"goal": "Build long-term wealth", "time_horizon_years": 10,
           "risk_tolerance": "conservative", "drawdown_reaction": "Sell some",
           "experience": "new", "age_range": "Under 25", "income_stability": "Very stable",
           "emergency_fund": "Under 3 months"}
GOAL = {"goal_type": "Build long-term wealth", "target_amount": 20000.0,
        "target_date": "2036-10-01", "monthly_contribution": 100.0}


class KitTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or "")) == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_kit_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            # profile and goal done, both already shown
            cls.kim = auth.create_user(c, "kim", "pw-123456789")
            advisor.save_profile(c, cls.kim, PROFILE)
            plans.save_plan(c, cls.kim, GOAL, set_by=cls.kim)
            prefs.save(c, cls.kim, {"first_steps": {"done": True},
                                    "gear_seen": ["map", "compass"],
                                    "gear_dates": {"map": {"on": "2026-09-14"}}})
            # the profile just answered: the map is earned now
            cls.lee = auth.create_user(c, "lee", "pw-123456789")
            advisor.save_profile(c, cls.lee, PROFILE)
            prefs.save(c, cls.lee, {"first_steps": {"done": True}, "gear_seen": []})
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _run(self, uid, name, page="Dashboard"):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": page}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused")
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    @staticmethod
    def _html(at):
        return " ".join(h.proto.body for h in at.get("html"))

    def _prefs(self, uid):
        c = portfolio.connect(self.db)
        try:
            return prefs.load(c, uid)
        finally:
            c.close()

    def test_home_card_names_every_piece_and_opens_the_window(self):
        with self._run(self.kim, "kim") as at:
            body = self._html(at)
            self.assertIn("Your kit · 2 of 9 earned", body)
            for k in gear.KEYS:
                name = gear.BY_KEY[k][1]
                self.assertIn(f">{name}</span>", body)          # a visible label
                self.assertIn(f"title='{name} - for ", body)    # and its meaning on hover
            # the next one: the tent, with the way there
            self.assertIn("Next to earn: <b>tent</b>", body)
            self.assertEqual(at.button(key="kit_go").label, gear.GO["tent"][0])
            self.assertEqual(at.button(key="kit_open").label, "What each piece is for")
            at.button(key="kit_open").click().run()
            body = self._html(at)
            for k in gear.KEYS:
                self.assertIn(gear.FOR[k].replace("'", "&#x27;"), body)
                self.assertIn(gear.HOW[k].replace("'", "&#x27;").replace('"', "&quot;"), body)
            self.assertIn("Earned Sep 14, 2026", body)    # when it was earned
            self.assertIn("Not yet", body)
            keys = [b.key for b in at.button if b.key]
            for k in ("tent", "rope", "boots", "lantern", "flag"):
                self.assertIn(f"kit_go_{k}", keys)
            # earned / nothing to do (the logbook: no check-in waiting without holdings)
            for k in ("map", "compass", "cloak", "logbook"):
                self.assertNotIn(f"kit_go_{k}", keys)

    def test_the_button_goes_to_the_waypoint(self):
        with self._run(self.kim, "kim") as at:
            at.button(key="kit_go").click().run()
            self.assertEqual(at.session_state["page"], "Get started")
            self.assertEqual(at.session_state["gs_at"], "basics")

    def test_milestone_says_what_why_and_whats_next(self):
        with self._run(self.lee, "lee") as at:
            body = self._html(at)
            self.assertIn("You've earned the <b>map</b> for your kit - for knowing", body)
            self.assertIn(gear.WHY["map"].replace("'", "&#x27;"), body)
            self.assertIn("Next: <b>compass</b>", body)
            self.assertEqual(at.button(key="milestone_go").label, gear.GO["compass"][0])
            p = self._prefs(self.lee)
            self.assertEqual(p["gear_seen"], ["map"])
            self.assertEqual(p["gear_dates"], {"map": {"on": date.today().isoformat()}})
            at.button(key="milestone_go").click().run()
            # the compass is earned on Learn's "Set a goal" waypoint
            self.assertEqual(at.session_state["page"], "Get started")
            self.assertEqual(at.session_state["gs_at"], "goal")
            self.assertNotIn("milestone_queue", at.session_state)


if __name__ == "__main__":
    unittest.main()
