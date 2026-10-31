"""Tests for bounded offline unsegmented known-plaintext review candidates."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from han_codebook.core import CaseError, anchors_and_review, load_case
from han_codebook.unaligned_review import (
    main, review_unsegmented, suggest_alignments
)


ROOT = Path(__file__).resolve().parents[1]


def sample():
    return {
        "case_id": "unaligned-review-fixture",
        "profiles": {"neutral": {
            "lexicon": {"補給": 8, "車隊": 8, "出發": 6, "後勤": 3},
            "sentences": [["補給", "車隊", "出發"]],
        }},
        "messages": [
            {"id": "other", "codes": ["101"]},
            {"id": "target", "codes": ["101", "102", "103"]},
        ],
        "known_pairs": [
            {"message_id": "other", "segments": ["補給"]},
            {"message_id": "target", "plaintext": "補給車隊出發"},
        ],
    }


class UnalignedReviewTests(unittest.TestCase):
    def test_trusted_anchor_and_dictionary_rank_without_promoting(self):
        case = sample()
        before = deepcopy(case)
        old_anchors, _, _ = anchors_and_review(case)
        with patch("han_codebook.agent.query_local_llm",
                   side_effect=AssertionError("no LLM call")):
            result = review_unsegmented(case)
        after_anchors, _, _ = anchors_and_review(case)
        self.assertEqual(case, before)
        self.assertEqual(old_anchors, after_anchors)
        self.assertEqual(result["trusted_anchor_count_unchanged"], 1)
        self.assertEqual(result["unaligned_pair_count"], 1)
        row = result["reviews"][0]
        self.assertEqual(row["status"], "manual_confirmation_required")
        self.assertEqual(row["verified_constraints_used"], 1)
        self.assertEqual(row["candidates"][0]["segments"], ["補給", "車隊", "出發"])
        self.assertTrue(all(c["status"] == "candidate_unverified"
                            for c in row["candidates"]))
        self.assertEqual(old_anchors, {"101": "補給"})
        self.assertNotIn("verified_alignment", json.dumps(result, ensure_ascii=False))

    def test_repeated_unknown_code_must_keep_same_phrase(self):
        found = suggest_alignments("補給車隊補給", ["101", "102", "101"],
                                   {"補給", "車隊"}, {}, beam_width=128)
        self.assertEqual(found["candidates"][0]["segments"],
                         ["補給", "車隊", "補給"])
        for item in found["candidates"]:
            self.assertEqual(item["segments"][0], item["segments"][2])

    def test_conflicting_anchor_cannot_be_overridden_by_guesses(self):
        case = sample()
        case["known_pairs"][0]["segments"] = ["軍令"]
        report = review_unsegmented(case)
        self.assertEqual(report["reviews"][0]["status"], "no_feasible_alignment")
        self.assertEqual(report["reviews"][0]["candidates"], [])
        self.assertEqual(report["trusted_anchor_count_unchanged"], 1)

    def test_contradictory_verified_pairs_fail_closed(self):
        case = sample()
        case["messages"].append({"id": "other2", "codes": ["101"]})
        case["known_pairs"].append({
            "message_id": "other2", "segments": ["錯誤"]
        })
        with self.assertRaisesRegex(CaseError, "conflicting verified"):
            review_unsegmented(case)

    def test_bad_segment_count_cannot_create_partial_trusted_anchor(self):
        case = sample()
        case["messages"][0]["codes"] = ["101", "108"]
        # Existing independently aligned plaintext must cover every code.
        with self.assertRaisesRegex(CaseError, "segment count"):
            review_unsegmented(case)

    def test_actual_synthetic_unsegmented_crib_and_no_oracle_loaded(self):
        case = load_case(ROOT / "benchmarks/cases/05_unaligned_crib.json")
        original = deepcopy(case)
        r = review_unsegmented(case, top_n=4)
        self.assertEqual(case, original)
        self.assertEqual(r["trusted_anchor_count_unchanged"], 0)
        self.assertEqual(r["unaligned_pair_count"], 1)
        self.assertEqual(r["reviews"][0]["message_id"], "L01")
        self.assertTrue(r["reviews"][0]["candidates"])
        self.assertTrue(all("".join(x["segments"]) ==
                            "奉令補給車隊明日凌晨準時出發"
                            for x in r["reviews"][0]["candidates"]))
        self.assertEqual(anchors_and_review(case)[0], {})

    def test_long_text_many_codes_stays_bounded(self):
        text = "兵力" * 75
        tokens = [f"{i:03}" for i in range(75)]
        result = suggest_alignments(text, tokens, {"兵力"}, {},
                                    top_n=3, beam_width=40)
        self.assertEqual(result["status"], "manual_confirmation_required")
        self.assertLess(result["expanded_states"], 2_000_001)
        self.assertEqual(len(result["candidates"][0]["segments"]), 75)
        self.assertEqual("".join(result["candidates"][0]["segments"]), text)

    def test_too_few_chars_or_impossible_forced_phrase_returns_no_candidates(self):
        empty = suggest_alignments("甲", ["001", "002"], {"甲"}, {})
        self.assertEqual(empty["status"], "no_feasible_alignment")
        self.assertFalse(empty["candidates"])
        forced = suggest_alignments("甲乙", ["001"], {"甲乙"}, {"001": "完全不同"})
        self.assertEqual(forced["status"], "no_feasible_alignment")
        self.assertEqual(forced["candidates"], [])

    def test_validation_rejects_oracle_and_invalid_input(self):
        case = sample()
        for forbidden in ("gold", "ground_truth", "codebook"):
            copied = deepcopy(case)
            copied[forbidden] = {"101": "補給"}
            with self.assertRaisesRegex(CaseError, "oracle"):
                review_unsegmented(copied)
        for options in ({"top_n": 0}, {"top_n": True}, {"beam_width": 1},
                        {"beam_width": 257}, {"beam_width": "96"}):
            with self.subTest(options=options), self.assertRaises(CaseError):
                review_unsegmented(case, **options)
        with self.assertRaisesRegex(CaseError, "1..500"):
            suggest_alignments("甲" * 501, ["001"], {"甲"}, {})
        with self.assertRaises(CaseError):
            suggest_alignments("甲乙", ["nonnumeric"], {"甲"}, {})

    def test_cli_serializes_offline_results_and_reports_errors(self):
        with TemporaryDirectory() as td:
            inp, out = Path(td) / "case.json", Path(td) / "alignment.json"
            data = sample()
            inp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(main(["--case", str(inp), "--out", str(out),
                                   "--top-n", "3", "--beam-width", "24"]), 0)
            saved = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(saved["reviews"][0]["candidates"][0]["segments"],
                             ["補給", "車隊", "出發"])
            self.assertEqual(saved["review_required"], True)
            out.unlink()
            data["ground_truth"] = {"101": "補給"}
            inp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(main(["--case", str(inp), "--out", str(out)]), 2)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
