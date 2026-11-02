"""Synthetic, offline regression for multi-round code coverage and state."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from han_codebook.agent import run_agent


def case_with_unknowns(count=27):
    return {
        "case_id": "fictional-coverage",
        "profiles": {"neutral": {"lexicon": {"甲": 2, "乙": 1},
                                 "sentences": [["甲", "乙"]]}},
        "messages": [{"id": "m", "codes": [str(x) for x in range(100, 100 + count)]}],
        "known_pairs": [],
    }


def synthetic_solver(case, **kwargs):
    proposals = {}
    for message in case["messages"]:
        for code in message["codes"]:
            proposals[code] = {
                "term": "甲", "status": "hypothesis_unverified",
                "alternatives": [{"term": "甲"}, {"term": "乙"}]
            }
    return {"proposals": proposals, "verified_anchors": {}, "objective_score": 1.0}


class RoundStateCoverageTests(unittest.TestCase):
    def test_twenty_seven_unknown_codes_get_fair_coverage_in_two_rounds(self):
        case = case_with_unknowns()
        before = deepcopy(case)
        packets = []
        def code_reply(_url, _model, packet, **kwargs):
            packets.append(deepcopy(packet))
            return {"hypotheses": [
                {"code": code, "candidates": ["甲"], "reason": "unverified"}
                for code in packet["unresolved"]
            ]}
        with TemporaryDirectory() as td:
            with patch("han_codebook.agent.analyze", side_effect=synthetic_solver), \
                 patch("han_codebook.agent.query_local_llm", side_effect=code_reply):
                result = run_agent(
                    case, rounds=3, llm_url="http://127.0.0.1:11434",
                    db_path=str(Path(td) / "audit.sqlite"), solver_iterations=1,
                    solver_restarts=1)
            with sqlite3.connect(Path(td) / "audit.sqlite") as db:
                selected = [json.loads(v) for (v,) in db.execute(
                    "SELECT payload_json FROM events "
                    "WHERE stage='round_code_selection' ORDER BY id")]
                summaries = [json.loads(v) for (v,) in db.execute(
                    "SELECT payload_json FROM events "
                    "WHERE stage='llm_proposals_unverified' ORDER BY id")]
        self.assertEqual(case, before)
        self.assertEqual([len(p["unresolved"]) for p in packets], [15, 15, 15])
        all_codes = set(str(x) for x in range(100, 127))
        self.assertEqual(set(packets[0]["unresolved"]) |
                         set(packets[1]["unresolved"]), all_codes)
        self.assertEqual(len(set(packets[0]["unresolved"]) &
                             set(packets[1]["unresolved"])), 3)
        self.assertEqual(selected[0]["unasked_codes"],
                         sorted(all_codes - set(packets[0]["unresolved"])))
        self.assertEqual(selected[1]["unasked_codes"], [])
        self.assertEqual(result["round_progress_summary"][0]["unasked_code_count"], 12)
        self.assertEqual(result["round_progress_summary"][1]["unasked_code_count"], 0)
        self.assertGreater(summaries[1]["repeated_hint_pairs"], 0)
        self.assertEqual(result["verified_anchors"], {})

    def test_repeated_proposals_are_not_independent_evidence(self):
        case = case_with_unknowns(1)
        requests = []
        weights = []
        def solver(payload, **kwargs):
            weights.append(deepcopy(kwargs.get("llm_hints", {})))
            return synthetic_solver(payload, **kwargs)
        def reply(_url, _model, packet, **kwargs):
            requests.append(deepcopy(packet))
            return {"hypotheses": [
                {"code": "100", "candidates": ["甲", "甲"], "reason": "repeated"}]}
        with TemporaryDirectory() as td:
            with patch("han_codebook.agent.analyze", side_effect=solver), \
                 patch("han_codebook.agent.query_local_llm", side_effect=reply):
                result = run_agent(case, rounds=3, model="offline-mock",
                                   db_path=str(Path(td) / "audit.sqlite"),
                                   solver_iterations=1, solver_restarts=1)
        self.assertEqual(weights[-1]["100"]["甲"], 0.25)
        self.assertEqual(len(requests), 3)
        self.assertEqual(requests[1]["round_context"]["round"], 2)
        self.assertEqual(requests[1]["round_context"]
                         ["prior_llm_hypotheses_unverified"][0]["candidates"], ["甲"])
        self.assertEqual([x["fresh_hint_pairs"] for x in result["round_progress_summary"]],
                         [1, 0, 0])
        self.assertEqual([x["repeated_hint_pairs"] for x in result["round_progress_summary"]],
                         [0, 1, 1])
        self.assertEqual(result["agent_rounds_completed"], 3)

    def test_adaptive_vocab_preserves_previous_hints_during_rescore(self):
        case = case_with_unknowns(1)
        observed = []
        def solver(payload, **kwargs):
            observed.append(deepcopy(kwargs.get("llm_hints", {})))
            return synthetic_solver(payload, **kwargs)
        def vocab(_url, _model, packet, **kwargs):
            return {"vocabulary": [{"term": "第" + str(packet["round"]) + "詞",
                                    "reason": "unverified context",
                                    "evidence_message_ids":[packet["messages"][0]["id"]]}]}
        def code(_url, _model, packet, **kwargs):
            return {"hypotheses": [{"code": "100", "candidates": ["甲"]}]}
        with TemporaryDirectory() as td:
            with patch("han_codebook.agent.analyze", side_effect=solver), \
                 patch("han_codebook.agent.query_local_llm", side_effect=code):
                run_agent(case, rounds=2, db_path=str(Path(td) / "audit.sqlite"),
                          adaptive_vocabulary=True, vocabulary_query=vocab,
                          solver_iterations=1, solver_restarts=1)
        # Initial baseline; vocab1 before code1; code1; vocab2 before code2; code2.
        self.assertEqual(len(observed), 5)
        self.assertEqual(observed[0], {})
        self.assertEqual(observed[1], {})
        self.assertEqual(observed[2]["100"]["甲"], 0.25)
        self.assertEqual(observed[3]["100"]["甲"], 0.25)
        self.assertEqual(observed[4]["100"]["甲"], 0.25)


if __name__ == "__main__":
    unittest.main()
