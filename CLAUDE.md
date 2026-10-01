# Waypoint (portfolio-tracker)

A Streamlit portfolio app: people bring holdings from any brokerage (CSV, paste,
screenshots, by hand, or percentages only) and get live values, charts, a plan,
income and an AI guide called **Sage** ("Ask Sage"). Advisors can manage clients.
Live on Streamlit Community Cloud with Neon Postgres; locally it runs on SQLite.

## Working rules
- `ROADMAP.md` is the plan. Work items in order (or the one named), tick them
  `[x]` with a short note in the same commit.
- **Always ask "Commit and push?" before committing or pushing.** Every push is approved.
- Explain the plan before refactoring CSV import (`csv_import.py`) or price fetching
  (`live_prices.py`, `update_prices.py`, `sync_history.py`).
- Never touch the real `portfolio.db` or `.env`. Use scratch copies (see Testing).
- No broker is "primary" - Schwab, Fidelity, Robinhood etc. are all equal.
- Copy for new users should be reassuring, not technical: privacy first, nothing scary.

## Commands
- Tests (all must pass): `python -m unittest discover -s tests` (~30s). Quiet:
  `... 2>&1 | grep -E "^(Ran|OK|FAILED|FAIL:|ERROR:)"`
- Run locally: `python -m streamlit run dashboard.py`. In the desktop app use the
  `.claude/launch.json` previews (`review-class` = scratch `classtest.db`, user alice).
- Python 3.13; `pandas==2.2.3` is pinned on purpose (3.0 is blocked on one machine).

## Where things live
- `dashboard.py` (~1.7k lines) - the app's one Streamlit script: styles, sign-in,
  sidebar, settings, formatting helpers, the header, live prices, loading holdings.
  Each page's code is in `views/` and runs inside it via `_view("name")` at the
  point it's listed (same names, no imports needed - read the header of any view):
  `dashboard_page`, `ticker_detail` (one ticker, from Dashboard/Watchlist),
  `watchlist`, `activity`, `income`, `plan`, `get_started`, `assistant` (Ask Sage),
  `profile`, `clients` (advisor side, weekly summary), `holdings_input` (paste,
  by hand, screenshots, CSV, the save step). Open just the view you need.
  Internal page "AI Assistant" is shown as "Ask Sage" (`PAGE_LABELS`).
- Data: `portfolio.py` (connect, schema setup + column back-fill, `write_snapshot`,
  delete/sample helpers), `schema.sql` / `schema_pg.sql` (keep **both** in step),
  `pgcompat.py` (SQLite-style SQL on Postgres, pooled connections).
- Getting holdings in: `csv_import.py` (the one CSV engine, any broker, layouts
  remembered; AI only on a button), `paste_parse.py`, `screenshot_read.py` (opt-in AI),
  `manual_entry.py`, `sample_data.py`. All save through dashboard `_review_and_save`.
- Prices: `live_prices.py` (in-app, every minute while open), `update_prices.py`
  (Finnhub; the 15-min job), `sync_history.py` (Yahoo daily/intraday bars, dividends,
  fundamentals; nightly job).
- Numbers: `perf.py` (value over time, bar stats), `income.py`, `allocation.py`,
  `asset_classes.py`, `metrics.py`, `alerts.py`, `changes.py` (buys/sells from
  snapshot differences), `plans.py`, `overview.py` (advisor clients).
- People: `auth.py` (logins, sessions, client setup links, self-serve sign-up), `manage_users.py`
  (admin account creation, AI limits), `ai_usage.py` (monthly AI allowances - any new
  AI feature checks `_ai_status` and counts with `_ai_record`), `advising.py`,
  `advisor.py` (Sage, Claude API with prompt caching), `prefs.py`, `accounts.py`.
- Text/other: `disclosures.py` (draft legal text, placeholders), `learn.py`,
  `client_plan.py` (PDF), `news.py`, `ui_enhancements.js`, `codefresh.py`
  (reloads changed modules on deploy), `friendly_errors.py`.
- Jobs: `.github/workflows/scheduled-sync.yml` (prices every 15 min in market
  hours, history nightly), `tests.yml`.

## Gotchas
- New columns on old tables: add them to the back-fill list in
  `portfolio._ensure_schema`, not only to the schema files. Indexes on `user_id`
  live in `USER_INDEXES` there (the column is back-filled on old databases).
- Postgres differences: `REAL` becomes DOUBLE PRECISION; `interval` is a keyword
  (qualify it, `b.interval`); timestamps are ISO text `YYYY-MM-DDTHH:MM:SSZ`.
- Every per-account query filters `user_id = ?`; advisors see clients only via `can_view`.
- Account numbers are masked to the last 3 digits (`accounts.mask_number`);
  uploads are never stored (`portfolio.temp_upload`).
- Never write tag-like text (`<html>`, `<div>`) in comments inside the app's
  `<style>` block or `ui_enhancements.js`: Streamlit drops the whole block
  (a test checks). Colors go through the `--pt-up` / `--pt-down` / `--pt-warn` variables.
- `dashboard.py` runs top to bottom, views included at their `_view(...)` line: a
  function used while the page is being drawn (sign-in, the sidebar) must be
  defined above that point. Button callbacks run later, so they can sit anywhere.
  A new view file needs its `_view("name")` line (a test checks they match).
- Never name the folder `pages/`: Streamlit turns that into its own page menu.
- Edit files with the Edit tool. Python patch scripts inside Bash heredocs have
  turned `\n` in strings into real newlines before.
- Commit messages: `git commit -F -` with a heredoc (PowerShell breaks on quotes).
- `AppTest` can't drive multi-step dialogs or `data_editor`; check those in the browser.

## Testing on scratch data
Scratch DBs and scripts live in the session scratchpad, never the repo. To count
the queries a page makes, hook `sqlite3.connect` with `set_trace_callback` and
run the page twice with `AppTest`, timing the second run.
