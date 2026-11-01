# Prioritized backlog

- P0: Verify the packaging and live Ollama JSON responses in user environment; document offline deployment with actual endpoint name.
- P0: Extend current deterministic synthetic benchmark to multiple independent dictionaries and independently collected public historical corpora; add blind hold-out at the phrase-vocabulary level.
- P1: Optional probabilistic alignment for plaintext not segmented to codes (manual acceptance gate) — preliminary **bounded offline suggestion CLI** introduced on PR #19 (branch feat/unaligned-plaintext-review-20261031), without automatic anchor promotion; calibrated probabilities, browser review acceptance and full variable-boundary inference remain TODO.
- P1: Character+phrase mix, homophones, added nulls, code-group aliases; evaluate joint search.
- P1: Metadata model selection that can abstain when contextual priors harm results — PR #18 merged into main (`dd9b7a428a11`), post-merge CI #41162052798 SUCCESS. Paired offline ablation is diagnostic only; independent corpus calibration and safe automatic abstention remain TODO.
- P1: Independent verification with held-out known-plaintext pairs and failure categorization — PR #17 merged into main (`1630ec87`); post-merge Hosted CI `41101409138` SUCCESS. This still does not establish blind historical decipherment.
- P2: MCP interface for Decipher-like agents, safe tool budget and long-running jobs.
- P2: Web UI, investigation provenance explorer, task state machine and worker coordination.

- PR #20 anchor-aware bounded segmentation robustness merged into main as `490da8ea0bfaff76400df51a0cb9c788872ac2ba` after latest-head 8/8 Hosted CI and official Codex Completed/No Findings. Post-merge main CI requires separate verification.
- PR #21 merged into main as `3732a72ad43ed545b8d0b41ddb04608e1076360d`; main post-merge GitHub CI #41165785923 SUCCESS (confirmed 2026-10-31). Independent offline holdout Top-N report does not expose plaintext.
- PR #22 explicit CLI researcher confirmation merged as `5c19ae6b9acf0d34125bf851b8e3959b459f26d7` after latest-head 8/8 Hosted CI, formal Codex Completed/No Findings and resolved P2 fixture; main post-merge CI pending fresh verification.
- PR #23 merged into main as `a6ad3b60481e5e57dbd75582449cf8d5a9baa5f2` after latest-head 8/8 Hosted CI and formal Codex Completed/No Findings; main post-merge CI must be independently verified.
- PR #24 browser explicit alignment review UI actually merged as `f693b3e1a10a9f7b6ed908017a38749d9100a493`, latest PR HEAD `14b001326d4158fd31cf65cb48c1a6fc70ad4936` 8/8 Hosted CI SUCCESS and official Codex Completed/No Findings; two P2 threads resolved. Postmerge main CI #41182294339 SUCCESS verified 2026-11-01.
- PR #25 actually merged to main as `93ea3b6194e875ce08c258d453840c4958932e87`; main push CI #41271860550 SUCCESS (2026-11-01). The 17-check Windows/Linux offline synthetic loopback smoke is implemented, not proof of human or live Ollama validation.
- PR #26 case-wide 2,000,000 expansion cap **MERGED** as `13a6959254631e054f4830b209b40700cfdba6fd`; exact-head Hosted 8/8 Python/Windows/Docker CI, Codex Completed/No Findings, main CI #41286937989 SUCCESS verified 2026-11-01.
- Current: optional `--extended` on one-click synthetic alignment smoke; preserve 17-check default, add 4 long-text/repeated-code/case-wide budget checks to make 21 total. Windows/Linux wrappers forward flags, output stays sanitized. Hosted CI/Codex/merge pending.
- Next: private workstation real cases and separately authorized live Ollama; public Vercel remains Mock-only.

- 2026-11-01 current main `4231aa2f5d46551f1077940fdb8658029621f870` (#28 merged, postmerge CI #41287789928 SUCCESS). PR #29 researcher known-pair row GUI remains OPEN: last seen HEAD `329ffa02e2d9ed9c24e84d0f288ba80074cdce2e`, 8/8 Hosted CI success but latest-head formal Codex No Findings not observed; do NOT merge it without gate.
- **Active branch `feat/one-click-run-diagnostic-bundle-20261101`**: GUI download share-safe ZIP and explicitly confirmed full private ZIP for completed/failed research runs; persist actual input case and audit, capture run settings, strict same-origin POST, bounded files, partial status, no oracle, public Vercel Mock disabled. Hosted CI/formal Codex Review and merge PENDING.
- Next: private workstation case 07 one-round endpoint smoke, then case 08 baseline vs three rounds with/without metadata and compare actual downloadable diagnostic ZIPs. No user endpoint run or historical accuracy result claimed.

## 2026-11-01 — User explicitly deferred all LAN LLM validation
- **DEFERRED / TODO, not authorized to run now**: case 07 live local LLM 1-round schema test, case 08 live 3-round with metadata ON/OFF, real LLM prompt/response capture, comparison with 0-round offline, and any live workstation/Ollama claims. User currently cannot use any LLM. Do not auto-run or fabricate results.
- PR #30 one-click diagnostic ZIP **actually MERGED** into main `c632d459a7f0019a05962ae37a6822fbd5e404a9`; main CI #41300662004 SUCCESS. Safe/private, terminal partial, gold isolation validated by Hosted CI, not by live LLM.
- PR #29 per-row known-pair GUI remains OPEN, 8/8 Hosted CI but no latest-HEAD formal Codex No Findings at last check; requested fresh review for `329ffa02e2d9ed9c24e84d0f288ba80074cdce2e` on Nov 1. Do not bypass gate.
- Active `feat/offline-case08-ablation-operator-20261101`: one-click Windows/Linux zero-LLM metadata on/off pair with matched solver parameters, separate read-only post-solve synthetic gold scoring, deterministic summary, private and safe diagnostic ZIPs, unique no-overwrite output directory, and Hosted regression tests. Awaiting CI/formal exact-head Codex and gate.

- PR #31 zero-LLM case08 paired ablation MERGED as `0b6a59e1020886cd0f05e58a1c7c7df7fdc4629b`; main push CI #41302563434 SUCCESS.
- **PR #29 CONFLICT RESOLUTION** (2026-11-01): original per-row researcher GUI HEAD `329ffa02e2d9ed9c24e84d0f288ba80074cdce2e` was 8/8 Hosted CI and Codex Completed/No Findings but made non-mergeable by later PR #30/#31. New two-parent merge commit reconciles original GUI with current diagnostic ZIP interface, Vercel Mock parity and newest study/docs. Latest merged HEAD must receive NEW full CI and Codex review before merge. No live LLM testing.
