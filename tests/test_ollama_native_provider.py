"""Offline-only native Ollama contract for reasoning-only JSON responses.

No network, research case, paid API, or synthetic truth is sent to an LLM.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from han_codebook.agent import (llm_api_base, llm_chat_endpoint, probe_llm_service,
                                query_local_llm, validate_llm_endpoint)
from han_codebook.config import load_settings
from han_codebook.core import CaseError
from han_codebook.model_settings import save_model_settings

HOST = "192.168.0.134"
BASE = f"http://{HOST}:11434"
LAN = {"provider": "ollama", "allow_private_network": True,
       "allowed_hosts": [HOST]}


class FakeSocket:
    def __enter__(self): return self
    def __exit__(self, *args): return False


class FakeResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, limit): return self.body


class NativeOllamaTests(unittest.TestCase):
    def test_native_json_success_uses_think_false_and_not_openai_route(self):
        response = {"message": {"role": "assistant",
                    "content": '{"vocabulary":[{"term":"補給","reason":"上下文","evidence_message_ids":["M1"]}],"patterns":[]}'},
                    "done": True, "done_reason": "stop",
                    "prompt_eval_count": 1024, "eval_count": 80}
        events, metrics = [], []
        with patch("han_codebook.agent._urlopen_llm", return_value=FakeResponse(response)) as http:
            result = query_local_llm(BASE, "qwen3.8:latest-128k",
                {"task": "generate_vocabulary", "messages": [{"id": "M1"}]},
                reasoning_effort="none", response_format="json_object",
                on_exchange=lambda stage, payload: events.append((stage, payload)),
                on_metrics=metrics.append, **LAN)
        req = http.call_args.args[0]
        self.assertEqual(req.full_url, BASE + "/api/chat")
        body = json.loads(req.data)
        self.assertIs(body["think"], False)
        self.assertIs(body["stream"], False)
        self.assertEqual(body["format"], "json")
        self.assertEqual(body["options"]["temperature"], 0.2)
        self.assertNotIn("response_format", body)
        self.assertNotIn("reasoning_effort", body)
        self.assertEqual(result["vocabulary"][0]["term"], "補給")
        self.assertEqual(metrics[0]["completion_tokens"], 80)
        self.assertEqual(metrics[0]["prompt_tokens"], 1024)
        self.assertEqual(events[1][1]["url"], BASE + "/api/chat")

    def test_native_reasoning_only_never_promoted_to_answer(self):
        response = {"message": {"role": "assistant", "content": "",
                    "thinking": '{"vocabulary":[{"term":"不可以拿來當正式資料"}]}'},
                    "done": True, "done_reason": "stop",
                    "prompt_eval_count": 100, "eval_count": 3304}
        with patch("han_codebook.agent._urlopen_llm", return_value=FakeResponse(response)):
            with self.assertRaisesRegex(CaseError, r"empty final content .*reasoning_only=True.*3304"):
                query_local_llm(BASE, "qwen3.8:latest-128k",
                    {"task": "generate_vocabulary"}, **LAN)

    def test_native_invalid_json_and_incomplete_response_fail_closed(self):
        for output in ('{"vocabulary":', '{"hypotheses": []}'):
            reply = {"message": {"content": output},
                     "done": True, "done_reason": "stop", "eval_count": 5}
            with self.subTest(output=output), patch(
                "han_codebook.agent._urlopen_llm", return_value=FakeResponse(reply)):
                with self.assertRaisesRegex(CaseError, "LLM output not valid expected JSON"):
                    query_local_llm(BASE, "mock", {"task": "generate_vocabulary"}, **LAN)
        incomplete = {"message": {"content": '{"vocabulary":[]}'}, "done": False}
        with patch("han_codebook.agent._urlopen_llm", return_value=FakeResponse(incomplete)):
            with self.assertRaisesRegex(CaseError, "incomplete"):
                query_local_llm(BASE, "mock", {"task": "generate_vocabulary"}, **LAN)

    def test_native_probe_checks_tags_without_any_chat_completion(self):
        logs = []
        response = {"models": [{"name": "qwen3.8:latest-128k"}]}
        with patch("han_codebook.agent.socket.create_connection", return_value=FakeSocket()) as tcp, \
             patch("han_codebook.agent._urlopen_llm", return_value=FakeResponse(response)) as http:
            ok = probe_llm_service(BASE, report=logs.append, **LAN)
        self.assertTrue(ok)
        self.assertEqual(tcp.call_args.args[0], (HOST, 11434))
        self.assertEqual(http.call_args.args[0].full_url, BASE + "/api/tags")
        self.assertTrue(any("[OK] /api/tags listed 1 model" in line for line in logs))
        self.assertTrue(all("chat/completions" not in line for line in logs))

    def test_native_requires_root_exact_private_ip_and_same_allowlist(self):
        self.assertEqual(llm_api_base(BASE, "ollama"), BASE + "/api")
        self.assertEqual(llm_chat_endpoint(BASE, "ollama"), BASE + "/api/chat")
        self.assertEqual(llm_chat_endpoint(BASE, "local"), BASE + "/v1/chat/completions")
        for url in (BASE + "/v1", BASE + "/v1/", BASE + "/api", "https://example.com:11434"):
            with self.subTest(url=url), self.assertRaises(CaseError):
                validate_llm_endpoint(url, **LAN)
        with self.assertRaisesRegex(CaseError, "LAN access"):
            validate_llm_endpoint(BASE, provider="ollama", allowed_hosts=[HOST])
        with self.assertRaisesRegex(CaseError, "LAN access"):
            validate_llm_endpoint(BASE, provider="ollama", allow_private_network=True,
                                  allowed_hosts=["192.168.0.999"])

    def test_saved_provider_selects_native_and_cannot_enable_external_api(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.yaml"
            path.write_text("project: {}\nanalysis: {}\nllm: {}\n", encoding="utf-8")
            payload = {"provider": "ollama", "base_url": BASE,
                       "model": "qwen3.8:latest-128k",
                       "timeout_seconds": 120, "allow_private_network": True,
                       "allow_external_api": False, "api_key_env": ""}
            saved = save_model_settings(path, payload)
            self.assertEqual(saved["provider"], "ollama")
            self.assertEqual(saved["allowed_hosts"], [HOST])
            self.assertEqual(load_settings(path)["llm"]["provider"], "ollama")
            payload["allow_external_api"] = True
            with self.assertRaisesRegex(CaseError, "External API consent"):
                save_model_settings(path, payload)
            self.assertEqual(load_settings(path)["llm"]["allow_external_api"], False)


    def test_native_redirect_never_forwards_case_or_authorization(self):
        """Both native chat and native tags fail closed on cross-origin 302."""
        import os
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        received = []

        class Receiver(BaseHTTPRequestHandler):
            def do_GET(self): self.capture()
            def do_POST(self): self.capture()
            def capture(self):
                received.append((self.path, self.headers.get("Authorization")))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")
            def log_message(self, *args): pass

        destination = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
        location = f"http://127.0.0.1:{destination.server_port}/unapproved"

        class Redirector(BaseHTTPRequestHandler):
            def do_GET(self): self.redirect()
            def do_POST(self): self.redirect()
            def redirect(self):
                self.send_response(302)
                self.send_header("Location", location)
                self.end_headers()
            def log_message(self, *args): pass

        origin = ThreadingHTTPServer(("127.0.0.1", 0), Redirector)
        threads = []
        for server in (destination, origin):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            threads.append(thread)
        try:
            url = f"http://127.0.0.1:{origin.server_port}"
            with patch.dict(os.environ, {"HAN_NATIVE_OLLAMA_TEST_TOKEN": "not_for_other_hosts"}):
                with self.assertRaisesRegex(CaseError, "LLM HTTP 302"):
                    query_local_llm(url, "mock", {"task": "generate_vocabulary"},
                                    provider="ollama", api_key_env="HAN_NATIVE_OLLAMA_TEST_TOKEN")
                logs = []
                self.assertFalse(probe_llm_service(
                    url, provider="ollama", api_key_env="HAN_NATIVE_OLLAMA_TEST_TOKEN",
                    report=logs.append))
                self.assertTrue(any("/api/tags HTTP 302" in line for line in logs))
            self.assertEqual(received, [], "native redirect leaked a request to unapproved destination")
        finally:
            for server in (origin, destination):
                server.shutdown()
                server.server_close()
            for thread in threads: thread.join(timeout=3)



if __name__ == "__main__":
    unittest.main()
