"""Node browser-model regression for researcher known plaintext pair CRUD."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("node"), "Node.js required for researcher UI VM tests")
class ResearcherKnownPairEditorTests(unittest.TestCase):
    def test_row_editor_validates_unaligned_and_independently_checked_pairs(self):
        cmd = [shutil.which("node"),
               str(ROOT / "tests/js/test_known_pairs_ui.js"),
               str(ROOT / "src/han_codebook/static/index.html")]
        finished = subprocess.run(cmd, text=True, capture_output=True, timeout=20)
        self.assertEqual(finished.returncode, 0, finished.stdout + finished.stderr)
        self.assertIn("regression passed", finished.stdout)

    def test_demo_interface_uses_synced_readonly_backend(self):
        demo = (ROOT / "vercel-demo/index.html").read_text(encoding="utf-8")
        js = (ROOT / "vercel-demo/workbench.js").read_text(encoding="utf-8")
        self.assertIn('id="knownAdd"', demo)
        self.assertIn('id="knownRowEditor"', demo)
        self.assertIn("function trustedFromPairs(pairs)", js)
        # Public MOCK never exposes actual backend acceptance.
        mock = (ROOT / "vercel-demo/mock_api.js").read_text(encoding="utf-8")
        self.assertIn("route==='/api/unaligned/accept'", mock)


if __name__ == "__main__":
    unittest.main()
