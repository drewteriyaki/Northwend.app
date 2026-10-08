"""Home in three parts (views/dashboard_page.py, home_tasks.py).

The middle (the chart, then one holdings table) and "This month" on the
right; a row of cards across on a phone (CSS). The table has headings, the
ticker first and the past month's mini chart, the largest rows first and
"Show all" opening the rest in place; a row opens the ticker's own page
(?page=ticker&t=VTI, views/ticker_detail.py) with Back to where it came from.
This month shows its first few cards and "Show N more"; each suggestion has a
small X that puts it away until its period ends (only its key and the period's
id are kept, in the login's own settings). An advisor in a client's account
sees the cards and writes nothing. Hidden amounts stay hidden, a percentages
portfolio shows no dollar values, and an empty account still gets the
get-started Home. Every fixed line passes the conclusion policy.

    python -m unittest tests.test_home_layout        (from the repo root)
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

import ai_policy  # noqa: E402
import auth  # noqa: E402
import home_tasks as ht  # noqa: E402
import manual_entry  # noqa: E402
import perf  # noqa: E402
import plans  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sample_data  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
BANNED = ("should", "best", "recommend", "buy", "sell", "rebalance", "will", "expect",
          "predict", "forecast", "urgent")
EXTRA = [f"ZQ{i}" for i in range(10)]   # gil's other holdings: 16 in all


class TaskStateTests(unittest.TestCase):

    def test_periods(self):
        self.assertEqual(ht.period_id(ht.MONTH, date(2026, 10, 7)), "2026-10")
        self.assertEqual(ht.period_id(ht.WEEK, date(2026, 10, 7)), "2026-W41")
        self.assertEqual(ht.period_id(ht.WEEK, date(2027, 1, 1)), "2026-W53")

    def test_marked_until_the_period_ends(self):
        d = date(2026, 10, 7)
        p = ht.with_mark({"other": 1}, "mix", d, ht.AWAY)
        self.assertEqual(p, {"other": 1, ht.PREF: {"mix": ["2026-10", "away"]}})
        self.assertTrue(ht.hidden(p, "mix", d))
        self.assertTrue(ht.hidden(p, "mix", date(2026, 10, 31)))
        self.assertFalse(ht.hidden(p, "mix", date(2026, 11, 1)))   # back next month
        self.assertFalse(ht.hidden(p, "route", d))
        p = ht.with_mark(p, "drill", d, ht.DONE)
        self.assertFalse(ht.hidden(p, "drill", date(2026, 10, 12)))   # a new week
        self.assertEqual(ht.put_away(p, d), ["mix", "drill"])
        self.assertEqual(ht.cleared(p), {"other": 1})
        self.assertEqual(ht.with_mark(p, "mix", d, None)[ht.PREF], {"drill": ["2026-W41", "done"]})

    def test_only_known_keys_and_marks(self):
        d = date(2026, 10, 7)
        self.assertEqual(ht.with_mark({}, "VTI $1,000", d, ht.DONE), {})
        self.assertEqual(ht.with_mark({}, "mix", d, "12.5%"), {})
        # last period's entries are dropped on the next write
        old = {ht.PREF: {"mix": ["2026-09", "away"], "junk": ["2026-10", "away"]}}
        self.assertEqual(ht.with_mark(old, "route", d, ht.DONE)[ht.PREF],
                         {"route": ["2026-10", "done"]})

    def test_the_x_says_its_period(self):
        self.assertEqual(ht.away_help("mix"), "Put away until next month")
        self.assertEqual(ht.away_help("drill"), "Put away until next week")
        self.assertEqual(ht.away_help("news"), "Put away until next week")
        self.assertEqual(ht.away_help("minute"), "Put away until tomorrow")
        # the X's name for screen readers says the same (ui_enhancements.js)
        with open(os.path.join(REPO, "ui_enhancements.js"), encoding="utf-8") as fh:
            js = fh.read()
        rules = re.findall(r"\[/\^st-key-(task_away_[^/]*)/, \(\) => \"([^\"]+)\"\]", js)
        for key in ht.TASKS:
            said = next(words for rule, words in rules if re.match(rule, f"task_away_{key}"))
            self.assertEqual(said, ht.away_help(key), key)

    def test_mix_lines(self):
        actual = {"Stocks": 85.0, "Bonds": 12.0, "Cash": 3.0}
        targets = {"Stocks": 60, "Bonds": 35, "Cash": 5}
        self.assertEqual(ht.mix_lines(actual, targets, 5.0),
                         ["Stocks is 25 points over your target.",
                          "Bonds is 23 points under your target."])
        self.assertEqual(ht.mix_lines(actual, targets, 5.0, masked=True),
                         ["Stocks is ••• points over your target.",
                          "Bonds is ••• points under your target."])
        self.assertEqual(ht.mix_lines(actual, {"Stocks": 84}, 5.0), [ht.MIX_WITHIN])
        rows = [{"label": "Stocks", "pct": 85.2}, {"label": "Cash", "pct": 0.2}]
        self.assertEqual(ht.mix_summary(rows), "About 85% stocks")
        self.assertNotRegex(ht.mix_summary(rows, masked=True), r"\d")


class WordingTests(unittest.TestCase):

    def test_every_line_passes_the_conclusion_policy(self):
        for line in ht.templates():
            with self.subTest(line=line):
                self.assertEqual(ai_policy.findings(line), [])
                for word in BANNED:
                    self.assertNotRegex(line.lower(), rf"\b{word}\b")

    def test_the_phone_and_wide_rules(self):
        with open(os.path.join(REPO, "dashboard.py"), encoding="utf-8") as fh:
            src = fh.read()
        css = src[src.index("/* Home in three parts"):src.index(".pt-hero-label {")]
        phone = css[css.index("@media (max-width: 640px)"):]
        self.assertIn(".st-key-pt_month_cards { flex-direction: row !important;", phone)
        self.assertIn(".st-key-pt_month_more_open { flex-direction: row !important;", phone)
        self.assertIn("overflow-x: auto", phone)
        narrow = css[css.index("@media (max-width: 900px)"):css.index("@media (max-width: 640px)")]
        self.assertIn("flex-direction: column", narrow)
        self.assertIn(":has(> .st-key-pt_home_side) { order: -1; }", narrow)
        self.assertIn("flex: 0 0 19rem", css)
        # the cards after the first few stay hidden until Show N more
        self.assertIn(".st-key-pt_month_more { display: none !important; }", css)
        # the X sits at the card's top right
        self.assertIn("position: absolute; top: .3rem; right: .3rem;", css)


class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_home_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        snap = date.today().isoformat()
        rows, totals = sample_data.snapshot_rows(snap)
        c = portfolio.connect(cls.db)
        try:
            cls.alice = auth.create_user(c, "alice", PW)
            portfolio.write_snapshot(c, cls.alice, {"snapshot_date": snap, "as_of_text": "t"},
                                     rows, totals, "alice.csv")
            plans.save_plan(c, cls.alice, {"target_alloc": {"Stocks": 40, "Bonds": 50,
                                                            "Cash": 10}}, set_by=cls.alice)
            cls.frank = auth.create_user(c, "frank", PW)   # percentages only
            portfolio.write_snapshot(c, cls.frank, {"snapshot_date": snap, "as_of_text": "t"},
                                     rows, totals, manual_entry.PCT_SOURCE)
            cls.carol = auth.create_user(c, "carol", PW)
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dana = auth.create_user(c, "dana", PW)
            portfolio.write_snapshot(c, cls.dana, {"snapshot_date": snap, "as_of_text": "t"},
                                     rows, totals, "dana.csv")
            auth.link_client(c, cls.carol, cls.dana)
            cls.erin = auth.create_user(c, "erin", PW)   # nothing in her account
            # gil: 16 holdings, smaller ones after the sample's six
            more = [{**rows[0], "symbol": s, "description": f"Fund {s}",
                     "market_value": 100.0 + i, "cost_basis": 90.0, "quantity": 1.0}
                    for i, s in enumerate(EXTRA)]
            cls.gil = auth.create_user(c, "gil", PW)
            portfolio.write_snapshot(c, cls.gil, {"snapshot_date": snap, "as_of_text": "t"},
                                     rows + more, totals, "gil.csv")
            for n in range(40):   # VTI's daily closes: its mini chart
                c.execute("INSERT OR REPLACE INTO daily_bars (ticker, date, close) "
                          "VALUES ('VTI', ?, ?)",
                          ((date.today() - timedelta(days=n)).isoformat(), 200.0 + n))
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _app(self, uid, name, query=None, flag="", **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")

        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        base = {"user_id": uid, "username": name, "auto_backfilled": True, "fs_hide": True}
        if not query:
            base["page"] = "Dashboard"
        for k, v in {**base, **state}.items():
            at.session_state[k] = v
        for k, v in (query or {}).items():
            at.query_params[k] = v
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
    def _block_keys(at):
        found, todo = [], [at._tree]
        while todo:
            node = todo.pop()
            pid = getattr(getattr(node, "proto", None), "id", "") or ""
            if "-" in pid:
                found.append(pid.rsplit("-", 1)[-1])
            todo.extend(getattr(node, "children", {}).values()
                        if isinstance(getattr(node, "children", None), dict) else [])
        return found

    @staticmethod
    def _html(at):
        return " ".join(h.proto.body for h in at.get("html"))

    @staticmethod
    def _table(at):
        """Home's holdings table (the one with the Ticker heading first)."""
        return next(d for d in at.dataframe if list(d.value.columns)[:1] == ["Ticker"])

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
            p.pop(ht.PREF, None)
            prefs.save(c, uid, p)
        finally:
            c.close()

    def test_three_parts_and_the_table(self):
        self._reset(self.alice)
        with self._app(self.alice, "alice") as at:
            keys = self._block_keys(at)
            for k in ("pt_home_band", "pt_home_layout", "pt_home_main", "pt_home_side",
                      "pt_home_chart", "pt_home_list", "pt_month_cards", "pt_route",
                      "pt_mix_card", "pt_task_route", "pt_task_mix"):
                self.assertIn(k, keys)
            buttons = {b.key: b for b in at.button}
            for k in ("task_done_route", "task_away_route", "task_done_mix", "task_away_mix"):
                self.assertIn(k, buttons)
            # the X: an icon at the card's top right, saying its period
            self.assertEqual(buttons["task_away_mix"].help, "Put away until next month")
            self.assertNotIn("Not now", [str(b.label) for b in at.button])
            self.assertNotIn("task_bring_back", buttons)
            # one table with headings: the ticker first, its mini chart, then
            # the columns under short names; no row of ticker buttons or pills
            table = self._table(at)
            cols = list(table.value.columns)
            self.assertEqual(cols[:2], ["Ticker", "Past month"])
            for head in ("Name", "Share", "Value", "Today", "Gain/loss"):
                self.assertIn(head, cols)
            self.assertEqual(list(table.value["Ticker"])[0], "VTI")   # largest first
            self.assertFalse([k for k in buttons if k.startswith("home_hold_")])
            self.assertNotIn("holdings_pill", [p.key for p in at.get("button_group")])
            self.assertNotIn("All holdings - the full table", [e.label for e in at.expander])
            # tapping a row opens the ticker's page (row selection, or a cell)
            modes = set(table.proto.selection_mode)
            self.assertTrue(modes)
            self.assertIn("perf_range", [s.key for s in at.get("button_group")])
            html = self._html(at)
            self.assertIn(ht.TITLE, html)
            self.assertIn("Stocks is", html)
            self.assertIn("points under your target", html)

    def test_show_all_opens_the_rest_in_place(self):
        with self._app(self.gil, "gil") as at:
            table = self._table(at)
            self.assertEqual(len(table.value), ht.LIST_LIMIT)
            self.assertEqual(at.button(key="home_hold_all_btn").label, "Show all 16 holdings")
            at.button(key="home_hold_all_btn").click().run()
            table = self._table(at)
            self.assertEqual(len(table.value), 16)                  # the same table, every row
            self.assertEqual(at.button(key="home_hold_all_btn").label, "Show fewer")
            self.assertEqual(sum(1 for d in at.dataframe if "Ticker" in d.value.columns), 1)
            at.button(key="home_hold_all_btn").click().run()
            self.assertEqual(len(self._table(at).value), ht.LIST_LIMIT)
            # a search shows every match
            at.text_input(key="ticker_search").set_value("zq").run()
            self.assertEqual(sorted(self._table(at).value["Ticker"]), EXTRA)

    def test_the_mini_chart_reads_nothing_more(self):
        stats = perf.bar_stats(self.db, ["VTI"])
        # about a month of closes, oldest first (UTC days: one either way)
        self.assertIn(len(stats["VTI"]["spark"]), range(perf.SPARK_DAYS - 1, perf.SPARK_DAYS + 3))
        self.assertEqual(stats["VTI"]["spark"][-1], 200.0)
        with self._app(self.gil, "gil") as at:
            table = self._table(at)
            spark = dict(zip(table.value["Ticker"], table.value["Past month"]))
            self.assertEqual(list(spark["VTI"]), stats["VTI"]["spark"])
            self.assertEqual(list(spark["BND"]), [])   # no closes yet: an empty line

    def test_a_ticker_has_its_own_page_with_back(self):
        # a row's pick: what the table's callback does (dashboard._open_ticker)
        with self._app(self.alice, "alice", page="Ticker", ticker_sym="VTI",
                       ticker_from="Dashboard") as at:
            self.assertEqual(at.title[0].value, "VTI")
            self.assertEqual(dict(at.query_params), {"page": "ticker", "t": "VTI"})
            self.assertEqual(at.button(key="ticker_back").label, "Back to Home")
            self.assertIn("pt_page_band", self._block_keys(at))
            self.assertIn("#### Your position", [m.value for m in at.markdown])
            # no menu item of its own: Home stays the one showing
            self.assertEqual(at.button(key="nav_Dashboard").proto.type, "primary")
            self.assertNotIn("nav_Ticker", [b.key for b in at.button])
            at.button(key="ticker_back").click().run()
            self.assertEqual(at.session_state["page"], "Dashboard")
            self.assertIn("pt_home_layout", self._block_keys(at))
        # an address: ?page=ticker&t=VTI opens it in a new session
        with self._app(self.alice, "alice", query={"page": "ticker", "t": "VTI"}) as at:
            self.assertEqual(at.title[0].value, "VTI")
        # something not held or watched: back to Home, nothing drawn for it
        with self._app(self.alice, "alice", query={"page": "ticker", "t": "NOPE"}) as at:
            self.assertIn("pt_home_layout", self._block_keys(at))
        # the old way to open one (a ticker strip's open row) lands on its page
        with self._app(self.alice, "alice", holdings_pill="BND") as at:
            self.assertEqual(at.title[0].value, "BND")

    def test_x_and_done_keep_only_keys_and_come_back(self):
        self._reset(self.alice)
        month = ht.period_id(ht.MONTH, date.today())
        with self._app(self.alice, "alice") as at:
            at.button(key="task_away_mix").click().run()
            self.assertNotIn("pt_mix_card", self._block_keys(at))
            at.button(key="task_done_route").click().run()
            self.assertNotIn("pt_route", self._block_keys(at))
            self.assertIn("task_bring_back", [b.key for b in at.button])
        kept = self._prefs(self.alice)[ht.PREF]
        self.assertEqual(kept, {"mix": [month, "away"], "route": [month, "done"]})
        self.assertNotRegex(json.dumps(kept), r"\$|%|VTI")
        with self._app(self.alice, "alice") as at:   # still away this month
            self.assertNotIn("pt_mix_card", self._block_keys(at))
            at.button(key="task_bring_back").click().run()
            self.assertIn("pt_mix_card", self._block_keys(at))
        self.assertNotIn(ht.PREF, self._prefs(self.alice))

    def test_this_month_shows_a_few_then_show_more(self):
        self._reset(self.alice)
        flags = "walk weekly seasons drills challenges wins money_minute news_feed"
        with self._app(self.alice, "alice", flag=flags) as at:
            keys = self._block_keys(at)
            self.assertIn("pt_month_more", keys)                     # hidden for now
            label = at.button(key="month_more").label
            self.assertRegex(label, r"^Show \d+ more$")
            at.button(key="month_more").click().run()
            keys = self._block_keys(at)
            self.assertIn("pt_month_more_open", keys)
            self.assertEqual(at.button(key="month_more").label, "Show fewer")
        with open(os.path.join(REPO, "views", "dashboard_page.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("box = first if shown < home_tasks.MONTH_LIMIT else rest", src)

    def test_hidden_amounts_stay_hidden(self):
        self._reset(self.alice)
        with self._app(self.alice, "alice", hide_amounts=True) as at:
            table = self._table(at).value
            for col in ("Share", "Value", "Today", "Gain/loss"):
                for cell in table[col]:
                    self.assertNotRegex(str(cell), r"\d", col)
            mix = next(h.proto.body for h in at.get("html") if ht.MIX_TITLE in h.proto.body)
            self.assertIn("points under your target", mix)
            self.assertNotRegex(re.sub(r"<[^>]+>|style='[^']*'", "", mix), r"\d")

    def test_a_percentages_portfolio_shows_no_dollar_values(self):
        with self._app(self.frank, "frank") as at:
            cols = list(self._table(at).value.columns)
            self.assertIn("Share", cols)
            for head in ("Value", "Gain/loss"):
                self.assertNotIn(head, cols)

    def test_an_advisor_in_a_clients_account_writes_nothing(self):
        before = self._prefs(self.dana)
        with self._app(self.carol, "carol", two_step_ok=self.carol_ok,
                       active_user_id=self.dana) as at:
            keys = self._block_keys(at)
            self.assertIn("pt_home_layout", keys)
            self.assertIn("pt_month_cards", keys)
            self.assertFalse([b.key for b in at.button if (b.key or "").startswith("task_")])
            self.assertEqual(list(self._table(at).value.columns)[:1], ["Ticker"])
            # and the ticker's page, opened from a row
            at.session_state["ticker_sym"] = "VTI"
            at.session_state["ticker_from"] = "Dashboard"
            at.session_state["page"] = "Ticker"
            at.run()
            self.assertEqual(at.title[0].value, "VTI")
        self.assertEqual(self._prefs(self.dana), before)

    def test_an_empty_account_keeps_the_get_started_home(self):
        with self._app(self.erin, "erin") as at:
            self.assertNotIn("pt_home_layout", self._block_keys(at))
            self.assertFalse(at.exception)


class CursorTests(unittest.TestCase):
    """This month counts the cards that drew something by streamlit's own
    count of a container's children (dashboard_page._box_count): pinned here,
    so an upgrade that moves it shows up as a failure, not a silent change."""

    def test_a_containers_count(self):
        from streamlit.testing.v1 import AppTest

        def script():
            import streamlit as st
            box = st.container()
            before = box._cursor.index
            with box:
                st.write("one")
                st.write("two")
            st.session_state["counts"] = (before, box._cursor.index)

        at = AppTest.from_function(script).run()
        self.assertEqual(at.session_state["counts"], (0, 2))


if __name__ == "__main__":
    unittest.main()
