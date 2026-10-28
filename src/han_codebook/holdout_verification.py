"""Offline leave-one-message-alignment-out verification of codebook hypotheses.

Trusted plaintext is held exclusively by the post-inference scorer. Every fold
removes *all* known pairs for a message, not just one duplicate pair. Only
codes with no remaining verified anchor count toward the independent score.

This is NOT blind decipherment: operator-supplied lexicons, training examples,
ciphertext and contextual metadata remain available to the solver.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any

from .candidate_ideas import idea_vocabulary
from .core import CaseError, analyze, anchors_and_review, validate_case


def _fold_input(case: dict[str, Any], message_id: str,
                withheld_codes: set[str]) -> dict[str, Any]:
    """Build a case without held-out plaintext or code-specific researcher cues."""
    folded = deepcopy(case)
    folded["known_pairs"] = [
        p for p in folded.get("known_pairs", [])
        if p["message_id"] != message_id
    ]
    retained, _, _ = anchors_and_review(folded)
    independent_codes = withheld_codes - set(retained)

    # An explicitly stored candidate, trial pin, or researcher counterfactual
    # may itself encode the answer that this fold is meant to predict.
    for key in ("candidate_ideas", "hypothesis_marks", "bold_hypotheses"):
        if key in folded:
            # Marks and bold hypotheses may be explicitly null in otherwise
            # valid historical cases; their normalizers treat None as empty.
            entries = folded[key] if folded[key] is not None else {}
            folded[key] = {
                code: value for code, value in entries.items()
                if code not in independent_codes
            }

    # UI revision history is never part of an inference case.
    folded.pop("hypothesis_revision_history", None)
    folded.pop("candidate_revision_history", None)
    validate_case(folded)
    return folded


def verify_known_pairs(case: dict[str, Any], *, max_folds: int = 10,
                       iterations: int = 3, restarts: int = 2,
                       use_metadata: bool = True) -> dict[str, Any]:
    """Check held-out *aligned* known pairs without any gold file or LLM calls.

    Distinct (message, code) annotations are scored once per fold, regardless
    of token frequency. Codes still anchored by other messages are recorded as
    overlap and excluded, rather than counted as decipherment successes.
    """
    if not isinstance(case, dict) or any(
        key in case for key in ("ground_truth", "gold", "codebook")
    ):
        raise CaseError("hold-out input must not contain any embedded evaluation oracle")
    if type(max_folds) is not int or not 1 <= max_folds <= 100:
        raise CaseError("max_folds must be an integer from 1 to 100")
    if type(iterations) is not int or not 1 <= iterations <= 100:
        raise CaseError("iterations must be an integer from 1 to 100")
    if type(restarts) is not int or not 1 <= restarts <= 20:
        raise CaseError("restarts must be an integer from 1 to 20")
    if type(use_metadata) is not bool:
        raise CaseError("use_metadata must be a boolean")
    validate_case(case)
    # Check the entire supplied evidence set for contradictory anchors first.
    anchors_and_review(case)
    messages = {m["id"]: m for m in case["messages"]}
    groups: dict[str, list[dict[str, Any]]] = {}
    unsegmented = 0
    for pair in case.get("known_pairs", []):
        if "segments" not in pair:
            unsegmented += 1
            continue
        groups.setdefault(pair["message_id"], []).append(pair)
    if not groups:
        raise CaseError("hold-out validation requires at least one segmented known pair")

    folds = []
    totals = Counter()
    for message_id, paired in list(groups.items())[:max_folds]:
        codes = messages[message_id]["codes"]
        truth: dict[str, str] = {}
        for pair in paired:
            # anchors_and_review already validated the segment count and
            # consistency, including repeated code groups.
            for code, term in zip(codes, pair["segments"]):
                if code in truth and truth[code] != term:
                    raise CaseError(f"contradictory held-out alignment for {message_id}")
                truth[code] = term
        folded = _fold_input(case, message_id, set(truth))
        retained, _, vocab = anchors_and_review(folded)
        independent = sorted(set(truth) - set(retained))
        overlap = len(truth) - len(independent)
        failures = Counter()
        details = []
        # For a case with no other known pairs and no profile lexicon, the
        # withheld aligned words may have been the *entire* vocabulary.
        # Never restore them just to make the solver run: record the missing
        # vocabulary as a legitimate failure category instead.
        vocab.update(idea_vocabulary(folded))
        marks = folded.get("hypothesis_marks") or {}
        vocab.update(mark["preferred"] for mark in marks.values()
                     if mark.get("preferred"))
        no_candidates = bool(independent) and not vocab
        if no_candidates:
            for code in independent:
                failures["term_missing_from_candidate_vocabulary"] += 1
                details.append({
                    "code": code, "outcome": "term_missing_from_candidate_vocabulary"
                })
        elif independent:
            # Only the sanitized case crosses the inference boundary.
            result = analyze(folded, use_metadata=use_metadata,
                             iterations=iterations, restarts=restarts)
            if result["verified_anchors"] != retained:
                raise CaseError("inference altered the retained trusted anchors")
            # The original withheld plaintext is consulted only *now*.
            for code in independent:
                proposal = result["proposals"][code]
                if proposal["status"] != "hypothesis_unverified":
                    raise CaseError("withheld code was improperly marked verified")
                term = truth[code]
                alternatives = [a["term"] for a in proposal["alternatives"][:5]]
                if proposal["term"] == term:
                    category = "correct_top1"
                elif term not in vocab:
                    category = "term_missing_from_candidate_vocabulary"
                elif term in alternatives:
                    category = "top5_only_ranking_error"
                else:
                    category = "candidate_ranked_below_top5"
                failures[category] += 1
                details.append({"code": code, "outcome": category})
        fold = {
            "heldout_message_id": message_id,
            "withheld_record_count": len(paired) + sum(
                p["message_id"] == message_id and "segments" not in p
                for p in case.get("known_pairs", [])
            ),
            "heldout_unique_codes": len(truth),
            "retained_anchor_overlap_excluded": overlap,
            "independently_testable_codes": len(independent),
            "correct_top1": failures["correct_top1"],
            "correct_top5": failures["correct_top1"] + failures["top5_only_ranking_error"],
            "failure_categories": dict(sorted(failures.items())),
            "outcomes_without_plaintext": details,
            "status": ("no_candidate_vocabulary" if no_candidates else
                       "scored" if independent else "no_newly_unanchored_codes"),
        }
        folds.append(fold)
        totals.update({
            "fold_code_assessments": len(independent),
            "top1_hits": fold["correct_top1"],
            "top5_hits": fold["correct_top5"],
            "overlapping_anchored_codes_excluded": overlap,
        })
        totals.update(failures)

    count = totals["fold_code_assessments"]
    return {
        "case_id": case.get("case_id", "unnamed"),
        "method": "offline leave-one-aligned-message-out; no LLM; no gold file",
        "available_fold_count": len(groups),
        "evaluated_fold_count": len(folds),
        "unaligned_plaintext_records_not_scored": unsegmented,
        "summary": {
            "independently_testable_fold_code_assessments": count,
            "top1_hits": totals["top1_hits"],
            "top5_hits": totals["top5_hits"],
            "top1_rate": round(totals["top1_hits"] / count, 4) if count else None,
            "top5_rate": round(totals["top5_hits"] / count, 4) if count else None,
            "overlapping_anchored_codes_excluded": totals["overlapping_anchored_codes_excluded"],
            "failure_categories": {
                key: totals[key] for key in (
                    "term_missing_from_candidate_vocabulary",
                    "top5_only_ranking_error",
                    "candidate_ranked_below_top5",
                )
            },
        },
        "folds": folds,
        "limitations": [
            "Held-out reference plaintext is used for post-inference scoring only.",
            "Other known-pair anchors that reveal the same code are excluded from scoring.",
            "The same code may be assessed in multiple folds; denominators are fold-code assessments, not globally independent codes.",
            "Operator lexicons, sentence priors, ciphertext and contextual metadata can still contain strong hints; this is NOT blind decipherment.",
            "Researcher candidate hints for newly unanchored held-out codes are removed; unrelated candidate hints remain.",
            "Unaligned plaintext is never promoted to a verified anchor or scored as segmented truth.",
            "Outputs are unverified hypotheses, not historical plaintext verification.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, type=Path,
                        help="Local research JSON with segmented known_pairs")
    parser.add_argument("--out", type=Path,
                        default=Path("artifacts/known_pair_holdout.json"))
    parser.add_argument("--max-folds", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--restarts", type=int, default=2)
    parser.add_argument("--no-metadata", action="store_true")
    args = parser.parse_args(argv)
    try:
        case = json.loads(args.case.read_text(encoding="utf-8"))
        result = verify_known_pairs(case, max_folds=args.max_folds,
                                    iterations=args.iterations,
                                    restarts=args.restarts,
                                    use_metadata=not args.no_metadata)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        summary = result["summary"]
        print(f"Offline hold-out: {result['evaluated_fold_count']}/{result['available_fold_count']} folds; "
              f"independently testable {summary['independently_testable_fold_code_assessments']} fold-codes; "
              f"Top-1 {summary['top1_hits']}, Top-5 {summary['top5_hits']}.")
        print(f"Saved: {args.out}; no reference plaintext included in report.")
        return 0
    except (CaseError, KeyError, TypeError, ValueError, OSError,
            json.JSONDecodeError) as exc:
        print(f"ERROR hold-out: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
