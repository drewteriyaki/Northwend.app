"""Adding clients from a file (ROADMAP 7): an advisor uploads a CSV with a
name (or household) and an email per row, sees each row's state first, then
adds the ready ones and emails them setup links in one step - through the
same add-and-invite path as Add client (dashboard._add_one_client). No
Streamlit here.

The file is read from memory and never stored. Header names are matched
loosely ("Name", "Client name", "Household", "E-mail address"...), and
"First name" / "Last name" columns are joined. A file has at most MAX_ROWS
rows.

Each row's state (review):
  ok         ready to add
  client     already one of this advisor's clients
  taken      the email already has a Northwend account - as Add client says
             when it can't make one (auth.client_checks_allowed caps how many
             new addresses a day can be checked this way)
  later      not checked: today's checks are used up - try again tomorrow
  invalid    no email, or it doesn't look like one
  duplicate  the same email as an earlier row
"""

from __future__ import annotations

import csv
import io
import re

import auth

MAX_ROWS = 200
MAX_BYTES = 500_000

STATES = {
    "ok": "Ready",
    "client": "Already your client",
    "taken": "Already has a Northwend account",
    "later": "Not checked yet",
    "invalid": "Email needs a look",
    "duplicate": "Same email as an earlier row",
}

_NAME = {"name", "fullname", "clientname", "client", "clientsname", "household",
         "householdname", "nameorhousehold", "clientorhousehold", "contact", "contactname",
         "displayname"}
_FIRST = {"firstname", "first", "givenname", "forename"}
_LAST = {"lastname", "last", "surname", "familyname"}


def _key(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (header or "").casefold())


def _columns(header: list[str]) -> dict:
    """{"name", "first", "last", "email"}: the column index of each, or None."""
    keys = [_key(h) for h in header]
    found = {"name": None, "first": None, "last": None, "email": None}
    for i, k in enumerate(keys):
        if found["email"] is None and ("email" in k or k in ("mail", "emailaddress")):
            found["email"] = i
        elif found["first"] is None and k in _FIRST:
            found["first"] = i
        elif found["last"] is None and k in _LAST:
            found["last"] = i
        elif found["name"] is None and (k in _NAME or "household" in k):
            found["name"] = i
    return found


def _text(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def parse(data: bytes) -> dict:
    """Read an uploaded file's bytes: {"ok", "error", "rows": [{"row": the
    row number as a spreadsheet shows it, "name", "email"}]}. Blank rows are
    skipped. Nothing is checked against the database here (review)."""
    def fail(msg):
        return {"ok": False, "error": msg, "rows": []}

    if not data:
        return fail("That file is empty.")
    if len(data) > MAX_BYTES:
        return fail(f"That file is too big for a list of clients - up to {MAX_ROWS} rows "
                    "of names and emails.")
    text = _text(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ","
    lines = [r for r in csv.reader(io.StringIO(text), delimiter=delimiter)]
    numbered = [(n, [c.strip() for c in r]) for n, r in enumerate(lines, start=1)
                if any(c.strip() for c in r)]
    if not numbered:
        return fail("That file is empty.")
    header_no, header = numbered[0]
    cols = _columns(header)
    body = numbered[1:]
    if cols["email"] is None:
        # no header row? a first row with an address in it is data
        at = [i for i, c in enumerate(header) if "@" in c]
        if not at:
            return fail("We couldn't find an email column. Put a header row at the top, "
                        "like: Name, Email")
        cols = {"name": next((i for i in range(len(header)) if i != at[0]), None),
                "first": None, "last": None, "email": at[0]}
        body = numbered
    if len(body) > MAX_ROWS:
        return fail(f"That file has {len(body)} rows - up to {MAX_ROWS} at a time. Split it "
                    "into smaller files.")

    def cell(r, i):
        return r[i] if i is not None and i < len(r) else ""

    rows = []
    for n, r in body:
        name = cell(r, cols["name"])
        if not name and (cols["first"] is not None or cols["last"] is not None):
            name = f"{cell(r, cols['first'])} {cell(r, cols['last'])}"
        rows.append({"row": n, "name": auth.clean_client_name(name),
                     "email": cell(r, cols["email"])})
    if not rows:
        return fail("There are no clients in that file - just the header row.")
    return {"ok": True, "error": None, "rows": rows}


def review(conn, advisor_id: int, rows: list[dict], *, now=None) -> list[dict]:
    """Each parsed row with its "state" (STATES) and "why" (a short reason;
    '' when ready), its email normalized. Looks up at most
    auth.CLIENT_CHECKS_PER_DAY new addresses a day for an existing account."""
    out, first_row = [], {}
    for r in rows:
        email = auth.normalize_email(r.get("email"))
        item = {**r, "email": email, "state": "ok", "why": ""}
        if not email:
            item.update(state="invalid", why="No email address")
        elif not auth.valid_email(email):
            item.update(state="invalid", why="Doesn't look like an email address")
        elif email in first_row:
            item.update(state="duplicate", why=f"Same as row {first_row[email]}")
        else:
            first_row[email] = r["row"]
        out.append(item)
    candidates = [r["email"] for r in out if r["state"] == "ok"]
    if not candidates:
        return out
    mine = set()
    for r in conn.execute("SELECT u.email, u.username FROM advisor_clients ac JOIN users u "
                          "ON u.id = ac.client_id WHERE ac.advisor_id = ?", (advisor_id,)):
        mine |= {(r["email"] or "").lower(), (r["username"] or "").lower()}
    for r in out:
        if r["state"] == "ok" and r["email"] in mine:
            r.update(state="client", why="Already in Your clients")
    to_check = [r["email"] for r in out if r["state"] == "ok"]
    allowed = auth.client_checks_allowed(conn, advisor_id, to_check, now=now)
    taken = set()
    for i in range(0, len(to_check), 100):   # a query per hundred, not per row
        part = [e for e in to_check[i:i + 100] if e in allowed]
        if part:
            marks = ", ".join("?" for _ in part)
            taken |= {(r["e"] or "").lower() for r in conn.execute(
                f"SELECT email AS e FROM users WHERE email IN ({marks}) UNION "
                f"SELECT lower(username) AS e FROM users WHERE lower(username) IN ({marks})",
                (*part, *part))}
    for r in out:
        if r["state"] != "ok":
            continue
        if r["email"] not in allowed:
            r.update(state="later", why=f"You've checked {auth.CLIENT_CHECKS_PER_DAY} new "
                                        "addresses today - add this one tomorrow")
        elif r["email"] in taken:
            r.update(state="taken", why="They can't be added as a new client")
    return out


def counts(reviewed: list[dict]) -> dict:
    """{state: how many rows}, every state present."""
    out = {s: 0 for s in STATES}
    for r in reviewed:
        out[r["state"]] += 1
    return out


def needs_a_look_csv(reviewed: list[dict]) -> bytes:
    """The rows that weren't ready, as a CSV to fix and upload again - every
    cell made safe for a spreadsheet (export.csv_bytes)."""
    import pandas as pd

    import export
    rows = [{"Row": r["row"], "Name": r["name"] or "", "Email": r["email"] or "",
             "Status": STATES[r["state"]], "Why": r["why"]}
            for r in reviewed if r["state"] != "ok"]
    return export.csv_bytes(pd.DataFrame(rows, columns=["Row", "Name", "Email", "Status", "Why"]))
