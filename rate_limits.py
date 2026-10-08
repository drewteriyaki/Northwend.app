"""How often one account may do the heavier things (security audit 1.8d):
read an uploaded file, save holdings or activity, and build a download (a
ZIP export or a PDF). The numbers are generous - a real person, or an
advisor working through a big book of clients, never reaches them - so they
only stop a script, a stuck key or someone misusing a login from tying up
the server or filling the database.

Counted per login (`LOGIN_ID`): an advisor working in a client's account
counts against the advisor, never the client. Over a limit the page says
CALM and nothing is read, saved or built; it is never an error.

The counts are rows in `email_sends` (the hashed, day-long counts the email
and client-check limits already use - auth.py), so no new table: the key is
a SHA-256 of "login:<id>" in `email_key`, `address_key` is '', `purpose` is
PURPOSE_PREFIX plus the action. Counts only - never what was uploaded,
saved or downloaded. They're tidied away after a day here (on the next
count) and nightly by tidy.py. Standard library only.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

UPLOAD = "upload"   # a file read: a positions or activity CSV, screenshots, a client list
SAVE = "save"       # holdings or activity saved, an account removed, the example loaded,
                    # clients added from a file
EXPORT = "export"   # a ZIP of your data or a client's record, a plan, report or proposal PDF
INVITE = "invite"   # a Doing it together invitation link made (together.py)
NUDGE = "nudge"     # a Doing it together nudge email sent (together.py)

# (per hour, per day) for each action, per login. Change them here only.
LIMITS = {
    UPLOAD: (30, 200),
    SAVE: (60, 300),
    EXPORT: (30, 150),
    # (a nudge is also once a week per partner, and there are at most 3
    # partners - together.py; these stop a script making and cancelling links)
    INVITE: (20, 50),
    NUDGE: (20, 50),
}
LABELS = {
    UPLOAD: "Files read (CSV, activity, screenshots, client lists)",
    SAVE: "Saves (holdings, activity, account removals, the example, clients from a file)",
    EXPORT: "Downloads built (ZIP exports, plan, report and proposal PDFs)",
    INVITE: "Doing it together invitations made",
    NUDGE: "Doing it together nudges sent",
}
PURPOSE_PREFIX = "limit_"   # email_sends.purpose: limit_upload, limit_save, limit_export...
CALM = "You've done a lot of that in a short time - please try again in a little while."


def _stamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")      # as auth.py's email_sends rows


def _key(login_id: int) -> str:
    """The count's key for a login: hashed, as the other limits' keys are."""
    return hashlib.sha256(f"login:{int(login_id)}".encode("utf-8")).hexdigest()


def allow(conn, login_id: int | None, action: str, *, now: datetime | None = None) -> bool:
    """Whether `login_id` may do `action` now. True counts it; False (over the
    hour's or the day's limit) counts nothing, so waiting is enough. No login
    (nothing to count against) is always allowed. Rows older than a day are
    tidied away first, as the email limits do."""
    per_hour, per_day = LIMITS[action]
    if login_id is None:
        return True
    now = now or datetime.now(timezone.utc)
    key, purpose = _key(login_id), PURPOSE_PREFIX + action
    conn.execute("DELETE FROM email_sends WHERE sent_at < ?",
                 (_stamp(now - timedelta(days=1)),))
    hour_ago = _stamp(now - timedelta(hours=1))
    times = [r["sent_at"] for r in conn.execute(
        "SELECT sent_at FROM email_sends WHERE email_key = ? AND purpose = ?", (key, purpose))]
    if len(times) >= per_day or sum(t >= hour_ago for t in times) >= per_hour:
        conn.commit()
        return False
    conn.execute("INSERT INTO email_sends (email_key, address_key, purpose, sent_at) "
                 "VALUES (?, '', ?, ?)", (key, purpose, _stamp(now)))
    conn.commit()
    return True


def rows_for_admin() -> list[tuple[str, str]]:
    """Admin > System's lines: the limits as set here - never anyone's counts."""
    return [(LABELS[a], f"{h} an hour, {d} a day per login") for a, (h, d) in LIMITS.items()]
