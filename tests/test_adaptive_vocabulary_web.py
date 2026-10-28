"""Loopback approval gate is a real per-round pause, not an inert GUI button."""
from __future__ import annotations

import copy
import json
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import patch
from urllib import request, error

from han_codebook.web import create_handler

ROOT = Path(__file__).resolve().parents[1]


class HumanReviewHTTPTest(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.handler=create_handler(self.root, ROOT/"config.offline.yaml")
        self.server=ThreadingHTTPServer(("127.0.0.1",0),self.handler)
        self.port=self.server.server_port
        self.server_thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.server_thread.start()
        self.case=json.loads((ROOT/"examples"/"demo_case.json").read_text(encoding="utf-8"))
        self.case.pop("ground_truth",None)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=3)
        self.tmp.cleanup()

    def post(self,path,body):
        data=json.dumps(body,ensure_ascii=False).encode("utf-8")
        req=request.Request(f"http://127.0.0.1:{self.port}"+path,
                            data=data,headers={"X-Han-UI":"local",
                                "Content-Type":"application/json"},method="POST")
        try:
            with request.urlopen(req,timeout=5) as response:
                return response.status,json.load(response)
        except error.HTTPError as exc:
            return exc.code,json.loads(exc.read())

    def get(self,path):
        with request.urlopen(f"http://127.0.0.1:{self.port}"+path,timeout=5) as response:
            return json.load(response)

    def wait_status(self,id,wanted):
        for _ in range(120):
            state=self.get("/api/jobs/"+id)
            if state["status"]==wanted:
                return state
            time.sleep(0.03)
        self.fail("Expected job "+wanted+"; got "+state["status"])

    def test_manual_review_pauses_and_accepts_only_offered_words(self):
        seen={}
        review_entered=threading.Event()
        def fake(case,**kw):
            seen["adaptive"]=kw["adaptive_vocabulary"]
            seen["review_enabled"]=kw["vocabulary_reviewer"] is not None
            review_entered.set()
            terms=kw["vocabulary_reviewer"](1,[
                {"term":"車隊","reason":"目擊資料","status":"unverified"},
                {"term":"補給","reason":"多報時序","status":"unverified"},
            ])
            seen["decision"]=terms
            raise RuntimeError("Stop after approval in mocked agent")
        with patch("han_codebook.web.run_agent",side_effect=fake):
            status,result=self.post("/api/start",{"case":self.case,"rounds":2,
                               "candidate_mode":"human","use_metadata":True})
            self.assertEqual(status,202,result)
            id=result["job_id"]
            self.assertTrue(review_entered.wait(4))
            pending=self.wait_status(id,"awaiting_review")
            self.assertEqual(pending["pending_review"]["round"],1)
            self.assertEqual(len(pending["pending_review"]["candidates"]),2)
            self.assertFalse(pending["review_submitted"])

            busy,body=self.post("/api/start",{"case":self.case,"rounds":0})
            self.assertEqual(busy,409,body)
            bad,body=self.post(f"/api/jobs/{id}/review",{"approved":["不是候選"]})
            self.assertEqual(bad,400,body)
            self.assertEqual(self.get("/api/jobs/"+id)["status"],"awaiting_review")
            accepted,body=self.post(f"/api/jobs/{id}/review",{"approved":["補給"]})
            self.assertEqual(accepted,200,body)
            self.assertEqual(body["accepted"],1)
            rejected,body=self.post(f"/api/jobs/{id}/review",{"approved":["車隊"]})
            self.assertEqual(rejected,409,body)
            failed=self.wait_status(id,"failed")
            self.assertEqual(seen["decision"],["補給"])
            self.assertTrue(seen["adaptive"] and seen["review_enabled"])
            self.assertNotIn("pending_review",failed)

    def test_automatic_mode_does_not_create_waiter(self):
        seen={}
        def fake(case,**kw):
            seen["adaptive"]=kw["adaptive_vocabulary"]
            seen["reviewer"]=kw["vocabulary_reviewer"]
            raise RuntimeError("Stop before model call")
        with patch("han_codebook.web.run_agent",side_effect=fake):
            status,result=self.post("/api/start",{"case":self.case,"rounds":2,
                                                  "candidate_mode":"automatic"})
            self.assertEqual(status,202,result)
            id=result["job_id"]
            job=self.wait_status(id,"failed")
            self.assertTrue(seen["adaptive"])
            self.assertIsNone(seen["reviewer"])
            self.assertNotIn("pending_review",job)
        bad,body=self.post("/api/start",{"case":self.case,"rounds":0,
                                         "candidate_mode":"automatic"})
        self.assertEqual(bad,400,body)


if __name__=="__main__":unittest.main()
