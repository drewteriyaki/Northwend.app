"""Unit tests for the pure logic modules. Standard library only.

    python -m unittest discover -s tests        (from the repo root)
"""

import argparse
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from datetime import date, datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import accounts  # noqa: E402
import advising  # noqa: E402
import advisor  # noqa: E402
import ai_parse  # noqa: E402
import alerts  # noqa: E402
import allocation  # noqa: E402
import auth  # noqa: E402
import manage_users  # noqa: E402
import changes  # noqa: E402
import charts  # noqa: E402
import learn  # noqa: E402
import client_plan  # noqa: E402
import metrics as M  # noqa: E402
import pandas as pd  # noqa: E402
import perf  # noqa: E402
import portfolio  # noqa: E402
import sync_history  # noqa: E402
import update_prices  # noqa: E402
import watchlist  # noqa: E402
import news  # noqa: E402
import overview  # noqa: E402
import pgcompat  # noqa: E402
import plans  # noqa: E402
import prefs  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample_positions.csv")


class TempDBMixin:
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_test_")
        self.db = os.path.join(self.dir, "test.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.user_id = auth.create_user(portfolio.connect(self.db), "testuser", "testpass")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class ParseCsvTests(unittest.TestCase):
    def test_shape(self):
        meta, rows, totals = portfolio.parse_csv(FIXTURE)
        self.assertEqual(meta["snapshot_date"], "2026-01-15")
        self.assertEqual(len(rows), 3)  # cash + totals rows excluded
        self.assertEqual({r["account"] for r in rows}, {"Individual ...111", "Individual ...222"})
        aaa = next(r for r in rows if r["symbol"] == "AAA")
        self.assertEqual(aaa["quantity"], 10.0)
        self.assertEqual(aaa["cost_basis"], 1000.0)
        self.assertEqual(aaa["market_value"], 1200.0)
        self.assertEqual(aaa["asset_type"], "Equity")
        self.assertEqual(totals["Individual ...111"]["cash_value"], 100.0)
        self.assertEqual(totals["Individual ...222"]["reported_gain"], -400.0)

    def test_currency_and_percent_parsing(self):
        self.assertEqual(portfolio.parse_num("$1,007.19"), 1007.19)
        self.assertEqual(portfolio.parse_num("-$290.04"), -290.04)
        self.assertEqual(portfolio.parse_num("($290.04)"), -290.04)
        self.assertEqual(portfolio.parse_num("-28.8%"), -28.8)
        self.assertIsNone(portfolio.parse_num("--"))
        self.assertIsNone(portfolio.parse_num("N/A"))


class ImportTests(TempDBMixin, unittest.TestCase):
    def _count(self, conn, table, **where):
        sql = f"SELECT COUNT(*) FROM {table}"
        args = ()
        if where:
            sql += " WHERE " + " AND ".join(f"{k} = ?" for k in where)
            args = tuple(where.values())
        return conn.execute(sql, args).fetchone()[0]

    def test_import_verifies_and_is_idempotent(self):
        conn = portfolio.connect(self.db)
        info = portfolio.import_csv(conn, FIXTURE, self.user_id)
        self.assertEqual(info["snapshot_date"], "2026-01-15")
        self.assertEqual(info["n_positions"], 3)
        with contextlib.redirect_stdout(io.StringIO()):
            ok = portfolio.verify_snapshot(conn, "2026-01-15")
        self.assertTrue(ok)
        portfolio.import_csv(conn, FIXTURE, self.user_id)  # again
        self.assertEqual(self._count(conn, "positions"), 3)
        self.assertEqual(self._count(conn, "snapshots"), 1)
        conn.close()

    def test_replace_by_date_across_filenames(self):
        other = os.path.join(self.dir, "renamed_export.csv")
        shutil.copyfile(FIXTURE, other)
        conn = portfolio.connect(self.db)
        portfolio.import_csv(conn, FIXTURE, self.user_id)
        portfolio.import_csv(conn, other, self.user_id)  # same date, different path
        self.assertEqual(self._count(conn, "positions", snapshot_date="2026-01-15"), 3)
        self.assertEqual(self._count(conn, "snapshots"), 1)
        conn.close()


class ConnectTests(TempDBMixin, unittest.TestCase):
    def test_creates_all_tables(self):
        conn = portfolio.connect(self.db)
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertLessEqual(
            {"snapshots", "positions", "account_totals", "price_history", "transactions", "value_log"},
            names,
        )
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(price_history)")}
        self.assertLessEqual({"day_open", "day_high", "day_low"}, cols)
        conn.close()


class SchemaSetupRaceTests(unittest.TestCase):
    """Right after a deploy several sessions connect at once. Setup must run
    once, not concurrently - on Postgres, racing CREATE TABLE IF NOT EXISTS
    raised psycopg.errors.UniqueViolation on the live app's first login."""

    def test_concurrent_connects_set_up_the_schema_once(self):
        import threading
        import time
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        db = os.path.join(tmp, "race.db")
        real, calls = portfolio._ensure_schema, []

        def slow_ensure(conn):
            calls.append(1)
            time.sleep(0.2)  # wide window for a second thread to slip in
            real(conn)

        errors = []

        def worker():
            try:
                portfolio.connect(db).close()  # SQLite: close in the opening thread
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        with unittest.mock.patch.object(portfolio, "_ensure_schema", slow_ensure):
            threads = [threading.Thread(target=worker) for _ in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(calls), 1)

    def test_postgres_setup_takes_the_advisory_lock_first(self):
        executed = []

        class FakeCursor:
            description = None

            def execute(self, sql, params=None):
                executed.append((sql, params))

            def __iter__(self):
                return iter([])

            def fetchall(self):
                return []

        class FakeRaw:
            def cursor(self):
                return FakeCursor()

            def commit(self):
                executed.append(("COMMIT", None))

        portfolio._ensure_schema(pgcompat.ConnWrapper(FakeRaw()))
        first_sql, first_params = executed[0]
        self.assertIn("pg_advisory_xact_lock", first_sql)
        self.assertIn("%s", first_sql)                      # placeholder translated for psycopg
        self.assertEqual(first_params, (portfolio.SCHEMA_ADVISORY_LOCK_ID,))
        self.assertEqual(executed[-1][0], "COMMIT")          # the lock is released by this commit
        self.assertTrue(any("CREATE TABLE" in sql for sql, _ in executed[1:]))


class DiffTests(unittest.TestCase):
    OLD = [
        {"account": "A", "symbol": "X", "description": "x", "quantity": 10, "cost_basis": 1000, "market_value": 1200},
        {"account": "A", "symbol": "Y", "description": "y", "quantity": 5, "cost_basis": 500, "market_value": 400},
        {"account": "A", "symbol": "Z", "description": "z", "quantity": 3, "cost_basis": 300, "market_value": 330},
    ]
    NEW = [
        {"account": "A", "symbol": "X", "description": "x", "quantity": 13, "cost_basis": 1300, "market_value": 1600},
        {"account": "A", "symbol": "Y", "description": "y", "quantity": 2, "cost_basis": 200, "market_value": 170},
        {"account": "A", "symbol": "W", "description": "w", "quantity": 7, "cost_basis": 700, "market_value": 720},
    ]

    def test_buckets(self):
        d = changes.diff_positions(self.OLD, self.NEW)
        self.assertEqual([e["symbol"] for e in d["new"]], ["W"])
        self.assertEqual([e["symbol"] for e in d["increased"]], ["X"])
        self.assertEqual([e["symbol"] for e in d["decreased"]], ["Y"])
        self.assertEqual([e["symbol"] for e in d["closed"]], ["Z"])
        self.assertEqual(d["unchanged"], [])

    def test_synthesized_transactions(self):
        d = changes.diff_positions(self.OLD, self.NEW)
        txns = {t["symbol"]: t for t in changes.synthesize_transactions(d, "2026-02-01", "f.csv")}
        self.assertEqual(txns["W"]["action"], "BUY")
        self.assertEqual(txns["W"]["amount"], -700.0)          # cash out
        self.assertEqual(txns["X"]["action"], "BUY")
        self.assertEqual(txns["X"]["quantity"], 3)             # the delta only
        self.assertEqual(txns["X"]["amount"], -300.0)
        self.assertEqual(txns["Y"]["action"], "SELL")
        self.assertEqual(txns["Y"]["quantity"], 3)
        self.assertGreater(txns["Y"]["amount"], 0)             # cash in
        self.assertEqual(txns["Z"]["action"], "SELL")
        self.assertEqual(txns["Z"]["amount"], 330.0)
        # realized_gain: average-cost method, SELL only
        self.assertIsNone(txns["W"]["realized_gain"])          # BUY -> not applicable
        self.assertIsNone(txns["X"]["realized_gain"])          # BUY -> not applicable
        # Y: sold 3 of 5 @ avg cost 100/share ($300 basis removed) for $255 -> -$45
        self.assertAlmostEqual(txns["Y"]["realized_gain"], -45.0)
        # Z: closed entirely, $330 proceeds - $300 cost basis -> +$30
        self.assertAlmostEqual(txns["Z"]["realized_gain"], 30.0)


class AllocationTests(unittest.TestCase):
    POS = [
        {"account": "A", "symbol": "X", "asset_type": "Equity", "market_value": 2000, "live_market_value": None},
        {"account": "A", "symbol": "Y", "asset_type": "ETFs & Closed End Funds", "market_value": 1000, "live_market_value": 1200},
        {"account": "B", "symbol": "Z", "asset_type": "Equity", "market_value": 500, "live_market_value": None},
    ]

    def test_breakdown_and_concentration(self):
        r = allocation.allocate(self.POS, {"A": 300, "B": 0})
        self.assertEqual(r["portfolio_value"], 2000 + 1200 + 500 + 300)
        self.assertEqual(r["by_asset_type"][0]["label"], "Equity")       # 2500, largest
        self.assertTrue(any(x["label"] == "Cash" for x in r["by_asset_type"]))
        self.assertEqual(r["by_asset_type"][1]["label"], "ETF / CEF")    # short label
        self.assertEqual(r["concentration"][0]["symbol"], "X")           # 2000/4000 = 50%
        self.assertTrue(all(c["pct"] > allocation.CONCENTRATION_PCT for c in r["concentration"]))


class AlertTests(unittest.TestCase):
    @staticmethod
    def _ctx(sym, day_pct, gl_pct):
        return {"pos": {"symbol": sym, "account": "A", "day_change_pct": day_pct,
                        "cost_basis": 100, "market_value": 100 + gl_pct},
                "quote": {}, "port_value": 1000, "acct_value": 1000}

    def test_default_rules(self):
        rows = [self._ctx("AAA", -6.0, -25), self._ctx("BBB", 2.0, -5),
                self._ctx("CCC", 7.5, 30), self._ctx("DDD", -1.0, -21)]
        fired = {(a.symbol, a.rule_key) for a in alerts.evaluate(rows)}
        self.assertIn(("AAA", "day_move"), fired)
        self.assertIn(("AAA", "total_gl"), fired)
        self.assertIn(("CCC", "day_move"), fired)
        self.assertIn(("DDD", "total_gl"), fired)
        self.assertNotIn(("DDD", "day_move"), fired)
        self.assertNotIn(("BBB", "day_move"), fired)
        self.assertNotIn(("BBB", "total_gl"), fired)

    def test_sorted_worst_first_and_custom_threshold(self):
        rows = [self._ctx("AAA", -6.0, -25), self._ctx("CCC", 7.5, 30)]
        fired = alerts.evaluate(rows)
        self.assertEqual([abs(a.value) for a in fired], sorted((abs(a.value) for a in fired), reverse=True))
        loose = alerts.evaluate(rows, [{**alerts.DEFAULT_RULES[0], "abs_gt": 1.0}])
        self.assertEqual({a.rule_key for a in loose}, {"day_move"})


class MetricsTests(unittest.TestCase):
    def test_effective_price_and_mv_fallbacks(self):
        live = {"pos": {"live_price": 50.0, "live_market_value": 500.0, "quantity": 10,
                        "market_value": 480, "cost_basis": 400}, "quote": {}}
        self.assertEqual(M.eff_price(live), 50.0)
        self.assertEqual(M.eff_mv(live), 500.0)
        quote_only = {"pos": {"quantity": 10, "market_value": 480, "cost_basis": 400},
                      "quote": {"price": 49.0}}
        self.assertEqual(M.eff_price(quote_only), 49.0)
        self.assertEqual(M.eff_mv(quote_only), 490.0)
        csv_only = {"pos": {"quantity": 10, "market_value": 480, "cost_basis": 400}, "quote": {}}
        self.assertEqual(M.eff_price(csv_only), 48.0)
        self.assertEqual(M.eff_mv(csv_only), 480.0)
        # no position at all (a watchlist ticker) - falls back to the last
        # known Yahoo daily close instead of returning None
        watchlist_only = {"pos": {}, "quote": {}, "stats": {"last_close": 123.45}}
        self.assertEqual(M.eff_price(watchlist_only), 123.45)
        self.assertIsNone(M.eff_price({"pos": {}, "quote": {}, "stats": {}}))

    def test_derived_values_and_safety(self):
        ctx = {"pos": {"symbol": "X", "quantity": 10, "cost_basis": 400, "market_value": 480,
                       "live_price": 50.0, "live_market_value": 500.0},
               "quote": {"pct_change": 1.5, "change": 0.75, "day_high": 51.0},
               "port_value": 2000, "acct_value": 1000}
        self.assertAlmostEqual(M.value("unrealized_usd", ctx), 100.0)
        self.assertAlmostEqual(M.value("unrealized_pct", ctx), 25.0)
        self.assertAlmostEqual(M.value("day_change_usd", ctx), 7.5)
        self.assertAlmostEqual(M.value("pct_of_portfolio", ctx), 25.0)
        self.assertIsNone(M.value("ma_50", ctx))                 # registered but unavailable
        self.assertIsNone(M.value("not_a_metric", {}))           # unknown key -> None, no raise
        self.assertIsNone(M.value("unrealized_usd", {"pos": {}, "quote": {}}))  # missing data -> None


class PerfTests(TempDBMixin, unittest.TestCase):
    AGG = {"snapshot_date": "2026-01-15", "portfolio_value": 3400.0, "holdings_value": 3250.0,
           "cash": 150.0, "cost_basis": 3500.0, "unrealized_gain": -250.0,
           "unrealized_gain_pct": -7.14, "day_change_usd": -12.0, "n_positions": 3,
           "n_priced": 3, "priced_at": "2026-01-15T21:00:00Z"}

    def test_log_open_throttle_and_history(self):
        portfolio.connect(self.db).close()  # create schema
        self.assertTrue(perf.log_open(self.db, self.user_id, self.AGG))
        self.assertFalse(perf.log_open(self.db, self.user_id, self.AGG))          # within the gap
        self.assertTrue(perf.log_open(self.db, self.user_id, self.AGG, min_gap_sec=0))
        # snapshot rows come from positions; add one via import
        conn = portfolio.connect(self.db)
        portfolio.import_csv(conn, FIXTURE, self.user_id)
        conn.close()
        # snapshots are opt-in; the default performance line is app_open (+ reconstructed)
        self.assertEqual({r["source"] for r in perf.history(self.db, self.user_id)}, {"app_open"})
        hist = perf.history(self.db, self.user_id, include_snapshots=True)
        self.assertEqual({r["source"] for r in hist}, {"snapshot", "app_open"})
        snap_row = next(r for r in hist if r["source"] == "snapshot")
        self.assertEqual(snap_row["source_label"], perf.SOURCE_LABEL["snapshot"])
        self.assertAlmostEqual(snap_row["portfolio_value"], 3400.0, places=2)

    def test_last_open_returns_most_recent_row(self):
        # Callers must call last_open() BEFORE log_open() writes the current
        # session's own row, or "since you last opened" just compares the
        # portfolio to itself - last_open() itself has no special-casing for
        # that, it always just returns the newest app_open row.
        portfolio.connect(self.db).close()
        self.assertIsNone(perf.last_open(self.db, self.user_id))          # never opened before
        perf.log_open(self.db, self.user_id, self.AGG, min_gap_sec=0)
        first = perf.last_open(self.db, self.user_id)
        self.assertAlmostEqual(first["portfolio_value"], 3400.0, places=2)
        newer_agg = {**self.AGG, "portfolio_value": 5000.0}
        perf.log_open(self.db, self.user_id, newer_agg, min_gap_sec=0)
        second = perf.last_open(self.db, self.user_id)
        self.assertAlmostEqual(second["portfolio_value"], 5000.0, places=2)


class PerfBarsTests(TempDBMixin, unittest.TestCase):
    def _seed(self):
        conn = portfolio.connect(self.db)
        portfolio.import_csv(conn, FIXTURE, self.user_id)  # AAA qty10 cost1000, BBB qty5 cost500, CCC qty2 cost2000
        bars = []
        # 60 trading days; AAA rises 100->? , CCC flat, BBB only has 30 days (recent listing)
        for i in range(60):
            date = f"2026-01-{i + 1:02d}" if i < 31 else f"2026-02-{i - 30:02d}"
            bars.append(("AAA", date, 100.0 + i))
            bars.append(("CCC", date, 800.0))
            if i >= 30:
                bars.append(("BBB", date, 90.0))
        conn.executemany(
            "INSERT INTO daily_bars (ticker, date, close, volume) VALUES (?, ?, ?, 1000)", bars)
        conn.commit()
        conn.close()

    def test_ticker_bars_moving_averages(self):
        self._seed()
        rows = perf.ticker_bars(self.db, "AAA")
        self.assertEqual(len(rows), 60)
        self.assertIsNone(rows[18]["ma_20"])                 # < 20 bars
        self.assertAlmostEqual(rows[19]["ma_20"], sum(100.0 + j for j in range(20)) / 20)
        self.assertIsNone(rows[59]["ma_200"])                # never enough for 200

    def test_bar_stats(self):
        self._seed()
        s = perf.bar_stats(self.db)["AAA"]
        self.assertEqual(s["last_close"], 159.0)             # 100 + 59
        self.assertEqual(s["volume"], 1000)
        self.assertAlmostEqual(s["ma_20"], sum(100.0 + j for j in range(40, 60)) / 20)

    def test_coverage_and_reconstruction(self):
        self._seed()
        covered, missing = perf.holdings_coverage(self.db, self.user_id)
        self.assertEqual(set(covered), {"AAA", "BBB", "CCC"})
        self.assertEqual(missing, [])
        hist = perf.history(self.db, self.user_id)
        rec = [r for r in hist if r["source"] == "reconstructed"]
        self.assertEqual(len(rec), 60)
        self.assertEqual(rec[0]["n_positions"], 2)           # BBB not listed yet
        self.assertEqual(rec[-1]["n_positions"], 3)
        # last day: AAA 10*159 + BBB 5*90 + CCC 2*800 + cash(150) = 1590+450+1600+150
        self.assertAlmostEqual(rec[-1]["portfolio_value"], 1590 + 450 + 1600 + 150, places=2)

    def test_reconstruction_forward_fills_asynchronous_tickers(self):
        # AAA and CCC don't report a bar at the same instant every minute -
        # a naive "exact timestamp match" sum would make the portfolio value
        # swing based on which ticker happened to report, not on real moves.
        conn = portfolio.connect(self.db)
        portfolio.import_csv(conn, FIXTURE, self.user_id)  # AAA qty10 cost1000, CCC qty2 cost2000
        now = datetime.now(timezone.utc).replace(microsecond=0)
        t0 = (now - timedelta(minutes=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        t1 = (now - timedelta(minutes=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
        t2 = (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.executemany(
            "INSERT INTO intraday_bars (ticker, interval, ts, close, volume) VALUES (?,?,?,?,1000)", [
                ("AAA", "1m", t0, 100.0),
                ("CCC", "1m", t1, 800.0),   # AAA silent this minute
                ("AAA", "1m", t2, 102.0),   # CCC silent this minute
            ])
        conn.commit()
        conn.close()

        hist = perf.history(self.db, self.user_id, days=1)
        rec = [r for r in hist if r["source"] == "reconstructed"]
        self.assertEqual([r["t"] for r in rec], [t0, t1, t2])
        # 14:30: only AAA has reported anything yet -> partial (matches
        # "a newly-listed holding joins once its bars begin")
        self.assertEqual(rec[0]["n_positions"], 1)
        self.assertAlmostEqual(rec[0]["holdings_value"], 10 * 100.0)
        # 14:31: AAA's 14:30 close carries forward (not dropped) + CCC's fresh 800
        self.assertEqual(rec[1]["n_positions"], 2)
        self.assertAlmostEqual(rec[1]["holdings_value"], 10 * 100.0 + 2 * 800.0)
        # 14:32: AAA's fresh 102 + CCC's 14:31 close carries forward (not dropped)
        self.assertEqual(rec[2]["n_positions"], 2)
        self.assertAlmostEqual(rec[2]["holdings_value"], 10 * 102.0 + 2 * 800.0)

    def test_history_empty_without_data(self):
        conn = portfolio.connect(self.db)
        portfolio.import_csv(conn, FIXTURE, self.user_id)
        conn.close()
        self.assertFalse(perf.has_bars(self.db))
        self.assertEqual(perf.history(self.db, self.user_id), [])                       # nothing to plot yet
        self.assertEqual({r["source"] for r in perf.history(self.db, self.user_id, include_snapshots=True)},
                         {"snapshot"})


class IntradayTests(TempDBMixin, unittest.TestCase):
    def _seed(self):
        conn = portfolio.connect(self.db)
        portfolio.import_csv(conn, FIXTURE, self.user_id)  # AAA, BBB, CCC
        now = datetime.now(timezone.utc)

        def stamp(minutes_ago):
            return (now - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")

        rows_1m = [("AAA", "1m", stamp(m), 100.0 + m) for m in range(10, 0, -1)]     # last 10 min
        rows_5m = [("AAA", "5m", stamp(m), 100.0 + m) for m in range(4000, 0, -5)]   # spans >7d
        rows_60m = [("AAA", "60m", stamp(m), 100.0 + m) for m in range(90000, 0, -60)]  # spans >60d
        conn.executemany(
            "INSERT INTO intraday_bars (ticker, interval, ts, close, volume) VALUES (?,?,?,?,1000)",
            rows_1m + rows_5m + rows_60m)
        conn.executemany(
            "INSERT INTO daily_bars (ticker, date, close, volume) VALUES (?,?,?,1000)",
            [("AAA", f"2020-01-{d:02d}", 50.0 + d) for d in range(1, 29)])
        conn.commit()
        conn.close()

    def test_intervals_for_thresholds(self):
        self.assertEqual(perf._intervals_for(1), ["1m", "5m", "15m", "60m", "1d"])
        self.assertEqual(perf._intervals_for(7), ["1m", "5m", "15m", "60m", "1d"])
        self.assertEqual(perf._intervals_for(8), ["5m", "15m", "60m", "1d"])
        self.assertEqual(perf._intervals_for(60), ["5m", "15m", "60m", "1d"])
        self.assertEqual(perf._intervals_for(61), ["60m", "1d"])
        self.assertEqual(perf._intervals_for(730), ["60m", "1d"])
        self.assertEqual(perf._intervals_for(731), ["1d"])
        self.assertEqual(perf._intervals_for(None), ["1d"])

    def test_ticker_series_picks_finest_available_resolution(self):
        self._seed()
        rows, interval = perf.ticker_series(self.db, "AAA", 1)      # "1D" -> the 1m bars
        self.assertEqual(interval, "1m")
        self.assertEqual(len(rows), 10)

        rows, interval = perf.ticker_series(self.db, "AAA", 30)     # 1m/15m don't cover -> 5m
        self.assertEqual(interval, "5m")

        rows, interval = perf.ticker_series(self.db, "AAA", 365)    # only 60m covers a year
        self.assertEqual(interval, "60m")

        rows, interval = perf.ticker_series(self.db, "AAA", None)   # "All" -> daily
        self.assertEqual(interval, "1d")
        self.assertEqual(len(rows), 28)
        self.assertIn("ma_20", rows[0])                             # daily rows carry MA cols

    def test_ticker_series_falls_back_when_no_intraday(self):
        conn = portfolio.connect(self.db)
        portfolio.import_csv(conn, FIXTURE, self.user_id)
        conn.executemany(
            "INSERT INTO daily_bars (ticker, date, close, volume) VALUES (?,?,?,1000)",
            [("AAA", f"2020-01-{d:02d}", 50.0 + d) for d in range(1, 5)])
        conn.commit()
        conn.close()
        rows, interval = perf.ticker_series(self.db, "AAA", 1)      # no intraday synced
        self.assertEqual(interval, "1d")
        self.assertEqual(len(rows), 2)                              # last-2 fallback, not empty

    def test_ticker_has_bars_and_has_intraday(self):
        self.assertFalse(perf.has_intraday(self.db))
        self._seed()
        self.assertTrue(perf.has_intraday(self.db))
        self.assertTrue(perf.ticker_has_bars(self.db, "AAA"))
        self.assertFalse(perf.ticker_has_bars(self.db, "ZZZ"))


class SyncHistoryUnitTests(TempDBMixin, unittest.TestCase):
    """Pure/storage-layer tests only - no network calls."""

    def test_num_coerces_and_drops_nan(self):
        self.assertEqual(sync_history._num("1.5"), 1.5)
        self.assertIsNone(sync_history._num(None))
        self.assertIsNone(sync_history._num(float("nan")))
        self.assertIsNone(sync_history._num("not a number"))

    def test_upsert_intraday_idempotent(self):
        conn = portfolio.connect(self.db)
        rows = [{"ts": "2026-01-01T14:30:00Z", "open": 1, "high": 2, "low": 0.5, "close": 1.5,
                "volume": 100}]
        sync_history.upsert_intraday(conn, "AAA", "1m", rows)
        sync_history.upsert_intraday(conn, "AAA", "1m", rows)  # re-sync same bar
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM intraday_bars").fetchone()[0]
        self.assertEqual(n, 1)
        updated = [{**rows[0], "close": 9.9}]
        sync_history.upsert_intraday(conn, "AAA", "1m", updated)
        conn.commit()
        close = conn.execute("SELECT close FROM intraday_bars").fetchone()[0]
        self.assertEqual(close, 9.9)                                # updates in place
        conn.close()


class _ConnectReached(Exception):
    """Raised by a patched connect() to prove the isfile guard let a
    Postgres DSN through without a network call actually happening."""


class CliPostgresDsnGuardTests(unittest.TestCase):
    """update_prices.py and sync_history.py both gate their --db argument on
    os.path.isfile() before connecting - correct for a local SQLite path,
    but a Postgres DSN (e.g. from the GitHub Actions scheduled-sync
    workflow's DATABASE_URL secret) is never a real file on disk, so a
    naive isfile() check would reject every hosted-deploy run with a
    misleading "No database at ..." error before ever reaching connect().
    Caught while wiring up the scheduled-sync workflow, before it ever ran
    in CI - not by these tests failing first, but these lock the fix in."""

    DSN = "postgresql://user:pw@example.neon.tech/neondb?sslmode=require"

    def test_update_prices_skips_isfile_check_for_postgres_dsn(self):
        with unittest.mock.patch.object(update_prices, "connect",
                                         side_effect=_ConnectReached):
            with self.assertRaises(_ConnectReached):
                update_prices.main(["--db", self.DSN, "--key", "dummy", "--user", "testuser"])

    def test_sync_history_skips_isfile_check_for_postgres_dsn(self):
        with unittest.mock.patch.object(sync_history, "connect",
                                         side_effect=_ConnectReached):
            with self.assertRaises(_ConnectReached):
                sync_history.main(["--db", self.DSN, "--no-info", "--no-intraday"])


class LoginLockoutTests(TempDBMixin, unittest.TestCase):
    T0 = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)

    def _fail(self, conn, n, username="testuser", start=None):
        t = start or self.T0
        for i in range(n):
            r = auth.attempt_login(conn, username, "wrong", now=t + timedelta(seconds=i))
        return r

    def test_locks_after_the_limit_even_for_the_right_password(self):
        conn = portfolio.connect(self.db)
        r = self._fail(conn, auth.MAX_FAILED_LOGINS - 1)
        self.assertEqual((r["locked_minutes"], r["attempts_left"]), (0, 1))
        r = self._fail(conn, 1, start=self.T0 + timedelta(minutes=1))
        self.assertEqual(r["locked_minutes"], auth.LOCKOUT_MINUTES)
        ok = auth.attempt_login(conn, "testuser", "testpass", now=self.T0 + timedelta(minutes=2))
        self.assertIsNone(ok["user_id"])                               # locked: password not checked
        self.assertGreater(ok["locked_minutes"], 0)
        later = self.T0 + timedelta(minutes=1 + auth.LOCKOUT_MINUTES, seconds=5)
        ok = auth.attempt_login(conn, "testuser", "testpass", now=later)
        self.assertEqual(ok["user_id"], self.user_id)                  # lock ran out
        conn.close()

    def test_success_resets_and_old_failures_expire(self):
        conn = portfolio.connect(self.db)
        self._fail(conn, auth.MAX_FAILED_LOGINS - 1)
        self.assertEqual(auth.attempt_login(conn, "testuser", "testpass", now=self.T0 + timedelta(minutes=1))
                         ["user_id"], self.user_id)
        r = self._fail(conn, 1, start=self.T0 + timedelta(minutes=2))
        self.assertEqual(r["attempts_left"], auth.MAX_FAILED_LOGINS - 1)  # count started over
        # failures spread past the window never add up to a lock
        conn2 = portfolio.connect(self.db)
        for i in range(auth.MAX_FAILED_LOGINS + 2):
            r = auth.attempt_login(conn2, "slowguesser", "x",
                                   now=self.T0 + timedelta(minutes=(auth.LOCKOUT_MINUTES + 1) * i))
        self.assertEqual(r["locked_minutes"], 0)
        conn2.close()
        conn.close()

    def test_unknown_usernames_lock_the_same_and_case_is_ignored(self):
        conn = portfolio.connect(self.db)
        r = self._fail(conn, auth.MAX_FAILED_LOGINS, username="nobody")
        self.assertEqual(r["locked_minutes"], auth.LOCKOUT_MINUTES)   # same as a real account
        self._fail(conn, auth.MAX_FAILED_LOGINS - 1, username="TestUser")
        r = auth.attempt_login(conn, "testuser", "nope", now=self.T0 + timedelta(seconds=30))
        self.assertEqual(r["locked_minutes"], auth.LOCKOUT_MINUTES)   # 'TestUser' counted too
        keys = [row["username_key"] for row in conn.execute("SELECT username_key FROM login_failures")]
        self.assertTrue(all(len(k) == 64 and "user" not in k for k in keys))  # hashed, not stored
        conn.close()

    def test_password_change_and_unlock_clear_a_lock(self):
        conn = portfolio.connect(self.db)
        self._fail(conn, auth.MAX_FAILED_LOGINS)
        auth.set_password(conn, "testuser", "new-password")
        self.assertEqual(auth.attempt_login(conn, "testuser", "new-password",
                                            now=self.T0 + timedelta(minutes=1))["user_id"], self.user_id)
        self._fail(conn, auth.MAX_FAILED_LOGINS, start=self.T0 + timedelta(minutes=2))
        self.assertTrue(auth.unlock_login(conn, "testuser"))
        self.assertFalse(auth.unlock_login(conn, "testuser"))
        self.assertEqual(auth.attempt_login(conn, "testuser", "new-password",
                                            now=self.T0 + timedelta(minutes=3))["user_id"], self.user_id)
        conn.close()


class ChangePasswordTests(TempDBMixin, unittest.TestCase):
    NEW = "brand-new-pass"

    def test_change_ends_other_sessions_and_keeps_this_one(self):
        conn = portfolio.connect(self.db)
        other = auth.create_session(conn, self.user_id)
        before = auth.password_stamp(conn, self.user_id)
        r = auth.change_password(conn, self.user_id, "testpass", self.NEW, keep_session=True)
        self.assertTrue(r["ok"])
        self.assertIsNone(auth.verify_login(conn, "testuser", "testpass"))
        self.assertEqual(auth.verify_login(conn, "testuser", self.NEW), self.user_id)
        self.assertIsNone(auth.session_user(conn, other))                 # other device signed out
        self.assertEqual(auth.session_user(conn, r["token"]), (self.user_id, "testuser"))
        self.assertNotEqual(auth.password_stamp(conn, self.user_id), before)  # open tabs notice
        self.assertIsNone(auth.change_password(conn, self.user_id, self.NEW, "another-pass")["token"])
        conn.close()

    def test_rejections_leave_the_password_alone(self):
        conn = portfolio.connect(self.db)
        for current, new in (("testpass", "short"), ("wrong", self.NEW), ("testpass", "testpass")):
            r = auth.change_password(conn, self.user_id, current, new)
            self.assertFalse(r["ok"])
            self.assertTrue(r["error"])
        self.assertEqual(auth.verify_login(conn, "testuser", "testpass"), self.user_id)
        # "must be different" only once the current password is right, so it
        # can't be used to confirm a guess
        self.assertIn("wrong", auth.change_password(conn, self.user_id, "guess-123", "guess-123")["error"])
        conn.close()

    def test_wrong_current_passwords_hit_the_login_lockout(self):
        conn = portfolio.connect(self.db)
        for _ in range(auth.MAX_FAILED_LOGINS):
            auth.change_password(conn, self.user_id, "wrong", self.NEW)
        r = auth.change_password(conn, self.user_id, "testpass", self.NEW)
        self.assertFalse(r["ok"])
        self.assertIn("Too many", r["error"])
        self.assertGreater(auth.attempt_login(conn, "testuser", "testpass")["locked_minutes"], 0)
        conn.close()

    def test_stamp_is_none_for_a_missing_account(self):
        conn = portfolio.connect(self.db)
        self.assertIsNone(auth.password_stamp(conn, 999999))
        self.assertEqual(len(auth.password_stamp(conn, self.user_id)), 16)
        conn.close()


class StaySignedInTests(TempDBMixin, unittest.TestCase):
    def test_token_signs_in_until_it_expires(self):
        conn = portfolio.connect(self.db)
        t0 = datetime(2026, 9, 1, tzinfo=timezone.utc)
        token = auth.create_session(conn, self.user_id, now=t0)
        self.assertEqual(auth.session_user(conn, token, now=t0), (self.user_id, "testuser"))
        late = t0 + timedelta(days=auth.SESSION_DAYS, seconds=1)
        self.assertIsNone(auth.session_user(conn, token, now=late))
        self.assertIsNone(auth.session_user(conn, "not-a-real-token", now=t0))
        self.assertIsNone(auth.session_user(conn, None))
        conn.close()

    def test_only_a_hash_of_the_token_is_stored(self):
        conn = portfolio.connect(self.db)
        token = auth.create_session(conn, self.user_id)
        stored = [r["token_hash"] for r in conn.execute("SELECT token_hash FROM login_sessions")]
        self.assertEqual(len(stored), 1)
        self.assertNotIn(token, stored[0])
        conn.close()

    def test_logout_ends_only_that_session(self):
        conn = portfolio.connect(self.db)
        phone, laptop = auth.create_session(conn, self.user_id), auth.create_session(conn, self.user_id)
        auth.end_session(conn, phone)
        self.assertIsNone(auth.session_user(conn, phone))
        self.assertEqual(auth.session_user(conn, laptop), (self.user_id, "testuser"))
        conn.close()

    def test_password_change_signs_out_everywhere(self):
        conn = portfolio.connect(self.db)
        other = auth.create_user(conn, "other", "pw-other")
        mine, theirs = auth.create_session(conn, self.user_id), auth.create_session(conn, other)
        auth.set_password(conn, "testuser", "a-new-password")
        self.assertIsNone(auth.session_user(conn, mine))
        self.assertEqual(auth.session_user(conn, theirs), (other, "other"))  # other users unaffected
        conn.close()

    def test_new_session_clears_expired_ones(self):
        conn = portfolio.connect(self.db)
        t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        auth.create_session(conn, self.user_id, now=t0)
        auth.create_session(conn, self.user_id, now=t0 + timedelta(days=auth.SESSION_DAYS + 1))
        n = conn.execute("SELECT COUNT(*) AS n FROM login_sessions").fetchone()["n"]
        self.assertEqual(n, 1)
        conn.close()


class AuthTests(TempDBMixin, unittest.TestCase):
    """TempDBMixin already created one user ('testuser'/'testpass', id
    self.user_id) via auth.create_user() in setUp - these tests exercise
    the rest of the auth surface directly."""

    def test_verify_login_round_trip(self):
        conn = portfolio.connect(self.db)
        self.assertEqual(auth.verify_login(conn, "testuser", "testpass"), self.user_id)

    def test_verify_login_rejects_wrong_password(self):
        conn = portfolio.connect(self.db)
        self.assertIsNone(auth.verify_login(conn, "testuser", "wrongpass"))

    def test_verify_login_rejects_unknown_username(self):
        conn = portfolio.connect(self.db)
        self.assertIsNone(auth.verify_login(conn, "nosuchuser", "whatever"))

    def test_duplicate_username_rejected(self):
        conn = portfolio.connect(self.db)
        with self.assertRaises(portfolio.DBError):
            auth.create_user(conn, "testuser", "anotherpass")

    def test_set_password_changes_login(self):
        conn = portfolio.connect(self.db)
        self.assertTrue(auth.set_password(conn, "testuser", "newpass"))
        self.assertIsNone(auth.verify_login(conn, "testuser", "testpass"))     # old password now rejected
        self.assertEqual(auth.verify_login(conn, "testuser", "newpass"), self.user_id)

    def test_set_password_unknown_user_returns_false(self):
        conn = portfolio.connect(self.db)
        self.assertFalse(auth.set_password(conn, "nosuchuser", "whatever"))

    def test_two_users_never_see_each_others_data(self):
        """The core multi-tenancy guarantee: create a second account in the
        same database, import a DIFFERENT csv for it, and confirm every
        user-owned read (positions, watchlist, value_log/perf.history) for
        user A never returns user B's rows, and vice versa."""
        conn = portfolio.connect(self.db)
        user_a = self.user_id
        user_b = auth.create_user(conn, "otheruser", "otherpass")

        portfolio.import_csv(conn, FIXTURE, user_a)
        other_fixture = os.path.join(self.dir, "other_positions.csv")
        shutil.copyfile(FIXTURE, other_fixture)
        # re-date the second file's snapshot so both users have distinct,
        # independently-verifiable data even though they share a "date" concept
        portfolio.import_csv(conn, other_fixture, user_b)

        a_positions = conn.execute(
            "SELECT symbol FROM positions WHERE user_id = ?", (user_a,)).fetchall()
        b_positions = conn.execute(
            "SELECT symbol FROM positions WHERE user_id = ?", (user_b,)).fetchall()
        self.assertEqual(len(a_positions), 3)
        self.assertEqual(len(b_positions), 3)

        watchlist.add(conn, user_a, "NVDA")
        watchlist.add(conn, user_b, "AMD")
        self.assertEqual(watchlist.list_tickers(conn, user_a), ["NVDA"])
        self.assertEqual(watchlist.list_tickers(conn, user_b), ["AMD"])

        perf.log_open(self.db, user_a, {"portfolio_value": 111}, min_gap_sec=0)
        perf.log_open(self.db, user_b, {"portfolio_value": 222}, min_gap_sec=0)
        self.assertEqual(perf.last_open(self.db, user_a)["portfolio_value"], 111)
        self.assertEqual(perf.last_open(self.db, user_b)["portfolio_value"], 222)


class _FakeCreateClient:
    """Stands in for anthropic.Anthropic for a single messages.create() call."""

    def __init__(self, text):
        self._text = text
        self.messages = self

    def create(self, **kwargs):
        self.kwargs = kwargs
        return _Obj(stop_reason="end_turn", content=[_Obj(type="text", text=self._text)])


def _fake_anthropic_response(mapping_dict_or_text) -> "_FakeCreateClient":
    text = (mapping_dict_or_text if isinstance(mapping_dict_or_text, str)
            else json.dumps(mapping_dict_or_text))
    return _FakeCreateClient(text)


class AiParseTests(unittest.TestCase):
    HEADER = ["Ticker", "Name", "Shares", "Basis", "Value", "Type"]
    FULL_MAPPING = {f: None for f in ai_parse.ALL_FIELDS}

    def _valid_mapping(self):
        m = dict(self.FULL_MAPPING)
        m.update({"symbol": 0, "description": 1, "quantity": 2,
                  "cost_basis": 3, "market_value": 4, "asset_type": 5})
        return m

    def test_map_columns_accepts_a_valid_response(self):
        body = _fake_anthropic_response(self._valid_mapping())
        mapping, error = ai_parse.map_columns(self.HEADER, "fake-key", client=body)
        self.assertEqual(error, "")
        self.assertEqual(mapping["symbol"], 0)
        self.assertEqual(mapping["quantity"], 2)
        self.assertEqual(mapping["reinvest"], None)  # not present in this header, correctly null

    def test_map_columns_strips_a_markdown_fence(self):
        fenced = "```json\n" + json.dumps(self._valid_mapping()) + "\n```"
        body = _fake_anthropic_response(fenced)
        mapping, error = ai_parse.map_columns(self.HEADER, "fake-key", client=body)
        self.assertEqual(error, "")
        self.assertEqual(mapping["symbol"], 0)

    def test_map_columns_rejects_missing_required_field(self):
        m = self._valid_mapping()
        m["symbol"] = None  # required field left unmapped
        body = _fake_anthropic_response(m)
        mapping, error = ai_parse.map_columns(self.HEADER, "fake-key", client=body)
        self.assertIsNone(mapping)
        self.assertIn("symbol", error)

    def test_map_columns_rejects_out_of_range_index(self):
        m = self._valid_mapping()
        m["symbol"] = 99  # header only has 6 columns
        body = _fake_anthropic_response(m)
        mapping, error = ai_parse.map_columns(self.HEADER, "fake-key", client=body)
        self.assertIsNone(mapping)
        self.assertIn("symbol", error)

    def test_map_columns_rejects_unparseable_json(self):
        body = _fake_anthropic_response("this is not json at all")
        mapping, error = ai_parse.map_columns(self.HEADER, "fake-key", client=body)
        self.assertIsNone(mapping)
        self.assertTrue(error)

    def test_guess_header_row_skips_title_and_blank_lines(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "weird.csv")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('"Export as of 09/24/2026"\n\nAccount 123\n')
                fh.write("Ticker,Name,Shares,Basis,Value,Type\n")
                fh.write("XYZ,Xyz Corp,10,100,120,Equity\n")
            self.assertEqual(ai_parse.guess_header_row(path), self.HEADER)

    def test_parse_with_mapping_matches_strict_parser_on_equivalent_data(self):
        mapping = self._valid_mapping()
        with tempfile.TemporaryDirectory() as d:
            weird_path = os.path.join(d, "weird.csv")
            with open(weird_path, "w", encoding="utf-8") as fh:
                fh.write('"Export as of 09/24/2026"\n\nMy Brokerage Account\n')
                fh.write("Ticker,Name,Shares,Basis,Value,Type\n")
                fh.write("XYZ,Xyz Corp,10,1000,1200,Equity\n")
                fh.write("Cash,--,--,--,300,Cash\n")
                fh.write("Account Total,,,1000,1500,\n")
            meta, positions, totals = ai_parse.parse_with_mapping(weird_path, mapping, self.HEADER)

        self.assertEqual(meta["snapshot_date"], "2026-09-24")
        self.assertEqual(len(positions), 1)
        p = positions[0]
        self.assertEqual(p["symbol"], "XYZ")
        self.assertEqual(p["quantity"], 10.0)
        self.assertEqual(p["cost_basis"], 1000.0)
        self.assertEqual(p["market_value"], 1200.0)
        self.assertEqual(totals["My Brokerage Account"]["cash_value"], 300.0)


class ParseCsvSmartTests(unittest.TestCase):
    def test_strict_success_never_touches_the_ai_fallback(self):
        with unittest.mock.patch("ai_parse.map_columns") as mock_map:
            meta, rows, totals = portfolio.parse_csv_smart(FIXTURE, api_key="unused-key")
        mock_map.assert_not_called()
        self.assertEqual(meta["snapshot_date"], "2026-01-15")

    def test_no_api_key_reraises_the_strict_error_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            bad_path = os.path.join(d, "bad.csv")
            with open(bad_path, "w", encoding="utf-8") as fh:
                fh.write("not,a,real,export\n")
            with self.assertRaises(SystemExit):
                portfolio.parse_csv_smart(bad_path, api_key=None)

    def test_falls_back_to_ai_only_when_strict_parser_fails(self):
        header = ["Ticker", "Name", "Shares", "Basis", "Value", "Type"]
        mapping = {f: None for f in ai_parse.ALL_FIELDS}
        mapping.update({"symbol": 0, "quantity": 2, "cost_basis": 3, "market_value": 4})
        with tempfile.TemporaryDirectory() as d:
            weird_path = os.path.join(d, "weird.csv")
            with open(weird_path, "w", encoding="utf-8") as fh:
                fh.write('"Export as of 09/24/2026"\n\nAcct\n')
                fh.write("Ticker,Name,Shares,Basis,Value,Type\n")
                fh.write("XYZ,Xyz Corp,10,1000,1200,Equity\n")

            with unittest.mock.patch("ai_parse.guess_header_row", return_value=header), \
                 unittest.mock.patch("ai_parse.map_columns", return_value=(mapping, "")) as mock_map:
                meta, positions, totals = portfolio.parse_csv_smart(weird_path, api_key="fake-key")

        mock_map.assert_called_once()
        self.assertEqual(positions[0]["symbol"], "XYZ")


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _FakeStream:
    def __init__(self, texts, message):
        self._texts, self._message = texts, message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(_Obj(type="text", text=t) for t in self._texts)

    def get_final_message(self):
        return self._message


class _FakeClient:
    """Stands in for anthropic.Anthropic: each messages.stream() call plays
    the next scripted turn and records what it was sent."""

    def __init__(self, turns):
        self._turns = list(turns)
        self.calls = []
        self.messages = self

    def stream(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self._turns.pop(0)


class AdvisorTests(TempDBMixin, unittest.TestCase):
    def _contexts(self):
        conn = portfolio.connect(self.db)
        portfolio.import_csv(conn, FIXTURE, self.user_id)
        positions = [dict(r) for r in conn.execute(
            "SELECT * FROM positions WHERE user_id = ?", (self.user_id,))]
        cash = {r["account"]: r["cash_value"] for r in conn.execute(
            "SELECT account, cash_value FROM account_totals WHERE user_id = ?", (self.user_id,))}
        conn.close()
        total = sum(p["market_value"] for p in positions) + sum(cash.values())
        ctxs = [{"pos": p, "quote": {}, "stats": {}, "info": {}, "port_value": total,
                 "acct_value": None} for p in positions]
        return ctxs, cash

    def test_portfolio_summary_sends_weights_not_dollars_or_account_names(self):
        ctxs, cash = self._contexts()
        text = advisor.portfolio_summary(ctxs, cash)
        for sym in ("AAA", "BBB", "CCC"):
            self.assertIn(sym, text)
        self.assertNotIn("$", text)
        self.assertNotIn("Individual", text)
        self.assertNotIn("...111", text)
        for dollars in ("1200", "1,200", "1600", "1,600"):   # fixture market values
            self.assertNotIn(dollars, text)
        self.assertIn("% of portfolio", text)

    def test_portfolio_summary_empty_account(self):
        self.assertIn("No holdings yet", advisor.portfolio_summary([], {}))

    def test_profile_round_trip_and_isolation(self):
        conn = portfolio.connect(self.db)
        other = auth.create_user(conn, "other", "pw")
        advisor.save_profile(conn, self.user_id, {"goal": "retire at 60", "risk_tolerance": "moderate"})
        advisor.save_profile(conn, self.user_id, {"time_horizon_years": 25, "goal": None})
        p = advisor.get_profile(conn, self.user_id)
        self.assertEqual(p["goal"], "retire at 60")        # None left it unchanged
        self.assertEqual(p["time_horizon_years"], 25)
        self.assertIsNone(advisor.get_profile(conn, other)["goal"])
        advisor.save_profile(conn, self.user_id, {"goal": None}, replace=True)
        self.assertIsNone(advisor.get_profile(conn, self.user_id)["risk_tolerance"])
        conn.close()

    def test_validate_profile_input(self):
        ok, err = advisor.validate_profile_input(
            {"goal": ["Buy a home", "Retirement"], "time_horizon_years": 20, "target_return_pct": 7,
             "risk_tolerance": "aggressive", "experience": None, "age_range": "25-34",
             "preferences": []})
        self.assertEqual(err, "")
        # pick-any answers are stored in the options' own order; an empty list is "no change"
        self.assertEqual(ok, {"goal": "Retirement; Buy a home", "time_horizon_years": 20,
                              "target_return_pct": 7.0, "risk_tolerance": "aggressive",
                              "age_range": "25-34"})
        for bad in ({"risk_tolerance": "yolo"}, {"time_horizon_years": 0},
                    {"target_return_pct": 900}, {"surprise": "x"}, "not a dict",
                    {"goal": "retire at 60"}, {"goal": ["Get rich quick"]},
                    {"notes": "the user's own field"}):
            fields, err = advisor.validate_profile_input(bad)
            self.assertIsNone(fields, bad)
            self.assertTrue(err)

    def test_system_prompt_asks_for_missing_profile_fields(self):
        empty = {f: None for f in advisor.PROFILE_FIELDS}
        self.assertIn("Still unknown", advisor.system_prompt(empty, "No holdings yet"))
        full = {f: None for f in advisor.PROFILE_FIELDS}
        full.update({"goal": "Retirement", "time_horizon_years": 30, "risk_tolerance": "moderate",
                     "drawdown_reaction": "Hold and wait", "experience": "new",
                     "age_range": "35-44", "income_stability": "Very stable",
                     "emergency_fund": "3-6 months"})
        prompt = advisor.system_prompt(full, "No holdings yet")
        self.assertNotIn("Still unknown", prompt)
        self.assertIn("Retirement", prompt)
        self.assertIn("None yet", prompt)  # no notes from earlier conversations
        self.assertIn("- saving for a boat",
                      advisor.system_prompt(full, "No holdings yet", "- saving for a boat"))

    def test_stream_reply_saves_profile_then_continues(self):
        tool_block = _Obj(type="tool_use", id="tu_1", name="update_investor_profile",
                          input={**{f: None for f in advisor.TOOL_PROFILE_FIELDS},
                                 "goal": ["Retirement"], "risk_tolerance": "moderate"})
        client = _FakeClient([
            _FakeStream(["Got it. "], _Obj(stop_reason="tool_use", content=[tool_block])),
            _FakeStream(["How long until you retire?"],
                        _Obj(stop_reason="end_turn", content=[_Obj(type="text", text="...")])),
        ])
        saved = []
        history = [{"role": "user", "content": "I want to retire at 60, moderate risk."}]
        text = "".join(advisor.stream_reply(client, history, "sys", saved.append))
        self.assertEqual(text, "Got it. How long until you retire?")
        self.assertEqual(saved, [{"goal": "Retirement", "risk_tolerance": "moderate"}])
        self.assertEqual(len(client.calls), 2)
        # second call carries the assistant tool_use turn and its tool_result
        self.assertEqual(client.calls[1]["messages"][-1]["content"][0]["tool_use_id"], "tu_1")

    def test_stream_reply_saves_memory(self):
        mem_block = _Obj(type="tool_use", id="tu_m", name="save_memory",
                         input={"notes": "- house ~2029\n- avoid crypto"})
        too_long = _Obj(type="tool_use", id="tu_x", name="save_memory",
                        input={"notes": "x" * (advisor.MEMORY_MAX_CHARS + 1)})
        client = _FakeClient([
            _FakeStream(["Noted."], _Obj(stop_reason="tool_use", content=[mem_block, too_long])),
            _FakeStream([], _Obj(stop_reason="end_turn", content=[])),
        ])
        notes, profile = [], []
        text = "".join(advisor.stream_reply(client, [{"role": "user", "content": "x"}], "sys",
                                            profile.append, notes.append))
        self.assertEqual(text, "Noted.")
        self.assertEqual(notes, ["- house ~2029\n- avoid crypto"])  # the too-long one isn't saved
        self.assertEqual(profile, [])
        results = client.calls[1]["messages"][-1]["content"]
        self.assertFalse(results[0].get("is_error"))
        self.assertTrue(results[1]["is_error"])
        self.assertEqual({t["name"] for t in client.calls[0]["tools"]},
                         {"update_investor_profile", "save_memory"})

    def test_memory_round_trip_is_separate_from_profile(self):
        conn = portfolio.connect(self.db)
        other = auth.create_user(conn, "other", "pw")
        self.assertEqual(advisor.get_memory(conn, self.user_id), "")
        advisor.save_memory(conn, self.user_id, "- house ~2029")      # before any profile row
        advisor.save_profile(conn, self.user_id, {"age_range": "25-34"}, replace=True)
        self.assertEqual(advisor.get_memory(conn, self.user_id), "- house ~2029")
        self.assertEqual(advisor.get_profile(conn, self.user_id)["age_range"], "25-34")
        self.assertNotIn("ai_memory", advisor.get_profile(conn, self.user_id))  # never shown
        self.assertEqual(advisor.get_memory(conn, other), "")
        conn.close()

    def test_profile_columns_added_to_an_existing_database(self):
        import sqlite3
        old = os.path.join(os.path.dirname(self.db), "old.db")
        c = sqlite3.connect(old)
        c.execute("CREATE TABLE investor_profiles (user_id INTEGER PRIMARY KEY, goal TEXT, "
                  "time_horizon_years INTEGER, target_return_pct REAL, risk_tolerance TEXT, "
                  "experience TEXT, notes TEXT, updated_at TEXT)")
        c.execute("INSERT INTO investor_profiles (user_id, goal) VALUES (1, 'retire at 60')")
        c.commit()
        c.close()
        conn = portfolio.connect(old)
        self.assertEqual(advisor.get_profile(conn, 1)["goal"], "retire at 60")
        advisor.save_memory(conn, 1, "- note")
        self.assertEqual(advisor.get_memory(conn, 1), "- note")
        conn.close()

    def test_ui_script_survives_the_html_sanitizer(self):
        # Streamlit's st.html sanitizer drops a whole script whose text looks
        # like it contains a tag (e.g. an SVG string), and then nothing runs.
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "ui_enhancements.js")
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(re.findall(r"<[/\w!]", fh.read()), [])

    def test_stream_reply_refusal(self):
        client = _FakeClient([_FakeStream([], _Obj(stop_reason="refusal", content=[]))])
        text = "".join(advisor.stream_reply(client, [{"role": "user", "content": "x"}],
                                            "sys", lambda f: None))
        self.assertEqual(text, advisor.REFUSAL_TEXT)


class AdvisorModeTests(TempDBMixin, unittest.TestCase):
    """self.user_id ("testuser") is the advisor in these tests."""

    def setUp(self):
        super().setUp()
        self.conn = portfolio.connect(self.db)
        auth.set_advisor(self.conn, "testuser", True)

    def tearDown(self):
        self.conn.close()
        super().tearDown()

    def test_existing_accounts_are_not_advisors(self):
        other = auth.create_user(self.conn, "plain", "pw")
        self.conn.execute("UPDATE users SET is_advisor = NULL WHERE id = ?", (other,))
        self.assertFalse(auth.is_advisor(self.conn, other))
        self.assertTrue(auth.is_advisor(self.conn, self.user_id))

    def test_client_without_password_cannot_log_in_until_given_one(self):
        cid = auth.create_client(self.conn, self.user_id, "jsmith")
        self.assertEqual(auth.list_clients(self.conn, self.user_id), [(cid, "jsmith")])
        self.assertIsNone(auth.verify_login(self.conn, "jsmith", ""))
        auth.set_password(self.conn, "jsmith", "clientpass1")
        self.assertEqual(auth.verify_login(self.conn, "jsmith", "clientpass1"), cid)

    def test_can_view_rules(self):
        client = auth.create_client(self.conn, self.user_id, "c1", "pw12345678")
        stranger = auth.create_user(self.conn, "stranger", "pw")
        other_adv = auth.create_user(self.conn, "adv2", "pw")
        auth.set_advisor(self.conn, "adv2", True)
        other_client = auth.create_client(self.conn, other_adv, "c2")

        self.assertTrue(auth.can_view(self.conn, self.user_id, self.user_id))
        self.assertTrue(auth.can_view(self.conn, self.user_id, client))
        self.assertFalse(auth.can_view(self.conn, self.user_id, stranger))
        self.assertFalse(auth.can_view(self.conn, self.user_id, other_client))  # someone else's client
        self.assertTrue(auth.can_view(self.conn, client, client))
        self.assertFalse(auth.can_view(self.conn, client, self.user_id))         # client can't see advisor
        self.assertFalse(auth.can_view(self.conn, stranger, client))

    def test_client_import_switch_is_off_by_default_and_only_the_advisor_sets_it(self):
        client = auth.create_client(self.conn, self.user_id, "c1")
        self.assertFalse(advising.client_can_import(self.conn, client))
        self.assertTrue(advising.set_client_can_import(self.conn, self.user_id, client, True))
        self.assertTrue(advising.client_can_import(self.conn, client))
        other_adv = auth.create_user(self.conn, "adv2", "pw")
        self.assertFalse(advising.set_client_can_import(self.conn, other_adv, client, False))
        self.assertTrue(advising.client_can_import(self.conn, client))   # not their client
        advising.set_client_can_import(self.conn, self.user_id, client, False)
        self.assertFalse(advising.client_can_import(self.conn, client))
        self.assertFalse(advising.client_can_import(self.conn, self.user_id))  # not a client

    def test_can_view_stops_when_advisor_rights_are_removed(self):
        client = auth.create_client(self.conn, self.user_id, "c1")
        auth.set_advisor(self.conn, "testuser", False)
        self.assertFalse(auth.can_view(self.conn, self.user_id, client))

    def test_only_advisors_create_clients_and_names_are_validated(self):
        plain = auth.create_user(self.conn, "plain", "pw")
        with self.assertRaises(ValueError):
            auth.create_client(self.conn, plain, "c1")
        with self.assertRaises(ValueError):
            auth.create_client(self.conn, self.user_id, "bad name; drop")
        with self.assertRaises(portfolio.DBError):
            auth.create_client(self.conn, self.user_id, "testuser")   # taken


class BulkCreateTests(TempDBMixin, unittest.TestCase):
    def test_parse_user_list_skips_blanks_and_comments(self):
        text = "alice,pw1\n\n# a comment\nbob\n  carol , pw3  \n"
        self.assertEqual(manage_users.parse_user_list(text), [
            ("alice", "pw1"), ("bob", None), ("carol", "pw3"),
        ])

    def test_bulk_create_generates_password_when_omitted_and_skips_existing(self):
        conn = portfolio.connect(self.db)
        path = os.path.join(self.dir, "users.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("testuser\nnewperson,chosenpw\n")  # testuser already exists (TempDBMixin)

        args = argparse.Namespace(db=self.db, file=path)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = manage_users.cmd_bulk_create(args)
        self.assertEqual(rc, 0)
        self.assertIn("already exists", out.getvalue())

        # newperson created with the chosen password (not regenerated)
        self.assertEqual(auth.verify_login(conn, "newperson", "chosenpw"), auth.get_user_id(conn, "newperson"))
        # testuser's original password is untouched
        self.assertEqual(auth.verify_login(conn, "testuser", "testpass"), self.user_id)


class PlanMathTests(unittest.TestCase):
    TODAY = date(2026, 9, 29)

    def test_future_value(self):
        self.assertAlmostEqual(plans.future_value(1000, 100, 0, 12), 2200)            # no growth
        self.assertAlmostEqual(plans.future_value(10000, 0, 6, 12), 10600, places=6)  # one year at 6%
        self.assertEqual(plans.future_value(500, 50, 6, -3), 500)                     # no negative time

    def test_required_monthly_reaches_the_target(self):
        need = plans.required_monthly(20000, 500000, 6, 360)
        self.assertAlmostEqual(plans.future_value(20000, need, 6, 360), 500000, places=4)
        self.assertEqual(plans.required_monthly(500000, 100000, 6, 12), 0.0)  # already enough
        self.assertIsNone(plans.required_monthly(1000, 5000, 6, 0))          # no time left

    def test_months_until_and_add_months(self):
        self.assertEqual(plans.months_until("2027-09-29", self.TODAY), 12)
        self.assertEqual(plans.months_until("2027-09-28", self.TODAY), 11)    # a day short
        self.assertEqual(plans.months_until("2026-01-01", self.TODAY), -9)
        self.assertEqual(plans.add_months(date(2026, 1, 31), 1), date(2026, 2, 28))
        self.assertEqual(plans.add_months(date(2026, 11, 15), 3), date(2027, 2, 15))

    def _plan(self, target, when, monthly=0):
        return {"target_amount": target, "target_date": when, "monthly_contribution": monthly}

    def test_progress_statuses(self):
        today = self.TODAY
        status = lambda plan, value: plans.progress(plan, value, today=today)["status"]  # noqa: E731
        self.assertEqual(status(self._plan(10000, "2030-01-01"), 12000), "reached")
        self.assertEqual(status(self._plan(10000, "2026-01-01"), 5000), "past_date")
        # 10 years at 6% turns 10k into ~17.9k: 15k is on track
        self.assertEqual(status(self._plan(15000, "2036-09-29"), 10000), "on_track")
        # ~20.7k at 8% but ~17.9k at 6%: 20k only at the optimistic end
        self.assertEqual(status(self._plan(20000, "2036-09-29"), 10000), "within_reach")
        self.assertEqual(status(self._plan(50000, "2036-09-29"), 10000), "behind")
        p = plans.progress(self._plan(50000, "2036-09-29"), 10000, today=today)
        self.assertLess(p["projected_low"], p["projected"])
        self.assertLess(p["projected"], p["projected_high"])
        self.assertAlmostEqual(p["pct_of_target"], 20.0)
        self.assertGreater(p["needed_monthly"], 0)

    def test_projection_series(self):
        rows = plans.projection_series(1000, 100, 24, today=self.TODAY)
        self.assertEqual(len(rows), 25)
        self.assertEqual(rows[0]["date"], "2026-09-29")
        self.assertEqual(rows[0]["mid"], 1000)
        self.assertEqual(rows[-1]["date"], "2028-09-29")
        long = plans.projection_series(1000, 100, 600, today=self.TODAY)
        self.assertLessEqual(len(long), 242)                                    # sampled
        self.assertEqual(long[-1]["date"], plans.add_months(self.TODAY, 600).isoformat())


class LearnTests(unittest.TestCase):
    def test_readiness_reads_the_profile(self):
        items = {i["key"]: i["state"] for i in learn.readiness({
            "emergency_fund": "None", "high_interest_debt": "Some",
            "employer_match": "Yes, and I get the full match", "withdrawal_needs": "A large amount"})}
        self.assertEqual(items, {"emergency_fund": learn.STOP, "high_interest_debt": learn.CAUTION,
                                 "employer_match": learn.GOOD, "withdrawal_needs": learn.CAUTION})
        self.assertEqual(learn.readiness_summary(learn.readiness({
            "emergency_fund": "None"})), "Start here first")
        ready = learn.readiness({"emergency_fund": "3-6 months", "high_interest_debt": "None",
                                 "employer_match": "No match or no plan"})
        self.assertEqual(learn.readiness_summary(ready), "Ready to start")
        self.assertEqual(learn.readiness_summary(learn.readiness({})), "Answer a few questions")

    def test_starter_mix_follows_horizon_and_risk(self):
        self.assertIsNone(learn.starter_mix({}))
        long = learn.starter_mix({"time_horizon_years": 30, "risk_tolerance": "moderate"})
        short = learn.starter_mix({"time_horizon_years": 2, "risk_tolerance": "moderate"})
        self.assertGreater(long["stocks_pct"], short["stocks_pct"])
        self.assertTrue(short["short_horizon"])
        careful = learn.starter_mix({"time_horizon_years": 30, "risk_tolerance": "conservative",
                                     "drawdown_reaction": "Sell everything"})
        self.assertLess(careful["stocks_pct"], long["stocks_pct"])
        for mix in (long, short, careful):
            self.assertEqual(sum(mix["weights"].values()), 100)
            self.assertEqual(mix["stocks_pct"] % 5, 0)
            self.assertTrue(mix["reasons"])
        self.assertEqual(learn.starter_mix({"time_horizon_years": 2}, horizon_years=25)["horizon_years"], 25)

    def test_target_date_year(self):
        today = date(2026, 9, 29)
        self.assertEqual(learn.target_date_year({"goal_type": "Retirement", "target_date": "2053-06-01"},
                                                None, today), 2055)
        self.assertEqual(learn.target_date_year(None, "25-34", today), 2060)   # 2026 + 35 = 2061
        self.assertIsNone(learn.target_date_year(None, "65 or older", today))

    def test_fee_cost_is_positive_and_grows_with_time(self):
        short, long = (learn.fee_cost(200, y, 6, 0.05, 1.0) for y in (10, 30))
        self.assertGreater(short, 0)
        self.assertGreater(long, short * 3)
        self.assertAlmostEqual(learn.grow_monthly(100, 1, 0), 1200)

    def test_simulate_monthly_buys_and_value(self):
        # one fund that doubles over the period: two buys of 100
        prices = {"AAA": [("2026-01-05", 10.0), ("2026-01-20", 12.0), ("2026-02-02", 20.0)]}
        rows = learn.simulate(prices, {"AAA": 1}, monthly=100)
        self.assertEqual([r["money_in"] for r in rows], [100, 100, 200])   # once per month
        self.assertAlmostEqual(rows[-1]["value"], 10 * 20 + 100)            # 10 units + new 100
        self.assertAlmostEqual(rows[-1]["nav"], 2.0)                        # price doubled
        # two funds, only shared days count
        both = learn.simulate({"A": [("d1", 1.0), ("d2", 1.0)], "B": [("d2", 2.0)]},
                              {"A": 50, "B": 50}, monthly=0, initial=100)
        self.assertEqual([r["date"] for r in both], ["d2"])
        self.assertEqual(learn.simulate(prices, {}, monthly=100), [])

    def test_max_drawdown_ignores_contributions(self):
        prices = {"A": [("2026-01-02", 10.0), ("2026-02-02", 5.0), ("2026-03-02", 10.0)]}
        rows = learn.simulate(prices, {"A": 1}, monthly=1000)
        self.assertAlmostEqual(learn.max_drawdown(rows), -50.0)             # the price halved
        self.assertIsNone(learn.max_drawdown(rows[:1]))


class PlanStorageTests(TempDBMixin, unittest.TestCase):
    def test_save_merges_and_records_who_saved(self):
        conn = portfolio.connect(self.db)
        self.assertIsNone(plans.get_plan(conn, self.user_id))
        plans.save_plan(conn, self.user_id, {"target_alloc": {"Equity": 70, "Cash": 0}}, set_by=self.user_id)
        plan = plans.save_plan(conn, self.user_id, {"goal_type": "Retirement", "target_amount": 900000,
                                                    "target_date": "2055-01-01"}, set_by=99)
        self.assertEqual(plan["target_alloc"], {"Equity": 70.0})   # kept, and zero targets dropped
        self.assertEqual(plan["set_by"], 99)
        self.assertTrue(plans.has_goal(plan))
        plan = plans.save_plan(conn, self.user_id, {"target_amount": None}, set_by=self.user_id)
        self.assertFalse(plans.has_goal(plan))                       # None clears a field
        conn.close()

    def test_contributions_are_per_user(self):
        conn = portfolio.connect(self.db)
        other = auth.create_user(conn, "other", "pw")
        plans.add_contribution(conn, self.user_id, "2026-09-02", 500, " paycheck ")
        plans.add_contribution(conn, self.user_id, "2026-09-20", -200)
        plans.add_contribution(conn, self.user_id, "2026-08-31", 300)
        plans.add_contribution(conn, other, "2026-09-05", 1000)
        self.assertEqual(plans.month_total(conn, self.user_id, 2026, 9), 300.0)
        rows = plans.list_contributions(conn, self.user_id)
        self.assertEqual([r["date"] for r in rows], ["2026-09-20", "2026-09-02", "2026-08-31"])
        self.assertEqual(rows[1]["note"], "paycheck")
        plans.delete_contribution(conn, other, rows[0]["id"])       # someone else's id: no effect
        self.assertEqual(len(plans.list_contributions(conn, self.user_id)), 3)
        plans.delete_contribution(conn, self.user_id, rows[0]["id"])
        self.assertEqual(plans.month_total(conn, self.user_id, 2026, 9), 500.0)
        conn.close()

    def test_money_in_history_adds_up(self):
        conn = portfolio.connect(self.db)
        portfolio.import_csv(conn, FIXTURE, self.user_id)
        hist = plans.money_in_history(conn, self.user_id)
        self.assertEqual(len(hist), 1)
        h = hist[0]
        mv = conn.execute("SELECT SUM(market_value) AS s FROM positions WHERE user_id = ?",
                          (self.user_id,)).fetchone()["s"]
        cash = conn.execute("SELECT SUM(cash_value) AS s FROM account_totals WHERE user_id = ?",
                            (self.user_id,)).fetchone()["s"]
        self.assertAlmostEqual(h["value"], mv + cash)
        self.assertAlmostEqual(h["money_in"] + h["growth"], h["value"])
        conn.close()


class PrefsTests(TempDBMixin, unittest.TestCase):
    def test_round_trip_and_legacy_file_carries_over(self):
        conn = portfolio.connect(self.db)
        self.assertEqual(prefs.load(conn, self.user_id), {})
        legacy = os.path.join(os.path.dirname(self.db), "old_prefs.json")
        with open(legacy, "w", encoding="utf-8") as fh:
            json.dump({"hide_amounts": True, "rules": {"day_change_pct": 3}}, fh)
        other = auth.create_user(conn, "other", "pw")
        self.assertEqual(prefs.load(conn, other, legacy)["hide_amounts"], True)   # imported once
        os.remove(legacy)
        self.assertEqual(prefs.load(conn, other, legacy)["rules"], {"day_change_pct": 3})  # now in the db
        prefs.save(conn, other, {"columns": ["symbol"]})
        self.assertEqual(prefs.load(conn, other), {"columns": ["symbol"]})
        self.assertEqual(prefs.load(conn, self.user_id), {})                     # per user
        conn.close()


class AccountLabelTests(TempDBMixin, unittest.TestCase):
    def test_set_display_and_clear(self):
        conn = portfolio.connect(self.db)
        accounts.set_label(conn, self.user_id, "Individual ...111", "  Roth IRA ")
        names = accounts.labels(conn, self.user_id)
        self.assertEqual(names, {"Individual ...111": "Roth IRA"})              # trimmed
        self.assertEqual(accounts.display("Individual ...111", names), "Roth IRA")
        self.assertEqual(accounts.display("Individual ...222", names), "Individual ...222")
        accounts.set_label(conn, self.user_id, "Individual ...111", "New name")   # replaces
        self.assertEqual(accounts.labels(conn, self.user_id), {"Individual ...111": "New name"})
        accounts.set_label(conn, self.user_id, "Individual ...111", "  ")         # blank clears
        self.assertEqual(accounts.labels(conn, self.user_id), {})
        conn.close()

    def test_labels_are_per_user(self):
        conn = portfolio.connect(self.db)
        other = auth.create_user(conn, "someone_else", "testpass")
        accounts.set_label(conn, self.user_id, "Individual ...111", "Mine")
        self.assertEqual(accounts.labels(conn, other), {})
        conn.close()

    def test_clash_catches_a_shared_display_name(self):
        accts = ["Individual ...111", "Individual ...222"]
        names = {"Individual ...111": "Brokerage"}
        self.assertEqual(accounts.clash("Individual ...222", "brokerage", accts, names),
                         "Individual ...111")                                  # case-insensitive
        self.assertIsNone(accounts.clash("Individual ...111", "Brokerage", accts, names))  # itself
        self.assertEqual(accounts.clash("Individual ...111", "Individual ...222", accts, {}),
                         "Individual ...222")                                  # another's broker name
        self.assertIsNone(accounts.clash("Individual ...222", "", accts, names))


class WatchlistTests(TempDBMixin, unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(watchlist.normalize("  nvda "), "NVDA")
        self.assertEqual(watchlist.normalize("brk.b"), "BRK.B")
        self.assertIsNone(watchlist.normalize(""))
        self.assertIsNone(watchlist.normalize("not a ticker"))       # spaces aren't valid
        self.assertIsNone(watchlist.normalize("way-too-long-for-a-ticker"))

    def test_add_list_remove_is_idempotent(self):
        conn = portfolio.connect(self.db)
        self.assertEqual(watchlist.add(conn, self.user_id, " nvda "), "NVDA")
        self.assertEqual(watchlist.add(conn, self.user_id, "NVDA"), "NVDA")        # re-add is a no-op, not a dupe
        self.assertIsNone(watchlist.add(conn, self.user_id, "not valid"))
        self.assertEqual(watchlist.list_tickers(conn, self.user_id), ["NVDA"])
        watchlist.remove(conn, self.user_id, "NVDA")
        self.assertEqual(watchlist.list_tickers(conn, self.user_id), [])
        conn.close()

    def test_all_sync_tickers_merges_held_and_watchlist(self):
        conn = portfolio.connect(self.db)
        portfolio.import_csv(conn, FIXTURE, self.user_id)
        watchlist.add(conn, self.user_id, "NVDA")
        held = {r["symbol"] for r in conn.execute("SELECT DISTINCT symbol FROM positions")}
        merged = watchlist.all_sync_tickers(conn)
        self.assertEqual(set(merged), held | {"NVDA"})
        self.assertEqual(merged, sorted(merged))                    # sorted, no dupes
        conn.close()


class NewsTests(TempDBMixin, unittest.TestCase):
    """No network calls - fetch_company_news is never exercised here, only
    the storage/caching layer around it."""

    ARTICLES = [
        {"id": 101, "headline": "Widgets up 5%", "summary": "A summary.", "source": "Reuters",
         "url": "https://example.com/101", "datetime": 1_700_000_000},
        {"id": 102, "headline": "CEO speaks", "summary": "Another summary.", "source": "Bloomberg",
         "url": "https://example.com/102", "datetime": 1_700_003_600},
    ]

    def test_upsert_is_idempotent_and_skips_incomplete_articles(self):
        conn = portfolio.connect(self.db)
        n = news.upsert_news(conn, "AAPL", self.ARTICLES)
        self.assertEqual(n, 2)
        n_again = news.upsert_news(conn, "AAPL", self.ARTICLES)     # re-sync, same articles
        self.assertEqual(n_again, 0)                                # INSERT OR IGNORE, no dupes
        # missing id or headline -> silently skipped, not an error
        n_bad = news.upsert_news(conn, "AAPL", [{"headline": "no id"}, {"id": 999}])
        self.assertEqual(n_bad, 0)
        rows = news.latest_news(conn, "AAPL")
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["id"] for r in rows}, {101, 102})
        conn.close()

    def test_published_at_converted_from_epoch(self):
        conn = portfolio.connect(self.db)
        news.upsert_news(conn, "AAPL", self.ARTICLES)
        rows = {r["id"]: r for r in news.latest_news(conn, "AAPL")}
        self.assertEqual(rows[101]["published_at"], "2023-11-14T22:13:20Z")
        conn.close()

    def test_needs_refresh_true_when_empty_false_after_fetch(self):
        conn = portfolio.connect(self.db)
        self.assertTrue(news.needs_refresh(conn, "AAPL"))           # nothing cached yet
        news.upsert_news(conn, "AAPL", self.ARTICLES)
        self.assertFalse(news.needs_refresh(conn, "AAPL"))          # just fetched, still fresh
        self.assertTrue(news.needs_refresh(conn, "AAPL", max_age_hours=0))  # force-stale
        self.assertTrue(news.needs_refresh(conn, "MSFT"))           # different ticker, never cached
        conn.close()

    def test_sync_ticker_skips_network_call_when_fresh(self):
        # sync_ticker's network path isn't exercised (no real fetch_company_news
        # call happens if the cache is already fresh) - this proves the guard
        # itself, i.e. that a fresh cache short-circuits before ever calling
        # out, by checking it returns (0, "") with no key required to work.
        conn = portfolio.connect(self.db)
        news.upsert_news(conn, "AAPL", self.ARTICLES)
        n, err = news.sync_ticker(conn, "AAPL", token="not-a-real-key")
        self.assertEqual((n, err), (0, ""))
        conn.close()


class ClientsOverviewTests(TempDBMixin, unittest.TestCase):
    def test_account_summary_matches_fixture(self):
        conn = portfolio.connect(self.db)
        portfolio.import_csv(conn, FIXTURE, self.user_id)
        advisor.save_profile(conn, self.user_id, {"goal": "retire", "risk_tolerance": "moderate"})
        s = overview.account_summary(conn, self.user_id, quotes={})
        # fixture: AAA 1200 + BBB 450 + CCC 1600 holdings, 100 + 50 cash
        self.assertEqual(s["portfolio_value"], 3400.0)
        self.assertEqual(s["n_positions"], 3)
        self.assertEqual(s["snapshot_date"], "2026-01-15")
        self.assertIsNotNone(s["imported_at"])
        # cost 3500 vs value 3250 -> -7.14%
        self.assertAlmostEqual(s["gain_pct"], -7.14, places=2)
        # default rules: CCC day move -6.5% (>5) and CCC total -20% is not > 20 -> 1 alert
        self.assertEqual(s["n_alerts"], 1)
        self.assertEqual((s["profile_answered"], s["profile_total"]),
                         (2, len(advisor.REQUIRED_PROFILE_FIELDS)))
        conn.close()

    def test_account_summary_empty_account(self):
        conn = portfolio.connect(self.db)
        s = overview.account_summary(conn, self.user_id, quotes={})
        self.assertFalse(s["has_data"])
        self.assertIsNone(s["portfolio_value"])
        self.assertEqual(s["profile_answered"], 0)
        conn.close()


class AdvisingTests(TempDBMixin, unittest.TestCase):
    def _pair(self, conn):
        auth.set_advisor(conn, "testuser", True)
        return auth.create_client(conn, self.user_id, "client1")

    def test_notes_private_and_next_steps(self):
        conn = portfolio.connect(self.db)
        client = self._pair(conn)
        self.assertEqual(advising.advisor_of(conn, client), self.user_id)
        self.assertIsNone(advising.advisor_of(conn, self.user_id))
        advising.add_note(conn, client, self.user_id, "Review", "Went over the plan", "2026-06-01")
        advising.add_note(conn, client, self.user_id, "Next step", "Raise monthly to $600", "2026-06-01")
        advising.add_note(conn, client, self.user_id, "Note", "Nervous about markets", "2026-06-02",
                          private=True)
        with self.assertRaises(ValueError):
            advising.add_note(conn, client, self.user_id, "Note", "   ", "2026-06-02")
        with self.assertRaises(ValueError):
            advising.add_note(conn, client, self.user_id, "Gossip", "x", "2026-06-02")
        seen = advising.list_notes(conn, client, include_private=False)
        self.assertEqual({n["body"] for n in seen}, {"Went over the plan", "Raise monthly to $600"})
        self.assertEqual(len(advising.list_notes(conn, client, include_private=True)), 3)
        step = advising.open_next_steps(seen)[0]
        advising.set_done(conn, self.user_id, step["id"], True)       # wrong client id: no effect
        self.assertEqual(len(advising.open_next_steps(advising.list_notes(conn, client, include_private=False))), 1)
        advising.set_done(conn, client, step["id"], True)
        self.assertEqual(advising.open_next_steps(advising.list_notes(conn, client, include_private=False)), [])
        self.assertEqual(advising.last_review(conn, client), "2026-06-01")
        conn.close()

    def test_review_status(self):
        today = date(2026, 9, 29)
        self.assertEqual(advising.review_status(None, today), ("never", None))
        self.assertEqual(advising.review_status("2026-09-01", today), ("ok", 28))
        self.assertEqual(advising.review_status("2026-05-01", today)[0], "due")

    def test_models_validate_and_replace_by_name(self):
        conn = portfolio.connect(self.db)
        with self.assertRaises(ValueError):
            advising.save_model(conn, self.user_id, "Bad", {"Equity": 50})
        with self.assertRaises(ValueError):
            advising.save_model(conn, self.user_id, " ", {"Equity": 100})
        advising.save_model(conn, self.user_id, "Growth", {"Equity": 80, "Cash": 20, "Fixed Income": 0})
        advising.save_model(conn, self.user_id, "Growth", {"Equity": 90, "Cash": 10})
        models = advising.list_models(conn, self.user_id)
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["target_alloc"], {"Equity": 90.0, "Cash": 10.0})
        self.assertEqual(advising.mix_text(models[0]["target_alloc"]), "Equity 90% · Cash 10%")
        other = auth.create_user(conn, "other", "pw")
        advising.delete_model(conn, other, models[0]["id"])            # not theirs
        self.assertEqual(len(advising.list_models(conn, self.user_id)), 1)
        self.assertEqual(advising.list_models(conn, other), [])
        conn.close()

    def test_drift_and_attention(self):
        self.assertIsNone(advising.max_drift({"Equity": 60}, {}))
        self.assertAlmostEqual(advising.max_drift({"Equity": 70, "Cash": 30},
                                                  {"Equity": 60, "Fixed Income": 20}), 20)
        self.assertEqual(advising.attention(has_data=True, goal_status="on_track", review="ok",
                                            n_alerts=0, drift=2.0, profile_done=True), [])
        reasons = advising.attention(has_data=True, goal_status="behind", review="due", n_alerts=2,
                                     drift=12.4, profile_done=False)
        self.assertEqual(reasons, ["Goal behind", "Review due", "2 alerts", "Drift 12 pts",
                                   "Profile incomplete"])
        self.assertIn("No goal", advising.attention(has_data=False, goal_status=None, review="never",
                                                    n_alerts=0, drift=None, profile_done=True))


class PostgresPrecisionTests(unittest.TestCase):
    """Postgres REAL is 4-byte and loses cents on large amounts, so every
    decimal column must be DOUBLE PRECISION there - new databases via
    schema_pg.sql, older ones converted by _widen_real_columns()."""

    @staticmethod
    def _columns(sql_text):
        out = {}
        for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", sql_text, re.S):
            for line in m.group(2).splitlines():
                parts = line.split("--")[0].split()
                if len(parts) >= 2 and parts[0].isidentifier() and parts[0].upper() != "PRIMARY":
                    out[(m.group(1), parts[0])] = " ".join(parts[1:3]).rstrip(",").upper()
        return out

    def test_every_sqlite_real_column_is_double_precision_on_postgres(self):
        with open(os.path.join(REPO, "schema.sql"), encoding="utf-8") as fh:
            lite = self._columns(fh.read())
        with open(os.path.join(REPO, "schema_pg.sql"), encoding="utf-8") as fh:
            pg = self._columns(fh.read())
        reals = [k for k, t in lite.items() if t.startswith("REAL")]
        self.assertGreater(len(reals), 40)
        for key in reals:
            self.assertTrue(pg[key].startswith("DOUBLE PRECISION"), key)
        self.assertFalse([k for k, t in pg.items() if t.startswith("REAL")])

    def test_older_database_real_columns_are_widened_once_per_table(self):
        executed = []
        reals = [("positions", "cost_basis"), ("positions", "market_value"),
                 ("daily_bars", "close"), ("someone_elses_table", "x")]

        class Col:
            def __init__(self, name):
                self.name = name

        class FakeCursor:
            def __init__(self):
                self.rows, self.description = [], None

            def execute(self, sql, params=None):
                executed.append(sql)
                if "data_type = 'real'" in sql:
                    self.rows = list(reals)
                    self.description = [Col("table_name"), Col("column_name")]
                elif "information_schema.columns WHERE table_name" in sql:
                    # every back-filled column already there except one REAL one
                    self.rows = [(c,) for c in ("live_price_at", "user_id", "is_advisor")
                                 + tuple(n for n, _ in portfolio.PROFILE_EXTRA_COLS)
                                 + ("live_price", "live_market_value", "live_unrealized_gain_pct",
                                    "day_open", "day_high", "day_low", "realized_gain")]
                    self.description = [Col("column_name")]
                else:
                    self.rows, self.description = [], None

            def __iter__(self):
                return iter(self.rows)

            def fetchall(self):
                return list(self.rows)

        class FakeRaw:
            def cursor(self):
                return FakeCursor()

            def commit(self):
                executed.append("COMMIT")

        with contextlib.redirect_stderr(io.StringIO()) as err:
            portfolio._ensure_schema(pgcompat.ConnWrapper(FakeRaw()))
        alters = [q for q in executed if q.startswith('ALTER TABLE "')]
        self.assertEqual(alters, [
            'ALTER TABLE "positions" ALTER COLUMN "cost_basis" TYPE DOUBLE PRECISION, '
            'ALTER COLUMN "market_value" TYPE DOUBLE PRECISION',
            'ALTER TABLE "daily_bars" ALTER COLUMN "close" TYPE DOUBLE PRECISION'])  # not someone else's
        self.assertIn("ALTER TABLE positions ADD COLUMN live_unrealized_gain DOUBLE PRECISION", executed)
        self.assertEqual(executed[-1], "COMMIT")
        self.assertIn("3 REAL column(s)", err.getvalue())


class ClientPlanTests(TempDBMixin, unittest.TestCase):
    _contexts = AdvisorTests._contexts

    def _facts(self):
        ctxs, cash = self._contexts()
        conn = portfolio.connect(self.db)
        advisor.save_profile(conn, self.user_id, {"goal": "retire", "risk_tolerance": "moderate"})
        facts = client_plan.build_facts(conn, self.user_id, ctxs, cash)
        summary = overview.account_summary(conn, self.user_id, quotes={})
        conn.close()
        return facts, summary, ctxs, cash

    def test_build_facts_matches_clients_overview(self):
        facts, summary, _, _ = self._facts()
        self.assertEqual(facts["summary"]["portfolio_value"], summary["portfolio_value"])
        self.assertEqual(facts["summary"]["gain_pct"], summary["gain_pct"])
        self.assertEqual(facts["cash"], 150.0)
        self.assertEqual([h["symbol"] for h in facts["holdings"]], ["CCC", "AAA", "BBB"])
        self.assertAlmostEqual(sum(h["weight_pct"] for h in facts["holdings"]), 3250 / 3400 * 100)
        # CCC 1600 / 3400 = 47% and AAA 1200 / 3400 = 35% are both over the 15% limit
        self.assertEqual([c["symbol"] for c in facts["concentration"]], ["CCC", "AAA"])
        self.assertEqual(len(facts["alerts"]), summary["n_alerts"])
        self.assertIn("experience", facts["missing"])

    def test_next_steps_parses_bullets_and_sends_no_dollars(self):
        _, _, ctxs, cash = self._facts()
        client = _FakeCreateClient("Here you go:\n- Add a bond fund\n- Trim CCC\n")
        steps = client_plan.next_steps(client, {"goal": "retire"},
                                       advisor.portfolio_summary(ctxs, cash),
                                       "User: how am I doing?", "- house ~2029")
        self.assertEqual(steps, ["Add a bond fund", "Trim CCC"])
        sent = json.dumps({"system": client.kwargs["system"], "messages": client.kwargs["messages"]})
        self.assertNotIn("$", sent)
        self.assertNotIn("Individual", sent)
        self.assertIn("how am I doing", sent)
        self.assertIn("house ~2029", sent)  # the assistant's notes inform the plan

    def test_next_steps_refusal_and_plain_text(self):
        refusing = _Obj(messages=_Obj(create=lambda **kw: _Obj(stop_reason="refusal", content=[])))
        self.assertIsNone(client_plan.next_steps(refusing, {}, "summary"))
        plain = _Obj(messages=_Obj(create=lambda **kw: _Obj(
            stop_reason="end_turn", content=[_Obj(type="text", text="Just diversify.")])))
        self.assertEqual(client_plan.next_steps(plain, {}, "summary"), ["Just diversify."])

    def test_render_pdf_handles_unicode_empty_account_and_no_steps(self):
        facts, _, _, _ = self._facts()
        pdf = client_plan.render_pdf(facts, ["Diversify \U0001F680 中文 — soon"],
                                     account_name="jsmith", advisor_name="alice")
        self.assertTrue(pdf.startswith(b"%PDF"))
        conn = portfolio.connect(self.db)
        empty_id = auth.create_user(conn, "empty", "pw")
        empty = client_plan.build_facts(conn, empty_id, [], {})
        conn.close()
        self.assertTrue(client_plan.render_pdf(empty, None, account_name="empty").startswith(b"%PDF"))


    def test_plan_pdf_includes_goal_and_advisor_steps_but_not_private_notes(self):
        ctxs, cash = self._contexts()
        conn = portfolio.connect(self.db)
        auth.set_advisor(conn, "testuser", True)
        client = auth.create_client(conn, self.user_id, "client1")
        plans.save_plan(conn, client, {"goal_type": "Retirement", "target_amount": 500000,
                                       "target_date": "2050-01-01", "monthly_contribution": 400},
                        set_by=self.user_id)
        advising.add_note(conn, client, self.user_id, "Next step", "Open a Roth IRA", "2026-09-01")
        advising.add_note(conn, client, self.user_id, "Next step", "SECRET-PRIVATE", "2026-09-01",
                          private=True)
        facts = client_plan.build_facts(conn, client, [], {})
        conn.close()
        self.assertEqual(facts["goal"]["target"], 500000)
        self.assertEqual(facts["advisor_steps"], ["Open a Roth IRA"])
        pdf = client_plan.render_pdf(facts, None, account_name="client1", advisor_name="testuser")
        self.assertTrue(pdf.startswith(b"%PDF"))


class RefreshAllUsersTests(TempDBMixin, unittest.TestCase):
    def test_each_ticker_fetched_once_and_applied_to_every_account(self):
        conn = portfolio.connect(self.db)
        other = auth.create_user(conn, "other", "pw")
        portfolio.import_csv(conn, FIXTURE, self.user_id)
        shutil.copyfile(FIXTURE, os.path.join(self.dir, "other.csv"))
        portfolio.import_csv(conn, os.path.join(self.dir, "other.csv"), other)

        fetched = []

        def fake_quote(ticker, key, timeout):
            fetched.append(ticker)
            return {"c": 50.0, "pc": 49.0, "d": 1.0, "dp": 2.0, "t": 1700000000}, ""

        with unittest.mock.patch.object(update_prices, "fetch_quote", side_effect=fake_quote):
            summary = update_prices.refresh_all_users(conn, "key", delay=0)

        self.assertEqual(sorted(fetched), ["AAA", "BBB", "CCC"])     # once each, not per account
        self.assertEqual(summary["updated_by_user"], {self.user_id: 3, other: 3})
        prices = {r["live_price"] for r in conn.execute("SELECT live_price FROM positions")}
        self.assertEqual(prices, {50.0})
        conn.close()


class NoSecretsInRepoTests(unittest.TestCase):
    """This repo is public. Fails if anything shaped like a real Anthropic API
    key or a Neon database password sits in a git-tracked file - an API key
    pasted into COMMANDS.txt nearly got pushed once."""

    PATTERNS = {
        "Anthropic API key": re.compile(r"sk-ant-(?:api|admin)\d\d-[A-Za-z0-9_-]{20,}"),
        "Neon database password": re.compile(r"npg_[A-Za-z0-9]{8,}"),
    }

    def test_tracked_files_contain_no_secrets(self):
        try:
            files = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True,
                                   text=True, check=True).stdout.split()
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git not available")
        found = []
        for rel in files:
            try:
                with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
                    text = fh.read()
            except (OSError, UnicodeDecodeError):
                continue  # deleted in the working tree, or binary
            found += [f"{rel}: {label}" for label, pat in self.PATTERNS.items() if pat.search(text)]
        self.assertEqual(found, [], "secret-looking values in tracked files - remove them before pushing")


class PgCompatTests(unittest.TestCase):
    """Pure logic only - no live Postgres needed. Every SQLite-specific
    construct the real codebase's SQL strings actually use (verified by
    grepping every .py file), translated exactly as portfolio.connect()
    will need it translated when given a Postgres DSN."""

    def test_is_postgres_dsn(self):
        self.assertTrue(pgcompat.is_postgres_dsn("postgres://u:p@host/db"))
        self.assertTrue(pgcompat.is_postgres_dsn("postgresql://u:p@host/db"))
        self.assertFalse(pgcompat.is_postgres_dsn("portfolio.db"))
        self.assertFalse(pgcompat.is_postgres_dsn(r"C:\scratch\test.db"))

    def test_translate_qmark_placeholders(self):
        self.assertEqual(
            pgcompat.translate_sql("SELECT * FROM t WHERE a = ? AND b = ?"),
            "SELECT * FROM t WHERE a = %s AND b = %s")

    def test_translate_named_placeholders(self):
        self.assertEqual(
            pgcompat.translate_sql("INSERT INTO t (a, b) VALUES (:a, :b)"),
            "INSERT INTO t (a, b) VALUES (%(a)s, %(b)s)")

    def test_translate_datetime_now(self):
        self.assertEqual(
            pgcompat.translate_sql("UPDATE t SET x = datetime('now')"),
            f"UPDATE t SET x = {pgcompat.PG_NOW_EXPR}")
        # exact fragment used in sync_history.py's f-strings
        self.assertEqual(
            pgcompat.translate_sql("VALUES (?, ?, datetime('now'))"),
            f"VALUES (%s, %s, {pgcompat.PG_NOW_EXPR})")

    def test_translate_combines_all_three(self):
        sql = ("INSERT INTO news (id, ticker, fetched_at) "
               "VALUES (:id, :ticker, datetime('now')) "
               "ON CONFLICT DO UPDATE SET x = ?")
        self.assertEqual(
            pgcompat.translate_sql(sql),
            "INSERT INTO news (id, ticker, fetched_at) "
            f"VALUES (%(id)s, %(ticker)s, {pgcompat.PG_NOW_EXPR}) "
            "ON CONFLICT DO UPDATE SET x = %s")

    def test_row_supports_positional_and_string_access(self):
        row = pgcompat.Row((1, "AAPL", 150.0), ("id", "symbol", "price"))
        # positional unpacking (perf.py's `for t, ticker, close in ...`)
        a, b, c = row
        self.assertEqual((a, b, c), (1, "AAPL", 150.0))
        # positional index
        self.assertEqual(row[0], 1)
        # string-key access (used pervasively)
        self.assertEqual(row["symbol"], "AAPL")
        self.assertEqual(row["price"], 150.0)

    def test_row_supports_dict_conversion(self):
        row = pgcompat.Row((1, "AAPL"), ("id", "symbol"))
        self.assertEqual(dict(row), {"id": 1, "symbol": "AAPL"})

    def test_split_statements_ignores_blank_segments(self):
        script = "CREATE TABLE a (x INT);\n\nCREATE TABLE b (y INT);  "
        stmts = pgcompat._split_statements(script)
        self.assertEqual(len(stmts), 2)
        self.assertTrue(stmts[0].startswith("CREATE TABLE a"))
        self.assertTrue(stmts[1].startswith("CREATE TABLE b"))

    def test_split_statements_ignores_semicolons_inside_comments(self):
        # Caught for real against a live Neon instance: schema_pg.sql's own
        # header comment contains a literal ';' in prose ("needs_refresh();"),
        # which a naive whole-text split on ';' treated as a statement
        # boundary and fed Postgres a garbage fragment starting mid-comment.
        script = ("-- a comment; with a semicolon in it\n"
                  "CREATE TABLE a (x INT);\n"
                  "-- another; comment; with; several\n"
                  "CREATE TABLE b (y INT);")
        stmts = pgcompat._split_statements(script)
        self.assertEqual(len(stmts), 2)
        self.assertTrue(stmts[0].startswith("CREATE TABLE a"))
        self.assertTrue(stmts[1].startswith("CREATE TABLE b"))

    def test_schema_pg_uses_the_same_now_expression_as_the_shim(self):
        # schema_pg.sql's DEFAULT clauses are written out literally (can't
        # reference a Python constant from SQL) - this pins them to
        # pgcompat.PG_NOW_EXPR so the two can't silently drift apart and
        # produce two different timestamp string shapes.
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "schema_pg.sql"), encoding="utf-8") as fh:
            sql = fh.read()
        n = sql.count(pgcompat.PG_NOW_EXPR)
        self.assertGreater(n, 0, "schema_pg.sql doesn't contain PG_NOW_EXPR verbatim")
        # every DEFAULT clause should use it - count DEFAULT occurrences too
        self.assertEqual(n, sql.count("DEFAULT ("))

    def test_close_swallows_rollback_failure_on_a_stale_pooled_connection(self):
        # Reproduced live against Neon: a pooled connection that went stale
        # between checkouts (server closed an idle connection) raised
        # psycopg.OperationalError from rollback() itself, which crashed the
        # whole page instead of just being treated as "discard this
        # connection, the pool will make a fresh one." close() must never
        # propagate a rollback failure.
        class _DeadConn:
            def rollback(self):
                raise OSError("the socket is dead, as a stale pooled connection's would be")

        putconn_calls = []

        class _FakePool:
            def putconn(self, conn):
                putconn_calls.append(conn)

        dead = _DeadConn()
        wrapper = pgcompat.ConnWrapper(dead, pool=_FakePool())
        wrapper.close()  # must not raise
        self.assertEqual(putconn_calls, [dead])  # still handed back for the pool to discard


class ChartsTests(unittest.TestCase):
    def _df(self, n=40):
        idx = pd.date_range("2026-01-01", periods=n, freq="D", tz="UTC")
        return pd.DataFrame({"t": idx, "v": [100.0 + i for i in range(n)]})

    def test_clip_range(self):
        df = self._df(40)
        self.assertEqual(len(charts.clip_range(df, "t", 5)), 6)     # last point + 5 days back
        self.assertEqual(len(charts.clip_range(df, "t", 14)), 15)
        self.assertEqual(len(charts.clip_range(df, "t", 365)), 40)  # more than we have
        self.assertEqual(len(charts.clip_range(df, "t", None)), 40)

    def test_window_change(self):
        df = self._df(11)  # values 100..110
        first, last, pct = charts.window_change(df, "t", "v")
        self.assertEqual((first, last), (100.0, 110.0))
        self.assertAlmostEqual(pct, 10.0)
        self.assertEqual(charts.window_change(df.iloc[0:0], "t", "v"), (None, None, None))

    def test_window_never_returns_whole_frame_when_range_too_short(self):
        df = self._df(40)
        # consecutive daily points: "1D" legitimately gives the last two
        win, short = charts.window(df, "t", 1)
        self.assertEqual(len(win), 2)
        self.assertFalse(short)
        # isolated last point (a gap): the clip yields 1 row -> fall back to last 2,
        # NOT the whole 40-row frame
        gappy = pd.concat([df.iloc[:39],
                           df.iloc[[39]].assign(t=df["t"].iloc[38] + pd.Timedelta(days=6))])
        win, short = charts.window(gappy, "t", 1)
        self.assertEqual(len(win), 2)
        self.assertTrue(short)
        # a comfortable range and "All" behave normally
        self.assertFalse(charts.window(df, "t", 30)[1])
        self.assertEqual(len(charts.window(df, "t", None)[0]), 40)

    def test_line_builds_layered_chart(self):
        spec = charts.line(self._df(5), x="t", y="v", y_title="V", y_format="$,.2f",
                           tooltip=[]).to_dict()
        self.assertIn("layer", spec)
        self.assertGreaterEqual(len(spec["layer"]), 3)

    def test_line_has_no_permanent_point_markers(self):
        spec = charts.line(self._df(5), x="t", y="v", y_title="V", y_format="$,.2f",
                           tooltip=[]).to_dict()
        line_layer = spec["layer"][0]
        mark = line_layer["mark"]
        self.assertFalse(mark.get("point", False))

    def test_line_color_sets_fixed_colour_no_legend(self):
        spec = charts.line(self._df(5), x="t", y="v", y_title="V", y_format="$,.2f",
                           tooltip=[], line_color="#22c55e").to_dict()
        line_layer = spec["layer"][0]
        self.assertEqual(line_layer["encoding"]["color"]["value"], "#22c55e")

    def test_compress_gaps_uses_ordinal_axis_in_chronological_order(self):
        # a gap that spans a month boundary - lexical string sort of the axis
        # labels ("Feb..." < "Jan...") would get this backwards if not handled
        idx = pd.to_datetime(["2026-01-30T09:30:00Z", "2026-01-30T09:31:00Z",
                              "2026-02-02T09:30:00Z", "2026-02-02T09:31:00Z"], utc=True)
        df = pd.DataFrame({"t": idx, "v": [10.0, 11.0, 12.0, 13.0]})
        spec = charts.line(df, x="t", y="v", y_title="V", y_format="$,.2f",
                           tooltip=[], compress_gaps=True).to_dict()
        line_layer = spec["layer"][0]
        self.assertEqual(line_layer["encoding"]["x"]["field"], "_x")
        self.assertEqual(line_layer["encoding"]["x"]["type"], "ordinal")
        # explicit chronological sort order, not the field's own alphabetical order
        expected_sort = ["Jan 30 09:30", "Jan 30 09:31", "Feb 02 09:30", "Feb 02 09:31"]
        self.assertEqual(line_layer["encoding"]["x"]["sort"], expected_sort)
        # every layer sharing the ordinal x channel must carry the SAME explicit
        # sort - Vega-Lite merges per-layer sorts for a shared scale, and a layer
        # left without one drags the whole resolved domain back to alphabetical
        # (this is exactly how the axis-order bug slipped through before).
        for layer in spec["layer"]:
            x_enc = layer.get("encoding", {}).get("x")
            if x_enc is not None and x_enc.get("field") == "_x":
                self.assertEqual(x_enc.get("sort"), expected_sort)

    def test_compress_gaps_off_keeps_temporal_axis(self):
        spec = charts.line(self._df(5), x="t", y="v", y_title="V", y_format="$,.2f",
                           tooltip=[], compress_gaps=False).to_dict()
        self.assertEqual(spec["layer"][0]["encoding"]["x"]["field"], "t")
        self.assertEqual(spec["layer"][0]["encoding"]["x"]["type"], "temporal")


class ManualEntryTests(TempDBMixin, unittest.TestCase):
    ROWS = [{"Account": "Roth", "Symbol": " vti ", "Shares": 10, "Total cost": 2000.0,
             "Type": "ETF"},
            {"Account": "", "Symbol": "VTSAX", "Shares": "5.5", "Total cost": None,
             "Type": "Mutual fund"},
            {"Account": "Roth", "Symbol": "", "Shares": None, "Total cost": None, "Type": "ETF"}]

    def test_validate_cleans_rows_and_reports_problems(self):
        import manual_entry as me
        clean, cash, errors = me.validate(self.ROWS, [{"Account": "Roth", "Cash": "1,000"}])
        self.assertEqual(errors, [])
        self.assertEqual([(h["account"], h["symbol"], h["quantity"], h["asset_type"]) for h in clean],
                         [("Roth", "VTI", 10.0, "ETFs & Closed End Funds"),
                          (me.DEFAULT_ACCOUNT, "VTSAX", 5.5, "Mutual Funds")])  # blank row dropped
        self.assertEqual(cash, {"Roth": 1000.0})
        bad = [{"Symbol": "VTI", "Shares": 0}, {"Symbol": "", "Shares": 3},
               {"Symbol": "B@D", "Shares": 1}, {"Symbol": "X", "Shares": 1, "Total cost": "abc"},
               {"Symbol": "Y", "Shares": 1}, {"Symbol": "Y", "Shares": 2}]
        _, _, errors = me.validate(bad, [{"Account": "A", "Cash": -5}])
        text = " ".join(errors)
        for bit in ("more than 0", "add a symbol", "doesn't look like", "dollar amount",
                    "listed twice", "Cash for A"):
            self.assertIn(bit, text)
        self.assertEqual(me.validate([], [])[2], ["Add at least one holding or some cash."])
        # cash on the default name follows a single renamed account
        one = [{"Account": "Roth", "Symbol": "VTI", "Shares": 1}]
        self.assertEqual(me.validate(one, [{"Account": me.DEFAULT_ACCOUNT, "Cash": 50}])[1],
                         {"Roth": 50.0})
        two = one + [{"Account": "Taxable", "Symbol": "BND", "Shares": 1}]
        self.assertEqual(me.validate(two, [{"Account": "", "Cash": 50}])[1],
                         {me.DEFAULT_ACCOUNT: 50.0})  # ambiguous: left alone

    def test_lookup_prefers_finnhub_then_yahoo_and_keeps_known_names(self):
        import manual_entry as me
        asked = []
        found = me.lookup(["VTI", "VTSAX", "NOPE"],
                          finnhub_quote=lambda s: {"VTI": 300.0}.get(s),
                          yahoo_info=lambda s: asked.append(s) or {"VTSAX": (150.0, "Vanguard TSM")
                                                                   }.get(s, (None, None)),
                          known_names={"VTI": "Vanguard Total Stock"})
        self.assertEqual(found["VTI"], {"price": 300.0, "name": "Vanguard Total Stock"})
        self.assertEqual(found["VTSAX"], {"price": 150.0, "name": "Vanguard TSM"})
        self.assertIsNone(found["NOPE"]["price"])
        self.assertNotIn("VTI", asked)  # had a price and a name: no Yahoo call

    def test_saved_like_an_import_and_replaces_the_same_day(self):
        import manual_entry as me
        clean, cash, _ = me.validate(self.ROWS, [{"Account": "Roth", "Cash": 500}])
        found = {"VTI": {"price": 300.0, "name": "Total Stock"},
                 "VTSAX": {"price": 150.0, "name": None}}
        meta, rows, totals, errors = me.build(clean, cash, found, today=date(2026, 9, 29))
        self.assertEqual(errors, [])
        self.assertEqual(rows[0]["market_value"], 3000.0)
        self.assertEqual(rows[0]["reported_gain"], 1000.0)
        conn = portfolio.connect(self.db)
        portfolio.write_snapshot(conn, self.user_id, meta, rows, totals, me.SOURCE)
        self.assertEqual(update_prices.latest_snapshot(conn, self.user_id), "2026-09-29")
        got = {r["symbol"]: r["market_value"] for r in conn.execute(
            "SELECT symbol, market_value FROM positions WHERE user_id = ?", (self.user_id,))}
        self.assertEqual(got, {"VTI": 3000.0, "VTSAX": 825.0})
        cash_rows = {r["account"]: r["cash_value"] for r in conn.execute(
            "SELECT account, cash_value FROM account_totals WHERE user_id = ?", (self.user_id,))}
        self.assertEqual(cash_rows, {"Roth": 500.0, me.DEFAULT_ACCOUNT: None})
        # saving again the same day replaces, it doesn't add
        meta2, rows2, totals2, _ = me.build(clean[:1], {}, found, today=date(2026, 9, 29))
        portfolio.write_snapshot(conn, self.user_id, meta2, rows2, totals2, me.SOURCE)
        self.assertEqual(conn.execute("SELECT COUNT(*) n FROM positions WHERE user_id = ?",
                                      (self.user_id,)).fetchone()["n"], 1)
        conn.close()

    def test_missing_price_is_an_error_and_prefill_round_trips(self):
        import manual_entry as me
        clean, _, _ = me.validate(self.ROWS[:1], [])
        self.assertIn("check the symbol", me.build(clean, {}, {"VTI": {"price": None}})[3][0])
        holdings, cash = me.prefill([{"account": "Roth", "symbol": "VTI", "quantity": 10,
                                      "cost_basis": 2000.0, "asset_type": "Fixed Income"}],
                                    {"Roth": 250.0, "Empty": 0})
        self.assertEqual(holdings[0]["Type"], "Bond")
        self.assertEqual(cash, [{"Account": "Roth", "Cash": 250.0}])
        self.assertEqual(me.validate(holdings, cash)[2], [])


class AssetClassTests(unittest.TestCase):
    AOR = {"quote_type": "ETF", "stock_pct": 0.6178, "bond_pct": 0.3754, "cash_pct": 0.0065,
           "other_pct": 0.0002}

    def test_yahoo_splits_funds_and_classes_stocks_and_money_market(self):
        import asset_classes as ac
        s = ac.from_yahoo(self.AOR)
        self.assertAlmostEqual(sum(s.values()), 1.0)
        self.assertAlmostEqual(s["Stocks"], 0.6178 / 0.9999, places=4)
        self.assertEqual(ac.main_class(s), "Stocks")
        self.assertEqual(ac.from_yahoo({"quote_type": "EQUITY"}), {"Stocks": 1.0})
        self.assertEqual(ac.from_yahoo({"quote_type": "MONEYMARKET"}), {"Cash": 1.0})
        self.assertIsNone(ac.from_yahoo({"quote_type": "ETF"}))       # no breakdown
        self.assertIsNone(ac.from_yahoo(None))
        self.assertEqual(ac.describe({"Bonds": 1.0}), "Bonds")
        self.assertEqual(ac.describe({"Stocks": 0.62, "Bonds": 0.38}), "62% stocks / 38% bonds")

    def test_override_beats_yahoo_beats_broker_type(self):
        import asset_classes as ac
        self.assertEqual(ac.split_for("AOR", "ETFs & Closed End Funds", self.AOR,
                                      {"AOR": "Bonds"}), ({"Bonds": 1.0}, "override"))
        self.assertEqual(ac.split_for("AOR", "ETFs & Closed End Funds", self.AOR)[1], "yahoo")
        self.assertEqual(ac.split_for("BND", "Fixed Income", None), ({"Bonds": 1.0}, "broker"))
        self.assertEqual(ac.split_for("XYZ", "ETFs & Closed End Funds", None),
                         ({"Other": 1.0}, "broker"))
        self.assertEqual(ac.split_for("X", "Equity", None, {"X": "Nonsense"})[1], "broker")

    def test_allocate_splits_balanced_funds_and_falls_back_to_broker_type(self):
        pos = [{"symbol": "AOR", "asset_type": "ETFs & Closed End Funds", "market_value": 1000,
                "account": "A"},
               {"symbol": "BND", "asset_type": "Fixed Income", "market_value": 500, "account": "A"},
               {"symbol": "VTI", "asset_type": "ETFs & Closed End Funds", "market_value": 250,
                "account": "A"}]
        out = allocation.allocate(pos, {"A": 250}, {"AOR": {"Stocks": 0.6, "Bonds": 0.4}})
        by = {r["label"]: r["value"] for r in out["by_asset_class"]}
        self.assertEqual(by, {"Stocks": 600.0, "Bonds": 900.0, "Cash": 250.0, "Other": 250.0})
        self.assertAlmostEqual(sum(r["pct"] for r in out["by_asset_class"]), 100.0)
        self.assertIn("ETF / CEF", {r["label"] for r in out["by_asset_type"]})  # still there

    def test_old_targets_convert_where_they_map(self):
        import asset_classes as ac
        self.assertEqual(ac.convert_targets({"Equity": 60, "Fixed Income": 35, "Cash": 5}),
                         ({"Stocks": 60.0, "Bonds": 35.0, "Cash": 5.0}, False))
        self.assertEqual(ac.convert_targets({"ETF / CEF": 70, "Fixed Income": 30}), ({}, True))
        self.assertEqual(ac.convert_targets({"Stocks": 60, "Bonds": 40}),
                         ({"Stocks": 60.0, "Bonds": 40.0}, False))
        self.assertEqual(ac.convert_targets({"Option": 10}), ({}, True))
        self.assertEqual(ac.convert_targets(None), ({}, False))


class AssetClassStorageTests(TempDBMixin, unittest.TestCase):
    def test_migration_moves_plans_and_models_once(self):
        import asset_classes as ac
        conn = portfolio.connect(self.db)
        other = auth.create_user(conn, "other", "pw")
        conn.execute("INSERT INTO plans (user_id, target_alloc) VALUES (?, ?)",
                     (self.user_id, json.dumps({"Equity": 60, "Fixed Income": 40})))
        conn.execute("INSERT INTO plans (user_id, target_alloc) VALUES (?, ?)",
                     (other, json.dumps({"ETF / CEF": 100})))
        conn.execute("INSERT INTO model_portfolios (advisor_id, name, target_alloc) VALUES (?, ?, ?)",
                     (self.user_id, "Old", json.dumps({"Mutual Funds": 50, "Cash": 50})))
        conn.commit()
        self.assertEqual(ac.migrate_targets(conn),
                         {"plans": 2, "plans_cleared": 1, "models": 1, "models_cleared": 1})
        conn.commit()
        self.assertEqual(plans.get_plan(conn, self.user_id)["target_alloc"],
                         {"Stocks": 60.0, "Bonds": 40.0})
        cleared = plans.get_plan(conn, other)
        self.assertEqual((cleared["target_alloc"], cleared["targets_cleared"]), ({}, 1))
        self.assertEqual(advising.list_models(conn, self.user_id)[0]["target_alloc"], {})
        self.assertEqual(ac.migrate_targets(conn)["plans"], 0)          # nothing left to do
        plans.save_plan(conn, other, {"target_alloc": {"Stocks": 100}}, other)
        self.assertEqual(plans.get_plan(conn, other)["targets_cleared"], 0)  # note goes away
        conn.close()

    def test_fund_split_is_stored_and_read_back(self):
        import asset_classes as ac
        conn = portfolio.connect(self.db)
        sync_history.upsert_info(conn, "AOR", {"name": "Balanced", **AssetClassTests.AOR})
        sync_history.upsert_info(conn, "AAPL", {"quote_type": "EQUITY"})
        conn.commit()
        pos = [{"symbol": "AOR", "asset_type": "ETFs & Closed End Funds"},
               {"symbol": "AAPL", "asset_type": "Equity"},
               {"symbol": "NEW", "asset_type": "Fixed Income"}]
        s = ac.splits(conn, pos, {"AAPL": "Other"})
        self.assertEqual(ac.main_class(s["AOR"]), "Stocks")
        self.assertEqual(s["AAPL"], {"Other": 1.0})                    # override wins
        self.assertEqual(s["NEW"], {"Bonds": 1.0})                     # no Yahoo row yet
        conn.close()


class FetchFundSplitTests(unittest.TestCase):
    """fetch_info asks Yahoo for a breakdown only for funds, and a failure
    there leaves the fund unclassified instead of breaking the sync."""

    def _fake_yf(self, info, asset_classes=None, fail=False):
        calls = []

        class FundsData:
            @property
            def asset_classes(self):
                if fail:
                    raise RuntimeError("no fund data")
                return asset_classes

        class Ticker:
            def __init__(self, t):
                self.info = info

            @property
            def funds_data(self):
                calls.append("funds_data")
                return FundsData()
        return type(sys)("yf"), Ticker, calls

    def _fetch(self, info, **kw):
        fake, ticker_cls, calls = self._fake_yf(info, **kw)
        fake.Ticker = ticker_cls
        with unittest.mock.patch.object(sync_history, "yf", fake):
            return sync_history.fetch_info("T"), calls

    def test_fund_gets_its_split(self):
        out, calls = self._fetch({"quoteType": "ETF", "category": "Allocation"},
                                 asset_classes={"stockPosition": 0.6, "bondPosition": 0.38,
                                                "cashPosition": 0.01, "preferredPosition": 0.01})
        self.assertEqual(calls, ["funds_data"])
        self.assertEqual((out["quote_type"], out["category"]), ("ETF", "Allocation"))
        self.assertEqual((out["stock_pct"], out["bond_pct"], out["other_pct"]), (0.6, 0.38, 0.01))

    def test_stock_makes_no_extra_request_and_failures_stay_blank(self):
        out, calls = self._fetch({"quoteType": "EQUITY"})
        self.assertEqual(calls, [])
        self.assertIsNone(out["stock_pct"])
        out, _ = self._fetch({"quoteType": "MUTUALFUND"}, fail=True)
        self.assertIsNone(out["bond_pct"])
        self.assertEqual(out["quote_type"], "MUTUALFUND")


class DisclosureTests(unittest.TestCase):
    def test_text_is_safe_markdown_and_covers_the_basics(self):
        import disclosures
        text = disclosures.SUMMARY + "".join(t + b for t, b in disclosures.SECTIONS)
        self.assertNotIn("$", text)  # Streamlit reads a pair of them as math
        for must in ("not financial advice", "Anthropic", "percentages", "header row",
                     "ticker", "Schwab", "hypothetical"):
            self.assertIn(must.lower(), text.lower())

    def test_the_ai_summary_it_describes_has_no_dollar_amounts(self):
        # disclosures promise the AI sees weights only; hold the code to it
        ctx = {"pos": {"symbol": "VTI", "account": "Brokerage 1234", "quantity": 123.0,
                       "market_value": 45678.9}, "metrics": {}}
        with unittest.mock.patch.object(advisor.M, "value",
                                        side_effect=lambda k, c: {"pct_of_portfolio": 100.0,
                                                                  "description": "Total Market"}.get(k)):
            text = advisor.portfolio_summary([ctx], {"Brokerage 1234": 250.0})
        for leak in ("45678", "45,678", "123", "Brokerage 1234", "250"):
            self.assertNotIn(leak, text)


class FriendlyErrorTests(unittest.TestCase):
    """An error in a page shows the friendly message, never the traceback
    (unless running locally with details on)."""

    SCRIPT = """
import sys
sys.path.insert(0, {repo!r})
import friendly_errors
import streamlit as st
friendly_errors.install(show_details={details})
st.write("before the error")
raise RuntimeError("secret detail")
"""

    def _run(self, details):
        from streamlit.testing.v1 import AppTest
        with contextlib.redirect_stderr(io.StringIO()) as err:
            at = AppTest.from_string(self.SCRIPT.format(repo=REPO, details=details)).run()
        return at, err.getvalue()

    def test_hosted_shows_the_message_and_logs_the_code(self):
        at, log = self._run(False)
        self.assertEqual(len(at.exception), 0)                      # no traceback on screen
        msg = at.error[0].value
        self.assertIn("Something went wrong", msg)
        self.assertNotIn("secret detail", msg)
        code = re.search(r"\*\*([0-9a-f]{6})\*\*", msg).group(1)
        self.assertIn(f"error code {code}", log)                    # matches the log line
        self.assertEqual([b.label for b in at.button], ["Try again"])
        self.assertEqual(at.markdown[0].value, "before the error")  # the page so far stays

    def test_local_run_can_show_details(self):
        at, _ = self._run(True)
        self.assertEqual(len(at.exception), 1)
        self.assertIn("secret detail", at.exception[0].message)

    def test_install_outside_a_streamlit_run_does_nothing(self):
        import friendly_errors
        self.assertFalse(friendly_errors.install())


class CodeFreshTests(unittest.TestCase):
    """A deploy that changes a module's file reloads all of the app's modules."""

    def setUp(self):
        import codefresh
        self.cf = codefresh
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        sys.path.insert(0, self.dir)
        self.addCleanup(sys.path.remove, self.dir)
        self.names = ["cf_mod_a", "cf_mod_b"]
        self.addCleanup(lambda: [sys.modules.pop(n, None) for n in self.names])
        for n in self.names:
            self._write(n, "VERSION = 1\n")

    def _write(self, name, text):
        with open(os.path.join(self.dir, name + ".py"), "w") as f:
            f.write(text)

    def _load(self):
        import importlib
        importlib.invalidate_caches()
        return [importlib.import_module(n) for n in self.names]

    def test_unchanged_files_keep_their_modules(self):
        a, _ = self._load()
        self.cf.mark_loaded(self.dir)
        self.assertEqual(self.cf.drop_stale(self.dir), {})
        self.assertIs(sys.modules["cf_mod_a"], a)

    def test_one_changed_file_reloads_them_all(self):
        a, b = self._load()
        self.cf.mark_loaded(self.dir)
        self._write("cf_mod_a", "VERSION = 2\nNEW = True\n")
        with contextlib.redirect_stderr(io.StringIO()):
            old = self.cf.drop_stale(self.dir)
        self.assertEqual(set(old), set(self.names))
        a2, b2 = self._load()
        self.assertEqual((a2.VERSION, a2.NEW), (2, True))
        self.assertIsNot(b2, b)  # the unchanged one is reloaded too
        self.cf.mark_loaded(self.dir)
        self.assertEqual(self.cf.drop_stale(self.dir), {})

    def test_modules_loaded_before_codefresh_count_as_stale(self):
        self._load()  # loaded, never stamped - a server running before the safeguard
        with unittest.mock.patch.object(self.cf, "_PREEXISTING", set(self.names)), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(set(self.cf.drop_stale(self.dir)), set(self.names))
        self._load()  # imported after codefresh (e.g. a lazy import): trusted
        self.assertEqual(self.cf.drop_stale(self.dir), {})

    def test_connection_pools_carry_over(self):
        old_pg = type(sys)("pgcompat")
        old_pg._POOLS = {"dsn": "pool"}
        new_pg = type(sys)("pgcompat")
        new_pg._POOLS = {}
        with unittest.mock.patch.dict(sys.modules, {"pgcompat": new_pg}):
            self.cf.carry_over({"pgcompat": old_pg})
        self.assertEqual(new_pg._POOLS, {"dsn": "pool"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
