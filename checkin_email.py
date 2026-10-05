#!/usr/bin/env python3
"""The Monthly Walk's reminder (ROADMAP R1; it was the monthly check-in's,
item 11): one short email a month to someone who asked for it (Account >
Monthly walk), saying only that it's time - no amounts, holdings, verdict
or anything else about their money.

Run daily by .github/workflows/scheduled-sync.yml:

  python checkin_email.py --db "$DATABASE_URL" --app-url https://app.northwend.app/

Sent at most once a month per person (remembered in their settings,
checkin.PREF_SENT, so a re-run doesn't send twice), on or after the day
they chose, only while Home has the walk waiting for them
(checkin.wants_email), and only to a confirmed email - an advisor's client
whose email isn't confirmed gets nothing. Off unless the person turned it
on. Does nothing when email isn't set up (RESEND_API_KEY) or --app-url is
missing; --dry-run lists how many would get it without sending anything.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date

import checkin
import mailer
import prefs
from portfolio import DEFAULT_DB, connect

SUBJECT = "Time for your monthly walk"
LINES = ("Time for your monthly walk - about 3 minutes.",
         ("A quick look at your holdings and your mix, one short read, and what your own "
          "plan says for the month. It's waiting on Home whenever suits you."),
         "To stop these emails, turn off the reminder under Account > Monthly walk.")


def recipients(conn) -> list[dict]:
    """Investors and clients with a confirmed email who turned the reminder
    on: [{"id", "email"}]. (The settings are read again in run(); the LIKE
    only narrows which ones.)"""
    return [dict(r) for r in conn.execute(
        "SELECT u.id, u.email FROM users u JOIN user_prefs p ON p.user_id = u.id "
        "WHERE COALESCE(u.is_advisor, 0) = 0 AND u.email IS NOT NULL AND u.email != '' "
        "AND u.email_verified_at IS NOT NULL AND p.data LIKE ? ORDER BY u.id",
        (f'%"{checkin.PREF_EMAIL}": true%',))]


def reminder(to: str, link: str) -> bool:
    """The email itself: no figures, nothing about their money."""
    text = f"{LINES[0]}\n\n{LINES[1]}\n\nOpen Northwend: {link}\n\n{LINES[2]}\n"
    return mailer.send(to, SUBJECT, text, mailer._html(list(LINES), ("Open Northwend", link)))


def run(conn, app_url: str, today: date, *, send=reminder, dry_run: bool = False) -> dict:
    link = app_url.rstrip("/") + "/?page=dashboard"
    done = {"sent": 0, "not_due": 0, "failed": 0, "would_send": 0}
    for r in recipients(conn):
        p = prefs.load(conn, r["id"])
        if not checkin.wants_email(p, today):
            done["not_due"] += 1
            continue
        if dry_run:
            done["would_send"] += 1
            continue
        if done["sent"] or done["failed"]:
            time.sleep(0.6)   # the email service takes a couple a second
        if send(r["email"], link):
            p[checkin.PREF_SENT] = checkin.month_of(today)
            prefs.save(conn, r["id"], p)
            done["sent"] += 1
        else:
            done["failed"] += 1
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Send monthly walk reminders to those who "
                                             "asked for them.")
    ap.add_argument("--db", default=os.environ.get("PORTFOLIO_DB") or DEFAULT_DB)
    ap.add_argument("--app-url", default=os.environ.get("APP_URL") or "",
                    help="the app's address, for the link in the email")
    ap.add_argument("--dry-run", action="store_true",
                    help="count who would get it; send and record nothing")
    args = ap.parse_args(argv)
    if not args.app_url:
        print("Skipped: no --app-url (or APP_URL) to link to.")
        return 0
    if mailer.status() == "off" and not args.dry_run:
        print("Skipped: email isn't set up (RESEND_API_KEY).")
        return 0
    conn = connect(args.db)
    try:
        done = run(conn, args.app_url, date.today(), dry_run=args.dry_run)
    finally:
        conn.close()
    print(", ".join(f"{k} {v}" for k, v in done.items()))
    return 1 if done["failed"] and not done["sent"] else 0


if __name__ == "__main__":
    sys.exit(main())
