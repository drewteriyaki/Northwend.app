"""Bring to my advisor (ROADMAP "Bring to my advisor", Phase C2; flag
`advisor_pack`): a client who has an advisor chooses, item by item, things
that are otherwise only theirs to show that advisor before a review - and
the advisor sees only those, dated and marked as the client's own.

What can go in (each unticked until the client ticks it):
- ONE_PAGER: their plan in plain words - explain_share.page's figure-free
  content (mix and target in whole percents, the goal's kind and a timeline
  bucket, where they are on the route), never a link;
- "fork:<key>": a Trail Fork they've marked as theirs - the fork's name
  only, never which steps they ticked (trail_forks.py; life events are
  sensitive);
- READINESS: the readiness map - which drills are rehearsed or not, never
  what they tapped (drills.py);
- STORM_NOTE: their Storm Drill answer, in their own words (future_notes
  DRILL - the same words as a Sealed Envelope), opted in on its own;
- PLACES: the "places I've looked" statuses from Lost & Found (lost_found.py);
- "q:<key>": questions they'd like to ask, picked from QUESTIONS - a fixed
  list, nothing typed.

Consent: the first tick shows CONSENT (naming the advisor) and a "yes"
records consent.grant(..., scope="advisor_pack", how="pack_choice") with
those words verbatim and their SHA-256. Later ticks and unticks change
what's shown at once; unticking the last item records a revoke. When the
relationship ends (advising.end_relationship, auth.unlink_client, an
account deleted - on_unlink) the rows go and a revoke is written with the
same 'how' as the end of full sharing.

Records: the advisor keeps nothing live. They see the items as they are
when they look, each with the day it was shared; after an exit nothing of
the pack stays with them except the dated consent records (their client
record's consent.csv) and whatever they wrote themselves (their notes).
Whether an advisor must keep a copy of what they reviewed (books and
records) is a question for the lawyer (docs/LEGAL_GATES.md).

One table, advisor_pack: one row per ticked item - a fixed key and the day,
never free text. Every read filters user_id; an advisor reads only through
for_advisor (auth.can_view, their own link, consent in force). Deleted with
either account (admin.ACCOUNT_TABLES); in the client's own export
(export.OWN). Never sent to the AI (meeting prep's talking points read
meeting.facts_for_ai only).
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import consent
import drills
import lost_found
import trail_forks

FLAG = "advisor_pack"            # flags.FEATURES["advisor_pack"]
SCOPE = consent.ADVISOR_PACK      # the consent records' scope
HOW = "pack_choice"               # consent.HOWS: the client's own ticks here
ACCESS_PAGE = "advisor_pack"      # access_log page for each time an advisor opens it

ONE_PAGER, READINESS, STORM_NOTE, PLACES = "one_pager", "readiness", "storm_note", "places"
FORK, QUESTION = "fork:", "q:"
# the features each kind of item comes from (flags.FEATURES): an item whose
# feature is off is neither offered nor shown
SOURCES = {READINESS: "drills", STORM_NOTE: "storm_drill", PLACES: "lost_found",
           FORK: "trail_forks"}

# ---- the words ---------------------------------------------------------------- #
TITLE = "Bring to my advisor"
INTRO = ("Your advisor can already see your account. A few things in Northwend are private "
         "to you - the life events you've marked in Trail Forks, your practice drills, your "
         "Storm Drill answer, and the places you've looked for forgotten money. If you'd like "
         "your advisor to see any of these before a meeting, tick them here. Nothing is "
         "ticked to start with, and if you untick something they stop seeing it straight "
         "away.")
QUESTIONS_LEAD = "Questions I'd like to ask"
QUESTIONS_NOTE = ("The questions are a fixed list, so there's nothing to type - pick any you'd "
                  "like to talk about.")
NOT_YET = "Nothing is shared until you tick something and say yes."
CONSENT = ("You're choosing to show your advisor, {advisor}, the things you tick in Bring to "
           "my advisor. They can already see your account, but not these things. They'll see "
           "only what you tick, as it is when they look, with the day you shared each one and "
           "a note that you shared it. If you untick something, they stop seeing it straight "
           "away. If you untick everything, this sharing ends. Anything they write down from "
           "it stays in their own records.")
CONFIRM = "Yes, share what I ticked"
STOP = "Stop sharing all of these"
STOPPED = "Done - your advisor no longer sees any of these."
SHARED_ON = "Shared on {date}"
NOT_ALLOWED = ("Bring to my advisor is for a client signed in to their own account.")

ADVISOR_TITLE = "What {client} chose to bring"
ADVISOR_INTRO = ("Things {client} chose to show you from the parts of Northwend that are "
                 "otherwise private to them. Each time you open this, it's added to the list "
                 "of your visits that they can see.")
ADVISOR_OPEN = "Open"
ADVISOR_CLOSE = "Close"
NOTHING_SHARED = "{client} hasn't chosen to share anything here."
SHARED_BY = "Shared by {client} on {date}; client-reported."
ADVISOR_FOOT = ("This is {client}'s own information, as they reported it - Northwend hasn't "
                "checked it. You don't keep a copy: if they untick something, or you stop "
                "working together, it disappears from this card.")

# the client's checkbox label, and the advisor's heading, per kind
LABELS = {
    ONE_PAGER: ("My plan in plain words - percentages and words, no amounts",
                "Their plan in plain words"),
    READINESS: ("My readiness map - which practice drills I've done, never my answers",
                "Their readiness map (practice drills done)"),
    STORM_NOTE: ("My Storm Drill answer - what I wrote I'd do if the market fell",
                 "Their Storm Drill answer, in their own words"),
    PLACES: ("The places I've looked for forgotten money (Lost & Found)",
             "Places they've looked for forgotten money"),
    FORK: ("A life event I've marked in Trail Forks: {fork}",
           "A life event they've marked in Trail Forks"),
}
STORM_WRITTEN = "Written on {date}."

QUESTIONS = (
    ("fees", "What do I pay each year, all told, and what is each part for?"),
    ("fit", "How does my mix fit when I'll need the money?"),
    ("drop", "What would we do together if markets fell sharply?"),
    ("accounts", "Which kinds of accounts am I using, and what is each one for?"),
    ("taxes", "Where do taxes come into my plan?"),
    ("income", "When the time comes, how would I take money out?"),
    ("change", "What would make us change the plan, and how would I know?"),
    ("checkin", "How and when do we check in with each other?"),
    ("paid", "How are you paid, and does anything you earn depend on what I choose?"),
)
QUESTION_WORDS = dict(QUESTIONS)
QUESTIONS_ADVISOR = "Questions they'd like to ask"

# ---- the advisor's seasonal note (R7's advisor side) ---------------------- #
SEASON_TITLE = "This season for your clients"
SEASON_TOPICS = {
    "january": "Clients who use Northwend see this year's contribution limits, last year's "
               "IRA window, and what their funds' fees add up to.",
    "april": "Clients see what each tax form from a brokerage, an employer or a plan is "
             "for, in plain words.",
    "enrollment": "Clients see a guide to open enrollment and how a health savings account "
                  "works.",
    "december": "Clients see their year in review, a letter to their future self and a few "
                "year-end reminders.",
}
SEASON_NOTE = ("This is so you know what your clients are reading. It's general education, "
               "the same for everyone - nothing here asks you to contact them.")


# ---- keys ----------------------------------------------------------------- #
def valid(item) -> bool:
    """A key the table may hold: a known kind, fork or question."""
    if not isinstance(item, str):
        return False
    if item in (ONE_PAGER, READINESS, STORM_NOTE, PLACES):
        return True
    if item.startswith(FORK):
        return item[len(FORK):] in trail_forks.BY_KEY
    if item.startswith(QUESTION):
        return item[len(QUESTION):] in QUESTION_WORDS
    return False


def kind(item: str) -> str:
    return FORK if item.startswith(FORK) else QUESTION if item.startswith(QUESTION) else item


def feature_ok(item: str, features) -> bool:
    """Whether the feature the item comes from is on (`features`: the names
    on, or None for all)."""
    need = SOURCES.get(kind(item))
    return features is None or need is None or need in features


def label(item: str) -> str:
    """The client's checkbox words for an item."""
    k = kind(item)
    if k == FORK:
        return LABELS[FORK][0].format(fork=trail_forks.BY_KEY[item[len(FORK):]]["title"])
    if k == QUESTION:
        return QUESTION_WORDS[item[len(QUESTION):]]
    return LABELS[k][0]


def offered(prefs_data: dict | None, *, has_storm_note: bool, features=None,
            ticked=()) -> list[str]:
    """The items this client can tick, in order: their plan, the forks
    they've marked, the readiness map, the storm note (only when they've
    written one), the places they've looked (only when they've marked one),
    then the questions - plus anything already ticked, so it can be
    unticked. Pure."""
    p = prefs_data or {}
    ticked = {t for t in ticked if valid(t)}
    out = [ONE_PAGER]
    out += [FORK + f for f in trail_forks.mine(p.get(trail_forks.PREF))]
    out += [FORK + f for f in trail_forks.FORK_KEYS
            if FORK + f in ticked and FORK + f not in out]
    out.append(READINESS)
    if has_storm_note or STORM_NOTE in ticked:
        out.append(STORM_NOTE)
    if lost_found.clean_saved(p.get(lost_found.PREF))["places"] or PLACES in ticked:
        out.append(PLACES)
    out += [QUESTION + q for q, _ in QUESTIONS]
    return [i for i in out if feature_ok(i, features)]


def features_now() -> set[str]:
    """The source features on right now (flags.on)."""
    import flags
    return {f for f in SOURCES.values() if flags.on(f)}


# ---- who ------------------------------------------------------------------- #
def _today(today: date | None) -> str:
    return (today or datetime.now(timezone.utc).date()).isoformat()


def advisor_for(conn, client_id: int, by: int) -> int | None:
    """The advisor this client may bring things to, or None: only the client
    signed in as themselves (`by` == `client_id`), never an advisor's or an
    admin's login, and only while they have an advisor."""
    import admin
    import advising
    import auth
    if by != client_id:
        return None
    if auth.is_advisor(conn, client_id) or admin.is_admin(conn, client_id):
        return None
    return advising.advisor_of(conn, client_id)


def shared(conn, client_id: int, advisor_id: int) -> dict:
    """{item: 'YYYY-MM-DD' shared on} - what this client shows this advisor
    (the client's own read)."""
    return {r["item"]: r["shared_on"] for r in conn.execute(
        "SELECT item, shared_on FROM advisor_pack WHERE user_id = ? AND advisor_id = ? "
        "ORDER BY id", (int(client_id), int(advisor_id))) if valid(r["item"])}


def consented(conn, client_id: int, advisor_id: int) -> bool:
    return consent.current(conn, client_id, advisor_id, SCOPE)


def consent_text(advisor: str) -> str:
    """The words shown before the first share, naming the advisor - recorded
    word for word with the grant."""
    return CONSENT.format(advisor=" ".join(str(advisor or "").split()) or "your advisor")


# ---- the client's choices --------------------------------------------------- #
def start(conn, client_id: int, items, *, by: int, text_shown: str,
          today: date | None = None, now: datetime | None = None) -> dict:
    """The first share: records the consent grant with `text_shown` and the
    ticked items, in one transaction. Returns shared(). Raises
    PermissionError for anyone but the client with an advisor, ValueError
    with nothing valid ticked or no words."""
    advisor_id = advisor_for(conn, client_id, by)
    if advisor_id is None:
        raise PermissionError(NOT_ALLOWED)
    picked = [i for i in dict.fromkeys(items or ()) if valid(i)]
    if not picked:
        raise ValueError("tick something to share")
    day = _today(today)
    try:
        if not consented(conn, client_id, advisor_id):
            consent.grant(conn, client_id, advisor_id, text_shown, HOW, scope=SCOPE, now=now,
                          commit=False)
        for item in picked:
            _add(conn, client_id, advisor_id, item, day)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return shared(conn, client_id, advisor_id)


def _add(conn, client_id, advisor_id, item, day):
    conn.execute("INSERT INTO advisor_pack (user_id, advisor_id, item, shared_on) "
                 "VALUES (?, ?, ?, ?) ON CONFLICT (user_id, advisor_id, item) DO NOTHING",
                 (int(client_id), int(advisor_id), item, day))


def tick(conn, client_id: int, item: str, on: bool, *, by: int, today: date | None = None,
         now: datetime | None = None) -> dict:
    """Tick or untick one item once sharing is agreed. Unticking takes it out
    of the advisor's view at once; unticking the last one ends this sharing
    (a revoke). Ticking while nothing is agreed raises PermissionError -
    that's start()'s, with the words. Returns shared()."""
    advisor_id = advisor_for(conn, client_id, by)
    if advisor_id is None:
        raise PermissionError(NOT_ALLOWED)
    if not valid(item):
        return shared(conn, client_id, advisor_id)
    agreed = consented(conn, client_id, advisor_id)
    if on and not agreed:
        raise PermissionError("the first share needs the consent words")
    try:
        if on:
            _add(conn, client_id, advisor_id, item, _today(today))
        else:
            conn.execute("DELETE FROM advisor_pack WHERE user_id = ? AND advisor_id = ? "
                         "AND item = ?", (int(client_id), int(advisor_id), item))
            left = conn.execute("SELECT COUNT(*) AS n FROM advisor_pack WHERE user_id = ? "
                                "AND advisor_id = ?", (int(client_id), int(advisor_id))
                                ).fetchone()["n"]
            if not left and agreed:
                consent.revoke(conn, client_id, advisor_id, HOW, scope=SCOPE, now=now,
                               commit=False)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return shared(conn, client_id, advisor_id)


def stop(conn, client_id: int, *, by: int, now: datetime | None = None) -> None:
    """Untick everything: the rows go and the sharing ends (a revoke)."""
    advisor_id = advisor_for(conn, client_id, by)
    if advisor_id is None:
        raise PermissionError(NOT_ALLOWED)
    try:
        on_unlink(conn, client_id, advisor_id, HOW, now=now)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def on_unlink(conn, client_id: int, advisor_id: int, how: str, *,
              now: datetime | None = None) -> None:
    """The client and this advisor no longer share it (the relationship
    ended, or the client stopped): their rows go, and a revoke is written
    when the sharing was in force. In the caller's transaction (no commit)."""
    conn.execute("DELETE FROM advisor_pack WHERE user_id = ? AND advisor_id = ?",
                 (int(client_id), int(advisor_id)))
    if int(client_id) != int(advisor_id) and consented(conn, client_id, advisor_id):
        consent.revoke(conn, client_id, advisor_id, how, scope=SCOPE, now=now, commit=False)


# ---- the advisor's card ------------------------------------------------------ #
def for_advisor(conn, advisor_id: int, client_id: int, *, features=None) -> list[dict]:
    """What `client_id` chose to show `advisor_id`, in order: [{"item",
    "kind", "title", "lines" (plain text), "own_words" (lines are the
    client's free text), "shared_on"}] - only ticked items, only while the
    advisor may view the client and the sharing is in force. Raises
    PermissionError for anyone else. An item with nothing behind it any
    more (a fork no longer theirs, a deleted note) is left out."""
    import auth
    if advisor_id == client_id or not auth.can_view(conn, advisor_id, client_id):
        raise PermissionError("only this client's advisor")
    if not consented(conn, client_id, advisor_id):
        return []
    rows = {i: d for i, d in shared(conn, client_id, advisor_id).items()
            if feature_ok(i, features)}
    if not rows:
        return []
    p = {}
    if any(kind(i) in (FORK, READINESS, PLACES) for i in rows):
        import prefs
        p = prefs.load(conn, client_id)
    order = offered(p, has_storm_note=True, features=features, ticked=rows)
    out = []
    for item in [i for i in order if i in rows]:
        built = _build(conn, client_id, item, p)
        if built is not None:
            out.append({"item": item, "kind": kind(item), "shared_on": rows[item], **built})
    return out


def _build(conn, client_id: int, item: str, p: dict) -> dict | None:
    k = kind(item)
    if k == ONE_PAGER:
        import explain_share
        lines = [f"{heading}: {text}"
                 for _, heading, text in explain_share.lines(explain_share.page(conn, client_id))]
        return {"title": LABELS[ONE_PAGER][1], "own_words": False,
                "lines": lines or [explain_share.PAGE_EMPTY]}
    if k == FORK:
        fork = item[len(FORK):]
        if fork not in trail_forks.mine(p.get(trail_forks.PREF)):
            return None
        return {"title": LABELS[FORK][1], "own_words": False,
                "lines": [trail_forks.BY_KEY[fork]["title"]]}
    if k == READINESS:
        lines = []
        for _side, side_label, rows in drills.readiness(p):
            done = [t for _k, t, ok in rows if ok]
            todo = [t for _k, t, ok in rows if not ok]
            lines.append(f"{side_label}: rehearsed - {', '.join(done) or 'none yet'}; "
                         f"not yet - {', '.join(todo) or 'none'}.")
        return {"title": LABELS[READINESS][1], "own_words": False, "lines": lines}
    if k == STORM_NOTE:
        import future_notes
        note = future_notes.get(conn, client_id, future_notes.DRILL)
        if not note or not str(note.get("body") or "").strip():
            return None
        return {"title": LABELS[STORM_NOTE][1], "own_words": True,
                "lines": [" ".join(str(note["body"]).split())],
                "written_on": future_notes.written_on(note)}
    if k == PLACES:
        places = lost_found.clean_saved(p.get(lost_found.PREF))["places"]
        if not places:
            return None
        return {"title": LABELS[PLACES][1], "own_words": False,
                "lines": [f"{name}: {lost_found.STATUSES[places[key]].lower()}"
                          for key, name in lost_found.PLACES if key in places]}
    if k == QUESTION:
        return {"title": QUESTIONS_ADVISOR, "own_words": False,
                "lines": [QUESTION_WORDS[item[len(QUESTION):]]]}
    return None


# ---- the seasonal note --------------------------------------------------------- #
def season_note(day: date) -> tuple[str, str]:
    """(heading, text) for the advisor's book: the season clients are in and
    its education topics - or, between seasons, the next one."""
    import seasons
    key = seasons.season_of(day)
    if key:
        return seasons.BY_KEY[key][2], SEASON_TOPICS[key]
    nxt, _first = seasons.next_season(day)
    return (f"Between seasons - next, {seasons.when_label(nxt)}",
            SEASON_TOPICS[nxt])


def all_text() -> str:
    """Every fixed word the feature shows (for the wording tests)."""
    parts = [TITLE, INTRO, QUESTIONS_LEAD, QUESTIONS_NOTE, NOT_YET, CONSENT, CONFIRM, STOP,
             STOPPED, SHARED_ON, NOT_ALLOWED, ADVISOR_TITLE, ADVISOR_INTRO, ADVISOR_OPEN,
             ADVISOR_CLOSE, NOTHING_SHARED, SHARED_BY, ADVISOR_FOOT, STORM_WRITTEN,
             QUESTIONS_ADVISOR, SEASON_TITLE, SEASON_NOTE, *SEASON_TOPICS.values(),
             *(w for pair in LABELS.values() for w in pair), *QUESTION_WORDS.values()]
    return "\n".join(parts)
