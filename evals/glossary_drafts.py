"""Offline eval cases for two AI helpers (docs/AI_PLAN.md section 9, rows 5
and 11): the glossary's fallback (glossary_ai.py) and advisor drafts
(advisor_drafts.py). Made-up data only; never sent to a real model.

Each case pairs what goes in with canned model answers: GOOD ones the helper
must show as they are, BAD ones it must never show. tests/test_ai_drafts.py
plays them through the helper with a fake model (a bad answer twice gives
None, a bad then a good gives the good one) and checks:

- glossary: prescriptive phrasing (ai_policy's conclusion, for-you-mix,
  rating, prediction and urgency kinds) never reaches the screen;
- advisor drafts: a draft that says or implies Northwend advises, recommends
  or approves anything never reaches the box.
"""

from __future__ import annotations

# (term, good answers, bad answers)
GLOSSARY = (
    ("Sharpe ratio",
     ("The Sharpe ratio compares a fund's return with how much it moved around, so people can "
      "see return per unit of ups and downs. A higher figure means more return for the same "
      "bumpiness in the past; it says nothing about the future.",),
     ("You should pick the fund with the higher Sharpe ratio.",
      "Consider switching to a fund with a better Sharpe ratio.",
      "A fund with a Sharpe ratio above 1 would suit you.")),
    ("REIT",
     ("A REIT (real estate investment trust) is a company that owns or finances property and "
      "pays out most of its income to shareholders. Funds that hold many REITs are one way "
      "people own real estate without buying a building.",),
     ("You might want to add a REIT fund to your portfolio.",
      "REITs will go up when rates fall, so now is a good time to buy.",
      "Your portfolio looks solid, but a REIT would round it out.")),
    ("Contango",
     ("Contango is when futures contracts for later dates cost more than the price today. "
      "People come across it with commodity funds that roll futures, where it can cost the "
      "fund a little each time it rolls.",),
     ("Don't miss out - avoid funds in contango asap!",
      "If I were you, I'd sell any commodity fund in contango.",
      "It's time to move out of oil funds while they're in contango.")),
    ("Sequence risk",
     ("Sequence risk is the chance that poor returns arrive early in retirement, while money "
      "is being taken out. Two people with the same average return can end up with different "
      "amounts depending on the order the returns came in.",),
     ("Most people in your position would move to bonds to avoid sequence risk.",
      "You need to build a cash buffer before you retire.",
      "Stocks will recover, so sequence risk is nothing to worry about.")),
)

# (kind, inputs, good drafts, bad drafts)
DRAFTS = (
    ("proposal",
     {"title": "A steadier mix", "mix": {"Stocks": 60, "Bonds": 35, "Cash": 5},
      "points": "closer to the house purchase in 2029"},
     ("I'm proposing we move to 60% stocks, 35% bonds and 5% cash, from the mix you have "
      "today. With the house purchase coming in 2029, I'd like more of the money in steadier "
      "holdings. Let's talk it through before anything changes.",),
     ("Northwend recommends moving to 60% stocks and 35% bonds.",
      "Based on Northwend's analysis, a steadier mix fits you better.",
      "This proposal has Northwend's approval and mine.",
      "The app suggests we shift to more bonds before 2029.")),
    ("message",
     {"points": "markets bumpy this week, the plan allows for it, happy to talk"},
     ("Markets have been bumpy this week. Your plan was built with weeks like this in mind, "
      "so nothing needs to change because of it. I'm happy to talk any time.",),
     ("Northwend advises staying calm and holding on.",
      "Advice from Northwend: markets always come back.",
      "We at Northwend think this is a buying opportunity.",
      "Markets will recover by spring, so there's nothing to worry about.")),
    ("report",
     {"facts": "Period: Q3 2026.\nMarket movement over the period: +2.1% of the starting "
               "value (deposits left out).\nGoal: 48% of the target, status on track.",
      "points": "talk about the new job's 401(k)"},
     ("Your portfolio moved up about 2.1% over the quarter, not counting what you added, and "
      "the goal stands at 48% of its target. Next time I'd like to talk about the 401(k) at "
      "your new job.",),
     ("Northwend's view is that you're doing well this quarter.",
      "Northwend thinks the 401(k) at your new job is the next step.",
      "Your goal is guaranteed to stay on track.",
      "Act now on the new 401(k) - don't miss out!!")),
)
