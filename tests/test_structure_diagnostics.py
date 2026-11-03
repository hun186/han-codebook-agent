"""Offline synthetic structural LOMO regression: never use gold or model."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from han_codebook.core import CaseError
from han_codebook.structure_diagnostics import main, structure_report


def case_fixture():
    return {
        "case_id": "synthetic-structure",
        "profiles": {"neutral": {"keywords": [], "lexicon": {"可信": 1},
                                  "sentences": []}},
        "messages": [
            {"id": "anchor", "codes": ["200"]},
            {"id": "A", "codes": ["100", "200", "300", "100", "400"],
             "sender": "PRIVATE_SENDER", "notes": "PRIVATE_NOTES"},
            {"id": "B", "codes": ["100", "200", "500"]},
            {"id": "C", "codes": ["600", "100", "700"]},
        ],
        "known_pairs": [{"message_id": "anchor", "segments": ["可信"]}],
    }


class StructuralLOMOTests(unittest.TestCase):
    def test_cross_message_support_not_within_message_or_plaintext(self):
        case = case_fixture()
        case["case_id"] = "PRIVATE_CASE_LABEL_NEVER_EXPORT"
        original = deepcopy(case)
        report = structure_report(case)
        row = next(r for r in report["unknown_code_context"] if r["code"] == "100")
        self.assertEqual(row["occurrences"], 4)
        self.assertEqual(row["distinct_messages"], 3)
        self.assertEqual(row["heldout_same_sided_neighbor"], 2)
        self.assertEqual(row["heldout_same_sided_verified_code_neighbor"], 2)
        self.assertEqual(report["summary"]["verified_code_count_excluded"], 1)
        self.assertNotIn("200", [r["code"] for r in report["unknown_code_context"]])
        repeat = next(p for p in report["repeated_cipher_patterns"]
                      if p["codes"] == ["100", "200"])
        self.assertEqual(repeat["distinct_message_count"], 2)
        self.assertEqual(repeat["sample_message_ids"], ["A", "B"])
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn("PRIVATE_", serialized)
        self.assertNotIn("PRIVATE_CASE_LABEL_NEVER_EXPORT", serialized)
        self.assertNotIn("可信", serialized)
        self.assertNotIn("ground_truth", serialized)
        self.assertEqual(original, case)

    def test_single_message_repetition_is_not_independent(self):
        case = case_fixture()
        case["messages"] = [
            {"id": "A", "codes": ["100", "200", "100", "200"]},
            {"id": "B", "codes": ["100", "300"]},
        ]
        case["known_pairs"] = []
        report = structure_report(case)
        row = next(r for r in report["unknown_code_context"] if r["code"] == "100")
        self.assertEqual(row["occurrences"], 3)
        self.assertEqual(row["distinct_messages"], 2)
        self.assertEqual(row["heldout_same_sided_neighbor"], 0)
        self.assertEqual(report["summary"]["repeated_patterns"], 0)

    def test_rejects_embedded_oracle(self):
        case = case_fixture()
        case["ground_truth"] = {"100": "不可傳送"}
        with self.assertRaises(CaseError):
            structure_report(case)
        del case["ground_truth"]
        case["messages"][1]["gold"] = {"100": "不可傳送"}
        with self.assertRaises(CaseError):
            structure_report(case)

    def test_unique_report_nonoverwrite_and_private_permissions(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / "case.json"
            output = Path(folder) / "new.json"
            source.write_text(json.dumps(case_fixture(), ensure_ascii=False), encoding="utf-8")
            self.assertEqual(main(["--case", str(source), "--out", str(output)]), 0)
            original = output.read_bytes()
            self.assertEqual(json.loads(original)["schema"], "han_cipher_structure_lomo_v1")
            with self.assertRaises(SystemExit) as caught:
                main(["--case", str(source), "--out", str(output)])
            self.assertEqual(caught.exception.code, 2)
            self.assertEqual(output.read_bytes(), original)
            existing_source = source.read_bytes()
            with self.assertRaises(SystemExit):
                main(["--case", str(source), "--out", str(source)])
            self.assertEqual(source.read_bytes(), existing_source)
            if os.name == "posix":
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_singleton_has_zero_supported_assessments(self):
        case = case_fixture()
        case["messages"] = [{"id": "one", "codes": ["100"]}]
        case["known_pairs"] = []
        del case["case_id"]  # case_id is optional, must not affect structure
        report = structure_report(case)
        self.assertEqual(report["summary"]["heldout_message_code_assessments"], 1)
        self.assertEqual(report["summary"]["heldout_with_same_sided_neighbor"], 0)
        self.assertEqual(report["repeated_cipher_patterns"], [])


    def test_unsegmented_plaintext_cannot_trigger_semantic_heuristics(self):
        case = case_fixture()
        case["profiles"] = {"neutral": {"lexicon": "unused-bad-analysis-data"}}
        case["known_pairs"].append({"message_id": "B", "plaintext": "未對齊明文" * 800})
        case["hypothesis_marks"] = {"100": {"untrusted": "never normalized"}}
        snapshot = deepcopy(case)
        with patch("han_codebook.core.segmentation_candidates",
                   side_effect=AssertionError("must not cut plaintext")), \
             patch("han_codebook.core.validate_case",
                   side_effect=AssertionError("must not validate semantic priors")), \
             patch("han_codebook.core.anchors_and_review",
                   side_effect=AssertionError("must not infer semantic anchors")):
            report = structure_report(case)
        self.assertEqual(report["summary"]["verified_code_count_excluded"], 1)
        self.assertEqual(case, snapshot)
        self.assertNotIn("未對齊明文", json.dumps(report, ensure_ascii=False))
        self.assertNotIn("unused-bad", json.dumps(report, ensure_ascii=False))

    def test_known_pair_conflicts_still_fail_without_exposing_reference_terms(self):
        case = case_fixture()
        case["known_pairs"].append({
            "message_id": "B", "segments": ["甲", "乙", "丙"]
        })
        with self.assertRaises(CaseError):
            structure_report(case)
        case["known_pairs"].pop()
        case["known_pairs"][0]["plaintext"] = "錯誤明文"
        with self.assertRaises(CaseError):
            structure_report(case)
        case["known_pairs"][0].pop("plaintext")
        case["known_pairs"][0]["segments"] = ["a", "b"]
        with self.assertRaises(CaseError):
            structure_report(case)

    def test_bounded_cipher_ids_and_invalid_known_pair_references(self):
        case = case_fixture()
        case["known_pairs"].append({"message_id": "missing", "plaintext": "未知"})
        with self.assertRaises(CaseError):
            structure_report(case)
        case["known_pairs"].pop()
        case["messages"][1]["codes"][0] = "0" * 65
        with self.assertRaises(CaseError):
            structure_report(case)
        case["messages"][1]["codes"][0] = "100"
        case["messages"].append({"id": "A", "codes": ["123"]})
        with self.assertRaises(CaseError):
            structure_report(case)
        case["messages"].pop()
        case["known_pairs"][0]["gold"] = {"secret": "unused"}
        with self.assertRaises(CaseError):
            structure_report(case)


if __name__ == "__main__":
    unittest.main()
