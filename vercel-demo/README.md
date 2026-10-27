# Han Codebook Agent — Vercel Mock PoC

Static, self-contained **synthetic public demonstration**. Vercel project's Root Directory must be `vercel-demo` and framework should be `Other` (null). It does **not** connect to OpenAI, Ollama, Qwen, private IPs, or any external API. There are no credentials, servers or persistent DB.

Features: same-codebook synthetic 10/25/50/100 messages, Python-solver-precomputed statistical baseline, explicit **deterministic mock** candidate hints and corresponding Python-rescored snapshots, per-code candidate reading, source metadata, manual undo/redo hypothesis previews, export/import JSON, after-click synthetic gold answer reveal.

Limits: the LLM never runs on Vercel, batch progression is a UI simulation, no re-solve of the statistical model happens when a researcher adds a manual hypothesis; the manual row just previews a local mapping substitution. This PoC uses a publicly inspectable synthetic gold JSON, which is not suitable for blind benchmarking. Real secure/offline analysis remains the local `run_web_windows.bat` workbench.

## Rebuild fixtures and test

From repository root:

```bash
PYTHONPATH=src python scripts/build_vercel_demo.py
python -m unittest discover -s tests -q
```

To preview locally: `python -m http.server 8767 -d vercel-demo` and visit `http://127.0.0.1:8767`.

Never deploy with `config.yaml`, private user inputs, SQLite audits or real LLM keys in this static app. `data/gold.json` is **synthetic**, and fetched only when a visitor clicks reveal.

## 研究員假說回饋 Mock（新增）

本展示版會在執行 Mock 後，將「偏好／排除／試鎖」及 Undo／Redo 即時回饋到**瀏覽器內的確定性候選重評分**，而不只是替換「研究員預覽」欄位。`mock_solver.js` 只依據可觀察密文相鄰碼組與既有統計／Mock 候選推導詞序相容度，對受到標註影響的碼組重新評分並列出前後變化，沒有隨機替換答案、沒有任何實際 LLM API 呼叫。試鎖是可撤銷的硬假說；偏好是加權、未必一定改變；排除會移除該候選。

- 原始統計／原始 Mock 正確率和趨勢圖保留為**無標註基線**，不隨研究員操作竄改。
- 「模擬 AI 建議後」顯示研究員標註後的重評分；下方顯示碼組前後差異、間接受影響的碼組、可檢查的計算說明。若沒有足夠鄰近線索，其他碼組的 Top-1 可能不變。
- 合成正確明文仍只在按「揭曉」後載入，重新評分器完全不讀 `gold.json`。揭曉後可另外查看**目前** Mock 的正確率，與原始評測基線區隔。
- 清空標註或 Undo 回空白版本，恢復**原始 Mock**，不需要執行任何網路呼叫。更換 10／25／50／100 封則重置此獨立實驗的標註與重評分結果。
- 此處的詞序相容度來自既有**未驗證候選**，只為透明展示因果與研究流程，**不是**可靠語言模型或真實密碼破解效能。
