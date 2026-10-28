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
- 輸出每組 Top-1／Top-5 及原因分類（詞庫不含正解、研究員排除、Top-5 內排序錯誤、排名低於 Top-5），預設**不輸出已知明文內容**。沒有真正獨立可評的碼組時顯示 `null`，不虛構 100%。
- 若已有未切詞的 `plaintext`，它無法充當確定的碼組對應，會標示為未納入這項逐碼評分。這個指令不連模型、不使用任何 `gold` 或 `ground_truth` 檔案。

**限制非常重要：** 原有的候選詞庫、人工先驗、範例句、密文字組與背景資料仍參與推理。因此這是「已知明文留出一致性測試」，**不是完全陌生詞庫的盲解，也不是歷史破譯成功率**。同一碼組出現在不同留出回合時會重複被計成不同 fold-code assessment，不能把它誤當獨立樣本數。
