"""Safe loopback UI updates for private-network OpenAI-compatible models.

Write the environment variable NAME, never a token. Preserve unrelated YAML.
"""
from __future__ import annotations
import os
import hashlib
import json
from pathlib import Path
import re
import secrets
import tempfile
from urllib.parse import urlsplit

from .agent import (DEEPINFRA_DEFAULT_MAX_OUTPUT_TOKENS,
                    validate_llm_endpoint, validate_max_output_tokens)
from .config import load_settings
from .core import CaseError

MAX_LLM_ROUNDS = 20

# This is a freshness receipt for NONSECRET model settings, not authentication.
# It must be compared while the job-admission/settings-write lock is held.
_CONFIRMATION_FIELDS = (
    "provider", "base_url", "model", "timeout_seconds", "allow_external_api",
    "allow_private_network", "allowed_hosts", "api_key_env",
    "reasoning_effort", "response_format", "max_output_tokens",
)


def llm_confirmation_token(llm: dict) -> str:
    values = {key: llm.get(key) for key in _CONFIRMATION_FIELDS}
    values["provider"] = llm.get("provider", "local")
    values["allow_external_api"] = llm.get("allow_external_api", False)
    canonical = json.dumps(values, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def require_llm_admission_confirmation(payload: dict, llm: dict) -> None:
    """Fail closed for external use and for any supplied stale destination."""
    provider = llm.get("provider", "local")
    provided = payload.get("confirmed_llm_config")
    if provider == "deepinfra":
        if payload.get("confirmed_external_api") is not True:
            raise CaseError("DeepInfra needs an explicit per-run external consent")
        if not llm.get("allow_external_api", False):
            raise CaseError("DeepInfra external API is disabled")
    if provider == "deepinfra" or provided is not None:
        expected = llm_confirmation_token(llm)
        if not isinstance(provided, str) or not secrets.compare_digest(provided, expected):
            raise CaseError("LLM model or provider changed after confirmation; confirm again")


def model_settings(path: Path) -> dict:
    llm = load_settings(path)["llm"]
    return {
        "base_url": llm.get("base_url", "http://127.0.0.1:11434"),
        "provider": llm.get("provider", "local"),
        "allow_external_api": llm.get("allow_external_api", False),
        "model": llm.get("model", "qwen3:14b"),
        "max_output_tokens": llm.get("max_output_tokens", DEEPINFRA_DEFAULT_MAX_OUTPUT_TOKENS),
        "timeout_seconds": llm.get("timeout_seconds", 90),
        "allow_private_network": llm.get("allow_private_network", False),
        "allowed_hosts": list(llm.get("allowed_hosts", [])),
        "api_key_env": llm.get("api_key_env", ""),
        "max_rounds": MAX_LLM_ROUNDS,
        "secret_value_exposed": False,
        "confirmation_token": llm_confirmation_token(llm),
    }


def save_model_settings(path: Path, raw: dict) -> dict:
    """Persist only allowlisted settings, with explicit LAN opt-in."""
    if not isinstance(raw, dict) or set(raw) - {"base_url", "model", "timeout_seconds", "allow_private_network", "provider", "allow_external_api", "api_key_env", "max_output_tokens"}:
        raise CaseError("Unsupported LLM configuration fields")
    url, model, timeout = raw.get("base_url"), raw.get("model"), raw.get("timeout_seconds")
    lan = raw.get("allow_private_network", False)
    provider = raw.get("provider", "local")
    external = raw.get("allow_external_api", False)
    env_name = raw.get("api_key_env", "")
    cap = raw.get("max_output_tokens")
    if provider == "deepinfra":
        cap = validate_max_output_tokens(
            DEEPINFRA_DEFAULT_MAX_OUTPUT_TOKENS if cap is None else cap)
    elif cap is not None:
        raise CaseError("max_output_tokens applies to DeepInfra only")
    if type(provider) is not str or provider not in ("local", "ollama", "deepinfra"):
        raise CaseError("Provider must be local, ollama or deepinfra")
    if type(external) is not bool or (provider != "deepinfra" and external):
        raise CaseError("External API consent only applies to DeepInfra")
    if provider == "deepinfra":
        if not external or lan:
            raise CaseError("DeepInfra needs external API consent, not LAN permission")
        env_name = env_name or "DEEPINFRA_API_KEY"
    if not isinstance(url, str) or len(url) > 250 or not isinstance(model, str) or not 1 <= len(model.strip()) <= 128:
        raise CaseError("Model name and local endpoint are required")
    if type(timeout) is not int or not 1 <= timeout <= 600 or type(lan) is not bool:
        raise CaseError("Timeout must be integer 1..600; private LAN must be a boolean")
    if not isinstance(env_name, str) or len(env_name) > 128 or (env_name and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_name)):
        raise CaseError("API secret reference must be an environment variable NAME, never the token")
    host = urlsplit(url).hostname or ""
    # The only allowed remote host is the exact private IP entered by the operator.
    allowlist = [host] if lan and host not in ("localhost", "127.0.0.1", "::1") else []
    validate_llm_endpoint(url, allow_private_network=lan, allowed_hosts=allowlist,
                          provider=provider, allow_external_api=external)
    import yaml
    existing = load_settings(path)
    existing["llm"].update({
        "base_url": url.rstrip("/"), "model": model.strip(), "timeout_seconds": timeout,
        "provider": provider, "allow_external_api": external,
        "allow_private_network": lan, "allowed_hosts": allowlist,
    })
    if env_name:
        existing["llm"]["api_key_env"] = env_name
    else:
        existing["llm"].pop("api_key_env", None)
    if provider == "deepinfra":
        existing["llm"]["max_output_tokens"] = cap
        existing["llm"].pop("reasoning_effort", None)
    else:
        existing["llm"].pop("max_output_tokens", None)
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
