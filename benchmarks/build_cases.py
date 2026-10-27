"""Deterministic fictional Chinese phrase-codebook benchmark fixture generator.

Gold is written separately from ciphertext-only case inputs. Never load gold into the solver.
No historical ciphertext or real encryption keys are included.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Intentionally mixed-length digit groups, Hanzi/phrase/fixed-command segments,
# and two codes for the same plaintext phrase (118 and 123).
CODEBOOK = {
    '0007':'令', '101':'補給', '102':'車隊', '103':'前線', '104':'運抵',
    '105':'糧秣', '106':'明日', '107':'凌晨', '108':'裝載', '109':'已畢',
    '110':'倉庫', '111':'需要', '112':'增援', '113':'奉令', '114':'調整',
    '115':'路線', '116':'第二營', '117':'集結', '118':'兵力', '119':'備戰',
    '120':'今夜', '121':'準時出發', '122':'請速報', '123':'兵力',
    '124':'軍司令部', '125':'補給處', '126':'報告', '127':'抵達',
}

MESSAGES = [
    ('L01','後勤司令部','第二補給處','113 101 102 106 107 121'),
    ('L02','第二補給處','前線補給分隊','101 102 105 104 110'),
    ('L03','後勤司令部','第二補給處','101 102 114 115'),
    ('L04','第二補給處','後勤司令部','105 108 109 126'),
    ('L05','第二補給處','糧秣倉庫','101 102 120 127 110'),
    ('L06','前線補給分隊','第二補給處','111 105 112 103'),
    ('L07','第二補給處','後勤司令部','125 126 105 104 110'),
    ('L08','運輸調度處','第二補給處','102 114 115 122'),
    ('L09','後勤司令部','第二補給處','0007 102 106 121'),
    ('L10','前線補給分隊','後勤司令部','102 127 103 126'),
    ('O01','軍司令部','第二營作戰室','124 113 116 118 117'),
    ('O02','第二營作戰室','軍司令部','116 123 117 119'),
    ('O03','軍司令部','第二營作戰室','116 118 120 119'),
    ('O04','第二營作戰室','軍司令部','116 111 112 103'),
    ('O05','軍司令部','第二營作戰室','124 0007 116 117'),
    ('O06','第二營作戰室','軍司令部','116 126 118 117'),
    ('O07','軍司令部','第二營作戰室','116 114 115 122'),
    ('O08','第二營作戰室','前線作戰處','116 123 127 103'),
]

PROFILES = {
    'logistics': {
        'keywords': ['補給','後勤','糧秣','倉庫','運輸','調度'],
        'lexicon': {s:weight for s,weight in [
            ('補給',8),('車隊',8),('前線',3),('運抵',6),('糧秣',8),
            ('明日',5),('凌晨',4),('裝載',5),('已畢',3),('倉庫',7),('需要',4),
            ('增援',3),('奉令',4),('調整',6),('路線',6),('今夜',3),
            ('準時出發',5),('請速報',3),('令',3),('補給處',5),('報告',4),('抵達',6),
            ('通信',2),('維修',2),('車站',3),('調撥',3),('停車',1)]},
        # These aren't copied verbatim from held-out telegrams.
        'sentences': [
            ['奉令','補給','車隊','調整','路線'],
            ['補給','車隊','明日','準時出發'],
            ['車隊','運抵','倉庫'],
            ['糧秣','裝載','已畢'],
            ['需要','增援','前線'],
            ['補給處','報告','糧秣','抵達'],
            ['車隊','今夜','抵達'],
        ]
    },
    'operations': {
        'keywords': ['作戰','軍司令','戰鬥','第二營','參謀'],
        'lexicon': {s:weight for s,weight in [
            ('軍司令部',9),('第二營',9),('兵力',9),('集結',9),('備戰',8),
            ('前線',7),('增援',6),('需要',3),('奉令',4),('調整',3),('路線',3),
            ('令',4),('今夜',5),('報告',3),('抵達',4),('請速報',3),
            ('部署',4),('戰車',2),('工兵',2),('指揮部',2),('明日',3)]},
        'sentences': [
            ['軍司令部','奉令','第二營','兵力','備戰'],
            ['第二營','兵力','集結','前線'],
            ['第二營','需要','增援'],
            ['兵力','今夜','備戰'],
            ['第二營','報告','兵力','集結'],
            ['令','第二營','集結'],
        ]
    },
}

def encode(seq: str) -> list[str]:
    codes=seq.split()
    for c in codes:
        assert c in CODEBOOK
    return codes


def base_case() -> dict:
    return {
        'case_id':'fictional_mixed_units',
        'description':'Fully synthetic. Correct answers separated in benchmarks/gold.',
        'codebook_assumptions': {'distinct_phrases': False},
        'profiles': copy.deepcopy(PROFILES),
        'messages':[{'id':m, 'sender':s, 'recipient':r, 'codes':encode(seq)} for m,s,r,seq in MESSAGES],
        'known_pairs':[],
    }


def aligned(case: dict, message_ids: tuple[str,...]) -> list[dict]:
    by_id={m['id']:m for m in case['messages']}
    return [{'message_id':mid,'segments':[CODEBOOK[c] for c in by_id[mid]['codes']]}
            for mid in message_ids]


def make_cases() -> list[tuple[str,dict,str]]:
    base=base_case()
    out=[]
    def add(id: str, case: dict, meaning: str):
        case['case_id']=id
        out.append((id,case,meaning))

    c=copy.deepcopy(base)
    c['known_pairs']=aligned(c,('L01','O01'))
    add('01_known_and_metadata',c,'Both verified aligned cribs and sender/recipient signals')

    c=copy.deepcopy(base)
    add('02_metadata_only',c,'Sender/recipient domain hints but no known plaintext')

    c=copy.deepcopy(base)
    c['known_pairs']=aligned(c,('L01','O01'))
    for m in c['messages']:
        m.pop('sender',None);m.pop('recipient',None)
    add('03_known_only',c,'Confirmed code alignments without sender/recipient context')

    c=copy.deepcopy(base)
    for m in c['messages']:
        m.pop('sender',None);m.pop('recipient',None)
    add('04_cipher_only_with_public_priors',c,'No known plaintext and no metadata; candidate lexicon remains available (not a zero-information cipher)')

    c=copy.deepcopy(base)
    c['known_pairs']=[{'message_id':'L01','plaintext':''.join(CODEBOOK[x] for x in c['messages'][0]['codes'])}]
    add('05_unaligned_crib',c,'Complete plaintext without segment alignment: suggestions only, never verified anchors')

    c=copy.deepcopy(base)
    c['known_pairs']=aligned(c,('O01',))
    for m in c['messages']:
        if m['id'].startswith('L'):
            m['sender']='作戰參謀處';m['recipient']='第二營作戰室'
    add('06_misleading_context',c,'Deliberately wrong recipient/sender clues for logistics traffic')

    c=copy.deepcopy(base)
    # Only three telegrams, one homonymous alias for 兵力 (118 and 123), and a one-char code 007.
    c['messages']=[m for m in c['messages'] if m['id'] in ('O01','O02','O05','O08')]
    c['known_pairs']=aligned(c,('O01',))
    add('07_alias_mixed_length',c,'One-character unit, full-phrase unit, mixed digit lengths and same phrase from two codes')
    return out


def main():
    (ROOT/'cases').mkdir(parents=True,exist_ok=True)
    (ROOT/'gold').mkdir(parents=True,exist_ok=True)
    suite=[]
    for id,case,description in make_cases():
        (ROOT/'cases'/f'{id}.json').write_text(json.dumps(case,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        used={x for m in case['messages'] for x in m['codes']}
        gold={'case_id':id,'codebook':{c:CODEBOOK[c] for c in sorted(used)},
              'messages':{m['id']:''.join(CODEBOOK[c] for c in m['codes']) for m in case['messages']}}
        (ROOT/'gold'/f'{id}.json').write_text(json.dumps(gold,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        suite.append({'id':id,'case':f'cases/{id}.json','gold':f'gold/{id}.json','description':description})
    (ROOT/'suite.json').write_text(json.dumps({'version':1,'cases':suite},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Generated {len(suite)} cases (inputs separate from gold).')

if __name__=='__main__':
    main()
