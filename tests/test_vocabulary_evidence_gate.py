"""Evidence-pointer gate for bounded automatic LLM vocabulary adoption."""
from __future__ import annotations

from copy import deepcopy
import unittest

from han_codebook.adaptive_vocabulary import refresh_vocabulary


def case():
    return {
        "case_id": "fictional-evidence-gate",
        "profiles": {"neutral": {"lexicon": {"既有詞": 2},
                                 "sentences": [["原有例句詞"]]}},
        "messages": [{"id": "m1", "codes": ["101", "102"]},
                     {"id": "m2", "codes": ["101", "103"]}],
        "known_pairs": [],
    }


def settings():
    return {"base_url": "http://127.0.0.1:11434",
            "model": "local-test-mock", "timeout_seconds": 10}


class AutoVocabularyEvidenceGateTests(unittest.TestCase):
    def test_automatic_adopts_only_supported_traceable_terms(self):
        src = case()
        original = deepcopy(src)
        proposals = [
            {"term": "可追溯詞", "reason": "電文m1的語境推測",
             "evidence_message_ids": ["m1"]},
            {"term": "無電文來源", "reason": "看起來常見"},
            {"term": "偽造來源", "reason": "似乎相關",
             "evidence_message_ids": ["does-not-exist"]},
            {"term": "重複來源", "reason": "似乎相關",
             "evidence_message_ids": ["m1", "m1"]},
            {"term": "無解釋", "reason": "", "evidence_message_ids": ["m2"]},
            {"term": "錯誤型別", "reason": "引用無效",
             "evidence_message_ids": [23]},
            {"term": "原有例句詞", "reason": "詞已存在",
             "evidence_message_ids": ["m1"]},
        ]
        def response(_url, _model, packet, **_kwargs):
            self.assertEqual(packet["task"], "generate_vocabulary")
            self.assertNotIn("gold", packet)
            return {"vocabulary": proposals}
        updated, record = refresh_vocabulary(
            src, round_number=1, metadata=False, current=None,
            llm_settings=settings(), query=response)
        self.assertEqual(src, original)
        self.assertEqual(record["review_mode"], "automatic")
        self.assertTrue(record["automatic_evidence_gate"])
        self.assertEqual(record["approved"], ["可追溯詞"])
        self.assertEqual(record["untraceable_proposed_count"], 5)
        self.assertEqual(record["rejected_count"], 5)
        self.assertEqual(record["total_dynamic_terms"], 1)
        self.assertEqual(
            updated["profiles"]["llm_dynamic_candidates"]["lexicon"],
            {"可追溯詞": 1.0})
        self.assertNotIn("偽造來源",
                         updated["profiles"]["llm_dynamic_candidates"]["lexicon"])
        self.assertEqual(record["proposed"][0]["evidence_message_ids"], ["m1"])
        self.assertFalse(record["proposed"][1]["context_reference_traceable"])

    def test_bounded_auto_budget_and_explicit_human_override(self):
        src = case()
        valid = [
            {"term": "新詞" + str(i), "reason": "電文可供查核",
             "evidence_message_ids": ["m1"]}
            for i in range(12)
        ]
        def query(_url, _model, packet, **_kwargs):
            return {"vocabulary": valid}
        updated, record = refresh_vocabulary(
            src, round_number=1, metadata=True, current=None,
            llm_settings=settings(), query=query)
        self.assertEqual(len(record["approved"]), 8)
        self.assertEqual(record["auto_per_round_limit"], 8)
        self.assertEqual(record["rejected_count"], 4)
        self.assertEqual(len(updated["profiles"]["llm_dynamic_candidates"]["lexicon"]), 8)

        def unsupported(_url, _model, packet, **_kwargs):
            return {"vocabulary": [{"term": "人工評估候選",
                                    "reason": "僅由模型猜想"}]}
        updated, manual = refresh_vocabulary(
            src, round_number=1, metadata=False, current=None,
            llm_settings=settings(), query=unsupported,
            review=lambda _round, _items: ["人工評估候選"])
        self.assertFalse(manual["automatic_evidence_gate"])
        self.assertEqual(manual["approved"], ["人工評估候選"])
        self.assertEqual(manual["untraceable_proposed_count"], 1)
        self.assertEqual(src, case())
        self.assertIn("人工評估候選",
                      updated["profiles"]["llm_dynamic_candidates"]["lexicon"])


if __name__ == "__main__":
    unittest.main()
