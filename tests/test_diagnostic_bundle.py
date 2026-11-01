"""Consent-gated diagnostic ZIP, redaction and incomplete-run regressions."""
from __future__ import annotations

from http.server import ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from urllib import request, error
from zipfile import ZipFile

from han_codebook.agent import create_audit, log_event
from han_codebook.diagnostic_bundle import build_diagnostic_zip
from han_codebook.web import create_handler
from han_codebook.core import load_case

ROOT = Path(__file__).resolve().parents[1]
SENTINEL = "PRIVATE_PLAINTEXT_SENTINEL_DO_NOT_SHARE"
PROMPT = "RAW_PROMPT_SECRET_SENTINEL"
CONFIG = {"model": "PRIVATE_MODEL_SECRET_SENTINEL", "rounds_requested": 3,
          "metadata": True, "capture_llm_io": True, "candidate_mode": "automatic"}


def unzip(blob):
    with ZipFile(BytesIO(blob)) as z:
        assert all("/" not in name and ".." not in name for name in z.namelist())
        return {n: z.read(n) for n in z.namelist()}


def seed(target: Path):
    target.mkdir(parents=True, exist_ok=True)
    (target / "input_case.json").write_text(
        json.dumps({"case_id": "TEST", "messages": [{"codes": ["001"],
                       "notes": SENTINEL}]}), encoding="utf-8"
    )
    with create_audit(target / "audit.sqlite") as db:
        log_event(db, 0, "statistical_baseline", {"mapping": {"001": SENTINEL}, "score": 30.3})
        log_event(db, 1, "llm_request", {"body": {"messages": [PROMPT]}, "url": "http://127.0.0.1:11434/v1"})
        log_event(db, 1, "llm_response", {"response": {"raw": PROMPT}, "elapsed_ms": 154.4,
                                          "usage": {"prompt_tokens": 50, "completion_tokens": 21}})
        log_event(db, 1, "llm_proposals_unverified", {"accepted": [{"code":"001", "candidates":[SENTINEL]}],
                                                       "rejected_count": 2})
        log_event(db, 1, "rescore", {"changed_count": 1,
                                    "mapping": {"001": SENTINEL}, "score": 42})
    (target / "result.json").write_text(json.dumps({"proposals": {SENTINEL: "x"}}))
    (target / "report.md").write_text("## " + SENTINEL, encoding="utf-8")
    (target / "report.docx").write_bytes(b"dummy docx payload")


class DiagnosticFormatTests(unittest.TestCase):
    def test_safe_and_explicit_private_modes_no_gold_or_secret_in_safe(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp)
            seed(target)
            jobid = "abcdef0123456789"
            safe = unzip(build_diagnostic_zip(target, job_id=jobid,
                        status="completed", config=CONFIG, private=False))
            self.assertEqual(set(safe), {"round_trace.jsonl", "diagnostics.json",
                                         "evaluation.json", "run_manifest.json"})
            text = b"".join(safe.values()).decode("utf-8")
            for secret in (SENTINEL, PROMPT, "PRIVATE_MODEL_SECRET_SENTINEL",
                           "127.0.0.1:11434", "audit.sqlite", "raw_model_token"):
                self.assertNotIn(secret, text)
            self.assertIn('"changed_count": 1', text)
            self.assertIn('"accepted_count": 1', text)
            self.assertIn('"capture_llm_io": true', text)
            self.assertIn('"complete": true', text)
            private = unzip(build_diagnostic_zip(target, job_id=jobid,
                          status="completed", config=CONFIG, private=True))
            self.assertIn("audit.sqlite", private)
            self.assertIn("input_case.json", private)
            self.assertIn("audit_events.jsonl", private)
            self.assertIn(SENTINEL, private["input_case.json"].decode())
            self.assertIn(PROMPT, private["audit_events.jsonl"].decode())
            self.assertIn("PRIVATE_MODEL_SECRET_SENTINEL",
                          private["run_manifest.json"].decode())
            # A separate synthetic gold is never copied even for PRIVATE.
            (target / "gold.json").write_text("MUST_NEVER_EXPORT_GOLD")
            private2 = unzip(build_diagnostic_zip(target, job_id=jobid,
                           status="completed", config=CONFIG, private=True))
            self.assertNotIn(b"MUST_NEVER_EXPORT_GOLD", b"".join(private2.values()))

    def test_partial_failure_status_and_no_raw_error_or_in_progress(self):
        with TemporaryDirectory() as tmp:
            target=Path(tmp)
            seed(target)
            summary=unzip(build_diagnostic_zip(target, job_id="1234567890abcdef",
                              status="failed", config=CONFIG,
                              error_type="CaseError"))
            self.assertIn(b'"complete": false', summary["run_manifest.json"])
            self.assertIn(b'"failure_category": "CaseError"', summary["diagnostics.json"])
            self.assertNotIn(b"RAW_PROMPT", b"".join(summary.values()))
            with self.assertRaises(ValueError):
                build_diagnostic_zip(target, job_id="1234567890abcdef",
                                     status="running", config=CONFIG)
            with self.assertRaises(ValueError):
                build_diagnostic_zip(target, job_id="../escape", status="failed",
                                     config=CONFIG)
            with self.assertRaises(ValueError):
                build_diagnostic_zip(target, job_id="1234567890abcdef",
                                     status="completed", config={**CONFIG, "url": SENTINEL})


class DiagnosticLoopbackHTTPTests(unittest.TestCase):
    def test_one_click_exports_success_failed_and_csrf_block(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root / "examples").mkdir()
            (root / "examples" / "test.json").write_text(
                (ROOT / "benchmarks/cases/07_alias_mixed_length.json").read_text(encoding="utf-8"),
                encoding="utf-8")
            (root / "config.yaml").write_text(
                "project: {}\nanalysis: {}\nllm:\n  model: mock\n  base_url: http://127.0.0.1:11434\n",
                encoding="utf-8")
            jobs={}
            server=ThreadingHTTPServer(("127.0.0.1",0),
                create_handler(root,root / "config.yaml",jobs))
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            url=f"http://127.0.0.1:{server.server_port}"
            def post(route,obj,origin=None):
                req=request.Request(url+route, data=json.dumps(obj).encode(),
                    headers={"Content-Type":"application/json","X-Han-UI":"local",
                             "Origin":origin or url}, method="POST")
                return request.urlopen(req, timeout=5)
            try:
                case=load_case(root / "examples" / "test.json")
                created=json.loads(post("/api/start", {
                    "case":case,"rounds":0,"use_metadata":True}).read())
                job=created["job_id"]
                for _ in range(100):
                    state=jobs[job]["status"]
                    if state in ("completed","failed"):break
                    time.sleep(.05)
                self.assertEqual(jobs[job]["status"],"completed",jobs[job].get("error"))
                route="/api/jobs/"+job+"/diagnostics"
                with self.assertRaises(error.HTTPError) as ctx:
                    post(route,{"mode":"private","confirmed":True},"http://untrusted.invalid")
                self.assertEqual(ctx.exception.code,403)
                with self.assertRaises(error.HTTPError) as ctx:
                    post(route,{"mode":"private","confirmed":False})
                self.assertEqual(ctx.exception.code,400)
                with self.assertRaises(error.HTTPError) as ctx:
                    request.urlopen(url+route)
                self.assertEqual(ctx.exception.code,404)
                with post(route,{"mode":"safe","confirmed":True}) as res:
                    self.assertEqual(res.headers["Content-Type"],"application/zip")
                    self.assertEqual(res.headers["Cache-Control"],"no-store")
                    exported=unzip(res.read())
                self.assertIn("diagnostics.json",exported)
                with post(route,{"mode":"private","confirmed":True}) as res:
                    private=unzip(res.read())
                self.assertEqual(json.loads(private["input_case.json"])["case_id"],
                                 case["case_id"])
                self.assertIn("audit.sqlite", private)
                # A previous failed run must not be reported as completed.
                failed="1a2b3c4d5e6f7890"
                target=root/"artifacts"/"web_runs"/failed
                seed(target)
                jobs[failed]={"type":"analysis","status":"failed",
                              "error":"CaseError: "+SENTINEL,
                              "diagnostic_config":CONFIG}
                with post("/api/jobs/"+failed+"/diagnostics",
                          {"mode":"safe","confirmed":True}) as res:
                    partial=unzip(res.read())
                self.assertIn(b'"complete": false',partial["run_manifest.json"])
                self.assertNotIn(SENTINEL.encode(),b"".join(partial.values()))
            finally:
                server.shutdown();server.server_close();thread.join(timeout=2)
