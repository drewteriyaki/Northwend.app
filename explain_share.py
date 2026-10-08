"""Explain It To Someone (ROADMAP R10): a private, expiring link that shows a
partner or an adult child the person's plan in plain words - without a
single figure - so they can understand it and, if they like, start
Northwend's Learn route themselves. Behind flag `explain_share`; the owner's
part is on the Life page and the page the link opens is drawn before
sign-in (views/explain_share.py), like the unsubscribe and reset links.

What the page shows, read from current data each time it's opened (page()):
- their mix by asset class (Stocks, Bonds, Cash, Other) in whole percents -
  from their own holdings only, never the example portfolio
  (intros.outline, the figure-free outline introductions use);
- their goal: what it's for (plans.GOAL_TYPES, or their profile's goals from
  advisor.GOAL_OPTIONS) and a timeline bucket (context_card.TIMELINES) -
  never an amount, a date or the goal's own name (free text could hold
  anything);
- where they are on Northwend's route (learn / start investing / investing);
- their plan: their target mix by asset class in whole percents and how far
  any part may drift (their own band, in points) before they look again;
- their first name, only if they ticked it for that link (the name they
  asked to be called, its first word, letters only - never the login or
  email).
Never a dollar amount, a share count, a price, a ticker, a fund name, an
account name or number, an institution, the email or the login. Every line
is checked (recap.has_money, and only known words or whole percents get in);
tests render a portfolio full of distinctive numbers and names and look for
each of them in every element.

The rules for the link:
- Made only by the signed-in owner, for their own account (by == user_id),
  never while an advisor is in a client's account, never for an advisor's
  client (client mode: their plan is the advisor's) and never by an admin
  (eligible()). A link stops working if its account later becomes any of
  those.
- The token is secrets.token_urlsafe(TOKEN_BYTES) - 256 bits. Only its
  SHA-256 is stored; the full link is shown once, when it's made.
- It expires after one of DAYS_CHOICES (default the shorter) and can be
  turned off at any time (revoke: the row is deleted). At most MAX_ACTIVE
  working links per account.
- An unknown, malformed, expired or turned-off link, a link whose owner
  can't share any more, and any link while the flag is off all show the same
  calm "no longer active" page - nothing says whose it was or why.
- Opening it needs no sign-in and signs nobody in. Each browser visit counts
  once against a per-address limit (a `signups` row keyed KEY_PREFIX + the
  address's SHA-256, as decoder_public.py does; tidied after a day), before
  the token is even looked up - so the limit says nothing about a link.
- For the owner only: how many times a link was opened and the last day
  (opens, last_opened_on) - never who, where from or when in the day.
- The token is never logged or printed; tidy.py deletes ended links.

One table, share_links: deleted with the account (admin.ACCOUNT_TABLES), in
the owner's Export everything (export.OWN, without its token_hash). Not in an
advisor's client record, never sent to the AI.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import date, datetime, timedelta, timezone

FLAG = "explain_share"     # flags.FEATURES["explain_share"]
QUERY = "share"            # ?share=<token>
TOKEN_BYTES = 32           # secrets.token_urlsafe(32): 256 bits, 43 characters
DAYS_CHOICES = (7, 30)     # how long a link works; the first is the default
DEFAULT_DAYS = DAYS_CHOICES[0]
MAX_ACTIVE = 3             # working links per account
KEY_PREFIX = "share:"      # signups.address_key for an opened link (rate limit)
PER_ADDRESS_PER_HOUR = 30  # links opened from one internet address in an hour
PER_HOUR = 1000            # links opened app-wide in an hour
DEFAULT_BAND = 5           # dashboard.DEFAULT_DRIFT_THRESHOLD, when they set none
NAME_MAX = 30
# a token as token_urlsafe makes them; anything else is never looked up
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,64}$")

# ---- the words ------------------------------------------------------------- #
OWNER_TITLE = "Explain it to someone"
OWNER_INTRO = ("Make a private link that shows a partner or family member your plan in plain "
               "words: your mix in percentages, what you're investing for and roughly when, "
               "and whether you're still learning the basics or already investing. They can "
               "read it without signing in, and start learning too if they'd like.")
OWNER_NEVER = ("The page never shows an amount, a holding, an account name or number, or your "
               "email - only percentages and plain words.")
OWNER_EXPIRY = ("A link works for the days you choose, and you can turn it off here at any "
                "time. Anyone with the link can open it, so send it only to people you'd "
                "show your plan to.")
SHOWN_ONCE = ("Copy it now. For your privacy Northwend keeps only a scrambled version of the "
              "link, so it can't be shown again - you can always make a new one.")
NOT_ALLOWED = ("Share links are for your own account. They aren't offered while an advisor "
               "manages the account.")
TOO_MANY = (f"You have {MAX_ACTIVE} working links, the most at one time. Turn one off to "
            "make another.")

PAGE_TITLE_NAMED = "{name}'s plan, in plain words"
PAGE_TITLE = "A plan, in plain words"
PAGE_INTRO = ("Someone who uses Northwend shared this page so you can see how their investing "
              "is set up. It shows percentages and plain words only - never amounts, "
              "holdings or account details.")
PAGE_EMPTY = "There isn't much to show here yet - they're just getting started."
LEARN_TITLE = "Want to understand it from the start?"
LEARN_TEXT = ("Northwend's Learn section explains the basics a few minutes at a time: what "
              "stocks, bonds and cash are, why people mix them, and how a plan like this one "
              "is put together. It's free, and you go at your own pace.")
LEARN_BUTTON = "Start learning the basics"
FOOTER = ("Northwend is an educational tool. This page describes one person's own plan - it "
          "isn't financial advice, and it isn't a suggestion for anyone else.")

INACTIVE_TITLE = "This link is no longer active"
INACTIVE_TEXT = ("Links to a Northwend plan work for a short time, and the person who made one "
                 "can turn it off whenever they like. If you were expecting to see something, "
                 "ask them for a new link.")
TOO_MANY_FROM_HERE = ("That's a lot of links opened from here in the last hour. Please try "
                      "again in a little while.")
TOO_MANY_EVERYWHERE = ("Lots of people are opening links right now. Please try again in a "
                       "little while.")

# what each asset class is, in plain words (asset_classes.CLASSES)
CLASS_WORDS = {
    "Stocks": "small pieces of companies. Their value moves up and down the most.",
    "Bonds": "loans to governments or companies that pay interest. Usually steadier than "
             "stocks.",
    "Cash": "money held in the account or in a savings-like fund. Steady, and grows slowly.",
    "Other": "anything that isn't one of those, like real estate funds or gold.",
}
# the route, in order (context_card.STAGES' keys), and the line for each
ROUTE = (("learn", "Learn the basics"), ("invest", "Get ready and start investing"),
         ("investing", "Investing, with a plan to follow"))
STAGE_LINES = {
    "learn": "They're at the first step: learning the basics before they start investing.",
    "invest": "They've learned the basics and are getting ready to start investing.",
    "investing": "They're investing, and their own holdings are in Northwend.",
}
GOAL_WORDS = {   # plans.GOAL_TYPES, as a line
    "Retirement": "Retirement",
    "Buy a home": "Buying a home",
    "Pay for education": "Paying for education",
    "Build long-term wealth": "Building long-term wealth",
    "Big purchase": "A big purchase",
    "Other": "A goal of their own",
}


# ---- small helpers ---------------------------------------------------------- #
def _iso(now: datetime) -> str:
    if now.tzinfo is None:   # a plain datetime is UTC already
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


def token_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def well_formed(token) -> bool:
    """Whether `token` could be one token_urlsafe made (nothing else is
    looked up - a long or odd string is simply not a link)."""
    return isinstance(token, str) and bool(_TOKEN_RE.match(token))


def link(base: str, token: str) -> str:
    """The full link for a token, on this app's address."""
    base = (base or "").split("?")[0].split("#")[0]
    if base and not base.endswith("/"):
        base += "/"
    return f"{base}?{QUERY}={token}"


def first_name(display_name) -> str | None:
    """The first word of the name they asked to be called, if it's a name:
    letters (and ' or -) only, up to NAME_MAX. Never a login or an email."""
    word = (str(display_name or "").split() or [""])[0].strip(".,;:")
    if not word or len(word) > NAME_MAX or not word[0].isalpha():
        return None
    if not all(ch.isalpha() or ch in "'-" for ch in word):
        return None
    return word


# ---- who may share ----------------------------------------------------------- #
def eligible(conn, user_id: int) -> bool:
    """Whether this account may have share links: not an admin's login, not
    an advisor's client (client mode - their plan is the advisor's)."""
    import admin
    import advising
    if not conn.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
        return False
    return not admin.is_admin(conn, user_id) and advising.advisor_of(conn, user_id) is None


def may_create(conn, user_id: int, by: int) -> bool:
    """The signed-in owner, in their own account, and an eligible one."""
    return by == user_id and eligible(conn, user_id)


# ---- the owner's links ------------------------------------------------------- #
def active(conn, user_id: int, *, now: datetime | None = None) -> list[dict]:
    """The account's working links, newest first: {"id", "created_at",
    "expires_at", "show_name", "opens", "last_opened_on"} - never the hash."""
    rows = conn.execute(
        "SELECT id, created_at, expires_at, show_name, opens, last_opened_on FROM share_links "
        "WHERE user_id = ? AND expires_at > ? ORDER BY created_at DESC, id DESC",
        (user_id, _iso(_now(now)))).fetchall()
    return [{**dict(r), "show_name": bool(r["show_name"])} for r in rows]


def create(conn, user_id: int, *, by: int, days: int = DEFAULT_DAYS, show_name: bool = False,
           now: datetime | None = None) -> str:
    """A new link's token (shown once; only its hash is kept). Raises
    PermissionError unless the signed-in owner makes it for their own
    eligible account, ValueError for a length not in DAYS_CHOICES or when
    MAX_ACTIVE links already work."""
    if not may_create(conn, user_id, by):
        raise PermissionError("only the account's owner can make a share link")
    if days not in DAYS_CHOICES:
        raise ValueError("a share link works for one of DAYS_CHOICES")
    now = _now(now)
    # ended links of theirs go first (tidy.py does it nightly too)
    conn.execute("DELETE FROM share_links WHERE user_id = ? AND expires_at <= ?",
                 (user_id, _iso(now)))
    if len(active(conn, user_id, now=now)) >= MAX_ACTIVE:
        conn.commit()
        raise ValueError(TOO_MANY)
    token = secrets.token_urlsafe(TOKEN_BYTES)
    conn.execute("INSERT INTO share_links (user_id, token_hash, created_at, expires_at, "
                 "show_name, opens) VALUES (?, ?, ?, ?, ?, 0)",
                 (user_id, token_hash(token), _iso(now), _iso(now + timedelta(days=days)),
                  1 if show_name else 0))
    conn.commit()
    return token


def revoke(conn, user_id: int, link_id: int) -> bool:
    """Turn one of the account's links off (it's deleted). False if it isn't theirs."""
    cur = conn.execute("DELETE FROM share_links WHERE id = ? AND user_id = ?",
                       (link_id, user_id))
    conn.commit()
    return (cur.rowcount or 0) > 0


def revoke_all(conn, user_id: int) -> int:
    cur = conn.execute("DELETE FROM share_links WHERE user_id = ?", (user_id,))
    conn.commit()
    return max(cur.rowcount or 0, 0)


def prune(conn, *, now: datetime | None = None) -> int:
    """Delete every ended link (tidy.py, nightly). How many went."""
    cur = conn.execute("DELETE FROM share_links WHERE expires_at <= ?", (_iso(_now(now)),))
    conn.commit()
    return max(cur.rowcount or 0, 0)


# ---- opening a link ---------------------------------------------------------- #
def take(conn, ip: str | None, *, now: datetime | None = None) -> str | None:
    """Count one opened link from `ip`, or say calmly why not now (and count
    nothing). The same for every link, working or not."""
    import auth
    now = _now(now)
    stamp, hour_ago = auth._utc(now), auth._utc(now - timedelta(hours=1))
    key = KEY_PREFIX + auth._address_key(ip)
    conn.execute("DELETE FROM signups WHERE created_at < ?",
                 (auth._utc(now - timedelta(days=1)),))
    reason = None
    if key != KEY_PREFIX:
        here = conn.execute("SELECT COUNT(*) AS n FROM signups WHERE address_key = ? "
                            "AND created_at >= ?", (key, hour_ago)).fetchone()["n"]
        if here >= PER_ADDRESS_PER_HOUR:
            reason = TOO_MANY_FROM_HERE
    if reason is None:
        everyone = conn.execute("SELECT COUNT(*) AS n FROM signups WHERE address_key LIKE ? "
                                "AND created_at >= ?", (KEY_PREFIX + "%", hour_ago)
                                ).fetchone()["n"]
        if everyone >= PER_HOUR:
            reason = TOO_MANY_EVERYWHERE
    if reason is None:
        conn.execute("INSERT INTO signups (address_key, created_at, ok) VALUES (?, ?, 0)",
                     (key, stamp))
    conn.commit()
    return reason


def lookup(conn, token, *, now: datetime | None = None) -> dict | None:
    """{"id", "user_id", "show_name"} for a working link, else None - for an
    unknown, malformed, expired or turned-off link, or one whose account
    can't share any more, alike."""
    if not well_formed(token):
        return None
    row = conn.execute("SELECT id, user_id, show_name FROM share_links WHERE token_hash = ? "
                       "AND expires_at > ?", (token_hash(token), _iso(_now(now)))).fetchone()
    if row is None or not eligible(conn, row["user_id"]):
        return None
    return {"id": row["id"], "user_id": row["user_id"], "show_name": bool(row["show_name"])}


def note_open(conn, user_id: int, link_id: int, *, today: date | None = None) -> None:
    """One more visit, and the day - for the owner's list only."""
    conn.execute("UPDATE share_links SET opens = opens + 1, last_opened_on = ? "
                 "WHERE id = ? AND user_id = ?",
                 ((today or datetime.now(timezone.utc).date()).isoformat(), link_id, user_id))
    conn.commit()


# ---- what the page shows ----------------------------------------------------- #
def _whole(v) -> int:
    try:
        return max(0, min(100, int(round(float(v)))))
    except (TypeError, ValueError):
        return 0


def _plan_parts(conn, user_id: int, today: date) -> dict:
    """The plan's goal kind, its timeline bucket and target mix, and the band."""
    import context_card
    import plans
    import prefs
    from asset_classes import CLASSES
    plan = plans.get_plan(conn, user_id) or {}
    out: dict = {}
    if plan.get("goal_type") in GOAL_WORDS:
        out["goal"] = plan["goal_type"]
    if plan.get("target_date"):
        try:
            months = plans.months_until(plan["target_date"], today)
        except ValueError:
            months = None
        if months is not None and months > 0:
            out["timeline"] = context_card.timeline_of(months / 12)
    target = [[k, _whole((plan.get("target_alloc") or {}).get(k))] for k in CLASSES]
    target = [[k, v] for k, v in target if v > 0]
    if target:
        out["target"] = target
        band = prefs.load(conn, user_id).get("drift_threshold")
        out["band"] = _whole(band) if band not in (None, "") and _whole(band) > 0 else DEFAULT_BAND
    return out


def page(conn, user_id: int, *, show_name: bool = False, today: date | None = None) -> dict:
    """Everything the share page shows, from current data - only known words
    and whole percents (clean_page): {"name", "stage", "mix", "goals",
    "timeline", "target", "band"}, each present only when there's one."""
    import intros
    today = today or datetime.now(timezone.utc).date()
    found = dict(intros.outline(conn, user_id))   # mix, goals, timeline, stage
    planned = _plan_parts(conn, user_id, today)
    if planned.get("goal"):   # the plan's goal comes first, with its own timeline
        found["goals"] = [planned["goal"]]
        found["timeline"] = planned.get("timeline") or found.get("timeline")
    for k in ("target", "band"):
        if k in planned:
            found[k] = planned[k]
    if show_name:
        found["name"] = owner_first_name(conn, user_id)
    return clean_page(found)


def owner_first_name(conn, user_id: int) -> str | None:
    """first_name() of the name the account asked to be called, if any."""
    row = conn.execute("SELECT display_name FROM users WHERE id = ?", (user_id,)).fetchone()
    return first_name(row["display_name"] if row else None)


def clean_page(raw) -> dict:
    """Only what the page may hold, whatever came in: anything else - a
    figure, a ticker, a name that isn't a first name - is dropped."""
    import advisor
    import context_card
    from asset_classes import CLASSES
    raw = raw if isinstance(raw, dict) else {}
    out: dict = {}

    def mix(pairs):
        kept = []
        for pair in pairs or []:
            if (isinstance(pair, (list, tuple)) and len(pair) == 2 and pair[0] in CLASSES
                    and isinstance(pair[1], int) and not isinstance(pair[1], bool)
                    and 0 < pair[1] <= 100 and pair[0] not in {k for k, _ in kept}):
                kept.append([pair[0], pair[1]])
        return kept

    if mix(raw.get("mix")):
        out["mix"] = mix(raw.get("mix"))
    goals = [g for g in raw.get("goals") or []
             if g in GOAL_WORDS or g in advisor.GOAL_OPTIONS]
    if goals:
        out["goals"] = list(dict.fromkeys(goals))
    if raw.get("timeline") in {label for label, _ in context_card.TIMELINES}:
        out["timeline"] = raw["timeline"]
    if raw.get("stage") in STAGE_LINES:
        out["stage"] = raw["stage"]
    if mix(raw.get("target")):
        out["target"] = mix(raw.get("target"))
        band = raw.get("band")
        if isinstance(band, int) and not isinstance(band, bool) and 0 < band <= 100:
            out["band"] = band
    name = first_name(raw.get("name")) if raw.get("name") else None
    if name:
        out["name"] = name
    return out


def _goal_words(g: str) -> str:
    return GOAL_WORDS.get(g, g)


def _mix_line(pairs) -> str:
    return ", ".join(f"{k} {v}%" for k, v in pairs)


def lines(raw) -> list[tuple[str, str, str]]:
    """[(part, heading, text)] in the page's order - what the page draws.
    Checked: never anything that reads as money."""
    import recap
    p = clean_page(raw)
    out = []
    if p.get("stage"):
        out.append(("stage", "Where they are", STAGE_LINES[p["stage"]]))
    if p.get("goals"):
        goal = " and ".join(_goal_words(g) for g in p["goals"])
        when = f", in {p['timeline']}" if p.get("timeline") else ""
        out.append(("goal", "What they're investing for", f"{goal}{when}."))
    elif p.get("timeline"):
        out.append(("goal", "What they're investing for",
                    f"A goal they'd like to reach in {p['timeline']}."))
    if p.get("mix"):
        out.append(("mix", "How their money is spread today", _mix_line(p["mix"]) + "."))
    if p.get("target"):
        text = f"The mix they're aiming for: {_mix_line(p['target'])}."
        if p.get("band"):
            text += (f" If any part moves more than {p['band']} percentage points away from its "
                     "target, they look at it again and decide whether to move it back.")
        out.append(("target", "Their plan", text))
    if any(recap.has_money(t) for _, _, t in out):
        raise ValueError("a share page never carries an amount")
    return out


def classes_shown(raw) -> list[str]:
    """The asset classes the page mentions, for its short glossary."""
    p = clean_page(raw)
    seen = [k for k, _ in (p.get("mix") or []) + (p.get("target") or [])]
    return list(dict.fromkeys(seen))


def title(raw) -> str:
    p = clean_page(raw)
    return PAGE_TITLE_NAMED.format(name=p["name"]) if p.get("name") else PAGE_TITLE


def all_text() -> str:
    """Every fixed word the feature shows (for the tests' word checks)."""
    parts = [OWNER_TITLE, OWNER_INTRO, OWNER_NEVER, OWNER_EXPIRY, SHOWN_ONCE, NOT_ALLOWED,
             TOO_MANY, PAGE_TITLE, PAGE_TITLE_NAMED, PAGE_INTRO, PAGE_EMPTY, LEARN_TITLE,
             LEARN_TEXT, LEARN_BUTTON, FOOTER, INACTIVE_TITLE, INACTIVE_TEXT,
             TOO_MANY_FROM_HERE, TOO_MANY_EVERYWHERE, *CLASS_WORDS.values(),
             *STAGE_LINES.values(), *GOAL_WORDS.values(), *(t for _, t in ROUTE)]
    return "\n".join(parts)
