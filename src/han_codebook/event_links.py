"""Conservative sighting-to-telegram candidates; never a plaintext oracle.

Event sources are metadata, not necessarily observations of the ciphertext
sender or proof a specific message discussed that event. Null association is
always retained as an explicit competing hypothesis.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime
from typing import Any

from .core import validate_case


def _day(text: Any):
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def _status_factor(status: str) -> float:
    if any(token in status for token in ("無關", "不相關", "已排除")):
        return 0.0
    return 0.35 if "未確認" in status else 1.0


def suggest_event_links(case: dict, *, limit_per_event: int = 4) -> list[dict]:
    """Compare all documented observations against all telegrams, by date only.

    Deliberately no learned semantics of the numerical code groups. This is an
    evidence navigation aid for a human/LLM, not code->plaintext assignment.
    """
    validate_case(case)
    if limit_per_event not in range(1, 7):
        raise ValueError("limit_per_event must be 1..6")
    messages = case["messages"]
    day_of = {m["id"]: _day(m.get("received_at")) for m in messages}
    occurrences = Counter(code for m in messages for code in set(m["codes"]))
    results = []
    for origin in messages:
        for index, obs in enumerate(origin.get("observations", [])):
            event_date = _day(obs.get("observed_at"))
            confidence = float(obs.get("confidence", 0.5))
            reliability = confidence * _status_factor(obs.get("status", ""))
            candidates = []
            for message in messages:
                msg_date = day_of[message["id"]]
                # Missing or unparseable timestamps cannot create inferred relevance.
                if not event_date or not msg_date or not reliability:
                    continue
                offset = (msg_date - event_date).days
                if abs(offset) > 7:
                    continue
                # Mild recency prior, no use of secret codebook or plaintext.
                proximity = 1 / (1 + abs(offset))
                score = round(0.55 * reliability * proximity, 4)
                recurring = sorted({c for c in message["codes"] if occurrences[c] > 1})
                candidates.append({
                    "message_id": message["id"],
                    "day_offset": offset,
                    "score": score,
                    "frequent_codes": recurring[:12],
                    "basis": "date proximity and stated source confidence only; code groups unverified",
                })
            candidates.sort(key=lambda x: (-x["score"],abs(x["day_offset"]),x["message_id"]))
            candidates = candidates[:limit_per_event]
            # Always include a 'no connection' alternative; never auto-link
            # merely because the nearest timestamp exists.
            candidates.append({
                "message_id": None, "score": round(0.45 + (1 - reliability) * 0.25, 4),
                "basis": "may be unrelated to all intercepted telegrams",
            })
            results.append({
                "event_id": f"{origin['id']}:observation:{index}",
                "source_message_id": origin["id"],
                "observed_at": obs.get("observed_at", ""),
                "source": obs["source"],
                "activity": obs.get("activity", ""),
                "destination": obs.get("destination", ""),
                "status": obs.get("status", ""),
                "confidence": confidence,
                "note": obs.get("note", ""),
                "association_status": "hypotheses_only",
                "candidates": candidates,
            })
    return results[:100]
