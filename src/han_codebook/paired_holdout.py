"""Paired metadata ON/OFF verification of *independently withheld* known pairs.

Both conditions use the same case, message folds and deterministic solver budget.
Held-out plaintext is used only by holdout_verification after inference. This
module compares correct/incorrect *outcomes*, not reference phrases or guesses.
No LLM, network calls, or synthetic gold files are involved.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from typing import Any

from .core import CaseError
from .holdout_verification import verify_known_pairs


_TOP1 = frozenset(("correct_top1",))
_TOP5 = frozenset(("correct_top1", "top5_only_ranking_error"))


def _effect(on: bool, off: bool) -> str:
    if on and not off:
        return "helped"
    if off and not on:
        return "harmed"
    return "both_correct" if on else "both_wrong"


def paired_metadata_holdout(case: dict[str, Any], *, max_folds: int = 10,
                            iterations: int = 3, restarts: int = 2) -> dict[str, Any]:
    """Score identical held-out code assessments with and without metadata.

    A comparison counts only if BOTH folds have produced a scored hypothesis.
    This cannot establish historical decipherment or independent lexical
    generalization: the same supplied vocabulary is visible in both variants.
    """
    # Independent copies prevent future mutating implementation details from
    # contaminating the other condition or the researcher's input object.
    common = dict(max_folds=max_folds, iterations=iterations, restarts=restarts)
    on = verify_known_pairs(deepcopy(case), use_metadata=True, **common)
    off = verify_known_pairs(deepcopy(case), use_metadata=False, **common)
    if (on["available_fold_count"] != off["available_fold_count"]
            or len(on["folds"]) != len(off["folds"])):
        raise CaseError("paired holdout fold sets disagree")
    rows: list[dict[str, Any]] = []
    total = Counter()
    for left, right in zip(on["folds"], off["folds"]):
        if (left["heldout_message_id"] != right["heldout_message_id"]
                or left["independently_testable_codes"] != right["independently_testable_codes"]
                or left["retained_anchor_overlap_excluded"]
                != right["retained_anchor_overlap_excluded"]):
            raise CaseError("paired holdout fold identity differs")
        on_outcomes = left["outcomes_without_plaintext"]
        off_outcomes = right["outcomes_without_plaintext"]
        codes_on = {item["code"]: item["outcome"] for item in on_outcomes}
        codes_off = {item["code"]: item["outcome"] for item in off_outcomes}
        if (len(codes_on) != len(on_outcomes) or len(codes_off) != len(off_outcomes)
                or set(codes_on) != set(codes_off)
                or len(codes_on) != left["independently_testable_codes"]):
            raise CaseError("paired holdout code identities differ")
        scorable = left["status"] == right["status"] == "scored"
        if scorable and (left["scored_code_assessments"] != len(codes_on)
                         or right["scored_code_assessments"] != len(codes_on)):
            raise CaseError("paired holdout score denominators disagree")
        effects = []
        fold_count = Counter()
        for code in sorted(codes_on):
            if not scorable:
                effects.append({"code": code, "top1": "not_comparable",
                                "top5": "not_comparable"})
                fold_count["not_comparable"] += 1
                continue
            top1 = _effect(codes_on[code] in _TOP1, codes_off[code] in _TOP1)
            top5 = _effect(codes_on[code] in _TOP5, codes_off[code] in _TOP5)
            effects.append({"code": code, "top1": top1, "top5": top5})
            fold_count["compared"] += 1
            fold_count["top1_" + top1] += 1
            fold_count["top5_" + top5] += 1
        total.update(fold_count)
        rows.append({
            "heldout_message_id": left["heldout_message_id"],
            "independently_testable_codes": len(codes_on),
            "paired_scored_code_assessments": fold_count["compared"],
            "not_comparable_code_assessments": fold_count["not_comparable"],
            "metadata_on_fold_status": left["status"],
            "metadata_off_fold_status": right["status"],
            "top1_helped": fold_count["top1_helped"],
            "top1_harmed": fold_count["top1_harmed"],
            "top5_helped": fold_count["top5_helped"],
            "top5_harmed": fold_count["top5_harmed"],
            "effects_without_plaintext": effects,
        })
    compared = total["compared"]
    return {
        "case_id": on["case_id"],
        "method": "offline paired known-pair holdout; metadata ON versus OFF; no LLM/gold",
        "same_folds_and_solver_budget": {"max_folds": max_folds,
                                          "iterations": iterations, "restarts": restarts},
        "evaluated_fold_count": len(rows),
        "metadata_on_summary": on["summary"],
        "metadata_off_summary": off["summary"],
        "paired_summary": {
            "paired_scored_code_assessments": compared,
            "not_comparable_code_assessments": total["not_comparable"],
            "top1_helped": total["top1_helped"],
            "top1_harmed": total["top1_harmed"],
            "top1_both_correct": total["top1_both_correct"],
            "top1_both_wrong": total["top1_both_wrong"],
            "top5_helped": total["top5_helped"],
            "top5_harmed": total["top5_harmed"],
            "top5_both_correct": total["top5_both_correct"],
            "top5_both_wrong": total["top5_both_wrong"],
            "top1_net_helped_minus_harmed": total["top1_helped"] - total["top1_harmed"],
            "top1_helped_rate": round(total["top1_helped"] / compared, 4) if compared else None,
            "top1_harmed_rate": round(total["top1_harmed"] / compared, 4) if compared else None,
        },
        "folds": rows,
        "limitations": [
            "All labels are independent held-out fold-code assessments, not unique globally independent code groups.",
            "Only fold codes scored under BOTH conditions enter paired denominators; unavailable folds are counted separately.",
            "No plaintext, guessed phrases, raw messages, LLM prompts, or synthetic gold are included in this report.",
            "Supplied lexicon and sentence examples remain available in both variants; not blind vocabulary-level decipherment.",
            "This is a deterministic offline sensitivity experiment, not evidence that metadata improves historical decipherment.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True,
                        help="NEW local JSON path (never overwrite prior evidence)")
    parser.add_argument("--max-folds", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--restarts", type=int, default=2)
    args = parser.parse_args(argv)
    try:
        if args.out.resolve() == args.case.resolve():
            raise CaseError("output must differ from original research input")
        case = json.loads(args.case.read_text(encoding="utf-8"))
        report = paired_metadata_holdout(case, max_folds=args.max_folds,
                                         iterations=args.iterations, restarts=args.restarts)
        payload = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(args.out, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
        summary = report["paired_summary"]
        print(f"Offline paired holdout: {report['evaluated_fold_count']} folds, "
              f"{summary['paired_scored_code_assessments']} comparable fold-codes; "
              f"metadata helped {summary['top1_helped']}, harmed {summary['top1_harmed']}.")
        print(f"Saved NEW result to: {args.out}. No reference plaintext included.")
        return 0
    except (CaseError, ValueError, TypeError, KeyError, OSError) as exc:
        print(f"ERROR paired holdout: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
