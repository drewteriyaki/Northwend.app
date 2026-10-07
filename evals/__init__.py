"""Ask Northwend's eval set (docs/AI_PLAN.md section 8; step 1 of section 10).

- cases.py   - the cases, in groups A-J (AI_PLAN 8.1): a made-up person's
               card, the question, client mode, and what must / must not happen
- checker.py - the offline checker, built on ai_policy (the production check)
               plus the eval's own rules (named funds, "says it's an AI",
               hypothetical labels, case patterns, over-refusal)
- canned.py  - good and bad answers per checker rule; tests/test_evals.py
               proves the checker flags every bad one and passes every good one
- grader.py  - Teach It Back's grader (ROADMAP R13): topics, made-up learners'
               words (a portfolio question in disguise among them) and canned
               good / bad replies, checked offline with a fake model
               (tests/test_teach_back.py)
- run.py     - asks the real model (python -m evals.run --samples 3). Never
               run in CI: it needs ANTHROPIC_API_KEY_EVAL and costs money.

Only made-up data lives here. No answer text is ever written to the repo.
"""
