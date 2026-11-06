"""Offline DeepInfra cache, catalog and refusal checks; never contacts a paid API."""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from han_codebook.agent import DEEPINFRA_BASE_URL, query_local_llm, summarize_llm_api_metrics
from han_codebook.core import CaseError
from han_codebook.model_catalog import (PREFERRED_MODEL, FALLBACK_MODEL,
                                        fetch_deepinfra_models)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def read(self, limit):
        return self.payload[:limit]


class FakeOpener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
    def open(self, req, timeout):
        self.calls.append(req)
        return FakeResponse(self.responses.pop(0))


class CacheAndModelCatalogTests(unittest.TestCase):
    def test_stable_prefix_and_hashed_cache_key_with_changing_batch(self):
        answer = {
            "choices": [{"finish_reason": "stop", "message": {"content": '{"hypotheses":[]}'}}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 5, "total_tokens": 205,
                      "prompt_tokens_details": {"cached_tokens": 160}},
        }
        opener = FakeOpener(answer, answer)
        evidence = {
            "policy": "unchanged research procedure",
            "available_vocabulary": ["補給", "交接"],
            "profiles": {"general": {"keywords": ["觀察"]}},
            "messages": [{"id": "M1", "codes": ["001"]}],
            "batch": {"round": 1},
        }
        metrics = []
        with patch.dict(os.environ, {"DEEPINFRA_API_KEY": "synthetic_fixture"}), \
             patch("han_codebook.agent.request.build_opener", return_value=opener):
            query_local_llm(DEEPINFRA_BASE_URL, PREFERRED_MODEL, evidence,
                            provider="deepinfra", allow_external_api=True,
                            on_metrics=metrics.append)
            query_local_llm(DEEPINFRA_BASE_URL, PREFERRED_MODEL, {
                **evidence, "messages": [{"id": "M2", "codes": ["002"]}],
                "batch": {"round": 2},
            }, provider="deepinfra", allow_external_api=True,
                on_metrics=metrics.append)
        self.assertEqual(len(opener.calls), 2)
        a, b = [json.loads(req.data) for req in opener.calls]
        self.assertEqual(a["prompt_cache_key"], b["prompt_cache_key"])
        self.assertTrue(a["prompt_cache_key"].startswith("han-codebook-v1-"))
        self.assertEqual(a["messages"][:2], b["messages"][:2])
        self.assertNotEqual(a["messages"][2], b["messages"][2])
        self.assertNotIn("M1", a["prompt_cache_key"])
        self.assertNotIn("M2", a["prompt_cache_key"])
        self.assertEqual(a["messages"][1]["role"], "user")
        self.assertNotIn("batch", a["messages"][1]["content"])
        self.assertEqual([m["cached_tokens"] for m in metrics], [160, 160])
        summary = summarize_llm_api_metrics(metrics)
        self.assertEqual(summary["cache_hit_rate"], 0.8)
        self.assertEqual(summary["cached_prompt_tokens_reported"], 320)
        self.assertIsNone(summary["cache_savings_usd_estimated"])

    def test_missing_cache_usage_is_not_a_zero_hit(self):
        rows = [{"attempt": 1, "json_complete": True, "prompt_tokens": 50,
                 "completion_tokens": 20, "total_tokens": 70}]
        result = summarize_llm_api_metrics(rows)
        self.assertEqual(result["cache_reported_attempts"], 0)
        self.assertIsNone(result["cache_hit_rate"])
        self.assertEqual(summarize_llm_api_metrics([])["cache_reported_attempts"], 0)

    def test_catalog_reads_fixed_route_without_chat_or_prompt(self):
        opener = FakeOpener({"data": [
            {"id": "random/Compatible-Model"},
            {"id": FALLBACK_MODEL},
            {"id": PREFERRED_MODEL},
            {"id": "wrong model with spaces"},
            {"id": PREFERRED_MODEL},
        ]})
        with patch.dict(os.environ, {"DEEPINFRA_API_KEY": "synthetic_fixture"}), \
             patch("han_codebook.model_catalog._urlopen_llm", side_effect=lambda req, **kwargs: opener.open(req, 12)):
            got = fetch_deepinfra_models()
        self.assertEqual(got["models"], [PREFERRED_MODEL, FALLBACK_MODEL, "random/Compatible-Model"])
        self.assertEqual(got["preferred_model"], PREFERRED_MODEL)
        self.assertEqual(got["count"], 3)
        self.assertNotIn("synthetic_fixture", json.dumps(got))
        req = opener.calls[0]
        self.assertEqual(req.full_url, DEEPINFRA_BASE_URL + "/models")
        self.assertEqual(req.get_method(), "GET")
        self.assertIsNone(req.data)

    def test_catalog_fallback_and_fail_closed(self):
        with patch.dict(os.environ, {"DEEPINFRA_API_KEY": ""}), \
             patch("han_codebook.model_catalog._urlopen_llm") as remote:
            with self.assertRaises(CaseError):
                fetch_deepinfra_models()
            remote.assert_not_called()
        with patch.dict(os.environ, {"DEEPINFRA_API_KEY": "synthetic_fixture"}), \
             patch("han_codebook.model_catalog._urlopen_llm",
                   return_value=FakeResponse({"data": [{"id": FALLBACK_MODEL}]})):
            got = fetch_deepinfra_models()
        self.assertEqual(got["preferred_model"], FALLBACK_MODEL)
        with patch.dict(os.environ, {"DEEPINFRA_API_KEY": "synthetic_fixture"}), \
             patch("han_codebook.model_catalog._urlopen_llm",
                   return_value=FakeResponse(b"<html>not json</html>")):
            with self.assertRaises(CaseError):
                fetch_deepinfra_models()


if __name__ == "__main__":
    unittest.main()
