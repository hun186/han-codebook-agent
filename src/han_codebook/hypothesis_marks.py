"""Reversible researcher hypotheses, separate from verified known-plaintext anchors.

A mark is an experimental constraint, never proof of decipherment. Case input stores
only the current mark state; UI version history holds earlier snapshots locally.
"""
from __future__ import annotations

from typing import Any

from .core import CaseError


def normalize_marks(case: dict[str, Any], anchors: dict[str, str]) -> dict[str, dict]:
    raw = case.get('hypothesis_marks', {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict) or len(raw) > 500:
        raise CaseError('hypothesis_marks must be an object with up to 500 codes')
    present = {code for message in case['messages'] for code in message['codes']}
    clean = {}
    for code, mark in raw.items():
        if code not in present or code in anchors or not isinstance(mark, dict):
            raise CaseError(f'cannot mark absent or verified code: {code}')
        if set(mark) - {'preferred', 'excluded', 'pinned', 'note'}:
            raise CaseError(f'unsupported annotation fields for code {code}')
        preferred = mark.get('preferred') or None
        pinned = bool(mark.get('pinned', False))
        excluded = mark.get('excluded', [])
        note = mark.get('note', '')
        if type(mark.get('pinned', False)) is not bool:
            raise CaseError(f'code {code}: pinned must be boolean')
        if preferred is not None and (not isinstance(preferred, str) or not 1 <= len(preferred.strip()) <= 32 or preferred != preferred.strip()):
            raise CaseError(f'code {code}: preferred must be a 1..32 character phrase')
        if not isinstance(excluded, list) or len(excluded) > 30 or any(not isinstance(w,str) or not 1 <= len(w) <= 32 for w in excluded):
            raise CaseError(f'code {code}: excluded must be a list of up to 30 phrases')
        if not isinstance(note,str) or len(note) > 500:
            raise CaseError(f'code {code}: note must be text of at most 500 characters')
        if len(set(excluded)) != len(excluded):
            raise CaseError(f'code {code}: duplicate exclusions')
        if pinned and preferred is None:
            raise CaseError(f'code {code}: trial pin requires preferred phrase')
        if preferred in excluded:
            raise CaseError(f'code {code}: preferred phrase cannot also be excluded')
        clean[code] = {'preferred': preferred, 'excluded': list(excluded), 'pinned': pinned, 'note': note}
    return clean
