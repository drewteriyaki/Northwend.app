"""Hardening 1b (PLAN step 1): signing everyone out (1b.2, audit X5), the
admin action log (1b.3, audit X2, decision D8), password hashing at 600,000
iterations (1b.7, audit 1.1b) and slow backup-code hashes (1b.8, 1.1e).

    python -m unittest tests.test_sign_out_and_log        (from the repo root)
"""

import contextlib
import hashlib
import io
import os
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import admin  # noqa: E402
import admin_log  # noqa: E402
import auth  # noqa: E402
import manage_users  # noqa: E402
import portfolio  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
NOW = datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc)


def _no_override():
    """The real counts: no test-only NORTHWEND_PBKDF2_ITERATIONS."""
    env = {k: v for k, v in os.environ.items() if k != auth.ITERATIONS_SETTING}
    return unittest.mock.patch.dict(os.environ, env, clear=True)


class _DB(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pt_1b_")
        self.db = os.path.join(self.tmp, "t.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.conn = portfolio.connect(self.db)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def one(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()


# --------------------------------------------------------------------------- #
# 1b.2 - sign everyone out
# --------------------------------------------------------------------------- #
class SessionGenTests(_DB):

    def test_sign_out_everyone_moves_every_logins_number_and_ends_saved_sign_ins(self):
        a = auth.create_user(self.conn, "ann", PW)
        b = auth.create_user(self.conn, "bob", PW)
        before = {u: auth.session_gen(self.conn, u) for u in (a, b)}
        self.assertEqual(before[a], "0.0")
        auth.create_session(self.conn, a)
        tok = auth.create_session(self.conn, b)
        self.assertEqual(auth.sign_out_everyone(self.conn), 2)
        for u in (a, b):
            self.assertNotEqual(auth.session_gen(self.conn, u), before[u])
        self.assertIsNone(auth.session_user(self.conn, tok))
        self.assertEqual(self.one("SELECT COUNT(*) AS n FROM login_sessions")["n"], 0)
        once = auth.session_gen(self.conn, a)
        auth.sign_out_everyone(self.conn)                     # again: moves again
        self.assertNotEqual(auth.session_gen(self.conn, a), once)
        self.assertEqual(self.one("SELECT number FROM app_state WHERE name = ?",
                                  (auth.EVERYONE_GEN,))["number"], 2)

    def test_other_devices_moves_only_that_logins_number(self):
        a = auth.create_user(self.conn, "ann", PW)
        b = auth.create_user(self.conn, "bob", PW)
        here = auth.create_session(self.conn, a)
        auth.create_session(self.conn, a)
        b_before = auth.session_gen(self.conn, b)
        a_before = auth.session_gen(self.conn, a)
        self.assertEqual(auth.end_other_sessions(self.conn, a, here), 1)
        self.assertNotEqual(auth.session_gen(self.conn, a), a_before)
        self.assertEqual(auth.session_gen(self.conn, b), b_before)
        self.assertEqual(auth.session_user(self.conn, here)[0], a)   # this browser stays

    def test_the_gates_row_carries_the_same_number(self):
        a = auth.create_user(self.conn, "ann", PW)
        auth.sign_out_everyone(self.conn)
        _, row = two_step.status_and_login(self.conn, a)
        self.assertEqual(auth.session_gen_of(row), auth.session_gen(self.conn, a))
        self.assertEqual(auth.session_gen_of(row), "0.1")
        self.assertIsNone(auth.session_gen(self.conn, 9999))

    def test_the_password_stamp_comes_from_the_salt(self):
        a = auth.create_user(self.conn, "ann", PW)
        stamp = auth.password_stamp(self.conn, a)
        auth.set_password(self.conn, "ann", "another-pass1")
        self.assertNotEqual(auth.password_stamp(self.conn, a), stamp)

    def test_the_command(self):
        a = auth.create_user(self.conn, "ann", PW)
        auth.create_session(self.conn, a)
        before = auth.session_gen(self.conn, a)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(manage_users.main(["--db", self.db, "sign-out-all"]), 0)
        self.assertIn("Signed everyone out", out.getvalue())
        self.assertNotEqual(auth.session_gen(self.conn, a), before)
        row = admin_log.recent(self.conn)[0]
        self.assertEqual((row["action"], row["admin"], row["target"]),
                         ("sign_out_all", None, None))
        self.assertEqual(row["detail"], "command line: 1 saved sign-in ended")


class SignOutAppTests(unittest.TestCase):
    """An open tab: after the number moves, its next run lands on sign-in."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="pt_1b_app_")
        cls.db = os.path.join(cls.tmp, "app.db")
        c = portfolio.connect(cls.db)
        try:
            cls.alice = auth.create_user(c, "alice", PW)
            cls.ann = auth.create_user(c, "ann", PW)            # an admin
            secret = two_step.new_secret()
            two_step.enable(c, cls.ann, secret, two_step.totp(secret))
            cls.ann_ok = f"{cls.ann}:{two_step.status(c, cls.ann)['stamp']}"
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _env(self, admins=""):
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "ANTHROPIC_API_KEY", "RESEND_API_KEY",
                            "NORTHWEND_ADMINS")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1")
        if admins:
            env["NORTHWEND_ADMINS"] = admins
        return unittest.mock.patch.dict(os.environ, env, clear=True)

    def _tab(self, user_id, username, page=None, admins="", **state):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        at.session_state["user_id"] = user_id
        at.session_state["username"] = username
        for k, v in state.items():
            at.session_state[k] = v
        if page:
            at.query_params["page"] = page
        return self._run(at, admins)

    def _run(self, at, admins=""):
        with self._env(admins):
            at.run()
        self.assertEqual([e.message for e in at.exception], [])
        return at

    @staticmethod
    def _signed_in(at):
        return "user_id" in at.session_state and at.session_state["user_id"] is not None

    @staticmethod
    def _text(at):
        return " ".join([m.value for m in at.markdown]
                        + [str(e.value) for k in ("error", "info", "success", "caption")
                           for e in getattr(at, k)])

    def _conn(self):
        return portfolio.connect(self.db)

    def test_an_open_tab_lands_on_sign_in_after_everyone_is_signed_out(self):
        at = self._tab(self.alice, "alice", "home")
        self.assertTrue(self._signed_in(at))
        self._run(at)                                    # still in on the next click
        self.assertTrue(self._signed_in(at))
        c = self._conn()
        try:
            auth.sign_out_everyone(c)
        finally:
            c.close()
        self._run(at)
        self.assertFalse(self._signed_in(at))
        self.assertIn("login_user", [t.key for t in at.text_input])
        self.assertIn("You've been signed out", self._text(at))
        # signing in again works, and the new tab stays in
        at.text_input(key="login_user").input("alice")
        at.text_input(key="login_pw").input(PW)
        at.button(key="FormSubmitter:login_form-Log in").click()
        self._run(at)
        self._run(at)
        self.assertEqual(at.session_state["user_id"], self.alice)

    def test_sign_out_other_devices_closes_the_other_tab_not_this_one(self):
        other = self._tab(self.alice, "alice", "home")
        here = self._tab(self.alice, "alice", "account")
        here.button(key="acct_sign_out_others").click()
        self._run(here)
        self.assertTrue(self._signed_in(here))
        self.assertRegex(self._text(here), r"Signed out (anywhere else|\d+ other devices?, and "
                                           r"any other open tabs)")
        self._run(here)
        self.assertTrue(self._signed_in(here))           # this tab noted the new number
        self._run(other)
        self.assertFalse(self._signed_in(other))

    def test_the_admins_button_signs_everyone_out_the_admin_too(self):
        alice_tab = self._tab(self.alice, "alice", "home")
        at = self._tab(self.ann, "ann", "admin", admins="ann", two_step_ok=self.ann_ok)
        self.assertIn("admin_sign_out_all", [b.key for b in at.button])
        at.button(key="admin_sign_out_all").click()         # without the tick: nothing
        self._run(at, "ann")
        self.assertTrue(self._signed_in(at))
        self.assertIn("Tick the box first", self._text(at))
        at.checkbox(key="admin_sign_out_all_ok").check()
        at.button(key="admin_sign_out_all").click()
        self._run(at, "ann")
        # the admin's own tab is signed out too - simplest, and right in an emergency
        self.assertFalse(self._signed_in(at))
        self._run(alice_tab)
        self.assertFalse(self._signed_in(alice_tab))
        c = self._conn()
        try:
            rows = [r for r in admin_log.recent(c) if r["action"] == "sign_out_all"]
        finally:
            c.close()
        self.assertEqual(rows[0]["admin"], "ann")

    def test_admin_actions_are_logged_and_shown_on_system(self):
        c = self._conn()
        try:
            bob = auth.create_user(c, "bob.nomail", PW)
        finally:
            c.close()
        at = self._tab(self.ann, "ann", "admin", admins="ann", two_step_ok=self.ann_ok)
        at.selectbox(key="admin_pick").set_value(bob)
        self._run(at, "ann")
        at.button(key="admin_temp_pw").click()
        self._run(at, "ann")
        at.button(key="admin_ai").click()
        self._run(at, "ann")
        c = self._conn()
        try:
            rows = admin_log.recent(c)
        finally:
            c.close()
        mine = [(r["action"], r["admin"], r["target"]) for r in rows]
        self.assertIn(("temp_password", "ann", "bob.nomail"), mine)
        self.assertIn(("ai_limits", "ann", "bob.nomail"), mine)
        # never the temporary password itself
        shown = at.session_state["admin_temp"][1]
        self.assertFalse(any(shown in (r["detail"] or "") for r in rows))
        # the System panel lists them
        self.assertIn("Admin actions", self._text(at))
        frames = [df.value for df in at.dataframe]
        self.assertTrue(any("Action" in f.columns and "temp password" in set(f["Action"])
                            for f in frames))


# --------------------------------------------------------------------------- #
# 1b.3 - the admin action log
# --------------------------------------------------------------------------- #
class AdminLogTests(_DB):

    def test_add_read_and_the_fixed_words(self):
        boss = auth.create_user(self.conn, "boss", PW)
        sam = auth.create_user(self.conn, "sam", PW)
        admin_log.add(self.conn, boss, "temp_password", sam, "shown to the admin once", now=NOW)
        admin_log.add(self.conn, None, "make_admin", boss, now=NOW + timedelta(minutes=1))
        rows = admin_log.recent(self.conn)
        self.assertEqual([r["action"] for r in rows], ["make_admin", "temp_password"])
        self.assertEqual((rows[1]["admin"], rows[1]["target"], rows[1]["at"]),
                         ("boss", "sam", "2026-10-06 12:00:00"))
        self.assertEqual(rows[0]["detail"], "command line")
        with self.assertRaises(ValueError):
            admin_log.add(self.conn, boss, "looked_at_holdings", sam)
        for i in range(admin_log.SHOWN + 5):
            admin_log.add(self.conn, boss, "clear_cache", commit=False)
        self.conn.commit()
        self.assertEqual(len(admin_log.recent(self.conn)), admin_log.SHOWN)

    def test_prune_keeps_a_year(self):
        boss = auth.create_user(self.conn, "boss", PW)
        admin_log.add(self.conn, boss, "unlock", now=NOW - timedelta(days=366))
        admin_log.add(self.conn, boss, "unlock", now=NOW - timedelta(days=364))
        self.assertEqual(admin_log.prune(self.conn, older_than_days=365, now=NOW), 1)
        self.assertEqual(len(admin_log.recent(self.conn)), 1)
        self.assertEqual(admin_log.prune(self.conn, now=NOW), 0)

    def test_deleting_an_account_clears_its_id_and_keeps_the_row(self):
        self.assertEqual(admin.ACCOUNT_REFERENCES["admin_log"], ("admin_id", "target_id"))
        self.assertNotIn("admin_log", admin.ACCOUNT_TABLES)
        boss = auth.create_user(self.conn, "boss", PW)
        admin.set_admin(self.conn, "boss", True)
        sam = auth.create_user(self.conn, "sam", PW)
        admin_log.add(self.conn, boss, "reset_password", sam)
        self.assertTrue(admin.delete_account(self.conn, sam, by=boss)["ok"])
        row = self.one("SELECT admin_id, target_id, action FROM admin_log")
        self.assertEqual((row["admin_id"], row["target_id"], row["action"]),
                         (boss, None, "reset_password"))

    def test_append_only_in_code(self):
        """No UPDATE or DELETE on admin_log anywhere but admin_log.prune (the
        year's retention). admin.delete_account clears ids through
        ACCOUNT_REFERENCES, which never names the table in SQL."""
        bad = re.compile(r"(UPDATE\s+admin_log|DELETE\s+FROM\s+admin_log|DROP\s+TABLE\s+"
                         r"(IF\s+EXISTS\s+)?admin_log|TRUNCATE\s+admin_log)", re.I)
        hits = []
        for root, dirs, files in os.walk(REPO):
            dirs[:] = [d for d in dirs if d not in (".git", "tests", "venv", ".venv",
                                                    "node_modules", "website", ".claude")]
            for name in files:
                if not name.endswith(".py"):
                    continue
                path = os.path.join(root, name)
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                for m in bad.finditer(text):
                    hits.append((os.path.relpath(path, REPO), m.group(0)))
        self.assertEqual(hits, [("admin_log.py", "DELETE FROM admin_log")])
        with open(os.path.join(REPO, "admin_log.py"), encoding="utf-8") as fh:
            src = fh.read()
        prune = src[src.index("def prune("):]
        self.assertIn("DELETE FROM admin_log", prune)
        self.assertEqual(src.count("DELETE FROM admin_log"), 1)
        self.assertEqual([n for n in dir(admin_log) if callable(getattr(admin_log, n))
                          and not n.startswith("_") and n not in ("datetime", "timedelta",
                                                                  "timezone")],
                         ["add", "prune", "recent"])

    def test_every_admin_action_in_the_portal_goes_through_the_log(self):
        with open(os.path.join(REPO, "views", "admin.py"), encoding="utf-8") as fh:
            src = fh.read()
        # every on_click / on_change callback on the page is an _admin_ action...
        callbacks = set(re.findall(r"on_(?:click|change)=(_admin_\w+)", src))
        self.assertGreater(len(callbacks), 15)
        for name in callbacks:
            body = src[src.index(f"def {name}("):]
            body = body[:body.index("\ndef ", 1)] if "\ndef " in body[1:] else body
            self.assertIn("_admin_do(", body, name)
        # ...and each names a fixed action word (the second argument is required)
        import ast
        calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "_admin_do"]
        self.assertGreater(len(calls), 15)
        for call in calls:
            self.assertGreaterEqual(len(call.args), 2, ast.unparse(call)[:60])
            word = call.args[1]
            words = ([word.body, word.orelse] if isinstance(word, ast.IfExp) else [word])
            for w in words:
                self.assertIsInstance(w, ast.Constant, ast.unparse(call)[:60])
                self.assertIn(w.value, admin_log.ACTIONS)

    def test_the_command_line_logs_its_changes(self):
        sam = auth.create_user(self.conn, "sam", PW)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            for args in (["make-advisor", "sam"], ["remove-advisor", "sam"],
                         ["make-admin", "sam"], ["remove-admin", "sam"],
                         ["ai-unlimited", "sam"], ["reset-two-step", "sam"]):
                self.assertEqual(manage_users.main(["--db", self.db, *args]), 0, args)
        rows = admin_log.recent(self.conn)
        self.assertEqual([r["action"] for r in reversed(rows)],
                         ["approve_advisor", "remove_advisor", "make_admin", "remove_admin",
                          "ai_limits", "reset_two_step"])
        self.assertTrue(all(r["admin"] is None and r["target"] == "sam" and
                            r["detail"].startswith("command line") for r in rows))
        self.assertEqual(sam, auth.get_user_id(self.conn, "sam"))

    def test_the_disclosures_say_so(self):
        import disclosures
        text = " ".join(" ".join(str(part) for part in s) if isinstance(s, (tuple, list))
                        else str(s) for s in disclosures.SECTIONS)
        text = " ".join(text.split())
        self.assertIn("temporary password to help its owner back", text)
        self.assertIn("every action they take on accounts is recorded", text)
        with open(os.path.join(REPO, "docs", "legal", "privacy-policy-DRAFT.md"),
                  encoding="utf-8") as fh:
            privacy = " ".join(fh.read().split())
        self.assertIn("reset the login without email", privacy)
        self.assertIn("admin action log", privacy)


# --------------------------------------------------------------------------- #
# 1b.7 - password hashing
# --------------------------------------------------------------------------- #
class PasswordHashTests(_DB):

    def _row(self, uid):
        return self.one("SELECT password_hash, password_salt, password_iterations FROM users "
                        "WHERE id = ?", (uid,))

    def test_a_new_password_uses_600k(self):
        self.assertEqual(auth.PBKDF2_ITERATIONS, 600_000)
        with _no_override():
            self.assertEqual(auth.iterations(), 600_000)
            uid = auth.create_user(self.conn, "ann", PW)
            row = self._row(uid)
            self.assertEqual(row["password_iterations"], 600_000)
            self.assertEqual(row["password_hash"], hashlib.pbkdf2_hmac(
                "sha256", PW.encode(), bytes.fromhex(row["password_salt"]), 600_000).hex())
            auth.set_password(self.conn, "ann", "another-pass1")
            self.assertEqual(self._row(uid)["password_iterations"], 600_000)

    def test_an_old_count_still_verifies_and_is_upgraded(self):
        uid = auth.create_user(self.conn, "ann", PW)
        salt = os.urandom(16)
        old = hashlib.pbkdf2_hmac("sha256", PW.encode(), salt, auth.LEGACY_ITERATIONS).hex()
        self.conn.execute("UPDATE users SET password_hash = ?, password_salt = ?, "
                          "password_iterations = ? WHERE id = ?",
                          (old, salt.hex(), auth.LEGACY_ITERATIONS, uid))
        self.conn.commit()
        stamp = auth.password_stamp(self.conn, uid)
        with _no_override():
            # a wrong password: nothing changes
            self.assertIsNone(auth.verify_login(self.conn, "ann", "wrong-password"))
            self.assertEqual(self._row(uid)["password_iterations"], auth.LEGACY_ITERATIONS)
            self.assertEqual(self._row(uid)["password_hash"], old)
            # the right one: in, and re-made at today's count with the same salt
            self.assertEqual(auth.attempt_login(self.conn, "ann", PW)["user_id"], uid)
            row = self._row(uid)
            self.assertEqual(row["password_iterations"], 600_000)
            self.assertNotEqual(row["password_hash"], old)
            self.assertEqual(row["password_salt"], salt.hex())
            # the stamp is the same, so the person's other open tabs stay open
            self.assertEqual(auth.password_stamp(self.conn, uid), stamp)
            self.assertEqual(auth.verify_login(self.conn, "ann", PW), uid)
            self.assertIsNone(auth.verify_login(self.conn, "ann", "wrong-password"))

    def test_rows_from_before_get_the_old_count(self):
        """The back-fill: an old users table without the column gets 200,000."""
        path = os.path.join(self.tmp, "old.db")
        import sqlite3
        raw = sqlite3.connect(path)
        raw.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT "
                    "NOT NULL UNIQUE, password_hash TEXT NOT NULL, password_salt TEXT NOT NULL, "
                    "created_at TEXT NOT NULL DEFAULT (datetime('now')))")
        salt = os.urandom(16)
        raw.execute("INSERT INTO users (username, password_hash, password_salt) VALUES (?, ?, ?)",
                    ("old", hashlib.pbkdf2_hmac("sha256", PW.encode(), salt, 200_000).hex(),
                     salt.hex()))
        raw.commit()
        raw.close()
        portfolio._SCHEMA_READY.discard(os.path.abspath(path))
        c = portfolio.connect(path)
        try:
            row = c.execute("SELECT password_iterations, session_gen FROM users").fetchone()
            self.assertEqual((row["password_iterations"], row["session_gen"]), (200_000, 0))
            self.assertIsNotNone(auth.verify_login(c, "old", PW))
        finally:
            c.close()

    def test_unknown_usernames_hash_at_todays_count(self):
        seen = []
        real = hashlib.pbkdf2_hmac

        def spy(name, pw, salt, n, *a):
            seen.append((salt, n))
            return real(name, pw, salt, 1)
        with _no_override(), unittest.mock.patch.object(auth.hashlib, "pbkdf2_hmac", spy):
            self.assertIsNone(auth.verify_login(self.conn, "nobody", PW))
        self.assertEqual(seen, [(auth._DUMMY_SALT, 600_000)])

    def test_the_test_override_is_ignored_on_a_hosted_copy(self):
        with unittest.mock.patch.dict(os.environ, {auth.ITERATIONS_SETTING: "1000"}):
            self.assertEqual(auth.iterations(), 1000)
            self.assertEqual(auth.iterations(two_step.BACKUP_ITERATIONS), 1000)
            with unittest.mock.patch.dict(os.environ, {"NORTHWEND_ENV": "production"}):
                self.assertEqual(auth.iterations(), 600_000)
        with unittest.mock.patch.dict(os.environ, {auth.ITERATIONS_SETTING: "9000000"}):
            self.assertEqual(auth.iterations(), 600_000)      # only ever lower


# --------------------------------------------------------------------------- #
# 1b.8 - backup codes
# --------------------------------------------------------------------------- #
class BackupCodeTests(_DB):

    def setUp(self):
        super().setUp()
        self.uid = auth.create_user(self.conn, "sam", PW)
        self.secret = two_step.new_secret()
        res = two_step.enable(self.conn, self.uid, self.secret, two_step.totp(self.secret, NOW),
                              now=NOW)
        self.codes = res["backup_codes"]

    def _stored(self):
        return self.one("SELECT backup_codes_hash FROM two_step WHERE user_id = ?",
                        (self.uid,))["backup_codes_hash"].split()

    def test_new_codes_are_slow_hashes(self):
        stored = self._stored()
        self.assertEqual(len(stored), two_step.BACKUP_CODES)
        for entry in stored:
            self.assertRegex(entry, r"^p2\$\d+\$[0-9a-f]{32}\$[0-9a-f]{64}$")
        self.assertEqual(len({e.split("$")[2] for e in stored}), 1)   # one salt per set
        for code in self.codes:
            self.assertNotIn(two_step._backup_hash(self.uid, code), stored)
        with _no_override():
            _, hashes = two_step._new_backup_codes(self.uid)
        self.assertTrue(hashes.startswith(f"p2${two_step.BACKUP_ITERATIONS}$"))
        later = NOW + timedelta(minutes=5)
        self.assertTrue(two_step.verify(self.conn, self.uid, self.codes[0], now=later)["ok"])
        self.assertEqual(len(self._stored()), two_step.BACKUP_CODES - 1)
        again = two_step.verify(self.conn, self.uid, self.codes[0], now=later)  # used up
        self.assertFalse(again["ok"])

    def test_old_sha256_codes_still_work_and_go_on_use_or_regenerate(self):
        old = ["abcd-efgh", "jkmn-pqrs", "tuvw-xyz2"]
        self.conn.execute("UPDATE two_step SET backup_codes_hash = ? WHERE user_id = ?",
                          (" ".join(two_step._backup_hash(self.uid, c) for c in old), self.uid))
        self.conn.commit()
        later = NOW + timedelta(minutes=5)
        res = two_step.verify(self.conn, self.uid, "ABCD EFGH", now=later)
        self.assertTrue(res["ok"])
        self.assertTrue(res["used_backup"])
        self.assertEqual(res["backup_left"], 2)
        self.assertNotIn(two_step._backup_hash(self.uid, old[0]), self._stored())
        self.assertFalse(two_step.verify(self.conn, self.uid, old[0], now=later)["ok"])
        # an old one also proves it's them (before new codes), and new codes replace them all
        made = two_step.new_backup_codes(self.conn, self.uid, old[1], now=later)
        self.assertTrue(made["ok"])
        self.assertTrue(all(e.startswith("p2$") for e in self._stored()))
        self.assertFalse(two_step.verify(self.conn, self.uid, old[2], now=later)["ok"])
        self.assertTrue(two_step.verify(self.conn, self.uid, made["backup_codes"][3],
                                        now=later)["ok"])

    def test_a_mixed_or_damaged_list(self):
        entries = ["p2$notanumber$00$00", "p2$1000$zz$00", "garbage",
                   two_step._backup_hash(self.uid, "abcd-efgh")]
        self.assertEqual(two_step._backup_match(self.uid, "abcdefgh", entries), entries[3])
        self.assertIsNone(two_step._backup_match(self.uid, "123456", entries))
        self.assertIsNone(two_step._backup_match(self.uid, "zzzzzzzz", entries))


if __name__ == "__main__":
    unittest.main()
