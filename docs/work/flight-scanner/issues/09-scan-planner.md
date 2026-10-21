# 09: Scan planner

**Parent:** `docs/work/flight-scanner/spec.md`

**What to build:** Limited source budgets are spent where Deals are most likely. Active Watches turn into a de-duplicated set of scan tasks per source, shared across overlapping Watches and prioritised; budgets are never exceeded and skipped tasks are visible.

**Blocked by:** 02, 03

**Status:** resolved

- [x] Overlapping Watches produce one shared scan task per (source, origin, destination or wildcard, month).
- [x] Tasks ranked by proximity of departure, recent volatility, distance of best price from a Deal, and time since last scan.
- [x] Each source's rate limit and quota is never exceeded; tasks over budget are recorded as skipped.
- [x] Paused and expired Watches generate no tasks.
- [x] Skipped tasks are exposed via the API.
- [x] Seam-1 tests: two overlapping Watches share tasks; a tight budget schedules the highest-priority tasks and records the rest as skipped.

## Comments

- Branch `ticket/09-scan-planner`: `scan_planner` module (shared, ranked tasks per source, wildcard
  collapse for wide Watches, round-trip-aware Demand, per-run/per-day budgets with skipped tasks
  recorded) + `GET /scan-tasks`; seam-1 tests in `tests/seam1/test_scan_planner.py`.
