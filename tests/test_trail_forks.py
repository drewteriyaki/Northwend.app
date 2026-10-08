"""Trail Forks (ROADMAP R8; trail_forks.py, views/trail_forks.py, flag
trail_forks).

The words never rank, recommend or say what to do, invent no deadlines or
figures, and every link goes to an official site (trail_forks.OFFICIAL_SITES);
divorce, inheritance and a death stay with what to ask a professional and open
softly; what's kept is fork and step keys in the person's own settings, never
free text; and in the app: off unless its flag is set, the login's own only
(never while an advisor is in a client's account), each fork ends in the Walk
(or the Plan, with the walk off), nothing reaches the AI or an advisor's
client record.

    python -m unittest tests.test_trail_forks        (from the repo root)
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
from datetime import date

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import advisor  # noqa: E402
import auth  # noqa: E402
import disclosures  # noqa: E402
import export  # noqa: E402
import flags  # noqa: E402
import manual_entry  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sample_data  # noqa: E402
import trail_forks as tf  # noqa: E402
import two_step  # noqa: E402
import whats_new  # noqa: E402

PW = "pw-123456789"
# words that tell, rank, recommend or rush - never in the content
NEVER = (r"\bshould", r"\bbest\b", r"\brecommend", r"\btop\b", r"\bcheapest\b",
         r"\bbetter\b", r"\bworst\b", r"\burgent", r"\bact now\b", r"\bhurry\b",
         r"\bdon't wait\b", r"\bmust\b", r"\byou need to\b", r"\bimmediately\b",
         r"\bright now\b", r"\bguarantee")
# the only digits the content may show: names of accounts and forms
ALLOWED_NUMBERS = (r"401\(k\)", r"W-4", r"W-2", r"Topic \d+", r"Publication \d+",
                   r"en-\d+")
SENSITIVE = ("inheritance", "divorce", "parent_death")


def _code_words(path):
    """A source file's text without its comment lines (lower case)."""
    with open(path, encoding="utf-8") as fh:
        return "\n".join(line for line in fh.read().lower().splitlines()
                         if not line.lstrip().startswith("#"))


class ContentTests(unittest.TestCase):

    def test_six_forks_each_with_the_four_parts(self):
        self.assertEqual(tf.FORK_KEYS, ("new_job", "layoff", "new_baby", "inheritance",
                                        "divorce", "parent_death"))
        for f in tf.FORKS:
            for part in ("opening", "changes", "gather", "ask", "not_rush", "links"):
                self.assertTrue(f[part], (f["key"], part))
            steps = tf.steps(f["key"])
            self.assertEqual(len(steps), len(set(steps)), f["key"])   # keys unique per fork
            for step in steps:
                self.assertRegex(step, r"^[a-z0-9_]+$")
            for whom, questions in f["ask"]:
                self.assertTrue(any(whom.startswith(w) for w in tf.WHOM), whom)
                self.assertTrue(all(q.endswith("?") for _, q in questions), whom)
            for also in f["see_also"]:
                self.assertIn(also, tf.SEE_ALSO)

    def test_no_telling_ranking_or_rushing_words(self):
        for where, text in (("trail_forks.py", tf.all_text().lower()),
                            ("views/trail_forks.py",
                             _code_words(os.path.join(REPO, "views", "trail_forks.py")))):
            for pat in NEVER:
                self.assertNotRegex(text, pat, (where, pat))
        entry = next(e for e in whats_new.ENTRIES if e["title"] == "Trail Forks")
        for pat in NEVER:
            self.assertNotRegex(entry["items"][0]["text"].lower(), pat)

    def test_no_invented_deadlines_or_figures(self):
        text = tf.all_text()
        self.assertNotRegex(text, r"\$")
        self.assertNotRegex(text, r"%")
        rest = text
        for allowed in ALLOWED_NUMBERS:
            rest = re.sub(allowed, "", rest)
        self.assertNotRegex(rest, r"\d", "a number crept in")
        self.assertNotRegex(text.lower(), r"\b(one|two|three|four|five|six|seven|eight|nine|"
                                          r"ten|thirty|sixty|ninety|hundred)\b[\s-]*"
                                          r"(day|week|month|year)")
        self.assertNotRegex(text.lower(), r"\bwithin\b|\bby (the )?(end|date)\b")
        # a deadline is only ever asked about, never stated
        for line in text.splitlines():
            if "deadline" in line.lower():
                self.assertIn("are there any deadlines?", line.lower(), line)

    def test_sensitive_routes_ask_never_tell(self):
        for key in SENSITIVE:
            f = tf.BY_KEY[key]
            whom = [w for w, _ in f["ask"]]
            self.assertTrue(any(w.startswith(tf.ATTORNEY) for w in whom), key)
            self.assertTrue(any(w.startswith(tf.TAX) for w in whom), key)
            words = tf.fork_text(key).lower()
            for telling in (r"\byou can't\b", r"\bfile for\b", r"\bsue\b", r"\bcontest\b",
                            r"\bwaive\b", r"\bdisclaim\b", r"\bsign it\b"):
                self.assertNotRegex(words, telling, key)
        self.assertTrue(any(w == tf.EXECUTOR for w, _ in tf.BY_KEY["inheritance"]["ask"]))
        self.assertTrue(any(w == tf.EXECUTOR for w, _ in tf.BY_KEY["parent_death"]["ask"]))
        self.assertTrue(any(w == tf.PLAN_ADMIN for w, _ in tf.BY_KEY["divorce"]["ask"]))

    def test_soft_openings(self):
        self.assertTrue(tf.BY_KEY["parent_death"]["opening"].startswith(
            "We're sorry for your loss."))
        self.assertIn("Nothing here needs to happen today", tf.BY_KEY["parent_death"]["opening"])
        self.assertIn("go gently", tf.BY_KEY["inheritance"]["opening"])
        self.assertIn("a lot to carry", tf.BY_KEY["divorce"]["opening"])
        self.assertIn("never says what to do", tf.BY_KEY["divorce"]["opening"])
        for scary in ("scam", "fraud", "beware", "warning", "penalt", "lose everything"):
            self.assertNotIn(scary, tf.all_text().lower())

    def test_only_official_links(self):
        for host in tf.OFFICIAL_SITES:
            self.assertTrue(host.endswith(".gov"), host)
        links = tf.links()
        self.assertTrue(links)
        for label, url in links:
            self.assertTrue(url.startswith("https://"), url)
            self.assertIn(tf.host(url), tf.OFFICIAL_SITES, (label, url))
        for name in ("trail_forks.py", os.path.join("views", "trail_forks.py")):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                for url in re.findall(r"https?://[^\s\"')]+", fh.read()):
                    self.assertIn(tf.host(url), tf.OFFICIAL_SITES, (name, url))

    def test_never_names_funds_or_brokerages(self):
        import brokerages
        text = tf.all_text()
        for broker, _url in brokerages.BROKERAGES:
            self.assertNotIn(broker.replace("*", ""), text)
        self.assertNotRegex(text, r"\b[A-Z]{3,5}X\b")   # a fund ticker

    def test_each_fork_ends_in_the_walk(self):
        self.assertIn("monthly walk", tf.WALK_END)
        self.assertIn("Plan", tf.PLAN_END)
        with open(os.path.join(REPO, "views", "trail_forks.py"), encoding="utf-8") as fh:
            view = fh.read()
        self.assertIn('st.session_state["checkin_open"] = True', view)
        self.assertIn('_go("Dashboard")', view)
        self.assertIn('flags.on("walk")', view)


class KeptTests(unittest.TestCase):

    def test_marking_ticking_and_unmarking(self):
        p = tf.with_fork({"other": 1}, "layoff", True)
        self.assertEqual(p, {"other": 1, tf.PREF: {"forks": ["layoff"], "done": {}}})
        p = tf.with_step(p, "layoff", "pay_stubs", True)
        p = tf.with_step(p, "layoff", "letter", True)
        self.assertEqual(tf.done_steps(p[tf.PREF], "layoff"), ["letter", "pay_stubs"])  # in order
        self.assertEqual(tf.progress(p[tf.PREF], "layoff"), (2, len(tf.steps("layoff"))))
        p = tf.with_fork(p, "new_job", True)
        self.assertEqual(tf.mine(p[tf.PREF]), ["new_job", "layoff"])   # FORKS' order
        p = tf.with_step(p, "layoff", "letter", False)
        self.assertEqual(tf.done_steps(p[tf.PREF], "layoff"), ["pay_stubs"])
        # unmarking drops its ticks; no forks leaves no key
        p = tf.with_fork(p, "layoff", False)
        self.assertEqual(p[tf.PREF], {"forks": ["new_job"], "done": {}})
        p = tf.with_fork(p, "new_job", False)
        self.assertEqual(p, {"other": 1})
        self.assertEqual(tf.cleared(tf.with_fork({"x": 1}, "divorce", True)), {"x": 1})

    def test_only_on_a_marked_fork_and_only_known_keys(self):
        self.assertEqual(tf.with_step({}, "layoff", "letter", True), {})   # not marked
        p = tf.with_fork({}, "divorce", True)
        self.assertEqual(tf.with_step(p, "divorce", "letter", True), p)   # another fork's step
        self.assertEqual(tf.with_step(p, "divorce", "my lawyer is Bob", True), p)
        self.assertEqual(tf.with_fork({}, "lottery", True), {})
        saved = {"forks": ["divorce", "nope", 3], "done": {"divorce": ["qdro", "free text"],
                                                          "layoff": ["letter"]},
                 "note": "anything", "on": "2026-10-06"}
        self.assertEqual(tf.clean_saved(saved), {"forks": ["divorce"],
                                                 "done": {"divorce": ["qdro"]}})
        self.assertEqual(tf.clean_saved("junk"), {"forks": [], "done": {}})
        # only keys are ever kept: no text, no dates
        p = tf.with_step(tf.with_fork({tf.PREF: saved}, "divorce", True), "divorce",
                         "filing", True)
        self.assertEqual(set(p[tf.PREF]), {"forks", "done"})
        for fork, ticks in p[tf.PREF]["done"].items():
            self.assertLessEqual(set(ticks), set(tf.steps(fork)))


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
                self.assertNotIn("trail_forks", fh.read(), name)
        with open(os.path.join(REPO, "views", "trail_forks.py"), encoding="utf-8") as fh:
            view = fh.read()
        for pat in (r"\bai_gateway\b", r"\badvisor\.\w", r"\bcoach_prompt\b", r"\b_ai_",
                    r"st\.text_input", r"st\.text_area", r"st\.chat_input"):
            self.assertNotRegex(view, pat)

    def test_the_flag_is_off_unless_set_and_owns_the_view(self):
        self.assertEqual(flags.FEATURES["trail_forks"], {"gates": (), "view": "trail_forks"})
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": ""}), \
                unittest.mock.patch.object(flags, "_secret", lambda name: None):
            self.assertFalse(flags.on("trail_forks"))
            self.assertFalse(flags.view_on("trail_forks"))
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": "trail_forks"}):
            self.assertTrue(flags.on("trail_forks"))

    def test_the_privacy_words_say_so(self):
        text = " ".join(body for _title, body in disclosures.SECTIONS)
        self.assertIn("their Trail Forks", text)
        self.assertIn("Trail Forks you mark as yours", text)
        for name in ("privacy-policy.md", "privacy-policy-DRAFT.md"):
            with open(os.path.join(REPO, "docs", "legal", name), encoding="utf-8") as fh:
                policy = fh.read()
            self.assertIn("Where Trail Forks is offered", policy, name)
            self.assertRegex(policy, r"your Trail Forks[^.]*which only you see", name)


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
        cls.dir = tempfile.mkdtemp(prefix="pt_trail_forks_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.alice = auth.create_user(c, "alice", PW)
            sample_data.load(c, cls.alice)
            # wren has real holdings, so the monthly walk is hers to take
            cls.wren = auth.create_user(c, "wren", PW)
            advisor.save_profile(c, cls.wren, {
                "goal": "Build long-term wealth", "time_horizon_years": 10,
                "risk_tolerance": "moderate", "drawdown_reaction": "Hold and wait",
                "experience": "some", "age_range": "35-44", "income_stability": "Very stable",
                "emergency_fund": "3-6 months", "high_interest_debt": "None",
                "employer_match": "No match or no plan"})
            meta, rows, totals, _ = manual_entry.build(
                [{"account": "Brokerage", "symbol": "VTI", "quantity": 10,
                  "cost_basis": 2500.0, "asset_type": "Equity"}],
                {"Brokerage": 50.0}, {"VTI": {"price": 300.0}}, today=date(2026, 9, 10))
            portfolio.write_snapshot(c, cls.wren, meta, rows, totals, manual_entry.SOURCE)
            prefs.save(c, cls.wren, {"first_steps": {"done": True},
                                     "disclosures_seen": disclosures.LAST_UPDATED})
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
    def _app(self, uid, name, flag="trail_forks", page="Life", **state):
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
        parts += [e.label for e in at.expander]
        parts += [c.label for c in at.checkbox]
        return " ".join(parts)

    @staticmethod
    def _tf_boxes(at):
        return [c for c in at.checkbox if str(c.key).startswith("tf_")]

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
            self.assertNotIn("Trail Forks", self._text(at))
            self.assertFalse(self._tf_boxes(at))

    def test_her_forks_and_ticks_kept_as_keys(self):
        before = self._dump()
        with self._app(self.alice, "alice") as at:
            text = self._text(at)
            self.assertIn("Trail Forks", text)
            self.assertIn(tf.INTRO, text)
            self.assertIn(tf.NOT_ADVICE, text)
            for f in tf.FORKS:   # (an expander with an icon isn't in at.expander)
                self.assertIn(f["opening"], text)
                self.assertIn(f["not_rush"][0], text)
            self.assertIn("https://www.irs.gov/publications/p504", text)
            # before a fork is hers, its steps are a plain list - no boxes
            self.assertEqual({c.key for c in self._tf_boxes(at)},
                             {f"tf_on_{k}" for k in tf.FORK_KEYS})
            self.assertNotIn("tf_clear", [b.key for b in at.button])
            at.checkbox(key="tf_on_layoff").check().run()
            at.checkbox(key="tf_layoff_letter").check().run()
            at.checkbox(key="tf_layoff_eligible").check().run()
            text = self._text(at)
            self.assertIn(f"2 of {len(tf.steps('layoff'))} steps ticked", text)
            self.assertIn("tf_clear", [b.key for b in at.button])
            # sample data isn't real holdings: the fork ends in the Plan
            self.assertIn(tf.PLAN_END, text)
            self.assertIn("tf_plan_layoff", [b.key for b in at.button])
        kept = self._prefs(self.alice)[tf.PREF]
        self.assertEqual(kept, {"forks": ["layoff"], "done": {"layoff": ["letter", "eligible"]}})
        # only her settings changed (and the sign-in)
        changed = {line.split('"')[1] for line in self._dump() ^ before
                   if line.startswith("INSERT")}
        self.assertLessEqual(changed, {"user_prefs", "login_sessions", "users"}, changed)
        # in her own export, as one of her settings
        c = portfolio.connect(self.db)
        try:
            self.assertIn("trail_forks", str(export.collect(c, self.alice)["settings"]))
        finally:
            c.close()
        # unmarked: its ticks go too; then cleared
        with self._app(self.alice, "alice") as at:
            self.assertTrue(at.checkbox(key="tf_layoff_letter").value)
            at.checkbox(key="tf_on_new_baby").check().run()
            at.checkbox(key="tf_on_layoff").uncheck().run()
            self.assertEqual(self._prefs(self.alice)[tf.PREF],
                             {"forks": ["new_baby"], "done": {}})
            at.button(key="tf_clear").click().run()
            self.assertIn("Your marks and ticks were cleared.", self._text(at))
        self.assertNotIn(tf.PREF, self._prefs(self.alice))

    def test_the_plan_button_opens_the_plan(self):
        with self._app(self.alice, "alice") as at:
            at.button(key="tf_plan_new_job").click().run()
            self.assertEqual(at.session_state["page"], "Plan")

    def test_with_the_walk_on_each_fork_ends_in_the_walk(self):
        with self._app(self.wren, "wren", flag="trail_forks,walk") as at:
            text = self._text(at)
            self.assertIn(tf.WALK_END, text)
            keys = [b.key for b in at.button]
            for k in tf.FORK_KEYS:
                self.assertIn(f"tf_walk_{k}", keys)
                self.assertNotIn(f"tf_plan_{k}", keys)
            at.button(key="tf_walk_parent_death").click().run()
            self.assertEqual(at.session_state["page"], "Dashboard")
            self.assertTrue(at.session_state["checkin_open"])

    def test_a_client_sees_it_and_her_advisor_is_only_someone_to_ask(self):
        with self._app(self.dana, "dana") as at:
            text = self._text(at)
            self.assertIn("Trail Forks", text)
            self.assertIn("Your advisor, Carol Reyes", text)
            self.assertIn("Nothing here is shared with them", text)
            at.checkbox(key="tf_on_divorce").check().run()
            at.checkbox(key="tf_divorce_qdro").check().run()
        self.assertEqual(self._prefs(self.dana)[tf.PREF],
                         {"forks": ["divorce"], "done": {"divorce": ["qdro"]}})
        # never in her advisor's record of her
        c = portfolio.connect(self.db)
        try:
            self.assertNotIn("trail_forks", str(export.client_record(c, self.carol, self.dana)))
            self.assertNotIn("divorce", str(export.client_record(c, self.carol, self.dana)))
        finally:
            c.close()

    def test_never_while_an_advisor_is_in_a_clients_account(self):
        c = portfolio.connect(self.db)
        try:
            prefs.save(c, self.dana, tf.with_fork(prefs.load(c, self.dana), "parent_death",
                                                  True))
        finally:
            c.close()
        before = self._prefs(self.dana)
        with self._app(self.carol, "carol", page="Account", two_step_ok=self.carol_ok,
                       active_user_id=self.dana) as at:
            text = self._text(at)
            self.assertNotIn("Trail Forks", text)
            self.assertNotIn(tf.BY_KEY["parent_death"]["opening"], text)
            self.assertFalse(self._tf_boxes(at))
        self.assertEqual(self._prefs(self.dana), before)
        # in her own account she has it, as an individual would
        with self._app(self.carol, "carol", page="Account", two_step_ok=self.carol_ok) as at:
            self.assertIn("Trail Forks", self._text(at))


if __name__ == "__main__":
    unittest.main()
