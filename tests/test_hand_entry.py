"""Entering holdings by hand: the name-or-ticker lookup (ticker_search.py,
Yahoo's search stubbed - it's out of reach here), the "not sure yet" card
(starter_funds.py), and the window's rows (views/holdings_input.py).

    python -m unittest discover -s tests        (from the repo root)
"""

import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import advisor  # noqa: E402
import auth  # noqa: E402
import learn  # noqa: E402
import manual_entry  # noqa: E402
import portfolio  # noqa: E402
import starter_funds  # noqa: E402
import ticker_search  # noqa: E402
import watchlist  # noqa: E402


def q(symbol, name, kind="EQUITY", **kw):
    """A quote as Yahoo's search returns it."""
    return {"symbol": symbol, "longname": name, "quoteType": kind, **kw}


YAHOO = {   # what the stubbed search answers, by query
    "apple": [q("AAPL", "Apple Inc."), q("APLE", "Apple Hospitality REIT, Inc."),
              q("AAPL.MX", "Apple Inc."), q("APC.F", "Apple Inc.")],
    "vti": [q("VTI", "Vanguard Total Stock Market Index Fund ETF Shares", "ETF"),
            q("VTIP", "Vanguard Short-Term Inflation-Protected Securities", "ETF")],
    "VTI": [q("VTI", "Vanguard Total Stock Market Index Fund ETF Shares", "ETF")],
    "ford": [q("FORD", "Forward Industries, Inc."), q("F", "Ford Motor Company")],
    "FORD": [q("FORD", "Forward Industries, Inc."), q("F", "Ford Motor Company")],
    "vanguard total stock market": [
        q("VTI", "Vanguard Total Stock Market Index Fund ETF Shares", "ETF"),
        q("VTSAX", "Vanguard Total Stock Market Index Fund Admiral Shares", "MUTUALFUND")],
    "bitcoin": [q("BTC-USD", "Bitcoin USD", "CRYPTOCURRENCY"), q("^BTC", "Bitcoin index", "INDEX")],
}


class FakeSearch:
    """Stands in for yfinance.Search: records how it was asked."""
    calls = []

    def __init__(self, query, **kw):
        FakeSearch.calls.append((query, kw))
        if query not in YAHOO:
            self.quotes = []
        else:
            self.quotes = YAHOO[query]


def stub(query):
    """ticker_search.yahoo_search's answer for the stubbed results."""
    return ticker_search.yahoo_search(query, raw=lambda s, t: YAHOO.get(s, []))


class TickerSearchTests(unittest.TestCase):
    def setUp(self):
        ticker_search.clear_cache()
        self.addCleanup(ticker_search.clear_cache)

    def test_an_exact_ticker_is_taken_as_is(self):
        r = ticker_search.resolve("VTI", search=stub)
        self.assertEqual((r["status"], r["symbol"], r["kind"]), ("ticker", "VTI", "ETF"))
        self.assertIn("Vanguard Total Stock Market", r["name"])
        r = ticker_search.resolve("vti", search=stub)   # lower case: still the ticker
        self.assertEqual((r["status"], r["symbol"]), ("ticker", "VTI"))

    def test_a_name_is_a_suggestion_to_confirm_with_others(self):
        r = ticker_search.resolve("apple", search=stub)
        self.assertEqual(r["status"], "suggest")          # never taken without a pick
        self.assertEqual(ticker_search.label(r["choices"][0]), "Apple Inc. (AAPL)")
        syms = [c["symbol"] for c in r["choices"]]
        self.assertIn("APLE", syms)                        # an alternative to pick
        self.assertNotIn("AAPL.MX", syms)                  # other exchanges' listings left out
        r = ticker_search.resolve("vanguard total stock market", search=stub)
        self.assertEqual([c["symbol"] for c in r["choices"]][:2], ["VTI", "VTSAX"])
        self.assertEqual(r["choices"][1]["kind"], "Mutual fund")

    def test_a_word_that_is_also_another_companys_ticker_is_asked_about(self):
        r = ticker_search.resolve("ford", search=stub)
        self.assertEqual(r["status"], "suggest")
        self.assertEqual(r["choices"][0]["symbol"], "F")                  # the name's match
        self.assertIn("FORD", [c["symbol"] for c in r["choices"]])        # the ticker, offered
        r = ticker_search.resolve("FORD", search=stub)                    # typed as a ticker
        self.assertEqual((r["status"], r["symbol"]), ("ticker", "FORD"))

    def test_crypto_kept_and_indexes_left_out(self):
        self.assertEqual([e["symbol"] for e in stub("bitcoin")], ["BTC-USD"])

    def test_without_yahoo_the_names_known_here_are_used(self):
        offline = lambda query: None   # noqa: E731 - Yahoo out of reach
        r = ticker_search.resolve("apple", search=offline)
        self.assertEqual((r["status"], r["symbol"]), ("suggest", "AAPL"))
        self.assertFalse(r["online"])
        r = ticker_search.resolve("Vanguard Total Stock Market", search=offline)
        self.assertEqual(r["choices"][0]["symbol"], "VTI")
        r = ticker_search.resolve("google", search=offline)   # another name people use
        self.assertEqual(r["choices"][0]["symbol"], "GOOGL")
        r = ticker_search.resolve("VTI", search=offline)
        self.assertEqual((r["status"], r["name"]), ("ticker", "Vanguard Total Stock Market ETF"))
        # a name known only from this copy's market data or holdings
        extra = [{"symbol": "ZZQX", "name": "Example Clean Energy Fund", "kind": "ETF"}]
        r = ticker_search.resolve("clean energy", search=offline, extra=extra)
        self.assertEqual(r["choices"][0]["symbol"], "ZZQX")
        r = ticker_search.resolve("ZZQX", search=offline, extra=extra)
        self.assertEqual(r["status"], "ticker")
        # a ticker nobody here knows is taken as typed (the price check follows)
        r = ticker_search.resolve("qqqz", search=offline)
        self.assertEqual((r["status"], r["symbol"]), ("unknown", "QQQZ"))
        self.assertEqual(ticker_search.resolve("no such company here", search=offline)["status"],
                         "none")
        self.assertEqual(ticker_search.resolve("  ", search=offline)["status"], "empty")

    def test_known_reads_market_data_and_only_this_accounts_holdings(self):
        d = tempfile.mkdtemp(prefix="pt_tsearch_")
        self.addCleanup(shutil.rmtree, d, True)
        c = portfolio.connect(os.path.join(d, "t.db"))
        try:
            ann = auth.create_user(c, "ann", "pw-123456789")
            bob = auth.create_user(c, "bob", "pw-123456789")
            c.execute("INSERT INTO security_info (ticker, name, quote_type) VALUES (?,?,?)",
                      ("SCHD", "Schwab U.S. Dividend Equity ETF", "ETF"))
            for uid, sym, desc in ((ann, "FZROX", "Fidelity ZERO Total Market Index Fund"),
                                   (bob, "SECRET", "Bob's Own Holding Co")):
                c.execute("INSERT INTO positions (user_id, snapshot_date, account, symbol, "
                          "description, asset_type, quantity, market_value) "
                          "VALUES (?,?,?,?,?,?,?,?)",
                          (uid, "2026-10-01", "Brokerage account", sym, desc, "Mutual Funds",
                           1, 100))
            c.commit()
            got = {e["symbol"]: e for e in ticker_search.known(c, ann)}
        finally:
            c.close()
        self.assertEqual(got["SCHD"]["kind"], "ETF")
        self.assertEqual(got["FZROX"]["kind"], "Mutual fund")
        self.assertNotIn("SECRET", got)                   # another account's holdings

    def test_yahoo_search_is_asked_briefly_cached_and_paused_when_down(self):
        import yfinance
        FakeSearch.calls = []
        with unittest.mock.patch.object(yfinance, "Search", FakeSearch):
            first = ticker_search.yahoo_search("apple", now=1000.0)
            again = ticker_search.yahoo_search("Apple", now=1010.0)   # cached
        self.assertEqual(first, again)
        self.assertEqual(len(FakeSearch.calls), 1)
        query, kw = FakeSearch.calls[0]
        self.assertEqual(query, "apple")
        self.assertLessEqual(kw["timeout"], 5)           # a short wait, not yfinance's 30s
        self.assertEqual(kw["news_count"], 0)            # just the securities

        def down(*a, **k):
            raise ConnectionError("no network")
        tries = []

        def raw(query, timeout):
            tries.append(query)
            return down()
        self.assertIsNone(ticker_search.yahoo_search("msft", now=2000.0, raw=raw))
        self.assertIsNone(ticker_search.yahoo_search("nvda", now=2005.0, raw=raw))
        self.assertEqual(tries, ["msft"])                # paused: no second wait
        ticker_search.yahoo_search("nvda", now=2000.0 + ticker_search.DOWN_SECONDS + 1, raw=raw)
        self.assertEqual(tries, ["msft", "nvda"])

    def test_the_bundled_list_is_small_and_well_formed(self):
        syms = [c[0] for c in ticker_search.COMMON]
        self.assertEqual(len(syms), len(set(syms)))
        self.assertLess(len(syms), 120)
        for sym, name, kind, _also in ticker_search.COMMON:
            self.assertTrue(ticker_search.looks_like_ticker(sym), sym)
            self.assertIn(kind, manual_entry.TYPES, sym)
            self.assertTrue(name)


class StarterFundsTests(unittest.TestCase):
    PROFILE = {"time_horizon_years": 20, "risk_tolerance": "moderate",
               "drawdown_reaction": "Hold and wait"}

    def test_the_card_is_the_same_for_everyone(self):
        # general education: never weighted by, or tied to, anyone's answers
        # (named funds beside "your mix" would read as a recommendation)
        import inspect
        self.assertEqual(list(inspect.signature(starter_funds.card).parameters),
                         ["info", "not_sure"])                  # no profile, no mix
        c = starter_funds.card()
        self.assertNotIn("pct", c["parts"][0])
        self.assertEqual([p["kind"] for p in c["parts"]],
                         ["a broad US stock index fund", "a broad international stock index fund",
                          "a broad US bond index fund"])

    def test_each_part_lists_funds_from_several_providers_and_no_single_stocks(self):
        c = starter_funds.card()
        self.assertEqual([p["label"] for p in c["parts"]],
                         ["US stocks", "International stocks", "Bonds"])
        providers = None
        for p in c["parts"]:
            names = {f["provider"] for f in p["funds"]}
            self.assertGreaterEqual(len(names), 3, p["label"])           # several, one each
            self.assertEqual(len(names), len(p["funds"]), p["label"])
            providers = providers or names
            self.assertEqual(names, providers)                           # the same ones each time
            for f in p["funds"]:
                self.assertRegex(f["name"], r"ETF$")                     # broad funds, not companies
        common = {sym: kind for sym, _n, kind, _a in ticker_search.COMMON}
        for t in starter_funds.ALL_FUNDS:
            self.assertEqual(common.get(t), "ETF", t)

    def test_the_wording(self):
        c = starter_funds.card()
        self.assertEqual(c["intro"], "Most simple portfolios are built from three kinds of funds. "
                                     "Here are a few well-known examples of each kind, from "
                                     "several providers:")
        self.assertEqual(c["footer"], "These are examples of each kind, from several providers, "
                                      "to learn from - not recommendations. Many similar funds "
                                      "exist.")
        self.assertEqual(c["note"], starter_funds.MIX_NOTE)
        self.assertTrue(starter_funds.card(not_sure=True)["intro"].startswith(
            "You're not sure yet - that's normal. Most simple portfolios"))
        for text in (c["intro"], c["footer"], c["note"]):
            for word in ("buy", "should", "recommend you", "your mix"):
                self.assertNotIn(word, text.lower())

    def test_names_and_fees_from_market_data(self):
        c = starter_funds.card(info={"VTI": {"name": "Vanguard Total Stock Market Index Fund ETF",
                                             "expense_ratio": 0.0003}})
        vti = c["parts"][0]["funds"][0]
        self.assertEqual((vti["symbol"], vti["fee"]), ("VTI", 0.0003))
        self.assertEqual(starter_funds.fee_text(vti["fee"]), "0.03% a year")
        self.assertEqual(starter_funds.fee_text(0.00035), "0.035% a year")
        self.assertIsNone(c["parts"][0]["funds"][1]["fee"])   # not known: not shown

    def test_practice_money_opens_learns_waypoint(self):
        state = {}
        starter_funds.open_practice(state)
        self.assertEqual((state["page"], state["gs_at"]), ("Get started", "practice"))
        with open(os.path.join(REPO, "views", "get_started.py"), encoding="utf-8") as fh:
            self.assertIn('("practice", ', fh.read())   # still the waypoint's key


class _App(unittest.TestCase):
    """The app with AppTest on a scratch database, as a new account."""

    def setUp(self):
        ticker_search.clear_cache()
        self.addCleanup(ticker_search.clear_cache)
        self.modules = {n: m for n, m in sys.modules.items()
                        if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                        == REPO}
        self.addCleanup(sys.modules.update, self.modules)
        self.dir = tempfile.mkdtemp(prefix="pt_handentry_")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.db = os.path.join(self.dir, "app.db")
        c = portfolio.connect(self.db)
        try:
            self.uid = auth.create_user(c, "newbie", "pw-123456789")
            advisor.save_profile(c, self.uid, StarterFundsTests.PROFILE)
        finally:
            c.close()

    def app(self, **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": self.uid, "username": "newbie", "page": "Dashboard",
                     "auto_backfilled": True, "income_synced": True, "open_dialog": "manual",
                     **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1")
        for p in (unittest.mock.patch.dict(os.environ, env, clear=True),
                  unittest.mock.patch.object(yfinance, "Ticker", offline),
                  unittest.mock.patch.object(yfinance, "Search", FakeSearch),
                  unittest.mock.patch("socket.socket.connect", offline_net.connect)):
            p.start()
            self.addCleanup(p.stop)
        return at

    def run_open(self, at):
        at.session_state["open_dialog"] = "manual"   # the window stays open
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        return at

    def rows(self, at):
        return list(at.session_state["me_ids"])

    def text(self, at):
        return "\n".join([m.value for m in at.markdown] + [m.value for m in at.caption]
                         + [m.value for m in at.error] + [m.value for m in at.success])


class HandEntryAppTests(_App):
    def test_a_new_user_adds_by_name_and_ticker_edits_removes_and_saves(self):
        at = self.run_open(self.app())
        first, = self.rows(at)                       # one empty row to start
        self.assertEqual(at.text_input(key=f"me_sym_{first}").label,
                         "Stock or fund (name or ticker)")
        self.assertEqual(at.number_input(key=f"me_w_qty_{first}").label, "How many shares")
        self.assertEqual(at.number_input(key=f"me_w_cost_{first}").label,
                         "What you paid in total")
        at.text_input(key=f"me_sym_{first}").set_value("apple")
        self.run_open(at)
        self.assertIn("Did you mean **Apple Inc. (AAPL)**?", self.text(at))
        # not confirmed yet: the review waits
        at.button(key="me_review_btn").click()
        self.run_open(at)
        self.assertIn('choose which "apple" you mean', self.text(at))
        self.assertNotIn("me_review", at.session_state)
        at.button(key=f"me_yes_{first}").click()
        self.run_open(at)
        self.assertEqual(at.session_state[f"me_sym_{first}"], "AAPL")
        self.assertEqual(at.session_state[f"me_type_{first}"], "Stock")
        at.number_input(key=f"me_w_qty_{first}").set_value(4)
        self.run_open(at)
        # + Add another, by ticker
        at.button(key="me_add").click()
        self.run_open(at)
        second = self.rows(at)[-1]
        at.text_input(key=f"me_sym_{second}").set_value("VTI")
        self.run_open(at)
        self.assertEqual(at.session_state[f"me_type_{second}"], "ETF")
        self.assertIn("Vanguard Total Stock Market Index Fund ETF Shares (VTI)", self.text(at))
        at.number_input(key=f"me_w_qty_{second}").set_value(10)
        self.run_open(at)
        # a third one, then removed
        at.button(key="me_add").click()
        self.run_open(at)
        third = self.rows(at)[-1]
        at.text_input(key=f"me_sym_{third}").set_value("ford")
        self.run_open(at)
        at.button(key=f"me_del_{third}").click()
        self.run_open(at)
        self.assertEqual(self.rows(at), [first, second])
        # edit a quantity
        at.number_input(key=f"me_w_qty_{first}").set_value(5)
        self.run_open(at)
        prices = {"AAPL": (230.0, "Apple Inc."), "VTI": (300.0, "Vanguard Total Stock Market ETF")}
        p = unittest.mock.patch.object(sys.modules["manual_entry"], "yahoo_price_and_name",
                                       lambda s: prices.get(s, (None, None)))
        p.start()
        self.addCleanup(p.stop)
        at.button(key="me_review_btn").click()
        self.run_open(at)
        self.assertIn("me_review", at.session_state)
        at.button(key="me_save").click()
        self.run_open(at)
        c = portfolio.connect(self.db)
        try:
            got = {r["symbol"]: (r["quantity"], r["market_value"], r["asset_type"])
                   for r in c.execute("SELECT * FROM positions WHERE user_id = ?", (self.uid,))}
        finally:
            c.close()
        self.assertEqual(got, {"AAPL": (5.0, 1150.0, "Equity"),
                               "VTI": (10.0, 3000.0, "ETFs & Closed End Funds")})

    def test_percentages_mode_and_a_second_account_still_work(self):
        at = self.run_open(self.app())
        first, = self.rows(at)
        at.button(key="me_add_acct").click()
        self.run_open(at)
        second = self.rows(at)[-1]
        self.assertEqual(at.session_state[f"me_acct_{second}"], "Brokerage account 2")
        renamed = [t for t in at.text_input if (t.key or "").startswith("me_gname_")
                   and t.value == "Brokerage account 2"][0]
        renamed.set_value("Roth IRA")
        self.run_open(at)
        self.assertEqual(at.session_state[f"me_acct_{second}"], "Roth IRA")
        at.segmented_control(key="me_mode").set_value("Percentages")
        self.run_open(at)
        self.assertIn(f"me_w_pct_{first}", [n.key for n in at.number_input])
        self.assertNotIn(f"me_w_qty_{first}", [n.key for n in at.number_input])

    def test_not_sure_yet_shows_the_example_card_and_its_buttons_work(self):
        at = self.run_open(self.app())
        self.assertIn("me_go_new", [b.key for b in at.button])     # offered to a new account
        shown = self.text(at)
        self.assertIn("**You're not sure yet - that's normal. Most simple portfolios are built "
                      "from three kinds of funds.", shown)
        # the same for everyone: kinds of funds with examples, never their mix's percentages
        mix = learn.starter_mix(StarterFundsTests.PROFILE)
        self.assertIn("**US stocks**", shown)
        self.assertNotIn(f"**US stocks** ({mix['weights']['us']}%)", shown)
        self.assertIn("A broad US stock index fund - e.g. VTI, ITOT, SCHB", shown)
        self.assertIn("to learn from - not recommendations.", shown)
        at.button(key="me_starter_watch").click()
        self.run_open(at)
        c = portfolio.connect(self.db)
        try:
            self.assertEqual(watchlist.list_tickers(c, self.uid), sorted(starter_funds.ALL_FUNDS))
        finally:
            c.close()
        at.button(key="me_starter_practice").click()
        self.run_open(at)    # the click, then a new run on Learn without the window
        self.assertEqual(at.session_state["page"], "Get started")
        self.assertEqual(at.session_state["gs_at"], "practice")


if __name__ == "__main__":
    unittest.main()
