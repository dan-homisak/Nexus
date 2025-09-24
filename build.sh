#!/usr/bin/env bash
set -euo pipefail
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install pyinstaller -r requirements.txt
pyinstaller --noconfirm --clean freeze.spec
echo "Built to dist/nexus/"
