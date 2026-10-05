# Northwend AI costs

Written October 5, 2026, against commit `899f35a` (staging). It goes with
`docs/AI_PLAN.md`. Nothing here is built yet.

**Source note.** The master brief (§5.4) says the cost controls from the
"earlier AI brief" stand. That brief was not shared with this session. This
document works from §5.4, §8a and the code.

**How the numbers were made.** Prompt sizes were measured from the code
(characters of the real `system_prompt`, tools and requests, built with the
eval script's made-up profile), divided by 4. Output sizes, conversation
lengths and tool-use rates are assumptions, listed in §4. Treat every dollar
figure as an estimate within about ±30%. Real numbers come from the token
logging in step 4 of the migration.

---

## 1. Prices

From Anthropic's list prices as cached in the Claude API reference
(dated 2026-09-25). **Verify on Anthropic's pricing page before relying on
them.** Dollars per million tokens.

| Model | ID in code | Input | Output | Cache write (5 min) | Cache write (1 h) | Cache read | Batch in / out | Min. cacheable prefix |
|---|---|---|---|---|---|---|---|---|
| Claude Sonnet 5 | `claude-sonnet-5` (`advisor.py:21`) | $2.00 | $10.00 | $2.50 | $4.00 | $0.20 | $1.00 / $5.00 | 1,024 tokens |
| Claude Sonnet 5.5 (proposed) | `claude-sonnet-5-5` | $2.00 | $10.00 | $2.50 | $4.00 | $0.20 | $1.00 / $5.00 | 512 tokens |
| Claude Haiku 4.5 | `claude-haiku-4-5-20251001` (`csv_import.py:445`) | $1.00 | $5.00 | $1.25 | $2.00 | $0.10 | $0.50 / $2.50 | 4,096 tokens |

Notes:
- Cache writes cost 1.25 times input (5-minute life) or 2 times (1-hour
  life). Reads cost 0.1 times. A read refreshes the timer.
- Batch is half price, results within 24 hours. Batch prices above are
  derived from that rule; verify.
- Thinking tokens are billed as output. Sonnet 5 and 5.5 think by default
  (adaptive), including the screenshot call, which doesn't set `thinking`.
- Sonnet 5's tokenizer uses about 30% more tokens than older models for the
  same text. Characters ÷ 4 may undercount by up to that much.
- Images cost about width × height ÷ 750 tokens. A phone screenshot is
  roughly 1,600-4,000 tokens depending on how far it is scaled down.
  **Verify with `count_tokens` on real screenshots.**
- Zero data retention (ZDR) is an arrangement with Anthropic, not a
  setting. The newest top-tier models (Fable) are excluded from ZDR. Sonnet
  and Haiku are not listed as excluded. **Confirm with Anthropic** that ZDR
  covers the models in use, and that it is available to an account this size.

---

## 2. Per-call token estimates (today)

| Call | Input (measured, chars ÷ 4) | Output | max_tokens |
|---|---|---|---|
| Chat: tools (2 tool schemas) | 3,803 chars ≈ **950** | - | - |
| Chat: guardrails alone | 2,614 chars ≈ 650 | - | - |
| Chat: system, new user, no holdings | 6,060 chars ≈ **1,500** | - | - |
| Chat: system, full profile, 8 holdings, 600-char notes | 8,123 chars ≈ **2,030** | - | - |
| Chat: system, full profile, 30 holdings, 1,500-char notes | 13,284 chars ≈ **3,320** | - | - |
| Chat: each earlier turn in history | user ≈ 60, answer ≈ 650 (assumed) | - | - |
| Chat: one reply | - | ≈ 650 text + 500 thinking (assumed, medium effort) | 16,000 × up to 4 rounds |
| Plan next steps | system ≈ 2,030 + chat transcript (0-15,000) + request ≈ 155 | ≈ 450 + 900 thinking | 4,000 |
| Meeting prep | system ≈ 2,030 + facts ≈ 75 + request ≈ 140 | ≈ 400 + 400 thinking | 2,000 |
| Screenshot read | prompt ≈ 360 + about 1,600-4,000 per image | ≈ 300-600 JSON + thinking | 4,000 |
| CSV / activity column mapping | ≈ 240 | ≈ 60-80 | 400 |

Measured with `scratchpad/measure_ai.py` (not in the repo) against the code
at `899f35a`.

---

## 3. Cost per chat turn

A "turn" is one message from the person and the full answer, including any
tool round.

### 3.1 Why caching mostly doesn't work today

The chat sets top-level automatic caching (`advisor.py:478`). The cache is a
prefix match: tools, then system, then messages. Three things change the
system prompt between turns:

1. **Live prices.** Weights (to 0.1%) and gain/loss % are rebuilt from live
   quotes every run (`advisor.py:364-368`), and quotes refresh every minute
   in market hours. Two turns a minute apart usually differ.
2. A memory save (`save_memory`) changes the notes section.
3. A profile save changes the profile section.

When the prefix changes, the whole context is written to the cache again at
1.25 times the input price. That is slightly **worse** than no caching. The
tool schemas alone (≈ 950 tokens) are under Sonnet 5's 1,024-token minimum,
so not even they are reused.

Caching does help *within* a turn (a tool round reads the first request),
and outside market hours when nothing was saved.

### 3.2 The numbers

Assumptions in §4. "Cache works" = prefix stable turn to turn. "Cache
breaks" = full rewrite each turn (today, in market hours).

| Scenario | No caching | Cache works | Cache breaks |
|---|---|---|---|
| **Today** (Sonnet 5, medium effort) | | | |
| Light: new user, 4-turn conversation | $0.022 | $0.016 | $0.021 |
| Typical: 8 holdings, 6-turn conversation | $0.025 | $0.016 | $0.025 |
| Heavy: 30 holdings, full notes, 20 turns, longer answers | $0.062 | $0.029 | $0.057 |
| **Target** (Sonnet 5.5, low effort, max_tokens 2,500, frozen card ≈ 1,000 tokens, 5,000-token library shared and cached) | | | |
| Typical | $0.031 | **$0.013** | $0.020 |
| Heavy | $0.059 | **$0.020** | $0.041 |

What this says:
- **Output is most of the bill** (about 70% of a typical cached turn).
  Effort and `max_tokens` matter more than input tricks.
- **Caching cuts a typical turn by about a third**, but only if the prefix is
  stable. Freezing the context card per conversation (AI_PLAN §3.5) is what
  makes it stable.
- The library makes the prompt bigger. Without caching, the target design
  costs *more* than today. The library must sit in the shared, cached block.

### 3.3 The worst case today

One message can run 4 tool rounds of up to 16,000 output tokens each, on a
40-message history with long pastes (the chat box has no length limit). That
is about **$1.31 for one message**. At 100 messages a month, one person can
cost about **$130**. An advisor at 5 times the allowances: about **$650**.
Unlikely, but nothing stops it.

The hard caps in AI_PLAN step 2 (2,000 characters in, 2,500 tokens out, 3
rounds, 30 messages) bring the worst single message to about $0.12 with a
warm cache, or about $0.40 cold. The cost-based allowance (§6) then caps the
month.

### 3.4 Other features (today, per use)

| Feature | Per use |
|---|---|
| Screenshot read (2 screenshots) | ≈ $0.026 (up to ≈ $0.08 with 5 large images) |
| CSV column mapping (Haiku) | ≈ $0.0007 |
| Meeting prep talking points | ≈ $0.013 |
| Plan PDF next steps | ≈ $0.024 (up to ≈ $0.20 with a long transcript) |

---

## 4. Assumptions

- A conversation: 6 turns typical, 4 light, 20 heavy.
- Person's message ≈ 60 tokens. Answer ≈ 650 tokens shown + 500 thinking
  (medium effort); target design 550 + 250 (low effort).
- A tool round in 25% of turns (40-50% heavy), adding ≈ 250 output tokens.
- Thinking from earlier turns is not billed again as input. **Verify** with
  logged `usage` once step 4 ships.
- Cache "works" means the 5-minute cache is warm between turns (people
  reply within minutes). The shared library block uses the 1-hour cache.
- Active-user use per month: light 4 turns, typical 24 turns (4
  conversations), heavy 100 turns (today's monthly cap) plus 10 screenshot
  reads and 5 plans.

---

## 5. Per active user and per advisor seat, per month

### 5.1 Individuals

| | Light | Typical | Heavy | Worst case |
|---|---|---|---|---|
| Today (cache as it behaves now: half works, half breaks) | $0.07 | $0.51 | $4.67 | ≈ $130 |
| Target design, before allowances | $0.05 | $0.31 | $2.01 | ≈ $12 (caps per message) |
| Target design, with the proposed allowances (§6) | $0.05 | $0.31 | ≈ $1.00-1.50 | **$1.80** |

### 5.2 Advisor seats

Today: chat, meeting prep, plan PDFs and screenshots, at 5 times the
individual allowances.

| | Light | Typical | Heavy (at today's 5× caps) | Worst case |
|---|---|---|---|---|
| Today | $0.48 | $1.55 | $24.63 | ≈ $650 |
| Target, with the proposed advisor allowance | ≈ $0.40 | ≈ $1.20 | **$17 cap** | **$17** |

Typical = 60 chat turns, 12 meeting preps, 3 plans, 4 screenshot reads a
month. Advisor drafts (AI_PLAN §9) add about $0.01-0.02 each.

At any plausible seat price, AI is a small share of seat revenue. The cap
exists to make the worst case known, not because the typical case is costly.

### 5.3 What the ceiling buys

At the proposed $100 a month: about 300 typical active individuals, or
about 100 at the per-person cap, or a mix such as 150 individuals and 10
advisor seats.

---

## 6. Proposed allowances

All counted in **cost**, worked out from the logged token counts at list
price (micro-dollars). People still see simple words: "about 12 messages
left today". The conversion uses the person's own average cost per turn.

| Allowance | Who | Daily | Monthly | Today's equivalent | Notes |
|---|---|---|---|---|---|
| Chat | individual | $0.25 (≈ 15-20 typical turns) | $1.00 (≈ 75 typical turns) | 100 messages, no daily limit | The daily cap stops a single binge |
| Habit bonus | individual | - | up to +$0.50 | none | +$0.25 for each finished Monthly Walk, +$0.25 for a written Storm Drill; learning and habits only (§5.4); never bought |
| Decode | individual | 5 decodes | $0.30 | screenshot 10, CSV 20 | Screenshots, document decoders, CSV mapping. CSV mapping on Haiku is almost free |
| System budget (automatic helpers) | per person | - | $0.05 | none | Near zero if helpers are rules (AI_PLAN §9) |
| System budget | whole app | - | $10 | none | Includes the no-account decoder pages: 3 decodes per address per day, Haiku only |
| Advisor | per seat | $2.00 | $17 in total: chat $8, drafts $6, decode $3 | 5× everything | Set in config. An advisor in a client's account uses their own |
| Bring your own key | advisors only | - | their own | none | Optional and later (after billing). Guardrails and the output check still apply. The key needs encrypted storage, which needs the `cryptography` package (PLAN D14) |
| Unlimited | admin-marked | - | - | exists | Keep for the owner and testing; counted in the global total |

Per-message caps (all users): 2,000 characters in; 2,500 output tokens; 3
tool rounds; 30 messages a conversation.

Check-then-count stays (check before the call, count after success), so
parallel tabs can overshoot by one call. That is a few cents at most.

---

## 7. The global ceiling

### 7.1 Levels

The gateway keeps a running month total (`ai_spend`) from logged tokens.

| Level | At | What happens |
|---|---|---|
| Normal | under 50% | Nothing |
| Alert | 50% | Email the admin (`ALERT_EMAIL`): spend so far, % of the ceiling, projected month end. Counts only, no names |
| Reduced | 80% | Email again. Chat runs at low effort with 1,500 output tokens. Automatic helpers and the no-account decoder pages pause. Daily chat allowances halve. Advisor allowances unchanged |
| Closing | 95% | No new conversations. Open ones may finish (up to 5 more turns). Decodes pause |
| Resting | 100% | Every AI feature shows: "Ask Northwend is resting until November 1. Everything else in Northwend works as usual." CSV import falls back to choosing columns by hand, as it does without a key |

Also: if the projection at the current daily rate passes the ceiling before
the 20th, email the admin once.

Each email is sent once per level per month (an `ai_alerts` row). The
resting copy is calm and names the date. It never says "limit", "budget"
or "cost".

### 7.2 Backstop: the console spend limit

Set in the Anthropic console, no code:
- Production workspace: 1.5 times the ceiling ($150). It only bites if the
  app's own count is wrong.
- Staging workspace: $10.
- Eval workspace: $50.

If the console limit is hit, the API returns errors. The gateway shows the
resting message for those errors, not "isn't available", and emails the
admin once (`error_alerts`, type and place only).

### 7.3 Batch and cache

- Nothing user-facing can wait 24 hours, so chat and decodes don't batch.
- The eval runs through the Batches API at half price.
- Any future nightly helper (if one turns out to need AI) batches.
- Caching as in AI_PLAN §4.2: shared library block (1-hour), card block
  (5-minute), conversation tail (automatic).

### 7.4 Beta

Invite codes (or a waitlist) while in beta, as §5.4 says. AI waits for a
confirmed email (as today). Self-made accounts get the AI allowance only
after confirmation; unconfirmed accounts are deleted after 30 days (PLAN
D5).

---

## 8. Eval costs

| Run | Calls | Cost |
|---|---|---|
| One sample of 64 cases (chat ≈ $0.025 each) + judge on Haiku (≈ $0.003 each) | 128 | ≈ $1.80 |
| Release / weekly run: 3 samples of groups A, B, C, F (36 cases), 1 of the rest (28) | 136 answers + 136 judgments | ≈ $3.80 |
| Same through the Batches API | | ≈ half |

A month of about 10 one-sample runs and 5 release runs: about $37, or about
$20 batched. Recommended budget $40, workspace limit $50.

---

## 9. Metrics for the admin page (§8a)

On Admin, counts only, exportable as CSV through `export.csv_cell`. Never a
name, never a prompt.

| Metric | How |
|---|---|
| AI spend this month | Sum of cost from `ai_spend`; with % of the ceiling and the projected month end |
| **AI cost per active user** | Individual-side spend ÷ individuals active this month |
| **AI cost per seat** | Advisor-side spend (calls by an advisor login) ÷ active advisor seats (approved now; paying once billing exists) |
| Spend by helper and by model | `ai_spend` rows |
| Average cost per chat turn | Chat spend ÷ chat turns |
| Cache hit rate | cache-read tokens ÷ (input + cache-write + cache-read tokens) |
| People at a cap | Count at the daily cap today; count at the monthly cap this month |
| Output-check hits | Count this month (no text) |
| Days resting | Count this month |
| Last eval run | Date, pass or fail, cases failed (numbers only) |
| Monthly running cost vs seat revenue | AI spend + fixed costs from config (hosting, database, email, market data) against seat revenue (from billing, later) |

"Active" needs a small new counter: one row per person per month when they
first sign in or open the app that month (`active_months(user_id, month)`).
Today nothing records it reliably (`login_sessions` has no last-used time).

### 9.1 Storage (no text, ever)

- `ai_usage`: add `input_tokens`, `cache_write_tokens`, `cache_read_tokens`,
  `output_tokens`, `cost_micro` to the existing (user, month, kind) rows.
  Back-fill list in `portfolio._ensure_schema`, both schema files.
- `ai_usage_daily (user_id, day, kind, cost_micro)`: for the daily cap. Kept
  35 days.
- `ai_spend (month, helper, model, side, calls, tokens..., cost_micro,
  check_hits)`: the app-wide totals. No `user_id`.
- `ai_alerts (month, level, sent_at)`.
- Tables with `user_id` go in `admin.ACCOUNT_TABLES` and `export.OWN`
  (tests check both).

---

## Decisions for the owner

**1. Global AI spend ceiling?**
Recommended: $100 a month in the beta, alerts at $50 and $80, reduced
service at $80, resting at $100.
Why: it covers about 300 typical users, and a known worst case matters more
than the typical one.

**2. Allowance values?**
Recommended: chat $0.25 a day and $1.00 a month; decode $0.30 a month;
habit bonus up to $0.50; advisors $17 a month (chat $8, drafts $6, decode
$3). All in config.
Why: typical people never see a limit, and the worst case per person falls
from about $130 to $1.80.

**3. Console spend limit?**
Recommended: production $150, staging $10, eval $50, as separate
workspaces.
Why: it catches a counting bug without touching normal use.

**4. Retrieval approach?**
Recommended: no vector database; the curated library in a shared, cached
prompt block.
Why: the content is small and owned, and one cache entry serves everyone
for about $0.001 a turn.

**5. Model per helper?**
Recommended: Sonnet 5.5 for chat and advisor drafts; Haiku 4.5 for CSV
mapping, glossary fallback, grader and the eval judge; rules for everything
else.
Why: Sonnet 5.5 costs the same as Sonnet 5 with a lower cache minimum, and
rules cost nothing.

**6. ZDR terms?**
Recommended: request ZDR for the production organisation now; run "no
dollars" until it is confirmed.
Why: the figures promise shouldn't rest on what someone types.

**7. Eval budget?**
Recommended: $40 a month, batched where possible, on its own workspace.
Why: about $2 a run is cheap insurance for the liability-critical rule.

**8. Bring your own key for advisors?**
Recommended: not before billing.
Why: it means storing a secret per advisor, which needs encryption at rest
first.
