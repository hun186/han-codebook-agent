"""Zero-adoption vocabulary cost guard: code inference must still run."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from han_codebook.adaptive_vocabulary import vocabulary_packet
from han_codebook.agent import run_agent
from han_codebook.core import CaseError


def case():
    return {"case_id": "fictional-vocab-cost",
            "profiles": {"neutral": {"keywords": [], "lexicon": {"甲": 1}}},
            "messages": [{"id": "m", "codes": ["100"]}],
            "known_pairs": []}


def solver(_case, **kwargs):
    return {"proposals": {
        "100": {"term": "甲", "status": "hypothesis_unverified",
                "alternatives": [{"term": "甲"}]}},
        "verified_anchors": {}, "objective_score": 0.0}


class AutoVocabCostTests(unittest.TestCase):
    def test_zero_yield_skips_only_vocab_not_code_rounds(self):
        original = case()
        preserved = deepcopy(original)
        vocab_calls = []
        code_calls = []
        def vocab(_url, _model, packet, **_kwargs):
            vocab_calls.append(packet["round"])
            return {"vocabulary": []}
        def code(_url, _model, packet, **_kwargs):
            code_calls.append(packet["round_context"]["round"])
            return {"hypotheses": []}
        with TemporaryDirectory() as td:
            db = Path(td)/"audit.sqlite"
            with patch("han_codebook.agent.analyze", side_effect=solver), \
                 patch("han_codebook.agent.query_local_llm", side_effect=code):
                result = run_agent(original, rounds=5, adaptive_vocabulary=True,
                                   vocabulary_query=vocab,
                                   db_path=str(db), vocab_zero_patience=2)
            with sqlite3.connect(db) as conn:
                skips = [json.loads(row[0]) for row in conn.execute(
                    "SELECT payload_json FROM events "
                    "WHERE stage='vocabulary_generation_skipped' ORDER BY id")]
        self.assertEqual(original, preserved)
        self.assertEqual(vocab_calls, [1, 2])
        self.assertEqual(code_calls, [1, 2, 3, 4, 5])
        self.assertEqual(result["agent_rounds_completed"], 5)
        self.assertEqual(result["vocabulary_generation_policy"]["vocabulary_llm_calls"], 2)
        self.assertEqual(result["vocabulary_generation_policy"]["vocabulary_skipped_rounds"], [3, 4, 5])
        self.assertEqual(len(skips), 3)
        self.assertTrue(all(x["code_inference_continues"] for x in skips))
        self.assertTrue(all(x["no_accuracy_oracle"] for x in skips))

    def test_accepted_new_word_resets_zero_streak(self):
        vocab_calls = []
        code_calls = []
        def vocab(_url, _model, packet, **_kwargs):
            r = packet["round"]
            vocab_calls.append(r)
            if r == 2:
                hint = packet["output_contract"]["illustrative_existing_code_only"]
                return {"vocabulary": [{
                    "term": "乙", "reason": "不足以解釋可核對的電文脈絡",
                    "target_code": hint["target_code"],
                    "contrasted_candidate": hint["contrasted_candidate"],
                    "evidence_message_ids": hint["evidence_message_ids"],
                    "contrast_reason": "與原候選可能存在衝突",
                }]}
            return {"vocabulary": []}
        def code(_url, _model, packet, **_kwargs):
            code_calls.append(packet["round_context"]["round"])
            return {"hypotheses": []}
        with TemporaryDirectory() as td:
            with patch("han_codebook.agent.analyze", side_effect=solver), \
                 patch("han_codebook.agent.query_local_llm", side_effect=code):
                result = run_agent(case(), rounds=5, adaptive_vocabulary=True,
                                   vocabulary_query=vocab, vocab_zero_patience=2,
                                   db_path=str(Path(td)/"audit.sqlite"))
        self.assertEqual(vocab_calls, [1, 2, 3, 4])
        self.assertEqual(code_calls, [1, 2, 3, 4, 5])
        self.assertEqual(result["vocabulary_generation_policy"]["vocabulary_skipped_rounds"], [5])
        self.assertIn("乙", result["dynamic_vocabulary_terms"])

    def test_human_review_does_not_auto_skip_or_verify_guesses(self):
        vocab_calls = []
        def vocab(_url, _model, packet, **_kwargs):
            vocab_calls.append(packet["round"])
            return {"vocabulary": []}
        with TemporaryDirectory() as td:
            with patch("han_codebook.agent.analyze", side_effect=solver), \
                 patch("han_codebook.agent.query_local_llm",
                       return_value={"hypotheses": []}):
                result = run_agent(
                    case(), rounds=4, adaptive_vocabulary=True,
                    vocabulary_reviewer=lambda _round, _proposals: [],
                    vocabulary_query=vocab, vocab_zero_patience=2,
                    db_path=str(Path(td)/"audit.sqlite"))
        self.assertEqual(vocab_calls, [1, 2, 3, 4])
        self.assertTrue(result["vocabulary_generation_policy"]["human_review_never_auto_skipped"])
        self.assertEqual(result["vocabulary_generation_policy"]["vocabulary_skipped_rounds"], [])
        self.assertEqual(result["verified_anchors"], {})

    def test_schema_example_matches_actual_unverified_code_and_source(self):
        current = solver(case())
        packet = vocabulary_packet(case(), round_number=2, metadata=False,
                                   current=current, vocabulary={"甲"})
        example = packet["output_contract"]["illustrative_existing_code_only"]
        self.assertEqual(example["target_code"], "100")
        self.assertEqual(example["contrasted_candidate"], "甲")
        self.assertEqual(example["evidence_message_ids"], ["m"])
        self.assertEqual(len(packet["output_contract"]
                             ["required_fields_for_automatic_adoption_with_prior_mapping"]), 6)

    def test_invalid_patience_rejected_before_network(self):
        for invalid in (True, False, -1, 21, "2", 2.0):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(CaseError, "vocab_zero_patience"):
                    run_agent(case(), rounds=0, vocab_zero_patience=invalid)


if __name__ == "__main__":
    unittest.main()
