"""Trail Forks (ROADMAP R8): a calm route per life event - a new job, a
layoff, a new baby, an inheritance, a divorce, the death of a parent. Each
route says what changes, what to gather, what to ask (and whom: HR, the plan
administrator, a tax preparer, an attorney, the estate's executor) and what
not to rush, and ends pointing into the Walk (the monthly walk, checkin.py,
when flag `walk` is on; the Plan page otherwise). The page is
views/trail_forks.py, on the Account page under Lost & Found, behind flag
`trail_forks`.

Education, never advice (docs/PRINCIPLES.md 2; ROADMAP's risk note for R8):
divorce, inheritance and a death are legal and tax territory, so those
routes stay with what to ask a professional - never what to do. A loss or a
divorce opens softly. No deadlines, ages or dollar figures are invented:
where a real rule has a timeline, the question is "are there any deadlines?"
for the plan administrator, HR or the executor. No funds or products are
named, nothing is ranked. Every link goes to an official government site
(OFFICIAL_SITES; a test checks).

The one thing kept: in the person's own settings (prefs PREF), which forks
they've marked as theirs and which of that fork's fixed steps they've
ticked - keys only, never free text, never a date, an amount or a name.
Unmarking a fork drops its ticks. Never shown to an advisor, never sent to
the AI. Pure logic, no Streamlit, no database.
"""

from __future__ import annotations

from urllib.parse import urlparse

PREF = "trail_forks"   # user_prefs key: {"forks": [fork, ...], "done": {fork: [step, ...]}}

# every link here goes to one of these: U.S. government sites only
OFFICIAL_SITES = (
    "www.irs.gov",               # IRS
    "www.dol.gov",               # U.S. Department of Labor
    "www.healthcare.gov",        # the federal health insurance marketplace
    "www.ssa.gov",               # Social Security Administration
    "www.consumerfinance.gov",   # Consumer Financial Protection Bureau
    "www.usa.gov",               # the federal government's own guide
)

INTRO = ("Life changes - a new job, a baby, a loss - and money questions come with them. "
         "Pick the fork you're on: each one shows what changes, what to gather, what to ask "
         "(and whom), and what not to rush.")
PRIVATE = ("Which forks you mark and the steps you tick are kept with your own settings. "
           "Only you see them - not an advisor - and none of it is sent to the AI. Nothing "
           "you write is kept: there's nowhere to write.")
NOT_ADVICE = ("Educational, not advice: Northwend never says what to do at a life event. For "
              "your own situation, an attorney, a tax preparer or the plan administrator can "
              "help.")
MINE_LABEL = "This is a fork I'm on"
MINE_HELP = "Marks it as yours, so you can tick the steps as you go. Only you see it."

# who to ask (a fork's questions are grouped under these)
HR = "HR or the benefits team"
PLAN_ADMIN = "The plan administrator"
FIRM = "The plan administrator or the account's firm"
OLD_PLAN = "Your old plan's administrator"
TAX = "A tax preparer"
ATTORNEY = "An attorney"
EXECUTOR = "The estate's executor"
UNEMPLOYMENT = "Your state's unemployment office"
SOCIAL_SECURITY = "Social Security"

# headings inside each fork
CHANGES = "What changes"
GATHER = "What to gather"
ASK = "What to ask, and whom"
NOT_RUSH = "What not to rush"

# where each fork ends: into the Walk (flag walk), or the Plan without it
WALK_END = ("When things feel steadier, the monthly walk is a calm way to look at your plan "
            "again. Your investments don't have to change on the same day your life does.")
WALK_BUTTON = "Go to your monthly walk"
PLAN_END = ("When things feel steadier, your Plan is a calm place to look at your goal and "
            "mix again. Your investments don't have to change on the same day your life does.")
PLAN_BUTTON = "Open your Plan"

# a fork's pointer to another part of the Account page
SEE_ALSO = {
    "lost_found": ("Lost & Found, on this page, lays out an old 401(k)'s common choices side "
                   "by side, with questions to ask."),
    "account_map": ("When you're ready, your own account map, on this page, is a way to make "
                    "things simpler for your own family later on."),
}

# Each fork: key, title, icon, opening (one soft line), changes, gather
# ((step, words), ...), ask ((whom, ((step, question), ...)), ...), not_rush,
# links ((label, url), ...), see_also (keys of SEE_ALSO)
FORKS = (
    {"key": "new_job", "title": "A new job", "icon": ":material/work:",
     "opening": ("A new job brings new paperwork, and a few choices that are easy to make "
                 "quickly on the first day. Most of them can wait until you understand them."),
     "changes": (
         "Your paycheck, and how much tax is held back from it - the W-4 you fill in tells "
         "the employer how much to withhold.",
         "Health insurance and benefits such as an HSA or FSA may change, and may start on a "
         "different day than your first day.",
         "A new workplace retirement plan, with its own choices, fees and match rules. Your "
         "old plan stays where it is until you decide what to do with it.",
     ),
     "gather": (
         ("offer", "Your offer letter and the benefits guide"),
         ("w4", "Your W-4, and last year's tax return to compare"),
         ("plan_docs", "The new plan's summary plan description and its list of investment "
                       "choices"),
         ("old_statement", "A recent statement from your old job's plan, if you had one"),
         ("beneficiaries", "Who you'd like to name as beneficiaries on the new plan and "
                           "insurance"),
     ),
     "ask": (
         (HR, (
             ("start", "When does each benefit start, and is there a window for choosing "
                       "them?"),
             ("match", "Does the plan match what I put in, and when is the match mine to "
                       "keep?"),
             ("auto", "Will I be signed up for the plan automatically, and at what amount?"),
             ("roll_in", "Does the plan accept money from an old plan or an IRA?"),
         )),
         (OLD_PLAN, (
             ("old_options", "What are my choices for the money in the old plan, and are "
                             "there any deadlines?"),
         )),
         (TAX, (
             ("withholding", "Does my withholding look about right for the year, with the "
                             "change of job?"),
         )),
     ),
     "not_rush": (
         "Choosing investments in the new plan - if you're signed up automatically, there's "
         "time to read the choices first.",
         "Moving an old 401(k). It can stay where it is while you look at the choices.",
         "Cashing out an old plan. It's usually taxed, and hard to undo.",
     ),
     "links": (
         ("Tax Withholding Estimator (IRS)",
          "https://www.irs.gov/individuals/tax-withholding-estimator"),
         ("Rollovers from retirement plans (IRS Topic 413)",
          "https://www.irs.gov/taxtopics/tc413"),
     ),
     "see_also": ("lost_found",)},

    {"key": "layoff", "title": "A layoff or job loss", "icon": ":material/work_off:",
     "opening": ("Losing a job is hard. A lot arrives at once, and not all of it needs an "
                 "answer today. This route helps you sort what has a date on it from what "
                 "can wait."),
     "changes": (
         "Your paycheck stops. The last one may include unused vacation or a severance "
         "payment - the employer can explain how theirs is worked out.",
         "Workplace health insurance usually ends. COBRA can let you keep the same coverage "
         "for a time, often at a higher cost, and losing coverage can also open a window to "
         "choose a plan through HealthCare.gov.",
         "Your 401(k) - the vested part - stays yours, and stays in the plan until you "
         "decide what to do with it.",
         "You may be able to get unemployment benefits from your state.",
     ),
     "gather": (
         ("letter", "Your separation letter or severance agreement, if there is one"),
         ("pay_stubs", "Your last pay stubs"),
         ("coverage_notice", "The notice of when your health coverage ends, and the COBRA "
                             "notice when it arrives"),
         ("statements", "Recent statements from your 401(k) and any HSA or FSA"),
         ("bills", "A rough list of your monthly bills, to see how long savings can cover "
                   "them"),
     ),
     "ask": (
         (HR, (
             ("coverage_end", "When exactly does my health coverage end, and what's in my "
                              "last paycheck?"),
             ("fsa", "Is there time left to claim FSA costs I already had?"),
         )),
         (UNEMPLOYMENT, (
             ("eligible", "Am I eligible for unemployment benefits, and how and when do I "
                          "apply?"),
         )),
         (PLAN_ADMIN, (
             ("plan_options", "What are my choices for my 401(k), and are there any "
                              "deadlines?"),
             ("loan", "If I have a loan from the plan, what happens to it now that I've "
                      "left?"),
         )),
         (ATTORNEY + ", if there's an agreement to sign", (
             ("agreement", "What does this severance agreement ask me to give up, and how "
                           "long do I have to review it?"),
         )),
     ),
     "not_rush": (
         "Cashing out your 401(k) to cover bills. It's usually taxed as income, and an extra "
         "tax may apply before retirement age - ask the plan administrator or a tax preparer "
         "first.",
         "Signing a severance agreement before you've read it, or had it read.",
         "Selling investments just to have cash in hand, if your emergency savings can carry "
         "you for now.",
     ),
     "links": (
         ("How to file for unemployment insurance (U.S. Department of Labor)",
          "https://www.dol.gov/general/topic/unemployment-insurance"),
         ("Unemployment benefits (USA.gov)", "https://www.usa.gov/unemployment-benefits"),
         ("Keeping your health coverage: COBRA (U.S. Department of Labor)",
          "https://www.dol.gov/general/topic/health-plans/cobra"),
         ("Health coverage if you're unemployed (HealthCare.gov)",
          "https://www.healthcare.gov/unemployed/"),
         ("The extra tax on early withdrawals (IRS Topic 558)",
          "https://www.irs.gov/taxtopics/tc558"),
     ),
     "see_also": ("lost_found",)},

    {"key": "new_baby", "title": "A new baby", "icon": ":material/child_care:",
     "opening": ("Congratulations. A new baby changes a lot at once - money is only a small "
                 "part of it, and most of it can be sorted in the quiet moments."),
     "changes": (
         "Health insurance: a birth usually lets you add the baby to your plan, or change "
         "plans, outside the usual season. The plan can tell you its window.",
         "Taxes: a child can change your withholding and the credits you may be able to "
         "claim.",
         "Leave from work, paid or unpaid, depending on your employer and your state.",
         "Who depends on you: life insurance, beneficiaries and a will start to matter more.",
     ),
     "gather": (
         ("birth_cert", "The birth certificate and the baby's Social Security number (the "
                        "hospital often helps you apply for it)"),
         ("health_plan", "Your health plan's details, to add the baby"),
         ("leave_policy", "Your employer's leave policy"),
         ("beneficiaries", "The beneficiary forms on your retirement accounts and life "
                           "insurance"),
         ("budget", "A look at the monthly budget with childcare in it"),
     ),
     "ask": (
         (HR, (
             ("add_baby", "How do I add the baby to my health plan, and are there any "
                          "deadlines?"),
             ("leave", "What leave can I take, and is any of it paid?"),
             ("dependent_care", "Is there a dependent care FSA, and how does it work?"),
         )),
         (TAX, (
             ("credits", "Which credits might apply to us, and does my withholding need a "
                         "change?"),
         )),
         (ATTORNEY, (
             ("will", "Do we need a will, and how do we name a guardian?"),
         )),
     ),
     "not_rush": (
         "Life insurance or a savings product offered to you in the first busy weeks - "
         "there's time to read and compare.",
         "Opening a college savings account. It can be opened any time, once you've read "
         "how each kind works.",
     ),
     "links": (
         ("Child Tax Credit (IRS)",
          "https://www.irs.gov/credits-deductions/individuals/child-tax-credit"),
         ("Tax Withholding Estimator (IRS)",
          "https://www.irs.gov/individuals/tax-withholding-estimator"),
         ("Family and Medical Leave (U.S. Department of Labor)",
          "https://www.dol.gov/agencies/whd/fmla"),
         ("Changing health plans after a life event (HealthCare.gov)",
          "https://www.healthcare.gov/coverage-outside-open-enrollment/"
          "special-enrollment-period/"),
     ),
     "see_also": ()},

    {"key": "inheritance", "title": "An inheritance", "icon": ":material/family_history:",
     "opening": ("If this comes after losing someone, go gently. What you've been left will "
                 "keep while you take the time you need."),
     "changes": (
         "What you receive may be cash, investments, a home, or an account such as an IRA or "
         "401(k) - and each kind has its own rules.",
         "An inherited retirement account has rules about how and when money is taken out. "
         "They depend on your relationship to the person and on the account.",
         "Taxes differ from one kind to another. A tax preparer can say which apply to you.",
         "The estate goes through steps run by the executor. What you receive, and when, "
         "follows those steps.",
     ),
     "gather": (
         ("letters", "Any letter from the executor, an attorney or the financial firm"),
         ("death_cert", "A copy of the death certificate, if a firm asks for one"),
         ("statements", "Statements for each account you're named on"),
         ("claim_forms", "The claim forms the firms send you"),
     ),
     "ask": (
         (EXECUTOR, (
             ("what_when", "What am I receiving, and roughly when will it come through?"),
             ("estate_debts", "Are there debts or taxes the estate still has to settle?"),
         )),
         (FIRM, (
             ("inherited_options", "What are my choices for this inherited account, and are "
                                   "there any deadlines?"),
             ("titling", "How will the account be set up in my name?"),
         )),
         (TAX, (
             ("taxes", "How is each part taxed, and when?"),
             ("basis", "What value is used for these investments for tax purposes?"),
         )),
         (ATTORNEY, (
             ("signing", "Is there anything I'm being asked to sign, and what does it mean "
                         "for me?"),
         )),
     ),
     "not_rush": (
         "Selling inherited investments or a home straight away. There's time to understand "
         "the taxes first.",
         "Taking all the money out of an inherited retirement account at once, before "
         "asking how it's taxed.",
         "Big purchases, gifts or loans to others while things settle.",
         "Products or offers that arrive soon after the news.",
     ),
     "links": (
         ("Retirement topics: beneficiaries (IRS)",
          "https://www.irs.gov/retirement-plans/plan-participant-employee/"
          "retirement-topics-beneficiary"),
         ("Survivors, executors and administrators (IRS Publication 559)",
          "https://www.irs.gov/publications/p559"),
     ),
     "see_also": ()},

    {"key": "divorce", "title": "A separation or divorce", "icon": ":material/call_split:",
     "opening": ("Going through a separation or divorce is a lot to carry. This route never "
                 "says what to do - it helps you gather what you'll be asked for, and what to "
                 "ask the people who can advise you."),
     "changes": (
         "How accounts, a home and debts are divided is worked out through the divorce "
         "itself - by agreement or by the court - with your attorney.",
         "A workplace retirement plan is usually divided with a special court order, a "
         "QDRO. The plan administrator can tell you what theirs needs.",
         "Your tax filing status, your withholding and who claims the children can change.",
         "Beneficiaries, insurance and the names on accounts may need a fresh look once "
         "things are final.",
     ),
     "gather": (
         ("statements", "Recent statements for every account - bank, brokerage, "
                        "retirement, HSA - in either name"),
         ("debts", "Statements for debts: mortgage, loans, credit cards"),
         ("tax_returns", "Recent tax returns"),
         ("pay_stubs", "Recent pay stubs for each of you"),
         ("beneficiaries", "A list of where each of you is named as a beneficiary"),
     ),
     "ask": (
         (ATTORNEY, (
             ("division", "How are accounts and debts usually divided where we live, and "
                          "what do you need from me?"),
             ("changes_allowed", "Is there anything I'm not allowed to change while this is "
                                 "going on?"),
             ("beneficiaries_when", "When can I change beneficiaries, and which ones?"),
         )),
         (PLAN_ADMIN, (
             ("qdro", "What does your plan need in a QDRO, and do you have a model order?"),
         )),
         (TAX, (
             ("filing", "How will this change my filing status and taxes this year?"),
             ("transfers", "Are any of the transfers between us taxed?"),
         )),
     ),
     "not_rush": (
         "Moving money out of joint accounts, or closing them, before talking with your "
         "attorney.",
         "Changing beneficiaries before your attorney says it's allowed.",
         "Cashing out a retirement account to cover costs - ask about the taxes first.",
         "Selling investments to make a split simpler.",
     ),
     "links": (
         ("Divorced or separated individuals (IRS Publication 504)",
          "https://www.irs.gov/publications/p504"),
         ("Retirement topics: QDROs (IRS)",
          "https://www.irs.gov/retirement-plans/plan-participant-employee/"
          "retirement-topics-qdro-qualified-domestic-relations-order"),
     ),
     "see_also": ()},

    {"key": "parent_death", "title": "The death of a parent", "icon": ":material/local_florist:",
     "opening": ("We're sorry for your loss. Nothing here needs to happen today. This route "
                 "is a gentle list for when you're ready - what to gather, and what to ask "
                 "the people helping you."),
     "changes": (
         "Someone - usually the executor named in the will - looks after the estate: "
         "gathering the accounts, paying debts and passing on what's left.",
         "An account or insurance policy that names you as a beneficiary usually comes to "
         "you directly, outside the will.",
         "Social Security is told of the death (the funeral home often does this), and some "
         "family members may be able to receive survivor benefits.",
         "A final tax return is usually filed for your parent, and the estate may file its "
         "own.",
         "Family members usually don't pay a parent's debts from their own money - the "
         "estate settles them. An attorney can say how that works where you are.",
     ),
     "gather": (
         ("death_certs", "Copies of the death certificate"),
         ("will", "The will or trust, if there is one, and who the executor is"),
         ("accounts", "A list of their accounts, insurance and debts - statements and mail "
                      "help"),
         ("ssn", "Their Social Security number, for the official forms - never for "
                 "Northwend"),
     ),
     "ask": (
         (EXECUTOR, (
             ("executor", "Who is the executor, and how can I help?"),
             ("named", "Am I named on any account or policy directly?"),
         )),
         (ATTORNEY, (
             ("probate", "Does the estate go through probate, and what are the steps?"),
             ("duties", "If I'm the executor, what am I responsible for?"),
         )),
         (TAX, (
             ("final_return", "Who files the final tax return, and does the estate file "
                              "one too?"),
         )),
         (FIRM, (
             ("claim", "How do I claim an account I'm named on, and are there any "
                       "deadlines?"),
         )),
         (SOCIAL_SECURITY, (
             ("survivor", "Has the death been reported, and is anyone in the family "
                          "eligible for survivor benefits?"),
         )),
     ),
     "not_rush": (
         "Paying a parent's debts from your own money - ask the executor or an attorney "
         "first.",
         "Selling the home or investments while you're grieving.",
         "Decisions about your own money. Your own plan can wait until you're ready.",
     ),
     "links": (
         ("Survivors benefits (Social Security)", "https://www.ssa.gov/benefits/survivors/"),
         ("Filing the final tax return of a deceased person (IRS)",
          "https://www.irs.gov/individuals/"
          "file-the-final-income-tax-returns-of-a-deceased-person"),
         ("Survivors, executors and administrators (IRS Publication 559)",
          "https://www.irs.gov/publications/p559"),
         ("Does a person's debt go away when they die? (CFPB)",
          "https://www.consumerfinance.gov/ask-cfpb/"
          "does-a-persons-debt-go-away-when-they-die-en-1463/"),
     ),
     "see_also": ("account_map",)},
)
BY_KEY = {f["key"]: f for f in FORKS}
FORK_KEYS = tuple(BY_KEY)
WHOM = (HR, PLAN_ADMIN, FIRM, OLD_PLAN, TAX, ATTORNEY, EXECUTOR, UNEMPLOYMENT, SOCIAL_SECURITY)


def steps(fork: str) -> tuple[str, ...]:
    """A fork's tickable steps, in order: what to gather, then what to ask."""
    f = BY_KEY.get(fork)
    if f is None:
        return ()
    return (tuple(k for k, _ in f["gather"])
            + tuple(k for _whom, qs in f["ask"] for k, _ in qs))


def clean_saved(saved) -> dict:
    """What's kept, checked: {"forks": [...], "done": {fork: [...]}} with only
    known forks (in FORKS' order) and, for each marked fork, only its own
    known steps (in order). Anything else is dropped."""
    if not isinstance(saved, dict):
        return {"forks": [], "done": {}}
    raw = saved.get("forks")
    raw = set(raw) if isinstance(raw, (list, tuple)) else set()
    forks = [k for k in FORK_KEYS if k in raw]
    done_raw = saved.get("done") if isinstance(saved.get("done"), dict) else {}
    done = {}
    for k in forks:
        ticks = done_raw.get(k)
        ticks = set(ticks) if isinstance(ticks, (list, tuple)) else set()
        kept = [s for s in steps(k) if s in ticks]
        if kept:
            done[k] = kept
    return {"forks": forks, "done": done}


def _put(prefs_data: dict, kept: dict) -> dict:
    out = dict(prefs_data or {})
    if kept["forks"]:
        out[PREF] = kept
    else:
        out.pop(PREF, None)
    return out


def with_fork(prefs_data: dict, fork: str, mine: bool) -> dict:
    """The person's settings with a fork marked as theirs, or not (which
    drops its ticks; no forks leaves no key behind). Unknown forks change
    nothing."""
    out = dict(prefs_data or {})
    if fork not in BY_KEY:
        return out
    kept = clean_saved(out.get(PREF))
    forks = set(kept["forks"])
    if mine:
        forks.add(fork)
    else:
        forks.discard(fork)
        kept["done"].pop(fork, None)
    return _put(out, clean_saved({"forks": list(forks), "done": kept["done"]}))


def with_step(prefs_data: dict, fork: str, step: str, done: bool) -> dict:
    """The person's settings with one step of a fork ticked or not. Only on
    a fork marked as theirs; unknown steps change nothing."""
    out = dict(prefs_data or {})
    kept = clean_saved(out.get(PREF))
    if fork not in kept["forks"] or step not in steps(fork):
        return out
    ticks = set(kept["done"].get(fork, ()))
    if done:
        ticks.add(step)
    else:
        ticks.discard(step)
    kept["done"][fork] = list(ticks)
    return _put(out, clean_saved(kept))


def cleared(prefs_data: dict) -> dict:
    """The person's settings without any forks or ticks."""
    out = dict(prefs_data or {})
    out.pop(PREF, None)
    return out


def mine(saved) -> list[str]:
    return clean_saved(saved)["forks"]


def done_steps(saved, fork: str) -> list[str]:
    return clean_saved(saved)["done"].get(fork, [])


def progress(saved, fork: str) -> tuple[int, int]:
    """(steps ticked, steps) for one fork."""
    return len(done_steps(saved, fork)), len(steps(fork))


def links() -> list[tuple[str, str]]:
    """Every (label, url) the forks link to."""
    return [lk for f in FORKS for lk in f["links"]]


def host(url: str) -> str:
    return urlparse(url).netloc.lower()


def fork_text(fork: str) -> str:
    """Every word one fork shows."""
    f = BY_KEY[fork]
    parts = [f["title"], f["opening"], *f["changes"], *(t for _, t in f["gather"]),
             *f["not_rush"], *(t for t, _ in f["links"]), *(SEE_ALSO[k] for k in f["see_also"])]
    for whom, qs in f["ask"]:
        parts += [whom, *(q for _, q in qs)]
    return "\n".join(parts)


def all_text() -> str:
    """Every word the section shows from here (for the tests' word checks)."""
    parts = [INTRO, PRIVATE, NOT_ADVICE, MINE_LABEL, MINE_HELP, CHANGES, GATHER, ASK,
             NOT_RUSH, WALK_END, WALK_BUTTON, PLAN_END, PLAN_BUTTON, *SEE_ALSO.values()]
    parts += [fork_text(k) for k in FORK_KEYS]
    return "\n".join(parts)
