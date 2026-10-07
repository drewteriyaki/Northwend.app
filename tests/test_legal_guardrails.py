"""Staying on the education side of the line (not an investment adviser):

- nothing worked out from a person's own answers names a fund - Learn's
  example mix, practice money, first investments, their direction, Home and
  Plan speak in kinds of funds and percentages; named example funds appear
  only in the general read, the same for everyone (starter_funds.py)
- every AI entry point's system prompt carries the rules (advisor.GUARDRAILS)
- where prices are shown, the page says where they come from and that they
  may be delayed (dashboard.PRICE_SOURCE)

Runs dashboard.py with streamlit's AppTest on a scratch database in a temp dir.

    python -m unittest tests.test_legal_guardrails        (from the repo root)
"""

import contextlib
import glob
import os
import re
import shutil
import sys
import tempfile
import types
import unittest
import unittest.mock
from datetime import date, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import advisor  # noqa: E402
import auth  # noqa: E402
import client_plan  # noqa: E402
import learn  # noqa: E402
import meeting  # noqa: E402
import plans  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sample_data  # noqa: E402
import starter_funds  # noqa: E402

# every fund the app names anywhere as an example, plus the ones it used to
# suggest by preference (ESG, dividends)
TICKERS = sorted(set(starter_funds.ALL_FUNDS)
                 | {t for b in learn.BLOCKS for t in b["examples"]}
                 | {"ESGV", "SCHD", "VYM", "VOO"})
TICKER_RE = re.compile(r"\b(" + "|".join(TICKERS) + r")\b")
PRICE_SOURCE = "Prices from Finnhub and Yahoo Finance, may be delayed"

PROFILE = {"goal": "Retirement", "time_horizon_years": 25, "risk_tolerance": "moderate",
           "drawdown_reaction": "Hold and wait", "experience": "new", "age_range": "25-34",
           "income_stability": "Very stable", "emergency_fund": "3-6 months",
           "high_interest_debt": "None", "employer_match": "No match or no plan",
           # each of these used to add a named fund to the example mix
           "preferences": "Hands-off / set and forget; Dividend income; "
                          "Sustainable (ESG) investing"}
GOAL = {"goal_type": "Retirement", "target_amount": 500000.0, "target_date": "2056-10-01",
        "monthly_contribution": 300.0, "target_alloc": {"Stocks": 80.0, "Bonds": 20.0}}
DONE = {"first_steps": {"done": True}}


def _texts(node):
    """Every piece of text a person can read under `node` (the app or a block)."""
    out = [m.value for m in node.markdown] + [c.value for c in node.caption]
    out += [h.proto.body for h in node.get("html")]
    for kind in ("info", "success", "warning"):
        out += [a.value for a in getattr(node, kind)]
    out += [b.label for b in node.button] + [b.help or "" for b in node.button]
    out += [m.label for m in node.metric] + [str(m.value) for m in node.metric]
    return out


def _block(node, key):
    """The container made with key=`key` under `node` (its proto id ends
    with the key), or None."""
    for child in getattr(node, "children", {}).values():
        if hasattr(child, "children"):
            if str(getattr(getattr(child, "proto", None), "id", "")).endswith(f"-{key}"):
                return child
            found = _block(child, key)
            if found is not None:
                return found
    return None


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_legal_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.setup_db(c)
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _run(self, uid, name, page, gates="", **state):
        """`gates`: NORTHWEND_GATES - "" (gate L3 off: common starting points,
        the same for everyone) unless "L3" (the tailored example mix)."""
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": page, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                   NORTHWEND_GATES=gates)
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline_net.connect):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    def assertNoTickers(self, texts, where):
        named = sorted({m for t in texts for m in TICKER_RE.findall(t or "")})
        self.assertEqual(named, [], f"{where}: a fund named next to the person's own answers")


class PersonalizedViewsTests(_Base):
    """Someone with answers, a goal and a target mix, nothing invested."""

    @classmethod
    def setup_db(cls, c):
        cls.ivy = auth.create_user(c, "ivy", "pw-123456789")
        advisor.save_profile(c, cls.ivy, PROFILE)
        prefs.save(c, cls.ivy, DONE)
        plans.save_plan(c, cls.ivy, GOAL, set_by=cls.ivy)
        # on the first steps' direction screen
        cls.fay = auth.create_user(c, "fay", "pw-123456789")
        advisor.save_profile(c, cls.fay, PROFILE)
        prefs.save(c, cls.fay, {"first_steps": {"step": 6}})
        # very different answers: money needed in two years, a calm ride
        cls.max = auth.create_user(c, "max", "pw-123456789")
        advisor.save_profile(c, cls.max, {**PROFILE, "time_horizon_years": 2,
                                          "risk_tolerance": "conservative",
                                          "drawdown_reaction": "Sell everything"})
        prefs.save(c, cls.max, DONE)
        # ten years of weekly prices for the practice funds, up to today
        today = date.today()
        for t, p0 in learn.PRACTICE_TICKERS.items():
            rows = [(p0, (today - timedelta(days=7 * i)).isoformat(), 100.0 + i % 9)
                    for i in range(0, 530)]
            c.executemany("INSERT INTO daily_bars (ticker, date, close, adj_close) "
                          "VALUES (?, ?, ?, ?)", [(t, d, px, px) for t, d, px in rows])
        c.commit()

    def test_the_example_mix_speaks_in_kinds_of_funds(self):
        # gate L3 on: the example mix worked out from their answers
        with self._run(self.ivy, "ivy", "Get started", gates="L3", gs_at="mix") as at:
            texts = _texts(at)
            self.assertNoTickers(texts, "An example mix")
            body = " ".join(texts)
            self.assertIn("An example worked out from your timeline and comfort answers", body)
            self.assertNotIn("for someone with your answers", body)
            for kind in learn.KINDS.values():
                self.assertIn(kind, body)                  # each part's kind of fund
            self.assertIn("target-date fund", body)        # the preferences, as kinds
            self.assertIn("ESG versions of broad index funds", body)
            self.assertIn("dividend-focused funds", body)
            self.assertNotIn("gs_watch", [b.key for b in at.button])

    def test_with_l3_off_nothing_is_worked_out_from_their_answers(self):
        """Gate L3 off (production today): the mix waypoint, Home and Plan show
        common starting points - the same table for everyone - and no copy
        says "for you", "your answers" or names a type for them (PLAN step 2,
        "done when")."""
        table = None
        for page, state in (("Get started", {"gs_at": "mix"}), ("Dashboard", {}),
                            ("Plan", {}), ("Get started", {"gs_at": "practice"}),
                            ("Get started", {"gs_at": "first"})):
            with self._run(self.ivy, "ivy", page, **state) as at:
                body = " ".join(_texts(at))
                for words in ("for your answers", "with your answers", "for someone like you",
                              "could look like for you", "Your direction",
                              "An example mix for this type", "Use the suggestion",
                              "Suggested starting point", "Example mix"):
                    self.assertNotIn(words, body, (page, state, words))
                for kind in learn.INVESTOR_TYPES.values():
                    self.assertNotIn(kind["name"], body, (page, state))
                if state.get("gs_at") == "mix":
                    self.assertIn(learn.COMMON_POINTS_NOTE, body)
                    tables = [h.proto.body for h in at.get("html")
                              if "pt-common-points" in h.proto.body]
                    self.assertEqual(len(tables), 1)
                    table = tables[0]
                    self.assertNoTickers(_texts(at), "Common starting points")
        # the table is identical for someone with very different answers
        with self._run(self.max, "max", "Get started", gs_at="mix") as at:
            self.assertIn(table, [h.proto.body for h in at.get("html")])

    def test_practice_money_names_kinds_not_funds(self):
        with self._run(self.ivy, "ivy", "Get started", gs_at="practice") as at:
            texts = _texts(at)
            self.assertIn("Worst drop", " ".join(texts))   # the practice run is shown
            self.assertNoTickers(texts, "Try it with practice money")
            self.assertIn("international stocks", " ".join(texts))

    def test_first_investments_name_funds_only_in_the_general_card(self):
        # never beside their direction or their mix (LEGAL_GATES B14), with
        # gate L3 on or off
        for gates in ("", "L3"):
            with self._run(self.ivy, "ivy", "Get started", gates=gates, gs_at="first") as at:
                body = " ".join(_texts(at))
                for words in ("Your direction", "from your answers", "the target mix you set",
                              "% stocks"):
                    self.assertNotIn(words, body, (gates, words))
        with self._run(self.ivy, "ivy", "Get started", gs_at="first") as at:
            card = _block(at._tree, "gs_starter_card")   # the general card
            general = _texts(card)
            outside = [t for t in _texts(at) if t not in general]
            self.assertNoTickers(outside, "Your first investments")
            # the card: examples of each kind, never this person's percentages
            self.assertTrue(TICKER_RE.search(" ".join(general)))
            self.assertIn(starter_funds.FOOTER, general)
            self.assertFalse([t for t in general if re.search(r"\(\d+%\)", t)])
            self.assertIn("gs_starter_watch", [b.key for b in at.button])
            self.assertIn("gs_starter_practice", [b.key for b in at.button])

    def test_the_general_read_in_learn_the_basics(self):
        # practice money's stand-ins are the first example of each kind there,
        # as its caption says
        for p in starter_funds.PARTS:
            self.assertEqual(p["funds"][0], learn.PRACTICE_TICKERS[p["key"]])
        with self._run(self.ivy, "ivy", "Get started", gs_at="basics") as at:
            general = " ".join(_texts(_block(at._tree, "gs_kinds_card")))
            for t in starter_funds.ALL_FUNDS:
                self.assertIn(t, general)
            self.assertIn(starter_funds.FOOTER, general)
            at.button(key="gs_kinds_watch").click().run()
            self.assertIn("Nothing is bought.", " ".join(s.value for s in at.success))

    def test_their_direction_home_and_plan_name_no_fund(self):
        # gate L3 on: their direction (the investor type and its example mix)
        with self._run(self.ivy, "ivy", "Dashboard", gates="L3") as at:
            self.assertNoTickers(_texts(at), "Home")
            at.button(key="start_direction").click().run()
            body = " ".join(_texts(at))
            self.assertIn("Kinds of funds that usually fill it", body)   # the window opened
            self.assertNoTickers(_texts(at), "Your direction")
        with self._run(self.ivy, "ivy", "Plan", gates="L3") as at:
            self.assertNoTickers(_texts(at), "Plan")
        with self._run(self.fay, "fay", "Get started", gates="L3") as at:
            body = " ".join(_texts(at))
            self.assertIn("Usually held through a broad US stock index fund", body)
            self.assertNoTickers(_texts(at), "First steps: Your direction")
        # off: the first steps' screen is the common starting points table
        with self._run(self.fay, "fay", "Get started") as at:
            self.assertTrue([h for h in at.get("html") if "pt-common-points" in h.proto.body])
            self.assertNotIn("Your direction", " ".join(_texts(at)))
            self.assertNoTickers(_texts(at), "First steps: Common starting points")
        with self._run(self.ivy, "ivy", "Plan") as at:
            self.assertNoTickers(_texts(at), "Plan")


class PriceSourceTests(_Base):
    """Where prices are shown, the page says where they come from."""

    @classmethod
    def setup_db(cls, c):
        cls.hal = auth.create_user(c, "hal", "pw-123456789")
        advisor.save_profile(c, cls.hal, PROFILE)
        prefs.save(c, cls.hal, DONE)
        sample_data.load(c, cls.hal)
        c.execute("INSERT INTO price_history (ticker, price, prev_close, change, pct_change, "
                  "fetched_at) VALUES ('VTI', 300.0, 299.0, 1.0, 0.33, '2026-10-02T18:41:00Z')")
        c.execute("INSERT INTO watchlist (user_id, ticker) VALUES (?, 'AAPL')", (cls.hal,))
        c.commit()

    def test_home_ticker_detail_and_watchlist_say_where_prices_come_from(self):
        for page, state in (("Dashboard", {}), ("Dashboard", {"holdings_pill": "VTI"}),
                            ("Watchlist", {}), ("Income", {})):
            with self._run(self.hal, "hal", page, **state) as at:
                status = [h.proto.body for h in at.get("html")
                          if "class='pt-status'" in h.proto.body]
                self.assertEqual(len(status), 1, page)                  # once per page
                self.assertIn(PRICE_SOURCE, status[0], page)
                if state:   # one ticker: its price's time, and that it may lag
                    self.assertTrue(any(c.value.startswith("As of ")
                                        and c.value.endswith("· may be delayed")
                                        for c in at.caption))


class _FakeClient:
    """Records each messages.create call's arguments."""

    def __init__(self, text="- One point"):
        self.calls = []
        outer = self

        class _Messages:
            def create(self, **kw):
                outer.calls.append(kw)
                return unittest.mock.Mock(
                    stop_reason="end_turn",
                    content=[unittest.mock.Mock(type="text", text=text)])
        self.messages = _Messages()


def _no_ai_sink():
    """No database for the AI gateway's checks and counts here (an app run
    earlier in the process may have left its own, since deleted)."""
    import ai_spend
    ai_spend.use_db(None)


class AIGuardrailTests(unittest.TestCase):
    FULL = {**{f: None for f in advisor.PROFILE_FIELDS}, **PROFILE}
    EMPTY = {f: None for f in advisor.PROFILE_FIELDS}

    def setUp(self):
        _no_ai_sink()

    def assertRules(self, system, where):
        for key, rule in advisor.GUARDRAILS:
            self.assertIn(rule, system, f"{where} is missing the {key} rule")

    def test_the_rules_cover_what_they_must(self):
        rules = " ".join(r for _k, r in advisor.GUARDRAILS).lower()
        for must in ("education only", "never recommend buying, selling or holding a specific "
                     "security", "specific allocation", "licensed professional",
                     "you're an ai", "no guarantees", "hypothetical",
                     "explain what kinds of investments are", "describe the person's own figures"):
            self.assertIn(must, rules)

    def test_ask_northwend(self):
        for profile in (self.EMPTY, self.FULL):
            prompt = advisor.system_prompt(profile, "No holdings yet", "- notes")
            self.assertRules(prompt, "Ask Northwend")
            self.assertNotIn("You may name specific funds or tickers", prompt)
            self.assertNotIn("recommendations", prompt.split("## Their profile")[0]
                             .replace("nothing you say is a recommendation", "")
                             .replace("not a recommendation", ""))
        # the chat's own prompt: the shared first block carries every rule, and
        # stream_reply sends it (with the person's card second) through the gateway
        self.assertRules(advisor.chat_rules(), "Ask Northwend's shared block")
        with open(os.path.join(REPO, "advisor.py"), encoding="utf-8") as fh:
            self.assertIn("shared=chat_rules(), card=card", fh.read())
        with open(os.path.join(REPO, "views", "assistant.py"), encoding="utf-8") as fh:
            self.assertIn("advisor.stream_reply(", fh.read())

    def test_meeting_prep(self):
        client = _FakeClient()
        self.assertEqual(meeting.talking_points(client, self.FULL, "No holdings yet", "facts"),
                         ["One point"])
        call, = client.calls
        self.assertRules(call["system"], "Meeting prep")
        self.assertIn("don't recommend buying, selling or holding a specific security",
                      call["messages"][0]["content"])

    def test_plan_pdf_has_no_ai(self):
        # AI_PLAN step 15: rule-based "Questions to look into", no AI call
        with open(os.path.join(REPO, "client_plan.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotRegex(src, r"\.messages\.|anthropic|ai_spend|advisor\.system_prompt")
        with open(os.path.join(REPO, "views", "profile.py"), encoding="utf-8") as fh:
            view = fh.read().split("def _render_plan_export")[1]
        for gone in ("anthropic", "_ai_status", "_ai_record", "next_steps"):
            self.assertNotIn(gone, view)
        self.assertIn("not recommendations", client_plan.QUESTIONS_NOTE)

    def test_every_ai_call_is_known(self):
        # only the gateway calls the API (AI_PLAN 4, steps 4-5; the plan PDF
        # has no AI call any more, step 15): every other
        # module asks ai_gateway.call() for a registered helper. A new AI
        # feature that writes for people must use advisor.system_prompt or
        # the chat's shared block (and so the rules); the others only read
        # files into rows
        import ai_gateway
        advice = {"advisor.py": "chat", "meeting.py": "prep"}
        reading = {"csv_import.py": "csv", "txn_import.py": "txn",
                   "screenshot_read.py": "screenshot"}
        callers, helpers = {}, set()
        found = set()
        for path in glob.glob(os.path.join(REPO, "*.py")) + glob.glob(
                os.path.join(REPO, "views", "*.py")):
            with open(path, encoding="utf-8") as fh:
                src = fh.read()
            if re.search(r"\.messages\.(create|stream|parse)\(", src):
                found.add(os.path.basename(path))
            for helper in re.findall(r"ai_gateway\.call\(\s*\"(\w+)\"", src):
                callers[helper] = os.path.basename(path)
                helpers.add(helper)
        self.assertEqual(found, {"ai_gateway.py"})
        self.assertEqual(helpers, set(ai_gateway.HELPERS))   # every helper registered, and used
        # helpers with rules of their own, checked on the way out (AI_PLAN 9):
        # the glossary's fallback (the conclusion policy's rules) and advisor
        # drafts (the advice is the advisor's, never Northwend's)
        own_rules = {"glossary_ai.py": "glossary", "advisor_drafts.py": "draft"}
        for name, helper in {**advice, **reading, **own_rules}.items():
            self.assertEqual(callers.get(helper), name, helper)
        for name in set(advice) - {"advisor.py"}:
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                self.assertIn("system=advisor.system_prompt(", fh.read(), name)
        # Teach It Back's grader writes for people with its own short prompt,
        # which carries the conclusion policy's rules (teach_back.system_prompt)
        self.assertEqual(callers.get("grader"), "teach_back.py")
        with open(os.path.join(REPO, "teach_back.py"), encoding="utf-8") as fh:
            self.assertIn("SYSTEM + ai_policy.rules_text()", fh.read())
        import advisor_drafts
        import ai_policy
        import glossary_ai
        self.assertTrue(glossary_ai.SYSTEM.startswith(ai_policy.rules_text()))
        self.assertIn("never the software's", advisor_drafts.SYSTEM)
        # the API's own client is still made elsewhere (a key, a timeout), but
        # never asked anything outside the gateway; and the gateway logs nothing
        with open(os.path.join(REPO, "ai_gateway.py"), encoding="utf-8") as fh:
            gateway = fh.read()
        self.assertNotIn("print(", gateway)
        self.assertNotRegex(gateway, r"import logging|logging\.|sys\.std|\.write\(")

    def test_no_helper_carries_dollars_without_zdr(self):
        # AI_PLAN 3.3 / 4.2: a helper that could carry a dollar figure is
        # refused on a hosted copy until AI_ZDR is set; none is marked today
        import ai_gateway
        import settings
        self.assertEqual([s.name for s in ai_gateway.HELPERS.values() if s.carries_dollars], [])
        spec = ai_gateway.HelperSpec("dollars", "claude-sonnet-5", 100, None, False, "chat",
                                     "chat", True, 10.0)
        with unittest.mock.patch.dict(ai_gateway.HELPERS, {"dollars": spec}), \
                unittest.mock.patch.object(settings, "hosted", return_value=True):
            for zdr, refused in (("", True), ("1", False)):
                client = _FakeClient()
                with unittest.mock.patch.dict(os.environ, {"AI_ZDR": zdr}):
                    if refused:
                        with self.assertRaises(ai_gateway.Refused) as cm:
                            ai_gateway.call("dollars", client=client,
                                            messages=[{"role": "user", "content": "x"}])
                        self.assertEqual(cm.exception.why, "zdr")
                        self.assertEqual(cm.exception.calm_text,
                                         "Ask Northwend isn't available right now.")
                        self.assertEqual(client.calls, [])
                    else:
                        ai_gateway.call("dollars", client=client,
                                        messages=[{"role": "user", "content": "x"}])
                        self.assertEqual(len(client.calls), 1)
        # a local copy (not hosted) may run it
        with unittest.mock.patch.dict(ai_gateway.HELPERS, {"dollars": spec}), \
                unittest.mock.patch.object(settings, "hosted", return_value=False):
            client = _FakeClient()
            ai_gateway.call("dollars", client=client, messages=[{"role": "user", "content": "x"}])
            self.assertEqual(len(client.calls), 1)

    def test_no_kind_of_adviser_is_suggested(self):
        # Northwend never suggests a person needs an advisor, or names a kind to find
        # (AI_PLAN.md 2.3): a licensed professional of their choosing, if they want one
        rules = " ".join(r for _k, r in advisor.GUARDRAILS).lower()
        self.assertIn("licensed professional of their choosing", rules)
        for word in ("fee-only", "fiduciary adviser", "such as a"):
            self.assertNotIn(word, rules)


class PrivacyWordingTests(unittest.TestCase):
    """Audit X3 / 1.3d: what the app says it keeps and sends stays true."""

    def read(self, *path):
        with open(os.path.join(REPO, *path), encoding="utf-8") as fh:
            return " ".join(fh.read().split())

    def test_the_trust_lines_say_what_is_saved(self):
        src = self.read("dashboard.py")
        lines = src.split("TRUST_LINE = (")[1].split("def ")[0].replace('" "', "")
        for untrue in ("never balances", "balances and gains", "Only symbols, share counts"):
            self.assertNotIn(untrue, lines)
        self.assertIn("symbols, shares, cost, value and cash", lines)
        self.assertIn("brokerage login", lines.split("NOT_KEPT")[1])

    def test_the_screenshot_reader_says_what_the_ai_sees(self):
        view = self.read("views", "holdings_input.py").split("def _render_screenshot_reader")[1]
        view = view.split("\ndef ")[0].replace('" "', "")
        self.assertIn("sees the whole picture", view)
        self.assertIn("including balances and account names", view)
        self.assertIn("Optional", view)
        import disclosures
        about = " ".join(" ".join(t for _h, t in disclosures.SECTIONS).split())
        self.assertIn("sees everything on them - including balances, account names", about)
        self.assertIn("never dollar amounts or account numbers", about)   # the guide's notes
        policy = self.read("docs", "legal", "privacy-policy-DRAFT.md")
        self.assertIn("including balances, account names", policy)

    def test_the_website_promise_is_about_the_holdings(self):
        home = self.read("website", "templates", "home.html")
        self.assertIn("Your holdings reach Ask Northwend as percentages - never dollar "
                      "amounts", home)
        self.assertNotIn("Only symbols, shares and cost are saved", home)
        for page in ("home.html", "advisors.html"):   # screenshots are off in production
            self.assertNotIn("screenshot", self.read("website", "templates", page).lower())

    def test_a_former_clients_delete_is_explained(self):
        import disclosures
        about = " ".join(" ".join(t for _h, t in disclosures.SECTIONS).split())
        self.assertIn("If you used to have an advisor:", about)
        self.assertIn("their notes, the proposals and reports they sent you", about)
        self.assertIn("If you used to have an advisor:",
                      self.read("docs", "legal", "privacy-policy-DRAFT.md"))


class MemoryFiguresTests(unittest.TestCase):
    """PLAN D9 / audit 1.4b: Ask Northwend's notes keep goals, dates and
    decisions - never dollar amounts, account names or numbers."""

    def setUp(self):
        _no_ai_sink()

    def test_the_instruction_keeps_no_amounts(self):
        prompt = advisor.system_prompt({f: None for f in advisor.PROFILE_FIELDS}, "No holdings")
        notes = prompt.split("## Your notes from earlier conversations")[1].split("##")[0]
        self.assertNotIn("amounts, life events", notes)
        self.assertIn("Never keep dollar amounts", notes)
        self.assertIn("account names or account numbers", notes)
        self.assertIn("never dollar amounts", advisor.MEMORY_TOOL["description"])
        notes = advisor.chat_rules().split("## Your notes")[1].split("##")[0]
        self.assertIn("Never keep dollar amounts", notes)
        self.assertIn("account names or account numbers", notes)

    def test_figures_are_taken_out_before_saving(self):
        cases = {
            "- saving $12,000 for a car": "- saving [amount] for a car",
            "- 12k dollars in savings": "- [amount] in savings",
            "- Acct 1234 is the Roth": "- Acct [number] is the Roth",
            "- Roth IRA ...678": "- Roth IRA [number]",
            "- has 25,000 in cash, 50000 more later": "- has [amount] in cash, [number] more later",
            "- goal 1.5m, or 5 million dollars": "- goal [amount], or [amount]",
            "- USD 5000 / 250 bucks / $500/month": "- [amount] / [amount] / [amount]/month",
            "- account #98765, acct x4321": "- account [number], acct [number]",
            "- the Schwab one, Z12345678": "- the Schwab one, [number]",
        }
        for raw, clean in cases.items():
            notes, error = advisor.validate_memory_input(
                {"notes": [{"kind": "context", "text": raw}]})
            self.assertEqual(error, "", raw)
            self.assertEqual([n.text for n in notes], [clean[2:]], raw)   # one line, no bullet
        # a note can't even be made holding a figure (the type checks itself)
        with self.assertRaises(ValueError):
            advisor.MemoryNote("context", "saving $12,000 for a car")
        with self.assertRaises(ValueError):
            advisor.MemoryNote("amounts", "a kind that isn't one")
        self.assertEqual(advisor.note("worry", "Acct 1234 is the Roth").text,
                         "Acct [number] is the Roth")

    def test_dates_ages_and_account_types_stay(self):
        for keep in ("- house ~2029\n- avoid crypto", "- retire at 60 in 2045, 7% return",
                     "- maxes 401(k), 401k match, 403b", "- sold on 2026-03-14",
                     "- years 2025-2030", "- S&P 500 fund, a 2050 target date fund",
                     "- brokerage account 2", "- FY2026 bonus, a 2050s goal"):
            self.assertEqual(advisor.scrub_memory(keep), keep)

    def test_notes_already_saved_are_scrubbed_before_the_prompt(self):
        prompt = advisor.system_prompt({f: None for f in advisor.PROFILE_FIELDS}, "No holdings",
                                       "- house ~2029, has $40,000 saved in Acct 5521")
        self.assertIn("house ~2029", prompt)
        for figure in ("40,000", "5521"):
            self.assertNotIn(figure, prompt)

    def test_the_model_is_told_when_figures_were_taken_out(self):
        ns = types.SimpleNamespace
        block = ns(type="tool_use", id="tu_m", name="save_memory",
                   input={"notes": [{"kind": "context", "text": "down payment $60k by 2028"}]})
        turns = [ns(stop_reason="tool_use", content=[block]), ns(stop_reason="end_turn",
                                                                  content=[])]

        class _Stream:
            def __init__(self, message):
                self.message = message

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def __iter__(self):
                return iter(())

            def get_final_message(self):
                return self.message

        class _Client:
            calls = []

            @property
            def messages(self):
                return self

            def stream(self, **kw):
                self.calls.append({**kw, "messages": list(kw["messages"])})
                return _Stream(turns.pop(0))
        client = _Client()
        saved = []
        list(advisor.stream_reply(client, [{"role": "user", "content": "x"}], "sys",
                                  lambda f: None, saved.append))
        self.assertEqual(saved, [(advisor.MemoryNote("context", "down payment [amount] by 2028"),)])
        result = client.calls[1]["messages"][-1]["content"][0]["content"]
        self.assertIn("amounts and account numbers taken out", result)


if __name__ == "__main__":
    unittest.main()
