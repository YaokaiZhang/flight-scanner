# Analytical layer on Databricks Free Edition (ADR-0003)

The operational loop never waits for Databricks. Once a day the Dagster job
`lakehouse` (04:15 Helsinki; by hand: `python -m flight_scanner lakehouse`):

1. exports history and staging (plus the app/reference tables the shared dbt models read) as
   Parquet, one file per table: `flight_scanner.lakehouse.export.EXPORT_TABLES`;
2. uploads them to the Unity Catalog volume `/Volumes/<catalog>/bronze/exports/<export_date>/`;
3. runs the `flight-scanner-analytics` job: `sql/medallion.sql` loads **bronze** (every export,
   append-only) and **silver** (the latest export), then dbt builds the
   shared models tagged `lakehouse` (`baseline_observations`, `baselines`, `backtest_deals`)
   into **gold** at the run's `as_of`;
4. reads `gold.baselines` and `gold.backtest_deals` back through the SQL warehouse and writes them
   to Postgres: new Baseline versions in `analytics.baseline_versions` (change-only, method
   `databricks/<method>`), the backtest in `analytics.backtest_deals`, the run in
   `analytics.lakehouse_runs`.

Detection uses `marts.effective_baselines`: per tier and key, the latest published version while
it is at most 7 days old (dbt var `published_baseline_max_age_days`), else the Baselines
recomputes every scan. If Databricks is down or over its fair-use quota, the run is recorded as
`unavailable` / `over_quota` and nothing else changes.

## One-time setup (owner)

1. **Account.** Sign up for Databricks Free Edition (https://www.databricks.com/learn/free-edition).
   It comes with one workspace, Unity Catalog and a serverless SQL warehouse.
2. **Catalog and volume.** In the SQL editor:
   ```sql
   CREATE CATALOG IF NOT EXISTS flight_scanner;
   CREATE SCHEMA IF NOT EXISTS flight_scanner.bronze;
   CREATE VOLUME IF NOT EXISTS flight_scanner.bronze.exports;
   CREATE VOLUME IF NOT EXISTS flight_scanner.bronze.raw;  -- only for FS_RAW_ARCHIVE
   ```
   (Using another catalog name: also edit the volume paths in `sql/medallion.sql`.)
3. **Warehouse id.** SQL Warehouses -> your warehouse -> Connection details: the id is the last
   part of the HTTP path (`/sql/1.0/warehouses/<id>`).
4. **Deploy the job.** `scripts/start.sh` does this for you once steps 5 and 6 are done: `up`
   deploys the bundle (and redeploys it whenever `dbt/` or this folder changes), downloading
   the Databricks CLI if none is on PATH, and writes the job id into an empty
   `FS_DATABRICKS_JOB_ID`. `scripts/start.sh deploy-databricks` forces a deploy. By hand: install
   the CLI, then from this folder `databricks bundle deploy -t free --var warehouse_id=<id>`,
   and note the job id (Jobs & Pipelines -> flight-scanner-analytics -> Job details).
5. **Token.** Settings -> Developer -> Access tokens -> Generate new token (give it a lifetime
   and renew it before it expires). It needs to write the volume, run the job and use the
   warehouse; the token of the workspace owner can.
6. **env.** In `.env`:
   ```
   FS_LAKEHOUSE=databricks
   DATABRICKS_HOST=<workspace URL, e.g. dbc-1234abcd-5678.cloud.databricks.com>
   DATABRICKS_TOKEN=<token>
   FS_DATABRICKS_JOB_ID=<job id; left empty, start.sh fills it in>
   FS_DATABRICKS_WAREHOUSE_ID=<warehouse id>
   ```
   Restart the stack; run `docker compose exec dagster-daemon python -m flight_scanner lakehouse` once
   and check it prints `status='published'`.

Running the shared models against the workspace by hand: set `DATABRICKS_HOST`,
`DATABRICKS_HTTP_PATH` and `DATABRICKS_TOKEN`, then
`dbt build --project-dir dbt --profiles-dir dbt --target databricks --select tag:lakehouse --vars '{as_of: "2026-11-11T03:00:00+00:00"}'`.

## What is verified without a workspace

- The adapter's REST contract (`tests/seam3/test_databricks_contract.py`, documented shapes).
- Every dbt model compiles with dbt-databricks and parses as Databricks SQL, with no
  Postgres-only constructs (`tests/seam3/test_dbt_databricks_portability.py`).
- The whole job end to end against `FakeDatabricks`, which runs the uploaded Parquet through the
  same shared models on a scratch Postgres database (`tests/seam1/test_lakehouse.py`).

Not verified: a real deployment (bundle schema, COPY INTO, the dbt task's environment), how Free
Edition reports a spent quota (assumed: HTTP 429 or a message mentioning a quota), and results on
Spark SQL (decimal precision, timestamp handling) matching Postgres.
