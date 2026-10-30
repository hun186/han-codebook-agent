"""Round-by-round, non-oracle LLM vocabulary expansion for the local agent.

New words are *unverified candidate vocabulary*, never trusted code alignments.
Researcher review is an optional callback; absence means automatic acceptance
within a bounded candidate budget, not automatic verification.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any, Callable

from .agent import query_local_llm
from .core import CaseError, validate_case
from .event_links import suggest_event_links
from .llm_evidence import safe_llm_message

MAX_NEW_TERMS_PER_ROUND = 32
MAX_DYNAMIC_TERMS = 128
MAX_CONTEXT_MESSAGES = 50


def vocabulary_packet(case: dict, *, round_number: int, metadata: bool,
                      current: dict | None, vocabulary: set[str]) -> dict:
    """Build a bounded packet from observable evidence + *unverified* current work."""
    validate_case(case)
    if any(key in case for key in ("gold", "ground_truth", "codebook")):
        raise CaseError("Adaptive vocabulary must not receive embedded evaluation answers")
    freq = Counter(code for m in case["messages"] for code in m["codes"])
    # Never present top-ranked guesses as verified plaintext, even in later rounds.
    proposals = (current or {}).get("proposals", {})
    unverified = [
        {"code": code, "candidate": p["term"]}
        for code, p in sorted(proposals.items())
        if p.get("status") == "hypothesis_unverified"
    ][:80]
    verified = [
        {"code": code, "term": p["term"]}
        for code, p in sorted(proposals.items())
        if p.get("status") == "verified_alignment"
    ][:80]
    return {
        "task": "generate_vocabulary",
        "mode": "adaptive_round",
        "round": round_number,
        "policy": ("Current guessed mappings are unverified; suggest additional Chinese "
                   "background words/patterns based on messages, independent observations "
                   "and competing hypotheses, without claiming a decoded message."),
        "corpus_statistics": {
            "messages_count": len(case["messages"]),
            "unique_cipher_groups": len(freq),
            "code_frequencies": dict(freq.most_common(150)),
        },
        "metadata_enabled": metadata,
        "messages": [safe_llm_message(m, metadata=metadata)
                     for m in case["messages"][:MAX_CONTEXT_MESSAGES]],
        "temporal_event_link_hypotheses": suggest_event_links(case)[:24] if metadata else [],
        "current_hypotheses_unverified": unverified,
        "verified_anchors": verified,
        "current_vocabulary": sorted(vocabulary)[:MAX_DYNAMIC_TERMS * 2],
        "requested_max_terms": MAX_NEW_TERMS_PER_ROUND,
        "requested_max_patterns": 10,
    }


def refresh_vocabulary(case: dict, *, round_number: int, metadata: bool,
                       current: dict | None, llm_settings: dict,
                       review: Callable[[int, list[dict]], list[str] | dict] | None = None,
                       query: Callable[..., dict] = query_local_llm,
                       on_exchange: Callable | None = None) -> tuple[dict, dict]:
    """One explicit private-model vocabulary request; review is opt-in.

    Rejects unknown returned words and disallows any partial case mutation.
    """
    from .agent import validate_llm_endpoint
    validate_llm_endpoint(llm_settings["base_url"],
                          allow_private_network=llm_settings.get("allow_private_network", False),
                          allowed_hosts=llm_settings.get("allowed_hosts", []))
    current_terms = {
        word for p in case["profiles"].values()
        for word in p.get("lexicon", {})
    }
    dynamic_terms = set(case["profiles"].get("llm_dynamic_candidates", {}).get("lexicon", {}))
    packet = vocabulary_packet(case, round_number=round_number, metadata=metadata,
                               current=current, vocabulary=current_terms)
    response = query(
        llm_settings["base_url"], llm_settings["model"], packet,
        timeout=llm_settings.get("timeout_seconds", 90),
        allow_private_network=llm_settings.get("allow_private_network", False),
        allowed_hosts=llm_settings.get("allowed_hosts", []),
        api_key_env=llm_settings.get("api_key_env"),
        on_exchange=on_exchange,
    )
    entries = response.get("vocabulary")
    if not isinstance(entries, list):
        raise CaseError("Adaptive LLM vocabulary response must contain vocabulary array")
    candidates = []
    seen = set(current_terms)
    for item in entries[:128]:
        word = item.get("term") if isinstance(item, dict) else item
        reason = item.get("reason", "") if isinstance(item, dict) else ""
        if (not isinstance(word, str) or word != word.strip()
                or not 1 <= len(word) <= 24 or any(ord(ch) < 32 for ch in word)
                or word in seen):
            continue
        seen.add(word)
        candidates.append({"term": word, "reason": str(reason)[:250],
                           "status": "unverified", "source_round": round_number})
        if len(candidates) >= MAX_NEW_TERMS_PER_ROUND:
            break

    researcher_added = []
    if review is not None:
        decision = review(round_number, deepcopy(candidates))
        # Existing review callbacks returning a list stay compatible. The GUI
        # returns a structured decision with separately typed original/additions.
        if isinstance(decision, dict):
            if set(decision) != {"approved", "added"}:
                raise CaseError("Review decision must provide approved and added")
            selection, researcher_added = decision["approved"], decision["added"]
        else:
            selection = decision
        if (not isinstance(selection, list) or not isinstance(researcher_added, list)
                or any(not isinstance(w, str) for w in selection + researcher_added)
                or len(set(selection)) != len(selection)
                or any(w not in {x["term"] for x in candidates} for w in selection)):
            raise CaseError("Invalid selected LLM proposals in human review")
        if (len(selection) + len(researcher_added) > MAX_NEW_TERMS_PER_ROUND
                or len(set(researcher_added)) != len(researcher_added)
                or any(not 1 <= len(w) <= 24 or w != w.strip()
                       or any(ord(ch) < 32 for ch in w)
                       or w in current_terms or w in selection
                       or w in {x["term"] for x in candidates}
                       for w in researcher_added)):
            raise CaseError("Researcher-added candidates must be unique new words, 1..24 chars")
    else:
        selection = [x["term"] for x in candidates]

    remaining = max(0, MAX_DYNAMIC_TERMS - len(dynamic_terms))
    # Human-added words are kept as explicit provenance, never verified anchors.
    approved = (selection + researcher_added)[:remaining]
    adopted_manual = [w for w in researcher_added if w in approved]
    updated = deepcopy(case)
    if approved:
        slot = updated["profiles"].setdefault("llm_dynamic_candidates",
            {"keywords": [], "lexicon": {}, "sentences": []})
        for word in approved:
            slot["lexicon"][word] = 1.0  # weak prior; never a verified mapping
    record = {
        "round": round_number, "model": llm_settings["model"],
        "status": "unverified_candidate_vocabulary",
        "review_mode": "human" if review is not None else "automatic",
        "proposed": candidates,
        "approved": approved,
        "researcher_added": [{"term": w, "status": "unverified",
                               "source": "researcher", "source_round": round_number}
                              for w in adopted_manual],
        "rejected_count": len(candidates) - len([w for w in selection if w in approved]),
        "total_dynamic_terms": len(dynamic_terms) + len(approved),
        "metadata_used": metadata,
    }
    return updated, record
