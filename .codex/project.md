# Han Codebook Agent — project overview

Purpose: historical Chinese numeric phrase-codebook research workbench with structured sender/recipient priors and trustworthy known plaintext/ciphertext anchors. A code may represent a character, phrase or formulaic sentence. Outputs are *hypotheses*, not verified decipherment.

Current implementation:
- `src/han_codebook/core.py`: input validation, metadata domain inference, manual-alignment review, language models, constrained search, hypothesis reports, demo-only evaluation.
- `src/han_codebook/agent.py`: local OpenAI-compatible LLM JSON proposals, bounded reranking, SQLite audit.
- `src/han_codebook/cli.py`: executable `python -m han_codebook`.
- `examples/`: fictional case, generator, ablations and observations.
- `tests/`: unit/integration smoke tests (mocked local HTTP endpoint).

Offline-first; YAML config requires PyYAML >=6 (legacy positional CLI requires no third-party runtime deps). Python >=3.10. Windows batches, config.yaml/config.offline.yaml and Linux Dockerfile supplied.

Important constraints: fixed token boundaries, no superencipherment solver; language priors drawn from user-provided profiles; aligned known plaintext is required to lock mappings. Distinct phrase constraint is soft, opt-in only.

## Browser workbench v0.3
- `src/han_codebook/web.py` and `static/index.html`: loopback-only UI, case/evidence editor, async analyses and offline benchmarks, no cloud frontend dependencies.
- `src/han_codebook/report.py`: transparent, Markdown round-by-round research reports, no ground-truth scoring in inference.
- `benchmarks/build_cases.py`: eighth fixture contains long telegrams and third-party observations with separate gold.
