"""Node-driven browser handler regression without adding frontend dependencies."""
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

class BrowserHypothesisRegression(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js unavailable')
    def test_atomic_crib_and_bounded_reversible_history(self):
        subprocess.run(['node',str(ROOT/'tests/js/test_marks_review.js'),str(ROOT/'src/han_codebook/static/index.html')],
                       check=True,timeout=30,capture_output=True,text=True)
