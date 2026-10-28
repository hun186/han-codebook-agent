"""No-network contract tests for subscription Codex CLI bridge.

All tests use synthetic JSONL from an injected fake subprocess; they do
NOT charge or exercise anyone's ChatGPT plan and are not benchmark results.
"""
from __future__ import annotations
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"benchmarks"/"blind_commercial"))
from codex_subscription import (check_codex_subscription, QuotaExhausted,
                                codex_subscription_reply,schema_for)


class CodexSubscriptionBridgeTests(unittest.TestCase):
    def setUp(self):
        td=tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.auth_home=Path(td.name)
        (self.auth_home/"auth.json").write_text(json.dumps({
            "auth_mode":"chatgpt","OPENAI_API_KEY":None,
            "tokens":{"access_token":"TEST_ONLY_FAKE_VALUE"}}),encoding="utf-8")
        self.clean=patch.dict(os.environ,{
          "OPENAI_API_KEY":"","CODEX_API_KEY":"","CODEX_ACCESS_TOKEN":"",
          "CODEX_HOME":str(self.auth_home)})
        self.clean.start()
        self.addCleanup(self.clean.stop)

    def test_requires_chatgpt_oauth_not_api_billing(self):
        def mock(argv,**kwargs):
            self.assertEqual(argv,["codex", "-c",'forced_login_method="chatgpt"',
                "-c",'cli_auth_credentials_store="file"',"login","status"])
            return SimpleNamespace(returncode=0,stdout="Logged in using ChatGPT",stderr="")
        check_codex_subscription(subprocess_run=mock)
        def api_key(argv,**kwargs):
            return SimpleNamespace(returncode=0,stdout="Logged in using API key",stderr="")
        with self.assertRaisesRegex(RuntimeError,"ChatGPT subscription"):
            check_codex_subscription(subprocess_run=api_key)
        with patch.dict(os.environ,{"OPENAI_API_KEY":"fake_test_value"}):
            with self.assertRaisesRegex(RuntimeError,"refuses API keys"):
                check_codex_subscription(subprocess_run=mock)

    def test_response_preserves_tokens_and_readonly_boundary(self):
        seen=[]
        def run(argv,**kwargs):
            seen.append((argv,kwargs))
            self.assertEqual(argv[:2],["codex","exec"])
            self.assertIn("--ephemeral",argv)
            self.assertIn('forced_login_method="chatgpt"',argv)
            self.assertEqual(kwargs.get("encoding"),"utf-8")
            self.assertIn("--ignore-user-config",argv)
            self.assertIn("--sandbox",argv)
            self.assertEqual(argv[argv.index("--sandbox")+1],"read-only")
            self.assertEqual(argv[argv.index("--model")+1],"gpt-6-astra")
            self.assertIn('model_reasoning_effort="high"',argv)
            self.assertEqual(argv[-1],"-")
            self.assertNotIn("OPENAI_API_KEY",kwargs["env"])
            self.assertTrue(Path(kwargs["cwd"]).is_dir())
            self.assertNotEqual(Path(kwargs["cwd"]).resolve(),ROOT.resolve())
            self.assertIn("[UNTRUSTED_EVIDENCE_JSON]",kwargs["input"])
            schema=json.loads(Path(argv[argv.index("--output-schema")+1]).read_text())
            self.assertEqual(schema["type"],"object")
            kind="vocabulary" if '"task": "generate_vocabulary"' in kwargs["input"] else "hypotheses"
            answer=({"vocabulary":[{"term":"道路","reason":"上下文共現"}],"patterns":[]}
                    if kind=="vocabulary" else
                    {"hypotheses":[{"code":"4331","candidates":["道路"],"reason":"交叉觀察"}]})
            Path(argv[argv.index("--output-last-message")+1]).write_text(
                json.dumps(answer,ensure_ascii=False),encoding="utf-8")
            events=[
                {"type":"thread.started","thread_id":"TEST-ONLY"},
                {"type":"turn.started"},
                {"type":"item.completed","item":{"id":"i1","type":"agent_message",
                                                  "text":json.dumps(answer,ensure_ascii=False)}},
                {"type":"turn.completed","usage":{"input_tokens":410,
                        "cached_input_tokens":12,"output_tokens":120,
                        "reasoning_output_tokens":70}},
            ]
            return SimpleNamespace(returncode=0,stdout="\n".join(
                    json.dumps(x,ensure_ascii=False) for x in events)+"\n",stderr="")
        sys_instruction="請根據未驗證資料提出候選詞"
        for payload in [
           {"task":"generate_vocabulary","messages":[{"codes":["4331"]}]},
           {"policy":"候選未證實","unresolved":{"4331":{}}}
        ]:
            chat={"messages":[{"role":"system","content":sys_instruction},
                              {"role":"user","content":json.dumps(payload,ensure_ascii=False)}]}
            reply=codex_subscription_reply(chat,subprocess_run=run)
            self.assertEqual(reply["model"],"gpt-6-astra")
            self.assertEqual(reply["provider"],"CODEX_CLI_CHATGPT_PLAN")
            self.assertEqual(reply["usage"]["prompt_tokens"],410)
            self.assertEqual(reply["usage"]["cached_input_tokens"],12)
            self.assertEqual(reply["usage"]["completion_tokens"],120)
            self.assertEqual(reply["usage"]["reasoning_tokens"],70)
            self.assertEqual(reply["model_identity_basis"],
                         "--model CLI option; no independent upstream model ID")
            json.loads(reply["choices"][0]["message"]["content"])
        self.assertEqual(len(seen),2)
        with patch.dict(os.environ,{"CODEX_HOME":""}):
            with self.assertRaisesRegex(RuntimeError,"dedicated"):
                check_codex_subscription(subprocess_run=lambda *a,**k:None)

    def test_tool_invocations_and_failed_turns_are_not_valid_baseline(self):
        response={"vocabulary":[],"patterns":[]}
        events=[
           {"type":"item.completed","item":{"type":"command_execution",
                                             "command":"ls","status":"completed"}},
           {"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":20}}
        ]
        def mock(argv,**kwargs):
            Path(argv[argv.index("--output-last-message")+1]).write_text(
                json.dumps(response),encoding="utf-8")
            return SimpleNamespace(returncode=0,stdout="\n".join(
                json.dumps(x) for x in events),stderr="")
        chat={"messages":[{"role":"system","content":"候選無法驗證"},
              {"role":"user","content":json.dumps({"task":"generate_vocabulary"})}]}
        with self.assertRaisesRegex(RuntimeError,"tool-free turn"):
            codex_subscription_reply(chat,subprocess_run=mock)
        events[0]={"type":"turn.failed"}
        with self.assertRaisesRegex(RuntimeError,"tool-free turn"):
            codex_subscription_reply(chat,subprocess_run=mock)

    def test_quota_pause_and_model_tool_rejection(self):
        chat={"messages":[{"role":"system","content":"Only JSON"},
                          {"role":"user","content":json.dumps({"task":"generate_vocabulary"})}]}
        def quota(argv,**kwargs):
            return SimpleNamespace(returncode=1,stdout="",stderr="Your usage limit has been reached")
        with self.assertRaises(QuotaExhausted):
            codex_subscription_reply(chat,subprocess_run=quota)
        events=[
            {"type":"item.completed","item":{"type":"collab_tool_call","tool":"spawn_agent"}},
            {"type":"turn.completed","usage":{"input_tokens":100,"output_tokens":20}}
        ]
        def tool(argv,**kwargs):
            Path(argv[argv.index("--output-last-message")+1]).write_text(
                json.dumps({"vocabulary":[],"patterns":[]}),encoding="utf-8")
            return SimpleNamespace(returncode=0,stdout="\n".join(json.dumps(x) for x in events),stderr="")
        with self.assertRaisesRegex(RuntimeError,"tool-free turn"):
            codex_subscription_reply(chat,subprocess_run=tool)
        events[0]={"type":"item.completed","item":{"type":"error","message":"Partial failure"}}
        with self.assertRaisesRegex(RuntimeError,"tool-free turn"):
            codex_subscription_reply(chat,subprocess_run=tool)
        events[:]=[{"type":"turn.failed","error":{"message":"usage limit reached"}}]
        with self.assertRaises(QuotaExhausted):
            codex_subscription_reply(chat,subprocess_run=tool)

    def test_schema_and_auth_fail_closed(self):
        with self.assertRaises(ValueError):
            schema_for("other")
        with self.assertRaises(ValueError):
            codex_subscription_reply({"messages":[]})
        with patch.dict(os.environ,{"CODEX_API_KEY":"fake_test_key"}):
            chat={"messages":[{"role":"system","content":"x"},
                              {"role":"user","content":"{}"}]}
            with self.assertRaisesRegex(RuntimeError,"no API credentials"):
                codex_subscription_reply(chat,
                    subprocess_run=lambda *args,**kw:None)


if __name__=="__main__":
    unittest.main()
