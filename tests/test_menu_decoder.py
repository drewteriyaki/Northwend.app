"""The 401(k) Menu Decoder (ROADMAP R5, menu_decoder.py, views/menu_decoder.py):
reading pasted plan menus in several recordkeepers' styles, matching by ticker
and by name (conservatively), honest "couldn't identify" rows, the fee
arithmetic, the pasted order, nothing written but the R5 numbers, the flag,
and the window in the app.

The menus below are made up, in the styles of each recordkeeper's enrolment
pages (listed alphabetically - none is primary). The fund data is fixture data
for these tests, not a statement of any fund's real fee.

    python -m unittest discover -s tests        (from the repo root)
"""

import contextlib
import json
import logging
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
import feature_counts  # noqa: E402
import flags  # noqa: E402
import menu_decoder as md  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sample_data  # noqa: E402
import sync_history  # noqa: E402

# fixture fund data, as security_info keeps it (expense_ratio a fraction)
INFO = [
    {"ticker": "FXAIX", "name": "Fidelity 500 Index Fund", "quote_type": "MUTUALFUND",
     "category": "Large Blend", "expense_ratio": 0.00015, "fetched_at": "2026-10-03 02:00:00"},
    {"ticker": "VBTLX", "name": "Vanguard Total Bond Market Ind", "quote_type": "MUTUALFUND",
     "category": "Intermediate Core Bond", "expense_ratio": 0.0004,
     "fetched_at": "2026-10-03 02:00:00"},
    {"ticker": "VFIFX", "name": "Vanguard Target Retirement 2050 Fund",
     "quote_type": "MUTUALFUND", "category": "Target-Date 2050", "expense_ratio": 0.0008,
     "fetched_at": "2026-10-02 02:00:00"},
    {"ticker": "RERGX", "name": "American Funds EuroPacific Growth Fund Class R-6",
     "quote_type": "MUTUALFUND", "category": "Foreign Large Growth", "expense_ratio": 0.0047,
     "fetched_at": "2026-10-02T02:00:00Z"},
    {"ticker": "RWMGX", "name": "American Funds Washington Mutual Investors Fund Class R-6",
     "quote_type": "MUTUALFUND", "category": "Large Value", "expense_ratio": 0.0027,
     "fetched_at": "2026-10-02T02:00:00Z"},
    {"ticker": "SPAXX", "name": "Fidelity Government Money Market Fund",
     "quote_type": "MONEYMARKET", "category": None, "expense_ratio": 0.0042,
     "fetched_at": "2026-10-02"},
    {"ticker": "AAPL", "name": "Apple Inc.", "quote_type": "EQUITY", "category": None,
     "expense_ratio": None, "fetched_at": "2026-10-02"},
]

# ---- made-up menus, one per recordkeeper style (alphabetical) --------------- #
EMPOWER = """Investment Options
Asset Class: Large Cap
American Funds Washington Mutual Investors Fund Class R-6
Ticker: RWMGX
Gross/Net Expense Ratio: 0.27% / 0.27%
Asset Class: International
American Funds EuroPacific Growth R6
Ticker: RERGX
Gross/Net Expense Ratio: 0.47% / 0.47%
Asset Class: Stable Value
Empower Stable Value Fund
Gross/Net Expense Ratio: 0.45% / 0.40%
Your balance: $12,345.67
"""

FIDELITY_NETBENEFITS = """Investment Choices
Stock Investments
FID 500 INDEX (FXAIX)
Large Blend   Expense Ratio 0.015%   1 Yr 24.95%   5 Yr 14.50%
FID TOTAL INTL INDEX (FTIHX)
Foreign Large Blend   Expense Ratio 0.06%
Blended Investments
FID FREEDOM IDX 2050 INV (FIPFX)
Target-Date 2050   Expense Ratio 0.12%
Bond Investments
FID US BOND IDX (FXNAX)
Short-Term Investments
FIMM GOVT PORT INST (FRGXX)
"""

PRINCIPAL = """Investment Option | Ticker | Total Annual Operating Expense
Principal LifeTime Hybrid 2050 CIT | N/A | 0.37%
Vanguard 500 Index Fund Admiral Shares | VFIAX | 0.04%
Principal MidCap Fund R6 |  | 0.59%
Principal Stable Value Fund | N/A | 0.35%
"""

T_ROWE = """T. Rowe Price Retirement 2050 Fund - I Class (TRZQX)    Net expense ratio: 0.34%   Gross expense ratio: 0.41%
T. Rowe Price Blue Chip Growth Fund - I Class (TRZBX)    Gross/Net 0.56%/0.56%
T. Rowe Price New Income Fund - I Class
Vanguard Total International Stock Index Fund Admiral Shares    0.12%
T. Rowe Price U.S. Treasury Money Fund - I Class
"""

VANGUARD = """Fund name\tTicker\tExpense ratio
Vanguard Target Retirement 2050 Trust II\t\t0.075%
Vanguard Institutional Index Fund Institutional Plus Shares\tVIIIX\t0.02%
Vanguard Total Bond Market Index Fund Admiral Shares\tVBTLX\t0.05%
Vanguard Federal Money Market Fund\tVMFXX\t0.11%
"""


def _rows(text, info=INFO):
    return md.decode(text, info)["rows"]


class RecordkeeperMenuTests(unittest.TestCase):
    """Each style read into fund lines: the right count, tickers, pasted
    fees, headings left out, and no dollar amount anywhere."""

    def test_empower(self):
        r = md.decode(EMPOWER, INFO)
        self.assertEqual(r["lines"], 3)
        self.assertEqual(r["skipped"], ["Investment Options"])
        a, b, c = r["rows"]
        self.assertEqual((a["status"], a["symbol"], a["fee"], a["fee_source"]),
                         ("ticker", "RWMGX", 0.0027, "pasted"))
        self.assertEqual((b["status"], b["symbol"], b["kind"]), ("ticker", "RERGX", "intl_stock"))
        # the trust-style plan option nobody here knows: honest, its fee as pasted (net)
        self.assertEqual((c["status"], c["kind"], c["kind_from"]),
                         ("unidentified", "stable_value", "name"))
        self.assertAlmostEqual(c["fee"], 0.0040)
        self.assertNotIn("12,345", json.dumps(r))   # the balance is never carried along

    def test_fidelity_netbenefits(self):
        r = md.decode(FIDELITY_NETBENEFITS, INFO)
        self.assertEqual([x["pasted_ticker"] for x in r["rows"]],
                         ["FXAIX", "FTIHX", "FIPFX", "FXNAX", "FRGXX"])
        self.assertEqual(r["skipped"], ["Investment Choices", "Stock Investments",
                                        "Blended Investments", "Bond Investments",
                                        "Short-Term Investments"])
        fx, ft, fi, fn, fr = r["rows"]
        # the category-and-fee line under each fund belongs to it; returns aren't fees
        self.assertEqual((fx["status"], fx["fee"], fx["fee_source"], fx["kind"]),
                         ("ticker", 0.00015, "pasted", "us_stock"))
        self.assertEqual((ft["status"], ft["fee"], ft["kind"]), ("ticker", 0.0006, "intl_stock"))
        self.assertEqual((fi["status"], fi["why"], fi["kind"], fi["kind_from"]),
                         ("unidentified", "unknown_ticker", "target_date", "name"))
        self.assertAlmostEqual(fi["fee"], 0.0012)
        self.assertEqual((fn["status"], fn["kind"], fn["fee"]), ("ticker", "bond", None))
        self.assertEqual((fr["status"], fr["fee"]), ("unidentified", None))

    def test_principal(self):
        r = md.decode(PRINCIPAL, INFO)
        self.assertEqual(r["lines"], 4)
        cit, vfiax, mid, stable = r["rows"]
        self.assertEqual((cit["status"], cit["kind"], cit["fee"]),
                         ("unidentified", "target_date", 0.0037))
        self.assertEqual((vfiax["status"], vfiax["symbol"], vfiax["fee"]),
                         ("ticker", "VFIAX", 0.0004))
        self.assertEqual(vfiax["name"], "Vanguard 500 Index Fund Admiral Shares")
        # an empty ticker cell keeps the fee column in its place
        self.assertEqual((mid["pasted"], mid["status"], mid["fee"]),
                         ("Principal MidCap Fund R6", "unidentified", 0.0059))
        self.assertEqual((stable["kind"], stable["fee"]), ("stable_value", 0.0035))

    def test_t_rowe_price(self):
        r = md.decode(T_ROWE, INFO)
        self.assertEqual(r["lines"], 5)
        ret, blue, new_income, vtiax, money = r["rows"]
        self.assertAlmostEqual(ret["fee"], 0.0034)        # net, not gross
        self.assertAlmostEqual(blue["fee"], 0.0056)       # "Gross/Net a/b": b
        self.assertEqual(ret["pasted"], "T. Rowe Price Retirement 2050 Fund - I Class")
        self.assertEqual((new_income["status"], new_income["kind"]), ("unidentified", None))
        # identified by its full name; a bare "0.12%" might be a return, so not taken
        self.assertEqual((vtiax["status"], vtiax["symbol"], vtiax["fee"]),
                         ("name", "VTIAX", None))
        self.assertEqual(money["kind"], "money_market")

    def test_vanguard(self):
        r = md.decode(VANGUARD, INFO)
        self.assertEqual(r["lines"], 4)
        trust, viiix, vbtlx, vmfxx = r["rows"]
        # a trust isn't the mutual fund of the same name: never matched to VFIFX
        self.assertEqual((trust["status"], trust["symbol"], trust["kind"], trust["fee"]),
                         ("unidentified", None, "target_date", 0.00075))
        self.assertEqual((viiix["status"], viiix["why"]), ("unidentified", "unknown_ticker"))
        # the plan's pasted fee shown; the data's different one noted with its date
        self.assertEqual((vbtlx["status"], vbtlx["fee"], vbtlx["fee_source"]),
                         ("ticker", 0.0005, "pasted"))
        self.assertEqual((vbtlx["data_fee"], vbtlx["fee_date"]), (0.0004, "2026-10-03"))
        self.assertEqual(vmfxx["kind"], "money_market")

    def test_a_long_paste_is_cut_and_said(self):
        text = "\n".join(f"Made Up Fund Number {i}" for i in range(md.MAX_LINES + 5))
        r = md.decode(text, INFO)
        self.assertEqual(r["lines"], md.MAX_LINES)
        self.assertTrue(r["truncated"])

    def test_blank_and_noise_only(self):
        self.assertEqual(md.decode("", INFO)["rows"], [])
        self.assertEqual(md.decode("\n  \n1 Yr 4.2%\n$1,000.00\n", INFO)["rows"], [])


class MatchingTests(unittest.TestCase):
    def test_by_ticker_from_the_data_and_from_known_names(self):
        a, b = _rows("Fidelity 500 Index Fund (FXAIX)\nFidelity Total Intl Index (FTIHX)")
        self.assertEqual((a["status"], a["fee"], a["fee_source"], a["fee_date"]),
                         ("ticker", 0.00015, "data", "2026-10-03"))
        # FTIHX is in ticker_search.COMMON: identified, but no fee without fund data
        self.assertEqual((b["status"], b["fee"], b["fee_source"]), ("ticker", None, None))

    def test_ticker_forms(self):
        self.assertEqual(md.tickers_in("Ticker: VFIAX"), ["VFIAX"])
        self.assertEqual(md.tickers_in("Some Fund (ABCDX)"), ["ABCDX"])
        self.assertEqual(md.tickers_in("Vanguard Admiral VBTLX 0.05%"), ["VBTLX"])
        self.assertEqual(md.tickers_in("Total Stock ETF  VTI", known={"VTI"}), ["VTI"])
        # capitals that are part of a name are not tickers
        self.assertEqual(md.tickers_in("MSCI EAFE INDEX (CIT)"), [])
        self.assertEqual(md.tickers_in("Ticker: N/A"), [])
        self.assertEqual(md.tickers_in("S&P 500 INDEX", known={"SP", "P"}), [])
        # an all-capitals line: a short known code isn't picked out of the name
        self.assertEqual(md.tickers_in("VANGUARD TOTAL BOND MARKET", known={"BOND", "TOTAL"}),
                         [])

    def test_by_name_after_spelling_out_abbreviations(self):
        for text in ("Vanguard 500 Index Fund Admiral Shares", "Vanguard 500 Idx Adm",
                     "VANGUARD 500 INDEX ADMIRAL", "Vanguard® 500 Index Fund - Admiral Shares"):
            with self.subTest(text):
                (r,) = _rows(text)
                self.assertEqual((r["status"], r["symbol"]), ("name", "VFIAX"))

    def test_close_is_not_a_match(self):
        for text in ("Vanguard 500 Index Fund",                     # no share class
                     "Vanguard 500 Index Fund Investor Shares",     # another class
                     "Vanguard Target Retirement 2050 Trust",       # a trust, not VFIFX
                     "Vanguard Target Retirement 2050 Fund CIT",
                     "Vanguard Total Bond Market Index Fund Admiral Shares",   # data name cut short
                     "Fidelity 500"):
            with self.subTest(text):
                (r,) = _rows(text)
                self.assertEqual((r["status"], r["why"], r["symbol"], r["fee"]),
                                 ("unidentified", "no_match", None, None))

    def test_two_funds_with_one_name_is_no_guess(self):
        info = INFO + [{"ticker": "FAKEX", "name": "Fidelity 500 Index Fund",
                        "quote_type": "MUTUALFUND", "expense_ratio": 0.001}]
        (r,) = _rows("Fidelity 500 Index Fund", info)
        self.assertEqual((r["status"], r["why"]), ("unidentified", "several"))
        (r,) = _rows("Fidelity 500 Index Fund")
        self.assertEqual((r["status"], r["symbol"]), ("name", "FXAIX"))

    def test_a_name_that_contradicts_its_ticker(self):
        (r,) = _rows("Zephyr Stable Value Account (FXAIX)")
        self.assertEqual((r["status"], r["why"], r["fee"]),
                         ("unidentified", "name_and_ticker_differ", None))

    def test_two_known_tickers_on_one_line(self):
        (r,) = _rows("Fidelity 500 Index Fund (FXAIX) (VFIAX)")
        self.assertEqual((r["status"], r["why"]), ("unidentified", "several_tickers"))

    def test_single_stocks_by_ticker_only(self):
        (r,) = _rows("Apple Inc. Company Stock (AAPL)")
        self.assertEqual((r["status"], r["kind"], r["fee"]), ("ticker", "company_stock", None))
        (r,) = _rows("Apple Inc.")
        self.assertEqual(r["status"], "unidentified")

    def test_unidentified_rows_say_so_plainly(self):
        table = md.table(md.decode("Mystery Growth Collective Trust", INFO))
        self.assertEqual(table[0]["What it is"],
                         "Couldn't identify this one - check the plan's fund fact sheet")
        self.assertEqual(table[0]["Yearly fee"], "—")


class KindTests(unittest.TestCase):
    def test_kinds_from_the_data(self):
        kinds = {r["symbol"]: r["kind"] for r in _rows("\n".join(
            f"{r['name']} ({r['ticker']})" for r in INFO))}
        self.assertEqual(kinds, {"FXAIX": "us_stock", "VBTLX": "bond", "VFIFX": "target_date",
                                 "RERGX": "intl_stock", "RWMGX": "us_stock",
                                 "SPAXX": "money_market",
                                 "AAPL": "company_stock"})

    def test_kinds_from_plain_words_in_a_name_only(self):
        for name, kind in (("Acme Stable Value Fund", "stable_value"),
                           ("Acme Government Money Market", "money_market"),
                           ("Acme Lifetime 2045 Trust", "target_date"),
                           ("Acme Core Bond Collective", "bond"),
                           ("Acme International Equity Index", "intl_stock"),
                           ("Acme S&P 500 Index Trust", "us_stock"),
                           ("Acme Global Real Estate", None),
                           ("Acme Growth Collective", None)):
            with self.subTest(name):
                self.assertEqual(md.kind_from_name(name), kind)

    def test_labels(self):
        self.assertEqual(md.kind_label("us_stock", "Fidelity 500 Index Fund"),
                         "US stock index fund")
        self.assertEqual(md.kind_label("bond", "Core Bond Fund"), "Bond fund")
        self.assertEqual(md.kind_label("stable_value", "Stable Value Index"), "Stable value fund")
        table = md.table(md.decode("Acme Stable Value Fund", INFO))
        self.assertEqual(table[0]["Kind"], "Stable value fund (going by its name)")
        for kind, (label, words) in md.KINDS.items():
            self.assertTrue(label and words, kind)


class FeeTests(unittest.TestCase):
    def test_only_labelled_percentages_are_fees(self):
        self.assertAlmostEqual(md.fees_in("Expense ratio: 0.04%"), 0.0004)
        self.assertAlmostEqual(md.fees_in("ER .02%"), 0.0002)
        self.assertAlmostEqual(md.fees_in("Gross 0.50%  Net 0.45%"), 0.0045)
        self.assertAlmostEqual(md.fees_in("Gross expense ratio 0.50%, net expense ratio 0.45%"),
                               0.0045)
        self.assertAlmostEqual(md.fees_in("Expense Ratio (Gross/Net): 0.52% / 0.45%"), 0.0045)
        self.assertAlmostEqual(md.fees_in("Gross expense ratio 0.50%"), 0.005)
        self.assertAlmostEqual(md.fees_in("Expense ratio 0.04%   1 Yr 12.30%"), 0.0004)
        for text in ("0.04%", "1 Yr 0.80%  5 Yr 2.1%", "7-day yield 4.21%",
                     "Expense ratio 12%", "Your election: 6%"):
            with self.subTest(text):
                self.assertIsNone(md.fees_in(text))

    def test_the_yearly_fee_on_a_year_of_contributions(self):
        self.assertAlmostEqual(md.yearly_dollars(300, 0.0004), 1.44)     # 300 x 12 x 0.04%
        self.assertAlmostEqual(md.yearly_dollars(500, 0.0075), 45.0)
        self.assertIsNone(md.yearly_dollars(None, 0.001))
        self.assertIsNone(md.yearly_dollars(300, None))
        self.assertIsNone(md.yearly_dollars(0, 0.001))
        self.assertEqual(md.fmt_dollars(1.44), "$1.44")
        self.assertEqual(md.fmt_dollars(1250.0), "$1,250")
        self.assertEqual(md.fmt_dollars(None), "—")
        self.assertEqual(md.dollars_column(300.0), "Fee on a year of $300 a month")

    def test_the_table_says_where_each_fee_comes_from(self):
        r = md.decode("Fidelity 500 Index Fund (FXAIX)\nAcme Stable Value  Expense ratio 0.4%\n"
                      "Acme Growth Collective", INFO)
        t = md.table(r, 300)
        self.assertEqual([x["Where the fee comes from"] for x in t],
                         ["Yahoo Finance, Oct 3, 2026", "As you pasted it", "—"])
        self.assertEqual([x["Fee on a year of $300 a month"] for x in t],
                         ["$0.54", "$14.40", "—"])
        self.assertEqual([x["Yearly fee"] for x in t], ["0.015%", "0.40%", "—"])
        self.assertNotIn("Fee on a year of $300 a month", md.table(r, None)[0])


class OrderAndWordingTests(unittest.TestCase):
    """The table is the person's own list: never sorted by fee or anything
    Northwend works out, never ranked or marked."""

    MENU = ("Acme Pricey Growth Fund  Expense ratio 1.10%\n"
            "Fidelity 500 Index Fund (FXAIX)\n"
            "Acme Middle Fund  Expense ratio 0.50%\n"
            "Vanguard Target Retirement 2050 Fund (VFIFX)\n"
            "Mystery Collective\n"
            "Acme Bond Index  Expense ratio 0.02%\n")

    def test_rows_keep_the_pasted_order(self):
        r = md.decode(self.MENU, INFO)
        self.assertEqual([x["line"] for x in r["rows"]], [1, 2, 3, 4, 5, 6])
        self.assertEqual([x["pasted"] for x in r["rows"]],
                         ["Acme Pricey Growth Fund", "Fidelity 500 Index Fund",
                          "Acme Middle Fund", "Vanguard Target Retirement 2050 Fund",
                          "Mystery Collective", "Acme Bond Index"])
        fees_shown = [x["fee"] for x in r["rows"]]
        self.assertNotEqual(fees_shown, sorted(fees_shown, key=lambda f: (f is None, f or 0)))
        self.assertEqual([x["#"] for x in md.table(r, 100)], [1, 2, 3, 4, 5, 6])
        # reversed paste, reversed table
        back = md.decode("\n".join(reversed(self.MENU.strip().splitlines())), INFO)
        self.assertEqual([x["pasted"] for x in back["rows"]],
                         [x["pasted"] for x in reversed(r["rows"])])

    def test_no_row_says_best_cheapest_or_recommended(self):
        cells = json.dumps(md.table(md.decode(self.MENU, INFO), 250)).lower()
        for word in ("best", "cheapest", "recommend", "top pick", "winner", "lowest", "★"):
            self.assertNotIn(word, cells)

    def test_the_window_never_sorts_the_table(self):
        with open(os.path.join(REPO, "views", "menu_decoder.py"), encoding="utf-8") as fh:
            view = fh.read()
        self.assertIn("menu_decoder.table(result, monthly)", view)
        self.assertNotIn("sort_values", view)
        self.assertIn("st.table(", view)            # a plain table: no click-to-sort
        self.assertNotIn("st.dataframe(", view)
        with open(os.path.join(REPO, "menu_decoder.py"), encoding="utf-8") as fh:
            module = fh.read()
        self.assertNotIn(".sort(", module)
        self.assertNotIn("sorted(result", module)


class NothingKeptTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_decoder_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.db = os.path.join(self.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.conn = portfolio.connect(self.db)
        self.addCleanup(self.conn.close)
        for r in INFO:
            sync_history.upsert_info(self.conn, r["ticker"], r)
        self.conn.commit()

    def test_reading_the_fund_data_is_one_select_and_nothing_is_logged(self):
        raw = sqlite3.connect(self.db)
        raw.row_factory = sqlite3.Row
        self.addCleanup(raw.close)
        seen = []
        raw.set_trace_callback(seen.append)
        with self.assertNoLogs(level=logging.DEBUG):
            known = md.known_funds(raw)
            result = md.decode(VANGUARD + EMPOWER, known)
            md.table(result, 300)
        self.assertEqual(len(seen), 1)
        self.assertTrue(seen[0].lstrip().upper().startswith("SELECT"), seen[0])
        self.assertEqual(result["rows"][2]["symbol"], "VBTLX")
        self.assertFalse(raw.in_transaction)

    def test_the_counts_are_numbers_only(self):
        result = md.decode(EMPOWER, INFO)
        saved = md.add_counts({"hide_amounts": True}, result)
        self.assertEqual(saved[md.PREF_COUNTS], {"decodes": 1, "lines": 3, "identified": 2})
        self.assertTrue(saved["hide_amounts"])
        again = md.add_counts(saved, md.decode(VANGUARD, INFO))
        self.assertEqual(again[md.PREF_COUNTS], {"decodes": 2, "lines": 7, "identified": 3})
        text = json.dumps(again)
        for word in ("Empower", "RERGX", "Stable", "Vanguard"):
            self.assertNotIn(word, text)
        self.assertIsNone(md.counts_in({}))
        self.assertIsNone(md.counts_in({md.PREF_COUNTS: "junk"}))


class FeatureCountTests(unittest.TestCase):
    def _people(self, n, lines=10, identified=7, **extra):
        return [{md.PREF_COUNTS: {"decodes": 1, "lines": lines, "identified": identified},
                 **extra} for _ in range(n)]

    def test_totals_only_for_a_group_of_twenty(self):
        self.assertIsNone(feature_counts.decoder_totals(self._people(19)))
        got = feature_counts.decoder_totals(self._people(20) + [{}])
        self.assertEqual(got, {"people": 20, "decodes": 20, "lines": 200, "identified": 140})

    def test_people_who_left_themselves_out_are_never_counted(self):
        everyone = self._people(20) + self._people(5, **{feature_counts.PREF_OFF: True})
        self.assertEqual(feature_counts.decoder_totals(everyone)["people"], 20)
        self.assertIsNone(feature_counts.decoder_totals(
            self._people(19) + self._people(5, **{feature_counts.PREF_OFF: True})))

    def test_from_the_database_settings_only(self):
        d = tempfile.mkdtemp(prefix="pt_decoder_fc_")
        self.addCleanup(shutil.rmtree, d, True)
        db = os.path.join(d, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(db))
        c = portfolio.connect(db)
        self.addCleanup(c.close)
        for i in range(21):
            uid = auth.create_user(c, f"person{i}", "pw-123456")
            prefs.save(c, uid, {md.PREF_COUNTS: {"decodes": 2, "lines": 10, "identified": 5}})
        self.assertEqual(feature_counts.decoder(c),
                         {"people": 21, "decodes": 42, "lines": 210, "identified": 105})


class FlagTests(unittest.TestCase):
    def test_the_feature_owns_the_view_and_is_off_unless_set(self):
        self.assertEqual(flags.FEATURES["decoder_401k"]["view"], "menu_decoder")
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": ""}), \
                unittest.mock.patch.object(flags, "_secret", lambda name: None):
            self.assertFalse(flags.on("decoder_401k"))
            self.assertFalse(flags.view_on("menu_decoder"))
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": "decoder_401k"}):
            self.assertTrue(flags.on("decoder_401k"))
            self.assertTrue(flags.view_on("menu_decoder"))


# --------------------------------------------------------------------------- #
# the window in the app
# --------------------------------------------------------------------------- #
APP_MENU = ("Fidelity 500 Index Fund (FXAIX)\n"
            "Zephyr Quiet Harbor Stable Value Fund  Expense ratio 0.40%\n"
            "Vanguard Target Retirement 2050 Trust II\n")


class DecoderPageTests(unittest.TestCase):
    """The card beside the Free money check on Plan's Contributions tab, the
    window, the table and what's kept. (AppTest draws a window in the full run
    when its button is clicked; a real browser check is worth doing for the
    look.)"""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="pt_decoder_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        conn = portfolio.connect(cls.db)
        cls.uid = auth.create_user(conn, "alice", "pw-123456")
        sample_data.load(conn, cls.uid)
        for r in INFO:
            sync_history.upsert_info(conn, r["ticker"], r)
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _app(self, flag="decoder_401k"):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": self.uid, "username": "alice", "page": "Plan",
                     "auto_backfilled": True}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items() if k != "FINNHUB_API_KEY"}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", NORTHWEND_FLAGS=flag)
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline_net.connect):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    def _dump(self):
        c = sqlite3.connect(self.db)
        try:
            return {line for line in c.iterdump()}
        finally:
            c.close()

    def _prefs(self):
        c = portfolio.connect(self.db)
        try:
            return prefs.load(c, self.uid)
        finally:
            c.close()

    def test_off_there_is_no_card(self):
        with self._app(flag="") as at:
            keys = [b.key for b in at.button]
            self.assertIn("fm_open_plan", keys)           # the Free money check stays
            self.assertNotIn("md_open_plan", keys)
            self.assertNotIn("Decode a 401(k) menu", " ".join(m.value for m in at.markdown))

    def test_paste_describe_and_nothing_kept_but_numbers(self):
        before = self._dump()
        with self._app() as at:
            self.assertIn("md_open_plan", [b.key for b in at.button])
            at.button(key="md_open_plan").click().run()
            self.assertIn("md_text", [t.key for t in at.text_area])
            at.text_area(key="md_text").input(APP_MENU)
            at.number_input(key="md_monthly").set_value(300.0)
            at.button(key="md_go").click().run()
            self.assertEqual([e.message for e in at.exception], [])
            result = at.session_state["md_result"]
            self.assertEqual((result["lines"], result["identified"]), (3, 1))
            # the window again, from what this session holds
            at.button(key="md_open_plan").click().run()
            self.assertEqual(at.text_area(key="md_text").value, APP_MENU)
            table = at.table[0].value
            self.assertEqual(list(table.index), [1, 2, 3])
            self.assertEqual(list(table["What it is"]),
                             ["Fidelity 500 Index Fund (FXAIX)",
                              "Couldn't identify this one - check the plan's fund fact sheet",
                              "Couldn't identify this one - check the plan's fund fact sheet"])
            self.assertEqual(list(table["Fee on a year of $300 a month"]),
                             ["$0.54", "$14.40", "—"])
            text = " ".join(m.value for m in at.markdown) + " " + \
                " ".join(c.value for c in at.caption)
            self.assertIn("We identified 1 of the 3 funds you pasted", text)
            self.assertIn("It doesn't rank them or say which to choose", text)
            self.assertIn("$300 a month is $3,600 in a year", text.replace("\\$", "$"))
            self.assertIn("isn't saved and no AI reads it", text)
            for word in ("best", "cheapest", "recommend"):
                self.assertNotIn(word, table.to_string().lower())
            # (the window's own words: the rest of the Plan page is drawn around it)
            with open(os.path.join(REPO, "views", "menu_decoder.py"), encoding="utf-8") as fh:
                said = " ".join(line for line in fh.read().lower().splitlines()
                                if not line.lstrip().startswith("#"))
            for word in ("best", "cheapest", "recommend", "top pick", "lowest"):
                self.assertNotIn(word, said)
            # describing the same list again in this session isn't counted twice
            at.button(key="md_go").click().run()
        after = self._dump()
        changed = {line.split('"')[1] for line in after ^ before if line.startswith("INSERT")}
        self.assertLessEqual(changed, {"user_prefs", "login_sessions", "users"}, changed)
        everything = "\n".join(after)
        for pasted in ("Zephyr Quiet Harbor", "Trust II"):
            self.assertNotIn(pasted, everything)
        self.assertEqual(self._prefs()[md.PREF_COUNTS],
                         {"decodes": 1, "lines": 3, "identified": 1})

    def test_left_out_of_feature_counts_nothing_is_counted(self):
        c = portfolio.connect(self.db)
        try:
            saved = prefs.load(c, self.uid)
            saved.pop(md.PREF_COUNTS, None)
            prefs.save(c, self.uid, {**saved, feature_counts.PREF_OFF: True})
        finally:
            c.close()
        self.addCleanup(self._forget_opt_out)
        with self._app() as at:
            at.button(key="md_open_plan").click().run()
            at.text_area(key="md_text").input("Acme Growth Collective")
            at.button(key="md_go").click().run()
            self.assertEqual(at.session_state["md_result"]["lines"], 1)
        self.assertNotIn(md.PREF_COUNTS, self._prefs())

    def _forget_opt_out(self):
        c = portfolio.connect(self.db)
        try:
            saved = prefs.load(c, self.uid)
            saved.pop(feature_counts.PREF_OFF, None)
            prefs.save(c, self.uid, saved)
        finally:
            c.close()


if __name__ == "__main__":
    unittest.main()
