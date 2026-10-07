"""The Client-Owned Book (ROADMAP R16; flag `client_owned_book`, gate L2 - an
advisor's record-keeping duty is a lawyer question, docs/LEGAL_GATES.md).
Pure logic, no Streamlit; drawn by views/client_book.py inside Your clients
and the client's Your advisor page.

Four parts:
1. The client's walk in the advisor's book. A client's monthly walks are
   theirs alone (checkin.py; the Privacy Policy says so), so the advisor sees
   them only if the client chooses to: "Let my advisor see when I've done my
   monthly walk" on the client's Your advisor page records a consent grant
   (scope consent.WALK_SIGNAL, how "walk_choice") with WALK_CONSENT word for
   word; turning it off writes a revoke. Then, and only then, the advisor's
   card for that client says "Walked this month: yes / not yet" and "Last walk:
   <month>" - read from checkin.PREF_LOG (the months a walk was finished)
   only. Never the verdict, a figure, a target or anything typed.
2. Counts only: how many clients walked this month (of those who share it)
   and how many brought in holdings in the last UPDATED_DAYS days. Plain
   counts over the advisor's own links - never a list, a ranking or a sort.
3. "Client-reported, as of <date>" beside every figure the book shows that
   comes from what was brought in (value, gain, goal progress), dated by the
   client's last holdings update (snapshots.imported_at).
4. A clean exit. The client's Stop sharing (advising.end_relationship) is
   unchanged: the client keeps every row of their own (EXIT_YOU_KEEP), the
   advisor keeps their own records - former_clients, their notes (archived
   ones too), proposals, reports and the consent records (EXIT_ADVISOR_KEEPS).
   on_unlink() ends the walk sharing with any end of the link.

HOW_BOOK_WORKS is the advisor's note on the model: no custody, no
aggregation, client-reported figures, their own notes are theirs.

Every read here goes through the advisor's own links (advisor_clients WHERE
advisor_id = ?) after auth.is_advisor and advisor_agreement.tools_open - what
auth.can_view checks, once for the whole book: an id that isn't this
advisor's client is dropped, so a count never includes another advisor's
client. No new table: the choice lives in consent_records (append-only).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import checkin
import consent

FLAG = "client_owned_book"        # flags.FEATURES["client_owned_book"]
SCOPE = consent.WALK_SIGNAL       # the consent records' scope
HOW = "walk_choice"               # consent.HOWS: the client's own switch
UPDATED_DAYS = 30                 # "brought in holdings in the last 30 days"

# ---- the words ---------------------------------------------------------------- #
WALK_SHARE_LABEL = "Let my advisor see when I've done my monthly walk"
WALK_SHARE_HELP = ("Only whether you've done your monthly walk this month, and the month of "
                   "your last one - never what your plan said, your mix or any amount.")
WALK_CONSENT = ("You're choosing to let your advisor, {advisor}, see whether you've done your "
                "monthly walk this month, and the month of your last one. They won't see what "
                "your plan said, your mix, any amount or anything you typed. Turn this off at "
                "any time and they stop seeing it at once.")
WALK_SHARE_OFF = "Your monthly walks are private to you. Nothing about them is shared."
WALK_SHARE_ON = ("Your advisor sees whether you've done your monthly walk this month, and the "
                 "month of your last one - nothing else about it.")

# what each side keeps after an exit - the client's Stop sharing step
EXIT_TITLE = "What happens to your information"
EXIT_YOU_KEEP = ("You keep everything in your account: your holdings and their history, your "
                 "plan and goals, your answers, your monthly walks, your notes to your future "
                 "self and your settings. A copy of the notes, proposals and reports your "
                 "advisor shared with you stays in your data download.")
EXIT_ADVISOR_KEEPS = ("Your advisor keeps their own records: their notes about your time "
                      "together, the proposals and reports they sent, the name and email they "
                      "had for you, and the dated record of when sharing began and ended. They "
                      "no longer see your account, and they stop seeing anything you chose to "
                      "show them straight away.")

# the advisor's note on how the book works
BOOK_TITLE = "How your book works"
HOW_BOOK_WORKS = (
    "Northwend never holds money and never connects to anyone's brokerage. There are no "
    "logins to a bank or broker, no custody and no account aggregation.",
    "The holdings in your book are what you or your client brought in - a statement, "
    "pasted text, or typed by hand. They're marked client-reported, with the day of the last "
    "update. Prices come from market data; Northwend doesn't check the holdings against "
    "the brokerage.",
    "Each client's monthly walk starts with updating their holdings, so clients who do it "
    "keep your book up to date. Whether a client did their walk is shown only if they "
    "choose to share it.",
    "Your notes, proposals and reports are your own records. If a relationship ends, they "
    "stay with you under Former clients, and your client keeps their whole account.",
)


# ---- small helpers ------------------------------------------------------------ #
def as_of(day) -> str | None:
    """'Oct 3, 2026' from a date or an ISO date/time text; None if unreadable."""
    if not day:
        return None
    if not isinstance(day, date):
        try:
            day = date.fromisoformat(str(day)[:10])
        except ValueError:
            return None
    return f"{day:%b} {day.day}, {day.year}"


def reported(day) -> str:
    """The label beside a client-entered figure: 'Client-reported, as of Oct 3,
    2026' (or just 'Client-reported' without a date)."""
    when = as_of(day)
    return f"Client-reported, as of {when}" if when else "Client-reported"


def month_label(month: str | None) -> str | None:
    """'October 2026' from '2026-10'."""
    if not month or len(str(month)) < 7:
        return None
    try:
        return f"{checkin.month_name(str(month)[:7])} {str(month)[:4]}"
    except ValueError:
        return None


def walk_state(p: dict | None, today: date) -> dict:
    """{"walked": finished this month, "last": 'YYYY-MM' of the latest
    finished walk or None} - from checkin.PREF_LOG only (never verdicts)."""
    log = sorted({m for m in (p or {}).get(checkin.PREF_LOG) or []
                  if isinstance(m, str) and len(m) == 7})
    return {"walked": checkin.month_of(today) in log, "last": log[-1] if log else None}


# ---- the advisor's own links ---------------------------------------------------- #
def own_clients(conn, advisor_id: int, client_ids=None) -> set[int]:
    """This advisor's linked clients (of `client_ids`, when given) - empty for
    anyone who isn't an advisor, or whose tools aren't open (the advisor
    agreement): auth.can_view, for the whole book in one read."""
    import advisor_agreement
    import auth

    if not auth.is_advisor(conn, advisor_id) or not advisor_agreement.tools_open(conn,
                                                                                  advisor_id):
        return set()
    mine = {r["client_id"] for r in conn.execute(
        "SELECT client_id FROM advisor_clients WHERE advisor_id = ? AND client_id != ?",
        (int(advisor_id), int(advisor_id)))}
    if client_ids is not None:
        mine &= {int(c) for c in client_ids}
    return mine


def sharing_walks(conn, advisor_id: int, client_ids) -> set[int]:
    """Of these clients (already this advisor's own), the ones whose latest
    walk-sharing record with this advisor is a grant - in one read."""
    ids = tuple(sorted({int(c) for c in client_ids}))
    if not ids:
        return set()
    ph = ", ".join("?" for _ in ids)
    return {r["client_id"] for r in conn.execute(
        "SELECT c.client_id, c.kind FROM consent_records c WHERE c.advisor_id = ? "
        f"AND c.scope = ? AND c.client_id IN ({ph}) AND c.id = (SELECT MAX(m.id) FROM "
        "consent_records m WHERE m.client_id = c.client_id AND m.advisor_id = c.advisor_id "
        "AND m.scope = c.scope)", (int(advisor_id), SCOPE, *ids)) if r["kind"] == "grant"}


def last_updates(conn, client_ids) -> dict:
    """{client_id: 'YYYY-MM-DD'} - the day holdings were last brought in
    (snapshots.imported_at). Callers pass this advisor's own clients only."""
    ids = tuple(sorted({int(c) for c in client_ids}))
    if not ids:
        return {}
    ph = ", ".join("?" for _ in ids)
    return {r["user_id"]: str(r["m"])[:10] for r in conn.execute(
        f"SELECT user_id, MAX(imported_at) AS m FROM snapshots WHERE user_id IN ({ph}) "
        "GROUP BY user_id", ids) if r["m"]}


def signals(conn, advisor_id: int, client_ids, today: date, *, saved: dict | None = None,
            ) -> dict:
    """{client_id: {"walk_shared", "walked", "last_walk", "updated"}} for this
    advisor's own clients among `client_ids` (anyone else's are left out).
    "walked" / "last_walk" are None unless the client shares their walks;
    "updated" is the day of their last holdings update or None. `saved` is
    {client_id: settings} when the caller has them (prefs.load_many)."""
    mine = own_clients(conn, advisor_id, client_ids)
    if not mine:
        return {}
    shares = sharing_walks(conn, advisor_id, mine)
    if shares:
        need = [c for c in shares if saved is None or c not in saved]
        if need:
            import prefs
            saved = {**(saved or {}), **prefs.load_many(conn, need)}
    updated = last_updates(conn, mine)
    out = {}
    for cid in sorted(mine):
        walk = walk_state((saved or {}).get(cid), today) if cid in shares else None
        out[cid] = {"walk_shared": cid in shares,
                    "walked": walk["walked"] if walk else None,
                    "last_walk": walk["last"] if walk else None,
                    "updated": updated.get(cid)}
    return out


def counts(sig: dict, today: date) -> dict:
    """Counts only, over signals(): {"clients", "sharing_walks",
    "walked_this_month", "updated_recently"} - no ids, no names, no order."""
    since = today - timedelta(days=UPDATED_DAYS)

    def recent(day):
        try:
            return day is not None and date.fromisoformat(day) >= since
        except ValueError:
            return False
    rows = list(sig.values())
    return {"clients": len(rows),
            "sharing_walks": sum(1 for s in rows if s["walk_shared"]),
            "walked_this_month": sum(1 for s in rows if s["walk_shared"] and s["walked"]),
            "updated_recently": sum(1 for s in rows if recent(s["updated"]))}


def walk_line(s: dict | None) -> str | None:
    """The card's words for one client: 'Walked this month: yes · Last walk:
    October 2026', or None when they don't share their walks."""
    if not s or not s.get("walk_shared"):
        return None
    last = month_label(s.get("last_walk"))
    return (f"Walked this month: {'yes' if s.get('walked') else 'not yet'} · Last walk: "
            f"{last or 'none yet'}")


# ---- the client's choice ------------------------------------------------------ #
def advisor_for(conn, client_id: int, by: int) -> int | None:
    """The advisor a client may share their walks with: only the client
    themselves (`by` is them), and only while they have one."""
    import advising
    import auth

    if int(by) != int(client_id) or auth.is_advisor(conn, client_id):
        return None
    adv = advising.advisor_of(conn, client_id)
    return adv if adv is not None and adv != client_id else None


def consent_text(advisor: str) -> str:
    return WALK_CONSENT.format(advisor=" ".join(str(advisor or "").split()) or "your advisor")


def shares_walk(conn, client_id: int, advisor_id: int) -> bool:
    return consent.current(conn, client_id, advisor_id, SCOPE)


def set_walk_sharing(conn, client_id: int, on: bool, *, by: int, text_shown: str | None = None,
                     now: datetime | None = None) -> bool:
    """The client turns walk sharing on (a grant with the words shown) or off
    (a revoke). Returns the state now. PermissionError for anyone but the
    client with an advisor; ValueError turning it on without the words."""
    advisor_id = advisor_for(conn, client_id, by)
    if advisor_id is None:
        raise PermissionError("only a client with an advisor can share their walks")
    now_on = shares_walk(conn, client_id, advisor_id)
    if on and not now_on:
        consent.grant(conn, client_id, advisor_id, text_shown, HOW, scope=SCOPE, now=now)
    elif not on and now_on:
        consent.revoke(conn, client_id, advisor_id, HOW, scope=SCOPE, now=now)
    return shares_walk(conn, client_id, advisor_id)


def on_unlink(conn, client_id: int, advisor_id: int, how: str, *,
              now: datetime | None = None) -> None:
    """Any end of the link (advising.end_relationship, auth.unlink_client, an
    account deleted): walk sharing ends with it, so a later new link starts
    unshared. In the caller's transaction (no commit)."""
    if int(client_id) != int(advisor_id) and shares_walk(conn, client_id, advisor_id):
        consent.revoke(conn, client_id, advisor_id, how, scope=SCOPE, now=now, commit=False)


def all_text() -> str:
    """Every sentence shown, for the wording tests."""
    return " ".join((WALK_SHARE_LABEL, WALK_SHARE_HELP, WALK_CONSENT, WALK_SHARE_OFF,
                     WALK_SHARE_ON, EXIT_TITLE, EXIT_YOU_KEEP, EXIT_ADVISOR_KEEPS, BOOK_TITLE,
                     *HOW_BOOK_WORKS))
