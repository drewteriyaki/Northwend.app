# Copy audit

Per the owner's master brief, section 9.2. Written against staging commit
`899f35a` (Oct 5, 2026). **No copy was changed.** The yardstick is
`docs/PRINCIPLES.md`. Feature-level findings are in `docs/LEGAL_GATES.md`.

## What was searched

- **Words** (any case, anywhere in a word): "for you", "recommend", "should",
  "best", "match", "premium", "upgrade". "for you" also catches "for your".
- **Python:** string literals only (comments and docstrings skipped) in
  `views/*.py`, `dashboard.py`, `learn.py`, `route.py`, `gear.py`,
  `storms.py`, `checkin.py`, `next_deposit.py`, `alerts.py`, `mailer.py`,
  `disclosures.py`, `advisor.py`, and the other modules with text people see:
  `starter_funds.py`, `brokerages.py`, `client_plan.py`, `meeting.py`,
  `checkin_email.py`, `weekly_email.py`, `fees.py`, `employer_match.py`,
  `cash_check.py`, `plans.py`, `recap.py`, `account_map.py`, `reports.py`,
  `proposals.py`, `future_notes.py`, `stress.py`, `advisor_demo.py`,
  `auth.py`, `friendly_errors.py`, `news.py`, `fund_holdings.py`,
  `income.py`, `ai_usage.py`, `two_step.py`, `admin.py`, `export.py`,
  `csv_import.py`, `manual_entry.py`, `paste_parse.py`, `screenshot_read.py`,
  `txn_import.py`, `client_csv.py`, `advising.py`. `tests/` skipped.
- **Website:** `website/templates/*.html` and `website/build.py`
  (`website/public/` is built from them).

## Counts

| | Hits |
|---|---|
| All hits | **179** (168 in Python, 11 on the website) |
| Not copy (dictionary keys, code names, a CSS comment) | 36 |
| AI instructions (the model reads them; people don't) | 12 |
| **User-facing copy** | **131** |
| - Rewrite | **13** |
| - Consider | **6** |
| - Fine | **112** |

By word, all 179: match 60, for you 54, recommend 32, best 17, should 16,
**premium 0, upgrade 0**. No "premium", "upgrade" or payment wording exists
anywhere (brief 3.4 holds today).

The seven words miss the biggest problem. The phrases that make copy "for
you" are mostly "your answers", "for someone", "fits", "for me", "your
direction", "people in your spot" and "suggested". Those are in a last
section, **Same problem, other words** (30 more places, not in the counts
above).

**Severity:**
- **Rewrite** - prescriptive, or implies Northwend recommends something for
  this person.
- **Consider** - fine in substance; the wording leans toward a nudge or a
  judgement.
- **Fine** - not a problem ("not recommendations", "employer match", "best
  month", "passwords don't match").

---

## Rewrite (13 hits)

| # | Where | In context | Why | Suggested rewrite |
|---|---|---|---|---|
| 1 | `views/get_started.py:425` | Set a goal, target mix: "Suggested starting point for your answers: 60% stocks, 40% bonds - **the example mix for your answers**" + Use the suggestion | Copies a mix worked out from their answers into their own target in one tap. That target then drives drift and the walk verdict. | Drop the button. "A common starting point for a 10-20 year timeline is about 75% stocks - see Common starting points. Your target is yours to choose." |
| 2 | `views/plan.py:745` | Plan > Target mix: "... **- the example mix for your answers**" + Use the suggestion | Same as 1. | Same as 1. |
| 3 | `views/plan.py:193` (with `:194`) | `SUGGEST_LEAD` "Suggested starting point **for your answers**", help "Worked out from your answers as a place to start - not advice" - on the goal date, monthly amount, return, What if | Says Northwend suggests something for them. Most uses are arithmetic or typical values, which are fine under another label. | Arithmetic: "What reaches your goal: $X a month (at the plan's assumed return)". Typical values: "A typical value people use: 6% a year". Mix: remove (see 1). |
| 4 | `learn.py:195` | Foundation type: "the example mix below shows what investing could look like **for you**." | A mix "for you", word for word (principle 2). | "Common starting points below show what investing can look like for different timelines." |
| 5 | `views/get_started.py:66` | Ready-made question: "Looking at my situation, what **should** I take care of before I start investing, and in what order?" | Northwend writes a question that asks the AI for a conclusion about the person - which brief 5.3 says it must not give. | "What do people usually take care of before they start investing, and in what order?" |
| 6 | `views/start_home.py:30` | `START_ASK`: "I'm new to investing. What **should** I do before I invest, and in what order?" | Same as 5. | "I'm new to investing. What do people usually do before they invest, and in what order?" |
| 7 | `dashboard.py:2064` | Quick start button label: "What **should** I do before I invest?" (its message is already general) | The label asks for a personal answer. | "What do people do before investing?" |
| 8 | `views/get_started.py:957` (with `:956`) | "Northwend says I'm a \"{type}\". Explain what that means **for someone like me** ... what I **should** understand" | Asks for a type-specific, person-specific reading. | "Explain the \"{type}\" description in general terms, what common starting points are built from, and what people usually learn before investing." |
| 9-11 | `learn.py:86-87` (3 hits: match, best, match) | Readiness, to someone not getting the full match: "Putting in enough to get the full **match** is usually the **best** return available: the **match** is often 50% or 100%..." | Tells this person what to do with their pay. ("best return available" is also a claim about returns.) | "An employer match adds money on top of what you put in - often 50% or 100% of it, up to a limit. Many people check what they'd need to put in to get all of it. The Free money check does the sums." |
| 12 | `views/get_started.py:978` | Direction card: "A common rule of thumb for learning, **from your answers** - not a **recommend**ation to buy anything." | "From your answers" makes the rule of thumb tailored; the disclaimer can't undo that. Keep the disclaimer (never remove a disclosure); change what it sits under. | "A common starting point for this timeline, the same for everyone in it - not a recommendation to buy anything." |
| 13 | `views/start_home.py:22` (with `:21`) | Route line: "What a mix could look like **for someone with your answers** - an example, not a **recommend**ation." | Same as 12. | "Common starting points for different timelines - the same for everyone, not a plan for you." |

---

## Consider (6 hits)

| # | Where | In context | Why | Suggested rewrite |
|---|---|---|---|---|
| 1 | `views/dashboard_page.py:17` | Route "Ask" when on track: "What **should** I keep an eye on from here?" | Mild; invites a personal list. | "What do people usually keep an eye on once they're on track?" |
| 2 | `views/cash_check.py:80` | "Cash you'll need soon, or keep for emergencies, is still **best** kept safe and easy to reach" | General, but reads as a rule for them. | "...is usually kept safe and easy to reach" |
| 3 | `mailer.py:160` | Proposal email: "{advisor} has shared a proposal with you: a suggested mix **for your** investments" | It is the advisor's - fine. Brief 4.4 wants the firm and the standing line on everything an advisor sends. | "{advisor} ({firm}) has shared a proposal... The advice is {advisor}'s, not Northwend's." (Text at L2.) |
| 4 | `views/free_money.py:126` (with `:124-125`) | "You may be leaving $X a year of free money on the table. Putting in 6% of your pay (instead of 3%) would get the whole **match**." | The sum is a calculator on their own inputs (brief 3.1 keeps it). "Leaving money on the table" pushes. | "Putting in 6% of your pay (instead of 3%) would add about $X a year in match. Whether to change it is up to you - check your plan's rules." |
| 5 | `learn.py:90` | "No employer **match** to collect. An IRA is a common place to start instead." | "Instead" points this person to an account type. | "No employer match to collect. Many people without one look at an IRA - Learn explains the kinds of accounts." |
| 6 | `views/get_started.py:547` | Under the example mix: "An example for learning, based on common rules of thumb - not a **recommend**ation." | The disclaimer is right; the screen above it is the problem (Rewrite 13, and "Same problem" 2). Keep it. | Keep the words; rewrite the mix above it. |

---

## Fine (112 hits)

Grouped. Every listed line is a hit that needs no change.

| Where | In context |
|---|---|
| `views/account.py:255`, `:309` | "What should we call you?"; "Signed in somewhere you shouldn't be" |
| `views/account.py:282`, `:317` | "Waiting for you to open the link"; "everything Northwend holds for your account" |
| `views/activity.py:99`, `views/clients.py:987`, `views/dashboard_page.py:610` | "No transactions match these filters"; "No clients match"; "No ticker matches your search" |
| `views/advisor_demo.py:122`, `:129` | "Also waiting for you"; "for your firm's files" |
| `views/assistant.py:16` | "it won't recommend what to buy or sell" |
| `views/cash_check.py:23`, `views/fees.py:17`, `views/free_money.py:17`, `views/fund_overlap.py:19`, `views/income.py:20` | Ready-made questions ending "Use examples, not recommendations." |
| `views/clients.py:105`, `:481`, `:664` | "your advisor's next steps for you"; "A note for your clients"; "How they're listed for you" |
| `views/dashboard_page.py:258`, `:329` | "Your advisor hasn't set a goal for you yet"; "price history for your holdings" |
| `views/first_steps.py:305`, `:314`, `dashboard.py:90` | "We never ask for your brokerage login" |
| `views/free_money.py:16`, `:68`, `:86`, `:103`, `:118`, `:119`, `:127`, `:129`, `:138`, `:155` | The employer match calculator's own words ("How your employer matches", "Matched money can come with a waiting period", "Ask Northwend about matches") |
| `views/get_started.py:71`, `:73` (x2), `:74`, `:76` | Ready-made questions: "What should I expect emotionally when my investments drop...", "What should I compare when choosing a brokerage ... Please don't recommend a specific one", "which questions should I ask to pick one?" |
| `views/get_started.py:475`, `views/start_home.py:18`, `views/profile.py:22` | "employer match. IRAs and 401(k)s have yearly limits"; "and any employer match"; "Does your employer match what you put into a retirement plan?" |
| `views/get_started.py:723` | "An example of the steps, not a recommendation to buy any fund." |
| `views/get_started.py:907`, `:916`, `:918`, `:921` | An advisor's client: "Your advisor has a proposal waiting for you", "Answer a few questions for your advisor", "prepare for your conversations", "Your advisor can bring them in for you" |
| `views/get_started.py:1009`, `:1093` | "(optional for you)"; "Learn is optional for you" |
| `views/holdings_input.py:562`, `:1065`, `:1082`, `:1105` | "a name is shown for you to confirm"; "Match it to the account in your holdings"; "didn't match a kind we know"; "export for your real buys" |
| `views/kit.py:123` | "You've earned the {gear} for your kit" (the storm cloak itself is in "Same problem" 18) |
| `views/kit.py:256` | Storms window: "some of the market's best days have come soon after its worst" - general history, the same for everyone |
| `views/plan.py:677` | "what you paid for your holdings plus cash" |
| `views/plan.py:947` | "4% is the best-known one" |
| `views/proposals.py:150`, `views/start_home.py:169` | Ready-made questions ending "Explain, don't recommend." |
| `views/proposals.py:158`, `:305` | "Waiting for your answer"; "kept for your records" |
| `views/two_step.py:181`, `two_step.py:237` | "changed for your account"; "That code didn't match" |
| `views/year_review.py:127`, `recap.py:383` | "Best month" |
| `dashboard.py:731`, `:1559`, `:2588` | "set up a Northwend account for you"; "passwords for your clients"; "Loading price history for your holdings" |
| `dashboard.py:760`, `:869`, `:1001`, `:1639` | "The two passwords don't match." |
| `dashboard.py:2068` | "Which questions should I ask myself to pick one?" (its button label is in "Same problem" 9) |
| `learn.py:82`, `:83`, `:93`, `:96`, `advisor.py:47`, `:62`, `:63` | "Employer match"; "You're getting your employer's full match"; "many employers match part of what you put into a 401(k)"; profile labels and answers ("Yes, and I get the full match", "No match or no plan") |
| `mailer.py:124`, `:150`, `:162`, `:166`, `:202`, `:206`, `:216`, `:258`, `:273`, `:315` | Account and advisor emails: "for your privacy, the figures stay in Northwend", "Your advisor has a proposal for you", "set up for you", "can't match the firm or the CRD" |
| `disclosures.py:108`, `:263-264` | "None of it is a recommendation to buy, sell or hold any security"; "The AI is told ... never to recommend ... a specific mix for you" |
| `disclosures.py:138`, `:185`, `:259` | "responsible for your own advice"; "everything held for your account"; "columns can't be matched" |
| `starter_funds.py:31` | "to learn from - not recommendations. Many similar funds exist." |
| `client_plan.py:46` | "Written by AI for education - not a recommendation" |
| `proposals.py:176` | "This proposal is your advisor's recommendation, made by them as your advisor." (a model for the brief 4.4 standing line) |
| `checkin_email.py:33`, `:34` | "Time for your monthly walk" |
| `export.py:67` | "Everything Northwend holds for your account" |
| `manual_entry.py:71`, `:211` | "total cost should be a dollar amount"; "Cash should be a percentage" |
| `website/templates/advisors.html:25`, `:42`, `:55`, `:61`, `:63` | "talking points drafted for you to edit"; "For your clients"; "the recommendations stay yours"; "Two-step sign-in for you" |
| `website/templates/home.html:47` | Sample chat: "Your mix is 64% stocks against a 70% target. Want me to explain what that gap means for your house deposit?" - drift against their own target, then an offer to explain |
| `website/templates/new-to-investing.html:113`, `:120`, `:133` | "not recommendations: the choice is yours"; "can't buy or sell anything for you" |

## AI instructions (12 hits - not shown to people)

`advisor.py:96`, `:98`, `:99`, `:100`, `:114`, `:115`, `:120`, `:404`, `:409`;
`client_plan.py:39`; `meeting.py:22`, `:23`. These are the rules that tell
the model never to recommend. They read correctly. Their gaps against brief
5.3 (no rule against rating the person's choices, soft forms, or suggesting
an advisor) are in `docs/LEGAL_GATES.md` section 5.

## Not copy (36 hits)

Dictionary keys and code: `"employer_match"`, `match_pct`, `match_yearly`,
`has_match`, `r['best']`, the `best` variable in `views/holdings_input.py:585`
and `website/build.py:109`, `:113`, answer values compared in code
(`learn.py:85`, `:92`, `views/get_started.py:241`), rule keys in
`advisor.py`, and a CSS comment (`dashboard.py:267`).

---

## Same problem, other words (30 places, not counted above)

These carry the "for you" problem without any of the seven words. They are
the main work for gate L3.

| # | Where | In context | Severity | Suggested rewrite |
|---|---|---|---|---|
| 1 | `views/get_started.py:44-45` | Why this waypoint: "an example split **for someone with your answers**" | Rewrite | "So you can see what simple mixes look like - common starting points for different timelines." |
| 2 | `views/get_started.py:524` | "An example **for someone with your answers**: 60% stocks, 40% bonds." | Rewrite | A table of timeline buckets, the same for everyone: "For 10-20 years, a common starting point is about 75% stocks, 25% bonds." (brief 3.1) |
| 3 | `views/get_started.py:526-528`, `learn.py:153-182` | "How it adds up": their horizon, then "Conservative comfort with risk: 15 points less in stocks", "You said you'd 'sell some' after a 20% drop: 5 points less in stocks" | Rewrite | Explain in general how timeline and comfort with drops move a mix ("shorter timelines usually hold more bonds"), not their own points. |
| 4 | `views/get_started.py:779-782` | Your first investments: "**Your direction:** ... an example mix of 60% stocks, 40% bonds, **from your answers**." | Rewrite | Remove from this screen (it sits above named example funds). If they set a target: "The target mix you set: ..." is fine. |
| 5 | `views/get_started.py:971` | "**An example mix for this type:** 60% stocks, 40% bonds." | Rewrite | "A common starting point for this timeline: ..." |
| 6 | `views/get_started.py:974` | "**Kinds of funds that usually fill it:**" | Consider | "Kinds of funds simple mixes are built from:" |
| 7 | `views/get_started.py:979` | "Ask Northwend **what this means for me**" | Rewrite | "Ask Northwend about this" |
| 8 | `views/get_started.py:68-69` | Ready-made question: "Explain why a mix ... **might fit my** time horizon and comfort with risk." | Rewrite | "How do people usually think about splitting money between US stocks, international stocks and bonds for different timelines? Talk about kinds of funds, not specific ones." |
| 9 | `dashboard.py:2066` | Quick start label: "Which account type **fits me**?" | Rewrite | "What kinds of accounts are there?" |
| 10 | `dashboard.py:2055-2056` | Quick start: "**Review my portfolio**" - "how my current portfolio compares with my goals" | Consider | "Explain my mix": "Describe my mix against the target I set, and what people usually look at in a mix." |
| 11 | `dashboard.py:2057-2058` | Quick start: "for anything **I'm too concentrated in**" | Rewrite | "...and show how much of the portfolio is in any one holding." ("too" asks for a rating.) |
| 12 | `views/dashboard_page.py:26` | Default Ask: "what's a sensible next step **for me** to learn about?" | Consider | "What do people usually learn about after setting up a plan?" |
| 13 | `views/assistant.py:76-78` | "so Northwend's **answers fit your** timeline and comfort with ups and downs" | Rewrite | "so Northwend can use your timeline and goal in its examples and sums." |
| 14 | `views/first_steps.py:311-313` | Welcome: "it shows **what kind of investor you are** and a route to follow" | Rewrite | "it shows common starting points and a route to follow" |
| 15 | `learn.py:189` | Foundation type: "**Build your base first** - investing comes right after." | Rewrite | "Many people build a base first: savings, then investing." |
| 16 | `learn.py:190-193` | "**People in your spot** usually start by ... It's often **the strongest first move**" | Rewrite | "Many people start by putting a little aside for emergencies and paying down high-interest debt." ("People in your spot" is the soft form brief 5.3 names: "most people in your position would...") |
| 17 | `learn.py:231` | Grower type: "**people in your spot** often hold mostly stocks" | Rewrite | "With many years ahead, a mix that is mostly stocks is a common starting point." |
| 18 | `views/kit.py:289` | Storm note: "**Holding steady through a storm earns the storm cloak**" (`gear.py:86`: "For holding steady through a market drop instead of selling") | Rewrite | Earn it for a habit or learning in a storm (reading "What storms have looked like", writing a storm note), never for not selling (principle 5). |
| 19 | `views/kit.py:279-281` | "**Nothing needs doing today.** If your goal is years away, the plan you set still holds" | Rewrite | "Drops like this are part of investing. Your plan's target and dates haven't changed; they're on the Plan page." |
| 20 | `checkin.py:270-275`, `:286-290` | Walk verdict: "your plan says **nothing to do this month**"; "your plan **points your next deposit mostly to bonds**" | Consider (L3) | "Your mix is within the band you set." / "Bonds are 8 points under the target you set; money added to bonds would move the mix back toward it." See `docs/LEGAL_GATES.md` section 4. |
| 21 | `views/dashboard_page.py:54-58` | Route: "**Close the gap to your goal** ... About $743 would get you there" | Consider | "The gap to your goal": "At about $743 a month, the projection reaches your goal by June 2031 at the plan's assumed return - or the date or the target could move. Hypothetical." |
| 22 | `views/dashboard_page.py:76` | Route: "You're on track. **Keep adding $X a month and your plan gets you there** by <date>." | Rewrite | "On track: at $X a month, the projection reaches your goal by <date>. Hypothetical, not a promise." (Projections must be labelled hypothetical, principle 2.) |
| 23 | `views/dashboard_page.py:49` | Route: "**Choose how much to add each month**" | Consider | "Your monthly amount" |
| 24 | `learn.py:62`, `:65`, `:77` | Readiness: "**Aim for** 3-6 months..."; "**Start with** an emergency fund"; "paying it down first is **a strong move**" | Rewrite | "Many people keep 3-6 months of expenses in savings before investing."; "Credit card interest is often 20% a year or more - more than investing usually earns - which is why many people pay it down first." |
| 25 | `views/get_started.py:650-652` | Practice, to someone who answered "Sell everything": "Selling during a drop locks in the loss; the chart shows what staying in would have looked like." | Consider | Say it to everyone, in general: "In past drops, people who sold locked in the loss; the chart shows the whole stretch." |
| 26 | `views/dashboard_page.py:418` | Yellow warning: "**Positions over 15%** of portfolio value" | Consider | Neutral styling: "Holdings that are more than 15% of the portfolio (a line many people use to check concentration):" |
| 27 | `views/next_deposit.py:86` | Home: "New money can bring it back without selling: your next deposit **could go mostly to bonds**." | Consider | "Toward the target you set, money added to bonds would bring it back without selling." (brief 3.1: make clear the target is theirs) |
| 28 | `client_plan.py:304-305`, `views/profile.py:111`, `:127` | PDF heading "**Suggested next steps**"; "AI-suggested next steps" | Rewrite | "Things to learn about and questions to ask" |
| 29 | `website/templates/new-to-investing.html:39` | "An example mix: What a simple portfolio looks like **for someone with your answers**." | Rewrite | "Common starting points: what simple mixes look like for different timelines - the same for everyone." |
| 30 | `website/templates/new-to-investing.html:119` | "the kinds of broad, low-cost index funds many people start with - **for each part of your mix**, examples from three different providers" | Rewrite | "...for each kind of fund, examples from three different providers" (named funds only in material identical for everyone). |

Severity here: Rewrite 21, Consider 9.

**One standing rule applies to every rewrite above:** never remove a
disclosure. Where a line is both a problem and a disclaimer (Rewrite 12,
Consider 6), change what the disclaimer sits under, and keep the disclaimer.
