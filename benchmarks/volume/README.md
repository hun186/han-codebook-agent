# 單一碼本：密文數量消融實驗

研究問題：在**相同碼本、相同候選詞庫、相同求解預算、零已知明文對照**的條件下，取得 10／25／50／100 封密電是否能改善碼組推測？

- 三個獨立合成案例 (`seed 101/202/303`)；每個案例的 100 封密電使用 **同一份固定的數字碼組→中文詞組碼本**。不同案例的秘密對應可不同，但**絕不在同一案例內換碼本**。
- 樣本數巢狀：10 封是 25 封的前 10 封；25 封是 50 封的前 25 封；50 封是 100 封的前 50 封。所有資訊使用相同候選詞彙表／同一組數據生成規則。
- 每個案例另有 20 封獨立探針電文，**從未進入推理**；這些探針的數字碼組有些可能根本沒有在先前收到的密電中出現，評分時必須計為未覆蓋、不可當作破解成功。
- 研究起始 **0 個已知明文錨點**，但**有固定候選詞庫**，而且這套候選詞庫含真實合成詞組與干擾詞，因此**不是純密文零資訊破解**。
- 收發單位與不確定的第三方觀察可開或關；觀察內容帶來源及低可信度，不能直接轉換成已確認的明文。
- 只用現有統計／bigram 求解器；**這個實驗沒有 LLM 推理**，不宣稱 100 封已經透過 AI 自主找出第一個突破口。

## 執行方式

Windows GitHub Desktop Pull 後，先執行過 `setup_windows.bat`，再雙擊 `run_volume_study_windows.bat`。正常完成後可開啟：

- `artifacts/volume_study.html`：無網路依賴、四張靜態 SVG 趨勢圖與逐組結果
- `artifacts/volume_study.md`：Markdown 實測表
- `artifacts/volume_study.json`：完整原始指標，可供 Excel 或其他程式處理

Linux／macOS：

```bash
export PYTHONPATH=src
python benchmarks/build_volume.py              # 如需重新產生確定性測試資料
python -m han_codebook.volume --out artifacts/volume_study.json
```

可使用 `--seeds 101` 只跑一組、`--metadata on` 只用收發情報、`--sizes 10,50,100` 或 `--iterations 4 --restarts 4` 控制離線求解預算。正式範例預設 4/4；CLI 也有相同預設。

## 指標閱讀方式

- **未知碼組 Top-1／Top-5**：僅評估已出現在當批密電的碼組，不把已知錨點算為破譯結果。
- **固定前 10 封碼組 Top-1**：固定相同碼組集合，比較新資料增加後對原本問題有沒有幫助，避免被新出現的困難詞組干擾。
- **獨立 20 封探針 Top-1**：未出現過的碼組計錯；這個數字更能檢查整體碼本是否能泛化。
- **碼組覆蓋率／單次出現數**：更多電文可能提高覆蓋率，但不保證語義正確。
- **運算時間**：研究者硬體與 Python 版本會影響時間，不作跨環境絕對比較。

## 局限

這是合成資料、固定明確分段的數字碼組、假設同一碼本、未加第二層密碼；測試題模板與公用詞彙先驗都比現實更受控。這批 100 封最多出現約 60 個不同碼組，不能外推到 300–500 個未知詞組的完整碼本。三個 seed 樣本數仍不足以做可靠統計推論，且每次重新開始搜尋可能落入不同局部最佳值；**更多密文不保證單調提高 Top-1**。

保留 `RESULTS.json`／`RESULTS.md` 作為這次實際離線運行的版本基線；`RESULTS.json` 的秒數屬執行環境觀測，不是效能 SLA。

## 額外內網 LLM 對照組（需明確 opt-in）

純統計測試 `run_volume_study_windows.bat` **故意不呼叫 LLM**，用於維持同一條基準線。
新版 `run_volume_llm_windows.bat` 才是「純統計 vs 內網 LLM」比較：

1. 先確認 `config.yaml` 內的 `llm.base_url`、`llm.model`、`allow_private_network` 和 `allowed_hosts` 正確；模型必須提供 `/v1/chat/completions`。
2. 雙擊 `run_volume_llm_windows.bat`：採 seed 101、10/25/50/100 封、1 輪 LLM，最多 25 封／請求。依各封數所需的批數，總計最多 8 次成功模型請求；若中途失敗則會中止。
3. 查看 `artifacts/volume_llm_study.html`／`.md`／`.json`，比較碼組 Top-1、20 封獨立探針、LLM 修正數與原正確對應被改錯數。

手動命令：

```cmd
set "PYTHONPATH=%CD%\src"
.venv\Scripts\python.exe -u -m han_codebook.volume_llm --enable-llm --llm-config config.yaml --seeds 101 --sizes 10,25,50,100 --rounds 1 --batch-size 25
```

如需三組 seed 與兩輪模型：將 `--seeds` 改為 `101,202,303`、`--rounds` 改為 `2`；請注意這會有約 48 次模型請求，且每次超時單獨計算。若要連 Prompt 與回覆都儲存於本機 JSON，另加 `--capture-llm-io`；**預設不保存完整原文**。

LLM 模式會在每一輪把當前 subset **全部電文**分成不重複的 25 封批次送出，並把合法候選彙整後，以相同的統計求解預算重新計算全批。已明確禁止只將前 50 封交給模型卻宣稱測過 100 封。關閉元數據時，LLM 不會看到發／收單位及第三方觀察。**LLM 必須真的回覆合法 JSON；失敗不會假裝成功，也不會退回統計結果冒充模型結果。**

本功能尚未直接連到使用者內網服務完成真正 Qwen/Ollama 實測，CI 的模型呼叫只用模擬 API；模擬回覆不計入實際正確率。演算法仍採詞庫約束候選排名，並非完整從零恢復未知詞彙的自主破譯 Agent。

## 瀏覽器查看每封密電的「目前候選解讀」

從這個版本開始，`volume_llm_study.html` 新增**密電候選解讀探索器**：
- 選擇 Seed、10／25／50／100 封與其中一封密電；同時檢視原始數字碼組、純統計猜測及內網 LLM 候選重新求解後的猜測。
- 每個中文詞組都是未驗證的 Top-1 假說；按詞組可查看數字碼、其他候選、模型實際輸出的 `reason`（若有）、所屬批次。被 LLM 加權後改變的詞組以不同底色提示，但改變不等於正確。
- 10／25／50／100 仍是**四次獨立求解**，不可誤稱為同一個 Agent 的連續記憶或已驗證的破譯結果。

**已有舊版 `artifacts/volume_llm_study.json` 的使用者不需要重新送八次 LLM！** 只要更新 PR 分支並執行 `run_volume_view_windows.bat`，程式會根據原 JSON 已保存的 `trace[].accepted` 候選，在本機使用相同預設求解參數（iterations=2、restarts=2）重新計算，產出 `artifacts/volume_llm_study_decipher.html` 與 `.json`；不呼叫任何 LLM API，原檔不覆寫。此視圖標記為「依建議紀錄重算」，並與原始報告的 Top-1 分數核對。如果當初使用自訂 `--iterations`／`--restarts` 或後續求解器改變，可能出現重算不一致，畫面不是歷史上原封不動的模型輸出。

無 Windows 批次檔時的命令：

```bash
PYTHONPATH=src python -m han_codebook.volume_llm --rebuild-view-from artifacts/volume_llm_study.json
```

本次另外修正兩個 Review P2：單一回覆中同碼組／候選詞重複不再放大加權；明確 `--capture-llm-io` 啟用時，LLM 批次失敗會保存部分 Prompt 與回覆到 `artifacts/volume_llm_study.failed.json`，保留非零結束碼且不生成該失敗批次的成功評分。此 `.failed.json` 可能包含敏感輸入，請勿放進公開 repo。
