#!/bin/sh
# One command from Linux/macOS, works offline and never opens a real model.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi
export PYTHONPATH="$ROOT/src"
cd "$ROOT"
"$PYTHON" -u scripts/check_manual_alignment_workbench.py \
  --output "$ROOT/artifacts/diagnostics/alignment_smoke_latest.json"
