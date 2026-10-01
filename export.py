"""Export everything (ROADMAP D1): one account's own data as a ZIP of CSV
files, from Profile > Your data, next to deleting it. Pure logic, no
Streamlit.

What's in it: the account's holdings and their history, cash, activity,
plan, goals, profile answers, settings, watchlist, AI use counts and an
advisor request; for a client, what their advisor shared with them (notes
not marked private, proposals that were shared, progress reports); for an
advisor, their model portfolios. Never a password, a sign-in or email-link
token, or a hash of an internet address; never another person's data (an
advisor's notes and reports about their clients stay with the clients).
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import datetime, timezone

# (file name, table, the column that is this account, extra WHERE)
OWN = [
    ("holdings", "positions", "user_id", ""),
    ("snapshots", "snapshots", "user_id", ""),
    ("cash", "account_totals", "user_id", ""),
    ("activity", "transactions", "user_id", ""),
    ("value_history", "value_log", "user_id", ""),
    ("account_names", "account_labels", "user_id", ""),
    ("profile", "investor_profiles", "user_id", ""),
    ("plan", "plans", "user_id", ""),
    ("contributions", "contributions", "user_id", ""),
    ("watchlist", "watchlist", "user_id", ""),
    ("settings", "user_prefs", "user_id", ""),
    ("ai_use", "ai_usage", "user_id", ""),
    ("advisor_request", "advisor_requests", "user_id", ""),
    ("from_your_advisor_notes", "advisor_notes", "client_id", " AND private = 0"),
    ("from_your_advisor_proposals", "proposals", "client_id", " AND status != 'draft'"),
    ("from_your_advisor_reports", "progress_reports", "client_id", ""),
    ("your_model_portfolios", "model_portfolios", "advisor_id", ""),
    # when two-step sign-in was turned on - its key and backup codes never
    ("two_step_sign_in", "two_step", "user_id", ""),
]
# never exported, whatever table they turn up in
SECRET_PARTS = {"password", "salt", "token", "hash", "ip", "secret"}   # whole parts of a column name
ACCOUNT_COLUMNS = ("username", "email", "email_verified_at", "created_at", "last_login_at",
                   "terms_version", "terms_accepted_at", "is_advisor")

README = """Everything Northwend holds for your account, exported {when} UTC.

One CSV file per kind of data; a file is left out when there's nothing in it.
Open them in any spreadsheet. Dates are UTC.

- account.csv: your login and email, and when the account was made
- holdings.csv, snapshots.csv, cash.csv: what you imported or entered
- activity.csv, value_history.csv: buys, sells and value over time
- plan.csv, contributions.csv, profile.csv: your goals and answers
- watchlist.csv, settings.csv, account_names.csv: your choices in the app
- ai_use.csv: how many AI requests you made each month (not what you asked)
- from_your_advisor_*.csv: what your advisor shared with you, if you have one
- two_step_sign_in.csv: when you turned on two-step sign-in, if you did

Not included: your password and sign-in records, which are never stored in a
readable form, or your two-step key and backup codes. Uploaded files and screenshots were never kept, so there's
nothing to export for them.
"""


def _safe(col: str) -> bool:
    return not SECRET_PARTS & set(col.lower().split("_"))


def _csv(rows: list[dict]) -> str:
    cols = [c for c in rows[0].keys() if _safe(c)]
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(cols)
    for r in rows:
        w.writerow(["" if r[c] is None else r[c] for c in cols])
    return out.getvalue()


def collect(conn, user_id: int) -> dict[str, list[dict]]:
    """{file name: rows} for every kind of data the account has."""
    found = {}
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is not None:
        row = dict(row)
        found["account"] = [{c: row.get(c) for c in ACCOUNT_COLUMNS if c in row}]
    for name, table, col, extra in OWN:
        rows = [dict(r) for r in conn.execute(
            f"SELECT * FROM {table} WHERE {col} = ?{extra}", (user_id,))]
        if rows:
            found[name] = rows
    return found


def export_zip(conn, user_id: int, *, now: datetime | None = None) -> bytes:
    """The ZIP: README.txt plus one CSV per kind of data."""
    now = now or datetime.now(timezone.utc)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", README.format(when=now.strftime("%Y-%m-%d %H:%M")))
        for name, rows in collect(conn, user_id).items():
            z.writestr(f"{name}.csv", _csv(rows))
    return buf.getvalue()


def file_name(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return f"northwend-export-{now.strftime('%Y-%m-%d')}.zip"
