"""Private non-oracle round-change warnings and reviewer checkpoints.

A persistent mapping can still be wrong. A model-first candidate can also be
wrong. This module detects disagreements and reversals; it NEVER picks a
winner from synthetic gold, the solver objective, or unblinded known pairs.
"""
from __future__ import annotations

from typing import Any

MAX_REVIEW_ITEMS_PER_ROUND = 50


def candidate_checkpoint(
    before: dict[str, Any] | None,
    after: dict[str, Any],
    previous_snapshots: list[dict[str, Any]],
    model_suggestions: list[dict[str, Any]],
    *,
    round_number: int,
) -> dict[str, Any]:
    old = (before or {}).get("proposals", {})
    new = after.get("proposals", {})
    hints = {
        item["code"]: item["candidates"][0]
        for item in model_suggestions
        if isinstance(item.get("code"), str)
        and isinstance(item.get("candidates"), list)
        and item["candidates"] and isinstance(item["candidates"][0], str)
    }
    items = []
    changed_count = 0
    review_candidate_count = 0
    disagreement_count = 0
    stable_replacement_count = 0
    for code in sorted(new):
        proposed = new[code]
        if proposed.get("status") != "hypothesis_unverified":
            continue
        current_term = proposed.get("term")
        previous_term = old.get(code, {}).get("term")
        model_first = hints.get(code)
        changed = previous_term is not None and previous_term != current_term
        disagreed = model_first is not None and model_first != current_term
        if not changed and not disagreed:
            continue
        review_candidate_count += 1
        changed_count += int(changed)
        disagreement_count += int(disagreed)
        # A minimum of two previous *snapshots* that agree is a stability
        # heuristic, never independent truth or a correctness score.
        recent = previous_snapshots[-2:]
        stable = (
            len(recent) == 2
            and all(s.get("proposals", {}).get(code, {}).get("term") ==
                    previous_term for s in recent)
        ) if changed else False
        stable_replacement_count += int(stable)
        flags = []
        if changed:
            flags.append("previous_round_first_choice_changed")
        if stable:
            flags.append("previously_stable_guess_replaced")
        if disagreed:
            flags.append("model_first_choice_differs_from_solver")
        if len(items) < MAX_REVIEW_ITEMS_PER_ROUND:
            candidates = [
                item["term"] for item in proposed.get("alternatives", [])[:5]
                if isinstance(item, dict) and isinstance(item.get("term"), str)
            ]
            items.append({
                "code": code,
                "round": round_number,
                "previous_unverified": previous_term if changed else None,
                "current_unverified": current_term,
                "model_first_unverified": model_first,
                "current_top5_unverified": candidates,
                "flags": flags,
                "needs_independent_confirmation": True,
            })
    return {
        "round": round_number,
        "label": "unverified_conflict_flags_not_accuracy",
        "changed_hypotheses": changed_count,
        "model_solver_first_choice_disagreements": disagreement_count,
        "previously_stable_guesses_replaced": stable_replacement_count,
        "review_items": items,
        "review_item_count": len(items),
        "truncated": review_candidate_count > MAX_REVIEW_ITEMS_PER_ROUND,
        "no_automatic_best_round_selection": True,
        "validation_warning": (
            "Previous stability and model agreement are NOT independent "
            "evidence of correctness. Do not compare LLM rounds using "
            "anchors already exposed to those rounds."
        ),
    }
