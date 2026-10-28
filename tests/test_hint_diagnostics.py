"""Guardrails for evidence-sensitive decoding and offline oracle separation."""
import json
from pathlib import Path
import unittest

from han_codebook.core import CaseError, analyze, domain_for_message
from han_codebook.hint_diagnostics import compare, evaluate_after_inference, hints_from_reply


ROOT = Path(__file__).resolve().parents[1] / "benchmarks" / "volume"


class HintDiagnosticsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = json.loads((ROOT / "seed_202_case.json").read_text(encoding="utf-8"))
        cls.case["messages"] = cls.case["messages"][:10]
        # A synthetic, deliberately fallible recorded response: no network calls.
        codes = sorted({c for m in cls.case["messages"] for c in m["codes"]})
        vocab = list(cls.case["profiles"]["logistics"]["lexicon"])
        cls.reply = {"hypotheses": [
            {"code": code, "candidates": [vocab[i % len(vocab)]]}
            for i, code in enumerate(codes[:15])]}

    def test_scale_zero_matches_baseline_and_one_is_default(self):
        hints, _ = hints_from_reply(self.case, self.reply)
        original = analyze(self.case, iterations=2, restarts=2)
        disabled = analyze(self.case, llm_hints=hints, hint_scale=0,
                           iterations=2, restarts=2)
        normal = analyze(self.case, llm_hints=hints, iterations=2, restarts=2)
        explicit = analyze(self.case, llm_hints=hints, hint_scale=1,
                           iterations=2, restarts=2)
        self.assertEqual(original["proposals"], disabled["proposals"])
        self.assertEqual(normal["proposals"], explicit["proposals"])

    def test_reject_invalid_hint_strength(self):
        for value in (-1, 5, True, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(CaseError):
                analyze(self.case, hint_scale=value, iterations=1, restarts=1)

    def test_observation_disagreement_is_discounted(self):
        profiles = {"ops": {"keywords": ["車隊"]}, "log": {"keywords": ["人員"]}}
        msg = {"id": "m", "codes": ["123"], "received_at": "1942-05-03T16:00:00",
               "observations": [{"source": "witness", "activity": "看到車隊",
                                 "confidence": 1.0, "observed_at": "1942-05-03",
                                 "status": "已排除關聯"}]}
        self.assertEqual(domain_for_message(msg, profiles, True, "legacy"), "ops")
        self.assertIsNone(domain_for_message(msg, profiles, True, "time_relevance"))
        msg["observations"][0]["status"] = "未確認關聯"
        msg["observations"][0]["observed_at"] = "1942-01-01T00:00:00"
        self.assertIsNone(domain_for_message(msg, profiles, True, "time_relevance"))

    def test_evaluation_gold_only_after_inference(self):
        report = compare(self.case, self.reply, observation_ablation=False)
        self.assertNotIn("synthetic_top1_correct", report["runs"][0])
        gold = json.loads((ROOT / "seed_202_gold.json").read_text(encoding="utf-8"))
        graded = evaluate_after_inference(report, gold)
        self.assertIn("synthetic_top1_correct", graded["runs"][0])
        self.assertNotIn("synthetic_top1_correct", report["runs"][0])
        with self.assertRaises(CaseError):
            compare({**self.case, "ground_truth": {}}, self.reply, observation_ablation=False)

    def test_duplicate_code_proposals_ignored(self):
        proposal = self.reply["hypotheses"][0]
        response = {"hypotheses": [proposal, proposal]}
        hints, accepted = hints_from_reply(self.case, response)
        self.assertEqual(len(hints), 1)
        self.assertEqual(len(accepted), 1)


if __name__ == "__main__":
    unittest.main()
