const el=id=>document.getElementById(id);let research=null,lastJob=null,poll=null,markSnapshots=[],markCursor=-1,markActions=[],priorResult=null,ideaSnapshots=[],ideaCursor=-1,lastLLMEntries=[];
let caseGeneration=0,lastLLMOrigin=null,vocabOrigin=null,vocabTimer=null;
let alignmentReport=null,alignmentOrigin=null,alignmentChoice=null;
let vocabRequestSerial=0,vocabActiveJobId=null,analysisRequestSerial=0,activeHumanReviewJobId=null;
function caseFingerprint(){
 if(!research)return null;
 const item={...research};delete item.hypothesis_revision_history;
 return JSON.stringify(item);
}
function captureOrigin(){return {generation:caseGeneration,caseRef:research,fingerprint:caseFingerprint()}}
function matchesCaseReference(origin){return !!(origin&&origin.generation===caseGeneration&&origin.caseRef===research)}
function matchesOrigin(origin){
 return !!(matchesCaseReference(origin)&&origin.fingerprint===caseFingerprint());
}
function invalidateOldJobs(){
 // Case replacement stops polling immediately, so cancel any pending human
 // decision at the server BEFORE dropping the old job identity.
 const staleHumanJob=activeHumanReviewJobId;
 activeHumanReviewJobId=null;
 if(staleHumanJob)api('/api/jobs/'+encodeURIComponent(staleHumanJob)+'/cancel',{})
  .catch(e=>notice('取消舊人工審核工作未成功：'+e.message,true));
 caseGeneration++;vocabRequestSerial++;vocabActiveJobId=null;analysisRequestSerial++;
 if(poll!==null){clearInterval(poll);poll=null}
 if(vocabTimer!==null){clearInterval(vocabTimer);vocabTimer=null}
 lastJob=null;lastLLMOrigin=null;vocabOrigin=null;lastLLMEntries=[];
 el('run').disabled=false;el('askVocabulary').disabled=false;
}
function notice(s,error=false){
 el('notice').textContent=s;el('notice').style.color=error?'#ffc083':'#a4b9ce';
 if(error){let toast=el('toast');toast.textContent='⚠ '+s+'（點選關閉）';toast.hidden=false;toast.onclick=()=>{toast.hidden=true}}
 else if(el('toast'))el('toast').hidden=true;
}
async function api(path,data){let opts={};if(data!==undefined)opts={method:'POST',headers:{'Content-Type':'application/json','X-Han-UI':'local'},body:JSON.stringify(data)};let res=await fetch(path,opts),val=await res.json();if(!res.ok)throw Error(val.error||res.status);return val}
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function profile(){return research.profiles[el('profilePick').value]};function msg(){return research.messages.find(m=>m.id===el('messagePick').value)}
async function listCases(){
 const cases=await api('/api/cases');
 el('caseList').innerHTML=cases.map(c=>`<option value="${esc(c.id)}">${esc(c.id)}</option>`).join('');
 await loadLLMSettings();
}
async function loadLLMSettings(){
 const cfg=await api('/api/settings');
 el('llmModel').value=cfg.model||'';
 el('llmUrl').value=cfg.base_url||'';
 el('llmTimeout').value=cfg.timeout_seconds||90;
 el('llmAllowLAN').checked=cfg.allow_private_network===true;
 el('llmKeyEnv').value=cfg.api_key_env||'';
 el('modelInfo').textContent=`${cfg.model} · ${cfg.endpoint}`;
}
async function saveLLMSettings(){
 const timeout=Number(el('llmTimeout').value);
 if(!Number.isInteger(timeout)||timeout<1||timeout>600)throw Error('請輸入 1～600 的整數等待秒數');
 if(!confirm('修改本機 LLM 端點設定？既有正在執行的工作不會改用新設定。'))return;
 const cfg=await api('/api/settings/llm',{base_url:el('llmUrl').value.trim(),
   model:el('llmModel').value.trim(),timeout_seconds:timeout,
   allow_private_network:el('llmAllowLAN').checked,api_key_env:el('llmKeyEnv').value.trim()});
 el('llmSettingStatus').textContent='設定已儲存：'+cfg.model+' · '+cfg.base_url;
 await loadLLMSettings();
}
async function testLLMSettings(){
 if(!confirm('將測試目前儲存的本機端點，僅傳送 TCP 與模型清單查詢，不傳研究案例。確定？'))return;
 el('llmSettingStatus').textContent='正在測試已儲存的模型端點...';
 const result=await api('/api/settings/test',{confirmed:true});
 el('llmSettingStatus').textContent=(result.connected?'基本連線檢查成功':'基本連線檢查未成功')+'\n'+(result.diagnostics||[]).join('\n')+'\n'+result.note;
}
function presentCase(){
 alignmentReport=null;alignmentOrigin=null;alignmentChoice=null;
 el('alignmentCandidates').textContent='尚未產生候選';el('alignmentTyped').value='';
 invalidateOldJobs();priorResult=null;vocabCandidateRecord=[];
 for(const id of ['summary','reportLink','bars','readings','roundChart','changes','exchanges','eventLinks'])el(id).replaceChildren();
 el('progress').textContent='此案例尚未執行分析';
 el('vocabProgress').textContent='';el('vocabSuggestions').replaceChildren();ideaSnapshots=[JSON.parse(JSON.stringify(research.candidate_ideas||{}))];ideaCursor=0;el('markCompare').textContent='重新分析後可與上一輪比較';el('profilePick').innerHTML=Object.keys(research.profiles).map(k=>`<option>${esc(k)}</option>`).join('');el('messagePick').innerHTML=research.messages.map(m=>`<option>${esc(m.id)}</option>`).join('');loadProfile();loadEvidence();initializeMarks();renderIdeas();renderBoldHypotheses();el('knownPairs').textContent=(research.known_pairs||[]).map(x=>`${x.message_id}: ${x.plaintext??(x.segments||[]).join('')} ${x.segments?'【逐碼對齊】':'【需要人工切詞】'}`).join('；');el('knownEdit').value=JSON.stringify(research.known_pairs||[],null,2);notice(`已載入 ${research.case_id}: ${research.messages.length} 封電文`)}
async function loadCase(){
 // Invalidate the old case immediately, before the network fetch returns.
 invalidateOldJobs();
 const requestGeneration=caseGeneration;
 const wanted=el('caseList').value;
 const loaded=await api('/api/case?id='+encodeURIComponent(wanted));
 if(requestGeneration!==caseGeneration)return;
 research=loaded;presentCase();
}
function newResearchCase(){const id=prompt('研究案例 ID（英文／數字／底線，稍後另存才會寫入檔案）','research_'+Date.now());if(!id)return;
 if(!/^[A-Za-z0-9_-]{1,50}$/.test(id)){notice('案例 ID 只能使用英文、數字、_、-（1 至 50 字元）',true);return}
 research={case_id:id,description:'研究員新建案例；待補充密碼組與候選詞',profiles:{general:{keywords:[],lexicon:{},sentences:[]}},
 messages:[{id:'MSG-001',codes:['000']}],known_pairs:[],candidate_ideas:{}};presentCase();notice('空白案例已建立於本次頁面。請修改 MSG-001 密碼組，輸入真實資料或虛構範例；按「另存案例」才會存檔。')}
function addNewMessage(){if(!research)return;let id=prompt('新電文 ID（不得與既有電文重複）','MSG-'+String(research.messages.length+1).padStart(3,'0'));if(!id)return;
 if(research.messages.some(m=>m.id===id)){notice('此電文 ID 已存在',true);return}
 let raw=prompt('輸入新電文數字碼組，以空白分隔','');if(!raw)return;let codes=raw.trim().split(/\s+/).filter(Boolean);
 if(!codes.length||codes.some(c=>!/^\d+$/.test(c))){notice('需輸入數字碼組，用空白分隔',true);return}
 research.messages.push({id,codes});el('messagePick').add(new Option(id,id));el('messagePick').value=id;loadEvidence();initializeMarks();notice('已建立 '+id+'，尚未存檔')}
function deleteMessage(){let m=msg();if(!research||!m||research.messages.length<2){notice('至少須保留一封電文',true);return}
 if(!confirm('刪除 '+m.id+'？此動作只在本次未存檔研究案例中發生。'))return;
 research.messages=research.messages.filter(x=>x!==m);
 research.known_pairs=(research.known_pairs||[]).filter(x=>x.message_id!==m.id);
 const remaining=new Set(research.messages.flatMap(x=>x.codes));
 const keep=record=>Object.fromEntries(Object.entries(record||{}).filter(([code])=>remaining.has(code)));
 research.candidate_ideas=keep(research.candidate_ideas);
 research.hypothesis_marks=keep(research.hypothesis_marks);
 // Only a still-existing trusted alignment can justify a conflicting
 // research hypothesis. A code surviving in another message is not enough.
 const survivingAnchors=verifiedCodes();
 research.bold_hypotheses=Object.fromEntries(Object.entries(keep(research.bold_hypotheses))
    .filter(([code,idea])=>survivingAnchors.has(code)&&verifiedWord(code)!==idea.term));
 // presentCase() reloads history from the persisted case object. Prune it
 // BEFORE rebuilding the editor or an old Undo can resurrect deleted codes.
 const history=research.hypothesis_revision_history;
 if(history&&Array.isArray(history.snapshots)){
  history.snapshots=history.snapshots.map(snapshot=>keep(snapshot));
 }
 // Also prune in-memory snapshots for callers still holding their references.
 ideaSnapshots=ideaSnapshots.map(snapshot=>keep(snapshot));
 markSnapshots=markSnapshots.map(snapshot=>keep(snapshot));
 presentCase()}
function newProfile(){if(!research)return;let name=prompt('新語境領域名稱（例如 logistics）','new_domain');if(!name)return;
 if(research.profiles[name]){notice('語境領域已存在',true);return}
 research.profiles[name]={keywords:[],lexicon:{},sentences:[]};el('profilePick').add(new Option(name,name));el('profilePick').value=name;loadProfile();notice('已新增語境領域；請設定詞彙或要求 LLM 提出候選')}

function loadProfile(){let p=profile();el('keywords').value=(p.keywords||[]).join(', ');el('sentences').value=(p.sentences||[]).map(a=>a.join(' ')).join('\n');renderVocab()}
function renderVocab(){let p=profile(),q=el('wordSearch').value.trim();el('vocabTable').innerHTML=Object.entries(p.lexicon||{}).filter(([k])=>k.includes(q)).map(([w,n])=>`<tr><td>${esc(w)}</td><td><input type="number" data-word="${esc(w)}" min="0" max="10000" value="${esc(n)}"></td><td><button data-delete="${esc(w)}">刪除</button></td></tr>`).join('');el('vocabTable').querySelectorAll('[data-word]').forEach(inp=>inp.addEventListener('change',()=>{let v=Number(inp.value);if(!Number.isFinite(v)||v<0){notice('權重必須為非負數',true);return}p.lexicon[inp.dataset.word]=v}));el('vocabTable').querySelectorAll('[data-delete]').forEach(b=>b.addEventListener('click',()=>{delete p.lexicon[b.dataset.delete];renderVocab()}))}
function loadEvidence(){let m=msg();if(!m)return;for(let k of ['sender','recipient','notes','domain','received_at'])el(k).value=m[k]||'';el('cipherEdit').value=m.codes.join('  ');el('observations').value=JSON.stringify(m.observations||[],null,2);renderObservations()}
function applyEvidence(){
 try{
  const m=msg();if(!m)throw Error('請先選擇電文');
  const staged={...m};
  for(const k of ['sender','recipient','notes','domain','received_at']){
   const value=el(k).value.trim();if(value)staged[k]=value;else delete staged[k];
  }
  const data=JSON.parse(el('observations').value);
  if(!Array.isArray(data))throw Error('第三方觀察需為陣列');
  for(const o of data){
   if(!o||typeof o!=='object'||Array.isArray(o)||typeof o.source!=='string'||!o.source.trim()||
      ('note' in o&&typeof o.note!=='string')||
      ('confidence' in o&&(typeof o.confidence!=='number'||!Number.isFinite(o.confidence)||o.confidence<0||o.confidence>1)))
     throw Error('觀察紀錄需有來源、有效文字備註及 0~1 的數值可信度');
  }
  staged.observations=data;
  const codes=el('cipherEdit').value.trim().split(/\s+/).filter(Boolean);
  if(!codes.length||codes.some(c=>!/^\d+$/.test(c)))throw Error('密碼組必須是以空格分隔的數字字串');
  staged.codes=codes;
  // A trusted known-plaintext alignment belongs to the exact ordered codes.
  const codeChanged=JSON.stringify(m.codes)!==JSON.stringify(codes);
  const hasCase=typeof research!=='undefined'&&research&&Array.isArray(research.messages);
  if(hasCase&&codeChanged&&(research.known_pairs||[]).some(p=>p.message_id===m.id))
   throw Error('此封電文有已知明密文對，請先獨立審核並移除對照資料，才能更動原始碼組');
  let valid=null,orphaned=[];
  if(hasCase){
   valid=new Set(research.messages.flatMap(entry=>entry===m?codes:entry.codes));
   const previous=new Set(research.messages.flatMap(entry=>entry.codes));
   orphaned=[...previous].filter(code=>!valid.has(code));
   const orphanedWithNotes=orphaned.filter(code=>
    Object.hasOwn(research.candidate_ideas||{},code)||
    Object.hasOwn(research.hypothesis_marks||{},code)||
    (typeof ideaSnapshots!=='undefined'&&ideaSnapshots.some(snapshot=>Object.hasOwn(snapshot,code)))||
    (typeof markSnapshots!=='undefined'&&markSnapshots.some(snapshot=>Object.hasOwn(snapshot,code))));
   if(orphanedWithNotes.length&&!confirm('以下碼組已不再出現，相關研究想法、標註及復原歷史將同步清除：'+orphanedWithNotes.join('、')+'。要繼續嗎？'))return;
  }
  // Commit only after *all* input and referential-integrity checks pass.
  Object.keys(m).forEach(k=>{if(!(k in staged))delete m[k]});
  Object.assign(m,staged);
  if(hasCase){
   const keep=record=>Object.fromEntries(Object.entries(record||{}).filter(([code])=>valid.has(code)));
   research.candidate_ideas=keep(research.candidate_ideas);
   research.hypothesis_marks=keep(research.hypothesis_marks);
   research.bold_hypotheses=keep(research.bold_hypotheses);
   if(typeof ideaSnapshots!=='undefined'&&ideaSnapshots.length){
    ideaSnapshots=ideaSnapshots.map(keep);
    ideaCursor=Math.min(Math.max(0,ideaCursor),ideaSnapshots.length-1);
    ideaSnapshots[ideaCursor]=JSON.parse(JSON.stringify(research.candidate_ideas));
   }
   if(typeof markSnapshots!=='undefined'&&markSnapshots.length){
    markSnapshots=markSnapshots.map(keep);
    markCursor=Math.min(Math.max(0,markCursor),markSnapshots.length-1);
    markSnapshots[markCursor]=JSON.parse(JSON.stringify(research.hypothesis_marks));
    persistMarkHistory();
   }
   initializeMarks();renderIdeas();
  }
  renderObservations();
  notice('已套用 '+m.id+' 的密文與情報'+(orphaned.length?'；已清理 '+orphaned.length+' 個不再出現的碼組及歷史':'')+'（尚未保存到磁碟）');
 }catch(e){notice(e.message,true)}
}
function renderObservations(){let data=[];try{data=JSON.parse(el('observations').value)||[]}catch(e){}el('obsCards').innerHTML=Array.isArray(data)?data.map((o,i)=>`<div class="message"><strong>觀察 ${i+1}</strong>：${esc(o.source||'未知來源')} · ${esc(o.activity||'')} · ${esc(o.destination||'')} · 可信度 ${esc(o.confidence??0.5)}　<button data-removeobs="${i}">移除</button></div>`).join(''):'';el('obsCards').querySelectorAll('[data-removeobs]').forEach(b=>b.onclick=()=>{let a=JSON.parse(el('observations').value);a.splice(Number(b.dataset.removeobs),1);el('observations').value=JSON.stringify(a,null,2);renderObservations()})}
function addObservation(){try{let data=JSON.parse(el('observations').value);if(!Array.isArray(data))throw Error('觀察資料不是陣列');let source=el('obsSource').value.trim(),n=Number(el('obsConfidence').value);if(!source||!Number.isFinite(n)||n<0||n>1)throw Error('來源不能空白，可信度須介於 0~1');data.push({source,observed_at:el('obsWhen').value.trim(),activity:el('obsActivity').value.trim(),destination:el('obsDest').value.trim(),status:el('obsStatus').value.trim(),confidence:n,note:el('obsNote').value.trim()});el('observations').value=JSON.stringify(data,null,2);renderObservations();notice('觀察已加入；按「套用此封情報」才納入分析')}catch(e){notice(e.message,true)}}
async function previewAlignmentCandidates(){
 if(!research)return notice('請先載入案例',true);
 const origin=captureOrigin(),button=el('previewAlignment');button.disabled=true;
 alignmentReport=null;alignmentOrigin=null;alignmentChoice=null;
 el('alignmentCandidates').textContent='正在產生離線候選…';
 el('alignmentTyped').value='';
 try{
  const report=await api('/api/unaligned/preview',{case:research,top_n:8,beam_width:96});
  if(!matchesOrigin(origin)){el('alignmentCandidates').textContent='案例已變更，舊候選無效';return notice('案例已變更，請重新預覽',true);}
  alignmentReport=report;alignmentOrigin=origin;
  const rows=(report.reviews||[]).flatMap(row=>(row.candidates||[]).map((candidate,i)=>({
   pair:row.known_pair_index,rank:i+1,message:row.message_id,codes:row.code_groups,segments:candidate.segments
  })));
  if(!rows.length){el('alignmentCandidates').textContent='沒有可供人工確認的完整候選；請檢查原始對照資料與固定錨點';return;}
  el('alignmentCandidates').innerHTML=rows.map(item=>`<div class="panel">
   <strong>電文 ${esc(item.message)}｜第 ${item.pair} 筆對照｜候選 #${item.rank}（未驗證）</strong>
   <div class="muted">${item.codes.map((code,i)=>esc(code)+' → '+esc(item.segments[i])).join(' ｜ ')}</div>
   <button data-alignment-pair="${item.pair}" data-alignment-rank="${item.rank}">選擇此候選供人工覆核</button>
   </div>`).join('');
  el('alignmentCandidates').querySelectorAll('[data-alignment-pair]').forEach(button=>button.onclick=()=>{
   if(!matchesOrigin(origin)){alignmentChoice=null;return notice('案例已修改，必須重新產生候選',true);}
   alignmentChoice={index:Number(button.dataset.alignmentPair),rank:Number(button.dataset.alignmentRank)};
   el('alignmentTyped').value='';
   notice('已選擇對照 #'+alignmentChoice.index+' 候選 '+alignmentChoice.rank+'；請自行逐碼重新輸入完整切段 JSON，並再次核對來源');
  });
  notice('已產生 '+rows.length+' 個待人工確認候選；沒有變更任何可信對照');
 }catch(e){
  if(matchesCaseReference(origin))el('alignmentCandidates').textContent='候選產生失敗';
  notice(e.message,true);
 }finally{button.disabled=false;}
}
async function confirmAlignmentCandidate(){
 if(!research||!alignmentReport||!alignmentChoice||!alignmentOrigin)return notice('請先產生並選擇一個候選',true);
 if(!matchesOrigin(alignmentOrigin))return notice('研究資料已變更，請重新產生候選',true);
 let segments;
 try{
  segments=JSON.parse(el('alignmentTyped').value);
  if(!Array.isArray(segments)||!segments.length||segments.some(x=>typeof x!=='string'||!x))throw Error('請輸入完整、非空的字串陣列');
 }catch(e){return notice('逐碼切段 JSON 無效：'+e.message,true);}
 if(!confirm('我已逐碼核對原始明文、密碼組與候選，並理解此步僅記錄研究員確認、不是歷史真偽證明；要將候選套用至目前頁面嗎？'))return;
 const origin=alignmentOrigin,button=el('confirmAlignment');button.disabled=true;
 try{
  const result=await api('/api/unaligned/accept',{
   case:research,report:alignmentReport,known_pair_index:alignmentChoice.index,
   candidate_rank:alignmentChoice.rank,confirmed_segments:segments,confirmed:true
  });
  if(!matchesOrigin(origin))return notice('資料在確認期間已變更；未套用舊結果，請重新預覽',true);
  if(!result||result.saved!==false||result.status!=='researcher_confirmed_not_saved'||!result.case)
   throw Error('伺服器未回傳安全的未存檔確認結果');
  research=result.case;presentCase();
  notice('研究員確認已套用到目前頁面，但尚未存檔。請使用「另存案例」建立新檔。');
 }catch(e){notice(e.message,true)}
 finally{button.disabled=false;}
}
function applyKnown(){try{
 let pairs=JSON.parse(el('knownEdit').value);if(!Array.isArray(pairs))throw Error('對照表需為陣列');
 const byId=new Map(research.messages.map(m=>[m.id,m])), anchored=new Map();
 for(const pair of pairs){const m=byId.get(pair.message_id);if(!m)throw Error('已知明文引用不存在的電文 '+pair.message_id);
  if(Array.isArray(pair.segments)){if(pair.segments.length!==m.codes.length||pair.segments.some(t=>typeof t!=='string'||!t))throw Error('逐碼明文與密碼組長度不一致');
   m.codes.forEach((c,i)=>{const w=pair.segments[i];if(anchored.has(c)&&anchored.get(c)!==w)throw Error('同一碼組的已知明文互相衝突：'+c);anchored.set(c,w)})
  }
 }
 const conflicts=[...anchored.keys()].filter(c=>Object.hasOwn(research.hypothesis_marks||{},c));
 if(conflicts.length)throw Error('請先清除以下碼組的人工假說，再套用已知明文：'+conflicts.join('、'));
 research.known_pairs=pairs;
 // Counterfactual readings remain only when a verified, different original
 // exists; never let old researcher hypotheses acquire anchor status.
 if(research.bold_hypotheses)for(const code of Object.keys(research.bold_hypotheses)){
  if(!anchored.has(code)||anchored.get(code)===research.bold_hypotheses[code].term)delete research.bold_hypotheses[code];
 }
 markSnapshots=markSnapshots.map(snapshot=>{const clean=copyMarks(snapshot);for(const code of anchored.keys())delete clean[code];return clean});persistMarkHistory();initializeMarks();if(typeof renderBoldHypotheses==='function')renderBoldHypotheses();notice('已知明密文對已套用；舊版歷史中的已驗證碼組標註已清理')
}catch(e){notice(e.message,true)}}
function saveProfile(){let p=profile();p.keywords=el('keywords').value.split(',').map(x=>x.trim()).filter(Boolean);p.sentences=el('sentences').value.split('\n').map(x=>x.trim().split(/\s+/).filter(Boolean)).filter(x=>x.length);notice('詞彙與範例句已套用（尚未保存到磁碟）')}

// Researcher marks are a reversible experiment separate from verified known pairs.
const copyMarks=marks=>JSON.parse(JSON.stringify(marks||{}));
function markedCodes(){return [...new Set((research?.messages||[]).flatMap(m=>m.codes))].sort()}
function verifiedWord(code){
 const byId=new Map((research?.messages||[]).map(m=>[m.id,m]));
 for(const pair of research?.known_pairs||[]){
  const m=byId.get(pair.message_id);
  if(m&&Array.isArray(pair.segments)&&pair.segments.length===m.codes.length){
   const idx=m.codes.indexOf(code);if(idx>=0)return pair.segments[idx];
  }
 }
 return null;
}
function verifiedCodes(){const byId=new Map((research?.messages||[]).map(m=>[m.id,m]));const locked=new Set();for(const pair of research?.known_pairs||[]){const m=byId.get(pair.message_id);if(m && Array.isArray(pair.segments)&&pair.segments.length===m.codes.length)m.codes.forEach(c=>locked.add(c))}return locked}
function persistMarkHistory(){
  // Keep the entire saved case well below the 1.5 MB HTTP body limit.
  // Drop distant history snapshots, NOT the current researcher mark state.
  for(;;){
    research.hypothesis_revision_history={version:1,cursor:markCursor,snapshots:markSnapshots.map(copyMarks),actions:[...markActions]};
    if(new Blob([JSON.stringify(research)]).size<=1000000)break;
    if(markSnapshots.length<=1){
      // The sole snapshot duplicates hypothesis_marks. Omit only the persisted
      // history (not the current marks or in-memory undo state). On reload the
      // current marks become the new first revision.
      delete research.hypothesis_revision_history;
      break;
    }
    if(markCursor>0){markSnapshots.shift();markActions.shift();markCursor--}
    else{markSnapshots.pop();markActions.pop()}
  }
}
function initializeMarks(){research.hypothesis_marks=copyMarks(research.hypothesis_marks);const old=research.hypothesis_revision_history;if(old&&old.version===1&&Array.isArray(old.snapshots)&&old.snapshots.length>0&&old.snapshots.length<=101&&Number.isInteger(old.cursor)&&old.cursor>=0&&old.cursor<old.snapshots.length&&JSON.stringify(old.snapshots[old.cursor])===JSON.stringify(research.hypothesis_marks)&&old.snapshots.every(x=>x&&typeof x==='object'&&!Array.isArray(x))){markSnapshots=old.snapshots.map(copyMarks);markCursor=old.cursor;markActions=Array.isArray(old.actions)&&old.actions.length===old.snapshots.length?old.actions.map(x=>String(x).slice(0,100)):old.snapshots.map((_,i)=>`版本 ${i}`)}else{markSnapshots=[copyMarks(research.hypothesis_marks)];markCursor=0;markActions=['原始狀態']}persistMarkHistory();const before=el('markCode').value;const locked=verifiedCodes();el('markCode').innerHTML=markedCodes().map(c=>`<option value="${esc(c)}">${esc(c)}${locked.has(c)?'（已驗證；可大膽指定）':''}</option>`).join('');if([...el('markCode').options].some(o=>o.value===before))el('markCode').value=before;loadMark();renderMarks()}
function loadMark(){
 const c=el('markCode').value,m=research?.hypothesis_marks?.[c]||{};
 const bold=(research?.bold_hypotheses||{})[c];
 el('markWord').value=bold?.term||m.preferred||'';
 el('markNote').value=bold?.note||m.note||'';
 const v=verifiedWord(c);
 el('boldStatus').textContent=v!==null?
  ('已驗證原詞：「'+v+'」'+(bold?'；目前另有紫紅色大膽假設：「'+bold.term+'」':'；若要反對此對應，須使用「大膽指定」並確認')):
  '這個碼組尚無可信逐碼明文；請使用一般偏好／排除／試鎖';
}
function commitMark(next, caption){const raw=JSON.stringify(next);if(raw===JSON.stringify(research.hypothesis_marks)){notice('標註沒有變化');return}markSnapshots=markSnapshots.slice(0,markCursor+1);markActions=markActions.slice(0,markCursor+1);markSnapshots.push(copyMarks(next));markActions.push(caption);if(markSnapshots.length>101){markSnapshots.shift();markActions.shift()}markCursor=markSnapshots.length-1;research.hypothesis_marks=copyMarks(next);persistMarkHistory();loadMark();renderMarks();notice(caption+'（尚未重新求解）')}
function modifyMark(op){if(!research)return;try{const code=el('markCode').value;if(!code||verifiedCodes().has(code))throw Error('此碼組已有可信逐碼明文，請用下方「大膽指定」建立反對假說，不得覆寫原文');const word=el('markWord').value.trim();const note=el('markNote').value.trim();if(word.length>32||note.length>500)throw Error('候選或研究註記過長');const next=copyMarks(research.hypothesis_marks);let m=next[code]||{preferred:null,excluded:[],pinned:false,note:''};if(op==='clear'){delete next[code];commitMark(next,`清除碼組 ${code} 的標註`);return}
if(!word)throw Error('請先輸入候選詞組');if(op==='exclude'){if(m.preferred===word){m.preferred=null;m.pinned=false}if(m.excluded.includes(word))m.excluded=m.excluded.filter(w=>w!==word);else m.excluded.push(word)}
if(op==='prefer'||op==='pin'){m.preferred=word;m.excluded=m.excluded.filter(w=>w!==word);m.pinned=op==='pin'}
m.note=note;next[code]=m;commitMark(next,`${code}：${op==='exclude'?'切換排除':op==='pin'?'試鎖':'偏好'} ${word}`)
}catch(e){notice(e.message,true)}}
function navigateMarks(shift){const next=markCursor+shift;if(next<0||next>=markSnapshots.length)return;markCursor=next;research.hypothesis_marks=copyMarks(markSnapshots[markCursor]);persistMarkHistory();loadMark();renderMarks();notice(`已${shift<0?'復原':'重做'}至版本 ${markCursor}（尚未重新求解）`)}
function renderMarks(){if(!research)return;el('markUndo').disabled=markCursor<=0;el('markRedo').disabled=markCursor>=markSnapshots.length-1;const marks=research.hypothesis_marks||{};el('markStatus').textContent=`目前有 ${Object.keys(marks).length} 個碼組標註；版本 ${markCursor}/${markSnapshots.length-1}；修改後需重新求解。`;
el('markList').innerHTML=Object.entries(marks).map(([code,m])=>`<div class="message"><button data-markcode="${esc(code)}">${esc(code)}</button> ${m.pinned?'📌 試鎖':m.preferred?'★ 偏好':'× 排除'} ${esc(m.preferred||'')} ${(m.excluded||[]).map(w=>`<button data-unexclude='${esc(code)}' data-word='${esc(w)}' title='取消這項排除'>× ${esc(w)}</button>`).join('')}<small> ${esc(m.note||'')}</small></div>`).join('')||'<p class="muted">目前沒有人工標註。</p>';
el('markList').querySelectorAll('[data-markcode]').forEach(b=>b.onclick=()=>{el('markCode').value=b.dataset.markcode;loadMark()});el('markList').querySelectorAll('[data-unexclude]').forEach(b=>b.onclick=()=>{el('markCode').value=b.dataset.unexclude;loadMark();el('markWord').value=b.dataset.word;modifyMark('exclude')});el('markHistory').innerHTML=markActions.map((title,index)=>`<div class="message">${index===markCursor?'●':'○'} <button data-restore="${index}">版本 ${index}</button> ${esc(title)}</div>`).join('');el('markHistory').querySelectorAll('[data-restore]').forEach(b=>b.onclick=()=>navigateMarks(Number(b.dataset.restore)-markCursor));}
function openMark(code){if(!research||!markedCodes().includes(code))return;el('tabs').querySelectorAll('button').forEach(b=>b.classList.toggle('active',b.dataset.page==='marks'));document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id==='marks'));el('markCode').value=code;loadMark();renderIdeas();el('markWord').focus()}
function applyBoldHypothesis(clear=false){
 if(!research)return;
 const code=el('markCode').value;
 if(!clear&&!verifiedCodes().has(code)){notice('大膽指定僅限已有逐碼明文錨點的碼組；未知碼請使用普通研究標註',true);return}
 const original=verifiedWord(code),word=el('markWord').value.trim(),note=el('markNote').value.trim();
 const next=JSON.parse(JSON.stringify(research.bold_hypotheses||{}));
 if(clear){
  if(!Object.hasOwn(next,code)){notice('此碼組沒有大膽假設');return}
  if(!confirm('取消 '+code+' 的大膽假設並恢復只顯示已驗證明文？'))return;
  delete next[code];
 }else{
  if(!word||word.length>32||word===original||note.length>500){notice('請填寫與已驗證原詞不同的 1～32 字假說（理由最多 500 字）',true);return}
  if(!confirm('⚠ 你正在挑戰可靠的逐碼明文：「'+code+'＝'+original+'」。\n你的大膽指定是：「'+word+'」。\n這只會建立紫紅色反對假說，不會改寫原始錨點或讓求解器認定它已證實。是否仍要保存？'))return;
  next[code]={term:word,note,confirmed:true};
 }
 research.bold_hypotheses=next;
 loadMark();renderBoldHypotheses();
 notice('已'+(clear?'取消':'保存')+'碼組 '+code+' 的大膽假說（尚未另存案例或重新分析）');
}
function renderBoldHypotheses(){
 if(!research)return;
 const bold=research.bold_hypotheses||{};
 el('boldList').innerHTML=Object.entries(bold).map(([code,v])=>
  `<div class="bold-mark"><strong>⚡ ${esc(code)}｜已知：${esc(verifiedWord(code)||'—')}</strong>　大膽假說：${esc(v.term)}<small> ${esc(v.note||'無備註')}</small></div>`).join('');
}
function renderPriorComparison(result){if(!priorResult){el('markCompare').textContent='本次是第一份分析結果，之後調整標註並重跑即可比較。';return}const a=priorResult.proposals||{},b=result.proposals||{};const changed=Object.keys(b).filter(code=>a[code]&&a[code].term!==b[code].term);el('markCompare').innerHTML=`<p>${changed.length} 個碼組的 Top-1 候選改變（不代表變好或變壞）</p>`+changed.slice(0,90).map(c=>`<div class="message"><button data-markcode="${esc(c)}">${esc(c)}</button> ${esc(a[c].term)} → ${esc(b[c].term)}</div>`).join('');el('markCompare').querySelectorAll('[data-markcode]').forEach(x=>x.onclick=()=>openMark(x.dataset.markcode))}


function copyIdeas(value){return JSON.parse(JSON.stringify(value||{}))}
function commitIdeas(next){ideaSnapshots=ideaSnapshots.slice(0,ideaCursor+1);ideaSnapshots.push(copyIdeas(next));if(ideaSnapshots.length>60)ideaSnapshots.shift();ideaCursor=ideaSnapshots.length-1;research.candidate_ideas=copyIdeas(next);renderIdeas();notice('研究員候選想法已保存於本頁案例（需另存案例才寫入磁碟；執行分析後才重新求解）')}
function renderIdeas(){if(!research||!el('ideaList'))return;const code=el('markCode').value,ideas=(research.candidate_ideas||{})[code]||[];
 el('undoIdea').disabled=ideaCursor<=0;el('redoIdea').disabled=ideaCursor>=ideaSnapshots.length-1;
 el('ideaList').innerHTML=ideas.map((o,i)=>'<div class="message"><strong>'+esc(o.term)+'</strong> · '+esc(o.source)+' · '+esc(o.status)+
 '<small> '+esc(o.note||'')+'</small> <button data-idea-remove="'+i+'">移除</button></div>').join('')||'<p class="muted">這個碼組尚無多重候選想法；可先從 LLM 建議或研究員手動提出。</p>';
 el('ideaList').querySelectorAll('[data-idea-remove]').forEach(b=>b.onclick=()=>{let v=copyIdeas(research.candidate_ideas),list=v[code]||[];
 list.splice(Number(b.dataset.ideaRemove),1);if(!list.length)delete v[code];commitIdeas(v)})}
function addResearchIdea(term,source='researcher',status='suggested',note='',code=el('markCode').value,quiet=false){
 if(!research||!markedCodes().includes(code)||verifiedCodes().has(code)){if(!quiet)notice('此碼組不存在或已有確定明文',true);return false}
 term=String(term||'').trim();if(!term||term.length>32||String(note).length>500){if(!quiet)notice('候選詞限 1~32 字，註記最多 500 字',true);return false}
 let next=copyIdeas(research.candidate_ideas),items=next[code]||[],prior=items.findIndex(x=>x.term===term);
 const value={term,source,status,note:String(note)};if(prior>=0){if(quiet)return false;items[prior]=value}else if(items.length>=12){if(!quiet)notice('單一碼組最多 12 個候選想法',true);return false}else items.push(value);
 next[code]=items;if(quiet){research.candidate_ideas=next;return true}commitIdeas(next);return true}
function navigateIdeas(direction){const n=ideaCursor+direction;if(n<0||n>=ideaSnapshots.length)return;ideaCursor=n;research.candidate_ideas=copyIdeas(ideaSnapshots[n]);renderIdeas();notice('已'+(direction<0?'復原':'重做')+'研究員候選想法（尚未重新求解）')}
function importPreviousLLMIdeas(){
 if(!matchesOrigin(lastLLMOrigin)){notice('模型候選不是來自目前這個版本的研究案例；請重新執行分析',true);return}
 if(!lastLLMEntries.length){notice('請先執行至少 1 輪本機 LLM；只有真實回覆且已接受的候選可以匯入',true);return}
 const before=copyIdeas(research.candidate_ideas);let count=0;
 for(let item of lastLLMEntries){if(!item||typeof item.code!=='string'||!Array.isArray(item.candidates))continue;
 for(let word of item.candidates.slice(0,5)){if(addResearchIdea(word,'llm','suggested',String(item.reason||'').slice(0,500),item.code,true))count++}}
 const current=copyIdeas(research.candidate_ideas);research.candidate_ideas=before;
 if(count)commitIdeas(current);
 notice('新增 '+count+' 個模型候選；重複詞組保留原有人工判定與註記，不會重新啟用已否定詞組')}
async function previewEventLinks(){
 if(!research)return;
 const origin=captureOrigin();
 try{
 const r=await api('/api/event-links',{case:JSON.parse(JSON.stringify(research))});
 if(!matchesOrigin(origin))return;
 el('eventLinks').innerHTML=r.events.map(o=>'<div class="message"><strong>'+esc(o.source)+'</strong> · '+esc(o.observed_at)+' · '+esc(o.activity)+
 '<br><small>'+esc(o.status)+' · 可信度 '+esc(o.confidence)+' · '+esc(o.event_id)+'</small>'+
 o.candidates.map(c=>'<div>可能相關：'+(c.message_id?'<button data-event-message="'+esc(c.message_id)+'">'+esc(c.message_id)+'</button>':'<strong>完全無關</strong>')+
 ' · 相對權重 '+esc(c.score)+(c.day_offset===undefined?'':' · 日差 '+esc(c.day_offset))+
 ' · '+esc(c.basis)+'</div>').join('')+'</div>').join('')||'<p class="muted">目前尚無第三方目擊紀錄。</p>';
 el('eventLinks').querySelectorAll('[data-event-message]').forEach(b=>b.onclick=()=>{
 if(!matchesOrigin(origin)){notice('事件關聯建議已不屬於目前案例，請重新分析',true);return}
 el('messagePick').value=b.dataset.eventMessage;loadEvidence();notice('已切換電文；這只是時間相關候選，不等於確認連結')});
 }catch(e){notice('事件時序分析失敗：'+e.message,true)}}
let vocabCandidateRecord=[];
function renderVocabularyIdeas(){
 if(!matchesOrigin(vocabOrigin)){el('vocabSuggestions').replaceChildren();return}
 const displayedJobSerial=vocabRequestSerial;
 el('vocabSuggestions').innerHTML=vocabCandidateRecord.map((x,i)=>'<div class="message"><strong>'+esc(x.term)+'</strong> <small>'+esc(x.reason||'未附理由')+
 '</small> <button data-adopt-vocab="'+i+'">加入目前領域詞庫</button></div>').join('');
 el('vocabSuggestions').querySelectorAll('[data-adopt-vocab]').forEach(b=>b.onclick=()=>{
 if(displayedJobSerial!==vocabRequestSerial||!matchesOrigin(vocabOrigin)){notice('研究案例或 LLM 工作已變更；此批詞庫建議不可採納，請重新產生',true);return}
 const selected=vocabCandidateRecord[Number(b.dataset.adoptVocab)];if(!selected)return;
 const word=selected.term;
 profile().lexicon[word]=Math.max(1,Number(profile().lexicon[word]||2));vocabOrigin={...vocabOrigin,fingerprint:caseFingerprint()};renderVocab();notice('已將未驗證候選「'+word+'」加入 '+el('profilePick').value+' 詞庫；另存案例後持久化')})}
async function askVocabulary(){
 if(!research)return;
 const origin=captureOrigin();
 if(!confirm('只將目前密電與可觀察情報傳給 config.yaml 指定的內網 LLM 產生詞庫候選。不是已知明文。確定呼叫？'))return;
 // Every submission gets its own request generation, independent of case
 // fingerprint. A late GET from an already completed job must not win.
 const serial=++vocabRequestSerial;
 vocabActiveJobId=null;vocabOrigin=null;vocabCandidateRecord=[];
 el('vocabSuggestions').replaceChildren();
 if(vocabTimer!==null){clearInterval(vocabTimer);vocabTimer=null}
 const current=()=>serial===vocabRequestSerial&&matchesOrigin(origin);
 try{
  const response=await api('/api/suggest-vocabulary',{
    case:JSON.parse(JSON.stringify(research)),confirmed:true,
    use_metadata:el('metadata').value==='true'});
  if(!current())return;
  const jobId=response.job_id;
  vocabActiveJobId=jobId;
  const active=()=>current()&&vocabActiveJobId===jobId;
  el('askVocabulary').disabled=true;
  el('vocabProgress').textContent='正在請模型產生候選詞庫；不會自動寫入研究員詞庫';
  let localTimer=null;
  function stopVocabTimer(){if(localTimer!==null)clearInterval(localTimer);if(vocabTimer===localTimer)vocabTimer=null}
  async function update(){
   if(!active()){
    stopVocabTimer();
    if(current()===false&&serial===vocabRequestSerial&&matchesCaseReference(origin)){
     vocabActiveJobId=null;vocabRequestSerial++;el('askVocabulary').disabled=false;
     notice('案例已修改，舊詞庫建議已失效；請重新產生');
    }
    return;
   }
   try{
    const job=await api('/api/jobs/'+jobId);
    if(!active()){
     stopVocabTimer();
     if(serial===vocabRequestSerial&&matchesCaseReference(origin)){
      vocabActiveJobId=null;vocabRequestSerial++;el('askVocabulary').disabled=false;
      notice('資料修改後的舊詞庫建議已隔離，請重新產生');
     }
     return;
    }
    el('vocabProgress').textContent=(job.logs||[]).join('\n')+(job.error?'\nERROR: '+job.error:'');
    if(job.status==='completed'||job.status==='failed'){
     stopVocabTimer();
     vocabActiveJobId=null;vocabRequestSerial++; // retire all outstanding GETs from this job
     el('askVocabulary').disabled=false;
     if(job.status==='completed'){
      vocabCandidateRecord=job.result.terms||[];vocabOrigin=origin;renderVocabularyIdeas();
      notice('模型產生 '+vocabCandidateRecord.length+' 個待審詞組，請逐項採納');
     }else notice('詞庫生成失敗：'+job.error,true);
    }
   }catch(e){
    stopVocabTimer();
    // A changed case fingerprint makes active() false, but the failing
    // request still owns the disabled control until its serial is retired.
    if(serial===vocabRequestSerial&&matchesCaseReference(origin)&&vocabActiveJobId===jobId){
     vocabActiveJobId=null;vocabRequestSerial++;
     el('askVocabulary').disabled=false;
     notice(matchesOrigin(origin)?e.message:'案例內容已修改，舊詞庫工作失效；請重新產生',!matchesOrigin(origin));
    }
   }
  }
  localTimer=setInterval(update,1500);vocabTimer=localTimer;update();
 }catch(e){if(current()){vocabActiveJobId=null;vocabRequestSerial++;el('askVocabulary').disabled=false;notice(e.message,true)}}
}

function chartBar(label,value,max=1){let val=Number(value)||0;return `<div class="chartrow"><span>${esc(label)}</span><div class="track"><div class="fill" style="width:${Math.max(0,Math.min(100,val/max*100))}%"></div></div><span>${esc(val.toFixed(2))}</span></div>`}
function lineChart(values){if(values.length<2)return '<p class="muted">至少兩個時間點才能繪製趨勢。</p>';let ys=values.map(v=>v.score),lo=Math.min(...ys),hi=Math.max(...ys),extent=hi-lo||1;let points=values.map((v,i)=>`${26+i*520/(values.length-1)},${160-(v.score-lo)/extent*125}`).join(' ');return `<svg viewBox="0 0 580 200" role="img" aria-label="逐輪統計目標分數趨勢" style="width:100%;max-height:250px"><line x1="26" y1="160" x2="550" y2="160" stroke="#4f6276"/><polyline points="${points}" fill="none" stroke="#4bd0bc" stroke-width="3"/>${values.map((v,i)=>{let x=26+i*520/(values.length-1),y=160-(v.score-lo)/extent*125;return `<circle cx="${x}" cy="${y}" r="5" fill="#4bd0bc"/><text x="${x}" y="182" fill="#a4b9ce" font-size="11" text-anchor="middle">${i===0?'Baseline':'R'+i}</text>`}).join('')}</svg>`}
function renderBenchmark(report){let rows=report.runs||[];el('benchmarkCharts').innerHTML='<h3>未知碼組 Top-1 正確率（依是否提供元數據）</h3>'+rows.map(x=>`<div class="message"><strong>${esc(x.case_id)}</strong> · 元數據 ${x.metadata?'有':'無'}${chartBar('Top-1 正確率',x.metrics.unknown_code_top1_rate??0,1)}${chartBar('完整電文正確率',x.metrics.non_crib_exact_rate??0,1)}<small>錨點 ${x.metrics.verified_anchor_count} · 未知碼 ${x.metrics.unknown_code_count} · 僅供合成基準評估</small></div>`).join('')+'<p class="alert">這些百分比是本套合成測試的評分，不表示能破解未知真實密電；語言詞彙與示例已提供給求解器。</p>'}
function renderJob(j){const origin=arguments.length>1?arguments[1]:null;if(origin&&!matchesOrigin(origin))return;if(j.type==='benchmark'){el('benchmarkProgress').textContent=j.logs.join('\n')||j.status;if(j.status==='completed')renderBenchmark(j.result);if(j.error)el('benchmarkProgress').textContent+='\nERROR: '+j.error;return}el('progress').textContent=j.logs.join('\n')||j.status;if(j.error)el('progress').textContent+='\nERROR: '+j.error;if(origin&&!matchesOrigin(origin))return;renderTrace(j);if(j.status!=='completed')return;
 if(origin&&!matchesOrigin(origin))return;
 lastLLMEntries=(j.events||[]).filter(x=>x.stage==='llm_proposals_unverified').flatMap(x=>x.payload.accepted||[]);
 lastLLMOrigin=origin;let result=j.result,proposals=Object.entries(result.proposals),anchored=proposals.filter(([,p])=>p.status==='verified_alignment').length;el('summary').innerHTML=`<div class="kpi"><div><small>分析電文</small><strong>${result.decoded_messages.length}</strong></div><div><small>已驗證碼組</small><strong>${anchored}</strong></div><div><small>待驗證碼組</small><strong>${proposals.length-anchored}</strong></div><div><small>完成 LLM 回合</small><strong>${result.agent_rounds_completed}</strong></div></div><p class="alert">候選排名與分數不等於破解成功率。必須使用獨立金標資料評估。</p>`;
let domCounts={};for(let m of result.decoded_messages)domCounts[m.domain_inferred||'未知']=(domCounts[m.domain_inferred||'未知']||0)+1;el('reportLink').innerHTML=`<a href="/api/jobs/${esc(j.id)}/report.docx" download style="color:#4bd0bc">下載研究分析報告（Word）</a>　｜　<a href="/api/jobs/${esc(j.id)}/report.md" download style="color:#4bd0bc">下載 Markdown</a>`;el('bars').innerHTML=chartBar('錨點占比',anchored/proposals.length,1)+chartBar('待驗證占比',(proposals.length-anchored)/proposals.length,1)+'<h3>電文領域分布</h3>'+Object.entries(domCounts).map(([k,n])=>chartBar(k,n,result.decoded_messages.length)).join('');
el('readings').innerHTML='<table><thead><tr><th>電文</th><th>每個碼組的目前候選（點選可標註）</th><th>確定碼組</th></tr></thead><tbody>'+result.decoded_messages.map(x=>`<tr><td>${esc(x.id)}<br><small>${esc(x.domain_inferred||'未知')}</small></td><td>${x.codes.map((c,i)=>`<button class="hypo-read ${research?.bold_hypotheses?.[c]?'bold-code':result.proposals[c]?.status==='verified_alignment'?'verified-code':''}" data-readcode="${esc(c)}" title="${research?.bold_hypotheses?.[c]?'紫紅：大膽指定未驗證假說，原始明文仍保留':result.proposals[c]?.status==='verified_alignment'?'綠色：已有可信逐碼明文，點選可記錄反對假說':'藍色：未驗證候選'}">${esc(research?.bold_hypotheses?.[c]?.term||x.suggested_segments[i])}${research?.bold_hypotheses?.[c]?'<small>⚡大膽假說</small>':''}<small>${esc(c)}</small></button>`).join('')}</td><td>${x.verified_codes}/${x.total_codes}</td></tr>`).join('')+'</tbody></table>';
el('readings').querySelectorAll('[data-readcode]').forEach(b=>b.onclick=()=>{openMark(b.dataset.readcode);if(!el('markWord').value)el('markWord').value=result.proposals[b.dataset.readcode]?.term||''});renderPriorComparison(result);priorResult=JSON.parse(JSON.stringify(result));

}
function renderTrace(j){let failedNotice=j.status==='failed'?'<p class="alert">分析失敗；以下為失敗前已取得的部分稽核事件，並非已完成的破譯。</p>':'';let events=j.events||[];let rounds=events.filter(x=>x.stage==='statistical_baseline'||x.stage==='rescore');el('roundChart').innerHTML=failedNotice+lineChart(rounds.map(x=>({score:x.payload.score})))+rounds.map(x=>`<div class="message"><strong>${x.stage==='statistical_baseline'?'Baseline':'Round '+x.round}</strong>　內部目標分數：${esc(x.payload.score)}<br><small>相較上一輪變更：${x.payload.changed_count??'—'} 碼</small></div>`).join('')+'<small>目標分數不是機率，不適合跨不同資料集直接比較。</small>';
el('changes').innerHTML=events.filter(x=>x.stage==='rescore').map(x=>`<details><summary>Round ${x.round}: ${Object.keys(x.payload.changes||{}).length} 個變更</summary><pre>${esc(JSON.stringify(x.payload.changes||{},null,2))}</pre></details>`).join('');
let phases=[
 {name:'動態候選詞庫',request:'vocabulary_llm_request',response:'vocabulary_llm_response'},
 {name:'碼組候選',request:'llm_request',response:'llm_response'}
];
let proposed=events.filter(x=>x.stage==='llm_proposals_unverified');
let vocabRounds=events.filter(x=>x.stage==='vocabulary_candidates_unverified');
let requestRecords=phases.flatMap(phase=>{
 const responses=events.filter(x=>x.stage===phase.response);
 return events.filter(x=>x.stage===phase.request).map(x=>({
  ...x,phase:phase.name,
  response:responses.find(r=>r.round===x.round)?.payload||null
 }));
});
el('exchanges').innerHTML=vocabRounds.map(x=>
 `<div class="message"><strong>Round ${x.round} · 動態詞庫（未驗證）</strong>　新增採納 ${esc(x.payload.approved?.length||0)} 詞，拒絕 ${esc(x.payload.rejected_count||0)} 詞 · ${esc(x.payload.review_mode)}</div>`
).join('')+proposed.map(x=>
 `<details><summary>Round ${x.round}：碼組建議接受 ${x.payload.accepted?.length||0} 項；拒絕 ${x.payload.rejected_count||0} 項</summary><pre>${esc(JSON.stringify(x.payload.accepted,null,2))}</pre></details>`
).join('')+requestRecords.map(x=>{
 const v=x.response||{};
 return `<details><summary>Round ${x.round} · ${esc(x.phase)}：完整請求與回覆</summary>
 <p class="muted">HTTP ${esc(v.http_status??200)} · API ${esc((Number(v.elapsed_ms||0)/1000).toFixed(1))} 秒 · token：${esc(JSON.stringify(v.usage||'未提供'))}</p>
 <h3>送往 LLM 的訊息</h3><pre>${esc(JSON.stringify(x.payload.body,null,2))}</pre>
 <h3>API 原始回覆</h3><pre>${esc(v.response||'尚無對應回覆')}</pre></details>`;
}).join('');
if(!requestRecords.length)el('exchanges').innerHTML+='<p class="muted">尚無完整 Prompt 擷取資料（可能未啟用，或此次尚未呼叫模型）。</p>';
}
async function startBenchmark(){try{let id=(await api('/api/start-benchmark',{})).job_id;el('runBenchmark').disabled=true;notice('基準評測已啟動');let timer=setInterval(async()=>{try{let j=await api('/api/jobs/'+id);renderJob(j);if(['completed','failed'].includes(j.status)){clearInterval(timer);el('runBenchmark').disabled=false;notice(j.status==='completed'?'基準評測完成':'基準評測失敗：'+j.error,j.status==='failed')}}catch(e){clearInterval(timer);el('runBenchmark').disabled=false;notice(e.message,true)}},1300)}catch(e){notice(e.message,true)}}
function renderPendingVocabularyReview(j,origin){
 const pane=el('pendingVocabularyReview');
 pane.dataset ||= {};
 const pending=j.status==='awaiting_review'?j.pending_review:null;
 if(!pending || !matchesOrigin(origin)){
  pane.hidden=true;pane.replaceChildren();pane.dataset.reviewKey='';return;
 }
 const key=j.id+':'+pending.round+':'+pending.review_token;
 if(pane.dataset.reviewKey!==key){
  pane.dataset.reviewKey=key;pane.hidden=false;
  pane.innerHTML='<h3>第 '+esc(pending.round)+' 輪候選詞人工覆核（全部均未驗證）</h3>'+
   '<p class="muted">只勾選要加入未驗證候選詞庫的項目。清空勾選代表全部拒絕，繼續下一步。</p>'+
   pending.candidates.map((x,i)=>'<label><input type="checkbox" data-review-term="'+i+'" checked> '+
     esc(x.term)+' <small>'+esc(x.reason||'')+'</small></label>').join('')+
   '<label for="reviewAddedWords"><strong>研究員新增候選詞</strong>（選填，每行一詞）</label>'+
   '<textarea id="reviewAddedWords" rows="4" maxlength="1500" spellcheck="false" placeholder="例：補給線&#10;前線集結"></textarea>'+
   '<p class="muted">可以全部不勾 LLM 建議，只加入自己提出的詞；本輪合計最多 32 個、單詞最多 24 字，所有新增詞仍是未驗證假說。</p>'+
   '<button class="primary" id="approveVocabulary">提交選詞與新增詞，繼續推論</button>';
  pane.querySelector('#approveVocabulary').onclick=async()=>{
   if(!matchesOrigin(origin)){notice('案例已變更，舊的人工覆核不再有效',true);return}
   const approved=Array.from(pane.querySelectorAll('input[data-review-term]:checked'))
     .map(x=>pending.candidates[Number(x.dataset.reviewTerm)].term);
   const rawAdded=pane.querySelector('#reviewAddedWords').value;
   const added=rawAdded.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
   if(approved.length+added.length>32){notice('本輪候選詞（勾選＋手動新增）合計不可超過 32 個',true);return}
   if(added.some(w=>w.length>24||/[\x00-\x1f]/.test(w)) ||
      new Set(added).size!==added.length ||
      added.some(w=>approved.includes(w)||pending.candidates.some(x=>x.term===w))){
    notice('新增詞須是 1～24 字、不重複、不可與 LLM 候選詞相同',true);return;
   }
   const button=pane.querySelector('#approveVocabulary');button.disabled=true;
   try{
    await api('/api/jobs/'+encodeURIComponent(j.id)+'/review',{
     approved,added,round:pending.round,review_token:pending.review_token
    });
    button.textContent='已提交，模型繼續運算中…';
   }catch(e){button.disabled=false;notice('人工覆核未送出：'+e.message,true)}
  };
 }
 const submit=pane.querySelector('#approveVocabulary');
 if(submit&&j.review_submitted){submit.disabled=true;submit.textContent='已提交，模型繼續運算中…'}
}
async function start(){
 if(!research)return;
 const origin=captureOrigin();
 const rounds=Number(el('rounds').value);
 if(!Number.isInteger(rounds)||rounds<0||rounds>20){notice('LLM 回合數必須是 0～20 整數；0 代表離線分析',true);return}
 const candidateMode=el('candidateMode').value;
 if(candidateMode!=='static'&&rounds===0){notice('逐回合動態候選至少需要 1 個 LLM 回合',true);return}
 if(rounds>0&&!confirm(`將電文與情報傳送到 config.yaml 指定的內網 LLM，共 ${rounds} 回合；候選模式：${candidateMode==='human'?'每輪人工確認':candidateMode==='automatic'?'自動擴充詞庫':'既有詞庫'}。確定執行？`))return;
 const serial=++analysisRequestSerial;
 const current=()=>serial===analysisRequestSerial&&matchesOrigin(origin);
 lastJob=null;
 if(poll!==null){clearInterval(poll);poll=null}
 try{
  const inferenceCase=JSON.parse(JSON.stringify(research));
  delete inferenceCase.hypothesis_revision_history;
  const queued=await api('/api/start',{case:inferenceCase,rounds,
    use_metadata:el('metadata').value==='true',capture_llm_io:el('capture').checked,
    candidate_mode:candidateMode});
  const jobId=queued.job_id;
  if(!current()){
   if(candidateMode==='human'){
    try{await api('/api/jobs/'+encodeURIComponent(jobId)+'/cancel',{})}catch(_e){}
   }
   return;
  }
  lastJob=jobId;
  if(candidateMode==='human')activeHumanReviewJobId=jobId;
  const active=()=>current()&&lastJob===jobId;
  let reviewCancellationSent=false;
  async function cancelStaleHumanReview(){
   if(candidateMode!=='human'||reviewCancellationSent)return;
   reviewCancellationSent=true;
   if(activeHumanReviewJobId===jobId)activeHumanReviewJobId=null;
   try{
    await api('/api/jobs/'+encodeURIComponent(jobId)+'/cancel',{});
    notice('研究案例已變更：正在取消舊人工審核工作，未審候選不會被採納',true);
   }catch(e){notice('取消舊人工審核工作未成功：'+e.message,true)}
  }
  for(let k of ['summary','reportLink','bars','readings','roundChart','changes','exchanges'])el(k).innerHTML='';
  const reviewPane=el('pendingVocabularyReview');
  reviewPane.hidden=true;reviewPane.dataset ||= {};reviewPane.dataset.reviewKey='';
  reviewPane.replaceChildren();
  el('run').disabled=true;notice('已啟動研究 '+jobId);
  let localPoll=null;
  function stopPoll(){if(localPoll!==null)clearInterval(localPoll);if(poll===localPoll)poll=null}
  async function update(){
   if(!active()){
    stopPoll();
    await cancelStaleHumanReview();
    if(serial===analysisRequestSerial&&matchesCaseReference(origin)){
     analysisRequestSerial++;el('run').disabled=false;
     notice('研究資料已變更，舊分析不會再套用；需要重新執行')
    }
    return;
   }
   try{
    const result=await api('/api/jobs/'+jobId);
    if(!active()){
     stopPoll();
     await cancelStaleHumanReview();
     if(serial===analysisRequestSerial&&matchesCaseReference(origin)){
      analysisRequestSerial++;el('run').disabled=false;
      notice('研究資料已變更，舊分析回覆已隔離；請重新執行')
     }
     return;
    }
    renderJob(result,origin);
    renderPendingVocabularyReview(result,origin);
    if(['completed','failed'].includes(result.status)){
     if(activeHumanReviewJobId===jobId)activeHumanReviewJobId=null;
     stopPoll();analysisRequestSerial++; // retire all concurrent GETs for this job
     el('run').disabled=false;
     notice(result.status==='completed'?'執行完成：結果已存入 artifacts/web_runs/'+jobId:'執行失敗：'+result.error,result.status==='failed');
    }
   }catch(e){
    if(candidateMode==='human'&&active()){
     // Retain the same job and scheduled GETs after a temporary network error.
     // Abandoning polling would strand an awaiting_review job until timeout.
     notice('人工覆核工作查詢暫時失敗，正在保留同一工作並重試：'+e.message,true);
     return;
    }
    stopPoll();
    if(!current())await cancelStaleHumanReview();
    // Restore only the control still owned by this request. Same-case edits
    // invalidate content fingerprints but must not strand a disabled button.
    if(serial===analysisRequestSerial&&matchesCaseReference(origin)&&lastJob===jobId){
     analysisRequestSerial++;lastJob=null;
     el('run').disabled=false;
     notice(matchesOrigin(origin)?e.message:'研究資料已修改，舊分析工作失效；請重新執行',!matchesOrigin(origin));
    }
   }
  }
  localPoll=setInterval(update,1300);poll=localPoll;update();
 }catch(e){if(current()){analysisRequestSerial++;notice(e.message,true);el('run').disabled=false}}
}

async function save(){if(!research)return;let name=prompt('輸入新案例英文檔名（不含副檔名）：','research_'+Date.now());if(!name)return;try{let s=await api('/api/save',{case:research,name});notice('保存成功：'+s.saved_as);await listCases();el('caseList').value=s.saved_as}catch(e){notice(e.message,true)}}
document.querySelectorAll('[data-go-page]').forEach(b=>b.onclick=()=>{
 const target=el('tabs').querySelector('[data-page="'+b.dataset.goPage+'"]');
 if(target)target.click();
});
el('tabs').querySelectorAll('button').forEach(b=>b.onclick=()=>{el('tabs').querySelectorAll('button').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.querySelectorAll('.page').forEach(p=>p.classList.toggle('active',p.id===b.dataset.page))});
el('markCode').onchange=()=>{loadMark();renderIdeas()};el('boldSet').onclick=()=>applyBoldHypothesis(false);el('boldClear').onclick=()=>applyBoldHypothesis(true);el('markPrefer').onclick=()=>modifyMark('prefer');el('markExclude').onclick=()=>modifyMark('exclude');el('markPin').onclick=()=>modifyMark('pin');el('markClear').onclick=()=>modifyMark('clear');el('markUndo').onclick=()=>navigateMarks(-1);el('markRedo').onclick=()=>navigateMarks(1);el('markReset').onclick=()=>commitMark({},'重設全部人工標註');el('markRun').onclick=()=>{el('tabs').querySelector('[data-page=overview]').click();start()};el('newCase').onclick=newResearchCase;el('addMessage').onclick=addNewMessage;el('delMessage').onclick=deleteMessage;el('newProfile').onclick=newProfile;
el('addIdea').onclick=()=>addResearchIdea(el('ideaTerm').value,el('ideaSource').value,el('ideaStatus').value,el('ideaNote').value);
el('undoIdea').onclick=()=>navigateIdeas(-1);el('redoIdea').onclick=()=>navigateIdeas(1);
el('importLLMIdeas').onclick=importPreviousLLMIdeas;el('checkEvents').onclick=previewEventLinks;
el('askVocabulary').onclick=askVocabulary;
el('llmPreset').onchange=()=>{
 const preset=el('llmPreset').value;
 if(preset==='ollama'&&!el('llmUrl').value.trim())el('llmUrl').value='http://127.0.0.1:11434';
 el('llmSettingStatus').textContent=preset==='ollama'?
   'Ollama 適用本機／內網 OpenAI-compatible /v1/chat/completions；請確認實際埠號與模型名稱。':
   '自訂內網相容端點：僅接受 loopback 或明確允許的私人 IPv4。';
};
el('saveLLM').onclick=()=>saveLLMSettings().catch(e=>notice(e.message,true));el('testLLM').onclick=()=>testLLMSettings().catch(e=>notice(e.message,true));
el('loadCase').onclick=()=>loadCase().catch(e=>notice(e.message,true));el('profilePick').onchange=loadProfile;el('messagePick').onchange=loadEvidence;el('wordSearch').oninput=renderVocab;el('addWord').onclick=()=>{let w=el('newWord').value.trim(),n=Number(el('newWeight').value);if(w&&Number.isFinite(n)&&n>=0){profile().lexicon[w]=n;el('newWord').value='';renderVocab()}};el('saveProfile').onclick=saveProfile;el('applyEvidence').onclick=applyEvidence;el('addObservation').onclick=addObservation;el('applyKnown').onclick=applyKnown;el('previewAlignment').onclick=previewAlignmentCandidates;el('confirmAlignment').onclick=confirmAlignmentCandidate;el('run').onclick=start;el('save').onclick=save;el('runBenchmark').onclick=startBenchmark;el('loadBenchmark').onclick=()=>api('/api/benchmark').then(renderBenchmark).catch(e=>notice(e.message,true));listCases().then(loadCase).catch(e=>notice(e.message,true));
