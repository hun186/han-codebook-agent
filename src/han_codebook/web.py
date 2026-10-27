"""Loopback-only research UI. No third-party JS, external bind, or generic file server."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from typing import Any

from .agent import run_agent
from .config import load_settings
from .core import CaseError, load_case, validate_case

MAX_BODY = 1_500_000


def list_cases(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for directory in (root / "examples", root / "benchmarks" / "cases", root / "benchmarks" / "volume", root / "artifacts" / "ui_cases"):
        if directory.is_dir():
            for p in sorted(directory.glob("*.json")):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and "messages" in data and "profiles" in data:
                        result[str(p.relative_to(root)).replace(os.sep, "/")] = p
                except (OSError, ValueError):
                    continue
    return result


def audit_timeline(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with sqlite3.connect(path) as db:
        rows = db.execute("SELECT at_utc, round, stage, payload_json FROM events ORDER BY id").fetchall()
    return [{"at": timestamp, "round": number, "stage": stage, "payload": json.loads(payload)}
            for timestamp, number, stage, payload in rows]


def create_handler(root: Path, settings_path: Path, jobs: dict[str, dict[str, Any]] | None = None):
    root = root.resolve()
    settings_path = settings_path.resolve()
    jobs = jobs if jobs is not None else {}
    jobs_lock = threading.Lock()
    static = Path(__file__).parent / "static" / "index.html"

    class Handler(BaseHTTPRequestHandler):
        server_version = "HanCodebookLocal/0.3"

        def log_message(self, *_args):
            return

        def _security(self) -> bool:
            host = self.headers.get("Host", "")
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if host not in allowed:
                self._json(403, {"error": "Loopback Host required"})
                return False
            if self.command == "POST":
                origin = self.headers.get("Origin")
                if origin and origin not in {f"http://{h}" for h in allowed}:
                    self._json(403, {"error": "Cross-origin writes are forbidden"})
                    return False
                if not origin and self.headers.get("X-Han-UI") != "local":
                    self._json(403, {"error": "Local UI request header required"})
                    return False
            return True

        def _json(self, status: int, payload: dict | list) -> None:
            out = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(out)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(out)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                raise ValueError(f"Invalid body size; max {MAX_BODY} bytes")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Request must be a JSON object")
            return data

        def do_GET(self):
            if not self._security():
                return
            url = urlsplit(self.path)
            if url.path == "/":
                html = static.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; object-src 'none'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(html)
                return
            if url.path == "/api/cases":
                self._json(200, [{"id": key} for key in list_cases(root)])
                return
            if url.path == "/api/case":
                key = parse_qs(url.query).get("id", [""])[0]
                filename = list_cases(root).get(key)
                if filename is None:
                    return self._json(404, {"error": "Unknown case"})
                case = load_case(filename)
                case.pop("ground_truth", None)
                self._json(200, case)
                return
            if url.path == "/api/benchmark":
                target = root / "artifacts" / "benchmark_results.json"
                if not target.is_file():
                    return self._json(404, {"error": "No offline benchmark report saved yet"})
                return self._json(200, json.loads(target.read_text(encoding="utf-8")))
            if url.path == "/api/settings":
                cfg = load_settings(settings_path)
                llm = cfg["llm"]
                self._json(200, {"model": llm.get("model"), "endpoint": llm.get("base_url"),
                                 "capture_io_available": True,
                                 "note": "LLM network calls happen only after explicitly pressing the LLM run button."})
                return
            if url.path.startswith("/api/jobs/") and url.path.endswith("/report.md"):
                job_id = url.path.split('/')[3] if len(url.path.split('/')) == 5 else ''
                with jobs_lock:
                    j = jobs.get(job_id)
                if not j or j.get("status") != "completed" or j.get("type") != "analysis":
                    return self._json(404, {"error": "Research report unavailable"})
                report = (root / "artifacts" / "web_runs" / job_id / "report.md").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="investigation-report.md"')
                self.send_header("Content-Length", str(len(report)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(report)
                return
            if url.path.startswith("/api/jobs/"):
                key = url.path.rsplit("/", 1)[-1]
                with jobs_lock:
                    job = copy.deepcopy(jobs.get(key))
                if job is None:
                    return self._json(404, {"error": "Unknown job"})
                self._json(200, job)
                return
            self._json(404, {"error": "Not found"})

        def do_POST(self):
            if not self._security():
                return
            try:
                data = self._body()
                if self.path == "/api/save":
                    case = data.get("case")
                    if not isinstance(case, dict) or "ground_truth" in case:
                        raise CaseError("Saved research case must exclude ground_truth")
                    validate_case(case)
                    name = data.get("name", "edited_research")
                    if not isinstance(name, str) or not 1 <= len(name) <= 50 or not all(c.isascii() and (c.isalnum() or c in "_-") for c in name):
                        raise CaseError("Name must contain only ASCII letters, digits, _ or - (1..50)")
                    target = root / "artifacts" / "ui_cases" / (name + ".json")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    # Create-only: avoid silently destroying an existing case.
                    with target.open("x", encoding="utf-8") as handle:
                        json.dump(case, handle, ensure_ascii=False, indent=2)
                    return self._json(201, {"saved_as": str(target.relative_to(root)).replace(os.sep, "/")})
                if self.path == "/api/start-benchmark":
                    with jobs_lock:
                        if any(j["status"] in ("queued", "running") for j in jobs.values()):
                            return self._json(409, {"error": "An investigation is already running"})
                        job_id = secrets.token_hex(8)
                        jobs[job_id] = {"id": job_id, "type": "benchmark", "status": "queued",
                                        "logs": [], "result": None, "events": [], "error": None}
                    def benchmark_work():
                        from .benchmark import run_suite
                        with jobs_lock:
                            jobs[job_id]["status"] = "running"
                        try:
                            report = run_suite(root / "benchmarks" / "suite.json", rounds=0,
                                progress=lambda message: jobs[job_id]["logs"].append(str(message)))
                            output = root / "artifacts" / "benchmark_results.json"
                            output.parent.mkdir(parents=True, exist_ok=True)
                            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                            with jobs_lock:
                                jobs[job_id]["result"] = report
                                jobs[job_id]["status"] = "completed"
                        except Exception as exc:
                            with jobs_lock:
                                jobs[job_id]["status"] = "failed"
                                jobs[job_id]["error"] = f"{type(exc).__name__}: {exc}"
                    threading.Thread(target=benchmark_work, daemon=True, name="benchmark-job").start()
                    return self._json(202, {"job_id": job_id})
                if self.path == "/api/start":
                    case = data.get("case")
                    if not isinstance(case, dict) or "ground_truth" in case:
                        raise CaseError("Inference case must exclude ground_truth")
                    validate_case(case)
                    rounds = data.get("rounds", 0)
                    if type(rounds) is not int or rounds not in (0, 1, 2, 3):
                        raise CaseError("Rounds must be an integer from 0 to 3")
                    metadata = data.get("use_metadata", True)
                    if type(metadata) is not bool:
                        raise CaseError("use_metadata must be boolean")
                    capture = data.get("capture_llm_io", False)
                    if type(capture) is not bool:
                        raise CaseError("capture_llm_io must be boolean")
                    with jobs_lock:
                        if sum(j["status"] in ("queued", "running") for j in jobs.values()) >= 1:
                            return self._json(409, {"error": "An investigation is already running"})
                        job_id = secrets.token_hex(8)
                        jobs[job_id] = {"id": job_id, "type": "analysis", "status": "queued", "logs": [], "result": None,
                                        "events": [], "error": None}
                    input_case = copy.deepcopy(case)
                    def work():
                        target = root / "artifacts" / "web_runs" / job_id
                        with jobs_lock:
                            jobs[job_id]["status"] = "running"
                        def progress(message):
                            with jobs_lock:
                                jobs[job_id]["logs"].append(str(message))
                        try:
                            target.mkdir(parents=True, exist_ok=True)
                            cfg = load_settings(settings_path)
                            llm = cfg["llm"]
                            result = run_agent(input_case, rounds=rounds,
                                llm_url=llm.get("base_url", "http://127.0.0.1:11434/v1"),
                                model=llm.get("model", "qwen3:14b"),
                                db_path=str(target / "audit.sqlite"), metadata=metadata,
                                llm_timeout=llm.get("timeout_seconds", 90),
                                allow_private_network=llm.get("allow_private_network", False),
                                llm_allowed_hosts=llm.get("allowed_hosts", []),
                                llm_api_key_env=llm.get("api_key_env"), progress=progress,
                                capture_llm_io=capture and rounds > 0,
                                solver_iterations=3, solver_restarts=2)
                            (target / "result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
                            events = audit_timeline(target / "audit.sqlite")
                            from .report import investigation_report
                            (target / "report.md").write_text(investigation_report(result, events), encoding="utf-8")
                            with jobs_lock:
                                jobs[job_id]["result"] = result
                                jobs[job_id]["events"] = events
                                jobs[job_id]["status"] = "completed"
                        except Exception as exc:
                            with jobs_lock:
                                jobs[job_id]["status"] = "failed"
                                jobs[job_id]["error"] = f"{type(exc).__name__}: {exc}"
                                try:
                                    jobs[job_id]["events"] = audit_timeline(target / "audit.sqlite")
                                except (OSError, sqlite3.Error, ValueError) as audit_error:
                                    jobs[job_id]["logs"].append(f"[WARN] Audit could not be read: {audit_error}")
                    threading.Thread(target=work, daemon=True, name="codebook-job").start()
                    return self._json(202, {"job_id": job_id})
                self._json(404, {"error": "Not found"})
            except FileExistsError:
                self._json(409, {"error": "Saved case already exists: choose a different name"})
            except (ValueError, OSError, KeyError) as exc:
                self._json(400, {"error": str(exc)})

    return Handler


def serve(root: Path, config: Path, host: str = "127.0.0.1", port: int = 8765) -> None:
    if host not in ("127.0.0.1", "localhost"):
        raise ValueError("Research UI may only bind to localhost")
    handler = create_handler(root, config)
    with ThreadingHTTPServer(("127.0.0.1", port), handler) as server:
        print(f"[web] Han Codebook local research UI: http://127.0.0.1:{server.server_port}", flush=True)
        print("[web] Loopback-only. Ctrl+C to stop. Research results saved under artifacts/web_runs/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Local-only browser workspace")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    config = (root / args.config).resolve()
    if not config.is_file():
        parser.error("YAML config file not found")
    serve(root, config, port=args.port)


if __name__ == "__main__":
    main()
