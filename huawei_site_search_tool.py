from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Iterable

import pandas as pd
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # Allows the importer/database layer to be tested in headless Linux.
    tk = None
    filedialog = messagebox = ttk = None

APP_TITLE = "Ericsson Network Inventory | Multi-Vendor Site Search"
DB_NAME = "site_inventory.sqlite3"

def app_base_dir() -> Path:
    # In a PyInstaller build, keep the DB/config beside the EXE rather than
    # inside the temporary extraction directory.
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

DEFAULT_OPERATOR_MAP = {
    "ENM-FDD1": "DTAC", "ENM-FDD2": "DTAC", "ENM-FDD3": "DTAC", "ENM-FDD4": "DTAC",
    "ENM-TDD1": "DTAC", "ENM-TDD2": "DTAC", "ENM-TDD3": "DTAC",
    "ENM1A": "TRUE", "ENM2A": "TRUE", "ENM3A": "TRUE", "ENM4A": "TRUE",
    "ENM5A": "TRUE", "ENM6A": "TRUE", "ENM7A": "TRUE",
}

def load_operator_map():
    result = dict(DEFAULT_OPERATOR_MAP)
    try:
        with open(app_base_dir() / "operator_mapping.json", encoding="utf-8") as fh:
            loaded = json.load(fh)
        result.update({str(k).strip().upper(): str(v).strip() for k, v in loaded.items()})
    except Exception:
        pass
    return result

OPERATOR_MAP = load_operator_map()

DATASET_ORDER = [
    "Huawei - NE", "Huawei - 2G", "Huawei - 3G", "Huawei - 4G", "Huawei - 5G",
    "Huawei - IP", "Huawei - VLAN", "Huawei - S1",
    "ZTE - NE", "ZTE - 2G Cell", "ZTE - 3G Cell", "ZTE - 4G Cell", "ZTE - 5G Cell",
    "Ericsson - Network Dump Audit", "Ericsson - 2G", "Ericsson - TCU",
    "Ericsson - NRCellDU", "Ericsson - EUtranCellFDD", "Ericsson - EUtranCellTDD", "Ericsson - UtranCell",
]


def clean(v) -> str:
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except Exception:
        pass
    return str(v).strip()


def norm(v) -> str:
    return re.sub(r"\s+", "", clean(v)).upper()


def operator_for_row(row: dict) -> str:
    # Explicit source values take precedence.
    for key in row:
        nk = norm(key)
        if nk in {"OPERATOR", "OPARATOR", "ACTUALOPERATOR"}:
            value = clean(row[key])
            if value:
                return value
    candidates = []
    for key, value in row.items():
        nk = norm(key)
        if nk in {"OSS", "ENM", "ENMNAME", "NODENAME", "NODEID"}:
            candidates.append(clean(value))
    for candidate in candidates:
        if candidate.upper() in OPERATOR_MAP:
            return OPERATOR_MAP[candidate.upper()]
    return ""


def file_kind(name: str) -> str:
    n = Path(name).name.lower()
    if "report_ne_report" in n or "report_ne_" in n:
        return "huawei_ne"
    if "report_gsm" in n:
        return "huawei_2g"
    if "report_umts" in n:
        return "huawei_3g"
    if "report_lte_s1" in n or "lte s1" in n:
        return "huawei_s1"
    if "report_lte" in n:
        return "huawei_4g"
    if "report_nr" in n:
        return "huawei_5g"
    if "devip" in n:
        return "huawei_ip"
    if "vlan" in n:
        return "huawei_vlan"
    if "zte_network_inventory" in n:
        return "zte_ne"
    if "zte_2g" in n or "2g_gsm" in n:
        return "zte_2g"
    if "zte_3g" in n or "3g_umts" in n:
        return "zte_3g"
    if "zte_4g" in n or "4g_lte" in n:
        return "zte_4g"
    if "zte_5g" in n or "5g_nr" in n:
        return "zte_5g"
    if "networkdumpauditreport" in n:
        return "ericsson_audit"
    if "network cell status" in n:
        return "ericsson_cells"
    return "other"


def dataset_for(vendor_kind: str, sheet: str, filename: str) -> str | None:
    s = clean(sheet)
    sl = s.lower()
    if vendor_kind == "huawei_ne": return "Huawei - NE"
    if vendor_kind == "huawei_2g": return "Huawei - 2G"
    if vendor_kind == "huawei_3g": return "Huawei - 3G"
    if vendor_kind == "huawei_4g": return "Huawei - 4G"
    if vendor_kind == "huawei_5g": return "Huawei - 5G"
    if vendor_kind == "huawei_ip": return "Huawei - IP"
    if vendor_kind == "huawei_vlan": return "Huawei - VLAN"
    if vendor_kind == "huawei_s1": return "Huawei - S1"
    if vendor_kind == "zte_ne": return "ZTE - NE"
    if vendor_kind == "zte_2g": return "ZTE - 2G Cell"
    if vendor_kind == "zte_3g": return "ZTE - 3G Cell"
    if vendor_kind == "zte_4g": return "ZTE - 4G Cell"
    if vendor_kind == "zte_5g": return "ZTE - 5G Cell"
    if vendor_kind == "ericsson_audit":
        # Explicit rule: only these three sheets; TERMPOINT_DATA is ignored.
        if sl == "network dump audit": return "Ericsson - Network Dump Audit"
        if sl == "2g": return "Ericsson - 2G"
        if sl == "tcu": return "Ericsson - TCU"
        return None
    if vendor_kind == "ericsson_cells":
        # Explicit rule: every sheet in Network Cell Status Output is imported.
        mapping = {
            "nrcelldu": "Ericsson - NRCellDU",
            "eutrancellfdd": "Ericsson - EUtranCellFDD",
            "eutrancelltdd": "Ericsson - EUtranCellTDD",
            "utrancell": "Ericsson - UtranCell",
        }
        return mapping.get(sl, "Ericsson - " + s)
    return "Other - " + (s or Path(filename).stem)


def dataframe_from_csv(path_or_file, chunksize=5000):
    encodings = ["utf-8", "cp1252", "latin1"]
    last = None
    for enc in encodings:
        try:
            return pd.read_csv(path_or_file, encoding=enc, dtype=str, keep_default_na=False,
                               chunksize=chunksize, on_bad_lines="skip")
        except Exception as exc:
            last = exc
            if hasattr(path_or_file, "seek"):
                path_or_file.seek(0)
    raise last


class Store:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.lock = threading.RLock()
        self.con = sqlite3.connect(db_path, check_same_thread=False)
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA synchronous=NORMAL")
        self.con.executescript("""
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY,
                dataset TEXT NOT NULL,
                vendor TEXT NOT NULL,
                source_file TEXT,
                source_sheet TEXT,
                row_no INTEGER,
                data_json TEXT NOT NULL,
                search_key TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_records_dataset ON records(dataset);
            CREATE INDEX IF NOT EXISTS idx_records_vendor ON records(vendor);
            CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(search_key, content='records', content_rowid='id');
        """)
        self.con.commit()

    def reset_dataset(self, dataset: str):
        with self.lock:
            ids = [r[0] for r in self.con.execute("SELECT id FROM records WHERE dataset=?", (dataset,))]
            self.con.execute("DELETE FROM records WHERE dataset=?", (dataset,))
            for rid in ids:
                self.con.execute("DELETE FROM records_fts WHERE rowid=?", (rid,))
            self.con.commit()

    def insert_rows(self, rows: list[tuple]):
        if not rows:
            return
        with self.lock:
            cur = self.con.cursor()
            cur.executemany("""INSERT INTO records(dataset,vendor,source_file,source_sheet,row_no,data_json,search_key)
                               VALUES(?,?,?,?,?,?,?)""", rows)
            self.con.commit()
            last_id = self.con.execute("SELECT last_insert_rowid()").fetchone()[0]
            start = last_id - len(rows) + 1
            # IDs are contiguous for this executemany in SQLite.
            self.con.executemany("INSERT INTO records_fts(rowid,search_key) VALUES(?,?)",
                                 [(start + i, r[-1]) for i, r in enumerate(rows)])
            self.con.commit()

    def datasets(self):
        with self.lock:
            return [r[0] for r in self.con.execute("SELECT DISTINCT dataset FROM records")]

    def count(self, dataset: str) -> int:
        with self.lock:
            return int(self.con.execute("SELECT COUNT(*) FROM records WHERE dataset=?", (dataset,)).fetchone()[0])

    def headers(self, dataset: str):
        with self.lock:
            row = self.con.execute("SELECT data_json FROM records WHERE dataset=? LIMIT 1", (dataset,)).fetchone()
        if not row:
            return []
        return list(json.loads(row[0]).keys())

    def rows(self, dataset: str, limit=500):
        with self.lock:
            data = self.con.execute("SELECT data_json FROM records WHERE dataset=? ORDER BY id LIMIT ?", (dataset, limit)).fetchall()
        return [json.loads(r[0]) for r in data]

    @staticmethod
    def _fts_expression(term: str) -> str:
        """Build a safe FTS5 prefix expression for an arbitrary user query.

        The old implementation wrapped the wildcard in quotes (e.g.\n        \"RYG7195*\"), which makes FTS5 treat * as literal text and misses
        valid prefixes.  Splitting punctuation into FTS tokens also makes IPs,
        hyphenated names and underscore-delimited identifiers searchable.
        """
        tokens = re.findall(r"[A-Z0-9]+", clean(term).upper())
        return " AND ".join(f"{token}*" for token in tokens if token)

    def search(self, terms: list[str], datasets: list[str], limit=1000):
        if not terms or not datasets:
            return []
        expressions = [self._fts_expression(t) for t in terms]
        expressions = [e for e in expressions if e]
        if not expressions:
            return []
        # Keep common searches fair across vendor/report tabs.  A broad term
        # must not consume the whole global limit in the first dataset.
        per_dataset = max(25, min(1000, limit // max(1, len(datasets))))
        match = " OR ".join(f"({e})" for e in expressions)
        ds_placeholders = ",".join("?" for _ in datasets)
        sql = f"""WITH matched AS (
                    SELECT r.dataset,r.vendor,r.source_file,r.source_sheet,r.row_no,r.data_json,
                           ROW_NUMBER() OVER (PARTITION BY r.dataset ORDER BY r.id) AS rn
                    FROM records_fts f JOIN records r ON r.id=f.rowid
                    WHERE f.records_fts MATCH ? AND r.dataset IN ({ds_placeholders})
                  )
                  SELECT dataset,vendor,source_file,source_sheet,row_no,data_json
                  FROM matched WHERE rn <= ? ORDER BY dataset,rn"""
        with self.lock:
            try:
                rows = self.con.execute(sql, [match, *datasets, per_dataset]).fetchall()
            except sqlite3.OperationalError:
                rows = []
            # If no indexed prefix matches, use a case-insensitive substring
            # fallback.  It is still capped per dataset so one broad value
            # cannot hide all other vendor tabs.
            if not rows:
                clauses = " OR ".join("r.search_key LIKE ? COLLATE NOCASE" for _ in terms)
                sql2 = f"""WITH matched AS (
                              SELECT r.dataset,r.vendor,r.source_file,r.source_sheet,r.row_no,r.data_json,
                                     ROW_NUMBER() OVER (PARTITION BY r.dataset ORDER BY r.id) AS rn
                              FROM records r
                              WHERE r.dataset IN ({ds_placeholders}) AND ({clauses})
                           )
                           SELECT dataset,vendor,source_file,source_sheet,row_no,data_json
                           FROM matched WHERE rn <= ? ORDER BY dataset,rn"""
                rows = self.con.execute(sql2, [*datasets, *[f"%{clean(t).upper()}%" for t in terms], per_dataset]).fetchall()
        out = []
        for ds, vendor, source, sheet, row_no, payload in rows:
            out.append({"dataset": ds, "vendor": vendor, "source_file": source,
                        "source_sheet": sheet, "row_no": row_no, "data": json.loads(payload)})
        return out

    def all_rows(self, dataset: str):
        with self.lock:
            rows = self.con.execute("SELECT data_json FROM records WHERE dataset=? ORDER BY id", (dataset,)).fetchall()
        return [json.loads(r[0]) for r in rows]


def iter_workbook(path: str, filename: str):
    kind = file_kind(filename)
    if kind == "other":
        return
    try:
        xls = pd.ExcelFile(path)
        for sheet in xls.sheet_names:
            dataset = dataset_for(kind, sheet, filename)
            if not dataset:
                continue
            df = pd.read_excel(path, sheet_name=sheet, dtype=str).fillna("")
            yield dataset, sheet, df
    except Exception as exc:
        raise RuntimeError(f"Could not read {filename}: {exc}") from exc


def iter_csv(path: str, filename: str):
    kind = file_kind(filename)
    if kind == "other":
        return
    dataset = dataset_for(kind, "CSV", filename)
    if not dataset:
        return
    reader = dataframe_from_csv(path)
    for df in reader:
        yield dataset, "CSV", df


def import_path(store: Store, path: str, progress=None):
    path = str(path)
    name = os.path.basename(path)
    if name.lower().endswith(".zip"):
        with tempfile.TemporaryDirectory(prefix="site_import_") as td:
            with zipfile.ZipFile(path) as zf:
                members = [m for m in zf.infolist() if not m.is_dir() and not m.filename.startswith("__MACOSX/")]
                for m in members:
                    ext = Path(m.filename).suffix.lower()
                    if ext not in {".xlsx", ".xlsm", ".csv"}:
                        continue
                    # Do not recurse into nested archives. Extract only supported data files safely.
                    target = Path(td) / Path(m.filename).name
                    target.write_bytes(zf.read(m))
                    import_path(store, str(target), progress)
        return
    if name.lower().endswith((".xlsx", ".xlsm")):
        iterator = iter_workbook(path, name)
    elif name.lower().endswith(".csv"):
        iterator = iter_csv(path, name)
    else:
        return
    seen = set()
    for dataset, sheet, df in iterator:
        if dataset not in seen:
            store.reset_dataset(dataset)
            seen.add(dataset)
        rows = []
        for i, raw in enumerate(df.to_dict(orient="records"), 1):
            data = {str(k): clean(v) for k, v in raw.items()}
            search_parts = list(data.values()) + [operator_for_row(data)] + [name, sheet, dataset]
            search_key = " ".join(x.upper() for x in search_parts if x)
            rows.append((dataset, dataset.split(" - ")[0], name, sheet, i, json.dumps(data, ensure_ascii=False), search_key))
            if len(rows) >= 1000:
                store.insert_rows(rows)
                rows.clear()
        store.insert_rows(rows)
        if progress:
            progress(dataset, store.count(dataset))


_TkBase = tk.Tk if tk is not None else object

class App(_TkBase):
    def __init__(self):
        if tk is None:
            raise RuntimeError("Tkinter is required to run the GUI. The data layer is still available for tests.")
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1450x850")
        self.store = Store(str(app_base_dir() / DB_NAME))
        self.views = {}
        self.tab_frames = {}
        self.last_results = {}
        self.busy = False
        self._build()
        self.refresh_tabs()

    def _build(self):
        # Ericsson-inspired light UI: deep navy header, blue action accents,
        # compact KPI cards and a focused global search experience.
        self.configure(bg="#F3F6FA")
        self.minsize(1180, 720)

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("App.TFrame", background="#F3F6FA")
        style.configure("Card.TFrame", background="#FFFFFF", relief="flat")
        style.configure("Header.TFrame", background="#0B1F3A")
        style.configure("HeaderTitle.TLabel", background="#0B1F3A", foreground="#FFFFFF", font=("Segoe UI", 20, "bold"))
        style.configure("HeaderSub.TLabel", background="#0B1F3A", foreground="#BBD0EA", font=("Segoe UI", 9))
        style.configure("Section.TLabel", background="#F3F6FA", foreground="#0B1F3A", font=("Segoe UI", 11, "bold"))
        style.configure("Muted.TLabel", background="#F3F6FA", foreground="#5D6B7A", font=("Segoe UI", 9))
        style.configure("CardTitle.TLabel", background="#FFFFFF", foreground="#607184", font=("Segoe UI", 9))
        style.configure("CardValue.TLabel", background="#FFFFFF", foreground="#0B1F3A", font=("Segoe UI", 18, "bold"))
        style.configure("Toolbar.TFrame", background="#FFFFFF")
        style.configure("Primary.TButton", font=("Segoe UI", 9, "bold"), foreground="#FFFFFF", background="#1677FF", padding=(13, 8))
        style.map("Primary.TButton", background=[("active", "#0E5FD6"), ("pressed", "#0B4EAF")])
        style.configure("Action.TButton", font=("Segoe UI", 9), foreground="#18324F", background="#EAF2FF", padding=(11, 8))
        style.map("Action.TButton", background=[("active", "#D7E8FF"), ("pressed", "#C4DCFF")])
        style.configure("Ghost.TButton", font=("Segoe UI", 9), foreground="#506174", background="#FFFFFF", padding=(10, 8))
        style.map("Ghost.TButton", background=[("active", "#EEF3F8")])
        style.configure("Search.TLabel", background="#FFFFFF", foreground="#18324F", font=("Segoe UI", 10, "bold"))
        style.configure("Treeview", background="#FFFFFF", fieldbackground="#FFFFFF", foreground="#20364D", rowheight=27, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background="#E8EEF5", foreground="#18324F", font=("Segoe UI", 9, "bold"), padding=(8, 7))
        style.map("Treeview", background=[("selected", "#DCEBFF")], foreground=[("selected", "#0B1F3A")])
        style.configure("TNotebook", background="#F3F6FA", borderwidth=0)
        style.configure("TNotebook.Tab", background="#E8EEF5", foreground="#4D6073", padding=(13, 8), font=("Segoe UI", 9, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "#FFFFFF")], foreground=[("selected", "#1677FF")])

        shell = ttk.Frame(self, style="App.TFrame")
        shell.pack(fill="both", expand=True)

        header = ttk.Frame(shell, style="Header.TFrame", padding=(24, 18, 24, 16))
        header.pack(fill="x")
        header.columnconfigure(1, weight=1)
        brand = tk.Canvas(header, width=42, height=42, bg="#0B1F3A", highlightthickness=0)
        brand.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 14))
        brand.create_oval(4, 4, 38, 38, fill="#1677FF", outline="")
        brand.create_text(21, 21, text="N", fill="#FFFFFF", font=("Segoe UI", 17, "bold"))
        ttk.Label(header, text="Multi-Vendor Network Inventory", style="HeaderTitle.TLabel").grid(row=0, column=1, sticky="w")
        ttk.Label(header, text="Search, inspect and export Huawei, Ericsson and ZTE network data from one workspace", style="HeaderSub.TLabel").grid(row=1, column=1, sticky="w", pady=(3, 0))
        self.header_state = tk.StringVar(value="READY")
        state = tk.Label(header, textvariable=self.header_state, bg="#12345D", fg="#BFE0FF", font=("Segoe UI", 9, "bold"), padx=12, pady=6)
        state.grid(row=0, column=2, rowspan=2, sticky="e")

        kpis = ttk.Frame(shell, style="App.TFrame", padding=(18, 14, 18, 8))
        kpis.pack(fill="x")
        for i in range(4):
            kpis.columnconfigure(i, weight=1)
        self.kpi_vars = {
            "records": tk.StringVar(value="0"),
            "vendors": tk.StringVar(value="0"),
            "tabs": tk.StringVar(value="0"),
            "status": tk.StringVar(value="Ready"),
        }
        self._make_kpi(kpis, 0, "TOTAL RECORDS", self.kpi_vars["records"], "#1677FF")
        self._make_kpi(kpis, 1, "VENDORS LOADED", self.kpi_vars["vendors"], "#00A88F")
        self._make_kpi(kpis, 2, "REPORT TABS", self.kpi_vars["tabs"], "#8B5CF6")
        self._make_kpi(kpis, 3, "WORKSPACE STATUS", self.kpi_vars["status"], "#F59E0B")

        toolbar = ttk.Frame(shell, style="Toolbar.TFrame", padding=(16, 10))
        toolbar.pack(fill="x", padx=18, pady=(0, 10))
        ttk.Button(toolbar, text="Import files", style="Action.TButton", command=self.choose_files).pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="Import folder", style="Action.TButton", command=self.choose_folder).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Import ZIP", style="Action.TButton", command=self.choose_zip).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Sync now", style="Primary.TButton", command=self.sync_async).pack(side="left", padx=6)
        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=12)
        ttk.Label(toolbar, text="Tip: use site, NE, cell or IP", style="Muted.TLabel").pack(side="left")

        search_card = ttk.Frame(shell, style="Card.TFrame", padding=(16, 13))
        search_card.pack(fill="x", padx=18, pady=(0, 10))
        search_card.columnconfigure(1, weight=1)
        ttk.Label(search_card, text="GLOBAL SEARCH", style="Search.TLabel").grid(row=0, column=0, sticky="nw", padx=(0, 14))
        self.query = tk.Text(search_card, width=50, height=2, relief="flat", bd=0, wrap="word", font=("Segoe UI", 10), bg="#F6F9FC", fg="#18324F", insertbackground="#1677FF", padx=10, pady=7)
        self.query.grid(row=0, column=1, sticky="ew")
        ttk.Button(search_card, text="Search all vendors", style="Primary.TButton", command=self.search_async).grid(row=0, column=2, padx=(12, 5))
        ttk.Button(search_card, text="Clear", style="Ghost.TButton", command=self.clear_search).grid(row=0, column=3)
        ttk.Button(search_card, text="Export results", style="Ghost.TButton", command=self.export_search).grid(row=0, column=4, padx=(5, 0))
        ttk.Label(search_card, text="Paste multiple values separated by comma, semicolon or new line", style="CardTitle.TLabel").grid(row=1, column=1, sticky="w", pady=(5, 0))

        match_box = ttk.Frame(shell, style="Card.TFrame", padding=(16, 12))
        match_box.pack(fill="x", padx=18, pady=(0, 10))
        match_box.columnconfigure(0, weight=1)
        match_title = ttk.Frame(match_box, style="Card.TFrame")
        match_title.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 7))
        ttk.Label(match_title, text="MATCHING REPORT TABS", style="Section.TLabel").pack(side="left")
        self.matching_hint = ttk.Label(match_title, text="Search to see exactly where the value was found.", style="CardTitle.TLabel")
        self.matching_hint.pack(side="right")
        self.matching_tabs = ttk.Treeview(match_box, columns=("vendor", "tab", "matches"), show="headings", height=4)
        self.matching_tabs.heading("vendor", text="Vendor")
        self.matching_tabs.heading("tab", text="Report tab")
        self.matching_tabs.heading("matches", text="Matches")
        self.matching_tabs.column("vendor", width=125, anchor="w")
        self.matching_tabs.column("tab", width=390, anchor="w")
        self.matching_tabs.column("matches", width=100, anchor="center")
        self.matching_tabs.grid(row=1, column=0, sticky="ew")
        match_scroll = ttk.Scrollbar(match_box, orient="vertical", command=self.matching_tabs.yview)
        match_scroll.grid(row=1, column=1, sticky="ns")
        self.matching_tabs.configure(yscrollcommand=match_scroll.set)
        self.matching_tabs.bind("<ButtonRelease-1>", self.open_matching_tab)
        self.matching_tabs.bind("<Double-1>", self.open_matching_tab)
        self.matching_tabs.bind("<Return>", self.open_matching_tab)

        content = ttk.Frame(shell, style="App.TFrame")
        content.pack(fill="both", expand=True, padx=18, pady=(0, 4))
        content.rowconfigure(0, weight=1); content.columnconfigure(0, weight=1)
        self.nb = ttk.Notebook(content)
        self.nb.grid(row=0, column=0, sticky="nsew")

        status_bar = tk.Frame(shell, bg="#0B1F3A", height=26)
        status_bar.pack(fill="x", side="bottom")
        self.status = tk.StringVar(value="Ready")
        tk.Label(status_bar, textvariable=self.status, bg="#0B1F3A", fg="#D7E7F9", anchor="w", font=("Segoe UI", 9), padx=14).pack(fill="x")

    def _make_kpi(self, parent, col, title, variable, accent):
        card = tk.Frame(parent, bg="#FFFFFF", highlightbackground="#DCE5EE", highlightthickness=1)
        card.grid(row=0, column=col, sticky="ew", padx=5)
        bar = tk.Frame(card, bg=accent, width=5)
        bar.pack(side="left", fill="y")
        body = tk.Frame(card, bg="#FFFFFF", padx=14, pady=9)
        body.pack(side="left", fill="both", expand=True)
        tk.Label(body, text=title, bg="#FFFFFF", fg="#607184", font=("Segoe UI", 8, "bold"), anchor="w").pack(fill="x")
        tk.Label(body, textvariable=variable, bg="#FFFFFF", fg="#0B1F3A", font=("Segoe UI", 16, "bold"), anchor="w").pack(fill="x", pady=(2, 0))

    def set_status(self, text):
        self.after(0, lambda: self.status.set(text))

    def choose_files(self):
        paths = filedialog.askopenfilenames(filetypes=[("Data files", "*.csv *.xlsx *.xlsm *.zip"), ("All files", "*.*")])
        if paths: self.import_async(list(paths))

    def choose_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            paths = [str(p) for p in Path(folder).rglob("*") if p.suffix.lower() in {".csv", ".xlsx", ".xlsm", ".zip"}]
            self.import_async(paths)

    def choose_zip(self):
        path = filedialog.askopenfilename(filetypes=[("ZIP archive", "*.zip")])
        if path: self.import_async([path])

    def sync_async(self):
        if self.busy:
            return
        self.busy = True
        self.set_status("Syncing Outlook attachments and importing...")
        def work():
            try:
                from auto_sync import sync_once
                result = sync_once(app_base_dir(), progress=self.set_status)
                self.after(0, self.refresh_tabs)
                self.header_state.set("SYNC COMPLETE")
                self.set_status(f"Sync complete: {len(result.get('downloaded', []))} new attachment(s), {result.get('skipped', 0)} skipped")
                if result.get("errors"):
                    self.after(0, lambda: messagebox.showwarning("Sync completed with errors", "\n".join(result["errors"])))
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Sync error", str(exc)))
                self.set_status("Sync failed")
            finally:
                self.busy = False
        threading.Thread(target=work, daemon=True).start()

    def import_async(self, paths):
        if self.busy: return
        self.busy = True
        self.set_status(f"Importing {len(paths)} file(s)...")
        def work():
            try:
                for path in paths:
                    import_path(self.store, path, lambda ds, n: self.set_status(f"{ds}: {n:,} rows"))
                self.after(0, self.refresh_tabs)
                self.header_state.set("DATA READY")
                self.set_status("Import complete")
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Import error", str(exc)))
                self.set_status("Import failed")
            finally:
                self.busy = False
        threading.Thread(target=work, daemon=True).start()

    def refresh_tabs(self):
        for tab in self.nb.tabs(): self.nb.forget(tab)
        self.views.clear()
        self.tab_frames.clear()
        self.clear_matching_tabs()
        datasets = self.store.datasets()
        order = [d for d in DATASET_ORDER if d in datasets] + [d for d in datasets if d not in DATASET_ORDER]
        for dataset in order:
            frame = ttk.Frame(self.nb, style="Card.TFrame")
            frame.rowconfigure(0, weight=1); frame.columnconfigure(0, weight=1)
            tree = ttk.Treeview(frame, show="headings")
            y = ttk.Scrollbar(frame, orient="vertical", command=tree.yview); x = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
            tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
            tree.grid(row=0,column=0,sticky="nsew", padx=(8, 0), pady=(8, 0)); y.grid(row=0,column=1,sticky="ns", pady=(8, 0)); x.grid(row=1,column=0,sticky="ew", padx=(8, 0))
            label = dataset.replace(" - ", "  |  ")
            self.nb.add(frame, text=f"{label}  ({self.store.count(dataset):,})")
            self.tab_frames[dataset] = frame
            self.views[dataset] = tree
            self.fill_tree(dataset, self.store.rows(dataset, 300))
        self.update_kpis(datasets)

    def update_kpis(self, datasets=None, matching_tabs=None):
        if not hasattr(self, "kpi_vars"):
            return
        datasets = datasets if datasets is not None else self.store.datasets()
        total = sum(self.store.count(ds) for ds in datasets)
        vendors = {ds.split(" - ")[0] for ds in datasets}
        self.kpi_vars["records"].set(f"{total:,}")
        self.kpi_vars["vendors"].set(str(len(vendors)))
        self.kpi_vars["tabs"].set(str(len(datasets)))
        if matching_tabs is not None:
            self.kpi_vars["status"].set(f"{len(matching_tabs)} match tabs")

    def fill_tree(self, dataset, rows):
        tree = self.views.get(dataset)
        if not tree: return
        for item in tree.get_children(): tree.delete(item)
        headers = []
        for row in rows:
            for k in row:
                if k not in headers: headers.append(k)
        headers = headers[:80]
        tree["columns"] = headers
        for h in headers:
            tree.heading(h, text=h); tree.column(h, width=145, minwidth=80, stretch=False)
        for row in rows:
            tree.insert("", "end", values=[row.get(h, "") for h in headers])

    def search_async(self):
        if self.busy: return
        raw = self.query.get("1.0", "end").strip()
        terms = [t.strip() for t in re.split(r"[,;\n\t]+", raw) if t.strip()]
        terms = [t for t in terms if norm(t) not in {"SITE_SEARCH", "SITE", "SEARCH"}]
        if not terms:
            return
        self.busy = True; self.header_state.set("SEARCHING..."); self.set_status("Searching all vendor tabs...")
        datasets = self.store.datasets()
        def work():
            try:
                results = self.store.search(terms, datasets, 5000)
                grouped = {}
                for r in results: grouped.setdefault(r["dataset"], []).append(r["data"])
                self.last_results = grouped
                def update():
                    for ds, tree in self.views.items():
                        if ds in grouped: self.fill_tree(ds, grouped[ds])
                        else: self.fill_tree(ds, [])
                    self.show_matching_tabs(grouped)
                    self.update_kpis(matching_tabs=grouped)
                    self.status.set(f"Search complete: {len(results):,} result rows across {len(grouped):,} tab(s)")
                    self.header_state.set("SEARCH COMPLETE")
                self.after(0, update)
            except Exception as exc:
                self.after(0, lambda: messagebox.showerror("Search error", str(exc)))
                self.set_status("Search failed")
            finally: self.busy = False
        threading.Thread(target=work, daemon=True).start()

    def clear_matching_tabs(self):
        if not hasattr(self, "matching_tabs"):
            return
        for item in self.matching_tabs.get_children():
            self.matching_tabs.delete(item)
        if hasattr(self, "matching_hint"):
            self.matching_hint.configure(text="Run a search to see matching tabs.")

    def show_matching_tabs(self, grouped):
        self.clear_matching_tabs()
        if not grouped:
            self.matching_hint.configure(text="No matching report tab found.")
            self.kpi_vars["status"].set("No matches")
            self.header_state.set("NO MATCH")
            return
        ordered = sorted(grouped.items(), key=lambda item: (-len(item[1]), DATASET_ORDER.index(item[0]) if item[0] in DATASET_ORDER else 9999, item[0]))
        for dataset, values in ordered:
            vendor = dataset.split(" - ")[0] if " - " in dataset else "Other"
            self.matching_tabs.insert("", "end", iid=dataset, values=(vendor, dataset, f"{len(values):,}"))
        self.matching_hint.configure(text=f"Found matches in {len(ordered)} report tab(s)  •  click a row to open")

    def open_matching_tab(self, _event=None):
        selected = self.matching_tabs.selection()
        if not selected:
            return
        dataset = selected[0]
        frame = self.tab_frames.get(dataset)
        if frame is not None:
            self.nb.select(frame)

    def clear_search(self):
        self.query.delete("1.0", "end")
        self.last_results = {}
        if hasattr(self, "header_state"):
            self.header_state.set("READY")
        if hasattr(self, "kpi_vars"):
            self.kpi_vars["status"].set("Ready")
        self.refresh_tabs()

    def export_search(self):
        if not self.last_results:
            messagebox.showinfo("Export", "Run a search first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".xlsx", filetypes=[("Excel", "*.xlsx"), ("CSV", "*.csv")])
        if not path: return
        try:
            if path.lower().endswith(".csv"):
                rows = []
                for ds, values in self.last_results.items():
                    for row in values:
                        rows.append({"Source Tab": ds, **row})
                pd.DataFrame(rows).to_csv(path, index=False)
            else:
                with pd.ExcelWriter(path, engine="openpyxl") as writer:
                    for ds, values in self.last_results.items():
                        name = re.sub(r"[\\/*?:\[\]]", "_", ds)[:31]
                        pd.DataFrame(values).to_excel(writer, sheet_name=name or "Results", index=False)
            self.status.set(f"Exported: {path}")
        except Exception as exc:
            messagebox.showerror("Export error", str(exc))


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
