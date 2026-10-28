'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync(process.argv[2],'utf8');
const script=html.split('<script>')[1].split('</script>')[0];
new vm.Script(script);
const grab=(from,to)=>{
 const a=script.indexOf(from),b=script.indexOf(to,a+from.length);
 assert(a>=0&&b>a,'missing function boundary '+from);
 return script.slice(a,b);
};
assert(html.includes('id="guide"'),'guide page missing');
assert(html.includes('aria-label="研究工作台導航"'),'sidebar missing');
assert(html.includes('data-go-page="evidence"'),'guide-to-workflow links missing');
assert(html.includes('@media(max-width:900px)'),'mobile navigation missing');

const dom={};const notices=[];
function el(id){
 if(!dom[id]){
  dom[id]={
   value:'',textContent:'',innerHTML:'',checked:false,disabled:false,
   replaceChildren(){this.innerHTML=''},
   querySelectorAll(selector){
    if(selector==='[data-adopt-vocab]'){
      const ids=[...this.innerHTML.matchAll(/data-adopt-vocab="(\d+)"/g)].map(m=>m[1]);
      const controls=ids.map(index=>({dataset:{adoptVocab:index},onclick:null}));
      this.buttons=controls;
      return controls;
    }
    return [];
   }
  };
 }
 return dom[id];
}
const timers=new Map();let nextTimer=1,api;
const ctx={
 el,notice:(message,err=false)=>notices.push({message,err}),confirm:()=>true,
 setInterval(fn){const token=nextTimer++;timers.set(token,fn);return token},
 clearInterval(token){timers.delete(token)},
 api:(...args)=>api(...args),
 renderVocab(){},renderTrace(){},renderPriorComparison(){},
 chartBar:()=>'',esc:x=>String(x),openMark(){},
 markedCodes:()=>['101'],verifiedCodes:()=>new Set(),
 };
vm.createContext(ctx);
vm.runInContext(grab('let research=null','function notice('),ctx);
vm.runInContext(grab('function copyIdeas(','async function previewEventLinks()'),ctx);
vm.runInContext(grab('let vocabCandidateRecord=','function chartBar('),ctx);
vm.runInContext(grab('async function previewEventLinks()','let vocabCandidateRecord='),ctx);
vm.runInContext(grab('function renderJob(j)','function renderTrace('),ctx);
vm.runInContext(grab('async function start(){','async function save()'),ctx);
vm.runInContext('function profile(){return research.profiles.general}',ctx);
el('markCode').value='101';el('metadata').value='true';el('rounds').value='1';

const caseA={case_id:'A',messages:[{id:'A1',codes:['101']}],
 profiles:{general:{lexicon:{},keywords:[],sentences:[]}},candidate_ideas:{}};
const caseB={case_id:'B',messages:[{id:'B1',codes:['101']}],
 profiles:{general:{lexicon:{},keywords:[],sentences:[]}},candidate_ideas:{}};
ctx._A=caseA;ctx._B=caseB;
const run=expression=>vm.runInContext(expression,ctx);
const clone=x=>JSON.parse(JSON.stringify(x));

(async()=>{
 // Delayed API response from case A after case B becomes active.
 let resolveSubmit;
 api=path=>path==='/api/suggest-vocabulary'?new Promise(resolve=>resolveSubmit=resolve):
   Promise.reject(new Error('unexpected call '+path));
 run('research=_A;invalidateOldJobs()');
 const pending=run('askVocabulary()');
 await Promise.resolve();
 assert(resolveSubmit,'vocabulary HTTP request never issued');
 run('research=_B;invalidateOldJobs()');
 resolveSubmit({job_id:'job-for-A'});
 await pending;
 assert.equal(run('vocabCandidateRecord.length'),0,'late A response was installed into B');
 assert.equal(timers.size,0,'late A response started a poller');

 // Same protection for independent async cross-telegram event associations.
 let resolveEvents;
 api=path=>path==='/api/event-links'?new Promise(resolve=>resolveEvents=resolve):
   Promise.reject(new Error('unexpected event call '+path));
 run('research=_A;invalidateOldJobs()');
 const pendingEvents=run('previewEventLinks()');
 await Promise.resolve();
 run('research=_B;invalidateOldJobs()');
 resolveEvents({events:[{source:'source A',observed_at:'1942-05-03',activity:'only A',status:'unconfirmed',
   confidence:0.5,event_id:'A-event',candidates:[]}]});
 await pendingEvents;
 assert(!el('eventLinks').innerHTML.includes('source A'),
   'late event association from A appeared in B');

 // Case revision changes while a vocabulary job is running also invalidate it.
 let resolveJob;
 api=path=>{
   if(path==='/api/suggest-vocabulary')return Promise.resolve({job_id:'delayed-vocab'});
   if(path==='/api/jobs/delayed-vocab')return new Promise(resolve=>resolveJob=resolve);
   return Promise.reject(new Error('unexpected call '+path));
 };
 run('research=_A;invalidateOldJobs()');
 await run('askVocabulary()');
 assert.equal(el('askVocabulary').disabled,true);
 run('research.messages[0].sender="new evidence during processing"');
 resolveJob({status:'completed',logs:[],result:{terms:[{term:'舊詞'}]}});
 for(let n=0;n<5;n++)await Promise.resolve();
 assert.equal(el('askVocabulary').disabled,false,'stale job left vocabulary button disabled');
 assert.equal(run('vocabCandidateRecord.length'),0,'same-case edited evidence accepted old results');

 // Completed case A vocabulary: multiple manual term adoptions permitted.
 api=async path=>{
  if(path==='/api/suggest-vocabulary')return {job_id:'A-vocab'};
  if(path==='/api/jobs/A-vocab')return {status:'completed',logs:[],result:{
    terms:[{term:'車隊',reason:'reason 1'},{term:'補給',reason:'reason 2'}]}};
  throw Error('unexpected API '+path);
 };
 run('research=_A;invalidateOldJobs()');
 await run('askVocabulary()');
 for(let n=0;n<5;n++)await Promise.resolve();
 assert.equal(run('vocabCandidateRecord.length'),2,'same-case results not shown');
 const first=el('vocabSuggestions').buttons[0];
 const second=el('vocabSuggestions').buttons[1];
 first.onclick();second.onclick();
 assert.equal(run('research.profiles.general.lexicon["車隊"]'),2);
 assert.equal(run('research.profiles.general.lexicon["補給"]'),2);

 // After a case switch, even an old DOM event is not allowed to mutate B.
 run('research=_B;invalidateOldJobs()');
 first.onclick();
 assert.equal(run('research.profiles.general.lexicon["車隊"]'),undefined,
   'stale DOM button wrote a foreign codebook vocabulary');

 // Analysis completion from A must never refresh B's LLM proposal cache.
 run('research=_A;invalidateOldJobs()');
 const origin=run('captureOrigin()');ctx._origin=origin;
 run('research=_B;invalidateOldJobs()');
 run("renderJob({type:'analysis',id:'A-job',status:'completed',logs:[],events:"+
  "[{stage:'llm_proposals_unverified',payload:{accepted:[{code:'101',candidates:['車隊']}]}}],"+
  "result:{}},_origin)");
 assert.equal(run('lastLLMEntries.length'),0,'A mapping proposals leaked into B');

 // Check a pending analysis HTTP response returned after the case changed.
 let resolveAnalysis;
 api=path=>path==='/api/start'?new Promise(resolve=>resolveAnalysis=resolve):
   Promise.reject(new Error('unexpected analysis API '+path));
 run('research=_A;invalidateOldJobs()');
 const pendingAnalysis=run('start()');
 await Promise.resolve();
 run('research=_B;invalidateOldJobs()');
 resolveAnalysis({job_id:'old-A'});
 await pendingAnalysis;
 assert.equal(run('lastJob'),null,'stale analysis job was adopted by B');

 // Batch LLM import must preserve researcher decisions, provenance and notes.
 run('research=_A;invalidateOldJobs()');
 run('research.candidate_ideas={"101":['+
  '{"term":"拒絕","source":"researcher","status":"rejected","note":"human rejection"},'+
  '{"term":"優選","source":"researcher","status":"shortlisted","note":"human shortlist"}]}');
 run('ideaSnapshots=[JSON.parse(JSON.stringify(research.candidate_ideas))];ideaCursor=0');
 run('lastLLMOrigin=captureOrigin();lastLLMEntries=['+
  '{"code":"101","candidates":["拒絕","優選","新建"],"reason":"LLM generated"}]');
 run('importPreviousLLMIdeas()');
 const ideas=clone(run('research.candidate_ideas["101"]'));
 assert.equal(ideas.length,3);
 assert.deepEqual(ideas.find(x=>x.term==='拒絕'),
  {term:'拒絕',source:'researcher',status:'rejected',note:'human rejection'});
 assert.deepEqual(ideas.find(x=>x.term==='優選'),
  {term:'優選',source:'researcher',status:'shortlisted',note:'human shortlist'});
 assert.equal(ideas.find(x=>x.term==='新建').source,'llm');
 assert.equal(ideas.find(x=>x.term==='新建').status,'suggested');
 run('navigateIdeas(-1)');
 assert.equal(clone(run('research.candidate_ideas["101"]')).length,2,'undo lost human state');
 run('navigateIdeas(1)');
 assert.equal(clone(run('research.candidate_ideas["101"]')).length,3,'redo lost imported entry');

 // A single case can also have several pending GETs for the SAME job.
 // A stale GET from the finished first job must not replace the next job.
 let resolveOldPoll,firstCalls=0;
 api=async path=>{
  if(path==='/api/suggest-vocabulary')return {job_id:'same-case-first'};
  if(path==='/api/jobs/same-case-first'){
   firstCalls++;
   if(firstCalls===1)return new Promise(resolve=>{resolveOldPoll=resolve});
   return {status:'completed',logs:[],result:{terms:[{term:'第一批'}]}};
  }
  throw Error('unexpected same-case job path: '+path);
 };
 run('research=_A;invalidateOldJobs()');
 await run('askVocabulary()');
 assert.equal(firstCalls,1);
 const activeInterval=[...timers.values()].at(-1);
 assert(activeInterval,'missing poll interval for same-case request');
 await activeInterval();
 for(let n=0;n<6;n++)await Promise.resolve();
 assert.equal(run('vocabCandidateRecord[0].term'),'第一批','second poll did not finish first job');
 assert.equal(el('askVocabulary').disabled,false,'first job did not release button');

 api=async path=>{
  if(path==='/api/suggest-vocabulary')return {job_id:'same-case-second'};
  if(path==='/api/jobs/same-case-second')
    return {status:'completed',logs:[],result:{terms:[{term:'第二批'}]}};
  throw Error('unexpected second job path: '+path);
 };
 await run('askVocabulary()');
 for(let n=0;n<6;n++)await Promise.resolve();
 assert.equal(run('vocabCandidateRecord[0].term'),'第二批','second job failed');
 resolveOldPoll({status:'completed',logs:[],result:{terms:[{term:'遲到的第一批'}]}});
 for(let n=0;n<6;n++)await Promise.resolve();
 assert.equal(run('vocabCandidateRecord[0].term'),'第二批',
   'late GET from first job overwrote new job in identical case');
 assert.equal(el('askVocabulary').disabled,false,'late GET altered second job button state');

 console.log('UI cross-case isolation, safe idea import and workflow guide PASS');
})().catch(e=>{console.error(e);process.exitCode=1});
