"""Build the public Vercel synthetic PoC; deterministic MOCK only, never contact an LLM.

IMPORTANT: secret benchmark gold is opened strictly AFTER the mock and baseline analyses
have completed. gold.json is public *demo-only* material and must not be used to
judge a blinded cryptanalytic experiment.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from han_codebook.core import analyze

INPUT = ROOT / 'benchmarks/volume/seed_101_case.json'
GOLD = ROOT / 'benchmarks/volume/seed_101_gold.json'
OUT = ROOT / 'vercel-demo/data'
SIZES = (10, 25, 50, 100)
BATCH = 25


def build():
    case = json.loads(INPUT.read_text(encoding='utf-8'))
    assert len(case['messages']) == 100 and not case.get('known_pairs')
    records = []
    for n in SIZES:
        msgs = case['messages'][:n]
        subset = {**case, 'messages': msgs, 'known_pairs': []}
        statistical = analyze(subset, use_metadata=True, iterations=2, restarts=2, seed=7)
        frequencies = Counter(c for m in msgs for c in m['codes'])
        hints = {}
        trace = []
        for start in range(0, n, BATCH):
            batch = msgs[start:start + BATCH]
            codes = Counter(c for m in batch for c in m['codes'])
            accepted = []
            for code, count in sorted(codes.items(), key=lambda kv: (-kv[1], kv[0]))[:15]:
                alts = [a['term'] for a in statistical['proposals'][code]['alternatives']]
                if not alts:
                    continue
                # Simulated, fallible, reproducible language suggestions derived ONLY from
                # the solver's candidate ranking and observable cipher frequencies.
                guess = alts[1] if len(alts) > 1 and (int(code) + start) % 3 == 0 else alts[0]
                second = next((term for term in alts if term != guess), None)
                candidates = [guess] + ([second] if second else [])
                for rank, word in enumerate(candidates):
                    hints.setdefault(code, {})[word] = min(0.6, hints.get(code, {}).get(word, 0) + 0.25/(rank+1))
                accepted.append({'code': code, 'candidates': candidates,
                    'reason': f'MOCK：碼組 {code} 在本批出現 {count} 次、累計出現 {frequencies[code]} 次；此建議僅模擬從候選排名與共現模式進行推測，並非真正模型推理。'})
            trace.append({'batch': len(trace) + 1, 'first': start+1,
                          'last': min(start + BATCH, n), 'accepted': accepted})
        mocked = analyze(subset, use_metadata=True, llm_hints=hints, iterations=2, restarts=2, seed=7)
        def minimize(result):
            return {code: {'term': p['term'], 'alternatives': [x['term'] for x in p['alternatives'][:5]],
                           'score_gap': p.get('score_gap_to_second',0)} for code,p in result['proposals'].items()}
        records.append({'size': n, 'messages': [
            {k: m[k] for k in ('id','codes','received_at','sender','recipient','observations') if k in m}
            for m in msgs], 'statistical': minimize(statistical), 'mock': minimize(mocked),
            'trace': trace})
    # GOLD is not opened by solver or MOCK producer above, only used for display grading.
    gold = json.loads(GOLD.read_text(encoding='utf-8'))
    observed = sorted({c for r in records for m in r['messages'] for c in m['codes']})
    assert all(c in gold['codebook'] for c in observed)
    for r in records:
        codes = list(r['statistical'])
        r['metrics'] = {key: {
            'correct': sum(p[c]['term'] == gold['codebook'][c] for c in codes), 'total': len(codes)}
            for key, p in [('statistical',r['statistical']),('mock',r['mock'])]}
    payload = {'kind':'PUBLIC_SYNTHETIC_MOCK','llm_used': False,'seed':101,
               'description':'Static PoC; actual Python solver statistical snapshots + deterministic MOCK suggestions (never an LLM request)',
               'sizes': list(SIZES), 'records': records}
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'demo.json').write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
    # Gold is a separate asset fetched only by an explicit user action; public and synthetic.
    (OUT/'gold.json').write_text(json.dumps({'kind':'PUBLIC_SYNTHETIC_GOLD','codebook':gold['codebook'],
           'messages':gold['messages']},ensure_ascii=False,separators=(',',':'))+'\n',encoding='utf-8')
    for r in records:
        print(f"[demo] {r['size']} telegrams, {len(r['statistical'])} code groups, mock {len(r['trace'])} batches; "
              f"baseline {r['metrics']['statistical']['correct']}/{r['metrics']['statistical']['total']}, "
              f"mock {r['metrics']['mock']['correct']}/{r['metrics']['mock']['total']}")
    return payload

if __name__=='__main__':build()
