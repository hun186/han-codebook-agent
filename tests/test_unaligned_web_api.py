"""Loopback API: preview and researcher acceptance are separate from disk save."""
from __future__ import annotations

from copy import deepcopy
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
from urllib import request, error

from han_codebook.web import create_handler


def fixture():
    return {
        "case_id": "offline-browser-alignment",
        "profiles": {"neutral": {"lexicon": {
            "補給": 8, "車隊": 7, "出發": 6
        }, "sentences": [["補給", "車隊", "出發"]]}},
        "messages": [
            {"id": "anchor", "codes": ["001"]},
            {"id": "target", "codes": ["001", "002", "003"]},
        ],
        "known_pairs": [
            {"message_id": "anchor", "segments": ["補給"]},
            {"message_id": "target", "plaintext": "補給車隊出發"},
        ],
    }


class OfflineAlignmentAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            create_handler(cls.root, cls.root / "config.yaml")
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.tmp.cleanup()

    def post(self, path, data, *, origin=None):
        req = request.Request(
            self.base + path,
            data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "X-Han-UI": "local",
                     "Origin": origin or self.base},
            method="POST"
        )
        return json.loads(request.urlopen(req).read().decode("utf-8"))

    def test_preview_and_accept_are_not_implicit_disk_save(self):
        source = fixture()
        before = deepcopy(source)
        with patch("han_codebook.agent.query_local_llm",
                   side_effect=AssertionError("no model call")):
            preview = self.post("/api/unaligned/preview", {
                "case": source, "top_n": 3, "beam_width": 8
            })
            self.assertEqual(preview["review_required"], True)
            self.assertEqual(preview["reviews"][0]["candidates"][0]["segments"],
                             ["補給", "車隊", "出發"])
            self.assertEqual(preview["top_n"], 3)
            self.assertEqual(preview["beam_width"], 8)
            result = self.post("/api/unaligned/accept", {
                "case": source, "report": preview, "known_pair_index": 1,
                "candidate_rank": 1,
                "confirmed_segments": ["補給", "車隊", "出發"],
                "confirmed": True
            })
        self.assertEqual(source, before)
        self.assertFalse(result["saved"])
        self.assertEqual(result["status"], "researcher_confirmed_not_saved")
        self.assertEqual(result["case"]["known_pairs"][1]["segments"],
                         ["補給", "車隊", "出發"])
        self.assertFalse((self.root / "artifacts" / "ui_cases").exists())
        saved = self.post("/api/save", {
            "case": result["case"], "name": "explicitly_saved_alignment"
        })
        self.assertEqual(saved["saved_as"],
                         "artifacts/ui_cases/explicitly_saved_alignment.json")

    def test_no_confirmation_stale_case_tampered_oracle_rejected(self):
        case = fixture()
        report = self.post("/api/unaligned/preview", {"case": case})
        required = {
            "case": case, "report": report, "known_pair_index": 1,
            "candidate_rank": 1,
            "confirmed_segments": ["補給", "車隊", "出發"], "confirmed": True
        }
        for patch_data in ({"confirmed": False},
                           {"confirmed_segments": ["補給", "車隊出發"]},
                           {"candidate_rank": 99}):
            with self.subTest(patch=patch_data), self.assertRaises(
                error.HTTPError
            ) as ctx:
                self.post("/api/unaligned/accept", {**required, **patch_data})
            self.assertEqual(ctx.exception.code, 400)
        changed = deepcopy(case)
        changed["messages"][0]["notes"] = "new archival evidence"
        with self.assertRaises(error.HTTPError) as ctx:
            self.post("/api/unaligned/accept", {**required, "case": changed})
        self.assertEqual(ctx.exception.code, 400)
        with self.assertRaises(error.HTTPError) as ctx:
            self.post("/api/unaligned/preview", {
                "case": {**case, "gold": {"001": "補給"}}
            })
        self.assertEqual(ctx.exception.code, 400)

    def test_researcher_marks_conflict_and_cross_origin_rejected(self):
        case = fixture()
        case["hypothesis_marks"] = {"002": {
            "preferred": "車隊", "excluded": [], "pinned": False
        }}
        preview = self.post("/api/unaligned/preview", {"case": case})
        with self.assertRaises(error.HTTPError) as ctx:
            self.post("/api/unaligned/accept", {
                "case": case, "report": preview, "known_pair_index": 1,
                "candidate_rank": 1,
                "confirmed_segments": ["補給", "車隊", "出發"],
                "confirmed": True
            })
        self.assertEqual(ctx.exception.code, 400)
        with self.assertRaises(error.HTTPError) as ctx:
            self.post("/api/unaligned/preview", {"case": fixture()},
                      origin="https://evil.example")
        self.assertEqual(ctx.exception.code, 403)
        with self.assertRaises(error.HTTPError) as ctx:
            self.post("/api/unaligned/preview", {
                "case": fixture(), "irrelevant": "not allowed"
            })
        self.assertEqual(ctx.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
