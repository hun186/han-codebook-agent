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
    if response.get("status")!="completed":
        raise ValueError("Responses API returned a non-completed response")
    actual=response.get("model","")
    if actual!=model and not str(actual).startswith(model+"-"):
        raise ValueError("API returned another model, cannot score as requested GPT-6 variant")
    parts=[]
    for item in response.get("output",[]):
        if item.get("type")=="message":
            for part in item.get("content",[]):
                if part.get("type")=="output_text": parts.append(part.get("text",""))
    result="".join(parts).strip()
    if not result:
        raise ValueError("Responses API returned no final output_text")
    # Explicit JSON parsing prevents accepting malformed inference as success.
    parsed=json.loads(result)
    if not isinstance(parsed,dict):raise ValueError("Expected JSON object from GPT-6")
    usage=response.get("usage",{})
    return {"choices":[{"message":{"role":"assistant","content":result}}],
            "model":actual,
            "usage":{"prompt_tokens":usage.get("input_tokens",0),
                     "completion_tokens":usage.get("output_tokens",0),
                     "cached_input_tokens":usage.get("input_tokens_details",{}).get("cached_tokens",0),
                     "reasoning_tokens":usage.get("output_tokens_details",{}).get("reasoning_tokens",0),
                     "total_tokens":usage.get("total_tokens",0)},
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
