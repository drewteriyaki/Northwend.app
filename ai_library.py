"""Northwend's own content library for Ask Northwend (docs/AI_PLAN.md 5.1-5.2,
step 10): the general education the guide reads before it answers, as one
block of text.

block_text() joins the shared, cached first system block (ai_gateway.
library_text(), build_request): the same text for every person - nothing in
it comes from anyone's account or answers - so one cache entry serves every
conversation. Built from what the app already says, so the guide and the
pages can't drift apart:

- learn.py: the three building blocks and their kinds of funds, the common
  order of things before investing (readiness), common starting points (one
  table, the same for everyone) and the "learn more" pages on Investor.gov,
  FINRA and the CFPB;
- starter_funds.py: "What these kinds of funds look like" - the only named
  funds here, examples of each kind from several providers (the same set
  ai_policy.GENERAL_EXAMPLES allows in an answer);
- stress.SCENARIOS and storms.PAST_STORMS: past drops, as history;
- disclosures.py and docs/PRINCIPLES.md: what Northwend is and isn't;
- route.py: the route's two stages and their waypoints;
- a short "how Northwend works" and the glossary (glossary.TERMS, the same
  text the app shows behind "What does this mean?"; a DRAFT for the owner to
  review - general definitions, no figures for anyone).

Size: the whole library stays under BUDGET_CHARS (about 8,000 tokens - past
that, AI_PLAN 5.2 says keep only an index here and add a read-only lookup
tool). A test checks the size and that no ticker outside the general
examples appears. Pure: no Streamlit, no database, no network.
"""

from __future__ import annotations

from functools import lru_cache

import disclosures
import glossary
import learn
import route
import starter_funds
import storms
import stress

BUDGET_CHARS = 32_000   # about 8,000 tokens at ~4 characters a token

# The route's waypoints by key (views/get_started.py GET_STARTED_STEPS, with
# gate L3 off: the mix waypoint is the common starting points table)
WAYPOINTS = {
    "profile": "About you", "ready": "Are you ready to invest?", "goal": "Set a goal",
    "basics": "Learn the basics", "mix": learn.COMMON_POINTS_TITLE,
    "practice": "Try it with practice money", "brokerage": "Choose a brokerage",
    "account": "Open your account", "first": "Your first investments", "bring": "Bring it in",
}

# (feature, what it does) - the app's features the guide can point to instead
# of improvising. Descriptive: each one shows facts or the person's own rule.
FEATURES = (
    ("Home", "the person's route and its one next step, their mix, and \"Your money, "
             "checked\": Fee check, Fund overlap and Cash check, one line each."),
    ("Plan", "their goal (amount and date), a monthly amount, their own target mix and band, "
             "and hypothetical projections at a stated yearly rate. Tabs include Stress test "
             "and Contributions."),
    ("Target mix and band", "the mix the person chose for themselves by asset class, and how "
                            "many points either way they're comfortable drifting before they "
                            "look at it. Northwend never sets either for them."),
    ("Drift", "how far each asset class is from the person's own target, in points. Home "
              "notes it when a class is outside their band."),
    ("Where could your next deposit go?", "under the Plan's target mix: an amount split by "
                                          "asset class so the mix moves closest to the "
                                          "person's own target without selling anything. "
                                          "Which funds fill each part is their choice."),
    ("Fee check", "each fund's yearly fee (its expense ratio) in dollars, the total, and what "
                  "it adds up to over 10 and 30 years at an assumed growth rate, with what "
                  "low-cost funds of the same kind often charge, for learning."),
    ("Fund overlap", "whether the person's funds hold the same companies, from each fund's "
                     "largest holdings. It describes overlap only."),
    ("Cash check", "how much sits in cash, and the difference between a brokerage's default "
                   "cash (a sweep account) and a money market fund. No rate is promised."),
    ("Stress test", "how a mix of asset classes would have done in 2008, 2020 and 2022: the "
                    "drop and roughly how long it took to get back. Hypothetical."),
    ("Free money check", "an employer match calculator: the match someone gets at what they "
                         "put in now, and where the full match starts."),
    ("Watchlist", "follow prices of funds and stocks without holding them. Nothing is bought."),
    ("Income", "dividends and interest the holdings paid and are expected to pay."),
    ("Activity", "buys, sells and money moved in, from imported history or worked out from "
                 "snapshots."),
    ("Year in review", "a look back over the year from Home; the shareable version has no "
                       "dollar figures."),
    ("Account", "the person's name, email, password, their data (export or delete), and "
                "what Ask Northwend remembers - notes they can read and delete."),
)
WALK = ("The Monthly Walk", "a few minutes on Home once a month: update holdings, look at the "
                            "mix against its target, one short read, then what the person's "
                            "own rule (target mix and band) says this month, by asset class.")

# The glossary: glossary.py (one text for the app and the guide; a DRAFT for
# the owner to review). General definitions only - never a figure for anyone,
# never a named fund.
GLOSSARY = glossary.TERMS


def _pct(v: float) -> str:
    return f"{abs(v):.0f}%"


def _intro() -> str:
    return ("## Northwend's guide\n"
            "Northwend's own general education - the same for everyone; nothing in it is "
            "about the person you're talking with. Prefer it when it covers the question and "
            "say so (\"Northwend's guide on fees says...\"); say plainly when something isn't "
            "covered here. The only named funds in it are examples of a kind of fund, the same "
            "for everyone - never offer them, or any fund, as an idea for this person.")


def _what_northwend_is() -> str:
    return ("### What Northwend is\n"
            + disclosures.SUMMARY + " It is free for individuals and never gives individual "
            "recommendations. Advisors pay a flat seat fee and are listed equally; any advice "
            "comes from a registered firm the person chose, never from Northwend. Holdings "
            "come in from a file, a paste, screenshots or by hand - never a brokerage login. "
            "Uploads are read and deleted, account numbers are kept to their last three "
            "digits, and emails never carry figures. Brokerages are listed alphabetically, "
            "never ranked. Ask Northwend sees holdings as whole percentages only - never "
            "amounts, share counts or account names.")


def _route() -> str:
    def names(keys):
        return ", ".join(WAYPOINTS[k] for k in keys)
    return ("### Northwend's route\n"
            f"Two stages. {route.STAGE_NAMES[route.LEARN]} (required only for someone brand "
            f"new): {names(route.STAGE_KEYS[route.LEARN])}. "
            f"{route.STAGE_NAMES[route.INVEST]}: {names(route.STAGE_KEYS[route.INVEST])}. "
            "Someone with experience, or already investing, starts at Start investing; Learn "
            "stays open to them. Someone who works with an advisor walks with their advisor: "
            f"Learn is the reads only ({names(route.MANAGED_LEARN_KEYS)}) and Start investing "
            "is bringing their holdings in - choosing what to buy is with their advisor.")


def _building_blocks() -> str:
    lines = ["### The building blocks of a simple portfolio",
             starter_funds.INTRO]
    by_key = {p["key"]: p for p in starter_funds.PARTS}
    for b in learn.BLOCKS:
        funds = by_key[b["key"]]["funds"]
        examples = "; ".join(f"{t} ({starter_funds.FUNDS[t][1]})" for t in funds)
        lines.append(f"- {b['label']}: {b['kind']}. {b['about']} Examples of this kind: "
                     f"{examples}.")
    lines += [starter_funds.FOOTER, starter_funds.MIX_NOTE,
              "Other kinds people meet: target-date funds and balanced funds (one fund "
              "holding stocks and bonds), single stocks, sector funds, and actively managed "
              "funds."]
    return "\n".join(lines)


def _before_investing() -> str:
    # learn.readiness's general lines (each one's "a few things to look at"
    # wording - never a verdict for anyone)
    sample = {"emergency_fund": "Under 3 months", "high_interest_debt": "Some",
              "employer_match": "Yes, but I'm not getting all of it",
              "withdrawal_needs": "A large amount", "income_stability": "Varies a lot"}
    lines = ["### What people often take care of before investing",
             "A common order of operations, in general (the \"Are you ready to invest?\" "
             "waypoint):"]
    lines += [f"- {i['label']}: {i['text']}" for i in learn.readiness(sample)]
    return "\n".join(lines)


def _starting_points() -> str:
    cols = learn.COMFORT_BUCKETS
    lines = [f"### {learn.COMMON_POINTS_TITLE}",
             learn.COMMON_POINTS_NOTE,
             "Share in stocks, by how long until the money is needed ("
             + "; ".join(f"{label.lower()}" for _k, label in cols) + "):"]
    for row in learn.common_starting_points():
        lines.append(f"- {row['timeline']}: "
                     + ", ".join(f"{row['stocks'][k]}%" for k, _l in cols))
    lines += ["Why, in general:"] + [f"- {w}" for w in learn.COMMON_POINTS_WHY]
    lines.append("These are about people in general. Never apply a row to this person as a "
                 "conclusion; their own target is theirs to choose.")
    return "\n".join(lines)


def _past_drops() -> str:
    lines = ["### Past drops, as history",
             "The S&P 500's biggest falls (price, high to low, rounded) and how long until "
             "the old high was passed again:"]
    lines += [f"- {name}: down about {drop}%, back in {back}"
              for name, drop, back in storms.PAST_STORMS]
    lines.append("Three hard stretches Northwend's Stress test uses, for a mix of asset "
                 "classes:")
    lines += [f"- {s['name']} ({s['when']}): {s['about']} Broad stocks fell about "
              f"{_pct(s['drop']['Stocks'])}; the US bond index "
              + ("rose" if s["drop"]["Bonds"] >= 0 else "fell")
              + f" about {_pct(s['drop']['Bonds'])}." for s in stress.SCENARIOS]
    lines.append(stress.ASSUMPTIONS)
    lines.append("Past drops say nothing certain about the next one - describe them as "
                 "history, never as a forecast.")
    return "\n".join(lines)


def _how_northwend_works() -> str:
    import flags
    feats = FEATURES + ((WALK,) if flags.on("walk") else ())
    return "\n".join(["### How Northwend works (point to these instead of improvising)"]
                     + [f"- {name}: {what}" for name, what in feats])


def _learn_more() -> str:
    lines = ["### Learn more from trusted sources",
             "Public education pages people can read (link them; don't quote them as "
             "Northwend's words):"]
    lines += [f"- {label}: {source}, {url}" for label, url, source in learn.LEARN_MORE.values()]
    return "\n".join(lines)


def _glossary() -> str:
    return "\n".join(["### Glossary"] + [f"- {term}: {meaning}" for term, meaning in GLOSSARY])


@lru_cache(maxsize=4)
def _cached(walk_on: bool) -> str:
    return "\n\n".join([_intro(), _what_northwend_is(), _route(), _building_blocks(),
                        _before_investing(), _starting_points(), _past_drops(),
                        _how_northwend_works(), _learn_more(), _glossary()])


def block_text() -> str:
    """The whole library, for the shared first system block - the same text
    for everyone on this copy (byte-identical call to call, so the cache
    holds)."""
    import flags
    return _cached(flags.on("walk"))
