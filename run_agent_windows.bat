@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist .venv\Scripts\python.exe (
  echo [ERROR] Run setup_windows.bat first.
  exit /b 1
)
set "PYTHONPATH=%CD%\src"
echo [1/2] Checking configured LLM transport and models endpoint ...
.venv\Scripts\python.exe -u -m han_codebook --config config.yaml --check-llm
if errorlevel 1 (
  echo [ERROR] LLM preflight failed. Please check config.yaml, network and reverse proxy.
  exit /b 1
)
echo [2/2] Running agent with continuous progress ...
.venv\Scripts\python.exe -u -m han_codebook --config config.yaml
if errorlevel 1 (
  echo [ERROR] Agent failed. Check the message above.
  exit /b 1
)
echo Report: artifacts\with_agent.json
endlocal
