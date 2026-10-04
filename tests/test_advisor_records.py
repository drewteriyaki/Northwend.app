"""Advisors' records and clients' consent: a client agrees to the About and
disclosures at their setup link (and an account made for someone who never
did is asked once, at sign-in); advisor notes are archived, never deleted,
and an edit keeps the earlier text; an advisor can export a client's record
(or all of them) - only their own clients, never another advisor's records
or anyone's secrets. Pure logic on a scratch database, plus the pages with
streamlit's AppTest.

    python -m unittest tests.test_advisor_records        (from the repo root)
"""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock
import zipfile
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import admin  # noqa: E402
import advising  # noqa: E402
import auth  # noqa: E402
import export  # noqa: E402
import portfolio  # noqa: E402
import proposals  # noqa: E402
import reports  # noqa: E402
import two_step  # noqa: E402
import weekly_email  # noqa: E402

NOW = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
AGREE = dict(agreed=True, adult=True, terms_version="October 1, 2026")


class _DB(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_records_")
        self.db = os.path.join(self.dir, "t.db")
        self.conn = portfolio.connect(self.db)
        c = self.conn
        self.carol = auth.create_user(c, "carol", "pw-123456789")
        auth.set_advisor(c, "carol", True)
        self.dana = auth.create_client(c, self.carol, "dana@example.com", name="Dana Lee")
        # another advisor, with a client of their own
        self.omar = auth.create_user(c, "omar", "pw-123456789")
        auth.set_advisor(c, "omar", True)
        self.zed = auth.create_client(c, self.omar, "zed", name="Zed")

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _row(self, uid):
        return self.conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()


class ConsentTests(_DB):

    def test_the_setup_link_needs_both_boxes_and_keeps_the_version(self):
        token = auth.create_invite(self.conn, self.carol, self.dana, now=NOW)
        no_age = auth.accept_invite(self.conn, token, "clientpass1", agreed=True,
                                    terms_version="v", now=NOW)
        self.assertEqual((no_age["ok"], no_age["error"]), (False, "Accounts are for people 18 "
                                                           "and over - tick the box to confirm."))
        no_agree = auth.accept_invite(self.conn, token, "clientpass1", adult=True,
                                      terms_version="v", now=NOW)
        self.assertEqual(no_agree["error"], "Tick the box to agree to the About and disclosures.")
        no_version = auth.accept_invite(self.conn, token, "clientpass1", agreed=True, adult=True,
                                        now=NOW)
        self.assertFalse(no_version["ok"])
        # none of those used the link up or set anything
        self.assertIsNotNone(auth.invite_info(self.conn, token, now=NOW))
        self.assertFalse(auth.has_agreed(self.conn, self.dana))
        self.assertIsNone(auth.verify_login(self.conn, "dana@example.com", "clientpass1"))

        ok = auth.accept_invite(self.conn, token, "clientpass1", now=NOW, **AGREE)
        self.assertTrue(ok["ok"])
        row = self._row(self.dana)
        self.assertEqual((row["terms_version"], row["terms_accepted_at"], row["terms_via"]),
                         ("October 1, 2026", "2026-10-04 12:00:00", auth.TERMS_VIA_SETUP_LINK))
        self.assertTrue(auth.login_facts(self.conn, self.dana)["agreed"])
        # still an account an advisor made, not a sign-up of their own
        self.assertFalse(auth.made_by_themselves(row))
        dana = {a["id"]: a for a in admin.list_accounts(self.conn)}[self.dana]
        self.assertFalse(dana["signed_up"])
        self.assertEqual(dana["terms_version"], "October 1, 2026")

    def test_agreeing_later_keeps_how_the_account_was_made(self):
        # an advisor an admin made, with an unconfirmed email: agreeing at
        # sign-in doesn't turn them into a "made it themselves" account
        auth.record_agreement(self.conn, self.carol, "v1", via=auth.TERMS_VIA_SIGN_IN, now=NOW)
        self.conn.execute("UPDATE users SET email = 'carol@example.com' WHERE id = ?",
                          (self.carol,))
        self.conn.commit()
        self.assertTrue(auth.has_agreed(self.conn, self.carol))
        self.assertEqual(proposals.who_to_tell(self.conn, self.carol)["email"],
                         "carol@example.com")
        self.assertIn(self.carol, [r["id"] for r in weekly_email.recipients(self.conn)])
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_ADMINS": "carol"}):
            self.assertTrue(admin.is_admin(self.conn, self.carol))
        # a new version later: where they first agreed is kept
        auth.record_agreement(self.conn, self.carol, "v2", via=auth.TERMS_VIA_SETUP_LINK)
        row = self._row(self.carol)
        self.assertEqual((row["terms_version"], row["terms_via"]), ("v2", auth.TERMS_VIA_SIGN_IN))
        # a real sign-up is still told apart
        made = auth.sign_up(self.conn, "sam@example.com", "pw-123456789", seconds_open=10, **AGREE)
        self.assertTrue(auth.made_by_themselves(self._row(made["user_id"])))

    def test_licence_checked_is_what_the_admin_sees(self):
        nia = auth.sign_up(self.conn, "nia@example.com", "pw-123456789", seconds_open=10,
                           **AGREE)["user_id"]
        auth.request_advisor(self.conn, nia, "Nia Wealth", "1234567")
        admin.approve_advisor(self.conn, "nia@example.com")
        rows = {a["id"]: a for a in admin.list_accounts(self.conn)}
        self.assertTrue(rows[nia]["licence_checked"])
        self.assertIsNone(rows[self.carol]["licence_checked"])   # made an advisor directly


class ArchiveTests(_DB):

    def test_archive_hides_restore_brings_back_and_nothing_is_deleted(self):
        c = self.conn
        advising.add_note(c, self.dana, self.carol, "Review", "Met to review the plan",
                          "2026-09-01")
        advising.add_note(c, self.dana, self.carol, "Next step", "Open a Roth IRA", "2026-09-01")
        review, step = sorted(advising.list_notes(c, self.dana, include_private=True),
                              key=lambda n: n["id"])
        self.assertTrue(advising.archive_note(c, self.dana, step["id"], now=NOW))
        self.assertFalse(advising.archive_note(c, self.zed, review["id"]))   # not Zed's note
        # hidden from the client and the advisor's normal view, and from the counts
        for private in (False, True):
            self.assertEqual([n["id"] for n in advising.list_notes(c, self.dana,
                                                                   include_private=private)],
                             [review["id"]])
        self.assertEqual(advising.open_next_steps(
            advising.notes_for(c, [self.dana], include_private=False)[self.dana]), [])
        advising.archive_note(c, self.dana, review["id"])
        self.assertIsNone(advising.last_review(c, self.dana))
        self.assertEqual(reports.build(c, self.dana, NOW.date(), NOW.date(), value_now=None,
                                       today=NOW.date())["next_steps"], [])
        # kept, and the advisor's Show archived lists them
        archived = advising.list_notes(c, self.dana, include_private=True, archived=True)
        self.assertEqual({n["id"] for n in archived}, {review["id"], step["id"]})
        self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM advisor_notes").fetchone()["n"], 2)
        self.assertTrue(advising.restore_note(c, self.dana, step["id"]))
        self.assertEqual([n["body"] for n in advising.list_notes(c, self.dana,
                                                                 include_private=False)],
                         ["Open a Roth IRA"])
        self.assertFalse(hasattr(advising, "delete_note"))

    def test_an_edit_keeps_the_earlier_text(self):
        c = self.conn
        advising.add_note(c, self.dana, self.carol, "Note", "Moving to $500 a month",
                          "2026-09-01")
        (note,) = advising.list_notes(c, self.dana, include_private=True)
        self.assertTrue(advising.edit_note(c, self.dana, note["id"], "Moving to $600 a month",
                                           now=NOW))
        self.assertFalse(advising.edit_note(c, self.dana, note["id"], "Moving to $600 a month"))
        self.assertFalse(advising.edit_note(c, self.zed, note["id"], "Not yours"))
        with self.assertRaises(ValueError):
            advising.edit_note(c, self.dana, note["id"], "  ")
        (note,) = advising.list_notes(c, self.dana, include_private=False)
        self.assertEqual((note["body"], note["edited_at"]),
                         ("Moving to $600 a month", "2026-10-04 12:00:00"))
        (earlier,) = advising.note_history(note)
        self.assertEqual((earlier["body"], earlier["replaced_at"]),
                         ("Moving to $500 a month", "2026-10-04 12:00:00"))
        # the client's own export has the note as it is now, not the earlier text
        files = _unzip(export.export_zip(c, self.dana))
        self.assertIn("$600", files["from_your_advisor_notes.csv"])
        self.assertNotIn("$500", files["from_your_advisor_notes.csv"])

    def test_messages_are_marked_and_archived_ones_leave_the_clients_export(self):
        c = self.conn
        res = advising.message_clients(c, self.carol, [self.dana], "Markets were bumpy",
                                       now=NOW)
        self.assertTrue(res["ok"])
        (msg,) = advising.list_notes(c, self.dana, include_private=False)
        self.assertEqual(msg["is_message"], 1)
        advising.archive_note(c, self.dana, msg["id"])
        self.assertNotIn("from_your_advisor_notes.csv", _unzip(export.export_zip(c, self.dana)))


class ClientRecordTests(_DB):

    def _fill(self):
        c = self.conn
        advising.add_note(c, self.dana, self.carol, "Review", "Annual review", "2026-09-01")
        advising.add_note(c, self.dana, self.carol, "Note", "Prefers email", "2026-09-02",
                          private=True)
        advising.add_note(c, self.dana, self.carol, "Note", "First draft", "2026-09-03")
        notes = {n["body"]: n for n in advising.list_notes(c, self.dana, include_private=True)}
        advising.edit_note(c, self.dana, notes["First draft"]["id"], "Second draft", now=NOW)
        advising.archive_note(c, self.dana, notes["Annual review"]["id"], now=NOW)
        advising.message_clients(c, self.carol, [self.dana], "Happy new year", now=NOW)
        pid = proposals.save(c, self.carol, self.dana, title="Steadier mix",
                             mix={"Stocks": 60, "Bonds": 40})
        proposals.share(c, self.carol, pid)
        proposals.respond(c, self.dana, pid, True)
        reports.save(c, self.carol, self.dana, label="Q3 2026", start=NOW.date(), end=NOW.date(),
                     facts={}, message="A calm quarter")
        c.execute("INSERT INTO investor_profiles (user_id, goal, ai_memory) VALUES (?, ?, ?)",
                  (self.dana, "Retire at 60", "SECRET-AI-MEMORY"))
        # a note from the client's earlier advisor (Omar): never in Carol's record
        advising.add_note(c, self.dana, self.omar, "Note", "OMAR-NOTE", "2026-08-01")
        # Omar's own client
        advising.add_note(c, self.zed, self.omar, "Note", "ZED-NOTE", "2026-09-01")
        token = auth.create_invite(c, self.carol, self.dana, now=NOW)
        auth.accept_invite(c, token, "clientpass1", now=NOW, **AGREE)
        auth.create_session(c, self.dana)
        c.commit()

    def test_one_clients_record(self):
        self._fill()
        files = _unzip(export.client_record_zip(self.conn, self.carol, self.dana, now=NOW))
        self.assertEqual(set(files), {"README.txt", "client.csv", "notes.csv",
                                      "note_history.csv", "proposals.csv", "reports.csv",
                                      "profile.csv"})
        self.assertIn("Dana Lee", files["README.txt"])
        self.assertIn("October 1, 2026", files["client.csv"])           # when they agreed
        self.assertIn(auth.TERMS_VIA_SETUP_LINK, files["client.csv"])
        notes = files["notes.csv"]
        for text in ("Annual review", "Prefers email", "Second draft", "Happy new year"):
            self.assertIn(text, notes)                                  # archived, private too
        self.assertIn("First draft", files["note_history.csv"])
        self.assertIn("accepted", files["proposals.csv"])
        self.assertIn("Q3 2026", files["reports.csv"])
        self.assertIn("Retire at 60", files["profile.csv"])
        everything = "".join(files.values())
        secrets_ = self.conn.execute("SELECT password_hash, password_salt FROM users WHERE id = ?",
                                     (self.dana,)).fetchone()
        for text in ("OMAR-NOTE", "ZED-NOTE", "SECRET-AI-MEMORY", "password", "salt",
                     "token", secrets_[0], secrets_[1]):
            self.assertNotIn(text, everything)

    def test_only_the_clients_own_advisor(self):
        self._fill()
        for who, client in ((self.omar, self.dana), (self.carol, self.zed),
                            (self.dana, self.dana), (self.zed, self.dana)):
            with self.assertRaises(PermissionError, msg=(who, client)):
                export.client_record_zip(self.conn, who, client)
        auth.unlink_client(self.conn, self.carol, self.dana)
        with self.assertRaises(PermissionError):
            export.client_record_zip(self.conn, self.carol, self.dana)

    def test_all_records_one_folder_per_own_client(self):
        self._fill()
        files = _unzip(export.all_client_records_zip(self.conn, self.carol, now=NOW))
        folders = {n.split("/")[0] for n in files}
        self.assertEqual(folders, {f"dana-lee-{self.dana}"})
        everything = "".join(files.values())
        self.assertIn("Second draft", everything)
        for text in ("OMAR-NOTE", "ZED-NOTE", "SECRET-AI-MEMORY"):
            self.assertNotIn(text, everything)
        self.assertEqual(_unzip(export.all_client_records_zip(self.conn, self.dana)), {})
        self.assertEqual(export.record_file_name("Dana Lee", NOW),
                         "northwend-client-record-dana-lee-2026-10-04.zip")


class WordingTests(unittest.TestCase):
    """Northwend checks an advisor's licence number - it doesn't vet or
    endorse them, and nothing in the app or on the website says it does."""

    PATTERN = (r"\b(vetted|vetting|verified (financial )?advisors?|trusted (financial )?advisors?"
               r"|endorsed by northwend|northwend[- ]approved|approved by northwend)\b")

    def test_no_vetting_or_endorsement_wording(self):
        import glob
        import re
        files = (glob.glob(os.path.join(REPO, "website", "templates", "*.html"))
                 + glob.glob(os.path.join(REPO, "views", "*.py"))
                 + [os.path.join(REPO, n) for n in ("dashboard.py", "mailer.py",
                                                   "disclosures.py")])
        for path in files:
            with open(path, encoding="utf-8") as fh:
                found = re.findall(self.PATTERN, fh.read(), re.IGNORECASE)
            self.assertEqual(found, [], os.path.relpath(path, REPO))
        with open(os.path.join(REPO, "website", "public", "advisors.html"),
                  encoding="utf-8") as fh:
            page = fh.read()
        self.assertIn("We check your licence", page)
        self.assertIn("isn't an endorsement", page.replace("&#x27;", "'").replace("&#39;", "'"))


def _unzip(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return {n: z.read(n).decode("utf-8") for n in z.namelist()}


class PageTests(unittest.TestCase):
    """The pages: the setup link's boxes, the one-time ask, archive and export."""

    @classmethod
    def setUpClass(cls):
        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_records_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        c = portfolio.connect(cls.db)
        try:
            cls.carol = auth.create_user(c, "carol", "pw-123456789")
            auth.set_advisor(c, "carol", True)
            auth.record_agreement(c, cls.carol, "v", via=auth.TERMS_VIA_SIGN_IN)
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            # a client from before the setup link asked: never agreed
            cls.dana = auth.create_user(c, "dana", "pw-123456789")
            auth.link_client(c, cls.carol, cls.dana)
            cls.eve = auth.create_client(c, cls.carol, "eve@example.com")
            advising.add_note(c, cls.dana, cls.carol, "Note", "Shown note", "2026-09-01")
            advising.add_note(c, cls.dana, cls.carol, "Note", "Archived note", "2026-09-02")
            gone = [n for n in advising.list_notes(c, cls.dana, include_private=True)
                    if n["body"] == "Archived note"][0]
            advising.archive_note(c, cls.dana, gone["id"])
            cls.gone = gone["id"]
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    @contextlib.contextmanager
    def _run(self, page=None, uid=None, name=None, query=None, **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        if uid is not None:
            state.update(user_id=uid, username=name, page=page)
        for k, v in state.items():
            at.session_state[k] = v
        for k, v in (query or {}).items():
            at.query_params[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused")
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    def _db(self):
        return portfolio.connect(self.db)

    @staticmethod
    def _text(at):
        parts = [m.value for m in at.markdown]
        for kind in ("success", "info", "warning", "error", "caption"):
            parts += [str(e.value) for e in getattr(at, kind)]
        return " ".join(parts)

    def test_setup_link_page_asks_to_agree(self):
        c = self._db()
        try:
            token = auth.create_invite(c, self.carol, self.eve)
        finally:
            c.close()
        with self._run(query={"invite": token}) as at:
            at.text_input(key="invite_pw").input("clientpass1")
            at.text_input(key="invite_pw_again").input("clientpass1")
            at.button(key="FormSubmitter:invite_form-Create my login").click().run()
            self.assertIn("tick the box", " ".join(e.value for e in at.error))
            c = self._db()
            try:
                self.assertFalse(auth.has_agreed(c, self.eve))
            finally:
                c.close()
            at.checkbox(key="invite_adult").check()
            at.checkbox(key="invite_agree").check()
            at.text_input(key="invite_pw").input("clientpass1")
            at.text_input(key="invite_pw_again").input("clientpass1")
            at.button(key="FormSubmitter:invite_form-Create my login").click().run()
            self.assertEqual(at.session_state["user_id"], self.eve)
            # just agreed: no second ask once in
            self.assertNotIn("terms_ok", [b.key for b in at.button])
        c = self._db()
        try:
            row = c.execute("SELECT terms_version, terms_via FROM users WHERE id = ?",
                            (self.eve,)).fetchone()
        finally:
            c.close()
        import disclosures
        self.assertEqual((row["terms_version"], row["terms_via"]),
                         (disclosures.LAST_UPDATED, auth.TERMS_VIA_SETUP_LINK))

    def test_a_client_who_never_agreed_is_asked_once(self):
        with self._run("Advisor notes", self.dana, "dana") as at:
            self.assertIn("terms_ok", [b.key for b in at.button])
            self.assertTrue(at.button(key="terms_ok").disabled)
            # archived notes are hidden from the client
            text = self._text(at)
            self.assertIn("Shown note", text)
            self.assertNotIn("Archived note", text)
            self.assertNotIn("note_archive_", " ".join(b.key or "" for b in at.button))
            at.checkbox(key="terms_adult").check().run()
            at.checkbox(key="terms_agree").check().run()
            at.button(key="terms_ok").click().run()
            self.assertNotIn("terms_ok", [b.key for b in at.button])
        c = self._db()
        try:
            self.assertTrue(auth.has_agreed(c, self.dana))
            self.assertEqual(c.execute("SELECT terms_via FROM users WHERE id = ?",
                                       (self.dana,)).fetchone()["terms_via"],
                             auth.TERMS_VIA_SIGN_IN)
        finally:
            c.close()
        with self._run("Dashboard", self.dana, "dana") as at:
            self.assertNotIn("terms_ok", [b.key for b in at.button])

    def test_the_advisor_archives_restores_and_exports(self):
        with self._run("Advisor notes", self.carol, "carol", active_user_id=self.dana,
                       two_step_ok=self.carol_ok) as at:
            keys = [b.key for b in at.button]
            self.assertNotIn("terms_ok", keys)          # carol agreed already
            self.assertNotIn(f"note_restore_{self.gone}", keys)
            at.toggle(key="notes_show_archived").set_value(True).run()
            self.assertIn("Archived note", self._text(at))
            at.button(key=f"note_restore_{self.gone}").click().run()
            self.assertIn(f"note_archive_{self.gone}", [b.key for b in at.button])
            at.button(key="client_record_prepare").click().run()
            self.assertIsNotNone(at.session_state["client_record"])
            files = _unzip(at.session_state["client_record"][2])
            self.assertIn("Archived note", files["notes.csv"])
        with self._run("Clients", self.carol, "carol", two_step_ok=self.carol_ok) as at:
            at.button(key="all_records_prepare").click().run()
            names = _unzip(at.session_state["all_records"][1])
            self.assertTrue(any(n.endswith("/notes.csv") for n in names))


if __name__ == "__main__":
    unittest.main()
