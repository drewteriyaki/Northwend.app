"""The Life page (views/life.py): the paperwork side of money in one place -
cards for the account map, Lost & Found and Explain it to someone, then
Trail Forks, the Inheritance Rehearsal and those three sections. Each keeps
its own flag and its own rules (the login's own only); Account keeps only
account things and points to Life. Life is an individual's page: an advisor
has none, and keeps their own copies of these on Account.

    python -m unittest tests.test_life        (from the repo root)
"""

import contextlib
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import auth  # noqa: E402
import explain_share as xs  # noqa: E402
import inheritance_rehearsal as ir  # noqa: E402
import portfolio  # noqa: E402
import sample_data  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
ALL = "lost_found,trail_forks,inheritance_rehearsal,explain_share"
SECTIONS = ["Account map", "Lost & Found", "Trail Forks", ir.TITLE, xs.OWNER_TITLE]


class LifeTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_life_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.alice = auth.create_user(c, "alice", PW)
            sample_data.load(c, cls.alice)
            cls.carol = auth.create_user(c, "carol", PW)        # an advisor
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dana = auth.create_user(c, "dana", PW)          # her client
            auth.link_client(c, cls.carol, cls.dana)
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _app(self, uid, name, page, flag=ALL, **state):
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
    def _subheaders(at):
        return [str(s.value) for s in at.subheader]

    @staticmethod
    def _cards(at):
        """The cards along the top of Life, by their titles."""
        bodies = " ".join(str(h.proto.body) for h in at.get("html"))
        titles = {"account_map": "Account map", "lost_found": "Lost &amp; Found",
                  "explain_share": xs.OWNER_TITLE}
        return {k for k, t in titles.items() if f"<div class='pt-life-title'>{t}</div>" in bodies}

    def test_every_section_on_life_and_none_on_account(self):
        with self._app(self.alice, "alice", "Life") as at:
            self.assertEqual(at.session_state["page"], "Life")
            heads = self._subheaders(at)
            for title in SECTIONS:
                self.assertIn(title, heads)
            # the order their words expect: Trail Forks just above the
            # Rehearsal; the account map above Lost & Found
            self.assertLess(heads.index("Trail Forks"), heads.index(ir.TITLE))
            self.assertLess(heads.index("Account map"), heads.index("Lost & Found"))
            self.assertEqual(self._cards(at), {"account_map", "lost_found", "explain_share"})
            links = " ".join(m.value for m in at.markdown)
            for anchor in ("#account-map", "#lost-and-found", "#explain-it"):
                self.assertIn(f"({anchor})", links)
        with self._app(self.alice, "alice", "Account") as at:
            heads = self._subheaders(at)
            for title in SECTIONS:
                self.assertNotIn(title, heads)
            for key in ("xs_make", "lf_clear", "tf_clear", "amap_clear"):
                self.assertNotIn(key, [b.key for b in at.button])
            # what stays: account things - and a way to Life
            for title in ("Your name", "Email", "Password and devices", "Your data",
                          "Delete your account"):
                self.assertIn(title, heads)
            at.button(key="acct_open_life").click().run()
            self.assertEqual(at.session_state["page"], "Life")

    def test_a_card_only_where_its_section_is(self):
        # every flag off: the account map (no flag) is all there is
        with self._app(self.alice, "alice", "Life", flag="") as at:
            self.assertEqual(self._cards(at), {"account_map"})
            self.assertEqual([h for h in self._subheaders(at) if h in SECTIONS],
                             ["Account map"])
        # an advisor's client can't make share links: no card for it
        with self._app(self.dana, "dana", "Life") as at:
            self.assertEqual(at.session_state["page"], "Life")
            self.assertEqual(self._cards(at), {"account_map", "lost_found"})
            self.assertNotIn(xs.OWNER_TITLE, self._subheaders(at))

    def test_an_advisor_has_no_life_and_keeps_their_own_on_account(self):
        with self._app(self.carol, "carol", "Life", two_step_ok=self.carol_ok) as at:
            self.assertNotEqual(at.session_state["page"], "Life")
        with self._app(self.carol, "carol", "Account", two_step_ok=self.carol_ok) as at:
            heads = self._subheaders(at)
            for title in SECTIONS:
                self.assertIn(title, heads)
            self.assertNotIn("acct_open_life", [b.key for b in at.button])
        # in a client's account: only the advisor's own account map, never the client's
        with self._app(self.carol, "carol", "Account", two_step_ok=self.carol_ok,
                       active_user_id=self.dana) as at:
            heads = self._subheaders(at)
            for title in SECTIONS[1:]:
                self.assertNotIn(title, heads)


if __name__ == "__main__":
    unittest.main()
