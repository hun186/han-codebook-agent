"""Read-only, explicitly requested DeepInfra model discovery (no case/prompt upload)."""
from __future__ import annotations

import json
import os
import re
from urllib import error, request

from .agent import DEEPINFRA_BASE_URL, _urlopen_llm
from .core import CaseError

PREFERRED_MODEL = "deepseek-ai/DeepSeek-V4.1-Flash-1017"
FALLBACK_MODEL = "deepseek-ai/DeepSeek-V4.1-Flash"
_MAX_BYTES = 500_000
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,127}$")


def fetch_deepinfra_models(*, api_key_env: str = "DEEPINFRA_API_KEY") -> dict:
    """No inference, user content, redirects, arbitrary destinations, or secrets in output."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", api_key_env):
        raise CaseError("Invalid API key environment variable name")
    token = os.environ.get(api_key_env)
    if not token:
        raise CaseError(f"DeepInfra API key environment variable not set: {api_key_env}")
    req = request.Request(
        DEEPINFRA_BASE_URL + "/models",
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with _urlopen_llm(req, timeout=12, provider="deepinfra") as response:
            raw = response.read(_MAX_BYTES + 1)
    except error.HTTPError as exc:
        raise CaseError(f"DeepInfra model list HTTP {exc.code}; check credentials or service") from exc
    except (error.URLError, OSError, TimeoutError) as exc:
        raise CaseError(f"DeepInfra model list unavailable: {type(exc).__name__}") from exc
    if len(raw) > _MAX_BYTES:
        raise CaseError("DeepInfra model catalog response exceeded size limit")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise CaseError("DeepInfra model list returned invalid JSON") from exc
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise CaseError("DeepInfra model list has unsupported structure")
    ids = {
        obj["id"] for obj in data["data"][:2000]
        if isinstance(obj, dict) and isinstance(obj.get("id"), str)
        and _MODEL_ID.fullmatch(obj["id"])
    }
    if not ids:
        raise CaseError("DeepInfra model list returned no usable model IDs")
    ordered = sorted(ids, key=lambda name: (
        0 if name == PREFERRED_MODEL else
        1 if name == FALLBACK_MODEL else
        2 if name.lower().startswith("deepseek-ai/") else 3, name.lower()))
    return {
        "models": ordered,
        "preferred_model": PREFERRED_MODEL if PREFERRED_MODEL in ids else
                           FALLBACK_MODEL if FALLBACK_MODEL in ids else None,
        "source": "DeepInfra /v1/openai/models",
        "count": len(ordered),
        "secret_value_exposed": False,
    }
