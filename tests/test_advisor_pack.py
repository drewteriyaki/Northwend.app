"""Bring to my advisor (ROADMAP Phase C2; advisor_pack.py,
views/advisor_pack.py, flag advisor_pack).

A client who has an advisor ticks, item by item, things that are otherwise
only theirs; the advisor sees only those. Checked here:
- nothing is shared by default; only the client signed in as themselves may
  share (never an advisor, an admin, another login or someone without an
  advisor);
- the first share records consent.grant(scope="advisor_pack") with the exact
  words and their SHA-256; unticking takes an item out of the advisor's view
  at once; unticking the last, "Stop sharing", the relationship ending, an
  admin's unlink and a deleted account each write a revoke and leave nothing;
- the advisor sees only ticked items, only through for_advisor (can_view);
  each opening of the card is an access_log row; never in the AI's facts;
- the one-pager carries no figure, the fork only its name, the readiness map
  no taps; no banned words; the season note for advisors;
- in the app (AppTest): the client's section (default nothing ticked, tick ->
  the words -> yes -> recorded), the advisor's card (open -> logged, only the
  ticked item), never for an advisor in client mode, flag off draws nothing.

    python -m unittest tests.test_advisor_pack        (from the repo root)
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

import access_log  # noqa: E402
import admin  # noqa: E402
import advising  # noqa: E402
import advisor_pack as ap  # noqa: E402
import auth  # noqa: E402
import consent  # noqa: E402
import drills  # noqa: E402
import export  # noqa: E402
import flags  # noqa: E402
import future_notes  # noqa: E402
import lost_found  # noqa: E402
import meeting  # noqa: E402
import plans  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import recap  # noqa: E402
import trail_forks  # noqa: E402
import two_step  # noqa: E402

PW = "pw-123456789"
TODAY = date(2026, 10, 6)
NEVER = (r"\bshould\b", r"\bbest\b", r"\brecommend", r"\bmust\b", r"\burgent", r"\bhurry\b",
         r"\brefer", r"\bwe advise\b")
SNAP = "2026-09-30"
ACCOUNT = "Pinecrest Brokerage ...987"
NEVER_IN_ONE_PAGER = ("ZQXW", "Zebra", "Pinecrest", "987", "4321", "98765", "123456", "55555",
                      "777777", "3333", "2033", "Maui", "$")
STORM_WORDS = "I will sit tight and call Carol before selling anything"


def _position(symbol, desc, asset_type, qty, cost, value):
    row = {c: None for c in portfolio.POSITION_COLS}
    row.update(snapshot_date=SNAP, account=ACCOUNT, symbol=symbol, description=desc,
               asset_type=asset_type, quantity=qty, cost_basis=cost, market_value=value)
    return row


def _seed(c):
    """carol (an advisor, card "Carol Reyes, Reyes Wealth") with her client
    dana (a distinctive portfolio and plan, forks, drills, a storm note,
    places looked); omar, another advisor; ivy, an investor with no advisor."""
    carol = auth.create_user(c, "carol", PW)
    auth.set_advisor(c, "carol", True)
    prefs.save(c, carol, {"advisor_card": {"name": "Carol Reyes", "firm": "Reyes Wealth"}})
    omar = auth.create_user(c, "omar", PW)
    auth.set_advisor(c, "omar", True)
    dana = auth.create_user(c, "dana", PW)
    auth.link_client(c, carol, dana)
    ivy = auth.create_user(c, "ivy", PW)
    portfolio.write_snapshot(
        c, dana, {"snapshot_date": SNAP, "as_of_text": "as of Pinecrest"},
        [_position("ZQXW", "Zebra Quantum Growth Fund", "Equity", 4321.0, 98765.43, 123456.78)],
        {ACCOUNT: {"cash_value": 55555.55, "reported_cost_basis": None,
                   "reported_market_value": None, "reported_gain": None,
                   "reported_gain_pct": None}}, "Pinecrest-777777.csv")
    plans.save_plan(c, dana, {"goal_type": "Buy a home", "goal_name": "Maui Beach House",
                              "target_amount": 777777, "target_date": "2033-06-01",
                              "monthly_contribution": 3333,
                              "target_alloc": {"Stocks": 70, "Bonds": 20, "Cash": 10}}, carol)
    p = {"drift_threshold": 7.0}
    p = trail_forks.with_fork(p, "new_job", True)
    p = trail_forks.with_fork(p, "divorce", True)
    p = trail_forks.with_step(p, "new_job", trail_forks.steps("new_job")[0], True)
    drills.record(p, "drop", "talk", TODAY)
    p = lost_found.with_status(p, "dol", "looking", TODAY)
    prefs.save(c, dana, p)
    future_notes.save(c, dana, future_notes.DRILL, STORM_WORDS)
    c.commit()
    return carol, omar, dana, ivy


class _DB(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_pack_")
        self.db = os.path.join(self.dir, "t.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.c = portfolio.connect(self.db)
        self.carol, self.omar, self.dana, self.ivy = _seed(self.c)
        self.text = ap.consent_text("Carol Reyes, Reyes Wealth")

    def tearDown(self):
        self.c.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def share(self, *items):
        return ap.start(self.c, self.dana, items, by=self.dana, text_shown=self.text,
                        today=TODAY)

    def seen(self, advisor=None):
        return ap.for_advisor(self.c, advisor or self.carol, self.dana)

    def pack_records(self):
        return [r for r in consent.history(self.c, self.dana) if r["scope"] == ap.SCOPE]


# --------------------------------------------------------------------------- #
# who, and nothing by default
# --------------------------------------------------------------------------- #
class WhoTests(_DB):

    def test_nothing_is_shared_by_default(self):
        self.assertEqual(self.seen(), [])
        self.assertEqual(ap.shared(self.c, self.dana, self.carol), {})
        self.assertFalse(ap.consented(self.c, self.dana, self.carol))
        self.assertEqual(self.pack_records(), [])

    def test_only_the_client_signed_in_as_themselves(self):
        self.assertEqual(ap.advisor_for(self.c, self.dana, self.dana), self.carol)
        self.assertIsNone(ap.advisor_for(self.c, self.dana, self.carol))   # the advisor
        self.assertIsNone(ap.advisor_for(self.c, self.carol, self.carol))  # an advisor's own
        self.assertIsNone(ap.advisor_for(self.c, self.ivy, self.ivy))      # no advisor
        for by in (self.carol, self.omar, self.ivy):
            with self.assertRaises(PermissionError):
                ap.start(self.c, self.dana, [ap.ONE_PAGER], by=by, text_shown=self.text)
            with self.assertRaises(PermissionError):
                ap.tick(self.c, self.dana, ap.ONE_PAGER, True, by=by)
            with self.assertRaises(PermissionError):
                ap.stop(self.c, self.dana, by=by)
        self.assertEqual(self.pack_records(), [])

    def test_never_an_admin(self):
        admin.set_admin(self.c, "dana", True)
        self.assertIsNone(ap.advisor_for(self.c, self.dana, self.dana))
        with self.assertRaises(PermissionError):
            self.share(ap.ONE_PAGER)

    def test_the_advisor_reads_only_their_own_clients(self):
        self.share(ap.ONE_PAGER)
        for who in (self.omar, self.ivy, self.dana):
            with self.assertRaises(PermissionError):
                ap.for_advisor(self.c, who, self.dana)

    def test_only_known_keys(self):
        self.assertTrue(ap.valid("fork:new_job"))
        self.assertTrue(ap.valid("q:fees"))
        for bad in ("fork:nope", "q:anything", "free text", "", None, 3, "one_pager "):
            self.assertFalse(ap.valid(bad))
        with self.assertRaises(ValueError):
            self.share("q:my own question", "notes")
        self.assertEqual(self.pack_records(), [])


# --------------------------------------------------------------------------- #
# consent and the advisor's view
# --------------------------------------------------------------------------- #
class ConsentTests(_DB):

    def test_consent_supports_the_new_scope_and_how(self):
        self.assertIn(ap.SCOPE, consent.SCOPES)
        self.assertIn(ap.HOW, consent.HOWS)
        with self.assertRaises(ValueError):
            consent.grant(self.c, self.dana, self.carol, "x", "intro", scope="everything")

    def test_the_first_share_records_the_exact_words(self):
        with self.assertRaises(ValueError):   # a grant needs the words
            ap.start(self.c, self.dana, [ap.ONE_PAGER], by=self.dana, text_shown="  ")
        self.share("q:fees")
        rec = self.pack_records()
        self.assertEqual(len(rec), 1)
        self.assertEqual((rec[0]["kind"], rec[0]["how"], rec[0]["advisor_id"]),
                         ("grant", "pack_choice", self.carol))
        self.assertEqual(rec[0]["text_shown"], self.text)
        self.assertEqual(rec[0]["text_sha256"], consent.text_sha256(self.text))
        self.assertIn("Carol Reyes, Reyes Wealth", self.text)
        # full sharing is untouched: its own scope
        self.assertFalse(consent.current(self.c, self.dana, self.carol))
        self.assertTrue(consent.current(self.c, self.dana, self.carol, ap.SCOPE))
        # later ticks need no new words
        ap.tick(self.c, self.dana, ap.READINESS, True, by=self.dana, today=TODAY)
        self.assertEqual(len(self.pack_records()), 1)

    def test_ticking_before_the_words_is_refused(self):
        with self.assertRaises(PermissionError):
            ap.tick(self.c, self.dana, ap.ONE_PAGER, True, by=self.dana)
        self.assertEqual(ap.shared(self.c, self.dana, self.carol), {})

    def test_the_advisor_sees_only_what_is_ticked(self):
        self.share("q:fees")
        seen = self.seen()
        self.assertEqual([s["item"] for s in seen], ["q:fees"])
        self.assertEqual(seen[0]["shared_on"], TODAY.isoformat())
        text = repr(seen)
        for other in (STORM_WORDS, "A new job", "Divorce", "dol", "Department of Labor",
                      "Hard times", ap.QUESTION_WORDS["paid"]):
            self.assertNotIn(other, text)

    def test_untick_removes_it_at_once_and_the_last_one_ends_it(self):
        self.share(ap.ONE_PAGER, ap.STORM_NOTE)
        self.assertEqual({s["item"] for s in self.seen()}, {ap.ONE_PAGER, ap.STORM_NOTE})
        ap.tick(self.c, self.dana, ap.STORM_NOTE, False, by=self.dana)
        self.assertEqual([s["item"] for s in self.seen()], [ap.ONE_PAGER])
        self.assertNotIn(STORM_WORDS, repr(self.seen()))
        self.assertTrue(ap.consented(self.c, self.dana, self.carol))
        ap.tick(self.c, self.dana, ap.ONE_PAGER, False, by=self.dana)
        self.assertEqual(self.seen(), [])
        self.assertEqual([r["kind"] for r in self.pack_records()], ["revoke", "grant"])
        self.assertEqual(self.pack_records()[0]["how"], "pack_choice")
        # sharing again asks for the words again
        with self.assertRaises(PermissionError):
            ap.tick(self.c, self.dana, ap.ONE_PAGER, True, by=self.dana)

    def test_stop_unticks_everything(self):
        self.share(ap.ONE_PAGER, "q:fees", ap.READINESS)
        ap.stop(self.c, self.dana, by=self.dana)
        self.assertEqual(self.seen(), [])
        self.assertEqual(ap.shared(self.c, self.dana, self.carol), {})
        self.assertFalse(ap.consented(self.c, self.dana, self.carol))

    def test_rows_without_consent_show_nothing(self):
        # belt and braces: a row with no grant in force is never shown
        self.c.execute("INSERT INTO advisor_pack (user_id, advisor_id, item, shared_on) "
                       "VALUES (?, ?, 'q:fees', '2026-10-06')", (self.dana, self.carol))
        self.c.commit()
        self.assertEqual(self.seen(), [])


# --------------------------------------------------------------------------- #
# when the relationship ends; records
# --------------------------------------------------------------------------- #
class EndTests(_DB):

    def _ended(self, how):
        self.assertEqual(self.c.execute("SELECT COUNT(*) AS n FROM advisor_pack").fetchone()["n"],
                         0)
        rec = self.pack_records()
        self.assertEqual((rec[0]["kind"], rec[0]["how"]), ("revoke", how))

    def test_the_advisor_ends_it(self):
        self.share(ap.ONE_PAGER, "q:fees")
        self.assertTrue(advising.end_relationship(self.c, self.carol, self.dana,
                                                  by="advisor")["ok"])
        self._ended("advisor_end")
        with self.assertRaises(PermissionError):   # the advisor keeps nothing live
            self.seen()

    def test_the_client_ends_it(self):
        self.share(ap.ONE_PAGER)
        advising.end_relationship(self.c, self.carol, self.dana, by="client")
        self._ended("client_stop")

    def test_an_admin_unlinks_them(self):
        self.share(ap.ONE_PAGER)
        auth.unlink_client(self.c, self.carol, self.dana)
        self._ended("admin")

    def test_an_account_is_deleted(self):
        self.share(ap.ONE_PAGER)
        admin.delete_account(self.c, self.carol, by=self.ivy)
        self._ended("account_deleted")

    def test_no_pack_writes_no_pack_revoke(self):
        advising.end_relationship(self.c, self.carol, self.dana, by="advisor")
        self.assertEqual(self.pack_records(), [])

    def test_in_the_clients_export_without_the_advisors_id(self):
        self.share("q:fees")
        rows = export.collect(self.c, self.dana)["brought_to_your_advisor"]
        self.assertEqual([(r["item"], r["shared_on"]) for r in rows],
                         [("q:fees", TODAY.isoformat())])
        self.assertNotIn("advisor_id", rows[0])
        self.assertEqual(admin.ACCOUNT_TABLES["advisor_pack"], ("user_id", "advisor_id"))
        # the advisor's own record keeps the dated consent words, not the items
        rec = export.client_record(self.c, self.carol, self.dana)
        self.assertIn(ap.SCOPE, [r["scope"] for r in rec["consent"]])
        self.assertNotIn("q:fees", repr(rec))


# --------------------------------------------------------------------------- #
# what each item carries
# --------------------------------------------------------------------------- #
class ContentTests(_DB):

    def test_the_one_pager_has_no_figures(self):
        self.share(ap.ONE_PAGER)
        (one,) = self.seen()
        self.assertTrue(one["lines"])
        text = " ".join(one["lines"])
        for bad in NEVER_IN_ONE_PAGER:
            self.assertNotIn(bad, text)
        self.assertFalse(recap.has_money(text))
        self.assertIn("Stocks", text)

    def test_a_fork_is_its_name_only(self):
        self.share("fork:divorce")
        (fork,) = self.seen()
        self.assertEqual(fork["lines"], [trail_forks.BY_KEY["divorce"]["title"]])
        self.assertNotIn("new_job", repr(fork))
        # a fork no longer theirs isn't shown
        p = trail_forks.with_fork(prefs.load(self.c, self.dana), "divorce", False)
        prefs.save(self.c, self.dana, p)
        self.assertEqual(self.seen(), [])

    def test_the_readiness_map_never_carries_a_tap(self):
        self.share(ap.READINESS)
        (rm,) = self.seen()
        text = " ".join(rm["lines"])
        self.assertIn("A sharp market drop", text)
        self.assertIn("rehearsed", text)
        for _k, words in drills.choices_of("drop"):
            self.assertNotIn(words, text)
        self.assertNotIn("talk", text)

    def test_the_storm_note_is_their_words_and_goes_when_deleted(self):
        self.share(ap.STORM_NOTE)
        (note,) = self.seen()
        self.assertTrue(note["own_words"])
        self.assertEqual(note["lines"], [STORM_WORDS])
        future_notes.delete(self.c, self.dana, future_notes.DRILL)
        self.assertEqual(self.seen(), [])

    def test_places_are_statuses_only(self):
        self.share(ap.PLACES)
        (pl,) = self.seen()
        self.assertEqual(len(pl["lines"]), 1)
        self.assertIn("still looking", pl["lines"][0])

    def test_an_item_whose_feature_is_off_is_neither_offered_nor_shown(self):
        self.share("fork:new_job", ap.READINESS, "q:fees")
        seen = ap.for_advisor(self.c, self.carol, self.dana, features={"drills"})
        self.assertEqual([s["item"] for s in seen], [ap.READINESS, "q:fees"])
        p = prefs.load(self.c, self.dana)
        self.assertNotIn("fork:new_job", ap.offered(p, has_storm_note=True, features=set()))

    def test_what_is_offered(self):
        p = prefs.load(self.c, self.dana)
        items = ap.offered(p, has_storm_note=True)
        self.assertEqual(items[:5], [ap.ONE_PAGER, "fork:new_job", "fork:divorce",
                                     ap.READINESS, ap.STORM_NOTE])
        self.assertIn(ap.PLACES, items)
        self.assertEqual(items[-len(ap.QUESTIONS):], [ap.QUESTION + q for q, _ in ap.QUESTIONS])
        # no note, no places: not offered
        bare = ap.offered({}, has_storm_note=False)
        self.assertNotIn(ap.STORM_NOTE, bare)
        self.assertNotIn(ap.PLACES, bare)
        self.assertFalse([i for i in bare if i.startswith(ap.FORK)])

    def test_never_in_the_ais_meeting_facts(self):
        self.share(ap.STORM_NOTE, "fork:divorce", "q:paid")
        p = meeting.prep(self.c, self.dana, today=TODAY, value=1.0, latest_snapshot=SNAP,
                         actual_pct={}, targets={}, drift_threshold=5, advisor_id=self.carol)
        facts = meeting.facts_for_ai(p)
        for word in (STORM_WORDS, "Divorce", ap.QUESTION_WORDS["paid"]):
            self.assertNotIn(word, facts)

    def test_wording(self):
        text = ap.all_text()
        for pat in NEVER:
            self.assertIsNone(re.search(pat, text, re.I), pat)
        self.assertIn("nothing to type", text)

    def test_the_season_note(self):
        for month, key in ((1, "january"), (4, "april"), (10, "enrollment"),
                           (11, "enrollment"), (12, "december")):
            heading, text = ap.season_note(date(2026, month, 15))
            self.assertEqual(text, ap.SEASON_TOPICS[key])
        heading, text = ap.season_note(date(2026, 6, 1))
        self.assertIn("October and November", heading)
        self.assertEqual(text, ap.SEASON_TOPICS["enrollment"])


class FlagTests(unittest.TestCase):

    def test_the_flag_needs_no_gate_and_owns_its_view(self):
        self.assertEqual(flags.FEATURES["advisor_pack"], {"gates": (), "view": "advisor_pack"})


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
        cls.dir = tempfile.mkdtemp(prefix="pt_pack_app_")
        cls.db = os.path.join(cls.dir, "app.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(cls.db))
        c = portfolio.connect(cls.db)
        try:
            cls.carol, cls.omar, cls.dana, cls.ivy = _seed(c)
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
        c = self._conn()
        try:
            c.execute("DELETE FROM advisor_pack")
            c.execute("DELETE FROM consent_records")
            c.execute("DELETE FROM advisor_access_log")
            c.commit()
        finally:
            c.close()

    def _run(self, at, flags="advisor_pack,storm_drill,trail_forks,drills,lost_found"):
        import yfinance

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS", "NORTHWEND_FLAGS",
                            "NORTHWEND_GATES", "RESEND_API_KEY")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                   NORTHWEND_FLAGS=flags, NORTHWEND_GATES="", NORTHWEND_ADMINS="")
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

    def _advisor_tab(self):
        return self._tab(self.carol, "carol", "Advisor notes", two_step_ok=self.carol_ok,
                         active_user_id=self.dana)

    @staticmethod
    def _text(at):
        parts = [m.value for m in at.markdown] + [h.proto.body for h in at.get("html")]
        for kind in ("success", "info", "warning", "error", "caption", "subheader"):
            parts += [str(e.value) for e in getattr(at, kind)]
        return " ".join(parts)

    def _conn(self):
        return portfolio.connect(self.db)

    @staticmethod
    def _boxes(at):
        return {cb.key: cb.value for cb in at.checkbox if (cb.key or "").startswith("pack_")}

    def _open_card(self, at):
        at.button(key="pack_open_btn").click()
        return self._run(at)

    def test_the_client_chooses_and_the_advisor_sees_only_that(self):
        at = self._run(self._tab(self.dana, "dana", "Account"))
        self.assertIn(ap.TITLE, self._text(at))
        boxes = self._boxes(at)
        self.assertIn("pack_one_pager", boxes)
        self.assertIn("pack_fork:divorce", boxes)
        self.assertIn("pack_storm_note", boxes)
        self.assertEqual(set(boxes.values()), {False})   # all off by default
        self.assertNotIn("pack_share", [b.key for b in at.button])
        self.assertNotIn(ap.CONSENT[:40], self._text(at))
        # the advisor's card: nothing shared, and the opening is logged
        adv = self._open_card(self._run(self._advisor_tab()))
        self.assertIn(ap.NOTHING_SHARED.format(client="dana"), self._text(adv))
        c = self._conn()
        try:
            pages = [r["page"] for r in access_log.for_client(c, self.dana, self.carol)]
        finally:
            c.close()
        self.assertIn(ap.ACCESS_PAGE, pages)
        # tick one: the words, then yes - recorded word for word
        at.checkbox(key="pack_q:fees").check()
        self._run(at)
        text = ap.consent_text("Carol Reyes, Reyes Wealth")
        self.assertIn(text[:60], self._text(at).replace("\\", ""))
        at.button(key="pack_share").click()
        self._run(at)
        c = self._conn()
        try:
            rec = [r for r in consent.history(c, self.dana) if r["scope"] == ap.SCOPE]
            self.assertEqual(ap.shared(c, self.dana, self.carol), {"q:fees": date.today()
                                                                  .isoformat()})
        finally:
            c.close()
        self.assertEqual(len(rec), 1)
        self.assertEqual((rec[0]["kind"], rec[0]["text_shown"]), ("grant", text))
        self.assertTrue(self._boxes(at)["pack_q:fees"])
        # the advisor opens it again: only the ticked question
        adv = self._open_card(self._run(self._advisor_tab()))
        shown = self._text(adv)
        self.assertIn(ap.QUESTION_WORDS["fees"], shown)
        self.assertIn("client-reported", shown)
        self.assertNotIn(ap.QUESTION_WORDS["paid"], shown)
        self.assertNotIn(STORM_WORDS, shown)
        # untick: gone from the advisor's view at once, and the sharing ends
        at.checkbox(key="pack_q:fees").uncheck()
        self._run(at)
        adv = self._open_card(self._run(self._advisor_tab()))
        self.assertNotIn(ap.QUESTION_WORDS["fees"], self._text(adv))
        self.assertIn(ap.NOTHING_SHARED.format(client="dana"), self._text(adv))
        c = self._conn()
        try:
            self.assertFalse(ap.consented(c, self.dana, self.carol))
        finally:
            c.close()

    def test_never_for_an_advisor_in_client_mode_and_never_with_the_flag_off(self):
        # the advisor's Account page is their own: no client section
        at = self._run(self._tab(self.carol, "carol", "Account", two_step_ok=self.carol_ok,
                                 active_user_id=self.dana))
        self.assertNotIn(ap.TITLE, self._text(at))
        self.assertEqual(self._boxes(at), {})
        # an investor without an advisor: none either
        at = self._run(self._tab(self.ivy, "ivy", "Account"))
        self.assertNotIn(ap.TITLE, self._text(at))
        # flag off: no section, no card, no season note
        at = self._run(self._tab(self.dana, "dana", "Account"), flags="")
        self.assertNotIn(ap.TITLE, self._text(at))
        adv = self._run(self._advisor_tab(), flags="")
        self.assertNotIn("pack_open_btn", [b.key for b in adv.button])
        book = self._run(self._tab(self.carol, "carol", "Clients", two_step_ok=self.carol_ok),
                         flags="")
        self.assertNotIn(ap.SEASON_TITLE, self._text(book))

    def test_the_season_note_in_the_advisors_book(self):
        at = self._run(self._tab(self.carol, "carol", "Clients", two_step_ok=self.carol_ok))
        text = self._text(at)
        self.assertIn(ap.SEASON_TITLE, text)
        self.assertIn(ap.season_note(date.today())[1], text)


if __name__ == "__main__":
    unittest.main()
