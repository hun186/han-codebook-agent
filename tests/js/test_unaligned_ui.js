'use strict';
const assert=require('assert');
const fs=require('fs');
const vm=require('vm');
const source=fs.readFileSync(process.argv[2],'utf8');
const script=source.split('<script>')[1].split('</script>')[0];
const begin=script.indexOf('function captureAlignmentOrigin(){');
const end=script.indexOf('function applyKnown(){try{',begin);
assert(begin>=0&&end>begin,'manual-review functions missing');
assert(source.includes('id="previewAlignment"'));
assert(source.includes('id="confirmAlignment"'));
let requests=[],notices=[],allowed=true,accepted=false,dom={};
// Match the PRODUCTION fingerprint, which intentionally omits history for
// ordinary inference jobs. Alignment acceptance must add its own strict check.
const normalFingerprint=caseObj=>{const copy={...caseObj};delete copy.hypothesis_revision_history;return JSON.stringify(copy)};
const el=id=>dom[id] ||= {value:'',innerHTML:'',textContent:'',disabled:false,querySelectorAll:()=>[]};
const caseData={
 case_id:'synthetic',messages:[{id:'m1',codes:['001','002']}],
 known_pairs:[{message_id:'m1',plaintext:'補給車隊'}],
 profiles:{neutral:{lexicon:{補給:1,車隊:1}}}
};
const row={known_pair_index:0,message_id:'m1',code_groups:['001','002'],
 candidates:[{segments:['補給','車隊'],status:'candidate_unverified',heuristic_score:8}]};
const review={review_required:true,top_n:8,beam_width:96,reviews:[row]};
const context={el,esc:s=>String(s).replace(/</g,'&lt;'),notice:(s,error)=>notices.push([s,error]),
 confirm:()=>allowed,
 api:async(path,data)=>{requests.push({path,data});return path.endsWith('preview')?review:{
   case:{...data.case,known_pairs:[{...data.case.known_pairs[0],segments:['補給','車隊']}]},
   saved:false,status:'researcher_confirmed_not_saved'
 }},
 matchesCaseReference:origin=>origin.caseRef===context.research,
 caseFingerprint:()=>normalFingerprint(context.research),
 captureOrigin:()=>({caseRef:context.research,fingerprint:normalFingerprint(context.research)}),
 matchesOrigin:origin=>origin.caseRef===context.research&&origin.fingerprint===normalFingerprint(context.research),
 presentCase:()=>{accepted=true},
};
vm.createContext(context);
vm.runInContext('let research=null,alignmentReport=null,alignmentOrigin=null,alignmentChoice=null;',context);
context.research=caseData;
vm.runInContext('research=globalThis.research;',context);
vm.runInContext(script.slice(begin,end),context);
let click;
el('alignmentCandidates').querySelectorAll=()=>[{dataset:{alignmentPair:'0',alignmentRank:'1'},set onclick(fn){click=fn}}];
(async()=>{
 await context.previewAlignmentCandidates();
 assert.strictEqual(requests[0].path,'/api/unaligned/preview');
 assert.strictEqual(requests[0].data.case,caseData);
 assert(el('alignmentCandidates').innerHTML.includes('未驗證'));
 assert(typeof click==='function','candidate selector not installed');
 click();
 assert.strictEqual(el('alignmentTyped').value,'','must not auto-type trusted segments');
 el('alignmentTyped').value='["補給","車隊"]';
 await context.confirmAlignmentCandidate();
 assert(accepted,'accepted case was not staged');
 assert.strictEqual(requests[1].path,'/api/unaligned/accept');
 assert.strictEqual(requests[1].data.confirmed,true);
 assert.strictEqual(requests[1].data.candidate_rank,1);
 assert.strictEqual(requests[1].data.known_pair_index,0);
 assert.deepStrictEqual(Array.from(requests[1].data.confirmed_segments),['補給','車隊']);
 assert(notices.some(x=>x[0].includes('尚未存檔')),'saved status must be explicit');
 // An edited case between preview and confirmation must not use stale report.
 accepted=false;requests=[];
 context.research=caseData;
 vm.runInContext('research=globalThis.research;',context);
 await context.previewAlignmentCandidates();
 click();
 caseData.messages[0].notes='changed evidence';
 el('alignmentTyped').value='["補給","車隊"]';
 await context.confirmAlignmentCandidate();
 assert(!accepted,'stale candidate applied after case mutation');
 assert(requests.every(x=>x.path!=='/api/unaligned/accept'));
 // Official Codex P2: changing ONLY Undo history while HTTP accept is in
 // flight must not silently replace newer snapshots with an old response.
 accepted=false;requests=[];
 const historyOnly={...caseData,messages:[{...caseData.messages[0]}],hypothesis_marks:{}};
 context.research=historyOnly;
 vm.runInContext('research=globalThis.research;',context);
 await context.previewAlignmentCandidates();click();
 el('alignmentTyped').value='["補給","車隊"]';
 const oldApi=context.api;
 let resolveDelayed;
 context.api=(path,data)=>{
  if(path!=='/api/unaligned/accept')return oldApi(path,data);
  requests.push({path,data});
  return new Promise(resolve=>{resolveDelayed=()=>resolve({
   case:{...data.case,known_pairs:[{...data.case.known_pairs[0],segments:['補給','車隊']}]},
   saved:false,status:'researcher_confirmed_not_saved'
  })});
 };
 const pendingAccept=context.confirmAlignmentCandidate();
 assert.strictEqual(typeof resolveDelayed,'function','accept request not started');
 historyOnly.hypothesis_revision_history={version:1,cursor:0,snapshots:[{other:{preferred:'甲'}}],actions:['edited']};
 assert(context.matchesOrigin(vm.runInContext('alignmentOrigin',context)),
        'ordinary job fingerprint should ignore undo-history only changes');
 resolveDelayed();await pendingAccept;
 assert(!accepted,'stale accept response discarded newer history snapshots');
 assert.strictEqual(historyOnly.hypothesis_revision_history.actions[0],'edited');
 context.api=oldApi;
 // Rejected confirmation must not send any POST accept.
 requests=[];allowed=false;
 const newCase={...caseData,messages:[{...caseData.messages[0]}]};
 context.research=newCase;
 vm.runInContext('research=globalThis.research;',context);
 await context.previewAlignmentCandidates();click();
 el('alignmentTyped').value='["補給","車隊"]';
 await context.confirmAlignmentCandidate();
 assert(requests.every(x=>x.path!=='/api/unaligned/accept'));
 console.log('Browser manual alignment review regression passed');
})().catch(e=>{console.error(e);process.exitCode=1});
