# Legal gates

Per the owner's master brief, section 6. Written against staging commit
`899f35a` (Oct 5, 2026). Nothing in the code or copy was changed for this
document. It is not legal advice: the owner's securities lawyer decides each
gate. The yardstick is `docs/PRINCIPLES.md`.

Contents:
1. The gates and their flags
2. Classifications
3. Every feature that exists today
4. The Monthly Walk verdict: what L3 should look at
5. Ask Northwend: the guardrails against the conclusion policy
6. Features in the brief that don't exist yet
7. Conflicts with what's already published

---

## 1. The gates and their flags

Each gate is a yes/no setting that is **off unless it is set**. Proposed
names are below. None of them exist yet. They would be read through the small
`settings.py` that `docs/PLAN.md` proposes (Phase 0, item 2). On hosted copies
they would be secrets. Staging can turn a gate on for testing with made-up
data.

| Gate | What the lawyer signs off | Proposed flag | When it is off |
|---|---|---|---|
| **L0** Beta baseline | Terms, Privacy Policy, the "educational, not advice" disclosure, 18+ and US-residency attestation, account deletion and export | `NORTHWEND_GATE_L0` (built as `L0` in `NORTHWEND_GATES`, `flags.gate("L0")`) | No open self-serve sign-up: Create account asks for an invite code first ("Northwend is in a small beta. If you have an invite code, enter it here."). The admin makes codes in Admin > Invite codes; each works once (`invite_codes.py`, step 1a.9). Signing in, setup links and admin-made accounts work as today. |
| **L1** Advisor seats and billing | Advisor agreement text, billing copy, the flat-fee-only structure, seat lapse | `NORTHWEND_GATE_L1` (and a separate `NORTHWEND_BILLING` feature flag, as the brief asks for both) | Advisor seats are free beta seats. The agreement is shown marked "beta". No price, checkout or billing screen. No call to the payment provider. |
| **L2** Directory and intro flow | Directory copy, filters, ordering rule, the two-step consent text, the standing "advice is the advisor's" line, state coverage | `NORTHWEND_GATE_L2` | No directory, no "Find a guide" link, no intro requests. Advisors add clients by setup link, as today. The standing line uses interim text. **Question for L2 (PLAN 5.7):** what an advisor sees of a client who hasn't yet confirmed sharing in their own words (a link from before consent records, or one an admin made). Today: everything, as before - the client is asked once at their next sign-in ("Keep sharing" or "Stop sharing", `views/consent_ask.py`) and the advisor's book says "hasn't confirmed sharing yet". **Question for L2 (ADR 0005):** whether "offers a one-time review" becomes a filter. Today it's shown on a listing only (offered or not, its price as the advisor states it, "Paid to the advisor directly; Northwend takes no part of it") - B4's five filters stay five and it's never a sort. Also for review here: the "How advisors are paid" explainer on Find a guide (`directory.FEES_*`) and the quiet "Want a second opinion? Find a guide" line on Learn and Plan (`directory.GUIDE_LINE`). |
| **L3** Conclusion policy | The example-mix rewrite and Ask Northwend's conclusion policy, with the eval set as evidence | `NORTHWEND_GATE_L3` | Anything worked out from a person's answers shows its most careful form (see below). |
| **L4** In-house advice | Never in scope | **No flag.** | Nothing is built toward it. If asked, refuse and point here. A test could check that no `NORTHWEND_GATE_L4` setting or code path exists. |

**What "off" means for L3 (proposal, for the owner to confirm).** The brief
says to "apply the example-mix rewrite behind gate L3". Today's wording ("an
example for someone with your answers") must go in **both** states. So:
- **L3 off:** the rewritten "common starting points" table, the same for
  everyone, with no bucket picked for the person and no "Use the suggestion"
  button that copies a mix into their target. Ask Northwend runs under the
  strict conclusion policy. The walk verdict uses descriptive wording.
- **L3 on:** whatever form the lawyer approves. For example, the person's own
  timeline bucket highlighted in that same table.

*Built in step 2 (Oct 6):* `flags.gate("L3")` is `dashboard.TAILORED_MIX`
(`flags.GATE_CHECKS["L3"]`). Off: the common starting points table
(`learn.common_starting_points`), no investor type, no "Use this" that copies
Northwend's mix into a target, practice mixes the same for everyone, and Ask
Northwend's rules add `situation_general` (`ai_policy.rules()`). On: today's
tailored example mix, its copy reworded (no "for your answers", no "for
you"), pending the lawyer. The stricter AI rules and the output check
(`ai_policy.py`) apply either way. Rows B2, B5, B6, B9, B10, B11, B14, B16,
C1, C2, C3, D1, D4, D7, G1, G2, G4 and W2 say what changed.

**Gates and feature flags are different things.** The Ritual items (R1-R5)
each get their own feature flag (brief 3.2). A feature that is also inside a
gate needs both to be on.

**Today's live copy has open sign-up.** With L0 off by default, the next
deploy would close self-serve sign-up unless the secret is set. That matches
the brief (the Terms and Privacy Policy are still drafts - audit 1.10a). It is
an owner decision to make before the flag ships. *(Step 1a.9 built it: to keep
sign-up open, set `NORTHWEND_GATES = "L0"` in the live app's secrets before
that release; without it, sign-up there needs an invite code.)*

**Standing rules (brief 9.5) that touch this file:** never build toward L4;
never add usage-based billing; never rank the directory; never let a helper
write to the database or change holdings; **never remove a disclosure**;
show diffs before any destructive change.

---

## 2. Classifications

| Class | Means |
|---|---|
| **Education** | General education. The same for everyone. Uses none of the person's data. |
| **Calculator** | Arithmetic on numbers the person typed or set themselves. |
| **Descriptive** | States facts about the person's own holdings, plan or answers. No judgement. |
| **Advisor tool** | Used by a registered advisor. What it produces is the advisor's. |
| **Directory** | Listing advisors, and the intro between a person and an advisor. |
| **Billing** | Money moving: seat fees. |
| **Account** | *(Added - not in the brief's list.)* Sign-in, settings, export, deletion, admin. Plumbing, not content. Forcing these into the six classes would mislabel them. |

The "Prescriptive today?" column answers one question: does the feature, as
it is today, conclude or imply what *this person* should hold, buy, sell,
change or target? **Yes** means it does, at least in part. **Borderline**
means the logic is fine but the wording or a default leans that way. **No**
means it stays on the right side of the "for you" line.

---

## 3. Every feature that exists today

Files are repository paths. Line numbers are at commit `899f35a`.

### 3.1 Sign-in, account, admin

| # | Feature | Where | Class | Gate | Prescriptive today? |
|---|---|---|---|---|---|
| A1 | Sign in, stay signed in, sessions | `dashboard.py` `_login`, `auth.py` | Account | L0 | No |
| A2 | Self-serve sign-up ("I'm 18 or older" box, agreeing to the disclosures) | `dashboard.py:818`, `auth.py:199-222` | Account | L0 | No. "I live in the United States" is asked beside the 18+ box, both kept with their times (step 1a.9). |
| A3 | Setup link from an advisor or admin | `dashboard.py:730`, `auth.py` | Account | L0 | No |
| A4 | Confirm email, change email, reset password | `auth.py`, `mailer.py:112-144`, `mailer.py:314` | Account | L0 | No |
| A5 | Two-step sign-in (required for advisors and admins) | `two_step.py`, `views/two_step.py` | Account | L0 | No |
| A6 | Account page: name, look, email, password, signed-in devices | `views/account.py` | Account | L0 | No |
| A7 | Export everything (ZIP of CSVs) | `export.py`, `views/account.py:316` | Account | L0 | No |
| A8 | Delete my holdings; delete my account | `views/account.py:329`, `views/account.py:341`, `admin.py` | Account | L0 | No |
| A9 | Leave me out of feature counts | `feature_counts.py`, `views/account.py` | Account | L0 | No |
| A10 | About and disclosures (in the app and as the website's About page) | `disclosures.py` | Education | L0 (its paid and advisor sections change at L1/L2 - section 7) | No |
| A11 | "Something went wrong" message; error email to the admin | `friendly_errors.py`, `error_alerts.py` | Account | L0 | No |
| A12 | Admin portal: accounts, advisor requests, AI use, feature tests, System | `views/admin.py`, `admin.py` | Account | L0 | No |
| A13 | Asking for advisor access (firm and CRD or licence number; the admin checks and approves) | `auth.py:964-991`, `views/admin.py:48`, `mailer.py:225-266` | Advisor tool | L1 | No. No stored evidence, check date or yearly re-check yet (brief 4.1). **Step 5:** the approval form records the source (BrokerCheck / IAPD), the CRD matched and the day (`licence_check.py`, `licence_checks`); Admin lists re-checks due from 11 months, flags 13; a nightly count is emailed to the admin. |
| A14 | Advisor preview: a made-up book while access is checked | `advisor_demo.py`, `views/advisor_demo.py` | Advisor tool | L1 | No |
| A15 | AI allowances and the "used up" messages | `ai_usage.py` | Account | L0 | No |

### 3.2 Learn (the route for someone new) and First steps

| # | Feature | Where | Class | Gate | Prescriptive today? |
|---|---|---|---|---|---|
| B1 | First steps slideshow: welcome, tap questions, goal, bring it in | `views/first_steps.py:285` | Calculator | L0 | No. Its goal screen's "a month - what reaches your goal" (`views/first_steps.py:227`) is arithmetic. |
| B2 | First steps "Your direction" screen | `views/first_steps.py:234` (draws B10) | Descriptive | **L3** | **Yes** - see B10. **Step 2 (L3 off): No** - the screen is "Common starting points", the same table for everyone (`learn.common_starting_points`); the type and its mix show only with L3 on. |
| B3 | The route: two stages, progress, the next waypoint | `views/get_started.py:1031`, `route.py` | Education | L0 | No |
| B4 | About you (the profile questions) | `views/get_started.py:204`, `views/profile.py:49` | Calculator | L0 | No |
| B5 | Are you ready to invest? (readiness check) | `learn.py:51-109`, `views/get_started.py:227` | Descriptive | **L3** (review) | **Borderline.** Not about securities, but it tells this person what to do first, with a red "Start here": "Start with an emergency fund" (`learn.py:65`), "paying it down first is a strong move" (`learn.py:77`), "Putting in enough to get the full match is usually the best return available" (`learn.py:86-87`). General form: "Many people build 3-6 months of savings first." **Step 2:** the three lines now speak in general terms ("Many people keep 3-6 months...", "which is why many people pay it down first", "An employer match adds money on top... Many people check what they'd need to put in to get all of it"); the red "Start here" state stays (Borderline). |
| B6 | Set a goal: what, monthly amount, how it's going, **target mix** | `views/get_started.py:319-431` | Calculator | L0; mix part **L3** | **Yes, for the mix part.** The slider starts at the example mix from their answers (`views/get_started.py:418-419`), and "Use the suggestion: X% stocks, Y% bonds - the example mix for your answers" (`views/get_started.py:424-426`) makes it their target in one tap. That target then drives drift, next deposit and the walk verdict. **Step 2 (L3 off): No** - nothing is filled in: they type their own % in stocks, with the common starting points table beside it for reference, and saving needs a number. L3 on keeps the slider and "Use this" (the example mix), and a target taken untouched is recorded (`checkin.PREF_TARGET_FROM`, see C3). |
| B7 | Learn the basics: six short reads, lesson numbers | `views/get_started.py:436-512`, `learn.py` | Education | L0 | No. The lesson numbers use the person's monthly amount and years (calculator). |
| B8 | "What these kinds of funds look like" (three kinds, three providers each) | `starter_funds.py` | Education | L0 | No - the same for everyone. But see B14 for where it is shown. |
| B9 | An example mix | `views/get_started.py:516-551`, `learn.starter_mix` `learn.py:140` | Descriptive | **L3** | **Yes.** "An example for someone with your answers: 60% stocks, 40% bonds" (`views/get_started.py:524`), then how *their* answers move it. Brief 3.1 says rewrite as common starting points by bucket, the same for everyone in the bucket. **Step 2 (L3 off): No** - the waypoint is "Common starting points": one table (5 timelines x 3 comfort columns) with no row picked, how timelines and comfort move a mix in general, the kinds of funds, "Illustrations, not a plan for you". L3 on keeps the example mix, reworded "An example worked out from your timeline and comfort answers". |
| B10 | Find your direction (the investor type card and window; the type name on Home's route) | `learn.investor_type` `learn.py:240`, `learn.INVESTOR_TYPES` `learn.py:186-237`, `views/get_started.py:962-1001`, `views/dashboard_page.py:119-125` | Descriptive | **L3** | **Yes.** Names a type for the person, "An example mix for this type", "Kinds of funds that usually fill it". The Foundation type says "Build your base first" and "the example mix below shows what investing could look like for you" (`learn.py:189-195`). **Step 2 (L3 off): No** - no type is named for anyone (Home's route label, Learn's and Home's direction line, the window): a "Common starting points" line opens the general table. With L3 on, the copy is rewritten ("Many people build a base first", no "people in your spot", no "for you", "Ask Northwend about this"). |
| B11 | Try it with practice money | `views/get_started.py:554-660`, `learn.simulate` | Calculator | L0; its "Example mix" choice **L3** | **Borderline.** The default mix is their example mix, run on the named stand-in funds. For someone who answered "Sell everything", it adds "Selling during a drop locks in the loss" (`views/get_started.py:650-652`) - a behaviour nudge aimed at them. **Step 2 (L3 off): No** - the choices are the target they set (if any), All stocks, 80% stocks, 60% stocks and Mostly bonds - the same for everyone - and the "Sell everything" line isn't shown. |
| B12 | Choose a brokerage (what to compare; brokerages alphabetical, unranked) | `brokerages.py`, `views/get_started.py:736` | Education | L0 | No |
| B13 | Open your account (steps and checklist) | `views/get_started.py:750` | Education | L0 | No. "Many people finish a 3-6 month emergency fund first" is shown only to those who answered short on savings - mild. |
| B14 | Your first investments | `views/get_started.py:770-791` | Education | **L3** | **Yes, by placement.** It opens with "Your direction: ... an example mix of X% stocks, Y% bonds, from your answers" (`views/get_started.py:779-782`), then "What your first buy looks like", then the named-fund card (B8). `starter_funds.py`'s own docstring says named funds next to "your mix" would read as a recommendation. **Step 2: No** - with L3 on or off, the step shows no direction, mix or target, and the page's direction / common-points line is hidden on this step; the named-fund card is the general one, the same for everyone. |
| B15 | Bring it in (waypoint) | `views/get_started.py:794` | Account | L0 | No |
| B16 | Home before anything is brought in: the route card and waypoint lines | `views/start_home.py:74`, `views/start_home.py:15-29` | Education | L0 | Borderline, through copy only: "What a mix could look like for someone with your answers" (`views/start_home.py:21`). **Step 2: No** - "Common starting points for different timelines - the same for everyone, not a plan for you." (L3 on: "An example mix worked out from your timeline and comfort answers"). |
| B17 | Learn more links (trusted public sources) | `learn.LEARN_MORE` | Education | L0 | No |

### 3.3 Home (with holdings)

| # | Feature | Where | Class | Gate | Prescriptive today? |
|---|---|---|---|---|---|
| C1 | Your route card: goal progress and the one next step | `route.py:15-75`, `views/dashboard_page.py:30-152` | Calculator | L0; wording **L3** | **Borderline.** The numbers are arithmetic toward their own goal. The words are orders: "Close the gap to your goal ... About $743 (... more) would get you there by <date> at the plan's assumed return - or you could move the date or the target" (`views/dashboard_page.py:53-58`); "You're on track. Keep adding $X a month and your plan gets you there by <date>" (`:76`), a projection not labelled hypothetical. **Step 2:** the on-track line is now "At $X a month, the projection reaches your goal by <date>. Hypothetical, not a promise." The "close the gap" line is unchanged (Consider). |
| C2 | Storm note ("Weather on the trail") and "What storms have looked like" | `storms.py`, `views/kit.py:243-301` | Descriptive | L0; wording **L3** | **Yes (soft).** "Nothing needs doing today. If your goal is years away, the plan you set still holds" (`views/kit.py:279-281`) is a hold message to this person during a drop. "Holding steady through a storm earns the storm cloak" (`views/kit.py:289`) rewards not selling - a trading behaviour, not learning or a habit (principle 5). The history table itself is general education. **Step 2:** the hold message is now "Drops like this are part of investing. Your plan's target and dates haven't changed; they're on the Plan page." The storm cloak (earned for not selling) is unchanged - still open (gear logic, not copy). **Step 7 (AI_PLAN section 9 row 4):** every word on the note and in the window is a fixed template in `storms.py` (`narrate`, `WINDOW_NOTE`), history in the past tense, checked against prediction words by a test; "some of the market's best days have come soon after its worst" is now "strongest days have come within days of its weakest". No AI. |
| C3 | The Monthly Walk (update, drift, one read, verdict; streak; next walk date) | `checkin.py`, `views/checkin.py` | Descriptive | L0 + its feature flag; the verdict **L3** | **Yes (soft, by design).** See section 4. **Step 2:** where the target came from is recorded (`checkin.PREF_TARGET_FROM`: own, advisor, or Northwend's example mix taken untouched - possible only with L3 on). While it is still the example mix, the verdict adds "This target started as Northwend's example mix and hasn't changed since. Is it the one you want? You can keep it as yours, or change it on the Plan." with a "Keep it as mine" button. The verdict wording itself is unchanged (section 4, points 1 and 4). |
| C4 | The walk's reminder email (off unless turned on) | `checkin_email.py` | Account | L0 | No. No figures. Still needs an unsubscribe header (audit 1.7c). |
| C5 | Your kit: milestones and gear | `gear.py`, `views/kit.py:113-221` | Education | L0 | Borderline only through the storm cloak (C2). The rest rewards learning and habits. |
| C6 | "Your money, checked" card (one line each for C7-C9) | `views/cash_check.py:112` | Descriptive | L0 | No |
| C7 | Fee check: each fund's fee in dollars, total, over 10 and 30 years | `fees.py`, `views/fees.py:36-90` | Descriptive | L0 | No. "Low-cost index funds of this kind often charge" sits on each row, with "not a suggestion to buy or sell anything". L3 may want a look: a cheaper figure on the same row as their fund can read as "switch". |
| C8 | Fund overlap | `fund_holdings.py`, `views/fund_overlap.py` | Descriptive | L0 | No. "This describes what your funds hold - it isn't a suggestion to buy or sell" (`views/fund_overlap.py:143`). |
| C9 | Cash check | `cash_check.py`, `views/cash_check.py:53-90` | Descriptive | L0 | No. No fund, brokerage or rate named. |
| C10 | Account map: the "if something happens to me" binder, its PDF, the Home nudge | `account_map.py`, `views/account_map.py` | Descriptive | L0 | No |
| C11 | Year in review, the share card and its PDF (no amounts) | `recap.py`, `views/year_review.py` | Descriptive | L0 | No |
| C12 | Notes to future you (on a holding or the plan; shown back in a storm) | `future_notes.py`, `views/future_notes.py` | Descriptive | L0 | No - the person's own words. |
| C13 | Portfolio value, today's move, since your last visit, totals | `views/dashboard_page.py:166-230` | Descriptive | L0 | No |
| C14 | Alerts: day move beyond ±5%, total gain/loss beyond ±20% (limits changeable) | `alerts.py`, `views/dashboard_page.py:263-290` | Descriptive | L0 | **Borderline.** Northwend picks the defaults. A red bell and "positions past your limits" frame normal moves as something to act on (calm-by-default, principle 5). Not advice. |
| C15 | Performance chart | `perf.py`, `views/dashboard_page.py:293-370` | Descriptive | L0 | No |
| C16 | Allocation bars, how holdings are classified, the Targets popover | `allocation.py`, `views/dashboard_page.py:377-411` | Descriptive | L0 | No |
| C17 | Concentration: "Positions over 15% of portfolio value" | `allocation.py:13`, `views/dashboard_page.py:412-420` | Descriptive | L0; wording **L3** | **Borderline.** The 15% line is Northwend's, fixed, in a yellow warning. It reads as "too much in one holding" - a rating of the person's choice (brief 5.3). The same line is fed to the AI ("facts worth pointing out", `advisor.py:443-448`) and printed in the plan PDF's "Things to watch" (`client_plan.py:289-296`). |
| C18 | Drift notice and the "next deposit could go" line | `views/dashboard_page.py:422-446`, `views/next_deposit.py:76-87` | Descriptive | L0 | No, when the target is their own. The line should say "the target you set". Inherits the target-origin problem in B6 and D7. |
| C19 | Accounts side by side, holdings table, one ticker's chart, stats and news | `views/dashboard_page.py:452+`, `views/ticker_detail.py`, `news.py` | Descriptive | L0 | No |

### 3.4 Plan (its tabs)

| # | Feature | Where | Class | Gate | Prescriptive today? |
|---|---|---|---|---|---|
| D1 | Goal form and goal status, with "Suggested starting point for your answers" lines | `views/plan.py:193-300`, `learn.suggestions` `learn.py:287` | Calculator | L0; the suggestion label **L3** | **Borderline.** The monthly amount is arithmetic. The goal date from age and the 6% return are typical values. The label "Suggested starting point for your answers" says Northwend suggests something for them. **Step 2: No** - each line says what kind of number it is: "What reaches your goal: $X a month, at 6% a year", "From your own timeline answer: by <date>", "A typical value people use: 6% a year" (`views/plan.py` `SUGGEST_LEADS`); the button reads "Use this". |
| D2 | How it's going (the range to the goal) | `views/plan.py:345` | Calculator | L0 | No |
| D3 | Money going out: planned expenses, a regular withdrawal, how long it lasts | `views/plan.py:130-183`, `views/plan.py:467`, `plans.py` | Calculator | L0 | No. "About $Z more a month gets you back on track" and "taking $X less a month or starting N years later makes it last" are arithmetic on their own items, labelled "Arithmetic on the plan's numbers, not advice". R11 (Pay Yourself) would go further. |
| D4 | What if | `views/plan.py:783` | Calculator | L0; its suggestion **L3** | **Borderline.** "Use the suggestion" fills the example mix's % in stocks (`views/plan.py:815-820`). **Step 2 (L3 off): No** - "From your own plan: $X a month · N years" only; the % in stocks starts from their own mix or target, else 60% for everyone. |
| D5 | Contributions (log money added or taken out; Free money check link) | `views/plan.py:587` | Calculator | L0 | No |
| D6 | Money in vs growth | `views/plan.py:656` | Descriptive | L0 | No |
| D7 | Target mix: edit targets and the band | `views/plan.py:685-768` | Calculator | L0; its suggestion **L3** | **Yes, for the suggestion.** "Use the suggestion: 60% stocks, 40% bonds - the example mix for your answers" (`views/plan.py:744-747`) sets their target in one tap. ("Apply a model portfolio" is the advisor's - H5.) **Step 2 (L3 off): No** - no button; "Your target is yours to choose" and the common starting points table. L3 on keeps "The example mix from your timeline and comfort answers: ... Use this", and saving it untouched is recorded as the example's (C3). |
| D8 | Where could your next deposit go? | `next_deposit.py`, `views/next_deposit.py:23-73` | Calculator | L0 | No - brief 3.1 keeps it. Its copy should say the target is theirs. It inherits the target-origin problem. |
| D9 | Stress test (2008, 2020, 2022 on the mix now and the target) | `stress.py`, `views/stress_test.py` | Calculator | L0 | No |
| D10 | Retirement income: what it pays now, 3/4/5% a year, how long a yearly amount lasts | `views/plan.py:897-997`, `plans.py:767-784` | Calculator | L0; review **L3** | **Borderline.** Three rules of thumb, labelled "not a promise", applied to their own value. "A yearly amount to try" starts at 4% of their value (`views/plan.py:973-974`) - Northwend picks the starting number. |

### 3.5 Money (Income, Activity, Watchlist)

| # | Feature | Where | Class | Gate | Prescriptive today? |
|---|---|---|---|---|---|
| E1 | Income: next 12 months, received, by holding, yield on cost | `income.py`, `views/income.py` | Descriptive | L0 | No |
| E2 | Activity: buys and sells from updates, imported history | `changes.py`, `txn_import.py`, `views/activity.py` | Descriptive | L0 | No |
| E3 | Watchlist | `watchlist.py`, `views/watchlist.py` | Descriptive | L0 | No |

### 3.6 Getting holdings in

| # | Feature | Where | Class | Gate | Prescriptive today? |
|---|---|---|---|---|---|
| F1 | Add or update holdings: paste, by hand, percentages only, CSV, activity export | `paste_parse.py`, `manual_entry.py`, `csv_import.py`, `txn_import.py`, `views/holdings_input.py` | Account | L0 | No |
| F2 | Read screenshots (AI, opt-in) | `screenshot_read.py` | Account | L0 | No. (A figures question, not an advice one: the image goes to the model. See the AI plan, brief 5.1.) |
| F3 | Let AI guess the columns (CSV, on a button) | `csv_import.py` | Account | L0 | No |
| F4 | Example portfolio (made up) | `sample_data.py` | Education | L0 | No - the same for everyone. |
| F5 | "Not sure yet" tab: the kinds-of-funds card | `views/holdings_input.py:669` | Education | L0 | No |

### 3.7 Ask Northwend and the other AI on the individual side

| # | Feature | Where | Class | Gate | Prescriptive today? |
|---|---|---|---|---|---|
| G1 | Ask Northwend chat (with memory and profile tools) | `advisor.py`, `views/assistant.py` | Education | **L3** | **Yes, in part.** See section 5. **Step 2:** the stricter rules and the output check are built (`ai_policy.py`, for the gateway to wire), and the 64-case eval (`evals/`) - see section 5. |
| G2 | Ready-made questions: quick starts, route and waypoint "Ask Northwend" buttons | `dashboard.py:2054-2069`, `views/dashboard_page.py:9-27`, `views/get_started.py:62-80`, `views/get_started.py:954-959`, `views/start_home.py:30` | Education | **L3** | **Yes.** Northwend writes these questions, and several ask the model for a conclusion about the person that it must then refuse: "Which account type fits me?", "anything I'm too concentrated in", "Review my portfolio", "Looking at my situation, what should I take care of ... and in what order?", "why a mix ... might fit my time horizon", "what's a sensible next step for me", "what that means for someone like me". **Step 2:** rewritten to general forms - "What do people do before investing?", "What kinds of accounts are there?", "...show how much of the portfolio is in any one holding", "What do people usually take care of before they start investing, and in what order?", "How do people usually think about splitting money ... for different timelines?", "Explain the \"{type}\" description in general terms". Still open (Consider): "Review my portfolio", "what's a sensible next step for me to learn about?", "What should I keep an eye on from here?". |
| G3 | Your investing profile window | `views/assistant.py:30`, `views/profile.py:49` | Calculator | L0 | No. Its copy "so Northwend's answers fit your timeline and comfort with ups and downs" (`views/assistant.py:75-78`) promises tailored answers. |
| G4 | Printable plan (PDF) with "Suggested next steps" written by AI | `client_plan.py:35-46`, `client_plan.py:288-311`, `views/profile.py:100-140` | Descriptive (+AI) | **L3** | **Yes.** The model is asked for "3 to 6 concrete, educational steps tied to their goals and risk tolerance", printed as "Suggested next steps" in a document called a plan. Also prints "Things to watch" with the 15% line (C17). **Step 2: No** - no AI: "Questions to look into" from fixed rules over their own answers and figures (drift beyond their band, a fee from 0.50%, cash from 20%, the goal's projection, open answers, emergency fund, debt, match), each a question, plus two asked of everyone (`client_plan.questions`). "Things to watch" is unchanged. **Step 7 (row 12):** the getting-ready questions come from `learn.readiness`, and the plan ends with a fixed bank, "Questions people often ask a licensed professional" (`client_plan.PRO_QUESTIONS`, the same for everyone; never that they need one). |

### 3.8 Advisor side

L1 off means these run as free beta seats, as today. The standing line is L2.

| # | Feature | Where | Class | Gate | Prescriptive today? |
|---|---|---|---|---|---|
| H1 | Your clients: the book, reason chips, search | `views/clients.py:941`, `overview.py` | Advisor tool | L1 | No |
| H2 | Add a client; setup link and invite email | `views/clients.py:655`, `auth.py`, `mailer.py:198` | Advisor tool | L1; consent **L2** | No. Today this is the only way a client joins an advisor. There is no separate, recorded second consent (brief 4.3). **Step 5:** the setup link shows the sharing sentence and records a grant with it (one by one and from a file alike); a client whose sharing has no grant in their own words (from before the records, or an admin's link) is asked once at sign-in, unflagged (`consent.to_ask`, `views/consent_ask.py`). |
| H3 | Add clients from a file | `client_csv.py`, `views/clients.py:761` | Advisor tool | L1 | No |
| H4 | Message clients (and the "you have a message" email) | `views/clients.py:853-938`, `mailer.py:268` | Advisor tool | L1; line **L2** | No. The message carries no firm name and no "advice is the advisor's" line (brief 4.4). **Step 5:** each message, and its email, carries the standing line with name and firm (`standing_line.py`, interim text). |
| H5 | Model portfolios (save; apply on a client's Plan) | `views/clients.py:516`, `views/plan.py:729-738` | Advisor tool | L1 | No - the advisor's. |
| H6 | How clients see you (advisor card); Monday email setting | `views/clients.py:465-513` | Advisor tool | L1 | No |
| H7 | This week summary and the Monday email (counts only) | `views/clients.py:1084`, `weekly_email.py`, `mailer.py:186` | Advisor tool | L1 | No |
| H8 | Advisor notes: notes, next steps, reviews, archive and edit history; the client's "Your advisor" page | `views/clients.py:15-188`, `advising.py` | Advisor tool | L1; line **L2** | No. **Step 5:** the advisor card over the client's notes carries the standing line. |
| H9 | Meeting prep: what changed, AI talking points kept as a private note | `meeting.py`, `views/meeting.py` | Advisor tool | L1 (AI policy L3) | No. Drafts for the advisor only. |
| H10 | Proposals: draft, compare, share; the client accepts or replies; PDF; emails | `proposals.py`, `views/proposals.py`, `mailer.py:158-183` | Advisor tool | L1; line **L2** | No. The PDF says "This proposal is your advisor's recommendation ... Northwend ... does not give investment advice" (`proposals.py:176-178`). The in-app card and the email don't carry that line or the firm. **Step 5:** the card, the PDF and the email carry the standing line with name and firm. |
| H11 | Progress reports: send, read, PDF, email | `reports.py`, `views/reports.py`, `mailer.py:144` | Advisor tool | L1; line **L2** | No. The PDF footer says "Prepared by your advisor in Northwend" (`reports.py:16`), without the standing line or firm. **Step 5:** the in-app report, its PDF and the email carry the standing line with name and firm. |
| H12 | Export a client's record; export all records | `export.client_record_zip`, `views/clients.py:190-260` | Advisor tool | L1 | No |
| H13 | End the relationship; client stops sharing; former clients; their emails | `advising.end_relationship`, `views/clients.py:261-436`, `mailer.py:281-312` | Advisor tool | **L2** (revocation, brief 4.3) | No |
| H14 | Client mode: no example funds or practice money; Home shows the advisor's next step | `route.advisor_step`, `views/start_home.py:158-230` | Advisor tool | L1 | No |
| H15 | An advisor viewing a client's Home, Plan and Money | `dashboard.py` (`can_view`) | Advisor tool | L1; logging **L2** | No. No access log yet (brief 4.3.5). |

### 3.9 Emails

All carry no figures today. None is prescriptive.

| Email | Where | Class | Gate |
|---|---|---|---|
| Confirm email, confirm new email, email changed, reset password, account created | `mailer.py:112-140`, `mailer.py:214`, `mailer.py:314` | Account | L0 |
| Monthly walk reminder | `checkin_email.py` | Account | L0 |
| Error alert to the admin | `error_alerts.py` | Account | L0 |
| Advisor request (to support), approved, declined | `mailer.py:225-266` | Advisor tool | L1 |
| Client invite, report ready, proposal shared, proposal answered, advisor message | `mailer.py:144-212`, `mailer.py:268` | Advisor tool | L1 (standing line L2) |
| Relationship ended, client stopped sharing | `mailer.py:281-312` | Advisor tool | L2 |
| Advisors' Monday email | `weekly_email.py`, `mailer.py:186` | Advisor tool | L1 |

### 3.10 PDFs

| PDF | Where | Class | Gate | Prescriptive today? |
|---|---|---|---|---|
| Client plan with rule-based "Questions to look into" (was AI "Suggested next steps") | `client_plan.py` | Descriptive | **L3** | No since step 2 (G4) |
| Proposal | `proposals.py` | Advisor tool | L1 | No |
| Progress report | `reports.py` | Advisor tool | L1 | No |
| Year in review, to share | `recap.py:425` | Descriptive | L0 | No |
| Account map | `account_map.py:297` | Descriptive | L0 | No |

### 3.11 Website (northwend.app)

| # | Page | Where | Class | Gate | Prescriptive today? |
|---|---|---|---|---|---|
| W1 | Home | `website/templates/home.html` | Education | L0 | No |
| W2 | New to investing | `website/templates/new-to-investing.html` | Education | L0; two lines **L3** | **Borderline.** "An example mix: What a simple portfolio looks like for someone with your answers" (`:39`). "for each part of your mix, examples from three different providers" (`:119`) ties named funds to "your mix". **Step 2: No** - "Common starting points: What simple mixes look like for different timelines - the same for everyone."; "for each kind of fund, examples from three different providers". |
| W3 | For advisors | `website/templates/advisors.html` | Advisor tool | L0; pricing copy **L1**; any directory mention **L2** | No |
| W4 | About (from `disclosures.py`) | `website/build.py` | Education | L0 | No |
| W5 | 404 | `website/templates/404.html` | Education | L0 | No |
| W6 | Decode your 401(k) menu (explains the no-account decoder and links to `?decode=401k`; a made-up example table in pasted order) | `website/templates/decode-401k.html` | Education | L0 (the route it links to: L0 + `decoder_public`, section 6) | No. "It doesn't rank the funds or say which to choose", "An educational tool, not financial advice", nothing about which fund to pick. |

### 3.12 Counts

| Class | Features |
|---|---|
| Education | 19 |
| Calculator | 15 |
| Descriptive | 25 |
| Advisor tool | 18 |
| Account | 17 |
| Directory | 0 |
| Billing | 0 |
| **Total** | **94** |

These count the rows in 3.1-3.8 and 3.11, and leave out the email and PDF
tables, which repeat features already counted. Directory and billing are
empty because none of it exists yet (section 6).

Prescriptive today: **Yes** - 11 rows (B2, B6, B9, B10, B14, C2, C3, D7, G1,
G2, G4). **Borderline** - 11 rows (B5, B11, B16, C1, C5, C14, C17, D1, D4,
D10, W2), and C7 is worth a glance.

**After step 2, with L3 off (production):** of the 11 "Yes" rows, B2, B6,
B9, B10, B14, D7 and G4 are No. Still open: C2 (the storm cloak, earned for
not selling), C3 (the verdict's wording; where the target came from is now
recorded and asked about), G1 (until the gateway wires `ai_policy`) and G2
(three Consider-level ready-made questions). Of the Borderline rows, B11,
B16, D1, D4 and W2 are No; B5 and C1 are reworded but stay Borderline.

---

## 4. The Monthly Walk verdict: what L3 should look at

**What it does.** `checkin.verdict` (`checkin.py:223-248`) reads the
person's target mix and band. With no target, there's no verdict. Within the
band, it says "Your mix is within the band you set - your plan says nothing to
do this month" (`checkin.py:270-271`). Outside the band, it picks the class
that would get most of a deposit (`next_deposit.split`) and says, for example,
"Your target has more bonds than you hold now, so your plan points your next
deposit mostly to bonds" (`checkin.py:272-275`). The rule is shown under it
(`checkin.rule_text`). No fund, figure or "sell" ever appears.

**Why it can pass.** It is arithmetic toward a target the person set. Brief
5.3 permits "describe drift against a target the person set". Speaking as "your
plan" is honest *if* the plan is really theirs.

**What L3 should look at:**
1. **"Nothing to do this month" is a hold** for a specific person. ROADMAP
   already flags this ("Principle risks higher than stated").
2. **Where the target came from.** Today the target can be Northwend's: the
   Set a goal slider starts at the example mix (`views/get_started.py:418-419`),
   and "Use the suggestion" copies the example mix into the target in one tap
   (`views/get_started.py:424`, `views/plan.py:744`). Then the chain is
   Northwend's mix, then Northwend's verdict, said as "your plan". Options: no
   pre-fill; the person types or confirms each number; record where the target
   came from (typed, suggestion, advisor) and show it under the verdict.
   *Step 2 did both:* with L3 off nothing is pre-filled or copied (they type
   it); with L3 on, a target taken from the example mix untouched is
   recorded (`checkin.PREF_TARGET_FROM`, "example"), and the verdict says so
   and asks, with "Keep it as mine" (`checkin.TARGET_FROM_NOTE`). Targets set
   by an advisor are recorded as the advisor's.
3. **The band is Northwend's number** unless they change it: 5 points
   (`dashboard.py:2441`). The rule line still says "Your rule: ... a band of 5
   points".
4. **Wording.** "Your plan points your next deposit to bonds" directs.
   Descriptive form: "Bonds are 8 points under the target you set. Money added
   to bonds would move the mix back toward it." The caption already says
   "which funds, and whether to add money at all, is up to you" - good.
5. **Weight.** A monthly prompt, a reminder email, a streak and a kept record
   (`walk_verdicts`, used by R2 and R3) make this the most-read sentence
   Northwend writes. A record of monthly verdicts could later read as a record
   of advice.
6. **Advisor's clients.** Their target is the advisor's. The verdict should
   say "the target your advisor set with you" (the caption already says the
   advisor set it).

---

## 5. Ask Northwend: the guardrails against the conclusion policy

`advisor.GUARDRAILS` (`advisor.py:92-131`) is in every AI prompt (chat,
meeting prep, the plan PDF). The extra instructions in
`advisor.system_prompt` (`advisor.py:384-455`) matter as much.

**What the guardrails permit, quoted:**
- "explain what kinds of investments are and how they work ...; share common
  rules of thumb as general education, labelled as such; and describe the
  person's own figures plainly - what they hold, their mix, concentration,
  overlap between their funds, fees, and how they compare with a target or
  goal they set themselves." (`what_you_may_do`)
- When asked what to buy: "explain the considerations people usually weigh
  ... and suggest talking to a licensed professional, such as a fee-only
  fiduciary adviser - or, for someone who has one, their own advisor."
  (`what_should_i_buy`)
- And from the system prompt: "tie explanations to their stated goals,
  timeline and comfort with risk", and point out "overall risk (beta, asset
  mix) next to their stated comfort with risk and time horizon".

**What they forbid, quoted:** "Never recommend buying, selling or holding a
specific security ... for this person, and never recommend a specific
allocation or percentage mix for them. Don't tell them what they should buy,
sell, keep or how much to put where." Plus no guarantees, no market timing,
projections labelled hypothetical.

**Against brief 5.3:**

| Brief 5.3 says | Today | Gap |
|---|---|---|
| Permitted: explain concepts | Yes | - |
| Permitted: what kinds of mixes have done historically | Yes (general) | - |
| Permitted: arithmetic on the person's inputs **through tools** | The model does sums in prose; no calculator tools yet | Add tools (AI plan) |
| Permitted: drift against a target the person set | Yes | - |
| Permitted: fees, overlap, cash as facts | Yes | - |
| Permitted: list questions to ask a professional | Partly ("considerations") | - |
| Not: state or **imply** what this person should hold, buy, sell, **change or target** | Covers "recommend" a security or mix. Doesn't cover "change" or "target", or implying. | Add "change", "target", and soft forms ("you might want to consider moving some to bonds", "most people in your position would...") |
| Not: a mix "for you" | Covered ("specific allocation or percentage mix for them") | But "rules of thumb" applied to their profile (e.g. "110 minus your age") gives a mix for them. Say rules of thumb are given in general terms only, never worked out for this person. |
| Not: **rate the person's choices** | Not covered. The prompt *asks* for "overall risk ... next to their stated comfort with risk" | Remove that instruction; describe, don't compare against what suits them. |
| Not: **recommend an advisor** | Suggests "a fee-only fiduciary adviser" | With a directory live this reads as steering (brief 3.3: never suggest the person needs an advisor). Change to "questions to ask a professional, if you ever choose to work with one". |
| Not: predict markets | Covered (`no_guarantees`) | - |
| Eval: 60+ cases, 15 on prescriptive phrasing, fail the build | `evals/`: 64 cases, the offline checker in Tests; the real-model run by hand (step 2) | Run it on the eval workspace and keep the result as L3's evidence |

Also outside 5.3 but close: the model sees tickers and weights
(`advisor.py:6-8`, `portfolio_summary`). Brief 5.1 says models never see
individual holdings. That belongs to the AI plan's `ContextCard` work.

**Step 2 (Oct 6).** The conclusion policy is built as `ai_policy.py`:
`rules()` (AI_PLAN 7.1's ten rules - soft forms, no ratings, no advisor or
kind of adviser, calm, client mode - plus `situation_general` while L3 is
off) and `check()`, a sentence-level output check with the fixed fallback
line. The gateway (built separately) wires both into every call; until then
the prompt still uses `advisor.GUARDRAILS`. The eval set is `evals/`: 64
cases in groups A-J, the 15 prescriptive cases each with three good and
three bad canned answers; its checker runs in Tests, the real-model run by
hand on the eval workspace (`python -m evals.run --samples 3`, RUNBOOK "The
AI eval").

**Client mode (brief 5.2).** For an advisor's client, the ready-made
questions already point back to the advisor (`views/start_home.py:158-176`).
The chat itself has no client-mode rule yet.

---

## 6. Features in the brief that don't exist yet

| Feature | Brief | Class | Gate | Notes |
|---|---|---|---|---|
| US-residency attestation; 18+ as its own field | 6 (L0) | Account | L0 | Today 18+ is part of the agreement (audit 1.10c) |
| Published Terms and Privacy Policy | 6 (L0) | Account | L0 | Drafts in `docs/legal/` |
| Advisor agreement and attestation at seat activation | 4.1 | Advisor tool | L1 | Marked "beta" while L1 is off. **Built (step 5):** `advisor_agreement.py`, flag `advisor_agreement`; the text is a draft for the lawyer |
| Licence evidence, check date, yearly re-check job | 4.1 | Advisor tool | L1 | **Built (step 5):** `licence_check.py` - still a manual look-up (no official API), now recorded |
| Seat billing: hosted checkout and portal, signed webhooks, seat status, founding seats, lapse grace period, daily reconciliation | 4.5, 7, 8a | Billing | L1 + `NORTHWEND_BILLING` | Not on Streamlit Community Cloud (brief 7) |
| Pricing copy (website and app) | 4.5 | Billing | L1 | One flat price; a test that billing never reads client or intro counts |
| The directory: profiles, filters, alphabetical only, no ranking (tested) | 4.2 | Directory | L2 | **Built** behind flag `directory` + L2 (`directory.py`, `views/directory.py`, `advisor_profiles`): B4's five filters only; alphabetical by name, tested on shuffled profiles for every filter combination. A listing may say it offers a one-time review and its price as the advisor states it (`advisor_profiles.one_time_cost`, ADR 0005) - shown, never filtered or sorted on (a filter is the L2 question above) |
| "Find a guide" page and its one calm link | 3.3 | Directory | L2 | **Built**: one link, in an individual's name menu (never client mode); nothing about browsing written or counted (tested). Its copy is DRAFT (`directory.COPY_STATUS`, `INTRO`, `ABOUT_LINES`) for review here. "Request an introduction" says introductions open soon until the intro flow. **ADR 0005:** a closed "How advisors are paid" explainer beside the listings (each fee model and commissions in plain words, none favoured; questions to ask; official links only - `directory.FEES_*`, `OFFICIAL_SITES`), and one quiet "Want a second opinion? Find a guide" line on Learn (once finished) and Plan (once a goal is set), for an individual on their own account only - never an advisor, an admin, client mode or someone with an advisor; nothing written or counted (tested). All DRAFT |
| Intro request (figure-free view and a message); advisor's text reply or scheduling link | 4.3.1-2 | Directory | L2 | **Built** behind flag `intros` + L2 (`intros.py`, `views/intros.py`, `intro_requests`): the person's name, a plain-text message and the outline they tick (asset-class percents, goals, timeline bucket, stage - never amounts, tickers or account details); only to a listed advisor; the advisor sees only their own, answers once in text, shares their scheduling link or declines; no counts. Copy DRAFT (`intros.COPY_STATUS`) for review here |
| Second, separate consent to full sharing; consent records (append-only, exact text, time, advisor) | 4.3.3, 7 | Directory | L2 | Kept the lawyer's period; default 7 years. **Built**: two steps after an answer (`intros.SHARE_LINES`, then the `CONFIRM_LINE` tick); the grant (how `intro`, exact words) and the link in one transaction (`intros.share_account`). The two-step text is DRAFT for review here. **Records built (step 5):** `consent.py`; existing clients asked once at sign-in (`sign_in_ask`, `consent.ask_text` - its wording for review here) |
| Revoke sharing ends access within one request | 4.3.4 | Advisor tool | L2 | Stop sharing exists (H13); needs the one-request test |
| Advisor access log, visible to the client (append-only) | 4.3.5 | Advisor tool | L2 | |
| The standing "advice is the advisor's, not Northwend's" line, with name and firm, on every advisor artefact | 4.4 | Advisor tool | L2 | **Built (step 5) with interim text:** `standing_line.STANDING_LINE`; the lawyer's final wording replaces it |
| State-coverage handling | 6 (L2) | Directory | L2 | **Built**: "Your state" filter; an advisor isn't shown for a state they didn't list; the state picked isn't saved |
| Common starting points (the example-mix rewrite) | 3.1 | Education | L3 | Replaces B9, B10's mix, the suggestion buttons. **Built in step 2** (what L3 off shows) |
| Conclusion policy, `ContextCard`, figures opt-in, 60+ case eval | 5 | Education | L3 | Step 2 built the policy (`ai_policy.py`) and the eval (`evals/`, 64 cases); the gateway wires the policy |
| Do-Nothing Ledger (R2) | 3.2 | Descriptive | L0 + flag; L3 review | Must show both directions (ROADMAP risk list) |
| Expedition Log (R3) | 3.2 | Descriptive | L0 + flag | Its line is fixed templates from the kept verdict, percentages only (`expedition_log.line`; AI_PLAN section 9 row 3, no AI) |
| Home summary: the mix in plain words (step 7, AI_PLAN section 9 row 1) | 5.3 | Descriptive | L0 + flag `plain_summary` | **Built:** `allocation.summary_words`, one line under Allocation - shares by class, holdings and accounts, the largest holding's share. Fixed templates, no AI, no judgement words (tested); hidden with Hide amounts |
| Glossary (step 7, AI_PLAN section 9 row 5) | 5.1 | Education | L0 + flag `glossary` | **Built:** `glossary.py` (owner-written draft, 65 terms, also Ask Northwend's), "What does this mean?" on Home, Fee check, Income, Open your account; the full list in Learn the basics. No named funds or advice words (tested). The AI fallback for an unknown word is not built |
| Storm Drill / Storm Shelter (R4) | 3.2 | Descriptive | L0 + flag | |
| The Sealed Envelope: the Storm Drill answer as a one-page PDF to seal ("Open this when the market has fallen 20%") | 3.2 | Descriptive (the person's own words back; the reminder is fixed education) | L0 + flag `sealed_envelope` (needs `storm_drill`; no gate) | **Built (step 9), off.** `sealed_envelope.py`, offered under the drill answer on the Plan's Stress test (`views/future_notes.py`). The page holds only the person's words exactly as written, the day they wrote them, the envelope's label (the roadmap's own 20% - a label the person keeps, not a forecast) and a fixed reminder ("You wrote this on a calm day. Read it slowly. Nothing has to be decided today.") - no instruction to buy, sell or hold. No figures, holdings, tickers, account names, email or login (`render_pdf` takes only the words, the day and an optional name; a test seeds distinctive values and checks the PDF); the name only if ticked (off by default; the display name, never the login). Made on the download click, never saved; prefs `sealed_envelope` keeps only the day, so Home's storm note can say "You wrote yourself a sealed envelope for a day like this". Never offered while an advisor is in a client's account; never sent to the AI. Tested in `tests/test_sealed_envelope.py`. |
| 401(k) Menu Decoder (R5), and decoder pages without an account | 3.2, 8a | Descriptive | L0 + flag; L3 review | Reads as a pick list if sorted by fee; rate-limit per IP. Signed in: built (flag `decoder_401k`, `menu_decoder.py`) |
| The 401(k) decoder without an account: `?decode=401k` before sign-in (decision B12) | 8a | Calculator / Descriptive on the pasted text (kind and fee of each pasted line, in the pasted order; fee in dollars at a monthly amount the visitor types) | L0 + flag `decoder_public`; **on in production only after step 4** (Render behind Cloudflare, so the per-address limit sees real addresses) - step 4 done October 6, 2026 | **Built (step 3); website page W6 published October 6, 2026; on when `decoder_public` is set.** `decoder_public.py`, `views/decoder_public.py`. No AI, no fetching (fund data already kept only; no Fund overlap button), no account row, no settings or counts per person, nothing logged. The only write: a count per hashed address in `signups` (key `decoder:` + SHA-256), 20 an hour per address and 600 an hour app-wide, a calm message when reached, tidied after a day. "Describes, doesn't rank" line beside the table; one line offering an account only after a table is shown; footer "educational, not advice; nothing you paste is saved". Website page W6 links to it. |
| Fact Sheet Decoder (R6, fact sheets only): paste a fund fact sheet's text, see its name, ticker, yearly fee, index or active, asset class, top holdings share, number of holdings, inception date and benchmark in plain words | 3.2 | Descriptive (what the public fact sheet states, each with a general "what this means" line; fee in dollars at a monthly amount the person types) | L0 + flag `decoder_factsheet`; L3 review as for R5 | **Built (step 9), off.** `factsheet_decoder.py`, `views/factsheet_decoder.py`, a card beside the Free money check; signed in only (no `?decode=` version). No AI, no PDF reading (paste only), nothing fetched, nothing saved (not even counts), rows in a fixed order, never rated, ranked or "should"/"best"/"cheap" (tested). **Statements excluded:** text that looks like one (an account number, an account value or balance, a name-and-address block) is stopped before it's read, the box cleared, nothing shown or kept (tested on the page and in the database); statements wait until local redaction is proven (ROADMAP R6). The AI button (AI_PLAN section 9 row 7) is not built: it would need the gateway, counted allowances and the owner's ZDR decision. **For L3:** the "what this means" lines and the index/active wording. |
| Lost & Found (R9): where to look for old 401(k)s, unclaimed property, old HSAs, FSAs and IRAs and savings bonds; an old 401(k)'s common choices; a "places I've looked" list | 3.2 | Education (the same for everyone; official links only). The list: Descriptive, the person's own ticks | L0 + flag `lost_found` (no gate: education) | **Built (step 9), off.** `lost_found.py`, `views/lost_found.py`, under the account map on Account. Links only to `lost_found.OFFICIAL_SITES` (.gov sites, NAUPA's unclaimed.org and the MissingMoney.com it endorses, FINRA BrokerCheck); no deadlines, ages or dollar figures. The rollover choices (leave it, the new plan, an IRA, cash out) are listed "in no particular order" with questions for the plan administrator or a tax professional - "Northwend doesn't suggest one"; no funds named; brokerages only from `brokerages.py` (alphabetical, names and links), and for a managed client a line about their advisor instead. "Searching and claiming through a state's own office is free"; fee-charging finders "you never need". The list (prefs `lost_found`: statuses and a day only) is the login's own, never drawn while an advisor is in a client's account, never in the client record or the AI. **For L3:** the cash-out line's tax wording ("usually counted as income... an extra early-withdrawal tax often applies too, unless an exception fits") and whether the side-by-side choices read as advice. Tested in `tests/test_lost_found.py`. |
| Trail Forks (R8): a route per life event - a new job, a layoff, a new baby, an inheritance, a divorce, the death of a parent: what changes, what to gather, what to ask and whom, what not to rush | 3.2 | Education (the same for everyone; official links only). The forks marked and steps ticked: Descriptive, the person's own ticks | L0 + flag `trail_forks` (no gate: education) | **Built (step 9), off.** `trail_forks.py`, `views/trail_forks.py`, under Lost & Found on Account. Divorce, inheritance and a death stay with what to ask an attorney, a tax preparer, the plan administrator or the estate's executor - never what to do; a loss or a divorce opens softly. No deadlines, ages or dollar figures: where a rule has a timeline the question is "are there any deadlines?". No funds or products named. Links only to `trail_forks.OFFICIAL_SITES` (irs.gov, dol.gov, healthcare.gov, ssa.gov, consumerfinance.gov, usa.gov). Each fork ends in the Walk (Home with the monthly walk open) or, without it, the Plan. Kept (prefs `trail_forks`): fork keys and step keys only - no typed text, no dates; the login's own, never drawn while an advisor is in a client's account, never in the client record or the AI. **For L3:** whether "what not to rush" lines (e.g. cashing out a 401(k), selling inherited investments, moving money out of joint accounts before talking with an attorney) read as advice, and the tax and estate wording in the inheritance, divorce and death routes. Tested in `tests/test_trail_forks.py`. |
| The Inheritance Rehearsal (ROADMAP "Someday"): a practice run at looking after a made-up parent's accounts, start to finish - what accounts exist, whom to call, papers often asked for, beneficiaries and the estate, an inherited IRA as a thing to ask about, what not to rush, Social Security and the final return, taking care of yourself | 3.2 | Education (the same made-up story for everyone; official links only). The steps walked through and the day finished: Descriptive, the person's own | L0 + flag `inheritance_rehearsal` (no gate: education) | **Built (step 9), off.** `inheritance_rehearsal.py`, `views/inheritance_rehearsal.py`, under Trail Forks on Account. A tap-through story about Pat, a made-up parent (a plan at an old employer, a brokerage account, a bank account, a savings bond) - no real firm named. Eight steps, each a situation and two or three taps that are things to find out or ask, never graded; after a tap, "what people often find". No rules, ages, deadlines, time limits or figures stated: the inherited IRA is only something to ask about ("are there any deadlines?"); papers are "often asked for - ask what they need". Links only to `trail_forks.OFFICIAL_SITES`. Ends gently at the person's own account map and, where it's on, Trail Forks' death-of-a-parent route. Kept (prefs `inheritance_rehearsal`): step keys and the day finished - not which choice was tapped, no typed text; the login's own, never drawn while an advisor is in a client's account, never in the client record or the AI. **For L3:** as with R8, the estate and tax wording (beneficiaries vs the estate, payable/transfer on death, letters testamentary, the inherited IRA and inherited investments' tax value) and whether any "people often..." note reads as advice. Tested in `tests/test_inheritance_rehearsal.py`. |
| The Four Seasons (R7): January (this year's contribution limits, last year's IRA window, the fee bill to the goal date), April (tax forms explained), October-November (open enrollment, HSAs), December (Year in review, a letter to future you, an RMD reminder) | 3.2 | Education (the same for everyone; official links only). The fee bill: Calculator (the Fee check's own figures and stated growth) | L0 + flag `seasons` (no gate: education) | **Built (step 9), off.** `seasons.py`, `views/seasons.py`: a card on Home while a season is on ("Not now" puts it away until the next), a line on Learn any time. Links only to `seasons.OFFICIAL_SITES` (irs.gov, ssa.gov, healthcare.gov, medicare.gov). Yearly figures (IRA, 401(k) and HSA limits; RMD age 73) are kept in `seasons.LIMITS` / `RMD_AGE` with their tax year (2026), the IRS page and the day checked; shown only in that tax year, and a test fails once it's past so they're reviewed each January. No deadlines beyond the IRS's own RMD dates; "check with your plan or a tax professional" under every season. The RMD note only for the profile's "65 or older" age range (nothing new asked). No funds named; the decoder only where `decoder_401k` is on. The state (prefs `seasons`: opened / put away per season) is the login's own, never drawn while an advisor is in a client's account, never in the AI. **For L3:** the tax-form and RMD wording. Tested in `tests/test_seasons.py`. |
| Explain It To Someone (R10): a private, expiring, revocable link (`?share=...`) that shows a partner or family member the owner's plan in plain words, opened without signing in | 3.2 | Descriptive (the person's own data, as percentages and words) | L0 + flag `explain_share` (no gate) | **Built (step 9), off.** `explain_share.py`, `views/explain_share.py`, table `share_links`; made on Account by the login's own account only - never an advisor in a client's account, never for an advisor's client (client mode; their links stop working), never an admin (`explain_share.eligible`, checked again at every open). Token `secrets.token_urlsafe(32)` (256 bits), only its SHA-256 kept, the full link shown once; 7 or 30 days (default 7), at most 3 working, "Turn off" deletes it, tidy.py deletes ended ones. The page: asset-class whole percents (own holdings only, never the example), the goal's kind (`plans.GOAL_TYPES` / `advisor.GOAL_OPTIONS`, never its own name) and a timeline bucket, the route stage, the target mix and drift band; the first name only if ticked (letters only, never the login or email). Never amounts, share counts, prices, tickers, fund or account names, institutions. Opening one signs no one in and draws no other page; each browser visit counts once against a per-address limit (30 an hour, 1000 app-wide; `signups` key `share:` + SHA-256, a day) before the link is looked up; unknown, malformed, expired, turned-off and flag-off links show the same "no longer active" page. Owner sees opens and the last day only. No should / best / recommend; "isn't a suggestion for anyone else". **For L3 / privacy review:** whether showing the target mix and band to a third party needs more consent wording than the creation screen's; the Learn button sends a visitor to Create account (invite code while L0's sign-up gate is off). Tested in `tests/test_explain_share.py`. |
| Price "as of" and "Price look wrong?" (PLAN G8) | 8a | Account (when a stored price is from; a person's note that a price looks off) | As of: none (describes prices already shown). Notes: L0 + flag `price_report` (no gate) | **Built.** `price_report.py`. As of: the stored quote time on the market's clock ("3:45 pm ET", "Oct 3 close"), with "may be delayed" beside a ticker's price as before. Notes: four fixed reasons, no free text; a `price_reports` row kept with the account until it's deleted, in the person's export; one per ticker a day, 5 a day per login; admins see counts by ticker and reason only, never who. Thank-you copy promises no fix or time. Tested in `tests/test_price_report.py`. |
| Preparedness drills (R12, the one-week test): ten tap-only situations, a readiness map, a count of weeks rehearsed, the whistle | 3.2 | Education (the same situations and notes for everyone), with Descriptive lines from the person's own data (mix by asset class in whole percents, timeline in words) | L0 + flag `drills`; L3 review | **Built (step 9), off.** `drills.py`, `views/drills.py`, one small card on Home under Your kit (and for someone not investing yet, with no mix). Taps are considerations and questions ("I'd want to know how long my emergency savings would last", "I'd ask my plan administrator..."), never trades; nothing marked right or wrong; after a tap, "things people often think about here" and "there's no right answer on an investment choice". No funds, brokerages, figures or deadlines (tested). One a week, no reminders or emails; the count of weeks only grows. Kept: prefs `drills` (drill keys, the tapped choice's key, ISO week - no free text), the login's own only: never drawn while an advisor is in a client's account, never in the client record or the AI. Metric: a third drill, totals only (`feature_counts.drill_returns`, opt-out respected). **For L3:** that no drill, choice order or note implies a correct investment choice - in particular the notes' "people often..." lines (e.g. the order people reach for money in a surprise expense, the drop drill's "a drop matters most for money that's needed soon") and the stocks/cash share line placed next to a situation. Tested in `tests/test_drills.py`. |
| Trail Conditions (ROADMAP "The weekly rhythm", Phase C): an opt-in Monday email - "Calm on the trail - nothing to do" almost every week | 3.2 | Education (fixed lines, the same for everyone; nothing about the person's money) | L0 + flag `trail_conditions` (no gate) | **Built, off.** `trail_conditions.py` (the job, Mondays 13:00 UTC in `scheduled-sync.yml` with its own failure step), the switch on Account (off by default; the login's own, never an advisor's login or in a client's account; a confirmed email). Lines change only when something changed, from fixed templates: a storm on the person's holdings (`storms.weather`, "Markets have fallen a long way recently" - a past fact, no figure), a season begun (once per season), the walk waiting (once a month), a readiness-map situation not rehearsed (at most every 4 weeks); at most 3 lines. No amounts, percentages, tickers, funds, account names, forecasts, "should / best / recommend" or urgency (tested). Kept in prefs: on/off, the consent time (dropped when turned off), the ISO week sent (never twice a week), what the last lines were about. An advisor's client may turn it on for themselves: their own consent, and nothing in it is about their money or their advisor. **CAN-SPAM:** treated as commercial email to be safe - opt-in only, one-click unsubscribe link with no sign-in (`unsubscribe.py`, kind `trail`) plus a `List-Unsubscribe` header, honoured at once (the switch and the link both stop the next send), a truthful From and subject, and Northwend's postal address in every email: `mailer.POSTAL_ADDRESS` is an empty placeholder, and **nothing is sent while it is empty** (tested). **For review:** whether the storm line ("markets have fallen a long way recently", read from the person's own holdings) needs any more context; the postal address to use (a PO box or registered mailbox is fine under CAN-SPAM). Tested in `tests/test_trail_conditions.py`. |
| Pay yourself (R11): savings pictured as a monthly paycheck - the payouts the person's own holdings are estimated to pay each month plus a rule of thumb they pick; the thinnest month; a hypothetical 20% fall; questions to ask a licensed professional about retirement income | 3.2 | Calculator / Descriptive (arithmetic on the person's own holdings and payouts under a rule they pick); the rules and questions are Education (the same for everyone) | L0 + flag `pay_yourself` + **gate L3** (`flags.FEATURES` needs both). **L3 review required before it's turned on anywhere but staging** | **Built (Phase E), off.** `pay_yourself.py`, `views/pay_yourself.py`, a Plan tab next to Money going out. **The risk:** a monthly paycheck from someone's own savings is retirement-income planning for a specific person - the closest item here to personalized advice (ROADMAP's "Principle risks higher than stated"). **Mitigations built:** (1) the person picks the rule from a fixed, named list - "Only what the investments pay out (income only)", "A fixed 3% / 4% / 5% of today's balance a year" (4% labelled "the '4% rule', a rule of thumb from studies of past markets"); only income only is pre-selected (it only adds up their own payouts), listed income only first then by rate, "Northwend doesn't rank them", nothing says one is better; (2) every figure says "under the rule you picked"; the page opens "Hypothetical, not a forecast, not advice" and "Northwend doesn't pick a rule for anyone, and it doesn't know your taxes, other income or spending"; (3) the 20% fall is a labelled scenario ("one round number picked to illustrate, not a forecast"): a rate rule on the lower balance, and the original study's fixed amount as a share of it; income only says payouts don't move with prices by themselves but can be cut; (4) never "withdraw X", "you can afford", "safe", "sustainable", "should", "best", "recommend", "enough" - a test greps for them and runs every template through `ai_policy.findings` (no hits); (5) "Questions to ask a licensed professional about retirement income" (taxes on withdrawals by account type, the order of accounts, RMDs, Social Security timing, inflation, an early fall, penalties, Medicare / Social Security taxation) - questions only, no answers about their case, the same for everyone; "Not included: taxes, fees, inflation, other income". Kept: prefs `pay_yourself` (the rule key only, never an amount or free text), the login's own. **Who sees it:** the login's own account; an advisor in a client's account sees the same picture on the client's data as an advisor tool, with the standing line ("This is {advisor}'s advice, from {firm} - not Northwend's"), their pick held in the session only (never saved to, nor read from, the client's settings); an advisor's client signed in themselves doesn't get the tab (their retirement income is their advisor's to discuss; Northwend's rules of thumb beside it would second-guess the advisor). Never sent to the AI. **For L3:** whether a named rule applied to the person's own balance (even one they pick) is a conclusion; whether "income only" as the pre-selection is acceptable; the "would come from the balance - selling some investments" line under a rate rule; the 4% rule's description; whether the questions list needs a tax-professional line beside it; whether the managed-client exclusion and the advisor view are right. Overlaps D10 (Retirement income's 3/4/5% figures), which stays as it is. Tested in `tests/test_pay_yourself.py`. |
| Bring to my advisor (ROADMAP Phase C2): a client chooses items that are otherwise only theirs to show their advisor; the advisor's "What <client> chose to bring" card over meeting prep; "This season for your clients" in the advisor's book (R7's advisor side) | 4.3 | Account (the client's own information, client-reported); the season note is Education | Flag `advisor_pack` (an Advisor tool for existing advisor-client links: no gate). The intro version is **not built** - it would sit behind `intros` + L2 | **Built, off.** `advisor_pack.py`, `views/advisor_pack.py`, table `advisor_pack` (a fixed key and the day per ticked item, never free text; SCHEMA_VERSION 10). Only a client signed in as themselves - never an advisor in client mode, never an admin. All off by default. Items: the R10 one-pager's content (no figures), a Trail Fork's name only, the R12 readiness map (rehearsed or not, never a tap), the Storm Drill answer (their own words, its own tick), the R9 places-looked statuses, questions from a fixed list (no free text). **Consent words:** the first share records `consent.grant(scope="advisor_pack", how="pack_choice")` with `advisor_pack.CONSENT` (naming the advisor) verbatim and its SHA-256; unticking the last item, Stop sharing, the relationship ending, an admin's unlink or a deleted account write a revoke. The advisor sees only ticked items, "Shared by <client> on <date>; client-reported", through `advisor_pack.for_advisor` (can_view, their own link, consent in force); each opening is an access-log row (page `advisor_pack`); unticking removes it at once; never sent to the AI. **Record-keeping (for the lawyer):** chosen simplest-safe - the advisor keeps nothing live; after an exit only the dated consent records stay in their client record, and they keep what they need in their own notes. Whether an adviser must retain a copy of client-shared material they reviewed (books and records, as R16) is open; if so, a dated read-only copy store would be added. **L2:** the pack going with an introduction (beside `intros.outline`) is not built; the lawyer sees the consent text either way. Anything the advisor writes to the client from it carries the standing line (`standing_line.py`). Tested in `tests/test_advisor_pack.py` and the principle matrix. |
| Shadow Trail (R14): up to two hypothetical mixes of kinds of funds, each run on past prices from the day it was set, beside the person's own holdings on the same prices | 3.2 | Descriptive (hypothetical performance of mixes the person sets, on past prices; the person's own line is their holdings on past prices) | L0 + flag `shadow_trail` + **gate L3** (`flags.FEATURES` needs both). **L3 review required before it's turned on anywhere but staging** | **Built (Phase F), off.** `shadow_trail.py`, `views/shadow_trail.py`, a Plan tab after Stress test. **The risk:** hypothetical performance shown beside someone's real portfolio invites chasing whichever path did best (ROADMAP R14). **Presentation rules built:** (1) a shadow is a mix of **kinds of funds only** - US stocks, international stocks, bonds, cash, whole 5% steps adding to 100 - never a ticker or a named fund; (2) **the proxy:** each kind is represented by the past prices (adjusted close, from `daily_bars`) of one broad index fund of that kind - the practice portfolio's stand-ins, `learn.PRACTICE_TICKERS` - described on the page only as "a broad US stock index fund", etc., never by name; cash is counted flat (no interest); nothing new is fetched (if the stand-ins' prices aren't on a copy, the page says so and draws nothing); (3) "Hypothetical - a path you didn't take, on past prices. Not a forecast, not advice." at the top and under the chart; percentages only, no dollar amounts; the person's own line is today's holdings on the same prices (money in and out not counted), said so; (4) at most two shadows; each changes at most once every 3 months (the next date shown); removing one is always allowed but doesn't bring that date forward; (5) one small chart and a table: neutral colours (your mix one solid colour, the shadows grey dashes), nothing marks which is higher, the table in a fixed order (your mix's figure beside each shadow, shadows in the order they were made), never sorted by change; (6) no action near it - no "switch", "rebalance to this", "use this mix" or trade link, and the shadow never feeds the target mix, drift, next deposit or the walk; no ranking words ("winning", "beat", "better", "best", "should", "recommend") - a test greps every line and runs it through `ai_policy.findings`. Kept: prefs `shadow_trail` (per shadow: kind keys and whole percentages, the day first set, the day last changed - no free text, no amounts), the login's own. **Who sees it:** the login's own account, an advisor's client signed in themselves included (their own exploration, like the practice portfolio); **never** drawn while an advisor is in a client's account and never read for them (an advisor seeing a client's what-ifs beside the portfolio they built would turn a learning toy into a scorecard of the advice); never in the client record or the AI. **For L3:** whether hypothetical performance of person-chosen mixes beside their real holdings is acceptable at all (SEC Marketing Rule-style hypothetical performance concerns, though Northwend isn't an adviser marketing a strategy); the proxy description; whether the person's own line (today's holdings on past prices) needs more caveats; whether the quarterly lock and two-shadow cap are enough against chasing. Tested in `tests/test_shadow_trail.py`. |
| Teach It Back (R13; AI_PLAN section 9 row 8, the grader): after a Learn basics topic, an optional "Explain it back in your own words" box; the AI says whether it holds | 3.2 | Education (understanding of a concept; never the person's money or choices) | L0 + flag `teach_back` (no gate: education); the grader's prompt and its fixed lines are covered by L3's review of the conclusion policy | **Built (Phase F), off.** `teach_back.py`, `views/teach_back.py`, gateway helper `grader` (cheap tier, the person's chat allowance; a calm "you can come back to this later" when it's used up, resting or the key is missing). Sends only the topic key, its fixed reference text (the same for everyone; figure-free) and the person's words after `teach_back.scrub` (emails, dollar amounts, account numbers, long digit runs, ticker-looking tokens masked). Generous verdict, "That holds" / "Not quite yet", one or two sentences pointing at what the topic says - never a score, grade or praise; the reply passes `ai_policy.check` plus the grader's own no-score check, else a fixed line is shown. A word check (`about_own_money`) adds a fixed line - "This only looks at the idea itself, not at your own money or choices" - when the person writes about their own money. "Try again" any time, no penalty; a topic that held stays held. Kept: prefs `teach_back` (per topic held yes/no and the day) - never the words, not in prefs, the database or a log. Three topics that hold earn the map case (gear); nothing depends on returns. The login's own: never drawn while an advisor is in a client's account. Eval cases in `evals/grader.py` (a portfolio question in disguise, prescriptive and prediction bait, scores), run offline with a fake model. **For L3:** AI grading can be wrong (said under the box); that "not yet" on an investing idea never reads as a verdict on the person's own choices. Tested in `tests/test_teach_back.py`. |
| The Client-Owned Book (R16): the client's walk in the advisor's book, counts-only signals, "client-reported, as of <date>" on the book's figures, a clean exit where the client keeps everything, and the no-custody, no-aggregation model written down for advisors | 4.3 | Advisor tool (the walk signal is Account: the client's own information, shared by their choice) | Flag `client_owned_book` + **gate L2** (`flags.FEATURES` needs both) | **Built, off.** `client_book.py`, `views/client_book.py`; no new table. **Walk signal:** a client's walks are theirs alone (Privacy Policy), so the advisor sees "Walked this month: yes / not yet · Last walk: <month>" only for a client who turns on "Let my advisor see when I've done my monthly walk" on Your advisor - a consent grant (scope `walk_signal`, how `walk_choice`) with `client_book.WALK_CONSENT` verbatim and its SHA-256; off is a revoke, and every end of the link (Stop sharing, End relationship, an admin's unlink, a deleted account) writes one, so a new link starts unshared. Read from `checkin.PREF_LOG` only - never the verdict, a figure or free text. **Counts only:** walked this month (of those who share), holdings brought in within 30 days - over the advisor's own links (`client_book.own_clients`: is_advisor, the advisor agreement, `advisor_clients`), never a list, ranking or sort; another advisor's client is never counted (tested, and in the principle matrix). **Labels:** each card's figures "Client-reported, as of <date>" (the last `snapshots.imported_at`), the book's total "client-reported". **Exit:** the one-step Stop sharing / End relationship is unchanged; the client's step now lists what they keep (everything in their account, and a copy of what the advisor shared in their download) and what the advisor keeps (their notes - archived and private too - proposals, reports, the former-client entry, the consent records); tested end to end. **"How your book works"** on Your clients and in `docs/legal/security-for-advisors-DRAFT.md`. **Questions for L2 (record-keeping):** (1) whether an adviser must retain a dated copy of the client-reported holdings and figures they reviewed after an exit (SEC Rule 204-2, state rules) - today they keep only what they wrote, the former-client entry and the consent records, and "the client keeps everything" means the client's own rows stay with the client; if a copy is required, a dated read-only snapshot owned by the advisor would be added; (2) whether "client-reported, as of <date>" is enough of a label for an adviser relying on client-entered figures; (3) the walk-sharing consent words; (4) whether the walk signal is something the adviser must keep. Privacy wording for when it's on is in the DRAFT policy only (nothing users see changes while it's gated off). Tested in `tests/test_client_book.py` and the principle matrix. |
| Owner metrics in Admin (counts only, CSV) | 8a | Account | L0 (seat figures L1) | |
| Anything toward in-house advice, coaching or an affiliated adviser | 6 (L4) | - | **L4: never** | Refuse and point here |

---

## 7. Conflicts with what's already published

Today's copy says Northwend is free with no plans to charge, and that no one
(including advisors) pays it. When L1 opens, advisors pay a flat seat fee, so
these places must change. **Nothing is changed here.** Under the brief's
standing rule, **never remove a disclosure**: each change below adds the true
statement (advisors pay a flat seat fee, never per client), and keeps every
existing protection (no commissions, no one pays to be mentioned or ranked).

**Must change when L1 opens - they say no one pays, or no plans to charge:**

| Where | Says today |
|---|---|
| `disclosures.py:99` | "Northwend is a free, early (beta) version" |
| `disclosures.py:116-121` ("How Northwend is paid", in the app and the About page) | "free while it's in beta ... If Northwend ever charges for anything, it will say so here first" - no mention of advisor seats |
| `docs/legal/terms-of-use-DRAFT.md:19` | "Northwend is a free website and app" |
| `docs/legal/terms-of-use-DRAFT.md:81-91` (section 5) | "Northwend is free. There are no plans to charge for it." and "It receives no money or other compensation from users, **advisors**, brokerages or fund companies." |
| `docs/legal/terms-of-use-DRAFT.md:200` | Liability cap "for a free service" |
| `docs/legal/privacy-policy-DRAFT.md:120` | "Northwend is free and isn't paid by anyone for what it shows." |
| `docs/legal/security-for-advisors-DRAFT.md:22-23` | "It is a free service run by one developer and isn't paid by anyone for what it shows." |
| `website/templates/advisors.html:89` | FAQ "What does it cost? Northwend is free while it's in beta. If it ever charges for anything, it will say so first" |
| `website/templates/advisors.html:101` | "Free while in beta." |
| `docs/brainstorm-context.md:38-42` | Principle 1 "Free, and paid by no one" - and its reason: it "keeps Northwend clear of investment-adviser registration ... which applies to personalized advice *for compensation*". Once advisors pay, there is compensation. The lawyer should re-check that reasoning; it makes the individual side's "no personalization" rule (L3) carry more weight. |
| `docs/brainstorm-context.md:171-172`, `:195-196` | "completely free and paid by no one"; "free and paid by no one" |
| `ROADMAP.md:1019-1020`, `:1028`, `:1039` (The Ritual) | "no revenue from anyone"; "Nobody pays us to read anything"; "Free, paid by no one" |

**Should change - they say "free while in beta", which implies individuals
might pay later (principle 1: free for individuals, full stop):**

| Where | Says today |
|---|---|
| `dashboard.py:819-821` (Create account; advisors see it too) | "Free while Northwend is in beta. ... We don't sell investments or take commissions." |
| `website/templates/home.html:4`, `:184` | "Free while in beta" |
| `website/templates/new-to-investing.html:134` | "Northwend is free while it's in beta ... If it ever charges for anything, it will say so first." |
| `website/templates/new-to-investing.html:145` | "Free while in beta." |
| `website/public/*` | Built copies of the templates above; rebuild with `python website/build.py` |

**Still true after L1 - keep as they are:**
- `brokerages.py:48`: "Northwend isn't paid by any of them and doesn't rank them."
- `website/templates/home.html:12`, `:151-155`, `website/templates/new-to-investing.html:6`, `views/first_steps.py:317-319`: "nothing to sell you"; "We don't sell investments"; "No one pays to be mentioned".
- `website/templates/new-to-investing.html:93`: "We're not paid by any of them" (brokerages).

**Other places that conflict with L2 (the directory and intro flow):**
- `docs/legal/terms-of-use-DRAFT.md:189-190`: "Northwend is not a party to it and does not refer clients to advisors." A directory with intro requests needs this re-worded by the lawyer (listing is not referring).
- `docs/legal/terms-of-use-DRAFT.md:58-60`: the `[LAWYER]` note asks whether the design keeps Northwend on the "publisher" (impersonal advice) side. B9, B10, B14 and the suggestion buttons are tailored, which is exactly what that question is about.
- `ROADMAP.md:650-652` (M2 "Get matched": "suggests a few advisors who fit"), `ROADMAP.md:668-669` (M6: clients pay advisors through Northwend), `ROADMAP.md:672-673` (M7 reviews), `ROADMAP.md:675-676` ("Want a human? Find an advisor" in Get started, the Plan and Ask Northwend). Each conflicts with brief 4.2 (no matching, no reviews), 4.5 (no money per client) or 3.3 (a calm link, never a prompt). These are plans, not published copy, but they should be struck when the owner approves the brief.
- `advisor.py:118-119` (in every AI prompt): "suggest talking to a licensed professional, such as a fee-only fiduciary adviser" - see section 5.
