'use strict';
const fs=require('fs');const path=require('path');const vm=require('vm');const assert=require('assert');
const root=path.resolve(__dirname,'../../vercel-demo');
class E {
  constructor(tag='div'){this.tagName=tag;this.children=[];this.dataset={};this.handlers={};this.className='';this._text='';this.value='';this.style={};this.disabled=false;this.attributes={};this.files=[];
    this.classList={toggle:(name,force)=>{const current=new Set(this.className.split(/\s+/).filter(Boolean));if(force===undefined? !current.has(name):force)current.add(name);else current.delete(name);this.className=[...current].join(' ');}};}
  set textContent(x){this._text=String(x);this.children=[];}
  get textContent(){return this._text+this.children.map(x=>x.textContent||'').join('');}
  append(...xs){this.children.push(...xs);}replaceChildren(...xs){this.children=[...xs];this._text='';}
  addEventListener(type,fn){this.handlers[type]=fn;}setAttribute(k,v){this.attributes[k]=String(v);}click(){if(this.onclick)this.onclick();if(this.handlers.click)this.handlers.click();}
}
(async()=>{
 const ids='status feedbackSummary volume revealGold runMock exportMarks importMarks importFile messageSearch messageList messageTitle messageMeta cipherChips statChips mockChips manualChips goldChips goldPanel goldScore codeDetails markCode markTerm markNote undo redo resetMarks markStatus markList runSummary runProgress timeline countMessages countCodes statRate mockRate trend'.split(' ');
 const map=Object.fromEntries(ids.map(id=>[id,new E('div')]));map.volume.value='100';
 const btns=['prefer','exclude','pin','clear'].map(v=>{let x=new E('button');x.dataset.mark=v;return x;});
 let fetched=[];
 const context={
   document:{getElementById:id=>map[id],createElement:tag=>new E(tag),createElementNS:(ns,tag)=>new E(tag),createTextNode:s=>({textContent:s}),querySelectorAll:selector=>selector==='[data-mark]'?btns:[]},
   fetch:async url=>{fetched.push(url);return {ok:true,json:async()=>JSON.parse(fs.readFileSync(path.join(root,url.replace(/^\//,'')),'utf8'))}},
   setTimeout:cb=>Promise.resolve().then(cb),Blob:class {constructor(items){this.parts=items}},
   URL:{createObjectURL:()=>'',revokeObjectURL:()=>{}}, FileReader:class {},console,
 };
 vm.createContext(context);vm.runInContext(fs.readFileSync(path.join(root,'mock_solver.js'),'utf8'),context);vm.runInContext(fs.readFileSync(path.join(root,'app.js'),'utf8'),context);
 await new Promise(r=>setTimeout(r,35));
 assert.match(map.status.textContent,/100 封/);
 assert.equal(map.messageList.children.length,100);
 assert.equal(map.mockChips.children[0].children[0].textContent,'待模擬');
 assert.deepEqual(fetched,['/data/demo.json']); // Gold must not load at boot.
 await vm.runInContext('runMock()',context);
 assert.equal(map.timeline.children.length,4);
 assert.equal(vm.runInContext('state.feedback.changed.length',context),0); // no marks, exact precomputed baseline
 assert.ok(map.mockChips.children[0].children[0].textContent!=='待模擬');
 await vm.runInContext('toggleGold()',context);
 assert.ok(fetched.includes('/data/gold.json'));
 assert.ok(!map.goldPanel.className.includes('hidden'));
 vm.runInContext('selectCode("135")',context);
 const original135=vm.runInContext('state.feedback.mapping["135"].term',context);
 map.markTerm.value='車隊';
 vm.runInContext('applyMark("pin")',context);
 assert.equal(vm.runInContext('state.marks["135"].pinned',context),'車隊');
 assert.equal(vm.runInContext('state.feedback.mapping["135"].term',context),'車隊');
 assert.notEqual(original135,'車隊');
 assert.ok(vm.runInContext('state.feedback.affected.length',context)>=1,'cipher adjacency should influence at least one other code');
 assert.match(map.feedbackSummary.textContent,/相較原始 Mock 改變/);
 vm.runInContext('historyMove(-1)',context);
 assert.equal(vm.runInContext('state.marks["135"]',context),undefined);
 assert.equal(vm.runInContext('state.feedback.changed.length',context),0,'undo restores exact pre-mark mock mapping');
 vm.runInContext('historyMove(1)',context);
 assert.equal(vm.runInContext('state.marks["135"].pinned',context),'車隊');
 assert.equal(vm.runInContext('state.feedback.mapping["135"].term',context),'車隊');
 assert.notEqual(original135,'車隊');
 assert.ok(vm.runInContext('state.feedback.affected.length',context)>=1,'cipher adjacency should influence at least one other code');
 assert.match(map.feedbackSummary.textContent,/相較原始 Mock 改變/);
 vm.runInContext('setSize(25)',context);
 assert.equal(map.messageList.children.length,25);
 assert.equal(map.timeline.children.length,0);
 console.log('Vercel mock UI Node VM smoke: PASS (mock rerank, linked-code changes, exclude, undo/redo, gold isolation, sample switch)');
})().catch(e=>{console.error(e);process.exit(1)});
