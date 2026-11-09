"""Confidence-free presentation guard: no gold or network is consulted."""
import copy
import unittest

from han_codebook.core import analyze
from han_codebook.hypothesis_quality import mark_presentation_uncertainty


class UncertaintyPresentationTests(unittest.TestCase):
    def test_heuristic_keeps_proposals_and_trusted_mappings(self):
        proposals = {
            "101": {"term": "可信", "status": "verified_alignment", "alternatives": []},
            **{
                str(200 + i): {
                    "term": "中央站", "status": "hypothesis_unverified",
                    "score_gap_to_second": 0.0,
                    "alternatives": [{"term": "中央站"}, {"term": "前往現場"}],
                }
                for i in range(12)
            },
        }
        original = copy.deepcopy(proposals)
        metrics = mark_presentation_uncertainty(proposals, vocabulary_size=2)
        self.assertEqual(metrics["unknown_codes"], 12)
        self.assertEqual(metrics["presentation_abstained_code_count"], 12)
        self.assertTrue(metrics["concentrated_mapping_warning"])
        self.assertEqual(proposals["101"], original["101"])
        for code in original:
            self.assertEqual(proposals[code]["term"], original[code]["term"])
            self.assertEqual(proposals[code]["alternatives"], original[code]["alternatives"])
            self.assertEqual(proposals[code]["status"], original[code]["status"])

    def test_no_unknowns_does_not_claim_accuracy(self):
        rows = {"001": {"term": "可靠詞", "status": "verified_alignment"}}
        metrics = mark_presentation_uncertainty(rows, 0)
        self.assertIsNone(metrics["dominant_unverified_term_fraction"])
        self.assertFalse(metrics["concentrated_mapping_warning"])
        self.assertNotIn("presentation_abstained", rows["001"])

    def test_cautious_reading_does_not_overwrite_raw_guess(self):
        case = {
            "case_id": "fictional-collapse",
            "profiles": {"general": {"keywords": [], "lexicon": {"甲站": 1, "乙站": 1}, "sentences": []}},
            "messages": [
                {"id": "F%02d" % i, "codes": [str(200+i)]}
                for i in range(12)
            ],
            "known_pairs": [],
        }
        result = analyze(case, iterations=1, restarts=1)
        self.assertEqual(result["unknown_code_count"], 12)
        self.assertGreater(result["hypothesis_quality"]["presentation_abstained_code_count"], 0)
        self.assertTrue(any(":待判]" in m["cautious_reading"] for m in result["decoded_messages"]))
        self.assertTrue(all(m["reading"] == "".join(m["suggested_segments"])
                            for m in result["decoded_messages"]))
        self.assertTrue(all(p["status"] == "hypothesis_unverified"
                            for p in result["proposals"].values()))


if __name__ == "__main__":
    unittest.main()
