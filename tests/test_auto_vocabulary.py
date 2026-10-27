"""Cold-start LLM lexicon: no fixture lexicon/oracle leaks and deterministic replay."""
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from han_codebook.auto_vocabulary import make_vocabulary_packet, generate_vocabulary, case_from_vocabulary_record
from han_codebook.core import CaseError
from han_codebook.volume_llm import run_llm_comparison, replay_decoding_views

ROOT=Path(__file__).resolve().parents[1]
CASE=json.loads((ROOT/'benchmarks/volume/seed_101_case.json').read_text(encoding='utf-8'))
CFG=ROOT/'config.yaml'

class ColdStartTest(unittest.TestCase):
    def settings(self):
        return {'base_url':'http://192.168.0.134:18080','model':'mock',
                'allow_private_network':True,'allowed_hosts':['192.168.0.134']}

    def fake(self,url,model,payload,**kw):
        if payload.get('task')=='generate_vocabulary':
            self.assertNotIn('profiles',payload)
            self.assertNotIn('gold',payload)
            self.assertNotIn('available_vocabulary',payload)
            if kw.get('on_exchange'):
                kw['on_exchange']('llm_request',{'body':payload})
                kw['on_exchange']('llm_response',{'response':'mock vocab'})
            return {'vocabulary':[{'term':w,'reason':'general-language prior'} for w in
                    ['抵達','集合','前往','到達','道路','建築','供應','檢查','移動','日期']],
                    'patterns':[['前往','道路'],['供應','檢查'],['不存在','道路']]}
        self.assertTrue(payload.get('available_vocabulary'))
        self.assertNotIn('gold',payload)
        return {'hypotheses':[]}

    def test_packet_hides_hardcoded_profiles_and_metadata_off(self):
        case={**CASE,'messages':CASE['messages'][:10]}
        first=make_vocabulary_packet(case,metadata=True)
        self.assertNotIn('profiles',first)
        self.assertEqual(first['corpus_statistics']['messages_count'],10)
        self.assertGreater(len(first['side_information_samples']),0)
        self.assertTrue(any('recipient' in m for m in first['side_information_samples']))
        second=make_vocabulary_packet(case,metadata=False)
        self.assertEqual(second['side_information_samples'],[])
        self.assertEqual(second['corpus_statistics'],first['corpus_statistics'])
        self.assertNotIn('ground_truth',str(second))

    def test_generate_discards_original_fixture_vocabulary_and_preserves_evidence(self):
        case={**CASE,'messages':CASE['messages'][:10]}
        old_profile=case['profiles']
        self.assertIn('補給',old_profile['logistics']['lexicon'])
        generated, record=generate_vocabulary(case,metadata=False,llm_settings=self.settings(),
                                              query=self.fake,progress=lambda _:None)
        self.assertEqual(generated['profiles']['llm_generated_background']['lexicon'].keys(),
                         {'抵達','集合','前往','到達','道路','建築','供應','檢查','移動','日期'})
        self.assertEqual(record['candidate_count'],10)
        self.assertEqual(len(record['patterns']),2)
        self.assertNotIn('補給',generated['profiles']['llm_generated_background']['lexicon'])
        self.assertIs(case['profiles'],old_profile)
        self.assertEqual(case['messages'],generated['messages'])
        replay=case_from_vocabulary_record(case,record)
        self.assertEqual(replay['profiles'],generated['profiles'])

    def test_llm_cold_start_and_old_mode_both_work(self):
        result=run_llm_comparison(sizes=(10,),seeds=(101,),metadata=True,auto_vocabulary=True,
                                  llm_config=CFG,iterations=1,restarts=1,query=self.fake,
                                  progress=lambda _:None)
        self.assertEqual(result['llm_call_total'],2)
        self.assertTrue(result['auto_vocabulary'])
        self.assertFalse(result['fixed_candidate_vocabulary_includes_gold_terms'])
        self.assertEqual(result['runs'][0]['candidate_count'],10)
        self.assertEqual(result['trace'][0]['trace'][0]['task'],'generate_vocabulary')
        self.assertEqual(result['trace'][0]['trace'][0]['status'],'completed')
        self.assertEqual(len(result['decoding_views']),1)
        replay=replay_decoding_views(result,iterations=1,restarts=1)
        self.assertTrue(replay['decoding_view_replay_checks'][0]['matches_saved_top1'])
        old=run_llm_comparison(sizes=(10,),seeds=(101,),metadata=False,auto_vocabulary=False,
                               llm_config=CFG,iterations=1,restarts=1,query=self.fake,
                               progress=lambda _:None)
        self.assertEqual(old['llm_call_total'],1)
        self.assertFalse(old['auto_vocabulary'])

    def test_no_fixed_vocabulary_fallback_when_llm_cannot_generate(self):
        def bad(url,model,packet,**kw):
            return {'vocabulary':['一','二']}
        with self.assertRaises(CaseError):
            generate_vocabulary({**CASE,'messages':CASE['messages'][:10]},metadata=True,
                                llm_settings=self.settings(),query=bad,progress=lambda _:None)

    def test_reject_oracle_and_input_derived_terms_as_gold(self):
        sample={**CASE,'messages':CASE['messages'][:10],'codebook':{'123':'plaintext'}}
        with self.assertRaises(CaseError):make_vocabulary_packet(sample,metadata=True)
        with self.assertRaises(CaseError):case_from_vocabulary_record(CASE,{'terms':[{'term':'a'},{'term':'a'}]})

if __name__=='__main__': unittest.main()
