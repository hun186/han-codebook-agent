@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m han_codebook.benchmark --config benchmarks/config.yaml %*
) else (
  python -m han_codebook.benchmark --config benchmarks/config.yaml %*
)
pause
