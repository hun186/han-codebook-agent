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

    def review_payload(self,id,approved,added=None):
        pending=self.get("/api/jobs/"+id)["pending_review"]
        return {"approved": approved, "added": added or [], "round": pending["round"],
                "review_token": pending["review_token"]}

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
            bad,body=self.post(f"/api/jobs/{id}/review",self.review_payload(id,["不是候選"]))
            self.assertEqual(bad,400,body)
            self.assertEqual(self.get("/api/jobs/"+id)["status"],"awaiting_review")
            approved_payload=self.review_payload(id,["補給"])
            accepted,body=self.post(f"/api/jobs/{id}/review",approved_payload)
            self.assertEqual(accepted,200,body)
            self.assertEqual(body["accepted"],1)
            rejected,body=self.post(f"/api/jobs/{id}/review",approved_payload)
            self.assertEqual(rejected,409,body)
            failed=self.wait_status(id,"failed")
            self.assertEqual(seen["decision"],{"approved":["補給"],"added":[]})
            self.assertTrue(seen["adaptive"] and seen["review_enabled"])
            self.assertNotIn("pending_review",failed)

    def test_case_change_can_cancel_waiting_review_without_ten_minute_gate(self):
        entered=threading.Event()
        def fake(case,**kw):
            entered.set()
            kw["vocabulary_reviewer"](1,[{"term":"待審","reason":"合成情報"}])
            raise RuntimeError("Unreachable after cancellation")
        with patch("han_codebook.web.run_agent",side_effect=fake):
            status,body=self.post("/api/start",{"case":self.case,"rounds":1,
                                                 "candidate_mode":"human"})
            self.assertEqual(status,202,body)
            id=body["job_id"]
            self.assertTrue(entered.wait(4))
            self.wait_status(id,"awaiting_review")
            old_payload=self.review_payload(id,["待審"])
            cancel_status,response=self.post(f"/api/jobs/{id}/cancel",{})
            self.assertEqual(cancel_status,200,response)
            failed=self.wait_status(id,"failed")
            self.assertIn("cancel",failed["error"].lower())
            self.assertNotIn("pending_review",failed)
            status,body=self.post(f"/api/jobs/{id}/review",old_payload)
            self.assertEqual(status,409,body)
            # The old job must no longer monopolize the analysis gate.
            status,body=self.post("/api/start",{"case":self.case,"rounds":0})
            self.assertEqual(status,202,body)

    def test_cancel_before_review_is_registered_does_not_leave_stale_waiter(self):
        started=threading.Event()
        proceed=threading.Event()
        def fake(case,**kw):
            started.set()
            if not proceed.wait(4):
                raise RuntimeError("test setup timed out")
            kw["vocabulary_reviewer"](1,[{"term":"未知","reason":"測試"}])
        with patch("han_codebook.web.run_agent",side_effect=fake):
            status,body=self.post("/api/start",{"case":self.case,"rounds":1,
                                                 "candidate_mode":"human"})
            self.assertEqual(status,202,body)
            id=body["job_id"]
            self.assertTrue(started.wait(4))
            cancel_status,_=self.post(f"/api/jobs/{id}/cancel",{})
            self.assertEqual(cancel_status,200)
            proceed.set()
            failed=self.wait_status(id,"failed")
            self.assertIn("cancel",failed["error"].lower())
            self.assertNotIn("pending_review",failed)

    def test_retry_from_prior_round_cannot_approve_next_round(self):
        seen=[]
        def fake(case,**kw):
            reviewer=kw["vocabulary_reviewer"]
            seen.append(reviewer(1,[{"term":"重複候選","reason":"round one"}]))
            seen.append(reviewer(2,[{"term":"重複候選","reason":"round two"}]))
            raise RuntimeError("Mock reviewer done")
        with patch("han_codebook.web.run_agent",side_effect=fake):
            status,body=self.post("/api/start",{"case":self.case,"rounds":2,
                                                 "candidate_mode":"human"})
            self.assertEqual(status,202,body)
            id=body["job_id"]
            self.wait_status(id,"awaiting_review")
            old_payload=self.review_payload(id,[])
            status,body=self.post(f"/api/jobs/{id}/review",old_payload)
            self.assertEqual(status,200,body)
            for _ in range(120):
                second=self.get("/api/jobs/"+id)
                if (second["status"]=="awaiting_review"
                        and second["pending_review"]["round"]==2):
                    break
                time.sleep(0.03)
            else:
                self.fail("Second review did not appear")
            self.assertNotEqual(old_payload["review_token"],
                                second["pending_review"]["review_token"])
            status,body=self.post(f"/api/jobs/{id}/review",old_payload)
            self.assertEqual(status,409,body)
            self.assertEqual(self.get("/api/jobs/"+id)["status"],"awaiting_review")
            status,body=self.post(f"/api/jobs/{id}/review",self.review_payload(id,["重複候選"]))
            self.assertEqual(status,200,body)
            self.wait_status(id,"failed")
            self.assertEqual(seen,[{"approved":[],"added":[]},
                                   {"approved":["重複候選"],"added":[]}])

    def test_researcher_adds_custom_words_alongside_or_instead_of_llm(self):
        received=[]
        def fake(case,**kw):
            reviewer=kw["vocabulary_reviewer"]
            received.append(reviewer(1,[{"term":"模型提議","reason":"LLM"}]))
            received.append(reviewer(2,[{"term":"模型另一詞","reason":"LLM"}]))
            raise RuntimeError("Mock review completed")
        with patch("han_codebook.web.run_agent",side_effect=fake):
            status,body=self.post("/api/start",{"case":self.case,"rounds":2,
                                                 "candidate_mode":"human"})
            self.assertEqual(status,202,body)
            id=body["job_id"]
            self.wait_status(id,"awaiting_review")
            invalid=self.review_payload(id,["模型提議"],["模型提議"])
            code,_=self.post(f"/api/jobs/{id}/review",invalid)
            self.assertEqual(code,400)
            code,_=self.post(f"/api/jobs/{id}/review",
                 self.review_payload(id,["模型提議"],["人工新增一","人工新增二"]))
            self.assertEqual(code,200)
            for _ in range(120):
                state=self.get("/api/jobs/"+id)
                if (state["status"]=="awaiting_review"
                        and state["pending_review"]["round"]==2):
                    break
                time.sleep(0.03)
            else:
                self.fail("Second round review not available")
            code,_=self.post(f"/api/jobs/{id}/review",
                 self.review_payload(id,[],["人工新增一"]))
            self.assertEqual(code,400,"An accepted prior-round word must not consume a new review token")
            self.assertEqual(self.get("/api/jobs/"+id)["status"],"awaiting_review")
            code,_=self.post(f"/api/jobs/{id}/review",
                 self.review_payload(id,[],["全由人工提出"]))
            self.assertEqual(code,200)
            self.wait_status(id,"failed")
            self.assertEqual(received,[
                {"approved":["模型提議"],"added":["人工新增一","人工新增二"]},
                {"approved":[],"added":["全由人工提出"]}])

    def test_invalid_added_terms_do_not_consume_review_token(self):
        def fake(case,**kw):
            kw["vocabulary_reviewer"](1,[{"term":"模型提議","reason":"LLM"}])
            raise RuntimeError("Mock done")
        with patch("han_codebook.web.run_agent",side_effect=fake):
            status,body=self.post("/api/start",{"case":self.case,"rounds":1,
                                                 "candidate_mode":"human"})
            self.assertEqual(status,202,body)
            id=body["job_id"]
            self.wait_status(id,"awaiting_review")
            for bad in ([""],["補給"],["重複詞","重複詞"],["一"*25],
                        ["研究" + chr(10) + "字"],["模型提議"],
                        ["新詞"+str(n) for n in range(33)]):
                code,_=self.post(f"/api/jobs/{id}/review",
                                  self.review_payload(id,[],bad))
                self.assertEqual(code,400,bad)
                self.assertEqual(self.get("/api/jobs/"+id)["status"],"awaiting_review")
            code,_=self.post(f"/api/jobs/{id}/review",
                              self.review_payload(id,[],["有效新詞"]))
            self.assertEqual(code,200)
            self.wait_status(id,"failed")

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
