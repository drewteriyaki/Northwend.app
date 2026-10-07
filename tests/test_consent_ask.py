"""Consent for advisor-made clients (PLAN step 5.7): a client whose sharing
rests only on a 'migration' grant - or on none while linked (an admin's link,
a password the advisor set) - is asked once at their next sign-in. "Keep
sharing" writes a 'sign_in_ask' grant with the exact words shown and the ask
goes; "Stop sharing" asks to confirm, then ends the link and writes the
revoke. A client who came in through the setup link (one by one or from a
file - the same path) is never asked. An advisor viewing the account never
sees the ask, nor does an admin; the advisor's book says "hasn't confirmed
sharing yet" until the client answers. The app runs with streamlit's AppTest.

    python -m unittest tests.test_consent_ask        (from the repo root)
"""

import contextlib
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402

import advising  # noqa: E402
import auth  # noqa: E402
import consent  # noqa: E402
import disclosures  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
SIGNED_IN = "2026-10-01 10:00:00"


def _signed_in_client(c, advisor_id, login, *, agreed=True):
    """An advisor-made client who has signed in (a password, not the setup
    link) and, unless told otherwise, agreed to the disclosures."""
    uid = auth.create_client(c, advisor_id, login, name=login.title())
    auth.set_password(c, login, PW)
    c.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (SIGNED_IN, uid))
    c.commit()
    if agreed:
        auth.record_agreement(c, uid, disclosures.LAST_UPDATED, via=auth.TERMS_VIA_SIGN_IN)
    return uid


# --------------------------------------------------------------------------- #
# consent.to_ask / unconfirmed / ask_text
# --------------------------------------------------------------------------- #
class WhoIsAskedTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pt_consent_ask_")
        self.db = os.path.join(self.tmp, "t.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.c = portfolio.connect(self.db)

    def tearDown(self):
        self.c.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _advisor(self, name):
        uid = auth.create_user(self.c, name, PW)
        auth.set_advisor(self.c, name, True)
        return uid

    def test_who_is_asked(self):
        c = self.c
        carol, omar = self._advisor("carol"), self._advisor("omar")
        # a link from before the records: only the 'migration' grant
        old = auth.create_user(c, "old", PW)
        auth.link_client(c, carol, old)
        consent.grant(c, old, carol, consent.MIGRATION_TEXT, "migration")
        self.assertEqual(consent.to_ask(c, old), [carol])
        # an admin's link of two accounts (or a password the advisor set): no grant at all
        linked = auth.create_user(c, "linked", PW)
        auth.link_client(c, omar, linked)
        auth.link_client(c, carol, linked)
        self.assertEqual(consent.to_ask(c, linked), [carol, omar])
        # the setup link's grant, an intro's, and the sign-in ask's own: not asked
        made = auth.create_client(c, carol, "made@example.com")
        token = auth.create_invite(c, carol, made)
        self.assertTrue(auth.accept_invite(c, token, PW, agreed=True, adult=True,
                                           us_resident=True, terms_version="v")["ok"])
        self.assertEqual(consent.to_ask(c, made), [])
        consent.grant(c, old, carol, consent.ask_text("Carol"), "sign_in_ask")
        self.assertEqual(consent.to_ask(c, old), [])
        # unlinked, then linked again without a new yes: asked again
        auth.unlink_client(c, carol, old)
        self.assertEqual(consent.to_ask(c, old), [])          # not linked: nothing to ask
        auth.link_client(c, carol, old)
        self.assertEqual(consent.to_ask(c, old), [carol])
        # someone with no advisor
        self.assertEqual(consent.to_ask(c, auth.create_user(c, "solo", PW)), [])
        # the advisor's side, for the whole book at once
        self.assertEqual(consent.unconfirmed(c, carol), {old, linked})
        self.assertEqual(consent.unconfirmed(c, omar), {linked})

    def test_the_words(self):
        self.assertIn("sign_in_ask", consent.HOWS)
        text = consent.ask_text("Carol Lee, Lee Advisers")
        self.assertIn("Carol Lee, Lee Advisers", text)
        # what the advisor sees and doesn't - as the Privacy Policy says
        self.assertIn("holdings, plan, goals and answers", text)
        with open(os.path.join(REPO, "docs", "legal", "privacy-policy.md"),
                  encoding="utf-8") as fh:
            policy = " ".join(fh.read().split())
        for private in ("notes to your future self", "monthly walks", "account map"):
            self.assertIn(private, text)
            self.assertIn(private, policy)
        self.assertIn("asked once at sign-in", policy)
        self.assertIn("stop sharing at any time", text)


# --------------------------------------------------------------------------- #
# the app
# --------------------------------------------------------------------------- #
class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_consent_ask_app_")
        cls.db = os.path.join(cls.dir, "app.db")

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        if os.path.exists(self.db):
            os.remove(self.db)
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        c = portfolio.connect(self.db)
        try:
            self.carol, self.carol_ok = self._two_step(c, "carol", advisor=True)
            prefs.save(c, self.carol, {"advisor_card": {"name": "Carol Lee",
                                                        "firm": "Lee Advisers"}})
            # dana: from before the records - only a 'migration' grant
            self.dana = _signed_in_client(c, self.carol, "dana")
            consent.grant(c, self.dana, self.carol, consent.MIGRATION_TEXT, "migration")
        finally:
            c.close()
        self.label = "Carol Lee, Lee Advisers"

    @staticmethod
    def _two_step(c, name, advisor=False):
        uid = auth.create_user(c, name, PW)
        if advisor:
            auth.set_advisor(c, name, True)
        secret = two_step.new_secret()
        two_step.enable(c, uid, secret, two_step.totp(secret))
        return uid, f"{uid}:{two_step.status(c, uid)['stamp']}"

    @contextlib.contextmanager
    def _app(self, admins=""):
        import yfinance

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                   NORTHWEND_ADMINS=admins)
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline_net.connect):
            yield

    def _at(self, uid, name, page="Dashboard", query=None, **state):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        if uid is not None:
            for k, v in {"user_id": uid, "username": name, "page": page, **state}.items():
                at.session_state[k] = v
        for k, v in (query or {}).items():
            at.query_params[k] = v
        return at

    def _run(self, at):
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        return at

    @staticmethod
    def _keys(at):
        return [b.key for b in at.button]

    @staticmethod
    def _text(at):
        parts = [m.value for m in at.markdown] + [h.proto.body for h in at.get("html")]
        for kind in ("success", "info", "warning", "error", "caption"):
            parts += [str(e.value) for e in getattr(at, kind)]
        return " ".join(parts)

    def _history(self, uid):
        c = portfolio.connect(self.db)
        try:
            return consent.history(c, uid)
        finally:
            c.close()

    def test_keep_sharing_records_the_words_and_the_ask_goes(self):
        with self._app():
            at = self._run(self._at(self.dana, "dana"))
            self.assertIn("consent_keep", self._keys(at))
            text = self._text(at)
            self.assertIn("Sharing with your advisor", text)
            self.assertIn("Carol Lee, Lee Advisers", text)
            self.assertIn("account map", text)
            # it waits, on any page, until answered - and the page is drawn under it
            plan_only = set(self._keys(at))
            at.session_state["page"] = "Plan"
            self._run(at)
            self.assertIn("consent_keep", self._keys(at))
            self.assertTrue(set(self._keys(at)) - plan_only)
            at.button(key="consent_keep").click()
            self._run(at)
            self.assertNotIn("consent_keep", self._keys(at))
            latest = self._history(self.dana)[0]
            self.assertEqual((latest["kind"], latest["how"], latest["advisor_id"]),
                             ("grant", "sign_in_ask", self.carol))
            self.assertEqual(latest["text_shown"], consent.ask_text(self.label))
            self.assertEqual(latest["text_sha256"], consent.text_sha256(latest["text_shown"]))
            # the next sign-in: not asked again; still shared
            at = self._run(self._at(self.dana, "dana"))
            self.assertNotIn("consent_keep", self._keys(at))
            self.assertEqual(len(self._history(self.dana)), 2)
            c = portfolio.connect(self.db)
            try:
                self.assertEqual(advising.advisor_of(c, self.dana), self.carol)
                self.assertEqual(consent.to_ask(c, self.dana), [])
            finally:
                c.close()
            # her sharing record on Account says how
            at = self._run(self._at(self.dana, "dana", "Account"))
            self.assertIn("when we asked you once, at sign-in", self._text(at))

    def test_stop_sharing_confirms_then_ends_it(self):
        with self._app():
            at = self._run(self._at(self.dana, "dana"))
            at.button(key="consent_stop_start").click()
            self._run(at)
            # a simple confirm first: nothing has changed yet
            self.assertIn("Stop sharing with your advisor?", self._text(at))
            self.assertEqual(len(self._history(self.dana)), 1)
            at.button(key="consent_stop_back").click()          # changed her mind
            self._run(at)
            self.assertIn("consent_keep", self._keys(at))
            at.button(key="consent_stop_start").click()
            self._run(at)
            at.button(key="consent_stop_yes").click()
            self._run(at)
            self.assertNotIn("consent_keep", self._keys(at))
            self.assertNotIn("consent_stop_yes", self._keys(at))
            self.assertIn("stopped sharing with your advisor", self._text(at))
            latest = self._history(self.dana)[0]
            self.assertEqual((latest["kind"], latest["how"], latest["advisor_id"]),
                             ("revoke", "client_stop", self.carol))
            self.assertIn("Carol Lee, Lee Advisers, will no longer see your account",
                          latest["text_shown"])
            c = portfolio.connect(self.db)
            try:
                self.assertIsNone(advising.advisor_of(c, self.dana))
                self.assertFalse(auth.can_view(c, self.carol, self.dana))
                self.assertIsNotNone(auth.get_username(c, self.dana))   # her account stays
                (former,) = advising.former_clients(c, self.carol)
                self.assertEqual((former["client_id"], former["ended_by"]),
                                 (self.dana, "client"))
            finally:
                c.close()
            # the advisor's very next run is her own book
            adv = self._run(self._at(self.carol, "carol", "Dashboard", two_step_ok=self.carol_ok,
                                     active_user_id=self.dana))
            self.assertEqual(adv.session_state["active_user_id"], self.carol)

    def test_one_box_at_a_time_the_agreement_first(self):
        c = portfolio.connect(self.db)
        try:
            ed = _signed_in_client(c, self.carol, "ed", agreed=False)
        finally:
            c.close()
        with self._app():
            at = self._run(self._at(ed, "ed"))
            self.assertIn("terms_ok", self._keys(at))
            self.assertNotIn("consent_keep", self._keys(at))
            for box in ("terms_adult", "terms_us", "terms_agree"):
                at.checkbox(key=box).check()
            self._run(at)
            at.button(key="terms_ok").click()
            self._run(at)
            self.assertNotIn("terms_ok", self._keys(at))
            self.assertIn("consent_keep", self._keys(at))   # then the sharing question

    def test_setup_link_clients_are_never_asked(self):
        # one by one or from a file, an advisor's new client goes through the
        # same path (dashboard._add_one_client): create_client, then the setup link
        c = portfolio.connect(self.db)
        try:
            fay = auth.create_client(c, self.carol, "fay@example.com", name="Fay")
            token = auth.create_invite(c, self.carol, fay)
        finally:
            c.close()
        with self._app():
            at = self._run(self._at(None, None, query={"invite": token}))
            shown = consent.setup_link_text(self.label)
            self.assertIn("Carol Lee, Lee Advisers", self._text(at))
            at.text_input(key="invite_pw").input("clientpass1")
            at.text_input(key="invite_pw_again").input("clientpass1")
            for box in ("invite_adult", "invite_us", "invite_agree"):
                at.checkbox(key=box).check()
            at.button(key="FormSubmitter:invite_form-Create my login").click()
            self._run(at)
            self.assertEqual(at.session_state["user_id"], fay)
            self.assertNotIn("consent_keep", self._keys(at))
            (row,) = self._history(fay)
            self.assertEqual((row["kind"], row["how"], row["text_shown"]),
                             ("grant", "setup_link", shown))
            # and at a later sign-in
            at = self._run(self._at(fay, "fay@example.com"))
            self.assertNotIn("consent_keep", self._keys(at))

    def test_never_the_advisor_or_an_admin(self):
        with self._app():
            # carol in dana's account sees what dana sees - but not the ask
            at = self._run(self._at(self.carol, "carol", "Dashboard", two_step_ok=self.carol_ok,
                                    active_user_id=self.dana))
            self.assertEqual(at.session_state["active_user_id"], self.dana)
            self.assertNotIn("consent_keep", self._keys(at))
            # her book says dana hasn't confirmed yet, calmly
            at = self._run(self._at(self.carol, "carol", "Clients", two_step_ok=self.carol_ok,
                                    active_user_id=self.carol))
            self.assertIn("hasn't confirmed sharing yet", self._text(at))
            self.assertIn("we'll ask them once", self._text(at))
        # an admin account that is also linked as a client isn't asked either
        c = portfolio.connect(self.db)
        try:
            ann, ann_ok = self._two_step(c, "ann")
            auth.link_client(c, self.carol, ann)
            auth.record_agreement(c, ann, disclosures.LAST_UPDATED, via=auth.TERMS_VIA_SIGN_IN)
            self.assertEqual(consent.to_ask(c, ann), [self.carol])
        finally:
            c.close()
        with self._app(admins="ann"):
            at = self._run(self._at(ann, "ann", "Dashboard", two_step_ok=ann_ok))
            self.assertNotIn("consent_keep", self._keys(at))
        with self._app():   # (the same account without the admin role is asked)
            at = self._run(self._at(ann, "ann", "Dashboard", two_step_ok=ann_ok))
            self.assertIn("consent_keep", self._keys(at))
        # once dana keeps sharing, the note goes from carol's book
        c = portfolio.connect(self.db)
        try:
            consent.grant(c, self.dana, self.carol, consent.ask_text(self.label), "sign_in_ask")
            consent.grant(c, ann, self.carol, consent.ask_text(self.label), "sign_in_ask")
        finally:
            c.close()
        with self._app():
            at = self._run(self._at(self.carol, "carol", "Clients", two_step_ok=self.carol_ok,
                                    active_user_id=self.carol))
            self.assertNotIn("hasn't confirmed sharing yet", self._text(at))


if __name__ == "__main__":
    unittest.main()
