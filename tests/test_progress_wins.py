"""What you did vs what the market did (progress_split.py, flag progress_split)
and Your wins (wins.py, flag wins).

The split's maths from logged money, imported deposits and logged values -
and "not known" when nothing says what was added, never a guess; the one
read gives what plans.money_moves and recap.value_points give; percentages
portfolios get no dollars; hidden amounts stay hidden. The wins: each worked
out from data already kept, kept as keys and days only, an undo only for one
the person marked, fees never offered as something to earn. Every fixed line
passes the conclusion policy and a banned-word list. In the app: off unless
set; an advisor in a client's account sees the split, not the wins, and
writes nothing.

    python -m unittest tests.test_progress_wins        (from the repo root)
"""

import contextlib
import json
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

import advisor  # noqa: E402
import ai_policy  # noqa: E402
import auth  # noqa: E402
import flags  # noqa: E402
import manual_entry  # noqa: E402
import plans  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import progress_split as ps  # noqa: E402
import recap  # noqa: E402
import sample_data  # noqa: E402
import two_step  # noqa: E402
import wins  # noqa: E402

PW = "pw-123456789"
BANNED = ("should", "best", "recommend", "buy", "sell", "will", "expect", "predict",
          "forecast", "likely", "urgent", "guarantee", "safe", "enough", "withdraw")
TODAY = date(2026, 10, 7)


def _facts(**kw):
    out = {"hand": [], "brokerage": [], "income": [], "window": None, "sources": {},
           "positions": {}, "cash": {}, "visits": [], "first_funds": [], "first_day": None}
    out.update(kw)
    return out


def _visits(*pts, snap="2025-12-01"):
    return [(f"{d}T12:00:00Z", snap, v) for d, v in pts]


SOURCES = {"2025-12-01": ["manual entry"]}


class SplitTests(unittest.TestCase):

    def test_the_change_is_what_was_added_plus_the_market(self):
        f = _facts(hand=[("2026-03-05", 1000.0), ("2026-04-05", 1000.0), ("2026-05-05", 1500.0)],
                   sources=SOURCES, visits=_visits(("2025-12-20", 50000.0), ("2026-06-30", 55000.0)))
        r = ps.split(f, ps.YEAR, TODAY, current=60000.0)
        self.assertEqual(r["state"], ps.SPLIT)
        self.assertEqual((r["v0"], r["v1"], r["added"], r["market"], r["change"]),
                         (50000.0, 60000.0, 3500.0, 6500.0, 10000.0))
        self.assertAlmostEqual(r["share"], 35.0)
        self.assertEqual(r["deposits"], 3)
        self.assertIsNone(r["since"])     # December's value starts this year
        # the chart: 0 at the start, June's stop, then today
        self.assertEqual(r["series"][0], {"date": "2025-12-20", "added": 0, "market": 0.0})
        self.assertEqual(r["series"][1], {"date": "2026-06-30", "added": 3500.0, "market": 1500.0})
        self.assertEqual(r["series"][-1], {"date": "2026-10-07", "added": 3500.0, "market": 6500.0})
        money = lambda v: f"${v:,.0f}"   # noqa: E731
        self.assertEqual(ps.lines(r, money)[0], "Of the $10,000 your portfolio grew, $3,500 was "
                                                "money you added and $6,500 came from the market.")

    def test_a_fall_is_said_both_ways_and_no_share_is_made_up(self):
        f = _facts(hand=[("2026-03-05", 2000.0)], sources=SOURCES,
                   visits=_visits(("2025-12-31", 50000.0)))
        r = ps.split(f, ps.YEAR, TODAY, current=51000.0)
        self.assertEqual((r["added"], r["market"]), (2000.0, -1000.0))
        self.assertIsNone(r["share"])
        money = lambda v: f"${v:,.0f}"   # noqa: E731
        self.assertIn("down $1,000", ps.lines(r, money)[0])
        r = ps.split(f, ps.YEAR, TODAY, current=47000.0)
        self.assertIn("more than the $2,000 you added", ps.lines(r, money)[0])

    def test_unknown_when_nothing_says_what_was_added(self):
        f = _facts(sources=SOURCES, visits=_visits(("2025-12-31", 50000.0)))
        r = ps.split(f, ps.YEAR, TODAY, current=56000.0)
        self.assertEqual(r["state"], ps.UNKNOWN)
        self.assertEqual(r["change"], 6000.0)
        self.assertNotIn("added", r)
        self.assertNotIn("market", r)

    def test_only_an_activity_export_covers_only_its_days(self):
        f = _facts(brokerage=[("2026-03-10", 500.0), ("2026-05-10", 500.0)],
                   window=("2026-03-01", "2026-06-30"), sources=SOURCES,
                   income=[("2026-04-01", 40.0)],
                   visits=_visits(("2025-12-31", 40000.0), ("2026-03-01", 45000.0),
                                  ("2026-06-30", 48000.0)))
        r = ps.split(f, ps.YEAR, TODAY, current=52000.0)
        # from the history's first day to its last, not January to today
        self.assertEqual((r["start"], r["end"]), ("2026-03-01", "2026-06-30"))
        self.assertEqual((r["added"], r["market"]), (1000.0, 2000.0))
        self.assertEqual(r["since"], "2026-03-01")
        self.assertEqual(r["until"], "2026-06-30")
        self.assertEqual(r["income"], 40.0)

    def test_a_hand_entry_inside_the_imported_history_isnt_counted_twice(self):
        f = _facts(hand=[("2026-03-10", 500.0), ("2026-08-01", 300.0)],
                   brokerage=[("2026-03-10", 500.0)], window=("2026-03-01", "2026-03-31"))
        self.assertEqual(ps.moves(f), [("2026-03-10", 500.0), ("2026-08-01", 300.0)])

    def test_pretend_portfolios(self):
        f = _facts(hand=[("2026-03-05", 100.0), ("2026-04-05", 100.0)],
                   sources={"2026-01-02": [ps.PCT_SOURCE]},
                   positions={"2026-01-02": (2, 2, 10000.0)},
                   visits=_visits(("2026-01-02", 10000.0), snap="2026-01-02"))
        self.assertEqual(ps.split(f, ps.YEAR, TODAY, pretend=ps.SAMPLE_SOURCE)["state"], ps.PRETEND)
        r = ps.split(f, ps.YEAR, TODAY, current=12000.0, pretend=ps.PCT_SOURCE)
        self.assertEqual(r["state"], ps.PERCENTAGES)
        self.assertEqual(r["months_added"], 2)
        self.assertFalse(any(k in r for k in ("added", "market", "change", "v0", "v1")))
        self.assertEqual(ps.value_points(f), [])   # pretend dollars are never values

    def test_not_enough_with_one_value(self):
        f = _facts(hand=[("2026-03-05", 100.0)], sources=SOURCES,
                   visits=_visits(("2026-10-07", 1000.0)))
        self.assertEqual(ps.split(f, ps.YEAR, TODAY)["state"], ps.NOT_ENOUGH)

    def test_money_added_after_the_last_update_is_flagged(self):
        f = _facts(hand=[("2026-10-01", 1000.0)], sources=SOURCES,
                   visits=_visits(("2025-12-31", 50000.0)))
        self.assertTrue(ps.split(f, ps.YEAR, TODAY, current=52000.0)["late"])

    def test_market_pct(self):
        rows = [{"t": "2025-12-31", "portfolio_value": 100.0, "n_priced": 2},
                {"t": "2026-01-02", "portfolio_value": 90.0, "n_priced": 1},
                {"t": "2026-10-06", "portfolio_value": 110.0, "n_priced": 2}]
        self.assertEqual(ps.market_pct(rows, "2026-01-01"), 10.0)
        self.assertIsNone(ps.market_pct(rows[:1], "2026-01-01"))


class ReadTests(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_ps_")
        self.c = portfolio.connect(os.path.join(self.dir, "r.db"))

    def tearDown(self):
        self.c.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_one_read_gives_what_the_app_already_counts(self):
        c = self.c
        uid = auth.create_user(c, "ann", PW)
        other = auth.create_user(c, "olly", PW)
        for u in (uid, other):
            sample_data.load(c, u, today=date(2026, 9, 1))
            c.execute("UPDATE snapshots SET source_file = ? WHERE user_id = ?",
                      (manual_entry.SOURCE, u))
            plans.add_contribution(c, u, "2026-09-10", 250.0)
            c.execute("INSERT INTO value_log (user_id, logged_at, snapshot_date, "
                      "portfolio_value) VALUES (?, '2026-09-20T15:00:00Z', '2026-09-01', ?)",
                      (u, 36000.0 + u))
        c.execute("INSERT INTO transactions (user_id, account, trade_date, action, amount, "
                  "origin) VALUES (?, 'Brokerage', '2026-09-15', 'DEPOSIT', 400, 'imported')",
                  (uid,))
        c.commit()
        f = ps.read(c, uid)
        self.assertEqual(ps.value_points(f), recap.value_points(c, uid))
        expect = sorted((m["date"], m["amount"]) for m in plans.money_moves(c, uid)
                        if m["counted"])
        self.assertEqual(ps.moves(f), expect)
        self.assertEqual(f["window"], ("2026-09-15", "2026-09-15"))
        self.assertEqual(f["first_day"], "2026-09-01")
        self.assertEqual({r["symbol"] for r in f["first_funds"]},
                         {h[1] for h in sample_data.HOLDINGS})
        # only this account's rows
        self.assertNotIn(36000.0 + other, [v for _, v in ps.value_points(f)])


class WinTests(unittest.TestCase):

    def test_three_months_in_a_row(self):
        moves = [("2026-03-05", 300.0), ("2026-04-05", 300.0), ("2026-05-02", 200.0),
                 ("2026-05-20", 250.0)]
        runs = wins.streaks(moves)
        self.assertEqual(runs[0]["months"], ["2026-03", "2026-04", "2026-05"])
        self.assertEqual(runs[0]["done_on"], "2026-05-20")
        # a gap breaks it; a month with more out than in doesn't count
        broken = [("2026-03-05", 300.0), ("2026-05-05", 300.0), ("2026-06-05", 300.0),
                  ("2026-06-20", -500.0)]
        self.assertFalse(any(r["done_on"] for r in wins.streaks(broken)))
        self.assertEqual(wins.current_streak([("2026-09-05", 1.0), ("2026-10-01", 1.0)], TODAY), 2)
        ev = wins.evaluate(prefs={}, today=TODAY, moves=moves)
        reg = next(w for w in ev["wins"] if w["key"] == wins.REGULAR)
        self.assertTrue(reg["earned"])
        self.assertEqual(ev["new"][wins.REGULAR], "2026-05-20")
        money = lambda v: f"${v:,.0f}"   # noqa: E731
        self.assertEqual(wins.words(reg, money)["number"], "$350 a month")
        reg_pct = {**reg, "pct_only": True}
        self.assertEqual(wins.words(reg_pct, money)["number"], "3 months in a row")

    def test_lower_fees_found_only_after_an_update(self):
        first = [{"symbol": "AAA", "asset_type": "ETFs & Closed End Funds", "quote_type": "ETF",
                  "value": 10000.0, "expense_ratio": 0.0050}]
        now = [{"symbol": "BBB", "asset_type": "ETFs & Closed End Funds", "quote_type": "ETF",
                "value": 20000.0, "expense_ratio": 0.0005}]
        fw = wins.fee_win(first, "2026-01-02", now, "2026-09-01")
        self.assertAlmostEqual(fw["drop"], 0.0045)
        self.assertAlmostEqual(fw["yearly"], 90.0)
        self.assertAlmostEqual(fw["long"], 90.0 * ((1.06 ** 30 - 1) / 0.06))
        self.assertIsNone(wins.fee_win(first, "2026-01-02", now, "2026-01-02"))   # no update
        self.assertIsNone(wins.fee_win(now, "2026-01-02", first, "2026-09-01"))   # went up
        ev = wins.evaluate(prefs={}, today=TODAY, first_rows=first, first_day="2026-01-02",
                           now_rows=now, latest_day="2026-09-01")
        fee = next(w for w in ev["wins"] if w["key"] == wins.FEES)
        t = wins.words(fee, lambda v: f"${v:,.0f}")
        self.assertEqual(t["number"], "$90 a year")
        self.assertIn("hypothetical", t["note"])
        self.assertEqual(wins.words(fee, lambda v: "•••")["number"], "••• a year")   # hidden
        self.assertEqual(wins.words({**fee, "pct_only": True}, lambda v: "x")["number"],
                         "0.45 points a year")
        # never offered as one to earn: that would reward changing funds
        ev = wins.evaluate(prefs={}, today=TODAY)
        self.assertNotIn(wins.FEES, [w["key"] for w in wins.shown(ev["wins"])[1]])

    def test_the_match_from_the_free_money_check_or_the_answer(self):
        full = {"match_check": {"salary": 80000.0, "contrib_pct": 6.0,
                                "preset": "50% of the first 6%"}}
        ev = wins.evaluate(prefs=full, today=TODAY)
        m = next(w for w in ev["wins"] if w["key"] == wins.MATCH)
        self.assertTrue(m["earned"])
        self.assertEqual(wins.words(m, lambda v: f"${v:,.0f}")["number"], "$2,400 a year")
        part = {"match_check": {**full["match_check"], "contrib_pct": 3.0}}
        m = next(w for w in wins.evaluate(prefs=part, today=TODAY)["wins"]
                 if w["key"] == wins.MATCH)
        self.assertFalse(m["earned"])
        self.assertAlmostEqual(wins.words(m, str)["progress"], 0.5)
        m = next(w for w in wins.evaluate(prefs={}, today=TODAY,
                                          profile={"employer_match": wins.MATCH_ANSWER})["wins"]
                 if w["key"] == wins.MATCH)
        self.assertTrue(m["earned"])
        no = wins.evaluate(prefs={}, today=TODAY, profile={"employer_match": wins.NO_MATCH_ANSWER})
        self.assertNotIn(wins.MATCH, [w["key"] for w in no["wins"]])

    def test_cushion_and_roth(self):
        ev = wins.evaluate(prefs={}, today=TODAY, profile={"emergency_fund": "3-6 months"},
                           accounts=["Roth IRA ...123", "Brokerage"])
        got = {w["key"]: w["earned"] for w in ev["wins"]}
        self.assertTrue(got[wins.CUSHION])
        self.assertTrue(got[wins.ROTH])
        self.assertFalse(got[wins.DEBT])
        ev = wins.evaluate(prefs={}, today=TODAY, profile={"emergency_fund": "Under 3 months"})
        c = next(w for w in ev["wins"] if w["key"] == wins.CUSHION)
        self.assertIn("Under 3 months", wins.words(c, str)["how"])

    def test_kept_as_keys_and_days_only_and_stays_earned(self):
        p = wins.with_earned({"other": 1}, {wins.REGULAR: "2026-05-20", "nope": "2026-01-01",
                                            wins.ROTH: "not a day"})
        self.assertEqual(p, {"other": 1, wins.PREF: {wins.REGULAR: {"on": "2026-05-20"}}})
        p = wins.with_mark(p, wins.DEBT, TODAY, True)
        self.assertEqual(p[wins.PREF][wins.DEBT], {"on": "2026-10-07", "self": True})
        self.assertEqual(wins.with_mark(p, wins.REGULAR, TODAY, False), p)   # not undoable
        self.assertEqual(wins.with_mark(p, wins.FEES, TODAY, True), p)       # not markable
        p2 = wins.with_mark(p, wins.DEBT, TODAY, False)
        self.assertNotIn(wins.DEBT, p2[wins.PREF])
        # earned once, earned for good - even when the data no longer shows it
        ev = wins.evaluate(prefs=p, today=TODAY)
        reg = next(w for w in ev["wins"] if w["key"] == wins.REGULAR)
        self.assertEqual((reg["earned"], reg["on"]), (True, "2026-05-20"))
        self.assertEqual(ev["new"], {})
        for v in p[wins.PREF].values():
            self.assertLessEqual(set(v), {"on", "self"})

    def test_recent_for_homes_card(self):
        p = {wins.PREF: {wins.REGULAR: {"on": "2026-05-20"}, wins.DEBT: {"on": "2026-10-01",
                                                                          "self": True}}}
        ev = wins.evaluate(prefs=p, today=TODAY)
        self.assertEqual([w["key"] for w in wins.recent(ev["wins"], TODAY)], [wins.DEBT])


class WordingTests(unittest.TestCase):

    def _all(self):
        return ps.templates() + wins.templates()

    def test_every_template_passes_the_conclusion_policy(self):
        for line in self._all():
            with self.subTest(line=line[:50]):
                self.assertEqual(ai_policy.findings(line, allowed_tickers=set()), [])

    def test_no_banned_words(self):
        for line in self._all():
            for word in BANNED:
                self.assertNotRegex(line.lower(), rf"\b{word}\b", line)

    def test_no_trail_words(self):
        for line in self._all():
            self.assertNotRegex(line.lower(), r"\b(trail|storm|summit|expedition|journey)\b", line)

    def test_brokerages_named_alphabetically_only(self):
        with open(os.path.join(REPO, "views", "progress_split.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("brokerages.sort_key", src)
        self.assertNotRegex(src, r"(?i)schwab|fidelity|vanguard|robinhood")

    def test_never_in_the_ai(self):
        for name in ("advisor.py", "context_card.py", "ai_gateway.py", "ai_tools.py",
                     "ai_library.py", os.path.join("views", "assistant.py")):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                self.assertNotRegex(fh.read(), r"\b(wins|progress_split)\.", name)

    def test_the_flags_are_off_unless_set(self):
        for name in ("progress_split", "wins"):
            self.assertEqual(flags.FEATURES[name], {"gates": (), "view": None})
            with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": ""}), \
                    unittest.mock.patch.object(flags, "_secret", lambda n: None):
                self.assertFalse(flags.on(name))


# --------------------------------------------------------------------------- #
# in the app
# --------------------------------------------------------------------------- #
class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_wins_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        today = date.today()
        c = portfolio.connect(cls.db)
        try:
            def real(uid, name):
                sample_data.load(c, uid, today=today - timedelta(days=25))
                c.execute("UPDATE snapshots SET source_file = ? WHERE user_id = ?",
                          (manual_entry.SOURCE, uid))
                c.execute("INSERT INTO value_log (user_id, logged_at, snapshot_date, "
                          "portfolio_value) VALUES (?, ?, ?, 30000)",
                          (uid, f"{today - timedelta(days=30)}T15:00:00Z",
                           (today - timedelta(days=25)).isoformat()))
                plans.add_contribution(c, uid, (today - timedelta(days=15)).isoformat(), 1000)
                plans.add_contribution(c, uid, (today - timedelta(days=10)).isoformat(), 500)
                for d in ("2025-03-05", "2025-04-05", "2025-05-05"):
                    plans.add_contribution(c, uid, d, 100)
            cls.bob = auth.create_user(c, "bob", PW)
            real(cls.bob, "bob")
            prefs.save(c, cls.bob, {"first_steps": {"done": True}})
            cls.pam = auth.create_user(c, "pam", PW)   # a percentages portfolio
            rows, totals = sample_data.snapshot_rows((today - timedelta(days=25)).isoformat())
            portfolio.write_snapshot(c, cls.pam, {"snapshot_date": rows[0]["snapshot_date"],
                                               "as_of_text": None},
                                     rows, totals, manual_entry.PCT_SOURCE)
            plans.add_contribution(c, cls.pam, (today - timedelta(days=5)).isoformat(), 777)
            prefs.save(c, cls.pam, {"first_steps": {"done": True}})
            cls.carol = auth.create_user(c, "carol", PW)
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dana = auth.create_user(c, "dana", PW)
            real(cls.dana, "dana")
            advisor.save_profile(c, cls.dana, {"emergency_fund": "3-6 months"})
            auth.link_client(c, cls.carol, cls.dana)
            prefs.save(c, cls.dana, {"first_steps": {"done": True}})
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _app(self, uid, name, flag="progress_split wins", page="Dashboard", **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": page,
                     "auto_backfilled": True, "income_synced": True, **state}.items():
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
        parts += [s.value for s in at.subheader]
        return " ".join(parts).replace("<wbr>", "").replace("\\$", "$")

    def _prefs(self, uid):
        c = portfolio.connect(self.db)
        try:
            return prefs.load(c, uid)
        finally:
            c.close()

    def _card(self, at):
        text = self._text(at)
        self.assertIn(ps.TITLE, text)
        return text

    def test_off_unless_set(self):
        with self._app(self.bob, "bob", flag="") as at:
            self.assertNotIn(ps.TITLE, self._text(at))
            self.assertNotIn("wins_open", [b.key for b in at.button])
        with self._app(self.bob, "bob", flag="", page="Plan") as at:
            self.assertNotIn(wins.PAGE_TITLE, [t.label for t in at.tabs])

    def test_the_split_on_home_and_hidden_amounts(self):
        with self._app(self.bob, "bob") as at:
            text = self._card(at)
            self.assertIn("+$1,500", text)               # what you did
            self.assertIn(ps.YOU_SUB_COUNT.format(n=2), text)
            self.assertIn(ps.SOURCE_NOTE, text)
            self.assertIn(ps.STEADY, text)
            at.session_state["hide_amounts"] = True
            at.run()
            text = self._text(at)
            self.assertNotIn("+$1,500", text)
            self.assertNotRegex(text.split(ps.YOU_LABEL)[1][:200], r"\$\d")
            # since you started: the same money, from the first value
            at.segmented_control(key="ps_period").set_value(ps.ALL).run()
            self.assertEqual([e.message for e in at.exception], [])

    def test_a_percentages_portfolio_shows_no_dollars(self):
        with self._app(self.pam, "pam") as at:
            text = self._card(at)
            self.assertIn(ps.PCT_LINE, text)
            self.assertIn(ps.PCT_ADDED.format(n=1), text)
            self.assertNotIn("777", text)
            self.assertNotIn(ps.YOU_SUB, text)

    def test_wins_on_home_and_plan_kept_as_keys_and_days(self):
        p = self._prefs(self.bob)
        p.pop(wins.PREF, None)
        c = portfolio.connect(self.db)
        try:
            prefs.save(c, self.bob, p)
        finally:
            c.close()
        with self._app(self.bob, "bob") as at:
            text = self._text(at)
            self.assertIn(wins.CARD_TITLE, text)     # the Roth account: earned today
            self.assertIn("wins_open", [b.key for b in at.button])
        kept = self._prefs(self.bob)[wins.PREF]
        self.assertEqual(kept[wins.REGULAR], {"on": "2025-05-05"})
        self.assertIn(wins.ROTH, kept)
        with self._app(self.bob, "bob", page="Plan") as at:
            self.assertIn(wins.PAGE_TITLE, [t.label for t in at.tabs])
            text = self._text(at)
            self.assertIn(wins.TITLES[wins.REGULAR], text)
            self.assertIn("$100 a month", text)
            at.button(key="win_mark_debt").click().run()
        kept = self._prefs(self.bob)[wins.PREF]
        self.assertEqual(kept[wins.DEBT]["self"], True)
        for v in kept.values():
            self.assertLessEqual(set(v), {"on", "self"})
            self.assertRegex(v["on"], r"^\d{4}-\d\d-\d\d$")
        self.assertFalse(re.search(r"\d", json.dumps({k: {kk: vv for kk, vv in v.items()
                                                          if kk != "on"}
                                                      for k, v in kept.items()})))

    def test_an_advisor_in_a_clients_account_sees_the_split_not_the_wins(self):
        before = self._prefs(self.dana)
        state = {"two_step_ok": self.carol_ok, "active_user_id": self.dana}
        with self._app(self.carol, "carol", **state) as at:
            text = self._card(at)
            self.assertIn("+$1,500", text)
            self.assertNotIn(wins.CARD_TITLE, text)
            self.assertFalse([b for b in at.button if str(b.key).startswith("win")])
        with self._app(self.carol, "carol", page="Plan", **state) as at:
            self.assertNotIn(wins.PAGE_TITLE, [t.label for t in at.tabs])
        self.assertEqual(self._prefs(self.dana), before)
        self.assertNotIn(wins.PREF, self._prefs(self.dana))


if __name__ == "__main__":
    unittest.main()
