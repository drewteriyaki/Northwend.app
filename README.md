# Northwend

*Your guide from first step to goal.* A portfolio tracker for any brokerage, with
**Ask Northwend**, an AI guide (named after the app) that explains investing in plain language. (The code and
repository still use the old name, portfolio tracker.)

Turn a Charles Schwab **Positions** export into a local SQLite database, then
explore it from the command line or a single-page Streamlit dashboard: live
prices, allocation, rule-based alerts, per-ticker price history, and a
portfolio-value-over-time chart.

Everything runs locally. The only network calls are optional stock quotes from
[Finnhub](https://finnhub.io) (free tier is enough). Your data never leaves your
machine.

---

## Quick start

1. **Python 3.10+** — <https://www.python.org/downloads/>
2. Install the dashboard's three dependencies (the CLI needs none):

   ```bash
   pip install -r requirements.txt
   ```

3. **Get live prices working (optional):** copy `.env.example` to `.env` and paste
   a free Finnhub API key after `FINNHUB_API_KEY=`.

4. **Import a Positions export.** In Schwab: Positions → Export, then:

   ```bash
   python portfolio.py import "path/to/All-Accounts-Positions-YYYY-MM-DD.csv"
   ```

   This builds `portfolio.db` and reconciles every parsed holding against the
   file's own "Positions Total" rows.

5. **Open the dashboard:**

   ```bash
   python -m streamlit run dashboard.py
   ```

   (Windows: double-click `dashboard.cmd`. `report.cmd`, `import.cmd` — drag a CSV
   onto it — `update-prices.cmd`, and `sync-history.cmd` are the other launchers.)

---

## The dashboard

| Section | What it does |
|---|---|
| **Header** | Every page opens with its own title and icon buttons: **import** (upload icon), **hide amounts** (eye icon - masks every dollar and percent), **refresh prices**, and **sync history**. Underneath, one line says how fresh the prices are and which statement is loaded, in your own time zone. |
| **Summary** | Portfolio value, today's move in $ and %, the change since your last visit (same statement only - a new import's jump isn't the market), and tiles for total gain/loss, holdings, and cash. |
| **Alerts** | One line with the count - open it for the list and the limits. Defaults: day move beyond ±5 %, total gain/loss beyond ±20 %. Recomputed on every page load, no scheduler. |
| **Import** | The upload icon opens a dialog: upload a fresh export (running locally you can also type a path). Shows new / increased / decreased / closed positions vs the prior snapshot **before** saving, then writes the snapshot and records inferred BUY/SELL rows in `transactions`. Re-importing a date replaces it. New tickers get their prices and daily history fetched right away. |
| **Performance** | Line chart of any recorded portfolio stat, with a **1D … 1Y** range picker and the **% change over the window** - the reconstructed value of your current holdings × each bar's close, gap-compressed so market-closed hours don't stretch the chart. Holdings with no Yahoo history get daily bars fetched automatically on the next visit; if the picked range has no data yet (1D before the nightly intraday sync), the chart shows the shortest range that does. |
| **Goal card** | One line under the summary: the plan's goal, % of the way there, and whether it's on track, with **Open plan** - or **Set a goal** if there isn't one. |
| **Allocation** | A stacked bar by asset type with a legend of % and $, and **By account**: each account's share of the portfolio with a thin bar of its own asset mix (hover a segment for its %), a flag for any single position over 15 % of the portfolio, and **Targets** — set a target % per asset type (saved as the plan's target mix) and get flagged when you've drifted beyond a threshold (default ±5 pts). |
| **Accounts** | Side-by-side comparison across every account — total value, gain/loss, today's move, position count — with a CSV export. **Rename** gives any account a nickname ("Roth IRA" instead of "Individual ...111"), used everywhere in the app and saved in `account_labels`; the broker's name stays the key in the database. |
| **Holdings** | Sortable table. **Columns** picks from ~35 stats (price, day change $/%, unrealized $/%, % of portfolio, day open/high/low, dividend yield, **20/50/200-day MA, volume, 52-wk high/low, beta, P/E, sector** …) — add or remove as many as you like; the choice is saved. Search and **tap a ticker's pill** above the table to open its chart, position summary, stats, and recent news headlines below (cached from Finnhub, refreshed every 4 hours). **Download CSV** exports the raw figures (disabled while amounts are hidden). |
| **Watchlist** | Track any ticker's chart/stats without owning it — add one by symbol, tap its pill the same way as a holding. |
| **Activity** | Every inferred BUY/SELL transaction, filterable by account/action/symbol, with an estimated realized gain/loss (average-cost method) per sale and a CSV export. |
| **Income** | Estimated annual dividend income and yield-on-holdings, plus a per-position breakdown (yield %, est. income, last pay date, reinvest) sorted by biggest contributor and a CSV export — from the CSV's own dividend fields, not Yahoo. |

**Refresh** (the circular-arrow icon top right, or pull down from the top of
the page on a phone) calls Finnhub's `/quote` endpoint for each ticker, appends
to `price_history`, and rewrites each position's live market value. It also
runs on its own when an account is opened and its prices are more than 15
minutes old.

**Sidebar:** open and close it with the tab at the middle of its right edge,
or click anywhere outside it to close it. **Light / dark** at the bottom flips
the theme (System, Light and Dark are also in the ⋮ menu); the browser
remembers the choice. Both come from `ui_enhancements.js`,
which also handles pull-to-refresh.

**Sync history** (the clock icon next to refresh) pulls the deepest history Yahoo allows at *every* resolution
it offers into `daily_bars` / `intraday_bars` / `security_info`: ~2 years daily,
plus 1-minute (~7 days back), 5- and 15-minute (~60 days back), and hourly
(~2 years back) bars. The per-ticker chart automatically picks the finest
resolution that covers whatever range you select — a real minute-by-minute line
for **1D**/**5D**, not one point per day. Also powers moving averages, volume,
52-wk figures, and the reconstructed performance line. Needs `pip install
yfinance`; a full sync makes ~130 requests and a few hundred thousand rows, so it
takes a minute or two.

---

## Plan

One plan per account (`plans.py`, tables `plans` and `contributions`), set by
the account owner or their advisor - it says which ("Set by your advisor ...").
It works before anything is imported, so someone just starting can set a goal.

- **Goal:** what it's for (retirement, a home, education, ...), a target amount
  and date, and how much is added each month. The form starts from the
  investing profile's goal and time horizon.
- **Status:** % of the way there and one of *On track* (the assumed return
  gets there), *Within reach* (only the optimistic end does), *Behind*, *Goal
  reached*, or *Date passed* - with the projected amount, or the monthly amount
  that would close the gap.
- **Projection:** compound growth at an assumed yearly return (slider, default
  6%) with a ±2-point shaded range and the goal as a dashed line. Before
  inflation, fees and taxes - an illustration, not a prediction.
- **Contributions:** log money added or taken out; "This month: $X of $Y
  planned". Logged by hand - imports don't add these.
- **Money in vs growth:** money in is cost basis plus cash; growth is the rest.
  With two or more statements it's a chart over time.
- **Target mix:** target % per asset type with each one's distance from it.
  Must total 100%. The Dashboard's **Targets** edits the same numbers.

---

## Get started

A step-by-step path for new investors (`learn.py`), built from the investing
profile. It's where an account with nothing imported yet lands; once there are
holdings it moves to the end of the menu. Educational: it explains and shows
examples, it doesn't tell anyone what to buy. Each step can hand a question to
the AI Assistant, and each is checked off automatically where the app can tell
(profile answered, goal set, a statement imported) or marked done by hand.

1. **About you** - the investing profile questions, one tap each. Adds
   *Does your employer match what you put into a retirement plan?*
2. **Are you ready to invest?** - emergency savings, high-interest debt, an
   employer match, money needed within 3 years, uneven income - each marked
   Good / Look at this / Start here, with why.
3. **Set a goal** - links to the Plan.
4. **Learn the basics** - stocks, bonds, funds and ETFs; diversification;
   compounding and fees worked out with the plan's own monthly amount and
   horizon; market drops; account types.
5. **An example mix** - a stock / bond split from the time horizon, risk
   comfort and 20%-drop answer (a stated rule of thumb, with its reasons),
   shown as US stocks / international stocks / bonds with example low-cost
   index funds (VTI, VXUS, BND and similar), a target-date fund year when it
   fits, and notes for ESG or dividend preferences. **Watch these example
   funds** adds them to the Watchlist.
6. **Try it with practice money** - a monthly amount put into the mix over
   the last 1-10 years of real prices (dividends included, from Yahoo; **Load
   price history** fetches 10 years the first time): what you'd have put in,
   what it'd be worth, and the worst drop along the way.
7. **Open an account and bring it in** - how to open a brokerage account and
   set up automatic investing, then import the first statement.

---

## Advisors and their clients

An advisor (`manage_users.py make-advisor`) manages client accounts
(`advisor_clients`) from the sidebar's **Viewing** switcher (`advising.py`).

- **Clients page:** one card per client, sorted by what needs a look - goal
  behind or past its date, no goal, a review due (90 days after the last one)
  or never done, alerts, drift of more than 5 points from the plan's target
  mix, an incomplete profile, no statement yet - with the goal's progress, the
  last review, open next steps and the statement date. **Open** switches to
  that client.
- **Advisor notes** (on a client's account): a dated timeline of *Reviews*
  (meetings - the latest is the client's last review), *Notes*, and *Next
  steps* the advisor ticks off. Anything marked **private** is for the advisor
  only. The Dashboard shows the last review and open next steps.
- **Model portfolios:** saved target mixes by asset type (Clients page),
  applied to a client from their Plan page's Target mix. Asset types are how
  holdings are grouped, so an ETF counts as ETF / CEF whatever it holds.
- **How clients see you:** name, firm, email, phone and a short message
  (Clients page), shown on the client's Advisor notes page and sidebar.
- **Plans:** the advisor sets each client's goal and target mix; the Plan
  shows "Set by your advisor ...".

**When a client with an advisor logs in**, their view is read-only for what
the advisor manages: no import or history sync, no alert limits (they see the
advisor's), no allocation targets or account renaming, and the goal, target
mix and contributions are view-only. They see their portfolio, Plan, the
**Advisor notes** page (the advisor's card, open next steps and the timeline,
never private notes), Get started and the AI Assistant. An account with no
statement yet says the advisor brings statements in.

The **client plan PDF** includes the goal's progress and the advisor's open
next steps (never private notes).

---

## Command line

```bash
python portfolio.py import <positions.csv>   # parse + store + verify
python portfolio.py verify                   # re-run the reconciliation
python portfolio.py report                   # unrealized gain/loss summary (+ live block if present)
python update_prices.py                       # fetch Finnhub quotes, refresh live values
python sync_history.py                         # pull daily + intraday bars + fundamentals from Yahoo
```

Or install the project once (`pip install -e .` from this folder, Python 3.10+)
for the same tools as commands that work from any folder: `northwend` (the app),
`northwend-portfolio` (import / verify / report), `northwend-prices`,
`northwend-history`, `northwend-users` and `northwend-weekly-email` - each takes
the same options as its script (`cli.py`, `pyproject.toml`).

Common options: `--db PATH` (default `./portfolio.db`), and
`--snapshot YYYY-MM-DD` on `verify` / `report`. `update_prices.py` takes
`--key`, `--delay`, `--timeout`; `sync_history.py` takes `--period` (daily
look-back: `6mo` `1y` `2y` `5y` `max`), `--tickers`, `--no-info`, `--no-intraday`
(skip the 1m/5m/15m/60m fetches for a much faster daily-only sync), `--delay`.

---

## Keeping data fresh automatically

By default, prices and history only update when you click **Refresh
prices** / **Sync history** in the dashboard. To have that happen on its
own, register two per-user Windows Scheduled Tasks (no admin rights needed):

```powershell
powershell -ExecutionPolicy Bypass -File setup-scheduled-tasks.ps1
```

This sets up:

- **PortfolioTracker-Refresh** — Finnhub quotes, every 15 minutes
- **PortfolioTracker-Sync** — Yahoo daily/intraday bars + fundamentals, once
  a day at 17:30 (after US market close — it takes a couple of minutes, so
  it isn't run more often than that)

Both only run while you're logged in, log to `logs\refresh.log` /
`logs\sync.log`, and can be removed with `Unregister-ScheduledTask
-TaskName "PortfolioTracker-Refresh"` (and `-Sync`). The dashboard's manual
buttons still work as an on-demand override.

---

## Data model (`schema.sql`)

| table | purpose |
|---|---|
| `snapshots` | one row per imported (file, as-of date) |
| `positions` | one real holding per account per snapshot; live-price columns filled by `update_prices.py` |
| `account_totals` | per account: cash value + the file's "Positions Total" figures, kept for reconciliation |
| `price_history` | append-only log of every Finnhub quote (price, prev close, day open/high/low, % change, …) |
| `daily_bars` | real daily OHLCV from Yahoo, one row per (ticker, trading day), upserted by `sync_history.py` |
| `intraday_bars` | real 1m/5m/15m/60m OHLCV from Yahoo, one row per (ticker, resolution, bar time); each resolution keeps whatever look-back Yahoo allows it |
| `security_info` | one row per ticker: 52-wk high/low, beta, P/E, P/B, market cap, sector, avg volume (from Yahoo) |
| `transactions` | BUY/SELL rows **inferred** from the change between two imported snapshots (the Positions export has no trade history), with an estimated `realized_gain` (average-cost method) on SELLs |
| `value_log` | portfolio-level aggregates, one row appended per dashboard session |
| `watchlist` | tickers tracked for their chart/stats without being an owned position |
| `news` | cached Finnhub company-news headlines per ticker, refetched when the cache is older than 4 hours |

`portfolio.connect()` creates and upgrades the schema on first use, so an old
database keeps working after an update.

---

## Using it for another portfolio

- Works with a positions export from **any brokerage** (`csv_import.py`): it
  finds the holdings table, matches columns by name (Schwab, Fidelity,
  Vanguard, E*TRADE and others are just layouts it knows), and remembers a
  layout once someone has confirmed it. Pasted tables use the same engine.
- Point at a different database with the `PORTFOLIO_DB` environment variable
  (e.g. one per person). The dashboard and every CLI command honour it.
- The Finnhub key can come from `.env`, the `FINNHUB_API_KEY` environment
  variable, or `--key`. Yahoo history (`sync_history.py`) needs no key.
- **AI column guess (optional, only when asked):** if a file's columns
  can't be matched by name, the column check offers "Let AI guess the
  columns". Only the column names and the kind of each cell ("text",
  "number", "money") are sent - never holdings, amounts or account numbers.
- **AI Assistant (sidebar):** an educational investing chatbot on Claude
  Sonnet 5, using the same `ANTHROPIC_API_KEY` - see `advisor.py`. It
  works from a per-account investing profile (`investor_profiles` table):
  goals, time horizon, target return, risk tolerance, how they'd react to
  a 20% drop, experience, age, income, emergency savings, debt, how often
  they add or withdraw money, and preferences. Every question in the
  profile form is a tap, not typing, with **Other notes** for anything
  else. The assistant fills in answers from the chat too, then reviews the
  account's holdings. Holdings are sent as percentages only (ticker, name,
  asset type, sector, weight, gain/loss %, dividend yield, beta, P/E) -
  never dollar amounts, share counts, or account names. Chat history lasts
  for the session, but the assistant keeps short notes of its own between
  conversations (`ai_memory`, up to 1,500 characters, never shown in the
  app), so the next chat picks up where the last one left off.
- **Login lockout:** 5 wrong passwords for a username within 15 minutes lock
  it for 15 minutes - even the right password is refused until then. Unknown
  usernames lock the same way, so a lock says nothing about which accounts
  exist, and only a hash of the typed username is kept (`login_failures`).
  `manage_users.py unlock <username>` or a password change clears it.
- **Stay signed in:** checked by default on the login form. The browser keeps
  a random token in a cookie (`pt_session`, 30 days) and the database keeps
  only its SHA-256 hash (`login_sessions`), so reloading the page or a phone
  reopening the tab doesn't sign you out. **Log out** ends that browser's
  session in the database and deletes the cookie; changing an account's
  password (`manage_users.py` or an advisor's **Client login**) signs it out
  everywhere. Leave the box unchecked on a shared computer.
- **Advisor mode:** an account marked as an advisor (`manage_users.py
  make-advisor`) gets a "Viewing" dropdown in the sidebar to switch
  between its own portfolio and its clients' (`advisor_clients` table),
  with full access to each, plus an "Add client" form. Whose data is
  shown is re-checked against the database on every page load
  (`auth.can_view`), not trusted from the session. Clients can be
  advisor-managed only (random password) or given a login. A "Clients"
  section (`overview.py`) summarizes every client - value, gain/loss %,
  alert count, last import, profile completeness - with an Open button.
- **Client plan (PDF):** under **Client plan** on the AI Assistant page,
  **Create plan** builds a printable PDF for the viewed account - profile,
  allocation, holdings with dollar amounts, concentration and alerts, and
  AI-written suggested next steps (`client_plan.py`, rendered with
  `fpdf2`). The one API call gets the same percentages-only summary as the
  chat; dollar figures are added locally. Download only - nothing is
  saved. Disabled while **Hide amounts** is on.
- Dashboard settings (columns, alert limits, hide amounts, ...) are saved per
  account in the database (`user_prefs`, `prefs.py`). Older
  `.dashboard_prefs.<id>.json` files are read once and carried over.
- `.env`, `portfolio.db`, `imports/`, and `.dashboard_prefs*.json` are
  git-ignored.

---

## Tests

```bash
python -m unittest discover -s tests
```

Covers the CSV parser, importer (idempotency, replace-by-date), snapshot diff and
transaction synthesis, allocation, alerts, the metrics registry, the charts
helpers, moving-average math, daily-value reconstruction, and the intraday
resolution picker (`ticker_series`). No network calls - intraday/daily rows are
inserted directly rather than fetched live. Standard library only. (Windows:
`tests\run.cmd`.)

---

## Not yet

- **Precise realized gains** (FIFO/specific-lot) and **dividend history** need
  a separate Schwab *Transactions* export — the dashboard's Activity section
  shows *inferred* BUY/SELL transactions with an average-cost `realized_gain`
  estimate today, not broker-reported figures.
- **True live/streaming intraday** — Yahoo's 1-minute bars lag a little and stop
  at ~8 days back; there's no websocket tick feed here.
- **Packaging** — currently a folder of scripts. A `pyproject.toml` with console
  entry points is the natural next step.
