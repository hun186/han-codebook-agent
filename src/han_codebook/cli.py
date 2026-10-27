from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from .agent import run_agent, probe_llm_service
from .config import load_settings
from .core import load_case, evaluate_demo, CaseError


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="han-codebook", description="Offline-first research workbench for Chinese historical codebooks")
    parser.add_argument("case", nargs="?", default=None, help="JSON case path (overrides config project.case)")
    parser.add_argument("--config", help="YAML settings file; other CLI flags override it")
    parser.add_argument("--check-llm", action="store_true", help="Check TCP and /v1/models without sending cipher data")
    parser.add_argument("--no-metadata", action="store_true", default=None, help="Ablation: ignore sender/recipient/domain")
    parser.add_argument("--rounds", type=int, default=None, help="LLM proposal rounds (0=offline)")
    parser.add_argument("--ollama-url", default=None, help="OpenAI-compatible base endpoint")
    parser.add_argument("--model", default=None, help="LLM model name")
    parser.add_argument("--out", default=None)
    parser.add_argument("--db", default=None)
    parser.add_argument("--evaluate-demo", action="store_true", default=None, help="Only score fictional demo ground truth")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config) if args.config else {"project": {}, "analysis": {}, "llm": {}}
        project, analysis, llm = (settings[key] for key in ("project", "analysis", "llm"))
        case_path = args.case or project.get("case")
        if not case_path and not args.check_llm:
            parser.error("case JSON is required: provide a positional path or config project.case")
        rounds = args.rounds if args.rounds is not None else analysis.get("rounds", 0)
        if not 0 <= rounds <= 20:
            parser.error("--rounds must be 0..20")
        timeout = llm.get("timeout_seconds", 90)
        metadata = not args.no_metadata if args.no_metadata is not None else analysis.get("use_metadata", True)
        evaluate = args.evaluate_demo if args.evaluate_demo is not None else analysis.get("evaluate_demo", False)
        url = args.ollama_url or llm.get("base_url", "http://127.0.0.1:11434/v1")
        model = args.model or llm.get("model", "qwen3:14b")
        out = args.out or project.get("output", "artifacts/result.json")
        db = args.db or project.get("audit_db", "artifacts/audit.sqlite")
        if args.check_llm:
            print(f"[check] API base: {url} | model configured: {model}", flush=True)
            ok = probe_llm_service(url, timeout=min(timeout, 8),
                                   allow_private_network=llm.get("allow_private_network", False),
                                   allowed_hosts=llm.get("allowed_hosts", []),
                                   api_key_env=llm.get("api_key_env"))
            print("[check] Note: TCP/models checks do not validate actual chat inference.", flush=True)
            return 0 if ok else 2
        print(f"[start] Case: {case_path} | rounds: {rounds} | model: {model}", flush=True)
        if rounds:
            print(f"[start] Chat endpoint: {url.rstrip('/') + ('' if url.rstrip('/').endswith('/v1') else '/v1')}/chat/completions", flush=True)
            print("[start] Waiting for LLM can take longer than an offline run. Ctrl+C cancels.", flush=True)
        case = load_case(case_path)
        result = run_agent(case, rounds=rounds, llm_url=url, model=model, db_path=db,
                           metadata=metadata, llm_timeout=timeout,
                           allow_private_network=llm.get("allow_private_network", False),
                           llm_allowed_hosts=llm.get("allowed_hosts", []),
                           llm_api_key_env=llm.get("api_key_env"),
                           progress=lambda message: print(message, flush=True))
        if evaluate:
            result["evaluation"] = evaluate_demo(result, case)
        dest = Path(out)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Case: {result['case_id']} | anchors: {result['known_code_count']} | unknown: {result['unknown_code_count']}")
        print(f"Metadata: {result['metadata_used']} | Agent rounds: {result['agent_rounds_completed']}")
        print("Codebook hypotheses (✓ verified alignment; ? unverified):")
        for code, proposal in sorted(result["proposals"].items()):
            tag = "✓" if proposal["status"] == "verified_alignment" else "?"
            print(f" {tag} {code} => {proposal['term']}")
        print("Messages:")
        for m in result["decoded_messages"]:
            print(f" {m['id']} [{m['domain_inferred'] or 'unknown domain'}]: {m['reading']} ({m['verified_codes']}/{m['total_codes']} code groups anchored)")
        if "evaluation" in result:
            print("Synthetic held-out evaluation (not a deployment quality claim):", result["evaluation"])
        print(f"Report: {dest} | Audit: {db}")
        return 0
    except (CaseError, OSError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
