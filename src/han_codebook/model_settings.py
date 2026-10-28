"""Safe loopback UI updates for private-network OpenAI-compatible models.

Write the environment variable NAME, never a token. Preserve unrelated YAML.
"""
from __future__ import annotations
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

from .agent import validate_llm_endpoint
from .config import load_settings
from .core import CaseError

MAX_LLM_ROUNDS = 20


def model_settings(path: Path) -> dict:
    llm = load_settings(path)["llm"]
    return {
        "base_url": llm.get("base_url", "http://127.0.0.1:11434"),
        "model": llm.get("model", "qwen3:14b"),
        "timeout_seconds": llm.get("timeout_seconds", 90),
        "allow_private_network": llm.get("allow_private_network", False),
        "allowed_hosts": list(llm.get("allowed_hosts", [])),
        "api_key_env": llm.get("api_key_env", ""),
        "max_rounds": MAX_LLM_ROUNDS,
        "secret_value_exposed": False,
    }


def save_model_settings(path: Path, raw: dict) -> dict:
    """Persist only allowlisted settings, with explicit LAN opt-in."""
    if not isinstance(raw, dict) or set(raw) - {"base_url", "model", "timeout_seconds", "allow_private_network", "api_key_env"}:
        raise CaseError("Unsupported LLM configuration fields")
    url, model, timeout = raw.get("base_url"), raw.get("model"), raw.get("timeout_seconds")
    lan = raw.get("allow_private_network", False)
    env_name = raw.get("api_key_env", "")
    if not isinstance(url, str) or len(url) > 250 or not isinstance(model, str) or not 1 <= len(model.strip()) <= 128:
        raise CaseError("Model name and local endpoint are required")
    if type(timeout) is not int or not 1 <= timeout <= 600 or type(lan) is not bool:
        raise CaseError("Timeout must be integer 1..600; private LAN must be a boolean")
    if not isinstance(env_name, str) or len(env_name) > 128 or (env_name and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_name)):
        raise CaseError("API secret reference must be an environment variable NAME, never the token")
    host = urlsplit(url).hostname or ""
    # The only allowed remote host is the exact private IP entered by the operator.
    allowlist = [host] if lan and host not in ("localhost", "127.0.0.1", "::1") else []
    validate_llm_endpoint(url, allow_private_network=lan, allowed_hosts=allowlist)
    import yaml
    existing = load_settings(path)
    existing["llm"].update({
        "base_url": url.rstrip("/"), "model": model.strip(), "timeout_seconds": timeout,
        "allow_private_network": lan, "allowed_hosts": allowlist,
    })
    if env_name:
        existing["llm"]["api_key_env"] = env_name
    else:
        existing["llm"].pop("api_key_env", None)
    # Avoid saving a literal secret or publishing it to the UI.
    existing["llm"].pop("api_key", None)
    path = path.resolve()
    fd, temporary = tempfile.mkstemp(prefix=".llm-config-", suffix=".yaml", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            yaml.safe_dump(existing, stream, allow_unicode=True, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return model_settings(path)
