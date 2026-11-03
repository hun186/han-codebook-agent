"""Review-only round checkpoints and truly masked post-run shadow folds."""
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
from han_codebook.round_checkpoint import candidate_checkpoint


def research_case():
    return {
        "case_id": "fictional-checkpoint",
        "profiles": {"neutral": {"keywords": [], "lexicon": {
            "甲": 2, "乙": 2, "丙": 2, "丁": 2},
            "sentences": [["甲", "乙", "丙"]]}},
        "messages": [
            {"id": "m1", "codes": ["100", "101"]},
            {"id": "m2", "codes": ["100", "102"]},
            {"id": "m3", "codes": ["142", "143", "144", "100"]},
        ],
        "known_pairs": [
            {"message_id": "m1", "segments": ["甲", "乙"]},
            {"message_id": "m2", "segments": ["甲", "丙"]},
        ],
    }


def solver_answer(term: str):
    return {
        "objective_score": 0.8,
        "verified_anchors": {"100": "甲", "101": "乙", "102": "丙"},
        "proposals": {
            "100": {"term": "甲", "status": "verified_alignment", "alternatives": []},
            "142": {"term": "甲", "status": "hypothesis_unverified",
                    "alternatives": [{"term": "甲"}, {"term": "乙"}]},
            "143": {"term": term, "status": "hypothesis_unverified",
                    "alternatives": [{"term": term}, {"term": "丙"}, {"term": "丁"}]},
            "144": {"term": "丁", "status": "hypothesis_unverified",
                    "alternatives": [{"term": "丁"}, {"term": "乙"}]},
        },
    }


class CheckpointTests(unittest.TestCase):
    def test_stable_guess_replaced_and_solver_model_conflict_not_verified(self):
        stable = solver_answer("甲")
        changed = solver_answer("乙")
        snapshots = [
            {"proposals": {"143": {"term": "甲"}}},
            {"proposals": {"143": {"term": "甲"}}},
        ]
        result = candidate_checkpoint(
            stable, changed, snapshots,
            [{"code": "143", "candidates": ["丙", "乙"], "reason": "unverified"}],
            round_number=3)
        row = next(x for x in result["review_items"] if x["code"] == "143")
        self.assertEqual(result["previously_stable_guesses_replaced"], 1)
        self.assertEqual(result["model_solver_first_choice_disagreements"], 1)
        self.assertEqual(row["previous_unverified"], "甲")
        self.assertEqual(row["current_unverified"], "乙")
        self.assertEqual(row["model_first_unverified"], "丙")
        self.assertIn("previously_stable_guess_replaced", row["flags"])
        self.assertTrue(row["needs_independent_confirmation"])
        self.assertTrue(result["no_automatic_best_round_selection"])

    def test_full_agent_preserves_latest_and_postrun_shadow_folds(self):
        source = research_case()
        original = deepcopy(source)
        answers = iter(["甲", "甲", "甲", "乙"])
        captured = []
        def fake_solver(payload, **kwargs):
            self.assertNotIn("ground_truth", payload)
            self.assertNotIn("gold", payload)
            return solver_answer(next(answers))
        def fake_llm(_url, _model, packet, **kwargs):
            captured.append(deepcopy(packet))
            return {"hypotheses": [
                {"code": "143", "candidates": ["丙", "乙"], "reason": "guess"}
            ]}
        with TemporaryDirectory() as td:
            db = Path(td) / "audit.sqlite"
            with patch("han_codebook.agent.analyze", side_effect=fake_solver), \
                 patch("han_codebook.agent.query_local_llm", side_effect=fake_llm):
                result = run_agent(source, rounds=3, db_path=str(db),
                                   postrun_holdout_folds=2,
                                   solver_iterations=1, solver_restarts=1)
            with sqlite3.connect(db) as conn:
                saved = [json.loads(row[0]) for row in conn.execute(
                    "SELECT payload_json FROM events WHERE stage='round_candidate_checkpoint'")]
                holdouts = [json.loads(row[0]) for row in conn.execute(
                    "SELECT payload_json FROM events "
                    "WHERE stage='independent_postrun_holdout_summary'")]
        self.assertEqual(source, original)
        self.assertEqual(result["proposals"]["143"]["term"], "乙")
        self.assertEqual(len(captured), 3)
        self.assertEqual(len(saved), 3)
        self.assertEqual(result["round_candidate_checkpoints"], saved)
        self.assertEqual(saved[2]["previously_stable_guesses_replaced"], 1)
        self.assertEqual(result["postrun_independent_holdout"]["status"], "completed")
        self.assertFalse(result["postrun_independent_holdout"]["evaluates_live_llm_rounds"])
        self.assertTrue(result["postrun_independent_holdout"]["no_automatic_round_selection"])
        self.assertGreater(result["postrun_independent_holdout"]["summary"]
                           ["scored_fold_code_assessments"], 0)
        self.assertEqual(len(holdouts), 1)
        # The reporting feature must never return a synthetic gold result.
        self.assertNotIn("ground_truth", json.dumps(result))
        self.assertNotIn("codebook", json.dumps(result))

    def test_default_no_shadow_work_and_invalid_folds_rejected(self):
        source = research_case()
        with TemporaryDirectory() as td:
            with patch("han_codebook.agent.analyze", return_value=solver_answer("甲")), \
                 patch("han_codebook.holdout_verification.verify_known_pairs",
                       side_effect=AssertionError("must remain opt-in")):
                output = run_agent(source, rounds=0, db_path=str(Path(td) / "audit.sqlite"))
        self.assertEqual(output["postrun_holdout_folds_requested"], 0)
        self.assertNotIn("postrun_independent_holdout", output)
        for invalid in (True, False, -1, 11, "2", 2.0):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(CaseError, "postrun_holdout_folds"):
                    run_agent(source, rounds=0, postrun_holdout_folds=invalid)


if __name__ == "__main__":
    unittest.main()
