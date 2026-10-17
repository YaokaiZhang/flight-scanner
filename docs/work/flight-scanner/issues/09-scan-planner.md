# 09: Scan planner

**Parent:** `docs/work/flight-scanner/spec.md`

**What to build:** Limited source budgets are spent where Deals are most likely. Active Watches turn into a de-duplicated set of scan tasks per source, shared across overlapping Watches and prioritised; budgets are never exceeded and skipped tasks are visible.

**Blocked by:** 02, 03

**Status:** ready-for-agent

- [ ] Overlapping Watches produce one shared scan task per (source, origin, destination or wildcard, month).
- [ ] Tasks ranked by proximity of departure, recent volatility, distance of best price from a Deal, and time since last scan.
- [ ] Each source's rate limit and quota is never exceeded; tasks over budget are recorded as skipped.
- [ ] Paused and expired Watches generate no tasks.
- [ ] Skipped tasks are exposed via the API.
- [ ] Seam-1 tests: two overlapping Watches share tasks; a tight budget schedules the highest-priority tasks and records the rest as skipped.
