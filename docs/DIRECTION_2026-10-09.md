# Northwend - direction update, October 9, 2026

The owner's decisions after a strategy review, as given to the Claude Code
session on October 9, 2026 (kept here word for word, apart from this header and
the notes at the end). Read it after the status report of October 9 and before
touching `docs/PLAN.md`, `docs/LEGAL_GATES.md`, `docs/PRINCIPLES.md` or the legal
pages. It supersedes the earlier briefs where they conflict. Companion: the
owner's workbook `Northwend_Plan_2w_30_90_180.xlsx` (the plan, revenue model,
costs, legal map, retention and metrics; not in the repo).

## 1. The sentence it lives by (revised)

Northwend never gives individual recommendations and never sells anyone's data.
Most of it is free for individuals, with an optional paid tier for more of the
guide. Advisors pay a flat seat fee for software and are listed equally. Any
advice comes from a registered firm the person chose, never from Northwend.

Update `docs/PRINCIPLES.md` to this. Grep app and website copy for the old
sentence and the phrases "paid by no one", "free, nothing to sell" and "calm";
propose rewrites in plain, literal words (brand: logo 3d, theme E2 navy band).

## 2. What changed, and what did not

Changed:

- Paid advisor seats open now, for the workspace only. Gate L1 is split: L1a =
  workspace seats and billing (opens without a lawyer); L1b = anything that
  connects a person to an advisor (stays gated with L2). Founding price
  $79/month or $790/year locked for life for the first 20; standard $99 later. A
  one-time onboarding service ($200-400) is sold by email and invoiced through
  Stripe.
- Optional individual Plus tier is allowed (new gate L4a): more Ask Northwend
  questions and decodes per month. Everything else stays free. It is capacity,
  never "more personal"; the conclusion policy is unchanged. Not before the
  90-day window.
- Product analytics are allowed: self-hosted PostHog or Plausible, events only,
  no third-party ad trackers, with an account-level "don't use my data to improve
  the app" opt-out honoured in code. Privacy and Terms are rewritten to say
  exactly this.
- No lawyer and no insurance during the early beta, by the owner's decision.
  Insurance (tech E&O + cyber) is scheduled for month 4, paid from seats. A
  one-hour attorney consultation is scheduled for month 3. The scoped opinion
  comes before the directory, whenever seats or a competition pay for it.

Not changed:

- No ads in the app. No data selling. No affiliate or referral fees. No
  brokerage or fund company pays to be mentioned. Brokerages alphabetical.
- No matching algorithm and no ranking of advisors, ever. Directory order is
  alphabetical within filters the person applies. Analytics data is never used
  to choose or suggest an advisor. (Reason: a compensated recommendation of
  advisers is itself treated as investment advice, and makes Northwend a
  promoter. See the Legal map sheet.)
- The AI never sees individual holdings, share counts, account names or
  numbers; derived planning figures only on per-conversation opt-in. Conclusion
  policy and eval set stand.
- Directory and introductions (L2 / L1b) stay off until the scoped opinion
  exists.
- Clients own their data and keep it on a clean exit. Consent and access logs
  stay.

## 3. Why the directory needs review and the workspace does not

- Selling advisors software (meeting prep, proposals, reports, records, client
  view) is ordinary B2B SaaS; the advisor is the regulated party. No adviser
  registration, no promoter status. A template agreement with four plain-words
  clauses is enough to start: the advisor is a registered representative of
  their own firm and responsible for all advice; Northwend provides software and
  records only; the client owns their data and keeps it if they leave;
  Northwend's liability is limited to fees paid.
- Connecting a person to an advisor for compensation triggers the SEC Marketing
  Rule (a compensated referral makes the platform a "promoter": written
  agreement, disclosure to the prospect, adviser oversight) and, in many states,
  solicitor registration. SEC guidance also treats advice about selecting
  advisers as investment advice. A flat-fee, unranked, person-chooses directory
  is the structure most likely to stay outside those rules, but that is exactly
  the question the scoped opinion answers. So L2 waits.
- A paid individual tier is lawful if the AI stays non-prescriptive (general
  education and arithmetic on the person's own inputs). Direct payment raises
  the stakes on the conclusion policy; include it in the opinion later, and keep
  the tier about capacity.
- Analytics with an accurate Privacy Policy are lawful; the promise to keep is
  "no third-party ad trackers and no data selling", not "no analytics".

## 4. Build order (the 2-week / 30 / 90 / 180 plan, condensed)

Next 2 weeks - finish the open-beta list:

1. Render cron jobs released and GitHub schedules removed (owner enters secrets).
2. Restore drill run; Neon backup branch named for deletion.
3. Live copy gets its own API keys and least-privilege DB roles.
4. Market data: recommend a licensed provider; switch on owner's OK; yfinance
   out of production.
5. Beta flag set: Walk, ledger, log, storm drill, 401(k) decoder, decoder_public
   on; directory, intros, billing, pay_yourself off.
6. Second-walk-within-45-days measure recorded and visible.
7. `NORTHWEND_MAX_SIGNUPS_PER_DAY` with a plain "we're full for today" page.
8. Split L1 into L1a / L1b in `docs/LEGAL_GATES.md`; add L4a.
9. Draft the revised Privacy Policy, Terms and the advisor software agreement
   from templates, in plain words, for the owner's approval. No lawyer during
   beta. Owner, same window: LLC; business bank account; console spend limit;
   DMARC to quarantine; Cloudflare cache rule.

30 days - first revenue and the beta opens:

10. Founding seats (price, count, annual option in config); Stripe hosted
    checkout and customer portal; signed webhooks; reconciliation job; graceful
    lapse (read + export).
11. Advisor page on the website: what the seat is and isn't, founding price,
    demo book, the four clauses.
12. Analytics with the opt-out. Marketing copy rewrite. Open sign-up with the
    daily cap.
13. First-30-days sequence: day 0, 3, 7, 14, 30 with one figure-free email each.
14. Tie each Learn topic to the person's own numbers (bonds -> their bond share
    and 2022; fees -> their fee check).
15. Weekly release day; public changelog.

Owner: hand outreach to 40 independents (XYPN, NAPFA small firms, newly
registered state RIAs, FPA Georgia); target 10 seats by day 30.

90 days - prove both sides:

16. 20 founding seats; record real AI and data cost per seat in `AI_COSTS.md`.
17. Individual Plus tier (L4a): capacity only; Stripe; one-click cancel.
18. Workspace improvements from founding-seat calls, built for advice-only and
    flat-fee planners first: a dated one-time-review plan page, bulk import
    polish, client mode.
19. Statement and fact-sheet decoder; Walk Together.
20. Service-layer extraction begins (hardening Phase 3).

Owner: E&O + cyber insurance (month 4); attorney consultation (month 3); two
pitch competitions.

180 days - open the directory, if the opinion exists:

21. Scoped opinion -> open L2 and L1b: alphabetical within the person's filters,
    two-step consent, access log visible to the client. Standard seats at $99;
    founding stays $79.
22. Annual plans; team seat for two-person firms.
23. Seasons, Trail Forks, Explain It To Someone, Pay Yourself.
24. Frontend replacement begins (auth first); mobile web app after.
25. Scope the employer channel ("Northwend for your team"): free for employees,
    flat annual fee from the employer.

If the money for the opinion is not there at 180 days, the directory simply
waits; nothing else in the plan depends on it.

## 5. Advisor targeting (for the website and outreach copy)

Independent, registered, solo and two-person firms, especially new, fee-only or
flat-fee planners taking clients who are just starting. Not advisors at large
firms (they need their firm's compliance approval for any outside listing and
already have tools). The pitch: a prospect who arrives with holdings, goal and
fee check already entered; a proposal and meeting prep in ten minutes; records
they can keep; a price under their planning software; clients who keep their
account if they leave. Northwend is not trying to be RightCapital's planning
engine; it is the front door and the client-facing view that planning platforms
do not have, and a full replacement only for advice-only planners who never
needed one.

## 6. Retention (unchanged in spirit; now scheduled)

- The Monthly Walk is the only ask; never a daily nudge.
- First-30-days sequence (day 0 first steps; day 3 practice money moving; day 7
  fee check or 401(k) decoder; day 14 goal set; day 30 first walk), each step
  earning gear (map, compass, boots, tent, rope), each email figure-free.
- A path before they have money: practice money -> first $50 -> first deposit ->
  first walk.
- Learning tied to the person's own numbers.
- Walk Together (90 days); Seasons and Trail Forks (180 days).
- The one measure: second walk within 45 days. Owner sets the threshold before
  launch.

## 7. Standing rules for every session

Never build matching or ranking of advisors. Never add usage-based or
per-client billing. Never let any helper write to the database or change
holdings. Never remove a disclosure. Never use analytics data to choose an
advisor for a person. Keep L2 and L1b off until the owner says the opinion
exists. Show diffs before any destructive change.

## 8. What to do first

1. Read this file and the workbook's Plan sheet.
2. Update `docs/LEGAL_GATES.md` (L1a/L1b/L4a), `docs/PRINCIPLES.md` (section 1)
   and `docs/PLAN.md` (section 4 order), ticking what the status report already
   shows done.
3. Draft the three legal-lite documents (Privacy, Terms, advisor agreement) in
   plain words and stop for the owner's review.
4. Continue the 7-item engineering list from where it stands. Report after each
   item.

---

## Notes from the session (not part of the owner's text)

- **Already built, ahead of this schedule** (behind flags, off on live unless
  listed in its flags): Seasons, Trail Forks, Explain It To Someone, Pay
  Yourself (item 23); Walk Together exists as "Doing it together"
  (`together.py`, item 19); the fact-sheet decoder exists (paste only) -
  statements still wait for local redaction (item 19).
- **The name L4a.** `docs/LEGAL_GATES.md` uses L4 for in-house advice, which is
  never built, and `flags.py` refuses an `L4` gate. L4a here is a different
  thing (the paid individual tier). The name is kept as given; when it's built
  its setting should be spelled so it can't be mistaken for L4.
- **Changing published promises.** The live Privacy Policy, Terms, About page
  and website say "no subscriptions", "no tracking" and "free for individuals".
  The rewrite is item 9; it takes effect only when published, with the date and
  version changed and existing users told (`users.terms_version` holds the
  `disclosures.LAST_UPDATED` each person agreed to). Analytics and the Plus tier
  must not ship before that.
