"""Consent records and the advisor access log (PLAN step 5.6, 5.8, 5.9 and
5.12; master brief 4.3; audit 1.2d and 1.6f): grant / revoke / current /
history, a grant at the setup link, a revoke on every way sharing ends, the
one-time back-fill, the access log written once per page view and shown
only to the client (never another advisor), append-only in code, kept when
an account is deleted, pruned after 7 years, in the client's export. The
app itself runs with streamlit's AppTest for the access log and "revoke
ends access within one request".

    python -m unittest tests.test_consent_access        (from the repo root)
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
import zipfile
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import access_log  # noqa: E402
import admin  # noqa: E402
import advising  # noqa: E402
import auth  # noqa: E402
import consent  # noqa: E402
import disclosures  # noqa: E402
import export  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import tidy  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
NOW = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)
AGREE = dict(agreed=True, adult=True, us_resident=True, terms_version="October 6, 2026")


class _DB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pt_consent_")
        self.db = os.path.join(self.tmp, "t.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.conn = portfolio.connect(self.db)
        self.env = unittest.mock.patch.dict(os.environ, {"MAIL_DRY_RUN": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def advisor(self, name):
        uid = auth.create_user(self.conn, name, PW)
        auth.set_advisor(self.conn, name, True)
        return uid

    def count(self, table, where="1 = 1", params=()):
        return self.conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE {where}",
                                 params).fetchone()["n"]


# --------------------------------------------------------------------------- #
# consent.py
# --------------------------------------------------------------------------- #
class ConsentTests(_DB):

    def test_grant_revoke_current_and_history(self):
        c = self.conn
        carol, omar = self.advisor("carol"), self.advisor("omar")
        dana = auth.create_user(c, "dana", PW)
        self.assertFalse(consent.current(c, dana, carol))
        words = "Share with Carol Lee, Lee Advisers:\n  holdings *and* plan. 100% yours."
        consent.grant(c, dana, carol, words, "intro", now=NOW)
        self.assertTrue(consent.current(c, dana, carol))
        self.assertFalse(consent.current(c, dana, omar))      # per advisor
        consent.revoke(c, dana, carol, "client_stop", text_shown="Stop?",
                       now=NOW + timedelta(days=1))
        self.assertFalse(consent.current(c, dana, carol))
        consent.grant(c, dana, carol, words, "intro", now=NOW + timedelta(days=2))
        self.assertTrue(consent.current(c, dana, carol))
        rows = consent.history(c, dana)
        self.assertEqual([r["kind"] for r in rows], ["grant", "revoke", "grant"])  # newest first
        first = rows[-1]
        # the exact words, verbatim, with their hash, the time in ISO UTC
        self.assertEqual(first["text_shown"], words)
        self.assertEqual(first["text_sha256"], consent.text_sha256(words))
        self.assertEqual(len(first["text_sha256"]), 64)
        self.assertEqual(first["at"], "2026-10-06T12:00:00Z")
        self.assertEqual((first["client_id"], first["advisor_id"], first["scope"],
                          first["how"], first["advisor"]),
                         (dana, carol, "full_sharing", "intro", "carol"))
        self.assertEqual(rows[1]["text_shown"], "Stop?")
        self.assertEqual(consent.between(c, dana, omar), [])
        self.assertEqual(len(consent.between(c, dana, carol)), 3)
        self.assertEqual(consent.history(c, carol), [])

    def test_what_a_record_must_have(self):
        c = self.conn
        carol = self.advisor("carol")
        dana = auth.create_user(c, "dana", PW)
        with self.assertRaises(ValueError):
            consent.grant(c, dana, carol, "   ", "intro")       # a grant needs the words
        with self.assertRaises(ValueError):
            consent.grant(c, dana, carol, "x", "because")       # a known 'how'
        with self.assertRaises(ValueError):
            consent.grant(c, dana, carol, "x", "intro", scope="everything")
        with self.assertRaises(ValueError):
            consent.revoke(c, carol, carol, "admin")             # two accounts
        self.assertEqual(self.count("consent_records"), 0)

    def test_the_setup_link_records_a_grant_with_the_words_shown(self):
        c = self.conn
        carol = self.advisor("carol")
        prefs.save(c, carol, {"advisor_card": {"name": "Carol Lee", "firm": "Lee Advisers"}})
        dana = auth.create_client(c, carol, "dana@example.com", name="Dana")
        self.assertEqual(consent.history(c, dana), [])          # made by the advisor: no grant yet
        token = auth.create_invite(c, carol, dana)
        self.assertEqual(auth.invite_info(c, token)["advisor_id"], carol)
        # a wrong form records nothing
        self.assertFalse(auth.accept_invite(c, token, PW, terms_version="v1")["ok"])
        self.assertEqual(consent.history(c, dana), [])
        res = auth.accept_invite(c, token, PW, **AGREE)
        self.assertTrue(res["ok"])
        (row,) = consent.history(c, dana)
        self.assertEqual((row["kind"], row["how"], row["advisor_id"]),
                         ("grant", "setup_link", carol))
        shown = consent.setup_link_text("Carol Lee, Lee Advisers")
        self.assertEqual(row["text_shown"], shown)
        self.assertIn("Carol Lee, Lee Advisers", shown)
        self.assertTrue(consent.current(c, dana, carol))
        # what the page passes is what's kept
        ed = auth.create_client(c, carol, "ed@example.com")
        token = auth.create_invite(c, carol, ed)
        self.assertTrue(auth.accept_invite(c, token, PW, consent_text="The words on the page.",
                                           **AGREE)["ok"])
        self.assertEqual(consent.history(c, ed)[0]["text_shown"], "The words on the page.")

    def test_every_way_sharing_ends_writes_a_revoke(self):
        c = self.conn
        carol = self.advisor("carol")
        clients = {}
        for name in ("dana", "ed", "fay", "gus"):
            clients[name] = auth.create_client(c, carol, f"{name}@example.com")
            auth.set_password(c, f"{name}@example.com", PW)
            c.execute("UPDATE users SET last_login_at = '2026-09-01 10:00:00' WHERE id = ?",
                      (clients[name],))
            c.commit()
            consent.grant(c, clients[name], carol, "Shared.", "setup_link")
        advising.end_relationship(c, carol, clients["dana"], by="client", text_shown="Stop?")
        advising.end_relationship(c, carol, clients["ed"], by="advisor")
        auth.unlink_client(c, carol, clients["fay"])
        auth.unlink_client(c, carol, clients["fay"])            # no link: nothing more
        boss = auth.create_user(c, "boss", PW)
        admin.set_admin(c, "boss", True)
        self.assertTrue(admin.delete_account(c, clients["gus"], by=boss)["ok"])
        how = {n: [(r["kind"], r["how"]) for r in consent.history(c, uid)]
               for n, uid in clients.items()}
        self.assertEqual(how, {"dana": [("revoke", "client_stop"), ("grant", "setup_link")],
                               "ed": [("revoke", "advisor_end"), ("grant", "setup_link")],
                               "fay": [("revoke", "admin"), ("grant", "setup_link")],
                               "gus": [("revoke", "account_deleted"), ("grant", "setup_link")]})
        self.assertEqual(consent.history(c, clients["dana"])[0]["text_shown"], "Stop?")
        for uid in clients.values():
            self.assertFalse(consent.current(c, uid, carol))
            self.assertFalse(auth.can_view(c, carol, uid))
        # an advisor's account deleted: each of their links gets its revoke
        omar = self.advisor("omar")
        zed = auth.create_client(c, omar, "zed")
        consent.grant(c, zed, omar, "Shared.", "setup_link")
        self.assertTrue(admin.delete_account(c, omar, by=boss)["ok"])
        self.assertEqual([r["how"] for r in consent.history(c, zed)],
                         ["account_deleted", "setup_link"])

    def test_the_back_fill_marks_existing_links_once(self):
        c = self.conn
        carol = self.advisor("carol")
        dana = auth.create_user(c, "dana", PW)
        ed = auth.create_user(c, "ed", PW)
        # a fresh database is marked at once: a link made now gets no 'migration' grant
        self.assertEqual(consent.backfill(c), 0)
        auth.link_client(c, carol, dana)
        self.assertEqual(consent.backfill(c), 0)
        self.assertEqual(consent.history(c, dana), [])
        # a database from before the records (no mark): each link gets one
        c.execute("DELETE FROM app_state WHERE name = ?", (consent.BACKFILL_MARK,))
        auth.link_client(c, carol, ed)
        consent.grant(c, ed, carol, "Already recorded.", "setup_link")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        with unittest.mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            portfolio.connect(self.db).close()                  # the schema setup runs it
        self.assertIn("consent records begun for 1 existing advisor link", err.getvalue())
        (row,) = consent.history(c, dana)
        self.assertEqual((row["kind"], row["how"], row["text_shown"]),
                         ("grant", "migration", consent.MIGRATION_TEXT))
        self.assertEqual([r["how"] for r in consent.history(c, ed)], ["setup_link"])
        self.assertEqual(consent.backfill(c), 0)                # once
        self.assertEqual(len(consent.history(c, dana)), 1)


# --------------------------------------------------------------------------- #
# access_log.py
# --------------------------------------------------------------------------- #
class AccessLogTests(_DB):

    def test_the_client_sees_every_advisor_an_advisor_only_their_own(self):
        c = self.conn
        carol, omar = self.advisor("carol"), self.advisor("omar")
        dana = auth.create_user(c, "dana", PW)
        bob = auth.create_user(c, "bob", PW)
        access_log.record(c, carol, dana, "Dashboard", now=NOW - timedelta(hours=2))
        access_log.record(c, omar, dana, "Plan", now=NOW - timedelta(hours=1))
        access_log.record(c, carol, dana, "Income", now=NOW - timedelta(days=100))
        seen = access_log.for_client(c, dana, dana, now=NOW)
        self.assertEqual([(r["advisor"], r["page"]) for r in seen],
                         [("omar", "Plan"), ("carol", "Dashboard")])   # newest first, 90 days
        self.assertEqual(seen[0]["at"], "2026-10-06T11:00:00Z")
        self.assertEqual(len(access_log.for_client(c, dana, dana, days=None, now=NOW)), 3)
        self.assertEqual([r["page"] for r in access_log.for_client(c, dana, carol, now=NOW)],
                         ["Dashboard"])
        self.assertEqual([r["page"] for r in access_log.for_client(c, dana, omar, now=NOW)],
                         ["Plan"])
        self.assertEqual(access_log.for_client(c, dana, bob, now=NOW), [])
        with self.assertRaises(ValueError):
            access_log.record(c, carol, carol, "Plan")
        with self.assertRaises(ValueError):
            access_log.record(c, carol, dana, " ")
        # what a row holds: who, whom, which page, when - nothing else
        cols = {r[1] for r in c.execute("PRAGMA table_info(advisor_access_log)")}
        self.assertEqual(cols, {"id", "at", "advisor_id", "client_id", "page"})

    def test_one_row_per_page_view(self):
        new = access_log.is_new_view
        self.assertTrue(new(None, 7, "Plan", 1000.0))
        last = (7, "Plan", 1000.0)
        self.assertFalse(new(last, 7, "Plan", 1001.0))           # a rerun
        self.assertFalse(new(last, 7, "Plan", 1000.0 + access_log.REPEAT_SECONDS - 1))
        self.assertTrue(new(last, 7, "Plan", 1000.0 + access_log.REPEAT_SECONDS))
        self.assertTrue(new(last, 7, "Income", 1001.0))          # another page
        self.assertTrue(new(last, 8, "Plan", 1001.0))            # another client


# --------------------------------------------------------------------------- #
# Append-only, kept, pruned, exported
# --------------------------------------------------------------------------- #
TABLES = {"consent_records": "consent.py", "advisor_access_log": "access_log.py"}


class AppendOnlyTests(_DB):

    def test_no_update_or_delete_anywhere_but_the_prune(self):
        """1.6f: no UPDATE, DELETE, TRUNCATE or DROP on either table in any
        module but its own prune (the 7-year retention, run by tidy.py).
        admin.delete_account never names them (KEPT_AFTER_DELETE)."""
        names = "|".join(TABLES)
        bad = re.compile(rf"(UPDATE\s+({names})\b|DELETE\s+FROM\s+({names})\b|TRUNCATE\s+"
                         rf"(TABLE\s+)?({names})\b|DROP\s+TABLE\s+(IF\s+EXISTS\s+)?({names})\b)",
                         re.I)
        hits = []
        for root, dirs, files in os.walk(REPO):
            dirs[:] = [d for d in dirs if d not in (".git", "tests", "venv", ".venv",
                                                    "node_modules", "website", ".claude")]
            for name in files:
                if not name.endswith((".py", ".sql")):
                    continue
                path = os.path.join(root, name)
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                for m in bad.finditer(text):
                    hits.append((os.path.relpath(path, REPO), m.group(0).split()[0].upper()))
        self.assertEqual(sorted(hits), [("access_log.py", "DELETE"), ("consent.py", "DELETE")])
        for table, module in TABLES.items():
            with open(os.path.join(REPO, module), encoding="utf-8") as fh:
                src = fh.read()
            self.assertEqual(src.count(f"DELETE FROM {table}"), 1)
            self.assertIn(f"DELETE FROM {table}", src[src.index("def prune("):])
        # the modules' public functions: add and read, and the prune
        public = {m.__name__: sorted(n for n in dir(m) if callable(getattr(m, n))
                                     and not n.startswith("_")
                                     and getattr(getattr(m, n), "__module__", "") == m.__name__)
                  for m in (consent, access_log)}
        self.assertEqual(public, {
            "consent": ["advisor_label", "ask_text", "backfill", "between", "current", "grant",
                        "history", "prune", "revoke", "setup_link_text", "text_sha256",
                        "to_ask", "unconfirmed"],
            "access_log": ["for_client", "is_new_view", "prune", "record"]})
        # tidy.py is what runs the prunes
        with open(os.path.join(REPO, "tidy.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("consent.prune(", src)
        self.assertIn("access_log.prune(", src)
        # and on Postgres the app's role gets add and read only (DB_ROLES.md)
        self.assertEqual(set(portfolio.APPEND_ONLY_TABLES), set(TABLES))
        self.assertIn("DELETE", portfolio.APPEND_ONLY_REVOKES["northwend_app"])
        self.assertIn("UPDATE", portfolio.APPEND_ONLY_REVOKES["northwend_jobs"])

    def test_deleting_an_account_keeps_the_records(self):
        c = self.conn
        carol = self.advisor("carol")
        dana = auth.create_client(c, carol, "dana@example.com")
        auth.set_password(c, "dana@example.com", PW)
        c.execute("UPDATE users SET last_login_at = '2026-09-01 10:00:00' WHERE id = ?", (dana,))
        c.commit()
        consent.grant(c, dana, carol, "Shared.", "setup_link")
        access_log.record(c, carol, dana, "Plan")
        self.assertEqual(admin.KEPT_AFTER_DELETE,
                         {"consent_records": ("client_id", "advisor_id"),
                          "advisor_access_log": ("advisor_id", "client_id")})
        for table in admin.KEPT_AFTER_DELETE:
            self.assertNotIn(table, admin.ACCOUNT_TABLES)
            self.assertNotIn(table, admin.ACCOUNT_REFERENCES)
        # the client stops sharing, then deletes their own account
        advising.end_relationship(c, carol, dana, by="client")
        self.assertTrue(admin.delete_own(c, dana, PW)["ok"])
        self.assertIsNone(auth.get_username(c, dana))
        self.assertEqual([r["how"] for r in consent.history(c, dana)],
                         ["client_stop", "setup_link"])
        self.assertEqual(self.count("advisor_access_log", "client_id = ?", (dana,)), 1)
        # the advisor's account goes too: the rows still say who
        boss = auth.create_user(c, "boss", PW)
        admin.set_admin(c, "boss", True)
        self.assertTrue(admin.delete_account(c, carol, by=boss)["ok"])
        self.assertEqual(self.count("consent_records", "advisor_id = ?", (carol,)), 2)
        rows = access_log.for_client(c, dana, dana)
        self.assertEqual([(r["advisor_id"], r["advisor"]) for r in rows], [(carol, None)])

    def test_prune_after_seven_years(self):
        c = self.conn
        carol = self.advisor("carol")
        old, recent, live = (auth.create_user(c, n, PW) for n in ("old", "recent", "live"))
        years = lambda n: NOW - timedelta(days=round(365.25 * n))  # noqa: E731
        consent.grant(c, old, carol, "Shared.", "intro", now=years(10))
        consent.revoke(c, old, carol, "client_stop", now=years(8))
        consent.grant(c, recent, carol, "Shared.", "intro", now=years(10))
        consent.revoke(c, recent, carol, "client_stop", now=years(6))
        consent.grant(c, live, carol, "Shared.", "intro", now=years(9))  # still in force
        access_log.record(c, carol, old, "Plan", now=years(8))
        access_log.record(c, carol, recent, "Plan", now=years(6))
        done = tidy.run(c, now=NOW)
        self.assertEqual((done["consent records"], done["advisor access log rows"]), (2, 1))
        self.assertEqual(consent.history(c, old), [])
        self.assertEqual(len(consent.history(c, recent)), 2)    # ended 6 years ago: kept whole
        self.assertTrue(consent.current(c, live, carol))        # in force: never pruned
        self.assertEqual(len(access_log.for_client(c, recent, recent, days=None)), 1)
        self.assertEqual(access_log.for_client(c, old, old, days=None), [])
        self.assertEqual(tidy.run(c, now=NOW)["consent records"], 0)

    def test_the_clients_export_has_both_and_the_advisors_record_their_own(self):
        c = self.conn
        carol, omar = self.advisor("carol"), self.advisor("omar")
        dana = auth.create_client(c, carol, "dana")
        auth.link_client(c, omar, dana)
        consent.grant(c, dana, carol, "Shared with Carol.", "setup_link")
        consent.grant(c, dana, omar, "Shared with Omar.", "setup_link")
        access_log.record(c, carol, dana, "Plan")
        access_log.record(c, omar, dana, "Income")
        files = {n: v.decode() for n, v in (
            (i.filename, zipfile.ZipFile(io.BytesIO(export.export_zip(c, dana))).read(i))
            for i in zipfile.ZipFile(io.BytesIO(export.export_zip(c, dana))).infolist())}
        self.assertIn("Shared with Carol.", files["sharing_with_an_advisor.csv"])
        self.assertIn("Shared with Omar.", files["sharing_with_an_advisor.csv"])
        self.assertIn("text_sha256", files["sharing_with_an_advisor.csv"])
        self.assertIn("Income", files["advisor_visits.csv"])
        self.assertIn("advisor_visits.csv", files["README.txt"])
        # the advisors' own exports hold nothing of these (they're the client's)
        self.assertNotIn("advisor_visits", export.collect(c, carol))
        # an advisor's record of the client: their own consent records only
        record = export.client_record(c, carol, dana)
        self.assertEqual([r["text_shown"] for r in record["consent"]], ["Shared with Carol."])
        self.assertEqual(set(record["consent"][0]), set(export.CONSENT_COLUMNS))


# --------------------------------------------------------------------------- #
# The app: the access log, the Account page, and revoking within one request
# --------------------------------------------------------------------------- #
class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_access_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        if os.path.exists(self.db):
            os.remove(self.db)
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        c = portfolio.connect(self.db)
        try:
            self.carol, self.carol_ok = self._advisor(c, "carol")
            self.omar, self.omar_ok = self._advisor(c, "omar")
            prefs.save(c, self.carol, {"advisor_card": {"name": "Carol Lee"}})
            self.dana = auth.create_client(c, self.carol, "dana", name="Dana")
            auth.set_password(c, "dana", PW)
            c.execute("UPDATE users SET last_login_at = '2026-09-01 10:00:00' WHERE id = ?",
                      (self.dana,))
            c.commit()
            consent.grant(c, self.dana, self.carol, "Shared with Carol.", "setup_link")
            self.zed = auth.create_client(c, self.omar, "zed", name="Zed")
        finally:
            c.close()

    @staticmethod
    def _advisor(c, name):
        uid = auth.create_user(c, name, PW)
        auth.set_advisor(c, name, True)
        secret = two_step.new_secret()
        two_step.enable(c, uid, secret, two_step.totp(secret))
        return uid, f"{uid}:{two_step.status(c, uid)['stamp']}"

    @contextlib.contextmanager
    def _app(self):
        import yfinance

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused")
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline):
            yield

    def _at(self, uid, name, page, **state):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": page, **state}.items():
            at.session_state[k] = v
        return at

    def _run(self, at):
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        return at

    def _rows(self, client_id):
        c = portfolio.connect(self.db)
        try:
            return [(r["advisor_id"], r["page"])
                    for r in reversed(access_log.for_client(c, client_id, client_id))]
        finally:
            c.close()

    def test_one_row_per_page_view_seen_by_the_client_only(self):
        with self._app():
            at = self._run(self._at(self.carol, "carol", "Dashboard",
                                    active_user_id=self.dana, two_step_ok=self.carol_ok))
            self.assertEqual(at.session_state["active_user_id"], self.dana)
            self.assertEqual(self._rows(self.dana), [(self.carol, "Dashboard")])
            self._run(at)                                       # a rerun: no new row
            self.assertEqual(self._rows(self.dana), [(self.carol, "Dashboard")])
            at.session_state["page"] = "Plan"
            self._run(at)
            at.session_state["page"] = "Account"                # the advisor's own page
            self._run(at)
            self.assertEqual(self._rows(self.dana),
                             [(self.carol, "Dashboard"), (self.carol, "Plan")])
            # the advisor's own portfolio isn't logged anywhere
            self._run(self._at(self.carol, "carol", "Dashboard", two_step_ok=self.carol_ok))
            # another advisor, on his own client
            self._run(self._at(self.omar, "omar", "Plan", active_user_id=self.zed,
                               two_step_ok=self.omar_ok))
            self.assertEqual(self._rows(self.zed), [(self.omar, "Plan")])
            self.assertEqual(len(self._rows(self.dana)), 2)
            # omar asking for dana's account falls back to his own: no row
            self._run(self._at(self.omar, "omar", "Plan", active_user_id=self.dana,
                               two_step_ok=self.omar_ok))
            self.assertEqual(len(self._rows(self.dana)), 2)

            # the client's Account page: who, which page, when - carol only
            at = self._run(self._at(self.dana, "dana", "Account"))
            text = " ".join(m.value for m in at.markdown) + " ".join(
                s.value for s in at.subheader)
            self.assertIn("Who has looked at your account", text)
            (frame,) = [d.value for d in at.dataframe]
            self.assertEqual(list(frame.columns), ["When", "Who", "Page"])
            self.assertEqual(sorted(frame["Page"]), ["Home", "Plan"])
            self.assertEqual(set(frame["Who"]), {"Carol Lee"})
            self.assertNotIn("omar", " ".join(str(v) for v in frame.values.ravel()))
            # and omar's client sees only omar
            at = self._run(self._at(self.zed, "zed", "Account"))
            (frame,) = [d.value for d in at.dataframe]
            self.assertEqual(list(frame["Page"]), ["Plan"])

    def test_stop_sharing_ends_access_on_the_very_next_run(self):
        with self._app():
            adv = self._run(self._at(self.carol, "carol", "Plan", active_user_id=self.dana,
                                     two_step_ok=self.carol_ok))
            self.assertEqual(adv.session_state["active_user_id"], self.dana)
            # dana: Your advisor > Stop sharing, through the page itself
            client = self._run(self._at(self.dana, "dana", "Advisor notes"))
            client.checkbox(key="stop_sharing_ok").check()
            client.button(key="stop_sharing").click()
            self._run(client)
            c = portfolio.connect(self.db)
            try:
                latest = consent.history(c, self.dana)[0]
                self.assertEqual((latest["kind"], latest["how"], latest["advisor_id"]),
                                 ("revoke", "client_stop", self.carol))
                self.assertIn("will no longer see your account", latest["text_shown"])
                self.assertFalse(consent.current(c, self.dana, self.carol))
                self.assertFalse(auth.can_view(c, self.carol, self.dana))
            finally:
                c.close()
            before = self._rows(self.dana)
            # carol's very next run, same session, any page: her own account
            adv.session_state["page"] = "Dashboard"
            self._run(adv)
            self.assertEqual(adv.session_state["active_user_id"], self.carol)
            self.assertNotIn(f"client={self.dana}", str(dict(adv.query_params)))
            self.assertEqual(self._rows(self.dana), before)       # and nothing logged


class WordingTests(unittest.TestCase):

    def test_the_disclosures_say_they_are_kept(self):
        text = " ".join(body for _, body in disclosures.SECTIONS)
        self.assertIn("7 years", text)
        self.assertIn("who has looked at your account", text.lower())
        with open(os.path.join(REPO, "docs", "legal", "privacy-policy-DRAFT.md"),
                  encoding="utf-8") as fh:
            draft = fh.read()
        self.assertIn("7 years", draft)
        self.assertIn("consent", draft.lower())


if __name__ == "__main__":
    unittest.main()
