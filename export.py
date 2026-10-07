"""Export everything (ROADMAP D1): one account's own data as a ZIP of CSV
files, from Profile > Your data, next to deleting it. Pure logic, no
Streamlit.

What's in it: the account's holdings and their history, cash, activity,
plan, goals, profile answers, settings, watchlist, AI use counts, an
account map and an advisor request; for a client, what their advisor shared with them (notes
not marked private, proposals that were shared, progress reports); for an
advisor, their model portfolios. Never a password, a sign-in or email-link
token, or a hash of an internet address; never another person's data (an
advisor's notes and reports about their clients stay with the clients).

Also an advisor's record of one client, or of all of them (client_record_zip,
all_client_records_zip): the Advisor notes page and Your clients.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from datetime import datetime, timezone

import advising
import auth
import consent

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
    ("money_going_out", "money_out", "user_id", ""),
    ("watchlist", "watchlist", "user_id", ""),
    ("settings", "user_prefs", "user_id", ""),
    ("ai_use", "ai_usage", "user_id", ""),
    ("advisor_request", "advisor_requests", "user_id", ""),
    # as the client sees them: not private, not archived (advising.archive_note)
    ("from_your_advisor_notes", "advisor_notes", "client_id",
     " AND private = 0 AND archived_at IS NULL"),
    ("from_your_advisor_proposals", "proposals", "client_id",
     " AND status != 'draft' AND archived_at IS NULL"),
    ("from_your_advisor_reports", "progress_reports", "client_id", ""),
    ("your_model_portfolios", "model_portfolios", "advisor_id", ""),
    # an advisor's clients whose relationship ended (advising.end_relationship)
    ("your_former_clients", "former_clients", "advisor_id", ""),
    # when two-step sign-in was turned on - its key and backup codes never
    ("two_step_sign_in", "two_step", "user_id", ""),
    # private to them: in their own export only, never an advisor's client record
    ("notes_to_future_you", "future_notes", "user_id", ""),
    # the "if something happens to me" binder (account_map.py) - their own only
    ("account_map", "account_map", "user_id", ""),
    # an advisor: each time they accepted the advisor agreement (advisor_agreement.py)
    ("advisor_agreement", "advisor_agreements", "user_id", ""),
    # an advisor: each check of their registration (licence_check.py)
    ("licence_checks", "licence_checks", "advisor_id", ""),
    # an advisor's own directory listing (directory.py)
    ("your_directory_listing", "advisor_profiles", "user_id", ""),
    # introductions (intros.py): the ones you sent, and - for an advisor - the
    # ones sent to you (without the sender's account id: LEFT_OUT_COLUMNS)
    ("your_introductions", "intro_requests", "person_id", ""),
    ("introductions_to_you", "intro_requests", "advisor_id", ""),
    # each "Price look wrong?" note they sent (price_report.py)
    ("price_reports", "price_reports", "user_id", ""),
    # a client's sharing with an advisor, with the words they were shown
    # (consent.py), and each time an advisor opened their account (access_log.py)
    ("sharing_with_an_advisor", "consent_records", "client_id", ""),
    ("advisor_visits", "advisor_access_log", "client_id", ""),
    # Explain it to someone (explain_share.py): the links they made - when,
    # until when, first name shown or not, visits (never the token or its hash)
    ("share_links", "share_links", "user_id", ""),
]
# never exported, whatever table they turn up in
SECRET_PARTS = {"password", "salt", "token", "hash", "ip", "secret"}   # whole parts of a column name
ACCOUNT_COLUMNS = ("username", "email", "email_verified_at", "created_at", "last_login_at",
                   "terms_version", "terms_accepted_at", "terms_via", "age_confirmed_at",
                   "us_resident_at", "is_advisor")
# the advisor's working record, not part of what the client was shown
LEFT_OUT_COLUMNS = {"from_your_advisor_notes": {"history", "archived_at"},
                    # which admin recorded it: an id of someone else's login
                    "licence_checks": {"checked_by"},
                    # the sender's account id: someone else's login
                    "introductions_to_you": {"person_id"},
                    # a share link's hash: never needed, never exported (SECRET_PARTS too)
                    "share_links": {"token_hash"}}

README = """Everything Northwend holds for your account, exported {when} UTC.

One CSV file per kind of data; a file is left out when there's nothing in it.
Open them in any spreadsheet. Dates are UTC.

- account.csv: your login and email, when the account was made, and when you
  agreed to the About and disclosures and confirmed you're 18 or older and
  live in the United States
- holdings.csv, snapshots.csv, cash.csv: what you imported or entered
- activity.csv, value_history.csv: buys, sells and value over time
- plan.csv, contributions.csv, profile.csv: your goals and answers
- money_going_out.csv: planned expenses and withdrawals in your plan
- watchlist.csv, settings.csv, account_names.csv: your choices in the app
- ai_use.csv: how many AI requests you made each month (not what you asked)
- your_former_clients.csv: for an advisor, clients whose relationship ended
- from_your_advisor_*.csv: what your advisor shared with you, if you have one
- two_step_sign_in.csv: when you turned on two-step sign-in, if you did
- notes_to_future_you.csv: the notes you wrote to yourself on a holding or your plan
  (symbol __STORM_DRILL__: what you wrote you'd do in a drop, on the Stress test)
- account_map.csv: your account map - who to call, paperwork, notes for family
- advisor_agreement.csv, licence_checks.csv: for an advisor, when you accepted
  the advisor agreement (and which version), and each check of your
  registration (where it was looked up, the number matched and the day)
- your_directory_listing.csv: for an advisor, your listing in Find a guide
- your_introductions.csv: introductions you sent from Find a guide - your
  message, what you chose to share and the advisor's answer
- introductions_to_you.csv: for an advisor, introductions people sent you
- sharing_with_an_advisor.csv: when you agreed to share your account with an
  advisor and when that ended, with the exact words you were shown
- advisor_visits.csv: each time an advisor opened a page in your account
- share_links.csv: the "Explain it to someone" links you made that still
  work - when you made each one, when it stops working, whether it shows your
  first name, and how many times it was opened (the links themselves are never
  kept)

Not included: your password and sign-in records, which are never stored in a
readable form, or your two-step key and backup codes. Uploaded files and screenshots were never kept, so there's
nothing to export for them.
"""


def _safe(col: str) -> bool:
    return not SECRET_PARTS & set(col.lower().split("_"))


# A spreadsheet runs a cell that starts with one of these as a formula
# (=HYPERLINK(...), +cmd|...): text someone typed - a holding's name, an
# account name, a note, a client's answer - could then do something on the
# computer of whoever opens the file (an advisor opening a client's, say).
# Text cells that start with one get an apostrophe in front, the usual way
# to keep a cell as plain text; numbers are left as they are.
FORMULA_START = ("=", "+", "-", "@", "\t", "\r", "\n", "＝", "＋", "－", "＠")


def csv_cell(value):
    """One cell for a CSV file, never read as a formula (FORMULA_START)."""
    if isinstance(value, str) and value.startswith(FORMULA_START):
        return "'" + value
    return value


def csv_bytes(frame) -> bytes:
    """A pandas DataFrame as CSV bytes for a download button, with every text
    cell made safe (csv_cell) - the Holdings, Accounts, Activity and Income
    downloads."""
    safe = frame.copy()
    for col in safe.columns:
        if safe[col].dtype == object:
            safe[col] = safe[col].map(csv_cell)
    safe.columns = [csv_cell(c) for c in safe.columns]
    return safe.to_csv(index=False).encode("utf-8")


def _csv(rows: list[dict]) -> str:
    cols = [c for c in rows[0].keys() if _safe(c)]
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(cols)
    for r in rows:
        w.writerow(["" if r[c] is None else csv_cell(r[c]) for c in cols])
    return out.getvalue()


def collect(conn, user_id: int) -> dict[str, list[dict]]:
    """{file name: rows} for every kind of data the account has."""
    found = {}
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is not None:
        row = dict(row)
        found["account"] = [{c: row.get(c) for c in ACCOUNT_COLUMNS if c in row}]
    for name, table, col, extra in OWN:
        drop = LEFT_OUT_COLUMNS.get(name, set())
        rows = [{k: v for k, v in dict(r).items() if k not in drop} for r in conn.execute(
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


# ---- an advisor's record of a client (Advisor notes / Your clients) -------- #
# Advisers keep records of their clients and what they told them for years
# (SEC Rule 204-2). This is the advisor's own copy of what they recorded in
# Northwend for a client: only their own clients (auth.can_view), only their
# own notes, proposals and reports (never another advisor's), and never a
# password, a sign-in or email-link token, or the AI guide's private memory.
RECORD_README = """{who} - client record from Northwend, exported {when} UTC by {advisor}.

One CSV file per kind of record; a file is left out when there's nothing in it.
Open them in any spreadsheet. Times are UTC.

- client.csv: who the client is, and when they agreed to Northwend's About and
  disclosures (terms_version, terms_accepted_at; terms_via says where, when it
  wasn't at sign-up) and confirmed they're 18 or older and live in the United
  States (age_confirmed_at, us_resident_at - empty if they agreed before these
  were kept on their own)
- notes.csv: your reviews, notes, next steps and messages - archived ones too
  (archived_at), private ones marked (private = 1), messages sent with Message
  clients marked (is_message = 1)
- note_history.csv: the earlier text of notes you edited, oldest first
- proposals.csv: your proposals, with the client's answer (status, responded_at) -
  archived ones too (archived_at)
- reports.csv: progress reports you sent, and when they were opened (read_at)
- consent.csv: when the client agreed to share their account with you and when
  that ended (kind grant / revoke, how), with the exact words they were shown
- profile.csv: the client's answers about their goals and risk (while they're
  your client - not once the relationship has ended)

For a former client, client.csv says when the relationship ended, who ended
it (ended_by) and what happened to their login (account: kept; setup link -
they were emailed a link to set up their own sign-in; or closed).

Only what you recorded for this client in Northwend. Keep it with your firm's
own records: Northwend isn't a record-keeping system for advisers.
"""
CLIENT_COLUMNS = ("username", "display_name", "email", "email_verified_at", "created_at",
                  "last_login_at", "terms_version", "terms_accepted_at", "terms_via",
                  "age_confirmed_at", "us_resident_at")
NOTE_COLUMNS = ("id", "kind", "note_date", "body", "private", "done", "is_message",
                "created_at", "edited_at", "archived_at")
PROPOSAL_COLUMNS = ("id", "title", "mix_json", "note", "status", "created_at", "updated_at",
                    "shared_at", "responded_at", "archived_at")
REPORT_COLUMNS = ("id", "period_label", "period_start", "period_end", "created_at", "read_at",
                  "message", "facts_json")
PROFILE_LEFT_OUT = {"ai_memory"}   # the AI guide's own notes, never shown in the app
# a former client's client.csv: who they were to the advisor when it ended
FORMER_COLUMNS = ("client_name", "email", "ended_at", "ended_by", "account")
CONSENT_COLUMNS = ("at", "kind", "scope", "how", "text_shown", "text_sha256")


def client_record(conn, advisor_id: int, client_id: int) -> dict[str, list[dict]]:
    """{file name: rows} of what `advisor_id` recorded for one of their
    clients. Raises PermissionError for anyone but this client's advisor."""
    if advisor_id == client_id or not auth.is_advisor(conn, advisor_id):
        raise PermissionError("only this client's advisor can export their record")
    former = None
    if not auth.can_view(conn, advisor_id, client_id):
        # a former client (advising.end_relationship): the advisor's own
        # records only - who they were when it ended, never their account now
        former = conn.execute(f"SELECT {', '.join(FORMER_COLUMNS)} FROM former_clients "
                              "WHERE advisor_id = ? AND client_id = ?",
                              (advisor_id, client_id)).fetchone()
        if former is None:
            raise PermissionError("only this client's advisor can export their record")
    if former is not None:
        found = {"client": [{"your_name_for_them": former["client_name"],
                             **{c: former[c] for c in FORMER_COLUMNS if c != "client_name"}}]}
    else:
        link = conn.execute("SELECT client_name, client_can_import FROM advisor_clients "
                            "WHERE advisor_id = ? AND client_id = ?",
                            (advisor_id, client_id)).fetchone()
        user = conn.execute(f"SELECT {', '.join(CLIENT_COLUMNS)} FROM users WHERE id = ?",
                            (client_id,)).fetchone()
        found = {"client": [{"your_name_for_them": link["client_name"],
                             **{c: user[c] for c in CLIENT_COLUMNS},
                             "can_import": int(bool(link["client_can_import"]))}]}
    notes = [dict(r) for r in conn.execute(
        "SELECT * FROM advisor_notes WHERE client_id = ? AND advisor_id = ? "
        "ORDER BY note_date, id", (client_id, advisor_id))]
    found["notes"] = [{c: n.get(c) for c in NOTE_COLUMNS} for n in notes]
    found["note_history"] = [
        {"note_id": n["id"], "kind": n["kind"], "note_date": n["note_date"], "version": i,
         "body": h.get("body"), "written_at": h.get("written_at"),
         "replaced_at": h.get("replaced_at")}
        for n in notes for i, h in enumerate(advising.note_history(n), start=1)]
    for file, table, cols in (("proposals", "proposals", PROPOSAL_COLUMNS),
                              ("reports", "progress_reports", REPORT_COLUMNS)):
        found[file] = [dict(r) for r in conn.execute(
            f"SELECT {', '.join(cols)} FROM {table} WHERE client_id = ? AND advisor_id = ? "
            "ORDER BY id", (client_id, advisor_id))]
    # the client's consent to share with this advisor and its end, word for
    # word (consent.py) - between the two of them only
    found["consent"] = [{c: r[c] for c in CONSENT_COLUMNS}
                        for r in reversed(consent.between(conn, client_id, advisor_id))]
    # their answers are their own: in the record only while they're a client
    found["profile"] = [] if former is not None else [
        {k: v for k, v in dict(r).items() if k not in PROFILE_LEFT_OUT}
        for r in conn.execute("SELECT * FROM investor_profiles WHERE user_id = ?", (client_id,))]
    return {k: v for k, v in found.items() if v}


def _write_record(z, conn, advisor_id: int, client_id: int, name: str, when: str,
                  folder: str = "") -> None:
    found = client_record(conn, advisor_id, client_id)   # the check, before anything's written
    advisor = auth.display_name(conn, advisor_id) or auth.get_username(conn, advisor_id) or ""
    z.writestr(f"{folder}README.txt", RECORD_README.format(who=name, when=when, advisor=advisor))
    for file, rows in found.items():
        z.writestr(f"{folder}{file}.csv", _csv(rows))


def client_record_zip(conn, advisor_id: int, client_id: int, *,
                      now: datetime | None = None) -> bytes:
    """One client's record as a ZIP: README.txt plus one CSV per kind of
    record. PermissionError if `advisor_id` isn't this client's advisor."""
    now = now or datetime.now(timezone.utc)
    name = (dict(auth.list_clients(conn, advisor_id)).get(client_id)
            or {f["client_id"]: f["client_name"] for f in advising.former_clients(
                conn, advisor_id)}.get(client_id) or f"Client {client_id}")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        _write_record(z, conn, advisor_id, client_id, name, now.strftime("%Y-%m-%d %H:%M"))
    return buf.getvalue()


def all_client_records_zip(conn, advisor_id: int, *, now: datetime | None = None) -> bytes:
    """Every client of this advisor (auth.list_clients) in one ZIP, a folder
    each. Empty for anyone who isn't an advisor."""
    now = now or datetime.now(timezone.utc)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if auth.is_advisor(conn, advisor_id):
            for client_id, name in auth.list_clients(conn, advisor_id):
                _write_record(z, conn, advisor_id, client_id, name,
                              now.strftime("%Y-%m-%d %H:%M"),
                              folder=f"{_slug(name)}-{client_id}/")
            # and former clients (advising.end_relationship): their records stay yours
            for f in advising.former_clients(conn, advisor_id):
                name = f["client_name"] or f"Client {f['client_id']}"
                _write_record(z, conn, advisor_id, f["client_id"], name,
                              now.strftime("%Y-%m-%d %H:%M"),
                              folder=f"former-{_slug(name)}-{f['client_id']}/")
    return buf.getvalue()


def _slug(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").casefold()).strip("-")[:40] or "client"


def record_file_name(client_name: str | None, now: datetime | None = None) -> str:
    """One client's record's file name - or, given None, the all-clients one."""
    day = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    if client_name is None:
        return f"northwend-client-records-{day}.zip"
    return f"northwend-client-record-{_slug(client_name)}-{day}.zip"
