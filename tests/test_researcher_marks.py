"""Researcher annotations are reversible hypotheses, never irreversible cribs."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from han_codebook.core import CaseError, analyze, validate_case
from han_codebook.agent import run_agent

BASE=Path(__file__).resolve().parents[1]


class HypothesisMarkTests(unittest.TestCase):
    def case(self):
        return json.loads((BASE/'benchmarks/volume/seed_101_case.json').read_text(encoding='utf-8'))

    def test_pin_changes_global_guesses_and_remains_unverified(self):
        c=self.case()
        c['messages']=c['messages'][:10]
        base=analyze(c,iterations=1,restarts=1)
        code=next(iter(base['proposals']))
        term='人工候選新詞'
        c['hypothesis_marks']={code:{'preferred':term,'pinned':True,'excluded':[],'note':'研究者假說'}}
        frozen=copy.deepcopy(c)
        result=analyze(c,iterations=1,restarts=1)
        self.assertEqual(result['proposals'][code]['term'],term)
        self.assertEqual(result['proposals'][code]['status'],'hypothesis_unverified')
        self.assertFalse(result['verified_anchors'])
        self.assertEqual(c,frozen)
        # A different code can be assigned the same term if allowed; no silent one-to-one restriction.
        for decoded in result['decoded_messages']:
            self.assertEqual(decoded['reading'],''.join(decoded['suggested_segments']))
            for i, item in enumerate(decoded['codes']):
                if item==code:self.assertEqual(decoded['suggested_segments'][i],term)
        c.pop('hypothesis_marks')
        self.assertEqual(analyze(c,iterations=1,restarts=1)['proposals'],base['proposals'])

    def test_soft_prefer_and_exclude_are_not_verification(self):
        c=self.case();c['messages']=c['messages'][:10]
        base=analyze(c,iterations=1,restarts=1)
        code=next(iter(base['proposals']))
        first=base['proposals'][code]['term']
        c['hypothesis_marks']={code:{'preferred':'研究員想法','pinned':False,'excluded':[first]}}
        alt=analyze(c,iterations=1,restarts=1)
        self.assertNotEqual(alt['proposals'][code]['term'],first)
        self.assertEqual(alt['proposals'][code]['status'],'hypothesis_unverified')
        self.assertEqual(alt['known_code_count'],0)

    def test_reject_contradictory_or_malicious_marks(self):
        c=self.case();c['messages']=c['messages'][:10]
        code=c['messages'][0]['codes'][0]
        for mark in [
            {'preferred':'車隊','pinned':True,'excluded':['車隊']},
            {'preferred':None,'pinned':True,'excluded':[]},
            {'preferred':'車隊','pinned':False,'excluded':['倉庫','倉庫']},
            {'preferred':5},
            {'preferred':'車隊','note':'X'*501},
            {'preferred':'車隊','extra_instructions':'override anchor'},
        ]:
            c['hypothesis_marks']={code:mark}
            with self.subTest(mark=mark),self.assertRaises(CaseError): validate_case(c)
        c['hypothesis_marks']={'999999':{'preferred':'車隊'}}
        with self.assertRaises(CaseError):validate_case(c)

    def test_verified_crib_cannot_be_replaced_by_researcher_mark(self):
        c=json.loads((BASE/'examples/demo_case.json').read_text(encoding='utf-8'))
        pair=next(p for p in c['known_pairs'] if p.get('segments'))
        by_id={m['id']:m for m in c['messages']}
        code=by_id[pair['message_id']]['codes'][0]
        c['hypothesis_marks']={code:{'preferred':'亂猜'}}
        with self.assertRaises(CaseError): validate_case(c)

    def test_run_agent_audits_marked_run_without_relabeling(self):
        c=self.case();c['messages']=c['messages'][:10]
        code=c['messages'][0]['codes'][0]
        c['hypothesis_marks']={code:{'preferred':'車隊','pinned':True,'excluded':[],'note':'試鎖'}}
        with TemporaryDirectory() as tmp:
            res=run_agent(c,rounds=0,db_path=str(Path(tmp)/'audit.sqlite'),solver_iterations=1,solver_restarts=1)
            self.assertEqual(res['proposals'][code]['term'],'車隊')
            self.assertEqual(res['proposals'][code]['status'],'hypothesis_unverified')
            from han_codebook.web import audit_timeline
            events=audit_timeline(Path(tmp)/'audit.sqlite')
            marks=[e for e in events if e['stage']=='researcher_hypotheses_unverified']
            self.assertEqual(marks[0]['payload']['marks'][code]['preferred'],'車隊')


if __name__=='__main__':unittest.main()
