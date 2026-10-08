"""Send feedback (the open beta): a short message from anyone signed in,
emailed to the person running Northwend (mailer._admin_to()) - and stored
nowhere in the app. The window is views/feedback.py, opened from the name
menu and the About page.

What the email holds, and nothing else: the person's own words, the kind
they picked, the name of the page they were on (never what was on it), this
copy's version and which copy it is (Live, Staging, Local), and a short
reference. The reference is the first 10 characters of a SHA-256 of
"feedback:<login id>": the same for every message from one login, so the
owner can tell repeats apart, but it isn't the login's number, name or
email. Their email address goes in only when they tick "You can reply to me
by email" - then as the Reply-To, so a reply reaches them. Never a figure,
a holding, an account or anything about a client: an advisor working in a
client's account sends feedback as themselves.

The only thing written to the database is the rate-limit count
(rate_limits.FEEDBACK: a hashed count, tidied away after a day).
Standard library only (plus mailer).
"""

from __future__ import annotations

import hashlib
import sys

import mailer

MAX_CHARS = 2000
INTRO = "Tell us what's confusing, broken or missing. We read every one."
PRIVATE = ("Please leave out passwords and account numbers. Your holdings and figures "
           "aren't sent - only what you write here.")
THANKS = "Thanks - it's on its way."
EMPTY = "Please write a few words first."
TOO_LONG = f"Please keep it to {MAX_CHARS:,} characters."
NOT_SENT = ("It didn't go through just now. Please try again in a little while, or write to "
            "support@northwend.app.")
REPLY_BOX = "You can reply to me by email"
REPLY_HELP = ("Your sign-in email goes with it, so we can write back. Leave this off and we "
              "won't know who sent it.")
NO_EMAIL = ("To get a reply, add and confirm an email on Account, or write to "
            "support@northwend.app.")

# (key, what the person sees) - always in this order
KINDS = (("broken", "Something's broken"), ("confusing", "Something's confusing"),
         ("idea", "An idea"), ("other", "Other"))
KIND_WORDS = dict(KINDS)


def reference(login_id: int) -> str:
    """The short code that tells one login's messages apart (see above)."""
    return hashlib.sha256(f"feedback:{int(login_id)}".encode("utf-8")).hexdigest()[:10]


def problem(words: str | None) -> str | None:
    """Why `words` can't be sent (EMPTY, TOO_LONG), or None."""
    words = (words or "").strip()
    if not words:
        return EMPTY
    if len(words) > MAX_CHARS:
        return TOO_LONG
    return None


def compose(words: str, kind: str, *, page: str, version: str, copy: str,
            login_id: int, reply: bool) -> tuple[str, str]:
    """The email's subject and text. `page` is a page's name only."""
    kind_words = KIND_WORDS.get(kind, KIND_WORDS["other"])
    subject = f"Northwend feedback: {kind_words}"
    lines = [
        "Someone sent feedback from the app.",
        "",
        f"Kind: {kind_words}",
        f"Page: {mailer._one_line(page, 60) or 'not known'}",
        f"Copy: {copy}",
        f"Version: {version or 'not known'}",
        f"Reference: {reference(login_id)} (the same for each message from one login - "
        "not their name or email)",
        ("Reply: they'd like a reply - answering this email goes to them."
         if reply else "Reply: they didn't ask for one, so there's no address."),
        "",
        "Their words:",
        "",
        (words or "").strip()[:MAX_CHARS],
    ]
    return subject, "\n".join(lines)


def send(words: str, kind: str, *, page: str, version: str, copy: str, login_id: int,
         reply_email: str | None = None) -> bool:
    """Email it to the owner; True once mailer accepted it (or logged it in a
    dry run). `reply_email`: the login's own confirmed email, only when they
    ticked REPLY_BOX - it becomes the Reply-To and nothing else."""
    reply_email = (reply_email or "").strip() or None
    subject, text = compose(words, kind, page=page, version=version, copy=copy,
                            login_id=login_id, reply=bool(reply_email))
    ok = mailer.send(mailer._admin_to(), subject, text, reply_to=reply_email)
    if not ok:
        print(f"[feedback] not sent ({kind}, reference {reference(login_id)})", file=sys.stderr)
    return ok
