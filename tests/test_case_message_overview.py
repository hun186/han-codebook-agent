"""Test the 100/1000-message dashboard without contacting LLM providers."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CaseOverviewSmoke(unittest.TestCase):
    def test_overview_layout_and_no_oracle(self):
        html=(ROOT/'src/han_codebook/static/index.html').read_text(encoding='utf-8')
        demo=(ROOT/'vercel-demo/index.html').read_text(encoding='utf-8')
        for page in (html,demo):
            self.assertIn('id="caseOverviewBody"',page)
            self.assertIn('id="caseOverviewFilter"',page)
            self.assertIn('id="caseOverviewSearch"',page)
            self.assertIn('id="caseOverviewPageSize"',page)
            self.assertIn('id="caseOverviewKpis"',page)
            self.assertIn('data-overview-expand', (ROOT/'vercel-demo/workbench.js').read_text(encoding='utf-8'))
            self.assertNotIn('gold.json',page)

    @unittest.skipUnless(shutil.which('node'), 'Node unavailable')
    def test_100_and_1000_messages(self):
        proc=subprocess.run(
            ['node',str(ROOT/'tests/js/test_case_message_overview.js')],
            text=True,capture_output=True,check=False,timeout=30)
        self.assertEqual(proc.returncode,0,proc.stdout+'\n'+proc.stderr)


if __name__=='__main__':
    unittest.main()
