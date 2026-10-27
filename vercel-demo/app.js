/* Han Codebook Vercel PoC: deterministic, entirely client-side MOCK. No model, API, cookies, or storage calls. */
'use strict';
const $ = id => document.getElementById(id);
const state = { data:null,record:null,messageId:null,code:null,mockReady:false,busy:false,gold:null,
                marks:{},history:[{}],cursor:0,feedback:null };
const clone = x => JSON.parse(JSON.stringify(x));
const element = (tag, className='', label=null) => {
  const x = document.createElement(tag); if(className)x.className=className;
  if(label !== null)x.textContent=String(label);return x;
};
const clear = x => x.replaceChildren();
const notice = s => { $('status').textContent = s; };
const record = () => state.record;
const selected = () => record()?.messages.find(m=>m.id===state.messageId) || record()?.messages[0];
const term = (mapping,code) => mapping?.[code]?.term || '？';
const correct = (mapping,code) => state.gold?.codebook?.[code]===term(mapping,code);
const mockMap = () => state.mockReady ? (state.feedback?.mapping || record().mock) : record().statistical;
function activeMark(code){return state.marks[code] || {preferred:null,excluded:[],pinned:null,note:''};}
function manualTerm(code){
  const m=activeMark(code), candidate=term(mockMap(),code);
  if(m.pinned)return m.pinned;
  if(m.preferred && !m.excluded.includes(m.preferred))return m.preferred;
  if(!m.excluded.includes(candidate))return candidate;
  const options=mockMap()[code]?.alternatives||[];
  return options.find(t=>!m.excluded.includes(t)) || '？';
}
function setSize(n){
  const r=state.data.records.find(x=>x.size===n);
  if(!r)throw new Error('不存在的電文數量');
  state.record=r;state.messageId=r.messages[0]?.id || null;state.mockReady=false;
  state.code=null;state.marks={};state.history=[{}];state.cursor=0;state.feedback=null;
  $('revealGold').textContent = state.gold ? '隱藏正確明文' : '揭曉正確明文';
  // Never imply that changing sample size preserves an inference agent's memory.
  $('runSummary').textContent='尚未執行模擬 AI；本模式每個封數都是獨立實驗。';
  $('runProgress').style.width='0%';clear($('timeline'));clear($('feedbackSummary'));
  notice(`載入 ${n} 封虛構密電。統計結果已預先由 Python 求解器計算；尚未執行 Mock AI。`);
  render();
}
function render(){
  const r=record();if(!r)return;
  $('countMessages').textContent=r.messages.length;
  $('countCodes').textContent=Object.keys(r.statistical).length;
  const rate=x=>(100*x.correct/Math.max(1,x.total)).toFixed(1)+'%';
  $('statRate').textContent=rate(r.metrics.statistical);
  $('mockRate').textContent=rate(r.metrics.mock); // Chart and original rate intentionally remain unmarked baseline.
  renderFeedback();
  renderList();renderMessage();renderMarks();renderChart();
}
function renderList(){
  const q=$('messageSearch').value.toLocaleLowerCase(), r=record();
  const list=$('messageList');clear(list);
  let count=0;
  for(const m of r.messages){
    if(q && ![m.id,m.sender,m.recipient,...m.codes].join(' ').toLocaleLowerCase().includes(q))continue;
    count++;
    const btn=element('button','message-link'+(m.id===state.messageId?' active':''));
    btn.type='button';btn.append(element('span','id',m.id));
    btn.append(element('span','sub',`${m.sender||'未知'} → ${m.recipient||'未知'} · ${m.received_at||''}`));
    btn.append(element('span','codes',m.codes.join(' ')));
    btn.addEventListener('click',()=>{state.messageId=m.id;renderList();renderMessage();});list.append(btn);
  }
  if(!count)list.append(element('div','panelbody hint','沒有符合條件的電文'));
}
function addChip(box, code, value, opts={}){
  const active=state.code===code, chip=element('button','token'+(active?' active':'')+(opts.changed?' changed':'')+(opts.locked?' locked':''));
  if(opts.graded)chip.className+=opts.correct?' correct':' wrong';
  chip.type='button';chip.dataset.code=code;
  chip.append(element('span','term',value));chip.append(element('span','code',code));
  chip.title=`碼組 ${code}，點選查看候選`;
  chip.addEventListener('click',()=>selectCode(code));box.append(chip);
}
function renderMessage(){
  const m=selected();if(!m)return;
  $('messageTitle').textContent=`密電 ${m.id} · 當前解讀`;
  $('messageMeta').textContent=`${m.received_at||'時間未知'} ｜ ${m.sender||'未知發件'} → ${m.recipient||'未知收件'} ｜ ${m.codes.length} 個碼組`;
  for(const id of ['cipherChips','statChips','mockChips','manualChips','goldChips'])clear($(id));
  m.codes.forEach(c=>{
    addChip($('cipherChips'),c,c);
    const s=term(record().statistical,c),a=term(mockMap(),c);
    addChip($('statChips'),c,s,{graded:!!state.gold,correct:correct(record().statistical,c)});
    addChip($('mockChips'),c,state.mockReady?a:'待模擬',{changed:state.mockReady&&term(record().mock,c)!==a,graded:!!state.gold&&state.mockReady,correct:correct(mockMap(),c)});
    addChip($('manualChips'),c,manualTerm(c),{locked:!!activeMark(c).pinned});
    if(state.gold)addChip($('goldChips'),c,state.gold.codebook[c]||'無資料');
  });
  $('goldPanel').classList.toggle('hidden',!state.gold);
  if(state.gold){
    const a=m.codes.filter(c=>correct(record().statistical,c)).length;
    const b=m.codes.filter(c=>correct(mockMap(),c)).length;
    $('goldScore').textContent=`統計 ${a}/${m.codes.length}｜目前 Mock ${b}/${m.codes.length}`;
  }
  renderCode();
}
function selectCode(code){state.code=code;$('markCode').value=code;loadMarkForm();renderMessage();}
function renderCode(){
  const box=$('codeDetails');clear(box);
  if(!state.code){box.textContent='點選任何碼組，查看候選詞及 Mock 理由。';return;}
  const c=state.code,p=record().statistical[c],a=mockMap()[c];
  box.append(element('div','',`碼組 ${c}｜統計：${p?.term||'？'}｜原始 Mock：${record().mock[c]?.term||'？'}｜重評分 Mock：${state.mockReady?(a?.term||'？'):'未執行'}｜研究員：${manualTerm(c)}`));
  box.append(element('div','',`統計前五候選：${(p?.alternatives||[]).join('、')}`));
  box.append(element('div','',`Mock 前五候選：${(a?.alternatives||[]).join('、')}`));
  const reports=record().trace.flatMap(t=>t.accepted.filter(x=>x.code===c).map(x=>({t,x})));
  if(reports.length && state.mockReady){
    for(const z of reports)box.append(element('div','',`第 ${z.t.first}～${z.t.last} 封：${z.x.candidates.join('、')}。${z.x.reason}`));
  }else box.append(element('div','',state.mockReady?'此碼組沒有 Mock 建議紀錄。':'尚未執行 Mock AI。'));
  if(state.mockReady&&a?.reason)box.append(element('div','',`重評分依據：${a.reason}`));
  if(state.gold)box.append(element('div','',`合成正解：${state.gold.codebook[c]||'不明'}`));
}
function loadMarkForm(){
  const m=activeMark(state.code);
  $('markTerm').value=m.pinned||m.preferred||'';
  $('markNote').value=m.note||'';
}
function renderMarks(){
  const box=$('markCode');const old=state.code;clear(box);
  for(const c of Object.keys(record().statistical)){
    const o=element('option','',c);o.value=c;box.append(o);
  }
  if(!state.code||!record().statistical[state.code])state.code=Object.keys(record().statistical)[0];
  box.value=state.code;
  if(old!==state.code)loadMarkForm();
  $('undo').disabled=state.cursor===0;$('redo').disabled=state.cursor>=state.history.length-1;
  const entries=Object.entries(state.marks);$('markStatus').textContent=`${entries.length} 組假說；歷史版本 ${state.cursor+1}/${state.history.length}。保存於目前瀏覽器工作階段。`;
  const div=$('markList');clear(div);
  for(const [c,m] of entries){
    const line=element('div','mark-row');line.append(element('strong','',c));
    line.append(document.createTextNode(`  ${m.pinned?'試鎖:'+m.pinned:m.preferred?'偏好:'+m.preferred:''} ${m.excluded?.length?'排除:'+m.excluded.join('、'):''}`));
    const b=element('button','btn sm','查看');b.onclick=()=>selectCode(c);line.append(b);div.append(line);
  }
}
function pushMarks(next){
  if(JSON.stringify(next)===JSON.stringify(state.marks))return;
  state.history=state.history.slice(0,state.cursor+1);
  state.history.push(clone(next));if(state.history.length>61)state.history.shift();
  state.cursor=state.history.length-1;state.marks=next;
  recomputeFeedback('更新研究員標註');renderMarks();renderMessage();
}
function applyMark(kind){
  const code=state.code;if(!code)return;
  const value=$('markTerm').value.trim();
  if(kind!=='clear'&&(!value||value.length>80)){notice('請先輸入長度 1～80 字的候選詞。');return;}
  const next=clone(state.marks),prev=clone(activeMark(code));
  if(kind==='clear')delete next[code];
  else {
    if(kind==='pin'){prev.pinned=value;prev.preferred=value;prev.excluded=prev.excluded.filter(x=>x!==value);}
    if(kind==='prefer'){prev.preferred=value;prev.pinned=null;prev.excluded=prev.excluded.filter(x=>x!==value);}
    if(kind==='exclude'){if(prev.pinned===value)prev.pinned=null;if(prev.preferred===value)prev.preferred=null;if(!prev.excluded.includes(value))prev.excluded.push(value);}
    prev.note=$('markNote').value.slice(0,300);next[code]=prev;
  }
  pushMarks(next);
  notice(`已${kind==='pin'?'試鎖':kind==='prefer'?'偏好':kind==='exclude'?'排除':'清除'}碼組 ${code}。已回饋 Mock 重新評分；不會寫入已驗證碼本。`);
}
function historyMove(delta){let i=state.cursor+delta;if(i<0||i>=state.history.length)return;state.cursor=i;state.marks=clone(state.history[i]);recomputeFeedback(delta<0?'復原標註':'重做標註');renderMarks();loadMarkForm();renderMessage();notice(`已${delta<0?'復原':'重做'}研究員假說；版本 ${i+1}/${state.history.length}`);}
function resetMarks(){pushMarks({});notice('已清空目前假說，可使用復原取回上一版本。');}
function downloadFile(name,value){
  const blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob);
  const a=element('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),500);
}
function importMarks(file){
  if(!file||file.size>100000)return notice('標註檔超過 100 KB，已拒絕載入。');
  const rd=new FileReader();rd.onload=()=>{
    try{
      const json=JSON.parse(String(rd.result));if(json.format!=='han-codebook-mock-marks-v1'||json.seed!==101||!json.marks||Array.isArray(json.marks))throw Error('不是有效的 Mock 標註檔');
      const next={};
      for(const [code,m] of Object.entries(json.marks)){
        if(!/^\d+$/.test(code)||!(code in record().statistical)||typeof m!=='object'||!m||Array.isArray(m))throw Error('無效碼組');
        const terms=[m.pinned,m.preferred,...(Array.isArray(m.excluded)?m.excluded:[])].filter(v=>v!==null&&v!==undefined);
        if(terms.some(v=>typeof v!=='string'||!v||v.length>80)||typeof m.note!=='string'||m.note.length>300||terms.length>32)throw Error('標註內容不合法');
        next[code]={pinned:m.pinned||null,preferred:m.preferred||null,excluded: [...new Set(m.excluded||[])],note:m.note};
      }
      pushMarks(next);notice(`已匯入 ${Object.keys(next).length} 個碼組標註，已回饋 Mock 重新評分；仍可復原。`);
    }catch(err){notice('匯入失敗：'+err.message);}
  };rd.readAsText(file,'utf-8');
}
function svgEl(tag,attrs={}){const el=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs))el.setAttribute(k,String(v));return el;}
function renderChart(){
  const svg=$('trend');svg.setAttribute('viewBox','0 0 800 220');clear(svg);
  const coords=(idx,rate)=>[65+idx*220,175-130*rate];
  for(let t=0;t<=4;t++){
    const val=t/20;
    svg.append(svgEl('line',{x1:55,y1:175-t*32.5,x2:750,y2:175-t*32.5,stroke:'#e5ecef'}));
    const tt=svgEl('text',{x:5,y:180-t*32.5,fill:'#718796','font-size':12});tt.textContent=Math.round(val*100)+'%';svg.append(tt);
  }
  for(let i=0;i<4;i++){
    const size=state.data.records[i].size, label=svgEl('text',{x:65+i*220,y:205,'text-anchor':'middle',fill:'#607787','font-size':13});label.textContent=size+' 封';svg.append(label);
  }
  for(const [key,color] of [['statistical','#497d9b'],['mock','#d99a42']]){
    const pts=state.data.records.map((r,i)=>coords(i,r.metrics[key].correct/r.metrics[key].total));
    svg.append(svgEl('polyline',{points:pts.map(z=>z.join(',')).join(' '),fill:'none',stroke:color,'stroke-width':3}));
    pts.forEach((p,i)=>{const dot=svgEl('circle',{cx:p[0],cy:p[1],r:5,fill:color});
      const ti=svgEl('title');ti.textContent=`${state.data.records[i].size} 封：${key==='mock'?'Mock':'統計'} ${(100*state.data.records[i].metrics[key].correct/state.data.records[i].metrics[key].total).toFixed(1)}%`;dot.append(ti);svg.append(dot);});
  }
}
function addEvent(batch){
  const card=element('div','event'),head=element('div','eventhead');
  head.append(element('span','',`Mock 批次 ${batch.batch} · 第 ${batch.first}～${batch.last} 封`));
  head.append(element('span','tag',`${batch.accepted.length} 個候選`));card.append(head);
  card.append(element('p','',`模擬產生 ${batch.accepted.length} 個合法候選；不是由 Qwen 輸出。`));
  const details=element('details'),summary=element('summary','', '展開 Mock 候選與說明');details.append(summary);
  const box=element('div','evidence-list');
  for(const item of batch.accepted){const line=element('div','evidence-line');
    const b=element('button','btn sm',item.code);b.onclick=()=>selectCode(item.code);
    line.append(b,document.createTextNode(` → ${item.candidates.join('、')}：${item.reason}`));box.append(line);
  }
  details.append(box);card.append(details);$('timeline').append(card);
}
function recomputeFeedback(cause='研究員更新') {
  if(!state.mockReady||!record())return;
  if(typeof MockFeedback==='undefined')throw Error('Mock 重新評分元件未載入');
  state.feedback=MockFeedback.solve(record(),state.marks);
  if(state.feedback.changed.length)notice(`${cause}：Mock 重新評分已改變 ${state.feedback.changed.length} 個碼組；非真實 LLM 輸出。`);
  renderFeedback();
}
function renderFeedback(){
  const box=$('feedbackSummary');if(!box)return;clear(box);
  if(!state.mockReady){box.textContent='執行 Mock 後修改標註，即可比較哪些碼組受影響。';return;}
  const f=state.feedback;
  if(!f){box.textContent='尚未取得模擬重新評分結果';return;}
  box.append(element('div','',`研究員標註 ${Object.keys(state.marks).length} 組；目前相較原始 Mock 改變 ${f.changed.length} 個碼組，其中 ${f.affected.length} 組不是直接標註的碼組。`));
  box.append(element('div','hint','依密文相鄰次數和未驗證候選詞序參考加權；未改變的候選表示目前證據不足以扭轉排序。非真實 AI 思考。'));
  for(const d of f.changed.slice(0,15)){
    const line=element('div','evidence-line');
    const btn=element('button','btn sm',d.code);btn.type='button';btn.onclick=()=>selectCode(d.code);
    line.append(btn,document.createTextNode(`　${d.before} → ${d.after}（${d.marked?'人工假說':'相鄰證據連動'}）`));box.append(line);
  }
  if(f.changed.length>15)box.append(element('div','hint',`其餘 ${f.changed.length-15} 組可從電文或碼組清單點選查看。`));
  if(state.gold){
    const total=Object.keys(f.mapping).length, hits=Object.entries(f.mapping).filter(([code,v])=>v.term===state.gold.codebook[code]).length;
    box.append(element('div','',`目前 Mock 對照合成正解：${hits}/${total}（${(100*hits/Math.max(1,total)).toFixed(1)}%）；僅揭曉後評分。`));
  }
}
async function runMock(){
  if(state.busy)return;state.busy=true;$('runMock').disabled=true;state.mockReady=false;
  $('runSummary').textContent='模擬分批流程；不發出網路模型請求。';clear($('timeline'));$('runProgress').style.width='0%';
  const batches=record().trace;
  try{
    for(let i=0;i<batches.length;i++){
      notice(`Mock 批次 ${i+1}/${batches.length}：展示第 ${batches[i].first}～${batches[i].last} 封的合成候選生成……`);
      await new Promise(ok=>setTimeout(ok,380));
      addEvent(batches[i]);$('runProgress').style.width=Math.round((i+1)*100/batches.length)+'%';
    }
    state.mockReady=true;recomputeFeedback('執行模擬分析');$('runSummary').textContent=`完成 ${batches.length} 批預先計算的 MOCK 建議；已根據目前標註重新評分整份碼本。全程無外部 LLM 呼叫。`;
    notice(`模擬完成：${record().size} 封密電、${batches.length} 批。Mock 不等於真實 LLM，人工標註不算正確答案。`);
  }finally{state.busy=false;$('runMock').disabled=false;renderMessage();}
}
async function toggleGold(){
  if(state.gold){state.gold=null;$('revealGold').textContent='揭曉正確明文';renderMessage();renderFeedback();return;}
  notice('正在載入獨立的合成正確答案（展示版公開資料）……');
  try{
    const r=await fetch('/data/gold.json',{cache:'no-store'});if(!r.ok)throw Error(`HTTP ${r.status}`);
    const g=await r.json();if(g.kind!=='PUBLIC_SYNTHETIC_GOLD'||!g.codebook)throw Error('格式錯誤');
    state.gold=g;$('revealGold').textContent='隱藏正確明文';renderMessage();renderFeedback();notice('已揭曉合成答案。顏色比對僅表示與測試金標是否相同，不能證明真實密電破解。');
  }catch(e){notice('讀取合成標準答案失敗：'+e.message);}
}
async function boot(){
  try{
    const r=await fetch('/data/demo.json',{cache:'no-store'});if(!r.ok)throw Error(`HTTP ${r.status}`);
    const d=await r.json();if(d.kind!=='PUBLIC_SYNTHETIC_MOCK'||d.llm_used!==false||!Array.isArray(d.records))throw Error('不是合成 Mock 資料');
    state.data=d;
    $('volume').onchange=()=>setSize(Number($('volume').value));
    $('runMock').onclick=runMock;$('revealGold').onclick=toggleGold;
    $('messageSearch').oninput=renderList;
    $('markCode').onchange=()=>selectCode($('markCode').value);
    for(const b of document.querySelectorAll('[data-mark]'))b.addEventListener('click',()=>applyMark(b.dataset.mark));
    $('undo').onclick=()=>historyMove(-1);$('redo').onclick=()=>historyMove(1);$('resetMarks').onclick=resetMarks;
    $('exportMarks').onclick=()=>downloadFile('han-codebook-mock-marks.json',{format:'han-codebook-mock-marks-v1',seed:101,marks:state.marks});
    $('importMarks').onclick=()=>$('importFile').click();$('importFile').onchange=event=>{importMarks(event.target.files?.[0]);event.target.value='';};
    setSize(Number($('volume').value));
  }catch(e){notice('Demo 初始化失敗：'+e.message);$('runMock').disabled=true;}
}
boot();
