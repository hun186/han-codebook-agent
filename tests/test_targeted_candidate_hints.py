"""Weak code-specific dynamic-vocabulary proposals stay unverified."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from han_codebook.adaptive_vocabulary import link_adopted_targeted_hints
from han_codebook.agent import run_agent


class TargetedCandidateTests(unittest.TestCase):
    def test_validated_eligible_term_links_once_without_touching_anchors(self):
        record = {"approved": ["新詞", "人工詞"], "proposed": [
            {"term": "新詞", "target_code": "222",
             "existing_candidate_contrast_traceable": True,
             "context_reference_traceable": True, "automatic_adoption_eligible": True},
            {"term": "人工詞", "target_code": "333",
             "existing_candidate_contrast_traceable": False,
             "context_reference_traceable": True, "automatic_adoption_eligible": False},
            {"term": "新詞", "target_code": "111",
             "existing_candidate_contrast_traceable": True,
             "context_reference_traceable": True, "automatic_adoption_eligible": True},
        ]}
        anchors = {"111": "已驗證"}
        original = dict(anchors)
        hints = {}
        seen = set()
        self.assertEqual(link_adopted_targeted_hints(record, trusted_anchors=anchors,
                         hints=hints, seen_pairs=seen), 1)
        self.assertEqual(hints, {"222": {"新詞": 0.15}})
        self.assertEqual(link_adopted_targeted_hints(record, trusted_anchors=anchors,
                         hints=hints, seen_pairs=seen), 0)
        self.assertEqual(anchors, original)

    def test_one_round_mocked_vocabulary_populates_auditable_weak_hint(self):
        case = {
            "case_id": "fictional-targeted",
            "profiles": {"general": {"keywords": [],
                                      "lexicon": {"舊詞": 1.0}, "sentences": []}},
            "messages": [{"id": "M1", "codes": ["111", "222"]}],
            "known_pairs": [],
        }

        def vocab_query(base, model, packet, **kwargs):
            proposal = next(p for p in packet["current_hypotheses_unverified"]
                            if p["code"] == "111")
            return {"vocabulary": [{
                "term": "新詞", "reason": "需從多則電文查證",
                "evidence_message_ids": ["M1"], "target_code": "111",
                "contrasted_candidate": proposal["candidate"],
                "contrast_reason": "暫時不符合相鄰密文的假說",
            }]}

        def code_query(*args, **kwargs):
            return {"hypotheses": []}

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "audit.sqlite"
            with patch("han_codebook.agent.query_local_llm", side_effect=code_query):
                result = run_agent(case, rounds=1, adaptive_vocabulary=True,
                                   vocabulary_query=vocab_query,
                                   llm_url="http://127.0.0.1:11434/v1",
                                   db_path=str(path), solver_iterations=1,
                                   solver_restarts=1)
            self.assertEqual(result["agent_rounds_completed"], 1)
            self.assertEqual(result["targeted_vocabulary_hint_pairs"], 1)
            self.assertEqual(result["verified_anchors"], {})
            self.assertEqual(result["proposals"]["111"]["status"],
                             "hypothesis_unverified")
            with sqlite3.connect(path) as conn:
                data = conn.execute(
                    "SELECT payload_json FROM events WHERE stage=?",
                    ("vocabulary_candidates_unverified",)
                ).fetchone()[0]
            self.assertEqual(json.loads(data)["targeted_code_hint_count"], 1)
            # Input remains free of model-generated mapping or Gold.
            self.assertEqual(case["profiles"]["general"]["lexicon"], {"舊詞": 1.0})
            self.assertNotIn("ground_truth", str(result))


if __name__ == "__main__":
    unittest.main()
