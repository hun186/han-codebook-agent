"""Offline verification for case replacement draft protection."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CaseTransitionGuardTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node unavailable")
    def test_guard_cancel_and_async_staleness(self):
        proc = subprocess.run(
            ["node", str(ROOT / "tests/js/test_case_transition_guard.js")],
            text=True, capture_output=True, check=False, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + "\n" + proc.stderr)


if __name__ == "__main__":
    unittest.main()
