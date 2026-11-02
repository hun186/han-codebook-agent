"""Bounded cross-message cipher context for comparing unverified candidates.

Only ciphertext IDs, token positions and EXPLICIT trusted anchors enter this
evidence view. Never reinterpret a model guess as an aligned known plaintext.
Metadata remains opt-in and is never copied into this helper.
"""
from __future__ import annotations

from typing import Any

MAX_TARGETS = 15
MAX_OCCURRENCES_PER_TARGET = 6
MAX_NEIGHBOR_DISTANCE = 2
MAX_CANDIDATES = 5


def _neighbor(code: str, anchors: dict[str, str]) -> dict[str, str]:
    item = {"code": code, "status": "verified_alignment" if code in anchors else "unknown"}
    if code in anchors:
        item["verified_term"] = anchors[code]
    return item


def cross_message_context(case: dict[str, Any], *,
                          selected: list[str], anchors: dict[str, str],
                          proposals: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Group distinct message occurrences for each target with trusted boundaries.

    The selection prefers different messages ahead of repeated positions,
    preserving stable case order. The record is a research prompt, NOT a
    cryptographic proof, and never reads gold / ground_truth.
    """
    messages = case["messages"]
    result: dict[str, Any] = {}
    for code in selected[:MAX_TARGETS]:
        if code in anchors or code not in proposals:
            continue
        present = [
            (message, index)
            for message in messages
            for index, item in enumerate(message["codes"])
            if item == code
        ]
        distinct = []
        repeated = []
        seen = set()
        for item in present:
            message_id = item[0]["id"]
            if message_id in seen:
                repeated.append(item)
            else:
                distinct.append(item)
                seen.add(message_id)
        samples = []
        for message, index in (distinct + repeated)[:MAX_OCCURRENCES_PER_TARGET]:
            codes = message["codes"]
            start = max(index - MAX_NEIGHBOR_DISTANCE, 0)
            end = min(index + MAX_NEIGHBOR_DISTANCE + 1, len(codes))
            samples.append({
                "message_id": message["id"],
                "target_offset": index,
                "window_start": start,
                "sequence": [_neighbor(item, anchors) for item in codes[start:end]],
            })
        proposed = proposals[code]
        alternatives = proposed.get("alternatives", [])
        # A top-ranked guess is only a model/statistical hypothesis.
        candidates = list(dict.fromkeys(
            item.get("term") for item in alternatives[:MAX_CANDIDATES]
            if isinstance(item, dict) and isinstance(item.get("term"), str)
        ))
        if proposed.get("term") not in candidates and isinstance(proposed.get("term"), str):
            candidates = [proposed["term"]] + candidates[:MAX_CANDIDATES-1]
        result[code] = {
            "status": "hypothesis_unverified",
            "candidate_comparison": candidates,
            "total_occurrences": len(present),
            "sampled_occurrences": samples,
            "sample_truncated": len(present) > len(samples),
            "research_question": (
                "Compare these unverified candidates against the same cipher "
                "code across DIFFERENT messages. Look for contradictions to "
                "the current top candidate; do not infer plaintext from "
                "untrusted metadata or call a guess verified."
            ),
        }
    return result


def check_evidence_refs(code: str, items: Any,
                        messages: list[dict[str, Any]]) -> list[str]:
    """Keep only real, distinct message IDs containing the exact target code.

    A valid reference is a *pointer*, not proof the candidate is correct.
    """
    if not isinstance(items, list):
        return []
    containing = {m["id"] for m in messages if code in m["codes"]}
    out = []
    for item in items:
        if isinstance(item, str) and item in containing and item not in out:
            out.append(item)
            if len(out) >= 6:
                break
    return out
