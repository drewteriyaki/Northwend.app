"""Notes to future you (ROADMAP 8): a private note a person writes to
themselves - on a holding ("Holding this for 20 years - it's the whole
market") or on their plan ("This is for the house; don't touch it before
2030"). Pure logic and storage, no Streamlit.

One note per holding (its symbol) and one for the plan (symbol NULL), in
`future_notes`. They're the person's own: never shown to an advisor (the
views draw them only on the login's own account), never in an advisor's
client record, and never sent to the AI unless the person asks Ask
Northwend about one - and then only that note, flattened to one line, in
their own question (ask_text). A real delete: it's their note. Exported
with Export everything; deleted with the account (admin.ACCOUNT_TABLES).

The moment they're for: when markets drop, Home's storm note shows the
person their own words back (storm_picks) - calm, never alarming.

The Storm Drill (ROADMAP R4, flag storm_drill) is one more note, under the
symbol DRILL: what the person wrote on the Plan's Stress test after seeing
2008 ("What will you do when this happens?"). No suggested answers, no
right one. Same table, so the same privacy, export and delete; shown back
on the storm note (drill_quote), never among the holdings' notes.
"""

from __future__ import annotations

from datetime import datetime, timezone

MAX_CHARS = 500          # a note, not an essay
STORM_HOLDINGS = 2       # holdings' notes shown with a storm, the ones that fell most
PLAN = None              # the plan's note has no symbol
DRILL = "__STORM_DRILL__"   # the Storm Drill answer (R4) - never a real symbol
DRILL_QUESTION = "What will you do when this happens?"

PLACEHOLDER_HOLDING = "e.g. Holding this for 20 years - it's the whole market."
PLACEHOLDER_PLAN = "e.g. This is for the house; don't touch it before 2030."
PRIVATE_LINE = ("Only you can see this - not an advisor, and Ask Northwend only if you "
                "ask it about the note.")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _symbol(symbol: str | None) -> str | None:
    s = (symbol or "").strip().upper()
    return s or None


def clean(text: str | None) -> str:
    """The note as kept: trimmed, at most MAX_CHARS."""
    return (text or "").strip()[:MAX_CHARS]


def get(conn, user_id: int, symbol: str | None = PLAN) -> dict | None:
    """The note on `symbol` (None: the plan), or None."""
    sym = _symbol(symbol)
    if sym is None:
        row = conn.execute("SELECT * FROM future_notes WHERE user_id = ? AND symbol IS NULL",
                           (user_id,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM future_notes WHERE user_id = ? AND symbol = ?",
                           (user_id, sym)).fetchone()
    return dict(row) if row is not None else None


def all_notes(conn, user_id: int) -> dict:
    """{symbol or None: note} - every note this account has, in one query."""
    return {r["symbol"]: dict(r) for r in conn.execute(
        "SELECT * FROM future_notes WHERE user_id = ? ORDER BY id", (user_id,))}


def save(conn, user_id: int, symbol: str | None, text: str, *, now: str | None = None) -> bool:
    """Write (or rewrite) the note on `symbol` (None: the plan). An empty
    note deletes it. True when something was kept."""
    body = clean(text)
    sym = _symbol(symbol)
    if not body:
        delete(conn, user_id, sym)
        return False
    when = now or _now()
    have = get(conn, user_id, sym)
    if have:
        conn.execute("UPDATE future_notes SET body = ?, updated_at = ? WHERE id = ? AND "
                     "user_id = ?", (body, when, have["id"], user_id))
    else:
        conn.execute("INSERT INTO future_notes (user_id, symbol, body, created_at, updated_at) "
                     "VALUES (?, ?, ?, ?, ?)", (user_id, sym, body, when, when))
    conn.commit()
    return True


def delete(conn, user_id: int, symbol: str | None = PLAN) -> None:
    sym = _symbol(symbol)
    if sym is None:
        conn.execute("DELETE FROM future_notes WHERE user_id = ? AND symbol IS NULL", (user_id,))
    else:
        conn.execute("DELETE FROM future_notes WHERE user_id = ? AND symbol = ?",
                     (user_id, sym))
    conn.commit()


def written_on(note: dict) -> str:
    """The day the words were written: the last edit, else the first save."""
    return str(note.get("updated_at") or note.get("created_at") or "")[:10]


def quote(note: dict, fmt_date) -> str:
    """"You wrote on Mar 3, 2026: 'Holding this for 20 years.'" (plain text;
    `fmt_date` turns an ISO date into words)."""
    body = " ".join(str(note.get("body") or "").split())
    return f"You wrote on {fmt_date(written_on(note))}: “{body}”"


def drill_quote(note: dict, fmt_date) -> str:
    """The Storm Drill answer back on the storm note: "You wrote this when
    you looked at 2008 (Oct 6, 2026): '...'" (plain text)."""
    body = " ".join(str(note.get("body") or "").split())
    return (f"You wrote this when you looked at 2008 ({fmt_date(written_on(note))}): "
            f"“{body}”")


def storm_picks(notes: dict, falls: dict, held: set | None = None) -> list[dict]:
    """The notes to show beside a storm: the plan's first (it's what the
    money is for), then up to STORM_HOLDINGS holdings' notes - those that
    fell most (`falls`: {symbol: drop %, positive = down}); a holding with a
    note but no known fall comes after the ones that fell. `held`: symbols
    held now (a note on something sold isn't shown)."""
    out = []
    if notes.get(None):
        out.append(notes[None])
    syms = [s for s in notes if s is not None and s != DRILL and (held is None or s in held)]
    syms.sort(key=lambda s: (falls.get(s) is None, -(falls.get(s) or 0.0), s))
    out += [{**notes[s], "fell_pct": falls.get(s)} for s in syms[:STORM_HOLDINGS]]
    return out


def ask_text(note: dict) -> str:
    """The question Ask Northwend starts with when the person asks it about
    their note: the note as data - one line, quoted, never a section of its
    own (like advisor._data_text) - inside their own question."""
    body = " ".join(str(note.get("body") or "").split())[:MAX_CHARS].replace('"', "'")
    if note.get("symbol") == DRILL:
        return ("When I looked at how my mix would have done in 2008, I wrote down what "
                f'I\'d do if a drop like that happened: "{body}". Can you help me think '
                "about it - does it still fit my goal and timeline?")
    about = f"about {note['symbol']}" if note.get("symbol") else "about my plan"
    return (f'I wrote a note to my future self {about}: "{body}". Can you help me think '
            "about it - does it still fit my goal and timeline, and what might be worth "
            "keeping in mind when markets move?")
