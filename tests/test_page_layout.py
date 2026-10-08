"""Plan and Money in two parts under the slim band (Style C).

Plan: the goal card and the tab groups in the middle, "Your mix", the next
deposit and the stress test on the right - each opens its tab. Money: the
tab's content in one card, the accounts (and on Income the year ahead) on
the right, from what's already loaded. One column without holdings; hidden
amounts stay hidden, a percentages portfolio shows shares rather than
dollars, and an advisor in a client's account sees the same. Every fixed
line passes the conclusion policy.

    python -m unittest tests.test_page_layout        (from the repo root)
"""

import contextlib
import os
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from datetime import date

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import ai_policy  # noqa: E402
import auth  # noqa: E402
import manual_entry  # noqa: E402
import plans  # noqa: E402
import portfolio  # noqa: E402
import sample_data  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
BANNED = ("should", "best", "recommend", "buy", "sell", "rebalance", "will", "expect",
          "predict", "forecast", "urgent")
PLAN_PARTS = ("pt_page_band", "pt_page_layout", "pt_page_main", "pt_page_side",
              "pt_plan_goal", "pt_plan_tabs", "pt_plan_mix", "pt_plan_stress")
MONEY_PARTS = ("pt_page_band", "pt_page_layout", "pt_page_main", "pt_money_card",
               "pt_page_side", "pt_money_accounts")


def _source(name):
    with open(os.path.join(REPO, name), encoding="utf-8") as fh:
        return fh.read()


class WordingTests(unittest.TestCase):

    def test_every_fixed_line_passes_the_conclusion_policy(self):
        lines = re.findall(r'^(?:PLAN_(?:MIX|DEPOSIT|STRESS)\w*) = "([^"]+)"',
                           _source(os.path.join("views", "plan.py")), re.M)
        lines += re.findall(r'^MONEY_(?:ACCOUNTS|INCOME)\w* = "([^"]+)"',
                            _source("dashboard.py"), re.M)
        self.assertGreaterEqual(len(lines), 10)
        for line in lines:
            with self.subTest(line=line):
                self.assertEqual(ai_policy.findings(line), [])
                for word in BANNED:
                    self.assertNotRegex(line.lower(), rf"\b{word}\b")

    def test_the_phone_and_wide_rules(self):
        src = _source("dashboard.py")
        css = src[src.index("/* The slim band pages in two parts"):src.index("/* Life's cards")]
        self.assertIn("flex: 0 0 19rem", css)
        narrow = css[css.index("@media (max-width: 900px)"):css.index("@media (max-width: 640px)")]
        self.assertIn("flex-direction: column", narrow)
        self.assertIn("width: 100% !important", narrow)
        # the slim band is its own rule, behind the band's mark
        band = src[src.index("def _band_css"):src.index("st.html(_band_css())")]
        self.assertIn('[data-pt-band="slim"]', band)
        self.assertIn(".st-key-pt_page_band", src)


class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_pages_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        snap = date.today().isoformat()
        rows, totals = sample_data.snapshot_rows(snap)
        c = portfolio.connect(cls.db)
        try:
            cls.alice = auth.create_user(c, "alice", PW)
            portfolio.write_snapshot(c, cls.alice, {"snapshot_date": snap, "as_of_text": "t"},
                                     rows, totals, "alice.csv")
            plans.save_plan(c, cls.alice, {"goal_type": "Retirement", "target_amount": 250000,
                                           "target_date": "2046-01-01",
                                           "monthly_contribution": 500,
                                           "target_alloc": {"Stocks": 40, "Bonds": 50,
                                                            "Cash": 10}}, set_by=cls.alice)
            cls.frank = auth.create_user(c, "frank", PW)   # percentages only
            portfolio.write_snapshot(c, cls.frank, {"snapshot_date": snap, "as_of_text": "t"},
                                     rows, totals, manual_entry.PCT_SOURCE)
            cls.carol = auth.create_user(c, "carol", PW)
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dana = auth.create_user(c, "dana", PW)
            portfolio.write_snapshot(c, cls.dana, {"snapshot_date": snap, "as_of_text": "t"},
                                     rows, totals, "dana.csv")
            auth.link_client(c, cls.carol, cls.dana)
            cls.erin = auth.create_user(c, "erin", PW)   # nothing in her account
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _app(self, uid, name, page, **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")

        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": page,
                     "auto_backfilled": True, "fs_hide": True, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused")
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline_net.connect):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    @staticmethod
    def _nodes(at):
        found, todo = [], [getattr(at, "_tree", at)]
        while todo:
            node = todo.pop()
            found.append(node)
            todo.extend(getattr(node, "children", {}).values()
                        if isinstance(getattr(node, "children", None), dict) else [])
        return found

    def _keys(self, at):
        ids = ((getattr(getattr(n, "proto", None), "id", "") or "") for n in self._nodes(at))
        return [pid.rsplit("-", 1)[-1] for pid in ids if "-" in pid]

    def _side_html(self, at):
        side = next(n for n in self._nodes(at)
                    if (getattr(getattr(n, "proto", None), "id", "") or "")
                    .endswith("-pt_page_side"))
        return " ".join(getattr(n.proto, "body", "") for n in self._nodes(side)
                        if getattr(n, "type", "") == "html")

    @staticmethod
    def _text(markup):
        return re.sub(r"<[^>]+>", " ", markup)

    def test_plan_in_two_parts(self):
        with self._app(self.alice, "alice", "Plan") as at:
            keys = self._keys(at)
            for k in PLAN_PARTS:
                self.assertIn(k, keys)
            self.assertNotIn("pt_home_band", keys)
            side = self._text(self._side_html(at))
            self.assertIn("Your mix", side)
            self.assertIn("points under your target", side)
            self.assertRegex(side, r"\d+%")
            # every tab is still drawn, in its three groups
            labels = [t.label for t in at.tabs]
            for name in ("Your plan", "What-ifs", "Money out", "Target mix", "Stress test"):
                self.assertIn(name, labels)
            # a card on the right opens its tab: the tabs are drawn afresh on it
            at.button(key="plan_side_stress").click().run()
            self.assertEqual(at.session_state["plan_tabs_n"], 1)
            self.assertIn("pt_plan_tabset", self._keys(at))
            outer = next(n for n in self._nodes(at)
                         if getattr(n, "type", "") == "tab_container"
                         and "What-ifs" in [t.label for t in n.children.values()])
            self.assertEqual(outer.proto.tab_container.default_tab_index,
                             [t.label for t in outer.children.values()].index("What-ifs"))

    def test_the_walks_way_back_stays_on_top(self):
        with self._app(self.alice, "alice", "Plan", walk_return=True) as at:
            self.assertIn("plan_back_walk", [b.key for b in at.button])

    def test_hidden_amounts_stay_hidden_on_the_right(self):
        for page in ("Plan", "Income", "Activity"):
            with self._app(self.alice, "alice", page, hide_amounts=True) as at:
                side = self._side_html(at)
                for cell in re.findall(r"<span class='pt-acct-val'>(.*?)</span>", side):
                    self.assertNotRegex(cell, r"\d", page)
                if page == "Plan":
                    # now and the points off are hidden; the targets are the person's own
                    rows = re.findall(r"<span>([^<]*)</span><span>([^<]*)</span>"
                                      r"<span>([^<]*)</span>", side)
                    self.assertTrue(rows)
                    for _kind, now, _target in rows:
                        self.assertNotRegex(now, r"\d")
                    self.assertNotRegex(self._text(side.split("pt-pmix'>")[1]
                                                   .split("</div>", 1)[1]), r"\d{1,2} points")
                self.assertNotIn("pt-inc-bars", side)

    def test_money_in_two_parts(self):
        for page in ("Income", "Activity", "Watchlist"):
            with self._app(self.alice, "alice", page) as at:
                keys = self._keys(at)
                for k in MONEY_PARTS:
                    self.assertIn(k, keys, page)
                self.assertEqual([b.key for b in at.button if (b.key or "").startswith("money_")],
                                 ["money_Income", "money_Activity", "money_Watchlist"])
                self.assertRegex(self._text(self._side_html(at)), r"\$[\d,]+")

    def test_a_percentages_portfolio_shows_shares_not_dollars(self):
        with self._app(self.frank, "frank", "Activity") as at:
            side = self._text(self._side_html(at))
            self.assertRegex(side, r"\d+%")
            self.assertNotIn("$", side)

    def test_an_advisor_in_a_clients_account(self):
        for page in ("Plan", "Income"):
            with self._app(self.carol, "carol", page, two_step_ok=self.carol_ok,
                           active_user_id=self.dana) as at:
                keys = self._keys(at)
                self.assertIn("pt_page_band", keys, page)
                self.assertIn("pt_page_side", keys, page)

    def test_nothing_held_is_one_column(self):
        with self._app(self.erin, "erin", "Plan") as at:
            keys = self._keys(at)
            self.assertIn("pt_plan_goal", keys)
            self.assertNotIn("pt_page_side", keys)
        with self._app(self.erin, "erin", "Watchlist") as at:
            keys = self._keys(at)
            self.assertIn("pt_money_card", keys)
            self.assertNotIn("pt_page_side", keys)


if __name__ == "__main__":
    unittest.main()
