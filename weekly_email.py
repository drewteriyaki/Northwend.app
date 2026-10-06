#!/usr/bin/env python3
"""The advisors' Monday email: their week in numbers - reviews due, coming
due, proposals a client accepted and open next steps - with a link to Your
clients. Counts only: no client names or figures leave the app by email.

Run weekly by .github/workflows/scheduled-sync.yml (Monday mornings):

  python weekly_email.py --db "$DATABASE_URL" --app-url https://app.northwend.app/

Sent once per advisor per week (remembered in their settings, so a re-run
doesn't send twice), only when there's something to say, only to a
confirmed email (or one an admin set up), and never to an advisor who
turned it off (Your clients > How clients see you > Monday email). Does
nothing when email isn't set up (RESEND_API_KEY) or --app-url is missing.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date

import advising
import mailer
import prefs
import settings
from portfolio import DEFAULT_DB, connect

PREF_OFF = "weekly_email_off"      # the advisor turned it off
PREF_SENT = "weekly_email_week"    # the week it was last sent, advising.week_of()


def counts(conn, advisor_id: int, today: date) -> dict:
    """{"due", "soon", "accepted", "steps"} over the advisor's clients."""
    out = {"due": 0, "soon": 0, "accepted": 0, "steps": 0}
    for r in conn.execute("SELECT client_id FROM advisor_clients WHERE advisor_id = ?",
                          (advisor_id,)).fetchall():
        cid = r["client_id"]
        review, days = advising.review_status(advising.last_review(conn, cid), today)
        if review in ("never", "due"):
            out["due"] += 1
        elif days is not None and days > advising.REVIEW_EVERY_DAYS - advising.SOON_DAYS:
            out["soon"] += 1
        out["accepted"] += conn.execute(
            "SELECT COUNT(*) AS n FROM proposals WHERE client_id = ? AND advisor_id = ? AND "
            "status = 'accepted' AND archived_at IS NULL", (cid, advisor_id)).fetchone()["n"]
        out["steps"] += len(advising.open_next_steps(
            advising.list_notes(conn, cid, include_private=True, advisor_id=advisor_id)))
    return out


def lines(c: dict) -> list[str]:
    """What the email says - empty when there's nothing to act on."""
    def n(k, one, many):
        return f"{c[k]} {one if c[k] == 1 else many}"
    out = []
    if c["due"]:
        out.append(n("due", "client is due a review", "clients are due a review"))
    if c["soon"]:
        out.append(n("soon", "review comes due", "reviews come due")
                   + f" in the next {advising.SOON_DAYS} days")
    if c["accepted"]:
        out.append(n("accepted", "client accepted a proposal", "clients accepted a proposal")
                   + " - over to you")
    if c["steps"]:
        out.append(n("steps", "next step is still open", "next steps are still open"))
    return out


def recipients(conn) -> list[dict]:
    """Advisors with an email that's confirmed, or set up by an admin (not
    made by themselves at sign-up - auth.made_by_themselves)."""
    return [dict(r) for r in conn.execute(
        "SELECT id, email FROM users WHERE is_advisor = 1 AND email IS NOT NULL AND email != '' "
        "AND (email_verified_at IS NOT NULL OR terms_version IS NULL OR terms_via IS NOT NULL) "
        "ORDER BY id")]


def run(conn, app_url: str, today: date, *, send=mailer.advisor_week) -> dict:
    week = advising.week_of(today)
    link = app_url.rstrip("/") + "/?page=your-clients"
    done = {"sent": 0, "nothing": 0, "off": 0, "already": 0, "failed": 0}
    for a in recipients(conn):
        p = prefs.load(conn, a["id"])
        if p.get(PREF_OFF):
            done["off"] += 1
            continue
        if p.get(PREF_SENT) == week:
            done["already"] += 1
            continue
        said = lines(counts(conn, a["id"], today))
        if not said:
            done["nothing"] += 1
            continue
        if done["sent"] or done["failed"]:
            time.sleep(0.6)   # the email service takes a couple a second
        if send(a["email"], link, said):
            p[PREF_SENT] = week
            prefs.save(conn, a["id"], p)
            done["sent"] += 1
        else:
            done["failed"] += 1
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Send advisors their Monday summary email.")
    ap.add_argument("--db", default=settings.get("PORTFOLIO_DB", DEFAULT_DB))
    ap.add_argument("--app-url", default=settings.get("APP_URL"),
                    help="the app's address, for the link in the email")
    args = ap.parse_args(argv)
    if not args.app_url:
        print("Skipped: no --app-url (or APP_URL) to link to.")
        return 0
    if mailer.status() == "off":
        print("Skipped: email isn't set up (RESEND_API_KEY).")
        return 0
    conn = connect(args.db)
    try:
        done = run(conn, args.app_url, date.today())
    finally:
        conn.close()
    print(", ".join(f"{k} {v}" for k, v in done.items()))
    return 1 if done["failed"] and not done["sent"] else 0


if __name__ == "__main__":
    sys.exit(main())
