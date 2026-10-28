"""Real Node VM tests for research GUI asynchronous case provenance and guide."""
from pathlib import Path
import shutil
import subprocess
import unittest


BASE = Path(__file__).resolve().parents[1]


class CaseProvenanceUITest(unittest.TestCase):
    def test_async_result_case_isolation_and_human_veto(self):
        if not shutil.which("node"):
            self.skipTest("Node.js not installed")
        proc = subprocess.run(
            ["node", str(BASE / "tests/js/test_case_provenance.js"),
             str(BASE / "src/han_codebook/static/index.html")],
            capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + "\n" + proc.stderr)

    def test_ciphertext_edit_preserves_reference_and_review_histories(self):
        if not shutil.which("node"):
            self.skipTest("Node.js not installed")
        proc = subprocess.run(
            ["node", str(BASE / "tests/js/test_cipher_edit_integrity.js"),
             str(BASE / "src/han_codebook/static/index.html")],
            capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + "\n" + proc.stderr)


if __name__ == "__main__":
    unittest.main()
