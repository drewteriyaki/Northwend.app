"""PLAN step 5, the advisor side's first pieces:
- the advisor agreement and attestation (advisor_agreement.py, master brief
  4.1, gate L1): the advisor tools stay closed until the current version is
  accepted; acceptance is recorded; a new version asks again; "Beta" while L1
  is off;
- the standing line (standing_line.py, brief 4.4) on every advisor-authored
  thing a client sees: proposals, progress reports (in the app and as PDFs),
  the advisor card over their notes, messages, and the emails;
- licence evidence and the yearly re-check (licence_check.py, D15): recorded
  at approval, due after 11 months, not current after 13, a nightly count
  emailed to the admin.

Pure pieces on a scratch database, and dashboard.py with streamlit's AppTest.

    python -m unittest tests.test_advisor_agreement        (from the repo root)
"""

import contextlib
import io
import os
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from datetime import date, datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import admin  # noqa: E402
import admin_log  # noqa: E402
import advising  # noqa: E402
import advisor_agreement  # noqa: E402
import auth  # noqa: E402
import export  # noqa: E402
import licence_check  # noqa: E402
import mailer  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import proposals  # noqa: E402
import reports  # noqa: E402
import standing_line  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
FLAG_ON = {"NORTHWEND_FLAGS": "advisor_agreement"}
CHECK = {"source": "IAPD", "crd": "CRD 7012345", "checked_on": "2026-10-01"}


@contextlib.contextmanager
def _settings(**values):
    """Only these flag and gate settings (none from the real environment or
    the app's secrets)."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("NORTHWEND_FLAGS", "NORTHWEND_GATES", "NORTHWEND_ADMINS")}
    env.update(values)
    with unittest.mock.patch.dict(os.environ, env, clear=True), \
            unittest.mock.patch("flags._secret", lambda name: None):
        yield


def _pdf_text(pdf: bytes) -> str:
    """The words on a PDF's pages, one string (fpdf2 compresses and splits them)."""
    import zlib
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


class _DB(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pt_step5_")
        self.db = os.path.join(self.tmp, "t.db")
        self.conn = portfolio.connect(self.db)
        c = self.conn
        self.carol = auth.create_user(c, "carol", PW)
        auth.set_advisor(c, "carol", True)
        self.dana = auth.create_client(c, self.carol, "dana", name="Dana Lee")

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)


# --------------------------------------------------------------------------- #
# 1. the advisor agreement
# --------------------------------------------------------------------------- #
class AgreementTests(_DB):

    def test_nothing_is_asked_while_the_flag_is_off(self):
        with _settings():
            self.assertFalse(advisor_agreement.required())
            self.assertTrue(advisor_agreement.tools_open(self.conn, self.carol))
            self.assertTrue(auth.can_view(self.conn, self.carol, self.dana))

    def test_tools_stay_closed_until_accepted(self):
        with _settings(**FLAG_ON):
            self.assertTrue(advisor_agreement.due(self.conn, self.carol, is_advisor=True))
            self.assertFalse(advisor_agreement.tools_open(self.conn, self.carol))
            self.assertFalse(auth.can_view(self.conn, self.carol, self.dana))
            self.assertTrue(auth.can_view(self.conn, self.carol, self.carol))   # their own
            self.assertTrue(auth.can_view(self.conn, self.dana, self.dana))
            # nothing an advisor does through can_view reaches the client
            res = advising.message_clients(self.conn, self.carol, [self.dana], "Hello",
                                           now=datetime.now(timezone.utc))
            self.assertFalse(res["ok"])
            with self.assertRaises(PermissionError):
                export.client_record(self.conn, self.carol, self.dana)
            # the box must be ticked
            with self.assertRaises(ValueError):
                advisor_agreement.accept(self.conn, self.carol, ticked=False)
            self.assertIsNone(advisor_agreement.latest(self.conn, self.carol))
            advisor_agreement.accept(self.conn, self.carol, ticked=True)
            self.assertFalse(advisor_agreement.due(self.conn, self.carol, is_advisor=True))
            self.assertTrue(auth.can_view(self.conn, self.carol, self.dana))

    def test_acceptance_is_recorded_with_version_hash_gate_and_time(self):
        when = datetime(2026, 10, 6, 15, 30, tzinfo=timezone.utc)
        with _settings(**FLAG_ON):
            advisor_agreement.accept(self.conn, self.carol, ticked=True, now=when)
        with _settings(NORTHWEND_FLAGS="advisor_agreement", NORTHWEND_GATES="L1"):
            advisor_agreement.accept(self.conn, self.carol, ticked=True)
        rows = [dict(r) for r in self.conn.execute(
            "SELECT user_id, version, text_hash, l1_on, accepted_at FROM advisor_agreements "
            "ORDER BY id")]
        self.assertEqual(len(rows), 2)   # each acceptance kept; nothing overwritten
        self.assertEqual(rows[0], {"user_id": self.carol, "version": advisor_agreement.VERSION,
                                   "text_hash": advisor_agreement.text_hash(), "l1_on": 0,
                                   "accepted_at": "2026-10-06 15:30:00"})
        self.assertEqual(rows[1]["l1_on"], 1)
        self.assertEqual(len(advisor_agreement.text_hash()), 64)
        # only an advisor accepts it
        with self.assertRaises(ValueError):
            advisor_agreement.accept(self.conn, self.dana, ticked=True)
        # what the admin sees, and the advisor's own export
        acc = {a["id"]: a for a in admin.list_accounts(self.conn)}
        self.assertEqual(acc[self.carol]["agreement"]["version"], advisor_agreement.VERSION)
        self.assertTrue(acc[self.carol]["agreement"]["current"])
        self.assertIsNone(acc[self.dana]["agreement"])
        mine = export.collect(self.conn, self.carol)["advisor_agreement"]
        self.assertEqual(len(mine), 2)
        self.assertNotIn("text_hash", export._csv(mine))   # a hash is never exported

    def test_a_new_version_asks_again(self):
        with _settings(**FLAG_ON):
            advisor_agreement.accept(self.conn, self.carol, ticked=True)
            self.assertTrue(advisor_agreement.tools_open(self.conn, self.carol))
            with unittest.mock.patch.object(advisor_agreement, "VERSION", "2027-01-01"):
                self.assertFalse(advisor_agreement.tools_open(self.conn, self.carol))
                self.assertFalse(auth.can_view(self.conn, self.carol, self.dana))
                acc = {a["id"]: a for a in admin.list_accounts(self.conn)}
                self.assertFalse(acc[self.carol]["agreement"]["current"])
            # the same version with different words asks again too
            with unittest.mock.patch.object(advisor_agreement, "TEXT",
                                            advisor_agreement.TEXT + "\n9. New."):
                self.assertFalse(advisor_agreement.tools_open(self.conn, self.carol))

    def test_beta_while_l1_is_off(self):
        with _settings(**FLAG_ON):
            self.assertEqual(advisor_agreement.label(), "Beta")
        with _settings(NORTHWEND_FLAGS="advisor_agreement", NORTHWEND_GATES="L1"):
            self.assertEqual(advisor_agreement.label(), "")
            self.assertTrue(advisor_agreement.required())

    def test_the_text_covers_what_the_brief_asks(self):
        t = advisor_agreement.TEXT
        for words in ("registered", "your own advice", "under your firm's supervision",
                      "won't present Northwend as an investment adviser", "Form ADV",
                      "client agreements", "books and records", "software and a listing",
                      "per client, per lead", "outcome"):
            self.assertIn(words, t)
        self.assertIn("DRAFT", advisor_agreement.__doc__)


# --------------------------------------------------------------------------- #
# 2. the standing line
# --------------------------------------------------------------------------- #
class StandingLineTests(_DB):

    def test_one_constant_and_its_words(self):
        self.assertEqual(standing_line.text("Carol Reyes", "Reyes Wealth"),
                         "This is Carol Reyes's advice, from Reyes Wealth - not Northwend's. "
                         "Northwend provides the software.")
        self.assertIn("their firm", standing_line.text("Carol", None))

    def test_name_and_firm_from_the_card_then_the_login_and_request(self):
        c = self.conn
        self.assertEqual(standing_line.who(c, self.carol), {"name": "carol", "firm": ""})
        auth.request_advisor(c, self.carol, "Reyes Wealth", "7012345")
        self.assertEqual(standing_line.who(c, self.carol)["firm"], "Reyes Wealth")
        prefs.save(c, self.carol, {"advisor_card": {"name": "Carol Reyes",
                                                    "firm": "Reyes Wealth Partners"}})
        self.assertEqual(standing_line.for_advisor(c, self.carol),
                         standing_line.text("Carol Reyes", "Reyes Wealth Partners"))

    def test_the_pdfs_carry_it(self):
        line = standing_line.text("Carol Reyes", "Reyes Wealth")
        pid = proposals.save(self.conn, self.carol, self.dana, title="Steadier",
                             mix={"Stocks": 60, "Bonds": 40}, note="Closer to the date.")
        p = proposals.for_client(self.conn, self.dana, include_drafts=True)[0]
        self.assertEqual(p["id"], pid)
        cmp = proposals.compare({"Stocks": 80, "Bonds": 20}, p["mix"])
        text = _pdf_text(proposals.render_pdf(p, cmp, client_name="Dana Lee",
                                              advisor_name="Carol Reyes", firm="Reyes Wealth"))
        self.assertIn("from Carol Reyes, Reyes Wealth", text)
        self.assertIn(line, text)
        reports.save(self.conn, self.carol, self.dana, label="Q3 2026", start=date(2026, 7, 1),
                     end=date(2026, 9, 30), facts={}, message="A calm quarter.")
        rep = reports.for_client(self.conn, self.dana)[0]
        text = _pdf_text(reports.render_pdf(rep, client_name="Dana Lee",
                                            advisor_name="Carol Reyes", firm="Reyes Wealth"))
        self.assertIn(line, text)


# --------------------------------------------------------------------------- #
# 3. licence evidence and the yearly re-check
# --------------------------------------------------------------------------- #
class LicenceTests(_DB):

    def test_what_a_check_needs(self):
        err = licence_check.check_error
        today = date(2026, 10, 6)
        self.assertIsNone(err("BrokerCheck", "1234567", "2026-10-06", today=today))
        self.assertIn("BrokerCheck or IAPD", err("Google", "1234567", "2026-10-06", today=today))
        self.assertIn("number", err("IAPD", " ", "2026-10-06", today=today))
        self.assertIn("future", err("IAPD", "1234567", "2026-10-07", today=today))
        self.assertIn("day", err("IAPD", "1234567", None, today=today))

    def test_due_after_eleven_months_not_current_after_thirteen(self):
        c = self.conn
        self.assertFalse(licence_check.licence_current(c, self.carol))   # none on record
        licence_check.record(c, self.carol, source="IAPD", crd="7012345", checked_on="2025-10-06")
        st = lambda d: licence_check.status(licence_check.last_check(c, self.carol), today=d)
        self.assertEqual(st(date(2026, 9, 5)), licence_check.CURRENT)
        self.assertEqual(st(date(2026, 9, 6)), licence_check.DUE)        # 11 months
        self.assertEqual(st(date(2026, 11, 6)), licence_check.DUE)       # 13 months: still in
        self.assertEqual(st(date(2026, 11, 7)), licence_check.OVERDUE)
        self.assertTrue(licence_check.licence_current(c, self.carol, today=date(2026, 11, 6)))
        self.assertFalse(licence_check.licence_current(c, self.carol, today=date(2026, 11, 7)))
        # a re-check makes it current again; the earlier one is kept
        licence_check.record(c, self.carol, source="BrokerCheck", crd="7012345",
                             checked_on="2026-11-10", now=datetime(2026, 11, 10, 9,
                                                                    tzinfo=timezone.utc))
        self.assertTrue(licence_check.licence_current(c, self.carol, today=date(2026, 11, 10)))
        self.assertEqual(c.execute("SELECT COUNT(*) FROM licence_checks").fetchone()[0], 2)
        self.assertEqual(licence_check.add_months(date(2026, 1, 31), 1), date(2026, 2, 28))

    def test_approval_records_the_check_and_a_bad_one_changes_nothing(self):
        c = self.conn
        nia = auth.create_user(c, "nia", PW)
        auth.request_advisor(c, nia, "Nia Wealth", "7012345")
        with self.assertRaises(ValueError):
            admin.approve_advisor(c, "nia", check={**CHECK, "source": "a website"})
        self.assertFalse(auth.is_advisor(c, nia))
        self.assertIsNone(licence_check.last_check(c, nia))
        admin.approve_advisor(c, "nia", check=CHECK, by=self.carol)
        self.assertTrue(auth.is_advisor(c, nia))
        got = licence_check.last_check(c, nia)
        self.assertEqual((got["source"], got["crd"], got["checked_on"], got["checked_by"]),
                         ("IAPD", "CRD 7012345", "2026-10-01", self.carol))
        acc = {a["id"]: a for a in admin.list_accounts(c)}
        self.assertEqual(acc[nia]["licence_checked"], "2026-10-01")
        self.assertEqual(acc[nia]["licence_check"]["source"], "IAPD")
        # in their own export, without the admin's id
        rows = export.collect(c, nia)["licence_checks"]
        self.assertEqual(rows[0]["crd"], "CRD 7012345")
        self.assertNotIn("checked_by", rows[0])
        # the admin's account going leaves the check, without their id
        self.assertTrue(admin.delete_account(c, self.carol, by=-1)["ok"])
        self.assertIsNone(licence_check.last_check(c, nia)["checked_by"])

    def test_who_is_due_and_the_nightly_count(self):
        c = self.conn
        today = date(2026, 10, 6)
        for name, day in (("ana", "2026-09-01"), ("ben", "2025-10-01"), ("cy", "2025-08-01")):
            uid = auth.create_user(c, name, PW)
            auth.set_advisor(c, name, True)
            licence_check.record(c, uid, source="IAPD", crd="1234567", checked_on=day)
        # an admin's own account in the advisor app isn't counted
        boss = auth.create_user(c, "boss", PW)
        auth.set_advisor(c, "boss", True)
        admin.set_admin(c, "boss", True)
        due = licence_check.due(c, today=today)
        self.assertEqual([(a["username"], a["status"]) for a in due],
                         [("carol", "none"), ("cy", "overdue"), ("ben", "due")])
        self.assertNotIn(boss, [a["id"] for a in due])
        self.assertEqual(licence_check.counts(c, today=today), {"due": 3, "overdue": 2})
        sent = []
        fake = lambda to, subject, text, html=None, **k: sent.append((to, subject, text)) or True
        env = {"RESEND_API_KEY": "re_test", "ALERT_EMAIL": "owner@example.com",
               "MAIL_DRY_RUN": ""}
        with unittest.mock.patch.dict(os.environ, env), \
                unittest.mock.patch.object(mailer, "send", fake):
            res = licence_check.remind(c, "https://app.example/?x=1", today=today)
            self.assertEqual(res, {"due": 3, "overdue": 2, "emailed": True})
            # once a week, not every night
            self.assertIsNone(licence_check.remind(c, today=date(2026, 10, 12))["emailed"])
            self.assertTrue(licence_check.remind(c, today=date(2026, 10, 13))["emailed"])
        self.assertEqual(len(sent), 2)
        to, subject, text = sent[0]
        self.assertEqual((to, subject), ("owner@example.com", "Advisor licence checks due"))
        self.assertIn("3 advisors are due a licence check", text)
        self.assertIn("https://app.example/?page=admin", text)
        for name in ("carol", "ben", "cy", "1234567"):   # counts only
            self.assertNotIn(name, text)

    def test_nothing_due_nothing_sent_and_the_command_prints_counts_only(self):
        c = self.conn
        licence_check.record(c, self.carol, source="IAPD", crd="7012345",
                             checked_on=date.today().isoformat())
        out = io.StringIO()
        with unittest.mock.patch.dict(os.environ, {"MAIL_DRY_RUN": "1"}), \
                contextlib.redirect_stdout(out):
            self.assertEqual(licence_check.main(["--db", self.db]), 0)
        self.assertEqual(out.getvalue().strip(),
                         "Licence re-checks: 0 due (0 not current) - no email.")

    def test_the_nightly_step_runs_with_a_failure_alert(self):
        with open(os.path.join(REPO, ".github", "workflows", "scheduled-sync.yml"),
                  encoding="utf-8") as fh:
            text = fh.read()
        tidy = text.split("\n  tidy:", 1)[1].split("\n  weekly-email:", 1)[0]
        self.assertIn('python licence_check.py --db "$DATABASE_URL"', tidy)
        self.assertIn('python error_alerts.py job "Nightly tidy"', tidy)


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
        cls.dir = tempfile.mkdtemp(prefix="pt_step5_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.carol = auth.create_user(c, "carol", PW)
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            prefs.save(c, cls.carol, {"advisor_card": {"name": "Carol Reyes",
                                                       "firm": "Reyes Wealth"}})
            cls.dana = auth.create_user(c, "dana", PW)
            auth.link_client(c, cls.carol, cls.dana)
            # an admin, and someone waiting for advisor access
            cls.ann = auth.create_user(c, "ann", PW)
            secret = two_step.new_secret()
            two_step.enable(c, cls.ann, secret, two_step.totp(secret))
            cls.ann_ok = f"{cls.ann}:{two_step.status(c, cls.ann)['stamp']}"
            cls.nia = auth.create_user(c, "nia", PW)
            auth.request_advisor(c, cls.nia, "Nia Wealth", "7012345")
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _run(self, at, flags="", gates="", admins=""):
        import yfinance

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                   NORTHWEND_FLAGS=flags, NORTHWEND_GATES=gates, NORTHWEND_ADMINS=admins)
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline):
            at.run()
        self.assertEqual([e.message for e in at.exception], [])
        return at

    def _tab(self, uid, name, page, **state):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": page, **state}.items():
            at.session_state[k] = v
        return at

    @staticmethod
    def _text(at):
        parts = [m.value for m in at.markdown] + [h.proto.body for h in at.get("html")]
        for kind in ("success", "info", "warning", "error", "caption", "subheader"):
            parts += [str(e.value) for e in getattr(at, kind)]
        return " ".join(parts)

    def _conn(self):
        return portfolio.connect(self.db)

    def test_your_clients_waits_for_the_agreement(self):
        c = self._conn()
        try:
            c.execute("DELETE FROM advisor_agreements")
            c.commit()
        finally:
            c.close()
        flag = "advisor_agreement"
        # flag off: the book, as today
        at = self._run(self._tab(self.carol, "carol", "Clients", two_step_ok=self.carol_ok))
        self.assertNotIn("agreement_accept", [b.key for b in at.button])
        # flag on: the agreement, marked Beta while L1 is off - and no clients
        at = self._tab(self.carol, "carol", "Clients", two_step_ok=self.carol_ok)
        self._run(at, flags=flag)
        text = self._text(at)
        self.assertIn(advisor_agreement.TITLE, text)
        self.assertIn(":blue-badge[Beta]", text)
        self.assertIn(advisor_agreement.BETA_NOTE, text)
        self.assertIn("agreement_accept", [b.key for b in at.button])
        self.assertNotIn("dana", text)
        # opening the client's account doesn't work either: back to their own
        other = self._tab(self.carol, "carol", "Dashboard", two_step_ok=self.carol_ok,
                          active_user_id=self.dana)
        self._run(other, flags=flag)
        self.assertNotIn(":material/visibility: Viewing", self._text(other))
        self._run(self._tab(self.carol, "carol", "Dashboard", two_step_ok=self.carol_ok,
                            active_user_id=self.dana))   # (the same, flag off: her client)
        on = self._run(self._tab(self.carol, "carol", "Dashboard", two_step_ok=self.carol_ok,
                                 active_user_id=self.dana))
        self.assertIn(":material/visibility: Viewing", self._text(on))
        # Accept without the tick: asked again, nothing kept
        at.button(key="agreement_accept").click()
        self._run(at, flags=flag)
        self.assertIn("Tick the box", self._text(at))
        at.checkbox(key="agreement_tick").check()
        at.button(key="agreement_accept").click()
        self._run(at, flags=flag)
        self.assertNotIn("agreement_accept", [b.key for b in at.button])
        c = self._conn()
        try:
            row = advisor_agreement.latest(c, self.carol)
        finally:
            c.close()
        self.assertEqual((row["version"], row["l1_on"]), (advisor_agreement.VERSION, 0))
        # with L1 on: no Beta label
        c = self._conn()
        try:
            c.execute("DELETE FROM advisor_agreements")
            c.commit()
        finally:
            c.close()
        at = self._run(self._tab(self.carol, "carol", "Clients", two_step_ok=self.carol_ok),
                       flags=flag, gates="L1")
        self.assertIn(advisor_agreement.TITLE, self._text(at))
        self.assertNotIn("Beta", self._text(at))

    def test_the_client_sees_whose_advice_it_is(self):
        c = self._conn()
        try:
            pid = proposals.save(c, self.carol, self.dana, title="A steadier mix",
                                 mix={"Stocks": 60, "Bonds": 40}, note="Closer to the date.")
            proposals.share(c, self.carol, pid)
            reports.save(c, self.carol, self.dana, label="Q3 2026", start=date(2026, 7, 1),
                         end=date(2026, 9, 30), facts={}, message="A calm quarter.")
            advising.message_clients(c, self.carol, [self.dana], "Markets were bumpy.",
                                     now=datetime.now(timezone.utc))
        finally:
            c.close()
        at = self._run(self._tab(self.dana, "dana", "Advisor notes"))
        line = standing_line.text("Carol Reyes", "Reyes Wealth")
        captions = [str(e.value) for e in at.caption]
        shown = [x for x in captions if line in x]
        # the advisor card, the proposal, the report and the message
        self.assertGreaterEqual(len(shown), 4, captions)
        self.assertIn("Markets were bumpy.", self._text(at))

    def test_approving_records_the_licence_check(self):
        at = self._tab(self.ann, "ann", "Admin", two_step_ok=self.ann_ok)
        self._run(at, admins="ann")
        self.assertIn("admin_src_nia", [s.key for s in at.selectbox])
        # no source picked: refused, nothing changes
        at.button(key="admin_ok_nia").click()
        self._run(at, admins="ann")
        self.assertIn("BrokerCheck or IAPD", self._text(at))
        c = self._conn()
        try:
            self.assertFalse(auth.is_advisor(c, self.nia))
        finally:
            c.close()
        at.selectbox(key="admin_src_nia").set_value("BrokerCheck")
        at.button(key="admin_ok_nia").click()
        self._run(at, admins="ann")
        c = self._conn()
        try:
            self.assertTrue(auth.is_advisor(c, self.nia))
            got = licence_check.last_check(c, self.nia)
            log = [r for r in admin_log.recent(c) if r["action"] == "approve_advisor"]
        finally:
            c.close()
        self.assertEqual((got["source"], got["crd"], got["checked_by"]),
                         ("BrokerCheck", "7012345", self.ann))
        self.assertIn("checked on BrokerCheck", log[0]["detail"])
        # carol has no check on record: listed as due, and a re-check is recorded there
        self.assertIn("Licence checks due", self._text(at))
        at.selectbox(key=f"admin_src_re{self.carol}").set_value("IAPD")
        at.button(key=f"admin_check_{self.carol}").click()
        self._run(at, admins="ann")
        self.assertIn("Enter the CRD or licence number", self._text(at))   # none typed yet
        at.text_input(key=f"admin_crd_re{self.carol}").input("CRD 7654321")
        at.button(key=f"admin_check_{self.carol}").click()
        self._run(at, admins="ann")
        c = self._conn()
        try:
            self.assertTrue(licence_check.licence_current(c, self.carol))
            self.assertEqual(admin_log.recent(c)[0]["action"], "licence_check")
        finally:
            c.close()


if __name__ == "__main__":
    unittest.main()
