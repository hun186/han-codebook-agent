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

- 每次拿掉同一封電文的**所有**已知明文紀錄，再以未改動的密文字組重新進行離線統計推理，之後才拿原本可靠的逐碼明文作分數比較。
- 保留的其他電文若已錨定同一數字碼組，該碼組**不得列入獨立驗證成績**，另外列出 overlap 數。只計算真正因扣掉已知對照而失去可靠錨點的碼組。
- 對這些待測碼組，移除原本針對它們的 `candidate_ideas`、`hypothesis_marks`、`bold_hypotheses`；不把 Undo/Redo 歷史交給求解器。完整案例不會被修改。
- 輸出每組 Top-1／Top-5 及原因分類（詞庫不含正解、Top-5 內排序錯誤、排名低於 Top-5），預設**不輸出已知明文內容**。沒有真正獨立可評的碼組時顯示 `null`，不虛構 100%。
- 若已有未切詞的 `plaintext`，它無法充當確定的碼組對應，會標示為未納入這項逐碼評分。這個指令不連模型、不使用任何 `gold` 或 `ground_truth` 檔案。

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
