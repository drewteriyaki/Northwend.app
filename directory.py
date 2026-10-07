"""The advisor directory (docs/PLAN.md step 5 items 3-4 and 11, master brief
3.3 and 4.2, decision B4): an advisor's listing, and "Find a guide", where
an individual browses the listings. Flag `directory`, gate L2 (both off
unless set - flags.py). Pure logic, no Streamlit; the pages are
views/directory.py (Find a guide, and "Your directory listing" on Your
clients).

The rules, enforced here and tested (tests/test_directory.py):
- **Everyone listed equally.** Listings come back in one order only:
  alphabetical by the name the advisor shows (sort_key; the firm only breaks
  a tie between two identical names), within whatever filters the person
  chose. Nothing Northwend computes is a sort key - no featured slots,
  ratings, reviews, "best match", or anything paid for. There is no other
  sort in this module and no ORDER BY in its SQL.
- **Filters per B4, and only those** (FILTERS): the state the person is in,
  virtual or in person, fee model, who they serve, and account minimum in
  bands. Credentials, registration type, the description, the scheduling
  link and a one-time review (ADR 0005: offered or not, its price as the
  advisor states it, paid to them directly) are shown but can't be filtered
  on (filtering on letters after a name would rank by another name; a
  one-time review filter is an L2 question).
- **Beside the listings**, "How advisors are paid" (FEES_*): each fee model
  in plain words, questions to ask, official sites only. And on Learn and
  Plan, one quiet "Want a second opinion? Find a guide" line
  (guide_link_shown) - nothing counted about who sees or presses it.
- **Nothing is counted about who browses** (brief 3.4). Browsing, filtering
  and pressing "Request an introduction" write nothing - no views,
  impressions or clicks, for anyone, and advisors see no such numbers. Only
  an introduction the person actually sends is recorded (intros.py, flag
  `intros`). The filters live in the browser session only; the state a
  person picks is never saved.
- **Shown only when** (visible): the account is an approved advisor
  (users.is_advisor), the profile is complete (missing), the advisor
  switched "listed" on, and - once the other step-5 work lands - the
  licence check is current and the advisor agreement accepted
  (OUTSIDE_CHECKS: used when those modules exist, skipped until then).

One table, advisor_profiles: one row per advisor (user_id), the lists kept
as JSON text. It's the advisor's own account data: deleted with the account
(admin.ACCOUNT_TABLES) and in Export everything (export.OWN).

The copy on Find a guide is DRAFT (COPY_STATUS) until the owner's lawyer
signs off gate L2.
"""

from __future__ import annotations

import importlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlsplit

FLAG = "directory"   # flags.FEATURES["directory"]: gate L2 as well as the flag

# ---- what a profile holds -------------------------------------------------- #
# registration type, as the advisor enters it: (key, label, the public lookup)
REG_TYPES = (
    ("sec_ria", "SEC-registered investment adviser (RIA)", "iapd"),
    ("state_ria", "State-registered investment adviser (RIA)", "iapd"),
    ("bd_rep", "Broker-dealer representative", "brokercheck"),
)
# the public regulator lookups, by an individual's CRD number (and their
# search pages, for a number that isn't a plain CRD)
LOOKUPS = {
    "iapd": ("the SEC's Investment Adviser Public Disclosure",
             "https://adviserinfo.sec.gov/individual/summary/{crd}",
             "https://adviserinfo.sec.gov/"),
    "brokercheck": ("FINRA BrokerCheck",
                    "https://brokercheck.finra.org/individual/summary/{crd}",
                    "https://brokercheck.finra.org/"),
}
# fee model, as the advisor states it (any of them)
FEE_MODELS = (
    ("aum", "A percentage of assets they manage (AUM)"),
    ("flat", "A flat fee"),
    ("hourly", "By the hour"),
    ("subscription", "A subscription or retainer"),
)
# the account minimum, in bands: the band the advisor's minimum falls in
MINIMUMS = (
    ("none", "No minimum"),
    ("under_100k", "Under $100,000"),
    ("100k_250k", "$100,000 to $249,999"),
    ("250k_500k", "$250,000 to $499,999"),
    ("500k_1m", "$500,000 to $999,999"),
    ("1m_plus", "$1,000,000 or more"),
)
# the person's side of the same bands: "a minimum of no more than ..."
MINIMUM_FILTER = (
    ("none", "No minimum"),
    ("under_100k", "Under $100,000"),
    ("100k_250k", "Under $250,000"),
    ("250k_500k", "Under $500,000"),
    ("500k_1m", "Under $1,000,000"),
)
# who they serve: a fixed list (the advisor ticks any)
SERVES = (
    ("new", "People just starting out"),
    ("families", "Families and households"),
    ("retirement", "People near or in retirement"),
    ("business", "Business owners and self-employed"),
    ("equity", "Employees with stock or options"),
    ("public", "Teachers and public employees"),
    ("medical", "Doctors and medical professionals"),
    ("military", "Military and veterans"),
    ("transitions", "Life changes: divorce, loss, inheritance"),
)
# how they meet clients
MEETING = (
    ("virtual", "Virtual"),
    ("in_person", "In person"),
    ("both", "Virtual or in person"),
)
# US states and DC (two-letter code, name)
STATES = (
    ("AL", "Alabama"), ("AK", "Alaska"), ("AZ", "Arizona"), ("AR", "Arkansas"),
    ("CA", "California"), ("CO", "Colorado"), ("CT", "Connecticut"), ("DE", "Delaware"),
    ("DC", "District of Columbia"), ("FL", "Florida"), ("GA", "Georgia"), ("HI", "Hawaii"),
    ("ID", "Idaho"), ("IL", "Illinois"), ("IN", "Indiana"), ("IA", "Iowa"),
    ("KS", "Kansas"), ("KY", "Kentucky"), ("LA", "Louisiana"), ("ME", "Maine"),
    ("MD", "Maryland"), ("MA", "Massachusetts"), ("MI", "Michigan"), ("MN", "Minnesota"),
    ("MS", "Mississippi"), ("MO", "Missouri"), ("MT", "Montana"), ("NE", "Nebraska"),
    ("NV", "Nevada"), ("NH", "New Hampshire"), ("NJ", "New Jersey"), ("NM", "New Mexico"),
    ("NY", "New York"), ("NC", "North Carolina"), ("ND", "North Dakota"), ("OH", "Ohio"),
    ("OK", "Oklahoma"), ("OR", "Oregon"), ("PA", "Pennsylvania"), ("RI", "Rhode Island"),
    ("SC", "South Carolina"), ("SD", "South Dakota"), ("TN", "Tennessee"), ("TX", "Texas"),
    ("UT", "Utah"), ("VT", "Vermont"), ("VA", "Virginia"), ("WA", "Washington"),
    ("WV", "West Virginia"), ("WI", "Wisconsin"), ("WY", "Wyoming"),
)

# every field, the lists among them, and those a listing needs (credentials
# and the scheduling link are optional)
FIELDS = ("display_name", "firm", "reg_type", "reg_number", "credentials", "fee_models",
          "minimum", "serves", "states", "meeting", "description", "scheduling_url",
          "one_time_cost")
LIST_FIELDS = ("credentials", "fee_models", "serves", "states")
REQUIRED = ("display_name", "firm", "reg_type", "reg_number", "fee_models", "minimum",
            "serves", "states", "meeting", "description")
LABELS = {"display_name": "Name", "firm": "Firm", "reg_type": "Registration type",
          "reg_number": "CRD number", "credentials": "Credentials",
          "fee_models": "Fee model", "minimum": "Account minimum", "serves": "Who you serve",
          "states": "States served", "meeting": "Virtual or in person",
          "description": "A short description", "scheduling_url": "Scheduling link",
          "one_time_cost": "One-time review"}
LIMITS = {"display_name": 60, "firm": 80, "reg_number": 20, "credential": 30,
          "credentials": 10, "description": 500, "scheduling_url": 300}

# A one-time review (ADR 0005): the advisor's own service, offered or not, at
# the price they state or "ask". Stored in one column, one_time_cost: '' (not
# offered), 'ask', or whole dollars as digits ('250'). Shown on the listing in
# plain words; never a filter (B4's five stay five - whether it becomes one is
# an L2 question, LEGAL_GATES) and never a sort (sort_key reads only the name).
ONE_TIME_ASK = "ask"
ONE_TIME_RANGE = (1, 10_000)   # whole dollars, as the advisor states it
ONE_TIME_CHOICES = (           # the advisor's form: (key, label)
    ("", "I don't offer one"),
    ("price", "Yes, at a set price"),
    (ONE_TIME_ASK, "Yes - people ask me for the price"),
)

# The filters a person can use (decision B4), and nothing else.
FILTERS = ("state", "meeting", "fee_models", "serves", "minimum")

# ---- the Find a guide page's words: DRAFT, reviewed under gate L2 ------------ #
COPY_STATUS = "DRAFT"   # until the lawyer signs off L2 (docs/LEGAL_GATES.md)
PAGE_TITLE = "Find a guide"
INTRO = ("If you'd ever like to work with a financial advisor, these are independent advisors "
         "who use Northwend. You don't need one to use anything in Northwend - it all stays "
         "free either way.")
ABOUT_LINES = (
    "**Each advisor is independent.** They work for their own registered firm, and their "
    "advice and fees are theirs and their firm's - not Northwend's.",
    "**How Northwend is paid.** Advisors pay Northwend a flat fee for its software and this "
    "listing. Northwend is never paid per client or per introduction, and no one can pay "
    "for a place in this list.",
    "**What Northwend checks, and what it doesn't.** Before a listing appears, Northwend "
    "checks that the advisor's registration number matches a record on the public "
    "regulator lookup (the SEC's Investment Adviser Public Disclosure or FINRA "
    "BrokerCheck). That's all: Northwend doesn't recommend, rate or vet advisors beyond "
    "it. Each listing links to that public record so you can read it yourself.",
)
ORDER_LINE = ("Listed in alphabetical order by name, within the filters you choose - "
              "nothing else decides the order.")
PRIVACY_LINE = ("Nothing about your browsing is recorded, and the state you pick isn't saved.")
NONE_MATCH = ("No advisors match these filters yet. Try fewer of them - or check back later, "
              "as more advisors join.")
NONE_YET = "No advisors are listed yet. Check back later."
# the button on each listing while the intro flow (flag `intros`) is off
INTROS_SOON = ("Introductions open soon. Until then, you're welcome to use the advisor's own "
               "scheduling link, or look up their public record.")
# under a listing's one-time review (ADR 0005 point 4)
ONE_TIME_NOTE = "Paid to the advisor directly; Northwend takes no part of it."

# ---- the calm link on Learn and Plan (ADR 0005 point 3): DRAFT, gate L2 ----- #
# One quiet line once someone has finished Learn or set a goal - no pop-up,
# nothing counted about who sees or presses it. Only for an individual on
# their own account (guide_link_shown).
GUIDE_LINE = "Want a second opinion?"
GUIDE_BUTTON = "Find a guide"

# ---- "How advisors are paid": a beginner's explainer beside the listings ---- #
# (ADR 0005 point 6; DRAFT for L2.) Plain words for each way the listings say
# advisors are paid - in FEE_MODELS' own order, then commissions (broker-dealer
# representatives can be listed, REG_TYPES) - each with its trade-off and a
# question to ask. Never ranks or favours a way; links go only to the official
# sites in OFFICIAL_SITES.
FEES_TITLE = "How advisors are paid"
FEES_INTRO = ("Advisors are paid in a few common ways, and some use more than one. Each way has "
              "its own trade-offs, and none is the right one for everyone. Every listing here "
              "says how that advisor is paid.")
FEES_EXPLAINED = (
    ("aum", "A percentage of assets they manage (AUM)",
     "A yearly fee worked out as a share of the money the advisor manages for you, usually "
     "taken from the account itself. It rises as the account grows and falls when it shrinks. "
     "Ask what the percentage comes to in dollars a year on your own amount."),
    ("flat", "A flat fee, including a one-time review",
     "A set price for a defined piece of work - for example, one look at your goal, your "
     "accounts and your questions. You know the cost before you start. Ask what's included, "
     "and what any later help would cost."),
    ("hourly", "By the hour",
     "You pay for the time the advisor spends, at their hourly rate. Ask roughly how many hours "
     "the work will take before it starts."),
    ("subscription", "A subscription or retainer",
     "A regular charge - monthly, quarterly or yearly - for ongoing help, whatever the size of "
     "your accounts. Ask what it covers and how to stop it."),
    ("commission", "Commissions",
     "Some financial professionals, such as broker-dealer representatives, are paid a "
     "commission when you buy or sell certain products through them, sometimes by the "
     "company behind the product. Ask which products pay them a commission, and how much."),
)
FEES_CONFLICTS = ("Any way of being paid can create a conflict of interest - a reason, even a "
                  "small one, for an advisor to lean one way. Registered advisers and brokers "
                  "have to describe how they're paid and their conflicts in writing, and you "
                  "can read their public records on the official sites below.")
FEES_QUESTIONS_TITLE = "Questions you can ask any advisor"
FEES_QUESTIONS = (
    "How are you paid for working with me, in total - and does anyone else pay you when I "
    "buy or keep something?",
    "Do you or your firm earn more if I pick one product, account or service over another?",
    "What conflicts of interest do you have, and how do you handle them?",
    "Do you act as a fiduciary - putting my interests first - all the time you work with me?",
    "Can I have your firm's relationship summary (Form CRS) and your fees in writing?",
    "If you offer a one-time review, what does it include, and what does it cost?",
)
# where to read more: official sources only (sec.gov / investor.gov, FINRA)
OFFICIAL_SITES = (
    ("Investor.gov, the SEC's site for investors", "https://www.investor.gov/"),
    ("FINRA BrokerCheck", "https://brokercheck.finra.org/"),
    ("The SEC's Investment Adviser Public Disclosure", "https://adviserinfo.sec.gov/"),
)
OFFICIAL_HOSTS = ("investor.gov", "sec.gov", "finra.org")   # and their subdomains

_URL_IN_TEXT = re.compile(
    r"(https?://|www\.|\b[a-z0-9-]+\.(com|net|org|io|co|app|us|biz|info|me|ly|ai|link)\b"
    r"|[\w.+-]+@[\w-]+\.)", re.I)
_CREDENTIAL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .&'()/®-]*$")
_REG_NUMBER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 -]*$")


def _keys(pairs) -> tuple:
    return tuple(k for k, *_ in pairs)


def _label_of(pairs, key) -> str:
    return next((label for k, label, *_ in pairs if k == key), "")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- checking what the advisor enters -------------------------------------- #
def scheduling_link_error(url: str) -> str | None:
    """What's wrong with a scheduling link, or None: https only, a real host,
    no login details or spaces in it, at most LIMITS["scheduling_url"]."""
    url = (url or "").strip()
    if len(url) > LIMITS["scheduling_url"]:
        return f"The scheduling link is too long (up to {LIMITS['scheduling_url']} characters)."
    if any(ch.isspace() for ch in url) or any(ord(ch) < 33 for ch in url):
        return "The scheduling link can't have spaces in it."
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
    except ValueError:
        return "That scheduling link doesn't look right."
    if parts.scheme.lower() != "https":
        return "The scheduling link must start with https://"
    if parts.username or parts.password or "@" in parts.netloc:
        return "The scheduling link can't hold a login."
    if "." not in host or host.startswith(".") or host.endswith("."):
        return "That scheduling link doesn't look right."
    return None


def _as_list(value) -> list:
    """A list from a list, or a comma-separated string (credentials)."""
    if value is None:
        return []
    if isinstance(value, str):
        value = value.split(",")
    return [str(v).strip() for v in value if str(v).strip()]


def clean(fields: dict) -> tuple[dict, list[str]]:
    """The profile as it would be saved, and what's wrong with it. Each
    field is checked when given; a missing one is only a problem for listing
    (missing()). Unknown keys are ignored."""
    errors: list[str] = []
    out: dict = {}
    for name in ("display_name", "firm"):
        text = " ".join(str(fields.get(name) or "").split())
        if len(text) > LIMITS[name]:
            errors.append(f"{LABELS[name]}: up to {LIMITS[name]} characters.")
        elif _URL_IN_TEXT.search(text):
            errors.append(f"{LABELS[name]}: no links or email addresses.")
        out[name] = text
    reg = fields.get("reg_type") or ""
    if reg and reg not in _keys(REG_TYPES):
        errors.append("Pick a registration type from the list.")
    out["reg_type"] = reg if reg in _keys(REG_TYPES) else ""
    number = " ".join(str(fields.get("reg_number") or "").split())
    if number and (len(number) > LIMITS["reg_number"] or not _REG_NUMBER.match(number)):
        errors.append("CRD number: letters, digits and dashes only, up to "
                      f"{LIMITS['reg_number']}.")
    out["reg_number"] = number
    creds = []
    for c in _as_list(fields.get("credentials")):
        if len(c) > LIMITS["credential"] or not _CREDENTIAL.match(c) or _URL_IN_TEXT.search(c):
            errors.append(f"Credentials: {c[:40]!r} doesn't look like a credential "
                          f"(up to {LIMITS['credential']} characters, no links).")
        elif c not in creds:
            creds.append(c)
    if len(creds) > LIMITS["credentials"]:
        errors.append(f"Credentials: up to {LIMITS['credentials']}.")
    out["credentials"] = creds[:LIMITS["credentials"]]
    for name, pairs in (("fee_models", FEE_MODELS), ("serves", SERVES), ("states", STATES)):
        given = _as_list(fields.get(name))
        bad = [g for g in given if g not in _keys(pairs)]
        if bad:
            errors.append(f"{LABELS[name]}: pick from the list.")
        # kept in the list's own order, not the order they were ticked
        out[name] = [k for k in _keys(pairs) if k in given]
    for name, pairs in (("minimum", MINIMUMS), ("meeting", MEETING)):
        value = fields.get(name) or ""
        if value and value not in _keys(pairs):
            errors.append(f"{LABELS[name]}: pick from the list.")
        out[name] = value if value in _keys(pairs) else ""
    desc = str(fields.get("description") or "").strip()
    if len(desc) > LIMITS["description"]:
        errors.append(f"Description: up to {LIMITS['description']} characters.")
    if _URL_IN_TEXT.search(desc):
        errors.append("Description: plain text only - no links or email addresses. Your "
                      "scheduling link has its own box.")
    if "<" in desc or ">" in desc:
        errors.append("Description: plain text only.")
    out["description"] = desc
    url = str(fields.get("scheduling_url") or "").strip()
    if url:
        problem = scheduling_link_error(url)
        if problem:
            errors.append(problem)
    out["scheduling_url"] = url
    out["one_time_cost"], problem = one_time_value(fields.get("one_time_cost"))
    if problem:
        errors.append(problem)
    return out, errors


def one_time_value(raw) -> tuple[str, str | None]:
    """A one-time review as saved ('' not offered, 'ask', or whole dollars as
    digits) and what's wrong with it, or None. Takes '', None, 'ask', a whole
    number, or text like '$1,250'."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return "", None
    if isinstance(raw, str) and raw.strip().casefold() == ONE_TIME_ASK:
        return ONE_TIME_ASK, None
    low, high = ONE_TIME_RANGE
    problem = (f"One-time review: a price in whole dollars from ${low:,} to ${high:,}, or "
               "\"ask\".")
    if isinstance(raw, bool):
        return "", problem
    if isinstance(raw, float):
        if not raw.is_integer():
            return "", problem
        raw = int(raw)
    if isinstance(raw, str):
        text = raw.strip().replace("$", "").replace(",", "").strip()
        if text.endswith(".00"):
            text = text[:-3]
        if not text.isascii() or not text.isdigit():
            return "", problem
        raw = int(text)
    if not isinstance(raw, int) or not low <= raw <= high:
        return "", problem
    return str(raw), None


def one_time_words(value: str) -> str:
    """How a listing says its one-time review, or '' when not offered."""
    if value == ONE_TIME_ASK:
        return "Offered - ask the advisor for the price"
    if value and value.isdigit():
        return f"Offered - ${int(value):,}, the price as the advisor states it"
    return ""


def missing(profile: dict | None) -> list[str]:
    """The required fields still empty (their LABELS), in form order."""
    profile = profile or {}
    return [LABELS[f] for f in REQUIRED if not profile.get(f)]


def complete(profile: dict | None) -> bool:
    return not missing(profile)


# ---- the advisor's own profile --------------------------------------------- #
def _row_to_profile(row) -> dict:
    p = dict(row)
    for f in LIST_FIELDS:
        try:
            value = json.loads(p.get(f) or "[]")
        except (TypeError, ValueError):
            value = []
        p[f] = [str(v) for v in value] if isinstance(value, list) else []
    p["listed"] = bool(p.get("listed"))
    return p


def get_profile(conn, user_id: int) -> dict | None:
    """This advisor's own profile (every field, `listed`, `updated_at`), or None."""
    row = conn.execute("SELECT * FROM advisor_profiles WHERE user_id = ?",
                       (user_id,)).fetchone()
    return _row_to_profile(row) if row else None


def _is_advisor(conn, user_id: int) -> bool:
    row = conn.execute("SELECT is_advisor FROM users WHERE id = ?", (user_id,)).fetchone()
    return bool(row and row["is_advisor"])


def save_profile(conn, user_id: int, fields: dict, *, listed: bool = False) -> dict:
    """Save an advisor's own profile ({"ok", "errors", "profile"}). Nothing is
    saved if any field is wrong. `listed` on needs a complete profile. Only
    an approved advisor's account has one (PermissionError otherwise)."""
    if not _is_advisor(conn, user_id):
        raise PermissionError("only an approved advisor has a directory listing")
    profile, errors = clean(fields)
    if listed and not errors and missing(profile):
        errors.append("To be listed, fill in: " + ", ".join(missing(profile)) + ".")
    if errors:
        return {"ok": False, "errors": errors, "profile": profile}
    values = [json.dumps(profile[f]) if f in LIST_FIELDS else profile[f] for f in FIELDS]
    cols = ", ".join(FIELDS)
    conn.execute(
        f"INSERT INTO advisor_profiles (user_id, {cols}, listed, updated_at) "
        f"VALUES (?, {', '.join('?' for _ in FIELDS)}, ?, ?) "
        "ON CONFLICT (user_id) DO UPDATE SET "
        + ", ".join(f"{f} = excluded.{f}" for f in (*FIELDS, "listed", "updated_at")),
        (user_id, *values, 1 if listed else 0, _now()))
    conn.commit()
    return {"ok": True, "errors": [], "profile": {**profile, "listed": bool(listed)}}


def set_listed(conn, user_id: int, on: bool) -> bool:
    """Turn this advisor's own listing on or off. On needs a complete profile;
    returns whether the setting is now `on`."""
    profile = get_profile(conn, user_id)
    if profile is None or (on and (missing(profile) or not _is_advisor(conn, user_id))):
        return False
    conn.execute("UPDATE advisor_profiles SET listed = ?, updated_at = ? WHERE user_id = ?",
                 (1 if on else 0, _now(), user_id))
    conn.commit()
    return True


def delete_profile(conn, user_id: int) -> bool:
    """Remove this advisor's own profile (and so their listing)."""
    cur = conn.execute("DELETE FROM advisor_profiles WHERE user_id = ?", (user_id,))
    conn.commit()
    return cur.rowcount > 0


# ---- conditions other step-5 work adds ------------------------------------- #
# PLAN step 5 items 1-2: the licence evidence and its yearly re-check
# (licence_check.py - no check on record, or one over 13 months old, is not
# current) and the advisor agreement (advisor_agreement.tools_open: the
# current version accepted, while its flag is on). A listing is shown only if
# each says True for the advisor - called as fn(conn, user_id) - and an error
# counts as "not current" (fail closed). A module that can't be imported is
# skipped (the tests use that to stand on approval alone).
OUTSIDE_CHECKS = (
    ("licence_check", "licence_current"),
    ("advisor_agreement", "tools_open"),
)


def _outside_checks():
    """The (module, function) checks that exist today."""
    found = []
    for mod_name, fn_name in OUTSIDE_CHECKS:
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue
        fn = getattr(mod, fn_name, None)
        if callable(fn):
            found.append(fn)
    return found


def _passes_outside_checks(conn, user_id: int, checks) -> bool:
    for fn in checks:
        try:
            if not fn(conn, user_id):
                return False
        except Exception:  # noqa: BLE001 - fail closed: not shown until it's sorted
            return False
    return True


def why_not_shown(conn, user_id: int) -> list[str]:
    """For the advisor's own page: why their listing isn't shown, in plain
    words ([] when it is). Never a count of anything."""
    profile = get_profile(conn, user_id)
    if profile is None:
        return ["You haven't filled in your listing yet."]
    out = []
    if not _is_advisor(conn, user_id):
        out.append("Your advisor access isn't approved.")
    if missing(profile):
        out.append("Still to fill in: " + ", ".join(missing(profile)) + ".")
    if not profile["listed"]:
        out.append("You've chosen not to be listed.")
    if not _passes_outside_checks(conn, user_id, _outside_checks()):
        out.append("Your licence check or advisor agreement needs renewing.")
    return out


# ---- the listings: who's shown, filtered, in the one order ----------------- #
def _fold(text: str) -> str:
    """Alphabetical without case, accents or punctuation ("José" with "Jose")."""
    plain = unicodedata.normalize("NFKD", (text or "").casefold())
    return " ".join("".join(ch for ch in plain if ch.isalnum() or ch == " ").split())


def sort_key(profile: dict) -> tuple:
    """The only order listings ever have: alphabetical by the name shown
    (then the firm, only to break a tie between two identical names). Both
    are what the advisor typed - nothing Northwend computes."""
    name, firm = profile.get("display_name") or "", profile.get("firm") or ""
    return (_fold(name), name, _fold(firm), firm)


def in_order(profiles) -> list[dict]:
    """Alphabetical by name (sort_key) - whatever order they came in."""
    return sorted(profiles, key=sort_key)


def check_filters(filters: dict | None) -> dict:
    """The person's filters, checked: only FILTERS (B4) - anything else, such
    as credentials, raises ValueError. Empty values mean "any"."""
    filters = {k: v for k, v in (filters or {}).items() if v not in (None, "", [], ())}
    unknown = [k for k in filters if k not in FILTERS]
    if unknown:
        raise ValueError(f"not a directory filter: {', '.join(map(str, unknown))}")
    checks = {"state": _keys(STATES), "meeting": ("virtual", "in_person"),
              "minimum": _keys(MINIMUM_FILTER)}
    for k, allowed in checks.items():
        if k in filters and filters[k] not in allowed:
            raise ValueError(f"{k}: {filters[k]!r} isn't one of the choices")
    for k, pairs in (("fee_models", FEE_MODELS), ("serves", SERVES)):
        if k in filters:
            filters[k] = _as_list(filters[k])
            if set(filters[k]) - set(_keys(pairs)):
                raise ValueError(f"{k}: not one of the choices")
    return filters


def matches(profile: dict, filters: dict | None) -> bool:
    """Whether a listing fits the person's filters: serves their state; meets
    the way they want (an advisor who does both fits either); has any of the
    fee models they ticked; serves any of the groups they ticked; and has a
    minimum no higher than the band they picked."""
    f = check_filters(filters)
    if "state" in f and f["state"] not in profile.get("states", []):
        return False
    if "meeting" in f and profile.get("meeting") not in (f["meeting"], "both"):
        return False
    if "fee_models" in f and not set(f["fee_models"]) & set(profile.get("fee_models", [])):
        return False
    if "serves" in f and not set(f["serves"]) & set(profile.get("serves", [])):
        return False
    if "minimum" in f:
        bands = _keys(MINIMUMS)
        have = profile.get("minimum")
        if have not in bands or bands.index(have) > bands.index(f["minimum"]):
            return False
    return True


def visible(conn) -> list[dict]:
    """Every listing a person can see: an approved advisor, a complete
    profile, listed by the advisor, and the OUTSIDE_CHECKS that exist. In
    alphabetical order. Reads only - nothing is written or counted."""
    rows = conn.execute(
        "SELECT p.* FROM advisor_profiles p JOIN users u ON u.id = p.user_id "
        "WHERE p.listed = 1 AND u.is_advisor = 1").fetchall()
    checks = _outside_checks()
    shown = [p for p in map(_row_to_profile, rows)
             if complete(p) and _passes_outside_checks(conn, p["user_id"], checks)]
    return in_order(shown)


def listings(conn, filters: dict | None = None) -> list[dict]:
    """Find a guide's list: the visible listings that fit the filters,
    alphabetical by name. Filtering never reorders."""
    f = check_filters(filters)
    return [p for p in visible(conn) if matches(p, f)]


# ---- how a listing reads ---------------------------------------------------- #
def lookup(profile: dict) -> tuple[str, str] | None:
    """(where, link) for the advisor's public regulator record: the page for
    their CRD number when it's a plain number, else that lookup's search."""
    kind = next((look for k, _, look in REG_TYPES if k == profile.get("reg_type")), None)
    if kind is None:
        return None
    where, page, search = LOOKUPS[kind]
    number = (profile.get("reg_number") or "").replace(" ", "")
    return where, (page.format(crd=number) if number.isdigit() else search)


def describe(profile: dict) -> dict:
    """A listing's words for the page: labels for every key it holds."""
    return {
        "reg_type": _label_of(REG_TYPES, profile.get("reg_type")),
        "fee_models": [_label_of(FEE_MODELS, k) for k in profile.get("fee_models", [])],
        "minimum": _label_of(MINIMUMS, profile.get("minimum")),
        "serves": [_label_of(SERVES, k) for k in profile.get("serves", [])],
        "states": ([] if len(profile.get("states", [])) == len(STATES) else
                   [_label_of(STATES, k) for k in profile.get("states", [])]),
        "all_states": len(profile.get("states", [])) == len(STATES),
        "meeting": _label_of(MEETING, profile.get("meeting")),
        "one_time": one_time_words(profile.get("one_time_cost") or ""),
    }


# ---- the calm link on Learn and Plan --------------------------------------- #
def guide_link_shown(*, directory_on: bool, is_advisor: bool, is_admin: bool,
                     client_mode: bool, has_advisor: bool) -> bool:
    """Whether Learn and Plan may show the quiet "Want a second opinion? Find
    a guide" line (GUIDE_LINE): only with `directory` on (its gate L2 too),
    only for an individual on their own account - never an advisor, an
    admin, client mode, or someone who already has an advisor. Where on the
    page (Learn finished, a goal set) is the page's to decide."""
    return bool(directory_on and not is_advisor and not is_admin and not client_mode
                and not has_advisor)


# ---- the introduction while its flag is off -------------------------------- #
def request_intro_placeholder(person_id: int, advisor_id: int) -> dict:
    """What "Request an introduction" does while the intro flow (flag
    `intros`, PLAN step 5 item 5) is off: nothing is sent, saved or counted;
    the page says INTROS_SOON. With it on, the button opens the intro form
    (views/intros.py) and only an intro actually sent is written
    (intros.send) - still nothing counted about browsing (brief 3.4)."""
    del person_id, advisor_id   # nothing to do: the intro flow is off
    return {"sent": False, "message": INTROS_SOON}
