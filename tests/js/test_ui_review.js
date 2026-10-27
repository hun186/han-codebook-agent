'use strict';
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const html = fs.readFileSync(process.argv[2], 'utf8');
const script = html.split('<script>')[1].split('</script>')[0];
const grab = (a, b) => script.slice(script.indexOf(a), script.indexOf(b));
const dom = {};
const el = id => dom[id] ||= {value:'',textContent:'',innerHTML:''};
const m = {id:'X',sender:'original',recipient:'original',codes:['123'],observations:[{source:'old',confidence:0.4}]};
let notes = [];
const context = {el,msg:()=>m,renderObservations:()=>{},notice:(v,b)=>notes.push([v,b]),
    lineChart:()=>'<svg>baseline</svg>',esc:s=>String(s),chartBar:()=>''};
vm.createContext(context);
vm.runInContext(grab('function applyEvidence()', 'function renderObservations()'), context);
Object.assign(el('sender'), {value:'changed'});
el('recipient').value='changed';
el('cipherEdit').value='bad cipher';
el('observations').value='[{"source":"new","confidence":0.8}]';
context.applyEvidence();
assert.strictEqual(m.sender, 'original', 'sender mutated on validation failure');
assert.strictEqual(m.recipient, 'original', 'recipient mutated on validation failure');
assert.strictEqual(m.observations[0].source, 'old');
assert.deepStrictEqual(m.codes, ['123']);
assert(notes.at(-1)[1], 'no validation error shown');
el('cipherEdit').value='007 008';
el('observations').value='[{"source":"new","confidence":2}]';
context.applyEvidence();
assert.strictEqual(m.sender, 'original', 'invalid observation allowed partial write');
el('observations').value='[{"source":"new","confidence":0.8}]';
context.applyEvidence();
assert.strictEqual(m.sender, 'changed');
assert.deepStrictEqual(Array.from(m.codes), ['007','008']);
assert.strictEqual(m.observations[0].source, 'new');
// Render failed-job history independently from result-only sections.
vm.runInContext(grab('function renderJob(j)', 'async function startBenchmark()'), context);
const events=[
 {round:0,stage:'statistical_baseline',payload:{score:3}},
 {round:1,stage:'llm_request',payload:{body:{model:'test',messages:[{content:'request_foo'}]}}},
 {round:1,stage:'llm_response',payload:{response:'context length exceeded',http_status:400,elapsed_ms:30}}
];
el('summary').innerHTML='old result';
context.renderJob({id:'failed1',type:'analysis',status:'failed',logs:['started'],error:'HTTP 400',events,result:null});
assert(el('roundChart').innerHTML.includes('分析失敗'));
assert(el('exchanges').innerHTML.includes('context length exceeded'));
assert(el('exchanges').innerHTML.includes('request_foo'));
assert(el('exchanges').innerHTML.includes('HTTP 400'));
assert.strictEqual(el('summary').innerHTML,'old result','failure should not show a fabricated result');
context.renderJob({id:'queued2',type:'analysis',status:'queued',logs:[],events:[],result:null});
assert(!el('exchanges').innerHTML.includes('request_foo'), 'stale audit exchange displayed');
console.log('UI P2 regression cases passed');
