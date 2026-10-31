"""Offline held-out validation of review-only plaintext segmentation proposals.

For each reliably segmented known-pair message, withhold ALL records for that
message. Generate bounded alignment proposals using only the remaining trusted
pairs and operator-supplied profile priors. Reference segmentation is consulted
ONLY after the proposal call, for scoring; never put it in a prompt/solver.

The report intentionally contains no source plaintext, reference segments,
proposed segments, or model scores. This is not blind historical decipherment.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any

from .core import CaseError, validate_case
from .unaligned_review import MAX_PLAINTEXT, _verified_and_vocabulary, review_unsegmented


def evaluate_segmentation_holdout(case: dict[str, Any], *, max_folds: int = 10,
                                  top_n: int = 8, beam_width: int = 96) -> dict[str, Any]:
    """Assess independent held-out message segmentations without answer leakage."""
    if not isinstance(case, dict) or any(
        key in case for key in ("gold", "ground_truth", "codebook")
    ):
        raise CaseError("segmentation holdout must not accept embedded evaluation oracle")
    if type(max_folds) is not int or not 1 <= max_folds <= 100:
        raise CaseError("max_folds must be an integer from 1 to 100")
    if type(top_n) is not int or not 1 <= top_n <= 12:
        raise CaseError("top_n must be an integer from 1 to 12")
    if type(beam_width) is not int or not 8 <= beam_width <= 256:
        raise CaseError("beam_width must be an integer from 8 to 256")

    # Historical annotations and ideas may encode the held-out answer. They
    # are never features of this evaluator, even for a different message.
    source = deepcopy(case)
    for key in ("hypothesis_marks", "bold_hypotheses", "candidate_ideas",
                "hypothesis_revision_history", "candidate_revision_history"):
        source.pop(key, None)
    validate_case(source)
    _verified_and_vocabulary(source)  # Fail closed on contradictory trusted pairs.

    messages = {m["id"]: m for m in source["messages"]}
    aligned: dict[str, list[dict[str, Any]]] = {}
    unaligned_count = 0
    for pair in source.get("known_pairs", []):
        if "segments" in pair:
            aligned.setdefault(pair["message_id"], []).append(pair)
        else:
            unaligned_count += 1
    if not aligned:
        raise CaseError("segmentation holdout requires a trusted segmented known pair")

    folds: list[dict[str, Any]] = []
    scored = top1_hits = topn_hits = skipped_length = overlaps = 0
    for message_id, records in list(aligned.items())[:max_folds]:
        # Conflicting duplicates are already rejected above, and the full
        # segmented truth remains private in this post-inference function.
        expected = list(records[0]["segments"])
        ciphertext_codes = messages[message_id]["codes"]
        plain = "".join(expected)

        folded = deepcopy(source)
        # Remove ALL reference records for this message, including duplicate
        # alignments and unsegmented plaintext, AND exclude all OTHER
        # unsegmented records (they are not trusted constraints).
        folded["known_pairs"] = [
            p for p in folded.get("known_pairs", [])
            if p["message_id"] != message_id and "segments" in p
        ]
        remaining_anchors, _ = _verified_and_vocabulary(folded)
        overlap_codes = len(set(ciphertext_codes) & set(remaining_anchors))
        folded["known_pairs"].append({
            "message_id": message_id, "plaintext": plain
        })
        rank: int | None = None
        candidates_seen = 0
        if len(plain) > MAX_PLAINTEXT:
            skipped_length += 1
            outcome = "not_scored_plaintext_over_limit"
        else:
            # The holdout answer crosses NO inference boundary except as
            # unsplit plaintext (the real-world user-supplied input form).
            results = review_unsegmented(
                folded, top_n=top_n, beam_width=beam_width
            )
            rows = [r for r in results["reviews"]
                    if r["message_id"] == message_id]
            if len(rows) != 1:
                raise CaseError("expected one isolated held-out review row")
            proposals = rows[0]["candidates"]
            candidates_seen = len(proposals)
            # Compare to the segmented reference ONLY after inference.
            rank = next((idx for idx, candidate in enumerate(proposals, 1)
                         if candidate["segments"] == expected), None)
            outcome = ("overlap_excluded_from_independent" if overlap_codes
                       else "scored")
            if overlap_codes:
                overlaps += 1
            else:
                scored += 1
                top1_hits += rank == 1
                topn_hits += rank is not None
        folds.append({
            "heldout_message_id": message_id,
            "withheld_record_count": sum(
                p["message_id"] == message_id
                for p in source.get("known_pairs", [])
            ),
            "code_group_count": len(ciphertext_codes),
            "overlap_code_groups_excluded": overlap_codes,
            "candidate_count": candidates_seen,
            "exact_reference_rank": rank,
            "outcome": outcome,
        })

    return {
        "case_id": source.get("case_id", "unnamed"),
        "method": "offline leave-one-segmented-message-out; post-inference comparison",
        "available_fold_count": len(aligned),
        "evaluated_fold_count": len(folds),
        "unsegmented_records_not_scored": unaligned_count,
        "summary": {
            "independent_scored_folds": scored,
            "independent_exact_top1_hits": top1_hits,
            "independent_exact_topn_hits": topn_hits,
            "independent_exact_top1_rate": top1_hits / scored if scored else None,
            "independent_exact_topn_rate": topn_hits / scored if scored else None,
            "overlap_folds_excluded": overlaps,
            "too_long_folds_not_scored": skipped_length,
        },
        "folds": folds,
        "limitations": [
            "This checks exact segmentation, not real decipherment accuracy.",
            "Any remaining externally anchored code excludes that entire fold from the independent rate.",
            "Operator profiles may already contain the reference phrases: this is not a blind vocabulary test.",
            "Beam pruning may miss the correct alignment; no calibrated probability is provided.",
            "No candidate, reference phrases, plaintext, or gold labels are serialized.",
            "No LLM calls and no automatic known-pair promotion are performed.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, type=Path)
    parser.add_argument("--out", type=Path,
                        default=Path("artifacts/segmentation_holdout.json"))
    parser.add_argument("--max-folds", type=int, default=10)
    parser.add_argument("--top-n", type=int, default=8)
    parser.add_argument("--beam-width", type=int, default=96)
    args = parser.parse_args(argv)
    try:
        case = json.loads(args.case.read_text(encoding="utf-8"))
        report = evaluate_segmentation_holdout(
            case, max_folds=args.max_folds, top_n=args.top_n,
            beam_width=args.beam_width
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2)
                            + "\n", encoding="utf-8")
        print("Offline segmentation holdout: "
              f"{report['evaluated_fold_count']} evaluated folds")
        print(f"Saved no-plaintext metrics: {args.out}")
        return 0
    except (CaseError, ValueError, TypeError, KeyError, OSError) as exc:
        print(f"ERROR segmentation holdout: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
