/* No network: prove the saved LLM endpoint, not an unsaved form, is probed. */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const file=process.argv[2]||path.resolve(__dirname,'../../src/han_codebook/static/index.html');
const source=fs.readFileSync(file,'utf8');
const script=file.endsWith('.html')?source.split('<script>')[1].split('</script>')[0]:source;
const begin=script.indexOf("let savedLLMProvider='local';");
const end=script.indexOf('function presentCase(){',begin);
assert(begin>0&&end>begin);
const dom={};
const el=id=>dom[id]||(dom[id]={value:'',checked:false,hidden:false,disabled:false,
 textContent:'',readOnly:false,replaceChildren(){},add(){}});
let persisted={
 provider:'local',base_url:'http://192.168.0.134',endpoint:'http://192.168.0.134',
 model:'test-ollama',timeout_seconds:90,max_output_tokens:8192,
 allow_private_network:true,allow_external_api:false,api_key_env:'',
 confirmation_token:'old-config'
};
let tests=0,settingsReads=0,settingsWrites=0,confirmationText='';
const api=async (route,payload)=>{
 if(route==='/api/settings'){settingsReads++;return {...persisted};}
 if(route==='/api/settings/llm'){
  settingsWrites++;
  persisted={...persisted,...payload,endpoint:payload.base_url,
              confirmation_token:'new-config'};
  return {...persisted};
 }
 if(route==='/api/settings/test'){
  tests++;
  assert.deepEqual(Object.keys(payload),['confirmed']);
  return {connected:true,diagnostics:['[OK] TCP '+persisted.base_url],
          tested_base_url:persisted.base_url,note:'No chat inference'};
 }
 throw Error('unexpected route '+route);
};
const context={
 el,api,URL,confirm:message=>{confirmationText=message;return true;},
 notice:()=>{},Option:class {}
};
vm.createContext(context);
new vm.Script(script.slice(begin,end),{filename:'model-settings.js'}).runInContext(context);
const run=expression=>vm.runInContext(expression,context);
(async()=>{
 await run('loadLLMSettings()');
 // A saved host without a port really means HTTP 80, never secretly 11434.
 await run('testLLMSettings()');
 assert.equal(tests,1);
 assert.match(confirmationText,/TCP Port 80/);
 assert.match(el('llmSettingStatus').textContent,/後端實際測試：http:\/\/192\.168\.0\.134/);
 // Typing :11434 without saving must NOT probe the previous 80 endpoint.
 el('llmPreset').value='ollama';
 el('llmUrl').value='http://192.168.0.134:11434';
 await run('testLLMSettings()');
 assert.equal(tests,1,'unsaved form launched a TCP probe');
 assert.match(el('llmSettingStatus').textContent,/請先按「儲存設定」/);
 // Saving updates the backend receipt; fresh test checks the exact saved port.
 await run('saveLLMSettings()');
 assert.equal(settingsWrites,1);
 assert.equal(persisted.base_url,'http://192.168.0.134:11434');
 await run('testLLMSettings()');
 assert.equal(tests,2);
 assert.match(confirmationText,/TCP Port 11434/);
 assert.match(el('llmSettingStatus').textContent,/後端實際測試：http:\/\/192\.168\.0\.134:11434/);
 // Another tab saving a new endpoint invalidates the local receipt.
 persisted={...persisted,base_url:'http://192.168.0.134:19999',
            confirmation_token:'other-tab-config'};
 await run('testLLMSettings()');
 assert.equal(tests,2,'stale browser tab sent an unexpected connection test');
 assert.match(el('llmSettingStatus').textContent,/後端已儲存的 LLM 設定與目前畫面不同/);
 console.log('LLM saved-vs-unsaved endpoint and TCP port smoke PASS');
})().catch(error=>{console.error(error);process.exitCode=1});
