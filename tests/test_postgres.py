"""Postgres: every way the app writes, its pages, and an older database's
upgrade - on a real Postgres. The live app runs on Neon Postgres (pgcompat.py
turns the app's SQLite-style SQL into Postgres's), while every other test
uses SQLite, so this is where Postgres-only failures show: SQL Postgres
refuses, a value too big for its column, a transaction left failed, a write
another connection never sees (not committed), a connection never handed
back to the pool.

Skipped unless NORTHWEND_TEST_PG is the URL of a Postgres database the tests
may use (postgresql://user@host:port/db). Each run works in schemas of its
own (nwtest_...), dropped at the end, so nothing else in it is touched. The
Tests workflow's postgres-tests job runs it against a postgres:16 service:

    NORTHWEND_TEST_PG=postgresql://postgres@localhost:5432/postgres \\
        python -m unittest tests.test_postgres -v
"""

import io
import json
import os
import re
import secrets
import sys
import types
import unittest
import unittest.mock
import zipfile
from datetime import date, datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import accounts  # noqa: E402
import admin  # noqa: E402
import advising  # noqa: E402
import advisor  # noqa: E402
import ai_usage  # noqa: E402
import auth  # noqa: E402
import checkin  # noqa: E402
import checkin_email  # noqa: E402
import csv_import  # noqa: E402
import error_alerts  # noqa: E402
import export  # noqa: E402
import feature_counts  # noqa: E402
import fund_holdings  # noqa: E402
import future_notes  # noqa: E402
import income  # noqa: E402
import learn  # noqa: E402
import live_prices  # noqa: E402
import mailer  # noqa: E402
import perf  # noqa: E402
import pgcompat  # noqa: E402
import plans  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import proposals  # noqa: E402
import reports  # noqa: E402
import sample_data  # noqa: E402
import sync_history  # noqa: E402
import two_step  # noqa: E402
import txn_import  # noqa: E402
import watchlist  # noqa: E402
import weekly_email  # noqa: E402

PG = os.environ.get("NORTHWEND_TEST_PG", "").strip()
SKIP = "set NORTHWEND_TEST_PG to a Postgres URL (postgresql://...) to run these"
if os.environ.get("NORTHWEND_TEST_PG_REQUIRED") and not PG.startswith(("postgres://",
                                                                       "postgresql://")):
    raise RuntimeError("NORTHWEND_TEST_PG_REQUIRED is set, but NORTHWEND_TEST_PG isn't a "
                       "postgresql:// URL - these tests would only be skipped")
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
BROKERS = os.path.join(FIXTURES, "brokers")
OLD_SCHEMA = os.path.join(FIXTURES, "schema_pg_2026-09-30.sql")   # schema_pg.sql at 7a43922
PW = "pw-123456789"
AGREE = dict(agreed=True, adult=True, terms_version="October 1, 2026")
NOW = datetime.now(timezone.utc).replace(microsecond=0)
TODAY = NOW.date()

_SCHEMAS: list[str] = []
_DSNS: list[str] = []


def _admin():
    import psycopg
    return psycopg.connect(PG, autocommit=True)


def fresh_db(tag: str) -> str:
    """A DSN for a new, empty schema of this run's (dropped in tearDownModule)."""
    name = f"nwtest_{os.getpid()}_{secrets.token_hex(3)}_{tag}"
    with _admin() as c:
        c.execute(f"CREATE SCHEMA {name}")
    _SCHEMAS.append(name)
    dsn = f"{PG}{'&' if '?' in PG else '?'}options=-csearch_path%3D{name}"
    _DSNS.append(dsn)
    return dsn


def _pgcompats():
    """pgcompat as imported here, and as the app last loaded it (codefresh
    can load a fresh copy; the pools are carried over to it)."""
    mods = {id(pgcompat): pgcompat}
    if sys.modules.get("pgcompat") is not None:
        mods[id(sys.modules["pgcompat"])] = sys.modules["pgcompat"]
    return list(mods.values())


def _pools(dsn):
    return list({id(p): p for m in _pgcompats() for p in [m._POOLS.get(dsn)] if p}.values())


def in_use(dsn) -> int:
    """Connections of this database's pool checked out and not handed back."""
    n = 0
    for p in _pools(dsn):
        s = p.get_stats()
        n += s.get("pool_size", 0) - s.get("pool_available", 0)
    return n


def close_db(dsn):
    for p in _pools(dsn):
        p.close()
    for m in _pgcompats():
        m._POOLS.pop(dsn, None)


def tearDownModule():
    if not PG:
        return
    for dsn in _DSNS:
        close_db(dsn)
    with _admin() as c:
        for name in _SCHEMAS:
            c.execute(f"DROP SCHEMA IF EXISTS {name} CASCADE")


@unittest.skipUnless(PG, SKIP)
class _PG(unittest.TestCase):
    """One schema per class, set up by today's code (portfolio.connect)."""
    TAG = "t"

    @classmethod
    def setUpClass(cls):
        cls.dsn = fresh_db(cls.TAG)
        cls.conn = portfolio.connect(cls.dsn)

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        close_db(cls.dsn)

    def tearDown(self):
        # the connection must still work after every step - Postgres refuses
        # everything in a transaction a failed statement left behind (rolled
        # back either way, so the next test starts clean)
        try:
            self.conn.execute("SELECT 1").fetchone()
        finally:
            self.conn.rollback()

    def seen(self, sql, params=()):
        """What ANOTHER connection sees: a write that wasn't committed (lost
        when the app's connection goes back to the pool) is missing here."""
        c = portfolio.connect(self.dsn)
        try:
            return [dict(r) for r in c.execute(sql, params)]
        finally:
            c.close()

    def one(self, sql, params=()):
        rows = self.seen(sql, params)
        self.assertEqual(len(rows), 1, rows)
        return rows[0]

    def user(self, name, *, advisor=False):
        uid = auth.create_user(self.conn, name, PW)
        if advisor:
            auth.set_advisor(self.conn, name, True)
        return uid


class _Mail:
    """mailer.send, recorded instead of sent."""

    def __init__(self):
        self.sent = []

    def __call__(self, to, subject, text, *a, **kw):
        self.sent.append((to, subject))
        return True


def _mail(test):
    box = _Mail()
    for m in {id(mailer): mailer, id(sys.modules.get("mailer", mailer)):
              sys.modules.get("mailer", mailer)}.values():
        p = unittest.mock.patch.object(m, "send", box)
        p.start()
        test.addCleanup(p.stop)
    return box


# --------------------------------------------------------------------------- #
# signing up, email links, passwords, sessions
# --------------------------------------------------------------------------- #
class SignInTests(_PG):
    TAG = "signin"

    def test_sign_up_confirm_reset_and_change_email(self):
        c = self.conn
        made = auth.sign_up(c, "Sam@Example.com", PW, seconds_open=10, ip="203.0.113.5", **AGREE)
        self.assertTrue(made["ok"], made)
        uid = made["user_id"]
        row = self.one("SELECT username, email, terms_version, terms_via FROM users WHERE id = ?",
                       (uid,))
        self.assertEqual(row, {"username": "sam@example.com", "email": "sam@example.com",
                               "terms_version": "October 1, 2026", "terms_via": None})
        self.assertEqual(self.one("SELECT COUNT(*) AS n FROM signups WHERE ok = 1")["n"], 1)
        again = auth.sign_up(c, "sam@example.com", PW, seconds_open=10, ip="203.0.113.5", **AGREE)
        self.assertIn("already an account", again["error"])

        sent = auth.start_confirmation(c, uid, ip="203.0.113.5")
        self.assertTrue(sent["ok"], sent)
        self.assertIn("just sent one", auth.start_confirmation(c, uid)["error"])  # read back
        self.assertTrue(auth.confirm_email(c, sent["token"])["ok"])
        self.assertIsNotNone(self.one("SELECT email_verified_at FROM users WHERE id = ?",
                                      (uid,))["email_verified_at"])
        again = auth.confirm_email(c, sent["token"])   # used: says it's already confirmed
        self.assertEqual((again["ok"], again["already"]), (True, True))

        reset = auth.request_password_reset(c, "SAM@example.com", ip="203.0.113.5")
        self.assertEqual(reset["to"], "sam@example.com")
        self.assertEqual(auth.reset_info(c, reset["token"])["user_id"], uid)
        self.assertTrue(auth.reset_password(c, reset["token"], "new-pass-12345")["ok"])
        self.assertEqual(auth.verify_login(c, "sam@example.com", "new-pass-12345"), uid)
        # no usable link is left (a used confirm link is remembered a day as
        # 'confirmed', only to answer "already confirmed")
        self.assertEqual(self.seen("SELECT * FROM email_tokens WHERE user_id = ? "
                                   "AND purpose <> 'confirmed'", (uid,)), [])

        change = auth.start_email_change(c, uid, "sam.new@example.com", "new-pass-12345")
        self.assertTrue(change["ok"], change)
        self.assertEqual(auth.pending_email_change(c, uid), "sam.new@example.com")
        done = auth.confirm_email_change(c, change["token"])
        self.assertEqual((done["ok"], done["username"]), (True, "sam.new@example.com"))
        self.assertEqual(self.one("SELECT username, email FROM users WHERE id = ?", (uid,)),
                         {"username": "sam.new@example.com", "email": "sam.new@example.com"})

        auth.set_display_name(c, uid, "  Sam   Lee ")
        self.assertEqual(self.one("SELECT display_name FROM users WHERE id = ?", (uid,)),
                         {"display_name": "Sam Lee"})

    def test_lockout_sessions_and_changing_the_password(self):
        c = self.conn
        uid = self.user("lena")
        for _ in range(auth.MAX_FAILED_LOGINS):
            self.assertIsNone(auth.attempt_login(c, "lena", "wrong")["user_id"])
        self.assertTrue(auth.attempt_login(c, "Lena", PW)["locked_minutes"])
        self.assertEqual(self.one("SELECT failures FROM login_failures WHERE username_key = ?",
                                  (auth._login_key("lena"),))["failures"],
                         auth.MAX_FAILED_LOGINS)
        self.assertTrue(auth.unlock_login(c, "lena"))
        self.assertEqual(auth.attempt_login(c, "lena", PW)["user_id"], uid)
        self.assertIsNotNone(self.one("SELECT last_login_at FROM users WHERE id = ?",
                                      (uid,))["last_login_at"])

        token = auth.create_session(c, uid)
        other = auth.create_session(c, uid)
        self.assertEqual(auth.session_user(c, token), (uid, "lena"))
        changed = auth.change_password(c, uid, PW, "newer-pass-123", keep_session=True)
        self.assertTrue(changed["ok"], changed)
        self.assertIsNone(auth.session_user(c, token))   # every other sign-in ended
        self.assertIsNone(auth.session_user(c, other))
        third = auth.create_session(c, uid)
        self.assertEqual(auth.end_other_sessions(c, uid, changed["token"]), 1)
        self.assertIsNone(auth.session_user(c, third))
        auth.end_session(c, changed["token"])
        self.assertEqual(self.seen("SELECT * FROM login_sessions WHERE user_id = ?", (uid,)), [])

    def test_wrong_passwords_from_one_address_pause_sign_in_there(self):
        # audit 1.1c: counted per address across usernames, key "addr:" + hash
        c = self.conn
        uid = self.user("addy")
        ip = "203.0.113.9"
        for i in range(auth.MAX_FAILED_LOGINS_PER_ADDRESS):
            r = auth.attempt_login(c, f"guess{i}", "wrong", ip=ip, now=NOW)
        self.assertTrue(r["from_here"])
        r = auth.attempt_login(c, "addy", PW, ip=ip, now=NOW + timedelta(minutes=1))
        self.assertEqual((r["user_id"], r["from_here"]), (None, True))
        self.assertEqual(auth.attempt_login(c, "addy", PW, ip="198.51.100.1",
                                            now=NOW + timedelta(minutes=1))["user_id"], uid)
        key = "addr:" + auth._address_key(ip)
        self.assertEqual(self.one("SELECT failures FROM login_failures WHERE username_key = ?",
                                  (key,))["failures"], auth.MAX_FAILED_LOGINS_PER_ADDRESS)
        later = NOW + timedelta(minutes=auth.LOCKOUT_MINUTES + 1)
        self.assertEqual(auth.attempt_login(c, "addy", PW, ip=ip, now=later)["user_id"], uid)

    def test_quoted_text_percent_signs_and_casts_reach_postgres_as_written(self):
        c = self.conn
        uid = self.user("quinn")
        c.execute("UPDATE users SET last_login_at = '2026-10-01 10:00:00', "
                  "display_name = 'Q? 100%' WHERE id = ?", (uid,))
        c.commit()
        row = c.execute("SELECT display_name, last_login_at, CAST(id AS TEXT)::int AS i "
                        "FROM users WHERE username LIKE 'qui%' AND id = :id", {"id": uid}).fetchone()
        self.assertEqual(tuple(row), ("Q? 100%", "2026-10-01 10:00:00", uid))

    def test_a_taken_username_leaves_the_connection_usable(self):
        # manage_users.py's bulk create carries on after one that exists
        self.user("taken")
        with self.assertRaises(portfolio.DBError):
            auth.create_user(self.conn, "taken", PW)
        self.assertIsNotNone(auth.create_user(self.conn, "next.one", PW))
        self.assertEqual(len(self.seen("SELECT id FROM users WHERE username IN "
                                       "('taken', 'next.one')")), 2)


class TwoStepTests(_PG):
    TAG = "twostep"

    def test_on_codes_backup_codes_remember_off_and_reset(self):
        c = self.conn
        uid = self.user("tess")
        secret = two_step.new_secret()
        on = two_step.enable(c, uid, secret, two_step.totp(secret, NOW), now=NOW)
        self.assertTrue(on["ok"], on)
        self.assertTrue(self.one("SELECT last_token_step FROM two_step WHERE user_id = ?",
                                 (uid,))["last_token_step"] > 0)
        later = NOW + timedelta(seconds=60)
        code = two_step.totp(secret, later)
        self.assertTrue(two_step.verify(c, uid, code, now=later)["ok"])
        self.assertFalse(two_step.verify(c, uid, code, now=later)["ok"])   # no replay
        used = two_step.verify(c, uid, on["backup_codes"][0], now=later)
        self.assertEqual((used["ok"], used["used_backup"]), (True, True))
        self.assertEqual(len(self.one("SELECT backup_codes_hash FROM two_step WHERE user_id = ?",
                                      (uid,))["backup_codes_hash"].split()),
                         two_step.BACKUP_CODES - 1)
        for _ in range(auth.MAX_FAILED_LOGINS):
            two_step.verify(c, uid, "000000", now=later)
        self.assertTrue(two_step.verify(c, uid, two_step.totp(secret, later),
                                        now=later)["locked_minutes"])
        self.assertTrue(two_step.unlock(c, uid))

        token = auth.create_session(c, uid)
        self.assertTrue(two_step.remember_device(c, token, uid))
        self.assertTrue(two_step.device_remembered(c, token, uid))
        fresh = two_step.new_backup_codes(c, uid, PW)
        self.assertTrue(fresh["ok"], fresh)
        self.assertTrue(two_step.disable(c, uid, PW)["ok"])
        self.assertFalse(two_step.is_on(c, uid))
        self.assertFalse(two_step.device_remembered(c, token, uid))
        self.assertTrue(two_step.enable(c, uid, secret, two_step.totp(secret))["ok"])
        self.assertTrue(two_step.reset(c, uid))
        self.assertEqual(self.seen("SELECT * FROM two_step WHERE user_id = ?", (uid,)), [])
        self.assertEqual(self.seen("SELECT * FROM login_sessions WHERE user_id = ?", (uid,)), [])


# --------------------------------------------------------------------------- #
# advisors: access, clients, notes, proposals, reports, records
# --------------------------------------------------------------------------- #
class AdvisorTests(_PG):
    TAG = "advisor"

    def advisor_with_client(self, tag):
        carol = self.user(f"carol.{tag}", advisor=True)
        dana = auth.create_client(self.conn, carol, f"dana.{tag}@example.com", name="Dana Lee")
        return carol, dana

    def test_asking_for_advisor_access_approved_or_declined(self):
        c = self.conn
        box = _mail(self)
        nia = auth.sign_up(c, "nia@example.com", PW, seconds_open=10, **AGREE)["user_id"]
        omar = auth.sign_up(c, "omar@example.com", PW, seconds_open=10, **AGREE)["user_id"]
        auth.request_advisor(c, nia, "Nia Wealth", "1234567")
        auth.request_advisor(c, omar, "Omar Capital", "7654321")
        self.assertEqual([r["username"] for r in auth.pending_advisor_requests(c)],
                         ["nia@example.com", "omar@example.com"])
        self.assertEqual(admin.approve_advisor(c, "nia@example.com", "https://app.example/"),
                         {"ok": True, "emailed": True})
        self.assertEqual(admin.decline_advisor(c, "omar@example.com", "https://app.example/"),
                         {"ok": True, "emailed": True})
        self.assertEqual([to for to, _ in box.sent], ["nia@example.com", "omar@example.com"])
        self.assertEqual(self.one("SELECT is_advisor FROM users WHERE id = ?", (nia,)),
                         {"is_advisor": 1})
        decided = {r["user_id"]: r["decision"] for r in self.seen(
            "SELECT user_id, decision FROM advisor_requests")}
        self.assertEqual(decided, {nia: "approved", omar: "declined"})
        rows = {a["id"]: a for a in admin.list_accounts(c)}
        self.assertEqual((rows[nia]["role"], rows[omar]["role"]), ("advisor", "investor"))
        self.assertIsNotNone(rows[nia]["licence_checked"])

        self.assertTrue(admin.set_admin(c, "nia@example.com", True))
        self.assertTrue(admin.is_admin(c, nia))
        made = admin.create_account(c, "pat@example.com")
        self.assertTrue(made["ok"], made)
        link = auth.setup_link(c, made["user_id"])
        self.assertTrue(auth.reset_password(c, link["token"], "pat-pass-12345")["ok"])
        self.assertEqual(auth.verify_login(c, "pat@example.com", "pat-pass-12345"),
                         made["user_id"])

    def test_add_and_invite_a_client_who_accepts_with_consent(self):
        c = self.conn
        carol, dana = self.advisor_with_client("invite")
        household = auth.create_client(c, carol, "", name="Chen household")
        self.assertEqual(auth.get_username(c, household), "chen.household")
        token = auth.create_invite(c, carol, dana)
        self.assertIsNotNone(auth.pending_invite(c, dana))
        refused = auth.accept_invite(c, token, "clientpass1", agreed=True,
                                     terms_version="v")   # not ticked 18 or over
        self.assertFalse(refused["ok"])
        self.assertIsNotNone(auth.invite_info(c, token))
        ok = auth.accept_invite(c, token, "clientpass1", **AGREE)
        self.assertTrue(ok["ok"], ok)
        row = self.one("SELECT terms_version, terms_via, email_verified_at, last_login_at "
                       "FROM users WHERE id = ?", (dana,))
        self.assertEqual((row["terms_version"], row["terms_via"]),
                         ("October 1, 2026", auth.TERMS_VIA_SETUP_LINK))
        self.assertTrue(row["email_verified_at"] and row["last_login_at"])
        self.assertEqual(self.seen("SELECT * FROM invites WHERE user_id = ?", (dana,)), [])
        self.assertEqual(auth.verify_login(c, f"dana.invite@example.com", "clientpass1"), dana)

        self.assertTrue(auth.set_client_name(c, carol, dana, " Dana  and Lee "))
        self.assertEqual(dict(auth.list_clients(c, carol))[dana], "Dana and Lee")
        auth.record_agreement(c, household, "v1", via=auth.TERMS_VIA_SIGN_IN)
        self.assertEqual(self.one("SELECT terms_via FROM users WHERE id = ?", (household,)),
                         {"terms_via": auth.TERMS_VIA_SIGN_IN})
        self.assertTrue(advising.set_client_can_import(c, carol, dana, True))
        self.assertEqual(advising.clients_can_import(c, [dana, household]), {dana})
        auth.cancel_invite(c, household)
        auth.unlink_client(c, carol, household)
        self.assertEqual([i for i, _ in auth.list_clients(c, carol)], [dana])

    def test_notes_edit_archive_restore_and_messages(self):
        c = self.conn
        carol, dana = self.advisor_with_client("notes")
        other = auth.create_client(c, carol, "eli.notes@example.com", name="Eli")
        advising.add_note(c, dana, carol, "Review", "Met to review the plan", "2026-09-01")
        advising.add_note(c, dana, carol, "Next step", "Open a Roth IRA", "2026-09-02")
        advising.add_note(c, dana, carol, "Note", "Prefers email", "2026-09-03", private=True)
        notes = {n["kind"]: n for n in advising.list_notes(c, dana, include_private=True)}
        self.assertEqual(len(advising.list_notes(c, dana, include_private=False)), 2)
        step = notes["Next step"]["id"]
        self.assertTrue(advising.edit_note(c, dana, step, "Open a Roth IRA this month",
                                           now=NOW))
        hist = json.loads(self.one("SELECT history FROM advisor_notes WHERE id = ?",
                                   (step,))["history"])
        self.assertEqual([h["body"] for h in hist], ["Open a Roth IRA"])
        advising.set_done(c, dana, step, True)
        self.assertEqual(self.one("SELECT done FROM advisor_notes WHERE id = ?", (step,)),
                         {"done": 1})
        self.assertTrue(advising.archive_note(c, dana, step, now=NOW))
        self.assertFalse(advising.archive_note(c, other, step))   # not that client's
        self.assertNotIn(step, [n["id"] for n in advising.list_notes(c, dana,
                                                                     include_private=True)])
        self.assertEqual([n["id"] for n in advising.list_notes(c, dana, include_private=True,
                                                               archived=True)], [step])
        self.assertTrue(advising.restore_note(c, dana, step))
        self.assertIsNone(self.one("SELECT archived_at FROM advisor_notes WHERE id = ?",
                                   (step,))["archived_at"])
        self.assertEqual(advising.last_review(c, dana), "2026-09-01")

        sent = advising.message_clients(c, carol, [dana, other], "Markets were bumpy.", now=NOW)
        self.assertEqual(sent["sent_to"], [dana, other])
        self.assertFalse(advising.message_clients(c, carol, [dana], "Markets were bumpy.",
                                                  now=NOW + timedelta(minutes=1))["ok"])
        self.assertEqual(len(self.seen("SELECT id FROM advisor_notes WHERE is_message = 1")), 2)
        by_client = advising.notes_for(c, [dana, other], include_private=False)
        self.assertEqual(len(by_client[other]), 1)

        advising.save_model(c, carol, "Balanced", {"Stocks": 60, "Bonds": 40})
        advising.save_model(c, carol, "Balanced", {"Stocks": 50, "Bonds": 50})   # replaced
        (model,) = advising.list_models(c, carol)
        self.assertEqual(model["target_alloc"], {"Stocks": 50.0, "Bonds": 50.0})
        advising.delete_model(c, carol, model["id"])
        self.assertEqual(self.seen("SELECT * FROM model_portfolios WHERE advisor_id = ?",
                                   (carol,)), [])

    def test_proposals_and_progress_reports(self):
        c = self.conn
        carol, dana = self.advisor_with_client("prop")
        pid = proposals.save(c, carol, dana, title="Steadier", mix={"Stocks": 60, "Bonds": 40},
                             note="Less ups and downs")
        draft = proposals.save(c, carol, dana, title="Draft only", mix={"Stocks": 100})
        self.assertEqual(proposals.save(c, carol, dana, title="Steadier mix",
                                        mix={"Stocks": 55, "Bonds": 45}, proposal_id=pid), pid)
        self.assertTrue(proposals.share(c, carol, pid))
        self.assertEqual([p["id"] for p in proposals.for_client(c, dana, include_drafts=False)],
                         [pid])
        self.assertEqual(advising.waiting_for_client(c, dana)["proposals"], 1)
        self.assertTrue(proposals.respond(c, dana, pid, True))
        self.assertFalse(proposals.respond(c, dana, pid, False))   # answered already
        proposals.delete(c, carol, draft)
        self.assertEqual(self.seen("SELECT id, status FROM proposals WHERE client_id = ?",
                                   (dana,)), [{"id": pid, "status": "accepted"}])

        perf.log_open(self.dsn, dana, {"portfolio_value": 1000.0}, min_gap_sec=0)
        start, end = reports.period_bounds("Last month", TODAY)[:2]
        facts = reports.build(c, dana, start, end, value_now=1100.0, today=TODAY)
        rid = reports.save(c, carol, dana, label="Last month", start=start, end=end,
                           facts=facts, message="Steady month.")
        self.assertEqual(reports.last_end(c, dana), end.isoformat())
        ends, labels = reports.sent(c, [dana])
        self.assertEqual((ends, labels), ({dana: end.isoformat()}, {(dana, "Last month")}))
        self.assertEqual(advising.waiting_for_client(c, dana)["reports"], 1)
        reports.mark_read(c, dana, rid)
        self.assertIsNotNone(self.one("SELECT read_at FROM progress_reports WHERE id = ?",
                                      (rid,))["read_at"])
        self.assertEqual(reports.for_client(c, dana)[0]["facts"]["value_end"],
                         facts["value_end"])

    def test_client_records_and_export_everything(self):
        c = self.conn
        carol, dana = self.advisor_with_client("rec")
        omar = self.user("omar.rec", advisor=True)
        advising.add_note(c, dana, carol, "Note", "Shared note", "2026-09-01")
        advising.add_note(c, dana, carol, "Note", "Private note", "2026-09-02", private=True)
        hidden = max(n["id"] for n in advising.list_notes(c, dana, include_private=True))
        advising.edit_note(c, dana, hidden, "Private note, edited", now=NOW)
        advising.archive_note(c, dana, hidden, now=NOW)
        proposals.share(c, carol, proposals.save(c, carol, dana, title="Mix",
                                                 mix={"Stocks": 70, "Bonds": 30}))
        advisor.save_profile(c, dana, {"goal": "Retirement", "time_horizon_years": 20})
        advisor.save_memory(c, dana, "likes short answers")
        sample_data.load(c, dana)

        record = zipfile.ZipFile(io.BytesIO(export.client_record_zip(c, carol, dana)))
        self.assertIn("notes.csv", record.namelist())
        notes = record.read("notes.csv").decode()
        self.assertIn("Private note, edited", notes)          # archived ones too
        self.assertIn("Private note", record.read("note_history.csv").decode())
        self.assertNotIn("likes short answers", record.read("profile.csv").decode())
        with self.assertRaises(PermissionError):
            export.client_record_zip(c, omar, dana)
        everyone = zipfile.ZipFile(io.BytesIO(export.all_client_records_zip(c, carol)))
        self.assertIn(f"dana-lee-{dana}/notes.csv", everyone.namelist())

        mine = zipfile.ZipFile(io.BytesIO(export.export_zip(c, dana)))
        names = mine.namelist()
        for f in ("account.csv", "holdings.csv", "profile.csv", "from_your_advisor_notes.csv",
                  "from_your_advisor_proposals.csv"):
            self.assertIn(f, names)
        shown = mine.read("from_your_advisor_notes.csv").decode()
        self.assertIn("Shared note", shown)
        self.assertNotIn("Private note", shown)
        self.assertNotIn("password", mine.read("account.csv").decode())

    def test_weekly_email_recipients_and_run(self):
        c = self.conn
        carol, dana = self.advisor_with_client("week")
        c.execute("UPDATE users SET email = 'carol.week@example.com' WHERE id = ?", (carol,))
        c.commit()
        self.assertIn(carol, [r["id"] for r in weekly_email.recipients(c)])
        proposals.respond(c, dana, proposals.save(c, carol, dana, title="Mix",
                                                  mix={"Stocks": 60, "Bonds": 40}), True)
        pid = proposals.save(c, carol, dana, title="Mix 2", mix={"Stocks": 50, "Bonds": 50})
        proposals.share(c, carol, pid)
        proposals.respond(c, dana, pid, True)
        sent = []
        done = weekly_email.run(c, "https://app.example/", TODAY,
                                send=lambda to, link, lines: sent.append(to) or True)
        if sent:
            self.assertEqual(prefs.load(c, carol)[weekly_email.PREF_SENT],
                             advising.week_of(TODAY))
            again = weekly_email.run(c, "https://app.example/", TODAY, send=lambda *a: True)
            self.assertGreaterEqual(again["already"], 1)
        self.assertEqual(sum(done.values()), len(weekly_email.recipients(c)))

    def test_clients_from_a_file_checks_and_invites_left(self):
        import client_csv
        c = self.conn
        carol, dana = self.advisor_with_client("csv")
        self.user("taken.csv@example.com")
        rows = client_csv.parse(
            b"Client name,Email\nNew,new.csv@example.com\nDana,DANA.CSV@example.com\n"
            b"Taken,taken.csv@example.com\nBad,nope\nNew again,new.csv@example.com\n")["rows"]
        states = [r["state"] for r in client_csv.review(c, carol, rows)]
        self.assertEqual(states, ["ok", "client", "taken", "invalid", "duplicate"])
        self.assertEqual(len(self.seen("SELECT * FROM email_sends WHERE purpose = "
                                       "'client_check'")), 2)
        with unittest.mock.patch.object(auth, "CLIENT_CHECKS_PER_DAY", 2):
            more = client_csv.parse(b"name,email\nX,x.csv@example.com\n")["rows"]
            self.assertEqual(client_csv.review(c, carol, more)[0]["state"], "later")
        left = auth.invites_left_today(c, carol)
        self.assertIsNone(auth.invite_email_limit(c, carol, "new.csv@example.com"))
        self.assertEqual(auth.invites_left_today(c, carol), left - 1)

    def test_ending_a_relationship_each_way(self):
        c = self.conn
        carol, dana = self.advisor_with_client("end")
        c.execute("UPDATE users SET last_login_at = ? WHERE id = ?", ("2026-09-01 10:00:00",
                                                                     dana))
        c.commit()
        advising.add_note(c, dana, carol, "Note", "Kept note", "2026-09-01")
        proposals.share(c, carol, proposals.save(c, carol, dana, title="Mix",
                                                 mix={"Stocks": 60, "Bonds": 40}))
        auth.create_invite(c, carol, dana)
        res = advising.end_relationship(c, carol, dana, by="advisor", now=NOW)
        self.assertEqual((res["ok"], res["account"]), (True, "kept"))
        self.assertFalse(auth.can_view(c, carol, dana))
        self.assertEqual(self.seen("SELECT * FROM advisor_clients WHERE client_id = ?",
                                   (dana,)), [])
        self.assertEqual(self.seen("SELECT * FROM invites WHERE user_id = ?", (dana,)), [])
        self.assertEqual(self.one("SELECT ended_by, account, client_name FROM former_clients "
                                  "WHERE client_id = ?", (dana,)),
                         {"ended_by": "advisor", "account": "kept", "client_name": "Dana Lee"})
        self.assertEqual(len(self.seen("SELECT id FROM advisor_notes WHERE client_id = ?",
                                       (dana,))), 1)
        record = zipfile.ZipFile(io.BytesIO(export.client_record_zip(c, carol, dana)))
        self.assertIn("Kept note", record.read("notes.csv").decode())
        self.assertIn(f"former-dana-lee-{dana}/notes.csv", zipfile.ZipFile(io.BytesIO(
            export.all_client_records_zip(c, carol))).namelist())
        self.assertIn("your_former_clients.csv", zipfile.ZipFile(io.BytesIO(
            export.export_zip(c, carol))).namelist())

        # never signed in, with an email: a link to choose a password
        eve = auth.create_client(c, carol, "eve.end@example.com", name="Eve")
        res = advising.end_relationship(c, carol, eve, by="advisor", now=NOW)
        self.assertEqual(res["account"], "setup link")
        self.assertTrue(auth.reset_password(c, res["setup_token"], "eves-own-pass1")["ok"])
        self.assertEqual(auth.verify_login(c, "eve.end@example.com", "eves-own-pass1"), eve)

        # never signed in, no email: closed, the advisor's records stay
        hh = auth.create_client(c, carol, "", name="End household")
        sample_data.load(c, hh)
        advising.add_note(c, hh, carol, "Review", "First meeting", "2026-09-01")
        self.assertEqual(advising.end_relationship(c, carol, hh, by="advisor")["account"],
                         "closed")
        self.assertEqual(self.seen("SELECT * FROM users WHERE id = ?", (hh,)), [])
        self.assertEqual(self.seen("SELECT * FROM positions WHERE user_id = ?", (hh,)), [])
        self.assertEqual(len(self.seen("SELECT id FROM advisor_notes WHERE client_id = ?",
                                       (hh,))), 1)

        # the client ends it
        omar = auth.create_client(c, carol, "omar.end@example.com", name="Omar")
        res = advising.end_relationship(c, carol, omar, by="client")
        self.assertEqual(res["ok"], True)
        self.assertIsNone(advising.advisor_of(c, omar))
        self.assertEqual([f["ended_by"] for f in advising.former_clients(c, carol)][0], "client")


# --------------------------------------------------------------------------- #
# notes to future you and the monthly check-in's reminder email
# --------------------------------------------------------------------------- #
@unittest.skipUnless(PG, SKIP)
class FutureNotesTests(_PG):
    TAG = "fnotes"

    def test_notes_add_edit_delete_export_and_never_the_advisors(self):
        c = self.conn
        carol = self.user("carol.fn", advisor=True)
        dana = auth.create_client(c, carol, "dana.fn@example.com", name="Dana")
        self.assertTrue(future_notes.save(c, dana, "vti", "Holding this for 20 years",
                                          now="2026-03-03T10:00:00Z"))
        self.assertTrue(future_notes.save(c, dana, None, "For the house; not before 2030"))
        future_notes.save(c, dana, "VTI", "Twenty years, whole market",
                          now="2026-04-01T10:00:00Z")
        # what another connection sees: committed, one note per holding, the plan's NULL
        self.assertEqual(self.one("SELECT body, created_at, updated_at FROM future_notes "
                                  "WHERE user_id = ? AND symbol = ?", (dana, "VTI")),
                         {"body": "Twenty years, whole market",
                          "created_at": "2026-03-03T10:00:00Z",
                          "updated_at": "2026-04-01T10:00:00Z"})
        self.assertEqual(self.one("SELECT body FROM future_notes WHERE user_id = ? AND "
                                  "symbol IS NULL", (dana,)),
                         {"body": "For the house; not before 2030"})
        self.assertEqual(set(future_notes.all_notes(c, dana)), {"VTI", None})
        mine = zipfile.ZipFile(io.BytesIO(export.export_zip(c, dana)))
        self.assertIn("Twenty years", mine.read("notes_to_future_you.csv").decode())
        record = zipfile.ZipFile(io.BytesIO(export.client_record_zip(c, carol, dana)))
        for name in record.namelist():
            self.assertNotIn("Twenty years", record.read(name).decode(), name)
        future_notes.delete(c, carol, "VTI")                 # not the advisor's to delete
        self.assertIsNotNone(future_notes.get(c, dana, "VTI"))
        self.assertFalse(future_notes.save(c, dana, "VTI", "  "))   # empty: deleted
        future_notes.delete(c, dana)
        self.assertEqual(self.seen("SELECT * FROM future_notes WHERE user_id = ?", (dana,)), [])

    def test_checkin_reminders_opt_in_confirmed_once_a_month(self):
        c = self.conn
        yes = self.user("yes.ci")
        off = self.user("off.ci")
        for uid, name, on in ((yes, "yes.ci", True), (off, "off.ci", False)):
            c.execute("UPDATE users SET email = ?, email_verified_at = ? WHERE id = ?",
                      (f"{name}@example.com", "2026-09-01T10:00:00Z", uid))
            c.commit()
            prefs.save(c, uid, {checkin.PREF_SINCE: "2026-08", checkin.PREF_EMAIL: on})
        carol = self.user("carol.ci", advisor=True)
        client = auth.create_client(c, carol, "client.ci@example.com", name="Cli")
        prefs.save(c, client, {checkin.PREF_SINCE: "2026-08", checkin.PREF_EMAIL: True})
        self.assertEqual([r["id"] for r in checkin_email.recipients(c)], [yes])
        day = date(2026, 10, 5)
        sent = []
        dry = checkin_email.run(c, "https://app.example/", day, dry_run=True,
                                send=lambda *a: sent.append(a) or True)
        self.assertEqual((dry["would_send"], sent), (1, []))
        done = checkin_email.run(c, "https://app.example/", day,
                                 send=lambda *a: sent.append(a) or True)
        self.assertEqual((done["sent"], len(sent)), (1, 1))
        self.assertEqual(json.loads(self.one("SELECT data FROM user_prefs WHERE user_id = ?",
                                             (yes,))["data"])[checkin.PREF_SENT], "2026-10")
        again = checkin_email.run(c, "https://app.example/", day, send=lambda *a: True)
        self.assertEqual(again["sent"], 0)


# --------------------------------------------------------------------------- #
# the Monthly Walk's kept verdicts and the feature counts (totals only)
# --------------------------------------------------------------------------- #
@unittest.skipUnless(PG, SKIP)
class WalkTests(_PG):
    TAG = "walk"

    def test_kept_walks_and_the_totals(self):
        c = self.conn
        first = date(2026, 10, 5)
        for i in range(22):
            uid = self.user(f"walker{i}.wk")
            p = {checkin.PREF_SINCE: "2026-09"}
            days = [first] + ([first + timedelta(days=30)] if i % 2 else [])
            for d in days:
                for k in checkin.REQUIRED:
                    checkin.tick(p, k, d)
                self.assertTrue(checkin.finish(p, d, {"kind": "next", "class": "Bonds",
                                                      "how": "most", "amount": 500.0}))
            if i == 0:
                p[feature_counts.PREF_OFF] = True        # left out of every count
            prefs.save(c, uid, p)
        other = self.user("other.wk")
        prefs.save(c, other, {"hide_amounts": True})
        # what another connection sees: the verdict's kind only, no figure
        kept = json.loads(self.one("SELECT p.data FROM user_prefs p JOIN users u ON u.id = "
                                   "p.user_id WHERE u.username = ?",
                                   ("walker21.wk",))["data"])[checkin.PREF_VERDICTS]
        self.assertEqual(kept, {"2026-10": {"kind": "next", "class": "Bonds", "how": "most",
                                            "on": "2026-10-05"},
                                "2026-11": {"kind": "next", "class": "Bonds", "how": "most",
                                            "on": "2026-11-04"}})
        self.assertEqual(feature_counts.walks(c, date(2026, 12, 31)),
                         {"first_walks": 21, "window_closed": 21, "second_walks": 11})
        self.assertEqual(feature_counts.walks(c, date(2026, 10, 6)),     # windows still open
                         {"first_walks": 21, "window_closed": 0, "second_walks": None})
        # under 20 after more leave themselves out: nothing at all
        for i in range(1, 3):
            uid = self.one("SELECT id FROM users WHERE username = ?", (f"walker{i}.wk",))["id"]
            p = prefs.load(c, uid)
            p[feature_counts.PREF_OFF] = True
            prefs.save(c, uid, p)
        self.assertIsNone(feature_counts.walks(c, date(2026, 12, 31)))


# --------------------------------------------------------------------------- #
# an investor's own data: holdings, activity, plans, settings, prices
# --------------------------------------------------------------------------- #
def _positions_file(name):
    with open(os.path.join(BROKERS, name), "rb") as fh:
        rows = csv_import.read_rows(fh.read())
    hi, _ = csv_import.find_header(rows)
    mapping = csv_import.auto_mapping(rows[hi])
    found = csv_import.parse(rows, mapping, today=TODAY)
    return rows[hi], mapping, csv_import.to_snapshot(found)


def _activity_file(name, **kw):
    with open(os.path.join(BROKERS, name), "rb") as fh:
        rows = csv_import.read_rows(fh.read())
    hi = txn_import.find_header(rows)
    mapping = txn_import.auto_mapping(rows[hi])
    return rows[hi], mapping, txn_import.parse(rows, mapping, header_i=hi, **kw)


class HoldingsTests(_PG):
    TAG = "holdings"

    def test_import_activity_remove_and_delete(self):
        c = self.conn
        uid = self.user("hank")
        sample_data.load(c, uid)
        header, mapping, (meta, rows, totals) = _positions_file("fidelity_positions.csv")
        src = "upload: Portfolio_Positions.csv"
        p = portfolio.prepare_save(c, uid, meta, rows, totals, src)
        self.assertEqual(p["replaces"], "example")
        portfolio.save_prepared(c, uid, p, src)
        csv_import.remember(c, header, mapping)
        self.assertEqual(csv_import.remembered(c, header), mapping)
        saved = self.seen("SELECT account, symbol, market_value FROM positions WHERE user_id = ? "
                          "ORDER BY account, symbol", (uid,))
        self.assertEqual({r["account"] for r in saved}, {"Individual ...678", "ROTH IRA ...321"})
        self.assertEqual(self.seen("SELECT * FROM snapshots WHERE user_id = ? AND source_file = ?",
                                   (uid, portfolio.SAMPLE_SOURCE)), [])
        # the same file again: nothing new to record
        again = portfolio.prepare_save(c, uid, meta, rows, totals, src)
        self.assertEqual(again["txns"], [])

        a_header, a_mapping, found = _activity_file("fidelity_activity.csv")
        first = txn_import.save(c, uid, found["rows"], "upload: History.csv")
        self.assertEqual(first["added"], len(found["rows"]))
        self.assertEqual(txn_import.save(c, uid, found["rows"], "upload: History.csv")["added"],
                         0)
        self.assertEqual(len(self.seen("SELECT id FROM transactions WHERE user_id = ? AND "
                                       "origin = 'imported'", (uid,))), len(found["rows"]))
        txn_import.refresh_gains(c, uid)
        c.commit()
        self.assertEqual(set(txn_import.covered(c, uid)), {r["account"] for r in found["rows"]})

        snap = portfolio.remove_account(c, uid, "ROTH IRA ...321")
        self.assertEqual(snap, max(TODAY.isoformat(), meta["snapshot_date"]))
        self.assertEqual({r["account"] for r in portfolio.current_holdings(c, uid)["rows"]},
                         {"Individual ...678"})
        accounts.set_label(c, uid, "Individual ...678", "Everyday")
        self.assertEqual(self.seen("SELECT nickname FROM account_labels WHERE user_id = ?",
                                   (uid,)), [{"nickname": "Everyday"}])

        portfolio.delete_holdings(c, uid)
        for table in portfolio.HOLDINGS_TABLES:
            self.assertEqual(self.seen(f"SELECT * FROM {table} WHERE user_id = ?", (uid,)), [],
                             table)

    def test_full_account_numbers_are_cut_wherever_they_come_from(self):
        c = self.conn
        uid = self.user("nora")
        meta = {"snapshot_date": "2026-09-01", "as_of_text": None}
        portfolio.write_snapshot(c, uid, meta, [{
            "snapshot_date": "2026-09-01", "account": "Brokerage 12345678", "symbol": "VTI",
            "quantity": 1.0, "cost_basis": 100.0, "market_value": 300.0}], {}, "upload: x.csv")
        self.assertEqual(self.seen("SELECT account FROM positions WHERE user_id = ?", (uid,)),
                         [{"account": "Brokerage ...678"}])
        # a money value past REAL's 7 digits keeps its cents (DOUBLE PRECISION)
        c.execute("UPDATE positions SET market_value = 12345678.91 WHERE user_id = ?", (uid,))
        c.commit()
        self.assertEqual(self.one("SELECT market_value FROM positions WHERE user_id = ?",
                                  (uid,))["market_value"], 12345678.91)

    def test_watchlist_plan_profile_settings_and_value_log(self):
        c = self.conn
        uid = self.user("wes")
        self.assertEqual(watchlist.add(c, uid, " vti "), "VTI")
        watchlist.add(c, uid, "VTI")   # again: no error, no second row
        watchlist.add(c, uid, "AAPL")
        watchlist.remove(c, uid, "AAPL")
        self.assertEqual(self.seen("SELECT ticker FROM watchlist WHERE user_id = ?", (uid,)),
                         [{"ticker": "VTI"}])
        self.assertIn("VTI", watchlist.all_sync_tickers(c))

        plan = plans.save_plan(c, uid, {"goal_type": "Retirement", "target_amount": 500000.0,
                                        "target_date": "2050-01-01", "monthly_contribution": 600,
                                        "target_alloc": {"Stocks": 70, "Bonds": 30}}, set_by=uid)
        self.assertEqual(plan["target_alloc"], {"Stocks": 70.0, "Bonds": 30.0})
        plans.save_plan(c, uid, {"notes": "Revisit in spring"}, set_by=uid)
        self.assertEqual(self.one("SELECT notes, target_amount FROM plans WHERE user_id = ?",
                                  (uid,)), {"notes": "Revisit in spring",
                                            "target_amount": 500000.0})
        plans.add_contribution(c, uid, TODAY.isoformat(), 250, "Paycheck")
        plans.add_contribution(c, uid, TODAY.isoformat(), -50)
        moves = plans.list_contributions(c, uid)
        self.assertEqual(plans.money_added(c, uid, TODAY.isoformat(), TODAY.isoformat()), 200.0)
        plans.delete_contribution(c, uid, moves[0]["id"])
        self.assertEqual(len(self.seen("SELECT id FROM contributions WHERE user_id = ?",
                                       (uid,))), 1)

        advisor.save_profile(c, uid, {"goal": "Retirement", "time_horizon_years": 25,
                                      "risk_tolerance": "Moderate"})
        advisor.save_profile(c, uid, {"experience": "Some"})
        advisor.save_memory(c, uid, "prefers short answers")
        profile, memory = advisor.get_profile_and_memory(c, uid)
        self.assertEqual((profile["goal"], profile["experience"], memory),
                         ("Retirement", "Some", "prefers short answers"))
        self.assertEqual(self.one("SELECT time_horizon_years FROM investor_profiles WHERE "
                                  "user_id = ?", (uid,)), {"time_horizon_years": 25})

        prefs.save(c, uid, {"show_everything": True, "hide_amounts": False})
        prefs.save(c, uid, {"show_everything": False})
        self.assertEqual(prefs.load_many(c, [uid])[uid], {"show_everything": False})

        self.assertTrue(perf.log_open(self.dsn, uid, {"portfolio_value": 1234.5}, min_gap_sec=0))
        self.assertFalse(perf.log_open(self.dsn, uid, {"portfolio_value": 1.0}))   # too soon
        self.assertEqual(perf.last_open(self.dsn, uid)["portfolio_value"], 1234.5)

    def test_ai_allowances_and_error_events(self):
        c = self.conn
        uid = auth.sign_up(c, "ada@example.com", PW, seconds_open=10, **AGREE)["user_id"]
        self.assertFalse(ai_usage.status(c, uid, "chat")["ok"])   # email not confirmed yet
        c.execute("UPDATE users SET email_verified_at = '2026-10-01 10:00:00' WHERE id = ?",
                  (uid,))
        c.commit()
        ai_usage.record(c, uid, "chat")
        ai_usage.record(c, uid, "chat")
        st = ai_usage.status(c, uid, "chat")
        self.assertEqual((st["used"], st["left"]), (2, ai_usage.LIMITS["chat"] - 2))
        self.assertEqual(self.one("SELECT used FROM ai_usage WHERE user_id = ?", (uid,)),
                         {"used": 2})
        ai_usage.set_unlimited(c, uid, True)
        self.assertIsNone(ai_usage.status(c, uid, "chat")["limit"])

        error_alerts.clear(c)
        box = _mail(self)
        f = {"error_type": "KeyError", "place": "views/plan.py", "line": 12,
             "kind": "KeyError in views/plan.py"}
        self.assertTrue(error_alerts.notify(c, f, now=NOW))
        self.assertFalse(error_alerts.notify(c, f, now=NOW + timedelta(minutes=5)))  # an hour
        self.assertEqual(len(box.sent), 1)
        (row,) = error_alerts.recent(c)
        self.assertEqual((row["times"], row["line"]), (2, 12))
        self.assertTrue(error_alerts.record(c, error_type="KeyError", place="views/plan.py",
                                            now=NOW + timedelta(hours=2)))
        self.assertEqual(error_alerts.clear(c), 1)
        self.assertEqual(self.seen("SELECT * FROM error_events"), [])

    def test_income_while_held_and_total_return(self):
        c = self.conn
        uid = self.user("ivan")
        held = (TODAY - timedelta(days=300)).isoformat()
        for day, rows in ((held, [("VTI", 10.0, 2500.0, 3000.0), ("SCHD", 20.0, 500.0, 560.0)]),
                          (TODAY.isoformat(), [("VTI", 10.0, 2500.0, 3100.0),
                                               ("SCHD", 20.0, 500.0, 580.0)])):
            portfolio.write_snapshot(c, uid, {"snapshot_date": day, "as_of_text": None}, [
                {"snapshot_date": day, "account": "Brokerage", "symbol": s, "quantity": q,
                 "cost_basis": cost, "market_value": mv} for s, q, cost, mv in rows], {},
                "upload: test.csv")
        for m in (2, 5, 8):
            c.execute("INSERT INTO daily_bars (ticker, date, close, dividend) VALUES (?, ?, ?, ?)",
                      ("VTI", (TODAY - timedelta(days=30 * m)).isoformat(), 300.0, 0.9))
        c.execute("INSERT INTO transactions (user_id, account, trade_date, action, symbol, "
                  "amount, origin) VALUES (?, 'Brokerage', ?, 'DIV', 'SCHD', 6.5, 'imported')",
                  (uid, (TODAY - timedelta(days=40)).isoformat()))
        c.commit()
        got = income.received_while_held(c, uid, ["VTI", "SCHD"], TODAY)
        self.assertEqual(got["SCHD"], {"amount": 6.5, "source": "brokerage",
                                       "since": (TODAY - timedelta(days=40)).isoformat()})
        self.assertEqual((got["VTI"]["amount"], got["VTI"]["source"]), (27.0, "estimated"))
        self.assertEqual(income.total_return(600.0, 2500.0, 27.0)["usd"], 627.0)
        self.assertIsNotNone(income.received(c, uid, TODAY))
        self.assertEqual(income.has_history(c, ["VTI", "SCHD"]), {"VTI"})

    def test_fund_top_holdings_and_the_nightly_jobs_writes(self):
        c = self.conn
        fund_holdings.store(c, "VTI", [{"symbol": "AAPL", "name": "Apple", "weight": 0.064},
                                       {"symbol": "MSFT", "name": "Microsoft", "weight": 0.06}],
                            now=NOW)
        fund_holdings.store(c, "BND", [], now=NOW)
        c.commit()
        fund_holdings.store(c, "VTI", [{"symbol": "NVDA", "name": "NVIDIA", "weight": 0.07}],
                            now=NOW)
        c.commit()
        tops = fund_holdings.cached(c, ["VTI", "BND", "VXUS"])
        self.assertEqual(tops["VTI"]["holdings"], [{"symbol": "NVDA", "name": "NVIDIA",
                                                    "weight": 0.07}])
        self.assertEqual(tops["BND"]["holdings"], [])
        self.assertNotIn("VXUS", tops)
        self.assertEqual(len(self.seen("SELECT slot FROM fund_top_holdings WHERE fund = 'VTI'")),
                         2)

        # Yahoo gives a crypto pair's volume in dollars: past INTEGER's limit
        big = 35_000_000_000
        with c:
            sync_history.upsert_bars(c, "BTC-USD", [
                {"date": TODAY.isoformat(), "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0,
                 "adj_close": 1.0, "volume": big, "dividend": 0.0}])
            sync_history.upsert_intraday(c, "BTC-USD", "60m", [
                {"ts": f"{TODAY.isoformat()}T14:00:00Z", "open": 1.0, "high": 1.0, "low": 1.0,
                 "close": 1.0, "volume": big}])
            sync_history.upsert_info(c, "BTC-USD", {"name": "Bitcoin USD", "avg_volume": big,
                                                    "avg_volume_10d": big,
                                                    "quote_type": "CRYPTOCURRENCY"})
        self.assertEqual(self.one("SELECT volume FROM daily_bars WHERE ticker = 'BTC-USD'"),
                         {"volume": big})
        self.assertEqual(self.one("SELECT avg_volume FROM security_info WHERE ticker = "
                                  "'BTC-USD'"), {"avg_volume": big})
        c.execute("INSERT INTO price_history (ticker, price, fetched_at, ok) VALUES "
                  "('VTI', 300.0, '2026-01-02T15:00:00Z', 1), ('VTI', 301.0, "
                  "'2026-01-02T15:01:00Z', 1)")
        c.commit()
        self.assertEqual(live_prices.trim_history(c), 1)   # one quote a day kept, after a week
        self.assertEqual(len(self.seen("SELECT id FROM price_history WHERE ticker = 'VTI'")), 1)


    def test_the_15_minute_price_job_and_news(self):
        import news
        import update_prices
        c = self.conn
        uid = self.user("pete")
        sample_data.load(c, uid)
        quote = {"c": 123.45, "pc": 120.0, "d": 3.45, "dp": 2.875, "o": 121.0, "h": 124.0,
                 "l": 119.5, "t": int(NOW.timestamp())}
        with unittest.mock.patch.object(update_prices, "fetch_quote",
                                        lambda symbol, key, timeout=10.0: (dict(quote), "")):
            done = update_prices.refresh_all_users(c, "key", delay=0)
        self.assertGreater(done["ok"], 0)
        self.assertEqual(done["failed"], 0)
        priced = self.seen("SELECT live_price, live_market_value FROM positions WHERE "
                           "user_id = ? AND live_price IS NOT NULL", (uid,))
        self.assertTrue(priced)
        self.assertEqual({r["live_price"] for r in priced}, {123.45})
        self.assertTrue(self.seen("SELECT 1 FROM price_history WHERE ok = 1 AND price = 123.45"))

        articles = [{"id": 7154455 + i, "headline": f"Headline {i}", "summary": "s",
                     "source": "Wire", "url": "https://example.com/a", "datetime":
                     int(NOW.timestamp()) - i * 3600} for i in range(3)]
        self.assertEqual(news.upsert_news(c, "VTI", articles), 3)
        self.assertEqual(news.upsert_news(c, "VTI", articles), 0)   # the same ones again
        self.assertFalse(news.needs_refresh(c, "VTI"))
        self.assertEqual([a["headline"] for a in news.latest_news(c, "VTI", limit=2)],
                         ["Headline 0", "Headline 1"])


class MoneyOutTests(_PG):
    """Money going out of a plan (plans.py, ROADMAP 12): every write path
    commits, the advisor writes for a client, and the projection reads it."""
    TAG = "moneyout"

    def test_add_change_remove_and_who_may(self):
        c = self.conn
        me = self.user("mo.owner")
        carol = self.user("mo.carol", advisor=True)
        dana = auth.create_client(c, carol, "mo.dana@example.com", name="Dana")
        stranger = self.user("mo.stranger")
        car = plans.add_money_out(c, me, "expense", {"label": "A car", "amount": 20000,
                                                     "start_date": "2027-06-01"}, by=me)
        plans.add_money_out(c, me, "expense", {"label": "Tuition", "amount": 15000, "times": 4,
                                               "start_date": "2030-09-01"}, by=me)
        w = plans.add_money_out(c, me, "withdrawal", {"amount": 2000, "start_date": "2035-01-01",
                                                      "inflation_pct": 2.5}, by=me)
        rows = self.seen("SELECT label, amount, times, inflation_pct, set_by FROM money_out "
                         "WHERE user_id = ? ORDER BY start_date", (me,))
        self.assertEqual([(r["label"], r["amount"], r["times"]) for r in rows],
                         [("A car", 20000.0, 1), ("Tuition", 15000.0, 4),
                          ("Regular withdrawal", 2000.0, 1)])
        self.assertEqual(rows[2]["inflation_pct"], 2.5)
        # one regular withdrawal: setting it again changes it
        self.assertEqual(plans.add_money_out(c, me, "withdrawal", {
            "amount": 2500, "start_date": "2036-01-01"}, by=me), w)
        plans.update_money_out(c, me, car, {"amount": 18000}, by=me)
        self.assertEqual(self.one("SELECT amount, updated_at FROM money_out WHERE id = ?",
                                  (car,))["amount"], 18000.0)
        self.assertEqual(self.one("SELECT amount, inflation_pct FROM money_out WHERE id = ?",
                                  (w,)), {"amount": 2500.0, "inflation_pct": 2.5})   # left out: kept
        self.assertTrue(plans.delete_money_out(c, me, car, by=me))
        self.assertEqual(self.seen("SELECT id FROM money_out WHERE id = ?", (car,)), [])
        with self.assertRaises(PermissionError):
            plans.add_money_out(c, me, "expense", {"label": "x", "amount": 1,
                                                   "start_date": "2028-01-01"}, by=stranger)
        # the advisor, for her client, recorded as who saved it
        plans.add_money_out(c, dana, "expense", {"label": "Roof", "amount": 9000,
                                                 "start_date": "2028-04-01"}, by=carol)
        self.assertEqual(self.one("SELECT set_by FROM money_out WHERE user_id = ?", (dana,)),
                         {"set_by": carol})
        with self.assertRaises(PermissionError):
            plans.list_money_out(c, dana, viewer=stranger)
        with self.assertRaises(PermissionError):
            plans.add_money_out(c, dana, "expense", {"label": "x", "amount": 1,
                                                     "start_date": "2028-01-01"}, by=dana)
        # the projection reads it back and takes it out
        items = plans.list_money_out(c, me)
        plan = {"target_amount": 500000, "target_date": "2046-10-05", "monthly_contribution": 800}
        today = date(2026, 10, 5)
        self.assertLess(plans.progress(plan, 50000, today=today, items=items)["projected"],
                        plans.progress(plan, 50000, today=today)["projected"])
        self.assertIsNotNone(plans.lasting(50000, 800, 6, items, today=today, age=40))
        # Export everything has it
        self.assertEqual([r["label"] for r in export.collect(c, me)["money_going_out"]],
                         ["Tuition", "Regular withdrawal"])


class YearAndMapTests(_PG):
    """Year in review's reads (recap.py) and the account map's writes
    (account_map.py) - ROADMAP 9 and 10."""
    TAG = "yearmap"

    def test_year_in_review_with_and_without_imported_history(self):
        import recap
        from tests.test_year_map import TODAY, seed
        c = self.conn
        ann, bea = self.user("ann.yr"), self.user("bea.yr")
        seed(c, ann)
        seed(c, bea, imported=True)
        r = recap.build(c, ann, 2026, TODAY, current_value=4900.0, basis=perf._basis(c, ann),
                        prefs={"gear_dates": {"map": {"on": "2026-02-01"}}})
        self.assertEqual((r["added"], r["value_start"], r["growth"]), (1000.0, 4100.0, -200.0))
        self.assertEqual((r["income"]["source"], r["income"]["total"]), ("estimated", 10.0))
        self.assertEqual((r["worst"]["month"], len(r["months"])), ("2026-03", 10))
        self.assertEqual((r["gear"], r["months_invested"]), (["map"], 10))
        self.assertEqual(r["notes"], 0)
        r = recap.build(c, bea, 2026, TODAY, current_value=5000.0, basis=perf._basis(c, bea))
        self.assertEqual((r["added"], r["income"]["source"], r["income"]["total"]),
                         (2000.0, "brokerage", 5.0))
        self.assertFalse(recap.has_money(recap.share_text(r)))
        self.assertTrue(recap.share_pdf(r).startswith(b"%PDF"))
        # notes to future you written that year (the table found in information_schema)
        import future_notes
        future_notes.save(c, ann, None, "Hold on", now="2026-04-01T10:00:00Z")
        self.assertEqual(recap.notes_written(c, ann, "2026-01-01", "2026-10-05"), 1)
        with unittest.mock.patch.object(recap, "NOTES_TABLE", "no_such_table"):
            self.assertIsNone(recap.notes_written(c, ann, "2026-01-01", "2026-10-05"))

    def test_account_map_save_export_and_delete(self):
        import account_map
        from tests.test_year_map import seed
        c = self.conn
        uid = auth.sign_up(c, "map@example.com", PW, seconds_open=10, **AGREE)["user_id"]
        seed(c, uid)
        account_map.save_account(c, uid, "Roth IRA ...641", {
            "kind": "Roth IRA", "contact": "Help line", "phone": "800-555-0101",
            "beneficiary": "Yes", "paperwork": "Desk", "notes": "Since 2019"})
        account_map.save_account(c, uid, "Roth IRA ...641", {"kind": "Roth IRA",
                                                             "beneficiary": "Not sure"})
        oid = account_map.save_other(c, uid, {"label": "Credit union", "digits": "12345"})
        account_map.save_other(c, uid, {"label": "Credit union savings", "digits": "678"}, oid)
        account_map.save_family(c, uid, "Spouse knows the password manager")
        rows = self.seen("SELECT entry, account, label, last_digits, kind, beneficiary, notes "
                         "FROM account_map WHERE user_id = ? ORDER BY entry", (uid,))
        self.assertEqual(rows, [
            {"entry": "account", "account": "Roth IRA ...641", "label": None,
             "last_digits": None, "kind": "Roth IRA", "beneficiary": "Not sure", "notes": None},
            {"entry": "family", "account": None, "label": None, "last_digits": None,
             "kind": None, "beneficiary": None, "notes": "Spouse knows the password manager"},
            {"entry": "other", "account": None, "label": "Credit union savings",
             "last_digits": "678", "kind": None, "beneficiary": None, "notes": None}])
        m = account_map.load(c, uid)
        self.assertEqual([a["account"] for a in m["accounts"]],
                         ["Individual ...222", "Roth IRA ...641"])
        self.assertTrue(account_map.render_pdf(m, name="Map").startswith(b"%PDF"))
        z = zipfile.ZipFile(io.BytesIO(export.export_zip(c, uid)))
        self.assertIn("Spouse knows", z.read("account_map.csv").decode())
        account_map.delete_entry(c, uid, oid)
        self.assertEqual(len(self.seen("SELECT id FROM account_map WHERE user_id = ?", (uid,))),
                         2)
        self.assertTrue(admin.delete_own(c, uid, PW)["ok"])
        self.assertEqual(self.seen("SELECT id FROM account_map WHERE user_id = ?", (uid,)), [])


class DeleteAccountTests(_PG):
    TAG = "delete"

    def test_delete_own_and_admin_delete_clear_every_table(self):
        c = self.conn
        uid = auth.sign_up(c, "del@example.com", PW, seconds_open=10, **AGREE)["user_id"]
        sample_data.load(c, uid)
        watchlist.add(c, uid, "VTI")
        prefs.save(c, uid, {"a": 1})
        plans.save_plan(c, uid, {"goal_type": "Home"}, set_by=uid)
        plans.add_money_out(c, uid, "expense", {"label": "A car", "amount": 20000,
                                                "start_date": "2027-06-01"}, by=uid)
        future_notes.save(c, uid, None, "For the house")
        auth.create_session(c, uid)
        self.assertFalse(admin.delete_own(c, uid, "wrong-password")["ok"])
        self.assertTrue(admin.delete_own(c, uid, PW)["ok"])
        for table, cols in admin.ACCOUNT_TABLES.items():
            where = " OR ".join(f"{col} = ?" for col in cols)
            self.assertEqual(self.seen(f"SELECT * FROM {table} WHERE {where}",
                                       (uid,) * len(cols)), [], table)
        self.assertEqual(self.seen("SELECT * FROM users WHERE id = ?", (uid,)), [])

        boss = self.user("boss")
        carol = self.user("carol.del", advisor=True)
        dana = auth.create_client(c, carol, "dana.del@example.com", name="Dana")
        plans.save_plan(c, dana, {"goal_type": "Home"}, set_by=carol)
        plans.add_money_out(c, dana, "withdrawal", {"amount": 2000,
                                                    "start_date": "2040-01-01"}, by=carol)
        res = admin.delete_account(c, carol, by=boss)
        self.assertEqual((res["ok"], res["orphaned_clients"]), (True, 1))
        self.assertEqual(self.one("SELECT set_by FROM plans WHERE user_id = ?", (dana,)),
                         {"set_by": None})
        self.assertEqual(self.one("SELECT set_by FROM money_out WHERE user_id = ?", (dana,)),
                         {"set_by": None})


# --------------------------------------------------------------------------- #
# the app itself (AppTest): writes made from a page, and every page drawn
# --------------------------------------------------------------------------- #
KINDS = ("markdown", "caption", "info", "success", "warning", "error")


def _offline(*a, **k):
    raise RuntimeError("offline in tests")


def app(test, dsn, uid, name, page, **state):
    """dashboard.py on `dsn`, signed in as `uid`, offline."""
    import yfinance
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
    for k, v in {"user_id": uid, "username": name, "page": page, "auto_backfilled": True,
                 "income_synced": True, **state}.items():
        at.session_state[k] = v
    env = {k: v for k, v in os.environ.items()
           if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "RESEND_API_KEY")}
    env.update(PORTFOLIO_DB=dsn, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused")
    for p in (unittest.mock.patch.dict(os.environ, env, clear=True),
              unittest.mock.patch.object(yfinance, "Ticker", _offline),
              unittest.mock.patch("socket.socket.connect", _offline)):
        p.start()
        test.addCleanup(p.stop)
    return at


def problems(at) -> list[str]:
    """What went wrong on a drawn page: exceptions, and the app's own
    "Something went wrong" message (friendly_errors.py)."""
    out = [f"exception: {e.message[:300]}" for e in at.exception]
    out += [f"error: {e.value[:300]}" for e in at.error if "went wrong" in (e.value or "")]
    return out


def seed_for_pages(conn):
    """An investor (alice: the example portfolio, activity, a watchlist,
    prices and dividends), an advisor with two-step (carol) and her client
    (dave). Returns (alice, carol, dave, carol's two_step_ok)."""
    alice = auth.create_user(conn, "alice", PW)
    sample_data.load(conn, alice)
    carol = auth.create_user(conn, "carol", PW)
    auth.set_advisor(conn, "carol", True)
    secret = two_step.new_secret()
    two_step.enable(conn, carol, secret, two_step.totp(secret))
    carol_ok = f"{carol}:{two_step.status(conn, carol)['stamp']}"
    dave = auth.create_client(conn, carol, "dave@example.com", name="Dave")
    sample_data.load(conn, dave)
    advising.add_note(conn, dave, carol, "Review", "First review", TODAY.isoformat())
    proposals.share(conn, carol, proposals.save(conn, carol, dave, title="Mix",
                                                mix={"Stocks": 60, "Bonds": 40}))
    for uid in (alice, dave):
        for i, (act, sym, qty, price, amt, gain, origin) in enumerate([
                ("BUY", "VTI", 5, 300, -1500, None, None),
                ("SELL", "AAPL", 3, 230, 690, 215.0, None),
                ("DEPOSIT", None, None, None, 2000, None, "imported"),
                ("DIV", "SCHD", None, None, 25.5, None, "imported"),
                ("WITHDRAWAL", None, None, None, -300, None, "imported")]):
            conn.execute("INSERT INTO transactions (user_id, account, trade_date, action, symbol, "
                         "quantity, price, amount, realized_gain, origin) VALUES "
                         "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (uid, "Brokerage", (TODAY - timedelta(days=10 * i)).isoformat(), act,
                          sym, qty, price, amt, gain, origin))
        for t in ("NVDA", "MSFT", "TSLA"):
            conn.execute("INSERT INTO watchlist (user_id, ticker) VALUES (?, ?)", (uid, t))
    for n, t in enumerate(("NVDA", "MSFT", "TSLA")):
        conn.execute("INSERT INTO price_history (ticker, price, prev_close, change, pct_change, "
                     "ok) VALUES (?, ?, ?, ?, ?, 1)", (t, 100 + n, 100, n - 1, (n - 1) * 1.1))
    for t in ("VTI", "VXUS", "BND", "AAPL", "VOO", "SCHD"):
        for m in (2, 5, 8, 11):
            conn.execute("INSERT INTO daily_bars (ticker, date, close, dividend) VALUES "
                         "(?, ?, ?, ?)", (t, (TODAY - timedelta(days=30 * m)).isoformat(), 100.0,
                                          0.5 if t != "AAPL" else 0.25))
    conn.commit()
    return alice, carol, dave, carol_ok


ALICE_PAGES = ("Get started", "Dashboard", "Plan", "Watchlist", "Activity", "Income",
               "AI Assistant", "Account", "About")
CAROL_PAGES = ("Clients", "Dashboard", "Plan", "Advisor notes", "Watchlist", "Activity",
               "Income", "AI Assistant", "Get started")


def sweep(test, dsn, people):
    """Draw every page: alice's 9 pages calm and with Show everything, and
    carol's 9 in her client dave's account - 27 in all. Each must draw
    without an error and hand every connection back to the pool."""
    alice, carol, dave, carol_ok = people
    runs = [(alice, "alice", page, show, {}) for page in ALICE_PAGES for show in (False, True)]
    runs += [(carol, "carol", page, None, {"active_user_id": dave, "two_step_ok": carol_ok})
             for page in CAROL_PAGES]
    found = []
    for uid, name, page, show, state in runs:
        if show is not None:
            c = portfolio.connect(dsn)
            try:
                p = prefs.load(c, uid)
                p["show_everything"] = show
                prefs.save(c, uid, p)
            finally:
                c.close()
        at = app(test, dsn, uid, name, page, **state)
        at.run()
        where = f"{name} {page}" + ("" if show is None else f" (show everything: {show})")
        found += [f"{where}: {p}" for p in problems(at)]
        if not at.title:
            found.append(f"{where}: nothing drawn")
        if in_use(dsn):
            found.append(f"{where}: {in_use(dsn)} connection(s) not handed back to the pool")
    test.assertTrue(_pools(dsn))   # (the check above looked at the app's own pool)
    test.assertEqual(len(runs), 27)
    test.assertEqual(found, [])


def _upload(name, data):
    return types.SimpleNamespace(name=name, getbuffer=lambda: data, getvalue=lambda: data,
                                 size=len(data), type="text/csv")


class _KeepModules(unittest.TestCase):
    """The app's first run can reload the repo's modules (codefresh.py): put
    back the ones other test files imported afterwards, so their mocks still
    reach (as the other AppTest classes do)."""

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)


@unittest.skipUnless(PG, SKIP)
class AppTests(_KeepModules):
    """Writes made from the pages, and the 27-page sweep, on one schema."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dsn = fresh_db("app")
        c = portfolio.connect(cls.dsn)
        try:
            cls.people = seed_for_pages(c)
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        close_db(cls.dsn)
        super().tearDownClass()

    def read(self, sql, params=()):
        c = portfolio.connect(self.dsn)
        try:
            return [dict(r) for r in c.execute(sql, params)]
        finally:
            c.close()

    def run_app(self, at):
        at.run()
        self.assertEqual(problems(at), [])
        self.assertEqual(in_use(self.dsn), 0, "a connection wasn't handed back to the pool")
        return at

    def test_page_sweep(self):
        sweep(self, self.dsn, self.people)

    def test_import_a_positions_file_then_an_activity_file(self):
        import streamlit
        c = portfolio.connect(self.dsn)
        try:
            ivy = auth.create_user(c, "ivy", PW)
        finally:
            c.close()
        files = {}
        real = streamlit.file_uploader

        def uploader(label, *a, key=None, **kw):
            if (key or "").startswith("csv_upload_"):   # csv_upload_<n>: new after a save
                return files.get("up")
            return real(label, *a, key=key, **kw)
        p = unittest.mock.patch.object(streamlit, "file_uploader", uploader)
        p.start()
        self.addCleanup(p.stop)
        for name, button in (("fidelity_positions.csv", "csv_save"),
                             ("fidelity_activity.csv", "txn_save")):
            with open(os.path.join(BROKERS, name), "rb") as fh:
                files["up"] = _upload(name, fh.read())
            at = self.run_app(app(self, self.dsn, ivy, "ivy", "Dashboard", open_dialog="import"))
            at.button(key=button).click()
            at.session_state["open_dialog"] = "import"
            self.run_app(at)
        files.clear()
        held = self.read("SELECT DISTINCT account FROM positions WHERE user_id = ?", (ivy,))
        self.assertEqual({r["account"] for r in held}, {"Individual ...678", "ROTH IRA ...321"})
        self.assertEqual(len(self.read("SELECT id FROM transactions WHERE user_id = ? AND "
                                       "origin = 'imported'", (ivy,))), 6)
        self.assertTrue(self.read("SELECT signature FROM csv_layouts"))   # layouts remembered
        # and the pages that show them
        for page in ("Dashboard", "Activity", "Income"):
            self.run_app(app(self, self.dsn, ivy, "ivy", page))

    def test_practice_money_step_completes(self):
        c = portfolio.connect(self.dsn)
        try:
            pia = auth.create_user(c, "pia", PW)   # past the first steps, a profile answered
            auth.record_agreement(c, pia, "October 1, 2026", via=auth.TERMS_VIA_SIGN_IN)
            prefs.save(c, pia, {"first_steps": {"done": True}})
            advisor.save_profile(c, pia, {"goal": "Build long-term wealth",
                                          "time_horizon_years": 10, "experience": "new",
                                          "risk_tolerance": "moderate"})
            start = TODAY - timedelta(days=6 * 365)
            bars = [(t, (start + timedelta(days=7 * w)).isoformat(), 100.0 + w * 0.1 + i)
                    for i, t in enumerate(learn.PRACTICE_TICKERS.values())
                    for w in range((TODAY - start).days // 7 + 1)]
            c.executemany("INSERT INTO daily_bars (ticker, date, close, adj_close) VALUES "
                          "(?, ?, ?, ?) ON CONFLICT (ticker, date) DO NOTHING",
                          [(t, d, p, p) for t, d, p in bars])
            c.commit()
        finally:
            c.close()
        at = self.run_app(app(self, self.dsn, pia, "pia", "Get started", gs_at="practice"))
        self.assertTrue(any("Worst drop" in h.proto.body for h in at.get("html")))
        at.button(key="gs_complete").click()
        self.run_app(at)
        c = portfolio.connect(self.dsn)
        try:
            self.assertIn("practice", prefs.load(c, pia).get("get_started_done") or [])
        finally:
            c.close()

    def test_agreeing_to_the_disclosures_on_a_page(self):
        c = portfolio.connect(self.dsn)
        try:
            uma = auth.create_user(c, "uma", PW)   # made by an admin: asked once, in the app
        finally:
            c.close()
        at = self.run_app(app(self, self.dsn, uma, "uma", "Dashboard"))
        at.checkbox(key="terms_adult").check()
        at.checkbox(key="terms_agree").check()
        self.run_app(at)
        at.button(key="terms_ok").click()
        self.run_app(at)
        (row,) = self.read("SELECT terms_version, terms_via FROM users WHERE id = ?", (uma,))
        self.assertEqual(row["terms_via"], auth.TERMS_VIA_SIGN_IN)
        self.assertTrue(row["terms_version"])

    def test_an_advisor_adds_and_invites_a_client(self):
        alice, carol, dave, carol_ok = self.people
        at = self.run_app(app(self, self.dsn, carol, "carol", "Clients", two_step_ok=carol_ok))
        at.text_input(key="new_client_name").input("Chen household")
        at.text_input(key="new_client_email").input("wei.chen@example.com")
        self.run_app(at)
        at.text_input(key="new_adv_name").input("Carol Ruiz")
        at.button(key="add_client").click()
        self.run_app(at)
        (row,) = self.read("SELECT u.id, ac.client_name FROM advisor_clients ac JOIN users u "
                           "ON u.id = ac.client_id WHERE ac.advisor_id = ? AND u.username = ?",
                           (carol, "wei.chen@example.com"))
        self.assertEqual(row["client_name"], "Chen household")
        self.assertTrue(self.read("SELECT 1 FROM invites WHERE user_id = ?", (row["id"],)))

    def test_ending_from_both_sides_and_the_preview_page(self):
        alice, carol, dave, carol_ok = self.people
        c = portfolio.connect(self.dsn)
        try:
            ann = auth.create_client(c, carol, "ann.pg@example.com", name="Ann")
            bo = auth.create_client(c, carol, "bo.pg@example.com", name="Bo")
            c.execute("UPDATE users SET last_login_at = ? WHERE id IN (?, ?)",
                      ("2026-09-01 10:00:00", ann, bo))
            pat = auth.create_user(c, "pat.pg@example.com", PW)
            auth.request_advisor(c, pat, "Pat Wealth", "CRD 1")
            c.commit()
        finally:
            c.close()
        _mail(self)
        at = self.run_app(app(self, self.dsn, carol, "carol", "Clients", two_step_ok=carol_ok))
        at.checkbox(key=f"end_ok_{ann}").check()
        at.button(key=f"end_go_card_{ann}").click()
        self.run_app(at)
        at = self.run_app(app(self, self.dsn, bo, "bo.pg@example.com", "Advisor notes"))
        at.checkbox(key="stop_sharing_ok").check()
        at.button(key="stop_sharing").click()
        self.run_app(at)
        rows = self.read("SELECT client_id, ended_by FROM former_clients WHERE advisor_id = ? "
                         "ORDER BY client_id", (carol,))
        self.assertEqual(rows, [{"client_id": ann, "ended_by": "advisor"},
                                {"client_id": bo, "ended_by": "client"}])
        self.assertEqual(self.read("SELECT * FROM advisor_clients WHERE client_id IN (?, ?)",
                                   (ann, bo)), [])
        before = self.read("SELECT COUNT(*) AS n FROM users")
        at = self.run_app(app(self, self.dsn, pat, "pat.pg@example.com", "Advisor preview"))
        self.assertTrue(any("Rivera household" in h.proto.body for h in at.get("html")))
        self.assertEqual(self.read("SELECT COUNT(*) AS n FROM users"), before)
        # Your clients with a former client draws too
        self.run_app(app(self, self.dsn, carol, "carol", "Clients", two_step_ok=carol_ok))


# --------------------------------------------------------------------------- #
# an older database, upgraded by today's code
# --------------------------------------------------------------------------- #
@unittest.skipUnless(PG, SKIP)
class UpgradeTests(_KeepModules):

    def test_a_database_from_sep_30_upgrades_and_every_page_draws(self):
        import psycopg
        dsn = fresh_db("upgrade")
        self.addCleanup(close_db, dsn)
        with open(OLD_SCHEMA, encoding="utf-8") as fh:
            old = fh.read()
        raw = psycopg.connect(dsn, autocommit=True)
        try:
            raw.execute(";\n".join(pgcompat._split_statements(old)))
            # the first Neon copy's money columns were REAL
            raw.execute("ALTER TABLE positions ALTER COLUMN market_value TYPE REAL")
            raw.execute("INSERT INTO users (username, password_hash, password_salt) "
                        "VALUES ('olive', 'x', 'y')")
            raw.execute("INSERT INTO positions (snapshot_date, account, symbol, quantity, "
                        "cost_basis, market_value, user_id) VALUES ('2026-09-29', "
                        "'Individual 12345678', 'VTI', 10, 2500, 3000, 1)")
            raw.execute("INSERT INTO snapshots (snapshot_date, source_file, user_id) VALUES "
                        "('2026-09-29', 'upload: old.csv', 1)")
            raw.execute("INSERT INTO transactions (account, trade_date, action, symbol) "
                        "VALUES ('Individual 12345678', '2026-09-28', 'BUY', 'VTI')")
            raw.execute("INSERT INTO daily_bars (ticker, date, close, volume) VALUES "
                        "('VTI', '2026-09-29', 300, 3000000)")
        finally:
            raw.close()

        conn = portfolio.connect(dsn)   # today's code: back-fill, new tables, clean-ups
        try:
            def cols(table):
                return {r["column_name"]: r["data_type"] for r in conn.execute(
                    "SELECT column_name, data_type FROM information_schema.columns WHERE "
                    "table_schema = current_schema() AND table_name = ?", (table,))}
            users = cols("users")
            for col in ("is_advisor", "email", "terms_version", "terms_via", "is_admin",
                        "display_name", "ai_unlimited", "last_login_at"):
                self.assertIn(col, users)
            self.assertIn("client_name", cols("advisor_clients"))
            self.assertTrue({"archived_at", "edited_at", "history", "is_message"}
                            <= set(cols("advisor_notes")))
            self.assertIn("two_step_until", cols("login_sessions"))
            self.assertIn("expense_ratio", cols("security_info"))
            self.assertTrue({"user_id", "origin", "row_key"} <= set(cols("transactions")))
            self.assertEqual(cols("positions")["market_value"], "double precision")
            self.assertEqual(cols("daily_bars")["volume"], "bigint")
            for table in ("fund_top_holdings", "proposals", "progress_reports", "two_step",
                          "error_events", "email_tokens", "advisor_requests", "csv_layouts",
                          "former_clients"):
                self.assertTrue(cols(table), table)
            self.assertEqual([r["account"] for r in conn.execute(
                "SELECT account FROM positions UNION ALL SELECT account FROM transactions")],
                ["Individual ...678", "Individual ...678"])
            self.assertEqual(conn.execute("SELECT market_value FROM positions").fetchone()[0],
                             3000.0)
            # a second process starting finds nothing left to do
            portfolio._SCHEMA_READY.discard(dsn)
            with unittest.mock.patch("sys.stderr", new_callable=io.StringIO) as err:
                portfolio._ensure_schema(conn)
            self.assertEqual(err.getvalue(), "")
            people = seed_for_pages(conn)
        finally:
            conn.close()
        sweep(self, dsn, people)


if __name__ == "__main__":
    unittest.main()
