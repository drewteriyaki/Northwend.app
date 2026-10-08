"""L0 sign-up basics (docs/PLAN.md step 1a.9; decisions D10 and B7):
"I live in the United States" beside the 18+ box everywhere it's asked, both
kept with their own times; invite codes for Create account while gate L0 is
off (made, listed and revoked on the Admin page, each used once); setup
links, admin-made accounts and signing in untouched either way.

    python -m unittest tests.test_signup_l0        (from the repo root)
"""

import os
import shutil
import sys
import tempfile
import time
import unittest
import unittest.mock
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import admin  # noqa: E402
import auth  # noqa: E402
import export  # noqa: E402
import flags  # noqa: E402
import invite_codes  # noqa: E402
import portfolio  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
STAMP = "2026-10-06 12:00:00"
BOXES = dict(agreed=True, adult=True, us_resident=True, terms_version="October 1, 2026")


def _gates(value):
    """Only this NORTHWEND_GATES (None: not set at all) - and no secrets file."""
    env = {k: v for k, v in os.environ.items() if k != flags.GATES_SETTING}
    if value is not None:
        env[flags.GATES_SETTING] = value
    return unittest.mock.patch.dict(os.environ, env, clear=True)


class _DB(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_l0_")
        self.db = os.path.join(self.dir, "t.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.conn = portfolio.connect(self.db)
        self.admin_id = auth.create_user(self.conn, "boss", PW)
        p = unittest.mock.patch.object(flags, "_secret", lambda name: None)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _sign_up(self, email="new@example.com", **kw):
        args = dict(BOXES, ip="203.0.113.7", seconds_open=10, now=NOW)
        args.update(kw)
        return auth.sign_up(self.conn, email, PW, **args)

    def _row(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()


class InviteCodeTests(_DB):

    def test_codes_are_short_and_have_no_look_alikes(self):
        made = invite_codes.make(self.conn, 30, by=self.admin_id, note=" for the book club ")
        self.assertEqual(len(set(made)), 30)
        for code in made:
            self.assertEqual(len(code), invite_codes.LENGTH)
            self.assertFalse(set(code) & set("0O1IL"), code)
            self.assertRegex(invite_codes.shown(code), r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")
        rows = invite_codes.listing(self.conn)
        self.assertEqual({r["status"] for r in rows}, {"unused"})
        self.assertEqual({r["note"] for r in rows}, {"for the book club"})
        self.assertEqual(len(invite_codes.make(self.conn, 999, by=self.admin_id)),
                         invite_codes.MAX_AT_ONCE)

    def test_with_l0_on_no_code_is_asked(self):
        with _gates("L0"):
            self.assertFalse(auth.invite_only())
            made = self._sign_up()
        self.assertTrue(made["ok"], made)

    def test_with_l0_off_a_code_is_needed_and_works_once(self):
        (code,) = invite_codes.make(self.conn, 1, by=self.admin_id)
        with _gates(None):
            self.assertTrue(auth.invite_only())
            none = self._sign_up()
            self.assertEqual(none["error"], invite_codes.NEED_CODE)
            wrong = self._sign_up(invite_code="ABCD-EFGH", ip="198.51.100.1")
            self.assertEqual(wrong["error"], invite_codes.NOT_WORKING)
            # typed in lower case, with the dash: fine
            typed = invite_codes.shown(code).lower()
            made = self._sign_up(invite_code=typed)
            self.assertTrue(made["ok"], made)
            again = self._sign_up(email="second@example.com", invite_code=code,
                                  ip="198.51.100.2")
            self.assertEqual((again["ok"], again["error"]), (False, invite_codes.NOT_WORKING))
        self.assertEqual(self._row("SELECT COUNT(*) AS n FROM users")["n"], 2)   # boss + new
        row = self._row("SELECT used_at, used_by, revoked_at FROM invite_codes WHERE code = ?",
                        (code,))
        self.assertEqual((row["used_at"], row["used_by"], row["revoked_at"]),
                         (STAMP, made["user_id"], None))
        (listed,) = invite_codes.listing(self.conn)
        self.assertEqual((listed["status"], listed["used_by"]), ("used", "new@example.com"))
        self.assertFalse(invite_codes.revoke(self.conn, code))    # used: nothing to stop

    def test_a_revoked_code_is_refused_calmly(self):
        (code,) = invite_codes.make(self.conn, 1, by=self.admin_id)
        self.assertTrue(invite_codes.revoke(self.conn, invite_codes.shown(code)))
        self.assertFalse(invite_codes.revoke(self.conn, code))
        with _gates(""):
            refused = self._sign_up(invite_code=code)
        self.assertFalse(refused["ok"])
        self.assertEqual(refused["error"], invite_codes.NOT_WORKING)
        for scary in ("revoked", "invalid", "error"):
            self.assertNotIn(scary, refused["error"].lower())
        self.assertEqual(invite_codes.listing(self.conn)[0]["status"], "revoked")

    def test_wrong_codes_count_toward_the_address_limit(self):
        with _gates(None):
            for i in range(auth.SIGNUP_TRIES_PER_ADDRESS_PER_HOUR):
                self._sign_up(email=f"g{i}@example.com", invite_code=f"WRONG{i:03d}")
            (code,) = invite_codes.make(self.conn, 1, by=self.admin_id)
            blocked = self._sign_up(email="real@example.com", invite_code=code)
        self.assertIn("tomorrow", blocked["error"])
        self.assertTrue(invite_codes.usable(self.conn, code))   # not used up by that

    def test_deleting_the_account_keeps_the_code_used(self):
        (code,) = invite_codes.make(self.conn, 1, by=self.admin_id)
        with _gates(None):
            uid = self._sign_up(invite_code=code)["user_id"]
        gone = admin.delete_own(self.conn, uid, PW)
        self.assertTrue(gone["ok"], gone)
        self.assertIsNone(auth.get_username(self.conn, uid))
        row = self._row("SELECT used_at, used_by FROM invite_codes WHERE code = ?", (code,))
        self.assertEqual((row["used_at"], row["used_by"]), (STAMP, None))
        self.assertFalse(invite_codes.usable(self.conn, code))

    def test_setup_links_and_signing_in_never_need_a_code(self):
        advisor = auth.create_user(self.conn, "carol", PW)
        auth.set_advisor(self.conn, "carol", True)
        client = auth.create_client(self.conn, advisor, "", name="Dana")
        token = auth.create_invite(self.conn, advisor, client)
        old = auth.create_user(self.conn, "old.timer", PW)      # agreed before D10
        self.conn.execute("UPDATE users SET terms_version = 'v1', terms_accepted_at = "
                          "'2026-01-01 00:00:00' WHERE id = ?", (old,))
        self.conn.commit()
        with _gates(None):
            self.assertTrue(auth.invite_only())
            ok = auth.accept_invite(self.conn, token, "clientpass1", now=NOW, **BOXES)
            self.assertTrue(ok["ok"], ok)
            self.assertEqual(auth.attempt_login(self.conn, "old.timer", PW)["user_id"], old)
            self.assertEqual(auth.attempt_login(self.conn, "boss", PW)["user_id"],
                             self.admin_id)
        facts = auth.login_facts_of(self._row(
            "SELECT " + ", ".join(auth.LOGIN_COLUMNS) + " FROM users WHERE id = ?", (old,)))
        self.assertTrue(facts["agreed"])          # not asked again
        row = self._row("SELECT age_confirmed_at, us_resident_at FROM users WHERE id = ?",
                        (old,))
        self.assertEqual((row["age_confirmed_at"], row["us_resident_at"]), (None, None))
        self.assertEqual(self._row("SELECT COUNT(*) AS n FROM invite_codes")["n"], 0)

    def test_the_table_is_cleared_on_delete_but_not_exported(self):
        self.assertEqual(admin.ACCOUNT_REFERENCES["invite_codes"], ("created_by", "used_by"))
        self.assertNotIn("invite_codes", admin.ACCOUNT_TABLES)
        self.assertNotIn("invite_codes", {t for _, t, _, _ in export.OWN})


class ConfirmationTests(_DB):
    """18 or older and living in the United States: both required wherever
    the disclosures are agreed to, each kept with its own time (D10)."""

    def _stamps(self, uid):
        r = self._row("SELECT terms_version, terms_accepted_at, age_confirmed_at, "
                      "us_resident_at FROM users WHERE id = ?", (uid,))
        return tuple(r)

    def test_sign_up_needs_both_and_keeps_both(self):
        for missing, words in (("adult", "18 and over"), ("us_resident", "United States")):
            refused = self._sign_up(needs_code=False, **{missing: False})
            self.assertFalse(refused["ok"])
            self.assertIn(words, refused["error"])
        made = self._sign_up(needs_code=False)
        self.assertEqual(self._stamps(made["user_id"]),
                         ("October 1, 2026", STAMP, STAMP, STAMP))

    def test_setup_link_needs_both_and_keeps_both(self):
        advisor = auth.create_user(self.conn, "carol", PW)
        auth.set_advisor(self.conn, "carol", True)
        client = auth.create_client(self.conn, advisor, "", name="Dana")
        token = auth.create_invite(self.conn, advisor, client)
        no_us = dict(BOXES, us_resident=False)
        refused = auth.accept_invite(self.conn, token, "clientpass1", now=NOW, **no_us)
        self.assertIn("United States", refused["error"])
        self.assertTrue(auth.accept_invite(self.conn, token, "clientpass1", now=NOW,
                                           **BOXES)["ok"])
        self.assertEqual(self._stamps(client), ("October 1, 2026", STAMP, STAMP, STAMP))

    def test_agreeing_after_sign_in_keeps_both(self):
        uid = auth.create_user(self.conn, "made.by.admin", PW)
        auth.record_agreement(self.conn, uid, "October 1, 2026", via=auth.TERMS_VIA_SIGN_IN,
                              now=NOW)
        self.assertEqual(self._stamps(uid), ("October 1, 2026", STAMP, STAMP, STAMP))

    def test_both_are_exported_with_the_account(self):
        uid = self._sign_up(needs_code=False)["user_id"]
        for cols in (export.ACCOUNT_COLUMNS, export.CLIENT_COLUMNS):
            self.assertIn("age_confirmed_at", cols)
            self.assertIn("us_resident_at", cols)
        self.assertIn("us_resident_at", self._row(
            "SELECT " + ", ".join(export.ACCOUNT_COLUMNS) + " FROM users WHERE id = ?",
            (uid,)).keys())


class GateRegistryTests(unittest.TestCase):
    def test_every_gate_check_is_made_somewhere(self):
        code = ""
        for folder in (REPO, os.path.join(REPO, "views")):
            for f in os.listdir(folder):
                if f.endswith(".py") and f != "flags.py":
                    with open(os.path.join(folder, f), encoding="utf-8") as fh:
                        code += fh.read()
        self.assertIn("L0", flags.GATE_CHECKS)
        for g in flags.GATE_CHECKS:
            self.assertIn(g, flags.GATES)
            self.assertIn(f'flags.gate("{g}")', code, f"nothing checks gate {g}")


# --------------------------------------------------------------------------- #
# in the app: Create account, the setup link, the Admin panel
# --------------------------------------------------------------------------- #
class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_l0_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.ann = auth.create_user(c, "ann", PW)      # an admin, with two-step
            secret = two_step.new_secret()
            two_step.enable(c, cls.ann, secret, two_step.totp(secret))
            cls.ann_ok = f"{cls.ann}:{two_step.status(c, cls.ann)['stamp']}"
            cls.carol = auth.create_user(c, "carol", PW)
            auth.set_advisor(c, "carol", True)
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _conn(self):
        return portfolio.connect(self.db)

    def _app(self, gates, *, query=None, state=None, admins=""):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in (query or {}).items():
            at.query_params[k] = v
        for k, v in (state or {}).items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "ANTHROPIC_API_KEY", "RESEND_API_KEY",
                            "NORTHWEND_ADMINS", flags.GATES_SETTING)}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1")
        if gates is not None:
            env[flags.GATES_SETTING] = gates
        if admins:
            env["NORTHWEND_ADMINS"] = admins
        self._env = env
        return at

    def _run(self, at):
        with unittest.mock.patch.dict(os.environ, self._env, clear=True):
            at.run()
        self.assertEqual([e.message for e in at.exception], [])
        return at

    @staticmethod
    def _text(at):
        parts = [m.value for m in at.markdown]
        for kind in ("error", "caption", "info", "success"):
            parts += [str(e.value) for e in getattr(at, kind)]
        return " ".join(parts)

    def _fill_signup(self, at, email, code=None):
        if code is not None:
            at.text_input(key="signup_code").input(code)
        at.text_input(key="signup_email").input(email)
        at.text_input(key="signup_pw").input(PW)
        at.text_input(key="signup_pw_again").input(PW)
        at.checkbox(key="signup_adult").check()
        at.checkbox(key="signup_us").check()
        at.checkbox(key="signup_agree").check()
        at.button(key="FormSubmitter:signup_form-Create account").click()

    def _user(self, email):
        c = self._conn()
        try:
            return c.execute("SELECT id, age_confirmed_at, us_resident_at FROM users "
                             "WHERE username = ?", (email,)).fetchone()
        finally:
            c.close()

    def test_l0_on_sign_up_as_today(self):
        at = self._app("L0", query={"signup": "1"},
                       state={"signup_opened": time.time() - 60})
        self._run(at)
        self.assertNotIn("signup_code", [t.key for t in at.text_input])
        self.assertNotIn(invite_codes.BETA_LINE, self._text(at))
        self._fill_signup(at, "open.door@example.com")
        self._run(at)
        row = self._user("open.door@example.com")
        self.assertIsNotNone(row)
        self.assertEqual(at.session_state["user_id"], row["id"])
        self.assertTrue(row["age_confirmed_at"] and row["us_resident_at"])

    def test_signing_up_from_a_home_link_still_opens_the_first_steps(self):
        at = self._app("L0", query={"signup": "1", "page": "home"},
                       state={"signup_opened": time.time() - 60})
        self._run(at)
        self._fill_signup(at, "from.home@example.com")
        self._run(at)
        self.assertEqual(at.session_state["page"], "Get started")
        self.assertIn("fs_skip", [b.key for b in at.button])   # the first steps slideshow

    def test_l0_off_asks_for_a_code(self):
        c = self._conn()
        try:
            (code,) = invite_codes.make(c, 1, by=self.ann)
        finally:
            c.close()
        at = self._app(None, query={"signup": "1"},
                       state={"signup_opened": time.time() - 60})
        self._run(at)
        self.assertIn(invite_codes.BETA_LINE, self._text(at))
        self.assertEqual(at.text_input[0].key, "signup_code")     # asked first
        self._fill_signup(at, "guess@example.com", "ZZZZ-ZZZZ")
        self._run(at)
        self.assertIn(invite_codes.NOT_WORKING, self._text(at))
        self.assertIsNone(self._user("guess@example.com"))
        self._fill_signup(at, "invited@example.com", invite_codes.shown(code))
        self._run(at)
        row = self._user("invited@example.com")
        self.assertIsNotNone(row)
        self.assertEqual(at.session_state["user_id"], row["id"])

    def test_the_setup_link_needs_no_code_but_both_boxes(self):
        c = self._conn()
        try:
            client = auth.create_client(c, self.carol, "", name="Eve")
            token = auth.create_invite(c, self.carol, client)
        finally:
            c.close()
        at = self._app(None, query={"invite": token})
        self._run(at)
        self.assertNotIn(invite_codes.BETA_LINE, self._text(at))
        at.text_input(key="invite_pw").input("clientpass1")
        at.text_input(key="invite_pw_again").input("clientpass1")
        at.checkbox(key="invite_adult").check()
        at.checkbox(key="invite_agree").check()
        at.button(key="FormSubmitter:invite_form-Create my login").click()
        self._run(at)
        self.assertIn("United States", self._text(at))          # the new box, not ticked
        at.text_input(key="invite_pw").input("clientpass1")
        at.text_input(key="invite_pw_again").input("clientpass1")
        at.checkbox(key="invite_us").check()
        at.button(key="FormSubmitter:invite_form-Create my login").click()
        self._run(at)
        self.assertEqual(at.session_state["user_id"], client)

    def test_admin_makes_and_revokes_codes(self):
        state = {"user_id": self.ann, "username": "ann", "two_step_ok": self.ann_ok}
        at = self._app(None, query={"page": "admin"}, state=state, admins="ann")
        self._run(at)
        self.assertIn("Sign-up is by invite code for now", self._text(at))
        at.number_input(key="admin_codes_n").set_value(3)
        at.text_input(key="admin_codes_note").input("Book club")
        at.button(key="admin_codes_make").click()
        self._run(at)
        self.assertIn("Made 3 invite codes", self._text(at))
        c = self._conn()
        try:
            codes = [r for r in invite_codes.listing(c) if r["note"] == "Book club"]
        finally:
            c.close()
        self.assertEqual(len(codes), 3)
        first = codes[0]["code"]
        at.button(key=f"admin_code_revoke_{first}").click()
        self._run(at)
        self.assertIn("won't work any more", self._text(at))
        c = self._conn()
        try:
            self.assertFalse(invite_codes.usable(c, first))
            self.assertEqual(sum(invite_codes.usable(c, r["code"]) for r in codes), 2)
        finally:
            c.close()
        self.assertNotIn(f"admin_code_revoke_{first}", [b.key for b in at.button])

    def test_an_old_account_signs_in_and_is_not_asked_again(self):
        c = self._conn()
        try:
            old = auth.create_user(c, "old.hand", PW)
            c.execute("UPDATE users SET terms_version = 'v1', terms_accepted_at = "
                      "'2026-01-01 00:00:00' WHERE id = ?", (old,))
            c.commit()
        finally:
            c.close()
        at = self._app(None)
        self._run(at)
        at.text_input(key="login_user").input("old.hand")
        at.text_input(key="login_pw").input(PW)
        at.button(key="FormSubmitter:login_form-Log in").click()
        self._run(at)
        self.assertEqual(at.session_state["user_id"], old)
        self.assertNotIn("terms_ok", [b.key for b in at.button])


if __name__ == "__main__":
    unittest.main()
