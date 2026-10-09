"""Invite someone (invite_links.py, views/invite_friend.py): each login's own
link to share while sign-up is open. The name menu's window for investors,
advisors and admins on their own account (never while an advisor is in a
client's account, never while sign-up needs an admin's code); the link uses
the app's own address; someone arriving sees "A friend invited you" and
nothing about who; an account made through it adds one to a count - never
who; an old or mistyped code is the plain sign-up; signed-in visitors are
unaffected; a new link replaces the old one; export, delete and Admin.

    python -m unittest tests.test_invite_links        (from the repo root)
"""

import os
import re
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
import disclosures  # noqa: E402
import export  # noqa: E402
import flags  # noqa: E402
import invite_codes  # noqa: E402
import invite_links  # noqa: E402
import portfolio  # noqa: E402
import rate_limits  # noqa: E402
import two_step  # noqa: E402
from tests import offline as offline_net  # noqa: E402

PW = "pw-123456789"
NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
BOXES = dict(agreed=True, adult=True, us_resident=True, terms_version="October 8, 2026")
APP_URL = "https://go.northwend.app/"


class LinkTests(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_invl_")
        self.db = os.path.join(self.dir, "t.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.c = portfolio.connect(self.db)
        self.alice = auth.create_user(self.c, "alice@example.com", PW)

    def tearDown(self):
        self.c.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _sign_up(self, email, friend_code=None, ip="203.0.113.7"):
        return auth.sign_up(self.c, email, PW, ip=ip, seconds_open=10, needs_code=False,
                            friend_code=friend_code, now=NOW, **BOXES)

    def test_one_short_code_per_login_kept_until_replaced(self):
        code = invite_links.code_for(self.c, self.alice)
        self.assertEqual(len(code), invite_links.LENGTH)
        self.assertFalse(set(code) & set("0O1IL"), code)
        self.assertTrue(invite_links.looks_like(code))
        self.assertTrue(invite_links.looks_like(code.lower()))
        self.assertEqual(invite_links.code_for(self.c, self.alice), code)    # the same one
        # told apart from an admin's code (8) and a setup link's token (43)
        self.assertFalse(invite_links.looks_like("ABCDEFGH"))
        self.assertFalse(invite_links.looks_like("x" * 43))
        self.assertEqual(invite_links.link(APP_URL, code), f"{APP_URL}?invite={code}")
        self.assertEqual(invite_links.link("https://go.northwend.app", code),
                         f"{APP_URL}?invite={code}")
        new = invite_links.new_code(self.c, self.alice)
        self.assertNotEqual(new, code)
        self.assertFalse(invite_links.valid(self.c, code))   # old: just the plain sign-up
        self.assertTrue(invite_links.valid(self.c, new))
        self.assertEqual(self.c.execute("SELECT COUNT(*) AS n FROM invite_links")
                         .fetchone()["n"], 1)

    def test_a_sign_up_through_a_link_counts_and_nothing_says_who(self):
        code = invite_links.code_for(self.c, self.alice)
        made = self._sign_up("friend@example.com", code)
        self.assertTrue(made["ok"], made)
        self.assertEqual(invite_links.joined(self.c, self.alice), 1)
        # an old or made-up code: the account is made, nothing is counted
        self.assertTrue(self._sign_up("other@example.com", "ZZZZZZZZZZ",
                                      ip="198.51.100.1")["ok"])
        self.assertEqual(invite_links.joined(self.c, self.alice), 1)
        # the count stays with the person when they make a new link
        new = invite_links.new_code(self.c, self.alice)
        self.assertTrue(self._sign_up("third@example.com", new, ip="198.51.100.2")["ok"])
        self.assertEqual(invite_links.joined(self.c, self.alice), 2)
        self.assertEqual(invite_links.total_joined(self.c), 2)
        self.assertEqual(invite_links.joined_words(2), "2 people have joined with your link.")
        self.assertEqual(invite_links.joined_words(1), "1 person has joined with your link.")
        # nothing ties the new account to the link: no column anywhere names it
        cols = [r[1] for r in self.c.execute("PRAGMA table_info(users)")]
        self.assertFalse([x for x in cols if "invite" in x or "friend" in x], cols)
        self.assertEqual([r[1] for r in self.c.execute("PRAGMA table_info(invite_links)")],
                         ["user_id", "code", "created_at", "joined"])

    def test_export_delete_and_admin_tables(self):
        code = invite_links.code_for(self.c, self.alice)
        friend = self._sign_up("friend@example.com", code)["user_id"]
        self.assertEqual(admin.ACCOUNT_TABLES["invite_links"], ("user_id",))
        self.assertIn(("your_invite_link", "invite_links", "user_id", ""), export.OWN)
        (row,) = export.collect(self.c, self.alice)["your_invite_link"]
        self.assertEqual((row["code"], row["joined"]), (code, 1))
        self.assertNotIn("your_invite_link", export.collect(self.c, friend))
        self.assertTrue(admin.delete_account(self.c, self.alice, by=-1)["ok"])
        self.assertIsNone(self.c.execute("SELECT 1 FROM invite_links").fetchone())
        self.assertFalse(invite_links.valid(self.c, code))
        self.assertEqual(auth.get_username(self.c, friend), "friend@example.com")  # stays

    def test_words_are_calm_and_promise_nothing(self):
        text = " ".join([invite_links.INTRO, invite_links.PRIVATE, invite_links.ARRIVED,
                         invite_links.ADVISOR_NOTE, invite_links.message("LINK"),
                         invite_links.NEW_LINK_HELP, invite_links.NEW_LINK_DONE,
                         invite_links.joined_words(0), invite_links.joined_words(3)])
        for word in ("reward", "earn", "bonus", "credit", "leaderboard", "rank", "free month",
                     "unlock"):
            self.assertIsNone(re.search(rf"{word}", text.lower()), word)
        self.assertNotIn("!", text)
        self.assertEqual(invite_links.INTRO, "Know someone who'd like a calm place to start? "
                                             "Share your link.")
        self.assertIn("never sells you anything", invite_links.message("x"))
        # the in-app privacy text says what's kept
        self.assertIn("Invite someone", " ".join(b for _, b in disclosures.SECTIONS))


class AppTests(unittest.TestCase):
    """dashboard.py through AppTest on a scratch database."""

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_invl_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.alice = auth.create_user(c, "alice", PW)
            auth.set_display_name(c, cls.alice, "Alicia")
            c.execute("UPDATE users SET email = 'alice@example.com' WHERE id = ?", (cls.alice,))
            cls.carol = auth.create_user(c, "carol", PW)        # an advisor
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            cls.dave = auth.create_user(c, "dave", PW)          # her client
            auth.link_client(c, cls.carol, cls.dave)
            cls.ann = auth.create_user(c, "ann", PW)            # an admin
            secret = two_step.new_secret()
            two_step.enable(c, cls.ann, secret, two_step.totp(secret))
            cls.ann_ok = f"{cls.ann}:{two_step.status(c, cls.ann)['stamp']}"
            # agreed after an admin made them (not their own sign-up: ann stays an admin)
            c.execute("UPDATE users SET terms_version = ?, terms_via = ?",
                      (disclosures.LAST_UPDATED, auth.TERMS_VIA_SIGN_IN))
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _conn(self):
        return portfolio.connect(self.db)

    def _app(self, *, gates="L0", query=None, state=None, admins=""):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in (query or {}).items():
            at.query_params[k] = v
        for k, v in (state or {}).items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "ANTHROPIC_API_KEY", "RESEND_API_KEY",
                            "NORTHWEND_ADMINS", flags.GATES_SETTING, "APP_URL")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", APP_URL=APP_URL)
        if gates is not None:
            env[flags.GATES_SETTING] = gates
        if admins:
            env["NORTHWEND_ADMINS"] = admins
        self._env = env
        return at

    def _run(self, at):
        with unittest.mock.patch.dict(os.environ, self._env, clear=True), \
                unittest.mock.patch("socket.socket.connect", offline_net.connect):
            at.run()
        self.assertEqual([e.message for e in at.exception], [])
        return at

    def _signed_in(self, uid, name, page="about", **state):
        return self._app(query={"page": page}, admins=state.pop("admins", ""),
                         gates=state.pop("gates", "L0"),
                         state={"user_id": uid, "username": name, **state})

    @staticmethod
    def _menu_keys(at):
        pops = {p.proto.id.rsplit("-", 1)[-1]: p for p in at.get("popover")}
        return [b.key for b in pops["pt_me"].button]

    @staticmethod
    def _text(at):
        parts = []
        for kind in ("markdown", "caption", "info", "success", "error", "warning", "code"):
            parts += [str(getattr(e, "value", "") or getattr(e, "body", "") or "")
                      for e in at.get(kind)]
        return " ".join(parts)

    def test_in_the_name_menu_on_your_own_account_only(self):
        cases = [("investor", self.alice, "alice", {}),
                 ("advisor", self.carol, "carol", {"two_step_ok": self.carol_ok}),
                 ("admin", self.ann, "ann", {"two_step_ok": self.ann_ok, "admins": "ann"})]
        for label, uid, name, state in cases:
            with self.subTest(label):
                at = self._run(self._signed_in(uid, name, **state))
                keys = self._menu_keys(at)
                self.assertIn("menu_invite", keys)
                self.assertEqual(keys[keys.index("menu_invite") + 1], "menu_feedback")
                self.assertIn("Invite someone", at.button(key="menu_invite").label)
        # an advisor in a client's account: not there
        at = self._run(self._signed_in(self.carol, "carol", two_step_ok=self.carol_ok,
                                       active_user_id=self.dave))
        self.assertNotIn("menu_invite", self._menu_keys(at))
        # sign-up by admin's code (gate L0 off): a link would lead nowhere
        at = self._run(self._signed_in(self.alice, "alice", gates=None))
        self.assertNotIn("menu_invite", self._menu_keys(at))

    def test_the_window_shows_the_link_on_the_app_address_and_a_new_one_replaces_it(self):
        at = self._run(self._signed_in(self.alice, "alice"))
        at.button(key="menu_invite").click()
        self._run(at)
        c = self._conn()
        try:
            code = invite_links.code_for(c, self.alice)
            joined = invite_links.joined(c, self.alice)
        finally:
            c.close()
        link = f"{APP_URL}?invite={code}"
        codes = [e.value for e in at.get("code")]
        self.assertEqual(codes, [link, invite_links.message(link)])
        text = self._text(at)
        self.assertIn(invite_links.INTRO, text)
        self.assertIn(invite_links.PRIVATE, text)
        self.assertIn(invite_links.joined_words(joined), text)
        self.assertNotIn(invite_links.ADVISOR_NOTE, text)
        # Make a new link: a new code, the old one no longer someone's link
        at.button(key="inv_new").click()
        self._run(at)
        c = self._conn()
        try:
            new = invite_links.code_for(c, self.alice)
            self.assertFalse(invite_links.valid(c, code))
        finally:
            c.close()
        self.assertNotEqual(new, code)
        self.assertIn(f"{APP_URL}?invite={new}", [e.value for e in at.get("code")])
        self.assertIn(invite_links.NEW_LINK_DONE, self._text(at))

    def test_an_advisor_link_invites_an_individual(self):
        at = self._run(self._signed_in(self.carol, "carol", two_step_ok=self.carol_ok))
        at.button(key="menu_invite").click()
        self._run(at)
        self.assertIn(invite_links.ADVISOR_NOTE, self._text(at))

    def test_new_links_are_rate_limited(self):
        c = self._conn()
        try:
            for _ in range(rate_limits.LIMITS[rate_limits.NEW_LINK][0]):
                rate_limits.allow(c, self.ann, rate_limits.NEW_LINK)
            before = invite_links.code_for(c, self.ann)
        finally:
            c.close()
        at = self._run(self._signed_in(self.ann, "ann", two_step_ok=self.ann_ok,
                                       admins="ann"))
        at.button(key="menu_invite").click()
        self._run(at)
        at.button(key="inv_new").click()
        self._run(at)
        self.assertIn(rate_limits.CALM, self._text(at))
        c = self._conn()
        try:
            self.assertEqual(invite_links.code_for(c, self.ann), before)
        finally:
            c.close()

    def _fill_signup(self, at, email):
        at.text_input(key="signup_email").input(email)
        at.text_input(key="signup_pw").input(PW)
        at.text_input(key="signup_pw_again").input(PW)
        at.checkbox(key="signup_adult").check()
        at.checkbox(key="signup_us").check()
        at.checkbox(key="signup_agree").check()
        at.button(key="FormSubmitter:signup_form-Create account").click()

    def test_arriving_through_a_link_says_a_friend_and_never_who(self):
        c = self._conn()
        try:
            code = invite_links.code_for(c, self.alice)
            before = invite_links.joined(c, self.alice)
        finally:
            c.close()
        at = self._run(self._app(query={"invite": code.lower()},
                                 state={"signup_opened": time.time() - 60}))
        text = self._text(at)
        self.assertIn(invite_links.ARRIVED, text)
        self.assertIn("signup_email", [t.key for t in at.text_input])   # Create account
        for who in ("alice", "Alicia", "alice@example.com"):
            self.assertNotIn(who, text)
        self.assertNotIn("invite", at.query_params)
        self.assertNotIn("signup_code", [t.key for t in at.text_input])   # open sign-up
        self._fill_signup(at, "pal@example.com")
        self._run(at)
        c = self._conn()
        try:
            pal = c.execute("SELECT id FROM users WHERE username = 'pal@example.com'").fetchone()
            self.assertIsNotNone(pal)
            self.assertEqual(at.session_state["user_id"], pal["id"])
            self.assertEqual(invite_links.joined(c, self.alice), before + 1)
        finally:
            c.close()

    def test_an_old_or_made_up_code_is_the_plain_sign_up(self):
        c = self._conn()
        try:
            before = invite_links.total_joined(c)
        finally:
            c.close()
        at = self._run(self._app(query={"invite": "ZZZZZZZZZZ"},
                                 state={"signup_opened": time.time() - 60}))
        text = self._text(at)
        self.assertNotIn(invite_links.ARRIVED, text)
        self.assertEqual([e.value for e in at.error], [])
        self.assertIn("signup_email", [t.key for t in at.text_input])
        self._fill_signup(at, "plain@example.com")
        self._run(at)
        self.assertIsNotNone(at.session_state["user_id"])
        c = self._conn()
        try:
            self.assertEqual(invite_links.total_joined(c), before)
        finally:
            c.close()

    def test_signed_in_visitors_are_unaffected(self):
        c = self._conn()
        try:
            code = invite_links.code_for(c, self.carol)
            before = invite_links.joined(c, self.carol)
        finally:
            c.close()
        at = self._app(query={"invite": code, "page": "about"},
                       state={"user_id": self.alice, "username": "alice"})
        self._run(at)
        self.assertEqual(at.session_state["user_id"], self.alice)
        self.assertEqual(at.session_state["page"], "About")
        self.assertNotIn(invite_links.ARRIVED, self._text(at))
        self.assertNotIn("signup_email", [t.key for t in at.text_input])
        c = self._conn()
        try:
            self.assertEqual(invite_links.joined(c, self.carol), before)
        finally:
            c.close()

    def test_admin_sees_a_total_never_who(self):
        c = self._conn()
        try:
            n = invite_links.total_joined(c)
        finally:
            c.close()
        at = self._run(self._signed_in(self.ann, "ann", page="admin", two_step_ok=self.ann_ok,
                                       admins="ann"))
        text = self._text(at)
        self.assertIn(f"Accounts made from invite links: **{n}**", text)
        self.assertNotIn(invite_codes.BETA_LINE, text)
