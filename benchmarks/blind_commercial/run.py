"""Execute the ORIGINAL adaptive han_codebook.agent with real GPT-6 calls.

This runner NEVER opens gold/reference files. Evaluation uses score.py later,
only after the whole inference JSON is locked. No cloud calls in CI or by
default; requires the explicit --allow-cloud-api and OPENAI_API_KEY.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"src"))
from han_codebook.agent import run_agent
from han_codebook.core import validate_case
from gpt_gateway import LoopbackGateway,openai_responses

SIZES=(10,25,50,100)


def json_sha(obj:object)->str:
    return hashlib.sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False,
                                    separators=(",",":")).encode("utf-8")).hexdigest()


def run_experiment(public_dir: Path,out_dir: Path,*,model:str,effort:str,rounds:int,
                   max_calls:int,timeout:int,provider,conditions=("with_aux","without_aux")) -> dict:
    public_dir=public_dir.resolve();out_dir=out_dir.resolve()
    if public_dir==out_dir or out_dir in public_dir.parents or public_dir in out_dir.parents:
        raise ValueError("Public input and result directories must be separate")
    if out_dir.exists() and list(out_dir.iterdir()):
        raise FileExistsError("Result output must be empty to prevent accidental overwrites")
    out_dir.mkdir(parents=True,exist_ok=True)
    manifests=json.loads((public_dir/"manifest.json").read_text(encoding="utf-8"))
    if manifests.get("protocol")!="blind-phrase-v1":
        raise ValueError("Unsupported blind manifest")
    if manifests.get("sizes")!=list(SIZES):raise ValueError("Must run fixed comparable sizes 10/25/50/100")
    if any(x.get("fixture_only") for x in manifests["studies"]) and provider is openai_responses:
        raise ValueError("Do not run a known-seed insecure fixture as a real GPT-6 blind study")
    n_runs=len(manifests["studies"])*len(SIZES)*len(conditions)
    expected_calls=n_runs*rounds*2
    if expected_calls>max_calls:
        raise ValueError(f"Expected {expected_calls} GPT API calls exceeds --max-calls {max_calls}")
    counter={"calls":0,"prompt_tokens":0,"completion_tokens":0}
    def counted_provider(packet):
        if counter["calls"]>=max_calls:
            raise RuntimeError("API call budget exhausted")
        counter["calls"]+=1
        answer=provider(packet)
        if not isinstance(answer,dict) or "choices" not in answer:
            raise RuntimeError("LLM provider did not return a real/valid Chat Completions response")
        usage=answer.get("usage",{})
        counter["prompt_tokens"]+=usage.get("prompt_tokens",0)
        counter["completion_tokens"]+=usage.get("completion_tokens",0)
        return answer
    experiments=[]
    with LoopbackGateway(provider=counted_provider) as gateway:
        for case in manifests["studies"]:
            sample=json.loads((public_dir/case["public_file"]).read_text(encoding="utf-8"))
            validate_case(sample)
            if json_sha(sample)!=case["public_sha256"]:
                raise ValueError("Public message digest mismatch; stop, no scoring")
            if len(sample["messages"])!=100 or sample.get("known_pairs"):
                raise ValueError("Blind corpus must contain 100 messages without anchors")
            for n in SIZES:
                for condition in conditions:
                    metadata=(condition=="with_aux")
                    current=dict(sample)
                    current["messages"]=sample["messages"][:n]
                    ref=f"{case['case_id']}_{n}_{condition}"
                    audit=out_dir/(ref+".sqlite")
                    print(f"[BLIND] {ref}: GPT API × {rounds*2} requests; autonomous review OFF",flush=True)
                    started=time.monotonic()
                    result=run_agent(current,rounds=rounds,model=model,llm_url=gateway.url,
                         db_path=str(audit),metadata=metadata,llm_timeout=timeout,
                         adaptive_vocabulary=True,vocabulary_reviewer=None,
                         capture_llm_io=True,solver_iterations=8,solver_restarts=4)
                    if result["agent_rounds_completed"]!=rounds:
                        raise RuntimeError("Actual completed rounds differ from requested")
                    if not result.get("adaptive_vocabulary") or result.get("human_vocabulary_review"):
                        raise RuntimeError("Not fully automatic dynamic vocabulary execution")
                    if any(p.get("status")=="verified_alignment" for p in result["proposals"].values()):
                        raise RuntimeError("Found unexpected verified plaintext in blind no-anchor case")
                    out={"study":case["case_id"],"n_messages":n,"condition":condition,
                         "public_sha256":case["public_sha256"],
                         "model":model,"reasoning_effort":effort,"rounds":rounds,
                         "seconds":round(time.monotonic()-started,2),
                         "mapping":{c:p["term"] for c,p in result["proposals"].items()},
                         "alternatives":{c:[a["term"] for a in p.get("alternatives",[])]
                                         for c,p in result["proposals"].items()},
                         "dynamic_vocabulary_terms":result.get("dynamic_vocabulary_terms",[]),
                         "audit_sqlite":audit.name,
                         "code_types":len(result["proposals"])}
                    experiments.append(out)
                    # Append-only checkpoint; never a scored artifact.
                    with (out_dir/"inference_progress.jsonl").open("a",encoding="utf-8") as f:
                        f.write(json.dumps(out,ensure_ascii=False,sort_keys=True)+"\n")
        if gateway.errors:
            raise RuntimeError(f"Loopback model transport failure: {len(gateway.errors)}")
    if counter["calls"]!=expected_calls:
        raise RuntimeError(f"Expected {expected_calls} actual model requests, saw {counter['calls']}")
    lock={"kind":"ACTUAL_MULTI_ROUND_BLIND_EVALUATION", "model":model,
          "reasoning_effort":effort, "n_rounds":rounds,
          "n_model_calls":counter["calls"],"usage":counter,
          "includes_hidden_reference":False,
          "n_experiments":len(experiments),"cases":experiments}
    final=out_dir/"predictions_LOCKED.json"
    final.write_text(json.dumps(lock,indent=2,sort_keys=True,ensure_ascii=False),encoding="utf-8")
    sha=hashlib.sha256(final.read_bytes()).hexdigest()
    (out_dir/"predictions_LOCKED.sha256").write_text(sha+"\n",encoding="ascii")
    print(f"[LOCKED] model={model}; calls={counter['calls']}; cases={len(experiments)}; SHA256={sha}",flush=True)
    return lock


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-dir",type=Path,required=True)
    parser.add_argument("--out-dir",type=Path,required=True)
    parser.add_argument("--model",default="gpt-6-astra",
                        choices=("gpt-6-astra","gpt-6-sol","gpt-6-luna"))
    parser.add_argument("--effort",default="high",
                        choices=("low","medium","high","xhigh","max"))
    parser.add_argument("--rounds",type=int,default=5)
    parser.add_argument("--max-calls",type=int,default=240)
    parser.add_argument("--timeout",type=int,default=240)
    parser.add_argument("--allow-cloud-api",action="store_true")
    args=parser.parse_args()
    if not args.allow_cloud_api:
        parser.error("External model calls require explicit --allow-cloud-api")
    if not os.environ.get("OPENAI_API_KEY"):
        parser.error("Set OPENAI_API_KEY as an environment variable; never commit it")
    if not 1<=args.rounds<=20:
        parser.error("--rounds must be 1..20")
    def provider(packet):
        return openai_responses(packet,key=os.environ["OPENAI_API_KEY"],
                               model=args.model,effort=args.effort,timeout=args.timeout)
    run_experiment(args.public_dir,args.out_dir,model=args.model,effort=args.effort,
                   rounds=args.rounds,max_calls=args.max_calls,timeout=args.timeout,
                   provider=provider)


if __name__=="__main__":
    main()
