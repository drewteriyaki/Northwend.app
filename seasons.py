"""The Four Seasons (ROADMAP R7): four fixed moments in the year, each with a
reason to open the app that isn't the balance. The page is views/seasons.py
(a card on Home while a season is on, a line on Learn any time), behind flag
`seasons`.

- January: the new year's contribution limits, last year's IRA window, and
  the funds' yearly fee bill carried to the goal date (fees.py's own figures
  and its stated growth - fee_bill below; nothing new is estimated).
- April: the tax forms people receive, explained.
- October and November: open enrollment - workplace benefits, an HSA, the
  401(k) menu (the decoder, R5, where its flag is on).
- December: Year in review (recap.py), a letter to future you (the plan's
  note to future you, future_notes.py) and, only where the person's age
  range is "65 or older", a reminder of required minimum distributions.

Education, never advice (docs/PRINCIPLES.md 2): the same words for everyone,
no funds named, nothing ranked. Every link goes to an official site
(OFFICIAL_SITES; a test checks). Figures that change yearly are kept in one
place, LIMITS and RMD_AGE, with the tax year they belong to, the IRS page they
came from and the day they were checked; they're shown only during that tax
year (limits_for, rmd_age), and a test fails once the year is past so they
get reviewed. Everything ends with "check with your plan or a tax
professional".

What's kept: per season (its year and key, "2026-december"), whether the
person opened it or put it away, in their own settings (prefs PREF) - never
free text. Pure logic, no Streamlit, no database.
"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlparse

import fees

PREF = "seasons"   # user_prefs key: {"2026-december": "seen" | "put_away", ...}
SEEN, PUT_AWAY = "seen", "put_away"
STATUSES = (SEEN, PUT_AWAY)
KEEP = 8           # the newest seasons' states kept (two years); older ones drop

# every link here goes to one of these: the IRS, the Social Security
# Administration, the Health Insurance Marketplace and Medicare - official
# government sites only
OFFICIAL_SITES = (
    "www.irs.gov",          # Internal Revenue Service
    "www.ssa.gov",          # Social Security Administration
    "www.healthcare.gov",   # the Health Insurance Marketplace (CMS)
    "www.medicare.gov",     # Medicare (CMS)
)

IRS_IRA_LIMITS = ("https://www.irs.gov/retirement-plans/plan-participant-employee/"
                  "retirement-topics-ira-contribution-limits")
IRS_401K_LIMITS = ("https://www.irs.gov/retirement-plans/plan-participant-employee/"
                   "retirement-topics-401k-and-profit-sharing-plan-contribution-limits")
IRS_HSA = "https://www.irs.gov/publications/p969"
IRS_IRA_YEAR_END = "https://www.irs.gov/retirement-plans/ira-year-end-reminders"
IRS_RMD = ("https://www.irs.gov/retirement-plans/"
           "retirement-plan-and-ira-required-minimum-distributions-faqs")

# --------------------------------------------------------------------------- #
# figures that change every year: the tax year, the source, the day checked.
# Shown only during LIMITS_YEAR (limits_for); a test fails once it's past.
# --------------------------------------------------------------------------- #
LIMITS_YEAR = 2026
LIMITS_CHECKED = "2026-10-06"
# (key, what, the figures, source page)
LIMITS = (
    ("ira", "IRAs, traditional and Roth together",
     "$7,500, or $8,600 at 50 or older - or your taxable pay for the year, if that's less",
     IRS_IRA_LIMITS),
    ("401k", "A 401(k), from your pay",
     "$24,500; at 50 or older up to $8,000 more, or up to $11,250 more at 60 to 63, where "
     "the plan allows these extra amounts",
     IRS_401K_LIMITS),
    ("hsa", "A health savings account (HSA)",
     "$4,400 with self-only coverage, $8,750 with family coverage; $1,000 more at 55 or older",
     IRS_HSA),
)
# the age required minimum distributions begin, per the IRS's FAQ (checked
# LIMITS_CHECKED); shown only through RMD_YEAR, then reviewed
RMD_AGE = 73
RMD_YEAR = 2026
RMD_AGE_RANGE = "65 or older"   # the profile's only age range that can include it

# --------------------------------------------------------------------------- #
# the four seasons
# --------------------------------------------------------------------------- #
# (key, months, title, icon, why it's worth a look)
SEASONS = (
    ("january", (1,), "January: a fresh year", ":material/ac_unit:",
     "This year's limits, last year's IRA window, and what your funds' fees add up to."),
    ("april", (4,), "April: tax forms, explained", ":material/description:",
     "What each form from your brokerage, employer or plan is for, in plain words."),
    ("enrollment", (10, 11), "Fall: open enrollment", ":material/eco:",
     "Choosing next year's workplace benefits, and how a health savings account works."),
    ("december", (12,), "December: looking back", ":material/auto_stories:",
     "Your year in review, a letter to future you, and a few year-end reminders."),
)
KEYS = tuple(s[0] for s in SEASONS)
BY_KEY = {s[0]: s for s in SEASONS}
MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August",
               "September", "October", "November", "December")

INTRO = ("Four moments in the year, each with something worth a look that isn't your "
         "balance.")
CHECK = ("Rules and amounts change from year to year - check with your plan or a tax "
         "professional before acting on any of it.")
NOT_ADVICE = "Educational, not advice: this explains how things work, the same for everyone."

# ---- January --------------------------------------------------------------- #
JAN_PARAS = (
    "Each year the IRS sets how much can go into retirement and health savings accounts "
    "for that year. The amounts often rise a little from one year to the next.",
)
JAN_LIMITS_LEAD = "How much can go in for {year}, from the IRS:"
JAN_NO_LIMITS = ("This year's amounts are on the IRS's pages below - Northwend shows them "
                 "here once they've been checked.")
JAN_MORE = (
    "**Last year's IRA window.** Money for a traditional or Roth IRA can usually still be "
    "added for the year just ended until the federal tax-filing date in April. If you add "
    "some in these months, the IRA's provider asks which year it's for.",
    "**Workplace plans** like a 401(k) go by the calendar year: what comes out of your pay "
    "in January counts toward the new year. Your plan's website shows what you're putting in.",
)
FEE_TITLE = "Your yearly fee bill"
FEE_NONE = ("Funds take a small yearly fee out of what you hold, so there's never a bill to "
            "notice. Once your holdings include funds with a known fee, the Fee check shows "
            "what they come to in dollars.")
JAN_LINKS = (
    ("IRA contribution limits (IRS)", IRS_IRA_LIMITS),
    ("401(k) contribution limits (IRS)", IRS_401K_LIMITS),
    ("IRA year-end reminders (IRS)", IRS_IRA_YEAR_END),
)

# ---- April ----------------------------------------------------------------- #
APRIL_PARAS = (
    "Tax forms arrive from late January into the spring. Here's what each one is for - your "
    "tax software or a tax professional puts them in the right place.",
)
# (form, what it is, the IRS's or SSA's page about it)
FORMS = (
    ("W-2", "From your employer: your pay and the tax taken out. Box 12 shows money you put "
            "into a workplace plan like a 401(k).",
     "https://www.irs.gov/forms-pubs/about-form-w-2"),
    ("1099-DIV", "Dividends and fund payouts, including the gains a fund passed on to you - "
                 "even if they were reinvested.",
     "https://www.irs.gov/forms-pubs/about-form-1099-div"),
    ("1099-B", "Sales in a regular (taxable) account: what you sold, what you got for it, and "
               "usually what you paid - the cost basis.",
     "https://www.irs.gov/forms-pubs/about-form-1099-b"),
    ("1099-INT", "Interest, for example from a savings account or Treasury bills.",
     "https://www.irs.gov/forms-pubs/about-form-1099-int"),
    ("1099-R", "Money that came out of a retirement account or pension, including a rollover "
               "- a rollover shows here even when no tax is due on it.",
     "https://www.irs.gov/forms-pubs/about-form-1099-r"),
    ("5498", "Money put into an IRA, and its value at the end of the year. It often comes "
             "later in the spring, and it's a record for you - there's nothing to file with it.",
     "https://www.irs.gov/forms-pubs/about-form-5498"),
    ("SSA-1099", "From Social Security, for anyone who received benefits: the year's total. "
                 "A my Social Security account has a copy.",
     "https://www.ssa.gov/myaccount/"),
)
APRIL_MORE = (
    "**One envelope, several forms.** Brokerages often send a consolidated 1099 that holds "
    "the 1099-DIV, 1099-B and 1099-INT together.",
    "**Corrected forms are routine.** A brokerage sometimes sends a corrected 1099 later on, "
    "when a fund changes how it labels its payouts.",
    "**Inside an IRA or a 401(k)**, buying, selling and dividends usually don't bring a "
    "1099 - only money coming out does, on a 1099-R.",
)
APRIL_LINKS = (("Filing your taxes (IRS)", "https://www.irs.gov/filing"),)

# ---- October and November -------------------------------------------------- #
FALL_PARAS = (
    "Many employers hold open enrollment in the fall: the yearly window to choose next "
    "year's health plan and other benefits. Your HR or benefits team has the dates. The "
    "choices usually stay until the next window, unless something like a move, a marriage "
    "or a new baby opens a change.",
    "**A health savings account (HSA)** comes with a high-deductible health plan. Money goes "
    "in before tax, can be invested, carries over from year to year and stays yours when you "
    "change jobs. Taken out for qualified medical costs, it isn't taxed.",
    "**A flexible spending account (FSA)** is chosen for the year ahead and is usually "
    "use-it-or-lose-it within the plan year, though some employers allow a short grace "
    "period or carry a small amount over.",
    "**Your 401(k) or similar plan:** enrollment is a natural moment to look at how much you "
    "put in, what it's invested in and who's named as your beneficiary. Many plans let you "
    "change the amount at any time of year.",
    "**Coverage not through work:** the Health Insurance Marketplace has its own open "
    "enrollment, starting in the fall, and HealthCare.gov lists its dates. **With "
    "Medicare,** Medicare.gov lists the fall window for changing plans.",
)
FALL_LIMITS_LEAD = "How much can go into an HSA for {year}, from the IRS:"
FALL_LINKS = (
    ("Dates for Marketplace coverage (HealthCare.gov)",
     "https://www.healthcare.gov/quick-guide/dates-and-deadlines/"),
    ("Joining or changing a Medicare plan (Medicare.gov)",
     "https://www.medicare.gov/basics/get-started-with-medicare/get-more-coverage/"
     "joining-a-plan"),
    ("HSAs and FSAs: Publication 969 (IRS)", IRS_HSA),
)

# ---- December -------------------------------------------------------------- #
DEC_PARAS = (
    "December is a natural time to look back: what you added, what you learned and what the "
    "year was like - not only where the balance ended up.",
)
LETTER_TITLE = "A letter to future you"
LETTER_NONE = ("Some people write a few lines on their plan for whoever opens this app a year "
               "from now: why they're investing, and what they'd like to remember when markets "
               "are rough. It's private - on Plan, under Note to future you.")
LETTER_BACK = "Here's what you wrote to future you:"
RMD_TITLE = "Required minimum distributions"
RMD_TEXT = ("From the year someone turns {age}, the IRS generally requires a yearly "
            "withdrawal from traditional IRAs and most workplace retirement plans; a Roth IRA "
            "has none while its owner is alive. The first one can wait until April 1 of the "
            "next year, and after that each year's is taken by December 31. The plan or IRA "
            "provider can usually work out the amount.")
RMD_TEXT_LATER = ("From the age the IRS sets, it generally requires a yearly withdrawal from "
                  "traditional IRAs and most workplace retirement plans; a Roth IRA has none "
                  "while its owner is alive. The IRS's page gives this year's rules, and the "
                  "plan or IRA provider can usually work out the amount.")
RMD_DATED = "The IRS's rule for {year}, checked {checked}."
DEC_LINKS = (("Required minimum distributions: FAQs (IRS)", IRS_RMD),)

# each form's own page (shown beside the form), then the season's links
FORM_LINKS = tuple((f"About Form {form} ({'SSA' if 'ssa.gov' in url else 'IRS'})", url)
                   for form, _words, url in FORMS)
LINKS = {"january": JAN_LINKS, "april": FORM_LINKS + APRIL_LINKS,
         "enrollment": FALL_LINKS, "december": DEC_LINKS}


# --------------------------------------------------------------------------- #
# which season, and the person's own state
# --------------------------------------------------------------------------- #
def today() -> date:
    """The day the app goes by (one place, so the tests can set it)."""
    return date.today()


def season_of(day: date) -> str | None:
    """The season `day` falls in ("january", "april", "enrollment",
    "december"), or None between seasons."""
    return next((k for k, months, *_ in SEASONS if day.month in months), None)


def season_id(day: date) -> str | None:
    """"2026-december": the season `day` falls in and its year, or None."""
    key = season_of(day)
    return f"{day.year}-{key}" if key else None


def next_season(day: date) -> tuple[str, date]:
    """(key, first day) of the next season to begin after `day` (a season
    already on doesn't count)."""
    for ahead in range(1, 13):
        m = (day.month - 1 + ahead) % 12 + 1
        y = day.year + (day.month - 1 + ahead) // 12
        key = season_of(date(y, m, 1))
        if key and key != season_of(day):
            return key, date(y, m, 1)
    raise AssertionError("no season in a year")   # pragma: no cover


def when_label(key: str) -> str:
    """"January", "April", "October and November", "December"."""
    names = [MONTH_NAMES[m - 1] for m in BY_KEY[key][1]]
    return " and ".join(names)


_SID = re.compile(r"^\d{4}-(" + "|".join(KEYS) + r")$")


def clean_saved(saved) -> dict:
    """What's kept, checked: {season id: status}, known seasons and statuses
    only, the newest KEEP of them."""
    if not isinstance(saved, dict):
        return {}
    kept = {k: v for k, v in saved.items()
            if isinstance(k, str) and _SID.match(k) and v in STATUSES}
    order = sorted(kept, key=lambda k: (int(k[:4]), KEYS.index(k[5:])), reverse=True)
    return {k: kept[k] for k in order[:KEEP]}


def status_of(saved, sid: str | None) -> str | None:
    return clean_saved(saved).get(sid) if sid else None


def with_status(prefs_data: dict, sid: str, status: str) -> dict:
    """The person's settings with one season's state set. "seen" never
    replaces "put_away"; an unknown season or status changes nothing."""
    out = dict(prefs_data or {})
    if not (isinstance(sid, str) and _SID.match(sid)) or status not in STATUSES:
        return out
    kept = clean_saved(out.get(PREF))
    if status == SEEN and kept.get(sid) == PUT_AWAY:
        return out
    kept[sid] = status
    out[PREF] = clean_saved(kept)
    return out


def home_state(saved, day: date) -> str | None:
    """What Home shows on `day`: "card" (a season is on and not looked at
    yet), "line" (opened already: one quiet line), or None (between seasons,
    or put away until the next one)."""
    sid = season_id(day)
    if not sid:
        return None
    status = status_of(saved, sid)
    return None if status == PUT_AWAY else ("line" if status == SEEN else "card")


# --------------------------------------------------------------------------- #
# dated figures
# --------------------------------------------------------------------------- #
def limits_for(year: int, keys=None) -> tuple:
    """LIMITS (only those in `keys`, if given) when `year` is the tax year
    they were checked for; () any other year - never stale figures."""
    if year != LIMITS_YEAR:
        return ()
    return tuple(lm for lm in LIMITS if keys is None or lm[0] in keys)


def rmd_age(year: int) -> int | None:
    """The IRS's RMD age, while the rule checked for RMD_YEAR is current."""
    return RMD_AGE if year <= RMD_YEAR else None


def rmd_may_apply(age_range: str | None) -> bool:
    """The reminder only for someone whose age range is the one that can
    include RMD age - the app never knows an exact age."""
    return age_range == RMD_AGE_RANGE


def rmd_text(year: int) -> str:
    age = rmd_age(year)
    return RMD_TEXT.format(age=age) if age else RMD_TEXT_LATER


def dated_line(year: int) -> str:
    return RMD_DATED.format(year=RMD_YEAR, checked=LIMITS_CHECKED) if rmd_age(year) else ""


# --------------------------------------------------------------------------- #
# January's fee bill: fees.py's own figures, carried to the goal date
# --------------------------------------------------------------------------- #
def years_to(target_date, today: date) -> int | None:
    """Whole years from `today` to a plan's target date (ISO), at least 1;
    None without a date."""
    try:
        target = date.fromisoformat(str(target_date)[:10])
    except (TypeError, ValueError):
        return None
    return max(1, round((target - today).days / 365.25))


def fee_bill(fee_result: dict | None, today: date, target_date=None) -> dict | None:
    """The fee check's result (fees.check) as January's fee bill: {yearly,
    ratio, years, total, growth}. years/total are None without a goal date;
    total is fees.cost_over over those years, at the fee check's own growth.
    None when no fund's fee is known."""
    if not fee_result or not fee_result.get("funds"):
        return None
    growth = fee_result.get("growth", fees.GROWTH)
    years = years_to(target_date, today) if target_date else None
    total = (sum(fees.cost_over(f["value"], f["ratio"], years, growth)["total"]
                 for f in fee_result["funds"]) if years else None)
    return {"yearly": fee_result["total_yearly"], "ratio": fee_result.get("ratio"),
            "years": years, "total": total, "growth": growth}


# --------------------------------------------------------------------------- #
# for the tests
# --------------------------------------------------------------------------- #
def links() -> list[tuple[str, str]]:
    """Every (label, url) shown, LIMITS' sources included."""
    out = [lk for k in KEYS for lk in LINKS[k]]
    return out + [(what, url) for _k, what, _f, url in LIMITS]


def host(url: str) -> str:
    return urlparse(url).netloc.lower()


def all_text(with_figures: bool = False) -> str:
    """Every word shown from here (LIMITS' figures only if asked)."""
    parts = [INTRO, CHECK, NOT_ADVICE, *JAN_PARAS, JAN_LIMITS_LEAD, JAN_NO_LIMITS, *JAN_MORE,
             FEE_TITLE, FEE_NONE, *APRIL_PARAS, *APRIL_MORE, *FALL_PARAS, FALL_LIMITS_LEAD,
             *DEC_PARAS, LETTER_TITLE, LETTER_NONE, LETTER_BACK, RMD_TITLE, RMD_TEXT_LATER]
    for _k, _m, title, _icon, why in SEASONS:
        parts += [title, why]
    for form, words, _u in FORMS:
        parts += [form, words]
    parts += [t for k in KEYS for t, _u in LINKS[k]]
    if with_figures:
        parts += [RMD_TEXT, RMD_DATED] + [f"{w} {f}" for _k, w, f, _u in LIMITS]
    return "\n".join(parts)
