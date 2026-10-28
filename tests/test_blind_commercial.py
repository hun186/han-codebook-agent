"""Safety, independence and original-agent end-to-end test WITHOUT network/API billing."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"benchmarks"/"blind_commercial"))
sys.path.insert(0,str(ROOT/"src"))
from generate import generate, digest
from run import run_experiment
from score import score,score_case
from han_codebook.adaptive_vocabulary import vocabulary_packet

class BlindExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base=Path(self.temp.name)
        self.public=base/"public"
        self.private=base/"separate_sealed"
        self.output=base/"results"
        self.manifest=generate(self.public,self.private,repeats=1,fixture_seed=925313)

    def test_no_fixed_roles_or_plaintext_leakage(self):
        public=json.loads((self.public/"blind_01.json").read_text(encoding="utf-8"))
        gold=json.loads((self.private/"blind_01.gold.json").read_text(encoding="utf-8"))
        self.assertEqual(len(public["messages"]),100)
        self.assertEqual(len(public["known_pairs"]),0)
        self.assertTrue(len(set(len(m["codes"]) for m in public["messages"]))>=4)
        codes={c for m in public["messages"] for c in m["codes"]}
        self.assertEqual(codes,set(gold["code_to_word"]))
        self.assertEqual(digest(public),gold["public_sha256"])
        self.assertFalse(any(
            c in public["profiles"]["neutral"]["lexicon"]
            for c in codes))
        for flag in ("code_to_word","plaintext_segments","ground_truth","gold","word_to_code",
                     "code_roles","fixed_position"):
            self.assertNotIn(flag,json.dumps(public,ensure_ascii=False))
        self.assertTrue(sum(len(m["observations"]) for m in public["messages"])>30)
        self.assertTrue(all(set(msg["observations"][0]).isdisjoint({"is_relevant","gold","plaintext"})
                 for msg in public["messages"] if msg["observations"]))
        p=vocabulary_packet(public,round_number=2,metadata=True,current=None,
                           vocabulary=set(public["profiles"]["neutral"]["lexicon"]))
        self.assertEqual(len(p["messages"]),100,"All 100 must reach vocabulary LLM")
        self.assertTrue("verified_anchors" in p)
        self.assertEqual(p["verified_anchors"],[])
        self.assertEqual(len(p["corpus_statistics"]["code_frequencies"])>0,True)

    def test_real_openai_forbidden_for_seeded_test(self):
        def never(_):raise AssertionError("Should not send a cloud API call")
        with self.assertRaisesRegex(ValueError,"known-seed"):
            run_experiment(self.public,self.output,model="gpt-6-astra",
                           effort="high",rounds=1,max_calls=16,timeout=5,
                           provider=never,real_api=True,solver_iterations=1,solver_restarts=1)

    def test_mock_transport_executes_same_real_agent_but_must_not_be_scored(self):
        seen=[]
        def local_fake(chat):
            body=json.loads(chat["messages"][1]["content"])
            seen.append(body)
            if body.get("task")=="generate_vocabulary":
                answer={"vocabulary":[{"term":"燃料","reason":"TEST DOUBLE, not GPT-6"},
                                      {"term":"臨時集結點","reason":"TEST DOUBLE"}],
                        "patterns":[]}
            else:
                words=body.get("available_vocabulary",[])
                guesses=[]
                for code in list(body.get("unresolved",{}))[:5]:
                    guesses.append({"code":code,"candidates":words[:1],
                                    "reason":"TEST DOUBLE, not a model"})
                answer={"hypotheses":guesses}
            return {"choices":[{"message":{"content":json.dumps(answer,ensure_ascii=False)}}],
                    "usage":{"prompt_tokens":0,"completion_tokens":0}}
        result=run_experiment(self.public,self.output,model="gpt-6-astra",
                    effort="high",rounds=1,max_calls=16,timeout=30,
                    provider=local_fake,solver_iterations=1,solver_restarts=1,
                    real_api=False)
        self.assertEqual(result["kind"],"TEST_DOUBLE_SMOKE_NOT_SCORED")
        self.assertEqual(result["provider"],"TEST_DOUBLE")
        self.assertEqual(result["n_model_calls"],16)
        self.assertEqual(result["n_experiments"],8)
        self.assertEqual(len(seen),16)
        self.assertEqual(len([v for v in seen if v.get("task")=="generate_vocabulary"]),8)
        self.assertEqual(len([v for v in seen if v.get("task")!="generate_vocabulary"]),8)
        # All messages (not the legacy first 50) flow through both LLM phases.
        self.assertEqual(sum(len(v.get("messages",[]))==100 for v in seen),4)
        # Both 100-message branches each have vocab + code call.
        self.assertEqual(len([v for v in seen if len(v.get("messages",[]))==100]),4)
        self.assertEqual(sorted(set(x["n_messages"] for x in result["cases"])),[10,25,50,100])
        self.assertEqual(sorted(set(x["condition"] for x in result["cases"])),
                         ["with_aux","without_aux"])
        for r in result["cases"]:
            self.assertFalse(r["mapping"]=={})
            with sqlite3.connect(self.output/r["audit_sqlite"]) as db:
                stages=[row[0] for row in db.execute("SELECT stage FROM events")]
            self.assertEqual(stages.count("vocabulary_llm_request"),1)
            self.assertEqual(stages.count("llm_request"),1)
            self.assertIn("rescore",stages)
            self.assertIn("vocabulary_rescore",stages)
        self.assertEqual(len((self.output/"predictions_LOCKED.sha256").read_text().strip()),64)
        with self.assertRaisesRegex(ValueError,"real LLM"):
            score(self.private,self.public,self.output)

    def test_score_is_exact_and_repeatable_without_shortcuts(self):
        public=json.loads((self.public/"blind_01.json").read_text(encoding="utf-8"))
        gold=json.loads((self.private/"blind_01.gold.json").read_text(encoding="utf-8"))
        n=10
        codes={c for m in public["messages"][:n] for c in m["codes"]}
        correct={c:gold["code_to_word"][c] for c in codes}
        run={"study":"blind_01","n_messages":10,"condition":"with_aux","rounds":3,
             "public_sha256":gold["public_sha256"],
             "mapping":correct,"alternatives":{c:[word] for c,word in correct.items()},
             "dynamic_vocabulary_terms":list(correct.values()),
             "model":"unit-test","reasoning_effort":"none","seconds":0}
        result=score_case(public,gold,run)
        self.assertEqual(result["type_top1"],1.0)
        self.assertEqual(result["position_accuracy"],1.0)
        self.assertEqual(result["complete_messages"],10)
        self.assertEqual(result["lexicon_coverage"],1.0)
        bad=dict(run)
        bad["mapping"]={c:"[未解]" for c in correct}
        x=score_case(public,gold,bad)
        self.assertEqual(x["correct_types"],0)
        self.assertEqual(x["complete_messages"],0)
        self.assertEqual(x["unresolved"],len(codes))

if __name__=="__main__":
    unittest.main()
