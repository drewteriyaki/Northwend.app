"""Principle test (PLAN 1a.10, audit 1.7b): no figures in email, ever.

Every public email function in mailer.py is found by introspection and
rendered with realistic sample inputs (SAMPLES); what would be sent - the
subject, the text, the html and the headers - must carry no currency amount
and no digit group. Dates ("Q3 2026", "September 2026"), small counts
("7 days", "3 clients") and the links are fine. A new email function fails
here until it has a sample.

    python -m unittest tests.test_principle_emails        (from the repo root)
"""

import inspect
import os
import re
import sys
import unittest
import unittest.mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import mailer  # noqa: E402
import standing_line  # noqa: E402
import weekly_email  # noqa: E402

# public functions in mailer.py that don't build an email
NOT_EMAILS = {"send", "dry_run", "status", "sender", "unsubscribe_headers"}

LINK = "https://app.northwend.app/?page=advisor-notes&token=Zx_kQ-abcdefABCDEF"
UNSUB = "https://app.northwend.app/?unsubscribe=Qw_er-tyUIOPasdfgh"
TO = "dana.lee@example.com"
ADVISOR = "Carol Reyes, Reyes Wealth Partners"
# the advisor's standing line (standing_line.py, master brief 4.4)
STANDING = standing_line.text("Carol Reyes", "Reyes Wealth Partners")
# the CRD or licence number an advisor typed: an identifier the admin looks
# up, sent only to the admin address - not a figure
LICENCE = "CRD 7012345"

# function name -> one or more sets of arguments (each a realistic email)
SAMPLES = {
    "confirm_email": [dict(to=TO, link=LINK, days=7)],
    "confirm_new_email": [dict(to=TO, link=LINK, days=7)],
    "email_changed": [dict(to=TO, new_email="dana.new@example.com", link=LINK)],
    "report_ready": [dict(to=TO, link=LINK, advisor_name=ADVISOR, period="Q3 2026",
                          standing=STANDING, from_name=ADVISOR),
                     dict(to=TO, link=LINK, advisor_name=ADVISOR, period="September 2026",
                          standing=STANDING)],
    "proposal_shared": [dict(to=TO, link=LINK, advisor_name=ADVISOR, standing=STANDING)],
    "proposal_answered": [dict(to=TO, link=LINK, client_name="Dana Lee", accepted=True),
                          dict(to=TO, link=LINK, client_name="Chen household",
                               accepted=False)],
    "advisor_week": [dict(to=TO, link=LINK, unsubscribe=UNSUB,
                          lines=weekly_email.lines({"due": 3, "soon": 1, "accepted": 2,
                                                    "steps": 12})),
                     dict(to=TO, link=LINK, lines=["1 client is due a review"])],
    "client_invite": [dict(to=TO, link=LINK, advisor_name=ADVISOR, days=7,
                           from_name=ADVISOR)],
    "account_created": [dict(to=TO, link=LINK, days=7)],
    "advisor_request": [dict(email="carol@reyeswealth.example", firm="Reyes Wealth Partners",
                             licence=LICENCE, app_link=LINK),
                        dict(email="carol@reyeswealth.example", firm="Reyes Wealth Partners",
                             licence=LICENCE)],
    "advisor_approved": [dict(to=TO, link=LINK)],
    "advisor_declined": [dict(to=TO, link=LINK)],
    "advisor_message": [dict(to=TO, link=LINK, advisor_name=ADVISOR, standing=STANDING,
                             from_name=ADVISOR)],
    # the nightly licence step (licence_check.remind): counts only
    "licence_checks_due": [dict(to=TO, link=LINK, due=3, overdue=1),
                           dict(to=TO, link=LINK, due=1, overdue=0)],
    "relationship_ended": [dict(to=TO, link=LINK, advisor_name=ADVISOR),
                           dict(to=TO, link=LINK, advisor_name=ADVISOR, setup_days=7,
                                from_name=ADVISOR)],
    "client_stopped_sharing": [dict(to=TO, link=LINK, client_name="Dana Lee")],
    # introductions (intros.py): only that one is waiting, or answered
    "intro_received": [dict(to=TO, link=LINK)],
    "intro_answered": [dict(to=TO, link=LINK, advisor_name="Carol Reyes", standing=STANDING,
                            from_name=ADVISOR)],
    "reset_password": [dict(to=TO, link=LINK, minutes=30)],
}

_URL = re.compile(r"https?://[^\s\"'<>)]+")
_ALLOWED = [
    re.compile(r"\b(?:Q[1-4]|January|February|March|April|May|June|July|August|September|"
               r"October|November|December)\s+(?:19|20)\d\d\b"),   # a period's label
    re.compile(r"\b(?:19|20)\d\d-\d\d-\d\d\b"),                     # a date
    re.compile(r"\.\.\.\d{3}\b"),                                   # an account's last 3 digits
    re.compile(r"font-size:\d+px|max-width:\d+px|padding:\d+px \d+px|margin:[\d px]+|"
               r"border-radius:\d+px|font-weight:\d+|line-height:[\d.]+|#[0-9a-fA-F]{6}"),
]
# what a figure looks like: a currency sign or code next to a number, a
# thousands group (1,234 or 1 234), cents (12.50), or a long run of digits
FIGURES = [
    re.compile(r"[$€£¥]\s*\d|\d\s*[$€£¥]"),
    re.compile(r"\b(?:USD|EUR|GBP|dollars?)\b", re.I),
    re.compile(r"\d{1,3}(?:[, ]\d{3})+"),
    re.compile(r"\d+\.\d\d\b"),
    re.compile(r"\d{4,}"),
    re.compile(r"\d+(?:\.\d+)?\s*%"),
]


def email_functions() -> dict:
    return {name: fn for name, fn in inspect.getmembers(mailer, inspect.isfunction)
            if fn.__module__ == mailer.__name__ and not name.startswith("_")
            and name not in NOT_EMAILS}


def render(fn, kwargs) -> list[dict]:
    """What `fn(**kwargs)` would send: one dict per send() call."""
    sent = []

    def fake_send(to, subject, text, html=None, *, from_name=None, headers=None):
        sent.append({"to": to, "subject": subject, "text": text, "html": html or "",
                     "from": mailer.sender(from_name), "headers": headers or {}})
        return True
    with unittest.mock.patch.object(mailer, "send", fake_send):
        fn(**kwargs)
    return sent


def figures_in(text: str) -> list[str]:
    text = _URL.sub(" ", text)
    for rx in _ALLOWED:
        text = rx.sub(" ", text)
    text = text.replace(LICENCE, " ")
    return [m.group(0) for rx in FIGURES for m in rx.finditer(text)]


class EmailFigures(unittest.TestCase):

    def test_every_email_function_has_a_sample(self):
        found = set(email_functions())
        self.assertTrue(found, "no email functions found in mailer.py")
        missing = sorted(found - set(SAMPLES))
        self.assertEqual(missing, [], "add realistic sample arguments to SAMPLES for "
                                      f"{missing} - and keep figures out of it")
        self.assertEqual(sorted(set(SAMPLES) - found), [], "SAMPLES names a function that "
                                                           "isn't in mailer.py any more")

    def test_no_figures_in_any_email(self):
        for name, fn in email_functions().items():
            for kwargs in SAMPLES.get(name, []):
                with self.subTest(email=name, args=sorted(kwargs)):
                    inspect.signature(fn).bind(**kwargs)   # the sample still fits
                    sent = render(fn, kwargs)
                    self.assertEqual(len(sent), 1, "each email function sends one email")
                    mail = sent[0]
                    for part in ("subject", "text", "html", "from"):
                        self.assertEqual(figures_in(mail[part]), [], f"{name}: {part}")
                    for key, value in mail["headers"].items():
                        self.assertEqual(figures_in(f"{key}: {value}"), [], f"{name}: {key}")
                    self.assertTrue(mail["subject"].strip() and mail["text"].strip())

    def test_advisor_authored_emails_carry_the_standing_line(self):
        # master brief 4.4: whatever an advisor sends a client says whose advice it is
        for name in ("report_ready", "proposal_shared", "advisor_message", "intro_answered"):
            self.assertIn("standing", inspect.signature(getattr(mailer, name)).parameters)
            for kwargs in SAMPLES[name]:
                with self.subTest(email=name):
                    mail = render(getattr(mailer, name), kwargs)[0]
                    self.assertIn(STANDING, mail["text"])
                    self.assertIn("Carol Reyes&#x27;s advice, from Reyes Wealth Partners - not "
                                  "Northwend&#x27;s.", mail["html"])

    def test_the_check_itself_catches_figures(self):
        # so a quiet pass means something
        for bad in ("Your portfolio is worth $12,400", "up 4.2% this month", "1,234 shares",
                    "a balance of 98765", "cash 12.50", "EUR 300", "£ 40",
                    "account 12345678"):
            self.assertTrue(figures_in(bad), bad)
        for fine in ("Your progress report for Q3 2026", "The link works for 7 days.",
                     "3 clients are due a review", "Brokerage ...123",
                     f"Open it: {LINK}", "September 2026"):
            self.assertEqual(figures_in(fine), [], fine)


if __name__ == "__main__":
    unittest.main()
