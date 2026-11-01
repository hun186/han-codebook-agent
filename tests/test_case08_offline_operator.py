"""Real offline case08 study: no model/HTTP, oracle AFTER predictions, fresh output."""
from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import sys
import unittest
from unittest.mock import patch
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_case08_offline_ablation.py"


class OfflineCase08StudyTests(unittest.TestCase):
    def test_two_zero_llm_runs_and_gold_never_enters_solver(self):
        from importlib.util import spec_from_file_location, module_from_spec
        spec = spec_from_file_location("offline08_test", SCRIPT)
        module = module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        real_load = module.load_case
        oracle_path = module.GOLD
        scores_called = []
        touched_gold = False
        def guard_case(path):
            self.assertNotEqual(Path(path).resolve(),oracle_path.resolve())
            return real_load(path)
        original_score = module.score_result
        def score_after_both(result, gold, case):
            # The second metadata-off run must be complete before oracle scoring.
            self.assertTrue((root / "metadata_on" / "result.json").exists())
            self.assertTrue((root / "metadata_off" / "result.json").exists())
            scores_called.append(1)
            return original_score(result, gold, case)
        def never_llm(*args, **kwargs):
            self.fail("An OFFLINE experiment called an LLM")
        with TemporaryDirectory() as tmp:
            parent = Path(tmp)
            original = module.secrets.token_hex
            def stable_secret(size):
                return original(size)
            # Defensive guard, even if future refactoring mistakenly requests
            # the network when rounds=0.
            with patch.object(module,"load_case",side_effect=guard_case), \
                 patch.object(module,"score_result",side_effect=score_after_both), \
                 patch("han_codebook.agent.query_local_llm",side_effect=never_llm):
                # Work directory exists only after study starts. Update the
                # reference from the newly created output inside score hook.
                def score_hook(result,gold,case):
                    nonlocal root
                    dirs=[p for p in parent.iterdir() if p.is_dir()]
                    self.assertEqual(len(dirs),1)
                    root=dirs[0]
                    return score_after_both(result,gold,case)
                module.score_result=score_hook
                root=parent / "not-created-yet"
                target=module.study(output_root=parent)
            self.assertEqual(target,root)
            self.assertEqual(len(scores_called),2)
            summary=json.loads((target/"comparison.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["llm_calls"],0)
            self.assertEqual(summary["case_id"],"08_long_dispatch_with_observations")
            self.assertEqual(set(summary["variants"]),{"metadata_on","metadata_off"})
            self.assertEqual(summary["variants"]["metadata_on"]["llm_rounds"],0)
            self.assertEqual(summary["variants"]["metadata_off"]["llm_rounds"],0)
            self.assertIn("changed_code_count",summary)
            self.assertNotIn("codebook", json.dumps(summary))
            self.assertNotIn("ground_truth", json.dumps(summary))
            for tag in ("metadata_on","metadata_off"):
                p=target/tag
                self.assertTrue((p/"audit.sqlite").exists())
                self.assertTrue((p/"report.md").exists())
                with ZipFile(p/"diagnostics_safe.zip") as z:
                    self.assertEqual(set(z.namelist()),{
                        "round_trace.jsonl","diagnostics.json","evaluation.json",
                        "run_manifest.json"})
                    self.assertEqual(json.loads(z.read("run_manifest.json"))["settings"]["rounds_requested"],0)
                with ZipFile(p/"diagnostics_private.zip") as z:
                    self.assertIn("audit.sqlite",z.namelist())
                    self.assertIn("input_case.json",z.namelist())
                    self.assertNotIn("gold.json",z.namelist())
                    self.assertEqual(json.loads(z.read("evaluation.json"))["status"],"not_performed")
            # An independent second invocation creates a NEW run instead of
            # overwriting the first. No prior files are lost.
            first=(target/"comparison.json").read_bytes()
            with patch("han_codebook.agent.query_local_llm",side_effect=never_llm):
                another=module.study(output_root=parent)
            self.assertNotEqual(another,target)
            self.assertEqual(first,(target/"comparison.json").read_bytes())

    def test_windows_linux_operator_and_no_llm_flags(self):
        bat=(ROOT/"check_case08_offline_ablation_windows.bat").read_text(encoding="utf-8")
        sh=(ROOT/"check_case08_offline_ablation.sh").read_text(encoding="utf-8")
        self.assertIn("check_case08_offline_ablation.py",bat)
        self.assertIn("check_case08_offline_ablation.py",sh)
        self.assertIn("PYTHONPATH",bat)
        self.assertIn("PYTHONPATH",sh)
        self.assertNotIn("--rounds 3",bat+sh)
        self.assertNotIn("check-llm",bat+sh)


if __name__=="__main__":
    unittest.main()
