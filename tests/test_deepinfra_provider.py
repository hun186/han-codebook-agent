"""Offline-only, secret-safe DeepInfra provider integration checks."""
from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from han_codebook.agent import (
    DEEPINFRA_BASE_URL, _RejectRedirects, llm_api_base,
    probe_llm_service, query_local_llm, run_agent, validate_llm_endpoint,
)
from han_codebook.cli import main as cli_main
from han_codebook.config import load_settings
from han_codebook.core import CaseError, load_case
from han_codebook.model_settings import model_settings, save_model_settings

ROOT = Path(__file__).resolve().parents[1]
MODEL = "deepseek-ai/DeepSeek-V4-Flash-0731"


class FakeResponse:
    def __init__(self, content):
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, _limit):
        return self.content


class FakeSocket:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FakeOpener:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def open(self, req, timeout):
        self.calls.append((req, timeout))
        return FakeResponse(self.content)


class DeepInfraTests(unittest.TestCase):
    def test_exact_https_host_and_explicit_opt_in(self):
        with self.assertRaises(CaseError):
            validate_llm_endpoint(DEEPINFRA_BASE_URL, provider="deepinfra")
        validate_llm_endpoint(DEEPINFRA_BASE_URL, provider="deepinfra",
                              allow_external_api=True)
        validate_llm_endpoint(DEEPINFRA_BASE_URL + "/", provider="deepinfra",
                              allow_external_api=True)
        for url in (
            "http://api.deepinfra.com/v1/openai",
            "https://api.deepinfra.com.evil.test/v1/openai",
            "https://deepinfra.com/v1/openai",
            "https://api.deepinfra.com:8443/v1/openai",
            "https://api.deepinfra.com/v1/openai/elsewhere",
            "https://api.deepinfra.com/v1/openai?token=secret",
            "https://user:pass@api.deepinfra.com/v1/openai",
            "https://api.deepinfra.com/v1/openai#fragment",
            "https://api.deepinfra.com/v1%2fopenai",
        ):
            with self.subTest(url=url), self.assertRaises(CaseError):
                validate_llm_endpoint(url, provider="deepinfra",
                                      allow_external_api=True)
        with self.assertRaises(CaseError):
            validate_llm_endpoint(DEEPINFRA_BASE_URL, provider="local",
                                  allow_external_api=True)
        with self.assertRaises(CaseError):
            validate_llm_endpoint(DEEPINFRA_BASE_URL, provider="unknown",
                                  allow_external_api=True)

    def test_no_paid_request_without_opt_in_or_environment_token(self):
        with patch("han_codebook.agent.request.build_opener") as opener:
            with self.assertRaises(CaseError):
                query_local_llm(DEEPINFRA_BASE_URL, MODEL, {"secret": "no send"},
                                provider="deepinfra", allow_external_api=False)
            opener.assert_not_called()
            with patch.dict(os.environ, {"DEEPINFRA_API_KEY": ""}):
                with self.assertRaises(CaseError):
                    query_local_llm(DEEPINFRA_BASE_URL, MODEL, {"secret": "no send"},
                                    provider="deepinfra", allow_external_api=True)
            opener.assert_not_called()

    def test_chat_uses_fixed_deepinfra_path_bearer_and_no_redirects(self):
        fake = FakeOpener(json.dumps({
            "choices": [{"message": {"content": '{"hypotheses":[]}'}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 6},
        }).encode())
        with patch.dict(os.environ, {"DEEPINFRA_API_KEY": "SYNTHETIC_TEST_SECRET"}):
            with patch("han_codebook.agent.request.build_opener", return_value=fake) as build, \
                 patch("han_codebook.agent.request.urlopen") as local:
                result = query_local_llm(
                    DEEPINFRA_BASE_URL, MODEL, {"task": "code", "codes": ["001"]},
                    provider="deepinfra", allow_external_api=True,
                    reasoning_effort="none", response_format="json_object")
                local.assert_not_called()
        self.assertEqual(result, {"hypotheses": []})
        handler = build.call_args.args[0]
        self.assertIsInstance(handler, _RejectRedirects)
        self.assertIsNone(handler.redirect_request(None, None, 302, "Moved", {},
                                                   "https://attacker.example/"))
        req, timeout = fake.calls[0]
        self.assertEqual(timeout, 90)
        self.assertEqual(req.full_url, DEEPINFRA_BASE_URL + "/chat/completions")
        self.assertEqual(req.get_header("Authorization"), "Bearer SYNTHETIC_TEST_SECRET")
        body = json.loads(req.data.decode("utf-8"))
        self.assertEqual(body["model"], MODEL)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertNotIn("reasoning_effort", body)
        self.assertEqual(body["max_tokens"], 8192)
        self.assertNotIn("SYNTHETIC_TEST_SECRET", req.data.decode())

    def test_models_probe_is_metadata_only_and_uses_official_route(self):
        fake = FakeOpener(b'{"data":[{"id":"deepseek-ai/DeepSeek-V4-Flash-0731"}]}')
        diagnostics = []
        with patch.dict(os.environ, {"DEEPINFRA_API_KEY": "SYNTHETIC_TEST_SECRET"}):
            with patch("han_codebook.agent.socket.create_connection", return_value=FakeSocket()) as tcp, \
                 patch("han_codebook.agent.request.build_opener", return_value=fake) as build:
                self.assertTrue(probe_llm_service(
                    DEEPINFRA_BASE_URL, provider="deepinfra",
                    allow_external_api=True, report=diagnostics.append))
        self.assertEqual(tcp.call_args.args[0], ("api.deepinfra.com", 443))
        self.assertIsInstance(build.call_args.args[0], _RejectRedirects)
        req, _timeout = fake.calls[0]
        self.assertEqual(req.full_url, DEEPINFRA_BASE_URL + "/models")
        self.assertIsNone(req.data)
        self.assertEqual(req.get_header("Authorization"), "Bearer SYNTHETIC_TEST_SECRET")
        self.assertTrue(any("models" in row for row in diagnostics))
        self.assertNotIn("SYNTHETIC_TEST_SECRET", "\n".join(diagnostics))

    def test_model_settings_never_save_plaintext_key_or_arbitrary_host(self):
        with TemporaryDirectory() as folder:
            cfg = Path(folder) / "config.yaml"
            cfg.write_text("project: {}\nanalysis: {}\nllm:\n  "
                           "base_url: http://127.0.0.1:11434\n"
                           "  model: qwen3:14b\n  reasoning_effort: none\n",
                           encoding="utf-8")
            raw = {"provider": "deepinfra", "allow_external_api": True,
                   "base_url": DEEPINFRA_BASE_URL, "model": MODEL,
                   "timeout_seconds": 90, "allow_private_network": False,
                   "api_key_env": "DEEPINFRA_API_KEY"}
            for invalid in (
                {**raw, "allow_external_api": False},
                {**raw, "base_url": "https://api.deepinfra.com.evil.test/v1/openai"},
                {**raw, "allow_private_network": True},
                {**raw, "api_key_env": "literal-secret:do-not-save"},
            ):
                original = cfg.read_bytes()
                with self.assertRaises(CaseError):
                    save_model_settings(cfg, invalid)
                self.assertEqual(cfg.read_bytes(), original)
            with patch.dict(os.environ, {"DEEPINFRA_API_KEY": "SYNTHETIC_TEST_SECRET"}):
                published = save_model_settings(cfg, raw)
            saved = load_settings(cfg)["llm"]
            self.assertEqual(published["provider"], "deepinfra")
            self.assertTrue(published["allow_external_api"])
            self.assertEqual(saved["api_key_env"], "DEEPINFRA_API_KEY")
            self.assertNotIn("reasoning_effort", saved)
            self.assertFalse(published["secret_value_exposed"])
            self.assertNotIn("SYNTHETIC_TEST_SECRET", cfg.read_text(encoding="utf-8"))
            self.assertNotIn("SYNTHETIC_TEST_SECRET", json.dumps(model_settings(cfg)))
            local = save_model_settings(cfg, {
                "provider": "local", "allow_external_api": False,
                "base_url": "http://127.0.0.1:11434", "model": "qwen3:14b",
                "timeout_seconds": 90, "allow_private_network": False, "api_key_env": ""})
            self.assertEqual(local["provider"], "local")
            self.assertFalse(local["allow_external_api"])

    def test_old_local_configs_remain_unchanged(self):
        local = load_settings(ROOT / "config.yaml")["llm"]
        self.assertEqual(local.get("provider", "local"), "local")
        self.assertFalse(local.get("allow_external_api", False))
        self.assertEqual(llm_api_base("http://127.0.0.1:11434"), "http://127.0.0.1:11434/v1")
        self.assertEqual(llm_api_base(DEEPINFRA_BASE_URL, "deepinfra"), DEEPINFRA_BASE_URL)
        sample = load_settings(ROOT / "config.deepinfra.example.yaml")["llm"]
        self.assertEqual(sample["provider"], "deepinfra")
        self.assertFalse(sample["allow_external_api"])

    def test_agent_routes_to_deepinfra_only_when_explicitly_enabled(self):
        case = load_case(ROOT / "examples/demo_case.json")
        seen = []

        def fake(_url, _model, _evidence, **kwargs):
            seen.append(kwargs)
            return {"hypotheses": []}

        with TemporaryDirectory() as folder:
            with patch.dict(os.environ, {"DEEPINFRA_API_KEY": "SYNTHETIC_TEST_SECRET"}):
                with patch("han_codebook.agent.query_local_llm", side_effect=fake):
                    result = run_agent(
                        case, rounds=1, llm_url=DEEPINFRA_BASE_URL,
                        llm_provider="deepinfra", llm_allow_external_api=True,
                        model=MODEL, db_path=str(Path(folder) / "audit.sqlite"),
                        solver_iterations=1, solver_restarts=1)
            self.assertEqual(result["agent_rounds_completed"], 1)
        self.assertTrue(seen)
        self.assertEqual(seen[0]["provider"], "deepinfra")
        self.assertTrue(seen[0]["allow_external_api"])
        with TemporaryDirectory() as folder:
            with patch("han_codebook.agent.query_local_llm") as fake:
                with self.assertRaises(CaseError):
                    run_agent(case, rounds=1, llm_url=DEEPINFRA_BASE_URL,
                              llm_provider="deepinfra", llm_allow_external_api=False,
                              db_path=str(Path(folder) / "audit.sqlite"))
                fake.assert_not_called()



    def test_cli_explicit_provider_override_does_not_reuse_lan_token(self):
        with patch("han_codebook.cli.probe_llm_service", return_value=True) as probe:
            self.assertEqual(cli_main([
                "--config", str(ROOT / "config.yaml"),
                "--provider", "deepinfra", "--allow-external-api",
                "--model", MODEL, "--check-llm",
            ]), 0)
        options = probe.call_args.kwargs
        self.assertEqual(options["provider"], "deepinfra")
        self.assertEqual(options["api_key_env"], "DEEPINFRA_API_KEY")
        self.assertTrue(options["allow_external_api"])
        self.assertEqual(probe.call_args.args[0], DEEPINFRA_BASE_URL)

    def test_retry_only_on_length_and_count_both_paid_requests(self):
        class QueueOpener:
            def __init__(self, bodies):
                self.bodies = list(bodies)
                self.calls = []
            def open(self, req, timeout):
                self.calls.append(json.loads(req.data.decode("utf-8")))
                return FakeResponse(self.bodies.pop(0))
        def response(finish, content, tokens):
            return json.dumps({"choices":[{"finish_reason":finish,
                                            "message":{"content":content}}],
                               "usage":{"prompt_tokens":100,
                                        "completion_tokens":tokens,
                                        "total_tokens":100+tokens}}).encode()
        first = response("length", '{"hypotheses":[]}', 8192)
        second = response("stop", '{"hypotheses":[]}', 128)
        opener = QueueOpener([first, second])
        measured = []
        with patch.dict(os.environ, {"DEEPINFRA_API_KEY": "SYNTHETIC_TEST_SECRET"}), \
             patch("han_codebook.agent.request.build_opener", return_value=opener):
            result = query_local_llm(
                DEEPINFRA_BASE_URL, MODEL, {"codes": ["001"]},
                provider="deepinfra", allow_external_api=True,
                max_output_tokens=8192, on_metrics=measured.append)
        self.assertEqual(result, {"hypotheses":[]})
        self.assertEqual([b["max_tokens"] for b in opener.calls], [8192,16384])
        self.assertEqual([m["json_complete"] for m in measured], [False, True])
        self.assertEqual([m["finish_reason"] for m in measured], ["length","stop"])
        from han_codebook.agent import summarize_llm_api_metrics
        summary = summarize_llm_api_metrics(measured)
        self.assertEqual(summary["attempts"], 2)
        self.assertEqual(summary["retries"], 1)
        self.assertEqual(summary["finish_reason_length_count"], 1)
        self.assertEqual(summary["json_completeness_rate"], 0.5)
        self.assertEqual(summary["total_tokens_reported"], 200+8192+128)

    def test_at_hard_cap_truncation_never_returns_partial_json_or_retries(self):
        class OneRequest:
            def __init__(self):
                self.requests = []
            def open(self, req, timeout):
                self.requests.append(json.loads(req.data.decode()))
                return FakeResponse(json.dumps({
                    "choices": [{"finish_reason": "length",
                                 "message": {"content": '{"hypotheses":[]}'}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 16384,
                              "total_tokens": 16394},
                }).encode())
        opener = OneRequest()
        metrics = []
        with patch.dict(os.environ, {"DEEPINFRA_API_KEY": "SYNTHETIC_TEST_SECRET"}), \
             patch("han_codebook.agent.request.build_opener", return_value=opener):
            with self.assertRaisesRegex(CaseError, "finish_reason=length"):
                query_local_llm(DEEPINFRA_BASE_URL, MODEL, {"codes": ["001"]},
                                provider="deepinfra", allow_external_api=True,
                                max_output_tokens=16384, on_metrics=metrics.append)
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(metrics[0]["status"], "truncated")
        self.assertFalse(metrics[0]["json_complete"])

    def test_invalid_json_without_length_never_retries(self):
        class OneRequest:
            def __init__(self): self.count = 0
            def open(self, req, timeout):
                self.count += 1
                return FakeResponse(json.dumps({
                    "choices": [{"finish_reason": "stop",
                                 "message": {"content": '{"hypotheses":['}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 9,
                              "total_tokens": 19},
                }).encode())
        opener = OneRequest()
        metrics = []
        with patch.dict(os.environ, {"DEEPINFRA_API_KEY": "SYNTHETIC_TEST_SECRET"}), \
             patch("han_codebook.agent.request.build_opener", return_value=opener):
            with self.assertRaisesRegex(CaseError, "not valid expected JSON"):
                query_local_llm(DEEPINFRA_BASE_URL, MODEL, {"codes": ["001"]},
                                provider="deepinfra", allow_external_api=True,
                                max_output_tokens=8192, on_metrics=metrics.append)
        self.assertEqual(opener.count, 1)
        self.assertEqual(metrics[0]["status"], "invalid_json")
        self.assertFalse(metrics[0]["json_complete"])

    def test_token_boundaries_and_settings_confirmation_receipt(self):
        from han_codebook.agent import validate_max_output_tokens
        for value in (-1, 0, 1023, 16385, 8192.0, True, "8192"):
            with self.subTest(value=value), self.assertRaises(CaseError):
                validate_max_output_tokens(value)
        self.assertEqual(validate_max_output_tokens(1024), 1024)
        self.assertEqual(validate_max_output_tokens(16384), 16384)
        with TemporaryDirectory() as folder:
            cfg = Path(folder) / "config.yaml"
            cfg.write_text("llm:\n  base_url: http://127.0.0.1:11434\n"
                           "  model: qwen3:14b\n", encoding="utf-8")
            deep={"provider": "deepinfra", "allow_external_api": True,
                  "base_url": DEEPINFRA_BASE_URL, "model": MODEL,
                  "timeout_seconds": 90, "allow_private_network": False,
                  "api_key_env": "DEEPINFRA_API_KEY", "max_output_tokens": 8192}
            initial=save_model_settings(cfg, deep)
            before=cfg.read_bytes()
            for bad in (0, True, 16385, 8192.5):
                with self.assertRaises(CaseError):
                    save_model_settings(cfg, {**deep, "max_output_tokens": bad})
                self.assertEqual(cfg.read_bytes(), before)
            updated=save_model_settings(cfg, {**deep, "max_output_tokens": 16384})
            self.assertNotEqual(initial["confirmation_token"], updated["confirmation_token"])
            self.assertEqual(load_settings(cfg)["llm"]["max_output_tokens"], 16384)
            local=save_model_settings(cfg, {
                "provider":"local", "allow_external_api":False,
                "base_url":"http://127.0.0.1:11434", "model":"qwen3:14b",
                "timeout_seconds":90, "allow_private_network":False,
                "api_key_env":""})
            self.assertEqual(local["provider"], "local")
            self.assertNotIn("max_output_tokens", load_settings(cfg)["llm"])

    def test_safe_metrics_summary_never_includes_prompt_or_result(self):
        from han_codebook.agent import summarize_llm_api_metrics
        rows=[{"attempt":1, "finish_reason":"stop", "json_complete":True,
               "prompt_tokens":20, "completion_tokens":10, "total_tokens":30,
               "estimated_cost":0.001, "private":"secret-research-packet"}]
        summary=summarize_llm_api_metrics(rows)
        self.assertEqual(summary["json_completeness_rate"], 1.0)
        self.assertEqual(summary["total_tokens_reported"], 30)
        self.assertNotIn("secret-research-packet", json.dumps(summary))
        self.assertIsNone(summarize_llm_api_metrics([])["json_completeness_rate"])


if __name__ == "__main__":
    unittest.main()
