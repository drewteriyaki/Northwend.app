"""PLAN G8: when each price is from ("as of"), and "Price look wrong?"
(price_report.py, flag price_report).

- as_of: the stored quote time in words on the market's clock - a time while
  open, the close once shut, the day for a mutual fund, the time for crypto;
  "older" when it's not the latest it could be;
- reports: fixed reasons only, one per ticker a day and PER_DAY a day per
  login; counts-only for admins; in the person's export; gone with the
  account;
- in the app: the words under a ticker's price and on the watchlist, the
  control only with the flag on, nothing read while it's drawn, a tap saves
  one row, and Admin's "Price notes" never names who.

    python -m unittest tests.test_price_report        (from the repo root)
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import admin  # noqa: E402
import advisor  # noqa: E402
import auth  # noqa: E402
import export  # noqa: E402
import flags  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import price_report as pr  # noqa: E402
import sample_data  # noqa: E402
import two_step  # noqa: E402
import whats_new  # noqa: E402

PW = "pw-123456789"
UTC = timezone.utc


def _t(s):
    return datetime.fromisoformat(s).replace(tzinfo=UTC)


# --------------------------------------------------------------------------- #
# as of
# --------------------------------------------------------------------------- #
class AsOfTests(unittest.TestCase):
    # October 2026: the 2nd is a Friday, the 5th a Monday, the 6th a Tuesday;
    # US Eastern is UTC-4.

    def test_a_stock_fetched_while_the_market_is_open_shows_the_time(self):
        a = pr.as_of("2026-10-06T19:45:00Z", "stock", now=_t("2026-10-06T19:50:00"))
        self.assertEqual(a, {"text": "3:45 pm ET", "close": False, "older": False})
        # another day: the day too, and it isn't the latest
        a = pr.as_of("2026-10-05T15:00:00Z", "stock", now=_t("2026-10-06T14:00:00"))
        self.assertEqual((a["text"], a["older"]), ("Oct 5, 11:00 am ET", True))
        # half an hour stale while open
        self.assertTrue(pr.as_of("2026-10-06T19:00:00Z", now=_t("2026-10-06T19:45:00"))["older"])

    def test_after_the_close_evenings_weekends_and_before_the_open_say_the_close(self):
        evening = pr.as_of("2026-10-06T20:05:00Z", now=_t("2026-10-06T23:00:00"))
        self.assertEqual(evening, {"text": "Oct 6 close", "close": True, "older": False})
        saturday = pr.as_of("2026-10-03T15:00:00Z", now=_t("2026-10-03T16:00:00"))
        self.assertEqual((saturday["text"], saturday["older"]), ("Oct 2 close", False))
        early = pr.as_of("2026-10-05T12:00:00Z", now=_t("2026-10-05T12:30:00"))
        self.assertEqual((early["text"], early["older"]), ("Oct 2 close", False))
        # Friday's close, read on Tuesday after the close: an older price
        self.assertTrue(pr.as_of("2026-10-03T15:00:00Z", now=_t("2026-10-06T21:00:00"))["older"])
        # a quote from during the day, the market closed since: older than the close
        self.assertTrue(pr.as_of("2026-10-06T19:45:00Z", now=_t("2026-10-06T20:30:00"))["older"])

    def test_funds_say_the_day_and_crypto_the_time(self):
        f = pr.as_of("2026-10-06T21:30:00Z", "fund", now=_t("2026-10-07T13:00:00"))
        self.assertEqual(f, {"text": "Oct 6", "close": True, "older": False})
        self.assertTrue(pr.as_of("2026-10-01T21:30:00Z", "fund", now=_t("2026-10-07T13:00:00"))
                        ["older"])
        c = pr.as_of("2026-10-03T15:00:00Z", "crypto", now=_t("2026-10-03T15:10:00"))
        self.assertEqual(c, {"text": "11:00 am ET", "close": False, "older": False})
        self.assertTrue(pr.as_of("2026-10-03T15:00:00Z", "crypto",
                                 now=_t("2026-10-03T17:00:00"))["older"])

    def test_the_line_and_what_it_reads(self):
        now = _t("2026-10-06T19:50:00")
        self.assertEqual(pr.as_of_line("2026-10-06T19:45:00Z", now=now),
                         "As of 3:45 pm ET · may be delayed")
        self.assertEqual(pr.as_of_line("2026-10-06T19:00:00Z", now=now),
                         "As of 3:00 pm ET · the latest we have · may be delayed")
        self.assertIn("funds are priced once a day",
                      pr.as_of_line("2026-10-06T19:00:00Z", "fund", now=now))
        # stored forms: 'Z', a space, no zone, a datetime
        for ts in ("2026-10-06 19:45:00", "2026-10-06T19:45:00", _t("2026-10-06T19:45:00")):
            self.assertEqual(pr.as_of(ts, now=now)["text"], "3:45 pm ET")
        for ts in (None, "", "not a time"):
            self.assertIsNone(pr.as_of(ts))
            self.assertEqual(pr.as_of_line(ts), "")
        for line in (pr.THANKS, pr.SAME_TICKER, pr.TOO_MANY, *pr.REASONS.values()):
            for word in ("should", "best", "recommend", "will be fixed", "within"):
                self.assertNotIn(word, line.lower())

    def test_kind(self):
        self.assertEqual(pr.kind("BTC-USD"), "crypto")
        self.assertEqual(pr.kind("X", "Crypto"), "crypto")
        self.assertEqual(pr.kind("VFIAX", "Mutual Funds"), "fund")
        self.assertEqual(pr.kind("VFIAX", None, "MUTUALFUND"), "fund")
        self.assertEqual(pr.kind("VTI", "ETFs & Closed End Funds", "ETF"), "stock")


# --------------------------------------------------------------------------- #
# reports
# --------------------------------------------------------------------------- #
class ReportTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pt_price_report_")
        self.db = os.path.join(self.tmp, "t.db")
        self.conn = portfolio.connect(self.db)
        self.ann = auth.create_user(self.conn, "ann", PW)
        self.bo = auth.create_user(self.conn, "bo", PW)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_report_saves_one_row_with_the_price_shown(self):
        now = _t("2026-10-06T19:50:00")
        res = pr.report(self.conn, self.ann, "vti", "too_high", price=301.25,
                        price_as_of="2026-10-06 19:45:00", now=now)
        self.assertEqual(res, {"ok": True, "message": pr.THANKS})
        row = dict(self.conn.execute("SELECT * FROM price_reports").fetchone())
        row.pop("id")
        self.assertEqual(row, {"user_id": self.ann, "ticker": "VTI", "reason": "too_high",
                               "shown_price": 301.25, "price_as_of": "2026-10-06T19:45:00Z",
                               "created_at": "2026-10-06T19:50:00Z"})

    def test_only_the_fixed_reasons(self):
        for reason in (None, "", "it's wrong, call me", "TOO_HIGH"):
            self.assertFalse(pr.report(self.conn, self.ann, "VTI", reason)["ok"])
        self.assertFalse(pr.report(self.conn, self.ann, "", "old")["ok"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM price_reports").fetchone()[0], 0)

    def test_one_per_ticker_a_day_and_a_few_a_day_in_all(self):
        day = _t("2026-10-06T14:00:00")
        self.assertTrue(pr.report(self.conn, self.ann, "VTI", "old", now=day)["ok"])
        again = pr.report(self.conn, self.ann, "VTI", "too_low", now=day + timedelta(hours=2))
        self.assertEqual(again, {"ok": False, "message": pr.SAME_TICKER})
        # someone else may report the same ticker
        self.assertTrue(pr.report(self.conn, self.bo, "VTI", "old", now=day)["ok"])
        for i, sym in enumerate(("AAA", "BBB", "CCC", "DDD"), start=1):
            self.assertTrue(pr.report(self.conn, self.ann, sym, "old",
                                      now=day + timedelta(minutes=i))["ok"])
        self.assertEqual(pr.report(self.conn, self.ann, "EEE", "old", now=day)["message"],
                         pr.TOO_MANY)
        self.assertEqual(pr.can_report(self.conn, self.ann, "EEE", now=day), pr.TOO_MANY)
        # the next day (UTC) starts afresh
        self.assertTrue(pr.report(self.conn, self.ann, "VTI", "old",
                                  now=_t("2026-10-07T00:00:01"))["ok"])

    def test_admins_see_counts_never_who(self):
        now = _t("2026-10-06T14:00:00")
        pr.report(self.conn, self.ann, "VTI", "old", price_as_of="2026-10-02T20:01:00Z", now=now)
        pr.report(self.conn, self.bo, "VTI", "old", price_as_of="2026-10-05T20:01:00Z", now=now)
        pr.report(self.conn, self.bo, "BND", "too_low", now=now)
        rows = pr.admin_counts(self.conn)
        self.assertEqual(rows[0], {"ticker": "VTI", "reason": "old", "n": 2,
                                   "latest_as_of": "2026-10-05T20:01:00Z",
                                   "latest": "2026-10-06T14:00:00Z"})
        self.assertEqual([(r["ticker"], r["n"]) for r in rows], [("VTI", 2), ("BND", 1)])
        for r in rows:
            self.assertFalse({"user_id", "username"} & set(r))

    def test_in_the_export_and_gone_with_the_account(self):
        pr.report(self.conn, self.ann, "VTI", "wrong_fund", price=10.0)
        pr.report(self.conn, self.bo, "BND", "old")
        mine = export.collect(self.conn, self.ann)["price_reports"]
        self.assertEqual([(r["ticker"], r["reason"]) for r in mine], [("VTI", "wrong_fund")])
        self.assertIn("price_reports", admin.ACCOUNT_TABLES)
        self.assertTrue(admin.delete_account(self.conn, self.ann, by=-1)["ok"])
        self.assertEqual([r["user_id"] for r in self.conn.execute(
            "SELECT user_id FROM price_reports")], [self.bo])

    def test_the_flag_and_whats_new(self):
        self.assertEqual(flags.FEATURES["price_report"]["gates"], ())
        flagged = [i for e in whats_new.ENTRIES for i in e["items"]
                   if isinstance(i, dict) and i.get("flag") == "price_report"]
        self.assertEqual(len(flagged), 1)


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
        cls.dir = tempfile.mkdtemp(prefix="pt_price_report_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.hal = auth.create_user(c, "hal", PW)
            advisor.save_profile(c, cls.hal, {"goal": "Retirement", "time_horizon_years": 25,
                                              "risk_tolerance": "moderate"})
            prefs.save(c, cls.hal, {"first_steps": {"done": True}})
            sample_data.load(c, cls.hal)
            now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            for sym, price in (("VTI", 300.0), ("NVDA", 200.0)):
                c.execute("INSERT INTO price_history (ticker, price, prev_close, change, "
                          "pct_change, fetched_at) VALUES (?, ?, ?, 1.0, 0.5, ?)",
                          (sym, price, price - 1, now))
            c.execute("INSERT INTO watchlist (user_id, ticker) VALUES (?, 'NVDA')", (cls.hal,))
            # an admin
            cls.ann = auth.create_user(c, "ann", PW)
            secret = two_step.new_secret()
            two_step.enable(c, cls.ann, secret, two_step.totp(secret))
            cls.ann_ok = f"{cls.ann}:{two_step.status(c, cls.ann)['stamp']}"
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _run(self, at, flags="", admins="", seen=None):
        import yfinance

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                   NORTHWEND_FLAGS=flags, NORTHWEND_ADMINS=admins)
        real_connect = sqlite3.connect

        def traced(*a, **k):
            conn = real_connect(*a, **k)
            if seen is not None:
                conn.set_trace_callback(seen.append)
            return conn
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline), \
                unittest.mock.patch("sqlite3.connect", traced):
            at.run()
        self.assertEqual([e.message for e in at.exception], [])
        return at

    def _tab(self, uid, name, page, **state):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": page, **state}.items():
            at.session_state[k] = v
        return at

    @staticmethod
    def _pops(at):
        return {p.proto.id.rsplit("-", 1)[-1] for p in at.get("popover")}

    def test_ticker_detail_says_when_and_the_control_waits_for_its_flag(self):
        seen_off, seen_on = [], []
        self._run(self._tab(self.hal, "hal", "Dashboard", holdings_pill="VTI"))   # warm
        at = self._run(self._tab(self.hal, "hal", "Dashboard", holdings_pill="VTI"),
                       seen=seen_off)
        self.assertTrue(any(c.value.startswith("As of ") and c.value.endswith("· may be delayed")
                            for c in at.caption))
        self.assertNotIn("price_report_open_VTI", self._pops(at))
        at = self._run(self._tab(self.hal, "hal", "Dashboard", holdings_pill="VTI"),
                       flags="price_report", seen=seen_on)
        self.assertIn("price_report_open_VTI", self._pops(at))
        # drawing it reads nothing (the trace did see the page's own queries)
        self.assertTrue(seen_on)
        self.assertFalse([s for s in seen_on if "price_reports" in s])
        self.assertEqual(len(seen_on), len(seen_off))   # the same queries as without it
        # Send without a reason: asked to pick one, nothing kept
        at.button(key="price_report_send_VTI").click()
        self._run(at, flags="price_report")
        self.assertIn("Pick one of the reasons first.", [c.value for c in at.caption])
        at.radio(key="price_report_reason_VTI").set_value("too_high")
        at.button(key="price_report_send_VTI").click()
        self._run(at, flags="price_report")
        self.assertIn(pr.THANKS, [c.value for c in at.caption])
        self.assertNotIn("price_report_open_VTI", self._pops(at))
        c = portfolio.connect(self.db)
        try:
            rows = [dict(r) for r in c.execute(
                "SELECT * FROM price_reports WHERE ticker = 'VTI'")]
        finally:
            c.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["user_id"], rows[0]["ticker"], rows[0]["reason"],
                          rows[0]["shown_price"]), (self.hal, "VTI", "too_high", 300.0))
        self.assertTrue(rows[0]["price_as_of"].endswith("Z"))

    def test_homes_price_as_of_column_is_in_words(self):
        import metrics as M
        at = self._run(self._tab(self.hal, "hal", "Dashboard",
                                 col_keys=[*M.DEFAULT_KEYS, "price_at"]))
        label = M.BY_KEY["price_at"].label
        tables = [d.value for d in at.dataframe if label in getattr(d.value, "columns", [])]
        self.assertEqual(len(tables), 1)
        # VTI has a stored quote: its time in words; the rest have none
        words = tables[0][label].tolist()
        timed = [w for w in words if w.endswith(" ET") or w.endswith(" close")]
        self.assertEqual(len(timed), 1, words)
        self.assertEqual(set(words) - set(timed), {"—"})

    def test_the_watchlist_says_when(self):
        at = self._run(self._tab(self.hal, "hal", "Watchlist"))
        rows = [h.proto.body for h in at.get("html") if "<div class='pt-wl-quote'>" in h.proto.body]
        self.assertTrue(rows)
        self.assertTrue(all("class='pt-wl-asof'>as of " in r for r in rows), rows)

    def test_admin_sees_counts_only(self):
        c = portfolio.connect(self.db)
        try:
            pr.report(c, self.hal, "BND", "old", price_as_of="2026-10-02T20:01:00Z")
        finally:
            c.close()
        at = self._run(self._tab(self.ann, "ann", "Admin", two_step_ok=self.ann_ok),
                       admins="ann")
        self.assertNotIn("Price notes", [s.value for s in at.subheader])
        at = self._run(self._tab(self.ann, "ann", "Admin", two_step_ok=self.ann_ok),
                       flags="price_report", admins="ann")
        self.assertIn("Price notes", [s.value for s in at.subheader])
        table = [d.value for d in at.dataframe if "Ticker" in d.value.columns
                 and "Notes" in d.value.columns]
        self.assertEqual(len(table), 1)
        df = table[0]
        self.assertIn("BND", list(df["Ticker"]))
        self.assertEqual(list(df.columns),
                         ["Ticker", "Reason", "Notes", "Latest price time", "Latest note"])


if __name__ == "__main__":
    unittest.main()
