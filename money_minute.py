"""Today's minute (flag `money_minute`): one small card a day on Home, under a
minute, at the top of the "This month" column (first on a phone).

Four kinds take turns:
- "What would you do?" - one of the preparedness drills' situations
  (drills.py, the same words): tap what you'd weigh first, never graded, then
  the drill's note on what people often think about.
- Quick question - a fixed question about how something works (fees maths,
  what an index fund is) with one answer, explained, sometimes with a link to
  the person's own page (the Fee check, their target mix).
- Myth or fact? - a fixed statement, then which it is and why.
- Teach it back - once a week, one of Learn's basics topics explained back in
  the person's own words, through Teach It Back itself (teach_back.py,
  views/teach_back.py: its AI check, its allowance and its rules). Only while
  flag `teach_back` is on.

The library is fixed and the same for everyone: no tickers, no forecasts,
never what to buy or sell; where a fact is stated, a link to an official
education site (SOURCES). Every line goes through the conclusion policy in
tests/test_money_minute.py.

The day's card is picked from the date and the login alone (pick): each
person has their own order of each kind, and nothing repeats until that
kind's whole list has been through once. The teach-back day is one weekday
per person.

"Days of learning" counts the days the person answered a minute. A missed day
costs nothing: the count only grows, and the week's seven marks just show
which days had one. No reminders.

What's kept (prefs PREF, the login's own settings), keys only:
  {"days": ["2026-10-07", ...], "seen": ["q_fee_math", "d_drop", ...]}
- the days answered and the ids of the cards answered; never what was tapped
or typed (Teach It Back keeps its own: held or not and the day per topic).
Never written while an advisor is in a client's account; never sent to the AI.

Pure logic: no Streamlit, no database. The card is views/money_minute.py.
"""

from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta

import drills
import teach_back

PREF = "money_minute"
DRILL, QUIZ, MYTH, TEACH = "drill", "quiz", "myth", "teach"
KINDS = (DRILL, QUIZ, MYTH, TEACH)
# days answered before "what would you do?" brings in hard times too
GENTLE_DAYS = 10
# the days that aren't the teach-back day take turns in this order
PATTERN = (QUIZ, DRILL, MYTH, QUIZ, MYTH)
EPOCH = date(2026, 1, 5)   # a Monday: day numbers count from here

# ---- the words people see (fixed, checked by tests) ------------------------ #
TITLE = "Today's minute"
KIND_LABELS = {DRILL: "What would you do?", QUIZ: "Quick question", MYTH: "Myth or fact?",
               TEACH: "Teach it back"}
ABOUT_A_MINUTE = "about a minute"
ONCE_A_WEEK = "once a week"
TOMORROW = {DRILL: "Tomorrow: what would you do?", QUIZ: "Tomorrow: a quick question.",
            MYTH: "Tomorrow: myth or fact?", TEACH: "Tomorrow: teach it back."}
WEEK_LINE = "This week. A missed day is fine - the count never goes down."
DONE_TODAY = "Done for today. A new one is here tomorrow."
YOUD_START = "You'd start with:"
DRILL_ASK = "What would you think about first?"
QUIZ_YES = "That's it."
QUIZ_NOT_QUITE = "Not quite."
ANSWER_IS = "The answer: {answer}"
MYTH_WORD, FACT_WORD = "Myth", "Fact"
TEACH_LEAD = "In a sentence or two, what's the main idea of this topic?"
TEACH_READ = "Read the topic first"
TEACH_SWAP = "Show a quick question instead"
SOURCE_LINE = "Learn more at {who}: [{label}]({url})"
LINK_LINES = {
    "fees": ("Your own funds' yearly fees are on the Fee check.", "Open the Fee check"),
    "mix": ("Your own mix and its target are on Plan.", "Open your target mix"),
}


def days_text(n: int) -> str:
    """'12 days of learning' - a count that only grows."""
    return f"{n} day{'' if n == 1 else 's'} of learning"


# ---- official sources ------------------------------------------------------- #
# learn.LEARN_MORE's topics, plus these. key -> (what the page is about, its
# address, who runs it). Only OFFICIAL_SITES are linked (a test checks).
EXTRA_SOURCES = {
    "fdic": ("how deposit insurance works", "https://www.fdic.gov/resources/deposit-insurance",
             "the FDIC"),
    "sipc": ("what SIPC protects", "https://www.sipc.org/for-investors/what-sipc-protects",
             "SIPC"),
    "ira": ("individual retirement accounts",
            "https://www.irs.gov/retirement-plans/individual-retirement-arrangements-iras",
            "the IRS"),
}
OFFICIAL_SITES = ("www.investor.gov", "www.finra.org", "www.consumerfinance.gov",
                  "www.fdic.gov", "www.sipc.org", "www.irs.gov")


def source(key: str | None) -> tuple[str, str, str] | None:
    """(label, url, who) for a source key, or None."""
    if not key:
        return None
    if key in EXTRA_SOURCES:
        return EXTRA_SOURCES[key]
    import learn

    return learn.LEARN_MORE.get(key)


# ---- the library ------------------------------------------------------------ #
# Quick questions: id, question, choices ((key, words), 2-3), the answer's
# key, the explanation, a source key (or None), a link to their own page
# ("fees", "mix" or None).
QUIZZES = (
    ("q_fee_math", "A fund charges 0.5% a year. On $10,000 invested, about how much is "
     "that in a year?",
     (("a", "$5"), ("b", "$50"), ("c", "$500")), "b",
     "0.5% of $10,000 is $50 a year. It comes out of the fund's value, so it never arrives "
     "as a bill.", "expense_ratios", "fees"),
    ("q_fee_gap", "Two funds hold the same things. One charges 0.05% a year, the other 1%. "
     "Over a few decades, how big can the gap in what you keep get?",
     (("a", "A few dollars at most"), ("b", "It can add up to a lot"),
      ("c", "There's no gap")), "b",
     "The fee is taken every year from money that would otherwise keep growing, so a small "
     "difference in the percentage adds up over many years.", "expense_ratios", "fees"),
    ("q_fee_compare", "Fund A charges 0.03% a year and fund B charges 0.75%. On $20,000, "
     "about how much more does fund B cost each year?",
     (("a", "$14"), ("b", "$144"), ("c", "$1,440")), "b",
     "The difference is 0.72 percentage points, and 0.72% of $20,000 is $144 a year.",
     "expense_ratios", "fees"),
    ("q_fee_where", "How is a fund's yearly fee (its expense ratio) paid?",
     (("a", "It's taken out of the fund's value"), ("b", "A bill arrives each month"),
      ("c", "It comes from your bank account")), "a",
     "The fee is taken out of the fund's value along the way, which is why it's easy to "
     "miss. A fund's documents list it.", "expense_ratios", "fees"),
    ("q_index_fund", "What does an index fund do?",
     (("a", "Tries to pick the winners"),
      ("b", "Holds a set list of holdings that stands for a market"),
      ("c", "Keeps the money in cash")), "b",
     "An index fund follows an index - a set list, like the S&P 500 - instead of trying to "
     "beat it. That keeps its costs low.", "index_funds", None),
    ("q_etf", "What's the main difference between an ETF and a mutual fund?",
     (("a", "An ETF trades during the day; a mutual fund trades once a day"),
      ("b", "ETFs can only hold bonds"), ("c", "Mutual funds can't hold stocks")), "a",
     "Both are funds holding many investments. An ETF trades on an exchange like a stock; a "
     "mutual fund trades with the fund company once a day, at its end-of-day price.", "etfs", None),
    ("q_bond", "What is a bond?",
     (("a", "A small piece of a company"),
      ("b", "A loan to a government or company that pays interest"),
      ("c", "A kind of bank account")), "b",
     "A bond is a loan: the borrower pays interest and returns the amount at the end. Its "
     "price can still move along the way.", "bonds", None),
    ("q_stock", "Owning one share of a company's stock means...",
     (("a", "You own a small piece of the company"), ("b", "You've lent it money"),
      ("c", "It owes you a fixed payment")), "a",
     "A share is a small piece of ownership. Its price moves with how the company does and "
     "what people think it's worth.", None, None),
    ("q_compound", "$1,000 grows 5% in a year, then 5% again the next year. After two years, "
     "about how much is it?",
     (("a", "$1,050"), ("b", "$1,100"), ("c", "$1,102.50")), "c",
     "The second year's 5% is on $1,050, not $1,000 - growth on earlier growth, called "
     "compounding. This is only arithmetic: real returns go up and down.",
     "compound_interest", None),
    ("q_diversify", "Why do people often hold many companies instead of one?",
     (("a", "So one company's trouble can't sink the whole thing"),
      ("b", "Because it costs more"), ("c", "Because one company is against the rules")), "a",
     "Spreading money across many holdings - diversification - means a big drop in any one "
     "of them matters less to the whole.", "diversification", None),
    ("q_inflation", "Prices rise 3% in a year and your savings earn 1%. What happens to what "
     "your savings can pay for?",
     (("a", "It goes down a little"), ("b", "It goes up"), ("c", "It stays the same")), "a",
     "The balance grew 1%, but things cost 3% more, so the same money pays for a little "
     "less. The return after inflation is called the real return.", None, None),
    ("q_drift", "Your target is 60% stocks and 40% bonds. After a strong year for stocks "
     "it's 70% and 30%. What is that gap called?",
     (("a", "Drift"), ("b", "Yield"), ("c", "Vesting")), "a",
     "Drift is how far a mix has moved from its target as prices change. Moving it back "
     "toward the target is called rebalancing.", "rebalancing", "mix"),
    ("q_bear", "What's a bear market?",
     (("a", "A fall of 20% or more from a high"), ("b", "A rise of 20% or more"),
      ("c", "A market for large companies only")), "a",
     "A bear market is a fall of 20% or more from a high; a fall of 10% or more is called a "
     "correction. Both have happened many times before.", "risk", None),
    ("q_dividend", "What's a dividend?",
     (("a", "A share of a company's profits paid to its shareholders"),
      ("b", "A fee for holding a fund"), ("c", "A kind of bond")), "a",
     "Some companies pay part of their profits to shareholders, often every quarter. Funds "
     "pass on the dividends of what they hold.", "dividends", None),
    ("q_match", "Your employer adds 50 cents for each dollar you put into the workplace plan, "
     "up to a limit. What's that called?",
     (("a", "An employer match"), ("b", "A dividend"), ("c", "A rollover")), "a",
     "An employer match is money your employer adds when you put money in. The plan's "
     "documents say how much, and when it becomes fully yours (vesting).",
     "account_types", None),
    ("q_roth", "With a Roth IRA, the money that goes in...",
     (("a", "has already been taxed, and qualified withdrawals later are tax-free"),
      ("b", "is never taxed at any point"), ("c", "can only be kept in cash")), "a",
     "Roth money goes in after tax, and qualified withdrawals come out tax-free. A "
     "traditional IRA works the other way round. The IRS sets yearly limits for both.",
     "ira", None),
    ("q_fdic", "What does FDIC insurance cover?",
     (("a", "Deposits at an insured bank, up to a limit"), ("b", "Stock market drops"),
      ("c", "Any investment at a brokerage")), "a",
     "FDIC insurance covers deposits at insured banks, up to a limit. It doesn't cover "
     "stocks, bonds or funds, even ones offered through a bank.", "fdic", None),
    ("q_sipc", "If a brokerage firm itself fails, what does SIPC protection do?",
     (("a", "Helps return customers' investments and cash, up to limits"),
      ("b", "Makes up for any drop in value"), ("c", "Nothing at all")), "a",
     "SIPC helps return customers' securities and cash when a member brokerage fails, up to "
     "limits. It doesn't cover investments losing value.", "sipc", None),
    ("q_horizon", "What's a time horizon?",
     (("a", "How long until the money is needed"), ("b", "How long a fund has existed"),
      ("c", "The hours the market is open")), "a",
     "Your time horizon is how long until you need the money. It's one of the main things "
     "people weigh when choosing how much ups and downs they can live with.",
     "risk_tolerance", None),
    ("q_emergency", "Where is an emergency fund usually kept?",
     (("a", "Somewhere steady and easy to reach, like savings"),
      ("b", "In a single company's stock"), ("c", "Locked away for ten years")), "a",
     "An emergency fund is for surprises, so it's usually kept where it's steady and quick "
     "to reach - often several months of expenses.", "emergency_fund", None),
    ("q_dca", "Putting the same amount in every month, whatever prices do, is called...",
     (("a", "Dollar-cost averaging"), ("b", "Market timing"), ("c", "Rebalancing")), "a",
     "Dollar-cost averaging means investing a set amount on a schedule. When prices are "
     "lower, the same amount gets more shares.", None, None),
    ("q_cost_basis", "What's an investment's cost basis?",
     (("a", "What was paid for it"), ("b", "Today's price"), ("c", "The fund's yearly fee")),
     "a",
     "Cost basis is what was paid. It's used to work out a gain or loss for taxes.",
     None, None),
    ("q_target_date", "What does a target-date fund do?",
     (("a", "Holds stocks and bonds, slowly shifting toward bonds as its year gets closer"),
      ("b", "Keeps everything in cash until a date"),
      ("c", "Pays a fixed amount on its date")), "a",
     "A target-date fund is one fund with a mix that gets steadier over time. Funds with the "
     "same year can still differ in their mix and their fees.", None, None),
    ("q_overlap", "Two of your funds both hold many of the same big companies. What's that "
     "called?",
     (("a", "Overlap"), ("b", "Diversification"), ("c", "Vesting")), "a",
     "Overlap means the money is less spread out than the number of funds suggests.",
     "diversification", None),
)

# Myth or fact: id, the statement, True when it's a myth, the explanation,
# a source key (or None), a link to their own page (or None).
MYTHS = (
    ("m_lot_of_money", "You need a lot of money to start investing.", True,
     "Many brokerages have no account minimum, and many offer fractional shares - part of a "
     "share - so small amounts can be invested.", "brokerage_accounts", None),
    ("m_fee_small", "A 1% yearly fee is too small to matter.", True,
     "Over many years it adds up, because it's taken every year from money that would "
     "otherwise keep growing.", "expense_ratios", "fees"),
    ("m_fee_bill", "A fund's yearly fee arrives as a bill.", True,
     "It's taken out of the fund's value, so it never shows up as a bill - which makes it "
     "easy to miss.", "expense_ratios", "fees"),
    ("m_index_beat", "An index fund tries to beat the market.", True,
     "An index fund aims to match its index, not beat it. Funds whose managers try to beat "
     "an index are called actively managed.", "index_funds", None),
    ("m_past", "A fund's past returns show what it does next.", True,
     "Past results don't tell anyone what comes next - fund documents say so too.",
     "risk", None),
    ("m_bonds_flat", "Bond prices never go down.", True,
     "Bond prices move too: they usually fall when interest rates rise. They have tended to "
     "move less than stocks.", "bonds", None),
    ("m_one_fund", "One fund can hold thousands of companies.", False,
     "A broad index fund can hold thousands of companies in a single purchase - that's "
     "diversification in one step.", "diversification", None),
    ("m_drops", "Market drops are a normal part of investing.", False,
     "Markets have fallen from time to time, sometimes sharply. Nobody knows in advance "
     "when, or how long one lasts.", "risk", None),
    ("m_cash", "Keeping everything in cash has no downside.", True,
     "Cash is steady, but rising prices shrink what it pays for over time.", "risk", None),
    ("m_more_funds", "Owning more funds always spreads your money out more.", True,
     "Funds can overlap - hold many of the same companies - so two funds can be less spread "
     "out than they look.", "diversification", None),
    ("m_ira_limits", "IRAs have yearly limits on how much can go in.", False,
     "The IRS sets the limits, and they can change from year to year.", "ira", None),
    ("m_match", "An employer match is money added on top of what you put in.", False,
     "It's money your employer adds to the workplace plan when you put money in. Some of it "
     "may take time to become fully yours, called vesting.", "account_types", None),
    ("m_etf_day", "ETFs trade during the day, like stocks.", False,
     "An ETF is a fund that trades on an exchange at prices that change through the day. A "
     "mutual fund trades once a day at its end-of-day price.", "etfs", None),
    ("m_early", "Starting earlier gives money more time to grow.", False,
     "Growth builds on earlier growth (compounding), so time matters - though returns go up "
     "and down along the way.", "compound_interest", None),
    ("m_broker_fails", "If your brokerage firm fails, the investments in your account "
     "vanish.", True,
     "Customer investments are kept separate from the firm's own money, and SIPC helps "
     "return customers' securities and cash up to limits. It doesn't cover investments "
     "losing value.", "sipc", None),
    ("m_fdic_limit", "Bank deposits are insured by the FDIC up to a limit.", False,
     "The standard limit is $250,000 per depositor, per insured bank, for each account "
     "ownership category.", "fdic", None),
    ("m_dividend_extra", "A dividend is extra money on top of the share price.", True,
     "When a dividend is paid, the share price usually drops by about that amount. It's part "
     "of the total return, not something extra.", "dividends", None),
    ("m_sp500", "The S&P 500 is a list of about 500 large US companies.", False,
     "It's an index - a set list that stands for a big part of the US stock market. Index "
     "funds that follow it hold those companies.", "index_funds", None),
    ("m_inflation", "Inflation means the same money pays for less over time.", False,
     "When prices rise, each dollar covers a little less. That's why returns are sometimes "
     "shown after inflation, as a real return.", None, None),
    ("m_drift_fixed", "Once you set a mix, it stays at those percentages by itself.", True,
     "As prices move, the parts of a mix grow at different speeds, so the percentages drift "
     "away from the target over time.", "rebalancing", "mix"),
)

QUIZ_BY_ID = {q[0]: q for q in QUIZZES}
MYTH_BY_ID = {m[0]: m for m in MYTHS}
DRILL_IDS = tuple(f"d_{k}" for k in drills.KEYS)
TEACH_IDS = tuple(f"t_{k}" for k in teach_back.CONCEPTS)
ALL_IDS = frozenset(QUIZ_BY_ID) | frozenset(MYTH_BY_ID) | frozenset(DRILL_IDS) | frozenset(
    TEACH_IDS)
LIBRARY = {QUIZ: tuple(QUIZ_BY_ID), MYTH: tuple(MYTH_BY_ID), DRILL: DRILL_IDS}


def kind_of(item: str) -> str | None:
    return {"q": QUIZ, "m": MYTH, "d": DRILL, "t": TEACH}.get(item[:1]) if item in ALL_IDS \
        else None


def drill_key(item: str) -> str:
    return item[2:]


def teach_key(item: str) -> str:
    return item[2:]


# ---- the daily pick ---------------------------------------------------------- #
def _seed(salt: str, login) -> int:
    return int(hashlib.sha256(f"{salt}:{login}".encode()).hexdigest()[:12], 16)


def teach_weekday(login) -> int:
    """The person's teach-back day of the week (0 = Monday), from the login."""
    return _seed("teach", login) % 7


def order(kind: str, login) -> tuple[str, ...]:
    """This person's own order of one kind's cards (the same every day)."""
    ids = list(LIBRARY[kind])
    random.Random(_seed(kind, login)).shuffle(ids)
    return tuple(ids)


def _slot(login, d: date) -> int:
    return (d - EPOCH).days + _seed("slot", login) % len(PATTERN)


def kind_for(login, d: date, teach: bool = True) -> str:
    """The day's kind: the teach-back day once a week (when `teach`), else the
    PATTERN's turn."""
    if teach and d.weekday() == teach_weekday(login):
        return TEACH
    return PATTERN[_slot(login, d) % len(PATTERN)]


def teach_topic(p: dict | None, d: date) -> str:
    """The Learn topic for a teach-back day: one explained back today stays;
    else the first that hasn't held yet; else they take turns by week."""
    s = teach_back.state(p)
    keys = tuple(teach_back.CONCEPTS)
    today = next((k for k in keys if s.get(k, {}).get("on") == d.isoformat()), None)
    if today:
        return today
    todo = [k for k in keys if not s.get(k, {}).get("held")]
    if todo:
        return todo[0]
    return keys[((d - EPOCH).days // 7) % len(keys)]


def pick(login, d: date, p: dict | None = None, teach: bool = True) -> str:
    """The day's card id, from the date and the login (and, on a teach-back
    day, which topics have held). Each kind's cards come in the person's own
    order, and none repeats until that kind's whole list has been shown."""
    kind = kind_for(login, d, teach)
    if kind == TEACH:
        return f"t_{teach_topic(p, d)}"
    slot = _slot(login, d)
    full, within = divmod(slot, len(PATTERN))
    n = full * PATTERN.count(kind) + PATTERN[:within].count(kind)
    ids = order(kind, login)
    before = sum(1 for day in state(p)["days"] if day < d.isoformat())
    if kind == DRILL and before < GENTLE_DAYS:
        # a new person's first days: good-times situations only (a raise, a
        # bonus) - never a market drop or a lost job as a first impression
        # (days before today, so answering doesn't change today's card)
        ids = tuple(i for i in ids if drills.side_of(drill_key(i)) == drills.GOOD)
    return ids[n % len(ids)]


def tomorrow_line(login, d: date, teach: bool = True) -> str:
    return TOMORROW[kind_for(login, d + timedelta(days=1), teach)]


# ---- what's kept ----------------------------------------------------------- #
def _day(v) -> str | None:
    try:
        return date.fromisoformat(v).isoformat() if isinstance(v, str) and len(v) == 10 \
            else None
    except ValueError:
        return None


def clean(raw) -> dict:
    """The kept state with anything unknown dropped: ISO days and known card
    ids only - never anything typed or tapped."""
    raw = raw if isinstance(raw, dict) else {}
    days = raw.get("days") if isinstance(raw.get("days"), list) else []
    seen = raw.get("seen") if isinstance(raw.get("seen"), list) else []
    return {"days": sorted({d for d in map(_day, days) if d}),
            "seen": sorted({i for i in seen if isinstance(i, str) and i in ALL_IDS})}


def state(p: dict | None) -> dict:
    return clean((p or {}).get(PREF))


def record(p: dict, item: str, d: date) -> bool:
    """Keep that the day's card was answered: the day and the card's id.
    Changes `p`; True when something new was kept."""
    if item not in ALL_IDS:
        return False
    s = state(p)
    day = d.isoformat()
    if day in s["days"] and item in s["seen"]:
        return False
    s["days"] = sorted(set(s["days"]) | {day})
    s["seen"] = sorted(set(s["seen"]) | {item})
    p[PREF] = s
    return True


def answered(p: dict | None, d: date) -> bool:
    return d.isoformat() in state(p)["days"]


def count(p: dict | None) -> int:
    """Days of learning: every day a minute was answered. Missed days don't
    take anything away."""
    return len(state(p)["days"])


def week_marks(p: dict | None, d: date) -> list[tuple[date, str]]:
    """Monday to Sunday of `d`'s week: (day, "done" / "today" / "open" /
    "later"). "open" is a past day without one - shown quietly, never as a
    loss."""
    days = set(state(p)["days"])
    monday = d - timedelta(days=d.weekday())
    out = []
    for i in range(7):
        day = monday + timedelta(days=i)
        if day.isoformat() in days:
            mark = "done"
        elif day == d:
            mark = "today"
        elif day > d:
            mark = "later"
        else:
            mark = "open"
        out.append((day, mark))
    return out


# ---- the cards' words ------------------------------------------------------- #
def quiz_answer_words(item: str) -> str:
    q = QUIZ_BY_ID[item]
    return dict(q[2])[q[3]]


def templates() -> list[str]:
    """Every fixed line the card shows (for the wording tests); the drill
    situations and Teach It Back's words are tested where they live."""
    out = [TITLE, ABOUT_A_MINUTE, ONCE_A_WEEK, WEEK_LINE, DONE_TODAY, YOUD_START, DRILL_ASK,
           QUIZ_YES, QUIZ_NOT_QUITE, MYTH_WORD, FACT_WORD, TEACH_LEAD, TEACH_READ, TEACH_SWAP,
           days_text(1), days_text(12)]
    out += list(KIND_LABELS.values()) + list(TOMORROW.values())
    for line, button in LINK_LINES.values():
        out += [line, button]
    for _id, question, choices, _ans, why, _src, _link in QUIZZES:
        out += [question, why, ANSWER_IS.format(answer=quiz_answer_words(_id))]
        out += [w for _, w in choices]
    for _id, statement, _myth, why, _src, _link in MYTHS:
        out += [statement, why]
    for key in list(EXTRA_SOURCES):
        label, _url, who = EXTRA_SOURCES[key]
        out.append(f"{label} {who}")
    return out
