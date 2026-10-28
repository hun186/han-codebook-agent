"""Deterministic regression coverage for LLM settings/Job admission races.

All inference and vocabulary generation are mocked: no research data leaves loopback.
"""
from __future__ import annotations

import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib import error, request

from han_codebook.core import analyze, load_case
from han_codebook.model_settings import save_model_settings
from han_codebook.web import create_handler

ROOT = Path(__file__).resolve().parents[1]


class LLMConfigRaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cfg = self.root / "config.yaml"
        self.cfg.write_text(
            "project: {}\nanalysis: {}\nllm:\n"
            "  base_url: http://127.0.0.1:11434\n"
            "  model: approved-model\n"
            "  timeout_seconds: 30\n", encoding="utf-8",
        )
        self.jobs = {}
        self.server = ThreadingHTTPServer(
            ("127.0.0.1", 0), create_handler(self.root, self.cfg, self.jobs)
        )
        self.server_thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.server_thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.case = load_case(ROOT / "examples" / "demo_case.json")
        self.case.pop("ground_truth", None)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=3)
        self.temp.cleanup()

    def post(self, path, payload):
        req = request.Request(
            self.base + path,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Han-UI": "local",
                "Origin": self.base,
            },
            method="POST",
        )
        with request.urlopen(req, timeout=8) as response:
            return json.load(response)

    def settings(self, model, port):
        return {
            "base_url": f"http://127.0.0.1:{port}",
            "model": model,
            "timeout_seconds": 30,
            "allow_private_network": False,
            "api_key_env": "",
        }

    def wait_completed(self, job_id):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            with request.urlopen(self.base + "/api/jobs/" + job_id, timeout=5) as response:
                state = json.load(response)
            if state["status"] in ("completed", "failed"):
                return state
            time.sleep(0.02)
        self.fail(f"Job {job_id} failed to finish")

    def fake_analysis(self, case, *, rounds, **kwargs):
        result = analyze(case, iterations=1, restarts=1)
        result["agent_rounds_completed"] = rounds
        return result

    def test_save_in_progress_cannot_admit_job_until_write_finishes(self):
        """Reproduces Codex P2: a save blocked mid-write must block /api/start."""
        import han_codebook.model_settings as module

        inside_save = threading.Event()
        release_save = threading.Event()
        started_request = threading.Event()
        observed = []

        def blocked_save(path, payload):
            inside_save.set()
            if not release_save.wait(timeout=6):
                raise AssertionError("Timed out waiting for controlled write release")
            return save_model_settings(path, payload)

        def capture_runner(case, *, rounds, **kwargs):
            observed.append((kwargs["model"], kwargs["llm_url"]))
            return self.fake_analysis(case, rounds=rounds, **kwargs)

        def begin_analysis():
            started_request.set()
            return self.post("/api/start", {"case": self.case, "rounds": 1})

        with patch.object(module, "save_model_settings", side_effect=blocked_save), \
             patch("han_codebook.web.run_agent", side_effect=capture_runner):
            with ThreadPoolExecutor(max_workers=2) as pool:
                writer = pool.submit(
                    self.post, "/api/settings/llm", self.settings("replacement-model", 18080)
                )
                try:
                    self.assertTrue(inside_save.wait(timeout=3))
                    starter = pool.submit(begin_analysis)
                    self.assertTrue(started_request.wait(timeout=3))
                    # The active write still holds the admission lock; neither
                    # an accepted Job nor a completed start response may appear.
                    time.sleep(0.2)
                    self.assertEqual(self.jobs, {})
                    self.assertFalse(starter.done())
                finally:
                    release_save.set()
                self.assertEqual(writer.result(timeout=5)["model"], "replacement-model")
                job_id = starter.result(timeout=5)["job_id"]
            state = self.wait_completed(job_id)
            self.assertEqual(state["status"], "completed", state.get("error"))
            self.assertEqual(observed, [("replacement-model", "http://127.0.0.1:18080")])

    def _defer_job_thread(self, job_name, deferred):
        """Keep the accepted Job queued until the test explicitly runs its worker."""
        original = threading.Thread

        def thread_factory(*args, **kwargs):
            if kwargs.get("name") != job_name:
                return original(*args, **kwargs)

            class DeferredJob:
                def start(self):
                    deferred.append(kwargs["target"])

            return DeferredJob()

        return patch("han_codebook.web.threading.Thread", side_effect=thread_factory)

    def test_accepted_analysis_uses_immutable_model_and_destination(self):
        deferred = []
        observed = []

        def capture_runner(case, *, rounds, **kwargs):
            observed.append((kwargs["model"], kwargs["llm_url"]))
            return self.fake_analysis(case, rounds=rounds, **kwargs)

        with patch("han_codebook.web.run_agent", side_effect=capture_runner):
            with self._defer_job_thread("codebook-job", deferred):
                job_id = self.post("/api/start", {"case": self.case, "rounds": 2})["job_id"]
            self.assertEqual(len(deferred), 1)
            with self.assertRaises(error.HTTPError) as context:
                self.post("/api/settings/llm", self.settings("replacement-model", 18080))
            self.assertEqual(context.exception.code, 409)

            # Simulate an external operator editing the YAML after admission;
            # a queued job must *still* use the previously approved snapshot.
            save_model_settings(self.cfg, self.settings("replacement-model", 18080))
            deferred[0]()
            state = self.wait_completed(job_id)
            self.assertEqual(state["status"], "completed", state.get("error"))
            self.assertEqual(observed, [("approved-model", "http://127.0.0.1:11434")])

    def test_accepted_vocabulary_uses_immutable_model_and_destination(self):
        deferred = []
        observed = []
        case = dict(self.case)
        case["known_pairs"] = []

        def fake_generate(_case, *, llm_settings, **_kwargs):
            observed.append((llm_settings["model"], llm_settings["base_url"]))
            return None, {"terms": [], "patterns": [], "model": llm_settings["model"]}

        with patch("han_codebook.auto_vocabulary.generate_vocabulary",
                   side_effect=fake_generate):
            with self._defer_job_thread("vocabulary-job", deferred):
                job_id = self.post("/api/suggest-vocabulary", {
                    "case": case, "confirmed": True
                })["job_id"]
            self.assertEqual(len(deferred), 1)
            save_model_settings(self.cfg, self.settings("replacement-model", 18080))
            deferred[0]()
            state = self.wait_completed(job_id)
            self.assertEqual(state["status"], "completed", state.get("error"))
            self.assertEqual(observed, [("approved-model", "http://127.0.0.1:11434")])


if __name__ == "__main__":
    unittest.main()
