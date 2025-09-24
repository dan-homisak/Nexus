@echo off
setlocal
cd /d "%~dp0"
if exist .venv\Scripts\activate (
  call .venv\Scripts\activate
)
python run_app.py
