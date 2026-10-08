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
import secrets
import sys
import types
import unittest
import unittest.mock
import zipfile
from datetime import date, datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import access_log  # noqa: E402
import accounts  # noqa: E402
import admin  # noqa: E402
import advising  # noqa: E402
import advisor  # noqa: E402
import ai_usage  # noqa: E402
import auth  # noqa: E402
import checkin  # noqa: E402
import checkin_email  # noqa: E402
import consent  # noqa: E402
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
import unsubscribe  # noqa: E402
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
AGREE = dict(agreed=True, adult=True, us_resident=True, terms_version="October 1, 2026")
SIGNUP = dict(AGREE, needs_code=False)   # (open sign-up: gate L0 on)
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
        made = auth.sign_up(c, "Sam@Example.com", PW, seconds_open=10, ip="203.0.113.5", **SIGNUP)
        self.assertTrue(made["ok"], made)
        uid = made["user_id"]
        row = self.one("SELECT username, email, terms_version, terms_via FROM users WHERE id = ?",
                       (uid,))
        self.assertEqual(row, {"username": "sam@example.com", "email": "sam@example.com",
                               "terms_version": "October 1, 2026", "terms_via": None})
        self.assertEqual(self.one("SELECT COUNT(*) AS n FROM signups WHERE ok = 1")["n"], 1)
        again = auth.sign_up(c, "sam@example.com", PW, seconds_open=10, ip="203.0.113.5", **SIGNUP)
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

    def test_invite_codes_and_the_two_confirmations(self):
        """PLAN 1a.9: with gate L0 off a code is needed and works once; the 18+
        and US-residency confirmations are kept with their own times."""
        import invite_codes
        c = self.conn
        boss = self.user("boss.l0")
        first, second = invite_codes.make(c, 2, by=boss, note="beta")
        signup = dict(AGREE, seconds_open=10, needs_code=True)
        self.assertEqual(auth.sign_up(c, "kim@example.com", PW, **signup)["error"],
                         invite_codes.NEED_CODE)
        made = auth.sign_up(c, "kim@example.com", PW, invite_code=invite_codes.shown(first)
                            .lower(), **signup)
        self.assertTrue(made["ok"], made)
        again = auth.sign_up(c, "lou@example.com", PW, invite_code=first, **signup)
        self.assertEqual(again["error"], invite_codes.NOT_WORKING)
        self.assertTrue(invite_codes.revoke(c, second))
        self.assertEqual(auth.sign_up(c, "lou@example.com", PW, invite_code=second,
                                      **signup)["error"], invite_codes.NOT_WORKING)
        rows = {r["code"]: r for r in invite_codes.listing(c)}
        self.assertEqual((rows[first]["status"], rows[first]["used_by"]),
                         ("used", "kim@example.com"))
        self.assertEqual(rows[second]["status"], "revoked")
        row = self.one("SELECT terms_accepted_at, age_confirmed_at, us_resident_at FROM users "
                       "WHERE id = ?", (made["user_id"],))
        self.assertTrue(row["age_confirmed_at"])
        self.assertEqual(len({row["terms_accepted_at"], row["age_confirmed_at"],
                              row["us_resident_at"]}), 1)
        # deleting the account clears who used it; the code stays used
        self.assertTrue(admin.delete_own(c, made["user_id"], PW)["ok"])
        (left,) = [r for r in invite_codes.listing(c) if r["code"] == first]
        self.assertEqual((left["status"], left["used_by"]), ("used", None))
        self.assertFalse(invite_codes.usable(c, first))
        c.execute("DELETE FROM signups")   # (this class shares one schema: the next
        c.commit()                         # test counts sign-ups from zero)

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

    def test_old_backup_codes_still_work_and_new_ones_are_slow_hashes(self):
        # PLAN 1b.8: PBKDF2 hashes; a set from before (plain SHA-256) still works
        c = self.conn
        uid = self.user("bea")
        secret = two_step.new_secret()
        on = two_step.enable(c, uid, secret, two_step.totp(secret, NOW), now=NOW)
        stored = self.one("SELECT backup_codes_hash FROM two_step WHERE user_id = ?",
                          (uid,))["backup_codes_hash"].split()
        self.assertTrue(all(e.startswith("p2$") for e in stored))
        later = NOW + timedelta(seconds=60)
        self.assertTrue(two_step.verify(c, uid, on["backup_codes"][1], now=later)["ok"])
        c.execute("UPDATE two_step SET backup_codes_hash = ? WHERE user_id = ?",
                  (two_step._backup_hash(uid, "abcd-efgh"), uid))
        c.commit()
        used = two_step.verify(c, uid, "abcd-efgh", now=later)
        self.assertEqual((used["ok"], used["used_backup"], used["backup_left"]), (True, True, 0))
        self.assertEqual(self.one("SELECT backup_codes_hash FROM two_step WHERE user_id = ?",
                                  (uid,))["backup_codes_hash"], "")


class TwoStepKeyTests(_PG):
    """Two-step keys sealed with NORTHWEND_TOTP_KEY (audit 1.1e) on Postgres:
    the sealed form fits the column, a readable row is sealed at a good code,
    and encrypt-two-step does the rest in one go."""
    TAG = "totpkey"

    def test_sealed_keys_and_the_command(self):
        from cryptography.fernet import Fernet
        k = Fernet.generate_key().decode()
        c = self.conn
        old_uid, new_uid, idle_uid = self.user("olive"), self.user("nina"), self.user("ida")
        no_key = {n: v for n, v in os.environ.items() if n != "NORTHWEND_TOTP_KEY"}
        with unittest.mock.patch.dict(os.environ, no_key, clear=True):
            old = two_step.new_secret()
            self.assertTrue(two_step.enable(c, old_uid, old, two_step.totp(old, NOW),
                                            now=NOW)["ok"])
            idle = two_step.new_secret()
            self.assertTrue(two_step.enable(c, idle_uid, idle, two_step.totp(idle, NOW),
                                            now=NOW)["ok"])
        def stored(uid):
            return self.one("SELECT totp_secret FROM two_step WHERE user_id = ?",
                            (uid,))["totp_secret"]

        self.assertEqual(stored(old_uid), old)
        with unittest.mock.patch.dict(os.environ, {**no_key, "NORTHWEND_TOTP_KEY": k},
                                      clear=True):
            new = two_step.new_secret()
            self.assertTrue(two_step.enable(c, new_uid, new, two_step.totp(new, NOW),
                                            now=NOW)["ok"])
            self.assertTrue(stored(new_uid).startswith(two_step.SEALED))
            later = NOW + timedelta(seconds=60)
            stamp = two_step.status(c, old_uid)["stamp"]
            for uid, s in ((old_uid, old), (new_uid, new)):
                self.assertTrue(two_step.verify(c, uid, two_step.totp(s, later), now=later)["ok"])
            self.assertTrue(stored(old_uid).startswith(two_step.SEALED))   # sealed on the way
            self.assertEqual(two_step.status(c, old_uid)["stamp"], stamp)
            self.assertEqual(two_step.storage(c),
                             {"sealed": 2, "readable": 1, "unreadable": 0, "old_key": 0})
            res = two_step.encrypt_all(c)
            self.assertEqual((res["ok"], res["sealed"]), (True, 1))
            self.assertEqual(two_step._open(stored(idle_uid)), idle)
            self.assertEqual(two_step.storage(c)["readable"], 0)


class SignOutAndLogTests(_PG):
    """PLAN 1b.2, 1b.3 and 1b.7 on Postgres: the session numbers, the admin
    action log, and passwords at 600,000 iterations."""
    TAG = "signout"

    def test_sign_out_everyone_and_other_devices(self):
        c = self.conn
        a, b = self.user("gen.a"), self.user("gen.b")
        before = auth.session_gen(c, a)
        tok = auth.create_session(c, b)
        self.assertGreaterEqual(auth.sign_out_everyone(c), 1)       # the upsert, first time
        self.assertIsNone(auth.session_user(c, tok))
        auth.sign_out_everyone(c)                                  # ...and again
        self.assertEqual(self.one("SELECT number FROM app_state WHERE name = ?",
                                  (auth.EVERYONE_GEN,))["number"], 2)
        now = auth.session_gen(c, a)
        self.assertNotEqual(now, before)
        _, row = two_step.status_and_login(c, a)
        self.assertEqual(auth.session_gen_of(row), now)
        here = auth.create_session(c, a)
        auth.create_session(c, a)
        b_gen = auth.session_gen(c, b)
        self.assertEqual(auth.end_other_sessions(c, a, here), 1)
        self.assertNotEqual(auth.session_gen(c, a), now)
        self.assertEqual(auth.session_gen(c, b), b_gen)
        self.assertEqual(self.one("SELECT session_gen FROM users WHERE id = ?",
                                  (a,))["session_gen"], 1)

    def test_the_admin_log_append_read_prune_and_a_deleted_account(self):
        import admin_log
        c = self.conn
        boss, sam = self.user("log.boss"), self.user("log.sam")
        admin.set_admin(c, "log.boss", True)
        admin_log.add(c, boss, "temp_password", sam, "shown to the admin once",
                      now=NOW - timedelta(days=400))
        admin_log.add(c, None, "make_admin", boss)
        admin_log.add(c, boss, "reset_password", sam)
        self.assertEqual(len(self.seen("SELECT id FROM admin_log")), 3)   # committed
        rows = admin_log.recent(c)
        self.assertEqual([(r["action"], r["admin"], r["target"]) for r in rows],
                         [("reset_password", "log.boss", "log.sam"),
                          ("make_admin", None, "log.boss"),
                          ("temp_password", "log.boss", "log.sam")])
        self.assertEqual(admin_log.prune(c), 1)
        self.assertTrue(admin.delete_account(c, sam, by=boss)["ok"])
        self.assertEqual(self.seen("SELECT target_id FROM admin_log WHERE action = "
                                   "'reset_password'"), [{"target_id": None}])

    def test_passwords_at_600k_and_an_old_hash_upgraded(self):
        import hashlib
        c = self.conn
        env = {k: v for k, v in os.environ.items() if k != auth.ITERATIONS_SETTING}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            uid = self.user("hash.new")
            self.assertEqual(self.one("SELECT password_iterations FROM users WHERE id = ?",
                                      (uid,))["password_iterations"], 600_000)
            old = self.user("hash.old")
            salt = os.urandom(16)
            c.execute("UPDATE users SET password_hash = ?, password_salt = ?, "
                      "password_iterations = 200000 WHERE id = ?",
                      (hashlib.pbkdf2_hmac("sha256", PW.encode(), salt, 200_000).hex(),
                       salt.hex(), old))
            c.commit()
            self.assertIsNone(auth.verify_login(c, "hash.old", "wrong-one"))
            self.assertEqual(auth.attempt_login(c, "hash.old", PW)["user_id"], old)
            self.assertEqual(self.one("SELECT password_iterations FROM users WHERE id = ?",
                                      (old,))["password_iterations"], 600_000)
            self.assertEqual(auth.verify_login(c, "hash.old", PW), old)


# --------------------------------------------------------------------------- #
# advisors: access, clients, notes, proposals, reports, records
# --------------------------------------------------------------------------- #
class RateLimitTests(_PG):
    """Audit 1.8d on Postgres: rate_limits.allow counts in email_sends,
    committed, and lets go after the hour."""
    TAG = "ratelimit"

    def test_saves_trip_at_the_hour_limit_and_reset(self):
        import rate_limits
        c = self.conn
        uid = self.user("rate.a")
        t0 = NOW
        per_hour = rate_limits.LIMITS[rate_limits.SAVE][0]
        with unittest.mock.patch.dict(rate_limits.LIMITS, {rate_limits.SAVE: (per_hour, 500)}):
            for _ in range(per_hour):
                self.assertTrue(rate_limits.allow(c, uid, rate_limits.SAVE, now=t0))
            self.assertFalse(rate_limits.allow(c, uid, rate_limits.SAVE, now=t0))
            # another connection sees them: committed, hashed, counts only
            rows = self.seen("SELECT * FROM email_sends WHERE purpose = 'limit_save'")
            self.assertEqual(len(rows), per_hour)
            self.assertNotIn(str(uid), {r["email_key"] for r in rows})
            self.assertTrue(rate_limits.allow(c, uid, rate_limits.SAVE,
                                              now=t0 + timedelta(hours=1, seconds=1)))
            # a day on, the first hour's rows are tidied away by the next count
            # (the one an hour on, and the new one, stay)
            self.assertTrue(rate_limits.allow(c, uid, rate_limits.SAVE,
                                              now=t0 + timedelta(days=1, minutes=2)))
            self.assertEqual(len(self.seen("SELECT * FROM email_sends WHERE purpose = "
                                           "'limit_save'")), 2)


class AdvisorTests(_PG):
    TAG = "advisor"

    def advisor_with_client(self, tag):
        carol = self.user(f"carol.{tag}", advisor=True)
        dana = auth.create_client(self.conn, carol, f"dana.{tag}@example.com", name="Dana Lee")
        return carol, dana

    def test_asking_for_advisor_access_approved_or_declined(self):
        c = self.conn
        box = _mail(self)
        nia = auth.sign_up(c, "nia@example.com", PW, seconds_open=10, **SIGNUP)["user_id"]
        omar = auth.sign_up(c, "omar@example.com", PW, seconds_open=10, **SIGNUP)["user_id"]
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
        self.assertEqual(auth.verify_login(c, "dana.invite@example.com", "clientpass1"), dana)

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
        notes = {n["kind"]: n for n in advising.list_notes(c, dana, include_private=True,
                                                           advisor_id=carol)}
        self.assertEqual(len(advising.list_notes(c, dana, include_private=False)), 2)
        step = notes["Next step"]["id"]
        self.assertTrue(advising.edit_note(c, dana, step, "Open a Roth IRA this month",
                                           now=NOW, advisor_id=carol))
        hist = json.loads(self.one("SELECT history FROM advisor_notes WHERE id = ?",
                                   (step,))["history"])
        self.assertEqual([h["body"] for h in hist], ["Open a Roth IRA"])
        advising.set_done(c, dana, step, True, advisor_id=carol)
        self.assertEqual(self.one("SELECT done FROM advisor_notes WHERE id = ?", (step,)),
                         {"done": 1})
        self.assertTrue(advising.archive_note(c, dana, step, now=NOW, advisor_id=carol))
        self.assertFalse(advising.archive_note(c, other, step, advisor_id=carol))   # not that client's
        self.assertNotIn(step, [n["id"] for n in advising.list_notes(
            c, dana, include_private=True, advisor_id=carol)])
        self.assertEqual([n["id"] for n in advising.list_notes(c, dana, include_private=True,
                                                               archived=True,
                                                               advisor_id=carol)], [step])
        self.assertTrue(advising.restore_note(c, dana, step, advisor_id=carol))
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
        hidden = max(n["id"] for n in advising.list_notes(c, dana, include_private=True,
                                                          advisor_id=carol))
        advising.edit_note(c, dana, hidden, "Private note, edited", now=NOW, advisor_id=carol)
        advising.archive_note(c, dana, hidden, now=NOW, advisor_id=carol)
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
                                send=lambda to, link, lines, unsub: sent.append(to) or True)
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
# PLAN step 5: the advisor agreement, licence checks (D15), the standing line
# --------------------------------------------------------------------------- #
@unittest.skipUnless(PG, SKIP)
class AdvisorAgreementTests(_PG):
    TAG = "agree"

    def test_agreement_licence_checks_and_the_nightly_count(self):
        import advisor_agreement
        import licence_check
        import standing_line
        c = self.conn
        carol = self.user("carol.pg", advisor=True)
        dana = auth.create_client(c, carol, "dana.pg", name="Dana")
        env = {"NORTHWEND_FLAGS": "advisor_agreement", "NORTHWEND_GATES": ""}
        with unittest.mock.patch.dict(os.environ, env), \
                unittest.mock.patch("flags._secret", lambda name: None):
            self.assertFalse(auth.can_view(c, carol, dana))
            advisor_agreement.accept(c, carol, ticked=True)
            self.assertTrue(auth.can_view(c, carol, dana))
        row = self.one("SELECT version, l1_on FROM advisor_agreements WHERE user_id = ?",
                       (carol,))
        self.assertEqual(row, {"version": advisor_agreement.VERSION, "l1_on": 0})
        # approval with the check made, kept by another connection
        nia = self.user("nia.pg")
        auth.request_advisor(c, nia, "Nia Wealth", "7012345")
        admin.approve_advisor(c, "nia.pg", check={"source": "IAPD", "crd": "7012345",
                                                  "checked_on": "2026-10-01"}, by=carol)
        self.assertEqual(self.one("SELECT source, crd, checked_on FROM licence_checks "
                                  "WHERE advisor_id = ?", (nia,)),
                         {"source": "IAPD", "crd": "7012345", "checked_on": "2026-10-01"})
        self.assertTrue(licence_check.licence_current(c, nia, today=date(2026, 10, 6)))
        today = date(2026, 10, 6)
        self.assertEqual(licence_check.counts(c, today=today), {"due": 1, "overdue": 1})
        box = _mail(self)
        with unittest.mock.patch.dict(os.environ, {"RESEND_API_KEY": "re_test",
                                                   "MAIL_DRY_RUN": ""}):
            self.assertTrue(licence_check.remind(c, today=today)["emailed"])
            self.assertIsNone(licence_check.remind(c, today=today)["emailed"])
        self.assertEqual([s for _, s in box.sent], ["Advisor license checks due"])
        self.assertEqual(self.one("SELECT number FROM app_state WHERE name = ?",
                                  (licence_check.MAILED_STATE,)),
                         {"number": today.toordinal()})
        prefs.save(c, carol, {"advisor_card": {"name": "Carol", "firm": "Reyes Wealth"}})
        self.assertIn("Carol's advice, from Reyes Wealth", standing_line.for_advisor(c, carol))
        acc = {a["id"]: a for a in admin.list_accounts(c)}
        self.assertTrue(acc[carol]["agreement"]["current"])
        self.assertEqual(acc[nia]["licence_status"], licence_check.status(
            licence_check.last_check(c, nia)))
        # deleting the advisor takes both with it
        self.assertTrue(admin.delete_account(c, nia, by=-1)["ok"])
        self.assertEqual(self.seen("SELECT * FROM licence_checks WHERE advisor_id = ?", (nia,)),
                         [])


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
        on = unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": "walk"})  # flags.py
        on.start()
        self.addCleanup(on.stop)
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

    def test_unsubscribe_links_turn_off_one_email_for_one_person(self):
        c = self.conn
        ann, bob = self.user("ann.un"), self.user("bob.un", advisor=True)
        for uid, name in ((ann, "ann.un"), (bob, "bob.un")):
            c.execute("UPDATE users SET email = ?, email_verified_at = ? WHERE id = ?",
                      (f"{name}@example.com", "2026-09-01T10:00:00Z", uid))
            c.commit()
            prefs.save(c, uid, {checkin.PREF_EMAIL: True})
        walk = unsubscribe.new_token(c, ann, "walk", "ann.un@example.com")
        week = unsubscribe.new_token(c, bob, "weekly", "bob.un@example.com")
        reset = auth.request_password_reset(c, "ann.un@example.com")["token"]
        for wrong in ("not-a-token", reset, ""):
            self.assertEqual(unsubscribe.use(c, wrong), {"ok": False, "kind": None})
        self.assertIs(prefs.load(c, ann)[checkin.PREF_EMAIL], True)
        self.assertEqual(unsubscribe.use(c, walk), {"ok": True, "kind": "walk"})
        self.assertEqual(unsubscribe.use(c, walk), {"ok": True, "kind": "walk"})  # again: fine
        self.assertIs(prefs.load(c, ann)[checkin.PREF_EMAIL], False)
        self.assertIs(prefs.load(c, bob)[checkin.PREF_EMAIL], True)              # not bob's
        self.assertEqual(unsubscribe.use(c, week), {"ok": True, "kind": "weekly"})
        self.assertIs(prefs.load(c, bob)[weekly_email.PREF_OFF], True)
        self.assertNotIn(weekly_email.PREF_OFF, prefs.load(c, ann))
        stored = [r["token_hash"] for r in c.execute(
            "SELECT token_hash FROM email_tokens WHERE purpose IN ('unsub_walk', 'unsub_weekly') "
            "AND user_id IN (?, ?)", (ann, bob))]
        self.assertEqual(len(stored), 2)
        self.assertNotIn(walk, stored)                                           # hashed only


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
        uid = auth.sign_up(c, "ada@example.com", PW, seconds_open=10, **SIGNUP)["user_id"]
        self.assertFalse(ai_usage.status(c, uid, "chat")["ok"])   # email not confirmed yet
        c.execute("UPDATE users SET email_verified_at = '2026-10-01 10:00:00' WHERE id = ?",
                  (uid,))
        c.commit()
        ai_usage.record(c, uid, "chat")
        ai_usage.record(c, uid, "chat")
        # cost by month and by day (the upsert's CASE on the day, on Postgres)
        day1 = datetime(2031, 3, 4, 9, tzinfo=timezone.utc)
        ai_usage.add_cost(c, uid, "chat", 100_000, now=day1)
        ai_usage.add_cost(c, uid, "chat", 50_000, now=day1)
        st = ai_usage.status(c, uid, "chat", now=day1)
        self.assertEqual((st["cost_used"], st["cost_left"], st["period"]), (150_000, 100_000, "day"))
        ai_usage.add_cost(c, uid, "chat", 20_000, now=day1 + timedelta(days=1))
        st = ai_usage.status(c, uid, "chat", now=day1 + timedelta(days=1))
        self.assertEqual((st["cost_used"], st["cost_left"]), (170_000, 230_000))
        self.assertEqual(self.one("SELECT cost_micro, day, day_cost_micro FROM ai_usage "
                                  "WHERE user_id = ? AND month = '2031-03'", (uid,)),
                         {"cost_micro": 170_000, "day": "2031-03-05", "day_cost_micro": 20_000})
        st = ai_usage.status(c, uid, "chat")
        self.assertEqual(st["used"], 2)
        self.assertEqual(self.one("SELECT used FROM ai_usage WHERE user_id = ? AND month = ?",
                                  (uid, ai_usage.month_of())), {"used": 2})
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

    def test_ai_spend_and_its_alerts(self):
        # the app-wide AI month total (ai_spend.py, PLAN 1a.6): counts only
        import ai_spend
        c = self.conn
        model = "claude-sonnet-5"
        big = {"input_tokens": 3_000_000_000, "output_tokens": 0,   # past 32-bit columns
               "cache_write_tokens": 0, "cache_read_tokens": 0}
        when = datetime(2031, 3, 15, 12, tzinfo=timezone.utc)
        self.assertEqual(ai_spend.record(c, "chat", model, {"input_tokens": 1000,
                                                             "output_tokens": 500}, now=when),
                         7000)   # 1,000 x $2 + 500 x $10 per million = 7,000 micro-dollars
        ai_spend.record(c, "chat", model, {"input_tokens": 1000, "cache_read_tokens": 2000},
                        now=when)
        row = self.one("SELECT calls, input_tokens, output_tokens, cache_read_tokens, cost_micro "
                       "FROM ai_spend WHERE month = '2031-03' AND helper = 'chat'")
        self.assertEqual(row, {"calls": 2, "input_tokens": 2000, "output_tokens": 500,
                               "cache_read_tokens": 2000, "cost_micro": 9400})
        self.assertEqual(ai_spend.level(c, when), ai_spend.NORMAL)
        box = _mail(self)
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_AI_CEILING_USD": "100"}):
            ai_spend.record(c, "csv", "claude-haiku-4-5-20251001", {"output_tokens": 10_000_000},
                            now=when)   # $50 more
            self.assertEqual(ai_spend.level(c, when), ai_spend.ALERT)
            self.assertEqual(ai_spend.maybe_alert(c, now=when), 50)
            self.assertIsNone(ai_spend.maybe_alert(c, now=when))   # once a month
            ai_spend.record(c, "chat", model, big, now=when)
            self.assertEqual(ai_spend.level(c, when), ai_spend.RESTING)
            self.assertEqual(ai_spend.maybe_alert(c, now=when), 80)
        self.assertEqual(len(box.sent), 2)
        self.assertEqual([r["level"] for r in self.seen(
            "SELECT level FROM ai_alerts WHERE month = '2031-03' ORDER BY level")], [50, 80])
        c.execute("DELETE FROM ai_spend WHERE month = '2031-03'")
        c.execute("DELETE FROM ai_alerts WHERE month = '2031-03'")
        c.commit()

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

    def test_dividend_dates_kept_read_and_pruned(self):
        import dividend_dates
        c = self.conn
        soon, later = (TODAY + timedelta(days=5)).isoformat(), (TODAY + timedelta(days=20))
        old = (TODAY - timedelta(days=800)).isoformat()
        uid = self.user("dora")
        sample_data.load(c, uid)
        dividend_dates.store(c, "VTI", [
            {"ex_date": soon, "pay_date": later.isoformat(), "declared_date": None,
             "record_date": soon, "amount": 0.93},
            {"ex_date": old, "pay_date": old, "declared_date": None, "record_date": None,
             "amount": 0.8}], now=NOW)
        dividend_dates.store(c, "AAPL", [], now=NOW)
        # stored again: the upcoming row is replaced, never doubled
        dividend_dates.store(c, "VTI", [
            {"ex_date": soon, "pay_date": later.isoformat(), "declared_date": None,
             "record_date": soon, "amount": 0.94}], now=NOW)
        rows = dividend_dates.upcoming(c, ["VTI", "AAPL"], TODAY)
        self.assertEqual([(r["ticker"], r["ex_date"], r["amount"]) for r in rows],
                         [("VTI", soon, 0.94)])
        todo, recent = dividend_dates.tickers_to_fetch(c, now=NOW)
        self.assertNotIn("VTI", todo)          # just asked
        self.assertNotIn("AAPL", todo)
        self.assertGreaterEqual(recent, 2)
        c.execute("INSERT INTO dividend_events (ticker, ex_date, pay_date, fetched_at) "
                  "VALUES ('OLD', ?, ?, ?)", (old, old, NOW.strftime("%Y-%m-%dT%H:%M:%SZ")))
        self.assertEqual(dividend_dates.prune(c, now=NOW), 1)
        c.commit()
        with c:
            sync_history.upsert_info(c, "AAPL", {"name": "Apple", "quote_type": "EQUITY",
                                                 "ex_dividend_date": soon,
                                                 "dividend_pay_date": None,
                                                 "earnings_date": later.isoformat()})
        self.assertEqual(self.one("SELECT ex_dividend_date, earnings_date FROM security_info "
                                  "WHERE ticker = 'AAPL'"),
                         {"ex_dividend_date": soon, "earnings_date": later.isoformat()})


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

    def test_progress_split_reads_in_one_query_on_postgres(self):
        # the UNION ALL of small reads (progress_split.read): the same money
        # and values as plans.money_moves and recap.value_points
        import progress_split
        import recap
        from tests.test_year_map import seed
        c = self.conn
        uid = self.user("ann.split")
        seed(c, uid, imported=True)
        f = progress_split.read(c, uid)
        self.assertEqual(progress_split.value_points(f), recap.value_points(c, uid))
        self.assertEqual(progress_split.moves(f),
                         sorted((m["date"], m["amount"]) for m in plans.money_moves(c, uid)
                                if m["counted"]))
        self.assertIsNotNone(f["window"])

    def test_account_map_save_export_and_delete(self):
        import account_map
        from tests.test_year_map import seed
        c = self.conn
        uid = auth.sign_up(c, "map@example.com", PW, seconds_open=10, **SIGNUP)["user_id"]
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


class DirectoryTests(_PG):
    """The advisor directory (directory.py, PLAN step 5): a listing saved,
    changed (the upsert), shown alphabetically within filters, exported and
    deleted with the account."""
    TAG = "directory"

    def test_listing_upsert_order_export_and_delete(self):
        import directory
        import licence_check
        c = self.conn
        boss = self.user("boss.dir")
        fields = {"reg_type": "sec_ria", "reg_number": "1234567", "credentials": "CFP®",
                  "fee_models": ["flat", "aum"], "minimum": "none", "serves": ["new"],
                  "states": ["NY", "CA"], "meeting": "both", "description": "How I work.",
                  "scheduling_url": "https://cal.example.com/me"}
        ids = {}
        for login, name in (("zoe.dir", "Zoë Abbott"), ("ann.dir", "ann Lee"),
                            ("ben.dir", "Ben Okafor")):
            ids[name] = self.user(login, advisor=True)
            # a current licence check (licence_check.py), so the listing shows
            licence_check.record(c, ids[name], source="IAPD", crd="1234567",
                                 checked_on=licence_check._today().isoformat())
            res = directory.save_profile(c, ids[name], {"display_name": name, "firm": "F",
                                                        **fields}, listed=True)
            self.assertTrue(res["ok"], res)
        # saved again: one row, changed in place
        directory.save_profile(c, ids["Ben Okafor"],
                               {"display_name": "Ben Okafor", "firm": "F", **fields,
                                "states": ["TX"], "meeting": "in_person"}, listed=True)
        self.assertEqual(self.one("SELECT COUNT(*) AS n, MAX(states) AS s FROM advisor_profiles "
                                  "WHERE user_id = ?", (ids["Ben Okafor"],)),
                         {"n": 1, "s": '["TX"]'})
        names = [p["display_name"] for p in directory.listings(c)]
        self.assertEqual(names, ["ann Lee", "Ben Okafor", "Zoë Abbott"])
        self.assertEqual([p["display_name"] for p in directory.listings(
            c, {"state": "NY", "meeting": "virtual", "fee_models": ["aum"]})],
            ["ann Lee", "Zoë Abbott"])
        self.assertTrue(directory.set_listed(c, ids["ann Lee"], False))
        self.assertEqual(self.one("SELECT listed FROM advisor_profiles WHERE user_id = ?",
                                  (ids["ann Lee"],)), {"listed": 0})
        self.assertEqual(len(directory.listings(c)), 2)
        z = zipfile.ZipFile(io.BytesIO(export.export_zip(c, ids["Zoë Abbott"])))
        self.assertIn("Zoë Abbott", z.read("your_directory_listing.csv").decode())
        self.assertTrue(admin.delete_account(c, ids["Zoë Abbott"], by=boss)["ok"])
        self.assertEqual(self.seen("SELECT user_id FROM advisor_profiles WHERE user_id = ?",
                                   (ids["Zoë Abbott"],)), [])
        self.assertEqual([p["display_name"] for p in directory.listings(c)], ["Ben Okafor"])


class IntroTests(_PG):
    """Introductions and the two-step consent (intros.py, PLAN step 5.5-5.6) on
    Postgres: sent, answered, shared in one transaction (the grant and the
    link both committed, or neither), exported and deleted with an account."""
    TAG = "intros"

    def test_send_answer_share_export_and_delete(self):
        import intros
        import licence_check
        c = self.conn
        boss = self.user("boss.in")
        carol = self.user("carol.in", advisor=True)
        licence_check.record(c, carol, source="IAPD", crd="1234567",
                             checked_on=licence_check._today().isoformat())
        self.assertTrue(directory_profile(c, carol, "Carol Reyes"))
        alice = self.user("alice.in")
        bob = self.user("bob.in")
        res = intros.send(c, alice, carol, "Hello there.", name="Alice",
                          outline={"mix": [["Stocks", 70], ["Bonds", 30]], "stage": "invest"})
        self.assertTrue(res["ok"], res)
        self.assertEqual(self.one("SELECT status, outline FROM intro_requests WHERE id = ?",
                                  (res["id"],)),
                         {"status": "sent",
                          "outline": '{"mix": [["Stocks", 70], ["Bonds", 30]], '
                                     '"stage": "invest"}'})
        self.assertFalse(intros.send(c, alice, carol, "Again", name="Alice")["ok"])
        other = intros.send(c, bob, carol, "Hi", name="Bob")["id"]
        self.assertEqual([r["id"] for r in intros.for_advisor(c, carol)], [other, res["id"]])
        self.assertTrue(intros.reply(c, carol, res["id"], "Happy to talk.", share_link=True)["ok"])
        self.assertTrue(intros.decline(c, carol, other, "Not now.")["ok"])
        self.assertEqual(self.one("SELECT status, reply, link_shared FROM intro_requests "
                                  "WHERE id = ?", (res["id"],)),
                         {"status": "replied", "reply": "Happy to talk.", "link_shared": 1})
        # a failure half-way leaves nothing behind
        text = intros.sharing_text_for(c, carol)
        with unittest.mock.patch.object(auth, "link_client", side_effect=RuntimeError("x")):
            with self.assertRaises(RuntimeError):
                intros.share_account(c, alice, res["id"], text, confirmed=True)
        self.assertEqual(self.seen("SELECT id FROM consent_records WHERE client_id = ?",
                                   (alice,)), [])
        self.assertTrue(intros.share_account(c, alice, res["id"], text, confirmed=True)["ok"])
        self.assertEqual(self.one("SELECT kind, how, text_shown FROM consent_records WHERE "
                                  "client_id = ?", (alice,)),
                         {"kind": "grant", "how": "intro", "text_shown": text})
        self.assertEqual(self.one("SELECT client_name FROM advisor_clients WHERE advisor_id = ? "
                                  "AND client_id = ?", (carol, alice)), {"client_name": "Alice"})
        z = zipfile.ZipFile(io.BytesIO(export.export_zip(c, alice)))
        self.assertIn("Hello there.", z.read("your_introductions.csv").decode())
        z = zipfile.ZipFile(io.BytesIO(export.export_zip(c, carol)))
        self.assertNotIn("person_id", z.read("introductions_to_you.csv").decode())
        self.assertTrue(admin.delete_account(c, bob, by=boss)["ok"])
        self.assertEqual(self.seen("SELECT id FROM intro_requests WHERE person_id = ?", (bob,)),
                         [])
        self.assertTrue(admin.delete_account(c, carol, by=boss)["ok"])
        self.assertEqual(self.seen("SELECT id FROM intro_requests"), [])


def directory_profile(c, uid, name):
    import directory
    return directory.save_profile(c, uid, {
        "display_name": name, "firm": "F", "reg_type": "sec_ria", "reg_number": "1234567",
        "fee_models": ["flat"], "minimum": "none", "serves": ["new"], "states": ["NY"],
        "meeting": "both", "description": "How I work.",
        "scheduling_url": "https://cal.example.com/me"}, listed=True)["ok"]


class DeleteAccountTests(_PG):
    TAG = "delete"

    def test_delete_own_and_admin_delete_clear_every_table(self):
        c = self.conn
        uid = auth.sign_up(c, "del@example.com", PW, seconds_open=10, **SIGNUP)["user_id"]
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

    def test_a_former_clients_own_delete_keeps_the_old_advisors_records(self):
        # PLAN D7: the client's own rows go; each former advisor's records stay
        from datetime import date
        c = self.conn
        carol = self.user("carol.d7", advisor=True)
        omar = self.user("omar.d7", advisor=True)
        dana = auth.create_client(c, carol, "dana.d7@example.com", name="Dana Lee")
        auth.link_client(c, omar, dana)
        auth.set_password(c, "dana.d7@example.com", PW)
        c.execute("UPDATE users SET last_login_at = ? WHERE id = ?", ("2026-09-01 10:00:00",
                                                                     dana))
        c.commit()
        sample_data.load(c, dana)
        advisor.save_profile(c, dana, {"goal": "Retirement"})
        for adv in (carol, omar):
            advising.add_note(c, dana, adv, "Note", "Kept note", "2026-09-01")
            proposals.save(c, adv, dana, title="Mix", mix={"Stocks": 60, "Bonds": 40})
            reports.save(c, adv, dana, label="Q3 2026", start=date(2026, 7, 1),
                         end=date(2026, 9, 30), facts={}, message="")
            advising.end_relationship(c, adv, dana, by="client", now=NOW)
        self.assertTrue(admin.delete_own(c, dana, PW)["ok"])
        self.assertEqual(self.seen("SELECT * FROM users WHERE id = ?", (dana,)), [])
        for table, cols in admin.ACCOUNT_TABLES.items():
            if table not in admin.ADVISOR_RECORD_TABLES:
                where = " OR ".join(f"{col} = ?" for col in cols)
                self.assertEqual(self.seen(f"SELECT * FROM {table} WHERE {where}",
                                           (dana,) * len(cols)), [], table)
        for table in admin.ADVISOR_RECORD_TABLES:
            self.assertEqual(sorted(r["advisor_id"] for r in self.seen(
                f"SELECT advisor_id FROM {table} WHERE client_id = ?", (dana,))),
                sorted((carol, omar)), table)
        record = zipfile.ZipFile(io.BytesIO(export.client_record_zip(c, carol, dana)))
        self.assertIn("Kept note", record.read("notes.csv").decode())

        # someone never linked to an advisor: everything goes
        eve = auth.sign_up(c, "eve.d7@example.com", PW, seconds_open=10, **SIGNUP)["user_id"]
        sample_data.load(c, eve)
        self.assertTrue(admin.delete_own(c, eve, PW)["ok"])
        for table, cols in admin.ACCOUNT_TABLES.items():
            where = " OR ".join(f"{col} = ?" for col in cols)
            self.assertEqual(self.seen(f"SELECT * FROM {table} WHERE {where}",
                                       (eve,) * len(cols)), [], table)


class ConsentAccessTests(_PG):
    """Consent records and the advisor access log (consent.py, access_log.py;
    PLAN step 5, audit 1.2d / 1.6f) on Postgres."""
    TAG = "consent"

    def test_records_revokes_the_log_delete_prune_and_export(self):
        c = self.conn
        carol = self.user("carol.cr", advisor=True)
        omar = self.user("omar.cr", advisor=True)
        dana = auth.create_client(c, carol, "dana.cr@example.com", name="Dana")
        token = auth.create_invite(c, carol, dana)
        self.assertTrue(auth.accept_invite(c, token, PW, consent_text="Shared with Carol.",
                                           **AGREE)["ok"])
        self.assertTrue(consent.current(c, dana, carol))
        row = self.one("SELECT kind, how, text_shown, text_sha256, at FROM consent_records "
                       "WHERE client_id = ?", (dana,))     # committed: another connection sees it
        self.assertEqual((row["kind"], row["how"], row["text_shown"]),
                         ("grant", "setup_link", "Shared with Carol."))
        self.assertEqual(row["text_sha256"], consent.text_sha256("Shared with Carol."))
        self.assertRegex(row["at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        access_log.record(c, carol, dana, "Plan")
        access_log.record(c, omar, dana, "Income", now=NOW - timedelta(days=200))
        self.assertEqual([r["page"] for r in access_log.for_client(c, dana, dana)], ["Plan"])
        self.assertEqual(len(access_log.for_client(c, dana, dana, days=None)), 2)
        self.assertEqual([r["page"] for r in access_log.for_client(c, dana, omar, days=None)],
                         ["Income"])
        self.assertEqual(access_log.for_client(c, dana, self.user("eve.cr"), days=None), [])
        files = export.collect(c, dana)
        self.assertEqual(len(files["sharing_with_an_advisor"]), 1)
        self.assertEqual(len(files["advisor_visits"]), 2)
        self.assertEqual(len(export.client_record(c, carol, dana)["consent"]), 1)

        # stop sharing: a revoke in the same commit as the unlink; access ends
        self.assertTrue(advising.end_relationship(c, carol, dana, by="client",
                                                  text_shown="Stop?")["ok"])
        self.assertEqual(self.one("SELECT kind, how, text_shown FROM consent_records WHERE "
                                  "client_id = ? ORDER BY id DESC LIMIT 1", (dana,)),
                         {"kind": "revoke", "how": "client_stop", "text_shown": "Stop?"})
        self.assertFalse(auth.can_view(c, carol, dana))
        # her account deleted: both tables keep their rows, ids and all
        self.assertTrue(admin.delete_own(c, dana, PW)["ok"])
        self.assertEqual(len(self.seen("SELECT id FROM consent_records WHERE client_id = ?",
                                       (dana,))), 2)
        self.assertEqual(len(self.seen("SELECT id FROM advisor_access_log WHERE client_id = ?",
                                       (dana,))), 2)
        # 7 years on, the prunes take them; not a day before
        later = NOW + timedelta(days=consent.KEEP_DAYS + 2)
        self.assertEqual(consent.prune(c, now=NOW), 0)
        self.assertGreaterEqual(consent.prune(c, now=later), 2)   # (and other tests' ended ones)
        self.assertGreaterEqual(access_log.prune(c, now=later), 2)
        for table in ("consent_records", "advisor_access_log"):
            self.assertEqual(self.seen(f"SELECT id FROM {table} WHERE client_id = ?",
                                       (dana,)), [], table)

    def test_the_back_fill_once(self):
        c = self.conn
        carol = self.user("carol.bf", advisor=True)
        dana = self.user("dana.bf")
        c.execute("DELETE FROM app_state WHERE name = ?", (consent.BACKFILL_MARK,))
        c.commit()
        auth.link_client(c, carol, dana)
        portfolio._SCHEMA_READY.discard(self.dsn)
        with unittest.mock.patch("sys.stderr", new_callable=io.StringIO):
            portfolio._ensure_schema(c)
        self.assertEqual(self.one("SELECT kind, how FROM consent_records WHERE client_id = ?",
                                  (dana,)), {"kind": "grant", "how": "migration"})
        self.assertEqual(consent.backfill(c), 0)
        # asked once at sign-in (PLAN 5.7): the migration grant alone isn't a yes
        self.assertEqual(consent.to_ask(c, dana), [carol])
        self.assertIn(dana, consent.unconfirmed(c, carol))
        consent.grant(c, dana, carol, consent.ask_text("Carol"), "sign_in_ask")
        self.assertEqual(consent.to_ask(c, dana), [])
        self.assertNotIn(dana, consent.unconfirmed(c, carol))

    def test_an_app_role_can_add_and_read_but_not_change_or_delete(self):
        import psycopg
        role = f"nwtest_app_{os.getpid()}_{secrets.token_hex(3)}"
        schema = self.dsn.split("search_path%3D", 1)[1]
        admin_conn = _admin()
        try:
            try:
                admin_conn.execute(f'CREATE ROLE "{role}"')
            except psycopg.Error as exc:
                self.skipTest(f"can't create a role here: {exc}")
            self.addCleanup(lambda: _drop_role(role))
            # what DB_ROLES step 1 gives the app: every row right on every table
            admin_conn.execute(f'GRANT USAGE ON SCHEMA {schema} TO "{role}"')
            admin_conn.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA '
                               f'{schema} TO "{role}"')
            admin_conn.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {schema} '
                               f'TO "{role}"')
        finally:
            admin_conn.close()
        # the schema setup's revoke, for this role as if it were northwend_app
        self.assertEqual(portfolio._append_only_grants(
            self.conn, {role: portfolio.APPEND_ONLY_REVOKES["northwend_app"],
                        "nwtest_no_such_role": "UPDATE"}), [role])
        self.conn.commit()
        raw = psycopg.connect(self.dsn, autocommit=True)
        try:
            raw.execute(f'SET ROLE "{role}"')
            raw.execute("INSERT INTO advisor_access_log (at, advisor_id, client_id, page) "
                        "VALUES ('2026-10-06T12:00:00Z', 1, 2, 'Plan')")
            raw.execute("INSERT INTO consent_records (at, client_id, advisor_id, kind, scope, "
                        "text_shown, how) VALUES ('2026-10-06T12:00:00Z', 2, 1, 'grant', "
                        "'full_sharing', 'x', 'intro')")
            self.assertTrue(raw.execute("SELECT COUNT(*) FROM consent_records").fetchone()[0])
            for sql in ("UPDATE consent_records SET kind = 'revoke'",
                        "DELETE FROM consent_records",
                        "UPDATE advisor_access_log SET page = 'x'",
                        "DELETE FROM advisor_access_log",
                        "TRUNCATE advisor_access_log"):
                with self.subTest(sql), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    raw.execute(sql)
            raw.execute("UPDATE watchlist SET ticker = ticker")   # other tables as before
        finally:
            raw.close()


def _drop_role(role):
    with _admin() as c:
        c.execute(f'DROP OWNED BY "{role}"')
        c.execute(f'DROP ROLE IF EXISTS "{role}"')


# --------------------------------------------------------------------------- #
# northwend-migrate (schema version) and northwend-tidy (retention, D5)
# --------------------------------------------------------------------------- #
@unittest.skipUnless(PG, SKIP)
class MigrateAndTidyTests(unittest.TestCase):

    def _versions(self, dsn):
        c = portfolio.connect(dsn)
        try:
            return [dict(r) for r in c.execute("SELECT version, applied_at FROM schema_version")]
        finally:
            c.close()

    def test_migrate_on_a_fresh_database(self):
        import cli
        dsn = fresh_db("migrate")
        self.addCleanup(close_db, dsn)
        out = io.StringIO()
        with unittest.mock.patch("sys.stdout", out):
            self.assertEqual(cli.migrate(["--db", dsn]), 0)
        self.assertIn(f"Schema of the Postgres database is at version {portfolio.SCHEMA_VERSION}",
                      out.getvalue())
        self.assertNotIn(PG.split("@")[-1], out.getvalue())   # the DSN is never printed
        rows = self._versions(dsn)
        self.assertEqual([r["version"] for r in rows], [portfolio.SCHEMA_VERSION])
        self.assertRegex(rows[0]["applied_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(portfolio.migrate(dsn), rows[0])   # again: nothing changes
        self.assertEqual(in_use(dsn), 0)

    def test_migrate_upgrades_a_database_from_sep_30_and_records_the_version(self):
        import psycopg
        dsn = fresh_db("migrateold")
        self.addCleanup(close_db, dsn)
        with open(OLD_SCHEMA, encoding="utf-8") as fh:
            old = fh.read()
        raw = psycopg.connect(dsn, autocommit=True)
        try:
            raw.execute(";\n".join(pgcompat._split_statements(old)))
            raw.execute("INSERT INTO users (username, password_hash, password_salt) "
                        "VALUES ('olive', 'x', 'y')")
            self.assertIsNone(raw.execute("SELECT to_regclass('schema_version')").fetchone()[0])
        finally:
            raw.close()
        with unittest.mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            done = portfolio.migrate(dsn)
        self.assertIn("changed to BIGINT", err.getvalue())   # the upgrade's own clean-ups ran
        self.assertEqual(done["version"], portfolio.SCHEMA_VERSION)
        c = portfolio.connect(dsn)
        try:
            cols = {r["column_name"] for r in c.execute(
                "SELECT column_name FROM information_schema.columns WHERE "
                "table_schema = current_schema() AND table_name = 'users'")}
            self.assertTrue({"email", "terms_version", "is_admin", "last_login_at"} <= cols)
            self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM schema_version")
                             .fetchone()["n"], 1)
        finally:
            c.close()

    def test_tidy_runs(self):
        import tidy
        dsn = fresh_db("tidy")
        self.addCleanup(close_db, dsn)
        c = portfolio.connect(dsn)
        long_ago = (NOW - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S")
        try:
            gone = auth.sign_up(c, "never.confirmed@example.com", PW, seconds_open=10,
                                **SIGNUP)["user_id"]
            sample_data.load(c, gone)
            kept = auth.sign_up(c, "confirmed@example.com", PW, seconds_open=10,
                                **SIGNUP)["user_id"]
            fresh = auth.sign_up(c, "just.joined@example.com", PW, seconds_open=10,
                                 **SIGNUP)["user_id"]
            made = auth.create_user(c, "admin.made", PW)
            c.execute("UPDATE users SET created_at = ? WHERE id IN (?, ?, ?)",
                      (long_ago, gone, kept, made))
            c.execute("UPDATE users SET email_verified_at = ? WHERE id = ?", (long_ago, kept))
            c.execute("INSERT INTO error_events (kind, source, error_type, place, first_seen, "
                      "last_seen) VALUES ('old', 'job', 'Job failed', 'x', ?, ?)",
                      ("2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"))
            c.execute("INSERT INTO intraday_bars (ticker, interval, ts, close) VALUES "
                      "('VTI', '1m', ?, 300), ('VTI', '1m', ?, 301)",
                      ((NOW - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       NOW.strftime("%Y-%m-%dT%H:%M:%SZ")))
            c.commit()
        finally:
            c.close()
        out = io.StringIO()
        with unittest.mock.patch.object(tidy, "admin_log", None), \
                unittest.mock.patch("sys.stdout", out):
            self.assertEqual(tidy.main(["--db", dsn]), 0)
        text = out.getvalue()
        self.assertIn("unconfirmed accounts 1, error records 1", text)
        self.assertIn("minute bars 1", text)
        self.assertNotIn("example.com", text)
        ids = {r["id"] for r in self._seen(dsn, "SELECT id FROM users")}
        self.assertEqual(ids, {kept, fresh, made})
        self.assertEqual(self._seen(dsn, "SELECT * FROM snapshots WHERE user_id = ?", (gone,)),
                         [])
        self.assertEqual(len(self._seen(dsn, "SELECT * FROM intraday_bars")), 1)
        self.assertEqual(in_use(dsn), 0)

    def _seen(self, dsn, sql, params=()):
        c = portfolio.connect(dsn)
        try:
            return [dict(r) for r in c.execute(sql, params)]
        finally:
            c.close()


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
              unittest.mock.patch("socket.socket.connect", offline_net.connect)):
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
        at.checkbox(key="terms_us").check()
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
                        "display_name", "ai_unlimited", "last_login_at", "age_confirmed_at",
                        "us_resident_at", "password_iterations", "session_gen"):
                self.assertIn(col, users)
            # passwords from before 1b.7 keep the count they were made with
            self.assertEqual(conn.execute("SELECT password_iterations, session_gen FROM users "
                                          "WHERE username = 'olive'").fetchone()[:],
                             (200_000, 0))
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
                          "former_clients", "invite_codes", "app_state", "admin_log",
                          "consent_records", "advisor_access_log"):
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
