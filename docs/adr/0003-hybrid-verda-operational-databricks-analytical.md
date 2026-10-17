# Operational loop on verda, analytical layer on Databricks Free Edition

Everything the owner depends on day-to-day — scan planning, ingestion, normalisation, Candidate/Deal detection, Verification, Alerts and the UI — runs on the single host `verda` (Docker Compose: Dagster, dbt, Postgres, FastAPI, Next.js). Heavy batch analytics — Baseline recomputation, backtests, seasonality analysis — run in Databricks Free Edition over a medallion copy of the data, and results are written back to Postgres. Databricks Free Edition restricts outbound internet and shuts compute off for the day when its fair-use quota is exceeded, so it must never sit on the alerting path: if it is unavailable, Alerts continue using the last published Baselines.

## Considered options

- **verda only** — free and simplest, but forgoes a lakehouse platform that is in high demand in the Nordic data-engineering market.
- **Azure + Databricks for everything** — ~€50–200+/month for always-on jobs and a SQL warehouse serving the UI, and Free Edition quotas make hourly scanning fragile.
- **Snowflake as the analytical layer** — technically equivalent for this role and well supported by dbt, but has no permanent free tier (30-day trial, then roughly $15–40/month for this workload).

## Consequences

- dbt models are kept adapter-portable (no vendor-specific SQL in shared models) so the same transformations run on Postgres and Databricks, and Snowflake remains a documented option.
