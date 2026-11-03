"""Source-code contrast gate: reference validity is not semantic correctness."""
from __future__ import annotations
from copy import deepcopy
import unittest

from han_codebook.adaptive_vocabulary import refresh_vocabulary


def case():
    return {"case_id": "fictional-contrast",
            "profiles": {"log": {"keywords": [], "lexicon": {"甲": 1, "乙": 1}}},
            "messages": [{"id": "A", "codes": ["100", "200"]},
                         {"id": "B", "codes": ["200", "101"]}],
            "known_pairs": []}


def previous():
    return {"proposals": {
        "100": {"term": "甲", "status": "hypothesis_unverified"},
        "101": {"term": "乙", "status": "hypothesis_unverified"},
        "200": {"term": "已知錨點", "status": "verified_alignment"},
    }}


def settings():
    return {"base_url": "http://localhost:11434", "model": "fictional-mock"}


class EvidenceContrastGateTests(unittest.TestCase):
    def test_only_exact_unverified_code_and_existing_term_contrast_is_auto_adopted(self):
        src = case()
        before = deepcopy(src)
        proposed = [
            {"term": "有效新候選", "reason": "電文存在",
             "evidence_message_ids": ["A"], "target_code": "100",
             "contrasted_candidate": "甲", "contrast_reason": "既有語句不能解釋附近的可信碼"},
            {"term": "錯誤跨報", "reason": "有引用",
             "evidence_message_ids": ["B"], "target_code": "100",
             "contrasted_candidate": "甲", "contrast_reason": "B沒有碼組100"},
            {"term": "錨點造假", "reason": "有引用",
             "evidence_message_ids": ["A"], "target_code": "200",
             "contrasted_candidate": "已知錨點", "contrast_reason": "不能更動可信錨點"},
            {"term": "舊候選不符", "reason": "有引用",
             "evidence_message_ids": ["A"], "target_code": "100",
             "contrasted_candidate": "乙", "contrast_reason": "引用錯誤的第一順位"},
            {"term": "沒有反證理由", "reason": "有引用",
             "evidence_message_ids": ["A"], "target_code": "100",
             "contrasted_candidate": "甲", "contrast_reason": "   "},
            {"term": "無對比", "reason": "有引用", "evidence_message_ids": ["A"]},
        ]
        updated, record = refresh_vocabulary(
            src, round_number=1, metadata=False, current=previous(),
            llm_settings=settings(), query=lambda *args, **kwargs: {"vocabulary": proposed})
        self.assertEqual(src, before)
        self.assertEqual(record["approved"], ["有效新候選"])
        self.assertEqual(record["untraceable_proposed_count"], 0)
        self.assertEqual(record["missing_existing_candidate_contrast_count"], 5)
        self.assertTrue(record["contrast_required_when_prior_mapping_exists"])
        self.assertEqual(updated["profiles"]["llm_dynamic_candidates"]["lexicon"],
                         {"有效新候選": 1.0})
        self.assertEqual(record["proposed"][0]["target_code"], "100")
        self.assertTrue(record["proposed"][0]["existing_candidate_contrast_traceable"])
        self.assertFalse(record["proposed"][1]["automatic_adoption_eligible"])

    def test_bootstrap_without_solver_and_manual_review_remain_possible(self):
        src = case()
        suggestion = {"term": "來源候選", "reason": "可能詞",
                      "evidence_message_ids": ["A"]}
        updated, record = refresh_vocabulary(
            src, round_number=1, metadata=True, current=None,
            llm_settings=settings(), query=lambda *a, **k: {"vocabulary": [suggestion]})
        self.assertEqual(record["approved"], ["來源候選"])
        self.assertFalse(record["contrast_required_when_prior_mapping_exists"])
        self.assertIn("來源候選", updated["profiles"]["llm_dynamic_candidates"]["lexicon"])
        # Manual reviewer can explicitly accept a hypothesis that lacks the
        # model's structural contrast; this still never verifies its mapping.
        manual, log = refresh_vocabulary(
            src, round_number=1, metadata=True, current=previous(),
            llm_settings=settings(), query=lambda *a, **k: {"vocabulary": [suggestion]},
            review=lambda _, proposals: ["來源候選"])
        self.assertEqual(log["approved"], ["來源候選"])
        self.assertFalse(log["automatic_evidence_gate"])
        self.assertIn("來源候選", manual["profiles"]["llm_dynamic_candidates"]["lexicon"])
        self.assertEqual(src, case())


if __name__ == "__main__":
    unittest.main()
