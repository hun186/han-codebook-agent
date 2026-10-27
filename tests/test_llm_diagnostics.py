"""Network diagnostics and visible CLI progress are testable entirely offline."""
from __future__ import annotations

import io
import json
import socket
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib import error

from han_codebook.agent import probe_llm_service, query_local_llm, run_agent
from han_codebook.cli import main
from han_codebook.core import CaseError, load_case

ROOT = Path(__file__).resolve().parents[1]
LAN = "http://192.168.0.134:18080"
OPTIONS = {"allow_private_network": True, "allowed_hosts": ["192.168.0.134"]}


class FakeSocket:
    def __enter__(self): return self
    def __exit__(self, *args): return False


class FakeResponse:
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, size): return self.body


class LLMCheckTests(unittest.TestCase):
    def test_models_probe_success(self):
        messages = []
        fake_json = json.dumps({"data": [{"id": "qwen3.6:latest-128k"}]}).encode()
        with patch('han_codebook.agent.socket.create_connection', return_value=FakeSocket()) as dial, \
             patch('han_codebook.agent.request.urlopen', return_value=FakeResponse(fake_json)) as urlopen:
            ok = probe_llm_service(LAN, report=messages.append, **OPTIONS)
        self.assertTrue(ok)
        self.assertEqual(dial.call_args.args[0], ("192.168.0.134", 18080))
        self.assertEqual(urlopen.call_args.args[0].full_url, LAN + '/v1/models')
        self.assertTrue(any('[OK] /v1/models' in m for m in messages))

    def test_refused_tcp_fails_quickly(self):
        messages = []
        with patch('han_codebook.agent.socket.create_connection', side_effect=OSError('refused')), \
             patch('han_codebook.agent.request.urlopen') as urlopen:
            self.assertFalse(probe_llm_service(LAN, report=messages.append, **OPTIONS))
            urlopen.assert_not_called()
        self.assertTrue(any('[ERROR] TCP' in m for m in messages))

    def test_web_ui_html_is_error(self):
        with patch('han_codebook.agent.socket.create_connection', return_value=FakeSocket()), \
             patch('han_codebook.agent.request.urlopen', return_value=FakeResponse(b'<html><title>Login</title></html>')):
            self.assertFalse(probe_llm_service(LAN, report=lambda _: None, **OPTIONS))

    def test_404_models_is_only_warning(self):
        with patch('han_codebook.agent.socket.create_connection', return_value=FakeSocket()), \
             patch('han_codebook.agent.request.urlopen', side_effect=error.HTTPError(LAN, 404, 'Not Found', {}, None)):
            self.assertTrue(probe_llm_service(LAN, report=lambda _: None, **OPTIONS))

    def test_401_models_fails(self):
        with patch('han_codebook.agent.socket.create_connection', return_value=FakeSocket()), \
             patch('han_codebook.agent.request.urlopen', side_effect=error.HTTPError(LAN, 401, 'Unauthorized', {}, None)):
            self.assertFalse(probe_llm_service(LAN, report=lambda _: None, **OPTIONS))

    def test_chat_404_reports_endpoint_not_found(self):
        with patch('han_codebook.agent.request.urlopen', side_effect=error.HTTPError(LAN, 404, 'Not Found', {}, None)):
            with self.assertRaisesRegex(CaseError, 'LLM HTTP 404.*chat/completions'):
                query_local_llm(LAN, 'qwen3.6:latest-128k', {}, **OPTIONS)

    def test_chat_html_reports_wrong_api(self):
        with patch('han_codebook.agent.request.urlopen', return_value=FakeResponse(b'<!DOCTYPE html><html></html>')):
            with self.assertRaisesRegex(CaseError, 'HTML returned instead of JSON'):
                query_local_llm(LAN, 'qwen3.6:latest-128k', {}, **OPTIONS)

    def test_check_llm_cli_without_case_loading(self):
        stream = io.StringIO()
        with patch('han_codebook.cli.probe_llm_service', return_value=True) as probe, redirect_stdout(stream):
            self.assertEqual(main(['--config', str(ROOT / 'config.yaml'), '--check-llm']), 0)
        self.assertTrue(probe.called)
        self.assertIn('Note: TCP/models checks do not validate actual chat inference', stream.getvalue())

    def test_run_agent_emits_progress_with_mock_llm(self):
        event_lines = []
        with TemporaryDirectory() as tdir:
            case = load_case(ROOT / 'examples/demo_case.json')
            with patch('han_codebook.agent.query_local_llm', return_value={'hypotheses': []}):
                result = run_agent(case, rounds=1, db_path=str(Path(tdir) / 'audit.sqlite'),
                                   llm_url=LAN, progress=event_lines.append, **{
                                       'allow_private_network': True, 'llm_allowed_hosts': ['192.168.0.134']})
        self.assertEqual(result['agent_rounds_completed'], 1)
        self.assertTrue(any('Round 1/1: requesting' in m for m in event_lines))
        self.assertTrue(any('response received' in m for m in event_lines))
        self.assertTrue(any('reranking' in m for m in event_lines))


if __name__ == '__main__': unittest.main()
