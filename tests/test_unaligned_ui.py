"""Node VM regression for manual browser candidate preview and confirmation."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "Node.js required for browser tests")
class ManualAlignmentBrowserTests(unittest.TestCase):
    def test_preview_confirmation_and_stale_guard(self):
        proc = subprocess.run(
            [shutil.which("node"), str(ROOT / "tests/js/test_unaligned_ui.js"),
             str(ROOT / "src/han_codebook/static/index.html")],
            text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("passed", proc.stdout)

    def test_vercel_mock_does_not_expose_acceptance(self):
        mock = (ROOT / "vercel-demo/mock_api.js").read_text(encoding="utf-8")
        self.assertIn("route==='/api/unaligned/preview'", mock)
        self.assertIn("route==='/api/unaligned/accept'", mock)
        self.assertIn("'previewAlignment','confirmAlignment'", mock)
        self.assertIn("control.disabled = true", mock)


if __name__ == "__main__":
    unittest.main()
