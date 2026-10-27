"""Offline-first multi-scenario synthetic benchmark with post-inference-only gold access.

Example: python -m han_codebook.benchmark --config benchmarks/config.yaml
Optional local LLM: --enable-llm --llm-config config.yaml --rounds 2
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .agent import run_agent
from .config import load_settings
from .core import CaseError, analyze, load_case


def score_result(result: dict[str, Any], gold: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    """Inspect secret labels AFTER analyze/run_agent returns. Never pass gold into them."""
    known = result['verified_anchors']
    code_truth = gold['codebook']
    predicted = result['proposals']
    missing = sorted(set(predicted) - set(code_truth))
    if missing:
        raise CaseError(f"gold file is missing ciphertext codes {missing}")
    # A single repeated code must always represent the same term for this *supported* family.
    if any(known[k] != code_truth[k] for k in known):
        raise CaseError('gold conflicts with verified known-plaintext alignment')
    unknown = sorted(set(predicted) - set(known))
    correct = sum(predicted[c]['term'] == code_truth[c] for c in unknown)
    top5 = sum(code_truth[c] in {v['term'] for v in predicted[c]['alternatives'][:5]} for c in unknown)

    excluded_messages = {p['message_id'] for p in case.get('known_pairs', []) if p.get('segments') is not None}
    unseen = [m for m in case['messages'] if m['id'] not in excluded_messages]
    exact = 0
    tokens, token_hits = 0, 0
    unanchored_tokens, unanchored_hits = 0, 0
    for message in unseen:
        if message['id'] not in gold['messages']:
            raise CaseError(f"gold missing message {message['id']}")
        result_segments = [predicted[c]['term'] for c in message['codes']]
        expected_segments = [code_truth[c] for c in message['codes']]
        truth_reading = gold['messages'][message['id']]
        if ''.join(expected_segments) != truth_reading:
            raise CaseError(f"gold mismatch for message {message['id']}")
        exact += ''.join(result_segments) == truth_reading
        tokens += len(message['codes'])
        token_hits += sum(a==b for a,b in zip(result_segments, expected_segments))
        for c in message['codes']:
            if c not in known:
                unanchored_tokens += 1
                unanchored_hits += predicted[c]['term'] == code_truth[c]
    return {
        'verified_anchor_count':len(known),
        'unknown_code_count':len(unknown),
        'unknown_code_top1_correct':correct,
        'unknown_code_top1_rate':round(correct/len(unknown),4) if unknown else None,
        'unknown_code_top5_correct':top5,
        'unknown_code_top5_rate':round(top5/len(unknown),4) if unknown else None,
        'non_crib_message_count':len(unseen),
        'non_crib_exact_messages':exact,
        'non_crib_exact_rate':round(exact/len(unseen),4) if unseen else None,
        'non_crib_segment_accuracy':round(token_hits/tokens,4) if tokens else None,
        'non_crib_unknown_segment_accuracy':round(unanchored_hits/unanchored_tokens,4) if unanchored_tokens else None,
        'unsegmented_pairs_require_review':len(result.get('pair_review', [])),
        'wrong_unknown_codes':[c for c in unknown if predicted[c]['term'] != code_truth[c]],
        'note':'Synthetic only. Gold is loaded after the solver finishes; lexicon/priors are supplied to solver. Predictions are not independently verified.'
    }


def run_suite(suite_path: str | Path, *, variants: tuple[bool,...]=(True,False),
              llm_settings: dict[str,Any] | None=None, rounds: int=0,
              audit_dir: Path | None=None) -> dict[str,Any]:
    suite_file=Path(suite_path).resolve()
    manifest=json.loads(suite_file.read_text(encoding='utf-8'))
    if manifest.get('version') != 1 or not isinstance(manifest.get('cases'), list) or not manifest['cases']:
        raise CaseError('benchmark suite requires nonempty cases, version 1')
    if not 0 <= rounds <= 20:
        raise CaseError('benchmark LLM rounds must be 0..20')
    if rounds and not llm_settings:
        raise CaseError('LLM benchmark requires explicit --enable-llm and --llm-config')
    results=[]
    for entry in manifest['cases']:
        source=(suite_file.parent/entry['case']).resolve()
        gold_path=(suite_file.parent/entry['gold']).resolve()
        if source == gold_path:
            raise CaseError('case JSON and gold JSON must be separate files')
        case=load_case(source)
        if 'ground_truth' in case:
            raise CaseError('benchmark input must NOT contain ground_truth; separate gold file required')
        if case.get('case_id') != entry['id']:
            raise CaseError(f"case_id differs from suite entry {entry['id']}")
        for use_metadata in variants:
            if rounds:
                llm=llm_settings or {}
                if audit_dir is None:
                    raise CaseError('audit_dir required for LLM benchmark')
                audit=Path(audit_dir)/f"{entry['id']}_{'meta' if use_metadata else 'no_meta'}.sqlite"
                prediction=run_agent(case,rounds=rounds,metadata=use_metadata,
                      llm_url=llm['base_url'],model=llm['model'],db_path=str(audit),
                      llm_timeout=llm.get('timeout_seconds',90),
                      allow_private_network=llm.get('allow_private_network',False),
                      llm_allowed_hosts=llm.get('allowed_hosts',[]),
                      llm_api_key_env=llm.get('api_key_env'))
            else:
                prediction=analyze(case,use_metadata=use_metadata)
            # Intentional security boundary: gold loaded only after inference.
            gold=json.loads(gold_path.read_text(encoding='utf-8'))
            if gold.get('case_id') != entry['id']:
                raise CaseError('wrong benchmark gold case_id')
            scores=score_result(prediction,gold,case)
            results.append({'case_id':entry['id'], 'description':entry['description'],
                'metadata':use_metadata,'llm_rounds':rounds,'metrics':scores})
    return {'suite':str(suite_file),'fictional_synthetic':True,
            'real_cryptanalytic_success_not_established':True,
            'case_count':len(manifest['cases']),'runs':results,
            'interpretation':'Profiles supply candidate vocabulary and example transitions, so no-information blind decipherment is NOT tested.'}


def render_markdown(report: dict[str, Any]) -> str:
    rows=[
      '# Han Codebook Agent — synthetic benchmark',
      '',
      '**警告：全部為虛構測試。模型可讀取候選詞彙與範例句，不能宣稱這是無情報盲解，更不是歷史電文破譯成功。**',
      '',
      '| Case | 元數據 | 錨點 | 未知碼 Top-1 | 未知碼 Top-5 | 未提供對齊答案電文全對 | 未對齊碼組在測試電文的正確率 | 人工切詞待審 |',
      '|---|---|---:|---:|---:|---:|---:|---:|',
    ]
    def fmt(v):
        return f'{100*v:.1f}%' if v is not None else 'N/A'
    for run in report['runs']:
        m=run['metrics']
        rows.append(f"| `{run['case_id']}` | {'有' if run['metadata'] else '無'} | {m['verified_anchor_count']} | {m['unknown_code_top1_correct']}/{m['unknown_code_count']} ({fmt(m['unknown_code_top1_rate'])}) | {fmt(m['unknown_code_top5_rate'])} | {m['non_crib_exact_messages']}/{m['non_crib_message_count']} ({fmt(m['non_crib_exact_rate'])}) | {fmt(m['non_crib_unknown_segment_accuracy'])} | {m['unsegmented_pairs_require_review']} |")
    rows += ['', '## 指標說明', '',
      '- **未知碼 Top-1 / Top-5**：只計算未由逐碼明文錨定的碼組，避免把已知答案當成破密成果。',
      '- **非 crib 電文**：排除用來建立逐碼明文錨點的電文；完整電文正確率要求整句完全一致。',
      '- **詞段正確率**：採碼組切分而非漢字 edit distance；真實密碼可能無法直接以此衡量。',
      '- **公平性限制**：詞彙表及示範轉移在事前就提供給求解器；語料小、分布刻意設計，沒有測試真實加數密碼或無界碼本。',
      '- **元數據反例**：誤導性收發單位可能讓準確率降低，不能假設加入情報必然改善結果。',
      '- **LLM 測試**：本次結果是否呼叫 LLM 應依 JSON `llm_rounds` 檢查；本機離線預設為 0。',
      '']
    return '\n'.join(rows)


def main(argv: list[str] | None=None) -> int:
    parser=argparse.ArgumentParser(description='Synthetic codebook benchmark (offline by default)')
    parser.add_argument('--config',default='benchmarks/config.yaml',help='YAML benchmark settings')
    parser.add_argument('--suite',help='override suite path')
    parser.add_argument('--out',help='override JSON output path')
    parser.add_argument('--variants',choices=['both','metadata','no-metadata'],default=None)
    parser.add_argument('--enable-llm',action='store_true',help='opt in to local/allowlisted LLM connection')
    parser.add_argument('--llm-config',help='existing main project config.yaml for model/host settings')
    parser.add_argument('--rounds',type=int,default=2,help='LLM rounds if enabled')
    args=parser.parse_args(argv)
    try:
        import yaml
        config_path=Path(args.config).resolve()
        settings=yaml.safe_load(config_path.read_text(encoding='utf-8'))
        if not isinstance(settings,dict) or set(settings)-{'benchmark'}:
            raise CaseError('benchmark config must contain only the benchmark mapping')
        b=settings['benchmark']
        if not isinstance(b,dict) or set(b)-{'suite','output','variants','audit_dir'}:
            raise CaseError('benchmark mapping has invalid keys')
        def resolve(s):
            return (config_path.parent/s).resolve()
        suite=Path(args.suite).resolve() if args.suite else resolve(b['suite'])
        out=Path(args.out).resolve() if args.out else resolve(b['output'])
        choice=args.variants or b.get('variants','both')
        if choice not in ('both','metadata','no-metadata'):
            raise CaseError('variants must be both, metadata, or no-metadata')
        variants={'both':(True,False),'metadata':(True,), 'no-metadata':(False,)}[choice]
        if args.enable_llm and not args.llm_config:
            raise CaseError('--enable-llm requires --llm-config pointing at your local settings')
        llm=load_settings(args.llm_config)['llm'] if args.enable_llm else None
        audit=resolve(b.get('audit_dir','../artifacts/benchmark_audit'))
        report=run_suite(suite,variants=variants,llm_settings=llm,
                          rounds=args.rounds if args.enable_llm else 0,audit_dir=audit)
        out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        md=out.with_suffix('.md')
        md.write_text(render_markdown(report),encoding='utf-8')
        print(render_markdown(report))
        print(f'JSON: {out} | Markdown: {md}')
        return 0
    except (CaseError, KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(f'ERROR benchmark: {exc}',file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
