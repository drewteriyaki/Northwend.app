"""The schema version and migrate command (PLAN 1b.6, audit 1.6d), and the
retention job (PLAN 1b.9, decision D5): `northwend-migrate` and
`northwend-tidy`, on temporary SQLite files. tests/test_postgres.py runs both
on Postgres.

    python -m unittest tests.test_retention
"""

import contextlib
import io
import os
import shutil
import sqlite3
import sys
import tempfile
import types
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import admin  # noqa: E402
import auth  # noqa: E402
import cli  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sample_data  # noqa: E402
import tidy  # noqa: E402

PW = "pw-123456789"
NOW = datetime(2026, 10, 6, 21, 30, tzinfo=timezone.utc)


def _stamp(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _ago(days):
    return _stamp(NOW - timedelta(days=days))


class _DB(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_retention_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.db = os.path.join(self.dir, "t.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))


# --------------------------------------------------------------------------- #
# schema version, northwend-migrate
# --------------------------------------------------------------------------- #
class SchemaVersionTests(_DB):

    def rows(self):
        c = sqlite3.connect(self.db)
        try:
            return c.execute("SELECT version, applied_at FROM schema_version").fetchall()
        finally:
            c.close()

    def test_the_app_records_the_version_when_it_sets_a_database_up(self):
        portfolio.connect(self.db).close()
        (version, applied), = self.rows()
        self.assertEqual(version, portfolio.SCHEMA_VERSION)
        self.assertRegex(applied, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_migrate_command_on_a_fresh_database(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.migrate(["--db", self.db]), 0)
        self.assertIn(f"at version {portfolio.SCHEMA_VERSION}", out.getvalue())
        self.assertEqual([r[0] for r in self.rows()], [portfolio.SCHEMA_VERSION])

    def test_migrate_upgrades_an_old_shaped_database_and_records_it(self):
        raw = sqlite3.connect(self.db)
        raw.executescript(
            "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL "
            "UNIQUE, password_hash TEXT NOT NULL, password_salt TEXT NOT NULL, created_at TEXT "
            "NOT NULL DEFAULT (datetime('now')));"
            "INSERT INTO users (username, password_hash, password_salt) VALUES ('olive', 'x', 'y');")
        raw.close()
        done = portfolio.migrate(self.db)
        self.assertEqual(done["version"], portfolio.SCHEMA_VERSION)
        c = sqlite3.connect(self.db)
        try:
            cols = {r[1] for r in c.execute("PRAGMA table_info(users)")}
            self.assertTrue({"email", "terms_version", "is_admin", "last_login_at"} <= cols)
            self.assertEqual(c.execute("SELECT username FROM users").fetchall(), [("olive",)])
        finally:
            c.close()

    def test_migrate_runs_again_on_purpose_and_keeps_when_it_was_reached(self):
        first = portfolio.migrate(self.db)
        with unittest.mock.patch.object(portfolio, "_ensure_schema",
                                        wraps=portfolio._ensure_schema) as setup:
            again = portfolio.migrate(self.db)   # this process already set it up
        setup.assert_called_once()
        self.assertEqual(again, first)
        self.assertEqual(len(self.rows()), 1)

    def test_a_newer_version_is_never_taken_back(self):
        portfolio.connect(self.db).close()
        c = sqlite3.connect(self.db)
        c.execute("UPDATE schema_version SET version = ?", (portfolio.SCHEMA_VERSION + 4,))
        c.commit()
        c.close()
        self.assertEqual(portfolio.migrate(self.db)["version"], portfolio.SCHEMA_VERSION + 4)

    def test_both_schema_files_have_the_table(self):
        for name in ("schema.sql", "schema_pg.sql"):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                self.assertIn("CREATE TABLE IF NOT EXISTS schema_version", fh.read(), name)

    def test_the_commands_have_help(self):
        for cmd in (cli.migrate, cli.tidy):
            out = io.StringIO()
            with self.subTest(cmd.__name__), contextlib.redirect_stdout(out):
                with self.assertRaises(SystemExit) as done:
                    cmd(["--help"])
            self.assertEqual(done.exception.code, 0)
            self.assertIn("--db", out.getvalue())


# --------------------------------------------------------------------------- #
# northwend-tidy: the retention schedule (D5)
# --------------------------------------------------------------------------- #
class TidyTests(_DB):

    def setUp(self):
        super().setUp()
        self.conn = portfolio.connect(self.db)
        self.addCleanup(self.conn.close)
        p = unittest.mock.patch.object(tidy, "admin_log", None)   # (another change adds it)
        p.start()
        self.addCleanup(p.stop)

    def account(self, name, *, days, self_made=True, confirmed=False, **cols):
        """An account made `days` ago; self-made = from the sign-up form."""
        uid = auth.create_user(self.conn, name, PW)
        values = {"created_at": _ago(days), **cols}
        if self_made:
            values.update(email=name, terms_version="October 1, 2026",
                          terms_accepted_at=_ago(days))
        if confirmed:
            values["email_verified_at"] = _ago(days - 1)
        sets = ", ".join(f"{k} = ?" for k in values)
        self.conn.execute(f"UPDATE users SET {sets} WHERE id = ?", (*values.values(), uid))
        self.conn.commit()
        return uid

    def ids(self):
        return {r["username"]: r["id"] for r in self.conn.execute("SELECT id, username FROM users")}

    def test_the_30_day_rule_deletes_only_never_confirmed_self_made_accounts(self):
        a = self.account
        gone = a("old.unconfirmed@example.com", days=40)
        sample_data.load(self.conn, gone)                  # their data goes with them
        prefs.save(self.conn, gone, {"theme": "dark"})
        auth.create_session(self.conn, gone, now=NOW - timedelta(days=35))   # long expired
        kept = {
            a("new.unconfirmed@example.com", days=10),
            a("old.confirmed@example.com", days=400, confirmed=True),
            a("signed.in.lately@example.com", days=60, last_login_at=_ago(5)),
            a("old.admin.made", days=400, self_made=False),
            a("admin.self.made@example.com", days=400, is_admin=1),
            a("advisor.self.made@example.com", days=400, is_advisor=1),
        }
        live = a("stays.signed.in@example.com", days=60)
        auth.create_session(self.conn, live, now=NOW - timedelta(days=3))
        kept.add(live)
        # an account the advisor made, and a self-made one that became a client
        carol = a("carol.advisor", days=400, self_made=False, is_advisor=1)
        dana = auth.create_client(self.conn, carol, "dana.client@example.com", name="Dana")
        self.conn.execute("UPDATE users SET created_at = ? WHERE id = ?", (_ago(90), dana))
        erin = a("erin.client@example.com", days=90)
        self.conn.execute("INSERT INTO advisor_clients (advisor_id, client_id) VALUES (?, ?)",
                          (carol, erin))
        # a former client of carol's: carol's own records about them stay
        fay = a("fay.former@example.com", days=90)
        self.conn.execute("INSERT INTO former_clients (advisor_id, client_id, ended_at, "
                          "ended_by, account) VALUES (?, ?, ?, 'client', 'kept')",
                          (carol, fay, _ago(50)))
        self.conn.commit()
        kept |= {carol, dana, erin}

        self.assertEqual(sorted(tidy.unconfirmed_accounts(self.conn, now=NOW)), [gone, fay])
        done = tidy.run(self.conn, now=NOW)
        self.assertEqual(done["unconfirmed accounts"], 2)
        left = set(self.ids().values())
        self.assertTrue(kept <= left, kept - left)
        self.assertNotIn(gone, left)
        self.assertNotIn(fay, left)
        for table, cols in admin.ACCOUNT_TABLES.items():
            where = " OR ".join(f"{col} = ?" for col in cols)
            self.assertEqual(self.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}",
                                               (gone,) * len(cols)).fetchone()[0], 0, table)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM former_clients WHERE "
                                           "client_id = ?", (fay,)).fetchone()[0], 1)
        # a second run the same night finds nothing more
        self.assertEqual(tidy.run(self.conn, now=NOW)["unconfirmed accounts"], 0)

    def test_old_records_links_counts_and_minute_bars(self):
        c = self.conn
        uid = self.account("someone@example.com", days=400, confirmed=True)
        iso = lambda days: (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
        for kind, last in (("old", 91), ("recent", 89)):
            c.execute("INSERT INTO error_events (kind, source, error_type, place, first_seen, "
                      "last_seen) VALUES (?, 'app', 'KeyError', 'x', ?, ?)",
                      (kind, iso(200), iso(last)))
        for h, expires in (("t-old", _ago(1)), ("t-live", _ago(-1))):
            c.execute("INSERT INTO email_tokens (token_hash, user_id, purpose, email, "
                      "created_at, expires_at) VALUES (?, ?, 'reset', 'x@example.com', ?, ?)",
                      (h, uid, _ago(3), expires))
            c.execute("INSERT INTO invites (token_hash, user_id, created_by, created_at, "
                      "expires_at) VALUES (?, ?, ?, ?, ?)", (h, uid, uid, _ago(9), expires))
            c.execute("INSERT INTO login_sessions (token_hash, user_id, expires_at) "
                      "VALUES (?, ?, ?)", (h, uid, expires))
        for key, start, locked in (("old", _ago(2), None), ("old-lock-over", _ago(2), _ago(1)),
                                   ("recent", _ago(0.5), None),
                                   ("still-locked", _ago(2), _ago(-0.01))):
            c.execute("INSERT INTO login_failures (username_key, failures, window_start, "
                      "locked_until) VALUES (?, 3, ?, ?)", (key, start, locked))
        for when in (_ago(2), _ago(0.5)):
            c.execute("INSERT INTO signups (address_key, created_at, ok) VALUES ('a', ?, 1)",
                      (when,))
            c.execute("INSERT INTO email_sends (email_key, address_key, purpose, sent_at) "
                      "VALUES ('e', 'a', 'reset', ?)", (when,))
        for interval, days in (("1m", 9), ("1m", 6), ("5m", 30), ("1m", 0)):
            c.execute("INSERT INTO intraday_bars (ticker, interval, ts, close) "
                      "VALUES ('VTI', ?, ?, 300)", (interval, iso(days)))
        c.commit()

        done = tidy.run(c, now=NOW)
        self.assertEqual(done, {"unconfirmed accounts": 0, "error records": 1, "email links": 1,
                                "setup links": 1, "sessions": 1, "wrong-password counts": 2,
                                "sign-up counts": 1, "email-send counts": 1, "minute bars": 1})
        q = lambda sql: [tuple(r) for r in c.execute(sql)]  # noqa: E731
        self.assertEqual(q("SELECT kind FROM error_events"), [("recent",)])
        self.assertEqual(q("SELECT token_hash FROM email_tokens"), [("t-live",)])
        self.assertEqual(sorted(q("SELECT username_key FROM login_failures")),
                         [("recent",), ("still-locked",)])
        self.assertEqual(sorted(q("SELECT b.interval FROM intraday_bars b")),
                         [("1m",), ("1m",), ("5m",)])

    def test_the_admin_log_is_pruned_when_that_module_is_in(self):
        log = types.SimpleNamespace(prune=unittest.mock.Mock(return_value=4))
        with unittest.mock.patch.object(tidy, "admin_log", log):
            done = tidy.run(self.conn, now=NOW)
        log.prune.assert_called_once_with(self.conn, older_than_days=365)
        self.assertEqual(done["admin log entries"], 4)
        self.assertNotIn("admin log entries", tidy.run(self.conn, now=NOW))   # module gone

    def test_the_command_prints_counts_only(self):
        uid = self.account("private.person@example.com", days=45)
        self.conn.execute("UPDATE users SET created_at = ? WHERE id = ?",
                          (_stamp(datetime.now(timezone.utc) - timedelta(days=45)), uid))
        self.conn.commit()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(cli.tidy(["--db", self.db]), 0)
        first, *rest = out.getvalue().splitlines()
        self.assertIn("unconfirmed accounts 1", first)
        # "Tidied: <what> <count>, ..." - words and counts, nothing else
        self.assertRegex(first, r"^Tidied: [a-z -]+ \d+(, [a-z -]+ \d+)*$")
        self.assertNotIn("private.person", out.getvalue())
        self.assertEqual(rest, ["(no admin action log in this copy yet - nothing to prune "
                                "there)"])

    def test_the_nightly_job_runs_it_with_its_own_failure_step(self):
        with open(os.path.join(REPO, ".github", "workflows", "scheduled-sync.yml"),
                  encoding="utf-8") as fh:
            text = fh.read()
        job = text.split("\n  tidy:", 1)[1].split("\n  weekly-email:", 1)[0]
        self.assertIn("github.event.schedule == '30 21 * * 1-5'", job)   # with the history sync
        self.assertIn('python tidy.py --db "$DATABASE_URL"', job)
        self.assertIn("if: failure()", job)
        self.assertIn('python error_alerts.py job "Nightly tidy"', job)


if __name__ == "__main__":
    unittest.main()
