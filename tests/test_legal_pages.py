"""The published Terms of Use and Privacy Policy (docs/legal/terms-of-use.md,
privacy-policy.md): on the website, linked from the app, nothing left for the
owner or a lawyer to fill in, and their facts the same as the code's."""

import os
import re
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "website"))

import build as site  # noqa: E402
import disclosures  # noqa: E402


def _flat(text: str) -> str:
    return " ".join(text.split())


class LegalTextTests(unittest.TestCase):

    def setUp(self):
        self.terms = site.legal_text("terms.html")
        self.privacy = site.legal_text("privacy.html")

    def test_nothing_left_to_fill_in(self):
        for name, text in (("terms", self.terms), ("privacy", self.privacy)):
            for mark in ("[OWNER", "[LAWYER", "DRAFT", "{{", "TODO", "PLAN ", "`"):
                self.assertNotIn(mark, text, f"{name}: {mark}")
            self.assertIn(f"**Effective date:** {disclosures.LAST_UPDATED}", text)
            self.assertIn(disclosures.OPERATOR_NAME, text)
            self.assertIn(disclosures.CONTACT, text)
            self.assertNotIn("$", text)

    def test_the_host_is_the_one_today_and_changes_with_the_move(self):
        before = _flat(site.legal_text("privacy.html", moved=False))
        self.assertIn("| **Streamlit Community Cloud** | Hosts the app today", before)
        self.assertNotIn("| **Render** |", before)
        self.assertNotIn("sits in front of the app", before)
        after = _flat(site.legal_text("privacy.html", moved=True))
        self.assertIn("| **Render** | Hosts the app", after)
        self.assertIn("sits in front of the app", after)
        self.assertNotIn("Streamlit Community Cloud", after)
        self.assertEqual(_flat(self.privacy), before if not disclosures.HOST_MOVED else after)

    def test_says_what_the_about_page_and_drafts_say(self):
        privacy = _flat(self.privacy)
        for text in ("no third-party analytics", "totals only, inside its own database",
                     "groups of 20 or more", "never shared, sold or sent to the AI",
                     "Leave me out of feature counts", "within 45 days",
                     "what they'd do in a drop (never what they wrote)",
                     "including balances, account names", "If you used to have an advisor:",
                     "reset the login without email", "admin action log",
                     "never dollar amounts, share counts, account names or numbers",
                     "never asks for your brokerage login"):
            self.assertIn(text.lower(), privacy.lower(), text)
        terms = _flat(self.terms)
        for text in ("18 or older", "live in the United States", "education and information only",
                     "not** a registered investment adviser", "Northwend is free",
                     "never ranked", "does not refer clients to advisors", "AI answers can be wrong"):
            self.assertIn(text, terms, text)

    def test_how_long_things_are_kept_matches_the_code(self):
        import admin_log
        import auth
        import tidy
        import unsubscribe
        privacy = _flat(self.privacy)
        self.assertEqual((tidy.UNCONFIRMED_DAYS, tidy.ERROR_EVENT_DAYS, tidy.COUNT_DAYS),
                         (30, 90, 1))
        self.assertIn("after 30 days without a sign-in", privacy)
        self.assertIn("| 90 days |", privacy)
        self.assertEqual(admin_log.KEEP_DAYS, 365)
        self.assertIn("The log is kept for a year", privacy)
        self.assertEqual(unsubscribe.LIFE_DAYS, 365)
        self.assertEqual((auth.SESSION_DAYS, auth.CONFIRM_DAYS, auth.RESET_MINUTES,
                          auth.INVITE_DAYS), (30, 3, 60, 7))
        self.assertIn("Password reset 60 minutes, confirm 3 days, an advisor's setup link 7 days",
                      privacy)
        self.assertEqual(auth.PBKDF2_ITERATIONS, 600_000)
        self.assertIn("(600,000 iterations)", privacy)


class LegalPagesTests(unittest.TestCase):

    def setUp(self):
        self.out = site.render()

    def test_published_on_the_site_and_in_the_sitemap(self):
        for name, path in (("terms.html", "/terms"), ("privacy.html", "/privacy")):
            self.assertIn(name, site.PUBLISHED)
            self.assertIn(f"<loc>{site.SITE_URL}{path}</loc>", self.out["sitemap.xml"])
            page = self.out[name]
            self.assertIn('<h1 id="legal-title" class="display">', page)
            self.assertIn('<nav class="toc"', page)
            self.assertNotIn("**", page)
        self.assertIn('<table class="calc doc-table">', self.out["privacy.html"])

    def test_every_page_links_them_in_the_footer(self):
        for name, page in self.out.items():
            if name.endswith(".html"):
                footer = page[page.index('<footer class="site-footer">'):]
                self.assertIn('<a href="/terms">Terms of Use</a>', footer, name)
                self.assertIn('<a href="/privacy">Privacy Policy</a>', footer, name)
        self.assertIn('href="/terms"', self.out["about.html"].split("<footer")[0])

    def test_the_app_links_them_wherever_people_agree(self):
        self.assertTrue(disclosures.TERMS_URL.endswith("/terms"))
        self.assertTrue(disclosures.PRIVACY_URL.endswith("/privacy"))
        self.assertTrue(disclosures.TERMS_URL.startswith(site.SITE_URL))
        with open(os.path.join(REPO, "dashboard.py"), encoding="utf-8") as fh:
            dash = fh.read()
        # sign-up, a client's setup link, and the once-only box for everyone else
        self.assertEqual(len(re.findall(r"st\.checkbox\(AGREE_BOX, key=", dash)), 3)
        self.assertNotIn('"I\'ve read and agree to the About and disclosures"', dash)
        self.assertIn("disclosures.TERMS_URL", dash)
        self.assertIn("disclosures.PRIVACY_URL", dash)


if __name__ == "__main__":
    unittest.main()
