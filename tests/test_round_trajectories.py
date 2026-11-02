"""Every round remains an unverified, reconstructable hypothesis snapshot."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sqlite3
import json
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from han_codebook.agent import _hypothesis_snapshot, run_agent


def case():
    return {"case_id": "synthetic-multi-round",
            "profiles": {"neutral": {"lexicon": {"甲": 1, "乙": 1, "丙": 1}}},
            "messages": [{"id": "m", "codes": ["100"]}],
            "known_pairs": []}


def make_mapping(phrase):
    return {"proposals": {"100": {"term": phrase, "status": "hypothesis_unverified",
                                  "alternatives": [{"term": phrase}, {"term": "乙"}]}},
            "objective_score": 0.3, "verified_anchors": {}}


class TrajectoryTests(unittest.TestCase):
    def test_baseline_all_rounds_and_reversion_tracked_without_gold(self):
        research = case()
        original = deepcopy(research)
        returned = iter(["甲", "乙", "甲", "丙"])
        def solver(payload, **kwargs):
            self.assertNotIn("gold", payload)
            self.assertNotIn("ground_truth", payload)
            return make_mapping(next(returned))
        with TemporaryDirectory() as td:
            path = Path(td) / "audit.sqlite"
            with patch("han_codebook.agent.analyze", side_effect=solver), \
                 patch("han_codebook.agent.query_local_llm",
                       return_value={"hypotheses": []}) as chat:
                result = run_agent(research, rounds=3, llm_url="http://localhost:11434",
                                   db_path=str(path))
            self.assertEqual(chat.call_count, 3)
            with sqlite3.connect(path) as db:
                snapshots = [json.loads(body) for (body,) in db.execute(
                    "SELECT payload_json FROM events WHERE stage='round_hypothesis_snapshot'"
                    " ORDER BY id")]
        self.assertEqual(original, research)
        self.assertEqual([s["proposals"]["100"]["term"] for s in
                          result["round_research_snapshots"]],
                         ["甲", "乙", "甲", "丙"])
        self.assertEqual([s["proposals"]["100"]["top5"][0] for s in snapshots],
                         ["乙", "甲", "丙"])
        self.assertEqual(result["round_research_snapshots"][2]
                         ["returned_to_older_hypothesis"], ["100"])
        self.assertEqual(result["round_progress_summary"][1]
                         ["returned_to_older_hypothesis_count"], 1)
        self.assertEqual(result["proposals"]["100"]["term"], "丙")
        self.assertIn("no gold", result["round_research_selection_policy"])
        self.assertTrue(all(s["proposals"]["100"]["status"] ==
                            "hypothesis_unverified"
                            for s in result["round_research_snapshots"]))

    def test_large_snapshot_is_bounded_and_labeled_not_accuracy(self):
        output = {"proposals": {
            str(i): {"term": "猜詞", "status": "hypothesis_unverified",
                     "alternatives": [{"term": "候選"}] * 8}
            for i in range(600)
        }, "objective_score": 1.0}
        snap = _hypothesis_snapshot(output, round_number=1,
                                    stage="post_llm_rescore", vocab_size=12,
                                    earlier=[])
        self.assertTrue(snap["truncated"])
        self.assertEqual(snap["snapshot_code_count"], 500)
        self.assertEqual(snap["available_code_count"], 600)
        self.assertTrue(all(len(x["top5"]) <= 5 for x in snap["proposals"].values()))
        self.assertNotIn("accuracy", snap)
        self.assertEqual(snap["returned_to_older_hypothesis"], [])


if __name__ == "__main__":
    unittest.main()
