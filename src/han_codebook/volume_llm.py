"""Explicit opt-in LAN LLM vs statistical baseline on nested single-codebook corpora.

All 100 training telegrams are supplied to the LLM once per round in non-overlapping
batches; no inference/evidence object contains secret benchmark gold or probe texts.
Unknown terms remain hypotheses and never become verified anchors.
"""
from __future__ import annotations

import argparse
from collections import Counter
from html import escape
import json
from pathlib import Path
from statistics import mean
import sys
import time
import threading
from typing import Any, Callable

from .agent import query_local_llm, validate_llm_endpoint
from .benchmark import score_result
from .config import load_settings
from .core import CaseError, analyze, anchors_and_review, validate_case
from .volume import MANIFEST, load_manifest, probe_metrics
from .volume_decode_view import build_decoding_view, attach_evaluation_gold, explorer_html
from .auto_vocabulary import generate_vocabulary, case_from_vocabulary_record
from .llm_evidence import safe_llm_message


class LLMStudyInterrupted(CaseError):
    """Incomplete LLM study; contains only collected audit and already-scored runs."""
    def __init__(self, message: str, *, trace: list[dict] | None = None, calls: int = 0):
        super().__init__(message)
        self.trace = trace or []
        self.calls = calls
        self.partial_report: dict = {}


def _input_messages(batch: list[dict], *, metadata: bool) -> list[dict]:
    # Reuse the exact nested-field whitelist used by cold-start vocabulary requests.
    return [safe_llm_message(message, metadata=metadata) for message in batch]


def llm_rescore(case: dict, baseline: dict, *, metadata: bool, llm_settings: dict,
                rounds: int = 1, batch_size: int = 25, iterations: int = 2,
                restarts: int = 2, capture_io: bool = False,
                progress: Callable[[str], None] = print,
                query: Callable[..., dict] = query_local_llm) -> tuple[dict, list[dict], int]:
    """Send complete corpus, in disjoint bounded batches, then rescore all messages.

    Inject `query` for offline/mocked tests. No oracle and no hidden gold access.
    """
    if not 1 <= rounds <= 5:
        raise CaseError('LLM rounds must be 1..5')
    if not 1 <= batch_size <= 50:
        raise CaseError('LLM batch size must be 1..50')
    validate_case(case)
    if case.get('known_pairs') or any(k in case for k in ('ground_truth', 'gold', 'codebook')):
        raise CaseError('LLM volume experiment requires zero known plaintext and no oracle data')
    url = llm_settings['base_url']
    model = llm_settings['model']
    validate_llm_endpoint(url, allow_private_network=llm_settings.get('allow_private_network', False),
                          allowed_hosts=llm_settings.get('allowed_hosts', []))
    _, _, vocabulary = anchors_and_review(case)
    hints: dict[str, dict[str, float]] = {}
    all_messages = case['messages']
    trace: list[dict] = []
    calls = 0
    result = baseline
    for step in range(1, rounds + 1):
        for offset in range(0, len(all_messages), batch_size):
            raw_batch = all_messages[offset:offset + batch_size]
            batch_codes = {c for m in raw_batch for c in m['codes']}
            unresolved = {
                c: {'current_guess': result['proposals'][c]['term'],
                    'alternatives': [v['term'] for v in result['proposals'][c]['alternatives'][:5]]}
                for c in sorted(batch_codes)
                if c in result['proposals'] and result['proposals'][c]['status'] == 'hypothesis_unverified'
            }
            if not unresolved:
                continue
            packet = {
                'policy': 'Propose only unverified hypotheses within available_vocabulary; no decoding oracle or verified plaintext exists.',
                'verified_anchors': {},
                'available_vocabulary': sorted(vocabulary),
                'profiles': ({k: {'keywords': p.get('keywords', []), 'lexicon': p.get('lexicon', {})}
                              for k, p in case['profiles'].items()} if metadata else {}),
                'messages': _input_messages(raw_batch, metadata=metadata),
                'unresolved': unresolved,
                'batch': {'round': step, 'start': offset + 1, 'end': offset + len(raw_batch),
                          'total_messages': len(all_messages)},
            }
            progress(f'[LLM] Round {step}/{rounds} messages {offset+1}-{offset+len(raw_batch)}/{len(all_messages)} '
                     f'({len(unresolved)} candidate codes) -> {model}',)
            record: dict[str, Any] = {'round': step, 'start': offset + 1,
                                      'end': offset + len(raw_batch), 'messages': len(raw_batch)}
            if capture_io:
                record['exchanges'] = []
                def on_exchange(stage: str, payload: dict) -> None:
                    record['exchanges'].append({'stage': stage, **payload})
            else:
                on_exchange = None
            started = time.monotonic()
            attempt_finished = False
            finished = threading.Event()
            def heartbeat() -> None:
                while not finished.wait(10):
                    progress(f'[LLM] Round {step}/{rounds} messages {offset+1}-{offset+len(raw_batch)}: '
                             f'still waiting ({time.monotonic()-started:.0f}s elapsed) ...')
            worker = threading.Thread(target=heartbeat, daemon=True)
            worker.start()
            try:
                # query_local_llm's request/response capture never includes authorization headers.
                reply = query(url, model, packet, timeout=llm_settings.get('timeout_seconds', 90),
                              allow_private_network=llm_settings.get('allow_private_network', False),
                              allowed_hosts=llm_settings.get('allowed_hosts', []),
                              api_key_env=llm_settings.get('api_key_env'), on_exchange=on_exchange)
                calls += 1
                attempt_finished = True
                entries = reply.get('hypotheses')
                if not isinstance(entries, list):
                    raise CaseError('LLM reply has no hypotheses array')
                accepted = []
                rejected = 0
                seen_codes: set[str] = set()
                for item in entries[:15]:
                    if not isinstance(item, dict) or item.get('code') not in unresolved or not isinstance(item.get('candidates'), list):
                        rejected += 1
                        continue
                    code = item['code']
                    if code in seen_codes:
                        rejected += 1  # Same API response does not constitute new evidence.
                        continue
                    words: list[str] = []
                    for word in item['candidates']:
                        if isinstance(word, str) and word in vocabulary and word not in words:
                            words.append(word)
                        if len(words) == 5:
                            break
                    if not words:
                        rejected += 1
                        continue
                    seen_codes.add(code)
                    for rank, word in enumerate(words):
                        hints.setdefault(code, {})[word] = min(0.6, hints.get(code, {}).get(word, 0.0) + 0.25/(rank+1))
                    accepted.append({'code': code, 'candidates': words, 'reason': str(item.get('reason',''))[:250]})
                record.update({'status':'completed', 'seconds': round(time.monotonic()-started, 3),
                               'accepted': accepted, 'rejected': rejected})
                trace.append(record)
            except Exception as exc:
                record.update({'status':'failed', 'seconds':round(time.monotonic()-started,3),
                               'error_type':type(exc).__name__, 'error_summary':str(exc)[:300]})
                trace.append(record)  # Include captured request/error response if explicitly opted in.
                raise LLMStudyInterrupted(
                    f'LLM batch {offset+1}-{offset+len(raw_batch)} failed: {type(exc).__name__}',
                    trace=trace, calls=calls + int(not attempt_finished)) from exc
            finally:
                finished.set()
                worker.join(timeout=1)
            progress(f'[LLM] Response {record["seconds"]:.1f}s; accepted {len(accepted)}, rejected {rejected}; '
                     f'{calls} call(s) so far')
        result = analyze(case, use_metadata=metadata, llm_hints=hints,
                         iterations=iterations, restarts=restarts, seed=7)
        progress(f'[LLM] Round {step}/{rounds} rescored all {len(all_messages)} messages; '
                 f'updated hypotheses for {len(hints)} codes')
    return result, trace, calls


def run_llm_comparison(manifest_path: str | Path = MANIFEST, *, sizes: tuple[int,...]=(10,25,50,100),
                       seeds: tuple[int,...]=(101,), metadata: bool = True,
                       llm_config: str | Path = 'config.yaml', rounds: int = 1,
                       batch_size: int = 25, iterations: int = 2, restarts: int = 2,
                       capture_io: bool = False, auto_vocabulary: bool = False,
                       progress: Callable[[str],None] = print,
                       query: Callable[...,dict] = query_local_llm) -> dict:
    if not sizes or tuple(sorted(set(sizes))) != sizes or any(x < 1 or x > 100 for x in sizes):
        raise CaseError('sizes must be ascending unique values from 1 to 100')
    if iterations < 1 or restarts < 1:
        raise CaseError('solver budget must be positive')
    config = load_settings(llm_config)['llm']
    if not {'base_url','model'} <= set(config):
        raise CaseError('LLM config must provide llm.base_url and llm.model')
    validate_llm_endpoint(config['base_url'], allow_private_network=config.get('allow_private_network',False),
                          allowed_hosts=config.get('allowed_hosts', []))
    spec, home = load_manifest(manifest_path)
    rows = []
    audit = []
    decoding_views = []
    for item in spec['datasets']:
        seed = int(item['seed'])
        if seed not in seeds:
            continue
        case = json.loads((home/item['case']).read_text(encoding='utf-8'))
        if case.get('known_pairs') or any(k in case for k in ('gold','ground_truth','codebook')):
            raise CaseError('case contains oracle data or initial plaintext')
        validate_case(case)
        if len(case['messages']) != 100:
            raise CaseError('each corpus must contain exactly 100 nested training messages')
        first_codes = {c for m in case['messages'][:sizes[0]] for c in m['codes']}
        for size in sizes:
            subset = {**case, 'case_id': f'{case["case_id"]}-n{size}', 'messages': case['messages'][:size]}
            vocab_record = None
            if auto_vocabulary:
                try:
                    subset,vocab_record = generate_vocabulary(
                        subset, metadata=metadata, llm_settings=config,
                        capture_io=capture_io,progress=progress,query=query)
                except Exception as exc:
                    # Raw LLM exchange is kept only when expressly opted into capture.
                    trace_record = getattr(exc,'vocabulary_record',
                                           {'task':'generate_vocabulary','status':'failed'})
                    interrupted = LLMStudyInterrupted('LLM vocabulary generation failed',
                                                      trace=[trace_record],calls=1)
                    interrupted.partial_report = {
                        'status':'failed', 'model':config['model'],
                        'failed_seed':seed, 'failed_messages':size,
                        'error':str(exc), 'completed_runs':rows,
                        'trace':audit + [{'seed':seed,'messages':size,'status':'failed',
                                           'trace':[trace_record]}],
                        'capture_llm_io':capture_io,
                        'note':'No scores for a failed vocabulary generation.',
                    }
                    raise interrupted from exc
            progress(f'[study] seed={seed} messages={size} metadata={metadata}: '
                     + ('LLM-generated-vocabulary baseline' if auto_vocabulary else 'offline baseline'))
            start = time.monotonic()
            baseline = analyze(subset, use_metadata=metadata, iterations=iterations,
                               restarts=restarts, seed=7)
            baseline_seconds = time.monotonic()-start
            start = time.monotonic()
            try:
                proposal, trace, calls = llm_rescore(subset, baseline, metadata=metadata,
                                llm_settings=config, rounds=rounds, batch_size=batch_size,
                                iterations=iterations, restarts=restarts, capture_io=capture_io,
                                progress=progress, query=query)
            except LLMStudyInterrupted as exc:
                exc.partial_report = {
                    'status':'failed', 'model':config['model'],
                    'failed_seed':seed, 'failed_messages':size,
                    'error':str(exc), 'completed_runs':rows,
                    'trace':audit + [{'seed':seed, 'messages':size, 'status':'failed',
                                      'trace':([vocab_record] if vocab_record else [])+exc.trace}],
                    'capture_llm_io':capture_io,
                    'note':'Analysis interrupted. No score was assigned to the failed run.',
                }
                raise
            # Capture guesses BEFORE looking at the secret gold: no oracle-derived text in viewer.
            pending_view=build_decoding_view(subset,baseline,proposal,seed=seed,size=size,trace=trace)
            llm_seconds = time.monotonic()-start
            # Gold is opened only AFTER both inference paths return. Never give gold to LLM.
            gold = json.loads((home/item['gold']).read_text(encoding='utf-8'))
            if len(gold.get('probe_messages', [])) != 20:
                raise CaseError('missing independent 20-message probe')
            if {m['id'] for m in subset['messages']} & {m['id'] for m in gold['probe_messages']}:
                raise CaseError('probe message leaked into inference subset')
            b = score_result(baseline, gold, subset)
            p = score_result(proposal, gold, subset)
            decoding_views.append(attach_evaluation_gold(pending_view,gold))
            bp = probe_metrics(baseline['proposals'],gold)
            pp = probe_metrics(proposal['proposals'],gold)
            fixed10 = lambda result: sum(result['proposals'][c]['term']==gold['codebook'][c]
                                          for c in first_codes if c in result['proposals']) / len(first_codes)
            changed = sorted(c for c in proposal['proposals']
                             if baseline['proposals'][c]['term'] != proposal['proposals'][c]['term'])
            vocab_coverage = (len({word for word in gold['codebook'].values()
                                   if word in subset['profiles']['llm_generated_background']['lexicon']})
                              / max(1,len(set(gold['codebook'].values())))) if auto_vocabulary else None
            row = {'seed':seed, 'messages':size, 'metadata':metadata, 'one_codebook':True,
                   'auto_vocabulary':auto_vocabulary,
                   'candidate_count':len(subset['profiles']['llm_generated_background']['lexicon']) if auto_vocabulary else None,
                   'generated_vocabulary_gold_term_coverage':round(vocab_coverage,4) if vocab_coverage is not None else None,
                   'initial_known_plaintext_pairs':0, 'model':config['model'], 'rounds':rounds,
                   'batch_size':batch_size, 'llm_calls':calls + int(auto_vocabulary), 'accepted_llm_hypotheses':sum(len(t['accepted']) for t in trace),
                   'distinct_codes_observed':len(proposal['proposals']),
                   'stat_top1':b['unknown_code_top1_rate'], 'llm_top1':p['unknown_code_top1_rate'],
                   'stat_top5':b['unknown_code_top5_rate'], 'llm_top5':p['unknown_code_top5_rate'],
                   'stat_fixed_first_codes':round(fixed10(baseline),4),
                   'llm_fixed_first_codes':round(fixed10(proposal),4),
                   'stat_probe_top1':bp['probe_top1_rate_all_groups'],
                   'llm_probe_top1':pp['probe_top1_rate_all_groups'],
                   'stat_probe_coverage':bp['probe_coverage_rate'],
                   'llm_probe_coverage':pp['probe_coverage_rate'],
                   'changed_codes':len(changed),
                   'stat_corrected_by_llm':sum(baseline['proposals'][c]['term'] != gold['codebook'][c] and proposal['proposals'][c]['term'] == gold['codebook'][c] for c in changed),
                   'stat_broken_by_llm':sum(baseline['proposals'][c]['term'] == gold['codebook'][c] and proposal['proposals'][c]['term'] != gold['codebook'][c] for c in changed),
                   'stat_elapsed_seconds':round(baseline_seconds,3),
                   'llm_elapsed_seconds':round(llm_seconds,3)}
            rows.append(row)
            audit.append({'seed':seed,'messages':size,
                          'trace':([vocab_record] if vocab_record else []) + trace})
            progress(f'[result] {size} messages: statistics={row["stat_top1"]:.1%}, LLM={row["llm_top1"]:.1%}; '
                     f'probe statistics={row["stat_probe_top1"]:.1%}, LLM={row["llm_probe_top1"]:.1%}; calls={calls}')
    if not rows:
        raise CaseError('none of the requested seed IDs exist')
    return {'title':'Single-codebook nested ciphertext volume: statistical vs local LLM',
            'data_status':'synthetic; not historical decryption evidence',
            'llm_used':True, 'mode':'local-llm-dictionary-constrained-ranking',
            'model':config['model'], 'llm_base_url':config['base_url'],
            'source_manifest':str(Path(manifest_path).resolve()),
            'metadata':metadata,'rounds':rounds,'batch_size':batch_size,
            'capture_llm_io':capture_io,'auto_vocabulary':auto_vocabulary,'fixed_codebook_per_seed':True,
            'zero_known_plaintext':True,'fixed_candidate_vocabulary_includes_gold_terms':not auto_vocabulary,
            'oracle_access':'after inference only', 'llm_call_total':sum(x['llm_calls'] for x in rows),
            'runs':rows,'trace':audit,'decoding_views':decoding_views}


def as_markdown(result: dict) -> str:
    lines = ['# 固定單一碼本：統計 vs 內網 LLM（合成密電研究）','',
             f'> 模型：`{result["model"]}`；每批最多 {result["batch_size"]} 封，{result["rounds"]} 輪，'+
             '0 個已知明文對照。所有封數皆供模型分析，不只取前 50 封。','',
             '| Seed | 封數 | 純統計 Top-1 | LLM Top-1 | 統計探針 | LLM 探針 | LLM 修正／改錯 | 模型請求數 |',
             '|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in result['runs']:
        lines.append(f'| {r["seed"]} | {r["messages"]} | {r["stat_top1"]:.1%} | {r["llm_top1"]:.1%} | '
                     f'{r["stat_probe_top1"]:.1%} | {r["llm_probe_top1"]:.1%} | '
                     f'{r["stat_corrected_by_llm"]} / {r["stat_broken_by_llm"]} | {r["llm_calls"]} |')
    lines += ['',f'- 模型呼叫總數：{result["llm_call_total"]}；資料來源為合成題庫。',
              ('- 此模式由 LLM 根據密文統計及輔助情報產生候選詞庫；不輸入案例預設詞庫。'
              if result.get('auto_vocabulary') else '- 固定詞庫包含正確候選詞，因此仍不是沒有先驗詞庫的純密文破解。'),
              '- 這不是完整自主的研究 Agent；LLM 只提出詞庫內候選，統計求解器再重新排序。',
              '- 真實內網實測成績以本次執行所生成的 JSON 為準；不要把模擬 API 測試當成模型能力。','']
    return '\n'.join(lines)


def as_html(result: dict) -> str:
    rows = result['runs']
    width=860
    xvals=sorted({v['messages'] for v in rows})
    left,right=60,800
    def x(n): return left+(n-min(xvals))/(max(xvals)-min(xvals) or 1)*(right-left)
    def y(p): return 245-195*p
    plots=[]
    for field,color,label in [('stat_top1','#3179b8','純統計'),('llm_top1','#c06d23','內網 LLM')]:
        s=sorted(rows,key=lambda a:(a['seed'],a['messages']))
        for seed in sorted({r['seed'] for r in rows}):
            points=[r for r in s if r['seed']==seed]
            pts=' '.join(f'{x(r["messages"]):.0f},{y(r[field]):.0f}' for r in points)
            plots.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" stroke-opacity=".7" points="{pts}" />')
            for r in points:
                plots.append(f'<circle cx="{x(r["messages"]):.0f}" cy="{y(r[field]):.0f}" r="4" fill="{color}"><title>seed {seed}, {r["messages"]}封 {label} {r[field]:.1%}</title></circle>')
    ticks=''.join(f'<text x="{x(i):.0f}" y="267" text-anchor="middle" font-size="13">{i}封</text>' for i in xvals)
    yticks=''.join(f'<text x="48" y="{y(i/4):.0f}" text-anchor="end" font-size="13">{i*25}%</text>' for i in range(5))
    table=''.join('<tr>'+''.join(f'<td>{escape(str(r[k]))}</td>' for k in
        ['seed','messages','stat_top1','llm_top1','stat_probe_top1','llm_probe_top1',
         'stat_corrected_by_llm','stat_broken_by_llm','llm_calls','llm_elapsed_seconds'])+'</tr>' for r in rows)
    html = ('<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>統計 vs 內網 LLM：單一碼本密文量實驗</title><style>body{font-family:system-ui,sans-serif;max-width:1100px;padding:20px;margin:auto;color:#182a3b;background:#fafbff}svg{max-width:100%;border:1px solid #ccd6df;border-radius:10px;background:white}table{border-collapse:collapse;width:100%;background:white}th,td{border:1px solid #cdd4db;padding:7px;text-align:right}th{background:#ecf2f8}.scroll{overflow:auto}p{line-height:1.7}</style>'
            '<h1>同一套碼本：統計與 LLM 破譯能力比較</h1>'
            f'<p>模型 {escape(result["model"])}；每批 {result["batch_size"]} 封；{result["rounds"]} 輪；請求 {result["llm_call_total"]} 次。</p>'
            '<p>合成案例、固定包含正確候選的詞庫、無已知明文錨點。LLM 僅提供詞庫內候選，不能當作實際歷史密電破譯能力。</p>'
            '<p><b style="color:#3179b8">■ 初始統計求解（詞庫來源見模式）</b>　<b style="color:#c06d23">■ 內網 LLM 後重排</b></p>'
            f'<svg viewBox="0 0 {width} 290" role="img" aria-label="未知碼組 Top-1 正確率">'
            '<line x1="60" y1="50" x2="60" y2="245" stroke="#bbb"/><line x1="60" y1="245" x2="800" y2="245" stroke="#bbb"/>'
            +ticks+yticks+''.join(plots)+'</svg><h2>完整結果</h2><div class="scroll"><table><thead><tr>'+
            ''.join('<th>'+x+'</th>' for x in ['Seed','封數','統計Top1','LLMTop1','統計探針','LLM探針','修正','改錯','請求數','LLM秒數'])+'</tr></thead><tbody>'+
            table+'</tbody></table></div><p>每個 seed 一組固定碼本；密文數量為同一串消息的巢狀前綴；獨立探針不提供給模型。</p></html>')
    return html.replace('</html>', explorer_html(result)+'</html>')


def replay_decoding_views(existing: dict[str, Any], *, manifest_path: str | Path = MANIFEST,
                          iterations: int = 2, restarts: int = 2) -> dict[str, Any]:
    """Recreate code-to-term snapshots from saved accepted hints, never call an LLM.

    Older study JSON records accepted suggestions but not solver snapshots. Replay
    exact rank weights and recompute locally. Verify the reproduced scores AFTER
    inference using separate gold; mismatches are explicitly reported.
    """
    if existing.get('llm_used') is not True or not existing.get('runs') or not existing.get('trace'):
        raise CaseError('existing report lacks completed LLM runs/accepted-hint trace')
    spec, home = load_manifest(manifest_path)
    seeds = {int(item['seed']): item for item in spec['datasets']}
    metadata = bool(existing.get('metadata', True))
    audit = {(int(a['seed']),int(a['messages'])):a['trace'] for a in existing['trace']}
    views: list[dict[str, Any]] = []
    checks = []
    for row in existing['runs']:
        seed, size = int(row['seed']), int(row['messages'])
        if seed not in seeds or not 1 <= size <= 100 or (seed,size) not in audit:
            raise CaseError('missing fixture or saved trace for a completed run')
        item=seeds[seed]
        case=json.loads((home/item['case']).read_text(encoding='utf-8'))
        if case.get('known_pairs') or any(k in case for k in ('gold','ground_truth','codebook')):
            raise CaseError('source case contains oracle data or known plaintext')
        case={**case,'messages':case['messages'][:size]}
        if existing.get('auto_vocabulary'):
            saved_vocabulary = next((v for v in audit[(seed,size)]
                                     if v.get('task')=='generate_vocabulary' and v.get('status')=='completed'),None)
            if not saved_vocabulary:
                raise CaseError('auto-vocabulary replay requires saved candidate term audit')
            case=case_from_vocabulary_record(case,saved_vocabulary)
        baseline=analyze(case,use_metadata=metadata,iterations=iterations,restarts=restarts,seed=7)
        hints: dict[str,dict[str,float]] = {}
        result=baseline
        trace=audit[(seed,size)]
        for step in range(1,int(existing['rounds'])+1):
            batch_found=False
            for record in trace:
                if record.get('round') != step:
                    continue
                batch_found=True
                if record.get('status') == 'failed':
                    raise CaseError('cannot replay an incomplete failed run')
                for item_hint in record.get('accepted',[]):
                    code=item_hint['code']
                    if code not in result['proposals']:
                        raise CaseError('trace contains a code outside the original input')
                    for rank,word in enumerate(item_hint['candidates']):
                        hints.setdefault(code,{})[word]=min(
                            0.6,hints.get(code,{}).get(word,0.0)+0.25/(rank+1))
            if not batch_found:
                raise CaseError('trace missing requested LLM round')
            result=analyze(case,use_metadata=metadata,llm_hints=hints,
                           iterations=iterations,restarts=restarts,seed=7)
        pending_view=build_decoding_view(case,baseline,result,seed=seed,size=size,trace=trace)
        # Never use gold until baseline and replayed solver outputs are finalized.
        gold=json.loads((home/seeds[seed]['gold']).read_text(encoding='utf-8'))
        old_b=score_result(baseline,gold,case)['unknown_code_top1_rate']
        old_l=score_result(result,gold,case)['unknown_code_top1_rate']
        match=abs(old_b-float(row['stat_top1']))<=0.0001 and abs(old_l-float(row['llm_top1']))<=0.0001
        views.append(attach_evaluation_gold(pending_view,gold))
        checks.append({'seed':seed,'messages':size,'matches_saved_top1':match,
                       'replayed_stat_top1':old_b,'replayed_llm_top1':old_l})
    reconstructed={**existing,'decoding_views':views,'decoding_view_replayed_offline':True,
                   'decoding_view_replay_checks':checks}
    return reconstructed


def main(argv: list[str] | None = None) -> int:
    p=argparse.ArgumentParser(description='Explicit opt-in LLM vs statistics, single-codebook volume benchmark')
    p.add_argument('--manifest', default=str(MANIFEST))
    p.add_argument('--llm-config', default='config.yaml', help='Local YAML private-network model settings')
    p.add_argument('--enable-llm', action='store_true', help='Explicit authorization to transmit fictional cases to configured LAN model')
    p.add_argument('--sizes', default='10,25,50,100')
    p.add_argument('--seeds', default='101', help='101 or 101,202,303')
    p.add_argument('--metadata', choices=('on','off'), default='on')
    p.add_argument('--rounds', type=int, default=1)
    p.add_argument('--batch-size', type=int, default=25)
    p.add_argument('--iterations', type=int, default=2)
    p.add_argument('--restarts', type=int, default=2)
    p.add_argument('--capture-llm-io', action='store_true', help='Opt in to saving raw Prompt and LLM responses locally (may contain sensitive data)')
    p.add_argument('--auto-vocabulary', action='store_true', help='LLM generates candidate lexicon from ciphertext frequencies and optional side-information; ignores fixture vocabulary (1 extra LLM call per size)')
    p.add_argument('--rebuild-view-from', metavar='REPORT.json', help='Offline replay of old accepted LLM suggestions; NO API calls')
    p.add_argument('--out', default='artifacts/volume_llm_study.json')
    a=p.parse_args(argv)
    if a.rebuild_view_from:
        try:
            source=Path(a.rebuild_view_from)
            existing=json.loads(source.read_text(encoding='utf-8'))
            result=replay_decoding_views(existing,manifest_path=a.manifest,
                                         iterations=a.iterations,restarts=a.restarts)
            out=source.with_name(source.stem+'_decipher.json')
            out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            out.with_suffix('.html').write_text(as_html(result),encoding='utf-8')
            mismatches=[x for x in result['decoding_view_replay_checks'] if not x['matches_saved_top1']]
            if mismatches:
                print(f'[replay WARNING] {len(mismatches)} scenarios differ from saved Top-1 results; view is a recomputation, not an exact snapshot.',file=sys.stderr)
            print(f'[replay] No LLM calls. Explorer: {out.with_suffix(".html")}; details: {out}')
            return 0
        except (CaseError,ValueError,OSError,KeyError,TypeError) as exc:
            print('[replay ERROR]',exc,file=sys.stderr)
            return 2
    if not a.enable_llm:
        print('ERROR: opt in with --enable-llm, or use run_volume_study_windows.bat for offline statistical testing.',file=sys.stderr)
        return 2
    try:
        sizes=tuple(int(x) for x in a.sizes.split(','))
        seeds=tuple(int(x) for x in a.seeds.split(','))
        result=run_llm_comparison(a.manifest,sizes=sizes,seeds=seeds,metadata=a.metadata=='on',
                      llm_config=a.llm_config,rounds=a.rounds,batch_size=a.batch_size,
                      iterations=a.iterations,restarts=a.restarts,capture_io=a.capture_llm_io,auto_vocabulary=a.auto_vocabulary)
        out=Path(a.out)
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        out.with_suffix('.md').write_text(as_markdown(result),encoding='utf-8')
        out.with_suffix('.html').write_text(as_html(result),encoding='utf-8')
        print(f'[done] Report: {out}; graph: {out.with_suffix(".html")}; markdown: {out.with_suffix(".md")}')
        return 0
    except LLMStudyInterrupted as exc:
        if a.capture_llm_io and exc.partial_report:
            failed_path=Path(a.out).with_suffix('.failed.json')
            try:
                failed_path.parent.mkdir(parents=True,exist_ok=True)
                failed_path.write_text(json.dumps(exc.partial_report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                print(f'[failed] Captured partial LLM trace: {failed_path}',file=sys.stderr)
            except OSError as write_exc:
                print(f'[ERROR] Could not write partial trace: {write_exc}',file=sys.stderr)
        print('[ERROR]',exc,file=sys.stderr)
        return 2
    except (CaseError,ValueError,OSError,KeyError) as exc:
        print('[ERROR]',exc,file=sys.stderr)
        return 2

if __name__=='__main__':
    raise SystemExit(main())
