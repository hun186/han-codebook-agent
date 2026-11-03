"""Validate ciphertext structure without triggering language/segmentation paths.

Only explicit known-pair alignments are inspected for contradictions. A
plaintext-only pair must never become a verified anchor here.
"""
from __future__ import annotations

from typing import Any

from .core import CaseError

MAX_MESSAGES = 20_000
MAX_CIPHER_TOKENS = 100_000
MAX_DISTINCT_CODES = 2_048
MAX_MESSAGE_ID_LENGTH = 128
MAX_CODE_LENGTH = 64
FORBIDDEN = frozenset(("gold", "ground_truth", "codebook"))


def trusted_cipher_code_ids(case: dict[str, Any]) -> set[str]:
    """Return structurally trusted code IDs without inferring phrase segments.

    Ignore unused semantic profiles, researcher marks, unsegmented plaintext
    and source notes. Explicit segments are read only to detect contradictory
    anchors; no Chinese terms enter the structural report or null control.
    """
    if not isinstance(case, dict) or FORBIDDEN.intersection(case):
        raise CaseError("Cipher-only input is not a mapping or contains an oracle")
    messages = case.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= MAX_MESSAGES:
        raise CaseError("Cipher-only input requires 1..20000 messages")
    by_id: dict[str, list[str]] = {}
    distinct: set[str] = set()
    total = 0
    for message in messages:
        if not isinstance(message, dict) or FORBIDDEN.intersection(message):
            raise CaseError("Message must be a mapping without an evaluation oracle")
        mid, codes = message.get("id"), message.get("codes")
        if (not isinstance(mid, str) or not 1 <= len(mid) <= MAX_MESSAGE_ID_LENGTH
                or mid in by_id):
            raise CaseError("Message IDs must be unique bounded nonempty strings")
        if (not isinstance(codes, list) or not codes
                or any(not isinstance(code, str)
                       or not 1 <= len(code) <= MAX_CODE_LENGTH
                       or not code.isdigit() for code in codes)):
            raise CaseError("Cipher groups must be bounded nonempty digit strings")
        total += len(codes)
        if total > MAX_CIPHER_TOKENS:
            raise CaseError("Cipher corpus exceeds diagnostic token cap")
        by_id[mid] = codes
        distinct.update(codes)
        if len(distinct) > MAX_DISTINCT_CODES:
            raise CaseError("Cipher corpus exceeds diagnostic distinct-code cap")

    pairs = case.get("known_pairs", [])
    if not isinstance(pairs, list):
        raise CaseError("Known pairs must be an array")
    trusted: dict[str, str] = {}
    for pair in pairs:
        if not isinstance(pair, dict) or FORBIDDEN.intersection(pair):
            raise CaseError("Known pair must be a mapping without an oracle")
        mid = pair.get("message_id")
        if not isinstance(mid, str) or mid not in by_id:
            raise CaseError("Known pair references a missing cipher message")
        if "segments" not in pair:
            # The long plaintext is neither read nor segmented.
            continue
        segments = pair["segments"]
        codes = by_id[mid]
        if (not isinstance(segments, list) or len(segments) != len(codes)
                or any(not isinstance(term, str) or not term for term in segments)):
            raise CaseError("Explicit trusted segments must match cipher group count")
        if "plaintext" in pair and pair["plaintext"] is not None:
            if (not isinstance(pair["plaintext"], str)
                    or "".join(segments) != pair["plaintext"]):
                raise CaseError("Explicit segments contradict attached plaintext")
        for code, term in zip(codes, segments):
            if code in trusted and trusted[code] != term:
                raise CaseError("Contradictory explicit trusted code alignments")
            trusted[code] = term
    return set(trusted)
