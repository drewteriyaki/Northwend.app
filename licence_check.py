"""Licence evidence and the yearly re-check (PLAN step 5 item 2, decision D15;
master brief 4.1; security audit 1.2c).

When the admin approves an advisor (Admin > Advisor requests, through
admin.approve_advisor) they record the check they made: where they looked
(FINRA BrokerCheck or the SEC's IAPD - there's no official API, so the look-up
itself is by hand), the CRD or licence number that matched, and the day. The
same is recorded about once a year after (Admin > Licence checks). Each check
is a row in licence_checks; the latest one counts:
- due for a re-check once it's DUE_MONTHS (11) months old - Admin lists them,
  and the nightly job emails the admin how many (main(), counts only);
- not current once it's more than CURRENT_MONTHS (13) months old - flagged on
  Admin, and the advisor directory leaves them out (licence_current) until
  they're re-checked.
An advisor with no check on record (approved before this, made an advisor
directly, or from the command line) is due, and not current.

    python licence_check.py --db <file or postgresql://...>   # the nightly step

Prints counts only - never a name, an email or a number.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone

import pgcompat
import settings

SOURCES = ("BrokerCheck", "IAPD")
LINKS = {"BrokerCheck": "https://brokercheck.finra.org/",
         "IAPD": "https://adviserinfo.sec.gov/"}
DUE_MONTHS = 11        # Admin lists them, the nightly job counts them
CURRENT_MONTHS = 13    # past this, not current: off the directory until re-checked
MAIL_EVERY_DAYS = 7    # the "re-checks due" email, at most once a week while any are
MAILED_STATE = "licence_due_mailed"   # app_state: the day (ordinal) it was last sent

# what status() says
NONE, CURRENT, DUE, OVERDUE = "none", "current", "due", "overdue"


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _as_date(value) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def add_months(d: date, months: int) -> date:
    """The same day `months` later (the month's last day if it's shorter)."""
    import calendar
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def check_error(source, crd, checked_on, *, today: date | None = None) -> str | None:
    """What's missing or wrong in a check before it's recorded, or None."""
    if source not in SOURCES:
        return "Pick where you checked: BrokerCheck or IAPD."
    crd = (crd or "").strip()
    if not crd or len(crd) > 40:
        return "Enter the CRD or licence number that matched (up to 40 characters)."
    if not checked_on:
        return "Enter the day you checked."
    try:
        day = _as_date(checked_on)
    except ValueError:
        return "Enter the day you checked."
    if day > (today or _today()):
        return "The day you checked can't be in the future."
    return None


def record(conn, advisor_id: int, *, source: str, crd: str, checked_on, by: int | None = None,
           now: datetime | None = None, commit: bool = True) -> dict:
    """Keep one check: where (SOURCES), the number that matched, the day, and
    which admin (`by`; None from the command line). Raises ValueError for a
    bad one (check_error). Returns the row as stored."""
    error = check_error(source, crd, checked_on,
                        today=(now.astimezone(timezone.utc).date() if now else None))
    if error:
        raise ValueError(error)
    row = {"source": source, "crd": crd.strip(), "checked_on": _as_date(checked_on).isoformat(),
           "checked_by": by, "recorded_at": _utc(now or datetime.now(timezone.utc))}
    conn.execute("INSERT INTO licence_checks (advisor_id, source, crd, checked_on, checked_by, "
                 "recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
                 (advisor_id, row["source"], row["crd"], row["checked_on"], by,
                  row["recorded_at"]))
    if commit:
        conn.commit()
    return row


def last_check(conn, advisor_id: int) -> dict | None:
    """The latest check: {"source", "crd", "checked_on", "checked_by",
    "recorded_at"}, or None."""
    row = conn.execute("SELECT source, crd, checked_on, checked_by, recorded_at FROM "
                       "licence_checks WHERE advisor_id = ? ORDER BY checked_on DESC, id DESC "
                       "LIMIT 1", (advisor_id,)).fetchone()
    return dict(row) if row else None


def last_checks(conn) -> dict[int, dict]:
    """{advisor id: their latest check} - every advisor at once (Admin)."""
    out: dict[int, dict] = {}
    for r in conn.execute("SELECT advisor_id, source, crd, checked_on, checked_by, recorded_at "
                          "FROM licence_checks ORDER BY checked_on, id"):
        out[r["advisor_id"]] = dict(r)
    return out


def status(check: dict | None, *, today: date | None = None) -> str:
    """NONE (no check on record), CURRENT, DUE (DUE_MONTHS old - still
    current) or OVERDUE (more than CURRENT_MONTHS old - not current)."""
    if not check:
        return NONE
    today = today or _today()
    day = _as_date(check["checked_on"])
    if today > add_months(day, CURRENT_MONTHS):
        return OVERDUE
    if today >= add_months(day, DUE_MONTHS):
        return DUE
    return CURRENT


def is_current(check: dict | None, *, today: date | None = None) -> bool:
    return status(check, today=today) in (CURRENT, DUE)


def licence_current(conn, advisor_id: int, *, today: date | None = None) -> bool:
    """Whether this advisor's licence was checked within CURRENT_MONTHS - for
    the advisor directory: an advisor whose isn't is left out until they're
    re-checked (D15). False with no check on record."""
    return is_current(last_check(conn, advisor_id), today=today)


def advisors(conn, *, today: date | None = None) -> list[dict]:
    """Every advisor (not admins: their own accounts switch to the advisor app
    to look around) with their latest check and status, oldest check first
    (none on record first): [{"id", "username", "check", "status"}]."""
    import admin
    listed = admin.listed_admins()
    checks = last_checks(conn)
    out = []
    for r in conn.execute("SELECT id, username, is_admin, terms_version, terms_via, "
                          "email_verified_at FROM users WHERE is_advisor = 1 ORDER BY id"):
        if admin._admin_row(r, listed):
            continue
        check = checks.get(r["id"])
        out.append({"id": r["id"], "username": r["username"], "check": check,
                    "status": status(check, today=today)})
    out.sort(key=lambda a: (a["check"] is not None,
                            a["check"]["checked_on"] if a["check"] else ""))
    return out


def due(conn, *, today: date | None = None) -> list[dict]:
    """Advisors who need a check now: none on record, due or overdue."""
    return [a for a in advisors(conn, today=today) if a["status"] != CURRENT]


def counts(conn, *, today: date | None = None) -> dict:
    """{"due": how many need a check (none on record, due or overdue),
    "overdue": of those, how many aren't current (more than CURRENT_MONTHS
    old, or none on record)} - counts only."""
    rows = due(conn, today=today)
    return {"due": len(rows), "overdue": sum(1 for a in rows if a["status"] in (NONE, OVERDUE))}


def _mailed_day(conn) -> int | None:
    row = conn.execute("SELECT number FROM app_state WHERE name = ?", (MAILED_STATE,)).fetchone()
    return row["number"] if row else None


def remind(conn, app_url: str | None = None, *, today: date | None = None) -> dict:
    """The nightly step: if any advisors need a check, email the admin how many
    (mailer.licence_checks_due, counts only) - at most once every
    MAIL_EVERY_DAYS. Returns {"due", "overdue", "emailed": True / False (the
    email failed) / None (nothing due, sent within the week, or no email set
    up here)}."""
    import error_alerts
    import mailer
    today = today or _today()
    n = counts(conn, today=today)
    last = _mailed_day(conn)
    if (not n["due"] or mailer.status() == "off"   # no key here: nothing to send with
            or (last is not None and today.toordinal() - last < MAIL_EVERY_DAYS)):
        return {**n, "emailed": None}
    link = (app_url or mailer._setting("APP_URL") or "https://app.northwend.app/").split("?")[0]
    sent = mailer.licence_checks_due(error_alerts.alert_to(), f"{link}?page=admin",
                                     n["due"], n["overdue"])
    if sent:
        conn.execute("INSERT INTO app_state (name, number) VALUES (?, ?) "
                     "ON CONFLICT (name) DO UPDATE SET number = excluded.number",
                     (MAILED_STATE, today.toordinal()))
        conn.commit()
    return {**n, "emailed": bool(sent)}


def main(argv=None) -> int:
    from portfolio import connect
    ap = argparse.ArgumentParser(description="Count advisors due a licence re-check and email "
                                             "the admin how many (D15). Prints counts only.")
    ap.add_argument("--db", default=settings.get("DATABASE_URL") or settings.get("PORTFOLIO_DB"),
                    help="SQLite file or Postgres connection string (postgresql://...)")
    ap.add_argument("--app-url", default=settings.get("APP_URL"),
                    help="the app's address, for the link in the email")
    args = ap.parse_args(argv)
    if not args.db:
        ap.error("--db is required (or DATABASE_URL / PORTFOLIO_DB)")
    conn = connect(args.db)
    try:
        res = remind(conn, args.app_url)
    finally:
        conn.close()
    said = {True: "emailed the admin", False: "the email couldn't be sent",
            None: "no email"}[res["emailed"]]
    print(f"Licence re-checks: {res['due']} due ({res['overdue']} not current) - {said}.")
    if res["emailed"] is False:
        return 1   # the workflow's "Tell the admin it failed" step says so
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        pgcompat.close_all_pools()   # no-op unless a Postgres DSN was connected
