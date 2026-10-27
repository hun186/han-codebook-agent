"""Regression: auxiliary observations may contain adversarial nested evaluation labels."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from han_codebook.auto_vocabulary import make_vocabulary_packet
from han_codebook.volume_llm import _input_messages
from han_codebook.llm_evidence import safe_observations

BASE = Path(__file__).resolve().parents[1]
CASE = json.loads((BASE/'benchmarks/volume/seed_101_case.json').read_text(encoding='utf-8'))


class ObservationLeakTests(unittest.TestCase):
    def setUp(self):
        self.case = copy.deepcopy(CASE)
        self.case['messages'] = self.case['messages'][:10]
        self.original = self.case['messages'][0]
        self.original['observations'] = [{
            'source':'field report','activity':'movement','destination':'northern road',
            'confidence':.6, 'note':'possibly unrelated',
            'ground_truth':{'0007':'兵力'}, 'gold':{'codebook':'SECRET'},
            'extraneous':{'plaintext':'SECRET'},
            # Even an otherwise allowed field must not contain a nested object.
            'status': {'ground_truth':{'009':'SECRET'}}
        }]

    def test_safe_observations_strips_oracle_keys_and_nested_values(self):
        value = safe_observations(self.original['observations'])
        self.assertEqual(value,[{'source':'field report','activity':'movement',
                                  'destination':'northern road','note':'possibly unrelated',
                                  'confidence':.6}])
        self.assertIn('ground_truth', self.original['observations'][0])

    def test_both_llm_paths_share_nested_whitelist(self):
        outputs = [
            _input_messages(self.case['messages'],metadata=True),
            make_vocabulary_packet(self.case,metadata=True)['side_information_samples'],
        ]
        for messages in outputs:
            with self.subTest(path='rescore' if 'codes' in messages[0] else 'vocab'):
                serialized=json.dumps(messages,ensure_ascii=False)
                for forbidden in ('ground_truth','gold','codebook','SECRET','extraneous'):
                    self.assertNotIn(forbidden,serialized)
                self.assertEqual(messages[0]['observations'][0]['destination'],'northern road')
                self.assertNotIn('status',messages[0]['observations'][0])

    def test_no_metadata_has_no_observations(self):
        self.assertEqual(_input_messages(self.case['messages'],metadata=False)[0].keys(), {'id','codes'})
        self.assertEqual(make_vocabulary_packet(self.case,metadata=False)['side_information_samples'],[])

if __name__=='__main__':unittest.main()
