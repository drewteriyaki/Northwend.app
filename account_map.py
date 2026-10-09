"""Account map (ROADMAP 10): an "if something happens to me" binder. Every
account the person has brought in (its name, kind, last 3 digits only, a
rough value and when it was last updated), any others they add by hand,
and what they fill in for each - who to call, a beneficiary named or not,
where the paperwork is - plus notes for family. Pure logic, no Streamlit;
the page is views/account_map.py (on the Life page; an advisor's on their own portfolio).

Private: only the person sees it and downloads its PDF. It is never
emailed, never shown to an advisor (it lives on the login's own Life page,
which an advisor has only on their own portfolio, never in a client's), and
never sent to the AI. It is in Export everything (export.OWN) and is
deleted with the account (admin.ACCOUNT_TABLES).

One table, account_map: one row per account the person filled in
(entry 'account', `account` the brought-in account's saved name - already
cut to its last 3 digits), per account added by hand (entry 'other') and
the notes for family (entry 'family', one per person).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

from accounts import mask_number

SAMPLE_SOURCE = "sample portfolio"
PCT_SOURCE = "percentages"

KINDS = ("Taxable brokerage", "Joint brokerage", "Roth IRA", "Traditional IRA",
         "Rollover IRA", "SEP or SIMPLE IRA", "401(k)", "403(b) or 457", "HSA",
         "529 college savings", "Trust", "Bank or savings", "Pension or annuity",
         "Life insurance", "Other", "Not sure")
BENEFICIARY = ("Yes", "No", "Not sure")
FIELDS = ("kind", "contact", "phone", "beneficiary", "paperwork", "notes")
LIMITS = {"label": 60, "kind": 40, "contact": 120, "phone": 40, "beneficiary": 10,
          "paperwork": 200, "notes": 600, "family": 4000}

# a guess at an account's kind from its name - only a starting point they can change
_KIND_GUESS = (
    (r"\broth\b", "Roth IRA"), (r"\brollover\b", "Rollover IRA"),
    (r"\b(sep|simple)\b", "SEP or SIMPLE IRA"), (r"\b(trad(itional)?\s+)?ira\b", "Traditional IRA"),
    (r"\b401\s?\(?k\)?", "401(k)"), (r"\b(403\s?\(?b\)?|457)", "403(b) or 457"),
    (r"\bhsa\b|health savings", "HSA"), (r"\b529\b", "529 college savings"),
    (r"\btrust\b", "Trust"), (r"\bjoint\b|\bjtwros\b", "Joint brokerage"),
    (r"\bindividual\b|\bbrokerage\b|\btaxable\b", "Taxable brokerage"),
)

# words that suggest a password or code was typed in - the page warns
_SECRET_WORDS = re.compile(r"\b(password|passwd|passcode|pass\s*word|pw|pin|login|log-in|"
                           r"username|security (question|answer)|2fa|otp|seed phrase)\b\s*"
                           r"(is|:|=|-)", re.I)


def guess_kind(name: str | None) -> str | None:
    for pat, kind in _KIND_GUESS:
        if re.search(pat, name or "", re.I):
            return kind
    return None


def last_digits(name: str | None) -> str | None:
    """The last 3 digits in an account's saved name ('Roth IRA ...641' -> '641')."""
    m = re.search(r"(\d{3})\D*$", mask_number(name) or "")
    return m.group(1) if m else None


def looks_secret(text: str | None) -> bool:
    """Whether a note seems to hold a password, PIN or login."""
    return bool(_SECRET_WORDS.search(text or ""))


def _clean(field: str, value) -> str | None:
    text = re.sub(r"[ \t]+", " ", str(value or "")).strip()
    if field == "beneficiary":
        return text if text in BENEFICIARY else None
    if field == "kind":
        return text if text in KINDS else None
    if field in ("label", "contact", "phone"):
        text = re.sub(r"\s+", " ", text)
    # (free text isn't cut like account names: a phone number would be)
    return text[:LIMITS[field]] or None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# what's been brought in
# --------------------------------------------------------------------------- #
def brought_in(conn, user_id: int) -> dict:
    """The accounts in the current holdings: {"accounts": [{"account",
    "value", "as_of", "n_holdings"}], "pretend": the example or percentages
    portfolio's source (then no accounts: they're made up)}. Values are rough:
    each holding at its latest price (else its own figure) plus cash."""
    import overview
    import metrics as M

    snap = conn.execute("SELECT MAX(snapshot_date) AS d FROM positions WHERE user_id = ?",
                        (user_id,)).fetchone()["d"]
    snap_c = conn.execute("SELECT MAX(snapshot_date) AS d FROM account_totals WHERE user_id = ?",
                          (user_id,)).fetchone()["d"]
    snap = max([d for d in (snap, snap_c) if d], default=None)
    if not snap:
        return {"accounts": [], "pretend": None}
    src = conn.execute("SELECT source_file FROM snapshots WHERE snapshot_date = ? AND user_id = ? "
                       "ORDER BY imported_at DESC LIMIT 1", (snap, user_id)).fetchone()
    src = src["source_file"] if src else None
    if src in (SAMPLE_SOURCE, PCT_SOURCE):
        return {"accounts": [], "pretend": src}
    rows = [dict(r) for r in conn.execute(
        "SELECT account, symbol, quantity, market_value FROM positions WHERE snapshot_date = ? "
        "AND user_id = ?", (snap, user_id))]
    quotes = overview.latest_quotes(conn, {r["symbol"] for r in rows})
    out: dict = {}
    for r in rows:
        a = out.setdefault(r["account"], {"account": r["account"], "value": 0.0,
                                          "as_of": str(snap)[:10], "n_holdings": 0})
        a["value"] += M.eff_mv({"pos": r, "quote": quotes.get(r["symbol"], {})}) or 0.0
        a["n_holdings"] += 1
    for r in conn.execute("SELECT account, cash_value FROM account_totals WHERE "
                          "snapshot_date = ? AND user_id = ?", (snap, user_id)):
        a = out.setdefault(r["account"], {"account": r["account"], "value": 0.0,
                                          "as_of": str(snap)[:10], "n_holdings": 0})
        a["value"] += float(r["cash_value"] or 0.0)
    for a in out.values():
        a["value"] = round(a["value"], 2)
    return {"accounts": sorted(out.values(), key=lambda a: a["account"].casefold()),
            "pretend": None}


# --------------------------------------------------------------------------- #
# read and write
# --------------------------------------------------------------------------- #
def _rows(conn, user_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM account_map WHERE user_id = ? ORDER BY entry, id", (user_id,))]


def exists(conn, user_id: int) -> bool:
    """Has this login made a map (any entry at all)?"""
    return conn.execute("SELECT 1 FROM account_map WHERE user_id = ? LIMIT 1",
                        (user_id,)).fetchone() is not None


def load(conn, user_id: int, nicknames: dict | None = None) -> dict:
    """The whole map: {"accounts": every brought-in account with what was
    filled in for it (and those filled in before that are no longer in the
    holdings: "gone"), "others": accounts added by hand, "family": the notes
    for family, "updated_at": the latest change, "made": anything filled in
    at all, "pretend"}."""
    nicknames = nicknames or {}
    have = brought_in(conn, user_id)
    saved = _rows(conn, user_id)
    by_acct = {r["account"]: r for r in saved if r["entry"] == "account"}
    accounts = []
    for a in have["accounts"]:
        s = by_acct.pop(a["account"], {})
        accounts.append({**a, "name": nicknames.get(a["account"]) or a["account"],
                         "digits": last_digits(a["account"]), "gone": False,
                         "guess": guess_kind(f"{a['account']} {nicknames.get(a['account']) or ''}"),
                         **{f: s.get(f) for f in FIELDS}, "id": s.get("id")})
    for s in by_acct.values():   # filled in, then taken out of the holdings
        accounts.append({"account": s["account"], "value": None, "as_of": None,
                         "n_holdings": 0, "name": nicknames.get(s["account"]) or s["account"],
                         "digits": last_digits(s["account"]), "gone": True, "guess": None,
                         **{f: s.get(f) for f in FIELDS}, "id": s["id"]})
    others = [{**{f: r.get(f) for f in FIELDS}, "id": r["id"], "label": r["label"],
               "digits": r["last_digits"]} for r in saved if r["entry"] == "other"]
    family = next((r["notes"] for r in saved if r["entry"] == "family"), None)
    return {"accounts": accounts, "others": others, "family": family,
            "updated_at": max((r["updated_at"] for r in saved), default=None),
            "made": bool(saved), "pretend": have["pretend"]}


def save_account(conn, user_id: int, account: str, fields: dict) -> None:
    """Save what's filled in for one brought-in account (its saved name)."""
    account = mask_number(account)
    vals = {f: _clean(f, fields.get(f)) for f in FIELDS}
    row = conn.execute("SELECT id FROM account_map WHERE user_id = ? AND entry = 'account' "
                       "AND account = ?", (user_id, account)).fetchone()
    if row:
        conn.execute(f"UPDATE account_map SET {', '.join(f'{f} = ?' for f in FIELDS)}, "
                     "updated_at = ? WHERE id = ? AND user_id = ?",
                     (*vals.values(), _now(), row["id"], user_id))
    else:
        conn.execute(f"INSERT INTO account_map (user_id, entry, account, {', '.join(FIELDS)}, "
                     f"updated_at) VALUES (?, 'account', ?, {', '.join('?' for _ in FIELDS)}, ?)",
                     (user_id, account, *vals.values(), _now()))
    conn.commit()


def save_other(conn, user_id: int, fields: dict, other_id: int | None = None) -> int | None:
    """Add (or change) an account added by hand: a name, its last digits (3
    at most), its kind and the same fields. Returns its id, None without a name."""
    label = _clean("label", fields.get("label"))
    if not label:
        return None
    digits = re.sub(r"\D", "", str(fields.get("digits") or ""))[-3:] or None
    vals = {f: _clean(f, fields.get(f)) for f in FIELDS}
    if other_id:
        conn.execute(f"UPDATE account_map SET label = ?, last_digits = ?, "
                     f"{', '.join(f'{f} = ?' for f in FIELDS)}, updated_at = ? "
                     "WHERE id = ? AND user_id = ? AND entry = 'other'",
                     (label, digits, *vals.values(), _now(), other_id, user_id))
        conn.commit()
        return other_id
    conn.execute(f"INSERT INTO account_map (user_id, entry, label, last_digits, "
                 f"{', '.join(FIELDS)}, updated_at) VALUES (?, 'other', ?, ?, "
                 f"{', '.join('?' for _ in FIELDS)}, ?)",
                 (user_id, label, digits, *vals.values(), _now()))
    new_id = conn.execute("SELECT MAX(id) AS i FROM account_map WHERE user_id = ? AND "
                          "entry = 'other'", (user_id,)).fetchone()["i"]
    conn.commit()
    return new_id


def delete_entry(conn, user_id: int, entry_id: int) -> None:
    """Remove one account added by hand, or what was filled in for one."""
    conn.execute("DELETE FROM account_map WHERE id = ? AND user_id = ?", (entry_id, user_id))
    conn.commit()


def save_family(conn, user_id: int, text: str | None) -> None:
    """The notes for family (blank clears them)."""
    text = _clean("family", text)
    conn.execute("DELETE FROM account_map WHERE user_id = ? AND entry = 'family'", (user_id,))
    if text:
        conn.execute("INSERT INTO account_map (user_id, entry, notes, updated_at) VALUES "
                     "(?, 'family', ?, ?)", (user_id, text, _now()))
    conn.commit()


def clear(conn, user_id: int) -> None:
    """Delete the whole map."""
    conn.execute("DELETE FROM account_map WHERE user_id = ?", (user_id,))
    conn.commit()


def nudge(n_accounts: int, made: bool, dismissed: bool) -> bool:
    """Home's one line: two or more accounts, no map yet, not put away."""
    return n_accounts >= 2 and not made and not dismissed


# --------------------------------------------------------------------------- #
# finding old accounts (education, with links)
# --------------------------------------------------------------------------- #
FIND_OLD = (
    ("An old 401(k) or other workplace plan",
     "Start with the former employer's HR or benefits team, or the plan's administrator named "
     "on an old statement or tax form. The US Department of Labor's Retirement Savings Lost "
     "and Found database can help you look up plans you were in.",
     (("Retirement Savings Lost and Found (US Department of Labor)",
       "https://lostandfound.dol.gov/"),)),
    ("A pension from a past job",
     "If the company or its plan has closed, the Pension Benefit Guaranty Corporation lists "
     "pensions it holds for people it couldn't find.",
     (("Search unclaimed pensions (PBGC)", "https://www.pbgc.gov/search-unclaimed-pensions"),)),
    ("Forgotten money your state is holding",
     "Forgotten bank balances, uncashed checks and dormant brokerage accounts are handed to "
     "the state after a few years. Each state has a free search - start from unclaimed.org, "
     "which links to every state's own site. Look in every state you've lived in. It never "
     "costs anything to claim.",
     (("unclaimed.org - find your state's search (NAUPA)", "https://unclaimed.org/"),)),
    ("An old brokerage account",
     "Call the firm with your name, address at the time and Social Security number, or look "
     "for an old 1099 tax form. If the firm was bought or renamed, FINRA BrokerCheck shows "
     "what became of it.",
     (("FINRA BrokerCheck", "https://brokercheck.finra.org/"),)),
    ("Paper US savings bonds",
     "TreasuryDirect's Treasury Hunt looks up matured savings bonds that haven't been cashed.",
     (("Treasury Hunt (TreasuryDirect)",
       "https://www.treasurydirect.gov/savings-bonds/treasury-hunt/"),)),
)


# --------------------------------------------------------------------------- #
# the PDF (fpdf2) - only the person downloads it
# --------------------------------------------------------------------------- #
def _latin(s) -> str:
    s = str(s if s is not None else "")
    for a, b in (("—", "-"), ("–", "-"), ("’", "'"), ("‘", "'"),
                 ("“", '"'), ("”", '"'), ("…", "...")):
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


def _day(d) -> str:
    """'Jun 1, 2026' from '2026-06-01'."""
    try:
        d = date.fromisoformat(str(d)[:10])
    except ValueError:
        return str(d or "")
    return f"{d:%b} {d.day}, {d.year}"


def _money0(v) -> str:
    return "-" if v is None else f"${v:,.0f}"


def render_pdf(m: dict, *, name: str, today: date | None = None,
               app_name: str = "Northwend") -> bytes:
    """The binder as a PDF: each account on its own block, then the notes
    for family and where to look for old accounts."""
    from fpdf import FPDF

    class _PDF(FPDF):
        def footer(self):
            self.set_y(-14)
            self.set_font("Helvetica", "I", 7)
            self.set_text_color(120)
            self.cell(0, 4, _latin(f"Private - made by {name} with {app_name}. Account numbers "
                                   f"show their last 3 digits only.   Page {self.page_no()}"),
                      align="C")
            self.set_text_color(0)

    pdf = _PDF(format="Letter")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(18, 16, 18)
    pdf.add_page()
    pdf.set_font("Times", "B", 20)
    pdf.cell(0, 10, _latin("My account map"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9.5)
    pdf.set_text_color(90)
    pdf.multi_cell(0, 5, _latin(
        f"{name}'s accounts, and what someone would need to find them. Made "
        f"{_day((today or date.today()).isoformat())}. Values are rough, "
        "as of the date shown. Keep this somewhere safe - it holds no passwords on purpose."),
        new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)

    def heading(text):
        if pdf.will_page_break(30):
            pdf.add_page()
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 7, _latin(text), new_x="LMARGIN", new_y="NEXT")

    def line(label, value):
        if not value:
            return
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(42, 5, _latin(label))
        pdf.set_font("Helvetica", "", 9.5)
        pdf.multi_cell(0, 5, _latin(value), new_x="LMARGIN", new_y="NEXT")

    def block(title, rows):
        if pdf.will_page_break(28):
            pdf.add_page()
        pdf.ln(2)
        pdf.set_draw_color(200)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(1.5)
        pdf.set_font("Helvetica", "B", 10.5)
        pdf.multi_cell(0, 6, _latin(title), new_x="LMARGIN", new_y="NEXT")
        for label, value in rows:
            line(label, value)

    accounts = [a for a in m["accounts"]]
    if accounts or m["others"]:
        heading("Accounts")
    for a in accounts:
        block(a["name"] + ("" if a["name"] == a["account"] else f"  ({a['account']})"), [
            ("Kind", a.get("kind") or (f"{a['guess']} (a guess from its name)" if a.get("guess")
                                       else "Not filled in")),
            ("Ends in", a["digits"] and f"...{a['digits']}"),
            ("Rough value", None if a["gone"] else
             f"{_money0(a['value'])} (as of {_day(a['as_of'])})"),
            ("Who to call", a.get("contact")), ("Phone", a.get("phone")),
            ("Beneficiary named", a.get("beneficiary")),
            ("Paperwork", a.get("paperwork")), ("Notes", a.get("notes")),
        ])
    for o in m["others"]:
        block(o["label"] + ("  (added by hand)"), [
            ("Kind", o.get("kind") or "Not filled in"),
            ("Ends in", o["digits"] and f"...{o['digits']}"),
            ("Who to call", o.get("contact")), ("Phone", o.get("phone")),
            ("Beneficiary named", o.get("beneficiary")),
            ("Paperwork", o.get("paperwork")), ("Notes", o.get("notes")),
        ])
    if m.get("family"):
        heading("Notes for family")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 5.2, _latin(m["family"]), new_x="LMARGIN", new_y="NEXT")
    heading("Looking for accounts that aren't listed")
    for title, text, links in FIND_OLD:
        pdf.set_font("Helvetica", "B", 9.5)
        pdf.multi_cell(0, 5, _latin(title), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 4.6, _latin(text + " " + "; ".join(f"{t}: {u}" for t, u in links)),
                       new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
    return bytes(pdf.output())


def file_name(today: date | None = None) -> str:
    return f"account-map-{(today or date.today()).isoformat()}.pdf"
