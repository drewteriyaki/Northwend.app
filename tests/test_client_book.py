"""The Client-Owned Book (ROADMAP R16; client_book.py, views/client_book.py,
flag client_owned_book + gate L2).

Checked here:
- the flag needs gate L2 and owns its view; off (or L2 off) draws nothing;
- the advisor sees a client's walk only if the client chose to share it
  (consent scope walk_signal, the exact words), and then only "walked this
  month" and the month of the last walk - never the verdict or a figure;
- counts only: plain numbers over the advisor's own links, never ids or names;
- an advisor never gets another advisor's client (or anything as a
  non-advisor), however the ids are passed;
- "Client-reported, as of <date>" beside the book's figures;
- a clean exit: after Stop sharing the client's account has all its data
  (holdings, plan, walks, notes, the notes their advisor shared) and the
  advisor keeps their own records (former_clients, notes - archived and
  private ones too - proposals, reports, consent records); walk sharing ends
  with any end of the link, and a new link starts unshared;
- the wording: no "should", "best", "recommend", nothing about referrals;
- in the app (AppTest): the book's note, counts and labels; the client's
  switch and the exit words.

    python -m unittest tests.test_client_book        (from the repo root)
"""

import os
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from datetime import date

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import admin  # noqa: E402
import advising  # noqa: E402
import auth  # noqa: E402
import checkin  # noqa: E402
import client_book as cb  # noqa: E402
import consent  # noqa: E402
import export  # noqa: E402
import flags  # noqa: E402
import future_notes  # noqa: E402
import plans  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import proposals  # noqa: E402
import reports  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
TODAY = date(2026, 10, 6)
NEVER = (r"\bshould\b", r"\bbest\b", r"\brecommend", r"\bmust\b", r"\burgent", r"\brefer",
         r"\bwe advise\b")
SNAP = "2026-09-30"
ACCOUNT = "Pinecrest Brokerage ...987"
FUTURE_WORDS = "Dear future me, stay the course"


def _position(symbol, qty, value):
    row = {c: None for c in portfolio.POSITION_COLS}
    row.update(snapshot_date=SNAP, account=ACCOUNT, symbol=symbol, description=f"{symbol} fund",
               asset_type="ETF", quantity=qty, cost_basis=value, market_value=value)
    return row


def _holdings(c, uid, imported_at=None):
    portfolio.write_snapshot(c, uid, {"snapshot_date": SNAP, "as_of_text": "as of"},
                             [_position("VTI", 10.0, 2500.0)],
                             {ACCOUNT: {"cash_value": 100.0, "reported_cost_basis": None,
                                        "reported_market_value": None, "reported_gain": None,
                                        "reported_gain_pct": None}}, "statement.csv")
    if imported_at:
        c.execute("UPDATE snapshots SET imported_at = ? WHERE user_id = ?", (imported_at, uid))
    c.commit()


def _seed(c):
    """carol (advisor; card "Carol Reyes, Reyes Wealth") with dana, eve and
    finn; omar (another advisor) with zed; ivy, an investor alone."""
    carol = auth.create_user(c, "carol", PW)
    auth.set_advisor(c, "carol", True)
    prefs.save(c, carol, {"advisor_card": {"name": "Carol Reyes", "firm": "Reyes Wealth"}})
    omar = auth.create_user(c, "omar", PW)
    auth.set_advisor(c, "omar", True)
    ids = {"carol": carol, "omar": omar}
    for name, adv in (("dana", carol), ("eve", carol), ("finn", carol), ("zed", omar)):
        uid = auth.create_user(c, name, PW)
        auth.link_client(c, adv, uid)
        consent.grant(c, uid, adv, f"{name} shares with their advisor", "setup_link")
        # they've signed in, so an exit keeps their account (advising.ending_plan)
        c.execute("UPDATE users SET last_login_at = ? WHERE id = ?", ("2026-09-01 10:00:00", uid))
        ids[name] = uid
    ids["ivy"] = auth.create_user(c, "ivy", PW)
    # walks: dana this month, eve this month, finn last in August, zed this month
    for name, log in (("dana", ["2026-08", "2026-10"]), ("eve", ["2026-10"]),
                      ("finn", ["2026-08"]), ("zed", ["2026-10"])):
        prefs.save(c, ids[name], {checkin.PREF_LOG: log,
                                  checkin.PREF_VERDICTS: {"2026-10": {"kind": "next",
                                                                      "class": "Bonds"}}})
    _holdings(c, ids["dana"], "2026-10-03 09:00:00")
    _holdings(c, ids["eve"], "2026-08-01 09:00:00")
    _holdings(c, ids["zed"], "2026-10-04 09:00:00")
    c.commit()
    return ids


class _DB(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_book_")
        self.db = os.path.join(self.dir, "t.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.c = portfolio.connect(self.db)
        self.ids = _seed(self.c)
        for k, v in self.ids.items():
            setattr(self, k, v)
        self.text = cb.consent_text("Carol Reyes, Reyes Wealth")

    def tearDown(self):
        self.c.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def share(self, uid, on=True):
        return cb.set_walk_sharing(self.c, uid, on, by=uid, text_shown=self.text)

    def walk_records(self, uid):
        return [r for r in consent.history(self.c, uid) if r["scope"] == cb.SCOPE]


# --------------------------------------------------------------------------- #
# the flag and the gate
# --------------------------------------------------------------------------- #
class FlagTests(unittest.TestCase):

    def _on(self, flag_list, gates):
        env = {k: v for k, v in os.environ.items()
               if k not in ("NORTHWEND_FLAGS", "NORTHWEND_GATES")}
        env.update(NORTHWEND_FLAGS=flag_list, NORTHWEND_GATES=gates)
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch("flags._secret", lambda name: None):
            return flags.on(cb.FLAG), flags.view_on("client_book")

    def test_needs_gate_l2_and_owns_its_view(self):
        self.assertEqual(flags.FEATURES[cb.FLAG], {"gates": ("L2",), "view": "client_book"})
        self.assertEqual(self._on("", ""), (False, False))
        self.assertEqual(self._on(cb.FLAG, ""), (False, False))       # gate off
        self.assertEqual(self._on("", "L2"), (False, False))          # flag off
        self.assertEqual(self._on(cb.FLAG, "L2"), (True, True))

    def test_consent_knows_the_scope_and_how(self):
        self.assertIn(cb.SCOPE, consent.SCOPES)
        self.assertIn(cb.HOW, consent.HOWS)


# --------------------------------------------------------------------------- #
# the client's walk, only when they choose
# --------------------------------------------------------------------------- #
class WalkSharingTests(_DB):

    def test_nothing_is_shared_by_default(self):
        sig = cb.signals(self.c, self.carol, [self.dana, self.eve, self.finn], TODAY)
        for s in sig.values():
            self.assertFalse(s["walk_shared"])
            self.assertIsNone(s["walked"])
            self.assertIsNone(s["last_walk"])
            self.assertIsNone(cb.walk_line(s))

    def test_turning_it_on_records_the_exact_words(self):
        self.assertTrue(self.share(self.dana))
        rec = self.walk_records(self.dana)
        self.assertEqual(len(rec), 1)
        self.assertEqual((rec[0]["kind"], rec[0]["how"], rec[0]["text_shown"],
                          rec[0]["advisor_id"]), ("grant", cb.HOW, self.text, self.carol))
        self.assertEqual(rec[0]["text_sha256"], consent.text_sha256(self.text))
        # on twice is one grant; off is a revoke; off twice is one revoke
        self.share(self.dana)
        self.assertFalse(self.share(self.dana, False))
        self.share(self.dana, False)
        self.assertEqual([r["kind"] for r in self.walk_records(self.dana)], ["revoke", "grant"])
        # full sharing is untouched
        self.assertTrue(consent.current(self.c, self.dana, self.carol))

    def test_on_needs_the_words(self):
        with self.assertRaises(ValueError):
            cb.set_walk_sharing(self.c, self.dana, True, by=self.dana, text_shown="  ")
        self.assertEqual(self.walk_records(self.dana), [])

    def test_only_the_client_with_an_advisor(self):
        for uid, by in ((self.dana, self.carol), (self.dana, self.omar), (self.dana, self.eve),
                        (self.ivy, self.ivy), (self.carol, self.carol)):
            with self.subTest(uid=uid, by=by), self.assertRaises(PermissionError):
                cb.set_walk_sharing(self.c, uid, True, by=by, text_shown=self.text)

    def test_the_advisor_sees_walked_and_the_month_only(self):
        self.share(self.dana)
        self.share(self.finn)
        sig = cb.signals(self.c, self.carol, [self.dana, self.eve, self.finn], TODAY)
        self.assertEqual(sig[self.dana]["walked"], True)
        self.assertEqual(sig[self.dana]["last_walk"], "2026-10")
        self.assertEqual(sig[self.finn]["walked"], False)
        self.assertEqual(sig[self.finn]["last_walk"], "2026-08")
        self.assertIsNone(sig[self.eve]["walked"])          # eve walked, but doesn't share it
        self.assertEqual(cb.walk_line(sig[self.dana]),
                         "Walked this month: yes · Last walk: October 2026")
        self.assertEqual(cb.walk_line(sig[self.finn]),
                         "Walked this month: not yet · Last walk: August 2026")
        # never the verdict, a class or a figure
        for s in sig.values():
            self.assertEqual(set(s), {"walk_shared", "walked", "last_walk", "updated"})
            self.assertNotIn("Bonds", repr(s))
            self.assertNotIn("2500", repr(s))

    def test_turning_it_off_hides_it_at_once(self):
        self.share(self.dana)
        self.share(self.dana, False)
        sig = cb.signals(self.c, self.carol, [self.dana], TODAY)
        self.assertIsNone(sig[self.dana]["walked"])


# --------------------------------------------------------------------------- #
# counts only, and only the advisor's own
# --------------------------------------------------------------------------- #
class CountTests(_DB):

    def test_counts_are_plain_numbers(self):
        self.share(self.dana)
        self.share(self.finn)
        sig = cb.signals(self.c, self.carol, [self.dana, self.eve, self.finn], TODAY)
        n = cb.counts(sig, TODAY)
        self.assertEqual(n, {"clients": 3, "sharing_walks": 2, "walked_this_month": 1,
                             "updated_recently": 1})   # dana Oct 3; eve in August; finn none
        for v in n.values():
            self.assertIsInstance(v, int)

    def test_never_another_advisors_client(self):
        cb.set_walk_sharing(self.c, self.zed, True, by=self.zed, text_shown=self.text)
        everyone = [self.dana, self.eve, self.finn, self.zed, self.ivy, self.omar]
        sig = cb.signals(self.c, self.carol, everyone, TODAY)
        self.assertEqual(set(sig), {self.dana, self.eve, self.finn})
        self.assertEqual(cb.counts(sig, TODAY)["clients"], 3)
        self.assertEqual(set(cb.signals(self.c, self.omar, everyone, TODAY)), {self.zed})
        # carol's own book, read with no ids at all for zed: still only hers
        self.assertEqual(cb.own_clients(self.c, self.carol),
                         {self.dana, self.eve, self.finn})
        # not an advisor (a client, an investor): nothing
        self.assertEqual(cb.signals(self.c, self.dana, everyone, TODAY), {})
        self.assertEqual(cb.signals(self.c, self.ivy, everyone, TODAY), {})

    def test_the_advisor_agreement_closes_it_like_can_view(self):
        with unittest.mock.patch("advisor_agreement.tools_open", lambda c, a: False):
            self.assertEqual(cb.signals(self.c, self.carol, [self.dana], TODAY), {})


# --------------------------------------------------------------------------- #
# client-reported, as of
# --------------------------------------------------------------------------- #
class LabelTests(_DB):

    def test_the_label(self):
        self.assertEqual(cb.reported("2026-10-03 09:00:00"), "Client-reported, as of Oct 3, 2026")
        self.assertEqual(cb.reported("2026-10-03T09:00:00Z"), "Client-reported, as of Oct 3, 2026")
        self.assertEqual(cb.reported(date(2026, 1, 15)), "Client-reported, as of Jan 15, 2026")
        self.assertEqual(cb.reported(None), "Client-reported")
        self.assertEqual(cb.reported("not a date"), "Client-reported")

    def test_dated_by_the_last_update(self):
        sig = cb.signals(self.c, self.carol, [self.dana, self.finn], TODAY)
        self.assertEqual(sig[self.dana]["updated"], "2026-10-03")
        self.assertIsNone(sig[self.finn]["updated"])

    def test_wording(self):
        text = cb.all_text()
        for pat in NEVER:
            self.assertIsNone(re.search(pat, text, re.I), pat)
        for words in ("never holds money", "no account aggregation", "client-reported",
                      "Your notes, proposals and reports are your own records"):
            self.assertIn(words, text)


# --------------------------------------------------------------------------- #
# the clean exit
# --------------------------------------------------------------------------- #
class ExitTests(_DB):

    def _advisor_records(self):
        c, carol, dana = self.c, self.carol, self.dana
        advising.add_note(c, dana, carol, "Review", "Reviewed the plan together", "2026-09-01")
        advising.add_note(c, dana, carol, "Note", "Private thought", "2026-09-02", private=True)
        advising.add_note(c, dana, carol, "Note", "Old note", "2026-09-03")
        old = max(n["id"] for n in advising.list_notes(c, dana, include_private=True,
                                                       advisor_id=carol))
        advising.archive_note(c, dana, old, advisor_id=carol)
        pid = proposals.save(c, carol, dana, title="A steadier mix", mix={"Stocks": 60,
                                                                           "Bonds": 40})
        proposals.share(c, carol, pid)
        reports.save(c, carol, dana, label="Q3 2026", start=date(2026, 7, 1),
                     end=date(2026, 9, 30), facts={"value_end": 2600.0}, message="Q3 notes")
        plans.save_plan(c, dana, {"goal_name": "Cabin", "target_amount": 50000,
                                  "target_date": "2035-01-01"}, carol)
        future_notes.save(c, dana, None, FUTURE_WORDS)

    def _counts(self, table, where, params):
        return self.c.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE {where}",
                              params).fetchone()["n"]

    def test_the_client_keeps_everything_and_the_advisor_keeps_their_records(self):
        c, carol, dana = self.c, self.carol, self.dana
        self._advisor_records()
        self.share(dana)
        before = export.collect(c, dana)
        notes_before = self._counts("advisor_notes", "client_id = ? AND advisor_id = ?",
                                    (dana, carol))
        res = advising.end_relationship(c, carol, dana, by="client", text_shown="Stop words")
        self.assertTrue(res["ok"])
        self.assertEqual(res["account"], "kept")
        # the client: every one of their own rows is still there
        after = export.collect(c, dana)
        for part in ("holdings", "snapshots", "cash", "plan", "settings", "notes_to_future_you",
                     "from_your_advisor_notes", "from_your_advisor_proposals",
                     "from_your_advisor_reports"):
            with self.subTest(part=part):
                self.assertTrue(after.get(part), part)
                self.assertEqual(len(after[part]), len(before[part]), part)
        self.assertIn(FUTURE_WORDS, repr(after["notes_to_future_you"]))
        self.assertIn("2026-10", repr(after["settings"]))          # their walks
        self.assertNotIn("Private thought", repr(after))             # never the advisor's private note
        self.assertTrue(auth.get_username(c, dana))                   # the login stays
        # the advisor: their own records stay
        self.assertEqual([f["client_id"] for f in advising.former_clients(c, carol)], [dana])
        self.assertEqual(self._counts("advisor_notes", "client_id = ? AND advisor_id = ?",
                                      (dana, carol)), notes_before)
        self.assertEqual(self._counts("advisor_notes", "client_id = ? AND advisor_id = ? AND "
                                      "archived_at IS NOT NULL", (dana, carol)), 1)
        record = export.client_record(c, carol, dana)
        self.assertEqual(len(record["notes"]), notes_before)
        self.assertTrue(record["proposals"] and record["reports"] and record["consent"])
        scopes = {(r["scope"], r["kind"]) for r in record["consent"]}
        self.assertIn((consent.FULL_SHARING, "revoke"), scopes)
        self.assertIn((cb.SCOPE, "grant"), scopes)
        self.assertIn((cb.SCOPE, "revoke"), scopes)
        self.assertNotIn("profile", record)          # their answers are theirs
        # and the advisor sees nothing live any more
        self.assertFalse(auth.can_view(c, carol, dana))
        self.assertEqual(cb.signals(c, carol, [dana], TODAY), {})
        self.assertFalse(cb.shares_walk(c, dana, carol))

    def test_a_new_link_starts_unshared(self):
        self.share(self.dana)
        advising.end_relationship(self.c, self.carol, self.dana, by="advisor")
        auth.link_client(self.c, self.carol, self.dana)
        sig = cb.signals(self.c, self.carol, [self.dana], TODAY)
        self.assertFalse(sig[self.dana]["walk_shared"])

    def test_every_end_of_the_link_ends_walk_sharing(self):
        self.share(self.dana)
        auth.unlink_client(self.c, self.carol, self.dana)
        self.assertEqual(self.walk_records(self.dana)[0]["how"], "admin")
        self.assertFalse(cb.shares_walk(self.c, self.dana, self.carol))
        self.share(self.eve)
        self.assertTrue(admin.delete_account(self.c, self.eve, by=-1)["ok"])
        recs = [r for r in consent.between(self.c, self.eve, self.carol)
                if r["scope"] == cb.SCOPE]
        self.assertEqual((recs[0]["kind"], recs[0]["how"]), ("revoke", "account_deleted"))

    def test_no_walk_sharing_writes_no_walk_revoke(self):
        advising.end_relationship(self.c, self.carol, self.dana, by="client")
        self.assertEqual(self.walk_records(self.dana), [])


# --------------------------------------------------------------------------- #
# in the app
# --------------------------------------------------------------------------- #
class AppTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # the app's first run reloads the repo's modules (codefresh.py): put
        # back the ones other test files imported, so their mocks still reach
        cls.modules = {n: m for n, m in sys.modules.items()
                       if os.path.dirname(os.path.abspath(getattr(m, "__file__", None) or ""))
                       == REPO}
        cls.dir = tempfile.mkdtemp(prefix="pt_book_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.ids = _seed(c)
            cls.carol, cls.dana, cls.zed = cls.ids["carol"], cls.ids["dana"], cls.ids["zed"]
            secret = two_step.new_secret()
            two_step.enable(c, cls.carol, secret, two_step.totp(secret))
            cls.carol_ok = f"{cls.carol}:{two_step.status(c, cls.carol)['stamp']}"
            c.commit()
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        sys.modules.update(cls.modules)
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        c = portfolio.connect(self.db)
        try:
            c.execute("DELETE FROM consent_records WHERE scope = ?", (cb.SCOPE,))
            c.commit()
        finally:
            c.close()

    def _run(self, at, flag_list="client_owned_book,walk", gates="L2"):
        import yfinance

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                   NORTHWEND_FLAGS=flag_list, NORTHWEND_GATES=gates, NORTHWEND_ADMINS="")
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline):
            at.run()
        self.assertEqual([e.message for e in at.exception], [])
        return at

    def _tab(self, uid, name, page, **state):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": page, **state}.items():
            at.session_state[k] = v
        return at

    def _book(self, **kw):
        return self._run(self._tab(self.carol, "carol", "Clients", two_step_ok=self.carol_ok),
                         **kw)

    @staticmethod
    def _text(at):
        parts = [m.value for m in at.markdown] + [h.proto.body for h in at.get("html")]
        for kind in ("success", "info", "warning", "error", "caption", "subheader"):
            parts += [str(e.value) for e in getattr(at, kind)]
        return " ".join(parts)

    def test_the_book_with_the_feature_on(self):
        text = self._text(self._book())
        self.assertIn(cb.HOW_BOOK_WORKS[0], text)
        self.assertIn("Client-reported, as of Oct 3, 2026", text)
        self.assertIn("Walked this month", text)
        self.assertIn("of 0 who share their walks", text)
        self.assertNotIn("<b>zed</b>", text)
        self.assertIn("<b>dana</b>", text)
        # dana chooses to share: her card says so - the month only
        c = portfolio.connect(self.db)
        try:
            cb.set_walk_sharing(c, self.dana, True, by=self.dana,
                                text_shown=cb.consent_text("Carol Reyes, Reyes Wealth"))
        finally:
            c.close()
        text = self._text(self._book())
        self.assertIn("of 1 who share their walks", text)
        self.assertIn("Walked this month: yes · Last walk: October 2026", text)
        self.assertNotIn(checkin.verdict_past({"kind": "next", "class": "Bonds"}), text)

    def test_off_without_the_flag_or_the_gate(self):
        for kw in ({"flag_list": "walk"}, {"gates": ""}):
            with self.subTest(**kw):
                text = self._text(self._book(**kw))
                self.assertNotIn(cb.HOW_BOOK_WORKS[0], text)
                self.assertNotIn("Client-reported", text)
                self.assertNotIn("Walked this month", text)
        at = self._run(self._tab(self.dana, "dana", "Advisor notes"), gates="")
        self.assertNotIn("walk_share", [t.key for t in at.toggle])
        self.assertNotIn(cb.EXIT_YOU_KEEP, self._text(at))

    def test_the_clients_switch_and_the_exit_words(self):
        at = self._run(self._tab(self.dana, "dana", "Advisor notes"))
        self.assertIn("walk_share", [t.key for t in at.toggle])
        self.assertFalse(at.toggle(key="walk_share").value)
        text = self._text(at)
        self.assertIn(cb.EXIT_YOU_KEEP, text)
        self.assertIn(cb.EXIT_ADVISOR_KEEPS, text)
        at.toggle(key="walk_share").set_value(True)
        self._run(at)
        c = portfolio.connect(self.db)
        try:
            rec = [r for r in consent.history(c, self.dana) if r["scope"] == cb.SCOPE]
        finally:
            c.close()
        self.assertEqual(len(rec), 1)
        self.assertEqual(rec[0]["text_shown"], cb.consent_text("Carol Reyes, Reyes Wealth"))
        self.assertIn(cb.WALK_SHARE_ON, self._text(at))
        # an advisor in dana's account never gets the switch
        adv = self._run(self._tab(self.carol, "carol", "Advisor notes",
                                  two_step_ok=self.carol_ok, active_user_id=self.dana))
        self.assertNotIn("walk_share", [t.key for t in adv.toggle])


if __name__ == "__main__":
    unittest.main()
