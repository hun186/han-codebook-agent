"""Paired offline metadata ablation of independent known-pair holdout folds."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from han_codebook.core import CaseError
from han_codebook.paired_holdout import main, paired_metadata_holdout


def fixture():
    return {
        "case_id": "paired-fictional",
        "profiles": {"neutral": {
            "keywords": [], "lexicon": {"車隊": 2, "集結": 2, "補給": 2},
            "sentences": [["補給", "車隊"]]}},
        "messages": [{"id": "m1", "codes": ["101", "102"]},
                     {"id": "m2", "codes": ["101", "103"]}],
        "known_pairs": [{"message_id": "m1", "segments": ["補給", "車隊"]},
                        {"message_id": "m2", "segments": ["補給", "集結"]}],
    }


def example_fold(mid, entries, *, status="scored"):
    return {
        "heldout_message_id": mid,
        "independently_testable_codes": len(entries),
        "retained_anchor_overlap_excluded": 0,
        "status": status,
        "scored_code_assessments": len(entries) if status == "scored" else 0,
        "outcomes_without_plaintext": [
            {"code": code, "outcome": outcome} for code, outcome in entries
        ],
    }


def report(*folds):
    return {"case_id": "paired-fictional", "available_fold_count": len(folds),
            "summary": {"top1_rate": None}, "folds": list(folds)}


class PairedHoldoutTests(unittest.TestCase):
    def test_same_fold_two_conditions_and_no_reference_text(self):
        case = fixture()
        before = deepcopy(case)
        with patch("han_codebook.agent.query_local_llm",
                   side_effect=AssertionError("No LLM calls in holdout")):
            with patch("han_codebook.paired_holdout.verify_known_pairs",
                       wraps=__import__(
                           "han_codebook.holdout_verification",
                           fromlist=["verify_known_pairs"]).verify_known_pairs) as runner:
                result = paired_metadata_holdout(case, iterations=1, restarts=1)
        self.assertEqual(case, before)
        self.assertEqual(runner.call_count, 2)
        self.assertEqual([c.kwargs["use_metadata"] for c in runner.call_args_list],
                         [True, False])
        self.assertEqual(result["evaluated_fold_count"], 2)
        self.assertEqual(result["paired_summary"]["paired_scored_code_assessments"], 2)
        self.assertEqual(result["paired_summary"]["not_comparable_code_assessments"], 0)
        self.assertNotIn("補給", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("車隊", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("集結", json.dumps(result, ensure_ascii=False))
        self.assertEqual([f["heldout_message_id"] for f in result["folds"]],
                         ["m1", "m2"])

    def test_help_harm_ties_and_blocked_are_paired_not_overcounted(self):
        on = report(
            example_fold("a", [
                ("101", "correct_top1"),
                ("102", "top5_only_ranking_error"),
                ("103", "candidate_ranked_below_top5"),
                ("104", "correct_top1")]),
            example_fold("b", [
                ("201", "not_scored_due_to_candidate_exclusions")],
                status="candidate_exclusions_blocked_inference"))
        off = report(
            example_fold("a", [
                ("101", "top5_only_ranking_error"),
                ("102", "correct_top1"),
                ("103", "term_missing_from_candidate_vocabulary"),
                ("104", "correct_top1")]),
            example_fold("b", [
                ("201", "not_scored_due_to_candidate_exclusions")],
                status="candidate_exclusions_blocked_inference"))
        with patch("han_codebook.paired_holdout.verify_known_pairs",
                   side_effect=[on, off]) as runner:
            result = paired_metadata_holdout(fixture(), iterations=2, restarts=3)
        self.assertEqual([c.kwargs["use_metadata"] for c in runner.call_args_list],
                         [True, False])
        self.assertEqual([c.kwargs["iterations"] for c in runner.call_args_list],
                         [2, 2])
        s = result["paired_summary"]
        self.assertEqual(s["paired_scored_code_assessments"], 4)
        self.assertEqual(s["not_comparable_code_assessments"], 1)
        self.assertEqual(s["top1_helped"], 1)
        self.assertEqual(s["top1_harmed"], 1)
        self.assertEqual(s["top1_both_correct"], 1)
        self.assertEqual(s["top1_both_wrong"], 1)
        self.assertEqual(s["top5_helped"], 0)
        self.assertEqual(s["top5_harmed"], 0)
        self.assertEqual(s["top5_both_correct"], 3)
        self.assertEqual(s["top5_both_wrong"], 1)
        self.assertEqual(s["top1_net_helped_minus_harmed"], 0)
        self.assertEqual(result["folds"][1]["paired_scored_code_assessments"], 0)
        self.assertEqual(result["folds"][1]["effects_without_plaintext"][0]["top1"],
                         "not_comparable")
        self.assertNotIn("plaintext", json.dumps(result["folds"]))

    def test_mismatched_folds_and_code_set_fail_closed(self):
        on = report(example_fold("m1", [("101", "correct_top1")]))
        for off in (report(example_fold("m2", [("101", "correct_top1")])),
                    report(example_fold("m1", [("102", "correct_top1")])),
                    report(example_fold("m1", [("101", "correct_top1"),
                                               ("102", "correct_top1")]))):
            with self.subTest(off=off), patch(
                "han_codebook.paired_holdout.verify_known_pairs",
                side_effect=[on, off]
            ):
                with self.assertRaisesRegex(CaseError, "paired holdout"):
                    paired_metadata_holdout(fixture())

    def test_cli_create_only_private_output_and_original_unchanged(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "case.json"
            output = root / "paired.json"
            source.write_text(json.dumps(fixture(), ensure_ascii=False),
                              encoding="utf-8")
            original = source.read_bytes()
            args = ["--case", str(source), "--out", str(output),
                    "--iterations", "1", "--restarts", "1"]
            with patch("han_codebook.agent.query_local_llm",
                       side_effect=AssertionError("LLM forbidden")):
                self.assertEqual(main(args), 0)
                first = output.read_bytes()
                self.assertEqual(main(args), 2)
                self.assertEqual(main(["--case", str(source), "--out", str(source),
                                       "--iterations", "1", "--restarts", "1"]), 2)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(output.read_bytes(), first)
            self.assertIn("paired_summary", json.loads(first))
            self.assertNotIn("補給", first.decode("utf-8"))
            if os.name == "posix":
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            if hasattr(os, "symlink"):
                symlink = root / "symlink.json"
                try:
                    symlink.symlink_to(output)
                except (OSError, NotImplementedError):
                    pass
                else:
                    self.assertEqual(main(["--case", str(source), "--out", str(symlink),
                                           "--iterations", "1", "--restarts", "1"]), 2)
                    self.assertEqual(output.read_bytes(), first)

    def test_reject_oracle_without_inference_or_output_file(self):
        with TemporaryDirectory() as temp:
            source = Path(temp) / "case.json"
            dest = Path(temp) / "report.json"
            case = fixture()
            case["ground_truth"] = {"101": "補給"}
            source.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
            with patch("han_codebook.paired_holdout.verify_known_pairs",
                       wraps=__import__(
                           "han_codebook.holdout_verification",
                           fromlist=["verify_known_pairs"]).verify_known_pairs):
                self.assertEqual(main(["--case", str(source), "--out", str(dest)]), 2)
            self.assertFalse(dest.exists())


if __name__ == "__main__":
    unittest.main()
