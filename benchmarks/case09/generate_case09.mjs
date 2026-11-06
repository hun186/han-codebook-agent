import fs from "node:fs";
import path from "node:path";
class PyRandom {
  constructor(seed){this.mt=new Uint32Array(624);this.i=624;this.init(19650218);const key=[];let n=BigInt(seed);do{key.push(Number(n&0xffffffffn));n>>=32n}while(n>0);let x=1,y=0;for(let z=Math.max(624,key.length);z>0;z--){const t=this.mt[x-1]^(this.mt[x-1]>>>30);this.mt[x]=((this.mt[x]^Math.imul(t,1664525))+key[y]+y)>>>0;x++;y++;if(x>=624){this.mt[0]=this.mt[623];x=1}if(y>=key.length)y=0}for(let z=623;z>0;z--){const t=this.mt[x-1]^(this.mt[x-1]>>>30);this.mt[x]=((this.mt[x]^Math.imul(t,1566083941))-x)>>>0;x++;if(x>=624){this.mt[0]=this.mt[623];x=1}}this.mt[0]=0x80000000;}
  init(seed){this.mt[0]=seed>>>0;for(let i=1;i<624;i++){const t=this.mt[i-1]^(this.mt[i-1]>>>30);this.mt[i]=(Math.imul(t,1812433253)+i)>>>0}}
  u32(){if(this.i>=624){for(let k=0;k<624;k++){const v=(this.mt[k]&0x80000000)|(this.mt[(k+1)%624]&0x7fffffff);this.mt[k]=this.mt[(k+397)%624]^(v>>>1)^((v&1)?0x9908b0df:0)}this.i=0}let y=this.mt[this.i++];y^=y>>>11;y^=(y<<7)&0x9d2c5680;y^=(y<<15)&0xefc60000;y^=y>>>18;return y>>>0}
  random(){return ((this.u32()>>>5)*67108864+(this.u32()>>>6))/9007199254740992}
  bits(k){return this.u32()>>>(32-k)}
  below(n){const k=Math.floor(Math.log2(n))+1;let r;do{r=this.bits(k)}while(r>=n);return r}
  choice(a){return a[this.below(a.length)]}
  sample(size,count){let p=Array.from({length:size},(_,i)=>i),r=[];for(let i=0;i<count;i++){const j=this.below(size-i);r.push(p[j]);p[j]=p[size-i-1]}return r}
  weighted(keys,w){const total=w.reduce((a,b)=>a+b,0),v=this.random()*total;let sum=0;for(let i=0;i<keys.length;i++){sum+=w[i];if(v<sum)return keys[i]}return keys[keys.length-1]}
  uniform(a,b){return a+(b-a)*this.random()}
}
function buildCase09(S){
 const files={},sizes=[25,100,400,1000],TOTAL=1000,probes=80;
 const allTerms=new Set(S.P);
 for(const k of Object.keys(S.H))for(const w of S.H[k])allTerms.add(w);
 for(const row of S.E)for(const w of row)allTerms.add(w);
 for(const scene of Object.values(S.S))for(const rows of Object.values(scene))for(const row of rows)for(const w of row)allTerms.add(w);
 const words=[...allTerms].sort((a,b)=>a<b?-1:a>b?1:0);
 const rng=new PyRandom(20261106);
 const codepool=rng.sample(900,words.length).map(n=>String(n+100).padStart(3,'0'));
 const encode=Object.fromEntries(words.map((w,i)=>[w,codepool[i]])),decode=Object.fromEntries(words.map(w=>[encode[w],w]));
 const messages=[],hidden=[];
 const start=Date.UTC(2018,8,1,5,0);
 const isoTime=t=>new Date(t).toISOString().slice(0,16);
 const isoDate=t=>new Date(t).toISOString().slice(0,10);
 const select=a=>rng.choice(a);
 for(let i=0;i<TOTAL+probes;i++){
  const phase=i<TOTAL?Math.min(3,Math.floor(i*4/TOTAL)):3;
  const weights=S.W[phase],keys=Object.keys(weights),scene=rng.weighted(keys,keys.map(k=>weights[k]));
  const cl=['clauses','actions','outcome'].map(k=>select(S.S[scene][k]));
  if(rng.random()<.08){const options=Object.keys(S.S).filter(k=>k!==scene);cl[2]=select(S.S[select(options)].outcome)}
  const h=Object.keys(S.H).map(k=>select(S.H[k]));
  if(h[2]===h[3]&&rng.random()<.8)h[3]=h[2]==='中央站'?'甲站':'中央站';
  const terms=[...h,...cl[0],...cl[1],...cl[2],...select(S.E)];
  if(terms.length!==24)throw Error('unexpected group count');
  const date=start+Math.floor(i*30*24*60/TOTAL)*60000;
  const m={id:i<TOTAL?`INT${String(i+1).padStart(5,'0')}`:`PROBE${String(i-TOTAL+1).padStart(4,'0')}`,received_at:isoTime(date),sender:`CH-${String(h[2].codePointAt(0)%19).padStart(2,'0')}`,recipient:`CH-${String(h[3].codePointAt(0)%19).padStart(2,'0')}`,notes:select(['一般收訊','有雜訊','有重播疑慮','訊號偏弱','錄音完整','時間戳可能有誤']),codes:terms.map(t=>encode[t])};
  if(i<TOTAL&&rng.random()<.16){const obskey=rng.random()>.2?scene:select(Object.keys(S.S)),[src,note]=S.C[obskey];const day=Math.floor(i*30/TOTAL),obsday=day+select([-2,-1,0,0,0,1,2]);m.observations=[{source:src,observed_at:isoDate(start+obsday*86400000),activity:'公開資訊摘要',destination:'資料未能定位',status:'未確認',confidence:Math.round(rng.uniform(.28,.8)*100)/100,note}]}
  messages.push(m);hidden.push({message_id:m.id,story_arc:scene,source_words:terms});
 }
 const profiles={general:{keywords:['居民','公告','通報'],lexicon:Object.fromEntries(S.P.slice(0,10).map(w=>[w,2])),sentences:[]},transport:{keywords:['物流','交通','橋'],lexicon:Object.fromEntries(S.P.slice(10,20).map(w=>[w,2])),sentences:[]},medical:{keywords:['醫療','衛生','門診'],lexicon:Object.fromEntries(S.P.slice(20).map(w=>[w,2])),sentences:[]}};
 const counter=new Map();for(const m of messages.slice(0,25))for(const c of m.codes)counter.set(c,(counter.get(c)||0)+1);
 const guessed=[...counter.entries()].sort((a,b)=>b[1]-a[1]).slice(0,30).map(v=>v[0]).filter(c=>!S.V.includes(decode[c]));
 const guesses={};for(let i=0;i<Math.min(12,guessed.length);i++){const c=guessed[i],right=decode[c];let guess=[0,4,7].includes(i)?right:select([...S.P,...S.D]);if(guess===right&&![0,4,7].includes(i))guess='港口封鎖';guesses[c]=[{term:guess,source:'researcher',status:'suggested',note:'探索性假說；尚無可靠逐碼證據，可能因事件聯想而錯誤。'}]}
 const suite=[],stats=[];
 const add=(path,value)=>{files[path]=JSON.stringify(value,null,2)+'\n'};
 for(const n of sizes)for(const mode of ['cold','sparse']){
  const base=messages.slice(0,n);
  const encountered=new Set(base.flatMap(m=>m.codes));
  const candidate_ideas=Object.fromEntries(Object.entries(guesses).filter(([k])=>encountered.has(k)));
  const c={codebook_assumptions:{distinct_phrases:true},description:'合成救援網路，大量電文、固定但未公開碼本、稀少可靠對照；Gold 已分離。',observation_policy:'time_relevance',profiles,messages:[...base],candidate_ideas,case_id:`09_valley_${String(n).padStart(4,'0')}_${mode}`,known_pairs:[]};
  if(mode==='sparse')for(let j=0;j<S.V.length;j++){const id=`REF-${String(j+1).padStart(2,'0')}`;c.messages.push({id,codes:[encode[S.V[j]]],sender:'ARCHIVE',recipient:'ANALYST',notes:'獨立可靠單碼參考條目；非24碼截獲電文'});c.known_pairs.push({message_id:id,segments:[S.V[j]]})}
  const filename=`${c.case_id}.json`;
  add('benchmarks/cases/'+filename,c);
  const used=new Set(c.messages.flatMap(m=>m.codes));
  const gold={case_id:c.case_id,codebook:Object.fromEntries([...used].sort().map(code=>[code,decode[code]])),messages:Object.fromEntries(c.messages.map(m=>[m.id,m.codes.map(code=>decode[code]).join('')]))};
  add('benchmarks/gold/'+filename,gold);
  suite.push({id:c.case_id,case:'cases/'+filename,gold:'gold/'+filename,description:`Fictional progressive corpus, n=${n}, ${mode}; 24-group intercepted messages`});
  stats.push({case_id:c.case_id,intercepted_messages:n,reference_fragments:c.known_pairs.length,intercepted_groups:n*24,unique_codes:encountered.size,speculative_code_hypotheses:Object.keys(candidate_ideas).length,external_observations:base.filter(m=>m.observations).length});
 }
 add('benchmarks/suite_case09.json',{version:1,cases:suite});
 add('benchmarks/case09/corpus_stats.json',{seed:20261106,three_digit:true,stats});
 // Keep the 80 held-out probes and oracle physically separated from solver inputs.
 add('benchmarks/case09/gold/oracle_and_probe_eval_only.json',{case_id:'09_valley_oracle',codebook:decode,probe_messages:messages.slice(TOTAL),verified_terms:S.V});
 return {files,counts:{terms:words.length,uniqueCodesIn1000:new Set(messages.slice(0,TOTAL).flatMap(m=>m.codes)).size,probeCount:probes,stats},codepool};
}
const spec = JSON.parse(fs.readFileSync(new URL("./spec.json", import.meta.url), "utf8"));
const result = buildCase09(spec);
const root = path.resolve(process.argv[2] || "benchmarks");
for (const [name, data] of Object.entries(result.files)) {
  if (!name.startsWith("benchmarks/")) continue;
  const target = path.join(root, name.slice("benchmarks/".length));
  fs.mkdirSync(path.dirname(target), {recursive:true});
  fs.writeFileSync(target, data, "utf8");
}
console.log(JSON.stringify(result.counts, null, 2));
