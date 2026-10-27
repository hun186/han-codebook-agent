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




# Longer fictional telegrams: named routes, quantity, status, intent and deadline.
LONG_TERMS = {
    '128': '車輛', '129': '十二輛', '130': '糧袋', '131': '三十箱',
    '132': '燃料', '133': '已完成清點', '134': '西側', '135': '橋梁',
    '136': '仍可通行', '137': '預計', '138': '午夜', '139': '請確認',
    '140': '收報後回電', '141': '道路', '142': '受阻', '143': '改行',
    '144': '北線', '145': '安全抵達', '146': '目的地', '147': '已核實',
    '148': '指揮所', '149': '工兵', '150': '警戒', '151': '陣地',
    '152': '編隊', '153': '完成部署', '154': '待命', '155': '明晨',
    '156': '增派人員', '157': '沿途', '158': '警戒加強', '159': '通知',
    '160': '補給需求', '161': '下一批', '162': '車隊已出發',
    '163': '請速報位置', '164': '傷員', '165': '醫療站',
    '166': '轉運', '167': '依原計畫', '168': '延後兩時',
}
CODEBOOK.update(LONG_TERMS)

LONG_TELEGRAMS = [
('後勤司令部','第二補給處',
 '113 101 102 120 121 128 129 105 131 108 133 141 134 135 136 137 138 104 103 139 140'),
('第二補給處','前線補給分隊',
 '125 126 101 102 128 129 130 131 133 141 142 143 144 137 138 145 146 139 140'),
('前線補給分隊','後勤司令部',
 '116 111 105 132 160 161 101 102 157 141 142 143 144 112 103 139 140'),
('第二補給處','後勤司令部',
 '125 126 105 130 131 108 109 133 102 120 121 141 134 135 136 163 140'),
('軍司令部','第二營作戰室',
 '124 113 116 118 117 119 152 151 153 150 155 137 103 159 148 139 140'),
('第二營作戰室','軍司令部',
 '116 126 123 117 152 153 151 150 154 157 141 142 111 149 156 139 140'),
('第二營作戰室','前線作戰處',
 '116 113 118 117 119 150 151 157 141 134 135 136 167 155 121 139 140'),
('後勤司令部','第二補給處',
 '0007 101 102 128 129 120 162 141 142 143 144 157 150 137 138 145 146 140'),
('第二補給處','後勤司令部',
 '125 126 102 105 131 132 108 133 141 134 135 142 143 144 168 137 145 146 140'),
('前線補給分隊','第二補給處',
 '103 125 126 160 105 132 111 112 156 160 163 161 102 137 155 121 140'),
('軍司令部','前線作戰處',
 '124 159 116 118 152 117 150 151 149 157 141 136 167 155 121 139 140'),
('第二營作戰室','軍司令部',
 '116 126 164 166 165 105 111 101 102 160 157 141 142 168 163 140'),
]


def long_case() -> dict:
    """Coherent longer fictional multi-clause dispatches, 16-21 groups each."""
    case=base_case()
    for profile in case['profiles'].values():
        profile['lexicon'].update({word: 3 for word in LONG_TERMS.values()})
    case['profiles']['logistics']['sentences'] += [
        ['車輛','十二輛','糧袋','三十箱','已完成清點'],
        ['道路','受阻','改行','北線'],
        ['預計','午夜','安全抵達','目的地'],
        ['傷員','轉運','醫療站'],
    ]
    case['profiles']['operations']['sentences'] += [
        ['第二營','編隊','完成部署','警戒','陣地'],
        ['工兵','沿途','道路','受阻'],
        ['警戒加強','指揮所','待命'],
    ]
    case['messages']=[]
    for i, (sender,recipient,seq) in enumerate(LONG_TELEGRAMS):
        m={'id':f'EXT{i+1:02}', 'sender':sender,'recipient':recipient,
           'codes':encode(seq),'notes':'虛構完整業務電報：包含數量、位置、動態、時限、回覆需求；無真實軍事情報'}
        if i in (1,3,5,7,9):
            m['observations']=[{'source':f'模擬第三方目擊紀錄-{i}',
                'observed_at':f'1942-05-{i+3:02}', 'activity':'目擊車隊移動',
                'destination':'補給倉庫', 'status':'途中', 'confidence':0.65,
                'note':'目擊對象可能與密電無關，須與其他來源交叉查證'}]
        case['messages'].append(m)
    case['known_pairs']=aligned(case,('EXT01','EXT05'))
    return case


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

    c=long_case()
    add('08_long_dispatch_with_observations',c,'Twelve fictional multi-clause 12-21-group telegrams, aligned pairs and uncertain third-party sightings')
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
