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
- [x] Login lockout after too many wrong passwords (this commit)

---

## Next up - in this order

### 1. Precise money columns on the live database - S - needs you
**Why:** the older money columns in Postgres (`positions`, `account_totals`,
`transactions`, `price_history`, `value_log`, ...) are `REAL`, which in Postgres
is a 4-byte float: amounts over about $1M lose cents. SQLite (local) is fine.
**What:** a one-time migration that changes them to `DOUBLE PRECISION`, plus
`schema_pg.sql` updated so new databases start right. Take a Neon backup/branch
first.
**Done when:** every money column in Neon is `double precision` and totals
match before and after.
**Needs you:** OK to run it against the live database.

### 2. Run the tests on every push - S
**Why:** 130 tests only run when someone runs them by hand; a broken commit
deploys straight to the live app.
**What:** a GitHub Actions job that runs `python -m unittest discover -s tests`
on each push.
**Done when:** a push shows a green (or red) test check on GitHub.

### 3. Change your own password - S
**Why:** today only an admin (`manage_users.py`) or an advisor can change a
password; nobody can change their own.
**What:** a "Change password" form in the sidebar (current + new password),
behind the same lockout; signs out other devices.
**Done when:** a user changes their password and their other sessions end.

### 4. Friendly errors and error visibility - M
**Why:** an unexpected error shows a raw traceback to users.
**What:** catch errors per page, show "Something went wrong - try again",
and keep the details in the Streamlit Cloud logs.
**Done when:** a forced error shows the friendly message and the log has the
full traceback.

### 5. Disclosures page - S - needs you
**Why:** the app shows example funds, projections and AI answers to real
people; advisors will ask what's said to their clients.
**What:** an "About and disclosures" page (educational, not advice; how data
is used and what's sent to the AI; not affiliated with any brokerage), linked
from the login screen and sidebar. I draft it.
**Needs you:** have the final wording reviewed by someone qualified before
launch.

### 6. Let a client import their own statements - S
**Why:** some advisors will want clients to upload their own files.
**What:** a per-client switch on the Clients page ("Client can import").
**Done when:** a client with the switch on sees the import button; others don't.

### 7. Stock vs bond funds - M
**Why:** holdings are grouped by the broker's asset type, so every ETF is
"ETF / CEF" whether it holds stocks or bonds - a true 60/40 target can't be
set or tracked.
**What:** classify each fund as stocks / bonds / cash / other from Yahoo's
fund category, with a manual override; allocation, targets, model portfolios
and drift use the new grouping.
**Done when:** VTI shows as stocks and BND as bonds, and a 60/40 model
portfolio tracks correctly.

### 8. Holdings without a Schwab file - M - needs you
**Why:** beginners and non-Schwab investors have no file to import.
**What:** type in holdings by hand (symbol, shares, cost), stored as a
snapshot like an import, so everything else works unchanged.
**Needs you:** OK to add a second way of writing snapshots next to the CSV
import.

### 9. Other brokers' CSV files - M
**Why:** the AI header-mapping fallback exists but hasn't been tried on real
Fidelity or Vanguard exports.
**What:** test with real exports, fix what breaks, and say which brokers are
supported.

### 10. Remember where you were - S
**Why:** a reload lands on Dashboard, and an advisor loses the client they
were viewing.
**What:** keep the page (and, for an advisor, the viewed client, re-checked
against their access) in the URL.

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
