@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher py.exe not found. Install Python 3.10+ first.
  exit /b 1
)
py -3 -m venv .venv
if errorlevel 1 exit /b 1
set "PYTHONPATH=%CD%\src"
echo Installing local research application dependencies (PyYAML, python-docx, lxml).
echo This may need network access or pre-downloaded compatible wheels.
.venv\Scripts\python.exe -m pip install -e .
if errorlevel 1 (
  echo ERROR: dependency install failed. For air-gapped installs, prepare matching wheel files first.
  exit /b 1
)
.venv\Scripts\python.exe -m unittest discover -s tests -v
if errorlevel 1 exit /b 1
echo Setup and tests succeeded.
endlocal
