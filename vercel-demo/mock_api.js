/* Browser-only API adapter for the canonical research workbench.
 * All responses are deterministic MOCK simulations from public synthetic fixtures.
 * No HTTP requests to Python, Ollama, public LLMs, or customer endpoints.
 */
(() => {
  'use strict';
  const nativeFetch = globalThis.fetch.bind(globalThis);
  const clone = value => JSON.parse(JSON.stringify(value));
  const cases = new Map();
  const jobs = new Map();
  const investigations = new Map(); // Browser-memory-only adaptive workflow state.
  const simulatedTerms = [
    '補給線','整備待命','沿線警戒','運輸調度','情報彙整','緊急集結',
    '物資轉運','車輛檢修','前線部署','夜間移動','後勤聯絡','臨時集散',
    '機動補給','行動時序','轉進路線','交通管制','聯合觀察','調查核對'
  ];
  let initialized = null;
  let seed = null;
  let sequence = 0;
  const oracleFields = ['gold', 'ground_truth', 'codebook'];
  const allowedCases = [10, 25, 50, 100];

  function safeCase(input) {
    if (!input || typeof input !== 'object' || Array.isArray(input) ||
        oracleFields.some(k => Object.hasOwn(input, k))) {
      throw Error('Mock demo only accepts research cases without embedded evaluation answers');
    }
    if (!Array.isArray(input.messages) || !input.messages.length ||
        !input.profiles || typeof input.profiles !== 'object') {
      throw Error('Case requires messages and profiles');
    }
    if (input.messages.some(m => !m || typeof m.id !== 'string' ||
        !Array.isArray(m.codes) || !m.codes.length ||
        m.codes.some(c => typeof c !== 'string' || !/^\d+$/.test(c)))) {
      throw Error('Messages need IDs and nonempty numeric-string code groups');
    }
    const byMessage = new Map(input.messages.map(m => [m.id, m.codes]));
    if (byMessage.size !== input.messages.length) {
      throw Error('Each message must have a unique ID');
    }
    // Mirror core.validate_case() + anchors_and_review(): only consistent
    // researcher-provided aligned evidence may become verified anchors.
    // The public fixture is deliberately not a plaintext oracle.
    const anchors = new Map();
    const pairs = input.known_pairs || [];
    if (!Array.isArray(pairs)) throw Error('known_pairs must be an array');
    for (const pair of pairs) {
      if (!pair || typeof pair !== 'object' || Array.isArray(pair)) {
        throw Error('Known pair must be a record');
      }
      const codes = byMessage.get(pair.message_id);
      if (!codes) throw Error('Known pair references an unknown message');
      if (!Object.hasOwn(pair, 'segments')) {
        if (typeof pair.plaintext !== 'string') {
          throw Error('Unsegmented known pair requires plaintext');
        }
        continue; // unsegmented text is never an anchor
      }
      const segments = pair.segments;
      if (!Array.isArray(segments) || segments.length !== codes.length ||
          segments.some(w => typeof w !== 'string' || !w)) {
        throw Error('Known pair segments must match code count and contain nonempty words');
      }
      if (pair.plaintext !== undefined && pair.plaintext !== null &&
          (typeof pair.plaintext !== 'string' ||
           segments.join('') !== pair.plaintext)) {
        throw Error('Known pair: segments do not concatenate to plaintext');
      }
      for (let i = 0; i < codes.length; i++) {
        const previous = anchors.get(codes[i]);
        if (previous !== undefined && previous !== segments[i]) {
          throw Error('Contradictory verified known plaintext for code ' + codes[i]);
        }
        anchors.set(codes[i], segments[i]);
      }
    }
    return clone(input);
  }
  function lexicalCandidates(caseData) {
    const words = new Set();
    for (const p of Object.values(caseData.profiles || {})) {
      for (const w of Object.keys(p.lexicon || {})) words.add(w);
      for (const sentence of p.sentences || []) for (const w of sentence) words.add(w);
    }
    for (const ideas of Object.values(caseData.candidate_ideas || {})) {
      for (const idea of ideas) if (idea.status !== 'rejected') words.add(idea.term);
    }
    // Match core.anchors_and_review(): each *explicitly segmented* known
    // plaintext pair contributes its words to the shared vocabulary. The
    // matching cipher code alone remains verified; reuse by another code
    // is still only an unverified hypothesis. safeCase validates these
    // alignments before any analysis. Unsegmented plaintext is NOT an anchor.
    for (const pair of caseData.known_pairs || []) {
      if (Array.isArray(pair.segments)) {
        for (const term of pair.segments) words.add(term);
      }
    }
    // Match local core.analyze(): a current researcher preferred hypothesis
    // contributes to the shared vocabulary for *all* unverified codes, not
    // just the code where the mark was entered. A removed/reverted mark has
    // no effect, and stale marks on absent codes cannot create new words.
    const presentCodes = new Set(caseData.messages.flatMap(m => m.codes));
    for (const [code, mark] of Object.entries(caseData.hypothesis_marks || {})) {
      if (presentCodes.has(code) && mark && typeof mark.preferred === 'string') {
        words.add(mark.preferred);
      }
    }
    return [...words].filter(w => typeof w === 'string' && w.length > 0 && w.length <= 32).sort();
  }
  const unique = arr => [...new Set(arr.filter(x => typeof x === 'string' && x))];
  const stableIndex = (code, length) => {
    let h = 2166136261;
    for (const x of code) h = Math.imul(h ^ x.charCodeAt(0), 16777619);
    return (h >>> 0) % Math.max(1, length);
  };
  function makeCase(rec) {
    const words = unique(Object.values(rec.statistical).flatMap(p => p.alternatives));
    const priors = Object.fromEntries(words.map((w, i) => [w, (i % 5) + 1]));
    return {
      case_id: 'demo_' + rec.size,
      description: '公開合成資料 ' + rec.size + ' 封；所有候選與模型輸出均為 MOCK',
      profiles: {
        logistics: {keywords: ['補給', '後勤', '倉庫'], lexicon: clone(priors), sentences: [
          ['補給', '車隊', '出發'], ['糧秣', '倉庫', '報告']
        ]},
        operations: {keywords: ['軍司令', '作戰', '第二營'], lexicon: clone(priors), sentences: [
          ['兵力', '集結', '前線'], ['第二營', '奉令', '報告']
        ]},
      },
      messages: clone(rec.messages),
      known_pairs: [],
      candidate_ideas: {},
    };
  }
  async function setup() {
    if (!initialized) initialized = (async () => {
      const r = await nativeFetch('/data/demo.json', {cache:'no-store'});
      if (!r.ok) throw Error('Public synthetic fixture unavailable');
      seed = await r.json();
      if (seed.kind !== 'PUBLIC_SYNTHETIC_MOCK' || seed.llm_used !== false ||
          !Array.isArray(seed.records)) throw Error('Invalid public mock fixture');
      for (const size of allowedCases) {
        const rec = seed.records.find(x => x.size === size);
        if (!rec) throw Error('Missing public synthetic size ' + size);
        cases.set('demo_' + size, makeCase(rec));
      }
    })();
    return initialized;
  }
  function mockMapping(caseData, rounds, useMetadata, addedTerms=[]) {
    const n = caseData.messages.length;
    const source = seed.records.find(x => x.size >= n) || seed.records.at(-1);
    const base = source.statistical;
    const model = source.mock;
    const fromData = rounds ? model : base;
    const vocab = lexicalCandidates(caseData);
    const codes = unique(caseData.messages.flatMap(m => m.codes)).sort();
    const verified = {};
    const byMessage = Object.fromEntries(caseData.messages.map(m => [m.id, m.codes]));
    for (const pair of caseData.known_pairs || []) {
      if (!pair.segments) continue;
      const seq = byMessage[pair.message_id];
      if (!seq || seq.length !== pair.segments.length) throw Error('Known plaintext alignment differs from cipher code count');
      seq.forEach((code, i) => {
        const word = pair.segments[i];
        if (!word || verified[code] && verified[code] !== word) throw Error('Contradictory verified known plaintext');
        verified[code] = word;
      });
    }
    const proposals = {};
    for (const code of codes) {
      if (Object.hasOwn(verified, code)) {
        proposals[code] = {term:verified[code], status:'verified_alignment', alternatives:[], evidence:'Only explicit researcher-entered segmented pairs'};
        continue;
      }
      const mark = (caseData.hypothesis_marks || {})[code] || {};
      const ideas = ((caseData.candidate_ideas || {})[code] || []).filter(x => x.status !== 'rejected');
      const showcase = (code === codes[0] || stableIndex(code, 9) === 0) ?
        addedTerms.filter(w => typeof w === 'string').slice(-4).reverse() : [];
      const ranked = unique([
        ...ideas.filter(x => x.status === 'shortlisted').map(x => x.term),
        ...(mark.preferred ? [mark.preferred] : []),
        ...showcase,
        // A snapshot is only a ranking hint, never a fresh source of words.
        // After an edited/deleted lexicon, removed synthetic snapshot words
        // must not re-enter static, automatic, or human-review results.
        // Explicit non-rejected researcher ideas, preferred marks and this
        // round's approved vocabulary are added separately above/below.
        ...(fromData[code]?.alternatives || []).filter(w => vocab.includes(w)),
        ...ideas.map(x => x.term),
        ...vocab,
      ]);
      let candidates = mark.pinned && mark.preferred ? [mark.preferred] :
        ranked.filter(w => !(mark.excluded || []).includes(w));
      if (!candidates.length) {
        throw Error('Mock code ' + code + ': researcher exclusions remove every candidate');
      }
      if (mark.preferred && !mark.pinned && candidates.includes(mark.preferred)) {
        candidates = [mark.preferred, ...candidates.filter(w => w !== mark.preferred)];
      }
      // A current preferred mark must take precedence even for a code
      // absent from the public fixture snapshot; the hash fallback is
      // only for otherwise unmarked, unsnapshotted codes.
      const selected = mark.preferred ? candidates[0] :
        fromData[code] ? candidates[0] : candidates[stableIndex(code, candidates.length)];
      const alternatives = unique([selected, ...candidates]).slice(0,5).map((term, i) => ({
        term, relative_score: -i * 0.25,
      }));
      proposals[code] = {
        term:selected, status:'hypothesis_unverified',
        alternatives, score_gap_to_second:0.25,
        researcher_mark:mark.preferred || mark.excluded?.length ? mark : null,
        evidence:'MOCK lexical proposal, not verified decoding',
      };
    }
    const decoded_messages = caseData.messages.map(m => {
      const pieces = m.codes.map(c => proposals[c].term);
      const domain = useMetadata ? (m.domain || (m.sender?.includes('軍') ? 'operations' : 'logistics')) : null;
      return {id:m.id, codes:clone(m.codes), suggested_segments:pieces,
        reading:pieces.join(''),domain_inferred:domain,
        verified_codes:m.codes.filter(c => Object.hasOwn(verified,c)).length,
        total_codes:m.codes.length};
    });
    return {case_id:caseData.case_id, proposals, decoded_messages, verified_anchors:verified,
      agent_rounds_completed:rounds, known_code_count:Object.keys(verified).length,
      unknown_code_count:codes.length-Object.keys(verified).length,
      objective_score:-codes.length,
      model:'BROWSER MOCK — no actual model inference', metadata_used:useMetadata,
      limitations:['PUBLIC MOCK: rankings are simulated, not real decryption.',
        'No real LLM calls; never treat generated Chinese as historical plaintext.']};
  }
  function analysis(caseData, rounds, useMetadata, capture=false) {
    const baseline=mockMapping(caseData, 0, useMetadata);
    const result=mockMapping(caseData, rounds, useMetadata);
    const events=[{round:0,stage:'statistical_baseline',payload:{
      score:baseline.objective_score,mapping:mappingDelta(null,baseline).mapping,changed_count:0}}];
    // The static browser mock has just one simulated model ranking.
    // It applies at round one; later rounds must report zero new changes.
    let prior=baseline;
    for(let n=1;n<=rounds;n++){
      const current=n===1?result:prior;
      const accepted = Object.entries(current.proposals)
        .filter(([,p])=>p.status==='hypothesis_unverified')
        .slice(0,15).map(([code,p])=>({code,candidates:p.alternatives.map(a=>a.term).slice(0,2),
          reason:'PUBLIC MOCK simulated candidate, not a model response'}));
      if(capture)traceMockExchange({events},n,'code',{
        task:'static_hypothesis_reranking',round:n,metadata_enabled:useMetadata,
        available_vocabulary:lexicalCandidates(caseData),
        verified_anchors:current.verified_anchors
      },{hypotheses:accepted,label:'PUBLIC MOCK · no model call'});
      events.push({round:n,stage:'llm_proposals_unverified',payload:{accepted,rejected_count:0}});
      events.push({round:n,stage:'rescore',payload:{
        score:current.objective_score,...mappingDelta(prior,current)}});
      prior=current;
    }
    return {result, events};
  }
  function mappingDelta(before, after) {
    const oldMap = Object.fromEntries(Object.entries(before?.proposals || {}).map(([k,v])=>[k,v.term]));
    const newMap = Object.fromEntries(Object.entries(after?.proposals || {}).map(([k,v])=>[k,v.term]));
    const changes = {};
    for(const code of Object.keys(newMap)){
      if (!Object.hasOwn(oldMap,code) && before === null)
        changes[code] = {before:null, after:newMap[code]};
      else if (Object.hasOwn(oldMap,code) && oldMap[code] !== newMap[code])
        changes[code] = {before:oldMap[code], after:newMap[code]};
    }
    return {mapping:newMap,changes,changed_count:Object.keys(changes).length};
  }
  function validationError(message,status=400) {
    const err=new Error(message);err.status=status;throw err;
  }
  function syntheticCandidates(state) {
    const existing=new Set(lexicalCandidates(state.caseData));
    const suggestions=simulatedTerms.filter(w=>!existing.has(w));
    // Rotate deterministic MOCK ideas so the suggested vocabulary evolves by round.
    return suggestions.slice((state.round-1)*3 % Math.max(1,suggestions.length))
      .concat(suggestions.slice(0,(state.round-1)*3 % Math.max(1,suggestions.length)))
      .slice(0,Math.min(5,Math.max(0,128-state.dynamicWords.length)))
      .map(term=>({term,reason:'PUBLIC MOCK · 第'+state.round+'輪跨電文與第三方情報模擬候選',
        source_round:state.round,status:'unverified'}));
  }
  function traceMockExchange(item,round,phase,requestPacket,responsePacket) {
    const prefix=phase==='vocabulary'?'vocabulary_':'';
    item.events.push({round,stage:prefix+'llm_request',payload:{
      url:'PUBLIC MOCK — no HTTP model request',
      model:'PUBLIC MOCK',body:{model:'PUBLIC MOCK',messages:[
        {role:'system',content:'公開展示：所有詞彙都只是未驗證候選'},
        {role:'user',content:JSON.stringify(requestPacket)}]}}});
    item.events.push({round,stage:prefix+'llm_response',payload:{
      response:JSON.stringify(responsePacket),elapsed_ms:0,usage:null,
      note:'Synthetic browser-only payload, not a real model response'}});
  }
  function pendingReview(state) {
    const item=jobs.get(state.id);
    const candidates=syntheticCandidates(state);
    if(state.capture)traceMockExchange(item,state.round,'vocabulary',{
      task:'generate_vocabulary',metadata_enabled:state.metadata,
      round:state.round,case_id:state.caseData.case_id,
      observable_message_count:state.caseData.messages.length,
      current_hypotheses_unverified:Object.keys(state.current?.proposals || {}).length
    },{vocabulary:candidates,patterns:[],label:'PUBLIC MOCK'});
    const review_token='PUBLIC-MOCK-'+state.id+'-ROUND-'+state.round+'-TOKEN-'+(++sequence);
    item.status='awaiting_review';
    item.review_submitted=false;
    item.pending_review={round:state.round,review_token,candidates};
    item.logs.push('[Mock] 第'+state.round+'/'+state.rounds+'輪：等待研究員覆核（可勾選、拒絕或自行新增詞）');
  }
  function applyAdaptiveRound(state, approved, added, suggestions) {
    const item=jobs.get(state.id);
    const chosen=approved.concat(added);
    // An empty first-round case has no lawful mapping until vocabulary is
    // actually approved. Never fabricate a hypothesis from fixture snapshots.
    if(!state.current && !chosen.length)
      validationError('PUBLIC MOCK: approve or add a word to bootstrap the empty vocabulary');
    if(state.dynamicWords.length+chosen.length>128)
      validationError('PUBLIC MOCK: dynamic candidate vocabulary is limited to 128 terms');
    const prior=state.current;
    const existingTerms=new Set(lexicalCandidates(state.caseData));
    if(chosen.some(w=>existingTerms.has(w)))
      validationError('Candidate vocabulary already contains a selected word');
    if(chosen.length){
      const profile=state.caseData.profiles.llm_dynamic_candidates ||= {
        keywords:[],lexicon:{},sentences:[]
      };
      for(const word of chosen)profile.lexicon[word]=1.0;
    }
    state.dynamicWords.push(...chosen);
    const record={round:state.round,model:'PUBLIC MOCK — no model calls',
      status:'unverified_candidate_vocabulary',review_mode:state.mode==='human'?'human':'automatic',
      proposed:suggestions,approved:chosen,
      researcher_added:added.map(term=>({term,status:'unverified',
        source:'researcher',source_round:state.round})),
      rejected_count:suggestions.length-approved.length,
      total_dynamic_terms:state.dynamicWords.length,metadata_used:state.metadata};
    item.events.push({round:state.round,stage:'vocabulary_candidates_unverified',payload:record});
    const rescored=mockMapping(state.caseData,state.round,state.metadata,state.dynamicWords);
    const delta=mappingDelta(prior,rescored);
    item.events.push({round:state.round,stage:'vocabulary_rescore',payload:{
      round:state.round,score:rescored.objective_score,candidate_count:lexicalCandidates(state.caseData).length,
      ...delta}});
    const accepted=Object.entries(rescored.proposals)
      .filter(([,p])=>p.status==='hypothesis_unverified')
      .slice(0,15).map(([code,p])=>({
        code,candidates:p.alternatives.map(x=>x.term).slice(0,2),
        reason:'PUBLIC MOCK · simulated code-hypothesis ranking, not a verified decoding'
      }));
    if(state.capture)traceMockExchange(item,state.round,'code',{
      task:'hypothesis_reranking',round:state.round,
      available_vocabulary:lexicalCandidates(state.caseData).slice(0,128),
      verified_anchors:rescored.verified_anchors,
      note:'PUBLIC MOCK input packet summary, no model call'
    },{hypotheses:accepted,label:'PUBLIC MOCK · no LLM call'});
    item.events.push({round:state.round,stage:'llm_proposals_unverified',
      payload:{accepted,rejected_count:0,returned_count:accepted.length}});
    const fullDelta=mappingDelta(prior,rescored);
    item.events.push({round:state.round,stage:'rescore',
      payload:{score:rescored.objective_score,...fullDelta}});
    item.logs.push('[Mock] 第'+state.round+'輪：'+suggestions.length+' 個模擬 LLM 詞，'
      +approved.length+' 採納，'+added.length+' 人工新增；重算 '+fullDelta.changed_count+' 個碼組，全部未驗證');
    state.current=rescored;
    state.round++;
    if(state.round>state.rounds){
      rescored.agent_rounds_completed=state.rounds;
      rescored.dynamic_vocabulary_terms=state.dynamicWords.slice();
      rescored.adaptive_vocabulary=true;
      rescored.human_vocabulary_review=state.mode==='human';
      item.result=rescored;
      item.status='completed';
      delete item.pending_review;
      delete item.review_submitted;
      item.logs.push('[Mock] 全部 '+state.rounds+' 回合已完成；輸出可下載合成 Word / Markdown');
      investigations.delete(state.id);
    } else if(state.mode==='human') {
      pendingReview(state);
    }
  }
  function startAdaptive(c,rounds,metadata,mode,capture) {
    // Mirror local run_agent() cold start. Static mode still rejects an empty
    // vocabulary; adaptive mode must propose/approve words BEFORE mapping.
    const coldStart=lexicalCandidates(c).length===0;
    const base=coldStart?null:mockMapping(c,0,metadata);
    const start=job('analysis',null,[{round:0,
      stage:coldStart?'vocabulary_bootstrap_required':'statistical_baseline',
      payload:{score:base?.objective_score??null,
        mapping:base?mappingDelta(null,base).mapping:{},changed_count:0,
        ...(coldStart?{note:'PUBLIC MOCK: no baseline; vocabulary approval required before decoding'}:{})}}]);
    const item=jobs.get(start.job_id);
    item.logs=['PUBLIC MOCK · '+mode+' 自適應詞庫分析：完全在瀏覽器記憶體執行，沒有模型呼叫'];
    const state={id:start.job_id,round:1,rounds,metadata,mode,capture,
      caseData:c,current:base,dynamicWords:[]};
    investigations.set(state.id,state);
    if(mode==='human')pendingReview(state);
    else while(state.round<=rounds){
      const suggestions=syntheticCandidates(state);
      if(state.capture)traceMockExchange(item,state.round,'vocabulary',{
        task:'generate_vocabulary',metadata_enabled:metadata,
        round:state.round,case_id:c.case_id,
        observable_message_count:c.messages.length,
        current_hypotheses_unverified:Object.keys(state.current?.proposals || {}).length
      },{vocabulary:suggestions,patterns:[],label:'PUBLIC MOCK'});
      const approved=suggestions.map(x=>x.term);
      applyAdaptiveRound(state,approved,[],suggestions);
    }
    return start;
  }
  function submitReview(id,data) {
    const item=jobs.get(id),state=investigations.get(id);
    if(!item || !state || state.mode!=='human' ||
       item.status!=='awaiting_review' || item.review_submitted)
      validationError('No active vocabulary review for this job',409);
    if(!data || !Number.isInteger(data.round) || typeof data.review_token!=='string' ||
       data.round!==item.pending_review.round ||
       data.review_token!==item.pending_review.review_token)
      validationError('Stale human vocabulary review round or token',409);
    const approved=data.approved,added=data.added??[];
    if(!Array.isArray(approved)||!Array.isArray(added)||
       approved.length+added.length>32||
       [...approved,...added].some(w=>typeof w!=='string')||
       new Set(approved).size!==approved.length||
       new Set(added).size!==added.length)
      validationError('Approve up to 32 distinct candidate strings per round');
    const offered=item.pending_review.candidates.map(x=>x.term);
    const words=new Set(lexicalCandidates(state.caseData));
    if(approved.some(w=>!offered.includes(w)))
      validationError('Cannot approve words outside the current MOCK LLM proposals');
    if(added.some(w=>!w || w.trim()!==w || w.length>24 ||
       /[\x00-\x1f]/.test(w) || offered.includes(w) ||
       approved.includes(w) || words.has(w)))
      validationError('Researcher-added words must be novel 1..24 character unverified terms');
    if(state.dynamicWords.length+approved.length+added.length>128)
      validationError('Dynamic vocabulary limit (128 total) reached');
    // The review response is single-use and bound to its exact round/token.
    const round=state.round;
    // Keep the exact review token usable if all first-round suggestions are
    // rejected: the researcher may approve/add a word instead of losing the job.
    if(!state.current && !approved.length && !added.length)
      validationError('PUBLIC MOCK: approve or add a word to bootstrap the empty vocabulary');
    item.review_submitted=true;
    applyAdaptiveRound(state,approved,added,item.pending_review.candidates);
    return {status:'submitted',round,accepted:approved.length,
      researcher_added:added.length};
  }
  function eventLinks(caseData) {
    const events=[];
    for(const m of caseData.messages)for(const obs of m.observations||[]){
      const observedAt=obs.observed_at||'';
      const ms=Date.parse(observedAt);
      const candidates=caseData.messages.map(other=>{
        const delta=Number.isFinite(ms)? Math.round((Date.parse(other.received_at||'')-ms)/86400000):null;
        return {message_id:other.id, score:delta===null?0.05:+Math.max(0,0.6-Math.abs(delta)*0.1).toFixed(2),
          day_offset:delta===null?undefined:delta,
          basis:'MOCK 時間鄰近假說，沒有語意配對或真實模型'};
      }).sort((a,b)=>b.score-a.score).slice(0,3);
      candidates.push({message_id:null,score:0.35,basis:'可能完全無關，需由研究員人工確認'});
      events.push({source:obs.source||'公開合成觀察',observed_at:observedAt,
        activity:obs.activity||obs.note||'',status:obs.status||'未確認',
        confidence:obs.confidence??0.5,event_id:m.id+'-obs-'+events.length,candidates});
    }
    return {events};
  }
  function benchmark() {
    return {fictional_synthetic:true, real_cryptanalytic_success_not_established:true,
      runs:seed.records.map(rec=>({
        case_id:'demo_'+rec.size,metadata:true,llm_rounds:0,
        metrics:{
          unknown_code_top1_rate:rec.metrics.statistical.correct/rec.metrics.statistical.total,
          non_crib_exact_rate:0,
          verified_anchor_count:0,
          unknown_code_count:rec.metrics.statistical.total,
        },
      }))};
  }
  const nextId=()=>String(++sequence).padStart(16,'0');
  function job(type, value, events=[]) {
    const id=nextId();
    jobs.set(id,{id,type,status:'completed',logs:['PUBLIC MOCK · 純瀏覽器模擬，未呼叫 Python／真實 LLM'],result:value,events,error:null});
    return {job_id:id};
  }
  const settings=()=>({base_url:'MOCK (no network)',endpoint:'MOCK (no network)',
    model:'PUBLIC MOCK LLM',timeout_seconds:90,allow_private_network:false,
    allowed_hosts:[],api_key_env:null,capture_io_available:false,
    note:'Vercel static demo is disconnected from all model endpoints.'});
  function handle(path, data) {
    const url=new URL(path,globalThis.location?.origin||'https://demo.invalid');
    const route=url.pathname;
    if (data && oracleFields.some(k=>Object.hasOwn(data,k))) throw Error('Embedded gold is not allowed');
    if(route==='/api/cases')return [...cases.keys()].map(id=>({id}));
    if(route==='/api/case'){
      const item=cases.get(url.searchParams.get('id'));
      if(!item)throw Error('Unknown case');
      return clone(item);
    }
    if(route==='/api/settings')return settings();
    if(route==='/api/settings/llm')throw Error('公開展示不允許更改模型端點；此頁永遠使用固定 MOCK LLM，不會向任何網址發送資料');
    if(route==='/api/settings/test')return {connected:false,diagnostics:['STATIC MOCK: no TCP or model probe was made'],
      note:'This website cannot access local or LAN models.'};
    if(route==='/api/event-links')return eventLinks(safeCase(data.case));
    if(route==='/api/suggest-vocabulary'){
      const c=safeCase(data.case);
      if(data.confirmed!==true)throw Error('Mock vocabulary action requires explicit confirmation');
      if((c.known_pairs||[]).length)throw Error('Cold-start candidates require no known plaintext pairs');
      const vocabulary=lexicalCandidates(c);
      const candidates=unique([
        ...Object.values(seed.records[0].mock).slice(0,14).map(p=>p.term),
        ...vocabulary,
      ]).slice(0,32);
      return job('vocabulary',{terms:candidates.map(term=>({term,reason:'MOCK 背景語彙候選，須人工審查'})),
        patterns:[['補給','車隊','出發']],model:'PUBLIC MOCK',status:'unverified_pending_researcher_review'});
    }
    if(route==='/api/save'){
      const c=safeCase(data.case),name=data.name;
      if(typeof name!=='string'|| !/^[A-Za-z0-9_-]{1,50}$/.test(name))throw Error('Invalid case name');
      if(cases.has(name))throw Error('Case already exists (create-only)');
      cases.set(name,c);
      return {saved_as:name, note:'Temporary browser session only; refresh clears saved changes'};
    }
    if(route==='/api/start'){
      const c=safeCase(data.case);
      const rounds=data.rounds??0;
      if(!Number.isInteger(rounds)||rounds<0||rounds>20)throw Error('Rounds must be 0..20');
      if(typeof data.use_metadata!=='undefined' && typeof data.use_metadata!=='boolean')
        throw Error('use_metadata must be boolean');
      const mode=data.candidate_mode??'static';
      if(!['static','automatic','human'].includes(mode))
        validationError('candidate_mode must be static, automatic or human');
      if(mode!=='static' && rounds===0)
        validationError('Dynamic vocabulary requires at least one Mock LLM round');
      if(mode!=='static')return startAdaptive(c,rounds,data.use_metadata!==false,mode,data.capture_llm_io===true);
      const out=analysis(c,rounds,data.use_metadata!==false,data.capture_llm_io===true);
      return job('analysis',out.result,out.events);
    }
    if(route==='/api/benchmark')return benchmark();
    if(route==='/api/start-benchmark')return job('benchmark',benchmark());
    const reviewRoute=route.match(/^\/api\/jobs\/([0-9a-f]{16})\/review$/);
    if(reviewRoute)return submitReview(reviewRoute[1],data);
    const cancelRoute=route.match(/^\/api\/jobs\/([0-9a-f]{16})\/cancel$/);
    if(cancelRoute){
      const id=cancelRoute[1],state=investigations.get(id),item=jobs.get(id);
      if(!state||!item||state.mode!=='human'||item.status!=='awaiting_review')
        validationError('No active cancellable human-review job',409);
      if(data && Object.keys(data).length)validationError('Cancel requires an empty request');
      item.status='failed';item.error='PUBLIC MOCK · human vocabulary review canceled';
      item.logs.push('[Mock] 人工覆核模擬工作已取消；未採納候選不會進入解讀');
      delete item.pending_review;delete item.review_submitted;
      investigations.delete(id);
      return {status:'cancelling'};
    }
    const match=route.match(/^\/api\/jobs\/([0-9a-f]{16})$/);
    if(match){
      const item=jobs.get(match[1]);
      if(!item)throw Error('Unknown job');
      return clone(item);
    }
    throw Error('Unknown mock API endpoint: '+route);
  }
  function jsonResponse(data,status=200) {
    return new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json; charset=utf-8'}});
  }
  globalThis.fetch=async (resource, options={}) => {
    const url=new URL(typeof resource==='string'?resource:resource.url,globalThis.location?.origin||'https://demo.invalid');
    const ownOrigin=globalThis.location?.origin||url.origin;
    if(url.origin!==ownOrigin)throw Error('Public mock refuses external network requests');
    if(!url.pathname.startsWith('/api/')) return nativeFetch(resource,options);
    try{
      await setup();
      const body=options.body?JSON.parse(options.body):undefined;
      return jsonResponse(handle(url.href,body));
    }catch(error){
      return jsonResponse({error:String(error.message||error)},error.status||400);
    }
  };

  // The original GUI expects the same API report routes as the local Python
  // backend; offer genuinely downloadable MOCK artifacts without a server.
  const escapeXml =s=>String(s??'').replace(/[&<>"']/g,c=>({
    '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'
  }[c]));
  const enc =new TextEncoder();
  function bytesU16(n){return Uint8Array.of(n&255,(n>>>8)&255)}
  function bytesU32(n){return Uint8Array.of(n&255,(n>>>8)&255,(n>>>16)&255,(n>>>24)&255)}
  function concat(arr) {
    const result=new Uint8Array(arr.reduce((n,a)=>n+a.length,0));let i=0;
    for(const a of arr){result.set(a,i);i+=a.length}return result;
  }
  function crc32(data) {
    let crc=0xffffffff;
    for(const byte of data){crc^=byte;for(let j=0;j<8;j++)crc=(crc>>>1)^((crc&1)?0xedb88320:0)}
    return (crc^0xffffffff)>>>0;
  }
  function zip(entries) {
    const files=[],central=[];let offset=0;
    for(const [name,text] of entries){
      const filename=enc.encode(name),data=enc.encode(text),crc=crc32(data);
      const local=concat([bytesU32(0x04034b50),bytesU16(20),bytesU16(0),bytesU16(0),
        bytesU16(0),bytesU16(0),bytesU32(crc),bytesU32(data.length),bytesU32(data.length),
        bytesU16(filename.length),bytesU16(0),filename,data]);
      files.push(local);
      central.push(concat([bytesU32(0x02014b50),bytesU16(20),bytesU16(20),bytesU16(0),
        bytesU16(0),bytesU16(0),bytesU16(0),bytesU32(crc),bytesU32(data.length),
        bytesU32(data.length),bytesU16(filename.length),bytesU16(0),bytesU16(0),
        bytesU16(0),bytesU16(0),bytesU32(0),bytesU32(offset),filename]));
      offset+=local.length;
    }
    const middle=concat(central);
    const end=concat([bytesU32(0x06054b50),bytesU16(0),bytesU16(0),
      bytesU16(entries.length),bytesU16(entries.length),bytesU32(middle.length),
      bytesU32(offset),bytesU16(0)]);
    return concat([...files,middle,end]);
  }
  function reportDocx(result) {
    const para=text=>'<w:p><w:r><w:t xml:space="preserve">'+escapeXml(text)+'</w:t></w:r></w:p>';
    const cell=text=>'<w:tc>'+para(text)+'</w:tc>';
    const row=arr=>'<w:tr>'+arr.map(cell).join('')+'</w:tr>';
    const table='<w:tbl>'+[
      ['數字碼組','模擬候選','狀態'],
      ...Object.entries(result.proposals).map(([c,p])=>[c,p.term,p.status])
    ].map(row).join('')+'</w:tbl>';
    const doc='<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
      +'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
      +para('Han Codebook Agent · PUBLIC MOCK 研究報告')
      +para('此報告來自公開合成資料與瀏覽器模擬，沒有執行真正的 LLM／Python 推論，也不代表解開歷史密電。')
      +para('案例：'+result.case_id+'　電文：'+result.decoded_messages.length+'　MOCK 回合：'+result.agent_rounds_completed)
      +table+'<w:sectPr/></w:body></w:document>';
    const types='<?xml version="1.0" encoding="UTF-8"?>'
      +'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
      +'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
      +'<Default Extension="xml" ContentType="application/xml"/>'
      +'<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
      +'</Types>';
    const rels='<?xml version="1.0" encoding="UTF-8"?>'
      +'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
      +'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
      +'</Relationships>';
    return zip([['[Content_Types].xml',types],['_rels/.rels',rels],['word/document.xml',doc]]);
  }
  function reportMarkdown(result) {
    return '# PUBLIC MOCK · 中文數字碼本研究報告\n\n'
      +'**公開合成資料；瀏覽器內的模擬結果，不是歷史密文的破譯。**\n\n'
      +'案例：'+result.case_id+'\n\n'
      +'| 數字碼組 | 模擬候選 | 狀態 |\n|---|---|---|\n'
      +Object.entries(result.proposals).map(([c,p])=>'| '+c+' | '+p.term+' | '+p.status+' |').join('\n')+'\n';
  }
  function downloadMock(link,ext,jobId){
    const item=jobs.get(jobId);
    if(!item || item.type!=='analysis'||item.status!=='completed')return;
    const body=ext==='docx'?reportDocx(item.result):enc.encode(reportMarkdown(item.result));
    const content=ext==='docx'?'application/vnd.openxmlformats-officedocument.wordprocessingml.document':'text/markdown;charset=utf-8';
    const objectUrl=URL.createObjectURL(new Blob([body],{type:content}));
    const a=document.createElement('a');
    a.href=objectUrl;a.download='PUBLIC-MOCK-research-report.'+ext;
    document.body.appendChild(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(objectUrl),1000);
  }
  document.addEventListener('click',event=>{
    const link=event.target.closest?.('a[href]');
    if(!link)return;
    const path=new URL(link.href,location.href).pathname;
    const match=path.match(/^\/api\/jobs\/([0-9a-f]{16})\/report\.(docx|md)$/);
    if(match){event.preventDefault();downloadMock(link,match[2],match[1])}
  },true);

  document.addEventListener('DOMContentLoaded', () => {
    // Keep all structural/functional controls identical to the canonical GUI,
    // while correcting backend-specific wording on this PUBLIC MOCK surface.
    const benchmark = document.getElementById('runBenchmark');
    if (benchmark) benchmark.textContent = '執行公開合成 Mock 基準（10／25／50／100）';
    const settingsPage = document.getElementById('modelSettings');
    if (settingsPage) settingsPage.querySelector('.panel')?.insertAdjacentHTML(
      'afterbegin',
      '<p class="alert" role="status">【展示模式】模型設定欄位僅供觀看本機操作版面；此頁不會儲存或使用任何端點設定，連線測試永遠顯示未連線。</p>'
    );
    const status = document.getElementById('llmSettingStatus');
    if (status) status.textContent = 'PUBLIC MOCK：不提供任何真實模型連線或端點設定';
  });

  globalThis.HanMockDemo = Object.freeze({
    // Read-only inspection helpers for automated regression tests.
    getJob:id=>jobs.get(id)?clone(jobs.get(id)):null,
    getSavedCase:id=>cases.get(id)?clone(cases.get(id)):null,
    makeDocxForTest:reportDocx,
    runForTest:handle,
  });
})();