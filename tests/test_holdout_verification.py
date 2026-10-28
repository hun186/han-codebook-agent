"""Regressions for independent, post-inference-only known-pair hold-out."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from han_codebook.core import CaseError, analyze, load_case
from han_codebook.holdout_verification import (
    _fold_input, main, verify_known_pairs
)

ROOT = Path(__file__).resolve().parents[1]


def small_case():
    return {
        "case_id": "synthetic-holdout",
        "profiles": {"neutral": {
            "keywords": [], "lexicon": {"兵力": 2, "車隊": 2, "集結": 2},
            "sentences": [["兵力", "車隊"]]}},
        "messages": [
            {"id": "m1", "codes": ["101", "102"]},
            {"id": "m2", "codes": ["101", "103"]},
        ],
        "known_pairs": [
            {"message_id": "m1", "segments": ["兵力", "車隊"]},
            {"message_id": "m2", "segments": ["兵力", "集結"]},
        ],
    }


class KnownPairHoldoutTests(unittest.TestCase):
    def test_genuine_fixture_runs_and_does_not_mutate_input(self):
        case = load_case(ROOT / "benchmarks/cases/07_alias_mixed_length.json")
        original = deepcopy(case)
        with patch("han_codebook.holdout_verification.analyze", wraps=analyze) as runner:
            report = verify_known_pairs(case, iterations=1, restarts=1)
            self.assertEqual(runner.call_count, 1)
            submitted = runner.call_args.args[0]
            self.assertEqual(submitted["known_pairs"], [])
        self.assertEqual(case, original)
        self.assertEqual(report["evaluated_fold_count"], 1)
        self.assertEqual(report["summary"]["independently_testable_fold_code_assessments"], 5)
        self.assertEqual(report["summary"]["overlapping_anchored_codes_excluded"], 0)
        self.assertNotIn("兵力", json.dumps(report, ensure_ascii=False))
        self.assertTrue(all(item["outcome"] != "verified_alignment"
                            for item in report["folds"][0]["outcomes_without_plaintext"]))

    def test_overlapping_verified_codes_not_counted_as_independent(self):
        case = small_case()
        with patch("han_codebook.holdout_verification.analyze", wraps=analyze) as runner:
            result = verify_known_pairs(case, iterations=1, restarts=1)
        self.assertEqual(result["evaluated_fold_count"], 2)
        self.assertEqual(result["summary"]["independently_testable_fold_code_assessments"], 2)
        self.assertEqual(result["summary"]["overlapping_anchored_codes_excluded"], 2)
        self.assertEqual([r["independently_testable_codes"] for r in result["folds"]], [1, 1])
        self.assertEqual([r["retained_anchor_overlap_excluded"] for r in result["folds"]], [1, 1])
        self.assertEqual(runner.call_count, 2)
        self.assertEqual(runner.call_args.args[0]["known_pairs"],
                         [{"message_id": "m1", "segments": ["兵力", "車隊"]}])

    def test_duplicate_message_records_and_unsegmented_copies_are_all_withheld(self):
        case = small_case()
        case["known_pairs"].append({
            "message_id": "m1", "plaintext": "兵力車隊"
        })
        case["known_pairs"].append({
            "message_id": "m1", "segments": ["兵力", "車隊"]
        })
        report = verify_known_pairs(case, max_folds=1, iterations=1, restarts=1)
        self.assertEqual(report["folds"][0]["withheld_record_count"], 3)
        self.assertEqual(report["unaligned_plaintext_records_not_scored"], 1)
        with patch("han_codebook.holdout_verification.analyze", wraps=analyze) as runner:
            verify_known_pairs(case, max_folds=1, iterations=1, restarts=1)
        self.assertEqual(runner.call_args.args[0]["known_pairs"],
                         [{"message_id": "m2", "segments": ["兵力", "集結"]}])

    def test_hidden_reference_never_sent_to_solver_and_researcher_cues_removed(self):
        case = small_case()
        case["candidate_ideas"] = {
            "102": [{"term": "車隊", "source": "researcher", "status": "shortlisted"}],
            "103": [{"term": "集結", "source": "researcher", "status": "suggested"}],
        }
        case["bold_hypotheses"] = {
            "102": {"term": "研究員反事實", "note": "", "confirmed": True}
        }
        folded = _fold_input(case, "m1", {"101", "102"})
        self.assertNotIn("102", folded["candidate_ideas"])
        self.assertNotIn("102", folded["bold_hypotheses"])
        self.assertIn("103", folded["candidate_ideas"])
        self.assertEqual(folded["known_pairs"],
                         [{"message_id": "m2", "segments": ["兵力", "集結"]}])

    def test_failure_categories_and_no_plaintext_output(self):
        case = small_case()
        # Withhold all truth by testing one message while the other has no
        # known pair. Vocabulary deliberately does not include '祕密答案'.
        case["known_pairs"] = [
            {"message_id": "m1", "segments": ["兵力", "祕密答案"]}
        ]
        observed_inputs = []
        def fake_solver(payload, **kwargs):
            observed_inputs.append(deepcopy(payload))
            self.assertEqual(payload["known_pairs"], [])
            return {
                "verified_anchors": {},
                "researcher_marks": {},
                "proposals": {
                    "101": {"term": "車隊", "status": "hypothesis_unverified",
                            "alternatives": [{"term": "車隊"}, {"term": "兵力"}]},
                    "102": {"term": "車隊", "status": "hypothesis_unverified",
                            "alternatives": [{"term": "車隊"}]},
                    "103": {"term": "車隊", "status": "hypothesis_unverified",
                            "alternatives": [{"term": "車隊"}]},
                },
            }
        with patch("han_codebook.holdout_verification.analyze", side_effect=fake_solver):
            result = verify_known_pairs(case)
        failures = result["summary"]["failure_categories"]
        self.assertEqual(failures["top5_only_ranking_error"], 1)
        self.assertEqual(failures["term_missing_from_candidate_vocabulary"], 1)
        self.assertEqual(result["summary"]["top1_hits"], 0)
        self.assertEqual(result["summary"]["top5_hits"], 1)
        self.assertNotIn("祕密答案", json.dumps(result, ensure_ascii=False))
        self.assertEqual(len(observed_inputs), 1)
        self.assertNotIn("祕密答案", json.dumps(observed_inputs[0], ensure_ascii=False))

    def test_correct_top1_and_available_term_ranked_below_top5(self):
        case = small_case()
        case["known_pairs"] = [case["known_pairs"][0]]
        def fake_solver(payload, **kwargs):
            self.assertEqual(payload["known_pairs"], [])
            return {
                "verified_anchors": {},
                "researcher_marks": {},
                "proposals": {
                    "101": {"term": "兵力", "status": "hypothesis_unverified",
                            "alternatives": [{"term": "兵力"}]},
                    "102": {"term": "集結", "status": "hypothesis_unverified",
                            "alternatives": [{"term": "集結"}]},
                },
            }
        with patch("han_codebook.holdout_verification.analyze", side_effect=fake_solver):
            result = verify_known_pairs(case)
        self.assertEqual(result["summary"]["top1_hits"], 1)
        self.assertEqual(result["summary"]["top5_hits"], 1)
        self.assertEqual(result["summary"]["failure_categories"]["candidate_ranked_below_top5"], 1)
        self.assertEqual(result["summary"]["top1_rate"], 0.5)

    def test_all_codes_reanchored_yields_no_valid_independent_score(self):
        case = small_case()
        case["messages"][1]["codes"] = ["101", "102"]
        case["known_pairs"][1]["segments"] = ["兵力", "車隊"]
        with patch("han_codebook.holdout_verification.analyze",
                   side_effect=AssertionError("no valid unanchored codes")):
            report = verify_known_pairs(case)
        self.assertEqual(report["summary"]["independently_testable_fold_code_assessments"], 0)
        self.assertIsNone(report["summary"]["top1_rate"])
        self.assertTrue(all(fold["status"] == "no_newly_unanchored_codes"
                            for fold in report["folds"]))

    def test_reject_oracle_invalid_arguments_and_unsegmented_only(self):
        case = small_case()
        for key in ("ground_truth", "gold", "codebook"):
            changed = deepcopy(case)
            changed[key] = {"101": "兵力"}
            with self.subTest(key=key), self.assertRaises(CaseError):
                verify_known_pairs(changed)
        for kw in ({"max_folds": 0}, {"max_folds": True},
                   {"iterations": 0}, {"restarts": 0}, {"use_metadata": 1}):
            with self.subTest(kw=kw), self.assertRaises(CaseError):
                verify_known_pairs(case, **kw)
        case["known_pairs"] = [{"message_id": "m1", "plaintext": "兵力車隊"}]
        with self.assertRaisesRegex(CaseError, "segmented known pair"):
            verify_known_pairs(case)

    def test_offline_cli_writes_report_without_plaintext_or_llm(self):
        case = small_case()
        with TemporaryDirectory() as temp:
            case_path = Path(temp) / "case.json"
            out = Path(temp) / "verification.json"
            case_path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
            with patch("han_codebook.agent.query_local_llm",
                       side_effect=AssertionError("no network calls")):
                code = main(["--case", str(case_path), "--out", str(out),
                             "--iterations", "1", "--restarts", "1"])
            self.assertEqual(code, 0)
            report = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(report["evaluated_fold_count"], 2)
            self.assertNotIn("兵力", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
