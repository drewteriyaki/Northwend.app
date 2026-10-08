"""The menu: a column down the left side on a laptop (a bar along the top
and the tab bar along the bottom on a phone), everything on it at once - no
More. Investors get Home, Plan, Money, Life, Learn and Ask Northwend (+ Your
advisor for a managed client); Money is one page with a tab each for Income,
Activity and Watchlist, listed under Money while it's open; Account, What's
new, About, Admin and Log out are in the name menu at the foot, under the
route's progress. Advisors get Your clients, Viewing, Portfolio, Plan,
Advisor notes, Money and Ask Northwend - no Life. Runs dashboard.py with
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

INVESTOR = ["nav_Dashboard", "nav_Plan", "nav_Money", "nav_Life", "nav_Get started",
            "nav_AI Assistant"]
INVESTOR_LABELS = ["Home", "Plan", "Money", "Life", "Learn", "Ask Northwend"]
PHONE = ["tab_Dashboard", "tab_Plan", "tab_Money", "tab_Life", "tab_Get started",
         "tab_AI Assistant"]
PHONE_LABELS = ["Home", "Plan", "Money", "Life", "Learn", "Ask"]
MONEY_TABS = ["money_Income", "money_Activity", "money_Watchlist"]


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
            cls.ann = auth.create_user(c, "ann", "pw-123456789")      # an admin
            secret = two_step.new_secret()
            two_step.enable(c, cls.ann, secret, two_step.totp(secret))
            cls.ann_ok = f"{cls.ann}:{two_step.status(c, cls.ann)['stamp']}"
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
    def _keys(at, prefix):
        return [b.key for b in at.button if (b.key or "").startswith(prefix)]

    @staticmethod
    def _popovers(at):
        """The menu's own popovers (keyed pt_...), by key; a page's own aren't counted."""
        pops = {p.proto.id.rsplit("-", 1)[-1]: p for p in at.get("popover")}
        return {k: p for k, p in pops.items() if k.startswith("pt_")}

    def _current(self, at, prefix):
        """The tabs drawn as the page showing (primary; aria-current in the browser)."""
        return [b.key for b in at.button
                if (b.key or "").startswith(prefix) and b.proto.type == "primary"]

    def test_investor_bar_shows_every_tab_and_no_more(self):
        at = self._run(self.alice, "alice", "plan")
        self.assertEqual(self._keys(at, "nav_"), INVESTOR)
        self.assertEqual([at.button(key=k).label for k in INVESTOR], INVESTOR_LABELS)
        # the phone tab bar: exactly the same six
        self.assertEqual(self._keys(at, "tab_"), PHONE)
        self.assertEqual([at.button(key=k).label.split(" ", 1)[1] for k in PHONE],
                         PHONE_LABELS)
        self.assertEqual(self._current(at, "nav_"), ["nav_Plan"])
        self.assertEqual(self._current(at, "tab_"), ["tab_Plan"])
        # nothing hidden behind a More, and no Streamlit sidebar: the menu
        # column is the app's own (pinned by the styles), one set of buttons
        # for a laptop and a phone
        labels = [b.label for b in at.button] + [p.proto.popover.label
                                                  for p in at.get("popover")]
        self.assertFalse([x for x in labels if "More" in x], labels)
        self.assertEqual(len(at.sidebar.children), 0)
        with open(os.path.join(REPO, "dashboard.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("st.sidebar", src)
        self.assertNotIn('st.popover("More"', src)

    def test_name_menu_and_add_holdings(self):
        at = self._run(self.alice, "alice", "about")
        pops = self._popovers(at)
        self.assertEqual(set(pops), {"pt_add", "pt_me"})
        self.assertEqual(pops["pt_me"].proto.popover.label, "alice")
        menu = [b.key for b in pops["pt_me"].button]
        self.assertEqual(menu, ["menu_Account", "menu_What's new", "menu_About", "pt_theme", "menu_logout"])
        self.assertEqual(self._current(at, "menu_"), ["menu_About"])
        self.assertEqual(self._keys(at, "nav_"), INVESTOR)   # About isn't a tab
        self.assertEqual(self._current(at, "nav_"), [])
        # + Add holdings: the existing ways in, each opening its window
        self.assertEqual([b.key for b in pops["pt_add"].button], ["add_manual", "add_import"])
        pops["pt_add"].button(key="add_manual").click()
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        # the account menu's pages open from it
        self._popovers(at)["pt_me"].button(key="menu_Account").click()
        at.run()
        self.assertEqual(at.session_state["page"], "Account")
        self.assertEqual(at.query_params["page"], "account")

    def test_admin_in_the_name_menu(self):
        # (admins must have two-step sign-in: ann has it, and her tab passed it)
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_ADMINS": "ann"}):
            at = self._run(self.ann, "ann", "home", two_step_ok=self.ann_ok)
        menu = [b.key for b in self._popovers(at)["pt_me"].button]
        self.assertEqual(menu, ["menu_Account", "menu_What's new", "menu_About", "menu_Admin", "pt_theme",
                                "menu_logout"])

    def test_money_is_one_page_with_three_tabs(self):
        at = self._run(self.alice, "alice", "home")
        at.button(key="nav_Money").click()
        at.run()
        self.assertEqual(at.session_state["page"], "Income")
        self.assertEqual(at.query_params["page"], "income")
        self.assertEqual(at.title[0].value, "Money")
        self.assertEqual(self._keys(at, "money_"), MONEY_TABS)
        self.assertEqual(self._current(at, "money_"), ["money_Income"])
        self.assertEqual(self._current(at, "nav_"), ["nav_Money"])
        self.assertEqual(self._current(at, "tab_"), ["tab_Money"])
        # the menu lists Money's tabs under it while it's open
        self.assertEqual(self._keys(at, "navsub_"),
                         ["navsub_Income", "navsub_Activity", "navsub_Watchlist"])
        self.assertEqual(self._current(at, "navsub_"), ["navsub_Income"])
        for tab, slug in (("Activity", "activity"), ("Watchlist", "watchlist")):
            at.button(key=f"money_{tab}").click()
            at.run()
            self.assertFalse(at.exception, [e.value for e in at.exception])
            self.assertEqual(at.session_state["page"], tab)
            self.assertEqual(at.query_params["page"], slug)
            self.assertEqual(self._current(at, "money_"), [f"money_{tab}"])
            self.assertEqual(self._current(at, "navsub_"), [f"navsub_{tab}"])
            self.assertEqual(self._current(at, "nav_"), ["nav_Money"])
        # Money goes back to the tab last open
        at.button(key="nav_Dashboard").click()
        at.run()
        self.assertEqual(self._keys(at, "money_"), [])
        self.assertEqual(self._keys(at, "navsub_"), [])
        at.button(key="nav_Money").click()
        at.run()
        self.assertEqual(at.session_state["page"], "Watchlist")

    def test_old_links_open_the_right_tab(self):
        for slug, page in (("income", "Income"), ("activity", "Activity"),
                           ("watchlist", "Watchlist"), ("money", "Income"),
                           ("dashboard", "Dashboard"), ("ask-sage", "AI Assistant"),
                           ("get-started", "Get started"), ("about", "About")):
            at = self._run(self.alice, "alice", slug)
            self.assertEqual(at.session_state["page"], page, slug)
        self.assertEqual(at.query_params["page"], "about")
        # a managed client's page from their advisor, by either name
        for slug in ("advisor-notes", "your-advisor"):
            at = self._run(self.dave, "dave", slug)
            self.assertEqual(at.session_state["page"], "Advisor notes", slug)
            self.assertEqual(at.query_params["page"], "your-advisor")

    def test_new_investor_starts_on_learn(self):
        at = self._run(self.bob, "bob")
        self.assertEqual(at.session_state["page"], "Get started")
        # the same order as with holdings: a tab never moves under their thumb
        self.assertEqual(self._keys(at, "nav_"), INVESTOR)
        self.assertEqual(self._keys(at, "tab_"), PHONE)
        # nothing in yet: the example portfolio is one of the ways in
        add = [b.key for b in self._popovers(at)["pt_add"].button]
        self.assertEqual(add, ["add_manual", "add_import", "add_sample"])

    def test_managed_client_gets_your_advisor_and_no_add_holdings(self):
        at = self._run(self.dave, "dave", "home")
        self.assertEqual(self._keys(at, "nav_"), [*INVESTOR, "nav_Advisor notes"])
        self.assertEqual(at.button(key="nav_Advisor notes").label, "Your advisor")
        self.assertEqual(self._keys(at, "tab_"), [*PHONE, "tab_Advisor notes"])
        pops = self._popovers(at)
        self.assertEqual(set(pops), {"pt_me"})   # their advisor brings statements in
        self.assertIn("Your advisor: **carol**",
                      [c.value for c in pops["pt_me"].caption])

    def test_advisor_bar(self):
        at = self._run(self.carol, "carol", "about", active_user_id=self.dave,
                       two_step_ok=self.carol_ok)
        self.assertEqual(self._keys(at, "nav_"),
                         ["nav_Clients", "nav_Dashboard", "nav_Plan", "nav_Advisor notes",
                          "nav_Money", "nav_AI Assistant"])
        labels = [at.button(key=k).label for k in self._keys(at, "nav_")]
        self.assertEqual(labels, ["Your clients", "Portfolio", "Plan", "Advisor notes", "Money",
                                  "Ask Northwend"])
        # no Life for an advisor: their own records stay on Account
        self.assertNotIn("tab_Life", self._keys(at, "tab_"))
        self.assertEqual(at.selectbox(key="viewing_select").value, self.dave)
        # the client's own Get started and login are in the viewing bar
        self.assertEqual(at.button(key="viewing_start").label, "Get started")
        self.assertEqual(set(self._popovers(at)), {"pt_add", "pt_me", "pt_client_login"})
        at.button(key="viewing_start").click()
        at.run()
        self.assertEqual(at.session_state["page"], "Get started")
        self.assertEqual(at.query_params["page"], "get-started")
        # her own portfolio: no Notes, no client tools; Add client is on Your clients
        at = self._run(self.carol, "carol", None, two_step_ok=self.carol_ok)
        self.assertEqual(at.session_state["page"], "Clients")
        self.assertNotIn("nav_Advisor notes", self._keys(at, "nav_"))
        self.assertEqual(self._keys(at, "viewing_"), [])
        self.assertIn("add_client", self._keys(at, "add_"))
        at.text_input(key="new_client_name").input("Erin Park")
        at.button(key="add_client").click()
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertTrue(any("Added Erin Park" in s.value for s in at.success))
        # she stays on Your clients (to add the next one), with a way into the new account
        self.assertEqual(at.session_state["active_user_id"], self.carol)
        at.button(key="client_msg_open").click()
        at.run()
        self.assertNotEqual(at.session_state["active_user_id"], self.carol)
        self.assertEqual(at.session_state["page"], "Dashboard")

    def test_menus_close_and_mark_the_page_for_screen_readers(self):
        with open(os.path.join(REPO, "ui_enhancements.js"), encoding="utf-8") as fh:
            js = fh.read()
        for sel in (".st-key-pt_add", ".st-key-pt_me", 'aria-current", "page"',
                    '"navigation"', ".st-key-pt_money_tabs"):
            self.assertIn(sel, js)
        self.assertIn('.st-key-pt_menu [class*="st-key-nav"] button', js)
        # Streamlit's own sidebar isn't used: its handle and click-away stay gone
        self.assertNotIn("stSidebar", js)
        self.assertNotIn("pt-sb-handle", js)

    @staticmethod
    def _nodes(at):
        """Every node on the page (an AppTest, or a node: everything under it)."""
        found, todo = [], [getattr(at, "_tree", at)]
        while todo:
            node = todo.pop()
            found.append(node)
            todo.extend(getattr(node, "children", {}).values()
                        if isinstance(getattr(node, "children", None), dict) else [])
        return found

    @classmethod
    def _block_keys(cls, at):
        """The keys of every keyed container on the page (or under a node)."""
        ids = ((getattr(getattr(n, "proto", None), "id", "") or "") for n in cls._nodes(at))
        return [pid.rsplit("-", 1)[-1] for pid in ids if "-" in pid]

    def test_the_blue_band_is_only_on_pages_that_opt_in(self):
        # The deep blue band (dashboard._band_css) is drawn only on the main
        # area ui_enhancements.js marks while a band container is there:
        # Home's tall one, the one slim one on Plan, Money's pages, Learn,
        # Life and Ask Northwend - never on sign-in, the agree box or any
        # other page
        bands = ("pt_home_band", "pt_page_band")
        want = {"home": "pt_home_band", "plan": "pt_page_band", "income": "pt_page_band",
                "activity": "pt_page_band", "watchlist": "pt_page_band",
                "learn": "pt_page_band", "life": "pt_page_band",
                "ask-northwend": "pt_page_band",
                "about": None, "account": None}
        for page, band in want.items():
            at = self._run(self.alice, "alice", page)
            keys = self._block_keys(at)
            self.assertEqual([k for k in bands if k in keys], [band] if band else [], page)
            if band:
                # the one-time agree box (alice hasn't agreed) is above the
                # band, never on it
                self.assertIn("pt_agree", keys, page)
                inside = next(n for n in self._nodes(at)
                              if (getattr(getattr(n, "proto", None), "id", "") or "")
                              .endswith("-" + band))
                self.assertNotIn("pt_agree", self._block_keys(inside), page)
        # a ticker's own page (?page=ticker&t=VTI) is on the slim band too
        at = self._run(self.alice, "alice", "ticker", ticker_sym="VTI", ticker_from="Dashboard")
        self.assertEqual([k for k in bands if k in self._block_keys(at)], ["pt_page_band"])
        self.assertEqual(at.title[0].value, "VTI")
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        at.run()   # signed out: the sign-in screen
        self.assertFalse(at.exception)
        self.assertIn("Northwend", [t.value for t in at.title])
        self.assertFalse(set(bands) & set(self._block_keys(at)))
        with open(os.path.join(REPO, "dashboard.py"), encoding="utf-8") as fh:
            src = fh.read()
        css = src[src.index("def _band_css"):src.index("st.html(_band_css())")]
        # every rule that paints the band needs the mark (or a band's container)
        self.assertIn("_BAND_ON = '[data-testid=\"stMainBlockContainer\"][data-pt-band]'", src)
        self.assertNotIn("stMainBlockContainer", css)
        with open(os.path.join(REPO, "ui_enhancements.js"), encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn('.st-key-pt_home_band', js)
        self.assertIn('.st-key-pt_page_band', js)
        self.assertIn('removeAttribute("data-pt-band")', js)
        self.assertNotIn("pt_slim", js + src)   # one slim band, not two

    def test_life_is_an_investors_page(self):
        at = self._run(self.alice, "alice", "home")
        at.button(key="nav_Life").click()
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertEqual(at.session_state["page"], "Life")
        self.assertEqual(at.query_params["page"], "life")
        self.assertEqual(at.title[0].value, "Life")
        self.assertEqual(self._current(at, "nav_"), ["nav_Life"])
        self.assertEqual(self._current(at, "tab_"), ["tab_Life"])
        # a link to it opens it
        at = self._run(self.alice, "alice", "life")
        self.assertEqual(at.session_state["page"], "Life")
        # a managed client has it too, before Your advisor
        at = self._run(self.dave, "dave", "life")
        self.assertEqual(at.session_state["page"], "Life")
        self.assertEqual(self._keys(at, "nav_"), [*INVESTOR, "nav_Advisor notes"])

    def test_no_life_for_an_advisor(self):
        for state in ({}, {"active_user_id": self.dave}):
            at = self._run(self.carol, "carol", "life", two_step_ok=self.carol_ok, **state)
            self.assertNotEqual(at.session_state["page"], "Life")
            self.assertNotIn("nav_Life", self._keys(at, "nav_"))
            self.assertNotIn("tab_Life", self._keys(at, "tab_"))

    def test_route_progress_at_the_foot_of_the_menu(self):
        # bob is new: Learn is his route, and the menu says how far along
        at = self._run(self.bob, "bob", "about")
        words = " ".join(str(h.proto.body) for h in at.get("html"))
        self.assertIn("Learn · step 1 of 6", words)
        nxt = at.button(key="side_route_next")
        self.assertEqual(nxt.label, "Next: About you")
        nxt.click()
        at.run()
        self.assertEqual(at.session_state["page"], "Get started")
        self.assertEqual(at.session_state["gs_at"], "profile")
        # never for an advisor, or in a client's account
        at = self._run(self.carol, "carol", "about", two_step_ok=self.carol_ok,
                       active_user_id=self.dave)
        self.assertNotIn("side_route_next", self._keys(at, "side_"))
        at = self._run(self.dave, "dave", "about")
        self.assertNotIn("side_route_next", self._keys(at, "side_"))


if __name__ == "__main__":
    unittest.main()
