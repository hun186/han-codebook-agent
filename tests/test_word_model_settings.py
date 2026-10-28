"""Local UI model configuration, Word export and counterfactual-annotation guards."""
from __future__ import annotations

import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from urllib import request, error
from zipfile import ZipFile

from han_codebook.bold_hypotheses import normalize_bold_hypotheses
from han_codebook.core import CaseError, analyze, load_case, validate_case
from han_codebook.model_settings import save_model_settings, model_settings
from han_codebook.report_docx import investigation_docx
from han_codebook.web import create_handler

ROOT = Path(__file__).resolve().parents[1]


class ModelSettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.cfg=Path(self.temp.name)/"config.yaml"
        self.cfg.write_text("project: {}\nanalysis: {}\nllm:\n  base_url: http://127.0.0.1:11434\n  model: old\n",encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_safe_local_and_lan_settings_persist(self):
        result=save_model_settings(self.cfg, {
            "base_url":"http://127.0.0.1:11434","model":"qwen3:14b",
            "timeout_seconds":120,"allow_private_network":False,
            "api_key_env":"HAN_CODEBOOK_LLM_API_KEY"})
        self.assertEqual(result["model"],"qwen3:14b")
        self.assertEqual(result["api_key_env"],"HAN_CODEBOOK_LLM_API_KEY")
        self.assertFalse(result["secret_value_exposed"])
        self.assertNotIn("password",self.cfg.read_text(encoding="utf-8").lower())
        result=save_model_settings(self.cfg, {
            "base_url":"http://192.168.0.134:18080","model":"qwen-local",
            "timeout_seconds":60,"allow_private_network":True,"api_key_env":""})
        self.assertEqual(result["allowed_hosts"],["192.168.0.134"])

    def test_public_url_and_secret_rejected_without_mutation(self):
        old=self.cfg.read_bytes()
        for url in ("https://api.openai.com/v1", "http://8.8.8.8/v1",
                    "http://localhost.evil.test/v1","http://127.0.0.1:11434/?x=y",
                    "http://192.168.0.134:11434"):
            with self.subTest(url=url),self.assertRaises(CaseError):
                save_model_settings(self.cfg,{
                    "base_url":url,"model":"test","timeout_seconds":90,
                    "allow_private_network":False,"api_key_env":""})
            self.assertEqual(self.cfg.read_bytes(),old)
        with self.assertRaises(CaseError):
            save_model_settings(self.cfg,{"base_url":"http://localhost:11434","model":"test",
                "timeout_seconds":90,"allow_private_network":False,
                "api_key_env":"actual-token-do-not-store!"})
        self.assertEqual(self.cfg.read_bytes(),old)


class WordAndBoldTests(unittest.TestCase):
    def test_word_is_real_docx_with_tables_and_unicode(self):
        result={"case_id":"軍事研究","proposals":{
              "101":{"term":"車隊","status":"verified_alignment"},
              "102":{"term":"橋梁","status":"hypothesis_unverified"}},
              "verified_anchors":{"101":"車隊"},
              "bold_hypotheses":{"101":{"term":"火車","note":"反事實試驗","confirmed":True}},
              "decoded_messages":[{"id":"m1","domain_inferred":"logistics",
                 "reading":"車隊 橋梁","verified_codes":1,"total_codes":2}],
              "metadata_used":True,"agent_rounds_completed":1}
        docx=investigation_docx(result,[
            {"stage":"statistical_baseline","round":0,"payload":{"score":1.23,"mapping":{"101":"車隊","102":"補給"}}},
            {"stage":"rescore","round":1,"payload":{"score":1.35,"changed_count":1}},
        ])
        self.assertGreater(len(docx),1000)
        with ZipFile(io.BytesIO(docx)) as archive:
            self.assertIsNone(archive.testzip())
            xml=archive.read("word/document.xml").decode()
            for word in ("軍事研究","車隊","橋梁","火車","逐輪","反事實"):
                self.assertIn(word,xml)
            self.assertGreater(xml.count("<w:tbl>"),3)

    def test_bold_counterfactual_never_changes_verified_anchors(self):
        case=load_case(ROOT/"examples/demo_case.json")
        result=analyze(case,iterations=1,restarts=1)
        anchors=result["verified_anchors"]
        self.assertTrue(anchors)
        code,original=next(iter(anchors.items()))
        case["bold_hypotheses"]={code:{"term":"研究員反對假說","note":"保留原錨點","confirmed":True}}
        validate_case(case)
        self.assertEqual(normalize_bold_hypotheses(case,anchors)[code]["term"],"研究員反對假說")
        rerun=analyze(case,iterations=1,restarts=1)
        self.assertEqual(rerun["verified_anchors"],anchors)
        self.assertEqual(rerun["proposals"][code]["term"],original)
        for replacement in (
            {code:{"term":"研究員反對假說","note":"","confirmed":False}},
            {code:{"term":original,"note":"","confirmed":True}},
            {"999999":{"term":"非錨點","note":"","confirmed":True}},
        ):
            case["bold_hypotheses"]=replacement
            with self.subTest(replacement=replacement),self.assertRaises(CaseError):
                validate_case(case)


class WordAndLLMHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=TemporaryDirectory()
        cls.root=Path(cls.temp.name)
        (cls.root/"examples").mkdir()
        (cls.root/"examples"/"example.json").write_text(
            (ROOT/"examples/demo_case.json").read_text(encoding="utf-8"),encoding="utf-8")
        (cls.root/"config.yaml").write_text(
            "project: {}\nanalysis: {}\nllm:\n  base_url: http://127.0.0.1:11434\n  model: test\n",encoding="utf-8")
        cls.server=ThreadingHTTPServer(("127.0.0.1",0),create_handler(cls.root,cls.root/"config.yaml"))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.base=f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join(timeout=2)
        cls.temp.cleanup()

    def post(self,path,body):
        req=request.Request(self.base+path,
            data=json.dumps(body,ensure_ascii=False).encode(),
            headers={"Content-Type":"application/json","X-Han-UI":"local","Origin":self.base},
            method="POST")
        return json.load(request.urlopen(req))

    def test_settings_api_rounds_and_word_download(self):
        result=self.post("/api/settings/llm",{
            "base_url":"http://127.0.0.1:11434","model":"local-test",
            "timeout_seconds":30,"allow_private_network":False,"api_key_env":""})
        self.assertEqual(result["model"],"local-test")
        case=json.load(request.urlopen(self.base+"/api/case?id=examples%2Fexample.json"))
        with self.assertRaises(error.HTTPError) as ex:
            self.post("/api/start",{"case":case,"rounds":21})
        self.assertEqual(ex.exception.code,400)
        job=self.post("/api/start",{"case":case,"rounds":0})["job_id"]
        for _ in range(150):
            state=json.load(request.urlopen(self.base+"/api/jobs/"+job))
            if state["status"] in ("completed","failed"):
                break
            time.sleep(0.1)
        self.assertEqual(state["status"],"completed",state["error"])
        response=request.urlopen(self.base+"/api/jobs/"+job+"/report.docx")
        self.assertEqual(response.status,200)
        self.assertEqual(response.headers.get_content_type(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        with ZipFile(io.BytesIO(response.read())) as z:
            self.assertIsNone(z.testzip())


if __name__ == "__main__":
    unittest.main()
