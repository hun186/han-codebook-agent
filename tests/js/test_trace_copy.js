/* Offline-only regression for 05 round-by-round prompt/response copy icons. */
'use strict';
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const assert=require('node:assert/strict');

const filename=process.argv[2]||path.resolve(__dirname,'../../src/han_codebook/static/index.html');
const source=fs.readFileSync(filename,'utf8');
const script=filename.endsWith('.html')
  ?source.split('<script>')[1].split('</script>')[0]:source;
const start=script.indexOf('let activeExchangeCopyToast=null;');
const end=script.indexOf('async function startBenchmark(){',start);
assert(start>=0&&end>start,'Trace-copy functions must wrap renderTrace');
assert(script.includes("el('exchanges').addEventListener('click',onTraceCopyClick)"),
       'Missing delegated binding for repeated rounds/renders');
assert(source.includes('.exchange-copy-toast')&&source.includes('3000'),
       'Missing adjacent toast or dismiss delay');
const fields=new Map();
const el=id=>{
 if(!fields.has(id))fields.set(id,{innerHTML:'',contains:()=>false});
 return fields.get(id);
};
const handlers=new Map(),timers=[];
let writes=[],fallbackCopy=false;
const document={
 addEventListener:(name,handler)=>handlers.set(name,handler),
 removeEventListener:(name,handler)=>{if(handlers.get(name)===handler)handlers.delete(name)},
 body:{appendChild:(input)=>{assert(input.value!==undefined)}},
 createElement:(name)=>{
  assert.equal(name,'textarea');
  return {value:'',style:{},setAttribute:()=>{},select:()=>{},remove:()=>{}};
 },
 execCommand:cmd=>{assert.equal(cmd,'copy');fallbackCopy=true;return true}
};
const navigator={clipboard:{writeText:async text=>{writes.push(text)}}};
const esc=x=>String(x??'').replace(/[&<>"']/g,
  c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const ctx={
 el,document,navigator,esc,lineChart:()=>'<div>chart</div>',
 notice:msg=>{throw Error('unexpected notice '+msg)},
 setTimeout:(fn,ms)=>{timers.push({fn,ms});return timers.length},
 clearTimeout:()=>{}
};
vm.createContext(ctx);
vm.runInContext(script.slice(start,end),ctx,{filename:'trace-copy-snippet.js'});
const {renderTrace,onTraceCopyClick,hideExchangeCopyToast}=ctx;
assert.equal(typeof renderTrace,'function');
assert.equal(typeof onTraceCopyClick,'function');

function eventFor(button){
 let stopped=false,prevented=false;
 return {target:{closest:()=>button},
  stopPropagation:()=>{stopped=true},
  preventDefault:()=>{prevented=true},
  verified:()=>{assert(stopped&&prevented)}};
}
function buttonFor(raw,toast){
 const section={querySelector:selector=>selector==='pre'?{textContent:raw}:null};
 const button={
  disabled:false,
  closest:selector=>selector==='.exchange-copy-block'?section:null,
  parentElement:{querySelector:selector=>selector==='.exchange-copy-toast'?toast:null}
 };
 el('exchanges').contains=node=>node===button;
 return button;
}
(async()=>{
 const prompt={model:'mock',messages:[{role:'user',content:'密電\\n碼組 <123> & 456'}]};
 const raw='{"choices":[{"message":{"content":"","reasoning":"<script>不可執行</script>"}}]}';
 renderTrace({status:'failed',events:[
  {stage:'vocabulary_llm_request',round:1,payload:{body:prompt}},
  {stage:'vocabulary_llm_response',round:1,payload:{response:raw,usage:{completion_tokens:10}}},
  {stage:'llm_request',round:2,payload:{body:{messages:['R2']}}},
  {stage:'llm_response',round:2,payload:{response:'{"hypotheses":[]}'}}
 ]});
 const html=el('exchanges').innerHTML;
 assert.equal((html.match(/data-copy-exchange="request"/g)||[]).length,2);
 assert.equal((html.match(/data-copy-exchange="response"/g)||[]).length,2);
 assert.equal((html.match(/class="exchange-copy-toast"/g)||[]).length,4);
 assert(html.includes('aria-label="複製送往 LLM 的訊息"'));
 assert(html.includes('aria-label="複製API 原始回覆"'));
 assert(html.includes('&lt;script&gt;不可執行&lt;/script&gt;'));
 assert(!html.includes('<script>不可執行</script>'),'Raw LLM text must be HTML-escaped');
 // Request is copied exactly as shown in <pre>, not from hidden/raw JSON.
 const toast1={hidden:true},promptText=JSON.stringify(prompt,null,2);
 const event1=eventFor(buttonFor(promptText,toast1));
 await onTraceCopyClick(event1);
 event1.verified();
 assert.equal(writes.at(-1),promptText);
 assert.equal(toast1.hidden,false);
 assert.equal(timers.at(-1).ms,3000);
 assert.equal(typeof handlers.get('click'),'function');
 handlers.get('click')();
 assert.equal(toast1.hidden,true,'Clicking page should dismiss toast');
 assert(!handlers.has('click'),'Click listener must be unbound on dismiss');
 // Response copy works independently; three seconds hides the adjacent bubble.
 const toast2={hidden:true},event2=eventFor(buttonFor(raw,toast2));
 await onTraceCopyClick(event2);
 assert.equal(writes.at(-1),raw);
 assert.equal(toast2.hidden,false);
 timers.at(-1).fn();
 assert.equal(toast2.hidden,true);
 // Older HTTP-LAN browsers may require execCommand fallback.
 navigator.clipboard.writeText=async()=>{throw Error('Clipboard API denied')};
 const toast3={hidden:true},event3=eventFor(buttonFor('legacy\nline',toast3));
 await onTraceCopyClick(event3);
 assert.equal(fallbackCopy,true);
 assert.equal(toast3.hidden,false);
 hideExchangeCopyToast();
 // No captured response: disabled copy control; no fake raw JSON.
 renderTrace({status:'failed',events:[{stage:'vocabulary_llm_request',
   round:1,payload:{body:prompt}}]});
 const missing=el('exchanges').innerHTML;
 assert(/data-copy-exchange="response"[^>]* disabled/.test(missing));
 assert(missing.includes('尚無對應回覆'));
 console.log('trace copy buttons, escaped raw prompt/reply, dismiss and fallback PASS');
})().catch(err=>{console.error(err);process.exitCode=1});
