"""Regression tests for crash-consistent blind commercial inference runs.

No real API or ChatGPT subscription calls: external model is a local test
double.  An API-shaped fake is used ONLY for spend-cap interruption testing;
that branch never reaches a valid prediction lock or real efficacy score.
"""
from __future__ import annotations
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"benchmarks"/"blind_commercial"))
sys.path.insert(0,str(ROOT/"src"))
import run as runner
import checkpoint as storage
from generate import generate
from codex_subscription import QuotaExhausted


def fake_reply(packet,*,real=False):
    body=json.loads(packet["messages"][1]["content"])
    if body.get("task")=="generate_vocabulary":
        answer={"vocabulary":[{"term":"運輸","reason":"TEST DOUBLE ONLY"}],"patterns":[]}
    else:
        words=body.get("available_vocabulary",[])
        answer={"hypotheses":[
            {"code":code,"candidates":words[:1],"reason":"TEST DOUBLE ONLY"}
            for code in list(body.get("unresolved",{}))[:5]]}
    return {"choices":[{"message":{"content":json.dumps(answer,ensure_ascii=False)}}],
            "model":"gpt-6-astra" if real else "TEST_DOUBLE",
            "usage":{"prompt_tokens":10,"cached_input_tokens":0,
                     "completion_tokens":10,"reasoning_tokens":0}}


class ResumeSafetyTests(unittest.TestCase):
    def setUp(self):
        td=tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        root=Path(td.name)
        self.public=root/"public"
        self.private=root/"gold_OUTSIDE_REPO"
        self.output=root/"outputs"
        generate(self.public,self.private,repeats=1,fixture_seed=987654)

    def run_mock(self,provider,*,resume=False,real=False,cap=100.0,
                 conditions=("with_aux",)):
        return runner.run_experiment(self.public,self.output,
            model="gpt-6-astra",effort="high",rounds=1,max_calls=16,timeout=30,
            provider=provider,conditions=conditions,
            real_api=real,solver_iterations=1,solver_restarts=1,
            max_estimated_usd=cap,
            provider_name="OPENAI_RESPONSES" if real else "TEST_DOUBLE",
            resume=resume)

    def test_unverified_container_cleanup_quarantines_resume(self):
        from checkpoint import ResumeStore
        signature={"test_case":"unverified Docker shutdown"}
        store=ResumeStore(self.output,signature=signature,resume=False)
        store.mark("failed",reason="unverified_container_cleanup: operator action required")
        with self.assertRaisesRegex(RuntimeError,"Unsafe resume"):
            ResumeStore(self.output,signature=signature,resume=True)
        state=json.loads((self.output/"run_status.json").read_text(encoding="utf-8"))
        self.assertEqual(state["state"],"failed")
        self.assertFalse((self.output/"predictions_LOCKED.json").exists())

    def test_parent_directory_entries_synced_after_atomic_replace(self):
        base=self.output/"deep"/"nested"
        dest=base/"test.json"
        calls=[]
        original=storage._sync_directory
        def traced(path):
            calls.append(Path(path))
            return original(path)
        with patch.object(storage,"_sync_directory",side_effect=traced):
            storage.atomic_json(dest,{"marker":"saved"})
        self.assertEqual(json.loads(dest.read_text()),{"marker":"saved"})
        if os.name=="posix":
            self.assertIn(dest.parent,calls,
                 "renamed checkpoint directory must be fsynced")
            self.assertIn(dest.parent.parent,calls,
                 "newly created child directory entry must be fsynced")
            self.assertIn(dest.parent.parent.parent,calls,
                 "newly created parent entry must be fsynced")
            self.assertEqual(calls[-1],dest.parent,
                 "durability barrier must occur after atomic replacement")

    def test_crash_after_prediction_lock_before_sha_resume_exact_original(self):
        asked=[]
        def live(packet):
            asked.append(1)
            return fake_reply(packet)
        original=runner.atomic_text
        def interrupt_sha(path,text):
            self.assertEqual(path.name,"predictions_LOCKED.sha256")
            raise OSError("SIMULATED POWER LOSS AFTER LOCK")
        with patch.object(runner,"atomic_text",side_effect=interrupt_sha):
            with self.assertRaisesRegex(OSError,"SIMULATED POWER LOSS"):
                self.run_mock(live)
        lock_path=self.output/"predictions_LOCKED.json"
        sha_path=self.output/"predictions_LOCKED.sha256"
        self.assertTrue(lock_path.is_file())
        self.assertFalse(sha_path.exists())
        self.assertEqual(len(asked),8)
        original_bytes=lock_path.read_bytes()
        self.assertEqual(json.loads((self.output/"run_status.json").read_text())["state"],"running")
        def never(packet):
            raise AssertionError("No replayed cloud/model request allowed during sealing")
        locked=self.run_mock(never,resume=True)
        self.assertEqual(original_bytes,lock_path.read_bytes())
        self.assertEqual(sha_path.read_text().strip(),
                         hashlib.sha256(original_bytes).hexdigest())
        self.assertEqual(json.loads((self.output/"run_status.json").read_text())["state"],"completed")
        self.assertEqual(locked["kind"],"TEST_DOUBLE_SMOKE_NOT_SCORED")
        self.assertEqual(locked["n_model_calls"],8)
        # A previously sealed, tampered SHA must not be silently rewritten.
        sha_path.write_text("BAD_HASH\n",encoding="ascii")
        self.assertNotEqual(sha_path.read_text().strip(),
                            hashlib.sha256(original_bytes).hexdigest())
        with self.assertRaisesRegex(RuntimeError,"already locked"):
            self.run_mock(never,resume=True)

    def test_resumed_api_spend_cap_includes_previous_successful_calls(self):
        # This is a FAKE OpenAI-shaped result with 0.0006 USD / model reply;
        # never emit completed GPT-6 evidence from a billing unit test.
        manifest=self.public/"manifest.json"
        data=json.loads(manifest.read_text(encoding="utf-8"))
        for item in data["studies"]:
            item["fixture_only"]=False
        manifest.write_text(json.dumps(data),encoding="utf-8")
        cap=0.0021
        seen=[]
        def first(packet):
            seen.append(1)
            if len(seen)==4:
                raise QuotaExhausted("usage limit reached (unit test)")
            return fake_reply(packet,real=True)
        with self.assertRaisesRegex(RuntimeError,"PAUSED_QUOTA"):
            self.run_mock(first,real=True,cap=cap)
        self.assertEqual(len(seen),4)
        self.assertEqual(len(list((self.output/"successful_requests").glob("*.json"))),3)
        self.assertFalse((self.output/"predictions_LOCKED.json").exists())
        after=[]
        def second(packet):
            after.append(1)
            return fake_reply(packet,real=True)
        with self.assertRaisesRegex(RuntimeError,"exceeded cap|Inference failed"):
            self.run_mock(second,real=True,cap=cap,resume=True)
        self.assertEqual(len(after),1,
            "spend from 3 persisted replies must be restored before calling the 4th")
        self.assertEqual(len(list((self.output/"successful_requests").glob("*.json"))),4)
        self.assertFalse((self.output/"predictions_LOCKED.json").exists())
        self.assertFalse((self.output/"evaluation.json").exists())


if __name__=="__main__":
    unittest.main()
