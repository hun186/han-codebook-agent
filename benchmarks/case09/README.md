# Case 09｜雲谷救援網（統一三位數碼組）
  
**虛構合成基準資料，並非真實截獲密文或破譯成果。**

- 同一固定碼本，25／100／400／1,000 封巢狀累積，主電文每封 24 個三位數碼組（100–999）。
- `cold`：0 個驗證對照；`sparse`：3 個可靠單碼錨點，其餘都是未確認假說。
- 研究員猜測保留於 `candidate_ideas`，不會升級成 `verified_alignment`。
- 故事包含降雨、道路中斷、醫療、物資、通訊受損、誤傳與恢復；166～167 筆不確定第三方觀察（以統計檔實際值為準）。
- 模型輸入只有 `benchmarks/cases/09_valley_*.json`；答案在 `benchmarks/gold/`，僅可在推論後讀取。另保留 80 封獨立 probe 於 `benchmarks/case09/gold/oracle_and_probe_eval_only.json`，不可送給模型。
- `REF-01`～`REF-03` 僅是現版 `known_pairs` 限制下的「單碼對照容器」，不是 24 碼截獲電文；評分時已知錨點必須扣除。

## 使用方式

本機研究工作台 `run_web_windows.bat` 啟動後，案例下拉會列出 `benchmarks/cases/09_valley_0025_sparse.json` 等八種選項。先用 25 封作展示，再依序切換 100／400／1,000 封；每批沿用**完全相同的密碼映射與前綴電文**。

### 離線測試

```bash
PYTHONPATH=src python -m han_codebook.benchmark --config benchmarks/config.yaml --suite benchmarks/suite_case09.json --variants metadata
```

上述指令會比較八組案例，1,000 封的統計搜尋耗時可能顯著增加。首次展示建議使用 25 封，`rounds=0`。**不要**直接將所有案例加入原本預設的 `benchmarks/suite.json`，避免常態 CI 重跑大型案例。

### 使用 DeepInfra

請在 UI 選擇上述案例，並確認外部傳輸授權後，再啟用 LLM；不要把 `benchmarks/gold` 或 `benchmarks/case09/gold` 丟進 Prompt。大語料會增加 Token 與費用。現有 `--adaptive-vocabulary` 冷啟動流程在 `sparse` 模式可能因已知對照被拒絕：這是專案功能限制，**不代表資料錯誤**。目前 `known_pairs` 尚未支援同封電文的局部錨點，長期建議補上 `verified_partial_mappings`。

碼本內詞組有部分未在公開候選詞庫中出現；不能假設模型已掌握所有正解。目標函數分數不等於 Gold 正確率。

### 可重現資料集

`benchmarks/case09/generate_case09.mjs` + `spec.json` 保存固定亂數種子及案例生成規則，需 Node.js 18+：

```bash
node benchmarks/case09/generate_case09.mjs benchmarks
```

生成的 8 組 cases、8 組 gold、`suite_case09.json` 可重現。本 PR 另外附單元測試，驗證三位數與 Gold 隔離。
