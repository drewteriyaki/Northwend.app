"""Introductions (docs/PLAN.md step 5 items 5 and 6, master brief 4.3): a
person who found an advisor in Find a guide asks to be introduced, the
advisor answers, and - only if the person then chooses it, in two separate
steps - the person shares their full account with that advisor. Flag
`intros`, gate L2 (flags.FEATURES; it lives inside Find a guide, so the
`directory` flag too). Pure logic, no Streamlit; the pages are
views/intros.py.

The rules, enforced here and tested (tests/test_intros.py):
- **Only an intro actually sent is recorded** (brief 3.4). Browsing,
  filtering and opening the form write nothing; there are no counts of
  views, impressions or clicks for anyone.
- **Only to an advisor shown in Find a guide** (directory.visible), from a
  person who isn't an advisor and doesn't already have one (client mode
  never sees any of this). No second open intro to the same advisor, none
  again for DECLINE_WAIT_DAYS after they declined, and at most PER_DAY a day.
- **The advisor sees only what the person chose to send:** the name they
  gave, their message, and a figure-free outline (outline()): their mix by
  asset class in whole percents, their goals, a timeline bucket and where
  they are on Northwend's route - the same kind of facts as Year in review's
  share card (recap.has_money guards it). Never an amount, a share count, a
  ticker, an account name or number, or their email. The outline is fixed
  when the intro is sent: it's what they agreed to share.
- **Advisors see only intros sent to them** (for_advisor, by advisor_id),
  and never the person's account id or email. They answer in text (plain,
  capped, no links or email addresses), can share the scheduling link from
  their listing, or decline.
- **Full sharing only from the second, separate consent** (share_account):
  after an answer, the person reads exactly what sharing means
  (sharing_lines, step 1), then ticks and confirms (CONFIRM_LINE, step 2).
  Only then, in one transaction: consent.grant(..., how="intro") with the
  exact words shown, the advisor_clients link (auth.link_client), and the
  intro marked shared. Stopping later is the existing "Stop sharing" (Your
  advisor page), which writes the revoke.

One table, intro_requests: deleted with either account
(admin.ACCOUNT_TABLES), in each side's Export everything (export.OWN).

The words people see are DRAFT (COPY_STATUS) until the lawyer signs off
gate L2 (docs/LEGAL_GATES.md).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

FLAG = "intros"   # flags.FEATURES["intros"]: gate L2 as well as the flag

STATUSES = ("sent", "replied", "declined", "withdrawn", "shared")
OPEN = ("sent", "replied")             # still waiting on someone
PER_DAY = 3                            # intros a person can send in 24 hours
DECLINE_WAIT_DAYS = 90                 # not to the same advisor again after a decline
LIMITS = {"message": 1000, "reply": 1000, "name": 40}
# what the person can choose to send with their message (outline())
PARTS = ("mix", "goals", "timeline", "stage")
PART_LABELS = {"mix": "Your mix by asset class", "goals": "Your goals",
               "timeline": "Your timeline", "stage": "Where you are"}
# the route stage in plain words (context_card.STAGES' keys)
STAGE_WORDS = {"learn": "Learning the basics",
               "invest": "Getting ready to start investing",
               "investing": "Already investing"}

# ---- the words: DRAFT, reviewed under gate L2 ------------------------------ #
COPY_STATUS = "DRAFT"   # until the lawyer signs off L2 (docs/LEGAL_GATES.md)
FORM_INTRO = ("Send a short note to say hello and what you'd like help with. The advisor "
              "answers here in Northwend. Nothing else about you is shared unless you "
              "choose it below.")
FORM_PRIVACY = ("They won't see any amounts, holdings, account names or your email. "
                "No need to include amounts or account numbers in your message - they can "
                "ask if they need them.")
SENT_NOTE = ("Sent. You'll see their answer under Your introductions on this page - and an "
             "email lets you know, if your email is confirmed.")
PERSON_LIST_NOTE = ("Only you and the advisor you wrote to see an introduction. Sharing your "
                    "full account is a separate choice, and only ever yours.")
ADVISOR_INTRO = ("People who found you in Find a guide and asked to talk. You see only what "
                 "they chose to send: their message and a figure-free outline - never "
                 "amounts, holdings or account details. Northwend doesn't count views or "
                 "clicks.")
SHARE_TITLE = "What sharing your full account means"
# step 1: exactly what full sharing does - true to the code (auth.can_view,
# dashboard CAN_MANAGE / CAN_IMPORT, access_log.py, export.client_record,
# advising.end_relationship) and to the Privacy Policy's "your advisor" lines
SHARE_LINES = (
    "{name} will see everything in your Northwend account: your holdings, plan, goals "
    "and investing-profile answers, and the name and email on your account. Your notes "
    "to future you, your monthly walks and your account map stay yours alone.",
    "{name} will set your plan, goal, target mix and alert limits from then on, and help "
    "you manage them. Bringing in new statements is up to them, unless they open it to "
    "you.",
    "Each time {name} opens a page in your account, it's noted on your Account page "
    "(\"Who has looked at your account\").",
    "Their advice is {name}'s, from {firm} - not Northwend's. Northwend provides the "
    "software, never moves money and never sees your brokerage login.",
    "You can stop sharing at any time from the Your advisor page, and you keep "
    "everything. {name} keeps their own notes about working with you, for their records.",
)
# step 2: the tick that confirms it
CONFIRM_LINE = "I understand - share my full account with {name}"

_URL_IN_TEXT = re.compile(
    r"(https?://|www\.|\b[a-z0-9-]+\.(com|net|org|io|co|app|us|biz|info|me|ly|ai|link)\b"
    r"|[\w.+-]+@[\w-]+\.)", re.I)
# an account or phone number (spaces and dashes taken out first) - not a year
# or an amount written with commas
_LONG_DIGITS = re.compile(r"\d{6,}")


def _utc(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:      # a plain datetime is UTC already
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- checking what people type ---------------------------------------------- #
def check_text(text, limit: int, what: str = "Your message") -> tuple[str, str | None]:
    """(the text as saved, what's wrong with it or None): plain text up to
    `limit` characters - no links, email addresses, tags or account numbers."""
    text = "\n".join(line.rstrip() for line in str(text or "").strip().splitlines())
    if len(text) > limit:
        return text, f"{what}: up to {limit} characters."
    if _URL_IN_TEXT.search(text):
        return text, f"{what}: plain text only - no links or email addresses."
    if "<" in text or ">" in text:
        return text, f"{what}: plain text only."
    if _LONG_DIGITS.search(text.replace(" ", "").replace("-", "")):
        return text, (f"{what}: please leave out account and phone numbers - contact "
                      "details can come once you're talking.")
    return text, None


def check_name(name) -> tuple[str, str | None]:
    """The name the person gives the advisor: one line, 1 to LIMITS["name"]
    characters, no email address, link or digits run."""
    name = " ".join(str(name or "").split())
    if not name:
        return name, "Add the name you'd like the advisor to see."
    if "@" in name:
        return name, "Your name: a name, not an email address."
    name, problem = check_text(name, LIMITS["name"], "Your name")
    return name, problem


# ---- the figure-free outline ------------------------------------------------ #
def _pct(v) -> int:
    try:
        return max(0, min(100, int(round(float(v)))))
    except (TypeError, ValueError):
        return 0


def clean_outline(raw) -> dict:
    """Only what an outline may hold, whatever came in (a dict or its JSON):
    "mix" [[asset class, whole %]], "goals" [advisor.GOAL_OPTIONS],
    "timeline" (a context_card.TIMELINES label), "stage" (a STAGE_WORDS key).
    Anything else - a figure, a ticker, a name - is dropped."""
    import advisor
    import context_card
    from asset_classes import CLASSES
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except ValueError:
            raw = {}
    raw = raw if isinstance(raw, dict) else {}
    out: dict = {}
    mix = []
    for pair in raw.get("mix") or []:
        if (isinstance(pair, (list, tuple)) and len(pair) == 2 and pair[0] in CLASSES
                and isinstance(pair[1], int) and not isinstance(pair[1], bool)
                and 0 < pair[1] <= 100 and pair[0] not in {k for k, _ in mix}):
            mix.append((pair[0], pair[1]))
    if mix:
        out["mix"] = [[k, v] for k, v in mix]
    goals = [g for g in raw.get("goals") or [] if g in advisor.GOAL_OPTIONS]
    if goals:
        out["goals"] = list(dict.fromkeys(goals))
    if raw.get("timeline") in {label for label, _ in context_card.TIMELINES}:
        out["timeline"] = raw["timeline"]
    if raw.get("stage") in STAGE_WORDS:
        out["stage"] = raw["stage"]
    return out


def outline(conn, person_id: int) -> dict:
    """What the person could send with an intro, from what Northwend already
    holds - the pieces Year in review's share card and Ask Northwend's card
    use: their latest holdings' mix by asset class (whole percents; nothing
    from the example portfolio), their goals and timeline bucket from their
    profile answers, and their stage on the route. Never an amount."""
    import advisor
    import asset_classes
    import context_card
    import portfolio
    from allocation import allocate

    held = portfolio.current_holdings(conn, person_id)
    real = bool(held["date"]) and held["source"] != portfolio.SAMPLE_SOURCE
    mix = []
    if real:
        rows = held["rows"]
        cash = {acct: (t.get("cash_value") or 0.0) for acct, t in held["totals"].items()}
        splits = asset_classes.splits(conn, rows, asset_classes.load_overrides(conn, person_id))
        alloc = allocate(rows, cash, splits)
        by = {r["label"]: r["pct"] for r in alloc["by_asset_class"]}
        mix = [[k, _pct(by[k])] for k in asset_classes.CLASSES
               if by.get(k) is not None and _pct(by[k]) > 0]
    profile = advisor.get_profile(conn, person_id)
    found = {"mix": mix,
             "goals": [g for g in advisor.split_multi(profile.get("goal"))
                       if g in advisor.GOAL_OPTIONS],
             "timeline": context_card.timeline_of(profile.get("time_horizon_years")),
             "stage": context_card.stage_of(has_real_holdings=real,
                                            experience=profile.get("experience"),
                                            managed=False)}
    return clean_outline(found)


def outline_lines(raw) -> list[tuple[str, str, str]]:
    """[(part, heading, line)] for an outline, in PARTS order - what the
    advisor reads. Checked: never anything that reads as money."""
    import recap
    o = clean_outline(raw)
    out = []
    if o.get("mix"):
        out.append(("mix", "Mix by asset class", ", ".join(f"{k} {v}%" for k, v in o["mix"])))
    if o.get("goals"):
        out.append(("goals", "Goals", ", ".join(o["goals"])))
    if o.get("timeline"):
        out.append(("timeline", "Timeline", f"{o['timeline']} until the money is needed"))
    if o.get("stage"):
        out.append(("stage", "Where they are", STAGE_WORDS[o["stage"]]))
    if any(recap.has_money(line) for _, _, line in out):
        raise ValueError("an intro's outline never carries an amount")
    return out


def pick(found: dict, parts) -> dict:
    """The parts of an outline the person ticked."""
    keep = set(parts or ()) & set(PARTS)
    return clean_outline({k: v for k, v in (found or {}).items() if k in keep})


# ---- who the advisor is, to the person ---------------------------------------- #
def advisor_names(conn, advisor_id: int) -> dict:
    """{"name", "firm"} as the person met them: the directory listing's name
    and firm, else how the advisor shows themselves to clients."""
    row = conn.execute("SELECT display_name, firm FROM advisor_profiles WHERE user_id = ?",
                       (advisor_id,)).fetchone()
    if row and row["display_name"]:
        return {"name": row["display_name"], "firm": row["firm"] or ""}
    import standing_line
    return standing_line.who(conn, advisor_id)


def sharing_lines(name: str, firm: str | None = None) -> list[str]:
    """Step 1's words, naming the advisor."""
    import standing_line
    firm = " ".join(str(firm or "").split()) or standing_line.NO_FIRM
    return [line.format(name=name, firm=firm) for line in SHARE_LINES]


def sharing_text(name: str, firm: str | None = None) -> str:
    """Everything the two steps show, as recorded with the consent grant:
    the title, step 1's lines and step 2's confirm line."""
    return "\n\n".join([SHARE_TITLE, *sharing_lines(name, firm),
                        CONFIRM_LINE.format(name=name)])


def sharing_text_for(conn, advisor_id: int) -> str:
    who = advisor_names(conn, advisor_id)
    return sharing_text(who["name"], who["firm"])


# ---- sending ------------------------------------------------------------------ #
def _is_advisor(conn, user_id: int) -> bool:
    row = conn.execute("SELECT is_advisor FROM users WHERE id = ?", (user_id,)).fetchone()
    return bool(row and row["is_advisor"])


def _has_advisor(conn, user_id: int) -> bool:
    return conn.execute("SELECT 1 FROM advisor_clients WHERE client_id = ? LIMIT 1",
                        (user_id,)).fetchone() is not None


def can_send(conn, person_id: int, advisor_id: int, *, now: datetime | None = None) -> str | None:
    """Why this person can't send this advisor an intro now, or None."""
    import directory
    now = now or datetime.now(timezone.utc)
    if person_id == advisor_id or _is_advisor(conn, person_id) or _has_advisor(conn, person_id):
        return "Introductions are for people who don't have an advisor in Northwend yet."
    if advisor_id not in {p["user_id"] for p in directory.visible(conn)}:
        return "This advisor isn't listed in Find a guide right now."
    mine = conn.execute("SELECT status, created_at, closed_at FROM intro_requests "
                        "WHERE person_id = ? AND advisor_id = ?",
                        (person_id, advisor_id)).fetchall()
    if any(r["status"] in OPEN for r in mine):
        return ("You've already written to this advisor - their answer will show under Your "
                "introductions.")
    since = _utc(now - timedelta(days=DECLINE_WAIT_DAYS))
    if any(r["status"] == "declined" and (r["closed_at"] or "") > since for r in mine):
        return "This advisor answered your last introduction, so it can't be sent again yet."
    day = conn.execute("SELECT COUNT(*) AS n FROM intro_requests WHERE person_id = ? "
                       "AND created_at > ?",
                       (person_id, _utc(now - timedelta(days=1)))).fetchone()["n"]
    if day >= PER_DAY:
        return (f"You've sent {PER_DAY} introductions in the last day - you can send more "
                "tomorrow.")
    return None


def send(conn, person_id: int, advisor_id: int, message: str, *, name: str,
         outline: dict | None = None, now: datetime | None = None) -> dict:
    """The person sends an intro: {"ok", "error", "id"}. `outline` is what
    they ticked to send (pick() of outline()) - cleaned again here."""
    now = now or datetime.now(timezone.utc)
    out = {"ok": False, "error": None, "id": None}
    message, problem = check_text(message, LIMITS["message"])
    if not problem and not message:
        problem = "Add a short message for the advisor."
    name, name_problem = check_name(name)
    problem = name_problem or problem or can_send(conn, person_id, advisor_id, now=now)
    if problem:
        return {**out, "error": problem}
    shared = clean_outline(outline or {})
    outline_lines(shared)   # never anything that reads as money
    conn.execute(
        "INSERT INTO intro_requests (person_id, advisor_id, created_at, person_name, message, "
        "outline, status, link_shared) VALUES (?, ?, ?, ?, ?, ?, 'sent', 0)",
        (person_id, advisor_id, _utc(now), name, message, json.dumps(shared)))
    new_id = conn.execute("SELECT MAX(id) AS i FROM intro_requests WHERE person_id = ? AND "
                          "advisor_id = ?", (person_id, advisor_id)).fetchone()["i"]
    conn.commit()
    return {**out, "ok": True, "id": new_id}


# ---- reading ------------------------------------------------------------------- #
_PERSON_COLS = ("id", "advisor_id", "created_at", "person_name", "message", "outline",
                "status", "reply", "replied_at", "link_shared", "closed_at")
# the advisor never reads the person's account id
_ADVISOR_COLS = ("id", "created_at", "person_name", "message", "outline", "status", "reply",
                 "replied_at", "link_shared", "closed_at")


def _shape(row) -> dict:
    d = dict(row)
    d["outline"] = clean_outline(d.get("outline"))
    d["lines"] = outline_lines(d["outline"])
    d["link_shared"] = bool(d.get("link_shared"))
    return d


def for_person(conn, person_id: int) -> list[dict]:
    """The person's own intros, newest first, each with the advisor's
    "advisor" name and "firm", and "scheduling_url" once they shared it."""
    rows = conn.execute(f"SELECT {', '.join(_PERSON_COLS)} FROM intro_requests "
                        "WHERE person_id = ? ORDER BY id DESC", (person_id,)).fetchall()
    out = []
    for r in rows:
        d = _shape(r)
        who = advisor_names(conn, d["advisor_id"])
        d["advisor"], d["firm"] = who["name"], who["firm"]
        d["scheduling_url"] = scheduling_url(conn, d["advisor_id"]) if d["link_shared"] else None
        out.append(d)
    return out


def for_advisor(conn, advisor_id: int) -> list[dict]:
    """Intros sent to this advisor, newest first: the name the person gave,
    their message, the outline they chose (and its "lines"), the status and
    any answer. Only their own - never another advisor's, never the person's
    account id or email."""
    rows = conn.execute(f"SELECT {', '.join(_ADVISOR_COLS)} FROM intro_requests "
                        "WHERE advisor_id = ? ORDER BY id DESC", (advisor_id,)).fetchall()
    return [_shape(r) for r in rows]


def scheduling_url(conn, advisor_id: int) -> str | None:
    """The scheduling link on the advisor's listing, if any."""
    row = conn.execute("SELECT scheduling_url FROM advisor_profiles WHERE user_id = ?",
                       (advisor_id,)).fetchone()
    return (row["scheduling_url"] or None) if row else None


def answer_email(conn, advisor_id: int, intro_id: int) -> str | None:
    """Where to tell the person that this advisor answered their intro: their
    confirmed email, for the advisor's own intro only. Used to send the "you
    have an answer" email - never shown to the advisor."""
    row = conn.execute("SELECT u.email, u.email_verified_at FROM intro_requests i "
                       "JOIN users u ON u.id = i.person_id WHERE i.id = ? AND i.advisor_id = ?",
                       (intro_id, advisor_id)).fetchone()
    return row["email"] if row and row["email"] and row["email_verified_at"] else None


def _mine_as_advisor(conn, advisor_id: int, intro_id: int):
    return conn.execute("SELECT * FROM intro_requests WHERE id = ? AND advisor_id = ?",
                        (intro_id, advisor_id)).fetchone()


# ---- the advisor answers -------------------------------------------------------- #
def reply(conn, advisor_id: int, intro_id: int, text: str, *, share_link: bool = False,
          now: datetime | None = None) -> dict:
    """The advisor's answer, once, to an intro sent to them: plain text (or
    only their scheduling link, with `share_link`). {"ok", "error"}."""
    row = _mine_as_advisor(conn, advisor_id, intro_id)
    if row is None or not _is_advisor(conn, advisor_id):
        return {"ok": False, "error": "That introduction isn't one of yours."}
    if row["status"] != "sent":
        return {"ok": False, "error": "You've already answered this introduction."}
    text, problem = check_text(text, LIMITS["reply"], "Your reply")
    url = scheduling_url(conn, advisor_id) if share_link else None
    if share_link and not url:
        problem = problem or "Add a scheduling link to your listing first."
    if not problem and not text and not url:
        problem = "Write a reply, or share your scheduling link."
    if problem:
        return {"ok": False, "error": problem}
    cur = conn.execute("UPDATE intro_requests SET status = 'replied', reply = ?, replied_at = ?, "
                       "link_shared = ? WHERE id = ? AND advisor_id = ? AND status = 'sent'",
                       (text, _utc(now), 1 if url else 0, intro_id, advisor_id))
    conn.commit()
    return {"ok": cur.rowcount == 1, "error": None if cur.rowcount == 1 else
            "You've already answered this introduction."}


def share_link(conn, advisor_id: int, intro_id: int) -> dict:
    """After a text reply: share the scheduling link from the listing too."""
    row = _mine_as_advisor(conn, advisor_id, intro_id)
    if row is None:
        return {"ok": False, "error": "That introduction isn't one of yours."}
    if row["status"] != "replied":
        return {"ok": False, "error": "Reply first - or this introduction is closed."}
    if not scheduling_url(conn, advisor_id):
        return {"ok": False, "error": "Add a scheduling link to your listing first."}
    conn.execute("UPDATE intro_requests SET link_shared = 1 WHERE id = ? AND advisor_id = ?",
                 (intro_id, advisor_id))
    conn.commit()
    return {"ok": True, "error": None}


def decline(conn, advisor_id: int, intro_id: int, note: str = "", *,
            now: datetime | None = None) -> dict:
    """The advisor won't take it further, with an optional short note (kept
    as the answer when there wasn't one). Closes an open intro."""
    row = _mine_as_advisor(conn, advisor_id, intro_id)
    if row is None:
        return {"ok": False, "error": "That introduction isn't one of yours."}
    if row["status"] not in OPEN:
        return {"ok": False, "error": "This introduction is already closed."}
    note, problem = check_text(note, LIMITS["reply"], "Your note")
    if problem:
        return {"ok": False, "error": problem}
    stamp = _utc(now)
    if row["status"] == "sent" and note:
        conn.execute("UPDATE intro_requests SET reply = ?, replied_at = ? WHERE id = ?",
                     (note, stamp, intro_id))
    conn.execute("UPDATE intro_requests SET status = 'declined', closed_at = ? WHERE id = ? "
                 "AND advisor_id = ?", (stamp, intro_id, advisor_id))
    conn.commit()
    return {"ok": True, "error": None}


# ---- the person's side ------------------------------------------------------------ #
def _mine_as_person(conn, person_id: int, intro_id: int):
    return conn.execute("SELECT * FROM intro_requests WHERE id = ? AND person_id = ?",
                        (intro_id, person_id)).fetchone()


def withdraw(conn, person_id: int, intro_id: int, *, now: datetime | None = None) -> dict:
    """The person takes back an open intro (it stays, marked withdrawn)."""
    row = _mine_as_person(conn, person_id, intro_id)
    if row is None or row["status"] not in OPEN:
        return {"ok": False, "error": "This introduction is already closed."}
    conn.execute("UPDATE intro_requests SET status = 'withdrawn', closed_at = ? WHERE id = ? "
                 "AND person_id = ?", (_utc(now), intro_id, person_id))
    conn.commit()
    return {"ok": True, "error": None}


def can_share(conn, person_id: int, intro_id: int) -> str | None:
    """Why the person can't share their full account from this intro, or None:
    the advisor has answered and not declined, the person has no advisor yet,
    and the advisor is still an approved advisor whose licence check and
    agreement are current (directory.OUTSIDE_CHECKS)."""
    import directory
    row = _mine_as_person(conn, person_id, intro_id)
    if row is None:
        return "That introduction isn't yours."
    if row["status"] != "replied":
        return "You can share once the advisor has answered."
    if _is_advisor(conn, person_id) or _has_advisor(conn, person_id):
        return "You already share your account with an advisor."
    adv = row["advisor_id"]
    if not (_is_advisor(conn, adv)
            and directory._passes_outside_checks(conn, adv, directory._outside_checks())):
        return "This advisor can't take on new clients in Northwend right now."
    return None


def share_account(conn, person_id: int, intro_id: int, text_shown: str, *, confirmed: bool,
                  now: datetime | None = None) -> dict:
    """Step 2: the person confirmed. Only with `confirmed` (the tick) and
    `text_shown` exactly the words the two steps show for this advisor now
    (sharing_text_for) - then, in one transaction: the consent grant with
    those words (how 'intro'), the advisor_clients link with the name the
    person gave as the advisor's name for them, and the intro marked shared.
    {"ok", "error", "advisor_id"}."""
    import auth
    import consent
    out = {"ok": False, "error": None, "advisor_id": None}
    if not confirmed:
        return {**out, "error": "Tick the box to confirm first."}
    problem = can_share(conn, person_id, intro_id)
    if problem:
        return {**out, "error": problem}
    row = _mine_as_person(conn, person_id, intro_id)
    adv = row["advisor_id"]
    if (text_shown or "") != sharing_text_for(conn, adv):
        return {**out, "error": "The details changed while you were reading - please read "
                                "them again."}
    try:
        cur = conn.execute("UPDATE intro_requests SET status = 'shared', closed_at = ? "
                           "WHERE id = ? AND person_id = ? AND status = 'replied'",
                           (_utc(now), intro_id, person_id))
        if cur.rowcount != 1:
            conn.rollback()
            return {**out, "error": "This introduction changed - please look again."}
        # the grant first: full sharing is made only from a grant (PLAN 5.6)
        consent.grant(conn, person_id, adv, text_shown, "intro", now=now, commit=False)
        auth.link_client(conn, adv, person_id, commit=False)
        conn.execute("UPDATE advisor_clients SET client_name = ? WHERE advisor_id = ? "
                     "AND client_id = ?", (row["person_name"], adv, person_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {**out, "ok": True, "advisor_id": adv}
