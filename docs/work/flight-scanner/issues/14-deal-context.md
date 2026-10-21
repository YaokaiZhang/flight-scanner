# 14: Deal context

**Parent:** `docs/work/flight-scanner/spec.md`

**What to build:** Alerts can explain why a fare might be cheap. An optional web-research agent adds a short Deal context line (sale, new route, off-season) to Alerts, never used as a price source and never delaying an Alert by more than 60 seconds.

**Blocked by:** 06

**Status:** resolved

- [x] Optional, enabled by configuration; the system runs fully without it.
- [x] Produces a short Deal context string per Deal from web research.
- [x] Alert delivery waits at most 60 s for it; if late, the Alert is sent without it.
- [x] Deal context is shown in the Deals feed when present.
- [x] Seam-1 test with a fake researcher covers both on-time and timed-out paths.

## Comments

- Branch `ticket/14-deal-context`: researcher interface + Claude web-search agent (FS_DEAL_CONTEXT=claude, off by default), `app/deal_context` asset with a 60 s wall-time cap before Alerts/Digests, "Why cheap?" line in Alerts and the Deals inspector; seam-1/2/3 tests with a fake researcher and canned API.
