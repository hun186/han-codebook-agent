"""Network-free tests: LLM mode must compare fairly and use every message."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from han_codebook.core import analyze, CaseError
from han_codebook.volume_llm import llm_rescore, run_llm_comparison, main

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / 'benchmarks/volume/seed_101_case.json'
CFG = ROOT / 'config.yaml'


class LocalLLMVolumeTests(unittest.TestCase):
    def _settings(self):
        return {'base_url': 'http://192.168.0.134:18080', 'model': 'mock-not-real',
                'allow_private_network':True, 'allowed_hosts':['192.168.0.134'], 'timeout_seconds':12}

    def test_every_one_of_100_messages_sent_exactly_once_per_round(self):
        case=json.loads(CASE.read_text(encoding='utf-8'))
        baseline=analyze(case,iterations=1,restarts=1)
        seen=[]
        def llm(url,model,packet,**kw):
            self.assertIsNone(kw['on_exchange'])
            self.assertEqual(packet['verified_anchors'],{})
            self.assertFalse({'gold','ground_truth','codebook'} & set(packet))
            seen.extend(m['id'] for m in packet['messages'])
            return {'hypotheses':[]}
        result,records,calls=llm_rescore(case,baseline,metadata=True,llm_settings=self._settings(),
            rounds=1,batch_size=25,iterations=1,restarts=1,query=llm,progress=lambda _:None)
        self.assertEqual(calls,4)
        self.assertEqual(len(records),4)
        self.assertEqual(seen,[m['id'] for m in case['messages']])
        self.assertEqual(result['proposals'],baseline['proposals'])
        self.assertTrue(all(record['accepted']==[] for record in records))

    def test_metadata_off_no_sender_recipient_notes_or_sightings_and_valid_hints(self):
        case=json.loads(CASE.read_text(encoding='utf-8'))
        case['messages']=case['messages'][:10]
        baseline=analyze(case,use_metadata=False,iterations=1,restarts=1)
        got=[]
        def fake_llm(url,model,packet,**kw):
            got.append(packet)
            code=next(iter(packet['unresolved']))
            word=packet['available_vocabulary'][0]
            return {'hypotheses':[{'code':code,'candidates':[word,'NOT_IN_VOCAB'],'reason':'test'},
                                 {'code':'999999999','candidates':[word]}]}
        out,log,calls=llm_rescore(case,baseline,metadata=False,llm_settings=self._settings(),
            rounds=1,batch_size=5,iterations=1,restarts=1,query=fake_llm,progress=lambda _:None)
        self.assertEqual(calls,2)
        self.assertTrue(all(p['profiles']=={} for p in got))
        self.assertTrue(all(set(m)=={'id','codes'} for p in got for m in p['messages']))
        self.assertEqual(sum(len(x['accepted']) for x in log),2)
        self.assertEqual(sum(x['rejected'] for x in log),2)
        self.assertEqual(out['known_code_count'],0)

    def test_io_capture_is_opt_in(self):
        case=json.loads(CASE.read_text(encoding='utf-8'))
        case['messages']=case['messages'][:10]
        b=analyze(case,iterations=1,restarts=1)
        def mock(url,model,packet,**kw):
            if kw['on_exchange']:
                kw['on_exchange']('llm_request',{'body':'mock-prompt'})
                kw['on_exchange']('llm_response',{'response':'mock-reply'})
            return {'hypotheses':[]}
        _, off,_=llm_rescore(case,b,metadata=True,llm_settings=self._settings(),rounds=1,
                            query=mock,iterations=1,restarts=1,progress=lambda _:None)
        _, on,_=llm_rescore(case,b,metadata=True,llm_settings=self._settings(),rounds=1,
                           query=mock,iterations=1,restarts=1,capture_io=True,progress=lambda _:None)
        self.assertNotIn('exchanges',off[0]);self.assertEqual(len(on[0]['exchanges']),2)

    def test_end_to_end_scores_after_fake_llm_and_reports(self):
        seen=[]
        def mock(url,model,packet,**kw):
            seen.extend(m['id'] for m in packet['messages'])
            return {'hypotheses':[]}
        report=run_llm_comparison(seeds=(101,),sizes=(10,25,50,100),metadata=False,
                llm_config=CFG,rounds=1,iterations=1,restarts=1,
                query=mock,progress=lambda _:None)
        self.assertEqual(report['llm_call_total'],8)
        self.assertEqual(len(seen),185)
        self.assertEqual([r['llm_calls'] for r in report['runs']],[1,1,2,4])
        self.assertEqual([r['messages'] for r in report['runs']],[10,25,50,100])
        self.assertTrue(all(r['stat_top1']==r['llm_top1'] for r in report['runs']))
        self.assertTrue(all(r['stat_corrected_by_llm']==0 for r in report['runs']))
        self.assertTrue(all(r['changed_codes']==0 for r in report['runs']))
        self.assertEqual(report['zero_known_plaintext'],True)
        self.assertEqual(report['llm_used'],True)  # mocked network, not live inference

    def test_opt_in_required_and_invalid_remote_rejected(self):
        self.assertEqual(main(['--sizes','10']),2)
        case=json.loads(CASE.read_text(encoding='utf-8'))
        b=analyze({**case,'messages':case['messages'][:10]},iterations=1,restarts=1)
        with self.assertRaises(CaseError):
            llm_rescore({**case,'messages':case['messages'][:10]},b,metadata=True,
                        llm_settings={**self._settings(),'allow_private_network':False},progress=lambda _:None)


if __name__=='__main__': unittest.main()
