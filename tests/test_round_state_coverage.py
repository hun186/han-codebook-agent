"""Synthetic, offline regression for multi-round code coverage and state."""
from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from docx import Document

from han_codebook.agent import run_agent
from han_codebook.report import investigation_report
from han_codebook.report_docx import investigation_docx


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

    def test_direct_llm_request_coverage_is_counted_not_confused_with_accuracy(self):
        case = case_with_unknowns(27)
        original = deepcopy(case)
        packets = []

        def no_code_answers(_url, _model, packet, **kwargs):
            packets.append(deepcopy(packet))
            return {"hypotheses": []}

        with TemporaryDirectory() as td:
            with patch("han_codebook.agent.analyze", side_effect=synthetic_solver), \
                 patch("han_codebook.agent.query_local_llm",
                       side_effect=no_code_answers):
                result = run_agent(
                    case, rounds=1, db_path=str(Path(td) / "audit.sqlite"),
                    solver_iterations=1, solver_restarts=1)
        self.assertEqual(case, original)
        self.assertEqual(len(packets), 1)
        self.assertEqual(len(packets[0]["unresolved"]), 15)
        self.assertEqual(result["code_llm_coverage"], {
            "unverified_code_count": 27,
            "queried_distinct_code_count": 15,
            "not_queried_code_count": 12,
            "per_round_target_cap": 15,
            "code_requests_only": True,
            "accuracy_measure": False,
        })
        self.assertEqual(result["round_progress_summary"][0]["unasked_code_count"], 12)
        report_result = {
            **result,
            "case_id": case["case_id"],
            "decoded_messages": [],
            "metadata_used": False,
        }
        md = investigation_report(report_result, [])
        self.assertIn("至少曾送交 LLM：15 組", md)
        self.assertIn("從未作為 LLM 目標：12 組", md)
        self.assertIn("不是破解正確率", md)
        doc = Document(BytesIO(investigation_docx(report_result, [])))
        word_text = "\\n".join(
            [p.text for p in doc.paragraphs]
            + [cell.text for table in doc.tables for row in table.rows
               for cell in row.cells]
        )
        self.assertIn("至少曾被送交 LLM 的不同碼組", word_text)
        self.assertIn("從未作為 LLM 目標的碼組", word_text)
        self.assertIn("12", word_text)
        self.assertIn("15", word_text)

    def test_offline_round_zero_has_no_direct_code_requests(self):
        case = case_with_unknowns(27)
        with TemporaryDirectory() as td:
            with patch("han_codebook.agent.analyze", side_effect=synthetic_solver), \
                 patch("han_codebook.agent.query_local_llm",
                       side_effect=AssertionError("unexpected paid call")):
                result = run_agent(
                    case, rounds=0, db_path=str(Path(td) / "audit.sqlite"),
                    solver_iterations=1, solver_restarts=1)
        self.assertEqual(result["code_llm_coverage"]["queried_distinct_code_count"], 0)
        self.assertEqual(result["code_llm_coverage"]["not_queried_code_count"], 27)
        self.assertEqual(result["code_llm_message_context"]["code_level_rounds"], [])

    def test_report_counts_actual_main_message_sample_not_all_evidence(self):
        case = case_with_unknowns(27)
        case["messages"] = [
            {"id": f"m{i:04d}", "codes": [str(100 + i % 27)]}
            for i in range(120)
        ]
        original = deepcopy(case)
        packets = []

        def no_answers(_url, _model, packet, **kwargs):
            packets.append(deepcopy(packet))
            return {"hypotheses": []}

        with TemporaryDirectory() as td:
            with patch("han_codebook.agent.analyze", side_effect=synthetic_solver), \
                 patch("han_codebook.agent.query_local_llm", side_effect=no_answers):
                result = run_agent(
                    case, rounds=1, db_path=str(Path(td) / "audit.sqlite"),
                    solver_iterations=1, solver_restarts=1)
        self.assertEqual(case, original)
        self.assertEqual(len(packets), 1)
        self.assertEqual(len(packets[0]["messages"]), 100)
        self.assertEqual(packets[0]["corpus_context_sampling"]["total_messages"], 120)
        self.assertIn("m0119", [m["id"] for m in packets[0]["messages"]])
        sample = result["code_llm_message_context"]
        self.assertEqual(sample["total_case_messages"], 120)
        self.assertEqual(sample["per_round_main_message_cap"], 100)
        self.assertEqual(sample["code_level_rounds"],
                         [{"round": 1, "sampled_main_messages": 100}])
        self.assertTrue(sample["other_cross_message_context_possible"])
        self.assertEqual(result["round_progress_summary"][0]["sampled_main_message_count"], 100)
        report_result = {
            **result, "case_id": case["case_id"],
            "decoded_messages": [], "metadata_used": False,
        }
        md = investigation_report(report_result, [])
        self.assertIn("主訊息清單抽樣 100／120 封", md)
        self.assertIn("跨電文片段", md)
        doc = Document(BytesIO(investigation_docx(report_result, [])))
        doc_text = "\n".join(
            [paragraph.text for paragraph in doc.paragraphs]
            + [cell.text for table in doc.tables for row in table.rows for cell in row.cells]
        )
        self.assertIn("100／120", doc_text)
        self.assertIn("動態詞彙階段", doc_text)

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
                                    "evidence_message_ids":[packet["messages"][0]["id"]],
                                    "target_code":"100",
                                    "contrasted_candidate":packet["current_hypotheses_unverified"][0]["candidate"],
                                    "contrast_reason":"此候選缺少跨電文解釋"}]}
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
        # Traceable new terms now enter as weak, unverified hints BEFORE the
        # code LLM request; each round preserves older hints and code opinions.
        self.assertEqual(observed[1], {"100": {"第1詞": 0.15}})
        self.assertEqual(observed[2]["100"], {"第1詞": 0.15, "甲": 0.25})
        self.assertEqual(observed[3]["100"],
                         {"第1詞": 0.15, "第2詞": 0.15, "甲": 0.25})
        self.assertEqual(observed[4]["100"], observed[3]["100"])


if __name__ == "__main__":
    unittest.main()
