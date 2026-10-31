# Prioritized backlog

- P0: Verify the packaging and live Ollama JSON responses in user environment; document offline deployment with actual endpoint name.
- P0: Extend current deterministic synthetic benchmark to multiple independent dictionaries and independently collected public historical corpora; add blind hold-out at the phrase-vocabulary level.
- P1: Optional probabilistic alignment for plaintext not segmented to codes (manual acceptance gate) — preliminary **bounded offline suggestion CLI** introduced on PR #19 (branch feat/unaligned-plaintext-review-20261031), without automatic anchor promotion; calibrated probabilities, browser review acceptance and full variable-boundary inference remain TODO.
- P1: Character+phrase mix, homophones, added nulls, code-group aliases; evaluate joint search.
- P1: Metadata model selection that can abstain when contextual priors harm results — PR #18 merged into main (`dd9b7a428a11`), post-merge CI #41162052798 SUCCESS. Paired offline ablation is diagnostic only; independent corpus calibration and safe automatic abstention remain TODO.
- P1: Independent verification with held-out known-plaintext pairs and failure categorization — PR #17 merged into main (`1630ec87`); post-merge Hosted CI `41101409138` SUCCESS. This still does not establish blind historical decipherment.
- P2: MCP interface for Decipher-like agents, safe tool budget and long-running jobs.
- P2: Web UI, investigation provenance explorer, task state machine and worker coordination.

- Next: verify anchor-aware reachability for longer unsegmented plaintext (new focused PR; Hosted CI/Codex review required), then add separately controlled manual acceptance and held-out validation; browser UI remains single-user loopback only.
