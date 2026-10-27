"""Configuration and network boundaries must be reproducible without an LLM server."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from io import BytesIO

from han_codebook.agent import query_local_llm, validate_llm_endpoint
from han_codebook.config import load_settings
from han_codebook.core import CaseError
from han_codebook.cli import main

BASE = Path(__file__).resolve().parents[1]


class YAMLConfigTests(unittest.TestCase):
    def test_repo_config_uses_supplied_endpoint(self):
        cfg = load_settings(BASE / "config.yaml")
        self.assertEqual(cfg["llm"]["base_url"], "http://192.168.0.134:18080")
        self.assertEqual(cfg["llm"]["allowed_hosts"], ["192.168.0.134"])
        self.assertTrue(cfg["llm"]["allow_private_network"])
        self.assertEqual(cfg["project"]["case"], str((BASE / "examples/demo_case.json").resolve()))

    def test_offline_config_cli_with_cli_override(self):
        with TemporaryDirectory() as td:
            dest = Path(td)
            output = dest / "result.json"
            audit = dest / "audit.sqlite"
            code = main(["--config", str(BASE / "config.offline.yaml"), "--out", str(output),
                         "--db", str(audit), "--no-metadata"])
            self.assertEqual(code, 0)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["agent_rounds_completed"], 0)
            self.assertEqual(result["metadata_used"], False)
            self.assertIn("evaluation", result)

    def test_invalid_key_fails_closed(self):
        with TemporaryDirectory() as td:
            config = Path(td) / "config.yaml"
            config.write_text("llm:\n  base_url: http://127.0.0.1:11434\n  secret_bad_key: blah\n")
            with self.assertRaisesRegex(CaseError, "Unknown config keys"):
                load_settings(config)

    def test_bad_types_fail_closed(self):
        with TemporaryDirectory() as td:
            config = Path(td) / "config.yaml"
            config.write_text("analysis:\n  rounds: 'two'\n")
            with self.assertRaisesRegex(CaseError, "must be int"):
                load_settings(config)

    def test_yaml_does_not_allow_arbitrary_object_execution(self):
        with TemporaryDirectory() as td:
            config = Path(td) / "config.yaml"
            config.write_text('!!python/object/apply:os.system ["echo SHOULD_NOT_RUN"]')
            with self.assertRaises(CaseError):
                load_settings(config)


class LLMSecurityTests(unittest.TestCase):
    def test_lan_ip_rejected_without_explicit_config(self):
        with self.assertRaises(CaseError):
            validate_llm_endpoint("http://192.168.0.134:18080")
        with self.assertRaises(CaseError):
            validate_llm_endpoint("http://192.168.0.134:18080", allow_private_network=True,
                                  allowed_hosts=["192.168.0.1"])

    def test_lan_ip_allowed_with_exact_allowlist(self):
        validate_llm_endpoint("http://192.168.0.134:18080", allow_private_network=True,
                              allowed_hosts=["192.168.0.134"])

    def test_public_ip_dns_credentials_forbidden(self):
        endpoints = ["http://8.8.8.8/v1", "https://example.com/v1",
                     "http://user:password@192.168.0.134:18080/v1",
                     "http://192.168.0.134:18080/v1?key=123", "http://169.254.169.254/v1"]
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(CaseError):
                    validate_llm_endpoint(endpoint, allow_private_network=True,
                                          allowed_hosts=["192.168.0.134", "8.8.8.8"])

    def test_lan_api_request_uses_v1_chat_completions(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *_):
                return False
            def read(self, limit):
                result = {"choices": [{"message": {"content": '{"hypotheses": []}'}}]}
                return json.dumps(result).encode("utf-8")

        seen = []
        def mock_open(req, timeout):
            seen.append(req)
            self.assertEqual(timeout, 90)
            return Response()

        with patch("han_codebook.agent.request.urlopen", side_effect=mock_open):
            result = query_local_llm("http://192.168.0.134:18080", "test-model", {"code": "001"},
                                     allow_private_network=True, allowed_hosts=["192.168.0.134"])
        self.assertEqual(result, {"hypotheses": []})
        self.assertEqual(seen[0].full_url, "http://192.168.0.134:18080/v1/chat/completions")
        self.assertIn(b'"test-model"', seen[0].data)


if __name__ == "__main__":
    unittest.main()
