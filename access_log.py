"""The advisor access log (PLAN step 5.8, master brief 4.3.5, audit 1.2d and
1.6f): one row each time an advisor opens a page in a client's account -
when, which advisor, which client, which page. Never figures, never what was
on the page.

Written by dashboard.py where the account shown switches to a client
(ON_CLIENT), once per page opened: a rerun of the same page (a click, a
refresh of a chart) isn't a new row, and neither is the same page again
within REPEAT_SECONDS in the same browser session (is_new_view). The client
sees their own rows on their Account page, "Who has looked at your account"
(for_client, the last SHOWN_DAYS); an advisor only ever gets their own rows.

Append-only. This module only adds rows (`record`) and reads them
(`for_client`); nothing changes or deletes a row except `prune`, the 7-year
retention rule the nightly tidy job runs (PLAN B6) - a test checks no other
code does. Deleting an account keeps these rows (admin.KEPT_AFTER_DELETE);
on Postgres the app's role can't UPDATE or DELETE them
(portfolio._append_only_grants).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

REPEAT_SECONDS = 30 * 60   # the same page again within this, in one session: not a new row
SHOWN_DAYS = 90            # what the client's Account page lists
KEEP_DAYS = 2557           # 7 years (PLAN B6)
MAX_PAGE = 60
# pages that are the advisor's own while a client's account is chosen (the
# login's Account, About, What's new, Admin; their book on Your clients):
# opening them isn't a look at the client's account
NOT_THE_CLIENTS = ("Clients", "Account", "What's new", "About", "Admin", "Advisor preview")


def _utc(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:      # a plain datetime is UTC already
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_new_view(last: tuple | None, client_id: int, page: str, now_ts: float) -> bool:
    """Whether opening `page` in `client_id`'s account at `now_ts` (seconds)
    is a new page view, given `last` = (client_id, page, ts) of the last row
    this browser session wrote (None: none yet). Pure, for the dashboard."""
    if last is None:
        return True
    last_client, last_page, last_ts = last
    return ((last_client, last_page) != (client_id, page)
            or now_ts - last_ts >= REPEAT_SECONDS)


def record(conn, advisor_id: int, client_id: int, page: str, *,
           now: datetime | None = None, commit: bool = True) -> None:
    """Write one row: `advisor_id` opened `page` in `client_id`'s account.
    The caller has checked they may (auth.can_view)."""
    advisor_id, client_id = int(advisor_id), int(client_id)
    if advisor_id == client_id:
        raise ValueError("an advisor's own account isn't logged")
    page = str(page or "").strip()[:MAX_PAGE]
    if not page:
        raise ValueError("which page")
    conn.execute("INSERT INTO advisor_access_log (at, advisor_id, client_id, page) "
                 "VALUES (?, ?, ?, ?)", (_utc(now), advisor_id, client_id, page))
    if commit:
        conn.commit()


def for_client(conn, client_id: int, viewer_id: int, *, days: int | None = SHOWN_DAYS,
               now: datetime | None = None) -> list[dict]:
    """The rows about `client_id`, newest first, as `viewer_id` may see them:
    the client gets every advisor's; an advisor only their own; anyone else
    nothing. `days`: only the last so many (None: all). Each {"at",
    "advisor_id", "advisor" (their name, or None once that account is gone),
    "page"}."""
    client_id, viewer_id = int(client_id), int(viewer_id)
    where, params = "l.client_id = ?", [client_id]
    if viewer_id != client_id:
        where += " AND l.advisor_id = ?"
        params.append(viewer_id)
    if days is not None:
        where += " AND l.at >= ?"
        params.append(_utc((now or datetime.now(timezone.utc)) - timedelta(days=days)))
    rows = conn.execute(
        "SELECT l.at, l.advisor_id, l.page, u.display_name, u.username "
        f"FROM advisor_access_log l LEFT JOIN users u ON u.id = l.advisor_id WHERE {where} "
        "ORDER BY l.at DESC, l.id DESC", tuple(params)).fetchall()
    return [{"at": r["at"], "advisor_id": r["advisor_id"],
             "advisor": r["display_name"] or r["username"], "page": r["page"]} for r in rows]


def prune(conn, older_than_days: int = KEEP_DAYS, *, now: datetime | None = None) -> int:
    """The retention rule (PLAN B6): drop rows older than 7 years. The only
    code that removes a row; the nightly tidy job runs it. Returns how many
    went."""
    cutoff = _utc((now or datetime.now(timezone.utc)) - timedelta(days=older_than_days))
    cur = conn.execute("DELETE FROM advisor_access_log WHERE at < ?", (cutoff,))
    conn.commit()
    return max(cur.rowcount or 0, 0)
