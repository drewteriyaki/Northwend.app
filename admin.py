"""The admin portal's data side (ROADMAP A1; the page is views/admin.py).

Admins are made only from outside the app, so nobody can grant it from
inside: the command line (manage_users.py make-admin, the users.is_admin
flag), or the NORTHWEND_ADMINS setting (the app's Secrets / environment,
which only the app's owner can change) - a list of logins. A listed login
counts only if the account was made by an admin, or its email is confirmed:
a login listed before it exists can't be claimed by signing up with it. The portal shows and changes logins
- who has an account, its role, whether its email is confirmed, locks - not
anyone's holdings or plans: the disclosures promise that only the person and
their advisor see those.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable
from datetime import datetime, timezone

import advisor_pack
import auth
import consent
import settings
import two_step

# Every table that holds one account's data, and the columns that point at an
# account. delete_account() clears all of them; a test fails when a new
# table with an account column isn't listed here.
ACCOUNT_TABLES = {
    "snapshots": ("user_id",), "positions": ("user_id",), "account_totals": ("user_id",),
    "transactions": ("user_id",), "value_log": ("user_id",), "account_labels": ("user_id",),
    "investor_profiles": ("user_id",), "watchlist": ("user_id",), "user_prefs": ("user_id",),
    "plans": ("user_id",), "contributions": ("user_id",), "login_sessions": ("user_id",),
    "ai_usage": ("user_id",), "email_tokens": ("user_id",), "advisor_requests": ("user_id",),
    "invites": ("user_id", "created_by"), "advisor_clients": ("advisor_id", "client_id"),
    "advisor_notes": ("advisor_id", "client_id"), "model_portfolios": ("advisor_id",),
    "proposals": ("advisor_id", "client_id"), "progress_reports": ("advisor_id", "client_id"),
    "two_step": ("user_id",), "money_out": ("user_id",),
    "former_clients": ("advisor_id", "client_id"),
    "future_notes": ("user_id",),   # notes to future you (future_notes.py)
    "account_map": ("user_id",),   # the account map (account_map.py)
    # the advisor agreement accepted (advisor_agreement.py) and the licence
    # checks made about an advisor (licence_check.py)
    "advisor_agreements": ("user_id",), "licence_checks": ("advisor_id",),
    "advisor_profiles": ("user_id",),   # an advisor's directory listing (directory.py)
    # an introduction from Find a guide (intros.py): gone with either account
    "intro_requests": ("person_id", "advisor_id"),
    # Explain it to someone's share links (explain_share.py): the owner's own
    "share_links": ("user_id",),
    "price_reports": ("user_id",),   # "Price look wrong?" notes (price_report.py)
    # Bring to my advisor (advisor_pack.py): what a client chose to show
    # their advisor - gone with either account
    "advisor_pack": ("user_id", "advisor_id"),
    # Doing it together (together.py): open invitations, and pairings - gone
    # with either account
    "together_invites": ("user_id",),
    "together_pairs": ("user_id", "partner_id"),
    # Invite someone (invite_links.py): the login's own link and its count -
    # the accounts made through it stay
    "invite_links": ("user_id",),
}
# Not listed: analytics_events (analytics.py) has no account column on
# purpose - its rows carry only the random id kept in the account's settings,
# so delete_account removes them by that id (analytics.on_account_deleted)
# before user_prefs goes.
# an advisor's own records about a client (advising.end_relationship keeps
# them when it closes an account nobody could open)
ADVISOR_RECORD_TABLES = ("advisor_notes", "proposals", "progress_reports", "former_clients")
# columns that only record who last changed something - cleared, not deleted
ACCOUNT_REFERENCES = {"plans": ("set_by",), "money_out": ("set_by",),
                      # who made and who used an invite code: cleared, so the
                      # code stays used (invite_codes.py)
                      "invite_codes": ("created_by", "used_by"),
                      # the admin action log (admin_log.py): the row stays,
                      # without the deleted account's id
                      "admin_log": ("admin_id", "target_id"),
                      # the admin who recorded a licence check: the check stays
                      "licence_checks": ("checked_by",)}
# Append-only records kept, ids and all, when an account is deleted (audit
# 1.6f, PLAN B6): consent to share with an advisor (consent.py) and the
# advisor access log (access_log.py). They hold ids, times and the words
# shown, never figures, and protect both the client and the advisor in a
# dispute - so they stay 7 years (their own prune, run by tidy.py), and the
# ids stay too, so a record still says who. Not cleared like
# ACCOUNT_REFERENCES, never deleted like ACCOUNT_TABLES.
KEPT_AFTER_DELETE = {"consent_records": ("client_id", "advisor_id"),
                     "advisor_access_log": ("advisor_id", "client_id")}


def listed_admins() -> set[str]:
    """Logins named in NORTHWEND_ADMINS (commas or spaces), lower-cased."""
    raw = settings.get("NORTHWEND_ADMINS").replace(",", " ")
    return {x.strip().lower() for x in raw.split() if x.strip()}


def _admin_row(row, listed: set[str]) -> bool:
    if row["is_admin"]:
        return True
    if (row["username"] or "").lower() not in listed:
        return False
    return not auth.made_by_themselves(row) or bool(row["email_verified_at"])


def is_admin(conn, user_id: int) -> bool:
    row = conn.execute("SELECT username, is_admin, terms_version, terms_via, email_verified_at "
                       "FROM users WHERE id = ?", (user_id,)).fetchone()
    return bool(row and _admin_row(row, listed_admins()))


def flagged_admins(conn) -> list[str]:
    """Logins made admins from the command line (users.is_admin), A-Z -
    NORTHWEND_ADMINS is listed_admins()."""
    return [r["username"] for r in conn.execute(
        "SELECT username FROM users WHERE is_admin = 1 ORDER BY username")]


def data_freshness(conn) -> tuple:
    """(when the newest price was fetched, the newest daily bar's date), each
    None while there are none - shared market data, the System panel."""
    last_price = conn.execute("SELECT MAX(fetched_at) AS t FROM price_history").fetchone()["t"]
    last_bar = conn.execute("SELECT MAX(date) AS d FROM daily_bars").fetchone()["d"]
    return last_price, last_bar


def set_admin(conn, username: str, flag: bool) -> bool:
    """Command line only (manage_users.py). False if no such user."""
    cur = conn.execute("UPDATE users SET is_admin = ? WHERE username = ?",
                       (1 if flag else None, username))
    conn.commit()
    return cur.rowcount > 0


DEFAULT_APP_URL = "https://go.northwend.app/"   # links in emails sent from the command line


def app_url() -> str:
    """The app's address for emails sent outside it (manage_users.py): the
    APP_URL setting, else DEFAULT_APP_URL. The Admin page passes its own."""
    import mailer
    return mailer._setting("APP_URL") or DEFAULT_APP_URL


def _advisor_email(conn, username: str) -> tuple[dict | None, str | None]:
    """(the users row, the address to write to - their email, or a login
    that is one - or None)."""
    row = conn.execute("SELECT id, username, email, is_advisor FROM users WHERE username = ?",
                       (username,)).fetchone()
    if row is None:
        return None, None
    to = row["email"] or (row["username"] if auth.valid_email(row["username"]) else None)
    return dict(row), to


def approve_advisor(conn, username: str, app_link: str | None = None, *,
                    check: dict | None = None, by: int | None = None) -> dict:
    """Make `username` an advisor (approving their request, if any) and email
    them that it's ready (mailer.advisor_approved). `check`: the license check
    the admin made - {"source", "crd", "checked_on"} (licence_check.record,
    D15), kept with `by` (the admin); a bad one raises ValueError before
    anything changes (licence_check.check_error). Returns {"ok": False if
    there's no such login, "emailed": True / False (the email failed) / None
    (no address, or they were an advisor already - nothing to say)}."""
    import licence_check
    import mailer
    if check is not None:
        error = licence_check.check_error(check.get("source"), check.get("crd"),
                                          check.get("checked_on"))
        if error:
            raise ValueError(error)
    row, to = _advisor_email(conn, username)
    if row is None:
        return {"ok": False, "emailed": None}
    if check is not None:
        licence_check.record(conn, row["id"], source=check["source"], crd=check["crd"],
                             checked_on=check["checked_on"], by=by, commit=False)
    auth.set_advisor(conn, username, True)
    if row["is_advisor"] or not to:
        return {"ok": True, "emailed": None}
    link = (app_link or app_url()).split("?")[0] + "?page=your-clients"
    return {"ok": True, "emailed": mailer.advisor_approved(to, link)}


def decline_advisor(conn, username: str, app_link: str | None = None) -> dict:
    """Turn down a waiting advisor request and tell them, politely
    (mailer.advisor_declined). Returns {"ok": False if there was no request
    waiting, "emailed": True / False / None (no address)}."""
    import mailer
    if not auth.decline_advisor(conn, username):
        return {"ok": False, "emailed": None}
    _, to = _advisor_email(conn, username)
    if not to:
        return {"ok": True, "emailed": None}
    return {"ok": True, "emailed": mailer.advisor_declined(to, (app_link or app_url()).split("?")[0])}


def list_accounts(conn, *, now: datetime | None = None) -> list[dict]:
    """Every login with what the portal shows: id, username, email,
    confirmed, role ('admin' / 'advisor' / 'client' / 'investor'), advisor
    (a client's advisor's username), clients (an advisor's count),
    ai_unlimited, signed_up (made it themselves), terms_version and
    terms_accepted_at (agreeing to the disclosures), licence_checked (the day
    of the latest recorded license check, else when an advisor request was
    approved, else None), licence_check (the latest recorded check, or None),
    licence_status (an advisor's licence_check.status, else None), agreement
    (the advisor agreement last accepted, advisor_agreement.latest_all, or
    None), created_at, last_login_at,
    locked (a wrong-password lock is running), request (an advisor request
    waiting), two_step (two-step sign-in is on - never its key)."""
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    advisor_of = {r["client_id"]: r["advisor"] for r in conn.execute(
        "SELECT ac.client_id, u.username AS advisor FROM advisor_clients ac "
        "JOIN users u ON u.id = ac.advisor_id")}
    n_clients: dict[int, int] = {}
    for r in conn.execute("SELECT advisor_id FROM advisor_clients"):
        n_clients[r["advisor_id"]] = n_clients.get(r["advisor_id"], 0) + 1
    locked = {r["username_key"] for r in conn.execute(
        "SELECT username_key FROM login_failures WHERE locked_until > ?", (stamp,))}
    waiting, checked = set(), {}
    for r in conn.execute("SELECT user_id, decision, decided_at FROM advisor_requests "
                          "WHERE decision IS NULL OR decision = 'approved'"):
        if r["decision"] is None:
            waiting.add(r["user_id"])
        else:   # approved: their firm and licence number were checked then
            checked[r["user_id"]] = r["decided_at"]
    two_step_on = {r["user_id"] for r in conn.execute("SELECT user_id FROM two_step")}
    import advisor_agreement
    import licence_check
    agreed = advisor_agreement.latest_all(conn)
    checks = licence_check.last_checks(conn)
    today = now.date()
    listed = listed_admins()
    out = []
    for r in conn.execute("SELECT id, username, email, email_verified_at, is_advisor, is_admin, "
                          "ai_unlimited, terms_version, terms_via, terms_accepted_at, "
                          "created_at, last_login_at FROM users "
                          "ORDER BY id"):
        r_admin = _admin_row(r, listed)
        role = ("admin" if r_admin else "advisor" if r["is_advisor"]
                else "client" if r["id"] in advisor_of else "investor")
        out.append({
            "id": r["id"], "username": r["username"], "email": r["email"],
            "confirmed": bool(r["email_verified_at"]) if r["email"] else None,
            "role": role, "is_advisor": bool(r["is_advisor"]), "is_admin": r_admin,
            "advisor": advisor_of.get(r["id"]), "clients": n_clients.get(r["id"], 0),
            "ai_unlimited": bool(r["ai_unlimited"]), "signed_up": auth.made_by_themselves(r),
            # when they agreed to the About and disclosures, and which version
            "terms_version": r["terms_version"], "terms_accepted_at": r["terms_accepted_at"],
            # the latest recorded check (licence_check.py), else - from before
            # checks were recorded - the day their request was approved
            "licence_checked": (checks[r["id"]]["checked_on"] if r["id"] in checks
                                else checked.get(r["id"])),
            "licence_check": checks.get(r["id"]),
            "licence_status": (licence_check.status(checks.get(r["id"]), today=today)
                               if r["is_advisor"] else None),
            # the advisor agreement they last accepted (advisor_agreement.py)
            "agreement": agreed.get(r["id"]),
            "created_at": r["created_at"], "last_login_at": r["last_login_at"],
            # wrong passwords, or wrong two-step codes (two_step.py)
            "locked": bool({auth._login_key(r["username"]), two_step._fail_key(r["id"])}
                           & locked),
            "request": r["id"] in waiting, "two_step": r["id"] in two_step_on,
        })
    return out


def create_account(conn, login: str) -> dict:
    """An account the admin makes. An email address becomes the login (as at
    sign-up), and the caller emails a link to choose a password
    (auth.setup_link); anything else is a username with a temporary password
    returned once, for the admin to pass on. Returns {"ok", "error",
    "user_id", "username", "email", "temp_password"}."""
    login = (login or "").strip()
    fail = {"ok": False, "user_id": None, "username": None, "email": None,
            "temp_password": None}
    email = auth.normalize_email(login) if "@" in login else None
    if email is not None and not auth.valid_email(email):
        return {**fail, "error": "That doesn't look like an email address."}
    if email is None and not auth.valid_username(login):
        return {**fail, "error": "Use an email address, or a username of letters, digits "
                                 "and . _ @ - (up to 50)."}
    name = email or login
    if conn.execute("SELECT 1 FROM users WHERE lower(username) = ? OR email = ?",
                    (name.lower(), name.lower())).fetchone():
        return {**fail, "error": f"There's already an account called {name}."}
    temp = secrets.token_urlsafe(9)
    user_id = auth.create_user(conn, name, temp)
    if email:
        conn.execute("UPDATE users SET email = ? WHERE id = ?", (email, user_id))
        conn.commit()
    return {"ok": True, "error": None, "user_id": user_id, "username": name, "email": email,
            "temp_password": None if email else temp}


def delete_account(conn, user_id: int, *, by: int,
                   keep_records_of: int | Iterable[int] | None = None) -> dict:
    """Delete an account and everything it holds, in one transaction. An
    advisor's clients keep their accounts (they just no longer have an
    advisor). Refuses the admin's own account and other admins. With
    `keep_records_of` (an advisor's id, or several), those advisors' own
    notes, proposals, reports and former-client rows about this account are
    kept (ADVISOR_RECORD_TABLES) - an advisor closing a client account nobody
    could open (advising.end_relationship), or a former client deleting
    their own account (delete_own, PLAN D7). Consent records and the advisor
    access log stay (KEPT_AFTER_DELETE), with a revoke added for each advisor
    link that ends here. Returns {"ok", "error", "username",
    "orphaned_clients"}."""
    if keep_records_of is None:
        keep = ()
    elif isinstance(keep_records_of, int):
        keep = (keep_records_of,)
    else:
        keep = tuple(sorted({int(a) for a in keep_records_of}))
    row = conn.execute("SELECT username, is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        return {"ok": False, "error": "No such account.", "username": None,
                "orphaned_clients": 0}
    if user_id == by or is_admin(conn, user_id):
        return {"ok": False, "error": "Admin accounts can't be deleted here - remove admin "
                "first (the command line, or NORTHWEND_ADMINS).", "username": row["username"],
                "orphaned_clients": 0}
    orphaned = conn.execute("SELECT COUNT(*) AS n FROM advisor_clients WHERE advisor_id = ?",
                            (user_id,)).fetchone()["n"]
    links = conn.execute("SELECT advisor_id, client_id FROM advisor_clients WHERE "
                         "advisor_id = ? OR client_id = ?", (user_id, user_id)).fetchall()
    import analytics
    import client_book
    import together
    with conn:
        # sharing this account was part of ends: a revoke each (consent.py),
        # in the same transaction. Consent records and access logs themselves
        # stay (KEPT_AFTER_DELETE).
        for link in links:
            consent.revoke(conn, link["client_id"], link["advisor_id"], "account_deleted",
                           commit=False)
            # and Bring to my advisor's sharing, when it was in force (advisor_pack.py)
            advisor_pack.on_unlink(conn, link["client_id"], link["advisor_id"],
                                   "account_deleted")
            # and sharing their walks (client_book.py)
            client_book.on_unlink(conn, link["client_id"], link["advisor_id"],
                                  "account_deleted")
        # doing it together ends with a revoke both ways (together.py)
        together.on_account_deleted(conn, user_id)
        # app-use events hold no user id, only the random id in the
        # settings: deleted by it here, before the settings go (analytics.py)
        analytics.on_account_deleted(conn, user_id)
        for table, cols in ACCOUNT_TABLES.items():
            where = " OR ".join(f"{c} = ?" for c in cols)
            params = (user_id,) * len(cols)
            if keep and table in ADVISOR_RECORD_TABLES:
                where = f"({where}) AND advisor_id NOT IN ({', '.join('?' * len(keep))})"
                params += keep
            conn.execute(f"DELETE FROM {table} WHERE {where}", params)
        for table, cols in ACCOUNT_REFERENCES.items():
            for c in cols:
                conn.execute(f"UPDATE {table} SET {c} = NULL WHERE {c} = ?", (user_id,))
        conn.execute("DELETE FROM login_failures WHERE username_key = ?",
                     (auth._login_key(row["username"]),))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return {"ok": True, "error": None, "username": row["username"], "orphaned_clients": orphaned}


def delete_own(conn, user_id: int, password: str) -> dict:
    """The Account page's "Delete my account": the person's own password
    first (wrong guesses count toward the lock). Not for admins, advisors
    with clients (their clients would lose their advisor - contact us), or a
    client whose advisor manages the account (ask the advisor). Returns
    {"ok", "error"}."""
    username = auth.get_username(conn, user_id)
    if username is None:
        return {"ok": False, "error": "Account not found."}
    result = auth.attempt_login(conn, username, password or "")
    if result["locked_minutes"]:
        m = result["locked_minutes"]
        return {"ok": False, "error": f"Too many wrong passwords. Try again in {m} minute"
                                      f"{'s' if m != 1 else ''}."}
    if result["user_id"] != user_id:
        return {"ok": False, "error": "Your password is wrong."}
    if is_admin(conn, user_id):
        return {"ok": False, "error": "An admin account can't be deleted here."}
    if conn.execute("SELECT 1 FROM advisor_clients WHERE advisor_id = ? LIMIT 1",
                    (user_id,)).fetchone():
        return {"ok": False, "error": "You still have clients. Contact us and we'll help them "
                                      "keep their accounts first."}
    if conn.execute("SELECT 1 FROM advisor_clients WHERE client_id = ? LIMIT 1",
                    (user_id,)).fetchone():
        return {"ok": False, "error": "Your advisor manages this account - ask them, or "
                                      "contact us."}
    # A former client (they stopped sharing, or their advisor ended it): their
    # old advisors keep their own records - notes, the proposals and reports
    # they sent, the former-client row - for their record-keeping duties;
    # everything that's the client's own goes (PLAN D7, brief 2.7)
    former = [r["advisor_id"] for r in conn.execute(
        "SELECT advisor_id FROM former_clients WHERE client_id = ?", (user_id,))]
    res = delete_account(conn, user_id, by=-1, keep_records_of=former or None)
    return {"ok": res["ok"], "error": res["error"]}
