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
- Active: canonical local GUI manual candidate preview, explicit selection, researcher retyping and separate accept/save; Node VM tests and Vercel UI sync, with PUBLIC MOCK buttons disabled and endpoint calls blocked. Formal Hosted CI/Codex Review still pending.
- Next: after UI merge, evaluate usability on user workstation with real cases and long unsegmented messages; no real Qwen or historical decipherment assumed.
