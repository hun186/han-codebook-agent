/* Offline state-machine smoke for case load/new navigation. No external calls. */
'use strict';
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const source=fs.readFileSync(path.resolve(__dirname,'../../vercel-demo/workbench.js'),'utf8');
const from=source.indexOf('async function loadCase(){');
const until=source.indexOf('function addNewMessage(){',from);
assert.ok(from>=0&&until>from,'case-navigation handlers must exist');
const controls=new Map();
const el=id=>{
 if(!controls.has(id))controls.set(id,{value:''});
 return controls.get(id);
};
const original={case_id:'ORIGINAL',messages:[{id:'M1',codes:['123']}]};
let dirty=true,allow=false,cancelledJobs=0,presentations=0,requests=0,confirms=0;
const ctx={
 research:original,caseGeneration:0,caseLoadRequestSerial:0,el,
 api:async()=>{requests++;return {case_id:'LOADED',messages:[]}},
 invalidateOldJobs:()=>{cancelledJobs++;ctx.caseGeneration++},
 presentCase:()=>{presentations++;ctx.invalidateOldJobs()},
 evidenceDraftChanged:()=>dirty,
 confirm:()=>{confirms++;return allow},
 prompt:()=> 'NEW_RESEARCH',
 notice:()=>{},
};
vm.createContext(ctx);
new vm.Script(source.slice(from,until),{filename:'case-transition.js'}).runInContext(ctx);
const run=script=>vm.runInContext(script,ctx);
el('caseList').value='other-case';
(async()=>{
 // Loading may fetch local data, but refusal must preserve the draft,
 // current case and active job identity.
 await run('loadCase()');
 assert.equal(ctx.research,original);
 assert.equal(cancelledJobs,0);
 assert.equal(presentations,0);
 assert.equal(confirms,1);
 allow=true;
 await run('loadCase()');
 assert.equal(ctx.research.case_id,'LOADED');
 assert.ok(cancelledJobs>=1);
 assert.equal(presentations,1);
 // If a newer case replaces the old one while a slow fetch is pending,
 // an obsolete response must not restore the previous selection.
 let resolveLate;
 ctx.api=()=>new Promise(resolve=>{requests++;resolveLate=resolve});
 dirty=false;allow=false;
 const stale=run('loadCase()');
 const newer={case_id:'NEWER',messages:[]};
 ctx.research=newer;ctx.caseGeneration++;
 resolveLate({case_id:'STALE',messages:[]});
 await stale;
 assert.equal(ctx.research,newer);
 // A draft typed while the request is in flight must also be protected.
 let resolveDraft;
 ctx.api=()=>new Promise(resolve=>{requests++;resolveDraft=resolve});
 const pending=run('loadCase()');
 dirty=true;allow=false;
 const jobsBefore=cancelledJobs;
 resolveDraft({case_id:'WOULD_DISCARD',messages:[]});
 await pending;
 assert.equal(ctx.research,newer);
 assert.equal(cancelledJobs,jobsBefore);
 assert.equal(presentations,1);
 // Creating a blank case is synchronous but must respect the same guard.
 const before=ctx.research;
 run('newResearchCase()');
 assert.equal(ctx.research,before);
 assert.equal(presentations,1);
 allow=true;
 run('newResearchCase()');
 assert.equal(ctx.research.case_id,'NEW_RESEARCH');
 assert.equal(ctx.research.messages.length,1);
 assert.equal(presentations,2);
 // Two overlapping loads must select the LAST requested case, even when the
 // earlier request returns first. A plain caseGeneration check is insufficient.
 dirty=false;allow=false;
 const beforeRace=ctx.research;
 const resolves=[];
 ctx.api=()=>new Promise(resolve=>resolves.push(resolve));
 const loadA=run('loadCase()');
 const loadB=run('loadCase()');
 assert.equal(resolves.length,2);
 resolves[0]({case_id:'OLDER_A',messages:[]});
 await loadA;
 assert.equal(ctx.research,beforeRace);
 assert.equal(presentations,2);
 resolves[1]({case_id:'LATEST_B',messages:[]});
 await loadB;
 assert.equal(ctx.research.case_id,'LATEST_B');
 assert.equal(presentations,3);
 console.log('Case transition guard PASS: load/new cancel, stale response, mid-flight draft, concurrent latest-request-wins');
})().catch(error=>{console.error(error);process.exitCode=1});
