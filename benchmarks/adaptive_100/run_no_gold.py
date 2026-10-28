"""Deterministic no-gold role-aware reassignment; original study logic.

This does NOT use a ChatGPT API or train on the reference key; it benefits from
known synthetic 6-slot grammar and hand-proposed vocabulary.
"""
from __future__ import annotations
import argparse, json, hashlib, collections
from pathlib import Path
import numpy as np
from scipy.optimize import linear_sum_assignment

category={
 'unit':['軍司令部','後勤司令部','第二營','偵察排','工兵連','衛生隊','通信站','前線補給分隊','補給處'],
 'action':['報告','調整','令','奉令','命令','確認','要求','準備','開始','完成','暫停','延後'],
 'object':['車隊','補給','燃料','彈藥','糧秣','道路','橋梁','陣地','人員','傷員','電台','文件','兵力','裝載'],
 'place':['北線','南線','東側','西側','前線','倉庫','集結地','補給站','路線'],
 'time':['今夜','明晨','午前','傍晚','兩小時內','入夜後','明日'],
 'status':['安全','受阻','不足','已抵達','請回電','優先','立即','緊急','暫時','持續','需要','抵達','已畢','準時出發'],
 'other':['轉運','修復','警戒','撤離','接應','盤點','運抵','集結','增援','備戰']}
position={0:'unit',1:'action',2:'object',3:'place',4:'time',5:'status'}
priors={
'unit':['軍司令部','第二營','後勤司令部','前線補給分隊','工兵連','偵察排','通信站','衛生隊','補給處'],
'action':['報告','要求','命令','完成','開始','準備','確認','調整','暫停','延後','奉令','令'],
'object':['車隊','燃料','補給','彈藥','糧秣','道路','橋梁','陣地','人員','傷員','電台','文件','兵力','裝載'],
'place':['北線','南線','前線','倉庫','西側','集結地','東側','補給站','路線'],
'time':['今夜','明晨','午前','入夜後','傍晚','兩小時內','明日'],
'status':['安全','立即','已抵達','緊急','受阻','不足','持續','優先','暫時','請回電','需要','抵達','已畢','準時出發'],
'other':['轉運','警戒','接應','修復','撤離','盤點','增援','集結','運抵','備戰']}

def infer(public,*,use_aux=True):
    messages=public['messages'];fixed=set(public['fixed_vocab'])
    roles={role:set(m['codes'][i] for m in messages) for i,role in position.items()}
    codes=set(c for m in messages for c in m['codes'])
    roles['other']=codes-set.union(*roles.values())
    assert len(codes)==60 and len(roles['other'])==6
    freq=collections.Counter(c for m in messages for c in m['codes'])
    obj=collections.defaultdict(collections.Counter)
    loc=collections.defaultdict(collections.Counter)
    sender=collections.defaultdict(collections.Counter)
    for m in messages:
        if use_aux:
            sender[m['codes'][0]][m['sender']]+=1
            for o in m['observations']:
                obj[m['codes'][2]][o['activity'].removeprefix('看見').removesuffix('活動')]+=o['confidence']
                loc[m['codes'][3]][o['location']]+=o['confidence']
    observed=set(m['sender'] for m in messages)|set(m['recipient'] for m in messages)
    for m in messages:
        for o in m['observations']:
            observed.add(o['activity'].removeprefix('看見').removesuffix('活動'))
            observed.add(o['location'])
    r2=sorted(observed-fixed)
    brainstorm=['命令','確認','要求','準備','開始','完成','暫停','延後','明晨','午前','傍晚',
      '兩小時內','入夜後','安全','受阻','不足','已抵達','請回電','優先','立即','緊急',
      '暫時','持續','轉運','修復','警戒','撤離','接應','盤點']
    r3=sorted(set(brainstorm)-fixed-set(r2))
    def solve(vocab):
        result={}
        for role,code_set in roles.items():
            typed=sorted(code_set,key=lambda c:(-freq[c],c))
            words=[w for w in priors[role] if w in vocab]
            m=np.full((len(typed),len(words)+len(typed)),-100.,float)
            for i,c in enumerate(typed):
                for k,w in enumerate(words):
                    rank=priors[role].index(w)
                    if role=='unit':
                        score=sender[c][w]*5.-1.4
                    elif role=='object':
                        score=obj[c][w]*5.-1.4
                    elif role=='place':
                        score=loc[c][w]*5.-1.4
                    else:
                        score=2.-.75*abs(i-rank)
                    m[i,k]=score+1e-6*(len(words)-k)
                m[i,len(words)+i]=0
            row,col=linear_sum_assignment(-m)
            for i,k in zip(row,col):
                result[typed[i]]=words[k] if k<len(words) and m[i,k]>0 else '[未解]'
        assert set(result)==codes
        return result
    rounds=[]
    for name,vocab in [('fixed_lexicon',fixed),
                       ('dynamic_metadata_observations',fixed|set(r2)),
                       ('dynamic_context_terms',fixed|set(r2)|set(r3))]:
        if use_aux or name=='dynamic_context_terms':
            m=solve(vocab)
            rounds.append({'stage':name,'vocabulary':sorted(vocab),
                'predictions':m,'decoded_n':sum(w!='[未解]' for w in m.values())})
    locked={'study':'NEW shuffled mapping blind trial; code-to-word mapping withheld',
      'messages':len(messages),'known_code_types':len(codes),'fixed_lexicon':sorted(fixed),
      'round2_new_terms':r2,'round3_new_terms':r3,
      'method':'GPT-6 proposed public-evidence + language-role candidates; deterministic one-to-one solver',
      'rounds':rounds,
      'notes':'The generator uses compositional template positions; GPT-6 did NOT make API calls per round; not suitable as real historical decoding evidence.'}
    return locked

def run(base):
    public=json.loads((base/'han_adaptive_new_public.json').read_text(encoding='utf-8'))
    locked=infer(public,use_aux=True)
    no_aux=infer(public,use_aux=False)
    (base/'han_adaptive_new_predictions_LOCKED.json').write_text(
       json.dumps(locked,ensure_ascii=False,sort_keys=True,indent=2),encoding='utf-8')
    (base/'han_adaptive_no_aux_LOCKED.json').write_text(
       json.dumps({'stage':'dynamic_full_no_aux',
        'predictions':no_aux['rounds'][-1]['predictions']},ensure_ascii=False,sort_keys=True,indent=2),encoding='utf-8')
    assert len(locked['rounds'])==3
    assert [len(x['vocabulary']) for x in locked['rounds']]==[27,48,77]
    return locked

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data-dir',type=Path,required=True)
    args=p.parse_args();run(args.data_dir)
