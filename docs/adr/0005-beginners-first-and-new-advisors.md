# ADR 0005: Beginners first; a place for newer advisors to be found

- **Status:** Accepted (direction). The parts that connect people with advisors
  stay behind gate L2 until the lawyer has reviewed them.
- **Date:** October 6, 2026
- **Approved:** by the owner ("Lets continue to market to new users as like a
  'new to investing start here' kind of app and then they can find a guide if
  they want to.")

## Context

The owner sees a gap: advisors early in their careers have no client base and
build one by cold calling, while people new to investing are already on
Northwend learning, setting goals and practising. For a beginner, a one-time
review with an advisor for a flat fee is the easiest way to try advice.

Most of what this needs is built behind flags (PLAN step 5): the directory
("Find a guide", flag `directory`, gate L2), introductions and two-step consent
(flag `intros`, gate L2), the advisor agreement, licence checks, the standing
"advice is the advisor's" line, consent records and the access log.

## Decision

1. **Northwend is marketed as "new to investing? start here".** The homepage and
   "New to investing" lead with learning, practice money and a goal. Finding a
   guide is a later, optional step, never the pitch.
2. **Advisors early in their careers are a named audience** for the advisor side:
   the tools work from the first client, seats are free in the beta, and (once
   L2 opens) people already learning on Northwend can find them.
3. **The guide stays optional and calm.** A quiet "Want a second opinion? Find a
   guide" link after someone finishes Learn or sets a goal; no pop-ups, no
   prompts, nothing counted about who browses.
4. **A one-time review is the advisor's service, not Northwend's.** Listings can
   say an advisor offers a one-time review (or flat fee, hourly, subscription,
   assets under management), and what it costs as the advisor states it. The
   person pays the advisor directly. Northwend never takes the payment or a cut.
5. **Never paid per lead, introduction or client.** If Northwend earns from
   advisors, it's one flat seat fee that doesn't change with introductions or
   clients won (PLAN step 6; `billing.py` has no usage component, a test checks).
   Being paid per lead would make Northwend a paid promoter under the SEC's
   Marketing Rule and state solicitor rules, and break "nobody pays to be shown".
6. **How an advisor is paid is shown plainly**, for every listing, in words a
   beginner understands, never ranked or filtered toward one model.

## To build (behind the existing flags, off on live)

- A "one-time review" offering on directory listings, and whether it's a filter
  (that changes decision B4's five filters: an L2 question).
- The calm "Find a guide" link on Learn and Plan (shown only where `directory`
  is on, never in client mode, never for advisors).
- A short, beginner-friendly "How advisors are paid" explainer beside the
  directory.
- The website's "For advisors" page: a question for advisors building a
  practice - no promises of clients, nothing about Find a guide until L2 opens.

## Consequences

- The L2 lawyer review should look at exactly this model: listings, the
  one-time-review offering, introductions, how-they're-paid wording, and the
  flat seat fee.
- The published Terms say Northwend "does not refer clients to advisors". That
  wording changes with the lawyer's help before L2 opens.
- Any later idea that pays Northwend per lead, per introduction or per client
  needs a new ADR, a lawyer's sign-off and new disclosures first.
