"""ROADMAP 7, advisor tools: adding clients from a CSV file (reading it, each
row's state, the add-and-invite step with its limits and the "who's it from"
rule), the made-up book a pending advisor can look at (never touching real
lists, counts or emails), and ending a relationship from either side (the
client keeps a self-directed account, the advisor keeps their records).

    python -m unittest tests.test_advisor_tools        (from the repo root)
"""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import types
import unittest
import unittest.mock
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import admin  # noqa: E402
import advising  # noqa: E402
import advisor  # noqa: E402
import advisor_demo  # noqa: E402
import auth  # noqa: E402
import client_csv  # noqa: E402
import export  # noqa: E402
import mailer  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import proposals  # noqa: E402
import reports  # noqa: E402
import sample_data  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"


class _DB(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_advtools_")
        self.db = os.path.join(self.dir, "t.db")
        self.conn = portfolio.connect(self.db)
        self.carol = auth.create_user(self.conn, "carol", PW)
        auth.set_advisor(self.conn, "carol", True)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def count(self, table, where="1 = 1", params=()):
        return self.conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE {where}",
                                 params).fetchone()["n"]


# --------------------------------------------------------------------------- #
# reading a client list
# --------------------------------------------------------------------------- #
class ParseTests(unittest.TestCase):

    def test_headers_matched_loosely(self):
        got = client_csv.parse(b"\xef\xbb\xbfClient Name,E-mail Address\r\n"
                               b"Dana Lee,Dana@Example.com\r\n\r\n,\r\nChen household,wei@x.com\r\n")
        self.assertTrue(got["ok"], got)
        self.assertEqual([(r["row"], r["name"], r["email"]) for r in got["rows"]],
                         [(2, "Dana Lee", "Dana@Example.com"), (5, "Chen household", "wei@x.com")])
        hh = client_csv.parse(b"Household;Email\nRivera household;r@x.com\n")
        self.assertEqual(hh["rows"][0]["name"], "Rivera household")

    def test_first_and_last_names_are_joined(self):
        got = client_csv.parse(b"First name\tLast name\tEmail\nWei\tChen\twei@x.com\n")
        self.assertEqual(got["rows"], [{"row": 2, "name": "Wei Chen", "email": "wei@x.com"}])

    def test_a_file_with_no_header_row(self):
        got = client_csv.parse(b"Dana,dana@x.com\nSam,sam@x.com\n")
        self.assertEqual([r["name"] for r in got["rows"]], ["Dana", "Sam"])

    def test_what_cant_be_read(self):
        self.assertIn("email column", client_csv.parse(b"name,phone\nDana,555\n")["error"])
        self.assertIn("empty", client_csv.parse(b"")["error"])
        self.assertIn("just the header", client_csv.parse(b"name,email\n")["error"])
        many = b"name,email\n" + b"".join(b"P%d,p%d@x.com\n" % (i, i)
                                           for i in range(client_csv.MAX_ROWS + 1))
        self.assertIn(f"up to {client_csv.MAX_ROWS}", client_csv.parse(many)["error"])
        ok = b"name,email\n" + b"".join(b"P%d,p%d@x.com\n" % (i, i)
                                         for i in range(client_csv.MAX_ROWS))
        self.assertEqual(len(client_csv.parse(ok)["rows"]), client_csv.MAX_ROWS)


class ReviewTests(_DB):

    def test_each_rows_state(self):
        c = self.conn
        auth.create_client(c, self.carol, "dana@x.com", name="Dana")
        auth.create_user(c, "taken@x.com", PW)        # someone else's account
        rows = client_csv.parse(
            b"name,email\nNew One,new@x.com\nDana again,DANA@x.com\nTaken,taken@x.com\n"
            b"No email,\nBad,not-an-email\nNew again,new@x.com\n")["rows"]
        got = {r["row"]: (r["state"], r["why"]) for r in client_csv.review(c, self.carol, rows)}
        self.assertEqual(got[2], ("ok", ""))
        self.assertEqual(got[3][0], "client")
        self.assertEqual(got[4][0], "taken")
        self.assertEqual(got[5], ("invalid", "No email address"))
        self.assertEqual(got[6][0], "invalid")
        self.assertEqual(got[7], ("duplicate", "Same as row 2"))
        # said calmly, and no more than Add client says
        self.assertNotIn("taken@x.com", got[4][1])

    def test_how_many_new_addresses_a_day_can_be_checked(self):
        c = self.conn
        rows = client_csv.parse(b"name,email\nA,a@x.com\nB,b@x.com\nC,c@x.com\n")["rows"]
        with unittest.mock.patch.object(auth, "CLIENT_CHECKS_PER_DAY", 2):
            got = [r["state"] for r in client_csv.review(c, self.carol, rows)]
            self.assertEqual(got, ["ok", "ok", "later"])
            # the same file again doesn't use up more: a and b are free, c still waits
            got = [r["state"] for r in client_csv.review(c, self.carol, rows)]
            self.assertEqual(got, ["ok", "ok", "later"])
        # only hashes are kept
        self.assertEqual(self.count("email_sends", "purpose = 'client_check'"), 2)
        for (key,) in c.execute("SELECT email_key FROM email_sends"):
            self.assertNotIn("@", key)

    def test_the_rows_that_need_a_look_are_safe_to_open(self):
        rows = client_csv.review(self.conn, self.carol, client_csv.parse(
            b"name,email\n=HYPERLINK(\"x\"),bad\nFine,fine@x.com\n")["rows"])
        text = client_csv.needs_a_look_csv(rows).decode()
        self.assertIn("'=HYPERLINK", text)
        self.assertNotIn("fine@x.com", text)

    def test_invites_left_today(self):
        self.assertEqual(auth.invites_left_today(self.conn, self.carol),
                         auth.INVITES_PER_ADVISOR_PER_DAY)
        auth.invite_email_limit(self.conn, self.carol, "a@x.com")
        self.assertEqual(auth.invites_left_today(self.conn, self.carol),
                         auth.INVITES_PER_ADVISOR_PER_DAY - 1)


# --------------------------------------------------------------------------- #
# ending a relationship
# --------------------------------------------------------------------------- #
class EndRelationshipTests(_DB):

    def setUp(self):
        super().setUp()
        c = self.conn
        # signed in before, with a profile and advisor records
        self.dana = auth.create_client(c, self.carol, "dana@x.com", name="Dana Lee")
        c.execute("UPDATE users SET last_login_at = '2026-09-01 10:00:00' WHERE id = ?",
                  (self.dana,))
        c.commit()
        advisor.save_profile(c, self.dana, {"goal": "Retirement", "time_horizon_years": 20})
        sample_data.load(c, self.dana)
        advising.add_note(c, self.dana, self.carol, "Note", "Shared note", "2026-09-01")
        advising.add_note(c, self.dana, self.carol, "Note", "Private note", "2026-09-02",
                          private=True)
        pid = proposals.save(c, self.carol, self.dana, title="Mix", mix={"Stocks": 60,
                                                                         "Bonds": 40})
        proposals.share(c, self.carol, pid)
        self.records = {t: self.count(t, "client_id = ?", (self.dana,))
                        for t in ("advisor_notes", "proposals")}

    def test_the_advisor_ends_it_and_the_client_keeps_their_account(self):
        c = self.conn
        auth.create_invite(c, self.carol, self.dana)
        self.assertEqual(advising.ending_plan(c, self.carol, self.dana)["account"], "kept")
        res = advising.end_relationship(c, self.carol, self.dana, by="advisor")
        self.assertEqual((res["ok"], res["account"], res["name"], res["client_email"]),
                         (True, "kept", "Dana Lee", "dana@x.com"))
        self.assertFalse(auth.can_view(c, self.carol, self.dana))
        self.assertIsNone(advising.advisor_of(c, self.dana))      # self-directed now
        self.assertNotIn(self.dana, dict(auth.list_clients(c, self.carol)))
        self.assertEqual(self.count("invites", "user_id = ?", (self.dana,)), 0)
        self.assertEqual(auth.verify_login(c, "dana@x.com", PW) is None, True)  # random pw kept
        self.assertTrue(self.count("positions", "user_id = ?", (self.dana,)))   # holdings stay
        for t, n in self.records.items():
            self.assertEqual(self.count(t, "client_id = ?", (self.dana,)), n, t)
        (f,) = advising.former_clients(c, self.carol)
        self.assertEqual((f["client_name"], f["ended_by"], f["account"]),
                         ("Dana Lee", "advisor", "kept"))
        # again: already ended
        self.assertFalse(advising.end_relationship(c, self.carol, self.dana, by="advisor")["ok"])

    def test_the_record_stays_exportable_without_the_clients_own_data(self):
        c = self.conn
        advising.end_relationship(c, self.carol, self.dana, by="client")
        files = zipfile.ZipFile(io.BytesIO(export.client_record_zip(c, self.carol, self.dana)))
        names = files.namelist()
        self.assertIn("notes.csv", names)
        self.assertIn("Private note", files.read("notes.csv").decode())
        self.assertIn("proposals.csv", names)
        self.assertNotIn("profile.csv", names)          # their answers are theirs now
        client = files.read("client.csv").decode()
        self.assertIn("client", client)                 # ended_by
        self.assertNotIn("last_login_at", client)
        everyone = zipfile.ZipFile(io.BytesIO(export.all_client_records_zip(c, self.carol)))
        self.assertIn(f"former-dana-lee-{self.dana}/notes.csv", everyone.namelist())
        # still nobody else's
        omar = auth.create_user(c, "omar", PW)
        auth.set_advisor(c, "omar", True)
        with self.assertRaises(PermissionError):
            export.client_record_zip(c, omar, self.dana)
        # the advisor's own export lists them
        mine = zipfile.ZipFile(io.BytesIO(export.export_zip(c, self.carol)))
        self.assertIn("your_former_clients.csv", mine.namelist())
        # and the client's export still has what was shared with them
        theirs = zipfile.ZipFile(io.BytesIO(export.export_zip(c, self.dana)))
        self.assertIn("Shared note", theirs.read("from_your_advisor_notes.csv").decode())

    def test_a_client_who_never_signed_in_gets_a_password_link(self):
        c = self.conn
        eve = auth.create_client(c, self.carol, "eve@x.com", name="Eve")
        c.execute("UPDATE users SET last_login_at = NULL WHERE id = ?", (eve,))
        auth.set_password(c, "eve@x.com", "advisor-set-1")    # a password the advisor knows
        self.assertEqual(advising.ending_plan(c, self.carol, eve)["account"], "setup link")
        res = advising.end_relationship(c, self.carol, eve, by="advisor")
        self.assertEqual(res["account"], "setup link")
        self.assertTrue(res["setup_token"])
        self.assertIsNone(auth.verify_login(c, "eve@x.com", "advisor-set-1"))
        self.assertTrue(auth.reset_password(c, res["setup_token"], "eves-own-1")["ok"])
        self.assertEqual(auth.verify_login(c, "eve@x.com", "eves-own-1"), eve)
        self.assertFalse(auth.can_view(c, self.carol, eve))

    def test_an_account_nobody_could_open_is_closed_and_the_records_stay(self):
        c = self.conn
        hh = auth.create_client(c, self.carol, "", name="Chen household")
        sample_data.load(c, hh)
        advising.add_note(c, hh, self.carol, "Review", "First meeting", "2026-09-01")
        self.assertEqual(advising.ending_plan(c, self.carol, hh)["account"], "closed")
        self.assertEqual(advising.end_relationship(c, self.carol, hh, by="advisor")["account"],
                         "closed")
        self.assertIsNone(auth.get_username(c, hh))
        self.assertEqual(self.count("positions", "user_id = ?", (hh,)), 0)
        self.assertEqual(self.count("advisor_notes", "client_id = ?", (hh,)), 1)
        record = zipfile.ZipFile(io.BytesIO(export.client_record_zip(c, self.carol, hh)))
        self.assertIn("First meeting", record.read("notes.csv").decode())
        self.assertIn("closed", record.read("client.csv").decode())

    def test_the_client_ends_it(self):
        c = self.conn
        res = advising.end_relationship(c, self.carol, self.dana, by="client")
        self.assertEqual((res["ok"], res["account"]), (True, "kept"))
        self.assertFalse(auth.can_view(c, self.carol, self.dana))
        self.assertEqual(advising.former_clients(c, self.carol)[0]["ended_by"], "client")

    # PLAN D7: a former client deletes their own account - everything that's
    # theirs goes, each old advisor's own records stay
    def _report(self, advisor_id, client_id):
        from datetime import date
        reports.save(self.conn, advisor_id, client_id, label="Q3 2026", start=date(2026, 7, 1),
                     end=date(2026, 9, 30), facts={}, message="Steady quarter")

    def test_a_former_clients_own_delete_keeps_each_old_advisors_records(self):
        c = self.conn
        self._report(self.carol, self.dana)
        omar = auth.create_user(c, "omar", PW)
        auth.set_advisor(c, "omar", True)
        auth.link_client(c, omar, self.dana)
        advising.add_note(c, self.dana, omar, "Note", "Omar's note", "2026-09-03")
        self._report(omar, self.dana)
        advising.end_relationship(c, self.carol, self.dana, by="client")
        advising.end_relationship(c, omar, self.dana, by="advisor")
        kept = {t: self.count(t, "client_id = ?", (self.dana,))
                for t in admin.ADVISOR_RECORD_TABLES}
        self.assertEqual(kept, {"advisor_notes": 3, "proposals": 1, "progress_reports": 2,
                                "former_clients": 2})
        auth.set_password(c, "dana@x.com", PW)              # her own, chosen since
        self.assertTrue(admin.delete_own(c, self.dana, PW)["ok"])
        self.assertIsNone(auth.get_username(c, self.dana))
        for table, cols in admin.ACCOUNT_TABLES.items():   # the client's own rows: gone
            if table in admin.ADVISOR_RECORD_TABLES:
                continue
            where = " OR ".join(f"{col} = ?" for col in cols)
            self.assertEqual(self.count(table, where, (self.dana,) * len(cols)), 0, table)
        for t, n in kept.items():                          # both advisors' records: kept
            self.assertEqual(self.count(t, "client_id = ?", (self.dana,)), n, t)
        record = zipfile.ZipFile(io.BytesIO(export.client_record_zip(c, self.carol, self.dana)))
        self.assertIn("Private note", record.read("notes.csv").decode())
        self.assertEqual([f["client_id"] for f in advising.former_clients(c, omar)],
                         [self.dana])

    def test_a_client_never_linked_deletes_everything(self):
        c = self.conn
        eve = auth.create_user(c, "eve", PW)
        sample_data.load(c, eve)
        advisor.save_profile(c, eve, {"goal": "Retirement"})
        self.assertTrue(admin.delete_own(c, eve, PW)["ok"])
        for table, cols in admin.ACCOUNT_TABLES.items():
            where = " OR ".join(f"{col} = ?" for col in cols)
            self.assertEqual(self.count(table, where, (eve,) * len(cols)), 0, table)
        # and Dana's advisor records, about someone else, are untouched
        self.assertEqual(self.count("advisor_notes", "client_id = ?", (self.dana,)), 2)

    def test_the_admin_delete_still_removes_the_old_advisors_records(self):
        c = self.conn
        self._report(self.carol, self.dana)
        advising.end_relationship(c, self.carol, self.dana, by="client")
        boss = auth.create_user(c, "boss", PW)
        self.assertTrue(admin.delete_account(c, self.dana, by=boss)["ok"])
        for t in admin.ADVISOR_RECORD_TABLES:
            self.assertEqual(self.count(t, "client_id = ?", (self.dana,)), 0, t)

    def test_deleting_the_advisor_clears_former_clients(self):
        advising.end_relationship(self.conn, self.carol, self.dana, by="advisor")
        boss = auth.create_user(self.conn, "boss", PW)
        self.assertTrue(admin.delete_account(self.conn, self.carol, by=boss)["ok"])
        self.assertEqual(self.count("former_clients"), 0)

    def test_emails_carry_no_figures(self):
        sent = []
        with unittest.mock.patch.object(mailer, "send", lambda *a, **k: sent.append((a, k))
                                        or True):
            mailer.relationship_ended("dana@x.com", "https://x/", "Carol Ruiz (Ruiz Wealth)",
                                      from_name="Carol Ruiz, Ruiz Wealth")
            mailer.relationship_ended("eve@x.com", "https://x/?reset=t", "Carol Ruiz",
                                      setup_days=7)
            mailer.client_stopped_sharing("carol@x.com", "https://x/?page=your-clients",
                                          "Dana Lee")
        (a1, k1), (a2, _), (a3, _) = sent
        self.assertIn("Carol Ruiz (Ruiz Wealth) has ended your advisory relationship", a1[2])
        self.assertIn("still here", a1[2])
        self.assertEqual(k1["from_name"], "Carol Ruiz, Ruiz Wealth")
        self.assertIn("Choose my password: https://x/?reset=t", a2[2])
        self.assertIn("7 days", a2[2])
        self.assertIn("Dana Lee has stopped sharing", a3[2])
        self.assertIn("Former clients", a3[2])
        for a, _ in sent:
            self.assertNotIn("$", a[2])
            self.assertNotIn("%", a[2])


# --------------------------------------------------------------------------- #
# the made-up book
# --------------------------------------------------------------------------- #
class DemoTests(unittest.TestCase):

    def test_book_proposal_report(self):
        from datetime import date
        rows = advisor_demo.book(date(2026, 10, 5))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["label"] == "Example" for r in rows))
        self.assertTrue(rows[0]["reasons"])           # who needs a look first
        cmp = advisor_demo.proposal_compare()
        self.assertEqual([c for c, *_ in cmp["rows"]], ["Stocks", "Bonds", "Cash"])
        self.assertTrue(reports.summary_lines(advisor_demo.REPORT["facts"], str))

    def test_no_tickers_named(self):
        import re
        text = repr((advisor_demo.PROPOSAL, advisor_demo.REPORT, advisor_demo.MEETING))
        for t in ("VTI", "VXUS", "BND", "VOO", "SCHD", "AAPL"):
            self.assertIsNone(re.search(rf"\b{t}\b", text), t)


# --------------------------------------------------------------------------- #
# the pages (AppTest)
# --------------------------------------------------------------------------- #
class _App(unittest.TestCase):
    """A fresh scratch database per test, with the app's mail caught."""

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_advtools_app_")
        self.db = os.path.join(self.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        c = portfolio.connect(self.db)
        try:
            self.carol = auth.create_user(c, "carol", PW)
            auth.set_advisor(c, "carol", True)
            c.execute("UPDATE users SET email = 'carol@example.com', email_verified_at = "
                      "'2026-09-01 10:00:00' WHERE id = ?", (self.carol,))
            c.commit()
            secret = two_step.new_secret()
            two_step.enable(c, self.carol, secret, two_step.totp(secret))
            self.carol_ok = f"{self.carol}:{two_step.status(c, self.carol)['stamp']}"
            self.seed(c)
        finally:
            c.close()
        self.files = {}
        self.sent = []

    def seed(self, c):
        pass

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def open_db(self):
        return portfolio.connect(self.db)

    @contextlib.contextmanager
    def app(self, uid, name, page, **state):
        import streamlit
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        real = streamlit.file_uploader

        def uploader(label, *a, key=None, **kw):
            if key and key.startswith("bulk_upload"):
                return self.files.get("up")
            return real(label, *a, key=key, **kw)
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": page, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "RESEND_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused")
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline), \
                unittest.mock.patch.object(streamlit, "file_uploader", uploader):
            at.run()
            # the app's own copy of mailer (codefresh can load a fresh one)
            with unittest.mock.patch.object(sys.modules["mailer"], "send",
                                            lambda *a, **k: self.sent.append(a) or True):
                self.ok(at)
                yield at

    def ok(self, at):
        self.assertEqual([e.message for e in at.exception], [])
        self.assertEqual([e.value for e in at.error if "went wrong" in (e.value or "")], [])

    def rerun(self, at):
        at.run()
        self.ok(at)

    @staticmethod
    def text(at):
        parts = [m.value for m in at.markdown] + [h.proto.body for h in at.get("html")]
        for kind in ("success", "info", "warning", "error", "caption"):
            parts += [str(e.value) for e in getattr(at, kind)]
        return " ".join(parts)


class BulkAddPageTests(_App):

    def upload(self, data):
        self.files["up"] = types.SimpleNamespace(name="clients.csv", getvalue=lambda: data,
                                                 getbuffer=lambda: data, size=len(data),
                                                 type="text/csv")

    def test_review_then_add_and_invite_within_the_limits(self):
        c = self.open_db()
        try:
            auth.create_user(c, "taken@x.com", PW)
            # 49 setup links already sent today: one left
            for i in range(auth.INVITES_PER_ADVISOR_PER_DAY - 1):
                auth.invite_email_limit(c, self.carol, f"earlier{i}@x.com")
        finally:
            c.close()
        self.upload(b"Name,Email\nAnn Ames,ann@x.com\nBo Berg,bo@x.com\nCy Cole,cy@x.com\n"
                    b"Taken,taken@x.com\nBad,nope\n")
        with self.app(self.carol, "carol", "Clients", two_step_ok=self.carol_ok) as at:
            page = self.text(at)
            self.assertIn("3 of 5 ready to add", page)
            self.assertIn("1 are left today", page)
            self.assertIn("bulk_problems", [b.key for b in at.get("download_button")])
            # who it's from comes first
            at.button(key="bulk_add").click()
            self.rerun(at)
            self.assertIn("Add your name first", self.text(at))
            c = self.open_db()
            try:
                self.assertEqual(auth.list_clients(c, self.carol), [])
            finally:
                c.close()
            at.text_input(key="bulk_adv_name").input("Carol Ruiz")
            at.button(key="bulk_add").click()
            self.rerun(at)
            page = self.text(at)
            self.assertIn("Added 3 clients", page)
            self.assertIn("Setup links went to 1", page)
            self.assertIn("2 didn't get a setup link yet", page)
        c = self.open_db()
        try:
            names = dict(auth.list_clients(c, self.carol))
            self.assertEqual(sorted(names.values()), ["Ann Ames", "Bo Berg", "Cy Cole"])
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM invites").fetchone()["n"], 1)
            self.assertEqual((prefs.load(c, self.carol).get("advisor_card") or {})["name"],
                             "Carol Ruiz")
        finally:
            c.close()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Carol Ruiz invited you", self.sent[0][1])


class DemoPageTests(_App):

    def seed(self, c):
        self.pat = auth.create_user(c, "pat@example.com", PW)
        auth.request_advisor(c, self.pat, "Pat Wealth", "CRD 12345")
        self.nina = auth.create_user(c, "nina", PW)
        self.dana = auth.create_client(c, self.carol, "dana@example.com", name="Dana")

    def snapshot(self):
        c = self.open_db()
        try:
            return {t: c.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
                    for t in ("users", "advisor_clients", "advisor_notes", "proposals",
                              "progress_reports", "invites", "email_sends", "former_clients",
                              "positions", "ai_usage")}
        finally:
            c.close()

    def test_a_pending_advisor_sees_the_example_book(self):
        before = self.snapshot()
        with self.app(self.pat, "pat@example.com", "Dashboard") as at:
            at.button(key="menu_advisor_preview").click()
            self.rerun(at)
            page = self.text(at)
            self.assertIn("This is an example", page)
            for name in ("Rivera household", "Sam Okafor", "Lee family"):
                self.assertIn(name, page)
            self.assertIn("Example", page)
            self.assertIn("A steadier mix", page)
            self.assertIn("Talking points", page)
            self.assertIn("went from", page)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.sent, [])
        # the real book isn't touched: carol still has exactly her one client
        c = self.open_db()
        try:
            self.assertEqual([i for i, _ in auth.list_clients(c, self.carol)], [self.dana])
            self.assertEqual(auth.list_clients(c, self.pat), [])
        finally:
            c.close()

    def test_only_while_pending(self):
        with self.app(self.nina, "nina", "Advisor preview") as at:
            self.assertNotIn("This is an example", self.text(at))
            self.assertNotIn("menu_advisor_preview", [b.key for b in at.button])
        with self.app(self.carol, "carol", "Advisor preview",
                      two_step_ok=self.carol_ok) as at:
            self.assertNotIn("This is an example", self.text(at))


class EndPageTests(_App):

    def seed(self, c):
        self.dana = auth.create_client(c, self.carol, "dana@example.com", name="Dana Lee")
        c.execute("UPDATE users SET last_login_at = '2026-09-01 10:00:00', email_verified_at "
                  "= '2026-09-01 10:00:00' WHERE id = ?", (self.dana,))
        c.commit()
        prefs.save(c, self.carol, {"advisor_card": {"name": "Carol Ruiz", "firm": "Ruiz Wealth"}})
        advising.add_note(c, self.dana, self.carol, "Note", "Kept note", "2026-09-01")

    def test_the_advisor_ends_it_from_the_card(self):
        with self.app(self.carol, "carol", "Clients", two_step_ok=self.carol_ok) as at:
            key = f"end_go_card_{self.dana}"
            at.button(key=key).click()               # not ticked: nothing happens
            self.rerun(at)
            self.assertIn("Tick the box", self.text(at))
            at.checkbox(key=f"end_ok_{self.dana}").check()
            at.button(key=key).click()
            self.rerun(at)
            page = self.text(at)
            self.assertIn("Ended your relationship with Dana Lee", page)
            self.assertIn("Former clients", page)
            self.assertIn("former_prep_" + str(self.dana), [b.key for b in at.button])
        c = self.open_db()
        try:
            self.assertFalse(auth.can_view(c, self.carol, self.dana))
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM advisor_notes WHERE "
                                       "client_id = ?", (self.dana,)).fetchone()["n"], 1)
        finally:
            c.close()
        (to, subject, text, *_), = self.sent
        self.assertEqual(to, "dana@example.com")
        self.assertIn("Carol Ruiz (Ruiz Wealth) has ended", text)
        self.assertNotIn("$", text)

    def test_the_client_stops_sharing(self):
        with self.app(self.dana, "dana@example.com", "Advisor notes") as at:
            self.assertIn("Stop sharing with my advisor", " ".join(
                e.label for e in at.expander))
            at.checkbox(key="stop_sharing_ok").check()
            at.button(key="stop_sharing").click()
            self.rerun(at)
            # self-directed now: no Your advisor page, they can bring holdings in
            self.assertEqual(at.session_state["page"], "Dashboard")
            self.assertNotIn("nav_Advisor notes", [b.key for b in at.button])
        c = self.open_db()
        try:
            self.assertIsNone(advising.advisor_of(c, self.dana))
            self.assertEqual(advising.former_clients(c, self.carol)[0]["ended_by"], "client")
        finally:
            c.close()
        (to, subject, text, *_), = self.sent
        self.assertEqual(to, "carol@example.com")
        self.assertIn("Dana Lee has stopped sharing", text)


if __name__ == "__main__":
    unittest.main()
