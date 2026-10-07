#!/usr/bin/env python3
"""Trail Conditions (ROADMAP "The weekly rhythm", Phase C; flag
`trail_conditions`): a short, opt-in Monday email. Almost every week it
says only CALM. Its words change only when something changed, and only
from the fixed templates below:

- a storm: the person's holdings are a storm's depth below their recent
  high (storms.weather, the same check as Home's storm note) - said as a
  past fact, with no figure;
- a season has begun (seasons.season_id) and its card hasn't been opened
  or put away - once per season (flag `seasons`);
- the Monthly Walk is waiting on Home (checkin.due) - once a month (flag
  `walk`);
- a situation on the readiness map not rehearsed yet (drills.py) - at most
  once every GAP_EVERY_WEEKS weeks, and never once all are rehearsed (flag
  `drills`).

At most MAX_LINES of those. Never a figure about the person (no amount,
percentage, ticker, fund or account name), never a forecast, never
"should", "best" or "recommend", never urgency. Education and reminders,
never advice (LEGAL_GATES.md section 6).

Opt-in only (Account > Trail Conditions, off by default; the login's own
switch - never an advisor in a client's account). Turning it on keeps the
time of consent (PREF_CONSENT); turning it off, from Account or the
one-click link in every email (unsubscribe.py, kind "trail"), stops it at
once and drops that time. An advisor's client can turn it on for
themselves: it's their own consent, and nothing in it is about their
money or their advisor.

Kept in the person's own settings (prefs.py), never anywhere else:
  PREF_ON       True while they want it
  PREF_CONSENT  when they turned it on (UTC, ISO)
  PREF_SENT     the ISO week it was last sent ("2026-W41") - never twice a week
  PREF_SEASON   the season last mentioned ("2026-enrollment")
  PREF_WALK     the month the walk was last mentioned ("2026-10")
  PREF_GAP      the ISO week the readiness map was last mentioned

Run on Mondays by .github/workflows/scheduled-sync.yml:

  python trail_conditions.py --db "$DATABASE_URL" --app-url https://go.northwend.app/

Sends nothing while the flag is off, while mailer.POSTAL_ADDRESS is empty
(CAN-SPAM: every email carries the postal address and the unsubscribe
link), without --app-url, or when email isn't set up; MAIL_DRY_RUN=1 logs
instead of sending (mailer.py); --dry-run counts who would get it.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import checkin
import drills
import flags
import mailer
import perf
import prefs
import seasons
import storms
import unsubscribe
from portfolio import DEFAULT_DB, connect

FLAG = "trail_conditions"
PREF_ON = "trail_conditions"
PREF_CONSENT = "trail_conditions_consent"
PREF_SENT = "trail_conditions_sent"
PREF_SEASON = "trail_conditions_season"
PREF_WALK = "trail_conditions_walk"
PREF_GAP = "trail_conditions_gap"
KEYS = (PREF_ON, PREF_CONSENT, PREF_SENT, PREF_SEASON, PREF_WALK, PREF_GAP)

MAX_LINES = 3
GAP_EVERY_WEEKS = 4

# ---- the words: fixed templates only ----------------------------------------- #
SWITCH_LABEL = "Trail Conditions"
SWITCH_HELP = ("A short Monday note. Most weeks it says all is calm. It never has amounts, "
               "holdings or anything else about your money, and you can stop it at any time.")
SUBJECT_CALM = "Trail Conditions: calm"
SUBJECT_NEWS = "Trail Conditions this week"
CALM = "Calm on the trail - nothing to do."
STORM = ("Markets have fallen a long way recently. Home has a calm note on what past storms "
         "have looked like.")
SEASON = {key: f"A new season has begun in the app - {title}. It's on Home whenever suits you."
          for key, _months, title, *_ in seasons.SEASONS}
WALK = "Your monthly walk is waiting on Home, whenever suits you."
GAP = "One situation on your readiness map is waiting, whenever suits you."
OUTRO = ("Trail Conditions never suggests buying or selling anything. To stop it, turn it off "
         "on the Account page, or use the link below.")


def all_lines() -> list[str]:
    """Every sentence an email can carry (the wording tests)."""
    return [SUBJECT_CALM, SUBJECT_NEWS, CALM, STORM, *SEASON.values(), WALK, GAP, OUTRO,
            SWITCH_LABEL, SWITCH_HELP]


# ---- the switch ---------------------------------------------------------------- #
def is_on(p: dict | None) -> bool:
    return bool((p or {}).get(PREF_ON))


def set_on(p: dict, on: bool, now: datetime | None = None) -> dict:
    """Turn it on (keeping when, the consent) or off (dropping that time).
    Turning on when already on keeps the first time. Changes `p`."""
    if on:
        if not is_on(p) or not p.get(PREF_CONSENT):
            p[PREF_CONSENT] = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
        p[PREF_ON] = True
    else:
        p[PREF_ON] = False
        p.pop(PREF_CONSENT, None)
    return p


# ---- what this week says ------------------------------------------------------- #
def _weeks_between(a: str, b: str) -> int | None:
    """Whole weeks from ISO week `a` to `b` ("2026-W41"), or None."""
    try:
        da = date.fromisocalendar(int(a[:4]), int(a[6:]), 1)
        db = date.fromisocalendar(int(b[:4]), int(b[6:]), 1)
    except (TypeError, ValueError):
        return None
    return (db - da).days // 7


def sent_this_week(p: dict | None, today: date) -> bool:
    return (p or {}).get(PREF_SENT) == drills.iso_week(today)


def news(p: dict, today: date, weather: dict | None) -> list[tuple[str, str, str | None]]:
    """What changed, as [(kind, line, what to remember or None)], at most
    MAX_LINES, in this order: storm, season, walk, readiness map. Empty
    means a calm week. Reads `p`, changes nothing."""
    out = []
    if weather and weather.get("level") == "storm":
        out.append(("storm", STORM, None))
    if flags.on("seasons"):
        sid = seasons.season_id(today)
        if (sid and p.get(PREF_SEASON) != sid
                and seasons.status_of(p.get(seasons.PREF), sid) is None):
            out.append(("season", SEASON[seasons.season_of(today)], sid))
    if flags.on("walk"):
        month = checkin.month_of(today)
        if p.get(PREF_WALK) != month and checkin.due(p, today):
            out.append(("walk", WALK, month))
    if flags.on("drills") and drills.count(p) < len(drills.KEYS):
        week, last = drills.iso_week(today), p.get(PREF_GAP)
        gone = _weeks_between(last, week) if last else None
        if not last or gone is None or gone >= GAP_EVERY_WEEKS:
            out.append(("gap", GAP, week))
    return out[:MAX_LINES]


def lines_of(items) -> list[str]:
    return [line for _k, line, _m in items] or [CALM]


def remember(p: dict, items, today: date) -> dict:
    """After a send: the week, and what was mentioned. Changes `p`."""
    p[PREF_SENT] = drills.iso_week(today)
    keys = {"season": PREF_SEASON, "walk": PREF_WALK, "gap": PREF_GAP}
    for kind, _line, mark in items:
        if kind in keys:
            p[keys[kind]] = mark
    return p


def weather_for(conn, user_id: int, today: date) -> dict | None:
    """storms.weather() for the account's own holdings - the storm note's
    check - or None (calm, or no holdings)."""
    since = (today - timedelta(days=storms.WINDOW_DAYS)).isoformat()
    try:
        return storms.weather(perf.daily_values(conn, perf.basis(conn, user_id), since), today)
    except Exception:  # noqa: BLE001 - one account's history must never stop the job
        return None


# ---- sending ------------------------------------------------------------------- #
def recipients(conn) -> list[dict]:
    """Non-advisor accounts with a confirmed email who turned it on:
    [{"id", "email"}]. (The settings are read again in run(); the LIKE
    only narrows which ones.)"""
    return [dict(r) for r in conn.execute(
        "SELECT u.id, u.email FROM users u JOIN user_prefs p ON p.user_id = u.id "
        "WHERE COALESCE(u.is_advisor, 0) = 0 AND u.email IS NOT NULL AND u.email != '' "
        "AND u.email_verified_at IS NOT NULL AND p.data LIKE ? ORDER BY u.id",
        (f'%"{PREF_ON}": true%',))]


def email(to: str, lines: list[str], link: str, unsub: str, address: str) -> bool:
    """The email itself: the week's lines, the outro, the one-click link and
    the postal address. Nothing about the person's money."""
    subject = SUBJECT_CALM if lines == [CALM] else SUBJECT_NEWS
    text = ("\n\n".join(lines) + f"\n\nOpen Northwend: {link}\n\n{OUTRO}\n"
            f"\n{mailer.UNSUBSCRIBE_LINE}: {unsub}\n\nNorthwend, {address}\n")
    return mailer.send(to, subject, text,
                       mailer._html([*lines, OUTRO], ("Open Northwend", link),
                                    unsubscribe=unsub, address=address),
                       headers=mailer.unsubscribe_headers(unsub))


def run(conn, app_url: str, today: date, *, send=email, dry_run: bool = False,
        address: str | None = None) -> dict:
    """Send this week's note to everyone who asked for it and hasn't had it
    this week. Nothing at all while the flag is off or the postal address
    (mailer.POSTAL_ADDRESS, or `address`) is empty."""
    address = (mailer.POSTAL_ADDRESS if address is None else address).strip()
    link = app_url.rstrip("/") + "/?page=dashboard"
    done = {"sent": 0, "calm": 0, "already": 0, "failed": 0, "would_send": 0}
    if not flags.on(FLAG) or not address:
        return done
    for r in recipients(conn):
        p = prefs.load(conn, r["id"])
        if not is_on(p):
            continue
        if sent_this_week(p, today):
            done["already"] += 1
            continue
        items = news(p, today, weather_for(conn, r["id"], today))
        if dry_run:
            done["would_send"] += 1
            continue
        if done["sent"] or done["failed"]:
            time.sleep(0.6)   # the email service takes a couple a second
        unsub = unsubscribe.link(app_url, unsubscribe.new_token(conn, r["id"], "trail",
                                                                r["email"]))
        if send(r["email"], lines_of(items), link, unsub, address):
            prefs.save(conn, r["id"], remember(p, items, today))
            done["sent"] += 1
            done["calm"] += not items
        else:
            done["failed"] += 1
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Send this week's Trail Conditions to those who "
                                             "asked for it.")
    ap.add_argument("--db", default=os.environ.get("PORTFOLIO_DB") or DEFAULT_DB)
    ap.add_argument("--app-url", default=os.environ.get("APP_URL") or "",
                    help="the app's address, for the link in the email")
    ap.add_argument("--dry-run", action="store_true",
                    help="count who would get it; send and record nothing")
    args = ap.parse_args(argv)
    if not flags.on(FLAG):
        print("Skipped: Trail Conditions isn't turned on here (NORTHWEND_FLAGS).")
        return 0
    if not mailer.POSTAL_ADDRESS.strip():
        print("Skipped: no postal address yet (mailer.POSTAL_ADDRESS) - every Trail "
              "Conditions email must carry one, so none are sent.")
        return 0
    if not args.app_url:
        print("Skipped: no --app-url (or APP_URL) to link to.")
        return 0
    if mailer.status() == "off" and not args.dry_run:
        print("Skipped: email isn't set up (RESEND_API_KEY).")
        return 0
    conn = connect(args.db)
    try:
        done = run(conn, args.app_url, date.today(), dry_run=args.dry_run)
    finally:
        conn.close()
    print(", ".join(f"{k} {v}" for k, v in done.items()))
    return 1 if done["failed"] and not done["sent"] else 0


if __name__ == "__main__":
    sys.exit(main())
