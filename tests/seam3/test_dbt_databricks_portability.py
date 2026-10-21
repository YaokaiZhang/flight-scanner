"""Seam 3: the shared dbt models are adapter-portable (ADR-0003).

The whole project is compiled with the dbt-databricks adapter (offline: no workspace here, see
`flight_scanner.testing.databricks_compile`), and every compiled model must parse as Databricks
SQL and be free of Postgres-only SQL. The models' behaviour is covered on Postgres by seam 1.
Not verified here: running them on a real SQL warehouse (types, numeric precision, timezones).
"""

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlglot

from flight_scanner.lakehouse import EXPORT_TABLES
from flight_scanner.testing.databricks_compile import compile_for_databricks

REPO = Path(__file__).parents[2]
POSTGRES_ONLY = {
    "a :: cast": r"::",
    "DISTINCT ON": r"\bdistinct\s+on\b",
    "AT TIME ZONE": r"\bat\s+time\s+zone\b",
    "now() / current clock (use as_of())": r"\bnow\s*\(|\bcurrent_(timestamp|date)\b",
    "interval literal": r"\binterval\s+'",
    "timestamptz": r"\btimestamptz\b|with time zone",
    "generate_series": r"\bgenerate_series\b",
}


@pytest.fixture(scope="module")
def compiled(tmp_path_factory) -> dict[str, str]:
    return compile_for_databricks(
        tmp_path_factory.mktemp("dbx"), datetime(2026, 11, 11, 3, tzinfo=UTC)
    )


def test_every_model_compiles_for_databricks(compiled):
    models = {p.stem for p in (REPO / "dbt" / "models").rglob("*.sql")}
    assert set(compiled) == models


def test_every_compiled_model_is_databricks_sql(compiled):
    for name, sql in compiled.items():
        sqlglot.parse(sql, read="databricks", error_level=sqlglot.ErrorLevel.RAISE)
        found = [what for what, rx in POSTGRES_ONLY.items() if re.search(rx, sql, re.I)]
        assert not found, f"{name}: {found}"


def test_on_databricks_models_read_silver_and_lakehouse_models_write_gold(compiled):
    # sources and staging/history relations are silver tables loaded from the daily export
    assert "`flight_scanner`.`silver`.`stg_leg_prices`" in compiled["baseline_observations"]
    assert "`flight_scanner`.`silver`.`watch_slots`" in compiled["baseline_observations"]
    assert "`flight_scanner`.`silver`.`deals`" in compiled["backtest_deals"]
    assert "`flight_scanner`.`gold`.`baseline_observations`" in compiled["baselines"]
    for sql in compiled.values():
        assert not re.search(r"`(staging|history|marts|app|ref|landing|analytics)`\.", sql)


def test_the_medallion_sql_loads_every_exported_table_into_silver():
    sql = (REPO / "databricks" / "sql" / "medallion.sql").read_text()
    for relation in EXPORT_TABLES:
        table = relation.split(".")[1]
        assert f"PATTERN = '*/{relation}.parquet'" in sql
        assert f"CREATE OR REPLACE TABLE silver.{table} AS" in sql
