"""Codex PR #3 P2 regression cases: failed-job traces, atomic edits, audit, worker cleanup."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import threading
import time
import unittest
from tempfile import TemporaryDirectory
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib import error, request
from io import BytesIO

from han_codebook.agent import query_local_llm, create_audit, log_event
from han_codebook.core import CaseError
from han_codebook.web import create_handler

ROOT = Path(__file__).resolve().parents[1]


class LLMFailedResponseAuditTests(unittest.TestCase):
    def test_http_error_response_capture_is_bounded_and_opt_in(self):
        for code in (400, 422):
            for capture in (False, True):
                with self.subTest(code=code,capture=capture):
                    seen=[]
                    failure=error.HTTPError('http://127.0.0.1:11434/v1/chat/completions', code,
                                            'too long', {}, BytesIO(b'context length exceeded'+b'x'*100000))
                    with patch('han_codebook.agent.request.urlopen',side_effect=failure):
                        with self.assertRaisesRegex(CaseError,f'LLM HTTP {code}'):
                            query_local_llm('http://127.0.0.1:11434','mock',{},
                                            on_exchange=(lambda stage,payload: seen.append((stage,payload))) if capture else None)
                    self.assertEqual([s for s,_ in seen], ['llm_request','llm_response'] if capture else [])
                    if capture:
                        body=seen[-1][1]
                        self.assertEqual(body['http_status'],code)
                        self.assertTrue(body['response'].startswith('context length exceeded'))
                        self.assertLessEqual(len(body['response'].encode()),64_000)
                        self.assertTrue(body['response_truncated'])
                        self.assertNotIn('Authorization',str(body))

    def test_http_error_without_body_is_still_logged(self):
        seen=[]
        failure=error.HTTPError('http://127.0.0.1:11434/v1/chat/completions', 502, 'bad gateway',{},None)
        with patch('han_codebook.agent.request.urlopen',side_effect=failure):
            with self.assertRaisesRegex(CaseError,'LLM HTTP 502'):
                query_local_llm('http://127.0.0.1:11434','mock',{},on_exchange=lambda stage,payload:seen.append((stage,payload)))
        self.assertEqual(seen[-1][1]['response'],'')


class BackgroundJobFailureTests(unittest.TestCase):
    def run_server(self, root):
        (root/'examples').mkdir(exist_ok=True)
        (root/'examples'/'case.json').write_text((ROOT/'benchmarks/cases/07_alias_mixed_length.json').read_text(encoding='utf-8'),encoding='utf-8')
        (root/'config.yaml').write_text('project: {}\nanalysis: {}\nllm:\n  base_url: http://127.0.0.1:11434\n  model: test\n')
        server=ThreadingHTTPServer(('127.0.0.1',0),create_handler(root,root/'config.yaml'))
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        return server,thread,f'http://127.0.0.1:{server.server_port}'

    def post(self, base, case):
        req=request.Request(base+'/api/start',data=json.dumps({'case':case,'rounds':0}).encode(),
                            headers={'Content-Type':'application/json','X-Han-UI':'local'},method='POST')
        return json.load(request.urlopen(req))['job_id']

    def get(self,base,job):
        for _ in range(70):
            result=json.load(request.urlopen(base+'/api/jobs/'+job))
            if result['status'] in ('failed','completed'):return result
            time.sleep(.04)
        self.fail('Job stuck in queued/running state')

    def test_unwritable_output_dir_fails_and_unblocks_next_request(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'artifacts').mkdir()
            (root/'artifacts'/'web_runs').write_text('path collision')
            srv,thread,base=self.run_server(root)
            try:
                case=json.load(request.urlopen(base+'/api/case?id=examples%2Fcase.json'))
                job=self.post(base,case)
                result=self.get(base,job)
                self.assertEqual(result['status'],'failed')
                self.assertIn('NotADirectoryError',result['error'])
                # No indefinite queued job, next request must not return 409.
                second=self.post(base,case)
                self.assertEqual(self.get(base,second)['status'],'failed')
            finally:
                srv.shutdown();srv.server_close();thread.join(timeout=2)

    def test_failed_job_returns_saved_timeline(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            srv,thread,base=self.run_server(root)
            try:
                case=json.load(request.urlopen(base+'/api/case?id=examples%2Fcase.json'))
                def failed_run(_input,*,db_path,**_kwargs):
                    with create_audit(db_path) as audit:
                        log_event(audit,0,'statistical_baseline',{'score':5})
                        log_event(audit,1,'llm_request',{'body':{'model':'fake'}})
                        log_event(audit,1,'llm_response',{'http_status':400,'response':'context length exceeded','elapsed_ms':13})
                    raise CaseError('LLM HTTP 400')
                with patch('han_codebook.web.run_agent',side_effect=failed_run):
                    result=self.get(base,self.post(base,case))
                self.assertEqual(result['status'],'failed')
                self.assertEqual([x['stage'] for x in result['events']],['statistical_baseline','llm_request','llm_response'])
                self.assertIsNone(result['result'])
            finally:
                srv.shutdown();srv.server_close();thread.join(timeout=2)


@unittest.skipUnless(shutil.which('node'), 'Node.js required for browser JS regression tests')
class BrowserDOMRegressionTests(unittest.TestCase):
    def test_atomic_evidence_update_and_failed_job_trace(self):
        p=subprocess.run([shutil.which('node'),str(ROOT/'tests/js/test_ui_review.js'),
                          str(ROOT/'src/han_codebook/static/index.html')],capture_output=True,text=True,timeout=10)
        self.assertEqual(p.returncode,0,p.stderr+p.stdout)
        self.assertIn('passed',p.stdout)


if __name__ == '__main__':unittest.main()
