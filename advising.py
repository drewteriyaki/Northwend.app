"""Advisor tools: notes and next steps per client, reviews, model portfolios,
and what makes a client need attention. Pure logic and storage, no
Streamlit.

Notes (`advisor_notes`) are written by the advisor on a client's account:
a *Review* (a meeting - the latest one is the client's last review), a
*Note*, or a *Next step* (an action item the advisor marks done). Anything
marked private is for the advisor only and never shown to the client.
Notes are archived, never deleted, and an edit keeps the earlier text (see
"a record that stays" below).

Model portfolios (`model_portfolios`) are an advisor's saved target mixes
by asset class (Stocks / Bonds / Cash / Other), applied to a client's plan
in one step.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from asset_classes import CLASSES

NOTE_KINDS = ("Review", "Note", "Next step")
REVIEW_EVERY_DAYS = 90       # a client is due for a review this long after the last one
DRIFT_ATTENTION_PTS = 5.0    # a target-mix gap past this many points needs attention
# what a model portfolio targets: asset classes, not broker types (asset_classes.py)
MODEL_ASSET_TYPES = CLASSES


def advisor_of(conn, client_id: int) -> int | None:
    """The advisor managing this account, if any."""
    row = conn.execute("SELECT advisor_id FROM advisor_clients WHERE client_id = ? "
                       "ORDER BY advisor_id LIMIT 1", (client_id,)).fetchone()
    return row["advisor_id"] if row else None


def waiting_for_client(conn, client_id: int) -> dict:
    """What their advisor has left for a client to look at, in one query:
    {"proposals": shared proposals waiting for their answer, "reports":
    progress reports not opened yet} - Home's next step (route.advisor_step)."""
    row = conn.execute(
        "SELECT (SELECT COUNT(*) FROM proposals WHERE client_id = ? AND status = 'shared' "
        "AND archived_at IS NULL) "
        "AS proposals, (SELECT COUNT(*) FROM progress_reports WHERE client_id = ? AND "
        "read_at IS NULL) AS reports", (client_id, client_id)).fetchone()
    return {"proposals": int(row["proposals"] or 0), "reports": int(row["reports"] or 0)}


def client_can_import(conn, client_id: int) -> bool:
    """Whether a managed client may import their own statements - off unless
    their advisor turned it on (advisor_clients.client_can_import)."""
    row = conn.execute("SELECT 1 FROM advisor_clients WHERE client_id = ? "
                       "AND client_can_import = 1 LIMIT 1", (client_id,)).fetchone()
    return row is not None


def clients_can_import(conn, client_ids) -> set:
    """client_can_import() for several clients in one query: the ids allowed."""
    ids = tuple(client_ids)
    if not ids:
        return set()
    return {r["client_id"] for r in conn.execute(
        "SELECT DISTINCT client_id FROM advisor_clients WHERE client_can_import = 1 AND "
        f"client_id IN ({', '.join('?' for _ in ids)})", ids)}


def set_client_can_import(conn, advisor_id: int, client_id: int, allowed: bool) -> bool:
    """Turn a client's own imports on or off. Only for the advisor's own
    clients; returns False (and changes nothing) otherwise."""
    cur = conn.execute("UPDATE advisor_clients SET client_can_import = ? "
                       "WHERE advisor_id = ? AND client_id = ?",
                       (1 if allowed else 0, advisor_id, client_id))
    conn.commit()
    return cur.rowcount > 0


# ---- notes and next steps --------------------------------------------------- #
def add_note(conn, client_id: int, advisor_id: int, kind: str, body: str, on: str,
             private: bool = False) -> None:
    if kind not in NOTE_KINDS:
        raise ValueError(f"kind must be one of {NOTE_KINDS}")
    body = (body or "").strip()
    if not body:
        raise ValueError("a note needs some text")
    conn.execute("INSERT INTO advisor_notes (client_id, advisor_id, kind, body, note_date, private) "
                 "VALUES (?, ?, ?, ?, ?, ?)",
                 (client_id, advisor_id, kind, body, on, 1 if private else 0))
    conn.commit()


def _private_sql(include_private: bool, advisor_id: int | None) -> tuple[str, tuple]:
    """Which private notes a reader sees: none for the client; for an
    advisor (`include_private`), only that advisor's own - so `advisor_id`
    is required then (a client who moved to a new advisor doesn't hand the
    old one's private notes to the new one; audit 1.2a)."""
    if not include_private:
        return " AND private = 0", ()
    if advisor_id is None:
        raise ValueError("include_private needs the advisor_id of the advisor reading")
    return " AND (private = 0 OR advisor_id = ?)", (advisor_id,)


def list_notes(conn, client_id: int, *, include_private: bool,
               archived: bool = False, advisor_id: int | None = None) -> list[dict]:
    """Newest first. `include_private` only for the advisor's own view, with
    their `advisor_id`: only their own private notes (_private_sql).
    Archived notes are left out; `archived=True` lists only those (the
    advisor's Show archived)."""
    sql = ("SELECT * FROM advisor_notes WHERE client_id = ? AND archived_at IS "
           + ("NOT NULL" if archived else "NULL"))
    extra, args = _private_sql(include_private, advisor_id)
    return [dict(r) for r in conn.execute(sql + extra + " ORDER BY note_date DESC, id DESC",
                                          (client_id, *args))]


def notes_for(conn, client_ids, *, include_private: bool,
              advisor_id: int | None = None) -> dict:
    """list_notes() for several clients in one query: {client_id: notes}."""
    ids = tuple(dict.fromkeys(client_ids))
    if not ids:
        return {}
    sql = (f"SELECT * FROM advisor_notes WHERE client_id IN ({', '.join('?' for _ in ids)}) "
           "AND archived_at IS NULL")
    extra, args = _private_sql(include_private, advisor_id)
    out = {i: [] for i in ids}
    for r in conn.execute(sql + extra + " ORDER BY client_id, note_date DESC, id DESC",
                          (*ids, *args)):
        out[r["client_id"]].append(dict(r))
    return out


MESSAGE_MAX = 2000           # characters in one message to clients
MESSAGE_REPEAT_MINUTES = 10  # the same message can't go out again this soon (a double click)


def message_clients(conn, advisor_id: int, client_ids, body: str, *, now,
                    today: date | None = None) -> dict:
    """One message from an advisor to several clients (Your clients > Message
    clients): saved as a Note each client sees on their Your advisor page,
    like any other. Only the advisor's own clients (auth.can_view); the same
    text from this advisor within MESSAGE_REPEAT_MINUTES is refused, so a
    double click or a reload can't send it twice. `now` is a UTC datetime;
    `today` the note's date (now's date if None).
    Returns {"ok", "error", "sent_to": [client ids]}."""
    import auth
    from datetime import timedelta

    body = (body or "").strip()
    if not body:
        return {"ok": False, "error": "Write a message first.", "sent_to": []}
    if len(body) > MESSAGE_MAX:
        return {"ok": False, "error": f"Keep the message under {MESSAGE_MAX} characters.",
                "sent_to": []}
    ids = [cid for cid in dict.fromkeys(client_ids)
           if cid != advisor_id and auth.can_view(conn, advisor_id, cid)]
    if not ids:
        return {"ok": False, "error": "Pick at least one client.", "sent_to": []}
    since = (now - timedelta(minutes=MESSAGE_REPEAT_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
    if conn.execute("SELECT 1 FROM advisor_notes WHERE advisor_id = ? AND body = ? AND "
                    "created_at >= ? LIMIT 1", (advisor_id, body, since)).fetchone():
        return {"ok": False, "sent_to": [],
                "error": "You sent this message a moment ago, so it wasn't sent again. "
                         "Change it if you meant to send another."}
    stamp, on = now.strftime("%Y-%m-%d %H:%M:%S"), (today or now.date()).isoformat()
    for cid in ids:
        conn.execute("INSERT INTO advisor_notes (client_id, advisor_id, kind, body, note_date, "
                     "private, created_at, is_message) VALUES (?, ?, 'Note', ?, ?, 0, ?, 1)",
                     (cid, advisor_id, body, on, stamp))
    conn.commit()
    return {"ok": True, "error": None, "sent_to": ids}


def open_next_steps(notes: list[dict]) -> list[dict]:
    return [n for n in notes if n["kind"] == "Next step" and not n["done"]]


def _mine(advisor_id: int) -> tuple[str, tuple]:
    """Only the note's own advisor changes it: the WHERE clause always needs
    `advisor_id` (the signed-in login). It's required - there is no "any
    advisor" (audit 1.2a)."""
    if advisor_id is None:
        raise ValueError("advisor_id is required: only the note's own advisor changes it")
    return " AND advisor_id = ?", (advisor_id,)


def set_done(conn, client_id: int, note_id: int, done: bool, *,
             advisor_id: int) -> bool:
    mine, args = _mine(advisor_id)
    cur = conn.execute("UPDATE advisor_notes SET done = ? WHERE id = ? AND client_id = ?" + mine,
                       (1 if done else 0, note_id, client_id, *args))
    conn.commit()
    return cur.rowcount > 0


# ---- a record that stays: archive, restore, edit ------------------------------ #
# Advisers keep client records for years (SEC Rule 204-2), so nothing an
# advisor writes is deleted from the app: Archive hides a note from both
# sides (and from the counts - last review, open next steps) but keeps it,
# Restore brings it back, and an edit keeps each earlier text in the note's
# own `history` (a JSON list, oldest first). All of it is in the advisor's
# export of the client's record (export.client_record_zip). A former client
# deleting their own account keeps them too (admin.delete_own, PLAN D7);
# deleting the client's whole account from the Admin portal still removes them.
def _stamp(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S")


def archive_note(conn, client_id: int, note_id: int, *, advisor_id: int,
                 now: datetime | None = None) -> bool:
    """Hide a note but keep it. False if it isn't this client's and that
    advisor's own, or is already archived."""
    mine, args = _mine(advisor_id)
    cur = conn.execute("UPDATE advisor_notes SET archived_at = ? WHERE id = ? AND client_id = ? "
                       "AND archived_at IS NULL" + mine, (_stamp(now), note_id, client_id, *args))
    conn.commit()
    return cur.rowcount > 0


def restore_note(conn, client_id: int, note_id: int, *, advisor_id: int) -> bool:
    """Bring an archived note back. False if it isn't this client's and
    that advisor's own."""
    mine, args = _mine(advisor_id)
    cur = conn.execute("UPDATE advisor_notes SET archived_at = NULL WHERE id = ? AND "
                       "client_id = ? AND archived_at IS NOT NULL" + mine,
                       (note_id, client_id, *args))
    conn.commit()
    return cur.rowcount > 0


def note_history(note: dict) -> list[dict]:
    """A note's earlier versions, oldest first: [{"body", "written_at",
    "replaced_at"}] (UTC). Empty for a note never edited."""
    try:
        out = json.loads(note.get("history") or "[]")
    except ValueError:
        return []
    return out if isinstance(out, list) else []


def edit_note(conn, client_id: int, note_id: int, body: str, *,
              advisor_id: int, now: datetime | None = None) -> bool:
    """Change a note's text, keeping the text it had (note_history). False
    if it isn't this client's and that advisor's own, or nothing changed. Raises ValueError for empty text."""
    body = (body or "").strip()
    if not body:
        raise ValueError("a note needs some text")
    mine, args = _mine(advisor_id)
    row = conn.execute("SELECT body, created_at, edited_at, history FROM advisor_notes "
                       "WHERE id = ? AND client_id = ?" + mine,
                       (note_id, client_id, *args)).fetchone()
    if row is None or row["body"] == body:
        return False
    stamp = _stamp(now)
    history = note_history(dict(row)) + [{"body": row["body"],
                                          "written_at": row["edited_at"] or row["created_at"],
                                          "replaced_at": stamp}]
    conn.execute("UPDATE advisor_notes SET body = ?, edited_at = ?, history = ? "
                 "WHERE id = ? AND client_id = ?" + mine,
                 (body, stamp, json.dumps(history), note_id, client_id, *args))
    conn.commit()
    return True


def last_review(conn, client_id: int) -> str | None:
    row = conn.execute("SELECT MAX(note_date) AS d FROM advisor_notes WHERE client_id = ? "
                       "AND kind = 'Review' AND archived_at IS NULL", (client_id,)).fetchone()
    return row["d"] if row else None


def last_review_in(notes: list[dict]) -> str | None:
    """last_review() from the client's notes already read (list_notes with
    include_private - a private Review counts too)."""
    return max((n["note_date"] for n in notes if n["kind"] == "Review"), default=None)


def review_status(last: str | None, today: date) -> tuple[str, int | None]:
    """('never', None), ('due', days since), or ('ok', days since)."""
    if not last:
        return "never", None
    days = (today - date.fromisoformat(str(last)[:10])).days
    return ("due" if days > REVIEW_EVERY_DAYS else "ok"), days


# ---- the weekly summary ------------------------------------------------------ #
SOON_DAYS = 14   # "coming due": a review falls due within this many days
_REVIEW_REASONS = ("Review due", "No review yet")


def week_of(today: date) -> str:
    """'2026-W40' - the summary is shown once per week (Monday to Sunday)."""
    iso = today.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def weekly_summary(rows: list[dict]) -> dict:
    """An advisor's week, from the Clients page rows ({"user_id", "name",
    "review", "review_days", "reasons"}): reviews due now (never reviewed
    first, then the most overdue), reviews falling due within SOON_DAYS
    (soonest first, with "in_days"), and clients needing a look for other
    reasons ("other": those reasons). "any" is False when there's nothing to say."""
    due = sorted((r for r in rows if r["review"] in ("never", "due")),
                 key=lambda r: (r["review"] != "never", -(r["review_days"] or 0)))
    soon = sorted(({**r, "in_days": REVIEW_EVERY_DAYS + 1 - r["review_days"]} for r in rows
                   if r["review"] == "ok" and r["review_days"] is not None
                   and r["review_days"] > REVIEW_EVERY_DAYS - SOON_DAYS),
                  key=lambda r: r["in_days"])
    attention = [{**r, "other": other} for r in rows
                 if (other := [x for x in r["reasons"] if x not in _REVIEW_REASONS])]
    # each client once, with every reason: reviews due, then coming due, then the rest
    why = {}
    for r in due:
        why[r["user_id"]] = (r, ["never reviewed" if r["review"] == "never"
                                 else f"last review {r['review_days']} days ago"])
    for r in soon:
        why[r["user_id"]] = (r, [f"review due in {r['in_days']} day"
                                 f"{'s' if r['in_days'] != 1 else ''}"])
    for r in attention:
        why.setdefault(r["user_id"], (r, []))[1].extend(r["other"])
    clients = [{**r, "why": reasons} for r, reasons in why.values()]
    review_ids = {r["user_id"] for r in due} | {r["user_id"] for r in soon}
    return {"due": due, "soon": soon, "attention": attention, "clients": clients,
            # clients to look at for reasons other than a review
            "others": [r for r in attention if r["user_id"] not in review_ids],
            "any": bool(due or soon or attention)}


# ---- ending a relationship (ROADMAP 7) --------------------------------------- #
# Either side can end it: the advisor from the client's card or Advisor notes
# page, the client from Your advisor ("Stop sharing with my advisor"). The
# client keeps their account and becomes self-directed (no advisor_clients
# row: no client mode, they manage their holdings and plan themselves). The
# advisor keeps their own notes, proposals and reports about them - nothing
# is deleted - and a former_clients row lets them still export that record
# (export.client_record). What happens to the client's login:
#   "kept"       they have signed in before: they carry on with their login
#   "setup link" never signed in but there's an email: the password is replaced
#                by a random one (so a password the advisor set no longer
#                works) and they're emailed a "choose your password" link
#   "closed"     never signed in and no email: nobody could ever open the
#                account, so it's closed - what the advisor entered for them
#                goes with it, the advisor's own records stay
ENDED_BY = ("advisor", "client")


def _client_name(conn, advisor_id: int, client_id: int) -> str | None:
    row = conn.execute("SELECT ac.client_name, u.display_name, u.username FROM advisor_clients ac "
                       "JOIN users u ON u.id = ac.client_id WHERE ac.advisor_id = ? "
                       "AND ac.client_id = ?", (advisor_id, client_id)).fetchone()
    return (row["client_name"] or row["display_name"] or row["username"]) if row else None


def ending_plan(conn, advisor_id: int, client_id: int) -> dict | None:
    """What ending this relationship would do, for the confirm step:
    {"account": "kept" / "setup link" / "closed", "email", "name" (the
    advisor's name for them)}. None if they aren't linked."""
    name = _client_name(conn, advisor_id, client_id)
    if name is None:
        return None
    row = conn.execute("SELECT email, last_login_at FROM users WHERE id = ?",
                       (client_id,)).fetchone()
    other = conn.execute("SELECT 1 FROM advisor_clients WHERE client_id = ? AND advisor_id != ? "
                         "LIMIT 1", (client_id, advisor_id)).fetchone()
    if row["last_login_at"] or other:   # another advisor still reaches the account
        account = "kept"
    else:
        account = "setup link" if row["email"] else "closed"
    return {"account": account, "email": row["email"], "name": name}


def end_relationship(conn, advisor_id: int, client_id: int, *, by: str,
                     now: datetime | None = None, text_shown: str | None = None) -> dict:
    """End the relationship between `advisor_id` and `client_id` (`by`:
    'advisor' or 'client' - who asked; the caller has checked it's one of
    them). Unlinks them, cancels any setup link the advisor made, writes a
    consent revoke ('client_stop' / 'advisor_end', with `text_shown`, the
    confirm step's words, if given), keeps the advisor's records and notes
    who the client was (former_clients), and deals with the client's login
    as ending_plan() says. Returns {"ok", "error", "account", "name",
    "client_email", "setup_token" (for the email, "setup link" only)}. Sends
    nothing: the caller emails both sides."""
    import admin
    import advisor_pack
    import auth
    import client_book
    import consent

    if by not in ENDED_BY:
        raise ValueError("ended by the advisor or the client")
    plan = ending_plan(conn, advisor_id, client_id)
    out = {"ok": False, "error": None, "account": None, "name": None, "client_email": None,
           "setup_token": None}
    if plan is None or advisor_id == client_id:
        return {**out, "error": "This relationship has already ended."}
    stamp = _stamp(now)
    try:
        conn.execute("DELETE FROM former_clients WHERE advisor_id = ? AND client_id = ?",
                     (advisor_id, client_id))
        conn.execute("INSERT INTO former_clients (advisor_id, client_id, client_name, email, "
                     "ended_at, ended_by, account) VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (advisor_id, client_id, plan["name"], plan["email"], stamp, by,
                      plan["account"]))
        # a setup link the advisor made (or holds) stops working
        conn.execute("DELETE FROM invites WHERE user_id = ?", (client_id,))
        conn.execute("DELETE FROM advisor_clients WHERE advisor_id = ? AND client_id = ?",
                     (advisor_id, client_id))
        # the record of it, in the same transaction as the unlink (consent.py)
        consent.revoke(conn, client_id, advisor_id,
                       "client_stop" if by == "client" else "advisor_end",
                       text_shown=text_shown, now=now, commit=False)
        # Bring to my advisor (advisor_pack.py): what the client chose to show
        # goes with it - the advisor keeps nothing of it live
        advisor_pack.on_unlink(conn, client_id, advisor_id,
                               "client_stop" if by == "client" else "advisor_end", now=now)
        # the Client-Owned Book (client_book.py): sharing their walks ends too
        client_book.on_unlink(conn, client_id, advisor_id,
                              "client_stop" if by == "client" else "advisor_end", now=now)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    token = None
    if plan["account"] == "setup link":
        import secrets
        # nobody has used this login: any password the advisor set stops
        # working, and the client chooses their own from the emailed link
        auth.set_password(conn, auth.get_username(conn, client_id), secrets.token_urlsafe(32))
        token = auth.setup_link(conn, client_id, now=now)["token"]
    elif plan["account"] == "closed":
        admin.delete_account(conn, client_id, by=advisor_id, keep_records_of=advisor_id)
    return {"ok": True, "error": None, "account": plan["account"], "name": plan["name"],
            "client_email": plan["email"], "setup_token": token}


def former_clients(conn, advisor_id: int) -> list[dict]:
    """This advisor's former clients, most recently ended first: {"client_id",
    "client_name", "email", "ended_at", "ended_by", "account"}."""
    return [dict(r) for r in conn.execute(
        "SELECT client_id, client_name, email, ended_at, ended_by, account FROM former_clients "
        "WHERE advisor_id = ? ORDER BY ended_at DESC, client_id DESC", (advisor_id,))]


# ---- model portfolios ------------------------------------------------------- #
def _clean_mix(mix: dict) -> dict:
    return {k: float(v) for k, v in (mix or {}).items() if v and float(v) > 0}


def list_models(conn, advisor_id: int) -> list[dict]:
    out = []
    for r in conn.execute("SELECT * FROM model_portfolios WHERE advisor_id = ? ORDER BY name",
                          (advisor_id,)):
        m = dict(r)
        try:
            m["target_alloc"] = _clean_mix(json.loads(m["target_alloc"]))
        except ValueError:
            m["target_alloc"] = {}
        out.append(m)
    return out


def save_model(conn, advisor_id: int, name: str, mix: dict) -> None:
    """Create a model, or replace the one with the same name."""
    name = (name or "").strip()
    mix = _clean_mix(mix)
    if not name:
        raise ValueError("give the model a name")
    if abs(sum(mix.values()) - 100) > 0.5:
        raise ValueError(f"the mix adds up to {sum(mix.values()):g}% - make it total 100%")
    conn.execute("DELETE FROM model_portfolios WHERE advisor_id = ? AND name = ?", (advisor_id, name))
    conn.execute("INSERT INTO model_portfolios (advisor_id, name, target_alloc) VALUES (?, ?, ?)",
                 (advisor_id, name, json.dumps(mix)))
    conn.commit()


def delete_model(conn, advisor_id: int, model_id: int) -> None:
    conn.execute("DELETE FROM model_portfolios WHERE id = ? AND advisor_id = ?", (model_id, advisor_id))
    conn.commit()


def mix_text(mix: dict) -> str:
    return " · ".join(f"{k} {v:g}%" for k, v in sorted(mix.items(), key=lambda kv: -kv[1]))


# ---- attention ------------------------------------------------------------- #
def max_drift(actual_pct: dict, targets: dict) -> float | None:
    """The largest gap, in percentage points, between the actual mix and the
    target mix (over the asset classes that have a target). None if no targets."""
    if not targets:
        return None
    return max(abs((actual_pct.get(k) or 0.0) - t) for k, t in targets.items())


INACTIVE_DAYS = 60   # a client who signs in has been away this long: worth a check-in


def attention(*, has_data: bool, goal_status: str | None, review: str, n_alerts: int,
              drift: float | None, profile_done: bool, proposal_accepted: bool = False,
              days_since_login: int | None = None) -> list[str]:
    """Why a client needs a look, most pressing first; empty when all good.
    `days_since_login` is None for a client who has never signed in (many
    are managed by the advisor alone) - only someone who used to sign in and
    stopped counts as inactive."""
    reasons = []
    if proposal_accepted:
        reasons.append("Proposal accepted")
    if not has_data:
        reasons.append("No statement yet")
    if goal_status in ("behind", "past_date"):
        reasons.append("Goal behind" if goal_status == "behind" else "Goal date passed")
    elif goal_status is None:
        reasons.append("No goal")
    if review == "never":
        reasons.append("No review yet")
    elif review == "due":
        reasons.append("Review due")
    if n_alerts:
        reasons.append(f"{n_alerts} alert{'s' if n_alerts != 1 else ''}")
    if drift is not None and drift > DRIFT_ATTENTION_PTS:
        reasons.append(f"Drift {drift:.0f} pts")
    if not profile_done:
        reasons.append("Profile incomplete")
    if days_since_login is not None and days_since_login > INACTIVE_DAYS:
        reasons.append(f"Not signed in for {days_since_login} days")
    return reasons
