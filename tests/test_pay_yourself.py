"""Pay yourself (ROADMAP R11; pay_yourself.py, views/pay_yourself.py, flag
pay_yourself + gate L3).

The rules are a fixed, named list the person picks from (income only by
default, nothing else pre-selected); every figure is under the rule picked;
the 20% fall is labelled hypothetical; no line tells anyone to take money out
or calls an amount affordable, lasting or safe (banned words and
ai_policy.findings over every template); only the rule's key is kept. In the
app: off unless the flag and gate L3 are both on; the login's own account
keeps its pick; an advisor in a client's account sees it with the standing
line and saves nothing; an advisor's client signed in themselves doesn't get
the tab; hidden amounts are masked.

    python -m unittest tests.test_pay_yourself        (from the repo root)
"""

import contextlib
import os
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from datetime import date, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import ai_policy  # noqa: E402
import auth  # noqa: E402
import flags  # noqa: E402
import pay_yourself as py  # noqa: E402
import plans  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sample_data  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
TAB = "Pay yourself"
# words that must never appear in what people read (R11's careful version)
NEVER = (r"\bwithdraw\b", r"\bafford", r"\bsafe(?:ly|ty)?\b", r"\bsustainab", r"\bshould\b",
         r"\bbest\b", r"\brecommend", r"\benough\b", r"\bsuggest", r"\bguarantee",
         r"\byou can take\b", r"\btake out \$", r"\bwill last\b", r"\bbetter\b", r"\bworse\b")


def _months(totals, start="2026-10"):
    """income_ahead()-shaped months from a list of 12 totals."""
    y, m = (int(x) for x in start.split("-"))
    out = []
    for t in totals:
        out.append({"month": f"{y:04d}-{m:02d}", "dividends": t, "interest": 0.0, "total": t})
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def _code_words(path):
    """A source file's text without its comment lines (lower case)."""
    with open(path, encoding="utf-8") as fh:
        return "\n".join(line for line in fh.read().lower().splitlines()
                         if not line.lstrip().startswith("#"))


class WordingTests(unittest.TestCase):

    def test_no_banned_words(self):
        text = py.all_text().lower()
        for pat in NEVER:
            self.assertNotRegex(text, pat)
        # the view's own strings (outside comments and docstrings it has none
        # that people read but these labels)
        view = _code_words(os.path.join(REPO, "views", "pay_yourself.py"))
        for pat in (r"\bwithdraw\b", r"\bafford", r"\bsustainab", r"\brecommend",
                    r"\benough\b", r"\"[^\"]*\bshould\b[^\"]*\"", r"\"[^\"]*\bbest\b[^\"]*\""):
            self.assertNotRegex(view, pat)

    def test_every_template_passes_the_conclusion_policy(self):
        for line in py.sample_texts():
            with self.subTest(line=line[:50]):
                self.assertEqual(ai_policy.findings(line, allowed_tickers=set()), [])

    def test_figures_are_under_the_rule_picked_and_the_fall_is_hypothetical(self):
        for t in (py.PAYCHECK_PCT, py.PAYCHECK_INCOME, py.THIN_INCOME, py.THIN_PCT,
                  py.DROP_PCT_LINE, py.DROP_INCOME_LINE, py.EXAMPLE_LINE, py.STAT_PAYCHECK,
                  py.STAT_PAYCHECK_INCOME, py.COVERED_PCT):
            self.assertIn("under the rule you picked", t.lower(), t[:40])
        self.assertIn("Hypothetical, not a forecast, not advice", py.DROP_LABEL)
        self.assertIn("hypothetical", py.STAT_DROP.lower())
        self.assertIn("not a forecast", py.DROP_NOTE)
        self.assertIn("not a forecast, not advice", py.INTRO)

    def test_questions_are_questions_only(self):
        self.assertTrue(py.QUESTIONS)
        for q in py.QUESTIONS:
            self.assertTrue(q.endswith("?"), q)
        joined = " ".join(py.QUESTIONS)
        for topic in ("taxed", "required minimum distributions", "Social Security"):
            self.assertIn(topic, joined)
        self.assertIn("licensed professional", py.QUESTIONS_TITLE)

    def test_the_rules_are_named_and_fixed(self):
        self.assertEqual(py.RULE_KEYS, ("income_only", "pct_3", "pct_4", "pct_5"))
        self.assertEqual(py.DEFAULT, "income_only")
        self.assertIn("4% rule", py.BY_KEY["pct_4"]["name"])
        self.assertIn("rule of thumb", py.BY_KEY["pct_4"]["name"])
        self.assertIn("income only", py.BY_KEY["income_only"]["name"])
        # listed income only first, then by rate - nothing ranks them
        rates = [r["pct"] for r in py.RULES[1:]]
        self.assertEqual(rates, sorted(rates))
        self.assertIn("doesn't rank them", py.PICK_HELP)


class PickTests(unittest.TestCase):

    def test_nothing_picked_is_income_only(self):
        self.assertEqual(py.saved_rule({}), "income_only")
        self.assertEqual(py.saved_rule(None), "income_only")
        self.assertEqual(py.saved_rule({py.PREF: {"rule": "pct_9"}}), "income_only")
        self.assertEqual(py.saved_rule({py.PREF: "pct_4"}), "income_only")
        self.assertEqual(py.rule("nonsense")["key"], "income_only")

    def test_only_a_known_key_is_kept(self):
        kept = py.with_rule({"other": 1}, "pct_4")
        self.assertEqual(kept, {"other": 1, py.PREF: {"rule": "pct_4"}})
        self.assertEqual(py.saved_rule(kept), "pct_4")
        self.assertEqual(py.with_rule({}, "pct_9; drop table"), {})
        self.assertEqual(py.cleared(kept), {"other": 1})


class ArithmeticTests(unittest.TestCase):
    BAL = 300_000.0

    def test_each_rate_rule(self):
        months = _months([100.0] * 12)
        for key, pct in (("pct_3", 3), ("pct_4", 4), ("pct_5", 5)):
            with self.subTest(key):
                pc = py.paycheck(key, self.BAL, months)
                self.assertAlmostEqual(pc["yearly"], self.BAL * pct / 100)
                self.assertAlmostEqual(pc["monthly"], self.BAL * pct / 100 / 12)
                for m in pc["months"]:
                    self.assertAlmostEqual(m["total"], pc["monthly"])
                    self.assertAlmostEqual(m["income"], 100.0)
                    self.assertAlmostEqual(m["from_balance"], pc["monthly"] - 100.0)
                self.assertFalse(pc["covered"])

    def test_income_only_adds_up_the_payouts(self):
        totals = [10, 0, 50, 10, 0, 50, 10, 0, 50, 10, 0, 300.0]
        pc = py.paycheck("income_only", self.BAL, _months(totals))
        self.assertAlmostEqual(pc["yearly"], sum(totals))
        self.assertAlmostEqual(pc["monthly"], round(sum(totals) / 12, 2))
        self.assertEqual([m["total"] for m in pc["months"]], totals)
        self.assertTrue(all(m["from_balance"] == 0 for m in pc["months"]))
        self.assertEqual(pc["thin"]["month"], "2026-11")     # the first of the empty months
        self.assertEqual(pc["full"]["month"], "2027-09")
        # the balance doesn't change it
        self.assertEqual(py.paycheck("income_only", 1.0, _months(totals))["yearly"],
                         pc["yearly"])

    def test_the_thin_month_under_a_rate_rule(self):
        totals = [400.0] * 12
        totals[4] = 25.0
        pc = py.paycheck("pct_4", self.BAL, _months(totals))     # 1,000 a month
        self.assertEqual(pc["thin"]["month"], "2027-02")
        thin = pc["months"][4]
        self.assertAlmostEqual(thin["income"], 25.0)
        self.assertAlmostEqual(thin["from_balance"], 975.0)

    def test_payouts_above_the_paycheck_are_part_of_it(self):
        pc = py.paycheck("pct_3", 12_000.0, _months([100.0] * 12))   # 30 a month
        self.assertTrue(pc["covered"])
        self.assertTrue(all(m["income"] == 30.0 and m["total"] == 30.0 for m in pc["months"]))

    def test_no_payouts(self):
        pc = py.paycheck("income_only", self.BAL, _months([0.0] * 12))
        self.assertIsNone(pc["thin"])
        self.assertEqual(pc["monthly"], 0)
        pc = py.paycheck("pct_4", self.BAL, [])
        self.assertAlmostEqual(pc["monthly"], 1000.0)

    def test_the_hypothetical_fall(self):
        months = _months([100.0] * 12)
        for key, pct in (("pct_3", 3), ("pct_4", 4), ("pct_5", 5)):
            d = py.after_drop(key, self.BAL, months)
            self.assertAlmostEqual(d["before"], self.BAL * pct / 1200)
            self.assertAlmostEqual(d["after"], self.BAL * 0.8 * pct / 1200)
            self.assertAlmostEqual(d["lower_balance"], self.BAL * 0.8)
            self.assertAlmostEqual(d["kept_pct"], pct / 0.8)
        d = py.after_drop("income_only", self.BAL, months)
        self.assertEqual((d["before"], d["after"], d["kept_pct"]), (100.0, 100.0, None))

    def test_income_ahead_adds_last_years_cash_interest_by_month(self):
        sched = [{"month": "2026-10", "total": 5.0}, {"month": "2026-11", "total": 0.0}]
        got = [{"month": "2025-11", "by_symbol": {"Interest": 3.0, "VTI": 9.0}},
               {"month": "2026-03", "by_symbol": {"Interest": 1.0}}]
        out = py.income_ahead(sched, got)
        self.assertEqual(out, [
            {"month": "2026-10", "dividends": 5.0, "interest": 0.0, "total": 5.0},
            {"month": "2026-11", "dividends": 0.0, "interest": 3.0, "total": 3.0}])
        self.assertEqual(py.income_ahead(sched, None)[1]["total"], 0.0)

    def test_labels(self):
        self.assertEqual(py.month_label("2026-11"), "Nov 2026")
        self.assertEqual(py.short_name("pct_4"), "4% a year")
        self.assertEqual(py.short_name("income_only"), "income only")
        self.assertEqual(py.pct_text(5.0), "5")
        self.assertEqual(py.pct_text(3.75), "3.75")


class FlagTests(unittest.TestCase):

    def test_needs_the_flag_and_gate_l3(self):
        self.assertEqual(flags.FEATURES["pay_yourself"],
                         {"gates": ("L3",), "view": "pay_yourself"})
        with unittest.mock.patch.object(flags, "_secret", lambda name: None):
            for f, g, want in (("", "", False), ("pay_yourself", "", False),
                               ("", "L3", False), ("pay_yourself", "L0", False),
                               ("pay_yourself", "L3", True)):
                with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": f,
                                                           "NORTHWEND_GATES": g}):
                    self.assertEqual(flags.on("pay_yourself"), want, (f, g))
                    self.assertEqual(flags.view_on("pay_yourself"), want, (f, g))

    def test_never_in_the_ai_or_an_advisors_files(self):
        for name in ("advisor.py", "context_card.py", "ai_gateway.py", "ai_tools.py",
                     "meeting.py", "reports.py", "overview.py", "weekly_email.py",
                     "client_plan.py", os.path.join("views", "assistant.py"),
                     os.path.join("views", "clients.py")):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                self.assertNotIn("pay_yourself", fh.read(), name)


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
        cls.dir = tempfile.mkdtemp(prefix="pt_pay_yourself_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.alice = auth.create_user(c, "alice", PW)
            sample_data.load(c, cls.alice)
            cls.carol = auth.create_user(c, "carol", PW)
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            prefs.save(c, cls.carol, {"advisor_card": {"name": "Carol Reyes",
                                                       "firm": "Reyes Wealth"}})
            cls.dana = auth.create_user(c, "dana", PW)
            sample_data.load(c, cls.dana)
            auth.link_client(c, cls.carol, cls.dana)
            goal = {"goal_type": "Retirement", "goal_name": "Retire", "target_amount": 85000,
                    "target_date": plans.add_months(date.today(), 120).isoformat(),
                    "monthly_contribution": 200}
            plans.save_plan(c, cls.alice, goal, set_by=cls.alice)
            plans.save_plan(c, cls.dana, goal, set_by=cls.carol)
            # a past year of payouts: BND every month, VTI once (made-up figures)
            today = date.today()
            for k in range(1, 12):
                d = (today.replace(day=1) - timedelta(days=1))
                for _ in range(k - 1):
                    d = d.replace(day=1) - timedelta(days=1)
                c.execute("INSERT INTO daily_bars (ticker, date, close, dividend) "
                          "VALUES ('BND', ?, 73.0, 0.2)", (d.replace(day=10).isoformat(),))
            c.execute("INSERT INTO daily_bars (ticker, date, close, dividend) "
                      "VALUES ('VTI', ?, 300.0, 1.5)",
                      ((today - timedelta(days=40)).isoformat(),))
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _app(self, uid, name, flag="pay_yourself", gates="L3", **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": "Plan",
                     "auto_backfilled": True, "income_synced": True, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                   NORTHWEND_FLAGS=flag, NORTHWEND_GATES=gates)
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    @staticmethod
    def _labels(at):
        return [t.label for t in at.tabs]

    @staticmethod
    def _tab(at):
        return next(t for t in at.tabs if t.label == TAB)

    def _tab_text(self, at):
        tab = self._tab(at)
        return " ".join([m.value for m in tab.markdown] + [c.value for c in tab.caption]
                        + [i.value for i in tab.info])

    @staticmethod
    def _html(at):
        return " ".join(h.proto.body for h in at.get("html"))

    def _prefs(self, uid):
        c = portfolio.connect(self.db)
        try:
            return prefs.load(c, uid)
        finally:
            c.close()

    def test_off_without_the_flag_or_the_gate(self):
        for flag, gates in (("", ""), ("pay_yourself", ""), ("", "L3")):
            with self.subTest(flag=flag, gates=gates), \
                    self._app(self.alice, "alice", flag=flag, gates=gates) as at:
                self.assertIn("Money going out", self._labels(at))
                self.assertNotIn(TAB, self._labels(at))

    def test_nothing_picked_shows_income_only(self):
        with self._app(self.alice, "alice") as at:
            labels = self._labels(at)
            self.assertEqual(labels.index(TAB), labels.index("Money going out") + 1)
            radio = at.radio(key=f"pay_rule_{self.alice}")
            self.assertEqual(radio.value, "income_only")
            text = self._tab_text(at)
            self.assertIn("Under the rule you picked (income only)", text)
            self.assertIn("the thinnest month is", text)
            self.assertNotIn("4% of today's", text)
            self.assertIn("Hypothetical, not a forecast, not advice", text)
            self.assertIn("doesn't change them by itself", text)
            self.assertIn(py.QUESTIONS[0].replace("$", r"\$"), text)
            self.assertIn(py.STAT_THIN, self._html(at))
            for pat in NEVER:
                self.assertNotRegex(text.lower(), pat)
        self.assertNotIn(py.PREF, self._prefs(self.alice))   # nothing kept until picked

    def test_picking_a_rule_keeps_only_its_key(self):
        with self._app(self.alice, "alice") as at:
            at.radio(key=f"pay_rule_{self.alice}").set_value("pct_4").run()
            self.assertEqual([e.message for e in at.exception], [])
            text = self._tab_text(at)
            self.assertIn("Under the rule you picked (4% a year)", text)
            self.assertIn("If your investments fell 20%, this rule would give about", text)
            self.assertIn("% of the lower balance", text)
            # the arithmetic on the page: 4% of today's balance, a twelfth a month
            m = re.search(r"about \\\$([\d,]+) a month - \\\$([\d,]+) a year, 4% of today's "
                          r"\\\$([\d,]+)", text)
            self.assertIsNotNone(m, text)
            monthly, yearly, bal = (float(g.replace(",", "")) for g in m.groups())
            self.assertAlmostEqual(yearly, bal * 0.04, delta=1)
            self.assertAlmostEqual(monthly, bal * 0.04 / 12, delta=1)
        self.assertEqual(self._prefs(self.alice)[py.PREF], {"rule": "pct_4"})
        # the next visit starts at the kept rule
        with self._app(self.alice, "alice") as at:
            self.assertEqual(at.radio(key=f"pay_rule_{self.alice}").value, "pct_4")
        c = portfolio.connect(self.db)
        try:
            prefs.save(c, self.alice, py.cleared(prefs.load(c, self.alice)))
        finally:
            c.close()

    def test_hidden_amounts(self):
        with self._app(self.alice, "alice", hide_amounts=True) as at:
            at.radio(key=f"pay_rule_{self.alice}").set_value("pct_5").run()
            text = self._tab_text(at)
            self.assertIn("•••", text)
            self.assertIn("5% of today's", text)               # percentages stay
            self.assertNotRegex(text, r"\$\d")
            self.assertNotRegex(self._html(at).split(py.STAT_PAYCHECK)[-1][:400], r"\$\d")
            df = self._tab(at).dataframe[0].value
            self.assertTrue(all(v == "•••" for v in df[py.TABLE_COLUMNS[3]]))
        c = portfolio.connect(self.db)
        try:
            prefs.save(c, self.alice, py.cleared(prefs.load(c, self.alice)))
        finally:
            c.close()

    def test_an_advisor_in_a_clients_account_sees_it_with_the_standing_line(self):
        with self._app(self.carol, "carol", active_user_id=self.dana,
                       two_step_ok=self.carol_ok) as at:
            self.assertIn(TAB, self._labels(at))
            text = self._tab_text(at)
            self.assertIn("For you as their advisor", text)
            self.assertIn("This is Carol Reyes's advice, from Reyes Wealth - not Northwend's",
                          text)
            self.assertNotIn(py.KEPT_LINE, text)
            at.radio(key=f"pay_rule_adv_{self.dana}").set_value("pct_3").run()
            self.assertEqual([e.message for e in at.exception], [])
            self.assertIn("Under the rule you picked (3% a year)", self._tab_text(at))
        self.assertNotIn(py.PREF, self._prefs(self.dana))    # never saved to the client
        self.assertNotIn(py.PREF, self._prefs(self.carol))

    def test_an_advisors_client_signed_in_doesnt_get_it(self):
        with self._app(self.dana, "dana") as at:
            self.assertIn("Money going out", self._labels(at))
            self.assertNotIn(TAB, self._labels(at))


if __name__ == "__main__":
    unittest.main()
