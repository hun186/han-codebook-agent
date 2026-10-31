"""Explicit, offline researcher acceptance of a reviewed segmentation.

Only a human-supplied exact full code-group alignment can be promoted to a
known pair. This module never automatically selects a heuristic candidate and
never changes the source case or review file. It writes a NEW file by default.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

from .core import CaseError
from .unaligned_review import review_unsegmented


def _digest(case: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        case, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def accept_reviewed_alignment(
    case: dict[str, Any], report: dict[str, Any], *,
    known_pair_index: int, candidate_rank: int,
    confirmed_segments: list[str], confirmed: bool = False,
) -> dict[str, Any]:
    """Return a NEW case only after explicit human confirmation.

    A report must exactly match a fresh, bounded review of the unchanged
    source input. Researcher text must exactly match the selected candidate.
    This is NOT automatic confirmation of historical plaintext authenticity.
    """
    if confirmed is not True:
        raise CaseError("explicit researcher confirmation is required")
    if type(known_pair_index) is not int or known_pair_index < 0:
        raise CaseError("known_pair_index must be a nonnegative integer")
    if type(candidate_rank) is not int or candidate_rank < 1:
        raise CaseError("candidate_rank must be a positive integer")
    if (not isinstance(confirmed_segments, list) or not confirmed_segments
            or any(not isinstance(s, str) or not s for s in confirmed_segments)):
        raise CaseError("confirmed_segments must be nonempty plaintext phrases")
    if not isinstance(report, dict):
        raise CaseError("review report must be an object")
    top_n, beam_width = report.get("top_n"), report.get("beam_width")
    if type(top_n) is not int or type(beam_width) is not int:
        raise CaseError("regenerate the review with recorded top_n and beam_width")

    # Review validation is oracle-rejecting and avoids legacy unbounded
    # recursive segmentation even for cases with researcher annotations.
    rebuilt = review_unsegmented(case, top_n=top_n, beam_width=beam_width)
    if report != rebuilt:
        raise CaseError("stale or changed review/case; regenerate before acceptance")
    target = next((r for r in rebuilt["reviews"]
                   if r["known_pair_index"] == known_pair_index), None)
    if target is None:
        raise CaseError("known pair is not an unsegmented reviewed record")
    choices = target["candidates"]
    if candidate_rank > len(choices):
        raise CaseError("selected candidate rank does not exist")
    chosen = choices[candidate_rank - 1]["segments"]
    if confirmed_segments != chosen:
        raise CaseError("typed segmentation does not match selected review candidate")

    # Existing marks for a newly trusted code require manual reconciliation.
    codes = target["code_groups"]
    for field in ("hypothesis_marks", "bold_hypotheses", "candidate_ideas"):
        marks = case.get(field) or {}
        if not isinstance(marks, dict):
            raise CaseError(f"{field} must be an object")
        if any(code in marks for code in codes):
            raise CaseError(
                f"{field} overlaps newly trusted code; reconcile annotations first"
            )

    result = deepcopy(case)
    pair = result["known_pairs"][known_pair_index]
    if "segments" in pair:
        raise CaseError("this known pair was already segmented")
    pair["segments"] = list(chosen)
    pair["alignment_provenance"] = {
        "method": "explicit_researcher_confirmed_review_candidate",
        "source_case_sha256": _digest(case),
        "review_candidate_rank": candidate_rank,
        "not_historical_authenticity_proof": True,
    }
    # Re-validating the newly promoted anchors must fail closed on conflicts
    # and inconsistent repetitions before any file can be saved.
    review_unsegmented(result, top_n=top_n, beam_width=beam_width)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, type=Path)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--known-pair-index", type=int, required=True)
    parser.add_argument("--candidate-rank", type=int, required=True)
    parser.add_argument("--confirmed-segments-json", required=True)
    parser.add_argument("--confirm-reviewed", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.out.resolve() in (args.case.resolve(), args.review.resolve()):
            raise CaseError("output must be a new path, not the case or review file")
        case = json.loads(args.case.read_text(encoding="utf-8"))
        report = json.loads(args.review.read_text(encoding="utf-8"))
        typed = json.loads(args.confirmed_segments_json)
        updated = accept_reviewed_alignment(
            case, report, known_pair_index=args.known_pair_index,
            candidate_rank=args.candidate_rank,
            confirmed_segments=typed, confirmed=args.confirm_reviewed
        )
        # Exclusive, private-permissions output: never silently overwrite a
        # source or prior acceptance; no plaintext appears in terminal logs.
        args.out.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(args.out, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(updated, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        print(f"Researcher-confirmed candidate saved as NEW sensitive case: {args.out}")
        return 0
    except (CaseError, ValueError, TypeError, KeyError, OSError) as exc:
        print(f"ERROR candidate acceptance: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
