import copy
import json
from pathlib import Path
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

from han_codebook.core import (load_case, analyze, evaluate_demo, anchors_and_review,
                               domain_for_message, segmentation_candidates, CaseError)
from han_codebook.agent import run_agent, query_local_llm
from han_codebook.cli import main

DEMO = Path(__file__).resolve().parents[1] / 'examples' / 'demo_case.json'


class CipherResearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = load_case(DEMO)
        cls.with_metadata = analyze(cls.case)
        cls.no_metadata = analyze(cls.case, use_metadata=False)

    def test_verified_pair_is_immutable(self):
        result = self.with_metadata
        self.assertEqual(result['verified_anchors']['005'], '補給')
        self.assertEqual(result['proposals']['005']['status'], 'verified_alignment')
        self.assertEqual(result['proposals']['005']['term'], '補給')
        self.assertEqual(result['proposals']['007']['status'], 'hypothesis_unverified')

    def test_metadata_is_structured_signal(self):
        self.assertEqual(domain_for_message(self.case['messages'][0], self.case['profiles'], True), 'logistics')
        self.assertEqual(domain_for_message(self.case['messages'][2], self.case['profiles'], True), 'operations')
        self.assertIsNone(domain_for_message(self.case['messages'][0], self.case['profiles'], False))
        self.assertNotEqual(self.with_metadata['decoded_messages'][0]['domain_inferred'],
                            self.no_metadata['decoded_messages'][0]['domain_inferred'])
        self.assertNotEqual(self.with_metadata['proposals']['020']['term'],
                            self.no_metadata['proposals']['020']['term'])

    def test_plaintext_without_segment_alignment_requires_review(self):
        anchors, reviews, _ = anchors_and_review(self.case)
        self.assertIn('014', anchors)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[0]['status'], 'manual_segmentation_required')
        self.assertIn(['補給','車隊','預定','出發'], reviews[0]['suggestions'])

    def test_conflicting_anchor_rejected(self):
        case = copy.deepcopy(self.case)
        case['known_pairs'].append({'message_id':'L2','segments':['錯誤','車隊','運抵','倉庫']})
        with self.assertRaises(CaseError):
            analyze(case)

    def test_ground_truth_not_seen_during_inference(self):
        case = copy.deepcopy(self.case)
        case['ground_truth'] = {'007':'錯誤標籤'}
        first = {c:p['term'] for c,p in self.with_metadata['proposals'].items()}
        second = {c:p['term'] for c,p in analyze(case)['proposals'].items()}
        self.assertEqual(first, second)

    def test_no_known_pairs_remains_unverified(self):
        case = copy.deepcopy(self.case)
        case['known_pairs'] = []
        result = analyze(case, iterations=2, restarts=1)
        self.assertEqual(result['known_code_count'], 0)
        self.assertTrue(all(p['status'] == 'hypothesis_unverified' for p in result['proposals'].values()))

    def test_invalid_data_rejected(self):
        case = copy.deepcopy(self.case)
        case['messages'][0]['codes'] = ['not numeric']
        with self.assertRaises(CaseError):
            analyze(case)

    def test_nonlocal_llm_endpoint_rejected(self):
        with self.assertRaises(CaseError):
            query_local_llm('https://example.org/v1', 'model', {})

    def test_optional_llm_loop_with_fake_local_server(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                size = int(self.headers['Content-Length'])
                payload = json.loads(self.rfile.read(size))
                assert len(payload['messages']) == 2
                content = json.dumps({'hypotheses':[{'code':'007','candidates':['糧秣'], 'reason':'示意推理'},
                                                     {'code':'005','candidates':['錯誤'], 'reason':'must reject verified code'}]})
                body = json.dumps({'choices':[{'message':{'content':content}}]}).encode()
                self.send_response(200)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *_):
                pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                result = run_agent(self.case, rounds=1, llm_url=f'http://127.0.0.1:{server.server_port}/v1',
                                   model='test-model', db_path=Path(tmp)/'audit.sqlite')
                self.assertEqual(result['agent_rounds_completed'], 1)
                self.assertEqual(result['proposals']['005']['term'], '補給')
                import sqlite3
                with sqlite3.connect(Path(tmp)/'audit.sqlite') as conn:
                    stages = [r[0] for r in conn.execute('select stage from events order by id')]
                self.assertEqual(stages, ['run_started','preflight','statistical_baseline','llm_proposals_unverified','rescore'])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_cli_writes_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, db = Path(tmp)/'out.json', Path(tmp)/'audit.sqlite'
            rc = main([str(DEMO), '--out', str(out), '--db', str(db), '--evaluate-demo'])
            self.assertEqual(rc, 0)
            self.assertTrue(out.is_file())
            self.assertTrue(db.is_file())
            self.assertIn('evaluation', json.loads(out.read_text(encoding='utf-8')))


if __name__ == '__main__':
    unittest.main()
