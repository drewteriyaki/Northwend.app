# Northwend - context for a brainstorming session

Paste this whole document into an AI model, then use the prompt at the end
(or your own). It describes the product as it exists in October 2026, the
rules it lives by, what we've learned from testing, and what competitors do,
so ideas can be specific rather than generic.

---

## 1. What Northwend is (one paragraph)

Northwend is a free web app (northwend.app; the app itself runs on Streamlit
with a Postgres database) that is "your guide from first step to goal". People
bring their investments from **any** brokerage - by uploading the
brokerage's own CSV, pasting text, a screenshot read by AI (opt-in), typing
holdings in, or just percentages - and Northwend shows where they stand,
helps them set a goal, and walks them toward it one step at a time with an
AI guide called **Ask Northwend**. Complete beginners get a learning route
(Learn, then Start investing). Financial advisors can manage clients in the
same app. The look is a calm "expedition": topographic contour lines, the
route drawn as a trail, milestones earned as pieces of gear.

## 2. Who it's for

- **Brand-new investors** (e.g. a 19-year-old with no account): need to learn,
  practise safely and open a first account without being sold to.
- **People already investing, scattered across brokerages** (a 401(k) at work,
  a Roth IRA somewhere, an old account elsewhere): want one calm view.
- **Dividend and income investors**: care about income ahead, yield, total
  return including dividends.
- **Near-retirees**: want to know what their money could pay them and how
  long it lasts.
- **Financial advisors (RIAs)**: want a light, client-friendly tool for
  proposals, reports and meeting prep, without a heavyweight platform.

## 3. Non-negotiable principles (any idea must respect these)

1. **Free, and paid by no one.** No subscriptions planned, no ads, no
   commissions, no referral fees, no brokerage or fund company pays to be
   mentioned. (This also keeps Northwend clear of investment-adviser
   registration in the US, which applies to personalized advice *for
   compensation*.) Any idea that needs money changing hands is out of scope
   or must be flagged as such.
2. **Education, never advice.** Northwend explains, compares and does
   arithmetic on the person's own numbers. It never says "buy X / sell Y /
   hold Z" for a specific person. Anything worked out from a person's own
   answers speaks in *kinds* of funds ("a broad US stock index fund"), never
   tickers; named examples appear only in general education that is the same
   for everyone. Projections are always labelled hypothetical.
3. **Privacy first.** No brokerage login, ever (no account linking/aggregation
   like Plaid). Uploaded files are read and deleted. Account numbers are cut
   to the last 3 digits. The AI sees percentages, never dollar amounts, share
   counts, account names or numbers. Emails never contain figures. No
   tracking or ads; usage statistics are off.
4. **Any brokerage is equal.** No broker is "primary" or recommended;
   brokerages are listed alphabetically with no ranking.
5. **Calm by default.** Summaries first, detail in a window. No urgency, no
   hype, no trading nudges. Gamification rewards learning and steady habits
   only - never trading, risk-taking or returns.
6. **Reassuring copy.** Plain words, short sentences, nothing scary.

## 4. What already exists (feature inventory)

**Getting started**
- A first-steps slideshow (taps only): timeline, feelings about ups and
  downs, experience, a "direction" (investor type).
- **Learn** (required only for the brand new): About you -> Are you ready
  (emergency fund, debt, employer match) -> Set a goal -> Learn the basics
  (six short reads) -> An example mix (kinds of funds + percentages for
  someone with your answers) -> Try it with practice money (a pretend
  monthly amount invested on real past prices).
- **Start investing**: Choose a brokerage (what to compare; well-known
  brokerages listed alphabetically, names and links only) -> Open your
  account -> Your first investments (general examples of each kind of fund
  from several providers - "to learn from, not recommendations") -> Bring it
  in.

**Seeing where you stand**
- Home: value, today's change, total return *including dividends*, the mix
  (stocks/bonds/cash/other), goal progress, the next step on your route, a
  storm note when markets drop, and one "Your money, checked" card:
  - **Fee check** - what each fund's yearly fee costs in dollars;
  - **Fund overlap** - which funds share their largest holdings, and what you
    own most of with funds looked through ("Apple: about 12% of your
    portfolio, through VTI, VOO and directly");
  - **Cash check** - how much sits in cash, sweep vs money market explained.
- Money: Income (dividends and interest ahead, month by month; received;
  yield on cost), Activity (buys/sells worked out from updates, or the
  brokerage's real history from its activity export), Watchlist.
- Live prices through the day; history synced nightly.

**Planning**
- Plan page: a goal (amount + date, by type), monthly amount, target mix and
  drift, "What if..." playground, **Stress test** (your mix through 2008,
  2020, 2022), **Where your next deposit could go** (by asset class, to move
  toward the target without selling), **Retirement income** tab (what the
  portfolio pays today; withdrawals at 3/4/5% as rules of thumb; how long a
  yearly amount lasts), **Free money check** (employer 401(k) match
  calculator).
- In progress: **money going out** (planned expenses and monthly
  withdrawals for income, built into one month-by-month projection).

**The guide**
- **Ask Northwend**: an AI chat (Claude) that explains using the person's own
  goal and mix (percentages only), with explicit rules (education only, says
  it's an AI, no guarantees). Monthly AI allowances.
- Milestones and a "kit" of gear (map, compass, boots, tent, rope...) earned
  by learning and habits.
- In progress: **Notes to future you** (a private note on a holding or the
  plan, shown back to you when markets drop) and a **monthly check-in**
  (3-minute routine, optional no-figures reminder email).

**For advisors**
- Approval with a license check; two-step sign-in required.
- Your clients: every client on one page (value, alerts, reviews due, who
  needs a look), client names and households, one-step "add and send invite"
  from the advisor's name and firm.
- Proposals (today's mix vs proposed, 2008/2022, value at the goal date) the
  client can accept; meeting prep (what changed + AI-drafted talking points);
  progress reports; notes (archived, never deleted, with edit history);
  Message all clients; model portfolios; a weekly counts-only email; client
  record export (for record-keeping duties).
- A "client mode" so an advisor's clients don't see example funds or the
  beginner trail.
- In progress: add clients from a CSV, a demo book while approval is
  pending, ending a relationship (the client keeps their account).

**Planned next (owner's backlog)**
- Year in review (a private yearly recap, plus a version to share with no
  dollar figures).
- Account map - an "if something happens to me" binder (every account,
  who to call, notes for family, a PDF only you download, a guide to finding
  old 401(k)s).

## 5. What we learned from persona walkthroughs

- **Beginners** loved practice money, the calm tone and the "guide, not a
  salesperson" stance. They self-select out when the first screen shows a big
  portfolio or asks for a brokerage file; they need a reason to come back
  before they have any money invested.
- **Phone users** are the majority for beginners; long windows and tiny
  targets hurt.
- **Scattered-account investors** value one view across brokerages, but
  updating holdings is manual (no account linking, by design) - so the app
  must earn the update each month.
- **Advisors** liked proposals, meeting prep and reports, but need value in
  the first 10 minutes, bulk client setup, records they can keep, and
  confidence about data and compliance.
- The biggest open question: **why would someone come back every week or
  month** when there's no linked account updating itself?

## 6. Competitive landscape (rough, for orientation)

- **Aggregators / net-worth trackers** (Empower Personal Dashboard, Monarch,
  Copilot, Kubera, Rocket Money): link accounts automatically (Plaid-style),
  strong dashboards and budgets; often monetized by subscriptions or by
  upselling advice/wealth management. Northwend deliberately doesn't link
  accounts.
- **Robo-advisors** (Betterment, Wealthfront, brokerages' own robos): manage
  money for a fee and pick funds - they *are* advisers. Northwend never
  manages or recommends.
- **Brokerage apps** (Fidelity, Schwab, Vanguard, Robinhood...): see only
  their own accounts; tools are tied to selling their products.
- **Research / education** (Morningstar, Investopedia, Yahoo Finance, Simply
  Wall St): rich data, often stock-picking oriented, ads or paywalls.
- **Advisor platforms** (eMoney, RightCapital, MoneyGuide, Asset-Map): deep
  planning, expensive, heavy onboarding; not consumer-friendly.
- **Northwend's current edges**: works with any brokerage without a login;
  calm, beginner-first route from zero to a first investment; education-only
  AI guide that never sells; fee/overlap/cash checks; practice money on real
  prices; advisors and their clients in one gentle app; completely free and
  paid by no one.

## 7. Practical constraints for ideas

- Streamlit app (Python), Postgres; a static website (no scripts allowed by
  its security policy). Small team (one owner + AI coding help).
- Market data from free/low-cost sources (Finnhub, Yahoo Finance); no paid
  data feeds yet; no brokerage connections.
- AI: Claude via API with monthly per-user allowances; the AI must never see
  dollar amounts or account details.
- US-focused (18+, US residents).
- Email via Resend (transactional; any marketing email would need
  unsubscribe).
- Must stay free with no compensation from anyone.

## 8. Prompt to use

> You are a product strategist with deep knowledge of personal finance
> apps, behavioral finance and community/retention design. Using the
> context above about Northwend, brainstorm ideas that would make it
> something **no competitor offers** and that people would feel a real
> need to sign up for and keep using for years.
>
> Rules: every idea must respect the principles in section 3 (free and paid
> by no one; education never advice - no buy/sell/hold for a specific person
> and no tickers tied to a person; privacy first - no brokerage login, the AI
> never sees dollar amounts; any brokerage equal; calm, no trading nudges;
> gamification only for learning and habits). Prefer ideas that work
> *because* Northwend doesn't link accounts and doesn't sell anything, rather
> than in spite of it.
>
> Give me:
> 1. **15 ideas**, each with: a name; the user problem it solves; who it's for
>    (beginner / scattered investor / income investor / near-retiree /
>    advisor / family); why no competitor can or will copy it (structural
>    reason, e.g. their business model forbids it); what makes someone come
>    back (the retention loop); rough effort (S/M/L); and any risk to the
>    principles.
> 2. Group them into **3-4 possible directions** for the product (a coherent
>    strategy each), and say which direction you'd bet on and why.
> 3. **5 "wild" ideas** that bend the usual assumptions (social, family,
>    offline, rituals, physical world, AI) while still respecting the rules.
> 4. For your top 3 ideas: the smallest version we could ship in a week to
>    test whether people actually come back.
>
> Avoid generic features every finance app has (budgets, net worth charts,
> price alerts, stock screeners, social trading/leaderboards of returns).
