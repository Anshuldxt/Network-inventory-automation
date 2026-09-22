@echo off
cd /d "%~dp0"
set APP=%CD%\multivendor_app.py
schtasks /Create /TN "MultiVendorNetworkInventory-DailySync" /TR "python \"%APP%\" --sync-and-import" /SC DAILY /ST 10:00 /F /RL LIMITED
if errorlevel 1 echo Could not create scheduled task. Run this file as the current Windows user.
if not errorlevel 1 echo Daily sync scheduled for 10:00 local time.
pause
