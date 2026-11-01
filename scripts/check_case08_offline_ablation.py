"""One command: isolated, real OFFLINE case-08 metadata ablation.

NO Ollama/API/model calls; gold opens only AFTER both predictions finish.
Each invocation creates a new directory and private, create-only artifacts.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import secrets
import sys

from han_codebook.agent import run_agent
from han_codebook.benchmark import score_result
from han_codebook.core import load_case
from han_codebook.diagnostic_bundle import build_diagnostic_zip, reject_oracle_fields
from han_codebook.report import investigation_report
from han_codebook.web_audit_format import read_audit_events

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "benchmarks/cases/08_long_dispatch_with_observations.json"
GOLD = ROOT / "benchmarks/gold/08_long_dispatch_with_observations.json"
DEFAULT_OUTPUT = ROOT / "artifacts/offline_case08_studies"


def write_new(path: Path, contents: bytes) -> None:
    # A unique study directory also prevents overwrite; individual files must
    # be created exactly once without following symlink targets.
    with path.open("xb") as handle:
        handle.write(contents)


def encoded(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def study(*, output_root: Path = DEFAULT_OUTPUT) -> Path:
    case_bytes = CASE.read_bytes()
    case = load_case(CASE)
    reject_oracle_fields(case)
    if case["case_id"] != "08_long_dispatch_with_observations":
        raise ValueError("Expected fixed case 08; refusing ambiguous inputs")
    output_root.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = output_root / ("case08_" + now + "_" + secrets.token_hex(4))
    directory.mkdir(mode=0o700)
    print("[OFFLINE] Case 08, zero LLM rounds; no endpoint or network probe", flush=True)
    results = {}
    per_mode = {}
    for enabled, label in ((True, "metadata_on"), (False, "metadata_off")):
        target = directory / label
        target.mkdir(mode=0o700)
        print(f"[OFFLINE] Executing {label} (same case, iterations=3, restarts=2)", flush=True)
        write_new(target / "input_case.json", case_bytes)
        # Same deterministic offline solver settings as the loopback GUI.
        result = run_agent(case, rounds=0, metadata=enabled,
                           db_path=str(target / "audit.sqlite"),
                           solver_iterations=3, solver_restarts=2,
                           adaptive_vocabulary=False, capture_llm_io=False)
        events = read_audit_events(target / "audit.sqlite")
        if result.get("agent_rounds_completed") != 0 or any(
            e.get("stage") in ("llm_request", "llm_response") for e in events
        ):
            raise RuntimeError("Offline invariant violated: unexpected LLM stage")
        write_new(target / "result.json", encoded(result))
        write_new(target / "report.md",
                  investigation_report(result, events).encode("utf-8"))
        try:
            from han_codebook.report_docx import investigation_docx
        except ImportError:
            print("[OFFLINE] Optional python-docx missing; Word report omitted.", flush=True)
        else:
            write_new(target / "report.docx", investigation_docx(result, events))
        config = {"model": None, "rounds_requested": 0, "metadata": enabled,
                  "capture_llm_io": False, "candidate_mode": "static"}
        job_id = secrets.token_hex(8)
        for mode in ("safe", "private"):
            blob = build_diagnostic_zip(target, job_id=job_id, status="completed",
                                        config=config, private=(mode == "private"))
            write_new(target / ("diagnostics_" + mode + ".zip"), blob)
        per_mode[label] = result
        results[label] = {
            "message_count": len(result["decoded_messages"]),
            "unique_code_count": len(result["proposals"]),
            "verified_anchor_count": len(result["verified_anchors"]),
            "audit_event_count": len(events),
            "llm_rounds": result["agent_rounds_completed"],
            "metadata": enabled,
            "objective_score": result["objective_score"],
        }
    # Gold is not accessible anywhere during inference. Only after BOTH
    # results exist in memory may this separate evaluation read the oracle.
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    for label, result in per_mode.items():
        scores = score_result(result, gold, case)
        # No correct phrase, gold codebook, full gold message, or oracle file
        # may appear in the output or the diagnostic ZIPs.
        results[label]["synthetic_evaluation"] = {
            key: value for key, value in scores.items()
            if key in ("unknown_code_count", "unknown_code_top1_correct",
                       "unknown_code_top1_rate", "unknown_code_top5_correct",
                       "unknown_code_top5_rate", "non_crib_message_count",
                       "non_crib_exact_messages", "non_crib_exact_rate",
                       "non_crib_segment_accuracy",
                       "non_crib_unknown_segment_accuracy")
        }
    left, right = per_mode["metadata_on"], per_mode["metadata_off"]
    before, after = left["proposals"], right["proposals"]
    if left["verified_anchors"] != right["verified_anchors"]:
        raise RuntimeError("Verified anchors changed under metadata ablation")
    changed = sorted(c for c in before if before[c]["term"] != after[c]["term"])
    summary = {
        "schema": 1, "case_id": case["case_id"],
        "case_sha256": sha256(case_bytes).hexdigest(),
        "method": "paired deterministic synthetic OFFLINE metadata ablation",
        "llm_calls": 0, "solver_iterations": 3, "solver_restarts": 2,
        "status": "complete",
        "variants": results, "changed_code_count": len(changed),
        "changed_code_ids": changed,
        "warning": (
            "Synthetic gold read only AFTER both solver runs. These rates are "
            "synthetic metrics, not independent historical decryption accuracy. "
            "Different metadata objective scores are not directly comparable."
        ),
    }
    write_new(directory / "comparison.json", encoded(summary))
    lines = [
        "# Case 08 — 零 LLM 離線情報消融比較", "",
        "> 只使用程式求解器；不呼叫 Ollama、外部網路或真實歷史密電。", "",
        "| 指標 | 啟用元數據 | 停用元數據 |",
        "|---|---:|---:|",
    ]
    for key, title in (
        ("unknown_code_top1_rate", "未知碼組 Top-1 正確率（僅合成金標）"),
        ("unknown_code_top5_rate", "未知碼組 Top-5 涵蓋率（僅合成金標）"),
        ("non_crib_exact_rate", "非已知明文電文完全匹配率（僅合成金標）"),
        ("non_crib_segment_accuracy", "非已知明文碼組位置準確率（僅合成金標）"),
    ):
        a = results["metadata_on"]["synthetic_evaluation"].get(key)
        b = results["metadata_off"]["synthetic_evaluation"].get(key)
        lines.append(f"| {title} | {a} | {b} |")
    lines += [
        "", f"兩種設定的第一順位發生差異：**{len(changed)}** 個碼組。",
        "完整研究候選、原始明文和稽核資料僅放在各自的私人資料夾／私人 ZIP。",
        "分數差異本身不是信賴度或真實歷史正確率。禁止把金標放進模型輸入。",
        "",
        "本研究的 LLM 連線、案例 07 實機探測及案例 08 三回合實驗仍是待辦；本次全部未執行。",
        "",
    ]
    write_new(directory / "comparison.md", "\n".join(lines).encode("utf-8"))
    print(f"[PASS] OFFLINE CASE08 study saved under {directory}", flush=True)
    print(f"[PASS] LLM calls=0; changed top-1 codes={len(changed)}", flush=True)
    return directory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT,
                        help="Parent directory; a fresh unique run folder is created")
    args = parser.parse_args(argv)
    try:
        study(output_root=args.output_dir)
    except Exception as exc:
        print(f"[FAIL] Offline case08 study incomplete: {type(exc).__name__}: {exc}",
              file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
