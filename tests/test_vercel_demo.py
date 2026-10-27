"""Safety and consistency checks for the Vercel synthetic-only Mock PoC."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "vercel-demo"


class VercelMockPoCTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = json.loads((ROOT / "data/case.json").read_text(encoding="utf-8"))
        cls.gold = json.loads((ROOT / "data/gold.json").read_text(encoding="utf-8"))

    def test_same_case_across_10_25_50_100_and_no_oracle(self):
        messages = self.case["messages"]
        self.assertEqual(len(messages), 100)
        self.assertEqual(len({m["id"] for m in messages}), 100)
        self.assertTrue(all(m["codes"] and all(str(c).isdigit() for c in m["codes"]) for m in messages))
        self.assertNotIn("ground_truth", self.case)
        self.assertNotIn("codebook", self.case)
        self.assertNotIn("gold", self.case)
        for m in messages:
            self.assertTrue(set(m) <= {"id","codes","received_at","sender","recipient","observations"})
            for ob in m.get("observations", []):
                self.assertTrue(set(ob) <= {"source","observed_at","activity","destination","status","confidence","note"})
                self.assertNotIn("ground_truth", ob)

    def test_synthetic_gold_is_separate_and_consistent(self):
        self.assertEqual(self.gold.get("kind"), "PUBLIC_SYNTHETIC_GOLD")
        dictionary = self.gold["codebook"]
        for m in self.case["messages"]:
            self.assertEqual(self.gold["messages"][m["id"]], "".join(dictionary[c] for c in m["codes"]))

    def test_no_real_llm_calls_or_credentials_in_demo(self):
        script = (ROOT / "app.js").read_text(encoding="utf-8")
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("/v1/chat/completions", script + html)
        self.assertNotIn("192.168.", script + html)
        self.assertNotIn("api_key", script.lower())
        self.assertIn("MOCK LLM", html)
        self.assertIn("data-action=", html)
        self.assertIn('const list=()=>S.data.messages.slice(0,S.size)', script)

    def test_static_security_headers(self):
        cfg = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["version"], 2)
        headers = {h["key"]:h["value"] for rule in cfg["headers"] for h in rule["headers"]}
        self.assertIn("Content-Security-Policy", headers)
        self.assertIn("connect-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")


if __name__ == "__main__":
    unittest.main()
