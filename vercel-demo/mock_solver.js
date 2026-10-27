/* Deterministic, explainable demonstration re-ranking. Never reads evaluation gold. */
'use strict';
(function(root) {
  const clean = x => Array.from(new Set(x.filter(s => typeof s === 'string' && s.length > 0)));
  const pairKey = (a,b) => JSON.stringify([a,b]);
  function evidence(record) {
    const adjacency = {}, transitions = {}, freq = {};
    const add = (a,b,weight) => {
      const key = pairKey(a,b);
      transitions[key] = (transitions[key]||0) + weight;
      freq[a] = (freq[a]||0) + weight;
    };
    for(const m of record.messages) {
      for(let i=0;i+1<m.codes.length;i++) {
        const a=m.codes[i], b=m.codes[i+1];
        if(a===b)continue;
        (adjacency[a]??={})[b] = (adjacency[a][b]||0)+1;
        (adjacency[b]??={})[a] = (adjacency[b][a]||0)+1;
        // Candidate word sequences are a rough *unverified* lexical prior, not truth.
        for(const source of [record.statistical,record.mock]) {
          const x=source[a]?.term, y=source[b]?.term;
          if(x&&y){add(x,y,.5);add(y,x,.5);}
        }
      }
    }
    function affinity(a,b) {
      const n=transitions[pairKey(a,b)]||0;
      const d=Math.max(1,Math.sqrt((freq[a]||0)*(freq[b]||0)));
      return Math.min(1,n/d);
    }
    return {adjacency,affinity};
  }
  function solve(record,marks={}) {
    const original=record.mock;
    const selected={};const explanations={};
    const {adjacency,affinity}=evidence(record);
    const codeList=Object.keys(original).sort();
    const options={};const baseline={};
    for(const code of codeList) {
      const old=original[code].term;baseline[code]=old;
      const stat=record.statistical[code]||{};
      options[code]=clean([old,...(original[code].alternatives||[]),stat.term,...(stat.alternatives||[])]).slice(0,12);
      const mark=marks[code]||{};
      if(mark.preferred&&!options[code].includes(mark.preferred))options[code].push(mark.preferred);
      if(mark.pinned&&!options[code].includes(mark.pinned))options[code].push(mark.pinned);
      const excluded=new Set(mark.excluded||[]);
      const allowed=options[code].filter(word=>!excluded.has(word));
      if(!allowed.length) { // impossible constraints should not produce fabricated certainty.
        selected[code]='？';explanations[code]='排除全部候選，無法推測';continue;
      }
      if(mark.pinned) {
        if(excluded.has(mark.pinned)) {selected[code]='？';explanations[code]='試鎖與排除互相矛盾';}
        else {selected[code]=mark.pinned;explanations[code]='研究員試鎖；僅為可撤回假說';}
      } else if(mark.preferred&&!excluded.has(mark.preferred)) {
        // A preference raises a candidate's score; unlike a trial pin it may lose.
        const preferredScore=(word)=>3.5 - Math.max(0,options[code].indexOf(word))*.60 + (word===mark.preferred?3.2:0);
        selected[code]=[...allowed].sort((a,b)=>preferredScore(b)-preferredScore(a)||a.localeCompare(b,'zh-Hant'))[0];
        explanations[code]=selected[code]===mark.preferred?'研究員偏好加權後成為第一候選；尚未驗證':'研究員偏好已加權，但不足以改變第一候選';
      } else {
        selected[code]=allowed[0];explanations[code]=excluded.has(old)?'研究員排除原候選，改採下一個合法候選':'維持預先計算的 Mock 候選';
      }
    }
    const changedMarks = codeList.filter(code=>selected[code]!==baseline[code] && marks[code]);
    // Only code pairs adjacent in the *observed ciphertext* can transmit hints.
    // No marks means no change at all; all numbers arise from the same deterministic input.
    for(let sweep=0;sweep<2;sweep++) {
      const next={...selected};
      for(const code of codeList) {
        if(marks[code]?.pinned||marks[code]?.preferred)continue;
        const allowed=options[code].filter(word=>!(marks[code]?.excluded||[]).includes(word));
        if(!allowed.length)continue;
        const neighbors=adjacency[code]||{};
        const neighborhoodTotal=Object.values(neighbors).reduce((sum,n)=>sum+n,0)||1;
        function score(word) {
          const pos=options[code].indexOf(word);
          let s = 3.5 - Math.max(0,pos)*.60;
          for(const markedCode of changedMarks) {
            const n=neighbors[markedCode]||0;
            if(!n)continue;
            const old=baseline[markedCode], now=selected[markedCode];
            const support = affinity(word,now)-affinity(word,old);
            s += 13*(n/neighborhoodTotal)*support;
          }
          return s;
        }
        const ordered=allowed.map(word=>({word,value:score(word)}))
          .sort((a,b)=>b.value-a.value || a.word.localeCompare(b.word,'zh-Hant'));
        next[code]=ordered[0].word;
        if(next[code]!==baseline[code]) {
          const parents=changedMarks.filter(m=>(neighbors[m]||0)>0);
          explanations[code]=parents.length?`因碼組 ${parents.slice(0,3).join('、')} 的研究員標註，依相鄰頻率及未驗證詞序先驗重新評分`:'候選重新排序';
        }
      }
      if(codeList.every(c=>next[c]===selected[c]))break;
      Object.assign(selected,next);
    }
    const mapping={};const changed=[];
    for(const code of codeList) {
      const newTerm=selected[code];
      const alternatives=clean([newTerm,...options[code]]).filter(w=>w!=='？');
      mapping[code]={term:newTerm,alternatives:alternatives.slice(0,5),reason:explanations[code]};
      if(newTerm!==baseline[code])changed.push({code,before:baseline[code],after:newTerm,reason:explanations[code],marked:!!marks[code]});
    }
    return {mapping,changed,affected:changed.filter(x=>!x.marked),marked:changed.filter(x=>x.marked),method:'cipher-adjacency-and-unverified-candidate-transition-heuristic'};
  }
  root.MockFeedback=Object.freeze({solve});
})(typeof window!=='undefined'?window:globalThis);
