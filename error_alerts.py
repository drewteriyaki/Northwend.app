#!/usr/bin/env python3
"""Error alerts (ROADMAP R1): the admin hears about a broken page or a failed
scheduled job by email, instead of a user finding it first.

Each kind of error - its type plus the file and function where it happened -
is one row in the error_events table: when it was first and last seen, how
many times, and when it was last emailed. At most one email per kind per
hour, across every app process (the claim on the row is one UPDATE, so two
processes can't both send). The Admin page's System panel lists the rows.

Never the person's data: only the error's type, file, function and line - not
its message, which can hold values, tickers or emails - and no user_id. The
full traceback stays in the server log, next to the error code the person saw.

The app (friendly_errors.py) calls report(), which works in a background
thread and never raises, so a failing alert can't slow the page or cause a
second error. A scheduled job that fails runs this file from its workflow
(.github/workflows/scheduled-sync.yml, a step with `if: failure()`):

  python error_alerts.py job "Refresh live prices" --db "$DATABASE_URL" --run-url URL

Alerts go to ALERT_EMAIL (.env, then the environment / the app's Secrets),
or admin@northwend.app. Email itself is mailer.py: with MAIL_DRY_RUN=1 the
alert is written to the log instead.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import traceback
from datetime import datetime, timedelta, timezone

import settings

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_TO = "admin@northwend.app"   # mailer.ADMIN_TO
EVERY = timedelta(hours=1)   # at most one email per kind of error in this time
LIST_LIMIT = 20              # rows shown on the System panel


def _stamp(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def alert_to() -> str:
    """Where alerts go: ALERT_EMAIL, or the admin address."""
    try:
        import mailer
        return mailer._setting("ALERT_EMAIL") or DEFAULT_TO
    except Exception:
        return settings.get("ALERT_EMAIL", DEFAULT_TO)


# ---- what failed, and where ------------------------------------------------ #

def _ours(filename: str) -> bool:
    """A file of this app's own (not Python's or a library's)."""
    if not filename or filename.startswith("<"):   # <string>, <frozen ...>
        return False
    path = os.path.normcase(os.path.abspath(filename))
    if not path.startswith(os.path.normcase(HERE) + os.sep):
        return False
    rel = os.path.relpath(path, HERE).replace(os.sep, "/").lower()
    return not any(part in rel for part in ("site-packages/", ".venv/", "venv/"))


def fingerprint(ex: BaseException) -> dict:
    """{"error_type", "place", "line", "kind"} for an exception: the innermost
    frame in the app's own files (else the innermost of all). The kind leaves
    the line out, so editing a file above it doesn't make it a new kind."""
    frames = traceback.extract_tb(ex.__traceback__) if ex.__traceback__ else []
    mine = [f for f in frames if _ours(f.filename)]
    frame = (mine or frames or [None])[-1]
    error_type = type(ex).__name__
    if frame is None:
        place, line = "unknown", None
    else:
        name = (os.path.relpath(os.path.abspath(frame.filename), HERE).replace(os.sep, "/")
                if _ours(frame.filename) else os.path.basename(frame.filename))
        func = "top level" if frame.name == "<module>" else frame.name
        place, line = f"{name}, {func}", frame.lineno
    return {"error_type": error_type, "place": place, "line": line,
            "kind": f"{error_type} in {place}"}


# ---- the record and the hourly limit -------------------------------------- #

def record(conn, *, error_type: str, place: str, line: int | None = None,
           source: str = "app", now: datetime | None = None, claim: bool = True) -> bool:
    """Count one error of this kind. True if it should be emailed now - it
    wasn't emailed in the last hour, and this call claimed the email (so only
    one process sends it). claim=False only counts it."""
    now = now or datetime.now(timezone.utc)
    kind = f"{error_type} in {place}"
    stamp = _stamp(now)
    conn.execute(
        "INSERT INTO error_events (kind, source, error_type, place, line, first_seen, "
        "last_seen, times) VALUES (?, ?, ?, ?, ?, ?, ?, 1) ON CONFLICT (kind) DO UPDATE SET "
        "last_seen = excluded.last_seen, line = excluded.line, "
        "times = error_events.times + 1",
        (kind, source, error_type, place, line, stamp, stamp))
    if not claim:
        conn.commit()
        return False
    cur = conn.execute(
        "UPDATE error_events SET emailed_at = ? WHERE kind = ? AND "
        "(emailed_at IS NULL OR emailed_at <= ?)", (stamp, kind, _stamp(now - EVERY)))
    conn.commit()
    return cur.rowcount > 0


def unclaim(conn, kind: str, stamp: str) -> None:
    """The email didn't go: let the next error of this kind try again."""
    conn.execute("UPDATE error_events SET emailed_at = NULL WHERE kind = ? AND emailed_at = ?",
                 (kind, stamp))
    conn.commit()


def recent(conn, limit: int = LIST_LIMIT) -> list[dict]:
    """The kinds seen, newest first, for the System panel."""
    return [dict(r) for r in conn.execute(
        "SELECT kind, source, error_type, place, line, first_seen, last_seen, times, "
        "emailed_at FROM error_events ORDER BY last_seen DESC, kind LIMIT ?", (limit,))]


def clear(conn) -> int:
    n = conn.execute("SELECT COUNT(*) AS n FROM error_events").fetchone()["n"]
    conn.execute("DELETE FROM error_events")
    conn.commit()
    return n


# ---- the email --------------------------------------------------------------- #

def _email(f: dict, *, times: int, first_seen: str, copy: str, ref: str = "",
           run_url: str = "", job: str = "") -> tuple[str, str]:
    """(subject, text): what failed and where - nothing of anyone's data."""
    label = f" ({copy})" if copy else ""
    if job:
        subject = f"Northwend{label}: the scheduled job \"{job}\" failed"
        lines = [f"The scheduled job \"{job}\" didn't finish."]
        if run_url:
            lines.append(f"The run, with its log: {run_url}")
    else:
        subject = f"Northwend{label}: {f['kind']}"
        where = f["place"] + (f", line {f['line']}" if f.get("line") else "")
        lines = ["The app hit an unexpected error. The person saw the calm \"something went "
                 "wrong\" message with a Try again button.",
                 f"What: {f['error_type']}\nWhere: {where}"]
        if ref:
            lines.append(f"Error code: {ref} - the full traceback is in the server log next "
                         "to it.")
    lines.append(f"Seen {times} time{'s' if times != 1 else ''} since "
                 f"{first_seen[:16].replace('T', ' ')} UTC. You'll get at most one email "
                 "about this an hour; the Admin page's System panel lists them all.")
    lines.append("No one's data is in this email.")
    return subject, "\n\n".join(lines) + "\n"


def notify(conn, f: dict, *, source: str = "app", copy: str = "", ref: str = "",
           run_url: str = "", job: str = "", send: bool = True,
           now: datetime | None = None) -> bool:
    """Record the error, and email the admin if this kind wasn't emailed in
    the last hour. True if an email went (or was logged in dry-run mode)."""
    import mailer
    now = now or datetime.now(timezone.utc)
    if not record(conn, error_type=f["error_type"], place=f["place"], line=f.get("line"),
                  source=source, now=now, claim=send):
        return False
    row = conn.execute("SELECT times, first_seen FROM error_events WHERE kind = ?",
                       (f["kind"],)).fetchone()
    subject, text = _email(f, times=row["times"], first_seen=row["first_seen"], copy=copy,
                           ref=ref, run_url=run_url, job=job)
    if mailer.send(alert_to(), subject, text):
        return True
    unclaim(conn, f["kind"], _stamp(now))
    return False


def report(db: str | None, ex: BaseException, *, ref: str = "", copy: str = "",
           send: bool = True) -> threading.Thread | None:
    """From the app: note an unexpected error and maybe email it - in the
    background, never raising. Returns the thread (tests wait on it)."""
    try:
        f = fingerprint(ex)
    except Exception:
        return None
    if not db:
        return None

    def work():
        try:
            from portfolio import connect
            conn = connect(db)
            try:
                notify(conn, f, copy=copy, ref=ref, send=send)
            finally:
                conn.close()
        except Exception as exc:  # an alert failing must never cause a second error
            try:
                print(f"[error alerts] couldn't record {f['kind']}: {type(exc).__name__}",
                      file=sys.stderr)
            except Exception:
                pass
    try:
        t = threading.Thread(target=work, name="error-alert", daemon=True)
        t.start()
        return t
    except Exception:
        return None


# ---- a scheduled job that failed (run from the workflow) ------------------- #

def job_failed(db: str, job: str, run_url: str = "", copy: str = "") -> bool:
    """Email that a scheduled job failed, through the same hourly limit. If
    the database can't be reached (often the very reason the job failed), the
    email goes anyway and says so - the limit can't be checked then."""
    import mailer
    f = {"error_type": "Job failed", "place": job, "line": None, "kind": f"Job failed in {job}"}
    try:
        from portfolio import connect
        conn = connect(db)
    except Exception as exc:
        print(f"[error alerts] database unreachable ({type(exc).__name__})", file=sys.stderr)
        subject, text = _email(f, times=1, first_seen=_stamp(datetime.now(timezone.utc)),
                               copy=copy, run_url=run_url, job=job)
        text = text.replace("You'll get at most one email about this an hour; ",
                            "The database couldn't be reached either, so this can repeat "
                            "each run; ")
        return mailer.send(alert_to(), subject, text)
    try:
        return notify(conn, f, source="job", copy=copy, run_url=run_url, job=job)
    finally:
        conn.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Tell the admin a scheduled job failed.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    j = sub.add_parser("job", help="a scheduled job failed")
    j.add_argument("name", help="the job's name, as the email should say it")
    j.add_argument("--db", default=settings.get("DATABASE_URL")
                   or settings.get("PORTFOLIO_DB"))
    j.add_argument("--run-url", default="", help="link to the failed run")
    j.add_argument("--copy", default=settings.get("NORTHWEND_ENV"),
                   help="which copy of the app, e.g. staging")
    args = ap.parse_args(argv)
    if not args.db:
        from portfolio import DEFAULT_DB
        args.db = DEFAULT_DB
    sent = job_failed(args.db, args.name, args.run_url, args.copy)
    print("Alert sent." if sent else "No alert sent (one went out within the hour, or email "
                                      "isn't set up).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
