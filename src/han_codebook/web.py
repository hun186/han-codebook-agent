"""Loopback-only research UI. No third-party JS, external bind, or generic file server."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import secrets
import re
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
    # Events remain outside the JSON-facing job record.
    review_waiters: dict[str, dict[str, Any]] = {}
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
                from .model_settings import model_settings
                settings = model_settings(settings_path)
                self._json(200, {**settings, "endpoint": settings["base_url"],
                                 "capture_io_available": True,
                                 "note": "Local/private OpenAI-compatible model only; credentials remain in environment variables."})
                return
            if url.path.startswith("/api/jobs/") and (url.path.endswith("/report.docx") or url.path.endswith("/report.md")):
                parts = url.path.split("/")
                job_id = parts[3] if len(parts) == 5 else ""
                if not re.fullmatch(r"[0-9a-f]{16}", job_id):
                    return self._json(404, {"error": "Unknown report"})
                with jobs_lock:
                    job = jobs.get(job_id)
                if job and (job.get("status") != "completed" or job.get("type") != "analysis"):
                    return self._json(404, {"error": "Analysis has not completed"})
                target = root / "artifacts" / "web_runs" / job_id
                wants_word = parts[4] == "report.docx"
                report_file = target / ("report.docx" if wants_word else "report.md")
                # Historical reports from before this deployment still have
                # result.json and audit.sqlite; make DOCX available on demand.
                if wants_word and not report_file.is_file():
                    result_json = target / "result.json"
                    audit_sqlite = target / "audit.sqlite"
                    if result_json.is_file() and audit_sqlite.is_file():
                        from .report_docx import investigation_docx
                        result = json.loads(result_json.read_text(encoding="utf-8"))
                        document = investigation_docx(result, audit_timeline(audit_sqlite))
                        report_file.write_bytes(document)
                if not report_file.is_file():
                    return self._json(404, {"error": "Research report unavailable"})
                blob = report_file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                                 if wants_word else "text/markdown; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="investigation-report.docx"'
                                 if wants_word else 'attachment; filename="investigation-report.md"')
                self.send_header("Content-Length", str(len(blob)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(blob)
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
                cancel_match = re.fullmatch(r"/api/jobs/([0-9a-f]{16})/cancel", self.path)
                if cancel_match:
                    if data:
                        raise CaseError("Cancel does not accept an arbitrary payload")
                    job_id = cancel_match.group(1)
                    with jobs_lock:
                        job = jobs.get(job_id)
                        if (not job or job.get("candidate_mode") != "human"
                                or job["status"] not in ("queued", "running", "awaiting_review", "cancelling")):
                            return self._json(409, {"error": "No cancellable human-review job"})
                        job["cancel_requested"] = True
                        job["status"] = "cancelling"
                        job["logs"].append("[review] Canceled after research case was changed")
                        waiter = review_waiters.get(job_id)
                        if waiter:
                            waiter["event"].set()
                    return self._json(200, {"status": "cancelling"})
                review_match = re.fullmatch(r"/api/jobs/([0-9a-f]{16})/review", self.path)
                if review_match:
                    job_id = review_match.group(1)
                    approved = data.get("approved")
                    if (set(data) != {"approved"} or not isinstance(approved, list)
                            or len(approved) > 32 or any(not isinstance(w, str) for w in approved)
                            or len(set(approved)) != len(approved)):
                        raise CaseError("Approved words must be a distinct string list (at most 32)")
                    with jobs_lock:
                        waiter = review_waiters.get(job_id)
                        job = jobs.get(job_id)
                        if not waiter or not job or job["status"] != "awaiting_review" or waiter["submitted"]:
                            return self._json(409, {"error": "No active vocabulary review for this job"})
                        offered = set(waiter["offered"])
                        if any(w not in offered for w in approved):
                            raise CaseError("Cannot approve words outside this round's pending candidates")
                        waiter["approved"] = approved[:]
                        waiter["submitted"] = True
                        job["review_submitted"] = True
                        waiter["event"].set()
                    return self._json(200, {"accepted": len(approved), "status": "submitted"})
                if self.path == "/api/settings/llm":
                    from .model_settings import save_model_settings
                    # The active-job check and the entire config write form one
                    # critical section with job admission and its LLM snapshot.
                    with jobs_lock:
                        if any(j["status"] in ("queued", "running", "awaiting_review", "cancelling") for j in jobs.values()):
                            return self._json(409, {"error": "Cannot change LLM settings while an investigation is active"})
                        new_settings = save_model_settings(settings_path, data)
                    return self._json(200, {**new_settings, "endpoint": new_settings["base_url"]})
                if self.path == "/api/settings/test":
                    if data.get("confirmed") is not True or set(data) != {"confirmed"}:
                        raise CaseError("Confirm a metadata-only connection check first")
                    from .agent import probe_llm_service
                    cfg = load_settings(settings_path)["llm"]
                    trace = []
                    ok = probe_llm_service(cfg.get("base_url","http://127.0.0.1:11434"),
                        timeout=min(cfg.get("timeout_seconds",90),8),
                        allow_private_network=cfg.get("allow_private_network",False),
                        allowed_hosts=cfg.get("allowed_hosts",[]),
                        api_key_env=cfg.get("api_key_env"), report=trace.append)
                    return self._json(200, {"connected":ok,"diagnostics":trace,
                           "note":"Only TCP and /v1/models checked; chat completions not verified."})
                if self.path == "/api/event-links":
                    case = data.get("case")
                    if not isinstance(case, dict) or any(k in case for k in ("gold", "codebook", "ground_truth")):
                        raise CaseError("Event analysis requires a research case without embedded gold")
                    from .event_links import suggest_event_links
                    return self._json(200, {"events": suggest_event_links(case)})
                if self.path == "/api/suggest-vocabulary":
                    case = data.get("case")
                    if not isinstance(case, dict) or any(k in case for k in ("gold", "codebook", "ground_truth")):
                        raise CaseError("LLM candidate generation requires a case without gold")
                    validate_case(case)
                    if case.get("known_pairs"):
                        raise CaseError("Cold-start candidate generation requires no known plaintext pairs")
                    if data.get("confirmed") is not True:
                        raise CaseError("LLM network use must be explicitly confirmed")
                    with jobs_lock:
                        if any(j["status"] in ("queued", "running", "awaiting_review", "cancelling") for j in jobs.values()):
                            return self._json(409, {"error": "An investigation is already running"})
                        llm_snapshot = copy.deepcopy(load_settings(settings_path)["llm"])
                        job_id = secrets.token_hex(8)
                        jobs[job_id] = {"id":job_id,"type":"vocabulary","status":"queued",
                                        "logs":[],"result":None,"events":[],"error":None}
                    input_case = copy.deepcopy(case)
                    def vocabulary_work():
                        with jobs_lock:
                            jobs[job_id]["status"] = "running"
                        def progress(message):
                            with jobs_lock:
                                jobs[job_id]["logs"].append(str(message))
                        try:
                            from .auto_vocabulary import generate_vocabulary
                            _,record = generate_vocabulary(input_case,metadata=data.get("use_metadata", True),
                                 llm_settings=llm_snapshot,progress=progress,capture_io=False)
                            # Do not mutate user profiles/ideas; proposals remain pending review.
                            with jobs_lock:
                                jobs[job_id]["result"] = {"terms":record["terms"],
                                      "patterns":record["patterns"],"model":record["model"],
                                      "status":"unverified_pending_researcher_review"}
                                jobs[job_id]["status"] = "completed"
                        except Exception as exc:
                            with jobs_lock:
                                jobs[job_id]["status"]="failed"
                                jobs[job_id]["error"]=f"{type(exc).__name__}: {exc}"
                    threading.Thread(target=vocabulary_work,daemon=True,name="vocabulary-job").start()
                    return self._json(202,{"job_id":job_id})
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
                        if any(j["status"] in ("queued", "running", "awaiting_review", "cancelling") for j in jobs.values()):
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
                    if type(rounds) is not int or not 0 <= rounds <= 20:
                        raise CaseError("Rounds must be an integer from 0 to 20")
                    metadata = data.get("use_metadata", True)
                    if type(metadata) is not bool:
                        raise CaseError("use_metadata must be boolean")
                    capture = data.get("capture_llm_io", False)
                    if type(capture) is not bool:
                        raise CaseError("capture_llm_io must be boolean")
                    candidate_mode = data.get("candidate_mode", "static")
                    if type(candidate_mode) is not str or candidate_mode not in ("static", "automatic", "human"):
                        raise CaseError("candidate_mode must be static, automatic or human")
                    if candidate_mode != "static" and rounds == 0:
                        raise CaseError("Dynamic vocabulary requires at least one LLM round")
                    with jobs_lock:
                        if sum(j["status"] in ("queued", "running", "awaiting_review", "cancelling") for j in jobs.values()) >= 1:
                            return self._json(409, {"error": "An investigation is already running"})
                        # Pin the approved LLM destination/model at job admission;
                        # background execution must never reread mutable YAML.
                        llm_snapshot = copy.deepcopy(load_settings(settings_path)["llm"])
                        job_id = secrets.token_hex(8)
                        jobs[job_id] = {"id": job_id, "type": "analysis", "status": "queued", "logs": [], "result": None,
                                        "events": [], "error": None,
                                        "candidate_mode": candidate_mode, "cancel_requested": False}
                    input_case = copy.deepcopy(case)
                    def work():
                        target = root / "artifacts" / "web_runs" / job_id

                        def check_cancel() -> None:
                            with jobs_lock:
                                if jobs[job_id].get("cancel_requested"):
                                    raise CaseError("Research case changed; review job canceled without accepting new candidates")

                        def reviewer(round_number: int, proposed: list[dict]) -> list[str]:
                            # Timeout fails closed, never silently auto-accept.
                            if not proposed:
                                return []
                            event = threading.Event()
                            with jobs_lock:
                                if jobs[job_id].get("cancel_requested"):
                                    raise CaseError("Review job canceled before new vocabulary proposals")
                                jobs[job_id]["status"] = "awaiting_review"
                                jobs[job_id]["pending_review"] = {
                                    "round": round_number,
                                    "candidates": copy.deepcopy(proposed),
                                }
                                jobs[job_id]["review_submitted"] = False
                                review_waiters[job_id] = {
                                    "event": event,
                                    "offered": [item["term"] for item in proposed],
                                    "approved": [], "submitted": False,
                                }
                            try:
                                if not event.wait(600):
                                    raise CaseError("Human vocabulary review timed out; no candidates auto-accepted")
                                with jobs_lock:
                                    if jobs[job_id].get("cancel_requested"):
                                        raise CaseError("Review job canceled while awaiting human decision")
                                    selected = review_waiters[job_id]["approved"][:]
                                    jobs[job_id]["status"] = "running"
                                    jobs[job_id].pop("pending_review", None)
                                    jobs[job_id].pop("review_submitted", None)
                                return selected
                            finally:
                                with jobs_lock:
                                    review_waiters.pop(job_id, None)

                        with jobs_lock:
                            jobs[job_id]["status"] = "running"
                        def progress(message):
                            with jobs_lock:
                                jobs[job_id]["logs"].append(str(message))
                        try:
                            target.mkdir(parents=True, exist_ok=True)
                            llm = llm_snapshot
                            result = run_agent(input_case, rounds=rounds,
                                llm_url=llm.get("base_url", "http://127.0.0.1:11434/v1"),
                                model=llm.get("model", "qwen3:14b"),
                                db_path=str(target / "audit.sqlite"), metadata=metadata,
                                llm_timeout=llm.get("timeout_seconds", 90),
                                allow_private_network=llm.get("allow_private_network", False),
                                llm_allowed_hosts=llm.get("allowed_hosts", []),
                                llm_api_key_env=llm.get("api_key_env"), progress=progress,
                                capture_llm_io=capture and rounds > 0,
                                solver_iterations=3, solver_restarts=2,
                                adaptive_vocabulary=candidate_mode != "static",
                                vocabulary_reviewer=reviewer if candidate_mode == "human" else None,
                                cancel_check=check_cancel if candidate_mode == "human" else None)
                            (target / "result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
                            events = audit_timeline(target / "audit.sqlite")
                            from .report import investigation_report
                            (target / "report.md").write_text(investigation_report(result, events), encoding="utf-8")
                            try:
                                from .report_docx import investigation_docx
                            except ImportError:
                                progress("[WARN] Word export unavailable (python-docx missing). "
                                         "Install dependencies with setup_windows.bat or pip install -e .; "
                                         "analysis and Markdown remain available.")
                            else:
                                (target / "report.docx").write_bytes(investigation_docx(result, events))
                            with jobs_lock:
                                jobs[job_id]["result"] = result
                                jobs[job_id]["events"] = events
                                jobs[job_id]["status"] = "completed"
                        except Exception as exc:
                            with jobs_lock:
                                jobs[job_id]["status"] = "failed"
                                jobs[job_id].pop("pending_review", None)
                                jobs[job_id].pop("review_submitted", None)
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
