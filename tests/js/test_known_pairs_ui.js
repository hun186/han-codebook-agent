'use strict';
const assert=require('assert');
const fs=require('fs');
const vm=require('vm');
const source=fs.readFileSync(process.argv[2],'utf8');
const script=source.split('<script>')[1].split('</script>')[0];
const begin=script.indexOf('function renderKnownPairs(){');
const end=script.indexOf('function saveProfile(){',begin);
assert(begin>0&&end>begin,'per-row research functions missing');
for(const id of ['knownPairs','knownAdd','knownRowEditor','knownRowMessage',
 'knownRowPlaintext','knownSegmentsGrid','knownRowVerified','knownRowSave',
 'knownRowCancel','knownEdit']){
 assert(source.includes('id="'+id+'"'),'missing UI control '+id);
}
assert(source.includes('el(\'knownAdd\').onclick'));
assert(source.includes('el(\'knownRowSave\').onclick'));
let records=[],ask=true,fields=[],dom={};
function el(id){
 if(!dom[id]){
  dom[id]={value:'',innerHTML:'',textContent:'',checked:false,hidden:true,
    querySelectorAll:()=>[]};
 }
 return dom[id];
}
el('knownSegmentsGrid').querySelectorAll=()=>fields;
const textCase={
 case_id:'synthetic',profiles:{neutral:{lexicon:{}}},messages:[
  {id:'m1',codes:['001','002']},{id:'m2',codes:['001','003']}
 ],known_pairs:[],hypothesis_marks:{},bold_hypotheses:{}
};
const context={
 el,esc:s=>String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;')
  .replace(/"/g,'&quot;').replace(/>/g,'&gt;'),
 notice:(s,bad=false)=>records.push({s,bad}),confirm:()=>ask,
 copyMarks:x=>JSON.parse(JSON.stringify(x||{})),
 persistMarkHistory:()=>{},initializeMarks:()=>{},renderBoldHypotheses:()=>{},
};
vm.createContext(context);
context.initialCase=textCase;
vm.runInContext('let research=globalThis.initialCase,markSnapshots=[],'
 +'alignmentReport=null,alignmentChoice=null,alignmentOrigin=null,'
 +'knownEditorIndex=null,knownEditorOrigin=null;',context);
vm.runInContext(script.slice(begin,end),context);
const canonical=()=>JSON.stringify(textCase.known_pairs,null,2);
const errors=()=>records.filter(x=>x.bad).map(x=>x.s);
const setFields=words=>{fields=words.map(value=>({value}));};
context.renderKnownPairs();
assert(el('knownPairs').innerHTML.includes('目前沒有明密文對'));
context.openKnownRowEditor(null);
assert.strictEqual(el('knownRowEditor').hidden,false);
el('knownRowMessage').value='m1';
el('knownRowPlaintext').value='補給車隊';
setFields(['','']);
context.saveKnownRow();
assert.strictEqual(textCase.known_pairs.length,1);
assert.strictEqual(textCase.known_pairs[0].plaintext,'補給車隊');
assert(!Object.hasOwn(textCase.known_pairs[0],'segments'),'unaligned must not become an anchor');
assert(el('knownPairs').innerHTML.includes('尚未切段'));
assert(el('knownRowEditor').hidden,'applied row editor must close');
// Incomplete and unconfirmed segment input are rejected; no partial mutations.
context.openKnownRowEditor(0);
setFields(['補給','']);
el('knownRowPlaintext').value='補給車隊';
context.saveKnownRow();
assert(errors().some(x=>x.includes('全部填寫')));
assert(!Object.hasOwn(textCase.known_pairs[0],'segments'));
setFields(['補給','車隊']);
context.saveKnownRow();
assert(errors().some(x=>x.includes('勾選')));
assert(!Object.hasOwn(textCase.known_pairs[0],'segments'));
el('knownRowVerified').checked=true;
context.saveKnownRow();
assert.deepStrictEqual(Array.from(textCase.known_pairs[0].segments),['補給','車隊']);
assert(el('knownEdit').value.includes('"segments"'));
assert(el('knownPairs').innerHTML.includes('逐碼對齊'));
// Adding a second pair with the same trusted code but an inconsistent word fails.
context.openKnownRowEditor(null);
el('knownRowMessage').value='m2';
context.renderKnownWordFields();
el('knownRowPlaintext').value='錯誤出發';
setFields(['錯誤','出發']);
el('knownRowVerified').checked=true;
context.saveKnownRow();
assert.strictEqual(textCase.known_pairs.length,1);
assert(errors().some(x=>x.includes('互相衝突')));
// One independent consistent known pair must succeed.
el('knownRowPlaintext').value='補給出發';
setFields(['補給','出發']);
el('knownRowVerified').checked=true;
context.saveKnownRow();
assert.strictEqual(textCase.known_pairs.length,2);
assert.strictEqual(textCase.known_pairs[1].segments[0],'補給');
// Existing independently verified codes MUST NOT be silently replaced even
// after clicking multiple confirmations. Amendments require explicit retraction
// of the old trusted evidence, THEN a separate independent new alignment.
textCase.known_pairs[1].alignment_provenance={method:'explicit_researcher_confirmed_review_candidate'};
context.renderKnownPairs();
context.openKnownRowEditor(1);
el('knownRowPlaintext').value='補給糧秣';
setFields(['補給','糧秣']);
el('knownRowVerified').checked=true;
context.saveKnownRow();
assert(errors().some(x=>x.includes('不得直接以不同詞句覆寫')));
assert.strictEqual(textCase.known_pairs[1].segments[1],'出發');
assert(Object.hasOwn(textCase.known_pairs[1],'alignment_provenance'),
       'failed replacement must retain trusted provenance');
// Researcher can explicitly retract the old row's segment verification.
context.openKnownRowEditor(1);
el('knownRowPlaintext').value='補給糧秣';
setFields(['','']);
context.saveKnownRow();
assert(!Object.hasOwn(textCase.known_pairs[1],'segments'));
assert(!Object.hasOwn(textCase.known_pairs[1],'alignment_provenance'),
       'retracted alignment cannot retain outdated provenance');
// New independent review, now free of the old code's anchor, is allowed.
context.openKnownRowEditor(1);
el('knownRowPlaintext').value='補給糧秣';
setFields(['補給','糧秣']);
el('knownRowVerified').checked=true;
context.saveKnownRow();
assert.strictEqual(textCase.known_pairs[1].segments[1],'糧秣');
// A second trusted code may still not overwrite an existing trusted term.
context.openKnownRowEditor(1);
el('knownRowPlaintext').value='錯誤糧秣';
setFields(['錯誤','糧秣']);
el('knownRowVerified').checked=true;
context.saveKnownRow();
assert.strictEqual(textCase.known_pairs[1].segments[0],'補給');
// Avoid overwriting parallel changes while the row editor is open.
context.openKnownRowEditor(0);
textCase.messages[0].notes='other researcher changed the case';
setFields(['補給','車隊']);
el('knownRowVerified').checked=true;
context.saveKnownRow();
assert(errors().some(x=>x.includes('已變更')));
context.closeKnownRowEditor();
context.renderKnownPairs();
// Delete is explicit, only edits in-memory case, and aborts on user cancel.
ask=false;context.deleteKnownRow(1);
assert.strictEqual(textCase.known_pairs.length,2);
ask=true;context.deleteKnownRow(1);
assert.strictEqual(textCase.known_pairs.length,1);
assert(el('knownEdit').value===canonical());
// Existing advanced JSON editing still uses the shared validator.
el('knownEdit').value=JSON.stringify([{message_id:'m1',
 plaintext:'補給車隊',segments:['補給','錯誤']}]);
context.applyKnown();
assert(errors().some(x=>x.includes('不得直接以不同詞句覆寫')));
assert.strictEqual(textCase.known_pairs[0].segments[1],'車隊',
 'conflicting direct JSON may not silently replace old state if rejected');
// Verify stale JSON cannot be silently replaced by the row manager.
el('knownEdit').value='[{"message_id":"m1"}]';
context.openKnownRowEditor(0);
assert(errors().some(x=>x.includes('進階 JSON 尚未套用')));
assert(el('knownEdit').value!==canonical());
console.log('known-pairs researcher row-editor regression passed');
