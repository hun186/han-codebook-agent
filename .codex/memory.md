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

## 2026-10-27 — 單一碼本跨密文數量實驗（新工作分支）
- 使用者明確要求「一個案例所有電文使用同一碼本」，不在同個測試集混用碼本。建三個獨立固定碼本種子，每個 100 封、巢狀取 10／25／50／100 封，另有 20 封獨立探針。
- 初始無明密文對照、含固定公用候選詞庫（含部分正確詞與干擾詞），分別開／關收發者和低可信度觀察；整輪全離線不呼叫 LLM。
- 改善 `core.analyze` 的統計查表快取和單碼組局部 delta 打分，避免對 100 封反覆全量重算。用已存在八組舊測試資料和 2 iterations/2 restarts 比對，預測碼本 0 差異；全部測試 52 項 PASS。
- 新增 `benchmarks/build_volume.py`、`benchmarks/volume/` case 與分開 gold、`src/han_codebook/volume.py`、`tests/test_volume.py`、`run_volume_study_windows.bat` 及自包含 HTML/JSON/MD 圖表報告。
- 三 seed × 10/25/50/100 × 有／無元數據，在 4 iterations/4 restarts 下共 24 runs。元數據開啟時未驗證碼組 Top-1 平均依序約 12.7%、5.0%、7.8%、10.0%；100 封並未單調進步。必須註明是合成試驗，不得宣稱真實破密成功。
- 當前 GitHub main `a98f154`（PR #3 合併後），PR #1 尚 open，包含重複基準內容，不要重複合併。新內容尚須建立 PR、驗證 Hosted CI 與正式 Codex Review，不能先寫成已通過。

## Single-codebook volume LLM extension (2026-10-27)
- PR #4 initially implemented 3×(10/25/50/100) **offline-only** ablation; user correctly noticed no real LLM calls. Keep original `run_volume_study_windows.bat` as statistical baseline.
- Added separate explicitly opt-in `run_volume_llm_windows.bat` / `han_codebook.volume_llm`: single fixed codebook per seed, zero known pairs, same statistical solver budget, nested prefixes, all messages supplied to model in non-overlapping <=25-message batches (100 messages = 4 model requests per round). Default seed 101, one model round, eight model requests total for the 10/25/50/100 comparison.
- Recompute predictions with dictionary-constrained LLM hints, post-inference-only gold scoring, independent 20-message probe, correct-vs-broken mapping count, local HTML/JSON/Markdown comparison, optional raw Prompt/response capture. Metadata-off strips sender/recipient/observations; never promote LLM guesses to verified. No external/public API allowed; private-network exact allowlist retained.
- Local full unittest 57 PASS after new regression tests, using mock calls, not a live user LAN endpoint. Do not claim actual Qwen improvements before user's real run.
- Branch PR #4 and Hosted CI status must be checked afresh before claiming update complete or merging.

## PR #4: decoded-message exploration and Codex review P2 (2026-10-27)
- User requests to view each ciphertext telegram as code-group-aligned current Chinese hypotheses and understand individual AI contributions rather than final accuracy alone.
- Added `src/han_codebook/volume_decode_view.py` and integrated `decoding_views` into LLM study reports, with standalone interactive HTML selector for seed/corpus size/message, side-by-side statistical/LLM guesses, top-five alternatives and LLM-provided reasons. All text is unverified hypothesis; no secret gold or holdout plaintext in explorer JSON. Use safely embedded inert JSON and DOM textContent.
- Added offline replay of existing `artifacts/volume_llm_study.json` saved trace to avoid repeating previous eight live model calls: `run_volume_view_windows.bat` or `--rebuild-view-from`, producing non-overwriting `_decipher` output; compare recomputed metrics to original scores and clearly mark replay.
- Review at PR #4 HEAD c7787e0 reported two P2s: within-response duplicate candidate/code inflates hints; opt-in audit trace lost on HTTP failure. Updated deduplication and failure handling, writing `.failed.json` only when explicit raw capture enabled and never reporting success for failed run. Add direct regression tests.
- New work requires Hosted GitHub CI and a fresh formal Codex review before merge; preserve old PR #1 unchanged. Do not claim user LAN Qwen has been rerun after modifications.

## PR #4 follow-up — truth reveal for synthetic training messages (2026-10-27)
- User highlighted that `available_vocabulary` is a *pre-supplied* lexicon, not inferred from ciphertext; preserve disclosure of this methodological limitation.
- Added post-inference-only `attach_evaluation_gold` for observed training ciphertext codes, with strict codebook/message consistency checks. Never feed gold, decoded evaluation view, or independent 20-message holdout into statistical analysis or LLM prompts.
- Explorer adds opt-in **reveal** toggle, code-level correctness overlays, per-message correct counts and exact synthetic plaintext. Toggle is UI-only; completed HTML/JSON contains evaluation labels and must not be fed back to inference. Works for offline replay of saved trace without additional model calls.
- Tests and hosted verification status must be determined from current PR head; do not claim results from unexecuted tools.

## Current work (2026-10-27) — Reversible researcher annotations
- Added `hypothesis_marks` to *case inputs* separately from known_pairs, with per-code preferred/experimental pinned/excluded/note; no mark can upgrade verified alignment. Solver supports soft preferences, trial pins and exclusions plus optional entirely new user terms without mutating the input case; undo or removal restores original inference deterministically.
- Browser `假說標註／復原` tab supports user-selected code via clickable decoded pieces, reversible local undo/redo revision snapshots, reset, re-run and diff against prior result; case save retains current marks and bounded revision snapshots for reopening an earlier version later. Added 100-message synthetic case to browser discovery; no synthetic gold in UI model data.
- Tests in tests/test_researcher_marks.py cover unverified pins, rollback, exclusion, contradictory marks and audit provenance. GitHub Hosted CI / Codex review still needed for this iteration.
- Follow-up Codex P2 hardening: UI auto-prunes historical snapshots to keep serialized research <=1,000,000 bytes (Web POST limit 1.5 MB), run requests omit history entirely, and applying newly segmented known pairs atomically rejects marks on newly verified codes; added Node VM regression test invoked by Python unittest. Full local suite now 79 tests PASS; Hosted CI and review for newest commit must be verified.
- Additional edge-case hardening: once an aligned known-plaintext pair becomes accepted, mark snapshots for that newly verified code are scrubbed so Undo cannot resurrect an invalid researcher hypothesis; preserve unrelated history. New test checks this. Latest local 79 unittest tests PASS; GitHub Hosted CI and review remain separately authoritative.

## PR #4 follow-up Codex review P1/P2 hardening (2026-10-27)
- Checked hosted HEAD 77a5d7a review, finding P1 nested observation fields (e.g. ground_truth) could reach LLM and cold-start prompts, plus P2 singleton undo snapshot duplicates large valid case beyond the Web POST maximum.
- Shared strict primitive observation/message whitelist in `src/han_codebook/llm_evidence.py` for both `volume_llm._input_messages` and `auto_vocabulary.make_vocabulary_packet`. No unrecognized nested keys may be passed; metadata disabled omits all side information.
- Browser `persistMarkHistory()` drops the *persisted* history when a single snapshot still exceeds the 1 MB history budget; in-memory undo state and current hypothesis marks survive. A saved case reinitializes undo history from its marks on reload.
- Added Python nested-oracle leak tests and Node 500-code × 500-character sole-snapshot regression. Run fresh tests, hosted CI, and formally review updated HEAD before merging; no real Qwen test claimed.


## Vercel public Mock PoC (2026-10-27)
- Added isolated `vercel-demo/` static deployment with synthetic seed-101 telegrams and a deterministic, explicitly labeled in-browser MOCK LLM. No network model calls, LAN host, secrets, persistent DB, or backend auth.
- Samples 10/25/50/100 messages; shows cipher/initial/mock/current researcher candidate view, undo/redo mark trial, and opt-in reveal of separate public synthetic gold. This is a UI demonstration (NOT Python inference or true LLM model), and should not be used for cipher recovery benchmarks.
- Vercel project Root Directory must be `vercel-demo`. Existing local Python web workbench remains authoritative for actual statistical runs and user-authorized Qwen calls. New CI/review/deployment statuses must be checked from GitHub/Vercel.


## 2026-10-27 — Vercel researcher-feedback Mock work
- Vercel static demo now provides deterministic, inspectable mock reranking after reversible researcher preferred/excluded/trial-pin marks. This is not real Qwen inference: original statistical and mock scores remain immutable historical baselines; a new post-mark simulation uses ciphertext adjacency and unverified precomputed lexical candidate transitions to rerank and list affected code groups. Undo/Redo recomputes from the same baseline. Gold is loaded only after explicit reveal and never enters the feedback solver.
- Local reconstructed suite completed 86 unittest cases PASS and Node VM checks for mark propagation, exclusion, undo/redo, gold isolation. Hosted CI and deployed Vercel require independent verification.
