"""Offline regression: actual LLM transport shown before any research submission."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LLMTransportPreflightUITests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node unavailable")
    def test_transport_preflight_local_and_browser_mock(self):
        runner = ROOT / "tests/js/test_llm_transport_preflight.js"
        for target in (ROOT / "src/han_codebook/static/index.html",
                       ROOT / "vercel-demo/workbench.js"):
            with self.subTest(target=str(target)):
                proc = subprocess.run(
                    ["node", str(runner), str(target)],
                    text=True, capture_output=True, check=False, timeout=30,
                )
                self.assertEqual(proc.returncode, 0, proc.stdout + "\n" + proc.stderr)


if __name__ == "__main__":
    unittest.main()
