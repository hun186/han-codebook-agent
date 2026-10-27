@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist .venv\Scripts\python.exe (
  echo Run setup_windows.bat first.
  exit /b 1
)
set "PYTHONPATH=%CD%\src"
.venv\Scripts\python.exe -m han_codebook --config config.offline.yaml
if errorlevel 1 exit /b 1
echo Report: artifacts\offline_demo.json
endlocal
