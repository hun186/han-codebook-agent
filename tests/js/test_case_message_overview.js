/* Offline 100/1000-message overview behavior regression. No API calls or secrets. */
'use strict';
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const js=fs.readFileSync(path.resolve(__dirname,'../../vercel-demo/workbench.js'),'utf8');
const begin=js.indexOf('// Overview reads the currently loaded case only.');
const end=js.indexOf('function loadEvidence(){',begin);
assert.ok(begin>=0&&end>begin,'overview functions must exist in the canonical mock JS');
const block=js.slice(begin,end);
const map=new Map();
function el(id){
 if(!map.has(id))map.set(id,{
   value:'',innerHTML:'',textContent:'',disabled:false,
   querySelectorAll:()=>[],scrollIntoView:()=>{},
 });
 return map.get(id);
}
const messages=Array.from({length:100},(_,i)=>{
 const n=i+1;
 return {id:'M'+String(n).padStart(3,'0'),
   codes:Array.from({length:12},(_,c)=>String(c+100+n).padStart(3,'0')),
   sender:n%2?'甲站':'乙站',recipient:'丙站',
   received_at:'1942-05-'+String((n%28)+1).padStart(2,'0'),
   domain:'logistics',notes:n===75?'secretword-75':'備註',
   observations:n%3===0?[{source:'偵察員甲',activity:'車隊',note:'補給行動 '+n,confidence:0.65}]:[]};
});
const known=[
 {message_id:'M025',segments:Array(12).fill('補給'),plaintext:'補給'.repeat(12)},
 {message_id:'M050',plaintext:'尚未逐碼切段的明文'},
];
const research={messages,known_pairs:known,gold:{hidden:'DO_NOT_RENDER_SYNTHETIC_ORACLE'}};
const escaped=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
el('caseOverviewFilter').value='all';
el('caseOverviewSort').value='original';
el('caseOverviewPageSize').value='50';
let confirmAllowed=false,loadCalls=0;
const context={research,el,esc:escaped,console,confirm:()=>confirmAllowed,
 loadEvidence:()=>{loadCalls++;const m=context.research.messages.find(x=>x.id===el('messagePick').value);vm.runInContext('overviewState.loadedMessageId='+JSON.stringify(m.id),context);el('cipherEdit').value=m.codes.join('  ');el('sender').value=m.sender;el('recipient').value=m.recipient;el('received_at').value=m.received_at;el('domain').value=m.domain||'';el('notes').value=m.notes||'';el('observations').value=JSON.stringify(m.observations||[],null,2);},
 notice:()=>{}};
vm.createContext(context);new vm.Script(block,{filename:'case-overview.js'}).runInContext(context);
const run=code=>vm.runInContext(code,context);
run('renderMessageOverview()');
assert.match(el('caseOverviewKpis').innerHTML,/100/);
assert.match(el('caseOverviewKpis').innerHTML,/研究員逐碼對照/);
assert.match(el('caseOverviewBody').innerHTML,/M001/);
assert.match(el('caseOverviewBody').innerHTML,/M050/);
assert.doesNotMatch(el('caseOverviewBody').innerHTML,/M051/);
assert.doesNotMatch(el('caseOverviewBody').innerHTML,/DO_NOT_RENDER_SYNTHETIC_ORACLE/);
assert.equal(el('caseOverviewPager').textContent,'第 1 / 2 頁');
run('overviewState.page=1;renderMessageOverview()');
assert.match(el('caseOverviewBody').innerHTML,/M051/);
assert.match(el('caseOverviewBody').innerHTML,/M100/);
assert.doesNotMatch(el('caseOverviewBody').innerHTML,/M001/);
el('caseOverviewSearch').value='secretword-75';run('overviewState.page=0;renderMessageOverview()');
assert.match(el('caseOverviewBody').innerHTML,/M075/);
assert.doesNotMatch(el('caseOverviewBody').innerHTML,/M074/);
el('caseOverviewSearch').value='';
el('caseOverviewFilter').value='aligned';run('renderMessageOverview()');
assert.match(el('caseOverviewBody').innerHTML,/M025/);
assert.doesNotMatch(el('caseOverviewBody').innerHTML,/M050/);
el('caseOverviewFilter').value='unaligned';run('renderMessageOverview()');
assert.match(el('caseOverviewBody').innerHTML,/M050/);
assert.doesNotMatch(el('caseOverviewBody').innerHTML,/M025/);
el('caseOverviewFilter').value='observed';run('renderMessageOverview()');
assert.match(el('caseOverviewMatchCount').textContent,/33 \/ 100/);
el('caseOverviewFilter').value='all';run('overviewState.expanded.add("M025");renderMessageOverview()');
assert.match(el('caseOverviewBody').innerHTML,/補給/);
assert.match(el('caseOverviewBody').innerHTML,/研究員逐碼對齊/);
assert.match(el('caseOverviewBody').innerHTML,/完整密碼組/);
assert.ok(run('selectEvidenceMessage("M025")'));
assert.equal(loadCalls,1);
el('notes').value='未套用的修改';
assert.equal(run('selectEvidenceMessage("M026")'),false);
assert.equal(el('messagePick').value,'M025');
assert.equal(loadCalls,1);
confirmAllowed=true;
assert.equal(run('selectEvidenceMessage("M026")'),true);
assert.equal(loadCalls,2);
el('caseOverviewFilter').value='all';
el('caseOverviewPageSize').value='25';
context.research.messages=Array.from({length:1000},(_,i)=>({...messages[i%100],id:'L'+String(i+1).padStart(4,'0')}));
context.research.known_pairs=[];
run('overviewState.page=0;overviewState.expanded.clear();renderMessageOverview()');
assert.equal(el('caseOverviewPager').textContent,'第 1 / 40 頁');
assert.match(el('caseOverviewBody').innerHTML,/L0025/);
assert.doesNotMatch(el('caseOverviewBody').innerHTML,/L0026/);
console.log('Case overview offline smoke PASS: 100/1000 rows, paging, filters, full plaintext, no gold, dirty-navigation guard');
