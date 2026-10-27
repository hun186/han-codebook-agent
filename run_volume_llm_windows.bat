@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist .venv\Scripts\python.exe (
  echo [ERROR] Run setup_windows.bat first.
  exit /b 1
)
set "PYTHONPATH=%CD%\src"
echo [LLM study] One fixed codebook per seed. Compare 10,25,50,100 cipher messages.
echo [LLM study] All messages sent in batches of up to 25; 1 LLM round; 1 seed; 8 chat API calls.
echo [LLM study] Transmits fictional test messages to endpoint in config.yaml. NO raw Prompt capture by default.
.venv\Scripts\python.exe -u -m han_codebook.volume_llm --enable-llm --llm-config config.yaml --seeds 101 --sizes 10,25,50,100 --rounds 1 --batch-size 25 --out artifacts\volume_llm_study.json
if errorlevel 1 (
  echo [ERROR] LLM comparison failed; see the error above. Offline benchmark unchanged.
  exit /b 1
)
echo Reports: artifacts\volume_llm_study.json artifacts\volume_llm_study.md artifacts\volume_llm_study.html
endlocal
