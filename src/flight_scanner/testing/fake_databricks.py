"""A stand-in for a Databricks workspace behind `DatabricksLakehouse`'s HTTP transport.

    databricks = FakeDatabricks(admin_db, work_dir)
    DatabricksLakehouse(FakeDatabricks.HOST, "token", job_id=1, warehouse_id="w",
                        transport=databricks, sleep=lambda s: None)
    databricks.uploaded        # [(export_date, file name)] put on the volume
    databricks.over_quota()    # Free Edition's fair-use quota is spent: runs fail with a quota
    databricks.go_down()       # every request answers 503
    databricks.recover()

It answers the Files API (uploads kept in memory), Jobs API run-now / runs/get and the SQL
Statement Execution API (`SELECT * FROM <catalog>.gold.<table>`, JSON_ARRAY). run-now runs the
analytics job the way the workspace would, but on Postgres: the uploaded Parquet files are loaded
into a scratch database as the silver tables (same names as on verda), then the shared dbt models
(`LAKEHOUSE_SELECTOR`) are built there at the job's `as_of` and their tables become the gold rows.
The bronze append and COPY INTO are not simulated.
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import uuid
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import psycopg
import pyarrow as pa
import pyarrow.parquet as pq

from flight_scanner.db import DbSettings, connect
from flight_scanner.lakehouse.base import GOLD_TABLES
from flight_scanner.pipeline import dbt as dbt_files
from flight_scanner.sources.polite_http import HttpResponse

# the dbt models the Databricks job builds (databricks/databricks.yml): baseline_observations,
# baselines, backtest_deals
LAKEHOUSE_SELECTOR = "tag:lakehouse"
QUOTA_MESSAGE = (
    "Run failed: the workspace exceeded its fair-use compute quota for today (QUOTA_EXCEEDED)"
)


def _pg_type(t: pa.DataType) -> str:
    if pa.types.is_decimal(t):
        return f"numeric({t.precision}, {t.scale})"
    if pa.types.is_timestamp(t):
        return "timestamptz" if t.tz else "timestamp"
    if pa.types.is_date(t):
        return "date"
    if pa.types.is_int32(t):
        return "integer"
    if pa.types.is_integer(t):
        return "bigint"
    if pa.types.is_floating(t):
        return "double precision"
    if pa.types.is_boolean(t):
        return "boolean"
    return "text"


def _type_name(values: list) -> str:
    v = next((v for v in values if v is not None), None)
    if isinstance(v, bool):
        return "BOOLEAN"
    if isinstance(v, Decimal):
        return "DECIMAL"
    if isinstance(v, int):
        return "LONG"
    if isinstance(v, float):
        return "DOUBLE"
    if isinstance(v, datetime):
        return "TIMESTAMP"
    if isinstance(v, date):
        return "DATE"
    return "STRING"


def _cell(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, datetime | date):
        return v.isoformat()
    return str(v)


def _json(status: int, payload: dict) -> HttpResponse:
    return HttpResponse(status, {"Content-Type": "application/json"}, json.dumps(payload).encode())


class FakeDatabricks:
    HOST = "https://fake-workspace.cloud.databricks.com"

    def __init__(self, admin_db: DbSettings, work_dir: Path):
        self.admin_db = replace(admin_db, dbname="postgres")
        self.work_dir = Path(work_dir) / "fake-databricks"
        self.files: dict[str, bytes] = {}  # volume path -> bytes
        self.uploaded: list[tuple[str, str]] = []  # (export_date folder, file name)
        self.runs: dict[int, dict] = {}
        self.gold: dict[str, list[dict]] = {}
        self.chunks: dict[str, dict] = {}  # next_chunk_internal_link -> chunk
        self.mode = "ok"

    def over_quota(self) -> None:
        self.mode = "over_quota"

    def go_down(self) -> None:
        self.mode = "down"

    def recover(self) -> None:
        self.mode = "ok"

    # --- the transport ---------------------------------------------------------------------

    def __call__(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float
    ) -> HttpResponse:
        if self.mode == "down":
            return _json(503, {"error_code": "TEMPORARILY_UNAVAILABLE", "message": "down"})
        if not headers.get("Authorization", "").startswith("Bearer "):
            return _json(401, {"error_code": "UNAUTHENTICATED", "message": "no token"})
        parts = urlsplit(url)
        path = unquote(parts.path)
        if method == "PUT" and path.startswith("/api/2.0/fs/directories/"):
            return HttpResponse(204, {}, b"")
        if method == "PUT" and path.startswith("/api/2.0/fs/files/"):
            volume_path = path.removeprefix("/api/2.0/fs/files")
            self.files[volume_path] = body or b""
            folder, name = volume_path.rsplit("/", 2)[-2:]
            self.uploaded.append((folder, name))
            return HttpResponse(204, {}, b"")
        if method == "POST" and path == "/api/2.2/jobs/run-now":
            return self._run_now(json.loads(body or b"{}"))
        if method == "GET" and path == "/api/2.2/jobs/runs/get":
            run_id = int(parse_qs(parts.query)["run_id"][0])
            return _json(200, {"run_id": run_id, "state": self.runs[run_id]})
        if method == "POST" and path == "/api/2.0/sql/statements":
            return self._statement(json.loads(body or b"{}")["statement"])
        if method == "GET" and path in self.chunks:
            return _json(200, self.chunks[path])
        return _json(404, {"error_code": "ENDPOINT_NOT_FOUND", "message": f"{method} {path}"})

    def _run_now(self, request: dict) -> HttpResponse:
        run_id = len(self.runs) + 1
        params = request["job_parameters"]
        if self.mode == "over_quota":
            state = {"result_state": "FAILED", "state_message": QUOTA_MESSAGE}
        else:
            try:
                self.gold = self._job(
                    params["export_date"], datetime.fromisoformat(params["as_of"])
                )
                state = {"result_state": "SUCCESS", "state_message": ""}
            except subprocess.CalledProcessError as e:
                state = {"result_state": "FAILED", "state_message": (e.stdout or "")[-2000:]}
        self.runs[run_id] = {"life_cycle_state": "TERMINATED", **state}
        return _json(200, {"run_id": run_id, "number_in_job": run_id})

    def _statement(self, statement: str) -> HttpResponse:
        match = re.fullmatch(r"SELECT \* FROM \w+\.gold\.(\w+)", statement.strip())
        if not match or match.group(1) not in self.gold:
            return _json(
                200,
                {
                    "statement_id": uuid.uuid4().hex,
                    "status": {"state": "FAILED", "error": {"message": f"bad: {statement}"}},
                },
            )
        rows = self.gold[match.group(1)]
        names = list(rows[0].keys()) if rows else []
        columns = [
            {"name": n, "type_name": _type_name([r[n] for r in rows]), "position": i}
            for i, n in enumerate(names)
        ]
        # two chunks when there is more than one row, to exercise chunk links
        data = [[_cell(r[n]) for n in names] for r in rows]
        sid = uuid.uuid4().hex
        first: dict = {"chunk_index": 0, "data_array": data[:1]}
        if len(data) > 1:
            first["next_chunk_internal_link"] = f"/api/2.0/sql/statements/{sid}/result/chunks/1"
            self.chunks[first["next_chunk_internal_link"]] = {"data_array": data[1:]}
        return _json(
            200,
            {
                "statement_id": sid,
                "status": {"state": "SUCCEEDED"},
                "manifest": {"format": "JSON_ARRAY", "schema": {"columns": columns}},
                "result": first,
            },
        )

    # --- the job on Postgres ---------------------------------------------------------------

    def _job(self, export_date: str, as_of: datetime) -> dict[str, list[dict]]:
        files = {
            p.rsplit("/", 1)[1].removesuffix(".parquet"): data
            for p, data in self.files.items()
            if p.rsplit("/", 2)[-2] == export_date
        }
        name = f"lakehouse_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(self.admin_db.conninfo, autocommit=True) as admin:
            admin.execute(f'CREATE DATABASE "{name}"')
        db = replace(self.admin_db, dbname=name)
        try:
            with connect(db, autocommit=True) as conn:
                for relation, data in files.items():
                    _load(conn, relation, pq.read_table(io.BytesIO(data)))
            self._dbt_build(db, as_of)
            with connect(db) as conn:
                return {t: conn.execute(f"SELECT * FROM marts.{t}").fetchall() for t in GOLD_TABLES}
        finally:
            with psycopg.connect(self.admin_db.conninfo, autocommit=True) as admin:
                admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')

    def _dbt_build(self, db: DbSettings, as_of: datetime) -> None:
        profiles = dbt_files.write_profiles(db, self.work_dir / "profiles", threads=2)
        target = dbt_files.new_target_path(self.work_dir)
        with dbt_files.clock_env(as_of):
            subprocess.run(
                [
                    dbt_files.dbt_executable(),
                    "build",
                    "--quiet",
                    "--select",
                    LAKEHOUSE_SELECTOR,
                    "--exclude-resource-type",
                    "test",
                    "--project-dir",
                    str(dbt_files.DBT_PROJECT_DIR),
                    "--profiles-dir",
                    str(profiles),
                    "--target-path",
                    str(target),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        dbt_files.finish_target_path(target)


def _load(conn: psycopg.Connection, relation: str, table: pa.Table) -> None:
    """A silver table: the exported snapshot under the same schema.table as on verda."""
    schema, name = relation.split(".")
    conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    columns = ", ".join(f'"{f.name}" {_pg_type(f.type)}' for f in table.schema)
    conn.execute(f'CREATE TABLE "{schema}"."{name}" ({columns})')
    names = ", ".join(f'"{f.name}"' for f in table.schema)
    with conn.cursor() as cur, cur.copy(f'COPY "{schema}"."{name}" ({names}) FROM STDIN') as copy:
        for row in table.to_pylist():
            copy.write_row(tuple(row.values()))
