"""Live loopback timeout: provider must finish before study lock is released.

No commercial model use. This uses an intentionally blocked provider callback
and a real local HTTP request from the original han_codebook Agent.
"""
import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"benchmarks"/"blind_commercial"))
sys.path.insert(0,str(ROOT/"src"))
from checkpoint import exclusive_run_lock
from codex_subscription import ContainerCleanupUnconfirmed
from generate import generate
from run import run_experiment


class GatewayInFlightLockTests(unittest.TestCase):
    def test_late_container_cleanup_failure_quarantines_after_http_timeout(self):
        """The original Agent times out BEFORE Docker failure reaches Handler."""
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)
            public=base/"public"
            private=base/"gold_only_for_generator"
            output=base/"results"
            generate(public,private,repeats=1,fixture_seed=9918)
            entered=threading.Event()
            release=threading.Event()
            exited=threading.Event()
            exceptions=[]
            provider_calls=[]
            def late_cleanup_failure(packet):
                provider_calls.append(1)
                entered.set()
                if not release.wait(15):
                    raise AssertionError("Provider test gate never released")
                raise ContainerCleanupUnconfirmed(
                    "Container cleanup unverified for han-blind-TEST; do not resume")
            def run(resume=False,provider=late_cleanup_failure):
                return run_experiment(public,output,model="gpt-6-astra",
                    effort="high",rounds=1,max_calls=16,timeout=1,
                    provider=provider,real_api=False,
                    conditions=("with_aux",),solver_iterations=1,
                    solver_restarts=1,resume=resume)
            def worker():
                try:
                    run()
                except Exception as exc:
                    exceptions.append(exc)
                finally:
                    exited.set()
            th=threading.Thread(target=worker,daemon=True)
            th.start()
            try:
                self.assertTrue(entered.wait(20),"Original Agent did not invoke provider")
                # Ensure caller has already timed out and written a generic
                # failure; only then allow the container cleanup to fail.
                deadline=time.monotonic()+12
                seen_normal_failure=False
                while time.monotonic()<deadline:
                    status=output/"run_status.json"
                    if status.exists():
                        snap=json.loads(status.read_text(encoding="utf-8"))
                        if (snap.get("state")=="failed" and
                            snap.get("reason","").startswith("inference interruption")):
                            seen_normal_failure=True
                            break
                    time.sleep(.08)
                self.assertTrue(seen_normal_failure,
                                "Did not reproduce generic failure before late cleanup")
                self.assertFalse(exited.is_set())
                with self.assertRaisesRegex(RuntimeError,"locked by another process"):
                    with exclusive_run_lock(output):
                        pass
            finally:
                release.set()
                th.join(timeout=20)
            self.assertTrue(exited.is_set(),"Runner did not drain failed provider")
            self.assertTrue(exceptions)
            final=json.loads((output/"run_status.json").read_text(encoding="utf-8"))
            self.assertEqual(final["state"],"failed")
            self.assertTrue(final["reason"].startswith("unverified_container_cleanup"))
            self.assertEqual(provider_calls,[1])
            self.assertFalse((output/"predictions_LOCKED.json").exists())
            self.assertFalse((output/"predictions_LOCKED.sha256").exists())
            def forbidden(packet):
                provider_calls.append(2)
                raise AssertionError("Resume cannot call model after cleanup uncertainty")
            with self.assertRaisesRegex(RuntimeError,"Unsafe resume"):
                run(resume=True,provider=forbidden)
            self.assertEqual(provider_calls,[1],"Unsafe resume called a model")
            # Even a second ordinary failed mark must not clear quarantine.
            from checkpoint import ResumeStore
            snapshot=json.loads((output/"run_status.json").read_text(encoding="utf-8"))
            self.assertEqual(snapshot["state"],"failed")

    def test_timed_out_provider_cannot_outlive_study_lock(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)
            public=base/"public"
            private=base/"never_opened_by_runner"
            output=base/"results"
            generate(public,private,repeats=1,fixture_seed=9917)
            entered=threading.Event()
            release=threading.Event()
            finished=threading.Event()
            problems=[]
            replies=[]
            def blocked_provider(packet):
                entered.set()
                if not release.wait(12):
                    raise RuntimeError("Test provider was never released")
                replies.append(1)
                data={"vocabulary":[],"patterns":[]}
                return {
                    "choices":[{"message":{"role":"assistant",
                                           "content":json.dumps(data)}}],
                    "model":"TEST_DOUBLE",
                    "usage":{"prompt_tokens":10,"completion_tokens":10,
                             "cached_input_tokens":0,"reasoning_tokens":0}
                }
            def worker():
                try:
                    run_experiment(public,output,model="gpt-6-astra",
                        effort="high",rounds=1,max_calls=16,timeout=1,
                        provider=blocked_provider,real_api=False,
                        conditions=("with_aux",),solver_iterations=1,
                        solver_restarts=1)
                except Exception as exc:
                    problems.append(exc)
                finally:
                    finished.set()
            thread=threading.Thread(target=worker,daemon=True)
            thread.start()
            try:
                self.assertTrue(entered.wait(20),"Original Agent did not reach provider")
                # Wait beyond the original 1s HTTP deadline: prior code would
                # release the lock while the daemon provider was still alive.
                time.sleep(2.0)
                self.assertFalse(finished.is_set(),
                    "Runner returned while a timed-out provider still ran")
                with self.assertRaisesRegex(RuntimeError,"locked by another process"):
                    with exclusive_run_lock(output):
                        pass
                self.assertFalse((output/"predictions_LOCKED.json").exists())
            finally:
                release.set()
                thread.join(timeout=20)
            self.assertTrue(finished.is_set(),"Gateway did not drain provider")
            self.assertTrue(problems,"The timeout must invalidate this run")
            self.assertEqual(len(replies),1)
            self.assertEqual(len(list((output/"successful_requests").glob("*.json"))),1)
            self.assertEqual(json.loads((output/"run_status.json").read_text())["state"],"failed")
            # After all handlers join, a resumed process can safely acquire
            # the lock without a predecessor still mutating the checkpoint.
            with exclusive_run_lock(output):
                pass


if __name__=="__main__":
    unittest.main()
