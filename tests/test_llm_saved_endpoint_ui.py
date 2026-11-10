"""Regression: the web UI must never silently test a stale unsaved Ollama URL."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class LLMStoredEndpointUITests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node unavailable")
    def test_saved_endpoint_and_actual_tcp_port(self):
        script = ROOT / "tests/js/test_llm_saved_endpoint.js"
        for target in (ROOT / "src/han_codebook/static/index.html",
                       ROOT / "vercel-demo/workbench.js"):
            with self.subTest(target=str(target)):
                proc = subprocess.run(
                    ["node", str(script), str(target)], text=True,
                    capture_output=True, check=False, timeout=30,
                )
                self.assertEqual(proc.returncode, 0, proc.stdout + "\n" + proc.stderr)


if __name__ == "__main__":
    unittest.main()
