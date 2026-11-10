"""Run third-party observation editor tests against canonical and mock UIs."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ObservationEditorTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node unavailable")
    def test_observation_note_edit_and_draft_protection(self):
        script = ROOT / "tests/js/test_observation_row_edit.js"
        for target in (ROOT / "src/han_codebook/static/index.html",
                       ROOT / "vercel-demo/workbench.js"):
            with self.subTest(target=str(target)):
                result = subprocess.run(
                    ["node", str(script), str(target)], text=True,
                    capture_output=True, check=False, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)


if __name__ == "__main__":
    unittest.main()
