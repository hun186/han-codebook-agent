'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(process.argv[2],'utf8');
const code=source.split('<script>')[1].split('</script>')[0];
new vm.Script(code);
const grab=(a,b)=>{let i=code.indexOf(a),j=code.indexOf(b,i+a.length);assert(i>=0&&j>i,a);return code.slice(i,j)};
assert(source.includes('id="rounds" type="number" min="0" max="20"'));
assert(source.includes('id="llmUrl"'));
assert(source.includes('id="llmKeyEnv"'));
assert(source.includes('id="boldSet"')&&source.includes('id="boldClear"'));
assert(source.includes('hypo-read.verified-code')&&source.includes('hypo-read.bold-code'));
assert(source.includes('report.docx')&&source.includes('先驗權重'));
const research={messages:[{id:'m1',codes:['101','102']}],
 known_pairs:[{message_id:'m1',segments:['車隊','橋梁']}],
 hypothesis_marks:{},bold_hypotheses:{}};
const dom={},notices=[];let decision=false;
function el(id){return dom[id]||(dom[id]={value:'',textContent:'',innerHTML:'',hidden:true,
 style:{},focus(){},classList:{toggle(){}},querySelectorAll(){return[]}})}
const ctx={el,research,confirm:()=>decision,notice:(v,b)=>notices.push({v,b}),
 esc:x=>String(x),markedCodes:()=>['101','102'],verifiedCodes:()=>new Set(['101','102']),
 verifiedWord:c=>c==='101'?'車隊':'橋梁',loadMark(){},renderIdeas(){},document:{querySelectorAll(){return[]}}};
vm.createContext(ctx);
vm.runInContext(grab('function applyBoldHypothesis(', 'function renderPriorComparison('),ctx);
vm.runInContext(grab('function openMark(', 'function applyBoldHypothesis('),ctx);
el('markCode').value='101';el('markWord').value='指揮官';el('markNote').value='跨電文聯想';
const frozen=JSON.stringify(research.known_pairs);
ctx.applyBoldHypothesis(false);
assert.equal(Object.keys(research.bold_hypotheses).length,0,'confirmation bypassed');
decision=true;
ctx.applyBoldHypothesis(false);
assert.equal(research.bold_hypotheses['101'].term,'指揮官');
assert.equal(research.bold_hypotheses['101'].confirmed,true);
assert.equal(JSON.stringify(research.known_pairs),frozen,'verified source overwritten');
assert.deepEqual(research.hypothesis_marks,{},'verified code silently promoted to ordinary mark');
assert(el('boldList').innerHTML.includes('指揮官'));
ctx.applyBoldHypothesis(true);
assert.equal(Object.keys(research.bold_hypotheses).length,0);
assert.equal(JSON.stringify(research.known_pairs),frozen);
ctx.openMark('101');
assert.equal(el('markCode').value,'101','verified code not selectable for explicit review');
console.log('Bold counterfactual confirmation, reversal, immutable verified data and UI links PASS');
