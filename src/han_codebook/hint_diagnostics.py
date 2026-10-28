"""Offline replay of recorded LLM proposals and observation-reliability ablations.

All solver trials finish before optional synthetic ground-truth scoring. The
script never contacts an LLM, nor selects a trust scale using gold labels.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import json
from pathlib import Path

from .core import CaseError, analyze, anchors_and_review, validate_case

SCALES = (0.0, 1.0, 2.4)


def hints_from_reply(case: dict, reply: dict) -> tuple[dict, list]:
    """Use the first 15 valid, distinct code proposals, as in volume_llm."""
    if not isinstance(reply, dict) or not isinstance(reply.get("hypotheses"), list):
        raise CaseError("reply JSON requires hypotheses list")
    _, _, vocab = anchors_and_review(case)
    observed = {code for m in case["messages"] for code in m["codes"]}
    hints, accepted = {}, []
    for item in reply["hypotheses"][:15]:
        if not isinstance(item, dict):
            continue
        code, words = item.get("code"), item.get("candidates")
        if not isinstance(code, str) or code not in observed or code in hints or not isinstance(words, list):
            continue
        unique = []
        for word in words:
            if isinstance(word, str) and word in vocab and word not in unique:
                unique.append(word)
            if len(unique) >= 5:
                break
        if unique:
            hints[code] = {word: 0.25/(idx+1) for idx, word in enumerate(unique)}
            accepted.append({"code": code, "candidates": unique})
    return hints, accepted


def compare(case: dict, reply: dict, *, iterations: int = 2, restarts: int = 2,
            observation_ablation: bool = True) -> dict:
    if any(key in case for key in ("gold", "ground_truth", "codebook")):
        raise CaseError("Do not embed evaluation oracle in inference case")
    validate_case(case)
    hints, accepted = hints_from_reply(case, reply)
    baseline = analyze(case, llm_hints=hints, hint_scale=0.0,
                       iterations=iterations, restarts=restarts, seed=7)
    original = {code: p["term"] for code, p in baseline["proposals"].items()}
    variants = [("metadata_all", case, True, 0.0),
                ("metadata_all", case, True, 1.0),
                ("metadata_all", case, True, 2.4)]
    if observation_ablation:
        without_obs = deepcopy(case)
        for m in without_obs["messages"]:
            m.pop("observations", None)
        time_aware = deepcopy(case)
        time_aware["observation_policy"] = "time_relevance"
        variants.extend([("no_observations", without_obs, True, 1.0),
                         ("time_relevance", time_aware, True, 1.0),
                         ("no_metadata", case, False, 1.0)])
    rows = []
    for name, subcase, metadata, scale in variants:
        result = baseline if scale == 0.0 and name == "metadata_all" else analyze(
            subcase, use_metadata=metadata, llm_hints=hints, hint_scale=scale,
            iterations=iterations, restarts=restarts, seed=7)
        mapping = {code: p["term"] for code, p in result["proposals"].items()}
        rows.append({
            "scenario": name, "hint_scale": scale,
            "observations_present": sum(len(m.get("observations", [])) for m in subcase["messages"]),
            "hinted_first_choice_adopted": sum(mapping.get(code) == next(iter(words))
                                               for code, words in hints.items()),
            "hinted_codes": len(hints),
            "changed_vs_no_hints": sum(mapping.get(c) != v for c, v in original.items()),
            "domain_inference": {m["id"]: m["domain_inferred"] for m in result["decoded_messages"]},
            "mapping": mapping,
        })
    return {
        "mode": "offline-LLM-replay; NO model calls",
        "no_oracle_during_inference": True,
        "accepted_hypotheses": accepted,
        "note": "Hint adoption and changed mappings are NOT accuracy; objective scores across scales are not comparable.",
        "runs": rows,
    }


def evaluate_after_inference(report: dict, gold: dict) -> dict:
    """Synthetic oracle scoring after all assignments; never feeds results into analyze."""
    if not isinstance(gold.get("codebook"), dict):
        raise CaseError("synthetic gold requires codebook object")
    output = deepcopy(report)
    for row in output["runs"]:
        missing = set(row["mapping"]) - set(gold["codebook"])
        if missing:
            raise CaseError("gold does not cover all inferred code groups")
        row["synthetic_top1_correct"] = sum(word == gold["codebook"][code]
                                             for code, word in row["mapping"].items())
        row["synthetic_top1_total"] = len(row["mapping"])
    output["scoring"] = "after inference only, synthetic cases; not historical decoding success"
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True, type=Path)
    parser.add_argument("--reply", required=True, type=Path, help="Saved LLM hypotheses; no new API calls")
    parser.add_argument("--gold", type=Path, help="Optional SYNTHETIC oracle, read AFTER inference")
    parser.add_argument("--messages", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=2)
    parser.add_argument("--restarts", type=int, default=2)
    parser.add_argument("--out", type=Path, default=Path("artifacts/hint_diagnostics.json"))
    args = parser.parse_args(argv)
    case = json.loads(args.case.read_text(encoding="utf-8"))
    if not 1 <= args.messages <= len(case["messages"]):
        parser.error("--messages must fit the case")
    if args.iterations < 1 or args.restarts < 1:
        parser.error("--iterations and --restarts must be positive")
    case["messages"] = case["messages"][:args.messages]
    reply = json.loads(args.reply.read_text(encoding="utf-8"))
    result = compare(case, reply, iterations=args.iterations, restarts=args.restarts)
    if args.gold:
        result = evaluate_after_inference(result, json.loads(args.gold.read_text(encoding="utf-8")))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in result["runs"]:
        score = (f"; synthetic correct {r['synthetic_top1_correct']}/{r['synthetic_top1_total']}"
                 if "synthetic_top1_correct" in r else "")
        print(f"{r['scenario']} scale={r['hint_scale']}: adopted "
              f"{r['hinted_first_choice_adopted']}/{r['hinted_codes']}, "
              f"changed {r['changed_vs_no_hints']}{score}")
    print("Saved:", args.out)


if __name__ == "__main__":
    main()
