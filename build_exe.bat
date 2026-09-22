@echo off
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
  echo Python 3.10 or newer is required.
  pause
  exit /b 1
)
python -m pip install -r requirements.txt
python -m PyInstaller --noconfirm --clean --onefile --windowed --name MultiVendorNetworkInventory multivendor_app.py
if exist dist\MultiVendorNetworkInventory.exe echo EXE created at dist\MultiVendorNetworkInventory.exe
pause
