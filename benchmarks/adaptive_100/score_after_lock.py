"""Offline scoring key use, never imported by run_no_gold or Vercel.

Keeps the reference mapping outside the browser-served vercel-demo tree.
"""
from __future__ import annotations
import argparse, collections,csv,hashlib,json
from pathlib import Path

def evaluate(base:Path):
    public=json.loads((base/'han_adaptive_new_public.json').read_text(encoding='utf-8'))
    locked=json.loads((base/'han_adaptive_new_predictions_LOCKED.json').read_text(encoding='utf-8'))
    noaux=json.loads((base/'han_adaptive_no_aux_LOCKED.json').read_text(encoding='utf-8'))
    gold=json.loads((base/'reference'/'han_adaptive_new_gold_PRIVATE.json').read_text(encoding='utf-8'))
    truth=gold['code_to_word']
    freq=collections.Counter(c for m in public['messages'] for c in m['codes'])
    assert len(truth)==60 and sum(freq.values())==852 and len(public['messages'])==100
    def summary(stage,map_,vocab):
        hit=[c for c in truth if map_[c]==truth[c]]
        return {'stage':stage,'candidate_count':len(vocab),'candidate_coverage_types':sum(w in vocab for w in truth.values()),
          'known_types':60,'decoded_types':sum(w!='[未解]' for w in map_.values()),
          'correct_types':len(hit),'type_acc_pct':round(100*len(hit)/60,2),
          'correct_positions':sum(freq[c] for c in hit),'n_positions':852,
          'position_acc_pct':round(100*sum(freq[c] for c in hit)/852,2),
          'complete_messages':sum(all(map_[c]==truth[c] for c in m['codes']) for m in public['messages']),
          'n_messages':100,'correct_codes':{c:truth[c] for c in sorted(hit)}}
    metrics=[summary(r['stage'],r['predictions'],set(r['vocabulary'])) for r in locked['rounds']]
    metrics.append(summary('dynamic_full_no_aux',noaux['predictions'],set(locked['rounds'][-1]['vocabulary'])))
    assert [(x['correct_types'],x['correct_positions'],x['complete_messages']) for x in metrics]==[
       (8,156,0),(28,444,0),(31,470,0),(4,50,0)]
    rows=[]
    for code in sorted(truth):
        rows.append({'code':code,'n_occurrences':freq[code],'true_word':truth[code],
           'fixed_guess':locked['rounds'][0]['predictions'][code],
           'after_observations':locked['rounds'][1]['predictions'][code],
           'after_dynamic_round3':locked['rounds'][2]['predictions'][code],
           'no_aux_guess':noaux['predictions'][code],
           'fixed_correct':int(locked['rounds'][0]['predictions'][code]==truth[code]),
           'dynamic_correct':int(locked['rounds'][2]['predictions'][code]==truth[code])})
    with (base/'han_adaptive_new_code_comparison.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    (base/'han_adaptive_new_metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2),encoding='utf-8')
    return metrics

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data-dir',type=Path,required=True)
    args=p.parse_args();print(json.dumps(evaluate(args.data_dir),ensure_ascii=False)[:600])
