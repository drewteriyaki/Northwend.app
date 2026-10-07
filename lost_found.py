"""Lost & Found (ROADMAP R9): a calm, educational place that helps a person
find money they already own - old 401(k)s and other workplace plans, state
unclaimed property, an old HSA, FSA or IRA, savings bonds, and the employer
match at their current job (which links to the Free money check,
employer_match.py, rather than repeating it). The front half of the account
map (ROADMAP item 10); the page is views/lost_found.py, under the account map
on the Account page, behind flag `lost_found`.

Education, never advice (docs/PRINCIPLES.md 2): for an old 401(k) found, the
common choices are explained side by side in no particular order, with the
questions to ask the plan administrator or a professional - Northwend never
says which one. No funds are named. Brokerages, where an IRA could be held,
come from brokerages.py: names and links only, alphabetical, never ranked.
Every link goes to an official site - government (.gov) or the state
offices' own association (OFFICIAL_SITES; a test checks). No deadlines or
dollar figures: those are the plan's and the IRS's, and they change.

The one thing kept: a checklist in the person's own settings (prefs
PREF: each place's status - still looking, found something, nothing there -
and the day of the last change). Never an amount, an account number or a
name; never shown to an advisor, never sent to the AI. Pure logic, no
Streamlit, no database.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import urlparse

import brokerages

PREF = "lost_found"   # user_prefs key: {"places": {place: status}, "on": "YYYY-MM-DD"}

# every link here goes to one of these: government sites, the association of
# state unclaimed property offices and the multistate search it endorses, and
# FINRA's BrokerCheck (the brokerage regulator). Brokerages' own sites only
# through brokerages.BROKERAGES, in its alphabetical list.
OFFICIAL_SITES = (
    "lostandfound.dol.gov",       # U.S. Department of Labor (EBSA)
    "www.pbgc.gov",               # Pension Benefit Guaranty Corporation
    "unclaimed.org",              # NAUPA: links to every state's own office
    "www.missingmoney.com",       # the multistate search NAUPA endorses
    "www.usa.gov",                # the federal government's own guide
    "www.treasurydirect.gov",     # U.S. Treasury: savings bonds
    "www.irs.gov",                # IRS
    "brokercheck.finra.org",      # FINRA, the brokerage regulator
)

INTRO = ("Money you already own can get left behind - in an old job's 401(k), an account "
         "you stopped using, or a state's list of unclaimed property. These are the free, "
         "official places to look, and what to have ready.")
PRIVATE = ("Northwend never asks for your Social Security number, account numbers or "
           "passwords - you give those only to the plan or the official site itself. Your "
           "list below is kept with your own settings, only you see it, and none of it is "
           "sent to the AI.")
NOT_ADVICE = ("Educational, not advice: nothing here suggests what to do with what you find. "
              "Searching and claiming through these official places is free.")

# (key, title, icon, paragraphs (markdown), links (label, url), what to have ready)
SECTIONS = (
    ("old_plans", "Old 401(k)s and other workplace plans", ":material/work_history:", (
        "When you leave a job, the part of its 401(k) or similar plan that's vested - "
        "yours to keep - stays yours. It simply stays with that plan until you move it, "
        "and after a few job changes it's easy to lose track of one.",
        "**The employer's HR or benefits team** is a good first call. If the company "
        "changed its name or was bought, they can often tell you who runs the plan now.",
        "**Old statements and tax forms.** A plan statement names the plan's "
        "administrator - the company that runs it. Your W-2 from that job shows in box "
        "12 whether you put money into a plan.",
        "**The Department of Labor's Retirement Savings Lost and Found** is a free "
        "search for plans from private employers and unions (not government or "
        "religious employers). You confirm who you are through Login.gov, the "
        "government's sign-in service. It may not list every plan, so the other places "
        "are still worth a look.",
        "**A pension from a past job:** if the company or its plan has closed, the "
        "Pension Benefit Guaranty Corporation (PBGC) lists pensions it holds for people "
        "it couldn't reach.",
    ), (
        ("Retirement Savings Lost and Found (U.S. Department of Labor)",
         "https://lostandfound.dol.gov/"),
        ("Search unclaimed pensions (PBGC)", "https://www.pbgc.gov/search-unclaimed-pensions"),
    ), (
        "The employer's name, and any later name if it was bought or renamed",
        "Roughly when you worked there",
        "Your address while you worked there",
        "Your Social Security number - for the plan or the official site when they ask, "
        "never for Northwend",
    )),
    ("unclaimed", "Unclaimed property held by a state", ":material/account_balance:", (
        "When a bank account, an uncashed check, a refund, an insurance payout or a "
        "brokerage account isn't used for some years, the company hands it to the state. "
        "The state keeps it for you until you claim it, however long that takes.",
        "**Each state has its own unclaimed property office.** Look in every state "
        "you've lived or worked in. unclaimed.org, from the association of those offices "
        "(NAUPA), links to each state's own site, and MissingMoney.com, which NAUPA "
        "endorses, searches many states' records at once.",
        "**Searching and claiming through a state's own office is free.** Some companies "
        "offer to find or claim money for a fee. You never need one - you can always go "
        "to the state's own site yourself.",
        "USA.gov lists other places that may be holding money for you, such as some "
        "federal agencies.",
    ), (
        ("unclaimed.org - find your state's office (NAUPA)", "https://unclaimed.org/"),
        ("MissingMoney.com - search many states at once", "https://www.missingmoney.com/"),
        ("Find unclaimed money (USA.gov)", "https://www.usa.gov/unclaimed-money"),
    ), (
        "Every name you've used, and every address you've lived at",
        "The states you've lived or worked in",
    )),
    ("other_accounts", "HSAs, FSAs, old IRAs and savings bonds", ":material/savings:", (
        "**A health savings account (HSA)** stays yours when you change jobs or health "
        "plans, and the money doesn't run out at the end of the year. An old statement, "
        "or the tax form the HSA's custodian sends (Form 5498-SA), names who holds it.",
        "**A flexible spending account (FSA)** works differently: it's usually "
        "use-it-or-lose-it within the plan year, though some employers allow a short "
        "grace period or carry a small amount over. If you left a job recently, the "
        "employer's benefits team can tell you whether a claims window is still open "
        "for costs you already had.",
        "**An old IRA** stays at the firm where it was opened until you move it. Old "
        "year-end statements, or the Form 5498 the firm sends, name it. If the firm was "
        "bought or renamed, FINRA BrokerCheck shows what became of it.",
        "**Paper U.S. savings bonds:** TreasuryDirect's Treasury Hunt looks up matured "
        "savings bonds that haven't been cashed.",
        "IRS Publication 969 explains HSAs and FSAs in more detail.",
    ), (
        ("FINRA BrokerCheck", "https://brokercheck.finra.org/"),
        ("Treasury Hunt (TreasuryDirect)",
         "https://www.treasurydirect.gov/savings-bonds/treasury-hunt/"),
        ("HSAs and FSAs: Publication 969 (IRS)", "https://www.irs.gov/publications/p969"),
    ), (
        "Old statements or tax forms, if you have them",
        "The employer's name, for an HSA or FSA that came with a job",
    )),
)

MATCH_TITLE = "Free money at your current job"
MATCH_TEXT = ("If your employer adds to your 401(k) when you put money in - a match - the "
              "Free money check works out what it's worth and whether you're getting all "
              "of it.")

# --------------------------------------------------------------------------- #
# an old 401(k) found: the common choices, side by side - never which one
# --------------------------------------------------------------------------- #
OPTIONS_TITLE = "Found an old 401(k)? The common choices"
OPTIONS_INTRO = ("These are the usual choices, in no particular order. Which fits depends on "
                 "your plan's rules, its fees and your taxes - questions for the plan "
                 "administrator or a tax professional. Northwend doesn't suggest one.")
OPTIONS = (
    ("Leave it in the old plan",
     "Many plans let former employees keep their money there. Some move small balances out "
     "on their own - the plan can tell you its rule."),
    ("Move it to your new employer's plan",
     "If your new plan accepts money from other plans (often called a roll-in), both can be "
     "kept in one place, under the new plan's rules and choices."),
    ("Move it to an IRA",
     "An individual retirement account you open yourself, at a brokerage you choose, with "
     "its own fees and choices."),
    ("Cash it out",
     "The money is paid to you. It's usually counted as income for that year, and taken "
     "before retirement age an extra early-withdrawal tax often applies too, unless an "
     "exception fits. Some is usually held back for taxes up front, so less arrives than "
     "the balance."),
)
QUESTIONS = (
    "What does it cost each year to keep the money where it is, and what would it cost in "
    "the new place?",
    "Which investments could I choose from in each place?",
    "Is all of it vested - mine to keep?",
    "Can it move as a direct rollover, straight from the old plan to the new account? What "
    "do you need from me?",
    "Is any of it Roth or after-tax money, and how is that part handled?",
    "If I took it as cash, how much would be held back for taxes, and would an "
    "early-withdrawal tax apply to me?",
    "Does the plan have a rule about small balances, or a date by which I'd need to decide?",
)
QUESTIONS_LEAD = "Questions worth asking the plan administrator or a tax professional:"
OPTIONS_LINKS = (
    ("Rollovers from retirement plans (IRS Topic 413)", "https://www.irs.gov/taxtopics/tc413"),
    ("The extra tax on early withdrawals (IRS Topic 558)",
     "https://www.irs.gov/taxtopics/tc558"),
)
IRA_LEAD = "Thinking about an IRA? Any brokerage can hold one. " + brokerages.LIST_INTRO

# --------------------------------------------------------------------------- #
# the person's own checklist (prefs PREF)
# --------------------------------------------------------------------------- #
PLACES = (
    ("past_employers", "Past employers' HR or benefits teams"),
    ("old_paperwork", "Old statements and tax forms"),
    ("dol", "Retirement Savings Lost and Found (Department of Labor)"),
    ("pbgc", "Unclaimed pensions (PBGC)"),
    ("states", "Unclaimed property in each state I've lived in"),
    ("hsa_fsa", "Old HSAs or FSAs"),
    ("iras", "Old IRAs and brokerage accounts"),
    ("bonds", "Savings bonds (Treasury Hunt)"),
    ("match", "My employer's match (Free money check)"),
)
PLACE_KEYS = tuple(k for k, _ in PLACES)
NOT_YET = ""
# status -> how it's shown; "not yet" is never stored
STATUSES = {NOT_YET: "Not looked yet", "looking": "Still looking",
            "found": "Found something", "none": "Nothing there"}
FOUND_NEXT = ("Found something? You can add it to your account map above (a name and the "
              "last 3 digits at most - never the whole number), or bring its holdings in.")


def clean_saved(saved) -> dict:
    """What's kept, checked: {"places": {place: status}, "on": date} with only
    known places and statuses (anything else is dropped)."""
    if not isinstance(saved, dict):
        return {"places": {}, "on": None}
    places = saved.get("places")
    places = {k: v for k, v in (places.items() if isinstance(places, dict) else ())
              if k in PLACE_KEYS and v in STATUSES and v != NOT_YET}
    on = saved.get("on")
    try:
        on = date.fromisoformat(str(on)).isoformat() if on else None
    except ValueError:
        on = None
    return {"places": places, "on": on if places else None}


def status_of(saved, place: str) -> str:
    return clean_saved(saved)["places"].get(place, NOT_YET)


def with_status(prefs_data: dict, place: str, status: str,
                today: date | None = None) -> dict:
    """The person's settings with one place's status changed (NOT_YET clears
    it; an empty list leaves no key behind). Unknown places or statuses
    change nothing."""
    out = dict(prefs_data or {})
    if place not in PLACE_KEYS or status not in STATUSES:
        return out
    kept = clean_saved(out.get(PREF))
    places = dict(kept["places"])
    if status == NOT_YET:
        places.pop(place, None)
    else:
        places[place] = status
    if places:
        out[PREF] = {"places": places, "on": (today or date.today()).isoformat()}
    else:
        out.pop(PREF, None)
    return out


def cleared(prefs_data: dict) -> dict:
    """The person's settings without the list."""
    out = dict(prefs_data or {})
    out.pop(PREF, None)
    return out


def summary(saved) -> dict:
    """{"looked": places with any status, "found", "looking", "none", "of": all places}."""
    places = clean_saved(saved)["places"]
    counts = {s: sum(1 for v in places.values() if v == s) for s in STATUSES if s}
    return {"looked": len(places), "of": len(PLACES), **counts}


def links() -> list[tuple[str, str]]:
    """Every (label, url) this page links to, outside the brokerages' list."""
    return [lk for s in SECTIONS for lk in s[4]] + list(OPTIONS_LINKS)


def host(url: str) -> str:
    return urlparse(url).netloc.lower()


def all_text() -> str:
    """Every word the page shows from here (for the tests' word checks)."""
    parts = [INTRO, PRIVATE, NOT_ADVICE, MATCH_TITLE, MATCH_TEXT, OPTIONS_TITLE,
             OPTIONS_INTRO, QUESTIONS_LEAD, IRA_LEAD, FOUND_NEXT, *QUESTIONS,
             *STATUSES.values()]
    for _key, title, _icon, paras, lks, ready in SECTIONS:
        parts += [title, *paras, *(t for t, _ in lks), *ready]
    parts += [f"{t} {w}" for t, w in OPTIONS]
    parts += [t for t, _ in OPTIONS_LINKS] + [t for _, t in PLACES]
    return "\n".join(parts)
