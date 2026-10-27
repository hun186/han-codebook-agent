# Han Codebook Agent — 本機瀏覽器研究工作台（v0.3）

本版本為離線優先的研究原型，僅可透過 `127.0.0.1` 使用，不能當作多使用者網站直接暴露在區網或網際網路。模型仍由 `config.yaml` 指定，可使用自行部署的 Ollama 或其他 OpenAI-compatible `/v1/chat/completions`。

## 啟動

Windows：先執行 `setup_windows.bat`，再執行 `run_web_windows.bat`。瀏覽器開啟 `http://127.0.0.1:8765`。Python 3.10+，依賴 `PyYAML>=6,<7`。

Linux：

```bash
python -m pip install -e .
python -m han_codebook.web --project-root . --config config.yaml --port 8765
```

沒有使用雲端網頁服務、CDN 或外部 JavaScript。只綁定 loopback，並檢查 Host / 寫入來源；拒絕任意檔案路徑讀取。不要把這個非授權式工具放到 nginx 對外反向代理；若要支援多人，應另外加入身分驗證、TLS、RBAC 與隔離儲存。

## 操作

1. **研究與執行**：選擇案例，切換元數據、LLM 回合（0 代表純離線），按「執行分析」。瀏覽器每約一秒更新背景工作的狀態與進度。LLM 呼叫只有使用者選擇回合大於零並明確確認後才開始。完成後有各電文解讀、分布圖與 Markdown 研究報告。
2. **詞彙先驗**：選擇物流／作戰領域，檢閱每個詞組的權重，編輯關鍵詞及 N-gram 範例句。詞彙與示範句是事先提供的線索，不是破譯結果。
3. **電文／第三方觀察**：編輯數字碼組、收／發報者、額外備註、第三方觀察紀錄（來源、活動、目的地、狀態、可信度 0–1），以及已知的逐碼對齊明密文。含未知切分的完整明文只會列為人工審核項，不會自動變成確定錨點。
4. **逐輪分析／Prompt**：比較離線 Baseline 與各輪候選碼本的變化數、統計目標分數曲線、接受／拒絕的 LLM 建議。執行前勾選「在本機 SQLite 保存完整 Prompt 與回覆」，才能顯示每輪原始請求／回覆、API 耗時和伺服器有提供時的 token 使用量。
5. **基準評測**：執行 8 組虛構測試案例，分別評測使用／不使用收發者元數據的未知碼 Top-1、整封電文完全正確率與候選詞段正確率。正確答案存於獨立 `benchmarks/gold`，求解器只讀 `benchmarks/cases`，金標在推理**完成後**才載入評分。

保存操作會寫到 `artifacts/ui_cases/<name>.json`，不會覆寫內建案例；執行結果存 `artifacts/web_runs/<run_id>/`（`result.json`、`audit.sqlite`、`report.md`）。基準報告寫到 `artifacts/benchmark_results.json`。這些資料夾已被 Git 忽略。

## LLM 監控與資料保護

- `llm.capture_io: false` 是 CLI 的預設；瀏覽器每輪另以核取方塊明確啟用，以免將可能敏感的電文、來源／行為細節及完整模型答案長期明文存入磁碟。
- 稽核紀錄只保存在本機 SQLite，不會提交 GitHub；但同一作業系統帳戶、能存取工作目錄的使用者仍可閱讀，必要時請使用磁碟加密與存取控制。
- 絕不把 `ground_truth`、獨立 benchmark 金標檔案或 API Bearer token 放入 LLM 的 Prompt；金標只在最後評分時載入。
- 將收發者與第三方觀察視為**可錯誤的推測來源**，不是可以覆寫已知明文的真值。`confidence` 權重不代表統計上校準的準確率。
- 介面報表中的 objective score 是內部相對分數，不是「破譯準確率」或機率；真實破譯成功需要獨立明密文對佐證。
- 若使用真實敏感資料，務必保護 HTTP 傳輸並審查下游模型服務的資料保存政策；內網 `http://` 並不加密。

## 長電文測試

`08_long_dispatch_with_observations` 為 12 封人工撰寫、16–21 碼組（約 42–55 字）的虛構多段電文，包含車隊數量、貨物數量、路線狀態、期限、動態及回報要求，並為其中五封提供可靠性未確定的第三方觀察。所有金標存於 `benchmarks/gold/08_long_dispatch_with_observations.json`；案例只含密文、詞彙與可見背景。

```bash
python -m han_codebook.benchmark --config benchmarks/config.yaml --variants both
```

完整基準預設離線運算，為保證實驗可重現，採固定隨機種子和每一情境 3 次迭代／2 次重啟的有限求解預算。此小型合成資料不能用來推論真實歷史密電的預期成功率。使用內網模型要另以 `--enable-llm --llm-config config.yaml` 明確啟用。

## 尚未完成

目前還不是通用密碼破解引擎：未支援未知分隔的詞組碼、加數再加密、外部歷史語料微調、可校準的概率信心、人工確認工作流與多人協作。本地 UI 已可保存案例及展示結果；真正擴充解密能力仍須以跨題庫實驗和更嚴格的金標驗證為先。
