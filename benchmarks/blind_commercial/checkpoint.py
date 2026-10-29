"""Crash-consistent checkpoints for the original 2-call-per-round Agent.

Every successful model response is written atomically BEFORE it is returned
to the local gateway. On resumption, the original Agent is reexecuted from
the start of an incomplete experiment using IDENTICAL cached responses and
a clean SQLite audit. Completed experiments are reused without reinference.

Cache writes and checkpoints are NOT scored evidence; the final lock remains
absent until all requested studies/conditions/rounds actually finish.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime,timezone
from pathlib import Path


def digest(obj:object)->str:
    return hashlib.sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False,
        separators=(",",":")).encode("utf-8")).hexdigest()


def _sync_directory(path:Path)->None:
    """Persist rename/create directory entries on POSIX after file fsync.

    Windows does not expose a portable directory-fsync through os.open; the
    same-filesystem atomic replace remains in effect there. If POSIX fsync
    fails, fail closed rather than falsely acknowledging a durable reply.
    """
    if os.name!="posix":
        return
    fd=os.open(str(path),os.O_RDONLY|getattr(os,"O_DIRECTORY",0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def durable_mkdir(path:Path)->None:
    """Sync each newly created directory's entry in its parent directory."""
    path=Path(path)
    missing=[]
    cur=path
    while not cur.exists():
        missing.append(cur)
        if cur.parent==cur:
            raise OSError("Cannot find existing parent for checkpoint directory")
        cur=cur.parent
    path.mkdir(parents=True,exist_ok=True)
    for created in reversed(missing):
        _sync_directory(created.parent)


def atomic_text(path:Path,content:str)->None:
    """Durable same-directory atomic replacement, with parent-dir fsync."""
    durable_mkdir(path.parent)
    fd,name=tempfile.mkstemp(dir=path.parent,prefix=".checkpoint-",suffix=".tmp")
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.replace(name,path)
        _sync_directory(path.parent)
    finally:
        if os.path.exists(name):os.unlink(name)


def atomic_json(path:Path,content:dict)->None:
    atomic_text(path,json.dumps(content,sort_keys=True,ensure_ascii=False,indent=2))


class ResumeStore:
    VERSION=1
    def __init__(self,root:Path,*,signature:dict,resume:bool):
        self.root=root.resolve()
        self.status=self.root/"run_status.json"
        self.requests=self.root/"successful_requests"
        self.completed=self.root/"completed_runs"
        self.signature=signature
        if resume:
            if not self.status.is_file():
                raise RuntimeError("Cannot resume: missing run_status.json")
            old=json.loads(self.status.read_text(encoding="utf-8"))
            if old.get("signature")!=signature:
                raise ValueError("Resume settings, corpus hashes or model differ; no reuse permitted")
            if old.get("state")=="completed":
                raise RuntimeError("Benchmark is already locked; do not resume a completed run")
            if old.get("state") not in ("paused_quota","failed","running"):
                raise ValueError("Unknown run checkpoint state")
        else:
            if self.root.exists() and list(self.root.iterdir()):
                raise FileExistsError("Output directory exists and is not empty; use --resume")
            durable_mkdir(self.root)
            self._write_status("running",reason="new experiment")
        durable_mkdir(self.requests)
        durable_mkdir(self.completed)
        if resume:
            self._write_status("running",reason="resumed by explicit user command")
        self.cache_hits=0
        self.real_new_calls=0

    def _write_status(self,state:str,**details)->None:
        prior={}
        if self.status.exists():
            prior=json.loads(self.status.read_text(encoding="utf-8"))
        info={
           "version":self.VERSION,"state":state,"signature":self.signature,
           "created_utc":prior.get("created_utc") or datetime.now(timezone.utc).isoformat(),
           "updated_utc":datetime.now(timezone.utc).isoformat(),
           "completed_run_count":len(list(self.completed.glob("*.json"))) if self.completed.exists() else 0,
           "cached_successful_calls":len(list(self.requests.glob("*.json"))) if self.requests.exists() else 0,
           **details,
        }
        atomic_json(self.status,info)

    def mark(self,state:str,*,reason:str="",current:str="")->None:
        if state not in ("running","paused_quota","failed","completed"):
            raise ValueError("Invalid checkpoint state")
        self._write_status(state,reason=reason,current=current)

    def invoke(self,chat:dict,*,provider,model:str,effort:str,provider_name:str,
               logical_id:str)->dict:
        """Cache by stable run/round/phase, never deduplicate two real model turns."""
        if not isinstance(logical_id,str) or not logical_id or len(logical_id)>256:
            raise ValueError("Each model call requires a stable logical identity")
        key=digest({"version":self.VERSION,"chat":chat,"model":model,
                    "effort":effort,"provider":provider_name,"logical_id":logical_id})
        path=self.requests/(key+".json")
        if path.exists():
            item=json.loads(path.read_text(encoding="utf-8"))
            if (item.get("request_key")!=key or
                item.get("response_digest")!=digest(item.get("reply"))):
                raise RuntimeError("Saved model response fingerprint corrupted; refusing replay")
            result=item["reply"]
            if not isinstance(result,dict) or "choices" not in result:
                raise ValueError("Corrupt saved response")
            self.cache_hits+=1
            return result
        answer=provider(chat)
        if not isinstance(answer,dict) or "choices" not in answer:
            raise RuntimeError("Provider response invalid; will not checkpoint")
        atomic_json(path,{"request_key":key,"response_digest":digest(answer),"reply":answer})
        self.real_new_calls+=1
        return answer

    def stored_replies(self)->list[dict]:
        """Verify each saved reply's filename/digests before using it for money."""
        records=[]
        for path in sorted(self.requests.glob("*.json")):
            record=json.loads(path.read_text(encoding="utf-8"))
            if (record.get("request_key")!=path.stem or
                record.get("response_digest")!=digest(record.get("reply")) or
                not isinstance(record.get("reply"),dict) or
                "choices" not in record["reply"]):
                raise RuntimeError("Saved model reply corrupted; refuse spend or scoring")
            records.append(record)
        return records

    def finished_run(self,ref:str,expected:dict|None=None)->dict|None:
        path=self.completed/(ref+".json")
        if not path.exists():return None
        info=json.loads(path.read_text(encoding="utf-8"))
        if info.get("checksum")!=digest(info.get("result")):
            raise ValueError(f"Completed checkpoint {ref} corrupted")
        run=info["result"]
        if run.get("checkpoint_id")!=ref:
            raise ValueError("Mismatched completed checkpoint reference")
        if expected and any(run.get(k)!=v for k,v in expected.items()):
            raise ValueError("Completed run settings/corpus differ; cannot reuse")
        audit=self.root/run["audit_sqlite"]
        if (audit.parent.resolve()!=self.root or
            not audit.is_file() or
            hashlib.sha256(audit.read_bytes()).hexdigest()!=run["audit_sha256"]):
            raise ValueError(f"Completed run audit modified: {ref}")
        return run

    def record_run(self,ref:str,run:dict)->None:
        if not ref.replace("_","").isalnum() or ref.startswith("."):
            raise ValueError("Invalid run ID")
        path=self.completed/(ref+".json")
        if path.exists():raise FileExistsError("Refusing to overwrite completed run")
        entry={"result":run,"checksum":digest(run)}
        atomic_json(path,entry)
        self._write_status("running",reason="completed a full experiment",current=ref)
