"""P2 regressions: billable rejected Responses and SIGKILL Docker recovery.

All API/provider/Docker interactions below are TEST DOUBLES. No user credits,
network access, real subscription inference or genuine accuracy measurement.
"""
from __future__ import annotations

import json
import os
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"benchmarks"/"blind_commercial"))
sys.path.insert(0,str(ROOT/"src"))

from checkpoint import ResumeStore,atomic_json,DOCKER_INFLIGHT
from codex_subscription import isolated_codex_run
from gpt_gateway import openai_responses,BillableResponseRejected
from generate import generate
from run import run_experiment,estimated_standard_usd


def fake_result(returncode=0,stderr=""):
    return SimpleNamespace(returncode=returncode,stdout="",stderr=stderr)


def charged_usage():
    # Astra Standard: 100 input + 10000 output = $0.501 (> $0.50).
    return {"prompt_tokens":100,"cached_input_tokens":0,
            "completion_tokens":10000,"reasoning_tokens":100}


class RejectedApiBillingTests(unittest.TestCase):
    def test_response_error_still_carries_usage_for_incomplete_or_empty_final(self):
        base={"id":"resp_TEST_NOT_PAID","model":"gpt-6-astra",
              "status":"incomplete","output":[],
              "usage":{"input_tokens":100,"output_tokens":10000,
                       "input_tokens_details":{"cached_tokens":0},
                       "output_tokens_details":{"reasoning_tokens":100},
                       "total_tokens":10100}}
        chat={"messages":[{"role":"system","content":"test"},
                          {"role":"user","content":"{}"}]}

        class Response:
            def __init__(self,raw):self.raw=raw
            def __enter__(self):return self
            def __exit__(self,*_):return False
            def read(self,_):return json.dumps(self.raw).encode()

        for status in ("incomplete","completed"):
            reply=dict(base,status=status)
            with patch("gpt_gateway.request.urlopen",return_value=Response(reply)):
                with self.subTest(status=status):
                    with self.assertRaises(BillableResponseRejected) as cm:
                        openai_responses(chat,key="FAKE_TEST_TOKEN",model="gpt-6-astra",
                                         effort="high",timeout=1)
                    self.assertEqual(cm.exception.usage,charged_usage()|{"total_tokens":10100})
                    self.assertEqual(cm.exception.remote_response_id,"resp_TEST_NOT_PAID")
                    self.assertEqual(cm.exception.actual_model,"gpt-6-astra")

    def test_billed_error_survives_restart_and_blocks_new_api_call_over_cap(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            public,private,out=root/"pub",root/"PRIVATE_GOLD",root/"output"
            generate(public,private,repeats=1,fixture_seed=9955)
            manifest=public/"manifest.json"
            m=json.loads(manifest.read_text(encoding="utf-8"))
            for s in m["studies"]:s["fixture_only"]=False
            manifest.write_text(json.dumps(m),encoding="utf-8")
            calls=[]
            def reject(_packet):
                calls.append(1)
                raise BillableResponseRejected(
                    "fake API incomplete",usage=charged_usage(),
                    remote_response_id="resp_FAKE_CHARGED",
                    actual_model="gpt-6-astra")

            def attempt(resume,provider):
                return run_experiment(public,out,model="gpt-6-astra",effort="high",
                                      rounds=1,max_calls=16,timeout=2,
                                      provider=provider,real_api=True,
                                      provider_name="OPENAI_RESPONSES",
                                      solver_iterations=1,solver_restarts=1,
                                      max_estimated_usd=.5,resume=resume)

            with self.assertRaisesRegex(RuntimeError,"Inference failed"):
                attempt(False,reject)
            self.assertEqual(len(calls),1)
            self.assertFalse((out/"predictions_LOCKED.json").exists())
            ledger=list((out/"rejected_billable_requests").glob("*.json"))
            self.assertEqual(len(ledger),1)
            record=json.loads(ledger[0].read_text(encoding="utf-8"))
            self.assertEqual(record["usage"],charged_usage())
            self.assertEqual(record["remote_response_id"],"resp_FAKE_CHARGED")
            self.assertGreater(estimated_standard_usd(record["usage"]),.5)
            self.assertEqual(len(list((out/"successful_requests").glob("*.json"))),0)

            def forbidden(_):
                calls.append(2)
                raise AssertionError("A paid call occurred after billing cap")
            with self.assertRaisesRegex(RuntimeError,"Previously incurred API usage exceeds"):
                attempt(True,forbidden)
            self.assertEqual(calls,[1])
            self.assertFalse((out/"evaluation.json").exists())

            record["usage"]["completion_tokens"]=1
            ledger[0].write_text(json.dumps(record),encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError,"ledger corrupt"):
                attempt(True,forbidden)
            self.assertEqual(calls,[1])


    def test_mismatched_luna_request_prices_actual_astra_without_retry(self):
        from run import billable_model
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)
            public,private,out=base/"public",base/"PRIVATE_GOLD",base/"out"
            generate(public,private,repeats=1,fixture_seed=10139)
            manifest=public/"manifest.json"
            m=json.loads(manifest.read_text(encoding="utf-8"))
            for study in m["studies"]:study["fixture_only"]=False
            manifest.write_text(json.dumps(m),encoding="utf-8")
            calls=[]
            def mismatched(_):
                calls.append("first")
                raise BillableResponseRejected(
                    "actual model differs",usage=charged_usage(),
                    remote_response_id="resp_actual_astra",
                    actual_model="gpt-6-astra")
            opts=dict(model="gpt-6-luna",effort="high",rounds=1,max_calls=16,
                      timeout=2,real_api=True,provider_name="OPENAI_RESPONSES",
                      solver_iterations=1,solver_restarts=1,max_estimated_usd=.10)
            with self.assertRaisesRegex(RuntimeError,"Inference failed"):
                run_experiment(public,out,provider=mismatched,resume=False,**opts)
            records=list((out/"rejected_billable_requests").glob("*.json"))
            self.assertEqual(len(records),1)
            charged=json.loads(records[0].read_text(encoding="utf-8"))
            self.assertEqual(charged["model"],"gpt-6-luna")
            self.assertEqual(charged["actual_model"],"gpt-6-astra")
            self.assertAlmostEqual(
                estimated_standard_usd(charged["usage"],
                                       model=billable_model(charged["actual_model"])),.501)
            self.assertAlmostEqual(
                estimated_standard_usd(charged["usage"],model="gpt-6-luna"),.00501)
            def forbidden(_):
                calls.append("wrong_retry")
                raise AssertionError("another charge after budget exhaustion")
            with self.assertRaisesRegex(RuntimeError,"Previously incurred API usage exceeds"):
                run_experiment(public,out,provider=forbidden,resume=True,**opts)
            self.assertEqual(calls,["first"])
            self.assertFalse((out/"predictions_LOCKED.json").exists())

    def test_unknown_actual_model_is_sticky_quarantine(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)
            public,private,out=base/"public",base/"private",base/"output"
            generate(public,private,repeats=1,fixture_seed=12377)
            manifest=public/"manifest.json"
            m=json.loads(manifest.read_text(encoding="utf-8"))
            for study in m["studies"]:study["fixture_only"]=False
            manifest.write_text(json.dumps(m),encoding="utf-8")
            calls=[]
            def rejected(_):
                calls.append("first")
                raise BillableResponseRejected(
                    "unknown model",usage=charged_usage(),
                    remote_response_id="resp_unexpected",
                    actual_model="unknown-paid-model")
            opts=dict(model="gpt-6-luna",effort="high",rounds=1,max_calls=16,
                      timeout=2,real_api=True,provider_name="OPENAI_RESPONSES",
                      solver_iterations=1,solver_restarts=1,max_estimated_usd=1.0)
            with self.assertRaisesRegex(RuntimeError,"Inference failed"):
                run_experiment(public,out,provider=rejected,resume=False,**opts)
            state=json.loads((out/"run_status.json").read_text(encoding="utf-8"))
            self.assertTrue(state["reason"].startswith("unverified_api_spend"))
            self.assertEqual(len(list((out/"rejected_billable_requests").glob("*.json"))),1)
            with self.assertRaisesRegex(RuntimeError,"Unsafe resume"):
                run_experiment(public,out,provider=lambda x:calls.append("retry"),
                               resume=True,**opts)
            self.assertEqual(calls,["first"])

    def test_failed_charge_ledger_write_blocks_resume_even_after_status_reset(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)
            public,private,out=base/"public",base/"private",base/"output"
            generate(public,private,repeats=1,fixture_seed=10188)
            manifest=public/"manifest.json"
            m=json.loads(manifest.read_text(encoding="utf-8"))
            for study in m["studies"]:study["fixture_only"]=False
            manifest.write_text(json.dumps(m),encoding="utf-8")
            calls=[]
            def billed_rejection(_):
                calls.append("charged")
                raise BillableResponseRejected(
                    "incomplete, charged",usage=charged_usage(),
                    remote_response_id="resp_no_durable_ledger",
                    actual_model="gpt-6-astra")
            import checkpoint
            original_atomic=checkpoint.atomic_json
            def fail_rejected(path,entry):
                if "rejected_billable_requests" in str(path):
                    raise OSError("test-only disk ledger write failure")
                return original_atomic(path,entry)
            opts=dict(model="gpt-6-astra",effort="high",rounds=1,max_calls=16,
                      timeout=2,real_api=True,provider_name="OPENAI_RESPONSES",
                      solver_iterations=1,solver_restarts=1,max_estimated_usd=.50)
            with patch("checkpoint.atomic_json",side_effect=fail_rejected):
                with self.assertRaisesRegex(RuntimeError,"Inference failed"):
                    run_experiment(public,out,provider=billed_rejection,resume=False,**opts)
            self.assertEqual(calls,["charged"])
            self.assertEqual(len(list((out/"rejected_billable_requests").glob("*.json"))),0)
            self.assertTrue((out/"api_request_inflight.json").is_file())
            state=json.loads((out/"run_status.json").read_text(encoding="utf-8"))
            self.assertTrue(state["reason"].startswith("unverified_api_spend"))
            # A damaged/stale status cannot override the durable pre-call marker.
            state.update(reason="ordinary failure",state="failed")
            (out/"run_status.json").write_text(json.dumps(state),encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError,"Unsafe resume"):
                run_experiment(public,out,provider=lambda x:calls.append("retry"),
                               resume=True,**opts)
            self.assertEqual(calls,["charged"])
            self.assertFalse((out/"predictions_LOCKED.json").exists())


class DurableDockerMarkerTests(unittest.TestCase):
    def test_sigkill_before_create_leaves_marker_and_resume_removes_old_container(self):
        """An actual child process exits via os._exit, bypassing Python finally."""
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)
            home=base/"home";home.mkdir()
            (home/"auth.json").write_text('{"test_only":true}',encoding="utf-8")
            scratch=base/"scratch";scratch.mkdir()
            output=base/"output"
            signature={"test":"kill-before-docker-create"}
            ResumeStore(output,signature=signature,resume=False)

            script=r'''import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from codex_subscription import isolated_codex_run
def kill_after_marker(argv,**kw):
    assert argv[:2]==["docker","create"],argv
    assert (Path(sys.argv[2])/"codex_container_inflight.json").is_file()
    os._exit(87)
isolated_codex_run(["codex","exec"],home=Path(sys.argv[3]),
                   scratch=Path(sys.argv[4]),lifecycle_root=Path(sys.argv[2]),
                   subprocess_run=kill_after_marker)
'''
            child=subprocess.run([sys.executable,"-c",script,
                                  str(ROOT/"benchmarks"/"blind_commercial"),
                                  str(output),str(home),str(scratch)],
                                  capture_output=True,text=True,timeout=15)
            self.assertEqual(child.returncode,87,child.stderr)
            marker=output/DOCKER_INFLIGHT
            saved=json.loads(marker.read_text(encoding="utf-8"))
            self.assertRegex(saved["name"],r"^han-blind-[0-9a-f]{32}$")
            events=[]
            def docker(argv,**kw):
                events.append(argv)
                self.assertEqual(argv[-1],saved["name"])
                if argv[1]=="rm":return fake_result(0)
                if argv[1]=="inspect":return fake_result(1,"No such object")
                raise AssertionError("unexpected docker operation")

            with patch("checkpoint.subprocess.run",side_effect=docker):
                ResumeStore(output,signature=signature,resume=True)
            self.assertEqual([v[1] for v in events],["rm","inspect"])
            self.assertFalse(marker.exists())
            self.assertEqual(json.loads((output/"run_status.json").read_text())["state"],"running")

    def test_ambiguous_docker_daemon_quarantines_checkpoint(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/"out";signature={"test":"ambiguous"}
            ResumeStore(out,signature=signature,resume=False)
            atomic_json(out/DOCKER_INFLIGHT,
                        {"version":1,"name":"han-blind-"+"a"*32})
            def fail(argv,**kw):
                return fake_result(1,"daemon unavailable")
            with patch("checkpoint.subprocess.run",side_effect=fail):
                with self.assertRaisesRegex(RuntimeError,"Unsafe resume"):
                    ResumeStore(out,signature=signature,resume=True)
            info=json.loads((out/"run_status.json").read_text())
            self.assertEqual(info["state"],"failed")
            self.assertTrue(info["reason"].startswith("unverified_container_cleanup"))
            self.assertTrue((out/DOCKER_INFLIGHT).exists())
            # Even after a later daemon recovery, explicit manual intervention
            # is required to clear the sticky quarantine state.
            with self.assertRaisesRegex(RuntimeError,"Unsafe resume"):
                ResumeStore(out,signature=signature,resume=True)


if __name__=="__main__":
    unittest.main()
