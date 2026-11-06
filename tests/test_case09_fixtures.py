"""Case 09: 3-digit progressive corpus schema and gold separation."""
from __future__ import annotations
import json
import unittest
from pathlib import Path
from han_codebook.core import load_case, anchors_and_review

BASE = Path(__file__).resolve().parents[1] / "benchmarks"

class Case09FixturesTests(unittest.TestCase):
    def test_three_digit_nested_cases(self):
        suite = json.loads((BASE / "suite_case09.json").read_text(encoding="utf-8"))
        self.assertEqual(len(suite["cases"]), 8)
        for item in suite["cases"]:
            case = load_case(BASE / item["case"])
            gold = json.loads((BASE / item["gold"]).read_text(encoding="utf-8"))
            n = int(item["id"].split("_")[2])
            intercepts = [m for m in case["messages"] if m["id"].startswith("INT")]
            self.assertEqual(len(intercepts), n)
            self.assertTrue(all(len(m["codes"]) == 24 for m in intercepts))
            self.assertTrue(all(len(code) == 3 and code.isascii() and code.isdigit()
                                for m in case["messages"] for code in m["codes"]))
            self.assertNotIn("gold", case)
            self.assertNotIn("codebook", case)
            self.assertNotIn("ground_truth", case)
            known, _, _ = anchors_and_review(case)
            self.assertEqual(len(known), 3 if item["id"].endswith("sparse") else 0)
            self.assertEqual(set(gold["codebook"]), set(code for m in case["messages"] for code in m["codes"]))
            for m in case["messages"]:
                self.assertEqual(gold["messages"][m["id"]],
                                 "".join(gold["codebook"][code] for code in m["codes"]))

    def test_same_prefix_and_codebook(self):
        variants = []
        for n in (25, 100, 400, 1000):
            c = json.loads((BASE / "cases" / f"09_valley_{n:04d}_cold.json").read_text(encoding="utf-8"))
            s = json.loads((BASE / "cases" / f"09_valley_{n:04d}_sparse.json").read_text(encoding="utf-8"))
            self.assertEqual(c["messages"], s["messages"][:n])
            variants.append(c["messages"])
        self.assertEqual(variants[0], variants[1][:25])
        self.assertEqual(variants[1], variants[2][:100])
        self.assertEqual(variants[2], variants[3][:400])

    def test_separate_probe_not_in_training(self):
        probe = json.loads((BASE / "case09" / "gold" / "oracle_and_probe_eval_only.json").read_text(encoding="utf-8"))
        self.assertEqual(len(probe["probe_messages"]), 80)
        self.assertEqual(len(set(m["id"] for m in probe["probe_messages"])), 80)
        self.assertTrue(all(len(c) == 3 for c in probe["codebook"]))
        self.assertTrue(all(len(m["codes"]) == 24 for m in probe["probe_messages"]))
        self.assertTrue(all(m["id"].startswith("PROBE") for m in probe["probe_messages"]))

if __name__ == "__main__":
    unittest.main()
