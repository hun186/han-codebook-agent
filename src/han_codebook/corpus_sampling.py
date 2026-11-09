"""Bounded, deterministic corpus-wide evidence sampling for LLM prompts.

Prompts contain a subset of real messages, not decoded plaintext and never an
evaluation oracle. All input fields are filtered later by safe_llm_message.
"""
from __future__ import annotations


def sample_corpus_messages(messages: list[dict], *,
                           focus_codes: list[str], limit: int = 100) -> list[dict]:
    """Prefer diverse occurrences of target codes, then sample entire timeline.

    Preserve input order, limit message count and avoid the first-100-only blind
    spot for 400/1000-message cases. No random calls, network, Gold, or input
    mutation. Caller retains responsibility for redacting free-form metadata.
    """
    if type(limit) is not int or limit < 1 or limit > 100:
        raise ValueError("sample limit must be an integer 1..100")
    if len(messages) <= limit:
        return list(messages)
    chosen: set[int] = set()
    # Three strata per target across the full corpus. Avoid wasting slots on
    # dozens of repeated occurrences of the same popular code at the start.
    for code in dict.fromkeys(focus_codes):
        indices = [i for i, m in enumerate(messages) if code in m["codes"]]
        if not indices:
            continue
        for i in (indices[0], indices[len(indices)//2], indices[-1]):
            chosen.add(i)
            if len(chosen) >= limit:
                break
        if len(chosen) >= limit:
            break
    # Evenly spread remaining slots over all messages, including late ones.
    n = len(messages)
    for j in range(limit):
        i = (j * (n - 1)) // max(1, limit - 1)
        chosen.add(i)
        if len(chosen) >= limit:
            break
    # Safety net for duplicate indices with pathological small/large limits.
    if len(chosen) < limit:
        for i in range(n):
            chosen.add(i)
            if len(chosen) == limit:
                break
    return [messages[i] for i in sorted(chosen)[:limit]]
