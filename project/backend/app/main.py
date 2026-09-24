import csv
import io
import os
import re
import time
from collections import defaultdict
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from openpyxl import Workbook, load_workbook
from psycopg import sql

from .db import conn, init_db, report_table
from .importer import (
    INPUT,
    SUPPORTED,
    _refresh_job,
    cancel_job,
    create_job,
    run_folder_job,
    run_import_job,
    update_upload_progress,
)

app = FastAPI(title="Multi-Vendor Network Inventory API", version="0.3.0")
origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/tabs")
def tabs():
    with conn() as c:
        return c.execute(
            """
            SELECT vendor, report, table_name, row_count AS count
            FROM report_catalog
            WHERE row_count > 0
            ORDER BY vendor, report
            """
        ).fetchall()


@app.get("/api/summary")
def summary():
    with conn() as c:
        total = c.execute("SELECT COALESCE(SUM(row_count),0) AS n FROM report_catalog").fetchone()["n"]
        files = c.execute("SELECT COUNT(*) AS n FROM imports WHERE status='IMPORTED'").fetchone()["n"]
        tab_count = c.execute("SELECT COUNT(*) AS n FROM report_catalog WHERE row_count > 0").fetchone()["n"]
    return {"records": total, "files": files, "tabs": tab_count}


@app.post("/api/upload")
async def upload(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    name = Path(file.filename or "upload.bin").name
    if Path(name).suffix.lower() not in SUPPORTED:
        raise HTTPException(400, "Only CSV/XLSX/XLSM/ZIP supported")
    INPUT.mkdir(parents=True, exist_ok=True)
    destination = INPUT / name
    total = int(file.size or 0)
    job_id = create_job("UPLOAD", name, total)
    received = 0
    last_reported = 0
    last_report_time = 0.0
    try:
        with destination.open("wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                received += len(chunk)
                now = time.monotonic()
                if received - last_reported >= 5 * 1024 * 1024 or now - last_report_time >= 1.0:
                    update_upload_progress(job_id, received)
                    last_reported, last_report_time = received, now
        update_upload_progress(job_id, received)
        _refresh_job(
            job_id,
            status="UPLOADED",
            bytes_received=received,
            bytes_total=total or received,
            message="Upload complete; processing started",
        )
        background_tasks.add_task(run_import_job, job_id, destination)
        return {
            "job_id": job_id,
            "file": name,
            "status": "UPLOADED",
            "bytes_total": total,
            "bytes_received": received,
        }
    except Exception as exc:
        _refresh_job(job_id, status="FAILED", message=str(exc))
        raise HTTPException(500, str(exc))


@app.post("/api/import")
def do_import(background_tasks: BackgroundTasks):
    job_id = create_job("FOLDER", "Input folder")
    background_tasks.add_task(run_folder_job, job_id)
    return {"job_id": job_id, "status": "QUEUED"}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    with conn() as c:
        job = c.execute("SELECT * FROM import_jobs WHERE id=%s", (job_id,)).fetchone()
        if not job:
            raise HTTPException(404, "Job not found")
        items = c.execute(
            """
            SELECT item_key,vendor,report,source_sheet,status,rows_imported,message,updated_at
            FROM import_job_items WHERE job_id=%s ORDER BY id
            """,
            (job_id,),
        ).fetchall()
    total = int(job["bytes_total"] or 0)
    received = int(job["bytes_received"] or 0)
    upload_percent = (
        100
        if total == 0 and job["status"] not in {"QUEUED", "UPLOADING"}
        else (min(100, round(received * 100 / total)) if total else 0)
    )
    item_total = len(items)
    item_done = sum(1 for item in items if item["status"] in {"COMPLETED", "SKIPPED"})
    processing_percent = round(item_done * 100 / item_total) if item_total else (100 if job["status"] == "COMPLETED" else 0)
    return {
        "job": job,
        "items": items,
        "upload_percent": upload_percent,
        "processing_percent": processing_percent,
        "reports_done": item_done,
        "reports_total": item_total,
    }


@app.get("/api/jobs")
def jobs(limit: int = 20):
    limit = max(1, min(limit, 100))
    with conn() as c:
        return c.execute("SELECT * FROM import_jobs ORDER BY created_at DESC LIMIT %s", (limit,)).fetchall()


@app.post("/api/jobs/{job_id}/cancel")
def cancel(job_id: str):
    with conn() as c:
        job = c.execute("SELECT status FROM import_jobs WHERE id=%s", (job_id,)).fetchone()
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] in {"COMPLETED", "FAILED", "CANCELLED"}:
        return {"job_id": job_id, "status": job["status"], "message": "Job already finished"}
    cancel_job(job_id)
    return {"job_id": job_id, "status": "CANCELLING"}


@app.get("/api/imports")
def import_history(limit: int = 100):
    """Every file the system has ever attempted to import, with the date/time it
    landed and what happened to it — imported, ignored (not on the approved list),
    cancelled, or errored."""
    limit = max(1, min(limit, 500))
    with conn() as c:
        rows = c.execute(
            """
            SELECT file_name, status, rows_imported, error, imported_at
            FROM imports
            ORDER BY imported_at DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    # Older rows (imported before this column existed) fall back to the stored key.
    for row in rows:
        if not row.get("file_name"):
            row["file_name"] = "(unknown file)"
    return rows


def _fetch_rows(c, table, row_ids):
    if not row_ids:
        return {}
    query = sql.SQL(
        "SELECT id,source_file,source_sheet,site_key,row_data FROM {} WHERE id = ANY(%s)"
    ).format(sql.Identifier(table))
    rows = c.execute(query, (row_ids,)).fetchall()
    return {int(row["id"]): row for row in rows}


def _terms_to_patterns(terms):
    return [f"%{t.strip().lower()}%" for t in terms if t and t.strip()]


def _search_counts_and_matches(c, patterns, limit):
    counts = c.execute(
        """
        SELECT vendor,report,table_name,COUNT(*) AS count
        FROM search_index
        WHERE searchable_text ILIKE ANY(%s)
        GROUP BY vendor,report,table_name
        ORDER BY vendor,report
        """,
        (patterns,),
    ).fetchall()
    matches = c.execute(
        """
        SELECT vendor,report,table_name,row_id,source_file,source_sheet,site_key
        FROM search_index
        WHERE searchable_text ILIKE ANY(%s)
        ORDER BY vendor,report,id
        LIMIT %s
        """,
        (patterns, limit),
    ).fetchall()
    return counts, matches


def _hydrate_results(c, matches):
    grouped = defaultdict(list)
    for match in matches:
        grouped[match["table_name"]].append(int(match["row_id"]))
    row_maps = {table: _fetch_rows(c, table, ids) for table, ids in grouped.items()}

    results = []
    for match in matches:
        row = row_maps.get(match["table_name"], {}).get(int(match["row_id"]))
        if not row:
            continue
        results.append(
            {
                "id": row["id"],
                "vendor": match["vendor"],
                "report": match["report"],
                "source_file": row["source_file"],
                "source_sheet": row["source_sheet"],
                "site_key": row["site_key"],
                "row_data": row["row_data"],
            }
        )
    return results


def _parse_bulk_terms(raw_text: str = "", upload_bytes: bytes = None, upload_name: str = ""):
    """Turn pasted text and/or an uploaded CSV/XLSX of site names into a clean,
    de-duplicated list of search terms. When a file is given, its first row is
    assumed to be a header and skipped; every other cell (any column) becomes a
    candidate term."""
    terms = []

    def add(value):
        v = str(value).strip() if value is not None else ""
        if v:
            terms.append(v)

    for chunk in re.split(r"[\n\r,;\t]+", raw_text or ""):
        add(chunk)

    if upload_bytes:
        ext = Path(upload_name or "").suffix.lower()
        if ext == ".csv":
            text = upload_bytes.decode("utf-8-sig", errors="ignore")
            rows = list(csv.reader(io.StringIO(text)))
            for row in rows[1:] if len(rows) > 1 else rows:
                for cell in row:
                    add(cell)
        elif ext in (".xlsx", ".xlsm"):
            workbook = load_workbook(io.BytesIO(upload_bytes), read_only=True, data_only=True)
            sheet = workbook.worksheets[0]
            for i, row in enumerate(sheet.iter_rows(values_only=True)):
                if i == 0:
                    continue  # header row
                for cell in row:
                    add(cell)
        else:
            raise HTTPException(400, "Unsupported file type — upload a CSV or XLSX list of sites")

    seen, unique = set(), []
    for t in terms:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            unique.append(t)

    if not unique:
        raise HTTPException(400, "No site names found — paste a list or upload a file")
    if len(unique) > 300:
        raise HTTPException(400, f"Too many sites at once ({len(unique)}) — split into batches of 300 or fewer")
    return unique


@app.get("/api/search")
def search(q: str, limit: int = 1000):
    query_text = q.strip()
    if not query_text:
        return {"query": "", "total": 0, "tabs": [], "results": []}
    limit = max(1, min(limit, 5000))
    patterns = _terms_to_patterns([query_text])
    with conn() as c:
        counts, matches = _search_counts_and_matches(c, patterns, limit)
        results = _hydrate_results(c, matches)
    return {
        "query": query_text,
        "total": sum(int(item["count"]) for item in counts),
        "tabs": counts,
        "results": results,
    }


@app.post("/api/search/bulk")
async def search_bulk(sites: str = Form(""), file: UploadFile = File(None), limit: int = 3000):
    """Search for many sites at once — paste a list and/or upload a CSV/XLSX of
    site names — and get every matching row across every vendor and report."""
    upload_bytes = await file.read() if file else None
    terms = _parse_bulk_terms(sites, upload_bytes, file.filename if file else "")
    patterns = _terms_to_patterns(terms)
    limit = max(1, min(limit, 5000))

    with conn() as c:
        counts, matches = _search_counts_and_matches(c, patterns, limit)
        results = _hydrate_results(c, matches)
        unmatched = [
            term
            for term, pattern in zip(terms, patterns)
            if not c.execute("SELECT 1 FROM search_index WHERE searchable_text ILIKE %s LIMIT 1", (pattern,)).fetchone()
        ]

    return {
        "query_terms": terms,
        "unmatched_terms": unmatched,
        "total": sum(int(item["count"]) for item in counts),
        "tabs": counts,
        "results": results,
    }


def _safe_sheet_name(name: str, used: set) -> str:
    """Excel sheet names: max 31 chars, no : \\ / ? * [ ], must be unique in the workbook."""
    cleaned = re.sub(r"[:\\/?*\[\]]", "-", str(name)).strip() or "Sheet"
    base = cleaned[:31]
    candidate, i = base, 1
    while candidate.lower() in used:
        suffix = f"~{i}"
        candidate = base[: 31 - len(suffix)] + suffix
        i += 1
    used.add(candidate.lower())
    return candidate


def _build_export_workbook(c, patterns):
    matches = c.execute(
        """
        SELECT vendor,report,table_name,row_id
        FROM search_index
        WHERE searchable_text ILIKE ANY(%s)
        ORDER BY vendor,report,id
        LIMIT 50000
        """,
        (patterns,),
    ).fetchall()
    grouped = defaultdict(list)
    for m in matches:
        grouped[(m["vendor"], m["report"], m["table_name"])].append(int(m["row_id"]))

    workbook = Workbook()
    workbook.remove(workbook.active)
    used_names = set()

    for (vendor, report, table), row_ids in grouped.items():
        rows = _fetch_rows(c, table, row_ids)
        ordered_rows = [rows[i] for i in row_ids if i in rows]
        if not ordered_rows:
            continue
        # Column order/names come straight from the source file's own header row.
        headers = list(ordered_rows[0]["row_data"].keys())
        sheet = workbook.create_sheet(_safe_sheet_name(f"{vendor} {report}", used_names))
        sheet.append(["Source file", "Source sheet"] + headers)
        for r in ordered_rows:
            data = r["row_data"] or {}
            sheet.append([r["source_file"], r["source_sheet"] or ""] + [data.get(h, "") for h in headers])

    if not workbook.sheetnames:
        workbook.create_sheet("No matches")
    return workbook


def _workbook_response(workbook, filename):
    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/search/export")
def search_export(q: str):
    query_text = q.strip()
    if not query_text:
        raise HTTPException(400, "Nothing to export — run a search first")
    patterns = _terms_to_patterns([query_text])
    with conn() as c:
        workbook = _build_export_workbook(c, patterns)
    safe_query = re.sub(r"[^A-Za-z0-9_-]+", "_", query_text)[:40] or "results"
    return _workbook_response(workbook, f"search_{safe_query}.xlsx")


@app.post("/api/search/bulk/export")
async def search_bulk_export(sites: str = Form(""), file: UploadFile = File(None)):
    upload_bytes = await file.read() if file else None
    terms = _parse_bulk_terms(sites, upload_bytes, file.filename if file else "")
    patterns = _terms_to_patterns(terms)
    with conn() as c:
        workbook = _build_export_workbook(c, patterns)
    return _workbook_response(workbook, f"bulk_search_{len(terms)}_sites.xlsx")


def _category_of(report: str) -> str:
    """Mirrors the frontend's categories.js classifier so the backend can filter
    exports the same way the UI groups Site/Cell/IP/MME inventory."""
    r = (report or "").lower()
    if re.search(r"\bs1\b", r) or "mme" in r:
        return "mme"
    if re.search(r"\bip\b", r) or "devip" in r or "vlan" in r:
        return "ip"
    if re.search(r"2g|3g|4g|5g|gsm|umts|lte|nr\b|fdd|tdd|tcu|cell", r):
        return "cell"
    # "NE" for Huawei/ZTE, and Ericsson's node-level dump report — all node/site records.
    if re.search(r"\bne\b", r) or "network dump audit" in r or "network_dump_audit" in r:
        return "site"
    return "other"


@app.get("/api/export/all")
def export_all(category: str = None):
    """Every report table with data, exported in one workbook — one sheet per
    vendor/report, using each report's own source column headers. Optionally
    scoped to a single inventory category (site/cell/ip/other)."""
    with conn() as c:
        tabs = c.execute(
            "SELECT vendor, report, table_name FROM report_catalog WHERE row_count > 0 ORDER BY vendor, report"
        ).fetchall()
        if category:
            tabs = [t for t in tabs if _category_of(t["report"]) == category]

        workbook = Workbook()
        workbook.remove(workbook.active)
        used_names = set()

        for t in tabs:
            rows = c.execute(
                sql.SQL(
                    "SELECT source_file, source_sheet, row_data FROM {} ORDER BY id LIMIT 500000"
                ).format(sql.Identifier(t["table_name"]))
            ).fetchall()
            if not rows:
                continue
            headers = list(rows[0]["row_data"].keys())
            sheet = workbook.create_sheet(_safe_sheet_name(f"{t['vendor']} {t['report']}", used_names))
            sheet.append(["Source file", "Source sheet"] + headers)
            for r in rows:
                data = r["row_data"] or {}
                sheet.append([r["source_file"], r["source_sheet"] or ""] + [data.get(h, "") for h in headers])

    if not workbook.sheetnames:
        workbook.create_sheet("No data")
    filename = f"network_inventory_export_{category or 'all'}.xlsx"
    return _workbook_response(workbook, filename)


@app.get("/api/report/{vendor}/{report:path}")
def report(vendor: str, report: str, offset: int = 0, limit: int = 100):
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    table = report_table(vendor, report)
    with conn() as c:
        catalog = c.execute(
            "SELECT table_name FROM report_catalog WHERE vendor=%s AND report=%s",
            (vendor, report),
        ).fetchone()
        if not catalog or catalog["table_name"] != table:
            raise HTTPException(404, "Report tab not found")
        total = c.execute(sql.SQL("SELECT COUNT(*) AS n FROM {} ").format(sql.Identifier(table))).fetchone()["n"]
        rows = c.execute(
            sql.SQL(
                "SELECT id,source_file,source_sheet,site_key,row_data FROM {} "
                "ORDER BY id OFFSET %s LIMIT %s"
            ).format(sql.Identifier(table)),
            (offset, limit),
        ).fetchall()
    return {"vendor": vendor, "report": report, "total": total, "results": rows}
