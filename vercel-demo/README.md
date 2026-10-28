# Han Codebook Agent — Vercel 同介面 Mock Demo

這是 **公開合成資料、純靜態、無外部模型連線的展示版**。本版與本機 Python 研究工作台使用**同一套 GUI HTML、側邊導覽、表單和前端互動程式**；兩者差別在於資料來源與運算後端。

| 項目 | 本機 GUI | Vercel Demo |
|---|---|---|
| 視覺與操作 | `src/han_codebook/static/index.html` | 同份頁面產生的 `index.html` + `workbench.js` |
| 案例和編輯 | 研究員檔案／本機資料夾 | 10、25、50、100 封公開合成範例；使用者新增/修改只存在目前瀏覽器記憶體 |
| LLM 設定 | 允許明確核准的 localhost／LAN 模型 | **僅顯示 Mock；不允許輸入端點後呼叫網路** |
| 回合／分析 | 真實 Python 統計和可選 LLM | `mock_api.js` 依公開候選快照、人工標註產生可重現的 Mock 結果 |
| 詞庫／目擊時序 | 本機推理流程與審計 | 無外部連線、僅用公開合成資料的假說模擬 |
| 人工標註 | 可逆標註、另存檔 | 同一 UI；可逆標註及再求解，頁面重載即清空未保存變更 |
| 研究報告 | Python Word/Markdown | 瀏覽器產生有效 OOXML DOCX／Markdown，內容明確標示 PUBLIC MOCK |
| 評測 | 由後端使用獨立合成答案計分 | 使用事先公佈的合成基準快照，不是即時模型準確率 |

重要：即使畫面與操作一致，Vercel 網頁的「分析完成」、「LLM 回合」均是**模擬流程**，不是實際 Ollama、Qwen、OpenAI、歷史密文解碼、資料庫儲存或雲端任務執行。不要在公開網站輸入敏感密文；本版雖不把輸入傳給模型，仍應只作虛構展示。

## 維護與同步

**本機 GUI 是單一介面來源。** 不能再手動重做一套 Vercel UI。當 `src/han_codebook/static/index.html` 有變動，從 repo 根目錄執行：

```bash
python scripts/sync_vercel_workbench.py --write
python scripts/sync_vercel_workbench.py --check
python -m unittest discover -s tests -v
```

此工具將本機 HTML 與內嵌程式碼同步成 `vercel-demo/index.html`、`vercel-demo/workbench.js`，在標頭注入公開 Mock 警示並先載入 `mock_api.js`；未觸碰本機原始頁面。Hosted CI 裡 `test_vercel_demo.py` 會執行同步一致性檢查，若有人只更新本機 GUI 而沒有更新 Vercel 副本，CI 應失敗。

為了維持既有合成快照的可重現性，`data/demo.json` 和 `data/gold.json` 繼續分開。新的 `mock_api.js` 只讀 `data/demo.json` 的公開候選，**不讀 gold.json、不接觸任何真實 LLM**。既有 `app.js` 和 `mock_solver.js` 是前一版獨立 UI 的保留測試資產，不再由首頁載入；不要把前一版 Mock 的正確率視為新版即時求解的績效。

## Vercel 部署

保留 Vercel Project Root Directory 為 **`vercel-demo`**，Framework 使用 Other；這是一個靜態網站，不可直接將 Root Directory 改為 `src/han_codebook/static`，否則缺少 Mock API。HTTP CSP 僅允許本來源腳本與本來源資料讀取，且攔截所有本機 GUI 的 `/api/*` 呼叫。

預覽時可從 repo 根目錄執行：

```bash
python -m http.server 8767 -d vercel-demo
```

瀏覽 `http://127.0.0.1:8767`。本機測試需安裝 Node.js 才會執行額外的 Browser Mock API 回歸；GitHub Hosted CI 另外執行完整 Python unittest。部署到正式網址前須檢查 PR、CI、Codex Review，並獲得明確合併／上線同意。請勿把 `config.yaml`、內網 IP、憑證、資料庫或私有研究案件放進展示資料。
