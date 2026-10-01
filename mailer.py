"""The emails the app sends - confirming an email address and resetting a
password - through Resend's HTTP API (https://resend.com/docs/api-reference).
Standard library only. Uses RESEND_API_KEY from .env, then the environment
(Streamlit Cloud's Secrets), like the other keys.

With MAIL_DRY_RUN=1 nothing is sent: the message goes to the server log
instead, so local runs on scratch databases never email anyone. Without a key
(and not a dry run) sending fails, so nobody is told an email is on its way
when it isn't.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from html import escape as html_escape

from update_prices import ENV_PATH, load_env

API_URL = "https://api.resend.com/emails"
SENDER = "Northwend <hello@northwend.app>"
REPLY_TO = "support@northwend.app"
TIMEOUT = 10  # seconds


def _setting(name: str) -> str:
    return (load_env(ENV_PATH).get(name) or os.environ.get(name) or "").strip()


def dry_run() -> bool:
    return _setting("MAIL_DRY_RUN") not in ("", "0", "false")


def send(to: str, subject: str, text: str, html: str | None = None) -> bool:
    """Send one email. True if Resend accepted it (or it was logged in dry-run
    mode); False on any failure - the reason goes to the server log, never
    to the person, and the caller shows a calm "try again" instead."""
    if dry_run():
        print(f"[mailer dry run] to={to} subject={subject!r}\n{text}", file=sys.stderr)
        return True
    if not _setting("RESEND_API_KEY"):
        print("[mailer] not sent: RESEND_API_KEY isn't set", file=sys.stderr)
        return False
    body = {"from": SENDER, "to": [to], "reply_to": REPLY_TO, "subject": subject, "text": text}
    if html:
        body["html"] = html
    req = urllib.request.Request(
        API_URL, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {_setting('RESEND_API_KEY')}",
                 "Content-Type": "application/json", "User-Agent": "northwend-app"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        detail = ""
        if isinstance(exc, urllib.error.HTTPError):
            detail = exc.read().decode("utf-8", "replace")[:300]
        print(f"[mailer] sending failed: {exc} {detail}", file=sys.stderr)
        return False


def _html(paragraphs: list[str], button: tuple[str, str]) -> str:
    """A plain, calm email body: a few paragraphs and one button."""
    label, url = button[0], html_escape(button[1])
    ps ="".join(f'<p style="margin:0 0 14px">{p}</p>' for p in paragraphs)
    return ('<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:15px;'
            'line-height:1.5;color:#1f2937;max-width:480px">'
            f'<p style="margin:0 0 18px;font-size:18px;font-weight:600">Northwend</p>{ps}'
            f'<p style="margin:22px 0"><a href="{url}" style="background:#2563eb;color:#ffffff;'
            'padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:600">'
            f'{label}</a></p>'
            f'<p style="margin:0;font-size:13px;color:#6b7280">Or open this link: {url}</p></div>')


def confirm_email(to: str, link: str, days: int) -> bool:
    lines = ["Welcome to Northwend! Please confirm this is your email address, so you can "
             "use the AI guide and reset your password if you ever need to.",
             f"The link works for {days} days.",
             "Didn't sign up? You can ignore this email - nothing else will be sent."]
    text = f"{lines[0]}\n\nConfirm your email: {link}\n\n{lines[1]}\n\n{lines[2]}\n"
    return send(to, "Confirm your email for Northwend", text,
                _html(lines, ("Confirm my email", link)))


def account_created(to: str, link: str, days: int) -> bool:
    """An account the admin made for someone: a link to choose their password."""
    lines = ["A Northwend account has been set up for you. Choose your password to sign "
             "in - only you will know it.",
             f"The link works once, for {days} days.",
             "Not expecting this? You can ignore this email."]
    text = f"{lines[0]}\n\nChoose your password: {link}\n\n{lines[1]}\n\n{lines[2]}\n"
    return send(to, "Your Northwend account", text,
                _html(lines, ("Choose my password", link)))


def advisor_request(email: str, firm: str, licence: str) -> bool:
    """Tell the admin (the support address) that an account asked for advisor
    access, with what to check."""
    text = (f"{email} asked for advisor access.\n\nFirm: {firm}\nCRD or licence number: "
            f"{licence}\n\nCheck it (BrokerCheck: https://brokercheck.finra.org), then run\n"
            f"  python manage_users.py make-advisor {email}\nor\n"
            f"  python manage_users.py decline-advisor {email}\n")
    return send(REPLY_TO, f"Advisor request: {firm}", text)


def reset_password(to: str, link: str, minutes: int) -> bool:
    lines = ["Someone - hopefully you - asked to reset the password for your Northwend "
             "account.",
             f"The link works once, for {minutes} minutes. Choosing a new password signs "
             "you out everywhere else.",
             "Didn't ask? You can ignore this email - your password stays the same."]
    text = f"{lines[0]}\n\nChoose a new password: {link}\n\n{lines[1]}\n\n{lines[2]}\n"
    return send(to, "Reset your Northwend password", text,
                _html(lines, ("Choose a new password", link)))
