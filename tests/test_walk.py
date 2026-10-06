"""The Monthly Walk v1 (ROADMAP R1, checkin.py, views/checkin.py) and the
feature counts behind its one-week test (R1's metric, R4's decided rules,
feature_counts.py): the rule-based verdict (no target, no verdict; within
the band, nothing to do; outside it, one next step for new money by asset
class - never "sell", a fund, a ticker or a figure), the rule shown under
it, what's kept of each walk (no figures), the walk count and the next
walk's day, the totals (groups of 20 or more, opt-out honoured, no names),
the privacy text that says so, and the Home card, Account switch and Admin
panel in the app. Runs dashboard.py with streamlit's AppTest on a scratch
database in a temp dir, plus the pure pieces.

    python -m unittest tests.test_walk        (from the repo root)
"""

import contextlib
import os
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from datetime import date, datetime, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import advisor  # noqa: E402
import auth  # noqa: E402
import checkin  # noqa: E402
import disclosures  # noqa: E402
import feature_counts  # noqa: E402
import gear  # noqa: E402
import manual_entry  # noqa: E402
import plans  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import two_step  # noqa: E402

OCT5 = date(2026, 10, 5)
WITHIN = "Your mix is within the band you set - your plan says nothing to do this month."
NO_TARGET = "Set a target mix to get a monthly verdict."
TO_BONDS = ("Your target has more bonds than you hold now, so your plan points your next "
            "deposit to bonds.")


def _calm(test, text):
    """A verdict never says sell, names a fund or a ticker, or gives a figure."""
    test.assertNotIn("sell", text.lower())
    test.assertNotIn("$", text)
    test.assertIsNone(re.search(r"\d", text), text)
    test.assertIsNone(re.search(r"\b[A-Z]{2,5}\b", text), text)


class _DB(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_walk_")
        self.db = os.path.join(self.dir, "t.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.conn = portfolio.connect(self.db)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.dir, ignore_errors=True)


# --------------------------------------------------------------------------- #
# the verdict: their own rule speaking
# --------------------------------------------------------------------------- #
class VerdictTests(unittest.TestCase):

    def test_no_target_no_verdict(self):
        v = checkin.verdict({"Stocks": 7000.0, "Bonds": 3000.0}, {}, 5.0, 500.0)
        self.assertEqual(v, {"kind": checkin.NONE})
        self.assertEqual(checkin.verdict_text(v), NO_TARGET)
        self.assertEqual(checkin.rule_text({}, 5.0), "")

    def test_within_the_band_says_nothing_to_do(self):
        targets = {"Stocks": 60.0, "Bonds": 40.0}
        for values in ({"Stocks": 6200.0, "Bonds": 3800.0},
                       {"Stocks": 6500.0, "Bonds": 3500.0},       # exactly at the band
                       {"Stocks": 6000.0, "Bonds": 4000.0}):
            v = checkin.verdict(values, targets, 5.0, 500.0)
            self.assertEqual(v, {"kind": checkin.WITHIN}, values)
        self.assertEqual(checkin.verdict_text(v), WITHIN)
        # their band, not a fixed one: 2 points flags what 5 doesn't
        self.assertEqual(checkin.verdict({"Stocks": 6300.0, "Bonds": 3700.0}, targets, 2.0,
                                         500.0)["kind"], checkin.NEXT)
        # a class with no target is never judged (Home's drift note's rule)
        self.assertEqual(checkin.verdict({"Stocks": 5800.0, "Bonds": 3800.0, "Other": 400.0},
                                         targets, 5.0, 500.0)["kind"], checkin.WITHIN)

    def test_outside_one_next_step_by_asset_class(self):
        targets = {"Stocks": 60.0, "Bonds": 30.0, "Cash": 10.0}
        # only bonds below its target: all of it
        v = checkin.verdict({"Stocks": 7000.0, "Bonds": 2000.0, "Cash": 1000.0}, targets, 5.0,
                            500.0)
        self.assertEqual(v, {"kind": "next", "class": "Bonds", "how": "all", "below": True})
        self.assertEqual(checkin.verdict_text(v), TO_BONDS)
        # bonds and cash both below: most of it to bonds (next_deposit's split)
        v = checkin.verdict({"Stocks": 7000.0, "Bonds": 2000.0, "Cash": 500.0}, targets, 5.0,
                            2000.0)
        self.assertEqual((v["class"], v["how"]), ("Bonds", "most"))
        self.assertEqual(checkin.verdict_text(v),
                         "Your target has more bonds than you hold now, so your plan points "
                         "your next deposit mostly to bonds.")
        self.assertIn("much of your next deposit to cash",
                      checkin.verdict_text({"kind": "next", "class": "Cash", "how": "much",
                                            "below": True}))
        self.assertEqual(checkin.verdict_text({"kind": "next", "class": "Other", "how": "all",
                                               "below": False}),
                         "Your plan points your next deposit to other holdings.")

    def test_never_sell_a_fund_or_a_figure(self):
        texts = [NO_TARGET, WITHIN, checkin.verdict_text({"kind": "next", "class": None})]
        for cls in ("Stocks", "Bonds", "Cash", "Other"):
            for how in checkin.HOWS:
                for below in (True, False):
                    v = {"kind": "next", "class": cls, "how": how, "below": below}
                    texts += [checkin.verdict_text(v), checkin.verdict_past(v)]
        texts += [checkin.verdict_past({"kind": k}) for k in checkin.KINDS]
        for text in texts:
            _calm(self, text)

    def test_the_rule_under_it_is_theirs(self):
        self.assertEqual(checkin.rule_text({"Bonds": 35.0, "Stocks": 60.0, "Cash": 5.0}, 5.0),
                         "Your rule: a target mix of 60% stocks, 35% bonds and 5% cash, and a "
                         "band of 5 points either way.")
        self.assertEqual(checkin.rule_text({"Stocks": 100.0}, 7.5),
                         "Your rule: a target mix of 100% stocks, and a band of 7.5 points "
                         "either way.")

    def test_only_kinds_are_kept_never_figures(self):
        self.assertEqual(checkin.stored({"kind": "next", "class": "Bonds", "how": "most",
                                         "below": True, "amount": 500.0, "pct": 21.0}),
                         {"kind": "next", "class": "Bonds", "how": "most"})
        self.assertEqual(checkin.stored({"kind": "within", "class": "Bonds"}), {"kind": "within"})
        self.assertEqual(checkin.stored({"kind": "next", "class": "VTI", "how": "$500"}),
                         {"kind": "next"})
        self.assertEqual(checkin.stored({"kind": "buy"}), {})
        self.assertEqual(checkin.stored(None), {})


# --------------------------------------------------------------------------- #
# walks: kept per month, counted, and the next one's day
# --------------------------------------------------------------------------- #
class WalkTests(unittest.TestCase):

    def _ready(self, p, d):
        for k in checkin.REQUIRED:
            checkin.tick(p, k, d)

    def test_each_walk_keeps_its_verdict_by_month(self):
        p = {checkin.PREF_SINCE: "2026-01", checkin.PREF_LOG: ["2026-07", "2026-08"]}
        self.assertEqual(checkin.count(p), 2)                 # the check-ins count as walks
        self._ready(p, OCT5)
        self.assertTrue(checkin.finish(p, OCT5, {"kind": "next", "class": "Bonds",
                                                 "how": "most", "below": True}))
        self.assertEqual(p[checkin.PREF_VERDICTS], {"2026-10": {
            "kind": "next", "class": "Bonds", "how": "most", "on": "2026-10-05"}})
        self.assertFalse(checkin.finish(p, OCT5 + timedelta(days=1), {"kind": "within"}))
        self.assertEqual(checkin.verdict_of(p, "2026-10")["kind"], "next")
        self.assertIsNone(checkin.verdict_of(p, "2026-08"))   # a check-in from before
        nov = date(2026, 11, 3)
        self._ready(p, nov)
        checkin.finish(p, nov, {"kind": "within"})
        self.assertEqual(set(p[checkin.PREF_VERDICTS]), {"2026-10", "2026-11"})
        self.assertEqual(checkin.count(p), 4)
        self.assertEqual(checkin.verdict_past(checkin.verdict_of(p, "2026-10")),
                         "Your plan pointed your next deposit mostly to bonds.")

    def test_a_missed_month_takes_nothing_away(self):
        p = {checkin.PREF_SINCE: "2026-01", checkin.PREF_LOG: ["2026-05", "2026-06", "2026-07"]}
        self.assertTrue(checkin.logbook(p))
        checkin.skip(p, OCT5)
        # months go by without a walk: the count and the logbook stay
        for d in (date(2026, 11, 2), date(2027, 2, 1)):
            self.assertEqual(checkin.count(p), 3)
            self.assertTrue(checkin.logbook(p))
            self.assertTrue(checkin.due(p, d))

    def test_the_next_walks_day(self):
        p = {checkin.PREF_SINCE: "2026-08"}
        self.assertEqual(checkin.next_walk(p, OCT5), OCT5)                  # waiting now
        p[checkin.PREF_DAY] = 12
        self.assertEqual(checkin.next_walk(p, OCT5), date(2026, 10, 12))    # this month, ahead
        checkin.tick(p, "mix", OCT5)
        self.assertEqual(checkin.next_walk(p, OCT5), OCT5)                  # started already
        self._ready(p, OCT5)
        checkin.finish(p, OCT5, {"kind": "within"})
        self.assertEqual(checkin.next_walk(p, OCT5), date(2026, 11, 12))    # walked: next month
        skipped = {checkin.PREF_SINCE: "2026-08"}
        checkin.skip(skipped, date(2026, 12, 3))
        self.assertEqual(checkin.next_walk(skipped, date(2026, 12, 3)), date(2027, 1, 1))
        # holdings in this month: the first walk is next month's
        self.assertEqual(checkin.next_walk({checkin.PREF_SINCE: "2026-10"}, OCT5),
                         date(2026, 11, 1))

    def test_four_steps_and_the_logbook_says_walk(self):
        self.assertEqual(checkin.STEP_KEYS, ("holdings", "mix", "read", "verdict"))
        self.assertIn("monthly walk", gear.HOW["logbook"])
        self.assertIn("three times - in any months", gear.HOW["logbook"])


# --------------------------------------------------------------------------- #
# feature counts: totals only, groups of 20 or more, opt-out honoured
# --------------------------------------------------------------------------- #
def _walker(first, second=None, *, off=False, before=None):
    """One account's settings with a first walk (and maybe a second)."""
    log, kept = list(before or []), {}
    for d in (first, second):
        if d:
            m = f"{d.year:04d}-{d.month:02d}"
            log.append(m)
            kept[m] = {"kind": "within", "on": d.isoformat()}
    p = {checkin.PREF_LOG: sorted(log), checkin.PREF_VERDICTS: kept}
    if off:
        p[feature_counts.PREF_OFF] = True
    return p


class FeatureCountTests(_DB):
    TODAY = date(2026, 12, 31)

    def test_nothing_under_twenty(self):
        first = date(2026, 10, 5)
        people = [_walker(first, first + timedelta(days=30)) for _ in range(19)]
        self.assertIsNone(feature_counts.walk_totals(people, self.TODAY))
        people.append(_walker(first))
        self.assertEqual(feature_counts.walk_totals(people, self.TODAY),
                         {"first_walks": 20, "window_closed": 20, "second_walks": 19})
        # leaving themselves out takes them out of every count, past walks too
        people[0][feature_counts.PREF_OFF] = True
        self.assertIsNone(feature_counts.walk_totals(people, self.TODAY))

    def test_second_walk_within_45_days(self):
        first = date(2026, 10, 5)
        people = ([_walker(first, first + timedelta(days=45)) for _ in range(10)]    # in time
                  + [_walker(first, first + timedelta(days=46)) for _ in range(5)]   # too late
                  + [_walker(first) for _ in range(5)]                               # not yet
                  + [_walker(first, off=True) for _ in range(5)]                     # left out
                  # a check-in before counting began: not their first walk
                  + [_walker(first, before=["2026-08"]) for _ in range(5)])
        self.assertEqual(feature_counts.walk_totals(people, self.TODAY),
                         {"first_walks": 20, "window_closed": 20, "second_walks": 10})
        # still inside their 45 days: counted as first walks, the share waits
        recent = [_walker(date(2026, 12, 20)) for _ in range(20)]
        self.assertEqual(feature_counts.walk_totals(people[:10] + recent, self.TODAY),
                         {"first_walks": 30, "window_closed": 10, "second_walks": None})
        self.assertEqual((feature_counts.MIN_GROUP, feature_counts.SECOND_WITHIN_DAYS), (20, 45))

    def test_from_the_database_settings_only(self):
        c = self.conn
        first = date(2026, 10, 5)
        for i in range(22):
            uid = auth.create_user(c, f"w{i}", "pw-123456789")
            prefs.save(c, uid, _walker(first, first + timedelta(days=30) if i % 2 else None,
                                       off=(i == 0)))
        nobody = auth.create_user(c, "nobody", "pw-123456789")
        prefs.save(c, nobody, {"hide_amounts": True})
        self.assertEqual(feature_counts.walks(c, self.TODAY),
                         {"first_walks": 21, "window_closed": 21, "second_walks": 11})
        # the query reads the settings column alone - never whose they are
        with open(os.path.join(REPO, "feature_counts.py"), encoding="utf-8") as fh:
            src = fh.read()
        sql = re.findall(r'"(SELECT[^"]*)"', src)
        self.assertEqual(sql, ["SELECT data FROM user_prefs WHERE data LIKE ?",
                               # the Storm Drill count (R4): settings only, no body
                               "SELECT p.data AS data FROM future_notes n LEFT JOIN user_prefs p "])

    def test_never_sent_to_the_ai_or_an_advisor(self):
        for name in ("advisor.py", "meeting.py", "reports.py", "overview.py", "advising.py",
                     "proposals.py", "weekly_email.py", "client_plan.py", "export.py",
                     os.path.join("views", "assistant.py"), os.path.join("views", "clients.py"),
                     os.path.join("views", "meeting.py"), os.path.join("views", "reports.py")):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                text = fh.read()
            for word in ("feature_counts", "walk_verdicts", "PREF_VERDICTS", "checkin"):
                self.assertNotIn(word, text, (name, word))


class PrivacyTextTests(unittest.TestCase):

    def test_said_plainly_in_the_app_and_the_policy(self):
        about = " ".join(body for _, body in disclosures.SECTIONS)
        policy_path = os.path.join(REPO, "docs", "legal", "privacy-policy-DRAFT.md")
        with open(policy_path, encoding="utf-8") as fh:
            policy = fh.read()
        for text in (about, policy):
            flat = " ".join(text.split())
            self.assertIn("no third-party analytics", flat.lower())
            self.assertIn("totals only, inside its own database", flat)
            self.assertIn("groups of 20 or more", flat)
            self.assertIn("never shared, sold or sent to the AI", flat)
            self.assertIn("Leave me out of feature counts", flat)
            self.assertIn("within 45 days", flat)
            self.assertNotIn("does not use analytics", flat)
            self.assertNotIn("doesn't send usage analytics", flat)
        self.assertEqual(disclosures.LAST_UPDATED, "October 6, 2026")   # everyone's told
        with open(os.path.join(REPO, "website", "public", "about.html"), encoding="utf-8") as fh:
            self.assertIn("Leave me out of feature counts", fh.read())


# --------------------------------------------------------------------------- #
# in the app
# --------------------------------------------------------------------------- #
class _WalkApp(unittest.TestCase):
    """The app on a scratch database with walkers seeded (no tests of its
    own: AppTests here, and tests/test_flags.py with the walk's flag off)."""
    FLAGS = "walk"   # NORTHWEND_FLAGS for the run (flags.py)

    @classmethod
    def setUpClass(cls):
        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or "")) == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_walk_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.seed(c)
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @classmethod
    def _investor(cls, c, name, target=None, **extra_prefs):
        uid = auth.create_user(c, name, "pw-123456789")
        advisor.save_profile(c, uid, {
            "goal": "Build long-term wealth", "time_horizon_years": 10,
            "risk_tolerance": "moderate", "drawdown_reaction": "Hold and wait",
            "experience": "some", "age_range": "35-44", "income_stability": "Very stable",
            "emergency_fund": "3-6 months", "high_interest_debt": "None",
            "employer_match": "No match or no plan"})
        plans.save_plan(c, uid, {"goal_type": "Build long-term wealth",
                                 "target_amount": 200000.0, "target_date": "2040-10-01",
                                 "monthly_contribution": 300.0, "target_alloc": target},
                        set_by=uid)
        # about 74% stocks, 25% bonds and 1% cash
        meta, rows, totals, _ = manual_entry.build(
            [{"account": "Brokerage", "symbol": "VTI", "quantity": 10, "cost_basis": 2500.0,
              "asset_type": "Equity"},
             {"account": "Brokerage", "symbol": "BND", "quantity": 10, "cost_basis": 1000.0,
              "asset_type": "Fixed Income"}],
            {"Brokerage": 50.0}, {"VTI": {"price": 300.0}, "BND": {"price": 100.0}},
            today=date(2026, 9, 10))
        portfolio.write_snapshot(c, uid, meta, rows, totals, manual_entry.SOURCE)
        seen = [k for k in gear.KEYS if k != "logbook"]
        prefs.save(c, uid, {"first_steps": {"done": True}, "gear_seen": seen,
                            "get_started_done": ["goal", "basics", "practice"],
                            "disclosures_seen": disclosures.LAST_UPDATED,
                            checkin.PREF_SINCE: "2026-08", **extra_prefs})
        return uid

    @classmethod
    def seed(cls, c):
        cls.wren = cls._investor(c, "wren", {"Stocks": 75.0, "Bonds": 25.0})     # within
        cls.bea = cls._investor(c, "bea", {"Stocks": 50.0, "Bonds": 50.0})       # outside
        cls.ola = cls._investor(c, "ola")                                        # no target
        # outside, and the target is still Northwend's example mix, untouched
        cls.eve = cls._investor(c, "eve", {"Stocks": 50.0, "Bonds": 50.0}, **{
            checkin.PREF_TARGET_FROM: {"by": "example",
                                       "mix": {"Stocks": 50.0, "Bonds": 50.0}}})
        # an advisor and her client, who finished this month's walk herself
        cls.carol = auth.create_user(c, "carol", "pw-123456789")
        auth.set_advisor(c, "carol", True)
        secret = two_step.new_secret()
        two_step.enable(c, cls.carol, secret, two_step.totp(secret))
        cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
        today = datetime.now().date()
        month = checkin.month_of(today)
        cls.dana = cls._investor(c, "dana", {"Stocks": 50.0, "Bonds": 50.0}, **{
            checkin.PREF_LOG: [month],
            checkin.PREF_STATE: {"month": month, "done": list(checkin.REQUIRED),
                                 "finished": today.isoformat(), "skipped": False},
            checkin.PREF_VERDICTS: {month: {"kind": "next", "class": "Bonds", "how": "all",
                                            "on": today.isoformat()}}})
        auth.link_client(c, cls.carol, cls.dana)

    @contextlib.contextmanager
    def _run(self, uid, name, page="Dashboard", **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": page, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                   NORTHWEND_FLAGS=self.FLAGS)
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    @staticmethod
    def _text(at):
        parts = [m.value for m in at.markdown] + [h.proto.body for h in at.get("html")]
        for kind in ("success", "info", "warning", "error", "caption"):
            parts += [str(e.value) for e in getattr(at, kind)]
        return " ".join(parts)

    @staticmethod
    def _keys(at):
        return [b.key for b in at.button if b.key]

    def _prefs(self, uid):
        c = portfolio.connect(self.db)
        try:
            return prefs.load(c, uid)
        finally:
            c.close()

    def _walk_to_verdict(self, at):
        at.button(key="walk_start").click().run()
        for key in ("walk_holdings_same", "walk_mix", "walk_read"):
            at.button(key=key).click().run()
        return self._text(at)



class AppTests(_WalkApp):

    def test_within_the_band_nothing_to_do(self):
        today = datetime.now().date()
        with self._run(self.wren, "wren") as at:
            self.assertIn("The monthly walk", self._text(at))
            text = self._walk_to_verdict(at)
            self.assertIn(WITHIN, text)
            self.assertIn("Your rule: a target mix of 75% stocks and 25% bonds, and a band of "
                          "5 points either way. You can change both on the Plan, under Target "
                          "mix.", text)
            self.assertIn("Northwend counts finished walks in totals only", text)
            at.button(key="walk_finish").click().run()
            text = self._text(at)
            self.assertIn("walk is done. Walks finished: 1. Next walk:", text)
            self.assertIn("Your plan said nothing to do this month", text)    # the quiet card
            self.assertIn("Walks finished: 1 · Next walk:", text)
        self.assertEqual(checkin.verdict_of(self._prefs(self.wren), checkin.month_of(today)),
                         {"kind": "within", "on": today.isoformat()})

    def test_outside_the_band_one_step_by_asset_class(self):
        today = datetime.now().date()
        with self._run(self.bea, "bea") as at:
            text = self._walk_to_verdict(at)
            self.assertIn(TO_BONDS, text)
            self.assertIn("a band of 5 points either way", text)
            verdict = next(m.value for m in at.markdown if m.value.startswith("**Your target"))
            _calm(self, verdict.strip("*"))
            # the link to the rule: the Plan's Target mix
            at.button(key="walk_plan").click().run()
            self.assertEqual(at.session_state["page"], "Plan")
        with self._run(self.bea, "bea", checkin_open=True) as at:
            at.button(key="walk_finish").click().run()
        self.assertEqual(checkin.verdict_of(self._prefs(self.bea), checkin.month_of(today)),
                         {"kind": "next", "class": "Bonds", "how": "all",
                          "on": today.isoformat()})

    def test_a_target_still_northwends_example_is_asked_about(self):
        # LEGAL_GATES C3: the verdict says, once and calmly, where the target came from
        with self._run(self.eve, "eve") as at:
            text = self._walk_to_verdict(at)
            self.assertIn(TO_BONDS, text)
            self.assertIn(checkin.TARGET_FROM_NOTE, text)
            _calm(self, checkin.TARGET_FROM_NOTE)
            at.button(key="walk_target_mine").click().run()
            self.assertNotIn(checkin.TARGET_FROM_NOTE, self._text(at))
            self.assertNotIn("walk_target_mine", self._keys(at))
        self.assertEqual(self._prefs(self.eve)[checkin.PREF_TARGET_FROM]["by"], "own")
        with self._run(self.eve, "eve", checkin_open=True) as at:   # hers now: nothing asked
            self.assertNotIn(checkin.TARGET_FROM_NOTE, self._text(at))

    def test_target_origin_rules(self):
        p = {}
        checkin.note_target(p, checkin.TARGET_EXAMPLE, {"Stocks": 60, "Bonds": 40, "Cash": 0})
        self.assertTrue(checkin.target_from_example(p, {"Stocks": 60.0, "Bonds": 40.0}))
        # changed since: theirs
        self.assertFalse(checkin.target_from_example(p, {"Stocks": 65.0, "Bonds": 35.0}))
        self.assertFalse(checkin.target_from_example(p, {}))
        checkin.note_target(p, checkin.TARGET_OWN, {"Stocks": 60, "Bonds": 40})
        self.assertFalse(checkin.target_from_example(p, {"Stocks": 60.0, "Bonds": 40.0}))
        self.assertFalse(checkin.target_from_example({}, {"Stocks": 60.0}))

    def test_no_target_no_verdict_and_a_link_to_the_plan(self):
        with self._run(self.ola, "ola") as at:
            text = self._walk_to_verdict(at)
            self.assertIn(NO_TARGET, text)
            self.assertNotIn("Your rule:", text)
            self.assertEqual(at.button(key="walk_plan").label, "Set a target mix")

    def test_an_advisor_never_sees_a_clients_walk(self):
        with self._run(self.carol, "carol", active_user_id=self.dana,
                       two_step_ok=self.carol_ok) as at:
            text = self._text(at)
            for words in ("Walks finished", "monthly walk", "Your plan pointed",
                          "next deposit to bonds"):
                self.assertNotIn(words, text)
            self.assertFalse([k for k in self._keys(at) if k.startswith("walk_")])
        with self._run(self.dana, "dana") as at:                 # while she sees her own
            text = self._text(at)
            self.assertIn("Your plan pointed your next deposit to bonds.", text)
            self.assertIn("Walks finished: 1", text)

    def test_leave_me_out_of_feature_counts(self):
        with self._run(self.ola, "ola", "Account") as at:
            self.assertFalse(at.toggle(key="acct_counts_off").value)
            self.assertIn("only groups of 20 or more", self._text(at))
            at.toggle(key="acct_counts_off").set_value(True).run()
        self.assertIs(self._prefs(self.ola)[feature_counts.PREF_OFF], True)
        with self._run(self.ola, "ola", "Account") as at:
            self.assertTrue(at.toggle(key="acct_counts_off").value)
            at.toggle(key="acct_counts_off").set_value(False).run()
        self.assertIs(self._prefs(self.ola)[feature_counts.PREF_OFF], False)

    def test_the_band_is_on_the_plan(self):
        with self._run(self.wren, "wren", "Plan", plan_tab="Target mix") as at:
            self.assertIn("Your band is 5 points either way", self._text(at))
            self.assertEqual(at.number_input(key="plan_drift_band").value, 5.0)


class AdminPanelTests(_DB):
    PANEL = """
import sys, os
sys.path.insert(0, {repo!r})
from datetime import datetime
import pandas as pd
import streamlit as st
import auth, mailer, pgcompat
from portfolio import connect
HERE = {repo!r}
DB = {db!r}
STAGING = False
HOSTED = False
LOGIN_ID = {uid}
IS_ADVISOR = False
path = os.path.join(HERE, "views", "admin.py")
with open(path, encoding="utf-8") as fh:
    exec(compile(fh.read(), path, "exec"), globals())
c = connect(DB)
_render_feature_tests(c)
c.close()
"""

    def _panel(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_string(self.PANEL.format(repo=REPO, db=self.db, uid=1),
                                 default_timeout=30).run()
        self.assertEqual(len(at.exception), 0, [e.message for e in at.exception])
        return " ".join([h.value for h in at.subheader] + [m.value for m in at.markdown]
                        + [c.value for c in at.caption])

    def test_totals_only_and_nothing_under_twenty(self):
        c = self.conn
        first = datetime.now().date() - timedelta(days=60)
        uids = []
        for i in range(19):
            uid = auth.create_user(c, f"walker{i}", "pw-123456789")
            prefs.save(c, uid, _walker(first, first + timedelta(days=30) if i < 8 else None))
            uids.append(uid)
        text = self._panel()
        self.assertIn("Feature tests", text)
        self.assertIn("Fewer than 20 people have finished a first walk", text)
        uid = auth.create_user(c, "walker19", "pw-123456789")
        prefs.save(c, uid, _walker(first))
        text = self._panel()
        self.assertIn("Finished a first walk: 20", text)
        self.assertIn("Walked again within 45 days: 8 of 20 (40%)", text)
        for i in range(20):
            self.assertNotIn(f"walker{i}", text)                    # never a name


if __name__ == "__main__":
    unittest.main()
