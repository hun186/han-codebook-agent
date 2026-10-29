"""Explicit-opt-in local bridge: original agent -> loopback -> OpenAI Responses.

This is a *benchmark-only* transport. It does not weaken the production
agent's protection against arbitrary public LLM endpoints. No external call
is made unless the CLI passes --allow-cloud-api and OPENAI_API_KEY is present.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import request, error
from typing import Callable

API_URL="https://api.openai.com/v1/responses"
MODEL="gpt-6-astra"


class BillableResponseRejected(ValueError):
    """Rejected inference with a received upstream usage report.

    Never cache this as a successful answer. Checkpoint caller durably
    records the charged usage before allowing another paid request.
    """
    def __init__(self,reason:str,*,usage:dict,remote_response_id:str|None):
        super().__init__(reason)
        self.usage=usage
        self.remote_response_id=remote_response_id


def _billable_usage(response:dict)->dict:
    raw=response.get("usage")
    if not isinstance(raw,dict):
        raise RuntimeError("API response lacks trustworthy usage; manual spend reconciliation required")
    input_detail=raw.get("input_tokens_details") or {}
    output_detail=raw.get("output_tokens_details") or {}
    if not isinstance(input_detail,dict) or not isinstance(output_detail,dict):
        raise RuntimeError("API usage breakdown invalid; manual spend reconciliation required")
    usage={"prompt_tokens":raw.get("input_tokens"),
           "completion_tokens":raw.get("output_tokens"),
           "cached_input_tokens":input_detail.get("cached_tokens",0),
           "reasoning_tokens":output_detail.get("reasoning_tokens",0),
           "total_tokens":raw.get("total_tokens",0)}
    a,b,c,d=usage["prompt_tokens"],usage["completion_tokens"],usage["cached_input_tokens"],usage["reasoning_tokens"]
    if (any(type(x)is not int or x<0 for x in (a,b,c,d)) or c>a or d>b):
        raise RuntimeError("API usage counters invalid; manual spend reconciliation required")
    return usage


def openai_responses(chat: dict, *, key: str, model: str, effort: str, timeout: int) -> dict:
    """Return a Chat Completions-shaped reply for the unchanged original agent."""
    if not key:raise ValueError("Missing API token")
    if model not in {"gpt-6-astra","gpt-6-sol","gpt-6-luna"}:
        raise ValueError("Explicitly select an audited GPT-6 API model")
    messages=chat.get("messages",[])
    if (not isinstance(messages,list) or len(messages)!=2 or
        [m.get("role") for m in messages]!=["system","user"]):
        raise ValueError("Unexpected local agent chat packet shape")
    body={
        "model":model,
        "store":False,
        "reasoning":{"effort":effort},
        "max_output_tokens":16384,
        "text":{"format":{"type":"json_object"}},
        "input":[{"role":m["role"],"content":str(m["content"])} for m in messages]
    }
    data=json.dumps(body,ensure_ascii=False).encode("utf-8")
    req=request.Request(API_URL,data=data,method="POST",headers={
        "Content-Type":"application/json",
        "Authorization":"Bearer "+key,
    })
    with request.urlopen(req,timeout=timeout) as resp:
        raw=resp.read(1_500_000)
    response=json.loads(raw)
    # A rejected response may still be billed: validate usage BEFORE
    # checking completion/final JSON. Always hand it to the durable ledger.
    usage=_billable_usage(response)
    remote_id=response.get("id")
    actual=response.get("model","")
    if response.get("status")!="completed":
        raise BillableResponseRejected("Responses API returned a non-completed response",
                                       usage=usage,remote_response_id=remote_id)
    if actual!=model and not str(actual).startswith(model+"-"):
        raise BillableResponseRejected("API returned another model, cannot score as requested GPT-6 variant",
                                       usage=usage,remote_response_id=remote_id)
    parts=[]
    for item in response.get("output",[]):
        if item.get("type")=="message":
            for part in item.get("content",[]):
                if part.get("type")=="output_text": parts.append(part.get("text",""))
    result="".join(parts).strip()
    if not result:
        raise BillableResponseRejected("Responses API returned no final output_text",
                                       usage=usage,remote_response_id=remote_id)
    # Explicit JSON parsing prevents accepting malformed inference as success.
    try:
        parsed=json.loads(result)
    except (TypeError,ValueError) as exc:
        raise BillableResponseRejected("Responses API final output was not JSON",
                                       usage=usage,remote_response_id=remote_id) from exc
    if not isinstance(parsed,dict):
        raise BillableResponseRejected("Expected JSON object from GPT-6",
                                       usage=usage,remote_response_id=remote_id)
    return {"choices":[{"message":{"role":"assistant","content":result}}],
            "model":actual,
            "usage":usage,
            "remote_response_id":response.get("id")}


class LoopbackGateway:
    def __init__(self,*,provider:Callable[[dict],dict]):
        self.provider=provider
        self.token=secrets.token_urlsafe(32)
        gateway=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                if self.path!="/v1/chat/completions":
                    self.send_error(404);return
                if (self.client_address[0] not in ("127.0.0.1","::1") or
                    self.headers.get("Authorization")!="Bearer "+gateway.token):
                    self.send_error(403);return
                try:
                    size=int(self.headers.get("Content-Length","0"))
                    if size<=0 or size>1_500_000:raise ValueError("Invalid request size")
                    body=json.loads(self.rfile.read(size))
                    data=gateway.provider(body)
                    encoded=json.dumps(data,ensure_ascii=False).encode("utf-8")
                    status=200
                except Exception as exc:
                    # Do not expose API-key-bearing upstream exceptions.
                    gateway.errors.append(type(exc).__name__+": "+str(exc)[:150])
                    encoded=json.dumps({"error":"Provider failed; see benchmark stderr"}).encode()
                    status=502
                try:
                    self.send_response(status)
                    self.send_header("Content-Type","application/json; charset=utf-8")
                    self.send_header("Content-Length",str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                except (BrokenPipeError, ConnectionResetError):
                    # The agent may have timed out while its provider was still
                    # running. The reply/cache has already been persisted; do
                    # not emit a misleading extra server traceback on disconnect.
                    pass
        self.server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        # Provider() can outlive a caller's socket timeout. All request threads
        # MUST exit before run_experiment releases its cross-process lock.
        self.server.daemon_threads=False
        self.server.block_on_close=True
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.errors:list[str]=[]
        self.calls:list[dict]=[]
    def __enter__(self):
        self.previous_token=os.environ.get("HAN_BLIND_LOOPBACK_TOKEN")
        os.environ["HAN_BLIND_LOOPBACK_TOKEN"]=self.token
        self.thread.start()
        return self
    def __exit__(self,*_):
        try:
            self.server.shutdown()
            # ThreadingMixIn.server_close blocks for all non-daemon request
            # threads, including a paid provider still executing after timeout.
            # Do not use a bounded join: the study lock must remain held.
            self.server.server_close()
            self.thread.join()
        finally:
            if self.previous_token is None:
                os.environ.pop("HAN_BLIND_LOOPBACK_TOKEN",None)
            else:
                os.environ["HAN_BLIND_LOOPBACK_TOKEN"]=self.previous_token
    @property
    def url(self)->str:
        return f"http://127.0.0.1:{self.server.server_port}"


def create_openai_gateway(*,model:str=MODEL,effort:str="high",timeout:int=240):
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set; public GPT-6 API evaluation cannot run")
    key=os.environ["OPENAI_API_KEY"]
    if effort not in ("low","medium","high","xhigh","max"):
        raise ValueError("Unsupported reasoning effort")
    def send(chat):
        result=openai_responses(chat,key=key,model=model,effort=effort,timeout=timeout)
        return result
    return LoopbackGateway(provider=send)
