@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
if not exist .venv\Scripts\python.exe (
 echo [ERROR] Run setup_windows.bat first.
 exit /b 1
)
set "PYTHONPATH=%CD%\src"
rem Detect a stale web server before opening a browser pointed at its old process.
.venv\Scripts\python.exe -c "import socket,sys;s=socket.socket();s.settimeout(1);used=(s.connect_ex(('127.0.0.1',8765))==0);s.close();sys.exit(1 if used else 0)"
if errorlevel 1 (
 echo [ERROR] TCP port 8765 is already in use. A previous Python server may still be running.
 echo [ACTION] Stop the previous run_web_windows.bat window with Ctrl+C, then try again.
 echo [INFO] This script will not force-stop any process.
 exit /b 1
)
rem Print imported backend module to distinguish current source from an old installed package.
.venv\Scripts\python.exe -c "import sys,han_codebook.model_settings as m;p=getattr(m,'SUPPORTED_LLM_PROVIDERS',());print('[web] Backend module:',m.__file__);print('[web] Provider capabilities:',','.join(p) if p else 'LEGACY');sys.exit(0 if 'ollama' in p else 2)"
if errorlevel 1 (
 echo [ERROR] Imported Python backend does not support Ollama native API.
 echo [ACTION] Update local main, verify this is the correct repo folder, then restart.
 exit /b 1
)
echo [web] Open http://127.0.0.1:8765 in your browser.
start "" "http://127.0.0.1:8765"
.venv\Scripts\python.exe -u -m han_codebook.web --project-root . --config config.yaml
endlocal
