"""Real Docker gold isolation plus non-root private bind-mount probe.

Uses a 0700 scratch directory, 0600 OAuth/schema files, and a 0600 gold
sentinel. No real CLI login or paid model requests.
"""
import json
import os
import shlex
import stat
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
                         "Docker gold boundary is exercised in separate Hosted CI job")
    def test_private_gold_host_file_is_unreadable_from_container(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td).resolve()
            gold=base/"protected_gold"/"private_truth.json"
            gold.parent.mkdir()
            gold.write_text('{"secret":"NEVER_A_MODEL_INPUT"}',encoding="utf-8")
            gold.chmod(0o600)
            home=base/"auth"
            home.mkdir()
            auth=home/"auth.json"
            auth.write_text('{"test_only":true}',encoding="utf-8")
            auth.chmod(0o600)
            scratch=base/"isolated_scratch"
            scratch.mkdir()
            (scratch/"visible.txt").write_text("ALLOWED",encoding="ascii")
            (scratch/"visible.txt").chmod(0o600)
            (scratch/"response_schema.json").write_text('{"type":"object"}',encoding="ascii")
            (scratch/"response_schema.json").chmod(0o600)
            scratch.chmod(0o700)
            if hasattr(os,"geteuid"):
                self.assertNotEqual(os.geteuid(),0,
                                    "Hosted gold-boundary probe requires non-root host user")
            # Actual container process must READ 0600 auth/schema, WRITE the
            # last reply as the host UID, but CANNOT read unmounted private gold.
            script=(
                'test "$(cat /work/visible.txt)" = ALLOWED && '
                'test -r /etc/han-codebook-auth.json && '
                'test -r /work/response_schema.json && '
                'cat /etc/han-codebook-auth.json >/dev/null && '
                'printf "%s" "{\"accepted\":true}" > /work/last_response.json && '
                'if cat '+shlex.quote(str(gold))+' >/dev/null 2>&1; then '
                'echo GOLD_WAS_READ; exit 67; fi; '
                'printf BOUNDARY_BLOCKED'
            )
            with patch.dict(os.environ,{"OPENAI_API_KEY":"",
                                     "CODEX_API_KEY":"",
                                     "CODEX_ACCESS_TOKEN":""}):
                result=isolated_codex_run(["/bin/sh","-c",script],home=home,
                                          scratch=scratch,image="alpine:3.20",
                                          timeout=75)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn("BOUNDARY_BLOCKED",result.stdout)
            self.assertNotIn("NEVER_A_MODEL_INPUT",result.stdout)
            reply=scratch/"last_response.json"
            self.assertEqual(json.loads(reply.read_text(encoding="utf-8")),
                             {"accepted":True})
            if hasattr(os,"getuid"):
                self.assertEqual(reply.stat().st_uid,os.getuid())
            self.assertTrue(reply.stat().st_mode & stat.S_IRUSR)


if __name__=="__main__":
    unittest.main()
