# Security at Northwend - for advisors

> **DRAFT - not legal advice; for review by a qualified lawyer before use.**
> Not published and not linked from the app or the website. Written for
> advisors and their compliance teams doing due diligence. Every statement is
> based on the code as of October 2026 (`auth.py`, `two_step.py`, `admin.py`,
> `portfolio.py`, `accounts.py`, `export.py`, `error_alerts.py`, and the
> developer header in `disclosures.py`). Assumptions and blanks are marked
> **[OWNER: ...]** or **[LAWYER: ...]**.

**Last reviewed:** [OWNER: date] · **Contact:** support@northwend.app

---

## In one paragraph

Northwend never connects to a brokerage and never asks for brokerage logins: it
stores only what you or your client paste, upload, type or photograph, and keeps
less than that where it can (uploaded files are deleted after reading; account
numbers are cut to their last 3 digits). Passwords are hashed, two-step sign-in is
required for every advisor, and the person who runs Northwend can see logins only -
never holdings, plans or profile answers. It is a free service run by one developer
and isn't paid by anyone for what it shows.

## Where data lives

- **Database:** Neon (managed Postgres) in the United States. [OWNER: region; whether
  storage is encrypted at rest under Neon's plan - confirm from Neon's documentation.]
- **App hosting:** Render (go.northwend.app), in the United States (Ohio), behind
  Cloudflare's proxy. Cloudflare adds security headers to every page: HTTPS only
  (HSTS), no framing by other sites, no camera, microphone or location access
  (`docs/CLOUDFLARE.md`).
- **Scheduled jobs** (price updates, history, the Monday advisor email) run on
  GitHub Actions with access to the database.
- **Secrets** (database address, API keys) live in each host's secret settings,
  never in the code repository.
- **The public website** (northwend.app) is static pages on Cloudflare Pages, with
  no scripts and no account data.
- **Connections** to the app are over HTTPS. [OWNER: confirm the database
  connection string requires TLS (`sslmode=require`).]

## What's stored about your clients

Holdings (symbols, shares, cost, value, account names with numbers cut to 3
digits), imported activity, plans and goals, profile answers, your notes,
proposals and progress reports, and your own name for the client. Uploaded files,
pasted text and screenshots are not kept. Clients can also use an example or
"percentages only" portfolio instead of real figures.

## Passwords and sign-in

- **Passwords** are stored only as PBKDF2-SHA256 hashes with a per-user salt and
  600,000 iterations - never as text. Passwords saved before that count are
  re-hashed at the next sign-in.
- **Lockout:** 5 wrong passwords for a username lock it for 15 minutes. Wrong
  two-step codes lock the same way.
- **"Stay signed in"** stores a random token in a cookie on the device; only its
  SHA-256 hash is kept, and it lasts at most 30 days. Logging out ends it; a
  password change signs out every other device. "Sign out other devices" (on
  the Account page) also closes tabs already open elsewhere, and the admin can
  sign every account out at once in an emergency.
- **Email links** (confirm, reset) are one-time and stored as hashes: confirm
  links last 3 days, reset links 60 minutes. Client setup links last 7 days.
- **Share links** ("Explain it to someone", where it's offered) carry a random
  256-bit token; only its SHA-256 hash is kept, and the full link is shown once to
  the person who made it. A link lasts 7 or 30 days (their choice), at most 3 work
  at once, and turning one off deletes it. Only the account's own login can make
  one - never an advisor in a client's account, never for an advisor's client
  (their links stop working if an advisor starts managing the account), never
  an admin. The page it opens needs no sign-in and signs no one in; it shows only
  asset-class percentages, the goal's kind and a range of years, the route stage
  and the target mix - never amounts, holdings, tickers, account details, the
  email or the login. A link that's unknown, ended or turned off, or any link
  while the feature is off, shows the same "no longer active" page. Opening links
  is limited per internet address (a hash of the address, kept one day), and the
  token is never logged.

## Two-step sign-in

- **Required for every advisor and admin account**; available to everyone else.
- A 6-digit code from an authenticator app (TOTP). The key can't be hashed, because
  it's needed to check codes, so it's stored encrypted (Fernet: AES-128 and an
  HMAC-SHA256 check), with the encryption key kept in the host's settings, apart
  from the database - a copy of the database alone can't make anyone's codes. It is
  never exported or shown to an admin.
- 8 one-time backup codes, stored only as salted PBKDF2-SHA256 hashes, shown once.
- "Remember this device" skips the code on that device for 30 days.
- For someone who lost their phone, an admin can reset their two-step sign-in (in
  the admin portal or with a command-line tool). That signs them out everywhere,
  and an advisor must set it up again straight away. An admin can also unlock a
  locked username and send a password-reset link to the account's own email. For
  an account without an email (one an advisor or the admin made), the admin
  portal can set a temporary password, shown to the admin once; the operator's
  command-line tool can also set one (used when creating accounts). Either is a
  way into that account, so every admin action - in the portal or the
  command-line tool - is written to an append-only admin action log (when, which
  admin, what, which login; never holdings or figures), kept for a year.
  [OWNER: policy - for example, a password is set this way only at the account
  holder's request.]

## What the operator can and can't see

- The **admin portal** shows logins only: username, email, role, when the account
  was made and last signed in, and locks. It shows **no holdings, plans, profile
  answers or notes**, and has no "view as" or impersonation.
- Admins are made only from outside the app (a command-line tool or a hosting
  secret), never from the web.
- The admin's System panel shows the app version, database type and whether keys
  are set - never their values.
- Error alerts emailed to the admin carry only the kind of error and where in the
  code it happened - no user ID, no error message, no data.
- **Honest limit:** the operator has administrative access to the hosting and
  database accounts, so it is technically possible to read the database directly.
  The app is designed so that day-to-day running never requires it.
  [OWNER: state a policy - for example, the database is read directly only to fix
  a problem a user reports, or when the law requires, and each such access is
  logged.] [LAWYER: wording.]

## Who sees a client's data in the app

- **You** (the client's advisor): everything in that client's account, through the
  advisor-client link (`can_view`), except what's theirs alone - their notes to
  their future self, their monthly walks, their account map (an "if
  something happens to me" list), their Lost & Found list (where they've
  looked for old accounts), their Trail Forks (life events they've marked), their
  Inheritance Rehearsal (the practice run's steps they've walked through), their
  preparedness drills (what they tapped), the Learn topics they've explained back
  (whether each held), the rule of thumb they picked on Pay
  yourself (you can look at the same picture with a rule you pick; yours isn't
  saved), their Shadow Trail (hypothetical mixes of kinds of funds they've
  set) and
  their share links. A client whose account you manage can't make share links,
  and any they made before stop working. Every per-account query is filtered
  by account.
- **What a client chooses to bring** (Bring to my advisor, where it's
  offered): a client can tick some of those private things to show you -
  their plan in plain words (no figures), the name of a life event they've
  marked (never its details), which drills they've rehearsed (never their
  answers), their storm drill answer in their own words, where they've looked
  for old accounts, and questions from a fixed list. You see only what's
  ticked, labelled "Shared by <client> on <date>; client-reported", on a card
  over meeting prep; each time you open it is logged and shown to the client.
  Unticking removes an item at once, and nothing of it stays with you after
  the relationship ends - only the dated consent record. Keep what you need
  for your own books and records in your own notes. [LAWYER: whether an
  adviser must keep a copy of client-shared material they reviewed.]
- **Your client:** their own portfolio, plan, and the notes you share (not notes you
  mark private).
- **No other advisor or user.** [OWNER: firms with several advisors - not supported
  today; each link is one advisor to one client.]
- **Every visit is logged and shown to the client.** Each page you open in a
  client's account is recorded (you, the client, the page, the time - never what
  was on it), and your client sees the list on their Account page. You never see
  another advisor's visits.
- **Introductions show only what the person chose to send.** Someone who writes
  to you from Find a guide sends their message, the name they give and, if they
  choose, a figure-free outline (mix by asset class in whole percents, goals, a
  timeline range, where they are on Northwend's route) - never amounts,
  holdings, account details or their email. You see only introductions sent to
  you, and Northwend counts no views or clicks of your listing. You see their
  account only if they then choose to share it, in two separate steps.
- **Consent is recorded.** When a client agrees to share their account with you
  (setting up their login from your link, choosing to share after an
  introduction, or - if sharing began another way or before these records were
  kept - choosing "Keep sharing" when asked once at their next sign-in) and when
  sharing ends (they stop it, you end it, or an account is deleted), the time and
  the exact words they were shown are kept. Until a client answers, Your clients
  says they haven't confirmed sharing yet. When sharing ends, your access ends on your very next page
  load. Your client record export includes your consent records with that client.

## How your book works: no custody, no aggregation

Not on yet: this part waits on the lawyer's review of advisor records (gate
L2). Where it's on, Your clients opens with a short "How your book works" note
that says the same.

- **No custody.** Northwend never holds, moves or touches money. It has no
  accounts of its own for clients and can't place a trade.
- **No aggregation.** Northwend never connects to a brokerage, bank or
  custodian and never asks for those logins. There is no data feed from a
  custodian; nothing is pulled in the background.
- **Client-reported figures.** Holdings are what you or your client bring in -
  a statement file, pasted text, a screenshot or typed by hand. Prices come
  from market data (ticker symbols only go to the data providers). Northwend
  doesn't check holdings against the custodian, so each client's card marks
  its figures "Client-reported, as of <date>", the day their holdings were
  last updated, and the book's total says "client-reported". Your custodian's
  records are the record of what a client holds.
- **The client's walk keeps the book current.** A client's monthly walk starts
  with updating their holdings, so your book is as current as their last
  walk. Whether a client walked is theirs: you see "Walked this month" and
  "Last walk: <month>" only for a client who turns that on, after seeing the
  exact words (kept with the consent records); never what their plan said,
  their mix, amounts or anything they typed.
- **Counts only.** The book also shows how many of your clients walked this
  month (of those who share it) and how many updated their holdings in the
  last 30 days - plain numbers across your own clients, never a list or a
  ranking, and never anyone else's clients.
- **Your notes are yours; the client's account is theirs.** When a
  relationship ends - either of you can end it in one step - the client keeps
  their whole account (holdings and history, plan, goals, answers, their
  walks and notes, and a copy of what you shared with them). You keep your own
  records: your notes (private and archived ones too, with their edit
  history), the proposals and reports you sent, the name and email you had
  for them, and the dated consent records - under Former clients, and in that
  client's record export. You no longer see their account. [LAWYER: whether
  this is enough for an adviser's books and records (SEC Rule 204-2, state
  rules), or whether a dated read-only copy of the client-reported figures
  you reviewed should stay with you after an exit.]

## AI and other services

From the stored data, only profile answers and holdings as percentages and facts go
to the AI provider (Anthropic) - never dollar amounts, share counts, account names or
numbers, email addresses or your notes' text. What a person types into the chat is
sent as typed; the guide's own notes between conversations keep goals, dates and
decisions, with dollar amounts and account numbers taken out before they're saved.
Draft with Northwend (where it's offered) sends the client's mix and holdings as
percentages - no notes, no names - and the words you type for that draft, with
amounts, long numbers and email addresses taken out; a message to several clients
sends only your words. The draft lands in a box for you to edit and is never sent,
saved or shared on its own: your own Send button does that, under your name, with
the standing line. Looking up a word in Learn's glossary sends the word only.
Screenshot reading is optional and offered only on some copies of the app [OWNER:
off in production today]; where it is, the whole picture goes to the AI - including
balances and account names on screen - only when someone chooses it.
Market data providers (Finnhub, Yahoo Finance) receive ticker symbols only. Resend
receives only an email address and the message. Full list: Privacy Policy,
section 4.

## Retention and deletion

- Data is kept until it is deleted. Anyone signed in to their own account can
  export everything held for it as CSV files and then delete their holdings or the
  whole account on the Account page. An advisor can't delete a client's account in
  the app; the operator deletes one on request (from the admin portal), and an
  advisor with clients asks the operator to close their own account.
  [OWNER: confirm this is the process you want for advisors and managed clients.]
- **A former client deleting their account:** once a relationship has ended, the
  client can delete their own account. Everything that's theirs is deleted; your
  own records about them stay with you - your notes, the proposals and progress
  reports you sent, and your former-client entry (the name and email you had for
  them) - and stay in your client record export.
- The database provider keeps a rolling backup of about 6 hours; deleted data is
  gone from it after that. [OWNER: confirm Neon's history window on the current plan.]
- Short-lived security records (sign-up and email-limit hashes) are kept one day.
- **Consent records and the access log** are append-only (the app's database role
  can add and read them, not change or delete them) and kept 7 years after
  sharing ends, even when either account is deleted. [LAWYER: confirm the period.]
- **Record-keeping is yours.** Northwend is not a books-and-records system. Export
  what you need to keep under your own obligations. [LAWYER: SEC Rule 204-2 / FINRA
  wording.] [OWNER: note archiving and a client record export are being added in a
  separate change.]

## If something goes wrong

- **Breach notification:** if we learn that advisors' or clients' personal
  information has been accessed without permission, we will notify affected
  advisors within [OWNER/LAWYER: timeframe, e.g. 72 hours] of confirming it, with
  what happened, what data was involved and what we're doing, so you can meet your
  own notice duties to clients. We will also notify individuals and regulators as
  the law requires. [LAWYER: state laws and Regulation S-P amendments.]
- **Availability:** Northwend is an early (beta) service with no uptime guarantee.
  [OWNER: backup and restore test practice.]

## Reporting a vulnerability

Email **support@northwend.app** with "Security" in the subject and enough detail to
reproduce the issue. Please don't access other people's data, run automated scans
that could affect others, or share the issue publicly before it's fixed. We'll
reply within [OWNER: number] business days and tell you when it's fixed. We won't
take legal action against good-faith research that follows these rules.
[LAWYER: safe-harbour wording.] [OWNER: consider a `security.txt` on northwend.app.]

## What Northwend does not do (yet)

So your due diligence is complete: there is no SOC 2 or other third-party audit, no
single sign-on, no IP allow-listing, no per-access audit log visible to advisors,
and no formal penetration test. [OWNER: update as any of these change.]
