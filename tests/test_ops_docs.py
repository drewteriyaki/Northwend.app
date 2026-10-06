"""The operations documents (PLAN 1b.1, 1b.10, 1b.11): every setting the code
reads is listed in .env.example (so a new setting can't go undocumented),
.env.example holds no values that could be secrets, the runbook has its
pages and a checklist for every gate, and ARCHITECTURE.md's pointers exist.

    python -m unittest tests.test_ops_docs        (from the repo root)
"""

import glob
import os
import re
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import flags  # noqa: E402

NAME = r"([A-Z][A-Z0-9_]*)"
# the ways the code reads a setting, each with the name as a literal
READS = [
    # settings.get / hosting._setting / mailer._setting / st.secrets.get / flags._secret
    re.compile(r"(?:settings\.get|_setting|_secret|secrets\.get|os\.environ\.get|os\.getenv)"
               r"\(\s*[\"']" + NAME + r"[\"']"),
    re.compile(r"os\.environ\[\s*[\"']" + NAME + r"[\"']\s*\]"),
    re.compile(r"secrets\[\s*[\"']" + NAME + r"[\"']\s*\]"),
    # a .env file read directly: load_env(...).get("NAME")
    re.compile(r"load_env\([^)]*\)\.get\(\s*[\"']" + NAME + r"[\"']"),
    # a setting's name kept in a constant (flags.GATES_SETTING = "NORTHWEND_GATES")
    re.compile(r"\b[A-Z_]*SETTING\s*=\s*[\"']" + NAME + r"[\"']"),
]
# settings.py reads through its own get("NAME")
SETTINGS_READ = re.compile(r"(?<![\w.])get\(\s*[\"']" + NAME + r"[\"']")


def _code_files():
    """The app's own Python: everything but the tests and the built website."""
    for path in glob.glob(os.path.join(REPO, "**", "*.py"), recursive=True):
        rel = os.path.relpath(path, REPO)
        if rel.split(os.sep)[0] in ("tests", ".claude", ".git", "venv", ".venv", "build"):
            continue
        yield rel, path


def names_read() -> dict:
    """{setting name: [files reading it]} across the code."""
    found = {}
    for rel, path in _code_files():
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        hits = {m for rx in READS for m in rx.findall(text)}
        if os.path.basename(rel) == "settings.py":
            hits |= set(SETTINGS_READ.findall(text))
        for name in hits:
            found.setdefault(name, []).append(rel)
    return found


def env_example() -> dict:
    """{name: value} for each `NAME=value` line in .env.example, commented
    out (`# NAME=`, set by the host or for tests only) or not."""
    out = {}
    with open(os.path.join(REPO, ".env.example"), encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"^(#\s*)?" + NAME + r"=(.*)$", line.strip())
            if m:
                out[m.group(2)] = (m.group(3).strip(), bool(m.group(1)))
    return out


def _read(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as fh:
        return fh.read()


class EnvExampleTests(unittest.TestCase):
    def test_the_scan_finds_settings(self):
        # if the patterns stop matching, the next test would pass on nothing
        found = names_read()
        for name in ("PORTFOLIO_DB", "NORTHWEND_ENV", "NORTHWEND_GATES", "NORTHWEND_FLAGS",
                     "NORTHWEND_AI_CEILING_USD", "ANTHROPIC_API_KEY", "RESEND_API_KEY",
                     "FINNHUB_API_KEY", "MAIL_DRY_RUN", "CLIENT_IP_HEADER", "MOVED_TO"):
            self.assertIn(name, found)

    def test_every_setting_is_in_env_example(self):
        listed = env_example()
        missing = {n: files for n, files in names_read().items() if n not in listed}
        self.assertEqual(missing, {}, "add these to .env.example, each with a one-line "
                                      "comment saying what it's for")

    def test_each_setting_has_a_comment(self):
        lines = _read(".env.example").splitlines()
        for i, line in enumerate(lines):
            if re.match(r"^(#\s*)?[A-Z][A-Z0-9_]*=", line.strip()):
                above = lines[i - 1].strip() if i else ""
                self.assertTrue(above.startswith("#") and not re.match(
                    r"^#\s*[A-Z][A-Z0-9_]*=", above), f"no comment above: {line}")

    def test_no_values_that_could_be_secrets(self):
        safe = {"MAIL_DRY_RUN": "1"}   # the only uncommented value: the safe default
        for name, (value, commented) in env_example().items():
            if commented:
                # a commented example may only be a local test database
                self.assertTrue(value == "" or value.startswith("postgresql://postgres@localhost"),
                                name)
            else:
                self.assertEqual(value, safe.get(name, ""), name)
        text = _read(".env.example")
        for prefix in ("sk-ant-", "re_", "sk_live_", "rk_live_", "npg_"):
            self.assertNotRegex(text, r"(?<![\w-])" + re.escape(prefix) + r"[A-Za-z0-9]{8,}")


class RunbookTests(unittest.TestCase):
    PAGES = ("Deploy", "Roll back", "Restore", "Rotate a key", "Sign everyone out",
             "Turn off AI or email", "Turn a feature or gate on or off", "Shut down",
             "If something goes wrong: incident and breach response", "Owner prerequisites",
             "Before turning on a gate", "Monthly budget")

    def test_every_page_is_there(self):
        heads = re.findall(r"^##+ (.+)$", _read("docs/RUNBOOK.md"), re.M)
        for page in self.PAGES:
            self.assertTrue(any(h.startswith(page) for h in heads), page)

    def test_the_incident_plan_covers_the_first_hour_and_the_notices(self):
        text = _read("docs/RUNBOOK.md")
        self.assertIn("(#if-something-goes-wrong-incident-and-breach-response)", text)  # contents
        plan = text.split("## If something goes wrong: incident and breach response", 1)[1]
        plan = plan.split("\n## ", 1)[0]
        for must in ("Sign everyone out", "ANTHROPIC_API_KEY", "RESEND_API_KEY",
                     "FINNHUB_API_KEY", "PORTFOLIO_DB", "NORTHWEND_TOTP_KEY", "MOVED_TO",
                     "Neon branch", "admin action log", "without unreasonable delay",
                     "attorney general", "check with a lawyer", "insurer", "Subject:",
                     "post-incident checklist"):
            self.assertIn(must, plan, must)
        # the Privacy Policy's promise the plan quotes is still the published one
        self.assertIn("without unreasonable delay", _read("docs/legal/privacy-policy.md"))
        self.assertIn("incident-and-breach-response", _read("docs/ARCHITECTURE.md"))

    def test_a_checklist_for_every_gate_and_none_for_l4(self):
        text = _read("docs/RUNBOOK.md")
        for gate in flags.GATES:
            self.assertRegex(text, rf"(?m)^### {gate}\b", gate)
        self.assertNotRegex(text, r"(?m)^### L4")

    def test_settings_it_names_exist(self):
        # every NAME=... the runbook tells someone to set is a real setting
        listed = env_example()
        for name in re.findall(r"`" + NAME + r"=", _read("docs/RUNBOOK.md")):
            self.assertIn(name, listed, name)


class ArchitectureTests(unittest.TestCase):
    def test_files_it_points_to_exist(self):
        text = _read("docs/ARCHITECTURE.md")
        self.assertIn("CLAUDE.md", text)   # the file map lives there, not copied here
        for rel in set(re.findall(r"`((?:[\w.-]+/)*[\w.-]+\.(?:py|md|yml|yaml|sql))`", text)):
            hits = glob.glob(os.path.join(REPO, rel)) or glob.glob(
                os.path.join(REPO, "**", rel), recursive=True)
            self.assertTrue(hits, rel)


if __name__ == "__main__":
    unittest.main()
