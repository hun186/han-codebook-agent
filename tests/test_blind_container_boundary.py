"""Real Docker OS-boundary probe. No actual ChatGPT login or model call.

CI sets HAN_RUN_DOCKER_BOUNDARY_TEST=1 and pulls alpine:3.20.
A host gold sentinel is present and readable to the test process, but the
isolated container must be able to see only /work and an auth.json file.
"""
import json
import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"benchmarks"/"blind_commercial"))
from codex_subscription import isolated_codex_run

class DockerBoundaryTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("HAN_RUN_DOCKER_BOUNDARY_TEST")=="1",
                         "Real Docker boundary probe is an explicit hosted CI job")
    def test_private_gold_host_file_is_unreadable_from_container(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td).resolve()
            gold=base/"protected_gold"/"private_truth.json"
            gold.parent.mkdir()
            gold.write_text(json.dumps({"secret":"NEVER_A_MODEL_INPUT"}),encoding="utf-8")
            self.assertTrue(gold.is_file())
            home=base/"auth"
            home.mkdir()
            (home/"auth.json").write_text('{"test_only":true}',encoding="utf-8")
            scratch=base/"isolated_scratch"
            scratch.mkdir()
            (scratch/"visible.txt").write_text("ALLOWED",encoding="ascii")
            # Prove actual host access is denied even to a root command inside
            # the isolated container, not just rejected after JSONL validation.
            script=("test \"$(cat /work/visible.txt)\" = ALLOWED && "
                    "if cat "+shlex.quote(str(gold))+" >/dev/null 2>&1; then "
                    "echo GOLD_WAS_READ; exit 67; fi; "
                    "printf BOUNDARY_BLOCKED")
            with patch.dict(os.environ,{"OPENAI_API_KEY":"",
                                     "CODEX_API_KEY":"",
                                     "CODEX_ACCESS_TOKEN":""}):
                result=isolated_codex_run(
                    ["/bin/sh","-c",script],home=home,scratch=scratch,
                    image="alpine:3.20",timeout=75)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn("BOUNDARY_BLOCKED",result.stdout)
            self.assertNotIn("NEVER_A_MODEL_INPUT",result.stdout)

if __name__=="__main__":
    unittest.main()
