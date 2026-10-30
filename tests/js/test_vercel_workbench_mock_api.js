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
  const staticTraceId=(await post('/api/start',{
    case:caseData,rounds:3,candidate_mode:'static',capture_llm_io:true
  })).job_id;
  const staticTrace=await get('/api/jobs/'+staticTraceId);
  assert.equal(staticTrace.events.filter(e=>e.stage==='llm_request').length,3);
  assert.equal(staticTrace.events.filter(e=>e.stage==='llm_response').length,3);
  const staticRescores=staticTrace.events.filter(e=>e.stage==='rescore');
  assert.equal(staticRescores.length,3);
  assert.ok(staticRescores[0].payload.changed_count>0);
  for(const event of staticRescores){
    assert.equal(event.payload.changed_count,Object.keys(event.payload.changes).length);
    assert.ok(event.payload.mapping);
  }
  assert.equal(staticRescores[1].payload.changed_count,0);
  assert.equal(staticRescores[2].payload.changed_count,0);
  const noCapture=(await post('/api/start',{
    case:caseData,rounds:2,candidate_mode:'static',capture_llm_io:false
  })).job_id;
  assert.equal((await get('/api/jobs/'+noCapture)).events.filter(
    e=>['llm_request','llm_response'].includes(e.stage)).length,0);

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
  // Codex PR #10 P2: fixture alternatives must NOT resurrect words removed
  // by the researcher. The Mock snapshot is a ranking prior, not a word list.
  const narrowed=JSON.parse(JSON.stringify(caseData));
  for(const profile of Object.values(narrowed.profiles)){
    profile.lexicon={'僅供測試':1};
    profile.sentences=[];
  }
  narrowed.candidate_ideas={};
  narrowed.hypothesis_marks={};
  const surviving=new Set(['僅供測試']);
  const assertAllowed=(result,allowed)=>{
    const available=new Set(allowed);
    for(const [code,p] of Object.entries(result.proposals)){
      if(p.status==='verified_alignment')continue;
      assert.ok(available.has(p.term),'removed fixture term resurrected for '+code+': '+p.term);
      assert.ok(p.alternatives.every(x=>available.has(x.term)),
        'removed fixture alternative leaked for '+code);
    }
    for(const msg of result.decoded_messages)
      assert.ok(msg.suggested_segments.every(x=>available.has(x)),
        'report/decoding contains removed vocabulary');
  };
  // Static 0 and static >0 share the underlying mapping path.
  for(const rounds of [0,2]){
    const id=(await post('/api/start',{
      case:narrowed,rounds,candidate_mode:'static'
    })).job_id;
    const result=(await get('/api/jobs/'+id)).result;
    assertAllowed(result,surviving);
    assert.ok(Object.values(result.proposals).every(p=>p.term==='僅供測試'));
  }
  const autoNarrowId=(await post('/api/start',{
    case:narrowed,rounds:2,candidate_mode:'automatic'
  })).job_id;
  const autoNarrow=await get('/api/jobs/'+autoNarrowId);
  assert.equal(autoNarrow.status,'completed');
  assertAllowed(autoNarrow.result,
    ['僅供測試',...autoNarrow.result.dynamic_vocabulary_terms]);
  // Human review does not grant all offered Mock words by default.
  const humanNarrowId=(await post('/api/start',{
    case:narrowed,rounds:1,candidate_mode:'human'
  })).job_id;
  const humanNarrowPending=await get('/api/jobs/'+humanNarrowId);
  assert.equal(humanNarrowPending.status,'awaiting_review');
  await post('/api/jobs/'+humanNarrowId+'/review',{
    round:humanNarrowPending.pending_review.round,
    review_token:humanNarrowPending.pending_review.review_token,
    approved:[],added:[]
  });
  const humanNarrow=(await get('/api/jobs/'+humanNarrowId)).result;
  assertAllowed(humanNarrow,surviving);
  assert.deepEqual(humanNarrow.dynamic_vocabulary_terms,[]);
  // Explicit approved words and researcher-entered hypotheses remain valid
  // even when they are absent from the underlying editable lexicon.
  const shortlist=JSON.parse(JSON.stringify(narrowed));
  shortlist.candidate_ideas={
    [firstCode]:[{term:'研究員明確保留',source:'researcher',status:'shortlisted'}]
  };
  const shortlistResult=(await get('/api/jobs/'+(await post('/api/start',{
    case:shortlist,rounds:0
  })).job_id)).result;
  assert.equal(shortlistResult.proposals[firstCode].term,'研究員明確保留');
  assertAllowed(shortlistResult,['僅供測試','研究員明確保留']);
  const approvedHuman=(await post('/api/start',{
    case:narrowed,rounds:1,candidate_mode:'human'
  })).job_id;
  const approval=(await get('/api/jobs/'+approvedHuman)).pending_review;
  const approvedWord=approval.candidates[0].term;
  await post('/api/jobs/'+approvedHuman+'/review',{
    round:approval.round,review_token:approval.review_token,
    approved:[approvedWord],added:['研究員人工補充']
  });
  const allowedHuman=(await get('/api/jobs/'+approvedHuman)).result;
  assertAllowed(allowedHuman,['僅供測試',approvedWord,'研究員人工補充']);
  // Excluding the entire remaining vocabulary must fail closed, never pull
  // an excluded word back from a snapshot to manufacture a result.
  const excluded=JSON.parse(JSON.stringify(narrowed));
  excluded.hypothesis_marks={[firstCode]:{
    preferred:null,pinned:false,excluded:['僅供測試']
  }};
  const rejectedRun=await sandbox.fetch('/api/start',{
    method:'POST',body:JSON.stringify({case:excluded,rounds:0})
  });
  assert.equal(rejectedRun.status,400);
  assert.match((await rejectedRun.json()).error,/exclusions remove every candidate/);

  // Codex PR #10 P2 follow-up: local core.analyze() treats active
  // hypothesis_marks.preferred as part of the *shared* vocabulary. With an
  // empty profile dictionary, a mark on code 000 must also let 001 run.
  const marksOnly=JSON.parse(JSON.stringify(caseData));
  marksOnly.messages=[{id:'empty-lexicon',codes:['000','001']}];
  marksOnly.known_pairs=[];
  marksOnly.candidate_ideas={};
  for(const profile of Object.values(marksOnly.profiles)){
    profile.lexicon={};
    profile.sentences=[];
  }
  marksOnly.hypothesis_marks={
    '000':{preferred:'研究員新詞',pinned:false,excluded:[]}
  };
  for(const rounds of [0,2]){
    const id=(await post('/api/start',{
      case:marksOnly,rounds,candidate_mode:'static'
    })).job_id;
    const result=(await get('/api/jobs/'+id)).result;
    assert.equal(result.known_code_count,0,
      'researcher preference must NOT become verified known plaintext');
    assertAllowed(result,['研究員新詞']);
    assert.equal(result.proposals['000'].term,'研究員新詞');
    assert.equal(result.proposals['001'].term,'研究員新詞');
    assert.ok(Object.values(result.proposals)
      .every(p=>p.status==='hypothesis_unverified'));
  }
  const autoMarksId=(await post('/api/start',{
    case:marksOnly,rounds:2,candidate_mode:'automatic'
  })).job_id;
  const autoMarks=await get('/api/jobs/'+autoMarksId);
  assert.equal(autoMarks.status,'completed');
  assert.deepEqual(Object.values(autoMarks.events[0].payload.mapping),
    ['研究員新詞','研究員新詞'],
    'automatic-mode baseline must use researcher preferred vocabulary');
  assertAllowed(autoMarks.result,
    ['研究員新詞',...autoMarks.result.dynamic_vocabulary_terms]);
  const humanMarksId=(await post('/api/start',{
    case:marksOnly,rounds:1,candidate_mode:'human'
  })).job_id;
  const humanMarksBefore=await get('/api/jobs/'+humanMarksId);
  assert.equal(humanMarksBefore.status,'awaiting_review');
  assert.deepEqual(Object.values(humanMarksBefore.events[0].payload.mapping),
    ['研究員新詞','研究員新詞']);
  await post('/api/jobs/'+humanMarksId+'/review',{
    round:humanMarksBefore.pending_review.round,
    review_token:humanMarksBefore.pending_review.review_token,
    approved:[],added:[]
  });
  const humanMarksAfter=await get('/api/jobs/'+humanMarksId);
  assert.equal(humanMarksAfter.status,'completed');
  assertAllowed(humanMarksAfter.result,['研究員新詞']);
  assert.equal(humanMarksAfter.result.proposals['001'].term,'研究員新詞');

  // A second preference is shared as well, while exclusions remain per-code.
  const twoMarks=JSON.parse(JSON.stringify(marksOnly));
  twoMarks.hypothesis_marks['001']={
    preferred:'另一個人工詞',pinned:false,excluded:['研究員新詞']
  };
  const twoMarksResult=(await get('/api/jobs/'+(await post('/api/start',{
    case:twoMarks,rounds:0
  })).job_id)).result;
  assertAllowed(twoMarksResult,['研究員新詞','另一個人工詞']);
  assert.equal(twoMarksResult.proposals['000'].term,'研究員新詞');
  assert.equal(twoMarksResult.proposals['001'].term,'另一個人工詞');
  assert.equal(twoMarksResult.proposals['001'].alternatives.some(
    candidate=>candidate.term==='研究員新詞'),false,
    'code exclusions must still override shared preferred words');

  // Undoing the sole manual preferred mark must not silently resurrect
  // snapshot terms from the deleted dictionary or invent a vocabulary.
  const undone=JSON.parse(JSON.stringify(marksOnly));
  undone.hypothesis_marks={};
  const emptyResponse=await sandbox.fetch('/api/start',{
    method:'POST',body:JSON.stringify({case:undone,rounds:0})
  });
  assert.equal(emptyResponse.status,400);
  assert.match((await emptyResponse.json()).error,/remove every candidate/);

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
  // Codex P1: contradictory plaintext/segments must never be upgraded
  // to verified_alignment in analysis or accepted by the Mock save path.
  const inconsistent=JSON.parse(JSON.stringify(caseData));
  inconsistent.messages[0].codes=['0007'];
  inconsistent.known_pairs=[{
    message_id:inconsistent.messages[0].id,
    plaintext:'可信原文',segments:['相反假說']
  }];
  for(const route of ['/api/start','/api/save','/api/event-links']){
    const payload=route==='/api/start'?{case:inconsistent,rounds:0}:
      route==='/api/save'?{case:inconsistent,name:'unsafe_alignment'}:
      {case:inconsistent};
    const response=await sandbox.fetch(route,{
      method:'POST',body:JSON.stringify(payload)
    });
    assert.equal(response.status,400,route+' must reject contradictory aligned truth');
    assert.match((await response.json()).error,/do not concatenate to plaintext/);
  }
  assert.equal(sandbox.HanMockDemo.getSavedCase('unsafe_alignment'),null);
  const consistent=JSON.parse(JSON.stringify(inconsistent));
  consistent.known_pairs[0].segments=['可信原文'];
  const accepted=(await post('/api/start',{case:consistent,rounds:0})).job_id;
  const validResult=(await get('/api/jobs/'+accepted)).result;
  assert.equal(validResult.proposals['0007'].term,'可信原文');
  assert.equal(validResult.proposals['0007'].status,'verified_alignment');

  const crossConflict=JSON.parse(JSON.stringify(caseData));
  crossConflict.messages[0].codes=['0007'];
  crossConflict.messages[1].codes=['0007'];
  crossConflict.known_pairs=[
    {message_id:crossConflict.messages[0].id,segments:['甲']},
    {message_id:crossConflict.messages[1].id,segments:['乙']}
  ];
  const cross=await sandbox.fetch('/api/start',{method:'POST',body:JSON.stringify({
    case:crossConflict,rounds:0
  })});
  assert.equal(cross.status,400);
  assert.match((await cross.json()).error,/Contradictory verified known plaintext/);

  const repeated=JSON.parse(JSON.stringify(caseData));
  repeated.messages[0].codes=['0007','0007'];
  repeated.known_pairs=[{message_id:repeated.messages[0].id,segments:['甲','乙']}];
  const repeatedResponse=await sandbox.fetch('/api/start',{
    method:'POST',body:JSON.stringify({case:repeated,rounds:0})
  });
  assert.equal(repeatedResponse.status,400);
  assert.match((await repeatedResponse.json()).error,/Contradictory verified known plaintext/);

  const unsegmented=JSON.parse(JSON.stringify(caseData));
  unsegmented.known_pairs=[{
    message_id:unsegmented.messages[0].id,
    plaintext:'尚未切詞的虛構明文'
  }];
  const unsegmentedId=(await post('/api/start',{case:unsegmented,rounds:0})).job_id;
  const unsegmentedResult=(await get('/api/jobs/'+unsegmentedId)).result;
  assert.ok(Object.values(unsegmentedResult.proposals)
    .every(p=>p.status!=='verified_alignment'));

  // Full adaptive parity: identical GUI/API stages, all computations synthetic.
  const auto=(await post('/api/start',{
    case:caseData,rounds:3,use_metadata:true,candidate_mode:'automatic'
  })).job_id;
  const automatic=await get('/api/jobs/'+auto);
  assert.equal(automatic.status,'completed');
  assert.equal(automatic.result.agent_rounds_completed,3);
  assert.equal(automatic.result.adaptive_vocabulary,true);
  assert.equal(automatic.result.human_vocabulary_review,false);
  assert.ok(automatic.result.dynamic_vocabulary_terms.length>0);
  assert.equal(automatic.events.filter(x=>x.stage==='vocabulary_candidates_unverified').length,3);
  assert.equal(automatic.events.filter(x=>x.stage==='vocabulary_rescore').length,3);
  assert.equal(automatic.events.filter(x=>x.stage==='rescore').length,3);
  assert.ok(Object.values(automatic.result.proposals)
    .every(p=>p.status==='hypothesis_unverified'));

  assert.equal(automatic.events.filter(e=>e.stage==='vocabulary_llm_request').length,0,
    'Full I/O audit must remain opt-in even for browser-only synthetic traces');
  const captured=(await post('/api/start',{
    case:caseData,rounds:2,candidate_mode:'automatic',capture_llm_io:true
  })).job_id;
  const trace=(await get('/api/jobs/'+captured)).events;
  for(const stage of ['vocabulary_llm_request','vocabulary_llm_response',
                      'llm_request','llm_response']){
    assert.equal(trace.filter(e=>e.stage===stage).length,2,stage+' should have 2 synthetic records');
  }
  for(const round of [1,2]){
    const vocab=trace.find(e=>e.round===round&&e.stage==='vocabulary_llm_response');
    const code=trace.find(e=>e.round===round&&e.stage==='llm_response');
    assert.ok(JSON.parse(vocab.payload.response).vocabulary);
    assert.ok(JSON.parse(code.payload.response).hypotheses);
    assert.ok(trace.filter(e=>e.round===round&&e.stage.endsWith('llm_request'))
      .every(e=>e.payload.body.model==='PUBLIC MOCK'));
  }
  const human=(await post('/api/start',{
    case:caseData,rounds:2,candidate_mode:'human',use_metadata:true
  })).job_id;
  const first=await get('/api/jobs/'+human);
  assert.equal(first.status,'awaiting_review');
  assert.equal(first.pending_review.round,1);
  assert.ok(first.pending_review.candidates.length>0);
  const offered=first.pending_review.candidates[0].term;
  const h1={round:1,review_token:first.pending_review.review_token,
    approved:[offered],added:['研究員自訂詞甲']};
  const badToken=await sandbox.fetch('/api/jobs/'+human+'/review',{
    method:'POST',body:JSON.stringify({...h1,review_token:'bad-token-0000'})
  });
  assert.equal(badToken.status,409);
  const badDuplicate=await sandbox.fetch('/api/jobs/'+human+'/review',{
    method:'POST',body:JSON.stringify({...h1,added:[offered]})
  });
  assert.equal(badDuplicate.status,400);
  assert.equal((await get('/api/jobs/'+human)).status,'awaiting_review');
  const accepted1=await post('/api/jobs/'+human+'/review',h1);
  assert.equal(accepted1.accepted,1);
  assert.equal(accepted1.researcher_added,1);
  const second=await get('/api/jobs/'+human);
  assert.equal(second.status,'awaiting_review');
  assert.equal(second.pending_review.round,2);
  assert.notEqual(second.pending_review.review_token,first.pending_review.review_token);
  const stale=await sandbox.fetch('/api/jobs/'+human+'/review',{
    method:'POST',body:JSON.stringify(h1)
  });
  assert.equal(stale.status,409);
  const duplicatePrior=await sandbox.fetch('/api/jobs/'+human+'/review',{
    method:'POST',body:JSON.stringify({
      round:2,review_token:second.pending_review.review_token,
      approved:[],added:['研究員自訂詞甲']
    })
  });
  assert.equal(duplicatePrior.status,400);
  assert.equal((await get('/api/jobs/'+human)).status,'awaiting_review');
  const accepted2=await post('/api/jobs/'+human+'/review',{
    round:2,review_token:second.pending_review.review_token,
    approved:[],added:['研究員自訂詞乙']
  });
  assert.equal(accepted2.accepted,0);
  assert.equal(accepted2.researcher_added,1);
  const finished=await get('/api/jobs/'+human);
  assert.equal(finished.status,'completed');
  assert.equal(finished.result.agent_rounds_completed,2);
  assert.ok(finished.result.dynamic_vocabulary_terms.includes('研究員自訂詞甲'));
  assert.ok(finished.result.dynamic_vocabulary_terms.includes('研究員自訂詞乙'));
  assert.deepEqual(
    Array.from(finished.events.filter(x=>x.stage==='vocabulary_candidates_unverified'),
      e=>e.payload.researcher_added.map(w=>w.term)),
    [['研究員自訂詞甲'],['研究員自訂詞乙']]);
  assert.ok(finished.events.filter(x=>x.stage==='vocabulary_rescore')
    .every(e=>e.payload.mapping&&typeof e.payload.changed_count==='number'));
  assert.ok(Object.values(finished.result.proposals)
    .every(p=>p.status!=='verified_alignment'));
  const sampleCode=Object.keys(finished.result.proposals).sort()[0];
  assert.equal(finished.result.proposals[sampleCode].term,'研究員自訂詞乙');
  const finishedDoc=Buffer.from(sandbox.HanMockDemo.makeDocxForTest(finished.result));
  assert.ok(finishedDoc.includes(Buffer.from('word/document.xml')));

  const cancelHuman=(await post('/api/start',{
    case:caseData,rounds:2,candidate_mode:'human'
  })).job_id;
  assert.equal((await get('/api/jobs/'+cancelHuman)).status,'awaiting_review');
  assert.equal((await post('/api/jobs/'+cancelHuman+'/cancel',{})).status,'cancelling');
  assert.equal((await get('/api/jobs/'+cancelHuman)).status,'failed');
  const rejectedPost=await sandbox.fetch('/api/jobs/'+cancelHuman+'/review',{
    method:'POST',body:JSON.stringify({
      round:1,review_token:'PUBLIC-MOCK-expired',approved:[],added:[]
    })
  });
  assert.equal(rejectedPost.status,409);
  const invalidMode=await sandbox.fetch('/api/start',{
    method:'POST',body:JSON.stringify({case:caseData,rounds:0,candidate_mode:'automatic'})
  });
  assert.equal(invalidMode.status,400);
  // The canonical Vercel GUI must actually submit the same reviewer-added
  // fields as the local UI; not merely display a decorative input.
  const guiJobId=(await post('/api/start',{
    case:caseData,rounds:1,candidate_mode:'human'
  })).job_id;
  const guiJob=await get('/api/jobs/'+guiJobId);
  const uiJs=fs.readFileSync(path.join(base,'workbench.js'),'utf8');
  const uiBegin=uiJs.indexOf('function renderPendingVocabularyReview(');
  const uiEnd=uiJs.indexOf('async function start(){',uiBegin);
  assert.ok(uiBegin>=0 && uiEnd>uiBegin);
  const submitButton={disabled:false,textContent:'',onclick:null};
  const newWordArea={value:'研究員畫面手填一\n研究員畫面手填二'};
  const pane={dataset:{},hidden:true,innerHTML:'',
    replaceChildren(){this.innerHTML='';},
    querySelector(selector){
      if(selector==='#approveVocabulary')return submitButton;
      if(selector==='#reviewAddedWords')return newWordArea;
      throw Error('Unexpected control in review GUI: '+selector);
    },
    querySelectorAll(selector){
      assert.equal(selector,'input[data-review-term]:checked');
      return []; // Explicitly reject all suggested words; use user additions only.
    }
  };
  const reviewMessages=[];
  const ui={console,Set,Number,Array,
    el:id=>{assert.equal(id,'pendingVocabularyReview');return pane;},
    matchesOrigin:()=>true,
    esc:x=>String(x),
    notice:(msg,err)=>reviewMessages.push({msg,err}),
    api:(uri,payload)=>post(uri,payload),
    guiJob,guiOrigin:{}
  };
  vm.createContext(ui);
  new vm.Script(uiJs.slice(uiBegin,uiEnd),{filename:'review-ui.js'}).runInContext(ui);
  vm.runInContext('renderPendingVocabularyReview(guiJob,guiOrigin)',ui);
  assert.equal(pane.hidden,false);
  assert.match(pane.innerHTML,/reviewAddedWords/);
  assert.match(pane.innerHTML,/研究員新增候選詞/);
  assert.equal(typeof submitButton.onclick,'function');
  await submitButton.onclick();
  assert.equal(submitButton.disabled,true);
  assert.equal(reviewMessages.filter(x=>x.err).length,0);
  const guiResult=(await get('/api/jobs/'+guiJobId));
  assert.equal(guiResult.status,'completed');
  assert.ok(guiResult.result.dynamic_vocabulary_terms.includes('研究員畫面手填一'));
  assert.ok(guiResult.result.dynamic_vocabulary_terms.includes('研究員畫面手填二'));
  assert.deepEqual(guiResult.events.find(x=>x.stage==='vocabulary_candidates_unverified')
    .payload.researcher_added.map(x=>x.term),['研究員畫面手填一','研究員畫面手填二']);

  const leak=await sandbox.fetch('/api/start',{
    method:'POST',body:JSON.stringify({case:{...caseData,ground_truth:{'0007':'答案'}},rounds:2})
  });
  assert.equal(leak.status,400);
  await assert.rejects(()=>sandbox.fetch('https://api.openai.com/v1/chat/completions'));
  assert.deepEqual(requests,['/data/demo.json']);
  assert.equal(typeof callbacks.click,'function');
  new vm.Script(fs.readFileSync(path.join(base,'workbench.js'),'utf8'),{filename:'workbench.js'});
  console.log('Canonical GUI Mock API: PASS, static 0/2/20 rounds, adaptive automatic + human rounds, researcher-added terms, stale approvals, report, network isolation');
})().catch(e=>{console.error(e);process.exitCode=1});
