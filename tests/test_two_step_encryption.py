"""Two-step keys encrypted at rest (audit 1.1e, PLAN D14; two_step.py "keys
at rest"): sealed with NORTHWEND_TOTP_KEY when it's set, readable without
it (a local copy), older readable rows sealed at the next good code or by
`manage_users.py encrypt-two-step`, rotation, a wrong key failing closed
calmly, and that neither the keys nor NORTHWEND_TOTP_KEY ever leave
(export, Admin > System, the admin action log, the command's output).

    python -m unittest tests.test_two_step_encryption     (from the repo root)
"""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import time
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from cryptography.fernet import Fernet  # noqa: E402

import admin  # noqa: E402
import admin_log  # noqa: E402
import auth  # noqa: E402
import error_alerts  # noqa: E402
import export  # noqa: E402
import manage_users  # noqa: E402
import portfolio  # noqa: E402
import settings  # noqa: E402
import two_step  # noqa: E402

NOW = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
KEY_A = Fernet.generate_key().decode()
KEY_B = Fernet.generate_key().decode()
KEY_C = Fernet.generate_key().decode()
PW = "sampass12"


def key(value):
    """NORTHWEND_TOTP_KEY set to `value` (None: unset) for a with-block."""
    env = {k: v for k, v in os.environ.items() if k != "NORTHWEND_TOTP_KEY"}
    if value is not None:
        env["NORTHWEND_TOTP_KEY"] = value
    return mock.patch.dict(os.environ, env, clear=True)


class _DB(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_totp_key_")
        self.db = os.path.join(self.dir, "test.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.conn = portfolio.connect(self.db)
        self.uid = auth.create_user(self.conn, "sam", PW)
        no_key = key(None)
        no_key.start()
        self.addCleanup(no_key.stop)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def stored(self, uid=None):
        return self.conn.execute("SELECT totp_secret FROM two_step WHERE user_id = ?",
                                 (uid or self.uid,)).fetchone()["totp_secret"]

    def turn_on(self, uid=None, now=NOW):
        uid = uid or self.uid
        secret = two_step.new_secret()
        res = two_step.enable(self.conn, uid, secret, two_step.totp(secret, now), now=now)
        self.assertTrue(res["ok"], res["error"])
        return secret, res["backup_codes"]


class SealTests(_DB):
    def test_setting_reads_one_or_more_keys(self):
        with key(None):
            self.assertEqual(settings.totp_keys(), [])
        with key(f" {KEY_B}, {KEY_A} "):
            self.assertEqual(settings.totp_keys(), [KEY_B, KEY_A])
        with key(f"{KEY_B}\n{KEY_A}"):
            self.assertEqual(settings.totp_keys(), [KEY_B, KEY_A])

    def test_round_trip_with_a_key(self):
        with key(KEY_A):
            secret, _ = self.turn_on()
            stored = self.stored()
            self.assertTrue(stored.startswith(two_step.SEALED))
            self.assertNotIn(secret, stored)
            self.assertEqual(two_step._open(stored), secret)
            later = NOW + timedelta(seconds=60)
            res = two_step.verify(self.conn, self.uid, two_step.totp(secret, later), now=later)
            self.assertTrue(res["ok"], res["error"])
            self.assertFalse(res["key_problem"])
            self.assertEqual(self.stored(), stored)   # already sealed: left as it is
            self.assertEqual(two_step.storage(self.conn),
                             {"sealed": 1, "readable": 0, "unreadable": 0, "old_key": 0})
            # the setup screen's key, the code and the link still work as before
            self.assertTrue(two_step.status(self.conn, self.uid)["on"])

    def test_no_key_locally_stays_readable_and_works(self):
        self.assertFalse(settings.hosted())
        secret, _ = self.turn_on()
        self.assertEqual(self.stored(), secret)
        self.assertEqual(two_step.key_state(), {"state": "not set", "count": 0, "key_id": None})
        later = NOW + timedelta(seconds=60)
        self.assertTrue(two_step.verify(self.conn, self.uid, two_step.totp(secret, later),
                                        now=later)["ok"])
        self.assertEqual(self.stored(), secret)   # nothing to seal with
        self.assertEqual(two_step.storage(self.conn)["readable"], 1)

    def test_a_readable_key_is_sealed_at_the_next_good_code(self):
        secret, _ = self.turn_on()            # before the key was set
        before = two_step.status(self.conn, self.uid)["stamp"]
        later = NOW + timedelta(seconds=60)
        with key(KEY_A):
            # it still works, and a wrong code changes nothing
            self.assertFalse(two_step.verify(self.conn, self.uid, "000000"
                                             if two_step.totp(secret, later) != "000000"
                                             else "111111", now=later)["ok"])
            self.assertEqual(self.stored(), secret)
            self.assertEqual(two_step.storage(self.conn)["readable"], 1)
            res = two_step.verify(self.conn, self.uid, two_step.totp(secret, later), now=later)
            self.assertTrue(res["ok"], res["error"])
            sealed = self.stored()
            self.assertTrue(sealed.startswith(two_step.SEALED))
            self.assertEqual(two_step._open(sealed), secret)
            # the same setup to a tab already past the code: no second ask
            self.assertEqual(two_step.status(self.conn, self.uid)["stamp"], before)
            again = NOW + timedelta(seconds=120)
            self.assertTrue(two_step.verify(self.conn, self.uid, two_step.totp(secret, again),
                                            now=again)["ok"])
            # turning it off with a code (the other code check) works too
            self.assertTrue(two_step.disable(
                self.conn, self.uid, two_step.totp(secret, NOW + timedelta(seconds=180)),
                now=NOW + timedelta(seconds=180))["ok"])

    def test_the_other_code_check_seals_too(self):
        secret, _ = self.turn_on()
        with key(KEY_A):
            when = NOW + timedelta(seconds=60)
            res = two_step.new_backup_codes(self.conn, self.uid, two_step.totp(secret, when),
                                            now=when)
            self.assertTrue(res["ok"], res["error"])
            self.assertTrue(self.stored().startswith(two_step.SEALED))

    def test_a_backup_code_alone_leaves_it_readable(self):
        secret, backups = self.turn_on()
        with key(KEY_A):
            res = two_step.verify(self.conn, self.uid, backups[0], now=NOW)
            self.assertTrue(res["used_backup"])
            self.assertEqual(self.stored(), secret)

    def test_rotation(self):
        with key(KEY_A):
            secret, _ = self.turn_on()
            old = self.stored()
        with key(f"{KEY_B},{KEY_A}"):          # the new key in front
            self.assertEqual(two_step.storage(self.conn)["old_key"], 1)
            later = NOW + timedelta(seconds=60)
            self.assertTrue(two_step.verify(self.conn, self.uid, two_step.totp(secret, later),
                                            now=later)["ok"])
            new = self.stored()
            self.assertNotEqual(new, old)       # re-sealed with B at the good code
            self.assertEqual(Fernet(KEY_B.encode()).decrypt(
                new[len(two_step.SEALED):].encode()).decode(), secret)
            self.assertEqual(two_step.storage(self.conn)["old_key"], 0)
        with key(KEY_B):                         # and the old key can go
            later = NOW + timedelta(seconds=120)
            self.assertTrue(two_step.verify(self.conn, self.uid, two_step.totp(secret, later),
                                            now=later)["ok"])

    def test_rotate_all_at_once(self):
        sam = self.uid
        ann = auth.create_user(self.conn, "ann", PW)
        with key(KEY_A):
            s1, _ = self.turn_on(sam)
            s2, _ = self.turn_on(ann)
        with key(f"{KEY_B},{KEY_A}"):
            res = two_step.encrypt_all(self.conn, rotate=True)
            self.assertTrue(res["ok"], res["error"])
            self.assertEqual((res["sealed"], res["resealed"]), (0, 2))
            self.assertEqual(res["key_id"], two_step.key_id(KEY_B))
        with key(KEY_B):
            for uid, s in ((sam, s1), (ann, s2)):
                self.assertEqual(two_step._open(self.stored(uid)), s)


class WrongKeyTests(_DB):
    def test_a_wrong_key_fails_closed_calmly(self):
        with key(KEY_A):
            secret, backups = self.turn_on()
        later = NOW + timedelta(seconds=60)
        for setting in (KEY_C, None, "not-a-fernet-key"):
            with self.subTest(setting=setting), key(setting):
                s = two_step.status(self.conn, self.uid)      # never raises
                self.assertTrue(s["on"])
                res = two_step.verify(self.conn, self.uid, two_step.totp(secret, later),
                                      now=later)
                self.assertFalse(res["ok"])
                self.assertTrue(res["key_problem"])
                self.assertIn("backup codes works in its place", res["error"])
                for bad in (secret, KEY_A, KEY_C, "Traceback", "InvalidToken", "Fernet"):
                    self.assertNotIn(bad, res["error"])
                self.assertEqual(two_step.storage(self.conn)["unreadable"], 1)
                two_step.unlock(self.conn, self.uid)
        # a backup code still gets them in, and the wrong tries counted
        with key(KEY_C):
            for _ in range(auth.MAX_FAILED_LOGINS):
                two_step.verify(self.conn, self.uid, two_step.totp(secret, later), now=later)
            self.assertTrue(two_step.verify(self.conn, self.uid, backups[0],
                                            now=later)["locked_minutes"])
            two_step.unlock(self.conn, self.uid)
            used = two_step.verify(self.conn, self.uid, backups[0], now=later)
            self.assertEqual((used["ok"], used["used_backup"], used["key_problem"]),
                             (True, True, True))
            # the password still turns it off for an investor (nothing else breaks)
            self.assertTrue(two_step.disable(self.conn, self.uid, PW, now=later)["ok"])

    def test_a_key_that_isnt_one(self):
        with key("not-a-fernet-key"):
            self.assertEqual(two_step.key_state()["state"], "not valid")
            secret, _ = self.turn_on()            # setup never breaks...
            self.assertEqual(self.stored(), secret)   # ...and stays readable
            self.assertFalse(two_step.encrypt_all(self.conn)["ok"])

    def test_the_alert_names_no_one(self):
        """The code page's note to the admin (views/two_step.py): type and
        place only, through error_alerts like any error."""
        import streamlit as st
        ns = {"st": st, "APP_NAME": "Northwend", "STAGING": False, "DB": self.db,
              "settings": settings}
        path = os.path.join(REPO, "views", "two_step.py")
        with open(path, encoding="utf-8") as fh:
            exec(compile(fh.read(), path, "exec"), ns)
        ns["_two_step_key_alert"]()
        for _ in range(100):   # written in the background
            rows = error_alerts.recent(self.conn)
            if rows:
                break
            time.sleep(0.05)
        self.assertEqual([r["error_type"] for r in rows], ["KeyUnreadable"])
        self.assertIn("two_step.py", rows[0]["place"])
        self.assertIsNone(rows[0]["emailed_at"])   # a local copy only lists it


class CommandTests(_DB):
    def run_cmd(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = manage_users.main(["--db", self.db, "encrypt-two-step", *args])
        return rc, out.getvalue()

    def test_encrypts_every_readable_key_and_logs_it(self):
        ann = auth.create_user(self.conn, "ann", PW)
        s1, _ = self.turn_on()
        s2, _ = self.turn_on(ann)
        rc, out = self.run_cmd()                    # no key here: nothing changes
        self.assertEqual(rc, 1)
        self.assertIn("isn't set", out)
        self.assertEqual((self.stored(), self.stored(ann)), (s1, s2))
        self.assertEqual(admin_log.recent(self.conn), [])
        with key(KEY_A):
            rc, out = self.run_cmd()
            self.assertEqual(rc, 0, out)
            for uid, s in ((self.uid, s1), (ann, s2)):
                self.assertEqual(two_step._open(self.stored(uid)), s)
            self.assertEqual(two_step.storage(self.conn)["readable"], 0)
            self.assertIn("2 readable keys encrypted", out)
            self.assertIn(two_step.key_id(KEY_A), out)
            rows = admin_log.recent(self.conn)
            self.assertEqual([r["action"] for r in rows], ["encrypt_two_step"])
            self.assertTrue(rows[0]["detail"].startswith("command line"))
            self.assertIn("2 readable keys encrypted", rows[0]["detail"])
            for text in (s1, s2, KEY_A, two_step.SEALED, *map(self.stored, (self.uid, ann))):
                self.assertNotIn(text, out)
                self.assertNotIn(text, str(rows))
            # a second run has nothing left to do
            rc, out = self.run_cmd()
            self.assertEqual(rc, 0)
            self.assertIn("0 readable keys encrypted", out)
        # with a different key the command refuses, changing nothing
        with key(KEY_C):
            before = self.stored()
            rc, out = self.run_cmd("--rotate")
            self.assertEqual(rc, 1)
            self.assertIn("2 stored keys won't open", out)
            self.assertEqual(self.stored(), before)

    def test_rotate_flag(self):
        with key(KEY_A):
            secret, _ = self.turn_on()
        with key(f"{KEY_B},{KEY_A}"):
            rc, out = self.run_cmd("--rotate")
            self.assertEqual(rc, 0, out)
            self.assertIn("1 re-encrypted with the first key", out)
        with key(KEY_B):
            self.assertEqual(two_step._open(self.stored()), secret)


class NeverLeavesTests(_DB):
    def test_export_never_has_the_key_or_secrets(self):
        with key(KEY_A):
            secret, backups = self.turn_on()
            z = zipfile.ZipFile(io.BytesIO(export.export_zip(self.conn, self.uid)))
            everything = "".join(z.read(n).decode("utf-8") for n in z.namelist())
            self.assertIn("enabled_at", everything)
            for text in (secret, self.stored(), self.stored()[len(two_step.SEALED):],
                         two_step.SEALED, KEY_A, "totp_secret", *backups):
                self.assertNotIn(text, everything)
            # the column is left out by name, whatever it holds
            self.assertFalse(export._safe("totp_secret"))
            acct = admin.list_accounts(self.conn)[0]
            self.assertIs(acct["two_step"], True)
            self.assertNotIn(self.stored(), str(acct))

    PANEL = """
import sys, os
sys.path.insert(0, {repo!r})
import pandas as pd
import streamlit as st
import auth, mailer, pgcompat
from portfolio import connect
HERE = {repo!r}
DB = {db!r}
STAGING = False
HOSTED = {hosted!r}
APP_NAME = "Northwend"
LOGIN_ID = {uid}
IS_ADVISOR = False
_app_address = lambda: ""
_anthropic_key = lambda: None
resolve_key = lambda k: None
st.session_state["user_id"] = {uid}
st.session_state["username"] = "boss"
path = os.path.join(HERE, "views", "admin.py")
with open(path, encoding="utf-8") as fh:
    exec(compile(fh.read(), path, "exec"), globals())
c = connect(DB)
_render_system(c)
c.close()
"""

    def panel(self, hosted=True):
        from streamlit.testing.v1 import AppTest
        boss = auth.create_user(self.conn, f"boss{time.monotonic_ns()}", "pw-boss-123")
        admin.set_admin(self.conn, auth.get_username(self.conn, boss), True)
        at = AppTest.from_string(self.PANEL.format(repo=REPO, db=self.db, uid=boss,
                                                   hosted=hosted), default_timeout=30).run()
        self.assertEqual(len(at.exception), 0, [e.message for e in at.exception])
        return "\n".join(m.value for m in at.markdown)

    def test_admin_system_shows_set_or_not_and_counts(self):
        ann = auth.create_user(self.conn, "ann", PW)
        s1, _ = self.turn_on()
        md = self.panel()
        self.assertIn("**Two-step key (NORTHWEND_TOTP_KEY):** not set - two-step keys are "
                      "stored readable", md)
        self.assertIn("**Two-step keys stored:** 0 encrypted, 1 readable", md)
        with key(f"{KEY_A},{KEY_B}"):
            s2, _ = self.turn_on(ann)
            md = self.panel()
            self.assertIn(f"set (key id {two_step.key_id(KEY_A)}; 2 keys, the first "
                          "encrypts)", md)
            self.assertIn("1 encrypted, 1 readable (each is encrypted at its next sign-in", md)
        with key(KEY_C):
            md = self.panel()
            self.assertIn("1 that won't open with this key", md)
        with key("nope"):
            self.assertIn("set, but not a valid key", self.panel())
        for text in (s1, s2, KEY_A, KEY_B, KEY_C, two_step.SEALED, self.stored(ann)):
            self.assertNotIn(text, md)


class WordsTests(unittest.TestCase):
    """The published words say "encrypted" only once the owner says the live
    copy's keys are (disclosures.TWO_STEP_ENCRYPTED), after the RUNBOOK's
    steps, in that order."""

    def test_the_privacy_policy_follows_the_switch(self):
        sys.path.insert(0, os.path.join(REPO, "website"))
        import build as site
        import disclosures
        for on in (False, True):
            with self.subTest(on=on), mock.patch.object(disclosures, "TWO_STEP_ENCRYPTED", on):
                text = " ".join(site.legal_text("privacy.html").split())
                self.assertIn("the key your authenticator app uses ("
                              + disclosures.two_step_key_words() + ")", text)
                self.assertEqual("stored encrypted" in text, on)
        self.assertEqual("encrypted" in disclosures._TWO_STEP_KEY_LINE,
                         disclosures.TWO_STEP_ENCRYPTED)
        security = dict(disclosures.SECTIONS)["Security"]
        self.assertEqual("stored\n  encrypted" in security, disclosures.TWO_STEP_ENCRYPTED)

    def test_the_drafts_and_developer_notes_are_true_to_the_code(self):
        def read(*p):
            with open(os.path.join(REPO, *p), encoding="utf-8") as fh:
                return " ".join(fh.read().split())
        import disclosures
        self.assertNotIn("stored readable", " ".join((disclosures.__doc__ or "").split()))
        self.assertIn("stored encrypted", read("docs", "legal", "privacy-policy-DRAFT.md"))
        self.assertIn("stored encrypted", read("docs", "legal", "security-for-advisors-DRAFT.md"))
        self.assertNotIn("stored readable", read("docs", "legal",
                                                 "security-for-advisors-DRAFT.md"))

    def test_the_runbook_puts_the_steps_in_order(self):
        with open(os.path.join(REPO, "docs", "RUNBOOK.md"), encoding="utf-8") as fh:
            text = fh.read()
        section = text[text.index("## Two-step key"):]
        section = section[:section.index("\n## ", 5)]
        order = [section.index(s) for s in ("`NORTHWEND_TOTP_KEY`", "encrypt-two-step`",
                                            "0 readable", "TWO_STEP_ENCRYPTED = True")]
        self.assertEqual(order, sorted(order))
        self.assertIn("Rotate it", section)
        self.assertIn("--rotate", section)


if __name__ == "__main__":
    unittest.main()
