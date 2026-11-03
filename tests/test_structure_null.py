"""Synthetic checks for independent, nonsemantic shuffled-order null baseline."""
from __future__ import annotations

from copy import deepcopy
import json
import os
import random
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from han_codebook.core import CaseError
from han_codebook.structure_diagnostics import structure_report
from han_codebook.structure_null import main, permutation_baseline


def case_fixture():
    return {
        "case_id": "PRIVATE_CASE_LABEL",
        "profiles": {"neutral": {"lexicon": {"機密錨詞": 1}, "sentences": []}},
        "messages": [
            {"id": "anchor", "codes": ["200"], "notes": "PRIVATE_NOTES"},
            {"id": "A", "codes": ["100", "200", "300", "100", "400"]},
            {"id": "B", "codes": ["100", "200", "500"]},
            {"id": "C", "codes": ["600", "100", "700"]},
        ],
        "known_pairs": [{"message_id": "anchor", "segments": ["機密錨詞"]}],
    }


class StructureNullTests(unittest.TestCase):
    def test_reproducible_nonsemantic_aggregate_and_input_immutable(self):
        case = case_fixture()
        snapshot = deepcopy(case)
        first = permutation_baseline(case, trials=8, seed=123)
        second = permutation_baseline(case, trials=8, seed=123)
        self.assertEqual(first, second)
        self.assertEqual(case, snapshot)
        self.assertEqual(first["trials"], 8)
        self.assertEqual(first["frozen_known_pair_messages"], 1)
        self.assertEqual(first["permutable_messages"], 3)
        self.assertEqual(first["observed"]["heldout_with_same_sided_neighbor"],
                         structure_report(case)["summary"]["heldout_with_same_sided_neighbor"])
        self.assertGreater(sum(first["changed_code_positions_per_trial"]), 0)
        output = json.dumps(first, ensure_ascii=False)
        for private in ("PRIVATE_CASE_LABEL", "PRIVATE_NOTES", "機密錨詞"):
            self.assertNotIn(private, output)
        self.assertNotIn("ground_truth", output)

    def test_freeze_all_known_pair_messages_without_shuffling_known_alignment(self):
        case = case_fixture()
        captured = []
        def wrapped(value):
            captured.append(deepcopy(value))
            return structure_report(value)
        with patch("han_codebook.structure_null.structure_report", side_effect=wrapped):
            permutation_baseline(case, trials=4, seed=11)
        self.assertEqual(len(captured), 5)
        self.assertTrue(all(x["messages"][0]["codes"] == ["200"] for x in captured))
        for variant in captured[1:]:
            for original, shuffled in zip(case["messages"], variant["messages"]):
                self.assertEqual(sorted(original["codes"]), sorted(shuffled["codes"]))

    def test_fails_closed_for_invalid_options_and_oracles(self):
        case = case_fixture()
        for invalid in (True, 0, 33, 1.5, "5"):
            with self.assertRaises(CaseError):
                permutation_baseline(case, trials=invalid)
        for invalid in (True, -1, 2**31, "1"):
            with self.assertRaises(CaseError):
                permutation_baseline(case, seed=invalid)
        case["ground_truth"] = {"100": "SECRET"}
        with self.assertRaises(CaseError):
            permutation_baseline(case, trials=1)

    def test_no_permutable_messages_requires_explicit_failure(self):
        case = case_fixture()
        case["messages"] = [{"id": "anchor", "codes": ["100", "200"]}]
        case["known_pairs"] = [{"message_id": "anchor", "segments": ["甲", "乙"]}]
        with self.assertRaises(CaseError):
            permutation_baseline(case, trials=3)

    def test_create_only_and_private_permissions(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / "source.json"
            output = Path(folder) / "control.json"
            source.write_text(json.dumps(case_fixture(), ensure_ascii=False), encoding="utf-8")
            self.assertEqual(main(["--case", str(source), "--out", str(output),
                                   "--trials", "3", "--seed", "7"]), 0)
            before = output.read_bytes()
            self.assertEqual(json.loads(before)["trials"], 3)
            with self.assertRaises(SystemExit) as thrown:
                main(["--case", str(source), "--out", str(output), "--trials", "3"])
            self.assertEqual(thrown.exception.code, 2)
            self.assertEqual(before, output.read_bytes())
            if os.name == "posix":
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_case08_synthetic_integration_without_loading_gold(self):
        path = Path(__file__).parents[1] / "benchmarks" / "cases" / "08_long_dispatch_with_observations.json"
        case = json.loads(path.read_text(encoding="utf-8"))
        report = permutation_baseline(case, trials=2, seed=5)
        self.assertGreater(report["permutable_messages"], 0)
        self.assertEqual(report["trials"], 2)
        self.assertEqual(set(report["observed"]), {
            "heldout_with_same_sided_neighbor",
            "heldout_with_same_sided_verified_code_neighbor",
            "repeated_patterns",
        })


    def test_long_unsegmented_known_pair_frozen_without_segmentation(self):
        case = case_fixture()
        case["known_pairs"].append({
            "message_id": "A", "plaintext": "私人未切段明文" * 1500
        })
        original = deepcopy(case)
        snapshots = []
        real_report = structure_report
        def observe(value):
            snapshots.append(deepcopy(value))
            return real_report(value)
        with patch("han_codebook.core.segmentation_candidates",
                   side_effect=AssertionError("should never segment known pair")), \
             patch("han_codebook.structure_null.structure_report",
                   side_effect=observe):
            result = permutation_baseline(case, trials=3, seed=9)
        self.assertEqual(case, original)
        self.assertEqual(result["frozen_known_pair_messages"], 2)
        self.assertEqual(result["permutable_messages"], 2)
        self.assertEqual(len(snapshots), 4)
        for shadow in snapshots[1:]:
            self.assertEqual(shadow["messages"][1]["codes"], case["messages"][1]["codes"])
        self.assertNotIn("私人未切段", json.dumps(result, ensure_ascii=False))


    def test_null_shadow_does_not_copy_unused_private_fields(self):
        class NoDeepCopy:
            def __deepcopy__(self, memo):
                raise AssertionError("Private fields must not be copied into null controls")

        case = case_fixture()
        sentinel = NoDeepCopy()
        case["case_id"] = sentinel
        case["profiles"] = {"private": sentinel}
        case["messages"][1]["notes"] = sentinel
        case["known_pairs"][0]["private_note"] = sentinel
        case["known_pairs"].append({"message_id": "B", "plaintext": sentinel})

        calls = []
        original_report = structure_report

        def inspect(value):
            if calls:
                self.assertEqual(set(value), {"messages", "known_pairs"})
                self.assertTrue(all(set(m) == {"id", "codes"} for m in value["messages"]))
                self.assertTrue(all(set(p) <= {"message_id", "segments"}
                                    for p in value["known_pairs"]))
                self.assertNotIn("plaintext", str(value))
            calls.append(1)
            return original_report(value)

        with patch("han_codebook.structure_null.structure_report", side_effect=inspect):
            result = permutation_baseline(case, trials=4, seed=7)
        self.assertEqual(len(calls), 5)
        self.assertEqual(result["trials"], 4)
        self.assertIs(case["messages"][1]["notes"], sentinel)
        self.assertIs(case["known_pairs"][1]["plaintext"], sentinel)
        self.assertNotIn("private", json.dumps(result, ensure_ascii=False).lower())

    def test_null_distribution_exactly_matches_original_full_copy_algorithm(self):
        case = case_fixture()
        baseline = permutation_baseline(case, trials=8, seed=71)
        rng = random.Random(71)
        frozen = {p["message_id"] for p in case["known_pairs"]}
        eligible = {m["id"] for m in case["messages"]
                    if m["id"] not in frozen and len(m["codes"]) > 1
                    and len(set(m["codes"])) > 1}
        actual_samples = []
        changed_positions = []
        for _ in range(8):
            shadow = deepcopy(case)
            changed = 0
            for message in shadow["messages"]:
                if message["id"] in eligible:
                    before = list(message["codes"])
                    rng.shuffle(message["codes"])
                    changed += sum(x != y for x, y in zip(before, message["codes"]))
            changed_positions.append(changed)
            actual_samples.append(structure_report(shadow)["summary"])
        self.assertEqual(baseline["changed_code_positions_per_trial"], changed_positions)
        for metric in ("heldout_with_same_sided_neighbor",
                       "heldout_with_same_sided_verified_code_neighbor",
                       "repeated_patterns"):
            values = [row[metric] for row in actual_samples]
            self.assertEqual(baseline["shuffled_order_null"][metric], {
                "minimum": min(values), "maximum": max(values),
                "mean": round(sum(values) / 8, 4),
            })


if __name__ == "__main__":
    unittest.main()
