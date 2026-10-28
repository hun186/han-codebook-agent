"""Verify the published 100-report demo, scoring isolation, and Word appendix.

Synthetic reference is allowed in this OFFLINE QA test only, not Mock inference.
"""
import collections
import hashlib
import json
from pathlib import Path
import unittest
import zipfile
from xml.etree import ElementTree

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'benchmarks'/'adaptive_100'
DEMO=ROOT/'vercel-demo'

class AdaptiveHundredPublishedTest(unittest.TestCase):
    def test_replay_is_complete_and_does_not_embed_gold(self):
        fixture=json.loads((DEMO/'data'/'adaptive_trial_100.json').read_text(encoding='utf-8'))
        public=fixture['public']
        lock=fixture['locked_predictions']
        gold=json.loads((DATA/'reference'/'han_adaptive_new_gold_PRIVATE.json').read_text(encoding='utf-8'))
        assert fixture['kind']=='PUBLIC_SYNTHETIC_ADAPTIVE_REPLAY'
        self.assertEqual(len(public['messages']),100)
        self.assertEqual(sum(len(m['codes']) for m in public['messages']),852)
        self.assertEqual(sum(len(m['observations']) for m in public['messages']),34)
        self.assertEqual(len(gold['code_to_word']),60)
        self.assertEqual([len(r['vocabulary']) for r in lock['rounds']],[27,48,77])
        self.assertEqual(len(lock['rounds'][-1]['predictions']),60)
        self.assertEqual([m['correct_types'] for m in fixture['published_metrics']],[8,28,31,4])
        self.assertEqual([m['correct_positions'] for m in fixture['published_metrics']],[156,444,470,50])
        self.assertEqual([m['complete_messages'] for m in fixture['published_metrics']],[0]*4)
        self.assertEqual(fixture['locked_sha256'],
          hashlib.sha256((DATA/'han_adaptive_new_predictions_LOCKED.json').read_bytes()).hexdigest())
        self.assertEqual(fixture['locked_sha256'],
          '960a0394a9bb2d873f81987fa4b3f31138cccb7ac8ef5ac60a12269e368ab86a')
        raw=(DEMO/'data'/'adaptive_trial_100.json').read_text(encoding='utf-8')
        self.assertNotIn('code_to_word',raw)
        self.assertNotIn('messages_words',raw)
        self.assertNotIn('ground_truth',raw)
        self.assertEqual(len(public['fixed_vocab']),27)
        self.assertEqual(len(lock['round2_new_terms']),21)
        self.assertEqual(len(lock['round3_new_terms']),29)

    def test_word_appendix_contains_every_cipher_and_reference(self):
        path=DEMO/'reports'/'adaptive_100_full_report.docx'
        self.assertGreater(path.stat().st_size,25000)
        with zipfile.ZipFile(path) as z:
            self.assertIn('word/document.xml',z.namelist())
            root=ElementTree.fromstring(z.read('word/document.xml'))
        ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        text=''.join(x.text or '' for x in root.findall('.//w:t',ns))
        public=json.loads((DATA/'han_adaptive_new_public.json').read_text(encoding='utf-8'))
        gold=json.loads((DATA/'reference'/'han_adaptive_new_gold_PRIVATE.json').read_text(encoding='utf-8'))
        lock=json.loads((DATA/'han_adaptive_new_predictions_LOCKED.json').read_text(encoding='utf-8'))
        prediction=lock['rounds'][-1]['predictions']
        for m in public['messages']:
            self.assertIn(m['id'],text)
            self.assertIn(m['sender'],text)
            self.assertIn(m['recipient'],text)
            for obs in m['observations']:
                self.assertIn(obs['activity'],text)
                self.assertIn(obs['location'],text)
            self.assertIn(' '.join(m['codes']),text)
            self.assertIn('｜'.join(gold['messages_words'][m['id']]),text)
            self.assertIn('｜'.join(
               '［未解］' if prediction[c]=='[未解]' else prediction[c] for c in m['codes']),text)
        for phrase in ['51.67%','55.16%','0/100','附錄 A','附錄 B']:
            self.assertIn(phrase,text)

if __name__=='__main__':
    unittest.main()
