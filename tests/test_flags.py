"""Feature flags and legal gates (flags.py, docs/PLAN.md "Flags and gates")
and the one-click unsubscribe links (unsubscribe.py, PLAN 1a.8): everything
off with no settings; the environment and Streamlit's secrets both read;
no L4 gate, ever; every feature checked somewhere; _view() skipping a view
whose feature is off and a gated page leaving PAGES; the Monthly Walk (Home
card, Account section, reminder email, the kit's logbook) and the AI
screenshot reader absent when their flags are off and there when on; and
unsubscribe links that turn off the right email for the right person only,
with the List-Unsubscribe headers set and still no figures in the emails.

    python -m unittest tests.test_flags        (from the repo root)
"""

import ast
import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from datetime import date, datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
sys.path.insert(0, TESTS)

import auth  # noqa: E402
import checkin  # noqa: E402
import checkin_email  # noqa: E402
import flags  # noqa: E402
import gear  # noqa: E402, F401
import mailer  # noqa: E402
import settings  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import unsubscribe  # noqa: E402
import weekly_email  # noqa: E402
import test_import_save  # noqa: E402  (its app fixture, for the screenshot tab)
import test_walk  # noqa: E402  (its walkers, for the walk with its flag off)

SETTINGS = (flags.GATES_SETTING, flags.FLAGS_SETTING)


@contextlib.contextmanager
def _settings(env=None, secrets=None):
    """Only these flag settings: `env` in the environment, `secrets` as
    Streamlit's secrets (a dict), nothing else."""
    clean = {k: v for k, v in os.environ.items() if k not in SETTINGS}
    clean.update(env or {})
    with unittest.mock.patch.dict(os.environ, clean, clear=True), \
            unittest.mock.patch.object(flags, "_secret", (secrets or {}).get):
        yield


class FlagTests(unittest.TestCase):

    def test_all_off_with_no_settings(self):
        with _settings():
            for g in flags.GATES:
                self.assertFalse(flags.gate(g))
            for name in flags.FEATURES:
                self.assertFalse(flags.on(name), name)
            s = flags.state()
            self.assertEqual(set(s["gates"].values()), {False})
            self.assertEqual({f["on"] for f in s["flags"].values()}, {False})
            self.assertEqual(s["unknown"], [])
            self.assertFalse(flags.on("no-such-feature"))

    def test_the_environment_is_read(self):
        with _settings({"NORTHWEND_FLAGS": " walk, Screenshot_AI ", "NORTHWEND_GATES": "l0 L3"}):
            self.assertTrue(flags.on("walk"))
            self.assertTrue(flags.on("screenshot_ai"))
            self.assertEqual(flags.gates_on(), {"L0", "L3"})
            self.assertFalse(flags.gate("L1"))

    def test_streamlits_secrets_are_read_a_list_or_a_string(self):
        with _settings(secrets={"NORTHWEND_FLAGS": ["walk"], "NORTHWEND_GATES": "L1,L2"}):
            self.assertTrue(flags.on("walk"))
            self.assertFalse(flags.on("screenshot_ai"))
            self.assertEqual(flags.gates_on(), {"L1", "L2"})
        # the environment first: set there (even empty), the secret isn't looked at
        with _settings({"NORTHWEND_FLAGS": ""}, secrets={"NORTHWEND_FLAGS": "walk"}):
            self.assertFalse(flags.on("walk"))

    def test_the_real_secrets_lookup(self):
        import streamlit

        class Secrets:
            def __init__(self, data):
                self.data = data

            def load_if_toml_exists(self):
                return self.data is not None

            def get(self, k):
                return self.data.get(k)
        clean = {k: v for k, v in os.environ.items() if k not in SETTINGS}
        with unittest.mock.patch.dict(os.environ, clean, clear=True):
            with unittest.mock.patch.object(streamlit, "secrets",
                                            Secrets({"NORTHWEND_FLAGS": ["walk", "x"]})):
                self.assertTrue(flags.on("walk"))
                self.assertEqual(flags.state()["unknown"], ["x"])
            with unittest.mock.patch.object(streamlit, "secrets", Secrets(None)):  # no file
                self.assertFalse(flags.on("walk"))

    def test_there_is_no_l4(self):
        with _settings({"NORTHWEND_GATES": "L0,L1,L2,L3,L4", "NORTHWEND_FLAGS": "walk"}):
            self.assertFalse(flags.gate("L4"))
            self.assertNotIn("L4", flags.gates_on())
            self.assertNotIn("L4", flags.state()["gates"])
            # even a feature that named it could never be on
            with unittest.mock.patch.dict(flags.FEATURES, {"walk": {"gates": ("L4",),
                                                                    "view": None}}):
                self.assertFalse(flags.on("walk"))
        self.assertEqual(flags.GATES, ("L0", "L1", "L2", "L3"))
        for name, f in flags.FEATURES.items():
            self.assertTrue(set(f["gates"]) <= set(flags.GATES), name)
        # no L4 setting anywhere in the app (LEGAL_GATES.md: no flag, nothing built)
        for path in _sources():
            with open(path, encoding="utf-8") as fh:
                self.assertNotIn("GATE_L4", fh.read(), path)

    def test_a_feature_needs_its_flag_and_every_gate(self):
        fake = {"fake": {"gates": ("L1", "L2"), "view": "fake_view", "page": "Fake"}}
        with unittest.mock.patch.dict(flags.FEATURES, fake):
            with _settings({"NORTHWEND_FLAGS": "fake", "NORTHWEND_GATES": "L1"}):
                self.assertFalse(flags.on("fake"))
                self.assertFalse(flags.view_on("fake_view"))
                self.assertFalse(flags.page_on("Fake"))
                self.assertEqual(flags.state()["flags"]["fake"],
                                 {"on": False, "set": True, "needs": ("L1", "L2")})
            with _settings({"NORTHWEND_FLAGS": "fake", "NORTHWEND_GATES": "L1,L2"}):
                self.assertTrue(flags.on("fake"))
                self.assertTrue(flags.view_on("fake_view"))
                self.assertTrue(flags.page_on("Fake"))
            with _settings({"NORTHWEND_GATES": "L1,L2"}):
                self.assertFalse(flags.on("fake"))
        with _settings():   # a view or page no feature owns always runs
            self.assertTrue(flags.view_on("kit"))
            self.assertTrue(flags.page_on("Plan"))

    def test_every_feature_is_checked_somewhere(self):
        code = ""
        for path in _sources():
            if os.path.basename(path) != "flags.py":
                with open(path, encoding="utf-8") as fh:
                    code += fh.read()
        for name, f in flags.FEATURES.items():
            owns_view = f.get("view") and os.path.exists(
                os.path.join(REPO, "views", f"{f['view']}.py"))
            self.assertTrue(f'flags.on("{name}")' in code or owns_view,
                            f"nothing checks the {name!r} flag")

    def test_view_hook_skips_a_view_whose_feature_is_off(self):
        """dashboard._view itself, run against a scratch views folder."""
        with open(os.path.join(REPO, "dashboard.py"), encoding="utf-8") as fh:
            src = fh.read()
        node = next(n for n in ast.parse(src).body
                    if isinstance(n, ast.FunctionDef) and n.name == "_view")
        here = tempfile.mkdtemp(prefix="pt_flags_view_")
        self.addCleanup(shutil.rmtree, here, True)
        os.makedirs(os.path.join(here, "views"))
        with open(os.path.join(here, "views", "fake.py"), "w", encoding="utf-8") as fh:
            fh.write("RAN = True\n")
        fake = {"fake": {"gates": (), "view": "fake", "page": None}}
        for setting, ran in (("", False), ("fake", True)):
            ns = {"os": os, "flags": flags, "HERE": here}
            exec(ast.get_source_segment(src, node), ns)  # noqa: S102
            with unittest.mock.patch.dict(flags.FEATURES, fake), \
                    _settings({"NORTHWEND_FLAGS": setting}):
                ns["_view"]("fake")
            self.assertEqual(ns.get("RAN", False), ran, setting)


def _sources():
    """Every .py file of the app (not the tests or the website)."""
    out = [os.path.join(REPO, f) for f in os.listdir(REPO) if f.endswith(".py")]
    out += [os.path.join(REPO, "views", f) for f in os.listdir(os.path.join(REPO, "views"))
            if f.endswith(".py")]
    return out


# --------------------------------------------------------------------------- #
# in the app: a gated page, the walk with its flag off
# --------------------------------------------------------------------------- #
class WalkOffTests(test_walk._WalkApp):
    FLAGS = ""

    def test_home_says_nothing_about_walks_and_the_data_stays(self):
        before = self._prefs(self.dana)
        with self._run(self.dana, "dana") as at:
            text = self._text(at)
            for words in ("monthly walk", "Walks finished", "Your plan said", "Logbook"):
                self.assertNotIn(words, text)
            self.assertFalse([k for k in self._keys(at) if k.startswith("walk_")])
            # the kit, without the logbook (nor the rope: she's an advisor's client)
            self.assertIn("of 7 earned", text)
        after = self._prefs(self.dana)
        for k in (checkin.PREF_LOG, checkin.PREF_STATE, checkin.PREF_VERDICTS):
            self.assertEqual(after[k], before[k])
        self.assertEqual(len(test_walk.feature_counts.walk_days(after)), 1)   # still counted

    def test_account_has_no_monthly_walk_section(self):
        with self._run(self.wren, "wren", "Account") as at:
            self.assertNotIn("Monthly walk", [s.value for s in at.subheader])
            self.assertNotIn("acct_checkin_email", [t.key for t in at.toggle])

    def test_with_the_flag_on_both_are_back(self):
        self.FLAGS = "walk"
        with self._run(self.wren, "wren") as at:
            self.assertIn("The monthly walk", self._text(at))
            self.assertIn("of 9 earned", self._text(at))
        with self._run(self.wren, "wren", "Account") as at:
            self.assertIn("Monthly walk", [s.value for s in at.subheader])
            self.assertIn("acct_checkin_email", [t.key for t in at.toggle])

    def test_a_gated_page_leaves_pages(self):
        """A FEATURES entry owning a page (a fake one): with its flag off the
        page can't be opened - the app goes to the first page instead."""
        with self._run(self.wren, "wren", "About") as at:       # first run settles the modules
            self.assertEqual(at.session_state["page"], "About")
        fake = {"fake": {"gates": (), "view": None, "page": "About"}}
        with unittest.mock.patch.dict(sys.modules["flags"].FEATURES, fake):
            with self._run(self.wren, "wren", "About") as at:
                self.assertEqual(at.session_state["page"], "Dashboard")
            self.FLAGS = "fake"
            with self._run(self.wren, "wren", "About") as at:
                self.assertEqual(at.session_state["page"], "About")


class ScreenshotFlagTests(test_import_save._AppBase):
    USERNAME = "shots"

    @classmethod
    def seed(cls, c):
        test_import_save.AppSaveTests.seed.__func__(cls, c)

    def _dialog(self, setting):
        at = self._app(open_dialog="manual")
        os.environ["NORTHWEND_FLAGS"] = setting   # (_app's patch puts it back)
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        return at

    def test_hidden_when_off_with_a_calm_way_instead(self):
        at = self._dialog("")
        self.assertIn(self._screens_off(), [c.value for c in at.caption])
        self.assertNotIn("me_shots_btn", [b.key for b in at.button])
        self.assertFalse([c for c in at.checkbox if (c.key or "").startswith("me_shots_ok")])

    def test_there_when_on(self):
        at = self._dialog("screenshot_ai")
        self.assertIn("me_shots_btn", [b.key for b in at.button])
        self.assertNotIn(self._screens_off(), [c.value for c in at.caption])

    @staticmethod
    def _screens_off():
        path = os.path.join(REPO, "views", "holdings_input.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        node = next(n for n in tree.body if isinstance(n, ast.Assign)
                    and getattr(n.targets[0], "id", "") == "SCREENSHOTS_OFF")
        return ast.literal_eval(node.value)


# --------------------------------------------------------------------------- #
# the walk's reminder email with its flag off; one-click unsubscribe
# --------------------------------------------------------------------------- #
class _DB(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_flags_")
        self.db = os.path.join(self.dir, "t.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.conn = portfolio.connect(self.db)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _person(self, name, *, advisor=False):
        c = self.conn
        uid = auth.create_user(c, name, "pw-123456789")
        if advisor:
            auth.set_advisor(c, name, True)
        c.execute("UPDATE users SET email = ?, email_verified_at = ? WHERE id = ?",
                  (f"{name}@example.com", "2026-09-01T10:00:00Z", uid))
        c.commit()
        prefs.save(c, uid, {checkin.PREF_SINCE: "2026-08", checkin.PREF_EMAIL: True})
        return uid


class WalkEmailFlagTests(_DB):
    TODAY = date(2026, 10, 5)

    def test_nothing_is_sent_while_the_walk_is_off(self):
        self._person("yes")
        sent = []
        with _settings():
            done = checkin_email.run(self.conn, "https://app.example/", self.TODAY,
                                     send=lambda *a: sent.append(a) or True)
            self.assertEqual((done["sent"], sent), (0, []))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(checkin_email.main(["--db", self.db, "--app-url",
                                                     "https://x/"]), 0)
            self.assertIn("isn't turned on", out.getvalue())
        self.assertEqual(self.conn.execute("SELECT COUNT(*) AS n FROM email_tokens")
                         .fetchone()["n"], 0)
        with _settings({"NORTHWEND_FLAGS": "walk"}):
            done = checkin_email.run(self.conn, "https://app.example/", self.TODAY,
                                     send=lambda *a: sent.append(a) or True)
        self.assertEqual(done["sent"], 1)
        to, link, unsub = sent[0]
        self.assertEqual((to, link), ("yes@example.com", "https://app.example/?page=dashboard"))
        self.assertTrue(unsub.startswith("https://app.example/?unsubscribe="))

    def test_the_link_turns_off_that_reminder(self):
        yes = self._person("yes")
        sent = []
        with _settings({"NORTHWEND_FLAGS": "walk"}):
            checkin_email.run(self.conn, "https://app.example/", self.TODAY,
                              send=lambda *a: sent.append(a) or True)
        token = sent[0][2].split("?unsubscribe=", 1)[1]
        self.assertEqual(unsubscribe.use(self.conn, token), {"ok": True, "kind": "walk"})
        self.assertIs(prefs.load(self.conn, yes)[checkin.PREF_EMAIL], False)
        self.assertEqual(checkin_email.recipients(self.conn), [])


class UnsubscribeTests(_DB):

    def test_the_right_email_for_the_right_person_only(self):
        c = self.conn
        ann, bob = self._person("ann"), self._person("bob", advisor=True)
        walk = unsubscribe.new_token(c, ann, "walk", "ann@example.com")
        week = unsubscribe.new_token(c, bob, "weekly", "bob@example.com")
        self.assertEqual(unsubscribe.use(c, walk), {"ok": True, "kind": "walk"})
        self.assertIs(prefs.load(c, ann)[checkin.PREF_EMAIL], False)
        self.assertNotIn(weekly_email.PREF_OFF, prefs.load(c, ann))
        self.assertIs(prefs.load(c, bob)[checkin.PREF_EMAIL], True)      # not bob's
        self.assertEqual(unsubscribe.use(c, walk)["ok"], True)          # a second click: same
        self.assertEqual(unsubscribe.use(c, week), {"ok": True, "kind": "weekly"})
        self.assertIs(prefs.load(c, bob)[weekly_email.PREF_OFF], True)
        self.assertIs(prefs.load(c, bob)[checkin.PREF_EMAIL], True)      # only that email

    def test_a_wrong_or_other_kind_of_token_does_nothing(self):
        c = self.conn
        ann = self._person("ann")
        reset = auth.request_password_reset(c, "ann@example.com")["token"]
        for wrong in (None, "", "not-a-token", reset, reset[:-1]):
            self.assertEqual(unsubscribe.use(c, wrong), {"ok": False, "kind": None})
        self.assertIs(prefs.load(c, ann)[checkin.PREF_EMAIL], True)
        # and an unsubscribe token opens nothing else: not a reset, not a confirm
        token = unsubscribe.new_token(c, ann, "walk", "ann@example.com")
        self.assertIsNone(auth.reset_info(c, token))
        self.assertFalse(auth.confirm_email(c, token)["ok"])
        # past its date, or after the account's email changed: nothing
        later = datetime(2030, 1, 1)
        self.assertFalse(unsubscribe.use(c, token, now=later)["ok"])
        c.execute("UPDATE users SET email = 'ann.new@example.com' WHERE id = ?", (ann,))
        c.commit()
        self.assertFalse(unsubscribe.use(c, token)["ok"])
        self.assertIs(prefs.load(c, ann)[checkin.PREF_EMAIL], True)

    def test_only_a_hash_is_kept_and_earlier_links_keep_working(self):
        c = self.conn
        ann = self._person("ann")
        first = unsubscribe.new_token(c, ann, "walk", "ann@example.com")
        unsubscribe.new_token(c, ann, "walk", "ann@example.com")   # next month's email
        stored = [r["token_hash"] for r in c.execute("SELECT token_hash FROM email_tokens")]
        self.assertEqual(len(stored), 2)
        self.assertNotIn(first, stored)
        self.assertTrue(unsubscribe.use(c, first)["ok"])

    def test_weekly_email_carries_a_link(self):
        c = self.conn
        carol = self._person("carol", advisor=True)
        client = auth.create_user(c, "client one", "x" * 12)
        auth.link_client(c, carol, client)
        sent = []
        weekly_email.run(c, "https://app.example/", date(2026, 10, 5),
                         send=lambda *a: sent.append(a) or True)
        token = sent[0][3].split("?unsubscribe=", 1)[1]
        self.assertEqual(unsubscribe.use(c, token), {"ok": True, "kind": "weekly"})
        self.assertIs(prefs.load(c, carol)[weekly_email.PREF_OFF], True)


class HeaderTests(unittest.TestCase):
    """What goes to Resend: the List-Unsubscribe headers, the link in the
    email - and still no figures."""

    def _sent(self, fn):
        bodies = []

        class Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def urlopen(req, timeout=None):
            bodies.append(json.loads(req.data.decode("utf-8")))
            return Resp()
        env = {k: v for k, v in os.environ.items() if k != "MAIL_DRY_RUN"}
        env["RESEND_API_KEY"] = "re_test_unused"
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(settings, "load_env", lambda *a, **k: {}), \
                unittest.mock.patch("urllib.request.urlopen", urlopen):
            self.assertTrue(fn())
        return bodies[0]

    def _check(self, body, unsub):
        self.assertEqual(body["headers"], {"List-Unsubscribe": f"<{unsub}>",
                                           "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"})
        self.assertIn(unsub, body["text"])
        self.assertIn(unsub, body["html"])
        said = body["text"].split("https://", 1)[0]   # the words, before any link
        for figure in ("$", "%"):
            self.assertNotIn(figure, said)

    def test_the_walk_reminder(self):
        unsub = "https://app.example/?unsubscribe=abc123"
        body = self._sent(lambda: checkin_email.reminder("a@example.com", "https://app.example/",
                                                         unsub))
        self._check(body, unsub)
        self.assertIsNone(re.search(r"\d{2,}", body["text"].split("https://", 1)[0]))

    def test_the_monday_email(self):
        unsub = "https://app.example/?unsubscribe=xyz789"
        body = self._sent(lambda: mailer.advisor_week("a@example.com", "https://app.example/",
                                                      ["1 client is due a review"], unsub))
        self._check(body, unsub)

    def test_no_headers_without_a_link(self):
        body = self._sent(lambda: mailer.confirm_email("a@example.com", "https://x/", 3))
        self.assertNotIn("headers", body)
        self.assertEqual(mailer.unsubscribe_headers(""), {})


class UnsubscribePageTests(unittest.TestCase):
    """?unsubscribe=<token> before sign-in: the email turned off, a calm page,
    nothing about the account."""

    @classmethod
    def setUpClass(cls):
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or "")) == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_unsub_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.ann = auth.create_user(c, "ann.private", "pw-123456789")
            cls.bob = auth.create_user(c, "bob.private", "pw-123456789")
            for uid, name in ((cls.ann, "ann.private"), (cls.bob, "bob.private")):
                c.execute("UPDATE users SET email = ?, email_verified_at = ? WHERE id = ?",
                          (f"{name}@example.com", "2026-09-01T10:00:00Z", uid))
                c.commit()
                prefs.save(c, uid, {checkin.PREF_EMAIL: True})
            cls.token = unsubscribe.new_token(c, cls.ann, "walk", "ann.private@example.com")
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _open(self, token):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        at.query_params["unsubscribe"] = token
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1")
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            at.run()
        self.assertEqual([e.message for e in at.exception], [])
        text = " ".join([m.value for m in at.markdown] + [str(s.value) for s in at.success]
                        + [str(i.value) for i in at.info])
        for private in ("ann.private", "bob.private", "@example.com"):
            self.assertNotIn(private, text)                   # nothing about the account
        self.assertNotIn("user_id", at.session_state)          # nobody signed in
        return text

    def _pref(self, uid):
        c = portfolio.connect(self.db)
        try:
            return prefs.load(c, uid)[checkin.PREF_EMAIL]
        finally:
            c.close()

    def test_a_wrong_link_changes_nothing(self):
        text = self._open("not-a-real-token")
        self.assertIn("This link isn't working any more", text)
        self.assertIs(self._pref(self.ann), True)

    def test_the_link_turns_off_that_persons_reminder(self):
        text = self._open(self.token)
        self.assertIn("You won't get these emails any more. You can turn them back on in "
                      "Account, under Monthly walk.", text)
        self.assertIs(self._pref(self.ann), False)
        self.assertIs(self._pref(self.bob), True)


if __name__ == "__main__":
    unittest.main()
