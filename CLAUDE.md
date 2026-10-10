# Northwend (portfolio-tracker)

A Streamlit portfolio app: people bring holdings from any brokerage (CSV, paste,
screenshots, by hand, or percentages only) and get live values, charts, a plan,
income and an AI guide with the app's name ("Ask Northwend"; was Waypoint / Sage). Advisors can manage clients.
Live on Streamlit Community Cloud with Neon Postgres; locally it runs on SQLite.

## Working rules
- `ROADMAP.md` is the plan. Work items in order (or the one named), tick them
  `[x]` with a short note in the same commit. The current order is the owner's
  direction update `docs/DIRECTION_2026-10-09.md` (ticked in `docs/PLAN.md`, "The
  current order"): advisor workspace seats (gate L1a) open without a lawyer; the
  directory and anything connecting a person to an advisor (L2 / L1b) wait for a
  scoped opinion; never matching or ranking advisors, never analytics used to pick one.
- **Always ask "Commit and push?" before committing or pushing.** Every push is approved.
- **Staging first.** Commit on the `staging` branch and push it; the staging app
  (its own Streamlit Cloud app and Neon database, banner "Staging copy") and the
  GitHub Tests check update. When the change looks right there and Tests is
  green, ask "Release to main?" and then `git push origin staging:main` (a
  fast-forward). `main` is protected: it takes only commits whose Tests check
  passed, no force pushes. Before starting work: `git checkout staging && git pull`.
- **What's new.** A release to main that changes something people can see adds an entry
  at the top of `whats_new.ENTRIES` (plain, calm words; an item for a flagged feature names
  its `flag`, so it only shows where that feature is on). It's in the name menu with a
  small dot until opened - never a pop-up.
- Explain the plan before refactoring CSV import (`csv_import.py`) or price fetching
  (`live_prices.py`, `update_prices.py`, `sync_history.py`).
- Never touch the real `portfolio.db` or `.env`. Use scratch copies (see Testing).
- No broker is "primary" - Schwab, Fidelity, Robinhood etc. are all equal.
- Copy for new users should be reassuring, not technical: privacy first, nothing scary.

## Commands
- Postgres tests: `NORTHWEND_TEST_PG=postgresql://... python -m unittest tests.test_postgres`
  (skipped without it; CI's `postgres-tests` job runs them on a real Postgres 16).
- Tests (all must pass): `python -m unittest discover -s tests` (~13 min). Quiet:
  `... 2>&1 | grep -E "^(Ran|OK|FAILED|FAIL:|ERROR:)"`. CI runs it in 4 shares
  at once (`scripts/test_shard.py`; the required `unit-tests` check gathers them).
  One share locally: `python -m unittest $(python scripts/test_shard.py 4 1)`.
  The main checkout's real `.env` makes some page tests reach the network: run
  the full suite on a `git archive HEAD` copy.
  Page tests block the outside network with `tests/offline.py`
  (`patch("socket.socket.connect", offline_net.connect)`); loopback is allowed
  because Windows' asyncio event loop needs it.
- Run locally: `python -m streamlit run dashboard.py`. In the desktop app use the
  `.claude/launch.json` previews (`review-class` = scratch `classtest.db`, user alice).
- Python 3.13; `pandas==2.2.3` is pinned on purpose (3.0 is blocked on one machine).

## Where things live
- `dashboard.py` (~1.7k lines) - the app's one Streamlit script: styles, sign-in,
  the menu, settings, formatting helpers, the header, live prices, loading holdings.
  Each page's code is in `views/` and runs inside it via `_view("name")` at the
  point it's listed (same names, no imports needed - read the header of any view):
  `dashboard_page` (Home in three parts: the navy band, then keyed containers
  `pt_home_layout` = `pt_home_main` - the chart, a compact holdings list, the rest
  below, the full table in an expander - and `pt_home_side` "This month": the walk,
  route, weekly, season, mix, drill, money checks, kit, news cards; one column
  under 900px, This month first and a sideways row of cards on a phone. Cards
  without their own done/put-away state get Done / Not now via `home_tasks.py`:
  keys + month/week id in the login's own prefs, nothing written by an advisor in
  a client's account), `ticker_detail` (one ticker's own page `TICKER_PAGE`, `?page=ticker&t=VTI`, opened from a row of Home's holdings table or the Watchlist - `dashboard._ticker_table`; no menu item, Back returns),
  `watchlist`, `activity`, `income`, `plan`, `get_started` (and `first_steps`, the
  new investor's slideshow shown in its place), `assistant` (Ask Northwend),
  `profile`, `account` (the login's own account: name, email, password, data),
  `life` (Life: the account map, Lost & Found, Trail Forks, the Inheritance Rehearsal,
  Explain it to someone - always the login's own; an advisor has Life only on their own
  portfolio, never in a client's account; Account just links to it),
  `clients` (advisor side, weekly summary), `holdings_input` (paste,
  by hand, screenshots, CSV, the save step). Open just the view you need.
  Internal page "AI Assistant" is shown as "Ask Northwend" (`PAGE_LABELS`, `GUIDE = APP_NAME`).
- Data: `portfolio.py` (connect, schema setup + column back-fill, `write_snapshot`,
  delete/sample helpers), `schema.sql` / `schema_pg.sql` (keep **both** in step),
  `pgcompat.py` (SQLite-style SQL on Postgres, pooled connections).
- Getting holdings in: `csv_import.py` (the one CSV engine, any broker, layouts
  remembered; AI only on a button), `paste_parse.py`, `screenshot_read.py` (opt-in AI),
  `manual_entry.py`, `sample_data.py`. All save through dashboard `_review_and_save`.
  Activity (transaction history) exports go to `txn_import.py` from the same
  upload (rows with `origin` 'imported'; worked-out rows have NULL origin).
- Prices: `live_prices.py` (in-app, every minute while open), `update_prices.py`
  (Finnhub; the 15-min job), `sync_history.py` (Yahoo daily/intraday bars, dividends,
  fundamentals and the ex-dividend / pay / earnings dates in Yahoo's quote; nightly job).
  `dividend_dates.py`: announced dividends from Polygon (also called Massive;
  `POLYGON_API_KEY`, ticker symbols only, 12.5 s apart, 200 a night) into the shared
  `dividend_events` table - its own nightly job; `merged` / `next_for` give Scout's week
  ahead, Income's "Announced pay dates" and a ticker's page their dates, each with its
  source - facts only, never estimated. `price_report.py`: a stored price's time in words on the
  market's clock (`as_of`: "3:45 pm ET", "Oct 3 close"; not flagged, reads only
  stored times) and "Price look wrong?" on ticker detail (flag `price_report`: fixed
  reasons, `price_reports` table, counts-only "Price notes" in Admin).
- News: `news.py` (Finnhub /company-news into the shared `news` table; ticker detail
  fetches its own ticker on view). `news_feed.py` + `views/news_feed.py` (Your news,
  flag `news_feed`, no gate: "News on what you own" on Home and a News tab in
  `MONEY_PAGES`; `news_feed.pick` is the fixed rule - 3 days, wires/law-firm notices
  out, same story once, 2 per ticker, 10 in all; headline, source, how long ago and a
  link only, never a summary or the person's figures; pages read `NEWS_ROWS`, never
  Finnhub. Its hourly job `python news_feed.py` (scheduled-sync.yml `news`) fetches held +
  watched tickers across accounts 1.5 s apart, 250 a run, prunes after 30 days).
- Numbers: `perf.py` (value over time, bar stats), `income.py`, `allocation.py`
  (`summary_words`: Home's plain-words line, flag `plain_summary`),
  `asset_classes.py`, `metrics.py`, `alerts.py`, `changes.py` (buys/sells from
  snapshot differences), `plans.py`, `pay_yourself.py` + `views/pay_yourself.py` (Pay
  yourself, R11, flag `pay_yourself` + gate L3 - L3 review before it's on beyond staging:
  a Plan tab, the monthly paycheck under a named rule of thumb the person picks, income
  only by default; every figure "under the rule you picked", the 20% fall hypothetical,
  never "withdraw"/"safe"/"enough" - `tests/test_pay_yourself.py` runs every line through
  `ai_policy.findings`; prefs keep the rule key only; an advisor in a client's account
  sees it with the standing line and saves nothing; not for an advisor's client signed
  in), `overview.py` (advisor clients), `fees.py` +
  `views/fees.py` (Fee check; `security_info.expense_ratio` is a fraction - Yahoo's
  `netExpenseRatio` is a percent, the others fractions: `sync_history._expense_ratio`),
  `own_numbers.py` + `views/own_numbers.py` (flag `learn_own_numbers`: "In your own
  portfolio" under four of Learn's basics - funds, spread, fees, ups - facts from their
  own holdings in percentages and asset classes, never tickers or advice words; 2022
  figures only from practice money's stored prices; only the login's own account),
  `fund_holdings.py` + `views/fund_overlap.py` (Fund overlap on Home: each fund's top 10
  holdings from Yahoo, fetched only when the window opens, kept a week in the shared
  `fund_top_holdings` table; yield on cost is `income.yield_on_cost`).
- People: `auth.py` (logins, sessions, client setup links, self-serve sign-up,
  confirm / reset links, advisor requests; sign-up needs an invite code from `invite_codes.py`
  while gate L0 is off - the live app sets `NORTHWEND_GATES = "L0"`; `NORTHWEND_MAX_SIGNUPS_PER_DAY`
  caps Create account a day, midnight to midnight Eastern - `auth.signups_full` counts `signups`
  rows with ok = 1, then "We're full for today"; setup links and admin/advisor-made accounts never count), `two_step.py` + `views/two_step.py`
  (two-step sign-in: `_two_step_gate()` runs inside `_login()` after any way in;
  required for advisors and admins; the authenticator keys are encrypted with `NORTHWEND_TOTP_KEY`
  (Fernet, "new,old" to rotate; `manage_users.py encrypt-two-step [--rotate]`; the published
  wording follows `disclosures.TWO_STEP_ENCRYPTED`, flipped only once live shows 0 readable) - an AppTest signing one in sets
  `two_step_ok`, see tests/test_menu.py; `manage_users.py reset-two-step`), `admin.py` + `views/admin.py` (the
  Admin portal: logins only, never holdings; admins made only from outside the app: `manage_users.py make-admin` or the
  `NORTHWEND_ADMINS` secret (a list of logins); its System panel shows the copy's
  version, database, email and keys (set or not, never values), "Sign everyone out" (`auth.sign_out_everyone`,
  also `manage_users.py sign-out-all`) and the last 100 rows of `admin_log.py` (append-only admin action
  log: every `_admin_do` names an action word, every changing `manage_users.py` command logs too; only
  `admin_log.prune` deletes, after a year); a new table with account data must be added to
  `admin.ACCOUNT_TABLES` - a test checks), `route.py` (the route's two stages, Learn - only
  required for the brand new - and Start investing; the investor home's next step),
  `brokerages.py` (Choose a brokerage: names and links only, alphabetical, never a fee
  or a ranking), `proposals.py` (advisor proposals, `views/proposals.py`),
  `gear.py` + `views/kit.py` (milestones and gear: learning and habits only;
  storms.py, the storm note on Home, is drawn there too; its words are fixed
  templates in `storms.narrate` / `WINDOW_NOTE`),
  `meeting.py` (meeting prep, `views/meeting.py`), `reports.py` (client
  progress reports, `views/reports.py`), `advisor_drafts.py` + `views/drafts.py`
  ("Draft with Northwend" into the editable box of a proposal, a message, a report;
  flag `advisor_drafts` + L1, L2; text only - never imports mailer/proposals/advising), `mailer.py` (Resend; `MAIL_DRY_RUN=1` logs instead of
  sending - use it for local runs), `manage_users.py`
  (admin account creation, AI limits), `ai_usage.py` (monthly AI allowances - any new
  AI feature checks `_ai_status`, counts with `_ai_record` only after a
  successful answer, and shows failures via `_ai_failed` - never raw error text),
  `ai_spend.py` (the app-wide monthly AI cost: tokens and cost per helper, no text or
  user_id; levels at 50/80/95/100% of `NORTHWEND_AI_CEILING_USD`, alert emails, calm
  "resting" wording - every AI call records with `ai_spend.note` after a good answer),
  `advising.py` (also ending a relationship: `end_relationship`, the advisor's records
  stay via `former_clients`), `client_csv.py` (Add clients from a file, through
  dashboard `_add_one_client`), `advisor_demo.py` + `views/advisor_demo.py` (the
  in-memory example book a pending advisor sees - never written anywhere),
  `advisor.py` (the AI guide), `ai_gateway.py` (the ONLY place the Claude API is called: a
  register of helpers, allowance and ceiling checks, cost recorded, nothing else logged; a
  test pins it), `context_card.py` (the typed, frozen card the chat is sent - it can't hold
  amounts, share counts or account details; client mode's rule goes after `</card>`, never
  in the shared block), `ai_policy.py` (the conclusion policy: rules in the shared prompt
  block; `advisor.stream_reply` checks each streamed sentence, asks once more on a break,
  then shows the fallback - pages draw it with `advisor.Redraw` in mind), `ai_library.py`
  (the guide's general library, in the shared block: same for everyone, size and ticker
  tests), `ai_tools.py` (read-only calculator tools: percentages in and out, no DB), `evals/`
  (`python -m evals.run`, not in CI; the offline checker is), `prefs.py`, `accounts.py`.
  The plan PDF (`client_plan.py`) has no AI: rule-based questions.
- Look: `.streamlit/config.toml` (the Northwend theme: colors per light/dark,
  Figtree text and Newsreader titles from `static/`, served at `app/static/`),
  and the `--pt-*` colors at the top of dashboard.py's styles. Keep both in
  step with the Northwend design system. The logo (star over paper hills) is
  `static/logo.svg` / `logo-dark.svg` (tab icon, `_logo()` beside the name; the site's
  `favicon.svg` is the same). The deep blue band ("E2"): `_band_css` draws it only on
  the main area marked `data-pt-band` by ui_enhancements.js, which it sets only while
  a band container is on the page (never sign-in, the agree box, other pages or windows):
  Home's tall `pt_home_band`, or the slim `pt_page_band` on the pages that opt in
  (`_band_kind`: `BAND_PAGES` = Plan, Learn, Life, Ask, plus Money's pages; on Life and
  Ask a line under the title, `_slim_band_line`). Under the slim band every one of them is
  `pt_page_layout` = `pt_page_main` + `pt_page_side` (~19rem; one column under
  900px): Plan's goal card `pt_plan_goal`, its tab groups in `pt_plan_tabs`, "Your mix" /
  next deposit / stress test on the right (each opens its tab: `_open_plan_tab`); Money's
  views draw `with _page_main():` into one card `pt_money_card`, Accounts (and on Income
  "Income ahead") on the right, from what's already loaded; Learn's side is This season
  and Milestones, Ask's "What it sees" (kept true to `context_card.ContextCard` - a test
  pins its fields); Life is the middle alone, Trail Forks a grid (`pt_tf_grid`).
- Website (northwend.app, Cloudflare Pages): `website/` - templates and assets,
  `build.py` writes `website/public/` (committed, served as is). Edit the
  templates, then run `python website/build.py`; a test fails if `public/` is
  stale. The About page comes from `disclosures.py`; `APP_URL` is in build.py.
  `/whats-new` is built from `whats_new.ENTRIES` (flagged items only if in build.py's `LIVE_FLAGS` - so
  rebuild after adding an entry); `/status` is hand-edited (`STATUS_NOW`,
  `NOTICES` in build.py; no scripts, no uptime figures).
  Pages: Home, New to investing, For advisors, About, 404 (`PAGES`; a page in `HELD` -
  none today - is built for tests but not published; Decode your 401(k) menu is live); its
  tables are worked out in build.py (no scripts: the CSP allows none) and
  its contour lines are the app's `static/topo-light.svg`. The design is
  the "Northwend website redesign" Claude Design canvas.
- Legal: the published Terms of Use and Privacy Policy are `docs/legal/terms-of-use.md`
  and `privacy-policy.md` (built into northwend.app/terms and /privacy; their
  `{{NAMES}}` - date = `disclosures.LAST_UPDATED`, the version agreed to, operator,
  contact, the host rows from `HOST_MOVED` - are filled by build.py; linked from every
  agree box via `AGREE_BOX` and the About page). The `-DRAFT` files beside them (and the
  security page for advisors) are the lawyer's working copies, written for after the
  move. Keep all their facts true to the code like `disclosures.py` (tests/test_legal_pages.py). The AI's rules are `advisor.GUARDRAILS` (in every
  AI prompt; a test pins every AI call); `scripts/ai_guardrail_eval.py` tries
  them on the real model. Anything worked out from a person's answers names
  kinds of funds, never tickers (named examples only in general reads).
- Text/other: `disclosures.py` (draft legal text, placeholders), `learn.py`,
  `glossary.py` (one glossary for the app and Ask Northwend; flag `glossary`, shown by
  dashboard `what_this_means(...)`; `glossary_ai.py`, flag `glossary_ai`: an unknown
  word, the term only, to the AI on Learn), `client_plan.py` (PDF; questions by rules, no AI), `news.py`, `ui_enhancements.js`, `codefresh.py`
  (reloads changed modules on deploy), `friendly_errors.py` (the "something went wrong"
  message; it also hands the error to `error_alerts.py`, R1: type and place only, no
  user_id, emailed to ALERT_EMAIL at most once an hour per kind, hosted copies only -
  a new scheduled job needs its own "Tell the admin it failed" step, a test checks).
- Recaps and records: `recap.py` + `views/year_review.py` (Year in review, a window from
  Home; the share version never has dollars), `account_map.py` + `views/account_map.py`
  (the "if something happens to me" map on Life - only the login's own, never an
  advisor's view or the AI), `lost_found.py` + `views/lost_found.py` (Lost & Found, R9, flag
  `lost_found`: under the account map, where to look for old 401(k)s and unclaimed money -
  official links only (`OFFICIAL_SITES`), an old 401(k)'s choices side by side, never which;
  the "places I've looked" list in the login's own prefs; never in a client's account),
  `trail_forks.py` + `views/trail_forks.py` (Trail Forks, R8, flag `trail_forks`: at the
  top of Life, a route per life event - what changes, gather, ask whom, not rush - ending in the
  Walk; divorce/inheritance/death only "what to ask"; forks and ticks as keys in the login's
  own prefs; never in a client's account),
  `inheritance_rehearsal.py` + `views/inheritance_rehearsal.py` (the Inheritance Rehearsal,
  flag `inheritance_rehearsal`: under Trail Forks, a tap-through practice run with a made-up
  parent - never graded, official links only, no rules/deadlines/figures; step keys and the
  day finished in the login's own prefs; never in a client's account),
  `seasons.py` + `views/seasons.py` (the Four Seasons, R7, flag `seasons`: a card on Home in
  January, April, October-November and December, a line on Learn; yearly figures live in
  `seasons.LIMITS` / `RMD_AGE` with their tax year and IRS page - a test fails once the year
  is past: update them each January),
  `weekly.py` + `views/weekly.py` (weekly summaries, flag `weekly`: one card on Home via
  `render_weekly()` - "Your week" Fri after the close to Sun, "The week ahead" Mon-Thu; pure
  builders `your_week`/`week_ahead` + fixed `*_lines` templates for a later email; reads only
  kept data (no benchmark, no future ex-dates; earnings/pay dates only from the broker file);
  `weekly.CALENDAR` (FOMC, NYSE) - a test fails once `CALENDAR_YEAR` is past; prefs keep the
  week id + seen/put_away, never written from an advisor's session),
  `explain_share.py` + `views/explain_share.py` (Explain it to someone, R10, flag
  `explain_share`: a figure-free share link, `?share=` drawn in `_login()` before sign-in
  and signing nobody in; table `share_links` keeps only the token's SHA-256; 7/30 days,
  3 at most, revoke deletes; the login's own account only, never client mode or an admin;
  the view isn't flag-owned so a link shows "no longer active" while the flag is off), `checkin.py` + `views/checkin.py` (the monthly check-in;
  `checkin_email.py` its no-figures reminder), `future_notes.py` (notes to future you; `sealed_envelope.py`, flag
  `sealed_envelope`, needs `storm_drill`: the drill answer as a one-page PDF - their
  words and day only, never a figure; made on click, never saved, prefs keep the day).
  `drills.py` + `views/drills.py` (preparedness drills, R12, flag `drills`: one card on
  Home under Your kit, one drill a week, taps are things to weigh - never trades, never
  graded; the readiness map; prefs `drills` keys only; the whistle in `gear.py`; never
  in a client's account, the client record or the AI; wording test in `tests/test_drills.py`).
  `challenges.py` + `views/challenges.py` (This month's practice challenge, flag `challenges`:
  a card in Home's This month and the full one under Learn's practice money; pretend money on
  the practice stand-ins' prices already in `daily_bars` - nothing fetched, a challenge whose
  months aren't there is "not ready yet"; the person picks a rule (% stocks, 5-point band),
  scored only on following it, no leaderboard; prefs `challenges` keys, step, answer keys and
  day only; never CLIENT_MODE or an advisor in a client's account; pure module, kinds not tickers).
  `month_world.py` + `views/month_world.py` (This month's world, flag `month_world`: one
  line in the drill card; `NOTES` are the owner's hand-written, L3-reviewed notes - ships
  empty; shown in its month and the next, only with `reviewed_on`, only while
  `month_world.problems()` passes (no forecast/advice words, tickers, funds; official
  sources) - Tests runs it over `NOTES`; lines by the person's largest asset class or two;
  prefs `month_world_seen` months only; never the AI; how-to in docs/RUNBOOK.md).
  `teach_back.py` + `views/teach_back.py` (Teach It Back, R13, flag `teach_back`: a box
  in Learn's basics window; the gateway's `grader` helper - cheap tier, kind "grader" in
  the chat allowance - gets the topic key, its fixed reference and the words after
  `teach_back.scrub`; holds / not yet, never a score; `ai_policy.check` + no-score check
  or a fixed line; prefs `teach_back` keep held + day only, never the words; the map case
  in `gear.py` after three; eval cases `evals/grader.py`, offline in `tests/test_teach_back.py`).
  `trail_conditions.py` (Trail Conditions, flag `trail_conditions`: the opt-in Monday
  email, switch on Account; calm unless a storm / season / walk / readiness gap, fixed
  lines, no figures; once an ISO week; unsubscribe kind "trail"; sends nothing while
  `mailer.POSTAL_ADDRESS` is empty - CAN-SPAM; its own job in scheduled-sync.yml).
  `advisor_pack.py` + `views/advisor_pack.py` (Bring to my advisor, Phase C2, flag
  `advisor_pack`: on Account a client signed in as themselves ticks private items to show
  their advisor - all off, first share records `consent.grant(scope="advisor_pack")` with the
  exact words; table `advisor_pack` keys + day only; the advisor reads only ticked items via
  `advisor_pack.for_advisor` on a card over meeting prep, each opening an access-log row;
  any link ending calls `advisor_pack.on_unlink`; "This season for your clients" in the book).
  `client_book.py` + `views/client_book.py` (R16 Client-Owned Book, flag `client_owned_book`
  + gate L2: "How your book works", counts only and "Client-reported, as of <date>" in Your
  clients; a client's walk shows only if they turn it on (consent scope `walk_signal`);
  Stop sharing lists what each side keeps; any link ending calls `client_book.on_unlink`).
  `together.py` + `views/together.py` (Doing it together, flag `together`: a section on
  Life, individuals only - never an advisor, an admin or client mode. A one-time
  `?together=` link (hash only, 7 days), both yeses via `consent.grant` scope `together`
  word for word; a partner is read ONLY through `together.for_partner` - learning days
  this month, walk done, wins - never a figure; at most 3; Stop sharing deletes both
  `together_pairs` rows and revokes both ways; the "Your walk is waiting" nudge is weekly,
  opt-out (`together_nudges_off`, unsubscribe kind "together"), `rate_limits.NUDGE`).
  The check-in is shown as the Monthly Walk (R1): `checkin.verdict` is the person's own
  rule speaking (target mix + drift band, asset classes only). `feature_counts.py`:
  totals only from settings, groups of 20+, skips `feature_counts_off` (Admin's Feature
  tests panel) - any new test metric goes through it and the privacy text first.
- Flags and settings: `flags.py` (`NORTHWEND_GATES` L0-L3, never L4; `NORTHWEND_FLAGS`;
  `FEATURES` - a view or page a feature owns is skipped by `_view`/`PAGES`, a feature inside
  a view checks `flags.on("name")`; a test checks every name is checked; everything is off
  unless set). `settings.py`: env/secrets reads go through `settings.get`; `settings.hosted()`
  (a hosted copy with no Postgres `PORTFOLIO_DB` stops). A new setting goes in
  `.env.example` with a one-line comment (a test checks). Operations (deploy, restore,
  keys, gates' checklists, budget): `docs/RUNBOOK.md`; one-page overview:
  `docs/ARCHITECTURE.md`; made-up staging people: `manage_users.py seed-staging`. One-click unsubscribe:
  `unsubscribe.py` + `views/unsubscribe.py` (`?unsubscribe=`, reusable hashed tokens in
  `email_tokens`). Legal gates and principles: `docs/LEGAL_GATES.md`, `docs/PRINCIPLES.md`.
- The 401(k) Menu Decoder: `menu_decoder.py` + `views/menu_decoder.py` (signed in, flag
  `decoder_401k`; pasted order, never sorted, nothing saved) and `decoder_public.py` +
  `views/decoder_public.py` (`?decode=401k` without an account, flag `decoder_public` +
  gate L0, a per-address limit - only after the hosting move). The Fact Sheet Decoder
  (R6, fact sheets only): `factsheet_decoder.py` + `views/factsheet_decoder.py` (signed
  in, flag `decoder_factsheet`; paste only, no AI, nothing saved; text that looks like a
  statement is stopped and cleared unread - statements wait for proven local redaction).
- Advisor safeguards (PLAN step 5): `advisor_agreement.py` + `views/advisor_agreement.py`
  (flag `advisor_agreement`; until the current version is accepted `auth.can_view` opens
  no client), `licence_check.py` (BrokerCheck/IAPD evidence at approval, re-check due at
  11 months, not current after 13; nightly count email), `standing_line.py` (the "advice is
  the advisor's" line on proposals, reports, messages and their emails), `consent.py`
  (append-only grants/revokes with the exact words shown; `views/consent_ask.py` asks a client
  whose sharing has no grant in their own words once, at sign-in) and `access_log.py` (each page an
  advisor opens in a client's account; the client sees it on Account). Consent and access
  rows are `admin.KEPT_AFTER_DELETE` (7 years, only their own `prune` deletes).
- The advisor directory: `directory.py` + `views/directory.py` (flag `directory` + gate L2;
  table `advisor_profiles`). "Find a guide" in an individual's name menu (never client
  mode), the advisor's "Your directory listing" on Your clients. Alphabetical by name
  within B4's five filters - `directory.sort_key` is the only sort, never anything
  computed or paid; nothing about browsing is written. Intro button: `request_intro_placeholder`
  while flag `intros` is off. ADR 0005 (same flag): a listing's one-time review
  (`one_time_cost`, shown only - never a filter or sort), "How advisors are paid"
  (`directory.FEES_*`, official links only) and the quiet "Find a guide" line on Learn
  and Plan (`dashboard._guide_line`, `directory.guide_link_shown`: individuals only).
- Introductions (PLAN 5.5-5.6): `intros.py` + `views/intros.py` (flag `intros` + gate L2,
  inside Find a guide and Your clients; table `intro_requests`). The advisor sees only the
  name, message and figure-free outline sent (`intros.clean_outline`), only their own;
  full sharing only via `intros.share_account` (two steps, then `consent.grant(how="intro")`
  with the exact words and `auth.link_client` in one transaction).
- Limits and incidents: `rate_limits.py` (per-login uploads / saves / exports an hour and a
  day, counted in `email_sends` as hashes; a new heavy action calls `_limit_ok`), the RUNBOOK's
  "If something goes wrong" (incident and breach response). Mail for the owner goes to
  `mailer._admin_to()` (ALERT_EMAIL, else admin@northwend.app); support@ is the public contact.
- Send feedback: `feedback.py` + `views/feedback.py` (the name menu's and About's window, every
  signed-in login, no flag): emailed to `mailer._admin_to()` with the words, kind, page name,
  copy, version and a hashed reference (`feedback.reference`); the login's email only as
  Reply-To when ticked; nothing stored but `rate_limits.FEEDBACK` (5 an hour, 20 a day).
- Invite someone: `invite_links.py` + `views/invite_friend.py` (the name menu's window, every
  login on their own account while gate L0 is on - never an advisor in a client's account; no
  flag): one 10-character code per login in `invite_links` (kept as is, not secret),
  `?invite=<code>` opens the usual sign-up with "A friend invited you" (never who; an
  advisor's long setup token on `?invite=` still goes to the setup page); `joined` is a count
  only - which account came through which link is never kept; Admin shows one total;
  "Make a new link" replaces the code (`rate_limits.NEW_LINK`). No emails, no rewards.
- `export.py`: Export everything (Your data); a new table with account data goes
  in `export.OWN` or the test's left-out list.
- Hosting move (PLAN step 4): `docs/CLOUDFLARE.md` (headers, proxy, obfuscation off),
  `docs/DB_ROLES.md` (app/jobs roles; `NORTHWEND_SKIP_SCHEMA_SETUP` = the app stops setting
  up the schema, `northwend-migrate` does; `db_roles.py` = `northwend-migrate --roles`, run as
  the owner: makes `northwend_app` / `northwend_jobs` (no CREATE, rows only, default privileges,
  the append-only revokes), prints a new role's connection string once, checks real rights;
  the RUNBOOK's "Separate keys per copy" lists every live key), `scripts/restore_check.py` (row counts for the
  restore drill), the RUNBOOK's "Move to Render" checklist; `disclosures.hosting_lines()`
  names the real host (`HOST_MOVED` flips the website's wording after the move).
- Hosting (L4): `render.yaml` (the app on Render, go.northwend.app) and
  `hosting.py` (`CLIENT_IP_HEADER` for the visitor's address behind a proxy;
  `MOVED_TO` turns an old copy into a "has moved" page).
- Packaging: `pyproject.toml` (`pip install -e .`) and `cli.py` (the `northwend*`
  commands). Its `dependencies` match requirements.txt and `py-modules` lists every
  top-level module - a new module goes there too (a test checks).
- Jobs: Render cron jobs in `render.yaml` (`northwend-prices` every 15 min in market
  hours, `northwend-news` hourly via `news_feed.py`; GitHub dropped most of their runs),
  `.github/workflows/scheduled-sync.yml` (history nightly, dividend dates, tidy,
  advisors' Monday email via `weekly_email.py`, the reminders), `tests.yml`.

## Gotchas
- New columns on old tables: add them to the back-fill list in
  `portfolio._ensure_schema`, not only to the schema files. Indexes on `user_id`
  live in `USER_INDEXES` there (the column is back-filled on old databases).
- Postgres differences: `REAL` becomes DOUBLE PRECISION; `interval` is a keyword
  (qualify it, `b.interval`); timestamps are ISO text `YYYY-MM-DDTHH:MM:SSZ`.
- Every per-account query filters `user_id = ?`; advisors see clients only via `can_view`.
  An advisor's name for a client is `advisor_clients.client_name` (not the client's
  own Account name). Emails an advisor sends go out from their name via
  `mailer.sender` (the address stays hello@); approving or declining an advisor
  goes through `admin.approve_advisor` / `decline_advisor` (they send the email).
  Advisor notes are never deleted: `advising.archive_note` / `restore_note`, edits
  keep earlier text in the note's `history`; a client's record exports with
  `export.client_record_zip`. Agreeing to the disclosures is `users.terms_version`;
  `terms_via` says how (empty = their own sign-up) - "made the account themselves"
  is `auth.made_by_themselves(row)`, not "has a terms_version".
- Account numbers are masked to the last 3 digits (`accounts.mask_number`);
  uploads are never stored (`portfolio.temp_upload`).
- Never write tag-like text (`<html>`, `<div>`) in comments inside the app's
  `<style>` block or `ui_enhancements.js`: Streamlit drops the whole block
  (a test checks). Colors go through the `--pt-up` / `--pt-down` / `--pt-warn` variables.
- `dashboard.py` runs top to bottom, views included at their `_view(...)` line: a
  function used while the page is being drawn (sign-in, the menu) must be
  defined above that point. Button callbacks run later, so they can sit anywhere.
  A new view file needs its `_view("name")` line (a test checks they match).
- The menu is `NAV`, drawn once (`_render_menu`, container `pt_menu`): on a laptop a
  column pinned down the left side by the styles (the app's own - not Streamlit's
  `st.sidebar`, which stays unused), on a phone (<= 640px) a slim bar along the top
  with the brand and the two menus, the items moving to the bottom tab bar
  `pt_tabbar`. Nothing behind a "More". Investors: Home, Plan, Money, Life, Learn,
  Ask Northwend (+ Your advisor); advisors: Your clients, Viewing, Portfolio, Plan,
  Advisor notes, Money, Life (only on their own portfolio, never in a client's
  account), Ask Northwend. At the column's foot (`pt_menu_foot`):
  the route's progress (`_render_side_route`, filled in once `_route_state` exists),
  + Add holdings and `ACCOUNT_MENU` (the name menu `pt_me`: Account, What's new,
  About, Admin, Log out). Money is one item grouping `MONEY_PAGES` (Income,
  Activity, Watchlist, and News while `news_feed` is on - still pages of their own, listed under Money while it's
  open, keys `navsub_*`). `PAGES` is every page the account can open. A new page
  goes in `NAV`, under Money or in the name menu - keep the menu short. A label
  change (`PAGE_LABELS`; investors see Get started as "Learn") changes its
  `?page=` slug: add the old one to `OLD_SLUGS`.
- An advisor's client (or an advisor in a client's account) is `CLIENT_MODE`:
  no example funds, no beginner trail or practice money; Home's next step is
  the advisor's (`route.advisor_step`).
- Never name the folder `pages/`: Streamlit turns that into its own page menu.
- Edit files with the Edit tool. Python patch scripts inside Bash heredocs have
  turned `\n` in strings into real newlines before.
- Commit messages: `git commit -F -` with a heredoc (PowerShell breaks on quotes).
- `AppTest` can't drive multi-step dialogs or `data_editor`; check those in the browser.
- Sections that change on their own (the Plan tabs) are `@st.fragment`: a click
  redraws just that part. Use `st.rerun(scope="fragment")` inside one, and a
  plain `st.rerun()` only when something outside it must change too.

## Testing on scratch data
Scratch DBs and scripts live in the session scratchpad, never the repo. To count
the queries a page makes, hook `sqlite3.connect` with `set_trace_callback` and
run the page twice with `AppTest`, timing the second run.
