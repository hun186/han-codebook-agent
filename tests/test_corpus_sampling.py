"""Target-diverse full-corpus sampling never consults Gold or expands billable calls."""
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from han_codebook.adaptive_vocabulary import vocabulary_packet
from han_codebook.agent import run_agent
from han_codebook.corpus_sampling import sample_corpus_messages


class FullCorpusContextTests(unittest.TestCase):
    def test_sampling_is_bounded_deterministic_and_reaches_late_messages(self):
        messages = [{"id": f"M{i:04d}", "codes": ["111", str(200+i)]}
                    for i in range(1000)]
        original = deepcopy(messages)
        sampled = sample_corpus_messages(messages, focus_codes=["111"], limit=100)
        self.assertEqual(len(sampled), 100)
        ids = [x["id"] for x in sampled]
        self.assertEqual(len(set(ids)), 100)
        self.assertIn("M0999", ids)
        self.assertTrue(any(int(mid[1:]) > 900 for mid in ids))
        self.assertTrue(any(400 < int(mid[1:]) < 600 for mid in ids))
        self.assertEqual(ids, [x["id"] for x in sample_corpus_messages(
            messages, focus_codes=["111"], limit=100)])
        self.assertEqual(messages, original)
        self.assertEqual(sample_corpus_messages(messages[:25], focus_codes=["111"]), messages[:25])
        for invalid in (0, 101, True, 2.4):
            with self.assertRaises(ValueError):
                sample_corpus_messages(messages, focus_codes=[], limit=invalid)

    def test_adaptive_packet_samples_late_corpus_without_gold(self):
        messages = [{"id": f"M{i:04d}", "codes": ["111"],
                     "sender": "A", "ground_truth": {"111": "秘密"}}
                    for i in range(120)]
        case = {
            "case_id": "fictional-wide",
            "messages": messages,
            "profiles": {"general": {"keywords": [],
                                      "lexicon": {"舊詞": 1}, "sentences": []}},
            "known_pairs": [],
        }
        packet = vocabulary_packet(case, round_number=1, metadata=False,
                                    current=None, vocabulary={"舊詞"})
        self.assertEqual(len(packet["messages"]), 100)
        self.assertEqual(packet["corpus_context_sampling"]["total_messages"], 120)
        self.assertIn("M0119", [m["id"] for m in packet["messages"]])
        self.assertNotIn("ground_truth", str(packet))
        self.assertTrue(all("sender" not in m for m in packet["messages"]))

    def test_one_round_mocked_code_inference_reads_late_case_evidence(self):
        case = {
            "case_id": "fictional-wide",
            "profiles": {"general": {"keywords": [],
                                      "lexicon": {"舊詞": 1}, "sentences": []}},
            "messages": [
                {"id": f"M{i:04d}", "codes": ["111"],
                 "sender": "A", "notes": "ordinary", "ground_truth": {"111": "秘密"}}
                for i in range(120)
            ],
            "known_pairs": [],
        }
        sent = []
        def fake(_url, _model, packet, **kwargs):
            sent.append(deepcopy(packet))
            return {"hypotheses": []}
        with tempfile.TemporaryDirectory() as td:
            with patch("han_codebook.agent.query_local_llm", side_effect=fake):
                result = run_agent(case, rounds=1, metadata=False,
                                   db_path=str(Path(td) / "audit.sqlite"),
                                   solver_iterations=1, solver_restarts=1)
        self.assertEqual(result["agent_rounds_completed"], 1)
        self.assertEqual(len(sent), 1)
        self.assertEqual(len(sent[0]["messages"]), 100)
        self.assertIn("M0119", [m["id"] for m in sent[0]["messages"]])
        self.assertTrue(all("sender" not in m and "notes" not in m
                            for m in sent[0]["messages"]))
        self.assertNotIn("ground_truth", str(sent[0]))


if __name__ == "__main__":
    unittest.main()
