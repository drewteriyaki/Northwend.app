"""Advisor proposals (ROADMAP G4): an advisor proposes a mix for a client,
compares it with today's, and shares it; the client sees it with the advisor's
note and says "let's go ahead" or "not right now".

The recommendation is the advisor's - a licensed professional advising their
own client. The app only stores it, compares the two mixes with stated,
rounded assumptions, and passes the answer back. Nothing is traded.

Statuses: draft (only the advisor sees it) -> shared -> accepted / declined.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import asset_classes
import auth
import plans

STATUSES = ("draft", "shared", "accepted", "declined")
# Long-run yearly returns assumed for each asset class - rounded, for an
# illustration, the same spirit as the plan's 6% (plans.DEFAULT_RETURN_PCT).
ASSUMED_RETURN = {"Stocks": 7.0, "Bonds": 4.0, "Cash": 3.0, "Other": 5.0}
# How broad markets did in two hard years, rounded (US and international
# stock indexes blended; the US aggregate bond index; Treasury bills; "Other"
# a rough middle for real estate and commodities).
HARD_YEARS = {
    "2008": {"Stocks": -40.0, "Bonds": 5.0, "Cash": 1.5, "Other": -25.0},
    "2022": {"Stocks": -18.0, "Bonds": -13.0, "Cash": 1.5, "Other": -10.0},
}
ASSUMPTIONS_NOTE = ("Illustration only. Assumes long-run yearly returns of about 7% for stocks, "
                    "4% for bonds, 3% for cash and 5% for other holdings; 2008 and 2022 use "
                    "rounded returns of broad market indexes. Real results differ, and fund "
                    "costs depend on the funds chosen.")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def clean_mix(mix: dict) -> dict:
    """Only the asset classes with a share, as floats; raises ValueError
    unless they add up to 100%."""
    out = {k: float(v) for k, v in (mix or {}).items()
           if k in asset_classes.CLASSES and v and float(v) > 0}
    total = sum(out.values())
    if abs(total - 100) > 0.5:
        raise ValueError(f"The mix adds up to {total:g}% - make it total 100%.")
    return out


def _row(r) -> dict:
    p = dict(r)
    try:
        p["mix"] = json.loads(p.pop("mix_json") or "{}")
    except ValueError:
        p["mix"] = {}
    return p


def save(conn, advisor_id: int, client_id: int, *, title: str, mix: dict, note: str = "",
         proposal_id: int | None = None) -> int:
    """Create a draft, or update one of this advisor's proposals for this
    client (which goes back to draft if it had been answered). The caller
    checks the advisor may view the client (auth.can_view)."""
    title = (title or "").strip() or "Proposed mix"
    mix = clean_mix(mix)
    if proposal_id is not None:
        cur = conn.execute("UPDATE proposals SET title = ?, mix_json = ?, note = ?, "
                           "status = 'draft', updated_at = ?, responded_at = NULL "
                           "WHERE id = ? AND advisor_id = ? AND client_id = ?",
                           (title[:120], json.dumps(mix), (note or "").strip()[:2000], _now(),
                            proposal_id, advisor_id, client_id))
        conn.commit()
        if not cur.rowcount:
            raise ValueError("That proposal isn't yours to change.")
        return proposal_id
    conn.execute("INSERT INTO proposals (advisor_id, client_id, title, mix_json, note, status, "
                 "created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'draft', ?, ?)",
                 (advisor_id, client_id, title[:120], json.dumps(mix), (note or "").strip()[:2000],
                  _now(), _now()))
    conn.commit()
    return conn.execute("SELECT MAX(id) AS id FROM proposals WHERE advisor_id = ? AND "
                        "client_id = ?", (advisor_id, client_id)).fetchone()["id"]


def share(conn, advisor_id: int, proposal_id: int) -> bool:
    """Share a draft. False if it isn't this advisor's or isn't a draft - so a
    double click can't email the client twice, and an answered proposal
    can't be put back to waiting (its answer is the record)."""
    cur = conn.execute("UPDATE proposals SET status = 'shared', shared_at = ?, updated_at = ? "
                       "WHERE id = ? AND advisor_id = ? AND status = 'draft'",
                       (_now(), _now(), proposal_id, advisor_id))
    conn.commit()
    return cur.rowcount > 0


def delete(conn, advisor_id: int, proposal_id: int) -> bool:
    """Delete a draft - only a draft: once shared, a proposal and the
    client's answer are part of the advisor's record (archive() instead).
    False if it isn't this advisor's draft."""
    cur = conn.execute("DELETE FROM proposals WHERE id = ? AND advisor_id = ? AND "
                       "status = 'draft'", (proposal_id, advisor_id))
    conn.commit()
    return cur.rowcount > 0


# A shared proposal is kept, like advisor notes (advising.archive_note):
# Archive hides it from both sides and Restore brings it back; it stays in
# the advisor's export of the client's record (export.client_record_zip).
def archive(conn, advisor_id: int, proposal_id: int, *, now: datetime | None = None) -> bool:
    """Hide a shared (or answered) proposal but keep it. False if it isn't
    this advisor's, is a draft (delete it instead) or is archived already."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute("UPDATE proposals SET archived_at = ? WHERE id = ? AND advisor_id = ? "
                       "AND status != 'draft' AND archived_at IS NULL",
                       (stamp, proposal_id, advisor_id))
    conn.commit()
    return cur.rowcount > 0


def restore(conn, advisor_id: int, proposal_id: int) -> bool:
    """Bring an archived proposal back. False if it isn't this advisor's."""
    cur = conn.execute("UPDATE proposals SET archived_at = NULL WHERE id = ? AND advisor_id = ? "
                       "AND archived_at IS NOT NULL", (proposal_id, advisor_id))
    conn.commit()
    return cur.rowcount > 0


def respond(conn, client_id: int, proposal_id: int, accept: bool) -> bool:
    """The client's answer to a shared proposal. False if it isn't theirs or
    isn't waiting for an answer."""
    cur = conn.execute("UPDATE proposals SET status = ?, responded_at = ? WHERE id = ? AND "
                       "client_id = ? AND status = 'shared'",
                       ("accepted" if accept else "declined", _now(), proposal_id, client_id))
    conn.commit()
    return cur.rowcount > 0


def who_to_tell(conn, user_id: int) -> dict:
    """Who to email about a proposal: {"email": an address it's fine to email
    or None, "name": what they're called, "signed_in": they've signed in at
    least once}. Only a confirmed email (a client's is confirmed once they set
    up their login), or an advisor's an admin set up (as weekly_email.py) -
    so a client who hasn't set up their login isn't sent to a dead end."""
    row = conn.execute("SELECT username, display_name, email, email_verified_at, "
                       "terms_version, terms_via, is_advisor, last_login_at FROM users "
                       "WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        return {"email": None, "name": "", "signed_in": False}
    ok = bool(row["email"]) and bool(row["email_verified_at"] or (
        row["is_advisor"] and not auth.made_by_themselves(row)))
    return {"email": row["email"] if ok else None,
            "name": row["display_name"] or row["username"],
            "signed_in": bool(row["last_login_at"])}


def get(conn, proposal_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
    return _row(row) if row else None


def open_counts(conn, client_ids) -> dict:
    """{client_id: {status: n}} of shared and accepted proposals not archived,
    one query for the whole book (clients with none are left out)."""
    ids = tuple(client_ids)
    out: dict = {}
    if not ids:
        return out
    for r in conn.execute("SELECT client_id, status, COUNT(*) AS n FROM proposals WHERE "
                          f"client_id IN ({', '.join('?' for _ in ids)}) AND status IN "
                          "('shared', 'accepted') AND archived_at IS NULL "
                          "GROUP BY client_id, status", ids):
        out.setdefault(r["client_id"], {})[r["status"]] = r["n"]
    return out


def for_client(conn, client_id: int, *, include_drafts: bool,
               archived: bool = False) -> list[dict]:
    """Newest first. A client sees only what was shared with them. Archived
    proposals are left out; `archived=True` lists only those (the advisor's
    Show archived)."""
    sql = ("SELECT * FROM proposals WHERE client_id = ? AND archived_at IS "
           + ("NOT NULL" if archived else "NULL"))
    if not include_drafts:
        sql += " AND status != 'draft'"
    return [_row(r) for r in conn.execute(sql + " ORDER BY id DESC", (client_id,))]


PDF_FOOTER = ("This proposal is your advisor's recommendation, made by them as your advisor. "
              "Northwend is the tool it was prepared in and does not give investment advice. "
              "All investing involves risk, including loss.")


def render_pdf(proposal: dict, cmp: dict, *, client_name: str, advisor_name: str,
               firm: str | None = None, goal_line: str | None = None) -> bytes:
    """A one-page PDF of a proposal: the advisor's note, today vs proposed, and
    the illustration with its assumptions. Dollar figures only when given.
    Under the title, the advisor's name and firm and their standing line
    (standing_line.py: the advice is theirs, not Northwend's)."""
    from fpdf import FPDF

    import standing_line
    from client_plan import _money0, _safe

    class _ProposalPDF(FPDF):
        def footer(self):
            self.set_y(-18)
            self.set_font("Helvetica", "I", 7)
            self.set_text_color(110)
            self.multi_cell(0, 3.5, _safe(PDF_FOOTER), align="C")
            self.set_text_color(0)

    pdf = _ProposalPDF(format="Letter")
    pdf.set_auto_page_break(auto=True, margin=22)
    pdf.set_margins(18, 16, 18)
    pdf.add_page()

    def para(text, size=9.5, style=""):
        pdf.set_font("Helvetica", style, size)
        pdf.multi_cell(0, 5, _safe(text), align="L", new_x="LMARGIN", new_y="NEXT")

    def heading(text):
        pdf.ln(3)
        para(text, 12, "B")

    def pct(v):
        return "-" if v is None else f"{v:.0f}%"

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, _safe(proposal["title"]), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(90)
    para(f"For {client_name}, from {advisor_name}" + (f", {firm}" if firm else "")
         + f"  |  {(proposal.get('shared_at') or proposal.get('updated_at') or '')[:10]}")
    para(standing_line.text(advisor_name, firm), 9, "I")
    pdf.set_text_color(0)
    if goal_line:
        para(goal_line)
    if proposal.get("note"):
        heading("Why")
        para(proposal["note"])
    heading("Today and proposed")
    pdf.set_font("Helvetica", "", 9)
    with pdf.table(col_widths=(40, 25, 25, 25), text_align=("LEFT", "RIGHT", "RIGHT", "RIGHT"),
                   line_height=5.5) as t:
        r = t.row()
        for h in ("Asset class", "Today", "Proposed", "Change"):
            r.cell(h)
        for cls, now, new, change in cmp["rows"]:
            r = t.row()
            for v in (cls, pct(now), pct(new),
                      "-" if change is None else f"{change:+.0f} pts"):
                r.cell(_safe(v))
    heading("What it could mean")
    t_ret, p_ret = cmp["assumed_return"]
    para(f"Assumed long-run return: {'-' if t_ret is None else f'{t_ret:.1f}%'} today, "
         f"{p_ret:.1f}% proposed, a year.")
    for year, (now, new) in cmp["hard_years"].items():
        para(f"In a year like {year}: about {'-' if now is None else f'{now:+.0f}%'} today, "
             f"{new:+.0f}% proposed.")
    if cmp.get("projected"):
        now, new = cmp["projected"]
        para(f"Projected at the goal date: about {_money0(now)} today, {_money0(new)} "
             "proposed.")
    pdf.ln(2)
    pdf.set_text_color(90)
    para(ASSUMPTIONS_NOTE, 8)
    pdf.set_text_color(0)
    return bytes(pdf.output())


_mix_return = asset_classes.mix_return   # (shared with stress.py, which stays pure)


def compare(today: dict, proposed: dict, *, value: float | None = None, monthly: float = 0.0,
            months: int | None = None, items=None, on=None) -> dict:
    """Today's mix next to the proposal: {"rows": [(class, today %, proposed
    %, change)], "stocks": (today, proposed), "assumed_return": (today,
    proposed), "hard_years": {year: (today %, proposed %)}, "projected":
    (today $, proposed $) at the goal date or None}. `today` may be empty (no
    holdings yet): its figures are then None. `items` (plans.list_money_out)
    and `on` (today's date): the plan's money going out, taken out on its
    dates."""
    classes = [c for c in asset_classes.CLASSES if today.get(c) or proposed.get(c)]
    rows = [(c, today.get(c), proposed.get(c, 0.0),
             (proposed.get(c, 0.0) - today[c]) if c in today else None) for c in classes]
    has_today = bool(sum(today.values()) if today else 0)
    t_ret = _mix_return(today, ASSUMED_RETURN) if has_today else None
    p_ret = _mix_return(proposed, ASSUMED_RETURN)
    hard = {y: (_mix_return(today, r) if has_today else None, _mix_return(proposed, r))
            for y, r in HARD_YEARS.items()}
    projected = None
    if value and months and months > 0:
        projected = (plans.value_at(value, monthly, t_ret, months, items, today=on)
                     if t_ret is not None else None,
                     plans.value_at(value, monthly, p_ret, months, items, today=on))
    return {"rows": rows,
            "stocks": (today.get("Stocks", 0.0) if has_today else None, proposed.get("Stocks", 0.0)),
            "assumed_return": (t_ret, p_ret), "hard_years": hard, "projected": projected}
