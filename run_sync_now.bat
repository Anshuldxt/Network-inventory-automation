@echo off
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (echo Python is required.&pause&exit /b 1)
python multivendor_app.py --sync-and-import
pause
