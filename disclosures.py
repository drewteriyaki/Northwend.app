"""The "About and disclosures" text, kept apart from the page code so the
wording can be reviewed and edited on its own. DRAFT - have the final wording
reviewed by someone qualified before launch (ROADMAP.md, item 5). Fill in
OPERATOR_NAME and CONTACT first; placeholders() lists what's still missing.

Each statement about data here must stay true to the code:
- The AI guide (Ask Northwend): the person's ContextCard (context_card.py -
  profile answers from fixed choices without "Other notes", tickers, market
  data's fund names, what each holds and whole-% weights, the mix, their own
  target mix, band and drift, the route stage, the guide's typed notes) and
  the chat; every call through ai_gateway.py. The plan PDF has no AI call
  (client_plan.questions, by fixed rules). advisor.scrub_memory takes amounts
  and account numbers out of the notes before they're saved and before
  they're sent; the notes are listed (and deletable) on the Account page and
  never read or written in an advisor's session in a client's account
  (ai_gateway.may_keep_memory).
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
- Two-step sign-in (two_step.py): TOTP; the key can't be hashed (it's needed
  to check codes), so it's stored encrypted (Fernet) with NORTHWEND_TOTP_KEY,
  a key kept in the host's settings apart from the database - readable only
  on a copy without that setting (a local run; Admin > System says so and
  counts any still readable). TWO_STEP_ENCRYPTED (below) says when the live
  copy's are all encrypted, for the published wording. Backup codes as PBKDF2
  hashes (older sets as SHA-256 until used or replaced); never exported or
  shown to an admin; wrong codes lock like passwords; "remember this device" is a date on the stay-signed-in
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
  Each check (source, the CRD matched, the day) is kept in licence_checks
  (licence_check.py); the advisor agreement accepted - version, text hash,
  gate L1 on or off, time - in advisor_agreements (advisor_agreement.py).
- Advisors' emails to clients (setup link, report waiting, a message waiting)
  carry the advisor's name and firm in the From name (mailer.sender); the
  report, proposal and message emails also carry the standing line
  (standing_line.py: the advice is the advisor's, not Northwend's);
  report and message emails say something is waiting - never figures or the
  message text. The advisor's name for a client ("Chen household") is
  advisor_clients.client_name, seen only by that advisor.
- Introductions (intros.py, views/intros.py; flag intros + gate L2):
  intro_requests keeps each intro a person sends from Find a guide - the name
  they give, their message (plain text, no links, emails or long numbers),
  the outline they tick (intros.clean_outline: asset-class mix in whole
  percents, goals, a timeline bucket, the route stage - never amounts, share
  counts, tickers or account details), the advisor's text answer and whether
  they shared their listing's scheduling link. The advisor reads only intros
  sent to them (intros.for_advisor - never the person's id or email); nothing
  about browsing is written. The "an introduction is waiting" / "answered"
  emails (mailer.intro_received / intro_answered) carry no text or figures,
  the answered one the standing line. Full sharing only after two steps:
  consent.grant(how='intro', the exact words, intros.sharing_text) and the
  advisor_clients link in one transaction (intros.share_account). Deleted with
  either account (admin.ACCOUNT_TABLES); in both sides' export.
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
  account. The Expedition Log and Do-Nothing Ledger (expedition_log.py,
  ledger.py, flags walk_log / ledger): prefs walk_log per walk - holdings
  updated or not, the largest drift in whole points, the mix's move in
  percent, whether a sale was recorded and whether a note was written - no
  amounts; the person's own only, never sent to the AI. Its reminder (checkin_email.py, GitHub Actions): off unless
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
  401(k) Menu Decoder adds numbers only to the person's own settings (prefs
  decoder_401k_counts: decodes, fund lines, identified - menu_decoder.add_counts;
  not for someone left out, not while an advisor views the account).
- 401(k) Menu Decoder (menu_decoder.py, views/menu_decoder.py, flag
  decoder_401k): the pasted fund list and its table live only in the session
  (st.session_state), never written to the database, logs or the AI; matching
  reads security_info only. Its optional overlap button fetches the identified
  funds' public top holdings like Home's Fund overlap (fund_top_holdings,
  shared market data, no user id).
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
- Upload, save and download limits (rate_limits.py, audit 1.8d): per login
  (an advisor in a client's account counts as the advisor), files read, saves
  and ZIP / PDF downloads built, rate_limits.LIMITS an hour and a day. Kept:
  only a count per action - a SHA-256 of the login's id, the action word and
  the time, in email_sends - for a day; never what was uploaded or saved.
- Delete my account: admin.delete_own; a former client's delete keeps each
  former advisor's own records (admin.ADVISOR_RECORD_TABLES, for every
  former_clients row) - everything else of theirs goes. Consent records
  (consent.py) and the advisor access log (access_log.py) stay, ids and all
  (admin.KEPT_AFTER_DELETE), for 7 years (consent.prune / access_log.prune in
  tidy.py; PLAN B6). The access log is on the client's Account page ("Who has
  looked at your account", access_log.for_client) and in their export.
  A consent grant is written at the setup link (auth.accept_invite), or - for
  sharing with no grant in the client's own words (a 'migration' grant, an
  admin's link) - when the client is asked once at sign-in and keeps sharing
  (consent.to_ask, views/consent_ask.py: 'sign_in_ask', consent.ask_text
  verbatim); stopping there is the client's own stop (a 'client_stop' revoke).
- Delete all my holdings: portfolio.delete_holdings / HOLDINGS_TABLES (keeps
  plans, profile, notes, settings, watchlist, login); only for an account
  that manages itself (dashboard CAN_MANAGE).
- How long things are kept (PLAN D5): tidy.py, nightly (the Scheduled sync
  workflow's tidy job) - never-confirmed self-made accounts after 30 days
  without a sign-in (tidy.UNCONFIRMED_DAYS, through admin.delete_account),
  error_events 90 days, expired email links / setup links / sessions, the
  login_failures / signups / email_sends counts after a day (signups also
  holds the no-account decoder's hourly counts, decoder_public.py; email_sends
  the upload / save / download counts, rate_limits.py). Session and
  link lengths: auth.py, two_step.py.
- Hosts (hosting_lines, PLAN step 4.7): named from where this copy runs
  (settings.host(); Cloudflare in front when CLIENT_IP_HEADER is
  cf-connecting-ip, as render.yaml sets it). The website's About is built
  offline, so until HOST_MOVED it names both: Community Cloud, moving to
  Render. Cloudflare Pages serves the website (website/).
- No third-party analytics: .streamlit/config.toml gatherUsageStats = false;
  the only counting is feature_counts.py (above), inside the database.
- Account map (account_map.py, the Account page): the login's own, never shown
  to an advisor, never emailed or sent to the AI; its PDF only downloaded.
  Year in review (recap.py): read from data already kept; the share version
  has no dollar figures.
- Lost & Found (lost_found.py, views/lost_found.py, flag lost_found): under the
  account map on Account; education with official links only. Its checklist is
  kept in the login's own settings (prefs lost_found: each place's status -
  still looking / found something / nothing there - and the day of the last
  change; never an amount, account number or name); never drawn while an
  advisor is in a client's account, not in an advisor's client record, never
  sent to the AI. In the person's own export (settings).
- Trail Forks (trail_forks.py, views/trail_forks.py, flag trail_forks): under
  Lost & Found on Account; education about life events with official links
  only. Kept in the login's own settings (prefs trail_forks): which forks the
  person marked as theirs and which fixed steps they ticked - keys only, no
  typed text, no dates, amounts or names; never drawn while an advisor is in a
  client's account, not in an advisor's client record, never sent to the AI.
  In the person's own export (settings).
- The Four Seasons (seasons.py, views/seasons.py, flag seasons): a card on Home
  in season, a line on Learn; education with official links only, yearly
  figures dated with their tax year and IRS page and shown only in that year.
  Kept in the login's own settings (prefs seasons: per season and year,
  opened or put away - no free text); never drawn while an advisor is in a
  client's account, never sent to the AI. In the person's own export
  (settings). The RMD note is shown only for the "65 or older" age range
  already in the profile; nothing new is asked.
- Explain it to someone (explain_share.py, views/explain_share.py, flag
  explain_share): share links made on Account by the login's own account only
  (never an advisor in a client's account, an advisor's client or an admin -
  explain_share.eligible). Table share_links: the token's SHA-256, never the
  token (shown once); expires after 7 or 30 days (DAYS_CHOICES); turning it
  off deletes the row; at most 3 working (MAX_ACTIVE); opens and the day of
  the last one, for the owner only; deleted with the account, ended ones
  nightly (tidy.py); in the owner's export without the hash. The page
  (explain_share.page) shows only asset-class whole percents, the goal's kind
  and a timeline bucket, the route stage, the target mix and band, and the
  first name only if ticked; never amounts, holdings, tickers, account names
  or numbers, email or login. Opening it signs nobody in; each visit is
  counted once per browser session against a per-address limit (a signups row
  keyed share: plus the address's SHA-256, a day). Flag off: every link shows
  "no longer active".
Change this text when any of those change.

Plain text, no "$" (Streamlit would read a pair of them as math).
"""

import settings

LAST_UPDATED = "October 6, 2026"

# The app's move from Streamlit Community Cloud to Render behind Cloudflare
# (PLAN step 4, audit 1.10a). A copy on either host names its own host by
# itself (hosting_lines). Only the website's About page, built offline, can't
# tell: until the move is done it names both. Once go.northwend.app serves
# from Render (RUNBOOK, "Move to Render"): set this to True, change
# LAST_UPDATED to that day (who sees the app's traffic changed), and rebuild
# the website.
HOST_MOVED = True   # done October 6, 2026: go.northwend.app on Render

# Two-step keys encrypted at rest (two_step.py, audit 1.1e). The code seals
# them whenever NORTHWEND_TOTP_KEY is set, but only the owner can set it on
# the live host. Until the live copy's are all encrypted, the published words
# (the in-app Security section, the About page and the Privacy Policy) keep
# saying only what's true today. Set this to True once the live app's Admin >
# System shows the key set and "0 readable" - after RUNBOOK, "Two-step key":
# the key on the host, then `manage_users.py encrypt-two-step` - and rebuild
# the website. The wording itself: two_step_key_words().
TWO_STEP_ENCRYPTED = True   # live: key set, 0 readable (October 6, 2026)


def two_step_key_words(encrypted: bool | None = None) -> str:
    """How the Privacy Policy describes the stored two-step key."""
    encrypted = TWO_STEP_ENCRYPTED if encrypted is None else encrypted
    if encrypted:
        return ("stored encrypted, with the encryption key kept apart from the database, "
                "so codes can be checked")
    return "stored so codes can be checked"


# the in-app Security section and the About page: a line only once it's true
_TWO_STEP_KEY_LINE = (" The key behind your codes is stored\n  encrypted, and what unlocks "
                      "it is kept apart from the database." if TWO_STEP_ENCRYPTED else "")


def hosting_lines(host: str | None = None, behind_cloudflare: bool | None = None,
                  moved: bool | None = None) -> str:
    """The first lines of "Services Northwend uses": who hosts the app, and
    Cloudflare. `host` is settings.host() ("Render", "Streamlit Community
    Cloud", or "" - this computer, or the website's build); behind_cloudflare
    is whether Cloudflare's proxy is in front (CLIENT_IP_HEADER says
    cf-connecting-ip); `moved` is HOST_MOVED."""
    host = settings.host() if host is None else host
    if behind_cloudflare is None:
        behind_cloudflare = settings.get("CLIENT_IP_HEADER").lower() == "cf-connecting-ip"
    moved = HOST_MOVED if moved is None else moved
    if host == "Streamlit Community Cloud":
        app = "- **Streamlit Community Cloud** hosts the app."
    elif host == "Render" or moved:
        app = "- **Render** hosts the app, in the United States."
        behind_cloudflare = behind_cloudflare or not host   # the website: the plan as done
    else:
        # the website before the move, and local runs: both, honestly
        return ("- **Streamlit Community Cloud** hosts the app today. It's moving to\n"
                "  **Render** (in the United States), with **Cloudflare** in front of it.\n"
                "- **Cloudflare** serves the website, northwend.app.")
    if behind_cloudflare:
        return (app + "\n- **Cloudflare** sits in front of the app and serves the website,\n"
                "  northwend.app: your connection passes through it on its way to the app.")
    return app + "\n- **Cloudflare** serves the website, northwend.app."
MIN_AGE = 18

# Fill these in before launch - see placeholders().
OPERATOR_NAME = "Andrew Zhang"
CONTACT = "support@northwend.app"

# the published Terms of Use and Privacy Policy (docs/legal/, built into the
# website by website/build.py; their date is LAST_UPDATED, the version agreed to)
TERMS_URL = "https://northwend.app/terms"
PRIVACY_URL = "https://northwend.app/privacy"

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
except what's theirs alone: their notes to future you, their monthly walks,
their account map, their Lost & Found list and their Trail Forks.
"""),
    ("Your data", f"""
- **What's stored:** the holdings you or your advisor add (symbols, shares,
  cost, value, cash and account names), so the app can show them; any activity history you import (each
  row's date, kind, symbol, shares, price, amount, fees and description, with
  account and bank numbers cut to their last 3 digits), your plan and goals,
  your investing-profile
  answers, notes, monthly walks (when each was finished and what your own plan
  said, and, where the walk's log is on, its percentages - never amounts), your account map if you make one, your Lost & Found list if you keep one (whether you've looked in each place and found something - never an amount or account number), the Trail Forks you mark as yours if you use them (which life events, and which listed steps you've ticked - nothing you type), and settings, and the name you'd like to be called, if you
  give one (shown in the app, and to your advisor). If you created your
  account yourself, or added an email on the Account page, also
  your email address - used only to sign in and to send you account emails
  (confirming the address, resetting your password; for advisors, an optional
  Monday summary with counts only - no client names or figures), never shown
  to anyone else or sent to the AI - and which version of this page you agreed
  to. Northwend sends no newsletters or marketing email. If you ask for advisor access, also
  your firm's name and your CRD or licence number, so it can be checked, and a
  note of each check (where it was looked up, the number that matched and the
  day); for an advisor, also which version of the advisor agreement you accepted
  and when.
- **Less is kept than you share:** an uploaded file is read and then deleted -
  the file itself is never kept - and any account number in an account name is
  cut to its last 3 digits before it's saved. Pasted text is read by the app
  itself (not by AI) and isn't saved; only symbols, share counts, cost and cash
  are taken from it. Screenshots, where they can be read, aren't saved either.
  A fund list pasted into the 401(k) menu decoder isn't saved at all.
- **You don't have to share real numbers at all:** try the example portfolio,
  or enter only percentages of a pretend total. Everything except real gains
  and income works the same.
- **Brokerage logins:** Northwend never asks for or stores your brokerage
  username or password, and never connects to your brokerage. It only reads
  what you choose to paste, upload, type in or photograph.
- **Who can see it:** you, and - if your account is managed by an advisor -
  that advisor. Where introductions are offered, an advisor you write to from
  Find a guide sees only the name you give, your message and the parts you
  choose to include (your mix by asset class in percents, goals, a timeline
  range, where you are on the route) - never amounts, holdings or your email -
  until you choose, in two separate steps, to share your full account. Those
  introductions are kept until you or the advisor deletes the account, and
  browsing Find a guide isn't recorded at all. Where "Explain it to someone"
  is offered, anyone you send one of its links to can see a page with your mix
  by asset class in percents, what you're investing for and roughly when (a
  range of years), where you are on the route, your target mix and how far it
  may drift - and your first name only if you tick it. Never an amount, a
  holding or fund, an account name or number, or your email. A link works for
  the 7 or 30 days you choose, you can turn it off at any time on the Account
  page, and only you can make one, for your own account (not while an advisor
  manages it). Northwend keeps only a scrambled version of the link and, for
  you, how many times it was opened - nothing about who opened it. To look after accounts, the person who runs Northwend can see
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
  advisor's setup link after 7 days. An "Explain it to someone" link works for
  the 7 or 30 days you chose, and is deleted soon after it ends. The scrambled counts that stop automated
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
- **Who has looked at your account:** each time an advisor opens a page in your
  account, Northwend notes who, which page and when - never what was on it -
  and your **Account** page lists it. When you agree to share your account with
  an advisor, or stop, that's noted too, with the words you were shown (if your
  sharing began before these records were kept, you're asked once, at sign-in,
  whether to keep sharing). These
  records are kept for 7 years after sharing ends, even if an account is
  deleted, to protect you and your advisor. They hold who, when and those
  words - never figures.
- **Taking a copy:** the **Account** page also downloads everything held for your
  account as spreadsheet (CSV) files - holdings, history, plan, answers,
  settings, what your advisor shared with you, the sharing and "who has
  looked" records, and any introductions. Passwords and sign-in
  records aren't included.
"""),
    ("Security", f"""
- **Passwords** are stored only as a salted, one-way hash, never as text. After
  5 wrong passwords a username is locked for 15 minutes.
- **Two-step sign-in:** after your password, a 6-digit code from an app on your
  phone, so a password alone isn't enough. Advisor and admin accounts always use
  it; anyone can turn it on from the **Account** page. Backup codes are stored
  only as a scrambled copy. On a device you trust you can skip the code for 30
  days.{_TWO_STEP_KEY_LINE}
- **New accounts:** to stop automated sign-ups, only a few accounts can be
  made from one internet address each day. For that, a scrambled copy of the
  address (not the address itself) is kept for one day.
- **Uploads and saves:** so the app stays quick for everyone, an account can
  only read so many files, save so many times and make so many downloads in an
  hour or a day - far more than anyone needs. For that, only a count is kept,
  for one day - never what was in the file or what was saved.
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
people took a second monthly walk within 45 days of their first, how many wrote
down on the Stress test what they'd do in a drop (never what they wrote), or
what share of the funds pasted into the 401(k) menu decoder were recognised
(numbers only - never the list or a fund's name). A count is never about one
person, is shown only for groups of 20 or more, and is never shared, sold or
sent to the AI. To leave yourself out, turn on **Leave me out of
feature counts** on the **Account** page.
"""),
    ("Services Northwend uses", f"""
{hosting_lines()}
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
The app's AI guide (Ask Northwend) uses Claude, an AI model from Anthropic. When
you use it, the app sends:

- your investing-profile answers (goals, time horizon, risk tolerance and so on;
  the chat leaves out your "Other notes" box),
- your holdings: in the chat as **tickers, fund names from market data, what each
  fund holds and each one's share of the portfolio in whole percents**, with your
  mix and your own target mix; for the plan's suggested next steps also types and
  sectors, gains or losses as percentages, and figures like dividend yield, beta
  and P/E - never dollar amounts, share counts, account names or numbers,
- what you type in the chat, and short notes the guide saved from earlier
  conversations - goals, dates and decisions, never dollar amounts or account
  numbers (the app takes those out before a note is saved). You can read and
  delete the notes on your Account page; an advisor working in your account never
  sees or changes them.

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
