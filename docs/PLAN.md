# Northwend plan

The owner's master brief (Oct 5) sets the direction: Northwend becomes
two-sided. Individuals get free education. Advisors pay a flat seat fee for
tools and an equal directory listing. This plan is the brief's build order
(§8, steps 1-9) fitted to the code on staging at `11fd189`.

It replaces the Oct 5 hardening plan. That plan's Phase 0, 1 and 2 detail is
kept, inside steps 1 and 4. It sits beside `ROADMAP.md` and doesn't replace
it.

Companion documents:
- `docs/SECURITY_AUDIT.md` - what the code does today, item by item.
- `docs/LEGAL_GATES.md` - every feature, its classification and its gate.
- `docs/COPY_AUDIT.md` - "for you", "recommend", "should" and the rest, with
  rewrites.
- `docs/AI_PLAN.md` and `docs/AI_COSTS.md` - steps 2 and 7, and every AI
  decision.

Sizes, as in ROADMAP: S = an hour or two, M = a session, L = several
sessions. Durations assume one owner working part-time with AI sessions:
about 6-8 sessions make a week.

---

## First, why the legal order matters (not legal advice)

Until now Northwend took no money from anyone. That was the main thing
keeping it clear of investment-adviser registration: the definition covers
someone who advises others about securities "for compensation". Seat fees
are compensation to the business.

So the defence now rests on the other half. The individual side has to be
impersonal education and arithmetic on a person's own numbers, never advice
about what that person should do. That's why **L0 (beta baseline) and L3
(conclusion policy) come before L1 (seats and billing) and L2 (directory)**.

It's also the securities attorney's first question: does the individual
side, as built, stay impersonal? Bring them `LEGAL_GATES.md`,
`COPY_AUDIT.md` and the eval results from `AI_PLAN.md`. A second question
belongs with L2: whether a flat listing fee from advisors raises solicitor
or promoter issues under the Marketing Rule and state rules.

This plan encodes the owner's intended position. It is not legal advice.

---

## The short version

- A lot of the brief is built already, on staging and not yet on `main`:
  the Monthly Walk, the calculators, and most of the advisor workspace,
  including client-initiated exit. What's missing is mostly the new legal
  surface: flags and gates, consent records, access logs, the directory,
  seats and billing.
- There are no feature flags today. The old plan dropped them. The brief
  needs them, so step 1 adds the smallest version (`flags.py`).
- Billing has one real engineering problem: Streamlit can't receive a
  webhook. The recommendation is to poll the provider instead, with no
  inbound endpoint at all (step 6).
- The brief's Phase 1 tools (a package re-layout, Alembic,
  pydantic-settings) are still recommended against. That's now an explicit
  owner decision (B9).
- **Total to "directory and billing ready to switch on": about 12-16 weeks
  of part-time work (roughly 3-4 months).** Going live also waits on the
  lawyer (L1, L2), a business entity and insurance. Start those in week 1:
  they take weeks of calendar time but little of the owner's.

## How it fits beside ROADMAP.md

- **Working rules stay the same.** Staging first, "Commit and push?",
  "Release to main?", and a plan first before touching CSV import or price
  fetching.
- **Security fixes travel like bug fixes.** They go to `main` once Tests is
  green on staging.
- **The brief's order replaces "Next two weeks".** The Walk (item 1) is
  built. The Storm Drill (item 2) and the 401(k) decoder (item 3) are in
  step 3. Decision B11 asks whether R5 may start early, because open
  enrolment ends soon.
- **The "Find an advisor" section (M0-M7) is superseded.** M0 is the legal
  gates. M1 and M3 become step 5. M2 "Get matched", M6 (clients paying
  advisors through Northwend) and M7 reviews are out: the brief forbids
  matching, money from individuals, and ratings. M4 shrinks to text replies.
  M5 becomes a link to the advisor's own scheduling tool.
- **The Ritual's Tier 3:** R15 "People With Your Answers" is dropped (the
  brief's 3.1 "common starting points" covers the need without other
  people's data). R16 "Client-Owned Book" is mostly step 5.
- When the owner approves this plan, add a short **"B. Build order"**
  section to ROADMAP (steps 1-9, one line each, pointing here). Tick items
  there, as usual.

---

## What's already built (staging, `11fd189`)

Eleven commits are on staging and not on `main` (main is at `b8de459`).
All tests pass on both. Decision B10 is whether to release them.

| Built | Where | Brief | What it still needs |
|---|---|---|---|
| The Monthly Walk v1: four steps, the rule-based verdict, walk count, next walk's day | `checkin.py`, `views/checkin.py` | §3.2 item 1 | A flag (none today). An unsubscribe link and `List-Unsubscribe` header on its reminder (`checkin_email.py` has neither; audit 1.7c). The verdict's "one next step by asset class" reviewed under L3 (see `LEGAL_GATES.md`) |
| Feature counts: R1's second-walk rate, groups of 20+, opt-out, privacy text first | `feature_counts.py`, Admin > Feature tests | §8a first metric | Fold into the owner metrics panel with CSV export (step 6) |
| Notes to future you | `future_notes.py`, `views/future_notes.py` | §3 inventory; feeds R3/R4 | Nothing for the brief. R3 and R4 build on it |
| Year in review, with a figure-free share card | `recap.py`, `views/year_review.py` | §3; R7's December | The share card is a good start for the intro's figure-free view (step 5) |
| Account map (the binder) | `account_map.py`, `views/account_map.py` | §3; R9 later | Nothing now. Its "find old accounts" half becomes R9 (step 9) |
| Money going out | `plans.py` (money_out) | §3.1 calculator | Classification only |
| Stress test | `stress.py`, `views/stress_test.py` | §3.1 calculator | The Storm Drill field doesn't exist. The storm note does (`storms.py`, Home) but shows no drill answer |
| Where your next deposit could go | `next_deposit.py` | §3.1 (stays, "the target is theirs") | Copy saying plainly that the target is the person's own (`COPY_AUDIT.md`) |
| Cash check, Free money check (employer match) | `cash_check.py`, `employer_match.py` | §3.1 calculators | Classification only |
| Example mix "for your answers" | `learn.suggestions`, `views/plan.py:193`, `views/get_started.py:524`, `views/start_home.py:21` | §3.1 rewrite | The rewrite to "common starting points" by bucket, behind L3 (step 2) |
| Add clients from a CSV, with invites | `client_csv.py` | §4.4 bulk import | A consent step at the client's setup link (step 5) |
| Demo book while approval is pending | `advisor_demo.py`, `views/advisor_demo.py` | §4.4 | Nothing. It's synthetic, in memory, labelled "Example" |
| Ending a relationship, both sides | `advising.end_relationship`, `former_clients`; the client's "Stop sharing with my advisor" (`views/clients.py:348-388`) | §2.7 clean exit | Already client-initiated: one expander, a confirm box and a button. Needs a consent-record entry on revoke, and an access-log line. "One step" is met if the confirm box counts as part of the step (L2) |
| Proposals, reports, meeting prep, message all clients, model portfolios, weekly counts email | `proposals.py`, `reports.py`, `meeting.py`, `weekly_email.py` | §4.4 | The standing line on every advisor artefact a client sees: the advisor's name and firm, and "the advice is the advisor's, not Northwend's". Not there today |
| Notes archived, edits keep history; client record export | `advising.archive_note`, `export.client_record_zip` | §4.4 | Nothing |
| Two-step sign-in, required for advisors and admins | `two_step.py`, `views/two_step.py` | §4.1 | An AppTest that the gate can't be skipped (Phase 0) |
| Advisor request with firm and CRD; admin approval with a BrokerCheck link | `auth.request_advisor`, `admin.approve_advisor` | §4.1 licence check | Evidence and date stored; a yearly re-check job (D15) |
| Monthly AI allowances, counted atomically | `ai_usage.py` | §5.4 | The rest is in `AI_PLAN.md` |
| Export everything; self-delete | `export.py`, `admin.delete_account` | L0 | A former advisor's records kept on delete (D7) |
| 18+ box at sign-up, stored with the terms version | `auth.sign_up` | L0 | US residency, and both as their own timestamped fields (D10) |
| Render move coded | `render.yaml`, `hosting.py` | Step 4 | The owner's steps |

---

## Flags and gates (the smallest version)

The brief wants every new feature behind a flag, and every gate as a config
flag that defaults to off. Today there are none. The old plan said staging
could ship things dark. That stopped being true: staging is fast-forwarded
to `main`, so anything on staging goes live at the next release.

**`flags.py` (M, step 1):**
- Reads two settings through `settings.py`: `NORTHWEND_GATES` (for example
  `L0`) and `NORTHWEND_FLAGS` (for example `walk,ledger`). Environment
  first, then Streamlit secrets. Missing means off.
- One table, `FEATURES`: each feature's name, the gates it needs, and the
  view it owns (if any). Example: `"directory": {"gates": ("L2",), "view":
  "directory"}`.
- `flags.on("ledger")` is true only when the feature's flag is on and all
  its gates are on.
- `_view(name)` in `dashboard.py` checks `FEATURES` before it runs a view.
  A whole view can't forget its flag. A gated page also leaves `PAGES`, so
  it isn't in the menu.
- A feature inside an existing view (the Storm Drill field on the Stress
  test, the Walk card on Home) calls `flags.on(...)` where it's drawn.
- Admin > System lists which gates and flags are on. They aren't secrets.
- Staging turns everything on. Production turns on what's been approved.

**Tests:**
- With no settings, every gate and flag is off.
- Every view named in `FEATURES` is skipped by `_view` and missing from
  `PAGES` when its flag is off (AppTest).
- Every name in `FEATURES` appears in at least one `flags.on("...")` call or
  owns a view. No flag that nothing checks.
- Every feature `LEGAL_GATES.md` puts behind a gate lists that gate in
  `FEATURES`. The test reads the document's table.

**What "off" means for something already live.** A gate that's off can't
switch off features people use today. For each existing feature,
`LEGAL_GATES.md` says what shows with its gate off. Example: with L0 off,
sign-up needs an invite code (B7), but the rest of the app works.

Per-account flags (beta testers) aren't needed yet. Add them later as one
settings key, if wanted.

---

## Step 1 - Hardening Phase 0 and Phase 1 (about 3 weeks, 20-23 sessions)

The brief's Phase 1 list is "layout, tests, CI, migrations, config, docs".
Each is covered below. The tools are lighter than the brief's (B9).

### 1a. Phase 0 - close the open P0 and P1 items (about 1.5 weeks, 10-12 sessions)

No architecture change. Each fix gets a test. Already done and dropped: CSV
export escaping, SQL parameterisation, hashed single-use tokens with
expiry, deletion in `finally`, the "no figures in email" templates, and the
secrets check of the full history (audit 1.5a).

1. **`flags.py` (M, new).** First, because everything after it uses it.
   See above.
2. **Secret scanning (owner, 2 minutes).** Turn on GitHub secret scanning
   and push protection.
3. **Fail closed on configuration (M, P1, audit 1.5b).** A small
   standard-library `settings.py`. It knows when it's hosted (`RENDER`,
   `/mount/src`, or `NORTHWEND_ENV`). When hosted, it refuses to start
   without a Postgres `PORTFOLIO_DB`. It decides about the "path on this
   machine" box, error details and alerts, which today key on "is the
   database Postgres". Move the scattered `os.environ` reads into it, one at
   a time. A test checks that a hosted copy with no DSN stops with a clear
   message.
4. **Size limits (S, P2, 1.3b).** `server.maxUploadSize` 10 MB. A row cap
   in `csv_import.read_rows` (5,000), a length cap on pasted text,
   `max_chars` on the chat box. Screenshot types checked by their first
   bytes. Reset the CSV uploader after a read.
5. **Sign-in limits (M, P1, 1.1c).** A per-address limit on wrong
   passwords, in `login_failures` with an `addr:` key and the hashed
   address. Hash against a dummy salt for an unknown username.
6. **AI ceiling, first slice (M, P1, 1.4c, G5).** The owner sets a spend
   limit in the Anthropic console, with a separate staging workspace. Then
   an app-wide monthly count with a calm "resting" message, and alerts at
   50% and 80%. The full gateway is step 2; the numbers are in
   `AI_PLAN.md` and `AI_COSTS.md`.
7. **Make the privacy wording true (S-M, P1, X3, 1.3d).**
   - "Never balances" in `TRUST_LINE`/`NOT_KEPT` says what's really kept.
   - The screenshot AI path goes behind a flag, off in production (D1, as
     updated for brief §5.1).
   - The chat memory instruction stops keeping dollar amounts (D9).
   - `disclosures.py` and the drafts match; rebuild the website.
8. **The Walk's reminder email (S-M, P2, 1.7c).** A one-click unsubscribe
   link and a `List-Unsubscribe` header, before the Walk is released. The
   advisors' Monday email gets the same.
9. **L0 sign-up basics (M).**
   - "I live in the United States" beside the 18+ box. Both stored as their
     own timestamped fields next to `terms_version` (D10).
   - Invite codes while L0 is off (B7): a short code table, used once,
     made by the admin. Advisors' setup links already count as invites.
10. **Principle tests (M, about 2 sessions).**
    - Every `mailer` function rendered with sample inputs: no currency or
      digit groups (1.7b).
    - An advisor without `two_step_ok` sees only the code page (1.1e).
    - `?client=<not yours>` falls back to your own account (1.2a).
    - The matrix: user A can't read, change or delete user B's rows in
      every table in `admin.ACCOUNT_TABLES`. New tables from steps 5-6 join
      it as they're made.
    - `advisor_id` required in the `advising` note helpers.
    - The "AI never sees figures" test extended to a fund name carrying a
      dollar figure.
11. **Owner tasks (S each).** Delete the old Neon backup branch (X6).
    Check DMARC (`dig TXT _dmarc.northwend.app`); add `p=quarantine` if
    missing (1.7a).
12. **Friendly save errors (S, X4).** The three `"... nothing was changed:
    {exc}"` messages become the calm message with an error code.
13. **First ADRs (S).** `docs/adr/`: screenshots (D1), flags and gates,
    and the B9 answer. One page each.

**Done when:** no P0 is open; every P1 above is closed or has a recorded
decision; `flags.py` and its tests are in; the new tests pass on SQLite and
Postgres; staging shows the new wording.

### 1b. Phase 1 - foundations (about 1.5 weeks, 10-11 sessions)

Most of the brief's goal is met already. Calculations are pure modules with
tests. Views are separate files. CLAUDE.md maps the code.

1. **RUNBOOK.md (M, G6, 1.10e).** One page each: deploy (staging, then
   main, on Render); roll back; restore (Neon to a branch, count rows,
   swap); rotate each key (Anthropic, Resend, Finnhub, Neon, GitHub, and
   later the billing keys); sign everyone out; turn off AI or email in an
   emergency; shut down cleanly (notice, export window, delete); who to tell
   after a breach, and what to say. **New from the brief:** an
   "owner prerequisites" page (business entity, insurance, the lawyer's
   sign-off per gate, with dates) and a checklist that a deploy turning on
   a gate must tick first.
2. **"Sign out everyone" (M, X5).** A session generation number checked on
   every run. `manage_users.py sign-out-all` bumps it.
3. **Admin action log (M, X2).** Append-only: who, what, which account,
   when. Never holdings. Shown on Admin > System, kept 1 year. The same
   append-only pattern is reused for consent records and access logs in
   step 5.
4. **CI additions (S, G3, 1.8e).** `ruff check` (small rule set),
   `pip-audit`, Dependabot weekly and grouped, Actions pinned by SHA, and a
   coverage number printed on each run (ratchet up, never down). A test
   that fails on a live billing key prefix (`sk_live_`, `rk_live_`,
   1.11a).
5. **Layer rule as a test (S, new; the cheap answer to "layout").**
   Calculation modules (`perf`, `plans`, `income`, `fees`, `stress`,
   `next_deposit`, `checkin`, ...) import neither Streamlit nor the
   database. SQL in `views/` is listed in an allowlist that may only
   shrink. This gives the brief's rule ("no business logic or SQL in
   pages") without moving files.
6. **A schema version and a migrate command (M, 1.6d).** A
   `schema_version` table and `northwend-migrate`, which runs
   `portfolio._ensure_schema` on purpose. The app still runs it at start
   until step 4 splits the database roles.
7. **Password hashing (S, 1.1b).** PBKDF2 at 600,000 iterations, the count
   stored per user, old hashes upgraded at next sign-in.
8. **TOTP secrets encrypted (S, 1.1e) - only if D14 says yes.** Backup-code
   hashes move to PBKDF2 either way.
9. **Retention, written and applied (M, 1.10d).** D5's table in
   `disclosures.py` and the Privacy draft. A nightly `northwend-tidy` step
   with its own "Tell the admin it failed" step.
10. **`.env.example` with every variable named (S).** Names and one-line
    meanings, no values.
11. **ARCHITECTURE.md (S, G10).** One page: a run of `dashboard.py` top to
    bottom, the data model in ten lines, where jobs run, what the AI is
    sent, where flags are checked. It points to CLAUDE.md for the file map.
12. **Staging seed (S).** `manage_users.py seed-staging`: a made-up
    household, an advisor and three clients from `sample_data.py`.
13. **More broker files (M, G1) - can slip without harm.** Made-up exports
    for Ally, Interactive Brokers, M1, Merrill, Public, SoFi and Webull. A
    plan first, since it touches `csv_import.py`.

**Done when:** the runbook covers every page above; CI runs lint, audit and
the layer test; `northwend-migrate` exists; the retention job runs nightly
on staging.

**If the owner chooses the brief's tools instead (B9):** the
`core/data/services/ui` re-layout adds 2-3 weeks (nearly every file moves,
the `_view` design breaks, every import in about 780 tests changes).
Alembic adds about 1 week (a baseline for two SQL dialects, plus learning
it). pydantic-settings adds 1-2 sessions and a dependency.

---

## Step 2 - AI foundations and the example-mix rewrite (2-3 weeks; `AI_PLAN.md`'s figure replaces this)

What it holds for this codebase, in brief. `AI_PLAN.md` has the items,
sizes and durations.

- A typed `ContextCard` replacing `advisor.portfolio_summary`.
- One gateway for every model call. Today they're spread over `advisor.py`,
  `meeting.py`, `client_plan.py`, `csv_import.py`, `txn_import.py` and
  `screenshot_read.py`, all pinned by `tests/test_legal_guardrails.py`. This
  was Phase 3 item 2 of the old plan; it moves here.
- Allowances, the ceiling and cost logging, built on step 1's first slice.
  The cost log is what feeds "AI cost per active user and per seat" in step
  6's owner metrics.
- The eval set (60+ cases, 15 on prescriptive phrasing), growing from
  `scripts/ai_guardrail_eval.py`. It's the evidence for L3.
- Ask Northwend moved onto the gateway.

**The example-mix rewrite (M, about 2 sessions, not AI).** "For someone
with your answers" becomes "common starting points" for a timeline and
comfort bucket, the same for everyone in the bucket, labelled as
illustrations. The places: `learn.suggestions`, `views/plan.py:193`
(`SUGGEST_LEAD`), `views/get_started.py:425` and `:524`,
`views/start_home.py:21`, `starter_funds.py`. Rewrites are in
`COPY_AUDIT.md`. Behind gate L3 and flag `general_mixes`. Since the rewrite
removes risk rather than adding it, the owner may want it on in production
before L3 signs off; `LEGAL_GATES.md` says what L3-off shows.

**Gate:** L3. **Done when:** see `AI_PLAN.md`; plus the example-mix rewrite
on staging, with a test that no "for your answers" or "for you" wording
remains in the example-mix paths.

---

## Step 3 - Individual side: the Ritual's Tier 1 (about 2-2.5 weeks, 12-14 sessions)

Each item behind its own flag. All on the person's own numbers, in
percentages and asset classes.

1. **The Monthly Walk (S; built).** Behind flag `walk`. The unsubscribe
   work is in step 1. The verdict copy is checked against brief §5.3: the
   person's own rule speaking, never a fund, never selling. Flag, test,
   done.
2. **The Do-Nothing Ledger, R2 (M, 2-3 sessions).** New. An entry for each
   walk with no change beyond the plan, from `checkin.PREF_VERDICTS` and
   `changes.py`. During a drop: what selling on a date would have meant,
   on the person's own mix by asset class, using `stress.py`'s price maths
   and `daily_bars`. Both directions, always labelled hypothetical, never
   "the right call". Flag `ledger`. **Done when:** a test shows the "would
   have helped" side appears when it's true.
3. **The Expedition Log, R3 (S-M, 1-2 sessions).** New. One line per walk:
   drift, deposits by asset class, the market's move, "no changes", and any
   note from Notes to future you. Percentages only. If it gets its own
   table, it joins `admin.ACCOUNT_TABLES` and `export.OWN`. Never shown to
   an advisor, never sent to the AI unless the person asks. Flag `log`.
4. **Storm Drill and Storm Shelter, R4 (M, 2 sessions).** New. One field
   after the 2008 run in `views/stress_test.py`: "What will you do when
   this happens?", saved (a kind of note in `future_notes`). When the storm
   note fires (`storms.weather`), Home shows the person's own answer, their
   ledger and their log, with no trade button. The R4 metric uses
   `feature_counts.py` rules (totals, groups of 20+, opt-out). Flag
   `storm_drill`.
5. **The 401(k) Menu Decoder, signed in, R5 (M, 3 sessions).** New.
   A pure `decoder.py`: paste a fund list; match against `security_info`
   (and `ticker_search` for names); kind from `asset_classes`; fee % with
   its source and date (`sync_history._expense_ratio`); fee in dollars at a
   monthly amount the person types, labelled hypothetical. Sorted by kind,
   then name, never by fee. Honest "couldn't identify" rows. No AI. Flag
   `decoder_401k`. A test checks the order and that no row says "best",
   "cheapest" or "recommended".
6. **The decoder without an account (§8a) (M-L, about 3 sessions).** Built
   here behind flag `public_decoder` and gate L0. **Switched on only after
   step 4**, because it needs Cloudflare and the real visitor address.
   - **How.** A route before sign-in in `dashboard.py`, where `?confirm=`
     and `?reset=` are handled today (above `_login()` at
     `dashboard.py:1207`). `?decode=401k` draws the decoder and stops. No
     login, no account row.
   - **No retention.** The pasted list lives only in the Streamlit session
     (server memory) and is never written or logged. Matching reads only
     the shared fund data already cached. It never fetches from Yahoo or
     Finnhub for a visitor. No AI on this path, ever.
   - **Rate limit.** Per address, using `hosting.client_ip` (with
     `CLIENT_IP_HEADER=cf-connecting-ip` behind Cloudflare), hashed, in the
     same per-address counters sign-up uses (kept 1 day). For example 10
     decodes per address per hour, plus an app-wide hourly cap. The hashed
     counter is the only thing stored.
   - **After the result:** "Create a free account to keep this", which opens
     `?signup=1`. The list carries over only inside the same session.
   - **Findable.** Streamlit pages are drawn by script, so search engines
     see little. The website gets a static, indexable "/401k-menu" page
     that explains the idea and links to the route.
   - **Risks.** It's the app's first feature with no sign-in. Each visit
     holds a Streamlit session in server memory, so a burst could exhaust a
     Render Starter instance; Cloudflare's rate limit on page loads is a
     coarse guard, and the app's cap is the real one. Someone could use it
     as a free fund-data lookup; the cap and "cached data only" limit that.
     Pasted menus may include balances; strip `$` amounts and digit groups
     on read and keep only names. Errors have no user, so `friendly_errors`
     must cope with that.

**Gate:** none for 1-5 beyond their flags (classification in
`LEGAL_GATES.md`); L0 for 6. **Done when:** each item is on staging behind
its flag with tests green, and the owner has turned on in production the
ones they've approved.

---

## Step 4 - Own the hosting: Hardening Phase 2 (about 1 week, mostly owner steps)

**Nothing in steps 5 and 6 is switched on in production before this step
is done.** Money and consent records don't go on Streamlit Community Cloud.
The owner steps take little code time, so start them during step 1. Then
step 4 is finished by the time step 3 is.

1. **Finish L4 (owner, M).** The Render Blueprint, checked on its
   `onrender.com` address, then `go.northwend.app`. Add to `render.yaml`:
   `NORTHWEND_ADMINS`, `ALERT_EMAIL`, `APP_URL`, `NORTHWEND_ENV`,
   `NORTHWEND_GATES`, `NORTHWEND_FLAGS`,
   `STREAMLIT_SERVER_MAX_UPLOAD_SIZE=10`,
   `STREAMLIT_CLIENT_SHOW_ERROR_DETAILS=none`,
   `STREAMLIT_BROWSER_GATHER_USAGE_STATS=false`.
2. **Cloudflare in front of the app (owner + S, 1.8b).** Proxy on for
   `go.northwend.app` (websockets work). A response-header rule: HSTS,
   `nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`,
   `frame-ancestors 'none'` plus `X-Frame-Options: DENY`, and a
   `Permissions-Policy` denying camera, microphone and geolocation. Then
   `CLIENT_IP_HEADER=cf-connecting-ip`. Aim for an "A" on
   securityheaders.com, not "A+" (Streamlit can't take a full CSP).
3. **Backups and a tested restore (M, 1.6e).** Per D6. A restore drill in
   RUNBOOK.md, run once now and every quarter.
4. **Uptime check (S, G4).** A free outside monitor on `/_stcore/health`
   and the website.
5. **Separate keys per copy (S, 1.5c).** Staging: its own Anthropic
   workspace, `MAIL_DRY_RUN=1` or a test-only Resend key, and test-mode
   billing keys only (1.11a). Production keys only in Render and in GitHub
   for the jobs.
6. **Least-privilege database roles (M, 1.6c).** An owner role for
   `northwend-migrate` only; an app role with row access and no DDL; a
   jobs role. The app role gets `INSERT, SELECT` only on the consent and
   access-log tables when they arrive (1.6f). Then schema setup leaves the
   app's start.
7. **Update the wording (S, 1.10a).** Render instead of Streamlit
   Community Cloud in `disclosures.py` and the drafts; Cloudflare added to
   "Services Northwend uses".
8. **Retire Community Cloud (owner, S).** `MOVED_TO` on the old app; delete
   it a month later.
9. **Scheduler: keep GitHub Actions.** It alerts on failure and costs
   nothing. The billing reconciliation job (step 6) runs there too.

**Dropped:** a Dockerfile (Render builds from `requirements.txt`).

**Done when:** the app is served at `go.northwend.app` from Render behind
Cloudflare with the headers above; a restore drill has passed; the uptime
check is live; Community Cloud shows "has moved"; the disclosures name the
real hosts.

---

## Step 5 - Advisor side (about 3-4 weeks, 20-24 sessions)

Behind L1 (the agreement) and L2 (directory, intros, consent, the standing
line). Until L1 is on, every seat is a free beta seat and the agreement is
marked "beta".

1. **Advisor agreement and attestation (M, 2 sessions).** New. At seat
   activation the advisor accepts the agreement (text from the lawyer under
   L1). Stored like the terms: version, a hash of the exact text, time.
   Shown again when the version changes. Flag `advisor_agreement`, gate L1
   (the beta text shows while L1 is off).
2. **Licence evidence and the yearly re-check (S-M, 1-2 sessions, D15).**
   At approval the admin records the CRD match, the source (BrokerCheck or
   IAPD) and the date. A yearly job emails the admin how many are due. An
   advisor not re-checked within 13 months leaves the directory until
   re-checked.
3. **Directory profile (M, 2 sessions).** New `advisor_profiles` table:
   name, firm, registration type and number as entered (with the public
   regulator link), credentials, fee model as the advisor states it,
   minimums, who they serve, states served, virtual or in person, a short
   description, a scheduling link. Edited by the advisor; shown only once
   approved and the licence is current.
4. **"Find a guide": browse with filters (M, 2 sessions).** Filters per
   B4. Order: alphabetical within the filters, and nothing else. No
   featured slots, ratings, reviews or "best match". A test builds
   profiles in shuffled order and checks the result is alphabetical for
   every filter combination. A test checks no sort key other than the name
   exists in the module. Nothing is counted about who browses (brief 3.4).
   A calm link from Plan and Learn, never a prompt. Flag `directory`, gate
   L2.
5. **Intro requests (M-L, 3 sessions).** New `intro_requests` table. The
   person sends a message; the advisor sees only the figure-free view
   (percentages, goal type, timeline bucket, stage; built from the same
   pieces as Year in review's share card). The advisor replies in-app, text
   only, or shares their scheduling link. Advisors see only intros actually
   sent to them; no impression or click counts. Flag `intros`, gate L2.
6. **Two-step consent and consent records (M, 2 sessions).** New
   append-only `consent_records`: person, advisor, firm, the exact text
   shown, a hash of it, the time, and whether it's a grant or a revoke.
   Full sharing (the `advisor_clients` link) is made only from a grant.
   Insert and read only; a test checks no `UPDATE` or `DELETE` touches it
   outside the retention job (1.6f).
7. **Consent for advisor-made clients (M, 1-2 sessions).** Clients made by
   an advisor (one by one or from `client_csv.py`) see the same consent
   text at their setup link. Existing clients are asked once at their next
   sign-in, the way `terms_via` was rolled out. What the advisor sees
   before that is a question for L2.
8. **Advisor access log (M, 2 sessions).** New append-only
   `advisor_access_log`: advisor, client, page, time; never figures.
   Written where `USER_ID` switches to a client (`dashboard.py:1244-1253` at `11fd189`),
   one row per page open. The client sees it on Account: "Who has looked
   at my account".
9. **Revoking ends access within one request (S).** Already true for "Stop
   sharing" and "End relationship" (`can_view` reads the link every run).
   Both now also write a revoke to `consent_records`. A test: revoke, then
   the advisor's very next run falls back to their own account.
10. **The standing line (S-M, 1 session).** Every proposal, report and
    message a client sees shows the advisor's name and firm and "The
    advice here is from your advisor and their firm, not from Northwend"
    (final text under L2). A test renders each.
11. **State coverage (S, 1 session).** "States served" is a filter; an
    advisor isn't shown for a state they didn't list. The person picks
    their state in the filter; it's not stored.
12. **Cross-user tests for the new tables (S-M, 1-2 sessions, 1.2d).**
    Profiles, intros, consent records and access logs join the matrix
    test. New tables join `admin.ACCOUNT_TABLES` and `export.OWN` (or the
    test's left-out list, for append-only records kept for their retention
    period).
13. **Advisor-side AI drafts.** Already advisor-only (meeting prep). Any
    new helper drafts text for the advisor to send; nothing goes to a
    client without the advisor's action. `AI_PLAN.md` step 7.

**Done when:** on staging with L1 and L2 on, a person can browse, send an
intro, receive a reply, grant full sharing, see who looked, and revoke,
with every record written; the ordering, append-only and revoke tests pass.

---

## Direction note (October 6): beginners first, newer advisors

ADR 0005. Northwend is marketed as "new to investing? start here"; finding a
guide is a later, optional step. Advisors early in their careers are a named
audience. Northwend is never paid per lead, introduction or client - only, if
at all, one flat seat fee (below) - and a one-time review is the advisor's
service, paid to them directly. The L2 lawyer review covers this model.

---

## Step 6 - Billing (about 2-2.5 weeks, 13-16 sessions; +2-3 sessions for a webhook service)

Behind L1 and flag `billing`. After step 4. The provider is decision B2.

### The webhook problem (audit 1.11f)

Streamlit can't receive a POST, so there's nowhere for a webhook to land.
Options:

| Option | What it is | Cost |
|---|---|---|
| A. Pull, no webhook | After checkout, the app reads the checkout session from the provider's API, on the server, and activates the seat. An hourly job in GitHub Actions lists subscriptions and updates every seat's status. It is also the reconciliation job (1.11e) | No new service. No inbound surface. A lapse is seen within the hour, which the grace period absorbs |
| B. A tiny webhook service | One Starlette route on a second Render service, sharing the database. Verifies the signature, records the event id, writes seat status only | About $7 a month more, a second service to watch, and the first "second way in" the old Phase 3 warned about |
| C. A route inside Streamlit's server | Hooks Streamlit's internal Tornado app | Private API; breaks on upgrades. Not recommended |
| D. A Cloudflare Worker | Receives the webhook, writes to Neon | A second codebase in another language. Not recommended |

**Recommendation: A for launch.** The brief asks for webhook-driven status;
pull meets the same goals (the provider is the source of truth, nothing is
trusted from the browser) with no new surface. Move to B if seats grow
past a few hundred or an hour's lag starts to matter. Decision B3.

### Items

1. **Seats and pricing config (M, 2 sessions).** New `seats` table: advisor,
   plan (`monthly`, `annual`, `founding`), status, provider customer and
   subscription ids, period end, grace end. No card data, ever (1.11d).
   Pricing in settings (§8a): `SEAT_PRICE_MONTHLY`, `SEAT_PRICE_ANNUAL`,
   `FOUNDING_PRICE_MONTHLY`, `FOUNDING_SEATS` (default 20), and the
   provider's price ids. Amounts in integer cents. One flat fee each.
2. **`billing.py` has no usage component (S, 1.11g).** A test reads its
   source and fails on any reference to clients, intros, `advisor_clients`
   or `intro_requests`. The pricing copy gets the same check.
3. **Checkout and the customer portal (M, 2 sessions).** Hosted by the
   provider. Northwend makes the session and links out. Idempotency keys
   on outgoing calls (1.11c).
4. **Status sync (M, 2 sessions).** Option A: verify on return, and the
   hourly job with its own "Tell the admin it failed" step. It emails the
   admin counts when local and provider status differ. (Option B adds the
   service, signature checks and a `billing_events` table keyed on event
   id.)
5. **Founding seats (S, 1 session).** The first `FOUNDING_SEATS` paid
   advisors get the founding price, locked while their seat stays active.
   A counter, and a test at the boundary.
6. **Seat lapse (M-L, 2-3 sessions).** During the grace period (B5) the
   advisor can read and export, nothing else. One check,
   `seats.can_write(advisor)`, in every advisor write path (notes,
   proposals, reports, messages, client changes). After grace: client data
   closes to the advisor; their own records stay exportable, like
   `former_clients`. Clients are unaffected and keep their accounts. Test:
   a lapsed seat cannot write (1.2d).
7. **The "paid by no one" copy (S, 1.10h).** Reworded, not removed, the
   day L1 opens. The places are in `LEGAL_GATES.md` and `COPY_AUDIT.md`.
   Beta seats keep the current copy until then.
8. **Owner metrics (M, 2-3 sessions, §8a).** An Admin panel, counts only,
   with a CSV download through `export.csv_cell`:
   - second-walk rate within 45 days (exists: `feature_counts.walks`);
   - paying seats, founding seats, monthly churn (from `seats`);
   - intro requests, and intro to full-sharing conversion (from
     `intro_requests` and `consent_records`);
   - AI cost per active user and per seat (from step 2's cost log;
     `AI_COSTS.md`);
   - monthly running cost against seat revenue (the owner types the
     month's costs from D16's budget; revenue is seats times price,
     labelled "expected").
   A monthly job saves one row of totals (no user ids), so past months
   don't change. Measures about individuals keep the 20-person minimum and
   the opt-out. The disclosures say these totals exist before counting
   starts.

**Done when:** on staging with test-mode keys, an advisor can buy a seat,
see it active, cancel in the portal, reach grace and then lapse, with every
state change matched by the reconciliation job; the no-usage and lapse
tests pass; the metrics panel downloads a CSV.

---

## Step 7 - The remaining AI helpers (see `AI_PLAN.md`)

Summary, walk verdict, log line, storm narrator, glossary, CSV mapper,
document decoder, grader, drills, year in review and advisor drafts. Some
have a non-AI version today: the CSV mapper (`csv_import.py`'s button),
meeting prep (`meeting.py`), year in review (`recap.py`, no AI), and the
walk verdict (rule-based). Items, order and durations are in `AI_PLAN.md`.

---

## Step 8 - Hardening Phases 3-4 (once step 4 is stable; alongside step 7)

**Phase 3 - service seams, not a second backend (about 1 week, spread
out).** Don't build FastAPI now. Nothing needs an API; a second way in
means a second sign-in system, CSRF, CORS and every access check written
again. Rough cost: 4-6 weeks plus upkeep. Instead:
1. When a view is touched, move its SQL into a module function with a test
   (the allowlist from step 1 shrinks).
2. Keep calculation modules free of Streamlit (the step 1 test).
3. If billing uses option B, that service stays one route that writes seat
   status only.

**Phase 4 - the frontend (decide later; D3).** About 11,000 lines of views
in 31 files. A realistic move for one owner is 3-4 months, during which
product work stops. Stay on Streamlit through launch and Tier 1. Re-decide
when phone load for Home stays over 3 seconds after tuning, an
accessibility need can't be met, or a mobile app is decided. If it
happens: FastAPI + Jinja + HTMX, auth pages first, with shared sign-in
tested on staging before anything else.

---

## Step 9 - The remaining retention features (about 10-14 weeks, in this order)

Each behind its own flag; classification in `LEGAL_GATES.md`.

| Item | Size | Duration | Notes |
|---|---|---|---|
| R6 Statement and fact-sheet decoder | L | 2-3 weeks | Fact sheets first. Statements only once local redaction is proven by tests |
| R7 The Four Seasons | M | 1-2 weeks | Mostly writing; dated content with sources |
| R8 Trail Forks | M | 1-2 weeks | Writing; "what to ask", never what to do |
| R9 Lost & Found | S-M | ~1 week | The account map's second half exists |
| R10 Explain It To Someone | S-M | ~1 week | Reuses step 5's figure-free view; an expiring, revocable link |
| R11 Pay Yourself | M | 1-2 weeks | Builds on money going out; rules of thumb chosen by the person |
| R12 Preparedness drills | M | ~2 weeks | Tap-only; no "right answer" on an investment choice |

---

## Alongside, any time (small; from the old Phase 5)

- **A status page (S, G7):** hand-edited, on the website, no scripts.
- **A "what's new" page (S, G11):** a short dated list, linked from About.
- **Price "as of" and "report a wrong price" (M, G8).**
- **The quarterly restore drill and the yearly licence re-check** in the
  runbook's calendar.

---

## Durations at a glance

| Step | What | Sessions | Duration | On the path to directory + billing? |
|---|---|---|---|---|
| 1 | Phase 0 (P1 fixes, flags, L0 basics, principle tests) and Phase 1 (runbook, CI, layer test, schema version, retention) | 20-23 | ~3 weeks | Yes |
| 1 + B9 | If the re-layout, Alembic and pydantic are chosen | +20-30 | +3-4 weeks | Yes, if chosen |
| 2 | AI foundations; example-mix rewrite | `AI_PLAN.md` | 2-3 weeks (AI_PLAN.md section 10: 18 small steps, about 14-18 sessions) | Yes |
| 3 | Walk flag, Ledger, Log, Storm Drill, 401(k) decoder, no-account decoder | 12-14 | 2-2.5 weeks | Yes |
| 4 | Render, Cloudflare, restore drill, keys, roles | 3-5 code + owner time | ~1 week, overlapped with steps 1-3 | Yes (0-1 week on the path) |
| 5 | Agreement, licence record, directory, intros, consent, access log, standing line | 20-24 | 3-4 weeks | Yes |
| 6 | Seats, pricing, checkout, sync job, lapse, founding seats, owner metrics | 13-16 (+2-3 for a webhook service) | 2-2.5 weeks (+0.5) | Yes |
| 7 | Remaining AI helpers | `AI_PLAN.md` | `AI_PLAN.md` | No |
| 8 | Service seams; frontend later | - | ~1 week spread; frontend 3-4 months if ever chosen | No |
| 9 | R6-R12 | - | 10-14 weeks | No |

**Total to "directory and billing ready to switch on": about 12-16 weeks
of part-time work** (steps 1, 2, 3, 5 and 6 in a row, with step 4's owner
steps run alongside). Starting the week of Oct 12, that's late January to
late February 2027. The low end assumes step 2 takes 2 weeks and the
smaller figure everywhere; the high end assumes 3 weeks and the larger.
Choosing the brief's Phase 1 tools (B9) adds 3-4 weeks.

**Going live also needs, outside the code:** the lawyer's sign-off on L0,
L3, L1 and L2, in that order; the business entity and insurance (B8); and
the billing provider's approval. Start all of them in week 1.

---

## Decisions for the owner

Each is a question, a recommended answer, and why in one line. AI decisions
(the global spend ceiling, allowance values, retrieval approach, model per
helper) are in `AI_PLAN.md`.

### New with the master brief

**B1. Seat price?**
*Recommended:* $49 a month, or $490 a year (two months free). Founding
seats $29 a month, locked while the seat stays active, for the first 20
paid advisors.
*Why:* below a typical advisor CRM seat, so it's an easy yes as an add-on,
and the founding price pays early advisors back for their feedback.

**B2. Billing provider?**
*Recommended:* Paddle, as merchant of record. (Lemon Squeezy, now owned by
Stripe, is similar; check its current terms.) Stripe with Stripe Tax is the
choice if the owner prefers the lowest fees.
*Why:* as the seller of record, Paddle collects and files sales tax in the
states that tax software, which a one-person owner shouldn't carry. At $49
it costs about $0.90 a seat a month more than Stripe Billing plus Stripe
Tax (roughly 5% + 50¢ against 2.9% + 30¢ + 0.7% + 0.5%). Both keep card
data off Northwend; the audit's 1.11 items apply to either.

**B3. Webhook or pull?**
*Recommended:* pull (option A in step 6): verify on return from checkout,
and an hourly reconciliation job in GitHub Actions. No inbound endpoint.
*Why:* Streamlit can't receive a POST, and a second service is a second
thing to secure, pay for and watch, to save at most an hour's lag that the
grace period absorbs.

**B4. Directory filters?**
*Recommended:* five filters from the brief's profile fields: state served,
virtual or in person, fee model (AUM, flat, hourly, subscription), who they
serve (a fixed list), and account minimum (in bands, including "no
minimum"). Shown but not filterable: credentials, registration type,
description, scheduling link.
*Why:* each filter answers "can this firm serve me at all"; filtering on
credentials invites reading more letters as "better", which is a ranking by
another name.

**B5. Grace period on lapse?**
*Recommended:* 30 days of read and export. After that, client data closes
to the advisor; their own records (notes, sent documents) stay exportable.
Clients are never affected.
*Why:* a month covers a failed card and a holiday, and the advisor never
loses the records their own rules require them to keep.

**B6. How long are consent records and access logs kept?**
*Recommended:* 7 years (the brief's default) until the lawyer says
otherwise. They hold ids, times and the exact consent text, never figures,
and they outlive account deletion. The Privacy Policy says so.
*Why:* it covers the advisers' 5-year record rule with margin, and these
records are what protects both the person and the owner in a dispute.

**B7. Invite codes or a waitlist during beta?**
*Recommended:* invite codes while L0 is off, made by the admin and handed
out by the owner. Advisors' setup links already work as invites. Open
sign-up when L0 is on and the AI ceiling is in place.
*Why:* a waitlist means keeping strangers' emails and a mailing process;
codes cap growth with no data on anyone who hasn't joined.

**B8. Business entity and insurance first?**
*Recommended:* yes. Form a single-member LLC (or the local equivalent)
before the first paid seat, and ideally before open sign-up. Get quotes for
technology errors-and-omissions and cyber insurance. Record both in the
runbook's owner prerequisites. Ask the attorney and an accountant which
form fits.
*Why:* the owner's first goal is limiting personal liability, and a
billing provider will ask for the entity anyway. (Not legal advice.)

**B9. The brief's Phase 1 tools: package re-layout, Alembic,
pydantic-settings?**
*Recommended:* none of them, for now. Instead: a layer-rule test, a
`schema_version` with a migrate command, and a standard-library
`settings.py` (step 1).
*Why:* together they'd cost 3-4 weeks with no change for users, and the
lighter pieces deliver the brief's actual goals: no SQL in pages,
versioned migrations tested on Postgres, and config that fails closed.

**B10. Release what's on staging now, or wait?**
*Recommended:* release after two small changes, about 2 sessions:
`flags.py` with the Walk behind `walk` (off in production until the owner
turns it on), and the Walk reminder's unsubscribe link and header.
*Why:* everything else on staging is calculators on the person's own
inputs and advisor tools, tested and green; the Walk's verdict is the one
advice-adjacent piece, and its email lacks the unsubscribe the audit
requires.

**B11. Let the 401(k) decoder start early?**
*Recommended:* yes. Let step 3's signed-in text box (no AI, no dependency
on step 2) be built during step 2.
*Why:* open enrolment ends in November or December, and it's R5's natural
test window; the brief's order would land it after the season.

**B12. The no-account decoder: in the app or on the website?**
*Recommended:* in the app, as a pre-sign-in route behind a flag, switched
on after step 4; plus a static explainer page on the website that links to
it.
*Why:* the website allows no scripts, so it can't compute; the app can,
and the static page is what search engines can find.

### Kept from the hardening plan (updated where the brief changes them)

**D1. Screenshot reading: what should the AI see?** *(updated)*
*Today:* the model receives the whole image, with every balance, account
name and number on screen (`screenshot_read.py:29-51`, `:117-146`).
*Recommended:* brief §5.1 now says models never see holdings, account names
or numbers, so the "separate consent screen" option no longer fits. Turn the
AI path off behind a flag now (step 1). Try reading screenshots locally with
OCR into the paste reader (`paste_parse.py`). If that handles test
screenshots from five brokers, bring screenshots back without AI. If not,
leave it off. Details in `AI_PLAN.md`.
*Why:* it's the one feature that breaks the figures policy by design.

**D2. Hosting: where does the app live?**
*Recommended:* Render Starter behind Cloudflare's proxy, Neon for the
database, GitHub Actions for jobs. Done before steps 5-6 go live.
*Why:* least to run for one person, and Cloudflare supplies the headers
that neither Streamlit nor Render can add.

**D3. Frontend: stay on Streamlit or move?**
*Recommended:* stay through launch and Tier 1 (step 8). Re-decide on
measured phone speed or an accessibility need.
*Why:* the move is a 3-4 month pause on the product.

**D4. Market data: which source, and what budget?**
*Recommended:* end-of-day prices as the primary data; stop minute-by-minute
quotes or keep them only while a page is open. Read Finnhub's display terms
before launch, and budget for one paid end-of-day plan if needed. The
no-account decoder never fetches for a visitor.
*Why:* calm by default needs daily closes, and they're the cheapest to
license properly.

**D5. Retention: how long is each thing kept?** *(rows added)*

| Data | Kept |
|---|---|
| Uploaded files, screenshots, pasted text (including the no-account decoder) | Not kept (memory only) |
| Holdings, plan, profile, notes | Until the person deletes them or the account |
| Deleted accounts | Gone at once; gone from backups when the restore window passes (D6) |
| Self-made accounts never confirmed | Deleted after 30 days |
| Sign-in sessions | 30 days; "remember device" 30 days |
| Wrong-password, sign-up, email-send and decoder counts (hashed address) | 1 day |
| Email links | Reset 1 hour, confirm 3 days, setup 7 days |
| Minute-by-minute prices | 1 week (then one close a day) |
| Daily prices, fund data | Kept (no personal data) |
| Error records | 90 days |
| Admin action log | 1 year |
| **Consent records, advisor access logs** | **7 years (B6), past account deletion** |
| **Intro requests and replies** | **The lawyer's call under L2; default: like consent records if sharing followed, else deleted with the account** |
| **Seats and billing ids** | **As long as tax records need (ask the accountant; default 7 years)** |
| **Owner metrics (monthly totals, no ids)** | **Kept** |
| Host logs | The host's default; check it's no more than 30 days |
| AI requests | Per the API terms; zero retention for any helper that carries a figure (`AI_PLAN.md`) |

*Why:* it writes down what the code mostly does, and adds what the brief
needs.

**D6. Backups: how long, given the promise?**
*Recommended:* a Neon plan with a 7-day restore window; the disclosure says
"up to 7 days"; drill a restore every quarter. No separate dump files.
*Why:* 6 hours is too short to notice most mistakes, and 30 days stretches
"deleted means deleted".

**D7. A former client deletes their account: do the old advisor's records
go too?** *(now settled by brief §2.7)*
*Recommended:* keep the advisor's own records (notes, sent documents,
`former_clients`); delete everything the client owns. Pass
`keep_records_of` for former advisors in `admin.delete_account`. Consent
records and access logs follow B6.
*Why:* the brief says advisors keep what their record-keeping duties need
and never the client's live data, which is what `end_relationship` already
does.

**D8. Admin access to accounts without an email?**
*Recommended:* keep the temporary-password recovery, log it in the admin
action log, and say so in the disclosures.
*Why:* recovery is needed for advisor-made logins, but today it's an
unrecorded way into holdings.

**D9. Should Ask Northwend's notes keep amounts people type?**
*Recommended:* no; goals, dates and decisions only. Now part of brief §5.1
(`AI_PLAN.md`).
*Why:* "the AI never sees dollar amounts" should hold across conversations.

**D10. US only, and how to record 18+?** *(now an L0 requirement)*
*Recommended:* "I live in the United States" beside the 18+ box, both as
their own timestamped fields (step 1).
*Why:* the brief's L0 needs both, and a stored attestation is what a lawyer
will ask for.

**D11. Require a confirmed email before saving holdings?**
*Recommended:* no. AI waits for confirmation (as today); unconfirmed
accounts go after 30 days.
*Why:* the data sits only in that person's account, and the step mostly
loses real people.

**D12. Alembic, the re-layout, pydantic-settings?** *(now B9)*

**D13. Decimal for money?**
*Recommended:* no for holdings and projections: floats, rounded at display.
Seat prices are integer cents, as the provider uses.
*Why:* Northwend shows and projects money but never moves it; billing
amounts are the provider's.

**D14. Encrypt TOTP secrets at rest?** *(approved Oct 6: done, ROADMAP 1b.8b)*
*Recommended:* only if adding the `cryptography` package is acceptable.
*Why:* the key would sit beside the database URL, so it guards a narrow
case (a leaked backup).

**D15. How is an advisor's licence checked, and how often?** *(updated:
the brief wants a job)*
*Recommended:* BrokerCheck or IAPD by CRD at approval, with the match,
source and date stored. A yearly job emails the admin who's due. An
advisor not re-checked within 13 months leaves the directory until they
are.
*Why:* the directory now rests on that check, and there's no official API
to automate the lookup itself.

**D16. A monthly budget, written down?** *(updated)*
*Recommended:* yes, one table in the runbook: Render, Neon, Cloudflare,
Resend, Anthropic (with the console limit), market data, the domain, and
now the attorney, insurance, the entity's yearly fees and the billing
provider's fees. The owner metrics compare it with seat revenue each month.
The AI ceiling's number is in `AI_COSTS.md`.
*Why:* until seats pay, every cost lands on the owner, and the funding
tranches are judged on these numbers.
