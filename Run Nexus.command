#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"

# Set a custom port if you want, e.g.:
# export NEXUS_PORT=8088

if [ ! -d ".venv" ]; then
  /usr/bin/env python3 -m venv .venv
fi
source .venv/bin/activate

if ! python -c "import fastapi, uvicorn, sqlalchemy, pydantic, pandas" 2>/dev/null; then
  python -m pip install --upgrade pip
  pip install -r requirements.txt
fi

python run_app.py

