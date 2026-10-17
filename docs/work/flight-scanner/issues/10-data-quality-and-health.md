# 10: Data-quality gates and the data-health page

**Parent:** `docs/work/flight-scanner/spec.md`

**What to build:** Bad data never causes false Alerts, and the owner can see whether to trust the system. Asset checks gate Deal detection per slice; a source outage doesn't stop the others; a data-health page shows freshness, coverage, backlog and Verification budget.

**Blocked by:** 05, 08, 09

**Status:** ready-for-agent

- [ ] Asset checks: zero rows for a normally populated origin, source-wide price-level jump beyond a threshold, stale source data.
- [ ] A failing check blocks Deal detection for the affected slice only, and is visible.
- [ ] One source failing does not stop ingestion or Alerts from other sources.
- [ ] Data-health page: per-source freshness and last success, coverage gaps (routes × months with no data), planner backlog and skipped tasks, Verification budget used, recent check failures.
- [ ] Seam-1 tests: a zero-row scan blocks detection for that slice; a failing source leaves others alerting.
- [ ] Seam-2 tests for the data-health endpoint.
