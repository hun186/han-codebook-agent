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
from codex_subscription import codex_subscription_reply,check_codex_subscription
from checkpoint import ResumeStore, atomic_json, atomic_text

SIZES=(10,25,50,100)


def json_sha(obj:object)->str:
    return hashlib.sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False,
                                    separators=(",",":")).encode("utf-8")).hexdigest()


def estimated_standard_usd(usage:dict)->float:
    """Official GPT-6 Standard rates; estimate, not an invoice or preflight cap."""
    ins=usage.get("prompt_tokens",0)
    cached=usage.get("cached_input_tokens",0)
    outs=usage.get("completion_tokens",0)
    reason=usage.get("reasoning_tokens",0)
    if any(type(x) is not int or x<0 for x in (ins,cached,outs,reason)) or cached>ins or reason>outs:
        raise RuntimeError("Invalid historical API usage counters")
    mul=2 if ins>272000 else 1
    return ((ins-cached)*10*mul+cached*1*mul+
            outs*50*(1.5 if ins>272000 else 1))/1_000_000


def run_experiment(public_dir: Path,out_dir: Path,*,model:str,effort:str,rounds:int,
                   max_calls:int,timeout:int,provider,conditions=("with_aux","without_aux"),
                   real_api:bool=False,solver_iterations:int=8,solver_restarts:int=4,
                   max_estimated_usd:float=100.0,
                   provider_name:str|None=None,resume:bool=False) -> dict:
    public_dir=public_dir.resolve();out_dir=out_dir.resolve()
    if public_dir==out_dir or out_dir in public_dir.parents or public_dir in out_dir.parents:
        raise ValueError("Public input and result directories must be separate")
    manifests=json.loads((public_dir/"manifest.json").read_text(encoding="utf-8"))
    if manifests.get("protocol")!="blind-phrase-v1":
        raise ValueError("Unsupported blind manifest")
    if manifests.get("sizes")!=list(SIZES):raise ValueError("Must run fixed comparable sizes 10/25/50/100")
    if real_api and any(x.get("fixture_only") for x in manifests["studies"]):
        raise ValueError("Do not run a known-seed insecure fixture as a real GPT-6 blind study")
    n_runs=len(manifests["studies"])*len(SIZES)*len(conditions)
    expected_calls=n_runs*rounds*2
    if expected_calls>max_calls:
        raise ValueError(f"Expected {expected_calls} GPT API calls exceeds --max-calls {max_calls}")
    if max_estimated_usd<=0:raise ValueError("--max-estimated-usd must be positive")
    provider_name=provider_name or ("OPENAI_RESPONSES" if real_api else "TEST_DOUBLE")
    if provider_name not in {"OPENAI_RESPONSES","CODEX_CLI_CHATGPT_PLAN","TEST_DOUBLE"}:
        raise ValueError("Unsupported inference provider")
    if real_api!=(provider_name!="TEST_DOUBLE"):
        raise ValueError("A test double cannot be scored as a real model provider")
    signature={
        "protocol":"subscription-blind-resume-v1",
        "manifest_sha256":hashlib.sha256((public_dir/"manifest.json").read_bytes()).hexdigest(),
        "public_sha256":{x["case_id"]:x["public_sha256"] for x in manifests["studies"]},
        "provider":provider_name,"model":model,"effort":effort,"rounds":rounds,
        "solver_iterations":solver_iterations,"solver_restarts":solver_restarts,
        "conditions":list(conditions),"max_calls":max_calls,
        "max_estimated_usd":max_estimated_usd,
    }
    checkpoints=ResumeStore(out_dir,signature=signature,resume=resume)
    # Reconstruct whole-study charges BEFORE another paid external request.
    historical=checkpoints.stored_replies()
    prior_spend=sum(estimated_standard_usd(r["reply"].get("usage",{}))
                    for r in historical) if provider_name=="OPENAI_RESPONSES" else 0.0
    if prior_spend>max_estimated_usd:
        raise RuntimeError("Previously incurred API usage exceeds experiment cost cap")
    counter={"calls":0,"prompt_tokens":0,"cached_input_tokens":0,
             "completion_tokens":0,"reasoning_tokens":0,"estimated_usd":prior_spend}
    model_ids={}
    request_scope={"cell":None,"index":0}
    def counted_provider(packet):
        if counter["calls"]>=max_calls:
            raise RuntimeError("API call budget exhausted")
        if request_scope["cell"] is None:
            raise RuntimeError("LLM request outside registered evaluation cell")
        i=request_scope["index"]
        request_scope["index"]+=1
        phase="vocabulary" if i%2==0 else "hypotheses"
        packet_task=json.loads(packet["messages"][1]["content"]).get("task")
        if (phase=="vocabulary")!=(packet_task=="generate_vocabulary"):
            raise RuntimeError("Unexpected LLM phase sequence; cannot safely replay")
        logical_id=f'{request_scope["cell"]}:round_{i//2+1}:{phase}'
        prior_new=checkpoints.real_new_calls
        answer=checkpoints.invoke(packet,provider=provider,model=model,effort=effort,
                                  provider_name=provider_name,logical_id=logical_id)
        is_new=checkpoints.real_new_calls>prior_new
        counter["calls"]+=1
        if not isinstance(answer,dict) or "choices" not in answer:
            raise RuntimeError("LLM provider did not return a real/valid Chat Completions response")
        usage=answer.get("usage",{})
        ins=usage.get("prompt_tokens",0)
        cached=usage.get("cached_input_tokens",0)
        outs=usage.get("completion_tokens",0)
        reason=usage.get("reasoning_tokens",0)
        if any(type(x) is not int or x<0 for x in (ins,cached,outs,reason)) or cached>ins or reason>outs:
            raise RuntimeError("Invalid usage counters, cannot price this API call")
        if real_api and not (ins>0 and outs>0 and answer.get("model")):
            raise RuntimeError("Actual GPT API response missing model ID or billable token counts")
        actual=str(answer.get("model") or "TEST_DOUBLE")
        model_ids[actual]=model_ids.get(actual,0)+1
        counter["prompt_tokens"]+=ins
        counter["cached_input_tokens"]+=cached
        counter["completion_tokens"]+=outs
        counter["reasoning_tokens"]+=reason
        if provider_name=="OPENAI_RESPONSES":
            # A replay of an already-paid request does not charge again.
            if is_new:
                counter["estimated_usd"]+=estimated_standard_usd(usage)
            if counter["estimated_usd"]>max_estimated_usd:
                raise RuntimeError("Whole-study estimated API spend exceeded cap; "
                                   "all valid responses have been checkpointed")
        # ChatGPT-plan Codex CLI has a usage allowance, not API-token billing.
        return answer
    experiments=[]
    with LoopbackGateway(provider=counted_provider) as gateway:
        for case in manifests["studies"]:
            sample=json.loads((public_dir/case["public_file"]).read_text(encoding="utf-8"))
            validate_case(sample)
            if sample.get("kind")!="BLIND_UNSTRUCTURED_CODEBOOK_V1":
                raise ValueError("Only synthetic blind benchmark inputs are allowed")
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
                    expected={"checkpoint_id":ref,"study":case["case_id"],
                              "n_messages":n,"condition":condition,
                              "public_sha256":case["public_sha256"],
                              "model":model,"reasoning_effort":effort,"rounds":rounds}
                    prior=checkpoints.finished_run(ref,expected)
                    if prior is not None:
                        experiments.append(prior)
                        print(f"[RESUME] {ref} already completed and audit verified",flush=True)
                        # Restored logical call counts are recomputed from the
                        # saved model-request cache instead of charging again.
                        # Replay below loads per-request usage for final totals.
                        continue
                    # A failed/incomplete run's sqlite contains partial events.
                    # Safely replay from its start using cached real model replies.
                    # Never continue appending partial audit events.
                    for stale in [audit,Path(str(audit)+"-wal"),Path(str(audit)+"-shm")]:
                        if stale.exists():stale.unlink()
                    checkpoints.mark("running",current=ref,reason="run active")
                    request_scope.update(cell=ref,index=0)
                    print(f"[BLIND] {ref}: {provider_name} x {rounds*2} logical turns; automatic mode",flush=True)
                    started=time.monotonic()
                    try:
                        result=run_agent(current,rounds=rounds,model=model,llm_url=gateway.url,
                             db_path=str(audit),metadata=metadata,llm_timeout=timeout,
                             adaptive_vocabulary=True,vocabulary_reviewer=None,
                             llm_api_key_env="HAN_BLIND_LOOPBACK_TOKEN",
                             capture_llm_io=True,solver_iterations=solver_iterations,
                             solver_restarts=solver_restarts)
                    except Exception as exc:
                        diagnosis=gateway.errors[-1] if gateway.errors else type(exc).__name__
                        if diagnosis.startswith("QuotaExhausted:"):
                            checkpoints.mark("paused_quota",current=ref,
                                reason="subscription usage allowance exhausted; resume explicitly after reset")
                            raise RuntimeError(
                                f"[PAUSED_QUOTA] {ref}: progress saved, no final accuracy or Word; "
                                "retry the IDENTICAL command with --resume after quota resets") from None
                        checkpoints.mark("failed",current=ref,
                            reason="inference interruption (not a validated result)")
                        # Never print Authorization values or the original prompt.
                        raise RuntimeError(f"Inference failed at {ref}: {diagnosis}") from exc
                    if request_scope["index"]!=rounds*2:
                        raise RuntimeError("Unexpected number of original Agent LLM phases")
                    request_scope["cell"]=None
                    if result["agent_rounds_completed"]!=rounds:
                        raise RuntimeError("Actual completed rounds differ from requested")
                    if not result.get("adaptive_vocabulary") or result.get("human_vocabulary_review"):
                        raise RuntimeError("Not fully automatic dynamic vocabulary execution")
                    if any(p.get("status")=="verified_alignment" for p in result["proposals"].values()):
                        raise RuntimeError("Found unexpected verified plaintext in blind no-anchor case")
                    # run_agent has closed its audit connection; hash exact DB
                    # bytes before this prediction is locked and before gold is read.
                    audit_hash=hashlib.sha256(audit.read_bytes()).hexdigest()
                    out={"checkpoint_id":ref,"study":case["case_id"],"n_messages":n,"condition":condition,
                         "public_sha256":case["public_sha256"],
                         "model":model,"reasoning_effort":effort,"rounds":rounds,
                         "seconds":round(time.monotonic()-started,2),
                         "mapping":{c:p["term"] for c,p in result["proposals"].items()},
                         "alternatives":{c:[a["term"] for a in p.get("alternatives",[])]
                                         for c,p in result["proposals"].items()},
                         "dynamic_vocabulary_terms":result.get("dynamic_vocabulary_terms",[]),
                         "audit_sqlite":audit.name,"audit_sha256":audit_hash,
                         "code_types":len(result["proposals"])}
                    checkpoints.record_run(ref,out)
                    experiments.append(out)
                    # Append-only history, not a scored artifact.
                    with (out_dir/"inference_progress.jsonl").open("a",encoding="utf-8") as f:
                        f.write(json.dumps(out,ensure_ascii=False,sort_keys=True)+"\n")
        if gateway.errors:
            raise RuntimeError(f"Loopback model transport failure: {len(gateway.errors)}")
    if len(experiments)!=n_runs:
        raise RuntimeError(f"Only {len(experiments)}/{n_runs} runs completed; refuse final lock")
    # Restarted runs can be skipped in full. Reconstruct usage/IDs from
    # the frozen request cache, not just calls replayed this invocation.
    persisted=checkpoints.stored_replies()
    if len(persisted)!=expected_calls:
        raise RuntimeError(f"Expected {expected_calls} distinct persisted model requests; "
                           f"found {len(persisted)}; refuse completed benchmark")
    counter={k:0 if k!="estimated_usd" else 0.0 for k in counter}
    model_ids={}
    for record in persisted:
        response=record["reply"]
        u=response.get("usage",{})
        counter["calls"]+=1
        for field,target in (("prompt_tokens","prompt_tokens"),("cached_input_tokens","cached_input_tokens"),
                             ("completion_tokens","completion_tokens"),("reasoning_tokens","reasoning_tokens")):
            counter[target]+=u.get(field,0)
        actual=str(response.get("model") or "TEST_DOUBLE")
        model_ids[actual]=model_ids.get(actual,0)+1
        if provider_name=="OPENAI_RESPONSES":
            counter["estimated_usd"]+=estimated_standard_usd(u)
    counter["estimated_usd"]=round(counter["estimated_usd"],6)
    lock={"kind":"ACTUAL_MULTI_ROUND_BLIND_EVALUATION" if real_api else "TEST_DOUBLE_SMOKE_NOT_SCORED",
          "provider":provider_name, "model":model,
          "reasoning_effort":effort, "n_rounds":rounds,
          "n_model_calls":counter["calls"],"usage":counter,
          "reported_api_model_ids":model_ids,
          "cost_notice":("API Standard token price estimate, not confirmed invoice"
                         if provider_name=="OPENAI_RESPONSES" else
                         "ChatGPT-plan Codex allowance; no additional API-token bill; quota applies"),
          "configured_max_estimated_usd":max_estimated_usd,
          "includes_hidden_reference":False,
          "n_experiments":len(experiments),"cases":experiments,
          "resume_evidence":{"saved_model_replies":len(persisted),
                             "new_successful_calls_this_invocation":checkpoints.real_new_calls,
                             "cached_replies_replayed_this_invocation":checkpoints.cache_hits,
                             "completed_runs":len(experiments)}}
    final=out_dir/"predictions_LOCKED.json"
    sha_file=out_dir/"predictions_LOCKED.sha256"
    if final.exists():
        # Crash may occur after durable prediction lock but before the SHA or
        # completed status. Only resume when ALL immutable experiment fields
        # still exactly match the validated finished runs/reply cache. Session
        # progress counters are deliberately excluded from this comparison.
        locked=json.loads(final.read_text(encoding="utf-8"))
        def stable(d):
            return {k:v for k,v in d.items() if k!="resume_evidence"}
        if stable(locked)!=stable(lock):
            raise ValueError("Existing prediction lock differs from audited checkpoints")
        lock=locked
    else:
        if sha_file.exists():
            raise ValueError("Orphan prediction SHA without lock; refuse overwriting")
        atomic_json(final,lock)
    sha=hashlib.sha256(final.read_bytes()).hexdigest()
    if sha_file.exists():
        if sha_file.read_text(encoding="ascii").strip()!=sha:
            raise ValueError("Prediction SHA differs from immutable lock; refuse repair")
    else:
        atomic_text(sha_file,sha+"\n")
    checkpoints.mark("completed",reason="all required experiments locked")
    print(f"[LOCKED] model={model}; logical_calls={counter['calls']}; "
          f"new_in_session={checkpoints.real_new_calls}; cases={len(experiments)}; SHA256={sha}",flush=True)
    return lock


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-dir",type=Path,required=True)
    parser.add_argument("--out-dir",type=Path,required=True)
    parser.add_argument("--model",default="gpt-6-astra",
                        choices=("gpt-6-astra","gpt-6-sol","gpt-6-luna","gpt-5.6-sol"))
    parser.add_argument("--effort",default="high",
                        choices=("low","medium","high","xhigh","max"))
    parser.add_argument("--rounds",type=int,default=5)
    parser.add_argument("--max-calls",type=int,default=240)
    parser.add_argument("--max-estimated-usd",type=float,default=100.0,
                        help="Abort before further calls after estimated Standard token charges exceed this cap")
    parser.add_argument("--timeout",type=int,default=600)
    parser.add_argument("--provider",choices=["openai-api","codex-subscription"],
                        default="openai-api")
    parser.add_argument("--allow-subscription-usage",action="store_true",
                        help="Explicit consent to consume the locally logged-in ChatGPT Codex allowance")
    parser.add_argument("--codex-bin",default="codex")
    parser.add_argument("--resume",action="store_true",
                        help="Resume a prior paused/failed run using saved successful model responses")
    parser.add_argument("--allow-cloud-api",action="store_true")
    args=parser.parse_args()
    if args.provider=="openai-api" and args.model=="gpt-5.6-sol":
        parser.error("This benchmark's billed API gateway currently supports only GPT-6; "
                     "use --provider codex-subscription for GPT-5.6 Sol")
    if args.provider=="codex-subscription" and args.model not in ("gpt-6-astra","gpt-5.6-sol"):
        parser.error("Subscription benchmark supports --model gpt-6-astra or gpt-5.6-sol")
    if args.provider=="openai-api":
        if not args.allow_cloud_api:
            parser.error("Paid API requires --allow-cloud-api")
        if not os.environ.get("OPENAI_API_KEY"):
            parser.error("Set OPENAI_API_KEY to use the separately billed API")
    else:
        if not args.allow_subscription_usage:
            parser.error("Codex subscription requires --allow-subscription-usage")
        check_codex_subscription(args.codex_bin)
    if not 1<=args.rounds<=20:
        parser.error("--rounds must be 1..20")
    if args.provider=="openai-api":
        def provider(packet):
            return openai_responses(packet,key=os.environ["OPENAI_API_KEY"],
                                   model=args.model,effort=args.effort,timeout=args.timeout)
        provider_name="OPENAI_RESPONSES"
    else:
        def provider(packet):
            return codex_subscription_reply(packet,model=args.model,effort=args.effort,
                                            timeout=max(30,args.timeout-10),
                                            codex_bin=args.codex_bin)
        provider_name="CODEX_CLI_CHATGPT_PLAN"
    run_experiment(args.public_dir,args.out_dir,model=args.model,effort=args.effort,
                   rounds=args.rounds,max_calls=args.max_calls,timeout=args.timeout,
                   provider=provider,real_api=True,provider_name=provider_name,
                   max_estimated_usd=args.max_estimated_usd,resume=args.resume)


if __name__=="__main__":
    main()
