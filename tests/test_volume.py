"""Shared-codebook volume study must preserve nesting and keep oracle labels out of inference."""
from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from han_codebook.core import analyze, load_case
from han_codebook.volume import MANIFEST, load_manifest, probe_metrics, run_study, main

ROOT=Path(__file__).resolve().parents[1]
BUILD=ROOT/'benchmarks'/'build_volume.py'


class VolumeStudyTests(unittest.TestCase):
    def test_seed_corpora_are_deterministic_nested_and_one_codebook(self):
        manifest, home=load_manifest(MANIFEST)
        self.assertEqual([x['seed'] for x in manifest['datasets']], [101,202,303])
        for item in manifest['datasets']:
            case=load_case(home/item['case'])
            gold=json.loads((home/item['gold']).read_text(encoding='utf-8'))
            self.assertEqual(len(case['messages']),100)
            self.assertEqual(len(gold['probe_messages']),20)
            self.assertEqual(case['known_pairs'],[])
            self.assertEqual(case['codebook_assumptions']['distinct_phrases'],False)
            self.assertFalse(set(case)&{'gold','codebook','ground_truth'})
            self.assertFalse(any(set(m)&{'plaintext','segments','ground_truth'} for m in case['messages']))
            self.assertFalse({m['id'] for m in case['messages']} & {m['id'] for m in gold['probe_messages']})
            for size in (10,25,50,100):
                observed={code for m in case['messages'][:size] for code in m['codes']}
                self.assertTrue(observed<=set(gold['codebook']))
                self.assertTrue(all('received_at' in m for m in case['messages'][:size]))
            self.assertEqual(len({m['id'] for m in case['messages']}),100)
            # The same code cannot mean different words anywhere in one corpus.
            self.assertTrue(all(''.join(gold['codebook'][c] for c in m['codes'])==gold['messages'][m['id']]
                                for m in case['messages']))

    def test_fixture_generation_matches_checked_in_files(self):
        bench=str(BUILD.parent)
        sys.path.insert(0,bench)
        try:
            spec=importlib.util.spec_from_file_location('volume_builder',BUILD)
            mod=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            expected=json.loads((ROOT/'benchmarks/volume/seed_101_case.json').read_text(encoding='utf-8'))
            gold=json.loads((ROOT/'benchmarks/volume/seed_101_gold.json').read_text(encoding='utf-8'))
            actual_case,actual_gold=mod.generate(101)
            self.assertEqual(actual_case,expected)
            self.assertEqual(actual_gold,gold)
        finally:
            sys.path.remove(bench)

    def test_only_inputs_reach_inference_and_metrics_compare_nested_sizes(self):
        calls=[]
        def recording(case,*args,**kwargs):
            calls.append(copy.deepcopy(case))
            return analyze(case,*args,**kwargs)
        with patch('han_codebook.volume.analyze',side_effect=recording):
            report=run_study(seeds=(101,),sizes=(10,50,100),metadata_variants=(True,False),iterations=1,restarts=1)
        self.assertEqual(len(report['runs']),6)
        self.assertEqual([len(c['messages']) for c in calls],[10,10,50,50,100,100])
        self.assertTrue(all(c['known_pairs']==[] for c in calls))
        self.assertTrue(all('gold' not in str(c) and 'ground_truth' not in str(c) for c in calls))
        self.assertEqual(report['runs'][0]['shared_initial_10_codes'],report['runs'][-1]['shared_initial_10_codes'])
        self.assertTrue(all(x['one_codebook'] for x in report['runs']))
        self.assertTrue(all(x['probe_messages']==20 for x in report['runs']))
        self.assertTrue(all(0<=x['probe_coverage_rate']<=1 for x in report['runs']))
        # Public vocab remains the same at 10,50,100 messages.
        self.assertEqual(calls[0]['profiles'],calls[-1]['profiles'])
        self.assertEqual(calls[0]['messages'],calls[-1]['messages'][:10])

    def test_gold_alters_scoring_not_inference(self):
        case=json.loads((ROOT/'benchmarks/volume/seed_101_case.json').read_text(encoding='utf-8'))
        gold=json.loads((ROOT/'benchmarks/volume/seed_101_gold.json').read_text(encoding='utf-8'))
        result=analyze({**case,'messages':case['messages'][:10]},iterations=1,restarts=1)
        original=probe_metrics(result['proposals'],gold)
        tampered=copy.deepcopy(gold)
        tampered['codebook']={key:'錯誤答案' for key in tampered['codebook']}
        changed=probe_metrics(result['proposals'],tampered)
        self.assertEqual(changed['probe_correct_groups'],0)
        self.assertGreaterEqual(original['probe_correct_groups'],0)
        self.assertEqual(result['known_code_count'],0)

    def test_cli_writes_reports_and_bad_ranges_fail(self):
        with TemporaryDirectory() as td:
            dest=Path(td)/'data.json'
            rc=main(['--seeds','101','--sizes','10,50','--metadata','on',
                     '--iterations','1','--restarts','1','--out',str(dest)])
            self.assertEqual(rc,0)
            self.assertTrue(dest.exists())
            self.assertTrue(dest.with_suffix('.md').exists())
            bad=main(['--seeds','101','--sizes','50,10','--out',str(Path(td)/'bad.json')])
            self.assertEqual(bad,2)


if __name__=='__main__':unittest.main()
