"""The daily export: history and staging (plus what the shared models also read) as Parquet.

Each relation is one full snapshot file named `<schema>.<table>.parquet`. Column types follow
Postgres (`information_schema`): unconstrained numerics become decimal(38, 9).
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import psycopg
import pyarrow as pa
import pyarrow.parquet as pq

from flight_scanner.lakehouse.base import Export, ExportedTable

# What the lakehouse rebuilds Baselines and the backtest from: staging (Fare observations in EUR
# per adult), history (change-only price history) and the app/reference tables the shared dbt
# models read as sources. The bronze/silver SQL (databricks/sql/medallion.sql) lists the same.
EXPORT_TABLES = (
    "staging.stg_leg_prices",
    "staging.stg_round_trip_prices",
    "staging.stg_price_insights",
    "history.leg_price_history",
    "history.round_trip_price_history",
    "app.watch_slots",
    "app.quality_gates",  # trip_prices leaves gated slices out (ticket 10)
    "app.deals",
    "app.alerts",
    "ref.airports",
)

_FREE_NUMERIC = (38, 9)


def _arrow_type(data_type: str, precision: int | None, scale: int | None) -> pa.DataType:
    if data_type in ("text", "character varying", "character"):
        return pa.string()
    if data_type == "date":
        return pa.date32()
    if data_type == "timestamp with time zone":
        return pa.timestamp("us", tz="UTC")
    if data_type == "timestamp without time zone":
        return pa.timestamp("us")
    if data_type == "numeric":
        p, s = (precision, scale) if precision is not None else _FREE_NUMERIC
        return pa.decimal128(p, s or 0)
    if data_type in ("integer", "smallint"):
        return pa.int32()
    if data_type == "bigint":
        return pa.int64()
    if data_type == "double precision":
        return pa.float64()
    if data_type == "real":
        return pa.float32()
    if data_type == "boolean":
        return pa.bool_()
    return pa.string()  # jsonb, arrays, ...: as JSON text


def _value(v, t: pa.DataType):
    if v is None:
        return None
    if pa.types.is_decimal(t):
        return Decimal(v).quantize(Decimal(1).scaleb(-t.scale))
    if pa.types.is_string(t) and not isinstance(v, str):
        return json.dumps(v, default=str)
    return v


def export_table(conn: psycopg.Connection, relation: str, directory: Path) -> ExportedTable:
    schema, table = relation.split(".")
    columns = conn.execute(
        """SELECT column_name, data_type, numeric_precision, numeric_scale
           FROM information_schema.columns
           WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position""",
        (schema, table),
    ).fetchall()
    if not columns:
        raise LookupError(f"{relation} does not exist (has dbt run yet?)")
    fields = [
        pa.field(
            c["column_name"],
            _arrow_type(c["data_type"], c["numeric_precision"], c["numeric_scale"]),
        )
        for c in columns
    ]
    names = ", ".join(f'"{c["column_name"]}"' for c in columns)
    rows = conn.execute(f'SELECT {names} FROM "{schema}"."{table}"').fetchall()
    arrays = [pa.array([_value(r[f.name], f.type) for r in rows], type=f.type) for f in fields]
    path = directory / f"{relation}.parquet"
    pq.write_table(pa.Table.from_arrays(arrays, schema=pa.schema(fields)), path)
    return ExportedTable(relation=relation, path=path, rows=len(rows))


def export_parquet(
    conn: psycopg.Connection, directory: Path, as_of: datetime, export_date
) -> Export:
    """Write every EXPORT_TABLES relation to `directory` as Parquet, in one snapshot."""
    directory.mkdir(parents=True, exist_ok=True)
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        tables = tuple(export_table(conn, r, directory) for r in EXPORT_TABLES)
    return Export(as_of=as_of, export_date=export_date, tables=tables)
