import json
import os
import uuid
from pathlib import Path

from psycopg import sql

from .db import conn, ensure_report_table, init_db, report_table
from .parser import classify, filter_sheet, iter_sources, source_is_recognized, row_meta


class ImportCancelled(Exception):
    """Raised internally when a running job has been cancelled from the UI."""

INPUT = Path(os.getenv("INPUT_DIR", "/data/input"))
ARCHIVE = INPUT.parent / "archive"
SUPPORTED = {".csv", ".xlsx", ".xlsm", ".zip"}
TERMINAL = {"COMPLETED", "FAILED", "SKIPPED", "CANCELLED"}


def _now_job(job_id, **fields):
    if not fields:
        return
    assignments, params = [], []
    for key, value in fields.items():
        if value == "now()":
            assignments.append(f"{key}=now()")
        else:
            assignments.append(f"{key}=%s")
            params.append(value)
    params.append(job_id)
    with conn() as c:
        c.execute(f"UPDATE import_jobs SET {', '.join(assignments)} WHERE id=%s", params)
        c.commit()


def create_job(kind, file_name="", bytes_total=0):
    job_id = str(uuid.uuid4())
    init_db()
    with conn() as c:
        c.execute(
            "INSERT INTO import_jobs(id,kind,file_name,status,bytes_total) VALUES (%s,%s,%s,%s,%s)",
            (job_id, kind, file_name, "QUEUED", int(bytes_total or 0)),
        )
        c.commit()
    return job_id


def _upsert_item(job_id, item_key, vendor, report, source_sheet, status, rows=0, message=""):
    with conn() as c:
        c.execute(
            """
            INSERT INTO import_job_items(job_id,item_key,vendor,report,source_sheet,status,rows_imported,message)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(job_id,item_key) DO UPDATE SET
              vendor=EXCLUDED.vendor, report=EXCLUDED.report, source_sheet=EXCLUDED.source_sheet,
              status=EXCLUDED.status, rows_imported=EXCLUDED.rows_imported,
              message=EXCLUDED.message, updated_at=now()
            """,
            (job_id, item_key, vendor, report, source_sheet or "", status, int(rows), message or ""),
        )
        c.commit()


def _refresh_job(job_id, rows_delta=0, **fields):
    if rows_delta:
        fields["rows_imported"] = f"rows_imported+{int(rows_delta)}"
    assignments, params = [], []
    for key, value in fields.items():
        if isinstance(value, str) and value.startswith("rows_imported+"):
            assignments.append(f"rows_imported={value}")
        elif value == "now()":
            assignments.append(f"{key}=now()")
        else:
            assignments.append(f"{key}=%s")
            params.append(value)
    if not assignments:
        return
    assignments.append("updated_at=now()")
    params.append(job_id)
    with conn() as c:
        c.execute(f"UPDATE import_jobs SET {', '.join(assignments)} WHERE id=%s", params)
        c.commit()


def _job_item_counts(job_id):
    with conn() as c:
        return c.execute(
            """
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE status IN ('COMPLETED','SKIPPED')) AS done,
                   COUNT(*) FILTER (WHERE status='FAILED') AS failed
            FROM import_job_items WHERE job_id=%s
            """,
            (job_id,),
        ).fetchone()


def complete_job(job_id, status="COMPLETED", message=""):
    counts = _job_item_counts(job_id)
    final_status = "FAILED" if counts["failed"] else status
    _refresh_job(
        job_id,
        status=final_status,
        message=message or (f"{counts['done']} report(s) completed" if counts["total"] else "Done"),
    )


def fail_job(job_id, message):
    _refresh_job(job_id, status="FAILED", message=str(message))


def update_upload_progress(job_id, received):
    _refresh_job(job_id, bytes_received=int(received), status="UPLOADING")


def cancel_job(job_id):
    """Flag a running job for cancellation. The worker checks this between files
    and between row batches, and stops at the next checkpoint — rows already
    committed to the database stay as they are."""
    with conn() as c:
        c.execute(
            "UPDATE import_jobs SET cancel_requested=true, message='Cancelling…', updated_at=now() "
            "WHERE id=%s AND status NOT IN ('COMPLETED','FAILED','CANCELLED')",
            (job_id,),
        )
        c.commit()


def _is_cancelled(job_id):
    if not job_id:
        return False
    with conn() as c:
        row = c.execute("SELECT cancel_requested FROM import_jobs WHERE id=%s", (job_id,)).fetchone()
    return bool(row and row["cancel_requested"])


def _insert_batch(table, batch):
    """Insert report rows and the corresponding lightweight search rows atomically."""
    if not batch:
        return 0
    value_sql = ",".join(["(%s,%s,%s,%s,%s::jsonb)"] * len(batch))
    params = []
    for source_file, source_sheet, site_key, searchable_text, row_json in batch:
        params.extend([source_file, source_sheet, site_key, searchable_text, row_json])

    with conn() as c:
        with c.cursor() as cur:
            insert = sql.SQL(
                'INSERT INTO {}(source_file,source_sheet,site_key,searchable_text,row_data) '
                'VALUES {} RETURNING id'
            ).format(sql.Identifier(table), sql.SQL(value_sql))
            cur.execute(insert, params)
            ids = [int(row["id"]) for row in cur.fetchall()]
            search_rows = [
                (table, row_id, source_file, source_sheet, site_key, searchable_text)
                for row_id, (source_file, source_sheet, site_key, searchable_text, _row_json) in zip(ids, batch)
            ]
            cur.executemany(
                """
                INSERT INTO search_index(table_name,row_id,vendor,report,source_file,source_sheet,site_key,searchable_text)
                SELECT %s, %s, catalog.vendor, catalog.report, %s, %s, %s, %s
                FROM report_catalog catalog WHERE catalog.table_name=%s
                ON CONFLICT(table_name,row_id) DO NOTHING
                """,
                [
                    (table, row_id, source_file, source_sheet, site_key, searchable_text, table)
                    for row_id, source_file, source_sheet, site_key, searchable_text in [
                        (row_id, source_file, source_sheet, site_key, searchable_text)
                        for row_id, (source_file, source_sheet, site_key, searchable_text, _row_json) in zip(ids, batch)
                    ]
                ],
            )
            cur.execute(
                "UPDATE report_catalog SET row_count=row_count+%s,updated_at=now() WHERE table_name=%s",
                (len(ids), table),
            )
        c.commit()
    return len(ids)


def import_file(path: Path, job_id=None):
    init_db()
    path = Path(path)
    key = str(path.resolve()) + "|" + str(path.stat().st_mtime_ns)
    if job_id:
        _refresh_job(job_id, status="PROCESSING", message=f"Processing {path.name}")
    with conn() as c:
        old = c.execute(
            "SELECT id FROM imports WHERE source_file=%s AND status=%s", (key, "IMPORTED")
        ).fetchone()
    if old:
        if job_id:
            _upsert_item(job_id, path.name, "—", "—", "", "SKIPPED", 0, "Already imported")
        return {"file": path.name, "status": "SKIPPED", "rows": 0}

    # A standalone (non-ZIP) upload that isn't on the approved file-name list is
    # skipped outright, with a clear reason recorded in the job and the import log,
    # rather than silently doing nothing.
    if path.suffix.lower() != ".zip" and not source_is_recognized(path.name):
        if job_id:
            _upsert_item(job_id, path.name, "—", "—", "", "SKIPPED", 0, "File name not on the approved import list")
        with conn() as c:
            c.execute(
                """
                INSERT INTO imports(source_file,file_name,status,rows_imported,error)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT(source_file) DO UPDATE SET
                  file_name=EXCLUDED.file_name,status=EXCLUDED.status,
                  rows_imported=EXCLUDED.rows_imported,error=EXCLUDED.error,imported_at=now()
                """,
                (key, path.name, "IGNORED", 0, "File name not on the approved import list"),
            )
            c.commit()
        return {"file": path.name, "status": "IGNORED", "rows": 0}

    file_rows = 0
    current_items = set()
    try:
        for source, sheet, rows in iter_sources(path):
            if _is_cancelled(job_id):
                raise ImportCancelled()
            vendor, report = classify(source, sheet)
            if not filter_sheet(vendor, report, source, sheet):
                continue
            table = ensure_report_table(vendor, report)
            item_key = f"{source}|{sheet}"
            current_items.add(item_key)
            if job_id:
                _upsert_item(job_id, item_key, vendor, report, sheet, "PROCESSING")
            batch = []
            item_rows = 0
            for row in rows:
                _site, searchable = row_meta(row)
                batch.append((source, sheet or "", _site, searchable, json.dumps(row, ensure_ascii=False)))
                if len(batch) >= 500:
                    if _is_cancelled(job_id):
                        raise ImportCancelled()
                    inserted = _insert_batch(table, batch)
                    file_rows += inserted
                    item_rows += inserted
                    if job_id:
                        _refresh_job(job_id, rows_delta=inserted, message=f"Loaded {vendor} / {report}")
                    batch = []
            if batch:
                inserted = _insert_batch(table, batch)
                file_rows += inserted
                item_rows += inserted
                if job_id:
                    _refresh_job(job_id, rows_delta=inserted, message=f"Loaded {vendor} / {report}")
            if job_id:
                _upsert_item(job_id, item_key, vendor, report, sheet, "COMPLETED", item_rows)

        with conn() as c:
            c.execute(
                """
                INSERT INTO imports(source_file,file_name,status,rows_imported)
                VALUES (%s,%s,%s,%s)
                ON CONFLICT(source_file) DO UPDATE SET
                  file_name=EXCLUDED.file_name,status=EXCLUDED.status,rows_imported=EXCLUDED.rows_imported,
                  error=NULL,imported_at=now()
                """,
                (key, path.name, "IMPORTED", file_rows),
            )
            c.commit()
        return {"file": path.name, "status": "IMPORTED", "rows": file_rows}
    except ImportCancelled:
        with conn() as c:
            c.execute(
                """
                INSERT INTO imports(source_file,file_name,status,rows_imported,error)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT(source_file) DO UPDATE SET
                  file_name=EXCLUDED.file_name,status=EXCLUDED.status,rows_imported=EXCLUDED.rows_imported,
                  error=EXCLUDED.error,imported_at=now()
                """,
                (key, path.name, "CANCELLED", file_rows, "Cancelled by user"),
            )
            c.commit()
        raise
    except Exception as exc:
        if job_id:
            fail_job(job_id, exc)
        with conn() as c:
            c.execute(
                """
                INSERT INTO imports(source_file,file_name,status,error) VALUES (%s,%s,%s,%s)
                ON CONFLICT(source_file) DO UPDATE SET
                  file_name=EXCLUDED.file_name,status=EXCLUDED.status,error=EXCLUDED.error,imported_at=now()
                """,
                (key, path.name, "ERROR", str(exc)),
            )
            c.commit()
        raise


def run_import_job(job_id, path):
    try:
        _refresh_job(job_id, status="PROCESSING", message=f"Processing {Path(path).name}")
        result = import_file(Path(path), job_id)
        if result["status"] == "IGNORED":
            _refresh_job(job_id, status="COMPLETED", message="File name not on the approved import list — nothing imported")
        else:
            complete_job(job_id, "COMPLETED", f"{result['file']} processed")
    except ImportCancelled:
        _refresh_job(job_id, status="CANCELLED", message="Import cancelled")
    except Exception as exc:
        fail_job(job_id, exc)


def run_folder_job(job_id):
    try:
        INPUT.mkdir(parents=True, exist_ok=True)
        paths = [
            p for p in sorted(INPUT.iterdir())
            if p.is_file() and p.suffix.lower() in SUPPORTED
        ]
        total_bytes = sum(p.stat().st_size for p in paths)
        _refresh_job(job_id, status="PROCESSING", bytes_total=total_bytes, message=f"Found {len(paths)} file(s)")
        for path in paths:
            if _is_cancelled(job_id):
                raise ImportCancelled()
            import_file(path, job_id)
        complete_job(job_id, "COMPLETED", "Input folder import complete")
    except ImportCancelled:
        _refresh_job(job_id, status="CANCELLED", message="Import cancelled")
    except Exception as exc:
        fail_job(job_id, exc)


def import_folder():
    INPUT.mkdir(parents=True, exist_ok=True)
    results = []
    for p in sorted(INPUT.iterdir()):
        if p.is_file() and p.suffix.lower() in SUPPORTED:
            try:
                results.append(import_file(p))
            except Exception as exc:
                results.append({"file": p.name, "status": "ERROR", "error": str(exc)})
    return results
