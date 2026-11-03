"""Bounded offline shuffled-order null control for cipher structural recurrence.

The null control preserves code frequencies and message membership. It cannot
measure decipherment accuracy, probability, or semantic correctness.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import random
from typing import Any

from .core import CaseError
from .structure_diagnostics import structure_report

MAX_NULL_TRIALS = 32
MAX_RANDOM_SEED = 2**31 - 1
METRICS = (
    "heldout_with_same_sided_neighbor",
    "heldout_with_same_sided_verified_code_neighbor",
    "repeated_patterns",
)


def permutation_baseline(case: dict[str, Any], *,
                         trials: int = 16, seed: int = 0) -> dict[str, Any]:
    """Evaluate code-order recurrence against an explicitly nonsemantic null.

    Do not permute any message referenced by a known pair, including one with
    unsegmented plaintext: source alignments/research records remain intact.
    Shuffled messages retain their original code multisets and identifiers.
    """
    if type(trials) is not int or not 1 <= trials <= MAX_NULL_TRIALS:
        raise CaseError("trials must be an integer in 1..32")
    if type(seed) is not int or not 0 <= seed <= MAX_RANDOM_SEED:
        raise CaseError("seed must be an integer in 0..2147483647")
    actual = structure_report(case)
    frozen = {p["message_id"] for p in case.get("known_pairs", [])}
    shuffle_ids = {
        m["id"] for m in case["messages"]
        if m["id"] not in frozen and len(m["codes"]) > 1
        and len(set(m["codes"])) > 1
    }
    if not shuffle_ids:
        raise CaseError("No independently permutable messages; null control is undefined")
    rng = random.Random(seed)
    samples: list[dict[str, int]] = []
    changed_positions: list[int] = []
    for _ in range(trials):
        shadow = deepcopy(case)
        changed = 0
        for message in shadow["messages"]:
            if message["id"] not in shuffle_ids:
                continue
            original_codes = list(message["codes"])
            rng.shuffle(message["codes"])
            changed += sum(a != b for a, b in zip(original_codes, message["codes"]))
        results = structure_report(shadow)["summary"]
        samples.append({metric: results[metric] for metric in METRICS})
        changed_positions.append(changed)

    observed = {metric: actual["summary"][metric] for metric in METRICS}
    null = {
        metric: {
            "minimum": min(row[metric] for row in samples),
            "maximum": max(row[metric] for row in samples),
            "mean": round(sum(row[metric] for row in samples) / trials, 4),
        }
        for metric in METRICS
    }
    return {
        "schema": "han_structure_order_permutation_null_v1",
        "privacy": "aggregate_code_only_no_case_labels_metadata_or_reference_text",
        "trials": trials,
        "seed": seed,
        "frozen_known_pair_messages": len(frozen),
        "permutable_messages": len(shuffle_ids),
        "observed": observed,
        "shuffled_order_null": null,
        "changed_code_positions_per_trial": changed_positions,
        "warning": (
            "Within-message random permutations preserve membership and code "
            "frequencies but destroy local order; aligned/known-pair messages "
            "are held fixed. Differences from these controls are exploratory "
            "structural signals, NOT p-values, semantic contradictions, "
            "estimated translation accuracy, or permission to promote anchors."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline cipher structural shuffled-order control, no LLM"
    )
    parser.add_argument("--case", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--trials", type=int, default=16)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        case = json.loads(Path(args.case).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        parser.error("Input is not a readable valid case JSON")
    try:
        report = permutation_baseline(case, trials=args.trials, seed=args.seed)
    except (CaseError, TypeError, ValueError) as exc:
        parser.error("Null-control input rejected: " + type(exc).__name__)
    output = Path(args.out)
    data = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
    except OSError:
        parser.error("Cannot create NEW report; existing evidence is preserved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
