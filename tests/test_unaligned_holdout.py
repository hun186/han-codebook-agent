"""Independent held-out segmentation scoring must never leak answer segments."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from han_codebook.core import CaseError
from han_codebook.unaligned_holdout import evaluate_segmentation_holdout, main
from han_codebook.unaligned_review import review_unsegmented


def fixture():
    return {
        "case_id": "segmentation-holdout-test",
        "profiles": {"neutral": {
            "lexicon": {"甲": 2, "乙": 2, "丙": 2},
            "sentences": [["甲", "乙"], ["乙", "丙"]],
        }},
        "messages": [
            {"id": "m1", "codes": ["001", "002"]},
            {"id": "m2", "codes": ["003", "004"]},
        ],
        "known_pairs": [
            {"message_id": "m1", "segments": ["甲", "乙"]},
            {"message_id": "m2", "segments": ["乙", "丙"]},
        ],
    }


class SegmentationHoldoutTests(unittest.TestCase):
    def test_independent_exact_rank_no_plaintext_output(self):
        case = fixture()
        before = deepcopy(case)
        report = evaluate_segmentation_holdout(case)
        self.assertEqual(case, before)
        self.assertEqual(report["evaluated_fold_count"], 2)
        self.assertEqual(report["summary"]["independent_scored_folds"], 2)
        self.assertEqual(report["summary"]["independent_exact_top1_hits"], 2)
        self.assertEqual(report["summary"]["independent_exact_topn_rate"], 1.0)
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("甲", serialized)
        self.assertNotIn("乙", serialized)
        self.assertNotIn("丙", serialized)
        self.assertNotIn('"segments"', serialized)
        self.assertNotIn('"plaintext"', serialized)

    def test_all_same_message_records_removed_before_review(self):
        case = fixture()
        case["known_pairs"].append(deepcopy(case["known_pairs"][0]))
        case["known_pairs"].append({"message_id": "m2", "plaintext": "乙丙"})
        case["hypothesis_revision_history"] = {"001": "甲"}
        case["candidate_ideas"] = {"001": [{"term": "甲"}]}
        observed = []

        def inspect(folded, **kw):
            target = next(p["message_id"] for p in folded["known_pairs"]
                          if "plaintext" in p)
            observed.append(target)
            self.assertEqual(
                [p for p in folded["known_pairs"]
                 if p["message_id"] == target and "segments" in p], [])
            self.assertNotIn("candidate_ideas", folded)
            self.assertNotIn("hypothesis_revision_history", folded)
            self.assertEqual(sum(p["message_id"] == target
                                 for p in folded["known_pairs"]), 1)
            return review_unsegmented(folded, **kw)

        with patch("han_codebook.unaligned_holdout.review_unsegmented",
                   side_effect=inspect):
            report = evaluate_segmentation_holdout(case)
        self.assertEqual(observed, ["m1", "m2"])
        self.assertEqual(report["folds"][0]["withheld_record_count"], 2)
        self.assertEqual(report["folds"][1]["withheld_record_count"], 2)

    def test_overlap_excluded_from_independent_denominator(self):
        case = fixture()
        case["messages"][1]["codes"] = ["001", "004"]
        case["known_pairs"][1]["segments"] = ["甲", "丙"]
        report = evaluate_segmentation_holdout(case)
        self.assertEqual(report["summary"]["overlap_folds_excluded"], 2)
        self.assertEqual(report["summary"]["independent_scored_folds"], 0)
        self.assertIsNone(report["summary"]["independent_exact_top1_rate"])
        self.assertTrue(all(
            fold["overlap_code_groups_excluded"] == 1
            for fold in report["folds"]
        ))

    def test_over_limit_excluded_not_wrong_prediction(self):
        case = fixture()
        case["messages"] = [{"id": "m1", "codes": ["001"]}]
        case["known_pairs"] = [
            {"message_id": "m1", "segments": ["甲" * 501]}
        ]
        report = evaluate_segmentation_holdout(case)
        self.assertEqual(report["summary"]["too_long_folds_not_scored"], 1)
        self.assertEqual(report["summary"]["independent_scored_folds"], 0)
        self.assertEqual(report["folds"][0]["outcome"],
                         "not_scored_plaintext_over_limit")

    def test_no_external_calls_or_input_mutation(self):
        case = fixture()
        before = deepcopy(case)
        with patch("han_codebook.agent.query_local_llm",
                   side_effect=AssertionError("LLM calls forbidden")):
            report = evaluate_segmentation_holdout(case, top_n=2)
        self.assertEqual(case, before)
        self.assertEqual(report["summary"]["independent_scored_folds"], 2)

    def test_invalid_oracle_and_contradiction_fail_closed(self):
        case = fixture()
        case["ground_truth"] = {"001": "甲"}
        with self.assertRaisesRegex(CaseError, "oracle"):
            evaluate_segmentation_holdout(case)
        case = fixture()
        case["known_pairs"].append(
            {"message_id": "m1", "segments": ["丙", "乙"]}
        )
        with self.assertRaisesRegex(CaseError, "conflicting verified"):
            evaluate_segmentation_holdout(case)
        case = fixture()
        for kwargs in ({"max_folds": 0}, {"max_folds": True},
                       {"top_n": 13}, {"beam_width": 2}):
            with self.subTest(kwargs=kwargs), self.assertRaises(CaseError):
                evaluate_segmentation_holdout(case, **kwargs)

    def test_cli_writes_only_aggregate_and_folds(self):
        with TemporaryDirectory() as td:
            infile = Path(td) / "case.json"
            outfile = Path(td) / "result.json"
            infile.write_text(json.dumps(fixture(), ensure_ascii=False),
                              encoding="utf-8")
            self.assertEqual(main(["--case", str(infile), "--out", str(outfile),
                                   "--max-folds", "1"]), 0)
            saved = json.loads(outfile.read_text(encoding="utf-8"))
            self.assertEqual(saved["evaluated_fold_count"], 1)
            self.assertEqual(saved["summary"]["independent_scored_folds"], 1)
            self.assertNotIn("甲", outfile.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
