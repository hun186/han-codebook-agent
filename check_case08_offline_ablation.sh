#!/bin/sh
# Strictly offline case 08 paired metadata ablation; no LLM and no network.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi
export PYTHONPATH="$ROOT/src"
cd "$ROOT"
exec "$PYTHON" -u scripts/check_case08_offline_ablation.py "$@"
