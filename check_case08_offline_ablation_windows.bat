@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Local Python environment missing. Run setup_windows.bat first.
  pause
  exit /b 1
)
set "PYTHONPATH=%CD%\src"
echo [OFFLINE CASE08] Two deterministic zero-LLM research runs: metadata ON/OFF.
echo [OFFLINE CASE08] No Ollama, chat completions, endpoint probes or network.
".venv\Scripts\python.exe" -u scripts\check_case08_offline_ablation.py %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (echo [PASS] Study saved in artifacts\offline_case08_studies.) else (echo [FAIL] Offline study was not accepted.)
echo.
pause
exit /b %RC%
