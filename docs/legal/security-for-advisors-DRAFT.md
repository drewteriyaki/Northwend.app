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
- **App hosting:** Streamlit Community Cloud and/or Render (app.northwend.app).
  [OWNER: which is live; Render region is "ohio" in `render.yaml`.]
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
  200,000 iterations - never as text.
- **Lockout:** 5 wrong passwords for a username lock it for 15 minutes. Wrong
  two-step codes lock the same way.
- **"Stay signed in"** stores a random token in a cookie on the device; only its
  SHA-256 hash is kept, and it lasts at most 30 days. Logging out ends it; a
  password change signs out every other device.
- **Email links** (confirm, reset) are one-time and stored as hashes: confirm
  links last 3 days, reset links 60 minutes. Client setup links last 7 days.

## Two-step sign-in

- **Required for every advisor and admin account**; available to everyone else.
- A 6-digit code from an authenticator app (TOTP). The key is stored readable,
  because it's needed to check codes; it is never exported or shown to an admin.
- 8 one-time backup codes, stored only as SHA-256 hashes, shown once.
- "Remember this device" skips the code on that device for 30 days.
- For someone who lost their phone, an admin can reset their two-step sign-in (in
  the admin portal or with a command-line tool). That signs them out everywhere,
  and an advisor must set it up again straight away. An admin can also unlock a
  locked username and send a password-reset link to the account's own email. The
  admin portal never shows or sets a password; the operator's command-line tool
  can set one (used when creating accounts). [OWNER: policy - for example, a
  password is set this way only at the account holder's request.]

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
  their future self, their monthly walks and their account map (an "if
  something happens to me" list). Every per-account query is filtered
  by account.
- **Your client:** their own portfolio, plan, and the notes you share (not notes you
  mark private).
- **No other advisor or user.** [OWNER: firms with several advisors - not supported
  today; each link is one advisor to one client.]

## AI and other services

From the stored data, only profile answers and holdings as percentages and facts go
to the AI provider (Anthropic) - never dollar amounts, share counts, account names or
numbers, email addresses or your notes' text. What a person types into the chat is
sent as typed; the guide's own notes between conversations keep goals, dates and
decisions, with dollar amounts and account numbers taken out before they're saved.
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
