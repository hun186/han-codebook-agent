"""Human-readable evidence-led comparison of statistical and LLM proposals."""
from __future__ import annotations

from typing import Any


def investigation_report(result: dict[str, Any], events: list[dict[str, Any]]) -> str:
    """Emit a Markdown research report, never presenting hypotheses as verified decrypts."""
    baseline = next((e['payload'].get('mapping', {}) for e in events
                     if e['stage'] == 'statistical_baseline'), {})
    rounds = [e for e in events if e['stage'] == 'rescore']
    llm_proposals = [e for e in events if e['stage'] == 'llm_proposals_unverified']
    llm_responses = [e for e in events if e['stage'] == 'llm_response']
    entries = result['proposals']
    verified = sum(x['status'] == 'verified_alignment' for x in entries.values())
    changed = sum(baseline.get(code) != p['term'] for code, p in entries.items())
    lines = [
        '# 中文歷史詞組密電 — AI 分析研究報告', '',
        '> 本結果僅為候選假設。除非由明密文對明確驗證，不能宣稱為已破解電文。', '',
        f"- 案例：`{result['case_id']}`",
        f"- 分析電文：{len(result['decoded_messages'])} 封",
        f"- 已確定錨點：{verified} 組；待驗證：{len(entries)-verified} 組",
        f"- LLM 回合數：{result['agent_rounds_completed']}；啟用元數據：{result['metadata_used']}",
        f"- 相較離線 Baseline，第一順位變更：{changed} 組（**不是**正確率）", '',
        '## 逐輪變化', '',
        '| 回合 | 合法候選碼組 | 被拒絕候選 | 第一順位變動 | 目標分數 |',
        '|---|---:|---:|---:|---:|',
    ]
    initial = next((e['payload'].get('score') for e in events if e['stage']=='statistical_baseline'), '')
    lines.append(f'| Baseline | — | — | — | {initial} |')
    for e in rounds:
        proposals = next((p['payload'] for p in llm_proposals if p['round']==e['round']), {})
        lines.append(f"| {e['round']} | {len(proposals.get('accepted',[]))} | {proposals.get('rejected_count',0)} | {e['payload'].get('changed_count',0)} | {e['payload'].get('score')} |")
    lines += ['', '## 碼組候選比較', '',
              '| 密碼組 | 狀態 | Baseline | 最後候選 | 改變 |',
              '|---|---|---|---|---|']
    for code, proposal in sorted(entries.items()):
        first = baseline.get(code, '')
        after = proposal['term']
        status = '已對齊明文' if proposal['status']=='verified_alignment' else '尚待驗證'
        lines.append(f"| `{code}` | {status} | {first} | {after} | {'是' if first != after else '否'} |")
    bold = result.get("bold_hypotheses", {})
    if bold:
        lines += ['', '## 研究員大膽指定（獨立反對假說，非已驗證明文）', '',
                  '以下指定僅供對照，**不會更改逐碼明文錨點，也不代表求解器認定這個替代詞正確**。', '',
                  '| 碼組 | 已驗證明文 | 大膽假說 | 研究理由 |',
                  '|---|---|---|---|']
        for code, item in sorted(bold.items()):
            original = result.get("verified_anchors", {}).get(code, "")
            clean = lambda v: str(v).replace("|", "／").replace("\\n", " ")
            lines.append(f"| \`{code}\` | {clean(original)} | {clean(item['term'])} | {clean(item['note'])} |")
    lines += ['', '## AI 請求及回覆摘要', '']
    if not llm_responses:
        lines.append('本次未存檔原始 API 回覆；請在本機瀏覽器勾選「完整 Prompt 與回覆」後重新執行。')
    for e in llm_responses:
        p=e['payload']
        lines.append(f"- Round {e['round']}：耗時 {p.get('elapsed_ms','?')} ms；Token usage `{p.get('usage')}`。原始內容可在本機 SQLite 稽核紀錄檢視。")
    lines += ['', '## 電文候選明文', '', '| 電文 | 領域推測 | 候選明文 | 已確定碼組 |', '|---|---|---|---|']
    for m in result['decoded_messages']:
        lines.append(f"| `{m['id']}` | {m['domain_inferred'] or '未知'} | {m['reading']} | {m['verified_codes']}/{m['total_codes']} |")
    lines += ['', '## 研究限制', '',
              '- 目前僅支援固定分隔之數字碼組，不含第二層加數密碼求解。',
              '- 詞彙及範例句是事先提供的語言先驗；不代表無資訊盲解。',
              '- 元數據及第三方目擊只作候選加權，絕不視為已確定明文。',
              '- 模型目標分數與候選差距不是校準機率，更不能當作破譯正確率。',
              '- 要量測正確率應使用與推理隔離的獨立金標基準。', '']
    return '\n'.join(lines)
