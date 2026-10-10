"""The database roles split (docs/DB_ROLES.md, PLAN 4.6, audit 1.6c / 1.6f):
- db_roles.py's SQL: the app and jobs roles get rows only - no CREATE on the
  schema or the database, never TRUNCATE / REFERENCES / TRIGGER - default
  privileges for what the owner makes later, the append-only revokes, and
  every statement safe to run twice; no password in it;
- `northwend-migrate --roles`: Postgres only, `--new-password` only with it;
- with NORTHWEND_SKIP_SCHEMA_SETUP on, nothing the app or the jobs run sends
  a CREATE / ALTER / DROP (a SQLite scratch database, every statement traced),
  and DDL is written only where the owner's migrate runs it;
- on a real Postgres (skipped without NORTHWEND_TEST_PG, like
  tests/test_postgres.py): the roles made twice, what each can and can't do,
  a table made later, the app and the tidy signed in as the roles.

    python -m unittest tests.test_db_roles_split        (from the repo root)
"""

import ast
import contextlib
import io
import os
import re
import secrets
import shutil
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock
from urllib.parse import urlsplit

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import db_roles  # noqa: E402
import pgcompat  # noqa: E402
import portfolio  # noqa: E402

DDL = re.compile(r"^\s*(CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|COMMENT|REINDEX|VACUUM)\b",
                 re.I)
PW = "pw-123456789"


def _skip(value):
    env = {k: v for k, v in os.environ.items() if k != "NORTHWEND_SKIP_SCHEMA_SETUP"}
    if value is not None:
        env["NORTHWEND_SKIP_SCHEMA_SETUP"] = value
    return unittest.mock.patch.dict(os.environ, env, clear=True)


# --------------------------------------------------------------------------- #
# the SQL
# --------------------------------------------------------------------------- #
class RolesSqlTests(unittest.TestCase):

    def setUp(self):
        self.stmts = db_roles.statements("neondb_owner", "neondb")
        self.text = db_roles.script()

    def test_both_roles_are_made_only_if_missing_with_no_extra_powers(self):
        for role in db_roles.ROLES:
            made = [s for s in self.stmts if f'CREATE ROLE "{role}"' in s]
            self.assertEqual(len(made), 1, role)
            self.assertRegex(made[0], r"^DO \$roles\$ BEGIN IF NOT EXISTS \(SELECT FROM "
                                      r"pg_catalog\.pg_roles WHERE rolname = '" + role + r"'\)")
            self.assertTrue(made[0].endswith("END IF; END $roles$"))
            for attr in ("LOGIN", "NOSUPERUSER", "NOCREATEDB", "NOCREATEROLE",
                         "NOREPLICATION", "NOBYPASSRLS"):
                self.assertIn(f" {attr}", made[0])

    def test_every_statement_is_safe_to_run_twice(self):
        # a guarded DO block, a GRANT / REVOKE (changing nothing when already
        # so), or default privileges - never a bare CREATE, a DROP or a rename
        for s in self.stmts:
            self.assertRegex(s, r"^(DO \$roles\$|GRANT |REVOKE |ALTER DEFAULT PRIVILEGES )", s)
            self.assertNotRegex(s, r"\b(DROP|RENAME|OWNER TO|PASSWORD)\b", s)
        self.assertEqual(self.text.count("$roles$"), 4)   # both blocks closed

    def test_the_roles_can_create_nothing(self):
        both = '"northwend_app", "northwend_jobs"'
        self.assertIn('REVOKE CREATE ON SCHEMA "public" FROM PUBLIC', self.stmts)
        self.assertIn(f'REVOKE CREATE ON SCHEMA "public" FROM {both}', self.stmts)
        self.assertIn(f'REVOKE CREATE ON DATABASE "neondb" FROM {both}', self.stmts)
        granted = []
        for s in self.stmts:
            m = re.search(r"\bGRANT (.+?) ON ", s)
            if m:
                granted.append(m.group(1))
                self.assertNotIn("WITH GRANT OPTION", s)
                self.assertNotIn("WITH ADMIN", s)
        self.assertEqual(sorted(set(granted)), ["CONNECT", "SELECT, INSERT, UPDATE, DELETE",
                                                "USAGE", "USAGE, SELECT"])
        self.assertNotRegex(self.text, r"\bGRANT\s+[^;]*\b(ALL PRIVILEGES|CREATE|TEMP\w*)\b"
                                       r"[^;]*\bON\b")

    def test_rows_on_every_table_and_counter_now_and_later(self):
        both = '"northwend_app", "northwend_jobs"'
        self.assertIn(f'GRANT CONNECT ON DATABASE "neondb" TO {both}', self.stmts)
        self.assertIn(f'GRANT USAGE ON SCHEMA "public" TO {both}', self.stmts)
        self.assertIn('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "public" '
                      f'TO {both}', self.stmts)
        self.assertIn(f'REVOKE TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA "public" '
                      f'FROM {both}', self.stmts)
        self.assertIn(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "public" TO {both}',
                      self.stmts)
        later = 'ALTER DEFAULT PRIVILEGES FOR ROLE "neondb_owner" IN SCHEMA "public" '
        self.assertIn(later + f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {both}",
                      self.stmts)
        self.assertIn(later + f"GRANT USAGE, SELECT ON SEQUENCES TO {both}", self.stmts)
        self.assertIn(later + f"REVOKE TRUNCATE, REFERENCES, TRIGGER ON TABLES FROM {both}",
                      self.stmts)
        # the default privileges come after the grants on what exists
        self.assertLess(self.stmts.index('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN '
                                         f'SCHEMA "public" TO {both}'),
                        self.stmts.index(later + "GRANT SELECT, INSERT, UPDATE, DELETE ON "
                                                 f"TABLES TO {both}"))

    def test_consent_and_access_log_stay_add_only_last(self):
        tables = ", ".join(portfolio.APPEND_ONLY_TABLES)
        lines = self.text.strip().splitlines()
        self.assertEqual(lines[-2:], [
            f'REVOKE UPDATE, DELETE, TRUNCATE ON {tables} FROM "northwend_app";',
            f'REVOKE UPDATE, TRUNCATE ON {tables} FROM "northwend_jobs";'])
        self.assertEqual(db_roles.append_only_revokes(),
                         {r: portfolio.APPEND_ONLY_REVOKES[r] for r in db_roles.ROLES})
        self.assertNotIn("DELETE", portfolio.APPEND_ONLY_REVOKES["northwend_jobs"])  # prunes

    def test_names_are_quoted_and_only_plain_role_names_are_taken(self):
        s = db_roles.statements('own"er', "my db", "sch ema")
        self.assertIn('FOR ROLE "own""er" IN SCHEMA "sch ema"', s[-1])
        self.assertIn('ON DATABASE "my db"', "\n".join(s))
        for bad in ("Northwend", "app; DROP TABLE users", "", "a-b", 'x"y', "app\n", "a" * 64):
            with self.assertRaises(ValueError, msg=bad):
                db_roles.statements("o", "d", "public", (bad, "northwend_jobs"))

    def test_the_statements_reach_postgres_as_written(self):
        # setup() sends each through pgcompat's ConnWrapper: nothing in them
        # may look like a placeholder or need a % doubled
        for s in self.stmts:
            self.assertEqual(pgcompat.translate_sql(s), s)

    def test_no_password_in_the_sql(self):
        self.assertNotIn("PASSWORD", self.text)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(db_roles.main(["--sql", "--owner", "o", "--database", "d"]), 0)
        self.assertEqual(out.getvalue(), db_roles.script("o", "d"))

    def test_passwords_are_long_random_and_safe_in_a_literal(self):
        seen = {db_roles.new_password() for _ in range(20)}
        self.assertEqual(len(seen), 20)
        for pw in seen:
            self.assertRegex(pw, r"^[A-Za-z0-9_-]{32}$")

    def test_a_roles_connection_string_is_the_owners_with_the_role_swapped(self):
        owner = ("postgresql://neondb_owner:OWNERSECRET@ep-x-pooler.us-east-2.aws.neon.tech/"
                 "neondb?sslmode=require&channel_binding=require")
        s = db_roles.connection_string(owner, "northwend_app", "a-b_C1")
        self.assertEqual(s, "postgresql://northwend_app:a-b_C1@ep-x-pooler.us-east-2.aws.neon"
                            ".tech/neondb?sslmode=require&channel_binding=require")
        self.assertNotIn("OWNERSECRET", s)
        self.assertNotIn("neondb_owner", s)
        odd = db_roles.connection_string("postgres://u@h:5432/db?options=-csearch_path%3Dx",
                                         "r", "p@ss/word")
        parts = urlsplit(odd)
        self.assertEqual((parts.username, parts.hostname, parts.port, parts.query),
                         ("r", "h", 5432, "options=-csearch_path%3Dx"))
        self.assertEqual(parts.password, "p%40ss%2Fword")   # quoted


# --------------------------------------------------------------------------- #
# northwend-migrate --roles
# --------------------------------------------------------------------------- #
class MigrateCommandTests(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_roles_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.db = os.path.join(self.dir, "m.db")
        self.addCleanup(portfolio._SCHEMA_READY.discard, os.path.abspath(self.db))

    def _run(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = portfolio.main(["migrate", "--db", self.db, *args])
        return code, out.getvalue(), err.getvalue()

    def test_roles_are_for_postgres_only(self):
        code, out, err = self._run("--roles")
        self.assertEqual(code, 2)
        self.assertIn("Schema of", out)          # the migrate itself still ran
        self.assertIn("Postgres database only", err)

    def test_a_new_password_needs_roles_and_a_known_role(self):
        code, _out, err = self._run("--new-password", "northwend_app")
        self.assertEqual(code, 2)
        self.assertIn("needs --roles", err)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            portfolio.main(["migrate", "--db", self.db, "--roles", "--new-password", "postgres"])

    def test_plain_migrate_is_unchanged(self):
        code, out, _err = self._run()
        self.assertEqual(code, 0)
        self.assertIn(f"is at version {portfolio.SCHEMA_VERSION}", out)

    def test_the_report_in_words(self):
        done = {"owner": "neondb_owner", "roles": list(db_roles.ROLES),
                "created": ["northwend_app"],
                "strings": {"northwend_app": "postgresql://northwend_app:x@h/db"},
                "problems": []}
        out = io.StringIO()
        self.assertEqual(db_roles.report(done, out), 0)
        text = out.getvalue()
        self.assertIn("northwend_app: made now", text)
        self.assertIn("northwend_jobs: already there", text)
        self.assertIn("shown this once", text)
        self.assertIn("Kept their passwords: northwend_jobs", text)
        done.update(strings={}, problems=["northwend_app: can create in schema public"])
        out = io.StringIO()
        self.assertEqual(db_roles.report(done, out), 1)
        self.assertIn("Not right yet", out.getvalue())
        self.assertNotIn("shown this once", out.getvalue())


# --------------------------------------------------------------------------- #
# no DDL from the app or the jobs with the setting on
# --------------------------------------------------------------------------- #
@contextlib.contextmanager
def traced(db: str):
    """Every statement any new SQLite connection to `db` runs, in a list.
    (Only that file: a library's own cache file - yfinance keeps one - isn't
    the app's database.)"""
    seen: list[str] = []
    real = sqlite3.connect
    want = os.path.normcase(os.path.abspath(db))

    def connect(*a, **kw):
        conn = real(*a, **kw)
        path = a[0] if a else kw.get("database")
        if isinstance(path, str) and os.path.normcase(os.path.abspath(path)) == want:
            conn.set_trace_callback(seen.append)
        return conn

    with unittest.mock.patch("sqlite3.connect", connect):
        yield seen


class NoDdlWhenSkippedTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="pt_noddl_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio.migrate(cls.db)   # the owner's migrate, done beforehand
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))

    @classmethod
    def tearDownClass(cls):
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        # each test is a new process (or a codefresh reload: the set starts empty)
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))

    def assertNoDdl(self, seen):
        self.assertTrue(seen, "the trace saw nothing - the hook isn't working")
        ddl = [s for s in seen if DDL.match(s)]
        self.assertEqual(ddl, [])

    def test_the_hook_sees_ddl_when_the_setup_runs(self):
        with _skip(None), traced(self.db) as seen:
            portfolio.connect(self.db).close()
        self.assertTrue([s for s in seen if DDL.match(s)])

    def test_the_apps_writes_send_no_ddl(self):
        import access_log
        import auth
        import consent
        import sample_data
        import watchlist
        with _skip("1"), traced(self.db) as seen:
            for _ in range(2):   # and again after a reload (the set emptied)
                portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
                c = portfolio.connect(self.db)
                try:
                    uid = auth.create_user(c, f"u{secrets.token_hex(3)}", PW)
                    sample_data.load(c, uid)
                    watchlist.add(c, uid, "VTI")
                    adv = auth.create_user(c, f"a{secrets.token_hex(3)}", PW)
                    consent.grant(c, uid, adv, consent.ask_text("A"), "sign_in_ask")
                    access_log.record(c, adv, uid, "Plan")
                    c.commit()
                finally:
                    c.close()
        self.assertNoDdl(seen)

    def test_the_jobs_send_no_ddl(self):
        import tidy
        with _skip("1"), traced(self.db) as seen, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(tidy.main(["--db", self.db]), 0)
        self.assertNoDdl(seen)

    def test_the_app_draws_a_page_with_no_ddl(self):
        import auth
        import sample_data
        from streamlit.testing.v1 import AppTest
        c = portfolio.connect(self.db, schema_setup=False)
        try:
            uid = auth.create_user(c, f"p{secrets.token_hex(3)}", PW)
            sample_data.load(c, uid)
        finally:
            c.close()
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        # the app's first run reloads the repo's modules (codefresh.py) - which
        # also empties the reloaded portfolio's _SCHEMA_READY, as on a deploy:
        # put back the ones other test files imported, so their mocks still reach
        modules = {n: m for n, m in sys.modules.items()
                   if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                   == REPO}
        self.addCleanup(sys.modules.update, modules)
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "RESEND_API_KEY",
                            "ANTHROPIC_API_KEY", "NORTHWEND_SKIP_SCHEMA_SETUP")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", NORTHWEND_SKIP_SCHEMA_SETUP="1")
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch("socket.socket.connect", offline_net.connect), \
                traced(self.db) as seen:
            at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
            at.session_state["user_id"] = uid
            at.session_state["username"] = "p"
            at.run()
        self.assertFalse(at.exception, [e.value for e in at.exception])
        self.assertNoDdl(seen)


class DdlOnlyInTheMigrateTests(unittest.TestCase):
    """DDL is written in one place: the owner's schema setup (portfolio's
    _ensure_schema and the helpers only it calls) and db_roles.py. Anywhere
    else, the app role would fail on it once NORTHWEND_SKIP_SCHEMA_SETUP is on."""
    SQL = re.compile(r"\b(CREATE\s+(UNIQUE\s+)?(TABLE|INDEX|VIEW|SCHEMA|ROLE|SEQUENCE|TRIGGER|"
                     r"FUNCTION|EXTENSION|TEMP|TEMPORARY)\b|ALTER\s+(TABLE|ROLE|SCHEMA|DATABASE|"
                     r"DEFAULT\s+PRIVILEGES|SEQUENCE|INDEX)\b|DROP\s+(TABLE|INDEX|VIEW|SCHEMA|"
                     r"ROLE|OWNED|SEQUENCE)\b|TRUNCATE\s+\w|GRANT\s+\w|REVOKE\s+\w)")
    ALLOWED = {"portfolio.py": {"_ensure_schema", "_widen_real_columns", "_widen_big_columns",
                                "_append_only_grants"},
               "db_roles.py": {"statements", "script", "setup"}}

    def _files(self):
        for root, dirs, files in os.walk(REPO):
            dirs[:] = [d for d in dirs if d not in (".git", "tests", "website", "evals",
                                                    "__pycache__", ".claude", "node_modules",
                                                    "docs", "static")
                       and not d.startswith(".")]
            for f in files:
                if f.endswith(".py"):
                    yield os.path.join(root, f)

    def test_ddl_strings_only_where_the_owner_runs_them(self):
        found = []
        for path in self._files():
            rel = os.path.relpath(path, REPO).replace(os.sep, "/")
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                          if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef,
                                            ast.AsyncFunctionDef))
                          and n.body and isinstance(n.body[0], ast.Expr)
                          and isinstance(n.body[0].value, ast.Constant)}

            def visit(node, func):
                for child in ast.iter_child_nodes(node):
                    f = child.name if isinstance(child, (ast.FunctionDef,
                                                         ast.AsyncFunctionDef)) else func
                    if (isinstance(child, ast.Constant) and isinstance(child.value, str)
                            and id(child) not in docstrings and self.SQL.search(child.value)):
                        if f not in self.ALLOWED.get(rel, set()):
                            found.append(f"{rel}:{child.lineno} in {f}: {child.value[:60]!r}")
                    visit(child, f)
            visit(tree, None)
        # restore_check.py reads the schema file's table names with a regex
        found = [f for f in found if not f.startswith("scripts/restore_check.py")]
        self.assertEqual(found, [])

    def test_the_schema_files_are_read_only_by_the_setup(self):
        for path in self._files():
            rel = os.path.relpath(path, REPO).replace(os.sep, "/")
            if rel in ("portfolio.py", "scripts/restore_check.py"):
                continue
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotRegex(text, r"(SCHEMA_PATH|SCHEMA_PG_PATH|_ensure_schema\()", rel)


# --------------------------------------------------------------------------- #
# on a real Postgres
# --------------------------------------------------------------------------- #
PG = os.environ.get("NORTHWEND_TEST_PG", "").strip()
SKIP = "set NORTHWEND_TEST_PG to a Postgres URL (postgresql://...) to run these"


def _admin():
    import psycopg
    return psycopg.connect(PG, autocommit=True)


def _close_pools(dsn):
    for mod in {id(pgcompat): pgcompat, id(sys.modules.get("pgcompat", pgcompat)):
                sys.modules.get("pgcompat", pgcompat)}.values():
        pool = mod._POOLS.pop(dsn, None)
        if pool is not None:
            pool.close()


@unittest.skipUnless(PG, SKIP)
class PostgresRolesTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        tag = f"{os.getpid()}_{secrets.token_hex(3)}"
        cls.schema = f"nwtest_{tag}_roles"
        cls.roles = (f"nwtest_app_{tag}", f"nwtest_jobs_{tag}")
        cls.dsns = []
        with _admin() as c:
            c.execute(f"CREATE SCHEMA {cls.schema}")
        cls.dsn = cls._with_path(PG)
        portfolio.migrate(cls.dsn)
        cls.conn = pgcompat.connect(cls.dsn)
        cls.first = db_roles.setup(cls.conn, cls.dsn, roles=cls.roles)

    @classmethod
    def _with_path(cls, dsn):
        out = f"{dsn}{'&' if '?' in dsn else '?'}options=-csearch_path%3D{cls.schema}"
        cls.dsns.append(out)
        return out

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()
        for dsn in cls.dsns + [s for s in cls.first.get("strings", {}).values()]:
            _close_pools(dsn)
            portfolio._SCHEMA_READY.discard(dsn)
        with _admin() as c:
            c.execute(f"DROP SCHEMA IF EXISTS {cls.schema} CASCADE")
            for role in cls.roles:
                exists = c.execute("SELECT 1 FROM pg_roles WHERE rolname = %s",
                                   (role,)).fetchone()
                if exists:
                    c.execute(f'DROP OWNED BY "{role}"')
                    c.execute(f'DROP ROLE "{role}"')

    def _as(self, role):
        """A raw connection to the test schema, acting as `role` (SET ROLE)."""
        import psycopg
        raw = psycopg.connect(self.dsn, autocommit=True)
        raw.execute(f'SET ROLE "{role}"')
        self.addCleanup(raw.close)
        return raw

    def test_made_once_then_left_alone(self):
        self.assertEqual(self.first["created"], list(self.roles))
        self.assertEqual(sorted(self.first["strings"]), sorted(self.roles))
        self.assertEqual(self.first["problems"], [])
        again = db_roles.setup(self.conn, self.dsn, roles=self.roles)
        self.assertEqual((again["created"], again["strings"], again["problems"]), ([], {}, []))
        new = db_roles.setup(self.conn, self.dsn, roles=self.roles,
                             new_passwords=(self.roles[0],))
        self.assertEqual(list(new["strings"]), [self.roles[0]])
        self.assertNotEqual(new["strings"][self.roles[0]], self.first["strings"][self.roles[0]])
        self.first["strings"].update(new["strings"])

    def test_neither_role_can_change_the_schema(self):
        import psycopg
        for role in self.roles:
            raw = self._as(role)
            for sql in ("CREATE TABLE role_check (x int)",
                        "CREATE INDEX role_check_idx ON users (username)",
                        "ALTER TABLE users ADD COLUMN role_check TEXT",
                        "DROP TABLE watchlist",
                        f"CREATE SCHEMA nwtest_{secrets.token_hex(3)}",
                        "TRUNCATE watchlist",
                        "CREATE ROLE nwtest_never"):
                with self.subTest(role=role, sql=sql), \
                        self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    raw.execute(sql)

    def test_rows_yes_and_the_append_only_tables(self):
        import psycopg
        app, jobs = self.roles
        raw = self._as(app)
        # a SERIAL id: the sequence's USAGE
        raw.execute("INSERT INTO users (username, password_hash, password_salt) "
                    "VALUES (%s, 'x', 'y')", (f"r{secrets.token_hex(3)}",))
        self.assertTrue(raw.execute("SELECT COUNT(*) FROM users").fetchone()[0])
        raw.execute("UPDATE users SET password_hash = 'z' WHERE password_hash = 'x'")
        raw.execute("INSERT INTO advisor_access_log (at, advisor_id, client_id, page) "
                    "VALUES ('2000-01-01T00:00:00Z', 1, 2, 'Plan')")
        raw.execute("INSERT INTO consent_records (at, client_id, advisor_id, kind, scope, "
                    "text_shown, how) VALUES ('2000-01-01T00:00:00Z', 2, 1, 'grant', "
                    "'full_sharing', 'x', 'intro')")
        for sql in ("UPDATE consent_records SET kind = 'revoke'", "DELETE FROM consent_records",
                    "UPDATE advisor_access_log SET page = 'x'", "DELETE FROM advisor_access_log"):
            with self.subTest(sql), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                raw.execute(sql)
        raw = self._as(jobs)
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            raw.execute("UPDATE consent_records SET kind = 'revoke'")
        raw.execute("DELETE FROM advisor_access_log WHERE at < '2001-01-01'")   # the prune
        raw.execute("DELETE FROM users WHERE password_hash = 'z'")

    def test_a_table_the_owner_makes_later_is_covered(self):
        with _admin() as c:
            c.execute(f"CREATE TABLE {self.schema}.later_table (id SERIAL PRIMARY KEY, x INT)")
        raw = self._as(self.roles[0])
        raw.execute("INSERT INTO later_table (x) VALUES (1)")
        self.assertEqual(raw.execute("SELECT COUNT(*) FROM later_table").fetchone()[0], 1)
        self.assertEqual(db_roles.check(self.conn, self.schema,
                                        self.conn.execute("SELECT current_database() AS d")
                                        .fetchone()["d"], self.roles), [])
        self.conn.rollback()

    def test_the_check_says_what_is_wrong(self):
        db = self.conn.execute("SELECT current_database() AS d").fetchone()["d"]
        app = self.roles[0]
        with _admin() as c:
            c.execute(f'GRANT CREATE ON SCHEMA {self.schema} TO "{app}"')
            c.execute(f'GRANT UPDATE ON {self.schema}.consent_records TO "{app}"')
        try:
            problems = db_roles.check(self.conn, self.schema, db, self.roles)
            self.conn.rollback()
            self.assertIn(f"{app}: can create in schema {self.schema}", problems)
            self.assertIn(f"{app}: has UPDATE on consent_records", problems)
        finally:
            with _admin() as c:
                c.execute(f'REVOKE CREATE ON SCHEMA {self.schema} FROM "{app}"')
                c.execute(f'REVOKE UPDATE ON {self.schema}.consent_records FROM "{app}"')

    def test_the_app_and_the_tidy_signed_in_as_the_roles(self):
        import psycopg
        import auth
        import tidy
        strings = {r: self._with_path_once(s) for r, s in self.first["strings"].items()}
        app_dsn, jobs_dsn = strings[self.roles[0]], strings[self.roles[1]]
        try:
            psycopg.connect(app_dsn).close()
        except psycopg.OperationalError as exc:
            self.skipTest(f"this server won't let the new role sign in here: {exc}")
        with _skip("1"):
            c = portfolio.connect(app_dsn)   # checks the version only
            try:
                self.assertEqual(c.execute("SELECT current_user AS u").fetchone()["u"],
                                 self.roles[0])
                auth.create_user(c, f"s{secrets.token_hex(3)}", PW)
            finally:
                c.close()
            with contextlib.redirect_stdout(io.StringIO()), \
                    unittest.mock.patch.object(tidy, "admin_log", None):
                self.assertEqual(tidy.main(["--db", jobs_dsn]), 0)
        # and the setup itself, were it tried as the app, is refused
        portfolio._SCHEMA_READY.discard(app_dsn)
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            portfolio.connect(app_dsn, schema_setup=True)

    def _with_path_once(self, s):
        # the strings keep the owner's query, which already has the search path
        self.assertIn(f"search_path%3D{self.schema}", s)
        self.dsns.append(s)
        return s


if __name__ == "__main__":
    unittest.main()
