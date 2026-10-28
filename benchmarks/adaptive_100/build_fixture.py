"""Regenerate the previously revealed adaptive 100-message synthetic benchmark.

Not a real codebook; fixed seed and templates are public after publication.
The reference key is output ONLY under benchmarks/adaptive_100/reference/, never Vercel.
"""
from __future__ import annotations
import json, random, argparse
from pathlib import Path
from datetime import date, timedelta

def build(folder: Path):
    rng=random.Random(202610282334)
    groups={
      'unit':['軍司令部','後勤司令部','第二營','偵察排','工兵連','衛生隊','通信站','前線補給分隊'],
      'action':['命令','報告','確認','要求','準備','開始','完成','暫停','調整','延後'],
      'object':['車隊','補給','燃料','彈藥','糧秣','道路','橋梁','陣地','人員','傷員','電台','文件'],
      'place':['北線','南線','東側','西側','前線','倉庫','集結地','補給站'],
      'time':['今夜','明晨','午前','傍晚','兩小時內','入夜後'],
      'status':['安全','受阻','不足','已抵達','請回電','優先','立即','緊急','暫時','持續'],
      'other':['轉運','修復','警戒','撤離','接應','盤點']
    }
    assert sum(map(len,groups.values()))==60
    words=[w for a in groups.values() for w in a]
    codes=[str(i) for i in rng.sample(range(400,999),60)]
    codec=dict(zip(words,codes))
    units=groups['unit'];objects=groups['object'];places=groups['place']
    times=groups['time'];actions=groups['action'];statuses=groups['status'];other=groups['other']
    messages=[]
    for i in range(100):
        when=date(1942,5,1)+timedelta(days=i//3)
        actor=rng.choices(units,weights=[20,18,18,9,8,7,7,13])[0]
        action=rng.choices(actions,weights=[8,17,11,12,10,10,11,6,9,6])[0]
        obj=rng.choice(objects);loc=rng.choice(places)
        tm=rng.choice(times);status=rng.choice(statuses)
        terms=[actor,action,obj,loc,tm,status]
        if i%2==0:
            terms+=[rng.choice(other),rng.choice(objects),rng.choice(places)]
        if i%3==0:
            terms+=[rng.choice(actions),rng.choice(objects),rng.choice(statuses)]
        sender=actor if rng.random()<.83 else rng.choice(units)
        recipient=rng.choice([u for u in units if u!=sender])
        ob=[]
        if i%3==0:
            matched=rng.random()<.8
            observed_obj=obj if matched else rng.choice(objects)
            observed_loc=loc if matched else rng.choice(places)
            ob.append({'source':'外部觀察-'+str(i%7),'observed_at':str(when),
              'activity':f'看見{observed_obj}活動','location':observed_loc,
              'confidence':0.75 if matched else 0.25,'status':'關聯待證實'})
        messages.append({'id':f'N-{i+1:03}','codes':[codec[t] for t in terms],
          'sent_at':str(when),'sender':sender,'recipient':recipient,'observations':ob})
    gold={'code_to_word':{v:k for k,v in codec.items()},'groups':groups,
       'messages_words':{m['id']:[next(w for w,c in codec.items() if c==k)
                               for k in m['codes']] for m in messages}}
    public={'study':'new independent synthetic benchmark',
      'notes':'60 hidden randomly assigned cipher codes; sender may be noisy; observations are suggestive, not verified',
      'messages':messages,
      'fixed_vocab':['今夜','令','依原計畫','倉庫','備戰','兵力','前線','報告','增援','奉令','工兵','已畢','抵達','明日','準時出發','第二營','糧秣','補給','補給處','裝載','調整','路線','車隊','軍司令部','運抵','集結','需要']}
    (folder/'reference').mkdir(parents=True,exist_ok=True)
    (folder/'han_adaptive_new_public.json').write_text(json.dumps(public,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'reference'/'han_adaptive_new_gold_PRIVATE.json').write_text(json.dumps(gold,ensure_ascii=False,indent=2),encoding='utf-8')
    assert sum(map(lambda m:len(m['codes']),messages))==852
    assert sum(len(m['observations']) for m in messages)==34
    return folder

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args();build(args.output_dir)
