"""The Fact Sheet Decoder (ROADMAP R6, fact sheets first; factsheet_decoder.py,
views/factsheet_decoder.py): reading made-up fact sheets in four layouts,
honest "couldn't find" rows, the fee arithmetic, the statement guard (a
statement is never read, shown or kept), the words it never uses, nothing
written, the flag, and the window in the app.

Every fund, ticker, person and address below is made up for these tests.

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
from datetime import date

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import auth  # noqa: E402
import factsheet_decoder as fs  # noqa: E402
import flags  # noqa: E402
import portfolio  # noqa: E402
import sample_data  # noqa: E402

TODAY = date(2026, 10, 6)

# "Label value" lines, a heading over a list of holdings
SHEET_LINES = """Example Total Stock Market Index Fund Admiral Shares
Fact sheet | June 30, 2026
Investment objective
Example Total Stock Market Index Fund seeks to track the performance of a benchmark index
that measures the investment return of the overall stock market.
Fund facts
Ticker symbol VXTSX
Expense ratio 0.04%
Inception date 11/13/2000
Asset class Domestic Stock - General
Benchmark CRSP US Total Market Index
Number of stocks 3,512
Top 10 holdings as % of total net assets 31.4%
Top 10 holdings
Example Software Corp. 6.8%
Sample Devices Inc. 5.9%
"""

# "Label: value", a gross/net fee, the ticker beside the name, a company address
SHEET_COLONS = """EXAMPLE FUNDS
Example Contrafund Growth Portfolio (EXCFX)
Quarterly fund fact sheet - as of 6/30/2026
Fund Information
Fund Inception: 05/17/1967
Morningstar Category: Large Growth
Benchmark: Russell 1000 Growth Index
Gross/Net Expense Ratio: 0.52% / 0.45%
Total Number of Holdings: 342
% of Fund in Top Ten Holdings: 48.2%
Strategy
The portfolio managers select companies with above-average growth potential.
Example Funds
PO Box 1100
Valley Forge, PA 19482
"""

# a row of labels over a row of values (tabs), the ticker after the exchange,
# a label alone with its value under it
SHEET_TABLE = ("Example Global Bond ETF\n"
               "NYSE Arca: EXGB\n"
               "Key facts\n"
               "Fund inception\tExpense ratio\tNumber of holdings\tBenchmark\n"
               "03/04/2015\t0.07%\t10,234\tExample Global Aggregate Bond Index\n"
               "The ETF seeks to track the investment results of an index composed of "
               "investment-grade bonds from around the world.\n"
               "Asset class\n"
               "Fixed Income\n")

# columns side by side, and most fields missing
SHEET_SPARSE = """Example Dividend Opportunities Fund
An actively managed fund investing in companies that pay dividends.
The fund's expense ratio is 0.85%.
Learn more before adding it to your account.
"""

# statement-like: a name and address, an account number, an account value
STATEMENT = """Example Brokerage
Quarterly Statement    Statement period: April 1 - June 30, 2026
Jordan Q. Quillfeather
123 Maple Street
Springfield, IL 62701
Account number: 5551-2345-9876
Total account value $84,213.55
Your holdings
Example Total Stock Market Index Fund (VXTSX)   412.338 shares   $54,120.11
Expense ratio 0.04%
"""
STATEMENT_BITS = ("Jordan", "Quillfeather", "Maple", "Springfield", "62701", "5551", "9876",
                  "84,213", "54,120", "412.338")

NEVER = ("best", "worst", "cheap", "expensive", "good", "bad", "should", "recommend",
         "great", "poor", "top pick", "winner", "high-cost", "low-cost", "★")


def _row(rows, what):
    return next(r for r in rows if r["What"] == what)


class LayoutTests(unittest.TestCase):
    def test_label_value_lines(self):
        r = fs.decode(SHEET_LINES)
        self.assertEqual(r["statement"], [])
        self.assertEqual(r["name"], "Example Total Stock Market Index Fund Admiral Shares")
        self.assertEqual(r["tickers"], ["VXTSX"])
        self.assertEqual(r["fee"], 0.0004)
        self.assertIsNone(r["gross"])
        self.assertEqual(r["management"], {"kind": "index", "from": "sheet"})
        self.assertEqual(r["asset_class"], {"stated": "Domestic Stock - General",
                                            "kind": "us_stock", "from": "sheet"})
        self.assertEqual(r["top_share"], {"pct": 31.4, "of": 10})
        self.assertEqual(r["holdings"], 3512)
        self.assertEqual(r["inception"], "11/13/2000")
        self.assertEqual(r["benchmark"], "CRSP US Total Market Index")
        self.assertEqual(r["found"], len(fs.FIELDS))

    def test_colons_gross_and_net_and_a_ticker_beside_the_name(self):
        r = fs.decode(SHEET_COLONS)
        self.assertEqual(r["statement"], [])          # a fund company's address isn't a person's
        self.assertEqual(r["name"], "Example Contrafund Growth Portfolio")
        self.assertEqual(r["tickers"], ["EXCFX"])
        self.assertEqual(r["fee"], 0.0045)            # net, what holders pay
        self.assertEqual(r["gross"], 0.0052)
        self.assertEqual(r["management"]["kind"], "active")
        self.assertEqual(r["asset_class"]["stated"], "Large Growth")
        self.assertEqual(r["asset_class"]["kind"], "us_stock")
        self.assertEqual(r["top_share"], {"pct": 48.2, "of": 10})
        self.assertEqual(r["holdings"], 342)
        self.assertEqual(r["inception"], "05/17/1967")
        self.assertEqual(r["benchmark"], "Russell 1000 Growth Index")

    def test_a_row_of_labels_over_a_row_of_values(self):
        r = fs.decode(SHEET_TABLE)
        self.assertEqual(r["name"], "Example Global Bond ETF")
        self.assertEqual(r["tickers"], ["EXGB"])
        self.assertEqual(r["fee"], 0.0007)
        self.assertEqual(r["holdings"], 10234)
        self.assertEqual(r["inception"], "03/04/2015")
        self.assertEqual(r["benchmark"], "Example Global Aggregate Bond Index")
        self.assertEqual(r["management"], {"kind": "index", "from": "sheet"})
        self.assertEqual(r["asset_class"]["stated"], "Fixed Income")
        self.assertEqual(r["asset_class"]["kind"], "bond")
        self.assertIsNone(r["top_share"])

    def test_columns_side_by_side(self):
        text = ("Example Small Cap Value Fund\n"
                "Ticker  EXSVX    Inception date  Aug 31, 1998\n"
                "Expense ratio  0.31%    Number of holdings  1,450\n"
                "Benchmark  Example Small Cap Value Index    Category  Small Value\n")
        r = fs.decode(text)
        self.assertEqual(r["tickers"], ["EXSVX"])
        self.assertEqual(r["inception"], "Aug 31, 1998")
        self.assertEqual(r["fee"], 0.0031)
        self.assertEqual(r["holdings"], 1450)
        self.assertEqual(r["benchmark"], "Example Small Cap Value Index")
        self.assertEqual(r["asset_class"]["kind"], "us_stock")
        # no "seeks to track" words, but the name says nothing either
        self.assertEqual(r["management"], {"kind": None, "from": None})

    def test_missing_fields_are_couldnt_find_rows(self):
        r = fs.decode(SHEET_SPARSE)
        self.assertEqual(r["statement"], [])   # "your account" alone isn't a statement
        self.assertEqual(r["name"], "Example Dividend Opportunities Fund")
        self.assertEqual(r["fee"], 0.0085)
        self.assertEqual(r["management"]["kind"], "active")
        rows = fs.rows(r, None, TODAY)
        self.assertEqual([x["What"] for x in rows], [fs.ROWS[f][0] for f in fs.FIELDS])
        for what in ("Ticker", "Share in its largest holdings", "Number of holdings",
                     "Inception date", "Benchmark"):
            self.assertEqual(_row(rows, what)["As the fact sheet states it"], fs.NOT_FOUND)
            self.assertTrue(_row(rows, what)["What this means"])   # still explained
        self.assertEqual(r["found"], 3)   # name, fee, index or active

    def test_an_index_fund_going_by_its_name(self):
        r = fs.decode("Example 500 Index Fund\nExpense ratio 0.02%\n")
        self.assertEqual(r["management"], {"kind": "index", "from": "name"})
        rows = fs.rows(r, None, TODAY)
        self.assertEqual(_row(rows, "Index or actively managed")["As the fact sheet states it"],
                         "Index fund (going by its name)")

    def test_a_list_under_a_heading_is_not_a_figure(self):
        text = ("Example Growth Fund\nTop 10 holdings\nExample Software Corp. 6.8%\n"
                "Number of holdings\nExample Devices 3,000 units\n")
        r = fs.decode(text)
        self.assertIsNone(r["top_share"])
        self.assertIsNone(r["holdings"])

    def test_blank_and_noise(self):
        for text in ("", "   \n\n", "12345\n%%%\n"):
            r = fs.decode(text)
            self.assertEqual(r["found"], 0)
            self.assertTrue(all(x["As the fact sheet states it"] == fs.NOT_FOUND
                                for x in fs.rows(r, 100, TODAY)))


class RowTests(unittest.TestCase):
    def test_each_row_as_the_sheet_states_it_with_what_it_means(self):
        rows = fs.rows(fs.decode(SHEET_COLONS), 300, TODAY)
        fee = _row(rows, "Yearly fee (expense ratio)")
        self.assertEqual(fee["As the fact sheet states it"],
                         "0.45% a year (before any fee waiver: 0.52%)")
        self.assertIn("$45 a year for every $10,000", fee["What this means"])
        # 300 x 12 x 0.45% = $16.20
        self.assertIn("On a year of $300 a month, about $16.20.", fee["What this means"])
        self.assertEqual(_row(rows, "What it invests in")["As the fact sheet states it"],
                         "Large Growth (a US stock fund)")
        self.assertEqual(_row(rows, "Share in its largest holdings")
                         ["As the fact sheet states it"], "48.2% in its top 10")
        self.assertIn("about 59 years ago", _row(rows, "Inception date")["What this means"])
        self.assertEqual(_row(rows, "Number of holdings")["As the fact sheet states it"], "342")

    def test_no_dollars_without_a_monthly_amount(self):
        fee = _row(fs.rows(fs.decode(SHEET_LINES), None, TODAY), "Yearly fee (expense ratio)")
        self.assertNotIn("a month", fee["What this means"])
        self.assertIn("$4 a year for every $10,000", fee["What this means"])

    def test_several_tickers_are_all_shown(self):
        r = fs.decode("Example Balanced Fund\nTicker: EXBIX, EXBAX\nCategory: Allocation--50% "
                      "to 70% Equity\n")
        self.assertEqual(r["tickers"], ["EXBIX", "EXBAX"])
        self.assertEqual(r["asset_class"]["kind"], "balanced")
        row = _row(fs.rows(r, None, TODAY), "Ticker")
        self.assertEqual(row["As the fact sheet states it"], "EXBIX, EXBAX")
        self.assertIn("one per share class", row["What this means"])


class WordingTests(unittest.TestCase):
    """Descriptive only: never a rating, a ranking or a "should"."""

    def test_nothing_it_can_show_uses_a_judging_word(self):
        shown = [fs.CALM, fs.STATEMENT_NOTE, fs.PLACEHOLDER, fs.NOT_FOUND,
                 json.dumps(fs.ROWS), json.dumps(fs.MANAGEMENT), json.dumps(fs.STATEMENT_SIGNS)]
        for sheet in (SHEET_LINES, SHEET_COLONS, SHEET_TABLE, SHEET_SPARSE):
            shown.append(json.dumps(fs.rows(fs.decode(sheet), 250, TODAY)))
        text = " ".join(shown).lower()
        for word in NEVER:
            self.assertNotRegex(text, r"\b" + word + r"\b", word)

    def test_the_window_never_judges_or_sorts(self):
        with open(os.path.join(REPO, "views", "factsheet_decoder.py"), encoding="utf-8") as fh:
            said = " ".join(line for line in fh.read().splitlines()
                            if not line.lstrip().startswith("#"))
        for word in NEVER:
            self.assertNotRegex(said.lower(), r"\b" + word + r"\b", word)
        self.assertIn("st.table(", said)              # a plain table: no click-to-sort
        self.assertNotIn("st.dataframe(", said)
        self.assertNotIn("sort", said)


class StatementGuardTests(unittest.TestCase):
    def test_a_statement_is_not_read(self):
        r = fs.decode(STATEMENT)
        self.assertEqual(set(r), {"statement"})       # nothing else comes back
        self.assertEqual(r["statement"], ["account_number", "balance", "address", "statement"])
        said = json.dumps(r) + fs.statement_signs_text(r["statement"])
        for bit in STATEMENT_BITS:
            self.assertNotIn(bit, said)

    def test_each_sign_on_its_own(self):
        cases = {
            "Example Fund\nAccount: XXXX-4821\n": ["account_number"],
            "Example Fund\nAcct # ****3307\n": ["account_number"],
            "Example Fund\nYour balance: 12,400.00\n": ["balance"],
            "Example Fund\nEnding balance 9,100\n": ["balance"],
            "Example Fund\nMs. Avery Example\n42 Birch Lane\nLakeview, OR 97630\n": ["address"],
        }
        for text, signs in cases.items():
            with self.subTest(text):
                self.assertEqual(fs.looks_like_statement(text), signs)

    def test_fact_sheets_are_not_statements(self):
        for sheet in (SHEET_LINES, SHEET_COLONS, SHEET_TABLE, SHEET_SPARSE):
            self.assertEqual(fs.looks_like_statement(sheet), [])
        # a company's mailing address, a growth-of-10,000 line, a minimum to open
        text = ("Example Index Fund\nMailing address\n100 Example Way\nMalvern, PA 19355\n"
                "Hypothetical growth of $10,000: ending value $24,310\n"
                "Minimum to open an account $3,000\n")
        self.assertEqual(fs.looks_like_statement(text), [])

    def test_a_workplace_plan_statement_is_caught(self):
        # Fresh-eyes pass Oct 8: "Total balance" / "Vested balance" (a 401(k)
        # statement's own words) weren't a balance sign, so with "participant
        # name" alone (not enough by itself) it was read as a fact sheet
        text = ("Participant name: Avery Example\nTotal balance: $45,678.90\n"
                "Vested balance: $40,000.00\n")
        self.assertIn("balance", fs.looks_like_statement(text))
        self.assertEqual(fs.looks_like_statement("Example Fund\nTotal balance 9,100\n"),
                         ["balance"])

    def test_a_long_run_of_mask_characters_is_quick(self):
        # Fresh-eyes pass Oct 8: "account" then a run of X's or stars with no
        # digits after took exponential time (26 took ~10 seconds, 40 days) -
        # Python's re holds the lock, so every visitor waited on it
        import time
        for mark in ("X", "*", "•"):
            text = "Your account " + mark * 26 + " see page 2"
            start = time.perf_counter()
            fs.looks_like_statement(text)
            self.assertLess(time.perf_counter() - start, 1.0, mark)
        # masked numbers are still found
        for text in ("Account: XXXX-XXXX-4821", "Account number ** ** 3307",
                     "acct XX XX XX 12345"):
            self.assertEqual(fs.looks_like_statement("Example Fund\n" + text), ["account_number"],
                             text)

    def test_the_signs_are_said_as_kinds_only(self):
        self.assertEqual(fs.statement_signs_text(["account_number", "balance"]),
                         "an account number and an account value or balance")


class NothingKeptTests(unittest.TestCase):
    def test_pure_no_logging(self):
        with self.assertNoLogs(level=logging.DEBUG):
            fs.rows(fs.decode(SHEET_COLONS), 100, TODAY)
            fs.decode(STATEMENT)

    def test_no_database_or_streamlit(self):
        with open(os.path.join(REPO, "factsheet_decoder.py"), encoding="utf-8") as fh:
            code = fh.read()
        for word in ("import streamlit", "import portfolio", "sqlite3", "connect(", "open(",
                     "anthropic", "ai_gateway", "requests", "urllib"):
            self.assertNotIn(word, code)


class FlagTests(unittest.TestCase):
    def test_the_feature_owns_the_view_and_is_off_unless_set(self):
        self.assertEqual(flags.FEATURES["decoder_factsheet"]["view"], "factsheet_decoder")
        self.assertEqual(flags.FEATURES["decoder_factsheet"]["gates"], ())
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": ""}), \
                unittest.mock.patch.object(flags, "_secret", lambda name: None):
            self.assertFalse(flags.on("decoder_factsheet"))
            self.assertFalse(flags.view_on("factsheet_decoder"))
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": "decoder_factsheet"}):
            self.assertTrue(flags.on("decoder_factsheet"))
            self.assertTrue(flags.view_on("factsheet_decoder"))
            self.assertFalse(flags.on("decoder_401k"))     # each its own flag


# --------------------------------------------------------------------------- #
# the window in the app
# --------------------------------------------------------------------------- #
# what the app itself writes while drawing a page (the sign-in, the example
# portfolio's value log and prices) - the decoder adds nothing, not even prefs
APP_OWN = {"login_sessions", "users", "value_log", "price_history", "sqlite_sequence"}


class FactSheetPageTests(unittest.TestCase):
    """The card on Plan's Contributions tab, the window, the table, the
    statement guard and what's kept. (A real browser check is worth doing for
    the look.)"""

    @classmethod
    def setUpClass(cls):
        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_factsheet_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        conn = portfolio.connect(cls.db)
        cls.uid = auth.create_user(conn, "alice", "pw-123456")
        sample_data.load(conn, cls.uid)
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _app(self, flag="decoder_factsheet"):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": self.uid, "username": "alice", "page": "Plan",
                     "auto_backfilled": True}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_FLAGS", "NORTHWEND_GATES")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", NORTHWEND_FLAGS=flag)
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    def _dump(self):
        c = sqlite3.connect(self.db)
        try:
            return set(c.iterdump())
        finally:
            c.close()

    @staticmethod
    def _page_text(at):
        parts = [m.value for m in at.markdown] + [c.value for c in at.caption]
        parts += [str(t.value) for t in at.text_area]
        parts += [t.value.to_string() for t in at.table]
        parts += [i.value for i in at.info] + [w.value for w in at.warning]
        return " ".join(parts).replace("\\$", "$")

    def test_off_there_is_no_card(self):
        with self._app(flag="") as at:
            keys = [b.key for b in at.button]
            self.assertIn("fm_open_plan", keys)           # the Free money check stays
            self.assertNotIn("fs_open_plan", keys)
            self.assertNotIn("fact sheet", self._page_text(at).lower())

    def test_paste_describe_and_nothing_kept(self):
        before = self._dump()
        with self._app() as at:
            self.assertIn("fs_open_plan", [b.key for b in at.button])
            self.assertNotIn("md_open_plan", [b.key for b in at.button])   # its own flag
            at.button(key="fs_open_plan").click().run()
            at.text_area(key="fs_text").input(SHEET_COLONS)
            at.number_input(key="fs_monthly").set_value(300.0)
            at.button(key="fs_go").click().run()
            # the window again, from what this session holds (AppTest draws a
            # window only on the run its button is clicked)
            at.button(key="fs_open_plan").click().run()
            result = at.session_state["fs_result"]
            self.assertEqual(result["tickers"], ["EXCFX"])
            table = at.table[0].value
            self.assertEqual(list(table.index), [fs.ROWS[f][0] for f in fs.FIELDS])
            self.assertEqual(table["As the fact sheet states it"].iloc[0],
                             "Example Contrafund Growth Portfolio")
            text = self._page_text(at)
            self.assertIn("It doesn't rate the fund or say whether to choose it", text)
            self.assertIn("no AI reads it", text)
            self.assertIn("statements aren't read yet", text.lower())
            self.assertIn("On a year of $300 a month, about $16.20.", text)
        after = self._dump()
        changed = {line.split('"')[1] for line in after ^ before if line.startswith("INSERT")}
        self.assertLessEqual(changed, APP_OWN, changed)
        everything = "\n".join(after)
        for pasted in ("Contrafund", "EXCFX", "Russell 1000"):
            self.assertNotIn(pasted, everything)

    def test_a_statement_is_stopped_and_nothing_from_it_is_shown_or_kept(self):
        before = self._dump()
        with self._app() as at:
            at.button(key="fs_open_plan").click().run()
            at.text_area(key="fs_text").input(STATEMENT)
            at.button(key="fs_go").click().run()
            # the window again, from what this session holds (AppTest draws a
            # window only on the run its button is clicked)
            at.button(key="fs_open_plan").click().run()
            text = self._page_text(at)
            self.assertIn("looks like an account statement", text)
            self.assertIn("Nothing you pasted was kept", text)
            self.assertEqual(at.text_area(key="fs_text").value, "")   # the box is cleared
            self.assertEqual(len(at.table), 0)
            for bit in STATEMENT_BITS:
                self.assertNotIn(bit, text)
            kept = " ".join(str(at.session_state[k]) for k in ("fs_result",)
                            if k in at.session_state)
            for bit in STATEMENT_BITS:
                self.assertNotIn(bit, kept)
        after = self._dump()
        changed = {line.split('"')[1] for line in after ^ before if line.startswith("INSERT")}
        self.assertLessEqual(changed, APP_OWN, changed)
        everything = "\n".join(after)
        for bit in STATEMENT_BITS:
            self.assertNotIn(bit, everything)


if __name__ == "__main__":
    unittest.main()
