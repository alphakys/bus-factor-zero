"""Exercise the operator-facing handoff and its rejection states."""

import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


class HandoffTest(unittest.TestCase):
    def setUp(self):
        scratch = TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.directory = Path(scratch.name) / "incident"
        prepared = self.run_cli("prepare")
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        self.plan = json.loads(prepared.stdout)

    def run_cli(self, command, *args):
        script = Path(__file__).with_name("handoff.py")
        return subprocess.run(
            [sys.executable, str(script), command, str(self.directory), *args],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_blocks_until_the_plan_is_approved_and_allows_retry(self):
        missing = self.run_cli("recover")
        self.assertEqual(missing.returncode, 2)
        rejected = self.run_cli("recover", "--approve", "unapproved")
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("approval does not match", rejected.stderr)
        self.assertEqual(self.plan["plan"]["before"]["reservations"], 2)

        for _ in range(2):
            recovery = self.run_cli("recover", "--approve", self.plan["sha256"])
            self.assertEqual(recovery.returncode, 0, recovery.stderr)
            result = json.loads(recovery.stdout)
            self.assertEqual(result["state"], "recovered")
            self.assertEqual(result["committed"]["order_ids"], ["order-a"])
            self.assertEqual(result["committed"]["stock"], 0)
            self.assertTrue(result["redelivery_unchanged"])

    def test_blocks_when_database_changes_after_review(self):
        with sqlite3.connect(self.directory / "orders.sqlite") as db:
            db.execute("UPDATE inventory SET stock = 1")
        rejected = self.run_cli("recover", "--approve", self.plan["sha256"])
        self.assertEqual(rejected.returncode, 1)
        self.assertIn("inventory changed since review", rejected.stderr)
        with sqlite3.connect(self.directory / "orders.sqlite") as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM reservations").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
