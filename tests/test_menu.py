"""The menu (ROADMAP S4): investors get Home, Plan, Ask Northwend and Learn,
and More for the rest; advisors keep the full list. Runs dashboard.py with
streamlit's AppTest on a scratch database in a temp dir.

    python -m unittest tests.test_menu        (from the repo root)
"""

import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import auth  # noqa: E402
import portfolio  # noqa: E402
import sample_data  # noqa: E402
import two_step  # noqa: E402

MAIN = ["nav_Dashboard", "nav_Plan", "nav_AI Assistant", "nav_Get started"]
MORE = ["nav_Watchlist", "nav_Activity", "nav_Income", "nav_Account", "nav_About"]


class MenuTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.db = os.path.join(cls.tmp, "menu.db")
        cls.env = unittest.mock.patch.dict(os.environ, {
            "PORTFOLIO_DB": cls.db, "MAIL_DRY_RUN": "1"})
        cls.env.start()
        for key in ("ANTHROPIC_API_KEY", "FINNHUB_API_KEY", "RESEND_API_KEY",
                    "NORTHWEND_ADMINS"):
            os.environ.pop(key, None)
        c = portfolio.connect(cls.db)
        try:
            cls.alice = auth.create_user(c, "alice", "pw-123456789")  # holdings
            sample_data.load(c, cls.alice)
            cls.bob = auth.create_user(c, "bob", "pw-123456789")      # nothing yet
            cls.carol = auth.create_user(c, "carol", "pw-123456789")  # an advisor
            auth.set_advisor(c, "carol", True)
            # advisors must have two-step sign-in (R2): carol has it, and her
            # tab has passed the code
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dave = auth.create_user(c, "dave", "pw-123456789")    # her client
            auth.link_client(c, cls.carol, cls.dave)
            sample_data.load(c, cls.dave)
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _run(self, user_id, username, page=None, **state):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        at.session_state["user_id"] = user_id
        at.session_state["username"] = username
        for k, v in state.items():
            at.session_state[k] = v
        if page:
            at.query_params["page"] = page
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return at

    @staticmethod
    def _more(at):
        pops = [p for p in at.sidebar.get("popover") if p.proto.id.endswith("pt_more")]
        return pops[0] if pops else None

    def _menus(self, at):
        """(the sidebar's own page buttons, the ones inside More) as keys."""
        more = self._more(at)
        inside = [b.key for b in more.button] if more else []
        top = [b.key for b in at.sidebar.button
               if b.key and b.key.startswith("nav_") and b.key not in inside]
        return top, inside

    def test_investor_menu_is_short_and_more_holds_the_rest(self):
        at = self._run(self.alice, "alice", "about")
        top, inside = self._menus(at)
        self.assertEqual(top, MAIN)
        self.assertEqual(inside, MORE)
        labels = {b.key: b.label for b in at.sidebar.button}
        self.assertEqual([labels[k] for k in MAIN], ["Home", "Plan", "Ask Northwend", "Learn"])
        # on a More page, More looks selected, and so does the page inside it
        self.assertEqual(self._more(at).proto.popover.type, "primary")
        self.assertEqual(at.sidebar.button(key="nav_About").proto.type, "primary")
        self.assertTrue(all(at.sidebar.button(key=k).proto.type == "tertiary" for k in MAIN))
        # the phone tab bar has the same four, then More with the rest
        tabs = [b.key for b in at.button if (b.key or "").startswith("tab_")]
        self.assertEqual(tabs, ["tab_Dashboard", "tab_Plan", "tab_AI Assistant", "tab_Get started"])
        self.assertIn("Learn", at.button(key="tab_Get started").label)
        more_tabs = [b.key for b in at.button if (b.key or "").startswith("more_")
                     and b.key[5:] in {k[4:] for k in MORE}]
        self.assertEqual(more_tabs, ["more_" + k[4:] for k in MORE])

        # a page inside More opens with one tap and keeps its place in the address
        at.sidebar.button(key="nav_Income").click()
        at.run()
        self.assertEqual(at.session_state["page"], "Income")
        self.assertEqual(at.query_params["page"], ["income"])
        self.assertEqual(self._more(at).proto.popover.type, "primary")
        # back on a main page, More isn't selected
        at.sidebar.button(key="nav_Plan").click()
        at.run()
        self.assertEqual(at.query_params["page"], ["plan"])
        self.assertEqual(self._more(at).proto.popover.type, "tertiary")
        self.assertEqual(at.sidebar.button(key="nav_Plan").proto.type, "primary")

    def test_deep_links_still_open_every_kind_of_page(self):
        # a More page by its own name, and Get started by its old and new names
        at = self._run(self.alice, "alice", "watchlist")
        self.assertEqual(at.session_state["page"], "Watchlist")
        at = self._run(self.alice, "alice", "get-started")
        self.assertEqual(at.session_state["page"], "Get started")
        self.assertEqual(at.query_params["page"], ["learn"])

    def test_new_investor_starts_on_learn(self):
        at = self._run(self.bob, "bob")
        self.assertEqual(at.session_state["page"], "Get started")
        top, inside = self._menus(at)
        # the same order as with holdings: a tab never moves under their thumb
        self.assertEqual(top, MAIN)
        self.assertEqual(inside, MORE)
        self.assertEqual(self._more(at).proto.popover.type, "tertiary")

    def test_advisor_menu_is_unchanged(self):
        at = self._run(self.carol, "carol", "about", active_user_id=self.dave,
                       two_step_ok=self.carol_ok)
        self.assertIsNone(self._more(at))
        top, _ = self._menus(at)
        self.assertEqual(top, ["nav_Clients", "nav_Dashboard", "nav_Plan", "nav_Advisor notes",
                               "nav_Watchlist", "nav_Activity", "nav_Income",
                               "nav_AI Assistant", "nav_Get started", "nav_Account",
                               "nav_About"])
        labels = {b.key: b.label for b in at.sidebar.button}
        self.assertEqual(labels["nav_Get started"], "Get started")
        self.assertEqual(labels["nav_Dashboard"], "Portfolio")

    def test_more_window_closes_after_a_choice(self):
        with open(os.path.join(REPO, "ui_enhancements.js"), encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn(".st-key-pt_more", js)
        with open(os.path.join(REPO, "dashboard.py"), encoding="utf-8") as fh:
            self.assertIn('key="pt_more"', fh.read())


if __name__ == "__main__":
    unittest.main()
