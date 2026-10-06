"""What's new (whats_new.py, views/whats_new.py): the dated list of changes
in the name menu - flagged items only where their feature is on, a dot
until the newest entry is opened, nothing else."""

import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import date

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import auth  # noqa: E402
import flags  # noqa: E402
import portfolio  # noqa: E402
import prefs  # noqa: E402
import whats_new  # noqa: E402

FIGURES = re.compile(r"\$\s?\d|\b\d{1,3}(,\d{3})+\b")


class EntryTests(unittest.TestCase):

    def test_entries_are_dated_newest_first_and_well_formed(self):
        dates = [e["date"] for e in whats_new.ENTRIES]
        for d in dates:
            date.fromisoformat(d)
        self.assertEqual(dates, sorted(dates, reverse=True))
        for e in whats_new.ENTRIES:
            self.assertTrue(e["title"].strip())
            self.assertTrue(e["items"])
            for it in e["items"]:
                text = it["text"] if isinstance(it, dict) else it
                self.assertTrue(text.strip())
                self.assertNotRegex(text, FIGURES)             # no amounts in the news
                self.assertNotIn("recommend", text.lower())

    def test_every_flag_named_is_a_real_feature(self):
        for e in whats_new.ENTRIES:
            for it in e["items"]:
                if isinstance(it, dict):
                    self.assertIn(it["flag"], flags.FEATURES, it["text"][:40])

    def test_a_flagged_item_shows_only_where_its_feature_is_on(self):
        entries = [{"date": "2030-01-02", "title": "T",
                    "items": ["Plain", {"text": "Hidden", "flag": "walk"}]},
                   {"date": "2030-01-01", "title": "Only flagged",
                    "items": [{"text": "Also hidden", "flag": "walk"}]}]
        off = whats_new.visible(on=lambda f: False, entries=entries)
        self.assertEqual(off, [{"date": "2030-01-02", "title": "T", "items": ["Plain"]}])
        on = whats_new.visible(on=lambda f: True, entries=entries)
        self.assertEqual([e["items"] for e in on], [["Plain", "Hidden"], ["Also hidden"]])

    def test_the_dot_until_the_newest_is_seen(self):
        entries = [{"date": "2030-01-02", "title": "T", "items": ["a"]}]
        self.assertTrue(whats_new.unseen({}, on=lambda f: False, entries=entries))
        seen = whats_new.mark_seen({"x": 1}, on=lambda f: False, entries=entries)
        self.assertEqual(seen, {"x": 1, whats_new.PREF_SEEN: "2030-01-02"})
        self.assertFalse(whats_new.unseen(seen, on=lambda f: False, entries=entries))

    def test_when(self):
        self.assertEqual(whats_new.when("2026-10-06"), "October 6, 2026")


class PageTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="pt_wn_")
        cls.db = os.path.join(cls.dir, "app.db")
        c = portfolio.connect(cls.db)
        try:
            cls.uid = auth.create_user(c, "wren", "pw-123456789")
            import disclosures
            prefs.save(c, cls.uid, {"first_steps": {"done": True},
                                    "disclosures_seen": disclosures.LAST_UPDATED})
            auth.record_agreement(c, cls.uid, disclosures.LAST_UPDATED, via="")
        finally:
            c.close()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def _app(self, page):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(os.path.join(REPO, "dashboard.py"), default_timeout=60)
        os.environ["PORTFOLIO_DB"] = self.db
        at.session_state["user_id"] = self.uid
        at.session_state["username"] = "wren"
        at.query_params["page"] = page
        return at

    def test_the_page_opens_lists_entries_and_marks_them_seen(self):
        old = os.environ.get("PORTFOLIO_DB")
        try:
            at = self._app("whats-new").run()
            self.assertFalse(at.exception)
            self.assertIn("What's new", [t.value for t in at.title])
            titles = [e.label for e in at.expander]
            self.assertTrue(any(whats_new.visible()[0]["title"] in t for t in titles))
            c = portfolio.connect(self.db)
            try:
                self.assertEqual(prefs.load(c, self.uid).get(whats_new.PREF_SEEN),
                                 whats_new.latest())
            finally:
                c.close()
        finally:
            if old is None:
                os.environ.pop("PORTFOLIO_DB", None)
            else:
                os.environ["PORTFOLIO_DB"] = old


if __name__ == "__main__":
    unittest.main()
