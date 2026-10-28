'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
const html = fs.readFileSync(process.argv[2], 'utf8');
const source = html.split('<script>')[1].split('</script>')[0];
new vm.Script(source);
const get=(start,end)=>{
 const i=source.indexOf(start),j=source.indexOf(end,i+start.length);
 assert(i>=0&&j>i,'function unavailable: '+start);
 return source.slice(i,j);
};
const copy=x=>JSON.parse(JSON.stringify(x));
const mark={preferred:'車隊',excluded:[],pinned:false,note:'previously marked'};
const idea={term:'車隊',source:'researcher',status:'rejected',note:'checked'};
const caseData={
 case_id:'delete-history-case',
 messages:[{id:'m1',codes:['101']},{id:'m2',codes:['104']}],
 profiles:{general:{keywords:[],lexicon:{},sentences:[]}},
 known_pairs:[],
 candidate_ideas:{'101':[idea]},
 hypothesis_marks:{},
 hypothesis_revision_history:{
  version:1,cursor:1,snapshots:[{'101':mark},{}],actions:['marked 101','cleared 101']
 }
};
const ui={};let confirmDeletion=true,rendered=0;
function el(id){
 if(!ui[id]){
  const element={value:'',textContent:'',options:[],disabled:false,
    querySelectorAll(){return []},
    replaceChildren(){this.innerHTML='';this.options=[]}};
  let markup='';
  Object.defineProperty(element,'innerHTML',{
   get(){return markup},
   set(v){markup=String(v);if(id==='markCode'){
    this.options=[...markup.matchAll(/<option value="([^"]+)"([^>]*)>/g)]
       .map(x=>({value:x[1],disabled:x[2].includes('disabled')}));
    if(!this.options.some(x=>x.value===this.value&&!x.disabled))
      this.value=this.options.find(x=>!x.disabled)?.value||'';
   }}
  });
  ui[id]=element;
 }
 return ui[id];
}
const ctx={
 research:caseData,Blob,
 markSnapshots:[],markCursor:-1,markActions:[],
 ideaSnapshots:[{'101':[idea]},{}],ideaCursor:1,
 msg(){return ctx.research.messages[0]},
 el,notice(){},confirm:()=>confirmDeletion,
 esc:x=>String(x),copyMarks:copy,copyIdeas:copy,
 markedCodes(){return [...new Set(ctx.research.messages.flatMap(m=>m.codes))].sort()},
 verifiedCodes(){return new Set()},
 loadMark(){},renderMarks(){rendered++},renderIdeas(){},
 presentCase(){
  ctx.ideaSnapshots=[copy(ctx.research.candidate_ideas)];ctx.ideaCursor=0;
  ctx.initializeMarks();
 }
};
vm.createContext(ctx);
vm.runInContext(get('function persistMarkHistory()','function initializeMarks()'),ctx);
vm.runInContext(get('function initializeMarks()','function loadMark()'),ctx);
vm.runInContext(get('function navigateMarks(','function renderMarks()'),ctx);
vm.runInContext(get('function deleteMessage()','function newProfile()'),ctx);

// The current marks are empty; an old snapshot still contains a code that
// occurs only in the message about to be deleted. Cancel means no mutation.
confirmDeletion=false;
const beforeDeletion=copy(ctx.research);
ctx.deleteMessage();
assert.deepEqual(copy(ctx.research),beforeDeletion,'cancelling delete altered the case');
confirmDeletion=true;
ctx.deleteMessage();
assert.deepEqual(copy(ctx.research.messages.map(m=>m.id)),['m2']);
assert(!('101' in ctx.research.candidate_ideas),'orphan idea was not removed');
assert(!('101' in ctx.research.hypothesis_marks),'orphan current mark was not removed');
assert.equal(rendered>0,true,'history was not reloaded after deletion');
assert.deepEqual(copy(ctx.research.hypothesis_revision_history.snapshots),[{},{}]);
assert.deepEqual(copy(ctx.markSnapshots),[{},{}]);
assert.deepEqual(copy(ctx.ideaSnapshots),[{}], 'old idea history not discarded on case presentation');
assert.equal(el('markCode').value,'104','code menu was not refreshed');
ctx.navigateMarks(-1);
assert(!('101' in ctx.research.hypothesis_marks),'undo resurrected deleted-code mark');
ctx.navigateMarks(1);
assert(!('101' in ctx.research.hypothesis_marks),'redo resurrected deleted-code mark');
assert(!Object.keys(ctx.research.hypothesis_revision_history.snapshots)
  .some(i=>'101' in ctx.research.hypothesis_revision_history.snapshots[i]));

// If code 101 still appears in a different telegram, it must retain its history.
const second={
 ...copy(caseData),
 messages:[{id:'m1',codes:['101']},{id:'m2',codes:['101','104']}],
 candidate_ideas:{'101':[idea]},
 hypothesis_revision_history:{
  version:1,cursor:1,snapshots:[{'101':mark},{}],actions:['marked 101','cleared 101']
 }
};
ctx.research=second;
ctx.deleteMessage();
assert.deepEqual(copy(second.messages.map(m=>m.id)),['m2']);
assert('101' in second.candidate_ideas,'still-observed code idea was removed');
ctx.navigateMarks(-1);
assert('101' in second.hypothesis_marks,'valid historical mark was removed');

// User cancellation must not change any data.
const canceled=copy(second);
confirmDeletion=false;
ctx.deleteMessage();
assert.deepEqual(copy(second),canceled,'cancelled deletion altered case');

console.log('Delete-message history pruning, undo/redo and retained-code preservation PASS');
