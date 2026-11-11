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
            if kw.get("on_exchange"):
                kw["on_exchange"]("llm_request",{"body":{"phase":"vocabulary", "round":round_number}})
                kw["on_exchange"]("llm_response",{"response":"vocabulary round "+str(round_number)})
            return {"vocabulary":[{"term":"第"+str(round_number)+"輪新詞","reason":"輔助情報＋暫時推論",
                                   "evidence_message_ids":["X-new"],
                                   "target_code":"999",
                                   "contrasted_candidate":next(
                                       x["candidate"] for x in payload["current_hypotheses_unverified"]
                                       if x["code"] == "999"),
                                   "contrast_reason":"現有候選不能解釋重複碼組"}],
                    "patterns":[]}
        def code_query(url,model,payload,**kw):
            self.assertTrue(payload["available_vocabulary"])
            if kw.get("on_exchange"):
                kw["on_exchange"]("llm_request",{"body":{"phase":"code", "round":len(generated)}})
                kw["on_exchange"]("llm_response",{"response":"code round "+str(len(generated))})
            return {"hypotheses":[{"code":"999","candidates":["第"+str(len(generated))+"輪新詞"],
                                   "reason":"待驗證跨報候選"}]}
        with TemporaryDirectory() as tmp, patch("han_codebook.agent.query_local_llm",side_effect=code_query):
            output=run_agent(case,rounds=2,llm_url=self.config()["base_url"],
                             model="mock-private",db_path=str(Path(tmp)/"audit.sqlite"),
                             metadata=True,vocabulary_query=vocab_query,
                             adaptive_vocabulary=True,capture_llm_io=True,
                             solver_iterations=1,solver_restarts=1,
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
                traces=[(stage,json.loads(payload)) for stage,payload in db.execute(
                    "SELECT stage, payload_json FROM events WHERE stage IN "
                    "('vocabulary_llm_request','vocabulary_llm_response','llm_request','llm_response') "
                    "ORDER BY id")]
            self.assertEqual(len(records),2)
            self.assertEqual([x[0] for x in traces],[
                'vocabulary_llm_request','vocabulary_llm_response','llm_request','llm_response',
                'vocabulary_llm_request','vocabulary_llm_response','llm_request','llm_response'])
            self.assertEqual(traces[1][1]['response'],'vocabulary round 1')
            self.assertEqual(traces[3][1]['response'],'code round 1')
            self.assertTrue(all(x["review_mode"]=="automatic" for x in records))
            self.assertEqual([r["approved"] for r in records],[["第1輪新詞"],["第2輪新詞"]])
            self.assertTrue(hypotheses[0]["accepted"])
            self.assertEqual(hypotheses[1]["accepted"][0]["candidates"],["第2輪新詞"])
            self.assertNotEqual(output["proposals"]["999"]["status"],"verified_alignment")

    def test_reasoning_only_third_vocabulary_preserves_previous_rounds(self):
        """Malformed optional vocab JSON is audited; code inference still runs."""
        case = sample()
        original = deepcopy(case)
        attempted_vocab_rounds, code_rounds, progress = [], [], []

        def vocabulary(url, model, packet, **kw):
            round_number = packet["round"]
            attempted_vocab_rounds.append(round_number)
            if round_number == 3:
                if kw.get("on_metrics"):
                    kw["on_metrics"]({
                        "provider": "local", "status": "invalid_json",
                        "json_complete": False, "finish_reason": "stop",
                        "prompt_tokens": 2186, "completion_tokens": 2799,
                        "total_tokens": 4985,
                    })
                raise CaseError(
                    "LLM output not valid expected JSON: empty final content "
                    "(reasoning_only=True, finish_reason=stop, completion_tokens=2799)"
                )
            prior = next(x["candidate"] for x in packet["current_hypotheses_unverified"]
                         if x["code"] == "999")
            return {"vocabulary": [{
                "term": f"第{round_number}輪新詞",
                "reason": "虛構測試資料，未驗證",
                "evidence_message_ids": ["X-new"], "target_code": "999",
                "contrasted_candidate": prior,
                "contrast_reason": "用於離線測試候選詞"
            }], "patterns": []}

        def code(url, model, packet, **kw):
            round_no = packet["round_context"]["round"]
            code_rounds.append(round_no)
            return {"hypotheses": [{
                "code": "999", "candidates": ["第1輪新詞"],
                "reason": "僅供測試，未驗證"
            }]}

        with TemporaryDirectory() as tmp, \
             patch("han_codebook.agent.query_local_llm", side_effect=code):
            db = Path(tmp) / "audit.sqlite"
            result = run_agent(
                case, rounds=3, llm_url=self.config()["base_url"],
                model="mock-private", db_path=str(db), metadata=True,
                vocabulary_query=vocabulary, adaptive_vocabulary=True,
                capture_llm_io=False, solver_iterations=1, solver_restarts=1,
                progress=progress.append)
            with sqlite3.connect(db) as conn:
                failures = [json.loads(item[0]) for item in conn.execute(
                    "SELECT payload_json FROM events WHERE stage='vocabulary_generation_failed'")]
                proposals = [json.loads(item[0]) for item in conn.execute(
                    "SELECT payload_json FROM events WHERE stage='llm_proposals_unverified'")]
                success_terms = [json.loads(item[0]) for item in conn.execute(
                    "SELECT payload_json FROM events WHERE stage='vocabulary_candidates_unverified'")]

        self.assertEqual(attempted_vocab_rounds, [1, 2, 3])
        self.assertEqual(code_rounds, [1, 2, 3])
        self.assertEqual(len(success_terms), 2)
        self.assertEqual(len(proposals), 3)
        self.assertEqual(result["agent_rounds_completed"], 3)
        self.assertEqual(result["dynamic_vocabulary_terms"], ["第1輪新詞", "第2輪新詞"])
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["reason"], "unusable_final_json")
        self.assertTrue(failures[0]["no_automatic_retry"])
        self.assertTrue(failures[0]["code_inference_continues"])
        self.assertNotIn("content", failures[0])
        policy = result["vocabulary_generation_policy"]
        self.assertEqual(policy["vocabulary_failed_rounds"], [3])
        self.assertEqual(policy["vocabulary_llm_calls"], 2)
        self.assertEqual(policy["vocabulary_attempted_calls"], 3)
        self.assertTrue(policy["partial_vocabulary_failure"])
        self.assertTrue(any("proceeding to code analysis" in line for line in progress))
        self.assertEqual(case, original)

    def test_vocab_network_error_never_silently_skips(self):
        def network_failure(*args, **kwargs):
            raise CaseError("LLM network error: disconnected")
        with TemporaryDirectory() as tmp, \
             patch("han_codebook.agent.query_local_llm") as code:
            with self.assertRaisesRegex(CaseError, "LLM network error"):
                run_agent(sample(), rounds=1, llm_url=self.config()["base_url"],
                          model="mock-private", db_path=str(Path(tmp)/"audit.sqlite"),
                          vocabulary_query=network_failure, adaptive_vocabulary=True,
                          solver_iterations=1, solver_restarts=1,
                          progress=lambda _: None)
            code.assert_not_called()

    def test_human_review_vocab_format_error_remains_fatal(self):
        def output_failure(*args, **kwargs):
            raise CaseError("LLM output not valid expected JSON: empty final content")
        with TemporaryDirectory() as tmp, \
             patch("han_codebook.agent.query_local_llm") as code:
            with self.assertRaisesRegex(CaseError, "empty final content"):
                run_agent(sample(), rounds=1, llm_url=self.config()["base_url"],
                          model="mock-private", db_path=str(Path(tmp)/"audit.sqlite"),
                          vocabulary_query=output_failure, adaptive_vocabulary=True,
                          vocabulary_reviewer=lambda _round, proposals: [],
                          solver_iterations=1, solver_restarts=1,
                          progress=lambda _: None)
            code.assert_not_called()

    def test_researcher_custom_terms_enter_next_round_and_are_audited(self):
        case=sample()
        original=deepcopy(case)
        def fake(url,model,payload,**kw):
            return {"vocabulary":[{"term":"模型候選詞","reason":"側面情報"}]}
        updated,record=refresh_vocabulary(
            case,round_number=1,metadata=True,current=None,
            llm_settings=self.config(),query=fake,
            review=lambda round_number,candidates:{
                "approved":[],"added":["研究員觀察","新增軍事詞"]})
        self.assertEqual(case,original)
        self.assertEqual(record["review_mode"],"human")
        self.assertEqual(record["approved"],["研究員觀察","新增軍事詞"])
        self.assertEqual(record["rejected_count"],1)
        self.assertEqual(
            [x["term"] for x in record["researcher_added"]],
            ["研究員觀察","新增軍事詞"])
        self.assertTrue(all(x["status"]=="unverified" for x in record["researcher_added"]))
        self.assertEqual(
            updated["profiles"]["llm_dynamic_candidates"]["lexicon"]["研究員觀察"],1.0)
        packet=vocabulary_packet(updated,round_number=2,metadata=True,current=None,
                                  vocabulary={"研究員觀察","新增軍事詞"})
        self.assertIn("研究員觀察",packet["current_vocabulary"])
        # The inference model sees these words as vocabulary, not verified mapping.
        self.assertEqual(packet["verified_anchors"],[])
        self.assertNotIn("ground_truth",str(packet))

    def test_custom_word_limits_and_selection_is_atomic(self):
        case=sample()
        before=deepcopy(case)
        def fake(url,model,payload,**kw):
            return {"vocabulary":[{"term":"模型詞","reason":"LLM"}]}
        for addition in (["模型詞"],["既有詞","既有詞"],[""],["    "],
                         ["詞"*25],["\u0001詞"],["過量"+str(i) for i in range(33)]):
            with self.subTest(addition=addition),self.assertRaises(CaseError):
                refresh_vocabulary(case,round_number=1,metadata=False,
                    current=None,llm_settings=self.config(),query=fake,
                    review=lambda n,items,addition=addition:{
                        "approved":[],"added":addition})
            self.assertEqual(case,before)
        with self.assertRaises(CaseError):
            refresh_vocabulary(case,round_number=1,metadata=False,
                current=None,llm_settings=self.config(),query=fake,
                review=lambda n,items:{
                    "approved":["模型詞"],"added":["模型詞"]})
        with self.assertRaises(CaseError):
            refresh_vocabulary(case,round_number=1,metadata=False,
                current=None,llm_settings=self.config(),query=fake,
                review=lambda n,items:{"approved":["模型詞"],"added":[
                    "人工"+str(i) for i in range(32)]})
        self.assertEqual(case,before)

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
