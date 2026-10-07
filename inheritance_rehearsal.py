"""The Inheritance Rehearsal (ROADMAP "Someday" -> built): a practice run at
looking after a made-up parent's accounts, start to finish, as a short
tap-through story - finding out what accounts exist, who to call first,
what papers are often asked for, beneficiaries and the estate, an inherited
IRA as a thing to ask about, what not to rush, Social Security and the final
tax return, and taking care of yourself. The page is
views/inheritance_rehearsal.py, on the Account page just under Trail Forks,
behind flag `inheritance_rehearsal`.

Education, never advice (docs/PRINCIPLES.md 2; LEGAL_GATES.md section 6,
L3 to look at the estate and tax wording as with R8): the family and its
accounts are made up (Pat, a plan at an old employer, a brokerage account, a
bank account, a paper savings bond) and no real firm is named. Each step is
a situation and two or three taps - things to find out or ask - never
graded; after a tap, what people often find. No rules, ages, deadlines,
figures or time limits are stated: where a real rule has a timeline, the
question is "are there any deadlines?". Every link goes to an official
government site (trail_forks.OFFICIAL_SITES; a test checks). It ends,
gently, at the person's own account map and, where it's on, Trail Forks'
route for the death of a parent.

The one thing kept: in the person's own settings (prefs PREF), which steps
they've walked through and the day they finished - step keys and a date
only, never what they tapped, never free text. Never shown to an advisor,
never sent to the AI. Pure logic, no Streamlit, no database.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import urlparse

from trail_forks import OFFICIAL_SITES  # noqa: F401 - the same official hosts, re-exported

PREF = "inheritance_rehearsal"   # user_prefs key: {"done": [step, ...], "finished": "YYYY-MM-DD"}

TITLE = "The Inheritance Rehearsal"
INTRO = ("This is a practice run with a made-up family, so you'll know what to expect if it "
         "ever happens for real. It goes through looking after a parent's accounts after they "
         "die, one small step at a time. Nothing is graded - each choice is just "
         "something to find out or ask.")
FAMILY = ("Meet Pat, a made-up parent. In this story Pat has died, and you're the one helping "
          "to sort things out. Pat had a retirement plan from an old employer, an account at a "
          "brokerage, a savings account at a bank, and a paper savings bond in a desk drawer.")
PRIVATE = ("Which steps you've gone through, and the day you finished, are saved in your "
           "own settings. Only you see them - not an advisor - and none of it is sent to the "
           "AI. Which choices you pick isn't saved, and there's no box to type in.")
NOT_ADVICE = ("Educational, not advice: Pat and the accounts are made up, and every real estate "
              "is different. For a real one, the executor, an attorney, a tax preparer or the "
              "plan administrator can help.")
TAP_LEAD = "What would you find out first?"
NOTE_LEAD = "What people often find"
NO_RIGHT_ANSWER = ("There's no right order and no wrong choice. In real life most of these "
                   "happen at the same time.")
START = "Start the practice run"
AGAIN = "Go through it again"
NEXT = "Next"
FINISH = "Finish"
LEAVE = "Leave the practice run"

END_TITLE = "The end of the practice run"
END = ("That's the end of the practice run. Real life is usually messier than this, and "
       "that's normal - nobody gets all of it right, and nobody does it all at once. If "
       "you'd like, here are two things you can do next, when you're ready.")
# where the story ends: the person's own account map (always on Account) and,
# where its flag is on, Trail Forks' route for the death of a parent
END_LINKS = {
    "account_map": ("Make your own account map",
                    "On this page, the account map lets you list your own accounts, so your "
                    "family knows where to look later on."),
    "trail_forks": ("Trail Forks: the death of a parent",
                    "Just above, Trail Forks has a list for the death of a parent - what to "
                    "gather and what to ask, for if it happens for real."),
}

# Each step: key, title, situation, choices ((choice, words, people often...), ...),
# links ((label, url), ...)
STEPS = (
    {"key": "what_exists", "title": "Finding out what there is",
     "situation": ("Nobody is quite sure which accounts Pat had. There's a pile of mail on the "
                   "kitchen table and a folder in the desk."),
     "choices": (
         ("a_list", "Look for a list Pat may have left - an account map, a binder, notes",
          "People often start with whatever list was left behind. When there isn't one, the "
          "list gets built a piece at a time - it doesn't have to be complete all at "
          "once."),
         ("the_mail", "Keep an eye on the mail for statements and letters",
          "Statements arrive on their own schedules, so the list tends to grow as the mail "
          "comes in. People often keep one folder for everything that arrives."),
         ("tax_forms", "Look at Pat's last tax return and tax forms",
          "A tax return and its forms - a Form 1099 from a brokerage or bank, for example - "
          "often point to accounts no one remembered. That's how the savings bond's interest "
          "might show up too."),
     ),
     "links": ()},

    {"key": "who_first", "title": "Who to call first",
     "situation": ("You've found the old employer's plan, the brokerage and the bank. You're "
                   "not sure whom to call first."),
     "choices": (
         ("executor", "Find out who the executor is - the person the will names to look after "
                      "the estate",
          "Firms often want to hear from the executor. If there's no will, a court can name "
          "someone to do it; an attorney can explain how that works where Pat lived."),
         ("plan_admin", "Call the plan administrator for the old employer's plan",
          "Plans usually have someone who handles a member's death. People often open with: "
          "\"What do you need from me, and whom can you talk to?\""),
         ("estate_team", "Call the brokerage and ask for its estate or bereavement team",
          "Many firms have a team just for this, sometimes called estate services or "
          "bereavement services. People often find it helps to note whom they spoke with, "
          "and what was said."),
     ),
     "links": ()},

    {"key": "papers", "title": "The papers people ask for",
     "situation": ("The brokerage says it will need some papers before anything can happen. "
                   "You're not sure which."),
     "choices": (
         ("certificate", "Ask whether they need a copy of the death certificate, and what kind",
          "Copies of the death certificate are often asked for by more than one place, and "
          "some ask for a certified copy. People often ask the funeral home how to order "
          "them."),
         ("letters", "Ask whether they need letters testamentary, or something like them",
          "Letters testamentary (or letters of administration) are court papers that show who "
          "may act for the estate. Not every account calls for them - one with a named "
          "beneficiary often doesn't. Ask what they need."),
         ("their_list", "Ask them to send a written list of what they need",
          "Each firm has its own list. People often find a written one saves calls back and "
          "forth, and they keep a copy of everything they send."),
     ),
     "links": ()},

    {"key": "beneficiaries", "title": "Beneficiaries and the estate",
     "situation": ("The plan says Pat named a beneficiary on the retirement plan. The "
                   "brokerage account doesn't seem to have one."),
     "choices": (
         ("who_named", "Ask who is named as beneficiary on each account",
          "An account with a named beneficiary usually goes to that person directly, outside "
          "the will. People are often surprised that, for that account, the beneficiary form "
          "is what counts."),
         ("none_named", "Ask what happens to an account with no beneficiary",
          "An account with no beneficiary usually becomes part of the estate, and the executor "
          "looks after it with everything else. An attorney can explain how that works where "
          "Pat lived."),
         ("pass_on", "Ask whether the bank account was set up to pass to someone",
          "Some bank and brokerage accounts can be set up to pass straight to a person - "
          "sometimes called payable on death or transfer on death. The firm can say how this "
          "one was set up."),
     ),
     "links": (
         ("Retirement topics: beneficiaries (IRS)",
          "https://www.irs.gov/retirement-plans/plan-participant-employee/"
          "retirement-topics-beneficiary"),
     )},

    {"key": "inherited_ira", "title": "An inherited retirement account",
     "situation": ("In the story, you're the beneficiary on Pat's retirement plan. The plan "
                   "mentions there are choices, and something called an inherited IRA."),
     "choices": (
         ("choices", "Ask what my choices are, and are there any deadlines?",
          "An inherited IRA is one kind of account a beneficiary may be able to move inherited "
          "retirement money into. The rules depend on the account and on your relationship "
          "to the person, and they do change - so people often ask the plan to walk them "
          "through each choice."),
         ("taxed", "Ask a tax preparer how money taken out of it is taxed",
          "Money taken out of an inherited retirement account is often taxed as income. "
          "People often ask a tax preparer before taking anything out, so nothing comes as a "
          "surprise."),
         ("stay_put", "Ask whether the money can stay where it is while I learn more",
          "The plan can say whether the money can stay put for now. People often find it "
          "easier to take things one question at a time."),
     ),
     "links": (
         ("Retirement topics: beneficiaries (IRS)",
          "https://www.irs.gov/retirement-plans/plan-participant-employee/"
          "retirement-topics-beneficiary"),
     )},

    {"key": "not_rush", "title": "What not to rush",
     "situation": ("A letter arrives offering to settle the estate quickly. A relative wonders "
                   "aloud about selling Pat's investments."),
     "choices": (
         ("selling", "Ask a tax preparer about selling inherited investments",
          "The value used for tax purposes is often different for inherited investments. "
          "People often find there's time to understand the taxes before selling anything."),
         ("offers", "Ask the executor or an attorney about offers that arrive",
          "Offers often arrive soon after the news. People often let them wait, and check "
          "anyone who offers to help through the executor or an attorney."),
         ("debts", "Ask the executor before paying any of Pat's bills or debts",
          "Family members usually don't pay a parent's debts from their own money - the "
          "estate settles them. People often ask the executor or an attorney before paying "
          "anything."),
     ),
     "links": (
         ("Does a person's debt go away when they die? (CFPB)",
          "https://www.consumerfinance.gov/ask-cfpb/"
          "does-a-persons-debt-go-away-when-they-die-en-1463/"),
     )},

    {"key": "official", "title": "Social Security and the final tax return",
     "situation": ("A letter from Social Security and a question about Pat's taxes turn up "
                   "together."),
     "choices": (
         ("reported", "Ask whether Pat's death has been reported to Social Security",
          "The funeral home often reports it. Some family members may be able to receive "
          "survivor benefits, and Social Security can say who's eligible."),
         ("final_return", "Ask who files Pat's final tax return",
          "A final tax return is usually filed for the person who died, and the estate may "
          "file its own. The executor and a tax preparer can say who does what."),
     ),
     "links": (
         ("Survivors benefits (Social Security)", "https://www.ssa.gov/benefits/survivors/"),
         ("Filing the final tax return of a deceased person (IRS)",
          "https://www.irs.gov/individuals/"
          "file-the-final-income-tax-returns-of-a-deceased-person"),
         ("Survivors, executors and administrators (IRS Publication 559)",
          "https://www.irs.gov/publications/p559"),
     )},

    {"key": "yourself", "title": "Taking care of yourself",
     "situation": ("It's been a long stretch of calls and paperwork, and you miss Pat. "
                   "You're tired."),
     "choices": (
         ("pause", "Take a break from the paperwork for a while",
          "People often find most of this can be done in small pieces, and that it's alright "
          "to stop for a while. Grieving takes time."),
         ("share", "Ask someone to share the calls or the paperwork",
          "Many families split the work - one person on the phone, another keeping the "
          "folder. Asking for help is part of doing this well."),
         ("own_money", "Leave decisions about your own money for later",
          "People often wait on decisions about their own money until things feel steadier. "
          "Your own plan will still be there."),
     ),
     "links": ()},
)
BY_KEY = {s["key"]: s for s in STEPS}
STEP_KEYS = tuple(BY_KEY)


def choices_of(step: str) -> tuple[tuple[str, str], ...]:
    """(choice, words) for one step's taps, in order."""
    return tuple((k, w) for k, w, _note in BY_KEY[step]["choices"])


def note_of(step: str, choice: str) -> str | None:
    """What people often find, after a tap - None for an unknown choice."""
    for k, _w, note in BY_KEY.get(step, {}).get("choices", ()):
        if k == choice:
            return note
    return None


def clean_saved(saved) -> dict:
    """What's kept, checked: {"done": [...]} with only known steps (in
    STEPS' order), plus "finished" (an ISO date) when there is one. Anything
    else is dropped."""
    if not isinstance(saved, dict):
        return {"done": []}
    raw = saved.get("done")
    raw = set(raw) if isinstance(raw, (list, tuple)) else set()
    out = {"done": [k for k in STEP_KEYS if k in raw]}
    fin = saved.get("finished")
    if isinstance(fin, str):
        try:
            out["finished"] = date.fromisoformat(fin).isoformat()
        except ValueError:
            pass
    return out


def _put(prefs_data: dict, kept: dict) -> dict:
    out = dict(prefs_data or {})
    if kept["done"] or kept.get("finished"):
        out[PREF] = kept
    else:
        out.pop(PREF, None)
    return out


def with_step(prefs_data: dict, step: str) -> dict:
    """The person's settings with one step walked through. Unknown steps
    change nothing."""
    out = dict(prefs_data or {})
    if step not in BY_KEY:
        return out
    kept = clean_saved(out.get(PREF))
    kept["done"] = kept["done"] + [step]
    return _put(out, clean_saved(kept))


def with_finished(prefs_data: dict, day: date) -> dict:
    """The person's settings with the day they finished (the latest time)."""
    out = dict(prefs_data or {})
    kept = clean_saved(out.get(PREF))
    kept["finished"] = day.isoformat()
    return _put(out, clean_saved(kept))


def cleared(prefs_data: dict) -> dict:
    """The person's settings without the rehearsal."""
    out = dict(prefs_data or {})
    out.pop(PREF, None)
    return out


def done_steps(saved) -> list[str]:
    return clean_saved(saved)["done"]


def finished_on(saved) -> date | None:
    fin = clean_saved(saved).get("finished")
    return date.fromisoformat(fin) if fin else None


def links() -> list[tuple[str, str]]:
    """Every (label, url) the steps link to."""
    return [lk for s in STEPS for lk in s["links"]]


def host(url: str) -> str:
    return urlparse(url).netloc.lower()


def step_text(step: str) -> str:
    """Every word one step shows."""
    s = BY_KEY[step]
    parts = [s["title"], s["situation"]]
    for _k, words, note in s["choices"]:
        parts += [words, note]
    parts += [label for label, _url in s["links"]]
    return "\n".join(parts)


def all_text() -> str:
    """Every word the section shows from here (for the tests' word checks)."""
    parts = [TITLE, INTRO, FAMILY, PRIVATE, NOT_ADVICE, TAP_LEAD, NOTE_LEAD, NO_RIGHT_ANSWER,
             START, AGAIN, NEXT, FINISH, LEAVE, END_TITLE, END]
    parts += [t for pair in END_LINKS.values() for t in pair]
    parts += [step_text(k) for k in STEP_KEYS]
    return "\n".join(parts)
