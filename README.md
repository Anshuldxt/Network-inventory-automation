# Multi-Vendor Network Inventory — Windows Application

This is a buildable Windows desktop application for Huawei, Ericsson and ZTE reports.

## Features

- Separate vendor/report tabs through the common search result navigator
- Global search across all imported reports
- Matching report tab and count shown after every search
- CSV, XLSX and ZIP import
- Per-user Input folder selection; no hard-coded Windows username
- SQLite local database and background import/search
- OneDrive/SharePoint-synced folder can be selected with **Input Folder**
- Windows EXE build script

## Run on a Windows laptop

Install Python 3.10+ once, then double-click `run_tool.bat`.

Or in PowerShell:

```powershell
python -m pip install -r requirements.txt
python multivendor_app.py
```

## Build a standalone EXE

On Windows, double-click `build_exe.bat`. The output is:

```text
dist\MultiVendorNetworkInventory.exe
```

The target laptop does not need Python after the EXE is built.

## First use

1. Open the app.
2. Click **Input Folder** and choose the user's OneDrive/SharePoint-synced Input folder.
3. Click **Import Folder** or **Import ZIP**.
4. Wait for the import status to complete.
5. Enter a site/NE/IP/cell value in **Global search**.
6. The left panel shows only matching report tabs and counts; click a tab to view rows.
7. Use **Export Search** to save the combined results.

## Classification rules

- Huawei CSV reports are classified by their filenames (`Report_Ne`, GSM, UMTS, LTE, NR, DEV/IP, VLAN, S1).
- ZTE workbooks are classified by filename and sheet name. ZTE `GSM`, `UMTS`, `LTE_*`, `NR`, `NodeData` and `IP` are supported.
- Ericsson `NetworkDumpAuditReport` imports only `Network Dump Audit`, `2G`, and `TCU`; `TERMPOINT_DATA` is ignored.
- Ericsson `Network Cell Status Output` imports `UtranCell`, `EUtranCellFDD`, `EUtranCellTDD`, and `NRCellDU`.
- ZIP archives are read without executing members; nested ZIPs are not unpacked.

For a clean rebuild, close the app and delete `inventory.sqlite3`, then import again.

## Sharing with another team member

Copy the folder to the other Windows laptop. The user selects their own Input folder once; the app stores it in `app_config.json`. Outlook sync uses the logged-in user's Outlook profile and shared-mailbox permissions. Python is only needed to run/build the source package; after `build_exe.bat`, use `dist\MultiVendorNetworkInventory.exe` as the standalone application.

The UI opens dedicated tabs for every supported report. After a search, the left `Matching reports` panel lists only tabs with matches; selecting one activates that report tab. Both CSV and Excel export buttons are available.
