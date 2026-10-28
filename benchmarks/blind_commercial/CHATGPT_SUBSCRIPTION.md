# 真正使用 ChatGPT 訂閱額度的 GPT-6 Astra 盲測

**此為 Codex CLI 經 ChatGPT 訂閱授權的真實模型推論，無需另購 API credits。**
不涉及模擬 LLM 內容、瀏覽器爬蟲、反向工程 ChatGPT 端點，亦不把既有的
51.67% 固定語法位置實驗當成成績。此方法會消耗 ChatGPT 訂閱所包含
的 **Codex／Work** 使用量，並受訂閱速率與用量限制。

## 運作方式

原 `han_codebook.agent.run_agent`（每輪自動新增候選詞、重新約束求解、
LLM 碼組假說、重新求解）仍使用它原有的本機 OpenAI-compatible
`/v1/chat/completions` 位址。Benchmark-only 的 `LoopbackGateway`
把這兩種請求透過 `codex_subscription.codex_subscription_reply()` 轉成：

```text
本機原 Agent
  → 127.0.0.1 临時受驗證端口
  → codex exec --model gpt-6-astra --sandbox read-only --output-schema ...
  → ChatGPT 訂閱內 Codex 模型
  → 結構化 JSON 回應
  → 原 Agent 自動續行、SQLite 記錄
```

每個模型請求是一個**獨立的真實 Codex 推論**（非模擬答覆）。
命令採 `--ephemeral`、`--ignore-user-config`、`--ignore-rules`，
於獨立臨時工作目錄以唯讀模式執行，並對事件記錄拒絕
shell/file/MCP/web tool invocations。也無需授權程式開啟任何
收錄正確答案的私有目錄；金鑰/答案永不送入提示。

兩點對外說明不能省略：

1. **不同於 Responses API 的嚴格等價測試。** Codex CLI 把
   原有 system/user 內容包在自己的單一提示、JSON Schema 約束
   與預設代理框架內。因此即使請求 `gpt-6-astra`，結果仍應
   命名為「GPT-6 Astra requested via Codex CLI / ChatGPT subscription
   baseline」，不能冒稱精確等價於直接 OpenAI Responses API。
2. CLI `--model` 是指定的模型名稱，JSONL 不一定包含服務端
   *獨立認證*的實際模型 ID；報告如實註明模型身分依據。
   真正付費的 Responses API 模式仍保留在相鄰的 `run.py`
   `--provider openai-api`。

## 你的 Windows 電腦怎麼啟用

1. 安裝最新版官方 Codex CLI（詳見官方文件）。
2. 在你的 Windows PowerShell / 終端執行：
   `codex login`。請選擇 **使用 ChatGPT 登入**，勿選 API Key。
   這一步需要你自行完成授權，我無法從 GitHub Connector 代你登入。
3. 核對：`codex login status` 必須顯示 ChatGPT 登入。
4. **API Key 的環境變數 `OPENAI_API_KEY`、`CODEX_API_KEY`、
   `CODEX_ACCESS_TOKEN` 需為空。** 程式若發現這些憑證便拒絕執行，
   避免誤走另外收費的 API。
5. 保持隱藏答案在 GitHub Repository **以外**的獨立安全路徑。
   先產出一組新的未知碼本：

```powershell
python benchmarks/blind_commercial/generate.py `
  --public-dir artifacts/blind_subscription/public `
  --private-dir D:\ProtectedHanGold `
  --repeats 1
```

先測小規模但**真實**的 1 組／1 輪／16 次訂閱模型請求：

```powershell
python benchmarks/blind_commercial/run.py `
  --public-dir artifacts/blind_subscription/public `
  --out-dir artifacts/blind_subscription/locked_results `
  --provider codex-subscription `
  --model gpt-6-astra --effort high --rounds 1 `
  --max-calls 16 --timeout 600 `
  --allow-subscription-usage
```

這 16 次包含 1 組未知碼本 × 10／25／50／100 封
× 有／無輔助情報 × 1 輪 × 2 次模型推論。

結束後**必須先有 predictions_LOCKED.sha256** 才能揭盲：

```powershell
python benchmarks/blind_commercial/score.py `
  --public-dir artifacts/blind_subscription/public `
  --private-dir D:\ProtectedHanGold `
  --results-dir artifacts/blind_subscription/locked_results
```

可再使用 `make_report.py` 輸出包含逐輪分析、
100 封原始密文／外部觀察／兩個最終還原／正確明文／逐碼判定的 Word。

此例只有一輪，僅為技術與用量 pilot。若要做完整 3 組 ×
5 輪的統計研究，需要 240 次推論；ChatGPT Plus 的 Astra
額度可能無法一次完成，**禁止透過爬蟲或繞過用量限制**。
依官方配額或重置時點分批執行，且不得在已揭盲後任意調整
提示或續跑同一個被揭盲的碼本。中途額度不足的部分結果不計為
完成的正式試驗。不要將已登入的 Codex 認證檔上傳 GitHub。

## 原始官方依據

- [Codex 使用 ChatGPT 方案](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan)
- [Codex CLI 非互動執行](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Codex CLI 指令與模型、JSON Schema 參數](https://learn.chatgpt.com/docs/developer-commands)
- [ChatGPT 訂閱與 API 計費分開](https://help.openai.com/en/articles/9039756-managing-billing-for-chatgpt-and-the-api-platform)
