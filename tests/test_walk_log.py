"""The Expedition Log (ROADMAP R3, expedition_log.py) and the Do-Nothing
Ledger (R2, ledger.py): the log line (percentages and facts only - never a
dollar sign or an amount), what's kept per walk (no figures), the ledger's
rule (no sale since the walk before), the hypothetical both ways and its
label, never a grade - and in the app: shown with their flags, hidden
without, never in an advisor's view, never in the AI's or advisor's files.

    python -m unittest tests.test_walk_log        (from the repo root)
"""

import html
import os
import re
import sys
import unittest
from datetime import date, datetime, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import checkin  # noqa: E402
import expedition_log  # noqa: E402
import ledger  # noqa: E402
import prefs  # noqa: E402
import recap  # noqa: E402
import test_walk  # noqa: E402

OCT5 = date(2026, 10, 5)
GROUPED = re.compile(r"\d,\d{3}")


def _plain(test, text):
    """No dollar sign, no grouped digits (an amount), no grade."""
    test.assertNotIn("$", text)
    test.assertIsNone(GROUPED.search(text), text)
    for word in ("right call", "wrong", "smart", "good decision", "well done"):
        test.assertNotIn(word, text.lower())


def _bodies(at, needle):
    """The app's html pieces that contain `needle`."""
    return [html.unescape(h.proto.body) for h in at.get("html")
            if needle in html.unescape(h.proto.body)]


class LogLineTests(unittest.TestCase):

    def test_the_line_from_percentages_and_facts(self):
        rec = {"on": "2026-10-05", "updated": True, "drift": {"class": "Stocks", "pts": 4},
               "market": 1.8, "sold": False, "note": True}
        text = expedition_log.line("2026-10", rec, {"kind": "within"})
        self.assertEqual(text, "October 2026: Holdings updated. Largest drift: stocks, 4 points "
                               "above target. Your mix rose 1.8% over the month before (prices "
                               "only). Your plan said nothing to do. You wrote a note to future "
                               "you.")
        _plain(self, text)
        text = expedition_log.line("2026-03", {"updated": False, "drift": {"class": "Bonds",
                                                                          "pts": -1},
                                               "market": -6.25},
                                   {"kind": "next", "class": "Bonds", "how": "most"})
        self.assertIn("Nothing changed in your holdings.", text)
        self.assertIn("bonds, 1 point below target", text)
        self.assertIn("fell 6.2%", text)
        self.assertIn("Your plan pointed new money mostly to bonds.", text)
        _plain(self, text)
        # no target, no prices: those parts are left out
        text = expedition_log.line("2026-04", {}, {"kind": "none"})
        self.assertEqual(text, "April 2026: Nothing changed in your holdings. No target mix "
                               "yet, so no verdict.")

    def test_only_fixed_facts_are_kept_never_amounts(self):
        p = {}
        kept = expedition_log.record(p, "2026-10", {
            "on": "2026-10-05", "updated": 1, "value": 123456.0, "amount": "$5,000",
            "drift": {"class": "Stocks", "pts": 4.4, "value": 900.0}, "market": 1.83,
            "sold": 0, "note": "I'm holding for the house"})
        self.assertEqual(kept, {"on": "2026-10-05", "updated": True,
                                "drift": {"class": "Stocks", "pts": 4}, "market": 1.8,
                                "sold": False, "note": True})
        self.assertEqual(p[expedition_log.PREF_LOG], {"2026-10": kept})
        # a class outside the fixed list is dropped
        self.assertIsNone(expedition_log.clean({"drift": {"class": "VTI", "pts": 3}})["drift"])

    def test_largest_drift_and_the_months_move(self):
        self.assertEqual(expedition_log.largest_drift({"Stocks": 74.0, "Bonds": 25.0, "Cash": 1.0},
                                                      {"Stocks": 50.0, "Bonds": 50.0}),
                         {"class": "Bonds", "pts": -25})
        self.assertIsNone(expedition_log.largest_drift({"Stocks": 100.0}, {}))
        pts = [((OCT5 - timedelta(days=d)).isoformat(), 100.0 + (30 - d)) for d in range(31)]
        self.assertEqual(expedition_log.market_move(pts, OCT5), 30.0)
        # closes that start late in the month: too little to say
        self.assertIsNone(expedition_log.market_move(pts[:5], OCT5))
        self.assertIsNone(expedition_log.market_move([], OCT5))

    def test_the_previous_walks_day(self):
        p = {checkin.PREF_VERDICTS: {"2026-08": {"kind": "within", "on": "2026-08-04"}},
             expedition_log.PREF_LOG: {"2026-09": {"on": "2026-09-07"}}}
        self.assertEqual(expedition_log.previous_day(p, "2026-10"), "2026-09-07")
        self.assertEqual(expedition_log.previous_day(p, "2026-09"), "2026-08-04")
        self.assertIsNone(expedition_log.previous_day(p, "2026-08"))

    def test_year_in_review_gets_the_years_lines(self):
        p = {expedition_log.PREF_LOG: {"2025-12": {"on": "2025-12-02"},
                                       "2026-02": {"on": "2026-02-03", "updated": True},
                                       "2026-01": {"on": "2026-01-05"}}}
        self.assertEqual([x["month"] for x in expedition_log.lines(p, 2026, newest_first=False)],
                         ["2026-01", "2026-02"])
        # never part of the version to share
        with open(os.path.join(REPO, "recap.py"), encoding="utf-8") as fh:
            src = fh.read()
        share = src[src.index("def share_lines"):src.index("def has_money")]
        self.assertNotIn("walk_log", share)


class SoldSinceTests(test_walk._DB):

    def _sale(self, uid, day, action="SELL"):
        self.conn.execute("INSERT INTO transactions (user_id, account, trade_date, action, "
                          "symbol) VALUES (?, 'Brokerage', ?, ?, 'VTI')", (uid, day, action))
        self.conn.commit()

    def test_any_sale_since_the_walk_before(self):
        self._sale(1, "2026-09-20")
        self._sale(1, "2026-10-02", "BUY")
        self._sale(2, "2026-10-03")                 # someone else's
        self.assertTrue(expedition_log.sold_since(self.conn, 1, "2026-09-07", "2026-10-05"))
        self.assertFalse(expedition_log.sold_since(self.conn, 1, "2026-09-20", "2026-10-05"))
        self.assertFalse(expedition_log.sold_since(self.conn, 1, None, "2026-10-05"))
        self.assertTrue(expedition_log.sold_since(self.conn, 1, None, "2026-09-30"))

    def test_year_in_review_carries_the_years_lines(self):
        p = {expedition_log.PREF_LOG: {"2025-12": {"on": "2025-12-02"},
                                       "2026-09": {"on": "2026-09-07", "market": -2.0}},
             checkin.PREF_VERDICTS: {"2026-09": {"kind": "within", "on": "2026-09-07"}}}
        r = recap.build(self.conn, 1, 2026, OCT5, prefs=p)
        self.assertEqual(r["walk_log"], [
            "September 2026: Nothing changed in your holdings. Your mix fell 2.0% over the "
            "month before (prices only). Your plan said nothing to do."])
        self.assertNotIn("September 2026", recap.share_text(r))


class LedgerTests(unittest.TestCase):

    def test_an_entry_only_for_a_walk_with_no_sale(self):
        p = {expedition_log.PREF_LOG: {"2026-08": {"on": "2026-08-04", "sold": False},
                                       "2026-09": {"on": "2026-09-07", "sold": True},
                                       "2026-10": {"on": "2026-10-05"}},
             # a walk from before the log: nothing known of sales, so no entry
             checkin.PREF_VERDICTS: {"2026-07": {"kind": "within", "on": "2026-07-01"}}}
        self.assertEqual(ledger.entries(p), [{"month": "2026-10", "on": "2026-10-05"},
                                             {"month": "2026-08", "on": "2026-08-04"}])
        self.assertEqual(ledger.entry_text("2026-10"),
                         "You stayed with your plan in October 2026.")

    def test_both_directions_honestly(self):
        pts = [("2026-08-04", 110.0), ("2026-09-07", 90.0), ("2026-10-05", 100.0)]
        ahead = ledger.what_if(pts, "2026-08-04")      # it fell since: selling would be ahead
        behind = ledger.what_if(pts, "2026-09-07")     # it rose since: selling would be behind
        self.assertEqual((ahead, behind), (10.0, -10.0))
        a = ledger.what_if_text("Aug 4, 2026", ahead)
        b = ledger.what_if_text("Sep 7, 2026", behind)
        self.assertEqual(a, "Hypothetical: if you had sold everything on Aug 4, 2026 and held "
                            "cash, you'd be about 10.0% ahead of where your mix is now.")
        self.assertIn("about 10.0% behind where your mix is now", b)
        self.assertIn("about where your mix is now", ledger.what_if_text("x", 0.2))
        for text in (a, b, ledger.HINDSIGHT, ledger.entry_text("2026-10")):
            _plain(self, text)
        self.assertIn("both ways", ledger.HINDSIGHT)
        self.assertIn("isn't a grade", ledger.HINDSIGHT)

    def test_no_prices_no_hypothetical(self):
        pts = [("2026-09-01", 100.0), ("2026-10-05", 90.0)]
        self.assertIsNone(ledger.what_if(pts, "2026-10-05"))      # the walk was the last close
        self.assertIsNone(ledger.what_if(pts, "2026-09-20"))      # no close within a week
        self.assertIsNone(ledger.what_if([], "2026-09-01"))


class NeverSharedTests(unittest.TestCase):
    def test_never_sent_to_the_ai_or_an_advisor(self):
        for name in ("advisor.py", "meeting.py", "reports.py", "overview.py", "advising.py",
                     "proposals.py", "weekly_email.py", "client_plan.py", "export.py",
                     os.path.join("views", "assistant.py"), os.path.join("views", "clients.py"),
                     os.path.join("views", "meeting.py"), os.path.join("views", "reports.py")):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                text = fh.read()
            for word in ("expedition_log", "walk_log", "ledger"):
                self.assertNotIn(word, text, (name, word))


# --------------------------------------------------------------------------- #
# in the app
# --------------------------------------------------------------------------- #
class _LogApp(test_walk._WalkApp):
    FLAGS = "walk,walk_log,ledger"

    @classmethod
    def seed(cls, c):
        super().seed(c)
        today = datetime.now().date()
        month = checkin.month_of(today)
        earlier = (today - timedelta(days=40)).isoformat()
        p = prefs.load(c, cls.dana)
        p[expedition_log.PREF_LOG] = {
            earlier[:7]: {"on": earlier, "updated": False, "sold": False,
                          "drift": {"class": "Stocks", "pts": 3}, "market": 1.2},
            month: {"on": today.isoformat(), "updated": True, "sold": True}}
        prefs.save(c, cls.dana, p)
        cls.earlier = earlier


class AppTests(_LogApp):

    def test_a_finished_walk_writes_its_line(self):
        today = datetime.now().date()
        month = checkin.month_of(today)
        with self._run(self.bea, "bea") as at:
            self._walk_to_verdict(at)
            at.button(key="walk_finish").click().run()
            text = html.unescape(self._text(at))
            label = expedition_log.month_label(month)
            self.assertIn(f"{label}: Nothing changed in your holdings. Largest drift: bonds, "
                          "25 points below target. Your plan pointed new money to bonds.", text)
            self.assertIn(f"You stayed with your plan in {label}.", text)
            self.assertNotIn("Hypothetical", text)          # no drop, no hypothetical
            for body in _bodies(at, label):
                _plain(self, body)
        kept = self._prefs(self.bea)[expedition_log.PREF_LOG][month]
        self.assertEqual(kept["on"], today.isoformat())
        self.assertEqual(kept["drift"], {"class": "Bonds", "pts": -25})
        self.assertIs(kept["sold"], False)
        self.assertEqual(set(kept), {"on", "updated", "drift", "market", "sold", "note"})

    def test_her_own_log_and_ledger_but_never_her_advisors_view(self):
        with self._run(self.dana, "dana") as at:
            text = self._text(at)
            label = expedition_log.month_label(self.earlier[:7])
            self.assertIn(f"{label}: Nothing changed in your holdings.", text)
            self.assertIn(f"You stayed with your plan in {label}.", text)
            # this month a sale was recorded: in the log, not the ledger
            this = expedition_log.month_label(checkin.month_of(datetime.now().date()))
            self.assertIn(f"{this}: Holdings updated.", text)
            self.assertNotIn(f"You stayed with your plan in {this}.", text)
        with self._run(self.carol, "carol", active_user_id=self.dana,
                       two_step_ok=self.carol_ok) as at:
            text = self._text(at)
            for words in ("Your log", "Your ledger", "stayed with your plan",
                          "Nothing changed in your holdings"):
                self.assertNotIn(words, text)


class FlagsOffTests(_LogApp):
    FLAGS = "walk"

    def test_hidden_without_their_flags_and_nothing_written(self):
        with self._run(self.dana, "dana") as at:
            self.assertIn("Walks finished", self._text(at))
            self.assertNotIn("stayed with your plan", self._text(at))
            self.assertNotIn("Nothing changed in your holdings", self._text(at))
        with self._run(self.bea, "bea") as at:
            self._walk_to_verdict(at)
            at.button(key="walk_finish").click().run()
        self.assertNotIn(expedition_log.PREF_LOG, self._prefs(self.bea))


class StormLedgerTests(_LogApp):
    """During a drop, each ledger line shows the hypothetical - both ways."""

    @classmethod
    def seed(cls, c):
        super().seed(c)
        today = datetime.now().date()
        # VTI climbs from 250 to 330 over 70 days, then falls to 260 by yesterday
        for d in range(100, 0, -1):
            day = (today - timedelta(days=d)).isoformat()
            vti = 250 + 80 * (100 - d) / 70 if d >= 30 else 330 - 70 * (30 - d) / 29
            for ticker, close in (("VTI", vti), ("BND", 100.0)):
                c.execute("INSERT INTO daily_bars (ticker, date, close) VALUES (?, ?, ?)",
                          (ticker, day, close))
        c.commit()
        cls.days = {k: (today - timedelta(days=d)).isoformat() for k, d in
                    (("behind", 95), ("ahead", 60))}
        p = prefs.load(c, cls.wren)
        month = checkin.month_of(today)
        p[checkin.PREF_LOG] = [month]
        p[checkin.PREF_STATE] = {"month": month, "done": list(checkin.REQUIRED),
                                 "finished": today.isoformat(), "skipped": False}
        p[expedition_log.PREF_LOG] = {d[:7]: {"on": d, "sold": False}
                                      for d in cls.days.values()}
        prefs.save(c, cls.wren, p)

    def test_the_hypothetical_both_ways_labelled(self):
        with self._run(self.wren, "wren") as at:
            text = html.unescape(self._text(at))
            self.assertIn("below their high", text)               # the storm note is up
            self.assertRegex(text, r"Hypothetical: if you had sold everything on .+ and held "
                                   r"cash, you'd be about \d+\.\d% behind where your mix is now")
            self.assertRegex(text, r"you'd be about \d+\.\d% ahead of where your mix is now")
            self.assertIn(ledger.HINDSIGHT, text)
            for body in _bodies(at, "Hypothetical"):
                _plain(self, body)


if __name__ == "__main__":
    unittest.main()
