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
import math
from pathlib import Path
import re
from typing import Any
from zipfile import ZipFile, ZIP_DEFLATED

from .web_audit_format import read_audit_events

MAX_SINGLE_FILE = 48 * 1024 * 1024
MAX_BUNDLE_BYTES = 128 * 1024 * 1024
TERMINAL = {"completed", "failed"}

ORACLE_KEYS = frozenset(("gold", "ground_truth", "codebook"))
# SQLite audit columns are ordinarily machine-produced, but older or manually
# modified audit files must not smuggle free-form text into a share-safe ZIP.
_SAFE_UTC = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:\+00:00|Z)\Z"
)
_SAFE_STAGE = re.compile(r"[a-z_]{1,72}\Z")


def reject_oracle_fields(case: Any) -> None:
    """Reject evaluation answers at ANY depth, before LLM or raw snapshots."""
    stack = [case]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if any(key in node for key in ORACLE_KEYS):
                raise ValueError("Research case must not contain evaluation oracle fields at any depth")
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


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
        at = event.get("at")
        stage = event.get("stage")
        entry = {
            "at_utc": at if type(at) is str and _SAFE_UTC.fullmatch(at) else None,
            "round": _safe_count(event.get("round")),
            "stage": stage if type(stage) is str and _SAFE_STAGE.fullmatch(stage)
                     else "unrecognized",
        }
        for key in ("changed_count", "rejected_count", "returned_count", "candidate_count",
                    "round", "known_anchors", "ambiguous_pairs", "messages"):
            if key in payload:
                count = _safe_count(payload[key])
                if count is not None:
                    entry[key] = count
        for key in ("accepted", "approved", "proposed"):
            if isinstance(payload.get(key), list):
                entry[key + "_count"] = len(payload[key])
        if entry["stage"] == "llm_response":
            elapsed = payload.get("elapsed_ms")
            entry["elapsed_ms"] = elapsed if (
                (type(elapsed) is int and elapsed >= 0)
                or (type(elapsed) is float and math.isfinite(elapsed) and elapsed >= 0)
            ) else None
            usage = payload.get("usage")
            if isinstance(usage, dict):
                entry["token_usage"] = {k: v for k, v in usage.items()
                    if k in ("prompt_tokens", "completion_tokens", "total_tokens")
                    and type(v) is int and v >= 0}
        output.append(entry)
    return output

def build_diagnostic_zip(target: Path, *, job_id: str, status: str,
                         config: dict, private: bool = False,
                         error_type: str | None = None) -> bytes:
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
    # A historical/corrupted in-memory job may bypass the HTTP start validator.
    # Do not copy arbitrary strings from its settings into a share-safe ZIP.
    if (type(config.get("rounds_requested")) is not int
            or not 0 <= config["rounds_requested"] <= 20
            or type(config.get("metadata")) is not bool
            or type(config.get("capture_llm_io")) is not bool
            or type(config.get("candidate_mode")) is not str
            or config["candidate_mode"] not in ("static", "automatic", "human")
            or (config.get("model") is not None
                and type(config["model"]) is not str)):
        raise ValueError("Invalid diagnostic setting values")
    if target.is_symlink() or not target.is_dir():
        raise ValueError("Invalid run directory")
    db = target / "audit.sqlite"
    events = read_audit_events(db)
    snapshot = target / "input_case.json"
    # Use precisely the bytes that passed the oracle check for digesting AND
    # packaging. A second read could include a file swapped after validation.
    case_bytes = None
    case_digest = None
    if snapshot.is_file():
        if snapshot.is_symlink() or snapshot.stat().st_size > MAX_SINGLE_FILE:
            raise ValueError("Input snapshot unavailable or oversized")
        case_bytes = snapshot.read_bytes()
        # Defensive recheck even for older files or if source contents
        # were manually changed after admission. Never package oracle data.
        reject_oracle_fields(json.loads(case_bytes))
        case_digest = sha256(case_bytes).hexdigest()
    trace = _sanitized_trace(events)
    stages: dict[str, int] = {}
    for e in trace:
        stage = e.get("stage")
        # Stage names are code-defined; reject arbitrary raw audit text in
        # the sanitized share-safe report.
        if type(stage) is str and _SAFE_STAGE.fullmatch(stage):
            stages[stage] = stages.get(stage, 0) + 1
    last_round = max((e["round"] for e in trace if type(e.get("round")) is int), default=0)
    failure_category = error_type if (type(error_type) is str and
        re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,79}", error_type)) else None
    files: dict[str, bytes] = {
        "round_trace.jsonl": _jsonl(trace),
        "diagnostics.json": _json({
            "complete": status == "completed",
            "status": status, "last_observed_round": last_round,
            "stage_counts": stages,
            "failure_category": failure_category if status == "failed" else None,
            "note": "No raw exception text, private URL, prompt or model reply in share-safe export."
        }),
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
        "settings": {k: (config.get(k) if (private or k != "model") else "redacted")
                     for k in ("model", "rounds_requested", "metadata", "capture_llm_io", "candidate_mode")},
        "limitations": [
            "Candidate scores are not calibrated correctness probabilities.",
            "Historical authenticity is not established by a researcher or model hypothesis.",
            "Full model internal hidden reasoning is not available.",
        ],
    }
    if private:
        missing_evidence = []
        if case_bytes is not None:
            files["input_case.json"] = case_bytes
        else:
            missing_evidence.append("input_case.json")
        if db.is_file():
            files["audit_events.jsonl"] = _jsonl(events)
        else:
            missing_evidence.extend(("audit_events.jsonl", "audit.sqlite"))
        if status == "completed" and missing_evidence:
            raise ValueError("Completed run must have a full audit and input snapshot")
        if missing_evidence:
            manifest["missing_evidence"] = missing_evidence
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
