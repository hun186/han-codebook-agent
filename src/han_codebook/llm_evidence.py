"""Strictly select observable message fields before sending data to a local LLM.

Case inputs are untrusted: top-level and nested arbitrary fields (including
synthetic evaluation labels) must never be forwarded to inference. Preserve only
primitive observations and the documented contextual string fields.
"""
from __future__ import annotations

import math
from typing import Any

TEXT_FIELDS = ("received_at", "sender", "recipient", "notes", "unit", "domain")
OBSERVATION_TEXT_FIELDS = ("source", "observed_at", "activity", "destination", "status", "note")


def safe_observations(observations: Any) -> list[dict[str, Any]]:
    if not isinstance(observations, list):
        return []
    result = []
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        # NEVER copy the original mapping or its unknown nested fields.
        clean = {name: observation[name] for name in OBSERVATION_TEXT_FIELDS
                 if isinstance(observation.get(name), str)}
        confidence = observation.get("confidence")
        if (isinstance(confidence, (float, int)) and not isinstance(confidence, bool)
                and math.isfinite(confidence) and 0 <= confidence <= 1):
            clean["confidence"] = confidence
        if clean.get("source", "").strip():
            result.append(clean)
    return result


def safe_message_metadata(message: dict[str, Any]) -> dict[str, Any]:
    result = {"id": message["id"]}
    for name in TEXT_FIELDS:
        if isinstance(message.get(name), str):
            result[name] = message[name]
    if "observations" in message:
        result["observations"] = safe_observations(message["observations"])
    return result


def safe_llm_message(message: dict[str, Any], *, metadata: bool) -> dict[str, Any]:
    # Codes are validated in the caller's validate_case; no gold or plaintext.
    result = {"id": message["id"], "codes": list(message["codes"])}
    if metadata:
        context = safe_message_metadata(message)
        context.pop("id", None)
        result.update(context)
    return result
