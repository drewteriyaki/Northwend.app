"""Rules about the code itself (PLAN 1b.4, 1b.5, audit 1.11a): no live billing
key in the repository, calculation modules kept apart from Streamlit and the
database, SQL in views/ only shrinking, and every GitHub Action pinned.

    python -m unittest tests.test_repo_rules
"""

import ast
import os
import re
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _tracked_files() -> list[str]:
    """Every file git tracks (or, without git, every file but .git's)."""
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True,
                             check=True, timeout=30).stdout
        files = [f for f in out.decode("utf-8", "replace").split("\0") if f]
        if files:
            return files
    except (OSError, subprocess.SubprocessError):
        pass
    found = []
    for root, dirs, names in os.walk(REPO):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", ".ruff_cache")]
        found += [os.path.relpath(os.path.join(root, n), REPO) for n in names]
    return found


# --------------------------------------------------------------------------- #
# 1.11a: a live billing key is never in the repository
# --------------------------------------------------------------------------- #
# Live (not test-mode) keys: Stripe's secret and restricted keys, Paddle's API
# keys and Paddle's live client-side tokens. Each needs a real-looking body
# after the prefix, so the prefixes named in docs (and here) don't count.
LIVE_KEY_PATTERNS = {
    "Stripe secret key": re.compile(r"\bsk_live_[0-9A-Za-z]{16,}"),
    "Stripe restricted key": re.compile(r"\brk_live_[0-9A-Za-z]{16,}"),
    "Paddle API key": re.compile(r"\bpdl_live_[0-9A-Za-z_]{16,}"),
    "Paddle live client token": re.compile(r"\blive_[0-9a-f]{27}\b"),
}


class LiveBillingKeyTests(unittest.TestCase):

    def test_the_patterns_catch_live_keys_and_not_test_ones(self):
        body = "4eC39HqLyjWDarjtT1zdp7dc"
        live = {"Stripe secret key": "sk_" + "live_" + body,
                "Stripe restricted key": "rk_" + "live_" + body,
                "Paddle API key": "pdl_" + "live_apikey_" + "01gtgztp8f" + body,
                "Paddle live client token": "live_" + "7d279f61a3499fed520f7cd8c08"}
        for name, key in live.items():
            self.assertTrue(LIVE_KEY_PATTERNS[name].search(f"KEY = '{key}'"), name)
        for text in ("sk_" + "test_" + body, "pdl_" + "sdbx_apikey_" + body,
                     "test_" + "7d279f61a3499fed520f7cd8c08", "a `sk_live_` prefix"):
            self.assertFalse(any(p.search(text) for p in LIVE_KEY_PATTERNS.values()), text)

    def test_no_live_billing_key_in_any_tracked_file(self):
        found = []
        for rel in _tracked_files():
            path = os.path.join(REPO, rel)
            try:
                with open(path, "rb") as fh:
                    text = fh.read().decode("utf-8", "ignore")
            except OSError:
                continue   # listed by git but not on disk (deleted, not yet staged)
            for name, pat in LIVE_KEY_PATTERNS.items():
                for m in pat.finditer(text):
                    line = text.count("\n", 0, m.start()) + 1
                    found.append(f"{rel}:{line} looks like a {name}")
        self.assertEqual(found, [], "Live keys belong in the host's secret store "
                                    "(settings.get), never in the repository - remove it "
                                    "and roll the key.")


# --------------------------------------------------------------------------- #
# 1b.5: the layer rule
# --------------------------------------------------------------------------- #
# Calculation modules: they work on what they're given and import neither
# Streamlit nor the database layer - not directly, and not through any of the
# app's modules they import. Some take a connection a caller opened (income,
# asset_classes, feature_counts read a few rows) but never open one.
# Not on the list yet, and why: perf (opens a database path itself, through
# portfolio.connect), plans (saves through auth and advising), recap (sqlite3
# for its error type), proposals (auth). Moving one of them onto the list is
# welcome; taking a module off is not.
CALCULATION_MODULES = (
    "allocation", "alerts", "asset_classes", "cash_check", "changes", "checkin", "drills",
    "employer_match", "factsheet_decoder", "feature_counts", "fees", "income",
    "inheritance_rehearsal", "lost_found", "menu_decoder",
    "metrics", "month_world",
    "next_deposit", "pay_yourself", "seasons", "shadow_trail",
    "storms", "stress", "trail_forks",
)
NOT_IN_CALCULATIONS = {"streamlit", "portfolio", "pgcompat", "sqlite3", "psycopg",
                       "psycopg_pool", "dashboard"}


def _imports(path: str) -> set[str]:
    """Top-level names of every module imported anywhere in the file
    (functions included)."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), path)
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split(".")[0])
    return names


class LayerRuleTests(unittest.TestCase):

    def test_calculation_modules_import_neither_streamlit_nor_the_database(self):
        ours = {f[:-3] for f in os.listdir(REPO) if f.endswith(".py")}
        for name in CALCULATION_MODULES:
            with self.subTest(name):
                self.assertIn(name, ours)
                seen, todo, chain = set(), [name], {name: name}
                while todo:
                    mod = todo.pop()
                    if mod in seen:
                        continue
                    seen.add(mod)
                    imported = _imports(os.path.join(REPO, f"{mod}.py"))
                    bad = sorted(imported & NOT_IN_CALCULATIONS)
                    self.assertEqual(bad, [], f"{chain[mod]} imports {', '.join(bad)}")
                    for nxt in sorted(imported & ours):
                        chain.setdefault(nxt, f"{chain[mod]} -> {nxt}")
                        todo.append(nxt)


# SQL in views/ (the brief's "no SQL in pages"): every view's reads and writes
# are module functions with their own tests (Step 8 Phase 3, Oct 8 - the last
# ones moved then), so no view may hold a SQL statement - the number of string
# literals holding one. Keep it empty: a view that gains SQL fails; put the
# new read or write in the module that owns its table and call that.
VIEW_SQL_ALLOWED: dict[str, int] = {}
SQL_RE = re.compile(r"\b(SELECT\b.*\bFROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|"
                    r"CREATE\s+(UNIQUE\s+)?(TABLE|INDEX)|ALTER\s+TABLE|DROP\s+(TABLE|INDEX))\b",
                    re.S)


def sql_literals(path: str) -> int:
    """How many string literals in the file hold SQL (an f-string counts as
    one, its {...} parts left out)."""
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), path)
    texts, inside = [], set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            texts.append("".join(v.value if isinstance(v, ast.Constant) else " x "
                                 for v in node.values))
            inside |= {id(v) for v in node.values}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in inside):
            texts.append(node.value)
    return sum(1 for t in texts if SQL_RE.search(t))


class ViewSqlTests(unittest.TestCase):

    def test_the_counter_finds_sql(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
            fh.write('a = c.execute("SELECT x FROM t WHERE id = ?", (1,))\n'
                     'b = f"DELETE FROM {table} WHERE id = ?"\n'
                     'n = "Select a fund from the list"\n'
                     'd = f"UPDATE users SET {col} = ?"\n')
        self.addCleanup(os.remove, fh.name)
        self.assertEqual(sql_literals(fh.name), 3)

    def test_sql_in_views_only_shrinks(self):
        folder = os.path.join(REPO, "views")
        now = {f: sql_literals(os.path.join(folder, f))
               for f in sorted(os.listdir(folder)) if f.endswith(".py")}
        for f, n in now.items():
            allowed = VIEW_SQL_ALLOWED.get(f, 0)
            with self.subTest(f):
                self.assertLessEqual(n, allowed, f"views/{f} has {n} SQL statement(s), "
                                     f"{allowed} allowed: move the new SQL into a module the "
                                     "view calls (no SQL in pages - ADR 0003)")
                self.assertGreaterEqual(n, allowed, f"views/{f} is down to {n} SQL "
                                        f"statement(s) - lower VIEW_SQL_ALLOWED to match")
        for f in VIEW_SQL_ALLOWED:
            self.assertIn(f, now, f"views/{f} is gone - take it out of VIEW_SQL_ALLOWED")


# --------------------------------------------------------------------------- #
# 1b.4: GitHub Actions pinned by commit SHA
# --------------------------------------------------------------------------- #
class WorkflowPinTests(unittest.TestCase):

    def test_every_action_is_pinned_to_a_commit_with_its_version(self):
        folder = os.path.join(REPO, ".github", "workflows")
        uses = re.compile(r"^\s*(?:-\s*)?uses:\s*(\S+)(.*)$")
        seen = 0
        for name in sorted(os.listdir(folder)):
            if not name.endswith((".yml", ".yaml")):
                continue
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                for n, line in enumerate(fh, 1):
                    m = uses.match(line)
                    if not m or m.group(1).startswith("./"):
                        continue
                    seen += 1
                    self.assertRegex(m.group(1), r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$",
                                     f"{name}:{n}: pin by full commit SHA")
                    self.assertRegex(m.group(2), r"#\s*v\d", f"{name}:{n}: say the version "
                                     "in a comment (# v4.4.0)")
        self.assertGreater(seen, 0)

    def test_dependabot_watches_pip_and_actions_weekly(self):
        with open(os.path.join(REPO, ".github", "dependabot.yml"), encoding="utf-8") as fh:
            text = fh.read()
        for eco in ("pip", "github-actions"):
            self.assertIn(f"package-ecosystem: {eco}", text)
        self.assertEqual(text.count("interval: weekly"), 2)
        self.assertEqual(text.count("groups:"), 2)


if __name__ == "__main__":
    unittest.main()
