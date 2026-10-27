"""Optional localhost OpenAI-compatible LLM proposal loop.

The model never receives 'ground_truth' or credentials, and cannot alter verified anchors.
"""
from __future__ import annotations

import ipaddress
import json
import os
import sqlite3
import socket
import time
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
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
                    api_key_env: str | None = None,
                    on_exchange: Callable[[str, dict[str, Any]], None] | None = None) -> dict[str, Any]:
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
    if on_exchange:
        on_exchange("llm_request", {"url": req.full_url, "model": model, "body": body})
    started_at = time.monotonic()
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read(500_000)
        if on_exchange:
            try:
                meta = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                meta = {}
            on_exchange("llm_response", {"url": req.full_url,
                "response": raw.decode("utf-8", errors="replace"),
                "elapsed_ms": round((time.monotonic() - started_at)*1000, 1),
                "usage": meta.get("usage") if isinstance(meta, dict) else None})
    except error.HTTPError as exc:
        reason = {400: "request rejected or incompatible API parameters", 401: "authentication required (set llm.api_key_env)",
                  403: "forbidden by service or proxy", 404: "API path or model not found; check /v1/chat/completions route",
                  405: "HTTP method not allowed; check API proxy", 422: "request schema/model not accepted",
                  502: "reverse proxy cannot reach the LLM upstream", 503: "LLM service unavailable",
                  504: "reverse proxy timed out"}.get(exc.code, "HTTP error")
        raise CaseError(f"LLM HTTP {exc.code}: {reason} (URL: {req.full_url})") from exc
    except (error.URLError, TimeoutError, ConnectionError) as exc:
        raise CaseError(f"LLM network error on {req.full_url}: {exc}") from exc
    try:
        if raw.lstrip().startswith((b"<!DOCTYPE", b"<html", b"<HTML")):
            raise ValueError("HTML returned instead of JSON; check proxy/API path")
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


def probe_llm_service(base_url: str, *, timeout: int = 6,
                      allow_private_network: bool = False,
                      allowed_hosts: tuple[str, ...] | list[str] = (),
                      api_key_env: str | None = None,
                      report: Callable[[str], None] = print) -> bool:
    """Lightweight transport + models-route diagnostics. No case data or LLM inference.

    A missing /v1/models route is inconclusive: some gateways support only chat.
    Return False for confirmed networking/authentication/proxy problems.
    """
    validate_llm_endpoint(base_url, allow_private_network=allow_private_network, allowed_hosts=allowed_hosts)
    parsed = parse.urlparse(base_url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    report(f"[check] TCP {host}:{port} (timeout {timeout}s) ...")
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except (OSError, TimeoutError) as exc:
        report(f"[ERROR] TCP connection failed: {exc}. Check network/firewall and service port.")
        return False
    report("[OK] TCP connected. Checking /v1/models (not a chat-model inference) ...")
    api = base_url.rstrip("/")
    if not api.endswith("/v1"):
        api += "/v1"
    headers = {"Accept": "application/json"}
    if api_key_env:
        token = os.environ.get(api_key_env)
        if not token:
            report(f"[ERROR] Missing authentication environment variable: {api_key_env}")
            return False
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(api + "/models", headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            content = response.read(100_000)
        if content.lstrip().startswith(b"<"):
            report("[WARN] /v1/models returned HTML, likely a web UI or reverse proxy page; chat API is unverified.")
            return False
        data = json.loads(content.decode("utf-8"))
        models = data.get("data") if isinstance(data, dict) else None
        if not isinstance(models, list):
            report("[WARN] /v1/models returned JSON but not an OpenAI-compatible model list; chat API is unverified.")
            return True
        available = [v.get("id") for v in models if isinstance(v, dict) and isinstance(v.get("id"), str)]
        report(f"[OK] /v1/models listed {len(available)} model(s)" + (": " + ", ".join(available[:8]) if available else ""))
        return True
    except error.HTTPError as exc:
        if exc.code in (404, 405, 501):
            report(f"[WARN] /v1/models HTTP {exc.code} unsupported; chat endpoint may still work.")
            return True
        report(f"[ERROR] /v1/models HTTP {exc.code}; check authentication or reverse proxy.")
        return False
    except (error.URLError, TimeoutError, ConnectionError, ValueError) as exc:
        report(f"[WARN] /v1/models check inconclusive: {exc}; chat endpoint may still work.")
        return True


def run_agent(case: dict[str, Any], *, rounds: int = 0, llm_url: str = "http://127.0.0.1:11434/v1",
              model: str = "qwen3:14b", db_path: str = "artifacts/audit.sqlite",
              metadata: bool = True, llm_timeout: int = 90,
              allow_private_network: bool = False,
              llm_allowed_hosts: tuple[str, ...] | list[str] = (),
              llm_api_key_env: str | None = None,
              progress: Callable[[str], None] | None = None,
              capture_llm_io: bool = False,
              solver_iterations: int = 8, solver_restarts: int = 4) -> dict[str, Any]:
    if rounds:
        validate_llm_endpoint(llm_url, allow_private_network=allow_private_network,
                              allowed_hosts=llm_allowed_hosts)
    conn = create_audit(db_path)
    run_id = uuid.uuid4().hex
    try:
        anchors, reviews, vocab = anchors_and_review(case)
        domains = list(case["profiles"])
        log_event(conn, 0, "run_started", {"run_id": run_id, "model": model if rounds else None, "rounds_requested": rounds, "capture_llm_io": capture_llm_io})
        log_event(conn, 0, "preflight", {"messages": len(case["messages"]), "known_anchors": len(anchors),
                                         "ambiguous_pairs": len(reviews), "domains": domains})
        hints: dict[str, dict[str, float]] = {}
        if progress:
            progress("[analysis] Computing local statistical baseline ...")
        current = analyze(case, use_metadata=metadata, iterations=solver_iterations, restarts=solver_restarts)
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
                "messages": (case["messages"][:50] if metadata else [
                    {"id": m["id"], "codes": m["codes"]} for m in case["messages"][:50]
                ]),
                "unresolved": unresolved,
            }
            if progress:
                progress(f"[agent] Round {num}/{rounds}: requesting {model} from {llm_url.rstrip('/')}/v1/chat/completions "
                         f"(socket timeout {llm_timeout}s; {len(unresolved)} unresolved codes) ...")
            start = time.monotonic()
            done = threading.Event()
            def heartbeat() -> None:
                while not done.wait(10):
                    if progress:
                        progress(f"[agent] Round {num}/{rounds}: still waiting for LLM ({time.monotonic()-start:.0f}s elapsed); "
                                 "model initialization or generation may be running ...")
            worker = threading.Thread(target=heartbeat, daemon=True) if progress else None
            if worker:
                worker.start()
            try:
                extra = {"on_exchange": lambda stage, payload: log_event(conn, num, stage, payload)} if capture_llm_io else {}
                reply = query_local_llm(llm_url, model, packet, timeout=llm_timeout,
                                        allow_private_network=allow_private_network,
                                        allowed_hosts=llm_allowed_hosts,
                                        api_key_env=llm_api_key_env, **extra)
            finally:
                done.set()
                if worker:
                    worker.join(timeout=1)
            if progress:
                progress(f"[agent] Round {num}/{rounds}: API response received in {time.monotonic()-start:.1f}s; "
                         "validating candidate proposals ...")
            accepted = []
            rejected_count = 0
            baseline_mapping = {c: p["term"] for c, p in current["proposals"].items()}
            for entry in reply["hypotheses"][:15]:
                if not isinstance(entry, dict):
                    rejected_count += 1
                    continue
                code, candidates = entry.get("code"), entry.get("candidates", [])
                if code not in unresolved or not isinstance(candidates, list):
                    rejected_count += 1
                    continue
                allowed = [x for x in candidates[:5] if isinstance(x, str) and x in vocab]
                if not allowed:
                    rejected_count += 1
                    continue
                for rank, word in enumerate(allowed):
                    hints.setdefault(code, {})[word] = min(0.6, hints.get(code, {}).get(word, 0.0) + 0.25 / (rank + 1))
                accepted.append({"code": code, "candidates": allowed, "reason": str(entry.get("reason", ""))[:250]})
            log_event(conn, num, "llm_proposals_unverified", {"accepted": accepted, "rejected_count": rejected_count, "returned_count": len(reply["hypotheses"])})
            if progress:
                progress(f"[agent] Round {num}/{rounds}: accepted {len(accepted)} unverified code hypotheses; reranking ...")
            current = analyze(case, use_metadata=metadata, llm_hints=hints,
                              iterations=solver_iterations, restarts=solver_restarts)
            new_mapping = {c: p["term"] for c, p in current["proposals"].items()}
            changes = {code: {"before": previous, "after": new_mapping[code]}
                       for code, previous in baseline_mapping.items() if previous != new_mapping[code]}
            log_event(conn, num, "rescore", {"score": current["objective_score"],
                                              "mapping": new_mapping, "changes": changes, "changed_count": len(changes)})
        current["agent_rounds_completed"] = rounds
        current["run_id"] = run_id
        current["audit_database"] = str(db_path)
        current["warning"] = "LLM suggestions influence ranking only; an AI guess never becomes a verified mapping."
        return current
    finally:
        conn.close()
