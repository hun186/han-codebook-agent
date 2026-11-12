"""Round-by-round, non-oracle LLM vocabulary expansion for the local agent.

New words are *unverified candidate vocabulary*, never trusted code alignments.
Researcher review is an optional callback; absence means automatic acceptance
within a bounded candidate budget, not automatic verification.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any, Callable

from .config import DEFAULT_LLM_TIMEOUT_SECONDS
from .agent import query_local_llm
from .core import CaseError, validate_case
from .event_links import suggest_event_links
from .llm_evidence import safe_llm_message

MAX_NEW_TERMS_PER_ROUND = 32
MAX_AUTO_ADOPT_WITH_CONTEXT_PER_ROUND = 8
MAX_DYNAMIC_TERMS = 128
MAX_CONTEXT_MESSAGES = 100

def link_adopted_targeted_hints(
    record: dict, *, trusted_anchors: dict[str, str],
    hints: dict[str, dict[str, float]], seen_pairs: set[tuple[str, str]],
) -> int:
    """Weakly associate an adopted novel term with its cited cipher code.

    Only the existing validated code/contrast/message gate is eligible. This
    remains an unverified LLM hint in the solver; never an immutable anchor.
    Repeated model opinions do not accumulate weight across rounds.
    """
    adopted = set(record.get("approved", []))
    linked = 0
    for proposal in record.get("proposed", []):
        if not isinstance(proposal, dict):
            continue
        code, term = proposal.get("target_code"), proposal.get("term")
        if (not isinstance(code, str) or code in trusted_anchors
                or not isinstance(term, str) or term not in adopted
                or not proposal.get("existing_candidate_contrast_traceable")
                or not proposal.get("context_reference_traceable")
                or not proposal.get("automatic_adoption_eligible")
                or (code, term) in seen_pairs):
            continue
        hints.setdefault(code, {})[term] = max(hints.get(code, {}).get(term, 0.0), 0.15)
        seen_pairs.add((code, term))
        linked += 1
    return linked



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
    from .corpus_sampling import sample_corpus_messages
    focus = set(row["code"] for row in unverified)
    focus_codes = sorted(focus or freq, key=lambda c: (-freq[c], c))[:15]
    sampled_messages = sample_corpus_messages(
        case["messages"], focus_codes=focus_codes, limit=MAX_CONTEXT_MESSAGES)
    verified = [
        {"code": code, "term": p["term"]}
        for code, p in sorted(proposals.items())
        if p.get("status") == "verified_alignment"
    ][:80]
    # Show a REAL current unverified code and an actual containing message.
    # This is a structural response example, NEVER a newly trusted word.
    example = None
    if current is not None:
        for hypothesis in unverified:
            source_ids = [
                message["id"] for message in sampled_messages
                if hypothesis["code"] in message["codes"]
            ]
            if source_ids:
                example = {
                    "target_code": hypothesis["code"],
                    "contrasted_candidate": hypothesis["candidate"],
                    "evidence_message_ids": source_ids[:2],
                    "contrast_reason": "explain why that current candidate is inadequate",
                }
                break
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
                     for m in sampled_messages],
        "corpus_context_sampling": {
            "total_messages": len(case["messages"]),
            "sampled_messages": len(sampled_messages),
            "strategy": "target_code_strata_then_even_full_corpus",
            "not_all_messages_shown": len(sampled_messages) < len(case["messages"]),
        },
        "temporal_event_link_hypotheses": suggest_event_links(case)[:24] if metadata else [],
        "current_hypotheses_unverified": unverified,
        "verified_anchors": verified,
        "current_vocabulary": sorted(vocabulary)[:MAX_DYNAMIC_TERMS * 2],
        "requested_max_terms": MAX_NEW_TERMS_PER_ROUND,
        "requested_max_patterns": 10,
        "output_contract": {
            "required_fields_for_automatic_adoption_with_prior_mapping": [
                "term", "reason", "evidence_message_ids", "target_code",
                "contrasted_candidate", "contrast_reason",
            ],
            "illustrative_existing_code_only": example,
            "instruction": (
                "Use the actual code and candidate from the current hypotheses. "
                "Each evidence ID must contain the target cipher group; do not "
                "treat model-generated justification as proof of plaintext."
            ),
        },
    }


def refresh_vocabulary(case: dict, *, round_number: int, metadata: bool,
                       current: dict | None, llm_settings: dict,
                       review: Callable[[int, list[dict]], list[str] | dict] | None = None,
                       query: Callable[..., dict] = query_local_llm,
                       on_exchange: Callable | None = None,
                       on_metrics: Callable | None = None) -> tuple[dict, dict]:
    """One explicit private-model vocabulary request; review is opt-in.

    Rejects unknown returned words and disallows any partial case mutation.
    """
    from .agent import validate_llm_endpoint
    validate_llm_endpoint(llm_settings["base_url"],
                          allow_private_network=llm_settings.get("allow_private_network", False),
                          allowed_hosts=llm_settings.get("allowed_hosts", []),
                          provider=llm_settings.get("provider", "local"),
                          allow_external_api=llm_settings.get("allow_external_api", False))
    current_terms = {
        word for p in case["profiles"].values()
        for word in p.get("lexicon", {})
    }
    # Example phrases are already in the solver's candidate space. Repeating
    # them as "new" model vocabulary does not constitute discovery.
    current_terms.update(
        word for p in case["profiles"].values()
        for sentence in p.get("sentences", []) for word in sentence
    )
    message_ids = {message["id"] for message in case["messages"]}
    messages_by_id = {message["id"]: message for message in case["messages"]}
    prior_hypotheses = {
        code: proposal for code, proposal in (current or {}).get("proposals", {}).items()
        if proposal.get("status") == "hypothesis_unverified"
    }
    is_empty_vocabulary_bootstrap = current is None
    dynamic_terms = set(case["profiles"].get("llm_dynamic_candidates", {}).get("lexicon", {}))
    packet = vocabulary_packet(case, round_number=round_number, metadata=metadata,
                               current=current, vocabulary=current_terms)
    response = query(
        llm_settings["base_url"], llm_settings["model"], packet,
        timeout=llm_settings.get("timeout_seconds", DEFAULT_LLM_TIMEOUT_SECONDS),
        allow_private_network=llm_settings.get("allow_private_network", False),
        allowed_hosts=llm_settings.get("allowed_hosts", []),
        api_key_env=llm_settings.get("api_key_env"),
        provider=llm_settings.get("provider", "local"),
        allow_external_api=llm_settings.get("allow_external_api", False),
        reasoning_effort=llm_settings.get("reasoning_effort"),
        response_format=llm_settings.get("response_format"),
        on_exchange=on_exchange,
        on_metrics=on_metrics,
        max_output_tokens=llm_settings.get("max_output_tokens"),
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
        references = item.get("evidence_message_ids") if isinstance(item, dict) else None
        traceable = (isinstance(reason, str) and bool(reason.strip())
                     and isinstance(references, list)
                     and 1 <= len(references) <= 3
                     and len(set(str(x) for x in references)) == len(references)
                     and all(isinstance(mid, str) and mid in message_ids
                             for mid in references))
        target = item.get("target_code") if isinstance(item, dict) else None
        compared = item.get("contrasted_candidate") if isinstance(item, dict) else None
        contrast_reason = item.get("contrast_reason", "") if isinstance(item, dict) else ""
        # A contrast is *checkable* only if it refers to this run's current
        # unverified mapping and the same cipher group in every cited message.
        # This is not semantic verification of the model's reason.
        valid_contrast = (
            isinstance(target, str) and target in prior_hypotheses
            and isinstance(compared, str)
            and compared == prior_hypotheses[target].get("term")
            and isinstance(contrast_reason, str) and bool(contrast_reason.strip())
            and traceable
            and all(target in messages_by_id[mid]["codes"] for mid in references)
        )
        eligible = traceable and (
            valid_contrast if current is not None else is_empty_vocabulary_bootstrap
        )
        candidates.append({
            "term": word, "reason": str(reason)[:250],
            "evidence_message_ids": references if traceable else [],
            "context_reference_traceable": bool(traceable),
            "target_code": target if isinstance(target, str) and target in prior_hypotheses else None,
            "contrasted_candidate": compared if valid_contrast else None,
            "contrast_reason": contrast_reason[:250] if valid_contrast else "",
            "existing_candidate_contrast_traceable": bool(valid_contrast),
            "automatic_adoption_eligible": bool(eligible),
            "status": "unverified", "source_round": round_number,
        })
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
        # Automatic means no human confirmation, NOT automatic factual
        # verification. Only adopt a bounded subset with a reason and
        # referentially valid source messages. Unsupported words remain in
        # the audit as proposals, not in the solver's adopted vocabulary.
        selection = [
            x["term"] for x in candidates if x["automatic_adoption_eligible"]
        ][:MAX_AUTO_ADOPT_WITH_CONTEXT_PER_ROUND]

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
        "automatic_evidence_gate": review is None,
        "untraceable_proposed_count": sum(
            not item["context_reference_traceable"] for item in candidates),
        "missing_existing_candidate_contrast_count": sum(
            item["context_reference_traceable"] and
            not item["automatic_adoption_eligible"] for item in candidates),
        "contrast_required_when_prior_mapping_exists": current is not None,
        "auto_per_round_limit": MAX_AUTO_ADOPT_WITH_CONTEXT_PER_ROUND,
        "total_dynamic_terms": len(dynamic_terms) + len(approved),
        "metadata_used": metadata,
    }
    return updated, record
