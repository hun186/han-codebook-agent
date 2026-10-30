"""Regression coverage for paired, oracle-isolated metadata/observation ablations."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from han_codebook.context_ablation import (
    _fold_outcomes, _paired, compare_context, main, MODE_ORDER
)
from han_codebook.core import CaseError


def case_with_observations():
    return {
        "case_id": "paired-context-case",
        "profiles": {
            "neutral": {"keywords": [], "lexicon": {
                "兵力": 2, "車隊": 2, "集結": 2
            }, "sentences": [["兵力", "車隊"]]}
        },
        "messages": [
            {"id": "m1", "codes": ["101", "102"],
             "sender": "後勤部", "recipient": "前線", "received_at": "2026-10-20",
             "observations": [{
                 "source": "research note", "note": "未確認外部目擊",
                 "status": "未確認", "observed_at": "2026-10-21",
                 "confidence": 0.3
             }]},
            {"id": "m2", "codes": ["101", "103"],
             "sender": "後勤部", "recipient": "前線", "received_at": "2026-10-21",
             "observations": [{
                 "source": "another sighting", "note": "非確定相關",
                 "status": "不相關", "confidence": 0.5
             }]},
        ],
        "known_pairs": [
            {"message_id": "m1", "segments": ["兵力", "車隊"]},
            {"message_id": "m2", "segments": ["兵力", "集結"]},
        ],
    }


def fake_report(outcomes, *, status="scored"):
    return {
        "available_fold_count": 1, "evaluated_fold_count": 1,
        "summary": {
            "independently_testable_fold_code_assessments": len(outcomes),
            "scored_fold_code_assessments": len(outcomes),
            "not_scored_due_to_candidate_exclusions": 0,
            "top1_hits": outcomes.count("correct_top1"),
            "top5_hits": sum(o in ("correct_top1", "top5_only_ranking_error")
                             for o in outcomes),
            "top1_rate": outcomes.count("correct_top1") / len(outcomes)
                         if outcomes else None,
            "top5_rate": sum(o in ("correct_top1", "top5_only_ranking_error")
                             for o in outcomes) / len(outcomes)
                         if outcomes else None,
            "overlapping_anchored_codes_excluded": 0,
        },
        "folds": [{
            "heldout_message_id": "m1",
            "status": status,
            "outcomes_without_plaintext": [
                {"code": f"{i:03}", "outcome": label}
                for i, label in enumerate(outcomes)
            ],
        }],
    }


class ContextAblationTests(unittest.TestCase):
    def test_real_offline_holdout_preserves_case_and_never_exposes_phrase(self):
        case = case_with_observations()
        before = deepcopy(case)
        with patch("han_codebook.agent.query_local_llm",
                   side_effect=AssertionError("no real model calls")):
            result = compare_context(
                case, max_folds=2, iterations=1, restarts=1,
                minimum_paired=5
            )
        self.assertEqual(case, before)
        self.assertEqual(tuple(result["modes"]), MODE_ORDER)
        self.assertEqual(result["policy_selection"], "none; diagnostic only")
        self.assertEqual(result["modes"]["legacy_context"]["evaluated_fold_count"], 2)
        self.assertEqual(result["modes"]["legacy_context"]["potential_fold_code_assessments"], 2)
        self.assertEqual(result["modes"]["legacy_context"]["overlapping_anchors_not_counted"], 2)
        for mode in MODE_ORDER[1:]:
            diff = result["paired_vs_legacy"][mode]
            self.assertEqual(diff["signal"], "insufficient_paired_evidence")
            self.assertEqual(diff["paired_inferred_fold_codes"], 2)
        serialized = json.dumps(result, ensure_ascii=False)
        for secret in ("兵力", "車隊", "集結", "未確認外部目擊", "後勤部"):
            self.assertNotIn(secret, serialized)
        self.assertNotIn("known_pairs", result)

    def test_mode_inputs_preserve_known_pairs_but_strip_correct_evidence(self):
        case = case_with_observations()
        captured = []

        def stub(payload, **kwargs):
            captured.append((deepcopy(payload), kwargs))
            return fake_report(["correct_top1"])
        with patch("han_codebook.context_ablation.verify_known_pairs",
                   side_effect=stub):
            compare_context(case, max_folds=1, iterations=1, restarts=1)

        self.assertEqual(len(captured), 4)
        legacy, no_obs, time, no_metadata = captured
        self.assertTrue(all(x[0]["known_pairs"] == case["known_pairs"]
                            for x in captured),
                        "fold implementation, not ablation, withholds plaintext")
        self.assertEqual(legacy[0]["observation_policy"], "legacy")
        self.assertIn("observations", legacy[0]["messages"][0])
        self.assertEqual(no_obs[0]["observation_policy"], "legacy")
        self.assertNotIn("observations", no_obs[0]["messages"][0])
        self.assertEqual(time[0]["observation_policy"], "time_relevance")
        self.assertIn("observations", time[0]["messages"][0])
        self.assertFalse(no_metadata[1]["use_metadata"])
        self.assertTrue(all(x[1]["use_metadata"] for x in captured[:3]))
        for key in ("sender", "recipient", "received_at", "notes", "unit",
                    "domain", "observations"):
            self.assertNotIn(key, no_metadata[0]["messages"][0])
        self.assertEqual(case["messages"][0]["sender"], "後勤部")

    def test_paired_comparison_flags_direction_but_not_auto_selection(self):
        miss = "candidate_ranked_below_top5"
        legacy = ["correct_top1"] * 3 + [miss] * 7
        variant = ["correct_top1", miss, miss, "correct_top1",
                   "correct_top1", "correct_top1"] + [miss] * 4
        reports = [fake_report(legacy), fake_report(variant),
                   fake_report(legacy), fake_report(variant)]
        with patch("han_codebook.context_ablation.verify_known_pairs",
                   side_effect=reports):
            r = compare_context(case_with_observations(), minimum_paired=10)
        diff = r["paired_vs_legacy"]["without_observations"]
        self.assertEqual(diff["paired_inferred_fold_codes"], 10)
        self.assertEqual(diff["legacy_only_top1_hits"], 2)
        self.assertEqual(diff["variant_only_top1_hits"], 3)
        self.assertEqual(diff["both_top1_hits"], 1)
        self.assertEqual(diff["neither_top1_hits"], 4)
        self.assertEqual(diff["top1_rate_delta_variant_minus_legacy"], 0.1)
        self.assertEqual(diff["signal"], "possible_context_harm")
        self.assertEqual(r["paired_vs_legacy"]["time_relevance"]["signal"],
                         "no_directional_difference")
        self.assertEqual(r["policy_selection"], "none; diagnostic only")

    def test_only_matching_actually_inferred_codes_enter_paired_deltas(self):
        baseline = fake_report(["correct_top1", "candidate_ranked_below_top5"])
        variant = fake_report(["candidate_ranked_below_top5", "correct_top1"],
                              status="candidate_exclusions_blocked_inference")
        reports = [baseline, variant, variant, variant]
        with patch("han_codebook.context_ablation.verify_known_pairs",
                   side_effect=reports):
            result = compare_context(case_with_observations(),
                                     minimum_paired=1)
        self.assertIsNone(result["paired_vs_legacy"]["without_observations"]
                          ["top1_rate_delta_variant_minus_legacy"])
        self.assertEqual(result["paired_vs_legacy"]["without_observations"]
                         ["paired_inferred_fold_codes"], 0)
        self.assertEqual(result["paired_vs_legacy"]["without_observations"]
                         ["signal"], "insufficient_paired_evidence")

    def test_mismatched_fold_code_inventory_fails_closed(self):
        first = fake_report(["correct_top1"])
        second = fake_report(["correct_top1", "correct_top1"])
        with patch("han_codebook.context_ablation.verify_known_pairs",
                   side_effect=[first, second]):
            with self.assertRaisesRegex(CaseError, "fold/code identities"):
                compare_context(case_with_observations())
        duplicated = fake_report(["correct_top1", "correct_top1"])
        duplicated["folds"][0]["outcomes_without_plaintext"][1]["code"] = "000"
        with self.assertRaisesRegex(CaseError, "duplicate fold/code"):
            _fold_outcomes(duplicated)

    def test_paired_summary_excludes_noncommon_records(self):
        base = {("a", "001"): "correct_top1",
                ("a", "002"): "correct_top1"}
        variant = {("a", "001"): "candidate_ranked_below_top5",
                   ("b", "003"): "correct_top1"}
        output = _paired(base, variant, minimum_paired=1)
        self.assertEqual(output["paired_inferred_fold_codes"], 1)
        self.assertEqual(output["legacy_only_top1_hits"], 1)
        self.assertEqual(output["variant_only_top1_hits"], 0)
        self.assertEqual(output["signal"], "possible_context_benefit")

    def test_input_validation_refuses_oracle_and_invalid_threshold(self):
        case = case_with_observations()
        for oracle in ("gold", "ground_truth", "codebook"):
            invalid = deepcopy(case)
            invalid[oracle] = {"101": "secret"}
            with self.assertRaisesRegex(CaseError, "oracle"):
                compare_context(invalid, iterations=1, restarts=1)
        for threshold in (0, -1, True, 10001, "10", 2.5):
            with self.assertRaises(CaseError):
                compare_context(case, minimum_paired=threshold)

    def test_cli_produces_safe_json_without_model_or_gold(self):
        case = case_with_observations()
        with TemporaryDirectory() as directory:
            inp = Path(directory) / "case.json"
            out = Path(directory) / "ablation.json"
            inp.write_text(json.dumps(case, ensure_ascii=False),
                           encoding="utf-8")
            self.assertEqual(main(["--case", str(inp), "--out", str(out),
                                   "--max-folds", "2", "--iterations", "1",
                                   "--restarts", "1"]), 0)
            result = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(tuple(result["modes"]), MODE_ORDER)
            self.assertNotIn("兵力", out.read_text(encoding="utf-8"))
            out.unlink()
            case["ground_truth"] = {"101": "兵力"}
            inp.write_text(json.dumps(case, ensure_ascii=False),
                           encoding="utf-8")
            self.assertEqual(main(["--case", str(inp), "--out", str(out)]), 2)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
