"""Northwend's glossary (docs/AI_PLAN.md section 9, row 5 - rules, not AI):
plain-English meanings of the words the app uses, owner-written, one or two
sentences each. Education only: general definitions, never a figure for
anyone, never a named fund, never what anyone ought to do. A DRAFT for the
owner to review (it was ai_library.GLOSSARY; AI_PLAN 5.1: "owner-written,
about 60 terms").

One text for everyone, used in two places so they can't drift apart:
- the app (flag `glossary`, flags.py): a "What does this mean?" popover
  beside the words on the pages where they show most (dashboard.py
  what_this_means(): Home's allocation, the Fee check, Income, Learn's
  "Open your account") and the whole list, A to Z, in Learn's basics;
- Ask Northwend's library (ai_library.GLOSSARY is this TERMS), which it
  reads before it answers.

A word that isn't here shows nothing (find() gives None). Learn's "Look up
another word" box sends an unknown one, the term alone, to Ask Northwend for
a general explanation (AI_PLAN's "AI fallback", cheap tier): glossary_ai.py,
flag `glossary_ai`.

Pure data and small lookups: standard library only, no Streamlit.
"""

from __future__ import annotations

import re

# (term, meaning). Each meaning starts in lower case so it reads after
# "term:" (the AI library's list); sentence() capitalises it for people.
TERMS = (
    ("Asset class", "a broad kind of investment. Northwend uses four: stocks, bonds, cash "
                    "and other (real estate, commodities and the rest)."),
    ("Asset allocation (mix)", "how money is split across asset classes, as percentages."),
    ("Stock (share, equity)", "a small piece of ownership in a company. Its price moves with "
                              "how investors value the company."),
    ("Bond", "a loan to a government or company that pays interest and returns the amount "
             "lent at the end. Usually moves less than stocks."),
    ("Cash", "money in a bank, a brokerage's sweep account or a money market fund. Steady "
             "in value; what it earns changes with interest rates."),
    ("Money market fund", "a fund holding very short-term loans; it aims to keep a steady "
                          "price and pays interest. Not bank-insured."),
    ("Sweep account", "where a brokerage parks uninvested cash by default. What it pays "
                      "varies a lot between brokerages."),
    ("High-yield savings account", "a bank savings account paying a higher rate than most; "
                                   "usually insured up to legal limits."),
    ("Certificate of deposit (CD)", "a bank deposit locked for a set time at a set rate."),
    ("Treasury bill", "a short-term loan to the US government, a year or less."),
    ("Fund", "a pool of many people's money invested in many holdings at once."),
    ("Mutual fund", "a fund bought from the fund company at its end-of-day price."),
    ("Exchange-traded fund (ETF)", "a fund that trades on an exchange like a stock, at "
                                   "prices that move during the day."),
    ("Index fund", "a fund that follows a market index - a set list of holdings - instead of "
                   "having managers pick. Usually low-cost and broad."),
    ("Index", "a list of holdings that stands for a market, like the S&P 500 (about 500 "
              "large US companies) or a total-market index."),
    ("Actively managed fund", "a fund whose managers choose what to hold, trying to beat an "
                              "index. Usually costs more than an index fund."),
    ("Target-date fund", "one fund holding stocks and bonds that slowly shifts toward bonds "
                         "as its target year (often a retirement year) gets closer - the "
                         "glide path."),
    ("Balanced fund", "one fund holding a fixed mix of stocks and bonds."),
    ("Expense ratio", "a fund's yearly fee, as a percentage of what you hold, taken out of the "
                      "fund's value a little each day - there's no bill to see."),
    ("Diversification", "spreading money across many holdings and kinds, so no single one can "
                        "sink the whole."),
    ("Concentration", "a large share in one holding. Northwend points out any single position "
                      "above a set share of the portfolio, as a fact."),
    ("Overlap", "two funds holding many of the same companies, so the money is less spread "
                "out than the number of funds suggests."),
    ("Rebalancing", "moving a mix back toward its target - by where new money goes, or by "
                    "selling some of what grew."),
    ("Drift", "how far a mix has moved from its target as prices change, in points."),
    ("Band", "the number of points either way a person lets their mix drift before they look "
             "at it - their own rule."),
    ("Large, mid and small cap", "companies grouped by their total market value."),
    ("Growth and value", "two styles: companies expected to grow fast, and companies priced "
                         "low for what they earn."),
    ("International stocks", "companies based outside the US. Emerging markets are the "
                             "faster-changing economies among them."),
    ("Home bias", "the habit of holding mostly companies from one's own country."),
    ("Dividend", "a share of a company's profits paid to its shareholders."),
    ("Dividend yield", "a year's dividends as a percentage of today's price."),
    ("Ex-dividend date", "the day from which a new buyer of a stock or fund doesn't get its "
                         "next dividend; whoever held it the day before does."),
    ("Yield", "the income an investment pays in a year - dividends or interest - as a "
              "percentage of its price."),
    ("Interest rate risk", "bond prices fall when interest rates rise, and longer bonds move "
                           "more - measured by duration."),
    ("Inflation", "prices rising over time, so money buys less."),
    ("Real return", "a return after inflation; the nominal return is before it."),
    ("Total return", "price change plus dividends or interest."),
    ("Compound growth", "growth on earlier growth: returns that stay invested earn returns of "
                        "their own."),
    ("Volatility", "how much and how fast prices move up and down."),
    ("Bear market", "a fall of 20% or more from a high; a correction is 10% or more."),
    ("Recovery", "the time it takes to get back to an earlier high after a drop."),
    ("Sequence risk", "the risk that a big drop comes just before or as withdrawals begin, "
                      "when there's less time to recover."),
    ("Risk tolerance", "how comfortable someone is with ups and downs, in feeling and in money."),
    ("Time horizon", "how long until the money is needed."),
    ("Dollar-cost averaging", "investing a set amount on a schedule, whatever prices do."),
    ("Emergency fund", "savings kept for surprises, often several months of expenses."),
    ("Employer match", "money an employer adds to a workplace retirement plan when the person "
                       "puts some in, often up to a share of pay."),
    ("Vesting", "when employer money in a plan becomes fully the person's own."),
    ("401(k) and 403(b)", "workplace retirement plans: money goes in from pay, often before "
                          "tax, with yearly limits."),
    ("Traditional IRA", "an individual retirement account; contributions may lower taxes now, "
                        "and withdrawals are taxed later."),
    ("Roth IRA", "an individual retirement account funded with taxed money; qualified "
                 "withdrawals later are tax-free. Income limits apply."),
    ("Roth 401(k)", "the Roth version of a workplace plan."),
    ("Health savings account (HSA)", "a tax-advantaged account for health costs, with a "
                                     "high-deductible health plan."),
    ("Taxable brokerage account", "a regular investing account with no special tax treatment "
                                  "and no withdrawal rules."),
    ("Capital gain", "the rise in value of something sold; taxed differently when held over a "
                     "year."),
    ("Cost basis", "what was paid for an investment, used to work out a gain or loss."),
    ("Required minimum distribution (RMD)", "the yearly amount that must come out of many "
                                            "retirement accounts from a set age."),
    ("Withdrawal rate", "the share of a portfolio taken out each year."),
    ("Brokerage", "a company that holds investments and carries out buys and sells."),
    ("Fractional shares", "buying part of a share, so any amount can be invested."),
    ("Market and limit orders", "a market order buys or sells at the current price; a limit "
                                "order only at a set price or better."),
    ("Hypothetical projection", "an illustration of the future at an assumed steady rate. "
                                "Real returns vary year to year; it is not a prediction."),
    ("Investment adviser", "a firm (or its representative) registered to give investment "
                           "advice for a fee; many act as fiduciaries, bound to put the "
                           "client's interest first."),
    ("Broker-dealer", "a firm that buys and sells investments for customers."),
    ("Financial planner", "someone who helps with a whole money picture; the title alone "
                          "isn't regulated, credentials vary."),
)

# Other ways the app (or a person) writes a term -> the term above. The term
# itself, its words before any "(...)" and each name inside the brackets are
# found without being listed here.
ALIASES = {
    "allocation": "Asset allocation (mix)",
    "stocks": "Stock (share, equity)",
    "bonds": "Bond",
    "etfs": "Exchange-traded fund (ETF)",
    "mutual funds": "Mutual fund",
    "index funds": "Index fund",
    "rebalance": "Rebalancing",
    "drift band": "Band",
    "401(k)": "401(k) and 403(b)",
    "403(b)": "401(k) and 403(b)",
    "ira": "Traditional IRA",
    "roth": "Roth IRA",
    "brokerage account": "Taxable brokerage account",
    "correction": "Bear market",
    "market order": "Market and limit orders",
    "limit order": "Market and limit orders",
    "ex-date": "Ex-dividend date",
}


def _key(text) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _index() -> dict:
    by_term = {t: (t, m) for t, m in TERMS}
    out = {}
    for term, meaning in TERMS:
        out.setdefault(_key(term), by_term[term])
        out.setdefault(_key(term.split(" (")[0]), by_term[term])
        inside = re.search(r" \(([^)]*)\)$", term)
        if inside:
            for alt in inside.group(1).split(","):
                out.setdefault(_key(alt), by_term[term])
    for alias, term in ALIASES.items():
        out.setdefault(_key(alias), by_term[term])
    return out


_INDEX = _index()


def find(word) -> tuple[str, str] | None:
    """(term, meaning) for a word as the app writes it ("ETF", "expense
    ratio", "RMD"), or None when the glossary doesn't have it."""
    return _INDEX.get(_key(word))


def sentence(meaning: str) -> str:
    """A meaning as a sentence for people: capital first letter, full stop."""
    text = meaning.strip()
    text = text[:1].upper() + text[1:]
    return text if text.endswith((".", "?", "!")) else text + "."


def pick(words) -> list[tuple[str, str]]:
    """[(term, sentence)] for the words the glossary has, in the order
    given, each term once. Unknown words are left out."""
    out, seen = [], set()
    for w in words:
        hit = find(w)
        if hit and hit[0] not in seen:
            seen.add(hit[0])
            out.append((hit[0], sentence(hit[1])))
    return out


def everything() -> list[tuple[str, str]]:
    """Every term, A to Z, as (term, sentence) - Learn's full list."""
    return sorted(((t, sentence(m)) for t, m in TERMS), key=lambda r: r[0].lower())
