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


## 2026-10-28 — LLM hint-sensitivity and third-party sighting relevance research PR
- Main baseline at `091a6ae` (PR #4 merged). New branch `feat/hint-sensitivity-observation-ablation-20261028`.
- User wanted proof whether weak Qwen/GPT-6 Top-1 stems from model quality, fixed vocabulary, weak hint integration or unreliable sightings; **avoid raising default model trust merely because more model hints are adopted**.
- `analyze` now supports explicit bounded `hint_scale` (0..4, default 1) and optional `case.observation_policy="time_relevance"`. Default `legacy` keeps old context scoring. Time-aware observations are discounted when uncertain, distant, invalid or explicitly unrelated; they are not verified evidence.
- Offline `hint_diagnostics` replays saved hypotheses without model API calls, compares scales 0/1/2.4 and sighting ablations (with/without/time-aware/no metadata), and optionally scores synthetic gold only AFTER every inference run. Never use gold to tune live weights. It prints hint adoption and mapping changes separately from accuracy.
- On the previously locked GPT-6 Seed 202 n10 hints: 5/15, 7/15, 11/15 top-choice hints adopted at scales 0,1,2.4; **all 6/51 synthetic Top-1**, not an improvement. Without observations 6/51; without all metadata 3/51. Only one synthetic seed, no new Qwen or GPT API run.
- Local targeted regression: 5 tests PASS using copied current `main` core. Full Hosted CI and formal review must be checked on GitHub; this work is not merged.
- Still missing: calibrated event-to-telegram latent association, data-driven confidence calibration, proper cold-start vocabulary integration in ordinary GUI, and genuine matched GPT/Qwen API benchmark. Do not claim implemented.


## 2026-10-28 — User research workflow and cross-telegram event evidence (PR #5 expanded)
- User requires a real investigator workflow: input own intercepted messages and optional sightings from scratch, autonomous local-model vocabulary hypotheses first, human reviewing multiple competing ideas per code, then LLM assessing possible correlations across sightings and telegrams. Sightings may be wholly unrelated. Never claim event links are confirmed mappings.
- Codex first review of PR #5 found P1 nested non-primitive observations affecting domain inference, P2 date-only/timezone asymmetry, P2 mismatched gold case IDs. Hardened primitive-only fields in inference domain scorer, sanitize LLM and event-link packet; unknown nested archival fields are ignored rather than sent to inference for compatibility with existing adversarial whitelist tests. Symmetric date comparison when either timestamp has only day precision; refuse synthetic gold with mismatched case_id.
- New `event_links.py` proposes dated candidates for each observation across telegrams and explicitly includes null (no connection). Scores are simple conservative timestamp/confidence heuristics, *not* learned code-semantic associations; no oracle. Local LLM packets and cold-start vocabulary packet receive bounded event candidates.
- New `candidate_ideas.py` offers multiple proposals per code, explicit source/status/note, bounded counts, no verified statuses. Solver allows their non-rejected terms as vocabulary and adds a weak 0.12 prior for shortlisted ideas; previous mark prefer/exclude/pin unchanged.
- Local `web.py` has `/api/event-links` and explicit-confirmation private-LLM `/api/suggest-vocabulary` async job, no model network without button. GUI supports blank case creation, adding/removing intercepted messages, sender/recipient/time/observations, adding language domains, reviewing generated candidate terms one by one, viewing event links, importing accepted code hypotheses from completed LLM runs, maintaining multi-idea bank with session-only undo/redo and saving current ideas in case JSON.
- New tests `tests/test_research_workbench.py` exercise observational no-oracle behavior, temporal links/unrelated alternative, idea bank, cross-case gold rejection, dates and Node syntax.
- **As of this handoff** several intermediate CI runs failed because strict observation rejection broke old tests intentionally containing nested `status`; adjusted to ignore nested values safely and preserve allowlisted output. Verify latest Hosted CI and review independently; never claim newest run PASS before checking. PR #5 OPEN, not merged; no real LAN Qwen or Vercel GUI deployment performed in this phase. True event-to-telegram semantic latent matching/calibration and production-ready model suggestions remain follow-up research.

## 2026-10-28 — PR #5 second Codex review and in-app workflow guide (newest handoff)
- User asked to address two new P2 review findings and add a first-class **GUI web guide** explaining research process and architecture with visible navigation.
- Latest review at HEAD `fb413d6` found P2: async vocabulary/analysis results can spill between cases, and importing LLM ideas silently resets previously rejected/shortlisted researcher ideas. Both addressed in `src/han_codebook/static/index.html`.
- Front-end now records `caseGeneration`, source case object and serialized case fingerprint (excluding revision-history UI cache). It guards asynchronous start, vocab generation/polling, event-link preview, render and adoption, as well as stale buttons, across case switches and in-place evidence revisions. Per-job timer ownership prevents a stale callback cancelling a newer case's timer. Any stale job after in-place case edit re-enables its corresponding button; case switches clear the old case's decoded readings, trace, event links and model suggestion cache. LLM candidate origin is checked again on manual import.
- Quiet LLM idea import never overwrites a duplicate proposal. Existing `rejected` or `shortlisted` states, human notes and source are preserved; only truly novel candidates are added. Undo/Redo remains.
- New `guide` section in local GUI shows seven-stage workflow, four evidence/verification layers, source trust vs known plaintext, loop vs mock, storage and caveats. Responsive desktop sticky sidebar; mobile horizontally scrollable tabs; each guide stage has a working navigation button. Old established trace-navigation label is retained for existing regression contracts.
- New Node VM regression `tests/js/test_case_provenance.js` and Python wrapper `tests/test_case_provenance_ui.py` test A-to-B delayed callback, stale vocab buttons, stale analysis and event results, same-case edits, reviewer veto preservation, undo and redo, in addition to guide markup. Do not claim production browser E2E or model accuracy improvement from CI.
- Pending at this snapshot: check newest Hosted CI, submit fresh formal Codex review after final edits, resolve any new findings; PR #5 still OPEN and not merged. Latest changes to root docs and UI remain only on PR head, not on deployed Vercel PoC.

## 2026-10-28 — PR #5 follow-up to third Codex review P2
- Third formal review completed at HEAD `f7142bb9`: new P2 #1 stale concurrent `/api/jobs/<id>` responses in *same* case override a later vocabulary job; new P2 #2 changing a code's final occurrence leaves orphan candidate_ideas and obsolete code menu/undo history.
- Frontend now has `vocabRequestSerial` + `vocabActiveJobId`. Every new job invalidates the preceding one; terminal result increments serial, so other concurrent pending responses are ignored. Candidate buttons record the job-display serial and reject clicks from retired jobs even if current case matches. `analysisRequestSerial` similarly rejects stale parallel analysis GETs.
- `applyEvidence()` parses and validates staged metadata atomically. It refuses code changes when trusted `known_pairs` attach to that message. After calculating all case-wide remaining codes, it prompts before deleting any orphaned annotations, then prunes orphan keys from `candidate_ideas`, `hypothesis_marks`, all candidate and mark undo/redo snapshots, persists mark revisions, refreshes code list and candidate review. If cleanup cancelled, no mutation is committed; codes that remain in other messages retain annotations.
- Regression `tests/js/test_case_provenance.js` reproduces overlapping outstanding same-case job polls, finished old job returning after new job, and old rendered candidate buttons. New `tests/js/test_cipher_edit_integrity.js` covers cancellation, orphan cleanup, undo/redo, dropdown refresh and known-plaintext refusal. `tests/test_case_provenance_ui.py` runs both in Hosted Python test matrices.
- A previous CI attempt failed due Node VM cross-realm array equality and missing mock helper; regression harness adjusted. **Do not label final HEAD as passing before checking Hosted CI.** PR remains open and should only merge upon explicit user authorization and clean final review.

## 2026-10-28 — PR #5 fourth formal Codex review P2 remediation
- Latest completed Codex review of `c699fd5a` found two **P2**, both reproducible in Node VM:
  1. An in-flight `/api/jobs/{id}` GET can reject after *same case* was edited. Old `active()` included case fingerprint so was false and the catch cleared the last poll without releasing the disabled vocabulary or analysis button.
  2. Deleting the last telegram with code 101 pruned current `hypothesis_marks` but did not prune `hypothesis_revision_history.snapshots`; `presentCase()` could accept the archived snapshots, so Undo resurrected invalid code 101.
- In `src/han_codebook/static/index.html`, vocabulary and analysis polling catch handlers now distinguish **error-cleanup ownership** from **still-valid content**: they restore buttons and retire the request only when request serial, originating case object/generation and Job ID are still current, even if the input fingerprint changed. They do not touch controls owned by a new job or a different case.
- `deleteMessage` prunes the current multi-idea/mark mappings, all in-memory candidate/mark undo snapshots, AND persisted `hypothesis_revision_history.snapshots` by the remaining code set **before** calling `presentCase`, preserving codes still present in other messages.
- Added actual Node VM scenarios to `tests/js/test_case_provenance.js` (edited case + rejected GET, new same-case job not unlocked by old failing job, analysis failure recovery) and `tests/js/test_delete_message_history.js` (deletion, persisted history reload, Undo/Redo, valid shared code, cancellation), with Python wrapper in `tests/test_case_provenance_ui.py`.
- Do not claim latest Hosted CI or new Codex review passed until GitHub confirms; PR #5 must remain open until reviewed and explicitly merged by user.


## 2026-10-28 — PR #6 Local model configuration, Word reports, 0..20 rounds, bold what-if hypotheses
- After PR #5 squash merged into main at `1fd29c7`, user requested: user-editable LLM rounds above 3, browser-side model endpoint settings inspired by `hun186/AI-Simulated-Patient`, Word report with readable tables, clarity on prior weights, visible feedback and color-coded manual challenges to verified plaintext.
- New branch `feat/ui-llm-settings-word-bold-hypotheses`, PR #6. Frontend rounds numeric 0..20; backend `/api/start` now accepts 0..20 integers only, aligned with existing `config.py` upper bound 20.
- New `model_settings.py` + `web.py` GET /api/settings, POST /api/settings/llm, POST /api/settings/test: safe YAML persistence via atomic replace, local/RFC1918-only validator with explicit LAN opt-in+exact allowlist; env-variable **name only**, not secret; no public API providers; metadata-only TCP plus models probe; block edits while jobs active.
- New `report_docx.py` and `python-docx` dependency; Word report has 4+ tables and unverified warnings. `/api/jobs/{id}/report.docx` returns a genuine OOXML document. Existing Markdown downloads remain; archived historical run folders can be converted on demand if valid result+SQLite exist.
- UI adds fixed error toast, explanation of prior weight as a subjective initial lexicon preference, green verified / blue unverified / purple counterfactual chips; explicit confirm for `bold_hypotheses` (verified code only, independent term/notes), reversible delete. `core.validate_case` guards against unconfirmed/non-anchor/same-term overrides; `run_agent` carries them as display/report-only metadata and preserves verified anchors. **No counterfactual solver run or change to trusted anchors**.
- Tests `tests/test_word_model_settings.py` for URL/no-secret persistence, genuine ZIP Word table output and HTTP, immutable anchor semantics; `tests/js/test_bold_review_ui.js` for explicit confirm, alternative display, reversible clear and original known-pair preservation. Hosted CI / Codex review must be checked for latest HEAD; PR OPEN, not merged.

## 2026-10-28 PR #6 Formal Codex review P1/P2 remediation
- Initial formal Codex review for HEAD `44e5f890` identified P1: Windows setup and README installed only PyYAML, so Word dependency was missing; P2: deleting last known-plaintext alignment for code still present in other telegrams could preserve invalid bold alternative and block save/inference.
- P1: Windows `setup_windows.bat` now runs `pip install -e .`, Docker includes `python-docx`, README Linux/Windows/offline wheel instructions updated. `web.py` preserves completed analysis and Markdown with explicit warning if Word library is missing, rather than failing an otherwise valid analysis.
- P2: `deleteMessage` now filters `bold_hypotheses` against **surviving verified aligned anchors**, not just still-present numerical codes, and removes same-term alternatives. `applyBoldHypothesis(clear=true)` can clear a stale alternative without requiring the old anchor to still exist. `tests/js/test_delete_message_history.js` adds a matched example where numeric code survives but unique aligned plaintext disappears, and a separate example where the alignment survives and the bold mark must remain.
- Latest branch HEAD and Hosted CI must be checked; only then request new formal review. No merge without explicit user direction.


## 2026-10-28 — PR #6 P2 LLM configuration race remediation (post-25d0920)
- GitHub PR #6 remained OPEN at verified pre-change HEAD `25d0920cd0ffe7b500bbd5cab16b4147e522534d`; latest Codex review had one unresolved P2 on `web.py`: LLM settings write released `jobs_lock` after the active-job check, before atomic YAML replacement. A competing `/api/start` could accept an analysis on the old approved endpoint while its worker loaded a replacement endpoint.
- Commit `64a21cb69f83e6995d4e9d6cac8cc3e419ecab8a`: keep active-job check and entire `save_model_settings()` call inside the same `jobs_lock` critical section as analysis/vocabulary job admission. At admission, deep-copy the LLM config; analysis `run_agent` and vocabulary `generate_vocabulary` consume only that captured per-job snapshot, not a later mutable YAML read. No change to trusted known-plaintext anchors or LLM destination allowlist.
- Commit `d416d44d5f025131ca5e32fb05caadcfcc301326`: add `tests/test_llm_config_race.py` with a controlled blocked settings write racing `/api/start`, deferred analysis worker after external YAML mutation, and deferred vocabulary worker after external YAML mutation. Tests use mocked inference; they do NOT transmit actual research data to a model. The settings HTTP API must reject edits while jobs are queued/running.
- The push CI `tests` run 40632292237 covers Python 3.10/3.12, unittest, and offline benchmark. Its outcome must be verified live; this memory entry itself is not proof of CI success. A new formal `@codex review` must be requested against the HEAD including this note once CI is checked. PR #6 must remain unmerged until review is clean and user explicitly authorizes merge.

## 2026-10-28 — Adaptive LLM vocabulary on every round; optional human review
- User requested LLM may propose new candidate vocabulary **in every analysis round** after considering side information and the current decoding hypotheses; researcher review must be optional so disabling it creates a fully automatic, bounded multi-round pipeline.
- Independent branch `feat/adaptive-llm-vocabulary-optional-review` from `main` (PR #8 GUI sync remains separate). `adaptive_vocabulary.py` constructs a non-oracle, metadata-conditional packet including whitelisted cipher/auxiliary data, cross-message time-link candidates, current *unverified* mappings and reliable segmented anchors; it parses new LLM candidate terms, deduplicates, caps at 32 new terms/round and 128 dynamic terms total. Outputs only hypotheses, never verified plaintext; original case is deepcopied before dynamic changes.
- `agent.run_agent` accepts `adaptive_vocabulary`, `vocabulary_reviewer`, and injected `vocabulary_query`. Each LLM round can first expand candidate words and recompute score, then request code-specific hints from the same private configured LLM and rerank. Existing no-adaptive mode and offline 0 rounds preserved.
- `web.py` `POST /api/start` accepts `candidate_mode: static|automatic|human`; automatic continues without human intervention; human pauses each vocabulary step at `awaiting_review` with a 600s fail-closed decision gate and `POST /api/jobs/{id}/review` explicit subset approval. Busy slots remain reserved while awaiting review. GUI offers dropdown and per-round checkbox panel; no public API or secret endpoints. Current auxiliary evidence is a snapshot at job start; newly added evidence during job requires starting a new analysis.
- New `tests/test_adaptive_vocabulary.py` uses mock private-model calls for 2 adaptive rounds, metadata ablation, reviewer rejection, no gold access, immutable input. See `docs/adaptive-vocabulary.md`.
- **Status**: code committed but no verified Hosted CI/Codex Review yet; do not claim ready, merge, or live production behavior until actual GitHub checks and formal review pass. PR #8 and PR #7 are distinct active work and must not be merged implicitly.

## 2026-10-28 — PR #9 latest validated implementation (before formal review)
- Added `tests/test_adaptive_vocabulary_web.py`: mocked agent inside real loopback HTTP server demonstrates pending human approval, rejecting non-offered terms, single submission, exclusive job gate and failure cleanup; confirms automatic mode supplies no reviewer and static/0-round protections. GUI browser VM regression `test_case_provenance` initially failed on an uninitialized mock `dataset` property; fixed in `static/index.html` with a safe fallback while keeping real browser logic unchanged. Test output now provides notices on future startup failures.
- **Hosted CI run `40672204870` SUCCESS** on HEAD `9de0be4b2bc4cd79cf7edcf12d75cb81b61850dc`: Python 3.10 and 3.12 each completed **117 unittests PASS** plus the benchmark command. Adaptive-specific tests, human approval HTTP flow, original GUI case/provenance regression all explicitly passed.
- Current head will change when this memory is committed. Verify the new final HEAD's Hosted CI and request formal Codex review on that exact SHA. No real LAN LLM execution performed, no production merge. PR #9 separate from #8 GUI parity and #7 holdout; canonical GUI synchronization with #8 must be handled after target merge.

## 2026-10-28 — PR #9 Codex P2 response: review cancellation + trace pairing
- Formal Codex on `351fdad00addc0609c8c7c7eec960e4a8abda1ae` started and identified two P2 threads: `PRRT_kwDOVY2jks6xE5ng` (when research case changes, client drops old polling and human-approval job remains stuck awaiting review for 600s); `PRRT_kwDOVY2jks6xE5no` (captured vocabulary and code-level LLM exchanges both recorded as `llm_request/llm_response` within the same round, UI mistakenly pairs the code prompt with vocabulary response).
- Fixes: `agent.py` prefixes vocabulary capture as `vocabulary_llm_request/response`; UI groups by phase and round for exact request-response pairing. Added trace assertions in `tests/test_adaptive_vocabulary.py`.
- Added `POST /api/jobs/{id}/cancel` limited to active human-review jobs, with `cancel_requested` and `cancelling` status that retains active job gate until the original worker actually stops; reviewer checks cancellation before and after the 600s wait and wakes promptly if a pending review is canceled. `agent.run_agent` checks optional `cancel_check` between major per-round stages. UI `start()` issues cancellation on stale case edits/switches, including delayed job creation before first poll. Never auto-accept stale review candidates.
- Added real HTTP regressions in `tests/test_adaptive_vocabulary_web.py` to cancel while waiting and before review is registered, rejecting approval after cancel, and allowing new jobs after cleanup. Updated `docs/adaptive-vocabulary.md`.
- **Updated HEAD and Hosted CI results must be verified again.** Old 117x2 tests SUCCESS on `9de0be4b`, but the latest cancellation and trace fixes are unreviewed as of this memory update. Reply to and resolve precise P2 threads only after Hosted CI confirms fixes; request fresh formal Codex on exact new HEAD. PR OPEN, never merge by inference.
