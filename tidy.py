"""The retention schedule, applied (PLAN D5, item 1b.9): what's kept only for
a while is deleted here, once a night (the Scheduled sync workflow's `tidy`
job, after market close).

    python tidy.py --db <file or postgresql://...>     # or: northwend-tidy --db ...

What goes:
- Accounts made through sign-up whose email was never confirmed, made more
  than 30 days ago and not signed into for 30 days (no sign-in and no
  stay-signed-in session in that time). Each is deleted the way an admin
  deletes one (admin.delete_account), so everything of theirs goes with it.
  Never an account an admin or an advisor made (auth.made_by_themselves),
  never an admin or an advisor, never anyone in an advisor relationship; a
  former client's old advisors keep their own records, as when people
  delete their own account (admin.delete_own).
- Error records (error_events) not seen for 90 days.
- Email links (email_tokens), advisors' setup links (invites) and
  stay-signed-in sessions (login_sessions) past their expiry date.
- Wrong-password counts (login_failures) not added to for a day whose lock has
  run out, and the day-old sign-up and email-send counts (signups,
  email_sends) - the app clears these only when the next one comes in.
- One-minute price bars (intraday_bars '1m') older than 8 days: Yahoo serves
  7 days of them (perf.INTRADAY_INTERVALS); daily bars stay. The quote table's
  minute rows are trimmed by the history sync (live_prices.trim_history).
- The admin action log past a year (admin_log.prune), when that module is in.

Prints counts only - never a name, an email or an id.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

import admin
import auth
import pgcompat
import settings
from portfolio import connect

UNCONFIRMED_DAYS = 30     # D5: self-made accounts never confirmed
ERROR_EVENT_DAYS = 90     # D5: error records
COUNT_DAYS = 1            # D5: wrong-password, sign-up and email-send counts
MINUTE_BAR_DAYS = 8       # D5: minute-by-minute prices, a week (+1 day of slack)
ADMIN_LOG_DAYS = 365      # D5: the admin action log
SYSTEM = -1               # `by` for admin.delete_account: no person, the nightly job

try:   # the admin action log (1b.3) - tidied only once it exists
    import admin_log
except ImportError:
    admin_log = None


def _stamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")     # users, links, sessions, counts


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")    # error_events, intraday bars


def unconfirmed_accounts(conn, *, now: datetime | None = None) -> list[int]:
    """The ids the 30-day rule would delete now (see the module's docstring)."""
    now = now or datetime.now(timezone.utc)
    cutoff = _stamp(now - timedelta(days=UNCONFIRMED_DAYS))
    # created_at, last_login_at and expires_at are all 'YYYY-MM-DD HH:MM:SS'
    # UTC, compared as text. A live stay-signed-in session (they last 30 days)
    # means a sign-in within the 30 days too.
    rows = conn.execute(
        "SELECT u.id, u.terms_version, u.terms_via FROM users u "
        "WHERE u.email_verified_at IS NULL AND u.created_at < ? "
        "AND (u.last_login_at IS NULL OR u.last_login_at < ?) "
        "AND COALESCE(u.is_admin, 0) = 0 AND COALESCE(u.is_advisor, 0) = 0 "
        "AND NOT EXISTS (SELECT 1 FROM advisor_clients a "
        "                WHERE a.client_id = u.id OR a.advisor_id = u.id) "
        "AND NOT EXISTS (SELECT 1 FROM login_sessions s "
        "                WHERE s.user_id = u.id AND s.expires_at > ?) "
        "ORDER BY u.id", (cutoff, cutoff, _stamp(now))).fetchall()
    # admin.delete_account also refuses any admin, NORTHWEND_ADMINS included
    return [r["id"] for r in rows if auth.made_by_themselves(r)]


def run(conn, *, now: datetime | None = None) -> dict:
    """Apply the schedule once. {what: how many deleted}."""
    now = now or datetime.now(timezone.utc)
    done: dict[str, int] = {}

    gone = 0
    for uid in unconfirmed_accounts(conn, now=now):
        # as admin.delete_own: a former client's old advisors keep their own
        # records (PLAN D7); everything that's the account's own goes
        former = [r["advisor_id"] for r in conn.execute(
            "SELECT advisor_id FROM former_clients WHERE client_id = ?", (uid,))]
        if admin.delete_account(conn, uid, by=SYSTEM, keep_records_of=former or None)["ok"]:
            gone += 1
    done["unconfirmed accounts"] = gone

    def delete(name, sql, params):
        cur = conn.execute(sql, params)
        done[name] = max(cur.rowcount or 0, 0)

    stamp = _stamp(now)
    day_ago = _stamp(now - timedelta(days=COUNT_DAYS))
    delete("error records", "DELETE FROM error_events WHERE last_seen < ?",
           (_iso(now - timedelta(days=ERROR_EVENT_DAYS)),))
    delete("email links", "DELETE FROM email_tokens WHERE expires_at <= ?", (stamp,))
    delete("setup links", "DELETE FROM invites WHERE expires_at <= ?", (stamp,))
    delete("sessions", "DELETE FROM login_sessions WHERE expires_at <= ?", (stamp,))
    delete("wrong-password counts", "DELETE FROM login_failures WHERE window_start < ? "
           "AND (locked_until IS NULL OR locked_until < ?)", (day_ago, stamp))
    delete("sign-up counts", "DELETE FROM signups WHERE created_at < ?", (day_ago,))
    delete("email-send counts", "DELETE FROM email_sends WHERE sent_at < ?", (day_ago,))
    # (`interval` is a keyword on Postgres: qualified. ts is ISO, so a day compares.)
    delete("minute bars", "DELETE FROM intraday_bars WHERE intraday_bars.interval = '1m' "
           "AND ts < ?", ((now - timedelta(days=MINUTE_BAR_DAYS)).strftime("%Y-%m-%d"),))
    conn.commit()
    if admin_log is not None:
        done["admin log entries"] = int(admin_log.prune(conn, older_than_days=ADMIN_LOG_DAYS)
                                        or 0)
        conn.commit()
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Delete what the retention schedule keeps only "
                                             "for a while (PLAN D5). Prints counts only.")
    ap.add_argument("--db", default=settings.get("DATABASE_URL") or settings.get("PORTFOLIO_DB"),
                    help="SQLite file or Postgres connection string (postgresql://...)")
    args = ap.parse_args(argv)
    if not args.db:
        ap.error("--db is required (or DATABASE_URL / PORTFOLIO_DB)")
    conn = connect(args.db)
    try:
        done = run(conn)
    finally:
        conn.close()
    print("Tidied: " + ", ".join(f"{k} {v}" for k, v in done.items()))
    if admin_log is None:
        print("(no admin action log in this copy yet - nothing to prune there)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        pgcompat.close_all_pools()   # no-op unless a Postgres DSN was connected
