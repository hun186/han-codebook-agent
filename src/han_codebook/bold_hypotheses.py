"""Explicit counterfactual readings that never overwrite validated known plaintext."""
from __future__ import annotations
from typing import Any
from .core import CaseError


def normalize_bold_hypotheses(case: dict[str, Any], anchors: dict[str, str]) -> dict[str, dict[str, str]]:
    records = case.get("bold_hypotheses", {})
    if records is None:
        return {}
    if not isinstance(records, dict) or len(records) > 100:
        raise CaseError("bold_hypotheses must be an object of up to 100 verified-code alternatives")
    clean = {}
    for code, value in records.items():
        if code not in anchors or not isinstance(value, dict) or set(value) - {"term", "note", "confirmed"}:
            raise CaseError(f"bold hypothesis must refer to an existing verified code: {code}")
        term, note, confirmed = value.get("term"), value.get("note", ""), value.get("confirmed")
        if (not isinstance(term, str) or not 1 <= len(term.strip()) <= 32 or term != term.strip()
                or not isinstance(note, str) or len(note) > 500 or confirmed is not True):
            raise CaseError(f"bold hypothesis {code} requires a phrase and explicit researcher confirmation")
        if term == anchors[code]:
            raise CaseError(f"bold hypothesis {code} must differ from known plaintext")
        clean[code] = {"term": term, "note": note, "confirmed": True}
    return clean
