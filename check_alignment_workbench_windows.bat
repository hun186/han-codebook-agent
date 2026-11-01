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
echo [OFFLINE] Running SYNTHETIC alignment preview / acceptance / save checks.
echo [OFFLINE] Uses only an ephemeral 127.0.0.1 server, no Ollama or real cases.
".venv\Scripts\python.exe" -u scripts\check_manual_alignment_workbench.py --output "%CD%\artifacts\diagnostics\alignment_smoke_latest.json" %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (echo [PASS] Offline alignment E2E completed.) else (echo [FAIL] See sanitized report in artifacts\diagnostics.)
echo Report: %CD%\artifacts\diagnostics\alignment_smoke_latest.json
pause
exit /b %RC%
