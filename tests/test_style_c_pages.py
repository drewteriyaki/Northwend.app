"""Learn, Life and Ask Northwend in Style C (views/get_started.py, life.py,
assistant.py; the pt_page_layout styles in dashboard.py).

The slim navy band with the page title (key pt_page_band, the same one as
Plan and Money - tests/test_menu.py checks which pages have it), then the middle
(pt_page_main) and, on Learn and Ask, a right-hand panel (pt_page_side) that
goes under the middle up to 900px wide. Ask's "What it sees" panel says only
what the conversation's ContextCard can hold, and only the notes where
they're kept.

    python -m unittest tests.test_style_c_pages        (from the repo root)
"""

import contextlib
import dataclasses
import html
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
import context_card  # noqa: E402
import plans  # noqa: E402
import portfolio  # noqa: E402
import sample_data  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"


def _src(name):
    with open(os.path.join(REPO, name), encoding="utf-8") as fh:
        return fh.read()


class StyleTests(unittest.TestCase):

    def test_the_wide_and_phone_rules(self):
        src = _src("dashboard.py")
        css = src[src.index("/* The slim band pages in two parts"):src.index("/* Home's band (_band_css")]
        self.assertIn("flex: 0 0 19rem", css)
        self.assertIn("border-radius: 16px", css)
        self.assertIn("box-shadow: 0 12px 28px -6px #132a3e40", css)
        narrow = css[css.index("@media (max-width: 900px)"):css.index("@media (max-width: 640px)")]
        self.assertIn(".st-key-pt_page_layout { flex-direction: column !important;", narrow)
        phone = css[css.index("@media (max-width: 640px)"):]
        self.assertIn(".st-key-pt_tf_grid { grid-template-columns: minmax(0, 1fr); }", phone)
        # one slim band, drawn only where ui_enhancements.js marks it (_band_css)
        band = src[src.index("def _band_css"):src.index("def _band_css") + 6000]
        self.assertIn('[data-pt-band="slim"]', band)
        self.assertNotIn('data-pt-band="slim"', css)
        self.assertNotIn("pt_slim", src)
        self.assertNotIn("<", css.replace("</", ""))   # nothing tag-like in the comments

    def test_the_script_marks_the_slim_band(self):
        js = _src("ui_enhancements.js")
        self.assertIn(".st-key-pt_page_band", js)
        self.assertIn(".st-key-pt_page_layout", js)
        self.assertIn('"slim"', js)
        self.assertIn('removeAttribute("data-pt-band")', js)


class WhatItSeesTests(unittest.TestCase):
    """The panel's words are held to the card (context_card.ContextCard)."""

    def test_the_card_has_not_grown(self):
        # a new field on the card means the panel's words need a look
        self.assertEqual({f.name for f in dataclasses.fields(context_card.ContextCard)},
                         {"scope", "goals", "timeline", "answers", "preferences",
                          "target_return", "unknown", "stage", "mix", "target", "band",
                          "drift", "holdings", "others", "positions", "accounts", "notes",
                          "client_mode", "advisor_label"})


class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_stylec_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        snap = date.today().isoformat()
        rows, totals = sample_data.snapshot_rows(snap)
        c = portfolio.connect(cls.db)
        try:
            cls.alice = auth.create_user(c, "alice", PW)
            portfolio.write_snapshot(c, cls.alice, {"snapshot_date": snap, "as_of_text": "t"},
                                     rows, totals, "alice.csv")
            plans.save_plan(c, cls.alice, {"target_alloc": {"Stocks": 40, "Bonds": 50,
                                                            "Cash": 10}}, set_by=cls.alice)
            cls.carol = auth.create_user(c, "carol", PW)
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dana = auth.create_user(c, "dana", PW)
            portfolio.write_snapshot(c, cls.dana, {"snapshot_date": snap, "as_of_text": "t"},
                                     rows, totals, "dana.csv")
            auth.link_client(c, cls.carol, cls.dana)
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
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                   NORTHWEND_FLAGS="seasons,trail_forks,lost_found,explain_share")
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline_net.connect):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at

    @staticmethod
    def _block_keys(at):
        found, todo = [], [at._tree]
        while todo:
            node = todo.pop()
            pid = getattr(getattr(node, "proto", None), "id", "") or ""
            if "-" in pid:
                found.append(pid.rsplit("-", 1)[-1])
            todo.extend(getattr(node, "children", {}).values()
                        if isinstance(getattr(node, "children", None), dict) else [])
        return found

    @staticmethod
    def _html(at):
        return " ".join(h.proto.body for h in at.get("html"))

    def test_learn_has_the_band_the_middle_and_the_panel(self):
        with self._app(self.alice, "alice", "Get started") as at:
            keys = self._block_keys(at)
            for k in ("pt_page_band", "pt_page_layout", "pt_page_main", "pt_page_side",
                      "pt_gs_steps", "pt_season_learn", "pt_kit"):
                self.assertIn(k, keys)
            self.assertNotIn("pt_home_band", keys)
            self.assertIn("Learn", [t.value for t in at.title])
            html = self._html(at)
            self.assertIn(">This season<", html)
            self.assertIn(">Milestones<", html)
            # the route's own controls are all still there
            self.assertIn("gs_stage", [s.key for s in at.get("button_group")] +
                          [s.key for s in at.get("segmented_control")])

    def test_life_has_the_band_and_one_column(self):
        with self._app(self.alice, "alice", "Life") as at:
            keys = self._block_keys(at)
            for k in ("pt_page_band", "pt_page_layout", "pt_page_main", "pt_tf_grid",
                      "pt_life_account_map", "pt_life_lost_found"):
                self.assertIn(k, keys)
            self.assertNotIn("pt_page_side", keys)
            self.assertIn("The paperwork side of money",
                          " ".join(c.value for c in at.caption))

    def test_ask_says_what_it_sees_in_your_own_account(self):
        with self._app(self.alice, "alice", "AI Assistant") as at:
            keys = self._block_keys(at)
            for k in ("pt_page_band", "pt_page_layout", "pt_page_main", "pt_page_side",
                      "pt_ask_sees"):
                self.assertIn(k, keys)
            html = self._html(at)
            self.assertIn(">What it sees<", html)
            self.assertIn("as percentages", html)
            self.assertIn("keeps short notes", html)          # kept in their own account
            self.assertIn("Never dollar amounts", html)
            self.assertNotIn("Your advisor's name", html)     # not client mode
            self.assertIn("percentages only", " ".join(c.value for c in at.caption))
            # the chat's own pieces are where they were
            self.assertTrue(at.chat_input)
            self.assertTrue([b for b in at.button if (b.key or "").startswith("quick_")])

    def test_an_advisor_in_a_clients_account_sees_no_notes_line(self):
        with self._app(self.carol, "carol", "AI Assistant", two_step_ok=self.carol_ok,
                       active_user_id=self.dana) as at:
            html = self._html(at)
            self.assertIn("This person's answers", html)
            self.assertIn("Not their notes", html)
            self.assertNotIn("keeps short notes", html)

    def test_the_panel_words_are_calm_and_figure_free(self):
        with self._app(self.alice, "alice", "AI Assistant") as at:
            panel = [h.proto.body for h in at.get("html") if "<p class='pt-ask-sees'>" in h.proto.body]
        self.assertTrue(panel)
        text = html.unescape(re.sub(r"<[^>]+>", " ", " ".join(panel)))
        self.assertNotRegex(text, r"[$]|\d")
        self.assertEqual(ai_policy.findings(text), [])

    def test_other_pages_have_no_slim_band(self):
        for page in ("Dashboard", "About", "Account"):
            with self._app(self.alice, "alice", page) as at:
                self.assertNotIn("pt_page_band", self._block_keys(at), page)


if __name__ == "__main__":
    unittest.main()
