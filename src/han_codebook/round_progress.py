"""Observable, oracle-free progress diagnostics for multi-round code research.

No correctness claim can be made without independent scoring. This module
only records search/rank movement and lack of additional proposal evidence.
"""
from __future__ import annotations

from typing import Any


def _top5(result: dict[str, Any]) -> dict[str, tuple[str, ...]]:
    return {
        code: tuple(item.get("term") for item in proposal.get("alternatives", [])[:5]
                    if isinstance(item, dict) and isinstance(item.get("term"), str))
        for code, proposal in result.get("proposals", {}).items()
        if proposal.get("status") == "hypothesis_unverified"
    }


def round_progress_diagnosis(previous: dict[str, Any],
                             current: dict[str, Any], *,
                             new_coverage_count: int,
                             fresh_hint_pairs: int,
                             accepted_vocabulary_terms: int,
                             stale_rounds: int,
                             stop_patience: int) -> dict[str, Any]:
    """Identify *lack of observable movement*, not evidence of accuracy."""
    before = _top5(previous)
    after = _top5(current)
    first_choice_changes = sum(
        previous["proposals"][c]["term"] != current["proposals"][c]["term"]
        for c in before.keys() & after.keys()
    )
    rank_changes = sum(before[code] != after[code]
                       for code in before.keys() & after.keys())
    no_observable_movement = first_choice_changes == 0 and rank_changes == 0
    no_new_evidence = (
        new_coverage_count == 0
        and fresh_hint_pairs == 0
        and accepted_vocabulary_terms == 0
    )
    stalled = no_observable_movement and no_new_evidence
    streak = stale_rounds + 1 if stalled else 0
    return {
        "first_choice_changes": first_choice_changes,
        "top5_ranking_changes": rank_changes,
        "new_research_coverage": new_coverage_count,
        "new_model_suggestion_pairs": fresh_hint_pairs,
        "new_auto_vocabulary_terms": accepted_vocabulary_terms,
        "no_first_choice_change": first_choice_changes == 0,
        "no_observable_rank_movement": no_observable_movement,
        "new_suggestions_without_rank_movement": no_observable_movement and fresh_hint_pairs > 0,
        "no_new_evidence_or_rank_movement": stalled,
        "consecutive_stalled_rounds": streak,
        "stop_recommended": stop_patience > 0 and streak >= stop_patience,
        "quality_note": "Observable movement is NOT correctness or verified decipherment",
    }
