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
      re-checked every load) is kept in the address (`2f31e0c`)
- [x] 9b - Positions CSVs from any brokerage: finds the table, matches
      columns by name / a remembered layout / the AI (column names and
      cell kinds only), a column check, then the usual review; spots
      transaction exports. Built on sample layouts - confirm with real
      exports (`3a47439`)
- [x] One import engine for every brokerage: uploads and pasted tables share
      csv_import.py and one review; Schwab is a layout like any other (checked
      identical to the old reader); the AI only guesses columns when asked;
      ai_parse.py and the Schwab-only preview removed (this commit)

---

## Next up - in this order

### 5. Disclosures page - S - needs you
**Why:** the app shows example funds, projections and AI answers to real
people; advisors will ask what's said to their clients.
**Built:** an "About and disclosures" page, last in the sidebar and on the
login screen: who runs it (individual, free beta, 18+), not advice,
projections, for advisors, your data (what's kept, retention, deleting),
security, cookies and tracking (usage statistics turned off), services used,
what's sent to the AI, market data, no guarantees, not affiliated, and how
changes are announced - a one-time notice after sign-in when it changes. The
wording lives in `disclosures.py`, with notes on which code each statement
depends on.
**Needs you:**
- Fill in `OPERATOR_NAME` and `CONTACT` in `disclosures.py` (a dedicated
  address like support@ is best) - the page shows placeholders until then.
- Have the final wording reviewed by someone qualified before launch; they
  may want separate Terms of Use and a Privacy Policy.
- Delete the Neon backup branch from the precision change once you're
  comfortable - it's a full copy of the data the retention line doesn't cover.
Then tick this.

---

## Launch - a public website, and the app on your own domain

Two pieces: a **website** (home, what we do, how it works, disclosures, Log in /
Create account) built as an ordinary website, and the **app** - this Streamlit
app - at `app.<your domain>`, restyled to match. The app stays in Streamlit;
only its look changes.

### L1. Name and domain - S - needs you
**What:** trademark check for "Waypoint" (USPTO, finance and investing), then
buy the domain (.com or .app, or a close variant like `usewaypoint.com`) and
check the social and app-store handles.
**Done when:** you own the domain and the name is clear to use.
- [x] **Name checked, renamed to Northwend** - "Waypoint" was crowded (a WAYPOINT
      class-36 filing by Waypoint Federal Credit Union, Waypoint Investors, a
      Waypoint budgeting app, many Waypoint advisors; the domains taken).
      Northwend: no app or company found using it; northwend.app, northwend.io,
      getnorthwend.com and northwendapp.com unregistered on Oct 1, 2026. The AI
      guide carries the same name ("Ask Northwend", was Sage).
- [ ] **Needs you:** search "Northwend" on USPTO trademark search (ideally an
      attorney's clearance), buy northwend.app (plus getnorthwend.com, and .io
      if wanted), check the social handles.

### L2. Brand and design in Claude Design - M - needs you
**What:** a design system (logo - the flag and compass are a start - colors,
type, voice), the website's home and sign-up pages, and a restyle of the
app's key screens (Dashboard, Plan, Ask Northwend, the phone tab bar).
**Note:** Streamlit can take the colors, fonts, logo and spacing, not a fully
custom layout - design the website freely, and give the app the same brand
rather than an identical layout.
**Done when:** the designs are ready to hand back here.

### L3. The website - M
**What:** build the home page, "what we do" / how it works, disclosures and
contact from the L2 designs, with Log in and Create account buttons that go to
the app. Host it on Vercel, Netlify or Cloudflare Pages (usually free) on the
L1 domain.
**Done when:** `<your domain>` is live and its buttons open the app.

### L4. Move the app to its own domain - M
**Why:** Streamlit Community Cloud only serves `….streamlit.app` addresses.
**What:** run the same app on a host with custom domains - Render, Railway,
Fly.io or Google Cloud Run (roughly $5-25 a month) - at `app.<your domain>`;
move the secrets; Neon and the GitHub scheduled jobs stay as they are. Apply
the L2 colors, fonts and logo (`.streamlit/config.toml` and the app's CSS).
**Done when:** the app runs at `app.<your domain>` and the old address points
there.

### L5. Create an account yourself - L
**Why:** accounts are made by an admin or an advisor today.
**What:** sign-up with email verification; "forgot password" by email (an
email service such as Resend or Postmark); bot protection on the form;
agreeing to the terms and disclosures; limits on AI use per account so costs
stay predictable (a free tier).
**Done when:** a stranger can create an account from the website, confirm
their email, reset a forgotten password, and use the app within its limits.
- [x] **AI limits** - monthly allowances per account (Ask Northwend 100 messages,
      screenshots 10, CSV help 20, plans 5; advisors 5x), shown as "X of Y left
      this month"; `manage_users.py ai-unlimited` for your own account. (ai_usage.py)
- [x] **Sign-up (no email sent yet)** - "Create an account" on the sign-in screen
      (also `?signup=1`): email as the login, 18+ and agreeing to the disclosures
      (version stored), bot checks (hidden field, too-fast form, 3 accounts per
      address a day, 20 app-wide an hour); normal AI limits. Sign in with email or
      username. (auth.sign_up, dashboard `_signup`)
- [ ] **Email confirmation and "forgot password"** - once an email service (and
      the L1 domain) is picked: fill `users.email_verified_at`, reset links.

### L6. Launch - S - needs you
**What:** the item-5 disclosures review done (and any Terms of Use / Privacy
Policy the reviewer asks for), a last pass on the live site, then open the
website's Create account button to everyone.

---

## Polish - smaller items, any order

- [x] **Phone navigation** - a bottom tab bar on narrow screens (Home, Plan,
      Sage, Watch or Clients, More); the sidebar stays on wider ones.
- [x] **Watchlist** - a row per ticker with its live price and today's change,
      tap to open its chart, remove from the row; Enter adds a ticker.
- [x] **Income** - estimated income by month, not just a yearly total. (S) - next 12 months by ex-dividend month, from the past year's payments (saved by the nightly sync) at today's shares.
- [x] **Activity** - a useful empty state that explains how activity appears. (S) - says why it's empty (example data, percentages, or just nothing yet), how updates become buys and sells with a small example, and offers the update buttons.
- [x] **Speed** - pages read only the account's own tickers and the time span
      needed (Dashboard 73 -> 50 queries, ~30% faster); the price table keeps
      minute-by-minute quotes for a week, then one close per ticker per day.
- [x] **Backend** - the value chart finds its bar size in one query and reuses the
      loaded holdings (Dashboard 39 -> 25 statements); per-account indexes; the
      15-minute job skips prices the app fetched in the last 10 minutes; a fund
      held in two accounts now counts both on the chart. `CLAUDE.md` added.
- [x] **Split dashboard.py** - one file per page in `views/` (dashboard.py 4,504 ->
      1,657 lines). Code moved unchanged; every page drew identically before
      and after (18 page views compared). (M)
- [x] **Accessibility** - contrast, keyboard use and screen-reader labels on
      the custom HTML parts (hero, chips, bars). (S) - up/down/warning colors
      pass AA contrast in light and dark (switching with the theme), dim text
      darkened; bars hidden from screen readers where the legend says the same,
      described where it doesn't; arrows and icon-only buttons named; less motion
      when the device asks for it.
- [x] **Advisor invites** - a one-time setup link for a new client instead of
      sharing a password. (M) - Client login > Create setup link; the client
      picks their own password and is signed in. Works once, 7 days, only a hash
      stored; a new link replaces the old, and it can be cancelled.
- [x] **Review reminders** - a weekly summary for advisors of clients due a
      review or needing attention. (M) - in the app: the first visit each week
      opens with reviews due, coming due in 14 days and who else needs a look,
      each with Open; Got it hides it until Monday (any device). Always on the
      Clients page. Email could follow once there's an email service and domain.

## Later

- [ ] **Real transactions** - import Schwab's Transactions export for actual
      realized gains and dividend history, instead of inferring them. (L)
- [ ] **Packaging** - `pyproject.toml` and console entry points. (S)
