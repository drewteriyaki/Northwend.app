"""Lost & Found (ROADMAP R9; lost_found.py, views/lost_found.py, flag
lost_found).

The words never rank or recommend, every link goes to an official site
(lost_found.OFFICIAL_SITES), brokerages come only from brokerages.py in
alphabetical order, no dollar figures or deadlines are invented; the
checklist is kept in the person's own settings, statuses only; and in the
app: off unless its flag is set, the login's own only (never while an
advisor is in a client's account), a client of an advisor sees a line about
their advisor instead of the brokerages, nothing reaches the AI or an
advisor's client record.

    python -m unittest tests.test_lost_found        (from the repo root)
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

import auth  # noqa: E402
import brokerages  # noqa: E402
import export  # noqa: E402
import flags  # noqa: E402
import lost_found as lf  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sample_data  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
# the account map's own short guide (views/account_map.py), when the flag is off
OLD_GUIDE = "Money can get left behind when you change jobs"
# ranking, recommending and urgent words that must never appear
NEVER = (r"\bbest\b", r"\bshould roll\b", r"\brecommend", r"\btop\b", r"\bcheapest\b",
         r"\byou should\b", r"\bbetter\b", r"\bworst\b", r"\burgent", r"\bact now\b",
         r"\bhurry\b", r"\bdon't wait\b", r"\bdeadline\b")


def _code_words(path):
    """A source file's text without its comment lines (lower case)."""
    with open(path, encoding="utf-8") as fh:
        return "\n".join(line for line in fh.read().lower().splitlines()
                         if not line.lstrip().startswith("#"))


class ContentTests(unittest.TestCase):

    def test_no_ranking_or_recommending_words(self):
        for where, text in (("lost_found.py", lf.all_text().lower()),
                            ("views/lost_found.py",
                             _code_words(os.path.join(REPO, "views", "lost_found.py")))):
            for pat in NEVER:
                self.assertNotRegex(text, pat, (where, pat))

    def test_only_official_links(self):
        for host in lf.OFFICIAL_SITES:
            self.assertTrue(host.endswith(".gov") or host in (
                "unclaimed.org", "www.missingmoney.com", "brokercheck.finra.org"), host)
        links = lf.links()
        self.assertTrue(links)
        for label, url in links:
            self.assertTrue(url.startswith("https://"), url)
            self.assertIn(lf.host(url), lf.OFFICIAL_SITES, (label, url))
        # every address written in the module or the page is one of them
        for name in ("lost_found.py", os.path.join("views", "lost_found.py")):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                for url in re.findall(r"https?://[^\s\"')]+", fh.read()):
                    self.assertIn(lf.host(url), lf.OFFICIAL_SITES, (name, url))
        # the old 401(k) search is the Department of Labor's own
        self.assertIn(("Retirement Savings Lost and Found (U.S. Department of Labor)",
                       "https://lostandfound.dol.gov/"), links)

    def test_no_invented_figures_or_deadlines(self):
        text = lf.all_text()
        self.assertNotRegex(text, r"\$\s?\d")
        self.assertNotRegex(text, r"\d\s*%")
        self.assertNotRegex(text, r"\b\d+\s*(day|week|month|year)s?\b")
        self.assertNotRegex(text, r"\bage \d|\b59|\b55\b|\b73\b")

    def test_the_choices_side_by_side_never_one(self):
        titles = [t for t, _ in lf.OPTIONS]
        self.assertEqual(titles, ["Leave it in the old plan",
                                  "Move it to your new employer's plan",
                                  "Move it to an IRA", "Cash it out"])
        self.assertIn("in no particular order", lf.OPTIONS_INTRO)
        self.assertIn("Northwend doesn't suggest one", lf.OPTIONS_INTRO)
        cash = dict(lf.OPTIONS)["Cash it out"]
        self.assertIn("income", cash)
        self.assertIn("early-withdrawal tax", cash)
        self.assertTrue(all(q.endswith("?") for q in lf.QUESTIONS))
        self.assertIn("plan administrator", lf.QUESTIONS_LEAD)
        self.assertIn("Educational, not advice", lf.NOT_ADVICE)
        self.assertIn("free", lf.NOT_ADVICE)

    def test_searching_is_free_said_calmly(self):
        unclaimed = next(s for s in lf.SECTIONS if s[0] == "unclaimed")
        words = " ".join(unclaimed[3])
        self.assertIn("free", words)
        self.assertIn("You never need one", words)
        for scary in ("scam", "fraud", "beware", "warning"):
            self.assertNotIn(scary, lf.all_text().lower())

    def test_brokerages_only_from_brokerages_py_alphabetical(self):
        names = [n for n, _ in brokerages.BROKERAGES]
        self.assertEqual(names, sorted(names, key=brokerages.sort_key))
        # the module and the page name none themselves - only brokerages.py's list
        for name in ("lost_found.py", os.path.join("views", "lost_found.py")):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                text = fh.read()
            for broker in names:
                self.assertNotIn(broker, text, (name, broker))
        with open(os.path.join(REPO, "views", "lost_found.py"), encoding="utf-8") as fh:
            view = fh.read()
        self.assertIn("brokerages.list_markdown()", view)
        self.assertIn("brokerages.NOT_RANKED", view)
        self.assertIn(brokerages.LIST_INTRO, lf.IRA_LEAD)

    def test_never_asks_for_numbers(self):
        self.assertIn("Social Security number", lf.PRIVATE)
        self.assertIn("never for Northwend", " ".join(lf.SECTIONS[0][5]))
        self.assertIn("last 3 digits at most", lf.FOUND_NEXT)


class ChecklistTests(unittest.TestCase):
    DAY = date(2026, 10, 6)

    def test_a_status_is_kept_with_the_day(self):
        p = lf.with_status({"other": 1}, "dol", "found", self.DAY)
        self.assertEqual(p, {"other": 1, lf.PREF: {"places": {"dol": "found"},
                                                   "on": "2026-10-06"}})
        p = lf.with_status(p, "states", "looking", self.DAY)
        self.assertEqual(lf.status_of(p[lf.PREF], "states"), "looking")
        self.assertEqual(lf.summary(p[lf.PREF]),
                         {"looked": 2, "of": len(lf.PLACES), "found": 1, "looking": 1,
                          "none": 0})

    def test_not_yet_clears_and_an_empty_list_leaves_no_key(self):
        p = lf.with_status({}, "bonds", "none", self.DAY)
        p = lf.with_status(p, "bonds", lf.NOT_YET, self.DAY)
        self.assertEqual(p, {})
        p = lf.with_status({"x": 1}, "bonds", "none", self.DAY)
        self.assertEqual(lf.cleared(p), {"x": 1})

    def test_unknown_places_statuses_and_junk_are_dropped(self):
        self.assertEqual(lf.with_status({}, "nowhere", "found", self.DAY), {})
        self.assertEqual(lf.with_status({}, "dol", "$5,000 found", self.DAY), {})
        saved = {"places": {"dol": "found", "x": "found", "iras": "1234"}, "on": "nope",
                 "amount": 5000}
        self.assertEqual(lf.clean_saved(saved), {"places": {"dol": "found"}, "on": None})
        self.assertEqual(lf.clean_saved("junk"), {"places": {}, "on": None})
        # only statuses are ever kept: no amounts, numbers or names
        p = lf.with_status({lf.PREF: saved}, "pbgc", "looking", self.DAY)
        self.assertEqual(set(p[lf.PREF]), {"places", "on"})
        self.assertLessEqual(set(p[lf.PREF]["places"].values()), set(lf.STATUSES))

    def test_every_place_has_a_label_and_the_match_is_one(self):
        self.assertEqual(len(lf.PLACE_KEYS), len(set(lf.PLACE_KEYS)))
        self.assertIn("match", lf.PLACE_KEYS)


class NeverSharedTests(unittest.TestCase):

    def test_never_in_the_ai_or_an_advisors_files(self):
        for name in ("advisor.py", "context_card.py", "ai_gateway.py", "ai_tools.py",
                     "ai_library.py", "meeting.py", "reports.py", "overview.py",
                     "advising.py", "proposals.py", "weekly_email.py", "client_plan.py",
                     "export.py", os.path.join("views", "assistant.py"),
                     os.path.join("views", "clients.py"), os.path.join("views", "meeting.py"),
                     os.path.join("views", "reports.py")):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("lost_found", text, name)
        with open(os.path.join(REPO, "views", "lost_found.py"), encoding="utf-8") as fh:
            view = fh.read()
        for pat in (r"\bai_gateway\b", r"\badvisor\.\w", r"\bcoach_prompt\b", r"\b_ai_"):
            self.assertNotRegex(view, pat)

    def test_the_flag_is_off_unless_set_and_owns_the_view(self):
        self.assertEqual(flags.FEATURES["lost_found"], {"gates": (), "view": "lost_found"})
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": ""}), \
                unittest.mock.patch.object(flags, "_secret", lambda name: None):
            self.assertFalse(flags.on("lost_found"))
            self.assertFalse(flags.view_on("lost_found"))
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": "lost_found"}):
            self.assertTrue(flags.on("lost_found"))


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
        cls.dir = tempfile.mkdtemp(prefix="pt_lost_found_")
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
    def _app(self, uid, name, flag="lost_found", **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": "Account",
                     "auto_backfilled": True, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                   NORTHWEND_FLAGS=flag)
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    @staticmethod
    def _text(at):
        parts = [m.value for m in at.markdown]
        for kind in ("caption", "subheader"):
            parts += [str(e.value) for e in getattr(at, kind)]
        return " ".join(parts)

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

    def test_off_unless_set_the_short_guide_stays(self):
        with self._app(self.alice, "alice", flag="") as at:
            text = self._text(at)
            self.assertNotIn("Lost & Found", text)
            self.assertIn(OLD_GUIDE, text)              # the account map's short guide
            self.assertNotIn("lf_match_open", [b.key for b in at.button])
            self.assertFalse([s for s in at.selectbox if str(s.key).startswith("lf_")])

    def test_where_to_look_and_her_own_list(self):
        before = self._dump()
        with self._app(self.alice, "alice") as at:
            text = self._text(at)
            self.assertIn("Lost & Found", text)
            self.assertNotIn(OLD_GUIDE, text)           # Lost & Found takes its place
            for _key, _title, _icon, paras, _links, _ready in lf.SECTIONS:
                for para in paras:
                    self.assertIn(para, text)
            self.assertIn(lf.OPTIONS_INTRO, text)
            self.assertIn("https://lostandfound.dol.gov/", text)
            self.assertIn(brokerages.list_markdown(), text)      # alphabetical, from brokerages.py
            self.assertIn(brokerages.NOT_RANKED, text)
            self.assertIn(lf.NOT_ADVICE, text)
            self.assertIn("lf_match_open", [b.key for b in at.button])
            self.assertNotIn("Found something?", text)
            at.selectbox(key="lf_place_dol").set_value(lf.STATUSES["found"]).run()
            at.selectbox(key="lf_place_states").set_value(
                lf.STATUSES["looking"]).run()
            text = self._text(at)
            self.assertIn("Looked in 2 of", text)
            self.assertIn("Found something?", text)
            keys = [b.key for b in at.button]
            self.assertIn("lf_add_import", keys)
            self.assertIn("lf_add_manual", keys)
        kept = self._prefs(self.alice)[lf.PREF]
        self.assertEqual(kept["places"], {"dol": "found", "states": "looking"})
        self.assertEqual(set(kept), {"places", "on"})
        # only her settings changed (and the sign-in)
        changed = {line.split('"')[1] for line in self._dump() ^ before
                   if line.startswith("INSERT")}
        self.assertLessEqual(changed, {"user_prefs", "login_sessions", "users"}, changed)
        # in her own export, as one of her settings
        c = portfolio.connect(self.db)
        try:
            self.assertIn("lost_found", str(export.collect(c, self.alice)["settings"]))
        finally:
            c.close()
        # cleared
        with self._app(self.alice, "alice") as at:
            self.assertEqual(at.selectbox(key="lf_place_dol").value, lf.STATUSES["found"])
            at.button(key="lf_clear").click().run()
            self.assertIn("Your list was cleared.", self._text(at))
        self.assertNotIn(lf.PREF, self._prefs(self.alice))

    def test_a_client_sees_it_with_her_advisor_not_brokerages(self):
        with self._app(self.dana, "dana") as at:
            text = self._text(at)
            self.assertIn("Lost & Found", text)
            self.assertIn("Your advisor, Carol Reyes", text)
            for name, _url in brokerages.BROKERAGES:
                self.assertNotIn(name.replace("*", "\\*"), text)
            at.selectbox(key="lf_place_iras").set_value(lf.STATUSES["found"]).run()
        self.assertEqual(self._prefs(self.dana)[lf.PREF]["places"], {"iras": "found"})
        # never in her advisor's record of her
        c = portfolio.connect(self.db)
        try:
            self.assertNotIn("lost_found", str(export.client_record(c, self.carol, self.dana)))
        finally:
            c.close()

    def test_never_while_an_advisor_is_in_a_clients_account(self):
        c = portfolio.connect(self.db)
        try:
            prefs.save(c, self.dana, lf.with_status({}, "bonds", "found"))
        finally:
            c.close()
        before = self._prefs(self.dana)
        with self._app(self.carol, "carol", two_step_ok=self.carol_ok,
                       active_user_id=self.dana) as at:
            text = self._text(at)
            self.assertNotIn("Lost & Found", text)
            self.assertNotIn("Places I've looked", text)
            self.assertFalse([s for s in at.selectbox if str(s.key).startswith("lf_")])
        self.assertEqual(self._prefs(self.dana), before)
        # in her own account she has it, as an individual would
        with self._app(self.carol, "carol", two_step_ok=self.carol_ok) as at:
            self.assertIn("Lost & Found", self._text(at))


if __name__ == "__main__":
    unittest.main()
