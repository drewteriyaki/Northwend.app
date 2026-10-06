# Northwend architecture

One page on how the app fits together (PLAN 1b.11, audit G10). For which file
holds what, read the file map in `CLAUDE.md` ("Where things live" and
"Gotchas"); it isn't copied here. Decisions are in `docs/adr/`, operations in
`docs/RUNBOOK.md`.

## The shape

- **One Streamlit script**, `dashboard.py`, runs top to bottom on every click.
  Each page's code is a file in `views/`, run in place by `_view("name")` as
  if it were written at that line (same globals, no imports).
- **Pure modules** do the sums and the data work (`perf.py`, `plans.py`,
  `income.py`, `checkin.py`, `auth.py`, ...). They don't import Streamlit, so
  tests, jobs and the command line use them directly.
- **One database**: SQLite locally, Postgres (Neon) on hosted copies.
  `portfolio.connect()` picks by the connection string; `pgcompat.py` turns
  the app's SQLite-style SQL into Postgres's. Settings come from the
  environment through `settings.py` (names in `.env.example`).

## A run of dashboard.py, top to bottom

1. **Fresh code and settings.** `codefresh.py` reloads changed modules after
   a deploy. `settings.database()` picks the database; `settings.hosted()`
   says whether this is a copy people use. Error handling
   (`friendly_errors.py`) and the AI spend counter (`ai_spend.py`) are set
   up. Page config and styles are drawn.
2. **Early stops.** Staging shows its banner. `MOVED_TO` set: only the "has
   moved" page (`hosting.py`). `settings.config_problem()`: a hosted copy
   without a Postgres database stops here, before any data is touched.
3. **Before sign-in.** `_login()` first handles links from emails:
   `?unsubscribe=` (`views/unsubscribe.py`, no sign-in), `?invite=` (a
   client's setup link), `?reset=` (a new password), `?confirm=` and
   `?email_change=`. Then a signed-in session, or the "stay signed in"
   cookie (`auth.session_user`), or the sign-in, sign-up and forgot-password
   forms. Sign-up asks for an invite code while gate L0 is off.
4. **The two-step gate.** Every way in ends at `_two_step_gate()`
   (`views/two_step.py`). Advisors and admins must pass it; others only if
   they turned it on. Until it's passed, only the code (or setup) page draws.
5. **Who, and whose data.** `LOGIN_ID` is who signed in. A changed password
   signs out open tabs (the password stamp). The account being looked at
   comes from the session or `?client=`, and is checked with
   `auth.can_view` on every run: your own, or a client linked to you as an
   advisor. Anything else falls back to your own. That account is
   `USER_ID`, and every per-account query filters on it. `CLIENT_MODE`,
   `CAN_MANAGE` and friends follow from it.
6. **Pages and menu.** `PAGES` (what this login can open) and `NAV` (the top
   bar) are built, minus any page whose feature is off (`flags.page_on`).
   `?page=` picks the page; old slugs are mapped (`OLD_SLUGS`).
7. **Agreement and email.** An account that hasn't agreed to the disclosures
   is asked once. An unconfirmed email is mentioned calmly.
8. **Views.** The `_view(...)` lines run in order: tools and windows first
   (clients, plan, checkin, fees, ...), then the header, live prices
   (`live_prices.py`, every minute while open), the holdings loaded for
   `USER_ID`, and the page itself (`dashboard_page`, `income`, `plan`,
   `assistant`, ...). `_view` skips a view whose feature is off
   (`flags.view_on`). Button callbacks run before the next run, so they can
   be defined anywhere; anything used while drawing must be defined above
   its first use.

## The data model, in about ten lines

- `users`: one row per login (password hash, email, advisor and admin
  flags, agreement and its time). Sessions in `login_sessions`, two-step in
  `two_step` (each authenticator key encrypted with `NORTHWEND_TOTP_KEY`, a
  host setting kept apart from the database; readable without it).
- `advisor_clients` links an advisor to a client (with the advisor's name
  for them). `advisor_notes`, `proposals`, `progress_reports`,
  `former_clients` are the advisor's records.
- `snapshots` > `positions` and `account_totals`: holdings as of a date, per
  account. Never the uploaded file, never more than an account number's last
  3 digits.
- `transactions` (activity), `value_log` (value at each visit).
- `plans` (one goal and a target mix per account), `investor_profiles`
  (answers), `user_prefs` (settings, the Monthly Walk's state), `money_out`,
  `contributions`.
- Shared market data, with no personal data: `price_history`, `daily_bars`,
  `intraday_bars`, `security_info`, `fund_top_holdings`, `news`.
- Every table that holds one account's data is listed in
  `admin.ACCOUNT_TABLES` (delete, export and the A/B matrix test use it).
- The schema is `schema.sql` and `schema_pg.sql`, kept in step. New columns
  on old tables are back-filled in `portfolio._ensure_schema`.

## Where jobs run

GitHub Actions on a schedule (`.github/workflows/scheduled-sync.yml`), against
the live database:
- prices every 15 minutes in market hours (`update_prices.py`, Finnhub);
- history, dividends and fund data nightly (`sync_history.py`, Yahoo);
- the advisors' Monday email (`weekly_email.py`);
- walk reminders daily, for those who asked (`checkin_email.py`).

Each job has a "Tell the admin it failed" step (`error_alerts.py`). The app
itself fetches prices only while a page is open. Tests run on every push
(`.github/workflows/tests.yml`), on SQLite and on a real Postgres.

## What the AI is sent

Every AI call, what it carries and what it never carries, is listed in
`docs/AI_PLAN.md` section 2 ("Today: every AI call in the code"). In short:
every prompt carries `advisor.GUARDRAILS` (a test pins every call); each
feature checks `_ai_status` first, counts with `_ai_record` only after a good
answer, and records cost with `ai_spend.note`. Screenshot reading sends the
image and is behind the `screenshot_ai` flag (off on the live copy).

## Where flags and gates are checked

All in `flags.py`, read from `NORTHWEND_FLAGS` and `NORTHWEND_GATES`
(everything off unless set):
- `_view()` skips a view a feature owns (`flags.view_on`), and `PAGES`/`NAV`
  drop its page (`flags.page_on`);
- a feature inside a view checks `flags.on("name")` where it's drawn (the
  walk in `views/checkin.py`, screenshot reading in
  `views/holdings_input.py`);
- a gate's effect on something already live checks `flags.gate(...)` (L0's
  invite codes in `auth.invite_only`);
- jobs check too (`checkin_email.py` sends nothing unless `walk` is on);
- Admin > System lists every gate and flag.

Tests check that every name in `flags.FEATURES` is checked somewhere, and
that no L4 exists.

## Limits, and when something goes wrong

Each kind of abuse has a limit next to the thing it guards: sign-in and
sign-up per address and per username, and email sends (`auth.py`), AI
allowances and the app-wide AI ceiling (`ai_usage.py`, `ai_spend.py`), and
how often one login reads uploaded files, saves holdings or activity and
builds ZIP or PDF downloads (`rate_limits.py`, checked through dashboard
`_limit_ok` / `_upload_ok`; an advisor in a client's account counts as the
advisor). They keep counts, never what was typed, uploaded or saved, and say
something calm when one is reached. Admin > System lists the upload and save limits.

If data may have been exposed, changed or lost, follow the RUNBOOK's
[incident and breach response](RUNBOOK.md#if-something-goes-wrong-incident-and-breach-response):
how to tell what happened, the first hour, who to tell and how fast, the
email to affected people, and the checklist afterwards.
