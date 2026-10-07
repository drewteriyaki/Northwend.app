"""Principle tests on the real app (PLAN 1a.10; audit 1.1e and 1.2a), with
streamlit's AppTest on a scratch database:

- An advisor or an admin signed in with their password but without passing
  two-step sign-in in this tab (no `two_step_ok`) sees only the two-step
  page - on every page they ask for in the address, with or without a
  ?client=. One who hasn't set two-step up sees only its setup page.
- `?client=<an id that isn't yours>` - another investor, another advisor's
  client - falls back to the viewer's own account and shows nothing of the
  other person's. (A real client of the advisor still opens: the control.)

    python -m unittest tests.test_principle_pages        (from the repo root)
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

SECRET_MARK = "ZEDSECRET"      # in the other people's holdings and names
SECRET_TICKER = "ZQXJ"
SECRET_FIG = 987654.32

# every ?page= the app knows (PAGE_LABELS / OLD_SLUGS), and some it doesn't
SLUGS = ("", "home", "portfolio", "dashboard", "clients", "your-clients", "plan",
         "advisor-notes", "your-advisor", "money", "income", "activity", "watchlist",
         "ask-northwend", "ask-sage", "ai-assistant", "get-started", "learn", "account",
         "about", "admin", "advisor-preview", "no-such-page")


def _secret_holdings(c, uid):
    acct = f"{SECRET_MARK} IRA ...999"
    row = {col: None for col in portfolio.POSITION_COLS}
    row.update(snapshot_date="2026-09-30", account=acct, symbol=SECRET_TICKER,
               description=f"{SECRET_MARK} Growth Fund", asset_type="ETF", quantity=100.0,
               cost_basis=SECRET_FIG, market_value=SECRET_FIG)
    portfolio.write_snapshot(c, uid, {"snapshot_date": "2026-09-30", "as_of_text": None},
                             [row], {acct: {"cash_value": SECRET_FIG,
                                            "reported_cost_basis": None,
                                            "reported_market_value": None,
                                            "reported_gain": None,
                                            "reported_gain_pct": None}}, "zed.csv")


def _walk(node):
    """Every node of AppTest's element tree (a block's children are a dict)."""
    yield node
    for child in (getattr(node, "children", None) or {}).values():
        yield from _walk(child)


class AccessPages(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.db = os.path.join(cls.tmp, "access.db")
        cls.env = unittest.mock.patch.dict(os.environ, {
            "PORTFOLIO_DB": cls.db, "MAIL_DRY_RUN": "1"})
        cls.env.start()
        for key in ("ANTHROPIC_API_KEY", "FINNHUB_API_KEY", "RESEND_API_KEY",
                    "NORTHWEND_ADMINS"):
            os.environ.pop(key, None)
        c = portfolio.connect(cls.db)
        try:
            cls.alice = auth.create_user(c, "alice", "pw-123456789")     # an investor
            sample_data.load(c, cls.alice)
            cls.bob = auth.create_user(c, "bob", "pw-123456789")         # another investor
            _secret_holdings(c, cls.bob)
            auth.set_display_name(c, cls.bob, f"{SECRET_MARK} Bob")
            cls.carol = auth.create_user(c, "carol", "pw-123456789")     # an advisor
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dana = auth.create_client(c, cls.carol, "dana", name="Dana Lee")  # her client
            sample_data.load(c, cls.dana)
            cls.omar = auth.create_user(c, "omar", "pw-123456789")       # another advisor
            auth.set_advisor(c, "omar", True)
            cls.zed = auth.create_client(c, cls.omar, "zed", name=f"{SECRET_MARK} Zed")
            _secret_holdings(c, cls.zed)
            cls.ann = auth.create_user(c, "ann", "pw-123456789")         # an admin
            secret = two_step.new_secret()
            two_step.enable(c, cls.ann, secret, two_step.totp(secret))
            cls.ann_ok = f"{cls.ann}:{two_step.status(c, cls.ann)['stamp']}"
            cls.newadv = auth.create_user(c, "newadv", "pw-123456789")   # no two-step yet
            auth.set_advisor(c, "newadv", True)
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        cls.env.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _run(self, user_id, username, page=None, client=None, **state):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        at.session_state["user_id"] = user_id
        at.session_state["username"] = username
        at.session_state["auto_backfilled"] = True   # no Yahoo history fetch from Home
        for k, v in state.items():
            at.session_state[k] = v
        if page:
            at.query_params["page"] = page
        if client is not None:
            at.query_params["client"] = str(client)
        at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        return at

    @staticmethod
    def _everything(at) -> str:
        """Every element's content as drawn, tables included."""
        return "\n".join(str(getattr(n, "proto", "")) for n in _walk(at._tree))

    def _only_the_gate(self, at, setup=False):
        keys = [w.key or "" for w in at.button] + [w.key or "" for w in at.text_input]
        self.assertEqual([k for k in keys if k.startswith(("nav_", "tab_", "menu_", "pt_"))], [])
        self.assertEqual(len(at.get("popover")), 0)
        if setup:
            self.assertIn("two_step_setup_out", keys)
            self.assertIn("One more step to keep accounts safe",
                          [s.value for s in at.subheader])
        else:
            self.assertIn("two_step_code", keys)
            self.assertIn("two_step_code_out", keys)
            self.assertEqual([s.value for s in at.subheader], ["Enter your code"])
        drawn = self._everything(at)
        for text in (SECRET_MARK, SECRET_TICKER, "Dana Lee", "Your clients"):
            self.assertNotIn(text, drawn)
        self.assertNotIn("active_user_id", at.session_state)

    # ---- 1.1e: the two-step gate --------------------------------------------- #
    def test_an_advisor_without_two_step_ok_sees_only_the_code_page(self):
        tries = [(slug, None) for slug in SLUGS] + [
            (slug, self.dana) for slug in ("", "home", "clients", "advisor-notes", "plan")]
        for slug, client in tries:
            with self.subTest(page=slug, client=client):
                self._only_the_gate(self._run(self.carol, "carol", slug, client))
        # a pass from another login, or from before two-step changed, isn't one
        for stale in (self.ann_ok, f"{self.carol}:None", f"{self.carol}:2001-01-01"):
            with self.subTest(two_step_ok=stale):
                self._only_the_gate(self._run(self.carol, "carol", "clients",
                                              two_step_ok=stale))

    def test_an_admin_without_two_step_ok_sees_only_the_code_page(self):
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_ADMINS": "ann"}):
            for slug in SLUGS:
                with self.subTest(page=slug):
                    self._only_the_gate(self._run(self.ann, "ann", slug))
            # the control: with the pass, the Admin page opens
            at = self._run(self.ann, "ann", "admin", two_step_ok=self.ann_ok)
            self.assertEqual(at.session_state["page"], "Admin")

    def test_an_advisor_without_two_step_sees_only_its_setup(self):
        for slug in ("", "clients", "home", "plan", "account", "admin"):
            with self.subTest(page=slug):
                self._only_the_gate(self._run(self.newadv, "newadv", slug, self.dana),
                                    setup=True)

    # ---- 1.2a: ?client= that isn't yours ------------------------------------- #
    def _falls_back(self, at, own_id):
        self.assertEqual(at.session_state["active_user_id"], own_id)
        self.assertNotIn("client", at.query_params)   # the address drops it
        drawn = self._everything(at)
        for text in (SECRET_MARK, SECRET_TICKER, "987,654", "987654"):
            self.assertNotIn(text, drawn)
        return drawn

    def test_the_check_sees_what_is_drawn(self):
        # the control for _everything(): the other person's holdings, opened
        # by someone who may see them, are found
        at = self._run(self.omar, "omar", "home", self.zed, two_step_ok=None)
        self._only_the_gate(at, setup=True)       # omar hasn't set two-step up
        at = self._run(self.zed, "zed", "home")
        self.assertIn(SECRET_TICKER, self._everything(at))

    def test_an_investor_cant_open_another_investors_account(self):
        for slug in ("home", "plan"):
            for other in (self.bob, self.zed, self.dana, self.carol):
                with self.subTest(page=slug, client=other):
                    drawn = self._falls_back(self._run(self.alice, "alice", slug, other),
                                             self.alice)
                    if slug == "home":
                        self.assertIn("VXUS", drawn)   # her own example holdings instead

    def test_an_advisor_cant_open_another_advisors_client(self):
        for slug in ("home", "advisor-notes"):
            for other in (self.zed, self.bob, self.omar):
                with self.subTest(page=slug, client=other):
                    self._falls_back(self._run(self.carol, "carol", slug, other,
                                               two_step_ok=self.carol_ok), self.carol)
        # not a number at all
        self._falls_back(self._run(self.carol, "carol", "home", "zed",
                                   two_step_ok=self.carol_ok), self.carol)
        # the control: her own client opens
        at = self._run(self.carol, "carol", "home", self.dana, two_step_ok=self.carol_ok)
        self.assertEqual(at.session_state["active_user_id"], self.dana)
        self.assertEqual(at.query_params["client"], str(self.dana))

    def test_a_client_cant_open_their_advisors_other_clients(self):
        at = self._run(self.zed, "zed", "home", self.dana)
        self.assertEqual(at.session_state["active_user_id"], self.zed)
        self.assertNotIn("Dana Lee", self._everything(at))


if __name__ == "__main__":
    unittest.main()
