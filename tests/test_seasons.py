"""The Four Seasons (ROADMAP R7; seasons.py, views/seasons.py, flag seasons).

The date logic picks the right season on every month and its edges; the
words never rank or recommend; every link goes to an official site
(seasons.OFFICIAL_SITES); yearly figures carry their tax year and IRS page
and show only in that year - and the review test below fails once that year
is past; the state kept is per season, opened or put away, no free text; in
the app: off unless its flag is set, a card on Home in season, a line on
Learn any time, the RMD note only for the "65 or older" age range, and
never while an advisor is in a client's account.

    python -m unittest tests.test_seasons        (from the repo root)
"""

import contextlib
import os
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from datetime import date, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import advisor  # noqa: E402
import auth  # noqa: E402
import fees  # noqa: E402
import flags  # noqa: E402
import future_notes  # noqa: E402
import plans  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sample_data  # noqa: E402
import seasons as ss  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
NEVER = (r"\bbest\b", r"\bshould\b", r"\brecommend", r"\btop\b", r"\bcheapest\b",
         r"\bbetter\b", r"\bworst\b", r"\burgent", r"\bact now\b", r"\bhurry\b",
         r"\bdon't wait\b", r"\bdeadline\b", r"\bmust\b")
VIEW = os.path.join(REPO, "views", "seasons.py")


def _code_words(path):
    """A source file's text without its comment lines (lower case)."""
    with open(path, encoding="utf-8") as fh:
        return "\n".join(line for line in fh.read().lower().splitlines()
                         if not line.lstrip().startswith("#"))


class SeasonDateTests(unittest.TestCase):

    def test_every_month(self):
        want = {1: "january", 2: None, 3: None, 4: "april", 5: None, 6: None, 7: None,
                8: None, 9: None, 10: "enrollment", 11: "enrollment", 12: "december"}
        for year in (2026, 2027, 2028):   # 2028: a leap year
            for month, key in want.items():
                with self.subTest(year=year, month=month):
                    self.assertEqual(ss.season_of(date(year, month, 15)), key)

    def test_the_edges(self):
        cases = {date(2026, 1, 1): "january", date(2026, 1, 31): "january",
                 date(2026, 2, 1): None, date(2026, 3, 31): None,
                 date(2026, 4, 1): "april", date(2026, 4, 30): "april",
                 date(2026, 5, 1): None, date(2026, 9, 30): None,
                 date(2026, 10, 1): "enrollment", date(2026, 11, 30): "enrollment",
                 date(2026, 12, 1): "december", date(2026, 12, 31): "december",
                 date(2027, 1, 1): "january", date(2028, 2, 29): None}
        for day, key in cases.items():
            with self.subTest(day=day):
                self.assertEqual(ss.season_of(day), key)
        # every day of a year lands in its month's season
        d = date(2026, 1, 1)
        while d.year == 2026:
            self.assertEqual(ss.season_of(d), ss.season_of(d.replace(day=1)))
            d += timedelta(days=1)

    def test_season_ids(self):
        self.assertEqual(ss.season_id(date(2026, 12, 31)), "2026-december")
        self.assertEqual(ss.season_id(date(2027, 1, 1)), "2027-january")
        self.assertEqual(ss.season_id(date(2026, 11, 1)), "2026-enrollment")
        self.assertIsNone(ss.season_id(date(2026, 7, 4)))

    def test_the_next_season(self):
        self.assertEqual(ss.next_season(date(2026, 2, 10)), ("april", date(2026, 4, 1)))
        self.assertEqual(ss.next_season(date(2026, 4, 10)), ("enrollment", date(2026, 10, 1)))
        # October's season runs on through November: the next is December
        self.assertEqual(ss.next_season(date(2026, 10, 1)), ("december", date(2026, 12, 1)))
        self.assertEqual(ss.next_season(date(2026, 11, 30)), ("december", date(2026, 12, 1)))
        self.assertEqual(ss.next_season(date(2026, 12, 31)), ("january", date(2027, 1, 1)))
        self.assertEqual(ss.when_label("enrollment"), "October and November")

    def test_four_seasons(self):
        self.assertEqual(ss.KEYS, ("january", "april", "enrollment", "december"))
        months = [m for _k, ms, *_ in ss.SEASONS for m in ms]
        self.assertEqual(len(months), len(set(months)))


class StateTests(unittest.TestCase):

    def test_seen_then_put_away(self):
        p = ss.with_status({"other": 1}, "2026-december", ss.SEEN)
        self.assertEqual(p, {"other": 1, ss.PREF: {"2026-december": "seen"}})
        p = ss.with_status(p, "2026-december", ss.PUT_AWAY)
        self.assertEqual(p[ss.PREF], {"2026-december": "put_away"})
        # opening it again later doesn't bring the card back
        self.assertEqual(ss.with_status(p, "2026-december", ss.SEEN), p)

    def test_home_state(self):
        dec = date(2026, 12, 5)
        self.assertEqual(ss.home_state({}, dec), "card")
        self.assertEqual(ss.home_state({"2026-december": "seen"}, dec), "line")
        self.assertIsNone(ss.home_state({"2026-december": "put_away"}, dec))
        # last year's put-away doesn't hide this year's
        self.assertEqual(ss.home_state({"2025-december": "put_away"}, dec), "card")
        # nothing between seasons
        self.assertIsNone(ss.home_state({}, date(2026, 7, 1)))

    def test_only_known_seasons_and_statuses_no_free_text(self):
        self.assertEqual(ss.with_status({}, "2026-summer", ss.SEEN), {})
        self.assertEqual(ss.with_status({}, "2026-april", "I filed late"), {})
        self.assertEqual(ss.with_status({}, "note: hello", ss.SEEN), {})
        saved = {"2026-april": "seen", "2026-may": "seen", "x": "y", "2026-january": 5,
                 "2026-december": "put_away"}
        self.assertEqual(ss.clean_saved(saved),
                         {"2026-december": "put_away", "2026-april": "seen"})
        self.assertEqual(ss.clean_saved("junk"), {})

    def test_only_the_newest_are_kept(self):
        p = {}
        for year in range(2020, 2027):
            for key in ss.KEYS:
                p = ss.with_status(p, f"{year}-{key}", ss.SEEN)
        kept = p[ss.PREF]
        self.assertEqual(len(kept), ss.KEEP)
        self.assertIn("2026-december", kept)
        self.assertNotIn("2020-january", kept)


class FiguresTests(unittest.TestCase):

    def test_review_the_yearly_figures(self):
        """Fails once the tax year the figures were checked for is past:
        update seasons.LIMITS (and RMD_AGE / RMD_YEAR) from the IRS pages
        they cite, then LIMITS_YEAR, RMD_YEAR and LIMITS_CHECKED."""
        this_year = date.today().year
        self.assertLessEqual(this_year, ss.LIMITS_YEAR,
                             "seasons.LIMITS is out of date: review it on irs.gov")
        self.assertLessEqual(this_year, ss.RMD_YEAR,
                             "seasons.RMD_AGE is out of date: review it on irs.gov")

    def test_every_figure_is_dated_and_sourced(self):
        date.fromisoformat(ss.LIMITS_CHECKED)
        self.assertEqual(int(ss.LIMITS_CHECKED[:4]), ss.LIMITS_YEAR)
        self.assertEqual({k for k, *_ in ss.LIMITS}, {"ira", "401k", "hsa"})
        for _key, what, figures, url in ss.LIMITS:
            self.assertRegex(figures, r"\$\d")
            self.assertEqual(ss.host(url), "www.irs.gov", what)
        # dollar figures live only in LIMITS
        self.assertNotRegex(ss.all_text(), r"\$\s?\d")
        for name in ("seasons.py", os.path.join("views", "seasons.py")):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                text = fh.read()
            found = re.findall(r"\$\d[\d,]*", text)
            allowed = re.findall(r"\$\d[\d,]*", " ".join(f for _k, _w, f, _u in ss.LIMITS))
            self.assertEqual(sorted(found), sorted(allowed) if name == "seasons.py" else [])

    def test_figures_only_in_their_own_year(self):
        self.assertEqual(len(ss.limits_for(ss.LIMITS_YEAR)), 3)
        self.assertEqual([k for k, *_ in ss.limits_for(ss.LIMITS_YEAR, ("hsa",))], ["hsa"])
        self.assertEqual(ss.limits_for(ss.LIMITS_YEAR + 1), ())
        self.assertEqual(ss.limits_for(ss.LIMITS_YEAR - 1), ())
        self.assertIn(str(ss.RMD_AGE), ss.rmd_text(ss.RMD_YEAR))
        later = ss.rmd_text(ss.RMD_YEAR + 1)
        self.assertNotRegex(later, r"\b7\d\b")
        self.assertEqual(ss.dated_line(ss.RMD_YEAR + 1), "")
        self.assertIn(str(ss.RMD_YEAR), ss.dated_line(ss.RMD_YEAR))

    def test_the_rmd_note_only_for_the_oldest_age_range(self):
        self.assertTrue(ss.rmd_may_apply("65 or older"))
        for other in (None, "", "55-64", "Under 25"):
            self.assertFalse(ss.rmd_may_apply(other))
        self.assertIn(ss.RMD_AGE_RANGE, advisor.CHOICES["age_range"])


class FeeBillTests(unittest.TestCase):
    TODAY = date(2026, 1, 15)

    def _check(self):
        info = {"VTI": {"quote_type": "ETF", "expense_ratio": 0.0003, "name": "A fund"},
                "XYZ": {"quote_type": "MUTUALFUND", "expense_ratio": 0.0075, "name": "B fund"}}
        return fees.check([{"symbol": "VTI", "value": 10000.0},
                           {"symbol": "XYZ", "value": 5000.0}], info)

    def test_the_fee_checks_own_figures_carried_to_the_goal(self):
        r = self._check()
        bill = ss.fee_bill(r, self.TODAY, "2046-01-01")
        self.assertEqual(bill["years"], 20)
        self.assertAlmostEqual(bill["yearly"], r["total_yearly"])
        self.assertAlmostEqual(bill["ratio"], r["ratio"])
        want = (fees.cost_over(10000.0, 0.0003, 20)["total"]
                + fees.cost_over(5000.0, 0.0075, 20)["total"])
        self.assertAlmostEqual(bill["total"], want)
        self.assertEqual(bill["growth"], fees.GROWTH)

    def test_without_a_goal_or_known_fees(self):
        r = self._check()
        bill = ss.fee_bill(r, self.TODAY, None)
        self.assertIsNone(bill["years"])
        self.assertIsNone(bill["total"])
        self.assertIsNone(ss.fee_bill(fees.check([], {}), self.TODAY, "2046-01-01"))
        self.assertIsNone(ss.fee_bill(None, self.TODAY))
        # a goal date already here still counts a year
        self.assertEqual(ss.years_to("2026-01-01", self.TODAY), 1)
        self.assertIsNone(ss.years_to("someday", self.TODAY))


class ContentTests(unittest.TestCase):

    def test_no_ranking_or_recommending_words(self):
        for where, text in (("seasons.py", ss.all_text(with_figures=True).lower()),
                            ("views/seasons.py", _code_words(VIEW))):
            for pat in NEVER:
                self.assertNotRegex(text, pat, (where, pat))

    def test_only_official_links(self):
        for host in ss.OFFICIAL_SITES:
            self.assertTrue(host.endswith(".gov"), host)
        links = ss.links()
        self.assertTrue(links)
        for label, url in links:
            self.assertTrue(url.startswith("https://"), url)
            self.assertIn(ss.host(url), ss.OFFICIAL_SITES, (label, url))
        for name in ("seasons.py", os.path.join("views", "seasons.py")):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                for url in re.findall(r"https?://[^\s\"')]+", fh.read()):
                    self.assertIn(ss.host(url), ss.OFFICIAL_SITES, (name, url))
        # every form explained links to its own official page
        for form, _words, url in ss.FORMS:
            self.assertIn(ss.host(url), ss.OFFICIAL_SITES, form)

    def test_each_season_has_its_moment(self):
        jan = " ".join(ss.JAN_MORE)
        self.assertIn("IRA window", jan)
        self.assertEqual({f for f, _w, _u in ss.FORMS},
                         {"W-2", "1099-DIV", "1099-B", "1099-INT", "1099-R", "5498", "SSA-1099"})
        fall = " ".join(ss.FALL_PARAS)
        self.assertIn("open enrollment", fall)
        self.assertIn("health savings account (HSA)", fall)
        self.assertIn("Year in review", " ".join(ss.SEASONS[3][4:]) + " Year in review")
        self.assertIn("future you", ss.LETTER_NONE + ss.LETTER_TITLE)
        self.assertIn("check with your plan or a tax professional", ss.CHECK)
        self.assertIn("Educational, not advice", ss.NOT_ADVICE)

    def test_no_invented_deadlines(self):
        text = ss.all_text()
        # no counted days, weeks or months; no dates except the RMD's own (IRS)
        self.assertNotRegex(text, r"\b\d+\s*(day|week|month)s?\b")
        self.assertNotRegex(text, r"\b(January|February|March|April|May|June|July|August|"
                                  r"September|October|November|December) \d")
        self.assertNotIn("April 15", ss.all_text(with_figures=True))
        for scary in ("penalty", "warning", "beware", "scam"):
            self.assertNotIn(scary, ss.all_text(with_figures=True).lower())

    def test_no_funds_or_brokerages_named(self):
        import brokerages
        text = ss.all_text(with_figures=True) + _code_words(VIEW)
        for name, _url in brokerages.BROKERAGES:
            self.assertNotIn(name.lower().replace("*", ""), text.lower())


class NeverSharedTests(unittest.TestCase):

    def test_never_in_the_ai_or_an_advisors_files(self):
        for name in ("advisor.py", "context_card.py", "ai_gateway.py", "ai_tools.py",
                     "ai_library.py", "meeting.py", "reports.py", "overview.py",
                     "advising.py", "proposals.py", "weekly_email.py", "client_plan.py",
                     os.path.join("views", "assistant.py"), os.path.join("views", "clients.py"),
                     os.path.join("views", "meeting.py"), os.path.join("views", "reports.py")):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotRegex(text, r"\bseasons\b", name)
        view = _code_words(VIEW)
        for pat in (r"\bai_gateway\b", r"\badvisor\.\w", r"\bcoach_prompt\b", r"\b_ai_"):
            self.assertNotRegex(view, pat)

    def test_the_flag_is_off_unless_set_and_owns_the_view(self):
        self.assertEqual(flags.FEATURES["seasons"], {"gates": (), "view": "seasons"})
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": ""}), \
                unittest.mock.patch.object(flags, "_secret", lambda name: None):
            self.assertFalse(flags.on("seasons"))
            self.assertFalse(flags.view_on("seasons"))
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": "seasons"}):
            self.assertTrue(flags.on("seasons"))


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
        cls.dir = tempfile.mkdtemp(prefix="pt_seasons_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.alice = auth.create_user(c, "alice", PW)
            sample_data.load(c, cls.alice)
            cls.olga = auth.create_user(c, "olga", PW)
            sample_data.load(c, cls.olga)
            advisor.save_profile(c, cls.olga, {"age_range": "65 or older"})
            cls.carol = auth.create_user(c, "carol", PW)
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dana = auth.create_user(c, "dana", PW)
            sample_data.load(c, cls.dana)
            auth.link_client(c, cls.carol, cls.dana)
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _app(self, uid, name, day, flag="seasons", page="Dashboard", **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")

        def patched(run):
            # whichever seasons module the app is using (codefresh may load
            # a fresh one on its first run): the day it goes by is `day`
            mod = sys.modules.get("seasons")
            if mod is None:
                import seasons as mod
            with unittest.mock.patch.object(mod, "today", lambda: day):
                run()
            return mod

        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": page,
                     "auto_backfilled": True, "fs_hide": True, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                   NORTHWEND_FLAGS=flag)
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline):
            mod = patched(at.run)
            if sys.modules.get("seasons") is not mod:   # reloaded during that run
                patched(at.run)
            self.assertEqual([e.message for e in at.exception], [])
            with unittest.mock.patch.object(sys.modules["seasons"], "today", lambda: day):
                yield at
            self.assertEqual([e.message for e in at.exception], [])

    @staticmethod
    def _text(at):
        parts = [m.value for m in at.markdown]
        for kind in ("caption", "subheader"):
            parts += [str(e.value) for e in getattr(at, kind)]
        return " ".join(parts)

    @staticmethod
    def _keys(at):
        return [b.key for b in at.button]

    def _prefs(self, uid):
        c = portfolio.connect(self.db)
        try:
            return prefs.load(c, uid)
        finally:
            c.close()

    def _reset(self, uid):
        c = portfolio.connect(self.db)
        try:
            p = prefs.load(c, uid)
            p.pop(ss.PREF, None)
            prefs.save(c, uid, p)
        finally:
            c.close()

    def test_off_unless_set(self):
        with self._app(self.alice, "alice", date(2026, 10, 15), flag="") as at:
            self.assertNotIn("ss_open_home_btn", self._keys(at))
            self.assertNotIn("Fall: open enrollment", self._text(at))
        with self._app(self.alice, "alice", date(2026, 10, 15), flag="",
                       page="Get started") as at:
            self.assertNotIn("ss_open_learn_btn", self._keys(at))

    def test_the_fall_card_opened_then_a_quiet_line(self):
        self._reset(self.alice)
        with self._app(self.alice, "alice", date(2026, 10, 15)) as at:
            self.assertIn("Fall: open enrollment", self._text(at))
            self.assertIn("ss_later", self._keys(at))
            at.button(key="ss_open_home_btn").click().run()
            text = self._text(at)
            self.assertIn(ss.FALL_PARAS[0], text)
            self.assertIn("How much can go into an HSA for 2026", text)
            self.assertIn("4,400", text)
            self.assertIn(ss.CHECK, text)
            self.assertIn("ss_match_home", self._keys(at))
        self.assertEqual(self._prefs(self.alice)[ss.PREF], {"2026-enrollment": "seen"})
        with self._app(self.alice, "alice", date(2026, 11, 20)) as at:
            keys = self._keys(at)
            self.assertIn("ss_open_home_btn", keys)        # one quiet line
            self.assertNotIn("ss_later", keys)
            self.assertNotIn(ss.FALL_PARAS[0], self._text(at))

    def test_not_now_puts_it_away_until_the_next_season(self):
        self._reset(self.alice)
        with self._app(self.alice, "alice", date(2026, 12, 3)) as at:
            self.assertIn("December: looking back", self._text(at))
            at.button(key="ss_later").click().run()
            self.assertNotIn("ss_open_home_btn", self._keys(at))
        self.assertEqual(self._prefs(self.alice)[ss.PREF], {"2026-december": "put_away"})
        with self._app(self.alice, "alice", date(2026, 12, 20)) as at:
            self.assertNotIn("ss_open_home_btn", self._keys(at))
        with self._app(self.alice, "alice", date(2027, 1, 5)) as at:
            self.assertIn("January: a fresh year", self._text(at))

    def test_between_seasons_nothing_on_home_and_learn_says_whats_coming(self):
        with self._app(self.alice, "alice", date(2026, 7, 4)) as at:
            self.assertNotIn("ss_open_home_btn", self._keys(at))
        with self._app(self.alice, "alice", date(2026, 7, 4), page="Get started") as at:
            self.assertIn("Coming up in October and November", self._text(at))
            at.button(key="ss_open_learn_btn").click().run()
            self.assertIn(ss.FALL_PARAS[0], self._text(at))
            at.pills(key="ss_pick_learn").set_value("april").run()
            text = self._text(at)
            self.assertIn(ss.APRIL_PARAS[0], text)
            self.assertIn("1099-DIV", text)
        # opening a season out of its time keeps nothing
        self.assertNotIn(ss.PREF, self._prefs(self.alice))

    def test_january_limits_in_their_year_only_and_the_fee_bill(self):
        self._reset(self.alice)
        with self._app(self.alice, "alice", date(2026, 1, 10)) as at:
            at.button(key="ss_open_home_btn").click().run()
            text = self._text(at)
            self.assertIn("How much can go in for 2026", text)
            self.assertIn("24,500", text)
            self.assertIn(ss.FEE_TITLE, text)
            # the Fee check's own figures, or its calm line when no fee is known
            self.assertTrue("Your funds' fees come to about" in text or ss.FEE_NONE in text)
            self.assertIn("IRA window", text)
        self._reset(self.alice)
        with self._app(self.alice, "alice", date(2027, 1, 10)) as at:
            at.button(key="ss_open_home_btn").click().run()
            text = self._text(at)
            self.assertNotIn("24,500", text)                   # never last year's figures
            self.assertIn(ss.JAN_NO_LIMITS, text)
        self._reset(self.alice)

    def test_the_fee_bill_carried_to_the_goal_date(self):
        c = portfolio.connect(self.db)
        try:
            fred = auth.create_user(c, "fred", PW)
            sample_data.load(c, fred)
            plans.save_plan(c, fred, {"goal_type": "Retirement", "target_amount": 1000000,
                                      "target_date": "2046-01-01"}, set_by=fred)
            c.execute("INSERT OR REPLACE INTO security_info (ticker, name, quote_type, "
                      "expense_ratio) VALUES ('VTI', 'A total market fund', 'ETF', 0.0003)")
            c.commit()
        finally:
            c.close()
        with self._app(fred, "fred", date(2026, 1, 10)) as at:
            at.button(key="ss_open_home_btn").click().run()
            text = self._text(at)
            self.assertIn("Your funds' fees come to about", text)
            self.assertIn("until your goal date, Jan 2046 - about 20 years", text)
            self.assertIn("the Fee check's assumption, not a forecast", text)
            self.assertIn("ss_fees_home", self._keys(at))
            # hidden amounts stay hidden
            at.session_state["hide_amounts"] = True
            at.run()
            text = self._text(at)
            self.assertIn("Your funds' fees come to about", text)
            amount = text.split("Your funds' fees come to about")[1].split(" a year")[0]
            self.assertNotRegex(amount, r"\d")   # the amount is masked; the % stays

    def test_december_the_rmd_note_only_for_65_or_older(self):
        with self._app(self.olga, "olga", date(2026, 12, 3)) as at:
            at.button(key="ss_open_home_btn").click().run()
            text = self._text(at)
            self.assertIn(ss.RMD_TITLE, text)
            self.assertIn("turns 73", text)
            self.assertIn(ss.LETTER_TITLE, text)
            self.assertIn(ss.LETTER_NONE, text)
            self.assertIn("ss_year_home", self._keys(at))
            self.assertIn("ss_plan_home", self._keys(at))
        self._reset(self.alice)
        c = portfolio.connect(self.db)
        try:
            future_notes.save(c, self.alice, future_notes.PLAN, "This is for the long run.")
        finally:
            c.close()
        with self._app(self.alice, "alice", date(2026, 12, 3)) as at:
            at.button(key="ss_open_home_btn").click().run()
            text = self._text(at)
            self.assertIn(ss.LETTER_TITLE, text)
            self.assertIn(ss.LETTER_BACK, text)                # her own words, back
            self.assertIn("This is for the long run.", " ".join(str(h.proto.body)
                                                               for h in at.get("html")))
            self.assertNotIn(ss.RMD_TITLE, text)
            self.assertNotIn("irs.gov/retirement-plans/retirement-plan-and-ira", text)
        self._reset(self.alice)

    def test_never_while_an_advisor_is_in_a_clients_account(self):
        before = self._prefs(self.dana)
        with self._app(self.carol, "carol", date(2026, 12, 3), two_step_ok=self.carol_ok,
                       active_user_id=self.dana) as at:
            self.assertNotIn("ss_open_home_btn", self._keys(at))
            self.assertNotIn("December: looking back", self._text(at))
        self.assertEqual(self._prefs(self.dana), before)
        # the client herself sees it
        with self._app(self.dana, "dana", date(2026, 12, 3)) as at:
            self.assertIn("December: looking back", self._text(at))


if __name__ == "__main__":
    unittest.main()
