# Prioritized backlog

- P0: Verify the packaging and live Ollama JSON responses in user environment; document offline deployment with actual endpoint name.
- P0: Extend current deterministic synthetic benchmark to multiple independent dictionaries and independently collected public historical corpora; add blind hold-out at the phrase-vocabulary level.
- P1: Optional probabilistic alignment for plaintext not segmented to codes (manual acceptance gate).
- P1: Character+phrase mix, homophones, added nulls, code-group aliases; evaluate joint search.
- P1: Metadata model selection that can abstain when the contextual priors make performance worse.
- P1: Independent verification with held-out known-plaintext pairs and failure categorization — recovered on mainline integration branch; requires latest Hosted CI, formal Codex Review and explicit merge approval. Does **not** establish blind historical decipherment.
- P2: MCP interface for Decipher-like agents, safe tool budget and long-running jobs.
- P2: Web UI, investigation provenance explorer, task state machine and worker coordination.

- Next: quantitative observation reliability ablation and robust longer-text token alignment; browser UI is single-user loopback only.
