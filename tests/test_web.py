"""Local browser workflow + evidence and LLM-provenance regression tests."""
from __future__ import annotations

import copy
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from urllib import request, error
from unittest.mock import patch

from han_codebook.agent import run_agent
from han_codebook.core import CaseError, domain_for_message, load_case
from han_codebook.web import create_handler, list_cases

ROOT = Path(__file__).resolve().parents[1]


class ContextEvidenceTests(unittest.TestCase):
    def test_observation_affects_prior_only_when_metadata_enabled(self):
        case = load_case(ROOT/'examples/demo_case.json')
        message = {'id':'extra','codes':['007'],'observations':[
            {'source':'第三方目擊','activity':'補給車隊','destination':'糧食倉庫',
             'confidence':0.8, 'note':'運輸途中'}]}
        self.assertEqual(domain_for_message(message, case['profiles'], True), 'logistics')
        self.assertIsNone(domain_for_message(message, case['profiles'], False))
        case['messages'].append(message)
        from han_codebook.core import validate_case
        validate_case(case)
        message['observations'][0]['confidence'] = 2
        with self.assertRaisesRegex(CaseError, 'confidence'):
            validate_case(case)

    def test_exact_request_and_response_audited_only_with_opt_in(self):
        case = load_case(ROOT/'benchmarks/cases/07_alias_mixed_length.json')
        fake = {"choices":[{"message":{"content":json.dumps({"hypotheses": [{"code":"123","candidates":["兵力"],"reason":"test"}]},ensure_ascii=False)}}]}
        class Response:
            def __enter__(self): return self
            def __exit__(self,*_): return False
            def read(self,size): return json.dumps(fake,ensure_ascii=False).encode()
        with TemporaryDirectory() as temp, patch('han_codebook.agent.request.urlopen', return_value=Response()):
            db = Path(temp)/'audit.sqlite'
            output=run_agent(case,rounds=1,db_path=db,llm_url='http://127.0.0.1:11434',
                             model='mock',capture_llm_io=True)
            from han_codebook.web import audit_timeline
            events=audit_timeline(db)
            req=[e for e in events if e['stage']=='llm_request']
            reply=[e for e in events if e['stage']=='llm_response']
            self.assertEqual((len(req),len(reply)),(1,1))
            self.assertNotIn('ground_truth',json.dumps(req[0]))
            self.assertEqual(req[0]['payload']['body']['model'],'mock')
            self.assertIn('choices',reply[0]['payload']['response'])
            self.assertTrue(any(e['stage']=='rescore' and 'changes' in e['payload'] for e in events))
            self.assertEqual(output['agent_rounds_completed'],1)
        with TemporaryDirectory() as temp, patch('han_codebook.agent.request.urlopen', return_value=Response()):
            db=Path(temp)/'audit.sqlite'
            run_agent(case,rounds=1,db_path=db,llm_url='http://127.0.0.1:11434',model='mock')
            from han_codebook.web import audit_timeline
            stages=[e['stage'] for e in audit_timeline(db)]
            self.assertNotIn('llm_request',stages)
            self.assertNotIn('llm_response',stages)


class UIHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=TemporaryDirectory()
        base=Path(cls.temp.name)
        (base/'examples').mkdir()
        (base/'src').mkdir()
        (base/'examples'/'case.json').write_text((ROOT/'benchmarks/cases/07_alias_mixed_length.json').read_text(encoding='utf-8'),encoding='utf-8')
        (base/'config.yaml').write_text('project: {}\nanalysis: {}\nllm:\n  base_url: http://127.0.0.1:11434\n  model: test\n',encoding='utf-8')
        cls.root=base
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),create_handler(base,base/'config.yaml'))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join(timeout=2);cls.temp.cleanup()

    def get(self,path):
        return json.loads(request.urlopen(self.base+path).read())

    def post(self,path,data,origin=None):
        req=request.Request(self.base+path,data=json.dumps(data,ensure_ascii=False).encode(),
                            headers={'Content-Type':'application/json','X-Han-UI':'local',
                                     'Origin':origin or self.base},method='POST')
        return json.loads(request.urlopen(req).read())

    def test_serve_html_case_list_and_no_gold(self):
        html=request.urlopen(self.base).read().decode()
        self.assertIn('逐輪分析／Prompt',html)
        self.assertIn('第三方',html)
        self.assertIn('examples/case.json',str(self.get('/api/cases')))
        case=self.get('/api/case?id=examples%2Fcase.json')
        self.assertNotIn('ground_truth',case)

    def test_save_case_and_reject_gold(self):
        case=self.get('/api/case?id=examples%2Fcase.json')
        path=self.post('/api/save',{'case':case,'name':'test_case'})['saved_as']
        self.assertEqual(path,'artifacts/ui_cases/test_case.json')
        case['ground_truth']={'a':'b'}
        with self.assertRaises(error.HTTPError) as context:
            self.post('/api/save',{'case':case,'name':'must_fail'})
        self.assertEqual(context.exception.code,400)

    def test_csrf_and_restrict_unknown_files(self):
        self.assertEqual(self.get('/api/cases')[0]['id'],'examples/case.json')
        req=request.Request(self.base+'/api/start',data=b'{}',headers={'Origin':'http://evil.test'},method='POST')
        with self.assertRaises(error.HTTPError) as err:
            request.urlopen(req)
        self.assertEqual(err.exception.code,403)
        with self.assertRaises(error.HTTPError) as err:
            request.urlopen(self.base+'/api/case?id=../../config.yaml')
        self.assertEqual(err.exception.code,404)

    def test_async_offline_run_and_progress(self):
        case=self.get('/api/case?id=examples%2Fcase.json')
        job=self.post('/api/start',{'case':case,'rounds':0,'use_metadata':True})['job_id']
        for _ in range(100):
            data=self.get('/api/jobs/'+job)
            if data['status'] in ('completed','failed'):
                break
            time.sleep(.1)
        self.assertEqual(data['status'],'completed',data['error'])
        self.assertEqual(data['result']['agent_rounds_completed'],0)
        self.assertTrue(any(e['stage']=='statistical_baseline' for e in data['events']))


if __name__=='__main__':unittest.main()

class MetadataAblationTests(unittest.TestCase):
    def test_llm_packet_excludes_send_receive_and_observations_when_disabled(self):
        case=load_case(ROOT/'benchmarks/cases/08_long_dispatch_with_observations.json')
        packet=[]
        def fake_llm(_url,_model,evidence,**_kwargs):
            packet.append(evidence)
            return {'hypotheses':[]}
        with TemporaryDirectory() as temp, patch('han_codebook.agent.query_local_llm',side_effect=fake_llm):
            run_agent(case,rounds=1,metadata=False,db_path=Path(temp)/'a.sqlite',
                      llm_url='http://127.0.0.1:11434',solver_iterations=2,solver_restarts=1)
        self.assertTrue(packet)
        self.assertTrue(all(set(x)=={'id','codes'} for x in packet[0]['messages']))
