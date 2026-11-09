"""Presentation-only uncertainty diagnostics: never infer oracle-backed accuracy.

The coordinate solver keeps its original complete Top-N hypotheses. This module
only marks unsupported presentation claims, not verified mappings or weights.
"""
from __future__ import annotations

from collections import Counter
from math import ceil


def mark_presentation_uncertainty(proposals: dict, vocabulary_size: int) -> dict:
    """Annotate guesses without changing candidate terms, ranking or anchors.

    A tiny uncalibrated score gap is NOT a probability. When one word is mapped
    to a large fraction of different codes, that may be a model collapse, not
    evidence of successful decoding. Both are presentation-only heuristics.
    """
    unknown = {code: item for code, item in proposals.items()
               if item.get("status") == "hypothesis_unverified"}
    count = len(unknown)
    by_term = Counter(item["term"] for item in unknown.values())
    top_term, top_count = by_term.most_common(1)[0] if by_term else ("", 0)
    collapse = count >= 10 and top_count >= max(5, ceil(count * 0.25))
    tied = 0
    hidden = 0
    for item in unknown.values():
        gap = item.get("score_gap_to_second")
        near_tie = (len(item.get("alternatives", ())) >= 2
                    and type(gap) in (int, float) and 0 <= gap <= 0.001)
        if near_tie:
            tied += 1
        repeated = collapse and item["term"] == top_term
        uncertain = bool(near_tie or repeated)
        item["presentation_abstained"] = uncertain
        item["presentation_reason"] = (
            "near_tied_rank" if near_tie else "concentrated_mapping" if repeated
            else None
        )
        if uncertain:
            hidden += 1
    return {
        "unknown_codes": count,
        "candidate_vocabulary_size": vocabulary_size,
        "distinct_top_terms": len(by_term),
        "dominant_unverified_term_code_count": top_count,
        "dominant_unverified_term_fraction": round(top_count / count, 4) if count else None,
        "near_tied_unverified_code_count": tied,
        "presentation_abstained_code_count": hidden,
        "concentrated_mapping_warning": collapse,
        "scope": "Heuristic for displaying uncertainty; not calibrated confidence or decryption accuracy",
    }
