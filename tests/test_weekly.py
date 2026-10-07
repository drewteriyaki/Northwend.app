"""Weekly summaries (weekly.py, views/weekly.py, flag weekly).

The moment on the market's clock (Friday's close, year end, daylight saving);
Your week's change, movers, goal and headlines from kept data only; hidden
amounts stay hidden; an empty portfolio shows nothing; the week ahead lists
only dates that are known (none estimated); every template passes the
conclusion policy and a banned-word list; the calendar is reviewed once its
year is past; what's kept is the week's id and seen / put away, and an
advisor's session writes nothing; in the app, off unless its flag is set.

    python -m unittest tests.test_weekly        (from the repo root)
"""

import contextlib
import os
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from datetime import date, datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import ai_policy  # noqa: E402
import auth  # noqa: E402
import flags  # noqa: E402
import plans  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sample_data  # noqa: E402
import two_step  # noqa: E402
import weekly as wk  # noqa: E402

PW = "pw-123456789"
BANNED = ("should", "best", "recommend", "buy", "sell", "will", "expect", "predict",
          "forecast", "likely", "urgent")
UTC = timezone.utc


def _utc(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


class MomentTests(unittest.TestCase):

    def test_monday_to_thursday_is_the_week_ahead(self):
        for day in (5, 6, 7, 8):   # Oct 5-8 2026, Monday-Thursday
            m = wk.moment(_utc(2026, 10, day, 15))
            self.assertEqual(m["kind"], wk.AHEAD)
            self.assertEqual(m["id"], "2026-W41-ahead")
            self.assertEqual(m["start"], date(2026, 10, day))
            self.assertEqual(m["end"], date(2026, 10, day) + timedelta(days=6))

    def test_friday_after_the_close_through_sunday_is_your_week(self):
        self.assertIsNone(wk.moment(_utc(2026, 10, 9, 19, 59)))   # 3:59 pm EDT
        for at in (_utc(2026, 10, 9, 20, 0), _utc(2026, 10, 10, 12), _utc(2026, 10, 11, 23)):
            m = wk.moment(at)
            self.assertEqual((m["kind"], m["id"]), (wk.WEEK, "2026-W41-week"))
            self.assertEqual((m["start"], m["end"]), (date(2026, 10, 5), date(2026, 10, 9)))
        # Sunday night in New York is already Monday in UTC: still the weekend
        self.assertEqual(wk.moment(_utc(2026, 10, 12, 3))["kind"], wk.WEEK)
        self.assertEqual(wk.moment(_utc(2026, 10, 12, 5))["kind"], wk.AHEAD)

    def test_daylight_saving(self):
        # Nov 6 2026 is after the clocks went back (EST, UTC-5): 4 pm is 21:00 UTC
        self.assertIsNone(wk.moment(_utc(2026, 11, 6, 20, 30)))
        self.assertEqual(wk.moment(_utc(2026, 11, 6, 21, 0))["kind"], wk.WEEK)
        # Mar 13 2026 is after they went forward (EDT, UTC-4): 4 pm is 20:00 UTC
        self.assertEqual(wk.moment(_utc(2026, 3, 13, 20, 0))["kind"], wk.WEEK)
        self.assertIsNone(wk.moment(_utc(2026, 3, 13, 19, 59)))

    def test_year_end_keeps_one_week_id(self):
        # Mon Dec 28 2026 - Fri Jan 1 2027 is ISO week 2026-W53
        ahead = wk.moment(_utc(2026, 12, 31, 15))
        self.assertEqual(ahead["id"], "2026-W53-ahead")
        self.assertEqual(ahead["end"], date(2027, 1, 6))
        week = wk.moment(_utc(2027, 1, 2, 15))
        self.assertEqual(week["id"], "2026-W53-week")
        self.assertEqual((week["start"], week["end"]), (date(2026, 12, 28), date(2027, 1, 1)))
        self.assertEqual(wk.moment(_utc(2027, 1, 4, 15))["id"], "2027-W01-ahead")
        # and a year whose first days belong to the year before's last week
        self.assertEqual(wk.moment(_utc(2026, 1, 1, 15))["id"], "2026-W01-ahead")


class StateTests(unittest.TestCase):

    def test_seen_then_put_away(self):
        p = wk.with_status({}, "2026-W41-week", wk.SEEN)
        self.assertEqual(p[wk.PREF], {"2026-W41-week": "seen"})
        p = wk.with_status(p, "2026-W41-week", wk.PUT_AWAY)
        p = wk.with_status(p, "2026-W41-week", wk.SEEN)       # never undoes put away
        self.assertEqual(p[wk.PREF], {"2026-W41-week": "put_away"})
        self.assertEqual(wk.home_state(p[wk.PREF], "2026-W41-week"), None)
        self.assertEqual(wk.home_state(p[wk.PREF], "2026-W42-ahead"), "card")
        self.assertEqual(wk.home_state({"2026-W42-ahead": "seen"}, "2026-W42-ahead"), "line")
        self.assertIsNone(wk.home_state({}, None))

    def test_only_ids_and_statuses_no_free_text(self):
        p = wk.with_status({}, "hello there", wk.SEEN)
        self.assertNotIn(wk.PREF, p)
        p = wk.with_status({}, "2026-W41-week", "my notes")
        self.assertNotIn(wk.PREF, p)
        self.assertEqual(wk.clean_saved({"2026-W41-week": "seen", "x": "seen", "2026-W41-ahead": 3}),
                         {"2026-W41-week": "seen"})

    def test_only_the_newest_are_kept(self):
        saved = {}
        for n in range(1, 13):
            saved = wk.with_status(saved, f"2026-W{n:02d}-ahead", wk.SEEN)
        kept = saved[wk.PREF]
        self.assertEqual(len(kept), wk.KEEP)
        self.assertIn("2026-W12-ahead", kept)
        self.assertNotIn("2026-W01-ahead", kept)
        saved = wk.with_status(saved, "2027-W01-ahead", wk.SEEN)
        self.assertIn("2027-W01-ahead", saved[wk.PREF])


MON, FRI = date(2026, 10, 5), date(2026, 10, 9)
VALUES = [("2026-09-30", 980.0), ("2026-10-02", 1000.0), ("2026-10-05", 1005.0),
          ("2026-10-08", 1030.0), ("2026-10-09", 1020.0), ("2026-10-12", 1100.0)]
CLOSES = [("AAA", "2026-10-02", 10.0), ("AAA", "2026-10-09", 11.0),
          ("BBB", "2026-10-02", 20.0), ("BBB", "2026-10-09", 19.0),
          ("CCC", "2026-10-02", 50.0), ("CCC", "2026-10-09", 50.5),
          ("DDD", "2026-10-02", 5.0), ("DDD", "2026-10-09", 4.0),
          ("EEE", "2026-10-02", 8.0), ("EEE", "2026-10-09", 8.8),
          ("FFF", "2026-10-02", 2.0), ("FFF", "2026-10-09", 2.1),
          ("GGG", "2026-10-05", 1.0)]   # no close before the week: left out


class YourWeekTests(unittest.TestCase):

    def test_change_movers_and_goal(self):
        d = wk.your_week(VALUES, CLOSES, start=MON, end=FRI, target=4000, goal_name="Retirement")
        self.assertEqual(d["base"], 1000.0)          # last close before Monday
        self.assertEqual(d["value"], 1020.0)         # Friday's, not next Monday's
        self.assertEqual(d["change"], 20.0)
        self.assertAlmostEqual(d["pct"], 2.0)
        self.assertEqual([t for t, _p in d["up"]], ["AAA", "EEE", "FFF"])   # top 3 up
        self.assertEqual([t for t, _p in d["down"]], ["DDD", "BBB"])
        self.assertEqual(d["goal"]["name"], "Retirement")
        self.assertAlmostEqual(d["goal"]["start_pct"], 25.0)
        self.assertAlmostEqual(d["goal"]["end_pct"], 25.5)
        words = wk.your_week_lines(d, level=lambda v: f"{v:.1f}%")
        self.assertEqual(words["change"],
                         "Your portfolio's value changed by $+20.00 (+2.0%) over the week.")
        self.assertEqual(words["up"], ["AAA +10.0%", "EEE +10.0%", "FFF +5.0%"])
        self.assertEqual(words["goal"], "Your goal, Retirement: from 25.0% to 25.5% of the "
                                        "amount over the week.")
        self.assertIn("Fri, Oct 9", words["span"])

    def test_no_goal_or_no_target(self):
        d = wk.your_week(VALUES, CLOSES, start=MON, end=FRI)
        self.assertIsNone(d["goal"])
        self.assertEqual(wk.your_week_lines(d)["goal"], "")
        self.assertIsNone(wk.your_week(VALUES, CLOSES, start=MON, end=FRI, target=0)["goal"])

    def test_a_holiday_friday_ends_on_thursday(self):
        values = [("2026-12-24", 100.0), ("2026-12-31", 103.0)]
        d = wk.your_week(values, [], start=date(2026, 12, 28), end=date(2027, 1, 1))
        self.assertEqual(d["last_day"], "2026-12-31")
        self.assertIn("Thu, Dec 31", wk.your_week_lines(d)["span"])
        self.assertAlmostEqual(d["pct"], 3.0)

    def test_masked_amounts_stay_masked(self):
        d = wk.your_week(VALUES, CLOSES, start=MON, end=FRI, target=4000)
        words = wk.your_week_lines(d, money=lambda v: "•••", pct=lambda v: "•••",
                                   level=lambda v: "•••")
        self.assertEqual(words["change"], "Your portfolio's value changed by ••• (•••) over "
                                          "the week.")
        self.assertNotRegex(words["change"] + words["goal"], r"\d")

    def test_a_percentages_portfolio_has_no_dollars(self):
        d = wk.your_week(VALUES, CLOSES, start=MON, end=FRI)
        self.assertEqual(wk.your_week_lines(d, dollars=False)["change"],
                         "Your portfolio's value changed by +2.0% over the week.")

    def test_empty_portfolio(self):
        d = wk.your_week([], [], start=MON, end=FRI, target=1000)
        self.assertTrue(d["empty"])
        self.assertIsNone(d["change"])
        self.assertIsNone(d["goal"])
        words = wk.your_week_lines(d)
        self.assertEqual(words["change"], wk.CHANGE_NONE)
        self.assertEqual(words["movers_none"], wk.MOVERS_NONE)
        self.assertEqual(words["headlines"], [])

    def test_headlines_from_kept_news_for_the_biggest_movers(self):
        def art(day, head, url="https://news.example/a"):
            return {"headline": head, "source": "Wire", "url": url,
                    "published_at": f"{day}T14:00:00Z"}
        kept = {"DDD": [art("2026-10-07", "DDD this week"), art("2026-09-20", "DDD old")],
                "AAA": [art("2026-10-10", "AAA on Saturday")],
                "EEE": [art("2026-10-06", "EEE bad link", url="javascript:alert(1)")],
                "BBB": [art("2026-10-06", "BBB news")],
                "FFF": [art("2026-10-06", "FFF news")]}
        d = wk.your_week(VALUES, CLOSES, start=MON, end=FRI, news=kept)
        heads = [h["headline"] for h in d["headlines"]]
        # by the size of the move: DDD -20%, AAA +10%, EEE +10% (no safe link), BBB -5%
        self.assertEqual(heads, ["DDD this week", "AAA on Saturday", "BBB news"])
        self.assertTrue(all(h["url"].startswith("https://") for h in d["headlines"]))


class WeekAheadTests(unittest.TestCase):

    POS = [{"symbol": "VTI", "div_pay_date": "10/09/2026", "next_earnings_date": "--"},
           {"symbol": "AAPL", "div_pay_date": "N/A", "next_earnings_date": "2026-10-29"},
           {"symbol": "SCHD", "div_pay_date": "10/20/2026", "next_earnings_date": None}]

    def test_only_known_dates_in_the_window(self):
        d = wk.week_ahead(self.POS, start=date(2026, 10, 5), end=date(2026, 10, 11),
                          snapshot=date(2026, 10, 2))
        self.assertEqual(d["holdings"], [(date(2026, 10, 9), "VTI", "pay")])
        words = wk.week_ahead_lines(d)
        self.assertEqual(words["holdings"], [("Fri, Oct 9", "VTI dividend pay date")])
        self.assertIn("Fri, Oct 2", words["source"])
        d = wk.week_ahead(self.POS, start=date(2026, 10, 26), end=date(2026, 11, 1))
        self.assertEqual(d["holdings"], [(date(2026, 10, 29), "AAPL", "earnings")])
        self.assertEqual(wk.week_ahead_lines(d)["holdings"][0][1], "AAPL earnings report date")

    def test_no_dividends_known_nothing_estimated(self):
        pos = [{"symbol": "VTI"}, {"symbol": "BND", "div_pay_date": "--"}]
        d = wk.week_ahead(pos, start=date(2026, 10, 5), end=date(2026, 10, 11))
        self.assertEqual(d["holdings"], [])
        words = wk.week_ahead_lines(d)
        self.assertEqual(words["holdings_none"], wk.NO_BROKER_DATES)
        self.assertEqual(words["ex_note"], wk.EX_NOTE)
        d = wk.week_ahead(self.POS, start=date(2026, 11, 2), end=date(2026, 11, 8))
        self.assertEqual(wk.week_ahead_lines(d)["holdings_none"], wk.AHEAD_NONE)
        self.assertEqual(wk.week_ahead([], start=date(2026, 11, 2),
                                       end=date(2026, 11, 8))["holdings"], [])

    def test_the_public_calendar_in_the_window(self):
        d = wk.week_ahead([], start=date(2026, 10, 26), end=date(2026, 11, 1))
        self.assertEqual([c[0] for c in d["calendar"]], [date(2026, 10, 28)])
        words = wk.week_ahead_lines(d)
        self.assertEqual(words["calendar"][0][2], wk.FED_URL)
        self.assertIn(wk.CALENDAR_CHECKED, words["cal_note"])
        # across the year end
        d = wk.week_ahead([], start=date(2026, 12, 28), end=date(2027, 1, 3))
        self.assertEqual([c[0] for c in d["calendar"]], [date(2027, 1, 1)])

    def test_parse_day(self):
        self.assertEqual(wk.parse_day("10/15/2026"), date(2026, 10, 15))
        self.assertEqual(wk.parse_day("10/15/26"), date(2026, 10, 15))
        self.assertEqual(wk.parse_day("2026-10-15"), date(2026, 10, 15))
        self.assertEqual(wk.parse_day("Oct 15, 2026"), date(2026, 10, 15))
        for junk in ("--", "N/A", "", None, "soon"):
            self.assertIsNone(wk.parse_day(junk))


class CalendarTests(unittest.TestCase):

    def test_review_the_calendar_each_year(self):
        self.assertLessEqual(date.today().year, wk.CALENDAR_YEAR,
                             "weekly.CALENDAR is for a past year: put in this year's FOMC "
                             "meetings and market holidays from the linked sources")

    def test_every_date_is_sourced_and_in_its_year(self):
        days = [d for d, _w, _u in wk.CALENDAR]
        self.assertEqual(days, sorted(days))
        for d, words, url in wk.CALENDAR:
            self.assertIn(re.sub(r"^https://([^/]+)/.*$", r"\1", url), wk.OFFICIAL_SITES)
            year = int(d[:4])
            # this year's dates, and next New Year's Day for the last week
            self.assertTrue(year == wk.CALENDAR_YEAR
                            or (year == wk.CALENDAR_YEAR + 1 and d[5:] == "01-01"), d)
            self.assertTrue(words)


class WordingTests(unittest.TestCase):

    def test_every_template_passes_the_conclusion_policy(self):
        for line in wk.templates():
            with self.subTest(line=line[:50]):
                self.assertEqual(ai_policy.findings(line, allowed_tickers={"VTI", "AAPL"}), [])

    def test_no_banned_words(self):
        for line in wk.templates():
            for word in BANNED:
                self.assertNotRegex(line.lower(), rf"\b{word}\b", line)

    def test_never_in_the_ai(self):
        for name in ("advisor.py", "context_card.py", "ai_gateway.py", "ai_tools.py",
                     "ai_library.py", os.path.join("views", "assistant.py")):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                self.assertNotRegex(fh.read(), r"\bweekly\.", name)

    def test_the_flag_is_off_unless_set_and_owns_the_view(self):
        self.assertEqual(flags.FEATURES["weekly"], {"gates": (), "view": "weekly"})
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": ""}), \
                unittest.mock.patch.object(flags, "_secret", lambda name: None):
            self.assertFalse(flags.on("weekly"))
            self.assertFalse(flags.view_on("weekly"))
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": "weekly"}):
            self.assertTrue(flags.on("weekly"))


# --------------------------------------------------------------------------- #
# in the app
# --------------------------------------------------------------------------- #
SAT = _utc(2026, 10, 10, 15)    # Your week: Oct 5-9
TUE = _utc(2026, 10, 6, 15)     # The week ahead: Oct 6-12


class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_weekly_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.alice = auth.create_user(c, "alice", PW)
            sample_data.load(c, cls.alice, today=date(2026, 10, 2))
            plans.save_plan(c, cls.alice, {"goal_type": "Retirement", "target_amount": 100000,
                                           "target_date": "2046-01-01"}, set_by=cls.alice)
            c.execute("UPDATE positions SET div_pay_date = '10/08/2026' WHERE user_id = ? "
                      "AND symbol = 'SCHD'", (cls.alice,))
            # each sample holding's closes: Friday Oct 2, then the week
            for _acct, sym, *_rest, price in sample_data.HOLDINGS:
                for day, f in (("2026-10-02", 1.0), ("2026-10-05", 1.01), ("2026-10-09",
                               1.05 if sym == "AAPL" else 0.98 if sym == "BND" else 1.02)):
                    c.execute("INSERT OR REPLACE INTO daily_bars (ticker, date, close, adj_close) "
                              "VALUES (?, ?, ?, ?)", (sym, day, price * f, price * f))
            c.execute("INSERT INTO news (id, ticker, headline, source, url, published_at) "
                      "VALUES (991, 'AAPL', 'Apple shows a new phone', 'Wire', "
                      "'https://news.example/apple', '2026-10-07T13:00:00Z')")
            cls.carol = auth.create_user(c, "carol", PW)
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dana = auth.create_user(c, "dana", PW)
            sample_data.load(c, cls.dana, today=date(2026, 10, 2))
            auth.link_client(c, cls.carol, cls.dana)
            cls.erin = auth.create_user(c, "erin", PW)   # nothing in her account
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _app(self, uid, name, at_time, flag="weekly", **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")

        def patched(run):
            mod = sys.modules.get("weekly")
            if mod is None:
                import weekly as mod
            with unittest.mock.patch.object(mod, "now", lambda: at_time):
                run()
            return mod

        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": "Dashboard",
                     "auto_backfilled": True, "fs_hide": True, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                   NORTHWEND_FLAGS=flag)
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline_net.connect):
            mod = patched(at.run)
            if sys.modules.get("weekly") is not mod:   # reloaded during that run
                patched(at.run)
            self.assertEqual([e.message for e in at.exception], [])
            with unittest.mock.patch.object(sys.modules["weekly"], "now", lambda: at_time):
                yield at
            self.assertEqual([e.message for e in at.exception], [])

    @staticmethod
    def _text(at):
        parts = [m.value for m in at.markdown]
        parts += [str(e.value) for e in at.caption]
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
            p.pop(wk.PREF, None)
            prefs.save(c, uid, p)
        finally:
            c.close()

    def test_off_unless_set(self):
        with self._app(self.alice, "alice", SAT, flag="") as at:
            self.assertNotIn("wk_open_btn", self._keys(at))
            self.assertNotIn(wk.WEEK_TITLE, self._text(at))

    def test_your_week_opened_then_a_quiet_line(self):
        self._reset(self.alice)
        with self._app(self.alice, "alice", SAT) as at:
            self.assertIn(wk.WEEK_WHY, self._text(at))
            self.assertIn("wk_later", self._keys(at))
            at.button(key="wk_open_btn").click().run()
            text = self._text(at)
            self.assertIn("Your portfolio's value changed by", text)
            self.assertIn("AAPL +5.0%", text)
            self.assertIn("BND -2.0%", text)
            self.assertIn("Your goal, Retirement: from", text)
            self.assertIn("Apple shows a new phone", text)
            self.assertIn(wk.WEEK_FOOT, text)
            # hidden amounts stay hidden
            at.session_state["hide_amounts"] = True
            at.run()
            text = self._text(at)
            line = text.split("Your portfolio's value changed by")[1].split("over the week")[0]
            self.assertNotRegex(line, r"\d")
            goal = text.split("Your goal, Retirement: from")[1].split("of the amount")[0]
            self.assertNotRegex(goal, r"\d")
        self.assertEqual(self._prefs(self.alice)[wk.PREF], {"2026-W41-week": "seen"})
        with self._app(self.alice, "alice", SAT + timedelta(hours=20)) as at:
            keys = self._keys(at)
            self.assertIn("wk_open_btn", keys)
            self.assertNotIn("wk_later", keys)
            self.assertNotIn(wk.WEEK_FOOT, self._text(at))

    def test_not_now_puts_this_weeks_away(self):
        self._reset(self.alice)
        with self._app(self.alice, "alice", TUE) as at:
            self.assertIn(wk.AHEAD_WHY, self._text(at))
            at.button(key="wk_open_btn").click().run()
            text = self._text(at)
            self.assertIn("SCHD dividend pay date", text)
            self.assertIn(wk.EX_NOTE, text)
        self._reset(self.alice)
        with self._app(self.alice, "alice", TUE) as at:
            at.button(key="wk_later").click().run()
            self.assertNotIn("wk_open_btn", self._keys(at))
        self.assertEqual(self._prefs(self.alice)[wk.PREF], {"2026-W41-ahead": "put_away"})
        with self._app(self.alice, "alice", SAT) as at:     # the weekend's is its own
            self.assertIn("wk_open_btn", self._keys(at))
        self._reset(self.alice)

    def test_nothing_on_friday_before_the_close_or_without_holdings(self):
        with self._app(self.alice, "alice", _utc(2026, 10, 9, 15)) as at:
            self.assertNotIn("wk_open_btn", self._keys(at))
        with self._app(self.erin, "erin", SAT) as at:
            self.assertNotIn("wk_open_btn", self._keys(at))

    def test_an_advisor_in_a_clients_account_sees_it_and_writes_nothing(self):
        before = self._prefs(self.dana)
        with self._app(self.carol, "carol", SAT, two_step_ok=self.carol_ok,
                       active_user_id=self.dana) as at:
            self.assertIn("wk_open_btn", self._keys(at))
            self.assertNotIn("wk_later", self._keys(at))
            at.button(key="wk_open_btn").click().run()
            self.assertIn(wk.WEEK_FOOT, self._text(at))
        self.assertEqual(self._prefs(self.dana), before)


if __name__ == "__main__":
    unittest.main()
