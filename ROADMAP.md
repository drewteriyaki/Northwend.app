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
- [x] `OPERATOR_NAME` (Andrew Zhang) and `CONTACT` (support@northwend.app)
  filled in - no placeholders left.
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
- [x] **northwend.app bought** (Cloudflare, auto-renew); USPTO wordmark search
      for "Northwend": no results, live or dead (Oct 1, 2026). Resend and
      support@ email routing set up on it.
- [ ] **Needs you:** search look-alikes on USPTO (Northwind, North Wend, North
      End in classes 9, 36 and 42; an attorney's clearance is better still);
      getnorthwend.com if wanted; the social handles. Note northwend.com is an
      unrelated supplements business.

### L2. Brand and design in Claude Design - M - needs you
**What:** a design system (logo - the flag and compass are a start - colors,
type, voice), the website's home and sign-up pages, and a restyle of the
app's key screens (Dashboard, Plan, Ask Northwend, the phone tab bar).
**Note:** Streamlit can take the colors, fonts, logo and spacing, not a fully
custom layout - design the website freely, and give the app the same brand
rather than an identical layout.
**Done when:** the designs are ready to hand back here.
- [x] **Design system** "Northwend" (a Claude Design System artifact): compass
      blue, navy ink, dawn for goals reached, gain/loss/warning and chart colors
      from the app, light and dark; Newsreader titles, Figtree text; voice, icon
      and waypoint-motif rules; six components. No logo yet.
- [x] **Website mockups** (a Claude Design canvas): Home and Create account,
      fluid, light and dark.
- [x] **App restyled to match** - `.streamlit/config.toml` theme (colors per
      theme, fonts served from `static/`, 8px corners, chart palette), the app's
      own pieces on `--pt-*` design-system colors, stronger edges on inputs.
- [ ] **Needs you:** review the system and mockups; a logo, if wanted.

### L3. The website - M
**What:** build the home page, "what we do" / how it works, disclosures and
contact from the L2 designs, with Log in and Create account buttons that go to
the app. Host it on Vercel, Netlify or Cloudflare Pages (usually free) on the
L1 domain.
**Done when:** `<your domain>` is live and its buttons open the app.
- [x] **Built** - `website/`: Home (how it works, privacy, the guide, for
      advisors), About and disclosures made from `disclosures.py`, a 404; plain
      HTML and CSS, no JavaScript, cookies or trackers; fonts self-hosted;
      security headers. `python website/build.py` writes `website/public/`
      (committed; a test checks it is current). Create account opens the app's
      `?signup=1`, Log in the app.
- [x] **Live at https://northwend.app** - Cloudflare Pages on this repo (no
      build command, output `website/public`), redeploys on every push to main.

### L3b. Staging and branch protection - M
**Why:** every push to `main` goes straight to real users; tests run beside
the deploy, not before it.
**What:**
- A `staging` branch with its own Streamlit Cloud app and its own database
  (a Neon branch), plus a Cloudflare Pages preview for the website - try
  changes there, then merge to `main`.
- Branch protection on `main` on GitHub: changes arrive by pull request and
  merge only when the tests pass.
- CLAUDE.md's working rules updated for the new flow (staging first).
**Done when:** a change can be seen on staging before it reaches anyone, and
`main` can't take a push whose tests fail.
- [x] **Code side** - the Tests workflow fixed (a doubled `cache: pip` had
      stopped every run since `19a25b6`; a test now catches repeated keys);
      `NORTHWEND_ENV = "staging"` shows a "Staging copy" banner and tab title;
      the `staging` branch; CLAUDE.md's staging-first rule.
- [ ] **Needs you:** the staging Streamlit app and Neon database, and the
      ruleset on `main` (steps given in the session).

### L4. Move the app to its own domain - M
**Why:** Streamlit Community Cloud only serves `….streamlit.app` addresses.
**What:** run the same app on a host with custom domains - Render, Railway,
Fly.io or Google Cloud Run (roughly $5-25 a month) - at `app.<your domain>`;
move the secrets; Neon and the GitHub scheduled jobs stay as they are. Apply
the L2 colors, fonts and logo (`.streamlit/config.toml` and the app's CSS).
**Done when:** the app runs at `app.<your domain>` and the old address points
there.
- [x] **Code ready** - Render chosen (Starter, always on). `render.yaml`
      (a Blueprint: build, start, health check, secrets asked for, never
      stored), `hosting.py`: the visitor's real address behind Render's
      proxy (`CLIENT_IP_HEADER`) for the sign-up and email limits, and a
      "Northwend has moved" page for the old address (`MOVED_TO`, keeps the
      ?query so old email links still work).
- [ ] **Needs you** - create the Render Blueprint from this repo and paste
      the secrets; check it on its `onrender.com` address; add `app` in
      Cloudflare DNS and the custom domain in Render. Then: website
      `APP_URL` to `https://app.northwend.app/`, and `MOVED_TO` on the old
      Community Cloud app.

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
- [x] **Email confirmation and "forgot password"** - Resend on northwend.app
      (`mailer.py`, from hello@, replies to support@). A confirm link after
      sign-up (3 days; "Send it again" notice); the AI features wait until it's
      confirmed (`ai_usage.CONFIRM_FOR_AI`). "Forgot password?" sends a one-hour
      reset link with the same answer whether or not there's an account; a reset
      signs out everywhere and counts as confirming. Links hashed and one-time;
      send limits by hashed email and address. `MAIL_DRY_RUN=1` logs instead of
      sending. Contact in the disclosures is support@northwend.app.
- [ ] **Needs you:** sign up on the live app with your own email to check the
      real email arrives (and a reset).

### R1. Error alerts - S
**Why:** errors only reach the server log today, so a broken page or a
failed price job is found by a user first.
**What:** an email to the admin (support@) when the live app hits an
unexpected error (friendly_errors.py: what failed and where - never the
person's data) and when a scheduled job fails; at most one email per kind
of error per hour, and a list on the Admin page's System panel.
- [x] **Built** - `error_alerts.py`: an unexpected error (friendly_errors)
      or a failed scheduled job (a `failure()` step in scheduled-sync.yml)
      emails ALERT_EMAIL (default support@) - type, file, function, line and
      the error code, never the message or anyone's data. One email per kind
      per hour across processes (`error_events`); only hosted copies email.
      Admin > System lists them, with Clear the list.

### R2. Two-step sign-in for advisors - M
**Why:** an advisor's login opens every client's portfolio; one stolen
password exposes the whole book.
**What:** an authenticator-app code (TOTP) after the password - required
for advisors and admins, optional for everyone on the Account page; a few
one-time backup codes; "remember this device for 30 days" on the
stay-signed-in cookie; the admin can reset it for someone locked out.
- [x] **Built** - `two_step.py` + `views/two_step.py`: after the password
      (or a stay-signed-in cookie, setup or reset link), a 6-digit code from
      an app on the phone (TOTP, no new library for the codes; `segno` for
      the QR picture), or one of 8 one-time backup codes. Advisors and
      admins set it up right after signing in; investors turn it on or off
      on Account. "Don't ask again on this device" (30 days) rides on the
      stay-signed-in session. Admin > Reset two-step (or `manage_users.py
      reset-two-step`) turns it off and signs them out everywhere.

### L6. Launch - S - needs you
**What:** the item-5 disclosures review done (and any Terms of Use / Privacy
Policy the reviewer asks for), a last pass on the live site, then open the
website's Create account button to everyone. **R1 and R2 first.**

---

## Calm by default - simpler for new investors - in this order

**Why:** pages show everything at once - Home has the value, stats, goal,
alerts, a performance chart, allocation, an accounts table and a holdings
table; Get started is seven open-ended steps on one page. A newcomer doesn't
know where to look first.

**Principles for every page:**
- **One thing at a time.** Each page leads with a short summary - a few
  numbers and one next step. Detail opens in a window (a dialog) when
  it's asked for; a full page of everything only where it's really needed
  (a holdings table, the advisor's client list).
- **Plain first, detail on request.** Investors get the simple view; a
  "Show everything" switch (Account page) brings back the full pages for
  people who want them. Advisors keep the full view.
- **Learn more from trusted sources** - links to public education sites
  (Investor.gov from the SEC, FINRA, the CFPB) next to the idea they
  explain, never copied text.

### S1. First steps as a slideshow - M
A new account goes through a short guided flow, one screen at a time, with
Back / Next and progress dots: welcome (what Northwend is, privacy) -> a
few tap questions -> your goal -> your investor type and example mix ->
bring your holdings or try the example. Skippable, resumable, and Get
started afterwards shows the same steps as cards you can reopen.
- [x] **Built** - `views/first_steps.py`, shown in place of Get started for
      an investor's own account that hasn't finished or skipped it: welcome
      -> four screens of two tap questions each (the profile's required
      answers, saved on Next, kept on Back) -> a rough goal (skippable) ->
      their investor type and example mix -> bring holdings in (paste, CSV,
      or the example, which opens Home). Progress dots; each screen slides
      in (still when the device asks for less motion). Where they are is
      saved in their settings. No goal screen for a managed client, no
      bring-it-in screen when they can't import. Get started then shows the
      full page, with "Go through the first steps again". Learn more links
      to Investor.gov and the CFPB on three screens.

### S1b. Get started, one waypoint at a time - S
- [x] **Built** - your direction in one line (the full card in a window); a
      route strip of the seven waypoints (✓ when reached) to jump between;
      one waypoint card at a time with previous / next; marking one done
      moves on; Learn the basics as six topic cards that open in a window.

### S2. A calm Home - M - tried and undone (Oct 1): the full Home stays;
a light cleanup instead, when we know what bothers you.
The value and today's move, your route's next step, and a few tiles -
Performance, Your mix, Holdings, Alerts - each opening its detail in a
window. The accounts comparison and column settings only in the full view.

### S3. A calm Plan page - M
- [x] **Built** - the goal card stays on top (goal, on-track chip,
      progress bar, one summary line, Edit goal); the rest is in tabs, one
      at a time: How it's going (the projection and assumed return), What
      if, Contributions, Money in vs growth, Target mix, and Proposals for an
      advisor on a client's plan. Each tab is a Streamlit fragment, so
      moving a slider or saving a contribution redraws only that tab, not
      the whole page.

### S4. A shorter menu for investors - S
Home, Plan, Ask Northwend, Learn (Get started) and More (Watchlist,
Activity, Income, Account, About) - the rest is one tap away, not gone.
- [x] **Built** - the investor's menu is Home, Plan, Ask Northwend and Learn
      (Get started), then More - a small window with Watchlist, Activity,
      Income, Account, About (and Advisor notes / Admin when they apply); More
      looks selected on those pages. The phone tab bar matches. Advisors keep
      the full menu; old ?page=get-started links still open Learn.

### S5. Learn more links - S
A small "Learn more" next to the ideas the app explains (index funds,
diversification, expense ratios, account types, risk) to the matching page
on Investor.gov, FINRA or the CFPB.
- [x] **Built** - one table in `learn.py` (`LEARN_MORE`: topic -> label,
      address, site; only Investor.gov, FINRA and the CFPB - a test checks)
      and `learn_more(topic)` in dashboard.py, a small caption link. On the
      Learn the basics cards, Get started (example mix, open an account,
      comfort with risk), first steps, the fee check, Plan (projection, What
      if, Target mix), Home (allocation, drift, accounts), storms and Income
      (dividends).

### S6. The other pages - M
The same pass over Income, Activity, Watchlist and Ask Northwend: a summary
first, detail in a window.
- [x] **Built** - each page leads with a few numbers and one next step:
      Income (expected next 12 months, next payment, received), Activity
      (money added, bought, sold in the last year, the 5 latest moves),
      Watchlist (count, biggest rise and fall, the 5 biggest moves today),
      Ask Northwend (suggested questions and the chat; profile and the
      printable plan in windows). Tables and charts open in windows. "Show
      everything" (Account > How pages look) brings back the full pages;
      advisors always get them.

---

## The Northwend expedition - a theme with some adventure - after S2

**Why:** the app works but looks plain. Northwend already speaks of routes,
waypoints and a guide; lean into it so the journey feels like an
expedition you're on - regions to cross, milestones to clear, gear earned
along the way - with richer looks and smoother movement between pages.

**Guardrail:** rewards are for learning and good habits - finishing a
lesson, setting a goal, adding money as planned, holding steady through a
drop - **never** for trading more, taking more risk or chasing returns
(the kind of "game" regulators warn about). No streaks that nag, no
losing anything for missing a week, and everything stays readable and
calm with motion turned off.

### T1. The look, designed in Claude Design - M - needs you
Take the Northwend design system further in Claude Design: an expedition
palette per region, illustrated backgrounds (a soft topographic map, the
route drawn across it), page headers that feel like map plates, icons for
milestones and gear. You review the mockups; the app's theme and styles
follow (as L2 did).
- [x] **Designed and first pass in the app** (Oct 1) - mockups on the
      "Northwend expedition look" canvas (Home on a night map, Get started
      as a map, a milestone reached, the kit), approved; the design
      system's brand book gained "The expedition" (map, trail, regions,
      map plate, milestones and gear). In the app: faint contour lines
      behind every page (static/topo-*.svg, built into the styles as
      Streamlit serves static files as plain text); the route drawn as a
      trail (route.trail_html: one image per theme, since st.html strips
      inline SVG) with the region you're in on Home and Get started; the
      map plate above those titles ("The foothills · your expedition").
      Milestones and gear are T3.

### T2. Movement between pages - S
Pages and windows that ease in instead of appearing all at once; the
route's progress drawing itself forward when a waypoint is reached; small,
quick, and off when the device asks for less motion.
- [x] **Built** - ui_enhancements.js watches the address's ?page= and
      replays a short fade-in on the page (opacity only: a transform would
      unpin the phone tab bar), and replays a left-to-right draw of the
      trail when its picture changes on the same page (a waypoint reached).
      Windows already ease in (Streamlit's own). Both stop when the device
      asks for less motion.

### T3. Milestones and gear - M
The route as regions with a milestone at the end of each ("First camp: a
goal set", "The foothills: your first statement in", "Storm weathered:
held steady through a 10% drop"). Clearing one earns a piece of gear for a
small kit shown on Home and the Account page (a compass, a map, boots, a
lantern...) - looks only, nothing to buy. A "Your expedition" window lists
what's cleared and what's next.
- [x] **Built** - `gear.py`: eight pieces, each earned by learning or a
      steady habit, worked out from what the app already knows - map
      (profile), compass (goal), tent (the basics), rope (practice money),
      boots (a real statement in), lantern (money added three months
      running), storm cloak (no selling through a 10% drop), summit flag
      (goal reached). Only what's been shown is kept (prefs gear_seen); an
      account from before gear existed takes what it has quietly. Home:
      Your kit (earned icons, the next one to earn, See your kit). A
      "milestone reached" window the first time one is earned, on Home or
      Get started (kept open through live-price redraws until Continue).
      Icons are images per theme (st.html strips inline SVG).

### T4. Storms - S
When the market drops sharply, the guide treats it as a storm to wait out:
a calm note on Home with what drops have looked like before and why
long-term investors usually hold - and a milestone for holding steady,
never for selling or buying.
- [x] **Built** - `storms.py`: the current holdings priced at each close
      (perf.daily_values - money in or out never looks like the market)
      against their 90-day high; 5% down is "rough weather", 10% "a storm".
      A calm note on Home (nothing needs doing; the storm cloak for holding
      steady), "What storms have looked like" (six past S&P 500 drops and
      how long each took to pass), Ask Northwend, and "Hide for now" (back
      if it gets worse or after a new high).
- -> Oct 5: the storm note becomes the trigger for **R4 Storm Shelter** (the
  person's drill answer, ledger and log; no trade button).

---

## Direction - a guide, not a brokerage - in this order

The app opens on what you own (value, gains, charts), which is what a
brokerage shows. A guide opens on where you're going and what to do next.
Two experiences in one app: **Investor** (new investors, and clients of an
advisor) and **Advisor**, each with its own home, navigation and tools.

**Guardrail for every item:** Northwend is education, not advice. For
investors, direction comes as investor types, example mixes and explanations
("people like you often..."), never "buy fund X". Advisors make
recommendations to their own clients - the app is their tool. Raise this in
the item-5 disclosures review before G3 and G4 go live.

### G1. Two experiences: Investor and Advisor - M
**What:** sign-up asks "I'm investing for myself" or "I'm a financial
advisor". Investors (and clients) get the investor app: route home, Plan,
Ask Northwend, holdings. An advisor sign-up *requests* advisor access (firm
and CRD/licence number); you approve it (`manage_users.py`) after checking,
and until then they use the investor app. Advisors get the advisor app: book
overview home, Clients, proposals, reports. Same codebase; navigation and
home chosen by the account's role. Clients keep seeing their advisor's notes.
One colour scheme for both (one brand; colour alone is a weak signal): the
role shows as an "Advisor" chip under the name in the sidebar, the advisor
home is titled "Your clients", and an advisor inside a client's account
always sees a bar "Viewing <client>'s account · Back to your clients". In-app
admin tools, if ever added, get their own labelled Admin area for your
account only.
**Done when:** each kind of account lands in its own experience, and nobody
can make themselves an advisor.
- [x] **Built** - sign-up asks "For my own investing" / "I'm a financial
      advisor" (`?signup=advisor` preselects it; the website's For advisors
      button uses it); an advisor's firm and CRD/licence go to
      `advisor_requests` and to support@ by email; `manage_users.py
      advisor-requests`, `make-advisor` (approves), `decline-advisor`. Advisor
      app opens on Your clients with an Advisor chip; the "Viewing <client>'s
      account · Back to your clients" bar on every page while inside a client.
      Investor app unchanged until G2. Disclosures list the advisor details.

### G2. "Your route" home for investors - M
**What:** the investor home opens on the goal and the next step ("74% of the
way to your house deposit · next waypoint: choose a monthly amount"), the
waypoint route and one nudge; the portfolio value and charts move below.
Mostly re-arranging Plan, Get started and Dashboard pieces that exist.
- [x] **Built** - the page is "Home" for investors ("Portfolio" for an
      advisor's own); a "Your route" card first: goal, progress and status,
      the Get started waypoints as dots to the goal, and one next step with a
      button and Ask Northwend. `route.py` picks the step: goal, profile,
      holdings, monthly amount, closing a gap, drift, stale holdings (45
      days), the next waypoint, then reached / on track. Clients aren't asked
      to do their advisor's part.

### A1. Admin portal - M
**Why:** looking after accounts shouldn't need the command line or code
changes. **What:** an Admin page for admin accounts only (made only from the
command line: `manage_users.py make-admin <login>`): advisor requests with
Approve / Decline; every account's login details (role, email confirmed,
advisor or clients, created, last sign-in, locked); per account: password
reset email or a temporary password, unlock, make/remove advisor, AI limits,
link to an advisor, delete with all its data; add an account (an email gets
a 7-day "choose your password" link); this month's AI use; and a switch to
show your own account as the investor or the advisor app. Logins only - no
holdings or plans (the disclosures say so).
- [x] **Built** - `admin.py` (data side; a test checks delete covers every
      table with account data), `views/admin.py`, `users.is_admin` and
      `last_login_at`. **Needs you:** `make-admin` on your own account (live
      and staging), then use the Admin page instead of `manage_users.py`.
- [x] **Easier to turn on, and a System panel** (Oct 1) - an admin can also
      be named in the app's Secrets (`NORTHWEND_ADMINS = "admin1"`), no
      command needed; `manage_users.py` takes `--db` before or after the
      command, defaults to `PORTFOLIO_DB`, and says which database it
      changed (a missing `--db` used to change the local file silently).
      Admin page: a System panel (this copy, version, database host,
      email, keys set or not, last price update, admins; Clear cached
      data, Send me a test email). Fixed "Last sign-in" showing None.

### G3. "Find your direction" for beginners - M/L
**What:** the front door for someone with nothing invested yet: a short,
friendly questionnaire (goal, timeline, comfort with ups and downs, emergency
fund, debt) ending in an investor type (e.g. Steady builder, Long-horizon
grower) with a plain explanation, an example mix for that type and the kinds
of funds that usually fill it; then into Get started. Builds on the profile
questions and model portfolios already in the app.
- [x] **Built** - `learn.investor_type()`: Foundation builder (emergency fund
      or high-interest debt first), Short-term saver (under 3 years),
      Careful preserver, Balanced navigator, Steady builder, Long-horizon
      grower - from the readiness check and the example mix, so they always
      agree. Get started opens with "Find your direction" until the questions
      are answered, then a "Your direction" card (type, explanation, example
      mix, kinds of funds, a note on drops, Ask Northwend); the Home route
      card names the type. Education wording only (a test checks).

### G4. Advisor proposals - L
**What:** an advisor builds a recommended mix for a client and shows today
vs proposed side by side (risk, diversification, costs, projected range);
shared to the client in the app and as a PDF; the client sees it under
their advisor's notes. The core of "helping clients grow".
- [x] **Built** - `proposals.py` + `views/proposals.py`: on a client's Plan
      page the advisor drafts a mix (start from today's, the current target or
      a model portfolio), with a note in plain words; save as draft or share.
      Each proposal compares today vs proposed: by asset class, assumed
      long-run return, how each would have done in 2008 and 2022 (rounded
      index figures), and the value at the goal date - with the assumptions
      stated. The client answers on Advisor notes ("Let's go ahead" / "Not
      right now" / Ask Northwend to explain); an accepted one can become the
      target mix in one click; a one-page PDF either side. Nothing is traded.

### G5. "What if" playground - M
**What:** sliders for monthly amount, years and mix showing a range of
outcomes ("adding 50 a month more gets you there 2 years sooner"), for
investors on their own goal and for advisors in meetings.
- [x] **Built** - a "What if...?" panel on the Plan page: monthly amount,
      years, stocks share and a one-off amount; the projected value and
      range, the difference from the current plan, when the goal would be
      reached and how much sooner or later, on the plan's projection chart.
      Nothing is saved unless "Use $X a month in my plan" is pressed (owners
      only). Assumptions shared with proposals (`plans.mix_return`).

### G6. Client onboarding by link - M
**What:** the client answers the goals and risk questionnaire from their
setup link, so the advisor has a ready profile before the first meeting.
- [x] **Built** - Add client takes an email (it becomes the login and the
      account's email); Client login gets "Email <address> a setup link",
      sent from Northwend in the advisor's name; after choosing a password the
      client lands on Get started with a welcome asking for the goals and risk
      questions ("your advisor sees your answers"). Opening the link counts as
      confirming the email the advisor gave.

### G7. Meeting prep - M
**What:** one click before a review: what changed since the last one, goal
progress, drift from target, open notes, and talking points drafted by the
AI for the advisor to edit.
- [x] **Built** - a "Meeting prep" panel at the top of a client's Advisor
      notes page (advisor only, `meeting.py`): last review and days since,
      value change since then, holdings added / reduced / sold out (from the
      snapshots either side), goal status, drift, open next steps, proposals
      waiting or accepted. "Draft with Northwend" writes talking points from
      percentages and facts only (its own AI allowance, "prep": 20 a month,
      advisors 100); edit and "Save as a private note". Disclosures updated.

### G8. Client progress reports - M
**What:** a clean monthly or quarterly summary an advisor sends each client
(growth, goal progress, what's next), in the app and as a PDF; email once
the email side allows it.
- [x] **Built** - `reports.py` + `views/reports.py`: a "Progress report"
      panel on the client's Advisor notes page (last month, last quarter or
      since the last report; a live preview; an optional message); Send saves
      it with the figures as they were, and emails the client that it's
      waiting - no figures in the email. The client reads reports on Advisor
      notes (new ones marked), with a PDF. Values come only from close to the
      period's edges; otherwise the report says it doesn't know.
- [x] **To several clients at once** (Oct 1) - Your clients > Send
      progress reports: a period, the clients (those who already have this
      period's report start unticked), one shared message; each client gets
      their own figures and a "report waiting" email.

### G9. Book overview for advisors - M
**What:** all clients in one view, sorted by who needs attention (off track,
drifted, review due, inactive) - the advisor home in G1, grown from the
weekly review summary.
- [x] **Built** - Your clients (already sorted by what needs a look) gains
      "Proposal accepted" (first - it's on the advisor) and "Not signed in
      for N days" (60+, only for clients who used to sign in) as reasons; a
      Show filter (Everyone / Needs a look / Review due / Waiting on you) and
      a search; each card also shows a proposal waiting, the last report and
      the last sign-in.

### P1. Positioning: "we don't sell investments" - S
**What:** say plainly, where people decide to trust Northwend, that it has
nothing to sell them - the guide-not-salesperson story.
- [x] **Built** - website home: "nothing to sell you" under the sign-up
      button, and two checks under "A guide, not a salesperson" (no funds,
      commissions or trading fees; no one pays to be mentioned). A new "How
      Northwend is paid" section in the disclosures (in the app and on the
      About page). One line each on Create account and Get started.

### G10. Fee check - M
**Why:** fund costs are easy to miss and add up over decades; few free
tools show them in dollars.
**What:** each fund's expense ratio (from the fund details the nightly sync
already reads) as a yearly cost in dollars at today's value, the
portfolio's total, and what that adds up to over 10 and 30 years. Beside it,
what a typical low-cost fund of the same kind charges - as education, never
"switch to X". Funds without a known expense ratio say so. One window from
Home (after S2) and a step in Learn.
- [x] **Built** - `fees.py` + `views/fees.py`: a Fee check card on Home
      (the yearly total in one line) opens a window - each fund's expense
      ratio in dollars a year, the total, and over 10 / 30 years at 6% (fees
      plus the growth they'd have earned); beside each, what low-cost index
      funds of its kind often charge. Unknown fees, single stocks and cash
      say so. Also under Learn the basics. The nightly sync now keeps
      `security_info.expense_ratio` (a fraction).

---

## Find an advisor - a marketplace for online advice - later

Like online therapy platforms, for money: investors can go it alone (the
default, free) and, whenever they want a human, find a verified advisor and
meet online. Advisors get clients and the tools in G1-G9 to serve them.

### M0. Legal and business model first - needs you
**Why:** paying or being paid for client referrals, advisor ratings and
testimonials, and taking payments for advice are all regulated (in the US
the SEC Marketing Rule and state rules for "promoters"/solicitors; whether
Northwend itself must register depends on how it is paid and what it
recommends). **What:** with a securities lawyer: how Northwend earns
(advisors pay a subscription or listing fee - simplest - vs a share of
fees or per-client referral fees), advisor terms of use, what Northwend may
say about an advisor, insurance. Every M item below waits for this.

### M1. Verified advisor profiles and a directory - M
Built on G1's checked advisors: a profile (credentials such as CFP or CFA,
CRD, fee model - flat, hourly or a share of assets - specialties such as
first-time investors or retirement, languages, availability) with
"licence checked on <date>"; investors browse and filter.

### M2. Get matched - M
A short "what do you want help with" questionnaire (reusing G3's profile)
that suggests a few advisors who fit: specialty, fee model, budget.

### M3. Request, consent and connect - M
The investor sends a request; when the advisor accepts, they become the
advisor's client. The investor chooses what to share first (holdings,
plan, goals) and can leave at any time (their data stays theirs).
Replaces "advisor sees everything" for marketplace clients.

### M4. Secure messages - M/L
Client-advisor messages in the app, kept for the advisor's record-keeping
duties and exportable.

### M5. Meetings - M
Booking against the advisor's availability, video through a link to Zoom,
Google Meet or Teams (not built in-house), email reminders.

### M6. Payments - L
Clients pay advisors through Northwend (e.g. Stripe Connect) - only once M0
settles how this may work.

### M7. Reviews - later
Client reviews of advisors, only in the form M0's advice allows.

Entry points for the investor app: "Want a human? Find an advisor" in Get
started, the Plan and Ask Northwend - always optional.

---

## Polish - smaller items, any order

- [x] **Phone navigation** - a bottom tab bar on narrow screens (Home, Plan,
      Sage, Watch or Clients, More); the sidebar stays on wider ones.
      **Phone and dark pass (Oct 2):** every page checked at 390px and in dark
      mode - the summary boxes no longer run off the screen (labels wrap);
      a ticker's stats two per line in reading order; captions and Learn more
      links, selected tabs/segments and slider values pass AA in dark, the
      light warning text too; the sidebar handle hides under an open window.
      Then (Oct 2): a phone summary box sizes its amount to fit and wraps a
      long one after a comma ($1,000,000+ no longer cut off); yields and
      shares of the portfolio read "0.87%", not "+0.87%" (changes keep their
      sign); money axes "$0", "$1.5k", "$1.2M" (were "$0.0", "$1.0k").
      Plan's tabs wrap onto two lines on a phone (no sideways scroll); the
      metric change chip and slider end labels pass AA in light mode
      (`--pt-ink-muted` / grayTextColor).
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
      **Again (Oct 2):** the login's row read once (`auth.login_facts`), the
      holdings, their source and the watchlist on one connection, price history
      on one, the profile once per run; Your clients, Admin, Account and About
      skip the holdings; Your clients reads logins, proposals, reports and
      settings once for the whole book. Home 49 -> 35 queries (21 -> 8
      connections), Your clients with 25 clients 408 -> 216; every page draws
      the same. A test caps both. Left for later: live_prices.freshen re-reads
      what load() has (~3 queries a run - it's price fetching, so a plan
      first), and a whole-book account_summary (~8 queries per client).
      **Whole book (Oct 2):** `overview.account_summaries` reads each table
      once for every client (`user_id IN (...)`), sharing `_summary` with the
      one-client version - Your clients is 23 queries with 1 client or 25
      (was 216); a test checks it doesn't grow with the book. The minute's
      price check (live_prices.freshen) takes the page's holdings and
      watchlist (`known=`) instead of reading them again: 3 fewer queries a
      minute per open page; same fetches and prices (a test compares).
      **Then:** the login's users row is read once a run - the two-step gate
      reads it first (as before, fresh every run) and the run reuses that
      read (`_gate_read`; windows and fragments read fresh); Income on one
      connection; Ask Northwend's profile and memory in one query; a client's
      model portfolios once. Ask 21 -> 17 queries, Account 11 -> 8. Schema
      setup on Postgres batched (same statements, same order): 73 -> 7 round
      trips per process start. Proposed, not done: quotes saved in fewer
      statements (price fetching - a plan first).
- [x] **Split dashboard.py** - one file per page in `views/` (dashboard.py 4,504 ->
      1,657 lines). Code moved unchanged; every page drew identically before
      and after (18 page views compared). (M)
- [x] **Accessibility** - contrast, keyboard use and screen-reader labels on
      the custom HTML parts (hero, chips, bars). (S) - up/down/warning colors
      pass AA contrast in light and dark (switching with the theme), dim text
      darkened; bars hidden from screen readers where the legend says the same,
      described where it doesn't; arrows and icon-only buttons named; less motion
      when the device asks for it.
      **The S6 summaries too (Oct 2):** stat boxes and Activity's latest moves
      read as lists; "+$215.00 gain" / "loss" in words, not only color;
      watchlist prices say what they are; a button with words is named by its
      words (no "open_in_new" read out), icons beside text hidden. The older
      .pt-stats rows (Home hero, Plan, Get started, Clients) too, since.
      Learn more: bonds and ETFs under a fund's name on its ticker page,
      dividends beside its yield - every topic now placed (a test checks).
- [x] **Advisor invites** - a one-time setup link for a new client instead of
      sharing a password. (M) - Client login > Create setup link; the client
      picks their own password and is signed in. Works once, 7 days, only a hash
      stored; a new link replaces the old, and it can be cancelled.
- [x] **Review reminders** - a weekly summary for advisors of clients due a
      review or needing attention. (M) - in the app: the first visit each week
      opens with reviews due, coming due in 14 days and who else needs a look,
      each with Open; Got it hides it until Monday (any device). Always on the
      Clients page. Email could follow once there's an email service and domain.
      **Email (Oct 1):** a Monday email to each advisor - counts only
      (reviews due and coming due, accepted proposals, open next steps), no
      client names or figures; once a week, only when there's something to
      say, confirmed emails only, off switch under How clients see you.
      `weekly_email.py`, a Monday job in scheduled-sync.yml. **Needs you:**
      GitHub secrets `RESEND_API_KEY` and `APP_URL` (skipped until set).

- [x] **D1. Export everything** - Your data (sidebar) > Prepare my data,
      then Download: a ZIP of CSVs with the account's own data (holdings and
      their history, plan, answers, settings, watchlist, AI use counts) and,
      for a client, what their advisor shared. Never passwords, sign-in or
      email-link tokens, private advisor notes or anyone else's data
      (`export.py`; a test makes every new account table choose: exported
      or left out on purpose). In the disclosures and on the About page.

- [x] **Account page** - one place for your own account (Account, in the
      menu for everyone): what's on it (name, login, email and whether it's
      confirmed, kind of account, member since, devices signed in); your
      name (shown in place of your login, and to your advisor); change or
      add your email (password first, then a link to the new address -
      nothing changes until it's opened; the login follows when it was the
      email; the old address is told); change password and sign out other
      devices; download your data and delete your holdings (moved from the
      sidebar); delete your account (password and DELETE; not for admins,
      advisors with clients, or managed clients).

### From the persona walkthroughs (Oct 2)
Seven people walked through the site and app in a browser (curious visitor,
beginner, scattered accounts, dividend investor, near-retiree, advisor,
phone-only beginner). What they found, fixed in this order:

- [x] **Import and privacy bugs** - worked-out buys and sells were saved
      with the file's full account number (holdings were masked); account
      names are now masked before anything is compared or saved, and a
      one-time clean-up at start masks rows saved before (checked on
      Postgres). Re-importing a file no longer shows everything as new and
      records fake sells; an account's first save is where it starts, not
      purchases; replacing the example isn't a sale. The screenshot reader no
      longer crashes (and counts only a read that ran); "since your last
      visit" starts again after a save; a row with no ticker is named in the
      review; "—" for a missing cost; typed rows default to "Other".
- [x] **Several brokerages** - every import replaced all saved holdings, so
      a Robinhood paste deleted the Fidelity 401(k). Now an import (CSV,
      paste, screenshots, by hand) replaces only the accounts in it; every
      other account carries forward (`changes.carry_forward`,
      `portfolio.prepare_save` / `save_prepared`). The review says
      "Updating" and "Kept as is"; what changed and worked-out trades cover
      only the accounts in the file. Paste asks which account and adds to
      the form (the broker guessed from the file's layout or name, never a
      fund's name); a file older than the current holdings is folded in,
      with a note and no trades; "Remove this account" on Home (no sells
      recorded). The example and percentages portfolios are never merged.
      Left: the command line's `portfolio.py import` still replaces its date.
- [x] **The beginner path** - with no holdings, Home showed a technical
      "upload your positions CSV" page everywhere. Now Home shows the route,
      their direction and calm options (practice money, an example, "I
      already invest"); Watchlist works without holdings; Income and
      Activity say one friendly line (`views/start_home.py`). Learn's "Open
      an account" is a checklist with "What your first buy looks like" (no
      more Learn <-> Home loop); the example doesn't count as an opened
      account (or a reached goal). First steps: a goal can't be lost, "no
      account yet - show me how" for the new, Next reachable on a phone.
      The example mix no longer overflows; Plan says "Starting out", not a
      red "Behind", with nothing invested; readiness questions answered in
      place (debt and employer match also on the safety-net slide); one
      welcome line after sign-up instead of three banners. Menu order is the
      same before and after holdings.
- [x] **The route, from the owner's own test** - each waypoint says what
      it's for; a progress bar ("Step 3 of 7 · 2 complete"); one big
      "Complete this step" button (small Back and "Skip for now"), no "Mark
      as done". "Set a goal" stays in Learn as four short parts (the goal as
      "I want to have $___ by ___", the monthly amount, how it's going, the
      mix); Plan has "Back to your route". Labels say what each number is
      for ("How much you'll invest each month"). A "Suggested starting
      point for your answers" on every slider and the target mix
      (`learn.suggestions`), never called a recommendation. The kit says
      what each piece is for and exactly how it's earned. Fixed on the way:
      the assumed-return slider could save 2% while saying 6%.
- [x] **Typing holdings in** - separate boxes per holding ("Stock or fund
      (name or ticker)", "How many shares", "What you paid in total") with
      "+ Add another"; a name is matched and confirmed ("Did you mean Apple
      Inc. (AAPL)?") via Yahoo's search with a local fallback
      (`ticker_search.py`), never silently guessed. Paste and screenshots are
      their own tabs. "Not sure yet" shows the example-funds card
      (`starter_funds.py`): their mix's parts, each with broad index funds
      from three providers - "examples to learn from, not recommendations" -
      to watch or try with practice money.
- [x] **A top bar instead of the sidebar** - five tabs always in view (Home,
      Plan, Learn, Ask Northwend, Money; + Your advisor for a managed
      client), the same on the phone's bottom bar, nothing behind a "More".
      Money is one page with Income, Activity and Watchlist tabs (each keeps
      its own address). Account, About, Admin and Log out are in the name
      menu at the right; Add holdings sits beside it. Advisors: Clients,
      Portfolio, Plan, Notes, Money, Ask.
- [x] **Learn, then Start investing** - the route has two stages. Learn (the
      six steps) is required only for the brand new; anyone with some
      experience or their own holdings starts on Start investing, with Learn
      marked optional. Start investing: Choose a brokerage (what to compare,
      then well-known brokerages alphabetically, names and links only - "not
      paid by any of them, doesn't rank them"), Open your account, Your first
      investments (the example-funds card under "Not sure what to start
      with?"), Bring it in. A managed client's Start investing is just Bring
      it in, with their advisor. Old account-checklist ticks carry over.
- [x] **The website for new investors and advisors** - redesigned in the
      design system's expedition look (a Claude Design canvas first, then
      ported): the app's own contour lines behind the top of each page, the
      route drawn as a trail, regions in italic. Home speaks to three groups
      (new to investing, already investing, advisors) and its "How it works"
      follows the app's route. New pages: /new-to-investing (the two stages,
      practice money, what a monthly amount could grow to and what a fund's
      fee costs - tables worked out by build.py at one stated, hypothetical
      rate, since the site runs no scripts - brokerages as equals, common
      questions) and /advisors (the tools as they are, the client side, how
      access works, questions). A phone menu with no script, a new footer,
      a sitemap.
- [x] **Advisor basics, part 1: getting an advisor and their clients set up**
      - approval and decline emails (`admin.approve_advisor` /
      `decline_advisor`, from the Admin portal and manage_users.py; the
      owner's request email links to the Admin portal). Client names and
      households (`advisor_clients.client_name`, the advisor's own name for
      the client, renamable), shown everywhere the advisor sees a client.
      One "Add and send invite" step, the invite from the advisor's name and
      firm (`mailer.sender`; asked for before the first invite). Report
      emails go only to confirmed emails, like proposals (Oct 4; a client
      who hasn't set up their login isn't emailed - the advisor is told to
      send a setup link). Your clients: no
      Viewing bar, plain-text emails, each client once in This week, and
      "N alerts" counts only real moves and losses (gains don't count).
      Message clients: one message to all (or some) clients, saved as a note
      they see, with a short "sent you a message" email (never the text);
      the same message can't go twice within 10 minutes.
- [x] **Advisor basics, part 2: the client's side and the AI's errors** -
      proposal emails (the client when one is shared, the advisor when it's
      answered; no figures or titles, confirmed emails only). A client mode
      for an advisor's clients (`CLIENT_MODE`): no example funds anywhere,
      no beginner trail or practice money; Home's next step is the
      advisor's ("Your advisor has a proposal waiting for you", a new
      report, questions, bringing statements in); clients land on Home.
      Friendly AI errors everywhere (busy, or not available - details to the
      log only, `ai_usage.failure_text`), and the allowance counted only on
      a successful answer. Fixed: chat and meeting prep on an empty account
      raised a NameError.
- [ ] **Next, from the walkthroughs:** website: an inflation table and the
      direction quiz before sign-up (needs the app, or a script the site
      doesn't allow); the public disclosures to mention advisor-sent emails
      (needs a LAST_UPDATED bump - owner's call).
- [x] **Total return with dividends, and retirement income** - Home's gain
      is labelled Price change, with Total return, with dividends beside it
      when dividends are known (`income.received_while_held`: the imported
      activity history first, else Yahoo's per-share payments times the
      shares held on each ex-date; the caption says which); a holding's
      details and the holdings table too. A Retirement income tab on Plan:
      what the portfolio pays today, steady withdrawals at 3/4/5% as rules
      of thumb (not a promise; taxes, fees, inflation and Social Security
      not included), and how long a yearly amount could last at one stated
      rate. It leads for someone 65+, retired or drawing income, or with a
      retirement / income goal within 10 years (`plans.retirement_first`).
- [x] **Fund overlap and yield on cost** - a Fund overlap card on Home (like
      Fee check; detail in a window): which funds share their largest
      holdings, and what you own most of with funds looked through ("Apple:
      about 12% of your portfolio, through VTI, VOO and directly"), from each
      fund's top 10 holdings on Yahoo (`fund_holdings.py`, fetched only when
      the window opens, stored weekly in `fund_top_holdings` - shared market
      data). Honest about being a floor; never a suggestion to buy or sell.
      Income's by-holding table gets yield on cost (this year's dividends as
      a share of what you paid; blank when the cost is unknown, none for a
      percentages-only portfolio).

### Legal fixes, and the overnight plan (Oct 4) - approved by the owner
Northwend stays free (no compensation from anyone), which keeps it clear of
investment-adviser registration; these keep it educational and give advisors
what their record-keeping needs. Batches of at most two agents; bug fixes
release to main when green, new features wait on staging for the owner.
- [x] **0. Legal fixes** - advisor side: clients agree to the disclosures at
      the setup link (old accounts asked once at sign-in; `users.terms_via`);
      notes archived, not deleted, edits keep history; export one client's
      record or all. Investor side: fund types (not tickers) wherever it's
      worked out from the person's answers - named examples only in a general
      read, the same for everyone (`starter_funds.py`); `advisor.GUARDRAILS`
      in every AI prompt (a test pins every AI call), and
      `scripts/ai_guardrail_eval.py` to try them against the real model;
      "may be delayed" price-source labels; Terms / Privacy / Security drafts
      in `docs/legal/` (unpublished, for a lawyer). Checked on a real Postgres,
      upgrading a database built with the day before's schema.
      Left for the owner: proposals can still be deleted once shared.
- [x] **1. Postgres check** - the live app runs on Postgres but every test
      ran on SQLite: `tests/test_postgres.py` (25 tests, skipped unless
      NORTHWEND_TEST_PG is set) runs the write paths of every feature, the
      27-page sweep and an upgrade from the Sep 30 schema on a real Postgres;
      the `postgres-tests` CI job runs it on every push. Fixed what it found:
      the column back-fill looked at every schema (a missing column could be
      skipped); a taken username left the connection unusable (bulk create
      stopped); trading volumes over 2.1 billion (crypto) crashed the nightly
      history sync - now BIGINT, widened once on old databases; quoted text
      with `?`/`:` or a literal `%` broke the SQL translation.
- [x] **2. Fresh-eyes bug and security pass** - 14 fixes, each with a test
      (`tests/test_bug_pass.py`): CSV formula injection in every export (and
      Streamlit's own table "Download as CSV" hidden - it doesn't escape);
      advisor notes tied to the advisor who wrote them (a new advisor can't
      read or change the old one's private notes); limits on invite and
      "something's waiting" emails, and on sending the same report twice;
      shared proposals archive instead of delete and share only once; names
      cleaned of line breaks in email From names and subjects; text flowing
      into AI prompts flattened and marked as data; admin-page markdown
      escaped; the What-if slider masked with hidden amounts. Re-walk: one
      small banner after an advisor's sign-up; a used confirm link says
      "already confirmed"; the paste/type window starts empty and shorter;
      goal dates default by goal type (`plans.goal_years_default`); chart
      toolbars hidden on phones. Not fixed, listed: "Add client" reveals
      whether an email has an account; a double click on Save and share makes
      two proposals; markdown links in advisor notes; an odd "since the last
      report" label on the same day.
- [x] **3. Stress test your mix** (Plan) - 2008, 2020, 2022, hypothetical: a Stress
      test tab (`stress.py`), the mix now or the target, drop and rough recovery.
      -> Oct 5: extended by **R4 Storm Drill** (a field after the 2008 run).
- [x] **4. Contribution helper** (`next_deposit.py`, Plan's Target mix tab; a
      line and button on Home's drift notice) - where the next deposit could go, by asset
      class (never a ticker), to move toward the target mix without selling.
- [x] **5. Cash check** (`cash_check.py`; Home's one "Your money, checked" card now
      holds Fee check, Fund overlap and Cash check) - how much sits in cash; a sweep account vs a money
      market fund, explained (no fund named).
- [x] **6. Free money check** - an employer 401(k) match calculator
      (`employer_match.py`; from Learn's readiness step and Plan's Contributions tab).
- [x] **7. Advisors** (`client_csv.py`, `advisor_demo.py`, `advising.end_relationship`;
      `former_clients` keeps the advisor's records) - add clients from a CSV with invites; a demo book
      while approval is pending; "End relationship" (the client keeps a
      self-directed account and is told).
- [ ] **8. Notes to future you** - a private note on a holding or the plan,
      shown back on Home when markets drop.
      -> Oct 5: stays; feeds **R3 The Expedition Log** and **R4 Storm Shelter**.
- [ ] **9. Year in review** - a private yearly recap, and a version to share
      with no dollar figures.
      -> Oct 5: stays, as December in **R7 The Four Seasons**; **R3**'s log
      becomes its main source.
- [ ] **10. Account map** - an "if something happens to me" binder: every
      account (brokerage, type, last 3 digits, rough value, who to call),
      notes for family, a PDF only you download, and a guide to finding old
      401(k)s and unclaimed accounts.
      -> Oct 5: the finding-old-accounts half becomes **R9 Lost & Found** (and
      moves up to Tier 2); the binder stays here.
- [ ] **11. Monthly check-in** - a 3-minute routine that counts toward a
      habit milestone; an optional reminder email (off unless turned on, no
      figures).
      -> Oct 5: **absorbed by R1 The Monthly Walk** (the walk is the check-in,
      redesigned around a verdict); higher priority - Tier 1, first in the
      next two weeks.
- [x] **12. Money going out** (owner, Oct 5; `plans.py` money_out, the `money_out` table)
      - stops adding money once withdrawals start; checks it lasts to 95;
      not on the What if tab or Your clients yet. Planned expenses (one-off or
      repeating, on dates) and regular withdrawals for income (monthly, from
      a date, optionally rising with inflation) on the Plan page; one
      month-by-month projection with money in and out, so the goal check,
      chart, retirement tab ("how long it lasts") and Home's on-track signal
      all include them; a calm note when withdrawals outpace growth.
      -> Oct 5: stays; the base that **R11 Pay Yourself** builds on.

## The Ritual - Northwend's primary direction (Oct 5)

From a product-strategy session on retention and differentiation. Northwend's
two deliberate "weaknesses" - no account linking and no revenue from anyone -
are the two things every competitor is structurally unable to give up. That is
now the lens for prioritizing features:

1. **A manual holdings update is a moment of attention we get to design.**
   Aggregators spend money removing that moment; we make it the product.
2. **We can say "nothing to do" and "you're fine."** Brokerages earn on
   activity, robos on assets, aggregators on upsell. None of them can end a
   session with "close the app."
3. **Nobody pays us to read anything, so we can read everything** - 401(k)
   plan menus, any brokerage's statement, fund fact sheets - with no angle.

Prefer features that exist *because* we don't link accounts and don't sell,
not in spite of it.

**The direction:** make the monthly update a designed ritual with a lasting
record (the Walk, the Ledger, the Log), and hang the rest of the product off
it. The Decoders (R5, R6) are the content the ritual points to.

**Hard constraints for every item below** (unchanged, restated):
- Free, paid by no one - flag anything that needs money to move.
- Education, never advice - no buy/sell/hold for a specific person; anything
  derived from a person's own answers speaks in kinds of funds, never tickers.
- Privacy first - no brokerage login; the AI never sees dollar amounts, share
  counts, account names or numbers. Any feature that reads an uploaded
  document parses it locally and strips figures before anything reaches the AI.
- Any brokerage equal, listed alphabetically.
- Calm by default - no urgency, no trading nudges; gamification rewards
  learning and habits only.
- Phone-first for beginners.

**How it absorbs the plan in flight** (overnight plan, Oct 4):
- **11. Monthly check-in** is absorbed by **R1 The Monthly Walk**: the walk is
  the check-in, redesigned around a verdict. Its reminder email becomes the
  Walk's reminder.
- **8. Notes to future you** stays. It feeds **R3 The Expedition Log** (a note
  added during a walk lands on that walk's line) and **R4 Storm Shelter**.
- **9. Year in review** stays as the December moment of **R7 The Four
  Seasons**. The **R3** log becomes its main source.
- **10. Account map**: its front half (finding old accounts) becomes **R9 Lost
  & Found**. The binder itself (who to call, notes for family, the PDF) stays
  with item 10.
- **3. Stress test** is extended by **R4 Storm Drill** (one field after the
  2008 run).
- **12. Money going out** is the base that **R11 Pay Yourself** builds on.
- **T4. Storms** (the storm note) becomes the trigger for **R4 Storm Shelter**.

### Tier 1 - build first

### R1. The Monthly Walk - M
**User problem:** no linked account means holdings go stale, and "update your
holdings" is a chore with no payoff. People don't know what to do after
looking, so they either do nothing or something reactive.
**Who:** everyone with holdings - scattered investors, income investors,
near-retirees. Advisors' clients walk too (see R15).
**What:** one "Walk" entry point on Home. It runs four steps:
1. update holdings (the existing add/update window);
2. see drift against the target mix;
3. one short read (from Learn, or what happened this month);
4. a rule-based verdict: **"Nothing to do this month"**, or one next step by
   asset class (e.g. "your next deposit could go mostly to bonds" - R1 reuses
   `next_deposit.py`).

No AI in v1. A streak counts walks completed, never returns. This absorbs item
11 (monthly check-in), including its milestone and optional reminder email
(off unless turned on, no figures).
**Retention loop:** the walk ends with a reason to come back - the verdict,
the log line (R3), the streak, the date of the next walk. Next month the
update is quicker because the walk remembers what changed.
**Effort:** M (v1: S-M; the pieces exist - update window, drift, Learn reads,
`next_deposit`).
**Principle risk:** "Nothing to do this month" is, in effect, a *hold* for a
specific person, and the next step is personalized allocation guidance. See
"Principle risks higher than stated" below.
**Mitigation:** the verdict is the person's own plan speaking ("Your target
mix is within the band you set - your plan says nothing to do"). The rule
(drift band, target) is theirs and visible, and it speaks in asset classes,
never funds. No verdict at all without a target mix ("set one to get a
monthly verdict").
**One-week test:** ship the Walk button and the verdict. Metric:
**second-walk completion within 45 days** of the first.

### R2. The Do-Nothing Ledger - S/M
**User problem:** staying the course is invisible; nobody records the times
you *didn't* panic, so the next drop feels like the first.
**Who:** anyone who has walked through at least one market drop; aimed at
investors in their first downturn.
**What:** every walk with no reactive change (no sale beyond the plan) gets a
ledger entry. During a drop, the ledger shows hypothetically what selling would
have cost, using the person's own mix on real prices. It is always labelled
hypothetical; it is a record, not a grade.
**Retention loop:** the ledger grows with every calm walk; each storm adds a
visible "you stayed" entry to come back to.
**Effort:** S/M (walk history + the stress-test price maths).
**Principle risk:** higher than it looks - see the list below. Hindsight can
cut either way (sometimes selling "would have helped"), and showing only the
winning side is cherry-picking.
**Mitigation:** show both directions honestly ("if you had sold on Mar 3: −X%
by now" *and*, when true, "+Y%"). Never "you made the right call". The ledger
records the decision, not its outcome. Percentages only.

### R3. The Expedition Log - S
**User problem:** a portfolio has no memory; every visit starts from zero.
**Who:** everyone who walks.
**What:** one auto-written line per walk, from percentages only (drift,
deposits by asset class, the market's move, "no changes"), plus any note the
person adds (item 8, Notes to future you). It feeds Year in review (item 9),
the storm note (R4) and Notes to future you.
**Retention loop:** the log is the lasting record; it gets more valuable the
longer you keep it, and it can't be exported to a competitor's app.
**Effort:** S.
**Principle risk:** low. The lines are factual, from the person's own data.
**Mitigation:** percentages only; never sent to the AI unless the person asks
about it (then flattened, as data); private (never shown to an advisor
without the client sharing it - see R15).

### R4. Storm Drill -> Storm Shelter - S
**User problem:** people decide what to do in a crash *during* the crash.
**Who:** everyone with holdings; beginners after practice money.
**What:**
- **Storm Drill:** on the existing Stress test (item 3), after the 2008 run,
  one field: "What will you do when this happens?" It is saved.
- **Storm Shelter:** when the storm note (T4) fires on a real drop, Home shows
  the person their own drill answer, their ledger (R2) and their log (R3).
  There is no trade button anywhere on that screen.

**Retention loop:** the drill answer waits for the storm; the storm brings the
person back to read their own words, and shelter adds a ledger entry.
**Effort:** S.
**Principle risk:** low (their own words back to them).
**Mitigation:** no suggested answers in the field; no "right" response.
**One-week test:** the field, plus surfacing it in the storm card. Metric:
on the next 5%+ drop, **the share of people who sell beyond their plan**,
comparing those with a drill note against those without.

### R5. 401(k) Menu Decoder - M
**User problem:** a 401(k) enrolment screen is a list of fund names with no
explanation; people pick by name or leave the default.
**Who:** anyone with a workplace plan - especially during open enrolment
(Oct-Nov, happening now: a natural test window).
**What:**
- Paste the plan's fund list (a photo later).
- Each fund is matched against existing fund data (`security_info`,
  `sync_history._expense_ratio`).
- Output per fund: its kind; its fee %; the fee in dollars at a monthly amount
  the person types. Each kind is explained with Learn content.
- Honest "couldn't identify" rows.
- No picks, and no "best" or "cheapest first" sorting by default (sort by
  kind, then by name).

**Retention loop:** one per enrolment season and job change; it links into
the Four Seasons (R7, Oct-Nov) and Trail Forks (R8, new job).
**Effort:** M (S for the text-box version).
**Principle risk:** higher than stated - see the list below. Next to "kind"
and "fee", people will read the table as a pick list. Wrong fee data harms.
**Mitigation:** show fees as facts with the source and date; explain that
kind and mix matter more than any single fund; "couldn't identify" rather
than a guess; a photo version must parse locally and strip figures and
account details before any AI.
**One-week test:** a text box and the matching table, no AI. Metric: **the
share of pasted funds identified**, plus whether the person returns within 30
days (e.g. to set a contribution with the Free money check).

### Tier 2 - next

### R6. Statement & Fact Sheet Decoder - L
**User problem:** brokerage statements and fund fact sheets are dense and
written for compliance, not for people.
**Who:** scattered investors, income investors, near-retirees, families
helping a parent.
**What:** upload any brokerage statement or fund fact sheet; it is explained
in plain words, then deleted.
**Engineering requirement:** parse locally, and strip every figure, account
number and name before anything reaches the AI.
**Retention loop:** every new statement (monthly or quarterly) is a reason to
come back, and it leads straight into the Walk (R1).
**Effort:** L (local PDF/image parsing and redaction is the hard part).
**Principle risk:** higher than stated (privacy) - see the list below.
**Mitigation:** fact sheets first (public documents, no personal data);
statements only once local redaction is proven by tests. Opt-in, like
screenshots today.

### R7. The Four Seasons - M (content-heavy)
**User problem:** "look at your balance" is a bad reason to open a finance
app.
**Who:** everyone; different moments matter to different personas.
**What:** four fixed calendar moments, each with a reason:
- **January:** contribution limits, the IRA window, the yearly fee bill
  projected to the goal date.
- **April:** tax forms explained.
- **Oct-Nov:** open enrolment (R5), HSA.
- **December:** Year in review (item 9), an RMD reminder for 73+, Letter from
  Future You.

**Retention loop:** four predictable visits a year that aren't about the
balance.
**Effort:** M (mostly content; small date logic).
**Principle risk:** tax-adjacent content (RMD ages, contribution limits)
changes yearly. Being out of date is the real risk.
**Mitigation:** dated content with sources, reviewed each season;
"check with your plan or a tax professional".

### R8. Trail Forks - M (content-heavy, code-light)
**User problem:** life events (new job, layoff, new baby, inheritance,
divorce, death of a parent) change everything, and people rush decisions.
**Who:** anyone at a life event; families.
**What:** a route per event:
- what changes;
- what to gather;
- what to ask;
- what *not* to rush.

Strictly educational.
**Retention loop:** life events are rare but high-trust moments; each fork
ends in the Walk.
**Effort:** M (writing).
**Principle risk:** higher than stated for divorce, inheritance and death -
see the list below.
**Mitigation:** what to ask a professional (attorney, tax preparer, plan
administrator) rather than what to do; gentle tone; no deadlines invented.

### R9. Lost & Found - S/M
**User problem:** old 401(k)s, unclaimed property and forgotten accounts are
money people already own.
**Who:** scattered investors, job changers, families.
**What:** the front half of the planned Account map (item 10):
- old 401(k)s (the Department of Labor's Retirement Savings Lost and Found);
- unclaimed property;
- an unused HSA;
- the employer match left on the table (`employer_match.py`).

Receiving brokerages are listed alphabetically.
**Retention loop:** each found account is a new account to bring in and walk.
**Effort:** S/M.
**Principle risk:** low; rollover choices are advice-adjacent.
**Mitigation:** explain the options (leave it, roll to an IRA, roll to the new
plan) neutrally, with what to ask; never recommend one.

### R10. Explain It To Someone - S/M
**User problem:** partners and adult children don't understand the plan, and
the person can't easily show them without sharing their balances.
**Who:** couples, families, a parent helping an adult child (and the
reverse).
**What:** a figure-free share view - percentages, the goal, the route and the
plan on one page - that a partner or adult child can read and then take the
Learn route themselves.
**Retention loop:** brings a second person in; shared understanding keeps
both walking.
**Effort:** S/M.
**Principle risk:** privacy (a share link).
**Mitigation:** no figures, no account details; the link expires, can be
revoked, and is created only by the owner.

### R11. Pay Yourself - M
**User problem:** near-retirees can't picture their savings as a paycheck.
**Who:** near-retirees and retirees.
**What:** a monthly "paycheck" built from income ahead (`income.py`) plus a
withdrawal rule of thumb. It shows which month is thin, and what a 20% drop
does to the paycheck. Builds on item 12 (money going out).
**Retention loop:** every month the paycheck is checked against the walk.
**Effort:** M.
**Principle risk:** higher than stated - see the list below. Retirement
income planning for a specific person is the closest thing here to
personalized advice.
**Mitigation:** rules of thumb are labelled and named, the person chooses the
rule, scenarios are labelled hypothetical, and nothing says "withdraw X".

### R12. Preparedness drills (weekly cadence, inside the Walk) - M
**User problem:** finance basics run out in weeks; what people need is
rehearsal for real situations.
**Who:** everyone - and it must work for someone with no money invested yet,
so beginners have a trail before their first dollar.
**What:**
- Short, tap-only scenarios, applied to the person's own mix and timeline
  (percentages), and repeated later with a twist:
  - difficulty: a market drop, job loss, a surprise expense, a fund closing;
  - prosperity, with equal weight: a raise, a bonus, a windfall, a goal
    reached early.
- Two renewable content sources: the person's own portfolio in percentages,
  and what happened in the world this month, explained for someone with their
  mix.
- A **readiness map** (which situations you've rehearsed, with gaps) is the
  pull, rather than a streak counter.

**Retention loop:** the readiness map's gaps, a weekly cadence (not daily),
and drills that come back with a twist.
**Effort:** M (content + a small engine).
**Principle risk:** a drill with a "correct" answer about what to do with
investments becomes advice.
**Mitigation:** drills rehearse considerations and questions, not trades;
answers are the person's own; "no right answer" on any investment choice.
**One-week test:**
- ten static drills;
- one card on Home;
- a weekly streak;
- one piece of gear;
- no reminders.

Metric: **unprompted return for a third drill**.

### Tier 3 - later / explore

### R13. Teach It Back - M
After each Learn topic, the person explains it in their own words to Ask
Northwend; gear is awarded when the explanation holds.
**Who:** beginners.
**Loop:** gear, plus the readiness map (R12).
**Risk:** low (education); AI grading can be wrong.
**Mitigation:** generous grading; a "try again" with no penalty; gear never
depends on returns.

### R14. Shadow Trail - M
Up to two hypothetical paths run alongside the real mix on real prices: no
action buttons, no tickers.
**Who:** tinkerers, practice-money graduates.
**Loop:** checking how the shadows are doing.
**Risk:** a tinkering toy that encourages chasing whichever path did best.
**Mitigation:** cap hard (two paths, kinds of funds only, changed at most
quarterly), always labelled hypothetical.

### R15. People With Your Answers - M
A percentage-only cohort view ("people with your timeline and direction hold
roughly X% stocks").
**Who:** beginners setting a target mix.
**Loop:** none strong - it's a reference.
**Risk:** highest advice risk on the list, and a privacy risk (other people's
data) - see the list below.
**Mitigation:**
- shown only beside the example mix;
- descriptive labelling;
- a minimum sample size;
- never per-fund;
- covered in the disclosures.

### R16. The Client-Owned Book (advisors) - L
**What:**
- The client's walk (R1) updates the advisor's book.
- The advisor gets counts-only signals.
- A one-click clean exit where the client keeps everything (builds on
  `advising.end_relationship`).
- The no-custody, no-aggregation model is documented explicitly for
  compliance confidence.

**Who:** advisors and their clients.
**Loop:** the client's monthly walk keeps the advisor's book current without
statements.
**Effort:** L.
**Risk:** advisors relying on client-entered data; "the client keeps
everything" versus the advisor's record-keeping duty - see the list below.
**Mitigation:** mark the book "client-reported, as of <date>"; the advisor's
own records (`former_clients`, archived notes) stay with the advisor after an
exit.

### Decided: no daily engagement (Oct 5)
We considered a "Duolingo for finance" model: a daily two-minute unit,
streaks, spaced repetition. **We are not pursuing daily usage as a goal.**
- Finance basics run out in weeks.
- A daily finance habit tends to become a daily balance check.
- Calm by default means rest days are real.

What we keep from that thinking, at a weekly-or-monthly cadence inside the
Walk:
- preparedness drills instead of lessons (R12);
- two renewable content sources (the person's portfolio in percentages, and
  this month's world explained for their mix);
- a readiness map as a stronger pull than a streak counter;
- drills that work before the first dollar.

### Someday / to explore (no commitment)
- **The Sealed Envelope** - a printable one-page PDF (no figures) at the end
  of a storm drill, to seal and open when the market falls 20%.
- **Walk Together** - two people pair up; the streak counts only if both walk
  in the same week; each sees only that the other walked.
- **Base Camp** - a monthly text-only, percentage-only thread with one
  prompt, moderated by Ask Northwend for advice and tickers. Invite-only if
  ever built.
- **The Inheritance Rehearsal** - practise administering a fictional parent's
  accounts.
- **Trail Conditions** - an email that says "calm, nothing to do" almost
  every week, and changes its wording only when something changes; never
  contains a figure.

### Next two weeks (in this order)
1. **The Monthly Walk v1 (R1)** - a Walk button on Home, the four steps, the
   rule-based verdict ("Nothing to do this month" or one next step by asset
   class), a walk streak. Folds in item 11.
   **Test:** ship it to everyone with holdings. **Metric: second-walk
   completion within 45 days.**
2. **The Storm Drill field (R4)** - the "What will you do when this happens?"
   field after the 2008 run on the Stress test, shown back in the storm card.
   **Test:** live until the next 5%+ drop. **Metric: on that drop, the share
   of people selling beyond their plan, with versus without a drill note.**
3. **The 401(k) Menu Decoder text box (R5)** - paste a fund list; a matching
   table of kind, fee % and fee in dollars at a typed monthly amount; honest
   "couldn't identify" rows; no AI. In open enrolment season now.
   **Test:** two weeks of enrolment season. **Metric: the share of pasted
   funds identified.**

### Principle risks higher than stated (flagged, not removed)
- **R1 Monthly Walk verdict:** "Nothing to do this month" is a *hold* for a
  specific person, and "one next step by asset class" is personalized
  allocation guidance. It's the most-used screen, so it carries the most
  weight. Keep it the person's own rule speaking (their target, their band),
  in asset classes, with no verdict without a target.
- **R2 Do-Nothing Ledger:** hindsight cuts both ways; showing only "what
  selling would have cost" is cherry-picked performance framing, and it
  implicitly tells people to hold. It must show both directions and record
  the decision, not grade it.
- **R5 401(k) Menu Decoder:** a table of kind and fee for a specific person's
  real choices will be read as a pick list, especially if sorted by fee.
  Wrong fee data matched to the wrong fund causes real harm. The photo
  version adds a privacy risk (enrolment screenshots often show balances).
- **R6 Statement Decoder:** statements are full of figures, names and account
  numbers. Reliable local redaction of PDFs and images is hard, and one miss
  sends personal data to the AI. Start with fact sheets.
- **R8 Trail Forks:** divorce, inheritance and death of a parent are legal
  and tax territory as much as investing; the content must stay with "what to
  ask" and avoid anything that reads as legal advice.
- **R11 Pay Yourself:** a monthly paycheck from someone's own savings is
  retirement-income planning for a specific person - the closest item to
  personalized advice after R15.
- **R15 People With Your Answers:** besides the advice risk you named, it
  uses other users' data. It needs aggregate-only figures, a minimum cohort,
  and a disclosures update (a change to "what's shared").
- **R16 Client-Owned Book:** advisors acting on client-entered figures, and
  "the client keeps everything" can collide with the advisor's duty to keep
  records. Keep the advisor's records with the advisor.
- **Someday - Walk Together and Base Camp:** both reveal to another person
  that someone uses a finance app and when. Base Camp is user-generated
  content: moderation by AI can miss tickers and advice, and a forum invites
  promotion.
- **Someday - Trail Conditions:** a weekly "calm, nothing to do" to everyone
  is a blanket hold message, and as a marketing email it needs an
  unsubscribe link and a postal address.

## Later

- [x] **Real transactions** - import a brokerage's activity export (any
      brokerage) for the real history instead of inferring it. (L)
      Decided (Oct 1): imported history replaces worked-out rows for the same
      account and dates; the same Upload a CSV button tells the two kinds of
      file apart; deposits will count as money added.
  - [x] **Phase 1 - read, review, save** - `txn_import.py`: finds the
        activity table, matches columns by name (best name first), a
        remembered layout or the AI on a button (names and cell kinds only);
        broker wording to Buy / Sell / Dividend / Reinvest / Interest /
        Deposit / Withdrawal / Fee or tax / Transfer / Split / Other (sweeps
        and core-account moves aren't money in). Review: which account (matched
        by name or last 3 digits), date range, counts by kind, the rows. Saved
        with `origin` 'imported' and a `row_key`, so a re-import adds only
        what's new; each account's worked-out rows up to its last imported
        date are replaced, and later holdings updates don't add any inside
        it. Activity: a Show filter and a From column. Made-up example files
        for Schwab, Fidelity, Vanguard and Robinhood layouts in tests.
  - [x] **Phase 2 - gains and income received** - each imported sale's
        realized gain by average cost, replayed in date order per account and
        symbol (same day: buys before sells); unknown (blank) when shares
        were held before the history starts, transferred in, or more were
        sold than it shows bought. Worked out again after every import.
        Income: "Received, last 12 months" - dividends and interest actually
        paid, by month, from the imported history (`income.received`).
  - [x] **Phase 3 - money added** - imported deposits and withdrawals count
        as money added (`plans.money_moves` / `money_added`): the Plan page's
        "This month" and list (marked "from your brokerage"), and progress
        reports' money in. Hand-logged entries dated inside the imported
        history aren't counted (shown crossed out) - it has the real
        figures. Moves between your own accounts and sweeps never count.
- [x] **Packaging** - `pyproject.toml` and console entry points. (S) -
      `pip install -e .` gives `northwend` (the app), `northwend-portfolio`,
      `northwend-prices`, `northwend-history`, `northwend-users` and
      `northwend-weekly-email` (`cli.py`: each runs its script's main() and
      closes pooled Postgres connections, like the scripts do). Editable
      install: the app reads views/, static/ and the schema files from the
      folder. requirements.txt stays for Streamlit Cloud and CI; a test keeps
      the two lists of pins the same and every module listed.
