"""Real two-process POSIX/Windows checkpoint-lock contention regression."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BENCH=ROOT/"benchmarks"/"blind_commercial"
sys.path.insert(0,str(BENCH))
from checkpoint import exclusive_run_lock
from generate import generate
from run import run_experiment

class CheckpointProcessLockTests(unittest.TestCase):
    def test_second_process_cannot_run_agent_or_touch_audit(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)
            public=base/"public"
            private=base/"gold"
            output=base/"results"
            generate(public,private,repeats=1,fixture_seed=7412)
            script=(
                "import sys,time;from pathlib import Path;"
                "sys.path.insert(0,sys.argv[1]);"
                "from checkpoint import exclusive_run_lock;"
                "lock=exclusive_run_lock(Path(sys.argv[2]));"
                "lock.__enter__();"
                "print('ACQUIRED',flush=True);time.sleep(60)"
            )
            proc=subprocess.Popen(
                [sys.executable,"-c",script,str(BENCH),str(output)],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                self.assertEqual(proc.stdout.readline().strip(),"ACQUIRED")
                self.assertIsNone(proc.poll())
                calls=[]
                def provider(packet):
                    calls.append(packet)
                    raise AssertionError("second model request must not occur")
                with self.assertRaisesRegex(RuntimeError,"locked by another process"):
                    run_experiment(public,output,model="gpt-6-astra",effort="high",
                        rounds=1,max_calls=16,timeout=10,provider=provider,
                        conditions=("with_aux",),real_api=False,
                        solver_iterations=1,solver_restarts=1)
                self.assertEqual(calls,[])
                self.assertFalse((output/"run_status.json").exists())
                self.assertFalse((output/"successful_requests").exists())
            finally:
                proc.kill()
                proc.wait(timeout=10)
                proc.stdout.close()
                proc.stderr.close()
            # A SIGKILL or TerminateProcess must release the kernel lock;
            # the .run.lock inode stays in place and is never manually deleted.
            self.assertTrue((output/".run.lock").is_file())
            with exclusive_run_lock(output):
                self.assertTrue((output/".run.lock").is_file())
            with exclusive_run_lock(output):
                with self.assertRaisesRegex(RuntimeError,"locked by another process"):
                    with exclusive_run_lock(output):
                        pass

if __name__=="__main__":
    unittest.main()
