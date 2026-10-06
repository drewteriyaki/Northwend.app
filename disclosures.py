"""The "About and disclosures" text, kept apart from the page code so the
wording can be reviewed and edited on its own. DRAFT - have the final wording
reviewed by someone qualified before launch (ROADMAP.md, item 5). Fill in
OPERATOR_NAME and CONTACT first; placeholders() lists what's still missing.

Each statement about data here must stay true to the code:
- The AI guide (Ask Northwend) / plan next steps: advisor.portfolio_summary() (tickers, names, % of
  portfolio, asset type and class, sector, gain/loss %, dividend yield, beta,
  P/E - no dollar amounts, share counts or account names), the profile
  answers, the chat, and the guide's saved notes (advisor.system_prompt;
  advisor.scrub_memory takes amounts and account numbers out of the notes
  before they're saved and before they're sent).
- CSV column guess (only when asked): column names and cell kinds only
  (csv_import.ai_mapping / sample_shapes).
- Screenshots: only where offered (the screenshot_ai flag, off in
  production) and opt-in; the images themselves, whole (screenshot_read.read)
  - the one time the AI sees figures, said in the reader's own consent line
  (views/holdings_input.py); only symbols / shares / cost / percent / cash
  survive screenshot_read.clean().
- Market data: tickers only (update_prices.py / live_prices.py / news.py ->
  Finnhub, sync_history.py / live_prices.py -> Yahoo Finance); the scheduled
  jobs run on GitHub Actions (.github/workflows/scheduled-sync.yml).
- Passwords: PBKDF2-SHA256 with a per-user salt, 600,000 iterations, the count
  kept per login (users.password_iterations; older hashes are re-made at the
  next sign-in); stay-signed-in cookies hold a random token whose hash is
  stored; 5 wrong passwords lock a username for 15 minutes (auth.py). "Sign
  out other devices" and the admin's "Sign everyone out" also close tabs
  already open (users.session_gen, app_state).
- Two-step sign-in (two_step.py): TOTP; the key is stored readable (needed to
  check codes), backup codes as PBKDF2 hashes (older sets as SHA-256 until
  used or replaced); never exported or shown to an admin; wrong codes lock
  like passwords; "remember this device" is a date on the stay-signed-in
  session (login_sessions.two_step_until).
- Sign-up: the email is the login, not shown to others or sent to the AI; only
  Resend gets it, to deliver the confirm / reset emails (mailer.py, auth.sign_up);
  bot checks keep only a SHA-256 of the internet address for a day (signups table); the version agreed to is stored (users.terms_version), with
  the 18+ and US-residency boxes each kept with its time (age_confirmed_at,
  us_resident_at). While gate L0 is off, sign-up needs a one-time invite code
  (invite_codes: the code, when and by which account it was used).
  Email links: hashed, one-time, confirm 3 days / reset 60 minutes; email-send
  limits keep only hashes for a day (email_tokens / email_sends). Unconfirmed
  self-serve accounts can't use the AI (ai_usage.CONFIRM_FOR_AI). Advisor
  sign-ups store firm + licence (advisor_requests) and email them to the
  support address (mailer.advisor_request) for the admin to check; the
  decision is emailed to them (admin.approve_advisor / decline_advisor).
- Advisors' emails to clients (setup link, report waiting, a message waiting)
  carry the advisor's name and firm in the From name only (mailer.sender);
  report and message emails say something is waiting - never figures or the
  message text. The advisor's name for a client ("Chen household") is
  advisor_clients.client_name, seen only by that advisor.
- Meeting prep talking points (meeting.facts_for_ai / talking_points): profile,
  advisor.portfolio_summary, and percentage facts - no dollars, no note text.
- Advisors' Monday email (weekly_email.py, GitHub Actions): counts only (reviews
  due / coming due, accepted proposals, open next steps), no client names or
  figures; confirmed or admin-made emails only; off switch in prefs
  (weekly_email_off); once a week (weekly_email_week).
- Notes to future you (future_notes.py, future_notes table): the person's own,
  never drawn while an advisor views the account, never in an advisor's client
  record (export.client_record), never in an AI prompt - only in the person's
  own chat message when they press "Ask Northwend about it"; real delete.
- The Monthly Walk (checkin.py, views/checkin.py): kept in the person's own
  settings (prefs checkin_log, walk_verdicts: the verdict's kind and asset
  class, and the day - no figures); never drawn while an advisor views the
  account. Its reminder (checkin_email.py, GitHub Actions): off unless
  turned on (prefs checkin_email), confirmed emails only, once a month
  (checkin_email_sent), says only that it's time - no figures.
- Feature counts (feature_counts.py): totals worked out in code from the
  settings column only (no user id read), shown only for groups of
  feature_counts.MIN_GROUP (20) or more, only in the Admin portal's
  "Feature tests" panel; never sent anywhere or to the AI; anyone with
  prefs feature_counts_off (Account > "Leave me out of feature counts") is
  skipped; only walks kept with their day (from the Walk on) count. The
  Storm Drill (flag storm_drill; its answer is a future_notes row, symbol
  future_notes.DRILL) is counted as how many people wrote one - never the
  words, and nothing about selling.
- Export everything (export.py): the account's own rows as CSV; never password
  hashes, tokens, IP hashes, private advisor notes or other accounts' data.
- Admin portal (admin.py, views/admin.py): logins only - username, email,
  role, created, last sign-in (users.last_login_at), locks; no holdings,
  plans or profile answers; feature counts as totals only (above). For an
  account without an email the admin can set a temporary password, shown to
  them once - a way back into that account (decision D8), so it's said in
  "Who can see it". Every admin action, there or in manage_users.py, is
  written to the admin action log (admin_log.py: when, which admin, a fixed
  action word, which account, a few words - never holdings or figures; kept
  a year, admin_log.prune), shown on Admin > System.
- Uploads: read from a temporary copy that's deleted (portfolio.temp_upload);
  account numbers cut to 3 digits on save (accounts.mask_number via
  portfolio.write_snapshot). Example / percentages portfolios: sample_data.py,
  manual_entry.PCT_SOURCE. Pasted text: paste_parse / csv_import, no AI.
- Delete my account: admin.delete_own; a former client's delete keeps each
  former advisor's own records (admin.ADVISOR_RECORD_TABLES, for every
  former_clients row) - everything else of theirs goes.
- Delete all my holdings: portfolio.delete_holdings / HOLDINGS_TABLES (keeps
  plans, profile, notes, settings, watchlist, login); only for an account
  that manages itself (dashboard CAN_MANAGE).
- How long things are kept (PLAN D5): tidy.py, nightly (the Scheduled sync
  workflow's tidy job) - never-confirmed self-made accounts after 30 days
  without a sign-in (tidy.UNCONFIRMED_DAYS, through admin.delete_account),
  error_events 90 days, expired email links / setup links / sessions, the
  login_failures / signups / email_sends counts after a day. Session and
  link lengths: auth.py, two_step.py.
- No third-party analytics: .streamlit/config.toml gatherUsageStats = false;
  the only counting is feature_counts.py (above), inside the database.
- Account map (account_map.py, the Account page): the login's own, never shown
  to an advisor, never emailed or sent to the AI; its PDF only downloaded.
  Year in review (recap.py): read from data already kept; the share version
  has no dollar figures.
Change this text when any of those change.

Plain text, no "$" (Streamlit would read a pair of them as math).
"""

LAST_UPDATED = "October 6, 2026"
MIN_AGE = 18

# Fill these in before launch - see placeholders().
OPERATOR_NAME = "Andrew Zhang"
CONTACT = "support@northwend.app"

_OPERATOR = OPERATOR_NAME or "[operator name]"
_CONTACT = CONTACT or "[contact email]"

SUMMARY = ("Northwend is an educational tool for following your investments. "
           "It is not financial advice, and it isn't connected to any brokerage.")

SECTIONS = [
    ("Who runs Northwend", f"""
Northwend is a free, early (beta) version, run by an individual developer,
{_OPERATOR}. It may change, have mistakes, or be unavailable at times. Questions,
problems or requests about your data: **{_CONTACT}**.

Northwend is for people **{MIN_AGE} and over**.
"""),
    ("Educational, not advice", """
Everything in this app - the dashboard, plans and projections, the Get started
path, example funds, model portfolios, alerts and the AI guide (Ask Northwend) - is for
education and information only. None of it is a recommendation to buy, sell or
hold any security, and none of it is personalized investment, tax or legal advice.

The people who built and run this app are not acting as your financial advisor
and are not a registered investment adviser or broker-dealer. If an advisor gave
you access, their advice comes from them, not from the app. Consider talking to a
licensed professional before making investment decisions.
"""),
    ("How Northwend is paid", """
Northwend is free while it's in beta. It **doesn't sell investments**: it has no
funds of its own, takes no commissions or trading fees, and no fund company or
brokerage pays to be mentioned in examples or answers. It doesn't show ads or
sell your data. If Northwend ever charges for anything, it will say so here
first, and nothing is charged without your say-so.
"""),
    ("Projections, examples and practice", """
- **Projections are hypothetical.** Plan and goal projections assume a steady
  yearly return (6% unless it's changed), shown with a lower and a higher case
  around it. Real returns go up and down, and can be negative for years at a
  time. A projection is not a promise.
- **Past performance doesn't predict future results.** Historical figures and
  the practice simulation use past prices, which won't repeat the same way.
- **Example funds are examples.** What's worked out from your own answers
  (your example mix) names kinds of funds, not specific ones. Funds named in
  Learn's general reads - the same for everyone - or in model portfolios show
  what a kind of investment looks like. Research any fund yourself - its
  costs, risks and holdings - before investing.
- **All investing involves risk,** including losing the money you put in.
"""),
    ("For advisors", """
If you use Northwend with clients, you remain responsible for your own advice,
licensing, record-keeping and compliance, and for having your clients' consent
to put their holdings here. Northwend doesn't supervise advice or check it for
suitability. A client you add can see their own portfolio, plan and your notes
to them (not ones you mark private); you can see everything in their account
except what's theirs alone: their notes to future you, their monthly walks and
their account map.
"""),
    ("Your data", f"""
- **What's stored:** the holdings you or your advisor add (symbols, shares,
  cost, value, cash and account names), so the app can show them; any activity history you import (each
  row's date, kind, symbol, shares, price, amount, fees and description, with
  account and bank numbers cut to their last 3 digits), your plan and goals,
  your investing-profile
  answers, notes, monthly walks (when each was finished and what your own plan
  said, with no amounts), your account map if you make one, and settings, and the name you'd like to be called, if you
  give one (shown in the app, and to your advisor). If you created your
  account yourself, or added an email on the Account page, also
  your email address - used only to sign in and to send you account emails
  (confirming the address, resetting your password; for advisors, an optional
  Monday summary with counts only - no client names or figures), never shown
  to anyone else or sent to the AI - and which version of this page you agreed
  to. Northwend sends no newsletters or marketing email. If you ask for advisor access, also
  your firm's name and your CRD or licence number, so it can be checked.
- **Less is kept than you share:** an uploaded file is read and then deleted -
  the file itself is never kept - and any account number in an account name is
  cut to its last 3 digits before it's saved. Pasted text is read by the app
  itself (not by AI) and isn't saved; only symbols, share counts, cost and cash
  are taken from it. Screenshots, where they can be read, aren't saved either.
- **You don't have to share real numbers at all:** try the example portfolio,
  or enter only percentages of a pretend total. Everything except real gains
  and income works the same.
- **Brokerage logins:** Northwend never asks for or stores your brokerage
  username or password, and never connects to your brokerage. It only reads
  what you choose to paste, upload, type in or photograph.
- **Who can see it:** you, and - if your account is managed by an advisor -
  that advisor. To look after accounts, the person who runs Northwend can see
  login details (your email or username, your role, when the account was made
  and last signed in) - not your holdings, plan or answers. If an account has
  no email address, they can set a temporary password to help its owner back
  in, and every action they take on accounts is recorded. It isn't sold,
  rented or shared for advertising.
- **How long it's kept:** your holdings, plan, answers and notes stay until you
  delete them or your account. The database provider keeps a short rolling
  backup (currently about 6 hours) so data can be recovered after an outage;
  deleted data is gone from it after that.
- **Kept only for a while,** and tidied away each night: an account you made
  yourself whose email was never confirmed is deleted, with everything in it,
  after 30 days without a sign-in. Sign-ins last 30 days ("stay signed in",
  and skipping the two-step code on a trusted device). Email links work until
  they run out: a password reset after 1 hour, a confirm link after 3 days, an
  advisor's setup link after 7 days. The scrambled counts that stop automated
  sign-ups and repeated wrong passwords are kept for 1 day, and error records
  (what went wrong and where - nothing about you) for 90 days.
- **Deleting:** on the **Account** page you can delete all your holdings
  (holdings, cash, activity and value history; your goals, profile answers,
  notes and settings stay), or your whole account and everything in it. If an
  advisor manages your account, ask them, or contact **{_CONTACT}**.
- **If you used to have an advisor:** deleting your account deletes everything
  that's yours. Your former advisor keeps only their own records about working
  with you - their notes, the proposals and reports they sent you, and the name
  and email they had for you - because advisors must keep records of their
  work. They can't see anything in your account once you've stopped sharing.
- **Taking a copy:** the **Account** page also downloads everything held for your
  account as spreadsheet (CSV) files - holdings, history, plan, answers,
  settings and what your advisor shared with you. Passwords and sign-in
  records aren't included.
"""),
    ("Security", """
- **Passwords** are stored only as a salted, one-way hash, never as text. After
  5 wrong passwords a username is locked for 15 minutes.
- **Two-step sign-in:** after your password, a 6-digit code from an app on your
  phone, so a password alone isn't enough. Advisor and admin accounts always use
  it; anyone can turn it on from the **Account** page. Backup codes are stored
  only as a scrambled copy. On a device you trust you can skip the code for 30
  days.
- **New accounts:** to stop automated sign-ups, only a few accounts can be
  made from one internet address each day. For that, a scrambled copy of the
  address (not the address itself) is kept for one day.
- **"Stay signed in"** keeps a random token in a cookie on your device; only a
  scrambled copy of it is stored. Changing your password or logging out ends it,
  and a password change signs out your other devices too.
- The site is served over an encrypted connection (HTTPS). No system is
  perfectly secure, though - don't store anything here you couldn't afford to
  have exposed, and use a password you don't use anywhere else.
"""),
    ("Cookies and tracking", """
Northwend sets one cookie of its own, only if you tick **Stay signed in**: it keeps
you signed in on that device. There are no advertising or tracking cookies, and no
third-party analytics or tracking. The hosting service may set cookies it needs
to run the site.

**Feature counts:** to learn whether features like the monthly walk help,
Northwend counts in totals only, inside its own database - for example, how many
people took a second monthly walk within 45 days of their first, or how many
wrote down on the Stress test what they'd do in a drop (never what they wrote). A count is
never about one person, is shown only for groups of 20 or more, and is never
shared, sold or sent to the AI. To leave yourself out, turn on **Leave me out of
feature counts** on the **Account** page.
"""),
    ("Services Northwend uses", """
- **Streamlit Community Cloud** hosts the app.
- **Neon** runs the database, in the United States.
- **Anthropic** (Claude) powers the AI guide, the optional column guess and,
  where it's offered, the optional screenshot reader - see the next section for
  exactly what's sent.
- **Finnhub** and **Yahoo Finance** provide prices, fund details and news; only
  ticker symbols are sent to them.
- **GitHub** runs the scheduled price updates.
- **Resend** delivers the account emails (confirming your address, resetting
  your password, an advisor's Monday summary); it receives only your email
  address and that message.

Each has its own privacy policy.
"""),
    ("What's sent to the AI", """
The app's AI guide (Ask Northwend) and the plan's suggested next steps use Claude,
an AI model from Anthropic. When you use them, the app sends:

- your investing-profile answers (goals, time horizon, risk tolerance and so on),
- your holdings as **tickers, fund names, types and sectors, each one's share of the
  portfolio, its gain or loss as a percentage, and figures like dividend yield,
  beta and P/E** - never dollar amounts, share counts, account names or numbers,
- what you type in the chat, and short notes the guide saved from earlier
  conversations - goals, dates and decisions, never dollar amounts or account
  numbers (the app takes those out before a note is saved).

If you have an advisor, they can ask the AI to draft **talking points** before
a meeting. That sends the same profile answers and holdings summary, plus facts
in percentages - how your portfolio and goal have moved since the last review,
which holdings were added or reduced, and how far the mix is from its target -
never dollar amounts or your advisor's notes.

**Reading screenshots** is optional and, where it's offered, the one exception:
the pictures you choose are sent to the AI whole, so it sees everything on
them - including balances, account names and any account numbers on screen.
You're asked first each time, and you can crop them to just your holdings list.
Only symbols, share counts, cost and cash are taken from what it reads, and the
pictures aren't saved. Pasting or typing your holdings instead sends nothing to
the AI: the app reads pasted text itself.

Uploaded files are read by the app itself. Only if a file's columns can't be
matched and you press **Let AI guess the columns** is anything sent: the
**column names and the kind of each cell** ("text", "number", "money") - never
the values, holdings or account numbers in it.

The AI is told to explain, never to recommend buying, selling or holding a
specific investment or a specific mix for you. AI answers can still be wrong or
out of date. Check anything important before acting on it.
"""),
    ("Market data", """
Prices, company details and news come from Finnhub and Yahoo Finance. Prices
update by themselves about every minute while the market is open (crypto around
the clock, mutual funds hourly), but may be delayed (often by 15 minutes) or
occasionally wrong - check your brokerage for exact figures before trading.
"""),
    ("No guarantees", """
Northwend is provided as-is, without warranties of any kind. Figures, prices,
classifications and AI answers may be incomplete, delayed or wrong, and you use
them at your own risk. To the extent the law allows, the people who run Northwend
aren't liable for losses from using it or relying on it.
"""),
    ("Not affiliated", """
Northwend is independent. It isn't affiliated with, endorsed by or connected to any
brokerage, or to Finnhub, Yahoo or Anthropic. Brokerage names are used only to
describe which files and screens it can read.
"""),
    ("Changes to this page", f"""
When this page changes in a way that matters - what's stored, who it's shared
with, what's sent to the AI - the date below changes and the app says so the next
time you sign in. Questions: **{_CONTACT}**.
"""),
]


def placeholders() -> list[str]:
    """What still has to be filled in before launch."""
    return [name for name, value in (("OPERATOR_NAME", OPERATOR_NAME), ("CONTACT", CONTACT))
            if not value]
