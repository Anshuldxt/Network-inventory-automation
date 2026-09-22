@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 goto run
where python3 >nul 2>nul
if %errorlevel%==0 (
  set PY=python3
  goto run3
)
echo Python 3.10+ was not found. Install Python and add it to PATH.
pause
exit /b 1
:run
set PY=python
:run3
%PY% auto_sync.py --sync-now
pause
