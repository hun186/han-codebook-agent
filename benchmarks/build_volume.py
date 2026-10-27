"""Generate nested 100-telegram fiction with a single, immutable codebook per case.

The secret labels are written to separate `gold` files. No initial known
plaintext is provided; all profile prior vocabularies are public candidate
pools, which is a much easier problem than an unconstrained historical cipher.
"""
from __future__ import annotations
import copy
import json
import random
from pathlib import Path
from build_cases import CODEBOOK, PROFILES, LONG_TERMS

HERE = Path(__file__).resolve().parent / 'volume'
SEEDS = (101, 202, 303)
COUNTS = (10, 25, 50, 100)

# Every transmission combines several independent clauses. A generator may use
# the same *plain language* vocabulary across seeds, but the codebook mapping
# is fixed within one seed/case and permuted across different seeds/cases.
LOG_OPEN = [
    ('113','101','102'), ('125','126','101','102'),
    ('101','102','120','121'), ('125','126','160'),
    ('103','125','126','160'), ('125','126','161','101','102'),
]
LOG_MIDDLE = [
    ('128','129','105','130','131','108','133'),
    ('105','130','131','108','109'),
    ('105','132','160','111','112'),
    ('141','134','135','136'),
    ('141','142','143','144'),
    ('102','157','141','142','143','144'),
    ('102','120','162'),
    ('102','137','138','145','146'),
    ('164','166','165','111','101'),
    ('101','102','168','137','155','121'),
]
LOG_END = [
    ('137','138','104','103','139','140'),
    ('137','145','146','140'),
    ('163','140'),
    ('121','139','140'),
    ('159','125','126','140'),
]
OPS_OPEN = [
    ('124','113','116','118'),
    ('116','126','123'),
    ('124','159','116'),
    ('116','113','118'),
    ('116','111','112'),
]
OPS_MIDDLE = [
    ('117','119','152','151','153'),
    ('152','153','151','150','154'),
    ('149','157','141','142','143','144'),
    ('150','151','157','141','136'),
    ('118','117','119','150','151'),
    ('116','155','121','167'),
    ('164','166','165','111','101'),
    ('116','123','127','103'),
    ('149','157','158','148'),
]
OPS_END = [
    ('137','103','159','148','139','140'),
    ('167','155','121','139','140'),
    ('154','163','140'),
    ('159','124','140'),
]
EXTRA_DECOYS = ('撤回','到港','支援','收到','設備','修理','洪水','油料不足','暫停','火車','第四旅','司令','哨所','醫官','新消息','待核准')


def generate(seed: int, total: int=120) -> tuple[dict,dict]:
    if total < 120:
        raise ValueError('generate master corpus of >=100 telegrams')
    rng=random.Random(seed)
    # Vary the synthetic secret assignments across independent cases, not within.
    keys=sorted(CODEBOOK)
    permuted=keys[:]
    rng.shuffle(permuted)
    secret={permuted[i]:CODEBOOK[key] for i,key in enumerate(keys)}
    # The inverse must handle aliases; the same plaintext may have multiple codes.
    inv={}
    for code,term in secret.items(): inv.setdefault(term,[]).append(code)

    def codes(seq):
        return [rng.choice(inv[CODEBOOK[c]]) for c in seq]

    profiles=copy.deepcopy(PROFILES)
    for profile in profiles.values():
        profile['lexicon'].update({word:3 for word in LONG_TERMS.values()})
        profile['lexicon'].update({word:1 for word in EXTRA_DECOYS})
    # Fixed generic language patterns authored independently from the random
    # target telegram stream. No generated whole telegram is inserted in priors.
    profiles['logistics']['sentences'] += [
        ['補給','車隊','明日','準時出發'], ['道路','受阻','改行','北線'],
        ['糧秣','裝載','已畢'], ['預計','午夜','安全抵達','目的地'],
        ['請確認','收報後回電'], ['車輛','十二輛','已完成清點']
    ]
    profiles['operations']['sentences'] += [
        ['第二營','兵力','集結','備戰'], ['編隊','完成部署','警戒','陣地'],
        ['工兵','沿途','道路','受阻'], ['明晨','依原計畫','準時出發'],
        ['指揮所','待命','請速報位置'],
    ]
    messages=[]
    gold_messages={}
    used=set()
    for i in range(total):
        is_log = i % 2 == 0
        opens,mids,ends=(LOG_OPEN,LOG_MIDDLE,LOG_END) if is_log else (OPS_OPEN,OPS_MIDDLE,OPS_END)
        count_mids=2 if rng.random()<0.67 else 3
        # First 10 and 25 remain prefixes of the exact same 100-message stream.
        seq=[*rng.choice(opens)]
        for part in rng.sample(mids,count_mids): seq += list(part)
        seq+=list(rng.choice(ends))
        coded=codes(seq)
        used.update(coded)
        mid=f'S{seed}-{i+1:03d}'
        if is_log:
            sender,recipient=rng.choice([('後勤司令部','第二補給處'),('第二補給處','糧秣倉庫'),('前線補給分隊','後勤司令部')])
        else:
            sender,recipient=rng.choice([('軍司令部','第二營作戰室'),('第二營作戰室','前線作戰處'),('第二營作戰室','軍司令部')])
        m={'id':mid,'sender':sender,'recipient':recipient,
           'received_at':f'1942-05-{(i%28)+1:02d}T{(i*7)%24:02d}:00:00',
           'codes':coded}
        if i%5==0:
            # Independent, sometimes misleading synthetic observations. No oracle truth.
            m['observations']=[{
                'source':f'模擬第三方記錄-{i}', 'observed_at':f'1942-05-{(i%28)+1:02d}',
                'activity':'看到移動車輛' if i%10==0 else '人員進出',
                'destination':'補給倉庫' if i%3 else '作戰室',
                'status':'未確認關聯', 'confidence':0.35,
                'note':'與通信可能無關，不能當作已知明文'}]
        messages.append(m)
        gold_messages[mid]=''.join(CODEBOOK[c] for c in seq)
    training_messages = messages[:100]
    probe_messages = messages[100:]
    case={'case_id':f'single-codebook-synthetic-seed-{seed}',
          'description':'100 nested synthetic telegrams with one codebook; zero known plaintext; generic vocabulary priors are provided.',
          'codebook_assumptions':{'distinct_phrases':False},
          'profiles':profiles,'messages':training_messages,'known_pairs':[]}
    gold={'case_id':case['case_id'],'codebook':{c:secret[c] for c in sorted(used)},
          'messages':{m['id']:gold_messages[m['id']] for m in training_messages},
          'probe_messages':probe_messages}
    return case,gold


def main():
    HERE.mkdir(parents=True,exist_ok=True)
    meta={'version':1,'assumption':'same codebook for all 100 messages within each seed, code mapping varies between seeds',
          'sizes':list(COUNTS),'datasets':[]}
    for seed in SEEDS:
        case,gold=generate(seed)
        assert not case['known_pairs'] and not any(k in case for k in ('ground_truth','gold','codebook'))
        for num in COUNTS:
            subset={c for m in case['messages'][:num] for c in m['codes']}
            assert subset.issubset(gold['codebook'])
        (HERE/f'seed_{seed}_case.json').write_text(json.dumps(case,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        (HERE/f'seed_{seed}_gold.json').write_text(json.dumps(gold,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        meta['datasets'].append({'seed':seed,'case':f'seed_{seed}_case.json','gold':f'seed_{seed}_gold.json'})
    (HERE/'manifest.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Generated nested single-codebook datasets for seeds',SEEDS,'sizes',COUNTS)

if __name__=='__main__':main()
