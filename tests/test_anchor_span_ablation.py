"""Non-oracle structural context: two-hop anchor evidence remains opt-in."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from han_codebook.anchor_span import two_hop_anchor_context
from han_codebook.core import analyze, CaseError
from han_codebook.anchor_span_ablation import compare_anchor_span


def synthetic():
    return {
        "case_id": "fictional-two-hop",
        "profiles": {"neutral": {
            "keywords": [], "lexicon": {"甲": 4, "乙": 4, "丙": 4, "丁": 4},
            "sentences": [["甲", "丙", "乙"], ["甲", "丙", "乙"],
                          ["甲", "丁", "乙"]],
        }},
        "messages": [
            {"id": "known", "codes": ["101", "102"]},
            {"id": "A", "codes": ["101", "200", "142", "201", "102"],
             "notes": "UNTRUSTED_SECRET_NOTE"},
            {"id": "B", "codes": ["101", "202", "142", "203", "102"]},
            {"id": "C", "codes": ["101", "204", "143", "205", "102"]},
        ],
        "known_pairs": [{"message_id": "known", "segments": ["甲", "乙"]}],
    }


class AnchorSpanAblationTests(unittest.TestCase):
    def test_collect_only_aligned_two_hop_anchors_across_distinct_messages(self):
        case = synthetic()
        tagged = [(m, "neutral") for m in case["messages"]]
        original = deepcopy(case)
        context = two_hop_anchor_context(
            tagged, {"101": "甲", "102": "乙"}, ["142", "143", "200"])
        self.assertEqual(context["142"], [
            ("neutral", "left", "甲"), ("neutral", "right", "乙"),
            ("neutral", "left", "甲"), ("neutral", "right", "乙"),
        ])
        self.assertEqual(context["143"], [
            ("neutral", "left", "甲"), ("neutral", "right", "乙"),
        ])
        self.assertNotIn("200", context)  # only immediate neighbor, no 2-hop anchor
        self.assertNotIn("UNTRUSTED_SECRET_NOTE", json.dumps(context))
        self.assertEqual(case, original)

    def test_ordinary_solver_and_anchor_ablations_keep_identical_anchors(self):
        case = synthetic()
        original = deepcopy(case)
        base = analyze(case, iterations=2, restarts=1, anchor_span_weight=0.0)
        alt = analyze(case, iterations=2, restarts=1, anchor_span_weight=0.3)
        self.assertEqual(case, original)
        self.assertEqual(base["verified_anchors"], alt["verified_anchors"])
        self.assertEqual(base["verified_anchors"], {"101": "甲", "102": "乙"})
        self.assertEqual(base["anchor_span_weight"], 0)
        self.assertEqual(base["anchor_span_context_code_count"], 0)
        self.assertEqual(alt["anchor_span_weight"], 0.3)
        self.assertGreater(alt["anchor_span_context_code_count"], 0)
        self.assertGreater(alt["anchor_span_context_records"], 0)
        self.assertEqual(alt["proposals"]["101"]["status"], "verified_alignment")
        self.assertEqual(alt["proposals"]["102"]["status"], "verified_alignment")
        self.assertTrue(all("ground_truth" not in p for p in (base, alt)))

    def test_offline_ablation_does_not_claim_correctness(self):
        case = synthetic()
        report = compare_anchor_span(case, weights=(0.0, 0.3),
                                     iterations=2, restarts=1)
        self.assertEqual(len(report["runs"]), 2)
        self.assertEqual(report["runs"][0]["anchor_span_weight"], 0.0)
        self.assertEqual(report["runs"][1]["anchor_span_weight"], 0.3)
        self.assertTrue(report["no_llm_calls"])
        self.assertTrue(report["no_gold_or_round_winner"])
        self.assertNotIn("accuracy", json.dumps(report).lower())
        self.assertNotIn("UNTRUSTED_SECRET_NOTE", json.dumps(report))
        self.assertEqual(report["runs"][0]["verified_anchor_count"], 2)

    def test_missing_or_invalid_weights_fail_closed(self):
        case = synthetic()
        for bad in (True, False, -0.1, 1.1, float("nan"),
                    float("inf"), "0.3"):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(CaseError, "anchor_span_weight"):
                    analyze(case, iterations=1, restarts=1,
                            anchor_span_weight=bad)

    def test_seven_messages_do_not_overweight_one_code(self):
        case = synthetic()
        messages = [
            {"id": str(i), "codes": ["101", "900", "142", "901", "102"]}
            for i in range(9)
        ]
        context = two_hop_anchor_context(
            [(m, None) for m in messages],
            {"101": "甲", "102": "乙"}, ["142"])
        self.assertEqual(len(context["142"]), 12)  # six messages, two anchor contexts


if __name__ == "__main__":
    unittest.main()
