"""Strict, optional YAML configuration; no implicit outbound connections."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .core import CaseError

_SCHEMAS = {
    "project": {"case": str, "output": str, "audit_db": str},
    "analysis": {"use_metadata": bool, "rounds": int, "evaluate_demo": bool},
    "llm": {"base_url": str, "model": str, "timeout_seconds": int,
            "allow_private_network": bool, "allowed_hosts": list, "api_key_env": str,
            "capture_io": bool},
}


def load_settings(path: str | Path) -> dict[str, Any]:
    """Read restricted mapping-only YAML using safe_load; paths relative to YAML file."""
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as exc:
        raise CaseError("YAML settings require PyYAML: python -m pip install 'PyYAML>=6,<7'") from exc
    cfg_path = Path(path).expanduser().resolve()
    try:
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise CaseError(f"Cannot read YAML config '{cfg_path}': {exc}") from exc
    if not isinstance(raw, dict):
        raise CaseError("Config must be a YAML mapping (sections: project, analysis, llm)")
    unknown_sections = set(raw) - set(_SCHEMAS)
    if unknown_sections:
        raise CaseError(f"Unknown config sections: {sorted(map(str, unknown_sections))}")
    result: dict[str, Any] = {}
    for section, schema in _SCHEMAS.items():
        values = raw.get(section, {})
        if not isinstance(values, dict):
            raise CaseError(f"Config '{section}' must be a mapping")
        extra = set(values) - set(schema)
        if extra:
            raise CaseError(f"Unknown config keys in {section}: {sorted(map(str, extra))}")
        for key, val in values.items():
            tp = schema[key]
            if type(val) is not tp:
                raise CaseError(f"Config '{section}.{key}' must be {tp.__name__}")
            if tp is str and (not val.strip() or "\x00" in val):
                raise CaseError(f"Config '{section}.{key}' must be a nonempty string")
            if key == "allowed_hosts" and not all(isinstance(s, str) and s.strip() for s in val):
                raise CaseError("Config 'llm.allowed_hosts' must be a list of host strings")
        result[section] = values
    for key in ("case", "output", "audit_db"):
        if key in result["project"]:
            result["project"][key] = str((cfg_path.parent / result["project"][key]).resolve())
    if not 0 <= result["analysis"].get("rounds", 0) <= 20:
        raise CaseError("Config 'analysis.rounds' must be in 0..20")
    if not 1 <= result["llm"].get("timeout_seconds", 90) <= 600:
        raise CaseError("Config 'llm.timeout_seconds' must be in 1..600")
    return result
