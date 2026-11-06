# Agent instructions

Read `.codex/project.md` and `.codex/memory.md` before changing code. The latest GitHub branch/PR/CI status, once this repository is published, must be checked before work. Do not infer Hosted CI/review state from local tests.

Rules:
- Preserve trusted known-plaintext alignments. Reject contradictions rather than overwriting them.
- Never label model-generated Chinese as verified historical plaintext.
- Never use `ground_truth` inside the solver or LLM prompt; it is for synthetic evaluation only.
- Maintain `python -m unittest discover -s tests -v` and update `.codex/memory.md` with concrete outcomes.
- Respect offline-first local inference: localhost by default. Remote RFC1918 hosts need `allow_private_network=true` and an exact `allowed_hosts` entry. **Arbitrary public API endpoints are prohibited.** The single explicitly user-authorized public exception is DeepInfra: only `provider=deepinfra`, `allow_external_api=true`, exact HTTPS base `https://api.deepinfra.com/v1/openai`, a key referenced from an environment variable, and per-research-run confirmation. Never infer this consent from LAN access, never silently activate it, never follow redirects with Bearer/case material, and never permit unrestricted public-host lists. `rounds=0` stays offline. Vercel public demo stays Mock-only.
- Distinguish research plans from implemented and verified features.
