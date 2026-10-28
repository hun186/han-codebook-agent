"""Round-by-round candidate discovery remains unverified and manual review is optional."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from han_codebook.agent import run_agent
from han_codebook.adaptive_vocabulary import vocabulary_packet, refresh_vocabulary
from han_codebook.core import CaseError

ROOT = Path(__file__).resolve().parents[1]


def sample():
    case = json.loads((ROOT / "examples" / "demo_case.json").read_text(encoding="utf-8"))
    case.pop("ground_truth", None)
    case["messages"] = case["messages"][:3]
    case["known_pairs"] = case["known_pairs"][:2]
    case["messages"].append({"id":"X-new", "codes":["999","013"],
                             "received_at":"1942-04-02",
                             "observations":[{"source":"目擊者A", "observed_at":"1942-04-02",
                                               "activity":"車隊移動", "confidence":0.6}]})
    return case


class AdaptiveVocabularyTest(unittest.TestCase):
    def config(self):
        return {"base_url":"http://127.0.0.1:11434",
                "model":"mock-private","timeout_seconds":30}

    def test_evidence_packet_is_bounded_unverified_and_metadata_ablatable(self):
        case=sample()
        unverified={"proposals":{"999":{"term":"推測詞","status":"hypothesis_unverified"},
                                "013":{"term":"可靠詞","status":"verified_alignment"}}}
        p=vocabulary_packet(case,round_number=2,metadata=True,current=unverified,
                            vocabulary={"既有詞"})
        self.assertEqual(p["round"],2)
        self.assertEqual(p["current_hypotheses_unverified"],[{"code":"999","candidate":"推測詞"}])
        self.assertEqual(p["verified_anchors"],[{"code":"013","term":"可靠詞"}])
        self.assertTrue(p["temporal_event_link_hypotheses"])
        self.assertTrue(p["messages"][0].get("sender"))
        quiet=vocabulary_packet(case,round_number=2,metadata=False,current=unverified,
                                vocabulary={"既有詞"})
        self.assertEqual(quiet["temporal_event_link_hypotheses"],[])
        self.assertNotIn("sender",quiet["messages"][0])
        self.assertNotIn("observations",quiet["messages"][-1])
        with self.assertRaises(CaseError):
            vocabulary_packet({**case,"ground_truth":{"999":"答案"}},
                              round_number=1,metadata=False,current=None,vocabulary=set())

    def test_every_round_new_candidates_and_auto_mode_isolation(self):
        case=sample()
        pristine=deepcopy(case)
        generated=[]
        def vocab_query(url,model,payload,**kw):
            self.assertEqual(payload["task"],"generate_vocabulary")
            self.assertNotIn("ground_truth",str(payload))
            round_number=payload["round"]
            generated.append(payload)
            return {"vocabulary":[{"term":"第"+str(round_number)+"輪新詞","reason":"輔助情報＋暫時推論"}],
                    "patterns":[]}
        def code_query(url,model,payload,**kw):
            self.assertTrue(payload["available_vocabulary"])
            return {"hypotheses":[{"code":"999","candidates":["第"+str(len(generated))+"輪新詞"],
                                   "reason":"待驗證跨報候選"}]}
        with TemporaryDirectory() as tmp, patch("han_codebook.agent.query_local_llm",side_effect=code_query):
            output=run_agent(case,rounds=2,llm_url=self.config()["base_url"],
                             model="mock-private",db_path=str(Path(tmp)/"audit.sqlite"),
                             metadata=True,vocabulary_query=vocab_query,
                             adaptive_vocabulary=True,solver_iterations=1,solver_restarts=1,
                             progress=lambda _:None)
            self.assertEqual(len(generated),2)
            self.assertEqual(output["dynamic_vocabulary_terms"],["第1輪新詞","第2輪新詞"])
            self.assertTrue(output["adaptive_vocabulary"])
            self.assertFalse(output["human_vocabulary_review"])
            self.assertEqual(case,pristine)
            with sqlite3.connect(Path(tmp)/"audit.sqlite") as db:
                records=[json.loads(row[0]) for row in db.execute(
                    "SELECT payload_json FROM events WHERE stage='vocabulary_candidates_unverified' ORDER BY id")]
                hypotheses=[json.loads(row[0]) for row in db.execute(
                    "SELECT payload_json FROM events WHERE stage='llm_proposals_unverified' ORDER BY id")]
            self.assertEqual(len(records),2)
            self.assertTrue(all(x["review_mode"]=="automatic" for x in records))
            self.assertEqual([r["approved"] for r in records],[["第1輪新詞"],["第2輪新詞"]])
            self.assertTrue(hypotheses[0]["accepted"])
            self.assertEqual(hypotheses[1]["accepted"][0]["candidates"],["第2輪新詞"])
            self.assertNotEqual(output["proposals"]["999"]["status"],"verified_alignment")

    def test_review_mode_may_reject_any_or_all_without_promoting_truth(self):
        case=sample()
        submitted=[]
        def fake(url,model,payload,**kw):
            return {"vocabulary":[{"term":"尚未證實", "reason":"可能詞"}]}
        def reviewer(round_number,candidates):
            submitted.append((round_number,candidates))
            return []
        updated,record=refresh_vocabulary(case,round_number=1,metadata=False,current=None,
                         llm_settings=self.config(),review=reviewer,query=fake)
        self.assertEqual(record["approved"],[])
        self.assertEqual(record["review_mode"],"human")
        self.assertEqual(case,updated)
        self.assertEqual(submitted[0][1][0]["status"],"unverified")
        with self.assertRaises(CaseError):
            refresh_vocabulary(case,round_number=1,metadata=False,current=None,
                llm_settings=self.config(),review=lambda _,__:["偽造核准"],query=fake)


if __name__=="__main__":
    unittest.main()
