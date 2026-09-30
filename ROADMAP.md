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
      where they map, cleared with a note where they can't (this commit)

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
