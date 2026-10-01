"""The admin portal's data side (ROADMAP A1; the page is views/admin.py).

Admins are made only from the command line (manage_users.py make-admin), so
nobody can grant it from inside the app. The portal shows and changes logins
- who has an account, its role, whether its email is confirmed, locks - not
anyone's holdings or plans: the disclosures promise that only the person and
their advisor see those.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

import auth

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
}
# columns that only record who last changed something - cleared, not deleted
ACCOUNT_REFERENCES = {"plans": ("set_by",)}


def is_admin(conn, user_id: int) -> bool:
    row = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
    return bool(row and row["is_admin"])


def set_admin(conn, username: str, flag: bool) -> bool:
    """Command line only (manage_users.py). False if no such user."""
    cur = conn.execute("UPDATE users SET is_admin = ? WHERE username = ?",
                       (1 if flag else None, username))
    conn.commit()
    return cur.rowcount > 0


def list_accounts(conn, *, now: datetime | None = None) -> list[dict]:
    """Every login with what the portal shows: id, username, email,
    confirmed, role ('admin' / 'advisor' / 'client' / 'investor'), advisor
    (a client's advisor's username), clients (an advisor's count),
    ai_unlimited, signed_up (made it themselves), created_at, last_login_at,
    locked (a wrong-password lock is running), request (an advisor request
    waiting)."""
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
    waiting = {r["user_id"] for r in conn.execute(
        "SELECT user_id FROM advisor_requests WHERE decision IS NULL")}
    out = []
    for r in conn.execute("SELECT id, username, email, email_verified_at, is_advisor, is_admin, "
                          "ai_unlimited, terms_version, created_at, last_login_at FROM users "
                          "ORDER BY id"):
        role = ("admin" if r["is_admin"] else "advisor" if r["is_advisor"]
                else "client" if r["id"] in advisor_of else "investor")
        out.append({
            "id": r["id"], "username": r["username"], "email": r["email"],
            "confirmed": bool(r["email_verified_at"]) if r["email"] else None,
            "role": role, "is_advisor": bool(r["is_advisor"]), "is_admin": bool(r["is_admin"]),
            "advisor": advisor_of.get(r["id"]), "clients": n_clients.get(r["id"], 0),
            "ai_unlimited": bool(r["ai_unlimited"]), "signed_up": bool(r["terms_version"]),
            "created_at": r["created_at"], "last_login_at": r["last_login_at"],
            "locked": auth._login_key(r["username"]) in locked,
            "request": r["id"] in waiting,
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


def delete_account(conn, user_id: int, *, by: int) -> dict:
    """Delete an account and everything it holds, in one transaction. An
    advisor's clients keep their accounts (they just no longer have an
    advisor). Refuses the admin's own account and other admins. Returns
    {"ok", "error", "username", "orphaned_clients"}."""
    row = conn.execute("SELECT username, is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        return {"ok": False, "error": "No such account.", "username": None,
                "orphaned_clients": 0}
    if user_id == by or row["is_admin"]:
        return {"ok": False, "error": "Admin accounts can't be deleted here - remove admin "
                "first, from the command line.", "username": row["username"],
                "orphaned_clients": 0}
    orphaned = conn.execute("SELECT COUNT(*) AS n FROM advisor_clients WHERE advisor_id = ?",
                            (user_id,)).fetchone()["n"]
    with conn:
        for table, cols in ACCOUNT_TABLES.items():
            where = " OR ".join(f"{c} = ?" for c in cols)
            conn.execute(f"DELETE FROM {table} WHERE {where}", (user_id,) * len(cols))
        for table, cols in ACCOUNT_REFERENCES.items():
            for c in cols:
                conn.execute(f"UPDATE {table} SET {c} = NULL WHERE {c} = ?", (user_id,))
        conn.execute("DELETE FROM login_failures WHERE username_key = ?",
                     (auth._login_key(row["username"]),))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    return {"ok": True, "error": None, "username": row["username"], "orphaned_clients": orphaned}
