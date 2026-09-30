"""The "About and disclosures" text, kept apart from the page code so the
wording can be reviewed and edited on its own. DRAFT - have the final wording
reviewed by someone qualified before launch (ROADMAP.md, item 5).

Each statement about data here must stay true to the code:
- AI Assistant / plan next steps: advisor.portfolio_summary() (weights only,
  no dollar amounts, share counts or account names), the profile answers,
  the chat, and the assistant's saved notes (advisor.system_prompt).
- AI import fallback: the header row only (ai_parse.map_columns).
- Screenshots: opt-in, the images themselves (screenshot_read.read); only
  symbols / shares / cost / percent / cash survive screenshot_read.clean().
- Market data: tickers only (update_prices.py / news.py -> Finnhub,
  sync_history.py -> Yahoo Finance).
- Passwords: PBKDF2 with a per-user salt; stay-signed-in cookies hold a random
  token whose hash is stored (auth.py).
- Uploads: read from a temporary copy that's deleted (portfolio.temp_upload);
  account numbers cut to 3 digits on save (accounts.mask_number via
  portfolio.write_snapshot). Example / percentages portfolios: sample_data.py,
  manual_entry.PCT_SOURCE.
Change this text when any of those change.

Plain text, no "$" (Streamlit would read a pair of them as math).
"""

LAST_UPDATED = "September 29, 2026"

SUMMARY = ("Waypoint is an educational tool for following your investments. "
           "It is not financial advice, and it isn't connected to any brokerage.")

SECTIONS = [
    ("Educational, not advice", """
Everything in this app - the dashboard, plans and projections, the Get started
path, example funds, model portfolios, alerts and Sage, the AI guide - is for
education and information only. None of it is a recommendation to buy, sell or
hold any security, and none of it is personalized investment, tax or legal advice.

The people who built and run this app are not acting as your financial advisor.
If an advisor gave you access, their advice comes from them, not from the app.
Consider talking to a licensed professional before making investment decisions.
"""),
    ("Projections, examples and practice", """
- **Projections are hypothetical.** Plan and goal projections assume a steady
  yearly return (6% unless it's changed), shown with a lower and a higher case
  around it. Real returns go up and down, and can be negative for years at a
  time. A projection is not a promise.
- **Past performance doesn't predict future results.** Historical figures and
  the practice simulation use past prices, which won't repeat the same way.
- **Example funds are examples.** Funds named in Get started, model portfolios
  or AI answers show what a kind of investment looks like. Research any fund
  yourself - its costs, risks and holdings - before investing.
- **All investing involves risk,** including losing the money you put in.
"""),
    ("Your data", """
- **What's stored:** the holdings you or your advisor import or enter
  (symbols, shares, cost, value and account names), your plan and goals, your
  investing-profile answers, notes, and settings. On the hosted site this lives
  in a Postgres database run by Neon (in the US), and the app runs on
  Streamlit Community Cloud.
- **Less is kept than you share:** an uploaded file is read and then deleted -
  the file itself is never kept - and any account number in an account name
  is cut to its last 3 digits before it's saved.
- **Pasted text** is read by the app itself, not by AI, and only symbols, share
  counts and cost are taken from it; the text isn't saved.
- **You don't have to share real numbers at all:** try the example portfolio,
  or enter only percentages of a pretend total. Everything except real gains
  and income works the same.
- **Who can see it:** you, and - if your account is managed by an advisor -
  that advisor. Your advisor's notes about you are shown to you, except ones
  they mark private.
- **Passwords** are stored only as a salted, one-way hash, never as text.
  "Stay signed in" keeps a random token in a cookie on your device; the app
  stores only a scrambled copy of it. Changing your password or logging out
  ends it.
- **Brokerage logins:** this app never asks for or stores your brokerage
  username or password. It only reads the statement files you import.
- **Deleting:** you can delete all your holdings yourself - in the sidebar, under
  **Your data**. To have your whole account deleted, contact whoever manages it.
"""),
    ("What's sent to the AI", """
Sage, the app's guide (Ask Sage), and the plan's suggested next steps use Claude,
an AI model from Anthropic. When you use them, the app sends:

- your investing-profile answers (goals, time horizon, risk tolerance and so on),
- your holdings as **tickers, fund names, types, sectors and percentages** of the
  portfolio - never dollar amounts, share counts, account names or numbers,
- what you type in the chat, and short notes Sage saved from earlier
  conversations.

If you choose to **read holdings from screenshots**, the images you upload are sent
to the AI so it can read them - that's the only time an image leaves the app, and
you're asked first. Crop them to just your holdings list. Only symbols, share
counts and cost are taken from what it reads, and the images aren't saved.
(Pasted text is different: the app reads it itself and nothing is sent.)

If a statement file isn't in a format the app recognizes, it may send the file's
**column-header row only** to work out which column is which. The values in the
file are read by the app itself and are not sent.

AI answers can be wrong or out of date. Check anything important before acting on it.
"""),
    ("Market data", """
Prices, company details and news come from Finnhub and Yahoo Finance. Only ticker
symbols are sent to them. Prices may be delayed or occasionally wrong, and the app
updates them on a schedule during market hours - check your brokerage for exact
figures before trading.
"""),
    ("Not affiliated", """
Waypoint is independent. It isn't affiliated with, endorsed by or
connected to Charles Schwab or any other brokerage, or to Finnhub, Yahoo or
Anthropic. Brokerage names are used only to describe which statement files it
can read.
"""),
]
