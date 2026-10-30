"""Regression and leakage checks for the fictional multi-scenario evaluation harness."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from han_codebook.benchmark import main, run_suite, score_result
from han_codebook.core import analyze, load_case, CaseError

ROOT=Path(__file__).resolve().parents[1]
BENCH=ROOT/'benchmarks'


class BenchmarkTests(unittest.TestCase):
    def test_benchmark_fixtures_golds_are_separate_and_reproducible(self):
        suite=json.loads((BENCH/'suite.json').read_text(encoding='utf-8'))
        self.assertEqual(len(suite['cases']),8)
        from importlib.util import spec_from_file_location, module_from_spec
        spec=spec_from_file_location('benchmark_builder',BENCH/'build_cases.py')
        module=module_from_spec(spec)
        spec.loader.exec_module(module)
        for entry in suite['cases']:
            case_path=BENCH/entry['case']
            gold_path=BENCH/entry['gold']
            self.assertNotEqual(case_path,gold_path)
            case=load_case(case_path)
            self.assertNotIn('ground_truth',case)
            self.assertEqual(case['case_id'],entry['id'])
            gold=json.loads(gold_path.read_text(encoding='utf-8'))
            self.assertEqual(gold['case_id'],entry['id'])
            self.assertEqual(set(gold['codebook']),{code for m in case['messages'] for code in m['codes']})
            self.assertEqual(set(gold['messages']),{m['id'] for m in case['messages']})
        self.assertEqual((BENCH/'cases/01_known_and_metadata.json').read_text(encoding='utf-8'),
                         json.dumps(module.make_cases()[0][1],ensure_ascii=False,indent=2)+'\n')

    def test_crib_segments_locked_and_not_counted_as_inference(self):
        case=load_case(BENCH/'cases/07_alias_mixed_length.json')
        result=analyze(case,iterations=2,restarts=1)
        self.assertEqual(result['verified_anchors']['118'],'兵力')
        self.assertNotIn('123',result['verified_anchors'])
        self.assertEqual(case['codebook_assumptions']['distinct_phrases'],False)
        self.assertEqual(result['proposals']['0007']['status'],'hypothesis_unverified')
        self.assertEqual({len(code) for m in case['messages'] for code in m['codes']}, {3,4})
        self.assertEqual(result['proposals']['123']['status'],'hypothesis_unverified')
        gold=json.loads((BENCH/'gold/07_alias_mixed_length.json').read_text(encoding='utf-8'))
        report=score_result(result,gold,case)
        self.assertEqual(report['verified_anchor_count'],5)
        self.assertEqual(report['unknown_code_count'],5)

    def test_unaligned_crib_cannot_be_counted_as_verified(self):
        case=load_case(BENCH/'cases/05_unaligned_crib.json')
        result=analyze(case,iterations=2,restarts=1)
        self.assertEqual(result['known_code_count'],0)
        self.assertEqual(len(result['pair_review']),1)
        self.assertTrue(all(x['status']=='hypothesis_unverified' for x in result['proposals'].values()))

    def test_gold_not_in_solver_or_inference(self):
        case=load_case(BENCH/'cases/01_known_and_metadata.json')
        a=analyze(case,iterations=2,restarts=1)
        modified=copy.deepcopy(case)
        modified['ground_truth']={'102':'故意錯誤的答案'}
        b=analyze(modified,iterations=2,restarts=1)
        self.assertEqual({k:v['term'] for k,v in a['proposals'].items()},
                         {k:v['term'] for k,v in b['proposals'].items()})
        with tempfile.TemporaryDirectory() as td:
            suite={'version':1,'cases':[{'id':'01_known_and_metadata','case':'case.json','gold':'gold.json',
                        'description':'isolated'}]}
            path=Path(td)
            (path/'suite.json').write_text(json.dumps(suite),encoding='utf-8')
            (path/'case.json').write_text(json.dumps(modified,ensure_ascii=False),encoding='utf-8')
            (path/'gold.json').write_text((BENCH/'gold/01_known_and_metadata.json').read_text(encoding='utf-8'),encoding='utf-8')
            with self.assertRaisesRegex(CaseError,'must NOT contain ground_truth'):
                run_suite(path/'suite.json',variants=(True,))

    def test_minimal_suite_run_and_scores_independent_of_gold(self):
        case=load_case(BENCH/'cases/01_known_and_metadata.json')
        gold=json.loads((BENCH/'gold/01_known_and_metadata.json').read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)
            (path/'case.json').write_text(json.dumps(case,ensure_ascii=False),encoding='utf-8')
            (path/'gold.json').write_text(json.dumps(gold,ensure_ascii=False),encoding='utf-8')
            manifest={'version':1,'cases':[{'id':case['case_id'],'case':'case.json','gold':'gold.json','description':'quick'}]}
            (path/'suite.json').write_text(json.dumps(manifest),encoding='utf-8')
            result=run_suite(path/'suite.json',variants=(True,False))
            self.assertEqual(len(result['runs']),2)
            self.assertTrue(all(r['metrics']['verified_anchor_count']==10 for r in result['runs']))
            self.assertTrue(all(r['metrics']['non_crib_message_count']==16 for r in result['runs']))
            self.assertTrue(all(r['llm_rounds']==0 for r in result['runs']))
            # Corrupting gold changes *scoring*, never the candidate prediction.
            fake=copy.deepcopy(gold)
            fake['codebook']['102']='錯誤'
            with self.assertRaises(CaseError):
                score_result(analyze(case,iterations=2,restarts=1),fake,case)

    def test_benchmark_one_llm_round_mock_local_http_never_receives_gold(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from threading import Thread
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body=self.rfile.read(int(self.headers['Content-Length']))
                requests.append(body.decode('utf-8'))
                self.send_response(200)
                self.send_header('Content-Type','application/json')
                result=json.dumps({'choices':[{'message':{'content':json.dumps({'hypotheses':[]})}}]}).encode()
                self.send_header('Content-Length',str(len(result)))
                self.end_headers()
                self.wfile.write(result)
            def log_message(self,*_):
                pass
        server=HTTPServer(('127.0.0.1',0),Handler)
        thread=Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            # Use the actual tiny alias case, but separate gold still scores only afterwards.
            with tempfile.TemporaryDirectory() as td:
                path=Path(td)
                entry={'id':'07_alias_mixed_length','case':str(BENCH/'cases/07_alias_mixed_length.json'),
                       'gold':str(BENCH/'gold/07_alias_mixed_length.json'),'description':'mock llm'}
                suite=path/'suite.json'
                suite.write_text(json.dumps({'version':1,'cases':[entry]}),encoding='utf-8')
                report=run_suite(suite,variants=(True,),rounds=1,audit_dir=path/'audit',
                   llm_settings={'base_url':f'http://127.0.0.1:{server.server_port}/v1','model':'mock-local',
                                 'allow_private_network':False,'allowed_hosts':[],
                                 'reasoning_effort':'none','response_format':'json_object'})
                self.assertEqual(report['runs'][0]['llm_rounds'],1)
                self.assertEqual(len(requests),1)
                request_body=json.loads(requests[0])
                self.assertEqual(request_body['reasoning_effort'],'none')
                self.assertEqual(request_body['response_format'],{'type':'json_object'})
                self.assertEqual(request_body['model'],'mock-local')
                self.assertNotIn('ground_truth',requests[0])
                self.assertNotIn('07_alias_mixed_length.json',requests[0])
                self.assertTrue(list((path/'audit').glob('*.sqlite')))
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)

    def test_runner_offline_by_default_and_requires_explicit_llm_opt_in(self):
        with tempfile.TemporaryDirectory() as td:
            temp=Path(td)
            with patch('han_codebook.benchmark.run_agent',side_effect=AssertionError('must not use LLM')):
                rc=main(['--config',str(BENCH/'config.yaml'), '--suite',str(BENCH/'suite.json'),
                         '--variants','metadata','--out',str(temp/'report.json')])
            self.assertEqual(rc,0)
            self.assertTrue((temp/'report.json').exists())
            self.assertTrue((temp/'report.md').exists())
            rep=json.loads((temp/'report.json').read_text(encoding='utf-8'))
            self.assertEqual(len(rep['runs']),8)
            self.assertTrue(all(r['llm_rounds']==0 for r in rep['runs']))
            with self.assertRaises(SystemExit):
                # Parsing invalid --variants should reject immediately.
                main(['--variants','unknown'])
            self.assertEqual(main(['--config',str(BENCH/'config.yaml'),'--enable-llm','--variants','metadata',
                                   '--out',str(temp/'should_not_create.json')]),2)
            self.assertFalse((temp/'should_not_create.json').exists())


if __name__=='__main__':
    unittest.main()
