"""User-facing investigation intake, event links and oracle-leak regression."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import unittest

from han_codebook.auto_vocabulary import make_vocabulary_packet
from han_codebook.candidate_ideas import normalize_ideas
from han_codebook.core import CaseError, analyze
from han_codebook.event_links import suggest_event_links
from han_codebook.hint_diagnostics import compare, evaluate_after_inference


ROOT = Path(__file__).resolve().parents[1]


def _case():
    return {
        "case_id": "human-workbench-synthetic",
        "messages": [
            {"id":"m1", "codes":["101","102","101"],"received_at":"1942-05-03T08:00:00",
             "sender":"補給處","observations":[
                 {"source":"目擊者", "observed_at":"1942-05-03","activity":"車輛出發",
                  "destination":"倉庫", "confidence":0.35, "status":"未確認關聯",
                  "unknown_extra":{"ground_truth":"不應使用"}}]},
            {"id":"m2","codes":["101","103","102"],"received_at":"1942-05-04T19:00:00",
             "recipient":"倉庫"},
            {"id":"m3","codes":["103","101"],"received_at":"1942-05-19"}],
        "profiles":{"general":{"keywords":["車隊"],"lexicon":{"車隊":3,"出發":2,"倉庫":1},
                              "sentences":[["車隊","出發"],["車隊","倉庫"]]}},
        "known_pairs":[],
    }


class HumanWorkbenchTests(unittest.TestCase):
    def test_temporal_candidates_retain_unrelated_alternative(self):
        events=suggest_event_links(_case())
        self.assertEqual(len(events),1)
        options=events[0]["candidates"]
        self.assertTrue(any(v["message_id"] is None for v in options))
        self.assertTrue(any(v["message_id"]=="m1" for v in options))
        self.assertFalse(any(v["message_id"]=="m3" for v in options))
        self.assertEqual(events[0]["association_status"],"hypotheses_only")

    def test_unrelated_sighting_not_a_hidden_anchor(self):
        case=_case()
        case["messages"][0]["observations"][0]["status"]="已排除關聯"
        options=suggest_event_links(case)[0]["candidates"]
        self.assertEqual(len(options),1)
        self.assertIsNone(options[0]["message_id"])

    def test_nested_oracle_cannot_enter_solver_as_metadata(self):
        case=_case()
        case["messages"][0]["observations"][0]["activity"]={"ground_truth":"車隊"}
        with self.assertRaises(CaseError):
            analyze(case,iterations=1,restarts=1)
        with self.assertRaises(CaseError):
            make_vocabulary_packet(case,metadata=True)
        # Unknown nested archival fields can exist; they must never be sent.
        case=_case()
        packet=make_vocabulary_packet(case,metadata=True)
        self.assertNotIn("ground_truth",json.dumps(packet,ensure_ascii=False))
        self.assertNotIn("unknown_extra",json.dumps(packet,ensure_ascii=False))

    def test_reversible_idea_bank_has_multiple_hypotheses(self):
        case=_case()
        case["candidate_ideas"]={"101":[
            {"term":"清晨","source":"researcher","status":"suggested","note":"可能的時間詞"},
            {"term":"車隊","source":"llm","status":"shortlisted","note":"待覆核"},
            {"term":"橋梁","source":"observation","status":"rejected","note":"已否定此想法"}]}
        normalized=normalize_ideas(case)
        self.assertEqual(len(normalized["101"]),3)
        result=analyze(case,iterations=1,restarts=1)
        self.assertIn("101",result["proposals"])
        # No idea may upgrade a code to a verified anchor.
        self.assertEqual(result["proposals"]["101"]["status"],"hypothesis_unverified")
        invalid=deepcopy(case)
        invalid["candidate_ideas"]["101"][0]["status"]="verified"
        with self.assertRaises(CaseError):
            normalize_ideas(invalid)

    def test_wrong_case_gold_rejected_before_accuracy(self):
        case=_case()
        report=compare(case,{"hypotheses":[]},iterations=1,restarts=1,observation_ablation=False)
        gold={"case_id":"other-dictionary","codebook":{c:"車隊" for c in ("101","102","103")}}
        with self.assertRaises(CaseError):
            evaluate_after_inference(report,gold)

    def test_same_calendar_day_precision_is_symmetric(self):
        from han_codebook.core import _observation_relevance
        sight={"status":"已確認觀察","observed_at":"1942-05-03T23:00:00+08:00"}
        m={"received_at":"1942-05-03"}
        self.assertEqual(_observation_relevance(m,sight),1.0)
        self.assertEqual(_observation_relevance({"received_at":sight["observed_at"]},
                                                {"status":"已確認觀察","observed_at":"1942-05-03"}),1.0)

    def test_webpage_exposes_new_intake_and_proposal_actions(self):
        source=(ROOT/"src"/"han_codebook"/"static"/"index.html").read_text(encoding="utf-8")
        for identifier in ('newCase','addMessage','askVocabulary','checkEvents','addIdea',
                           'undoIdea','redoIdea','importLLMIdeas'):
            self.assertIn('id="'+identifier+'"',source)
        self.assertIn("function presentCase()",source)
        # Syntax compile, without executing browser functionality or making LLM calls.
        code=source.split("<script>")[-1].split("</script>")[0]
        try:
            completed=subprocess.run(["node","--check","-"],input=code,text=True,
                                      capture_output=True,timeout=6)
        except FileNotFoundError:
            return  # The GitHub Python-only matrix may not provide Node.
        self.assertEqual(completed.returncode,0,completed.stderr)


if __name__=="__main__":
    unittest.main()
