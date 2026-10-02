"""Packaging (ROADMAP Polish): pyproject.toml and the console commands in cli.py.

    python -m unittest discover -s tests        (from the repo root)
"""

import contextlib
import glob
import io
import os
import re
import sys
import tomllib
import unittest
import unittest.mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

import cli  # noqa: E402
import pgcompat  # noqa: E402

with open(os.path.join(REPO, "pyproject.toml"), "rb") as fh:
    PYPROJECT = tomllib.load(fh)


def _requirements():
    """requirements.txt's pins, without comments."""
    with open(os.path.join(REPO, "requirements.txt"), encoding="utf-8") as fh:
        lines = (re.sub(r"\s*#.*$", "", line).strip() for line in fh)
        return [line for line in lines if line]


class PackagingTests(unittest.TestCase):
    def test_dependencies_match_requirements(self):
        # Streamlit Cloud and the Tests workflow install requirements.txt;
        # an installed copy installs pyproject's list - the same pins
        self.assertEqual(sorted(PYPROJECT["project"]["dependencies"]), sorted(_requirements()))

    def test_every_module_is_listed(self):
        on_disk = sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(REPO, "*.py")))
        self.assertEqual(sorted(PYPROJECT["tool"]["setuptools"]["py-modules"]), on_disk)

    def test_commands_point_at_cli(self):
        scripts = PYPROJECT["project"]["scripts"]
        self.assertIn("northwend", scripts)
        for name, target in scripts.items():
            module, _, func = target.partition(":")
            self.assertEqual(module, "cli", name)
            self.assertTrue(callable(getattr(cli, func, None)), f"{name} -> {target}")

    def test_command_runs_main_and_closes_pools(self):
        import manage_users
        seen = []
        with unittest.mock.patch.object(manage_users, "main",
                                        lambda argv=None: seen.append(argv) or 0), \
                unittest.mock.patch.object(pgcompat, "close_all_pools") as close:
            self.assertEqual(cli.users(["list"]), 0)
        self.assertEqual(seen, [["list"]])
        close.assert_called_once()

        def boom(argv=None):
            raise RuntimeError("failed")
        with unittest.mock.patch.object(manage_users, "main", boom), \
                unittest.mock.patch.object(pgcompat, "close_all_pools") as close:
            with self.assertRaises(RuntimeError):
                cli.users([])
        close.assert_called_once()   # closed even when the command fails

    def test_help_for_each_script_command(self):
        for name in ("portfolio", "prices", "history", "users", "weekly_email"):
            out = io.StringIO()
            with self.subTest(name), contextlib.redirect_stdout(out):
                with self.assertRaises(SystemExit) as done:
                    getattr(cli, name)(["--help"])
            self.assertEqual(done.exception.code, 0, name)
            self.assertIn("usage:", out.getvalue(), name)

    def test_dashboard_runs_streamlit_on_the_app(self):
        from streamlit.web import cli as stcli
        with unittest.mock.patch.object(stcli, "main", return_value=0) as run, \
                unittest.mock.patch.object(sys, "argv", ["northwend"]):
            cli.dashboard(["--server.port", "8600"])
            self.assertEqual(sys.argv, ["streamlit", "run", os.path.join(REPO, "dashboard.py"),
                                        "--server.port", "8600"])
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
