# Northwend Privacy Policy

> **DRAFT - not legal advice; for review by a qualified lawyer before use.**
> The lawyer's working copy, written for after the hosting move. The version
> people read is `docs/legal/privacy-policy.md` (on the website, linked from sign-up),
> with these notes resolved in plain, careful wording - keep the two in step. Every statement
> about data is based on the code as of October 2026 and reuses the
> developer header in `disclosures.py`, which lists the code each statement
> depends on - change both together. Assumptions and blanks are marked
> **[OWNER: ...]** or **[LAWYER: ...]**.

**Effective date:** [OWNER: date]
**Who we are:** Northwend is run by Andrew Zhang, an individual developer
("we", "us"). [LAWYER: company name, if one is formed.]
**Contact:** support@northwend.app

This policy explains what Northwend collects, why, who it's shared with, how long
it's kept, and your choices. It is written to meet the California Online Privacy
Protection Act (CalOPPA). [LAWYER: check whether CCPA/CPRA or other state privacy
laws apply at Northwend's size, and whether advisors' client data brings in
Gramm-Leach-Bliley / Regulation S-P duties for advisors.]

**The short version:** Northwend keeps what you give it to run your account, and
less than you share where it can. It never asks for your brokerage login. It
doesn't sell your data, share it for advertising, show ads, or track you across
other sites.

---

## 1. Who Northwend is for

Northwend is for people **18 and over in the United States**. We don't knowingly
collect information from anyone under 18. If you believe a child has made an
account, contact us and we will delete it.

## 2. What we collect

**Account and sign-in**
- Your username, and - if you signed up yourself or added one - your email address.
- A one-way hash of your password (never the password itself).
- The name you'd like to be called, if you give one.
- When the account was made and when you last signed in; which version of the
  terms you agreed to, and when; when you confirmed you're 18 or older and live
  in the United States. If you joined with an invite code: which code, and when.
- If you turn on two-step sign-in: the key your authenticator app uses (stored
  encrypted, with the encryption key kept apart from the database, so codes can be
  checked) and your backup codes as hashes.
- "Stay signed in": a random token in a cookie on your device; we store only a hash.
- For advisors asking for access: your firm's name and your CRD or licence number.

**Your investments and plans** (what you or your advisor add)
- Holdings: symbols, share counts, cost, value, cash and account names, so the
  app can show them. Account numbers in account names are cut to their last 3
  digits before saving.
- Activity history you import: date, kind, symbol, shares, price, amount, fees and
  description, with account and bank numbers cut to the last 3 digits.
- Your portfolio's value over time, any contributions you record, and nicknames
  you give your accounts.
- Your plan and goal, target mix, watchlist, settings and progress through Learn.
- Notes you write to your future self on a holding or your plan, and your monthly
  walks: the months you finished one, the day, and the kind of verdict your own
  plan gave (for example "nothing to do" or "next deposit mostly to bonds") - no
  amounts. Where the walk's log is on, also for each walk: whether you updated your
  holdings, how far your mix was from its target (in points), how your mix moved
  over the month before (in percent), whether a sale was recorded and whether you
  wrote a note - never amounts, and only you see it.
- If you make one, your account map: for each account, its kind, who to call,
  whether a beneficiary is named, where the paperwork is, and your notes for
  family (accounts you add by hand keep at most their last 3 digits).
- Your investing-profile answers (goals, timeline, comfort with risk, age range,
  emergency savings, debt, employer match and similar).
- Short notes the AI guide saves between conversations, listed on your Account
  page where you can delete any or all of them: goals, dates and decisions.
  Dollar amounts and account numbers are taken out before a note is saved. An
  advisor working in your account never sees or changes them.
- For advisors and their clients: advisor notes, proposals, progress reports,
  model portfolios, and the advisor's own name for each client.
- Introductions (once the directory and intro flow are on, gate L2): each
  introduction you send an advisor from Find a guide - the name you give, your
  message, what you choose to include (your mix by asset class in whole
  percents, your goals, a timeline range and where you are on Northwend's route -
  never amounts, holdings or account details), when you sent it, and the
  advisor's answer. Browsing Find a guide isn't recorded at all. [LAWYER: wording.]

You don't have to use real numbers: an example portfolio and a "percentages only"
mode work without any.

**What we don't keep**
- Uploaded files are read from a temporary copy that is deleted; the file is never
  stored.
- Pasted text is read by the app itself (not by AI) and isn't saved; only symbols,
  share counts, cost and cash are taken from it. A fund list pasted into the
  401(k) menu decoder isn't saved at all - it stays in your current visit only.
- Screenshots you choose to have read (where that's offered) are not saved.
- Your brokerage username and password: Northwend never asks for them.
- Your AI chat messages are kept only for your current visit (in the app's
  memory) and are not saved to the database. Only the guide's own short notes
  are saved (see above).

**Technical information**
- To stop automated sign-ups, a SHA-256 hash of your internet (IP) address - not
  the address itself - is kept for one day when you sign up. Email-sending limits
  likewise keep only hashes, for one day.
- Repeated wrong passwords are counted per username (as a hash) for 15 minutes.
- How many files your account read, how many times it saved and how many
  downloads it made in the last day, so the limits on uploads and saves can
  apply - counts only (with a hash of your account's number), never what was in
  a file or what was saved, and deleted after a day.
- How many AI requests your account made each month, per feature, so the monthly
  allowance can be applied (counts only, not what was asked).
- When something breaks, the admin is emailed the kind of error and where in the
  code it happened - never your data, the error message, or your user ID. The full
  error details stay in the hosting provider's server log. [OWNER: log retention
  at the host.]
- Our hosting providers receive your IP address and browser details as part of
  serving the site and may keep them in their logs. [OWNER: confirm each host's log
  retention.]
- Northwend uses no third-party analytics or tracking: Streamlit's usage
  statistics are turned off, and the website (northwend.app) runs no scripts.
- **Feature counts.** To learn whether features like the monthly walk help,
  Northwend counts in totals only, inside its own database - for example, how many
  people took a second monthly walk within 45 days of their first, how many
  wrote down on the Stress test what they'd do in a drop (never what they
  wrote), or what share of the funds pasted into the 401(k) menu decoder were
  recognised (for that, your settings keep three numbers - how many lists,
  funds and recognised funds - never the list or a fund's name). The counts are
  worked out by the app's code from what's already stored; nobody looks at one
  person's record to make them. A count is never about one person, is shown only
  for groups of 20 or more (and only on the admin page), and is never shared,
  sold or sent to the AI. You can leave yourself out at any time with **Leave me
  out of feature counts** on the Account page; you're then left out of every
  count, including ones about walks you took before. Counting began on [OWNER:
  the date this text is live] and covers only walks from then on.

## 3. How we use it

Only to run Northwend for you: to sign you in, store and show your portfolio,
work out values and plans, answer your AI questions, let your advisor work with
you (if you have one), send account emails, keep the service secure, and fix
problems - and, in totals only, to learn whether features help (the feature
counts in section 2, which you can leave yourself out of). We don't use your data
for advertising, and we don't sell it.

## 4. Who it's shared with

**We don't sell, rent or share your personal information for advertising or
marketing.** Northwend is free and isn't paid by anyone for what it shows.

It is shared only as needed to run the service, with:

| Service | What it does | What it receives |
|---|---|---|
| **Neon** | The database (United States) | Everything stored for your account |
| **Render** | Hosts the app (go.northwend.app), in the United States (Ohio) | Requests to the app, your IP address, server logs [OWNER: written for after the move (PLAN step 4). Until then the host is Streamlit Community Cloud, as the About page says; publish this wording only once go.northwend.app serves from Render and `disclosures.HOST_MOVED` is True] |
| **Anthropic** (Claude) | The AI guide, advisor talking points; the column guess only when you choose, and screenshot reading only where it's offered and you choose it | See section 5 |
| **Finnhub** | Live prices, company details, news | Ticker symbols only |
| **Yahoo Finance** (through the unofficial yfinance library) | Prices, price history, dividends, fund details | Ticker symbols only |
| **GitHub Actions** | Runs the scheduled price updates, the advisors' Monday email and the monthly walk reminders people turn on | Access to the database to do those jobs |
| **Resend** | Sends account emails | Your email address and that message |
| **Cloudflare** | Serves the website northwend.app (Pages), and sits in front of the app: every connection to go.northwend.app passes through it, and it adds security settings | Visitors' IP address and browser details; for the app, the requests and pages passing through it on their way |

Your advisor, if you have one, sees everything in your account except your notes
to your future self, your monthly walks and your account map, which only you
see (the account map is never emailed, and its PDF is only downloaded by you);
you see your own portfolio, plan and the notes your advisor shares with you (not
ones they mark private).

**Introductions.** An advisor you write to from Find a guide sees only what you
send: the name you give, your message and the parts you choose to include
(above) - not your email, holdings, amounts or anything else in your account.
Their answer is seen only by you. Sharing your full account with them is a
separate choice you make afterwards, in two steps that say exactly what they
would see; only then do they see your account as described above, including the
name and email on it. [LAWYER: the two-step consent text, `intros.SHARE_LINES`.]

Each time an advisor opens a page in a client's account, Northwend records who,
which client, which page and when - never what was on the page or any figure -
and the client sees the list on their Account page ("Who has looked at your
account", the last 90 days; their data download has all of it). An advisor never
sees another advisor's visits. When a client agrees to share their account with an
advisor (when they set up their login from the advisor's link, choose to share
after an introduction, or - if sharing began another way or before these records
were kept - are asked once at sign-in and choose to keep sharing), or sharing
ends (the client stops it, the advisor ends it, we unlink them on request, or an
account is deleted), Northwend records it with the time and the exact words the
client was shown. Section 7 says how long these records are kept. [LAWYER: wording.]

The person who runs Northwend can see, on an admin page, only login details:
username, email, role, when the account was made and last signed in, and locks -
not your holdings, plans or answers - and the feature counts, as totals only.
For an account without an email address (one an advisor or the admin made), the
admin can reset the login without email by setting a temporary password, which
is shown to them once - so it could also be used to sign in to that account.
Every admin action (this one, resets, role changes, deletions, signing everyone
out) is written to an admin action log: when, which admin, what was done and to
which login - never holdings or figures. The log is kept for a year.
[LAWYER: wording.]

We may also disclose information if the law requires it, to protect someone's
safety, or as part of a transfer of the service (we'd tell you first).
[LAWYER: wording.]

## 5. What's sent to the AI

When you use the AI guide, Northwend sends Anthropic:

- your investing-profile answers (the chat leaves out your "Other notes" box);
- your holdings: in the chat, as tickers, fund names from market data, what each
  fund holds and each one's share of the portfolio in whole percents, with your mix
  and your own target mix; for a plan's suggested next steps, also types and
  sectors, gains or losses as percentages, and figures like dividend yield, beta
  and P/E - **never dollar amounts, share counts, account names or numbers**;
- what you type in the chat, and the guide's short notes from earlier
  conversations (goals, dates and decisions - dollar amounts and account numbers
  are taken out before a note is saved). A note to your future self is sent only
  when you ask the guide about that note, as part of your question.

An advisor's meeting talking points send the same profile and holdings summary,
plus facts in percentages (how the portfolio and goal moved since the last review,
which holdings were added or reduced, drift from target) - never dollar amounts or
note text.

**Reading screenshots** is optional, offered only on some copies of the app [OWNER:
off in production today, behind the `screenshot_ai` flag; see PLAN D1], and the one
exception to the above: the pictures you choose are sent whole, so the AI sees
everything on them - including balances, account names and any account numbers on
screen. You're asked first each time; only symbols, share counts, cost and cash are
taken from what it reads, and the pictures aren't saved. Pasting or typing instead
sends nothing to the AI.

A file's **column names and kinds of cell** ("text", "number") are sent only if you
press "Let AI guess the columns" - never the values. Your email address is never
sent to the AI.

[OWNER/LAWYER: state Anthropic's data handling for API use - retention period and
that API data isn't used to train models - from the current Anthropic commercial
terms, and link them.]

## 6. Cookies and Do Not Track

- Northwend sets **one cookie of its own**, only if you tick "Stay signed in", to
  keep you signed in on that device. The hosting service may set cookies it needs
  to run the site.
- There are **no advertising or tracking cookies** and no third-party analytics.
- **No cross-site tracking by others:** we don't allow third parties to collect
  personal information about your online activities over time and across other
  websites through Northwend. [OWNER/LAWYER: confirm the hosting providers' own
  cookies (Render, Cloudflare) don't do this. Cloudflare's features that set
  cookies or add scripts stay off (docs/CLOUDFLARE.md).]
- **Do Not Track:** Northwend does not track you across other websites or let
  others do so through it, so it treats every visitor the same whether or not
  their browser sends a Do Not Track signal. [LAWYER: also mention Global Privacy
  Control if a state law requires it.]

## 7. How long we keep it

What's kept only for a while is deleted by a nightly job (`tidy.py`); the rest
stays until you delete it. [This is decision D5 in `docs/PLAN.md`; keep the two
in step.]

| What | How long |
|---|---|
| Files you upload, screenshots, pasted text | Not kept: read in memory, then gone |
| Your holdings, plan, profile answers, notes and settings | Until you delete them or your account (or we close the account, see the Terms) |
| A deleted account | Gone at once; gone from the database provider's rolling backup when that window passes (currently about 6 hours) [OWNER: confirm the Neon plan's history window; decision D6] |
| An account made through sign-up whose email was never confirmed | Deleted, with everything in it, after 30 days without a sign-in |
| Sign-in sessions ("stay signed in") and "remember this device" for two-step sign-in | 30 days; ended sooner by logging out or changing your password |
| Wrong-password, sign-up and email-send counts (a hash of the internet address, never the address) | 1 day |
| Upload, save and download counts per account (counts only) | 1 day |
| How often the 401(k) decoder without an account was used from one internet address (a hash of the address, never the address or what was pasted) | 1 day [once the no-account decoder is on - PLAN step 3] |
| Email links (stored only as hashes, each works once) | Password reset 60 minutes, confirm 3 days, an advisor's setup link 7 days |
| Unsubscribe links in reminder emails | 1 year |
| Minute-by-minute prices (no personal data) | 1 week, then one closing price a day |
| Daily prices and fund details (no personal data) | Kept |
| Error records (the kind of error and where it happened, no personal data) | 90 days |
| The record of what the person running Northwend did to accounts (never holdings) | 1 year [once the admin action log is in - PLAN 1b.3] |
| An advisor's own records about a former client (their notes, the proposals and reports they sent, the name and email they had) | Kept for the advisor's record-keeping duties after the client leaves or deletes their account (section 8) [LAWYER: how long] |
| Introductions (the name and message sent, what was included, the advisor's answer) | Until the person's or the advisor's account is deleted [LAWYER: should the advisor keep their copy longer, as a record?] |
| Records of consent to share with an advisor (when, which advisor, the exact words shown) and of each advisor's visits to a client's account (who, which page, when - never figures) | 7 years after the sharing ends (visits: 7 years), kept even when either account is deleted, to protect the client and the advisor in a dispute [decision B6 in `docs/PLAN.md`; LAWYER: confirm the period] |
| Server logs at the host | [OWNER: per host; check it's no more than 30 days] |
| Requests to the AI | Per Anthropic's API terms (section 5) |

## 8. Your choices: see, correct, download, delete

- **See and correct:** your holdings, plan, profile answers, name, email and
  settings are all shown in the app, and you can change them there (Account,
  Profile, Plan and the holdings window). An advisor-managed client can ask their
  advisor, or us.
- **Download:** the Account page's "Export everything" downloads everything held for
  your account as spreadsheet (CSV) files, including any introductions you sent
  or received. Passwords, sign-in tokens, internet
  address hashes, advisors' private notes and other accounts' data aren't included.
- **Delete holdings:** the Account page deletes all your holdings, cash, activity
  and value history (your goals, answers, notes and settings stay).
- **Delete your account:** the Account page deletes your account and everything in
  it. If an advisor manages your account, ask them or contact us, and we'll delete
  it; an advisor with clients contacts us so their clients aren't left without
  notice.
- **If you used to have an advisor:** deleting your account deletes everything
  that's yours - holdings, history, plan, answers, notes, settings and login. Your
  former advisor keeps only their own records about working with you: their
  notes, the proposals and progress reports they sent you, and the name and email
  they had for you, because advisers must keep records of their advice (for
  example SEC Rule 204-2). They can't see your account once you've stopped
  sharing with them. [LAWYER: confirm this split and how long the advisor may
  keep these records.] The records of your consent to share and of advisors'
  visits to your account also stay, for 7 years (section 7): they hold who,
  when and the words you were shown, never figures.
- **Anything else,** or if you can't sign in: email support@northwend.app. We'll
  answer within [OWNER: number] days.
- **Emails:** Northwend sends no newsletters or marketing. Advisors can turn off
  the Monday summary on the Clients page. The monthly walk reminder is off
  unless you turn it on (Account page), and says only that it's time - no figures.
- **Feature counts:** turn on "Leave me out of feature counts" on the Account
  page to be left out of every count (see section 2).

## 9. Security

Passwords are stored as salted PBKDF2-SHA256 hashes (600,000 iterations); after 5 wrong passwords a
username is locked for 15 minutes. Two-step sign-in is required for advisors and
admins and available to everyone. The site is served over HTTPS. Uploads are
deleted after reading and account numbers are cut to 3 digits. No system is
perfectly secure; if we learn of a breach affecting your information we will tell
you as the law requires. See "Security for advisors" for more detail.
[LAWYER: state breach-notification wording.]

## 10. Where data is kept

Northwend is offered in the United States and its data is stored in the United
States (Neon; the app runs on Render in Ohio). [OWNER: confirm the Neon region.] Some service
providers may process data elsewhere under their own terms.

## 11. Changes to this policy

When this policy changes in a way that matters - what's stored, who it's shared
with, what's sent to the AI - we update the effective date above and the app tells
you the next time you sign in, before the change applies to information we already
hold. [OWNER: notice period; whether to also email confirmed addresses.]

## 12. Contact

Questions or requests: **support@northwend.app**. [LAWYER: a postal address may be
required.]
