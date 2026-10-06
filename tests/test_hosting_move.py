"""PLAN step 4, the code side of owning the hosting (Render behind Cloudflare):
- render.yaml lists every setting the live app needs (.env.example is the
  list), secrets only as `sync: false`, Streamlit's own settings with values
  this Streamlit accepts, and Streamlit's health check;
- NORTHWEND_SKIP_SCHEMA_SETUP (audit 1.6c): off by default; on, a process
  doesn't set the schema up and stops clearly when `northwend-migrate` hasn't;
- scripts/restore_check.py (1.6e): row counts only, read-only;
- the disclosures name the host each copy really runs on (1.10a), and the
  website (built offline) names both until the move is done;
- docs/CLOUDFLARE.md has every header, and the runbook the move and the
  uptime check; the old copy's "has moved" page needs no secrets.

    python -m unittest tests.test_hosting_move        (from the repo root)
"""

import contextlib
import importlib
import importlib.util
import io
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import tomllib
import unittest
import unittest.mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import disclosures  # noqa: E402
import portfolio  # noqa: E402
import settings  # noqa: E402
from tests import test_ops_docs as ops  # noqa: E402


def _read(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


def render_env() -> dict:
    """{key: ("value", text) | ("sync", False)} for render.yaml's envVars
    (no YAML library in requirements: the file's own simple layout)."""
    out, key = {}, None
    for line in _read("render.yaml").splitlines():
        line = line.split(" #", 1)[0].rstrip()
        m = re.match(r"^\s*- key:\s*([A-Z][A-Z0-9_]*)\s*$", line)
        if m:
            key = m.group(1)
            out[key] = None
            continue
        m = re.match(r"^\s+(value|sync):\s*(.*)$", line)
        if m and key:
            raw = m.group(2).strip().strip('"')
            out[key] = ("sync", raw == "true") if m.group(1) == "sync" else ("value", raw)
            key = None
    return out


def _restore_check():
    spec = importlib.util.spec_from_file_location(
        "restore_check", os.path.join(REPO, "scripts", "restore_check.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
# render.yaml
# --------------------------------------------------------------------------- #
class RenderBlueprintTests(unittest.TestCase):
    # settings .env.example lists that the live app on Render doesn't take
    NOT_ON_RENDER = {
        "DATABASE_URL": "the GitHub jobs' name for the connection string",
        "ANTHROPIC_API_KEY_EVAL": "the eval workspace's key: never an app's",
        "MOVED_TO": "set only on the old copy, after the move",
    }
    SECRETS = ("PORTFOLIO_DB", "ANTHROPIC_API_KEY", "RESEND_API_KEY", "FINNHUB_API_KEY",
               "NORTHWEND_TOTP_KEY", "NORTHWEND_ADMINS", "ALERT_EMAIL")
    # switched by hand in Render's Environment: a Blueprint sync must not undo it
    BY_HAND = ("NORTHWEND_GATES", "NORTHWEND_FLAGS", "NORTHWEND_AI_CEILING_USD", "AI_ZDR")

    def test_the_parser_reads_the_file(self):
        env = render_env()
        self.assertGreaterEqual(len(env), 15)
        self.assertNotIn(None, env.values(), "a key with neither value nor sync: false")

    def test_every_setting_the_live_app_needs_is_listed(self):
        env = render_env()
        listed = ops.env_example()
        needed = {n for n, (_v, commented) in listed.items() if not commented}
        needed |= {n for n in listed if n.startswith("STREAMLIT_") or n == "PYTHON_VERSION"}
        for name in self.NOT_ON_RENDER:
            self.assertIn(name, listed, "the skip list names a setting that no longer exists")
            self.assertNotIn(name, env, f"{name}: {self.NOT_ON_RENDER[name]}")
        missing = sorted(needed - set(env) - set(self.NOT_ON_RENDER))
        self.assertEqual(missing, [], "add these to render.yaml's envVars (or, with the "
                                      "reason, to NOT_ON_RENDER)")

    def test_every_key_in_it_is_documented(self):
        listed = ops.env_example()
        self.assertEqual(sorted(k for k in render_env() if k not in listed), [],
                         "add these to .env.example")

    def test_secrets_are_never_written_in_it(self):
        env = render_env()
        for key in self.SECRETS + self.BY_HAND:
            self.assertEqual(env[key], ("sync", False), key)
        text = _read("render.yaml")
        for prefix in ("sk-ant-", "re_", "postgresql://", "postgres://", "npg_"):
            self.assertNotRegex(text, r"(?<![\w-])" + re.escape(prefix) + r"[A-Za-z0-9]{4,}")

    def test_the_fixed_values(self):
        env = render_env()
        want = {"NORTHWEND_ENV": "production", "CLIENT_IP_HEADER": "cf-connecting-ip",
                "APP_URL": "https://go.northwend.app/", "MAIL_DRY_RUN": "0",
                "NORTHWEND_SKIP_SCHEMA_SETUP": "0", "STREAMLIT_SERVER_MAX_UPLOAD_SIZE": "10",
                "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
                "STREAMLIT_CLIENT_SHOW_ERROR_DETAILS": "none"}
        for key, value in want.items():
            self.assertEqual(env[key], ("value", value), key)
        # the same limit as the config file Community Cloud reads
        with open(os.path.join(REPO, ".streamlit", "config.toml"), "rb") as fh:
            config = tomllib.load(fh)
        self.assertEqual(str(config["server"]["maxUploadSize"]),
                         env["STREAMLIT_SERVER_MAX_UPLOAD_SIZE"][1])
        self.assertIs(config["browser"]["gatherUsageStats"], False)
        # the live copy is hosted, so settings.py fails closed there too
        self.assertIn(env["NORTHWEND_ENV"][1], settings.HOSTED_ENVS)

    def test_streamlits_settings_are_real_options_with_accepted_values(self):
        from streamlit import config
        options = {o.env_var: key for key, o in config.get_config_options().items()}
        for key in render_env():
            if key.startswith("STREAMLIT_"):
                self.assertIn(key, options, f"{key} isn't a setting this Streamlit reads")
        self.assertEqual(options["STREAMLIT_CLIENT_SHOW_ERROR_DETAILS"], "client.showErrorDetails")
        accepted = {o.value for o in config.ShowErrorDetailsConfigOptions}
        self.assertIn(render_env()["STREAMLIT_CLIENT_SHOW_ERROR_DETAILS"][1], accepted)

    def test_the_health_check_is_streamlits_own(self):
        text = _read("render.yaml")
        self.assertRegex(text, r"(?m)^\s+healthCheckPath: /_stcore/health\s*$")
        from streamlit.web.server.starlette import starlette_routes
        self.assertEqual(starlette_routes.ROUTE_HEALTH, "_stcore/health")
        # the uptime monitor watches the same address
        self.assertIn("go.northwend.app/_stcore/health", _read("docs", "RUNBOOK.md"))

    def test_the_region_is_in_the_united_states(self):
        # the disclosures say "Render ... in the United States"
        region = re.search(r"(?m)^\s+region:\s*(\w+)", _read("render.yaml")).group(1)
        self.assertIn(region, ("ohio", "virginia", "oregon"))
        self.assertIn("Render** hosts the app, in the United States",
                      disclosures.hosting_lines(host="Render"))


# --------------------------------------------------------------------------- #
# NORTHWEND_SKIP_SCHEMA_SETUP
# --------------------------------------------------------------------------- #
def _skip(value):
    env = {k: v for k, v in os.environ.items() if k != "NORTHWEND_SKIP_SCHEMA_SETUP"}
    if value is not None:
        env["NORTHWEND_SKIP_SCHEMA_SETUP"] = value
    return unittest.mock.patch.dict(os.environ, env, clear=True)


class SkipSchemaSetupTests(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_skip_")
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.db = os.path.join(self.dir, "skip.db")
        self.addCleanup(portfolio._SCHEMA_READY.discard, os.path.abspath(self.db))

    def _tables(self):
        c = sqlite3.connect(self.db)
        try:
            return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            c.close()

    def _fresh(self):
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))

    def test_the_setting_is_off_unless_set(self):
        for value, on in ((None, False), ("", False), ("0", False), ("no", False),
                          ("1", True), ("true", True), (" On ", True), ("yes", True)):
            with _skip(value):
                self.assertIs(settings.skip_schema_setup(), on, repr(value))

    def test_off_the_app_sets_the_schema_up_as_before(self):
        with _skip(None), unittest.mock.patch.object(
                portfolio, "_ensure_schema", wraps=portfolio._ensure_schema) as setup:
            portfolio.connect(self.db).close()
        self.assertEqual(setup.call_count, 1)
        self.assertIn("users", self._tables())

    def test_on_a_database_never_set_up_stops_with_a_clear_message(self):
        with _skip("1"):
            with self.assertRaises(portfolio.SchemaNotReady) as caught:
                portfolio.connect(self.db)
        self.assertIn("not set up", str(caught.exception))
        self.assertIn("northwend-migrate", str(caught.exception))
        self.assertEqual(self._tables(), set())   # nothing created
        self.assertNotIn(os.path.abspath(self.db), portfolio._SCHEMA_READY)

    def test_on_migrate_still_sets_it_up_and_the_app_then_only_checks(self):
        with _skip("1"):
            done = portfolio.migrate(self.db)
            self.assertEqual(done["version"], portfolio.SCHEMA_VERSION)
            self._fresh()   # a new process: the app starting after the migrate
            with unittest.mock.patch.object(portfolio, "_ensure_schema") as setup:
                conn = portfolio.connect(self.db)
                try:
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
                finally:
                    conn.close()
            setup.assert_not_called()

    def test_on_a_schema_older_than_the_code_stops(self):
        portfolio.migrate(self.db)
        c = sqlite3.connect(self.db)
        c.execute("UPDATE schema_version SET version = ?", (portfolio.SCHEMA_VERSION - 1,))
        c.commit()
        c.close()
        self._fresh()
        with _skip("1"), self.assertRaises(portfolio.SchemaNotReady) as caught:
            portfolio.connect(self.db)
        self.assertIn(f"at version {portfolio.SCHEMA_VERSION - 1}", str(caught.exception))
        # with the setting off, the app brings it up to date itself, as always
        with _skip(None):
            portfolio.connect(self.db).close()

    def test_the_jobs_can_be_told_too(self):
        wf = _read(".github", "workflows", "scheduled-sync.yml")
        top = wf.split("\njobs:", 1)[0]
        self.assertIn("NORTHWEND_SKIP_SCHEMA_SETUP: ${{ vars.NORTHWEND_SKIP_SCHEMA_SETUP }}", top)

    def test_the_roles_page_has_the_sql(self):
        text = _read("docs", "DB_ROLES.md")
        for role in ("northwend_app", "northwend_jobs"):
            self.assertIn(f"CREATE ROLE {role} WITH LOGIN", text)
        self.assertIn("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public", text)
        self.assertIn("ALTER DEFAULT PRIVILEGES", text)
        self.assertNotRegex(text, r"GRANT\s+(ALL|CREATE)\b[^;]*\bTO northwend_(app|jobs)")
        for word in ("NORTHWEND_SKIP_SCHEMA_SETUP", "northwend-migrate", "1.6f"):
            self.assertIn(word, text)


# --------------------------------------------------------------------------- #
# scripts/restore_check.py
# --------------------------------------------------------------------------- #
class RestoreCheckTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.rc = _restore_check()
        cls.dir = tempfile.mkdtemp(prefix="pt_restore_")
        cls.live = os.path.join(cls.dir, "live.db")
        cls.restored = os.path.join(cls.dir, "restored.db")
        import auth
        portfolio.migrate(cls.restored)
        c = portfolio.connect(cls.restored)
        try:
            auth.create_user(c, "private.person", "pw-123456789")
        finally:
            c.close()
        shutil.copyfile(cls.restored, cls.live)
        c = portfolio.connect(cls.live)   # live gained a sign-up after the restore point
        try:
            auth.create_user(c, "later.person", "pw-123456789")
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        for path in (cls.live, cls.restored):
            portfolio._SCHEMA_READY.discard(os.path.abspath(path))
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_every_table_in_both_schema_files(self):
        pg = self.rc.tables()
        lite = self.rc.tables(os.path.join(REPO, "schema.sql"))
        self.assertEqual(pg, lite)
        for t in ("users", "snapshots", "positions", "plans", "advisor_notes", "transactions"):
            self.assertIn(t, pg)

    def test_counts_only_and_read_only(self):
        seen, real = [], sqlite3.connect

        def traced(*a, **k):
            seen.append((a, k))
            conn = real(*a, **k)
            conn.set_trace_callback(statements.append)
            return conn
        statements = []
        with unittest.mock.patch.object(self.rc.sqlite3, "connect", traced):
            counts = self.rc.counts(self.restored)
        self.assertEqual(counts["users"], 1)
        self.assertEqual(counts["positions"], 0)
        self.assertTrue(all("mode=ro" in a[0] and k.get("uri") for a, k in seen))
        for sql in statements:
            self.assertRegex(sql, r'^SELECT (COUNT\(\*\) FROM "\w+"|name FROM sqlite_master)')

    def test_the_comparison_and_what_it_prints(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.rc.main(["--db", self.restored, "--against", self.live])
        text = out.getvalue()
        self.assertEqual(code, 0)
        self.assertRegex(text, r"(?m)^users\s+1\s+2\s+\+1$")
        self.assertRegex(text, r"(?m)^positions\s+0\s+0\s+same$")
        self.assertNotIn("private.person", text)   # never a row's contents
        self.assertNotIn(self.dir, text)            # the label, not the path

    def test_a_missing_table_fails(self):
        gone = os.path.join(self.dir, "gone.db")
        shutil.copyfile(self.restored, gone)
        c = sqlite3.connect(gone)
        c.execute("DROP TABLE news")
        c.commit()
        c.close()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(self.rc.main(["--db", gone]), 1)
        self.assertRegex(out.getvalue(), r"(?m)^news\s+missing$")

    def test_the_password_is_never_shown(self):
        dsn = "postgresql://northwend_app:s3cret-pass@ep-x-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require"
        self.assertEqual(self.rc.where(dsn), "ep-x-pooler.us-east-2.aws.neon.tech/neondb")
        self.assertNotIn("s3cret", self.rc.where(dsn))

    def test_the_runbook_drill_uses_it(self):
        self.assertIn("python scripts/restore_check.py --db", _read("docs", "RUNBOOK.md"))


# --------------------------------------------------------------------------- #
# the disclosures name the real host
# --------------------------------------------------------------------------- #
class HostWordingTests(unittest.TestCase):

    def test_each_host_names_itself(self):
        cc = disclosures.hosting_lines(host="Streamlit Community Cloud", behind_cloudflare=False)
        self.assertIn("**Streamlit Community Cloud** hosts the app.", cc)
        self.assertNotIn("Render", cc)
        self.assertIn("**Cloudflare** serves the website", cc)   # true today: Pages
        render = disclosures.hosting_lines(host="Render", behind_cloudflare=True)
        self.assertIn("**Render** hosts the app", render)
        self.assertIn("sits in front of the app", render)
        self.assertNotIn("Streamlit", render)
        # on Render but not (yet) behind Cloudflare: no claim it is
        bare = disclosures.hosting_lines(host="Render", behind_cloudflare=False)
        self.assertNotIn("in front", bare)
        self.assertNotIn("Streamlit", bare)

    def test_the_website_names_both_until_the_move_is_done(self):
        before = disclosures.hosting_lines(host="", behind_cloudflare=False, moved=False)
        self.assertIn("Streamlit Community Cloud", before)
        self.assertIn("moving to", before)
        self.assertIn("**Render**", before)
        after = disclosures.hosting_lines(host="", behind_cloudflare=False, moved=True)
        self.assertNotIn("Streamlit", after)
        self.assertIn("sits in front of the app", after)
        # a copy still on Community Cloud says so, moved or not
        self.assertNotIn("Render", disclosures.hosting_lines(
            host="Streamlit Community Cloud", behind_cloudflare=False, moved=True))
        about = _read("website", "public", "about.html")
        if disclosures.HOST_MOVED:
            self.assertNotIn("Streamlit Community Cloud", about)
        else:
            self.assertIn("moving to <strong>Render</strong>", about)

    def test_the_about_page_follows_the_copys_host(self):
        # the module as it is now (another test may have reloaded the app's modules)
        mod = importlib.import_module("disclosures")

        def services():
            return dict(mod.SECTIONS)["Services Northwend uses"]
        self.addCleanup(importlib.reload, mod)   # back to this machine's
        env = {k: v for k, v in os.environ.items()
               if k not in ("RENDER", "CLIENT_IP_HEADER", "NORTHWEND_ENV")}
        with unittest.mock.patch.dict(os.environ, {**env, "RENDER": "true",
                                                   "CLIENT_IP_HEADER": "cf-connecting-ip"},
                                      clear=True):
            importlib.reload(mod)
            self.assertIn("**Render** hosts the app", services())
            self.assertIn("sits in front of the app", services())
            self.assertNotIn("Streamlit", services())
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch("settings._on_community_cloud", return_value=True):
            importlib.reload(mod)
            self.assertIn("**Streamlit Community Cloud** hosts the app.", services())
            self.assertNotIn("Render", services())
        for host in ("Render", "Streamlit Community Cloud", ""):
            for cf in (True, False):
                self.assertNotIn("$", mod.hosting_lines(host=host, behind_cloudflare=cf))

    def test_the_drafts_are_written_for_after_the_move(self):
        policy = _read("docs", "legal", "privacy-policy-DRAFT.md")
        self.assertIn("| **Render** | Hosts the app", policy)
        self.assertIn("sits in front of the app", policy)
        # the "publish only after the move" notes go once the move is done
        for text in (policy, _read("docs", "legal", "security-for-advisors-DRAFT.md")):
            if disclosures.HOST_MOVED:
                self.assertNotIn("written for after the move", text)
            else:
                self.assertIn("HOST_MOVED", text)


# --------------------------------------------------------------------------- #
# Cloudflare, the runbook
# --------------------------------------------------------------------------- #
class CloudflareDocTests(unittest.TestCase):

    def test_every_header_is_in_the_rule(self):
        text = _read("docs", "CLOUDFLARE.md")
        for header in ("Strict-Transport-Security", "X-Content-Type-Options",
                       "Referrer-Policy", "Content-Security-Policy", "X-Frame-Options",
                       "Permissions-Policy"):
            self.assertRegex(text, rf"(?m)^\|\s*`{header}`\s*\|", header)
        self.assertIn("`frame-ancestors 'none'`", text)
        self.assertIn("`DENY`", text)
        for word in ("WebSockets", "Email Address Obfuscation", "securityheaders.com",
                     "cf-connecting-ip", "Full (strict)", "Bypass cache", "Rocket Loader",
                     "Web Analytics"):
            self.assertIn(word, text)

    def test_the_app_sends_what_the_website_sends(self):
        # the shared headers have the same values on the app and the website
        text = _read("docs", "CLOUDFLARE.md")
        site = dict(re.findall(r"(?m)^  ([\w-]+): (.+)$", _read("website", "assets", "_headers")))
        for header in ("X-Content-Type-Options", "Referrer-Policy", "Permissions-Policy",
                       "Strict-Transport-Security"):
            self.assertIn(f"| `{header}` | `{site[header]}` |", text, header)


class RunbookMoveTests(unittest.TestCase):

    def test_the_move_checklist_in_order(self):
        text = _read("docs", "RUNBOOK.md")
        self.assertIn("## Move to Render", text)
        page = text.split("## Move to Render", 1)[1].split("\n## ", 1)[0]
        heads = re.findall(r"(?m)^### (\d+)\. (.+)$", page)
        self.assertEqual([int(n) for n, _ in heads], list(range(1, len(heads) + 1)))
        steps = ["Blueprint", "onrender.com", "domain in Render", "Cloudflare",
                 "go.northwend.app", "new address", "old app into a signpost",
                 "real hosts", "delete the old app"]
        self.assertEqual(len(heads), len(steps))
        for (_n, head), word in zip(heads, steps):
            self.assertIn(word, head)
        for word in ("docs/CLOUDFLARE.md", "`MOVED_TO = ", "HOST_MOVED = True",
                     "**Done when** (PLAN step 4)", "restore_check.py", "Uptime check"):
            self.assertIn(word, page)

    def test_the_uptime_check(self):
        text = _read("docs", "RUNBOOK.md")
        self.assertIn("## Uptime check", text)
        page = text.split("## Uptime check", 1)[1].split("\n## ", 1)[0]
        self.assertIn("/_stcore/health", page)
        self.assertIn("https://northwend.app/", page)


class MovedCopyTests(unittest.TestCase):
    """The old Community Cloud app after the move: MOVED_TO and nothing else.
    Its page says where Northwend is now before anything needs a database,
    so every secret can come out of the old app (RUNBOOK, Move to Render)."""

    def test_the_old_copy_needs_no_secrets(self):
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        modules = {n: m for n, m in sys.modules.items()
                   if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                   == REPO}
        self.addCleanup(sys.modules.update, modules)
        keep = {k: v for k, v in os.environ.items()
                if not (k.startswith(("NORTHWEND_", "PORTFOLIO_", "ANTHROPIC_", "RESEND_",
                                      "FINNHUB_")) or k in ("RENDER", "MOVED_TO", "DATABASE_URL",
                                                            "CLIENT_IP_HEADER"))}
        env = {**keep, "NORTHWEND_ENV": "production", "MOVED_TO": "https://go.northwend.app/"}
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        at.query_params["reset"] = "abc"
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch("settings.load_env", lambda *a: {}), \
                unittest.mock.patch("socket.socket.connect", offline):
            at.run()
        self.assertEqual([e.message for e in at.exception], [])
        self.assertEqual([e.value for e in at.error], [])
        self.assertIn("has moved", at.title[0].value)


if __name__ == "__main__":
    unittest.main()
