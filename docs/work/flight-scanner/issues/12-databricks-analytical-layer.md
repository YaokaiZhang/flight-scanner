# 12: Databricks analytical layer

**Parent:** `docs/work/flight-scanner/spec.md`

**What to build:** The heavy analytics run in a lakehouse (ADR-0003). History and staging are exported daily to Databricks Free Edition, built into bronze/silver/gold tables, Baselines and backtests are recomputed there and written back as new Baseline versions. Alerts never depend on it.

**Blocked by:** 05, 11

**Status:** ready-for-agent

- [ ] Daily export of history and staging as Parquet to a Unity Catalog volume.
- [ ] Bronze, silver and gold tables built in Databricks.
- [ ] Baseline recompute and backtest jobs run there using the shared, adapter-portable dbt models.
- [ ] Results are written back to Postgres as new Baseline versions with method recorded.
- [ ] When Databricks is unavailable or over quota, detection continues on the last published Baselines; seam-1 test simulates this.
- [ ] Setup steps that need the owner (account, tokens) are documented.
