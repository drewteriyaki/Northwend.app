"""How the app is used (direction item 12; the revised Privacy Policy's
"product analytics"): a small event log kept in Northwend's own database -
no new service, no script, no cookie, no third party.

Flag `analytics`, off unless set. It may only be switched on after the
revised Privacy Policy (docs/legal/next/privacy-policy.md) is published with
its new date - flags.py and docs/RUNBOOK.md say so.

What one event is (table analytics_events): when, a random id, the event's
name from EVENTS, the page from PAGES, and props - a few short words from
PROPS, nothing else. clean() is the validator: an unknown event is dropped;
a page not in PAGES is left out; a prop whose key isn't the event's own, or
whose value isn't one of that key's fixed words, is dropped. So an amount, a
ticker, an account name, an email, a name or anything typed can never be
stored, whatever a caller passes.

Who: a random id (PREF_ID, 16 hex characters) kept in the login's own
settings, made the first time an event is recorded. Never the user id - the
table has no column for one. Turning on "Don't use my data to improve the
app" (feature_counts.PREF_OFF, the same switch as the feature counts) deletes
the id's events and the id itself (forget); turning it off again later starts
a new id, so the old and new can't be joined. Deleting the account does the
same (on_account_deleted, called by admin.delete_account before the settings
go). The person's own events are in their Export everything (own_events).

Never recorded (allowed()): the flag is off; the person turned the switch on;
the browser sends Global Privacy Control (Sec-GPC: 1) or Do Not Track (DNT:
1); an admin; an advisor inside a client's account (nothing about the
client); nobody signed in. Kept 12 months (KEEP_DAYS, tidy.py). Admin sees
totals only, for groups of feature_counts.MIN_GROUP or more people
(summary) - never one id's events, and nothing by advisor: events carry no
advisor, client or role, so they can't be used to choose, rank or suggest
an advisor.

record() never raises: analytics must never break a page.
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timedelta, timezone

import feature_counts

FLAG = "analytics"
PREF_ID = "analytics_id"            # the random id, in the login's own settings
PREF_OFF = feature_counts.PREF_OFF  # one switch for feature counts and analytics
KEEP_DAYS = 365                     # 12 months (the draft policy's section 7)
MIN_GROUP = feature_counts.MIN_GROUP
SUMMARY_DAYS = 30

SWITCH_LABEL = "Don't use my data to improve the app"
SWITCH_LABEL_BEFORE = "Leave me out of feature counts"   # the published policy's words
SWITCH_HELP = ("Turn this on and no app-use events are recorded for you, the ones already "
               "recorded are deleted, and you're left out of every feature count.")

# the pages an event may name (dashboard's PAGES - internal names, never a ticker)
PAGES = ("Clients", "Get started", "Dashboard", "Plan", "Advisor notes", "Watchlist",
         "Activity", "Income", "News", "AI Assistant", "Life", "Account", "What's new",
         "About", "Ticker", "Admin", "Advisor preview", "Find a guide")

# each prop key -> its only allowed values
PROPS = {
    "device": ("phone", "tablet", "computer"),
    "method": ("csv", "paste", "screenshot", "manual", "percent", "example"),
    "kind": ("menu_401k", "factsheet"),
}
# event -> the prop keys it may carry (device on every one)
EVENTS = {
    "page_opened": (),
    "holdings_added": ("method",),
    "walk_finished": (),
    "decoder_used": ("kind",),
    "first_steps_done": (),
    "first_steps_skipped": (),
    "ask_question": (),           # a count only - never the question
    "challenge_started": (),
    "drill_done": (),
}
_ID = re.compile(r"[0-9a-f]{16}")


def clean(event, page=None, props=None):
    """(event, page or None, props as JSON text) with everything not on the
    allow-lists dropped, or None for an event that isn't in EVENTS."""
    if not isinstance(event, str) or event not in EVENTS:
        return None
    page = page if isinstance(page, str) and page in PAGES else None
    keep = {}
    if isinstance(props, dict):
        allowed = set(EVENTS[event]) | {"device"}
        for k, v in props.items():
            if k in allowed and isinstance(v, str) and v in PROPS.get(k, ()):
                keep[k] = v
    return event, page, json.dumps(keep, sort_keys=True) if keep else None


def device_of(headers) -> str | None:
    """phone, tablet or computer from the browser's User-Agent - None when
    there isn't one. Only the kind is kept, never the browser string."""
    ua = _header(headers, "User-Agent")
    if not ua:
        return None
    if re.search(r"iPad|Tablet|Android(?!.*Mobile)", ua):
        return "tablet"
    if re.search(r"Mobi|iPhone|Android", ua):
        return "phone"
    return "computer"


def _header(headers, name: str) -> str:
    if not headers:
        return ""
    try:
        for k, v in dict(headers).items():
            if str(k).lower() == name.lower():
                return str(v or "").strip()
    except Exception:  # noqa: BLE001 - odd headers mean "not sent"
        return ""
    return ""


def browser_says_no(headers) -> bool:
    """Global Privacy Control (Sec-GPC: 1) or Do Not Track (DNT: 1): treated
    as "don't use my data to improve the app" for the visit."""
    return _header(headers, "Sec-GPC") == "1" or _header(headers, "DNT") == "1"


def flag_on() -> bool:
    import flags
    return flags.on("analytics")


def switch_label() -> str:
    """The Account switch's name. The published Privacy Policy and About page
    still call it SWITCH_LABEL_BEFORE, so it keeps that name until the flag
    is on - which itself waits for the revised policy (flags.py)."""
    return SWITCH_LABEL if flag_on() else SWITCH_LABEL_BEFORE


def allowed(*, prefs, headers=None, signed_in=True, is_admin=False,
            in_clients_account=False, flag=None) -> bool:
    """Whether an event may be recorded now (the module's "Never recorded")."""
    if not (flag_on() if flag is None else flag):
        return False
    if not signed_in or is_admin or in_clients_account:
        return False
    if feature_counts.left_out(prefs if isinstance(prefs, dict) else {}):
        return False
    return not browser_says_no(headers)


def id_of(p) -> str | None:
    """The settings' analytics id, if it's a well-formed one."""
    v = (p or {}).get(PREF_ID) if isinstance(p, dict) else None
    return v if isinstance(v, str) and _ID.fullmatch(v) else None


def new_id() -> str:
    return secrets.token_hex(8)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def record(conn, anon_id, event, page=None, props=None, *, now=None) -> bool:
    """One INSERT, after clean(). True if a row went in; never raises."""
    try:
        got = clean(event, page, props)
        if got is None or not isinstance(anon_id, str) or not _ID.fullmatch(anon_id):
            return False
        conn.execute("INSERT INTO analytics_events (at, anon_id, event, page, props) "
                     "VALUES (?, ?, ?, ?, ?)",
                     (_iso(now or datetime.now(timezone.utc)), anon_id, *got))
        conn.commit()
        return True
    except Exception:  # noqa: BLE001 - analytics never breaks a page
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        return False


def forget(conn, p) -> int:
    """Delete every event under the settings' id and take the id out of `p`
    (the caller saves `p`). How many events went."""
    anon = id_of(p)
    if isinstance(p, dict):
        p.pop(PREF_ID, None)
    if not anon:
        return 0
    cur = conn.execute("DELETE FROM analytics_events WHERE anon_id = ?", (anon,))
    return max(cur.rowcount or 0, 0)


def on_account_deleted(conn, user_id: int) -> int:
    """admin.delete_account, inside its transaction and before the settings
    go: the account's events, by the id its settings hold."""
    row = conn.execute("SELECT data FROM user_prefs WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        return 0
    try:
        p = json.loads(row["data"])
    except (TypeError, ValueError):
        return 0
    return forget(conn, p if isinstance(p, dict) else {})


def own_events(conn, p) -> list[dict]:
    """The person's own events for Export everything (export.collect)."""
    anon = id_of(p)
    if not anon:
        return []
    return [{"at": r["at"], "event": r["event"], "page": r["page"] or "",
             "details": r["props"] or ""}
            for r in conn.execute("SELECT at, event, page, props FROM analytics_events "
                                  "WHERE anon_id = ? ORDER BY id", (anon,))]


def prune(conn, *, now: datetime | None = None) -> int:
    """Delete events older than KEEP_DAYS (tidy.py, nightly). How many went."""
    cutoff = _iso((now or datetime.now(timezone.utc)) - timedelta(days=KEEP_DAYS))
    cur = conn.execute("DELETE FROM analytics_events WHERE at < ?", (cutoff,))
    conn.commit()
    return max(cur.rowcount or 0, 0)


def summary(conn, *, now: datetime | None = None, days: int = SUMMARY_DAYS) -> dict:
    """Admin's "App use (last 30 days)", totals only: {"events": [{"event",
    "times", "people"}], "details": [{"event", "detail", "people"}], "pages":
    [{"page", "times", "people"}], "days": [{"day", "people"}]} - each row
    only when at least MIN_GROUP different ids are in it. Never a list of one
    id's events; nothing by advisor (events hold none)."""
    since = _iso((now or datetime.now(timezone.utc)) - timedelta(days=days))
    q = lambda sql: conn.execute(sql, (since, MIN_GROUP)).fetchall()  # noqa: E731
    events = q("SELECT event, COUNT(*) AS times, COUNT(DISTINCT anon_id) AS people "
               "FROM analytics_events WHERE at >= ? GROUP BY event "
               "HAVING COUNT(DISTINCT anon_id) >= ? ORDER BY event")
    details = q("SELECT event, props, COUNT(DISTINCT anon_id) AS people "
                "FROM analytics_events WHERE at >= ? AND props IS NOT NULL "
                "GROUP BY event, props HAVING COUNT(DISTINCT anon_id) >= ? "
                "ORDER BY event, props")
    pages = q("SELECT page, COUNT(*) AS times, COUNT(DISTINCT anon_id) AS people "
              "FROM analytics_events WHERE at >= ? AND event = 'page_opened' "
              "AND page IS NOT NULL GROUP BY page "
              "HAVING COUNT(DISTINCT anon_id) >= ? ORDER BY page")
    per_day = q("SELECT SUBSTR(at, 1, 10) AS day, COUNT(DISTINCT anon_id) AS people "
                "FROM analytics_events WHERE at >= ? GROUP BY SUBSTR(at, 1, 10) "
                "HAVING COUNT(DISTINCT anon_id) >= ? ORDER BY day")

    def words(props):
        try:
            d = json.loads(props) if props else {}
        except ValueError:
            d = {}
        return ", ".join(f"{k} {v}" for k, v in sorted(d.items()))

    return {"events": [{"event": r["event"], "times": r["times"], "people": r["people"]}
                       for r in events],
            "details": [{"event": r["event"], "detail": words(r["props"]),
                         "people": r["people"]} for r in details],
            "pages": [{"page": r["page"], "times": r["times"], "people": r["people"]}
                      for r in pages],
            "days": [{"day": r["day"], "people": r["people"]} for r in per_day]}
