/* No real network: transport preflight must expose saved API mode before sending case. */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const filename=process.argv[2]||path.resolve(__dirname,'../../src/han_codebook/static/index.html');
const source=fs.readFileSync(filename,'utf8');
const script=filename.endsWith('.html')?source.split('<script>')[1].split('</script>')[0]:source;
const settingsBegin=script.indexOf("let savedLLMProvider='local';");
const settingsEnd=script.indexOf('function presentCase(){',settingsBegin);
const startBegin=script.indexOf('async function start(){');
const startEnd=script.indexOf('async function save(){',startBegin);
assert(settingsBegin>0&&settingsEnd>settingsBegin&&startBegin>settingsEnd&&startEnd>startBegin);
const fields={};
function el(id){return fields[id]||(fields[id]={
 value:'',checked:false,disabled:false,hidden:false,style:{},textContent:'',
 replaceChildren(){},add(){}
})}
Object.assign(el('rounds'),{value:'3'});
Object.assign(el('candidateMode'),{value:'automatic'});
Object.assign(el('vocabZeroPatience'),{value:'2'});
Object.assign(el('postrunHoldoutFolds'),{value:'0'});
Object.assign(el('progressStopPatience'),{value:'0'});
let settings={
 provider:'local',model:'qwen3.8:latest-128k',
 base_url:'http://192.168.0.134:11434',
 confirmation_token:'receipt-old',
 timeout_seconds:180,allow_private_network:true,allow_external_api:false,
 max_output_tokens:8192,api_key_env:''
};
const confirmations=[],notices=[];
const api=async (route,payload)=>{
 if(route==='/api/settings')return {...settings};
 throw Error('Never call '+route+' in preflight-only test');
};
const context={
 el,api,URL,Option:class{},
 confirm:message=>{confirmations.push(message);return false},
 notice:(message,bad)=>notices.push({message,bad}),
 captureOrigin:()=>({case:'sample'}),matchesOrigin:()=>true,
 research:{case_id:'demo'}
};
vm.createContext(context);
vm.runInContext(script.slice(settingsBegin,settingsEnd),context);
vm.runInContext(script.slice(startBegin,startEnd),context);
const execute=js=>vm.runInContext(js,context);
(async()=>{
 await execute('loadLLMSettings()');
 const compat=execute('llmTransportSummary({provider:"local",base_url:"http://192.168.0.134:11434"})');
 assert.equal(compat.provider,'local');
 assert.equal(compat.endpoint,'http://192.168.0.134:11434/v1/chat/completions');
 assert.match(compat.warning,/並未使用 Ollama 原生/);
 assert.equal(execute('llmTransportSummary({provider:"ollama",base_url:"http://192.168.0.134:11434"}).endpoint'),
  'http://192.168.0.134:11434/api/chat');
 assert.equal(execute('llmTransportSummary({provider:"ollama",base_url:"http://192.168.0.134:11434"}).warning'),'');
 assert.equal(execute('llmTransportSummary({provider:"local",base_url:"http://192.168.0.134:18080/v1"}).endpoint'),
  'http://192.168.0.134:18080/v1/chat/completions');
 assert.equal(execute('llmTransportSummary({provider:"deepinfra",base_url:"https://api.deepinfra.com/v1/openai"}).endpoint'),
  'https://api.deepinfra.com/v1/openai/chat/completions');
 await execute('start()');
 assert.equal(confirmations.length,1);
 assert.match(confirmations[0],/local（OpenAI-compatible）/);
 assert.match(confirmations[0],/192\.168\.0\.134:11434\/v1\/chat\/completions/);
 assert.match(confirmations[0],/Ollama 原生 \/api\/chat/);
 // Changing on-screen provider without saving must never send actual case.
 el('llmPreset').value='ollama';
 await execute('start()');
 assert.equal(confirmations.length,1);
 assert.match(notices.at(-1).message,/尚未儲存/);
 el('llmPreset').value='compatible';
 // Another browser tab changes settings; stale visible fields must not authorize.
 settings={...settings,provider:'ollama',confirmation_token:'receipt-new'};
 await execute('start()');
 assert.match(notices.at(-1).message,/另一個視窗/);
 assert.equal(confirmations.length,1);
 await execute('loadLLMSettings()');
 await execute('start()');
 assert.equal(confirmations.length,2);
 assert.match(confirmations[1],/Ollama 原生 API/);
 assert.match(confirmations[1],/\/api\/chat/);
 assert.doesNotMatch(confirmations[1],/並未使用 Ollama 原生/);
 console.log('transport preview + unsaved/stale admission guard PASS');
})().catch(error=>{console.error(error);process.exitCode=1});
