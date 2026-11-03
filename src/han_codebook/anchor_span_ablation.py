"""Offline, non-oracle two-hop anchor structural-prior ablation.

Run the same deterministic solver case at two prechosen weights. This is a
sensitivity check, not evidence of better decipherment. The report contains
no plaintext, full ciphertext, LLM prompts, or reference answer.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from .core import CaseError, analyze, validate_case


def compare_anchor_span(
    case: dict[str, Any], *,
    weights: tuple[float, ...] = (0.0, 0.3),
    iterations: int = 3, restarts: int = 2, seed: int = 7,
    metadata: bool = True,
) -> dict[str, Any]:
    if not isinstance(case, dict) or any(
        key in case for key in ("ground_truth", "gold", "codebook")
    ):
        raise CaseError("ablation must not receive an embedded reference answer")
    if (not isinstance(weights, tuple) or len(weights) < 2
            or any(isinstance(x, bool) or not isinstance(x, (int, float))
                   or x < 0 or x > 1 for x in weights)):
        raise CaseError("weights must be a tuple of at least two values 0..1")
    if type(iterations) is not int or iterations < 1:
        raise CaseError("iterations must be a positive integer")
    if type(restarts) is not int or restarts < 1:
        raise CaseError("restarts must be a positive integer")
    validate_case(case)
    runs = []
    first = None
    for weight in weights:
        result = analyze(
            case, use_metadata=metadata,
            iterations=iterations, restarts=restarts, seed=seed,
            anchor_span_weight=weight)
        mapping = {code: p["term"] for code, p in result["proposals"].items()
                   if p["status"] == "hypothesis_unverified"}
        ranked = {code: tuple(x["term"] for x in p["alternatives"][:5])
                  for code, p in result["proposals"].items()
                  if p["status"] == "hypothesis_unverified"}
        if first is None:
            first = {"mapping": mapping, "ranked": ranked,
                     "anchors": result["verified_anchors"]}
        if result["verified_anchors"] != first["anchors"]:
            raise CaseError("verified anchor set changed across ablation")
        runs.append({
            "anchor_span_weight": weight,
            "unknown_code_count": len(mapping),
            "verified_anchor_count": len(result["verified_anchors"]),
            "codes_with_two_hop_anchor_context": result["anchor_span_context_code_count"],
            "two_hop_anchor_context_records": result["anchor_span_context_records"],
            "changed_top1_code_ids_vs_weight_zero": sorted(
                code for code in mapping if first["mapping"].get(code) != mapping[code]),
            "changed_top5_order_code_ids_vs_weight_zero": sorted(
                code for code in ranked if first["ranked"].get(code) != ranked[code]),
        })
    return {
        "case_id": case.get("case_id", "unnamed"),
        "method": "offline two-hop verified-anchor heuristic sensitivity, not validation",
        "no_llm_calls": True,
        "no_gold_or_round_winner": True,
        "same_solver_budget": {"iterations": iterations, "restarts": restarts,
                                "seed": seed, "metadata": metadata},
        "runs": runs,
        "limitations": [
            "Changed code IDs or rankings are NOT correctness or historical decipherment.",
            "Profile-derived two-hop bigrams are only heuristics; default inference weight is zero.",
            "All trusted anchors are immutable; model reasons and unverified hints are not promoted.",
            "No LLM calls, source plaintext, reference answers or private model endpoints are included.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path,
                        help="NEW private JSON path; never overwrite existing file")
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--restarts", type=int, default=2)
    parser.add_argument("--no-metadata", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.case.resolve() == args.out.resolve():
            raise CaseError("output must differ from input")
        data = json.loads(args.case.read_text(encoding="utf-8"))
        report = compare_anchor_span(
            data, iterations=args.iterations, restarts=args.restarts,
            metadata=not args.no_metadata)
        payload = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(args.out, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
        print(f"Saved private offline non-oracle ablation: {args.out}")
        return 0
    except (CaseError, ValueError, TypeError, KeyError, OSError) as exc:
        print(f"ERROR structural ablation: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
