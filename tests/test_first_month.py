"""Your first month (first_month.py, views/first_month.py, flag first_month).

The checklist from made-up states (a new account, partway, all done, older
than five weeks), the gear each step earns and its order, the fixed lines
(no figures, tickers or advice words), what's kept (keys only), and the card
on Home with AppTest: shown for an individual's young account - with or
without holdings - and never for an older account, an advisor's client, an
advisor in a client's account or an advisor's own portfolio.

    python -m unittest tests.test_first_month        (from the repo root)
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
from tests import offline as offline_net  # noqa: E402

import ai_policy  # noqa: E402
import auth  # noqa: E402
import checkin  # noqa: E402
import first_month as fm  # noqa: E402
import flags  # noqa: E402
import gear  # noqa: E402
import home_tasks  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import recap  # noqa: E402
import route  # noqa: E402
import sample_data  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
ALL = {"profile_done": True, "practice_done": True, "costs_checked": True,
       "goal_set": True, "first_walk": True}
BANNED = ("should", "best", "recommend", "buy", "sell", "rebalance", "overdue", "late",
          "missed", "streak", "behind", "hurry up", "calm", "trail", "storm")
CARD = "class='pt-fm-list'"   # the card's checklist (views/first_month.py)


class ChecklistTests(unittest.TestCase):

    def test_a_new_account_starts_at_the_questions(self):
        steps = fm.checklist({})
        self.assertEqual([s["key"] for s in steps],
                         ["start", "practice", "costs", "goal", "walk"])
        self.assertEqual([s["day"] for s in steps], [0, 3, 7, 14, 30])
        self.assertFalse(any(s["done"] for s in steps))
        self.assertEqual(fm.current(steps)["key"], "start")
        self.assertTrue(fm.shown(0, steps))
        self.assertEqual(fm.lines(steps)["count"], "0 of 5 done")

    def test_partway_shows_the_first_open_step_in_order(self):
        steps = fm.checklist({"profile_done": True, "goal_set": True})
        self.assertEqual(fm.current(steps)["key"], "practice")
        self.assertEqual(fm.lines(steps)["next"], fm.TITLES["practice"])
        self.assertEqual(fm.lines(steps)["count"], "2 of 5 done")
        # a step past its day is simply still open: nothing else changes
        late = fm.checklist({"profile_done": True})
        self.assertEqual(fm.lines(late), fm.lines(fm.checklist({"profile_done": True})))
        self.assertTrue(fm.shown(29, late))

    def test_all_done_hides_the_card(self):
        steps = fm.checklist(ALL)
        self.assertIsNone(fm.current(steps))
        self.assertFalse(fm.shown(3, steps))

    def test_only_while_the_account_is_young(self):
        steps = fm.checklist({})
        self.assertTrue(fm.shown(fm.SHOW_DAYS - 1, steps))
        self.assertFalse(fm.shown(fm.SHOW_DAYS, steps))
        self.assertFalse(fm.shown(90, steps))
        self.assertFalse(fm.shown(None, steps))   # no date: never guessed

    def test_age_from_the_users_row(self):
        today = date(2026, 10, 10)
        self.assertEqual(fm.age_days("2026-10-10 08:00:00", today), 0)
        self.assertEqual(fm.age_days("2026-09-05 23:59:59", today), 35)
        self.assertEqual(fm.age_days("2026-10-12T00:00:00Z", today), 0)   # never negative
        self.assertIsNone(fm.age_days("", today))
        self.assertIsNone(fm.age_days("not a date", today))

    def test_without_the_walk_its_step_is_left_out(self):
        steps = fm.checklist({}, walk=False)
        self.assertNotIn("walk", [s["key"] for s in steps])
        self.assertFalse(fm.shown(1, fm.checklist({k: v for k, v in ALL.items()
                                                    if k != "first_walk"}, walk=False)))

    def test_where_each_step_points(self):
        a = fm.action
        self.assertEqual(a("start"), ("Answer the questions", ("learn", "profile")))
        self.assertEqual(a("practice"), ("Try practice money", ("learn", "practice")))
        self.assertEqual(a("goal"), ("Set a goal", ("learn", "goal")))
        # what funds cost: the Fee check with funds held, else the read on Learn
        self.assertEqual(a("costs", has_funds=True), (fm.GO_FEES, ("fees", None)))
        self.assertEqual(a("costs"), (fm.GO_FEES_READ, ("learn", "basics")))
        # the walk: open on Home when it's waiting
        self.assertEqual(a("walk", walk_due=True, real_holdings=True),
                         (fm.GO_WALK, ("checkin", None)))
        # before money: the route's next Start investing waypoint
        self.assertEqual(a("walk", invest_next="account"), (fm.GO_INVEST, ("learn", "account")))
        # holdings in, the walk not offered yet: nothing to press
        self.assertIsNone(a("walk", real_holdings=True, invest_next=None))
        self.assertEqual(fm.why("walk"), fm.WALK_NO_HOLDINGS)
        self.assertEqual(fm.why("walk", real_holdings=True), fm.WALK_LATER)
        self.assertEqual(fm.why("walk", real_holdings=True, walk_due=True), fm.WALK_DUE)
        # every Learn place named is a real waypoint
        with open(os.path.join(REPO, "views", "get_started.py"), encoding="utf-8") as fh:
            steps = fh.read().split("GET_STARTED_STEPS = (", 1)[1].split("\n)", 1)[0]
        for k in ("profile", "practice", "goal", "basics"):
            self.assertIn(f'("{k}", ', steps)
        for k in route.stage_keys(route.INVEST):
            self.assertIn(f'("{k}", ', steps)


class GearTests(unittest.TestCase):

    def test_each_step_earns_one_piece_in_order(self):
        self.assertEqual([fm.GEAR[k] for k in fm.KEYS],
                         ["map", "rope", "binoculars", "compass", "watch"])
        for k in fm.KEYS:
            g = fm.GEAR[k]
            self.assertIn(g, gear.KEYS)
            # the step and its gear use the same fact: they never disagree
            self.assertEqual(gear.NEED[g], fm.FACT[k])
        # step by step, the gear comes in the steps' order
        facts, got = {}, []
        for k in fm.KEYS:
            facts[fm.FACT[k]] = True
            have = gear.earned(facts)
            new = [g for g in have if g not in got]
            self.assertEqual(new, [fm.GEAR[k]])
            got = have

    def test_older_accounts_take_the_new_pieces_quietly(self):
        self.assertEqual(fm.QUIET_GEAR, gear.NEEDS_FIRST_MONTH)
        fresh = ["boots", "binoculars", "watch"]
        self.assertEqual(fm.quiet_for(fresh, 3), fresh)                    # a new account
        self.assertEqual(fm.quiet_for(fresh, fm.SHOW_DAYS - 1), fresh)
        self.assertEqual(fm.quiet_for(fresh, fm.SHOW_DAYS), ["boots"])     # past its first month
        self.assertEqual(fm.quiet_for(fresh, None), ["boots"])            # age unknown: quiet
        self.assertEqual(fm.quiet_for([], 400), [])

    def test_the_new_pieces_are_learning_and_habits(self):
        for g in gear.NEEDS_FIRST_MONTH:
            text = " ".join((gear.FOR[g], gear.HOW[g], gear.WHY[g], gear.BY_KEY[g][2],
                             gear.BY_KEY[g][3])).lower()
            for word in ("return", "profit", "gain", "trade", "buy", "sell", "$", "%"):
                self.assertNotIn(word, text, (g, word))
        # in the kit only with the flag on (or once earned: views/kit.py)
        self.assertNotIn("binoculars", gear.kit_keys(first_month=False))
        self.assertNotIn("watch", gear.kit_keys(first_month=False))
        self.assertNotIn("watch", gear.kit_keys(walk=False))
        self.assertIn("binoculars", gear.kit_keys())
        self.assertEqual(gear.GO["binoculars"][1], ("costs", "Dashboard"))
        self.assertEqual(gear.GO["watch"][1], ("checkin", "Dashboard"))


class KeptTests(unittest.TestCase):

    def test_only_tool_keys_are_kept(self):
        p = {}
        self.assertTrue(fm.note_used(p, "fees"))
        self.assertFalse(fm.note_used(p, "fees"))          # once
        self.assertFalse(fm.note_used(p, "VTI $1,234"))    # nothing else ever
        self.assertTrue(fm.note_used(p, "decoder"))
        self.assertEqual(p, {fm.PREF: {"used": ["fees", "decoder"]}})
        self.assertTrue(fm.costs_checked(p))

    def test_the_signals_already_kept(self):
        self.assertEqual(fm.READS_PREF, recap.LEARN_READS)
        self.assertFalse(fm.costs_checked({}))
        self.assertFalse(fm.costs_checked({recap.LEARN_READS: {"basics:funds": "2026-10-01"}}))
        self.assertTrue(fm.costs_checked({recap.LEARN_READS: {"basics:fees": "2026-10-01"}}))
        self.assertFalse(fm.first_walk({}))
        self.assertTrue(fm.first_walk({checkin.PREF_LOG: ["2026-10"]}))
        self.assertFalse(fm.costs_checked({fm.PREF: "junk"}))

    def test_the_card_uses_home_tasks(self):
        self.assertEqual(home_tasks.TASKS[fm.TASK], (home_tasks.WEEK, True))
        self.assertIn(fm.TASK, home_tasks.NAMES)
        p = home_tasks.with_mark({}, fm.TASK, date(2026, 10, 10), home_tasks.AWAY)
        self.assertEqual(p, {home_tasks.PREF: {fm.TASK: ["2026-W41", "away"]}})

    def test_the_flag(self):
        self.assertEqual(flags.FEATURES["first_month"], {"gates": (), "view": None})
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": ""}), \
                unittest.mock.patch.object(flags, "_secret", lambda name: None):
            self.assertFalse(flags.on("first_month"))


class WordingTests(unittest.TestCase):

    def test_no_figures_tickers_or_advice(self):
        lines = fm.templates()
        self.assertGreater(len(lines), 20)
        for line in lines:
            with self.subTest(line=line):
                self.assertNotRegex(line, r"\d")
                self.assertNotIn("$", line)
                self.assertNotIn("%", line)
                self.assertNotRegex(line, r"\b[A-Z]{2,5}\b")   # no tickers
                self.assertEqual(ai_policy.findings(line, allowed_tickers=set()), [])
                for word in BANNED:
                    self.assertNotRegex(line.lower(), rf"\b{word}\b")

    def test_the_walk_keeps_its_name(self):
        self.assertIn("Monthly Walk", fm.TITLES["walk"])
        self.assertEqual(fm.TITLES["practice"], "Try practice money")
        self.assertEqual(fm.TITLES["goal"], "Set a goal")
        self.assertEqual(fm.TITLES["costs"], "Check what your funds cost")

    def test_lines_for_a_later_email_are_the_same_for_everyone(self):
        a = fm.lines(fm.checklist({"profile_done": True}))
        b = fm.lines(fm.checklist({"profile_done": True}))
        self.assertEqual(a, b)
        self.assertEqual(set(a), {"title", "intro", "count", "items", "next", "why", "gear"})


class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_first_month_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        snap = date.today().isoformat()
        rows, totals = sample_data.snapshot_rows(snap)
        c = portfolio.connect(cls.db)
        try:
            def holder(name):
                uid = auth.create_user(c, name, PW)
                portfolio.write_snapshot(c, uid, {"snapshot_date": snap, "as_of_text": "t"},
                                         rows, totals, f"{name}.csv")
                return uid
            cls.amy = holder("amy")            # new, her own holdings
            cls.bea = auth.create_user(c, "bea", PW)   # new, nothing brought in yet
            cls.old = holder("olga")           # made long ago
            old_day = (date.today() - timedelta(days=60)).isoformat()
            c.execute("UPDATE users SET created_at = ? WHERE id = ?",
                      (f"{old_day} 09:00:00", cls.old))
            cls.carol = auth.create_user(c, "carol", PW)   # an advisor
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            portfolio.write_snapshot(c, cls.carol, {"snapshot_date": snap, "as_of_text": "t"},
                                     rows, totals, "carol.csv")
            cls.dana = holder("dana")          # carol's client
            auth.link_client(c, cls.carol, cls.dana)
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _app(self, uid, name, flag="first_month walk", **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")

        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        base = {"user_id": uid, "username": name, "auto_backfilled": True, "fs_hide": True,
                "page": "Dashboard"}
        for k, v in {**base, **state}.items():
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
    def _html(at):
        return " ".join(h.proto.body for h in at.get("html"))

    @staticmethod
    def _card(at):
        return next(h.proto.body for h in at.get("html") if CARD in h.proto.body)

    @staticmethod
    def _keys(at):
        return [b.key for b in at.button if b.key]

    def _prefs(self, uid):
        c = portfolio.connect(self.db)
        try:
            return prefs.load(c, uid)
        finally:
            c.close()

    def _set_prefs(self, uid, p):
        c = portfolio.connect(self.db)
        try:
            prefs.save(c, uid, p)
        finally:
            c.close()

    def test_the_card_for_a_young_account_with_holdings(self):
        self._set_prefs(self.amy, {})
        with self._app(self.amy, "amy") as at:
            card = self._card(at)
            self.assertIn(fm.TITLE, card)
            for title in fm.TITLES.values():
                self.assertIn(title, card)
            self.assertIn("0 of 5 done", card)
            text = re.sub(r"<[^>]+>", " ", card)
            self.assertNotIn("$", text)               # no figures, no tickers
            self.assertNotRegex(text, r"\b[A-Z]{2,5}\b")
            self.assertEqual(at.button(key="first_month_go").label, fm.GO["start"])
            self.assertIn("task_away_first_month", self._keys(at))
            self.assertIn("task_done_first_month", self._keys(at))
            # the next step's button opens that waypoint on Learn
            at.button(key="first_month_go").click().run()
            self.assertEqual(at.session_state["page"], "Get started")
            self.assertEqual(at.session_state["gs_at"], "profile")

    def test_put_away_keeps_only_the_key_and_the_week(self):
        self._set_prefs(self.amy, {})
        with self._app(self.amy, "amy") as at:
            at.button(key="task_away_first_month").click().run()
            self.assertNotIn(CARD, self._html(at))
        kept = self._prefs(self.amy)
        self.assertEqual(kept[home_tasks.PREF],
                         {fm.TASK: [home_tasks.task_period(fm.TASK, home_tasks.today()),
                                    home_tasks.AWAY]})
        self.assertNotIn(fm.PREF, kept)   # nothing of the card's own
        self._set_prefs(self.amy, {})

    def test_the_cost_step_opens_the_fee_check_and_keeps_its_key(self):
        # practice money done (the questions aren't): the card shows it done
        self._set_prefs(self.amy, {"get_started_done": ["practice"]})
        with self._app(self.amy, "amy") as at:
            self.assertIn("1 of 5 done", self._card(at))
            self.assertIn(">Binoculars</span>", self._html(at))   # in the kit with the flag on
            at.session_state["first_month_costs"] = True   # the binoculars' button (views/kit.py)
            at.run()
            self.assertNotIn("first_month_costs", at.session_state)
        kept = self._prefs(self.amy)
        self.assertEqual(kept.get(fm.PREF), {"used": ["fees"]})   # a key, nothing else
        self.assertTrue(fm.costs_checked(kept))
        self._set_prefs(self.amy, {})

    def test_before_money_the_card_points_to_practice_and_learn(self):
        self._set_prefs(self.bea, {})
        with self._app(self.bea, "bea") as at:
            self.assertIn(CARD, self._html(at))
            self.assertNotIn("task_away_first_month", self._keys(at))   # no X off This month
            self.assertEqual(at.button(key="first_month_go").label, fm.GO["start"])

    def test_an_older_account_earns_them_without_the_window(self):
        # olga read "Fees add up" and finished walks before the feature came
        seen = [k for k in gear.KEYS if k not in gear.NEEDS_FIRST_MONTH]
        self._set_prefs(self.old, {recap.LEARN_READS: {fm.FEES_READ: "2026-01-05"},
                                   checkin.PREF_LOG: ["2026-02", "2026-03"],
                                   "gear_seen": seen})
        with self._app(self.old, "olga") as at:
            self.assertNotIn("milestone_queue", at.session_state)   # no window
            self.assertIn(">Binoculars</span>", self._html(at))     # but in the kit, earned
        kept = self._prefs(self.old)
        self.assertIn("binoculars", kept["gear_seen"])   # taken as seen: no window later
        self.assertIn("watch", kept["gear_seen"])
        self.assertIn("by", kept["gear_dates"]["binoculars"])      # "earned by", not "on"
        self.assertIn("by", kept["gear_dates"]["watch"])
        self._set_prefs(self.old, {})

    def test_not_for_an_older_account(self):
        with self._app(self.old, "olga") as at:
            self.assertNotIn(CARD, self._html(at))
            self.assertNotIn("first_month_go", self._keys(at))

    def test_not_while_the_flag_is_off(self):
        # the fees read already counts, but with the flag off nothing new shows
        seen = [k for k in gear.KEYS if k != "binoculars"]
        self._set_prefs(self.amy, {recap.LEARN_READS: {fm.FEES_READ: "2026-10-01"},
                                   "gear_seen": seen})
        with self._app(self.amy, "amy", flag="walk") as at:
            self.assertNotIn(CARD, self._html(at))
            self.assertNotIn(">Binoculars</span>", self._html(at))
            self.assertNotIn("milestone_queue", at.session_state)
        self.assertEqual(self._prefs(self.amy).get("gear_seen"), seen)
        # on: the read earns the binoculars, celebrated once
        with self._app(self.amy, "amy") as at:
            self.assertEqual(at.session_state["milestone_queue"], ["binoculars"])
        self.assertIn("binoculars", self._prefs(self.amy)["gear_seen"])
        self._set_prefs(self.amy, {})

    def test_not_for_an_advisors_client(self):
        with self._app(self.dana, "dana") as at:
            self.assertNotIn(CARD, self._html(at))

    def test_not_for_an_advisor_in_a_clients_account(self):
        before = self._prefs(self.dana)
        with self._app(self.carol, "carol", two_step_ok=self.carol_ok,
                       active_user_id=self.dana) as at:
            self.assertNotIn(CARD, self._html(at))
            self.assertNotIn("first_month_go", self._keys(at))
        self.assertEqual(self._prefs(self.dana), before)

    def test_not_for_an_advisors_own_portfolio(self):
        with self._app(self.carol, "carol", two_step_ok=self.carol_ok) as at:
            self.assertNotIn(CARD, self._html(at))


if __name__ == "__main__":
    unittest.main()
