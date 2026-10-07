"""scripts/test_shard.py and the Tests workflow that runs the suite in shares."""
import importlib.util
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "test_shard", os.path.join(REPO, "scripts", "test_shard.py"))
test_shard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(test_shard)

WORKFLOW = os.path.join(REPO, ".github", "workflows", "tests.yml")


class ShardTests(unittest.TestCase):

    def test_every_test_file_is_in_exactly_one_share(self):
        files = sorted(f[:-3] for f in os.listdir(os.path.join(REPO, "tests"))
                       if f.startswith("test_") and f.endswith(".py"))
        shares = test_shard.shares(4)
        flat = [m for s in shares for m in s]
        self.assertEqual(sorted(flat), files)
        self.assertEqual(len(flat), len(set(flat)))
        self.assertTrue(all(shares))

    def test_shares_keep_alphabetical_order_and_stay_balanced(self):
        shares = test_shard.shares(4)
        for s in shares:
            self.assertEqual(s, sorted(s))
        loads = [sum(test_shard.cost(os.path.join(test_shard.TESTS, m + ".py")) for m in s)
                 for s in shares]
        self.assertLess(max(loads), 1.5 * min(loads))

    def test_the_workflow_runs_four_shares_and_keeps_the_required_name(self):
        with open(WORKFLOW, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("shard: [1, 2, 3, 4]", src)
        self.assertIn("python scripts/test_shard.py 4 ${{ matrix.shard }}", src)
        # main's branch protection requires these job names
        self.assertIn("\n  unit-tests:\n", src)
        self.assertIn("\n  postgres-tests:\n", src)
        self.assertIn('test "${{ needs.unit-tests-shard.result }}" = "success"', src)


if __name__ == "__main__":
    unittest.main()
