"""One-click synthetic smoke CLI must be offline, repeatable, and not leak plaintext."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_manual_alignment_workbench.py"


class OfflineAlignmentSmokeTests(unittest.TestCase):
    def test_script_checks_all_safety_steps_without_user_data(self):
        with TemporaryDirectory() as temp:
            report = Path(temp) / "sanitized" / "result.json"
            for run in range(2):
                cmd = [sys.executable, str(SCRIPT), "--output", str(report)]
                completed = subprocess.run(
                    cmd, cwd=temp, capture_output=True, text=True, timeout=60
                )
                self.assertEqual(completed.returncode, 0,
                                 completed.stdout + completed.stderr)
                self.assertIn("ALIGNMENT_OFFLINE_E2E_PASS 17/17",
                              completed.stdout)
                content = report.read_text(encoding="utf-8")
                payload = json.loads(content)
                self.assertEqual(payload["status"], "PASS")
                self.assertEqual(payload["checks_total"], 17)
                self.assertEqual(payload["checks_passed"], 17)
                self.assertTrue(all(row["status"] == "PASS"
                                    for row in payload["checks"]))
                self.assertNotIn("補給", content)
                self.assertNotIn("車隊", content)
                self.assertNotIn("出發", content)
                self.assertNotIn("source_case_sha256", content)
                self.assertNotIn("confirmed_segments", content)
                self.assertNotIn("192.168.", content)
                self.assertNotIn("known_pairs", content)
                self.assertIn("synthetic localhost", content)
                self.assertEqual(
                    len({row["check"] for row in payload["checks"]}), 17
                )


if __name__ == "__main__":
    unittest.main()
