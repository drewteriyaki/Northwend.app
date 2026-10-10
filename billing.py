"""Paid advisor seats (direction item 10; flag `billing` + gate L1a). Standard
library only, no Streamlit: the page is views/billing.py, and the nightly
reconciliation runs from the command line (`python billing.py --sync`).

What a seat is: the advisor workspace, sold as one flat fee a month or a year.
Never a fee per client, per introduction or by usage (direction section 7) -
nothing here counts or reads anything about anyone else's account; a test
reads this file and fails if it ever does.

Billing by pull (ADR 0004; PLAN step 6, option A). Streamlit can't receive a
webhook, and a second service just for one would cost money and be a second
way in. So Northwend never takes a status from the browser or a link:
- Subscribe makes a Stripe Checkout Session (hosted page, subscription mode,
  client_reference_id = the login's id) and keeps its id in the seat's row
  (start_checkout). Stripe's page takes the card; Northwend never sees it.
- Back in the app (?billing=done), or on any later look at Your seat, the
  kept session is read from Stripe's API on the server and checked - it must
  name this login - before the seat changes (verify_checkout). The URL itself
  carries nothing that's trusted.
- Every night `python billing.py --sync` reads each known subscription from
  Stripe and updates its row (sync_all) - cancellations and failed payments
  are seen within a day; the grace days absorb that.
- Manage billing opens Stripe's customer portal (portal_url): change card,
  switch monthly/yearly, cancel.

Founding seats: the first NORTHWEND_FOUNDING_SEATS (default 20) advisors who
ever start a paid seat get a founding place, numbered 1, 2, 3 ... in
app_state's FOUNDING_STATE row - places are never handed out twice, even after
a seat ends or an account is deleted. A founding seat keeps its price while it
continues without a break (status active, trialing or past_due); once it
ends (canceled, unpaid, expired), the place is lost, and starting again is a
new seat at the standard price. Which Stripe price a checkout uses:
STRIPE_PRICE_MONTHLY / _YEARLY while the advisor would get a founding place,
else STRIPE_PRICE_STANDARD_MONTHLY / _YEARLY when the owner has set them (the
founding ones otherwise). The founding price itself is kept by Stripe: a
subscription keeps its price until it ends.

Lapse (can_write): while the flag is off, every seat is a free beta seat and
nothing is ever closed. On, an advisor may add clients and send proposals,
reports and messages (and use the AI helpers for them) while the seat is
live, or until its grace_until: GRACE_DAYS from the first time the app saw
them with billing on (so beta advisors and newly approved ones have time to
subscribe), or from the day a seat ended. Reading and every export stay open
always; clients are never blocked from their own accounts.

Manual seats (set_manual): before the in-app checkout is used, the owner may
take payment outside the app - a Stripe Payment Link emailed by hand, or an
invoice. Admin > Advisor seats then sets the seat active with a note ("Payment
Link", "Invoice") and a paid-through day, or ended, and may mark it founding
(the next place); each change goes in the admin action log ("seat_manual").
Such a seat shows its status on Your seat with no Subscribe or Manage billing,
Stripe is never asked about it, and past its paid-through day it ends like any
other (end_manual, in the nightly sync): the grace days count from that day.
A seat with a live Stripe subscription can't be set by hand.

Table seats (schema.sql), one row per advisor: Stripe's customer and
subscription ids, the checkout waiting to be checked, plan, status, founding
and its number, started, current period end, grace end, last checked. No card
data, ever. Deleted with the account (admin.ACCOUNT_TABLES) - but
admin.delete_account refuses while a seat is live, so nobody is charged for
an account that's gone; in the advisor's own export (export.OWN).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import flags
import settings

FLAG = "billing"
API = "https://api.stripe.com/v1"
TIMEOUT = 20
# Stripe's subscription statuses that keep a seat working without a break
# (past_due: a payment failed and Stripe is still retrying it)
LIVE = ("active", "trialing", "past_due")
# a seat row before any subscription
NONE = "none"
PLANS = ("monthly", "yearly")
INTERVAL_PLAN = {"month": "monthly", "year": "yearly"}
FOUNDING_STATE = "founding_places_given"   # app_state's row: places handed out, ever
DEFAULT_FOUNDING_SEATS = 20
DEFAULT_GRACE_DAYS = 14
DEFAULT_PRICES = "79/790"   # what the founding seat costs, for the page (USD a month / a year)
RETURN_PARAM = "billing"    # ?billing=done / ?billing=cancel on the way back from Stripe

# ---- the words (plain and literal: the seat is software) ---------------------- #
TITLE = "Your seat"
WHAT_IT_IS = ("A seat is the Northwend workspace you use with your own clients: your client "
              "list, meeting prep, proposals, progress reports, notes and records. One flat "
              "fee - never per client.")
NOT_INCLUDED = ("It doesn't include a directory listing, introductions or leads.")
FOUNDING_KEPT = ("Founding price kept while the seat continues without a break.")
CARD_NOTE = "Stripe takes the payment on its own page. Northwend never sees your card."
BETA_LINE = "Your seat is a free beta seat."
CLOSED_LINE = ("Your seat isn't active, so adding clients and sending proposals, reports and "
               "messages are paused. Everything you have is still here to read and download.")
NOT_REACHED = ("Stripe couldn't be reached just now. Nothing was charged - try again in a "
               "minute.")
NOT_SET_UP = "Seats can't be bought here yet."
MANUAL_RENEW = ("To renew or change it, write to support@northwend.app - we'll send a new "
                "payment link.")


class BillingError(Exception):
    """Stripe refused or couldn't be reached. The message never holds the key."""


# --------------------------------------------------------------------------- #
# settings
# --------------------------------------------------------------------------- #
def on() -> bool:
    """Whether billing is on: the flag and gate L1a (flags.FEATURES)."""
    return flags.on(FLAG)


def secret_key() -> str:
    """The Stripe key (a restricted key, rk_test_... then rk_live_...), or ""."""
    return settings.get("STRIPE_SECRET_KEY", env_file=True)


def _whole(raw: str, default: int) -> int:
    try:
        value = int(raw or default)
    except ValueError:
        return default
    return max(value, 0)


def founding_seats() -> int:
    """How many founding places there are (NORTHWEND_FOUNDING_SEATS, default 20)."""
    return _whole(settings.get("NORTHWEND_FOUNDING_SEATS"), DEFAULT_FOUNDING_SEATS)


def grace_days() -> int:
    """Days the tools stay open with no live seat (NORTHWEND_SEAT_GRACE_DAYS,
    default 14)."""
    return _whole(settings.get("NORTHWEND_SEAT_GRACE_DAYS"), DEFAULT_GRACE_DAYS)


def price_id(plan: str, founding: bool) -> str:
    """The Stripe price for a new checkout: the founding price while the
    advisor would get a founding place, else the standard one if the owner
    set it, else the founding one ("" when not set)."""
    if plan == "monthly":
        founding_id = settings.get("STRIPE_PRICE_MONTHLY")
        standard_id = settings.get("STRIPE_PRICE_STANDARD_MONTHLY")
    elif plan == "yearly":
        founding_id = settings.get("STRIPE_PRICE_YEARLY")
        standard_id = settings.get("STRIPE_PRICE_STANDARD_YEARLY")
    else:
        raise ValueError("Pick monthly or yearly.")
    return founding_id if founding else (standard_id or founding_id)


def configured() -> bool:
    """Whether checkout can work: the key and both founding prices are set."""
    return bool(secret_key() and settings.get("STRIPE_PRICE_MONTHLY")
                and settings.get("STRIPE_PRICE_YEARLY"))


def _amounts(raw: str) -> tuple[str, str]:
    parts = [p.strip().lstrip("$") for p in (raw or "").split("/")]
    if len(parts) != 2 or not all(p.replace(".", "", 1).isdigit() for p in parts):
        parts = DEFAULT_PRICES.split("/")
    return parts[0], parts[1]


def prices(founding: bool) -> dict:
    """{"monthly": "$79", "yearly": "$790"} for the page: NORTHWEND_SEAT_PRICES
    (the founding seat) or NORTHWEND_STANDARD_SEAT_PRICES ("99/990"; the
    founding ones when not set). Shown only - Stripe's page shows the real
    amount before anyone pays."""
    raw = settings.get("NORTHWEND_SEAT_PRICES") or DEFAULT_PRICES
    if not founding:
        raw = settings.get("NORTHWEND_STANDARD_SEAT_PRICES") or raw
    m, y = _amounts(raw)
    return {"monthly": f"${m}", "yearly": f"${y}"}


def price_words(founding: bool) -> str:
    p = prices(founding)
    return f"{p['monthly']} a month, or {p['yearly']} a year"


# --------------------------------------------------------------------------- #
# Stripe, over plain HTTPS (one function; tests replace it)
# --------------------------------------------------------------------------- #
def _encode(params: dict, prefix: str = "") -> list[tuple[str, str]]:
    """Stripe's form encoding: nested dicts and lists as a[b][0]=..."""
    out: list[tuple[str, str]] = []
    for key, value in params.items():
        name = f"{prefix}[{key}]" if prefix else str(key)
        if value is None:
            continue
        if isinstance(value, dict):
            out += _encode(value, name)
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    out += _encode(item, f"{name}[{i}]")
                else:
                    out.append((f"{name}[{i}]", str(item)))
        elif isinstance(value, bool):
            out.append((name, "true" if value else "false"))
        else:
            out.append((name, str(value)))
    return out


def _stripe(method: str, path: str, params: dict | None = None, *,
            idempotency_key: str | None = None) -> dict:
    """One call to Stripe's API; the reply as a dict. Raises BillingError."""
    key = secret_key()
    if not key:
        raise BillingError("STRIPE_SECRET_KEY isn't set.")
    body = urllib.parse.urlencode(_encode(params or {}))
    url = f"{API}/{path.lstrip('/')}"
    data = None
    if method == "GET":
        if body:
            url += "?" + body
    else:
        data = body.encode("utf-8")
    headers = {"Authorization": f"Bearer {key}",
               "Content-Type": "application/x-www-form-urlencoded"}
    if idempotency_key and method == "POST":
        headers["Idempotency-Key"] = idempotency_key
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001 - any body we can't read
            msg = ""
        raise BillingError(f"Stripe said {e.code}" + (f": {msg[:200]}" if msg else "")) from None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        raise BillingError(f"Stripe couldn't be reached ({type(e).__name__}).") from None


# --------------------------------------------------------------------------- #
# the seats table
# --------------------------------------------------------------------------- #
def _stamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _from_epoch(value) -> str | None:
    try:
        return _stamp(datetime.fromtimestamp(int(value), tz=timezone.utc)) if value else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(timezone.utc)


COLUMNS = ("user_id", "stripe_customer", "stripe_subscription", "checkout_session", "plan",
           "status", "founding", "founding_no", "started_at", "current_period_end",
           "grace_until", "last_checked", "manual_note", "created_at")


def seat(conn, user_id: int) -> dict | None:
    """The login's own seat row, or None."""
    row = conn.execute(f"SELECT {', '.join(COLUMNS)} FROM seats WHERE user_id = ?",
                       (user_id,)).fetchone()
    return dict(row) if row else None


def ensure(conn, user_id: int, *, now: datetime | None = None) -> dict:
    """The seat row, made the first time an advisor is seen with billing on -
    status "none", the tools open for grace_days() from then."""
    row = seat(conn, user_id)
    if row:
        return row
    now = _now(now)
    conn.execute("INSERT INTO seats (user_id, status, founding, grace_until, created_at) "
                 "VALUES (?, ?, 0, ?, ?) ON CONFLICT (user_id) DO NOTHING",
                 (user_id, NONE, _stamp(now + timedelta(days=grace_days())), _stamp(now)))
    conn.commit()
    return seat(conn, user_id)


def _update(conn, user_id: int, **cols) -> None:
    sets = ", ".join(f"{c} = ?" for c in cols)
    conn.execute(f"UPDATE seats SET {sets} WHERE user_id = ?", (*cols.values(), user_id))


def is_manual(row: dict | None) -> bool:
    """A seat an admin set by hand (paid outside the app: a Payment Link
    emailed, an invoice) - no Stripe subscription behind it."""
    return bool(row) and bool(row.get("manual_note")) and not row.get("stripe_subscription")


def is_live(row: dict | None, now: datetime | None = None) -> bool:
    """Live: a Stripe status that continues, or a manual seat still inside
    its paid-through day."""
    if not row or row.get("status") not in LIVE:
        return False
    if is_manual(row):
        end = _parse(row.get("current_period_end"))
        return bool(end and _now(now) < end)
    return True


def _manual_grace(row: dict, grace: datetime | None) -> datetime | None:
    """A manual seat past its paid-through day: the grace counts from that day
    (before the nightly job has marked it ended)."""
    if is_manual(row) and row["status"] in LIVE:
        end = _parse(row["current_period_end"])
        if end:
            return end + timedelta(days=grace_days())
    return grace


def founding_used(conn) -> int:
    """Founding places handed out, ever (never given back)."""
    row = conn.execute("SELECT number FROM app_state WHERE name = ?",
                       (FOUNDING_STATE,)).fetchone()
    return int(row["number"]) if row else 0


def offers_founding(conn, user_id: int) -> bool:
    """Whether this advisor's first seat would get a founding place now: they
    never started a paid seat, and places are left."""
    row = seat(conn, user_id)
    return not (row and row.get("started_at")) and founding_used(conn) < founding_seats()


def _take_founding_place(conn) -> int | None:
    """The next founding place's number, or None when none are left. One
    UPDATE that refuses past the limit, so two at once can't both take the
    last place."""
    limit = founding_seats()
    conn.execute("INSERT INTO app_state (name, number) VALUES (?, 0) "
                 "ON CONFLICT (name) DO NOTHING", (FOUNDING_STATE,))
    cur = conn.execute("UPDATE app_state SET number = number + 1 WHERE name = ? AND number < ?",
                       (FOUNDING_STATE, limit))
    if not cur.rowcount:
        return None
    return founding_used(conn)


# --------------------------------------------------------------------------- #
# a subscription read from Stripe -> the seat's row
# --------------------------------------------------------------------------- #
def _first_item(sub: dict) -> dict:
    items = ((sub.get("items") or {}).get("data")) or []
    return items[0] if items else {}


def _plan_of(sub: dict) -> str | None:
    item = _first_item(sub)
    interval = ((item.get("price") or {}).get("recurring") or {}).get("interval")
    if interval in INTERVAL_PLAN:
        return INTERVAL_PLAN[interval]
    pid = (item.get("price") or {}).get("id")
    for plan in PLANS:
        if pid and pid in (price_id(plan, True), price_id(plan, False)):
            return plan
    return None


def _period_end(sub: dict) -> str | None:
    # newer Stripe API versions keep it on the item, older ones on the subscription
    return _from_epoch(sub.get("current_period_end") or _first_item(sub).get("current_period_end"))


def _id(value) -> str | None:
    """An id, whether Stripe sent the id or the expanded object."""
    if isinstance(value, dict):
        return value.get("id")
    return value or None


def apply(conn, user_id: int, sub: dict, *, now: datetime | None = None) -> dict:
    """Write what Stripe says about this login's subscription into its seat,
    and hand out or take away the founding place. Returns the row."""
    now = _now(now)
    row = ensure(conn, user_id, now=now)
    status = str(sub.get("status") or NONE)
    cols = {"stripe_subscription": _id(sub.get("id")) or row["stripe_subscription"],
            "stripe_customer": _id(sub.get("customer")) or row["stripe_customer"],
            "plan": _plan_of(sub) or row["plan"], "status": status,
            "current_period_end": _period_end(sub) or row["current_period_end"],
            "last_checked": _stamp(now)}
    if status in LIVE:
        if not row["started_at"]:
            # the first paid seat this advisor ever started: a founding place if any are left
            cols["started_at"] = _from_epoch(sub.get("start_date")) or _stamp(now)
            number = _take_founding_place(conn)
            cols["founding"] = 1 if number else 0
            cols["founding_no"] = number
    elif status in ("incomplete",):
        pass   # the first payment is still being made: nothing starts or ends yet
    else:
        # ended (canceled, unpaid, incomplete_expired, paused): the founding
        # place goes, and the tools stay open for the grace days from the end
        ended = (_from_epoch(sub.get("ended_at")) or cols["current_period_end"]
                 or _stamp(now))
        end = _parse(ended) or now
        cols["founding"] = 0
        cols["grace_until"] = _stamp(min(end, now) + timedelta(days=grace_days()))
    _update(conn, user_id, **cols)
    conn.commit()
    return seat(conn, user_id)


# --------------------------------------------------------------------------- #
# checkout, the check on return, the portal
# --------------------------------------------------------------------------- #
def _return_url(app_url: str, what: str) -> str:
    base = (app_url or "").split("?")[0].split("#")[0]
    return f"{base}?page=account&{RETURN_PARAM}={what}"


def start_checkout(conn, user_id: int, plan: str, app_url: str, *,
                   now: datetime | None = None) -> str:
    """A Stripe Checkout Session for one seat (quantity 1, always); its id is
    kept on the seat so the return can be checked. Returns Stripe's page
    address. Raises BillingError (or ValueError for a bad plan or a seat
    that's already live)."""
    now = _now(now)
    row = ensure(conn, user_id, now=now)
    if is_live(row, now):
        raise ValueError("Your seat is already active - Manage billing changes it.")
    founding = offers_founding(conn, user_id)
    price = price_id(plan, founding)
    if not (price and secret_key()):
        raise BillingError("Stripe isn't set up here yet.")
    params = {"mode": "subscription",
              "line_items": [{"price": price, "quantity": 1}],
              "client_reference_id": str(user_id),
              "metadata": {"northwend_user": str(user_id)},
              "subscription_data": {"metadata": {"northwend_user": str(user_id)}},
              "success_url": _return_url(app_url, "done"),
              "cancel_url": _return_url(app_url, "cancel")}
    if row["stripe_customer"]:
        params["customer"] = row["stripe_customer"]
    # the same click twice within ten minutes gets the same session back
    bucket = int(now.timestamp()) // 600
    session = _stripe("POST", "checkout/sessions", params,
                      idempotency_key=f"nw-seat-{user_id}-{price}-{bucket}")
    cols = {"checkout_session": session.get("id")}
    if row["started_at"] and row["founding"]:
        cols["founding"] = 0   # a new seat after one ended: that's a break
    _update(conn, user_id, **cols)
    conn.commit()
    if not session.get("url"):
        raise BillingError("Stripe didn't send a checkout page.")
    return session["url"]


def verify_checkout(conn, user_id: int, *, now: datetime | None = None) -> str:
    """Check the checkout kept on this login's seat with Stripe itself.
    Returns "none" (nothing waiting), "open" (not paid yet), "done" (the
    seat is set from Stripe's subscription), "expired" or "mismatch" (the
    session isn't this login's - nothing changes)."""
    now = _now(now)
    row = seat(conn, user_id)
    if not row or not row["checkout_session"]:
        return "none"
    session = _stripe("GET", f"checkout/sessions/{urllib.parse.quote(row['checkout_session'])}",
                      {"expand": ["subscription"]})
    if str(session.get("client_reference_id") or "") != str(user_id) \
            or session.get("mode") != "subscription":
        _update(conn, user_id, checkout_session=None)
        conn.commit()
        return "mismatch"
    if session.get("status") == "expired":
        _update(conn, user_id, checkout_session=None)
        conn.commit()
        return "expired"
    if session.get("status") != "complete" or not session.get("subscription"):
        return "open"
    sub = session["subscription"]
    if not isinstance(sub, dict):
        sub = _stripe("GET", f"subscriptions/{urllib.parse.quote(str(sub))}")
    if not _belongs(sub, user_id):
        _update(conn, user_id, checkout_session=None)
        conn.commit()
        return "mismatch"
    if not sub.get("customer"):
        sub = {**sub, "customer": session.get("customer")}
    apply(conn, user_id, sub, now=now)
    _update(conn, user_id, checkout_session=None)
    conn.commit()
    return "done"


def _belongs(sub: dict, user_id: int) -> bool:
    """A subscription's metadata, when it has ours, must name this login."""
    who = (sub.get("metadata") or {}).get("northwend_user")
    return who is None or str(who) == str(user_id)


def portal_url(conn, user_id: int, app_url: str) -> str:
    """Stripe's customer portal for this login's own Stripe customer."""
    row = seat(conn, user_id)
    if not row or not row["stripe_customer"]:
        raise ValueError("There's no seat to manage yet.")
    base = (app_url or "").split("?")[0].split("#")[0]
    res = _stripe("POST", "billing_portal/sessions",
                  {"customer": row["stripe_customer"], "return_url": f"{base}?page=account"})
    if not res.get("url"):
        raise BillingError("Stripe didn't send a page.")
    return res["url"]


# --------------------------------------------------------------------------- #
# what the app asks
# --------------------------------------------------------------------------- #
def state(conn, user_id: int, *, now: datetime | None = None) -> dict:
    """The login's seat for the page: {"billing": on or not, "open": may
    add and send, "live", "status", "plan", "founding", "founding_no",
    "period_end", "grace_until", "started"}. Off, a free beta seat, always
    open, and nothing is read or written."""
    if not on():
        return {"billing": False, "open": True, "live": False, "status": "beta", "plan": None,
                "founding": False, "founding_no": None, "period_end": None,
                "grace_until": None, "started": False, "waiting": False, "manual": None}
    now = _now(now)
    row = ensure(conn, user_id, now=now)
    live = is_live(row, now)
    grace = _parse(row["grace_until"])
    if not live:
        grace = _manual_grace(row, grace)
    return {"billing": True, "open": live or bool(grace and now < grace), "live": live,
            "status": row["status"], "plan": row["plan"], "founding": bool(row["founding"]),
            "founding_no": row["founding_no"], "period_end": row["current_period_end"],
            "grace_until": _stamp(grace) if grace else None, "started": bool(row["started_at"]),
            "waiting": bool(row["checkout_session"]),
            "manual": row["manual_note"] if is_manual(row) else None}


def can_write(conn, user_id: int, *, now: datetime | None = None) -> bool:
    """Whether this advisor may add clients and send proposals, reports and
    messages. Always while billing is off. Reading and exports never ask."""
    return state(conn, user_id, now=now)["open"]


def has_live_seat(conn, user_id: int) -> bool:
    """A seat Stripe is still charging for (admin.delete_account refuses then).
    A manual seat isn't: nothing renews it."""
    row = seat(conn, user_id)
    return is_live(row) and not is_manual(row)


def counts(conn, *, now: datetime | None = None) -> dict:
    """For Admin: how many seats are live, founding places used of how many,
    founding seats still kept, seats that ended past their grace, and seat
    rows not started. Counts only - never who, never card details."""
    now = _now(now)
    out = {"live": 0, "founding_kept": 0, "lapsed": 0, "not_started": 0,
           "founding_used": founding_used(conn), "founding_total": founding_seats()}
    for r in conn.execute("SELECT status, founding, started_at, grace_until, manual_note, "
                          "stripe_subscription, current_period_end FROM seats"):
        r = dict(r)
        grace = _parse(r["grace_until"])
        if not is_live(r, now):
            grace = _manual_grace(r, grace)
        if is_live(r, now):
            out["live"] += 1
            out["founding_kept"] += 1 if r["founding"] else 0
        elif not r["started_at"]:
            out["not_started"] += 1
        elif not (grace and now < grace):
            out["lapsed"] += 1
    return out


# --------------------------------------------------------------------------- #
# manual seats: paid outside the app (a Payment Link emailed, an invoice)
# --------------------------------------------------------------------------- #
MANUAL_NOTES = ("Payment Link", "Invoice", "Other")


def set_manual(conn, user_id: int, *, active: bool, paid_through: str | None = None,
               note: str = "Payment Link", founding: bool = False,
               now: datetime | None = None) -> dict:
    """Admin only (views/admin.py, logged as "seat_manual"): set an advisor's
    seat by hand. active=True needs `paid_through` ("YYYY-MM-DD", the last
    day paid for); founding=True takes the next founding place if the seat
    has none (ValueError when none are left). active=False ends it now: the
    founding place goes and the usual grace days start. Refused for a seat
    with a Stripe subscription that's still live - Stripe is the record
    there. Returns the row."""
    now = _now(now)
    who = conn.execute("SELECT is_advisor FROM users WHERE id = ?", (user_id,)).fetchone()
    if not who or not who["is_advisor"]:
        raise ValueError("Only an advisor has a seat.")
    note = (note or "").strip()[:40] or "Other"
    row = ensure(conn, user_id, now=now)
    if row["stripe_subscription"] and row["status"] in LIVE:
        raise ValueError("This seat is paid through Stripe - change it there.")
    cols = {"manual_note": note, "stripe_subscription": None, "last_checked": _stamp(now)}
    if active:
        try:
            end = datetime.strptime(str(paid_through), "%Y-%m-%d").replace(
                tzinfo=timezone.utc) + timedelta(days=1)   # through the end of that day
        except ValueError:
            raise ValueError("Give the last day paid for, like 2026-11-30.") from None
        if end <= now:
            raise ValueError("The paid-through day has already passed.")
        cols.update(status="active", current_period_end=_stamp(end),
                    plan=row["plan"] or "monthly")
        if not row["started_at"]:
            cols["started_at"] = _stamp(now)
        if founding and not row["founding"]:
            number = _take_founding_place(conn)
            if number is None:
                conn.rollback()
                raise ValueError("No founding places are left.")
            cols.update(founding=1, founding_no=number)
    else:
        cols.update(status="ended", founding=0,
                    grace_until=_stamp(now + timedelta(days=grace_days())))
    _update(conn, user_id, **cols)
    conn.commit()
    return seat(conn, user_id)


def end_manual(conn, *, now: datetime | None = None) -> int:
    """Nightly: manual seats past their paid-through day end - status
    "ended", the founding place gone, grace counted from that day. Stripe is
    never asked about them. Returns how many ended."""
    now = _now(now)
    n = 0
    rows = [dict(x) for x in conn.execute(
        f"SELECT {', '.join(COLUMNS)} FROM seats WHERE manual_note IS NOT NULL "
        "AND stripe_subscription IS NULL")]
    for r in rows:
        end = _parse(r["current_period_end"])
        if r["status"] in LIVE and end and end <= now:
            _update(conn, r["user_id"], status="ended", founding=0,
                    grace_until=_stamp(end + timedelta(days=grace_days())),
                    last_checked=_stamp(now))
            n += 1
    conn.commit()
    return n


# --------------------------------------------------------------------------- #
# the nightly reconciliation
# --------------------------------------------------------------------------- #
def sync_all(conn, *, now: datetime | None = None, pause: float = 0.1) -> dict:
    """Read every known subscription (and every checkout still waiting) from
    Stripe and update its seat. {"checked", "changed", "failed",
    "mismatched"} - counts only."""
    now = _now(now)
    out = {"checked": 0, "changed": 0, "failed": 0, "mismatched": 0,
           "manual_ended": end_manual(conn, now=now)}
    rows = [dict(r) for r in conn.execute(
        "SELECT user_id, stripe_subscription, checkout_session, status FROM seats "
        "WHERE stripe_subscription IS NOT NULL OR checkout_session IS NOT NULL ORDER BY user_id")]
    for r in rows:
        uid = r["user_id"]
        try:
            if r["checkout_session"]:
                if verify_checkout(conn, uid, now=now) == "mismatch":
                    out["mismatched"] += 1
            if r["stripe_subscription"] and (seat(conn, uid) or {}).get(
                    "stripe_subscription") == r["stripe_subscription"]:
                sub = _stripe("GET",
                              f"subscriptions/{urllib.parse.quote(r['stripe_subscription'])}")
                if not _belongs(sub, uid):
                    out["mismatched"] += 1
                    continue
                apply(conn, uid, sub, now=now)
            out["checked"] += 1
            if (seat(conn, uid) or {}).get("status") != r["status"]:
                out["changed"] += 1
        except BillingError:
            out["failed"] += 1
        if pause:
            time.sleep(pause)
    return out


def main(argv=None) -> int:
    from portfolio import connect
    ap = argparse.ArgumentParser(description="Paid advisor seats: --sync reads every known "
                                             "subscription from Stripe and updates the seats "
                                             "table. Prints counts only.")
    ap.add_argument("--sync", action="store_true", help="reconcile every seat with Stripe")
    ap.add_argument("--db", default=settings.get("DATABASE_URL") or settings.get("PORTFOLIO_DB"),
                    help="SQLite file or Postgres connection string (postgresql://...)")
    args = ap.parse_args(argv)
    if not args.sync:
        ap.error("nothing to do: pass --sync")
    if not args.db:
        ap.error("--db is required (or DATABASE_URL / PORTFOLIO_DB)")
    if not secret_key():
        print("Skipped: STRIPE_SECRET_KEY isn't set.")
        return 0
    conn = connect(args.db)
    try:
        res = sync_all(conn)
    finally:
        conn.close()
    print(f"Seats: {res['checked']} checked, {res['changed']} changed, {res['failed']} "
          f"couldn't be read, {res['mismatched']} not matching their account; "
          f"{res['manual_ended']} manual seats past their paid-through day ended.")
    # a seat Stripe couldn't tell us about fails the run, so the admin hears of it
    return 1 if res["failed"] or res["mismatched"] else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        import pgcompat
        pgcompat.close_all_pools()   # no-op unless a Postgres DSN was connected
