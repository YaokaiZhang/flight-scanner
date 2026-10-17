# 14: Deal context

**Parent:** `docs/work/flight-scanner/spec.md`

**What to build:** Alerts can explain why a fare might be cheap. An optional web-research agent adds a short Deal context line (sale, new route, off-season) to Alerts, never used as a price source and never delaying an Alert by more than 60 seconds.

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] Optional, enabled by configuration; the system runs fully without it.
- [ ] Produces a short Deal context string per Deal from web research.
- [ ] Alert delivery waits at most 60 s for it; if late, the Alert is sent without it.
- [ ] Deal context is shown in the Deals feed when present.
- [ ] Seam-1 test with a fake researcher covers both on-time and timed-out paths.
