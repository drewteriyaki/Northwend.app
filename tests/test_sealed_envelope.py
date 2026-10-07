"""The Sealed Envelope (flag sealed_envelope, sealed_envelope.py): the Storm
Drill answer as a one-page PDF - the person's words exactly as written, the
day, a calm label and a fixed reminder; never a figure, holding, account
name, email or login; their name only if ticked. Offered under the drill
answer on the Plan's Stress test (needs storm_drill), never in an advisor's
session; Home's storm note says "You wrote yourself a sealed envelope..."
once one was made. Runs dashboard.py with streamlit's AppTest on a scratch
database in a temp dir (test_future_notes' scratch app), plus the pure pieces.

    python -m unittest tests.test_sealed_envelope        (from the repo root)
"""

import inspect
import os
import re
import shutil
import sys
import tempfile
import unittest
import unittest.mock
import zlib
from datetime import date

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

import auth  # noqa: E402
import flags  # noqa: E402
import future_notes  # noqa: E402
import manual_entry  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import sealed_envelope as se  # noqa: E402
import test_future_notes as tfn  # noqa: E402
import test_storm_drill as tsd  # noqa: E402

DRILL = future_notes.DRILL
WORDS = "Breathe first.\nRead my plan note, then wait a week before touching anything."


def _pdf_text(pdf: bytes) -> bytes:
    """The PDF's page content, inflated (fpdf2 compresses it)."""
    out = b""
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.S):
        try:
            out += zlib.decompress(m.group(1))
        except zlib.error:
            out += m.group(1)
    return out


def _envelopes(at):
    """The envelope's download button(s) on the page (others, like an
    advisor's client record, aren't this)."""
    return [d for d in at.get("download_button") if "envelope" in d.proto.label.lower()]


def _pages(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page\b", pdf))


class PureTests(unittest.TestCase):

    def test_a_known_flag_off_by_default_no_gate(self):
        self.assertEqual(flags.FEATURES["sealed_envelope"], {"gates": (), "view": None})
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": ""}):
            self.assertFalse(flags.on("sealed_envelope"))
        with unittest.mock.patch.dict(os.environ, {"NORTHWEND_FLAGS": "sealed_envelope"}):
            self.assertTrue(flags.on("sealed_envelope"))

    def test_render_pdf_can_take_nothing_but_words_day_and_name(self):
        self.assertEqual(list(inspect.signature(se.render_pdf).parameters),
                         ["body", "written_on", "name"])

    def test_one_calm_page_their_words_the_day_the_label(self):
        pdf = se.render_pdf(WORDS, "2026-10-06")
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertEqual(_pages(pdf), 1)
        text = _pdf_text(pdf)
        for part in ("Breathe first.", "then wait a week before touching anything.",
                     "Oct 6, 2026", se.TITLE, "You wrote this on a calm day."):
            self.assertIn(part.encode("latin-1"), text, part)
        self.assertNotIn(b"For ", text)                        # no name unless asked
        self.assertIn(b"For Quentin", _pdf_text(se.render_pdf(WORDS, "2026-10-06",
                                                              name="Quentin")))
        # a full-length answer still fits on one page
        self.assertEqual(_pages(se.render_pdf("word " * 100, "2026-10-06")), 1)

    def test_words_kept_exactly_line_breaks_too(self):
        self.assertEqual(se.words({"body": "  one\r\ntwo  "}), "one\ntwo")
        self.assertEqual(se.words(None), "")
        # typed characters outside the PDF's font don't break it
        self.assertTrue(se.render_pdf("“Calm” — ✓ 雨", "2026-10-06").startswith(b"%PDF"))

    def test_the_fixed_words_are_education_never_instructions(self):
        for text in (se.TITLE, se.REMINDER, se.OFFER, se.OFFER_LINE, se.STORM_LINE, se.FOOTER):
            low = text.lower()
            for word in ("should", "best", "recommend", "buy", "sell", "hold ", "must"):
                self.assertNotIn(word, low, text)
        self.assertNotIn("$", se.TITLE + se.REMINDER + se.OFFER_LINE)


class NoFiguresTests(unittest.TestCase):
    """A person with distinctive holdings, accounts, email, login and name:
    the envelope made from their saved drill answer holds none of them."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pt_envelope_")
        self.db = os.path.join(self.dir, "t.db")
        portfolio._SCHEMA_READY.discard(os.path.abspath(self.db))
        self.conn = portfolio.connect(self.db)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_the_pdf_has_no_figures_holdings_accounts_email_or_login(self):
        c = self.conn
        uid = auth.create_user(c, "zorblaxlogin", "pw-123456789")
        auth.set_display_name(c, uid, "Quentin")
        c.execute("UPDATE users SET email = ? WHERE id = ?", ("wombat@example.com", uid))
        c.commit()
        meta, rows, totals, _ = manual_entry.build(
            [{"account": "Pelicanbank 4417", "symbol": "QZXW", "quantity": 329.2177,
              "cost_basis": 12345.67, "asset_type": "ETF"}], {"Pelicanbank 4417": 777.77},
            {"QZXW": {"price": 300.0}}, today=date(2026, 9, 10))
        portfolio.write_snapshot(c, uid, meta, rows, totals, manual_entry.SOURCE)
        future_notes.save(c, uid, DRILL, WORDS, now="2026-10-06T10:00:00Z")
        note = future_notes.get(c, uid, DRILL)
        # the way the view makes it (views/future_notes.py render_sealed_envelope)
        text = _pdf_text(se.render_pdf(se.words(note), future_notes.written_on(note)))
        self.assertIn(b"wait a week", text)
        for bad in ("QZXW", "Pelicanbank", "4417", "98,765", "98765", "12,345", "12345",
                    "777", "wombat", "example.com", "zorblax", "Quentin", "$"):
            self.assertNotIn(bad.encode(), text, bad)


class EnvelopeAppTests(tfn.AppTests):
    """The app: the offer under the drill answer, the storm note's line.
    Reuses test_future_notes' scratch app (VTI 15% down: a storm)."""

    @classmethod
    def seed(cls, c):
        super().seed(c)
        cls.uma = cls._investor(c, "uma")                     # wrote an answer, no envelope
        future_notes.save(c, cls.uma, DRILL, WORDS, now="2026-03-05T10:00:00Z")
        cls.vic = cls._investor(c, "vic")                     # made an envelope since
        future_notes.save(c, cls.vic, DRILL, WORDS, now="2026-03-05T10:00:00Z")
        p = prefs.load(c, cls.vic)
        p[se.PREF_MADE] = "2026-03-06"
        prefs.save(c, cls.vic, p)
        auth.set_display_name(c, cls.vic, "Victoria")
        cls.wes = cls._investor(c, "wes")                     # envelope older than the words
        future_notes.save(c, cls.wes, DRILL, WORDS, now="2026-04-01T10:00:00Z")
        p = prefs.load(c, cls.wes)
        p[se.PREF_MADE] = "2026-03-06"
        prefs.save(c, cls.wes, p)
        future_notes.save(c, cls.dana, DRILL, "Quokka drill, kept private")
        p = prefs.load(c, cls.dana)
        p[se.PREF_MADE] = "2026-10-01"
        prefs.save(c, cls.dana, p)

    _run = tsd.DrillAppTests._run

    def setUp(self):
        self.flags_now = "walk storm_drill sealed_envelope"

    def test_offered_under_their_answer_and_opens_to_the_pdf(self):
        with self._run(self.vic, "vic", "Plan") as at:
            self.assertIn("se_offer", self._keys(at))
            self.assertEqual(len(_envelopes(at)), 0)   # nothing made yet
            at.button(key="se_offer").click().run()
            self.assertIn("It holds no numbers about your money", self._text(at))
            self.assertEqual(len(_envelopes(at)), 1)
            box = at.checkbox(key="se_name")                     # her name: off unless ticked
            self.assertFalse(box.value)

    def test_no_name_box_without_a_name_to_put(self):
        with self._run(self.uma, "uma", "Plan") as at:
            at.button(key="se_offer").click().run()
            self.assertEqual(len(_envelopes(at)), 1)
            self.assertNotIn("se_name", [b.key for b in at.checkbox])   # never the login

    def test_no_answer_no_offer(self):
        with self._run(self.kai, "kai", "Plan") as at:
            self.assertIn(future_notes.DRILL_QUESTION, self._text(at))
            self.assertNotIn("se_offer", self._keys(at))

    def test_hidden_with_the_flag_off_or_without_the_drill(self):
        for flags_now in ("walk storm_drill", "walk sealed_envelope"):
            self.flags_now = flags_now
            with self._run(self.vic, "vic", "Plan") as at:
                self.assertNotIn("se_offer", self._keys(at), flags_now)
            with self._run(self.vic, "vic") as at:
                self.assertNotIn(se.STORM_LINE, self._text(at), flags_now)

    def test_the_storm_note_remembers_the_envelope(self):
        with self._run(self.vic, "vic") as at:
            text = self._text(at)
            self.assertIn("Your storm drill", text)
            self.assertIn(se.STORM_LINE, text)
            self.assertIn("wait a week", text)
            for label in [str(b.label) for b in at.button]:
                for word in ("sell", "buy", "trade", "rebalance"):
                    self.assertNotIn(word, label.lower(), label)
        for uid, name in ((self.uma, "uma"), (self.wes, "wes")):   # none, or older words
            with self._run(uid, name) as at:
                text = self._text(at)
                self.assertIn("Your storm drill", text, name)
                self.assertNotIn(se.STORM_LINE, text, name)

    def test_never_in_an_advisors_session(self):
        for page in ("Dashboard", "Plan"):
            with self._run(self.carol, "carol", page, active_user_id=self.dana,
                           two_step_ok=self.carol_ok) as at:
                text = self._text(at)
                self.assertNotIn("se_offer", self._keys(at), page)
                self.assertNotIn(se.STORM_LINE, text, page)
                self.assertNotIn("sealed envelope", text.lower(), page)
                self.assertEqual(len(_envelopes(at)), 0, page)
        with self._run(self.dana, "dana", "Plan") as at:          # while she sees her own
            self.assertIn("se_offer", self._keys(at))


# the notes' own app tests run in test_future_notes; not again here
for _name in [n for n in vars(tfn.AppTests) if n.startswith("test_")]:
    setattr(EnvelopeAppTests, _name, None)


if __name__ == "__main__":
    unittest.main()
