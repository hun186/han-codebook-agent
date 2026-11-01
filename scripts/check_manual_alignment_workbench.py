"""One-shot offline integration acceptance of the local researcher alignment workflow.

Runs ONLY on an ephemeral localhost server and synthetic Chinese telegram data.
Never reads user cases/config/secrets, contacts an LLM or writes real plaintext.
A diagnostic report contains check names/statuses only, not candidate text.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
from urllib import error, request
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from han_codebook.web import create_handler  # noqa: E402


def synthetic_case() -> dict:
    return {
        "case_id": "SYNTHETIC_ALIGNMENT_SMOKE_ONLY",
        "profiles": {"neutral": {
            "lexicon": {"補給": 8, "車隊": 7, "出發": 6},
            "sentences": [["補給", "車隊", "出發"]],
        }},
        "messages": [
            {"id": "anchor", "codes": ["001"]},
            {"id": "target", "codes": ["001", "002", "003"]},
            {"id": "unrelated", "codes": ["009"]},
        ],
        "known_pairs": [
            {"message_id": "anchor", "segments": ["補給"]},
            {"message_id": "target", "plaintext": "補給車隊出發"},
        ],
        "hypothesis_marks": {
            "009": {"preferred": "後勤", "excluded": [], "pinned": False},
        },
        "hypothesis_revision_history": {
            "version": 1, "cursor": 1,
            "snapshots": [
                {"002": {"preferred": "車隊", "excluded": [], "pinned": False},
                 "009": {"preferred": "後勤", "excluded": [], "pinned": False}},
                {"009": {"preferred": "後勤", "excluded": [], "pinned": False}},
            ],
            "actions": ["old hypothetical mark", "cleared before acceptance"],
        },
    }


def run_checks() -> dict:
    checks: list[dict[str, str]] = []

    def record(name: str, ok: bool) -> None:
        checks.append({"check": name, "status": "PASS" if ok else "FAIL"})

    # A clean temporary folder means we cannot touch existing cases or create
    # persistent acceptance artifacts even if the process is interrupted.
    with TemporaryDirectory(prefix="han-alignment-smoke-") as tmp:
        root = Path(tmp)
        server = ThreadingHTTPServer(("127.0.0.1", 0),
                                     create_handler(root, root / "config.yaml"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"

        def api(path: str, data: dict | None = None, *,
                other_origin: str | None = None) -> tuple[int, dict | str]:
            headers = {}
            payload = None
            if data is not None:
                payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
                headers = {"Content-Type": "application/json",
                           "Origin": other_origin or origin, "X-Han-UI": "local"}
            req = request.Request(origin + path, data=payload, headers=headers,
                                  method="POST" if data is not None else "GET")
            try:
                with request.urlopen(req, timeout=15) as response:
                    body = response.read()
                    if response.headers.get("Content-Type", "").startswith("application/json"):
                        return response.status, json.loads(body)
                    return response.status, body.decode("utf-8")
            except error.HTTPError as exc:
                body = exc.read()
                try:
                    return exc.code, json.loads(body)
                except ValueError:
                    return exc.code, "HTTP error"

        try:
            original = synthetic_case()
            source = deepcopy(original)
            with patch("han_codebook.agent.query_local_llm",
                       side_effect=AssertionError("external model forbidden")):
                status, html = api("/")
                record("loopback_workbench_has_manual_review_controls",
                       status == 200 and isinstance(html, str)
                       and 'id="previewAlignment"' in html
                       and 'id="confirmAlignment"' in html)

                status, preview = api("/api/unaligned/preview", {
                    "case": source, "top_n": 3, "beam_width": 8
                })
                has_candidates = (status == 200 and isinstance(preview, dict)
                                  and len(preview.get("reviews", [])) == 1
                                  and bool(preview["reviews"][0]["candidates"]))
                record("preview_returns_unverified_candidates", has_candidates
                       and all(c["status"] == "candidate_unverified"
                               for c in preview["reviews"][0]["candidates"]))
                record("preview_does_not_change_case_or_disk",
                       source == original and not (root / "artifacts").exists())
                if not has_candidates:
                    record("acceptance_requires_valid_preview", False)
                    return {"checks": checks}

                choices = preview["reviews"][0]["candidates"]
                index = next((i for i, c in enumerate(choices)
                              if c["segments"] == ["補給", "車隊", "出發"]), None)
                record("synthetic_reference_alignment_is_reviewable", index is not None)
                if index is None:
                    return {"checks": checks}
                accepted = {
                    "case": source, "report": preview, "known_pair_index": 1,
                    "candidate_rank": index + 1,
                    "confirmed_segments": ["補給", "車隊", "出發"],
                    "confirmed": True,
                }

                no, _ = api("/api/unaligned/accept",
                            {**accepted, "confirmed": False})
                record("without_explicit_confirmation_is_rejected", no == 400)

                no, _ = api("/api/unaligned/accept", {
                    **accepted, "confirmed_segments": ["補給", "車隊出發"]
                })
                record("wrong_retyped_segments_are_rejected", no == 400)

                stale_case = deepcopy(source)
                stale_case["messages"][0]["notes"] = "synthetic changed"
                no, _ = api("/api/unaligned/accept", {
                    **accepted, "case": stale_case
                })
                record("stale_case_digest_is_rejected", no == 400)

                no, _ = api("/api/unaligned/preview", {
                    "case": {**source, "gold": {"001": "補給"}}
                })
                record("embedded_gold_is_rejected", no == 400)

                no, _ = api("/api/unaligned/preview", {
                    "case": source
                }, other_origin="https://example.invalid")
                record("cross_origin_write_is_rejected", no == 403)

                conflicting = deepcopy(source)
                conflicting["hypothesis_marks"]["002"] = {
                    "preferred": "車隊", "excluded": [], "pinned": False
                }
                no, report2 = api("/api/unaligned/preview", {
                    "case": conflicting
                })
                if no == 200:
                    no, _ = api("/api/unaligned/accept", {
                        **accepted, "case": conflicting, "report": report2
                    })
                record("active_researcher_marks_block_promotion", no == 400)

                code, reply = api("/api/unaligned/accept", accepted)
                success = code == 200 and isinstance(reply, dict)
                modified = reply.get("case", {}) if success else {}
                record("researcher_confirmed_case_is_not_auto_saved",
                       success and reply.get("saved") is False
                       and reply.get("status") == "researcher_confirmed_not_saved"
                       and not (root / "artifacts").exists())
                pairs = modified.get("known_pairs", [])
                record("verified_anchors_and_source_stay_intact",
                       len(pairs) == 2 and pairs[0]["segments"] == ["補給"]
                       and pairs[1]["segments"] == ["補給", "車隊", "出發"]
                       and source == original)
                history = modified.get("hypothesis_revision_history", {})
                snapshots = history.get("snapshots", [])
                record("undo_history_cannot_resurrect_new_anchors",
                       len(snapshots) == 2 and all(
                           "002" not in snap and "003" not in snap
                           and "009" in snap for snap in snapshots)
                       and history.get("cursor") == 1)
                record("explicit_confirmation_keeps_provenance",
                       pairs[1].get("alignment_provenance", {}).get("method")
                       == "explicit_researcher_confirmed_review_candidate")

                code, saved = api("/api/save", {
                    "case": modified, "name": "synthetic_e2e_acceptance"
                })
                expected = root / "artifacts/ui_cases/synthetic_e2e_acceptance.json"
                record("separate_explicit_save_creates_new_case",
                       code == 201 and expected.exists() and
                       saved.get("saved_as") == "artifacts/ui_cases/synthetic_e2e_acceptance.json")
                no, _ = api("/api/save", {
                    "case": modified, "name": "synthetic_e2e_acceptance"
                })
                record("duplicate_filename_cannot_overwrite", no == 409)
                if expected.exists():
                    reloaded = json.loads(expected.read_text(encoding="utf-8"))
                    record("saved_case_roundtrip_preserves_provenance_and_history",
                           reloaded == modified)
                else:
                    record("saved_case_roundtrip_preserves_provenance_and_history", False)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    return {"checks": checks}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "artifacts/diagnostics/alignment_smoke_latest.json",
        help="Sanitized result JSON; default is project-root artifacts/diagnostics"
    )
    args = parser.parse_args(argv)
    try:
        result = run_checks()
        passed = sum(x["status"] == "PASS" for x in result["checks"])
        result = {
            "schema_version": 1, "suite": "offline_synthetic_alignment_e2e",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "status": "PASS" if passed == len(result["checks"]) and passed == 17
                      else "FAIL",
            "checks_passed": passed, "checks_total": len(result["checks"]),
            "scope": "synthetic localhost end-to-end only; no real model or historical decoding",
            "checks": result["checks"],
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        staged = args.output.with_name(args.output.name + ".tmp")
        staged.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
        os.replace(staged, args.output)
        print(f"ALIGNMENT_OFFLINE_E2E_{result['status']} {passed}/{len(result['checks'])}")
        print(f"Sanitized report: {args.output}")
        return 0 if result["status"] == "PASS" else 2
    except Exception as exc:
        # Intentionally avoid logging raw case text or HTTP response payloads.
        print(f"ALIGNMENT_OFFLINE_E2E_FAILED ({type(exc).__name__})",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
