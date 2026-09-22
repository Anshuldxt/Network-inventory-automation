@echo off
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
  echo Python 3.10 or newer is required.
  pause
  exit /b 1
)
python -m pip install -r requirements.txt
python multivendor_app.py
