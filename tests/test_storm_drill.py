"""The Storm Drill (ROADMAP R4, flag storm_drill): "What will you do when
this happens?" on the Plan's Stress test, kept as the person's own note
(future_notes.DRILL), shown back on Home's storm note when a drop comes -
with no trade button - and counted in totals only (feature_counts). Hidden
with its flag off, never in an advisor's session, in the person's export,
gone with the account. Runs dashboard.py with streamlit's AppTest on a
scratch database in a temp dir, plus the pure pieces.

    python -m unittest tests.test_storm_drill        (from the repo root)
"""

import contextlib
import csv
import io
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from tests import offline as offline_net  # noqa: E402
sys.path.insert(0, os.path.join(REPO, "tests"))

import admin  # noqa: E402
import auth  # noqa: E402
import export  # noqa: E402
import feature_counts  # noqa: E402
import flags  # noqa: E402
import future_notes  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import test_future_notes as tfn  # noqa: E402

DRILL = future_notes.DRILL
WORDS = "Read this note, breathe, and keep my monthly amount going."


class _DB(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_drill_")
        self.db = os.path.join(self.dir, "t.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.conn = portfolio.connect(self.db)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.dir, ignore_errors=True)


class DrillStorageTests(_DB):

    def test_off_by_default_and_a_known_flag(self):
        self.assertIn("storm_drill", flags.FEATURES)
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": ""}):
            self.assertFalse(flags.on("storm_drill"))
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": "storm_drill"}):
            self.assertTrue(flags.on("storm_drill"))

    def test_kept_as_their_own_note_never_among_the_holdings(self):
        c = self.conn
        uid = auth.create_user(c, "ivy", "pw-123456789")
        self.assertTrue(future_notes.save(c, uid, DRILL, WORDS, now="2026-10-06T10:00:00Z"))
        self.assertEqual(future_notes.get(c, uid, DRILL)["body"], WORDS)
        notes = future_notes.all_notes(c, uid)
        self.assertEqual(future_notes.storm_picks(notes, {}, None), [])   # not a holding's note
        quote = future_notes.drill_quote(future_notes.get(c, uid, DRILL),
                                         lambda d: "Oct 6, 2026")
        self.assertEqual(quote, f"You wrote this when you looked at 2008 (Oct 6, 2026): “{WORDS}”")
        ask = future_notes.ask_text(future_notes.get(c, uid, DRILL))
        self.assertIn("2008", ask)
        self.assertNotIn(DRILL, ask)
        self.assertNotIn("\n", ask)
        future_notes.save(c, uid, DRILL, "  ")                            # empty: a real delete
        self.assertIsNone(future_notes.get(c, uid, DRILL))

    def test_in_their_export_never_the_advisors_record_and_gone_with_the_account(self):
        c = self.conn
        carol = auth.create_user(c, "carol", "pw-123456789")
        auth.set_advisor(c, "carol", True)
        dana = auth.create_client(c, carol, "dana@example.com", name="Dana")
        future_notes.save(c, dana, DRILL, WORDS)
        mine = tfn._unzip(export.export_zip(c, dana))
        rows = list(csv.DictReader(io.StringIO(mine["notes_to_future_you.csv"])))
        self.assertEqual({r["symbol"]: r["body"] for r in rows}, {DRILL: WORDS})
        self.assertIn(DRILL, mine["README.txt"])
        for name, text in tfn._unzip(export.client_record_zip(c, carol, dana)).items():
            self.assertNotIn("breathe", text, name)
        boss = auth.create_user(c, "boss", "pw-123456789")
        admin.set_admin(c, "boss", True)
        self.assertTrue(admin.delete_account(c, dana, by=boss)["ok"])
        self.assertEqual(c.execute("SELECT COUNT(*) AS n FROM future_notes").fetchone()["n"], 0)


class DrillCountTests(_DB):

    def test_totals_only_twenty_or_more_and_left_out_respected(self):
        c = self.conn
        uids = []
        for i in range(19):
            uid = auth.create_user(c, f"d{i}", "pw-123456789")
            future_notes.save(c, uid, DRILL, f"words {i}")
            if i % 2:
                prefs.save(c, uid, {"hide_amounts": True})   # some have settings, some none
            uids.append(uid)
        future_notes.save(c, uids[0], None, "a plan note - not a drill answer")
        self.assertIsNone(feature_counts.drill_answers(c))          # 19: nothing shown
        late = auth.create_user(c, "d19", "pw-123456789")
        future_notes.save(c, late, DRILL, "words 19")
        self.assertEqual(feature_counts.drill_answers(c), 20)
        prefs.save(c, uids[1], {"hide_amounts": True, feature_counts.PREF_OFF: True})
        self.assertIsNone(feature_counts.drill_answers(c))          # left out: 19 again
        self.assertEqual(feature_counts.drill_total([{}] * 25), 25)
        self.assertIsNone(feature_counts.drill_total([{feature_counts.PREF_OFF: True}] * 25))

    def test_said_plainly_first(self):
        import disclosures
        about = " ".join(" ".join(body.split()) for _, body in disclosures.SECTIONS)
        with open(os.path.join(REPO, "docs", "legal", "privacy-policy-DRAFT.md"),
                  encoding="utf-8") as fh:
            policy = " ".join(fh.read().split())
        for text in (about, policy):
            self.assertIn("what they'd do in a drop (never what they wrote)", text)


class DrillAppTests(tfn.AppTests):
    """The app: the field on the Stress test, the answer on the storm note.
    Reuses test_future_notes' scratch app (VTI 15% down: a storm)."""

    @classmethod
    def seed(cls, c):
        super().seed(c)
        cls.uma = cls._investor(c, "uma")                        # writes a drill answer
        cls.vic = cls._investor(c, "vic")                        # wrote one before
        future_notes.save(c, cls.vic, DRILL, WORDS, now="2026-03-05T10:00:00Z")
        future_notes.save(c, cls.dana, DRILL, "Quokka drill, kept private")

    @contextlib.contextmanager
    def _run(self, uid, name, page="Dashboard", **state):
        import yfinance
        from streamlit.testing.v1 import AppTest

        def offline(*a, **k):
            raise RuntimeError("offline in tests")
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=120)
        for k, v in {"user_id": uid, "username": name, "page": page, **state}.items():
            at.session_state[k] = v
        env = {k: v for k, v in os.environ.items()
               if k not in ("FINNHUB_API_KEY", "NORTHWEND_ADMINS")}
        env.update(PORTFOLIO_DB=self.db, MAIL_DRY_RUN="1", ANTHROPIC_API_KEY="sk-test-unused",
                   NORTHWEND_FLAGS=getattr(self, "flags_now", "walk storm_drill"))
        with unittest.mock.patch.dict(os.environ, env, clear=True), \
                unittest.mock.patch.object(yfinance, "Ticker", offline), \
                unittest.mock.patch("socket.socket.connect", offline_net.connect):
            at.run()
            self.assertEqual([e.message for e in at.exception], [])
            yield at
            self.assertEqual([e.message for e in at.exception], [])

    def setUp(self):
        self.flags_now = "walk storm_drill"

    def _labels(self, at):
        return [str(b.label) for b in at.button]

    def test_write_it_on_the_stress_test_and_read_it_on_the_storm_note(self):
        with self._run(self.uma, "uma", "Plan") as at:
            text = self._text(at)
            self.assertIn(future_notes.DRILL_QUESTION, text)
            self.assertIn("there's no right answer", text)
            self.assertIn("Only you can see this", text)
            box = at.text_area(key="fn_text_drill")
            self.assertFalse(box.placeholder)                   # no suggested answer
            box.set_value(WORDS)
            at.button(key="fn_save_drill").click().run()
            self.assertEqual(self._note(self.uma, DRILL)["body"], WORDS)
            self.assertIn("Saved. Only you can see it.", self._text(at))
        with self._run(self.uma, "uma") as at:
            text = self._text(at)
            self.assertIn("A big market drop", text)
            self.assertIn("Your storm drill", text)
            self.assertIn("You wrote this when you looked at 2008", text)
            self.assertIn(WORDS, text)
            # no trade button anywhere on the card (or the page)
            for label in self._labels(at):
                for word in ("sell", "buy", "trade", "rebalance"):
                    self.assertNotIn(word, label.lower(), label)
            storm_keys = sorted(k for k in self._keys(at) if k.startswith("storm_"))
            self.assertEqual(storm_keys, ["storm_ask", "storm_hide", "storm_more"])
            # the holdings' notes are still theirs, apart from the drill
            self.assertNotIn(DRILL, text)

    def test_no_answer_one_quiet_line(self):
        with self._run(self.kai, "kai") as at:
            text = self._text(at)
            self.assertIn("A big market drop", text)
            self.assertIn("You can write down what you'd do in a drop like this", text)
            self.assertNotIn("Your storm drill", text)

    def test_hidden_with_the_flag_off(self):
        self.flags_now = "walk"
        with self._run(self.vic, "vic", "Plan") as at:
            self.assertNotIn(future_notes.DRILL_QUESTION, self._text(at))
            self.assertNotIn("fn_save_drill", self._keys(at))
        with self._run(self.vic, "vic") as at:
            text = self._text(at)
            self.assertIn("A big market drop", text)               # the storm note as before
            self.assertNotIn("Your storm drill", text)
            self.assertNotIn("breathe", text)
            self.assertNotIn("You can write down what you'd do", text)

    def test_never_in_an_advisors_session(self):
        for page in ("Dashboard", "Plan"):
            with self._run(self.carol, "carol", page, active_user_id=self.dana,
                           two_step_ok=self.carol_ok) as at:
                text = self._text(at)
                self.assertNotIn("Quokka", text, page)
                self.assertNotIn("storm drill", text.lower(), page)
                self.assertNotIn(future_notes.DRILL_QUESTION, text, page)
                self.assertNotIn("You can write down what you'd do", text, page)
                self.assertFalse([k for k in self._keys(at) if k.endswith("_drill")], page)
        with self._run(self.dana, "dana") as at:                  # while she sees her own
            self.assertIn("Quokka drill, kept private", self._text(at))


# the notes' own app tests run in test_future_notes; not again here
for _name in [n for n in vars(tfn.AppTests) if n.startswith("test_")]:
    setattr(DrillAppTests, _name, None)


if __name__ == "__main__":
    unittest.main()
