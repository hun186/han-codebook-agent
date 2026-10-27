# Project memory

## Current Focus
v0.2 YAML config and LAN endpoint support implemented; new project draft, awaiting user creation of a new GitHub repository. Do not pretend ZIP creation equals GitHub push or Hosted CI success.

## Recent Outcomes (2026-10-27)
- Verified `matthewdgreen/decipher` public GitHub repo and README via connector; it has local Ollama agent mode and external context flags, but no dedicated Chinese phrase-codebook solver.
- Implemented offline tokenized research prototype, structured sender/recipient context, verified code-to-phrase anchors, review-only unaligned plaintext, optional Ollama proposal loop, SQLite audit, CLI, Windows/Docker usage, example synthetic benchmark.
- Local `unittest` suite: 10 baseline tests passed in v0.1; 19 tests passed in v0.2. The LLM test used a mock localhost HTTP server; no live Ollama verification yet.
- Controlled toy trial: metadata+known: 9/15 unknown correct; no metadata+known: 12/15; metadata/no known: 19/27; neither: 5/27. Results from ONE hand-built toy case; metadata sometimes hurts, and results must not be generalized. See `examples/EXPERIMENT.md`.
- There is NO real historical cipher automatically cracked here, no independent cryptanalytic verification, no Hosted CI/review, no remote git push.

## Open Handoffs
1. User creates blank `hun186/han-codebook-agent` or provides another repo URI; publish and enable Hosted CI.
2. Validate user LAN service 192.168.0.134:18080 OpenAI-compatible /v1/chat/completions API, credentials/model name and JSON compatibility. No live network validation has been performed.
3. Acquire public-period Mandarin military telegram corpus and train/evaluate with train/test separation. Do not contaminate lexical priors with held-out plaintext.
4. Implement proper variable phrase boundary inference and possible multiple codes per concept; model known-plaintext alignment uncertainty explicitly.
5. Add outer additive superencipherment diagnosis, not a blind promise to decrypt.
6. Improve candidate generation/search, automated cross-validated domain-weight selection, confidence calibration, independent held-out verification.
7. Add research GUI and background job orchestration only after solver evidence improves.

## Recent Outcomes (v0.2 config update — 2026-10-27)
- YAML primary configuration in `config.yaml`; user-provided LAN endpoint `http://192.168.0.134:18080`; no real server probe performed.
- Added `config.offline.yaml`, `--config` and CLI override merge, strict validation, YAML safe_load, relative paths relative to config file.
- Private-network HTTP opt-in and literal-IP allowlist, public-host denial and optional env-key auth; existing localhost mode kept.
- Windows `run_agent_windows.bat`, offline demo batch, setup installs PyYAML; Docker includes configs.
- 19 local unittest tests passed, including a mocked endpoint. Actual Ollama compatibility remains unverified, and no GitHub push/Hosted CI has been performed.
