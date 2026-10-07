"""Learn more links (ROADMAP S5): learn.LEARN_MORE and learn.learn_more_md()."""

import contextlib
import glob
import os
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import learn  # noqa: E402


def _view_sources():
    for path in [os.path.join(HERE, "dashboard.py"), *glob.glob(os.path.join(HERE, "views", "*.py"))]:
        with open(path, encoding="utf-8") as fh:
            yield os.path.basename(path), fh.read()


class LearnMoreTableTests(unittest.TestCase):
    def test_only_trusted_public_sites(self):
        self.assertEqual(set(learn.LEARN_MORE_SITES),
                         {"www.investor.gov", "www.finra.org", "www.consumerfinance.gov"})
        for topic, (label, url, source) in learn.LEARN_MORE.items():
            u = urlparse(url)
            self.assertEqual(u.scheme, "https", topic)
            self.assertIn(u.netloc, learn.LEARN_MORE_SITES, topic)
            self.assertEqual(source, learn.LEARN_MORE_SITES[u.netloc], topic)
            self.assertTrue(u.path and u.path != "/", topic)        # a page, not the home page
            self.assertFalse(re.search(r"[\s()\[\]<>\"']", url), topic)   # safe in a markdown link

    def test_every_topic_has_a_label(self):
        self.assertGreaterEqual(len(learn.LEARN_MORE), 10)
        for topic, entry in learn.LEARN_MORE.items():
            self.assertRegex(topic, r"^[a-z_]+$")
            self.assertEqual(len(entry), 3, topic)
            label = entry[0]
            self.assertTrue(label.strip(), topic)
            self.assertFalse(re.search(r"[\[\]*_`$<>]", label), topic)   # plain words only

    def test_the_ideas_the_app_explains_are_covered(self):
        for topic in ("index_funds", "diversification", "expense_ratios", "account_types",
                      "risk", "risk_tolerance", "asset_allocation", "compound_interest",
                      "dividends", "bonds", "etfs", "emergency_fund", "market_drops"):
            self.assertIn(topic, learn.LEARN_MORE)

    def test_never_advice(self):
        for label, _url, _source in learn.LEARN_MORE.values():
            for word in ("buy", "sell", "should"):
                self.assertNotIn(word, label.lower())

    def test_markdown_line(self):
        line = learn.learn_more_md("index_funds")
        label, url, source = learn.LEARN_MORE["index_funds"]
        self.assertIn("Learn more", line)
        self.assertIn(f"[{label}]({url})", line)
        self.assertIn(source, line)
        self.assertEqual(learn.learn_more_md("no_such_topic"), "")
        self.assertEqual(learn.learn_more_md(None), "")

    def test_pages_use_known_topics(self):
        """Every learn_more("topic") call and every *_LINKS table in the pages
        names a topic in learn.LEARN_MORE - a typo would quietly show nothing."""
        used = set()
        for name, src in _view_sources():
            for topic in re.findall(r"learn_more\(\"([a-z_]+)\"\)", src):
                used.add((name, topic))
            for body in re.findall(r"^[A-Z_]+_LINKS = \{(.*?)\}", src, re.M | re.S):
                for topic in re.findall(r":\s*\"([a-z_]+)\"", body):
                    used.add((name, topic))
        self.assertGreaterEqual(len(used), 10)
        for name, topic in used:
            self.assertIn(topic, learn.LEARN_MORE, f"{name}: {topic}")
        # and every topic is placed somewhere
        self.assertEqual(set(learn.LEARN_MORE) - {t for _, t in used}, set())


class LearnMorePageTests(unittest.TestCase):
    """The links show up where the idea is explained (AppTest, scratch DB)."""

    @classmethod
    def setUpClass(cls):
        import auth
        import portfolio
        import sample_data

        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == HERE}
        cls.dir = tempfile.mkdtemp(prefix="pt_learn_more_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        conn = portfolio.connect(cls.db)
        cls.uid = auth.create_user(conn, "alice", "pw-123456")
        sample_data.load(conn, cls.uid)
        # what Yahoo would say: BND holds bonds, VTI stocks; VTI has a yield
        for t, stock, bond in (("BND", 0.0, 0.99), ("VTI", 0.99, 0.0)):
            conn.execute("INSERT INTO security_info (ticker, name, quote_type, stock_pct, bond_pct) "
                         "VALUES (?, ?, 'ETF', ?, ?)", (t, t, stock, bond))
        conn.execute("UPDATE positions SET div_yield_pct = 1.4 WHERE symbol = 'VTI'")
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _run(self, page, **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(HERE, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": self.uid, "username": "alice", "page": page,
                     "auto_backfilled": True, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items() if k != "FINNHUB_API_KEY"}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1")
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    @staticmethod
    def _links(at):
        return " ".join(c.value for c in at.caption)

    def test_home(self):
        with self._run("Dashboard") as at:
            text = self._links(at)
            self.assertIn(learn.LEARN_MORE["diversification"][1], text)
            self.assertIn(learn.LEARN_MORE["account_types"][1], text)

    def test_learn_the_basics_window(self):
        with self._run("Get started", gs_at="basics", fs_hide=True) as at:
            at.button(key="basics_funds").click().run()
            self.assertIn(learn.LEARN_MORE["index_funds"][1], self._links(at))

    def test_ticker_page(self):
        """A holding's page: bonds for a bond fund, ETFs for another fund,
        nothing for a single stock; dividends beside a dividend yield."""
        url = {t: learn.LEARN_MORE[t][1] for t in ("bonds", "etfs", "dividends")}
        for sym, shown in (("BND", {"bonds"}), ("VTI", {"etfs", "dividends"}),
                           ("VXUS", {"etfs"}),     # no Yahoo data: the broker's type says fund
                           ("AAPL", set())):
            with self._run("Dashboard", holdings_pill=sym) as at:
                self.assertIn(f"## {sym}", [m.value for m in at.markdown])
                text = self._links(at)
                self.assertEqual({t for t, u in url.items() if u in text}, shown, sym)

    def test_plan(self):
        with self._run("Plan") as at:   # no goal yet: the goal form, Target mix below
            self.assertIn(learn.LEARN_MORE["asset_allocation"][1], self._links(at))


class LearnReadsTests(unittest.TestCase):
    """Opening a basics topic notes it for Year in review (recap.LEARN_READS) -
    only in the login's own account, never while an advisor is in a client's."""

    @classmethod
    def setUpClass(cls):
        import auth
        import portfolio
        import prefs
        import sample_data
        import two_step

        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == HERE}
        cls.dir = tempfile.mkdtemp(prefix="pt_learn_reads_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.carol = auth.create_user(c, "carol", "pw-123456789")
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dana = auth.create_user(c, "dana", "pw-123456789")
            sample_data.load(c, cls.dana)
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
    def _run(self, uid, name, **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(HERE, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": "Get started",
                     "gs_at": "basics", "fs_hide": True, "auto_backfilled": True,
                     **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY", "ANTHROPIC_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1")
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch("settings.load_env", lambda *a, **k: {}), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    def _prefs(self, uid):
        import portfolio
        import prefs
        c = portfolio.connect(self.db)
        try:
            return prefs.load(c, uid)
        finally:
            c.close()

    def test_an_advisor_in_a_clients_account_leaves_her_prefs_alone(self):
        import recap
        before = self._prefs(self.dana)
        with self._run(self.carol, "carol", two_step_ok=self.carol_ok,
                       active_user_id=self.dana) as at:
            at.button(key="basics_funds").click().run()
            self.assertIn("### :material/category: Stocks, bonds and funds",
                          [m.value for m in at.markdown])     # the window did open
        self.assertEqual(self._prefs(self.dana), before)
        self.assertEqual(self._prefs(self.carol).get(recap.LEARN_READS), None)
        # her own reading is still noted
        with self._run(self.dana, "dana") as at:
            at.button(key="basics_funds").click().run()
        self.assertIn("basics:funds", self._prefs(self.dana)[recap.LEARN_READS])

    def test_an_advisors_complete_isnt_dated_as_her_learning(self):
        """Complete this step in a client's account (an advisor's press) moves
        the route on, but isn't dated in her Year in review (LEARN_DATES)."""
        import recap
        with self._run(self.carol, "carol", two_step_ok=self.carol_ok,
                       active_user_id=self.dana) as at:
            at.button(key="gs_complete").click().run()
        saved = self._prefs(self.dana)
        self.assertIn("basics", saved.get("get_started_done") or [])
        self.assertNotIn("basics", saved.get(recap.LEARN_DATES) or {})
        # her own press is dated (the step open again first)
        import portfolio
        import prefs
        saved.pop("get_started_done")
        c = portfolio.connect(self.db)
        try:
            prefs.save(c, self.dana, saved)
        finally:
            c.close()
        with self._run(self.dana, "dana") as at:
            at.button(key="gs_complete").click().run()
        self.assertIn("basics", self._prefs(self.dana).get(recap.LEARN_DATES) or {})


if __name__ == "__main__":
    unittest.main()
