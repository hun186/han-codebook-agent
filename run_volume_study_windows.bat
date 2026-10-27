@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist .venv\Scripts\python.exe (
  echo [ERROR] Run setup_windows.bat first.
  exit /b 1
)
set "PYTHONPATH=%CD%\src"
echo [study] Same codebook in each corpus, zero known plaintext; sample sizes 10/25/50/100.
echo [study] Three synthetic seeds; offline search only, no LLM calls.
.venv\Scripts\python.exe -u -m han_codebook.volume --out artifacts\volume_study.json
if errorlevel 1 (
  echo [ERROR] Volume benchmark failed.
  exit /b 1
)
echo Reports: artifacts\volume_study.json artifacts\volume_study.md and artifacts\volume_study.html
endlocal
