# Ollama native JSON (local/LAN only)

## Why this mode exists
Some thinking models answer OpenAI-compatible `/v1/chat/completions` with
`finish_reason=stop`, nonempty reasoning, but empty `message.content`.
The response cannot be accepted as a JSON result. Increasing the context window
alone does not fix this failure. Never treat the reasoning field as final answer.

## Choose a transport deliberately
* **Ollama 原生 API** in the local workbench stores `llm.provider: ollama`
  and uses `http://127.0.0.1:11434/api/chat`, or an exact allowlisted
  private LAN host such as `http://192.168.0.134:11434/api/chat`. Enter only
  the server root as `base_url`, **not** `/v1` or `/api`.
* The native request sets `stream:false`, `format:"json"`,
  `think:false` by default (`reasoning_effort:none` also maps to false).
  If the operator explicitly requests another supported reasoning level in
  YAML, the model may still generate thinking; final JSON remains mandatory.
* **內網 OpenAI-compatible** retains `llm.provider: local` and
  `/v1/chat/completions`, for reverse proxies/vLLM. Selecting a port alone
  must not change the transport.
* **DeepInfra** remains external, consent-gated, and unchanged. No automatic
  fallback, second paid request, or implicit switch to another service.

For command-line research, set `provider: ollama` under `llm:` in your
**actual** YAML file, or pass `--provider ollama`. For example:

```yaml
llm:
  provider: ollama
  base_url: "http://192.168.0.134:11434"
  model: "qwen3.8:latest-128k"
  timeout_seconds: 180
  allow_private_network: true
  allowed_hosts: ["192.168.0.134"]
  reasoning_effort: none
  response_format: json_object
```

Keep project and analysis sections in the existing file. Do not commit real
case data, credentials or private prompts. Run `python -m han_codebook
--config config.yaml --check-llm` to test TCP and Ollama `/api/tags` metadata
without sending case data. Actual inference requires a separate user-initiated
research run. The GUI connection test is not a chat-completion test.

## Validation boundary
Offline mocked regressions cover native payload, native model-list parsing,
explicit allowlist, JSON-only acceptance and reasoning-only rejection. They do
not establish that a remote machine's Ollama version honors `think:false`,
or that any Chinese ciphertext was deciphered. If the real native model still
returns empty `content`, retain the failed diagnosis; do not fabricate terms.
For Ollama documentation, see https://docs.ollama.com/api/chat and
https://docs.ollama.com/capabilities/thinking.
