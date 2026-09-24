import hashlib
import os
import re
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://inventory:change_me@localhost:5432/network_inventory",
).replace("postgresql+psycopg://", "postgresql://")


def _slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return text or "unknown"


def report_table(vendor: str, report: str) -> str:
    """Return a deterministic, safe physical table name for one vendor/report."""
    base = f"report_{_slug(vendor)}_{_slug(report)}"
    if len(base) <= 55:
        return base
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:8]
    return f"{base[:46]}_{digest}"


@contextmanager
def conn():
    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as connection:
        yield connection


def init_db():
    with conn() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(78123456)")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS report_catalog (
              vendor TEXT NOT NULL,
              report TEXT NOT NULL,
              table_name TEXT PRIMARY KEY,
              row_count BIGINT NOT NULL DEFAULT 0,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              UNIQUE(vendor, report)
            );

            CREATE TABLE IF NOT EXISTS search_index (
              id BIGSERIAL PRIMARY KEY,
              vendor TEXT NOT NULL,
              report TEXT NOT NULL,
              table_name TEXT NOT NULL,
              row_id BIGINT NOT NULL,
              source_file TEXT NOT NULL,
              source_sheet TEXT,
              site_key TEXT,
              searchable_text TEXT NOT NULL,
              imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              UNIQUE(table_name, row_id)
            );
            CREATE INDEX IF NOT EXISTS idx_search_vendor_report
              ON search_index(vendor, report);
            CREATE INDEX IF NOT EXISTS idx_search_report
              ON search_index(report);
            CREATE INDEX IF NOT EXISTS idx_search_site_key
              ON search_index(site_key);
            CREATE INDEX IF NOT EXISTS idx_search_text_lower
              ON search_index(searchable_text);

            CREATE TABLE IF NOT EXISTS imports (
              id BIGSERIAL PRIMARY KEY,
              source_file TEXT UNIQUE NOT NULL,
              file_name TEXT,
              status TEXT NOT NULL,
              rows_imported INTEGER DEFAULT 0,
              error TEXT,
              imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            ALTER TABLE imports ADD COLUMN IF NOT EXISTS file_name TEXT;
            CREATE INDEX IF NOT EXISTS idx_imports_imported_at ON imports(imported_at DESC);

            CREATE TABLE IF NOT EXISTS import_jobs (
              id TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              file_name TEXT,
              status TEXT NOT NULL,
              bytes_received BIGINT NOT NULL DEFAULT 0,
              bytes_total BIGINT NOT NULL DEFAULT 0,
              rows_imported BIGINT NOT NULL DEFAULT 0,
              message TEXT,
              cancel_requested BOOLEAN NOT NULL DEFAULT false,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            ALTER TABLE import_jobs ADD COLUMN IF NOT EXISTS cancel_requested BOOLEAN NOT NULL DEFAULT false;

            CREATE TABLE IF NOT EXISTS import_job_items (
              id BIGSERIAL PRIMARY KEY,
              job_id TEXT NOT NULL REFERENCES import_jobs(id) ON DELETE CASCADE,
              item_key TEXT NOT NULL,
              vendor TEXT,
              report TEXT,
              source_sheet TEXT,
              status TEXT NOT NULL,
              rows_imported BIGINT NOT NULL DEFAULT 0,
              message TEXT,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              UNIQUE(job_id, item_key)
            );
            CREATE INDEX IF NOT EXISTS idx_job_items_job
              ON import_job_items(job_id, id);
            """
        )
        connection.commit()


def ensure_report_table(vendor: str, report: str) -> str:
    """Create/register one physical table and return its safe name."""
    table = report_table(vendor, report)
    with conn() as connection:
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS \"{table}\" (
              id BIGSERIAL PRIMARY KEY,
              source_file TEXT NOT NULL,
              source_sheet TEXT,
              site_key TEXT,
              searchable_text TEXT NOT NULL,
              row_data JSONB NOT NULL,
              imported_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        connection.execute(
            f'CREATE INDEX IF NOT EXISTS "idx_{table}_site" ON "{table}"(site_key)'
        )
        connection.execute(
            f'CREATE INDEX IF NOT EXISTS "idx_{table}_search" ON "{table}"(searchable_text)'
        )
        connection.execute(
            """
            INSERT INTO report_catalog(vendor, report, table_name)
            VALUES (%s, %s, %s)
            ON CONFLICT(vendor, report) DO UPDATE SET
              table_name=EXCLUDED.table_name,
              updated_at=now()
            """,
            (vendor, report, table),
        )
        connection.commit()
    return table
