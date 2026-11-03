"""A cold vocabulary start cannot contrast a candidate that does not exist."""
from __future__ import annotations
import json
import unittest
from unittest.mock import patch

from han_codebook.adaptive_vocabulary import vocabulary_packet
from han_codebook.agent import query_local_llm


class FakeResponse:
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def read(self, _): return json.dumps({
        "choices": [{"message": {"content": '{"vocabulary":[],"patterns":[]}'}}],
        "usage": {},
    }).encode("utf-8")


class VocabularyBootstrapPromptTests(unittest.TestCase):
    def check_prompt(self, packet):
        requests = []
        with patch("han_codebook.agent.request.urlopen", return_value=FakeResponse()):
            result = query_local_llm(
                "http://localhost:11434", "MOCK", packet,
                on_exchange=lambda stage, payload: requests.append((stage, payload)))
        self.assertEqual(result["vocabulary"], [])
        return requests[0][1]["body"]["messages"][0]["content"]

    def test_empty_candidate_bootstrap_never_demands_old_mapping(self):
        case = {"case_id": "fictional",
                "profiles": {"neutral": {"lexicon": {}}},
                "messages": [{"id": "M", "codes": ["142"]}],
                "known_pairs": []}
        packet = vocabulary_packet(
            case, round_number=1, metadata=False,
            current=None, vocabulary=set())
        self.assertIsNone(packet["output_contract"]["illustrative_existing_code_only"])
        prompt = self.check_prompt(packet)
        self.assertIn("空詞庫啟動", prompt)
        self.assertIn("不要求 target_code", prompt)
        self.assertNotIn("output_contract.illustrative_existing_code_only", prompt)

    def test_independent_vocabulary_generator_needs_no_contract(self):
        prompt = self.check_prompt({
            "task": "generate_vocabulary",
            "messages": [{"id": "M", "codes": ["142"]}],
        })
        self.assertIn("獨立詞彙蒐集", prompt)
        self.assertIn("vocabulary", prompt)
        self.assertNotIn("必須附 target_code", prompt)

    def test_existing_candidate_requires_full_traceable_contract(self):
        case = {"case_id": "fictional",
                "profiles": {"neutral": {"lexicon": {"甲": 1}}},
                "messages": [{"id": "M", "codes": ["142"]}],
                "known_pairs": []}
        current = {"proposals": {"142": {
            "term": "甲", "status": "hypothesis_unverified"}}}
        packet = vocabulary_packet(
            case, round_number=2, metadata=False,
            current=current, vocabulary={"甲"})
        prompt = self.check_prompt(packet)
        self.assertIn("contrasted_candidate", prompt)
        self.assertIn("contrast_reason", prompt)
        self.assertIn("output_contract.illustrative_existing_code_only", prompt)
        self.assertEqual(packet["output_contract"]["illustrative_existing_code_only"]
                         ["target_code"], "142")


if __name__ == "__main__":
    unittest.main()
