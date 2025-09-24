@echo off
setlocal
cd /d "%~dp0"
rem Set a custom port if you want, e.g.:
rem set NEXUS_PORT=8088

if not exist .venv\Scripts\python.exe (
  py -m venv .venv
)
call .venv\Scripts\activate

python -c "import fastapi, uvicorn, sqlalchemy, pydantic, pandas" >nul 2>&1
if errorlevel 1 (
  python -m pip install --upgrade pip
  pip install -r requirements.txt
)

python run_app.py

