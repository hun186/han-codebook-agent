"""Offline structural context recurrence across distinct cipher messages.

Not a plaintext decoder, a correctness score, or a source of verified anchors.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
from typing import Any

from .core import CaseError, anchors_and_review, validate_case

MAX_TOKENS = 100_000
MAX_CODES = 2_048
MAX_PATTERNS = 50
MAX_MESSAGE_SAMPLES = 6
FORBIDDEN = frozenset(("gold", "ground_truth", "codebook"))


def structure_report(case: dict[str, Any]) -> dict[str, Any]:
    """Compare same-sided cipher neighbors after holding out each message.

    One message contributes one vote per (code, side, neighbor). It can
    have repeated code occurrences, but cannot independently support itself.
    """
    if not isinstance(case, dict):
        raise CaseError("Case must be a mapping")
    if FORBIDDEN.intersection(case):
        raise CaseError("Evaluation answers are prohibited")
    if isinstance(case.get("messages"), list):
        if any(isinstance(m, dict) and FORBIDDEN.intersection(m)
               for m in case["messages"]):
            raise CaseError("Embedded evaluation answers are prohibited")
    validate_case(case)
    messages = case["messages"]
    total = sum(len(m["codes"]) for m in messages)
    if total > MAX_TOKENS:
        raise CaseError("Cipher corpus exceeds diagnostic token cap")
    anchors, _, _ = anchors_and_review(case)
    occurrences: Counter[str] = Counter()
    by_code: dict[str, dict[str, set[tuple[str, str]]]] = defaultdict(dict)
    patterns: dict[tuple[str, ...], set[str]] = defaultdict(set)

    for message in messages:
        mid = message["id"]
        codes = message["codes"]
        neighbors: dict[str, set[tuple[str, str]]] = defaultdict(set)
        for i, code in enumerate(codes):
            occurrences[code] += 1
            neighbors[code]  # retain single-code messages without neighbors
            if i:
                neighbors[code].add(("left", codes[i - 1]))
            if i + 1 < len(codes):
                neighbors[code].add(("right", codes[i + 1]))
        for code, contexts in neighbors.items():
            by_code[code][mid] = contexts
        for size in (2, 3):
            for i in range(len(codes) - size + 1):
                patterns[tuple(codes[i:i + size])].add(mid)
    if len(by_code) > MAX_CODES:
        raise CaseError("Cipher corpus exceeds diagnostic distinct-code cap")

    rows = []
    total_assessments = any_neighbor = anchored_neighbor = repeat_codes = 0
    for code in sorted(by_code):
        if code in anchors:
            continue
        contexts_by_mid = by_code[code]
        frequency = Counter(
            neighbor for contexts in contexts_by_mid.values() for neighbor in contexts
        )
        with_any = sum(
            any(frequency[neighbor] > 1 for neighbor in contexts)
            for contexts in contexts_by_mid.values()
        )
        with_anchor = sum(
            any(frequency[neighbor] > 1 and neighbor[1] in anchors
                for neighbor in contexts)
            for contexts in contexts_by_mid.values()
        )
        n = len(contexts_by_mid)
        total_assessments += n
        any_neighbor += with_any
        anchored_neighbor += with_anchor
        repeat_codes += int(n >= 2)
        rows.append({
            "code": code,
            "occurrences": occurrences[code],
            "distinct_messages": n,
            "heldout_same_sided_neighbor": with_any,
            "heldout_same_sided_verified_code_neighbor": with_anchor,
            "different_left_codes": len({
                other for contexts in contexts_by_mid.values()
                for side, other in contexts if side == "left"
            }),
            "different_right_codes": len({
                other for contexts in contexts_by_mid.values()
                for side, other in contexts if side == "right"
            }),
        })
    repeated = [(seq, ids) for seq, ids in patterns.items() if len(ids) >= 2]
    repeated.sort(key=lambda p: (-len(p[1]), -len(p[0]), p[0]))
    return {
        "schema": "han_cipher_structure_lomo_v1",
        "scope": "same_sided_immediate_code_neighbors_in_distinct_messages",
        "privacy": "code_ids_only_no_metadata_words_candidates_or_oracle",
        "summary": {
            "message_count": len(messages),
            "cipher_token_count": total,
            "verified_code_count_excluded": len(anchors),
            "unknown_code_count": len(rows),
            "unknown_codes_seen_in_multiple_messages": repeat_codes,
            "heldout_message_code_assessments": total_assessments,
            "heldout_with_same_sided_neighbor": any_neighbor,
            "heldout_with_same_sided_verified_code_neighbor": anchored_neighbor,
            "repeated_patterns": len(repeated),
            "repeated_patterns_truncated": len(repeated) > MAX_PATTERNS,
        },
        "unknown_code_context": rows,
        "repeated_cipher_patterns": [
            {
                "codes": list(seq),
                "distinct_message_count": len(ids),
                "sample_message_ids": sorted(ids)[:MAX_MESSAGE_SAMPLES],
                "message_ids_truncated": len(ids) > MAX_MESSAGE_SAMPLES,
            }
            for seq, ids in repeated[:MAX_PATTERNS]
        ],
        "warning": (
            "This is leave-one-message-out structural recurrence only. "
            "Matching neighborhoods and proximity to verified cipher codes "
            "cannot validate candidate words, rank LLM rounds, or estimate "
            "decipherment accuracy. Missing recurrence is not a contradiction."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline cross-message cipher structure diagnostic, no LLM"
    )
    parser.add_argument("--case", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        case = json.loads(Path(args.case).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        parser.error("Input is not a readable valid JSON case")
    try:
        report = structure_report(case)
    except (CaseError, ValueError, TypeError) as exc:
        parser.error("Structural diagnostic input rejected: " + type(exc).__name__)
    data = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output = Path(args.out)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
    except OSError:
        parser.error("Cannot create NEW report; no existing file is overwritten")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
