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
| **L0** Beta baseline | Terms, Privacy Policy, the "educational, not advice" disclosure, 18+ and US-residency attestation, account deletion and export | `NORTHWEND_GATE_L0` | No open self-serve sign-up. Existing accounts, setup links and admin-made accounts work as today. |
| **L1** Advisor seats and billing | Advisor agreement text, billing copy, the flat-fee-only structure, seat lapse | `NORTHWEND_GATE_L1` (and a separate `NORTHWEND_BILLING` feature flag, as the brief asks for both) | Advisor seats are free beta seats. The agreement is shown marked "beta". No price, checkout or billing screen. No call to the payment provider. |
| **L2** Directory and intro flow | Directory copy, filters, ordering rule, the two-step consent text, the standing "advice is the advisor's" line, state coverage | `NORTHWEND_GATE_L2` | No directory, no "Find a guide" link, no intro requests. Advisors add clients by setup link, as today. The standing line uses interim text. |
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

**Gates and feature flags are different things.** The Ritual items (R1-R5)
each get their own feature flag (brief 3.2). A feature that is also inside a
gate needs both to be on.

**Today's live copy has open sign-up.** With L0 off by default, the next
deploy would close self-serve sign-up unless the secret is set. That matches
the brief (the Terms and Privacy Policy are still drafts - audit 1.10a). It is
an owner decision to make before the flag ships.

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
| A2 | Self-serve sign-up ("I'm 18 or older" box, agreeing to the disclosures) | `dashboard.py:818`, `auth.py:199-222` | Account | L0 | No. No US-residency question yet (L0 needs one). |
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
| A13 | Asking for advisor access (firm and CRD or licence number; the admin checks and approves) | `auth.py:964-991`, `views/admin.py:48`, `mailer.py:225-266` | Advisor tool | L1 | No. No stored evidence, check date or yearly re-check yet (brief 4.1). |
| A14 | Advisor preview: a made-up book while access is checked | `advisor_demo.py`, `views/advisor_demo.py` | Advisor tool | L1 | No |
| A15 | AI allowances and the "used up" messages | `ai_usage.py` | Account | L0 | No |

### 3.2 Learn (the route for someone new) and First steps

| # | Feature | Where | Class | Gate | Prescriptive today? |
|---|---|---|---|---|---|
| B1 | First steps slideshow: welcome, tap questions, goal, bring it in | `views/first_steps.py:285` | Calculator | L0 | No. Its goal screen's "a month - what reaches your goal" (`views/first_steps.py:227`) is arithmetic. |
| B2 | First steps "Your direction" screen | `views/first_steps.py:234` (draws B10) | Descriptive | **L3** | **Yes** - see B10. |
| B3 | The route: two stages, progress, the next waypoint | `views/get_started.py:1031`, `route.py` | Education | L0 | No |
| B4 | About you (the profile questions) | `views/get_started.py:204`, `views/profile.py:49` | Calculator | L0 | No |
| B5 | Are you ready to invest? (readiness check) | `learn.py:51-109`, `views/get_started.py:227` | Descriptive | **L3** (review) | **Borderline.** Not about securities, but it tells this person what to do first, with a red "Start here": "Start with an emergency fund" (`learn.py:65`), "paying it down first is a strong move" (`learn.py:77`), "Putting in enough to get the full match is usually the best return available" (`learn.py:86-87`). General form: "Many people build 3-6 months of savings first." |
| B6 | Set a goal: what, monthly amount, how it's going, **target mix** | `views/get_started.py:319-431` | Calculator | L0; mix part **L3** | **Yes, for the mix part.** The slider starts at the example mix from their answers (`views/get_started.py:418-419`), and "Use the suggestion: X% stocks, Y% bonds - the example mix for your answers" (`views/get_started.py:424-426`) makes it their target in one tap. That target then drives drift, next deposit and the walk verdict. |
| B7 | Learn the basics: six short reads, lesson numbers | `views/get_started.py:436-512`, `learn.py` | Education | L0 | No. The lesson numbers use the person's monthly amount and years (calculator). |
| B8 | "What these kinds of funds look like" (three kinds, three providers each) | `starter_funds.py` | Education | L0 | No - the same for everyone. But see B14 for where it is shown. |
| B9 | An example mix | `views/get_started.py:516-551`, `learn.starter_mix` `learn.py:140` | Descriptive | **L3** | **Yes.** "An example for someone with your answers: 60% stocks, 40% bonds" (`views/get_started.py:524`), then how *their* answers move it. Brief 3.1 says rewrite as common starting points by bucket, the same for everyone in the bucket. |
| B10 | Find your direction (the investor type card and window; the type name on Home's route) | `learn.investor_type` `learn.py:240`, `learn.INVESTOR_TYPES` `learn.py:186-237`, `views/get_started.py:962-1001`, `views/dashboard_page.py:119-125` | Descriptive | **L3** | **Yes.** Names a type for the person, "An example mix for this type", "Kinds of funds that usually fill it". The Foundation type says "Build your base first" and "the example mix below shows what investing could look like for you" (`learn.py:189-195`). |
| B11 | Try it with practice money | `views/get_started.py:554-660`, `learn.simulate` | Calculator | L0; its "Example mix" choice **L3** | **Borderline.** The default mix is their example mix, run on the named stand-in funds. For someone who answered "Sell everything", it adds "Selling during a drop locks in the loss" (`views/get_started.py:650-652`) - a behaviour nudge aimed at them. |
| B12 | Choose a brokerage (what to compare; brokerages alphabetical, unranked) | `brokerages.py`, `views/get_started.py:736` | Education | L0 | No |
| B13 | Open your account (steps and checklist) | `views/get_started.py:750` | Education | L0 | No. "Many people finish a 3-6 month emergency fund first" is shown only to those who answered short on savings - mild. |
| B14 | Your first investments | `views/get_started.py:770-791` | Education | **L3** | **Yes, by placement.** It opens with "Your direction: ... an example mix of X% stocks, Y% bonds, from your answers" (`views/get_started.py:779-782`), then "What your first buy looks like", then the named-fund card (B8). `starter_funds.py`'s own docstring says named funds next to "your mix" would read as a recommendation. |
| B15 | Bring it in (waypoint) | `views/get_started.py:794` | Account | L0 | No |
| B16 | Home before anything is brought in: the route card and waypoint lines | `views/start_home.py:74`, `views/start_home.py:15-29` | Education | L0 | Borderline, through copy only: "What a mix could look like for someone with your answers" (`views/start_home.py:21`). |
| B17 | Learn more links (trusted public sources) | `learn.LEARN_MORE` | Education | L0 | No |

### 3.3 Home (with holdings)

| # | Feature | Where | Class | Gate | Prescriptive today? |
|---|---|---|---|---|---|
| C1 | Your route card: goal progress and the one next step | `route.py:15-75`, `views/dashboard_page.py:30-152` | Calculator | L0; wording **L3** | **Borderline.** The numbers are arithmetic toward their own goal. The words are orders: "Close the gap to your goal ... About $743 (... more) would get you there by <date> at the plan's assumed return - or you could move the date or the target" (`views/dashboard_page.py:53-58`); "You're on track. Keep adding $X a month and your plan gets you there by <date>" (`:76`), a projection not labelled hypothetical. |
| C2 | Storm note ("Weather on the trail") and "What storms have looked like" | `storms.py`, `views/kit.py:243-301` | Descriptive | L0; wording **L3** | **Yes (soft).** "Nothing needs doing today. If your goal is years away, the plan you set still holds" (`views/kit.py:279-281`) is a hold message to this person during a drop. "Holding steady through a storm earns the storm cloak" (`views/kit.py:289`) rewards not selling - a trading behaviour, not learning or a habit (principle 5). The history table itself is general education. |
| C3 | The Monthly Walk (update, drift, one read, verdict; streak; next walk date) | `checkin.py`, `views/checkin.py` | Descriptive | L0 + its feature flag; the verdict **L3** | **Yes (soft, by design).** See section 4. |
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
| D1 | Goal form and goal status, with "Suggested starting point for your answers" lines | `views/plan.py:193-300`, `learn.suggestions` `learn.py:287` | Calculator | L0; the suggestion label **L3** | **Borderline.** The monthly amount is arithmetic. The goal date from age and the 6% return are typical values. The label "Suggested starting point for your answers" says Northwend suggests something for them. |
| D2 | How it's going (the range to the goal) | `views/plan.py:345` | Calculator | L0 | No |
| D3 | Money going out: planned expenses, a regular withdrawal, how long it lasts | `views/plan.py:130-183`, `views/plan.py:467`, `plans.py` | Calculator | L0 | No. "About $Z more a month gets you back on track" and "taking $X less a month or starting N years later makes it last" are arithmetic on their own items, labelled "Arithmetic on the plan's numbers, not advice". R11 (Pay Yourself) would go further. |
| D4 | What if | `views/plan.py:783` | Calculator | L0; its suggestion **L3** | **Borderline.** "Use the suggestion" fills the example mix's % in stocks (`views/plan.py:815-820`). |
| D5 | Contributions (log money added or taken out; Free money check link) | `views/plan.py:587` | Calculator | L0 | No |
| D6 | Money in vs growth | `views/plan.py:656` | Descriptive | L0 | No |
| D7 | Target mix: edit targets and the band | `views/plan.py:685-768` | Calculator | L0; its suggestion **L3** | **Yes, for the suggestion.** "Use the suggestion: 60% stocks, 40% bonds - the example mix for your answers" (`views/plan.py:744-747`) sets their target in one tap. ("Apply a model portfolio" is the advisor's - H5.) |
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
| G1 | Ask Northwend chat (with memory and profile tools) | `advisor.py`, `views/assistant.py` | Education | **L3** | **Yes, in part.** See section 5. |
| G2 | Ready-made questions: quick starts, route and waypoint "Ask Northwend" buttons | `dashboard.py:2054-2069`, `views/dashboard_page.py:9-27`, `views/get_started.py:62-80`, `views/get_started.py:954-959`, `views/start_home.py:30` | Education | **L3** | **Yes.** Northwend writes these questions, and several ask the model for a conclusion about the person that it must then refuse: "Which account type fits me?", "anything I'm too concentrated in", "Review my portfolio", "Looking at my situation, what should I take care of ... and in what order?", "why a mix ... might fit my time horizon", "what's a sensible next step for me", "what that means for someone like me". |
| G3 | Your investing profile window | `views/assistant.py:30`, `views/profile.py:49` | Calculator | L0 | No. Its copy "so Northwend's answers fit your timeline and comfort with ups and downs" (`views/assistant.py:75-78`) promises tailored answers. |
| G4 | Printable plan (PDF) with "Suggested next steps" written by AI | `client_plan.py:35-46`, `client_plan.py:288-311`, `views/profile.py:100-140` | Descriptive (+AI) | **L3** | **Yes.** The model is asked for "3 to 6 concrete, educational steps tied to their goals and risk tolerance", printed as "Suggested next steps" in a document called a plan. Also prints "Things to watch" with the 15% line (C17). |

### 3.8 Advisor side

L1 off means these run as free beta seats, as today. The standing line is L2.

| # | Feature | Where | Class | Gate | Prescriptive today? |
|---|---|---|---|---|---|
| H1 | Your clients: the book, reason chips, search | `views/clients.py:941`, `overview.py` | Advisor tool | L1 | No |
| H2 | Add a client; setup link and invite email | `views/clients.py:655`, `auth.py`, `mailer.py:198` | Advisor tool | L1; consent **L2** | No. Today this is the only way a client joins an advisor. There is no separate, recorded second consent (brief 4.3). |
| H3 | Add clients from a file | `client_csv.py`, `views/clients.py:761` | Advisor tool | L1 | No |
| H4 | Message clients (and the "you have a message" email) | `views/clients.py:853-938`, `mailer.py:268` | Advisor tool | L1; line **L2** | No. The message carries no firm name and no "advice is the advisor's" line (brief 4.4). |
| H5 | Model portfolios (save; apply on a client's Plan) | `views/clients.py:516`, `views/plan.py:729-738` | Advisor tool | L1 | No - the advisor's. |
| H6 | How clients see you (advisor card); Monday email setting | `views/clients.py:465-513` | Advisor tool | L1 | No |
| H7 | This week summary and the Monday email (counts only) | `views/clients.py:1084`, `weekly_email.py`, `mailer.py:186` | Advisor tool | L1 | No |
| H8 | Advisor notes: notes, next steps, reviews, archive and edit history; the client's "Your advisor" page | `views/clients.py:15-188`, `advising.py` | Advisor tool | L1; line **L2** | No |
| H9 | Meeting prep: what changed, AI talking points kept as a private note | `meeting.py`, `views/meeting.py` | Advisor tool | L1 (AI policy L3) | No. Drafts for the advisor only. |
| H10 | Proposals: draft, compare, share; the client accepts or replies; PDF; emails | `proposals.py`, `views/proposals.py`, `mailer.py:158-183` | Advisor tool | L1; line **L2** | No. The PDF says "This proposal is your advisor's recommendation ... Northwend ... does not give investment advice" (`proposals.py:176-178`). The in-app card and the email don't carry that line or the firm. |
| H11 | Progress reports: send, read, PDF, email | `reports.py`, `views/reports.py`, `mailer.py:144` | Advisor tool | L1; line **L2** | No. The PDF footer says "Prepared by your advisor in Northwend" (`reports.py:16`), without the standing line or firm. |
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
| Client plan with AI "Suggested next steps" | `client_plan.py` | Descriptive (+AI) | **L3** | **Yes** (G4) |
| Proposal | `proposals.py` | Advisor tool | L1 | No |
| Progress report | `reports.py` | Advisor tool | L1 | No |
| Year in review, to share | `recap.py:425` | Descriptive | L0 | No |
| Account map | `account_map.py:297` | Descriptive | L0 | No |

### 3.11 Website (northwend.app)

| # | Page | Where | Class | Gate | Prescriptive today? |
|---|---|---|---|---|---|
| W1 | Home | `website/templates/home.html` | Education | L0 | No |
| W2 | New to investing | `website/templates/new-to-investing.html` | Education | L0; two lines **L3** | **Borderline.** "An example mix: What a simple portfolio looks like for someone with your answers" (`:39`). "for each part of your mix, examples from three different providers" (`:119`) ties named funds to "your mix". |
| W3 | For advisors | `website/templates/advisors.html` | Advisor tool | L0; pricing copy **L1**; any directory mention **L2** | No |
| W4 | About (from `disclosures.py`) | `website/build.py` | Education | L0 | No |
| W5 | 404 | `website/templates/404.html` | Education | L0 | No |

### 3.12 Counts

| Class | Features |
|---|---|
| Education | 18 |
| Calculator | 15 |
| Descriptive | 25 |
| Advisor tool | 18 |
| Account | 17 |
| Directory | 0 |
| Billing | 0 |
| **Total** | **93** |

These count the rows in 3.1-3.8 and 3.11, and leave out the email and PDF
tables, which repeat features already counted. Directory and billing are
empty because none of it exists yet (section 6).

Prescriptive today: **Yes** - 11 rows (B2, B6, B9, B10, B14, C2, C3, D7, G1,
G2, G4). **Borderline** - 11 rows (B5, B11, B16, C1, C5, C14, C17, D1, D4,
D10, W2), and C7 is worth a glance.

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
| Eval: 60+ cases, 15 on prescriptive phrasing, fail the build | `scripts/ai_guardrail_eval.py` exists, run by hand | Grow it and run it in CI (AI plan) |

Also outside 5.3 but close: the model sees tickers and weights
(`advisor.py:6-8`, `portfolio_summary`). Brief 5.1 says models never see
individual holdings. That belongs to the AI plan's `ContextCard` work.

**Client mode (brief 5.2).** For an advisor's client, the ready-made
questions already point back to the advisor (`views/start_home.py:158-176`).
The chat itself has no client-mode rule yet.

---

## 6. Features in the brief that don't exist yet

| Feature | Brief | Class | Gate | Notes |
|---|---|---|---|---|
| US-residency attestation; 18+ as its own field | 6 (L0) | Account | L0 | Today 18+ is part of the agreement (audit 1.10c) |
| Published Terms and Privacy Policy | 6 (L0) | Account | L0 | Drafts in `docs/legal/` |
| Advisor agreement and attestation at seat activation | 4.1 | Advisor tool | L1 | Marked "beta" while L1 is off |
| Licence evidence, check date, yearly re-check job | 4.1 | Advisor tool | L1 | Today a manual check, nothing stored but the number |
| Seat billing: hosted checkout and portal, signed webhooks, seat status, founding seats, lapse grace period, daily reconciliation | 4.5, 7, 8a | Billing | L1 + `NORTHWEND_BILLING` | Not on Streamlit Community Cloud (brief 7) |
| Pricing copy (website and app) | 4.5 | Billing | L1 | One flat price; a test that billing never reads client or intro counts |
| The directory: profiles, filters, alphabetical only, no ranking (tested) | 4.2 | Directory | L2 | |
| "Find a guide" page and its one calm link | 3.3 | Directory | L2 | No analytics on who browsed |
| Intro request (figure-free view and a message); advisor's text reply or scheduling link | 4.3.1-2 | Directory | L2 | |
| Second, separate consent to full sharing; consent records (append-only, exact text, time, advisor) | 4.3.3, 7 | Directory | L2 | Kept the lawyer's period; default 7 years |
| Revoke sharing ends access within one request | 4.3.4 | Advisor tool | L2 | Stop sharing exists (H13); needs the one-request test |
| Advisor access log, visible to the client (append-only) | 4.3.5 | Advisor tool | L2 | |
| The standing "advice is the advisor's, not Northwend's" line, with name and firm, on every advisor artefact | 4.4 | Advisor tool | L2 | Today only on the proposal PDF |
| State-coverage handling | 6 (L2) | Directory | L2 | |
| Common starting points (the example-mix rewrite) | 3.1 | Education | L3 | Replaces B9, B10's mix, the suggestion buttons |
| Conclusion policy, `ContextCard`, figures opt-in, 60+ case eval in CI | 5 | Education | L3 | |
| Do-Nothing Ledger (R2) | 3.2 | Descriptive | L0 + flag; L3 review | Must show both directions (ROADMAP risk list) |
| Expedition Log (R3) | 3.2 | Descriptive | L0 + flag | |
| Storm Drill / Storm Shelter (R4) | 3.2 | Descriptive | L0 + flag | |
| 401(k) Menu Decoder (R5), and decoder pages without an account | 3.2, 8a | Descriptive | L0 + flag; L3 review | Reads as a pick list if sorted by fee; rate-limit per IP |
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
- `docs/legal/terms-of-use-DRAFT.md:161-162`: "Northwend is not a party to it and does not refer clients to advisors." A directory with intro requests needs this re-worded by the lawyer (listing is not referring).
- `docs/legal/terms-of-use-DRAFT.md:58-60`: the `[LAWYER]` note asks whether the design keeps Northwend on the "publisher" (impersonal advice) side. B9, B10, B14 and the suggestion buttons are tailored, which is exactly what that question is about.
- `ROADMAP.md:650-652` (M2 "Get matched": "suggests a few advisors who fit"), `ROADMAP.md:668-669` (M6: clients pay advisors through Northwend), `ROADMAP.md:672-673` (M7 reviews), `ROADMAP.md:675-676` ("Want a human? Find an advisor" in Get started, the Plan and Ask Northwend). Each conflicts with brief 4.2 (no matching, no reviews), 4.5 (no money per client) or 3.3 (a calm link, never a prompt). These are plans, not published copy, but they should be struck when the owner approves the brief.
- `advisor.py:118-119` (in every AI prompt): "suggest talking to a licensed professional, such as a fee-only fiduciary adviser" - see section 5.
