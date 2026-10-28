"""Full-round audit and safe cancellation for adaptive local LLM vocabulary."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from han_codebook.agent import run_agent
from han_codebook.core import CaseError

ROOT=Path(__file__).resolve().parents[1]


def case_data():
    obj=json.loads((ROOT/"examples"/"demo_case.json").read_text(encoding="utf-8"))
    obj.pop("ground_truth",None)
    return obj


def mapping(word):
    return {"proposals":{"999":{"term":word,"status":"hypothesis_unverified"}},
            "verified_anchors":{},"objective_score": 0.0}


class AdaptiveRoundIntegrityTests(unittest.TestCase):
    def test_vocab_change_counted_even_if_code_llm_returns_no_hypotheses(self):
        calls=[]
        def fake_analyze(case,**kw):
            calls.append(deepcopy(case["profiles"]))
            return mapping("原詞" if len(calls)==1 else "新增詞")
        def fake_vocab(url,model,packet,**kw):
            return {"vocabulary":[{"term":"新增詞","reason":"依跨報背景提出"}]}
        def fake_code(url,model,packet,**kw):
            self.assertIn("新增詞",packet["available_vocabulary"])
            return {"hypotheses":[]}
        with TemporaryDirectory() as temp:
            with patch("han_codebook.agent.analyze",side_effect=fake_analyze):
                with patch("han_codebook.agent.query_local_llm",side_effect=fake_code):
                    result=run_agent(case_data(),rounds=1,model="local-mock",
                        llm_url="http://127.0.0.1:11434",
                        db_path=str(Path(temp)/"audit.sqlite"),
                        adaptive_vocabulary=True,vocabulary_query=fake_vocab)
            self.assertEqual(len(calls),3)
            self.assertIn("新增詞",calls[1]["llm_dynamic_candidates"]["lexicon"])
            with sqlite3.connect(Path(temp)/"audit.sqlite") as db:
                rows=[(stage,json.loads(body)) for stage,body in db.execute(
                    "SELECT stage,payload_json FROM events WHERE stage IN "
                    "('vocabulary_rescore','rescore') ORDER BY id")]
            self.assertEqual(rows[0][0],"vocabulary_rescore")
            self.assertEqual(rows[0][1]["changed_count"],1)
            self.assertEqual(rows[0][1]["changes"]["999"],
                {"before":"原詞","after":"新增詞"})
            self.assertEqual(rows[1][0],"rescore")
            self.assertEqual(rows[1][1]["changed_count"],1)
            self.assertEqual(rows[1][1]["changes"]["999"],
                {"before":"原詞","after":"新增詞"})
            self.assertEqual(result["proposals"]["999"]["term"],"新增詞")

    def test_cancel_after_vocab_rescore_suppresses_next_code_model_call(self):
        flags={"cancelled":False,"code_calls":0,"steps":0}
        def fake_analyze(case,**kw):
            flags["steps"]+=1
            if flags["steps"]==2:flags["cancelled"]=True
            return mapping("原詞" if flags["steps"]==1 else "新增詞")
        def fake_vocab(url,model,packet,**kw):
            return {"vocabulary":[{"term":"新增詞","reason":"可疑活動"}]}
        def fake_code(url,model,packet,**kw):
            flags["code_calls"]+=1
            return {"hypotheses":[]}
        def cancel_check():
            if flags["cancelled"]:
                raise CaseError("job cancelled while rescoring")
        with TemporaryDirectory() as temp:
            with patch("han_codebook.agent.analyze",side_effect=fake_analyze):
                with patch("han_codebook.agent.query_local_llm",side_effect=fake_code):
                    with self.assertRaisesRegex(CaseError,"job cancelled"):
                        run_agent(case_data(),rounds=1,model="local-mock",
                            llm_url="http://127.0.0.1:11434",
                            db_path=str(Path(temp)/"audit.sqlite"),
                            adaptive_vocabulary=True,vocabulary_query=fake_vocab,
                            cancel_check=cancel_check)
        self.assertEqual(flags["steps"],2)
        self.assertEqual(flags["code_calls"],0)


if __name__=="__main__":unittest.main()
