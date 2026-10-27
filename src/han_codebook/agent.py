"""Optional localhost OpenAI-compatible LLM proposal loop.

The model never receives 'ground_truth' or credentials, and cannot alter verified anchors.
"""
from __future__ import annotations

import ipaddress
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request, error, parse
from .core import analyze, anchors_and_review, CaseError


def create_audit(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, at_utc TEXT NOT NULL, round INTEGER NOT NULL, stage TEXT NOT NULL, payload_json TEXT NOT NULL)")
    conn.commit()
    return conn


def log_event(conn: sqlite3.Connection, round_num: int, stage: str, payload: dict[str, Any]) -> None:
    conn.execute("INSERT INTO events (at_utc, round, stage, payload_json) VALUES (?, ?, ?, ?)",
                 (datetime.now(timezone.utc).isoformat(), round_num, stage, json.dumps(payload, ensure_ascii=False)))
    conn.commit()


def validate_llm_endpoint(base_url: str, *, allow_private_network: bool = False,
                          allowed_hosts: tuple[str, ...] | list[str] = ()) -> None:
    """Never send research material to public hosts; private IPs require explicit opt-in."""
    parsed = parse.urlparse(base_url)
    hostname = parsed.hostname
    if (parsed.scheme not in ("http", "https") or not hostname or
            parsed.username or parsed.password or parsed.query or parsed.fragment or
            not parsed.netloc or parsed.path not in ("", "/", "/v1", "/v1/")):
        raise CaseError("LLM endpoint must be an http(s) base URL, optionally ending in /v1")
    try:
        _ = parsed.port  # catch invalid ports early
    except ValueError as exc:
        raise CaseError(f"Invalid LLM endpoint port: {exc}") from exc
    if hostname in ("localhost", "127.0.0.1", "::1"):
        return
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError as exc:
        raise CaseError("Remote LLM endpoint must use an explicit private-network IP address, not DNS") from exc
    private_ranges = (ipaddress.ip_network("10.0.0.0/8"),
                      ipaddress.ip_network("172.16.0.0/12"),
                      ipaddress.ip_network("192.168.0.0/16"))
    if not (addr.version == 4 and any(addr in net for net in private_ranges)):
        raise CaseError("Remote LLM endpoint must be RFC1918 private IPv4; public IPs are not allowed")
    if not allow_private_network or hostname not in allowed_hosts:
        raise CaseError("LAN access requires llm.allow_private_network=true AND exact llm.allowed_hosts entry")


def query_local_llm(base_url: str, model: str, evidence: dict[str, Any], timeout: int = 90,
                    *, allow_private_network: bool = False,
                    allowed_hosts: tuple[str, ...] | list[str] = (),
                    api_key_env: str | None = None) -> dict[str, Any]:
    """Private LAN is opt-in and allowlisted; never send to unrestricted external URLs."""
    validate_llm_endpoint(base_url, allow_private_network=allow_private_network,
                          allowed_hosts=allowed_hosts)
    api = base_url.rstrip("/")
    if not api.endswith("/v1"):
        api += "/v1"
    # Intentionally minimal, HTTP POST to local Ollama/vLLM/OpenAI-compatible endpoint.
    body = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": (
                "你是歷史中文詞組電碼分析的研究助手。所有未知對應都是假設，絕不宣稱已破譯。"
                "請只回傳 JSON：{\"hypotheses\":[{\"code\":\"123\",\"candidates\":[\"糧秣\",\"補給\"],\"reason\":\"...\"}]}。"
                "每個 candidate 必須來自提供的合法詞彙列表；不得更動 verified_anchors；最多回傳 15 個碼組。"
            )},
            {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)}
        ],
    }
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key_env:
        token = os.environ.get(api_key_env)
        if not token:
            raise CaseError(f"LLM API key environment variable not set: {api_key_env}")
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(api + "/chat/completions", data=payload, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read(500_000)
    except (error.URLError, TimeoutError) as e:
        raise CaseError(f"LLM endpoint did not respond: {e}") from e
    try:
        data = json.loads(raw.decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("not text")
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        obj = json.loads(content)
        if not isinstance(obj.get("hypotheses"), list):
            raise ValueError("missing hypotheses array")
        return obj
    except (KeyError, IndexError, ValueError, TypeError) as e:
        raise CaseError(f"Local LLM output not valid expected JSON: {e}") from e


def run_agent(case: dict[str, Any], *, rounds: int = 0, llm_url: str = "http://127.0.0.1:11434/v1",
              model: str = "qwen3:14b", db_path: str = "artifacts/audit.sqlite",
              metadata: bool = True, llm_timeout: int = 90,
              allow_private_network: bool = False,
              llm_allowed_hosts: tuple[str, ...] | list[str] = (),
              llm_api_key_env: str | None = None) -> dict[str, Any]:
    if rounds:
        validate_llm_endpoint(llm_url, allow_private_network=allow_private_network,
                              allowed_hosts=llm_allowed_hosts)
    conn = create_audit(db_path)
    try:
        anchors, reviews, vocab = anchors_and_review(case)
        domains = list(case["profiles"])
        log_event(conn, 0, "preflight", {"messages": len(case["messages"]), "known_anchors": len(anchors),
                                         "ambiguous_pairs": len(reviews), "domains": domains})
        hints: dict[str, dict[str, float]] = {}
        current = analyze(case, use_metadata=metadata)
        log_event(conn, 0, "statistical_baseline", {"score": current["objective_score"],
                                                     "mapping": {c: p["term"] for c, p in current["proposals"].items()}})
        for num in range(1, rounds + 1):
            unresolved = {
                c: p for c, p in current["proposals"].items()
                if p["status"] == "hypothesis_unverified"
            }
            packet = {
                "policy": "Propose dictionary-constrained hypotheses only; you have no decoding oracle.",
                "verified_anchors": anchors,
                "available_vocabulary": sorted(vocab),
                "profiles": {name: {"keywords": p.get("keywords", []), "lexicon": p.get("lexicon", {})}
                             for name, p in case["profiles"].items()},
                "messages": case["messages"][:50],
                "unresolved": unresolved,
            }
            reply = query_local_llm(llm_url, model, packet, timeout=llm_timeout,
                                    allow_private_network=allow_private_network,
                                    allowed_hosts=llm_allowed_hosts,
                                    api_key_env=llm_api_key_env)
            accepted = []
            for entry in reply["hypotheses"][:15]:
                if not isinstance(entry, dict):
                    continue
                code, candidates = entry.get("code"), entry.get("candidates", [])
                if code not in unresolved or not isinstance(candidates, list):
                    continue
                allowed = [x for x in candidates[:5] if isinstance(x, str) and x in vocab]
                if not allowed:
                    continue
                for rank, word in enumerate(allowed):
                    hints.setdefault(code, {})[word] = min(0.6, hints.get(code, {}).get(word, 0.0) + 0.25 / (rank + 1))
                accepted.append({"code": code, "candidates": allowed, "reason": str(entry.get("reason", ""))[:250]})
            log_event(conn, num, "llm_proposals_unverified", {"accepted": accepted})
            current = analyze(case, use_metadata=metadata, llm_hints=hints)
            log_event(conn, num, "rescore", {"score": current["objective_score"],
                                              "mapping": {c: p["term"] for c, p in current["proposals"].items()}})
        current["agent_rounds_completed"] = rounds
        current["audit_database"] = str(db_path)
        current["warning"] = "LLM suggestions influence ranking only; an AI guess never becomes a verified mapping."
        return current
    finally:
        conn.close()
