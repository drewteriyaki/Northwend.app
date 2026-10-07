"""Fee check (ROADMAP G10): fees.py, the expense ratio from the nightly sync,
and the Home card / window.

    python -m unittest discover -s tests        (from the repo root)
"""

import contextlib
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import auth  # noqa: E402
import fees  # noqa: E402
import perf  # noqa: E402
import portfolio  # noqa: E402
import sample_data  # noqa: E402
import sync_history  # noqa: E402


class CostOverTests(unittest.TestCase):
    def test_compounds_the_fee_and_its_lost_growth(self):
        one = fees.cost_over(10_000, 0.01, 1, 0.06)
        self.assertAlmostEqual(one["paid"], 106.0)
        self.assertAlmostEqual(one["lost_growth"], 0.0)
        two = fees.cost_over(10_000, 0.01, 2, 0.06)
        self.assertAlmostEqual(two["paid"], 106.0 + 111.2364)
        self.assertAlmostEqual(two["total"], 10_000 * 1.06 ** 2 - 10_000 * (1.06 * 0.99) ** 2)
        self.assertAlmostEqual(two["paid"] + two["lost_growth"], two["total"])
        self.assertGreater(two["lost_growth"], 0)

    def test_longer_and_costlier_add_up_to_more(self):
        cheap, dear = fees.cost_over(50_000, 0.0003, 30), fees.cost_over(50_000, 0.0075, 30)
        self.assertGreater(dear["total"], 20 * cheap["total"])
        self.assertGreater(fees.cost_over(50_000, 0.0075, 30)["total"],
                           3 * fees.cost_over(50_000, 0.0075, 10)["total"])

    def test_nothing_costs_nothing(self):
        self.assertEqual(fees.cost_over(0, 0.01, 30)["total"], 0)
        self.assertEqual(fees.cost_over(10_000, 0, 30)["total"], 0)
        self.assertEqual(fees.cost_over(None, None, 10)["total"], 0)


class KindTests(unittest.TestCase):
    def test_from_yahoo_category(self):
        for cat, kind in (("Large Blend", "us_stock"), ("Mid-Cap Growth", "us_stock"),
                          ("Small Value", "us_stock"), ("Foreign Large Blend", "intl_stock"),
                          ("Diversified Emerging Mkts", "intl_stock"),
                          ("Intermediate Core Bond", "bond"), ("Muni National Interm", "bond"),
                          ("Inflation-Protected Bond", "bond"), ("World Bond", "bond"),
                          ("Target-Date 2055", "target_date"),
                          ("Global Moderate Allocation", "balanced"),
                          ("Technology", "sector"), ("Global Real Estate", "sector"),
                          ("Trading--Leveraged Equity", None), ("Trading--Inverse Equity", None)):
            with self.subTest(cat):
                self.assertEqual(fees.kind_of(cat), kind)

    def test_falls_back_to_the_name_then_what_it_holds(self):
        self.assertEqual(fees.kind_of(None, "Vanguard Target Retirement 2055 Fund"), "target_date")
        self.assertEqual(fees.kind_of(None, "Vanguard Total Intl Stock Index Admiral"),
                         "intl_stock")
        self.assertEqual(fees.kind_of(None, "Fidelity 500 Index"), "us_stock")
        self.assertEqual(fees.kind_of("", "Vanguard Total Bond Market Index Adm"), "bond")
        self.assertEqual(fees.kind_of(None, "ProShares UltraPro QQQ 3x"), None)
        self.assertEqual(fees.kind_of(None, "Some Fund", {"stock_pct": 0.6, "bond_pct": 0.4}),
                         "balanced")
        self.assertEqual(fees.kind_of(None, "Some Fund", {"stock_pct": 0.97, "cash_pct": 0.03}),
                         "stock")
        self.assertEqual(fees.kind_of(None, "Some Fund", {"bond_pct": 0.9, "cash_pct": 0.1}),
                         "bond")
        self.assertIsNone(fees.kind_of(None, "Some Fund"))

    def test_every_kind_has_a_plausible_low_cost_figure(self):
        for key, (label, typical) in fees.KINDS.items():
            with self.subTest(key):
                self.assertTrue(label)
                self.assertTrue(0.0001 <= typical <= 0.0025)   # 0.01% - 0.25%

    def test_holding_types(self):
        self.assertEqual(fees.holding_type("ETF", "Equity"), "fund")
        self.assertEqual(fees.holding_type("MUTUALFUND", None), "fund")
        self.assertEqual(fees.holding_type("EQUITY", "Equity"), "stock")
        self.assertEqual(fees.holding_type("EQUITY", "ETFs & Closed End Funds"), "fund")  # a CEF
        self.assertEqual(fees.holding_type("MONEYMARKET", "Mutual Funds"), "cash")
        self.assertEqual(fees.holding_type(None, "Cash and Money Market"), "cash")
        self.assertEqual(fees.holding_type(None, "Mutual Funds"), "fund")   # not synced yet
        self.assertEqual(fees.holding_type("", "Equity"), "stock")
        self.assertEqual(fees.holding_type("CRYPTOCURRENCY", "Crypto"), "other")
        self.assertEqual(fees.holding_type(None, "Fixed Income"), "other")    # a single bond


class CheckTests(unittest.TestCase):
    INFO = {"VTI": {"quote_type": "ETF", "category": "Large Blend", "expense_ratio": 0.0003,
                    "name": "Vanguard Total Stock Market ETF"},
            "ARKK": {"quote_type": "ETF", "category": "Mid-Cap Growth", "expense_ratio": 0.0075},
            "NEWF": {"quote_type": "MUTUALFUND", "expense_ratio": None},
            "AAPL": {"quote_type": "EQUITY"},
            "SPAXX": {"quote_type": "MONEYMARKET"}}
    HOLDINGS = [
        {"symbol": "VTI", "name": "VTI ETF", "asset_type": "ETFs & Closed End Funds", "value": 6000},
        {"symbol": "VTI", "name": "VTI ETF", "asset_type": "ETFs & Closed End Funds", "value": 4000},
        {"symbol": "ARKK", "name": "ARK Innovation", "asset_type": "ETFs & Closed End Funds",
         "value": 2000},
        {"symbol": "NEWF", "name": "A new fund", "asset_type": "Mutual Funds", "value": 500},
        {"symbol": "OLDF", "name": "Never synced", "asset_type": "Mutual Funds", "value": 900},
        {"symbol": "AAPL", "name": "Apple", "asset_type": "Equity", "value": 3000},
        {"symbol": "SPAXX", "name": "Money market", "asset_type": "Cash and Money Market",
         "value": 800},
        {"symbol": "", "value": 5}]

    def test_yearly_cost_total_and_years(self):
        r = fees.check(self.HOLDINGS, self.INFO)
        self.assertEqual([f["symbol"] for f in r["funds"]], ["ARKK", "VTI"])  # costliest first
        vti = r["funds"][1]
        self.assertEqual(vti["value"], 10_000)                 # two accounts added up
        self.assertAlmostEqual(vti["yearly"], 3.0)
        self.assertEqual(vti["name"], "Vanguard Total Stock Market ETF")  # Yahoo's name first
        self.assertEqual((vti["kind"], vti["typical"]), ("us_stock", fees.KINDS["us_stock"][1]))
        self.assertAlmostEqual(vti["typical_yearly"], 10_000 * fees.KINDS["us_stock"][1])
        self.assertAlmostEqual(r["total_yearly"], 3.0 + 15.0)
        self.assertAlmostEqual(r["value_known"], 12_000)
        self.assertAlmostEqual(r["ratio"], 18 / 12_000)
        for y in (10, 30):
            self.assertAlmostEqual(r["over"][y]["total"],
                                   fees.cost_over(10_000, 0.0003, y)["total"]
                                   + fees.cost_over(2000, 0.0075, y)["total"])
        self.assertGreater(r["over"][30]["total"], r["over"][10]["total"])
        self.assertEqual(r["growth"], fees.GROWTH)

    def test_unknown_stocks_and_cash_are_said_not_counted(self):
        r = fees.check(self.HOLDINGS, self.INFO)
        self.assertEqual([u["symbol"] for u in r["unknown"]], ["OLDF", "NEWF"])
        self.assertEqual(r["no_fee"], ["AAPL"])
        self.assertEqual(r["cash"], ["SPAXX"])
        self.assertTrue(fees.has_funds(r))

    def test_only_stocks_has_nothing_to_show(self):
        r = fees.check([{"symbol": "AAPL", "asset_type": "Equity", "value": 100}], self.INFO)
        self.assertFalse(fees.has_funds(r))
        self.assertIsNone(r["ratio"])
        self.assertEqual(r["over"][30]["total"], 0)
        self.assertFalse(fees.has_funds(fees.check([], None)))

    def test_ratio_formatting(self):
        self.assertEqual(fees.fmt_ratio(0.0003), "0.03%")
        self.assertEqual(fees.fmt_ratio(0.00014999999), "0.015%")
        self.assertEqual(fees.fmt_ratio(0.0075), "0.75%")
        self.assertEqual(fees.fmt_ratio(0.01), "1.00%")
        self.assertEqual(fees.fmt_ratio(None), "—")


class FetchExpenseRatioTests(unittest.TestCase):
    """sync_history keeps the expense ratio as a fraction, whatever unit Yahoo
    used, from the requests it already makes."""

    def _fetch(self, info, *, ops=None, overview=None, asset_classes=None):
        import pandas as pd
        calls = []

        class FundsData:
            asset_classes = None
            fund_overview = None

            @property
            def fund_operations(self):
                if ops is None:
                    raise RuntimeError("no operations")
                return pd.DataFrame({"T": [ops, 0.02]},
                                    index=["Annual Report Expense Ratio", "Annual Holdings Turnover"])

        fd = FundsData()
        fd.asset_classes = asset_classes or {"stockPosition": 1.0}
        fd.fund_overview = overview

        class Ticker:
            def __init__(self, t):
                self.info = info

            @property
            def funds_data(self):
                calls.append("funds_data")
                return fd
        fake = type(sys)("yf")
        fake.Ticker = Ticker
        with unittest.mock.patch.object(sync_history, "yf", fake):
            return sync_history.fetch_info("T"), calls

    def test_net_ratio_is_a_percent_and_annual_report_a_fraction(self):
        out, calls = self._fetch({"quoteType": "ETF", "netExpenseRatio": 0.03})   # VOO
        self.assertAlmostEqual(out["expense_ratio"], 0.0003)
        self.assertEqual(calls, ["funds_data"])                  # no extra request
        out, _ = self._fetch({"quoteType": "MUTUALFUND", "annualReportExpenseRatio": 0.0004})
        self.assertAlmostEqual(out["expense_ratio"], 0.0004)
        out, _ = self._fetch({"quoteType": "MUTUALFUND", "netExpenseRatio": 0.04,
                              "annualReportExpenseRatio": 0.0004})
        self.assertAlmostEqual(out["expense_ratio"], 0.0004)

    def test_fund_details_fill_in_the_ratio_and_a_mutual_funds_category(self):
        out, calls = self._fetch({"quoteType": "MUTUALFUND"}, ops=0.0008,
                                 overview={"categoryName": "Target-Date 2055"})
        self.assertAlmostEqual(out["expense_ratio"], 0.0008)
        self.assertEqual(out["category"], "Target-Date 2055")
        self.assertEqual(calls, ["funds_data"])
        self.assertEqual(out["stock_pct"], 1.0)
        self.assertNotIn("_expense_ratio", out)
        out, _ = self._fetch({"quoteType": "ETF", "category": "Large Blend",
                              "netExpenseRatio": 0.03}, overview={"categoryName": "Other"})
        self.assertEqual(out["category"], "Large Blend")         # info's own category kept

    def test_unknown_or_implausible_stays_blank_and_stocks_have_none(self):
        out, _ = self._fetch({"quoteType": "ETF"})
        self.assertIsNone(out["expense_ratio"])
        out, _ = self._fetch({"quoteType": "ETF", "annualReportExpenseRatio": 3.0})  # not 300%
        self.assertIsNone(out["expense_ratio"])
        out, calls = self._fetch({"quoteType": "EQUITY", "netExpenseRatio": 0.5})
        self.assertIsNone(out["expense_ratio"])
        self.assertEqual(calls, [])


class ExpenseRatioStorageTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_fees_")
        self.db = os.path.join(self.dir, "test.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_old_database_gains_the_column_and_it_round_trips(self):
        conn = portfolio.connect(self.db)   # then made as a database from before fees
        conn.execute("ALTER TABLE security_info DROP COLUMN expense_ratio")
        conn.commit()
        conn.close()
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        with contextlib.closing(sqlite3.connect(self.db)) as raw:
            cols = [r[1] for r in raw.execute("PRAGMA table_info(security_info)")]
        self.assertNotIn("expense_ratio", cols)
        conn = portfolio.connect(self.db)                 # the back-fill adds it again
        sync_history.upsert_info(conn, "VOO", {"quote_type": "ETF", "expense_ratio": 0.0003})
        sync_history.upsert_info(conn, "AAPL", {"quote_type": "EQUITY"})
        conn.commit()
        conn.close()
        info = perf.security_info(self.db, ["VOO", "AAPL"])
        self.assertAlmostEqual(info["VOO"]["expense_ratio"], 0.0003)
        self.assertIsNone(info["AAPL"]["expense_ratio"])


class FeeCheckPageTests(unittest.TestCase):
    """Home shows the Fee check card and its window; Learn the basics links it.
    (AppTest draws the window when its button is clicked; a real browser
    check is still worth doing for the look.)"""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="pt_fees_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        conn = portfolio.connect(cls.db)
        cls.uid = auth.create_user(conn, "alice", "pw-123456")
        sample_data.load(conn, cls.uid)
        for t, qt, cat, er in (("VTI", "ETF", "Large Blend", 0.0003),
                               ("BND", "ETF", "Intermediate Core Bond", 0.0003),
                               ("VOO", "ETF", "Large Blend", 0.0003),
                               ("SCHD", "ETF", "Large Value", 0.0006),
                               ("VXUS", "ETF", "Foreign Large Blend", None),
                               ("AAPL", "EQUITY", None, None)):
            sync_history.upsert_info(conn, t, {"quote_type": qt, "category": cat,
                                               "expense_ratio": er})
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _run(self, page, **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": self.uid, "username": "alice", "page": page,
                     "auto_backfilled": True, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items() if k != "FINNHUB_API_KEY"}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1")
        # no prices from the internet: Yahoo and any socket fail at once
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline_net.connect):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    def _html(self, at):
        return " ".join(h.proto.body for h in at.get("html"))

    def test_home_card_and_window(self):
        with self._run("Dashboard") as at:
            self.assertIn("Fee check", self._html(at))
            self.assertRegex(self._html(at), r"about <span style='font-weight:600'>\$\d+</span> a year")
            self.assertIn("1 fund not known yet", self._html(at))
            at.button(key="fees_open").click().run()
            self.assertEqual([m.label for m in at.metric][:3],
                             ["Each year, at today's value", "Over 10 years", "Over 30 years"])
            text = " ".join(m.value for m in at.markdown)
            self.assertIn("grew 6% a year", text)
            self.assertIn("We don't know the yearly fee for VXUS", text)
            self.assertIn("Single stocks have no yearly fund fee, so AAPL is left out", text)
            table = next(d.value for d in at.dataframe if "Fund" in d.value.columns)
            self.assertEqual(list(table["Fund"].str.split(" - ").str[0]),
                             ["VTI", "VOO", "BND", "SCHD"])
            self.assertTrue(table.iloc[:, -1].str.startswith("around 0.").all())
            self.assertTrue(at.session_state["dialog_open"])   # live prices wait

    def test_hidden_amounts_are_masked(self):
        with self._run("Dashboard", hide_amounts=True) as at:
            self.assertIn("about <span style='font-weight:600'>•••</span> a year", self._html(at))
            at.button(key="fees_open").click().run()
            self.assertTrue(all(m.value == "•••" for m in at.metric[:3]))

    def test_learn_the_basics_opens_it(self):
        with self._run("Get started", gs_at="basics", fs_hide=True) as at:
            at.button(key="fees_learn_open").click().run()
            self.assertIn("Over 30 years", [m.label for m in at.metric])


if __name__ == "__main__":
    unittest.main()
