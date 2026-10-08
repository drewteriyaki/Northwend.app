"""Send feedback (feedback.py, views/feedback.py): the name menu's item for
everyone signed in, its window, what the email to the team holds - and
doesn't - the reply-to only when ticked, the rate limit, and that nothing but
the limit's count is written. Runs dashboard.py with streamlit's AppTest on a
scratch database in a temp dir, with mailer.send recorded instead of sent.

    python -m unittest tests.test_feedback        (from the repo root)
"""

import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import auth  # noqa: E402
import disclosures  # noqa: E402
import feedback  # noqa: E402
import mailer  # noqa: E402
import portfolio  # noqa: E402
import rate_limits  # noqa: E402
import two_step  # noqa: E402
from tests import offline as offline_net  # noqa: E402

PW = "pw-123456789"
SNAP = "2026-10-01"
ACCOUNT = "Brokerage ...483"
# distinctive figures: none of them may ever appear in a feedback email
SHARES, VALUE, CASH = 7319.0, 864257.0, 51973.0
FIGURES = ("7319", "7,319", "864257", "864,257", "51973", "51,973", "483")
WORDS = "The chart on this page is hard to read on my phone."


def _holdings(c, uid):
    row = {k: None for k in portfolio.POSITION_COLS}
    row.update(snapshot_date=SNAP, account=ACCOUNT, symbol="QQQM", description="QQQM fund",
               asset_type="ETF", quantity=SHARES, cost_basis=VALUE, market_value=VALUE)
    portfolio.write_snapshot(c, uid, {"snapshot_date": SNAP, "as_of_text": "as of"}, [row],
                             {ACCOUNT: {"cash_value": CASH, "reported_cost_basis": None,
                                        "reported_market_value": None, "reported_gain": None,
                                        "reported_gain_pct": None}}, "statement.csv")
    c.commit()


class FeedbackWordsTests(unittest.TestCase):
    """feedback.py on its own: no Streamlit, no database."""

    def test_empty_and_too_long_are_refused(self):
        self.assertEqual(feedback.problem(""), feedback.EMPTY)
        self.assertEqual(feedback.problem("   \n "), feedback.EMPTY)
        self.assertEqual(feedback.problem(None), feedback.EMPTY)
        self.assertEqual(feedback.problem("x" * (feedback.MAX_CHARS + 1)), feedback.TOO_LONG)
        self.assertIsNone(feedback.problem("x" * feedback.MAX_CHARS))

    def test_the_reference_tells_logins_apart_without_naming_them(self):
        a, b = feedback.reference(12), feedback.reference(13)
        self.assertEqual(a, feedback.reference(12))
        self.assertNotEqual(a, b)
        self.assertEqual(len(a), 10)
        self.assertTrue(re.fullmatch(r"[0-9a-f]{10}", a))

    def test_the_email_says_what_it_is_and_nothing_more(self):
        subject, text = feedback.compose(WORDS, "confusing", page="Home", version="abc1234",
                                         copy="Live", login_id=7, reply=False)
        self.assertEqual(subject, "Northwend feedback: Something's confusing")
        for line in ("Kind: Something's confusing", "Page: Home", "Copy: Live",
                     "Version: abc1234", f"Reference: {feedback.reference(7)}",
                     "Reply: they didn't ask for one", WORDS):
            self.assertIn(line, text)
        # an unknown kind is Other; long words are cut
        subject, text = feedback.compose("y" * 3000, "nonsense", page="", version="",
                                         copy="Staging", login_id=7, reply=True)
        self.assertEqual(subject, "Northwend feedback: Other")
        self.assertIn("y" * feedback.MAX_CHARS, text)
        self.assertNotIn("y" * (feedback.MAX_CHARS + 1), text)
        self.assertIn("Reply: they'd like a reply", text)

    def test_reply_to_goes_to_mailer_only_when_given(self):
        sent = []
        with unittest.mock.patch.object(mailer, "send",
                                        side_effect=lambda *a, **k: sent.append((a, k)) or True):
            feedback.send(WORDS, "idea", page="Plan", version="v", copy="Live", login_id=3)
            feedback.send(WORDS, "idea", page="Plan", version="v", copy="Live", login_id=3,
                          reply_email="ann@example.com")
        self.assertIsNone(sent[0][1]["reply_to"])
        self.assertEqual(sent[1][1]["reply_to"], "ann@example.com")
        self.assertEqual(sent[0][0][0], mailer._admin_to())

    def test_mailer_reply_to_is_one_clean_address(self):
        out = []
        with unittest.mock.patch.dict(os.environ, {"MAIL_DRY_RUN": "1"}), \
                unittest.mock.patch("sys.stderr") as err:
            err.write.side_effect = out.append
            mailer.send("x@example.com", "s", "t", reply_to='ann@example.com\r\nBcc: <evil>')
            mailer.send("x@example.com", "s", "t")
        log = "".join(out)
        self.assertIn("reply_to=ann@example.com Bcc: evil", log)   # one line, no brackets
        self.assertIn(f"reply_to={mailer.REPLY_TO}", log)

    def test_the_rate_limit_is_five_an_hour_and_twenty_a_day(self):
        self.assertEqual(rate_limits.LIMITS[rate_limits.FEEDBACK], (5, 20))


class FeedbackAppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # put back the repo's modules afterwards, for the other test files
        cls.modules = {n: m for n, m in sys.modules.items() if os.path.dirname(
            os.path.abspath(getattr(m, "__file__", None) or "")) == REPO}
        cls.tmp = tempfile.mkdtemp()
        cls.db = os.path.join(cls.tmp, "feedback.db")
        c = portfolio.connect(cls.db)
        try:
            cls.alice = auth.create_user(c, "alice", PW)      # an investor, with an email
            _holdings(c, cls.alice)
            c.execute("UPDATE users SET email = ?, email_verified_at = ? WHERE id = ?",
                      ("alice@example.com", "2026-09-01 10:00:00", cls.alice))
            cls.bob = auth.create_user(c, "bob", PW)          # no email
            cls.carol = auth.create_user(c, "carol", PW)      # an advisor
            auth.set_advisor(c, "carol", True)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            c.execute("UPDATE users SET email = ?, email_verified_at = ? WHERE id = ?",
                      ("carol@example.com", "2026-09-01 10:00:00", cls.carol))
            cls.dave = auth.create_user(c, "dave", PW)        # her client
            auth.link_client(c, cls.carol, cls.dave)
            _holdings(c, cls.dave)
            c.execute("UPDATE users SET email = ?, email_verified_at = ? WHERE id = ?",
                      ("dave@example.com", "2026-09-01 10:00:00", cls.dave))
            cls.ann = auth.create_user(c, "ann", PW)          # an admin
            secret = two_step.new_secret()
            two_step.enable(c, cls.ann, secret, two_step.totp(secret))
            cls.ann_ok = f"{cls.ann}:{two_step.status(c, cls.ann)['stamp']}"
            # everyone has agreed to the disclosures (no "one quick thing" note)
            c.execute("UPDATE users SET terms_version = ?", (disclosures.LAST_UPDATED,))
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.sent = []

    def _record(self, to, subject, text, html=None, **kw):
        self.sent.append({"to": to, "subject": subject, "text": text, **kw})
        return True

    def _run(self, uid, name, page="Plan", admins="", **state):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": page, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "RESEND_API_KEY", "ANTHROPIC_API_KEY",
                            "NORTHWEND_ADMINS", "ALERT_EMAIL", "NORTHWEND_ENV")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1")
        if admins:
            env["NORTHWEND_ADMINS"] = admins
        for p in (unittest.mock.patch.dict(os.environ, env, clear=True),
                  unittest.mock.patch("socket.socket.connect", offline_net.connect)):
            p.start()
            self.addCleanup(p.stop)
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        # the app's first run may reload the repo's modules (codefresh.py): the
        # app's own mailer is the one to record
        self._mailer = sys.modules["mailer"]
        p = unittest.mock.patch.object(self._mailer, "send", side_effect=self._record)
        p.start()
        self.addCleanup(p.stop)
        return at

    def _menu(self, at):
        pops = {p.proto.id.rsplit("-", 1)[-1]: p for p in at.get("popover")}
        return pops["pt_me"]

    def _open(self, at):
        self._menu(at).button(key="menu_feedback").click()
        at.run()
        self.assertEqual([e.message for e in at.exception], [])
        return at

    @staticmethod
    def _text(at):
        return " ".join(str(getattr(e, "value", "") or getattr(e, "body", "") or "")
                        for kind in ("markdown", "caption", "success", "warning", "info")
                        for e in at.get(kind))

    def _counts(self):
        c = sqlite3.connect(self.db)
        try:
            names = [r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%'")]
            return {n: c.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0] for n in names}
        finally:
            c.close()

    def _clear_counts(self):
        c = sqlite3.connect(self.db)
        try:
            c.execute("DELETE FROM email_sends WHERE purpose = ?",
                      (rate_limits.PURPOSE_PREFIX + rate_limits.FEEDBACK,))
            c.commit()
        finally:
            c.close()

    def test_in_the_name_menu_for_everyone(self):
        cases = [(self.alice, "alice", {}, ""), (self.bob, "bob", {}, ""),
                 (self.dave, "dave", {}, ""),
                 (self.carol, "carol", {"active_user_id": self.dave,
                                        "two_step_ok": self.carol_ok}, ""),
                 (self.ann, "ann", {"two_step_ok": self.ann_ok}, "ann")]
        for uid, name, state, admins in cases:
            with self.subTest(name):
                at = self._run(uid, name, "About", admins=admins, **state)
                keys = [b.key for b in self._menu(at).button]
                self.assertIn("menu_feedback", keys)
                self.assertEqual(keys[keys.index("menu_feedback") + 1], "pt_theme")
                self.assertIn("Send feedback", at.button(key="menu_feedback").label)
                # and on the About page itself
                self.assertEqual(at.button(key="about_feedback").label, "Send feedback")

    def test_the_window_refuses_an_empty_message_and_sends_one_with_words(self):
        self._clear_counts()
        at = self._open(self._run(self.alice, "alice", "Plan"))
        text = self._text(at)
        self.assertIn(feedback.INTRO, text)
        self.assertIn(feedback.PRIVATE, text)
        self.assertEqual([o for o in at.radio(key="fb_kind").options],
                         [w for _, w in feedback.KINDS])
        self.assertFalse(at.checkbox(key="fb_reply").value)    # off by default
        # empty: refused, nothing sent, nothing counted
        before = self._counts()
        at.button(key="fb_send").click().run()
        self.assertIn(feedback.EMPTY, self._text(at))
        self.assertEqual(self.sent, [])
        self.assertEqual(self._counts(), before)
        # words: sent, thanks in the window
        at.radio(key="fb_kind").set_value("broken")
        at.text_area(key="fb_words").input(WORDS)
        at.button(key="fb_send").click().run()
        self.assertEqual([e.message for e in at.exception], [])
        self.assertIn(feedback.THANKS, self._text(at))
        self.assertEqual(len(self.sent), 1)
        mail = self.sent[0]
        self.assertEqual(mail["to"], mailer._admin_to())
        self.assertEqual(mail["subject"], "Northwend feedback: Something's broken")
        self.assertIn(WORDS, mail["text"])
        self.assertIn("Page: Plan", mail["text"])
        self.assertIn("Copy: Local", mail["text"])
        self.assertIn(f"Reference: {feedback.reference(self.alice)}", mail["text"])
        # no reply asked for: no address, no login number, no figures
        self.assertIsNone(mail.get("reply_to"))
        self.assertNotIn("alice", mail["text"])
        self.assertNotIn("@example.com", mail["text"])
        self.assertNotIn(f"user {self.alice}", mail["text"])
        for figure in FIGURES:
            self.assertNotIn(figure, mail["text"])
            self.assertNotIn(figure, mail["subject"])
        # only the rate-limit count was written
        after = self._counts()
        changed = {t: after[t] - before[t] for t in after if after[t] != before.get(t)}
        self.assertEqual(changed, {"email_sends": 1})
        # Close ends it
        at.button(key="fb_close").click().run()
        self.assertNotIn(feedback.THANKS, self._text(at))
        self.assertFalse(at.session_state["fb_open"] if "fb_open" in at.session_state else False)

    def test_reply_to_only_when_ticked(self):
        self._clear_counts()
        at = self._open(self._run(self.alice, "alice", "Plan"))
        at.text_area(key="fb_words").input(WORDS)
        at.checkbox(key="fb_reply").check()
        at.button(key="fb_send").click().run()
        self.assertEqual(self.sent[-1]["reply_to"], "alice@example.com")
        self.assertNotIn("alice@example.com", self.sent[-1]["text"])   # a header, not the body
        self.assertIn("Reply: they'd like a reply", self.sent[-1]["text"])

    def test_no_email_no_reply_box(self):
        at = self._open(self._run(self.bob, "bob", "Plan"))
        self.assertNotIn("fb_reply", [c.key for c in at.checkbox])
        self.assertIn(feedback.NO_EMAIL, self._text(at))

    def test_an_advisor_in_a_clients_account_sends_as_themselves(self):
        self._clear_counts()
        at = self._open(self._run(self.carol, "carol", "Plan", active_user_id=self.dave,
                                  two_step_ok=self.carol_ok))
        at.text_area(key="fb_words").input(WORDS)
        at.checkbox(key="fb_reply").check()
        at.button(key="fb_send").click().run()
        mail = self.sent[-1]
        self.assertEqual(mail["reply_to"], "carol@example.com")    # hers, never the client's
        self.assertIn(f"Reference: {feedback.reference(self.carol)}", mail["text"])
        self.assertNotIn(feedback.reference(self.dave), mail["text"])
        for word in ("dave", *FIGURES):
            self.assertNotIn(word, mail["text"])

    def test_the_rate_limit_stops_a_sixth_in_an_hour(self):
        self._clear_counts()
        c = portfolio.connect(self.db)
        try:
            now = datetime.now(timezone.utc)
            for i in range(rate_limits.LIMITS[rate_limits.FEEDBACK][0]):
                self.assertTrue(rate_limits.allow(c, self.bob, rate_limits.FEEDBACK,
                                                  now=now - timedelta(minutes=10 + i)))
        finally:
            c.close()
        at = self._open(self._run(self.bob, "bob", "Plan"))
        at.text_area(key="fb_words").input(WORDS)
        at.button(key="fb_send").click().run()
        self.assertEqual(self.sent, [])
        self.assertIn(rate_limits.CALM, self._text(at))
        self.assertNotIn(feedback.THANKS, self._text(at))
        self._clear_counts()

    def test_a_failed_send_says_so_calmly(self):
        self._clear_counts()
        at = self._open(self._run(self.bob, "bob", "Plan"))
        at.text_area(key="fb_words").input(WORDS)
        with unittest.mock.patch.object(self._mailer, "send", return_value=False):
            at.button(key="fb_send").click().run()
        self.assertIn(feedback.NOT_SENT, self._text(at))
        self.assertNotIn(feedback.THANKS, self._text(at))


if __name__ == "__main__":
    unittest.main()
