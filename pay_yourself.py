"""Pay yourself (ROADMAP R11): a monthly "paycheck" picture from someone's own
savings - the income their investments are estimated to pay each month
(income.py's next 12 months, plus cash interest from an imported activity
history) under a rule of thumb the person picks from a fixed, named list.

The careful version (docs/LEGAL_GATES.md section 6; L3 review before it's on
anywhere but staging - flags.FEATURES["pay_yourself"] needs gate L3 as well
as its flag):
- The person picks the rule. Nothing is pre-selected but "income only", the
  most descriptive one (it only adds up what the holdings pay), and nothing
  says one rule is better than another. Listed income only first, then the
  rates lowest first.
- Every figure is "under the rule you picked"; the 20% fall is a labelled
  hypothetical scenario, not a forecast; nothing tells anyone to take money
  out, or says an amount is affordable or lasts. The questions to ask a
  licensed professional are questions only, the same for everyone.
- What's kept: the picked rule's key in the person's own settings (PREF) -
  never an amount, never free text.

Pure logic and fixed text: standard library only. No Streamlit, no
database, no network (tests/test_repo_rules.py's calculation layer). The view
is views/pay_yourself.py.
"""

from __future__ import annotations

from datetime import date

PREF = "pay_yourself"   # user_prefs key: {"rule": one of RULE_KEYS}
INCOME_ONLY = "income_only"
DEFAULT = INCOME_ONLY
DROP_PCT = 20.0         # the hypothetical fall: a labelled scenario, not a forecast

# The fixed list, in this order: income only (the default), then the rates
# lowest first. "pct" is the share of today's balance a year; None for income
# only. Names and notes are the same for everyone.
RULES = (
    {"key": INCOME_ONLY, "pct": None,
     "name": "Only what the investments pay out (income only)",
     "about": "Adds up the dividends and interest your holdings are estimated to pay. "
              "Nothing is sold under this rule, so the amount changes month to month."},
    {"key": "pct_3", "pct": 3.0,
     "name": "A fixed 3% of today's balance a year",
     "about": "A rule of thumb a little below the 4% rule. The same amount each month, a "
              "twelfth of 3% of today's balance."},
    {"key": "pct_4", "pct": 4.0,
     "name": "A fixed 4% of today's balance a year (the \"4% rule\", a rule of thumb from "
             "studies of past markets)",
     "about": "Studies of past US markets looked at taking about 4% of the starting balance "
              "in the first year. Here it's 4% of today's balance, a twelfth each month."},
    {"key": "pct_5", "pct": 5.0,
     "name": "A fixed 5% of today's balance a year",
     "about": "A rule of thumb a little above the 4% rule. The same amount each month, a "
              "twelfth of 5% of today's balance."},
)
BY_KEY = {r["key"]: r for r in RULES}
RULE_KEYS = tuple(r["key"] for r in RULES)

# ---- fixed text (every line here is checked by tests/test_pay_yourself.py) -- #
TITLE = "Pay yourself: your savings as a monthly paycheck"
INTRO = ("This shows what your own investments are estimated to pay each month, and how "
         "much a monthly paycheck from your savings would be under a rule of thumb you pick "
         "from the list. Hypothetical, not a forecast, not advice. Northwend doesn't pick a rule "
         "for anyone, and it doesn't know your taxes, other income or spending.")
PICK_LABEL = "A rule of thumb to look at"
PICK_HELP = ("These are general rules of thumb, the same list for everyone, listed income "
             "only first and then by rate. None of them is a plan for you, and Northwend "
             "doesn't rank them.")
KEPT_LINE = "Only the rule you picked is kept, in your own settings - never an amount."
ADVISOR_LEAD = ("For you as their advisor: this uses your client's own holdings. The rule "
                "you pick here isn't saved and isn't shown to them.")
NO_HOLDINGS = ("Once your holdings are in, this shows what they're estimated to pay each "
               "month. For now, here is what each rule means for every {example} invested.")
PRETEND = ("Your dollar amounts are pretend, so here is what each rule means for every "
           "{example} invested. The months your holdings pay in are still shown.")
EXAMPLE_LINE = ("Under the rule you picked, every {example} invested gives about {monthly} a "
                "month ({yearly} a year).")
EXAMPLE_INCOME_ONLY = ("Under the rule you picked, the paycheck is what the holdings pay out, "
                       "so it depends on the holdings themselves.")

STAT_PAYCHECK = "Monthly paycheck, under the rule you picked"
STAT_PAYCHECK_INCOME = "Average month, under the rule you picked"
STAT_THIN = "The month with the smallest payouts"
STAT_DROP = "If investments fell 20% (hypothetical)"

PAYCHECK_PCT = ("Under the rule you picked ({name_short}), the paycheck is about {monthly} a "
                "month - {yearly} a year, {pct}% of today's {balance}.")
PAYCHECK_INCOME = ("Under the rule you picked (income only), the next 12 months add up to "
                   "about {yearly} - an average of {monthly} a month, but some months pay "
                   "much more than others.")
NO_INCOME = ("Your holdings don't show any dividends or interest yet, so under the rule you "
             "picked there's nothing to show. Payment dates are added each evening, when "
             "price history is updated.")

THIN_INCOME = ("Under the rule you picked, the month with the smallest payouts is {thin}, at "
               "about {thin_amount}; the month with the largest is {full}, at about "
               "{full_amount}.")
THIN_PCT = ("The month with the smallest payouts is {thin}: your investments are estimated to "
            "pay about {thin_amount} that month. Under the rule you picked, the other "
            "{from_balance} of that month's paycheck would come from the balance - selling "
            "some investments.")
THIN_NAME_ONLY = ("Your holdings are estimated to pay the least in {thin} and the most in "
                  "{full}.")
COVERED_PCT = ("Under the rule you picked, the estimated payouts cover the whole paycheck in "
               "every month. In months that pay more, the extra isn't added on top of the "
               "paycheck.")
PAYOUT_NOTE = ("Payouts are estimated from each holding's last year of payments at today's "
               "share count, by the month a payment is announced to go out (the money "
               "usually arrives a few weeks later). Companies and funds change their payouts.")

DROP_LABEL = "Hypothetical, not a forecast, not advice"
DROP_PCT_LINE = ("If your investments fell 20%, this rule would give about {after} a month "
                 "instead of {before}, under the rule you picked ({pct}% of the lower "
                 "balance). In the studies behind the 4% rule, the dollar amount was set in "
                 "the first year and then kept the same. Kept at {before} a month, it would "
                 "be {kept_pct}% of the lower balance a year.")
DROP_INCOME_LINE = ("If your investments fell 20%, this rule would give the same estimate "
                    "of about {monthly} a month on average, under the rule you picked: "
                    "payouts are paid per share you own, so lower prices alone don't change "
                    "them. But companies and funds can cut their payouts, and in some past "
                    "market falls many did.")
DROP_NOTE = ("A 20% fall is just an example number, not a forecast of what markets will do. "
             "If your mix is entered, the Stress test tab shows how it would have done in "
             "three real market falls from the past.")

NOT_INCLUDED = ("Not included: taxes, fees, inflation, and income from elsewhere - Social "
                "Security or a pension, for example. Under a percentage rule, the balance "
                "also goes up and down with markets, so next year's amount would be "
                "different.")

QUESTIONS_TITLE = "Questions to ask a licensed professional about retirement income"
QUESTIONS_LEAD = ("Questions people often bring to a tax professional or financial planner "
                  "they choose. Northwend can't answer them for your case.")
QUESTIONS = (
    "How are withdrawals from each of my account types taxed - a traditional IRA or "
    "401(k), a Roth account, a taxable account?",
    "Does the order I take money from my accounts change the taxes I pay?",
    "When do required minimum distributions (RMDs) start for me, and how do they fit with "
    "a rule of thumb like this one?",
    "How does the age I start Social Security change my monthly benefit, and how does it "
    "fit with what my investments pay?",
    "How would a rule like this keep up with inflation over the years?",
    "What happens to a paycheck like this if markets fall early in retirement?",
    "Are there penalties or fees for taking money out of any of my accounts before a "
    "certain age?",
    "Could my retirement income change what I pay for Medicare or how my Social Security "
    "is taxed?",
)

TABLE_COLUMNS = ("Month", "Paid by your investments", "From the balance, under the rule",
                 "Paycheck, under the rule you picked")


# --------------------------------------------------------------------------- #
# the rule and the saved pick
# --------------------------------------------------------------------------- #
def rule(key) -> dict:
    """The rule for `key`; income only for anything unknown."""
    return BY_KEY.get(key) or BY_KEY[DEFAULT]


def short_name(key) -> str:
    """'income only' or '3% a year', for a sentence."""
    r = rule(key)
    return "income only" if r["pct"] is None else f"{r['pct']:g}% a year"


def saved_rule(prefs_data) -> str:
    """The rule key kept in the person's settings, else the default."""
    kept = (prefs_data or {}).get(PREF)
    key = kept.get("rule") if isinstance(kept, dict) else None
    return key if key in BY_KEY else DEFAULT


def with_rule(prefs_data, key) -> dict:
    """Settings with the picked rule kept (a known key only; nothing else is
    ever kept). The default is kept too - picking it is a pick."""
    out = dict(prefs_data or {})
    if key in BY_KEY:
        out[PREF] = {"rule": key}
    return out


def cleared(prefs_data) -> dict:
    out = dict(prefs_data or {})
    out.pop(PREF, None)
    return out


# --------------------------------------------------------------------------- #
# the arithmetic
# --------------------------------------------------------------------------- #
def month_label(month: str) -> str:
    """'2026-11' -> 'Nov 2026'."""
    y, m = (int(x) for x in str(month)[:7].split("-"))
    return date(y, m, 1).strftime("%b %Y")


def income_ahead(schedule_months, received_months=None) -> list[dict]:
    """The next 12 months of estimated payouts: income.schedule()'s
    dividend months, plus the cash interest (no symbol) the brokerage paid
    in the same calendar month last year (income.received(), if an activity
    history was imported). [{"month", "dividends", "interest", "total"}]."""
    interest_by_cal = {}
    for r in received_months or []:
        cash = float((r.get("by_symbol") or {}).get("Interest") or 0.0)
        if cash:
            cal = str(r["month"])[5:7]
            interest_by_cal[cal] = interest_by_cal.get(cal, 0.0) + cash
    out = []
    for r in schedule_months or []:
        divs = float(r.get("total") or 0.0)
        interest = interest_by_cal.get(str(r["month"])[5:7], 0.0)
        out.append({"month": r["month"], "dividends": round(divs, 2),
                    "interest": round(interest, 2), "total": round(divs + interest, 2)})
    return out


def paycheck(key, balance, months) -> dict:
    """The paycheck under rule `key` on `balance`, with `months` from
    income_ahead(). Returns {"rule", "pct", "monthly" (steady for a rate
    rule, the average for income only), "yearly", "months": [{"month",
    "income", "from_balance", "total"}], "thin", "full" (the months with the
    least and most payouts, None without any payouts), "covered" (payouts
    cover every month's paycheck - rate rules only)}."""
    r = rule(key)
    balance = max(0.0, float(balance or 0.0))
    rows = []
    if r["pct"] is None:
        for m in months:
            inc = max(0.0, float(m["total"]))
            rows.append({"month": m["month"], "income": round(inc, 2), "from_balance": 0.0,
                         "total": round(inc, 2)})
        yearly = round(sum(x["total"] for x in rows), 2)
        monthly = round(yearly / 12, 2)
    else:
        yearly = round(balance * r["pct"] / 100, 2)
        monthly = round(yearly / 12, 2)
        for m in months:
            inc = max(0.0, float(m["total"]))
            part = min(inc, monthly)
            rows.append({"month": m["month"], "income": round(part, 2),
                         "from_balance": round(monthly - part, 2), "total": monthly})
    paying = [m for m in months if float(m["total"]) > 0]
    thin = full = None
    if paying:
        thin = min(months, key=lambda m: float(m["total"]))
        full = max(months, key=lambda m: float(m["total"]))
    covered = (r["pct"] is not None and bool(rows) and monthly > 0
               and all(x["from_balance"] <= 0 for x in rows))
    return {"rule": r["key"], "pct": r["pct"], "monthly": monthly, "yearly": yearly,
            "months": rows, "thin": thin, "full": full, "covered": covered}


def after_drop(key, balance, months, drop_pct: float = DROP_PCT) -> dict:
    """The hypothetical: the paycheck under rule `key` if the investments'
    value fell `drop_pct`%. {"before", "after" (monthly), "lower_balance",
    "kept_pct" (today's amount as a % of the lower balance - rate rules;
    None for income only)}. Income only: payouts are per share, so the
    estimate itself doesn't move with prices."""
    r = rule(key)
    before = paycheck(key, balance, months)
    lower = max(0.0, float(balance or 0.0)) * (1 - drop_pct / 100)
    if r["pct"] is None:
        return {"before": before["monthly"], "after": before["monthly"],
                "lower_balance": round(lower, 2), "kept_pct": None}
    after = round(lower * r["pct"] / 100 / 12, 2)
    kept = (before["yearly"] / lower * 100) if lower > 0 else None
    return {"before": before["monthly"], "after": after, "lower_balance": round(lower, 2),
            "kept_pct": round(kept, 2) if kept is not None else None}


def pct_text(v) -> str:
    """'4', '3.5', '6.25' - a percent without trailing zeros."""
    return f"{round(float(v), 2):g}"


# --------------------------------------------------------------------------- #
# every line people read, filled with example figures (for the tests)
# --------------------------------------------------------------------------- #
def sample_texts() -> list[str]:
    """Every fixed line with its placeholders filled in, for the banned-word
    and conclusion-policy checks."""
    f = {"example": "$100,000", "monthly": "$333", "yearly": "$4,000", "name_short":
         "4% a year", "pct": "4", "balance": "$250,000", "thin": "Nov 2026",
         "thin_amount": "$12", "full": "Dec 2026", "full_amount": "$410",
         "from_balance": "$321", "after": "$267", "before": "$333", "kept_pct": "5"}
    lines = [TITLE, INTRO, PICK_LABEL, PICK_HELP, KEPT_LINE, ADVISOR_LEAD, NO_HOLDINGS,
             PRETEND, EXAMPLE_LINE, EXAMPLE_INCOME_ONLY, STAT_PAYCHECK, STAT_PAYCHECK_INCOME,
             STAT_THIN, STAT_DROP, PAYCHECK_PCT, PAYCHECK_INCOME, NO_INCOME, THIN_INCOME,
             THIN_PCT, THIN_NAME_ONLY, COVERED_PCT, PAYOUT_NOTE, DROP_LABEL, DROP_PCT_LINE,
             DROP_INCOME_LINE, DROP_NOTE, NOT_INCLUDED, QUESTIONS_TITLE, QUESTIONS_LEAD, *QUESTIONS,
             *TABLE_COLUMNS]
    for r in RULES:
        lines += [r["name"], r["about"]]
    return [s.format(**f) for s in lines]


def all_text() -> str:
    return "\n".join(sample_texts())
