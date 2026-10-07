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
import sys
import urllib.error
import urllib.request
from html import escape as html_escape

import settings

API_URL = "https://api.resend.com/emails"
SENDER = "Northwend <hello@northwend.app>"
SENDER_ADDRESS = "hello@northwend.app"   # every email comes from here, whatever the name
REPLY_TO = "support@northwend.app"
# Where mail for the person running Northwend goes (advisor requests; error_alerts,
# ai_spend and licence_check use it too): ALERT_EMAIL when set, else this.
ADMIN_TO = "admin@northwend.app"
TIMEOUT = 10  # seconds
# PLACEHOLDER - for the owner to fill in. Northwend's postal address (a street
# address, a PO box or a registered mailbox), printed at the foot of every
# Trail Conditions email: CAN-SPAM asks for one in a commercial email. While it's
# empty, trail_conditions.py sends nothing at all and says why in the job's log.
POSTAL_ADDRESS = ""


class EmailNotSent(Exception):
    """An account email (confirm, reset, a new address) that Resend didn't
    accept - its daily or monthly allowance used up, a bad key, or no answer.
    Never raised by send(): the app raises and catches it only to tell the
    admin through error_alerts (its kind and place, never the address)."""


def _setting(name: str) -> str:
    return settings.get(name, env_file=True)   # .env first, then the environment


def _admin_to() -> str:
    """Where mail for the person running Northwend goes: ALERT_EMAIL, or ADMIN_TO."""
    return _setting("ALERT_EMAIL") or ADMIN_TO


def dry_run() -> bool:
    return _setting("MAIL_DRY_RUN") not in ("", "0", "false")


def status() -> str:
    """How email is set up here, for the Admin page: "sending", "dry run" or "off"."""
    if dry_run():
        return "dry run"
    return "sending" if _setting("RESEND_API_KEY") else "off"


def _one_line(text: str | None, limit: int, drop: str = "") -> str:
    """Text for an email header: control characters and line breaks of any
    kind (CR, LF, NEL, the Unicode line and paragraph separators) - and the
    characters in `drop` - become spaces, runs of spaces become one, and it's
    cut to `limit` characters. A name typed into the app can't start a new
    header line this way."""
    import unicodedata
    out = "".join(" " if ch in drop or unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp")
                  else ch for ch in (text or ""))
    return " ".join(out.split())[:limit].strip()


def sender(from_name: str | None = None) -> str:
    """The From line: SENDER, or `"<from_name> via Northwend" <hello@...>` for
    an email sent on an advisor's behalf. Quotes, angle brackets, backslashes
    and line breaks are taken out of the name, so it can't change the address."""
    name = _one_line(from_name, 70, drop='"<>\\').strip(" ,")
    return f'"{name} via Northwend" <{SENDER_ADDRESS}>' if name else SENDER


def unsubscribe_headers(url: str | None) -> dict:
    """The List-Unsubscribe headers for an email someone can turn off with a
    link (unsubscribe.py), or {} without one. The https address works for
    mail apps that open it (a GET). List-Unsubscribe-Post (RFC 8058) is what
    Gmail and Yahoo look for, but their one-click POST can't be answered yet:
    Streamlit serves the page, not a POST endpoint, so such a POST changes
    nothing until the hosting can take it (PLAN step 4). The link in the
    email itself always works."""
    if not url:
        return {}
    return {"List-Unsubscribe": f"<{url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}


UNSUBSCRIBE_LINE = "Stop these emails in one click"


def send(to: str, subject: str, text: str, html: str | None = None, *,
         from_name: str | None = None, headers: dict | None = None) -> bool:
    """Send one email. True if Resend accepted it (or it was logged in dry-run
    mode); False on any failure - the reason goes to the server log, never
    to the person, and the caller shows a calm "try again" instead.
    `from_name` puts an advisor's name in the From line (sender()). The
    subject is made one line (_one_line): some carry a name someone typed.
    `headers`: extra email headers (unsubscribe_headers), each made one line."""
    subject = _one_line(subject, 150)
    if dry_run():
        print(f"[mailer dry run] from={sender(from_name)} to={to} subject={subject!r}\n{text}",
              file=sys.stderr)
        return True
    if not _setting("RESEND_API_KEY"):
        print("[mailer] not sent: RESEND_API_KEY isn't set", file=sys.stderr)
        return False
    body = {"from": sender(from_name), "to": [to], "reply_to": REPLY_TO, "subject": subject,
            "text": text}
    if html:
        body["html"] = html
    if headers:
        body["headers"] = {k: _one_line(v, 500) for k, v in headers.items()}
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


def _html(paragraphs: list[str], button: tuple[str, str], *, unsubscribe: str = "",
          address: str = "") -> str:
    """A plain, calm email body: a few paragraphs and one button - and, with
    `unsubscribe` (a link, unsubscribe.py), a small line to stop the emails;
    with `address`, the sender's postal address at the foot (POSTAL_ADDRESS)."""
    label, url = button[0], html_escape(button[1])
    stop = (f'<p style="margin:14px 0 0;font-size:13px;color:#6b7280">'
            f'<a href="{html_escape(unsubscribe)}" style="color:#6b7280">{UNSUBSCRIBE_LINE}</a>'
            '</p>' if unsubscribe else "")
    if address:
        stop += ('<p style="margin:10px 0 0;font-size:12px;color:#6b7280">'
                 f'Northwend, {html_escape(address)}</p>')
    ps ="".join(f'<p style="margin:0 0 14px">{p}</p>' for p in paragraphs)
    return ('<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:15px;'
            'line-height:1.5;color:#1f2937;max-width:480px">'
            f'<p style="margin:0 0 18px;font-size:18px;font-weight:600">Northwend</p>{ps}'
            f'<p style="margin:22px 0"><a href="{url}" style="background:#2563eb;color:#ffffff;'
            'padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:600">'
            f'{label}</a></p>'
            f'<p style="margin:0;font-size:13px;color:#6b7280">Or open this link: {url}</p>'
            f'{stop}</div>')


def confirm_email(to: str, link: str, days: int) -> bool:
    lines = ["Welcome to Northwend! Please confirm this is your email address, so you can "
             "use the AI guide and reset your password if you ever need to.",
             f"The link works for {days} days.",
             "Didn't sign up? You can ignore this email - nothing else will be sent."]
    text = f"{lines[0]}\n\nConfirm your email: {link}\n\n{lines[1]}\n\n{lines[2]}\n"
    return send(to, "Confirm your email for Northwend", text,
                _html(lines, ("Confirm my email", link)))


def confirm_new_email(to: str, link: str, days: int) -> bool:
    """Changing the account's email (Account page): confirm the new one."""
    lines = ["You asked to use this address for your Northwend account. Confirm it and it "
             "becomes your email - and your login, if you sign in with your email.",
             f"The link works for {days} days.",
             "Didn't ask for this? You can ignore this email - nothing changes."]
    text = f"{lines[0]}\n\nConfirm this email: {link}\n\n{lines[1]}\n\n{lines[2]}\n"
    return send(to, "Confirm your new email for Northwend", text,
                _html(lines, ("Confirm this email", link)))


def email_changed(to: str, new_email: str, link: str) -> bool:
    """To the OLD address once a change is confirmed - in case it wasn't them."""
    lines = [f"The email on your Northwend account was changed to {new_email}. This address "
             "won't get account emails any more.",
             "Wasn't you? Reply to this email or write to support@northwend.app straight away, "
             "and reset your password."]
    text = f"{lines[0]}\n\n{lines[1]}\n\nNorthwend: {link}\n"
    return send(to, "Your Northwend email was changed", text,
                _html([html_escape(x) for x in lines], ("Open Northwend", link)))


def report_ready(to: str, link: str, advisor_name: str, period: str, *, standing: str,
                 from_name: str | None = None) -> bool:
    """A progress report is waiting - no figures in the email itself. Only
    sent to a confirmed email (proposals.who_to_tell), so the client can
    sign in to read it. `standing`: the advisor's standing line
    (standing_line.text - the advice is theirs, not Northwend's)."""
    lines = [f"{advisor_name} has shared your progress report for {period}.",
             "Sign in to read it - for your privacy, the figures stay in Northwend and aren't "
             "sent by email.", standing]
    text = f"{lines[0]}\n\n{lines[1]}\n\nRead it: {link}\n\n{lines[2]}\n"
    return send(to, f"Your progress report for {period}", text,
                _html([html_escape(x) for x in lines], ("Read my report", link)),
                from_name=from_name)


def proposal_shared(to: str, link: str, advisor_name: str, *, standing: str) -> bool:
    """An advisor shared a proposal (proposals.py) - no figures in the email
    itself. `standing`: the advisor's standing line (standing_line.text)."""
    lines = [f"{advisor_name} has shared a proposal with you: a suggested mix for your "
             "investments, with a note on why.",
             "Sign in to read it and let them know what you think - for your privacy, the "
             "details stay in Northwend and aren't sent by email.",
             "Nothing is bought or sold until you and your advisor decide together.", standing]
    text = f"{lines[0]}\n\n{lines[1]}\n\nRead it: {link}\n\n{lines[2]}\n\n{lines[3]}\n"
    return send(to, "Your advisor has a proposal for you", text,
                _html([html_escape(x) for x in lines], ("Read the proposal", link)))


def proposal_answered(to: str, link: str, client_name: str, accepted: bool) -> bool:
    """A client answered their advisor's proposal - no figures in the email."""
    if accepted:
        subject = f"{client_name} accepted your proposal"
        first = (f"{client_name} said \"let's go ahead\" to your proposal. Nothing has been "
                 "bought or sold in Northwend - it's over to you to take it from here with them.")
    else:
        subject = f"{client_name} answered your proposal"
        first = (f"{client_name} said \"not right now\" to your proposal. You could talk it "
                 "through at your next conversation, or make a new one.")
    lines = [first, "The details are in Northwend - they aren't sent by email."]
    text = f"{lines[0]}\n\n{lines[1]}\n\nOpen their plan: {link}\n"
    return send(to, subject, text,
                _html([html_escape(x) for x in lines], ("Open their plan", link)))


def advisor_week(to: str, link: str, lines: list[str], unsubscribe: str = "") -> bool:
    """An advisor's Monday summary (weekly_email.py): counts only - no client
    names or figures in the email. `unsubscribe`: its one-click link."""
    intro = "Here's your week in Northwend:"
    outro = ("Client names and details are in the app. To stop these emails, turn off "
             "Monday email under Your clients > How clients see you.")
    text = intro + "\n\n" + "\n".join(f"- {x}" for x in lines) + \
        f"\n\nOpen your clients: {link}\n\n{outro}\n"
    if unsubscribe:
        text += f"\n{UNSUBSCRIBE_LINE}: {unsubscribe}\n"
    return send(to, "Your week in Northwend", text,
                _html([intro, *lines, outro], ("Open your clients", link), unsubscribe=unsubscribe),
                headers=unsubscribe_headers(unsubscribe))


def client_invite(to: str, link: str, advisor_name: str, days: int, *,
                  from_name: str | None = None) -> bool:
    """An advisor's setup link for their client (auth.create_invite), from
    the advisor's name and firm (`from_name`, see sender())."""
    lines = [f"{advisor_name} has set up a Northwend account for you, to follow your "
             "investments and plan together.",
             "Choose your password - only you will know it - then answer a few quick questions "
             "about your goals and how you feel about ups and downs, so your advisor can prepare "
             "for your first conversation.",
             f"The link works once, for {days} days. Not expecting this? You can ignore it."]
    text = f"{lines[0]}\n\n{lines[1]}\n\nSet up your account: {link}\n\n{lines[2]}\n"
    return send(to, f"{advisor_name} invited you to Northwend", text,
                _html([html_escape(x) for x in lines], ("Set up my account", link)),
                from_name=from_name)


def account_created(to: str, link: str, days: int) -> bool:
    """An account the admin made for someone: a link to choose their password."""
    lines = ["A Northwend account has been set up for you. Choose your password to sign "
             "in - only you will know it.",
             f"The link works once, for {days} days.",
             "Not expecting this? You can ignore this email."]
    text = f"{lines[0]}\n\nChoose your password: {link}\n\n{lines[1]}\n\n{lines[2]}\n"
    return send(to, "Your Northwend account", text,
                _html(lines, ("Choose my password", link)))


def advisor_request(email: str, firm: str, licence: str, app_link: str = "") -> bool:
    """Tell the admin (the support address) that an account asked for advisor
    access, with what to check and where to decide: the Admin portal
    (`app_link` + ?page=admin), or the command line."""
    admin = f"{app_link.split('?')[0]}?page=admin" if app_link else ""
    text = (f"{email} asked for advisor access.\n\nFirm: {firm}\nCRD or licence number: "
            f"{licence}\n\nCheck it (BrokerCheck: https://brokercheck.finra.org), then "
            + (f"approve or decline it in the Admin portal, under Advisor requests:\n  {admin}\n\n"
               "Or from the command line:\n" if admin else "run\n")
            + f"  python manage_users.py make-advisor {email}\nor\n"
            f"  python manage_users.py decline-advisor {email}\n"
            "Either way, they get an email saying what was decided.\n")
    return send(_admin_to(), f"Advisor request: {firm}", text)


def advisor_approved(to: str, link: str) -> bool:
    """Their advisor request was approved (auth.set_advisor, via
    admin.approve_advisor): what to do first."""
    lines = ["Your advisor access is ready.",
             "Next: sign in, then set up two-step sign-in - it keeps your clients' accounts "
             "safe and takes about a minute. After that, add your first client from Your "
             "clients.",
             "Questions? Reply to this email - we're happy to help."]
    text = f"{lines[0]}\n\n{lines[1]}\n\nSign in: {link}\n\n{lines[2]}\n"
    return send(to, "Your Northwend advisor access is ready", text,
                _html(lines, ("Sign in to Northwend", link)))


def licence_checks_due(to: str, link: str, due: int, overdue: int) -> bool:
    """The nightly licence step (licence_check.remind, D15): how many advisors
    need their registration looked up again - counts only, never a name or a
    number. To the admin (error_alerts.alert_to)."""
    lines = [f"{due} advisor{'s are' if due != 1 else ' is'} due a licence check: no check on "
             "record, or the last one is 11 months old or more.",
             (f"{overdue} of them {'have' if overdue != 1 else 'has'} no check in the last 13 "
              "months, so they're left out of the advisor directory until they're re-checked."
              if overdue else "All of them are still within 13 months of their last check."),
             "Look each one up on BrokerCheck or IAPD, then record it in the Admin portal, under "
             "Licence checks."]
    text = "\n\n".join(lines) + f"\n\nOpen Admin: {link}\n"
    return send(to, "Advisor licence checks due", text, _html(lines, ("Open Admin", link)))


def advisor_declined(to: str, link: str) -> bool:
    """Their advisor request was declined (auth.decline_advisor, via
    admin.decline_advisor). Polite, and says what to do next."""
    lines = ["Thank you for asking for advisor access to Northwend. We weren't able to "
             "approve it this time.",
             "This usually happens when we can't match the firm or the CRD or licence number "
             "to a public record, or when some details were missing.",
             "Your account still works as an investor account. If you think we got it wrong, "
             "or you'd like to send more details, reply to this email or write to "
             f"{REPLY_TO}."]
    text = "\n\n".join(lines) + f"\n\nNorthwend: {link}\n"
    return send(to, "Your Northwend advisor request", text,
                _html(lines, ("Open Northwend", link)))


def advisor_message(to: str, link: str, advisor_name: str, *, standing: str,
                    from_name: str | None = None) -> bool:
    """An advisor sent their clients a message (Your clients > Message
    clients). Only that it's there - never the message itself or any figures.
    `standing`: the advisor's standing line (standing_line.text)."""
    lines = [f"{advisor_name} sent you a message.",
             "Sign in to read it on your Your advisor page - for your privacy, messages stay "
             "in Northwend and aren't sent by email.", standing]
    text = f"{lines[0]}\n\n{lines[1]}\n\nRead it: {link}\n\n{lines[2]}\n"
    return send(to, f"{advisor_name} sent you a message", text,
                _html([html_escape(x) for x in lines], ("Read the message", link)),
                from_name=from_name)


def intro_received(to: str, link: str) -> bool:
    """Someone sent an advisor an introduction from Find a guide (intros.py).
    Only that one is waiting - never who, their message or anything about them."""
    lines = ["Someone who found you in Find a guide has asked for an introduction.",
             "Sign in to read it under Introductions on Your clients - for their privacy, "
             "introductions stay in Northwend and aren't sent by email."]
    text = f"{lines[0]}\n\n{lines[1]}\n\nRead it: {link}\n"
    return send(to, "You have a new introduction in Northwend", text,
                _html([html_escape(x) for x in lines], ("Read it", link)))


def intro_answered(to: str, link: str, advisor_name: str, *, standing: str,
                   from_name: str | None = None) -> bool:
    """An advisor answered (or declined) a person's introduction (intros.py).
    Only that there's an answer - never its text or any figures. `standing`:
    the advisor's standing line (standing_line.text)."""
    lines = [f"{advisor_name} answered your introduction.",
             "Sign in to read it under Your introductions on Find a guide - for your privacy, "
             "answers stay in Northwend and aren't sent by email. Nothing in your account is "
             "shared unless you choose it.", standing]
    text = f"{lines[0]}\n\n{lines[1]}\n\nRead it: {link}\n\n{lines[2]}\n"
    return send(to, f"{advisor_name} answered your introduction", text,
                _html([html_escape(x) for x in lines], ("Read the answer", link)),
                from_name=from_name)


def relationship_ended(to: str, link: str, advisor_name: str, *, setup_days: int | None = None,
                       from_name: str | None = None) -> bool:
    """An advisor ended the relationship (advising.end_relationship): the
    client keeps their account. With `setup_days`, `link` is a "choose your
    password" link (they never set one up). No figures."""
    lines = [f"{advisor_name} has ended your advisory relationship in Northwend.",
             "Your account and holdings are still here - nothing has been deleted. From now on "
             "the account is yours to manage: your plan, your goals and bringing in new "
             "statements. Your advisor no longer sees it."]
    if setup_days:
        lines.append("You haven't chosen a password yet. Choose one to keep using your "
                     f"account - the link works once, for {setup_days} days.")
        button = "Choose my password"
    else:
        button = "Open Northwend"
    lines.append("Questions about Northwend? Reply to this email - we're happy to help.")
    text = "\n\n".join(lines[:-1]) + f"\n\n{button}: {link}\n\n{lines[-1]}\n"
    return send(to, "Your advisory relationship in Northwend has ended", text,
                _html([html_escape(x) for x in lines], (button, link)), from_name=from_name)


def client_stopped_sharing(to: str, link: str, client_name: str) -> bool:
    """A client stopped sharing their account with their advisor
    (advising.end_relationship, by the client). No figures."""
    lines = [f"{client_name} has stopped sharing their Northwend account with you, so you no "
             "longer see their portfolio.",
             "Your notes, proposals and reports about them are kept: find them under Your "
             "clients > Former clients, where you can export their record."]
    text = f"{lines[0]}\n\n{lines[1]}\n\nOpen your clients: {link}\n"
    return send(to, f"{client_name} stopped sharing their account with you", text,
                _html([html_escape(x) for x in lines], ("Open your clients", link)))


def reset_password(to: str, link: str, minutes: int) -> bool:
    lines = ["Someone - hopefully you - asked to reset the password for your Northwend "
             "account.",
             f"The link works once, for {minutes} minutes. Choosing a new password signs "
             "you out everywhere else.",
             "Didn't ask? You can ignore this email - your password stays the same."]
    text = f"{lines[0]}\n\nChoose a new password: {link}\n\n{lines[1]}\n\n{lines[2]}\n"
    return send(to, "Reset your Northwend password", text,
                _html(lines, ("Choose a new password", link)))
