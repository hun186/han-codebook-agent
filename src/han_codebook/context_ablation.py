"""Paired offline context ablation using held-out, aligned known plaintext.

Each variant uses exactly the same leave-one-message-out folds and candidate
lexicon. Hidden reference phrases are handled only by holdout_verification's
post-inference scorer. No LLM calls, no gold files, no auto-policy selection.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any

from .core import CaseError
from .holdout_verification import verify_known_pairs

MODE_ORDER = ("legacy_context", "without_observations", "time_relevance",
              "no_metadata")
CORRECT_TOP1 = "correct_top1"
CORRECT_TOP5 = frozenset(("correct_top1", "top5_only_ranking_error"))


def _variant(case: dict[str, Any], mode: str) -> tuple[dict[str, Any], bool]:
    """Isolate each trial; never mutate the investigator's archived case."""
    if mode not in MODE_ORDER:
        raise CaseError("unknown context ablation mode")
    candidate = deepcopy(case)
    candidate["observation_policy"] = (
        "time_relevance" if mode == "time_relevance" else "legacy"
    )
    if mode in ("without_observations", "no_metadata"):
        for message in candidate["messages"]:
            message.pop("observations", None)
    if mode == "no_metadata":
        for message in candidate["messages"]:
            for key in ("sender", "recipient", "received_at", "notes", "unit",
                        "domain"):
                message.pop(key, None)
    return candidate, mode != "no_metadata"


def _fold_outcomes(report: dict[str, Any]) -> tuple[dict[tuple[str, str], str],
                                                  dict[tuple[str, str], str]]:
    """Return all fold/code outcomes and subset where inference really ran."""
    all_outcomes: dict[tuple[str, str], str] = {}
    inferred: dict[tuple[str, str], str] = {}
    for fold in report["folds"]:
        message_id = fold["heldout_message_id"]
        for row in fold["outcomes_without_plaintext"]:
            key = (message_id, row["code"])
            if key in all_outcomes:
                raise CaseError("duplicate fold/code assessment")
            all_outcomes[key] = row["outcome"]
            if fold["status"] == "scored":
                inferred[key] = row["outcome"]
    return all_outcomes, inferred


def _paired(baseline: dict, variant: dict, minimum_paired: int) -> dict:
    """Compare only identical fold/code records with actual inference in both."""
    common = sorted(set(baseline) & set(variant))
    base_only = sum(baseline[key] == CORRECT_TOP1 and
                    variant[key] != CORRECT_TOP1 for key in common)
    variant_only = sum(variant[key] == CORRECT_TOP1 and
                       baseline[key] != CORRECT_TOP1 for key in common)
    base_five = sum(baseline[key] in CORRECT_TOP5 for key in common)
    variant_five = sum(variant[key] in CORRECT_TOP5 for key in common)
    n = len(common)
    if n < minimum_paired:
        signal = "insufficient_paired_evidence"
    elif variant_only > base_only:
        signal = "possible_context_harm"
    elif base_only > variant_only:
        signal = "possible_context_benefit"
    else:
        signal = "no_directional_difference"
    return {
        "paired_inferred_fold_codes": n,
        "legacy_only_top1_hits": base_only,
        "variant_only_top1_hits": variant_only,
        "both_top1_hits": sum(baseline[k] == CORRECT_TOP1 and
                              variant[k] == CORRECT_TOP1 for k in common),
        "neither_top1_hits": n - base_only - variant_only -
                             sum(baseline[k] == CORRECT_TOP1 and
                                 variant[k] == CORRECT_TOP1 for k in common),
        "legacy_top5_hits": base_five,
        "variant_top5_hits": variant_five,
        "top1_rate_delta_variant_minus_legacy":
            round((variant_only - base_only) / n, 4) if n else None,
        "top5_rate_delta_variant_minus_legacy":
            round((variant_five - base_five) / n, 4) if n else None,
        "signal": signal,
    }


def compare_context(case: dict[str, Any], *, max_folds: int = 10,
                    iterations: int = 3, restarts: int = 2,
                    minimum_paired: int = 10) -> dict[str, Any]:
    """Compare ablations; never feed held-out plaintext to model/inference.

    This is an *exploratory diagnostic*, not cross-validated model selection.
    Its labels must not automatically change live solver policy or weights.
    """
    if not isinstance(case, dict):
        raise CaseError("case must be an object")
    if type(minimum_paired) is not int or not 1 <= minimum_paired <= 10000:
        raise CaseError("minimum_paired must be an integer from 1 to 10000")
    reports = {}
    all_keys = None
    inference = {}
    for mode in MODE_ORDER:
        prepared, use_metadata = _variant(case, mode)
        report = verify_known_pairs(
            prepared, max_folds=max_folds, iterations=iterations,
            restarts=restarts, use_metadata=use_metadata
        )
        current_all, current_inferred = _fold_outcomes(report)
        if all_keys is not None and set(current_all) != all_keys:
            raise CaseError("context variants changed held-out fold/code identities")
        all_keys = set(current_all)
        inference[mode] = current_inferred
        summary = report["summary"]
        reports[mode] = {
            "available_fold_count": report["available_fold_count"],
            "evaluated_fold_count": report["evaluated_fold_count"],
            "potential_fold_code_assessments":
                summary["independently_testable_fold_code_assessments"],
            "inferred_fold_code_assessments": len(current_inferred),
            "scored_fold_code_assessments":
                summary["scored_fold_code_assessments"],
            "unscorable_due_to_exclusions":
                summary["not_scored_due_to_candidate_exclusions"],
            "top1_hits": summary["top1_hits"],
            "top5_hits": summary["top5_hits"],
            "top1_rate": summary["top1_rate"],
            "top5_rate": summary["top5_rate"],
            "overlapping_anchors_not_counted":
                summary["overlapping_anchored_codes_excluded"],
        }
    return {
        "case_id": case.get("case_id", "unnamed"),
        "method": "offline paired held-out known-pair context ablation",
        "minimum_paired_inferred_fold_codes": minimum_paired,
        "baseline": "legacy_context",
        "modes": reports,
        "paired_vs_legacy": {
            mode: _paired(inference["legacy_context"], inference[mode],
                          minimum_paired)
            for mode in MODE_ORDER if mode != "legacy_context"
        },
        "policy_selection": "none; diagnostic only",
        "limitations": [
            "Only truly inferred, matching fold/code pairs enter paired deltas.",
            "Top-1 and Top-5 are checked against withheld reliable segments AFTER inference.",
            "Previously verified overlapping anchors are excluded from scoring.",
            "Fold/code records can repeat a code across folds; they are not independent samples.",
            "The evidence threshold is descriptive, not a statistical significance test.",
            "All variants share operator-provided lexicons and sentence priors.",
            "This is not blind cryptanalysis or historical decipherment accuracy.",
            "No model calls, oracle files, or automatic inference-policy changes.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--out", type=Path,
                        default=Path("artifacts/context_ablation.json"))
    parser.add_argument("--max-folds", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--restarts", type=int, default=2)
    parser.add_argument("--minimum-paired", type=int, default=10)
    args = parser.parse_args(argv)
    try:
        case = json.loads(args.case.read_text(encoding="utf-8"))
        report = compare_context(
            case, max_folds=args.max_folds, iterations=args.iterations,
            restarts=args.restarts, minimum_paired=args.minimum_paired
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2)
                            + "\n", encoding="utf-8")
        print("Offline context ablation: "
              + ", ".join(f"{mode}: {row['top1_hits']}/"
                          f"{row['scored_fold_code_assessments']}"
                          for mode, row in report["modes"].items()))
        print(f"Saved: {args.out}; no reference plaintext or solver mapping.")
        return 0
    except (CaseError, KeyError, TypeError, ValueError, OSError) as exc:
        print(f"ERROR context ablation: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
