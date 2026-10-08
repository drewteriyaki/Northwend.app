"""Consent records (PLAN step 5.6 and 5.9, master brief 4.3, audit 1.2d and
1.6f): when a client agreed to share their account with an advisor, and
when that ended - with the exact words they were shown.

One row per event in `consent_records`: the time (ISO UTC), the client, the
advisor, 'grant' or 'revoke', the scope ('full_sharing': the advisor sees
the whole account - today's `advisor_clients` link; 'advisor_pack': the
client shows them items that are otherwise only theirs, advisor_pack.py;
'walk_signal': the client lets them see whether they've walked this month,
client_book.py; 'together': one person lets a partner see three habit
facts, together.py - advisor_id is then the partner), the text shown, stored
verbatim with its SHA-256, and how it happened (HOWS).

Append-only. This module only adds rows (`grant`, `revoke`, `backfill`) and
reads them (`current`, `history`, `between`); nothing changes or deletes a
row except `prune`, the 7-year retention rule the nightly tidy job runs
(PLAN B6) - a test checks no other code does. Deleting an account keeps
these rows (admin.KEPT_AFTER_DELETE): they hold ids, times and the words
shown, never figures, and they protect both the client and the advisor in a
dispute. Postgres: the app's role can't UPDATE or DELETE them at all
(portfolio._append_only_grants, docs/DB_ROLES.md).

Today a grant is written when a client opens their advisor's setup link and
creates their login (auth.accept_invite), and a revoke when either side ends
it (advising.end_relationship: 'client_stop' / 'advisor_end'), when an admin
unlinks them ('admin'), or when either account is deleted
('account_deleted'). Links that existed before these records began got one
'migration' grant, once (backfill). The intro flow (step 5.5) calls
grant(..., how='intro') after the person's second, explicit consent.

Asked once at sign-in (PLAN step 5.7): a client whose sharing with an
advisor rests only on a 'migration' grant - or on no grant at all while
linked (an admin's link of two accounts, a client who got in with a
password the advisor set rather than the setup link) - is asked at their
next sign-in, once (`to_ask`, views/consent_ask.py): "Keep sharing" writes a
'sign_in_ask' grant with `ask_text` word for word; "Stop sharing" is the
client's own stop (advising.end_relationship). The advisor's book marks
those clients "hasn't confirmed sharing yet" (`unconfirmed`); what the
advisor sees before then is unchanged (a question for gate L2).

`current()` reads the records only. Who can see an account is still decided
by the link itself (auth.can_view, re-read on every run), so ending sharing
takes effect on the advisor's very next page load.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

KINDS = ("grant", "revoke")
SCOPES = ("full_sharing", "advisor_pack", "walk_signal", "together")
FULL_SHARING = "full_sharing"
# Bring to my advisor (advisor_pack.py): the client shows their advisor items
# that are otherwise only theirs - its own grant and revoke, beside full sharing
ADVISOR_PACK = "advisor_pack"
# The Client-Owned Book (client_book.py): the client lets their advisor see
# whether they walked this month and the month of their last walk - nothing else
WALK_SIGNAL = "walk_signal"
# Doing it together (together.py): two individuals each see three habit facts
# about the other. Not an advisor relationship: client_id is the person
# sharing, advisor_id the partner who sees it - one grant per direction
TOGETHER = "together"
# how each record came about
HOWS = (
    "setup_link",       # the client created their login from their advisor's setup link
    "intro",            # the second, explicit consent after an intro (step 5.5)
    "client_stop",      # the client's "Stop sharing with my advisor"
    "advisor_end",      # the advisor's "End relationship"
    "admin",            # an admin unlinked them (Admin portal or manage_users.py)
    "account_deleted",  # the client's or the advisor's account was deleted
    "migration",        # a link from before consent records began (backfill)
    "sign_in_ask",      # "Keep sharing" when asked once at sign-in (ask_text, to_ask)
    "pack_choice",      # the client's own ticks in Bring to my advisor (scope advisor_pack)
    "walk_choice",      # the client's own switch for sharing their walks (scope walk_signal)
    "together_invite",  # Doing it together: the inviter's yes, when they made the link
    "together_join",    # Doing it together: the invitee's yes, on the link
    "together_stop",    # Doing it together: the person who stopped sharing
    "together_ended",   # Doing it together: the other side of that stop
)
KEEP_DAYS = 2557        # 7 years (PLAN B6), counted from when the sharing ended
BACKFILL_MARK = "consent_backfill"   # app_state row: the one-time back-fill has run
MAX_TEXT = 4000

# what a 'migration' grant says, in place of words nobody recorded
MIGRATION_TEXT = ("Sharing began before Northwend kept consent records (October 2026), "
                  "so the words shown at the time weren't recorded.")


def _utc(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:      # a plain datetime is UTC already
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def text_sha256(text: str | None) -> str | None:
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text is not None else None


def setup_link_text(advisor: str) -> str:
    """The sharing sentence on an advisor's setup link page (dashboard
    _invite_setup), naming the advisor; recorded word for word with the
    grant when the client creates their login."""
    return (f"Your account is shared with your advisor, {advisor}: they can see your "
            "holdings, plan, goals and answers, and help manage them. You can stop sharing "
            "at any time from the Your advisor page, and you keep everything.")


def ask_text(advisor: str) -> str:
    """What the once-only sign-in ask shows (views/consent_ask.py), naming
    the advisor; recorded word for word with a 'sign_in_ask' grant. What the
    advisor sees and doesn't is the Privacy Policy's "Your advisor, if you
    have one, sees everything in your account except ..." (future_notes,
    the Monthly Walk, the account map, the AI guide's notes)."""
    return (f"Your account is shared with your advisor, {advisor}: they can see your "
            "holdings, plan, goals and answers, and help manage them. They don't see your "
            "notes to your future self, your monthly walks, your account map or the notes "
            "the AI guide keeps for you - those are only yours. You can stop sharing at "
            "any time from the Your advisor page, and you keep everything.\n\n"
            "Your sharing began before Northwend asked about it here, so we're asking once: "
            "would you like to keep sharing with them?")


def advisor_label(conn, advisor_id: int) -> str:
    """The advisor as their clients see them: the name and firm on their
    advisor card, else their own name, else their login."""
    import prefs
    card = prefs.load(conn, advisor_id).get("advisor_card") or {}
    row = conn.execute("SELECT username, display_name FROM users WHERE id = ?",
                       (advisor_id,)).fetchone()
    name = (card.get("name") or (row["display_name"] if row else None)
            or (row["username"] if row else None) or "your advisor")
    return name + (f", {card['firm']}" if card.get("firm") else "")


def _add(conn, client_id: int, advisor_id: int, kind: str, how: str, text: str | None,
         scope: str, now: datetime | None, commit: bool) -> None:
    if kind not in KINDS:
        raise ValueError(f"not a consent kind: {kind!r}")
    if how not in HOWS:
        raise ValueError(f"not a consent 'how': {how!r}")
    if scope not in SCOPES:
        raise ValueError(f"not a consent scope: {scope!r}")
    client_id, advisor_id = int(client_id), int(advisor_id)
    if client_id == advisor_id:
        raise ValueError("a consent record is between two different accounts")
    if text is not None:
        text = str(text)[:MAX_TEXT]
    conn.execute("INSERT INTO consent_records (at, client_id, advisor_id, kind, scope, "
                 "text_shown, text_sha256, how) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 (_utc(now), client_id, advisor_id, kind, scope, text, text_sha256(text), how))
    if commit:
        conn.commit()


def grant(conn, client_id: int, advisor_id: int, text_shown: str, how: str, *,
          scope: str = FULL_SHARING, now: datetime | None = None, commit: bool = True) -> None:
    """The client agreed to share (`scope`) with the advisor, having been
    shown `text_shown` - stored exactly as given, with its SHA-256. A grant
    needs the words: an empty text raises ValueError."""
    if not (text_shown or "").strip():
        raise ValueError("a grant records the exact text shown")
    _add(conn, client_id, advisor_id, "grant", how, text_shown, scope, now, commit)


def revoke(conn, client_id: int, advisor_id: int, how: str, *, text_shown: str | None = None,
           scope: str = FULL_SHARING, now: datetime | None = None, commit: bool = True) -> None:
    """Sharing ended (`how`: who or what ended it). `text_shown`: the words
    on the confirm step, when there was one."""
    _add(conn, client_id, advisor_id, "revoke", how, text_shown or None, scope, now, commit)


def current(conn, client_id: int, advisor_id: int, scope: str = FULL_SHARING) -> bool:
    """Whether the latest record between them, for `scope`, is a grant."""
    row = conn.execute("SELECT kind FROM consent_records WHERE client_id = ? AND advisor_id = ? "
                       "AND scope = ? ORDER BY id DESC LIMIT 1",
                       (int(client_id), int(advisor_id), scope)).fetchone()
    return bool(row and row["kind"] == "grant")


# a link whose latest record is a grant other than 'migration': the client has
# said yes in their own words (setup link, intro, the sign-in ask)
_CONFIRMED = ("EXISTS (SELECT 1 FROM consent_records c WHERE c.client_id = a.client_id "
              "AND c.advisor_id = a.advisor_id AND c.scope = 'full_sharing' "
              "AND c.kind = 'grant' AND c.how != 'migration' AND c.id = "
              "(SELECT MAX(m.id) FROM consent_records m WHERE m.client_id = a.client_id "
              "AND m.advisor_id = a.advisor_id AND m.scope = 'full_sharing'))")


def to_ask(conn, client_id: int) -> list[int]:
    """The advisors this client shares with who haven't heard a yes from them
    in their own words: linked, and the latest record between them is a
    'migration' grant, a revoke, or there's none. In one read, lowest
    advisor id first. The sign-in ask (views/consent_ask.py)."""
    return [r["advisor_id"] for r in conn.execute(
        "SELECT a.advisor_id FROM advisor_clients a WHERE a.client_id = ? "
        f"AND a.advisor_id != a.client_id AND NOT {_CONFIRMED} ORDER BY a.advisor_id",
        (int(client_id),))]


def unconfirmed(conn, advisor_id: int) -> set[int]:
    """This advisor's clients who haven't confirmed sharing yet (to_ask, the
    other way round) - for the whole book in one read (Your clients)."""
    return {r["client_id"] for r in conn.execute(
        "SELECT a.client_id FROM advisor_clients a WHERE a.advisor_id = ? "
        f"AND a.advisor_id != a.client_id AND NOT {_CONFIRMED}", (int(advisor_id),))}


_COLS = "c.id, c.at, c.client_id, c.advisor_id, c.kind, c.scope, c.text_shown, c.text_sha256, c.how"


def _rows(conn, where: str, params: tuple) -> list[dict]:
    rows = conn.execute(
        f"SELECT {_COLS}, u.display_name, u.username FROM consent_records c "
        f"LEFT JOIN users u ON u.id = c.advisor_id WHERE {where} ORDER BY c.id DESC",
        params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        name, login = d.pop("display_name"), d.pop("username")
        d["advisor"] = name or login   # their name now; None once their account is gone
        out.append(d)
    return out


def history(conn, client_id: int) -> list[dict]:
    """Every record about this client, newest first: {"id", "at",
    "client_id", "advisor_id", "kind", "scope", "text_shown", "text_sha256",
    "how", "advisor" (their name, or None if that account is gone)}. The
    client's own: their Account page and their export."""
    return _rows(conn, "c.client_id = ?", (int(client_id),))


def between(conn, client_id: int, advisor_id: int) -> list[dict]:
    """The records between one client and one advisor, newest first - an
    advisor's own record of a client (export.client_record) never shows
    another advisor's."""
    return _rows(conn, "c.client_id = ? AND c.advisor_id = ?", (int(client_id), int(advisor_id)))


def backfill(conn, *, now: datetime | None = None) -> int:
    """Once per database: a 'migration' grant for every advisor-client link
    that has no consent record, so each relationship from before these
    records has a start. Marked done in app_state (BACKFILL_MARK) - links
    made afterwards get their own grant (or none, until the client accepts
    their setup link). Returns how many were written; the caller commits."""
    if conn.execute("SELECT 1 FROM app_state WHERE name = ?", (BACKFILL_MARK,)).fetchall():
        return 0
    links = conn.execute(
        "SELECT a.client_id, a.advisor_id FROM advisor_clients a WHERE NOT EXISTS "
        "(SELECT 1 FROM consent_records c WHERE c.client_id = a.client_id "
        "AND c.advisor_id = a.advisor_id) ORDER BY a.advisor_id, a.client_id").fetchall()
    for r in links:
        if r["client_id"] != r["advisor_id"]:
            _add(conn, r["client_id"], r["advisor_id"], "grant", "migration", MIGRATION_TEXT,
                 FULL_SHARING, now, False)
    conn.execute("INSERT INTO app_state (name, number) VALUES (?, 1) "
                 "ON CONFLICT (name) DO NOTHING", (BACKFILL_MARK,))
    return len(links)


def prune(conn, older_than_days: int = KEEP_DAYS, *, now: datetime | None = None) -> int:
    """The retention rule (PLAN B6): a client and advisor's records go 7
    years after their sharing ended - when their latest record is a revoke
    older than that. Sharing still in force keeps every record. The only
    code that removes a row; the nightly tidy job runs it. Returns how many
    went."""
    cutoff = _utc((now or datetime.now(timezone.utc)) - timedelta(days=older_than_days))
    cur = conn.execute(
        "DELETE FROM consent_records WHERE EXISTS (SELECT 1 FROM consent_records n "
        "WHERE n.client_id = consent_records.client_id "
        "AND n.advisor_id = consent_records.advisor_id AND n.scope = consent_records.scope "
        "AND n.kind = 'revoke' AND n.at < ? AND n.id = (SELECT MAX(m.id) FROM consent_records m "
        "WHERE m.client_id = n.client_id AND m.advisor_id = n.advisor_id "
        "AND m.scope = n.scope))", (cutoff,))
    conn.commit()
    return max(cur.rowcount or 0, 0)
