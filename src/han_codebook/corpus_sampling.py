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
    # Reserve space for entire-corpus sampling even if target codes are
    # concentrated early. The caller targets <=15 codes; limit also guards
    # direct uses of this helper with a larger supplied focus list.
    for code in list(dict.fromkeys(focus_codes))[:min(15, limit // 4)]:
        indices = [i for i, m in enumerate(messages) if code in m["codes"]]
        if not indices:
            continue
        for i in (indices[0], indices[len(indices)//2], indices[-1]):
            chosen.add(i)
    n = len(messages)
    remaining = limit - len(chosen)
    # The earlier implementation used the first 'remaining' points of a
    # 100-point grid, which accidentally removed late messages. Build a fresh
    # grid for the *remaining* number of slots across [0, n-1].
    if remaining == 1:
        chosen.add(n - 1)
    elif remaining > 1:
        for j in range(remaining):
            chosen.add((j * (n - 1)) // (remaining - 1))
    if len(chosen) < limit:
        # Target strata may overlap with the even grid. Fill those gaps by
        # sampling the still-unused indices over the ENTIRE corpus.
        available = [i for i in range(n) if i not in chosen]
        count = limit - len(chosen)
        if count == 1:
            chosen.add(available[len(available) // 2])
        else:
            for j in range(count):
                chosen.add(available[(j * (len(available) - 1)) // (count - 1)])
    return [messages[i] for i in sorted(chosen)]
