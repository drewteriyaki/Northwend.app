# Northwend security audit

Written October 5, 2026, against commit `ca362b2` (staging). It covers the
owner's hardening brief: every checkbox in Part 1 (1.1 to 1.10), every gap in
Part 2, and anything else found while reading the code. Nothing was fixed. The
fixes are planned in `docs/PLAN.md`.

How to read it:

- **Status.** *Confirmed*: a real issue. *Not an issue*: already handled, and
  the entry says how. *Partly*: some of it is handled and some is open.
  *Needs decision*: the owner has to choose before anyone fixes it.
- **Severity** uses the brief's scale. P0: fix before any more public use.
  P1: fix before leaving Streamlit Community Cloud. P2: fix during the
  migration. P3: hygiene. Where the code changes the brief's severity, the
  entry says why.
- References are `file:line` at `ca362b2`.
- **Revised Oct 5 for the owner's master brief** (two-sided: free education,
  flat-fee advisor seats, legal gates L0-L4). New entries: 1.2d, 1.6f,
  1.10f-h and 1.11 (payments). They are for things not built yet, so they
  aren't in the counts below. Each is a condition on its gate opening.

---

## Summary

| | Part 1 (45 checks) | Part 2 (12 gaps) | Extra findings (9) | Total |
|---|---|---|---|---|
| Not an issue | 11 | 1 | - | 12 |
| Confirmed | 6 | 2 | 9 | 17 |
| Partly | 22 | 9 | - | 31 |
| Needs decision | 6 | - | - | 6 |
| **Open items** | **34** | **11** | **9** | **54** |

Open items by severity:

| Severity | Part 1 | Part 2 | Extra | Total |
|---|---|---|---|---|
| P0 | 0 | 0 | 0 | **0** |
| P1 | 14 | 1 | 2 | **17** |
| P2 | 15 | 3 | 3 | **21** |
| P3 | 5 | 7 | 4 | **16** |

The overall picture: the core is in better shape than the brief assumed.
Sessions are random tokens stored hashed on the server. Passwords are salted
and stretched. All SQL is parameterised. Every page re-checks whose data it
shows, on every run. Uploads are deleted in a `finally` block. CSV exports
are escaped, and advisors have two-step sign-in. Most open items sit at the
edges: configuration that fails open, missing ceilings on cost and size,
missing headers on the app, backups, and privacy wording that promises more
than the code does.

### Open P0 and P1 items

| # | Item | Status | Sev |
|---|---|---|---|
| 1.5a | Secrets in git history: none, checked on the full history (141 commits, Oct 5) | Not an issue | - |
| 1.1c | Login throttling is per username only: nothing limits one address trying many usernames | Partly | P1 |
| 1.2a | Access checks are sound, but no app-level test tries another person's `?client=` id, and some helpers make the advisor filter optional | Partly | P1 |
| 1.2c | The advisor licence check is a manual BrokerCheck look. No evidence is kept and nothing re-checks it yearly | Partly | P1 |
| 1.3d | Screenshot reading sends the whole image (balances, account names and numbers) to the AI, and the AI sends back share counts and cost | Needs decision | P1 |
| 1.4b | "Percentages only" is held by tests, not by a type. The chat's memory tool asks the AI to keep "amounts" | Partly | P1 |
| 1.4c | AI limits are per account. Nothing caps the whole app's monthly spend, and the chat box has no length limit | Partly | P1 |
| 1.5b | Configuration fails open: without `PORTFOLIO_DB` a hosted copy runs on a local SQLite file, shows tracebacks, sends no alerts, and offers to read CSV files from the server's own disk | Confirmed | P1 |
| 1.6e | Backups are Neon's rolling window (about 6 hours). There is no scheduled copy and no tested restore | Confirmed | P1 |
| 1.7a | SPF, DKIM and DMARC on northwend.app couldn't be checked from here | Partly | P1 |
| 1.8b | The website has strict headers. The app has none: no frame-ancestors, HSTS or nosniff | Partly | P1 |
| 1.8c | Still on Streamlit Community Cloud. The Render move is coded (L4) and waits on owner steps | Confirmed | P1 |
| 1.9a | Market data is Finnhub's free tier plus yfinance. The terms for showing it to the public are unresolved | Needs decision | P1 |
| 1.10a | Terms and Privacy Policy are unpublished drafts with lawyer placeholders. The disclosures still name Streamlit Cloud as the host | Partly | P1 |
| 1.10b | Export and self-delete work. But a former client who deletes their account also deletes their old advisor's notes, proposals and reports | Needs decision | P1 |
| G5 | No cost ceiling: no written budget, no app-wide AI cap, no spend alerts | Confirmed | P1 |
| X3 | Privacy wording overstates. The app says "never balances" but saves holding values and cash. The website says the AI never sees dollar amounts or share counts, which screenshots break | Confirmed | P1 |
| X6 | A full copy of the database (the Neon branch kept from the precision change) sits outside the stated retention | Confirmed | P1 |
| 1.10h | Published copy says no advisor pays. It must be reworded (not removed) before the first paid seat | Confirmed | P1 at L1 |

---

## Part 1 - security checks

### 1.1 Authentication and sessions

**1.1a Session persistence - Not an issue (brief: P0).**
"Stay signed in" uses `secrets.token_urlsafe(32)` (256 random bits). Only a
SHA-256 of the token is stored. Each token expires after 30 days and is
looked up on the server every time (`auth.py:284-327`). Logging out deletes
the row (`auth.py:323-327`, `dashboard.py:1173-1196`). A password change
deletes every session (`auth.py:76-89`). An open tab also notices a password
change through a stamp of the password hash (`dashboard.py:1220-1227`).
Without "stay signed in", sign-in lives only in the server-side session.
One caveat is logged as extra finding X1: the cookie is written by
JavaScript, so it can't be `HttpOnly`.

**1.1b Password storage - Partly, P2 (brief: P0 for anything but argon2/bcrypt).**
PBKDF2-HMAC-SHA256 with a 16-byte random salt per password and 200,000
iterations, compared in constant time (`auth.py:24`, `auth.py:31-33`,
`auth.py:71`). PBKDF2 is a sound, standard choice, so this is not P0. But
200,000 is below today's usual advice for PBKDF2-SHA256 (about 600,000).
Fix: raise the count, and re-hash a password at its next successful sign-in.
That keeps the standard-library-only design. argon2 would add a dependency
for little gain.

**1.1c Login throttling - Partly, P1.**
Done: 5 wrong passwords lock a username for 15 minutes. Unknown usernames
are counted the same way, the error is the same for a wrong user or a wrong
password, and comparison is constant-time (`auth.py:233-271`). The two-step
code has its own lock (`two_step.py:131-170`).
Open:
- No limit per internet address on sign-in. One address can try one common
  password against many usernames. Sign-up and the email links already have
  per-address limits (`auth.py:418-492`, `auth.py:517-549`). Sign-in should
  have one too.
- An unknown username returns before any hashing (`auth.py:66-67`). The
  timing then shows whether an account exists. Fix: hash against a dummy
  salt.
- Sign-up says "There's already an account with this email"
  (`auth.py:483-486`). This is rate-limited and counted, so it's an accepted
  trade-off (P3).
- Anyone who knows a username can lock it for 15 minutes. That's the price
  of a username lock. An address limit softens it.

**1.1d Reset and invite links - Not an issue (brief: P1).**
All links are `token_urlsafe(32)`, stored only as SHA-256, and single-use.
A new link replaces the old one. Lifetimes: reset 60 minutes, confirm 3 days,
invite 7 days (`auth.py:330-352`, `auth.py:503-508`, `auth.py:651-676`,
`auth.py:901-919`). A reset link stops working if the account's email has
changed (`auth.py:667-676`). Invite spam is limited: one advisor can send 50
a day in total, 5 a day to one address, with a 2-minute gap
(`auth.py:552-589`). The invite email carries no figures
(`mailer.py:198-211`). A reset or setup link still goes through two-step
sign-in afterwards.

**1.1e Advisor two-step sign-in - Partly, P2 (brief: P1).**
Done: TOTP per RFC 6238, with replay blocked (`last_token_step`) and a lock
after wrong codes (`two_step.py:146-170`, `two_step.py:249-286`). The 8 backup codes are stored only
as hashes and each works once (`two_step.py:110-128`). The gate runs on every
full run, after any way of signing in, before any page is drawn
(`views/two_step.py:156-194`, `dashboard.py:1084-1094`). Advisors and admins
can't skip setup (`views/two_step.py:182-184`). Fragments and dialogs skip
the gate, but a session only reaches them after a full run has passed it.
Open:
- The TOTP secret is stored as plain text (`two_step.py:241-243`). Anyone
  with a copy of the database can make codes. Encrypting it with a key kept
  in the host's secrets is a small change.
  **Fixed Oct 6 (D14 approved; ROADMAP 1b.8b):** with `NORTHWEND_TOTP_KEY` set
  (a host setting, never in the database or the repo) each key is stored as
  `enc1:` + a Fernet token (`cryptography`; AES-128-CBC with HMAC-SHA256).
  Older readable keys are sealed at their owner's next good code, or all at
  once by `manage_users.py encrypt-two-step` (logged); comma-separated keys
  rotate (`--rotate`). A key that won't open matches no code (backup codes
  still work) and alerts the admin; Admin > System shows the key set or not
  and the counts. Without the setting (a local run, or a host not set up
  yet) keys stay readable, so it protects the live copy only once the owner
  sets it there and runs the command (RUNBOOK, "Two-step key").
  Tests: `tests/test_two_step_encryption.py`, `tests/test_postgres.py`.
- Backup codes are plain SHA-256 of about 40 bits each (`two_step.py:110-113`).
  That's fine against online guessing, which the lock covers, but weak
  against offline guessing from a stolen database. A slow hash would fix it.
  **Fixed Oct 6 (ROADMAP 1b.8):** PBKDF2, one salt per set.
- No app-level test shows the gate. Every AppTest that signs in an advisor
  sets `two_step_ok` itself (for example `tests/test_advisor_client.py:245`).
  Add one test that an advisor without it sees only the code page.

**1.1f Email verification before data is stored - Needs decision, P3 (brief: P2).**
An unconfirmed account can save holdings. The AI waits until the email is
confirmed (`ai_usage.py:23`, `ai_usage.py:54-66`). Holdings sit only in that
person's own account, so requiring confirmation first adds friction and
protects little. Recommendation: keep it as is, and delete self-made
accounts that are never confirmed after 30 days (see the retention decision
in PLAN.md).

**1.1g Session controls - Partly, P3.**
Done: logout ends the session on the server. Account shows how many devices
are signed in and offers "sign out other devices" (`auth.py:849-856`). The
password is asked again before deleting the account, changing the email,
changing the password, or turning two-step off (`admin.py:240-266`,
`views/account.py:255`, `views/account.py:270`, `two_step.py:289-318`).
Open: no password prompt before "Prepare my data" (`views/account.py:292`),
"Delete all my holdings" (`views/account.py:298-300`) or stopping sharing
with an advisor. There's no list of devices to revoke one by one. See also
X5: "sign out other devices" doesn't close tabs that are already open.

### 1.2 Authorization

**1.2a Object-level access checks - Partly, P1.**
The design is sound:
- `USER_ID`, whose data a page shows, is worked out on every run and checked
  with `auth.can_view` (own account, or an advisor's linked client). It's
  never taken from the address or the session as is (`dashboard.py:1236-1245`,
  `auth.py:1076-1084`).
- Advisor actions filter on both the advisor and the client
  (`advising.py:68-76`, `advising.py:177-258`; `proposals.py:62-104`).
- Private notes are visible only to the advisor who wrote them
  (`advising.py:92-100`).
- Ending a relationship removes the link, so `can_view` turns false at once
  (`advising.py:367-412`).
- Existing tests: two users never see each other's holdings
  (`tests/test_core.py:812`), the `can_view` rules (`tests/test_core.py:1082`,
  `tests/test_core.py:1109`), private notes (`tests/test_bug_pass.py:142`),
  messages go only to the advisor's own clients
  (`tests/test_advisor_basics.py:283`), and ending a relationship
  (`tests/test_advisor_tools.py:169-232`).

Open:
- No AppTest opens `?client=<someone else's id>` and checks the page falls
  back to the person's own account.
- No test runs the full matrix ("A cannot read, change or delete B's X") for
  every account table.
- Some helpers take `advisor_id=None` to mean "any advisor"
  (`advising.py:177-180`). The app always passes it today, but a new caller
  that forgets it would widen access. Make it required.

One difference from the brief: there is no "client accepts the invite" step.
An advisor creates the client's account and manages it from the start, by
design.

**1.2b Role checks on the server - Not an issue (brief: P1).**
Streamlit draws every page on the server. Nothing reaches the browser unless
Python code runs and draws it, so "hidden" means "not sent". Client mode
(`CLIENT_MODE`) is worked out from the database on every run
(`dashboard.py:1265-1280`). Every Admin action re-checks admin rights in the
database (`views/admin.py:20-29`). This would need re-doing in any future
API (see PLAN.md Phase 3).

**1.2c Advisor approval and licence check - Partly, P1.**
Done: asking for advisor access stores the firm and the CRD or licence
number (`auth.py:964-987`). The admin sees them with a "Check on BrokerCheck"
link and approves or declines; the person is emailed either way
(`views/admin.py:318-323`, `admin.py:94-120`). Until then the account is an
ordinary investor account with no client features. The pending "demo book"
is made-up data in memory, labelled "Example" and never written anywhere
(`advisor_demo.py:1-12`, `views/advisor_demo.py:94`).
Open:
- What was checked isn't recorded. The approval date is shown as "licence
  checked" (`views/admin.py:361-364`), but there's no CRD match or IAPD link
  saved with it.
- Nothing re-checks once a year.
- The Terms draft still has `[OWNER: describe how the check is done]`
  (`docs/legal/terms-of-use-DRAFT.md:154-155`).
*PLAN step 5 (built):* all three. The approval form records the source
(BrokerCheck or IAPD), the CRD matched and the day (`licence_check.py`,
`licence_checks`); Admin > Licence checks lists advisors due from 11 months
and flags them past 13 (`licence_check.licence_current` for the directory); the
nightly tidy job emails the admin a count, at most weekly; the Terms draft
describes the process.

**1.2d New resources from the master brief - Not built yet, P1 before L2 opens.**
The master brief (Oct 5) adds four resources: the advisor directory, intro
requests, consent records and advisor access logs. None exist today. When
they're built, each joins the cross-user matrix test (1.2a), plus three
rules the brief names:
- **A lapsed seat cannot write.** It keeps read and export for the grace
  period and nothing else (brief §4.5). Today there are no seats.
- **Revoking sharing ends access within one request.** This already holds
  for "stop sharing" and "end relationship": they delete the
  `advisor_clients` link, and `can_view` reads it on every run
  (`advising.py:367-412`, `dashboard.py:1236-1245`). The same must hold for
  the new consent record. Write it as a test from the start: revoke, then
  the very next run as the advisor falls back to their own account.
- **Every advisor access to a client's data is logged and shown to the
  client** (brief §4.3.5). Nothing logs advisor access today. The natural
  place is where `USER_ID` switches to a client (`dashboard.py:1236-1245`):
  one row per page open, holding who, which client, which page and when.
  Never figures.

One difference from today, which the brief changes on purpose: an advisor
now creates or invites a client and manages them from the start (1.2a). The
brief adds a second way in, where the person picks the advisor and opts in
to full sharing in two steps. Both ways need the consent record.

### 1.3 File uploads and "read and delete"

**1.3a Deletion guaranteed - Not an issue (brief: P0).**
A positions or activity CSV is written to a private temp folder, which
`shutil.rmtree` removes in a `finally` block (`portfolio.py:675-686`,
`views/holdings_input.py:1113-1115`). Screenshots and client lists are read
from memory only (`views/holdings_input.py:380-392`,
`views/clients.py:780`). No log line prints a file's contents.
Small caveat (P3): Streamlit's uploader keeps the bytes in server memory
until the window closes or the widget is reset. The screenshot path resets
it (`views/holdings_input.py:391`), but the CSV path doesn't.

**1.3b Limits and validation - Confirmed, P2 (brief: P1).**
- No `server.maxUploadSize` in `.streamlit/config.toml` or `render.yaml`, so
  Streamlit's default of 200 MB applies.
- A positions or activity CSV, and pasted text, have no size or row limit
  (`csv_import.py:171-184`). The client-list CSV does: 500 KB and 200 rows
  (`client_csv.py:31-32`).
- Screenshots: at most 5 images of 5 MB each, but the check runs after the
  upload, and the type is judged from the file name only. GIF is accepted
  although the message says PNG, JPG or WEBP (`screenshot_read.py:23-62`).
- Images are never decoded on the server (they're sent to the API as they
  are), so a decompression bomb doesn't apply.

P2 rather than P1: one person can only slow their own session. But the fix
is a config line and a row cap, so it belongs in Phase 0.

**1.3c CSV formula injection - Not an issue (brief: P1).**
Every CSV the app makes goes through `export.csv_cell`. It quotes cells that
start with `= + - @`, tab, CR, LF, or their full-width forms
(`export.py:95-114`). That covers Holdings, Accounts, Activity, Income, the
ZIP export and the client-list "needs a look" file (`client_csv.py:190-198`).
Streamlit's own table "Download as CSV" is hidden. Tested in
`tests/test_bug_pass.py`.

**1.3d Screenshot reading vs. the AI principle - Needs decision, P1.**
What the model sees today: the whole image (`screenshot_read.py:117-146`),
which means every balance, gain, account name and account number on the
screen. The prompt then asks it to return share counts, total cost and
average cost (`screenshot_read.py:29-51`). The answer is re-checked
(`screenshot_read.clean`), so only ticker-shaped symbols and numbers are
kept. But the model has already seen everything.

The disclosures say this honestly (`disclosures.py:221-225`). It's opt-in
behind a checkbox (`views/holdings_input.py:368-369`). But:
- the website says "The AI sees percentages. Never dollar amounts, share
  counts, account names or numbers." with no exception
  (`website/templates/home.html:133`);
- the owner's own rule from Oct 5 says "any feature that reads an uploaded
  document parses it locally and strips figures before anything reaches the
  AI" (`ROADMAP.md:1036-1037`).

Options and a recommendation are in PLAN.md, Decision D1.

### 1.4 The AI guide (Ask Northwend)

**1.4a Prompt injection - Partly, P2 (brief: P1).**
Done:
- Text from users or files is flattened to one short line before it goes
  into the prompt, so it can't start a section of its own
  (`advisor.py:341-345`; tested in `tests/test_bug_pass.py:347-361`).
- The prompt says this text is data, never instructions (`advisor.py:406-410`).
- The guardrails come first and say they outrank anything later
  (`advisor.py:92-142`).
- The model's only actions are two tools that write the person's own
  profile (fixed choices, checked in `advisor.py:285-316`) and its own notes
  (at most 1,500 characters, `advisor.py:319-330`). It can't touch anyone
  else's data or send anything.
- Advisor notes never go into prompts.

Open: the notes are free text the model writes and reads back in every later
conversation (`advisor.py:425-440`). A one-time injection could persist, but
only in that person's own guide. Clear sections (for example tags around
holdings and notes) would make the data boundary plainer.

**1.4b "Percentages only" enforced in code - Partly, P1.**
Done: `portfolio_summary` builds the holdings text from percentages, yield,
beta and P/E only (`advisor.py:348-381`). Tests check that no `$`, no account
name and no fixture dollar value appears (`tests/test_core.py:914-924`), and
the same for meeting prep and the plan PDF (`tests/test_core.py:1553`,
`tests/test_core.py:2662`). Every AI call site is pinned
(`tests/test_legal_guardrails.py:308`).
Open:
- It's a convention, not a type. A fund's name comes from the person's file
  as free text (up to 80 characters), so it could carry anything.
- The memory tool's own instruction asks the model to keep "specifics behind
  their goals (dates, amounts, life events)" (`advisor.py:430-433`). Dollar
  figures someone types in chat are kept and sent back in every later
  conversation. Typing them is the person's choice, but asking the model to
  keep them goes against the principle.
- "Let AI guess the columns" sends column names (`csv_import.py:446-478`). A
  broker that puts an account number in a header would send it.
- Screenshots: see 1.3d.

**1.4c AI allowances and a spend ceiling - Partly, P1.**
Done: monthly allowances per account and kind, counted in the database with
one atomic upsert (`ai_usage.py:20`, `ai_usage.py:93-99`), only after a
successful answer. Advisors get 5 times as much. AI waits for a confirmed
email.
Open:
- No app-wide ceiling. Total exposure grows with every confirmed account.
  There's no budget alert either.
- The chat box has no length limit (`views/assistant.py:114`). A reply can
  use up to 16,000 output tokens with up to 4 tool rounds
  (`advisor.py:21-23`), and a conversation may run 40 messages
  (`dashboard.py:2045`). One long paste per message can cost far more than
  the allowance suggests.
- The allowance is checked before the call and counted after, so a few
  parallel tabs can go slightly over. Minor.

Fix: a spend limit in the Anthropic console (no code), an app-wide monthly
count with a hard stop, alerts at 50% and 80%, and `max_chars` on the chat.

**1.4d Output rendering - Not an issue (brief: P2).**
Answers are drawn with `st.markdown` and `st.write_stream`, without
`unsafe_allow_html` (`views/assistant.py:93`, `views/assistant.py:149`).
Streamlit escapes the HTML.

**1.4e Logging - Not an issue (brief: P2).**
No prompt or answer is logged. A failed request logs its kind and the first
300 characters of the API's error (`ai_usage.py:159-163`). That error text
comes from the API and doesn't repeat the prompt.

### 1.5 Secrets and configuration

**1.5a No secrets in the repo - Not an issue (checked on the full history).**
`.env`, `.streamlit/secrets.toml` and `portfolio.db` are git-ignored
(`.gitignore`). Searching every patch in the 94 commits available found no
key-shaped strings. The only hits were test placeholders such as
`postgresql://u:pw@ep-x.neon.tech/db`. No secret file was ever added; only
`.env.example`, which is empty.
**Full history checked (Oct 5).** After fetching the whole history (141
commits), no file like `.env`, `secrets.toml` or a key file was ever added,
and no Anthropic, Resend, AWS, GitHub or database-password strings appear in
any patch. The only key-like value is the RFC 6238 test secret in the
two-step tests. Nothing to rotate. Still worth turning on GitHub secret
scanning and push protection so it stays that way.

**1.5b One configuration module - Confirmed, P1 (fails open).**
Settings are read in 9 files, from `.env` or the environment
(`dashboard.py:65-69`, `dashboard.py:1995-2004`, `mailer.py:30-31`,
`admin.py:45-48`, `error_alerts.py:52`, `update_prices.py:66`,
`weekly_email.py:109-110`, `manage_users.py:322`, `hosting.py`).
The real problem is what happens when one is missing:
- Without `PORTFOLIO_DB` the app quietly uses `portfolio.db` beside the code
  (`dashboard.py:65`).
- "Hosted" is inferred from "the database is Postgres". So that same
  misconfigured copy also:
  - shows a "path to a CSV on this machine" box that reads files from the
    server's own disk (`views/holdings_input.py:1107-1115`);
  - shows tracebacks on screen (`dashboard.py:84-85`);
  - sends no error alerts (`dashboard.py:87`).

A mistyped secret name on Render would produce exactly this. Fix: a small
standard-library `settings.py` that knows it's hosted (Render's `RENDER`,
Community Cloud's `/mount/src`, or `NORTHWEND_ENV`) and refuses to start
without a Postgres DSN. pydantic-settings isn't needed.

**1.5c Separate credentials per environment - Partly, P2.**
Staging has its own Streamlit app and Neon database (CLAUDE.md). The
scheduled jobs hold the production connection string in GitHub secrets
(`.github/workflows/scheduled-sync.yml:12-20`), so the staging database gets
no price updates. Whether staging shares the production Anthropic, Resend
and Finnhub keys can't be seen from the code. Recommendation: separate
Anthropic workspaces with their own spend limits, and a staging Resend key
limited to test addresses, or `MAIL_DRY_RUN`.

### 1.6 Database

**1.6a SQL built by string formatting - Not an issue (brief: P0).**
Every value is a bound parameter. The f-strings found only insert fixed
table or column names from constants, or a list of `?` marks. Examples:
`admin.py:226-233`, `export.py:135-137`, `auth.py:558-564`,
`portfolio.py:232-237`, `asset_classes.py:162-180`. The Postgres
translation leaves quoted text alone (`pgcompat.py:21-63`), and that's
tested.

**1.6b Connections - Partly, P2.**
One `psycopg_pool` pool per process, at most 5 connections
(`pgcompat.py:229-236`). Broken connections are dropped when returned
(`pgcompat.py:185-207`), but there's no check when one is taken out, so the
first query after Neon closes an idle connection can fail. Fix: pass
`check=ConnectionPool.check_connection`. `sslmode=require` isn't enforced in
code; it relies on the Neon string. Use Neon's pooled endpoint if the app
ever runs more than one process.

**1.6c Least privilege - Confirmed, P2 (brief: P1).**
The app sets up and upgrades its own schema at first connect: it creates
tables, adds columns and creates indexes (`portfolio.py:170-260`,
`portfolio.py:368-391`). So the app's database role must own the schema and
can drop tables. The GitHub jobs use the same role. P2 because it only
matters after a separate break-in, and it needs the migration step in 1.6d
first.

**1.6d Migrations - Needs decision, P2 (brief: P1, Alembic).**
Today: two schema files kept in step, plus a back-fill list run at start
(`portfolio.py:170-260`). It's idempotent. The CI Postgres job tests an
upgrade from the Sep 30 schema (`tests/test_postgres.py`). There's no version
number and no way back. Recommendation in PLAN.md: keep this approach, add a
`schema_version` row and a `northwend-migrate` command run at deploy. Not
Alembic.

**1.6e Backups - Confirmed, P1.**
Backups are Neon's rolling restore window, which the disclosures put at
"about 6 hours" (`disclosures.py:154-156`). There's no scheduled copy and no
restore that has ever been tested. Going to 30 days, as the brief asks,
would break the current promise that deleted data is gone after about 6
hours. Decision D6 in PLAN.md.

**1.6f Data minimisation - Partly, P3 (brief: P2).**
Done: account numbers are cut to their last 3 digits before anything is
compared or saved (`portfolio.py:546-549`), and older rows were cleaned once
at start (`portfolio.py:288-320`). Full numbers live only in memory during
the review.
Open:
- The uploaded file's name is kept as `snapshots.source_file`
  (`portfolio.py:689-693`). Some brokers put the account number in the file
  name.
- Values are stored as plain numbers (`positions.market_value`,
  `account_totals.cash_value`; `schema_pg.sql:51-90`).

Encrypting values in the app: recommended against. The key would live beside
the app, a leak of the database usually comes with a leak of the app, and it
would break every SQL sum the pages use. See X3 for wording that
overstates what's kept.

**1.6g Money math - Needs decision, P3 (brief: P2).**
All amounts are floats (`DOUBLE PRECISION`). Northwend shows and projects
money; it never moves it. Rounding happens at display. Recommendation: keep
floats, and add display-boundary tests where a figure is shown in two
places. Converting to `Decimal` would touch nearly every module for little
benefit.

**1.6f Append-only records - Not built yet, P1 before L2 opens (master brief §7).**
Consent records and advisor access logs must be append-only. In order of
strength:
- In code, the module exposes only insert and read, and a test checks that
  no `UPDATE` or `DELETE` against those tables appears anywhere outside the
  retention job.
- In Postgres, the app's role gets `INSERT, SELECT` only on the two tables.
  This needs the separate roles in PLAN Phase 2.
- A trigger rejects `UPDATE` and `DELETE`, and the retention job runs under
  the owner role.

Deleting an account (`admin.delete_account`) must not remove these rows
while the retention period runs. They hold ids and timestamps, never
figures, so keeping them doesn't break "deleted means deleted" for
holdings. The Privacy Policy has to say so (1.10g).

### 1.7 Email (Resend)

**1.7a SPF, DKIM, DMARC - Partly (unverified), P1.**
Resend only sends for a verified domain, which needs its SPF and DKIM
records, and mail is going out from hello@northwend.app (ROADMAP L5). A
DMARC record is unknown. DNS couldn't be queried from this session. Check
with `dig TXT _dmarc.northwend.app` and add `v=DMARC1; p=quarantine` (or
stricter) if it's missing.

**1.7b No figures in email, in code - Partly, P2 (brief: P1).**
Every template takes only names, links, a period label and counts
(`mailer.py:112-322`). The Monday email is counts only (`mailer.py:186-195`).
Several tests check for no `$` (`tests/test_advisor_basics.py:250`,
`tests/test_advisor_basics.py:457`, `tests/test_advisor_client.py:78`,
`tests/test_advisor_tools.py:273`, `tests/test_advisor_tools.py:526`). There
is no single test that renders every template in `mailer.py`. A new template
could slip through. Add one that calls every public function with sample
inputs and checks for no currency or digit groups.

**1.7c Unsubscribe - Partly, P2 (brief: P1).**
The only non-transactional email today, the advisors' Monday summary, says
how to turn it off in the app (`mailer.py:189-191`). It has no one-click
link and no `List-Unsubscribe` header. The Monthly Walk reminder (ROADMAP
R1, next up) will be the first email to investors that isn't about their
account. It must ship with both.

**1.7d Resend webhooks - Not an issue.**
None are used (Streamlit can't receive them). Bounces aren't handled. That's
fine at this volume. Note for later.

### 1.8 Web layer, headers, hosting

**1.8a Error details hidden - Partly, P2 (brief: P1).**
`friendly_errors.py` replaces the traceback with "Something went wrong" and
a code, and emails the admin (`friendly_errors.py:27-79`). Open:
- `client.showErrorDetails` isn't set, so Streamlit's default (full details)
  is the fallback if the hook ever misses. It reaches into Streamlit's
  private API for button callbacks (`friendly_errors.py:46-54`).
- Details show on screen whenever the database isn't Postgres
  (`dashboard.py:84-85`; see 1.5b).
- Three save paths show the raw database error to the person (X4).

Fix: set `STREAMLIT_CLIENT_SHOW_ERROR_DETAILS` on the hosts, keyed to "hosted"
rather than to the database type.

**1.8b Security headers - Partly, P1.**
The website is done: a strict CSP with no scripts, `frame-ancestors 'none'`,
HSTS, nosniff, a referrer policy and a permissions policy
(`website/public/_headers`). The app sends none of these. Streamlit can't set
them, and Render can't add response headers to a web service (as far as I
know, only to static sites; worth confirming). A logged-in finance app that
can be framed is a clickjacking risk. Fix: put Cloudflare's proxy in front of
app.northwend.app (websockets work through it) with a rule that adds
`frame-ancestors 'none'` / `X-Frame-Options: DENY`, HSTS, nosniff, a
referrer policy and a permissions policy. A full CSP for Streamlit isn't
practical, because of its inline scripts and styles.

**1.8c Streamlit Community Cloud - Confirmed, P1 (being fixed).**
The live app is on Community Cloud. Its secrets hold the database owner's
connection string and every API key. The move is coded: `render.yaml`
(Starter, always on, health check, secrets not stored) and `hosting.py`
(real visitor address, "has moved" page). It waits on the owner's steps
(`ROADMAP.md:178-196`). Also missing from `render.yaml`: `NORTHWEND_ADMINS`,
`ALERT_EMAIL`, `APP_URL`, `NORTHWEND_ENV`, and the upload and error-details
settings.

**1.8d Abuse controls - Partly, P2.**
Done: sign-up has a hidden field, a too-fast check, 3 accounts per address
per day, 10 tries per address per hour and 20 accounts app-wide per hour
(`auth.py:418-492`). Email links have send limits. AI has allowances.
Advisors can check at most 200 new addresses a day (`auth.py:606-631`).
~~Open: no limit on how often someone uploads or saves.~~ **Done (Oct 6):**
`rate_limits.py` limits each login (an advisor in a client's account counts
as the advisor): files read 30 an hour and 200 a day, saves 60 and 300, ZIP
and PDF downloads built 30 and 150. Over a limit the page says "You've done
a lot of that in a short time - please try again in a little while." and
nothing is read, saved or built. Counts only, in `email_sends`, for a day;
Admin > System lists the numbers. Still open: nothing. A disposable-email
check isn't worth it now.

**1.8e Dependency hygiene - Partly, P3.**
Direct dependencies are pinned in `requirements.txt` and `pyproject.toml`
(a test keeps them equal). Python is pinned on Render (3.13.7) and in CI
(3.13). Missing: a lock on indirect dependencies, `pip-audit` in CI,
Dependabot, and Actions pinned by SHA (they use `@v4` and `@v5`).

### 1.9 Market data

**1.9a Terms and sources - Needs decision, P1.**
- Live prices: Finnhub's free tier first, then Yahoo through yfinance; crypto
  and mutual funds from Yahoo (`live_prices.py:1-22`).
- History, dividends, fund details and fund top-10s: yfinance
  (`sync_history.py`, `fund_holdings.py`).
- Prices are cached and shared across accounts in Postgres (`price_history`,
  `daily_bars`, `security_info`, `fund_top_holdings`). The minute quotes are
  trimmed after a week (`live_prices.py:197-214`).
- Pages say prices "may be delayed" (`tests/test_legal_guardrails.py:231`).

Open:
- Yahoo's terms don't allow this kind of use.
- Finnhub's free plan limits showing data to the public; check the current
  terms.
- No "as of" marker per stale price.
- No written statement of which source is primary.

Decision D4 in PLAN.md.

**1.9b Where the nightly job runs - Not an issue (brief: P2).**
GitHub Actions on a schedule: prices every 15 minutes in market hours,
history nightly, and the advisors' Monday email. Each job emails the admin
if it fails (`.github/workflows/scheduled-sync.yml`). The app only fetches
while someone has a page open. Caveats are logged as X9.

### 1.10 Privacy and legal

**1.10a Published Privacy Policy and Terms - Partly, P1.**
The in-app "About and disclosures" is live and is also the website's About
page (`disclosures.py`, `website/build.py`). The Terms, Privacy Policy and
advisor security page are drafts with `[LAWYER]` and `[OWNER]` placeholders
(`docs/legal/`). The disclosures still say "Streamlit Community Cloud hosts
the app" (`disclosures.py:191`), which must change at the Render move.

**1.10b Deletion, export, and the advisor split - Needs decision, P1.**
Done:
- Export everything as a ZIP (`export.py`, Account page). An advisor can
  export a client's record (`export.client_record_zip`).
- Deleting your own account is immediate, after your password
  (`admin.py:240-266`). Advisors who still have clients, and managed
  clients, must ask (`admin.py:255-264`).
- Ending a relationship keeps the advisor's own notes, proposals and reports
  (`advising.py:367-412`, `admin.py:38-40`).

The gap: after a client stops sharing, they can delete their own account.
That call passes no `keep_records_of` (`admin.py:265`), so it deletes the
former advisor's notes, proposals, reports and `former_clients` row too
(`admin.py:26-37`, `admin.py:226-231`). `advising.py:193-199` says these
records are kept for the advisor's record-keeping duties. Which side wins is
a legal call (Decision D7). Either way the Privacy Policy should say it.

**1.10c 18+ and US residency - Partly, P2 (brief: P1).**
An "I'm 18 or older" box is required at sign-up and at the setup link
(`dashboard.py:732`, `dashboard.py:838`, `auth.py:199-205`). It's recorded as
part of the agreement (`terms_version` plus `terms_accepted_at`,
`auth.py:208-222`), not as its own field. US residency isn't asked; the
Terms draft says US only, with an `[OWNER: confirm]`
(`docs/legal/terms-of-use-DRAFT.md:32`). Decision D10.

**1.10d Written retention schedule - Partly, P2.**
Much is already in code: sign-up and email-send counts are kept 1 day
(`auth.py:455`, `auth.py:524`), minute prices 1 week, sessions 30 days, and
links expire. It isn't written in one place. Some things have no rule:
`error_events`, `csv_layouts`, `news`, never-confirmed accounts, and host
logs. Proposed schedule: Decision D5.

**1.10e Incident response page - Confirmed, P2.**
None in the repo. There's no way to sign everyone out at once: deleting
`login_sessions` doesn't close tabs that are already open (X5). The tools
that exist: `manage_users.py reset-two-step`, password resets, Admin >
System. The advisor security draft promises breach notification
(`docs/legal/security-for-advisors-DRAFT.md:130-137`) without a procedure
behind it.
**Update (Oct 6):** the procedure is written: `docs/RUNBOOK.md`, "If something
goes wrong: incident and breach response" (how to tell what happened, the
first hour, who to tell and how fast, the email to affected people, the
checklist afterwards; legal deadlines marked "check with a lawyer"). "Sign
everyone out" exists since 1b.2 (X5).

**1.10f Advisor agreement and directory disclosures - Not built yet, P1 before L1/L2 (master brief §7).**
To add to the legal checklist:
- The advisor agreement text (gate L1). Today the advisor accepts the same
  disclosures as everyone, plus the request form (`auth.py:964-987`).
- The directory and intro copy (gate L2), including the standing line that
  advice is the advisor's, not Northwend's.
- The two-step consent text. Record it word for word with the consent, as
  the brief asks.

**1.10g Retention for consent and access logs - Needs decision.**
The brief's default is seven years, or whatever the lawyer specifies. It
goes into Decision D5's table as two new rows, and into the Privacy Policy.

**1.10h Published copy says "paid by no one" - Confirmed, P1 the day L1 opens.**
Today the disclosures, the website and the legal drafts say no advisor
pays. That stays true while seats are free beta seats (brief §4.5). The
copy has to change before the first paid seat. The brief says "never remove
a disclosure", so it should be reworded, not removed. Each place is listed
in `docs/LEGAL_GATES.md`.

### 1.11 Payments (new in the master brief)

None of this is built. It's listed so billing starts with these in place,
behind gate L1, after hosting has moved (PLAN step 4).

**1.11a Keys in config only.** Stripe's secret and webhook keys come from
the host's secret store through `settings.py` (PLAN Phase 0 item 2). Staging
uses test-mode keys only. A test fails if a live key prefix (`sk_live_`,
`rk_live_`) is found in the repo.

**1.11b Webhook signature verification.** Every webhook is checked with
Stripe's library against the signing secret before anything is read.
Anything else gets a 400 and is logged by type only.

**1.11c Idempotency.** A `stripe_events` table keyed on the event id. An
event that's already been handled is acknowledged and skipped. Outgoing API
calls carry idempotency keys.

**1.11d No card data, ever.** Checkout and the customer portal are hosted by
Stripe. The database keeps the customer and subscription ids, the seat
status and dates, and nothing else. Error reports (`error_alerts`) never
include a webhook body.

**1.11e Daily reconciliation.** A scheduled job compares Stripe's
subscription status with each local seat and emails the admin, with counts
only, when they differ. Like every job, it gets its own "Tell the admin it
failed" step.

**1.11f Where the webhook lands.** Streamlit can't receive a POST. The
webhook needs a small separate endpoint on Render (a tiny Starlette or
FastAPI app sharing the database), or the daily job polling Stripe instead
of webhooks. That's a decision (PLAN, decisions). This is the first piece
of the "second way in" that PLAN Phase 3 warned about. Keep it to one route
that only writes seat status.

**1.11g The billing module has no usage component.** A test checks that the
billing code never reads client counts or intro counts (brief §4.5).

---

## Part 2 - planning gaps

**G1 Test strategy - Partly, P2.**
708 tests in 27 files, run on SQLite and on a real Postgres 16 in CI. The
calculations have their own tests: total return, money going out, fees,
overlap, stress, next deposit, cash check, employer match. Made-up broker
files for Schwab, Fidelity, Vanguard, Robinhood, E*Trade and an odd layout
are in `tests/fixtures/brokers/`. Principle tests exist for AI prompts, fund
kinds versus tickers, page query caps and calm copy.
Missing: the gate and `?client=` AppTests (1.1e, 1.2a), an all-templates
email test (1.7b), more broker layouts (Merrill, Interactive Brokers,
Webull, SoFi, Public, Ally, M1), and a coverage number to watch.

**G2 Staging - Not an issue.**
A `staging` branch with its own Streamlit app, Neon database and a "Staging
copy" banner. `main` takes only commits whose tests passed (CLAUDE.md;
ROADMAP L3b). One gap: the scheduled jobs don't update staging's prices
(X9).

**G3 CI - Partly, P3.**
Unit and Postgres tests run on every push, and `main` is protected. No lint,
no dependency audit, no secret scan. A type-checker would cost more than it
returns on this codebase today.

**G4 Observability - Partly, P2.**
Done: app errors and failed jobs email the admin, at most once an hour per
kind, with no personal data (`error_alerts.py`). Admin > System lists them.
Missing:
- an outside uptime check of the app and the website;
- an alert when AI use is climbing;
- a short daily or weekly count (sign-ups, active accounts, AI use, job
  runs) sent to the owner.

**G5 Cost ceiling - Confirmed, P1.**
No written budget. Per-account AI allowances exist, but no app-wide cap or
alert (1.4c). The Render plan, Neon plan and any data plan aren't written
down anywhere as a monthly total.

**G6 Bus factor - Confirmed, P2.**
CLAUDE.md is a good guide for developers. There's no runbook for deploying,
restoring, rotating keys, signing everyone out, or shutting down cleanly with
an export for every user.
Master brief addition: the runbook also lists the owner-side prerequisites
for gated features: a business entity, and insurance (errors and omissions,
cyber). They aren't code. A deploy that turns on a gate checks them off
first (`docs/LEGAL_GATES.md`).

**G7 Support and status - Partly, P3.**
support@northwend.app exists and is in the disclosures. There's no status
page.

**G8 Data correctness - Partly, P3.**
Pages say prices "may be delayed". A missing price is said plainly. There's
no per-holding "as of" or confidence marker, and no "report a wrong price".

**G9 Accessibility - Partly, P3.**
Much is done: AA contrast in both themes, screen-reader labels, lists for
stat rows, less motion when asked (ROADMAP Polish; `tests/test_calm_pages.py`
`test_screen_readers`). Tap-target size on phones hasn't been measured.

**G10 Architecture docs - Partly, P3.**
CLAUDE.md's "Where things live" and "Gotchas" serve as the architecture map.
ROADMAP records the decisions with dates. There are no ADRs. A one-page
ARCHITECTURE.md that points to CLAUDE.md would help a new reader.

**G11 Changelog and versioning - Partly, P3.**
Admin > System shows the running commit (`hosting.version`). The disclosures
show a one-time notice when they change. ROADMAP's Done list is a developer
changelog. There's no "what's new" for users. Rollback today is a revert
pushed through staging. Render can also roll back to an earlier deploy.

**G12 Performance budget - Partly, P3.**
Query counts per page are capped by a test (`tests/test_page_queries.py`),
and sections that change on their own are fragments. Phone load time isn't
measured.

---

## Extra findings (not in the brief)

**X1 The sign-in cookie isn't HttpOnly - Confirmed, P2.**
Streamlit can read cookies but not set them, so the page sets `pt_session`
with JavaScript (`dashboard.py:639-649`). It's `SameSite=Lax` and `Secure`
on https, but any script injected into the page could read it. The app draws
raw HTML in about 60 places. The ones checked escape the person's text with
`html.escape`, but nothing tests that every one does. Fixes: a test that
looks for raw HTML calls given unescaped values, and (only if the app
leaves Streamlit) an HttpOnly cookie set by the server.

**X2 Admin can sign in as accounts without an email - Confirmed, P2.**
For an account with no email (one an advisor or admin made), Admin can set a
temporary password and is shown it (`views/admin.py:73-80`,
`views/admin.py:379-384`). That's a way into that person's holdings. The
disclosures say the person who runs Northwend sees login details, "not your
holdings" (`disclosures.py:149-153`). No admin action is logged. Fix: an
append-only admin action log, and disclosure wording that names this
recovery path.

**X3 Privacy wording promises more than the code does - Confirmed, P1.**
- The app says "Only symbols, share counts and cost are saved - never
  balances" and "Not kept: ... balances and gains" (`dashboard.py:89-92`).
  In fact the file's own value per holding and the cash balance are saved
  (`csv_import.py:404-414`; checked on the Fidelity fixture: market value
  1861.5 and cash 1234.56 saved). The Privacy draft has it right ("symbols,
  share counts, cost, value", `docs/legal/privacy-policy-DRAFT.md:48`).
- The website's AI claim ignores screenshots (1.3d).
- The chat's memory asks for amounts (1.4b).

Northwend's trust rests on these lines, so P1.

**X4 Raw database errors shown on save - Confirmed, P3.**
`views/holdings_input.py:488`, `:513` and `:972` show
`f"... nothing was changed: {exc}"`. A Postgres error can include SQL and
the row's values (the person's own). This breaks the "never raw error text"
rule in CLAUDE.md.

**X5 Open tabs survive "sign out other devices" - Confirmed, P2.**
`auth.end_other_sessions` (`auth.py:849-856`) and an admin's reset delete the
stored sessions. But a tab that's already open keeps its sign-in in server
memory until it reloads. Only a password change or a two-step change closes
it (`dashboard.py:1220-1227`, `views/two_step.py:176-182`). For an incident
you need a "sign out everyone now" switch: a session generation number
checked on every run.

**X6 A full copy of the data outside the retention promise - Confirmed, P1.**
ROADMAP item 5 asks the owner to delete the Neon backup branch from the
precision change. It is "a full copy of the data the retention line doesn't
cover" (`ROADMAP.md:93-94`). Until it's deleted, "deleted data is gone after
about 6 hours" isn't true. This is a 2-minute owner task.

**X7 Finnhub key in the request URL - Confirmed, P3.**
`update_prices.py:89` puts `token=` in the query string, which proxies and
logs may keep. Finnhub also accepts the `X-Finnhub-Token` header.

**X8 The devcontainer turns off XSRF and CORS - Confirmed, P3.**
`.devcontainer/devcontainer.json:22` runs Streamlit with
`--server.enableXsrfProtection false --server.enableCORS false`. It's only
for Codespaces, but it shouldn't be copied to a host. Remove the flags or
add a comment saying why they're there.

**X9 Scheduled jobs: credentials and reliability - Confirmed, P3.**
- The jobs hold the production owner connection string in GitHub secrets.
- Staging's database gets no price updates.
- GitHub may delay scheduled runs under load. In a public repository it
  turns schedules off after 60 days without activity.
- Actions are pinned by tag, not SHA.

None of this is urgent. It goes in the runbook, and a narrower database role
for the jobs comes with 1.6c.

---

## Checked and fine (worth knowing)

- XSRF protection is Streamlit's default and isn't turned off on any host
  (only in the devcontainer, X8).
- `csv_layouts` is shared across accounts but holds only column-name
  fingerprints and indexes (`schema_pg.sql:468-475`).
- A reset or setup link still goes through two-step sign-in.
- Admin rights from `NORTHWEND_ADMINS` need a confirmed email for a
  self-made account (`admin.py:51-56`), so nobody can claim a listed name by
  signing up with it.
- Weekly emails go only to confirmed addresses and say counts only.
- Account deletion covers every table with account data. A test makes each
  new table choose (`admin.ACCOUNT_TABLES`, `export.OWN`).
