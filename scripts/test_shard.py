"""Print one share of the test modules, so CI can run the suite in parallel.

    python scripts/test_shard.py COUNT INDEX     # INDEX from 1 to COUNT

Every tests/test_*.py goes into exactly one share (a test checks), balanced
by a rough cost: AppTests (each runs the whole app) count far more than plain
tests. Within a share the modules keep their alphabetical order, as
`unittest discover` runs them. Standard library only.
"""
from __future__ import annotations

import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(REPO, "tests")
APP_RUN = re.compile(r"\bat\.run\(|\.run\(\)|AppTest\.from_file")


def cost(path: str) -> int:
    """A rough cost: each place the whole app is run weighs like many tests."""
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    return 1 + src.count("def test_") + 25 * len(APP_RUN.findall(src))


def modules() -> list[str]:
    return sorted(f[:-3] for f in os.listdir(TESTS)
                  if f.startswith("test_") and f.endswith(".py"))


def shares(count: int) -> list[list[str]]:
    """The modules split into `count` shares of about the same cost."""
    weighted = sorted(((cost(os.path.join(TESTS, m + ".py")), m) for m in modules()),
                      reverse=True)
    loads = [0] * count
    out: list[list[str]] = [[] for _ in range(count)]
    for c, m in weighted:            # biggest first, each to the lightest share
        i = loads.index(min(loads))
        loads[i] += c
        out[i].append(m)
    return [sorted(s) for s in out]


def main(argv: list[str]) -> int:
    count, index = int(argv[1]), int(argv[2])
    if not 1 <= index <= count:
        raise SystemExit("INDEX runs from 1 to COUNT")
    print(" ".join("tests." + m for m in shares(count)[index - 1]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
