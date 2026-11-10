/* Pure offline browser-VM regression. No network, no archived evidence leakage. */
'use strict';
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const target=process.argv[2]||path.resolve(__dirname,'../../src/han_codebook/static/index.html');
const source=fs.readFileSync(target,'utf8');
const script=target.endsWith('.html')?source.split('<script>')[1].split('</script>')[0]:source;
const from=script.indexOf('function evidenceDraftChanged(){');
const until=script.indexOf('// Alignment confirmation',from);
assert(from>=0&&until>from,'observation draft functions missing');
for(const id of ['obsSource','obsWhen','obsActivity','obsDest','obsStatus',
                 'obsConfidence','obsNote','cancelObservationEdit','obsCards']){
 assert(source.includes("el('"+id+"')")||source.includes('id="'+id+'"'),'missing '+id);
}
const elements={};
const buttons={};
function el(id){
 if(!elements[id]){
  elements[id]={value:'',innerHTML:'',textContent:'',hidden:true,checked:false,
   querySelectorAll(selector){
    const attr=selector==='[data-editobs]'?'editobs':'removeobs';
    const matches=Array.from(this.innerHTML.matchAll(new RegExp('data-'+attr+'="([0-9]+)"','g')));
    const controls=matches.map(match=>({dataset:{[attr]:match[1]},onclick:null}));
    buttons[selector]=controls;
    return controls;
   }};
 }
 return elements[id];
}
const original={
 id:'m1',codes:['123'],notes:'原始密電備註',
 observations:[{source:'居民觀測',observed_at:'2018-09-02',
  activity:'公開資訊摘要',destination:'資料未能定位',status:'未確認',
  confidence:0.51,note:'雨水相關但未確認',archive_only:{dont_touch:true}}]
};
const research={case_id:'synthetic',messages:[original,{id:'m2',codes:['234'],observations:[]}],
 known_pairs:[],candidate_ideas:{},hypothesis_marks:{}};
let ask=false;
const errors=[];
const ctx={
 el,overviewState:{loadedMessageId:null},research,
 msg:()=>research.messages.find(m=>m.id===el('messagePick').value),
 esc:x=>String(x??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;'),
 confirm:()=>ask,
 notice:(message,bad=false)=>{if(bad)errors.push(message)},
 renderMessageOverview:()=>{},
 renderIdeas:()=>{},initializeMarks:()=>{},persistMarkHistory:()=>{},
 ideaSnapshots:[],markSnapshots:[],markCursor:0,
};
vm.createContext(ctx);
vm.runInContext(script.slice(from,until),ctx,{filename:'observation-form.js'});
const run=expression=>vm.runInContext(expression,ctx);
el('messagePick').value='m1';
run('loadEvidence()');
assert(el('obsCards').innerHTML.includes('雨水相關但未確認'),'existing note should be visible');
assert.equal(run('evidenceDraftChanged()'),false);
buttons['[data-editobs]'][0].onclick();
assert.equal(el('obsSource').value,'居民觀測');
assert.equal(el('obsNote').value,'雨水相關但未確認');
assert.equal(el('obsConfidence').value,'0.51');
assert.equal(el('cancelObservationEdit').hidden,false);
assert.equal(run('evidenceDraftChanged()'),true,'editing a row is an uncommitted draft');
el('obsNote').value='修正後的補充內容';
// Navigation and Apply must not silently discard the unsaved row form.
assert.equal(run("selectEvidenceMessage('m2')"),false);
assert.equal(el('messagePick').value,'m1');
run('applyEvidence()');
assert(errors.some(s=>s.includes('未加入／未儲存')),'Apply must reject open edit draft');
assert.equal(original.observations[0].note,'雨水相關但未確認');
run('addObservation()');
let staged=JSON.parse(el('observations').value);
assert.equal(staged.length,1,'edit must replace, never append');
assert.equal(staged[0].note,'修正後的補充內容');
assert.equal(staged[0].archive_only.dont_touch,true,'archival fields stay intact');
assert.equal(original.observations[0].note,'雨水相關但未確認','in-memory case must not update early');
assert.equal(el('cancelObservationEdit').hidden,true);
run('applyEvidence()');
assert.equal(original.observations[0].note,'修正後的補充內容');
assert.equal(run('evidenceDraftChanged()'),false);
// Editing JSON manually while an existing row is being edited must not be overwritten.
buttons['[data-editobs]'][0].onclick();
const advanced=JSON.parse(el('observations').value);
advanced[0].note='由 JSON 編輯';
el('observations').value=JSON.stringify(advanced,null,2);
el('obsNote').value='錯誤覆寫';
run('addObservation()');
assert(errors.some(s=>s.includes('進階 JSON')),'stale observation edit must refuse overwrite');
assert.equal(JSON.parse(el('observations').value)[0].note,'由 JSON 編輯');
run('resetObservationEditor()');
assert.equal(JSON.parse(el('observations').value)[0].note,'由 JSON 編輯');
// Cancel must never overwrite staged JSON.
buttons['[data-editobs]'][0].onclick();
el('obsNote').value='不該保留';
run('resetObservationEditor()');
assert.equal(JSON.parse(el('observations').value)[0].note,'由 JSON 編輯');
// Adding a new observation uses the same form but creates a distinct record.
el('obsSource').value='後續目擊';
el('obsNote').value='新增說明';
run('addObservation()');
staged=JSON.parse(el('observations').value);
assert.equal(staged.length,2);
assert.equal(staged[1].note,'新增說明');
// Unsaved new observation inputs must protect case transition.
el('obsNote').value='未加入的草稿';
assert.equal(run("selectEvidenceMessage('m2')"),false);
ask=true;
assert.equal(run("selectEvidenceMessage('m2')"),true);
assert.equal(el('obsNote').value,'');
assert.equal(el('messagePick').value,'m2');
console.log('observation add/edit/note/cancel/stale JSON/nav guard PASS');
