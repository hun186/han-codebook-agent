"""Per-telegram hypothesis explorer and review-P2 regression, without live LLM."""
from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from han_codebook.core import analyze
from han_codebook.volume_decode_view import build_decoding_view, explorer_html
from han_codebook.volume_llm import (
    LLMStudyInterrupted, llm_rescore, run_llm_comparison, as_html, main,
)

BASE = Path(__file__).resolve().parents[1]
CASE = BASE / 'benchmarks/volume/seed_101_case.json'
CFG = BASE / 'config.yaml'


class ViewerTests(unittest.TestCase):
    def settings(self):
        return {'base_url':'http://192.168.0.134:18080', 'model':'mock',
                'allow_private_network':True,'allowed_hosts':['192.168.0.134']}

    def corpus(self, count=10):
        case=json.loads(CASE.read_text(encoding='utf-8'))
        case['messages']=case['messages'][:count]
        return case

    def test_view_contains_code_aligned_guesses_without_oracle(self):
        c=self.corpus()
        base=analyze(c,iterations=1,restarts=1)
        view=build_decoding_view(c,base,base,seed=101,size=10,trace=[])
        self.assertEqual(len(view['messages']),10)
        self.assertEqual(view['messages'][0]['codes'],c['messages'][0]['codes'])
        self.assertEqual(view['statistical'],view['llm'])
        self.assertTrue(all('term' in x and x['status']=='hypothesis_unverified'
                            for x in view['statistical'].values()))
        self.assertFalse({'ground_truth','gold','codebook','probe_messages'} & set(view))
        self.assertNotIn('plaintext',json.dumps(view,ensure_ascii=False))

    def test_html_embedded_json_is_script_safe_and_marks_guesses(self):
        c=self.corpus()
        c['messages'][0]['sender']='</script><script>alert(1)</script>'
        b=analyze(c,iterations=1,restarts=1)
        v=build_decoding_view(c,b,b,seed=101,size=10,trace=[])
        html=explorer_html({'decoding_views':[v]})
        self.assertIn('密電候選解讀探索器',html)
        self.assertIn('未驗證',html)
        self.assertIn('decStat',html)
        self.assertIn('decLlm',html)
        self.assertNotIn('</script><script>alert(1)</script>',html)
        self.assertIn('\\u003c/script\\u003e',html)

    def test_real_report_html_contains_message_explorer(self):
        def mock(url,model,packet,**kwargs):
            return {'hypotheses':[]}
        report=run_llm_comparison(sizes=(10,25),seeds=(101,),metadata=True,
            llm_config=CFG,rounds=1,iterations=1,restarts=1,
            query=mock,progress=lambda s:None)
        self.assertEqual([v['messages_count'] for v in report['decoding_views']],[10,25])
        self.assertEqual([len(v['messages']) for v in report['decoding_views']],[10,25])
        self.assertTrue(all('received_at' in m for v in report['decoding_views'] for m in v['messages']))
        self.assertIn('decodingViewData',as_html(report))
        self.assertEqual(report['runs'][0]['stat_top1'],report['runs'][0]['llm_top1'])
        self.assertFalse(any('codebook' in v for v in report['decoding_views']))

    def test_duplicate_candidates_and_duplicate_entries_do_not_inflate_hints(self):
        c=self.corpus()
        b=analyze(c,iterations=1,restarts=1)
        code=sorted(b['proposals'])[0]
        word=sorted({w for p in c['profiles'].values() for w in p['lexicon']})[0]
        def run(candidates):
            def mock(url,model,packet,**kw):
                return {'hypotheses':[{'code':code,'candidates':candidates,'reason':'test'},
                        {'code':code,'candidates':[word],'reason':'duplicate'}]}
            return llm_rescore(c,b,metadata=True,llm_settings=self.settings(),
                iterations=1,restarts=1,query=mock,progress=lambda s:None)
        unique=run([word])
        repeated=run([word]*5)
        self.assertEqual(unique[0]['proposals'],repeated[0]['proposals'])
        self.assertEqual(unique[1][0]['accepted'],repeated[1][0]['accepted'])
        self.assertEqual(unique[1][0]['rejected'],1)
        self.assertEqual(repeated[1][0]['rejected'],1)

    def test_failed_model_call_keeps_opt_in_partial_trace(self):
        c=self.corpus()
        b=analyze(c,iterations=1,restarts=1)
        def failing(url,model,packet,**kw):
            kw['on_exchange']('llm_request',{'body':'mock-req'})
            kw['on_exchange']('llm_response',{'http_status':400,'body':'mock-reply'})
            raise RuntimeError('test mock http 400')
        with self.assertRaises(LLMStudyInterrupted) as cm:
            llm_rescore(c,b,metadata=True,llm_settings=self.settings(),
                capture_io=True,iterations=1,restarts=1,query=failing,
                progress=lambda s:None)
        record=cm.exception.trace[0]
        self.assertEqual(record['status'],'failed')
        self.assertEqual(len(record['exchanges']),2)
        self.assertEqual(record['exchanges'][1]['http_status'],400)
        def failing_no_capture(url,model,packet,**kw):
            raise RuntimeError('mock connection failed')
        with self.assertRaises(LLMStudyInterrupted) as cm2:
            llm_rescore(c,b,metadata=True,llm_settings=self.settings(),
                capture_io=False,iterations=1,restarts=1,query=failing_no_capture,
                progress=lambda s:None)
        self.assertNotIn('exchanges',cm2.exception.trace[0])

    def test_failed_study_cli_writes_partial_only_after_opt_in(self):
        with TemporaryDirectory() as td:
            out=Path(td)/'volume.json'
            partial={'status':'failed','capture_llm_io':True,
                     'trace':[{'seed':101,'messages':50,'status':'failed','trace':[
                         {'exchanges':[{'stage':'llm_response','body':'mock-http-error'}]}]}]}
            error=LLMStudyInterrupted('mock failure',trace=partial['trace'])
            error.partial_report=partial
            with patch('han_codebook.volume_llm.run_llm_comparison',side_effect=error):
                status=main(['--enable-llm','--capture-llm-io','--out',str(out)])
                self.assertEqual(status,2)
                failfile=out.with_suffix('.failed.json')
                self.assertTrue(failfile.is_file())
                self.assertIn('mock-http-error',failfile.read_text(encoding='utf-8'))
                self.assertFalse(out.exists())
                failfile.unlink()
                status=main(['--enable-llm','--out',str(out)])
                self.assertEqual(status,2)
                self.assertFalse(failfile.exists())

if __name__ == '__main__':
    unittest.main()

# Additional replay regression intentionally outside class to keep fixture usage straightforward.
class OfflineReplayTests(unittest.TestCase):
    def test_replay_old_report_needs_no_llm_calls_and_reproduces_scores(self):
        from han_codebook.volume_llm import replay_decoding_views
        def mock(url,model,packet,**kw):
            c=next(iter(packet['unresolved']))
            return {'hypotheses':[{'code':c,'candidates':[packet['available_vocabulary'][0]],'reason':'mocked'}]}
        report=run_llm_comparison(sizes=(10,25,50,100),seeds=(101,),llm_config=CFG,
            iterations=2,restarts=2,query=mock,progress=lambda s:None)
        views=report.pop('decoding_views')
        rebuilt=replay_decoding_views(report,iterations=2,restarts=2)
        self.assertEqual(rebuilt['decoding_views'],views)
        self.assertTrue(all(x['matches_saved_top1'] for x in rebuilt['decoding_view_replay_checks']))
        self.assertIn('重新求解',as_html(rebuilt))

    def test_offline_cli_replay_without_llm_enable_switch(self):
        from han_codebook.volume_llm import replay_decoding_views
        def mock(url,model,packet,**kw): return {'hypotheses':[]}
        report=run_llm_comparison(sizes=(10,),seeds=(101,),llm_config=CFG,
            iterations=2,restarts=2,query=mock,progress=lambda s:None)
        report.pop('decoding_views')
        with TemporaryDirectory() as folder:
            path=Path(folder)/'study.json'
            path.write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8')
            with patch('han_codebook.volume_llm.query_local_llm',side_effect=AssertionError('LLM must not run')):
                self.assertEqual(main(['--rebuild-view-from',str(path),'--manifest',str(BASE/'benchmarks/volume/manifest.json')]),0)
            self.assertTrue(path.with_name('study_decipher.html').is_file())
            self.assertTrue(path.with_name('study_decipher.json').is_file())
            self.assertTrue(path.is_file())
