# Han Codebook Agent — 中文詞組電碼分析原型

> **v0.2 研究用 PoC，不是已驗證的歷史電報自動破譯器。** 本程式不包含真實機密電報、歷史碼本或秘密資料；所有示範案例均為虛構。未知碼組一律標註為假設，不將語句通順當作破譯證明。

此專案針對「一個數字碼組可能代表一個字、一個詞、地名或固定短句」的中文詞組碼本，先解決兩項非常實際的證據整合問題：

1. **收發者／單位／背景情報**：從 `sender`、`recipient`、`domain` 判斷後勤或作戰等領域，使用不同的字詞先驗與片語關係；允許不確定領域。
2. **已知明密文對（known plaintext）**：若提供與每個碼組明確對齊的 `segments`，建立**不可由 LLM 覆寫的確定約束**；若只提供完整明文而未切詞，列出切分候選但**不自動建立確定對照**。

本機統計搜尋不需要 LLM；可選擇呼叫本機或經授權的私有區網 Ollama／OpenAI-compatible `/v1/chat/completions`，進行多輪候選補充、重新排名、留下 SQLite 審計紀錄。自動流程：資料驗證 → 明密文對齊 → 收發單位分析 → 統計／N-gram 候選 →（可選）LLM 建議 → 約束重算 → 證據與歧義報告。


## v0.3：本機瀏覽器研究工作台

已新增可直接使用的 **Web UI**（本機 `127.0.0.1:8765`，不對外開放、不依賴 CDN）：

- Windows 先執行 `setup_windows.bat`，再雙擊 `run_web_windows.bat`；Linux 使用 `python -m han_codebook.web --project-root . --config config.yaml`。
- 在瀏覽器編輯詞彙先驗、範例句、原始密碼組、收發單位、已知明密文對與第三方目擊情報（來源、行為、目的地、狀態、可信度）。
- 支援離線或明確啟用的區網 LLM、多輪進度、Baseline 與後續變化比較、目標分數趨勢、分布統計、逐輪 Prompt／原始回覆（必須逐次勾選記錄）、Markdown 分析報告。
- 增加 12 封、每封 16～21 個碼組（約 42～55 字）的虛構長電文，獨立保存金標，附有離線基準統計圖表及消融測試。
- 所有本機操作與輸出都在 `artifacts/`，預設被 Git 忽略；沒有身分驗證，**請勿將本機 UI 對外網公開或架成多人服務**。

詳細說明：[docs/browser-workbench.md](docs/browser-workbench.md)。目前仍是研究 PoC：語言先驗與目擊情報可能誤導推理，統計目標分數不是正確率，真實歷史密碼／第二層加數法尚未成功破譯。

## 建議使用 YAML 設定檔（v0.2）

`config.yaml` 是主要執行設定。可以集中指定資料來源、發／收報單位元數據、LLM 模型、遠端端點、Agent 回合數及分析紀錄位置，不必每次手動輸入一長串 CLI 參數。示範設定使用**使用者提供的私有網路位址** `http://192.168.0.134:18080`，但未連線測試；請確認伺服器會提供 **OpenAI-compatible `/v1/chat/completions`**，而非只有一般網頁。

```yaml
project:
  case: examples/demo_case.json
  output: artifacts/with_agent.json
  audit_db: artifacts/audit.sqlite

analysis:
  use_metadata: true
  rounds: 2
  evaluate_demo: false

llm:
  base_url: "http://192.168.0.134:18080"
  model: "qwen3.6:latest-128k"
  timeout_seconds: 90
  allow_private_network: true
  allowed_hosts:
    - "192.168.0.134"
```

一般執行只需：

```bash
python -m han_codebook --config config.yaml
```

為保留之前習慣，原始命令列參數仍可用，並**覆寫**設定檔對應欄位，例如 `--rounds 0`（無 LLM）、`--no-metadata`（不使用收發方資訊）、`--model ...`、`--ollama-url ...`、`--out ...`、`--db ...`。未指定 `--config` 時，舊式 `python -m han_codebook examples/demo_case.json` 仍有效。設定檔內的相對路徑一律相對 `config.yaml` 所在目錄計算。

### Linux / macOS 安裝

Python 3.10 以上。Web Word 報告需要 `python-docx`，YAML 使用經驗證的 `yaml.safe_load`；請從本 repo 一次安裝完整套件依賴：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
export PYTHONPATH=src
python -m han_codebook --config config.offline.yaml  # 離線演算，無模型呼叫
python -m han_codebook --config config.yaml          # 呼叫區網 LLM
```

不能從外網下載套件的環境，請預先在可連網的電腦取得目標作業系統／Python 版本適用的 **PyYAML、python-docx、lxml 及所需相依 wheel**，再使用 `python -m pip install --no-index --find-links wheels -e .`；不能只準備 PyYAML。舊式不用 YAML 的位置參數模式仍不需 PyYAML；但完整 GUI 的 Word 功能需要額外依賴。

### Windows 安裝

1. 執行 `setup_windows.bat`：建立虛擬環境、執行 `pip install -e .` 安裝 PyYAML／python-docx 等依賴並執行測試。需事先安裝 Python 3.10+；首次安裝通常需要網路或離線 wheel。
2. `run_demo_windows.bat`：只進行本機數字碼本求解，不會呼叫 LLM。
3. `run_agent_windows.bat`：讀取 `config.yaml` 並向指定的區網模型服務發送研究案例。 啟動時先做 TCP 與 `/v1/models` 輕量檢查，之後每輪呼叫 LLM 會即時顯示等待與執行進度。

也可以從 PowerShell 執行：

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe -m han_codebook --config config.yaml
```

### LLM API 路由、連線與安全

- 使用 `base_url: http://192.168.0.134:18080` 時，程式實際呼叫 `http://192.168.0.134:18080/v1/chat/completions`。若 18080 是 Open WebUI/nginx 網頁入口，**不代表**它必然支援這個 API：需要確認反向代理路由，可能必須改成真正供應 API 的 port。
- 建議先從執行程式的電腦確認 `curl http://192.168.0.134:18080/v1/models`（有些伺服器不支援列表、或需授權；失敗不能單獨證明 Chat API 不可用）。本專案尚未在該真實端點完成端到端驗證。
- 程式預設**只允許 localhost**。使用其他區網 IPv4 必須明確設定 `allow_private_network: true`，並把確切 IP 放入 `allowed_hosts`；公開 IP、任意 DNS 主機、URL 帳密／參數都被拒絕。避免誤把密電送往外部 LLM。這不代表 LAN HTTP 已加密；有真正敏感資料請部署 HTTPS、驗證憑證與妥善隔離網路。
- 模型與端點須自行部署，此專案不會自動下載模型；只要求 OpenAI-compatible 的文字對話回覆，並以 JSON 解析候選詞。
- 如反向代理需要 Bearer token，在 YAML 設 `api_key_env: HAN_CODEBOOK_LLM_API_KEY`，並在作業系統環境變數設定 token，**不要把 token 寫進設定檔或提交 Git**。
- `--rounds 0` 完全跳過 LLM；`config.offline.yaml` 提供確定的離線測試模式。

### Docker

```bash
docker build -t han-codebook-agent .
docker run --rm -v "$(pwd)/artifacts:/app/artifacts" han-codebook-agent --config config.offline.yaml
# 先確認容器內可連上 192.168.0.134:18080，再改為 --config config.yaml
```

Docker image 包含研究程式、YAML 解析器和 Word 匯出依賴，不包含 LLM；建置時預設從套件來源取得 Python 相依套件。若完全隔網，請預先準備依賴套件及基礎 image。

## 資料格式

請參考 [examples/demo_case.json](examples/demo_case.json)。簡化範例：

```json
{
  "case_id": "sample",
  "codebook_assumptions": {"distinct_phrases": true},
  "messages": [
    {"id": "A", "sender": "軍需處", "recipient": "糧食補給倉庫", "codes": ["123", "456"]},
    {"id": "B", "sender": "軍需處", "recipient": "糧食補給倉庫", "codes": ["123", "789"]}
  ],
  "known_pairs": [
    {"message_id": "A", "plaintext": "兵力集結", "segments": ["兵力", "集結"]}
  ],
  "profiles": {
    "logistics": {
      "keywords": ["補給", "糧食", "軍需"],
      "lexicon": {"兵力": 2, "集結": 2, "補給": 8, "車隊": 8, "糧秣": 7},
      "sentences": [["補給", "車隊"], ["補給", "糧秣"]]
    }
  }
}
```

- 所有 `codes` 都是**字串**，保留前導零，例如 `"0042"`。
- `sender`、`recipient` 是可選文字；若不知可略過。`domain` 可明確指定已有的 profile 名稱。
- `lexicon` 的權重代表**人工提供的先驗偏好**，不是模型自動學到的客觀頻率。
- `sentences` 是由既有公開資料／人工提供的**獨立參考語料**，以詞組切分成 list；不應把待測電文的真實答案偷偷塞入訓練語料。
- `known_pairs[].segments` 的順序及數量必須和原碼組完全對應；若沒有可靠對齊，僅放 `plaintext` 讓系統提供待審切詞候選。
- `codebook_assumptions.distinct_phrases=true` 會對不同碼組對應同一詞組施加**軟懲罰**，不是數學硬限制，不能適用於所有同音／異碼密碼系統。資料沒有指定時預設 `false`。
- `ground_truth` **僅供虛構示範的 benchmark 評估**。正式研究資料請勿放答案，解碼程序不會讀它，只有 `--evaluate-demo` 才會計算。

## 目前功能與未完成功能

| 項目 | v0.1 | 備註 |
|---|---|---|
| 中文數字碼組、詞組假設 | 已實作 | 每個碼組可對應不同長度詞組 |
| 發送者／接收者先驗 | 已實作 | 簡單關鍵字領域推測，非完整知識圖譜 |
| 明密文對明確對齊 | 已實作 | 確定錨點不可覆寫，矛盾會拒絕輸入 |
| 未對齊明文 | 已實作候選切詞 | 必須人工確認後才能成為確定錨點 |
| 統計搜尋 | 已實作基本版 | 詞頻、相鄰詞、詞組唯一性假設、隨機重啟座標搜尋 |
| 多輪 LLM 代理人 | 已實作 PoC | 產生 JSON 候選 → 有界加權重算 → SQLite 留痕；**不具自主新工具生成或持續長任務排程** |
| 可接 Ollama | 已實作 API 客戶端 | localhost 或明確許可的區網 IP；尚未在你的 Ollama 實例做現場端到端驗收 |
| 獨立解碼驗證 | 部分 | 只能保證已對齊錨點與約束一致，無密鑰解密驗證器 |
| 碼本外再加密（亂數加數、OTP） | 不支援 | 必須先分析外層密碼，不能直接做詞組推理 |
| 更多樣的同義詞、多碼同詞及多字詞邊界 | 研究中 | `distinct_phrases` 可關閉，尚無專用同音求解器 |
| GUI、分散式 Worker、進階 Corpus 訓練 | 尚未實作 | 後續里程碑 |

## 初步實驗結果

請看 [examples/EXPERIMENT.md](examples/EXPERIMENT.md)，內含四組開關對照和詳細評估限制。值得注意的是：即使元數據提供合理領域線索，小樣本中也**可能使錯誤偏好變得更強**，不可宣稱凡有背景資料就必然更準確。

## 實驗倫理、限制與判讀

研究人員不能把生成的通順中文當作破解成功。`proposals.*.status` 僅有 `verified_alignment` 與 `hypothesis_unverified`；`score_gap_to_second` 是**相對排序差**，不是已校準的機率。正式解讀應用未參與求解的獨立已知電文檢查，且核對時間、地名及編碼一致性。若使用正確的一次性密碼本或經充分保護的現代加密，本系統無法從純密文中可靠恢復原文。

## 測試

```bash
python -m unittest discover -s tests -v
```

CI 位於 `.github/workflows/test.yml`，部署至 GitHub 後才會啟動 Hosted CI；這份 ZIP 本身不是 GitHub 上的 Repository，也不代表已通過 Hosted CI。

## 上傳 GitHub

使用者先在 GitHub 建立空白 public repo（例如 `han-codebook-agent`），**不要額外勾選建立 README**，然後在解壓後專案根目錄：

```bash
git init
git add .
git commit -m "feat: initial Chinese codebook research prototype"
git branch -M main
git remote add origin https://github.com/YOUR_ACCOUNT/han-codebook-agent.git
git push -u origin main
```

未來可在既有 Repository 擴充 MCP 工具服務、長時任務 Worker、真正的異碼同義模型、審查 UI、民國時期獨立語料與大型盲測。

### LLM 在 Windows 看起來卡住怎麼辦？

新版 `run_agent_windows.bat` 會先執行 `--check-llm`：只確認 TCP 可連與 `/v1/models` 路由（不送密文、不進行推理）。若路由不支援則提示警告，不能據此斷言聊天 API 正常；若回傳 HTML 則可能誤指向網頁入口。

直接診斷：

```cmd
set PYTHONPATH=src
.venv\Scripts\python.exe -u -m han_codebook --config config.yaml --check-llm
curl.exe --max-time 10 -i http://192.168.0.134:18080/v1/models
```

開始真正執行時，程式會顯示目前輪次、呼叫的 API URL、模型名稱，每 10 秒提示仍在等待，並在返回後顯示成功接受幾個未驗證候選。`llm.timeout_seconds` 是底層 socket I/O 逾時而不是整輪 LLM 生成的硬性總時間上限；慢速模型生成仍可能超過此時間。可以用 Ctrl+C 中止。若端點是 nginx/Open WebUI 的一般網頁，而非 OpenAI-compatible API，請調整反向代理或改成實際提供 `/v1/chat/completions` 的端點。若 HTTP 401/403，檢查 Bearer token；404，檢查路由或模型；502/504，檢查代理與上游服務。

不要把 API token、真實密文或敏感情報貼到公共 GitHub Issue。尚未在使用者的區網端點實測。

### v0.3 Review hardening: failure diagnostics and editing consistency

- **An unsuccessful analysis is not a verified decoding.** Its trace tab can still show available baseline and round events, including a previously captured LLM request/error response, without enabling result-only decoding and report download.
- The browser applies cipher/metadata/observation changes as one validated unit. Invalid code groups or observation metadata do not partially save sender or receiver edits.
- If the analysis output folder cannot be created, the job becomes `failed` instead of indefinitely occupying the single-job slot; fix filesystem permissions and retry.
- With the **explicit** `capture_llm_io` checkbox enabled, responses from HTTP errors such as `400` and `422` are saved in the local SQLite audit with status and at most 64 KB of response body. Error bodies may themselves include sensitive data; do not enable this setting on sensitive research without reviewing local storage protections. Nothing is captured by default.
- Additional regression coverage: `python -m unittest discover -s tests -p 'test_review_p2.py' -v` (browser JavaScript check uses Node.js if available).

## 單一碼本下的 10／25／50／100 封密電比較

使用者提出更貼近真實研究的固定碼本情境：**一個案件內所有密電使用同一份碼本**，先從大量未知電文累積模式，觀察更多密文能否改善推測。已加入三組合成案例，分別對同一批 100 封密電逐步取前 10、25、50、100 封；另外保留每組獨立 20 封探針。全部採零初始明文對照；**但已提供包含真正詞彙與干擾詞的固定候選詞池**。此實驗是離線統計求解對照，不包含 LLM。

在 Windows 執行 `run_volume_study_windows.bat`，結束後開啟 `artifacts/volume_study.html`，即可比較收發元數據開／關下的三組實測曲線，或讀取 `artifacts/volume_study.json` 做更詳細分析。重建固定題庫使用 `python benchmarks/build_volume.py`。設計、限制與實測基線見 [`benchmarks/volume/README.md`](benchmarks/volume/README.md)。**更多資料不等於每次都會更準確；不能用目標函數上升冒充解密正確率。**

### 同碼本 10／25／50／100 封：增加內網 LLM 對照

`run_volume_study_windows.bat` 僅跑純統計（不呼叫 LLM）。若要評估內網 Ollama 模型，請在 `main` 更新相應版本後使用新增的 `run_volume_llm_windows.bat`，它會明確以 `--enable-llm` 啟用私有網路模型，預設 seed 101、1 輪、每批 25 封，對 10、25、50、100 封合計 8 次聊天 API 請求。**100 封會全部分批提供，並非只送前 50 封。**

輸出 `artifacts/volume_llm_study.html`、`.md`、`.json` 比較相同密文下純統計與 LLM 重排後的 Top-1、獨立探針正確率及 AI 造成的修正／錯誤。完整 Prompt／回覆預設不記錄，需用 `--capture-llm-io` 明確啟用。本測試仍是固定候選詞庫中的假設排名，不是無限制詞庫的完全自主破譯。Hosted CI 以模擬 API 確認流程，不代表用戶私有 Qwen 已完成真實推論驗證。詳見 `benchmarks/volume/README.md`。

### 100 封實驗：檢視每一封密電的目前候選明文

最新的內網 LLM 實驗 HTML 報表含「**密電候選解讀探索器**」，提供 10／25／50／100 封資料量切換、密電選取、數字碼組→候選中文對照，以及統計與 AI 候選之間的差異、理由及可追溯碼組。**中文皆屬未經確認的推測，不是已成功破解。**

如果已用舊版 `run_volume_llm_windows.bat` 跑過 8 次模型呼叫，更新程式後可以改跑 `run_volume_view_windows.bat`：**純本機重算，不用再呼叫 Qwen**，產出 `artifacts/volume_llm_study_decipher.html`。它會核對新重算與原報告 Top-1 指標是否吻合；若不吻合，介面會註記這是重算而非原始碼本快照。詳見 [benchmarks/volume/README.md](benchmarks/volume/README.md)。

### 可逆的研究員假說標註（實驗功能）

本機 `run_web_windows.bat` 的「假說標註／復原」頁面支援對碼組設定「★偏好」、「×排除」、「📌試鎖」與來源備註；每個動作可按「復原」「重做」「全部重設」。在研究總覽中點候選解讀的數字碼組，也能直接跳至該碼組標註。研究員必須按「重新求解」才會把當前標註帶入統計／LLM 推理；先前猜測可在介面與新結果比較。

**標註是工作假說，不是已驗證明密文**。即使使用「試鎖」，也只是暫時的候選搜尋約束，`verified_anchors` 不增加。所有編輯先留在瀏覽器記憶體；「另存案例」會保存目前標註，undo/redo 歷史只維持當次網頁使用階段。可開啟 `benchmarks/volume/seed_101_case.json` 進行 100 封實驗，但不會將金標答案交給模型。

人工標註歷史依**序列化後位元組大小**自動裁剪最舊版本，讓案例另存保持在 1 MB 預算內；重跑分析只送目前標註、**不會把 Undo/Redo 的舊版本傳給求解器或 LLM**。若剛加入的已知明密文對涵蓋已標註碼組，會整筆拒絕這次修改；先在標註頁取消該碼組的人工假說，再套用已知對照。可點選每個「排除候選」標籤單獨恢復。

新增已確認的逐碼明文後，系統會同步清理舊假說版本中涉及該已確認碼組的人工試鎖／偏好／排除，避免按「復原」重新帶回與真實已知明文衝突的標註；不受影響的其他碼組歷史仍可繼續使用。


## Vercel 靜態 Mock 展示站（本機 GUI 同介面）

- `vercel-demo/index.html` 與 `vercel-demo/workbench.js` 由**本機 GUI 唯一來源** `src/han_codebook/static/index.html` 同步產生，沿用同一套深色介面、工作流程導航、密電編輯、候選詞庫、可逆研究假說、逐輪模擬、基準評測及 Word／Markdown 下載入口。
- Vercel 只載入 `mock_api.js` 的瀏覽器內純合成回應，絕不連線到內網 Qwen／Ollama，模型設定頁僅供展示且不允許設定真實端點。編輯案例僅存在本次瀏覽器頁面，重載即消失。**Mock 輸出不是可靠的歷史解密或實際 LLM 測試**。
- GUI 同步指令：`python scripts/sync_vercel_workbench.py --write`；CI 以 `--check` 防止本機／Vercel 版本不一致。
- Vercel Root Directory 保持 `vercel-demo`，Framework 選 Other，僅使用公開合成資料，沒有私有網路設定、API Key 或 SQLite 審計庫。完整限制與驗證見 [vercel-demo/README.md](vercel-demo/README.md)。


## LLM 提示敏感度與動態目擊可靠性（研究實驗）

破譯研究有兩個不同的 LLM 工作：**(A) 根據可觀察情報產生候選詞庫**（`volume_llm --auto-vocabulary`，非預設），以及 **(B) 在既有詞庫內為各碼組提議候選**（一般 `run_agent` / `volume_llm` 的工作）。目前不會自動把 A 與 B 當成已驗證破譯；無已知明文時仍需可靠的外部約束。

本輪加入 **離線提示權重診斷**：核心 `analyze(..., hint_scale=0..4)`，預設 1.0 維持正常推理，0 表示忽略模型提示；建議只把 2.4 當作實驗比較，**不要因為它採納較多 LLM 詞組就宣稱準確率提高**。診斷器比較 0／1／2.4，報出候選採納數、碼組變動、不同目擊處理方式，並可在全數推論完成後才讀合成標準答案。

```powershell
.venv\Scripts\python.exe -m han_codebook.hint_diagnostics --case benchmarks/volume/seed_202_case.json --reply YOUR_SAVED_HYPOTHESES.json --messages 10 --gold benchmarks/volume/seed_202_gold.json --out artifacts/hint_diagnostics.json
```

`YOUR_SAVED_HYPOTHESES.json` 格式為 `{"hypotheses":[{"code":"123","candidates":["車隊"],"reason":"..."}]}`；必須是**已保存的模型實際候選**。這個診斷指令**不呼叫 LLM、不重複產生新建議，也不把合成答案送回求解器**。真實調查時省略 `--gold`；不要用合成真值挑選正式部署權重。

另加入可選的 `case.observation_policy: "time_relevance"`（預設 `legacy` 不改變既有計算）：第三方目擊狀態若明確標示無關／已排除，則不作為領域推斷證據；未確認相關性會降低權重；遙遠或無法解析的觀察時間會減權。日期只有日精度時不虛構精確時刻。這些權重是**待校準的研究假設**，並不代表已實現特定事件對密電的完整配對、時序因果判讀或真假識別。

診斷對照會比較「保留目擊／移除目擊／時間相關性減權／關閉全部元資料」，以區分究竟是收發者先驗還是動態觀察促成排名差異。即使有更多密電，若缺少獨立可驗證線索，正確率也未必增加。


## 本機研究員從零建立案例（PR #5）

`run_web_windows.bat` 的本機研究 GUI 不再只用於檢視既有案例的破譯 Log：

1. 按「＋ 建立空白案例」，設定案例 ID；在「電文與第三方觀察」修改第一封數字碼組和時間，按「套用此封情報」，再用「＋ 新增電文」逐封建檔。
2. 可新增語境領域、人工輸入候選詞及範例句；按「＋ 新增觀察」附上第三方目擊、時間、可能目的地、可信度及「未確認」狀態。
3. 「分析目擊與密電時序」會列出每則觀察與多封通信的**日期鄰近候選**及重複碼組，且一定保留「可能完全無關」；並非事件語意推理器或已驗證的連結。事件連結候選也會以明確標示的未驗證情報送入後續本機 LLM。
4. 「請內網 LLM 產生候選詞」必須人工確認才會連到 `config.yaml` 的**私有網路 allowlist 模型**，結果逐項供研究員採納，**不會自動寫入詞庫或鎖碼**。此流程使用原本的 `auto_vocabulary`；如果案例已有確定已知明文對照，冷啟動程序會拒絕呼叫。
5. 在「假說標註／復原」，同一數字碼組現在可有**多個**研究員、LLM 或目擊來源候選，每項可設待審／優先考慮／否定與文字證據；優先考慮只施加微弱可逆先驗（0.12），可透過本次會話的「復原／重做想法庫」撤銷。傳統「偏好／排除／試鎖」仍是另一組可逆標註，只有明密文逐碼對齊資料才算真正 verified anchor。
6. 完成一輪內網 LLM 後，可選擇把該輪被接受的**碼組對應候選**匯入多想法庫供人工覆核。候選想法與電文可透過「另存案例」保存到本機 `artifacts/ui_cases/`；想法庫的 Undo／Redo 快照僅限當次網頁工作階段，重新載入保存案例則從已保存想法開始。

> **研究限制**：本輪只提供保守的時間距離／可信度候選及給 LLM 跨電文整合的初步結構，不是會自動把真實目擊和密文事件做聯合因果配對的成熟模型。沒有可靠外部約束時，100 封電文仍可能有很低正確率。LLM 未經證實的提議不會變成解密答案。本機 GUI 的新功能不會自動出現在 Vercel 純靜態 Mock PoC；Vercel 並不會呼叫私有模型。

### 研究流程導覽（GUI 內建說明）

本機瀏覽器的左側「**研究導航**」現在有獨立「**研究流程／架構說明**」頁。桌面提供固定側邊欄，行動裝置為可水平捲動導航。說明頁用七階段連結展示：**從零建案 → 密電與目擊輸入 → 詞庫與 LLM 候選 → 統計與 LLM 推論 → 多候選人工覆核 → 逐輪比較 → 撤銷／再求解**，同時交代四層資訊的驗證界線和保存限制。每個階段都能點擊前往對應功能。

Codex Review 防止跨案例污染的兩項 P2 已實作：
- 非同步分析與詞庫生成、目擊關聯結果，均以**原案例物件、頁面版本及案例內容指紋**比對；切換或改動案例時，舊回覆與舊按鈕不能寫到目前案例，並清除前一案例的解讀及觀察畫面。若在同案編輯期間修改研究資料，操作按鈕會重新開放並提示重算。另一案例運行中的背景工作仍可由原工作系統自行完成，但不會在新案例介面套用。
- 批次匯入 LLM 建議時，若該碼組詞組已存在，**完整保留既有的人工 `rejected`／`shortlisted` 狀態、來源與文字註記**，只新增原本不存在的候選；試鎖和已知明文也不因此提升或被覆寫。

由 `tests/js/test_case_provenance.js` 搭配 `tests/test_case_provenance_ui.py` 透過 Node VM 執行延遲回覆、舊按鈕、同案修改、跨案例目擊、人工否定與 Undo/Redo 回歸。Hosted GitHub CI 與 Codex review 狀態須依目前 PR HEAD 再確認。Vercel 純靜態 Mock PoC 不包含此本機 GUI 的新功能。

### 2026-10-28：同案不同 Job 與密碼組編輯一致性

- 詞庫生成除了「同一個研究案例」外，現在另核對**每一次模型請求序號**及**目前 Job ID**。即使同一個 Job 因間隔輪詢產生多個尚未回覆的 HTTP GET，完成或失敗時也會退休該 Job 的所有舊回覆；下一個 Job 的候選與按鈕不能被上一個 Job 的延遲結果改動。分析工作也採取相同的回覆失效處理。候選採納按鈕綁定生成它的展示工作序號。
- 研究員在「密電與第三方情報」修改碼組時，系統先驗證完整輸入並檢查是否存在逐碼或非逐碼已知明文對照：**有已知明文對照時不得直接更改對應密碼組**，需先獨立覆核。若某個舊碼組在所有電文中都不再出現，系統會要求確認移除它的候選想法及標註；確認後同步清理 Undo/Redo 快照、儲存歷史並刷新碼組選單。取消不會部分寫入。仍在其他電文出現的碼組不會被清除。
- 新增 `tests/js/test_cipher_edit_integrity.js` 與 `tests/js/test_case_provenance.js` 相關情境；由 `tests/test_case_provenance_ui.py` 在 Hosted CI 執行 Node VM 的實際輸入／輪詢／撤銷測試。


## 本機研究工作台：模型設定、長回合與 Word 匯出（PR #6）

- 「**LLM 端點設定**」頁參考 `AI-Simulated-Patient` 的 Provider/Model 人機介面，但**本研究系統只開放 OpenAI-compatible 本機／明確允許的 RFC1918 私人網路端點**，拒絕公網、DNS 與 URL 內嵌帳密。設定只存到本機 `config.yaml`；API Key 只能填**伺服器已有的環境變數名稱**，不得貼入金鑰本體。可測試 TCP 與 `/v1/models`，不包含任何研究電文，且此測試**不等於驗證 chat completion**。正在執行分析／產生詞庫時禁止改連線設定。
- 原 GUI 只有 0～3 輪，下拉式選單只是當時的 UI 限制；現在使用**整數數字輸入**，前後端均驗證 0～20；0 輪完全離線，1～20 輪會連模型，較多回合並不等於更準確或更多有效證據。建議先 1～3 輪檢查逐輪改變與是否陷入重複，再自行比較其他輪數。
- 執行完成後同時提供**Word（`.docx`）**及 Markdown 研究報告，Word 表格含統計摘要、每輪模型建議／變化、碼組狀態與候選、逐封密電解讀及限制。舊的保存分析若有 `result.json`、`audit.sqlite`，也能以同一 Job ID 的 `/api/jobs/<id>/report.docx` 補產 Word；不能讀取使用者電腦以外的 `127.0.0.1` 結果。
- 「**先驗權重**」是研究員提供給詞彙的初始偏好，不是實測頻率、校準機率或已驗證錨點；GUI 現已內建定義與數值例子。
- 逐碼閱讀畫面標色：**綠色**＝可信逐碼已知明文、**藍色**＝未驗證候選、**紫紅色**＝研究員明知與可靠錨點不同、仍經顯式確認提出的**大膽反對假說**。操作錯誤有顯眼固定提示。反對假說存在獨立的 `bold_hypotheses` 資料結構，不能寫入 `known_pairs`／`hypothesis_marks` 的 verified anchors，報告也會雙欄並列「已驗證原詞」與「反對假說」。**大膽指定僅改變研究顯示與報告，不會偷偷將未驗證詞組送入求解器當作真實錨點**；真正的反事實求解模式仍屬後續研究。
- `python-docx>=1.1,<2` 是新的 Word 匯出安裝依賴。部署時更新 Python 套件，請勿只將新的 HTML 複製到舊程式。研究資料與完整模型輸出仍僅在本機；Vercel 靜態 Mock PoC 不具備此後端功能。
