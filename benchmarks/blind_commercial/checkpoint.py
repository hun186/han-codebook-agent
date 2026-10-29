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
import contextlib
import json
import os
import tempfile
import threading
import re
import secrets
import subprocess
from gpt_gateway import BillableResponseRejected
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



@contextlib.contextmanager
def exclusive_run_lock(root: Path):
    """Cross-process, OS-owned nonblocking study lock (Windows + POSIX).

    The lock file is never unlinked: unlinking a live inode could permit
    another process to acquire a different lock on the same directory.
    Kernel locks are released on close, including abnormal process exit.
    """
    root=Path(root).resolve()
    durable_mkdir(root)
    fd=os.open(str(root/".run.lock"),os.O_CREAT|os.O_RDWR,0o600)
    locked=False
    try:
        try:
            if os.name=="nt":
                import msvcrt
                if os.fstat(fd).st_size==0:
                    os.write(fd,bytes([0]))
                    os.fsync(fd)
                os.lseek(fd,0,os.SEEK_SET)
                msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
            elif os.name=="posix":
                import fcntl
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            else:
                raise RuntimeError("No supported kernel file lock on this OS")
            locked=True
        except (OSError,BlockingIOError) as exc:
            raise RuntimeError("Study output directory is locked by another process; no checkpoint or model call was attempted") from exc
        yield
    finally:
        try:
            if locked:
                if os.name=="nt":
                    import msvcrt
                    os.lseek(fd,0,os.SEEK_SET)
                    msvcrt.locking(fd,msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(fd,fcntl.LOCK_UN)
        finally:
            os.close(fd)



DOCKER_INFLIGHT="codex_container_inflight.json"


def reconcile_stale_codex_container(root:Path,*,subprocess_run=subprocess.run)->None:
    """After SIGKILL, force-remove a durable container name under the study lock.

    Unknown daemon state, corrupted evidence or unverified inspect result
    quarantines the checkpoint. Never infer cleanup from docker start --attach.
    """
    marker=Path(root)/DOCKER_INFLIGHT
    if not marker.exists():return
    try:
        data=json.loads(marker.read_text(encoding="utf-8"))
        name=data.get("name")
        if (not isinstance(name,str) or
            re.fullmatch(r"han-blind-[0-9a-f]{32}",name) is None or
            data.get("version")!=1):
            raise ValueError("Malformed durable Docker in-flight marker")
        removed=subprocess_run(["docker","rm","--force",name],
                               capture_output=True,text=True,timeout=40,check=False)
        inspected=subprocess_run(["docker","inspect","--type","container",name],
                                 capture_output=True,text=True,timeout=20,check=False)
        missing=(inspected.returncode!=0 and
                 any(q in inspected.stderr.lower()
                     for q in ("no such object","no such container")))
        accepted_remove=(removed.returncode==0 or
                         (removed.returncode!=0 and
                          "no such" in removed.stderr.lower()))
        if not missing or not accepted_remove:
            raise RuntimeError("Docker termination not verifiable")
        marker.unlink()
        _sync_directory(marker.parent)
    except BaseException as exc:
        raise RuntimeError(
            "Unsafe resume: unverified_container_cleanup; Docker in-flight marker retained for operator action"
        ) from exc


class ResumeStore:
    VERSION=1
    def __init__(self,root:Path,*,signature:dict,resume:bool):
        self.root=root.resolve()
        # Gateway provider handlers and the runner can report failures from
        # different threads. Serialize status read/update/atomic replace.
        self._status_lock=threading.RLock()
        self.status=self.root/"run_status.json"
        self.requests=self.root/"successful_requests"
        self.completed=self.root/"completed_runs"
        self.failed_requests=self.root/"rejected_billable_requests"
        self.signature=signature
        if resume:
            if not self.status.is_file():
                raise RuntimeError("Cannot resume: missing run_status.json")
            old=json.loads(self.status.read_text(encoding="utf-8"))
            if old.get("signature")!=signature:
                raise ValueError("Resume settings, corpus hashes or model differ; no reuse permitted")
            if str(old.get("reason","")).startswith(("unverified_container_cleanup","unverified_api_spend")):
                raise RuntimeError("Unsafe resume: previous paid inference/cleanup unverified; checkpoint quarantined")
            # This check precedes any new model request AND the resumed status.
            # In-flight markers are fsynced before Docker CREATE/START.
            try:
                reconcile_stale_codex_container(self.root)
            except RuntimeError:
                self._write_status("failed",reason="unverified_container_cleanup: stale Docker state cannot be verified")
                raise
            if old.get("state")=="completed":
                raise RuntimeError("Benchmark is already locked; do not resume a completed run")
            if old.get("state") not in ("paused_quota","failed","running"):
                raise ValueError("Unknown run checkpoint state")
        else:
            if self.root.exists() and any(p.name!='.run.lock' for p in self.root.iterdir()):
                raise FileExistsError("Output directory exists and is not empty; use --resume")
            durable_mkdir(self.root)
            self._write_status("running",reason="new experiment")
        durable_mkdir(self.requests)
        durable_mkdir(self.completed)
        durable_mkdir(self.failed_requests)
        if resume:
            self._write_status("running",reason="resumed by explicit user command")
        self.cache_hits=0
        self.real_new_calls=0

    def _write_status(self,state:str,**details)->None:
        with self._status_lock:
            return self._write_status_locked(state,**details)

    def _write_status_locked(self,state:str,**details)->None:
        prior={}
        if self.status.exists():
            prior=json.loads(self.status.read_text(encoding="utf-8"))
        if str(prior.get("reason","")).startswith(("unverified_container_cleanup","unverified_api_spend")):
            # Cannot be reset by a late generic error from another thread or
            # the next stage. Quarantine survives any subsequent status update.
            state="failed"
            details["reason"]=prior["reason"]
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
        try:
            answer=provider(chat)
        except BillableResponseRejected as exc:
            self.record_rejected_billable(
                request_key=key,logical_id=logical_id,model=model,exc=exc)
            raise
        if not isinstance(answer,dict) or "choices" not in answer:
            raise RuntimeError("Provider response invalid; will not checkpoint")
        atomic_json(path,{"request_key":key,"response_digest":digest(answer),"reply":answer})
        self.real_new_calls+=1
        return answer

    def record_rejected_billable(self,*,request_key:str,logical_id:str,
                                 model:str,exc:BillableResponseRejected)->None:
        """Write billable failed usage durably; NEVER create a successful reply."""
        usage=exc.usage
        vals=[usage.get(q) for q in ("prompt_tokens","completion_tokens",
                                    "cached_input_tokens","reasoning_tokens")]
        if (any(type(x)is not int or x<0 for x in vals) or
            vals[2]>vals[0] or vals[3]>vals[1]):
            self.mark("failed",reason="unverified_api_spend: rejected response lacked valid usage")
            raise RuntimeError("Unable to durably price rejected API response")
        entry={"request_key":request_key,"logical_id":logical_id,
               "model":model,"usage":usage,
               "remote_response_id":exc.remote_response_id,
               "rejected":True}
        entry["digest"]=digest({k:v for k,v in entry.items() if k!="digest"})
        # Each paid retry must be independently accounted, even for an
        # identical prompt, so never overwrite a previous failed attempt.
        filename=secrets.token_hex(16)+".json"
        path=self.failed_requests/filename
        atomic_json(path,entry)

    def stored_rejected_billable(self)->list[dict]:
        """Verify all separately charged failures before a resume/spend cap."""
        records=[]
        if not self.failed_requests.exists():
            return records
        for path in sorted(self.failed_requests.glob("*.json")):
            item=json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(item,dict) or item.get("rejected") is not True
                or item.get("digest")!=digest({k:v for k,v in item.items() if k!="digest"})
                or not isinstance(item.get("request_key"),str)
                or not isinstance(item.get("usage"),dict)):
                raise RuntimeError("Failed billable API usage ledger corrupt; refuse resume")
            records.append(item)
        return records

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
