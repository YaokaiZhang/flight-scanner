# 10: Data-quality gates and the data-health page

**Parent:** `docs/work/flight-scanner/spec.md`

**What to build:** Bad data never causes false Alerts, and the owner can see whether to trust the system. Asset checks gate Deal detection per slice; a source outage doesn't stop the others; a data-health page shows freshness, coverage, backlog and Verification budget.

**Blocked by:** 05, 08, 09

**Status:** resolved

- [x] Asset checks: zero rows for a normally populated origin, source-wide price-level jump beyond a threshold, stale source data.
- [x] A failing check blocks Deal detection for the affected slice only, and is visible.
- [x] One source failing does not stop ingestion or Alerts from other sources.
- [x] Data-health page: per-source freshness and last success, coverage gaps (routes × months with no data), planner backlog and skipped tasks, Verification budget used, recent check failures.
- [x] Seam-1 tests: a zero-row scan blocks detection for that slice; a failing source leaves others alerting.
- [x] Seam-2 tests for the data-health endpoint.

## Comments

- Branch `ticket/10-data-quality-and-health`: checks (zero_rows per source+origin, price_jump and stale_data per source) run after ingestion as Dagster asset checks; failing slices are gated out of `marts.trip_prices`; `GET /data-health` and the Data health page show sources, coverage gaps, backlog, Verification budget and check failures.
