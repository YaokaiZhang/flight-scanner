"""The lakehouse interface: what the daily job hands an analytical engine and gets back."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

# gold tables the job reads back: the shared dbt models' outputs
GOLD_TABLES = ("baselines", "backtest_deals")


class LakehouseUnavailable(Exception):
    """The engine cannot serve today (outage, or Free Edition's fair-use quota is spent).
    Expected and harmless: detection keeps using the last published Baselines."""

    def __init__(self, reason: Literal["unavailable", "over_quota"], detail: str):
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


class LakehouseError(Exception):
    """Anything else (bad credentials, a failing job): the run is recorded as failed."""


@dataclass(frozen=True)
class ExportedTable:
    relation: str  # schema.table in Postgres, e.g. staging.stg_leg_prices
    path: Path  # the Parquet file
    rows: int

    @property
    def file_name(self) -> str:
        return self.path.name


@dataclass(frozen=True)
class Export:
    """One daily export: every table as one Parquet file, for `export_date` (Helsinki)."""

    as_of: datetime
    export_date: date
    tables: tuple[ExportedTable, ...]

    @property
    def rows(self) -> int:
        return sum(t.rows for t in self.tables)


@dataclass(frozen=True)
class LakehouseResult:
    remote_run_id: str
    gold: dict[str, list[dict[str, Any]]]  # GOLD_TABLES -> rows (Python values)


class Lakehouse(Protocol):
    name: str

    def run(self, export: Export) -> LakehouseResult:
        """Upload the export, run the analytics job at `export.as_of`, read the gold tables.
        Raises LakehouseUnavailable or LakehouseError."""
        ...
