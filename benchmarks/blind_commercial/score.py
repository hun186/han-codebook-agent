"""Offline-only score: open private answers strictly after predictions are locked.

This file must never be imported into runner, gateway or original agent.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import sqlite3
from pathlib import Path

def digest(data:object)->str:
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False,
                                    separators=(",",":")).encode("utf-8")).hexdigest()

def score_case(public:dict,gold:dict,run:dict)->dict:
    if digest(public)!=gold["public_sha256"] or run["public_sha256"]!=gold["public_sha256"]:
        raise ValueError("Mismatched public corpus / sealed gold hash")
    n=run["n_messages"]
    messages=public["messages"][:n]
    truth=gold["code_to_word"]
    freq=collections.Counter(c for m in messages for c in m["codes"])
    mapping=run["mapping"]
    if set(mapping)!=set(freq):
        raise ValueError("Predictions must match exactly the codes observed in the scoped subset")
    accurate={c for c in freq if truth[c]==mapping[c]}
    vocab=set(public["profiles"]["neutral"]["lexicon"])
    vocab.update(run.get("dynamic_vocabulary_terms",[]))
    top5=run.get("alternatives",{})
    alt_hits=sum(truth[c] in top5.get(c,[]) for c in freq)
    complete=sum(all(mapping[c]==truth[c] for c in m["codes"]) for m in messages)
    return {
      "study":run["study"],"n_messages":n,"metadata":run["condition"]=="with_aux",
      "rounds":run["rounds"],"code_types":len(freq),
      "correct_types":len(accurate),"type_top1":round(len(accurate)/len(freq),5),
      "top5_correct_types":alt_hits,"type_top5":round(alt_hits/len(freq),5),
      "positions":sum(freq.values()),"correct_positions":sum(freq[c] for c in accurate),
      "position_accuracy":round(sum(freq[c] for c in accurate)/sum(freq.values()),5),
      "complete_messages":complete,"complete_rate":round(complete/n,5),
      "lexicon_coverage":round(sum(truth[c] in vocab for c in freq)/len(freq),5),
      "unresolved":sum(mapping[c] in ("[未解]","") for c in freq),
      "model":run["model"],"reasoning_effort":run["reasoning_effort"],
      "seconds":run["seconds"],"no_verified_anchors":True
    }

def score_round_trace(public:dict,gold:dict,run:dict,results_dir:Path)->list[dict]:
    """Evaluate baseline, post-vocabulary and post-hypothesis snapshots AFTER lock."""
    messages=public["messages"][:run["n_messages"]]
    freq=collections.Counter(c for m in messages for c in m["codes"])
    truth=gold["code_to_word"]
    path=results_dir/run["audit_sqlite"]
    if path.parent.resolve()!=results_dir.resolve():
        raise ValueError("Audit path escapes the locked results directory")
    trace=[]
    with sqlite3.connect(path) as db:
        events=db.execute("SELECT round,stage,payload_json FROM events WHERE stage IN "
             "('statistical_baseline','vocabulary_rescore','rescore') ORDER BY id").fetchall()
    for round_number,stage,packed in events:
        packet=json.loads(packed)
        mapping=packet.get("mapping")
        if not mapping:
            # The baseline is optional when the new vocabulary bootstraps
            # from scratch; no score is claimed for missing assignments.
            continue
        if set(mapping)!=set(freq):
            raise ValueError("Audit mapping/code coverage differs from scoped public ciphertext")
        hit={c for c in freq if mapping[c]==truth[c]}
        trace.append({
          "study":run["study"],"n_messages":run["n_messages"],
          "condition":run["condition"],"round":round_number,"stage":stage,
          "code_types":len(freq),"correct_types":len(hit),
          "type_top1":round(len(hit)/len(freq),5),
          "positions":sum(freq.values()),
          "correct_positions":sum(freq[c] for c in hit),
          "position_accuracy":round(sum(freq[c] for c in hit)/sum(freq.values()),5),
          "complete_messages":sum(all(mapping[c]==truth[c] for c in m["codes"]) for m in messages),
        })
    if len([x for x in trace if x["stage"]=="rescore"])!=run["rounds"]:
        raise ValueError("Audit does not contain one post-hypothesis rescore per LLM round")
    final=next(x for x in reversed(trace) if x["stage"]=="rescore")
    if final["correct_types"]!=sum(run["mapping"][c]==truth[c] for c in freq):
        raise ValueError("Audit final mapping differs from locked predictions")
    return trace


def score(private_dir:Path,public_dir:Path,results_dir:Path)->dict:
    locked=results_dir/"predictions_LOCKED.json"
    sha=(results_dir/"predictions_LOCKED.sha256").read_text(encoding="ascii").strip()
    if hashlib.sha256(locked.read_bytes()).hexdigest()!=sha:
        raise ValueError("Predictions lock fingerprint mismatch; refuse scoring")
    src=json.loads(locked.read_text(encoding="utf-8"))
    if src.get("kind")!="ACTUAL_MULTI_ROUND_BLIND_EVALUATION" or src.get("includes_hidden_reference") is not False:
        raise ValueError("Not a finished and unscored real LLM inference lock")
    if src.get("n_model_calls",0)!=src["n_experiments"]*src["n_rounds"]*2:
        raise ValueError("Not all real model calls were completed")
    cache={}
    measures=[]
    all_rounds=[]
    for item in src["cases"]:
        study=item["study"]
        if study not in cache:
            pub=json.loads((public_dir/(study+".json")).read_text(encoding="utf-8"))
            gold=json.loads((private_dir/(study+".gold.json")).read_text(encoding="utf-8"))
            cache[study]=(pub,gold)
        measures.append(score_case(*cache[study],item))
        all_rounds.extend(score_round_trace(*cache[study],item,results_dir))
    # Publish scoring only to the PRIVATE evaluation folder, never the
    # browser demo, Vercel or model prompt path.
    evaluated={"locked_sha256":sha,"model":src["model"],"total_runs":len(measures),
               "results":measures,"round_trajectories":all_rounds,
               "warning":"Real API results only if run.py was executed with explicit cloud opt-in; never score a mock as GPT-6"}
    out=results_dir/"evaluation.json"
    if out.exists():raise FileExistsError("Refuse overwriting published evaluation")
    out.write_text(json.dumps(evaluated,ensure_ascii=False,indent=2),encoding="utf-8")
    with (results_dir/"evaluation.csv").open("x",encoding="utf-8-sig",newline="") as fh:
        fields=list(measures[0])
        writer=csv.DictWriter(fh,fieldnames=fields)
        writer.writeheader()
        writer.writerows(measures)
    with (results_dir/"round_trajectories.csv").open("x",encoding="utf-8-sig",newline="") as fh:
        fields=list(all_rounds[0])
        writer=csv.DictWriter(fh,fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_rounds)
    return evaluated

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--private-dir",type=Path,required=True)
    ap.add_argument("--public-dir",type=Path,required=True)
    ap.add_argument("--results-dir",type=Path,required=True)
    args=ap.parse_args()
    r=score(args.private_dir,args.public_dir,args.results_dir)
    print(json.dumps({"locked_sha256":r["locked_sha256"],
                      "total_runs":r["total_runs"],"note":"Scored only after completed lock"},
                     ensure_ascii=False))

if __name__=="__main__":main()
