"""PLAN step 7: the helpers that are rules, not AI (docs/AI_PLAN.md section 9,
rows 1, 3, 4, 5 and 12) - every one fixed templates over the person's own
figures or the same text for everyone, and every word checked against the
conclusion policy:

- the Home summary (allocation.summary_words, flag plain_summary);
- the Expedition Log line (expedition_log.line, from the kept verdict);
- the storm narrator (storms.narrate and the window's words);
- the glossary (glossary.py, flag glossary) - the same text Ask Northwend reads;
- the plan PDF's questions (client_plan: learn.readiness, open answers and a
  fixed bank of questions people ask a licensed professional).

    python -m unittest tests.test_rule_helpers        (from the repo root)
"""

import itertools
import os
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock
import zlib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import ai_library  # noqa: E402
import ai_policy  # noqa: E402
import allocation  # noqa: E402
import auth  # noqa: E402
import checkin  # noqa: E402
import client_plan  # noqa: E402
import expedition_log  # noqa: E402
import glossary  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sample_data  # noqa: E402
import storms  # noqa: E402

# Words none of these templates may use: advice, rankings, judgement of the
# person's mix, predictions (the conclusion policy, ai_policy.RULES).
BANNED = re.compile(
    r"\b(?:should|best|(?<!not )recommend\w*|must buy|must sell|ought|too (?:much|little|many|few|"
    r"aggressive|conservative|risky)|aggressive|conservative|well[- ]diversified|"
    r"diversified enough|not diversified|risky|on track|on the right track|behind|"
    r"good|bad|solid|great|poor|will (?:recover|rise|fall|bounce|come back)|bottom\w*|"
    r"soon|guarantee\w*|safe|forecast\w*|predict(?!ion\b))\b", re.I)


def _clean(case, text):
    case.assertIsNone(BANNED.search(text), text)
    case.assertEqual(ai_policy.findings(text), [], text)


def _pdf_text(pdf: bytes) -> str:
    """The words on a PDF's pages, one string (fpdf2 compresses them)."""
    raw = b""
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.S):
        try:
            raw += zlib.decompress(m.group(1))
        except zlib.error:
            raw += m.group(1)
    parts = re.findall(rb"\((.*?)(?<!\\)\)\s*Tj", raw, re.S)
    text = b" ".join(p.replace(rb"\(", b"(").replace(rb"\)", b")").replace(rb"\\", b"\\")
                     for p in parts).decode("latin-1")
    return " ".join(text.split())


def _pos(symbol, kind, value, account="Brokerage ...123"):
    return {"symbol": symbol, "asset_type": kind, "market_value": value, "account": account}


# --------------------------------------------------------------------------- #
# 1. the Home summary
# --------------------------------------------------------------------------- #
class SummaryTests(unittest.TestCase):

    def _words(self, positions, cash=None):
        return allocation.summary_words(allocation.allocate(positions, cash), positions)

    def test_the_mix_counts_and_largest_share(self):
        positions = [_pos("AAA", "Equity", 500), _pos("BBB", "Equity", 200),
                     _pos("CCC", "Fixed Income", 250, "IRA ...456")]
        self.assertEqual(self._words(positions, {"IRA ...456": 50}),
                         "About 70% in stocks, 25% in bonds and 5% in cash. 3 holdings "
                         "across 2 accounts; the largest, AAA, is 50% of the total.")

    def test_one_class_one_holding_and_slivers(self):
        self.assertEqual(self._words([_pos("AAA", "Equity", 100)]),
                         "Everything is in stocks. 1 holding.")
        words = self._words([_pos("AAA", "Equity", 997), _pos("ZZZ", "Weird", 3)])
        self.assertTrue(words.startswith("About 100% in stocks and under 1% in other "
                                         "holdings."), words)
        # the same symbol in two accounts is one holding
        words = self._words([_pos("AAA", "Equity", 60), _pos("AAA", "Equity", 50, "IRA ...456"),
                             _pos("BBB", "Fixed Income", 90)])
        self.assertIn("2 holdings across 2 accounts; the largest, AAA, is 55%", words)

    def test_a_half_percent_is_not_zero(self):
        # Fresh-eyes pass Oct 8: "{:.0f}" rounds halves to even - 0.5% of cash
        # read "0% in cash"
        words = self._words([_pos("AAA", "Equity", 995)], {"Brokerage ...123": 5})
        self.assertTrue(words.startswith("About 100% in stocks and under 1% in cash."), words)
        words = self._words([_pos("AAA", "Equity", 975)], {"Brokerage ...123": 25})
        self.assertTrue(words.startswith("About 98% in stocks and 2% in cash."), words)

    def test_nothing_to_read(self):
        self.assertEqual(allocation.summary_words(allocation.allocate([], {})), "")
        self.assertEqual(self._words([_pos("AAA", "Equity", 0)]), "")

    def test_only_descriptive_words(self):
        kinds = ("Equity", "Fixed Income", "Cash and Money Market", "Other")
        for combo in itertools.combinations_with_replacement(kinds, 3):
            positions = [_pos(f"S{i}", k, 100 * (i + 1), f"Acct {i % 2}")
                         for i, k in enumerate(combo)]
            words = self._words(positions, {"Acct 0": 10})
            self.assertTrue(words)
            _clean(self, words)
            self.assertNotIn("$", words)        # shares and counts, never an amount
            self.assertNotIn("US", words)       # no region data, so never a region


# --------------------------------------------------------------------------- #
# 3. the Expedition Log line
# --------------------------------------------------------------------------- #
class LogLineTests(unittest.TestCase):

    def test_every_line_is_facts_and_percentages(self):
        verdicts = [None, {"kind": checkin.WITHIN}, {"kind": checkin.NONE},
                    {"kind": checkin.NEXT}] + [
            {"kind": checkin.NEXT, "class": c, "how": h}
            for c in ("Stocks", "Bonds", "Cash", "Other") for h in ("all", "most", "much")]
        drifts = [None, {"class": "Stocks", "pts": 0}, {"class": "Bonds", "pts": 1},
                  {"class": "Cash", "pts": -7}]
        n = 0
        for v, d, m, updated, note in itertools.product(
                verdicts, drifts, (None, 0.0, 1.8, -12.4), (True, False), (True, False)):
            text = expedition_log.line("2026-10", {"on": "2026-10-05", "updated": updated,
                                                   "drift": d, "market": m, "note": note}, v)
            self.assertTrue(text.startswith("October 2026: "))
            _clean(self, text)
            self.assertNotIn("$", text)
            n += 1
        self.assertGreater(n, 500)


# --------------------------------------------------------------------------- #
# 4. the storm narrator
# --------------------------------------------------------------------------- #
class NarratorTests(unittest.TestCase):

    def test_fixed_words_filled_from_the_weather(self):
        w = {"level": "storm", "drop_pct": 12.4, "high_date": "2026-08-01",
             "as_of": "2026-09-30"}
        words = storms.narrate(w)
        self.assertEqual(words["title"], "A big market drop")
        self.assertEqual(words["lead"], "Your holdings are about 12% below their high on "
                                        "2026-08-01 (as of the close on 2026-09-30).")
        self.assertEqual(words["body"], storms.BODIES["storm"])
        self.assertEqual(words["steady"], storms.STEADY)
        rough = storms.narrate({**w, "level": "rough", "drop_pct": 6.0}, lambda d: "DAY")
        self.assertEqual(rough["title"], "A market dip")
        self.assertIn("6% below their high on DAY", rough["lead"])

    def test_history_never_a_prediction(self):
        texts = [storms.WINDOW_CAPTION, storms.WINDOW_NOTE, storms.STEADY,
                 *storms.TITLES.values(), *storms.BODIES.values(),
                 *(f"{n} fell {f}% and took {b} to pass its old high." for n, f, b
                   in storms.PAST_STORMS)]
        for level in ("rough", "storm"):
            texts += storms.narrate({"level": level, "drop_pct": 9.6, "high_date": "2026-08-01",
                                     "as_of": "2026-09-30"}).values()
        for text in texts:
            _clean(self, text)
        self.assertIn("don't promise", storms.WINDOW_NOTE)

    def test_the_note_draws_only_the_narrators_words(self):
        with open(os.path.join(REPO, "views", "kit.py"), encoding="utf-8") as fh:
            view = fh.read()
        self.assertIn("storms.narrate(w, _fmt_date)", view)
        self.assertIn("storms.WINDOW_NOTE", view)
        self.assertNotIn("Dips like this", view)


# --------------------------------------------------------------------------- #
# 5. the glossary
# --------------------------------------------------------------------------- #
class GlossaryTests(unittest.TestCase):

    def test_one_text_for_the_app_and_the_guide(self):
        self.assertIs(ai_library.GLOSSARY, glossary.TERMS)
        self.assertIn("### Glossary", ai_library.block_text())
        self.assertIn("- Expense ratio: ", ai_library.block_text())

    def test_short_general_and_never_advice(self):
        self.assertTrue(30 <= len(glossary.TERMS) <= 70, len(glossary.TERMS))
        self.assertEqual(len({t for t, _ in glossary.TERMS}), len(glossary.TERMS))
        for term, meaning in glossary.everything():
            _clean(self, f"{term}: {meaning}")
            self.assertLessEqual(len(re.findall(r"[.!?](?:\s|$)", meaning)), 2, term)
            self.assertNotRegex(meaning, r"\$\d")       # never a figure in dollars
            self.assertEqual(ai_policy.tickers_in(meaning), set(), term)   # no named funds
        for alias, term in glossary.ALIASES.items():
            self.assertIn(term, {t for t, _ in glossary.TERMS}, alias)

    def test_the_words_the_app_uses_are_found(self):
        for word in ("expense ratio", "Index fund", "ETF", "Mutual fund", "Asset class",
                     "Asset allocation", "rebalance", "Drift", "Band", "RMD", "HSA", "401(k)",
                     "IRA", "Roth IRA", "Roth", "dividend", "Ex-dividend date", "Yield",
                     "Bond", "Target-date fund", "Concentration", "Diversification",
                     "Brokerage account", "Total return"):
            self.assertIsNotNone(glossary.find(word), word)
        self.assertEqual(glossary.find("etf")[0], "Exchange-traded fund (ETF)")
        self.assertEqual(glossary.find("Roth 401(k)")[0], "Roth 401(k)")
        self.assertIsNone(glossary.find("Frobnication"))   # unknown: nothing (AI fallback later)
        rows = glossary.pick(["Frobnication", "ETF", "Exchange-traded fund", "Drift"])
        self.assertEqual([t for t, _ in rows], ["Exchange-traded fund (ETF)", "Drift"])
        self.assertTrue(rows[0][1][0].isupper() and rows[0][1].endswith("."))

    def test_the_pages_only_ask_for_words_it_has(self):
        for name in ("dashboard_page", "fees", "income", "get_started"):
            with open(os.path.join(REPO, "views", f"{name}.py"), encoding="utf-8") as fh:
                src = fh.read()
            calls = re.findall(r"what_this_means\((.*?)key=", src, re.S)
            self.assertTrue(calls, name)
            for call in calls:
                for word in re.findall(r'"([^"]+)"', call):
                    self.assertIsNotNone(glossary.find(word), f"{name}: {word}")


# --------------------------------------------------------------------------- #
# 12. the plan PDF's questions
# --------------------------------------------------------------------------- #
class PlanQuestionsTests(unittest.TestCase):

    def _facts(self, profile):
        return {"profile": profile, "missing": [], "summary": {"has_data": False},
                "plan": {}, "goal": None}

    def test_the_bank_and_the_general_questions(self):
        for q in client_plan.PRO_QUESTIONS + client_plan.GENERAL_QUESTIONS:
            self.assertTrue(q.endswith("?"), q)
            _clean(self, q)
        for text in (client_plan.PRO_TITLE, client_plan.PRO_TITLE_CLIENT, client_plan.PRO_NOTE,
                     client_plan.QUESTIONS_NOTE):
            _clean(self, text)
        self.assertNotRegex(client_plan.PRO_NOTE, r"\bneed\b")   # never "you need one"

    def test_getting_ready_comes_from_the_readiness_check(self):
        asks = " ".join(client_plan.questions(self._facts({
            "emergency_fund": "Under 3 months", "high_interest_debt": "Some",
            "employer_match": "Not sure", "income_stability": "Varies a lot"})))
        self.assertIn('You answered "Under 3 months" for emergency savings', asks)
        self.assertIn("high-interest debt", asks)
        self.assertIn("Does your employer match", asks)
        self.assertIn("Your income varies a lot", asks)
        # all in place: none of those
        asks = " ".join(client_plan.questions(self._facts({
            "emergency_fund": "3-6 months", "high_interest_debt": "None",
            "employer_match": "Yes, and I get the full match",
            "income_stability": "Very stable"})))
        for gone in ("emergency savings", "high-interest debt", "employer", "varies"):
            self.assertNotIn(gone, asks)
        for profile in ({}, {"emergency_fund": "None", "employer_match":
                             "Yes, but I'm not getting all of it"}):
            for q in client_plan.questions(self._facts(profile)):
                self.assertTrue(q.endswith("?"), q)
                self.assertEqual(ai_policy.findings(q), [], q)

    def test_the_pdf_prints_the_bank(self):
        d = tempfile.mkdtemp(prefix="pt_rules_")
        try:
            db = os.path.join(d, "t.db")
            portfolio._SCHEMA_READY.discard(os.path.abspath(db))
            conn = portfolio.connect(db)
            try:
                uid = auth.create_user(conn, "pat", "pw-123456789")
                facts = client_plan.build_facts(conn, uid, [], {})
            finally:
                conn.close()
            text = _pdf_text(client_plan.render_pdf(facts, None, account_name="pat"))
            self.assertIn(client_plan.PRO_TITLE, text)
            self.assertIn("How are you paid", text)
            text = _pdf_text(client_plan.render_pdf(facts, None, account_name="pat",
                                                    advisor_name="Carol"))
            self.assertIn(client_plan.PRO_TITLE_CLIENT, text)
        finally:
            shutil.rmtree(d, ignore_errors=True)


# --------------------------------------------------------------------------- #
# the app: Home's summary and the glossary popover behind their flags
# --------------------------------------------------------------------------- #
class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_rules_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.uid = auth.create_user(c, "sam", "pw-123456789")
            sample_data.load(c, cls.uid)
            prefs.save(c, cls.uid, {"first_steps": {"done": True}})
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _run(self, page, flags="", **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": self.uid, "username": "sam", "page": page, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                   NORTHWEND_FLAGS=flags, NORTHWEND_GATES="")
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch("flags._secret", lambda name: None), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline):
            at.run()
        self.assertEqual([e.message for e in at.exception], [])
        return at

    @staticmethod
    def _text(at):
        return " ".join(m.value for m in at.markdown)

    @staticmethod
    def _popovers(at):
        return [p.proto.popover.label for p in at.get("popover")]

    def test_home_summary_and_glossary_only_with_their_flags(self):
        at = self._run("Dashboard")
        self.assertNotIn("% in stocks", self._text(at))
        self.assertNotIn("What does this mean?", self._popovers(at))
        at = self._run("Dashboard", "plain_summary,glossary")
        text = self._text(at)
        # (the scratch database has no fund data, so the example's ETFs count as other)
        self.assertRegex(text, r"About \d+% in other holdings, \d+% in stocks and \d+% in "
                               r"cash\. 6 holdings across 2 accounts; the largest, \w+, is "
                               r"\d+% of the total\.")
        self.assertIn("What does this mean?", self._popovers(at))
        self.assertIn("**Drift** - How far a mix has moved", text)

    def test_learn_lists_the_whole_glossary(self):
        at = self._run("Get started", "glossary", gs_at="basics")
        text = self._text(at)
        for term, meaning in glossary.everything():
            self.assertIn(f"**{term}** - {meaning}", text)
        at = self._run("Get started", "", gs_at="basics")
        self.assertNotIn("**Yield** - ", self._text(at))


if __name__ == "__main__":
    unittest.main()
