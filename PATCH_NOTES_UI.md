# Frontend polish patch

This patch uses the existing multi-vendor search build and refreshes only the desktop UI.

## Included
- Ericsson-inspired navy/blue light theme
- Branded header with workspace status
- KPI cards for records, vendors, report tabs and search status
- Separate action bar for file, folder, ZIP import and Sync Now
- Prominent global search panel with multi-value hint
- Matching Report Tabs navigator with vendor, tab and result count
- Click a matching row to open the corresponding report tab
- Styled report grids and notebook tabs
- Existing Huawei, Ericsson and ZTE import, search, export and sync logic retained

Before testing, keep the existing `site_inventory.sqlite3` handling unchanged. For a clean test, delete the database and re-import the source reports.
