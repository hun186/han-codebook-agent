"""Researcher confirmation must never be triggered merely by heuristic rank."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from han_codebook.core import CaseError
from han_codebook.unaligned_accept import accept_reviewed_alignment, main
from han_codebook.unaligned_review import review_unsegmented


def fixture():
    return {
        "case_id": "human-acceptance",
        "profiles": {"neutral": {
            "lexicon": {"補給": 8, "車隊": 7, "出發": 6},
            "sentences": [["補給", "車隊", "出發"]],
        }},
        "messages": [
            {"id": "trusted", "codes": ["001"]},
            {"id": "target", "codes": ["001", "002", "003"]},
        ],
        "known_pairs": [
            {"message_id": "trusted", "segments": ["補給"]},
            {"message_id": "target", "plaintext": "補給車隊出發"},
        ],
    }


class ManualAlignmentAcceptanceTests(unittest.TestCase):
    def test_only_explicit_exact_confirmation_promotes_new_copy(self):
        case = fixture()
        before = deepcopy(case)
        report = review_unsegmented(case, top_n=3, beam_width=8)
        self.assertEqual(report["top_n"], 3)
        self.assertEqual(report["beam_width"], 8)
        segments = ["補給", "車隊", "出發"]
        promoted = accept_reviewed_alignment(
            case, report, known_pair_index=1,
            candidate_rank=1, confirmed_segments=segments, confirmed=True
        )
        self.assertEqual(case, before)
        self.assertNotIn("segments", case["known_pairs"][1])
        self.assertEqual(promoted["known_pairs"][1]["segments"], segments)
        self.assertEqual(promoted["known_pairs"][0]["segments"], ["補給"])
        prov = promoted["known_pairs"][1]["alignment_provenance"]
        self.assertEqual(prov["method"],
                         "explicit_researcher_confirmed_review_candidate")
        self.assertTrue(prov["not_historical_authenticity_proof"])
        self.assertEqual(prov["source_case_sha256"], report["source_case_sha256"])

    def test_promotion_prunes_old_undo_snapshots_but_keeps_other_marks(self):
        case = fixture()
        case["messages"].append({"id": "other", "codes": ["004"]})
        retained = {"preferred": "車站", "excluded": [], "pinned": False}
        former = {"preferred": "車隊", "excluded": [], "pinned": False}
        case["hypothesis_marks"] = {"004": retained}
        case["hypothesis_revision_history"] = {
            "version": 1, "cursor": 1,
            "snapshots": [
                {"002": former, "003": former, "004": retained},
                {"004": retained},
            ],
            "actions": ["先前標註", "清除已驗證前的標註"],
        }
        before = deepcopy(case)
        reviewed = review_unsegmented(case)
        updated = accept_reviewed_alignment(
            case, reviewed, known_pair_index=1, candidate_rank=1,
            confirmed_segments=["補給", "車隊", "出發"], confirmed=True,
        )
        self.assertEqual(case, before)
        history = updated["hypothesis_revision_history"]
        self.assertEqual(history["cursor"], 1)
        self.assertEqual(history["actions"], before["hypothesis_revision_history"]["actions"])
        self.assertEqual(history["snapshots"], [
            {"004": retained}, {"004": retained}
        ])
        self.assertEqual(updated["hypothesis_marks"], {"004": retained})
        # Simulates later browser Undo; no old mark on a new trusted code.
        for snapshot in history["snapshots"]:
            self.assertFalse({"001", "002", "003"} & set(snapshot))
            replayed = deepcopy(updated)
            replayed["hypothesis_marks"] = snapshot
            review_unsegmented(replayed)

    def test_unconfirmed_or_wrong_retyped_segments_fail_closed(self):
        case = fixture()
        report = review_unsegmented(case)
        opts = dict(known_pair_index=1, candidate_rank=1,
                    confirmed_segments=["補給", "車隊", "出發"])
        with self.assertRaisesRegex(CaseError, "explicit researcher"):
            accept_reviewed_alignment(case, report, **opts)
        with self.assertRaisesRegex(CaseError, "explicit researcher"):
            accept_reviewed_alignment(case, report, confirmed=1, **opts)
        with self.assertRaisesRegex(CaseError, "typed segmentation"):
            accept_reviewed_alignment(
                case, report, known_pair_index=1, candidate_rank=1,
                confirmed_segments=["補給", "車隊出發"], confirmed=True
            )
        with self.assertRaisesRegex(CaseError, "candidate_rank"):
            accept_reviewed_alignment(
                case, report, known_pair_index=1, candidate_rank=0,
                confirmed_segments=opts["confirmed_segments"], confirmed=True
            )
        with self.assertRaisesRegex(CaseError, "rank does not exist"):
            accept_reviewed_alignment(
                case, report, known_pair_index=1, candidate_rank=12,
                confirmed_segments=opts["confirmed_segments"], confirmed=True
            )
        with self.assertRaisesRegex(CaseError, "not an unsegmented"):
            accept_reviewed_alignment(
                case, report, known_pair_index=0, candidate_rank=1,
                confirmed_segments=opts["confirmed_segments"], confirmed=True
            )

    def test_report_and_case_changed_or_tampered_are_stale(self):
        case = fixture()
        report = review_unsegmented(case, top_n=2)
        options = dict(known_pair_index=1, candidate_rank=1,
                       confirmed_segments=["補給", "車隊", "出發"],
                       confirmed=True)
        for corrupted in (
            dict(case, case_id="different"),
            dict(case, messages=deepcopy(case["messages"])),
        ):
            corrupted["messages"][0]["notes"] = "changed"  # not just heuristic input
            with self.assertRaisesRegex(CaseError, "stale or changed"):
                accept_reviewed_alignment(corrupted, report, **options)
        wrong = deepcopy(report)
        wrong["reviews"][0]["candidates"][0]["heuristic_score"] = 999
        with self.assertRaisesRegex(CaseError, "stale or changed"):
            accept_reviewed_alignment(case, wrong, **options)
        wrong = deepcopy(report)
        wrong.pop("top_n")
        with self.assertRaisesRegex(CaseError, "regenerate"):
            accept_reviewed_alignment(case, wrong, **options)

    def test_annotations_on_promoted_codes_must_be_reconciled(self):
        for key, value in (
            ("hypothesis_marks", {"002": {
                "preferred": "車隊", "excluded": [], "pinned": False
            }}),
            ("bold_hypotheses", {"001": {
                "term": "後勤", "confirmed": True
            }}),
            ("candidate_ideas", {"002": [{"term": "車隊"}]}),
        ):
            case = fixture()
            case[key] = value
            report = review_unsegmented(case)
            with self.subTest(field=key), self.assertRaisesRegex(
                CaseError, "reconcile annotations first"
            ):
                accept_reviewed_alignment(
                    case, report, known_pair_index=1, candidate_rank=1,
                    confirmed_segments=["補給", "車隊", "出發"], confirmed=True
                )

    def test_trusted_mismatch_and_repeated_code_are_not_promoted(self):
        case = fixture()
        case["known_pairs"][0]["segments"] = ["不符"]
        result = review_unsegmented(case)
        self.assertEqual(result["reviews"][0]["candidates"], [])
        with self.assertRaisesRegex(CaseError, "rank does not exist"):
            accept_reviewed_alignment(
                case, result, known_pair_index=1, candidate_rank=1,
                confirmed_segments=["補給", "車隊", "出發"], confirmed=True
            )
        case = fixture()
        case["messages"][1]["codes"] = ["002", "003", "002"]
        case["known_pairs"][1]["plaintext"] = "補給車隊車隊"
        result = review_unsegmented(case)
        for item in result["reviews"][0]["candidates"]:
            self.assertEqual(item["segments"][0], item["segments"][2])

    def test_undo_history_cannot_resurrect_newly_verified_code(self):
        case = fixture()
        # The researcher marked 002 in an earlier revision, then cleared it
        # while keeping a separate legitimate experimental code 009.
        case["messages"].append({"id": "other", "codes": ["009"]})
        other = {"preferred": "後勤", "excluded": [], "pinned": False}
        old = {"preferred": "車隊", "excluded": [], "pinned": False}
        case["hypothesis_marks"] = {"009": deepcopy(other)}
        case["hypothesis_revision_history"] = {
            "version": 1, "cursor": 1,
            "snapshots": [
                {"002": deepcopy(old), "009": deepcopy(other)},
                {"009": deepcopy(other)},
            ],
            "actions": ["標記 002", "清除 002"],
        }
        report = review_unsegmented(case)
        before = deepcopy(case)
        updated = accept_reviewed_alignment(
            case, report, known_pair_index=1, candidate_rank=1,
            confirmed_segments=["補給", "車隊", "出發"], confirmed=True
        )
        self.assertEqual(case, before)
        history = updated["hypothesis_revision_history"]
        self.assertEqual(history["cursor"], 1)
        self.assertEqual(history["actions"], ["標記 002", "清除 002"])
        for snapshot in history["snapshots"]:
            self.assertNotIn("002", snapshot)
            self.assertEqual(snapshot["009"], other)
        self.assertEqual(updated["hypothesis_marks"], {"009": other})
        self.assertEqual(updated["known_pairs"][1]["segments"],
                         ["補給", "車隊", "出發"])

    def test_cli_requires_confirmation_and_exclusive_private_new_file(self):
        with TemporaryDirectory() as td:
            inp = Path(td) / "original.json"
            review = Path(td) / "review.json"
            out = Path(td) / "accepted.json"
            case = fixture()
            inp.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
            review.write_text(json.dumps(review_unsegmented(case), ensure_ascii=False),
                              encoding="utf-8")
            opts = ["--case", str(inp), "--review", str(review), "--out", str(out),
                    "--known-pair-index", "1", "--candidate-rank", "1",
                    "--confirmed-segments-json",
                    json.dumps(["補給", "車隊", "出發"], ensure_ascii=False)]
            with patch("han_codebook.agent.query_local_llm",
                       side_effect=AssertionError("must stay offline")):
                self.assertEqual(main(opts), 2)
                self.assertFalse(out.exists())
                self.assertEqual(main(opts + ["--confirm-reviewed"]), 0)
                self.assertEqual(main(opts + ["--confirm-reviewed"]), 2)
            self.assertEqual(json.loads(inp.read_text(encoding="utf-8")), case)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))
                             ["known_pairs"][1]["segments"],
                             ["補給", "車隊", "出發"])
            with patch("os.open", side_effect=FileExistsError("already exists")):
                self.assertEqual(main(opts + ["--confirm-reviewed"]), 2)
            self.assertEqual(
                main(["--case", str(inp), "--review", str(review),
                      "--out", str(inp), "--known-pair-index", "1",
                      "--candidate-rank", "1", "--confirmed-segments-json",
                      '["補給", "車隊", "出發"]', "--confirm-reviewed"]), 2
            )


if __name__ == "__main__":
    unittest.main()
