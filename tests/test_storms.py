"""Storms (ROADMAP T4): storms.py and perf.daily_values()."""

import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth  # noqa: E402
import perf  # noqa: E402
import portfolio  # noqa: E402
import storms  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample_positions.csv")


def _days(values, end=date(2026, 9, 30)):
    """(date, value) one day apart, ending on `end`."""
    n = len(values)
    return [((end - timedelta(days=n - 1 - i)).isoformat(), v) for i, v in enumerate(values)]


class WeatherTests(unittest.TestCase):
    def test_calm(self):
        self.assertIsNone(storms.weather(_days([100, 101, 99, 98, 97, 98])))   # 3% off

    def test_rough_and_storm(self):
        w = storms.weather(_days([100, 102, 99, 97, 96]))
        self.assertEqual(w["level"], "rough")
        self.assertAlmostEqual(w["drop_pct"], (102 - 96) / 102 * 100)
        self.assertEqual(w["high_date"], "2026-09-27")
        self.assertEqual(w["as_of"], "2026-09-30")
        self.assertEqual(storms.weather(_days([100, 100, 95, 90, 88]))["level"], "storm")

    def test_high_only_within_window(self):
        # a high from long ago doesn't count, and order and junk don't matter
        old = [("2026-01-02", 500.0)]
        recent = _days([100, 99, 98, 97, 96, 95])
        self.assertEqual(storms.weather(list(reversed(old + recent)))["high"], 100)
        self.assertIsNone(storms.weather(_days([100, None, 0, 90])))   # too few real closes

    def test_recovered_is_calm(self):
        self.assertIsNone(storms.weather(_days([100, 85, 90, 95, 99])))

    def test_hidden(self):
        w = storms.weather(_days([100, 100, 95, 94, 94]))
        hide = {"level": "rough", "high_date": w["high_date"]}
        self.assertTrue(storms.hidden(w, hide))
        worse = dict(w, level="storm")
        self.assertFalse(storms.hidden(worse, hide))                    # it got worse
        self.assertFalse(storms.hidden(dict(w, high_date="2026-10-01"), hide))   # a new high
        self.assertFalse(storms.hidden(w, None))
        self.assertFalse(storms.hidden(None, hide))

    def test_never_advice(self):
        text = " ".join(name for name, _, _ in storms.PAST_STORMS)
        for word in ("buy", "sell", "should"):
            self.assertNotIn(word, text.lower())


class DailyValuesTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_test_")
        self.db = os.path.join(self.dir, "test.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        conn = portfolio.connect(self.db)
        self.user_id = auth.create_user(conn, "testuser", "testpass")
        portfolio.import_csv(conn, FIXTURE, self.user_id)   # AAA x10, BBB x5, CCC x2
        bars = []
        for i in range(10):
            d = f"2026-03-{i + 1:02d}"
            bars += [("AAA", d, 100.0 - i), ("CCC", d, 800.0)]
            if i >= 5:
                bars.append(("BBB", d, 90.0))          # listed later
        conn.executemany("INSERT INTO daily_bars (ticker, date, close, volume) "
                         "VALUES (?, ?, ?, 1000)", bars)
        conn.commit()
        conn.close()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_only_fully_priced_days(self):
        basis = perf._basis(portfolio.connect(self.db), self.user_id)
        vals = perf.daily_values(self.db, basis, "2026-03-01")
        self.assertEqual([d for d, _ in vals], [f"2026-03-{i:02d}" for i in range(6, 11)])
        cash = basis[2]
        self.assertAlmostEqual(vals[0][1], 95 * 10 + 90 * 5 + 800 * 2 + cash)
        self.assertEqual(len(perf.daily_values(self.db, basis, "2026-03-09")), 2)


if __name__ == "__main__":
    unittest.main()
