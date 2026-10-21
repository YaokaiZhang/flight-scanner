"""The analytical layer (ADR-0003): a daily export to Databricks, which rebuilds Baselines and
the backtest with the shared dbt models; its Baselines come back as new versions.

    lakehouse = build_lakehouse(settings)          # None unless FS_LAKEHOUSE=databricks
    run = run_daily(conn, lakehouse, work_dir, now)  # export -> run -> publish, recorded

Owner setup (workspace, volume, job, tokens): databricks/README.md.
"""

from __future__ import annotations

from flight_scanner.config import Settings
from flight_scanner.lakehouse.base import (
    Export,
    ExportedTable,
    Lakehouse,
    LakehouseError,
    LakehouseResult,
    LakehouseUnavailable,
)
from flight_scanner.lakehouse.databricks import DatabricksLakehouse
from flight_scanner.lakehouse.export import EXPORT_TABLES, export_parquet
from flight_scanner.lakehouse.job import LakehouseRun, latest_run, run_daily

__all__ = [
    "EXPORT_TABLES",
    "DatabricksLakehouse",
    "Export",
    "ExportedTable",
    "Lakehouse",
    "LakehouseError",
    "LakehouseResult",
    "LakehouseRun",
    "LakehouseUnavailable",
    "build_lakehouse",
    "export_parquet",
    "latest_run",
    "run_daily",
]

REQUIRED = (
    "DATABRICKS_HOST",
    "DATABRICKS_TOKEN",
    "FS_DATABRICKS_JOB_ID",
    "FS_DATABRICKS_WAREHOUSE_ID",
)


def build_lakehouse(settings: Settings) -> Lakehouse | None:
    """FS_LAKEHOUSE=databricks turns the daily job on (see .env.example); empty = off."""
    env = settings.env
    kind = env.get("FS_LAKEHOUSE", "").strip().lower()
    if not kind:
        return None
    if kind != "databricks":
        raise ValueError(f"unknown FS_LAKEHOUSE {kind!r} (expected 'databricks' or empty)")
    missing = [k for k in REQUIRED if not env.get(k)]
    if missing:
        raise ValueError(f"FS_LAKEHOUSE=databricks needs {', '.join(missing)}")
    catalog = env.get("FS_DATABRICKS_CATALOG") or "flight_scanner"
    return DatabricksLakehouse(
        host=env["DATABRICKS_HOST"],
        token=env["DATABRICKS_TOKEN"],
        job_id=int(env["FS_DATABRICKS_JOB_ID"]),
        warehouse_id=env["FS_DATABRICKS_WAREHOUSE_ID"],
        catalog=catalog,
        volume=env.get("FS_DATABRICKS_VOLUME") or f"/Volumes/{catalog}/bronze/exports",
        run_timeout_seconds=60 * float(env.get("FS_DATABRICKS_RUN_TIMEOUT_MINUTES") or "60"),
    )
