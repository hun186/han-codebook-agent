@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist .venv\Scripts\python.exe (
 echo [ERROR] Run setup_windows.bat first.
 exit /b 1
)
set "PYTHONPATH=%CD%\src"
echo [web] Open http://127.0.0.1:8765 in your browser.
start "" "http://127.0.0.1:8765"
.venv\Scripts\python.exe -u -m han_codebook.web --project-root . --config config.yaml
endlocal
