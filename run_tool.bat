@echo off
setlocal
where python >nul 2>nul
if %errorlevel%==0 (
  python huawei_site_search_tool.py
  exit /b %errorlevel%
)
where python3 >nul 2>nul
if %errorlevel%==0 (
  python3 huawei_site_search_tool.py
  exit /b %errorlevel%
)
echo Python 3.10+ was not found. Install Python and add it to PATH.
pause
