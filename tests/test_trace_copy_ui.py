"""Run browser-only trace copy regression against canonical and static Mock workbench."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TraceCopyUITests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node unavailable")
    def test_trace_copy_controls_canonical_and_mock(self):
        runner = ROOT / "tests/js/test_trace_copy.js"
        for target in (ROOT / "src/han_codebook/static/index.html",
                       ROOT / "vercel-demo/workbench.js"):
            with self.subTest(target=str(target)):
                result = subprocess.run(
                    ["node", str(runner), str(target)],
                    text=True, capture_output=True, check=False, timeout=25,
                )
                self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)


if __name__ == "__main__":
    unittest.main()
