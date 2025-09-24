@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -m venv .venv
)
call .venv\Scripts\activate
pip install --upgrade pip
pip install pyinstaller -r requirements.txt
pyinstaller --noconfirm --clean freeze.spec
echo.
echo Built to dist\car-tracker\car-tracker.exe
