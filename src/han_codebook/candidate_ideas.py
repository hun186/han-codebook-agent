"""Multi-idea researcher/LLM proposal bank; no inferred phrase is a known anchor."""
from __future__ import annotations
from typing import Any

from .core import CaseError

IDEA_SOURCES = {"researcher", "llm", "observation"}
IDEA_STATUSES = {"suggested", "shortlisted", "rejected"}


def normalize_ideas(case: dict[str, Any]) -> dict[str, list[dict]]:
    raw = case.get("candidate_ideas", {})
    if not isinstance(raw, dict) or len(raw) > 500:
        raise CaseError("candidate_ideas must be a mapping of at most 500 codes")
    codes = {c for m in case["messages"] for c in m["codes"]}
    clean = {}
    for code, ideas in raw.items():
        if not isinstance(code, str) or code not in codes or not isinstance(ideas, list) or len(ideas) > 12:
            raise CaseError("candidate_ideas invalid or absent code, or more than 12 ideas")
        seen = set()
        accepted = []
        for idea in ideas:
            if not isinstance(idea, dict) or set(idea) - {"term","source","status","note"}:
                raise CaseError("candidate idea must use only term/source/status/note")
            term, source, status, note = (idea.get("term"), idea.get("source","researcher"),
                                          idea.get("status","suggested"), idea.get("note",""))
            if (not isinstance(term,str) or not 1 <= len(term.strip()) <= 32 or term != term.strip()
                    or source not in IDEA_SOURCES or status not in IDEA_STATUSES
                    or not isinstance(note,str) or len(note) > 500):
                raise CaseError("invalid unverified candidate idea")
            if term in seen:
                raise CaseError("duplicate candidate idea for code")
            seen.add(term)
            accepted.append({"term":term,"source":source,"status":status,"note":note})
        clean[code] = accepted
    return clean


def idea_vocabulary(case: dict) -> set[str]:
    return {idea["term"] for ideas in normalize_ideas(case).values()
            for idea in ideas if idea["status"] != "rejected"}


def shortlisted_bonus(case: dict) -> dict[str, dict[str, float]]:
    return {code:{idea["term"]: 0.12 for idea in ideas if idea["status"] == "shortlisted"}
            for code,ideas in normalize_ideas(case).items()}
