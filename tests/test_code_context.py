"""Cipher-only cross-message contrast and safe local-model evidence regression."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from han_codebook.code_context import cross_message_context, check_evidence_refs
from han_codebook.agent import run_agent


def fictional_case():
    return {
        "case_id": "synthetic-context-evidence",
        "profiles": {"neutral": {"lexicon": {"補給": 1, "道路": 1, "改行": 1, "北線": 1}}},
        "messages": [
            {"id": "anchor", "codes": ["200"]},
            {"id": "A", "codes": ["101", "100", "200", "101", "100"],
             "sender": "private_sender_MUST_NOT_COPY_IF_METADATA_OFF",
             "ground_truth": {"100": "SECRET_ORACLE"}},
            {"id": "B", "codes": ["200", "100", "101"],
             "notes": "private_notes_MUST_NOT_COPY_IF_METADATA_OFF"},
            {"id": "C", "codes": ["101", "200", "100"]},
        ],
        "known_pairs": [{"message_id": "anchor", "segments": ["補給"]}],
    }


def proposals():
    return {
        "100": {"term": "道路", "status": "hypothesis_unverified",
                "alternatives": [{"term": "道路"}, {"term": "改行"}, {"term": "北線"}]},
        "101": {"term": "改行", "status": "hypothesis_unverified",
                "alternatives": [{"term": "改行"}]},
        "200": {"term": "補給", "status": "verified_alignment", "alternatives": []},
    }


class CodeContextTests(unittest.TestCase):
    def test_distinct_message_windows_and_verified_only(self):
        case = fictional_case()
        original = deepcopy(case)
        context = cross_message_context(
            case, selected=["100", "200"], anchors={"200": "補給"},
            proposals=proposals())
        self.assertEqual(set(context), {"100"})
        row = context["100"]
        self.assertEqual(row["total_occurrences"], 4)
        self.assertEqual([x["message_id"] for x in row["sampled_occurrences"]],
                         ["A", "B", "C", "A"])
        self.assertEqual(row["candidate_comparison"], ["道路", "改行", "北線"])
        self.assertEqual(row["sampled_occurrences"][0]["target_offset"], 1)
        self.assertTrue(all(item.get("verified_term") == "補給"
                            for window in row["sampled_occurrences"]
                            for item in window["sequence"]
                            if item["code"] == "200"))
        self.assertTrue(all("verified_term" not in item
                            for window in row["sampled_occurrences"]
                            for item in window["sequence"]
                            if item["code"] != "200"))
        serial = json.dumps(context, ensure_ascii=False)
        self.assertNotIn("SECRET_ORACLE", serial)
        self.assertNotIn("private_sender", serial)
        self.assertNotIn("private_notes", serial)
        self.assertEqual(case, original)

    def test_refs_only_actual_messages_containing_target(self):
        case = fictional_case()
        self.assertEqual(
            check_evidence_refs("100", ["anchor", "B", "B", None, "C", "fake", "A"],
                                case["messages"]), ["B", "C", "A"])
        self.assertEqual(check_evidence_refs("100", "B", case["messages"]), [])
        self.assertEqual(check_evidence_refs("100", [{"id": "B"}], case["messages"]), [])

    def test_agent_exposes_contrast_no_metadata_oracle_and_validates_references(self):
        case = fictional_case()
        initial = deepcopy(case)
        packets = []
        def mock_solver(_case, **kwargs):
            return {"proposals": deepcopy(proposals()), "objective_score": 1.0,
                    "verified_anchors": {"200": "補給"}}
        def mock_chat(_url, _model, payload, **kwargs):
            packets.append(deepcopy(payload))
            return {"hypotheses": [{
                "code": "100", "candidates": ["改行", "道路"], "reason": "unverified",
                "supporting_message_ids": ["fake", "B", "anchor", "A"],
                "counterexample_message_ids": ["C", "anchor", "C", "fake"],
            }]}
        with TemporaryDirectory() as temp:
            dbpath = Path(temp) / "audit.sqlite"
            with patch("han_codebook.agent.analyze", side_effect=mock_solver), \
                 patch("han_codebook.agent.query_local_llm", side_effect=mock_chat):
                output = run_agent(case, rounds=1, metadata=False,
                                   db_path=str(dbpath),
                                   llm_url="http://127.0.0.1:11434")
            with sqlite3.connect(dbpath) as conn:
                audit = json.loads(conn.execute(
                    "SELECT payload_json FROM events"
                    " WHERE stage='llm_proposals_unverified'").fetchone()[0])
        self.assertEqual(case, initial)
        self.assertEqual(len(packets), 1)
        serialized = json.dumps(packets[0], ensure_ascii=False)
        self.assertNotIn("private_sender", serialized)
        self.assertNotIn("private_notes", serialized)
        self.assertNotIn("SECRET_ORACLE", serialized)
        self.assertIn("cross_message_context", packets[0])
        self.assertEqual(packets[0]["cross_message_context"]["100"]
                         ["candidate_comparison"], ["道路", "改行", "北線"])
        self.assertEqual(audit["accepted"][0]["supporting_message_ids"], ["B", "A"])
        self.assertEqual(audit["accepted"][0]["counterexample_message_ids"], ["C"])
        self.assertEqual(audit["supporting_message_references"], 2)
        self.assertEqual(audit["counterexample_message_references"], 1)
        self.assertTrue(audit["references_are_not_verified"])
        self.assertEqual(output["verified_anchors"], {"200": "補給"})


if __name__ == "__main__":
    unittest.main()
