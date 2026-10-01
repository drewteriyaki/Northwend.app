"""Two-step sign-in (ROADMAP R2, two_step.py): the codes, setup, the lock on
wrong codes, backup codes, remembering a device, turning it off, the admin
reset - and that the key never leaves (export, Admin portal).

    python -m unittest tests.test_two_step        (from the repo root)
"""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import admin  # noqa: E402
import auth  # noqa: E402
import export  # noqa: E402
import manage_users  # noqa: E402
import portfolio  # noqa: E402
import two_step  # noqa: E402

NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)


class TotpMathTests(unittest.TestCase):
    # RFC 6238 appendix B, SHA-1: the secret is the ASCII "12345678901234567890"
    RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    RFC_VECTORS = [(59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"),
                   (1234567890, "89005924"), (2000000000, "69279037"),
                   (20000000000, "65353130")]

    def test_rfc6238_vectors(self):
        for t, want in self.RFC_VECTORS:
            with self.subTest(t=t):
                self.assertEqual(two_step.totp(self.RFC_SECRET, t, digits=8), want)
                # the 6-digit code an app shows is the last six of the same number
                self.assertEqual(two_step.totp(self.RFC_SECRET, t), want[-6:])
                when = datetime.fromtimestamp(t, tz=timezone.utc)
                self.assertEqual(two_step.totp(self.RFC_SECRET, when), want[-6:])

    def test_rfc4226_hotp_vectors(self):
        key = b"12345678901234567890"
        for counter, want in enumerate(["755224", "287082", "359152", "969429", "338314"]):
            self.assertEqual(two_step.hotp(key, counter), want)

    def test_secret_key_and_link(self):
        secret = two_step.new_secret()
        self.assertRegex(secret, r"^[A-Z2-7]{32}$")
        self.assertNotEqual(secret, two_step.new_secret())
        self.assertEqual(two_step.grouped("ABCDEFGHIJ"), "ABCD EFGH IJ")
        # typed in groups, or lower case, still works
        self.assertEqual(two_step.totp(two_step.grouped(secret).lower(), NOW),
                         two_step.totp(secret, NOW))
        uri = two_step.otpauth_uri(secret, "sam@example.com")
        self.assertTrue(uri.startswith("otpauth://totp/Northwend:sam@example.com?secret="))
        for part in (f"secret={secret}", "issuer=Northwend", "algorithm=SHA1", "digits=6",
                     "period=30"):
            self.assertIn(part, uri)
        self.assertIn("issuer=Northwend%20staging",
                      two_step.otpauth_uri(secret, "a b", "Northwend staging"))


class TwoStepTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_two_step_")
        self.db = os.path.join(self.dir, "test.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.conn = portfolio.connect(self.db)
        self.uid = auth.create_user(self.conn, "sam", "sampass12")

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _turn_on(self, uid=None, now=NOW):
        uid = uid or self.uid
        secret = two_step.new_secret()
        res = two_step.enable(self.conn, uid, secret, two_step.totp(secret, now), now=now)
        self.assertTrue(res["ok"], res["error"])
        return secret, res["backup_codes"]

    def test_setup_only_turns_on_with_the_apps_first_code(self):
        secret = two_step.new_secret()
        bad = two_step.enable(self.conn, self.uid, secret, "000000", now=NOW)
        if two_step.totp(secret, NOW) != "000000":
            self.assertFalse(bad["ok"])
            self.assertFalse(two_step.status(self.conn, self.uid)["on"])
        self.assertFalse(two_step.enable(self.conn, self.uid, "not base32!", "123456",
                                         now=NOW)["ok"])
        res = two_step.enable(self.conn, self.uid, secret, two_step.totp(secret, NOW), now=NOW)
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["backup_codes"]), two_step.BACKUP_CODES)
        self.assertEqual(len(set(res["backup_codes"])), two_step.BACKUP_CODES)
        for code in res["backup_codes"]:
            self.assertRegex(code, r"^[a-z2-9]{4}-[a-z2-9]{4}$")
        s = two_step.status(self.conn, self.uid)
        self.assertEqual((s["on"], s["required"], s["backup_left"]), (True, False, 8))
        # backup codes are stored only as hashes
        row = self.conn.execute("SELECT * FROM two_step WHERE user_id = ?", (self.uid,)).fetchone()
        for code in res["backup_codes"]:
            self.assertNotIn(code, str(dict(row)))
            self.assertNotIn(code.replace("-", ""), str(dict(row)))

    def test_codes_window_replay_and_backup_codes(self):
        secret, backups = self._turn_on()
        later = NOW + timedelta(minutes=5)
        # the code used to turn it on can't be used again
        self.assertFalse(two_step.verify(self.conn, self.uid, two_step.totp(secret, NOW),
                                         now=NOW)["ok"])
        self.assertTrue(two_step.verify(self.conn, self.uid, two_step.totp(secret, later),
                                        now=later)["ok"])
        self.assertFalse(two_step.verify(self.conn, self.uid, two_step.totp(secret, later),
                                         now=later)["ok"])   # replay
        # a phone 30 seconds out still works; two steps out doesn't
        t = later + timedelta(minutes=5)
        self.assertTrue(two_step.verify(self.conn, self.uid,
                                        two_step.totp(secret, t - timedelta(seconds=30)),
                                        now=t)["ok"])
        t2 = t + timedelta(minutes=5)
        far = two_step.totp(secret, t2 + timedelta(seconds=61))
        if far not in {two_step.totp(secret, t2 + timedelta(seconds=d)) for d in (-30, 0, 30)}:
            self.assertFalse(two_step.verify(self.conn, self.uid, far, now=t2)["ok"])
        two_step.unlock(self.conn, self.uid)
        # spaces in the typed code are fine
        t3 = t2 + timedelta(minutes=5)
        c = two_step.totp(secret, t3)
        self.assertTrue(two_step.verify(self.conn, self.uid, f" {c[:3]} {c[3:]} ", now=t3)["ok"])
        # a backup code works once, in any case and with or without its dash
        res = two_step.verify(self.conn, self.uid, backups[0].upper().replace("-", ""), now=t3)
        self.assertEqual((res["ok"], res["used_backup"], res["backup_left"]), (True, True, 7))
        self.assertFalse(two_step.verify(self.conn, self.uid, backups[0], now=t3)["ok"])
        self.assertEqual(two_step.status(self.conn, self.uid)["backup_left"], 7)

    def test_wrong_codes_lock_like_wrong_passwords(self):
        secret, backups = self._turn_on()
        t = NOW + timedelta(minutes=2)
        right = two_step.totp(secret, t)
        wrong = "000000" if right != "000000" else "111111"
        for i in range(auth.MAX_FAILED_LOGINS - 1):
            res = two_step.verify(self.conn, self.uid, wrong, now=t)
            self.assertFalse(res["ok"])
            self.assertEqual(res["locked_minutes"], 0)
        res = two_step.verify(self.conn, self.uid, wrong, now=t)
        self.assertEqual(res["locked_minutes"], auth.LOCKOUT_MINUTES)
        # locked: even the right code or a backup code is refused, without counting
        self.assertEqual(two_step.verify(self.conn, self.uid, right, now=t)["locked_minutes"],
                         auth.LOCKOUT_MINUTES)
        self.assertFalse(two_step.verify(self.conn, self.uid, backups[1], now=t)["ok"])
        self.assertTrue(admin.list_accounts(self.conn, now=t)[0]["locked"])
        # the password lock is separate
        self.assertEqual(auth.attempt_login(self.conn, "sam", "sampass12", now=t)["user_id"],
                         self.uid)
        # it runs out, or the admin's Unlock clears it
        after = t + timedelta(minutes=auth.LOCKOUT_MINUTES + 1)
        self.assertTrue(two_step.verify(self.conn, self.uid, two_step.totp(secret, after),
                                        now=after)["ok"])
        for _ in range(auth.MAX_FAILED_LOGINS):
            two_step.verify(self.conn, self.uid, wrong, now=after)
        self.assertTrue(two_step.unlock(self.conn, self.uid))
        self.assertTrue(two_step.verify(self.conn, self.uid, backups[1], now=after)["ok"])

    def test_required_for_advisors_and_admins(self):
        self.assertFalse(two_step.status(self.conn, self.uid)["required"])
        auth.set_advisor(self.conn, "sam", True)
        self.assertTrue(two_step.status(self.conn, self.uid)["required"])
        auth.set_advisor(self.conn, "sam", False)
        boss = auth.create_user(self.conn, "boss", "bosspass1")
        admin.set_admin(self.conn, "boss", True)
        self.assertTrue(two_step.status(self.conn, boss)["required"])
        listed = auth.create_user(self.conn, "listed", "listedpass1")
        with mock.patch.dict(os.environ, {"NORTHWEND_ADMINS": "listed"}):
            self.assertTrue(two_step.status(self.conn, listed)["required"])
        self.assertEqual(two_step.status(self.conn, 9999)["on"], False)

    def test_turning_off_needs_a_code_or_the_password(self):
        secret, backups = self._turn_on()
        t = NOW + timedelta(minutes=3)
        res = two_step.disable(self.conn, self.uid, "wrong-password", now=t)
        self.assertFalse(res["ok"])
        self.assertTrue(two_step.status(self.conn, self.uid)["on"])
        # by password
        self.assertTrue(two_step.disable(self.conn, self.uid, "sampass12", now=t)["ok"])
        self.assertFalse(two_step.status(self.conn, self.uid)["on"])
        self.assertFalse(two_step.disable(self.conn, self.uid, "sampass12", now=t)["ok"])
        # by a code from the app
        secret, _ = self._turn_on(now=t)
        t2 = t + timedelta(minutes=1)
        self.assertTrue(two_step.disable(self.conn, self.uid, two_step.totp(secret, t2),
                                         now=t2)["ok"])
        # advisors keep it on
        self._turn_on(now=t2)
        auth.set_advisor(self.conn, "sam", True)
        self.assertIn("keep", two_step.disable(self.conn, self.uid, "sampass12", now=t2)["error"])
        self.assertTrue(two_step.status(self.conn, self.uid)["on"])

    def test_wrong_answers_count_toward_the_password_lock(self):
        self._turn_on()
        t = NOW + timedelta(minutes=3)
        for _ in range(auth.MAX_FAILED_LOGINS):
            two_step.disable(self.conn, self.uid, "123456" if _ % 2 else "guess", now=t)
        # locked: the right password is refused too
        res = two_step.disable(self.conn, self.uid, "sampass12", now=t)
        self.assertIn("Too many", res["error"])
        self.assertTrue(two_step.status(self.conn, self.uid)["on"])
        self.assertTrue(auth.attempt_login(self.conn, "sam", "sampass12", now=t)["locked_minutes"])

    def test_new_backup_codes_replace_the_old_ones(self):
        secret, old = self._turn_on()
        t = NOW + timedelta(minutes=1)
        self.assertFalse(two_step.new_backup_codes(self.conn, self.uid, "nope", now=t)["ok"])
        res = two_step.new_backup_codes(self.conn, self.uid, old[0], now=t)  # a backup code works
        self.assertTrue(res["ok"])
        self.assertFalse(set(res["backup_codes"]) & set(old))
        self.assertFalse(two_step.verify(self.conn, self.uid, old[1], now=t)["ok"])
        self.assertTrue(two_step.verify(self.conn, self.uid, res["backup_codes"][0], now=t)["ok"])

    def test_remember_this_device_rides_on_the_stay_signed_in_session(self):
        secret, _ = self._turn_on()
        token = auth.create_session(self.conn, self.uid, now=NOW)
        other = auth.create_session(self.conn, self.uid, now=NOW)
        self.assertFalse(two_step.device_remembered(self.conn, token, self.uid, now=NOW))
        self.assertFalse(two_step.remember_device(self.conn, None, self.uid, now=NOW))
        self.assertTrue(two_step.remember_device(self.conn, token, self.uid, now=NOW))
        self.assertTrue(two_step.device_remembered(self.conn, token, self.uid, now=NOW))
        self.assertFalse(two_step.device_remembered(self.conn, other, self.uid, now=NOW))
        # someone else's session can't be marked, nor counts for this account
        eve = auth.create_user(self.conn, "eve", "evepass12")
        self.assertFalse(two_step.remember_device(self.conn, token, eve, now=NOW))
        self.assertFalse(two_step.device_remembered(self.conn, token, eve, now=NOW))
        # it lasts REMEMBER_DAYS (the session itself as long)
        soon = NOW + timedelta(days=two_step.REMEMBER_DAYS - 1)
        self.assertTrue(two_step.device_remembered(self.conn, token, self.uid, now=soon))
        gone = NOW + timedelta(days=two_step.REMEMBER_DAYS, minutes=1)
        self.assertFalse(two_step.device_remembered(self.conn, token, self.uid, now=gone))
        # setting it up again forgets every device
        self._turn_on(now=NOW + timedelta(minutes=1))
        self.assertFalse(two_step.device_remembered(self.conn, token, self.uid, now=NOW))
        # and so does a new password (every session ends)
        two_step.remember_device(self.conn, token, self.uid, now=NOW)
        auth.set_password(self.conn, "sam", "newpass123")
        self.assertFalse(two_step.device_remembered(self.conn, token, self.uid, now=NOW))

    def test_admin_reset_turns_it_off_and_signs_out_everywhere(self):
        secret, _ = self._turn_on()
        before = two_step.status(self.conn, self.uid)["stamp"]
        token = auth.create_session(self.conn, self.uid)
        two_step.remember_device(self.conn, token, self.uid)
        for _ in range(auth.MAX_FAILED_LOGINS):
            two_step.verify(self.conn, self.uid, "abcdefgh")
        self.assertTrue(two_step.reset(self.conn, self.uid))
        s = two_step.status(self.conn, self.uid)
        self.assertEqual((s["on"], s["stamp"]), (False, None))
        self.assertIsNone(auth.session_user(self.conn, token))
        self.assertFalse(two_step.reset(self.conn, self.uid))
        # set up again: a different stamp, so open tabs notice
        self._turn_on(now=NOW + timedelta(minutes=1))
        self.assertNotEqual(two_step.status(self.conn, self.uid)["stamp"], before)
        self.assertTrue(two_step.verify(self.conn, self.uid, "abcdefgh")["ok"] is False)

    def test_manage_users_reset_two_step(self):
        self._turn_on()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(manage_users.main(["--db", self.db, "reset-two-step", "sam"]), 0)
            self.assertEqual(manage_users.main(["--db", self.db, "reset-two-step", "nobody"]), 1)
        self.assertIn("reset", out.getvalue())
        self.assertFalse(two_step.is_on(self.conn, self.uid))

    def test_the_key_never_leaves(self):
        secret, backups = self._turn_on()
        z = zipfile.ZipFile(io.BytesIO(export.export_zip(self.conn, self.uid)))
        files = {n: z.read(n).decode("utf-8") for n in z.namelist()}
        self.assertIn("two_step_sign_in.csv", files)
        self.assertIn("enabled_at", files["two_step_sign_in.csv"])
        everything = "".join(files.values())
        row = self.conn.execute("SELECT backup_codes_hash FROM two_step WHERE user_id = ?",
                                (self.uid,)).fetchone()
        for text in (secret, row["backup_codes_hash"].split()[0], "totp_secret", *backups):
            self.assertNotIn(text, everything)
        # the Admin portal sees on/off only
        acct = admin.list_accounts(self.conn)[0]
        self.assertIs(acct["two_step"], True)
        self.assertNotIn(secret, str(acct))

    def test_deleting_the_account_removes_it(self):
        self._turn_on()
        boss = auth.create_user(self.conn, "boss", "bosspass1")
        admin.set_admin(self.conn, "boss", True)
        self.assertTrue(admin.delete_account(self.conn, self.uid, by=boss)["ok"])
        self.assertIsNone(self.conn.execute("SELECT 1 FROM two_step").fetchone())


class SchemaTests(unittest.TestCase):
    def test_both_schemas_have_two_step(self):
        for name in ("schema.sql", "schema_pg.sql"):
            with open(os.path.join(REPO, name), encoding="utf-8") as fh:
                text = fh.read()
            with self.subTest(name):
                self.assertIn("CREATE TABLE IF NOT EXISTS two_step", text)
                self.assertIn("two_step_until", text)

    def test_old_databases_get_the_remember_column(self):
        d = tempfile.mkdtemp(prefix="pt_two_step_old_")
        try:
            import sqlite3
            db = os.path.join(d, "old.db")
            raw = sqlite3.connect(db)
            raw.execute("CREATE TABLE login_sessions (token_hash TEXT PRIMARY KEY, user_id "
                        "INTEGER NOT NULL, created_at TEXT, expires_at TEXT NOT NULL)")
            raw.commit()
            raw.close()
            portfolio._SCHEMA_READY.discard(os.path.abspath(db))
            conn = portfolio.connect(db)
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(login_sessions)")}
            conn.close()
            self.assertIn("two_step_until", cols)
        finally:
            shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
