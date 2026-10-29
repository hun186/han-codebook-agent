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
from generate import generate
from run import run_experiment


class GatewayInFlightLockTests(unittest.TestCase):
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
