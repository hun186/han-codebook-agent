# Agent instructions

Read `.codex/project.md` and `.codex/memory.md` before changing code. The latest GitHub branch/PR/CI status, once this repository is published, must be checked before work. Do not infer Hosted CI/review state from local tests.

Rules:
- Preserve trusted known-plaintext alignments. Reject contradictions rather than overwriting them.
- Never label model-generated Chinese as verified historical plaintext.
- Never use `ground_truth` inside the solver or LLM prompt; it is for synthetic evaluation only.
- Maintain `python -m unittest discover -s tests -v` and update `.codex/memory.md` with concrete outcomes.
- Respect offline-first local inference: no external LLM calls unless specifically opt-in; remote RFC1918 endpoints require explicit allow_private_network=true plus matching allowlisted host; no public API endpoints.
- Distinguish research plans from implemented and verified features.
