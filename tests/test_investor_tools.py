"""The investor tools (ROADMAP overnight plan 3-6): Stress test your mix
(stress.py), where the next deposit could go (next_deposit.py), Cash check
(cash_check.py) and the Free money check (employer_match.py) - the maths,
and the pages that show them drawn by AppTest.

    python -m unittest tests.test_investor_tools        (from the repo root)
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

import advisor  # noqa: E402
import auth  # noqa: E402
import cash_check  # noqa: E402
import employer_match as em  # noqa: E402
import manual_entry  # noqa: E402
import next_deposit as nd  # noqa: E402
import plans  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import proposals  # noqa: E402
import sample_data  # noqa: E402
import stress  # noqa: E402


class StressTests(unittest.TestCase):
    def test_three_stretches_with_2020(self):
        self.assertEqual([s["key"] for s in stress.SCENARIOS], ["2008", "2020", "2022"])
        for s in stress.SCENARIOS:
            self.assertEqual(set(s["drop"]), {"Stocks", "Bonds", "Cash", "Other"})
            self.assertEqual(set(s["pace"]), set(s["drop"]))

    def test_drop_is_the_weighted_mix(self):
        s = stress.BY_KEY["2008"]
        self.assertAlmostEqual(stress.drop_pct({"Stocks": 100}, s), -50.0)
        self.assertAlmostEqual(stress.drop_pct({"Stocks": 60, "Bonds": 40}, s), -28.0)
        # the same weighted mix as the proposal card's hard years
        mix = {"Stocks": 70, "Bonds": 20, "Cash": 10}
        self.assertAlmostEqual(stress.drop_pct(mix, s), proposals._mix_return(mix, s["drop"]))
        # shares that don't add up to 100 are scaled
        self.assertAlmostEqual(stress.drop_pct({"Stocks": 30, "Bonds": 20}, s), -28.0)
        self.assertIsNone(stress.drop_pct({}, s))

    def test_2020_and_2022(self):
        s20, s22 = stress.BY_KEY["2020"], stress.BY_KEY["2022"]
        self.assertAlmostEqual(stress.drop_pct({"Stocks": 100}, s20), -34.0)
        # 2022: bonds fell too, so a 60/40 mix lost nearly as much as in 2020
        self.assertLess(stress.drop_pct({"Bonds": 100}, s22), -10)
        self.assertAlmostEqual(stress.drop_pct({"Stocks": 60, "Bonds": 40}, s22),
                               0.6 * -25 + 0.4 * -16)

    def test_recovery_times(self):
        s08, s20, s22 = (stress.BY_KEY[k] for k in ("2008", "2020", "2022"))
        stocks = {"Stocks": 100}
        # quick in 2020, years in 2008
        self.assertLess(stress.months_back(stocks, s20), 12)
        self.assertGreater(stress.months_back(stocks, s08), 36)
        # a gentler mix falls less and is back sooner in 2008
        self.assertLess(stress.months_back({"Stocks": 60, "Bonds": 40}, s08),
                        stress.months_back(stocks, s08))
        # 2022's bonds took years
        self.assertGreater(stress.months_back({"Bonds": 100}, s22), 24)
        # something that never fell is back at once
        self.assertEqual(stress.months_back({"Cash": 100}, s08), 0)
        self.assertEqual(stress.months_back({"Bonds": 100}, s08), 0)
        # never back within the cap
        self.assertIsNone(stress.months_back(stocks, s08, cap=6))

    def test_run_in_dollars(self):
        rows = stress.run({"Stocks": 60, "Bonds": 40}, 100_000)
        self.assertEqual([r["key"] for r in rows], ["2008", "2020", "2022"])
        self.assertAlmostEqual(rows[0]["drop_usd"], -28_000)
        self.assertIsNone(stress.run({"Stocks": 100})[0]["drop_usd"])
        self.assertEqual(stress.worst(rows)["key"], "2008")
        self.assertEqual(stress.run({}), [])

    def test_time_words(self):
        self.assertEqual(stress.time_text(7), "about 7 months")
        self.assertEqual(stress.time_text(1), "about 1 month")
        self.assertEqual(stress.time_text(30), "about 2½ years")
        self.assertEqual(stress.time_text(36), "about 3 years")
        self.assertEqual(stress.time_text(None), "more than 20 years")


class NextDepositTests(unittest.TestCase):
    NOW = {"Stocks": 70_000.0, "Bonds": 20_000.0, "Cash": 10_000.0}
    TARGET = {"Stocks": 60.0, "Bonds": 40.0}

    @staticmethod
    def _distance(current, target, add):
        total = sum(current.values()) + sum(add.values())
        t = {k: v / sum(target.values()) for k, v in target.items()}
        return sum(((current.get(k, 0) + add.get(k, 0)) / total - t.get(k, 0)) ** 2
                   for k in set(current) | set(t))

    def test_never_sells_and_adds_up(self):
        for amount in (1, 100, 999.5, 5_000, 40_000, 250_000):
            with self.subTest(amount):
                add = nd.split(self.NOW, self.TARGET, amount)
                self.assertTrue(all(v >= 0 for v in add.values()))
                self.assertAlmostEqual(sum(add.values()), amount, places=6)
                self.assertNotIn("Cash", add)    # no target: nothing goes there

    def test_small_deposit_goes_to_the_furthest_below(self):
        self.assertEqual(nd.split(self.NOW, self.TARGET, 1000), {"Bonds": 1000})
        self.assertEqual(nd.words({"Bonds": 1000.0}), "entirely to bonds")

    def test_lands_closest_to_target(self):
        # against every split in steps of 5% of the deposit
        current = {"Stocks": 5000.0, "Bonds": 3000.0, "Cash": 500.0, "Other": 1500.0}
        target = {"Stocks": 50, "Bonds": 30, "Cash": 5, "Other": 15}
        for amount in (500.0, 2000.0, 9000.0):
            best = nd.split(current, target, amount)
            d_best = self._distance(current, target, best)
            steps = range(21)
            for a, b, c in itertools.product(steps, steps, steps):
                if a + b + c > 20:
                    continue
                trial = {"Stocks": a / 20 * amount, "Bonds": b / 20 * amount,
                         "Cash": c / 20 * amount, "Other": (20 - a - b - c) / 20 * amount}
                self.assertLessEqual(d_best, self._distance(current, target, trial) + 1e-12)

    def test_a_big_deposit_reaches_the_target(self):
        current = {"Stocks": 70_000.0, "Bonds": 30_000.0}
        need = nd.to_reach(current, self.TARGET)
        self.assertAlmostEqual(need, 70_000 / 0.6 - 100_000)
        add = nd.split(current, self.TARGET, need + 1000)
        after = nd.mix_pct({k: current.get(k, 0) + add.get(k, 0) for k in self.TARGET})
        self.assertAlmostEqual(after["Stocks"], 60.0, places=6)
        # already at target: shared in the target's proportions
        add = nd.split({"Stocks": 600.0, "Bonds": 400.0}, self.TARGET, 100)
        self.assertAlmostEqual(add["Stocks"], 60.0)
        self.assertEqual(nd.to_reach({"Stocks": 600.0, "Bonds": 400.0}, self.TARGET), 0.0)

    def test_money_in_an_untargeted_class_cannot_be_fixed_by_adding(self):
        self.assertIsNone(nd.to_reach(self.NOW, self.TARGET))

    def test_plan_rows_and_rounding(self):
        r = nd.plan(self.NOW, self.TARGET, 1234.56)
        self.assertEqual(sum(r["add"].values()), 1235)
        self.assertTrue(all(float(v).is_integer() for v in r["add"].values()))
        self.assertEqual([x["class"] for x in r["rows"]], ["Stocks", "Bonds", "Cash"])
        self.assertLess(r["gap_after"], r["gap_before"])
        bonds = r["rows"][1]
        self.assertAlmostEqual(bonds["now_pct"], 20.0)
        self.assertGreater(bonds["after_pct"], 20.0)

    def test_nothing_to_split(self):
        self.assertEqual(nd.split(self.NOW, {}, 100), {})
        self.assertEqual(nd.split(self.NOW, self.TARGET, 0), {})
        self.assertEqual(nd.split({}, self.TARGET, 100), {"Stocks": 60.0, "Bonds": 40.0})
        self.assertEqual(nd.words({}), "")
        self.assertEqual(nd.words({"Stocks": 50.0, "Bonds": 50.0}), "to stocks and bonds")
        self.assertEqual(nd.words({"Other": 90.0, "Bonds": 10.0}), "mostly to other holdings")


class CashCheckTests(unittest.TestCase):
    def test_thresholds(self):
        self.assertTrue(cash_check.summary(1000, 0, 10_000)["show"])          # 10%
        self.assertFalse(cash_check.summary(900, 0, 10_000)["show"])          # 9%, $900
        self.assertTrue(cash_check.summary(5000, 0, 200_000)["show"])         # $5,000
        self.assertFalse(cash_check.summary(4999, 0, 200_000)["show"])
        self.assertTrue(cash_check.summary(2000, 3000, 200_000)["show"])      # both kinds count
        self.assertFalse(cash_check.summary(0, 0, 10_000)["show"])
        self.assertFalse(cash_check.summary(100, 0, 0)["show"])               # nothing to compare

    def test_pretend_dollars_count_only_as_a_share(self):
        self.assertFalse(cash_check.summary(9000, 0, 100_000, pretend=True)["show"])
        self.assertTrue(cash_check.summary(10_000, 0, 100_000, pretend=True)["show"])

    def test_figures(self):
        s = cash_check.summary(8000, 2000, 50_000)
        self.assertEqual((s["cash"], s["sweep"], s["money_market"]), (10_000, 8000, 2000))
        self.assertAlmostEqual(s["pct"], 20.0)
        self.assertAlmostEqual(s["per_point"], 100.0)
        self.assertEqual(cash_check.mostly(s), "sweep")
        self.assertEqual(cash_check.mostly(cash_check.summary(100, 900, 1000)), "money_market")
        self.assertEqual(cash_check.mostly(cash_check.summary(500, 500, 1000)), "both")
        self.assertAlmostEqual(cash_check.yearly_at(10_000, 4), 400.0)
        self.assertEqual(cash_check.yearly_at(-5, 4), 0.0)


class EmployerMatchTests(unittest.TestCase):
    def test_half_of_the_first_six(self):
        tiers = em.PRESET_TIERS["50% of the first 6%"]
        r = em.check(60_000, 4, tiers)
        self.assertAlmostEqual(r["match_pct"], 2.0)
        self.assertAlmostEqual(r["match_yearly"], 1200)
        self.assertAlmostEqual(r["max_pct"], 3.0)
        self.assertAlmostEqual(r["max_yearly"], 1800)
        self.assertAlmostEqual(r["missing_yearly"], 600)
        self.assertEqual(r["full_at"], 6.0)
        self.assertFalse(r["getting_all"])
        self.assertAlmostEqual(r["you_yearly"], 2400)

    def test_safe_harbor_two_tiers(self):
        tiers = em.PRESET_TIERS["100% of the first 3%, then 50% of the next 2%"]
        self.assertAlmostEqual(em.match_pct(3, tiers), 3.0)
        self.assertAlmostEqual(em.match_pct(4, tiers), 3.5)
        self.assertAlmostEqual(em.match_pct(5, tiers), 4.0)
        self.assertAlmostEqual(em.match_pct(10, tiers), 4.0)    # nothing past the cap
        self.assertEqual(em.full_at(tiers), 5.0)
        self.assertEqual(em.describe(tiers), "100% of the first 3%, then 50% of the next 2%")

    def test_every_preset_reads_as_its_label(self):
        for label, tiers in em.PRESETS:
            self.assertEqual(em.describe(tiers), label)

    def test_full_match_and_over(self):
        r = em.check(80_000, 8, em.PRESET_TIERS["100% of the first 4%"])
        self.assertTrue(r["getting_all"])
        self.assertAlmostEqual(r["match_yearly"], 3200)
        self.assertEqual(r["missing_yearly"], 0)

    def test_edges(self):
        tiers = em.PRESET_TIERS["100% of the first 6%"]
        r = em.check(None, 3, tiers)                      # no salary: shares of pay only
        self.assertIsNone(r["match_yearly"])
        self.assertAlmostEqual(r["missing_pct"], 3.0)
        r = em.check(50_000, 0, tiers)                    # putting nothing in
        self.assertEqual(r["match_yearly"], 0)
        self.assertAlmostEqual(r["missing_yearly"], 3000)
        r = em.check(-5, -2, tiers)                       # nonsense in, nothing out
        self.assertEqual((r["you_pct"], r["match_pct"]), (0.0, 0.0))
        self.assertIsNone(r["match_yearly"])
        r = em.check(50_000, 5, ())                       # no match at all
        self.assertFalse(r["has_match"])
        self.assertTrue(r["getting_all"])

    def test_custom(self):
        self.assertEqual(em.tiers_for(em.CUSTOM, 25, 8), ((25.0, 8.0),))
        self.assertEqual(em.tiers_for(em.CUSTOM, 0, 8), ())
        self.assertEqual(em.tiers_for("50% of the first 6%"), ((50.0, 6.0),))
        r = em.check(100_000, 8, em.tiers_for(em.CUSTOM, 25, 8))
        self.assertAlmostEqual(r["match_yearly"], 2000)

    def test_saved_inputs_are_checked(self):
        self.assertEqual(em.clean_saved({"salary": 70000, "contrib_pct": 5, "preset": "nope",
                                         "rate": "x", "up_to": 500}),
                         {"salary": 70000.0, "contrib_pct": 5.0})
        self.assertEqual(em.clean_saved("junk"), {})
        self.assertEqual(em.clean_saved({"preset": em.CUSTOM})["preset"], em.CUSTOM)


class ToolPageTests(unittest.TestCase):
    """The tools on Home, Plan and Learn, drawn by AppTest with Yahoo out of
    reach: alice has the example portfolio with more cash and a target mix;
    nina has no holdings; pat a percentages portfolio."""

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_tools_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        conn = portfolio.connect(cls.db)
        cls.alice = auth.create_user(conn, "alice", "pw-123456")
        cls.nina = auth.create_user(conn, "nina", "pw-123456")
        cls.pat = auth.create_user(conn, "pat", "pw-123456")
        for uid in (cls.alice, cls.pat):
            sample_data.load(conn, uid)
            # $8,240 of plain cash with the Roth IRA's $240: a meaningful share
            conn.execute("UPDATE account_totals SET cash_value = 8000 WHERE user_id = ? AND "
                         "account = 'Brokerage'", (uid,))
        conn.execute("UPDATE snapshots SET source_file = ? WHERE user_id = ?",
                     (manual_entry.PCT_SOURCE, cls.pat))
        for uid in (cls.alice, cls.pat, cls.nina):
            plans.save_plan(conn, uid, {"goal_type": "Retirement", "target_amount": 500_000.0,
                                        "target_date": "2050-01-01",
                                        "monthly_contribution": 400.0,
                                        "target_alloc": {"Stocks": 60.0, "Bonds": 40.0}},
                            set_by=uid)
            advisor.save_profile(conn, uid, {"employer_match":
                                             "Yes, but I'm not getting all of it"})
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _run(self, uid, name, page, **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": page, "auto_backfilled": True,
                     "income_synced": True, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused")
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    @staticmethod
    def _html(at):
        return " ".join(h.proto.body for h in at.get("html"))

    @staticmethod
    def _text(at):
        return " ".join([m.value for m in at.markdown] + [c.value for c in at.caption])

    @staticmethod
    def _tab(at, label):
        return next(t for t in at.tabs if t.label == label)

    # ---- Home ------------------------------------------------------------ #
    def test_home_one_card_with_cash_check(self):
        with self._run(self.alice, "alice", "Dashboard") as at:
            body = self._html(at)
            self.assertEqual(body.count("Your money, checked"), 1)
            self.assertIn("Fee check", body)
            self.assertIn("Cash check", body)
            self.assertRegex(body, r"About <span style='font-weight:600'>\$8,240</span> "
                                   r"\(\d+% of your portfolio\) is in cash")
            # the drift notice has where the next deposit could go
            self.assertIn("your next deposit could go", self._text(at))
            at.button(key="cash_open").click().run()
            self.assertTrue(at.session_state["dialog_open"])
            text = self._text(at)
            self.assertIn("often called a *sweep*", text)
            self.assertIn("Each 1% a year of interest on your \\$8,240 of cash is about "
                          "**\\$82 a year**", text)
            self.assertIn("no rate is promised", text)
            self.assertNotRegex(text, r"\b(SPAXX|VMFXX|SWVXX|Fidelity|Vanguard|Schwab)\b")

    def test_home_hidden_amounts(self):
        with self._run(self.alice, "alice", "Dashboard", hide_amounts=True) as at:
            body = self._html(at)
            self.assertIn("About <span style='font-weight:600'>•••</span> (•••", body)
            at.button(key="cash_open").click().run()
            self.assertIn("about **••• a year**", self._text(at))

    def test_home_deposit_link_opens_the_target_mix(self):
        with self._run(self.alice, "alice", "Dashboard") as at:
            at.button(key="dash_deposit").click().run()
            self.assertEqual(at.session_state["page"], "Plan")

    def test_percentages_portfolio_shares_only(self):
        with self._run(self.pat, "pat", "Dashboard") as at:
            self.assertRegex(self._html(at), r"About <span style='font-weight:600'>\d+%</span> "
                                             r"of your portfolio is cash")
            at.button(key="cash_open").click().run()
            self.assertNotIn("Each 1% a year", self._text(at))

    # ---- Plan ------------------------------------------------------------ #
    def test_plan_stress_test(self):
        with self._run(self.alice, "alice", "Plan") as at:
            tab = self._tab(at, "Stress test")
            body = " ".join(h.proto.body for h in tab.get("html"))
            for name in ("2008: the global financial crisis", "2020: the Covid drop",
                         "2022: stocks and bonds both down"):
                self.assertIn(name, body)
            self.assertRegex(body, r"-\$[\d,]+")           # dollars on today's value
            self.assertIn("back to where it started in about", body)
            text = " ".join(m.value for m in tab.markdown) + " ".join(c.value for c in tab.caption)
            self.assertIn("Your mix now:", text)
            self.assertIn("past won't repeat the same way", text)
            # the target mix too
            at.segmented_control(key="stress_pick").set_value("Your target mix").run()
            tab = self._tab(at, "Stress test")
            self.assertIn("**Your target mix:** 60% stocks, 40% bonds",
                          " ".join(m.value for m in tab.markdown))
            self.assertIn("-28%", " ".join(h.proto.body for h in tab.get("html")))

    def test_plan_stress_test_hidden_and_percentages(self):
        with self._run(self.alice, "alice", "Plan", hide_amounts=True) as at:
            body = " ".join(h.proto.body for h in self._tab(at, "Stress test").get("html"))
            self.assertNotRegex(body, r"\$\d")
            self.assertIn("•••", body)
        with self._run(self.pat, "pat", "Plan") as at:
            tab = self._tab(at, "Stress test")
            self.assertNotRegex(" ".join(h.proto.body for h in tab.get("html")), r"\$\d")
            self.assertIn("pretend", " ".join(c.value for c in tab.caption))

    def test_plan_next_deposit(self):
        with self._run(self.alice, "alice", "Plan") as at:
            self.assertEqual(at.number_input(key="deposit_amount").value, 400.0)  # the plan's
            body = " ".join(h.proto.body for h in self._tab(at, "Target mix").get("html"))
            self.assertIn("+$400", body)
            self.assertIn("→", body)
            at.number_input(key="deposit_amount").set_value(5000).run()
            body = " ".join(h.proto.body for h in self._tab(at, "Target mix").get("html"))
            self.assertIn("+$5,000", body)
            self.assertNotIn("VTI", body)
        with self._run(self.alice, "alice", "Plan", hide_amounts=True) as at:
            body = " ".join(h.proto.body for h in self._tab(at, "Target mix").get("html"))
            self.assertIn("100% of it", body)
            self.assertNotRegex(body, r"\$\d")

    def test_plan_free_money_window(self):
        # (AppTest can't change a field inside a window and keep it open, so
        # the fields start filled in, as a remembered answer would)
        with self._run(self.alice, "alice", "Plan", fm_loaded=True, fm_salary=60_000.0,
                       fm_contrib=4.0, fm_preset="50% of the first 6%") as at:
            at.button(key="fm_open_plan").click().run()
            text = self._text(at)
            labels = [h.proto.body for h in at.get("html")]
            self.assertTrue(any("The most they&#x27;d add" in b or "The most they'd add" in b
                                for b in labels))
            self.assertIn("You may be leaving about **\\$600 a year** of free money", text)
            self.assertIn("vesting", text)
            self.assertIn("Check your plan's rules", text)
            # nothing kept unless asked
            with contextlib.closing(portfolio.connect(self.db)) as c:
                self.assertNotIn(em.PREF, prefs.load(c, self.alice))

    def test_plan_without_holdings(self):
        with self._run(self.nina, "nina", "Plan") as at:
            labels = [t.label for t in at.tabs]
            self.assertIn("Stress test", labels)           # the target mix alone
            self.assertNotIn("Target mix", labels)
            text = " ".join(m.value for m in self._tab(at, "Stress test").markdown)
            self.assertIn("Your target mix:", text)

    # ---- Learn ----------------------------------------------------------- #
    def test_learn_readiness_has_the_free_money_check(self):
        with self._run(self.nina, "nina", "Get started", gs_at="ready", fs_hide=True,
                       fm_loaded=True, fm_salary=50_000.0, fm_contrib=6.0,
                       fm_preset="50% of the first 6%") as at:
            at.button(key="fm_open_learn").click().run()
            self.assertIn("You're getting the whole match", self._text(at))
        # hidden amounts: shares of pay, no salary field
        with self._run(self.nina, "nina", "Get started", gs_at="ready", fs_hide=True,
                       hide_amounts=True, fm_loaded=True, fm_salary=50_000.0, fm_contrib=2.0,
                       fm_preset="50% of the first 6%") as at:
            at.button(key="fm_open_learn").click().run()
            self.assertNotIn("fm_salary", [n.key for n in at.number_input])
            self.assertIn("about **2% of pay** a year of free money", self._text(at))

    def test_remembered_numbers(self):
        with contextlib.closing(portfolio.connect(self.db)) as c:
            prefs.save(c, self.nina, {em.PREF: {"salary": 70_000, "contrib_pct": 3,
                                                "preset": "100% of the first 4%"}})
        try:
            with self._run(self.nina, "nina", "Plan") as at:
                at.button(key="fm_open_plan").click().run()
                self.assertEqual(at.number_input(key="fm_salary").value, 70_000)
                self.assertTrue(at.checkbox(key="fm_remember").value)
                self.assertIn("about **\\$700 a year**", self._text(at))
        finally:
            with contextlib.closing(portfolio.connect(self.db)) as c:
                prefs.save(c, self.nina, {})


if __name__ == "__main__":
    unittest.main()
