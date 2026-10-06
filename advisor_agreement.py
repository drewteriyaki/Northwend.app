"""The advisor agreement and attestation (master brief 4.1; PLAN step 5 item 1;
docs/LEGAL_GATES.md gate L1). The page is views/advisor_agreement.py.

DRAFT. TEXT below is a first draft for the owner's securities lawyer, who
supplies the real wording under gate L1 (LAWYER_NOTES lists what to look at).
Nothing here is legal advice.

At seat activation an approved advisor accepts the agreement before the
advisor tools open: Your clients shows it instead of the book, and
auth.can_view lets an advisor into no client's account until they have
(tools_open). Their own investor side - Portfolio, Plan, Money, Account -
works as usual meanwhile. When VERSION or the text changes, they are asked
again.

While gate L1 is off every seat is a free beta seat (brief 4.5) and the same
text is shown marked "Beta" (label()). Each acceptance is a row in
advisor_agreements: the version, a SHA-256 of the exact text shown, whether
L1 was on then, and the time - stored like the terms (users.terms_version).

The flag `advisor_agreement` (flags.FEATURES) turns the requirement on; off,
nothing is asked and nothing changes (staging turns it on first).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import flags

# Bump with any change to TEXT (the hash changes anyway): every advisor is
# asked again at their next visit to Your clients.
VERSION = "2026-10-06"
BETA_LABEL = "Beta"
BETA_NOTE = ("Northwend is in beta: advisor seats are free for now, and this is the same "
             "agreement every advisor accepts.")
TITLE = "Northwend advisor agreement"

# The agreement itself - plain words, the same for every advisor. Markdown
# (bold and numbered points only). DRAFT for the lawyer (LAWYER_NOTES).
TEXT = """\
**1. Who you are.** You are a representative of a firm registered with the SEC or \
a state securities regulator as an investment adviser (or of a broker-dealer, \
where that is permitted), and the firm's name and the CRD or licence number you \
gave Northwend are yours and true. You'll tell Northwend straight away if your \
registration or your firm changes.

**2. The advice is yours.** Anything you give a client through Northwend - \
proposals, model portfolios, notes, messages and progress reports - is your own \
advice, given under your firm's supervision. Northwend doesn't review, approve or \
supervise it, and each of these carries your name and firm and says so.

**3. Northwend isn't anyone's adviser.** You won't present Northwend as an \
investment adviser, or say or suggest that Northwend recommends you, your \
advice or any investment.

**4. Your obligations stay yours.** You're responsible for your client \
agreements, delivering your Form ADV (or your firm's other required disclosures), \
your books and records, your clients' consent to use Northwend with you, and your \
firm's compliance policies. Northwend is not your system of record: export what \
you need to keep.

**5. What Northwend is.** Northwend is software and a listing. It provides tools, \
records and - where it's turned on - a directory where people choose whom to \
contact, in alphabetical order.

**6. How Northwend is paid.** Never per client, per lead, per introduction or by \
outcome. Northwend takes no share of your fees and pays or takes nothing for \
referrals. Any seat fee is one flat fee, shown before you pay it.

**7. Licence checks.** Northwend looks up your registration (FINRA BrokerCheck or \
the SEC's IAPD) when you join and about once a year after. Advisor access may be \
paused if a registration can't be confirmed.

**8. Changes.** If this agreement changes, you'll see the new version and be asked \
to accept it before you continue with clients.
"""

TICK_LABEL = ("I've read the advisor agreement and I agree to it, for myself and as a "
              "representative of my firm.")

# For the lawyer (not shown in the app).
LAWYER_NOTES = (
    "[LAWYER: confirm who may hold a seat - IAR of an SEC- or state-registered RIA, "
    "broker-dealer representatives and where that is permitted.]",
    "[LAWYER: confirm the Form ADV / Regulation S-P / Rule 204-2 wording in point 4.]",
    "[LAWYER: point 5 - listing is not referring; align with the Terms draft section 9.]",
    "[LAWYER: point 6 - the flat-fee-only structure (brief 4.5); billing copy is L1's.]",
    "[LAWYER: whether acceptance needs anything beyond a ticked box and a stored time.]",
)


def text_hash(text: str | None = None) -> str:
    """SHA-256 of the exact text shown (hex) - TEXT unless given."""
    return hashlib.sha256((TEXT if text is None else text).encode("utf-8")).hexdigest()


def required() -> bool:
    """Whether accepting is required at all (the flag)."""
    return flags.on("advisor_agreement")


def l1_on() -> bool:
    """Gate L1 (flags.GATE_CHECKS): off, the agreement is shown marked Beta."""
    return flags.gate("L1")


def label() -> str:
    """"Beta" while gate L1 is off, else ""."""
    return "" if l1_on() else BETA_LABEL


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def latest(conn, user_id: int) -> dict | None:
    """The advisor's latest acceptance: {"version", "text_hash", "l1_on",
    "accepted_at"}, or None if they never accepted."""
    row = conn.execute("SELECT version, text_hash, l1_on, accepted_at FROM advisor_agreements "
                       "WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
    return dict(row) if row else None


def is_current(row: dict | None) -> bool:
    """Whether an acceptance (latest()) is of today's version and text."""
    return bool(row) and row["version"] == VERSION and row["text_hash"] == text_hash()


def has_current(conn, user_id: int) -> bool:
    return is_current(latest(conn, user_id))


def tools_open(conn, advisor_id: int) -> bool:
    """Whether this advisor may use the advisor tools: nothing is asked while
    the flag is off; on, the current version must be accepted. No query while
    the flag is off."""
    return not required() or has_current(conn, advisor_id)


def due(conn, user_id: int, *, is_advisor: bool) -> bool:
    """Whether an advisor still has the current version to accept."""
    return bool(is_advisor) and not tools_open(conn, user_id)


def accept(conn, user_id: int, *, ticked: bool, now: datetime | None = None) -> dict:
    """Record that this advisor accepted the current version (the box ticked),
    with whether gate L1 was on. A new row each time; nothing is changed or
    deleted. Raises ValueError if the box wasn't ticked or the account isn't
    an advisor. Returns the stored row."""
    if not ticked:
        raise ValueError("Tick the box to accept the agreement.")
    row = conn.execute("SELECT is_advisor FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row or not row["is_advisor"]:
        raise ValueError("Only an advisor accepts the advisor agreement.")
    stored = {"version": VERSION, "text_hash": text_hash(), "l1_on": 1 if l1_on() else 0,
              "accepted_at": _utc(now or datetime.now(timezone.utc))}
    conn.execute("INSERT INTO advisor_agreements (user_id, version, text_hash, l1_on, "
                 "accepted_at) VALUES (?, ?, ?, ?, ?)",
                 (user_id, stored["version"], stored["text_hash"], stored["l1_on"],
                  stored["accepted_at"]))
    conn.commit()
    return stored


def latest_all(conn) -> dict[int, dict]:
    """{advisor id: their latest acceptance, with "current"} - for Admin."""
    out: dict[int, dict] = {}
    for r in conn.execute("SELECT user_id, version, text_hash, l1_on, accepted_at "
                          "FROM advisor_agreements ORDER BY id"):
        out[r["user_id"]] = {**dict(r), "current": is_current(dict(r))}
    return out
