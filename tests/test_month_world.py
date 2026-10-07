"""This month's world, for your mix (ROADMAP Phase C; month_world.py,
views/month_world.py, flag month_world).

The notes are the owner's: NOTES ships empty, and every note in it must pass
the same checks the app uses (no forecast or advice words, no tickers or
fund families, official sources only, reviewed and dated) - so a bad note
fails here before it ships. A note shows in its own month and the next
only, and only once reviewed. The person's mix picks the per-class lines;
someone with no holdings sees the general paragraphs. In the app: off unless
its flag is set, inside the drill card, never while an advisor is in a
client's account, never in the AI. The one example note below is made up and
lives only in this test.

    python -m unittest tests.test_month_world        (from the repo root)
"""

import html
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from datetime import date, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import advisor  # noqa: E402
import auth  # noqa: E402
import flags  # noqa: E402
import gear  # noqa: E402
import manual_entry  # noqa: E402
import month_world as mw  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sample_data  # noqa: E402
import trail_conditions as tc  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
W = html.escape(mw.TITLE)   # the card's eyebrow, as the page has it
PROFILE = {"goal": "Build long-term wealth", "time_horizon_years": 15,
           "risk_tolerance": "moderate", "drawdown_reaction": "Hold",
           "experience": "new", "age_range": "25-34", "income_stability": "Very stable",
           "emergency_fund": "3-6 months"}


def fake(month, reviewed_on="2026-10-02", **over):
    """A made-up note - for these tests only, never in NOTES."""
    note = {"month": month,
            "title": "A made-up month, for the tests",
            "paragraphs": ["This is a made-up note for the tests. Nothing here happened.",
                           "A second made-up paragraph about an imaginary month."],
            "for_mix": {"stocks": "Made-up line about stocks.",
                        "bonds": "Made-up line about bonds.",
                        "cash": "Made-up line about cash."},
            "sources": [("A made-up source", "https://www.bls.gov/made-up-for-tests")],
            "reviewed_by": "Test reviewer",
            "reviewed_on": reviewed_on}
    note.update(over)
    return note


class NotesTests(unittest.TestCase):
    """What ships: the owner's notes, each passing every check."""

    def test_every_note_passes_the_checks_and_is_reviewed(self):
        months = [n.get("month") for n in mw.NOTES]
        self.assertEqual(len(months), len(set(months)), "one note a month")
        for n in mw.NOTES:
            with self.subTest(n.get("month")):
                self.assertEqual(mw.problems(n), [])
                self.assertTrue(mw.reviewed(n), "reviewed_by and reviewed_on")

    def test_empty_notes_show_nothing(self):
        with unittest.mock.patch.object(mw, "NOTES", []):
            self.assertIsNone(mw.current(date(2026, 10, 6)))

    def test_the_frame_words(self):
        text = mw.all_text()
        # the one place a banned word appears says there isn't one
        self.assertIn("never a forecast", mw.INTRO)
        self.assertEqual(mw.word_problems(text.replace("never a forecast", "")), [])
        self.assertNotRegex(text, r"\d")
        self.assertEqual(set(mw.CLASS_KEYS.values()) | {"Other"},
                         set(__import__("asset_classes").CLASSES))


class CheckTests(unittest.TestCase):

    def test_the_fake_note_is_fine(self):
        self.assertEqual(mw.problems(fake("2026-10")), [])

    def test_each_banned_word_is_caught(self):
        for sentence in ("Rates will stay high.", "Prices won't fall.", "Rates going to rise.",
                         "Markets expected a cut.", "The forecast was for growth.",
                         "Analysts predicted it.", "The outlook is mixed.",
                         "Savers should look at this.", "The best month in years.",
                         "Some recommended bonds.", "People buy dips.",
                         "Some sell in May.", "Now is a calm time.",
                         "Inflation’ll ease."):
            with self.subTest(sentence):
                note = fake("2026-10", paragraphs=[sentence, "A made-up second paragraph."])
                self.assertTrue(mw.problems(note), sentence)
                self.assertTrue(mw.word_problems(sentence), sentence)
        # the same in a per-class line and the title
        self.assertTrue(mw.problems(fake("2026-10", for_mix={"stocks": "Stocks should rise."})))
        self.assertTrue(mw.problems(fake("2026-10", title="What to expect")))
        # plain past facts are fine
        self.assertEqual(mw.word_problems("The CPI rose 0.3% in September, the BLS reported. "
                                          "The FOMC held its rate at its meeting."), [])

    def test_tickers_funds_and_brokerages_are_caught(self):
        for sentence in ("VTI rose last month.", "$SPY fell.", "Vanguard's fund rose.",
                         "Fidelity reported it.", "iShares funds grew."):
            with self.subTest(sentence):
                self.assertTrue(mw.word_problems(sentence), sentence)
        self.assertEqual(mw.word_problems("A money market fund pays interest."), [])
        self.assertEqual(mw.word_problems("The federal funds rate was unchanged."), [])

    def test_sources_must_be_official(self):
        self.assertTrue(mw.problems(fake("2026-10", sources=[])))
        self.assertTrue(mw.problems(fake("2026-10", sources=[("News", "https://example.com/x")])))
        self.assertTrue(mw.problems(fake("2026-10", sources=[("BLS", "http://www.bls.gov/x")])))
        self.assertTrue(mw.problems(fake("2026-10", sources=["https://www.bls.gov/x"])))
        for site in mw.OFFICIAL_SITES:
            self.assertTrue(site.endswith(".gov"), site)
            self.assertEqual(mw.problems(fake("2026-10", sources=[("x", f"https://{site}/a")])),
                             [])

    def test_shape(self):
        self.assertTrue(mw.problems(fake("2026-13")))
        self.assertTrue(mw.problems(fake("Oct 2026")))
        self.assertTrue(mw.problems(fake("2026-10", title=" ")))
        self.assertTrue(mw.problems(fake("2026-10", paragraphs=["Only one."])))
        self.assertTrue(mw.problems(fake("2026-10", paragraphs=["A."] * 5)))
        self.assertTrue(mw.problems(fake("2026-10", for_mix={"intl_stocks": "A line."})))
        self.assertTrue(mw.problems(fake("2026-10", reviewed_on="Oct 2")))
        self.assertEqual(mw.problems(fake("2026-10", for_mix={})), [])
        self.assertTrue(mw.problems("not a note"))


class WhenTests(unittest.TestCase):
    OCT = date(2026, 10, 6)

    def test_its_month_and_the_next_only(self):
        n = fake("2026-10")
        self.assertIs(mw.current(self.OCT, [n]), n)
        self.assertIs(mw.current(date(2026, 11, 30), [n]), n)       # last month's
        self.assertIsNone(mw.current(date(2026, 12, 1), [n]))       # too old
        self.assertIsNone(mw.current(date(2026, 9, 30), [fake("2026-10", "2026-09-28")]))
        # January shows December's
        dec = fake("2026-12", "2026-12-02")
        self.assertIs(mw.current(date(2027, 1, 15), [dec]), dec)
        self.assertEqual(mw.last_month(date(2027, 1, 15)), "2026-12")

    def test_this_months_before_last_months(self):
        sep, octo = fake("2026-09", "2026-09-02"), fake("2026-10")
        self.assertIs(mw.current(self.OCT, [sep, octo]), octo)
        self.assertIs(mw.current(self.OCT, [sep]), sep)

    def test_an_unreviewed_note_never_shows(self):
        for over in ({"reviewed_on": ""}, {"reviewed_by": ""}, {"reviewed_on": None},
                     {"reviewed_on": "2026-10-20"}):                  # not yet, on the 6th
            with self.subTest(over):
                self.assertIsNone(mw.current(self.OCT, [fake("2026-10", **over)]))
        self.assertIsNotNone(mw.current(date(2026, 10, 20),
                                        [fake("2026-10", reviewed_on="2026-10-20")]))

    def test_a_note_failing_a_check_never_shows(self):
        bad = fake("2026-10", paragraphs=["Rates will fall.", "A second paragraph."])
        self.assertIsNone(mw.current(self.OCT, [bad]))


class MixTests(unittest.TestCase):

    def test_the_largest_class_or_two(self):
        n = fake("2026-10")
        self.assertEqual(mw.lines_for(n, {"Stocks": 74.4, "Bonds": 24.6, "Cash": 1.0}),
                         [("stocks", 74, "Made-up line about stocks.")])
        self.assertEqual(mw.lines_for(n, {"Stocks": 60.2, "Bonds": 30.0, "Cash": 9.8}),
                         [("stocks", 60, "Made-up line about stocks."),
                          ("bonds", 30, "Made-up line about bonds.")])
        self.assertEqual([k for k, *_ in mw.lines_for(n, {"Cash": 80, "Stocks": 20})],
                         ["cash"])
        # "Other" has no line; a class the note has no line for is skipped
        self.assertEqual([k for k, *_ in mw.lines_for(n, {"Other": 90, "Bonds": 10})],
                         ["bonds"])
        only_stocks = fake("2026-10", for_mix={"stocks": "A stocks line."})
        self.assertEqual([k for k, *_ in mw.lines_for(only_stocks, {"Bonds": 70, "Stocks": 30})],
                         ["stocks"])
        self.assertEqual(mw.lead_of("stocks", 74),
                         "For someone with mostly stocks (about 74% of your mix)")
        # "mostly" only for the largest class over half: a smaller part says so
        self.assertEqual(mw.lead_of("bonds", 28, largest=False),
                         "For the bonds in your mix (about 28%)")
        self.assertEqual(mw.lead_of("bonds", 60, largest=False),
                         "For the bonds in your mix (about 60%)")
        self.assertEqual(mw.lead_of("stocks", 45),
                         "For the stocks in your mix (about 45%)")
        self.assertEqual(mw.lead_of("stocks", 50),
                         "For the stocks in your mix (about 50%)")

    def test_a_beginner_gets_no_lines(self):
        self.assertEqual(mw.lines_for(fake("2026-10"), None), [])
        self.assertEqual(mw.lines_for(fake("2026-10"), {}), [])


class SeenTests(unittest.TestCase):

    def test_months_only_newest_kept(self):
        p = {"other": 1}
        self.assertTrue(mw.mark_seen(p, "2026-10"))
        self.assertFalse(mw.mark_seen(p, "2026-10"))
        self.assertFalse(mw.mark_seen(p, "my words"))
        self.assertEqual(p, {"other": 1, mw.PREF: ["2026-10"]})
        self.assertTrue(mw.seen(p, "2026-10"))
        for m in range(1, 10):
            mw.mark_seen(p, f"2027-0{m}")
        self.assertEqual(len(p[mw.PREF]), mw.KEEP)
        self.assertEqual(p[mw.PREF][-1], "2027-09")
        self.assertEqual(mw.clean_seen(["2026-10", "junk", 5, "2026-13"]), ["2026-10"])
        self.assertEqual(mw.clean_seen("junk"), [])


class TrailConditionsTests(unittest.TestCase):
    OCT_MONDAY = date(2026, 10, 12)

    def _news(self, p, flag="trail_conditions,drills,month_world", notes=None):
        notes = [fake("2026-10")] if notes is None else notes
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": flag}), \
                unittest.mock.patch.object(tc.month_world, "NOTES", notes):
            return tc.news(p, self.OCT_MONDAY, None)

    def test_one_fixed_line_once_per_note(self):
        p = {}
        items = [i for i in self._news(p) if i[0] == "world"]
        self.assertEqual(items, [("world", tc.WORLD, "2026-10")])
        tc.remember(p, items, self.OCT_MONDAY)
        self.assertEqual(p[tc.PREF_WORLD], "2026-10")
        self.assertFalse([i for i in self._news(p) if i[0] == "world"])
        self.assertIn(tc.WORLD, tc.all_lines())
        self.assertIn(tc.PREF_WORLD, tc.KEYS)
        self.assertNotRegex(tc.WORLD, r"\d")

    def test_not_when_opened_empty_or_off(self):
        self.assertFalse([i for i in self._news({mw.PREF: ["2026-10"]}) if i[0] == "world"])
        self.assertFalse([i for i in self._news({}, notes=[]) if i[0] == "world"])
        self.assertFalse([i for i in self._news({}, flag="trail_conditions,drills")
                          if i[0] == "world"])
        self.assertFalse([i for i in self._news({}, flag="trail_conditions,month_world")
                          if i[0] == "world"])


class NeverSharedTests(unittest.TestCase):

    def test_never_in_the_ai_or_an_advisors_files(self):
        for name in ("advisor.py", "context_card.py", "ai_gateway.py", "ai_tools.py",
                     "ai_library.py", "ai_policy.py", "meeting.py", "reports.py",
                     "overview.py", "advising.py", "proposals.py", "weekly_email.py",
                     "client_plan.py", "intros.py",
                     os.path.join("views", "assistant.py"), os.path.join("views", "clients.py")):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                self.assertNotIn("month_world", fh.read(), name)
        with open(os.path.join(REPO, "views", "month_world.py"), encoding="utf-8") as fh:
            view = fh.read()
        for pat in (r"\bai_gateway\b", r"\badvisor\.\w", r"\b_ai_", r"\b_ask_", r"\bmailer\b",
                    r"\bsend_"):
            self.assertNotRegex(view, pat)

    def test_the_flag_is_off_unless_set_and_owns_the_view(self):
        self.assertEqual(flags.FEATURES["month_world"], {"gates": (), "view": "month_world"})
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": ""}), \
                unittest.mock.patch.object(flags, "_secret", lambda name: None):
            self.assertFalse(flags.on("month_world"))
            self.assertFalse(flags.view_on("month_world"))

    def test_privacy_words_runbook_and_the_gate_row(self):
        import disclosures
        text = " ".join(body for _t, body in disclosures.SECTIONS)
        self.assertIn("this month's world", text)
        for name in ("privacy-policy.md", "privacy-policy-DRAFT.md"):
            with open(os.path.join(REPO, "docs", "legal", name), encoding="utf-8") as fh:
                self.assertIn("Where this month's world is offered", fh.read(), name)
        with open(os.path.join(REPO, "docs", "LEGAL_GATES.md"), encoding="utf-8") as fh:
            self.assertIn("flag `month_world`", fh.read())
        with open(os.path.join(REPO, "docs", "RUNBOOK.md"), encoding="utf-8") as fh:
            runbook = fh.read()
        self.assertIn("## Writing this month's world", runbook)
        cal = runbook.split("\n## Calendar\n", 1)[1].split("\n## ", 1)[0]
        self.assertIn("Write this month's world", cal)


# --------------------------------------------------------------------------- #
# in the app
# --------------------------------------------------------------------------- #
class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_month_world_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        cls.today = date.today()
        cls.note = fake(mw.month_of(cls.today), reviewed_on=cls.today.isoformat())
        seen = {"first_steps": {"done": True}, "gear_seen": list(gear.KEYS)}
        c = portfolio.connect(cls.db)
        try:
            # a beginner: no money invested yet
            cls.bea = auth.create_user(c, "bea", PW)
            advisor.save_profile(c, cls.bea, PROFILE)
            prefs.save(c, cls.bea, dict(seen))
            # an investor: about two thirds stocks, one third bonds
            cls.ivy = auth.create_user(c, "ivy", PW)
            advisor.save_profile(c, cls.ivy, PROFILE)
            meta, rows, totals, _ = manual_entry.build(
                [{"account": "Brokerage", "symbol": "VTI", "quantity": 10, "cost_basis": 2500.0,
                  "asset_type": "Equity"},
                 {"account": "Brokerage", "symbol": "BND", "quantity": 15, "cost_basis": 1500.0,
                  "asset_type": "Fixed Income"}],
                {"Brokerage": 50.0}, {"VTI": {"price": 300.0}, "BND": {"price": 100.0}},
                today=cls.today - timedelta(days=3))
            portfolio.write_snapshot(c, cls.ivy, meta, rows, totals, manual_entry.SOURCE)
            prefs.save(c, cls.ivy, dict(seen))
            # an advisor and her client
            cls.carol = auth.create_user(c, "carol", PW)
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dana = auth.create_user(c, "dana", PW)
            sample_data.load(c, cls.dana)
            auth.link_client(c, cls.carol, cls.dana)
            prefs.save(c, cls.dana, dict(seen))
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _run(self, at, notes):
        """Run with `notes` as NOTES in whichever month_world module the app
        is using (codefresh may load a fresh one on its first run)."""
        def once():
            mod = sys.modules.get("month_world") or mw
            with unittest.mock.patch.object(mod, "NOTES", notes):
                at.run()
            return mod
        mod = once()
        if sys.modules.get("month_world") is not mod:   # reloaded during that run
            once()
        self.assertEqual([e.message for e in at.exception], [])
        return at

    def _app(self, uid, name, flag="drills,month_world", notes=None, **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": "Dashboard",
                     "auto_backfilled": True, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                   NORTHWEND_FLAGS=flag)
        patches = (unittest.mock.patch.dict(os.environ, env, clear=True),
                   unittest.mock.patch.object(yfinance, "Ticker", offline),
                   unittest.mock.patch("socket.socket.connect", offline_net.connect))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return self._run(at, [self.note] if notes is None else notes)

    @staticmethod
    def _text(at):
        parts = [m.value for m in at.markdown]
        parts += [str(e.value) for e in at.caption]
        parts += [h.proto.body for h in at.get("html")]
        parts += [b.label for b in at.button]
        return " ".join(parts)

    def _prefs(self, uid):
        c = portfolio.connect(self.db)
        try:
            return prefs.load(c, uid)
        finally:
            c.close()

    def test_off_unless_set(self):
        at = self._app(self.bea, "bea", flag="drills")
        self.assertIn("This week's drill", self._text(at))
        self.assertNotIn(W, self._text(at))
        self.assertNotIn("world_open_btn", [b.key for b in at.button])

    def test_empty_notes_show_nothing(self):
        at = self._app(self.bea, "bea", notes=[])
        self.assertIn("This week's drill", self._text(at))
        self.assertNotIn(W, self._text(at))

    def test_an_unreviewed_note_never_shows(self):
        at = self._app(self.bea, "bea", notes=[dict(self.note, reviewed_on="")])
        self.assertNotIn(W, self._text(at))

    def test_a_beginner_sees_the_general_paragraphs(self):
        at = self._app(self.bea, "bea")
        text = self._text(at)
        self.assertIn(W, text)
        self.assertIn(self.note["title"], text)
        self.assertNotIn(self.note["paragraphs"][0], text)     # closed: one line
        at.button(key="world_open_btn").click()
        text = self._text(self._run(at, [self.note]))
        for para in self.note["paragraphs"]:
            self.assertIn(para, text)
        self.assertIn(mw.GENERAL_ONLY, text)
        self.assertNotIn("% of your mix", text)
        self.assertIn(mw.NOT_ADVICE, text)
        self.assertIn("https://www.bls.gov/made-up-for-tests", text)
        self.assertEqual(self._prefs(self.bea)[mw.PREF], [self.note["month"]])

    def test_her_mix_picks_the_lines(self):
        at = self._app(self.ivy, "ivy")
        at.button(key="world_open_btn").click()
        text = self._text(self._run(at, [self.note]))
        self.assertRegex(text, r"For someone with mostly stocks \(about \d{1,3}% of your mix\)")
        self.assertRegex(text, r"For the bonds in your mix \(about \d{1,3}%\)")
        self.assertNotIn("mostly bonds", text)
        self.assertIn("Made-up line about stocks.", text)
        self.assertIn("Made-up line about bonds.", text)
        self.assertNotIn("Made-up line about cash.", text)
        self.assertNotIn(mw.GENERAL_ONLY, text)

    def test_never_while_an_advisor_is_in_a_clients_account(self):
        before = self._prefs(self.dana)
        at = self._app(self.carol, "carol", two_step_ok=self.carol_ok, active_user_id=self.dana)
        self.assertNotIn(W, self._text(at))
        self.assertNotIn("world_open_btn", [b.key for b in at.button])
        self.assertEqual(self._prefs(self.dana), before)
        # in her own account she has it
        at = self._app(self.dana, "dana")
        self.assertIn(W, self._text(at))


if __name__ == "__main__":
    unittest.main()
