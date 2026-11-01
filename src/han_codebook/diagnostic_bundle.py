"""Bounded, fail-closed, loopback-only diagnostic ZIP export.

The default SHARE bundle never includes plaintext, prompts, LLM responses,
endpoint addresses or credentials. PRIVATE is explicit user opt-in.
Synthetic benchmark gold is NEVER collected by this exporter.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
from typing import Any
from zipfile import ZipFile, ZIP_DEFLATED

from .web_audit_format import read_audit_events

MAX_SINGLE_FILE = 48 * 1024 * 1024
MAX_BUNDLE_BYTES = 128 * 1024 * 1024
TERMINAL = {"completed", "failed"}

def _json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")

def _jsonl(rows: list[dict]) -> bytes:
    return "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows).encode("utf-8")

def _safe_count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None

def _sanitized_trace(events: list[dict]) -> list[dict]:
    output = []
    for event in events:
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        entry = {"at_utc": event.get("at"), "round": event.get("round"),
                 "stage": event.get("stage")}
        for key in ("changed_count", "rejected_count", "returned_count", "candidate_count",
                    "round", "known_anchors", "ambiguous_pairs", "messages"):
            if key in payload:
                count = _safe_count(payload[key])
                if count is not None:
                    entry[key] = count
        for key in ("accepted", "approved", "proposed"):
            if isinstance(payload.get(key), list):
                entry[key + "_count"] = len(payload[key])
        if event.get("stage") == "llm_response":
            entry["elapsed_ms"] = payload.get("elapsed_ms") if type(payload.get("elapsed_ms")) in (int, float) else None
            usage = payload.get("usage")
            if isinstance(usage, dict):
                entry["token_usage"] = {k: v for k, v in usage.items()
                    if k in ("prompt_tokens", "completion_tokens", "total_tokens")
                    and type(v) is int and v >= 0}
        output.append(entry)
    return output

def build_diagnostic_zip(target: Path, *, job_id: str, status: str,
                         config: dict, private: bool = False) -> bytes:
    """Build one immutable snapshot of a TERMINAL job's artifacts.

    No arbitrary path is accepted from a browser; target is constructed by the
    calling loopback server from a 16-character hex job id.
    """
    if not re.fullmatch(r"[0-9a-f]{16}", job_id):
        raise ValueError("Invalid job identity")
    if status not in TERMINAL:
        raise ValueError("Only completed or failed analyses can be exported")
    if not isinstance(config, dict) or set(config) - {
        "model", "rounds_requested", "metadata", "capture_llm_io", "candidate_mode"
    }:
        raise ValueError("Unexpected diagnostic settings")
    if target.is_symlink() or not target.is_dir():
        raise ValueError("Invalid run directory")
    db = target / "audit.sqlite"
    events = read_audit_events(db)
    snapshot = target / "input_case.json"
    case_digest = None
    if snapshot.is_file():
        if snapshot.is_symlink() or snapshot.stat().st_size > MAX_SINGLE_FILE:
            raise ValueError("Input snapshot unavailable or oversized")
        case_digest = sha256(snapshot.read_bytes()).hexdigest()
    files: dict[str, bytes] = {
        "round_trace.jsonl": _jsonl(_sanitized_trace(events)),
        "evaluation.json": _json({
            "status": "not_performed",
            "note": "Gold/oracle is never loaded into the solver or diagnostic ZIP. "
                    "Use separate post-inference synthetic scoring to assess accuracy."
        }),
    }
    manifest = {
        "schema_version": 1, "job_id": job_id,
        "exported_utc": datetime.now(timezone.utc).isoformat(),
        "run_status": status, "complete": status == "completed",
        "content_mode": "private_raw" if private else "share_safe",
        "case_sha256": case_digest, "event_count": len(events),
        "settings": {k: config.get(k) for k in
                     ("model", "rounds_requested", "metadata", "capture_llm_io", "candidate_mode")},
        "limitations": [
            "Candidate scores are not calibrated correctness probabilities.",
            "Historical authenticity is not established by a researcher or model hypothesis.",
            "Full model internal hidden reasoning is not available.",
        ],
    }
    if private:
        if not snapshot.is_file():
            raise ValueError("Private bundle requires original input snapshot")
        if not db.is_file():
            raise ValueError("Private bundle requires audit evidence")
        files["input_case.json"] = snapshot.read_bytes()
        files["audit_events.jsonl"] = _jsonl(events)
        for name in ("result.json", "report.md", "report.docx", "audit.sqlite"):
            path = target / name
            if path.is_file():
                if path.is_symlink() or path.stat().st_size > MAX_SINGLE_FILE:
                    raise ValueError("Unsafe or oversized private evidence")
                files[name] = path.read_bytes()
        manifest["private_warning"] = (
            "Contains researcher input, candidate plaintext and possibly raw model "
            "requests/responses when capture_llm_io was enabled. Inspect before sharing."
        )
    else:
        # Default share mode includes only non-sensitive counters/stages and
        # generic failure category, never messages, candidate terms or URLs.
        manifest["privacy"] = "No case text, prompts, model replies, endpoint or raw SQLite."
    files["run_manifest.json"] = _json(manifest)
    total = sum(len(data) for data in files.values())
    if total > MAX_BUNDLE_BYTES or any(len(data) > MAX_SINGLE_FILE for data in files.values()):
        raise ValueError("Diagnostic bundle exceeds hard size cap")
    out = BytesIO()
    with ZipFile(out, "w", compression=ZIP_DEFLATED, compresslevel=6) as z:
        for name, data in sorted(files.items()):
            z.writestr(name, data)
    return out.getvalue()
