# Portfolio Tracker

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
| **Allocation** | A stacked bar by asset type with a legend of % and $, and **By account**: each account's share of the portfolio with a thin bar of its own asset mix (hover a segment for its %), a flag for any single position over 15 % of the portfolio, and **Targets** — set a target % per asset type and get flagged when you've drifted beyond a threshold (default ±5 pts). |
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

## Command line

```bash
python portfolio.py import <positions.csv>   # parse + store + verify
python portfolio.py verify                   # re-run the reconciliation
python portfolio.py report                   # unrealized gain/loss summary (+ live block if present)
python update_prices.py                       # fetch Finnhub quotes, refresh live values
python sync_history.py                         # pull daily + intraday bars + fundamentals from Yahoo
```

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

- Works with any Schwab **All-Accounts Positions** export — account names and
  counts are read from the file, nothing is hard-coded.
- Point at a different database with the `PORTFOLIO_DB` environment variable
  (e.g. one per person). The dashboard and every CLI command honour it.
- The Finnhub key can come from `.env`, the `FINNHUB_API_KEY` environment
  variable, or `--key`. Yahoo history (`sync_history.py`) needs no key.
- **AI-assisted import (optional):** if a CSV's headers don't match the
  expected Schwab shape (a different broker, renamed/reordered columns),
  and an `ANTHROPIC_API_KEY` is set (same `.env`/environment-variable
  pattern as `FINNHUB_API_KEY`), the importer asks Claude to map the
  file's column headers to the fields it needs, then parses the actual
  data itself using that mapping - see `ai_parse.py`. Only the header
  row (plain column-name text, e.g. `"Symbol,Description,Qty,..."`) is
  ever sent; real holdings, dollar amounts, and account numbers are
  never sent to the API under this design. Unset (the default): strict
  parsing only, identical to before this existed.
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
