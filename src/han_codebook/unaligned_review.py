"""Offline candidate alignment for unsegmented known plaintext (review ONLY).

This module deliberately does not modify known_pairs, add verified anchors, or
call a model. It explores bounded hypotheses over the code-group sequence,
respecting trusted *other* segmented pairs and repeated code identities.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any

from .core import CaseError, validate_case

MAX_PLAINTEXT = 500
MAX_EXPANSIONS = 2_000_000


def _verified_and_vocabulary(case: dict[str, Any]) -> tuple[dict[str, str], set[str]]:
    """Only independently segmented pairs may lock an anchor; no oracle inputs."""
    trusted: dict[str, str] = {}
    vocabulary = {
        term
        for profile in case["profiles"].values()
        for term in profile.get("lexicon", {})
    }
    vocabulary.update(
        term for profile in case["profiles"].values()
        for sentence in profile.get("sentences", [])
        for term in sentence
    )
    messages = {message["id"]: message for message in case["messages"]}
    for pair in case.get("known_pairs", []):
        if "segments" not in pair:
            continue
        codes = messages[pair["message_id"]]["codes"]
        if len(pair["segments"]) != len(codes):
            raise CaseError(f"known pair {pair['message_id']}: segment count must match code count")
        for code, term in zip(codes, pair["segments"]):
            if code in trusted and trusted[code] != term:
                raise CaseError(f"conflicting verified known plaintext for code {code}")
            trusted[code] = term
            vocabulary.add(term)
    return trusted, vocabulary


def _segment_score(term: str, vocabulary: set[str]) -> float:
    """Heuristic ranking, not a probability or calibrated model confidence."""
    if term in vocabulary:
        return 3.0 + 0.25 * len(term)
    return 0.0 if len(term) == 1 else -2.5 * len(term)


def suggest_alignments(plaintext: str, codes: list[str],
                       vocabulary: set[str], trusted: dict[str, str], *,
                       top_n: int = 8, beam_width: int = 96) -> dict[str, Any]:
    """Finite bounded-beam search with code repetition and immutable anchors.

    Beam pruning can miss a plausible alignment: even the top-ranked candidate
    is *never* verified without explicit human acceptance via existing APIs.
    """
    if not isinstance(plaintext, str) or not plaintext or len(plaintext) > MAX_PLAINTEXT:
        raise CaseError("review plaintext must contain 1..500 characters")
    if (not isinstance(codes, list) or not codes or
            any(not isinstance(c, str) or not c.isdigit() for c in codes)):
        raise CaseError("cipher codes must be nonempty numeric strings")
    if type(top_n) is not int or not 1 <= top_n <= 12:
        raise CaseError("top_n must be an integer from 1 to 12")
    if type(beam_width) is not int or not 8 <= beam_width <= 256:
        raise CaseError("beam_width must be an integer from 8 to 256")
    if not isinstance(vocabulary, set) or not all(
            isinstance(v, str) and v for v in vocabulary):
        raise CaseError("vocabulary must be a set of nonempty phrases")
    if not isinstance(trusted, dict) or not all(
            isinstance(k, str) and isinstance(v, str) and v
            for k, v in trusted.items()):
        raise CaseError("trusted anchors must map code groups to phrases")

    if len(plaintext) < len(codes):
        return {"status": "no_feasible_alignment", "candidates": [],
                "beam_pruned": False, "expanded_states": 0}
    repeated = {code for code, count in Counter(codes).items() if count > 1}
    # (heuristic_score, character_offset, segments, repeated_unknown_assignments)
    states: list[tuple[float, int, tuple[str, ...], tuple[tuple[str, str], ...]]] = [
        (0.0, 0, (), ())
    ]
    pruned = False
    expansions = 0
    size = len(plaintext)
    for index, code in enumerate(codes):
        slots_after = len(codes) - index - 1
        next_states = []
        for score, offset, pieces, assignments in states:
            saved = dict(assignments)
            forced = trusted.get(code, saved.get(code))
            if forced is not None:
                endings = [offset + len(forced)] if plaintext.startswith(forced, offset) else []
            else:
                endings = range(offset + 1, size - slots_after + 1)
            for end in endings:
                if end > size - slots_after or (slots_after == 0 and end != size):
                    # The final code must consume the ENTIRE known plaintext
                    # before ranking/pruning; a partial suffix is not a solution.
                    continue
                expansions += 1
                if expansions > MAX_EXPANSIONS:
                    raise CaseError("alignment search budget exceeded; provide confirmed segments or fewer codes")
                term = plaintext[offset:end]
                if not term:
                    continue
                next_assignments = saved
                if code in repeated and code not in trusted and code not in saved:
                    next_assignments = {**saved, code: term}
                next_states.append((
                    score + _segment_score(term, vocabulary),
                    end, pieces + (term,),
                    tuple(sorted(next_assignments.items()))
                ))
        if not next_states:
            states = []
            break
        # Keep different prefix offsets and repeated-code choices, but prune
        # globally to guarantee bounded search even for 500-character text.
        next_states.sort(key=lambda x: (-x[0], x[2]))
        if len(next_states) > beam_width:
            pruned = True
        states = next_states[:beam_width]
    final = []
    seen = set()
    for score, offset, pieces, _ in sorted(states, key=lambda x: (-x[0], x[2])):
        if offset != size or pieces in seen:
            continue
        seen.add(pieces)
        final.append({
            "segments": list(pieces),
            "heuristic_score": round(score, 4),
            "status": "candidate_unverified",
        })
        if len(final) == top_n:
            break
    return {
        "status": "manual_confirmation_required" if final else "no_feasible_alignment",
        "candidates": final,
        "beam_pruned": pruned,
        "expanded_states": expansions,
    }


def review_unsegmented(case: dict[str, Any], *, top_n: int = 8,
                       beam_width: int = 96) -> dict[str, Any]:
    """Return proposals, not a revised case or verified plaintext."""
    if not isinstance(case, dict) or any(
        key in case for key in ("gold", "ground_truth", "codebook")
    ):
        raise CaseError("alignment review must not accept embedded evaluation oracle")
    # core.validate_case() normally invokes legacy recursive suggestion
    # generation when mark/bold keys exist, even if they are empty. Validate
    # the base case first without triggering that unbounded search, then
    # validate annotations against ONLY independently verified anchors.
    base_case = dict(case)
    base_case.pop("hypothesis_marks", None)
    base_case.pop("bold_hypotheses", None)
    validate_case(base_case)
    trusted, vocab = _verified_and_vocabulary(case)
    if "hypothesis_marks" in case:
        from .hypothesis_marks import normalize_marks
        normalize_marks(case, trusted)
    if "bold_hypotheses" in case:
        from .bold_hypotheses import normalize_bold_hypotheses
        normalize_bold_hypotheses(case, trusted)
    by_id = {m["id"]: m["codes"] for m in case["messages"]}
    rows = []
    for record_index, pair in enumerate(case.get("known_pairs", [])):
        if "segments" in pair:
            continue
        mid = pair["message_id"]
        result = suggest_alignments(
            pair["plaintext"], by_id[mid], vocab, trusted,
            top_n=top_n, beam_width=beam_width
        )
        rows.append({
            "known_pair_index": record_index,
            "message_id": mid,
            "code_groups": list(by_id[mid]),
            "verified_constraints_used": sum(c in trusted for c in by_id[mid]),
            **result,
        })
    return {
        "case_id": case.get("case_id", "unnamed"),
        "method": "offline bounded-beam plaintext alignment; review only",
        "review_required": True,
        "trusted_anchor_count_unchanged": len(trusted),
        "unaligned_pair_count": len(rows),
        "reviews": rows,
        "limitations": [
            "Top candidates are heuristics, not probabilities or verified alignments.",
            "Beam pruning may omit a valid segmentation, even if no candidates remain.",
            "Suggestions never change known_pairs or promote inferred words to trusted anchors.",
            "Only independently segmented known pairs constrain codes; neither gold nor LLM is used.",
            "The report contains user-supplied plaintext and must be treated as sensitive research data.",
            "Researcher must explicitly confirm one complete alignment separately before it can become a trusted known pair.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--out", type=Path,
                        default=Path("artifacts/unaligned_review.json"))
    parser.add_argument("--top-n", type=int, default=8)
    parser.add_argument("--beam-width", type=int, default=96)
    args = parser.parse_args(argv)
    try:
        case = json.loads(args.case.read_text(encoding="utf-8"))
        report = review_unsegmented(
            case, top_n=args.top_n, beam_width=args.beam_width
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2)
                            + "\n", encoding="utf-8")
        print(f"Review-only alignment: {report['unaligned_pair_count']} unsegmented pairs")
        print(f"Saved sensitive offline review candidates: {args.out}")
        return 0
    except (CaseError, ValueError, TypeError, KeyError, OSError) as exc:
        print(f"ERROR alignment review: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
