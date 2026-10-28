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

## GPT-5.6 Sol — 不需另購 API 額度的替代商用模型

如果你希望先用 GPT-5 系列而不是 Astra，這套同一個原系統
Agent 和相同盲測程序也支援 **`gpt-5.6-sol`**。這是官方
Codex 可選模型，會消耗你 ChatGPT 訂閱的 Codex 使用量，
**不是**在此對話直接呼叫的 API，也沒有繞過配額限制。

在本頁後面示例的 `run.py` 命令將
`--model gpt-6-astra` 改為 `--model gpt-5.6-sol` 即可；
其餘參數（`--provider codex-subscription`、
`--allow-subscription-usage`、`--resume` 等）不變。

- 請在**新的一組未知碼本和全新結果資料夾**跑 GPT-5.6 Sol。
- **不允許**在相同測試的 `--resume` 中途從 Astra 改成 Sol，
  更不能混合兩種模型的回覆算成單一模型正確率。
- 報告會明確記錄 `model=gpt-5.6-sol`、
  `provider=CODEX_CLI_CHATGPT_PLAN`、
  reasoning effort、逐輪回覆與已完成的真實推論次數。
- 模型可用性受你的 ChatGPT 訂閱、CLI 版本、當下的模型配額限制。
  本 repo 的無網路回歸只能驗證命令與回覆處理，**不能證明已經
  成功呼叫你帳號的 GPT-5.6 Sol**。

官方型號參考：https://developers.openai.com/api/docs/models/gpt-5.6-sol

## 你的 Windows 電腦怎麼啟用

1. 安裝最新版官方 Codex CLI（詳見官方文件）。
2. **建立獨立且只供此研究使用的 CODEX_HOME，不能沿用平常的 ~/.codex**，
   以免繼承其他模型/API Key、AGENTS.md、skills 或工具設定：

```powershell
$env:CODEX_HOME = Join-Path $env:USERPROFILE ".han-codebook-subscription"
New-Item -ItemType Directory -Force -Path $env:CODEX_HOME | Out-Null
codex -c 'forced_login_method="chatgpt"' -c 'cli_auth_credentials_store="file"' login
codex -c 'forced_login_method="chatgpt"' -c 'cli_auth_credentials_store="file"' login status
```

3. 登入時選 **Sign in with ChatGPT**，不得使用 API Key。完成後應確認
   專用 CODEX_HOME 下有 OAuth `auth.json`（**不要上傳、貼給任何人或提交 GitHub**）。
   程式對同一目錄的 `auth.json`、ChatGPT 登入方式以及 exec 強制參數都會
   驗證；若沒有訂閱授權、憑證有異或含其他 AGENTS/skills，就拒絕執行。
   這一步需使用者自己操作，本對話與 GitHub Connector 不會取得認證。
4. 確保 `OPENAI_API_KEY`、`CODEX_API_KEY`、`CODEX_ACCESS_TOKEN`
   都未設定（不能只在程式裡把 API Key 改為空字串）。
   同一 PowerShell 視窗須保持 `$env:CODEX_HOME` 設定。
5. 隱藏答案要放在 GitHub Repository **以外**的路徑。
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

### 當 Codex 訂閱額度用完：保留進度再恢復

如果第 4、150 或任何一個模型請求回覆 **quota / usage limit**：
- 程式寫入 `run_status.json`，狀態為 `paused_quota`，不會寫入
  `predictions_LOCKED.json`、評分或 Word。模型已成功回覆的請求先原子保存
  在 `successful_requests/`，已完成的試驗保存於 `completed_runs/`。
- **不會背景自動重試，不會繞過訂閱配額**。使用者待官方用量重置後，
  在同一個 CODEX_HOME、同一組隱藏答案及原始公開案例下，
  重跑完全相同的命令並在最後加上 `--resume`：

```powershell
python benchmarks/blind_commercial/run.py `
  --public-dir artifacts/blind_subscription/public `
  --out-dir artifacts/blind_subscription/locked_results `
  --provider codex-subscription `
  --model gpt-6-astra --effort high --rounds 1 `
  --max-calls 16 --timeout 600 `
  --allow-subscription-usage --resume
```

- 恢復時嚴格比對模型、回合、資料 SHA256 和求解器設定。已完成試驗
  的 SQLite 摘要必須一致。未完成試驗從該次的第一輪重新建立審計，
  但已成功回覆的相同 Prompt 直接讀取鎖定快取，**不再新增模型請求**。
  唯一不可完全消除的情況是 CLI 已成功消耗額度、但作業系統在
  寫入本機 checkpoint 前瞬間當機；此時該次可能需要再呼叫一次，
  所以不能宣稱絕對 exactly-once 計費。
- 若 `run_status.json` 為 `completed`，`--resume` 會被拒絕，
  不允許偷偷增加回合或修改已揭盲研究題目。

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
