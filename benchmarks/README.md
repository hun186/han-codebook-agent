# 中文數字碼本合成破譯測試集 v0.1

此處的 7 組案例和答案皆由 `python benchmarks/build_cases.py` 以固定虛構字典與電文產生；**不是真實破譯成果**。場景採混合單字、詞組和整句命令；詞組長度不等於碼組字數，碼組可有前導零與不同長度（`0007`、`118`），也允許異碼同義（`118`、`123` 同為「兵力」）。這些範例尚未模擬真正的複雜詞段推斷或外層加數密碼。

| 案例 | 可用情報 | 驗測目的 |
|---|---|---|
| `01_known_and_metadata` | 收發單位＋兩封已對齊明文 | 交叉驗證；已知錨點不計入破譯成績 |
| `02_metadata_only` | 僅收發者身分 | 查測後勤與作戰語境是否改善排名 |
| `03_known_only` | 僅兩封對齊明文 | 降低元數據偏誤 |
| `04_cipher_only_with_public_priors` | 沒有收發者及對齊明文，但有候選詞庫 | 有先驗詞庫的近盲解；**不是零資訊** |
| `05_unaligned_crib` | 一封完整但未切段的明文 | 防止未證實切詞被當成確定錨點 |
| `06_misleading_context` | 刻意誤導的收發者資訊＋部分錨點 | 驗證資訊錯誤時不能盲目自信 |
| `07_alias_mixed_length` | 已知部分對齊；多碼同詞／數字長度混合 | 評估異碼同義與詞組切分假設 |

## 使用

執行 `run_benchmark_windows.bat` 或：

```bash
export PYTHONPATH=src
python -m han_codebook.benchmark --config benchmarks/config.yaml
```

`benchmarks/config.yaml` 選擇套件、產出位置與 `both / metadata / no-metadata` 變體。預設離線、LLM 回合數為 0；要測你自己部署的 Ollama，必須**明確選擇** `--enable-llm --llm-config config.yaml --rounds 2`。既有 `config.yaml` 的模型示例為 `192.168.0.134:18080`，尚未實機連線驗收。

- `benchmarks/cases/`：求解器可讀取的密文、領域詞庫、背景情報和確認的對齊片段。
- `benchmarks/gold/`：完整正確碼本和每封原文，**僅在求解完成後評分**。不要把這些資料放入 LLM Prompt 或候選詞庫。
- `benchmarks/suite.json`：七個案例的版本清單及各自答案路徑。
- `artifacts/benchmark_results.json`、`.md`：得分和比較表；是執行後的產物，不是程式碼。

重要指標：未知碼 Top-1／Top-5、整封未提供逐碼答案的電文全部答對率、未知碼組在電文中的正確率、人工待審切詞件數；**已知明文錨點獨立計數，不算破譯成功**。錯誤情報可能使表現下降；若只產生通順中文，仍不能宣稱完成破譯。

本專案的詞庫、候選轉移句皆屬提供給求解器的先驗資訊；這是一組「管線正確性＋可比對演算法成績」的小型合成資料，不可外推成真實歷史密電破譯成功率。LLM 模型並未在用戶實際內網主機執行，單元測試只模擬 API。

## 從已知逐碼明文做留出驗證（純離線研究）

有至少一封已可靠切分的 `known_pairs[].segments`，可在專案根目錄使用：

```bash
python -m han_codebook.holdout_verification --case benchmarks/cases/01_known_and_metadata.json --out artifacts/known_pair_holdout.json --max-folds 10
```

在 Windows 已安裝的環境也可執行 `.venv\\Scripts\\python.exe -m han_codebook.holdout_verification ...`。

**報告檔案採證據保全模式：**每次請指定**新的** `--out` 檔名，例如 `known_pair_holdout_20261102_run02.json`。程式以 exclusive create 寫出，既有報告、符號連結和 `--case` 來源檔皆不可覆寫；在 POSIX 系統上要求 `0600` 權限。預設名稱若已存在也會拒絕執行，請自行另取名稱，而非先刪除既有研究證據。

- 每次拿掉同一封電文的**所有**已知明文紀錄，再以未改動的密文字組重新進行離線統計推理，之後才拿原本可靠的逐碼明文作分數比較。
- 保留的其他電文若已錨定同一數字碼組，該碼組**不得列入獨立驗證成績**，另外列出 overlap 數。只計算真正因扣掉已知對照而失去可靠錨點的碼組。
- 對這些待測碼組，移除原本針對它們的 `candidate_ideas`、`hypothesis_marks`、`bold_hypotheses`；不把 Undo/Redo 歷史交給求解器。完整案例不會被修改。
- 輸出每組 Top-1／Top-5 及原因分類（詞庫不含正解、Top-5 內排序錯誤、排名低於 Top-5），預設**不輸出已知明文內容**。沒有真正獨立可評的碼組時顯示 `null`，不虛構 100%。
- 若已有未切詞的 `plaintext`，它無法充當確定的碼組對應，會標示為未納入這項逐碼評分。這個指令不連模型、不使用任何 `gold` 或 `ground_truth` 檔案。

**正解詞彙先驗覆蓋稽核：** Holdout JSON 的每個 fold 及 summary 新增 `reference_phrase_prior_coverage`，僅在完成離線求解／明確失敗後，統計原始正解詞是否已由 `profile_lexicon`、`profile_sentences`、`other_retained_anchor_terms` 或 `remaining_researcher_hints` 明確提供。`in_any_explicit_prior` 是至少命中一種明確來源的測試碼數；`absent_from_explicit_priors` 是四種來源都沒有該詞的碼數。**各來源會重疊，不能相加作分母**；不輸出正解詞，也不能把這項稽核理解為真的未知詞盲解：自由文字、語意同義與其他模型先驗不在此量測範圍。所有數量都是 fold-code assessments，不代表跨回合唯一碼組數。

**限制非常重要：** 原有的候選詞庫、人工先驗、範例句、密文字組與背景資料仍參與推理。因此這是「已知明文留出一致性測試」，**不是完全陌生詞庫的盲解，也不是歷史破譯成功率**。同一碼組出現在不同留出回合時會重複被計成不同 fold-code assessment，不能把它誤當獨立樣本數。

- **無法求解的留出回合**：即使總詞庫不為空，其他仍未錨定的碼組也可能因先前的研究員 `excluded` 排除全部候選。此時不放寬排除條件、不補回留出的答案；該 fold 註記 `candidate_exclusions_blocked_inference`，並列出阻擋的碼組。保留先前已成功的 fold；此類 fold 不進 Top-1／Top-5 的實際評分分母。`independently_testable_fold_code_assessments` 是潛在可測量數，`scored_fold_code_assessments` 才是比率分母，`not_scored_due_to_candidate_exclusions` 則另行計數。若全部無法評分，比率應為 `null`，不可虛構命中率。

## 情報與觀察資料的配對消融（純離線）

當案例有可靠、已逐碼切分的 `known_pairs[].segments` 時，可以在**相同留出電文／碼組**上比較四種設定：

```bash
python -m han_codebook.context_ablation \
  --case benchmarks/cases/01_known_and_metadata.json \
  --out artifacts/context_ablation.json \
  --max-folds 10 --iterations 3 --restarts 2 --minimum-paired 10
```

- `legacy_context`：沿用傳統觀察資料權重與其他可用元資料。
- `without_observations`：保留收發單位等元資料，但移除所有外部觀察，測試觀察資料有沒有幫忙。
- `time_relevance`：保留外部觀察，改用日期／時間關聯與不相關狀態的折減規則。
- `no_metadata`：移除收發單位、日期和觀察資料，並以 `use_metadata=False` 求解；既有先驗詞庫、已知明文及密文仍適用。

每個變體都執行既有 `holdout_verification`，相同留出錨點的參考詞只在**推論完成後**供計分。報告不包含留出的正解詞、求解詞組、原始觀察文字或公開合成 gold。對照差值只使用兩個變體都**真正完成推論**的相同 `(留出電文, 碼組)`；如果沒有任何共同可比較碼組，差值是 `null`，不應推測優劣。每回合仍可能重複評估同一碼組，不能當成獨立的歷史實驗樣本。

`--minimum-paired` 預設 10，少於該數即標示 `insufficient_paired_evidence`；超過門檻時若同一組碼的 Top-1 命中方向不同，僅標示 `possible_context_harm`／`possible_context_benefit` 的**探索性訊號**，不是顯著性檢定、不是保證正確率會提升。**不會自動選擇模型、不會修改正式推理權重，也不會呼叫 LLM。** 候選詞庫、例句、領域先驗仍然是研究員提供，因此不是零情報盲解或歷史破譯成功率。

## 未逐碼切分的已知明文：候選對齊與研究員覆核（純離線）

針對 `known_pairs` 只有完整 `plaintext`、尚未指定各碼組 `segments` 的案例，新增獨立的**候選對齊診斷**：

```bash
python -m han_codebook.unaligned_review \
  --case benchmarks/cases/05_unaligned_crib.json \
  --out artifacts/unaligned_review.json \
  --top-n 8 --beam-width 96
```

執行後以既有 `profiles[].lexicon/sentences` 與**其他已正式切段的可信 `known_pairs[].segments`** 作候選詞與固定錨點，嘗試把一整句中文切為與該封密電碼組數相同的片段。每種候選強制保留其他可信明文、同一封密電內重複碼組必須指向相同片段，並產生最多 8 個 `candidate_unverified` 結果。包含 500 字以下、字詞長度混合的明文，使用有界 beam search 避免指數路徑爆炸；可藉 `beam_width` 取捨候選涵蓋量與成本。

**重要限制：** 這是排序啟發式，不是機率校準，也不是已證實的破譯；`heuristic_score` 不等於信賴度。搜尋會先以可信錨點及每個碼組至少一字的必要條件，預判剩餘明文是否仍可能被完整消耗，避免長文有效切分在進入 Beam 前被不相關的高分短詞排擠；此預判不會將猜測升為可信錨點。Beam 截斷仍可能漏掉合理候選，甚至出現 `no_feasible_alignment`。它**不修改**原案例、不自動寫回 `known_pairs[].segments`、不新增 `verified_alignment`，必須由研究員另外確認完整碼組—明文分段才可升為可信對照。資料完全離線，不載入合成 `gold`／`ground_truth`、不呼叫任何 LLM。**輸出的 JSON 含研究員輸入的明文，應按敏感研究檔案管理，不宜上傳公開 Repository 或分享。**

目前這是一項獨立 CLI 診斷能力；尚未整合進瀏覽器的覆核／接受按鈕，更沒有自動將候選推進真實密文求解。

## 未切段明文候選的留出驗證（純離線，不洩漏明文）

已有**人工可靠切段**的 `known_pairs[].segments`，可以輪流拿一封當成「僅知道完整明文、不知道各碼組切段」的待審件；在生成候選之前，系統會移除該封的**所有**已知對照紀錄、研究員標註與提示。候選生成後，才用原始切段做完全一致的 Top-1／Top-N 比較：

```bash
python -m han_codebook.unaligned_holdout \
  --case benchmarks/cases/01_known_and_metadata.json \
  --out artifacts/segmentation_holdout.json \
  --max-folds 10 --top-n 8 --beam-width 96
```

- 同碼組仍由**其他**可信電文鎖定的 fold，因答案部分已知，**只作診斷並排除於獨立 Top-N 命中率分母**；無獨立 fold 時回報 `null`，不虛構 100%。
- 完整明文長度超過 500 字的 fold 不推論也不當作錯誤命中；獨立統計只計入實際評分件數。
- 報告不輸出任何已知原文、候選詞組或標準切段，只輸出 fold 代號、排名和分母。原始輸入檔仍可能包含敏感研究明文，不能公開上傳。
- 詞庫、例句與背景先驗仍是研究員預先提供，**此測試不是零資訊盲解、不是歷史密文破譯成功率，也不是對機率的校準**；不改變正式求解器、不呼叫 LLM、不自動接納任何切分為可信錨點。

## 研究員人工確認候選對齊（離線 CLI；絕不自動核准）

先用上述 `unaligned_review` 產生**本地**敏感候選報告，研究員逐一比對密碼組與原始明文；確認分段與原始已知明文完全一致、沒有矛盾的可信錨點後，才可執行以下指令。候選名次從 **1** 開始，而已知明文記錄的索引從 **0** 開始：

```bash
python -m han_codebook.unaligned_accept \
  --case benchmarks/cases/05_unaligned_crib.json \
  --review artifacts/unaligned_review.json \
  --known-pair-index 0 --candidate-rank 1 \
  --confirmed-segments-json '["奉令","補給","車隊","明日凌晨","準時出發"]' \
  --confirm-reviewed \
  --out artifacts/researcher_confirmed_case.json
```

**上例片段只作參考**，必須以實際輸入報告中的碼組數及候選片段為準，不會自動幫研究員選擇或確保候選為正確歷史明文。請勿直接複製範例而不逐碼查核；若所填分段與所選候選不一致，工具會拒絕。

- 需同時提供精確的**完整分段 JSON**、原始候選名次，以及 `--confirm-reviewed`；缺任何一項均不會寫入。
- 報告記載產生時的 `top_n`、`beam_width` 與來源案例 SHA-256；程式會重新生成候選並比對**整份**報告。若案例或候選被改過，需重新產生新報告，禁止套用舊結果。
- 不得與其他已確認碼組矛盾；同一碼組在同封電文中必須完全一致。若研究員標註、試鎖或自行補充候選涉及即將變為可信的碼組，應先單獨核對及清理；工具不會暗中刪除這些標註。
- **絕不覆寫**原案例、原報告或已存在的輸出檔；另存新案例，預設使用私人檔案權限，保留 `alignment_provenance`（記載研究員確認、來源雜湊與原候選名次）。
- 研究員確認只是對切段的**人工決策**，不是 AI 自動確證歷史明文真偽。原始研究明文與輸出檔都應保密，不能放進公開 GitHub。純離線、無模型呼叫、無 `gold`／`ground_truth` 進入推理。

目前是獨立 CLI 安全核准；**瀏覽器的候選預覽與按鈕尚未完成**，不能宣稱 UI 已支援。

## 本機工作台：人工候選預覽與回傳已確認案例（HTTP API）

自 PR #22 的人工確認 CLI 起，新增同源且僅限 loopback 的兩階段路由。這些路由供後續瀏覽器 UI 串接；**這個 PR 仍未加入可操作的瀏覽器候選按鈕**。

- `POST /api/unaligned/preview`，JSON `{"case": <research_case>, "top_n": 8, "beam_width": 96}`：只產生候選報告（含原始明文），絕不改寫磁碟或可信錨點。
- `POST /api/unaligned/accept`：需完整提供 `case`、原 `report`、`known_pair_index`、`candidate_rank`、`confirmed_segments`、`confirmed: true`。伺服器重新核驗**原始案例 SHA-256**、候選、手動輸入、可信錨點及研究員標註。只回傳 `{"case": ..., "saved": false, "status": "researcher_confirmed_not_saved"}`；並不持久化。
- 研究員要把確認的案例寫入磁碟，必須**再額外明確呼叫現有** `POST /api/save`，並指定全新 ASCII 檔名。現有防跨來源、請求上限與建立新檔不覆寫保護維持不變。

此介面不是外網 API、不是對公開 Vercel Mock 開放的功能；沒有呼叫模型，也不承諾切段代表歷史破譯正確。不要用外部資料夾或公開分享方式儲存明文報告。

## 瀏覽器人工切段覆核（本機工作台）

本機 `http://127.0.0.1:8765` 的「已知明密文對」編輯區下方新增「**已知明文候選切段 · 研究員人工覆核**」。先將完整明文對照套用，再按「產生離線候選切段」預覽；每個候選皆顯示數字碼組、分段及「未驗證」標示。

研究員必須自行選擇候選，**完整重新輸入該候選每一個碼組的中文字詞 JSON 陣列**，並在第二次確認視窗中確認逐碼核對，才呼叫原本的受保護 acceptance API。後端重新驗證原案例、候選與明文，不會因網頁選中候選就自動核准。案例若在 API 執行期間被修改，前端會丟棄舊回應；成功也只是更新目前工作台記憶體中的案例，**仍需另外使用「另存案例」建立新檔**。

公開 Vercel Mock 雖由同步工具沿用相同畫面，但**人工切段預覽及確認按鈕在公開 Mock 被停用**，且 Mock API 明確拒絕對應路由；不接受真實明文、不向伺服器送出相關研究資料。同步以 `python scripts/sync_vercel_workbench.py --check` 驗證；本機單人 loopback 工作台不應作公開網站。

## 多封未切段明文的案例總運算預算（離線安全邊界）

`python -m han_codebook.unaligned_review` 及本機瀏覽器 `/api/unaligned/preview` 不只對**單封**明文限制最多 500 個字與 2,000,000 次候選展開，也對**同一案例全部未切段 known_pairs 合計**限制 2,000,000 次展開。每封的用量會從同一個案例預算扣除，且不受使用者修改 `top_n`、`beam_width` 或造假 HTTP 參數影響。

若某封耗盡剩餘預算，整筆預覽會以明確 `case-wide search budget exceeded` 失敗，**不會回傳只覆蓋前幾封的部分候選**，也不會自動接受任何候選或移除可信錨點。使用者可拆成較少電文的研究案例，或先由研究員核對並提供可信逐碼分段。成功的預覽會額外回傳 `expanded_states_total` 與 `expansion_budget_per_case`，方便了解用量；兩者都是搜尋運算量，不代表解密正確率或歷史證明。

上限為運算展開數而**非精確秒數**；較長文本仍可能花費時間。實際工作站的 UI/效能及本機 Ollama 呼叫須在使用者裝置另外驗證，這項修改不會呼叫模型或使用真實密電。

## 一鍵診斷：選擇性長篇明文擴充（全部合成資料）

一般雙擊 `check_alignment_workbench_windows.bat`，或執行 `sh check_alignment_workbench.sh`，**仍只跑原本 17 項**純離線、安全、不含真實研究資料的驗證。要額外檢查長篇已知明文和共用運算預算，請明確選擇：

```bat
check_alignment_workbench_windows.bat --extended
```

```sh
sh check_alignment_workbench.sh --extended
```

或直接執行 `python scripts/check_manual_alignment_workbench.py --extended`。擴充模式在同一個臨時 127.0.0.1 loopback 伺服器上加跑 4 項（總共 21 項）：**剛好 500 字**含末尾可信錨點能產生未驗證候選、**501 字**明確拒絕、**重複數字碼組**維持完全相同的候選詞、**兩封未切段電文**共用預算耗盡時拒絕整份預覽。

輸出仍是專案根目錄 `artifacts/diagnostics/alignment_smoke_latest.json`，只含檢查名稱、PASS/FAIL 與時間，不寫出合成明文、切段、原始資料或模型機密。每次先使上一份 PASS 失效，再產生本次結果。**這些測試不等同真實歷史密電破譯、使用者實機效能或 Ollama 已驗證**，也不會呼叫外部模型。

## 離線候選報告的安全另存（不覆寫）

`python -m han_codebook.unaligned_review --case <input> --out <new-json-file>` 產生的檔案包含使用者輸入的原始明文與候選切段，應視為**敏感研究資料**。新版預設以建立新檔（exclusive create）方式輸出，在支援的 POSIX 系統上採最多擁有者讀寫權限 `0600`；如果指定檔案或符號連結已存在，會明確失敗而不覆寫。

請每次指定新的輸出路徑（例如新的檔案名稱），不要對來源案例、上一輪候選報告或其他研究證據覆寫。若想重新產生候選，先選擇其他名稱；報告中的案例雜湊與原驗證設定仍會供後續明確人工確認步驟核對。這不會將候選自動提升為可信錨點。
## 一鍵匯出完整研究診斷 ZIP（本機 GUI）

在「03 推論與解讀」執行完分析後，含執行失敗的終止工作，會出現「下載分享診斷 ZIP／下載完整私人研究 ZIP」。這不是新的破譯方法，而是把每次執行已存在的 SQLite/Word/Markdown 稽核資料做成可供反覆檢視的有限大小 ZIP。只開放 loopback 同源 POST；**執行中的工作不可匯出成完整成果**。

- **分享診斷版（預設）**：`run_manifest.json`（執行狀態、模型名稱隱去、案例 SHA-256、設定非敏感摘要）、`diagnostics.json`（末次觀察回合、各事件階段數量、失敗時的錯誤類別）、`round_trace.jsonl`（各回合數量、採納／拒絕／變更統計及 token 數字，不含任何明文或模型輸入／輸出）、`evaluation.json`（標示沒有啟用金標計分）。
- **完整私人研究版（再次明確確認）**：除上述摘要外，包含 `input_case.json`（真正執行的案例快照）、`audit_events.jsonl`（逐輪原始事件，包括候選詞與原因）、`audit.sqlite`、成功時的 `result.json`、`report.md` 和 `report.docx`（若當次有成功產出）。若希望追查真正的 LLM Prompt 與回覆，必須在執行前勾選原本「在本機 SQLite 保存完整 LLM Prompt 與回覆」。若沒勾選，之後無法補造沒有記錄的請求。
- **失敗或中斷**：只要工作已進入 `failed` 終止狀態，ZIP 會清楚標示 `complete=false`、`failure_category`，只包含已存在的部分證據；缺失檔案不得用假結果補齊。未完成的人工審核／仍執行中的工作不准匯出成終態證據。
- **安全**：輸出前需要使用者點擊，私人模式須額外確認。模組拒絕錯誤 job ID、路徑符號連結及超大原始檔（48 MB 單檔／128 MB 解包資料）；不會蒐集合成 gold 或研究正解；公開 Vercel Mock 不提供真實診斷 ZIP。**私人版可能包含密電、研究員情報、內網路徑、模型回覆與可能被自行貼入 Prompt 的機密**，務必先自己檢查內容，再決定是否分享給 ChatGPT；不要直接上傳 GitHub。分享版保留的計數和狀態有助於診斷故障，**不包含完整破譯研究內容**。

### 建議第一個落地 LLM 精進案例：08

先用 `07_alias_mixed_length` 跑 1 回合確認你的內網 OpenAI-compatible 模型真正能產生回覆，再對 `08_long_dispatch_with_observations` 做 0 回合離線基線、3 回合動態候選自動模式、3 回合相同設定但停用收發與第三方情報。三次使用完全相同的輸入案例（12 封、212 個碼組位置、2 封已知逐碼對照）。每次都下載**私人診斷 ZIP**，並保存獨立副本；模型、回合、元數據、設定與執行結束情況應在報告中明確記錄。沒有連到使用者真正內網模型就不能宣稱已完成實機 E2E。合成 gold 只可在獨立推理完成後評分，不能包含在 LLM 輸入或診斷包中。

## 無 LLM 也能執行：案例 08 離線情報消融一鍵研究

目前若無法使用內網 LLM，**請不要啟動實機 LLM 對照實驗**；案例 07 的 1 回合模型連線，以及案例 08 的三回合「情報開啟／關閉」實機分析，保留為**待辦，不因離線通過而視為已完成**。先執行確實有輸出、完全不連線的 0 回合對照：

```bat
check_case08_offline_ablation_windows.bat
```

Linux／macOS 使用 `sh check_case08_offline_ablation.sh`，也可以用 `python scripts/check_case08_offline_ablation.py`。可選 `--output-dir <dir>` 決定資料夾父路徑；每次執行都會建立新的 `case08_時間_亂數` 子目錄，不會覆寫先前研究。Windows 的 bat 會自動偵測專案 `.venv` 並設定 `PYTHONPATH`。

執行同一份 `benchmarks/cases/08_long_dispatch_with_observations.json` 共 **兩次 rounds=0、iterations=3、restarts=2**，只有收發者／第三方情報開關不同；不呼叫模型、沒有網路探測，也不更改已確認錨點。等**兩組推理都完成後**才讀取分離的 `benchmarks/gold/08_long_dispatch_with_observations.json` 計算合成正確率。原始 gold 不進入求解器、Prompt 或診斷 ZIP。

成果在 `artifacts/offline_case08_studies/<unique-id>/`：`comparison.json`、`comparison.md` 供比較合成 Top-1、Top-5、非已知明文完全一致率及每碼組位置正確率，也列出被情報影響而換第一順位的碼組 ID；`metadata_on/`、`metadata_off/` 各有 `input_case.json`、`audit.sqlite`、`result.json`、Markdown／可用時的 Word 報告，以及 `diagnostics_safe.zip`、`diagnostics_private.zip`。私人 ZIP 含完整合成明文、候選等內容，分享前請檢查。

合成分數僅在獨立 gold 後處理階段產生；它不等於歷史密電真實破譯能力，也不能據此宣稱使用了 Ollama。此工具與現有 17／21 項明密文切段離線 smoke 分開，互不取代。

## 已知明密文對：研究員逐筆維護 GUI

本機工作台的「01 密電與第三方情報」→「已知明密文對」顯示每筆對應電文、完整明文、逐碼核對狀態及「編輯此筆／刪除此筆」操作；按「＋ 新增明密文對」即可從目前電文選單選擇目標，輸入一整段原始明文。這個表單**不要求研究員直接修改 JSON**；原本的整批 JSON 編輯保留在「進階」展開區。

尚未切段的明文：只填「已知完整明文」，所有逐碼欄位保持空白，即以 `plaintext` 保存為**待人工切段**，不能當作已確認錨點。已獨立核對的明文：依每個數字碼組填寫詞句，完整拼接必須與原文一致，勾選「我已獨立核對」並再次確認，才建立 `segments`。同一數字碼組在各筆已知對照的詞句不得衝突；編輯來源或內容時會移除已不適用的 `alignment_provenance`。**禁止直接把既有可信錨點改成另一個詞句**；若原史料需校訂，必須先明確撤回原對照的逐碼驗證、重新審核後再建立新對照。撤回既有錨點、刪除對照均需明確確認，並防止在編輯期間以舊表單覆蓋較新的研究內容。請先套用進階 JSON 的草稿，才使用逐筆管理。

表單只修改目前瀏覽器的研究案例；若要持久保存，請按工作台「另存案例」建立新的本機檔案，不會默默覆寫原案例。逐碼研究員核對屬可追溯研究資料，**不是 LLM 自動推測，也不等於已證明歷史真偽**。公開 Vercel Mock 只保留同版 GUI 和瀏覽器內的合成示範，不開放真實服務端的研究認證 API。


## 配對式 Metadata ON/OFF 已知明密文 Holdout（完全離線）

既有 `python -m han_codebook.holdout_verification` 可逐封移除逐碼明文並事後評分，但單次執行只測一個 Metadata 設定。若要在相同的 held-out 電文、相同求解預算下，比較 Metadata 是否幫助或誤導解碼，可使用：

```sh
python -m han_codebook.paired_holdout --case benchmarks/cases/07_alias_mixed_length.json --out artifacts/paired_holdout_new.json --max-folds 10 --iterations 3 --restarts 2
```

- 同一案例複製兩份，分別移除同一封電文的**全部**已知明密文對與該封重新失去驗證的碼組研究提示，再以 Metadata ON/OFF 執行完全離線分析；兩者使用相同 folds 與 deterministic solver budget。
- 僅比較**兩邊都產生有效評分**的 `(fold, code)`，計數 Metadata helped／harmed／both correct／both wrong，Top-1 與 Top-5 分開計算。候選詞不足、研究人員排除條件導致無法求解者，另列 `not_comparable_code_assessments`，不得當作猜錯或納入分母。
- 報告只含碼組 ID、每碼相對改善狀態、折數、分母、統計及限制；**不含原始已知明文、候選中文詞、原始電文、LLM 記錄或任何 gold**。報告採新增檔案（exclusive create）並在 POSIX 要求 0600 權限，禁止覆寫舊報告或來源案例。
- **重要限制：**這仍不是詞庫盲測。提供給推論系統的 profile lexicon／sentences 仍可能含有正確詞，且相同 code 可在不同 folds 被評估多次，折－碼計數不能當作全局獨立碼數。配對實驗只能辨識此合成／研究案例對 Metadata 的敏感性，不能推論真實歷史密碼準確度，也沒有呼叫任何模型。

## 真實 Case 08 多回合研究回饋（非金標決策）

根據使用者在本機實際完成的 Case 08（5 回合與三組 0／3／3 回合診斷 ZIP）觀察：模型可以成功回覆，但固定 15 筆碼組容易重複研究少數碼組；當詞庫不再更新時，前後回合請求可能幾乎完全相同；同一候選詞多次回覆不代表更多**獨立證據**。私人 ZIP 與內網端點不得提交至 GitHub。

- `run_agent()` 每回合依**目前已要求研究次數**優先挑選最多 15 個尚未錨定的碼組，再用碼組頻率及 ID 穩定排序；例如 27 個未知碼最晚在第二回合都能得到一次請求機會。請求機會不等於模型已提供有效候選或已解密。
- `round_context` 提供本回合、目標碼組、尚未被要求研究的碼組數，以及同碼組先前模型建議（明確標為未驗證）；提示模型重新檢查，不把前輪的模型輸出升為可信明文。
- 既有提示權重在新增候選詞的預先求解時不再被丟掉。同一 `(code, candidate)` 重複回覆只計入 `repeated_hint_pairs`，不再次提高加權；相同回覆中重複碼組被拒絕。
- 新增 `round_code_selection`、`round_progress_snapshot` 稽核事件，及結果的 `round_progress_summary`（目標碼數、未研究數、首次提示數、重複提示數、第一順位變更數、停滯訊號）。所有映射維持**未驗證假說**，系統不會用合成 gold 或目標函數自動挑選最佳回合。原始稽核事件可能含私密資料，請用私人 ZIP 保存並審閱分享範圍。
- 新功能已有純離線 mock 回歸測試；需在使用者私人工作站重新執行 0／3／5 回合，以及 Metadata ON／OFF、不同隨機種子的重複實驗，才能判斷是否真正提高合成案例或歷史研究表現。
