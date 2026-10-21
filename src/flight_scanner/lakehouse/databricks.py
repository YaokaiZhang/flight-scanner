"""Databricks Free Edition as the lakehouse, over its REST APIs (stdlib HTTP, injectable).

One `run(export)`:
  1. uploads each Parquet file to the Unity Catalog volume (Files API):
     PUT /api/2.0/fs/files{volume}/{export_date}/{schema.table}.parquet
  2. starts the analytics job (Jobs API run-now, job parameters `as_of`, `export_date`): bronze
     (COPY INTO from the volume) -> silver (latest export) -> gold (the shared dbt models,
     `dbt build --select baseline_observations baselines backtest_deals`); see databricks/;
  3. polls the run until it terminates;
  4. reads the gold tables through a SQL warehouse (SQL Statement Execution API, JSON_ARRAY).

Errors: HTTP 429 or any answer mentioning a quota -> LakehouseUnavailable("over_quota");
network errors, 5xx (after retries) and a run that does not finish in time ->
LakehouseUnavailable("unavailable"); everything else (401/403, a failed job) -> LakehouseError.
The token goes only into the Authorization header.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import quote

from flight_scanner.lakehouse.base import (
    GOLD_TABLES,
    Export,
    LakehouseError,
    LakehouseResult,
    LakehouseUnavailable,
)
from flight_scanner.sources.polite_http import HttpResponse, Transport, urllib_transport

TERMINAL = {"TERMINATED", "SKIPPED", "INTERNAL_ERROR"}
_QUOTA = re.compile(r"quota|resource_exhausted|rate limit", re.IGNORECASE)


def _typed(value: str | None, type_name: str) -> Any:
    """A JSON_ARRAY cell (always a string) as a Python value of its column type."""
    if value is None:
        return None
    t = type_name.upper()
    if t == "DECIMAL":
        return Decimal(value)
    if t in ("LONG", "INT", "SHORT", "BYTE"):
        return int(value)
    if t in ("DOUBLE", "FLOAT"):
        return float(value)
    if t == "BOOLEAN":
        return value.lower() == "true"
    if t == "DATE":
        return date.fromisoformat(value)
    if t in ("TIMESTAMP", "TIMESTAMP_NTZ"):
        return datetime.fromisoformat(value)
    return value


class DatabricksLakehouse:
    name = "databricks"

    def __init__(
        self,
        host: str,
        token: str,
        job_id: int,
        warehouse_id: str,
        catalog: str = "flight_scanner",
        volume: str = "/Volumes/flight_scanner/bronze/exports",
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        poll_seconds: float = 30.0,
        run_timeout_seconds: float = 3600.0,
        max_retries: int = 2,
        request_timeout: float = 120.0,
    ):
        self.host = host.rstrip("/")
        if not self.host.startswith("http"):
            self.host = "https://" + self.host
        self.token = token
        self.job_id = job_id
        self.warehouse_id = warehouse_id
        self.catalog = catalog
        self.volume = volume.rstrip("/")
        self.transport = transport or urllib_transport
        self.sleep = sleep
        self.monotonic = monotonic
        self.poll_seconds = poll_seconds
        self.run_timeout_seconds = run_timeout_seconds
        self.max_retries = max_retries
        self.request_timeout = request_timeout

    # --- the job -------------------------------------------------------------------------

    def run(self, export: Export) -> LakehouseResult:
        folder = f"{self.volume}/{export.export_date.isoformat()}"
        self._call("PUT", f"/api/2.0/fs/directories{quote(folder)}")
        for t in export.tables:
            self._call(
                "PUT",
                f"/api/2.0/fs/files{quote(folder)}/{quote(t.file_name)}?overwrite=true",
                body=t.path.read_bytes(),
                content_type="application/octet-stream",
            )
        started = self._json(
            "POST",
            "/api/2.2/jobs/run-now",
            {
                "job_id": self.job_id,
                "job_parameters": {
                    "as_of": export.as_of.isoformat(),
                    "export_date": export.export_date.isoformat(),
                },
            },
        )
        run_id = str(started["run_id"])
        self._wait(run_id)
        gold = {t: self._select(f"SELECT * FROM {self.catalog}.gold.{t}") for t in GOLD_TABLES}
        return LakehouseResult(remote_run_id=run_id, gold=gold)

    def _wait(self, run_id: str) -> None:
        deadline = self.monotonic() + self.run_timeout_seconds
        while True:
            state = self._json("GET", f"/api/2.2/jobs/runs/get?run_id={run_id}")["state"]
            if state.get("life_cycle_state") in TERMINAL:
                break
            if self.monotonic() >= deadline:
                raise LakehouseUnavailable("unavailable", f"job run {run_id} did not finish")
            self.sleep(self.poll_seconds)
        if state.get("result_state") != "SUCCESS":
            message = state.get("state_message") or state.get("life_cycle_state")
            if _QUOTA.search(message or ""):
                raise LakehouseUnavailable("over_quota", message)
            raise LakehouseError(f"job run {run_id} {state.get('result_state')}: {message}")

    def _select(self, statement: str) -> list[dict[str, Any]]:
        answer = self._json(
            "POST",
            "/api/2.0/sql/statements",
            {
                "warehouse_id": self.warehouse_id,
                "statement": statement,
                "wait_timeout": "50s",
                "on_wait_timeout": "CONTINUE",
                "disposition": "INLINE",
                "format": "JSON_ARRAY",
            },
        )
        deadline = self.monotonic() + self.run_timeout_seconds
        while answer["status"]["state"] in ("PENDING", "RUNNING"):
            if self.monotonic() >= deadline:
                raise LakehouseUnavailable("unavailable", f"statement did not finish: {statement}")
            self.sleep(self.poll_seconds)
            answer = self._json("GET", f"/api/2.0/sql/statements/{answer['statement_id']}")
        status = answer["status"]
        if status["state"] != "SUCCEEDED":
            message = (status.get("error") or {}).get("message", status["state"])
            if _QUOTA.search(message):
                raise LakehouseUnavailable("over_quota", message)
            raise LakehouseError(f"{statement}: {message}")
        columns = [(c["name"], c["type_name"]) for c in answer["manifest"]["schema"]["columns"]]
        rows: list[dict[str, Any]] = []
        chunk = answer.get("result") or {}
        while True:
            for cells in chunk.get("data_array") or []:
                rows.append({n: _typed(v, t) for (n, t), v in zip(columns, cells, strict=True)})
            link = chunk.get("next_chunk_internal_link")
            if not link:
                return rows
            chunk = self._json("GET", link)

    # --- HTTP ----------------------------------------------------------------------------

    def _json(self, method: str, path: str, payload: dict | None = None) -> dict:
        body = json.dumps(payload).encode() if payload is not None else None
        resp = self._call(method, path, body=body, content_type="application/json")
        try:
            return json.loads(resp.body)
        except ValueError as e:
            raise LakehouseError(f"{method} {path}: not JSON") from e

    def _call(
        self, method: str, path: str, body: bytes | None = None, content_type: str | None = None
    ) -> HttpResponse:
        headers = {"Authorization": f"Bearer {self.token}"}
        if content_type and body is not None:
            headers["Content-Type"] = content_type
        url = self.host + path
        for attempt in range(self.max_retries + 1):
            last = attempt == self.max_retries
            try:
                resp = self.transport(method, url, headers, body, self.request_timeout)
            except OSError as e:
                if last:
                    raise LakehouseUnavailable("unavailable", f"{method} {path}: {e}") from e
            else:
                text = resp.body[:500].decode("utf-8", "replace")
                if resp.status == 429 or (resp.status >= 400 and _QUOTA.search(text)):
                    raise LakehouseUnavailable("over_quota", f"{resp.status} {text}")
                if resp.status < 400:
                    return resp
                if resp.status < 500:
                    raise LakehouseError(f"{method} {path}: {resp.status} {text}")
                if last:
                    raise LakehouseUnavailable("unavailable", f"{method} {path}: {resp.status}")
            self.sleep(2.0 * 2**attempt)
        raise AssertionError("unreachable")
