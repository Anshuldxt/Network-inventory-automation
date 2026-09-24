import csv
import io
import re
import zipfile
from pathlib import Path

from openpyxl import load_workbook

REQUIRED_EXT = {".csv", ".xlsx", ".xlsm"}


def clean(value):
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "nat", "none"} else text


def norm_header(value, index):
    value = clean(value)
    return value or f"Column_{index + 1}"


# Exact allow-list of source file names the business wants imported. Anything not
# matching one of these patterns is ignored, whether it's a standalone upload or an
# entry inside a ZIP archive. Matching is done on a lowercased, whitespace-normalized
# basename with the extension stripped, so a trailing date/suffix like
# "NetworkDumpAuditReport_20260922.xlsx" or "Report_GSM_combine_1.csv" still matches.
ALLOWED_SOURCE_PATTERNS = (
    # Huawei
    "report_gsm_combine",
    "report_lte_s1_combine",   # "Report_LTE S1_combine" normalizes to this
    "report_lte_combine",
    "report_ne_report_combine",
    "report_nr_combine",
    "report_umts_combine",
    "devip_combine_others",
    "vlan_combine_others",
    # Ericsson
    "networkdumpauditreport",
    "network_cell_status_output",  # "Network Cell Status Output" normalizes to this
    # ZTE
    "zte_network_inventory_dump",
    "zte_2g_gsm_combined",
    "zte_3g_umts_combined",
    "zte_4g_lte_combined",
    "zte_5g_nr_combined",
)


def _normalize_name(name: str) -> str:
    stem = Path(str(name)).stem.lower()
    stem = re.sub(r"[\s\-]+", "_", stem)
    stem = re.sub(r"_+", "_", stem)
    return stem


def source_is_recognized(name: str) -> bool:
    """Only these exact known network-report file names are imported; everything
    else (unrelated CSVs/XLSX dropped in the input folder or bundled in a ZIP) is
    skipped."""
    normalized = _normalize_name(name)
    # "Report_LTE_combine" must not accidentally match the more specific
    # "report_lte_s1_combine" pattern check order is irrelevant here since we
    # require the pattern to actually appear as a substring of the real name.
    return any(pattern in normalized for pattern in ALLOWED_SOURCE_PATTERNS)


def classify(name, sheet=""):
    s = (str(name) + " " + str(sheet)).lower()
    if "huawei" in s or any(x in s for x in [
        "report_ne", "report_gsm", "report_umts", "report_lte", "report_nr",
        "devip", "vlan_combine", "lte s1", "s1_combine",
    ]):
        vendor = "Huawei"
    elif "zte" in s or any(x in s for x in ["nodedata", "cell_dump", "zte_"]):
        vendor = "ZTE"
    elif "ericsson" in s or any(x in s for x in [
        "networkdumpaudit", "network cell status", "network_cell", "enmfdd", "enmtdd",
    ]):
        vendor = "Ericsson"
    else:
        vendor = "Other"

    if vendor == "Huawei":
        if "gsm" in s:
            report = "2G"
        elif "umts" in s:
            report = "3G"
        elif "s1" in s:
            report = "S1/MME"
        elif "lte" in s:
            report = "4G"
        elif "nr" in s:
            report = "5G"
        elif "devip" in s:
            report = "IP"
        elif "vlan" in s:
            report = "VLAN"
        elif "ne" in s:
            report = "NE"
        else:
            report = "Other"
    elif vendor == "ZTE":
        sheet_l = str(sheet).lower()
        if "network_inventory" in s:
            # ZTE_NETWORK_INVENTORY_DUMP.xlsx always has "network_inventory" in its
            # own filename, so we must key off the *sheet* name, not the filename,
            # to tell the NodeData sheet apart from the IP sheet.
            report = "IP" if sheet_l == "ip" else "NE"
        elif "2g" in s or "gsm" in s:
            report = "2G"
        elif "3g" in s or "umts" in s:
            report = "3G"
        elif "4g" in s or "lte" in s:
            report = "4G"
        elif "5g" in s or "nr" in s:
            report = "5G"
        else:
            report = str(sheet) or "Other"
    elif vendor == "Ericsson":
        if "network cell status" in s:
            report = str(sheet) or "Cell Status"
        elif str(sheet) in {"Network Dump Audit", "2G", "TCU"}:
            report = str(sheet)
        elif "audit" in s:
            report = str(sheet) or "Network Dump Audit"
        else:
            report = str(sheet) or "Other"
    else:
        report = str(sheet) or "Other"
    return vendor, report


def row_meta(row):
    low = {str(k).lower(): clean(v) for k, v in row.items()}
    label = next((low[k] for k in [
        "userlabel", "cell name", "cellname", "nodeid", "nename", "ne name",
    ] if low.get(k)), "")
    site_key = re.sub(r"[^A-Za-z0-9]", "", label)[:7].upper() if label else ""
    searchable = " ".join(clean(v) for v in row.values()).lower()
    return site_key, searchable


def rows_from_csv(data, encoding="latin1"):
    text = data.decode(encoding, errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
    except Exception:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    all_rows = list(reader)
    if not all_rows:
        return []
    headers = [norm_header(x, i) for i, x in enumerate(all_rows[0])]
    output = []
    for values in all_rows[1:]:
        padded = list(values) + [""] * len(headers)
        row = {headers[i]: clean(padded[i]) for i in range(len(headers))}
        if any(row.values()):
            output.append(row)
    return output


def rows_from_xlsx(data):
    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    output = []
    for sheet in workbook.sheetnames:
        worksheet = workbook[sheet]
        iterator = worksheet.iter_rows(values_only=True)
        try:
            headers = [norm_header(x, i) for i, x in enumerate(next(iterator))]
        except StopIteration:
            continue
        for values in iterator:
            padded = list(values) + [None] * len(headers)
            row = {headers[i]: clean(padded[i]) for i in range(len(headers))}
            if any(row.values()):
                output.append((sheet, row))
    return output


def iter_sources(path: Path):
    extension = path.suffix.lower()
    if extension == ".zip":
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                member = Path(info.filename)
                if member.suffix.lower() not in REQUIRED_EXT:
                    continue
                if not source_is_recognized(info.filename):
                    continue
                yield from iter_bytes(member.name, archive.read(info))
        return
    # Standalone upload (not a ZIP): apply the same allow-list so a random CSV/XLSX
    # that isn't on the approved list is never imported.
    if not source_is_recognized(path.name):
        return
    yield from iter_bytes(path.name, path.read_bytes())


def iter_bytes(name, data):
    extension = Path(name).suffix.lower()
    if extension == ".csv":
        yield name, "", rows_from_csv(data)
    elif extension in {".xlsx", ".xlsm"}:
        grouped = {}
        for sheet, row in rows_from_xlsx(data):
            grouped.setdefault(sheet, []).append(row)
        for sheet, rows in grouped.items():
            yield name, sheet, rows


def filter_sheet(vendor, report, source, sheet):
    if vendor == "Ericsson" and (
        "networkdumpaudit" in source.lower() or "execution_report" in source.lower()
    ):
        return sheet in {"Network Dump Audit", "2G", "TCU"}
    return True
