"""Unverified per-telegram decipherment explorer for *synthetic* volume trials.

View data are built only from solver proposals and ciphertext. Secret gold and
held-out plaintext are never included in the explorer payload.
"""
from __future__ import annotations

from html import escape
import json
from typing import Any


def build_decoding_view(case: dict[str, Any], baseline: dict[str, Any],
                        llm_result: dict[str, Any], *, seed: int, size: int,
                        trace: list[dict[str, Any]]) -> dict[str, Any]:
    """Snapshot for the current corpus size; never consult ground truth."""
    def proposals(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            code: {
                'term': data['term'],
                'status': data['status'],
                'alternatives': [v['term'] for v in data.get('alternatives', [])[:5]],
            }
            for code, data in result['proposals'].items()
        }
    messages = []
    for message in case['messages']:
        # Whitelist fields so that a future fixture cannot carry gold into this report.
        messages.append({key: message[key]
                         for key in ('id', 'codes', 'sender', 'recipient', 'received_at')
                         if key in message})
    trace_hints = [
        {'batch': f"{step['start']}–{step['end']}", 'round': step['round'],
         'accepted': [
             {'code': item['code'], 'candidates': item['candidates'], 'reason': item['reason']}
             for item in step.get('accepted', [])
         ]}
        for step in trace
    ]
    return {'seed': seed, 'messages_count': size, 'messages': messages,
            'statistical': proposals(baseline), 'llm': proposals(llm_result),
            'batches': trace_hints,
            'note': '中文全為目前 Top-1 候選；非已驗證歷史明文'}


def explorer_html(report: dict[str, Any]) -> str:
    """Self-contained interactive viewer for a completed, offline HTML report.

    JSON is embedded as inert script text and escaped against </script> and HTML
    injections. All dynamic content is rendered through DOM.textContent.
    """
    views = report.get('decoding_views', [])
    if not views:
        return ''
    payload = json.dumps(views, ensure_ascii=False, separators=(',', ':'))
    for old, new in [('<', '\\u003c'), ('>', '\\u003e'), ('&', '\\u0026'),
                     ('\u2028', '\\u2028'), ('\u2029', '\\u2029')]:
        payload = payload.replace(old, new)
    replay_notice = ('<p class="decoder-note">此圖由既有 LLM 建議紀錄在本機重新求解，非原始儲存的碼本快照；如重算分數不同，請以原報告為準。</p>'
                     if report.get('decoding_view_replayed_offline') else '')
    return ('''
<style>
.decoder{margin-top:26px;padding:20px;border:1px solid #cbd5e1;border-radius:15px;background:#f8fafc}
.decoder h2{margin:0 0 8px}.decoder p{line-height:1.65}
.decoder-controls{display:flex;gap:12px;flex-wrap:wrap;align-items:end;margin:16px 0}
.decoder-controls label{display:grid;gap:5px;font-size:13px;font-weight:650}
.decoder select{font:inherit;padding:7px 10px;border:1px solid #9ca3af;border-radius:8px;background:white;max-width:330px}
.decoder-summary{background:#fff;border:1px solid #d5dde7;border-radius:9px;padding:12px;margin:12px 0}
.decoder-compare{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}
.decoder-pane{background:white;border:1px solid #dbe2ec;border-radius:10px;padding:12px;min-width:0}
.decoder-pane h3{margin:0 0 8px;font-size:16px}.decoder-plain{line-height:2.3;overflow-wrap:anywhere;margin:9px 0}
.decoder-word{border:1px dashed #b4bed0;border-radius:6px;padding:3px 5px;margin:2px 2px 2px 0;display:inline-block;background:#f1f5f9;cursor:pointer;font-size:15px}
.decoder-word.changed{border-color:#bd740b;background:#fff1d6}.decoder-word:focus-visible{outline:3px solid #2563eb}
.decoder-word.active{outline:2px solid #0c6a89}.decoder-code{display:block;color:#56667a;font-family:ui-monospace,monospace;font-size:11px;line-height:1.3}
.decoder-evidence{white-space:pre-wrap;overflow-wrap:anywhere;background:#fff;border:1px solid #dbe2ec;border-radius:10px;padding:12px;margin-top:14px;min-height:65px}
.decoder-note{color:#9a3412;font-size:13px;font-weight:650}.decoder-muted{color:#586577;font-size:13px}
.decoder ol{padding-left:22px}.decoder li{margin:5px 0}
</style>
<section id="decipherExplorer" class="decoder" aria-label="密電候選解讀探索器">
  <h2>密電候選解讀探索器</h2>
  <p class="decoder-note">注意：下列中文全部是尚未驗證的 Top-1 推測，不是已解開的明文。此處僅顯示訓練電文，沒有揭露獨立測試答案。</p>
''' + replay_notice + '''
  <div class="decoder-controls">
    <label>合成碼本 Seed <select id="decSeed"></select></label>
    <label>已收到的電文數 <select id="decSize"></select></label>
    <label>選擇密電 <select id="decMessage"></select></label>
  </div>
  <div class="decoder-summary" id="decSummary"></div>
  <div class="decoder-compare">
    <section class="decoder-pane"><h3>純統計推測</h3><div id="decStat"></div></section>
    <section class="decoder-pane"><h3>LLM 建議後重新求解</h3><div id="decLlm"></div></section>
  </div>
  <div class="decoder-evidence" id="decEvidence" aria-live="polite">點選中文詞組可查看來源碼組、前後候選與 LLM 建議理由。</div>
  <p class="decoder-muted">橘底：該碼組的 Top-1 相比純統計發生變動。不代表變動正確；每個封數都是獨立執行的分析，不是同一 Agent 的連續記憶。</p>
</section>
<script type="application/json" id="decodingViewData">''' + payload + '''</script>
<script>
(() => {
  'use strict';
  const views = JSON.parse(document.getElementById('decodingViewData').textContent);
  const seedSel = document.getElementById('decSeed');
  const sizeSel = document.getElementById('decSize');
  const msgSel = document.getElementById('decMessage');
  const el = id => document.getElementById(id);
  const text = (s) => document.createTextNode(String(s == null ? '' : s));
  const clear = (node) => { while(node.firstChild) node.removeChild(node.firstChild); };
  const uniqueSorted = list => [...new Set(list)].sort((a,b) => Number(a)-Number(b));
  const option = (select, value, caption) => {
    const opt=document.createElement('option'); opt.value=String(value);opt.textContent=caption;
    select.appendChild(opt);
  };
  const current = () => views.find(v=>String(v.seed)===seedSel.value && String(v.messages_count)===sizeSel.value);
  function renderCode(view, message, target, kind) {
    clear(target);
    const paragraph = document.createElement('div'); paragraph.className='decoder-plain';
    message.codes.forEach((code, index) => {
      const entry=view[kind][code] || null;
      const other=view[kind === 'statistical' ? 'llm' : 'statistical'][code] || null;
      const changed=!!(entry && other && entry.term !== other.term);
      const token=document.createElement('button');token.type='button';
      token.className='decoder-word' + (changed ? ' changed' : '');
      token.title=`碼組 ${code}：未驗證的推測；點選查看細節`;
      token.setAttribute('aria-label',`第 ${index+1} 碼組 ${code}，候選 ${entry ? entry.term : '未知'}`);
      const word=document.createElement('span');word.textContent=entry ? entry.term : '〔未解〕';
      const digit=document.createElement('span');digit.className='decoder-code';digit.textContent=code;
      token.append(word, digit);
      token.addEventListener('click', () => {
        document.querySelectorAll('.decoder-word.active').forEach(x=>x.classList.remove('active'));
        token.classList.add('active');
        renderEvidence(view, message, code);
      });
      paragraph.appendChild(token);
    });
    target.appendChild(paragraph);
    const caption=document.createElement('p');caption.className='decoder-muted';
    caption.textContent=`${message.codes.length} 個數字碼組；所有詞組均為候選，未有確認錨點`;
    target.appendChild(caption);
  }
  function renderEvidence(view, message, code) {
    const dest=el('decEvidence');clear(dest);
    const b=view.statistical[code],a=view.llm[code];
    const para=document.createElement('p');para.textContent=`密電 ${message.id}｜碼組 ${code}｜未驗證假說`;
    dest.appendChild(para);
    const ul=document.createElement('ul');
    const facts=[`純統計 Top-1：${b?.term || '未知'}；其他候選：${(b?.alternatives||[]).join('、') || '無'}`,
                 `LLM 後 Top-1：${a?.term || '未知'}；其他候選：${(a?.alternatives||[]).join('、') || '無'}`];
    const logs=view.batches.flatMap(batch=>batch.accepted.filter(h=>h.code===code)
                       .map(h=>`第 ${batch.round} 輪、第 ${batch.batch} 封：LLM 建議 ${h.candidates.join('、')}；模型提供的理由：${h.reason || '未提供'}`));
    if(!logs.length) facts.push('這次記錄沒有針對此碼組的 LLM 合格建議；重新排序的變化不一定來自直接建議。');
    facts.push(...logs);
    facts.forEach(s=>{const li=document.createElement('li');li.textContent=s;ul.appendChild(li);});
    dest.appendChild(ul);
  }
  function refreshMessages() {
    const view=current();if(!view)return;
    const previous=msgSel.value;clear(msgSel);
    view.messages.forEach((m,i)=>option(msgSel,m.id,`${i+1}. ${m.id} (${m.codes.length} 碼組)`));
    if(view.messages.some(m=>m.id===previous))msgSel.value=previous;
    render();
  }
  function refreshSizes() {
    const last=sizeSel.value;clear(sizeSel);
    uniqueSorted(views.filter(v=>String(v.seed)===seedSel.value).map(v=>v.messages_count))
      .forEach(n=>option(sizeSel,n,`${n} 封`));
    if([...sizeSel.options].some(x=>x.value===last))sizeSel.value=last;
    refreshMessages();
  }
  function render() {
    const view=current();if(!view)return;
    const message=view.messages.find(m=>m.id===msgSel.value) || view.messages[0];
    if(!message)return;
    const changed=message.codes.filter(c=>view.statistical[c]?.term !== view.llm[c]?.term).length;
    el('decSummary').textContent=`${message.id}｜原始密文：${message.codes.join(' ')} ｜收報：${message.received_at || '未記錄'}｜${message.sender || '未知發件人'} → ${message.recipient || '未知收件人'}｜本封有 ${changed} 個位置的 Top-1 不同`;
    renderCode(view,message,el('decStat'),'statistical');
    renderCode(view,message,el('decLlm'),'llm');
    clear(el('decEvidence'));el('decEvidence').appendChild(text('點選任一候選詞組，查看它對應的原始碼組、其他候選和 LLM 建議。'));
  }
  uniqueSorted(views.map(v=>v.seed)).forEach(n=>option(seedSel,n,`Seed ${n}`));
  seedSel.addEventListener('change',refreshSizes);
  sizeSel.addEventListener('change',refreshMessages);
  msgSel.addEventListener('change',render);
  refreshSizes();
})();
</script>
''')
