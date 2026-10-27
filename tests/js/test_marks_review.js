'use strict';
const assert=require('assert');
const fs=require('fs');
const vm=require('vm');
const html=fs.readFileSync(process.argv[2],'utf8');
const script=html.split('<script>')[1].split('</script>')[0];
const grab=(a,b)=>{let i=script.indexOf(a),j=script.indexOf(b);assert(i>=0&&j>i,'function not found '+a);return script.slice(i,j)};
const elData={knownEdit:{value:''}};
const research={messages:[{id:'a',codes:['001','002']}],known_pairs:[],hypothesis_marks:{'001':{preferred:'甲',pinned:true,excluded:[],note:'trial'}}};
const notices=[];
const ctx={research,el:(id)=>elData[id]||(elData[id]={}),notice:(s,b)=>notices.push({s,b}),initializeMarks:()=>{},
  Blob,markSnapshots:[{'001':{preferred:'甲',pinned:true,excluded:[],note:'trial'}},{}],markActions:['original','cleared'],markCursor:1,copyMarks:(x)=>JSON.parse(JSON.stringify(x))};
vm.createContext(ctx);
vm.runInContext(grab('function persistMarkHistory()', 'function initializeMarks()'),ctx);
vm.runInContext(grab('function applyKnown()', 'function saveProfile()'),ctx);
elData.knownEdit.value=JSON.stringify([{message_id:'a',segments:['已知甲','已知乙']}]);
ctx.applyKnown();
assert.deepStrictEqual(research.known_pairs,[],'conflicting known plaintext partly applied');
assert.strictEqual(notices.at(-1).b,true,'collision not reported');
assert(research.hypothesis_marks['001'],'existing mark removed unexpectedly');
delete research.hypothesis_marks['001'];
ctx.applyKnown();
assert.strictEqual(research.known_pairs.length,1,'non-conflicting known pair did not apply');
assert.strictEqual(notices.at(-1).b,undefined,'successful edit reported as error');
assert(ctx.markSnapshots.every(snapshot=>!('001' in snapshot)), 'old marks for newly verified code resurrect through undo');
const snapshots=[];
const words=Array.from({length:60},(_,i)=>String(i).padStart(3,'0'));
for(let step=0;step<80;step++){
  const mark={};
  words.slice(0,Math.min(60,step+1)).forEach(code=>mark[code]={preferred:'長文字',excluded:[],pinned:false,note:'文'.repeat(500)});
  snapshots.push(mark);
}
ctx.markSnapshots=snapshots;
ctx.markActions=snapshots.map((_,i)=>'history '+i);
ctx.markCursor=snapshots.length-1;
const initialLength=snapshots.length;
ctx.persistMarkHistory();
const size=new Blob([JSON.stringify(research)]).size;
assert(size<=1000000,'saved research history exceeds byte budget: '+size);
assert(ctx.markSnapshots.length < initialLength,'oversized history not pruned');
assert(ctx.markSnapshots[ctx.markCursor]['059'],'current state was not preserved');
assert(ctx.markActions.length===ctx.markSnapshots.length,'history labels are misaligned');
// Reproduce review case: large current annotations plus exactly one snapshot.
// Both are independently legal but their duplication can exceed the 1.5 MB API cap.
const big={};
for(let i=0;i<500;i++)big[String(i).padStart(4,'0')]={preferred:'長文字',excluded:[],pinned:false,note:'文'.repeat(500)};
research.hypothesis_marks=JSON.parse(JSON.stringify(big));
ctx.markSnapshots=[JSON.parse(JSON.stringify(big))];
ctx.markActions=['only'];ctx.markCursor=0;
ctx.persistMarkHistory();
assert.strictEqual(ctx.markSnapshots.length,1,'in-memory current snapshot should survive');
assert.strictEqual(ctx.markCursor,0,'cursor for in-memory snapshot should survive');
assert.strictEqual('hypothesis_revision_history' in research,false,'duplicate oversized sole snapshot persisted');
assert(new Blob([JSON.stringify(research)]).size<1500000,'large valid case still exceeds Web API limit');
assert(research.hypothesis_marks['0499'].note.length===500,'current researcher annotations discarded');
console.log('Reversible hypothesis UI regression PASS; size='+size+', retained='+ctx.markSnapshots.length);
