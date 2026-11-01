"""One-click synthetic smoke CLI must be offline, repeatable, and not leak plaintext."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_manual_alignment_workbench.py"


class OfflineAlignmentSmokeTests(unittest.TestCase):
    def test_script_checks_all_safety_steps_without_user_data(self):
        with TemporaryDirectory() as temp:
            report = Path(temp) / "sanitized" / "result.json"
            for run in range(2):
                cmd = [sys.executable, str(SCRIPT), "--output", str(report)]
                # The second run emulates a workstation with an incorrect
                # HTTP(S) proxy and explicitly NO proxy-bypass environment.
                env = os.environ.copy()
                if run:
                    env.update({
                        "http_proxy": "http://127.0.0.1:1",
                        "https_proxy": "http://127.0.0.1:1",
                        "HTTP_PROXY": "http://127.0.0.1:1",
                        "HTTPS_PROXY": "http://127.0.0.1:1",
                        "no_proxy": "", "NO_PROXY": "",
                    })
                completed = subprocess.run(
                    cmd, cwd=temp, env=env, capture_output=True, text=True,
                    timeout=60
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


    def test_exception_replaces_earlier_pass_report_with_redacted_fail(self):
        with TemporaryDirectory() as temp:
            out = Path(temp) / "diagnostics/result.json"
            out.parent.mkdir(parents=True)
            out.write_text('{"status":"PASS","checks_passed":17}', encoding="utf-8")
            spec = importlib.util.spec_from_file_location("alignment_smoke_local", SCRIPT)
            self.assertIsNotNone(spec)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with patch.object(
                module, "run_checks",
                side_effect=OSError("synthetic sensitive phrase 補給 should not log")
            ):
                rc = module.main(["--output", str(out)])
            self.assertEqual(rc, 2)
            record = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "FAIL")
            self.assertEqual(record["error_type"], "OSError")
            self.assertEqual(record["checks_passed"], 0)
            self.assertEqual(record["checks_total"], 17)
            self.assertNotIn("補給", out.read_text(encoding="utf-8"))

    def test_no_earlier_pass_is_left_after_unwritable_output(self):
        with TemporaryDirectory() as temp:
            report = Path(temp) / "old-success.json"
            report.write_text('{"status":"PASS"}', encoding="utf-8")
            # Failed/early termination during checks cannot preserve a
            # previously persisted PASS even if new report creation fails.
            spec = importlib.util.spec_from_file_location("alignment_smoke_guard", SCRIPT)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with patch.object(module, "run_checks", side_effect=RuntimeError("boom")), \
                 patch.object(module.os, "replace", side_effect=OSError("disk full")):
                rc = module.main(["--output", str(report)])
            self.assertEqual(rc, 2)
            self.assertFalse(report.exists(), "must invalidate obsolete PASS")


if __name__ == "__main__":
    unittest.main()
