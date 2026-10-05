# Northwend hardening plan

This adapts the owner's hardening brief (Phases 0-5) to what the audit found
in the code (`docs/SECURITY_AUDIT.md`, written against commit `ca362b2`). It
sits beside `ROADMAP.md`. It doesn't replace it.

## The short version

- Northwend is closer to "production" than the brief assumed. Staging, a
  protected `main`, CI on SQLite and Postgres, scheduled jobs that report
  failures, error alerts, packaging, two-step sign-in, export and
  self-delete, and the Render move all exist or are coded.
- Before any wider launch, there are about two weeks of real work: Phase 0
  plus Phase 2. Most of it is small and specific.
- The brief's big rebuilds can wait. Recommended against for now: the
  `core/data/services/ui` re-layout, Alembic, pydantic-settings, a Docker
  image, the FastAPI backend and the HTMX frontend. Each is weighed below,
  with its cost. The Streamlit app can be made safe enough for a free beta
  where it stands.
- Durations assume one owner working part-time with AI sessions. ROADMAP's
  sizes: S = an hour or two, M = a session, L = several sessions.

## How it fits beside ROADMAP.md

- **Working rules stay the same.** Staging first, "Commit and push?",
  "Release to main?", and a plan first before touching CSV import or price
  fetching.
- **Security fixes travel like bug fixes.** They go to `main` once Tests is
  green on staging, the same as the Oct 4 batches.
- **The Ritual comes after Phase 0, not after the whole plan.** Phase 0 runs
  first, then **R1 The Monthly Walk** ("Next two weeks", item 1) carries on.
  Phase 2 runs alongside it, mostly as owner steps. One rule ties them
  together: the Walk's reminder email must ship with an unsubscribe link and
  header (audit 1.7c).
- **Launch.** L6 should wait for Phase 0, Phase 2, and L4's owner steps.
  ROADMAP already says "R1 and R2 first"; this adds the items marked
  "before launch" below.
- When the owner approves this plan, add a short **"H. Hardening"** section
  to ROADMAP (H0-H5, one line each, pointing here). Tick items there, as
  usual.

---

## Phase 0 - Close the open P0 and P1 items in code (about 1 week, 6-8 sessions)

No architecture change. Each fix gets a test. Items already done are dropped
from the brief's list: CSV export escaping, SQL parameterisation, hashed
single-use tokens with expiry, deletion in `finally`, and the "no figures in
email" templates.

1. **Secrets check - done (Oct 5).** The full history is clean (audit 1.5a).
   Owner: turn on GitHub secret scanning and push protection (2 minutes).
2. **Fail closed on configuration (M, P1, audit 1.5b).** Add a small
   standard-library `settings.py`. It knows when it's hosted (`RENDER`,
   `/mount/src`, or `NORTHWEND_ENV`). When hosted, it refuses to start
   without a Postgres `PORTFOLIO_DB`, and it is what decides about the
   "path on this machine" box, error details and alerts. Today these are
   keyed on "is the database Postgres". Move the scattered `os.environ`
   reads into it, one at a time. A test checks that a hosted copy with no
   DSN stops with a clear message.
3. **Size limits (S, P2, 1.3b).** Set `server.maxUploadSize` to 10 MB in
   `.streamlit/config.toml`. Add a row cap to `csv_import.read_rows`
   (5,000 rows), a length cap on pasted text, and `max_chars` on the chat
   box. Check screenshot types by their first bytes (PNG, JPEG and WEBP
   signatures). That needs no Pillow. Reset the CSV uploader after a
   successful read, as the screenshot one does.
4. **Sign-in limits (M, P1, 1.1c).** Add a per-address limit on wrong
   passwords. Use the same `login_failures` table with an `addr:` key and
   the hashed address the sign-up limits already use. Hash against a dummy
   salt for an unknown username, so timing doesn't reveal accounts.
5. **AI ceiling (M, P1, 1.4c and G5).** No code first: the owner sets a
   monthly spend limit in the Anthropic console, with a separate workspace
   for staging. Then add an app-wide monthly count in `ai_usage`, with a
   calm "Ask Northwend is resting until next month" at the cap. The admin
   is emailed at 50% and 80%, through `error_alerts`/`mailer`, counts only.
6. **Make the privacy wording true (S, P1, X3 and 1.3d).**
   - Fix "never balances" in `TRUST_LINE`/`NOT_KEPT` to say what's kept
     (values and cash are; account numbers beyond 3 digits, files and
     images aren't).
   - Add "except screenshots you choose to send" to the website's AI line,
     or follow Decision D1.
   - Change the memory tool's instruction so it doesn't keep dollar amounts
     or account details (Decision D9).
   - Update `disclosures.py` and the drafts to match, and rebuild the
     website.
7. **Principle tests the brief asked for (M).**
   - Every `mailer` function rendered with sample inputs: no currency
     amounts or digit groups (1.7b).
   - An AppTest showing an advisor without `two_step_ok` sees only the code
     page (1.1e).
   - An AppTest showing `?client=<not yours>` falls back to your own
     account (1.2a).
   - A matrix test: user A can't read, change or delete user B's rows in
     every table in `admin.ACCOUNT_TABLES`.
   - Make `advisor_id` required in the `advising` note helpers.
   - The "AI never sees figures" test exists already
     (`tests/test_core.py:914`). Extend it to a fund name that carries a
     dollar figure, and decide whether to strip it (strip digits after `$`).
8. **Owner tasks (S each).**
   - Delete the old Neon backup branch (X6).
   - Check DMARC with `dig TXT _dmarc.northwend.app`, and add
     `p=quarantine` if missing (1.7a).
9. **Friendly save errors (S, P3, X4).** Replace the three
   `"... nothing was changed: {exc}"` messages with the calm message plus
   an error code.
10. **Record Decision D1 (screenshots)** as the first ADR in `docs/adr/`.
    Keep ADRs to one page each, and only for decisions in the list at the
    end of this document.

**Done when:** no P0 is open; every P1 above is closed or has a decision
recorded; the new tests pass on SQLite and Postgres; staging shows the new
wording.

---

## Phase 1 - Foundations, without a re-layout (1-2 weeks, spread out)

The brief's goal is right: testable, deployable, legible code. But most of
it exists already. The calculations are pure modules with tests (`perf`,
`plans`, `income`, `fees`, `stress`, `next_deposit`, ...). Views are
separate files. CLAUDE.md maps the code.

1. **RUNBOOK.md (M, P2, G6 and 1.10e).** One page each:
   - deploy (staging, then main, on Render);
   - roll back (revert through staging; Render's rollback);
   - restore (Neon point-in-time to a branch, check row counts, swap);
   - rotate each key (Anthropic, Resend, Finnhub, the Neon password, the
     GitHub secrets);
   - sign everyone out;
   - turn off AI or email in an emergency;
   - shut down cleanly (notice, export window, delete);
   - who to tell after a breach, and what to say.

   Written so a capable stranger could follow it.
2. **"Sign out everyone" (M, P2, X5).** A session generation number in the
   database, checked on every run like the password stamp. A
   `manage_users.py sign-out-all` command bumps it. This also makes "sign
   out other devices" close open tabs.
3. **Admin action log (M, P2, X2).** An append-only table: who, what, which
   account, when. Never holdings. It's shown on Admin > System and kept 1
   year. Name the temporary-password path in the disclosures.
4. **CI additions (S, P3, G3 and 1.8e).**
   - `ruff check` with a small rule set; formatting changes left alone.
   - `pip-audit` against `requirements.txt`.
   - Dependabot, weekly and grouped, for pip and Actions.
   - Pin Actions by SHA.

   Skipped: mypy (the views share one namespace through `_view`, so a type
   checker would need many exceptions to be useful), pre-commit, and a
   Makefile (`cli.py` and `COMMANDS.txt` already cover setup and run).
5. **A schema version and a migrate command (M, P2, 1.6d).** A
   `schema_version` table, and `northwend-migrate` running
   `portfolio._ensure_schema` on purpose. The app still runs it at start
   until Phase 2 item 6 splits the roles. Keep the two schema files and the
   back-fill list. The Postgres CI job already tests upgrading an old
   database.
6. **Password hashing (S, P2, 1.1b).** Raise PBKDF2 to 600,000 iterations,
   and store the count per user so old hashes are upgraded at their next
   sign-in. Standard library only.
7. **TOTP secrets encrypted at rest (S, P2, 1.1e) - only if Decision D14
   says yes.** Python's standard library has no encryption, so this needs
   the `cryptography` package. The key would go in the host's secrets
   (`NORTHWEND_TOTP_KEY`). In the same step, switch backup-code hashes to
   PBKDF2 (standard library), which needs no decision.
8. **Retention, written and applied (M, P2, 1.10d).** Put Decision D5's
   table in `disclosures.py` and the Privacy draft. Add a nightly
   `northwend-tidy` step to the history job: unconfirmed self-made accounts
   older than 30 days, `error_events` older than 90 days, admin log older
   than 1 year. It reports counts, and has its own "Tell the admin it
   failed" step, as CLAUDE.md requires.
9. **More broker files (M, P2, G1).** Made-up exports for Merrill,
   Interactive Brokers, Webull, SoFi, Public, Ally and M1, alphabetical,
   none primary. A plan first, per CLAUDE.md, since it touches
   `csv_import.py`.
10. **A short ARCHITECTURE.md (S, P3, G10).** One page: a run of
    `dashboard.py` from top to bottom (sign-in, gate, `USER_ID`, views), the
    data model in ten lines, where jobs run, and what the AI is sent. It
    points to CLAUDE.md for the file map instead of copying it.
11. **Staging seed (S, P3).** A `manage_users.py seed-staging` command: a
    made-up household, an advisor and three clients, built from
    `sample_data.py`. Staging never needs real data.

**Dropped from the brief's Phase 1, and why:**

- **The `northwend/core|data|services|ui_streamlit` re-layout.** It would
  move nearly every file, break the `_view` design, invalidate every import
  in 708 tests, and need CLAUDE.md, `pyproject.toml` and the packaging test
  rewritten. Rough cost: 2-3 weeks with no change for users. The real goal
  (no business logic or SQL in pages) is mostly met already. The few SQL
  reads left in views (for example `views/clients.py:585-588`) can move
  into modules one at a time, when they're next touched.
- **pydantic-settings.** It's a dependency for what about 60 lines of
  standard library can do (Phase 0 item 2).
- **Alembic.** It means a baseline, two schema dialects, a new tool to learn
  and a third copy of the schema. The current approach is idempotent and
  tested on Postgres. A version number gives most of the benefit.

---

## Phase 2 - Own the hosting (about 1 week; mostly owner steps, some in parallel with Phase 1)

The code for this is mostly done (ROADMAP L4: `render.yaml`, `hosting.py`).
What's left:

1. **Finish L4 (owner, M).** Create the Render Blueprint, check it on its
   `onrender.com` address, then point `app.northwend.app` at it. Add the
   missing environment variables to `render.yaml`:
   - `NORTHWEND_ADMINS`, `ALERT_EMAIL`, `APP_URL`, `NORTHWEND_ENV`;
   - `STREAMLIT_SERVER_MAX_UPLOAD_SIZE=10`;
   - `STREAMLIT_CLIENT_SHOW_ERROR_DETAILS=none`;
   - `STREAMLIT_BROWSER_GATHER_USAGE_STATS=false`, as a second guard.
2. **Cloudflare in front of the app (owner + S, P1, 1.8b).** Turn on
   Cloudflare's proxy for `app.northwend.app`. Websockets work through it.
   Add a response-header rule:
   - `Strict-Transport-Security: max-age=31536000; includeSubDomains`
   - `X-Content-Type-Options: nosniff`
   - `Referrer-Policy: strict-origin-when-cross-origin`
   - `Content-Security-Policy: frame-ancestors 'none'`, plus
     `X-Frame-Options: DENY`
   - `Permissions-Policy: camera=(), microphone=(), geolocation=()`

   Then set `CLIENT_IP_HEADER=cf-connecting-ip`, so the address limits see
   real visitors. A full CSP isn't practical for Streamlit, so aim for an
   "A" on securityheaders.com, not "A+". Rate limiting at the edge can't
   see sign-in attempts, because they travel inside the websocket. The
   app's own limits (Phase 0 item 4) do that job.
3. **Backups and a tested restore (M, P1, 1.6e).** Per Decision D6: choose
   the Neon restore window and update the disclosures to match. Write a
   restore drill into RUNBOOK.md: restore to a branch at a past time, count
   rows in the main tables, compare, delete the branch. Run it once now,
   then every quarter, with a calendar reminder. Scripting it through
   Neon's API is a later nicety.
4. **Uptime check (S, P2, G4).** A free outside monitor on
   `/_stcore/health` and the website, emailing the owner. No third-party
   script on any page.
5. **Separate keys per copy (S, P2, 1.5c).** Staging gets its own Anthropic
   workspace and limit, and `MAIL_DRY_RUN=1` or a test-only Resend key.
   Production keys live only in Render (and in GitHub for the jobs).
6. **Least-privilege database roles (M, P2, 1.6c).**
   - an owner role used only by `northwend-migrate`;
   - an app role with read and write on rows but no DDL;
   - a jobs role for the scheduled jobs.

   Then remove schema setup from the app's start. This needs Phase 1 item 5
   first.
7. **Update the wording (S, P1, 1.10a).** Change "Streamlit Community Cloud
   hosts the app" to Render in `disclosures.py` and the drafts, and add
   Cloudflare to "Services Northwend uses".
8. **Retire Community Cloud (owner, S).** Set `MOVED_TO` on the old app.
   After a month, when old email links have expired (the longest lasts 7
   days), delete it and its secrets.
9. **Scheduler: keep GitHub Actions.** It runs, it alerts on failure, and
   it costs nothing. The brief's worker container with APScheduler would be
   a second always-on service to pay for and watch. Revisit only if GitHub's
   schedule delays start to matter. Render's cron jobs are the simple next
   step then.

**Dropped:** a Dockerfile. Render's native Python runtime builds from
`requirements.txt`. Only a move to a VPS would need one.

**Done when:** the app is served at `app.northwend.app` from Render behind
Cloudflare with the headers above; a restore drill has passed once; the
uptime check is live; Community Cloud shows "has moved"; the disclosures
name the real hosts.

---

## Phase 3 - Service seams, not a second backend (no fixed block; about 1 week spread over later work)

The brief proposes a FastAPI backend (3-5 weeks). **Recommendation: don't
build it now.**

- Nothing needs an API today. There's no mobile app and no second frontend.
- A second way in means a second sign-in system, CSRF, CORS, rate limiting,
  and every access check written again for a surface that today can't
  exist. The audit's strongest result (1.2b: "hidden means not sent") holds
  only because there's no API.
- Rough cost: 4-6 weeks for one owner, plus ongoing upkeep, with nothing
  new for users.

Instead, keep the seams clean, so an API stays cheap to add later:

1. When a view is touched, move any SQL it still holds into a module
   function with a test (S each).
2. One "AI gateway" in `advisor.py`: every model call goes through one
   function. That function checks the allowance and the app-wide cap,
   builds the context, and logs nothing. Today the calls are spread across
   `advisor.py`, `meeting.py`, `client_plan.py`, `csv_import.py`,
   `txn_import.py` and `screenshot_read.py`. The existing test pins every
   call (`tests/test_legal_guardrails.py:308`). (M)
3. Keep pure calculation modules free of Streamlit imports. A test can
   check this.

**When to revisit:** when a mobile app or a non-Streamlit frontend is
actually decided (see Phase 4).

---

## Phase 4 - The frontend (decide later; don't start before launch and R1-R5)

The brief recommends FastAPI + Jinja + HTMX + Alpine, page by page.
That's a sound stack if Northwend leaves Streamlit. **But it shouldn't start
now.**

- **The cost is larger than the brief's 4-8 weeks.** There are about 10,000
  lines of views across 27 pages, plus the design system, phone layouts and
  accessibility work already done in Streamlit. A realistic figure for one
  owner with AI help is 3-4 months, during which the Ritual work stops.
- **A strangler move has a hard first step.** Two apps on one domain must
  share sign-in. Streamlit can read a cookie set by the new app, and
  sessions are already server-side, so this can work. It is still a new
  piece of security work.
- **What Streamlit costs today is known and bounded.** It can't set its own
  headers (fixed at Cloudflare) or `HttpOnly` cookies (X1, contained by
  escaping and a test). It re-runs the whole page (contained by fragments
  and query caps, `tests/test_page_queries.py`). It has limits on phone
  layout and tap targets (G9).

**Recommendation:** stay on Streamlit through launch and the Ritual's
Tier 1. Decide again when one of these is true:

- phone load times measured on a mid-range phone stay over 3 seconds for
  Home after tuning;
- an accessibility need can't be met in Streamlit;
- a mobile app is decided.

If the move happens, the brief's stack and order (auth pages first, then
Home, then bringing holdings in) is the right one. Add one step before it:
sign-in shared between the two apps, tested on staging.

---

## Phase 5 - Quality of life (ongoing, folded into ROADMAP)

Already done, and dropped from the brief's list:

- friendly errors with a code;
- the owner's admin portal (accounts, advisor approvals, AI use, System);
- self-serve export and delete;
- the support email;
- calm empty states.

Still worth doing, small and in any order:

- **A status page (S, G7):** a hand-edited page on the website,
  `/status`. No scripts, matching the site's CSP.
- **A "what's new" page (S, G11):** a short dated list on the website,
  linked from About. No pop-ups, nothing that nags.
- **Price "as of" and "report a wrong price" (M, G8):** show the quote time
  when it's older than a day. Add a button that records ticker, date and a
  reason (no account data), listed on Admin.
- **The licence check, recorded (S, 1.2c):** when approving, the admin
  records the CRD match and the source (BrokerCheck or IAPD) and the date.
  Add a yearly reminder to re-check advisors approved over 11 months ago,
  as a line on Admin. Fill in the Terms placeholder to match.
- **The quarterly restore drill and the yearly licence re-check** go in
  the runbook's calendar.
- **Dropped:** feature flags in a table (staging already ships things
  dark), and nightly pre-computing of the checks on Home (query caps show
  no need yet).

---

## Durations at a glance

| Phase | What | Realistic time | Before launch? |
|---|---|---|---|
| 0 | Close P0/P1 items in code, principle tests, owner quick tasks | ~1 week (6-8 sessions) | Yes |
| 1 | Runbook, sign-out-all, admin log, CI additions, schema version, retention job, broker files | 1-2 weeks, spread out | Runbook and sign-out-all, yes |
| 2 | Render live behind Cloudflare, backups and restore drill, uptime, keys, roles | ~1 week, mostly owner steps | Yes (except roles) |
| 3 | Service seams (no FastAPI) | ~1 week spread over other work | No |
| 4 | New frontend | 3-4 months if chosen; not now | No |
| 5 | Status, what's new, price "as of", licence record | a few S/M items | Status page, yes |

Total before launch: about 3 weeks of part-time work, half of it owner
steps that don't need code.

---

## Decisions for the owner

Each is a question, a recommended answer, and why in one line.

**D1. Screenshot reading: what should the AI see?**
*Today:* the model receives the whole image. That means every balance,
gain, account name and number on screen. It sends back symbols, share
counts, total or average cost, percentages and cash
(`screenshot_read.py:29-51`, `screenshot_read.py:117-146`).
*Recommended:*
1. Now: keep it opt-in, and make every claim say "except screenshots you
   choose to send".
2. Next: try reading screenshots on the server with a local OCR library
   and feeding the text into the existing paste reader (`paste_parse.py`),
   with no AI at all.
3. If the local read handles the owner's test screenshots from five
   brokers, remove the AI path. If not, keep it with a separate consent
   screen that says plainly what the AI sees.

*Why:* the owner's own Oct 5 rule says uploaded documents are parsed
locally before anything reaches the AI, and the paste reader already turns
holdings text into rows.
(Local OCR is a heavy dependency: RapidOCR with onnxruntime, or Tesseract,
which needs a system package. Check memory on Render Starter before
committing.)

**D2. Hosting: where does the app live?**
*Recommended:* Render Starter (already chosen and coded) behind Cloudflare's
proxy, with Neon kept as the database and GitHub Actions kept for jobs.
*Why:* least to run for one person, and Cloudflare supplies the headers that
neither Streamlit nor Render can add.

**D3. Frontend: stay on Streamlit or move?**
*Recommended:* stay through launch and Ritual Tier 1. Re-decide on measured
phone speed or an accessibility need. If moving, use FastAPI + Jinja +
HTMX.
*Why:* the move is a 3-4 month pause on the product, and Streamlit's known
gaps can each be contained today.

**D4. Market data: which source, and what budget?**
*Recommended:* make end-of-day prices the primary data, and stop the
minute-by-minute live quotes (or keep them only while a page is open, from
one source whose terms allow it). Read Finnhub's current terms for public
display before launch. Budget for one paid end-of-day plan if the free
terms don't allow it, as the first cost accepted. Drop Yahoo for anything
that can come from the paid source.
*Why:* "calm by default" needs daily closes, not ticking prices, and
end-of-day data is the cheapest to license properly.

**D5. Retention: how long is each thing kept?**
*Recommended schedule:*

| Data | Kept |
|---|---|
| Uploaded files, screenshots, pasted text | Not kept (memory only, during the review) |
| Holdings, plan, profile, notes | Until the person deletes them or the account |
| Deleted accounts | Gone at once; gone from backups when the restore window passes (D6) |
| Self-made accounts never confirmed | Deleted after 30 days |
| Sign-in sessions | 30 days; "remember device" 30 days |
| Wrong-password counts, sign-up and email-send counts | 1 day |
| Email links | Reset 1 hour, confirm 3 days, setup 7 days |
| Minute-by-minute prices | 1 week (then one close a day) |
| Daily prices, fund data | Kept (no personal data) |
| Error records (`error_events`) | 90 days |
| Admin action log | 1 year |
| Host logs (Render, GitHub) | The host's default; say so, and check it's no more than 30 days |
| AI requests | Anthropic's commercial terms; check and quote them in the Privacy Policy |

*Why:* it writes down what the code mostly does already, and adds the three
rules that are missing.

**D6. Backups: how long, given the promise?**
*Recommended:* move to a Neon plan with a 7-day restore window. Change the
disclosure from "about 6 hours" to "up to 7 days", and drill a restore every
quarter. Don't keep separate dump files.
*Why:* 6 hours is too short to notice most mistakes. 30 days stretches the
"deleted means deleted" promise. Dumps would be one more copy of everyone's
data to guard.

**D7. A former client deletes their account: do the old advisor's records go too?**
*Today:* yes. Notes, proposals, reports and the former-client row are
deleted (`admin.py:265`).
*Recommended:* keep the advisor's own records (as `end_relationship`
already does when it closes an account). Delete everything the client owns.
State the split in the Privacy Policy, and have the lawyer confirm.
*Why:* the code already treats these as the advisor's records under
Rule 204-2 (`advising.py:193-199`), and a client shouldn't be able to erase
them by accident.

**D8. Admin access to accounts without an email?**
*Recommended:* keep the temporary-password recovery, add the admin action
log (Phase 1), and say in the disclosures that the admin can reset a login
that has no email.
*Why:* recovery is needed for advisor-made logins, but today it is an
unrecorded way into holdings.

**D9. Should Ask Northwend's notes keep amounts people type?**
*Recommended:* no. Tell the memory tool to keep goals, dates and decisions
but never dollar amounts, account names or numbers. Add a test on the
instruction.
*Why:* "the AI never sees dollar amounts" should hold across conversations,
even when someone volunteers a figure once.

**D10. US only, and how to record 18+?**
*Recommended:* add "I live in the United States" next to the 18+ box. Store
both as their own timestamped fields alongside `terms_version`.
*Why:* the Terms draft already says US only, and a stored attestation is
what a lawyer will ask for.

**D11. Require a confirmed email before saving holdings?**
*Recommended:* no. Keep AI waiting for confirmation (as today), and delete
unconfirmed accounts after 30 days (D5).
*Why:* the data sits only in that person's own account, and the extra step
mostly loses real people.

**D12. Alembic, the layer re-layout, pydantic-settings?**
*Recommended:* none of them. Add a schema version number, a migrate
command and a standard-library `settings.py` instead.
*Why:* each would cost days to weeks and add tooling, and the current
pieces already work and are tested on Postgres.

**D13. Decimal for money?**
*Recommended:* no. Keep floats, round at display, and test display
boundaries.
*Why:* Northwend shows and projects money but never moves it, and the change
would touch almost every module.

**D14. Encrypt TOTP secrets at rest?**
*Recommended:* only if adding the `cryptography` package is acceptable.
Otherwise leave them as they are, and treat database access as the thing to
protect.
*Why:* the key would sit in the same secrets store as the database URL, so
it guards a narrow case (a leaked backup).

**D15. How is an advisor's licence checked, and how often?**
*Recommended:* BrokerCheck or the SEC's IAPD lookup by CRD number. Record
the match, the source and the date at approval. Re-check yearly from a
reminder on Admin.
*Why:* the Terms promise that licences are checked, and right now there's
nothing to show for it.

**D16. A monthly budget, written down?**
*Recommended:* yes, as one table in the runbook: Render, Neon, Cloudflare
(free), Resend, Anthropic (with the console limit), market data, the
domain. Set the AI cap at about half the total, with alerts at 50% and 80%.
*Why:* free and paid by no one means every cost lands on the owner, and a
written ceiling is what makes the AI cap a real number.
