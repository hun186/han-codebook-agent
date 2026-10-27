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
echo Installing YAML parser dependency (PyYAML). This may need network access.
.venv\Scripts\python.exe -m pip install "PyYAML>=6.0,<7"
if errorlevel 1 (
  echo ERROR: PyYAML install failed. For air-gapped use, prepare a PyYAML wheel in advance.
  exit /b 1
)
.venv\Scripts\python.exe -m unittest discover -s tests -v
if errorlevel 1 exit /b 1
echo Setup and tests succeeded.
endlocal
