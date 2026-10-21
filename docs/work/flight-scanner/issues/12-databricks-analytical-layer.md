# 12: Databricks analytical layer

**Parent:** `docs/work/flight-scanner/spec.md`

**What to build:** The heavy analytics run in a lakehouse (ADR-0003). History and staging are exported daily to Databricks Free Edition, built into bronze/silver/gold tables, Baselines and backtests are recomputed there and written back as new Baseline versions. Alerts never depend on it.

**Blocked by:** 05, 11

**Status:** resolved

- [x] Daily export of history and staging as Parquet to a Unity Catalog volume.
- [x] Bronze, silver and gold tables built in Databricks.
- [x] Baseline recompute and backtest jobs run there using the shared, adapter-portable dbt models.
- [x] Results are written back to Postgres as new Baseline versions with method recorded.
- [x] When Databricks is unavailable or over quota, detection continues on the last published Baselines; seam-1 test simulates this.
- [x] Setup steps that need the owner (account, tokens) are documented.

## Comments

- Branch `ticket/12-databricks-analytical-layer`: daily Dagster job `lakehouse` exports staging/history (+ the app/ref tables the models read) as Parquet to a UC volume, a Databricks job (asset bundle in `databricks/`) loads bronze/silver and builds the `tag:lakehouse` dbt models into gold; Baselines come back as change-only versions in `analytics.baseline_versions` (method `databricks/...`) and `marts.effective_baselines` prefers them for detection for up to 7 days. Verified offline only (REST contract, dbt-databricks compile + SQL parse, seam-1 against `FakeDatabricks`); no real workspace was used.
