"""PLAN step 7, the AI helpers (docs/AI_PLAN.md section 9):
- row 5, the glossary's AI fallback (glossary_ai.py, flag glossary_ai): the
  term only goes, scrubbed; the answer passes the conclusion policy and is
  labelled general; counted against the chat allowance;
- row 11, advisor drafts (advisor_drafts.py, views/drafts.py, flag
  advisor_drafts + gates L1 and L2): the client's ADVISOR_FULL card and the
  advisor's typed points go; the draft only fills an editable box, labelled,
  never sent, saved or messaged from the helper; the advisor's allowance.

The model is always faked; nothing here calls the real API.

    python -m unittest tests.test_ai_drafts        (from the repo root)
"""

import ast
import os
import shutil
import sys
import tempfile
import types
import unittest
import unittest.mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import advisor_drafts  # noqa: E402
import ai_gateway  # noqa: E402
import ai_policy  # noqa: E402
import ai_spend  # noqa: E402
import ai_usage  # noqa: E402
import auth  # noqa: E402
import glossary_ai  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sample_data  # noqa: E402
import two_step  # noqa: E402
from evals import glossary_drafts as cases  # noqa: E402

PW = "pw-123456789"


def _message(text, stop="end_turn"):
    usage = types.SimpleNamespace(input_tokens=400, output_tokens=80,
                                  cache_creation_input_tokens=0, cache_read_input_tokens=0)
    return types.SimpleNamespace(stop_reason=stop, usage=usage,
                                 content=[types.SimpleNamespace(type="text", text=text)])


class _Model:
    """Stands in for anthropic.Anthropic: answers `texts` in turn (the last
    one again once they run out) and keeps every request."""

    def __init__(self, *texts):
        self.texts, self.calls = list(texts) or ["A word people use."], []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        text = self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]
        return _message(text)


def _sent(call) -> str:
    """Everything a request sends, as text."""
    return repr(call["system"]) + repr(call["messages"])


# --------------------------------------------------------------------------- #
# the register and the allowances
# --------------------------------------------------------------------------- #
class RegisterTests(unittest.TestCase):

    def test_both_helpers_are_registered(self):
        g, d = ai_gateway.HELPERS["glossary"], ai_gateway.HELPERS["draft"]
        self.assertEqual((g.model, g.kind, g.carries_dollars), (ai_gateway.HAIKU, "glossary",
                                                                False))   # the cheap tier
        self.assertEqual((d.model, d.kind, d.carries_dollars), (ai_gateway.SONNET, "draft",
                                                                False))   # the mid tier
        for kind in ("glossary", "draft"):
            self.assertIn(kind, ai_usage.KINDS)
            self.assertIn(kind, ai_usage.NOUNS)
            self.assertIn(kind, ai_usage.TYPICAL_MICRO)
            self.assertIn(kind, ai_spend.FEATURES)
        # a look-up is the person's chat allowance; a draft the advisor's drafts
        self.assertEqual(ai_usage.bucket_of("glossary", False), "chat")
        self.assertEqual(ai_usage.bucket_of("draft", True), "drafts")


# --------------------------------------------------------------------------- #
# the glossary's fallback
# --------------------------------------------------------------------------- #
class GlossaryTests(unittest.TestCase):

    def setUp(self):
        offline_net.no_ai_sink()   # an earlier app run's database is gone

    def test_only_a_term_is_sent(self):
        for raw, term in (("Sharpe ratio", "Sharpe ratio"), ("What is a REIT?", "REIT"),
                          ("what does contango mean", "contango"), ("Series I bond",
                                                                    "Series I bond"),
                          ("buy-and-hold", "buy-and-hold"), ("Rule 72(t)", "Rule 72(t)")):
            self.assertEqual(glossary_ai.clean_term(raw), term, raw)
        for raw in ("", "should i sell my VTI", "my 401k balance", "$5,000 in bonds",
                    "acct 12345678", "me@example.com", "x" * 41, "the best fund",
                    "what we ought to hold", "a <b>tag</b>", "is this worth it",
                    "one two three four five six"):
            self.assertIsNone(glossary_ai.clean_term(raw), raw)

    def test_grouped_digits_are_not_sent(self):
        # Fresh-eyes pass Oct 8: "987 654 321" got past the 4-digit check
        for raw in ("987 654 321", "acct 12 34 56 78", "12-34-56", "1.234.567"):
            self.assertIsNone(glossary_ai.clean_term(raw), raw)
        for raw in ("S&P 500", "60/40", "529 plan", "401(k) vs 403(b)", "3-2-1"):
            self.assertEqual(glossary_ai.clean_term(raw), raw, raw)

    def test_the_request_carries_the_term_and_nothing_else(self):
        model = _Model(cases.GLOSSARY[0][1][0])
        text = glossary_ai.explain("Sharpe ratio", user_id=None, client=model)
        self.assertEqual(text, cases.GLOSSARY[0][1][0])
        (call,) = model.calls
        self.assertEqual((call["model"], call["max_tokens"]), (ai_gateway.HAIKU, 300))
        self.assertEqual(call["system"], glossary_ai.SYSTEM)   # the same for everyone
        self.assertIn(ai_policy.rules_text(), call["system"])
        self.assertEqual(call["messages"], glossary_ai.messages_for("Sharpe ratio"))
        self.assertNotIn("<card>", _sent(call))

    def test_eval_prescriptive_phrasing_never_shows(self):
        for term, good, bad in cases.GLOSSARY:
            for b in bad:
                with self.subTest(term=term, bad=b):
                    # broken twice: nothing to show
                    self.assertIsNone(glossary_ai.explain(term, user_id=None,
                                                          client=_Model(b, b)))
                    # broken, then a general answer: the general one, after one retry
                    model = _Model(b, good[0])
                    self.assertEqual(glossary_ai.explain(term, user_id=None, client=model),
                                     good[0])
                    self.assertEqual(len(model.calls), 2)
                    self.assertIn(ai_policy.RETRY_REMINDER, repr(model.calls[1]["messages"]))
            for g in good:
                self.assertEqual(ai_policy.findings(g, ai_policy.tickers_in(term)), [], g)
                self.assertEqual(glossary_ai.explain(term, user_id=None, client=_Model(g)), g)

    def test_a_declined_answer_shows_nothing(self):
        model = _Model("x")
        model.create = lambda **kw: _message("", stop="refusal")
        self.assertIsNone(glossary_ai.explain("Sharpe ratio", user_id=None, client=model))

    def test_the_fixed_words(self):
        for text in (glossary_ai.LABEL, glossary_ai.NOT_A_TERM, glossary_ai.NO_ANSWER):
            self.assertNotRegex(text, r"(?i)\b(?:should|best|recommend)")
        self.assertIn("not about your money", glossary_ai.LABEL)


# --------------------------------------------------------------------------- #
# advisor drafts
# --------------------------------------------------------------------------- #
class DraftTests(unittest.TestCase):

    def setUp(self):
        offline_net.no_ai_sink()   # an earlier app run's database is gone

    def test_what_goes_in(self):
        ask = advisor_drafts.request_text(
            "proposal", card="<card>\nMix by asset class: Stocks 80%.\n</card>",
            title="Steadier <b>", mix={"Stocks": 60.0, "Bonds": 35.4, "Cash": 4.6, "Other": 0},
            points="Move $25,000 to bonds, acct 1234-5678-9012, ask jo@example.com, by 2029")
        self.assertIn("<card>", ask)
        self.assertIn("Stocks 60%, Bonds 35%, Cash 5%", ask)
        self.assertIn("[amount]", ask)
        self.assertIn("[number]", ask)
        self.assertIn("[email]", ask)
        self.assertIn("2029", ask)          # a year isn't an account number
        for gone in ("$", "25,000", "1234", "jo@example.com", "<b>"):
            self.assertNotIn(gone, ask)
        self.assertEqual(len(advisor_drafts.scrub("y" * 900)), advisor_drafts.POINTS_MAX)
        with self.assertRaises(ValueError):
            advisor_drafts.request_text("email")
        # the proposal's title is typed by the advisor too: no amount reaches the AI
        ask = advisor_drafts.request_text("proposal", title="$1.2M plan, acct 99887766",
                                          mix={"Stocks": 60})
        self.assertIn("The proposal's title: [amount] plan, acct [number]", ask)
        for gone in ("$", "1.2M", "99887766"):
            self.assertNotIn(gone, ask)

    def test_report_facts_are_percentages_only(self):
        facts = {"value_start": 200_000.0, "value_end": 210_000.0, "money_in": 5_000.0,
                 "growth": 5_000.0, "goal": {"pct": 48.2, "status": "on_track",
                                             "target": 500_000.0},
                 "next_steps": ["Call about the ROTH-SECRET-STEP"]}
        text = advisor_drafts.report_facts(facts, "Q3 2026")
        self.assertIn("+2.5%", text)
        self.assertIn("48% of the target", text)
        self.assertIn("Open next steps shared with the client: 1.", text)
        for gone in ("$", "200", "5,000", "5000", "500", "ROTH-SECRET-STEP"):
            self.assertNotIn(gone, text)

    def test_eval_drafts_never_claim_northwend_advises(self):
        for kind, inputs, good, bad in cases.DRAFTS:
            for b in bad:
                with self.subTest(kind=kind, bad=b):
                    self.assertTrue(advisor_drafts.problems(
                        b, ai_policy.tickers_in(advisor_drafts.request_text(kind, **inputs))))
                    self.assertIsNone(advisor_drafts.draft(kind, user_id=None,
                                                           client=_Model(b, b), **inputs))
                    model = _Model(b, good[0])
                    self.assertEqual(advisor_drafts.draft(kind, user_id=None, client=model,
                                                          **inputs), good[0])
                    self.assertIn(advisor_drafts.REMINDER, repr(model.calls[1]["messages"]))
            for g in good:
                model = _Model(g)
                self.assertEqual(advisor_drafts.draft(kind, user_id=None, client=model,
                                                      **inputs), g)
                (call,) = model.calls
                self.assertEqual((call["model"], call["max_tokens"]), (ai_gateway.SONNET, 2000))
                self.assertEqual(call["system"], advisor_drafts.SYSTEM)

    def test_the_rules_say_the_advice_is_the_advisors(self):
        self.assertIn("never the software's", advisor_drafts.SYSTEM)
        self.assertIn("Don't mention Northwend", advisor_drafts.SYSTEM)
        self.assertTrue(advisor_drafts.northwend_claims("Northwend recommends a 60/40 mix."))
        self.assertTrue(advisor_drafts.northwend_claims("This mix is approved by Northwend."))
        self.assertFalse(advisor_drafts.northwend_claims("It's waiting on your Northwend page."))
        self.assertFalse(advisor_drafts.northwend_claims("I recommend we move to 60/40."))

    def test_the_draft_path_never_sends_saves_or_messages(self):
        # AI_PLAN section 9: the gateway returns text; it never calls mailer,
        # proposals, advising.add_note or messaging - not imported anywhere in
        # these files (functions included) ...
        banned = {"mailer", "proposals", "advising", "messaging"}
        for name in ("advisor_drafts", "ai_gateway", "ai_policy", "glossary_ai"):
            with open(os.path.join(REPO, f"{name}.py"), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            found = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    found |= {a.name.split(".")[0] for a in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module:
                    found.add(node.module.split(".")[0])
            self.assertEqual(found & banned, set(), name)
        # ... and not called when a draft is made, even if something were to
        import advising
        import mailer
        import proposals

        def boom(*a, **k):
            raise AssertionError("a draft reached sending or saving")
        with unittest.mock.patch.object(mailer, "send", boom), \
                unittest.mock.patch.object(advising, "add_note", boom), \
                unittest.mock.patch.object(advising, "message_clients", boom), \
                unittest.mock.patch.object(proposals, "save", boom), \
                unittest.mock.patch.object(proposals, "share", boom):
            for kind, inputs, good, _bad in cases.DRAFTS:
                self.assertEqual(advisor_drafts.draft(kind, user_id=None,
                                                      client=_Model(good[0]), **inputs), good[0])

    def test_the_label(self):
        self.assertEqual(advisor_drafts.LABEL, "Draft - written with AI, edit before sending")


# --------------------------------------------------------------------------- #
# the app, through AppTest, with the model faked
# --------------------------------------------------------------------------- #
class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_ai_drafts_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.sam = auth.create_user(c, "sam", PW)
            prefs.save(c, cls.sam, {"first_steps": {"done": True}})
            cls.carol = auth.create_user(c, "carol", PW)
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dana = auth.create_client(c, cls.carol, "dana", name="Dana Lee")
            sample_data.load(c, cls.dana)
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        ai_spend.use_db(None)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def page(self, uid, name, model, page, flags="", gates="", **state):
        import anthropic
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in dict(user_id=uid, username=name, page=page, auto_backfilled=True,
                         income_synced=True, **state).items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "RENDER", "NORTHWEND_ENV",
                            "RESEND_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                   NORTHWEND_FLAGS=flags, NORTHWEND_GATES=gates)
        for p in (unittest.mock.patch.dict(os.environ, env, clear=True),
                  unittest.mock.patch("flags._secret", lambda name: None),
                  unittest.mock.patch.object(anthropic, "Anthropic", lambda **kw: model),
                  unittest.mock.patch.object(yfinance, "Ticker", offline),
                  unittest.mock.patch("socket.socket.connect", offline_net.connect)):
            p.start()
            self.addCleanup(p.stop)
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        return at

    def used(self, uid, kind):
        c = portfolio.connect(self.db)
        try:
            row = c.execute("SELECT used FROM ai_usage WHERE user_id = ? AND kind = ?",
                            (uid, kind)).fetchone()
            return row["used"] if row else 0
        finally:
            c.close()

    @staticmethod
    def _words(at):
        return " ".join([m.value for m in at.markdown] + [m.value for m in at.caption]
                        + [m.value for m in at.info])

    # ---- the glossary's look-up ---------------------------------------------- #
    def test_look_up_another_word(self):
        good = cases.GLOSSARY[0][1][0]
        model = _Model(good)
        at = self.page(self.sam, "sam", model, "Get started", "glossary", gs_at="basics")
        self.assertNotIn("gloss_go", [b.key for b in at.button])   # its own flag
        at = self.page(self.sam, "sam", model, "Get started", "glossary,glossary_ai",
                       gs_at="basics")
        # a word the glossary has: its own words, no AI
        at.text_input(key="gloss_q").set_value("ETF")
        at.button(key="gloss_go").click().run()
        self.assertIn("**Exchange-traded fund (ETF)** - ", self._words(at))
        self.assertEqual(model.calls, [])
        # a sentence about their money: not sent
        at.text_input(key="gloss_q").set_value("should i sell my VTI")
        at.button(key="gloss_go").click().run()
        self.assertIn(glossary_ai.NOT_A_TERM, self._words(at))
        self.assertEqual(model.calls, [])
        # another word: the term alone goes; the answer is labelled general
        at.text_input(key="gloss_q").set_value("Sharpe ratio")
        at.button(key="gloss_go").click().run()
        self.assertEqual([e.message for e in at.exception], [])
        words = self._words(at)
        self.assertIn(good, words)
        self.assertIn(glossary_ai.LABEL, words)
        (call,) = model.calls
        self.assertEqual(call["messages"], glossary_ai.messages_for("Sharpe ratio"))
        self.assertNotIn("<card>", _sent(call))
        self.assertEqual(self.used(self.sam, "glossary"), 1)   # the chat allowance

    # ---- advisor drafts ------------------------------------------------------ #
    def _carol(self, model, page, flags="advisor_drafts", gates="L1,L2", **state):
        return self.page(self.carol, "carol", model, page, flags, gates,
                         two_step_ok=self.carol_ok, **state)

    def test_drafts_need_the_flag_and_both_gates(self):
        model = _Model("x")
        for flags, gates in (("", "L1,L2"), ("advisor_drafts", "L1"),
                             ("advisor_drafts", "L2")):
            at = self._carol(model, "Advisor notes", flags, gates, active_user_id=self.dana)
            self.assertNotIn("draft_report", [b.key for b in at.button], (flags, gates))

    def test_a_proposal_draft_fills_the_box_only(self):
        good = cases.DRAFTS[0][2][0]
        model = _Model(good)
        before = self.used(self.carol, "draft")
        at = self._carol(model, "Plan", active_user_id=self.dana)
        at.text_input(key="prop_title").set_value("A steadier mix")
        at.text_input(key="draft_points_proposal").set_value("house in 2029, $40,000 down")
        at.button(key="draft_proposal").click().run()
        self.assertEqual([e.message for e in at.exception], [])
        self.assertEqual(at.text_area(key="prop_note").value, good)
        self.assertIn(advisor_drafts.LABEL, self._words(at))
        (call,) = model.calls
        sent = _sent(call)
        self.assertIn("<card>", sent)                      # the client's card, ADVISOR_FULL
        self.assertIn("Notes aren't kept in this conversation", sent)
        self.assertIn("[amount]", sent)
        self.assertNotIn("$", sent.replace("\\$", ""))
        self.assertNotIn("Dana", sent)                     # no names
        c = portfolio.connect(self.db)
        try:   # nothing saved, shared or sent - the advisor's buttons do that
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM proposals").fetchone()["n"], 0)
        finally:
            c.close()
        self.assertEqual(self.used(self.carol, "draft"), before + 1)   # the advisor's allowance
        self.assertEqual(self.used(self.dana, "draft"), 0)

    def test_a_report_draft(self):
        good = cases.DRAFTS[2][2][0]
        model = _Model(good)
        at = self._carol(model, "Advisor notes", active_user_id=self.dana)
        at.button(key="draft_report").click().run()
        self.assertEqual([e.message for e in at.exception], [])
        self.assertEqual(at.text_area(key="rep_message").value, good)
        self.assertIn(advisor_drafts.LABEL, self._words(at))
        sent = _sent(model.calls[0])
        self.assertIn("<card>", sent)
        self.assertIn("Period:", sent)
        self.assertNotIn("$", sent.replace("\\$", ""))
        c = portfolio.connect(self.db)
        try:
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM progress_reports")
                             .fetchone()["n"], 0)
        finally:
            c.close()

    def test_a_message_draft_sends_no_card(self):
        good = cases.DRAFTS[1][2][0]
        model = _Model(good)
        at = self._carol(model, "Clients")
        at.text_input(key="draft_points_message").set_value("bumpy week, plan allows for it")
        at.button(key="draft_message").click().run()
        self.assertEqual([e.message for e in at.exception], [])
        self.assertEqual(at.text_area(key="msg_body").value, good)
        sent = _sent(model.calls[0])
        self.assertNotIn("<card>", repr(model.calls[0]["messages"]))   # several clients: no card
        self.assertIn("bumpy week", sent)
        c = portfolio.connect(self.db)
        try:   # not sent: still only the advisor's own Review and send does that
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM advisor_notes")
                             .fetchone()["n"], 0)
        finally:
            c.close()


if __name__ == "__main__":
    unittest.main()
