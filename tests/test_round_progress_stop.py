"""Oracle-free progress/stall diagnosis and explicit opt-in early stop tests."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from han_codebook.agent import run_agent
from han_codebook.core import CaseError
from han_codebook.round_progress import round_progress_diagnosis


def case_with_codes(count=27):
    return {"case_id": "fictional-stall",
            "profiles": {"neutral": {"lexicon": {"甲": 1, "乙": 1}}},
            "messages": [{"id": "synthetic", "codes":
                          [str(i) for i in range(100, 100+count)]}],
            "known_pairs": []}


def stable_solver(case, **kwargs):
    return {"proposals": {
        code: {"term": "甲", "status": "hypothesis_unverified",
               "alternatives": [{"term": "甲"}, {"term": "乙"}]}
        for code in {c for m in case["messages"] for c in m["codes"]}},
        "verified_anchors": {}, "objective_score": 1.0}


class RoundProgressTests(unittest.TestCase):
    def test_no_top1_change_is_not_equivalent_to_no_progress(self):
        prior = stable_solver(case_with_codes(1))
        newer = deepcopy(prior)
        newer["proposals"]["100"]["alternatives"].reverse()
        d = round_progress_diagnosis(
            prior, newer, new_coverage_count=0, fresh_hint_pairs=0,
            accepted_vocabulary_terms=0, stale_rounds=1, stop_patience=2)
        self.assertTrue(d["no_first_choice_change"])
        self.assertEqual(d["top5_ranking_changes"], 1)
        self.assertFalse(d["no_observable_rank_movement"])
        self.assertFalse(d["stop_recommended"])
        self.assertEqual(d["consecutive_stalled_rounds"], 0)

    def test_novel_candidate_without_rank_change_is_not_claimed_accuracy(self):
        base = stable_solver(case_with_codes(1))
        d = round_progress_diagnosis(base, base, new_coverage_count=0,
                                     fresh_hint_pairs=3, accepted_vocabulary_terms=0,
                                     stale_rounds=4, stop_patience=2)
        self.assertTrue(d["new_suggestions_without_rank_movement"])
        self.assertFalse(d["stop_recommended"])
        self.assertIn("NOT correctness", d["quality_note"])

    def test_opt_in_stops_only_after_full_coverage_and_two_empty_rounds(self):
        case = case_with_codes()
        pristine = deepcopy(case)
        packets = []
        def fake_chat(_url, _model, packet, **kwargs):
            packets.append(deepcopy(packet))
            return {"hypotheses": [{
                "code": code, "candidates": ["甲"], "reason": "repeat"}
                for code in packet["unresolved"]]}
        with TemporaryDirectory() as td:
            dbpath = Path(td)/"audit.sqlite"
            with patch("han_codebook.agent.analyze", side_effect=stable_solver), \
                 patch("han_codebook.agent.query_local_llm", side_effect=fake_chat):
                result = run_agent(case, rounds=7, progress_stop_patience=2,
                                   db_path=str(dbpath))
            with sqlite3.connect(dbpath) as conn:
                stops = [json.loads(v) for (v,) in conn.execute(
                    "SELECT payload_json FROM events WHERE stage='round_early_stop'")]
        self.assertEqual(case, pristine)
        self.assertTrue(result["early_stop_triggered"])
        self.assertEqual(result["agent_rounds_requested"], 7)
        self.assertEqual(result["agent_rounds_completed"], 4)
        self.assertEqual(len(packets), 4)
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0]["rounds_completed"], 4)
        self.assertTrue(stops[0]["oracle_not_consulted"])
        self.assertEqual([d["consecutive_stalled_rounds"]
                          for d in result["round_progress_summary"]], [0, 0, 1, 2])
        self.assertEqual(result["round_progress_summary"][0]["new_research_coverage"], 15)
        self.assertEqual(result["round_progress_summary"][1]["new_research_coverage"], 12)
        self.assertTrue(all(d["first_choice_changes"] == 0
                            for d in result["round_progress_summary"]))

    def test_default_does_not_stop_and_invalid_patience_fails_closed(self):
        case = case_with_codes(1)
        with TemporaryDirectory() as td:
            with patch("han_codebook.agent.analyze", side_effect=stable_solver), \
                 patch("han_codebook.agent.query_local_llm",
                       return_value={"hypotheses": []}) as chat:
                result = run_agent(case, rounds=4, db_path=str(Path(td)/"a.sqlite"))
            self.assertEqual(chat.call_count, 4)
        self.assertFalse(result["early_stop_triggered"])
        self.assertEqual(result["agent_rounds_completed"], 4)
        for invalid in (True, False, -1, 1, 21, "2", 2.0):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(CaseError, "progress_stop_patience"):
                    run_agent(case, rounds=2,
                              progress_stop_patience=invalid)


if __name__ == "__main__":
    unittest.main()
