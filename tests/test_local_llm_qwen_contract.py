"""Captured Qwen failure modes, distilled to synthetic non-sensitive regression.

Never call LAN or a real model; no benchmark correctness is attributed to mocks.
"""
from __future__ import annotations
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from han_codebook.agent import query_local_llm
from han_codebook.auto_vocabulary import generate_vocabulary
from han_codebook.config import load_settings
from han_codebook.core import CaseError, analyze
from han_codebook.volume_llm import llm_rescore, as_markdown

ROOT=Path(__file__).resolve().parents[1]
CASE=ROOT/"benchmarks/volume/seed_101_case.json"
BASE="http://192.168.0.134:18080"
NETWORK={"allow_private_network":True,"allowed_hosts":["192.168.0.134"]}

class FakeResponse:
    def __init__(self,body): self.body=json.dumps(body).encode("utf-8")
    def __enter__(self): return self
    def __exit__(self,*a): return False
    def read(self,n): return self.body

class QwenContractTests(unittest.TestCase):
    def test_empty_final_with_reasoning_is_explicitly_failed_not_fabricated(self):
        events=[]
        response={"choices":[{"message":{"role":"assistant","content":"",
                                         "reasoning":"Thinking but never produced final JSON"},
                               "finish_reason":"stop"}],
                  "usage":{"prompt_tokens":8608,"completion_tokens":17106}}
        with patch("han_codebook.agent.request.urlopen",return_value=FakeResponse(response)):
            with self.assertRaisesRegex(CaseError,"empty final content .*reasoning_only=True.*17106"):
                query_local_llm(BASE,"qwen3.8:latest-128k",{"unresolved":{}},
                    reasoning_effort="none",response_format="json_object",
                    on_exchange=lambda stage,payload:events.append((stage,payload)),**NETWORK)
        request=events[0][1]["body"]
        self.assertEqual(request["reasoning_effort"],"none")
        self.assertEqual(request["response_format"],{"type":"json_object"})
        self.assertEqual(events[1][0],"llm_response")
        self.assertIn("reasoning",events[1][1]["response"])

    def test_controls_are_opt_in_and_json_content_still_validated(self):
        reply={"choices":[{"message":{"role":"assistant","content":
                   '{"hypotheses": []}'}}],"usage":{}}
        events=[]
        with patch("han_codebook.agent.request.urlopen",return_value=FakeResponse(reply)):
            result=query_local_llm(BASE,"mock",{"unresolved":{}},
                on_exchange=lambda stage,packet:events.append((stage,packet)),**NETWORK)
        self.assertEqual(result,{"hypotheses":[]})
        self.assertNotIn("reasoning_effort",events[0][1]["body"])
        self.assertNotIn("response_format",events[0][1]["body"])
        with self.assertRaisesRegex(CaseError,"Unsupported llm.reasoning_effort"):
            query_local_llm(BASE,"mock",{},reasoning_effort="unsafe",**NETWORK)

    def test_strict_config_controls(self):
        with TemporaryDirectory() as td:
            p=Path(td)/"test.yaml"
            p.write_text('llm:\n  reasoning_effort: none\n  response_format: json_object\n')
            v=load_settings(p)["llm"]
            self.assertEqual(v["reasoning_effort"],"none")
            self.assertEqual(v["response_format"],"json_object")
            p.write_text('llm:\n  reasoning_effort: giant\n')
            with self.assertRaisesRegex(CaseError,"reasoning_effort"):
                load_settings(p)
            p.write_text('llm:\n  response_format: fabricated\n')
            with self.assertRaisesRegex(CaseError,"response_format"):
                load_settings(p)

    def test_invalid_joined_codes_rejected_with_reasons(self):
        case=json.loads(CASE.read_text(encoding="utf-8"))
        case["messages"]=case["messages"][:10]
        baseline=analyze(case,iterations=1,restarts=1)
        def mock(url,model,packet,**kwargs):
            self.assertEqual(packet["allowed_codes"],sorted(packet["unresolved"]))
            codes=packet["allowed_codes"]
            word=packet["available_vocabulary"][0]
            self.assertTrue(codes)
            # Observed Qwen behavior: multiple code groups joined in one key.
            return {"hypotheses":[{"code":f"{codes[0]}-{codes[1]}",
                                   "candidates":[word],"reason":"test"} for i in range(15)]}
        out,records,calls=llm_rescore(case,baseline,metadata=True,
            llm_settings={"base_url":BASE,"model":"MOCK",**NETWORK},
            rounds=1,batch_size=10,iterations=1,restarts=1,
            query=mock,progress=lambda _:None)
        self.assertEqual(calls,1)
        self.assertEqual(records[0]["rejected"],15)
        self.assertEqual(records[0]["rejection_reasons"],{"invalid_code":15})
        self.assertEqual(len(records[0]["rejection_examples"]),5)
        self.assertEqual(records[0]["accepted"],[])
        self.assertEqual(out["proposals"],baseline["proposals"])
        report={"model":"MOCK","batch_size":10,"rounds":1,"runs":[],
                "llm_call_total":1,"trace":[{"seed":101,"messages":10,
                                             "trace":records}]}
        self.assertIn("invalid_code:15",as_markdown(report))

    def test_discarded_pattern_strings_are_diagnosed_not_silently_converted(self):
        case=json.loads(CASE.read_text(encoding="utf-8"))
        case["messages"]=case["messages"][:10]
        def mock(url,model,packet,**kwargs):
            self.assertEqual(packet["task"],"generate_vocabulary")
            self.assertEqual(kwargs.get("reasoning_effort"),"none")
            return {"vocabulary":[{"term":w} for w in ("補給","車隊","出發","倉庫","糧秣")],
                    "patterns":["車隊出發",["補給","不在詞庫"],["補給","車隊","出發"]]}
        _,record=generate_vocabulary(case,metadata=False,
            llm_settings={"base_url":BASE,"model":"MOCK",**NETWORK,
                          "reasoning_effort":"none","response_format":"json_object"},
            progress=lambda _:None,query=mock)
        self.assertEqual(record["patterns"],[["補給","車隊","出發"]])
        self.assertEqual(record["vocabulary_diagnostics"]["patterns"],
                         {"not_token_arrays":1,"unknown_terms":1,"valid":1})
        self.assertTrue(record["discarded_manual_profiles"])
