"""Evaluate increased ciphertext volume under ONE shared codebook per corpus.

The input is a nested 100-message training stream (10,25,50,100 prefixes).
Completely separate secret gold holds the codebook and 20 disjoint probe
messages; it is read ONLY after inference returns, never passed to analyze.
"""
from __future__ import annotations
import argparse
from html import escape
from statistics import mean
from collections import Counter
import json
from pathlib import Path
import time
from typing import Any
from .core import CaseError, analyze, validate_case
from .benchmark import score_result

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / 'benchmarks' / 'volume' / 'manifest.json'


def load_manifest(path: str | Path) -> tuple[dict, Path]:
    path = Path(path).resolve()
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('version') != 1 or not manifest.get('datasets'):
        raise CaseError('Invalid volume manifest')
    return manifest, path.parent


def probe_metrics(proposals: dict, gold: dict) -> dict:
    predicted = {code: p['term'] for code, p in proposals.items()}
    answer = gold['codebook']
    probes = gold['probe_messages']
    total = sum(len(m['codes']) for m in probes)
    covered = hits = exact = 0
    for m in probes:
        codes = m['codes']
        covered += sum(c in predicted for c in codes)
        hits += sum(predicted.get(c) == answer[c] for c in codes)
        exact += int(all(predicted.get(c) == answer[c] for c in codes))
    return {
        'probe_messages': len(probes), 'probe_groups': total,
        'probe_covered_groups': covered, 'probe_correct_groups': hits,
        'probe_coverage_rate': round(covered/total,4) if total else 0,
        'probe_top1_rate_all_groups': round(hits/total,4) if total else 0,
        'probe_top1_rate_covered_groups': round(hits/covered,4) if covered else None,
        'probe_exact_message_rate': round(exact/len(probes),4) if probes else 0
    }


def run_study(manifest_path: str | Path=MANIFEST, *, sizes: tuple[int,...]=(10,25,50,100),
              seeds: tuple[int,...] | None=None, metadata_variants: tuple[bool,...]=(True,False),
              iterations: int=2, restarts: int=2) -> dict[str,Any]:
    if not sizes or any(x <= 0 or x > 100 for x in sizes) or tuple(sorted(set(sizes))) != sizes:
        raise CaseError('sizes must be ascending unique values between 1 and 100')
    if not metadata_variants or iterations < 1 or restarts < 1:
        raise CaseError('Provide metadata variants and positive search budget')
    spec, home=load_manifest(manifest_path)
    runs=[]
    for item in spec['datasets']:
        seed=int(item['seed'])
        if seeds is not None and seed not in seeds:
            continue
        case=json.loads((home/item['case']).read_text(encoding='utf-8'))
        if any(k in case for k in ('ground_truth','gold','codebook')) or case.get('known_pairs'):
            raise CaseError('input leaks gold or known plaintext; zero initial anchors required')
        validate_case(case)
        if len(case['messages']) != 100:
            raise CaseError('each dataset requires 100 fixed ordered training telegrams')
        if len({m['id'] for m in case['messages']}) != 100:
            raise CaseError('duplicate message IDs')
        # Open gold strictly only after inference; never pass into analyze().
        gold_path=home/item['gold']
        first_codes={c for m in case['messages'][:sizes[0]] for c in m['codes']}
        for size in sizes:
            subset={**case, 'case_id':f"{case['case_id']}-n{size}", 'messages':case['messages'][:size]}
            for meta in metadata_variants:
                started=time.perf_counter()
                result=analyze(subset, use_metadata=meta, iterations=iterations, restarts=restarts,seed=7)
                elapsed=time.perf_counter()-started
                gold=json.loads(gold_path.read_text(encoding='utf-8'))
                if len(gold.get('probe_messages',[])) != 20:
                    raise CaseError('exactly 20 disjoint probe messages required')
                training_ids={m['id'] for m in case['messages']}
                if any(m['id'] in training_ids for m in gold['probe_messages']):
                    raise CaseError('training/test message leakage')
                metrics=score_result(result,gold,subset)
                pr=probe_metrics(result['proposals'],gold)
                in_common={c:p for c,p in result['proposals'].items() if c in first_codes}
                baseline_top1=sum(p['term']==gold['codebook'][c] for c,p in in_common.items())
                code_frequencies=Counter(c for m in subset['messages'] for c in m['codes'])
                singletons=sum(1 for f in code_frequencies.values() if f==1)
                row={
                    'seed':seed,'messages':size,'metadata':meta,'one_codebook':True,
                    'initial_known_plaintext_pairs':0,'search_iterations':iterations,'search_restarts':restarts,
                    'distinct_codes_observed':len(result['proposals']),
                    'singleton_codes':singletons,
                    'shared_initial_10_codes':len(first_codes),
                    'shared_initial_10_correct':baseline_top1,
                    'shared_initial_10_top1_rate':round(baseline_top1/len(first_codes),4),
                    'elapsed_seconds':round(elapsed,4),
                    'unknown_top1_rate':metrics['unknown_code_top1_rate'],
                    'unknown_top5_rate':metrics['unknown_code_top5_rate'],
                    'unknown_code_count':metrics['unknown_code_count'],
                    'message_exact_rate':metrics['non_crib_exact_rate'],
                    'token_correct_rate':metrics['non_crib_segment_accuracy'],
                    **pr
                }
                runs.append(row)
                print(f"seed={seed} n={size:>3} metadata={str(meta):5} codes={row['distinct_codes_observed']:>2} "
                      f"top1={row['unknown_top1_rate']:.1%} probe={row['probe_top1_rate_all_groups']:.1%} time={elapsed:.2f}s",flush=True)
    if not runs:
        raise CaseError('no selected seeds found')
    return {'title':'Single-codebook nested ciphertext-volume experiment (fictional)',
            'data_status':'synthetic; not historical-decryption accuracy',
            'count_control':'All sample sizes are nested prefixes of the same 100-message sequence per seed.',
            'codebook_control':'One unchanging secret codebook within each seed; independent fixed codebooks across seeds.',
            'candidate_prior':'Generator supplies a public vocabulary with intended terms and decoys; not a pure ciphertext-only scenario.',
            'initial_anchors':0,'llm_used':False,
            'heldout_probe':'20 disjoint telegrams per seed, not included in any inference set',
            'search_iterations':iterations,'search_restarts':restarts,'runs':runs}


def as_markdown(result: dict) -> str:
    lines=['# 固定單一碼本：密電數量與破譯表現比較（合成實驗）','',
           '> 無已知明文、未使用 LLM、固定候選詞庫與求解預算；此數字不代表真實密碼破解能力。','',
           '| 種子 | 封數 | 收發情報 | 碼組覆蓋 | 單次出現碼組 | 未知碼 Top-1 | 未知碼 Top-5 | 固定前10封碼組 Top-1 | 獨立20封 Top-1 | 運算秒數 |',
           '|---:|---:|:---:|---:|---:|---:|---:|---:|---:|---:|']
    for v in result['runs']:
        pct=lambda x:f'{x:.1%}'
        lines.append(f"| {v['seed']} | {v['messages']} | {'有' if v['metadata'] else '無'} | "
            f"{v['distinct_codes_observed']} | {v['singleton_codes']} | {pct(v['unknown_top1_rate'])} | "
            f"{pct(v['unknown_top5_rate'])} | {pct(v['shared_initial_10_top1_rate'])} | "
            f"{pct(v['probe_top1_rate_all_groups'])} | {v['elapsed_seconds']:.2f} |")
    lines+=['','- 同一 seed 的 10／25／50／100 封逐步增加，不會更換碼本。','- 固定前 10 封碼組的準確率，讓比較不受新增碼組難度差異干擾。',
           '- 獨立 20 封測試包含尚未在已收密電中出現的碼組；未覆蓋者計錯，避免虛高。',
           '- 這仍是已知候選詞池的合成情境，且沒有二次加密、假碼、碼本變動。','']
    return '\n'.join(lines)


def mean_by_volume(result: dict) -> list[dict]:
    """Show seed-averages separately from raw scores; no pooling away failures."""
    runs=result['runs']
    groups=sorted({(v['messages'],v['metadata']) for v in runs})
    records=[]
    for size,meta in groups:
        batch=[r for r in runs if (r['messages'],r['metadata']) == (size,meta)]
        records.append({'messages':size,'metadata':meta,'seeds':len(batch),
                        'mean_code_top1':round(mean(v['unknown_top1_rate'] for v in batch),4),
                        'mean_fixed10_top1':round(mean(v['shared_initial_10_top1_rate'] for v in batch),4),
                        'mean_probe_top1':round(mean(v['probe_top1_rate_all_groups'] for v in batch),4),
                        'mean_probe_coverage':round(mean(v['probe_coverage_rate'] for v in batch),4),
                        'mean_distinct_codes':round(mean(v['distinct_codes_observed'] for v in batch),2)})
    return records


def as_html(result: dict) -> str:
    """Standalone, no network, no JS: SVG trends and full results table."""
    aggregates=mean_by_volume(result)
    def chart(key: str,label: str) -> str:
        width,height=650,245
        lo,hi=10,100
        def x(n): return 50+(n-lo)/(hi-lo)*560
        def y(v): return 200-(v if key != 'mean_distinct_codes' else v/80)*170
        lines=[]
        for meta,stroke,name in ((True,'#176ba0','使用收發情報'),(False,'#aa6432','不使用收發情報')):
            subset=sorted([r for r in aggregates if r['metadata']==meta],key=lambda r:r['messages'])
            pts=' '.join(f"{x(r['messages']):.1f},{y(r[key]):.1f}" for r in subset)
            lines.append(f'<polyline points="{pts}" stroke="{stroke}" stroke-width="3" fill="none"/>')
            for r in subset:
                val=r[key]
                label_value=f'{val:.1f}' if key=='mean_distinct_codes' else f'{val:.1%}'
                lines.append(f'<circle cx="{x(r["messages"]):.1f}" cy="{y(val):.1f}" r="4" fill="{stroke}"><title>{name}，{r["messages"]}封：{label_value}</title></circle>')
        xticks=''.join(f'<text x="{x(n):.1f}" y="220" text-anchor="middle" font-size="12">{n}封</text>' for n in (10,25,50,100))
        yticks=''.join(f'<text x="42" y="{y(i/4*(80 if key=="mean_distinct_codes" else 1)):.1f}" text-anchor="end" font-size="11">{round(i*20) if key=="mean_distinct_codes" else round(i*25)}{ "" if key=="mean_distinct_codes" else "%"}</text>' for i in range(5))
        return (f'<section class="chart"><h2>{escape(label)}</h2><svg viewBox="0 0 {width} {height}" role="img" '
                f'aria-label="{escape(label)} 隨收到電文數量變動">'
                '<line x1="50" y1="30" x2="50" y2="200" stroke="#aaa"/>'
                '<line x1="50" y1="200" x2="620" y2="200" stroke="#aaa"/>'
                +xticks+yticks+''.join(lines)+'</svg></section>')
    rows=''.join('<tr>'+''.join(f'<td>{escape(str(v[k]))}</td>' for k in ('seed','messages','metadata','distinct_codes_observed',
           'unknown_top1_rate','shared_initial_10_top1_rate','probe_coverage_rate','probe_top1_rate_all_groups','elapsed_seconds'))+'</tr>' for v in result['runs'])
    return ('<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>單一碼本密電量與破譯成效</title><style>body{font-family:system-ui,"Noto Sans TC",sans-serif;margin:32px auto;max-width:1100px;padding:0 18px;background:#f9fafc;color:#192432}'
            'p{line-height:1.7}.charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(350px,1fr));gap:16px}.chart{border:1px solid #dce1eb;border-radius:12px;padding:15px;background:white}'
            'svg{width:100%;height:auto}.legend{display:flex;gap:25px}.legend span{display:inline-flex;align-items:center;gap:7px}.swatch{width:22px;height:4px;display:inline-block}'
            'table{border-collapse:collapse;width:100%;background:white}td,th{border:1px solid #dce1eb;padding:8px;text-align:right;font-size:13px}th{background:#eef3f8}.tablewrap{overflow:auto}</style>'
            '<h1>單一碼本：10／25／50／100 封密電</h1>'
            '<p>三組獨立合成碼本 × 四種累積電文數 × 收發情報開關。起始已知對照為 0；保留固定候選詞庫，僅使用統計求解器，未呼叫 LLM。</p>'
            '<p><strong>注意：</strong>這是人工生成、由已知候選詞池支援的研究測試。縱軸是與獨立標準答案比較後的正確率，不是模型主觀分數，也不是歷史密電真實破解率。</p>'
            '<div class="legend"><span><i class="swatch" style="background:#176ba0"></i>使用收發情報</span><span><i class="swatch" style="background:#aa6432"></i>不使用收發情報</span></div>'
            '<div class="charts">'+chart('mean_code_top1','觀察到的未知碼組 Top-1（種子平均）')
            +chart('mean_fixed10_top1','固定前10封碼組 Top-1（種子平均）')
            +chart('mean_probe_top1','獨立20封電文碼組 Top-1（種子平均）')
            +chart('mean_distinct_codes','觀察到不同碼組數（種子平均）')+'</div>'
            '<h2>完整逐組結果</h2><p>欄位：seed、封數、元數據開關、已見不同碼組、Top-1、共同碼組 Top-1、獨立測試覆蓋率、獨立測試 Top-1、運算秒數。未觀察碼組在獨立測試中計為錯誤。</p>'
            '<div class="tablewrap"><table><thead><tr><th>Seed</th><th>封數</th><th>Metadata</th><th>碼組數</th><th>Top-1</th><th>共同碼組 Top-1</th><th>探針覆蓋</th><th>探針 Top-1</th><th>秒數</th></tr></thead><tbody>'
            +rows+'</tbody></table></div><p>來源：同份 JSON 實測結果。圖中平均值不保證單調上升。</p></html>')


def main(argv:list[str] | None=None) -> int:
    parser=argparse.ArgumentParser(description='Nested ciphertext-volume offline evaluation, single secret codebook')
    parser.add_argument('--manifest',default=str(MANIFEST))
    parser.add_argument('--sizes',default='10,25,50,100')
    parser.add_argument('--seeds',default='all',help='all or comma-separated integer seeds')
    parser.add_argument('--metadata',choices=('both','on','off'),default='both')
    parser.add_argument('--iterations',type=int,default=2)
    parser.add_argument('--restarts',type=int,default=2)
    parser.add_argument('--out',default='artifacts/volume_study.json')
    args=parser.parse_args(argv)
    try:
        sizes=tuple(int(x) for x in args.sizes.split(','))
        seeds=None if args.seeds=='all' else tuple(int(x) for x in args.seeds.split(','))
        result=run_study(args.manifest,sizes=sizes,seeds=seeds,
                         metadata_variants={'both':(True,False),'on':(True,),'off':(False,)}[args.metadata],
                         iterations=args.iterations,restarts=args.restarts)
        out=Path(args.out)
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        out.with_suffix('.md').write_text(as_markdown(result),encoding='utf-8')
        out.with_suffix('.html').write_text(as_html(result),encoding='utf-8')
        print(f'Reports: {out}, {out.with_suffix(".md")}, {out.with_suffix(".html")}',flush=True)
        return 0
    except (CaseError,ValueError,OSError,KeyError) as e:
        print('ERROR:',e)
        return 2

if __name__=='__main__':raise SystemExit(main())
