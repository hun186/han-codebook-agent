# Han Codebook Agent — 中文詞組電碼分析原型

> **v0.2 研究用 PoC，不是已驗證的歷史電報自動破譯器。** 本程式不包含真實機密電報、歷史碼本或秘密資料；所有示範案例均為虛構。未知碼組一律標註為假設，不將語句通順當作破譯證明。

此專案針對「一個數字碼組可能代表一個字、一個詞、地名或固定短句」的中文詞組碼本，先解決兩項非常實際的證據整合問題：

1. **收發者／單位／背景情報**：從 `sender`、`recipient`、`domain` 判斷後勤或作戰等領域，使用不同的字詞先驗與片語關係；允許不確定領域。
2. **已知明密文對（known plaintext）**：若提供與每個碼組明確對齊的 `segments`，建立**不可由 LLM 覆寫的確定約束**；若只提供完整明文而未切詞，列出切分候選但**不自動建立確定對照**。

本機統計搜尋不需要 LLM；可選擇呼叫本機或經授權的私有區網 Ollama／OpenAI-compatible `/v1/chat/completions`，進行多輪候選補充、重新排名、留下 SQLite 審計紀錄。自動流程：資料驗證 → 明密文對齊 → 收發單位分析 → 統計／N-gram 候選 →（可選）LLM 建議 → 約束重算 → 證據與歧義報告。

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

Python 3.10 以上。YAML 使用經驗證的安全解析器 `yaml.safe_load`，需要一次性安裝 `PyYAML`：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install 'PyYAML>=6.0,<7'
export PYTHONPATH=src
python -m han_codebook --config config.offline.yaml  # 離線演算，無模型呼叫
python -m han_codebook --config config.yaml          # 呼叫區網 LLM
```

不能從外網下載套件的環境，可預先在可連網的電腦下載**符合目標作業系統與 Python 版本**的 PyYAML wheel，帶入封閉網路後執行 `python -m pip install --no-index --find-links wheels 'PyYAML>=6,<7'`。舊式不用 YAML 的位置參數執行模式仍不依賴 PyYAML。

### Windows 安裝

1. 執行 `setup_windows.bat`：建立虛擬環境、安裝 PyYAML、執行測試。需事先安裝 Python 3.10+；首次安裝通常需要網路或離線 wheel。
2. `run_demo_windows.bat`：只進行本機數字碼本求解，不會呼叫 LLM。
3. `run_agent_windows.bat`：讀取 `config.yaml` 並向指定的區網模型服務發送研究案例。

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

Docker image 只包含研究程式與 YAML 解析器，不包含本機 LLM；建置時預設從套件來源取得 PyYAML。若完全隔網，請預先準備依賴套件及基礎 image。

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
