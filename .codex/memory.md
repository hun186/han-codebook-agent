# Project memory

## Current Focus
v0.3 browser workbench implementation in progress on branch; GitHub main d602616 (2026-10-27) has v0.2 and successful Hosted CI. PR #1 separate benchmark suite still open. Never confuse local test and Hosted CI.

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

## Recent outcomes (2026-10-27 — LLM run responsiveness PR)
- User reported `run_agent_windows.bat` apparently froze after successful offline run. Root cause in code: no status output before synchronous potentially slow LLM request; live LAN endpoint `192.168.0.134:18080` unverified.
- Added `--check-llm` lightweight TCP + `GET /v1/models` preflight, with distinct network/auth/HTML and unsupported route interpretations; this check never sends ciphertext and does not establish chat compatibility.
- `run_agent_windows.bat` now invokes preflight before processing, runs unbuffered Python and outputs staged progress. Core Agent loop emits stage/round/request progress plus 10-second wait heartbeats and a result summary.
- HTTP failures 401/403/404/502/503/504 and HTML-instead-of-JSON are now diagnosed explicitly without leaking API tokens.
- Existing v0.2 offline operation is unchanged; all local tests passed (28 tests) and a separate offline CLI smoke test passed. New tests mock the network; real Ollama service has **not** been verified.
- This fix should be applied via dedicated PR branch; initial synthetic benchmark PR #1 remains open, independent of this fix.

## Recent outcomes (v0.3 browser prototype, 2026-10-27)
- Built local-only Python ThreadingHTTPServer + self-contained browser UI, research case editing, lexicon prior editor, known pairs and third-party observations, active job progress, round deltas, score curve, domain distribution, audit raw request/response opt-in, Markdown analysis report.
- Added observation evidence to metadata-conditioned scoring (never verified anchors), required source and confidence range validation.
- Added strict benchmark case #8: 12 longer messages, 16-21 groups ~42-55 characters, simulated transport and operational details, 5 sightings, gold separated from case, deterministic offline budget.
- Local tests run on reconstructed v0.3 working tree; need GitHub push and hosted CI before declaring release readiness.
- Web UI binds only loopback and disallows generic file serving/CORS writes. Browser sessions are not authenticated; never expose via public port.
- LLM source prompts, raw responses, timings and returned token usage can be locally captured only with explicit user opt-in. Correctness not proven by a valid HTTP response.
- Outstanding: independent period corpus, real LAN live inference validation, calibrated abstention, genuine variable-length superencipherment support.

## PR #3 review P2 corrections (2026-10-27)
- Hosted PR #3 head before this patch: `63d38ac24ac09f46e1ed35205d53036f14d538a5` (OPEN). Initial Codex review yielded four unresolved P2 findings: failed-job UI trace hidden, non-atomic evidence edit, job stuck queued after output mkdir failure, HTTPError response body missing from opt-in audit. Treat new head/review/CI as authoritative after push.
- `static/index.html`: `renderTrace` now runs on queued/running/failed as well as completed; current job trace replaces prior trace, failure is labelled as partial; result-only statistics still require completed status. `applyEvidence` stages and validates cipher/observations/fields prior to mutating any message property; previous good record stays untouched on validation failure.
- `web.py`: moving analysis target mkdir into guarded work try ensures failures transition jobs to `failed` and release single-job gate; audit load failures cannot leave job running indefinitely.
- `agent.py`: on explicit capture opt-in, HTTPError response body recorded with status, elapsed time, truncation and strict 64,000-byte cap; without capture, no request/response body is logged. Secrets in Authorization headers are never copied.
- Added `tests/test_review_p2.py` with Python simulated HTTP and background server jobs and `tests/js/test_ui_review.js` with Node VM DOM regression. Separate local targeted tests passed 5 tests. Full test run and Hosted CI/review must be confirmed before merge. Real user's LAN Ollama service still untested by these regression tests.
