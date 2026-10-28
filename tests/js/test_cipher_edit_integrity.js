'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync(process.argv[2],'utf8');
const source=html.split('<script>')[1].split('</script>')[0];
new vm.Script(source);
const extract=(a,b)=>{
 const begin=source.indexOf(a),end=source.indexOf(b,begin+a.length);
 assert(begin>=0&&end>begin,'missing '+a);return source.slice(begin,end);
};
const ui={},messages=[];
function el(id){return ui[id]||(ui[id]={value:'',innerHTML:'',textContent:''})}
const mkIdea=word=>({term:word,source:'researcher',status:'shortlisted',note:'人工覆核'});
const mkMark=()=>({preferred:'車隊',excluded:[],pinned:false,note:'人工試驗'});
const obj={
 case_id:'research',messages:[{id:'m1',codes:['101','104'],observations:[]},
                             {id:'m2',codes:['104','105'],observations:[]}],
 profiles:{general:{keywords:[],lexicon:{},sentences:[]}},
 known_pairs:[],
 candidate_ideas:{'101':[mkIdea('車隊')],'104':[mkIdea('補給')]},
 hypothesis_marks:{'101':mkMark()}
};
let acceptCleanup=false,markHistorySaved=0,markedRefreshed=0;
const ctx={
 research:obj,
 ideaSnapshots:[{},JSON.parse(JSON.stringify(obj.candidate_ideas))],ideaCursor:1,
 markSnapshots:[{},JSON.parse(JSON.stringify(obj.hypothesis_marks))],markCursor:1,
 confirm:()=>acceptCleanup,
 notice:(v,isError)=>messages.push({v,isError}),
 el,renderObservations(){},
 persistMarkHistory(){
  markHistorySaved++;
  obj.hypothesis_revision_history={version:1,snapshots:JSON.parse(JSON.stringify(ctx.markSnapshots)),cursor:ctx.markCursor};
 },
 initializeMarks(){
  markedRefreshed++;
  const codes=[...new Set(obj.messages.flatMap(m=>m.codes))].sort();
  el('markCode').value=codes[0];
  el('markCode').options=codes.map(value=>({value,disabled:false}));
 },
 renderIdeas(){},loadMark(){},renderMarks(){},Blob
};
ctx.msg=()=>obj.messages[0];
vm.createContext(ctx);
vm.runInContext(extract('function applyEvidence()','function renderObservations()'),ctx);
vm.runInContext(extract('function navigateIdeas(','function importPreviousLLMIdeas()'),ctx);
vm.runInContext(extract('function navigateMarks(','function renderMarks()'),ctx);
function setFields(codes){
 el('cipherEdit').value=codes;
 el('observations').value='[]';
 for(const k of ['sender','recipient','notes','domain','received_at'])el(k).value='';
}
const deepcopy=x=>JSON.parse(JSON.stringify(x));

// A researcher may cancel orphan annotation cleanup; no partial mutation.
setFields('102 104');
const previous=deepcopy(obj);
ctx.applyEvidence();
assert.deepEqual(obj,previous,'cancelled cleanup caused a partial case mutation');
assert.equal(markedRefreshed,0);

// Accept the change; keep 104 because it still exists in another message.
acceptCleanup=true;
ctx.applyEvidence();
assert.deepEqual(obj.messages[0].codes,['102','104']);
assert.deepEqual(obj.candidate_ideas['104'],[mkIdea('補給')]);
assert(!('101' in obj.candidate_ideas),'orphaned idea survived');
assert(!('101' in obj.hypothesis_marks),'orphaned mark survived');
for(const snapshot of ctx.ideaSnapshots)assert(!('101' in snapshot),'undo resurrects orphan idea');
for(const snapshot of ctx.markSnapshots)assert(!('101' in snapshot),'undo resurrects orphan mark');
assert(markHistorySaved>0&&markedRefreshed>0,'mark history/dropdown not refreshed');
assert(el('markCode').options.some(o=>o.value==='102'),'new code not available in UI');
assert(!el('markCode').options.some(o=>o.value==='101'),'removed code still in UI');
ctx.navigateIdeas(-1);
assert(!('101' in obj.candidate_ideas),'undo resurrected orphan idea');
ctx.navigateIdeas(1);
assert(!('101' in obj.candidate_ideas),'redo resurrected orphan idea');
ctx.navigateMarks(-1);
assert(!('101' in obj.hypothesis_marks),'mark undo resurrected orphan mark');
ctx.navigateMarks(1);
assert(!('101' in obj.hypothesis_marks),'mark redo resurrected orphan mark');

// A known ciphertext/plaintext pair must never be silently reinterpreted.
obj.known_pairs=[{message_id:'m1',segments:['車隊','補給']}];
const existing=deepcopy(obj);
setFields('103 104');
ctx.applyEvidence();
assert.deepEqual(obj,existing,'known-plaintext pair changed with ciphertext');
assert(messages.at(-1).isError,'known-pair edit rejection did not report error');

console.log('Cipher edit cleanup, cancellation, historical snapshots, code navigation, known anchor integrity PASS');
