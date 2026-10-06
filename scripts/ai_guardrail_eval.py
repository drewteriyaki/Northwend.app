"""Try Ask Northwend's rules against the real model - now the eval set in
evals/ (docs/AI_PLAN.md section 8). Kept so the old command still works:

    python scripts/ai_guardrail_eval.py [--samples 3] [--group A] ...

is the same as `python -m evals.run ...` (see evals/run.py for how to run it
on the eval workspace). Not run by the test suite: it calls the API.
"""

from __future__ import annotations

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from evals.run import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
