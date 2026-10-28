# Genuine blind commercial-LLM codebook evaluation (PR #12)

**This is a NEW experiment protocol, not an achieved accuracy result.**

The earlier synthetic adaptive study that reported **51.67%** (withdrawn PR #11)
is methodologically unsuitable as evidence of cryptanalytic capability:
its algorithm was given privileged fixed semantic positions and the external
observations were deliberately close to plaintext. The first purported
GPT-6 study (13.33%) also was not the real end-to-end model-driven agent.
**Neither score should appear on the formal model-performance dashboard or in
a final claim that GPT-6 can/cannot break codebooks.**

## What changes

- **Fresh secret codebook per replication** using cryptographically random
  numeric assignments. Codebook and plaintext are written ONLY into a
  separate private folder **outside GitHub**. Generated public input reveals
  only cipher groups, sender/recipient/dates and noisy observations.
- **Variable-length coded messages** built from multiple independently chosen
  Chinese phrase clauses, optional fragments, reorderings, and no published
  fixed slot labels. Twelve private interleaved event threads produce
  repeated but shifting reports over time; the model never receives the
  thread membership or the private original text. The generator necessarily has language templates (this
  remains synthetic, NOT a validated historical cipher simulation); the
  original solver and LLM are not given the generator, original segments,
  a word→code list, slot roles, or plaintext targets.
- **Mixed external evidence:** observations with uncertainty, time shifts,
  mismatched details and irrelevant clutter. No "relevant" flag in LLM input.
- **Actual existing `han_codebook.agent.run_agent`** with
  `adaptive_vocabulary=True`, `vocabulary_reviewer=None`,
  per-round vocabulary calls, solver rescore, code-hypothesis calls and
  solver rescore. NO human approval at any round.
- A benchmark-only, **explicitly opt-in loopback bridge** translates the
  agent's private `/v1/chat/completions` requests into OpenAI
  `https://api.openai.com/v1/responses`, with `model=gpt-6-astra`,
  `reasoning.effort=high` (configurable). Production project/GUI still
  forbid unrestricted public endpoints. This bridge is the *only*
  cloud-facing component and is not installed in the production web server.
- For each independent secret codebook, identical **nested** 10, 25, 50,
  100 message subsets are tested **with and without auxiliary information**
  using the same model and round count. Default 3 independent replications,
  5 adaptive rounds, 2 calls/round -> up to 240 paid API requests.
- **All 100 messages** (not only the first 50) are included in both the
  vocabulary and code-proposal LLM context at the 100-message stage.
- Complete API/audit logs and final predictions are **hashed and locked**
  before the separate scorer has access to the private codebook.
  Errors/timeouts are a failed or incomplete run, NEVER scored as success.

The codebook is a substitution over Chinese words/phrases, not an additive
superencipherment. Better synthetic validity does not imply authenticity.
A model may still discover language templates by analyzing the corpus; that is
part of the evaluation, not privileged knowledge injected into the solver.
The analyst may not adapt prompts by reading the hidden answers during a run.

## First run

Python 3.10+, install the local project with `pip install -e .`. The
benchmark runner requires no `openai` SDK; it uses the standard HTTP client
through a loopback bridge. For a separate score, the package's standard
dependencies include PyYAML; `python-docx` is used by the local report but
not the benchmark itself.

**Generate new secret experiments:**

```bash
python benchmarks/blind_commercial/generate.py \
  --public-dir artifacts/blind_20261029/public \
  --private-dir /secure/outside-repo/han_holdouts \
  --repeats 3
```

On Windows, choose a protected directory outside the cloned GitHub working
tree for `--private-dir` (not a public folder). Do **not** provide
`--fixture-seed` for any real benchmark; it exists solely for automated
no-network regression tests.

**Explicitly permit external GPT API processing of the synthetic-only input:**

```bash
# Define OPENAI_API_KEY securely in the local process environment first.
python benchmarks/blind_commercial/run.py \
  --public-dir artifacts/blind_20261029/public \
  --out-dir artifacts/blind_20261029/locked_results \
  --model gpt-6-astra --effort high --rounds 5 \
  --max-calls 240 --allow-cloud-api
```

This performs actual paid API requests. A ChatGPT Plus/Pro login **is not**
an API credential. If the API credential, quota or model entitlement is not
available, the run cannot start; do NOT substitute a browser mock or claim
GPT-6 was tested. To minimize costs use one replication and a smaller
round budget as a **separate pre-registered pilot**, not as full results.

**Only AFTER the runner finishes and writes its SHA-256 lock:**

```bash
python benchmarks/blind_commercial/score.py \
  --public-dir artifacts/blind_20261029/public \
  --private-dir /secure/outside-repo/han_holdouts \
  --results-dir artifacts/blind_20261029/locked_results
```

The scorer produces `evaluation.json` and `evaluation.csv`. It includes:
unique code Top-1, Top-5, code-position-weighted accuracy, whole-telegram
exact recovery, unresolved codes and vocabulary coverage by subset, condition
and replication. Report all seed runs, not just the best. Don't publish
any GPT-6 success rate before a real API run.

## Safety and falsifiability

- Keep **all** private reference JSONs outside the repo and the model prompt.
  Do not upload the hidden key to Vercel, GitHub, or any unscored case data.
- The public fixture checksum binds predictions to the right reference.
- The locked prediction file and SQLite event audit prove completed rounds.
  Always report actual API model ID, usage, latency and failures; compare
  input token budget for the 100-message condition with 10-message samples.
- Estimate uncertainty across the independent replications. If results
  remain low, investigate missing anchors, cipher identifiability and
  auxiliary evidence quality, not merely increase model effort.
- Do not include historical codebooks, real sensitive intercepted messages,
  or user proprietary intelligence in the external API benchmark.
- Original local LAN model settings and Vercel Mock demo remain separate.
- A convincing high score would need repeated new blind studies without
  privileged syntax or labels, ideally a second generator and real-world
  (legally distributable) historically documented evaluation data.

See [OpenAI reasoning models](https://developers.openai.com/api/docs/guides/reasoning)
for model and Responses API guidance.
