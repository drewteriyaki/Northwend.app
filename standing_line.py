"""The standing line (master brief 4.4; PLAN step 5 item 10; docs/PRINCIPLES.md
principle 6): every advisor-authored thing a client sees - a proposal, a
progress report (in the app and as a PDF), the advisor's notes and messages,
and the emails saying one is waiting - carries the advisor's name and firm and
says the advice is the advisor's, not Northwend's.

STANDING_LINE is the one place the words live. They are interim wording: the
final text is the lawyer's under gate L2 (docs/LEGAL_GATES.md, "The standing
line uses interim text" while L2 is off) and replaces it here.
"""

from __future__ import annotations

STANDING_LINE = ("This is {name}'s advice, from {firm} - not Northwend's. "
                 "Northwend provides the software.")
NO_NAME = "your advisor"   # never expected: an advisor always has a login
NO_FIRM = "their firm"     # an advisor with no firm on their card or request


def text(name: str | None, firm: str | None = None) -> str:
    """The line for this advisor: their name (as they show it to clients)
    and firm."""
    name = " ".join(str(name or "").split()) or NO_NAME
    firm = " ".join(str(firm or "").split()) or NO_FIRM
    return STANDING_LINE.format(name=name, firm=firm)


def who(conn, advisor_id: int) -> dict:
    """{"name", "firm"} as the advisor's clients know them: their card (Your
    clients > How clients see you), else their login, and the firm from the
    card, else the one their advisor request named."""
    import prefs
    card = prefs.load(conn, advisor_id).get("advisor_card") or {}
    name = (card.get("name") or "").strip()
    if not name:
        row = conn.execute("SELECT username FROM users WHERE id = ?", (advisor_id,)).fetchone()
        name = row["username"] if row else ""
    firm = (card.get("firm") or "").strip()
    if not firm:
        row = conn.execute("SELECT firm FROM advisor_requests WHERE user_id = ? AND "
                           "(decision IS NULL OR decision = 'approved')",
                           (advisor_id,)).fetchone()
        firm = (row["firm"] if row else "") or ""
    return {"name": name, "firm": firm}


def for_advisor(conn, advisor_id: int) -> str:
    """text() for an advisor, from who()."""
    w = who(conn, advisor_id)
    return text(w["name"], w["firm"])
