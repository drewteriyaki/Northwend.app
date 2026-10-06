# ADR 0001: Screenshot reading

- **Status:** Accepted
- **Date:** October 2026
- **Approved:** by the owner with PLAN.md (decision D1, as updated for brief §5.1)

## Context

People can bring holdings in from a screenshot of their brokerage. Today
`screenshot_read.py` sends the whole image to the AI. The image shows every
balance, account name and account number on the screen.

The brief (§5.1) now says the AI never sees holdings, account names or
numbers. A separate consent screen doesn't fix that. Screenshots are the one
feature that breaks the figures rule by design.

Paste and CSV import already work without any AI.

## Decision

1. The AI path stays in the code, behind the flag `screenshot_ai`
   (`flags.py`). It is off in production. Staging may turn it on.
2. Next, try reading screenshots on the server with local OCR, and pass
   the text to the paste reader (`paste_parse.py`). No image or text leaves
   the server.
3. Test it on made-up screenshots from five brokers. If it reads all five,
   bring screenshots back without AI and remove the AI path.
4. If it doesn't, leave screenshots off. Paste and CSV stay the ways in.

## Consequences

- Production never sends a screenshot to the AI. The privacy wording can
  say so plainly.
- People on the live copy lose screenshot import until OCR works. Paste and
  CSV cover the same brokers.
- OCR adds a dependency (an OCR engine) and some server time per image.
  Both are checked before it ships.
- Removing the AI path also removes one AI cost and one place an AI call
  can fail.
- `views/holdings_input.py` checks `flags.on("screenshot_ai")` where the
  screenshot option is drawn. `tests/test_flags.py` covers the flag.
