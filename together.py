"""Doing it together (ROADMAP "Walk Together", flag `together`): two people
with their own Northwend accounts - friends, partners, family - pair up and
each sees three facts about the other's habits. Nothing else, ever.

What crosses over (for_partner, the ONLY read of a partner's data):
- "learn_days": how many different days this month they learned something -
  the days kept for Learn's steps and reads (recap.LEARN_DATES / LEARN_READS),
  Teach It Back's days (teach_back.PREF) and, where the money minute keeps its
  days in settings (MINUTE_PREF), those days too;
- "walk_done": whether this month's walk is finished (checkin.PREF_LOG);
- "wins": how many wins they've earned - the WINS_PREF list where one is
  kept, else the gear they've been shown (gear_seen, known keys only).
Three numbers (a count, a yes/no, a count), and their first name if they gave
one (explain_share.first_name: letters only, never the login or email). Never
a value, a holding, a goal, an account, a fund, a verdict or a date.

The rules:
- Individuals on their own account only: never an advisor, an admin, an
  advisor's client (client mode) or an advisor working in a client's account
  (eligible(), may_use()). A pairing whose side later becomes one of those
  shows nothing until it's ended.
- Pairing starts with a one-time link: secrets.token_urlsafe(TOKEN_BYTES),
  only its SHA-256 kept (together_invites), shown once, working INVITE_DAYS
  days. The person who opens it must be signed in to their own eligible
  account and say yes to JOIN_CONSENT. Then both sides are recorded with
  consent.grant (scope "together"): the inviter's with INVITE_CONSENT (the
  words they saw when they made the link, dated then), the invitee's with
  JOIN_CONSENT - word for word, with their SHA-256. The link is deleted.
- At most MAX_PARTNERS pairings (and open invitations) per account.
- Either side stops in one step (stop): both rows go and a revoke is written
  for each direction (consent.revoke) - the other side simply sees it end.
  Deleting either account does the same (on_account_deleted).
- A nudge: a fixed email with no figures and no names ("Your walk is
  waiting", NUDGE_LINES) through mailer, to a confirmed email only, only
  while the partner hasn't walked this month, only if they allow nudges
  (PREF_NUDGES_OFF unset - on from pairing, a switch on Life, and the
  email's one-click unsubscribe, kind "together"), at most once every
  NUDGE_DAYS days from each person to each partner, and inside
  rate_limits.NUDGE.

Two tables: together_invites (open invitations: the hash and the times) and
together_pairs (one row per direction: user_id sees partner_id; since and
when user_id last nudged them). Every read filters user_id. Deleted with
either account (admin.ACCOUNT_TABLES); in the owner's export without the
hash or the partner's id (export.OWN). Never sent to the AI, never in an
advisor's client record.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import date, datetime, timedelta, timezone

import consent

FLAG = "together"                 # flags.FEATURES["together"]
SCOPE = consent.TOGETHER          # the consent records' scope
HOW_INVITE = "together_invite"    # consent.HOWS: the inviter's yes, when they made the link
HOW_JOIN = "together_join"        # the invitee's yes, on the link
HOW_STOP = "together_stop"        # the person who pressed Stop sharing
HOW_ENDED = "together_ended"      # the other side of a stop
QUERY = "together"                # ?together=<token>
TOKEN_BYTES = 32                  # 256 bits
INVITE_DAYS = 7
MAX_PARTNERS = 3                  # pairings plus open invitations, per account
NUDGE_DAYS = 7                    # one nudge a week from each person to each partner
FACTS = ("learn_days", "walk_done", "wins")   # all that ever crosses over
PREF_NUDGES_OFF = "together_nudges_off"       # True: no nudge emails for this account
MINUTE_PREF = "money_minute"      # the money minute's settings, where it keeps them
WINS_PREF = "wins"                # wins earned, where they're kept
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")

# ---- the words -------------------------------------------------------------- #
TITLE = "Doing it together"
INTRO = ("Pair up with a friend, partner or family member who uses Northwend. You see each "
         "other's habits, never amounts or holdings.")
WHAT_SHARED = ("What's shared: learning days this month, whether this month's walk is done, "
               "and wins earned. Never values, holdings, goals or accounts. Either of you can "
               "stop sharing at any time.")
INVITE_CONSENT = (
    "You're inviting someone to do it together. Once they say yes, each of you sees three "
    "things about the other, and nothing else: how many days you've learned something this "
    "month, whether you've done this month's walk, and how many wins you've earned - and "
    "your first name, if you've given one on your Account page. Never your amounts, "
    "holdings, goals or accounts. Each of you can send the other a short email, at most "
    "once a week, that says only \"Your walk is waiting\", and either of you can turn those "
    "off. Either of you can stop sharing at any time, in one step.")
JOIN_CONSENT = (
    "{name} invited you to do it together. If you say yes, each of you sees three things "
    "about the other, and nothing else: how many days you've learned something this month, "
    "whether you've done this month's walk, and how many wins you've earned - and your "
    "first name, if you've given one on your Account page. Never your amounts, holdings, "
    "goals or accounts. Each of you can send the other a short email, at most once a week, "
    "that says only \"Your walk is waiting\", and either of you can turn those off. Either "
    "of you can stop sharing at any time, in one step.")
SOMEONE = "Someone"               # the inviter, when they've given no first name
PARTNER = "Your partner"          # a partner, when they've given no first name
MAKE_LINK = "Invite someone with a link"
INVITE_AGREE = "I understand what we'll each see"
SHOWN_ONCE = ("Send this link to the person you'd like to pair up with. It works once, for "
              f"{INVITE_DAYS} days. For your privacy Northwend keeps only a scrambled version, "
              "so it can't be shown again - you can always make a new one.")
JOIN_YES = "Yes, pair up"
JOIN_NO = "No thanks"
JOINED = "You're paired up. You'll see each other's habits here."
DECLINED = "Nothing was shared. The invitation is still there if you change your mind."
LINK_GONE = ("This invitation is no longer active. Invitations work once, for a short time - "
             "ask for a new link if you'd like to pair up.")
SIGN_IN = ("Someone invited you to do it together on Northwend. Sign in to your own account "
           "to answer - nothing is shared until you say yes.")
NOT_ALLOWED = ("Doing it together is for your own account. It isn't offered to advisors, or "
               "while an advisor manages the account.")
OWN_LINK = "That's your own invitation - send it to the person you'd like to pair up with."
ALREADY = "You're already paired up with them."
FULL = (f"You can do it together with up to {MAX_PARTNERS} people at a time, counting "
        "invitations not yet answered. Stop sharing with someone, or cancel an invitation, "
        "to make room.")
THEY_ARE_FULL = (f"They're already doing it together with {MAX_PARTNERS} people, the most "
                 "at one time.")
STOP = "Stop sharing"
STOPPED = "Done - you no longer share with each other. Nothing of theirs stays here."
NONE_YET = "You haven't paired up with anyone yet."
YOU = "You"
LEARN_LABEL = "Learning days this month"
WALK_LABEL = "{month} walk"
WINS_LABEL = "Wins earned"
DONE, NOT_YET = "Done", "Not yet"
PAIRED_SINCE = "Paired since {month}"
NOT_SHOWN = "Nothing is shown while this account can't do it together."
NUDGE_BUTTON = "Send a nudge"
NUDGE_TITLE = "{name} hasn't done the {month} walk yet"
NUDGE_NOTE = "Send a friendly nudge. It says only \"Your walk is waiting\", nothing else."
NUDGE_SENT = "Nudge sent."
NUDGE_WAIT = "You've sent them a nudge in the last week. You can send another on {day}."
NUDGE_OFF = "They've turned nudges off."
NUDGE_NO_EMAIL = "They haven't confirmed an email address, so a nudge can't reach them."
NUDGE_FAILED = "The nudge didn't go just now. Please try again in a little while."
NUDGE_SWITCH = "Let the people I do it together with send me a nudge (\"Your walk is waiting\")"

NUDGE_SUBJECT = "Your walk is waiting"
NUDGE_LINES = (
    "Your walk is waiting.",
    "Someone you're doing it together with on Northwend sent you a friendly nudge. Your "
    "monthly walk takes about 3 minutes, whenever you're ready.",
    "To stop these nudges, turn them off on the Life page, under Doing it together.")


# ---- small helpers ---------------------------------------------------------- #
def _now(now: datetime | None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def _iso(now: datetime) -> str:
    return _now(now).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(stamp: str | None) -> datetime | None:
    try:
        return datetime.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def token_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def well_formed(token) -> bool:
    return isinstance(token, str) and bool(_TOKEN_RE.match(token))


def link(base: str, token: str) -> str:
    base = (base or "").split("?")[0].split("#")[0]
    if base and not base.endswith("/"):
        base += "/"
    return f"{base}?{QUERY}={token}"


def _first_name(conn, user_id: int) -> str | None:
    import explain_share
    return explain_share.owner_first_name(conn, user_id)


def month_name(today: date) -> str:
    return today.strftime("%B")


# ---- who may ----------------------------------------------------------------- #
def eligible(conn, user_id: int) -> bool:
    """An individual's own account: not an advisor, not an admin, not an
    advisor's client (client mode)."""
    import admin
    import advising
    row = conn.execute("SELECT is_advisor FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None or row["is_advisor"]:
        return False
    return not admin.is_admin(conn, user_id) and advising.advisor_of(conn, user_id) is None


def may_use(conn, user_id: int, by: int) -> bool:
    """The signed-in person, in their own eligible account."""
    return by == user_id and eligible(conn, user_id)


# ---- invitations -------------------------------------------------------------- #
def open_invites(conn, user_id: int, *, now: datetime | None = None) -> list[dict]:
    """The account's invitations not yet answered: {"id", "created_at", "expires_at"}."""
    return [dict(r) for r in conn.execute(
        "SELECT id, created_at, expires_at FROM together_invites WHERE user_id = ? "
        "AND expires_at > ? ORDER BY created_at DESC, id DESC", (user_id, _iso(_now(now))))]


def _pair_count(conn, user_id: int) -> int:
    return conn.execute("SELECT COUNT(*) AS n FROM together_pairs WHERE user_id = ?",
                        (user_id,)).fetchone()["n"]


def room(conn, user_id: int, *, now: datetime | None = None) -> int:
    """How many more pairings or invitations the account may have."""
    return max(0, MAX_PARTNERS - _pair_count(conn, user_id)
               - len(open_invites(conn, user_id, now=now)))


def invite(conn, user_id: int, *, by: int, now: datetime | None = None) -> str:
    """A new one-time link's token (shown once; only its hash is kept).
    PermissionError unless the signed-in person makes it for their own
    eligible account; ValueError(FULL) when there's no room."""
    if not may_use(conn, user_id, by):
        raise PermissionError("only the account's owner can invite someone")
    now = _now(now)
    conn.execute("DELETE FROM together_invites WHERE user_id = ? AND expires_at <= ?",
                 (user_id, _iso(now)))
    if room(conn, user_id, now=now) <= 0:
        conn.commit()
        raise ValueError(FULL)
    token = secrets.token_urlsafe(TOKEN_BYTES)
    conn.execute("INSERT INTO together_invites (user_id, token_hash, created_at, expires_at) "
                 "VALUES (?, ?, ?, ?)", (user_id, token_hash(token), _iso(now),
                                         _iso(now + timedelta(days=INVITE_DAYS))))
    conn.commit()
    return token


def cancel_invite(conn, user_id: int, invite_id: int) -> bool:
    cur = conn.execute("DELETE FROM together_invites WHERE id = ? AND user_id = ?",
                       (invite_id, user_id))
    conn.commit()
    return (cur.rowcount or 0) > 0


def find_invite(conn, hashed: str, *, now: datetime | None = None) -> dict | None:
    """{"id", "user_id", "created_at", "name"} for a working invitation by its
    hash (the page keeps only the hash), else None - unknown, used, expired,
    or its maker can't do it together any more, alike. "name": the inviter's
    first name, or SOMEONE."""
    if not isinstance(hashed, str) or not re.fullmatch(r"[0-9a-f]{64}", hashed):
        return None
    row = conn.execute("SELECT id, user_id, created_at FROM together_invites "
                       "WHERE token_hash = ? AND expires_at > ?",
                       (hashed, _iso(_now(now)))).fetchone()
    if row is None or not eligible(conn, row["user_id"]):
        return None
    return {**dict(row), "name": _first_name(conn, row["user_id"]) or SOMEONE}


def join_text(name: str) -> str:
    """JOIN_CONSENT naming the inviter - recorded word for word."""
    return JOIN_CONSENT.format(name=name or SOMEONE)


def accept(conn, hashed: str, user_id: int, *, by: int, text_shown: str,
           now: datetime | None = None) -> int:
    """Pair up: the signed-in person (`user_id`, by == user_id) says yes to
    an invitation, having been shown `text_shown`. In one transaction: both
    directions' rows, both consent grants (the inviter's with INVITE_CONSENT,
    dated when they made the link), and the invitation deleted. Returns the
    partner's id. PermissionError for someone who can't, ValueError (with
    the words to show) when the link doesn't work or there's no room."""
    if not (text_shown or "").strip():
        raise ValueError("a yes records the exact words shown")
    if not may_use(conn, user_id, by):
        raise PermissionError(NOT_ALLOWED)
    now = _now(now)
    found = find_invite(conn, hashed, now=now)
    if found is None:
        raise ValueError(LINK_GONE)
    partner = found["user_id"]
    if partner == user_id:
        raise ValueError(OWN_LINK)
    if conn.execute("SELECT 1 FROM together_pairs WHERE user_id = ? AND partner_id = ?",
                    (user_id, partner)).fetchone():
        raise ValueError(ALREADY)
    if room(conn, user_id, now=now) <= 0:
        raise ValueError(FULL)
    # the invitation itself is one of the inviter's places; it becomes the pair
    if _pair_count(conn, partner) >= MAX_PARTNERS:
        raise ValueError(THEY_ARE_FULL)
    made = _parse(found["created_at"]) or now
    with conn:
        conn.execute("DELETE FROM together_invites WHERE id = ?", (found["id"],))
        for me, them in ((user_id, partner), (partner, user_id)):
            conn.execute("INSERT INTO together_pairs (user_id, partner_id, since) "
                         "VALUES (?, ?, ?)", (me, them, _iso(now)))
        consent.grant(conn, partner, user_id, INVITE_CONSENT, HOW_INVITE, scope=SCOPE,
                      now=made, commit=False)
        consent.grant(conn, user_id, partner, text_shown, HOW_JOIN, scope=SCOPE, now=now,
                      commit=False)
    return partner


# ---- pairings ------------------------------------------------------------------ #
def partners(conn, user_id: int) -> list[dict]:
    """The account's partners, oldest first: {"partner_id", "since",
    "nudged_at", "name"} - the name is their first name or PARTNER."""
    rows = conn.execute(
        "SELECT p.partner_id, p.since, p.nudged_at, u.display_name FROM together_pairs p "
        "JOIN users u ON u.id = p.partner_id WHERE p.user_id = ? ORDER BY p.since, p.id",
        (user_id,)).fetchall()
    import explain_share
    return [{"partner_id": r["partner_id"], "since": r["since"], "nudged_at": r["nudged_at"],
             "name": explain_share.first_name(r["display_name"]) or PARTNER} for r in rows]


def _paired(conn, a: int, b: int) -> bool:
    """Both directions' rows, and both grants in force."""
    n = conn.execute("SELECT COUNT(*) AS n FROM together_pairs WHERE (user_id = ? AND "
                     "partner_id = ?) OR (user_id = ? AND partner_id = ?)",
                     (a, b, b, a)).fetchone()["n"]
    return (n == 2 and consent.current(conn, a, b, SCOPE)
            and consent.current(conn, b, a, SCOPE))


def stop(conn, user_id: int, partner_id: int, *, by: int,
         now: datetime | None = None) -> bool:
    """Stop sharing, in one step: both rows go and both directions get a
    revoke. False if they weren't paired. Only the signed-in person, for
    their own account (it works even if they've since become ineligible -
    stopping is always allowed)."""
    if by != user_id:
        raise PermissionError("only the account's owner can stop sharing")
    if not conn.execute("SELECT 1 FROM together_pairs WHERE user_id = ? AND partner_id = ?",
                        (user_id, partner_id)).fetchone():
        return False
    with conn:
        _end(conn, user_id, partner_id, HOW_STOP, HOW_ENDED, now)
    return True


def _end(conn, a: int, b: int, how_a: str, how_b: str, now: datetime | None) -> None:
    conn.execute("DELETE FROM together_pairs WHERE (user_id = ? AND partner_id = ?) OR "
                 "(user_id = ? AND partner_id = ?)", (a, b, b, a))
    if consent.current(conn, a, b, SCOPE):
        consent.revoke(conn, a, b, how_a, scope=SCOPE, now=now, commit=False)
    if consent.current(conn, b, a, SCOPE):
        consent.revoke(conn, b, a, how_b, scope=SCOPE, now=now, commit=False)


def on_account_deleted(conn, user_id: int, *, now: datetime | None = None) -> None:
    """An account is going (admin.delete_account, inside its transaction):
    each pairing ends with a revoke both ways; the rows go with the account."""
    for r in conn.execute("SELECT partner_id FROM together_pairs WHERE user_id = ?",
                          (user_id,)).fetchall():
        _end(conn, user_id, r["partner_id"], "account_deleted", "account_deleted", now)


def history(conn, user_id: int) -> list[dict]:
    """The account's own consent records for doing it together, newest first:
    {"at", "kind", "how", "text_shown", "name"} - the partner's first name
    (or PARTNER), never their login or email."""
    import explain_share
    rows = [r for r in consent.history(conn, user_id) if r["scope"] == SCOPE]
    ids = sorted({r["advisor_id"] for r in rows})
    names = {}
    if ids:
        names = {u["id"]: explain_share.first_name(u["display_name"]) for u in conn.execute(
            f"SELECT id, display_name FROM users WHERE id IN ({', '.join('?' * len(ids))})",
            tuple(ids))}
    return [{"at": r["at"], "kind": r["kind"], "how": r["how"], "text_shown": r["text_shown"],
             "name": names.get(r["advisor_id"]) or PARTNER} for r in rows]


def prune(conn, *, now: datetime | None = None) -> int:
    """Delete every invitation past its date (tidy.py, nightly)."""
    cur = conn.execute("DELETE FROM together_invites WHERE expires_at <= ?", (_iso(_now(now)),))
    conn.commit()
    return max(cur.rowcount or 0, 0)


# ---- the three facts ------------------------------------------------------------ #
def _dates_in(value, depth: int = 0) -> set[str]:
    """Every 'YYYY-MM-DD' found in a kept setting (keys, values, lists)."""
    out: set[str] = set()
    if depth > 4:
        return out
    if isinstance(value, str):
        if _DAY_RE.match(value):
            out.add(value[:10])
    elif isinstance(value, dict):
        for k, v in value.items():
            out |= _dates_in(k, depth + 1) | _dates_in(v, depth + 1)
    elif isinstance(value, (list, tuple)):
        for v in value:
            out |= _dates_in(v, depth + 1)
    return out


def facts_from(p: dict | None, today: date) -> dict:
    """The three facts from one account's settings - only these keys, only a
    whole number, a yes/no and a whole number."""
    import checkin
    import gear
    import recap
    import teach_back
    p = p if isinstance(p, dict) else {}
    month = checkin.month_of(today)
    days = (_dates_in(p.get(recap.LEARN_DATES)) | _dates_in(p.get(recap.LEARN_READS))
            | {v["on"] for v in teach_back.state(p).values()})
    if MINUTE_PREF in p:
        days |= _dates_in(p.get(MINUTE_PREF))
    learn_days = len({d for d in days if d[:7] == month and d <= today.isoformat()})
    walk_done = month in {m for m in p.get(checkin.PREF_LOG) or [] if isinstance(m, str)}
    wins_kept = p.get(WINS_PREF)
    if isinstance(wins_kept, (list, dict)):
        wins = len(wins_kept)
    else:
        seen = p.get("gear_seen")
        wins = len({k for k in seen if k in gear.KEYS}) if isinstance(seen, list) else 0
    return {"learn_days": int(learn_days), "walk_done": bool(walk_done), "wins": int(wins)}


def own_facts(conn, user_id: int, *, today: date | None = None) -> dict:
    """The same three facts about yourself (the "You" card)."""
    import prefs
    return facts_from(prefs.load(conn, user_id), today or datetime.now(timezone.utc).date())


def for_partner(conn, viewer_id: int, partner_id: int, *, today: date | None = None) -> dict:
    """The ONLY read of a partner's data: {"learn_days", "walk_done",
    "wins"} - nothing else. PermissionError unless the two are paired with
    both grants in force and both may still do it together."""
    import prefs
    if not (_paired(conn, viewer_id, partner_id) and eligible(conn, viewer_id)
            and eligible(conn, partner_id)):
        raise PermissionError("not paired")
    found = facts_from(prefs.load(conn, partner_id), today or datetime.now(timezone.utc).date())
    return {k: found[k] for k in FACTS}


# ---- nudges -------------------------------------------------------------------- #
def nudges_on(p: dict | None) -> bool:
    return not (p or {}).get(PREF_NUDGES_OFF)


def set_nudges(p: dict, on: bool) -> dict:
    """The settings with nudges on or off (changed in place, and returned)."""
    if on:
        p.pop(PREF_NUDGES_OFF, None)
    else:
        p[PREF_NUDGES_OFF] = True
    return p


def next_nudge(nudged_at: str | None, now: datetime | None = None) -> datetime | None:
    """When the next nudge may go to that partner, or None if it may now."""
    last = _parse(nudged_at)
    if last is None:
        return None
    nxt = last + timedelta(days=NUDGE_DAYS)
    return nxt if nxt > _now(now) else None


def nudge_email(to: str, link: str, unsub: str = "") -> bool:
    """The email itself: fixed words, no figures, no names."""
    import mailer
    text = (f"{NUDGE_LINES[0]}\n\n{NUDGE_LINES[1]}\n\nOpen Northwend: {link}\n\n"
            f"{NUDGE_LINES[2]}\n")
    if unsub:
        text += f"\n{mailer.UNSUBSCRIBE_LINE}: {unsub}\n"
    return mailer.send(to, NUDGE_SUBJECT, text,
                       mailer._html(list(NUDGE_LINES), ("Open Northwend", link),
                                    unsubscribe=unsub),
                       headers=mailer.unsubscribe_headers(unsub))


def nudge(conn, user_id: int, partner_id: int, *, by: int, app_url: str, send=nudge_email,
          now: datetime | None = None, today: date | None = None) -> tuple[bool, str]:
    """Send one nudge to a partner: (sent, the words to show). Only between
    two paired, eligible accounts, while the partner hasn't walked this
    month, allows nudges and has a confirmed email; once every NUDGE_DAYS
    from this person to that partner; inside rate_limits.NUDGE."""
    import prefs
    import rate_limits
    import unsubscribe
    if not may_use(conn, user_id, by):
        raise PermissionError(NOT_ALLOWED)
    now = _now(now)
    today = today or now.date()
    facts = for_partner(conn, user_id, partner_id, today=today)   # paired, or PermissionError
    if facts["walk_done"]:
        return False, ""
    row = conn.execute("SELECT nudged_at FROM together_pairs WHERE user_id = ? AND "
                       "partner_id = ?", (user_id, partner_id)).fetchone()
    wait = next_nudge(row["nudged_at"] if row else None, now)
    if wait is not None:
        return False, NUDGE_WAIT.format(day=f"{wait:%b} {wait.day}")
    if not nudges_on(prefs.load(conn, partner_id)):
        return False, NUDGE_OFF
    who = conn.execute("SELECT email FROM users WHERE id = ? AND email IS NOT NULL AND "
                       "email != '' AND email_verified_at IS NOT NULL",
                       (partner_id,)).fetchone()
    if who is None:
        return False, NUDGE_NO_EMAIL
    if not rate_limits.allow(conn, by, rate_limits.NUDGE, now=now):
        return False, rate_limits.CALM
    base = (app_url or "").split("?")[0].rstrip("/")
    unsub = unsubscribe.link(base, unsubscribe.new_token(conn, partner_id, "together",
                                                         who["email"], now=now)) if base else ""
    if not send(who["email"], base + "/?page=dashboard", unsub):
        return False, NUDGE_FAILED
    conn.execute("UPDATE together_pairs SET nudged_at = ? WHERE user_id = ? AND partner_id = ?",
                 (_iso(now), user_id, partner_id))
    conn.commit()
    return True, NUDGE_SENT


def all_text() -> str:
    """Every fixed word the feature shows (for the tests' word checks)."""
    return "\n".join([
        TITLE, INTRO, WHAT_SHARED, INVITE_CONSENT, JOIN_CONSENT, SOMEONE, PARTNER, MAKE_LINK,
        INVITE_AGREE, SHOWN_ONCE, JOIN_YES, JOIN_NO, JOINED, DECLINED, LINK_GONE, SIGN_IN,
        NOT_ALLOWED, OWN_LINK, ALREADY, FULL, THEY_ARE_FULL, STOP, STOPPED, NONE_YET, YOU,
        LEARN_LABEL, WALK_LABEL, WINS_LABEL, DONE, NOT_YET, PAIRED_SINCE, NOT_SHOWN,
        NUDGE_BUTTON, NUDGE_TITLE, NUDGE_NOTE, NUDGE_SENT, NUDGE_WAIT, NUDGE_OFF,
        NUDGE_NO_EMAIL, NUDGE_FAILED, NUDGE_SWITCH, NUDGE_SUBJECT, *NUDGE_LINES])
