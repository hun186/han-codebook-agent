"""Bounded, *two-hop* verified-anchor context for optional solver ablation.

Only plaintext terms from explicitly aligned, immutable trusted anchors
are used; no model guesses, metadata notes, synthetic gold or codebook oracle
is read. One target occurrence per message prevents repeated text dominating
the structural signal. This is a heuristic, NOT an alignment proof.
"""
from __future__ import annotations

from typing import Any

MAX_CONTEXT_MESSAGES_PER_CODE = 6


def two_hop_anchor_context(
    tagged_messages: list[tuple[dict[str, Any], str | None]],
    anchors: dict[str, str],
    unknown_codes: list[str],
) -> dict[str, list[tuple[str | None, str, str]]]:
    """Return (domain, left/right, verified_term) for anchors exactly 2 away.

    Direct neighbors are already covered by the ordinary bigram objective.
    Two-hop context is evaluated only as a bounded, opt-in weak prior.
    """
    unknown = set(unknown_codes)
    collected: dict[str, list[tuple[str | None, str, str]]] = {}
    seen_messages: dict[str, set[str]] = {}
    for message, domain in tagged_messages:
        codes = message["codes"]
        for pos, target in enumerate(codes):
            if target not in unknown:
                continue
            known = seen_messages.setdefault(target, set())
            if (message["id"] in known or
                    len(known) >= MAX_CONTEXT_MESSAGES_PER_CODE):
                continue
            neighbors = []
            if pos >= 2 and codes[pos - 2] in anchors:
                neighbors.append((domain, "left", anchors[codes[pos - 2]]))
            if pos + 2 < len(codes) and codes[pos + 2] in anchors:
                neighbors.append((domain, "right", anchors[codes[pos + 2]]))
            if neighbors:
                known.add(message["id"])
                collected.setdefault(target, []).extend(neighbors)
    return collected
