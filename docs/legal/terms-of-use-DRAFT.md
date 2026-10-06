# Northwend Terms of Use

> **DRAFT - not legal advice; for review by a qualified lawyer before use.**
> The lawyer's working copy, written for after the hosting move. The version
> people read is `docs/legal/terms-of-use.md` (on the website, linked from sign-up),
> with these notes resolved in plain, careful wording - keep the two in step. Every statement
> about what the app does is based on the code as of October 2026 (see
> `disclosures.py`, whose developer header lists which code each data statement
> depends on). Assumptions and blanks are marked **[OWNER: ...]** (a fact or
> decision for the owner) or **[LAWYER: ...]** (a legal question).

**Effective date:** [OWNER: date these terms take effect]
**Operator:** Andrew Zhang, an individual developer ("we", "us") [LAWYER: should the
service be run through a company (for example an LLC) before launch? If so, name it here.]
**Contact:** support@northwend.app

---

## 1. What Northwend is

Northwend is a free website and app that helps you follow your own investments
and learn how investing works. You can bring in holdings from any brokerage (by
pasting, uploading a file, reading screenshots or typing them in), see their value,
set a goal, read short lessons, try "practice money" on past prices, and ask an AI
guide ("Ask Northwend") questions. Financial advisors can also use it with their
clients.

Northwend does not connect to your brokerage, cannot place trades, and never asks
for your brokerage login.

## 2. Who can use it

- You must be **18 or older**.
- Northwend is offered **only to people in the United States**. [OWNER: confirm
  US-only; people confirm "I live in the United States" next to "I'm 18 or
  older" when they agree, and both are kept with their date, but the app does
  not check location.] [LAWYER: whether to state
  that use from outside the US is at the user's own risk and not permitted.]
- You must be able to agree to these terms. If you use Northwend for a business
  (for example an advisory firm), you agree for that business too.

## 3. Education, not advice

**Everything in Northwend is for education and information only.** That includes
the dashboard, plans and projections, Learn, example mixes, example funds, practice
money, model portfolios, alerts, and every AI answer.

- Nothing in Northwend is a recommendation to buy, sell or hold any security, or a
  recommendation of a particular mix for you.
- Northwend is **not** a registered investment adviser, broker-dealer, financial
  planner, tax adviser or law firm, and we are not acting as your adviser.
- Anything worked out from your own answers (your "example mix", your "direction")
  is described in kinds of funds and percentages - a common rule of thumb for
  learning. Apart from your own holdings and watchlist, named funds appear only in
  material that is the same for every user (general reads, which show examples of
  each kind of fund from several providers, and the made-up example portfolio), or
  that comes from your advisor. They are not recommendations.
- If an advisor gave you access, their advice comes from them, not from Northwend.
- Consider talking to a licensed professional before making investment decisions.

[LAWYER: confirm this framing, together with the app's design (no named funds tied
to a person's answers; AI rules in `advisor.GUARDRAILS`), keeps Northwend within the
"publisher" / impersonal-advice side of the Investment Advisers Act and state law.]

## 4. The AI guide and other AI features

Northwend uses an AI model (Claude, from Anthropic) for the AI guide, for
advisors' meeting talking points, and - only when
you choose - for guessing a file's columns and, where it's offered, reading
screenshots.

- **AI answers can be wrong, incomplete or out of date.** Check anything important
  before relying on it.
- The AI is instructed to give education only: it will not recommend buying,
  selling or holding a specific security or a specific mix for you, and it will
  say it is an AI if asked. These instructions reduce but cannot remove the chance
  of a mistaken or inappropriate answer.
- **Projections are hypothetical.** Any figure about the future (growth at a
  yearly rate, reaching a goal, retirement income) is an illustration built on
  assumptions, not a prediction or a promise.
- Each account has a monthly allowance of AI requests. We may change allowances
  or turn AI features off at any time.
- Don't put information into the chat that you don't want sent to the AI provider
  (see the Privacy Policy for what is sent).

## 5. Free service; how Northwend is paid

- **Northwend is free.** There are no plans to charge for it.
- **Northwend isn't paid by anyone for what it shows.** It receives no money or
  other compensation from users, advisors, brokerages or fund companies. It takes
  no commissions, trading fees or referral fees, and no company pays to be named
  in examples, lists or AI answers. Brokerage lists are alphabetical and never
  ranked.
- **No ads, and your data is not sold.**
- If we ever decide to charge for anything, we will **give notice first** (see
  section 14), and nothing will be charged without your agreement.

## 6. Your account and keeping it secure

- Give accurate sign-up information and keep your email address current.
- Keep your password private and don't reuse it elsewhere. You are responsible
  for what happens under your account.
- Advisor and admin accounts must use two-step sign-in; anyone else can turn it on.
- Tell us right away at support@northwend.app if you think someone else has used
  your account.
- We may lock an account temporarily after repeated wrong passwords or codes.

## 7. Acceptable use

Don't:

- break the law, or use Northwend to give unlawful financial advice;
- add someone else's financial information without their permission;
- try to get into accounts or data that aren't yours, probe or attack the
  service, or get around its limits (for example AI allowances or sign-up checks);
- copy, scrape or resell the service or its market data, or use it to train AI
  models;
- upload malware, or anything you don't have the right to share;
- use automated tools to create accounts or send heavy traffic;
- try to make the AI produce harmful content or ignore its rules.

## 8. Your information and how accurate it is

- **You own the information you add.** You give us permission to store and
  process it only to run Northwend for you (and for your advisor, if you have one),
  as the Privacy Policy describes.
- **Imported data may be wrong.** Northwend reads what you paste, upload, type or
  photograph. Files from different brokerages vary, screenshots can be misread, and
  some columns may be guessed. Check what you bring in against your brokerage
  statements. Your brokerage's records are the official ones.
- **Prices may be delayed or wrong.** Prices, fund details and news come from
  Finnhub and Yahoo Finance (Yahoo through an unofficial library). They may be
  delayed 15 minutes or more, and occasionally missing or wrong. Mutual funds
  usually price once a day. Don't trade on Northwend's figures - check your
  brokerage first.
- **Figures are estimates.** Gains, income estimates, fees, allocations, projections
  and practice results are worked out from that data and from assumptions, and can
  be wrong.

## 9. Advisors

These extra terms apply if you use Northwend as a financial advisor.

- **Your advice is yours.** You are solely responsible for any advice or
  recommendation you give your clients, including proposals, model portfolios,
  notes and reports you share through Northwend, and for its suitability.
  Northwend does not supervise, review or approve advice.
- **Your obligations are yours.** You remain responsible for your own licensing
  and registration, compliance, books-and-records and record-keeping obligations,
  privacy notices to your clients, and your firm's policies. Northwend is not a
  record-keeping system of record. [LAWYER: confirm wording on SEC Rule 204-2 /
  FINRA record-keeping and Regulation S-P.] [OWNER: say whether advisors can export
  a client record for their own files; another change in progress adds a client
  record export.]
- **Your licence is checked.** You ask for advisor access with your firm's name and
  your CRD or licence number, and we check them before turning advisor access on
  (the operator can also turn it on directly, from outside the app). We may refuse
  or remove advisor access at any time, for example if a licence can't be confirmed
  or lapses. The check is done by hand: we look up your firm and your CRD or
  licence number on FINRA BrokerCheck or the SEC's Investment Adviser Public
  Disclosure (IAPD) site and confirm they match a current registration, and we
  keep a record of where we looked, the number that matched and the date. We
  repeat the check about once a year (we're reminded once 11 months have passed).
  If your registration hasn't been re-checked within 13 months, you're left out of
  any advisor listing until it has been. [LAWYER: confirm this is enough, and
  whether a lapsed registration should also pause access to clients' accounts.]
- **The advisor agreement.** Before you use the advisor tools you accept the
  Northwend advisor agreement: that you represent a registered firm, that all
  advice you give through Northwend is yours under your firm's supervision, that
  you won't present Northwend as an adviser, and that your client agreements,
  Form ADV delivery and record keeping are yours. We keep which version you
  accepted and when, and ask again when it changes. While Northwend is in beta,
  advisor seats are free and the agreement is marked "beta". [LAWYER: the
  agreement's text is in `advisor_agreement.py` (TEXT), a draft for your review.]
- **Whose advice it is.** Everything you share with a client through Northwend -
  proposals, progress reports, notes and messages, and the emails saying one is
  waiting - shows your name and firm and says the advice is yours, not
  Northwend's (`standing_line.py`; interim wording until gate L2).
- **Client consent.** Before you add a client or their holdings, you must have their
  permission. Clients you add can see their own portfolio, plan, and the notes you
  share with them (not ones you mark private). You can see everything in their
  account except what's theirs alone: their notes to their future self and their
  monthly walks.
- **Client relationships.** Your relationship with your clients is between you and
  them. Northwend is not a party to it and does not refer clients to advisors.
  Emails you send through Northwend (a client's setup link, or a note that a report
  or message is waiting) carry your name and firm as the sender name, go out from
  Northwend's address, and never include figures or your message text.
- **Ending.** If you close your advisor account, your clients keep their own
  accounts. [OWNER: confirm what happens to clients' access and to your notes;
  today an advisor with clients must contact us to close the account.]

## 10. Changes to the service, and ending your use

- Northwend is an early (beta) service. Features may change, pause or end, and the
  service may be unavailable at times.
- **You can stop at any time.** The Account page lets you download a copy of your
  data and delete your holdings or your whole account (an advisor-managed client
  asks their advisor or us; an advisor with clients contacts us).
- **We may suspend or close an account** that breaks these terms, puts others at
  risk, or that the law requires us to close. Where we can, we'll tell you first
  and give you a chance to download your data.
- We may shut Northwend down. If we do, we'll give at least [OWNER: number] days'
  notice where we can, so you can download your data. [LAWYER: notice period.]

## 11. No warranties

Northwend is provided **"as is" and "as available"**, without warranties of any
kind, express or implied, including merchantability, fitness for a particular
purpose, accuracy and non-infringement. We don't promise that it will be
uninterrupted, error-free or secure, or that any figure, price, projection or AI
answer is correct. [LAWYER: state-specific consumer-law carve-outs.]

## 12. Limitation of liability

To the fullest extent the law allows:

- we are not liable for any investment decision you make or any trading or
  investment loss, whether or not it relied on Northwend;
- we are not liable for indirect, incidental, special, consequential or punitive
  damages, or for lost profits, data or goodwill;
- our total liability for any claim about Northwend is limited to [LAWYER: amount;
  for a free service often USD 100 or less].

Some places don't allow some of these limits, so they may not all apply to you.

## 13. Indemnity

If you use Northwend in a way that breaks these terms or the law (or, for advisors,
in connection with advice you give your clients), you agree to cover our reasonable
costs of claims that result. [LAWYER: scope; whether to apply to consumers.]

## 14. Changes to these terms

When these terms change in a way that matters, we'll update the effective date
and tell you in the app the next time you sign in (and by email if you have a
confirmed address [OWNER: the app does not send this email today]) at least [OWNER: number] days before the change takes effect,
except where a change is needed sooner for legal or security reasons. If you keep
using Northwend after that, the new terms apply. The app records which version of
its terms each sign-up agreed to.

## 15. Governing law and disputes

These terms are governed by the laws of [LAWYER: state], without regard to conflict
of laws rules. Disputes will be resolved in the state or federal courts in
[LAWYER: county, state]. [LAWYER: arbitration / class-action waiver, small-claims
carve-out - include or not.]

## 16. Other

- **Not affiliated.** Northwend is independent and not affiliated with or endorsed
  by any brokerage, fund company, Finnhub, Yahoo or Anthropic. Brokerage and fund
  names are used only to describe what Northwend can read or to give examples.
- If part of these terms can't be enforced, the rest still applies.
- These terms, the Privacy Policy and the in-app "About and disclosures" page are
  the whole agreement between you and us about Northwend.
  [LAWYER: reconcile with `disclosures.py`, which is shown in the app today and
  currently acts as the terms users agree to at sign-up.]
- Questions: **support@northwend.app**.
