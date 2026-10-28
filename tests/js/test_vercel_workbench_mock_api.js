/* Browser-side API contract smoke test: no server, storage, or network model. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { TextEncoder } = require('node:util');

(async () => {
  const base = path.resolve(__dirname, '../../vercel-demo');
  const fixture = JSON.parse(fs.readFileSync(path.join(base,'data/demo.json'),'utf8'));
  const requests = [];
  const callbacks = {};
  const origin = 'https://example.test';
  const sandbox = {
    URL, Blob, Response, TextEncoder, Uint8Array, setTimeout, console,
    location: { origin, href:origin+'/' },
    fetch: async url => {
      requests.push(String(url));
      assert.equal(String(url),'/data/demo.json','must never call model/public API');
      return new Response(JSON.stringify(fixture), {status:200});
    },
    document: {addEventListener: (event, callback) => {callbacks[event] = callback}},
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  const code = fs.readFileSync(path.join(base,'mock_api.js'),'utf8');
  new vm.Script(code, {filename:'mock_api.js'}).runInContext(sandbox);
  const get = async path => {
    const r=await sandbox.fetch(path);
    if(r.status!==200)throw Error('HTTP '+r.status+': '+await r.text());
    return r.json();
  };
  const post = async (path, data) => {
    const r=await sandbox.fetch(path,{method:'POST',body:JSON.stringify(data)});
    if(r.status!==200)throw Error('HTTP '+r.status+': '+await r.text());
    return r.json();
  };
  const ids=await get('/api/cases');
  assert.deepEqual(Array.from(ids,x=>x.id),['demo_10','demo_25','demo_50','demo_100']);
  const cfg=await get('/api/settings');
  assert.match(cfg.model,/MOCK/);
  assert.equal(cfg.allow_private_network,false);
  assert.equal((await post('/api/settings/test',{confirmed:true})).connected,false);
  const settingsPost=await sandbox.fetch('/api/settings/llm',{
    method:'POST',body:JSON.stringify({base_url:'https://example.org'})
  });
  assert.equal(settingsPost.status,400);
  assert.match((await settingsPost.json()).error,/不允許更改模型端點/);
  const caseData=await get('/api/case?id=demo_10');
  assert.equal(caseData.messages.length,10);
  assert.equal(caseData.known_pairs.length,0);
  assert.ok(caseData.profiles.logistics.lexicon);
  assert.equal(caseData.messages[0].codes[0],fixture.records[0].messages[0].codes[0]);
  for(const rounds of [0,2,20]){
    const start=await post('/api/start',{case:caseData,rounds,use_metadata:true});
    const run=await get('/api/jobs/'+start.job_id);
    assert.equal(run.status,'completed');
    assert.equal(run.type,'analysis');
    assert.equal(run.result.agent_rounds_completed,rounds);
    assert.equal(run.result.decoded_messages.length,10);
    assert.equal(run.result.decoded_messages[0].codes.length,caseData.messages[0].codes.length);
    assert.ok(Object.values(run.result.proposals).every(p=>p.status==='hypothesis_unverified'));
    assert.equal(run.events.filter(x=>x.stage==='llm_proposals_unverified').length,rounds);
    assert.equal(run.events.filter(x=>x.stage==='rescore').length,rounds);
    if(rounds===0) assert.equal(run.events.length,1);
    if(rounds===2){
      const docx=sandbox.HanMockDemo.makeDocxForTest(run.result);
      const bytes=Buffer.from(docx);
      assert.equal(bytes.readUInt32LE(0),0x04034b50);
      assert.ok(bytes.includes(Buffer.from('word/document.xml')));
      assert.ok(bytes.includes(Buffer.from('[Content_Types].xml')));
      assert.equal(bytes.readUInt32LE(bytes.length-22),0x06054b50);
    }
  }
  const noMetadataId=(await post('/api/start',{
    case:caseData,rounds:0,use_metadata:false
  })).job_id;
  const noMetadata=(await get('/api/jobs/'+noMetadataId)).result;
  assert.equal(noMetadata.metadata_used,false);
  assert.equal(noMetadata.decoded_messages[0].domain_inferred,null);
  const preferredCase=JSON.parse(JSON.stringify(caseData));
  const firstCode=preferredCase.messages[0].codes[0];
  preferredCase.hypothesis_marks={
    [firstCode]:{preferred:'研究員新詞',pinned:false,excluded:[],note:'mock preference'}
  };
  const preferId=(await post('/api/start',{case:preferredCase,rounds:0})).job_id;
  const preferResult=(await get('/api/jobs/'+preferId)).result;
  assert.equal(preferResult.proposals[firstCode].term,'研究員新詞');
  assert.equal(preferResult.proposals[firstCode].status,'hypothesis_unverified');
  const proposal=await post('/api/suggest-vocabulary',{case:caseData,confirmed:true});
  const vocabJob=await get('/api/jobs/'+proposal.job_id);
  assert.equal(vocabJob.type,'vocabulary');
  assert.ok(vocabJob.result.terms.length>0);
  assert.ok(vocabJob.result.terms.every(t=>t.reason.includes('MOCK')));
  const events=await post('/api/event-links',{case:caseData});
  assert.ok(events.events.length>0);
  assert.ok(events.events[0].candidates.some(x=>x.message_id===null));
  const mockBench=await get('/api/benchmark');
  assert.equal(mockBench.runs.length,4);
  const benchId=(await post('/api/start-benchmark',{})).job_id;
  assert.equal((await get('/api/jobs/'+benchId)).result.runs.length,4);

  // Capture editable UI workflow on static site with no persisted storage.
  const modified=JSON.parse(JSON.stringify(caseData));
  modified.messages[0].codes=['0007','123'];
  modified.known_pairs=[{message_id:modified.messages[0].id,segments:['可信詞','逐碼明文']}];
  modified.candidate_ideas={'123':[{term:'人工猜測',source:'researcher',status:'suggested',note:''}]};
  const save=await post('/api/save',{case:modified,name:'my_mock_case'});
  assert.equal(save.saved_as,'my_mock_case');
  assert.equal((await get('/api/cases')).length,5);
  const reloaded=await get('/api/case?id=my_mock_case');
  assert.deepEqual(reloaded.messages[0].codes,['0007','123']);
  const runId=(await post('/api/start',{case:reloaded,rounds:1})).job_id;
  const run=await get('/api/jobs/'+runId);
  assert.equal(run.result.proposals['0007'].status,'verified_alignment');
  assert.equal(run.result.proposals['0007'].term,'可信詞');
  assert.equal(run.result.proposals['123'].term,'逐碼明文');
  const leak=await sandbox.fetch('/api/start',{
    method:'POST',body:JSON.stringify({case:{...caseData,ground_truth:{'0007':'答案'}},rounds:2})
  });
  assert.equal(leak.status,400);
  await assert.rejects(()=>sandbox.fetch('https://api.openai.com/v1/chat/completions'));
  assert.deepEqual(requests,['/data/demo.json']);
  assert.equal(typeof callbacks.click,'function');
  new vm.Script(fs.readFileSync(path.join(base,'workbench.js'),'utf8'),{filename:'workbench.js'});
  console.log('Canonical GUI Mock API: PASS, simulated 0/2/20 rounds, browser jobs, edits, Word ZIP, network isolation');
})().catch(e=>{console.error(e);process.exitCode=1});
