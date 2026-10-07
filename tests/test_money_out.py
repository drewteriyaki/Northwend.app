"""Money going out of a plan (ROADMAP 12): planned expenses and a regular
withdrawal, the month-by-month projection in plans.py, storage and who may
change it, and the Plan / Home pages drawn with streamlit's AppTest on a
scratch database in a temp dir.

    python -m unittest tests.test_money_out        (from the repo root)
"""

import contextlib
import csv
import io
import os
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock
import zipfile
from datetime import date

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import admin  # noqa: E402
import advisor  # noqa: E402
import auth  # noqa: E402
import client_plan  # noqa: E402
import export  # noqa: E402
import manual_entry  # noqa: E402
import plans  # noqa: E402
import portfolio  # noqa: E402
import proposals  # noqa: E402
import sample_data  # noqa: E402
import two_step  # noqa: E402

TODAY = date(2026, 10, 5)


def _expense(amount, on, label="A car", times=1, every=12):
    return {"kind": "expense", "label": label, "amount": amount, "start_date": on,
            "times": times, "every_months": every}


def _withdrawal(amount, on, end=None, rise=None):
    return {"kind": "withdrawal", "label": "Regular withdrawal", "amount": amount,
            "start_date": on, "end_date": end, "inflation_pct": rise, "times": 1,
            "every_months": 1}


class ProjectionMathsTests(unittest.TestCase):
    PLAN = {"target_amount": 500000, "target_date": "2046-10-05", "monthly_contribution": 800}

    def test_no_money_out_is_the_closed_form(self):
        for items in (None, []):
            self.assertEqual(plans.progress(self.PLAN, 50000, today=TODAY, items=items),
                             plans.progress(self.PLAN, 50000, today=TODAY))
            self.assertEqual(plans.projection_series(50000, 800, 240, today=TODAY, items=items),
                             plans.projection_series(50000, 800, 240, today=TODAY))
            self.assertEqual(plans.value_at(50000, 800, 6, 240, items, today=TODAY),
                             plans.future_value(50000, 800, 6, 240))
            self.assertEqual(plans.required_monthly(50000, 500000, 6, 240, items, today=TODAY),
                             plans.required_monthly(50000, 500000, 6, 240))
        # the month-by-month walk with nothing out agrees with the formula
        walk = plans.simulate(50000, 800, 6, 240)["values"][-1]
        self.assertAlmostEqual(walk, plans.future_value(50000, 800, 6, 240), places=4)
        # an expense already past changes nothing
        past = [_expense(9000, "2026-01-01")]
        self.assertAlmostEqual(plans.progress(self.PLAN, 50000, today=TODAY, items=past)["projected"],
                               plans.future_value(50000, 800, 6, 240), places=4)

    def test_a_one_off_expense(self):
        car = [_expense(20000, "2027-06-01")]
        # Jun 1 2027 comes out at the month-end on or after it: Jun 5 2027, month 8
        self.assertEqual(plans.out_schedule(car, TODAY, 240), {8: 20000.0})
        p = plans.progress(self.PLAN, 50000, today=TODAY, items=car)
        r = (1.06) ** (1 / 12) - 1
        # the same as the closed form less the car, grown for the 232 months after it
        self.assertAlmostEqual(p["projected"], plans.future_value(50000, 800, 6, 240)
                               - 20000 * (1 + r) ** 232, places=4)
        self.assertAlmostEqual(p["projected_without"], plans.future_value(50000, 800, 6, 240))
        self.assertEqual(p["out_by_goal"], 20000.0)
        self.assertLess(p["projected_low"], p["projected"])
        self.assertLess(p["projected"], p["projected_high"])
        # the dip is in the chart: the month before and the month of it
        rows = plans.projection_series(50000, 800, 240, today=TODAY, items=car)
        by_date = {r["date"]: r["mid"] for r in rows}
        self.assertLess(by_date["2027-06-05"], by_date["2027-05-05"])
        self.assertEqual(plans.out_markers(car, TODAY, 240),
                         [{"date": "2027-06-05", "kind": "expense", "label": "A car"}])

    def test_a_repeating_expense(self):
        tuition = [_expense(15000, "2030-09-01", "Tuition", times=4)]
        sched = plans.out_schedule(tuition, TODAY, 240)
        self.assertEqual(sorted(sched), [47, 59, 71, 83])         # each fall, 4 years
        self.assertEqual(set(sched.values()), {15000.0})
        self.assertEqual(plans.out_schedule(tuition, TODAY, 60), {47: 15000.0, 59: 15000.0})
        self.assertEqual(plans.when_text(tuition[0]), "each year for 4 years from Sep 2030")
        self.assertEqual(plans.money_out_text(tuition), "Tuition, $15,000 each year for 4 years "
                                                        "from Sep 2030")

    def test_withdrawals_with_and_without_inflation(self):
        flat = [_withdrawal(2000, "2027-01-05")]
        sched = plans.out_schedule(flat, TODAY, 40)
        self.assertEqual(min(sched), 3)
        self.assertEqual(set(sched.values()), {2000.0})
        self.assertEqual(len(sched), 38)
        rising = [_withdrawal(2000, "2027-01-05", rise=2.5)]
        sched = plans.out_schedule(rising, TODAY, 40)
        self.assertEqual(sched[3], 2000.0)                        # its first year
        self.assertEqual(sched[14], 2000.0)
        self.assertAlmostEqual(sched[15], 2050.0)                 # a year on: 2.5% more
        self.assertAlmostEqual(sched[27], 2000 * 1.025 ** 2)
        # with an end date it stops
        ends = [_withdrawal(2000, "2027-01-05", end="2027-12-31")]
        self.assertEqual(sorted(plans.out_schedule(ends, TODAY, 40)), list(range(3, 15)))
        # money stops being added when the withdrawal starts
        self.assertEqual(plans.adding_stops(flat, TODAY), 3)
        walk = plans.simulate(1000, 100, 0, 5, add_until=3)["values"]
        self.assertEqual(walk, [1000, 1100, 1200, 1200, 1200, 1200])
        self.assertEqual(plans.when_text(rising[0]), "a month from Jan 2027, rising 2.5% a year")

    def test_runs_out_month(self):
        # 10,000 at no growth, 1,000 a month from the first month: ten months, then short
        items = [_withdrawal(1000, "2026-11-05")]
        out = plans.simulate(10000, 0, 0, 24, plans.out_schedule(items, TODAY, 24))
        self.assertEqual(out["runs_out"], 11)
        self.assertEqual(out["values"][10], 0)
        self.assertEqual(min(out["values"]), 0)                    # never below nothing
        last = plans.lasting(10000, 0, 0, items, today=TODAY)
        self.assertEqual(last["runs_out"], 11)
        self.assertEqual(last["horizon"], 1 + plans.LAST_YEARS * 12)
        self.assertEqual(last["less"], 1000.0)                     # nothing, at no growth
        self.assertIsNone(last["later"])                           # waiting doesn't grow it
        # with growth and an age: some less a month, or a later start, lasts to 95
        big = [_withdrawal(4000, "2046-11-01", rise=2.5)]
        last = plans.lasting(50000, 800, 6, big, today=TODAY, age=40)
        self.assertEqual(last["horizon"], (plans.LAST_AGE - 40) * 12)
        self.assertIsNotNone(last["runs_out"])
        self.assertEqual(last["less"] % 50, 0)
        fixed = [{**big[0], "amount": 4000 - last["less"]}]
        self.assertIsNone(plans.lasting(50000, 800, 6, fixed, today=TODAY, age=40)["runs_out"])
        not_quite = [{**big[0], "amount": 4000 - last["less"] + 60}]
        self.assertIsNotNone(plans.lasting(50000, 800, 6, not_quite, today=TODAY,
                                           age=40)["runs_out"])
        later = [{**big[0], "start_date": plans.add_months(date(2046, 11, 1),
                                                           12 * last["later"]).isoformat()}]
        self.assertIsNone(plans.lasting(50000, 800, 6, later, today=TODAY, age=40)["runs_out"])
        self.assertIsNone(plans.lasting(50000, 800, 6, [_expense(1, "2030-01-01")], today=TODAY))
        self.assertEqual(plans.age_from({"age_range": "35-44"}), 40)
        self.assertIsNone(plans.age_from({}))

    def test_required_monthly_with_money_out(self):
        car = [_expense(20000, "2027-06-01")]
        need = plans.required_monthly(50000, 500000, 6, 240, car, today=TODAY)
        self.assertGreater(need, plans.required_monthly(50000, 500000, 6, 240))
        self.assertAlmostEqual(plans.value_at(50000, need, 6, 240, car, today=TODAY), 500000,
                               delta=5)
        self.assertEqual(plans.progress(self.PLAN, 50000, today=TODAY, items=car)["needed_monthly"],
                         need)
        # growth alone gets there even after the car
        self.assertEqual(plans.required_monthly(900000, 500000, 6, 240, car, today=TODAY), 0.0)
        # withdrawals already going: nothing more is added, nothing reaches it
        going = [_withdrawal(100, "2026-01-01")]
        self.assertIsNone(plans.required_monthly(1000, 500000, 6, 240, going, today=TODAY))
        # a status that was on track can fall behind
        plan = {"target_amount": 450000, "target_date": "2046-10-05", "monthly_contribution": 800}
        self.assertEqual(plans.progress(plan, 50000, today=TODAY)["status"], "on_track")
        self.assertIn(plans.progress(plan, 50000, today=TODAY,
                                     items=[_expense(100000, "2027-06-01")])["status"],
                      ("within_reach", "behind"))

    def test_proposal_compare_takes_money_out(self):
        car = [_expense(20000, "2027-06-01")]
        a = proposals.compare({"Stocks": 60, "Bonds": 40}, {"Stocks": 80, "Bonds": 20},
                              value=50000, monthly=800, months=240)
        b = proposals.compare({"Stocks": 60, "Bonds": 40}, {"Stocks": 80, "Bonds": 20},
                              value=50000, monthly=800, months=240, items=car, on=TODAY)
        self.assertLess(b["projected"][0], a["projected"][0])
        self.assertLess(b["projected"][1], a["projected"][1])


class MoneyOutStorageTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_mo_")
        self.db = os.path.join(self.dir, "test.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.conn = portfolio.connect(self.db)
        c = self.conn
        self.owner = auth.create_user(c, "owner", "pw-123456789")
        self.stranger = auth.create_user(c, "stranger", "pw-123456789")
        self.adv = auth.create_user(c, "adv", "pw-123456789")
        auth.set_advisor(c, "adv", True)
        self.client = auth.create_client(c, self.adv, "client1")
        self.other_adv = auth.create_user(c, "otheradv", "pw-123456789")
        auth.set_advisor(c, "otheradv", True)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_add_change_list_and_remove(self):
        c, me = self.conn, self.owner
        car = plans.add_money_out(c, me, "expense", {"label": " A car ", "amount": 20000,
                                                     "start_date": "2027-06-01"}, by=me)
        plans.add_money_out(c, me, "expense", {"label": "Tuition", "amount": 15000,
                                               "start_date": "2030-09-01", "times": 4}, by=me)
        w = plans.add_money_out(c, me, "withdrawal", {"amount": 2000, "start_date": "2035-01-01",
                                                      "inflation_pct": 2.5}, by=me)
        items = plans.list_money_out(c, me)
        self.assertEqual([i["label"] for i in items], ["A car", "Tuition", "Regular withdrawal"])
        self.assertEqual(items[1]["times"], 4)
        self.assertEqual(items[2]["inflation_pct"], 2.5)
        self.assertEqual({i["set_by"] for i in items}, {me})
        # one regular withdrawal: setting it again changes that one
        again = plans.add_money_out(c, me, "withdrawal", {"amount": 2500,
                                                          "start_date": "2036-01-01"}, by=me)
        self.assertEqual(again, w)
        w_row = plans.get_withdrawal(plans.list_money_out(c, me))
        self.assertEqual((w_row["amount"], w_row["start_date"]), (2500.0, "2036-01-01"))
        plans.update_money_out(c, me, car, {"amount": 18000}, by=me)
        self.assertEqual(plans.list_money_out(c, me)[0]["amount"], 18000.0)
        self.assertEqual(plans.list_money_out(c, me)[0]["label"], "A car")   # kept
        self.assertTrue(plans.delete_money_out(c, me, car, by=me))
        self.assertFalse(plans.delete_money_out(c, me, car, by=me))
        self.assertEqual(len(plans.list_money_out(c, me)), 2)
        self.assertEqual(plans.list_money_out(c, self.stranger), [])

    def test_bad_input_is_refused(self):
        c, me = self.conn, self.owner
        for kind, fields in (("expense", {"label": "x", "amount": 0, "start_date": "2027-01-01"}),
                             ("expense", {"label": "", "amount": 5, "start_date": "2027-01-01"}),
                             ("expense", {"label": "x", "amount": 5, "start_date": "soon"}),
                             ("withdrawal", {"amount": 5, "start_date": "2030-01-01",
                                             "end_date": "2029-01-01"}),
                             ("gift", {"label": "x", "amount": 5, "start_date": "2027-01-01"})):
            with self.assertRaises(ValueError):
                plans.add_money_out(c, me, kind, fields, by=me)
        self.assertEqual(plans.list_money_out(c, me), [])

    def test_who_may_change_it(self):
        c = self.conn
        item = {"label": "Roof", "amount": 12000, "start_date": "2028-04-01"}
        # the owner, on their own account
        self.assertTrue(plans.may_change(c, self.owner, self.owner))
        # nobody else
        for who in (self.stranger, self.adv):
            with self.assertRaises(PermissionError):
                plans.add_money_out(c, self.owner, "expense", item, by=who)
            with self.assertRaises(PermissionError):
                plans.list_money_out(c, self.owner, viewer=who)
        # the client's advisor, recorded as who saved it - like the plan
        made = plans.add_money_out(c, self.client, "expense", item, by=self.adv)
        self.assertEqual(plans.list_money_out(c, self.client, viewer=self.adv)[0]["set_by"],
                         self.adv)
        # a managed client reads it, but the plan is their advisor's to change
        self.assertEqual(len(plans.list_money_out(c, self.client, viewer=self.client)), 1)
        with self.assertRaises(PermissionError):
            plans.update_money_out(c, self.client, made, {"amount": 1}, by=self.client)
        # another advisor can't touch it, or someone else's item by id
        for who in (self.other_adv, self.stranger):
            with self.assertRaises(PermissionError):
                plans.delete_money_out(c, self.client, made, by=who)
        with self.assertRaises(LookupError):
            plans.update_money_out(c, self.owner, made, {"amount": 1}, by=self.owner)
        self.assertFalse(plans.delete_money_out(c, self.owner, made, by=self.owner))
        self.assertEqual(len(plans.list_money_out(c, self.client)), 1)

    def test_exported_and_cleared_with_the_account(self):
        c, me = self.conn, self.owner
        plans.add_money_out(c, me, "expense", {"label": "A car", "amount": 20000,
                                               "start_date": "2027-06-01"}, by=me)
        plans.add_money_out(c, self.client, "expense", {"label": "Roof", "amount": 9000,
                                                        "start_date": "2028-06-01"}, by=self.adv)
        z = zipfile.ZipFile(io.BytesIO(export.export_zip(c, me)))
        self.assertIn("money_going_out.csv", z.namelist())
        rows = list(csv.DictReader(io.StringIO(z.read("money_going_out.csv").decode("utf-8-sig"))))
        self.assertEqual([r["label"] for r in rows], ["A car"])
        self.assertIn("money_going_out.csv", z.read("README.txt").decode())
        self.assertIn("money_out", admin.ACCOUNT_TABLES)
        self.assertIn("set_by", admin.ACCOUNT_REFERENCES["money_out"])

    def test_client_plan_pdf_mentions_it(self):
        c = self.conn
        plans.save_plan(c, self.client, {"goal_type": "Retirement", "target_amount": 500000,
                                         "target_date": "2050-01-01",
                                         "monthly_contribution": 400}, set_by=self.adv)
        before = client_plan.build_facts(c, self.client, [], {})
        plans.add_money_out(c, self.client, "withdrawal", {"amount": 2000,
                                                           "start_date": "2050-02-01"}, by=self.adv)
        plans.add_money_out(c, self.client, "expense", {"label": "A car", "amount": 20000,
                                                        "start_date": "2030-06-01"}, by=self.adv)
        facts = client_plan.build_facts(c, self.client, [], {})
        self.assertEqual(len(facts["money_out"]), 2)
        self.assertLess(facts["goal"]["projected"], before["goal"]["projected"])
        self.assertTrue(client_plan.render_pdf(facts, None, account_name="client1")
                        .startswith(b"%PDF"))


class MoneyOutPageTests(unittest.TestCase):
    """The Plan and Home pages with money going out, drawn with AppTest."""

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_mo_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        today = date.today()
        cls.goal_date = plans.add_months(today, 120).isoformat()
        cls.car_date = plans.add_months(today, 8).isoformat()
        cls.income_date = plans.add_months(today, 121).isoformat()
        goal = {"goal_type": "Retirement", "goal_name": "Retire", "target_amount": 85000,
                "target_date": cls.goal_date, "monthly_contribution": 200}
        c = portfolio.connect(cls.db)
        try:
            # the example portfolio (about 33,340 with cash), a car and an income
            cls.rose = auth.create_user(c, "rose", "pw-123456789")
            sample_data.load(c, cls.rose)
            advisor.save_profile(c, cls.rose, {"goal": "Retirement", "age_range": "55-64",
                                               "time_horizon_years": 10})
            plans.save_plan(c, cls.rose, goal, set_by=cls.rose)
            plans.add_money_out(c, cls.rose, "expense", {"label": "A car", "amount": 20000,
                                                         "start_date": cls.car_date}, by=cls.rose)
            plans.add_money_out(c, cls.rose, "withdrawal",
                                {"amount": 2000, "start_date": cls.income_date,
                                 "inflation_pct": 2.5}, by=cls.rose)
            # the same, with nothing going out
            cls.sam = auth.create_user(c, "sam", "pw-123456789")
            sample_data.load(c, cls.sam)
            advisor.save_profile(c, cls.sam, {"goal": "Retirement", "age_range": "55-64",
                                              "time_horizon_years": 10})
            plans.save_plan(c, cls.sam, goal, set_by=cls.sam)
            # percentages only, with a planned expense
            cls.pat = auth.create_user(c, "pat", "pw-123456789")
            holdings, cash, errors = manual_entry.validate_weights(
                [{"Symbol": "VTI", "Percent": 60, "Type": "ETF"},
                 {"Symbol": "BND", "Percent": 30, "Type": "ETF"}], 10, 10000)
            assert not errors, errors
            meta, rows, totals, errors = manual_entry.build_weights(
                holdings, cash, 10000, {"VTI": {"price": 300.0}, "BND": {"price": 72.0}},
                today=today)
            portfolio.write_snapshot(c, cls.pat, meta, rows, totals, manual_entry.PCT_SOURCE)
            plans.save_plan(c, cls.pat, goal, set_by=cls.pat)
            plans.add_money_out(c, cls.pat, "expense", {"label": "A car", "amount": 20000,
                                                        "start_date": cls.car_date}, by=cls.pat)
            # an advisor and her client
            cls.carol = auth.create_user(c, "carol", "pw-123456789")
            auth.set_advisor(c, "carol", True)
            c.execute("UPDATE users SET email = 'carol@example.com', email_verified_at = "
                      "'2026-09-01T10:00:00Z' WHERE id = ?", (cls.carol,))
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dana = auth.create_client(c, cls.carol, "dana")
            sample_data.load(c, cls.dana)
            plans.save_plan(c, cls.dana, goal, set_by=cls.carol)
            plans.add_money_out(c, cls.dana, "expense", {"label": "A car", "amount": 20000,
                                                         "start_date": cls.car_date}, by=cls.carol)
            c.commit()
        finally:
            c.close()

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
                unittest.mock.patch("socket.socket.connect", offline_net.connect):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    @staticmethod
    def _text(at):
        return " ".join([m.value for m in at.markdown] + [c.value for c in at.caption]
                        + [i.value for i in at.info])

    @staticmethod
    def _html(at):
        return " ".join(h.proto.body for h in at.get("html"))

    @staticmethod
    def _can_edit(at):
        return any(n.label == "Take out each month ($)" for n in at.number_input)

    def _tab_text(self, at, label):
        tab = next(t for t in at.tabs if t.label == label)
        return " ".join([m.value for m in tab.markdown] + [c.value for c in tab.caption]
                        + [i.value for i in tab.info])

    def test_plan_takes_the_car_and_the_income_out(self):
        with self._run(self.rose, "rose", "Plan") as at:
            labels = [t.label for t in at.tabs]
            self.assertIn("Money going out", labels)
            going = self._tab_text(at, "How it's going")
            self.assertIn("With a car in", going)
            self.assertIn("instead of", going)
            self.assertIn("more a month gets you back on track", going)
            self.assertIn(r"Taking \$2,000 a month from", going)
            self.assertIn("rising 2.5% a year", going)
            self.assertIn("runs out in", going)            # 33k can't pay 2,000 a month for long
            self.assertIn("Dotted lines are planned expenses", going)
            self.assertNotIn("you should", going.lower())
            # the same lines on Money going out, and the list
            out = self._tab_text(at, "Money going out")
            lasting = re.search(r"Taking .*? a year\.", going).group(0)
            self.assertIn(lasting, out)
            self.assertIn("A car", self._html(at))
            # Retirement income uses the plan's withdrawal: the same figures
            retire = self._tab_text(at, "Retirement income")
            self.assertIn(lasting, retire)
            self.assertEqual(at.number_input(key="retire_yearly").value, 24000.0)
            # the goal card counts the car: behind, where the same plan without it is on track
            self.assertIn("pt-chip pt-down'>Behind", self._html(at))
        with self._run(self.sam, "sam", "Plan") as at:
            self.assertIn("pt-chip pt-up'>On track", self._html(at))
            self.assertNotIn("With a car", self._text(at))
            self.assertIn("would still be paying", self._tab_text(at, "Retirement income"))

    def test_home_on_track_signal_counts_it(self):
        with self._run(self.rose, "rose", "Dashboard") as at:
            self.assertIn("'>Behind<", self._html(at))
        with self._run(self.sam, "sam", "Dashboard") as at:
            self.assertIn("'>On track<", self._html(at))

    def test_hidden_amounts(self):
        with self._run(self.rose, "rose", "Plan", hide_amounts=True) as at:
            going = self._tab_text(at, "How it's going")
            self.assertIn("With a car in", going)
            self.assertIn("Taking ••• a month from", going)
            self.assertIn("rising 2.5% a year", going)     # percentages and years stay
            self.assertNotIn("2,000", going + self._tab_text(at, "Money going out"))
            self.assertNotIn("20,000", self._html(at))
            self.assertIn("Show amounts", self._tab_text(at, "Money going out"))
            self.assertFalse(self._can_edit(at))   # no forms while amounts are hidden

    def test_percentages_only(self):
        with self._run(self.pat, "pat", "Plan") as at:
            out = self._tab_text(at, "Money going out")
            self.assertIn("percentages of a pretend total", out)
            self.assertNotIn("With a car in", self._text(at))

    def test_advisor_on_a_clients_plan(self):
        with self._run(self.carol, "carol", "Plan", active_user_id=self.dana,
                       two_step_ok=self.carol_ok) as at:
            self.assertIn("With a car in", self._tab_text(at, "How it's going"))
            self.assertTrue(self._can_edit(at))     # she can change it
        # the client sees it, read-only
        with self._run(self.dana, "dana", "Plan") as at:
            out = self._tab_text(at, "Money going out")
            self.assertIn("sets these with you", out)
            self.assertFalse(self._can_edit(at))

    def test_adding_an_expense_on_the_page(self):
        with self._run(self.sam, "sam", "Plan") as at:
            next(t for t in at.text_input if t.label == "What it's for").set_value("A boat")
            amount = next(n for n in at.number_input if n.label == "Amount ($)")
            amount.set_value(5000.0)
            next(b for b in at.button if b.label == "Save expense").click().run()
            self.assertEqual([e.message for e in at.exception], [])
        c = portfolio.connect(self.db)
        try:
            items = plans.list_money_out(c, self.sam)
            self.assertEqual([(i["label"], i["amount"]) for i in items], [("A boat", 5000.0)])
            plans.delete_money_out(c, self.sam, items[0]["id"], by=self.sam)
        finally:
            c.close()


if __name__ == "__main__":
    unittest.main()
