"""Upcoming dividend dates (dividend_dates.py, sync_history._event_dates).

Facts only: Yahoo's dates from the info reply the history sync already makes,
Polygon's announced dividends from the nightly job, the brokerage file's
cells - past dates never shown, nothing estimated. The job: no key, no calls;
paced, capped, the longest-ago first, stopped by repeated refusals, failing
only when every call failed. The pages: Scout (tests/test_weekly.py), Income's
"Announced pay dates", a ticker's page, Admin > System. All offline: the HTTP
call is a fake.

    python -m unittest tests.test_dividend_dates        (from the repo root)
"""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from datetime import date, datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import auth  # noqa: E402
import dividend_dates as dd  # noqa: E402
import portfolio  # noqa: E402
import sample_data  # noqa: E402
import sync_history  # noqa: E402

PW = "pw-123456789"
NOW = datetime(2026, 10, 8, 22, 0, tzinfo=timezone.utc)
TODAY = NOW.date()


def _ts(day: str, hour: int = 0) -> int:
    y, m, d = map(int, day.split("-"))
    return int(datetime(y, m, d, hour, tzinfo=timezone.utc).timestamp())


def _reply(ticker, *divs):
    return {"status": "OK", "results": [
        {"ticker": ticker, "ex_dividend_date": ex, "pay_date": pay, "record_date": ex,
         "declaration_date": "2026-09-20", "cash_amount": amt, "currency": "USD",
         "frequency": 4, "dividend_type": "CD"} for ex, pay, amt in divs]}


class _DB(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_divdates_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.db = os.path.join(self.dir, "t.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.conn = portfolio.connect(self.db)
        self.addCleanup(self.conn.close)


# --------------------------------------------------------------------------- #
# Yahoo: the dates in the info reply
# --------------------------------------------------------------------------- #
class YahooDatesTests(unittest.TestCase):

    def test_unix_seconds_become_days(self):
        got = sync_history._event_dates({
            "exDividendDate": _ts("2026-11-07"), "dividendDate": _ts("2026-11-13"),
            # 4:30 pm New York on Oct 29 is 20:30 UTC: still the 29th there
            "earningsTimestamp": _ts("2026-10-29", 20) + 1800,
            "earningsTimestampStart": _ts("2026-10-29", 20) + 1800,
            "earningsTimestampEnd": _ts("2026-10-29", 20) + 1800,
            "isEarningsDateEstimate": False})
        self.assertEqual(got, {"ex_dividend_date": "2026-11-07",
                               "dividend_pay_date": "2026-11-13",
                               "earnings_date": "2026-10-29"})

    def test_an_estimated_or_unsettled_earnings_date_is_left_out(self):
        est = sync_history._event_dates({"earningsTimestamp": _ts("2026-10-29", 20),
                                         "isEarningsDateEstimate": True})
        self.assertIsNone(est["earnings_date"])
        spread = sync_history._event_dates({
            "earningsTimestampStart": _ts("2026-10-27", 20),
            "earningsTimestampEnd": _ts("2026-11-02", 20)})
        self.assertIsNone(spread["earnings_date"])

    def test_a_fund_gets_nothing_and_junk_is_none(self):
        self.assertEqual(sync_history._event_dates({}), dict.fromkeys(sync_history.EVENT_COLS))
        self.assertEqual(sync_history._event_dates({"exDividendDate": "soon",
                                                    "dividendDate": -5}),
                         dict.fromkeys(sync_history.EVENT_COLS))

    def test_fetch_info_keeps_them_with_no_extra_request(self):
        calls = []

        class FakeTicker:
            def __init__(self, t):
                calls.append(t)
                self.info = {"shortName": "Apple", "quoteType": "EQUITY",
                             "exDividendDate": _ts("2026-11-07"),
                             "dividendDate": _ts("2026-08-14"),   # the last one, past
                             "earningsTimestamp": _ts("2026-10-29", 20)}

        with unittest.mock.patch.object(sync_history, "yf",
                                        unittest.mock.Mock(Ticker=FakeTicker)):
            info = sync_history.fetch_info("AAPL")
        self.assertEqual(calls, ["AAPL"])     # one reply, as before
        self.assertEqual((info["ex_dividend_date"], info["dividend_pay_date"],
                          info["earnings_date"]), ("2026-11-07", "2026-08-14", "2026-10-29"))


class YahooStoredTests(_DB):

    def test_upsert_info_writes_the_dates(self):
        with self.conn:
            sync_history.upsert_info(self.conn, "AAPL", {"name": "Apple",
                                                         "ex_dividend_date": "2026-11-07",
                                                         "dividend_pay_date": "2026-08-14",
                                                         "earnings_date": "2026-10-29"})
        row = self.conn.execute("SELECT ex_dividend_date, dividend_pay_date, earnings_date "
                                "FROM security_info WHERE ticker = 'AAPL'").fetchone()
        self.assertEqual(tuple(row), ("2026-11-07", "2026-08-14", "2026-10-29"))


# --------------------------------------------------------------------------- #
# Polygon: parse and store
# --------------------------------------------------------------------------- #
class ParseTests(unittest.TestCase):

    def test_fields_read(self):
        rows = dd.parse(_reply("VTI", ("2026-12-22", "2026-12-26", 0.9312)), "VTI")
        self.assertEqual(rows, [{"ex_date": "2026-12-22", "pay_date": "2026-12-26",
                                 "declared_date": "2026-09-20", "record_date": "2026-12-22",
                                 "amount": 0.9312}])

    def test_other_tickers_bad_dates_and_other_currencies(self):
        body = _reply("VTI", ("2026-12-22", None, 0.93), ("not a date", "2026-12-26", 1.0),
                      ("2026-12-22", "2026-12-26", 0.5))   # the same ex date twice: first kept
        body["results"].append({"ticker": "VOO", "ex_dividend_date": "2026-12-20"})
        body["results"].append({"ticker": "VTI", "ex_dividend_date": "2026-09-20",
                                "cash_amount": 1.2, "currency": "CAD"})
        rows = dd.parse(body, "VTI")
        self.assertEqual([(r["ex_date"], r["pay_date"], r["amount"]) for r in rows],
                         [("2026-12-22", None, 0.93), ("2026-09-20", None, None)])
        self.assertEqual(dd.parse(None, "VTI"), [])
        self.assertEqual(dd.parse({"results": "nope"}, "VTI"), [])

    def test_share_classes_and_what_is_asked(self):
        self.assertEqual(dd.query_symbol("brk-b"), "BRK.B")
        self.assertEqual(dd.parse(_reply("BRK.B", ("2026-12-01", None, 1.0)), "BRK/B")[0]
                         ["ex_date"], "2026-12-01")
        url = dd.request_url("BRK-B", "https://example.test/")
        self.assertEqual(url, "https://example.test/v3/reference/dividends?ticker=BRK.B"
                              "&order=desc&sort=ex_dividend_date&limit=12")
        for sym in ("VTI", "AAPL", "BRK.B"):
            self.assertTrue(dd.wanted(sym), sym)
        for sym in ("VTSAX", "FXAIX", "BTC-USD", "", None, "not a ticker"):
            self.assertFalse(dd.wanted(sym), sym)

    def test_the_key_goes_in_the_header_never_the_address(self):
        seen = {}

        class Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{"results": []}'

        def fake_open(req, timeout):
            seen["url"], seen["auth"] = req.full_url, req.get_header("Authorization")
            return Resp()

        with unittest.mock.patch("urllib.request.urlopen", fake_open):
            self.assertEqual(dd.http_get(dd.request_url("VTI"), "secret-key"),
                             (200, {"results": []}))
        self.assertNotIn("secret-key", seen["url"])
        self.assertEqual(seen["auth"], "Bearer secret-key")
        self.assertTrue(seen["url"].startswith(dd.DEFAULT_BASE + dd.PATH))

    def test_the_base_address_can_be_set(self):
        with unittest.mock.patch.dict(os.environ, {"DIVIDEND_API_BASE": "https://api.massive.test/"}):
            self.assertEqual(dd.base_url(), "https://api.massive.test")
        with unittest.mock.patch.dict(os.environ, {}, clear=True), \
                unittest.mock.patch.object(dd.settings, "load_env", lambda p: {}):
            self.assertEqual(dd.base_url(), dd.DEFAULT_BASE)
            self.assertEqual(dd.api_key(), "")
        with unittest.mock.patch.dict(os.environ, {"MASSIVE_API_KEY": "m-key"}, clear=True), \
                unittest.mock.patch.object(dd.settings, "load_env", lambda p: {}):
            self.assertEqual(dd.api_key(), "m-key")


class StoreTests(_DB):

    def test_upcoming_rows_are_replaced_past_ones_kept(self):
        c = self.conn
        dd.store(c, "VTI", dd.parse(_reply("VTI", ("2026-12-22", "2026-12-26", 0.93),
                                           ("2026-09-25", "2026-09-30", 0.88)), "VTI"), now=NOW)
        # the company moved its date: the old upcoming row goes, the past one stays
        dd.store(c, "VTI", dd.parse(_reply("VTI", ("2026-12-23", "2026-12-29", 0.95)), "VTI"),
                 now=NOW)
        got = [tuple(r) for r in c.execute(
            "SELECT ex_date, pay_date, amount FROM dividend_events WHERE ticker = 'VTI' "
            "ORDER BY ex_date")]
        self.assertEqual(got, [("", None, None), ("2026-09-25", "2026-09-30", 0.88),
                               ("2026-12-23", "2026-12-29", 0.95)])

    def test_upcoming_reads_only_from_today_on(self):
        c = self.conn
        dd.store(c, "VTI", dd.parse(_reply("VTI", ("2026-12-22", "2026-12-26", 0.93),
                                           ("2026-10-01", "2026-10-09", 0.9),   # pay still ahead
                                           ("2026-06-20", "2026-06-26", 0.85)), "VTI"), now=NOW)
        rows = dd.upcoming(c, ["vti", "AAPL"], TODAY)
        self.assertEqual([r["ex_date"] for r in rows], ["2026-10-01", "2026-12-22"])
        self.assertEqual(dd.upcoming(c, [], TODAY), [])

    def test_prune_keeps_about_two_years(self):
        c = self.conn
        old = (TODAY - timedelta(days=dd.KEEP_DAYS + 5)).isoformat()
        stamp = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
        c.executemany("INSERT INTO dividend_events (ticker, ex_date, pay_date, fetched_at) "
                      "VALUES (?, ?, ?, ?)",
                      [("VTI", old, old, stamp), ("VTI", "2026-06-20", "2026-06-26", stamp),
                       ("GONE", "", None, "2026-08-01T00:00:00Z"), ("VTI", "", None, stamp)])
        self.assertEqual(dd.prune(c, now=NOW), 2)
        self.assertEqual(sorted(tuple(r) for r in c.execute(
            "SELECT ticker, ex_date FROM dividend_events")),
            [("VTI", ""), ("VTI", "2026-06-20")])


# --------------------------------------------------------------------------- #
# what the pages show
# --------------------------------------------------------------------------- #
class ShownTests(unittest.TestCase):

    EVENTS = [{"ticker": "VTI", "ex_date": "2026-10-05", "pay_date": "2026-10-09",
               "amount": 0.93},
              {"ticker": "VTI", "ex_date": "2026-12-22", "pay_date": "2026-12-26",
               "amount": 0.95}]

    def test_next_for_skips_past_dates(self):
        nxt = dd.next_for(self.EVENTS, {}, "vti", TODAY)
        # the ex date has passed; its pay date hasn't
        self.assertEqual((nxt["ex"], nxt["pay"], nxt["amount"], nxt["source"]),
                         (None, date(2026, 10, 9), 0.93, dd.ANNOUNCED))
        later = dd.next_for(self.EVENTS, {}, "VTI", date(2026, 10, 10))
        self.assertEqual((later["ex"], later["pay"]), (date(2026, 12, 22), date(2026, 12, 26)))

    def test_yahoo_only_when_nothing_announced_and_never_a_past_date(self):
        info = {"ex_dividend_date": "2026-11-07", "dividend_pay_date": "2026-08-14",
                "earnings_date": "2026-10-29"}
        nxt = dd.next_for([], info, "AAPL", TODAY)
        self.assertEqual((nxt["ex"], nxt["pay"], nxt["source"], nxt["earnings"]),
                         (date(2026, 11, 7), None, dd.YAHOO, date(2026, 10, 29)))
        past = dd.next_for([], {"ex_dividend_date": "2026-08-07",
                                "earnings_date": "2026-07-30"}, "AAPL", TODAY)
        self.assertEqual((past["source"], past["earnings"]), (None, None))
        self.assertEqual(dd.NONE_YET, "No upcoming date announced yet")

    def test_merged_never_estimates(self):
        # a holding that paid every quarter but has nothing announced: nothing listed
        rows = dd.merged([], {"VTI": {}}, [{"symbol": "VTI", "div_pay_date": "--"}],
                         start=TODAY, end=TODAY + timedelta(days=60))
        self.assertEqual(rows, [])


class JobTests(_DB):

    def setUp(self):
        super().setUp()
        self.uid = auth.create_user(self.conn, "alice", PW)
        sample_data.load(self.conn, self.uid)   # VTI VXUS BND AAPL VOO SCHD
        self.conn.execute("INSERT INTO watchlist (user_id, ticker) VALUES (?, 'VTSAX')",
                          (self.uid,))          # a mutual fund: never asked
        self.conn.commit()
        self.sleeps, self.urls = [], []

    def run_job(self, replies, **kw):
        replies = list(replies)

        def get(url, key):
            self.urls.append(url)
            self.assertEqual(key, "k")
            return replies.pop(0) if replies else (200, {"results": []})

        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            s = dd.sync_all(self.conn, "k", base="https://x.test", get=get,
                            sleep=self.sleeps.append, now=NOW, **kw)
        return s

    def asked(self):
        return [u.split("ticker=")[1].split("&")[0] for u in self.urls]

    def test_paced_and_oldest_first(self):
        stamp = lambda days: (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
        self.conn.executemany("INSERT INTO dividend_events (ticker, ex_date, fetched_at) "
                              "VALUES (?, '', ?)", [("AAPL", stamp(9)), ("BND", stamp(5)),
                                                    ("VOO", stamp(1))])   # VOO: asked lately
        self.conn.commit()
        s = self.run_job([(200, _reply("SCHD", ("2026-12-15", "2026-12-19", 0.26)))])
        # never asked first (by name), then the longest ago; VOO waits
        self.assertEqual(self.asked(), ["SCHD", "VTI", "VXUS", "AAPL", "BND"])
        self.assertEqual(self.sleeps, [dd.PACE] * 4)
        self.assertEqual(dd.PACE, 12.5)
        self.assertEqual((s["asked"], s["ok"], s["failed"], s["skipped"], s["stored"]),
                         (5, 5, 0, 1, 1))
        self.assertEqual(dd.upcoming(self.conn, ["SCHD"], TODAY)[0]["pay_date"], "2026-12-19")

    def test_the_nightly_cap(self):
        s = self.run_job([], max_tickers=2)
        self.assertEqual(len(self.urls), 2)
        self.assertEqual(s["skipped"], 4)
        self.assertEqual(dd.MAX_PER_RUN, 200)
        # the next night carries on with the others
        self.urls.clear()
        self.run_job([], max_tickers=10)
        self.assertEqual(len(self.urls), 4)

    def test_repeated_refusals_stop_the_run(self):
        s = self.run_job([(429, None), (403, None)])
        self.assertTrue(s["stopped"])
        self.assertEqual(len(self.urls), 2)
        self.assertEqual(s["ok"], 0)
        # one refusal between answers doesn't stop it; other errors count as failed
        self.urls.clear()
        self.conn.execute("DELETE FROM dividend_events")
        self.conn.commit()
        s = self.run_job([(429, None), (200, {"results": []}), (500, None), (0, None)])
        self.assertFalse(s["stopped"])
        self.assertEqual((s["asked"], s["ok"], s["failed"]), (6, 3, 3))

    def test_main_fails_only_when_every_call_failed(self):
        def run(status):
            self.conn.execute("DELETE FROM dividend_events")
            self.conn.commit()
            with unittest.mock.patch.object(dd, "api_key", lambda: "k"), \
                    unittest.mock.patch.object(dd, "http_get", lambda u, k: (status, None if status != 200 else {"results": []})), \
                    unittest.mock.patch.object(dd.time, "sleep", lambda s: None), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                code = dd.main(["--db", self.db])
            return code, out.getvalue()

        self.assertEqual(run(500)[0], 1)
        code, out = run(200)
        self.assertEqual(code, 0)
        self.assertIn("6 asked, 6 answered", out)

    def test_no_key_no_calls(self):
        def boom(*a, **k):
            raise AssertionError("no call without a key")

        with unittest.mock.patch.object(dd, "api_key", lambda: ""), \
                unittest.mock.patch.object(dd, "http_get", boom), \
                unittest.mock.patch("urllib.request.urlopen", boom), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(dd.main(["--db", self.db]), 0)
        self.assertIn("no POLYGON_API_KEY set - nothing fetched", out.getvalue())
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM dividend_events").fetchone()[0],
                         0)

    def test_the_nightly_workflow_runs_it_with_its_own_failure_step(self):
        with open(os.path.join(REPO, ".github", "workflows", "scheduled-sync.yml"),
                  encoding="utf-8") as fh:
            text = fh.read()
        job = text.split("\n  dividend-dates:", 1)[1].split("\n  tidy:", 1)[0]
        self.assertIn("github.event.schedule == '30 21 * * 1-5'", job)
        self.assertIn('python dividend_dates.py --db "$DATABASE_URL"', job)
        self.assertIn("POLYGON_API_KEY: ${{ secrets.POLYGON_API_KEY }}", job)
        self.assertIn('python error_alerts.py job "Dividend dates"', job)

    def test_named_wherever_third_parties_are(self):
        with open(os.path.join(REPO, "disclosures.py"), encoding="utf-8") as fh:
            self.assertIn("- **Polygon** (also called Massive) provides announced dividend "
                          "dates; only\n  ticker symbols are sent to it", fh.read())
        for name in ("privacy-policy.md", "privacy-policy-DRAFT.md"):
            with open(os.path.join(REPO, "docs", "legal", name), encoding="utf-8") as fh:
                self.assertIn("| **Polygon** (also called Massive) | Announced dividend dates",
                              fh.read())
        with open(os.path.join(REPO, "website", "public", "privacy.html"),
                  encoding="utf-8") as fh:
            self.assertIn("Polygon", fh.read())


# --------------------------------------------------------------------------- #
# in the app
# --------------------------------------------------------------------------- #
class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="pt_divdates_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        cls.today = dd.today()
        c = portfolio.connect(cls.db)
        try:
            cls.alice = auth.create_user(c, "alice", PW)
            sample_data.load(c, cls.alice)
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            c.executemany(
                "INSERT INTO dividend_events (ticker, ex_date, pay_date, amount, fetched_at) "
                "VALUES (?, ?, ?, ?, ?)",
                [("VTI", cls.day(3), cls.day(8), 0.93, stamp),
                 ("SCHD", cls.day(-30), cls.day(-25), 0.25, stamp),   # past: not shown
                 ("BND", cls.day(70), cls.day(75), 0.2, stamp)])      # past 60 days
            c.executemany(
                "INSERT INTO security_info (ticker, quote_type, ex_dividend_date, "
                "dividend_pay_date, earnings_date) VALUES (?, ?, ?, ?, ?)",
                [("AAPL", "EQUITY", cls.day(10), cls.day(-50), cls.day(20)),
                 ("VXUS", "ETF", None, None, None)])
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    @classmethod
    def day(cls, n):
        return (cls.today + timedelta(days=n)).isoformat()

    def _run(self, page, **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")

        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": self.alice, "username": "alice", "page": page,
                     "auto_backfilled": True, "income_synced": True, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY", "POLYGON_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1")
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline_net.connect):
            at.run()
        self.assertEqual([e.message for e in at.exception], [])
        return " ".join([m.value for m in at.markdown] + [s.value for s in at.subheader]
                        + [str(e.value) for e in at.caption])

    def _words(self, iso):
        d = date.fromisoformat(iso)
        return f"{d:%b} {d.day}, {d.year}"

    def test_income_lists_announced_pay_dates(self):
        text = self._run("Income")
        self.assertIn("Announced pay dates", text)
        d = date.fromisoformat(self.day(8))
        self.assertIn(f"**{d:%a}, {d:%b} {d.day}** - VTI, pays \\$0.93 a share, ex-dividend "
                      f"{self._words(self.day(3))} (Announced by the company or fund)", text)
        self.assertNotIn("SCHD, pays", text)       # past
        self.assertNotIn("BND, pays", text)        # past the 60 days
        self.assertNotIn("AAPL", text.split("Announced pay dates")[-1].split("Only dates")[0])

    def test_a_tickers_page_shows_its_next_dates(self):
        text = self._run("Ticker", ticker_sym="VTI", ticker_from="Dashboard")
        self.assertIn(f"Next dividend: ex-dividend **{self._words(self.day(3))}**, paid "
                      f"**{self._words(self.day(8))}**, \\$0.93 a share (Announced by the "
                      "company or fund)", text)
        self.assertNotIn("Next earnings report", text)    # a fund
        text = self._run("Ticker", ticker_sym="AAPL", ticker_from="Dashboard")
        # Yahoo's last pay date is past: only its ex date
        self.assertIn(f"Next dividend: ex-dividend **{self._words(self.day(10))}** "
                      "(From Yahoo Finance)", text)
        self.assertIn(f"Next earnings report: **{self._words(self.day(20))}** "
                      "(From Yahoo Finance)", text)
        text = self._run("Ticker", ticker_sym="VXUS", ticker_from="Dashboard")
        self.assertIn("Next dividend: No upcoming date announced yet.", text)

    def test_hidden_amounts_stay_hidden(self):
        text = self._run("Ticker", ticker_sym="VTI", ticker_from="Dashboard",
                         hide_amounts=True)
        self.assertNotIn("0.93", text)


class AdminPanelTests(_DB):
    """Admin > System says whether the key is set - never its value."""

    PANEL = """
import sys, os
sys.path.insert(0, {repo!r})
import pandas as pd
import streamlit as st
import auth, mailer, pgcompat
from portfolio import connect
HERE = {repo!r}
DB = {db!r}
STAGING = False
HOSTED = False
APP_NAME = "Northwend"
LOGIN_ID = {uid}
IS_ADVISOR = False
_app_address = lambda: ""
_anthropic_key = lambda: None
resolve_key = lambda k: None
st.session_state["user_id"] = {uid}
st.session_state["username"] = "boss"
path = os.path.join(HERE, "views", "admin.py")
with open(path, encoding="utf-8") as fh:
    exec(compile(fh.read(), path, "exec"), globals())
c = connect(DB)
_render_system(c)
c.close()
"""

    def _panel(self, env):
        from streamlit.testing.v1 import AppTest
        import admin
        uid = auth.create_user(self.conn, f"boss{len(env)}", "pw-boss-123")
        admin.set_admin(self.conn, f"boss{len(env)}", True)
        keep = {k: v for k, v in os.environ.items()
                if k not in ("POLYGON_API_KEY", "MASSIVE_API_KEY")}
        with unittest.mock.patch.dict(os.environ, {**keep, **env}, clear=True), \
                unittest.mock.patch("dividend_dates.settings.load_env", lambda p: {}):
            at = AppTest.from_string(self.PANEL.format(repo=REPO, db=self.db, uid=uid),
                                     default_timeout=30).run()
        self.assertEqual(len(at.exception), 0, [e.message for e in at.exception])
        return "\n".join(m.value for m in at.markdown)

    def test_set_or_not_never_the_value(self):
        md = self._panel({"POLYGON_API_KEY": "pk-very-secret"})
        self.assertIn("**Dividend dates (Polygon key):** set", md)
        self.assertNotIn("pk-very-secret", md)
        md = self._panel({})
        self.assertIn("**Dividend dates (Polygon key):** not set", md)


if __name__ == "__main__":
    unittest.main()
