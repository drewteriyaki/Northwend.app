# Roadmap

The plan for getting from "working" to "ready to launch", one step at a time.
Each step is built and tested locally, checked on the live site, then
committed and pushed before the next one starts.

Sizes: **S** = an hour or two, **M** = a session, **L** = several sessions.
"Needs you" means a decision or an action only you can take.

---

## Done

- [x] Product polish pass: page headers, summary hero, import dialog, account
      nicknames, allocation bars (`5e57309`)
- [x] Login crash after deploy fixed; merged allocation views; light/dark switch (`323efa4`)
- [x] Stay signed in across reloads (`eb9ddff`)
- [x] Phase 1 - plans and goals, money in vs growth, settings in the database (`16996e6`)
- [x] Phase 2 - Get started path for new investors (`ae6be46`)
- [x] Phase 3 - advisor tools and a read-only client view (`ea0346c`)
- [x] Login lockout after too many wrong passwords (`eac5b77`)
- [x] 1 - Precise money columns: every Postgres `REAL` column is now
      `DOUBLE PRECISION`, checked in Neon (`c646b42`)
- [x] Deploy safeguard: the app reloads all its modules together when a push
      changes them, so no reboot is needed (`1797e9d`)
- [x] 2 - Tests run on GitHub on every push (`6e12e00`)
- [x] 3 - Change your own password from the sidebar; signs out other devices,
      including tabs already open (`8a55015`)
- [x] 4 - Friendly errors: "Something went wrong" with Try again and an error
      code instead of a traceback; the full traceback and the same code go to
      the Streamlit Cloud log (`9c35e03`)
- [x] 6 - "Client can import" switch on each client card; off by default, and
      the plan, goal, target mix and limits stay the advisor's (`4be1bdc`)
- [x] 7 - Stocks / Bonds / Cash / Other: funds split by what they hold (Yahoo's
      fund breakdown), with a per-account override; allocation, targets, model
      portfolios, drift, the plan PDF and the AI use it. Old targets converted
      where they map, cleared with a note where they can't (`815158a`)
- [x] 8 - Enter holdings by hand (any brokerage, no file): priced at save from
      Finnhub, then Yahoo; saved through the same write_snapshot() as an
      import, with the usual "what changed" review (`c1749aa`)
- [x] 9a - Privacy first: uploads read from a temporary copy and deleted;
      account numbers cut to 3 digits on save; an example portfolio; a
      percentages-only portfolio; disclosures updated (`5f3fea3`)
- [x] 9c - Paste your holdings from any brokerage's website (read by the app, no
      AI); "what we'll keep" before every save; the no-login promise; delete
      all my holdings, self-serve (`18b0b75`)
- [x] 9d - Holdings from screenshots: opt-in, read by the AI, images never
      kept; the answer is re-checked so only symbols / shares / cost survive
      (`09d20f7`)
- [x] Real Robinhood screenshot: average cost x shares becomes total cost;
      crypto saved as Yahoo's BTC-USD with a Crypto type (this commit)
- [x] Holdings section in the sidebar (paste / type / screenshots, CSV,
      example data) instead of header icons; one bigger Refresh for prices
      and history together (`9feb7ce`)
- [x] Prices keep themselves current: every minute while the market is open
      (crypto around the clock, mutual funds hourly), shared across viewers;
      the Refresh button is gone (this commit)
- [x] Brand: Waypoint, with Sage as the guide (Ask Sage); Get started is a
      route of numbered waypoints (`513b468`)
- [x] Live prices for holdings entered without a cost (`7a43922`)
- [x] 10 - Remember where you were: the page (and an advisor's client,
      re-checked every load) is kept in the address (this commit)

---

## Next up - in this order

### 5. Disclosures page - S - needs you
**Why:** the app shows example funds, projections and AI answers to real
people; advisors will ask what's said to their clients.
**Built:** an "About and disclosures" page (educational, not advice;
projections; how data is stored; what's sent to the AI; market data; not
affiliated), last in the sidebar and expandable on the login screen. The
wording lives in `disclosures.py`, with notes on which code each statement
depends on.
**Needs you:** have the final wording reviewed by someone qualified before
launch, and decide who people contact to delete their data. Then tick this.

### 9b. Any brokerage's CSV - L
**Why:** people will come from every brokerage, and each exports a different
layout; today only Schwab's imports reliably.
**What:**
- Find the holdings table anywhere in a file (title lines, notes, one table
  or a section per account).
- Match columns by common names first; if that isn't enough, AI sees only
  the column names and the *shape* of a few rows ("text, number, date") -
  never the values.
- Need only a symbol plus shares or value; cost optional; missing values
  from live prices; no date in the file -> today; no account column -> one
  account named after the file.
- A "check the columns" step with a dropdown per column before saving.
- Remember each layout, so the next file from the same broker imports
  without questions.
- Recognize a transactions export (or other wrong file) and say so.
**Done when:** exports from at least Fidelity, Vanguard, Robinhood, E*TRADE
and Schwab import (real samples, numbers blanked), and an unknown layout can
be fixed by hand in the column check.
**Needs you:** sample exports from real brokerages, numbers blanked out.

---

## Polish - smaller items, any order

- [ ] **Phone navigation** - a bottom tab bar or fewer top-level pages instead
      of a sidebar you open. (M)
- [ ] **Watchlist** - price and today's change next to each ticker without
      tapping in. (S)
- [ ] **Income** - estimated income by month, not just a yearly total. (S)
- [ ] **Activity** - a useful empty state that explains how activity appears. (S)
- [ ] **Speed** - measure page loads on the live database and cut the slowest
      queries; cache shared market data. (M)
- [ ] **Accessibility** - contrast, keyboard use and screen-reader labels on
      the custom HTML parts (hero, chips, bars). (S)
- [ ] **Advisor invites** - a one-time setup link for a new client instead of
      sharing a password. (M)
- [ ] **Review reminders** - a weekly summary for advisors of clients due a
      review or needing attention. (M)

## Later

- [ ] **Real transactions** - import Schwab's Transactions export for actual
      realized gains and dividend history, instead of inferring them. (L)
- [ ] **Packaging** - `pyproject.toml` and console entry points. (S)
