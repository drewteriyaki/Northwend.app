"""Learn the basics with your own numbers (direction item 14; own_numbers.py,
views/own_numbers.py, flag learn_own_numbers): after four basics topics'
reads, one short "In your own portfolio" box - a fact from the person's own
holdings, description only. Never "should", never a ticker, never while an
advisor is in a client's account; nothing saved, nothing sent to the AI.

    python -m unittest tests.test_learn_own_numbers        (from the repo root)
"""

import contextlib
import itertools
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
import ai_policy  # noqa: E402
import auth  # noqa: E402
import fees  # noqa: E402
import flags  # noqa: E402
import learn  # noqa: E402
import manual_entry  # noqa: E402
import own_numbers as on  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sample_data  # noqa: E402
import two_step  # noqa: E402
from allocation import allocate  # noqa: E402

PW = "pw-123456789"
FLAG = "learn_own_numbers"

# made-up holdings: two funds and a single stock in two accounts, plus cash
POS = [
    {"symbol": "VTI", "asset_type": "ETFs & Closed End Funds", "market_value": 6000.0,
     "account": "A"},
    {"symbol": "BND", "asset_type": "ETFs & Closed End Funds", "market_value": 2500.0,
     "account": "A"},
    {"symbol": "AAPL", "asset_type": "Equity", "market_value": 1000.0, "account": "B"},
]
CASH = {"A": 500.0}
SPLITS = {"VTI": {"Stocks": 1.0}, "BND": {"Bonds": 1.0}}
INFO = {"VTI": {"quote_type": "ETF", "expense_ratio": 0.0003},
        "BND": {"quote_type": "ETF", "expense_ratio": 0.0005},
        "AAPL": {"quote_type": "EQUITY"}}
STOCKS_2022 = [("2021-12-31", 100.0), ("2022-06-30", 78.0), ("2022-12-30", 80.0)]
BONDS_2022 = [("2021-12-31", 100.0), ("2022-06-30", 90.0), ("2022-12-30", 87.0)]
# words that would judge or prescribe - none of them is ever in a box
JUDGING = ("should", "consider", "too high", "too low", "too much", "too little", "better",
           "worse", "recommend", "suggest", "you need", "ought", "must", "ideal", "right for",
           "good", "bad", "cheap", "expensive", "switch", "rebalance", "buy", "sell")


def _alloc(pos=POS, cash=CASH, splits=SPLITS, info=INFO):
    return allocate(pos, cash, splits, info)


def _fee_result(pos=POS, info=INFO):
    return fees.check([{"symbol": p["symbol"], "asset_type": p["asset_type"],
                        "value": p["market_value"]} for p in pos], info)


def _every_line():
    """Every box line the templates can make, over a spread of made-up cases."""
    year = on.mix_year(STOCKS_2022, BONDS_2022, 25)
    cases = []
    for pos, cash, splits, info in (
            (POS, CASH, SPLITS, INFO),
            (POS[:1], {}, SPLITS, INFO),                            # one fund, nothing else
            (POS[2:], {}, {}, INFO),                                # one single stock
            (POS[1:2], {}, SPLITS, INFO),                           # all bonds
            ([{**p, "market_value": 3.0} if p["symbol"] == "AAPL" else p for p in POS],
             CASH, SPLITS, INFO),                                   # a sliver
            (POS, CASH, SPLITS, {"VTI": {"quote_type": "ETF"}, "BND": {"quote_type": "ETF"}}),
    ):
        a = _alloc(pos, cash, splits, info)
        fr = _fee_result(pos, info)
        for t, y, money in itertools.product(on.TOPICS, (year, None), ("$2", None)):
            cases.append(on.lines(t, alloc=a, positions=pos, info=info, fee_result=fr,
                                  fee_money=money, year=y))
    for b in (0, 15, 100):
        cases.append(on.ups_lines(_alloc(), on.mix_year(STOCKS_2022, BONDS_2022, b)))
    lines = {line for case in cases for line in case}
    return lines | {on.NO_HOLDINGS, on.NO_HOLDINGS_MANAGED, on.FIXED_2022, on.TITLE,
                    on.TITLE_EXAMPLE}


# --------------------------------------------------------------------------- #
# the facts, per topic
# --------------------------------------------------------------------------- #
class TopicTests(unittest.TestCase):

    def test_funds_counts_and_shares(self):
        self.assertEqual(on.lines("funds", alloc=_alloc(), positions=POS, info=INFO),
                         ["You hold 2 funds and 1 single stock.",
                          "Funds are about 85% of your total, single stocks about 10%."])
        # one kind only: no shares sentence
        a = _alloc(POS[:2], {})
        self.assertEqual(on.lines("funds", alloc=a, positions=POS[:2], info=INFO),
                         ["You hold 2 funds."])

    def test_the_same_fund_in_two_accounts_is_one_holding(self):
        pos = POS + [{**POS[0], "account": "B"}]
        self.assertEqual(on.lines("funds", alloc=_alloc(pos), positions=pos, info=INFO)[0],
                         "You hold 2 funds and 1 single stock.")

    def test_spread_holdings_classes_and_the_largest(self):
        self.assertEqual(on.lines("spread", alloc=_alloc(), positions=POS, info=INFO),
                         ["You have 3 holdings across 3 asset classes: stocks, bonds and cash.",
                          "Your largest single holding is about 60% of your total. It's a "
                          "fund, which holds many companies or bonds itself."])
        a = _alloc(POS[2:], {}, {}, INFO)
        self.assertEqual(on.lines("spread", alloc=a, positions=POS[2:], info=INFO),
                         ["You have 1 holding, all in stocks.",
                          "Your one holding is about 100% of your total. It's a single "
                          "company's stock."])

    def test_fees_in_words(self):
        r = _fee_result()
        self.assertEqual(on.lines("fees", fee_result=r, fee_money="$2"),
                         ["Your funds' average yearly fee is about 0.036% of what they're "
                          "worth, weighted by how much is in each.",
                          "At today's value that's about $2 a year - the same figure Fee check "
                          "shows."])
        # no dollars unless they're passed (hidden, percentages only)
        self.assertEqual(len(on.lines("fees", fee_result=r)), 1)
        # one fund's fee not known
        r = _fee_result(info={**INFO, "BND": {"quote_type": "ETF"}})
        self.assertEqual(on.lines("fees", fee_result=r)[-1],
                         "1 fund with a fee not known yet isn't counted.")
        # no fee known at all, and no funds at all
        r = _fee_result(info={"VTI": {"quote_type": "ETF"}, "BND": {"quote_type": "ETF"}})
        self.assertIn("aren't known here yet", on.lines("fees", fee_result=r)[0])
        r = _fee_result(POS[2:])
        self.assertEqual(on.lines("fees", fee_result=r),
                         ["None of your holdings is a fund, so there's no yearly fund fee to "
                          "add up - single stocks and cash don't charge one."])

    def test_ups_bond_share_and_a_labelled_hypothetical_2022(self):
        year = on.mix_year(STOCKS_2022, BONDS_2022, 25)
        self.assertAlmostEqual(year["stocks"], -20.0)
        self.assertAlmostEqual(year["bonds"], -13.0)
        self.assertAlmostEqual(year["mix"], 0.75 * -20.0 + 0.25 * -13.0)
        got = on.lines("ups", alloc=_alloc(), year=year)
        self.assertEqual(got[0], "Bonds are about 25% of your mix, stocks about 70%.")
        self.assertIn("broad US stocks were down about 20% and broad US bonds down about 13%",
                      got[1])
        self.assertTrue(got[2].startswith("Hypothetically, a mix of 25% bonds and 75% US "
                                          "stocks held through all of 2022 would have been "
                                          "down about 18%."))
        self.assertIn("not your own holdings, and not a prediction", got[2])

    def test_ups_without_kept_prices_is_the_fixed_line(self):
        got = on.lines("ups", alloc=_alloc(), year=None)
        self.assertEqual(got, ["Bonds are about 25% of your mix, stocks about 70%.",
                               on.FIXED_2022])
        a = _alloc(POS[2:], {}, {}, INFO)
        self.assertEqual(on.lines("ups", alloc=a, year=None)[0],
                         "Your mix has no bonds; stocks are about 100% of it.")

    def test_a_year_is_only_worked_out_with_both_ends_kept(self):
        self.assertIsNone(on.year_change([], 2022))
        self.assertIsNone(on.year_change([("2022-12-30", 1.0)], 2022))     # no start
        self.assertIsNone(on.year_change([("2021-12-31", 1.0)], 2022))     # no end
        self.assertIsNone(on.year_change([("2021-06-30", 1.0), ("2022-12-30", 2.0)], 2022))
        self.assertIsNone(on.year_change([("2021-12-31", 1.0), ("2022-10-31", 2.0)], 2022))
        self.assertAlmostEqual(on.year_change([("2021-12-31T00:00:00", 2.0),
                                               ("2022-12-30", 1.0), ("2023-01-03", 9.0)],
                                              2022), -50.0)
        self.assertIsNone(on.mix_year(STOCKS_2022, [], 30))

    def test_skipped_topics_have_no_box_and_say_why(self):
        topics = {k for k in ("funds", "spread", "time", "fees", "ups", "accounts")}
        self.assertEqual(set(on.TOPICS) | set(on.SKIPPED), topics)
        self.assertFalse(set(on.TOPICS) & set(on.SKIPPED))
        for t in on.SKIPPED:
            self.assertEqual(on.lines(t, alloc=_alloc(), positions=POS, info=INFO,
                                      fee_result=_fee_result()), [])
        # every Learn basics topic is either boxed or skipped
        with open(os.path.join(REPO, "views", "get_started.py"), encoding="utf-8") as fh:
            src = fh.read()
        body = src.split("def _basics_topics(", 1)[1].split("\n\n\n", 1)[0]
        for t in topics:
            self.assertIn(f'("{t}", ', body)

    def test_nothing_to_show_without_holdings(self):
        empty = allocate([], {}, {}, {})
        for t in on.TOPICS:
            self.assertEqual(on.lines(t, alloc=empty, positions=[], info={}, year=None), [])


# --------------------------------------------------------------------------- #
# the words: describe, never prescribe; no tickers
# --------------------------------------------------------------------------- #
class WordingTests(unittest.TestCase):

    def test_every_line_keeps_the_conclusion_policy(self):
        lines = _every_line()
        self.assertGreater(len(lines), 25)
        for line in sorted(lines):
            with self.subTest(line=line):
                self.assertEqual(ai_policy.findings(line, allowed_tickers=set()), [])

    def test_no_judging_or_prescribing_words(self):
        for line in sorted(_every_line()):
            low = line.lower()
            for w in JUDGING:
                with self.subTest(line=line, word=w):
                    self.assertNotRegex(low, rf"\b{w}\b")

    def test_no_tickers_or_fund_names(self):
        held = {p["symbol"] for p in POS} | set(learn.PRACTICE_TICKERS.values())
        for line in sorted(_every_line()):
            with self.subTest(line=line):
                self.assertEqual(ai_policy.tickers_in(line), set())
                for t in held:
                    self.assertNotRegex(line, rf"\b{t}\b")
                self.assertNotIn("Vanguard", line)

    def test_anything_not_their_own_is_labelled_hypothetical(self):
        year = on.mix_year(STOCKS_2022, BONDS_2022, 25)
        mix = [s for s in on.ups_lines(_alloc(), year) if "would have" in s]
        self.assertEqual(len(mix), 1)
        self.assertTrue(mix[0].startswith("Hypothetically"))

    def test_the_flag_has_no_gate_and_is_off_unless_set(self):
        self.assertEqual(flags.FEATURES[FLAG], {"gates": (), "view": "own_numbers"})
        env = {k: v for k, v in os.environ.items() if k not in ("NORTHWEND_FLAGS",)}
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(flags, "_secret", lambda name: None):
            self.assertFalse(flags.on(FLAG))
            self.assertFalse(flags.view_on("own_numbers"))

    def test_nothing_goes_to_the_ai_or_is_saved(self):
        for path in ("own_numbers.py", os.path.join("views", "own_numbers.py")):
            with open(os.path.join(REPO, path), encoding="utf-8") as fh:
                src = fh.read()
            for word in ("anthropic", "ai_gateway", "advisor.", "_write_prefs", "prefs.save",
                         "INSERT", "UPDATE ", "_ai_record"):
                with self.subTest(path=path, word=word):
                    self.assertNotIn(word, src)


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
        cls.dir = tempfile.mkdtemp(prefix="pt_own_numbers_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            profile = {"goal": "Retirement", "time_horizon_years": 20,
                       "risk_tolerance": "moderate", "drawdown_reaction": "Hold and wait",
                       "experience": "new", "age_range": "25-34",
                       "income_stability": "Very stable", "emergency_fund": "3-6 months",
                       "high_interest_debt": "None", "employer_match": "No match or no plan"}
            done = {"first_steps": {"done": True}}
            # ann: her own holdings (the example's rows, saved as her own entry)
            cls.ann = auth.create_user(c, "ann", PW)
            advisor.save_profile(c, cls.ann, profile)
            rows, totals = sample_data.snapshot_rows("2026-10-01")
            portfolio.write_snapshot(c, cls.ann, {"snapshot_date": "2026-10-01",
                                                  "as_of_text": "Entered by hand"},
                                     rows, totals, manual_entry.SOURCE)
            prefs.save(c, cls.ann, done)
            for t, qt, stock, bond, er in (("VTI", "ETF", 1.0, 0.0, 0.0003),
                                           ("VXUS", "ETF", 1.0, 0.0, 0.0005),
                                           ("BND", "ETF", 0.0, 1.0, 0.0003),
                                           ("VOO", "ETF", 1.0, 0.0, 0.0003),
                                           ("SCHD", "ETF", 1.0, 0.0, 0.0006),
                                           ("AAPL", "EQUITY", None, None, None)):
                c.execute("INSERT INTO security_info (ticker, quote_type, stock_pct, bond_pct, "
                          "expense_ratio) VALUES (?, ?, ?, ?, ?)", (t, qt, stock, bond, er))
            for t, prices in (("VTI", STOCKS_2022), ("BND", BONDS_2022)):
                for d, p in prices:
                    c.execute("INSERT INTO daily_bars (ticker, date, close, adj_close) "
                              "VALUES (?, ?, ?, ?)", (t, d, p, p))
            # cam: nothing held yet
            cls.cam = auth.create_user(c, "cam", PW)
            advisor.save_profile(c, cls.cam, profile)
            prefs.save(c, cls.cam, done)
            # an advisor and her client (the example portfolio)
            cls.carol = auth.create_user(c, "carol", PW)
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dana = auth.create_user(c, "dana", PW)
            sample_data.load(c, cls.dana)
            advisor.save_profile(c, cls.dana, profile)
            auth.link_client(c, cls.carol, cls.dana)
            prefs.save(c, cls.dana, done)
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _app(self, uid, name, flag=FLAG, **state):
        import anthropic
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")

        def no_ai(**kw):
            raise AssertionError("nothing goes to the AI here")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": "Get started",
                     "gs_at": "basics", "fs_hide": True, "auto_backfilled": True,
                     **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY", "ANTHROPIC_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", NORTHWEND_FLAGS=flag)
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch("settings.load_env", lambda *a, **k: {}), \
                unittest.mock.patch.object(anthropic, "Anthropic", no_ai), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline_net.connect):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    def _stored(self):
        c = portfolio.connect(self.db)
        try:
            out = []
            for t in [r["name"] for r in c.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'")]:
                # what any visit writes (sign-in, the value log, live prices);
                # the settings are checked on their own
                if t in ("user_prefs", "login_sessions", "value_log", "price_history",
                         "app_state", "advisor_access_log", "ai_spend"):
                    continue
                out += [repr(tuple(r)) for r in c.execute(f"SELECT * FROM {t}")]
            return "\n".join(sorted(out))
        finally:
            c.close()

    def _prefs(self, uid):
        c = portfolio.connect(self.db)
        try:
            return prefs.load(c, uid)
        finally:
            c.close()

    @staticmethod
    def _md(at):
        return [m.value for m in at.markdown]

    @staticmethod
    def _box(at):
        """The box's text: the markdown after its title."""
        md = [m.value for m in at.markdown]
        for title in (on.TITLE, on.TITLE_EXAMPLE):
            head = f"**:material/person: {title}**"
            if head in md:
                return title, md[md.index(head) + 1]
        return None, None

    def _read(self, at, topic):
        at.button(key=f"basics_{topic}").click().run()
        self.assertEqual([e.message for e in at.exception], [])
        return self._box(at)

    def test_her_own_numbers_under_each_topic(self):
        before, kept = self._stored(), self._prefs(self.ann)
        with self._app(self.ann, "ann") as at:
            title, text = self._read(at, "funds")
            self.assertEqual(title, on.TITLE)
            self.assertTrue(text.startswith("You hold 5 funds and 1 single stock. Funds are "
                                            "about "))
            title, text = self._read(at, "spread")
            self.assertTrue(text.startswith("You have 6 holdings across 3 asset classes: "
                                            "stocks, bonds and cash. Your largest single "
                                            "holding is about 36% of your total. It's a fund"))
            title, text = self._read(at, "fees")
            self.assertTrue(text.startswith("Your funds' average yearly fee is about 0.035% "))
            self.assertIn(r"At today's value that's about \$", text)
            self.assertIn("own_fees_open", [b.key for b in at.button])
            title, text = self._read(at, "ups")
            self.assertTrue(text.startswith("Bonds are about 15% of your mix, stocks about "
                                            "81%."))
            self.assertIn("Hypothetically, a mix of 15% bonds and 85% US stocks held through "
                          "all of 2022 would have been down about 19%.", text)
            for t in on.SKIPPED:
                self.assertEqual(self._read(at, t), (None, None))
            self.assertNotRegex(" ".join(self._md(at)), r"\b(?:should|consider)\b")
        self.assertEqual(self._stored(), before)    # nothing new saved
        # in her settings only what reading a topic already noted (Year in review)
        now = self._prefs(self.ann)
        for k in set(now) | set(kept):
            if k not in ("learn_reads", "learn_dates"):
                self.assertEqual(now.get(k), kept.get(k), k)

    def test_hidden_amounts_drop_the_dollars(self):
        with self._app(self.ann, "ann", hide_amounts=True) as at:
            _title, text = self._read(at, "fees")
            self.assertIn("average yearly fee is about", text)
            self.assertNotIn("today's value", text)

    def test_the_fee_check_button_opens_fee_check(self):
        with self._app(self.ann, "ann") as at:
            self._read(at, "fees")
            at.button(key="own_fees_open").click().run()
            self.assertIn("Each year, at today's value", [m.label for m in at.metric])

    def test_without_holdings_the_add_line_and_buttons(self):
        with self._app(self.cam, "cam") as at:
            at.button(key="basics_funds").click().run()
            md = self._md(at)
            self.assertIn(f"**:material/person: {on.TITLE}**", md)
            self.assertIn(on.NO_HOLDINGS, md)
            keys = [b.key for b in at.button]
            self.assertIn("own_add_funds", keys)
            self.assertIn("own_sample_funds", keys)
            at.button(key="basics_time").click().run()
            self.assertNotIn(on.NO_HOLDINGS, self._md(at))

    def test_never_while_an_advisor_is_in_a_clients_account(self):
        with self._app(self.carol, "carol", two_step_ok=self.carol_ok,
                       active_user_id=self.dana) as at:
            for t in on.TOPICS:
                self.assertEqual(self._read(at, t), (None, None))
            self.assertNotIn(on.NO_HOLDINGS, self._md(at))
        # signed in as herself, the client sees her own (here the example portfolio)
        with self._app(self.dana, "dana") as at:
            title, text = self._read(at, "spread")
            self.assertEqual(title, on.TITLE_EXAMPLE)
            self.assertTrue(text.startswith("You have 6 holdings"))

    def test_flag_off_leaves_the_window_as_it_was(self):
        with self._app(self.ann, "ann", flag="") as at:
            off = {}
            for t in ("funds", "spread", "fees", "ups"):
                at.button(key=f"basics_{t}").click().run()
                off[t] = (self._md(at), [b.key for b in at.button])
                self.assertEqual(self._box(at), (None, None))
                self.assertFalse([k for k in off[t][1] if k and k.startswith("own_")])
        with self._app(self.ann, "ann") as at:
            for t in ("funds", "spread", "fees", "ups"):
                at.button(key=f"basics_{t}").click().run()
                title, text = self._box(at)
                self.assertEqual(title, on.TITLE)
                md = [m for m in self._md(at)
                      if m not in (f"**:material/person: {on.TITLE}**", text)]
                self.assertEqual(md, off[t][0])
                self.assertEqual([k for k in (b.key for b in at.button)
                                  if not (k or "").startswith("own_")], off[t][1])


if __name__ == "__main__":
    unittest.main()
