"""The admin action log (PLAN 1b.3, audit X2, decision D8): who did what to
which login, and when - every action taken in the Admin portal
(views/admin.py, through its `_admin_do`) or with manage_users.py.

Append-only. This module only adds rows (`add`) and reads them (`recent`);
nothing here changes or deletes a row, except `prune`, which drops rows
older than a year for the nightly tidy job (a test checks no other code
does). Deleting an account clears its id in the rows that name it
(admin.ACCOUNT_REFERENCES) - the row itself stays.

What a row holds: the time, the admin's login id (NULL for the command line,
which has no login), a fixed action word (ACTIONS), the account it was done
to (if any) and a short detail made by the code - never anyone's holdings,
figures, passwords or codes. The Admin portal shows the last 100 on System.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# The only action words a row can have.
ACTIONS = (
    "approve_advisor",    # made an advisor (approving a request, or straight away)
    "licence_check",      # recorded a licence check (licence_check.py) - source and day only
    "decline_advisor",    # turned down an advisor request
    "remove_advisor",     # took advisor rights away
    "make_admin",         # command line only
    "remove_admin",       # command line only
    "create_account",
    "delete_account",
    "reset_password",     # emailed a reset link
    "temp_password",      # set a temporary password (an account without an email)
    "set_password",       # command line: typed a new password for someone
    "unlock",             # cleared a wrong-password or wrong-code lock
    "reset_two_step",
    "encrypt_two_step",   # command line: sealed the readable two-step keys (counts, key id)
    "ai_limits",          # lifted or restored the monthly AI limits
    "link_client",
    "unlink_client",
    "make_codes",         # made invite codes (never the codes themselves)
    "revoke_code",
    "sign_out_all",
    "own_role",           # the admin's own account switched investor / advisor app
    "clear_cache",
    "test_email",
    "clear_errors",
)
KEEP_DAYS = 365          # how long rows are kept (prune, the nightly tidy job)
SHOWN = 100              # how many the Admin portal shows
MAX_DETAIL = 200
COMMAND_LINE = "command line"


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def add(conn, admin_id: int | None, action: str, target_id: int | None = None,
        detail: str = "", *, now: datetime | None = None, commit: bool = True) -> None:
    """Write one row. `admin_id` is the admin's login (None: the command
    line); `action` one of ACTIONS; `detail` a few words made by the code -
    never holdings, figures, passwords or codes."""
    if action not in ACTIONS:
        raise ValueError(f"not an admin_log action: {action!r}")
    if admin_id is None and not detail.startswith(COMMAND_LINE):
        detail = COMMAND_LINE + (f": {detail}" if detail else "")
    conn.execute("INSERT INTO admin_log (at, admin_id, action, target_id, detail) "
                 "VALUES (?, ?, ?, ?, ?)",
                 (_utc(now or datetime.now(timezone.utc)), admin_id, action, target_id,
                  (detail or "")[:MAX_DETAIL]))
    if commit:
        conn.commit()


def recent(conn, limit: int = SHOWN) -> list[dict]:
    """The newest `limit` rows, newest first: {"at", "admin" (login, or None),
    "action", "target" (login, or None - no account, or a deleted one),
    "detail"}."""
    rows = conn.execute(
        "SELECT l.at, l.action, l.detail, l.admin_id, l.target_id, a.username AS admin, "
        "t.username AS target FROM admin_log l LEFT JOIN users a ON a.id = l.admin_id "
        "LEFT JOIN users t ON t.id = l.target_id ORDER BY l.id DESC LIMIT ?",
        (int(limit),)).fetchall()
    return [{"at": r["at"], "admin": r["admin"], "action": r["action"],
             "target": r["target"], "detail": r["detail"] or ""} for r in rows]


def prune(conn, older_than_days: int = KEEP_DAYS, *, now: datetime | None = None) -> int:
    """The retention rule: drop rows older than `older_than_days` (a year).
    The only code that removes a row. Returns how many went."""
    cutoff = _utc((now or datetime.now(timezone.utc)) - timedelta(days=older_than_days))
    cur = conn.execute("DELETE FROM admin_log WHERE at < ?", (cutoff,))
    conn.commit()
    return cur.rowcount
