"""Security regressions for stale/tampered blind reports and model-specific API fees.

All model replies here are local TEST DOUBLES, never commercial inference.
A synthetic lock is changed to the real-provider marker solely to exercise
the fail-closed report code; no Word document or real-model success is emitted.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks" / "blind_commercial"))
sys.path.insert(0, str(ROOT / "src"))

from generate import generate
from run import run_experiment, estimated_standard_usd
from score import score, verify_published_evaluation
from make_report import build


class ModelSpecificPricingTests(unittest.TestCase):
    def test_standard_rates_are_per_model_and_include_cached_tokens(self):
        usage = {"prompt_tokens": 100000, "cached_input_tokens": 10000,
                 "completion_tokens": 20000, "reasoning_tokens": 3000}
        self.assertAlmostEqual(estimated_standard_usd(usage, "gpt-6-astra"), 1.91)
        self.assertAlmostEqual(estimated_standard_usd(usage, "gpt-6-sol"), .382)
        self.assertAlmostEqual(estimated_standard_usd(usage, "gpt-6-luna"), .0191)
        self.assertAlmostEqual(estimated_standard_usd(usage), 1.91)

    def test_long_context_prices_and_invalid_fail_closed(self):
        long = {"prompt_tokens": 272001, "cached_input_tokens": 100000,
                "completion_tokens": 100000, "reasoning_tokens": 50000}
        for model, rates in (("gpt-6-astra", (10., 1., 50.)),
                             ("gpt-6-sol", (2., .2, 10.)),
                             ("gpt-6-luna", (.1, .01, .5))):
            input_rate, cached_rate, output_rate = rates
            expected = ((172001 * input_rate + 100000 * cached_rate) * 2
                        + 100000 * output_rate * 1.5) / 1000000
            self.assertAlmostEqual(estimated_standard_usd(long, model), expected)
        with self.assertRaisesRegex(ValueError, "Unknown API token rates"):
            estimated_standard_usd({}, "invented-model")
        with self.assertRaisesRegex(RuntimeError, "Invalid historical API usage"):
            estimated_standard_usd({"prompt_tokens": 1, "cached_input_tokens": 2}, "gpt-6-luna")


class UntrustedEvaluationReportTests(unittest.TestCase):
    def test_score_recomputed_and_word_refuses_modified_metrics_and_rounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            public, private, output = base / "public", base / "secret", base / "results"
            generate(public, private, repeats=1, fixture_seed=66341)

            def mock_reply(chat):
                packet = json.loads(chat["messages"][1]["content"])
                if packet.get("task") == "generate_vocabulary":
                    payload = {"vocabulary": [{"term": "交通", "reason": "TEST DOUBLE"}],
                               "patterns": []}
                else:
                    payload = {"hypotheses": []}
                return {
                    "choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}],
                    "model": "TEST_DOUBLE",
                    "usage": {"prompt_tokens": 10, "cached_input_tokens": 0,
                              "completion_tokens": 10, "reasoning_tokens": 0},
                }

            locked = run_experiment(public, output, model="gpt-6-astra",
                                    effort="high", rounds=1, max_calls=16,
                                    timeout=30, provider=mock_reply, real_api=False,
                                    solver_iterations=1, solver_restarts=1)
            self.assertEqual(locked["kind"], "TEST_DOUBLE_SMOKE_NOT_SCORED")

            # A local test-only marker: ensure Word's genuine-scoring guard
            # actually recomputes instead of trusting a compatible-looking JSON.
            synthetic = copy.deepcopy(locked)
            synthetic["kind"] = "ACTUAL_MULTI_ROUND_BLIND_EVALUATION"
            synthetic["provider"] = "CODEX_CLI_CHATGPT_PLAN"
            synthetic["includes_hidden_reference"] = False
            frozen = output / "predictions_LOCKED.json"
            frozen.write_text(json.dumps(synthetic, ensure_ascii=False), encoding="utf-8")
            sha = hashlib.sha256(frozen.read_bytes()).hexdigest()
            (output / "predictions_LOCKED.sha256").write_text(sha + "\n", encoding="ascii")

            evaluation = score(private, public, output)
            verify_published_evaluation(synthetic, evaluation, public, private, output)
            self.assertEqual(evaluation["total_runs"], 8)
            self.assertTrue(evaluation["round_trajectories"])
            original = copy.deepcopy(evaluation)
            destination = base / "MUST_NOT_CREATE.docx"

            for kind in ("results", "round_trajectories"):
                corrupted = copy.deepcopy(original)
                entry = corrupted[kind][0]
                entry["correct_types"] = entry["code_types"]
                # Even if test model happened to have 100% top1, change the
                # only trustable denominator too; this must be caught.
                entry["code_types"] += 1
                (output / "evaluation.json").write_text(
                    json.dumps(corrupted, ensure_ascii=False), encoding="utf-8")
                with self.subTest(kind=kind):
                    with self.assertRaisesRegex(ValueError, "evaluation scores/round trajectories"):
                        build("blind_01", public, private, output, destination)
                    self.assertFalse(destination.exists())

            (output / "evaluation.json").write_text(
                json.dumps(original, ensure_ascii=False), encoding="utf-8")
            (output / "predictions_LOCKED.sha256").write_text("0" * 64, encoding="ascii")
            with self.assertRaisesRegex(ValueError, "lock fingerprint mismatch"):
                build("blind_01", public, private, output, destination)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
