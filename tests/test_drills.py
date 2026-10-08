"""Preparedness drills (ROADMAP R12, the one-week test; drills.py,
views/drills.py, flag drills).

The words: ten drills, hard times and good times alike; taps are things to
weigh or ask, never a trade, never graded; no "should", "best",
"recommend", right/wrong grades, figures, funds or brokerages. The logic:
one drill a week (ISO weeks), the next not rehearsed, repeats with a twist
once all ten are; a count of weeks rehearsed that only grows; keys only
kept. The gear (the whistle) and the metric (a third drill, totals only,
the opt-out respected). In the app: off unless its flag is set; works for
someone with no money invested (no mix); a tap updates the readiness map;
never while an advisor is in a client's account, never in the client
record or the AI.

    python -m unittest tests.test_drills        (from the repo root)
"""

import contextlib
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
import brokerages  # noqa: E402
import drills  # noqa: E402
import export  # noqa: E402
import feature_counts  # noqa: E402
import flags  # noqa: E402
import gear  # noqa: E402
import manual_entry  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sample_data  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
# grading, advising and urgent words that must never appear
NEVER = (r"\bshould\b", r"\bbest\b", r"\brecommend", r"\bcorrect", r"\bwrong\b",
         r"\bright answer\b", r"\bright choice\b", r"\bbetter\b", r"\bworst\b",
         r"\bmistake\b", r"\bsmart\b", r"\bguarantee", r"\bmust\b", r"\burgent",
         r"\bact now\b", r"\bdon't miss\b", r"\bstreak\b", r"\bfire\b", r"\bbroken\b")
# a tap is something to weigh or ask - never a trade
TRADES = (r"\bbuy\b", r"\bsell\b", r"\bsold\b", r"\bbought\b", r"\brebalance",
          r"\bswitch\b", r"\bmove (it|my|the)\b", r"\bput (it|my|the)\b", r"\binvest it\b")
PROFILE = {"goal": "Build long-term wealth", "time_horizon_years": 15,
           "risk_tolerance": "moderate", "drawdown_reaction": "Hold",
           "experience": "new", "age_range": "25-34", "income_stability": "Very stable",
           "emergency_fund": "3-6 months"}


def _code_words(path):
    """A source file's text without its comment lines (lower case)."""
    with open(path, encoding="utf-8") as fh:
        return "\n".join(line for line in fh.read().lower().splitlines()
                         if not line.lstrip().startswith("#"))


class ContentTests(unittest.TestCase):

    def test_ten_drills_hard_and_good_alike(self):
        self.assertEqual(len(drills.DRILLS), 10)
        self.assertEqual(len(set(drills.KEYS)), 10)
        sides = [drills.side_of(k) for k in drills.KEYS]
        self.assertEqual(sides.count(drills.HARD), 5)
        self.assertEqual(sides.count(drills.GOOD), 5)
        # suggested in turn: hard, good, hard, good...
        self.assertEqual(sides, [drills.HARD, drills.GOOD] * 5)
        titles = {drills.title_of(k) for k in drills.KEYS}
        for t in ("A sharp market drop", "Losing a job", "A surprise expense", "A fund closing",
                  "A raise", "A bonus", "A windfall", "A goal reached early"):
            self.assertIn(t, titles)

    def test_two_to_four_taps_each_considerations_not_trades(self):
        for k in drills.KEYS:
            choices = drills.choices_of(k)
            self.assertTrue(2 <= len(choices) <= 4, k)
            self.assertEqual(len({c for c, _ in choices}), len(choices), k)
            for c, words in choices:
                self.assertRegex(c, r"^[a-z_]+$")
                self.assertTrue(words.startswith("I'd "), (k, words))   # what they'd weigh
                for pat in TRADES:
                    self.assertNotRegex(words.lower(), pat, (k, words))

    def test_no_grading_or_advising_words(self):
        text = drills.all_text().replace(drills.NO_RIGHT_ANSWER, "").lower()
        for pat in NEVER:
            self.assertNotRegex(text, pat, pat)
        view = _code_words(os.path.join(REPO, "views", "drills.py"))
        for pat in NEVER:
            self.assertNotRegex(view, pat, ("views/drills.py", pat))
        # the one place "right answer" appears says there isn't one
        self.assertIn("There's no right answer on an investment choice", drills.NO_RIGHT_ANSWER)

    def test_no_figures_funds_or_brokerages(self):
        text = drills.all_text()
        self.assertNotRegex(text, r"\d")            # no invented numbers, months or deadlines
        self.assertNotIn("$", text)
        self.assertNotRegex(text, r"\b[A-Z]{2,5}\b")   # no tickers
        for name, _url in brokerages.BROKERAGES:
            self.assertNotIn(name.replace("*", ""), text)
        self.assertNotRegex(text.lower(), r"\brecover(s|ed)? in\b")

    def test_every_drill_has_a_note_and_a_twist(self):
        for k in drills.KEYS:
            self.assertTrue(drills.think_of(k).endswith("."), k)
            self.assertTrue(drills.twist_of(k).startswith("This time, imagine"), k)
            self.assertTrue(drills.BY_KEY[k][3].startswith("Imagine"), k)


class PictureTests(unittest.TestCase):

    def test_beginner_version_has_no_mix(self):
        lines = drills.picture("drop", None, None)
        self.assertEqual(lines, [drills.BEGINNER_LINE])
        lines = drills.picture("job", {}, 15)
        self.assertEqual(lines, [drills.BEGINNER_LINE,
                                 "Your goal is many years away."])

    def test_own_mix_in_whole_percents_only(self):
        mix = {"Stocks": 74.4, "Bonds": 24.6, "Cash": 1.0}
        self.assertEqual(drills.picture("drop", mix, 2)[0],
                         "In your own mix, about 74% is in stocks - the part that usually "
                         "moves most, down and up.")
        self.assertEqual(drills.picture("drop", mix, 2)[1],
                         "Your goal is a few years away or less.")
        self.assertEqual(drills.picture("expense", mix, 6),
                         ["Of what you hold here, about 1% is cash.",
                          "Your goal is several years away."])
        self.assertEqual(drills.picture("raise", mix, None), [])   # no lens, no timeline
        for k in drills.KEYS:
            for line in drills.picture(k, mix, 8):
                self.assertNotIn("$", line)

    def test_timeline_words(self):
        self.assertIsNone(drills.timeline_words(None))
        self.assertIsNone(drills.timeline_words(0))
        self.assertIsNone(drills.timeline_words("soon"))
        self.assertIn("a few years", drills.timeline_words(1))
        self.assertIn("several", drills.timeline_words(3))
        self.assertIn("many", drills.timeline_words(10))


class WeekTests(unittest.TestCase):
    MON = date(2026, 10, 5)     # ISO week 41

    def test_iso_weeks(self):
        self.assertEqual(drills.iso_week(self.MON), "2026-W41")
        self.assertEqual(drills.iso_week(self.MON + timedelta(days=6)), "2026-W41")   # Sunday
        self.assertEqual(drills.iso_week(self.MON + timedelta(days=7)), "2026-W42")
        self.assertEqual(drills.iso_week(date(2027, 1, 1)), "2026-W53")
        self.assertEqual(drills.week_start(date(2026, 10, 8)), self.MON)
        self.assertEqual(drills.next_week_start(date(2026, 10, 11)), date(2026, 10, 12))

    def test_one_a_week_the_next_not_rehearsed(self):
        p = {}
        # a new person's first drill is a good time, never a market drop
        self.assertEqual(drills.suggested(p, self.MON), ("raise", False))
        self.assertTrue(drills.record(p, "raise", "split", self.MON))
        self.assertEqual(drills.done_this_week(p, self.MON + timedelta(days=3)), "raise")
        # the rest of the week: the same drill, done; another isn't kept
        self.assertEqual(drills.suggested(p, self.MON + timedelta(days=2)), ("raise", False))
        self.assertFalse(drills.record(p, "drop", "plan", self.MON + timedelta(days=2)))
        # tapping again on this week's drill changes the choice
        self.assertTrue(drills.record(p, "raise", "match", self.MON + timedelta(days=1)))
        self.assertEqual(drills.chosen(p, "raise"), "match")
        self.assertEqual(drills.weeks_rehearsed(p), 1)
        # next week: another good time (GENTLE_FIRST), then the hard ones in turn
        nxt = self.MON + timedelta(days=7)
        self.assertEqual(drills.GENTLE_FIRST, 2)
        self.assertEqual(drills.suggested(p, nxt), ("bonus", False))
        self.assertTrue(drills.record(p, "bonus", "fund", nxt))
        self.assertEqual(drills.weeks_rehearsed(p), 2)
        self.assertEqual(drills.rehearsed(p), ["raise", "bonus"])
        self.assertEqual(drills.suggested(p, nxt + timedelta(days=7)), ("drop", False))
        self.assertFalse(drills.third_done(p))

    def test_first_drills_are_never_hard_times(self):
        # someone who did a hard one already: the next is still a good time
        p = {}
        drills.record(p, "drop", "plan", self.MON)
        self.assertEqual(drills.suggested(p, self.MON + timedelta(days=7)), ("raise", False))
        for n in range(20):     # nothing done: whatever the week, a good time first
            day = self.MON + timedelta(days=7 * n)
            self.assertEqual(drills.side_of(drills.suggested({}, day)[0]), drills.GOOD)

    def test_a_missed_week_costs_nothing(self):
        p = {}
        drills.record(p, "raise", "goal", self.MON)
        later = self.MON + timedelta(days=7 * 5)       # four weeks skipped
        self.assertEqual(drills.weeks_rehearsed(p), 1)
        self.assertEqual(drills.suggested(p, later), ("bonus", False))
        drills.record(p, "bonus", "debt", later)
        self.assertEqual(drills.weeks_rehearsed(p), 2)   # it only grows
        self.assertEqual(drills.weeks_text(2), "Weeks you've rehearsed: 2")

    def test_repeats_come_back_with_a_twist(self):
        p = {}
        day = self.MON
        # the two gentle ones first, then the rest in DRILLS order
        first = [k for k in drills.KEYS if drills.side_of(k) == drills.GOOD][:2]
        expected = first + [k for k in drills.KEYS if k not in first]
        for k in expected:
            self.assertEqual(drills.suggested(p, day), (k, False))
            drills.record(p, k, drills.choices_of(k)[0][0], day)
            day += timedelta(days=7)
        # all ten: the one done longest ago comes back, as a repeat
        self.assertEqual(drills.suggested(p, day), (expected[0], True))
        drills.record(p, expected[0], drills.choices_of(expected[0])[1][0], day)
        self.assertEqual(drills.state(p)["done"][expected[0]]["times"], 2)
        self.assertEqual(drills.suggested(p, day), (expected[0], True))
        self.assertEqual(drills.suggested(p, day + timedelta(days=7)), (expected[1], True))
        self.assertEqual(drills.weeks_rehearsed(p), 11)

    def test_only_keys_are_kept(self):
        self.assertFalse(drills.record({}, "drop", "I'd sell everything", self.MON))
        self.assertFalse(drills.record({}, "nope", "plan", self.MON))
        p = {"other": 1}
        drills.record(p, "drop", "plan", self.MON)
        self.assertEqual(p, {"other": 1, drills.PREF: {
            "done": {"drop": {"choice": "plan", "week": "2026-W41", "times": 1}},
            "weeks": ["2026-W41"]}})
        junk = {"done": {"drop": {"choice": "plan", "week": "2026-W41", "note": "my words"},
                         "raise": {"choice": "free text", "week": "2026-W40"},
                         "x": {"choice": "plan", "week": "2026-W40"},
                         "job": {"choice": "fund", "week": "last week"}},
                "weeks": ["2026-W39", "nope", 5], "amount": 5000}
        self.assertEqual(drills.clean(junk), {
            "done": {"drop": {"choice": "plan", "week": "2026-W41", "times": 1}},
            "weeks": ["2026-W39", "2026-W41"]})
        self.assertEqual(drills.clean("junk"), {"done": {}, "weeks": []})

    def test_readiness_map(self):
        p = {}
        drills.record(p, "drop", "plan", self.MON)
        drills.record(p, "raise", "split", self.MON + timedelta(days=7))
        m = drills.readiness(p)
        self.assertEqual([(s, label) for s, label, _ in m],
                         [(drills.HARD, "Hard times"), (drills.GOOD, "Good times")])
        hard = {k: done for k, _t, done in m[0][2]}
        good = {k: done for k, _t, done in m[1][2]}
        self.assertEqual(len(hard), 5)
        self.assertEqual(len(good), 5)
        self.assertTrue(hard["drop"])
        self.assertTrue(good["raise"])
        self.assertFalse(hard["job"])


class GearAndCountTests(unittest.TestCase):

    def test_the_whistle_for_three_drills(self):
        self.assertIn("whistle", gear.KEYS)
        self.assertEqual(gear.NEED["whistle"], "drills_done")
        self.assertEqual(gear.DRILLS, drills.GEAR_AT)
        self.assertIn("three different preparedness drills", gear.HOW["whistle"])
        self.assertEqual(gear.earned({"drills_done": True}), ["whistle"])
        self.assertNotIn("whistle", gear.kit_keys(drills=False))
        self.assertIn("whistle", gear.kit_keys())
        self.assertEqual(gear.GO["whistle"][1], ("drill", "Dashboard"))

    def test_third_drill_counted_in_totals_only(self):
        def person(n):
            p = {}
            for i, k in enumerate(drills.KEYS[:n]):
                drills.record(p, k, drills.choices_of(k)[0][0], date(2026, 9, 7) + timedelta(days=7 * i))
            return p
        people = [person(1)] * 12 + [person(3)] * 7
        self.assertIsNone(feature_counts.drill_totals(people))       # 19 < MIN_GROUP
        people.append(person(4))
        self.assertEqual(feature_counts.drill_totals(people), {"started": 20, "third": 8})
        people[-1] = {**person(4), feature_counts.PREF_OFF: True}    # left out
        self.assertIsNone(feature_counts.drill_totals(people))
        self.assertIsNone(feature_counts.drill_totals([{}] * 30))    # nobody started


class NeverSharedTests(unittest.TestCase):

    def test_never_in_the_ai_or_an_advisors_files(self):
        for name in ("advisor.py", "context_card.py", "ai_gateway.py", "ai_tools.py",
                     "ai_library.py", "ai_policy.py", "meeting.py", "reports.py",
                     "overview.py", "advising.py", "proposals.py", "weekly_email.py",
                     "client_plan.py", "intros.py", "export.py",
                     os.path.join("views", "assistant.py"), os.path.join("views", "clients.py"),
                     os.path.join("views", "meeting.py"), os.path.join("views", "reports.py")):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("drills", text, name)
        with open(os.path.join(REPO, "views", "drills.py"), encoding="utf-8") as fh:
            view = fh.read()
        for pat in (r"\bai_gateway\b", r"\badvisor\.\w", r"\bcoach_prompt\b", r"\b_ai_",
                    r"\b_ask_", r"\bmailer\b", r"\bsend_"):
            self.assertNotRegex(view, pat)

    def test_the_flag_is_off_unless_set_and_owns_the_view(self):
        self.assertEqual(flags.FEATURES["drills"], {"gates": (), "view": "drills"})
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": ""}), \
                unittest.mock.patch.object(flags, "_secret", lambda name: None):
            self.assertFalse(flags.on("drills"))
            self.assertFalse(flags.view_on("drills"))
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": "drills"}):
            self.assertTrue(flags.on("drills"))

    def test_no_reminders(self):
        for name in ("checkin_email.py", "weekly_email.py", "mailer.py",
                     os.path.join(".github", "workflows", "scheduled-sync.yml")):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                self.assertNotIn("drill", fh.read().replace("storm_drill", ""), name)


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
        cls.dir = tempfile.mkdtemp(prefix="pt_drills_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        cls.today = date.today()
        c = portfolio.connect(cls.db)
        try:
            # a beginner: no money invested yet
            cls.bea = auth.create_user(c, "bea", PW)
            advisor.save_profile(c, cls.bea, PROFILE)
            prefs.save(c, cls.bea, {"first_steps": {"done": True},
                                    "gear_seen": list(gear.KEYS)})
            # an investor with her own holdings, two drills done in earlier weeks
            cls.ivy = auth.create_user(c, "ivy", PW)
            advisor.save_profile(c, cls.ivy, PROFILE)
            meta, rows, totals, _ = manual_entry.build(
                [{"account": "Brokerage", "symbol": "VTI", "quantity": 10, "cost_basis": 2500.0,
                  "asset_type": "Equity"},
                 {"account": "Brokerage", "symbol": "BND", "quantity": 10, "cost_basis": 1000.0,
                  "asset_type": "Fixed Income"}],
                {"Brokerage": 50.0}, {"VTI": {"price": 300.0}, "BND": {"price": 100.0}},
                today=cls.today - timedelta(days=3))
            portfolio.write_snapshot(c, cls.ivy, meta, rows, totals, manual_entry.SOURCE)
            p = {"first_steps": {"done": True},
                 "gear_seen": [k for k in gear.KEYS if k != "whistle"]}
            drills.record(p, "drop", "plan", cls.today - timedelta(days=14))
            drills.record(p, "raise", "split", cls.today - timedelta(days=7))
            prefs.save(c, cls.ivy, p)
            # an advisor and her client, who has done a drill herself
            cls.carol = auth.create_user(c, "carol", PW)
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dana = auth.create_user(c, "dana", PW)
            sample_data.load(c, cls.dana)
            auth.link_client(c, cls.carol, cls.dana)
            d = {"first_steps": {"done": True}}
            drills.record(d, "drop", "talk", cls.today)
            prefs.save(c, cls.dana, d)
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _app(self, uid, name, flag="drills", page="Dashboard", **state):
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
        parts += [str(e.value) for e in at.caption]
        parts += [h.proto.body for h in at.get("html")]
        parts += [e.label for e in at.expander]
        return " ".join(parts)

    def _prefs(self, uid):
        c = portfolio.connect(self.db)
        try:
            return prefs.load(c, uid)
        finally:
            c.close()

    def test_off_unless_set(self):
        with self._app(self.bea, "bea", flag="") as at:
            self.assertNotIn("This week's drill", self._text(at))
            self.assertNotIn("drill_start", [b.key for b in at.button])
            self.assertNotIn("Whistle", self._text(at))     # not in the kit either

    def test_a_beginner_rehearses_and_the_map_updates(self):
        with self._app(self.bea, "bea") as at:
            text = self._text(at)
            self.assertIn("This week's drill", text)
            # day one opens on a good time, not a sharp market drop
            self.assertIn(f"<b>{drills.title_of('raise')}</b>", text)
            self.assertIn("0 of 10 situations rehearsed", text)
            at.button(key="drill_start").click().run()
            text = self._text(at)
            self.assertIn(drills.BY_KEY["raise"][3], text)
            self.assertIn(drills.BEGINNER_LINE, text)          # no mix: the beginner version
            self.assertNotIn("% is in stocks", text)
            keys = [b.key for b in at.button]
            for c, _w in drills.choices_of("raise"):
                self.assertIn(f"drill_tap_{c}", keys)
            at.button(key="drill_tap_match").click().run()
            text = self._text(at)
            self.assertIn(drills.choice_words("raise", "match"), text)
            self.assertIn(drills.THINK_LEAD, text)
            self.assertIn(drills.think_of("raise"), text)
            self.assertIn(drills.NO_RIGHT_ANSWER, text)
            self.assertIn("1 of 10 situations rehearsed", text)
            self.assertIn("Weeks you&#x27;ve rehearsed: 1", text)
            self.assertNotIn("drill_tap_split", [b.key for b in at.button])
        kept = self._prefs(self.bea)[drills.PREF]
        self.assertEqual(kept, {"done": {"raise": {"choice": "match",
                                                   "week": drills.iso_week(date.today()),
                                                   "times": 1}},
                                "weeks": [drills.iso_week(date.today())]})
        # in her own export, as one of her settings
        c = portfolio.connect(self.db)
        try:
            self.assertIn("drills", str(export.collect(c, self.bea)["settings"]))
        finally:
            c.close()
        # a new visit the same week: done, with next week's day - no second drill
        with self._app(self.bea, "bea") as at:
            text = self._text(at)
            self.assertIn("Done for this week", text)
            self.assertNotIn("drill_start", [b.key for b in at.button])

    def test_her_own_mix_and_the_whistle_on_a_third(self):
        with self._app(self.ivy, "ivy") as at:
            self.assertIn("Weeks you&#x27;ve rehearsed: 2", self._text(at))
            self.assertIn(drills.title_of("job"), self._text(at))     # the next: a hard time
            at.button(key="drill_start").click().run()
            text = self._text(at)
            # her cash share, a whole percent - never an amount
            line = next(str(c.value) for c in at.caption
                        if "Of what you hold here" in str(c.value))
            self.assertRegex(line, r"^Of what you hold here, about \d{1,3}% is cash\. "
                                   r"Your goal is many years away\.$")
            self.assertNotIn(drills.BEGINNER_LINE, text)
            at.button(key="drill_tap_fund").click().run()
            text = self._text(at)
            self.assertIn("3 of 10 situations rehearsed", text)
            # the whistle: earned, celebrated once the drill's window closes
            # (one window at a time)
            at.button(key="drill_close").click().run()
            self.assertIn("You've earned the <b>whistle</b>", self._text(at))
        self.assertIn("whistle", self._prefs(self.ivy)["gear_seen"])

    def test_never_while_an_advisor_is_in_a_clients_account(self):
        before = self._prefs(self.dana)
        with self._app(self.carol, "carol", two_step_ok=self.carol_ok,
                       active_user_id=self.dana) as at:
            text = self._text(at)
            self.assertNotIn("This week's drill", text)
            self.assertNotIn("readiness map", text)
            self.assertNotIn(drills.choice_words("drop", "talk"), text)
            self.assertFalse([b for b in at.button if str(b.key).startswith("drill_")])
        self.assertEqual(self._prefs(self.dana), before)
        # never in her advisor's record of her
        c = portfolio.connect(self.db)
        try:
            self.assertNotIn("drills", str(export.client_record(c, self.carol, self.dana)))
        finally:
            c.close()
        # in her own account she has it
        with self._app(self.dana, "dana") as at:
            self.assertIn("This week's drill", self._text(at))


if __name__ == "__main__":
    unittest.main()
