#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

# Set a custom port if you want, e.g.:
# export NEXUS_PORT=8088

VENV_DIR=".venv"
PYTHON_BIN="$VENV_DIR/bin/python"

if [ ! -x "$PYTHON_BIN" ]; then
  /usr/bin/env python3 -m venv "$VENV_DIR"
fi

# Use the venv interpreter directly so renaming the project directory keeps working.
if ! "$PYTHON_BIN" -c "import fastapi, uvicorn, sqlalchemy, pydantic, pandas" 2>/dev/null; then
  "$PYTHON_BIN" -m pip install --upgrade pip
  "$PYTHON_BIN" -m pip install -r requirements.txt
fi

"$PYTHON_BIN" run_app.py
