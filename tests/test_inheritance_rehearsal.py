"""The Inheritance Rehearsal (ROADMAP "Someday" -> built; inheritance_rehearsal.py,
views/inheritance_rehearsal.py, flag inheritance_rehearsal).

The story is clearly made up and gentle from its first line; the words never
tell, rank, rush or grade; no figures, ages, deadlines or time limits (a
deadline is only ever asked about); no real firm is named; every link goes to
an official site (trail_forks.OFFICIAL_SITES); what's kept is step keys and
the day finished in the person's own settings, never what was tapped. In the
app: off unless its flag is set, the whole walk-through start to finish, the
end's pointers (Trail Forks only where it's on), the login's own only (never
while an advisor is in a client's account), nothing reaches the AI or an
advisor's client record.

    python -m unittest tests.test_inheritance_rehearsal        (from the repo root)
"""

import contextlib
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock
from datetime import date, datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import auth  # noqa: E402
import disclosures  # noqa: E402
import export  # noqa: E402
import flags  # noqa: E402
import inheritance_rehearsal as ir  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sample_data  # noqa: E402
import trail_forks  # noqa: E402
import two_step  # noqa: E402
import whats_new  # noqa: E402

PW = "pw-123456789"
# words that tell, rank, recommend, rush or grade - never in the content
NEVER = (r"\bshould", r"\bbest\b", r"\brecommend", r"\bmust\b", r"\burgent", r"\btop\b",
         r"\bbetter\b", r"\bworst\b", r"\bact now\b", r"\bhurry\b", r"\bdon't wait\b",
         r"\byou need to\b", r"\bimmediately\b", r"\bright now\b", r"\bguarantee",
         r"\bcorrect\b", r"\bwrong answer\b", r"\bscore", r"\bgrade\b", r"\bmistake")
# the only digits the content may show: names of accounts and forms
ALLOWED_NUMBERS = (r"401\(k\)", r"Form 1099", r"Publication \d+", r"en-\d+")


def _code_words(path):
    """A source file's text without its comment lines (lower case)."""
    with open(path, encoding="utf-8") as fh:
        return "\n".join(line for line in fh.read().lower().splitlines()
                         if not line.lstrip().startswith("#"))


class ContentTests(unittest.TestCase):

    def test_a_short_story_of_situations_and_taps(self):
        self.assertTrue(6 <= len(ir.STEPS) <= 10)
        self.assertEqual(len(ir.STEP_KEYS), len(set(ir.STEP_KEYS)))
        for s in ir.STEPS:
            self.assertRegex(s["key"], r"^[a-z0-9_]+$")
            self.assertTrue(s["title"] and s["situation"], s["key"])
            choices = ir.choices_of(s["key"])
            self.assertTrue(2 <= len(choices) <= 3, s["key"])
            self.assertEqual(len({k for k, _ in choices}), len(choices))
            for k, _words in choices:
                note = ir.note_of(s["key"], k)
                self.assertTrue(note, (s["key"], k))
            self.assertIsNone(ir.note_of(s["key"], "nope"))
        # the story's own beats, in order
        keys = ir.STEP_KEYS
        self.assertEqual(keys[0], "what_exists")
        self.assertEqual(keys[-1], "yourself")
        for beat in ("who_first", "papers", "beneficiaries", "inherited_ira", "not_rush"):
            self.assertIn(beat, keys)

    def test_gentle_and_clearly_made_up_from_the_first_line(self):
        self.assertTrue(ir.INTRO.startswith(
            "This is a practice run with a made-up family, so you'll know what to expect if it "
            "ever happens for real."))
        self.assertIn("made-up parent", ir.FAMILY)
        self.assertIn("Nothing is graded", ir.INTRO)
        self.assertIn("made up", ir.NOT_ADVICE)
        for scary in ("scam", "fraud", "beware", "warning", "penalt", "lose everything",
                      "too late"):
            self.assertNotIn(scary, ir.all_text().lower())

    def test_no_telling_ranking_or_grading_words(self):
        for where, text in (("inheritance_rehearsal.py", ir.all_text().lower()),
                            ("views/inheritance_rehearsal.py",
                             _code_words(os.path.join(REPO, "views",
                                                      "inheritance_rehearsal.py")))):
            for pat in NEVER:
                self.assertNotRegex(text, pat, (where, pat))
        entry = next(e for e in whats_new.ENTRIES if e["title"] == "The Inheritance Rehearsal")
        self.assertEqual(entry["items"][0]["flag"], "inheritance_rehearsal")
        for pat in NEVER:
            self.assertNotRegex(entry["items"][0]["text"].lower(), pat)

    def test_no_figures_ages_deadlines_or_time_limits(self):
        text = ir.all_text()
        self.assertNotRegex(text, r"\$")
        self.assertNotRegex(text, r"%")
        rest = text
        for allowed in ALLOWED_NUMBERS:
            rest = re.sub(allowed, "", rest)
        self.assertNotRegex(rest, r"\d", "a number crept in")
        low = text.lower()
        self.assertNotRegex(low, r"\b(one|two|three|four|five|six|seven|eight|nine|ten|"
                                 r"twelve|thirty|sixty|ninety|hundred)\b[\s-]*"
                                 r"(day|week|month|year)")
        self.assertNotRegex(low, r"\bwithin\b|\bby (the )?(end|date)\b|\bseventies\b|"
                                 r"\beighties\b|\byears old\b|\bage of\b")
        # a deadline is only ever asked about, never stated
        for line in text.splitlines():
            if "deadline" in line.lower():
                self.assertIn("are there any deadlines?", line.lower(), line)
        self.assertIn("are there any deadlines?", low)
        # papers are what's often asked for: ask what they need
        self.assertIn("Ask what they need", ir.step_text("papers"))
        self.assertIn("inherited IRA", ir.step_text("inherited_ira"))

    def test_only_official_links(self):
        self.assertIs(ir.OFFICIAL_SITES, trail_forks.OFFICIAL_SITES)
        links = ir.links()
        self.assertTrue(links)
        for label, url in links:
            self.assertTrue(url.startswith("https://"), url)
            self.assertIn(ir.host(url), trail_forks.OFFICIAL_SITES, (label, url))
        for name in ("inheritance_rehearsal.py",
                     os.path.join("views", "inheritance_rehearsal.py")):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                for url in re.findall(r"https?://[^\s\"')]+", fh.read()):
                    self.assertIn(ir.host(url), trail_forks.OFFICIAL_SITES, (name, url))

    def test_never_names_a_real_firm_or_fund(self):
        import brokerages
        text = ir.all_text()
        for broker, _url in brokerages.BROKERAGES:
            self.assertNotIn(broker.replace("*", ""), text)
        self.assertNotRegex(text, r"\b[A-Z]{3,5}X\b")   # a fund ticker
        self.assertIn("a brokerage", text)

    def test_the_end_points_gently_to_the_map_and_trail_forks(self):
        self.assertEqual(ir.END_LINKS["account_map"][0], "Make your own account map")
        self.assertEqual(ir.END_LINKS["trail_forks"][0], "Trail Forks: the death of a parent")
        with open(os.path.join(REPO, "views", "inheritance_rehearsal.py"),
                  encoding="utf-8") as fh:
            view = fh.read()
        self.assertIn('flags.on("trail_forks")', view)
        self.assertIn("parent_death", trail_forks.BY_KEY)


class KeptTests(unittest.TestCase):

    def test_steps_and_the_day_finished_only(self):
        p = ir.with_step({"other": 1}, "papers")
        p = ir.with_step(p, "what_exists")
        p = ir.with_step(p, "papers")   # twice is once
        self.assertEqual(p, {"other": 1, ir.PREF: {"done": ["what_exists", "papers"]}})
        p = ir.with_finished(p, date(2026, 10, 6))
        self.assertEqual(ir.finished_on(p[ir.PREF]), date(2026, 10, 6))
        self.assertEqual(ir.done_steps(p[ir.PREF]), ["what_exists", "papers"])
        self.assertEqual(ir.cleared(p), {"other": 1})
        self.assertEqual(ir.with_step({}, "lottery"), {})

    def test_anything_else_is_dropped(self):
        saved = {"done": ["papers", "free text", 3], "finished": "not a date",
                 "tapped": {"papers": "letters"}, "note": "Pat is my dad"}
        self.assertEqual(ir.clean_saved(saved), {"done": ["papers"]})
        self.assertEqual(ir.clean_saved("junk"), {"done": []})
        self.assertIsNone(ir.finished_on(saved))
        p = ir.with_step({ir.PREF: saved}, "yourself")
        self.assertEqual(set(p[ir.PREF]), {"done"})


class NeverSharedTests(unittest.TestCase):

    def test_never_in_the_ai_or_an_advisors_files(self):
        for name in ("advisor.py", "context_card.py", "ai_gateway.py", "ai_tools.py",
                     "ai_library.py", "meeting.py", "reports.py", "overview.py",
                     "advising.py", "proposals.py", "weekly_email.py", "client_plan.py",
                     "export.py", os.path.join("views", "assistant.py"),
                     os.path.join("views", "clients.py"), os.path.join("views", "meeting.py"),
                     os.path.join("views", "reports.py")):
            path = os.path.join(REPO, name)
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8") as fh:
                self.assertNotIn("inheritance_rehearsal", fh.read(), name)
        with open(os.path.join(REPO, "views", "inheritance_rehearsal.py"),
                  encoding="utf-8") as fh:
            view = fh.read()
        for pat in (r"\bai_gateway\b", r"\badvisor\.\w", r"\bcoach_prompt\b", r"\b_ai_",
                    r"st\.text_input", r"st\.text_area", r"st\.chat_input"):
            self.assertNotRegex(view, pat)

    def test_the_flag_is_off_unless_set_and_owns_the_view(self):
        self.assertEqual(flags.FEATURES["inheritance_rehearsal"],
                         {"gates": (), "view": "inheritance_rehearsal"})
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": ""}), \
                unittest.mock.patch.object(flags, "_secret", lambda name: None):
            self.assertFalse(flags.on("inheritance_rehearsal"))
            self.assertFalse(flags.view_on("inheritance_rehearsal"))
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": "inheritance_rehearsal"}):
            self.assertTrue(flags.on("inheritance_rehearsal"))

    def test_the_privacy_words_say_so(self):
        text = " ".join(body for _title, body in disclosures.SECTIONS)
        self.assertRegex(text, r"their Inheritance\s+Rehearsal")
        self.assertIn("the Inheritance Rehearsal's steps you've walked through", text)
        for name in ("privacy-policy.md", "privacy-policy-DRAFT.md"):
            with open(os.path.join(REPO, "docs", "legal", name), encoding="utf-8") as fh:
                policy = fh.read()
            self.assertIn("Where the Inheritance Rehearsal is offered", policy, name)
            self.assertIn("your Inheritance Rehearsal", policy, name)


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
        cls.dir = tempfile.mkdtemp(prefix="pt_inheritance_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.alice = auth.create_user(c, "alice", PW)
            sample_data.load(c, cls.alice)
            cls.carol = auth.create_user(c, "carol", PW)
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            prefs.save(c, cls.carol, {"advisor_card": {"name": "Carol Reyes",
                                                       "firm": "Reyes Wealth"}})
            cls.dana = auth.create_user(c, "dana", PW)
            auth.link_client(c, cls.carol, cls.dana)
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _app(self, uid, name, flag="inheritance_rehearsal", page="Life", **state):
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
    def _text(at):
        parts = [m.value for m in at.markdown]
        for kind in ("caption", "subheader"):
            parts += [str(e.value) for e in getattr(at, kind)]
        parts += [b.label for b in at.button]
        return " ".join(parts)

    @staticmethod
    def _ir_buttons(at):
        return [b.key for b in at.button if str(b.key).startswith("ir_")]

    def _prefs(self, uid):
        c = portfolio.connect(self.db)
        try:
            return prefs.load(c, uid)
        finally:
            c.close()

    def _dump(self):
        c = sqlite3.connect(self.db)
        try:
            return set(c.iterdump())
        finally:
            c.close()

    def test_off_unless_set(self):
        with self._app(self.alice, "alice", flag="") as at:
            self.assertNotIn(ir.TITLE, self._text(at))
            self.assertFalse(self._ir_buttons(at))

    def test_the_whole_walk_through_kept_as_keys(self):
        before = self._dump()
        with self._app(self.alice, "alice") as at:
            text = self._text(at)
            self.assertIn(ir.TITLE, text)
            self.assertIn(ir.INTRO, text)
            self.assertIn(ir.NOT_ADVICE, text)
            self.assertEqual(self._ir_buttons(at), ["ir_start"])
            at.button(key="ir_start").click().run()
            self.assertIn(ir.FAMILY, self._text(at))
            for i, s in enumerate(ir.STEPS):
                key = s["key"]
                text = self._text(at)
                self.assertIn(f"Step {i + 1} of {len(ir.STEPS)}", text)
                self.assertIn(s["situation"], text)
                for _choice, words in ir.choices_of(key):
                    self.assertIn(words, text)
                # tap the last choice (no choice is the right one)
                choice = ir.choices_of(key)[-1][0]
                at.button(key=f"ir_tap_btn_{key}_{choice}").click().run()
                text = self._text(at)
                self.assertIn(ir.note_of(key, choice), text)
                self.assertIn(ir.NOTE_LEAD, text)
                for _label, url in s["links"]:
                    self.assertIn(url, text)
                at.button(key=f"ir_next_{key}").click().run()
            text = self._text(at)
            self.assertIn(ir.END_TITLE, text)
            self.assertIn(ir.END_LINKS["account_map"][0], text)
            self.assertNotIn(ir.END_LINKS["trail_forks"][0], text)   # its flag is off
            at.button(key="ir_close").click().run()
            text = self._text(at)
            self.assertIn("You finished the practice run on", text)
            self.assertIn(ir.AGAIN, text)
            self.assertIn("ir_clear", self._ir_buttons(at))
        kept = self._prefs(self.alice)[ir.PREF]
        self.assertEqual(kept, {"done": list(ir.STEP_KEYS),
                                "finished": datetime.now().date().isoformat()})
        # only her settings changed (and the sign-in)
        changed = {line.split('"')[1] for line in self._dump() ^ before
                   if line.startswith("INSERT")}
        self.assertLessEqual(changed, {"user_prefs", "login_sessions", "users"}, changed)
        # in her own export, as one of her settings
        c = portfolio.connect(self.db)
        try:
            self.assertIn("inheritance_rehearsal", str(export.collect(c, self.alice)["settings"]))
        finally:
            c.close()
        # cleared
        with self._app(self.alice, "alice") as at:
            at.button(key="ir_clear").click().run()
            self.assertIn("Your practice run was cleared.", self._text(at))
        self.assertNotIn(ir.PREF, self._prefs(self.alice))

    def test_leaving_part_way_keeps_the_steps_so_far(self):
        with self._app(self.dana, "dana") as at:
            at.button(key="ir_start").click().run()
            at.button(key="ir_tap_btn_what_exists_a_list").click().run()
            at.button(key="ir_leave_what_exists").click().run()
            self.assertIn(f"1 of {len(ir.STEPS)} steps", self._text(at))
            self.assertEqual(self._prefs(self.dana)[ir.PREF], {"done": ["what_exists"]})
        # never in her advisor's record of her
        c = portfolio.connect(self.db)
        try:
            self.assertNotIn("inheritance_rehearsal",
                             str(export.client_record(c, self.carol, self.dana)))
        finally:
            c.close()

    def test_the_end_points_to_trail_forks_where_its_on(self):
        with self._app(self.alice, "alice", flag="inheritance_rehearsal,trail_forks",
                       ir_step="end") as at:
            text = self._text(at)
            self.assertIn(ir.END_LINKS["trail_forks"][0], text)
            self.assertIn("(#trail-forks)", text)
            self.assertIn(ir.END_LINKS["account_map"][0], text)

    def test_never_while_an_advisor_is_in_a_clients_account(self):
        c = portfolio.connect(self.db)
        try:
            prefs.save(c, self.dana, ir.with_step(prefs.load(c, self.dana), "papers"))
        finally:
            c.close()
        before = self._prefs(self.dana)
        for page in ("Account", "Life"):   # (no Life in a client's account: her portfolio)
            with self._app(self.carol, "carol", page=page, two_step_ok=self.carol_ok,
                           active_user_id=self.dana) as at:
                text = self._text(at)
                self.assertNotIn(ir.TITLE, text)
                self.assertFalse(self._ir_buttons(at))
        self.assertEqual(self._prefs(self.dana), before)
        # on her own portfolio she has it on Life, as an individual would - not on Account
        with self._app(self.carol, "carol", page="Life", two_step_ok=self.carol_ok) as at:
            self.assertIn(ir.TITLE, [str(h.value) for h in at.subheader])
        with self._app(self.carol, "carol", page="Account", two_step_ok=self.carol_ok) as at:
            self.assertNotIn(ir.TITLE, [str(h.value) for h in at.subheader])


if __name__ == "__main__":
    unittest.main()
