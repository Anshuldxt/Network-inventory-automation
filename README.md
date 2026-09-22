# Multi-Vendor Site Search — Phase 2 Auto-Sync Build

This build keeps Huawei, ZTE and Ericsson data in vendor/report-specific tabs and adds daily Outlook attachment synchronization.

## Run the GUI

```powershell
python -m pip install -r requirements.txt
python huawei_site_search_tool.py
```

The GUI now has **Sync Now**. It reads matching attachments from the Outlook profile, saves them into the configured OneDrive/SharePoint-synced `Input` folder, and imports them into the local SQLite database.

## Daily schedule

The default schedule is **daily at 10:00 local time** (the user's machine is expected to be on India time / IST).

1. Confirm `auto_sync_config.json`.
2. Run `install_auto_sync_task.bat` once.
3. Test immediately with `run_sync_now.bat` or `Start-ScheduledTask -TaskName MultiVendorSiteSearch-DailySync`.

The task runs as the currently logged-in Windows user and uses the already-configured Outlook profile and searches configured Outlook stores/folders. Leave `mailbox_name` blank to search all configured stores; set it to a shared-mailbox display name to scope it.

## Current auto-sync filters

Sender matching uses `ENABLE-NOREPLY` by default. Subject and attachment filters are:

| Vendor | Subject contains | Attachment pattern |
|---|---|---|
| Huawei | `DTAC-OF-TH | RAN - True Huawei Daily Cell NE Status |` | `Report.zip` |
| Ericsson | `TRUE_BO_RAN_ERICSSON_ENABLE_Daily_Network_Dump_Audit` | `*_Execution_Report.zip` |
| Ericsson | `TRUE | Network Cell Audit - Ericsson |` | `Network Cell Status Reports_*.zip` |
| ZTE | `TRUE_BO_RAN_ZTE_Enable_Daily_NE_inventory_report` | `HARDWARE_SOFTWARE.zip` |
| ZTE | `TRUE_BO_RAN_ZTE_Enable_Daily_Cell_report` | `CELL_DUMP.zip` |

Edit `auto_sync_config.json` if sender, subject, filename, mailbox, or folder changes. The path is currently configured as:

```text
C:\Users\eansdix\OneDrive - Ericsson\Daily Work\2026\Sep\gleaninvtool\Input
```

## Duplicate handling

`auto_sync_manifest.json` stores processed Outlook message/attachment keys. New daily messages replace the stable attachment filename in the Input folder using an atomic save, then import the latest data. Re-running the same message skips it. If the database is deleted, use the GUI folder/ZIP import to rebuild it, or clear the manifest if you want to force a sync re-import.

## Existing import behavior

- ZIP, folder and individual CSV/XLSX/XLSM imports remain supported.
- Huawei tabs are unchanged.
- ZTE tabs remain `ZTE - NE`, `ZTE - 2G Cell`, `ZTE - 3G Cell`, `ZTE - 4G Cell`, `ZTE - 5G Cell`.
- Ericsson `NetworkDumpAuditReport_*.xlsx` imports only `Network Dump Audit`, `2G`, and `TCU`; `TERMPOINT_DATA` is ignored.
- Ericsson `Network Cell Status Output_*.xlsx` imports every sheet.
- Power BI is not included in this phase.

## Windows requirement

Automatic mailbox retrieval requires Microsoft Outlook desktop configured with the shared mailbox and `pywin32`. The GUI/import/search layer can still be used without Outlook sync.

## Scheduler fix

The installer uses Windows Task Scheduler logon type `Interactive`, which is the valid value for a task that runs in the logged-in user session.
