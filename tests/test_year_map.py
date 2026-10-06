"""Year in review (recap.py, views/year_review.py) and the account map
(account_map.py, views/account_map.py), ROADMAP 9 and 10.

The recap's maths for a year with and without an imported activity history,
the share version with no dollar figures, hidden amounts and pretend
portfolios; the account map's saving, its PDF, its privacy (never shown to an
advisor, in Export everything, deleted with the account) and Home's line.

    python -m unittest tests.test_year_map        (from the repo root)
"""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock
import zipfile
from datetime import date, datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import account_map  # noqa: E402
import admin  # noqa: E402
import auth  # noqa: E402
import export  # noqa: E402
import perf  # noqa: E402
import plans  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import recap  # noqa: E402

PW = "pw-123456789"
TODAY = date(2026, 10, 5)
# VTI's close at the end of each month (BND stays at 70): Dec of the year
# before, then January to October
VTI = {0: 200, 1: 210, 2: 205, 3: 180, 4: 195, 5: 215, 6: 220, 7: 225, 8: 222, 9: 230, 10: 232}


def _ym(year, m):
    return (year - 1, 12) if m == 0 else (year, m)


def seed(conn, uid, today=TODAY, *, imported=False):
    """Two accounts brought in last November (VTI in a Roth IRA, BND and
    cash in an individual account) and updated in June, a year of closes,
    two visits' values, money added by hand in February and April - and,
    with `imported`, an activity export: a deposit in May and a dividend in
    June (and a hand entry inside it, which the export replaces)."""
    y = today.year
    for snap, vti_qty in ((f"{y - 1}-11-15", 10), (f"{y}-06-01", 12)):
        rows = [{"snapshot_date": snap, "account": "Roth IRA ...641", "symbol": "VTI",
                 "description": "Total market fund", "asset_type": "ETF",
                 "quantity": vti_qty, "cost_basis": 1800.0, "market_value": vti_qty * 200.0},
                {"snapshot_date": snap, "account": "Individual ...222", "symbol": "BND",
                 "description": "Bond fund", "asset_type": "ETF", "quantity": 20,
                 "cost_basis": 1500.0, "market_value": 1400.0}]
        totals = {"Individual ...222": {"cash_value": 600.0, "reported_cost_basis": None,
                                        "reported_market_value": None, "reported_gain": None,
                                        "reported_gain_pct": None}}
        portfolio.write_snapshot(conn, uid, {"snapshot_date": snap, "as_of_text": None},
                                 rows, totals, "upload: positions.csv")
    for m, px in VTI.items():
        yy, mm = _ym(y, m)
        for day in (3, 25):
            d = date(yy, mm, day)
            if d > today:
                continue
            for t, close in (("VTI", float(px)), ("BND", 70.0)):
                div = 0.25 if t == "BND" and day == 3 and mm in (3, 6) and yy == y else None
                conn.execute("INSERT INTO daily_bars (ticker, date, close, dividend) VALUES "
                             "(?, ?, ?, ?) ON CONFLICT DO NOTHING", (t, d.isoformat(), close, div))
    for when, snap, value in ((f"{y - 1}-12-20T15:00:00Z", f"{y - 1}-11-15", 4100.0),
                              (f"{y}-03-10T15:00:00Z", f"{y - 1}-11-15", 3900.0)):
        conn.execute("INSERT INTO value_log (logged_at, snapshot_date, source, portfolio_value, "
                     "user_id) VALUES (?, ?, 'app_open', ?, ?)", (when, snap, value, uid))
    plans.add_contribution(conn, uid, f"{y}-02-03", 500)
    plans.add_contribution(conn, uid, f"{y}-04-05", 500)
    if imported:
        plans.add_contribution(conn, uid, f"{y}-05-20", 300)   # inside the export: not counted
        for d, action, sym, amount in ((f"{y}-05-02", "DEPOSIT", None, 1000.0),
                                       (f"{y}-06-15", "DIV", "BND", 5.0)):
            conn.execute("INSERT INTO transactions (user_id, account, trade_date, action, "
                         "symbol, amount, origin) VALUES (?, ?, ?, ?, ?, ?, 'imported')",
                         (uid, "Individual ...222", d, action, sym, amount))
    conn.commit()


def _value(px):
    return 12 * px + 20 * 70 + 600


class _DB(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="pt_yearmap_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        cls.conn = portfolio.connect(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        shutil.rmtree(cls.dir, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Year in review
# --------------------------------------------------------------------------- #
class RecapMathsTests(_DB):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        c = cls.conn
        cls.ann = auth.create_user(c, "ann", PW)
        seed(c, cls.ann)
        cls.bea = auth.create_user(c, "bea", PW)
        seed(c, cls.bea, imported=True)

    def build(self, uid, year=2026, **kw):
        basis = perf._basis(self.conn, uid)
        return recap.build(self.conn, uid, year, TODAY, basis=basis, **kw)

    def test_monthly_moves_and_the_years_move(self):
        series = [("2025-12-31", 100.0), ("2026-01-15", 105.0), ("2026-01-31", 110.0),
                  ("2026-02-27", 99.0), ("2026-03-31", 108.9)]
        months = recap.monthly_moves(series, 2026, "2026-10-05")
        self.assertEqual([(m["month"], m["pct"], m["partial"]) for m in months],
                         [("2026-01", 10.0, False), ("2026-02", -10.0, False),
                          ("2026-03", 10.0, False)])
        self.assertEqual(recap.year_move(series, 2026, "2026-10-05"), (8.9, None))
        # a series starting inside the year: from its first value ("since")
        late = series[2:]
        self.assertEqual(recap.monthly_moves(late, 2026, "2026-10-05")[0]["month"], "2026-02")
        self.assertEqual(recap.year_move(late, 2026, "2026-10-05"), (-1.0, "2026-01-31"))
        self.assertEqual(recap.year_move([], 2026, "2026-10-05"), (None, None))

    def test_the_year_so_far_without_imported_history(self):
        r = self.build(self.ann, current_value=4900.0)
        self.assertTrue(r["so_far"])
        self.assertTrue(r["money"])
        # money added: the two hand entries
        self.assertEqual((r["added"], r["moves"], r["months_added"]),
                         (1000.0, 2, ["2026-02", "2026-04"]))
        # start: the last value before January 1 (a visit on Dec 20); end: today's
        self.assertEqual((r["value_start"], r["value_start_day"]), (4100.0, "2026-01-01"))
        self.assertEqual((r["value_end"], r["value_end_day"]), (4900.0, "2026-10-05"))
        self.assertEqual(r["growth"], round(4900 - 4100 - 1000, 2))
        # dividends: no export, so worked out from the payments x shares held
        self.assertEqual(r["income"], {"total": 10.0, "dividends": 10.0, "interest": 0.0,
                                       "payments": 2, "source": "estimated", "since": None})
        # month by month: the holdings now at each month's last close
        want = {f"2026-{m:02d}": round((_value(VTI[m]) / _value(VTI[m - 1]) - 1) * 100, 2)
                for m in range(1, 11)}
        self.assertEqual({m["month"]: m["pct"] for m in r["months"]}, want)
        self.assertEqual(r["worst"]["month"], "2026-03")
        self.assertEqual(r["best"]["month"], max(want, key=want.get))
        self.assertEqual(r["market_move"], round((_value(232) / _value(200) - 1) * 100, 2))
        self.assertIsNone(r["market_since"])
        self.assertEqual((r["months_invested"], r["investing_since"]), (10, "2025-11-15"))
        self.assertIn("March was a hard month", r["perspective"])   # a drop of more than 5%
        self.assertEqual(r["notes"], 0)   # no notes to future you written

    def test_the_year_so_far_with_imported_history(self):
        r = self.build(self.bea, current_value=5000.0)
        # the export's deposit counts; the hand entry inside the export doesn't
        self.assertEqual(r["added"], 2000.0)
        self.assertEqual(r["months_added"], ["2026-02", "2026-04", "2026-05"])
        # dividends: the brokerage's own figures, since the export starts
        self.assertEqual(r["income"], {"total": 5.0, "dividends": 5.0, "interest": 0.0,
                                       "payments": 1, "source": "brokerage",
                                       "since": "2026-05-02"})
        self.assertEqual(r["growth"], round(5000 - 4100 - 2000, 2))

    def test_a_whole_past_year(self):
        r = self.build(self.ann, year=2025, current_value=4900.0)
        self.assertFalse(r["so_far"])
        self.assertEqual(r["end"], "2025-12-31")
        # nothing before the year: from the first value inside it; today's value isn't used
        self.assertEqual((r["value_start"], r["value_start_day"]), (4000.0, "2025-11-15"))
        self.assertEqual((r["value_end"], r["value_end_day"]), (4100.0, "2025-12-20"))
        self.assertEqual((r["added"], r["growth"]), (0.0, 100.0))
        self.assertEqual(r["months_invested"], 2)
        self.assertEqual(recap.january_year(date(2027, 1, 20)), 2026)
        self.assertIsNone(recap.january_year(date(2027, 2, 1)))

    def test_milestones_steps_and_reads_of_the_year(self):
        p = {"gear_dates": {"map": {"on": "2026-02-01"}, "boots": {"by": "2025-12-01"}},
             recap.LEARN_DATES: {"basics": "2026-03-01", "mix": "2025-06-01"},
             recap.LEARN_READS: {"basics:funds": "2026-03-01", "basics:fees": "2026-03-02",
                                 "basics:time": "2025-01-01"}}
        r = self.build(self.ann, prefs=p, current_value=4900.0)
        self.assertEqual(r["gear"], ["map"])
        self.assertEqual(r["steps"], ["profile", "basics"])   # the map is About you
        self.assertEqual(r["reads"], ["basics:fees", "basics:funds"])
        self.assertTrue(recap.note_done(p, recap.LEARN_DATES, "goal", date(2026, 5, 1)))
        self.assertFalse(recap.note_done(p, recap.LEARN_DATES, "goal", date(2026, 6, 1)))
        self.assertEqual(p[recap.LEARN_DATES]["goal"], "2026-05-01")   # the first time kept

    def test_notes_to_future_you_written_that_year(self):
        import future_notes
        c = self.conn
        uid = auth.create_user(c, "nia.yr", PW)
        for sym, when in (("VTI", "2026-03-01T10:00:00Z"), (None, "2026-10-05T23:00:00Z"),
                          ("BND", "2025-05-01T10:00:00Z")):
            future_notes.save(c, uid, sym, "Stay the course", now=when)
        self.assertEqual(recap.notes_written(c, uid, "2026-01-01", "2026-10-05"), 2)
        self.assertEqual(recap.notes_written(c, uid, "2025-01-01", "2025-12-31"), 1)
        # a copy of the app without the notes table skips them quietly
        with unittest.mock.patch.object(recap, "NOTES_TABLE", "no_such_table"):
            self.assertIsNone(recap.notes_written(c, uid, "2026-01-01", "2026-10-05"))

    def test_pretend_portfolios_show_no_money(self):
        for src in recap.PRETEND_SOURCES:
            r = self.build(self.ann, pretend=src, current_value=4900.0)
            self.assertFalse(r["money"])
            for k in ("added", "income", "value_start", "value_end", "growth"):
                self.assertIsNone(r[k], (src, k))
        # a percentages portfolio's weights are real: its percent moves stay
        self.assertTrue(self.build(self.ann, pretend="percentages")["months"])
        self.assertEqual(self.build(self.ann, pretend="sample portfolio")["months"], [])

    def test_the_share_version_has_no_dollar_figures(self):
        r = self.build(self.bea, current_value=5000.0,
                       prefs={"gear_dates": {"lantern": {"on": "2026-05-01"}},
                              recap.LEARN_READS: {"basics:funds": "2026-03-01"}})
        text = recap.share_text(r)
        self.assertNotIn("$", text)
        self.assertFalse(recap.has_money(text))
        for amount in (r["added"], r["value_end"], r["value_start"], r["growth"],
                       r["income"]["total"]):
            shown = [f"{amount:,.2f}"] + ([f"{abs(amount):,.0f}"] if abs(amount) >= 100 else [])
            for s in shown:
                self.assertNotIn(s, text, amount)
        self.assertIn("Best month", text)
        self.assertIn("Added money in 3 months", text)
        self.assertIn("Lantern", text)
        self.assertIn("1 read", text)
        self.assertTrue(recap.has_money("added $1,000"))
        self.assertTrue(recap.has_money("value 12,345"))
        pdf = recap.share_pdf(r)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertNotIn(b"$", _pdf_text(pdf))
        self.assertEqual(recap.share_file_name(r), "my-2026-so-far-northwend.pdf")

    def test_an_empty_year(self):
        c = self.conn
        uid = auth.create_user(c, "cal", PW)
        r = recap.build(c, uid, 2026, TODAY, current_value=None)
        self.assertTrue(recap.is_empty(r))
        self.assertIn("Every route starts somewhere", r["perspective"])


def _pdf_text(pdf: bytes) -> bytes:
    """The PDF's page content, inflated (fpdf2 compresses it)."""
    import re
    import zlib
    out = b""
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.S):
        try:
            out += zlib.decompress(m.group(1))
        except zlib.error:
            out += m.group(1)
    return out


# --------------------------------------------------------------------------- #
# Account map
# --------------------------------------------------------------------------- #
class AccountMapTests(_DB):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        c = cls.conn
        cls.dot = auth.create_user(c, "dot", PW)
        seed(c, cls.dot)

    def test_brought_in_accounts_with_a_rough_value(self):
        m = account_map.load(self.conn, self.dot, {"Roth IRA ...641": "My Roth"})
        self.assertEqual([(a["account"], a["name"], a["digits"], a["guess"])
                          for a in m["accounts"]],
                         [("Individual ...222", "Individual ...222", "222", "Taxable brokerage"),
                          ("Roth IRA ...641", "My Roth", "641", "Roth IRA")])
        # each holding at its latest quote, else its own figure, plus cash
        by = {a["account"]: a for a in m["accounts"]}
        self.assertEqual(by["Individual ...222"]["value"], 2000.0)
        self.assertEqual(by["Roth IRA ...641"]["as_of"], "2026-06-01")
        self.assertFalse(m["made"])

    def test_save_change_add_and_remove(self):
        c, uid = self.conn, self.dot
        account_map.save_account(c, uid, "Roth IRA ...641", {
            "kind": "Roth IRA", "contact": "Brokerage help line", "phone": "800-555-0101",
            "beneficiary": "Yes", "paperwork": "Blue folder", "notes": "Opened 2019"})
        account_map.save_account(c, uid, "Roth IRA ...641", {"kind": "Made up kind",
                                                             "beneficiary": "Maybe",
                                                             "phone": "800-555-0101"})
        oid = account_map.save_other(c, uid, {"label": "Credit union savings",
                                              "digits": "1234-5678", "kind": "Bank or savings",
                                              "contact": "Branch"})
        self.assertIsNone(account_map.save_other(c, uid, {"label": "  "}))
        account_map.save_family(c, uid, "My spouse knows the password manager.")
        m = account_map.load(c, uid)
        roth = next(a for a in m["accounts"] if a["account"] == "Roth IRA ...641")
        # a kind or answer not on the list isn't kept; a phone number stays whole
        self.assertEqual((roth["kind"], roth["beneficiary"], roth["phone"], roth["contact"]),
                         (None, None, "800-555-0101", None))
        self.assertEqual([(o["label"], o["digits"], o["kind"]) for o in m["others"]],
                         [("Credit union savings", "678", "Bank or savings")])
        self.assertEqual(m["family"], "My spouse knows the password manager.")
        self.assertTrue(m["made"])
        account_map.save_other(c, uid, {"label": "Credit union", "digits": "9"}, oid)
        self.assertEqual(account_map.load(c, uid)["others"][0]["label"], "Credit union")
        account_map.delete_entry(c, uid, oid)
        account_map.save_family(c, uid, "")
        m = account_map.load(c, uid)
        self.assertEqual((m["others"], m["family"]), ([], None))
        # someone else's id is never touched
        other = auth.create_user(c, "eve.map", PW)
        account_map.save_family(c, other, "Mine")
        eid = c.execute("SELECT id FROM account_map WHERE user_id = ?", (other,)).fetchone()["id"]
        account_map.delete_entry(c, uid, eid)
        self.assertEqual(account_map.load(c, other)["family"], "Mine")
        account_map.clear(c, uid)
        self.assertFalse(account_map.load(c, uid)["made"])

    def test_passwords_are_warned_about(self):
        for text in ("password: hunter2", "The PIN is 1234", "login = me@x.com"):
            self.assertTrue(account_map.looks_secret(text), text)
        for text in ("My spouse knows the password manager.", "Statements in the desk", None):
            self.assertFalse(account_map.looks_secret(text), text)

    def test_the_pdf_builds_with_last_digits_only(self):
        c, uid = self.conn, self.dot
        account_map.save_account(c, uid, "Individual ...222", {"contact": "Ann", "notes":
                                                                "Joint with Sam"})
        account_map.save_family(c, uid, "The will is with our lawyer — call first.")
        pdf = account_map.render_pdf(account_map.load(c, uid), name="Dot", today=TODAY)
        self.assertTrue(pdf.startswith(b"%PDF"))
        text = _pdf_text(pdf)
        self.assertIn(b"...222", text)
        self.assertIn(b"lostandfound.dol.gov", text)
        self.assertEqual(account_map.file_name(TODAY), "account-map-2026-10-05.pdf")
        account_map.clear(c, uid)

    def test_pretend_portfolios_list_no_accounts(self):
        c = self.conn
        import sample_data
        uid = auth.create_user(c, "sam.map", PW)
        sample_data.load(c, uid)
        m = account_map.load(c, uid)
        self.assertEqual((m["accounts"], m["pretend"]), ([], "sample portfolio"))

    def test_in_export_everything_never_in_an_advisors_record_and_deleted(self):
        c = self.conn
        uid = auth.sign_up(c, "fay.map@example.com", PW, seconds_open=10, agreed=True,
                           adult=True, us_resident=True, needs_code=False,
                           terms_version="October 1, 2026")["user_id"]
        account_map.save_family(c, uid, "Call our lawyer first")
        z = zipfile.ZipFile(io.BytesIO(export.export_zip(c, uid)))
        self.assertIn("account_map.csv", z.namelist())
        self.assertIn("Call our lawyer first", z.read("account_map.csv").decode())
        self.assertIn("account_map.csv", z.read("README.txt").decode())
        # an advisor's record of a client never has it
        adv = auth.create_user(c, "gil.map", PW)
        auth.set_advisor(c, "gil.map", True)
        client = auth.create_client(c, adv, "hal.map@example.com", name="Hal")
        account_map.save_family(c, client, "Private to Hal")
        rec = export.client_record(c, adv, client)
        self.assertNotIn("Private to Hal", repr(rec))
        self.assertIn("account_map", admin.ACCOUNT_TABLES)
        self.assertTrue(admin.delete_own(c, uid, PW)["ok"])
        self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM account_map WHERE user_id = ?",
                                   (uid,)).fetchone()["n"], 0)

    def test_homes_line(self):
        self.assertTrue(account_map.nudge(2, False, False))
        self.assertFalse(account_map.nudge(1, False, False))
        self.assertFalse(account_map.nudge(3, True, False))
        self.assertFalse(account_map.nudge(3, False, True))


# --------------------------------------------------------------------------- #
# the app (AppTest)
# --------------------------------------------------------------------------- #
class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_yearmap_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        today = datetime.now().date()
        c = portfolio.connect(cls.db)
        try:
            cls.ivy = auth.create_user(c, "ivy", PW)
            seed(c, cls.ivy, today)
            prefs.save(c, cls.ivy, {"first_steps": {"done": True}})
            cls.adv = auth.create_user(c, "jo", PW)
            auth.set_advisor(c, "jo", True)
            import two_step
            secret = two_step.new_secret()
            two_step.enable(c, cls.adv, secret, two_step.totp(secret))
            cls.adv_ok = f"{cls.adv}:{two_step.status(c, cls.adv)['stamp']}"
            cls.kit = auth.create_client(c, cls.adv, "kit@example.com", name="Kit")
            seed(c, cls.kit, today)
            prefs.save(c, cls.kit, {"first_steps": {"done": True}})
            account_map.save_family(c, cls.kit, "Kit's private family note")
            account_map.save_account(c, cls.kit, "Roth IRA ...641", {"contact": "Kit's sister"})
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _run(self, uid, name, page="Dashboard", **state):
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
    def _text(at):
        parts = [h.proto.body for h in at.get("html")]
        for kind in ("markdown", "caption", "info", "success", "warning", "subheader"):
            parts += [e.value for e in getattr(at, kind)]
        parts += [e.proto.label for e in at.get("expandable")]
        return " ".join(parts)

    def _set_hidden(self, uid, on):
        c = portfolio.connect(self.db)
        try:
            p = prefs.load(c, uid)
            p["hide_amounts"] = on
            prefs.save(c, uid, p)
        finally:
            c.close()

    def test_year_so_far_opens_from_home(self):
        self._set_hidden(self.ivy, False)
        with self._run(self.ivy, "ivy") as at:
            at.button(key="year_open").click().run()
            text = self._text(at)
            self.assertIn("Money you added", text)
            self.assertIn("$1,000.00", text)
            self.assertIn("Month by month", text)
            self.assertIn("Private to you", text)
            self.assertIn("My " + str(datetime.now().year) + " so far", text)  # the share card

    def test_hidden_amounts_are_masked(self):
        self._set_hidden(self.ivy, True)
        try:
            with self._run(self.ivy, "ivy") as at:
                at.button(key="year_open").click().run()
                text = self._text(at)
                self.assertIn("Money you added", text)
                self.assertIn("•••", text)
                self.assertNotIn("$1,000", text)
                self.assertNotIn("My " + str(datetime.now().year) + " so far", text)
        finally:
            self._set_hidden(self.ivy, False)

    def test_homes_account_map_line_goes_to_the_account_page(self):
        with self._run(self.ivy, "ivy") as at:
            self.assertIn("You have 2 accounts", self._text(at))
            at.button(key="amap_nudge_go").click().run()
            self.assertEqual(at.session_state["page"], "Account")
            self.assertIn("Account map", self._text(at))
        with self._run(self.ivy, "ivy") as at:   # once: put away by going
            self.assertNotIn("You have 2 accounts", self._text(at))

    def test_the_client_sees_their_map_and_their_advisor_never_does(self):
        with self._run(self.kit, "kit@example.com", page="Account") as at:
            text = self._text(at)
            self.assertIn("Account map", text)
            self.assertEqual(at.text_area(key="amap_family").value, "Kit's private family note")
        with self._run(self.adv, "jo", page="Account", active_user_id=self.kit,
                       two_step_ok=self.adv_ok) as at:
            text = self._text(at)
            self.assertNotIn("Kit's private family note", text)
            self.assertNotIn("Kit's sister", text)
            self.assertNotIn("Kit's private family note",
                             " ".join(str(t.value) for t in at.text_area))
            self.assertNotIn("Kit's sister", " ".join(str(t.value) for t in at.text_input))
        # nor on the client's Home, opened by the advisor
        with self._run(self.adv, "jo", page="Dashboard", active_user_id=self.kit,
                       two_step_ok=self.adv_ok) as at:
            text = self._text(at)
            self.assertNotIn("You have 2 accounts", text)
            self.assertNotIn("Your year so far", " ".join(b.label for b in at.button))

    def test_saving_an_account_on_the_page(self):
        with self._run(self.ivy, "ivy", page="Account") as at:
            at.text_input(key="amap_a1_contact").input("Roth help line")
            at.text_input(key="amap_a1_phone").input("800-555-0199")
            at.button(key="FormSubmitter:amap_a1_form-Save").click().run()
            self.assertIn("Saved.", self._text(at))
        c = portfolio.connect(self.db)
        try:
            m = account_map.load(c, self.ivy)
        finally:
            c.close()
        roth = next(a for a in m["accounts"] if a["account"] == "Roth IRA ...641")
        self.assertEqual((roth["contact"], roth["phone"]), ("Roth help line", "800-555-0199"))


if __name__ == "__main__":
    unittest.main()
