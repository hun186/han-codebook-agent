@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist .venv\Scripts\python.exe (
  echo [ERROR] Python environment missing. Run setup_windows.bat first.
  exit /b 2
)
if not exist artifacts\volume_llm_study.json (
  echo [ERROR] Missing artifacts\volume_llm_study.json. Run the LLM volume study first.
  exit /b 2
)
set "PYTHONPATH=%CD%\src"
echo [view] Rebuilding original suggestions locally. NO LLM API calls.
.venv\Scripts\python.exe -u -m han_codebook.volume_llm --rebuild-view-from artifacts\volume_llm_study.json
if errorlevel 1 (
  echo [ERROR] Local replay failed. See diagnostics above.
  exit /b 2
)
start "" "artifacts\volume_llm_study_decipher.html"
echo [view] Opened artifacts\volume_llm_study_decipher.html
endlocal
