# ADR 0004: Billing by pull - Paddle, no inbound webhook

- **Status:** Accepted
- **Date:** October 2026
- **Approved:** by the owner with PLAN.md (decisions B2 and B3; step 6)

## Context

Advisor seats will be paid (step 6, behind gate L1 and the flag `billing`).
The owner is one person. Sales tax on software differs by state.

Billing providers tell an app about changes with webhooks. Streamlit can't
receive a POST, so there is nowhere for a webhook to land. The options were
a pull from the provider's API, a small second web service, a hook into
Streamlit's private server, or a Cloudflare Worker.

## Decision

1. **Paddle, as merchant of record (B2).** Paddle is the seller of record.
   It collects and files sales tax. Card data never reaches Northwend.
2. **No inbound webhook (B3).** Northwend never exposes an endpoint for the
   provider to call.
3. **Check on return from checkout.** When the advisor comes back from
   Paddle's hosted checkout, the app reads that checkout from Paddle's API,
   on the server, and activates the seat. Nothing from the browser is
   trusted.
4. **An hourly reconciliation job.** A GitHub Actions job lists the
   subscriptions and updates every seat's status. It has its own "Tell the
   admin it failed" step, like the other scheduled jobs.

## Consequences

- No new service to secure, pay for or watch, and no new way in.
- Paddle is the source of truth. A seat's status is never taken from a
  link or a form.
- A lapse or a cancellation is seen within the hour. The grace period (B5)
  absorbs that delay.
- Paddle costs about $0.90 a seat a month more than Stripe Billing with
  Stripe Tax, at $49 a seat. That buys not having to file sales tax.
- If seats grow past a few hundred, or an hour's lag starts to matter, move
  to a small webhook service (option B in step 6). That is a new decision.
- `billing.py` has no usage component. A test reads its source and fails on
  any reference to clients or intros (step 6, item 2).
