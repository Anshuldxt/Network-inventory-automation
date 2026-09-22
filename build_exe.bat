@echo off
setlocal
where python >nul 2>nul
if %errorlevel%==0 goto build
where python3 >nul 2>nul
if %errorlevel%==0 (
  set PY=python3
  goto build3
)
echo Python 3.10+ was not found.
pause
exit /b 1
:build
set PY=python
:build3
%PY% -m pip install -r requirements.txt
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name MultiVendorSiteSearch --hidden-import auto_sync --hidden-import win32com.client --hidden-import pythoncom --hidden-import pywintypes huawei_site_search_tool.py
copy /Y auto_sync_config.json dist\auto_sync_config.json >nul
copy /Y operator_mapping.json dist\operator_mapping.json >nul
echo EXE created in dist\MultiVendorSiteSearch.exe
pause
